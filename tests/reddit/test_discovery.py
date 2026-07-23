"""Tests for search-based Reddit URL discovery."""

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.config import Settings
from app.db.base import Base
from app.db.models import DiscoveredUrlRecord, ResearchProjectRecord
from app.search.models import DiscoveredUrl
from app.search.provider import GoogleCustomSearchProvider, parse_google_custom_search_results
from app.search.repository import normalize_url
from app.search.service import run_url_discovery


class FakeProvider:
    provider_name = "fake_search"

    def __init__(self, urls: list[DiscoveredUrl]) -> None:
        self.urls = urls

    def search(self, query: str, *, limit: int) -> list[DiscoveredUrl]:
        return self.urls[:limit]


def make_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    session.add(
        ResearchProjectRecord(
            project_id=1,
            slug="zurich-tutoring",
            topic="Swiss tutoring market",
            access_mode="personal",
        )
    )
    session.commit()
    return session


def test_google_custom_search_settings_require_key_and_engine_id() -> None:
    status = GoogleCustomSearchProvider.validate_settings(Settings(_env_file=None))

    assert status.valid is False
    assert status.reason_codes == [
        "missing_google_custom_search_api_key",
        "missing_google_custom_search_engine_id",
    ]


def test_parse_google_custom_search_results_extracts_link_title_snippet() -> None:
    results = parse_google_custom_search_results(
        {
            "items": [
                {
                    "link": "https://www.reddit.com/r/askswitzerland/comments/abc/test/",
                    "title": "Tutoring Switzerland",
                    "snippet": "Parents discuss tutoring.",
                },
                {"title": "No link"},
            ]
        },
        limit=10,
    )

    assert len(results) == 1
    assert results[0].title == "Tutoring Switzerland"
    assert results[0].snippet == "Parents discuss tutoring."


def test_normalize_url_removes_fragment_and_trailing_slash() -> None:
    assert (
        normalize_url("https://WWW.Reddit.com/r/test/comments/abc/title/#thing")
        == "https://www.reddit.com/r/test/comments/abc/title"
    )


def test_run_url_discovery_dry_run_does_not_persist() -> None:
    session = make_session()
    provider = FakeProvider([DiscoveredUrl(url="https://reddit.com/r/test/comments/abc/title")])

    summary = run_url_discovery(
        session,
        project_id=1,
        query="site:reddit.com tutoring Switzerland",
        limit=10,
        dry_run=True,
        provider=provider,
    )

    assert summary.discovered == 1
    assert summary.stored == 0
    assert session.scalars(select(DiscoveredUrlRecord)).all() == []


def test_run_url_discovery_persists_and_deduplicates_urls() -> None:
    session = make_session()
    provider = FakeProvider(
        [
            DiscoveredUrl(
                url="https://reddit.com/r/test/comments/abc/title/",
                title="First",
                snippet="Snippet",
            ),
            DiscoveredUrl(url="https://reddit.com/r/test/comments/abc/title#fragment"),
        ]
    )

    first = run_url_discovery(
        session,
        project_id=1,
        query="site:reddit.com tutoring Switzerland",
        limit=10,
        dry_run=False,
        provider=provider,
    )
    second = run_url_discovery(
        session,
        project_id=1,
        query="site:reddit.com tutoring Switzerland",
        limit=10,
        dry_run=False,
        provider=provider,
    )

    assert first.stored == 1
    assert first.duplicates == 1
    assert second.stored == 0
    assert second.duplicates == 2
    records = session.scalars(select(DiscoveredUrlRecord)).all()
    assert len(records) == 1
    assert records[0].title == "First"
