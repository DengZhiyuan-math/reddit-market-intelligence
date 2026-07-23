"""Models for strict market signal extraction contracts."""

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, model_validator

from app.llm.models import LlmValidationStatus


class SignalExtractionStatus(StrEnum):
    """Allowed extraction-level statuses."""

    EXTRACTED = "extracted"
    ABSTAINED = "abstained"
    UNCERTAIN = "uncertain"


class PurchaseIntentLevel(StrEnum):
    """Stable purchase-intent labels for signal extraction."""

    NONE = "none"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class EvidenceCandidate(BaseModel):
    """One source item eligible for market signal extraction."""

    project_db_id: int
    project_id: int
    topic: str
    business_context: str | None = None
    content_item_id: int
    source_type: str
    source_id: str
    source_mode: str = "reddit_api"
    text: str = Field(min_length=1)
    language: str | None = None
    relevance_score: float | None = Field(default=None, ge=0.0, le=1.0)
    quality_score: float | None = Field(default=None, ge=0.0, le=1.0)
    llm_judgement_id: int | None = None
    ambiguity_judgement_json: dict[str, Any] | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class MarketSignalOutput(BaseModel):
    """One coherent extracted market insight."""

    user_persona: str = Field(min_length=1)
    user_problem: str = Field(min_length=1)
    explicit_need: str = Field(min_length=1)
    implicit_need: str = Field(min_length=1)
    emotional_tone: str = Field(min_length=1)
    purchase_intent: PurchaseIntentLevel
    trust_concern: bool
    price_concern: bool
    urgency: str = Field(min_length=1)
    useful_quote: str | None = None
    recommended_business_response: str = Field(min_length=1)
    confidence: float = Field(ge=0.0, le=1.0)


class SignalExtractionRequest(BaseModel):
    """Structured input sent to the signal extraction provider."""

    project_id: int
    content_item_id: int
    topic: str
    business_context: str | None = None
    text: str = Field(min_length=1)
    source_type: str
    source_id: str
    source_mode: str = "reddit_api"
    language: str | None = None
    relevance_score: float | None = Field(default=None, ge=0.0, le=1.0)
    quality_score: float | None = Field(default=None, ge=0.0, le=1.0)
    llm_judgement_id: int | None = None
    ambiguity_judgement_json: dict[str, Any] | None = None
    confidence_threshold: float = Field(default=0.70, ge=0.0, le=1.0)
    metadata: dict[str, Any] = Field(default_factory=dict)


class SignalExtractionOutput(BaseModel):
    """Validated JSON output for market signal extraction."""

    status: SignalExtractionStatus
    signals: list[MarketSignalOutput] = Field(default_factory=list)
    abstention_reason: str | None = None
    confidence: float = Field(ge=0.0, le=1.0)

    @model_validator(mode="after")
    def validate_status_shape(self) -> "SignalExtractionOutput":
        """Ensure extracted output has signals and abstained output explains itself."""

        if self.status == SignalExtractionStatus.EXTRACTED and not self.signals:
            raise ValueError("Extracted output must include at least one signal.")
        if self.status in {
            SignalExtractionStatus.ABSTAINED,
            SignalExtractionStatus.UNCERTAIN,
        } and not self.abstention_reason:
            raise ValueError("Abstained or uncertain output must include abstention_reason.")
        return self


class SignalExtractionProviderResult(BaseModel):
    """Raw provider response plus audit metadata."""

    output: dict[str, Any] | str
    provider: str = "codex-local"
    model: str = "gpt-5.2-codex"
    raw_response_json: dict[str, Any] | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    cost_estimate: float | None = None


class SignalValidationResult(BaseModel):
    """Result of validating one provider response."""

    validation_status: LlmValidationStatus
    provider_result: SignalExtractionProviderResult
    output: SignalExtractionOutput | None = None
    error: str | None = None
    output_json: dict[str, Any] | None = None


class SignalExtractionRunSummary(BaseModel):
    """User-facing and persisted summary for one signal extraction run."""

    candidates: int = 0
    extracted_signals: int = 0
    abstained: int = 0
    failed: int = 0
    skipped_duplicates: int = 0
    remaining: int = 0
    errors: int = 0

    def merge(self, other: "SignalExtractionRunSummary") -> "SignalExtractionRunSummary":
        """Add another summary into this one in-place and return self."""

        for field_name in type(self).model_fields:
            setattr(self, field_name, getattr(self, field_name) + getattr(other, field_name))
        return self
