import pytest
from pydantic import ValidationError

from app.analysis.models import (
    SignalExtractionOutput,
    SignalExtractionRunSummary,
    SignalExtractionStatus,
)


def valid_output() -> dict:
    return {
        "status": "extracted",
        "signals": [
            {
                "user_persona": "PARENT",
                "user_problem": "Cannot find trusted math support.",
                "explicit_need": "Find a reliable math tutor.",
                "implicit_need": "Reduce exam anxiety.",
                "emotional_tone": "worried",
                "purchase_intent": "high",
                "trust_concern": True,
                "price_concern": False,
                "urgency": "high",
                "useful_quote": "Can anyone recommend a math tutor?",
                "recommended_business_response": "Offer transparent tutor matching.",
                "confidence": 0.91,
            }
        ],
        "abstention_reason": None,
        "confidence": 0.91,
    }


def test_valid_extracted_output_with_all_llm_04_fields_parses() -> None:
    output = SignalExtractionOutput.model_validate(valid_output())

    assert output.status == SignalExtractionStatus.EXTRACTED
    assert output.signals[0].recommended_business_response == "Offer transparent tutor matching."
    assert output.signals[0].confidence == 0.91


def test_missing_recommended_business_response_raises_validation_error() -> None:
    payload = valid_output()
    del payload["signals"][0]["recommended_business_response"]

    with pytest.raises(ValidationError):
        SignalExtractionOutput.model_validate(payload)


def test_confidence_above_one_raises_validation_error() -> None:
    payload = valid_output()
    payload["confidence"] = 1.2

    with pytest.raises(ValidationError):
        SignalExtractionOutput.model_validate(payload)


def test_status_accepts_extracted_abstained_and_uncertain() -> None:
    extracted = SignalExtractionOutput.model_validate(valid_output())
    abstained = SignalExtractionOutput.model_validate(
        {
            "status": "abstained",
            "signals": [],
            "abstention_reason": "No concrete market need.",
            "confidence": 0.82,
        }
    )
    uncertain = SignalExtractionOutput.model_validate(
        {
            "status": "uncertain",
            "signals": [],
            "abstention_reason": "Evidence is too ambiguous.",
            "confidence": 0.51,
        }
    )

    assert extracted.status == SignalExtractionStatus.EXTRACTED
    assert abstained.status == SignalExtractionStatus.ABSTAINED
    assert uncertain.status == SignalExtractionStatus.UNCERTAIN


def test_extracted_output_requires_at_least_one_signal() -> None:
    payload = valid_output()
    payload["signals"] = []

    with pytest.raises(ValidationError):
        SignalExtractionOutput.model_validate(payload)


def test_abstained_output_requires_reason() -> None:
    with pytest.raises(ValidationError):
        SignalExtractionOutput.model_validate(
            {
                "status": "abstained",
                "signals": [],
                "abstention_reason": None,
                "confidence": 0.8,
            }
        )


def test_run_summary_contains_required_counters() -> None:
    summary = SignalExtractionRunSummary(
        candidates=1,
        extracted_signals=2,
        abstained=3,
        failed=4,
        skipped_duplicates=5,
        remaining=6,
        errors=7,
    )

    assert summary.candidates == 1
    assert summary.extracted_signals == 2
    assert summary.abstained == 3
    assert summary.failed == 4
    assert summary.skipped_duplicates == 5
    assert summary.remaining == 6
    assert summary.errors == 7
