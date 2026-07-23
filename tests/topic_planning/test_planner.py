"""Tests for deterministic topic planning."""

from pathlib import Path

from app.topic_planning.models import (
    DEFAULT_CLASSIFICATION_LABELS,
    DEFAULT_PAIN_POINT_LABELS,
    DEFAULT_PERSONA_LABELS,
    TopicPlan,
)
from app.topic_planning.planner import (
    MAX_QUERY_STRATEGIES,
    DeterministicTopicPlanner,
    TopicPlanningContext,
)


def zurich_context() -> TopicPlanningContext:
    return TopicPlanningContext(
        topic="Swiss tutoring market in Zurich",
        region="Switzerland, Zurich",
        languages=["en", "de"],
        target_users=["parents", "students", "expat families"],
        business_context="AI + human tutor platform",
        time_range="last 12 months",
    )


def test_deterministic_planner_generates_zurich_tutoring_plan() -> None:
    plan = DeterministicTopicPlanner().generate(zurich_context())

    assert isinstance(plan, TopicPlan)
    assert "Swiss tutoring market in Zurich" in plan.core_topic
    assert "math tutor Zurich" in plan.primary_keywords
    assert "Nachhilfe Zürich" in [*plan.primary_keywords, *plan.secondary_keywords]
    assert {"Switzerland", "askswitzerland", "Zurich", "ETHZurich"}.issubset(
        set(plan.candidate_subreddits)
    )
    assert set(DEFAULT_CLASSIFICATION_LABELS).issubset(plan.classification_labels)
    assert set(DEFAULT_PERSONA_LABELS).issubset(plan.persona_labels)
    assert set(DEFAULT_PAIN_POINT_LABELS).issubset(plan.pain_point_labels)


def test_planner_includes_zurich_english_and_german_locale_vocabulary() -> None:
    plan = DeterministicTopicPlanner().generate(zurich_context())
    terms = {term.term for term in plan.locale_vocabulary}

    assert {"Nachhilfe", "Zürich", "Gymnasium", "Matura", "Mathematik", "tutor"}.issubset(
        terms
    )


def test_planner_query_strategy_is_bounded() -> None:
    plan = DeterministicTopicPlanner().generate(zurich_context())

    assert 1 <= len(plan.query_strategy) <= MAX_QUERY_STRATEGIES
    assert all(query.rationale for query in plan.query_strategy)


def test_planner_has_generic_non_swiss_fallback() -> None:
    plan = DeterministicTopicPlanner().generate(
        TopicPlanningContext(topic="remote productivity tools", languages=["en"])
    )

    assert plan.core_topic == "remote productivity tools"
    assert "remote productivity tools recommendations" in [
        *plan.primary_keywords,
        *plan.secondary_keywords,
    ]
    assert "AskReddit" in plan.candidate_subreddits


def test_planner_module_has_no_network_or_provider_imports() -> None:
    source = Path("app/topic_planning/planner.py").read_text().casefold()

    for forbidden in ("openai", "praw", "asyncpraw", "requests.", "httpx"):
        assert forbidden not in source
