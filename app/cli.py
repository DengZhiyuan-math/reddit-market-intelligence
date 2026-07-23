"""Command-line interface for the Reddit Market Intelligence System."""

import json
import os
from datetime import UTC, datetime
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
import typer
from rich.console import Console
from rich.table import Table
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app.compliance.policies import AccessMode
from app.config import Settings
from app.db.base import Base
from app.db.import_registry import import_project_registry
from app.db.session import session_scope
from app.analysis.exporter import export_market_signals
from app.analysis.models import SignalExtractionRunSummary
from app.analysis.service import SignalExtractionServiceError, run_signal_extraction
from app.demo.models import DemoRunSummary
from app.demo.service import run_fixture_demo
from app.llm.exporter import export_review_queue
from app.llm.models import LlmReviewRunSummary
from app.llm.service import LlmReviewServiceError, run_llm_review
from app.projects.models import ProjectCreateInput, ResearchProject, RunConfig, StageRun, StageStatus
from app.projects.service import (
    ProjectNotFoundError,
    create_project,
    get_project_or_raise,
    record_stage_run,
)
from app.projects.store import ProjectRegistryStore
from app.processing.exporter import export_calibration_samples
from app.processing.models import FilteringRunSummary
from app.processing.service import ProcessingServiceError, run_filtering
from app.reddit.models import CollectionRunSummary
from app.reddit.service import (
    RedditCollectionServiceError,
    run_reddit_collection,
    validate_reddit_credentials,
)
from app.reports.exporter import export_report_evidence
from app.reports.models import ReportGenerationSummary
from app.reports.service import ReportGenerationServiceError, generate_market_report
from app.runtime.preflight import preflight_exit_code, run_preflight
from app.search.models import DiscoveryRunSummary
from app.search.service import DiscoveryServiceError, run_url_discovery
from app.sources.selection import CollectionSourceMode, SourceSelection, select_collection_source
from app.web_fallback.models import WebFallbackIngestionSummary
from app.web_fallback.service import WebFallbackServiceError, run_web_fallback_ingestion
from app.topic_planning.service import (
    TopicPlanningServiceError,
    generate_and_persist_topic_plan,
    generate_topic_plan_for_project,
    get_topic_plan,
    list_topic_plans,
    select_topic_plan,
)

app = typer.Typer(help="Reddit market intelligence pipeline.")
projects_app = typer.Typer(help="Create and inspect research projects.")
db_app = typer.Typer(help="Manage database migrations and status.")
plans_app = typer.Typer(help="Generate and inspect structured Reddit research plans.")
reddit_app = typer.Typer(help="Validate credentials and collect Reddit evidence.")
filtering_app = typer.Typer(help="Clean content and route relevance bands.")
llm_app = typer.Typer(help="Review ambiguous content with the LLM gateway.")
analysis_app = typer.Typer(help="Extract and inspect market signals.")
reports_app = typer.Typer(help="Generate reports and export report evidence.")
demo_app = typer.Typer(help="Run no-credential synthetic fixture demos.")
app.add_typer(projects_app, name="projects")
app.add_typer(db_app, name="db")
app.add_typer(plans_app, name="plans")
app.add_typer(reddit_app, name="reddit")
app.add_typer(filtering_app, name="filtering")
app.add_typer(llm_app, name="llm")
app.add_typer(analysis_app, name="analysis")
app.add_typer(reports_app, name="reports")
app.add_typer(demo_app, name="demo")

console = Console()
error_console = Console(stderr=True)

settings = Settings()
DEFAULT_REGISTRY_PATH = settings.project_registry_path
DEFAULT_RUN_LIMIT = settings.default_run_limit


def _alembic_config(database_url: str | None = None) -> Config:
    if database_url:
        os.environ["DATABASE_URL"] = database_url
    return Config("alembic.ini")


def _safe_database_url(database_url: str) -> str:
    return make_url(database_url).render_as_string(hide_password=True)


def _database_status(database_url: str) -> tuple[str | None, str | None]:
    engine = create_engine(database_url)
    script = ScriptDirectory.from_config(Config("alembic.ini"))
    with engine.connect() as connection:
        context = MigrationContext.configure(connection)
        current = context.get_current_revision()
    return current, script.get_current_head()


def _ensure_sqlite_parent(database_url: str) -> None:
    url = make_url(database_url)
    if url.drivername.startswith("sqlite") and url.database not in {None, "", ":memory:"}:
        Path(url.database).parent.mkdir(parents=True, exist_ok=True)


def _print_plan_summary(plan_result) -> None:
    table = Table(title=f"Research plan {plan_result.record.id}")
    table.add_column("Field")
    table.add_column("Value")
    table.add_row("plan_id", str(plan_result.record.id))
    table.add_row("selected", str(plan_result.record.selected))
    table.add_row("core_topic", plan_result.topic_plan.core_topic)
    table.add_row("primary_keywords", ", ".join(plan_result.topic_plan.primary_keywords[:5]))
    table.add_row("candidate_subreddits", ", ".join(plan_result.topic_plan.candidate_subreddits))
    if plan_result.search_query_count:
        table.add_row("search_queries", str(plan_result.search_query_count))
    console.print(table)


def _print_plan_json(plan_result) -> None:
    console.print_json(data=plan_result.topic_plan.model_dump(mode="json"))


def _print_collection_summary(summary: CollectionRunSummary) -> None:
    table = Table(title="Reddit collection summary")
    table.add_column("Metric")
    table.add_column("Value")
    for field_name in (
        "requested_queries",
        "processed_queries",
        "stored_posts",
        "stored_comments",
        "duplicate_posts_skipped",
        "duplicate_comments_skipped",
        "request_failures",
        "permanent_failures",
        "rate_limit_stops",
        "elapsed_ms",
    ):
        table.add_row(field_name, str(getattr(summary, field_name)))
    console.print(table)


def _print_discovery_summary(summary: DiscoveryRunSummary) -> None:
    table = Table(title="URL discovery summary")
    table.add_column("Field")
    table.add_column("Value")
    table.add_row("provider", summary.provider)
    table.add_row("query", summary.query)
    table.add_row("discovered", str(summary.discovered))
    table.add_row("stored", str(summary.stored))
    table.add_row("duplicates", str(summary.duplicates))
    table.add_row("dry_run", str(summary.dry_run))
    console.print(table)

    url_table = Table(title="Discovered URLs")
    url_table.add_column("URL")
    url_table.add_column("Title")
    url_table.add_column("Snippet")
    for discovered in summary.urls:
        url_table.add_row(discovered.url, discovered.title or "", discovered.snippet or "")
    console.print(url_table)
    for discovered in summary.urls:
        console.print(f"URL: {discovered.url}")


def _print_web_fallback_summary(summary: WebFallbackIngestionSummary) -> None:
    table = Table(title="Web fallback ingestion summary")
    table.add_column("Metric")
    table.add_column("Value")
    for field_name in (
        "candidates",
        "fetched",
        "stored_posts",
        "stored_comments",
        "duplicate_posts",
        "duplicate_comments",
        "excluded",
        "errors",
    ):
        table.add_row(field_name, str(getattr(summary, field_name)))
    console.print(table)


def _print_source_selection(selection: SourceSelection) -> None:
    table = Table(title="Collection source selection")
    table.add_column("Field")
    table.add_column("Value")
    table.add_row("mode", selection.mode.value)
    table.add_row("can_collect", str(selection.can_collect))
    table.add_row("api_available", str(selection.api_available))
    table.add_row("fallback_enabled", str(selection.fallback_enabled))
    table.add_row("reason_codes", ", ".join(selection.reason_codes) or "")
    table.add_row("risk_flags", ", ".join(selection.risk_flags) or "")
    table.add_row("message", selection.message)
    console.print(table)


def _print_filtering_summary(summary: FilteringRunSummary) -> None:
    table = Table(title="Filtering summary")
    table.add_column("Metric")
    table.add_column("Value")
    for field_name in (
        "raw_posts_processed",
        "raw_comments_processed",
        "content_items_created",
        "content_items_updated",
        "accepted",
        "rejected",
        "ambiguous",
        "embedded",
        "llm_review_required",
        "duplicate_text",
        "errors",
    ):
        table.add_row(field_name, str(getattr(summary, field_name)))
    console.print(table)


def _print_llm_review_summary(summary: LlmReviewRunSummary) -> None:
    table = Table(title="LLM review summary")
    table.add_column("Metric")
    table.add_column("Value")
    for field_name in (
        "reviewed",
        "relevant",
        "irrelevant",
        "failed",
        "skipped",
        "remaining",
        "errors",
    ):
        table.add_row(field_name, str(getattr(summary, field_name)))
    console.print(table)


def _print_signal_extraction_summary(summary: SignalExtractionRunSummary) -> None:
    table = Table(title="Market signal extraction summary")
    table.add_column("Metric")
    table.add_column("Value")
    for field_name in (
        "candidates",
        "extracted_signals",
        "abstained",
        "failed",
        "skipped_duplicates",
        "remaining",
        "errors",
    ):
        table.add_row(field_name, str(getattr(summary, field_name)))
    console.print(table)


def _print_report_generation_summary(summary: ReportGenerationSummary) -> None:
    table = Table(title="Report generation summary")
    table.add_column("Metric")
    table.add_column("Value")
    for field_name in (
        "market_signal_count",
        "report_path",
        "artifact_id",
        "warnings",
        "errors",
    ):
        value = getattr(summary, field_name)
        if isinstance(value, list):
            value = ", ".join(value)
        table.add_row(field_name, str(value or ""))
    console.print(table)


def _print_demo_summary(summary: DemoRunSummary) -> None:
    table = Table(title="Synthetic fixture demo summary")
    table.add_column("Metric")
    table.add_column("Value")
    for field_name in (
        "project_id",
        "run_id",
        "sample_count",
        "content_item_count",
        "market_signal_count",
        "report_path",
        "evidence_markdown_path",
        "evidence_csv_path",
        "market_signals_path",
        "summary_path",
        "warnings",
    ):
        value = getattr(summary, field_name)
        if isinstance(value, list):
            value = ", ".join(value)
        table.add_row(field_name, str(value or ""))
    console.print(table)


def _parse_access_mode(value: str) -> AccessMode:
    try:
        return AccessMode(value)
    except ValueError as exc:
        supported = ", ".join(mode.value for mode in AccessMode)
        raise typer.BadParameter(
            f"Unsupported access mode {value!r}. Supported values: {supported}."
        ) from exc


def _parse_stage_status(value: str) -> StageStatus:
    try:
        return StageStatus(value)
    except ValueError as exc:
        supported = ", ".join(status.value for status in StageStatus)
        raise typer.BadParameter(
            f"Unsupported stage status {value!r}. Supported values: {supported}."
        ) from exc


def _project_table(project: ResearchProject) -> Table:
    table = Table(title=f"Project {project.project_id}")
    table.add_column("Field")
    table.add_column("Value")
    table.add_row("project_id", str(project.project_id))
    table.add_row("slug", project.slug)
    table.add_row("topic", project.topic)
    table.add_row("region", project.region or "")
    table.add_row("languages", ", ".join(project.languages))
    table.add_row("target_users", ", ".join(project.target_users))
    table.add_row("access_mode", project.access_mode.value)
    table.add_row("eligibility", project.collection_eligibility.severity.value)
    table.add_row("run_limit", str(project.run_config.limit))
    return table


def _print_stage_runs(project: ResearchProject) -> None:
    if not project.stage_runs:
        console.print("Stage runs: none")
        return

    table = Table(title="Stage runs")
    table.add_column("stage")
    table.add_column("status")
    table.add_column("run_limit")
    table.add_column("message")
    for stage_run in project.stage_runs:
        table.add_row(
            stage_run.stage,
            stage_run.status.value,
            str(stage_run.run_limit or ""),
            stage_run.message or "",
        )
    console.print(table)


@projects_app.command("create")
def create_project_command(
    topic: str = typer.Option(..., "--topic", help="Market research topic."),
    region: str | None = typer.Option(None, "--region", help="Geographic market scope."),
    language: list[str] | None = typer.Option(
        None,
        "--language",
        help="Relevant language code or name. Repeat for multiple languages.",
    ),
    target_user: list[str] | None = typer.Option(
        None,
        "--target-user",
        help="Target user/persona. Repeat for multiple users.",
    ),
    business_context: str | None = typer.Option(
        None,
        "--business-context",
        help="Business context used for compliance eligibility.",
    ),
    time_range: str | None = typer.Option(None, "--time-range", help="Desired analysis period."),
    access_mode: str = typer.Option(
        AccessMode.PERSONAL.value,
        "--access-mode",
        help="One of: personal, research, commercial-approved.",
    ),
    limit: int = typer.Option(
        DEFAULT_RUN_LIMIT,
        "--limit",
        min=1,
        help="Default per-stage run limit.",
    ),
    dry_run: bool = typer.Option(False, "--dry-run", help="Validate and print without writing."),
    registry_path: Path = typer.Option(
        DEFAULT_REGISTRY_PATH,
        "--registry-path",
        help="Path to the local Phase 2 project registry.",
    ),
) -> None:
    """Create a durable research project."""

    parsed_access_mode = _parse_access_mode(access_mode)
    store = ProjectRegistryStore(registry_path)
    project_input = ProjectCreateInput(
        topic=topic,
        region=region,
        languages=language or [],
        target_users=target_user or [],
        business_context=business_context,
        time_range=time_range,
        access_mode=parsed_access_mode,
    )
    project = create_project(
        store,
        project_input,
        run_config=RunConfig(limit=limit, dry_run=dry_run),
        dry_run=dry_run,
    )

    console.print(_project_table(project))
    if dry_run:
        console.print(f"Dry run: project_id {project.project_id} was not written.")
    else:
        console.print(f"Registry path: {registry_path}")


@projects_app.command("show")
def show_project_command(
    project_id: int = typer.Option(..., "--project-id", help="Project ID to inspect."),
    registry_path: Path = typer.Option(
        DEFAULT_REGISTRY_PATH,
        "--registry-path",
        help="Path to the local Phase 2 project registry.",
    ),
) -> None:
    """Show a stored research project."""

    store = ProjectRegistryStore(registry_path)
    try:
        project = get_project_or_raise(store, project_id)
    except ProjectNotFoundError as exc:
        error_console.print(str(exc))
        raise typer.Exit(code=1) from exc

    console.print(_project_table(project))
    _print_stage_runs(project)


@projects_app.command("record-stage")
def record_stage_command(
    project_id: int = typer.Option(..., "--project-id", help="Project ID to update."),
    stage: str = typer.Option(..., "--stage", help="Pipeline stage name to record."),
    status: str = typer.Option(..., "--status", help="Stage status value."),
    message: str | None = typer.Option(None, "--message", help="Optional status note."),
    limit: int | None = typer.Option(None, "--limit", min=1, help="Optional run limit."),
    registry_path: Path = typer.Option(
        DEFAULT_REGISTRY_PATH,
        "--registry-path",
        help="Path to the local Phase 2 project registry.",
    ),
) -> None:
    """Record stage metadata without executing the stage."""

    store = ProjectRegistryStore(registry_path)
    parsed_status = _parse_stage_status(status)
    now = datetime.now(UTC)
    stage_run = StageRun(
        stage=stage,
        status=parsed_status,
        started_at=now,
        completed_at=now if parsed_status is not StageStatus.RUNNING else None,
        run_limit=limit,
        message=message,
    )
    try:
        project = record_stage_run(store, project_id, stage_run)
    except ProjectNotFoundError as exc:
        error_console.print(str(exc))
        raise typer.Exit(code=1) from exc

    console.print(f"Recorded stage run for project_id {project.project_id}: {stage}={status}")


@projects_app.command("import-json")
def import_json_command(
    registry_path: Path = typer.Option(
        DEFAULT_REGISTRY_PATH,
        "--registry-path",
        help="Path to the local Phase 2 project registry.",
    ),
) -> None:
    """Explicitly import Phase 2 JSON project state into the database."""

    try:
        with session_scope() as session:
            result = import_project_registry(registry_path, session)
    except Exception as exc:
        error_console.print(f"Database import failed: {exc}")
        raise typer.Exit(code=1) from exc

    console.print("JSON registry import complete")
    console.print(f"Imported projects: {result.imported_projects}")
    console.print(f"Updated projects: {result.updated_projects}")
    console.print(f"Skipped projects: {result.skipped_projects}")
    console.print(f"Imported stage runs: {result.imported_stage_runs}")


@db_app.command("upgrade")
def db_upgrade_command(
    database_url: str | None = typer.Option(
        None,
        "--database-url",
        help="Override DATABASE_URL for this command.",
    ),
) -> None:
    """Upgrade the configured database to the latest migration."""

    previous_database_url = os.environ.get("DATABASE_URL")
    try:
        command.upgrade(_alembic_config(database_url), "head")
    except Exception as exc:
        error_console.print(f"Database upgrade failed: {exc}")
        raise typer.Exit(code=1) from exc
    finally:
        if database_url:
            if previous_database_url is None:
                os.environ.pop("DATABASE_URL", None)
            else:
                os.environ["DATABASE_URL"] = previous_database_url
    console.print("Database upgraded to head.")


@db_app.command("status")
def db_status_command(
    database_url: str | None = typer.Option(
        None,
        "--database-url",
        help="Override DATABASE_URL for this command.",
    ),
) -> None:
    """Show database migration status."""

    resolved_url = database_url or Settings().database_url
    try:
        current, head = _database_status(resolved_url)
    except Exception as exc:
        error_console.print(f"Database status failed: {exc}")
        raise typer.Exit(code=1) from exc

    table = Table(title="Database status")
    table.add_column("Field")
    table.add_column("Value")
    table.add_row("database_url", _safe_database_url(resolved_url))
    table.add_row("current_revision", current or "none")
    table.add_row("head_revision", head or "none")
    console.print(table)


@db_app.command("preflight")
def db_preflight_command(
    database_url: str | None = typer.Option(
        None,
        "--database-url",
        help="Override DATABASE_URL for this command.",
    ),
) -> None:
    """Check local runtime readiness for live collection."""

    settings = Settings()
    if database_url:
        settings.database_url = database_url
    checks = run_preflight(settings=settings, database_status_checker=_database_status)

    table = Table(title="Runtime preflight")
    table.add_column("Check")
    table.add_column("Status")
    table.add_column("Detail")
    table.add_column("Remediation")
    for check in checks:
        table.add_row(check.name, check.status, check.detail, check.remediation)
    console.print(table)
    for check in checks:
        if check.status in {"fail", "warn"}:
            console.print(
                f"{check.status.upper()} {check.name}: {check.detail}"
                + (f" Remediation: {check.remediation}" if check.remediation else "")
            )

    raise typer.Exit(code=preflight_exit_code(checks))


@plans_app.command("generate")
def plans_generate_command(
    project_id: int = typer.Option(..., "--project-id", help="Database project ID to plan."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Generate JSON without persisting."),
    selected: bool = typer.Option(True, "--selected/--not-selected", help="Mark persisted plan selected."),
) -> None:
    """Generate a structured Reddit research plan for a project."""

    try:
        with session_scope() as session:
            if dry_run:
                topic_plan = generate_topic_plan_for_project(session, project_id)
                console.print_json(data=topic_plan.model_dump(mode="json"))
                return
            result = generate_and_persist_topic_plan(session, project_id, selected=selected)
            _print_plan_summary(result)
    except Exception as exc:
        error_console.print(f"Topic plan generation failed: {exc}")
        raise typer.Exit(code=1) from exc


@plans_app.command("list")
def plans_list_command(
    project_id: int = typer.Option(..., "--project-id", help="Database project ID to inspect."),
) -> None:
    """List persisted topic plans for a project."""

    try:
        with session_scope() as session:
            plans = list_topic_plans(session, project_id)
    except Exception as exc:
        error_console.print(f"Topic plan listing failed: {exc}")
        raise typer.Exit(code=1) from exc

    table = Table(title=f"Topic plans for project {project_id}")
    table.add_column("plan_id")
    table.add_column("selected")
    table.add_column("core_topic")
    table.add_column("primary_keywords")
    for plan in plans:
        table.add_row(
            str(plan.record.id),
            str(plan.record.selected),
            plan.topic_plan.core_topic,
            ", ".join(plan.topic_plan.primary_keywords[:3]),
        )
    console.print(table)


@plans_app.command("show")
def plans_show_command(
    plan_id: int = typer.Option(..., "--plan-id", help="Research plan ID to inspect."),
    json_output: bool = typer.Option(False, "--json", help="Print the full plan JSON."),
) -> None:
    """Show a persisted topic plan."""

    try:
        with session_scope() as session:
            plan = get_topic_plan(session, plan_id)
            if json_output:
                _print_plan_json(plan)
            else:
                _print_plan_summary(plan)
    except Exception as exc:
        error_console.print(f"Topic plan lookup failed: {exc}")
        raise typer.Exit(code=1) from exc


@plans_app.command("select")
def plans_select_command(
    project_id: int = typer.Option(..., "--project-id", help="Database project ID."),
    plan_id: int = typer.Option(..., "--plan-id", help="Research plan ID to select."),
) -> None:
    """Select one topic plan for downstream collection."""

    try:
        with session_scope() as session:
            plan = select_topic_plan(session, project_id, plan_id)
    except (TopicPlanningServiceError, Exception) as exc:
        error_console.print(f"Topic plan selection failed: {exc}")
        raise typer.Exit(code=1) from exc

    console.print(f"Selected topic plan {plan.record.id} for project {project_id}.")


@plans_app.command("export")
def plans_export_command(
    plan_id: int = typer.Option(..., "--plan-id", help="Research plan ID to export."),
    output: Path = typer.Option(..., "--output", help="Output JSON file path."),
) -> None:
    """Export a persisted topic plan JSON file."""

    try:
        with session_scope() as session:
            plan = get_topic_plan(session, plan_id)
            data = plan.topic_plan.model_dump(mode="json")
    except Exception as exc:
        error_console.print(f"Topic plan export failed: {exc}")
        raise typer.Exit(code=1) from exc

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    console.print(f"Exported topic plan {plan_id} to {output}.")


@reddit_app.command("validate-credentials")
def reddit_validate_credentials_command() -> None:
    """Validate Reddit OAuth settings and descriptive User-Agent."""

    status = validate_reddit_credentials(Settings())
    if status.valid:
        console.print(status.message)
        return
    error_console.print(status.message)
    error_console.print("Reason codes: " + ", ".join(status.reason_codes))
    raise typer.Exit(code=1)


@reddit_app.command("collect")
def reddit_collect_command(
    project_id: int = typer.Option(..., "--project-id", help="Database project ID to collect."),
    limit_per_query: int = typer.Option(
        DEFAULT_RUN_LIMIT,
        "--limit-per-query",
        min=1,
        help="Maximum posts to request for each materialized search query.",
    ),
    max_comments_per_post: int = typer.Option(
        10,
        "--max-comments-per-post",
        min=0,
        help="Maximum top-level comments to store per collected post.",
    ),
    skip_comments: bool = typer.Option(
        False,
        "--skip-comments",
        help="Collect posts only and skip top-level comments.",
    ),
) -> None:
    """Collect Reddit posts and optional top-level comments for a project."""

    settings = Settings()
    source_selection = select_collection_source(settings)
    _print_source_selection(source_selection)
    if not source_selection.can_collect:
        error_console.print("Reddit collection failed: " + source_selection.message)
        if source_selection.reason_codes:
            error_console.print("Reason codes: " + ", ".join(source_selection.reason_codes))
        raise typer.Exit(code=1)
    if source_selection.mode != CollectionSourceMode.REDDIT_API:
        error_console.print(
            "Reddit collection failed: public-web fallback is selected but ingestion is not implemented yet."
        )
        raise typer.Exit(code=1)

    try:
        with session_scope() as session:
            summary = run_reddit_collection(
                session,
                project_id,
                limit_per_query,
                max_comments_per_post,
                collect_comments=not skip_comments,
                settings=settings,
            )
    except (RedditCollectionServiceError, Exception) as exc:
        error_console.print(f"Reddit collection failed: {exc}")
        raise typer.Exit(code=1) from exc

    _print_collection_summary(summary)


@reddit_app.command("discover-urls")
def reddit_discover_urls_command(
    project_id: int = typer.Option(..., "--project-id", help="Database project ID for discovery."),
    query: str = typer.Option(..., "--query", help="Site-scoped search query to execute."),
    limit: int = typer.Option(10, "--limit", min=1, max=10, help="Maximum URLs to discover."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Print URLs without persisting them."),
) -> None:
    """Discover candidate Reddit URLs through a configured search provider."""

    try:
        with session_scope() as session:
            summary = run_url_discovery(
                session,
                project_id=project_id,
                query=query,
                limit=limit,
                dry_run=dry_run,
            )
    except (DiscoveryServiceError, Exception) as exc:
        error_console.print(f"URL discovery failed: {exc}")
        raise typer.Exit(code=1) from exc

    _print_discovery_summary(summary)


@reddit_app.command("collect-fallback")
def reddit_collect_fallback_command(
    project_id: int = typer.Option(..., "--project-id", help="Database project ID to collect."),
    limit: int = typer.Option(10, "--limit", min=1, help="Maximum discovered URLs to fetch."),
) -> None:
    """Collect explicitly enabled public-web fallback evidence from discovered URLs."""

    try:
        with session_scope() as session:
            summary = run_web_fallback_ingestion(session, project_id=project_id, limit=limit)
    except (WebFallbackServiceError, Exception) as exc:
        error_console.print(f"Web fallback collection failed: {exc}")
        raise typer.Exit(code=1) from exc

    _print_web_fallback_summary(summary)


@filtering_app.command("run")
def filtering_run_command(
    project_id: int = typer.Option(..., "--project-id", help="Database project ID to filter."),
    limit: int | None = typer.Option(
        None,
        "--limit",
        min=1,
        help="Optional maximum raw posts and raw comments to materialize.",
    ),
) -> None:
    """Clean collected Reddit content and route relevance decisions."""

    try:
        with session_scope() as session:
            summary = run_filtering(session, project_id, limit=limit)
    except (ProcessingServiceError, Exception) as exc:
        error_console.print(f"Filtering failed: {exc}")
        raise typer.Exit(code=1) from exc

    _print_filtering_summary(summary)


@filtering_app.command("export-samples")
def filtering_export_samples_command(
    project_id: int = typer.Option(..., "--project-id", help="Database project ID to export."),
    output_path: Path | None = typer.Option(
        None,
        "--output-path",
        help="Markdown output path. Defaults to outputs/exports/project-{id}/calibration-samples.md.",
    ),
    limit_per_band: int = typer.Option(
        25,
        "--limit-per-band",
        min=1,
        help="Maximum samples per accepted/ambiguous/rejected band.",
    ),
) -> None:
    """Export accepted, ambiguous, and rejected samples for calibration review."""

    try:
        with session_scope() as session:
            path = export_calibration_samples(
                session,
                project_id,
                output_path,
                limit_per_band=limit_per_band,
            )
    except Exception as exc:
        error_console.print(f"Calibration sample export failed: {exc}")
        raise typer.Exit(code=1) from exc

    console.print(f"Exported calibration samples to {path}.")


@llm_app.command("review")
def llm_review_command(
    project_id: int = typer.Option(..., "--project-id", help="Database project ID to review."),
    limit: int | None = typer.Option(
        None,
        "--limit",
        min=1,
        help="Optional maximum pending ambiguous items to review.",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Count pending ambiguous items without writing LLM calls or judgements.",
    ),
) -> None:
    """Review pending ambiguous content items through the LLM gateway."""

    try:
        with session_scope() as session:
            summary = run_llm_review(session, project_id, limit=limit, dry_run=dry_run)
    except (LlmReviewServiceError, Exception) as exc:
        error_console.print(f"LLM review failed: {exc}")
        raise typer.Exit(code=1) from exc

    _print_llm_review_summary(summary)


@llm_app.command("export-review-queue")
def llm_export_review_queue_command(
    project_id: int = typer.Option(..., "--project-id", help="Database project ID to export."),
    output_path: Path | None = typer.Option(
        None,
        "--output-path",
        help="Markdown output path. Defaults to outputs/exports/project-{id}/llm-review-queue.md.",
    ),
    limit: int = typer.Option(
        50,
        "--limit",
        min=1,
        help="Maximum pending ambiguous items to export.",
    ),
) -> None:
    """Export pending ambiguous items that still require LLM review."""

    try:
        with session_scope() as session:
            path = export_review_queue(session, project_id, output_path, limit=limit)
    except Exception as exc:
        error_console.print(f"LLM review queue export failed: {exc}")
        raise typer.Exit(code=1) from exc

    console.print(f"Exported LLM review queue to {path}.")


@analysis_app.command("extract-signals")
def analysis_extract_signals_command(
    project_id: int = typer.Option(..., "--project-id", help="Database project ID to analyze."),
    limit: int | None = typer.Option(
        None,
        "--limit",
        min=1,
        help="Optional maximum eligible evidence items to process.",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Count eligible evidence without writing calls or market signals.",
    ),
) -> None:
    """Extract source-linked market signals from accepted/reviewed evidence."""

    try:
        with session_scope() as session:
            summary = run_signal_extraction(session, project_id, limit=limit, dry_run=dry_run)
    except (SignalExtractionServiceError, Exception) as exc:
        error_console.print(f"Market signal extraction failed: {exc}")
        raise typer.Exit(code=1) from exc

    _print_signal_extraction_summary(summary)


@analysis_app.command("export-signals")
def analysis_export_signals_command(
    project_id: int = typer.Option(..., "--project-id", help="Database project ID to export."),
    output_path: Path | None = typer.Option(
        None,
        "--output-path",
        help="Markdown output path. Defaults to outputs/exports/project-{id}/market-signals.md.",
    ),
    limit: int = typer.Option(
        50,
        "--limit",
        min=1,
        help="Maximum extracted signals to export.",
    ),
) -> None:
    """Export extracted market signals for QA before final report generation."""

    try:
        with session_scope() as session:
            path = export_market_signals(session, project_id, output_path, limit=limit)
    except Exception as exc:
        error_console.print(f"Market signal export failed: {exc}")
        raise typer.Exit(code=1) from exc

    console.print(f"Exported market signals to {path}.")


@reports_app.command("generate")
def reports_generate_command(
    project_id: int = typer.Option(..., "--project-id", help="Database project ID to report on."),
    output_path: Path | None = typer.Option(
        None,
        "--output-path",
        help="Markdown output path. Defaults to outputs/reports/project-{id}/market-report.md.",
    ),
    limit: int = typer.Option(
        100,
        "--limit",
        min=1,
        help="Maximum source-linked market signals to include in the report appendix.",
    ),
) -> None:
    """Generate a source-linked Markdown market intelligence report."""

    try:
        with session_scope() as session:
            summary = generate_market_report(
                session,
                project_id,
                output_path=output_path,
                limit=limit,
            )
    except (ReportGenerationServiceError, Exception) as exc:
        error_console.print(f"Report generation failed: {exc}")
        raise typer.Exit(code=1) from exc

    _print_report_generation_summary(summary)


@reports_app.command("export-evidence")
def reports_export_evidence_command(
    project_id: int = typer.Option(..., "--project-id", help="Database project ID to export."),
    output_dir: Path | None = typer.Option(
        None,
        "--output-dir",
        help="Output directory. Defaults to outputs/exports/project-{id}.",
    ),
    limit: int = typer.Option(
        100,
        "--limit",
        min=1,
        help="Maximum source-linked market signals to export.",
    ),
) -> None:
    """Export report evidence appendix rows as Markdown and CSV."""

    try:
        with session_scope() as session:
            markdown_path, csv_path = export_report_evidence(
                session,
                project_id,
                output_dir=output_dir,
                limit=limit,
            )
    except Exception as exc:
        error_console.print(f"Report evidence export failed: {exc}")
        raise typer.Exit(code=1) from exc

    console.print(f"Exported report evidence Markdown to {markdown_path}.")
    console.print(f"Exported report evidence CSV to {csv_path}.")


@demo_app.command("run-fixture")
def demo_run_fixture_command(
    database_url: str | None = typer.Option(
        None,
        "--database-url",
        help="Demo database URL. Defaults to fixture-demo.sqlite3 inside --output-dir.",
    ),
    output_dir: Path = typer.Option(
        Path("outputs/demo"),
        "--output-dir",
        help="Directory for synthetic report and evidence artifacts.",
    ),
    sample_path: Path | None = typer.Option(
        None,
        "--sample-path",
        help="Optional JSONL sample path. Defaults to the built-in synthetic Zurich sample.",
    ),
) -> None:
    """Run a synthetic no Reddit credentials fixture demo through report/export stages."""

    resolved_database_url = database_url or f"sqlite:///{output_dir / 'fixture-demo.sqlite3'}"
    try:
        _ensure_sqlite_parent(resolved_database_url)
        engine = create_engine(resolved_database_url)
        Base.metadata.create_all(engine)
        factory = sessionmaker(bind=engine, expire_on_commit=False)
        with session_scope(factory) as session:
            summary = run_fixture_demo(session, output_dir=output_dir, sample_path=sample_path)
    except Exception as exc:
        error_console.print(f"Fixture demo failed: {exc}")
        raise typer.Exit(code=1) from exc

    console.print("Synthetic fixture demo uses no Reddit credentials and no live LLM calls.")
    _print_demo_summary(summary)
    console.print(f"Report: {summary.report_path}")
    console.print(f"Evidence CSV: {summary.evidence_csv_path}")
    console.print(f"Market signals: {summary.market_signals_path}")


if __name__ == "__main__":
    app()
