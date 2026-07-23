"""Small structured logging helpers built on the standard library."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any


REDACTED = "[REDACTED]"
SENSITIVE_KEY_PARTS = ("api_key", "client_secret", "token", "password", "authorization")


def build_event(event: str, **fields: Any) -> dict[str, Any]:
    """Build a compact structured event, dropping fields that are not available."""

    payload = {"event": event, **fields}
    return {key: value for key, value in payload.items() if value is not None}


def redact_event(event: Mapping[str, Any]) -> dict[str, Any]:
    """Return a copy of an event with sensitive values redacted recursively."""

    return {key: _redact_value(key, value) for key, value in event.items()}


def log_event(
    logger: logging.Logger,
    event: str,
    *,
    level: int = logging.INFO,
    **fields: Any,
) -> dict[str, Any]:
    """Emit a redacted structured event and return the emitted payload for tests."""

    safe_event = redact_event(build_event(event, **fields))
    logger.log(level, "%s", safe_event)
    return safe_event


def _redact_value(key: str, value: Any) -> Any:
    if _is_sensitive_key(key):
        return REDACTED
    if isinstance(value, Mapping):
        return {nested_key: _redact_value(str(nested_key), nested_value) for nested_key, nested_value in value.items()}
    if isinstance(value, list):
        return [_redact_value(key, item) for item in value]
    return value


def _is_sensitive_key(key: str) -> bool:
    normalized = key.lower().replace("-", "_")
    return any(part in normalized for part in SENSITIVE_KEY_PARTS)
