from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.analysis.repository import MARKET_SIGNAL_EXTRACTION
from app.db.base import Base
from app.db.models import (
    ContentItemRecord,
    LlmCallRecord,
    MarketSignalRecord,
    PipelineRunRecord,
    ReportArtifactRecord,
    ResearchProjectRecord,
)
from app.processing.models import ACCEPTED, AMBIGUOUS, REJECTED
from app.reports.models import ReportGenerationSummary
from app.reports.repository import REPORT_GENERATION, ReportRepository
import app.db.models  # noqa: F401


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
    source_mode: str = "reddit_api",
) -> ContentItemRecord:
    item = ContentItemRecord(
        project_id=project.id,
        source_type="reddit_post",
        source_id=source_id,
        source_mode=source_mode,
        text=f"Original text for {source_id}",
        cleaned_text=f"Cleaned text for {source_id}",
        language="en",
        relevance_score=0.8,
        quality_score=0.9,
        ambiguity_score=0.2,
        llm_review_required=False,
        final_status=status,
        reason_codes=[],
    )
    session.add(item)
    session.flush()
    return item


def add_signal(
    session: Session,
    project: ResearchProjectRecord,
    item: ContentItemRecord,
    *,
    confidence: float | None = 0.86,
    persona: str = "PARENT",
    pain_point: str = "Needs trusted math support.",
) -> MarketSignalRecord:
    signal = MarketSignalRecord(
        project_id=project.id,
        run_id=None,
        content_item_id=item.id,
        llm_judgement_id=None,
        source_mode=item.source_mode,
        intent_label="Find a tutor recommendation.",
        persona_label=persona,
        pain_point=pain_point,
        urgency_level="medium",
        buying_signal=True,
        quote="Can anyone recommend a math tutor in Zurich?",
        confidence=confidence,
        signal_json={"user_persona": persona, "confidence": confidence},
    )
    session.add(signal)
    session.flush()
    return signal


def add_extraction_call(
    session: Session,
    project: ResearchProjectRecord,
    item: ContentItemRecord,
    status: str,
) -> LlmCallRecord:
    call = LlmCallRecord(
        project_id=project.id,
        content_item_id=item.id,
        call_type=MARKET_SIGNAL_EXTRACTION,
        provider="codex-local",
        model_name="gpt-5.2-codex",
        input_json={"text": item.cleaned_text},
        output_json={"status": status, "confidence": 0.7},
        validation_status="validated",
    )
    session.add(call)
    session.flush()
    return call


def test_list_evidence_items_returns_source_linked_market_signals() -> None:
    session = make_session()
    project = seed_project(session)
    item = add_item(session, project, ACCEPTED, "post-1")
    signal = add_signal(session, project, item)
    repository = ReportRepository(session)

    evidence_items = repository.list_evidence_items(project.id)

    assert len(evidence_items) == 1
    assert evidence_items[0].signal_id == signal.id
    assert evidence_items[0].content_item_id == item.id
    assert evidence_items[0].source_type == "reddit_post"
    assert evidence_items[0].source_id == "post-1"
    assert evidence_items[0].source_mode == "reddit_api"


def test_dataset_summary_counts_signals_statuses_and_abstentions() -> None:
    session = make_session()
    project = seed_project(session)
    accepted = add_item(session, project, ACCEPTED, "accepted")
    add_item(session, project, REJECTED, "rejected")
    add_item(session, project, AMBIGUOUS, "ambiguous", source_mode="web_static")
    add_signal(session, project, accepted)
    add_extraction_call(session, project, accepted, "abstained")
    add_extraction_call(session, project, accepted, "uncertain")
    repository = ReportRepository(session)

    summary = repository.build_dataset_summary(project.id)

    assert summary.market_signal_count == 1
    assert summary.content_status_counts == {
        "accepted": 1,
        "rejected": 1,
        "ambiguous": 1,
    }
    assert summary.persona_counts == {"PARENT": 1}
    assert summary.pain_point_counts == {"Needs trusted math support.": 1}
    assert summary.urgency_counts == {"medium": 1}
    assert summary.buying_signal_counts == {"true": 1, "false": 0, "unknown": 0}
    assert summary.source_mode_counts == {"reddit_api": 2, "web_static": 1}
    assert summary.abstained_count == 1
    assert summary.uncertain_count == 1


def test_list_evidence_items_limit_and_confidence_ordering() -> None:
    session = make_session()
    project = seed_project(session)
    low_item = add_item(session, project, ACCEPTED, "low")
    high_item = add_item(session, project, ACCEPTED, "high")
    null_item = add_item(session, project, ACCEPTED, "null")
    add_signal(session, project, low_item, confidence=0.4)
    high_signal = add_signal(session, project, high_item, confidence=0.95)
    add_signal(session, project, null_item, confidence=None)
    repository = ReportRepository(session)

    evidence_items = repository.list_evidence_items(project.id, limit=1)

    assert len(evidence_items) == 1
    assert evidence_items[0].signal_id == high_signal.id


def test_report_run_lifecycle_uses_report_generation_stage() -> None:
    session = make_session()
    project = seed_project(session)
    repository = ReportRepository(session)

    run = repository.start_report_run(project.id, {"limit": 50})
    repository.complete_report_run(
        run.id,
        "completed",
        ReportGenerationSummary(market_signal_count=2),
    )

    persisted_run = session.scalar(select(PipelineRunRecord))
    assert persisted_run.stage == REPORT_GENERATION
    assert persisted_run.status == "completed"
    assert persisted_run.summary["market_signal_count"] == 2


def test_record_report_artifact_persists_auditable_payload() -> None:
    session = make_session()
    project = seed_project(session)
    item = add_item(session, project, ACCEPTED, "post-1")
    add_signal(session, project, item)
    repository = ReportRepository(session)
    dataset_summary = repository.build_dataset_summary(project.id)

    artifact = repository.record_report_artifact(
        project_db_id=project.id,
        run_id=None,
        artifact_path="outputs/reports/project-1/market-report.md",
        format="markdown",
        dataset_summary=dataset_summary,
        report_json={"sections": []},
    )

    persisted_artifact = session.scalar(select(ReportArtifactRecord))
    assert artifact.id == persisted_artifact.id
    assert persisted_artifact.format == "markdown"
    assert persisted_artifact.artifact_path == "outputs/reports/project-1/market-report.md"
    assert persisted_artifact.dataset_summary["market_signal_count"] == 1
    assert persisted_artifact.report_json == {"sections": []}
