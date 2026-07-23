"""Tests for structured topic planning models and prompt helpers."""

import pytest
from pydantic import ValidationError

from app.topic_planning.models import (
    DEFAULT_CLASSIFICATION_LABELS,
    DEFAULT_PAIN_POINT_LABELS,
    DEFAULT_PERSONA_LABELS,
    TOPIC_PLAN_SCHEMA_VERSION,
    LocaleVocabularyTerm,
    PlannedSearchQuery,
    TopicPlan,
)
from app.topic_planning.prompts import build_topic_planner_prompt, topic_plan_json_schema


def valid_topic_plan_payload() -> dict:
    return {
        "schema_version": TOPIC_PLAN_SCHEMA_VERSION,
        "core_topic": "Swiss tutoring market in Zurich",
        "market_hypotheses": ["Parents need reliable math tutors"],
        "primary_keywords": ["math tutor Zurich", "Math Tutor Zurich"],
        "secondary_keywords": ["Gymnasium math help"],
        "negative_keywords": ["game tutor"],
        "candidate_subreddits": ["Switzerland", "askswitzerland"],
        "classification_labels": list(DEFAULT_CLASSIFICATION_LABELS),
        "persona_labels": list(DEFAULT_PERSONA_LABELS),
        "pain_point_labels": list(DEFAULT_PAIN_POINT_LABELS),
        "locale_vocabulary": [
            {
                "term": "Nachhilfe",
                "language": "de",
                "category": "tutoring",
                "rationale": "Common German term for tutoring.",
            }
        ],
        "query_strategy": [
            {
                "query": "math tutor Zurich",
                "subreddit": "askswitzerland",
                "sort": "relevance",
                "time_filter": "year",
                "rationale": "Direct Zurich tutoring search.",
            }
        ],
    }


def test_topic_plan_accepts_required_fields() -> None:
    plan = TopicPlan.model_validate(valid_topic_plan_payload())

    assert plan.core_topic == "Swiss tutoring market in Zurich"
    assert plan.primary_keywords == ["math tutor Zurich"]
    assert isinstance(plan.locale_vocabulary[0], LocaleVocabularyTerm)
    assert isinstance(plan.query_strategy[0], PlannedSearchQuery)


def test_topic_plan_rejects_missing_required_fields() -> None:
    payload = valid_topic_plan_payload()
    payload.pop("core_topic")

    with pytest.raises(ValidationError):
        TopicPlan.model_validate(payload)


def test_topic_plan_rejects_missing_default_labels() -> None:
    payload = valid_topic_plan_payload()
    payload["classification_labels"] = ["LOOKING_FOR_TUTOR"]

    with pytest.raises(ValidationError, match="missing required default labels"):
        TopicPlan.model_validate(payload)


def test_topic_plan_rejects_extra_fields() -> None:
    payload = valid_topic_plan_payload()
    payload["freeform_notes"] = "not allowed"

    with pytest.raises(ValidationError):
        TopicPlan.model_validate(payload)


def test_topic_plan_schema_exports_required_fields() -> None:
    schema = topic_plan_json_schema()

    required = set(schema["required"])
    assert schema["additionalProperties"] is False
    assert {
        "core_topic",
        "market_hypotheses",
        "primary_keywords",
        "secondary_keywords",
        "negative_keywords",
        "candidate_subreddits",
        "classification_labels",
        "persona_labels",
        "pain_point_labels",
        "locale_vocabulary",
        "query_strategy",
    }.issubset(required)


def test_build_topic_planner_prompt_is_json_only_contract() -> None:
    prompt = build_topic_planner_prompt(
        {
            "topic": "Swiss tutoring market",
            "region": "Zurich",
            "languages": ["en", "de"],
        }
    )

    assert "Return JSON only" in prompt
    assert "core_topic" in prompt
    assert "locale_vocabulary" in prompt
    assert "Swiss tutoring market" in prompt
