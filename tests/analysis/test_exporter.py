from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.analysis.exporter import export_market_signals
from app.db.base import Base
from app.db.models import ContentItemRecord, MarketSignalRecord, ResearchProjectRecord
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


def add_content_item(
    session: Session,
    project: ResearchProjectRecord,
    source_id: str = "post-123",
) -> ContentItemRecord:
    item = ContentItemRecord(
        project_id=project.id,
        source_type="reddit_post",
        source_id=source_id,
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


def add_market_signal(
    session: Session,
    project: ResearchProjectRecord,
    item: ContentItemRecord,
) -> MarketSignalRecord:
    signal = MarketSignalRecord(
        project_id=project.id,
        content_item_id=item.id,
        persona_label="PARENT",
        pain_point="Needs trusted math support.",
        urgency_level="medium",
        buying_signal=True,
        quote="Can anyone recommend a math tutor in Zurich?",
        confidence=0.86,
        signal_json={
            "user_persona": "PARENT",
            "user_problem": "Needs trusted math support.",
            "explicit_need": "Find a tutor recommendation.",
            "confidence": 0.86,
        },
    )
    session.add(signal)
    session.flush()
    return signal


def test_export_market_signals_contains_signal_details(tmp_path: Path) -> None:
    session = make_session()
    project = seed_project(session)
    item = add_content_item(session, project)
    signal = add_market_signal(session, project, item)
    output = tmp_path / "market-signals.md"

    path = export_market_signals(session, 1, output, limit=50)

    content = path.read_text()
    assert path == output
    assert "# Market Signal QA Export" in content
    assert f"Market signal {signal.id}" in content
    assert f"content_item_id: {item.id}" in content
    assert "post-123" in content
    assert "Can anyone recommend a math tutor in Zurich?" in content
    assert "confidence: 0.860" in content
    assert "Executive Summary" not in content
    assert "Actionable Recommendations" not in content


def test_export_market_signals_honors_limit(tmp_path: Path) -> None:
    session = make_session()
    project = seed_project(session)
    first = add_content_item(session, project)
    add_market_signal(session, project, first)
    second = add_content_item(session, project, "post-456")
    add_market_signal(session, project, second)

    path = export_market_signals(session, 1, tmp_path / "signals.md", limit=1)

    content = path.read_text()
    assert "Signal count: 1" in content
    assert content.count("### Market signal") == 1


def test_export_market_signals_uses_default_path(monkeypatch, tmp_path: Path) -> None:
    session = make_session()
    project = seed_project(session)
    item = add_content_item(session, project)
    add_market_signal(session, project, item)
    monkeypatch.chdir(tmp_path)

    path = export_market_signals(session, 1)

    assert path == Path("outputs/exports/project-1/market-signals.md")
    assert path.exists()


def test_export_market_signals_requires_existing_project(tmp_path: Path) -> None:
    session = make_session()

    try:
        export_market_signals(session, 404, tmp_path / "signals.md")
    except ValueError as exc:
        assert "Project not found in database: 404" in str(exc)
    else:
        raise AssertionError("Expected ValueError for missing project")
