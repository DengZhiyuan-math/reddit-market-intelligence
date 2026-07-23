from app.compliance.policies import AccessMode, EligibilitySeverity
import pytest

from app.projects.models import ProjectCreateInput, RunConfig, StageRun, StageStatus
from app.projects.service import (
    ProjectNotFoundError,
    create_project,
    list_stage_runs,
    record_stage_run,
    slugify_topic,
)
from app.projects.store import ProjectRegistryStore


def test_slugify_topic_creates_readable_slug() -> None:
    assert slugify_topic("Swiss tutoring market in Zurich") == "swiss-tutoring-market-in-zurich"


def test_create_project_persists_durable_metadata(tmp_path) -> None:
    store = ProjectRegistryStore(tmp_path / "projects.json")

    project = create_project(
        store,
        ProjectCreateInput(
            topic="Swiss tutoring market in Zurich",
            region="Switzerland, Zurich",
            languages=["en", "de"],
            target_users=["parents", "students"],
            time_range="last 12 months",
            access_mode=AccessMode.PERSONAL,
        ),
        run_config=RunConfig(limit=50),
    )

    stored = store.get_project(1)
    assert stored is not None
    assert project.project_id == 1
    assert stored.project_id == 1
    assert stored.slug == "swiss-tutoring-market-in-zurich"
    assert stored.topic == "Swiss tutoring market in Zurich"
    assert stored.region == "Switzerland, Zurich"
    assert stored.languages == ["en", "de"]
    assert stored.target_users == ["parents", "students"]
    assert stored.run_config.limit == 50
    assert stored.retention_policy.retention_days == 2
    assert stored.created_at == stored.updated_at


def test_business_context_with_personal_access_records_blocked_eligibility(tmp_path) -> None:
    store = ProjectRegistryStore(tmp_path / "projects.json")

    project = create_project(
        store,
        ProjectCreateInput(
            topic="Swiss tutoring market",
            business_context="AI + human tutor platform",
            access_mode=AccessMode.PERSONAL,
        ),
    )

    assert project.collection_eligibility.allowed is False
    assert project.collection_eligibility.severity is EligibilitySeverity.BLOCK
    assert project.collection_eligibility.required_action is not None


def test_business_context_with_commercial_approved_access_records_allowed_eligibility(
    tmp_path,
) -> None:
    store = ProjectRegistryStore(tmp_path / "projects.json")

    project = create_project(
        store,
        ProjectCreateInput(
            topic="Swiss tutoring market",
            business_context="AI + human tutor platform",
            access_mode=AccessMode.COMMERCIAL_APPROVED,
        ),
    )

    assert project.collection_eligibility.allowed is True
    assert project.collection_eligibility.severity is EligibilitySeverity.ALLOW


def test_dry_run_does_not_write_registry(tmp_path) -> None:
    registry_path = tmp_path / "projects.json"
    store = ProjectRegistryStore(registry_path)

    project = create_project(
        store,
        ProjectCreateInput(topic="Swiss tutoring market", access_mode=AccessMode.PERSONAL),
        dry_run=True,
    )

    assert project.project_id == 1
    assert registry_path.exists() is False


def test_record_stage_run_preserves_project_metadata(tmp_path) -> None:
    store = ProjectRegistryStore(tmp_path / "projects.json")
    project = create_project(
        store,
        ProjectCreateInput(
            topic="Swiss tutoring market in Zurich",
            access_mode=AccessMode.PERSONAL,
        ),
    )

    updated = record_stage_run(
        store,
        project.project_id,
        StageRun(stage="topic_planning", status=StageStatus.SUCCEEDED, run_limit=25),
    )

    stored = store.get_project(project.project_id)
    assert stored is not None
    assert updated.topic == "Swiss tutoring market in Zurich"
    assert updated.slug == "swiss-tutoring-market-in-zurich"
    assert updated.access_mode is AccessMode.PERSONAL
    assert len(updated.stage_runs) == 1
    assert updated.stage_runs[0].stage == "topic_planning"
    assert updated.stage_runs[0].status is StageStatus.SUCCEEDED
    assert stored.topic == project.topic
    assert stored.stage_runs[0].run_limit == 25


def test_record_stage_run_unknown_project_is_readable_error(tmp_path) -> None:
    store = ProjectRegistryStore(tmp_path / "projects.json")

    with pytest.raises(ProjectNotFoundError, match="Project not found"):
        record_stage_run(
            store,
            999,
            StageRun(stage="topic_planning", status=StageStatus.FAILED),
        )


def test_list_stage_runs_returns_project_stage_metadata(tmp_path) -> None:
    store = ProjectRegistryStore(tmp_path / "projects.json")
    project = create_project(
        store,
        ProjectCreateInput(topic="Swiss tutoring market", access_mode=AccessMode.PERSONAL),
    )
    record_stage_run(
        store,
        project.project_id,
        StageRun(stage="topic_planning", status=StageStatus.SUCCEEDED),
    )

    stage_runs = list_stage_runs(store, project.project_id)

    assert len(stage_runs) == 1
    assert stage_runs[0].stage == "topic_planning"
