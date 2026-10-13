"""Database persistence helpers for LLM ambiguity review."""

from datetime import UTC, datetime

from sqlalchemy import exists, select
from sqlalchemy.orm import Session

from app.db.models import (
    ContentItemRecord,
    LlmCallRecord,
    LlmJudgementRecord,
    PipelineRunRecord,
    RelevanceDecisionRecord,
    ResearchPlanRecord,
    ResearchProjectRecord,
)
from app.llm.models import (
    LlmReviewRunSummary,
    LlmValidationStatus,
    ValidationResult,
)
from app.processing.models import AMBIGUOUS, LLM_DECISION

AMBIGUITY_REVIEW = "ambiguity_review"


class LlmReviewRepository:
    """Repository for ambiguity review queues and audit persistence."""

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

    def start_review_run(self, project_db_id: int, run_config: dict) -> PipelineRunRecord:
        """Create a running pipeline run for LLM ambiguity review."""

        run = PipelineRunRecord(
            project_id=project_db_id,
            stage="llm_review",
            status="running",
            run_config=run_config,
            summary={},
            started_at=datetime.now(UTC),
        )
        self.session.add(run)
        self.session.flush()
        return run

    def get_selected_research_plan(self, project_db_id: int) -> ResearchPlanRecord | None:
        """Return the selected research plan for a database project if present."""

        return self.session.scalar(
            select(ResearchPlanRecord)
            .where(
                ResearchPlanRecord.project_id == project_db_id,
                ResearchPlanRecord.selected.is_(True),
            )
            .order_by(ResearchPlanRecord.id.desc())
        )

    def complete_review_run(
        self,
        run_id: int,
        status: str,
        summary: LlmReviewRunSummary,
    ) -> PipelineRunRecord:
        """Persist final LLM review run status and summary counters."""

        run = self.session.get(PipelineRunRecord, run_id)
        if run is None:
            raise ValueError(f"LLM review run not found: {run_id}")
        run.status = status
        run.summary = summary.model_dump(mode="json")
        run.completed_at = datetime.now(UTC)
        self.session.flush()
        return run

    def list_pending_ambiguity_items(
        self,
        project_db_id: int,
        limit: int | None = None,
        content_ids: list[int] | None = None,
        force: bool = False,
    ) -> list[ContentItemRecord]:
        """Return content items that still need ambiguity review."""

        statement = (
            select(ContentItemRecord)
            .where(
                ContentItemRecord.project_id == project_db_id,
                ContentItemRecord.final_status == AMBIGUOUS,
                ContentItemRecord.llm_review_required.is_(True),
            )
            .order_by(ContentItemRecord.ambiguity_score.desc().nullslast(), ContentItemRecord.id)
        )
        if not force:
            statement = statement.where(~self._validated_judgement_exists())
        if content_ids is not None:
            statement = statement.where(ContentItemRecord.id.in_(content_ids))
        if limit is not None:
            statement = statement.limit(limit)
        return list(self.session.scalars(statement))

    def count_remaining_ambiguity_items(self, project_db_id: int) -> int:
        """Count pending ambiguity-review items for a project."""

        return len(self.list_pending_ambiguity_items(project_db_id))

    def has_validated_ambiguity_judgement(self, content_item_id: int) -> bool:
        """Return whether an item already has a validated ambiguity judgement."""

        return self.session.scalar(
            select(
                exists().where(
                    LlmJudgementRecord.content_item_id == content_item_id,
                    LlmJudgementRecord.judgement_type == AMBIGUITY_REVIEW,
                    LlmJudgementRecord.validation_status == LlmValidationStatus.VALIDATED.value,
                )
            )
        )

    def record_llm_call(
        self,
        *,
        content_item: ContentItemRecord,
        run_id: int | None,
        input_json: dict,
        validation: ValidationResult,
        prompt_version_id: int | None = None,
        schema_version_id: int | None = None,
        call_type: str = AMBIGUITY_REVIEW,
    ) -> LlmCallRecord:
        """Persist one LLM call attempt, whether validation succeeded or failed."""

        provider_result = validation.provider_result
        call = LlmCallRecord(
            project_id=content_item.project_id,
            run_id=run_id,
            content_item_id=content_item.id,
            call_type=call_type,
            provider=provider_result.provider,
            model_name=provider_result.model,
            prompt_version_id=prompt_version_id,
            schema_version_id=schema_version_id,
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

    def record_validated_judgement(
        self,
        *,
        content_item: ContentItemRecord,
        llm_call: LlmCallRecord,
        validation: ValidationResult,
        prompt_version_id: int | None = None,
        schema_version_id: int | None = None,
    ) -> LlmJudgementRecord:
        """Persist a validated ambiguity judgement and clear the pending queue flag."""

        if validation.output is None:
            raise ValueError("Cannot record judgement without validated output.")
        judgement = LlmJudgementRecord(
            content_item_id=content_item.id,
            llm_call_id=llm_call.id,
            judgement_type=AMBIGUITY_REVIEW,
            output_json=validation.output.model_dump(mode="json"),
            model_name=llm_call.model_name,
            prompt_version_id=prompt_version_id,
            schema_version_id=schema_version_id,
            validation_status=LlmValidationStatus.VALIDATED.value,
        )
        content_item.llm_review_required = False
        self.session.add(judgement)
        self.session.flush()
        return judgement

    def record_failed_call(
        self,
        *,
        content_item: ContentItemRecord,
        run_id: int | None,
        input_json: dict,
        validation: ValidationResult,
        prompt_version_id: int | None = None,
        schema_version_id: int | None = None,
    ) -> LlmCallRecord:
        """Persist a failed validation attempt without creating a judgement."""

        return self.record_llm_call(
            content_item=content_item,
            run_id=run_id,
            input_json=input_json,
            validation=validation,
            prompt_version_id=prompt_version_id,
            schema_version_id=schema_version_id,
        )

    def record_llm_relevance_decision(
        self,
        *,
        content_item: ContentItemRecord,
        run_id: int | None,
        decision: str,
        score: float | None,
        reason: str,
        output_json: dict,
        schema_version_id: int | None = None,
    ) -> RelevanceDecisionRecord:
        """Record an optional LLM relevance decision in the unified decision ledger."""

        record = RelevanceDecisionRecord(
            content_item_id=content_item.id,
            project_id=content_item.project_id,
            run_id=run_id,
            decision_type=LLM_DECISION,
            decision=decision,
            score=score,
            reason=reason,
            output_json=output_json,
            schema_version_id=schema_version_id,
        )
        self.session.add(record)
        self.session.flush()
        return record

    @staticmethod
    def _validated_judgement_exists():
        return exists().where(
            LlmJudgementRecord.content_item_id == ContentItemRecord.id,
            LlmJudgementRecord.judgement_type == AMBIGUITY_REVIEW,
            LlmJudgementRecord.validation_status == LlmValidationStatus.VALIDATED.value,
        )


def _call_output_json(validation: ValidationResult) -> dict | None:
    if validation.validation_status == LlmValidationStatus.VALIDATED:
        return validation.output_json
    return {
        "error": validation.error,
        "output": validation.output_json,
    }
