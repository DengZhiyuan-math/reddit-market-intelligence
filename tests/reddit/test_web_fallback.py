"""Tests for public-web fallback ingestion."""

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.config import Settings
from app.db.base import Base
from app.db.models import (
    DiscoveredUrlRecord,
    ProjectRedditPostRecord,
    RedditPostRawRecord,
    ResearchProjectRecord,
    WebFallbackFetchRecord,
)
from app.web_fallback.models import FetchResult
from app.web_fallback.parser import parse_reddit_discussion_html
from app.web_fallback.service import WebFallbackServiceError, run_web_fallback_ingestion


HTML = """
<html>
  <head>
    <meta property="og:title" content="Tutoring in Switzerland">
    <meta name="description" content="Parents discuss math tutoring in Zurich.">
  </head>
  <body>
    <div data-reddit-comment-id="c1">We need help with Gymnasium math.</div>
  </body>
</html>
"""


class FakeFetcher:
    acquisition_method = "web_static"

    def __init__(self, text: str | None = HTML, status_code: int = 200, error: str | None = None):
        self.text = text
        self.status_code = status_code
        self.error = error

    def fetch(self, url: str) -> FetchResult:
        return FetchResult(
            url=url,
            final_url=url,
            status_code=self.status_code,
            text=self.text,
            error=self.error,
            acquisition_method=self.acquisition_method,
        )


def make_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    project = ResearchProjectRecord(
        project_id=1,
        slug="zurich-tutoring",
        topic="Swiss tutoring market",
        access_mode="personal",
    )
    session.add(project)
    session.flush()
    session.add(
        DiscoveredUrlRecord(
            project_id=project.id,
            provider="fake_search",
            query="site:reddit.com tutoring Switzerland",
            url="https://www.reddit.com/r/askswitzerland/comments/abc/title/",
            normalized_url="https://www.reddit.com/r/askswitzerland/comments/abc/title",
        )
    )
    session.commit()
    return session


def fallback_settings(**overrides) -> Settings:
    data = {
        "reddit_api_enabled": False,
        "web_fallback_enabled": True,
        "web_fallback_mode": "static",
    }
    data.update(overrides)
    return Settings(_env_file=None, **data)


def test_parse_reddit_discussion_html_extracts_post_and_top_level_comments() -> None:
    parsed = parse_reddit_discussion_html(
        HTML,
        url="https://www.reddit.com/r/askswitzerland/comments/abc/title/",
    )

    assert parsed.content_available is True
    assert parsed.post is not None
    assert parsed.post.reddit_post_id == "web_abc"
    assert parsed.post.subreddit == "askswitzerland"
    assert parsed.comments[0].body == "We need help with Gymnasium math."


def test_parse_reddit_discussion_html_excludes_deleted_content() -> None:
    parsed = parse_reddit_discussion_html(
        "<html><body>[deleted]</body></html>",
        url="https://www.reddit.com/r/askswitzerland/comments/abc/title/",
    )

    assert parsed.content_available is False
    assert parsed.exclusion_reason == "deleted_or_removed"


def test_parse_reddit_discussion_html_excludes_verification_page() -> None:
    parsed = parse_reddit_discussion_html(
        "<html><head><title>Reddit - Please wait for verification</title></head></html>",
        url="https://www.reddit.com/r/askswitzerland/comments/abc/title/",
    )

    assert parsed.content_available is False
    assert parsed.exclusion_reason == "verification_required"


def test_web_fallback_requires_explicit_fallback_enabled() -> None:
    session = make_session()

    try:
        run_web_fallback_ingestion(
            session,
            project_id=1,
            limit=10,
            settings=Settings(_env_file=None),
            fetcher=FakeFetcher(),
        )
    except WebFallbackServiceError as exc:
        assert "web_fallback_disabled" in str(exc)
    else:
        raise AssertionError("Expected WebFallbackServiceError")


def test_web_fallback_ingests_parseable_discovered_url() -> None:
    session = make_session()

    summary = run_web_fallback_ingestion(
        session,
        project_id=1,
        limit=10,
        settings=fallback_settings(),
        fetcher=FakeFetcher(),
    )

    assert summary.candidates == 1
    assert summary.fetched == 1
    assert summary.stored_posts == 1
    assert summary.stored_comments == 1
    assert session.scalar(select(RedditPostRawRecord)).reddit_post_id == "web_abc"
    assert session.scalar(select(ProjectRedditPostRecord)) is not None
    fetch = session.scalar(select(WebFallbackFetchRecord))
    assert fetch is not None
    assert fetch.acquisition_method == "web_static"
    assert fetch.content_available is True
    assert "public_web_fallback" in fetch.risk_flags


def test_web_fallback_excludes_parse_failed_content_from_evidence() -> None:
    session = make_session()

    summary = run_web_fallback_ingestion(
        session,
        project_id=1,
        limit=10,
        settings=fallback_settings(),
        fetcher=FakeFetcher(text="<html><body>[removed]</body></html>"),
    )

    assert summary.excluded == 1
    assert session.scalars(select(RedditPostRawRecord)).all() == []
    fetch = session.scalar(select(WebFallbackFetchRecord))
    assert fetch.content_available is False
