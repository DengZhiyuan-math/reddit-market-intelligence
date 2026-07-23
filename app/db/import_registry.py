"""Import Phase 2 JSON project registries into the Phase 3 database schema."""

from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import (
    ProjectStageRunRecord,
    ResearchProjectRecord,
    RetentionPolicyRecord,
)
from app.projects.models import ResearchProject, StageRun
from app.projects.store import ProjectRegistryStore


@dataclass(frozen=True)
class RegistryImportResult:
    """Summary of an explicit JSON registry import."""

    imported_projects: int = 0
    updated_projects: int = 0
    skipped_projects: int = 0
    imported_stage_runs: int = 0


def _json_dump(value) -> dict | list:
    return value.model_dump(mode="json") if hasattr(value, "model_dump") else value


def _find_project(session: Session, project_id: int) -> ResearchProjectRecord | None:
    return session.scalar(
        select(ResearchProjectRecord).where(ResearchProjectRecord.project_id == project_id)
    )


def _apply_project_fields(record: ResearchProjectRecord, project: ResearchProject) -> None:
    record.project_id = project.project_id
    record.slug = project.slug
    record.topic = project.topic
    record.region = project.region
    record.languages = project.languages
    record.target_users = project.target_users
    record.business_context = project.business_context
    record.time_range = project.time_range
    record.access_mode = project.access_mode.value
    record.run_config = project.run_config.model_dump(mode="json")
    record.collection_eligibility = project.collection_eligibility.model_dump(mode="json")
    record.created_at = project.created_at
    record.updated_at = project.updated_at


def _ensure_retention_policy(session: Session, record: ResearchProjectRecord, project: ResearchProject) -> None:
    existing = session.scalar(
        select(RetentionPolicyRecord).where(RetentionPolicyRecord.project_id == record.id)
    )
    policy = existing or RetentionPolicyRecord(project_id=record.id)
    policy.retention_days = project.retention_policy.retention_days
    policy.delete_removed_content = project.retention_policy.delete_removed_content
    policy.targets = [target.value for target in project.retention_policy.targets]
    if existing is None:
        session.add(policy)


def _stage_exists(session: Session, record: ResearchProjectRecord, stage_run: StageRun) -> bool:
    return (
        session.scalar(
            select(ProjectStageRunRecord).where(
                ProjectStageRunRecord.project_id == record.id,
                ProjectStageRunRecord.stage == stage_run.stage,
                ProjectStageRunRecord.started_at == stage_run.started_at,
            )
        )
        is not None
    )


def _import_stage_runs(
    session: Session,
    record: ResearchProjectRecord,
    stage_runs: list[StageRun],
) -> int:
    imported = 0
    for stage_run in stage_runs:
        if _stage_exists(session, record, stage_run):
            continue
        session.add(
            ProjectStageRunRecord(
                project_id=record.id,
                stage=stage_run.stage,
                status=stage_run.status.value,
                started_at=stage_run.started_at,
                completed_at=stage_run.completed_at,
                run_limit=stage_run.run_limit,
                message=stage_run.message,
            )
        )
        imported += 1
    return imported


def import_project_registry(registry_path: Path, session: Session) -> RegistryImportResult:
    """Explicitly import a Phase 2 JSON registry into database-backed project state."""

    registry = ProjectRegistryStore(registry_path).load()
    imported_projects = 0
    updated_projects = 0
    skipped_projects = 0
    imported_stage_runs = 0

    for project in registry.projects:
        record = _find_project(session, project.project_id)
        if record is None:
            record = ResearchProjectRecord(project_id=project.project_id)
            session.add(record)
            imported_projects += 1
        else:
            updated_projects += 1

        _apply_project_fields(record, project)
        session.flush()
        _ensure_retention_policy(session, record, project)
        imported_stage_runs += _import_stage_runs(session, record, project.stage_runs)
        if not project.stage_runs and record is not None:
            skipped_projects += 0

    session.commit()
    return RegistryImportResult(
        imported_projects=imported_projects,
        updated_projects=updated_projects,
        skipped_projects=skipped_projects,
        imported_stage_runs=imported_stage_runs,
    )
