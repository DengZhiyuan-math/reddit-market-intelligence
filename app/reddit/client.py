"""Read-only Reddit API client construction and preflight validation."""

from collections.abc import Callable
from typing import Any

from app.config import Settings
from app.reddit.models import RedditCredentialsStatus

PLACEHOLDER_VALUES = {"", "changeme", "change-me", "placeholder", "todo", "none", "null"}
USER_AGENT_MIN_LENGTH = 12
USER_AGENT_HINTS = ("/", ":", "@", "contact", "reddit-market-intel", "market-intel")


class RedditConfigurationError(ValueError):
    """Raised when Reddit settings are not safe enough for collection."""


class RedditClientFactory:
    """Factory for validating settings and creating read-only Reddit clients."""

    def __init__(self, settings: Settings, reddit_factory: Callable[..., Any] | None = None) -> None:
        self.settings = settings
        self._reddit_factory = reddit_factory

    @staticmethod
    def validate_settings(settings: Settings) -> RedditCredentialsStatus:
        """Validate credential presence and descriptive User-Agent quality."""

        reason_codes: list[str] = []
        if _is_missing_or_placeholder(settings.reddit_client_id):
            reason_codes.append("missing_reddit_client_id")
        if _is_missing_or_placeholder(settings.reddit_client_secret):
            reason_codes.append("missing_reddit_client_secret")
        if _is_missing_or_placeholder(settings.reddit_user_agent):
            reason_codes.append("missing_reddit_user_agent")
        elif len(settings.reddit_user_agent.strip()) < USER_AGENT_MIN_LENGTH:
            reason_codes.append("reddit_user_agent_too_short")
        elif not _has_user_agent_hint(settings.reddit_user_agent):
            reason_codes.append("reddit_user_agent_not_descriptive")

        if reason_codes:
            return RedditCredentialsStatus(
                valid=False,
                reason_codes=reason_codes,
                message="Reddit credentials are not ready for collection.",
            )
        return RedditCredentialsStatus(
            valid=True,
            reason_codes=[],
            message="Reddit credentials are configured for read-only collection.",
        )

    def create_read_only_client(self) -> Any:
        """Create a read-only PRAW client after validating settings."""

        status = self.validate_settings(self.settings)
        if not status.valid:
            raise RedditConfigurationError(status.message + " " + ", ".join(status.reason_codes))

        reddit_factory = self._reddit_factory or _load_praw_reddit_factory()
        reddit = reddit_factory(
            client_id=self.settings.reddit_client_id,
            client_secret=self.settings.reddit_client_secret,
            user_agent=self.settings.reddit_user_agent,
            ratelimit_seconds=self.settings.reddit_ratelimit_seconds,
        )
        if getattr(reddit, "read_only", True) is not True:
            raise RedditConfigurationError("Reddit client must be read-only.")
        return reddit


def _load_praw_reddit_factory() -> Callable[..., Any]:
    import praw

    return praw.Reddit


def _is_missing_or_placeholder(value: str | None) -> bool:
    if value is None:
        return True
    return value.strip().lower() in PLACEHOLDER_VALUES


def _has_user_agent_hint(value: str) -> bool:
    normalized = value.strip().lower()
    return any(hint in normalized for hint in USER_AGENT_HINTS)
