"""Models for public-web fallback ingestion."""

from pydantic import BaseModel, Field

from app.reddit.models import RedditCommentSnapshot, RedditPostSnapshot


PARSER_VERSION = "reddit-html-v1"


class FetchResult(BaseModel):
    """One public-web fetch result."""

    url: str
    final_url: str | None = None
    status_code: int | None = None
    text: str | None = None
    error: str | None = None
    acquisition_method: str = "web_static"


class ParsedFallbackPage(BaseModel):
    """Parsed Reddit discussion content from a public page."""

    post: RedditPostSnapshot | None = None
    comments: list[RedditCommentSnapshot] = Field(default_factory=list)
    content_available: bool = False
    exclusion_reason: str | None = None


class WebFallbackIngestionSummary(BaseModel):
    """Summary for one fallback ingestion run."""

    candidates: int = 0
    fetched: int = 0
    stored_posts: int = 0
    stored_comments: int = 0
    duplicate_posts: int = 0
    duplicate_comments: int = 0
    excluded: int = 0
    errors: int = 0
