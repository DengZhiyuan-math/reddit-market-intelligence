from app.db.models import ResearchProjectRecord
from app.processing.models import ACCEPTED, AMBIGUOUS, REJECTED
from app.processing.relevance import (
    ambiguity_score,
    build_topic_text,
    cosine_similarity,
    route_similarity,
)


def test_cosine_similarity_identical_vectors_is_one() -> None:
    assert cosine_similarity([1, 0], [1, 0]) == 1.0


def test_route_similarity_accepts_high_scores() -> None:
    assert route_similarity(0.80, 0.72, 0.35) == ACCEPTED


def test_route_similarity_rejects_low_scores() -> None:
    assert route_similarity(0.20, 0.72, 0.35) == REJECTED


def test_route_similarity_marks_middle_band_ambiguous() -> None:
    assert route_similarity(0.50, 0.72, 0.35) == AMBIGUOUS


def test_ambiguity_score_is_highest_near_threshold_midpoint() -> None:
    assert ambiguity_score(0.535, 0.72, 0.35) > ambiguity_score(0.70, 0.72, 0.35)


def test_build_topic_text_includes_project_and_plan_keywords() -> None:
    project = ResearchProjectRecord(
        project_id=1,
        slug="project-1",
        topic="Swiss tutoring market in Zurich",
        region="Switzerland, Zurich",
        languages=["en", "de"],
        target_users=["parents"],
        business_context="AI + human tutor platform",
        access_mode="commercial-approved",
        run_config={},
        collection_eligibility={},
    )
    plan = {
        "core_topic": "Swiss private tutoring demand",
        "primary_keywords": ["math tutor Zurich"],
        "secondary_keywords": ["Matura preparation"],
        "locale_vocabulary": [{"term": "Nachhilfe"}],
    }

    topic_text = build_topic_text(project, plan)

    assert "Swiss tutoring market in Zurich" in topic_text
    assert "math tutor Zurich" in topic_text
    assert "Nachhilfe" in topic_text
