"""Service orchestration for market signal extraction."""

import logging

from sqlalchemy.orm import Session

from app.analysis.gateway import (
    DeterministicSignalProvider,
    SignalExtractionProvider,
    validate_signal_provider_result,
)
from app.analysis.models import (
    EvidenceCandidate,
    SignalExtractionRequest,
    SignalExtractionRunSummary,
    SignalExtractionStatus,
)
from app.analysis.prompts import build_signal_extraction_prompt
from app.analysis.repository import SignalExtractionRepository
from app.config import Settings
from app.llm.models import LlmValidationStatus
from app.observability import log_event


class SignalExtractionServiceError(RuntimeError):
    """Raised when market signal extraction cannot complete safely."""


logger = logging.getLogger(__name__)


def run_signal_extraction(
    session: Session,
    project_id: int,
    limit: int | None = None,
    dry_run: bool = False,
    provider: SignalExtractionProvider | None = None,
    *,
    settings: Settings | None = None,
) -> SignalExtractionRunSummary:
    """Extract market signals from eligible evidence and persist auditable results."""

    resolved_settings = settings or Settings()
    resolved_provider = provider or DeterministicSignalProvider(
        provider=resolved_settings.signal_extraction_provider,
        model=resolved_settings.signal_extraction_model,
    )
    resolved_limit = limit if limit is not None else resolved_settings.signal_extraction_default_limit
    repository = SignalExtractionRepository(session)
    project = repository.get_project_by_project_id(project_id)
    candidates = repository.list_signal_candidates(project.id, limit=resolved_limit)
    summary = SignalExtractionRunSummary(
        candidates=len(candidates),
        remaining=len(repository.list_signal_candidates(project.id)),
    )
    log_event(
        logger,
        "analysis.signal_extraction.started",
        stage="market_signal_extraction",
        project_id=project_id,
        llm_provider=resolved_provider.provider,
        llm_model=resolved_provider.model,
        status="dry_run" if dry_run else "started",
        item_count_in=len(candidates),
    )
    if dry_run:
        log_event(
            logger,
            "analysis.signal_extraction.completed",
            stage="market_signal_extraction",
            project_id=project_id,
            llm_provider=resolved_provider.provider,
            llm_model=resolved_provider.model,
            status="dry_run",
            item_count_in=len(candidates),
            item_count_out=0,
        )
        return summary

    run = None
    try:
        run = repository.start_signal_run(
            project.id,
            {
                "limit": resolved_limit,
                "dry_run": dry_run,
                "signal_extraction_provider": resolved_provider.provider,
                "signal_extraction_model": resolved_provider.model,
                "signal_extraction_max_retries": resolved_settings.signal_extraction_max_retries,
                "signal_extraction_confidence_threshold": (
                    resolved_settings.signal_extraction_confidence_threshold
                ),
            },
        )
        for candidate in candidates:
            if repository.has_existing_signals(candidate.content_item_id, candidate.llm_judgement_id):
                summary.skipped_duplicates += 1
                continue
            request = _build_signal_request(
                candidate,
                confidence_threshold=resolved_settings.signal_extraction_confidence_threshold,
            )
            prompt_payload = build_signal_extraction_prompt(request)
            provider_result = resolved_provider.extract(request)
            validation = validate_signal_provider_result(provider_result, source_text=candidate.text)
            log_event(
                logger,
                "analysis.signal_extraction.validation",
                stage="market_signal_extraction",
                project_id=project_id,
                run_id=run.id,
                llm_provider=provider_result.provider,
                llm_model=provider_result.model,
                input_tokens=provider_result.input_tokens,
                output_tokens=provider_result.output_tokens,
                cost_estimate=provider_result.cost_estimate,
                status=validation.validation_status.value,
            )
            llm_call = repository.record_extraction_call(
                candidate=candidate,
                run_id=run.id,
                input_json=prompt_payload,
                validation=validation,
            )
            if validation.validation_status == LlmValidationStatus.FAILED:
                summary.failed += 1
                continue
            if validation.output is None:
                summary.failed += 1
                continue
            if validation.output.status in {
                SignalExtractionStatus.ABSTAINED,
                SignalExtractionStatus.UNCERTAIN,
            }:
                summary.abstained += 1
                continue
            for signal in validation.output.signals:
                repository.record_market_signal(
                    candidate=candidate,
                    run_id=run.id,
                    signal=signal,
                    llm_call_id=llm_call.id,
                )
                summary.extracted_signals += 1
        summary.remaining = len(repository.list_signal_candidates(project.id))
    except Exception as exc:
        summary.errors += 1
        log_event(
            logger,
            "analysis.signal_extraction.failed",
            stage="market_signal_extraction",
            project_id=project_id,
            run_id=run.id if run is not None else None,
            llm_provider=resolved_provider.provider,
            llm_model=resolved_provider.model,
            status="failed",
            error=str(exc),
        )
        if run is not None:
            repository.complete_signal_run(run.id, "failed", summary)
        raise SignalExtractionServiceError(str(exc)) from exc

    repository.complete_signal_run(run.id, "completed", summary)
    log_event(
        logger,
        "analysis.signal_extraction.completed",
        stage="market_signal_extraction",
        project_id=project_id,
        run_id=run.id,
        llm_provider=resolved_provider.provider,
        llm_model=resolved_provider.model,
        status="completed",
        item_count_in=len(candidates),
        item_count_out=summary.extracted_signals,
        failed=summary.failed,
        remaining=summary.remaining,
    )
    return summary


def _build_signal_request(
    candidate: EvidenceCandidate,
    *,
    confidence_threshold: float,
) -> SignalExtractionRequest:
    return SignalExtractionRequest(
        project_id=candidate.project_id,
        content_item_id=candidate.content_item_id,
        topic=candidate.topic,
        business_context=candidate.business_context,
        text=candidate.text,
        source_type=candidate.source_type,
        source_id=candidate.source_id,
        source_mode=candidate.source_mode,
        language=candidate.language,
        relevance_score=candidate.relevance_score,
        quality_score=candidate.quality_score,
        llm_judgement_id=candidate.llm_judgement_id,
        ambiguity_judgement_json=candidate.ambiguity_judgement_json,
        confidence_threshold=confidence_threshold,
        metadata=candidate.metadata,
    )
