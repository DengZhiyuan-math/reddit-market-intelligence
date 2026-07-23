"""Service orchestration for cleaning and relevance routing."""

from sqlalchemy.orm import Session

from app.config import Settings
from app.processing.embeddings import (
    DeterministicEmbeddingProvider,
    EmbeddingProvider,
    embedding_text_hash,
)
from app.processing.models import AMBIGUOUS, REJECTED, FilteringRunSummary, ReasonSeverity
from app.processing.relevance import (
    ambiguity_score as calculate_ambiguity_score,
    build_topic_text,
    cosine_similarity,
    route_similarity,
)
from app.processing.repository import ProcessingRepository


class ProcessingServiceError(RuntimeError):
    """Raised when filtering cannot complete safely."""


def run_filtering(
    session: Session,
    project_id: int,
    limit: int | None = None,
    embedding_provider: EmbeddingProvider | None = None,
    *,
    settings: Settings | None = None,
) -> FilteringRunSummary:
    """Run content cleaning, embedding, and relevance routing for one project."""

    resolved_settings = settings or Settings()
    provider = embedding_provider or DeterministicEmbeddingProvider(
        dimensions=resolved_settings.embedding_dimensions,
        model=resolved_settings.embedding_model,
        provider=resolved_settings.embedding_provider,
    )
    repository = ProcessingRepository(session)
    project = repository.get_project_by_project_id(project_id)
    run = repository.start_filtering_run(
        project.id,
        {
            "limit": limit,
            "embedding_provider": resolved_settings.embedding_provider,
            "embedding_model": resolved_settings.embedding_model,
            "accept_threshold": resolved_settings.relevance_accept_threshold,
            "reject_threshold": resolved_settings.relevance_reject_threshold,
        },
    )
    summary = FilteringRunSummary()
    try:
        summary.raw_posts_processed = len(repository.list_raw_project_posts(project.id, limit=limit))
        summary.raw_comments_processed = len(
            repository.list_raw_project_comments(project.id, limit=limit)
        )
        topic_plan = repository.get_selected_research_plan(project.id)
        topic_text = build_topic_text(project, topic_plan)
        topic_embedding = provider.embed([topic_text])[0]
        materialized = repository.materialize_raw_content_items(
            project=project,
            run_id=run.id,
            limit=limit,
        )
        for content_item, inserted in materialized:
            if inserted:
                summary.content_items_created += 1
            else:
                summary.content_items_updated += 1
            if _has_reason(content_item, "DUPLICATE_TEXT"):
                summary.duplicate_text += 1
            if _is_hard_rejected(content_item):
                summary.rejected += 1
                continue
            text = content_item.cleaned_text or ""
            content_embedding = provider.embed([text])[0]
            score = cosine_similarity(topic_embedding.vector, content_embedding.vector)
            route = route_similarity(
                score,
                resolved_settings.relevance_accept_threshold,
                resolved_settings.relevance_reject_threshold,
            )
            item_ambiguity = calculate_ambiguity_score(
                score,
                resolved_settings.relevance_accept_threshold,
                resolved_settings.relevance_reject_threshold,
            )
            requires_review = route == AMBIGUOUS
            repository.upsert_content_embedding(
                content_item=content_item,
                embedding=content_embedding,
                text_hash=embedding_text_hash(text),
            )
            repository.update_relevance_routing(
                content_item=content_item,
                final_status=route,
                relevance_score=score,
                ambiguity_score=item_ambiguity,
                llm_review_required=requires_review,
            )
            repository.record_relevance_decision(
                content_item=content_item,
                run_id=run.id,
                decision=route,
                score=score,
                reason=f"Embedding similarity {score:.3f} routed to {route}.",
                output_json={
                    "accept_threshold": resolved_settings.relevance_accept_threshold,
                    "reject_threshold": resolved_settings.relevance_reject_threshold,
                    "embedding_provider": content_embedding.provider,
                    "embedding_model": content_embedding.model,
                    "dimensions": content_embedding.dimensions,
                },
            )
            summary.embedded += 1
            if route == "accepted":
                summary.accepted += 1
            elif route == REJECTED:
                summary.rejected += 1
            else:
                summary.ambiguous += 1
            if requires_review:
                summary.llm_review_required += 1
    except Exception as exc:
        summary.errors += 1
        repository.complete_filtering_run(run.id, "failed", summary)
        raise ProcessingServiceError(str(exc)) from exc

    repository.complete_filtering_run(run.id, "completed", summary)
    return summary


def _is_hard_rejected(content_item) -> bool:
    if content_item.final_status == REJECTED:
        return any(
            reason.get("severity") == ReasonSeverity.REJECT.value
            for reason in content_item.reason_codes
        )
    return False


def _has_reason(content_item, code: str) -> bool:
    return any(reason.get("code") == code for reason in content_item.reason_codes)

