from app.processing.cleaner import clean_reddit_text, combine_post_text
from app.processing.models import (
    DELETED_CONTENT,
    REMOVED_CONTENT,
    VERY_SHORT_TEXT,
)


def reason_codes(result) -> set[str]:
    return {reason.code for reason in result.reasons}


def test_combine_post_text_uses_title_and_body() -> None:
    assert combine_post_text("Math tutor?", "Looking in Zurich") == "Math tutor?\n\nLooking in Zurich"


def test_cleaner_normalizes_whitespace() -> None:
    result = clean_reddit_text("Hello\n\n   world")

    assert result.cleaned_text == "Hello world"


def test_cleaner_strips_markdown_link_syntax() -> None:
    result = clean_reddit_text("Try [STOA](https://example.com) for math help in Zurich.")

    assert "STOA" in result.cleaned_text
    assert "https://example.com" not in result.cleaned_text


def test_deleted_content_is_evidence_ineligible() -> None:
    result = clean_reddit_text("[deleted]")

    assert result.cleaned_text == ""
    assert result.evidence_eligible is False
    assert DELETED_CONTENT in reason_codes(result)


def test_removed_content_is_evidence_ineligible() -> None:
    result = clean_reddit_text("[removed]")

    assert result.cleaned_text == ""
    assert result.evidence_eligible is False
    assert REMOVED_CONTENT in reason_codes(result)


def test_empty_text_is_evidence_ineligible() -> None:
    result = clean_reddit_text(None)

    assert result.cleaned_text == ""
    assert result.evidence_eligible is False


def test_very_short_text_keeps_cleaned_text_with_reason() -> None:
    result = clean_reddit_text("Too short")

    assert result.cleaned_text == "Too short"
    assert result.evidence_eligible is True
    assert VERY_SHORT_TEXT in reason_codes(result)
