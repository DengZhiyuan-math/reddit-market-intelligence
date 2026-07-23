from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.base import Base
from app.db.models import ContentItemRecord, ResearchProjectRecord
import app.db.models  # noqa: F401
from app.processing.exporter import export_calibration_samples
from app.processing.models import ACCEPTED, AMBIGUOUS, NEGATIVE_KEYWORD, REJECTED


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
    status: str,
    source_id: str,
    *,
    relevance_score: float | None,
    reason_codes: list[dict[str, str]] | None = None,
) -> ContentItemRecord:
    item = ContentItemRecord(
        project_id=project.id,
        source_type="reddit_post",
        source_id=source_id,
        text=f"Original text for {source_id}",
        cleaned_text=f"Cleaned calibration text for {source_id}",
        language="en",
        relevance_score=relevance_score,
        quality_score=0.8,
        ambiguity_score=0.2,
        llm_review_required=status == AMBIGUOUS,
        final_status=status,
        reason_codes=reason_codes or [],
    )
    session.add(item)
    session.flush()
    return item


def test_export_calibration_samples_groups_statuses_with_reasons(tmp_path: Path) -> None:
    session = make_session()
    project = seed_project(session)
    accepted = add_content_item(session, project, ACCEPTED, "accepted-1", relevance_score=0.91)
    ambiguous = add_content_item(session, project, AMBIGUOUS, "ambiguous-1", relevance_score=0.52)
    rejected = add_content_item(
        session,
        project,
        REJECTED,
        "rejected-1",
        relevance_score=0.12,
        reason_codes=[
            {
                "code": NEGATIVE_KEYWORD,
                "severity": "reject",
                "explanation": "Matched a negative keyword.",
            }
        ],
    )
    session.commit()

    output = export_calibration_samples(session, 1, tmp_path / "samples.md", limit_per_band=5)

    content = output.read_text()
    assert "# Calibration Samples" in content
    assert "## Accepted" in content
    assert f"### Content item {accepted.id}" in content
    assert "## Ambiguous" in content
    assert f"### Content item {ambiguous.id}" in content
    assert "llm_review_required: True" in content
    assert "## Rejected" in content
    assert f"### Content item {rejected.id}" in content
    assert "NEGATIVE_KEYWORD (reject): Matched a negative keyword." in content
    assert "Cleaned calibration text for accepted-1" in content


def test_export_calibration_samples_uses_default_project_path(
    tmp_path: Path,
    monkeypatch,
) -> None:
    session = make_session()
    project = seed_project(session)
    add_content_item(session, project, ACCEPTED, "accepted-1", relevance_score=0.91)
    session.commit()
    monkeypatch.chdir(tmp_path)

    output = export_calibration_samples(session, 1)

    assert output == Path("outputs/exports/project-1/calibration-samples.md")
    assert output.exists()


def test_export_calibration_samples_rejects_unknown_project(tmp_path: Path) -> None:
    session = make_session()

    try:
        export_calibration_samples(session, 404, tmp_path / "samples.md")
    except ValueError as exc:
        assert "Project 404 was not found" in str(exc)
    else:
        raise AssertionError("Expected ValueError")
