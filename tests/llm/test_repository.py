from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.db.base import Base
from app.db.models import (
    ContentItemRecord,
    LlmCallRecord,
    LlmJudgementRecord,
    PipelineRunRecord,
    ResearchProjectRecord,
)
import app.db.models  # noqa: F401
from app.llm.gateway import validate_provider_result
from app.llm.models import LlmReviewProviderResult, LlmReviewRunSummary, LlmValidationStatus
from app.llm.repository import AMBIGUITY_REVIEW, LlmReviewRepository
from app.processing.models import ACCEPTED, AMBIGUOUS, LLM_DECISION, REJECTED


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
    return project


def add_item(
    session: Session,
    project: ResearchProjectRecord,
    status: str,
    source_id: str,
    *,
    review_required: bool = True,
    ambiguity_score: float | None = 0.5,
) -> ContentItemRecord:
    item = ContentItemRecord(
        project_id=project.id,
        source_type="reddit_post",
        source_id=source_id,
        text=f"Original text for {source_id}",
        cleaned_text=f"Cleaned text for {source_id}",
        language="en",
        relevance_score=0.5,
        quality_score=0.8,
        ambiguity_score=ambiguity_score,
        llm_review_required=review_required,
        final_status=status,
        reason_codes=[],
    )
    session.add(item)
    session.flush()
    return item


def valid_validation():
    return validate_provider_result(
        LlmReviewProviderResult(
            output={
                "is_relevant": True,
                "relevance_score": 0.86,
                "quality_score": 0.77,
                "intent_label": "LOOKING_FOR_TUTOR",
                "persona_label": "PARENT",
                "pain_points": ["MATH_DIFFICULTY"],
                "buying_signal": True,
                "urgency_level": "medium",
                "reason": "Asks for tutor help.",
                "confidence": 0.93,
            },
            provider="codex-local",
            model="gpt-5.2-codex",
            raw_response_json={"fixture": "valid"},
        )
    )


def failed_validation():
    return validate_provider_result(
        LlmReviewProviderResult(
            output={"is_relevant": True, "relevance_score": 1.4},
            provider="codex-local",
            model="gpt-5.2-codex",
            raw_response_json={"fixture": "invalid"},
        )
    )


def test_repository_loads_project_and_review_run_lifecycle() -> None:
    session = make_session()
    project = seed_project(session)
    repository = LlmReviewRepository(session)

    run = repository.start_review_run(project.id, {"limit": 10})
    repository.complete_review_run(run.id, "completed", LlmReviewRunSummary(reviewed=1))

    assert repository.get_project_by_project_id(1) == project
    assert run.stage == "llm_review"
    assert run.status == "completed"
    assert session.scalar(select(PipelineRunRecord)).summary["reviewed"] == 1


def test_pending_queue_contains_only_review_required_ambiguous_items() -> None:
    session = make_session()
    project = seed_project(session)
    pending = add_item(session, project, AMBIGUOUS, "pending", ambiguity_score=0.9)
    add_item(session, project, ACCEPTED, "accepted")
    add_item(session, project, REJECTED, "rejected")
    add_item(session, project, AMBIGUOUS, "not-required", review_required=False)
    repository = LlmReviewRepository(session)

    items = repository.list_pending_ambiguity_items(project.id)

    assert items == [pending]
    assert repository.count_remaining_ambiguity_items(project.id) == 1


def test_pending_queue_respects_limit_and_orders_by_ambiguity_score() -> None:
    session = make_session()
    project = seed_project(session)
    low = add_item(session, project, AMBIGUOUS, "low", ambiguity_score=0.2)
    high = add_item(session, project, AMBIGUOUS, "high", ambiguity_score=0.9)
    repository = LlmReviewRepository(session)

    assert repository.list_pending_ambiguity_items(project.id, limit=1) == [high]
    assert repository.list_pending_ambiguity_items(project.id) == [high, low]


def test_validated_judgement_excludes_item_from_queue() -> None:
    session = make_session()
    project = seed_project(session)
    item = add_item(session, project, AMBIGUOUS, "pending")
    repository = LlmReviewRepository(session)
    call = repository.record_llm_call(
        content_item=item,
        run_id=None,
        input_json={"prompt": "test"},
        validation=valid_validation(),
    )
    repository.record_validated_judgement(content_item=item, llm_call=call, validation=valid_validation())
    session.commit()

    assert repository.list_pending_ambiguity_items(project.id) == []
    assert repository.has_validated_ambiguity_judgement(item.id) is True


def test_valid_review_persists_call_and_judgement_and_clears_queue_flag() -> None:
    session = make_session()
    project = seed_project(session)
    item = add_item(session, project, AMBIGUOUS, "pending")
    repository = LlmReviewRepository(session)
    validation = valid_validation()

    call = repository.record_llm_call(
        content_item=item,
        run_id=None,
        input_json={"prompt": "test"},
        validation=validation,
    )
    judgement = repository.record_validated_judgement(
        content_item=item,
        llm_call=call,
        validation=validation,
    )

    assert call.validation_status == LlmValidationStatus.VALIDATED.value
    assert judgement.judgement_type == AMBIGUITY_REVIEW
    assert judgement.output_json["is_relevant"] is True
    assert judgement.output_json["confidence"] == 0.93
    assert item.llm_review_required is False
    assert len(session.scalars(select(LlmCallRecord)).all()) == 1
    assert len(session.scalars(select(LlmJudgementRecord)).all()) == 1


def test_failed_validation_persists_call_without_judgement() -> None:
    session = make_session()
    project = seed_project(session)
    item = add_item(session, project, AMBIGUOUS, "pending")
    repository = LlmReviewRepository(session)

    call = repository.record_failed_call(
        content_item=item,
        run_id=None,
        input_json={"prompt": "test"},
        validation=failed_validation(),
    )

    assert call.validation_status == LlmValidationStatus.FAILED.value
    assert call.output_json["error"]
    assert len(session.scalars(select(LlmCallRecord)).all()) == 1
    assert len(session.scalars(select(LlmJudgementRecord)).all()) == 0
    assert item.llm_review_required is True


def test_optional_llm_relevance_decision_uses_llm_decision_type() -> None:
    session = make_session()
    project = seed_project(session)
    item = add_item(session, project, AMBIGUOUS, "pending")
    repository = LlmReviewRepository(session)

    decision = repository.record_llm_relevance_decision(
        content_item=item,
        run_id=None,
        decision="accepted",
        score=0.86,
        reason="Validated relevant by LLM review.",
        output_json={"confidence": 0.93},
    )

    assert LLM_DECISION == "llm"
    assert decision.decision_type == "llm"
