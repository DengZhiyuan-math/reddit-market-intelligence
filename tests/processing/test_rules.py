from app.processing.models import (
    DELETED_CONTENT,
    DUPLICATE_TEXT,
    NEGATIVE_KEYWORD,
    ProcessingReason,
    ReasonSeverity,
)
from app.processing.rules import (
    build_reason,
    contains_negative_keyword,
    duplicate_text_reason,
    negative_keyword_reason,
    normalize_negative_keywords,
    text_hash,
)


def test_processing_reason_serializes_code_and_explanation() -> None:
    reason = ProcessingReason(
        code=DELETED_CONTENT,
        severity=ReasonSeverity.REJECT.value,
        explanation="Deleted content is excluded.",
    )

    assert reason.model_dump() == {
        "code": DELETED_CONTENT,
        "severity": "reject",
        "explanation": "Deleted content is excluded.",
    }


def test_build_reason_includes_code_and_explanation() -> None:
    reason = build_reason(DUPLICATE_TEXT, "Duplicate content item.")

    assert reason.code == DUPLICATE_TEXT
    assert reason.explanation == "Duplicate content item."


def test_negative_keyword_matching_is_case_insensitive() -> None:
    assert contains_negative_keyword("Need a game tutor", ["game tutor"])


def test_normalize_negative_keywords_deduplicates_values() -> None:
    assert normalize_negative_keywords(["Game Tutor", " game tutor ", "Music Tutor"]) == [
        "game tutor",
        "music tutor",
    ]


def test_text_hash_is_stable_for_duplicate_detection() -> None:
    assert text_hash("same text") == text_hash("same text")
    assert text_hash("same text") == text_hash(" SAME TEXT ")


def test_duplicate_reason_is_auditable() -> None:
    reason = duplicate_text_reason()

    assert reason.code == DUPLICATE_TEXT
    assert "duplicates" in reason.explanation


def test_negative_keyword_reason_mentions_keyword() -> None:
    reason = negative_keyword_reason("game tutor")

    assert reason.code == NEGATIVE_KEYWORD
    assert "game tutor" in reason.explanation

