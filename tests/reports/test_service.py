from pathlib import Path

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.db.base import Base
from app.db.models import (
    ContentItemRecord,
    MarketSignalRecord,
    PipelineRunRecord,
    ReportArtifactRecord,
    ResearchProjectRecord,
)
from app.processing.models import ACCEPTED
from app.reports.repository import REPORT_GENERATION
from app.reports.service import ReportGenerationServiceError, generate_market_report
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


def add_item(session: Session, project: ResearchProjectRecord) -> ContentItemRecord:
    item = ContentItemRecord(
        project_id=project.id,
        source_type="reddit_post",
        source_id="post-1",
        source_table="reddit_posts_raw",
        text="Can anyone recommend a math tutor in Zurich?",
        cleaned_text="Can anyone recommend a math tutor in Zurich?",
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


def add_signal(
    session: Session,
    project: ResearchProjectRecord,
    item: ContentItemRecord,
) -> MarketSignalRecord:
    signal = MarketSignalRecord(
        project_id=project.id,
        run_id=None,
        content_item_id=item.id,
        llm_judgement_id=None,
        intent_label="Find a tutor recommendation.",
        persona_label="PARENT",
        pain_point="Needs trusted math support.",
        urgency_level="medium",
        buying_signal=True,
        quote="Can anyone recommend a math tutor in Zurich?",
        confidence=0.86,
        signal_json={"user_persona": "PARENT", "confidence": 0.86},
    )
    session.add(signal)
    session.flush()
    return signal


def seed_one_signal(session: Session) -> ResearchProjectRecord:
    project = seed_project(session)
    item = add_item(session, project)
    add_signal(session, project, item)
    return project


def test_service_creates_default_report_run_and_artifact(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    session = make_session()
    seed_one_signal(session)

    summary = generate_market_report(session, 1)

    default_path = Path("outputs/reports/project-1/market-report.md")
    run = session.scalar(select(PipelineRunRecord))
    artifact = session.scalar(select(ReportArtifactRecord))
    assert default_path.exists()
    assert run.stage == REPORT_GENERATION
    assert run.status == "completed"
    assert artifact.format == "markdown"
    assert artifact.dataset_summary["market_signal_count"] == 1
    assert summary.artifact_id == artifact.id
    assert summary.report_path == str(default_path)


def test_zero_evidence_report_writes_caveated_artifact(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    session = make_session()
    seed_project(session)

    summary = generate_market_report(session, 1)

    markdown = Path(summary.report_path).read_text(encoding="utf-8")
    artifact = session.scalar(select(ReportArtifactRecord))
    assert "insufficient evidence" in markdown
    assert summary.warnings == ["No trusted market signals found"]
    assert artifact.dataset_summary["market_signal_count"] == 0


def test_service_respects_custom_output_path(tmp_path) -> None:
    session = make_session()
    seed_one_signal(session)
    output_path = tmp_path / "custom-report.md"

    summary = generate_market_report(session, 1, output_path=output_path)

    assert output_path.exists()
    assert summary.report_path == str(output_path)


def test_file_write_failure_marks_run_failed(monkeypatch) -> None:
    session = make_session()
    seed_one_signal(session)

    def fail_write(_output_path: Path, _markdown: str) -> None:
        raise OSError("disk is full")

    monkeypatch.setattr("app.reports.service._write_report_file", fail_write)

    with pytest.raises(ReportGenerationServiceError):
        generate_market_report(session, 1)

    run = session.scalar(select(PipelineRunRecord).order_by(PipelineRunRecord.id.desc()))
    assert run.status == "failed"


def test_successful_reruns_create_artifact_history_without_mutating_signals(tmp_path) -> None:
    session = make_session()
    seed_one_signal(session)
    output_path = tmp_path / "market-report.md"

    generate_market_report(session, 1, output_path=output_path)
    generate_market_report(session, 1, output_path=output_path)

    artifacts = session.scalars(select(ReportArtifactRecord)).all()
    signals = session.scalars(select(MarketSignalRecord)).all()
    assert len(artifacts) == 2
    assert len(signals) == 1
