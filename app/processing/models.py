"""Shared models and constants for content processing."""

from enum import StrEnum

from pydantic import BaseModel, Field


class FinalStatus(StrEnum):
    """Stable content routing states used by later pipeline stages."""

    ACCEPTED = "accepted"
    REJECTED = "rejected"
    AMBIGUOUS = "ambiguous"
    PENDING = "pending"


class ReasonSeverity(StrEnum):
    """How strongly a rule reason should affect downstream routing."""

    REJECT = "reject"
    LOW_QUALITY = "low_quality"
    INFO = "info"


class ReasonCode(StrEnum):
    """Machine-readable reason codes persisted with content items."""

    DELETED_CONTENT = "DELETED_CONTENT"
    REMOVED_CONTENT = "REMOVED_CONTENT"
    INACCESSIBLE_CONTENT = "INACCESSIBLE_CONTENT"
    EMPTY_TEXT = "EMPTY_TEXT"
    VERY_SHORT_TEXT = "VERY_SHORT_TEXT"
    DUPLICATE_TEXT = "DUPLICATE_TEXT"
    OBVIOUS_SPAM = "OBVIOUS_SPAM"
    OFF_LANGUAGE = "OFF_LANGUAGE"
    NEGATIVE_KEYWORD = "NEGATIVE_KEYWORD"


class DecisionType(StrEnum):
    """Decision producers stored in relevance_decisions."""

    RULE = "rule"
    LANGUAGE = "language"
    EMBEDDING = "embedding"
    LLM = "llm"


DELETED_CONTENT = ReasonCode.DELETED_CONTENT.value
REMOVED_CONTENT = ReasonCode.REMOVED_CONTENT.value
INACCESSIBLE_CONTENT = ReasonCode.INACCESSIBLE_CONTENT.value
EMPTY_TEXT = ReasonCode.EMPTY_TEXT.value
VERY_SHORT_TEXT = ReasonCode.VERY_SHORT_TEXT.value
DUPLICATE_TEXT = ReasonCode.DUPLICATE_TEXT.value
OBVIOUS_SPAM = ReasonCode.OBVIOUS_SPAM.value
OFF_LANGUAGE = ReasonCode.OFF_LANGUAGE.value
NEGATIVE_KEYWORD = ReasonCode.NEGATIVE_KEYWORD.value

ACCEPTED = FinalStatus.ACCEPTED.value
REJECTED = FinalStatus.REJECTED.value
AMBIGUOUS = FinalStatus.AMBIGUOUS.value
PENDING = FinalStatus.PENDING.value

RULE_DECISION = DecisionType.RULE.value
LANGUAGE_DECISION = DecisionType.LANGUAGE.value
EMBEDDING_DECISION = DecisionType.EMBEDDING.value
LLM_DECISION = DecisionType.LLM.value


class ProcessingReason(BaseModel):
    """Auditable rule output: compact code plus human-readable explanation."""

    code: str = Field(min_length=1)
    severity: str = Field(min_length=1)
    explanation: str = Field(min_length=1)


class CleanedTextResult(BaseModel):
    """Result of normalizing one raw Reddit text string."""

    original_text: str
    cleaned_text: str
    reasons: list[ProcessingReason] = Field(default_factory=list)
    evidence_eligible: bool = True
    quality_score: float = Field(default=1.0, ge=0.0, le=1.0)


class RelevanceThresholds(BaseModel):
    """Configurable thresholds for low-false-negative routing."""

    accept_threshold: float = Field(default=0.72, ge=0.0, le=1.0)
    reject_threshold: float = Field(default=0.35, ge=0.0, le=1.0)


class FilteringRunSummary(BaseModel):
    """User-facing and persisted summary for one filtering run."""

    raw_posts_processed: int = 0
    raw_comments_processed: int = 0
    content_items_created: int = 0
    content_items_updated: int = 0
    accepted: int = 0
    rejected: int = 0
    ambiguous: int = 0
    embedded: int = 0
    llm_review_required: int = 0
    duplicate_text: int = 0
    errors: int = 0

    def merge(self, other: "FilteringRunSummary") -> "FilteringRunSummary":
        """Add another summary into this one in-place and return self."""

        for field_name in type(self).model_fields:
            setattr(self, field_name, getattr(self, field_name) + getattr(other, field_name))
        return self
