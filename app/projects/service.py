"""Service layer for creating and reading durable research projects."""

import re
from datetime import UTC, datetime

from app.compliance.policies import (
    ProjectPolicyContext,
    RetentionPolicy,
    evaluate_collection_eligibility,
)
from app.projects.models import ProjectCreateInput, ResearchProject, RunConfig, StageRun
from app.projects.store import ProjectRegistryStore


class ProjectNotFoundError(ValueError):
    """Raised when a requested project ID does not exist."""


def slugify_topic(topic: str) -> str:
    """Create a stable, readable slug from a project topic."""

    slug = re.sub(r"[^a-z0-9]+", "-", topic.lower()).strip("-")
    return slug or "project"


def create_project(
    store: ProjectRegistryStore,
    project_input: ProjectCreateInput,
    run_config: RunConfig | None = None,
    dry_run: bool = False,
) -> ResearchProject:
    """Create a research project and persist it unless dry-run is enabled."""

    now = datetime.now(UTC)
    project_id = store.load().next_project_id if dry_run else store.next_project_id()
    eligibility = evaluate_collection_eligibility(
        ProjectPolicyContext(
            access_mode=project_input.access_mode,
            business_context=project_input.business_context,
        )
    )
    project = ResearchProject(
        project_id=project_id,
        slug=slugify_topic(project_input.topic),
        topic=project_input.topic,
        region=project_input.region,
        languages=project_input.languages,
        target_users=project_input.target_users,
        business_context=project_input.business_context,
        time_range=project_input.time_range,
        access_mode=project_input.access_mode,
        retention_policy=RetentionPolicy(),
        collection_eligibility=eligibility,
        run_config=run_config or RunConfig(),
        stage_runs=[],
        created_at=now,
        updated_at=now,
    )
    if not dry_run:
        store.add_project(project)
    return project


def get_project_or_raise(store: ProjectRegistryStore, project_id: int) -> ResearchProject:
    """Return a project or raise a readable service error."""

    project = store.get_project(project_id)
    if project is None:
        raise ProjectNotFoundError(f"Project not found: {project_id}")
    return project


def record_stage_run(
    store: ProjectRegistryStore,
    project_id: int,
    stage_run: StageRun,
) -> ResearchProject:
    """Append metadata for a stage run without recreating project state."""

    project = get_project_or_raise(store, project_id)
    updated_project = project.model_copy(
        update={
            "stage_runs": [*project.stage_runs, stage_run],
            "updated_at": datetime.now(UTC),
        }
    )
    store.update_project(updated_project)
    return updated_project


def list_stage_runs(store: ProjectRegistryStore, project_id: int) -> list[StageRun]:
    """List stage run metadata for a project."""

    return get_project_or_raise(store, project_id).stage_runs
