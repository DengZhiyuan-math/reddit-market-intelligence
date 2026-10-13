"""Models for strict LLM ambiguity review contracts."""

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class UrgencyLevel(StrEnum):
    """Allowed urgency labels for ambiguity review outputs."""

    NONE = "none"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class LlmValidationStatus(StrEnum):
    """Stable validation statuses persisted for LLM calls and judgements."""

    PENDING = "pending"
    VALIDATED = "validated"
    FAILED = "failed"
    SKIPPED = "skipped"


class AmbiguityReviewRequest(BaseModel):
    """Structured input sent to the ambiguity review provider."""

    project_id: int
    content_item_id: int
    topic: str
    business_context: str | None = None
    text: str = Field(min_length=1)
    source_type: str
    source_id: str
    subreddit: str | None = None
    language: str | None = None
    relevance_score: float | None = Field(default=None, ge=-1.0, le=1.0)
    quality_score: float | None = Field(default=None, ge=0.0, le=1.0)
    ambiguity_score: float | None = Field(default=None, ge=0.0, le=1.0)
    classification_labels: list[str] = Field(default_factory=list)
    persona_labels: list[str] = Field(default_factory=list)
    pain_point_labels: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class AmbiguityReviewOutput(BaseModel):
    """Validated JSON output for one ambiguous Reddit content item."""

    model_config = ConfigDict(extra="forbid")

    is_relevant: bool
    relevance_score: float = Field(ge=0.0, le=1.0)
    quality_score: float = Field(ge=0.0, le=1.0)
    intent_label: str = Field(min_length=1)
    persona_label: str = Field(min_length=1)
    pain_points: list[str] = Field(default_factory=list)
    buying_signal: bool
    urgency_level: UrgencyLevel
    reason: str = Field(min_length=1)
    confidence: float = Field(ge=0.0, le=1.0)


class LlmReviewProviderResult(BaseModel):
    """Raw provider response plus audit metadata."""

    output: dict[str, Any] | str
    provider: str = "codex-local"
    model: str = "gpt-5.2-codex"
    raw_response_json: dict[str, Any] | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    cost_estimate: float | None = None


class ValidationResult(BaseModel):
    """Result of validating a provider response."""

    validation_status: LlmValidationStatus
    provider_result: LlmReviewProviderResult
    output: AmbiguityReviewOutput | None = None
    error: str | None = None
    output_json: dict[str, Any] | None = None


class LlmReviewRunSummary(BaseModel):
    """User-facing and persisted summary for one LLM review run."""

    reviewed: int = 0
    relevant: int = 0
    irrelevant: int = 0
    failed: int = 0
    skipped: int = 0
    remaining: int = 0
    errors: int = 0

    def merge(self, other: "LlmReviewRunSummary") -> "LlmReviewRunSummary":
        """Add another summary into this one in-place and return self."""

        for field_name in type(self).model_fields:
            setattr(self, field_name, getattr(self, field_name) + getattr(other, field_name))
        return self
