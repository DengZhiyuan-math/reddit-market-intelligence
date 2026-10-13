from app.llm.gateway import DeterministicReviewProvider, validate_provider_result
from app.llm.models import AmbiguityReviewRequest, LlmReviewProviderResult, LlmValidationStatus
from app.llm.prompts import build_ambiguity_review_prompt


def make_request(text: str = "Can anyone recommend a math tutor in Zurich?"):
    return AmbiguityReviewRequest(
        project_id=1,
        content_item_id=10,
        topic="Swiss tutoring market",
        business_context="AI + human tutor platform",
        text=text,
        source_type="reddit_post",
        source_id="post1",
        subreddit="askswitzerland",
        language="en",
        relevance_score=0.51,
        quality_score=0.8,
        ambiguity_score=0.7,
        classification_labels=["LOOKING_FOR_TUTOR", "UNRELATED"],
        persona_labels=["PARENT", "UNKNOWN"],
        pain_point_labels=["MATH_DIFFICULTY"],
    )


def test_prompt_payload_contains_json_contract() -> None:
    payload = build_ambiguity_review_prompt(make_request())

    assert "Return JSON only" in payload["system"]
    assert "is_relevant" in payload["required_output_fields"]
    assert "relevance_score" in payload["required_output_fields"]
    assert "confidence" in payload["required_output_fields"]
    assert payload["input"]["subreddit"] == "askswitzerland"


def test_deterministic_review_provider_returns_local_metadata() -> None:
    provider = DeterministicReviewProvider()
    result = provider.review(make_request())

    assert result.provider == "deterministic"
    assert result.model == "review-rules-v1"
    assert result.raw_response_json is not None


def test_valid_provider_output_validates_successfully() -> None:
    provider = DeterministicReviewProvider()
    validation = validate_provider_result(provider.review(make_request()))

    assert validation.validation_status == LlmValidationStatus.VALIDATED
    assert validation.output is not None
    assert validation.output.is_relevant is True


def test_invalid_provider_output_returns_failed_validation() -> None:
    result = LlmReviewProviderResult(
        output={"is_relevant": True, "relevance_score": 1.4},
        provider="codex-local",
        model="gpt-5.2-codex",
        raw_response_json={"output": {"is_relevant": True, "relevance_score": 1.4}},
    )

    validation = validate_provider_result(result)

    assert validation.validation_status == LlmValidationStatus.FAILED
    assert validation.output is None
    assert "validation error" in (validation.error or "").lower()


def test_json_string_provider_output_is_supported() -> None:
    result = LlmReviewProviderResult(
        output=(
            '{"is_relevant": false, "relevance_score": 0.1, "quality_score": 0.5, '
            '"intent_label": "UNRELATED", "persona_label": "UNKNOWN", "pain_points": [], '
            '"buying_signal": false, "urgency_level": "none", "reason": "Unrelated", '
            '"confidence": 0.8}'
        )
    )

    validation = validate_provider_result(result)

    assert validation.validation_status == LlmValidationStatus.VALIDATED
    assert validation.output is not None
    assert validation.output.is_relevant is False
