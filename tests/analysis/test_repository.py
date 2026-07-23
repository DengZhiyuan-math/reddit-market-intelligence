from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.analysis.gateway import validate_signal_provider_result
from app.analysis.models import SignalExtractionProviderResult, SignalExtractionRunSummary
from app.analysis.repository import MARKET_SIGNAL_EXTRACTION, SignalExtractionRepository
from app.db.base import Base
from app.db.models import (
    ContentItemRecord,
    LlmCallRecord,
    LlmJudgementRecord,
    MarketSignalRecord,
    PipelineRunRecord,
    ResearchProjectRecord,
)
import app.db.models  # noqa: F401
from app.llm.models import LlmValidationStatus
from app.llm.repository import AMBIGUITY_REVIEW
from app.processing.models import ACCEPTED, REJECTED


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
    text: str | None = None,
) -> ContentItemRecord:
    item = ContentItemRecord(
        project_id=project.id,
        source_type="reddit_post",
        source_id=source_id,
        text=text or f"Original text for {source_id}",
        cleaned_text=f"Cleaned text for {source_id}",
        language="en",
        relevance_score=0.8,
        quality_score=0.9,
        ambiguity_score=0.5,
        llm_review_required=False,
        final_status=status,
        reason_codes=[],
    )
    session.add(item)
    session.flush()
    return item


def add_judgement(
    session: Session,
    item: ContentItemRecord,
    *,
    is_relevant: bool = True,
    validation_status: LlmValidationStatus = LlmValidationStatus.VALIDATED,
) -> LlmJudgementRecord:
    judgement = LlmJudgementRecord(
        content_item_id=item.id,
        judgement_type=AMBIGUITY_REVIEW,
        output_json={
            "is_relevant": is_relevant,
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
        model_name="gpt-5.2-codex",
        validation_status=validation_status.value,
    )
    session.add(judgement)
    session.flush()
    return judgement


def valid_signal_validation(source_text: str = "Can anyone recommend a math tutor in Zurich?"):
    return validate_signal_provider_result(
        SignalExtractionProviderResult(
            output={
                "status": "extracted",
                "signals": [
                    {
                        "user_persona": "PARENT",
                        "user_problem": "Needs trusted math support.",
                        "explicit_need": "Find a tutor recommendation.",
                        "implicit_need": "Reduce school pressure.",
                        "emotional_tone": "worried",
                        "purchase_intent": "medium",
                        "trust_concern": True,
                        "price_concern": False,
                        "urgency": "medium",
                        "useful_quote": source_text,
                        "recommended_business_response": "Offer transparent curriculum support.",
                        "confidence": 0.86,
                    }
                ],
                "abstention_reason": None,
                "confidence": 0.86,
            },
            provider="codex-local",
            model="gpt-5.2-codex",
            raw_response_json={"fixture": "valid"},
        ),
        source_text=source_text,
    )


def abstained_signal_validation():
    return validate_signal_provider_result(
        SignalExtractionProviderResult(
            output={
                "status": "abstained",
                "signals": [],
                "abstention_reason": "Evidence is too generic.",
                "confidence": 0.72,
            }
        ),
        source_text="Generic education discussion.",
    )


def test_candidate_selection_includes_only_eligible_evidence() -> None:
    session = make_session()
    project = seed_project(session)
    accepted = add_item(session, project, ACCEPTED, "accepted")
    add_item(session, project, REJECTED, "rejected")
    relevant_item = add_item(session, project, REJECTED, "relevant-judgement")
    irrelevant_item = add_item(session, project, REJECTED, "irrelevant-judgement")
    invalid_item = add_item(session, project, REJECTED, "invalid-judgement")
    relevant_judgement = add_judgement(session, relevant_item, is_relevant=True)
    add_judgement(session, irrelevant_item, is_relevant=False)
    add_judgement(
        session,
        invalid_item,
        is_relevant=True,
        validation_status=LlmValidationStatus.FAILED,
    )
    repository = SignalExtractionRepository(session)

    candidates = repository.list_signal_candidates(project.id)

    assert [candidate.content_item_id for candidate in candidates] == [
        accepted.id,
        relevant_item.id,
    ]
    assert candidates[0].llm_judgement_id is None
    assert candidates[1].llm_judgement_id == relevant_judgement.id
    assert repository.list_signal_candidates(project.id, limit=1) == [candidates[0]]


def test_signal_run_and_call_lifecycle_are_auditable() -> None:
    session = make_session()
    project = seed_project(session)
    item = add_item(session, project, ACCEPTED, "accepted")
    repository = SignalExtractionRepository(session)
    candidate = repository.list_signal_candidates(project.id)[0]
    validation = valid_signal_validation()

    run = repository.start_signal_run(project.id, {"limit": 10})
    call = repository.record_extraction_call(
        candidate=candidate,
        run_id=run.id,
        input_json={"prompt": "test"},
        validation=validation,
    )
    signal = repository.record_market_signal(
        candidate=candidate,
        run_id=run.id,
        signal=validation.output.signals[0],
        llm_call_id=call.id,
    )
    repository.complete_signal_run(run.id, "completed", SignalExtractionRunSummary(candidates=1))

    persisted_run = session.scalar(select(PipelineRunRecord))
    persisted_call = session.scalar(select(LlmCallRecord))

    assert item.id == signal.content_item_id
    assert persisted_run.stage == MARKET_SIGNAL_EXTRACTION
    assert persisted_run.summary["candidates"] == 1
    assert persisted_call.call_type == MARKET_SIGNAL_EXTRACTION
    assert persisted_call.validation_status == LlmValidationStatus.VALIDATED.value
    assert signal.signal_json["llm_call_id"] == call.id
    assert signal.buying_signal is True


def test_judgement_derived_signal_persists_judgement_source_link() -> None:
    session = make_session()
    project = seed_project(session)
    item = add_item(session, project, REJECTED, "relevant-judgement")
    judgement = add_judgement(session, item)
    repository = SignalExtractionRepository(session)
    candidate = repository.list_signal_candidates(project.id)[0]
    validation = valid_signal_validation()

    signal = repository.record_market_signal(
        candidate=candidate,
        run_id=None,
        signal=validation.output.signals[0],
    )

    assert signal.content_item_id == item.id
    assert signal.llm_judgement_id == judgement.id


def test_abstained_output_is_audited_without_market_signal() -> None:
    session = make_session()
    project = seed_project(session)
    add_item(session, project, ACCEPTED, "accepted")
    repository = SignalExtractionRepository(session)
    candidate = repository.list_signal_candidates(project.id)[0]

    repository.record_extraction_call(
        candidate=candidate,
        run_id=None,
        input_json={"prompt": "test"},
        validation=abstained_signal_validation(),
    )

    assert len(session.scalars(select(LlmCallRecord)).all()) == 1
    assert len(session.scalars(select(MarketSignalRecord)).all()) == 0


def test_existing_accepted_signal_is_excluded_on_rerun() -> None:
    session = make_session()
    project = seed_project(session)
    item = add_item(session, project, ACCEPTED, "accepted")
    repository = SignalExtractionRepository(session)
    candidate = repository.list_signal_candidates(project.id)[0]
    validation = valid_signal_validation()

    repository.record_market_signal(candidate=candidate, run_id=None, signal=validation.output.signals[0])

    assert repository.has_existing_signals(item.id, None) is True
    assert repository.list_signal_candidates(project.id) == []


def test_existing_judgement_signal_excludes_only_same_judgement() -> None:
    session = make_session()
    project = seed_project(session)
    item = add_item(session, project, REJECTED, "multi-judgement")
    first_judgement = add_judgement(session, item)
    second_judgement = add_judgement(session, item)
    repository = SignalExtractionRepository(session)
    first_candidate, second_candidate = repository.list_signal_candidates(project.id)
    validation = valid_signal_validation()

    repository.record_market_signal(
        candidate=first_candidate,
        run_id=None,
        signal=validation.output.signals[0],
    )
    remaining_candidates = repository.list_signal_candidates(project.id)

    assert first_candidate.llm_judgement_id == first_judgement.id
    assert second_candidate.llm_judgement_id == second_judgement.id
    assert [candidate.llm_judgement_id for candidate in remaining_candidates] == [
        second_judgement.id
    ]
