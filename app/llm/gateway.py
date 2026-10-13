"""Provider and validation gateway for ambiguity review outputs."""

from collections.abc import Sequence
import json
from typing import Protocol

from pydantic import ValidationError

from app.llm.models import (
    AmbiguityReviewOutput,
    AmbiguityReviewRequest,
    LlmReviewProviderResult,
    LlmValidationStatus,
    ValidationResult,
)


class LlmReviewProvider(Protocol):
    """Provider contract for Codex-shaped or fake ambiguity review calls."""

    provider: str
    model: str

    def review(self, request: AmbiguityReviewRequest) -> LlmReviewProviderResult:
        """Return raw ambiguity review output for validation."""


class DeterministicReviewProvider:
    """Offline provider used for deterministic tests and local MVP runs."""

    def __init__(
        self,
        *,
        provider: str = "codex-local",
        model: str = "gpt-5.2-codex",
        fixture_output: dict | str | None = None,
    ) -> None:
        self.provider = "deterministic"
        self.model = "review-rules-v1"
        self.fixture_output = fixture_output

    def review(self, request: AmbiguityReviewRequest) -> LlmReviewProviderResult:
        """Return a deterministic, schema-shaped review response."""

        output = self.fixture_output if self.fixture_output is not None else self._default_output(request)
        return LlmReviewProviderResult(
            output=output,
            provider=self.provider,
            model=self.model,
            raw_response_json={"output": output},
        )

    def _default_output(self, request: AmbiguityReviewRequest) -> dict:
        text = request.text.lower()
        is_relevant = any(
            marker in text
            for marker in ("tutor", "math", "school", "gymnasium", "matura", "homework")
        )
        return {
            "is_relevant": is_relevant,
            "relevance_score": 0.82 if is_relevant else 0.24,
            "quality_score": request.quality_score if request.quality_score is not None else 0.8,
            "intent_label": _first_known(request.classification_labels, "UNKNOWN"),
            "persona_label": _first_known(request.persona_labels, "UNKNOWN"),
            "pain_points": _known_slice(request.pain_point_labels, default=["UNKNOWN"]),
            "buying_signal": is_relevant,
            "urgency_level": "medium" if is_relevant else "none",
            "reason": "Deterministic offline review based on topic-adjacent keywords.",
            "confidence": 0.75,
        }


def validate_provider_result(provider_result: LlmReviewProviderResult) -> ValidationResult:
    """Validate raw provider output into a strict ambiguity review object."""

    try:
        output_payload = _coerce_output_payload(provider_result.output)
        output = AmbiguityReviewOutput.model_validate(output_payload)
    except (TypeError, ValueError, ValidationError) as exc:
        return ValidationResult(
            validation_status=LlmValidationStatus.FAILED,
            provider_result=provider_result,
            error=str(exc),
            output_json=_safe_output_json(provider_result.output),
        )

    return ValidationResult(
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


def _first_known(labels: Sequence[str], fallback: str) -> str:
    return next((label for label in labels if label and label != "UNRELATED"), fallback)


def _known_slice(labels: Sequence[str], *, default: list[str]) -> list[str]:
    selected = [label for label in labels if label and label != "UNRELATED"][:3]
    return selected or default
