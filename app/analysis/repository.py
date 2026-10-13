"""Database persistence helpers for market signal extraction."""

from datetime import UTC, datetime

from sqlalchemy import exists, select
from sqlalchemy.orm import Session

from app.analysis.models import (
    EvidenceCandidate,
    MarketSignalOutput,
    SignalExtractionRunSummary,
    SignalValidationResult,
)
from app.db.models import (
    ContentItemRecord,
    LlmCallRecord,
    LlmJudgementRecord,
    MarketSignalRecord,
    PipelineRunRecord,
    ResearchProjectRecord,
)
from app.llm.models import LlmValidationStatus
from app.llm.repository import AMBIGUITY_REVIEW
from app.processing.models import ACCEPTED
from app.processing.repository import ProcessingRepository

MARKET_SIGNAL_EXTRACTION = "market_signal_extraction"


class SignalExtractionRepository:
    """Repository for source-linked signal extraction queues and persistence."""

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

    def list_signal_candidates(
        self,
        project_db_id: int,
        limit: int | None = None,
        content_ids: list[int] | None = None,
        force: bool = False,
    ) -> list[EvidenceCandidate]:
        """Return accepted and validated-relevant evidence not already extracted."""

        project = self.session.get(ResearchProjectRecord, project_db_id)
        if project is None:
            raise ValueError(f"Project not found in database: {project_db_id}")

        candidates = self._accepted_content_candidates(project, force=force)
        candidates.extend(self._validated_relevant_judgement_candidates(project, force=force))
        if force:
            unique = {}
            for candidate in candidates:
                unique.setdefault(candidate.content_item_id, candidate)
            candidates = list(unique.values())
        if content_ids is not None:
            candidates = [item for item in candidates if item.content_item_id in content_ids]
        candidates.sort(
            key=lambda candidate: (candidate.content_item_id, candidate.llm_judgement_id or 0)
        )
        if limit is not None:
            candidates = candidates[:limit]
        for candidate in candidates:
            item = self.session.get(ContentItemRecord, candidate.content_item_id)
            candidate.metadata.update(ProcessingRepository(self.session).get_source_context(item))
        return candidates

    def has_existing_signals(self, content_item_id: int, llm_judgement_id: int | None) -> bool:
        """Return whether equivalent extracted signals already exist."""

        conditions = [MarketSignalRecord.content_item_id == content_item_id]
        if llm_judgement_id is None:
            conditions.append(MarketSignalRecord.llm_judgement_id.is_(None))
        else:
            conditions.append(MarketSignalRecord.llm_judgement_id == llm_judgement_id)
        return bool(self.session.scalar(select(exists().where(*conditions))))

    def start_signal_run(self, project_db_id: int, run_config: dict) -> PipelineRunRecord:
        """Create a running pipeline run for market signal extraction."""

        run = PipelineRunRecord(
            project_id=project_db_id,
            stage=MARKET_SIGNAL_EXTRACTION,
            status="running",
            run_config=run_config,
            summary={},
            started_at=datetime.now(UTC),
        )
        self.session.add(run)
        self.session.flush()
        return run

    def complete_signal_run(
        self,
        run_id: int,
        status: str,
        summary: SignalExtractionRunSummary,
    ) -> PipelineRunRecord:
        """Persist final market signal extraction run status and counters."""

        run = self.session.get(PipelineRunRecord, run_id)
        if run is None:
            raise ValueError(f"Signal extraction run not found: {run_id}")
        run.status = status
        run.summary = summary.model_dump(mode="json")
        run.completed_at = datetime.now(UTC)
        self.session.flush()
        return run

    def record_extraction_call(
        self,
        *,
        candidate: EvidenceCandidate,
        run_id: int | None,
        input_json: dict,
        validation: SignalValidationResult,
        call_type: str = MARKET_SIGNAL_EXTRACTION,
    ) -> LlmCallRecord:
        """Persist one extraction call attempt, whether validation succeeded or failed."""

        provider_result = validation.provider_result
        call = LlmCallRecord(
            project_id=candidate.project_db_id,
            run_id=run_id,
            content_item_id=candidate.content_item_id,
            call_type=call_type,
            provider=provider_result.provider,
            model_name=provider_result.model,
            input_json=input_json,
            output_json=_call_output_json(validation),
            raw_response_json=provider_result.raw_response_json,
            validation_status=validation.validation_status.value,
            input_tokens=provider_result.input_tokens,
            output_tokens=provider_result.output_tokens,
            cost_estimate=provider_result.cost_estimate,
        )
        self.session.add(call)
        self.session.flush()
        return call

    def record_market_signal(
        self,
        *,
        candidate: EvidenceCandidate,
        run_id: int | None,
        signal: MarketSignalOutput,
        llm_call_id: int | None = None,
    ) -> MarketSignalRecord:
        """Persist one validated, queryable market signal."""

        signal_json = signal.model_dump(mode="json")
        if llm_call_id is not None:
            signal_json["llm_call_id"] = llm_call_id

        record = MarketSignalRecord(
            project_id=candidate.project_db_id,
            run_id=run_id,
            content_item_id=candidate.content_item_id,
            llm_judgement_id=candidate.llm_judgement_id,
            source_mode=candidate.source_mode,
            intent_label=signal.explicit_need,
            persona_label=signal.user_persona,
            pain_point=signal.user_problem,
            urgency_level=signal.urgency,
            buying_signal=signal.purchase_intent.value in {"medium", "high"},
            quote=signal.useful_quote,
            confidence=signal.confidence,
            signal_json=signal_json,
        )
        self.session.add(record)
        self.session.flush()
        return record

    def _accepted_content_candidates(
        self,
        project: ResearchProjectRecord,
        force: bool = False,
    ) -> list[EvidenceCandidate]:
        statement = (
            select(ContentItemRecord)
            .where(
                ContentItemRecord.project_id == project.id,
                ContentItemRecord.final_status == ACCEPTED,
            )
            .order_by(ContentItemRecord.id)
        )
        candidates: list[EvidenceCandidate] = []
        for item in self.session.scalars(statement):
            if force or not self.has_existing_signals(item.id, None):
                candidates.append(_candidate_from_item(project, item))
        return candidates

    def _validated_relevant_judgement_candidates(
        self,
        project: ResearchProjectRecord,
        force: bool = False,
    ) -> list[EvidenceCandidate]:
        statement = (
            select(LlmJudgementRecord)
            .join(ContentItemRecord, ContentItemRecord.id == LlmJudgementRecord.content_item_id)
            .where(
                ContentItemRecord.project_id == project.id,
                LlmJudgementRecord.judgement_type == AMBIGUITY_REVIEW,
                LlmJudgementRecord.validation_status == LlmValidationStatus.VALIDATED.value,
            )
            .order_by(ContentItemRecord.id, LlmJudgementRecord.id)
        )
        candidates: list[EvidenceCandidate] = []
        seen = set()
        rows = list(self.session.scalars(statement))
        for judgement in reversed(rows) if force else rows:
            if force and judgement.content_item_id in seen:
                continue
            seen.add(judgement.content_item_id)
            if judgement.output_json.get("is_relevant") is not True:
                continue
            if not force and self.has_existing_signals(judgement.content_item_id, judgement.id):
                continue
            item = self.session.get(ContentItemRecord, judgement.content_item_id)
            if item is None:
                continue
            candidates.append(_candidate_from_item(project, item, judgement))
        return candidates


def _candidate_from_item(
    project: ResearchProjectRecord,
    item: ContentItemRecord,
    judgement: LlmJudgementRecord | None = None,
) -> EvidenceCandidate:
    return EvidenceCandidate(
        project_db_id=project.id,
        project_id=project.project_id,
        topic=project.topic,
        business_context=project.business_context,
        content_item_id=item.id,
        source_type=item.source_type,
        source_id=item.source_id,
        source_mode=item.source_mode,
        text=item.cleaned_text or item.text,
        language=item.language,
        relevance_score=item.relevance_score,
        quality_score=item.quality_score,
        llm_judgement_id=judgement.id if judgement else None,
        ambiguity_judgement_json=judgement.output_json if judgement else None,
        metadata={
            "source_table": item.source_table,
            "source_mode": item.source_mode,
            "final_status": item.final_status,
            "ambiguity_score": item.ambiguity_score,
        },
    )


def _call_output_json(validation: SignalValidationResult) -> dict | None:
    if validation.validation_status == LlmValidationStatus.VALIDATED:
        return validation.output_json
    return {
        "error": validation.error,
        "output": validation.output_json,
    }
