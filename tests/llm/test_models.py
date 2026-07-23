import pytest
from pydantic import ValidationError

from app.config import Settings
from app.llm.models import AmbiguityReviewOutput, LlmReviewRunSummary, UrgencyLevel


def valid_output_payload() -> dict:
    return {
        "is_relevant": True,
        "relevance_score": 0.88,
        "quality_score": 0.79,
        "intent_label": "LOOKING_FOR_TUTOR",
        "persona_label": "PARENT",
        "pain_points": ["MATH_DIFFICULTY"],
        "buying_signal": True,
        "urgency_level": "medium",
        "reason": "The text asks for a math tutor.",
        "confidence": 0.91,
    }


def test_settings_include_local_llm_review_defaults() -> None:
    settings = Settings(_env_file=None)

    assert settings.llm_review_provider == "codex-local"
    assert settings.llm_review_model == "gpt-5.2-codex"
    assert settings.llm_review_max_retries == 1
    assert settings.llm_review_default_limit == 25


def test_valid_ambiguity_review_output_parses_all_required_fields() -> None:
    output = AmbiguityReviewOutput.model_validate(valid_output_payload())

    assert output.is_relevant is True
    assert output.relevance_score == 0.88
    assert output.urgency_level == UrgencyLevel.MEDIUM
    assert output.confidence == 0.91


def test_missing_confidence_is_rejected() -> None:
    payload = valid_output_payload()
    del payload["confidence"]

    with pytest.raises(ValidationError):
        AmbiguityReviewOutput.model_validate(payload)


def test_score_above_one_is_rejected() -> None:
    payload = valid_output_payload()
    payload["relevance_score"] = 1.2

    with pytest.raises(ValidationError):
        AmbiguityReviewOutput.model_validate(payload)


def test_urgency_levels_are_limited_to_contract_values() -> None:
    for urgency in ("none", "low", "medium", "high"):
        payload = valid_output_payload()
        payload["urgency_level"] = urgency
        assert AmbiguityReviewOutput.model_validate(payload).urgency_level == urgency

    payload = valid_output_payload()
    payload["urgency_level"] = "soon"
    with pytest.raises(ValidationError):
        AmbiguityReviewOutput.model_validate(payload)


def test_review_run_summary_tracks_remaining_queue() -> None:
    summary = LlmReviewRunSummary(reviewed=2, relevant=1, irrelevant=1, remaining=3)

    assert summary.remaining == 3
