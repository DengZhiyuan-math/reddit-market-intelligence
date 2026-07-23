from app.config import Settings
from app.reddit.client import RedditClientFactory, RedditConfigurationError


def _settings(**overrides) -> Settings:
    data = {
        "reddit_client_id": "client-id",
        "reddit_client_secret": "client-secret",
        "reddit_user_agent": "reddit-market-intel/0.1 by contact@example.com",
    }
    data.update(overrides)
    return Settings(_env_file=None, **data)


def test_validate_settings_reports_missing_credentials() -> None:
    status = RedditClientFactory.validate_settings(
        _settings(
            reddit_client_id=None,
            reddit_client_secret=None,
            reddit_user_agent=None,
        )
    )

    assert status.valid is False
    assert status.reason_codes == [
        "missing_reddit_client_id",
        "missing_reddit_client_secret",
        "missing_reddit_user_agent",
    ]


def test_validate_settings_rejects_placeholder_values() -> None:
    status = RedditClientFactory.validate_settings(
        _settings(
            reddit_client_id="changeme",
            reddit_client_secret="placeholder",
            reddit_user_agent="todo",
        )
    )

    assert status.valid is False
    assert "missing_reddit_client_id" in status.reason_codes
    assert "missing_reddit_client_secret" in status.reason_codes
    assert "missing_reddit_user_agent" in status.reason_codes


def test_validate_settings_rejects_short_user_agent() -> None:
    status = RedditClientFactory.validate_settings(_settings(reddit_user_agent="short"))

    assert status.valid is False
    assert status.reason_codes == ["reddit_user_agent_too_short"]


def test_validate_settings_rejects_non_descriptive_user_agent() -> None:
    status = RedditClientFactory.validate_settings(_settings(reddit_user_agent="plain user agent"))

    assert status.valid is False
    assert status.reason_codes == ["reddit_user_agent_not_descriptive"]


def test_validate_settings_accepts_descriptive_user_agent() -> None:
    status = RedditClientFactory.validate_settings(_settings())

    assert status.valid is True
    assert status.reason_codes == []


def test_create_read_only_client_passes_praw_configuration() -> None:
    captured = {}

    class FakeReddit:
        read_only = True

    def fake_reddit_factory(**kwargs):
        captured.update(kwargs)
        return FakeReddit()

    client = RedditClientFactory(_settings(reddit_ratelimit_seconds=9), fake_reddit_factory)

    reddit = client.create_read_only_client()

    assert reddit.read_only is True
    assert captured == {
        "client_id": "client-id",
        "client_secret": "client-secret",
        "user_agent": "reddit-market-intel/0.1 by contact@example.com",
        "ratelimit_seconds": 9,
    }


def test_create_read_only_client_rejects_invalid_settings_before_factory_call() -> None:
    called = False

    def fake_reddit_factory(**kwargs):
        nonlocal called
        called = True
        return object()

    client = RedditClientFactory(_settings(reddit_client_id=None), fake_reddit_factory)

    try:
        client.create_read_only_client()
    except RedditConfigurationError as exc:
        assert "missing_reddit_client_id" in str(exc)
    else:
        raise AssertionError("Expected RedditConfigurationError")

    assert called is False


def test_create_read_only_client_rejects_write_capable_client() -> None:
    class FakeReddit:
        read_only = False

    client = RedditClientFactory(_settings(), lambda **kwargs: FakeReddit())

    try:
        client.create_read_only_client()
    except RedditConfigurationError as exc:
        assert "read-only" in str(exc)
    else:
        raise AssertionError("Expected RedditConfigurationError")
