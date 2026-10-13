"""Typed models for compliant Reddit collection."""

from typing import Any

from pydantic import BaseModel, Field


class RedditCredentialsStatus(BaseModel):
    """Validation result for Reddit API credentials."""

    valid: bool
    reason_codes: list[str] = Field(default_factory=list)
    message: str


class RateLimitSnapshot(BaseModel):
    """Normalized Reddit rate-limit headers captured from a response."""

    used: float | None = None
    remaining: float | None = None
    reset: float | None = None
    headers: dict[str, str] = Field(default_factory=dict)


class CollectionRunSummary(BaseModel):
    """User-facing and persisted summary for one Reddit collection run."""

    requested_queries: int = 0
    processed_queries: int = 0
    stored_posts: int = 0
    stored_comments: int = 0
    duplicate_posts_skipped: int = 0
    duplicate_comments_skipped: int = 0
    request_failures: int = 0
    permanent_failures: int = 0
    rate_limit_stops: int = 0
    elapsed_ms: int = 0

    def merge(self, other: "CollectionRunSummary") -> "CollectionRunSummary":
        """Add another summary into this one in-place and return self."""

        for field_name in type(self).model_fields:
            setattr(self, field_name, getattr(self, field_name) + getattr(other, field_name))
        return self


class RedditPostSnapshot(BaseModel):
    """Stable raw-post snapshot extracted from a PRAW-like submission."""

    reddit_post_id: str
    reddit_fullname: str | None = None
    subreddit: str | None = None
    title: str | None = None
    body: str | None = None
    author: str | None = None
    score: int | None = None
    upvote_ratio: float | None = None
    num_comments: int | None = None
    created_utc: int | None = None
    permalink: str | None = None
    url: str | None = None
    raw_json: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def from_submission(cls, submission: Any) -> "RedditPostSnapshot":
        """Create a snapshot from a PRAW-like submission object."""

        post_id = str(getattr(submission, "id"))
        subreddit = getattr(submission, "subreddit", None)
        raw_json = {
            "id": post_id,
            "name": getattr(submission, "name", None),
            "subreddit": str(subreddit) if subreddit is not None else None,
            "title": getattr(submission, "title", None),
            "selftext": getattr(submission, "selftext", None),
            "score": getattr(submission, "score", None),
            "upvote_ratio": getattr(submission, "upvote_ratio", None),
            "num_comments": getattr(submission, "num_comments", None),
            "created_utc": getattr(submission, "created_utc", None),
            "permalink": getattr(submission, "permalink", None),
            "url": getattr(submission, "url", None),
        }
        return cls(
            reddit_post_id=post_id,
            reddit_fullname=getattr(submission, "name", None),
            subreddit=str(subreddit) if subreddit is not None else None,
            title=getattr(submission, "title", None),
            body=getattr(submission, "selftext", None),
            author=_stringify_optional(getattr(submission, "author", None)),
            score=getattr(submission, "score", None),
            upvote_ratio=getattr(submission, "upvote_ratio", None),
            num_comments=getattr(submission, "num_comments", None),
            created_utc=_coerce_int(getattr(submission, "created_utc", None)),
            permalink=getattr(submission, "permalink", None),
            url=getattr(submission, "url", None),
            raw_json=raw_json,
        )


def _stringify_optional(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


def _coerce_int(value: Any) -> int | None:
    if value is None:
        return None
    return int(value)


class RedditCommentSnapshot(BaseModel):
    """Stable raw-comment snapshot extracted from a top-level PRAW-like comment."""

    reddit_comment_id: str
    reddit_fullname: str | None = None
    reddit_post_id: str
    parent_id: str | None = None
    body: str | None = None
    author: str | None = None
    score: int | None = None
    depth: int | None = 0
    created_utc: int | None = None
    permalink: str | None = None
    raw_json: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def from_comment(
        cls,
        comment: Any,
        *,
        reddit_post_id: str,
        depth: int = 0,
    ) -> "RedditCommentSnapshot":
        """Create a snapshot from a PRAW-like comment object."""

        comment_id = str(getattr(comment, "id"))
        raw_json = {
            "id": comment_id,
            "name": getattr(comment, "name", None),
            "link_id": getattr(comment, "link_id", None),
            "parent_id": getattr(comment, "parent_id", None),
            "body": getattr(comment, "body", None),
            "score": getattr(comment, "score", None),
            "depth": depth,
            "created_utc": getattr(comment, "created_utc", None),
            "permalink": getattr(comment, "permalink", None),
        }
        return cls(
            reddit_comment_id=comment_id,
            reddit_fullname=getattr(comment, "name", None),
            reddit_post_id=reddit_post_id,
            parent_id=getattr(comment, "parent_id", None),
            body=getattr(comment, "body", None),
            author=_stringify_optional(getattr(comment, "author", None)),
            score=getattr(comment, "score", None),
            depth=depth,
            created_utc=_coerce_int(getattr(comment, "created_utc", None)),
            permalink=getattr(comment, "permalink", None),
            raw_json=raw_json,
        )


class ExportImportSummary(BaseModel):
    """Distinct captured evidence and persistence counts for an offline batch."""

    run_id: int | None = None
    dry_run: bool = False
    captured_posts: int = 0
    captured_comments: int = 0
    stored_posts: int = 0
    stored_comments: int = 0
    duplicate_posts: int = 0
    duplicate_comments: int = 0
    in_file_duplicates: int = 0
    new_post_links: int = 0
    new_comment_links: int = 0
    missing_fields: dict[str, int] = Field(default_factory=dict)
    nested_replies: int = 0
    more_markers: list[dict[str, Any]] = Field(default_factory=list)
    post_coverage: dict[str, dict[str, Any]] = Field(default_factory=dict)
    items: list[dict[str, Any]] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
