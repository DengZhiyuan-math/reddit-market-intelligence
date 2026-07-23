from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.analysis.gateway import DeterministicSignalProvider
from app.analysis.models import SignalExtractionRequest
from app.analysis.service import SignalExtractionServiceError, run_signal_extraction
from app.config import Settings
from app.db.base import Base
from app.db.models import (
    ContentItemRecord,
    LlmCallRecord,
    MarketSignalRecord,
    PipelineRunRecord,
    ResearchProjectRecord,
)
import app.db.models  # noqa: F401
from app.processing.models import ACCEPTED


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


def add_accepted_item(
    session: Session,
    project: ResearchProjectRecord,
    source_id: str = "accepted-1",
    text: str = "Can anyone recommend a math tutor in Zurich?",
) -> ContentItemRecord:
    item = ContentItemRecord(
        project_id=project.id,
        source_type="reddit_post",
        source_id=source_id,
        source_table="reddit_posts_raw",
        text=text,
        cleaned_text=text,
        language="en",
        relevance_score=0.82,
        quality_score=0.91,
        ambiguity_score=0.1,
        llm_review_required=False,
        final_status=ACCEPTED,
        reason_codes=[],
    )
    session.add(item)
    session.flush()
    return item


def two_signal_provider() -> DeterministicSignalProvider:
    quote = "Can anyone recommend a math tutor in Zurich?"
    return DeterministicSignalProvider(
        fixture_output={
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
                    "useful_quote": quote,
                    "recommended_business_response": "Offer transparent curriculum support.",
                    "confidence": 0.86,
                },
                {
                    "user_persona": "PARENT",
                    "user_problem": "Wants local Zurich-specific help.",
                    "explicit_need": "Find tutoring in Zurich.",
                    "implicit_need": "Avoid mismatched generic support.",
                    "emotional_tone": "practical",
                    "purchase_intent": "low",
                    "trust_concern": False,
                    "price_concern": False,
                    "urgency": "low",
                    "useful_quote": quote,
                    "recommended_business_response": "Explain Swiss curriculum fit.",
                    "confidence": 0.78,
                },
            ],
            "abstention_reason": None,
            "confidence": 0.86,
        }
    )


class RaisingProvider:
    provider = "codex-local"
    model = "gpt-5.2-codex"

    def extract(self, request: SignalExtractionRequest):
        raise RuntimeError("provider crashed")


def test_dry_run_returns_candidate_summary_without_writes() -> None:
    session = make_session()
    project = seed_project(session)
    add_accepted_item(session, project)

    summary = run_signal_extraction(session, 1, dry_run=True)

    assert summary.candidates == 1
    assert summary.remaining == 1
    assert len(session.scalars(select(PipelineRunRecord)).all()) == 0
    assert len(session.scalars(select(LlmCallRecord)).all()) == 0
    assert len(session.scalars(select(MarketSignalRecord)).all()) == 0


def test_service_uses_settings_default_limit() -> None:
    session = make_session()
    project = seed_project(session)
    add_accepted_item(session, project, "one")
    add_accepted_item(session, project, "two")
    settings = Settings(_env_file=None, signal_extraction_default_limit=1)

    summary = run_signal_extraction(session, 1, dry_run=True, settings=settings)

    assert summary.candidates == 1
    assert summary.remaining == 2


def test_valid_provider_output_with_two_signals_persists_two_rows() -> None:
    session = make_session()
    project = seed_project(session)
    add_accepted_item(session, project)

    summary = run_signal_extraction(session, 1, provider=two_signal_provider())

    run = session.scalar(select(PipelineRunRecord))
    signals = session.scalars(select(MarketSignalRecord)).all()
    assert summary.extracted_signals == 2
    assert summary.abstained == 0
    assert summary.failed == 0
    assert run is not None
    assert run.stage == "market_signal_extraction"
    assert run.status == "completed"
    assert len(session.scalars(select(LlmCallRecord)).all()) == 1
    assert len(signals) == 2
    assert signals[0].content_item_id == signals[1].content_item_id
    assert {
        "user_persona",
        "user_problem",
        "explicit_need",
        "implicit_need",
        "emotional_tone",
        "purchase_intent",
        "trust_concern",
        "price_concern",
        "urgency",
        "useful_quote",
        "recommended_business_response",
        "confidence",
    }.issubset(signals[0].signal_json)


def test_abstained_provider_output_creates_call_without_signal() -> None:
    session = make_session()
    project = seed_project(session)
    add_accepted_item(session, project, text="Generic education discussion.")
    provider = DeterministicSignalProvider(
        fixture_output={
            "status": "abstained",
            "signals": [],
            "abstention_reason": "Evidence is too generic.",
            "confidence": 0.72,
        }
    )

    summary = run_signal_extraction(session, 1, provider=provider)

    assert summary.abstained == 1
    assert summary.extracted_signals == 0
    assert len(session.scalars(select(LlmCallRecord)).all()) == 1
    assert len(session.scalars(select(MarketSignalRecord)).all()) == 0


def test_invalid_provider_output_creates_failed_call_without_signal() -> None:
    session = make_session()
    project = seed_project(session)
    add_accepted_item(session, project)
    provider = DeterministicSignalProvider(fixture_output={"status": "extracted", "confidence": 0.9})

    summary = run_signal_extraction(session, 1, provider=provider)

    call = session.scalar(select(LlmCallRecord))
    assert summary.failed == 1
    assert summary.extracted_signals == 0
    assert call is not None
    assert call.validation_status == "failed"
    assert len(session.scalars(select(MarketSignalRecord)).all()) == 0


def test_provider_exception_marks_pipeline_run_failed() -> None:
    session = make_session()
    project = seed_project(session)
    add_accepted_item(session, project)

    try:
        run_signal_extraction(session, 1, provider=RaisingProvider())
    except SignalExtractionServiceError as exc:
        assert "provider crashed" in str(exc)
    else:
        raise AssertionError("Expected SignalExtractionServiceError")

    run = session.scalar(select(PipelineRunRecord))
    assert run is not None
    assert run.stage == "market_signal_extraction"
    assert run.status == "failed"
    assert run.summary["errors"] == 1


def test_rerun_does_not_duplicate_market_signals() -> None:
    session = make_session()
    project = seed_project(session)
    add_accepted_item(session, project)

    first = run_signal_extraction(session, 1, provider=two_signal_provider())
    second = run_signal_extraction(session, 1, provider=two_signal_provider())

    assert first.extracted_signals == 2
    assert second.candidates == 0
    assert second.extracted_signals == 0
    assert second.skipped_duplicates == 0
    assert len(session.scalars(select(MarketSignalRecord)).all()) == 2
