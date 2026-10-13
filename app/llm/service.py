"""Service orchestration for LLM ambiguity review."""

import logging

from sqlalchemy.orm import Session

from app.config import Settings
from app.llm.providers import review_provider
from app.db.models import ContentItemRecord, ResearchPlanRecord, ResearchProjectRecord
from app.llm.gateway import (
    LlmReviewProvider,
    validate_provider_result,
)
from app.llm.models import AmbiguityReviewRequest, LlmReviewRunSummary, LlmValidationStatus
from app.llm.prompts import build_ambiguity_review_prompt
from app.llm.repository import LlmReviewRepository
from app.observability import log_event
from app.processing.repository import ProcessingRepository


class LlmReviewServiceError(RuntimeError):
    """Raised when ambiguity review cannot complete safely."""


logger = logging.getLogger(__name__)


def run_llm_review(
    session: Session,
    project_id: int,
    limit: int | None = None,
    dry_run: bool = False,
    provider: LlmReviewProvider | None = None,
    *,
    settings: Settings | None = None,
    content_ids: list[int] | None = None,
    force: bool = False,
) -> LlmReviewRunSummary:
    """Review pending ambiguous content items and persist validated judgements."""

    resolved_settings = settings or Settings()
    resolved_provider = provider or review_provider(resolved_settings)
    resolved_limit = limit if limit is not None else resolved_settings.llm_review_default_limit
    repository = LlmReviewRepository(session)
    project = repository.get_project_by_project_id(project_id)
    topic_plan = repository.get_selected_research_plan(project.id)
    run = None
    summary = LlmReviewRunSummary()
    log_event(
        logger,
        "llm.review.started",
        stage="llm_review",
        project_id=project_id,
        llm_provider=resolved_provider.provider,
        llm_model=resolved_provider.model,
        status="dry_run" if dry_run else "started",
    )
    try:
        pending_items = repository.list_pending_ambiguity_items(
            project.id, limit=resolved_limit, content_ids=content_ids, force=force
        )
        if dry_run:
            summary.skipped = len(pending_items)
            summary.remaining = repository.count_remaining_ambiguity_items(project.id)
            log_event(
                logger,
                "llm.review.completed",
                stage="llm_review",
                project_id=project_id,
                llm_provider=resolved_provider.provider,
                llm_model=resolved_provider.model,
                status="dry_run",
                item_count_in=len(pending_items),
                item_count_out=0,
            )
            return summary

        run = repository.start_review_run(
            project.id,
            {
                "limit": resolved_limit,
                "dry_run": dry_run,
                "llm_review_provider": resolved_provider.provider,
                "llm_review_model": resolved_provider.model,
                "llm_review_max_retries": resolved_settings.llm_review_max_retries,
            },
        )
        for content_item in pending_items:
            if not force and repository.has_validated_ambiguity_judgement(content_item.id):
                summary.skipped += 1
                continue
            context = ProcessingRepository(session).get_source_context(content_item)
            request = _build_review_request(project, topic_plan, content_item, context)
            prompt_payload = build_ambiguity_review_prompt(request)
            provider_result = resolved_provider.review(request)
            validation = validate_provider_result(provider_result)
            log_event(
                logger,
                "llm.review.validation",
                stage="llm_review",
                project_id=project_id,
                run_id=run.id,
                llm_provider=provider_result.provider,
                llm_model=provider_result.model,
                input_tokens=provider_result.input_tokens,
                output_tokens=provider_result.output_tokens,
                cost_estimate=provider_result.cost_estimate,
                status=validation.validation_status.value,
            )
            if validation.validation_status == LlmValidationStatus.FAILED:
                repository.record_failed_call(
                    content_item=content_item,
                    run_id=run.id,
                    input_json=prompt_payload,
                    validation=validation,
                )
                summary.failed += 1
                continue
            llm_call = repository.record_llm_call(
                content_item=content_item,
                run_id=run.id,
                input_json=prompt_payload,
                validation=validation,
            )
            repository.record_validated_judgement(
                content_item=content_item,
                llm_call=llm_call,
                validation=validation,
            )
            if validation.output is not None:
                repository.record_llm_relevance_decision(
                    content_item=content_item,
                    run_id=run.id,
                    decision="accepted" if validation.output.is_relevant else "rejected",
                    score=validation.output.relevance_score,
                    reason=validation.output.reason,
                    output_json=validation.output.model_dump(mode="json"),
                )
                if validation.output.is_relevant:
                    summary.relevant += 1
                else:
                    summary.irrelevant += 1
            summary.reviewed += 1
        summary.remaining = repository.count_remaining_ambiguity_items(project.id)
    except Exception as exc:
        summary.errors += 1
        log_event(
            logger,
            "llm.review.failed",
            stage="llm_review",
            project_id=project_id,
            run_id=run.id if run is not None else None,
            llm_provider=resolved_provider.provider,
            llm_model=resolved_provider.model,
            status="failed",
            error=str(exc),
        )
        if run is not None:
            repository.complete_review_run(run.id, "failed", summary)
        raise LlmReviewServiceError(str(exc)) from exc

    repository.complete_review_run(run.id, "completed", summary)
    log_event(
        logger,
        "llm.review.completed",
        stage="llm_review",
        project_id=project_id,
        run_id=run.id,
        llm_provider=resolved_provider.provider,
        llm_model=resolved_provider.model,
        status="completed",
        item_count_in=len(pending_items),
        item_count_out=summary.reviewed,
        failed=summary.failed,
        remaining=summary.remaining,
    )
    return summary


def _build_review_request(
    project: ResearchProjectRecord,
    topic_plan: ResearchPlanRecord | None,
    content_item: ContentItemRecord,
    context: dict,
) -> AmbiguityReviewRequest:
    plan_json = topic_plan.plan_json if topic_plan is not None else {}
    return AmbiguityReviewRequest(
        project_id=project.project_id,
        content_item_id=content_item.id,
        topic=plan_json.get("core_topic") or project.topic,
        business_context=project.business_context,
        text=content_item.cleaned_text or content_item.text,
        source_type=content_item.source_type,
        source_id=content_item.source_id,
        subreddit=context["subreddit"],
        language=content_item.language,
        relevance_score=content_item.relevance_score,
        quality_score=content_item.quality_score,
        ambiguity_score=content_item.ambiguity_score,
        classification_labels=list(plan_json.get("classification_labels") or []),
        persona_labels=list(plan_json.get("persona_labels") or []),
        pain_point_labels=list(plan_json.get("pain_point_labels") or []),
        metadata={
            **context,
            "source_table": content_item.source_table,
            "final_status": content_item.final_status,
            "llm_review_required": content_item.llm_review_required,
        },
    )
