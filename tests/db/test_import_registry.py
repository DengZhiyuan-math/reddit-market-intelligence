"""Tests for explicit JSON registry database import."""

from datetime import UTC, datetime

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.compliance.policies import AccessMode
from app.db.base import Base
from app.db.import_registry import import_project_registry
from app.db.models import ProjectStageRunRecord, ResearchProjectRecord, RetentionPolicyRecord
import app.db.models  # noqa: F401
from app.projects.models import ProjectCreateInput, StageRun, StageStatus
from app.projects.service import create_project, record_stage_run
from app.projects.store import ProjectRegistryStore


def make_session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def create_registry(registry_path) -> None:
    store = ProjectRegistryStore(registry_path)
    project = create_project(
        store,
        ProjectCreateInput(
            topic="Swiss tutoring market",
            region="Zurich",
            languages=["en", "de"],
            target_users=["parents"],
            business_context="AI + human tutor platform",
            time_range="last 12 months",
            access_mode=AccessMode.COMMERCIAL_APPROVED,
        ),
    )
    record_stage_run(
        store,
        project.project_id,
        StageRun(
            stage="topic-planning",
            status=StageStatus.SUCCEEDED,
            started_at=datetime(2026, 5, 20, tzinfo=UTC),
            completed_at=datetime(2026, 5, 20, tzinfo=UTC),
            run_limit=25,
            message="metadata only",
        ),
    )


def test_import_project_registry_preserves_phase_2_project_metadata(tmp_path) -> None:
    registry_path = tmp_path / "projects.json"
    create_registry(registry_path)
    session = make_session()

    result = import_project_registry(registry_path, session)

    project = session.scalar(select(ResearchProjectRecord))
    retention = session.scalar(select(RetentionPolicyRecord))
    stage_run = session.scalar(select(ProjectStageRunRecord))
    assert result.imported_projects == 1
    assert result.imported_stage_runs == 1
    assert project is not None
    assert project.project_id == 1
    assert project.slug == "swiss-tutoring-market"
    assert project.access_mode == "commercial-approved"
    assert project.run_config["limit"] == 100
    assert project.collection_eligibility["allowed"] is True
    assert retention is not None
    assert "raw_text" in retention.targets
    assert stage_run is not None
    assert stage_run.stage == "topic-planning"
    assert stage_run.status == "succeeded"


def test_repeat_import_does_not_duplicate_project_or_stage_rows(tmp_path) -> None:
    registry_path = tmp_path / "projects.json"
    create_registry(registry_path)
    session = make_session()

    first = import_project_registry(registry_path, session)
    second = import_project_registry(registry_path, session)

    projects = session.scalars(select(ResearchProjectRecord)).all()
    stage_runs = session.scalars(select(ProjectStageRunRecord)).all()
    assert first.imported_projects == 1
    assert second.imported_projects == 0
    assert second.updated_projects == 1
    assert len(projects) == 1
    assert len(stage_runs) == 1
