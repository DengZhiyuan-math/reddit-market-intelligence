"""Service orchestration for compliant Reddit collection."""

from sqlalchemy.orm import Session
from app.llm.transport import RunBudget

from app.config import Settings
from app.reddit.client import RedditClientFactory
from app.reddit.collector import RedditCollector
from app.reddit.models import CollectionRunSummary, RedditCredentialsStatus
from app.reddit.repository import RedditCollectionRepository


class RedditCollectionServiceError(RuntimeError):
    """Raised when Reddit collection cannot start or complete safely."""


def validate_reddit_credentials(settings: Settings) -> RedditCredentialsStatus:
    """Validate Reddit credentials without creating a network client."""

    return RedditClientFactory.validate_settings(settings)


def run_reddit_collection(
    session: Session,
    project_id: int,
    limit_per_query: int,
    max_comments_per_post: int,
    collect_comments: bool = True,
    *,
    settings: Settings | None = None,
    reddit_client=None,
    selected_query_ids: list[int] | None = None,
    budget: RunBudget | None = None,
    strict_stop: bool = False,
) -> CollectionRunSummary:
    """Run post and optional top-level comment collection for a project."""

    resolved_settings = settings or Settings()
    status = validate_reddit_credentials(resolved_settings)
    if not status.valid:
        raise RedditCollectionServiceError(status.message + " " + ", ".join(status.reason_codes))

    repository = RedditCollectionRepository(session)
    project = repository.get_project_by_project_id(project_id)
    if strict_stop:
        resolved_settings = resolved_settings.model_copy(update={"reddit_ratelimit_seconds": 0})
    reddit = reddit_client or RedditClientFactory(resolved_settings).create_read_only_client(
        timeout=budget.timeout(30) if budget else None
    )
    run = repository.start_collection_run(
        project.id,
        {
            "limit_per_query": limit_per_query,
            "max_comments_per_post": max_comments_per_post,
            "collect_comments": collect_comments,
        },
    )
    collector = RedditCollector(
        reddit,
        repository,
        resolved_settings,
        budget=budget,
        strict_stop=strict_stop,
        selected_query_ids=selected_query_ids,
    )
    before = repository.project_source_ids(project.id)
    summary = CollectionRunSummary()
    try:
        summary.merge(collector.collect_posts(project_id, limit_per_query, run_id=run.id))
        if collect_comments:
            summary.merge(
                collector.collect_top_level_comments(
                    project_id,
                    max_comments_per_post,
                    run_id=run.id,
                )
            )
    except Exception as exc:
        summary.request_failures += 1
        summary.permanent_failures += 1
        repository.complete_collection_run(run.id, "failed", summary)
        if strict_stop:
            run.summary = {**run.summary, "reason": type(exc).__name__}
            session.commit()
        raise RedditCollectionServiceError(
            "Reddit collection failed: " + type(exc).__name__
        ) from None

    run_status = "completed"
    if (
        summary.permanent_failures
        and summary.processed_queries == 0
        and summary.stored_comments == 0
    ):
        run_status = "failed"
    repository.complete_collection_run(run.id, run_status, summary)
    if strict_stop:
        after = repository.project_source_ids(project.id)
        scope = {kind: sorted(after[kind] - before[kind]) for kind in before}
        run.summary = {
            **run.summary,
            "scope": scope,
            "repeat_ids": {kind: sorted(collector.seen[kind] & before[kind]) for kind in before},
            "source_requests": budget.requests if budget else None,
        }
        if not any(scope.values()):
            run.status = "no_evidence"
        session.commit()
    return summary
