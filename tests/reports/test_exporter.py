from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.base import Base
from app.db.models import (
    ContentItemRecord,
    LlmCallRecord,
    MarketSignalRecord,
    ResearchProjectRecord,
)
from app.analysis.repository import MARKET_SIGNAL_EXTRACTION
from app.processing.models import ACCEPTED
from app.reports.exporter import CSV_HEADER, export_report_evidence
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


def seed_signal_and_abstention(session: Session) -> ResearchProjectRecord:
    project = seed_project(session)
    item = ContentItemRecord(
        project_id=project.id,
        source_type="reddit_post",
        source_id="post-1",
        source_table="reddit_posts_raw",
        source_mode="web_static",
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
    session.add(
        MarketSignalRecord(
            project_id=project.id,
            content_item_id=item.id,
            source_mode="web_static",
            intent_label="Find a tutor recommendation.",
            persona_label="PARENT",
            pain_point="Needs trusted math support.",
            urgency_level="medium",
            buying_signal=True,
            quote="Can anyone recommend a math tutor in Zurich?",
            confidence=0.86,
            signal_json={"fixture": True},
        )
    )
    session.add(
        LlmCallRecord(
            project_id=project.id,
            content_item_id=item.id,
            call_type=MARKET_SIGNAL_EXTRACTION,
            provider="codex-local",
            model_name="gpt-5.2-codex",
            input_json={},
            output_json={"status": "abstained", "confidence": 0.7},
            validation_status="validated",
        )
    )
    session.flush()
    return project


def test_export_report_evidence_writes_markdown_and_csv(tmp_path: Path) -> None:
    session = make_session()
    seed_signal_and_abstention(session)

    markdown_path, csv_path = export_report_evidence(session, 1, output_dir=tmp_path, limit=100)

    markdown = markdown_path.read_text(encoding="utf-8")
    csv_text = csv_path.read_text(encoding="utf-8")
    assert markdown.startswith("# Report Evidence Export")
    assert "Signal 1" in markdown
    assert "content_item_id" in markdown
    assert "source_id" in markdown
    assert "source_mode: web_static" in markdown
    assert ",".join(CSV_HEADER) in csv_text.splitlines()[0]
    assert "web_static" in csv_text
    assert "Can anyone recommend a math tutor in Zurich?" in csv_text
    assert csv_text.count("\n") == 2


def test_export_report_evidence_uses_default_paths(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    session = make_session()
    seed_signal_and_abstention(session)

    markdown_path, csv_path = export_report_evidence(session, 1)

    assert markdown_path == Path("outputs/exports/project-1/report-evidence.md")
    assert csv_path == Path("outputs/exports/project-1/report-evidence.csv")
    assert markdown_path.exists()
    assert csv_path.exists()
