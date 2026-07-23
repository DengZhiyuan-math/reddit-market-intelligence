"""Tests for API-first collection source selection."""

from app.config import Settings
from app.sources.selection import CollectionSourceMode, select_collection_source


def _settings(**overrides) -> Settings:
    data = {
        "reddit_client_id": "client-id",
        "reddit_client_secret": "client-secret",
        "reddit_user_agent": "reddit-market-intel/0.1 by contact@example.com",
    }
    data.update(overrides)
    return Settings(_env_file=None, **data)


def test_source_selection_prefers_reddit_api_when_credentials_are_valid() -> None:
    selection = select_collection_source(_settings(web_fallback_enabled=True))

    assert selection.mode == CollectionSourceMode.REDDIT_API
    assert selection.can_collect is True
    assert selection.api_available is True
    assert selection.risk_flags == []


def test_source_selection_blocks_when_api_unavailable_and_fallback_disabled() -> None:
    selection = select_collection_source(_settings(reddit_client_id=None))

    assert selection.mode == CollectionSourceMode.UNAVAILABLE
    assert selection.can_collect is False
    assert "missing_reddit_client_id" in selection.reason_codes
    assert "web_fallback_disabled" in selection.reason_codes


def test_source_selection_allows_explicit_static_fallback_when_api_unavailable() -> None:
    selection = select_collection_source(
        _settings(
            reddit_api_enabled=False,
            web_fallback_enabled=True,
            web_fallback_mode="static",
        )
    )

    assert selection.mode == CollectionSourceMode.WEB_FALLBACK_STATIC
    assert selection.can_collect is True
    assert selection.api_available is False
    assert "public_web_fallback" in selection.risk_flags


def test_source_selection_rejects_evasion_like_fallback_settings() -> None:
    selection = select_collection_source(
        _settings(
            reddit_api_enabled=False,
            web_fallback_enabled=True,
            web_fallback_proxy_rotation_enabled=True,
            web_fallback_captcha_bypass_enabled=True,
            web_fallback_login_enabled=True,
            web_fallback_fake_user_agent_enabled=True,
        )
    )

    assert selection.mode == CollectionSourceMode.UNAVAILABLE
    assert selection.can_collect is False
    assert "web_fallback_proxy_rotation_disallowed" in selection.reason_codes
    assert "web_fallback_captcha_bypass_disallowed" in selection.reason_codes
    assert "web_fallback_login_scraping_disallowed" in selection.reason_codes
    assert "web_fallback_fake_user_agent_disallowed" in selection.reason_codes
