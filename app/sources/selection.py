"""API-first collection source selection."""

from enum import StrEnum

from pydantic import BaseModel, Field

from app.config import Settings
from app.reddit.client import RedditClientFactory


class CollectionSourceMode(StrEnum):
    """Supported high-level collection source modes."""

    REDDIT_API = "reddit_api"
    WEB_FALLBACK_STATIC = "web_fallback_static"
    WEB_FALLBACK_BROWSER = "web_fallback_browser"
    UNAVAILABLE = "unavailable"


class SourceSelection(BaseModel):
    """Result of deciding which collection source is allowed for a run."""

    mode: CollectionSourceMode
    can_collect: bool
    api_available: bool
    fallback_enabled: bool
    reason_codes: list[str] = Field(default_factory=list)
    risk_flags: list[str] = Field(default_factory=list)
    message: str


def select_collection_source(settings: Settings) -> SourceSelection:
    """Prefer Reddit API and only select fallback when explicitly enabled."""

    guardrail_reasons = validate_fallback_guardrails(settings)
    if guardrail_reasons:
        return SourceSelection(
            mode=CollectionSourceMode.UNAVAILABLE,
            can_collect=False,
            api_available=False,
            fallback_enabled=settings.web_fallback_enabled,
            reason_codes=guardrail_reasons,
            risk_flags=["fallback_guardrail_violation"],
            message="Fallback configuration violates collection guardrails.",
        )

    credential_status = RedditClientFactory.validate_settings(settings)
    api_available = settings.reddit_api_enabled and credential_status.valid
    if api_available:
        return SourceSelection(
            mode=CollectionSourceMode.REDDIT_API,
            can_collect=True,
            api_available=True,
            fallback_enabled=settings.web_fallback_enabled,
            message="Official Reddit API collection selected.",
        )

    reasons: list[str] = []
    if not settings.reddit_api_enabled:
        reasons.append("reddit_api_disabled")
    reasons.extend(credential_status.reason_codes)

    if not settings.web_fallback_enabled:
        return SourceSelection(
            mode=CollectionSourceMode.UNAVAILABLE,
            can_collect=False,
            api_available=False,
            fallback_enabled=False,
            reason_codes=[*reasons, "web_fallback_disabled"],
            message="Reddit API is unavailable and web fallback is disabled.",
        )

    fallback_mode = _fallback_mode(settings.web_fallback_mode)
    return SourceSelection(
        mode=fallback_mode,
        can_collect=True,
        api_available=False,
        fallback_enabled=True,
        reason_codes=reasons,
        risk_flags=["public_web_fallback", "not_official_reddit_api"],
        message="Public-web fallback collection selected.",
    )


def validate_fallback_guardrails(settings: Settings) -> list[str]:
    """Return reason codes for disallowed fallback settings."""

    reasons: list[str] = []
    if settings.web_fallback_proxy_rotation_enabled:
        reasons.append("web_fallback_proxy_rotation_disallowed")
    if settings.web_fallback_captcha_bypass_enabled:
        reasons.append("web_fallback_captcha_bypass_disallowed")
    if settings.web_fallback_login_enabled:
        reasons.append("web_fallback_login_scraping_disallowed")
    if settings.web_fallback_fake_user_agent_enabled:
        reasons.append("web_fallback_fake_user_agent_disallowed")
    if settings.web_fallback_mode not in {"static", "browser"}:
        reasons.append("web_fallback_mode_invalid")
    return reasons


def _fallback_mode(value: str) -> CollectionSourceMode:
    if value == "browser":
        return CollectionSourceMode.WEB_FALLBACK_BROWSER
    return CollectionSourceMode.WEB_FALLBACK_STATIC
