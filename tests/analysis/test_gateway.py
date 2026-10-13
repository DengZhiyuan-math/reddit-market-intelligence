from app.analysis.gateway import (
    DeterministicSignalProvider,
    validate_signal_provider_result,
)
from app.analysis.models import SignalExtractionProviderResult, SignalExtractionRequest
from app.analysis.prompts import build_signal_extraction_prompt
from app.llm.models import LlmValidationStatus


def make_request(text: str = "Can anyone recommend a math tutor in Zurich?"):
    return SignalExtractionRequest(
        project_id=1,
        content_item_id=10,
        topic="Swiss tutoring market",
        business_context="AI + human tutor platform",
        text=text,
        source_type="reddit_post",
        source_id="post-1",
        language="en",
        relevance_score=0.82,
        quality_score=0.9,
    )


def test_prompt_payload_contains_required_contract() -> None:
    prompt = build_signal_extraction_prompt(make_request())

    assert "Return JSON only" in prompt["system"]
    assert "user_persona" in prompt["required_signal_fields"]
    assert "user_problem" in prompt["required_signal_fields"]
    assert "recommended_business_response" in prompt["required_signal_fields"]
    assert "confidence" in prompt["required_signal_fields"]


def test_deterministic_provider_returns_codex_local_by_default() -> None:
    provider = DeterministicSignalProvider()

    result = provider.extract(make_request())

    assert result.provider == "deterministic"
    assert result.model == "signal-rules-v1"


def test_valid_provider_output_returns_validated_status() -> None:
    request = make_request()
    result = DeterministicSignalProvider().extract(request)

    validation = validate_signal_provider_result(result, source_text=request.text)

    assert validation.validation_status == LlmValidationStatus.VALIDATED
    assert validation.output is not None
    assert validation.output.signals[0].user_persona == "PARENT"


def test_invalid_provider_output_returns_failed_status() -> None:
    result = SignalExtractionProviderResult(
        output={"status": "extracted", "confidence": 0.9},
    )

    validation = validate_signal_provider_result(result, source_text="source")

    assert validation.validation_status == LlmValidationStatus.FAILED
    assert validation.error


def test_quote_absent_from_source_text_returns_failed_status() -> None:
    result = SignalExtractionProviderResult(
        output={
            "status": "extracted",
            "signals": [
                {
                    "user_persona": "PARENT",
                    "user_problem": "Needs tutoring.",
                    "explicit_need": "Find tutor.",
                    "implicit_need": "Reduce stress.",
                    "emotional_tone": "worried",
                    "purchase_intent": "medium",
                    "trust_concern": True,
                    "price_concern": False,
                    "urgency": "medium",
                    "useful_quote": "Invented quote",
                    "recommended_business_response": "Offer transparent help.",
                    "confidence": 0.8,
                }
            ],
            "abstention_reason": None,
            "confidence": 0.8,
        }
    )

    validation = validate_signal_provider_result(result, source_text="Actual source text")

    assert validation.validation_status == LlmValidationStatus.FAILED
    assert "useful_quote" in validation.error
