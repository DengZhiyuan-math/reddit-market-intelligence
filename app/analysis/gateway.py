"""Provider and validation gateway for market signal extraction outputs."""

import json
from typing import Protocol

from pydantic import ValidationError

from app.analysis.models import (
    SignalExtractionOutput,
    SignalExtractionProviderResult,
    SignalExtractionRequest,
    SignalExtractionStatus,
    SignalValidationResult,
)
from app.llm.models import LlmValidationStatus


class SignalExtractionProvider(Protocol):
    """Provider contract for Codex-shaped or fake signal extraction calls."""

    provider: str
    model: str

    def extract(self, request: SignalExtractionRequest) -> SignalExtractionProviderResult:
        """Return raw signal extraction output for validation."""


class DeterministicSignalProvider:
    """Offline provider used for deterministic tests and local MVP runs."""

    def __init__(
        self,
        *,
        provider: str = "codex-local",
        model: str = "gpt-5.2-codex",
        fixture_output: dict | str | None = None,
    ) -> None:
        self.provider = provider
        self.model = model
        self.fixture_output = fixture_output

    def extract(self, request: SignalExtractionRequest) -> SignalExtractionProviderResult:
        """Return a deterministic, schema-shaped extraction response."""

        output = self.fixture_output if self.fixture_output is not None else self._default_output(request)
        return SignalExtractionProviderResult(
            output=output,
            provider=self.provider,
            model=self.model,
            raw_response_json={"output": output},
        )

    def _default_output(self, request: SignalExtractionRequest) -> dict:
        quote = _short_quote(request.text)
        confidence = max(request.confidence_threshold, 0.75)
        return {
            "status": SignalExtractionStatus.EXTRACTED.value,
            "signals": [
                {
                    "user_persona": "PARENT",
                    "user_problem": "Needs trusted academic support.",
                    "explicit_need": "Find reliable tutoring help.",
                    "implicit_need": "Reduce uncertainty and school stress.",
                    "emotional_tone": "concerned",
                    "purchase_intent": "medium",
                    "trust_concern": "trusted" in request.text.lower()
                    or "recommend" in request.text.lower(),
                    "price_concern": "price" in request.text.lower()
                    or "expensive" in request.text.lower(),
                    "urgency": "medium",
                    "useful_quote": quote,
                    "recommended_business_response": (
                        "Respond with transparent, curriculum-aware tutoring support."
                    ),
                    "confidence": confidence,
                }
            ],
            "abstention_reason": None,
            "confidence": confidence,
        }


def validate_signal_provider_result(
    provider_result: SignalExtractionProviderResult,
    *,
    source_text: str,
) -> SignalValidationResult:
    """Validate raw provider output into a strict signal extraction object."""

    try:
        output_payload = _coerce_output_payload(provider_result.output)
        output = SignalExtractionOutput.model_validate(output_payload)
        _validate_quotes(output, source_text)
    except (TypeError, ValueError, ValidationError) as exc:
        return SignalValidationResult(
            validation_status=LlmValidationStatus.FAILED,
            provider_result=provider_result,
            error=str(exc),
            output_json=_safe_output_json(provider_result.output),
        )

    return SignalValidationResult(
        validation_status=LlmValidationStatus.VALIDATED,
        provider_result=provider_result,
        output=output,
        output_json=output.model_dump(mode="json"),
    )


def _coerce_output_payload(output: dict | str) -> dict:
    if isinstance(output, dict):
        return output
    if isinstance(output, str):
        parsed = json.loads(output)
        if not isinstance(parsed, dict):
            raise TypeError("Provider output JSON must decode to an object.")
        return parsed
    raise TypeError("Provider output must be a dict or JSON object string.")


def _safe_output_json(output: dict | str) -> dict | None:
    try:
        return _coerce_output_payload(output)
    except (TypeError, ValueError, json.JSONDecodeError):
        return None


def _validate_quotes(output: SignalExtractionOutput, source_text: str) -> None:
    for signal in output.signals:
        quote = (signal.useful_quote or "").strip()
        if quote and quote not in source_text:
            raise ValueError("useful_quote must be an exact excerpt from source_text.")


def _short_quote(text: str, *, max_length: int = 120) -> str:
    compact = " ".join(text.split())
    if len(compact) <= max_length:
        return compact
    return compact[:max_length].rstrip()
