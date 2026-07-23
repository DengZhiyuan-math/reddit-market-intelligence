from contextlib import contextmanager

from typer.testing import CliRunner

import app.cli as cli
from app.cli import app
from app.config import Settings
from app.reddit.models import CollectionRunSummary
from app.reddit.service import RedditCollectionServiceError, run_reddit_collection
from app.search.models import DiscoveredUrl, DiscoveryRunSummary
from app.web_fallback.models import WebFallbackIngestionSummary
from tests.reddit.fakes import FakeReddit, FakeSubmission, FakeSubreddit
from tests.reddit.test_collector_posts import make_session, seed_project_with_query


runner = CliRunner()


@contextmanager
def fake_session_scope():
    yield object()


def test_service_returns_collection_run_summary() -> None:
    session = make_session()
    seed_project_with_query(session)
    reddit = FakeReddit({"askswitzerland": FakeSubreddit([FakeSubmission(id="abc")])})
    settings = Settings(
        _env_file=None,
        reddit_client_id="client-id",
        reddit_client_secret="client-secret",
        reddit_user_agent="reddit-market-intel/0.1 by contact@example.com",
    )

    summary = run_reddit_collection(
        session,
        project_id=1,
        limit_per_query=5,
        max_comments_per_post=0,
        collect_comments=False,
        settings=settings,
        reddit_client=reddit,
    )

    assert isinstance(summary, CollectionRunSummary)
    assert summary.stored_posts == 1
    assert summary.requested_queries == 1


def test_service_validation_failure_prevents_collection() -> None:
    session = make_session()
    seed_project_with_query(session)
    reddit = FakeReddit({"askswitzerland": FakeSubreddit([FakeSubmission(id="abc")])})

    try:
        run_reddit_collection(
            session,
            project_id=1,
            limit_per_query=5,
            max_comments_per_post=0,
            collect_comments=False,
            settings=Settings(_env_file=None),
            reddit_client=reddit,
        )
    except RedditCollectionServiceError as exc:
        assert "missing_reddit_client_id" in str(exc)
    else:
        raise AssertionError("Expected RedditCollectionServiceError")

    assert reddit.subreddits["askswitzerland"].search_calls == []


def test_reddit_validate_credentials_success(monkeypatch) -> None:
    monkeypatch.setenv("REDDIT_CLIENT_ID", "client-id")
    monkeypatch.setenv("REDDIT_CLIENT_SECRET", "client-secret")
    monkeypatch.setenv("REDDIT_USER_AGENT", "reddit-market-intel/0.1 by contact@example.com")

    result = runner.invoke(app, ["reddit", "validate-credentials"])

    assert result.exit_code == 0
    assert "configured for read-only collection" in result.output


def test_reddit_validate_credentials_failure_is_readable(monkeypatch) -> None:
    monkeypatch.delenv("REDDIT_CLIENT_ID", raising=False)
    monkeypatch.delenv("REDDIT_CLIENT_SECRET", raising=False)
    monkeypatch.delenv("REDDIT_USER_AGENT", raising=False)

    result = runner.invoke(app, ["reddit", "validate-credentials"])

    assert result.exit_code == 1
    assert "Reddit credentials are not ready" in result.output
    assert "missing_reddit_client_id" in result.output


def test_reddit_collect_prints_summary(monkeypatch) -> None:
    monkeypatch.setenv("REDDIT_CLIENT_ID", "client-id")
    monkeypatch.setenv("REDDIT_CLIENT_SECRET", "client-secret")
    monkeypatch.setenv("REDDIT_USER_AGENT", "reddit-market-intel/0.1 by contact@example.com")
    monkeypatch.setattr(cli, "session_scope", fake_session_scope)
    monkeypatch.setattr(
        cli,
        "run_reddit_collection",
        lambda session,
        project_id,
        limit_per_query,
        max_comments_per_post,
        collect_comments=True,
        settings=None: (
            CollectionRunSummary(
                requested_queries=2,
                stored_posts=3,
                stored_comments=4,
                duplicate_posts_skipped=1,
                duplicate_comments_skipped=1,
                elapsed_ms=25,
            )
        ),
    )

    result = runner.invoke(
        app,
        [
            "reddit",
            "collect",
            "--project-id",
            "1",
            "--limit-per-query",
            "5",
            "--max-comments-per-post",
            "2",
        ],
    )

    assert result.exit_code == 0
    assert "Collection source selection" in result.output
    assert "reddit_api" in result.output
    assert "Reddit collection summary" in result.output
    assert "stored_posts" in result.output
    assert "stored_comments" in result.output


def test_reddit_collect_failure_is_readable(monkeypatch) -> None:
    monkeypatch.setenv("REDDIT_CLIENT_ID", "client-id")
    monkeypatch.setenv("REDDIT_CLIENT_SECRET", "client-secret")
    monkeypatch.setenv("REDDIT_USER_AGENT", "reddit-market-intel/0.1 by contact@example.com")
    monkeypatch.setattr(cli, "session_scope", fake_session_scope)

    def fail(
        session,
        project_id,
        limit_per_query,
        max_comments_per_post,
        collect_comments=True,
        settings=None,
    ):
        raise RedditCollectionServiceError("credentials missing")

    monkeypatch.setattr(cli, "run_reddit_collection", fail)

    result = runner.invoke(app, ["reddit", "collect", "--project-id", "1"])

    assert result.exit_code == 1
    assert "Reddit collection failed" in result.output
    assert "credentials missing" in result.output


def test_reddit_collect_blocks_when_api_and_fallback_unavailable(monkeypatch) -> None:
    monkeypatch.delenv("REDDIT_CLIENT_ID", raising=False)
    monkeypatch.delenv("REDDIT_CLIENT_SECRET", raising=False)
    monkeypatch.delenv("REDDIT_USER_AGENT", raising=False)

    result = runner.invoke(app, ["reddit", "collect", "--project-id", "1"])

    assert result.exit_code == 1
    assert "Collection source selection" in result.output
    assert "web_fallback_disabled" in result.output


def test_reddit_discover_urls_prints_dry_run_summary(monkeypatch) -> None:
    monkeypatch.setattr(cli, "session_scope", fake_session_scope)
    monkeypatch.setattr(
        cli,
        "run_url_discovery",
        lambda session, project_id, query, limit, dry_run: DiscoveryRunSummary(
            provider="fake_search",
            query=query,
            discovered=1,
            dry_run=dry_run,
            urls=[
                DiscoveredUrl(
                    url="https://www.reddit.com/r/askswitzerland/comments/abc/title",
                    title="Tutoring Switzerland",
                    snippet="Parents discuss tutoring.",
                )
            ],
        ),
    )

    result = runner.invoke(
        app,
        [
            "reddit",
            "discover-urls",
            "--project-id",
            "1",
            "--query",
            "site:reddit.com tutoring Switzerland",
            "--dry-run",
        ],
    )

    assert result.exit_code == 0
    assert "URL discovery summary" in result.output
    assert "fake_search" in result.output
    assert "https://www.reddit.com/r/askswitzerland/comments/abc/title" in result.output


def test_reddit_collect_fallback_prints_summary(monkeypatch) -> None:
    monkeypatch.setattr(cli, "session_scope", fake_session_scope)
    monkeypatch.setattr(
        cli,
        "run_web_fallback_ingestion",
        lambda session, project_id, limit: WebFallbackIngestionSummary(
            candidates=2,
            fetched=2,
            stored_posts=1,
            stored_comments=3,
        ),
    )

    result = runner.invoke(app, ["reddit", "collect-fallback", "--project-id", "1", "--limit", "2"])

    assert result.exit_code == 0
    assert "Web fallback ingestion summary" in result.output
    assert "stored_posts" in result.output
