"""Rate-limit and retry helpers for Reddit collection."""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from time import sleep as default_sleep
from typing import Any

from app.reddit.models import RateLimitSnapshot

RATE_LIMIT_HEADER_NAMES = {
    "x-ratelimit-used": "used",
    "x-ratelimit-remaining": "remaining",
    "x-ratelimit-reset": "reset",
}


def parse_rate_limit_headers(headers: Mapping[str, Any] | None) -> RateLimitSnapshot:
    """Parse Reddit `X-Ratelimit-*` headers into numeric fields when present."""

    if not headers:
        return RateLimitSnapshot()
    normalized = {str(key).lower(): str(value) for key, value in headers.items()}
    values: dict[str, float | None] = {"used": None, "remaining": None, "reset": None}
    for header_name, field_name in RATE_LIMIT_HEADER_NAMES.items():
        values[field_name] = _parse_float(normalized.get(header_name))
    return RateLimitSnapshot(
        used=values["used"],
        remaining=values["remaining"],
        reset=values["reset"],
        headers=dict(normalized),
    )


def should_stop_for_rate_limit(snapshot: RateLimitSnapshot, min_remaining: float) -> bool:
    """Return true when collection should stop instead of pressuring Reddit limits."""

    return snapshot.remaining is not None and snapshot.remaining <= min_remaining


@dataclass(frozen=True)
class RetryPolicy:
    """Bounded retry policy for transient Reddit collection failures."""

    max_attempts: int = 3
    backoff_seconds: float = 1.0
    transient_status_codes: tuple[int, ...] = (408, 425, 429, 500, 502, 503, 504)

    def is_transient_error(self, exc: BaseException) -> bool:
        """Classify common timeout, rate-limit, and server errors as transient."""

        status_code = getattr(exc, "status_code", None) or getattr(exc, "status", None)
        if status_code in self.transient_status_codes:
            return True
        name = exc.__class__.__name__.lower()
        message = str(exc).lower()
        transient_tokens = ("timeout", "temporar", "rate limit", "too many requests", "server error")
        return any(token in name or token in message for token in transient_tokens)

    def run(self, operation: Callable[[], Any], sleep: Callable[[float], None] | None = None) -> Any:
        """Run an operation with bounded retries and injectable sleep."""

        sleeper = sleep or default_sleep
        last_error: BaseException | None = None
        for attempt in range(1, self.max_attempts + 1):
            try:
                return operation()
            except Exception as exc:
                last_error = exc
                if attempt >= self.max_attempts or not self.is_transient_error(exc):
                    raise
                sleeper(self.backoff_seconds * attempt)
        if last_error is not None:
            raise last_error
        raise RuntimeError("RetryPolicy operation did not run")


def _parse_float(value: str | None) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except ValueError:
        return None
