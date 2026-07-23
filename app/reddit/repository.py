"""Database persistence helpers for Reddit collection."""

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import (
    PipelineRunRecord,
    ProjectRedditCommentRecord,
    ProjectRedditPostRecord,
    RedditCommentRawRecord,
    RedditApiRequestRecord,
    RedditPostRawRecord,
    ResearchProjectRecord,
    SearchQueryRecord,
)
from app.reddit.models import (
    CollectionRunSummary,
    RateLimitSnapshot,
    RedditCommentSnapshot,
    RedditPostSnapshot,
)
from app.reddit.rate_limiter import parse_rate_limit_headers


class RedditCollectionRepository:
    """Repository for collection runs and request-level provenance."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def start_collection_run(
        self,
        project_db_id: int,
        run_config: dict[str, Any],
    ) -> PipelineRunRecord:
        """Create a running pipeline run for Reddit collection."""

        run = PipelineRunRecord(
            project_id=project_db_id,
            stage="reddit_collection",
            status="running",
            run_config=run_config,
            summary={},
            started_at=datetime.now(UTC),
        )
        self.session.add(run)
        self.session.flush()
        return run

    def get_project_by_project_id(self, project_id: int) -> ResearchProjectRecord:
        """Return a database project by its durable project ID."""

        project = self.session.scalar(
            select(ResearchProjectRecord).where(ResearchProjectRecord.project_id == project_id)
        )
        if project is None:
            raise ValueError(f"Project not found in database: {project_id}")
        return project

    def list_pending_search_queries(
        self,
        project_db_id: int,
        limit: int | None = None,
    ) -> list[SearchQueryRecord]:
        """List pending Reddit search queries for a database project."""

        statement = (
            select(SearchQueryRecord)
            .where(
                SearchQueryRecord.project_id == project_db_id,
                SearchQueryRecord.source == "reddit",
                SearchQueryRecord.status == "pending",
            )
            .order_by(SearchQueryRecord.id)
        )
        if limit is not None:
            statement = statement.limit(limit)
        return list(self.session.scalars(statement))

    def mark_search_query_status(self, search_query_id: int, status: str) -> SearchQueryRecord:
        """Update a search query status."""

        query = self.session.get(SearchQueryRecord, search_query_id)
        if query is None:
            raise ValueError(f"Search query not found: {search_query_id}")
        query.status = status
        self.session.flush()
        return query

    def upsert_raw_post(self, snapshot: RedditPostSnapshot) -> tuple[RedditPostRawRecord, bool]:
        """Insert or return a globally deduplicated raw Reddit post."""

        existing = self.session.scalar(
            select(RedditPostRawRecord).where(
                RedditPostRawRecord.reddit_post_id == snapshot.reddit_post_id
            )
        )
        if existing is not None:
            return existing, False
        record = RedditPostRawRecord(
            reddit_post_id=snapshot.reddit_post_id,
            reddit_fullname=snapshot.reddit_fullname,
            subreddit=snapshot.subreddit,
            title=snapshot.title,
            body=snapshot.body,
            author=snapshot.author,
            score=snapshot.score,
            upvote_ratio=snapshot.upvote_ratio,
            num_comments=snapshot.num_comments,
            created_utc=snapshot.created_utc,
            permalink=snapshot.permalink,
            url=snapshot.url,
            raw_json=snapshot.raw_json,
        )
        self.session.add(record)
        self.session.flush()
        return record, True

    def link_project_post(
        self,
        *,
        project_db_id: int,
        run_id: int | None,
        search_query: SearchQueryRecord,
        request_id: int | None,
        raw_post: RedditPostRawRecord,
    ) -> tuple[ProjectRedditPostRecord, bool]:
        """Create or return project/query provenance for a raw Reddit post."""

        existing = self.session.scalar(
            select(ProjectRedditPostRecord).where(
                ProjectRedditPostRecord.project_id == project_db_id,
                ProjectRedditPostRecord.reddit_post_raw_id == raw_post.id,
                ProjectRedditPostRecord.search_query_id == search_query.id,
            )
        )
        if existing is not None:
            return existing, False
        record = ProjectRedditPostRecord(
            project_id=project_db_id,
            run_id=run_id,
            search_query_id=search_query.id,
            request_id=request_id,
            reddit_post_raw_id=raw_post.id,
            subreddit=search_query.subreddit,
            query=search_query.query,
            sort=search_query.sort,
            time_filter=search_query.time_filter,
            filters_json=search_query.filters_json,
        )
        self.session.add(record)
        self.session.flush()
        return record, True

    def link_project_post_without_query(
        self,
        *,
        project_db_id: int,
        run_id: int | None,
        raw_post: RedditPostRawRecord,
        subreddit: str | None,
        query: str | None,
        filters_json: dict[str, Any] | None = None,
    ) -> tuple[ProjectRedditPostRecord, bool]:
        """Create or return project provenance for a fallback-discovered post."""

        existing = self.session.scalar(
            select(ProjectRedditPostRecord).where(
                ProjectRedditPostRecord.project_id == project_db_id,
                ProjectRedditPostRecord.reddit_post_raw_id == raw_post.id,
                ProjectRedditPostRecord.search_query_id.is_(None),
            )
        )
        if existing is not None:
            return existing, False
        record = ProjectRedditPostRecord(
            project_id=project_db_id,
            run_id=run_id,
            search_query_id=None,
            request_id=None,
            reddit_post_raw_id=raw_post.id,
            subreddit=subreddit,
            query=query,
            filters_json=filters_json or {},
        )
        self.session.add(record)
        self.session.flush()
        return record, True

    def list_project_posts_for_comment_collection(
        self,
        project_db_id: int,
        run_id: int | None = None,
        limit: int | None = None,
    ) -> list[ProjectRedditPostRecord]:
        """List project post associations eligible for top-level comment collection."""

        statement = (
            select(ProjectRedditPostRecord)
            .where(ProjectRedditPostRecord.project_id == project_db_id)
            .order_by(ProjectRedditPostRecord.id)
        )
        if run_id is not None:
            statement = statement.where(ProjectRedditPostRecord.run_id == run_id)
        if limit is not None:
            statement = statement.limit(limit)
        return list(self.session.scalars(statement))

    def get_raw_post(self, raw_post_id: int) -> RedditPostRawRecord:
        """Return a raw post by internal row ID."""

        raw_post = self.session.get(RedditPostRawRecord, raw_post_id)
        if raw_post is None:
            raise ValueError(f"Raw Reddit post not found: {raw_post_id}")
        return raw_post

    def get_search_query(self, search_query_id: int | None) -> SearchQueryRecord | None:
        """Return a search query by ID when available."""

        if search_query_id is None:
            return None
        return self.session.get(SearchQueryRecord, search_query_id)

    def upsert_raw_comment(
        self,
        snapshot: RedditCommentSnapshot,
    ) -> tuple[RedditCommentRawRecord, bool]:
        """Insert or return a globally deduplicated raw Reddit comment."""

        existing = self.session.scalar(
            select(RedditCommentRawRecord).where(
                RedditCommentRawRecord.reddit_comment_id == snapshot.reddit_comment_id
            )
        )
        if existing is not None:
            return existing, False
        record = RedditCommentRawRecord(
            reddit_comment_id=snapshot.reddit_comment_id,
            reddit_fullname=snapshot.reddit_fullname,
            reddit_post_id=snapshot.reddit_post_id,
            parent_id=snapshot.parent_id,
            body=snapshot.body,
            author=snapshot.author,
            score=snapshot.score,
            depth=snapshot.depth,
            created_utc=snapshot.created_utc,
            permalink=snapshot.permalink,
            raw_json=snapshot.raw_json,
        )
        self.session.add(record)
        self.session.flush()
        return record, True

    def link_project_comment(
        self,
        *,
        project_db_id: int,
        run_id: int | None,
        search_query_id: int | None,
        request_id: int | None,
        raw_comment: RedditCommentRawRecord,
    ) -> tuple[ProjectRedditCommentRecord, bool]:
        """Create or return project/query provenance for a raw Reddit comment."""

        existing = self.session.scalar(
            select(ProjectRedditCommentRecord).where(
                ProjectRedditCommentRecord.project_id == project_db_id,
                ProjectRedditCommentRecord.reddit_comment_raw_id == raw_comment.id,
                ProjectRedditCommentRecord.search_query_id == search_query_id,
            )
        )
        if existing is not None:
            return existing, False
        query = self.get_search_query(search_query_id)
        record = ProjectRedditCommentRecord(
            project_id=project_db_id,
            run_id=run_id,
            search_query_id=search_query_id,
            request_id=request_id,
            reddit_comment_raw_id=raw_comment.id,
            subreddit=query.subreddit if query is not None else None,
            query=query.query if query is not None else None,
            sort=query.sort if query is not None else None,
            time_filter=query.time_filter if query is not None else None,
            filters_json=query.filters_json if query is not None else {},
        )
        self.session.add(record)
        self.session.flush()
        return record, True

    def complete_collection_run(
        self,
        run_id: int,
        status: str,
        summary: CollectionRunSummary,
    ) -> PipelineRunRecord:
        """Persist final run status and summary counters."""

        run = self.session.get(PipelineRunRecord, run_id)
        if run is None:
            raise ValueError(f"Collection run not found: {run_id}")
        run.status = status
        run.summary = summary.model_dump(mode="json")
        run.completed_at = datetime.now(UTC)
        self.session.flush()
        return run

    def create_request_log(
        self,
        *,
        project_db_id: int,
        run_id: int | None,
        endpoint: str,
        action: str,
        search_query_id: int | None = None,
        subreddit: str | None = None,
        query: str | None = None,
        request_params: dict[str, Any] | None = None,
    ) -> RedditApiRequestRecord:
        """Create a pending request log row before a Reddit operation runs."""

        request = RedditApiRequestRecord(
            project_id=project_db_id,
            run_id=run_id,
            search_query_id=search_query_id,
            endpoint=endpoint,
            action=action,
            subreddit=subreddit,
            query=query,
            request_params=request_params or {},
        )
        self.session.add(request)
        self.session.flush()
        return request

    def finish_request_log(
        self,
        request_id: int,
        *,
        status_code: int | None = None,
        error: str | None = None,
        elapsed_ms: int | None = None,
        rate_limit: RateLimitSnapshot | None = None,
        response_headers: Mapping[str, Any] | None = None,
    ) -> RedditApiRequestRecord:
        """Finish a request log with outcome, timing, and rate-limit metadata."""

        request = self.session.get(RedditApiRequestRecord, request_id)
        if request is None:
            raise ValueError(f"Reddit API request log not found: {request_id}")
        snapshot = rate_limit or parse_rate_limit_headers(response_headers)
        request.status_code = status_code
        request.error = error
        request.elapsed_ms = elapsed_ms
        request.rate_limit_used = snapshot.used
        request.rate_limit_remaining = snapshot.remaining
        request.rate_limit_reset = snapshot.reset
        request.response_headers = dict(response_headers or snapshot.headers)
        request.completed_at = datetime.now(UTC)
        self.session.flush()
        return request
