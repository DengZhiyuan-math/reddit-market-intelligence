"""Database persistence helpers for evidence-grounded reports."""

from datetime import UTC, datetime
from typing import Any
from urllib.parse import urljoin

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
    ProjectRedditPostRecord,
    ProjectRedditCommentRecord,
    RedditPostRawRecord,
    RedditCommentRawRecord,
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
        signal_ids: list[int] | None = None,
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
        if signal_ids is not None:
            statement = statement.where(MarketSignalRecord.id.in_(signal_ids))
        if limit is not None:
            statement = statement.limit(limit)

        evidence_items: list[ReportEvidenceItem] = []
        for signal in self.session.scalars(statement):
            item = self.session.get(ContentItemRecord, signal.content_item_id)
            evidence = _evidence_item_from_records(signal, item)
            evidence.source_url = self._source_url(project_db_id, item)
            evidence_items.append(evidence)
        return evidence_items

    def _source_url(self, project_db_id: int, item: ContentItemRecord | None) -> str | None:
        if item is None or item.source_type not in {"reddit_post", "reddit_comment"}:
            return None
        if item.source_type == "reddit_post":
            raw_type, association_type, raw_key, link_key = (
                RedditPostRawRecord,
                ProjectRedditPostRecord,
                RedditPostRawRecord.reddit_post_id,
                ProjectRedditPostRecord.reddit_post_raw_id,
            )
        else:
            raw_type, association_type, raw_key, link_key = (
                RedditCommentRawRecord,
                ProjectRedditCommentRecord,
                RedditCommentRawRecord.reddit_comment_id,
                ProjectRedditCommentRecord.reddit_comment_raw_id,
            )
        raw = self.session.scalar(select(raw_type).where(raw_key == item.source_id))
        if raw is None:
            return None
        association = self.session.scalar(
            select(association_type)
            .where(association_type.project_id == project_db_id, link_key == raw.id)
            .order_by(association_type.id)
        )
        if association and "source_snapshot" in (association.filters_json or {}):
            url = association.filters_json["source_snapshot"].get("permalink")
            return urljoin("https://www.reddit.com", url) if url else None
        url = (association.filters_json or {}).get("source_url") if association else None
        if not url and association and association.run_id:
            run = self.session.get(PipelineRunRecord, association.run_id)
            if run:
                kind = "post" if item.source_type == "reddit_post" else "comment"
                url = next(
                    (
                        entry.get("source_url")
                        for entry in run.summary.get("items", [])
                        if entry.get("id") == item.source_id and entry.get("type") == kind
                    ),
                    None,
                )
        url = (
            url
            or raw.permalink
            or raw.raw_json.get("permalink")
            or raw.raw_json.get("source_snapshot", {}).get("permalink")
        )
        return urljoin("https://www.reddit.com", url) if url else None

    def _import_summary(
        self, project_db_id: int, source_scope: dict[str, list[str]] | None = None
    ) -> dict[str, Any]:
        batches, items, coverage, comments_by_post = [], set(), {}, {}
        runs = self.session.scalars(
            select(PipelineRunRecord)
            .where(
                PipelineRunRecord.project_id == project_db_id,
                PipelineRunRecord.stage == "reddit_collection",
                PipelineRunRecord.status == "completed",
            )
            .order_by(PipelineRunRecord.id)
        )
        for run in runs:
            if run.run_config.get("input_format") not in {"listing_json", "rows_json", "csv"}:
                continue
            scoped_items = [
                item
                for item in run.summary.get("items", [])
                if source_scope is None
                or item["id"] in source_scope.get("reddit_" + item["type"], [])
            ]
            if source_scope is not None and not scoped_items:
                continue
            discussion_ids = {item["post_id"] for item in scoped_items}
            batches.append(
                {
                    "run_id": run.id,
                    "capture": {
                        key: value
                        for key, value in run.run_config.items()
                        if key != "source_snapshot"
                    },
                    "coverage": {
                        key: value for key, value in run.summary.items() if key != "items"
                    },
                }
            )
            for item in scoped_items:
                items.add((item["type"], item["id"]))
                if item["type"] == "comment":
                    comments_by_post.setdefault(item["post_id"], set()).add(item["id"])
            for pid, value in run.summary.get("post_coverage", {}).items():
                if source_scope is not None and pid not in discussion_ids:
                    continue
                existing = coverage.setdefault(
                    pid, {"comments_complete": "unknown", "captured_comments": 0}
                )
                if value.get("comments_complete") == "incomplete":
                    existing["comments_complete"] = "incomplete"
        for pid, value in coverage.items():
            value["captured_comments"] = len(comments_by_post.get(pid, set()))
        return dict(
            import_batches=batches,
            import_unique_posts=sum(kind == "post" for kind, _ in items),
            import_unique_comments=sum(kind == "comment" for kind, _ in items),
            import_discussions=len(coverage),
            import_coverage=coverage,
        )

    def build_dataset_summary(
        self,
        project_db_id: int,
        *,
        signal_ids: list[int] | None = None,
        content_ids: list[int] | None = None,
        extraction_run_ids: list[int] | None = None,
    ) -> ReportDatasetSummary:
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
        if signal_ids is not None:
            signals = [item for item in signals if item.id in signal_ids]
        if content_ids is not None:
            content_items = [item for item in content_items if item.id in content_ids]
        calls = self.session.scalars(
            select(LlmCallRecord).where(
                LlmCallRecord.project_id == project_db_id,
                LlmCallRecord.call_type == MARKET_SIGNAL_EXTRACTION,
            )
        )

        abstained_count = 0
        uncertain_count = 0
        for call in calls:
            if extraction_run_ids is not None and call.run_id not in extraction_run_ids:
                continue
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
            **self._import_summary(
                project_db_id,
                {
                    "reddit_post": [
                        item.source_id
                        for item in content_items
                        if item.source_type == "reddit_post"
                    ],
                    "reddit_comment": [
                        item.source_id
                        for item in content_items
                        if item.source_type == "reddit_comment"
                    ],
                }
                if content_ids is not None
                else None,
            ),
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
