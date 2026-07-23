"""Database settings tests."""

from app.config import Settings


def test_database_settings_defaults_are_local_and_non_secret() -> None:
    settings = Settings(_env_file=None)

    assert settings.database_url.startswith("postgresql+psycopg://")
    assert "localhost:5432/reddit_market_intel" in settings.database_url
    assert settings.database_echo is False
    assert "REDDIT_CLIENT_SECRET" not in settings.database_url


def test_database_settings_can_be_overridden(monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://user:pass@db:5432/custom")
    monkeypatch.setenv("DATABASE_ECHO", "true")

    settings = Settings(_env_file=None)

    assert settings.database_url == "postgresql+psycopg://user:pass@db:5432/custom"
    assert settings.database_echo is True
