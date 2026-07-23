"""Loader and validators for the synthetic Zurich tutoring eval sample."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError, field_validator


ALLOWED_SOURCE_TYPES = {"reddit_post", "reddit_comment"}
ALLOWED_URGENCY_LEVELS = {"none", "low", "medium", "high"}
ALLOWED_INTENT_LABELS = {
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
}
ALLOWED_PERSONA_LABELS = {
    "PARENT",
    "STUDENT",
    "EXPAT_PARENT",
    "UNIVERSITY_STUDENT",
    "TEACHER",
    "TUTOR",
    "SCHOOL_ADMIN",
    "UNKNOWN",
}
ALLOWED_PAIN_POINTS = {
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
    "AI_HOMEWORK_HELP",
}


class EvalSampleRow(BaseModel):
    """One synthetic labelled sample used for fixture demos and calibration tests."""

    sample_id: str = Field(pattern=r"^zt-\d{3}$")
    source_type: Literal["reddit_post", "reddit_comment"]
    subreddit: str = Field(min_length=1)
    title: str = Field(min_length=1)
    body: str = Field(min_length=1)
    language: str = Field(min_length=2, max_length=5)
    expected_relevance: bool
    expected_intent_label: str
    expected_persona_label: str
    expected_pain_points: list[str] = Field(default_factory=list)
    expected_urgency_level: str
    expected_buying_signal: bool
    notes: str = Field(min_length=1)

    @field_validator("expected_intent_label")
    @classmethod
    def validate_intent_label(cls, value: str) -> str:
        if value not in ALLOWED_INTENT_LABELS:
            raise ValueError(f"Unsupported intent label: {value}")
        return value

    @field_validator("expected_persona_label")
    @classmethod
    def validate_persona_label(cls, value: str) -> str:
        if value not in ALLOWED_PERSONA_LABELS:
            raise ValueError(f"Unsupported persona label: {value}")
        return value

    @field_validator("expected_pain_points")
    @classmethod
    def validate_pain_points(cls, values: list[str]) -> list[str]:
        unknown = sorted(set(values) - ALLOWED_PAIN_POINTS)
        if unknown:
            raise ValueError(f"Unsupported pain point label(s): {unknown}")
        return values

    @field_validator("expected_urgency_level")
    @classmethod
    def validate_urgency_level(cls, value: str) -> str:
        if value not in ALLOWED_URGENCY_LEVELS:
            raise ValueError(f"Unsupported urgency level: {value}")
        return value

    @property
    def text(self) -> str:
        """Combined text shaped like a Reddit title/body pair."""

        return f"{self.title}\n\n{self.body}"


def default_eval_sample_path() -> Path:
    """Return the repository default synthetic eval sample path."""

    return Path(__file__).resolve().parents[2] / "data" / "eval" / "zurich_tutoring_sample.jsonl"


def load_eval_samples(path: Path | str | None = None) -> list[EvalSampleRow]:
    """Load and validate eval samples in deterministic sample-id order."""

    sample_path = Path(path) if path is not None else default_eval_sample_path()
    rows: list[EvalSampleRow] = []
    for line_number, line in enumerate(sample_path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            payload: dict[str, Any] = json.loads(line)
            rows.append(EvalSampleRow.model_validate(payload))
        except (json.JSONDecodeError, ValidationError) as exc:
            raise ValueError(f"Invalid eval sample row at line {line_number}: {exc}") from exc
    return sorted(rows, key=lambda row: row.sample_id)


def count_by_relevance(samples: list[EvalSampleRow]) -> dict[str, int]:
    """Count samples by relevant/unrelated status."""

    counts = Counter("relevant" if sample.expected_relevance else "unrelated" for sample in samples)
    return dict(counts)


def count_by_persona(samples: list[EvalSampleRow]) -> dict[str, int]:
    """Count samples by expected persona label."""

    return dict(Counter(sample.expected_persona_label for sample in samples))


def count_by_pain_point(samples: list[EvalSampleRow]) -> dict[str, int]:
    """Count samples by expected pain point label."""

    counts: Counter[str] = Counter()
    for sample in samples:
        counts.update(sample.expected_pain_points)
    return dict(counts)
