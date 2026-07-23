from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.config import Settings
from app.db.base import Base
from app.db.models import (
    ContentItemRecord,
    LlmCallRecord,
    LlmJudgementRecord,
    PipelineRunRecord,
    RelevanceDecisionRecord,
    ResearchPlanRecord,
    ResearchProjectRecord,
)
import app.db.models  # noqa: F401
from app.llm.gateway import DeterministicReviewProvider
from app.llm.models import AmbiguityReviewRequest
from app.llm.service import LlmReviewServiceError, run_llm_review
from app.processing.models import AMBIGUOUS


def make_session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def seed_project(session: Session) -> ResearchProjectRecord:
    project = ResearchProjectRecord(
        project_id=1,
        slug="project-1",
        topic="Swiss tutoring market in Zurich",
        region="Switzerland, Zurich",
        languages=["en", "de"],
        target_users=["parents"],
        business_context="AI + human tutor platform",
        time_range="last 12 months",
        access_mode="commercial-approved",
        run_config={"limit": 100},
        collection_eligibility={"allowed": True},
    )
    session.add(project)
    session.flush()
    session.add(
        ResearchPlanRecord(
            project_id=project.id,
            plan_json={
                "core_topic": "Swiss tutoring market",
                "classification_labels": ["LOOKING_FOR_TUTOR", "UNRELATED"],
                "persona_labels": ["PARENT", "UNKNOWN"],
                "pain_point_labels": ["MATH_DIFFICULTY"],
            },
            selected=True,
        )
    )
    session.flush()
    return project


def add_ambiguous_item(
    session: Session,
    project: ResearchProjectRecord,
    source_id: str = "ambiguous-1",
) -> ContentItemRecord:
    item = ContentItemRecord(
        project_id=project.id,
        source_type="reddit_post",
        source_id=source_id,
        source_table="reddit_posts_raw",
        text="Can anyone recommend a math tutor in Zurich?",
        cleaned_text="Can anyone recommend a math tutor in Zurich?",
        language="en",
        relevance_score=0.52,
        quality_score=0.8,
        ambiguity_score=0.7,
        llm_review_required=True,
        final_status=AMBIGUOUS,
        reason_codes=[],
    )
    session.add(item)
    session.flush()
    return item


class RaisingProvider:
    provider = "codex-local"
    model = "gpt-5.2-codex"

    def review(self, request: AmbiguityReviewRequest):
        raise RuntimeError("provider crashed")


def test_dry_run_returns_summary_without_persistence() -> None:
    session = make_session()
    project = seed_project(session)
    add_ambiguous_item(session, project)

    summary = run_llm_review(session, 1, dry_run=True)

    assert summary.skipped == 1
    assert summary.remaining == 1
    assert len(session.scalars(select(LlmCallRecord)).all()) == 0
    assert len(session.scalars(select(PipelineRunRecord)).all()) == 0


def test_valid_relevant_review_persists_call_judgement_and_decision() -> None:
    session = make_session()
    project = seed_project(session)
    item = add_ambiguous_item(session, project)

    summary = run_llm_review(session, 1)

    judgement = session.scalar(select(LlmJudgementRecord))
    assert summary.reviewed == 1
    assert summary.relevant == 1
    assert summary.irrelevant == 0
    assert summary.remaining == 0
    assert item.llm_review_required is False
    assert item.final_status == AMBIGUOUS
    assert judgement is not None
    assert judgement.output_json["is_relevant"] is True
    assert "confidence" in judgement.output_json
    assert len(session.scalars(select(LlmCallRecord)).all()) == 1
    assert len(session.scalars(select(RelevanceDecisionRecord)).all()) == 1


def test_valid_irrelevant_review_increments_irrelevant() -> None:
    session = make_session()
    project = seed_project(session)
    add_ambiguous_item(session, project)
    provider = DeterministicReviewProvider(
        fixture_output={
            "is_relevant": False,
            "relevance_score": 0.12,
            "quality_score": 0.8,
            "intent_label": "UNRELATED",
            "persona_label": "UNKNOWN",
            "pain_points": [],
            "buying_signal": False,
            "urgency_level": "none",
            "reason": "Unrelated to tutoring demand.",
            "confidence": 0.9,
        }
    )

    summary = run_llm_review(session, 1, provider=provider)

    assert summary.reviewed == 1
    assert summary.relevant == 0
    assert summary.irrelevant == 1


def test_invalid_provider_output_persists_failed_call_without_judgement() -> None:
    session = make_session()
    project = seed_project(session)
    item = add_ambiguous_item(session, project)
    provider = DeterministicReviewProvider(fixture_output={"is_relevant": True})

    summary = run_llm_review(session, 1, provider=provider)

    call = session.scalar(select(LlmCallRecord))
    assert summary.failed == 1
    assert summary.reviewed == 0
    assert summary.remaining == 1
    assert call is not None
    assert call.validation_status == "failed"
    assert len(session.scalars(select(LlmJudgementRecord)).all()) == 0
    assert item.llm_review_required is True


def test_service_failure_marks_pipeline_run_failed() -> None:
    session = make_session()
    project = seed_project(session)
    add_ambiguous_item(session, project)

    try:
        run_llm_review(session, 1, provider=RaisingProvider())
    except LlmReviewServiceError as exc:
        assert "provider crashed" in str(exc)
    else:
        raise AssertionError("Expected LlmReviewServiceError")

    run = session.scalar(select(PipelineRunRecord))
    assert run is not None
    assert run.stage == "llm_review"
    assert run.status == "failed"
    assert run.summary["errors"] == 1


def test_rerun_does_not_duplicate_validated_judgement() -> None:
    session = make_session()
    project = seed_project(session)
    add_ambiguous_item(session, project)

    first = run_llm_review(session, 1)
    second = run_llm_review(session, 1)

    assert first.reviewed == 1
    assert second.reviewed == 0
    assert second.remaining == 0
    assert len(session.scalars(select(LlmJudgementRecord)).all()) == 1


def test_service_uses_settings_default_limit() -> None:
    session = make_session()
    project = seed_project(session)
    add_ambiguous_item(session, project, "one")
    add_ambiguous_item(session, project, "two")
    settings = Settings(_env_file=None, llm_review_default_limit=1)

    summary = run_llm_review(session, 1, settings=settings)

    assert summary.reviewed == 1
    assert summary.remaining == 1
