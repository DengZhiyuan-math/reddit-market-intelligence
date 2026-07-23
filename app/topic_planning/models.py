"""Pydantic contracts for structured Reddit topic planning."""

from typing import Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

TOPIC_PLAN_SCHEMA_VERSION = "topic_plan.v1"

DEFAULT_CLASSIFICATION_LABELS: tuple[str, ...] = (
    "LOOKING_FOR_TUTOR",
    "ASKING_PRICE",
    "PRICE_COMPLAINT",
    "QUALITY_COMPLAINT",
    "RECOMMENDATION_REQUEST",
    "EXAM_PREPARATION",
    "HOMEWORK_HELP",
    "LANGUAGE_SUPPORT",
    "SCHOOL_SYSTEM_CONFUSION",
    "AI_TOOL_DISCUSSION",
    "GENERAL_EDUCATION_DISCUSSION",
    "UNRELATED",
)

DEFAULT_PERSONA_LABELS: tuple[str, ...] = (
    "PARENT",
    "STUDENT",
    "EXPAT_PARENT",
    "UNIVERSITY_STUDENT",
    "TEACHER",
    "TUTOR",
    "SCHOOL_ADMIN",
    "UNKNOWN",
)

DEFAULT_PAIN_POINT_LABELS: tuple[str, ...] = (
    "TOO_EXPENSIVE",
    "CANNOT_FIND_TRUSTED_TUTOR",
    "URGENT_EXAM_HELP",
    "MATH_DIFFICULTY",
    "GERMAN_LANGUAGE_BARRIER",
    "SWISS_SCHOOL_SYSTEM_CONFUSION",
    "LOW_TEACHER_QUALITY",
    "LACK_OF_STRUCTURE",
    "NEED_LAST_MINUTE_HELP",
    "NEED_ONLINE_HELP",
    "NEED_LOCAL_TUTOR",
)


def dedupe_normalized(values: list[str]) -> list[str]:
    """Strip empty strings and remove duplicates while preserving first spelling."""

    seen: set[str] = set()
    normalized: list[str] = []
    for value in values:
        clean = value.strip()
        key = clean.casefold()
        if not clean or key in seen:
            continue
        seen.add(key)
        normalized.append(clean)
    return normalized


class TopicPlanningModel(BaseModel):
    """Base model configured for strict JSON contracts."""

    model_config = ConfigDict(extra="forbid")


class LocaleVocabularyTerm(TopicPlanningModel):
    """Locale-specific vocabulary to support multilingual Reddit search."""

    term: str = Field(min_length=1)
    language: str = Field(min_length=1)
    category: str = Field(min_length=1)
    rationale: str = Field(min_length=1)


class PlannedSearchQuery(TopicPlanningModel):
    """Executable subreddit/query strategy for later Reddit collection."""

    query: str = Field(min_length=1)
    subreddit: str = Field(min_length=1)
    sort: str = Field(default="relevance", min_length=1)
    time_filter: str = Field(default="year", min_length=1)
    rationale: str = Field(min_length=1)


class TopicPlan(TopicPlanningModel):
    """Strict structured Reddit research plan."""

    schema_version: str = Field(default=TOPIC_PLAN_SCHEMA_VERSION, min_length=1)
    core_topic: str = Field(min_length=1)
    market_hypotheses: list[str] = Field(min_length=1)
    primary_keywords: list[str] = Field(min_length=1)
    secondary_keywords: list[str] = Field(min_length=1)
    negative_keywords: list[str] = Field(min_length=1)
    candidate_subreddits: list[str] = Field(min_length=1)
    classification_labels: list[str] = Field(min_length=1)
    persona_labels: list[str] = Field(min_length=1)
    pain_point_labels: list[str] = Field(min_length=1)
    locale_vocabulary: list[LocaleVocabularyTerm] = Field(min_length=1)
    query_strategy: list[PlannedSearchQuery] = Field(min_length=1)

    @field_validator(
        "market_hypotheses",
        "primary_keywords",
        "secondary_keywords",
        "negative_keywords",
        "candidate_subreddits",
        "classification_labels",
        "persona_labels",
        "pain_point_labels",
        mode="before",
    )
    @classmethod
    def normalize_string_lists(cls, value: list[str]) -> list[str]:
        return dedupe_normalized(value)

    @model_validator(mode="after")
    def ensure_required_default_labels(self) -> Self:
        missing_classification = set(DEFAULT_CLASSIFICATION_LABELS).difference(
            self.classification_labels
        )
        missing_persona = set(DEFAULT_PERSONA_LABELS).difference(self.persona_labels)
        missing_pain_points = set(DEFAULT_PAIN_POINT_LABELS).difference(self.pain_point_labels)
        missing = sorted(missing_classification | missing_persona | missing_pain_points)
        if missing:
            raise ValueError(f"Topic plan missing required default labels: {', '.join(missing)}")
        return self
