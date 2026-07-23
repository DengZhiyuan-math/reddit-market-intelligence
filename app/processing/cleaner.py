"""Text cleaning helpers for raw Reddit content."""

import re

from app.processing.models import (
    DELETED_CONTENT,
    EMPTY_TEXT,
    REMOVED_CONTENT,
    VERY_SHORT_TEXT,
    CleanedTextResult,
    ReasonSeverity,
)
from app.processing.rules import build_reason

MIN_TEXT_LENGTH = 30

_MARKDOWN_LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
_QUOTE_PREFIX_RE = re.compile(r"(?m)^\s*>\s?")
_MARKDOWN_NOISE_RE = re.compile(r"[*_`~]+")
_WHITESPACE_RE = re.compile(r"\s+")


def combine_post_text(title: str | None, body: str | None) -> str:
    """Combine a Reddit post title and body into one analysis string."""

    return "\n\n".join(part.strip() for part in (title or "", body or "") if part and part.strip())


def clean_reddit_text(text: str | None) -> CleanedTextResult:
    """Normalize raw Reddit text while preserving evidence useful for analysis."""

    original = "" if text is None else str(text)
    stripped = original.strip()
    lowered = stripped.casefold()
    reasons = []

    if text is None or not stripped:
        reasons.append(
            build_reason(
                EMPTY_TEXT,
                "Raw Reddit text is empty or missing.",
                ReasonSeverity.REJECT.value,
            )
        )
        return CleanedTextResult(
            original_text=original,
            cleaned_text="",
            reasons=reasons,
            evidence_eligible=False,
            quality_score=0.0,
        )

    if lowered == "[deleted]":
        reasons.append(
            build_reason(
                DELETED_CONTENT,
                "Reddit marks this content as deleted; it is excluded from report evidence.",
                ReasonSeverity.REJECT.value,
            )
        )
        return CleanedTextResult(
            original_text=original,
            cleaned_text="",
            reasons=reasons,
            evidence_eligible=False,
            quality_score=0.0,
        )

    if lowered == "[removed]":
        reasons.append(
            build_reason(
                REMOVED_CONTENT,
                "Reddit marks this content as removed; it is excluded from report evidence.",
                ReasonSeverity.REJECT.value,
            )
        )
        return CleanedTextResult(
            original_text=original,
            cleaned_text="",
            reasons=reasons,
            evidence_eligible=False,
            quality_score=0.0,
        )

    cleaned = _normalize_markdown(stripped)
    if not cleaned:
        reasons.append(
            build_reason(
                EMPTY_TEXT,
                "Text becomes empty after markdown and whitespace normalization.",
                ReasonSeverity.REJECT.value,
            )
        )
        return CleanedTextResult(
            original_text=original,
            cleaned_text="",
            reasons=reasons,
            evidence_eligible=False,
            quality_score=0.0,
        )

    quality_score = 1.0
    if len(cleaned) < MIN_TEXT_LENGTH:
        reasons.append(
            build_reason(
                VERY_SHORT_TEXT,
                f"Cleaned text is shorter than {MIN_TEXT_LENGTH} characters.",
                ReasonSeverity.LOW_QUALITY.value,
            )
        )
        quality_score = 0.4

    return CleanedTextResult(
        original_text=original,
        cleaned_text=cleaned,
        reasons=reasons,
        evidence_eligible=True,
        quality_score=quality_score,
    )


def _normalize_markdown(text: str) -> str:
    text = _MARKDOWN_LINK_RE.sub(r"\1", text)
    text = _QUOTE_PREFIX_RE.sub("", text)
    text = _MARKDOWN_NOISE_RE.sub("", text)
    return _WHITESPACE_RE.sub(" ", text).strip()

