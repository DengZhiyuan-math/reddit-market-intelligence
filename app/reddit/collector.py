"""Read-only Reddit collection orchestration."""

from collections.abc import Callable
from itertools import islice
from app.llm.transport import RunBudget, BudgetExceeded
import logging
from time import monotonic
from typing import Any

from app.config import Settings
from app.observability import log_event
from app.reddit.models import CollectionRunSummary, RedditCommentSnapshot, RedditPostSnapshot
from app.reddit.rate_limiter import (
    RetryPolicy,
    parse_rate_limit_headers,
    should_stop_for_rate_limit,
)
from app.reddit.repository import RedditCollectionRepository


logger = logging.getLogger(__name__)


class RedditCollector:
    """Collect Reddit posts and comments through a read-only client adapter."""

    def __init__(
        self,
        reddit: Any,
        repository: RedditCollectionRepository,
        settings: Settings,
        *,
        retry_policy: RetryPolicy | None = None,
        sleep: Callable[[float], None] | None = None,
        budget: RunBudget | None = None,
        strict_stop: bool = False,
        selected_query_ids: list[int] | None = None,
    ) -> None:
        self.reddit = reddit
        self.repository = repository
        self.settings = settings
        self.retry_policy = retry_policy or RetryPolicy(
            max_attempts=settings.reddit_retry_attempts,
            backoff_seconds=settings.reddit_retry_backoff_seconds,
        )
        self.sleep = sleep
        self.budget, self.strict_stop, self.selected_query_ids = (
            budget,
            strict_stop,
            selected_query_ids,
        )
        self.seen = {"reddit_post": set(), "reddit_comment": set()}
        self.before = {"reddit_post": set(), "reddit_comment": set()}

    def collect_posts(
        self,
        project_id: int,
        limit_per_query: int,
        run_id: int | None = None,
    ) -> CollectionRunSummary:
        """Collect posts for pending materialized search queries."""

        started = monotonic()
        project = self.repository.get_project_by_project_id(project_id)
        queries = self.repository.list_pending_search_queries(project.id)
        if self.selected_query_ids is not None:
            queries = [self.repository.get_search_query(qid) for qid in self.selected_query_ids]
            if any(query is None or query.project_id != project.id for query in queries):
                raise ValueError("Selected API query is missing or belongs to another project")
        if self.strict_stop:
            self.before = self.repository.project_source_ids(project.id)
        summary = CollectionRunSummary(requested_queries=len(queries))
        log_event(
            logger,
            "reddit.collection.posts.started",
            stage="reddit_collection",
            project_id=project_id,
            run_id=run_id,
            item_count_in=len(queries),
        )
        for query in queries:
            remaining = (
                self.budget.max_items - sum(map(len, self.seen.values()))
                if self.budget
                else limit_per_query
            )
            if remaining <= 0:
                break
            if self.budget:
                self.budget.source_request()
            request = self.repository.create_request_log(
                project_db_id=project.id,
                run_id=run_id,
                search_query_id=query.id,
                endpoint=f"/r/{query.subreddit}/search",
                action="search_subreddit",
                subreddit=query.subreddit,
                query=query.query,
                request_params={
                    "sort": query.sort or "relevance",
                    "time_filter": query.time_filter or "all",
                    "limit": limit_per_query,
                },
            )
            request_started = monotonic()
            try:
                request_limit = min(limit_per_query, remaining)

                def operation():
                    return list(
                        islice(
                            self.reddit.subreddit(query.subreddit).search(
                                query.query,
                                sort=query.sort or "relevance",
                                time_filter=query.time_filter or "all",
                                limit=request_limit,
                            ),
                            request_limit,
                        )
                    )

                submissions = (
                    operation()
                    if self.strict_stop
                    else self.retry_policy.run(operation, sleep=self.sleep)
                )
            except Exception as exc:
                summary.request_failures += 1
                summary.permanent_failures += 1
                log_event(
                    logger,
                    "reddit.collection.posts.request_failed",
                    stage="reddit_collection",
                    project_id=project_id,
                    run_id=run_id,
                    reddit_endpoint=f"/r/{query.subreddit}/search",
                    subreddit=query.subreddit,
                    keyword=query.query,
                    error=str(exc),
                )
                self.repository.finish_request_log(
                    request.id,
                    error=str(exc),
                    elapsed_ms=_elapsed_ms(request_started),
                )
                self.repository.mark_search_query_status(query.id, "failed")
                if self.strict_stop:
                    raise
                continue

            response_headers = _headers_from_listing(submissions)
            snapshot = parse_rate_limit_headers(response_headers)
            log_event(
                logger,
                "reddit.collection.posts.rate_limit",
                stage="reddit_collection",
                project_id=project_id,
                run_id=run_id,
                reddit_endpoint=f"/r/{query.subreddit}/search",
                subreddit=query.subreddit,
                keyword=query.query,
                x_ratelimit_used=snapshot.used,
                x_ratelimit_remaining=snapshot.remaining,
                x_ratelimit_reset=snapshot.reset,
            )
            if should_stop_for_rate_limit(snapshot, self.settings.reddit_min_remaining):
                summary.rate_limit_stops += 1

            for submission in submissions:
                post_snapshot = RedditPostSnapshot.from_submission(submission)
                self.seen["reddit_post"].add(post_snapshot.reddit_post_id)
                if self.strict_stop and post_snapshot.reddit_post_id in self.before["reddit_post"]:
                    summary.duplicate_posts_skipped += 1
                    continue
                raw_post, inserted = self.repository.upsert_raw_post(post_snapshot)
                _, linked = self.repository.link_project_post(
                    project_db_id=project.id,
                    run_id=run_id,
                    search_query=query,
                    request_id=request.id,
                    raw_post=raw_post,
                    snapshot=post_snapshot,
                )
                if inserted and linked:
                    summary.stored_posts += 1
                else:
                    summary.duplicate_posts_skipped += 1
            summary.processed_queries += 1
            self.repository.finish_request_log(
                request.id,
                status_code=200,
                elapsed_ms=_elapsed_ms(request_started),
                response_headers=response_headers,
            )
            self.repository.mark_search_query_status(query.id, "completed")
            if summary.rate_limit_stops:
                if self.strict_stop:
                    raise BudgetExceeded("Reddit rate-limit stop")
                break

        summary.elapsed_ms = _elapsed_ms(started)
        log_event(
            logger,
            "reddit.collection.posts.completed",
            stage="reddit_collection",
            project_id=project_id,
            run_id=run_id,
            status="completed",
            item_count_in=summary.requested_queries,
            item_count_out=summary.stored_posts,
            request_failures=summary.request_failures,
            duplicate_posts_skipped=summary.duplicate_posts_skipped,
            rate_limit_stops=summary.rate_limit_stops,
        )
        return summary

    def collect_top_level_comments(
        self,
        project_id: int,
        max_comments_per_post: int,
        run_id: int | None = None,
    ) -> CollectionRunSummary:
        """Collect top-level comments for already collected project posts."""

        started = monotonic()
        project = self.repository.get_project_by_project_id(project_id)
        project_posts = self.repository.list_project_posts_for_comment_collection(
            project.id, run_id
        )
        summary = CollectionRunSummary()
        log_event(
            logger,
            "reddit.collection.comments.started",
            stage="reddit_collection",
            project_id=project_id,
            run_id=run_id,
            item_count_in=len(project_posts),
        )
        for project_post in project_posts:
            remaining = (
                self.budget.max_items - sum(map(len, self.seen.values()))
                if self.budget
                else max_comments_per_post
            )
            if remaining <= 0:
                break
            if self.budget:
                self.budget.source_request()
            raw_post = self.repository.get_raw_post(project_post.reddit_post_raw_id)
            request = self.repository.create_request_log(
                project_db_id=project.id,
                run_id=run_id,
                search_query_id=project_post.search_query_id,
                endpoint=f"/comments/{raw_post.reddit_post_id}",
                action="fetch_top_level_comments",
                subreddit=project_post.subreddit,
                query=project_post.query,
                request_params={"max_comments_per_post": max_comments_per_post},
            )
            request_started = monotonic()
            try:

                def operation():
                    return self.reddit.submission(id=raw_post.reddit_post_id)

                submission = (
                    operation()
                    if self.strict_stop
                    else self.retry_policy.run(operation, sleep=self.sleep)
                )
                if self.strict_stop:
                    submission.comment_limit = min(max_comments_per_post, remaining)
                submission.comments.replace_more(limit=0)
            except Exception as exc:
                summary.request_failures += 1
                summary.permanent_failures += 1
                log_event(
                    logger,
                    "reddit.collection.comments.request_failed",
                    stage="reddit_collection",
                    project_id=project_id,
                    run_id=run_id,
                    reddit_endpoint=f"/comments/{raw_post.reddit_post_id}",
                    subreddit=project_post.subreddit,
                    keyword=project_post.query,
                    error=str(exc),
                )
                self.repository.finish_request_log(
                    request.id,
                    error=str(exc),
                    elapsed_ms=_elapsed_ms(request_started),
                )
                if self.strict_stop:
                    raise
                continue

            for comment in islice(submission.comments, min(max_comments_per_post, remaining)):
                comment_snapshot = RedditCommentSnapshot.from_comment(
                    comment,
                    reddit_post_id=raw_post.reddit_post_id,
                    depth=0,
                )
                self.seen["reddit_comment"].add(comment_snapshot.reddit_comment_id)
                if (
                    self.strict_stop
                    and comment_snapshot.reddit_comment_id in self.before["reddit_comment"]
                ):
                    summary.duplicate_comments_skipped += 1
                    continue
                raw_comment, inserted = self.repository.upsert_raw_comment(comment_snapshot)
                _, linked = self.repository.link_project_comment(
                    project_db_id=project.id,
                    run_id=run_id,
                    search_query_id=project_post.search_query_id,
                    request_id=request.id,
                    raw_comment=raw_comment,
                    snapshot=comment_snapshot,
                )
                if inserted and linked:
                    summary.stored_comments += 1
                else:
                    summary.duplicate_comments_skipped += 1
            self.repository.finish_request_log(
                request.id,
                status_code=200,
                elapsed_ms=_elapsed_ms(request_started),
            )
        summary.elapsed_ms = _elapsed_ms(started)
        log_event(
            logger,
            "reddit.collection.comments.completed",
            stage="reddit_collection",
            project_id=project_id,
            run_id=run_id,
            status="completed",
            item_count_in=len(project_posts),
            item_count_out=summary.stored_comments,
            request_failures=summary.request_failures,
            duplicate_comments_skipped=summary.duplicate_comments_skipped,
        )
        return summary


def _elapsed_ms(started: float) -> int:
    return int((monotonic() - started) * 1000)


def _headers_from_listing(listing: list[Any]) -> dict[str, Any]:
    if not listing:
        return {}
    first = listing[0]
    return dict(getattr(first, "response_headers", {}) or {})
