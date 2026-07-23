"""Service orchestration for evidence-grounded report generation."""

import logging
from pathlib import Path

from sqlalchemy.orm import Session

from app.observability import log_event
from app.reports.generator import build_market_report, render_market_report_markdown
from app.reports.models import ReportGenerationSummary
from app.reports.repository import ReportRepository


class ReportGenerationServiceError(RuntimeError):
    """Raised when report generation cannot complete safely."""


logger = logging.getLogger(__name__)


def generate_market_report(
    session: Session,
    project_id: int,
    output_path: Path | None = None,
    limit: int = 100,
) -> ReportGenerationSummary:
    """Generate, write, and persist a Markdown market intelligence report."""

    repository = ReportRepository(session)
    project = repository.get_project_by_project_id(project_id)
    resolved_output_path = output_path or Path(
        f"outputs/reports/project-{project_id}/market-report.md"
    )
    summary = ReportGenerationSummary(report_path=str(resolved_output_path))
    run = None
    log_event(
        logger,
        "report.generation.started",
        stage="report_generation",
        project_id=project_id,
        artifact_path=str(resolved_output_path),
        item_count_in=limit,
    )

    try:
        run = repository.start_report_run(
            project.id,
            {
                "limit": limit,
                "output_path": str(resolved_output_path),
                "format": "markdown",
            },
        )
        evidence_items = repository.list_evidence_items(project.id, limit=limit)
        dataset_summary = repository.build_dataset_summary(project.id)
        report = build_market_report(
            project.project_id,
            project.topic,
            evidence_items,
            dataset_summary,
        )
        markdown = render_market_report_markdown(report)
        _write_report_file(resolved_output_path, markdown)

        artifact = repository.record_report_artifact(
            project_db_id=project.id,
            run_id=run.id,
            artifact_path=str(resolved_output_path),
            format="markdown",
            dataset_summary=dataset_summary,
            report_json=report,
        )
        summary.market_signal_count = dataset_summary.market_signal_count
        summary.artifact_id = artifact.id
        if dataset_summary.market_signal_count == 0:
            summary.warnings.append("No trusted market signals found")
        repository.complete_report_run(run.id, "completed", summary)
        log_event(
            logger,
            "report.generation.completed",
            stage="report_generation",
            project_id=project_id,
            run_id=run.id,
            status="completed",
            item_count_in=len(evidence_items),
            item_count_out=dataset_summary.market_signal_count,
            artifact_path=str(resolved_output_path),
        )
    except Exception as exc:
        summary.errors += 1
        log_event(
            logger,
            "report.generation.failed",
            stage="report_generation",
            project_id=project_id,
            run_id=run.id if run is not None else None,
            status="failed",
            error=str(exc),
            artifact_path=str(resolved_output_path),
        )
        if run is not None:
            repository.complete_report_run(run.id, "failed", summary)
        raise ReportGenerationServiceError(str(exc)) from exc

    return summary


def _write_report_file(output_path: Path, markdown: str) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(markdown, encoding="utf-8")
