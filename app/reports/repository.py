"""Database persistence helpers for evidence-grounded reports."""

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.analysis.repository import MARKET_SIGNAL_EXTRACTION
from app.db.models import (
    ContentItemRecord,
    LlmCallRecord,
    MarketSignalRecord,
    PipelineRunRecord,
    ReportArtifactRecord,
    ResearchProjectRecord,
)
from app.reports.models import (
    ReportDatasetSummary,
    ReportEvidenceItem,
    ReportGenerationSummary,
    MarketReport,
)

REPORT_GENERATION = "report_generation"


class ReportRepository:
    """Repository for report evidence loading, summaries, runs, and artifacts."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def get_project_by_project_id(self, project_id: int) -> ResearchProjectRecord:
        """Return a database project by its durable project ID."""

        project = self.session.scalar(
            select(ResearchProjectRecord).where(ResearchProjectRecord.project_id == project_id)
        )
        if project is None:
            raise ValueError(f"Project not found in database: {project_id}")
        return project

    def list_evidence_items(
        self,
        project_db_id: int,
        limit: int | None = None,
    ) -> list[ReportEvidenceItem]:
        """Return trusted market signals with source links for reporting."""

        statement = (
            select(MarketSignalRecord)
            .where(MarketSignalRecord.project_id == project_db_id)
            .order_by(
                MarketSignalRecord.confidence.is_(None),
                MarketSignalRecord.confidence.desc(),
                MarketSignalRecord.id,
            )
        )
        if limit is not None:
            statement = statement.limit(limit)

        evidence_items: list[ReportEvidenceItem] = []
        for signal in self.session.scalars(statement):
            item = self.session.get(ContentItemRecord, signal.content_item_id)
            evidence_items.append(_evidence_item_from_records(signal, item))
        return evidence_items

    def build_dataset_summary(self, project_db_id: int) -> ReportDatasetSummary:
        """Build aggregate report inputs without promoting abstentions to evidence."""

        signals = list(
            self.session.scalars(
                select(MarketSignalRecord).where(MarketSignalRecord.project_id == project_db_id)
            )
        )
        content_items = list(
            self.session.scalars(
                select(ContentItemRecord).where(ContentItemRecord.project_id == project_db_id)
            )
        )
        calls = self.session.scalars(
            select(LlmCallRecord).where(
                LlmCallRecord.project_id == project_db_id,
                LlmCallRecord.call_type == MARKET_SIGNAL_EXTRACTION,
            )
        )

        abstained_count = 0
        uncertain_count = 0
        for call in calls:
            status = (call.output_json or {}).get("status")
            if status == "abstained":
                abstained_count += 1
            elif status == "uncertain":
                uncertain_count += 1

        return ReportDatasetSummary(
            market_signal_count=len(signals),
            content_status_counts=_count_values(item.final_status for item in content_items),
            persona_counts=_count_values(signal.persona_label for signal in signals),
            pain_point_counts=_count_values(signal.pain_point for signal in signals),
            urgency_counts=_count_values(signal.urgency_level for signal in signals),
            buying_signal_counts=_count_bool_values(signal.buying_signal for signal in signals),
            source_mode_counts=_count_values(item.source_mode for item in content_items),
            abstained_count=abstained_count,
            uncertain_count=uncertain_count,
        )

    def start_report_run(self, project_db_id: int, run_config: dict[str, Any]) -> PipelineRunRecord:
        """Create a running pipeline run for report generation."""

        run = PipelineRunRecord(
            project_id=project_db_id,
            stage=REPORT_GENERATION,
            status="running",
            run_config=run_config,
            summary={},
            started_at=datetime.now(UTC),
        )
        self.session.add(run)
        self.session.flush()
        return run

    def complete_report_run(
        self,
        run_id: int,
        status: str,
        summary: ReportGenerationSummary,
    ) -> PipelineRunRecord:
        """Persist final report generation run status and counters."""

        run = self.session.get(PipelineRunRecord, run_id)
        if run is None:
            raise ValueError(f"Report generation run not found: {run_id}")
        run.status = status
        run.summary = summary.model_dump(mode="json")
        run.completed_at = datetime.now(UTC)
        self.session.flush()
        return run

    def record_report_artifact(
        self,
        *,
        project_db_id: int,
        run_id: int | None,
        artifact_path: str,
        format: str,
        dataset_summary: ReportDatasetSummary,
        report_json: MarketReport | dict[str, Any],
        template_version_id: int | None = None,
    ) -> ReportArtifactRecord:
        """Persist generated report metadata for audit and reruns."""

        report_payload = (
            report_json.model_dump(mode="json")
            if isinstance(report_json, MarketReport)
            else report_json
        )
        artifact = ReportArtifactRecord(
            project_id=project_db_id,
            run_id=run_id,
            template_version_id=template_version_id,
            artifact_path=artifact_path,
            format=format,
            dataset_summary=dataset_summary.model_dump(mode="json"),
            report_json=report_payload,
        )
        self.session.add(artifact)
        self.session.flush()
        return artifact


def _evidence_item_from_records(
    signal: MarketSignalRecord,
    item: ContentItemRecord | None,
) -> ReportEvidenceItem:
    return ReportEvidenceItem(
        signal_id=signal.id,
        content_item_id=signal.content_item_id,
        llm_judgement_id=signal.llm_judgement_id,
        source_type=item.source_type if item else None,
        source_id=item.source_id if item else None,
        source_mode=_source_mode_from_records(signal, item),
        persona=signal.persona_label,
        pain_point=signal.pain_point,
        urgency=signal.urgency_level,
        buying_signal=signal.buying_signal,
        confidence=signal.confidence,
        quote=signal.quote,
        signal_json=signal.signal_json,
    )


def _count_values(values: object) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        key = str(value) if value not in {None, ""} else "unknown"
        counts[key] = counts.get(key, 0) + 1
    return counts


def _source_mode_from_records(
    signal: MarketSignalRecord,
    item: ContentItemRecord | None,
) -> str | None:
    if item is not None and item.source_mode != "reddit_api":
        return item.source_mode
    return signal.source_mode if signal.source_mode else item.source_mode if item else None


def _count_bool_values(values: object) -> dict[str, int]:
    counts = {"true": 0, "false": 0, "unknown": 0}
    for value in values:
        if value is True:
            counts["true"] += 1
        elif value is False:
            counts["false"] += 1
        else:
            counts["unknown"] += 1
    return counts
