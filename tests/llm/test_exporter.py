from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.base import Base
from app.db.models import ContentItemRecord, ResearchProjectRecord
import app.db.models  # noqa: F401
from app.llm.exporter import export_review_queue
from app.processing.models import ACCEPTED, AMBIGUOUS, REJECTED


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
    text: str | None = None,
) -> ContentItemRecord:
    item = ContentItemRecord(
        project_id=project.id,
        source_type="reddit_post",
        source_id=source_id,
        text=text or f"Original text for {source_id}",
        cleaned_text=text or f"Cleaned text for {source_id}",
        language="en",
        relevance_score=0.51,
        quality_score=0.82,
        ambiguity_score=0.71,
        llm_review_required=review_required,
        final_status=status,
        reason_codes=[],
    )
    session.add(item)
    session.flush()
    return item


def test_export_review_queue_contains_pending_ambiguous_items(tmp_path: Path) -> None:
    session = make_session()
    project = seed_project(session)
    pending = add_item(
        session,
        project,
        AMBIGUOUS,
        "pending-1",
        text="Can anyone recommend a math tutor in Zurich for Gymnasium preparation?",
    )
    add_item(session, project, ACCEPTED, "accepted-1")
    add_item(session, project, REJECTED, "rejected-1")
    output = tmp_path / "queue.md"

    path = export_review_queue(session, 1, output, limit=50)

    content = path.read_text()
    assert path == output
    assert "# LLM Review Queue" in content
    assert "## Pending Ambiguous Items" in content
    assert f"Content item {pending.id}" in content
    assert "source_id: pending-1" in content
    assert "math tutor in Zurich" in content
    assert "accepted-1" not in content
    assert "rejected-1" not in content


def test_export_review_queue_honors_limit(tmp_path: Path) -> None:
    session = make_session()
    project = seed_project(session)
    add_item(session, project, AMBIGUOUS, "first")
    add_item(session, project, AMBIGUOUS, "second")

    path = export_review_queue(session, 1, tmp_path / "queue.md", limit=1)

    content = path.read_text()
    assert "Pending item count: 1" in content
    assert content.count("### Content item") == 1


def test_export_review_queue_uses_default_path(monkeypatch, tmp_path: Path) -> None:
    session = make_session()
    project = seed_project(session)
    add_item(session, project, AMBIGUOUS, "pending")
    monkeypatch.chdir(tmp_path)

    path = export_review_queue(session, 1)

    assert path == Path("outputs/exports/project-1/llm-review-queue.md")
    assert path.exists()


def test_export_review_queue_requires_existing_project(tmp_path: Path) -> None:
    session = make_session()

    try:
        export_review_queue(session, 404, tmp_path / "queue.md")
    except ValueError as exc:
        assert "Project not found in database: 404" in str(exc)
    else:
        raise AssertionError("Expected ValueError for missing project")
