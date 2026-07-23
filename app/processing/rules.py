"""Pure rule helpers for content quality and rejection decisions."""

import hashlib

from app.processing.models import (
    DUPLICATE_TEXT,
    NEGATIVE_KEYWORD,
    OBVIOUS_SPAM,
    ProcessingReason,
    ReasonSeverity,
)
from app.topic_planning.models import dedupe_normalized


def build_reason(
    code: str,
    explanation: str,
    severity: str = ReasonSeverity.LOW_QUALITY.value,
) -> ProcessingReason:
    """Create a persisted reason object with code and readable explanation."""

    return ProcessingReason(code=code, severity=severity, explanation=explanation)


def normalize_negative_keywords(values: list[str]) -> list[str]:
    """Normalize negative keywords for case-insensitive matching."""

    return [value.casefold() for value in dedupe_normalized(values)]


def contains_negative_keyword(text: str, keywords: list[str]) -> bool:
    """Return whether text contains any configured negative keyword."""

    haystack = text.casefold()
    return any(keyword in haystack for keyword in normalize_negative_keywords(keywords))


def negative_keyword_reason(keyword: str) -> ProcessingReason:
    """Explain why a negative keyword match lowers relevance."""

    return build_reason(
        NEGATIVE_KEYWORD,
        f"Text matched negative keyword {keyword!r}, so it may be outside the research topic.",
        ReasonSeverity.LOW_QUALITY.value,
    )


def text_hash(text: str) -> str:
    """Return a stable SHA-256 hash for duplicate detection."""

    return hashlib.sha256(text.strip().casefold().encode("utf-8")).hexdigest()


def duplicate_text_reason() -> ProcessingReason:
    """Explain duplicate text rejection or downranking."""

    return build_reason(
        DUPLICATE_TEXT,
        "Text duplicates another content item already processed for this project.",
        ReasonSeverity.LOW_QUALITY.value,
    )


def obvious_spam_reason() -> ProcessingReason:
    """Explain obvious spam rejection or downranking."""

    return build_reason(
        OBVIOUS_SPAM,
        "Text contains obvious spam-like promotional or giveaway language.",
        ReasonSeverity.LOW_QUALITY.value,
    )


def is_obvious_spam(text: str) -> bool:
    """Detect a small deterministic set of spam markers."""

    haystack = text.casefold()
    markers = ("free money", "giveaway", "click here", "promo code", "limited offer")
    return any(marker in haystack for marker in markers)

