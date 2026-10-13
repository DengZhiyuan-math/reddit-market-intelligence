"""One finite, scoped research run using existing stage services and tables."""

from datetime import UTC, datetime, timedelta
from pathlib import Path
import json
import hashlib
import math
import shlex
import shutil
import subprocess
from time import monotonic

from sqlalchemy import select, func, or_
from sqlalchemy.orm import Session

from app.analysis.service import run_signal_extraction
from app.config import Settings
from app.db.models import (
    ContentItemRecord,
    LlmJudgementRecord,
    MarketSignalRecord,
    PipelineRunRecord,
    ResearchProjectRecord,
    SearchQueryRecord,
)
from app.llm.providers import embedding_provider, review_provider, signal_provider, topic_provider
from app.llm.service import run_llm_review
from app.llm.transport import BudgetExceeded, ModelTransport, ModelUnavailable, RunBudget
from app.processing.repository import ProcessingRepository
from app.processing.service import run_filtering
from app.reddit.public_json import acquire_public_json
from app.reddit.browser_dom import acquire_browser_dom, validate_browser_config, BrowserDomError
from app.reddit.builtin_browser import import_browser_capture, prepare_browser_task, _stamp
from app.reddit.repository import RedditCollectionRepository
from app.reddit.service import run_reddit_collection, validate_reddit_credentials
from app.reports.exporter import export_report_evidence
from app.reports.provider import RealReportProvider
from app.reports.service import generate_market_report
from app.topic_planning.service import generate_and_persist_topic_plan, get_topic_plan

SOURCES = {
    "existing",
    "imported",
    "auto",
    "reddit-api",
    "public-json",
    "browser-dom",
    "builtin-browser-dom",
}


def pipeline_preflight(
    session: Session,
    project_id: int,
    *,
    source="auto",
    allow_public_json=False,
    allow_browser_dom=False,
    settings: Settings | None = None,
    check_login=True,
    browser_capture_path: Path | None = None,
):
    settings = settings or Settings()
    if source not in SOURCES:
        raise ValueError("Unknown pipeline source")
    repository = RedditCollectionRepository(session)
    with session.no_autoflush:
        project = repository.get_project_by_project_id(project_id)
    api_ready = settings.reddit_api_enabled and validate_reddit_credentials(settings).valid
    selected_source = source
    if source == "auto":
        selected_source = (
            "reddit-api"
            if api_ready
            else "browser-dom"
            if allow_browser_dom
            else "public-json"
            if allow_public_json
            else "unavailable"
        )
    source_ready = (
        selected_source in {"existing", "imported", "public-json"}
        or selected_source == "reddit-api"
        and api_ready
    )
    browser_ready = False
    try:
        validate_browser_config(settings)
        browser_ready = shutil.which(settings.browser_dom_executable) is not None
    except BrowserDomError:
        pass
    if selected_source == "browser-dom":
        source_ready = browser_ready
    if selected_source == "builtin-browser-dom":
        source_ready = browser_capture_path is not None and browser_capture_path.is_file()
    provider = settings.real_model_provider
    model_ready, login = False, "unknown"
    if provider == "codex-cli":
        model_ready = shutil.which(settings.codex_executable) is not None
        if model_ready and check_login:
            try:
                status = subprocess.run(
                    [settings.codex_executable, "login", "status"],
                    capture_output=True,
                    text=True,
                    shell=False,
                    timeout=10,
                )
                login = "authenticated" if status.returncode == 0 else "unavailable"
                model_ready = status.returncode == 0
            except (OSError, subprocess.TimeoutExpired):
                login, model_ready = "unavailable", False
    elif provider == "openai-compatible":
        model_ready = settings.model_api_key is not None
    return {
        "project_id": project.project_id,
        "source": selected_source,
        "source_ready": bool(source_ready),
        "model_provider": provider,
        "model": settings.real_model,
        "model_ready": model_ready,
        "codex_login": login,
        "http_key_present": settings.model_api_key is not None,
        "oauth_configured": api_ready,
        "network_access": "unobserved",
        "dom_compatibility": "unobserved",
        "browser_configured": browser_ready,
        "browser_capture_required": selected_source == "builtin-browser-dom" and not source_ready,
        "ready": bool(source_ready and model_ready),
    }


def run_pipeline(
    session: Session,
    project_id: int,
    *,
    source="auto",
    allow_public_json=False,
    allow_browser_dom=False,
    dry_run=False,
    output_dir: Path | None = None,
    max_queries=3,
    max_items=10,
    max_requests=16,
    max_model_calls=24,
    max_seconds=300,
    max_browser_operations=80,
    browser_capture_path: Path | None = None,
    max_analysis_items: int | None = None,
    since: str | None = None,
    until: str | None = None,
    _resume_run_id: int | None = None,
    settings: Settings | None = None,
):
    settings = settings or Settings()
    previous_run = session.get(PipelineRunRecord, _resume_run_id) if _resume_run_id else None
    resume_state = dict(previous_run.summary) if previous_run else {}
    if max_analysis_items is not None and not 1 <= max_analysis_items <= max_items:
        raise ValueError("Analysis limit must be between one and max_items")
    for value in (
        max_queries,
        max_items,
        max_requests,
        max_model_calls,
        max_seconds,
        max_browser_operations,
    ):
        if not math.isfinite(value) or value <= 0:
            raise ValueError("Pipeline limits must be positive and finite")
    if (
        max_queries > 24
        or max_items > 100
        or max_requests > 100
        or max_model_calls > 200
        or max_seconds > 3600
        or max_browser_operations > 400
    ):
        raise ValueError("Pipeline limit exceeds bounded maximum")
    readiness = pipeline_preflight(
        session,
        project_id,
        source=source,
        allow_public_json=allow_public_json,
        allow_browser_dom=allow_browser_dom,
        settings=settings,
        check_login=False,
        browser_capture_path=browser_capture_path,
    )
    if dry_run:
        return {
            "status": "dry_run",
            "preflight": readiness,
            "model_calls": 0,
            "source_requests": 0,
            "artifacts": {},
        }
    awaiting_capture = (
        readiness["source"] == "builtin-browser-dom"
        and browser_capture_path is None
        and not resume_state.get("source_scope")
    )
    if awaiting_capture:
        until = until or datetime.now(UTC).isoformat()
        since = since or (_stamp(until) - timedelta(days=365)).isoformat()
        if _stamp(since) >= _stamp(until):
            raise ValueError("Browser window must have since before until")
    repository = RedditCollectionRepository(session)
    project = repository.get_project_by_project_id(project_id)
    if previous_run and previous_run.project_id != project.id:
        raise ValueError("Resume run belongs to another project")
    budget = RunBudget(
        max_model_calls=max_model_calls,
        max_requests=max_requests,
        max_items=max_items,
        max_seconds=max_seconds,
        max_browser_operations=max_browser_operations,
    )
    inherited_calls = resume_state.get("model_calls", 0)
    budget.model_calls = inherited_calls
    budget.requests = resume_state.get("source_requests", 0)
    budget.browser_operations = resume_state.get("browser_operations", 0)
    budget.browser_navigations = resume_state.get("browser_navigations", 0)
    budget.audit = list(resume_state.get("model_audit", []))
    budget.started -= resume_state.get("active_seconds", 0)
    parent = PipelineRunRecord(
        project_id=project.id,
        stage="research_pipeline",
        status="running",
        started_at=datetime.now(UTC),
        run_config={
            "source": source,
            "selected_source": readiness["source"],
            "model_provider": settings.real_model_provider,
            "model": settings.real_model,
            "max_queries": max_queries,
            "max_items": max_items,
            "max_analysis_items": max_analysis_items,
            "max_requests": max_requests,
            "max_model_calls": max_model_calls,
            "max_seconds": max_seconds,
            "max_browser_operations": max_browser_operations,
            "output_dir": str((output_dir or Path("outputs/research")).resolve()),
            "since": since,
            "until": until,
            "resumed_from": _resume_run_id,
            "browser_task_path": previous_run.run_config.get("browser_task_path")
            if previous_run
            else None,
            "browser_task_fingerprint": previous_run.run_config.get("browser_task_fingerprint")
            if previous_run
            else None,
        },
        summary={},
    )
    session.add(parent)
    session.commit()
    outcome = {
        "run_id": parent.id,
        "project_fingerprint": _project_fingerprint(project),
        "status": "running",
        "stages": [],
        "source_scope": {},
        "signal_ids": [],
        "artifacts": {},
    }
    if previous_run:
        outcome["resumed_from"] = previous_run.id
    run_dir = (output_dir or Path("outputs/research")).resolve() / f"run-{parent.id}"

    def save():
        if outcome.get("content_ids"):
            outcome["content_fingerprints"] = _content_fingerprints(session, outcome["content_ids"])
        outcome.update(
            model_calls=budget.model_calls,
            source_requests=budget.requests,
            browser_operations=budget.browser_operations,
            browser_navigations=budget.browser_navigations,
            browser_internal_http_requests=None,
            model_audit=budget.audit,
            cost_estimate=None,
            active_seconds=monotonic() - budget.started,
            new_model_calls=budget.model_calls - inherited_calls,
        )
        run_dir.mkdir(parents=True, exist_ok=True)
        summary_path = run_dir / "run-summary.json"
        outcome["summary_path"] = str(summary_path)
        parent.status = outcome["status"]
        parent.summary = dict(outcome)
        if outcome["status"] != "running":
            parent.completed_at = datetime.now(UTC)
        session.commit()
        summary_path.write_text(json.dumps(outcome, ensure_ascii=False, indent=2), encoding="utf-8")

    def stage(name, operation):
        budget.check()
        earlier = [entry for entry in resume_state.get("stages", []) if entry["stage"] == name]
        if earlier and all(entry["status"] == "completed" for entry in earlier):
            children = [session.get(PipelineRunRecord, entry["run_id"]) for entry in earlier]
            if any(
                child is None or child.project_id != project.id or child.status != "completed"
                for child in children
            ):
                raise ValueError("Completed stage no longer matches this project")
            outcome["stages"].extend({**entry, "reused": True} for entry in earlier)
            return None, children
        previous = set(
            session.scalars(
                select(PipelineRunRecord.id).where(PipelineRunRecord.project_id == project.id)
            )
        )
        try:
            result = operation()
        except Exception as exc:
            children = list(
                session.scalars(
                    select(PipelineRunRecord).where(
                        PipelineRunRecord.project_id == project.id,
                        PipelineRunRecord.id.not_in(previous),
                    )
                )
            )
            cause = exc.__cause__ or exc
            if not children:
                child = PipelineRunRecord(
                    project_id=project.id,
                    stage=name,
                    status="blocked"
                    if isinstance(cause, (BudgetExceeded, PermissionError))
                    or "unavailable" in str(cause)
                    else "failed",
                    started_at=datetime.now(UTC),
                    completed_at=datetime.now(UTC),
                    run_config={"parent_run_id": parent.id},
                    summary={"error_type": type(cause).__name__, "model_audit": list(budget.audit)},
                )
                session.add(child)
                session.flush()
                children = [child]
            for child in children:
                child.run_config = {**child.run_config, "parent_run_id": parent.id}
                outcome["stages"].append(
                    {"stage": name, "run_id": child.id, "status": child.status}
                )
            session.commit()
            raise
        children = list(
            session.scalars(
                select(PipelineRunRecord).where(
                    PipelineRunRecord.project_id == project.id,
                    PipelineRunRecord.id.not_in(previous),
                )
            )
        )
        invalid = getattr(result, "failed", 0) or getattr(result, "errors", 0)
        for child in children:
            if invalid:
                child.status = "failed"
            child.run_config = {**child.run_config, "parent_run_id": parent.id}
            outcome["stages"].append({"stage": name, "run_id": child.id, "status": child.status})
        if not children:
            outcome["stages"].append({"stage": name, "status": "completed"})
        save()
        if invalid:
            raise ModelUnavailable(f"{name} produced failed model validation")
        return result, children

    try:
        if (
            not readiness["ready"]
            and not awaiting_capture
            and not (resume_state.get("source_scope") and readiness["model_ready"])
        ):
            raise ModelUnavailable(
                "Source or real model configuration is unavailable; see preflight"
            )
        processing = ProcessingRepository(session)
        selected = processing.get_selected_research_plan(project.id)
        if selected:
            plan = get_topic_plan(session, selected.id)
        else:
            plan, _ = stage(
                "planning",
                lambda: generate_and_persist_topic_plan(
                    session,
                    project_id,
                    provider=topic_provider(
                        settings.model_copy(
                            update={
                                "topic_planner_provider": settings.real_model_provider,
                                "topic_planner_model": settings.real_model,
                            }
                        ),
                        budget,
                    ),
                ),
            )
        outcome["plan_id"] = plan.record.id
        outcome["plan_fingerprint"] = _fingerprint(plan.record.plan_json)
        if awaiting_capture:
            task = prepare_browser_task(
                project_id=project_id,
                plan_id=plan.record.id,
                queries=plan.topic_plan.query_strategy,
                since=since,
                until=until,
                max_items=max_items,
                max_queries=max_queries,
                max_discussions=max_requests - len(plan.topic_plan.query_strategy[:max_queries]),
            )
            run_dir.mkdir(parents=True, exist_ok=True)
            task_path = run_dir / "browser-task.json"
            task["run_id"] = parent.id
            task_path.write_text(json.dumps(task, ensure_ascii=False, indent=2), encoding="utf-8")
            parent.run_config = {
                **parent.run_config,
                "browser_task_path": str(task_path),
                "browser_task_fingerprint": _fingerprint(task),
            }
            outcome.update(
                status="awaiting_browser",
                reason="Collect the prepared task with Codex in-app browser tools.",
                next_command=shlex.join(
                    [
                        "reddit-market-intel",
                        "pipeline",
                        "resume",
                        "--run-id",
                        str(parent.id),
                        "--browser-capture-path",
                        str(run_dir / "browser-capture.json"),
                    ]
                ),
            )
            outcome["artifacts"]["browser_task"] = str(task_path)
            save()
            return outcome
        selected_source = readiness["source"]
        if resume_state.get("source_scope"):
            scope = resume_state["source_scope"]
            if "acquisition" in resume_state:
                outcome["acquisition"] = resume_state["acquisition"]
            outcome["stages"].extend(
                {**entry, "reused": True}
                for entry in resume_state.get("stages", [])
                if entry["stage"] == "acquisition"
            )
        elif selected_source == "builtin-browser-dom":
            expected_task = None
            if parent.run_config.get("browser_task_path"):
                expected_task = json.loads(
                    Path(parent.run_config["browser_task_path"]).read_text(encoding="utf-8")
                )
                if _fingerprint(expected_task) != parent.run_config["browser_task_fingerprint"]:
                    raise ValueError("Frozen browser task changed; start a new run")
            result, _ = stage(
                "acquisition",
                lambda: import_browser_capture(
                    session,
                    project_id=project_id,
                    plan_id=plan.record.id,
                    input_path=browser_capture_path,
                    max_items=max_items,
                    expected_task=expected_task,
                ),
            )
            outcome["acquisition"] = result.metadata
            if result.status != "completed":
                outcome["status"], outcome["reason"] = result.status, result.reason
                save()
                return outcome
            if sum(map(len, result.scope.values())) > max_items:
                raise ValueError("Captured scope exceeds pipeline item limit")
            scope = result.scope
        elif selected_source == "browser-dom":
            result, _ = stage(
                "acquisition",
                lambda: acquire_browser_dom(
                    session,
                    project_id=project_id,
                    queries=plan.topic_plan.query_strategy,
                    settings=settings,
                    budget=budget,
                    max_queries=max_queries,
                    output_dir=run_dir / "captures",
                ),
            )
            if result.status != "completed":
                outcome["status"], outcome["reason"] = result.status, result.reason
                save()
                return outcome
            scope = result.scope
        elif selected_source == "public-json":
            result, _ = stage(
                "acquisition",
                lambda: acquire_public_json(
                    session,
                    project_id=project_id,
                    queries=plan.topic_plan.query_strategy,
                    budget=budget,
                    max_queries=max_queries,
                ),
            )
            if result.status != "completed":
                outcome["status"], outcome["reason"] = result.status, result.reason
                save()
                return outcome
            scope = result.scope
        elif selected_source == "reddit-api":
            query_ids = list(
                session.scalars(
                    select(SearchQueryRecord.id)
                    .where(
                        SearchQueryRecord.project_id == project.id,
                        SearchQueryRecord.research_plan_id == plan.record.id,
                    )
                    .order_by(SearchQueryRecord.id)
                    .limit(max_queries)
                )
            )
            _, children = stage(
                "acquisition",
                lambda: run_reddit_collection(
                    session,
                    project_id,
                    max(1, max_items // 2),
                    max_items,
                    settings=settings,
                    selected_query_ids=query_ids,
                    budget=budget,
                    strict_stop=True,
                ),
            )
            child = children[-1]
            if child.status != "completed":
                outcome["status"], outcome["reason"] = (
                    child.status,
                    "No newly associated API evidence",
                )
                save()
                return outcome
            scope = child.summary["scope"]
        else:
            rows = [
                ("reddit_post", row.raw_post.reddit_post_id, row.project_post.filters_json)
                for row in processing.list_raw_project_posts(project.id)
            ]
            rows += [
                (
                    "reddit_comment",
                    row.raw_comment.reddit_comment_id,
                    row.project_comment.filters_json,
                )
                for row in processing.list_raw_project_comments(project.id)
            ]
            scope = {"reddit_post": [], "reddit_comment": []}
            for kind, rid, metadata in rows:
                if selected_source == "imported" and metadata.get("acquisition_method") not in {
                    "web_json",
                    "manual_web",
                    "dom",
                }:
                    continue
                if rid not in scope[kind] and sum(map(len, scope.values())) < max_items:
                    scope[kind].append(rid)
        outcome["source_scope"] = scope
        if not any(scope.values()):
            outcome["status"], outcome["reason"] = (
                "no_evidence",
                "Selected source has no qualifying evidence",
            )
            save()
            return outcome
        if max_analysis_items is not None:
            remaining = max_analysis_items
            analysis_scope = {}
            for kind, ids in scope.items():
                analysis_scope[kind] = ids[:remaining]
                remaining -= len(analysis_scope[kind])
            outcome["analysis_scope"] = analysis_scope
            scope = analysis_scope
        embedding = embedding_provider(settings, budget)
        lexical = getattr(embedding, "provider", "") == "deterministic"
        _, filter_runs = stage(
            "filtering",
            lambda: run_filtering(
                session,
                project_id,
                embedding_provider=embedding,
                settings=settings,
                source_scope=scope,
                lexical_review_all=lexical,
            ),
        )
        content_ids = list(
            session.scalars(
                select(ContentItemRecord.id).where(
                    ContentItemRecord.project_id == project.id,
                    ContentItemRecord.run_id == filter_runs[-1].id,
                )
            )
        )
        outcome["content_ids"] = content_ids
        save()
        real_settings = settings.model_copy(
            update={
                "llm_review_provider": settings.real_model_provider,
                "llm_review_model": settings.real_model,
                "signal_extraction_provider": settings.real_model_provider,
                "signal_extraction_model": settings.real_model,
            }
        )
        stage(
            "review",
            lambda: run_llm_review(
                session,
                project_id,
                limit=max_items,
                provider=review_provider(real_settings, budget),
                settings=real_settings,
                content_ids=content_ids,
                force=True,
            ),
        )
        _, extract_runs = stage(
            "extraction",
            lambda: run_signal_extraction(
                session,
                project_id,
                limit=max_items,
                provider=signal_provider(real_settings, budget),
                settings=real_settings,
                content_ids=content_ids,
                force=True,
            ),
        )
        extraction_ids = [run.id for run in extract_runs]
        identifiers = list(
            session.scalars(
                select(MarketSignalRecord.id).where(
                    MarketSignalRecord.project_id == project.id,
                    MarketSignalRecord.run_id.in_(extraction_ids),
                )
            )
        )
        outcome["signal_ids"], outcome["extraction_run_ids"] = identifiers, extraction_ids
        if not identifiers:
            outcome["status"], outcome["reason"] = (
                "no_evidence",
                "No validated real signals in this pipeline run",
            )
            save()
            return outcome
        report_path = run_dir / "market-report.md"
        earlier_reports = [
            entry
            for entry in resume_state.get("stages", [])
            if entry["stage"] == "report" and entry["status"] == "completed"
        ]
        if earlier_reports:
            report_path = Path(
                session.get(PipelineRunRecord, earlier_reports[-1]["run_id"]).run_config[
                    "output_path"
                ]
            )
        stage(
            "report",
            lambda: generate_market_report(
                session,
                project_id,
                output_path=report_path,
                limit=max_items * 10,
                signal_ids=identifiers,
                content_ids=content_ids,
                extraction_run_ids=extraction_ids,
                provider=RealReportProvider(
                    ModelTransport(
                        settings, settings.real_model_provider, settings.real_model, budget
                    )
                ),
            ),
        )
        budget.check()
        markdown, csv_path = export_report_evidence(
            session,
            project_id,
            output_dir=run_dir / "evidence",
            limit=max_items * 10,
            signal_ids=identifiers,
        )
        outcome["artifacts"] = {
            "report": str(report_path),
            "evidence_markdown": str(markdown),
            "evidence_csv": str(csv_path),
        }
        outcome["status"] = "completed"
    except Exception as exc:
        if not session.is_active:
            session.rollback()
        cause = exc.__cause__ or exc
        outcome["status"] = (
            "blocked"
            if isinstance(cause, (BudgetExceeded, PermissionError)) or "unavailable" in str(cause)
            else "failed"
        )
        outcome["reason"] = (
            str(exc)
            if isinstance(exc, (BudgetExceeded, ModelUnavailable))
            else f"Pipeline stage failed ({type(exc).__name__})"
        )
        outcome["artifacts"] = {}
    save()
    return outcome


def resume_pipeline(
    session: Session,
    run_id: int,
    *,
    browser_capture_path: Path | None = None,
    settings: Settings | None = None,
    dry_run=False,
):
    """Continue a stopped run with its frozen limits and completed stages."""
    prior = session.get(PipelineRunRecord, run_id)
    if prior is None or prior.stage not in {"research_pipeline", "research_pipeline_continuation"}:
        raise ValueError("Research pipeline run not found")
    if prior.status == "completed":
        return _completed_result(prior)
    later = session.scalar(
        select(PipelineRunRecord)
        .where(
            PipelineRunRecord.project_id == prior.project_id,
            or_(
                PipelineRunRecord.run_config["resumed_from"].as_integer() == run_id,
                PipelineRunRecord.run_config["continued_from"].as_integer() == run_id,
            ),
        )
        .order_by(PipelineRunRecord.id.desc())
    )
    if later:
        if later.status == "completed":
            return _completed_result(later)
        raise ValueError(f"A continuation already exists; use run {later.id}")
    if prior.status not in {"failed", "blocked", "awaiting_browser"}:
        raise ValueError("Only failed, blocked or awaiting-browser runs can resume")
    if prior.status == "awaiting_browser" and browser_capture_path is None and not dry_run:
        return {**prior.summary, "new_model_calls": 0, "idempotent": True}
    selected = ProcessingRepository(session).get_selected_research_plan(prior.project_id)
    project = session.get(ResearchProjectRecord, prior.project_id)
    if prior.summary.get(
        "project_fingerprint", _project_fingerprint(project)
    ) != _project_fingerprint(project):
        raise ValueError("Project research context changed; start a new run")
    if prior.summary.get("plan_id") and (
        selected is None
        or selected.id != prior.summary["plan_id"]
        or prior.summary.get("plan_fingerprint", _fingerprint(selected.plan_json))
        != _fingerprint(selected.plan_json)
    ):
        raise ValueError("Selected research plan changed; start a new run")
    fingerprints = prior.summary.get("content_fingerprints")
    if not fingerprints and any(
        entry["stage"] == "filtering" and entry["status"] == "completed"
        for entry in prior.summary.get("stages", [])
    ):
        raise ValueError("Old run has no source checkpoint; start a new run")
    if fingerprints and fingerprints != _content_fingerprints(
        session, prior.summary["content_ids"]
    ):
        raise ValueError("Source content or context changed; start a new run")
    resolved = settings or Settings()
    config = prior.run_config
    if (config["model_provider"], config["model"]) != (
        resolved.real_model_provider,
        resolved.real_model,
    ):
        raise ValueError("Resume requires the original model configuration")
    options = {
        name: config[name]
        for name in (
            "max_queries",
            "max_items",
            "max_requests",
            "max_model_calls",
            "max_seconds",
            "max_browser_operations",
            "max_analysis_items",
            "since",
            "until",
        )
        if name in config
    }
    return run_pipeline(
        session,
        project.project_id,
        source=config["selected_source"],
        output_dir=Path(config.get("output_dir", "outputs/research")),
        browser_capture_path=browser_capture_path,
        _resume_run_id=run_id,
        settings=resolved,
        dry_run=dry_run,
        **options,
    )


def _content_fingerprints(session, content_ids):
    latest = dict(
        session.execute(
            select(LlmJudgementRecord.content_item_id, func.max(LlmJudgementRecord.id))
            .where(
                LlmJudgementRecord.content_item_id.in_(content_ids),
                LlmJudgementRecord.judgement_type == "ambiguity_review",
                LlmJudgementRecord.validation_status == "validated",
            )
            .group_by(LlmJudgementRecord.content_item_id)
        ).all()
    )
    repo = ProcessingRepository(session)
    return {
        str(item.id): _fingerprint(
            {
                "run_id": item.run_id,
                "project_id": item.project_id,
                "source_id": item.source_id,
                "source_type": item.source_type,
                "text": item.cleaned_text or item.text,
                "context": repo.get_source_context(item),
                "judgement_id": latest.get(item.id),
            }
        )
        for item in session.scalars(
            select(ContentItemRecord).where(ContentItemRecord.id.in_(content_ids))
        )
    }


def _fingerprint(value):
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True).encode()
    ).hexdigest()


def _project_fingerprint(project):
    return _fingerprint(
        {
            name: getattr(project, name)
            for name in (
                "topic",
                "region",
                "languages",
                "target_users",
                "business_context",
                "time_range",
                "access_mode",
            )
        }
    )


def _completed_result(run):
    return {
        **run.summary,
        "model_calls": run.summary.get("model_calls", run.summary.get("total_model_calls", 0)),
        "new_model_calls": 0,
        "idempotent": True,
    }


def pipeline_status(session: Session, *, project_id: int | None = None, run_id: int | None = None):
    """Read a compact committed run state and its existing artifact paths."""
    if (project_id is None) == (run_id is None):
        raise ValueError("Specify exactly one of project_id or run_id")
    statement = select(PipelineRunRecord).where(
        PipelineRunRecord.stage.in_(["research_pipeline", "research_pipeline_continuation"])
    )
    if run_id is not None:
        statement = statement.where(PipelineRunRecord.id == run_id)
    else:
        project = ProcessingRepository(session).get_project_by_project_id(project_id)
        statement = statement.where(PipelineRunRecord.project_id == project.id)
    run = session.scalar(statement.order_by(PipelineRunRecord.id.desc()).limit(1))
    if run is None:
        raise ValueError("Research pipeline run not found")
    summary = run.summary
    project = session.get(ResearchProjectRecord, run.project_id)
    return {
        "run_id": run.id,
        "project_id": project.project_id,
        "status": run.status,
        "source": run.run_config.get("selected_source"),
        "model_calls": summary.get("model_calls", summary.get("total_model_calls", 0)),
        "source_records": sum(map(len, summary.get("source_scope", {}).values())),
        "analysis_records": sum(
            map(len, summary.get("analysis_scope", summary.get("source_scope", {})).values())
        ),
        "signal_count": len(summary.get("signal_ids", [])),
        "stages": summary.get("stages", []),
        "artifacts": summary.get("artifacts", {}),
        "summary_path": summary.get("summary_path"),
        "reason": summary.get("reason"),
        "next_command": summary.get("next_command"),
        "resumed_from": summary.get("resumed_from", summary.get("continued_from")),
    }
