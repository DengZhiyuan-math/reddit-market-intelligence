"""Database repository helpers for structured topic plans."""

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from app.db.models import (
    ArtifactVersionRecord,
    ResearchPlanRecord,
    ResearchProjectRecord,
    SearchQueryRecord,
)
from app.topic_planning.models import TopicPlan
from app.topic_planning.prompts import TOPIC_PLANNER_PROMPT_VERSION

SCHEMA_ARTIFACT_TYPE = "schema"
PROMPT_ARTIFACT_TYPE = "prompt"
TOPIC_PLAN_SCHEMA_NAME = "topic_plan"
TOPIC_PLANNER_PROMPT_NAME = "topic_planner"


class TopicPlanningRepositoryError(ValueError):
    """Raised when topic-planning persistence cannot complete."""


def get_project_by_project_id(session: Session, project_id: int) -> ResearchProjectRecord:
    """Return a database project by its durable Phase 2 project ID."""

    project = session.scalar(
        select(ResearchProjectRecord).where(ResearchProjectRecord.project_id == project_id)
    )
    if project is None:
        raise TopicPlanningRepositoryError(f"Project not found in database: {project_id}")
    return project


def get_or_create_artifact_version(
    session: Session,
    artifact_type: str,
    name: str,
    version: str,
) -> ArtifactVersionRecord:
    """Get or create an artifact version row."""

    artifact = session.scalar(
        select(ArtifactVersionRecord).where(
            ArtifactVersionRecord.artifact_type == artifact_type,
            ArtifactVersionRecord.name == name,
            ArtifactVersionRecord.version == version,
        )
    )
    if artifact is not None:
        return artifact
    artifact = ArtifactVersionRecord(
        artifact_type=artifact_type,
        name=name,
        version=version,
        metadata_json={},
    )
    session.add(artifact)
    session.flush()
    return artifact


def create_research_plan(
    session: Session,
    project: ResearchProjectRecord,
    topic_plan: TopicPlan,
    *,
    selected: bool,
) -> ResearchPlanRecord:
    """Persist a validated topic plan."""

    schema_version = get_or_create_artifact_version(
        session,
        SCHEMA_ARTIFACT_TYPE,
        TOPIC_PLAN_SCHEMA_NAME,
        topic_plan.schema_version,
    )
    prompt_version = get_or_create_artifact_version(
        session,
        PROMPT_ARTIFACT_TYPE,
        TOPIC_PLANNER_PROMPT_NAME,
        TOPIC_PLANNER_PROMPT_VERSION,
    )
    if selected:
        clear_selected_plans(session, project.id)
    record = ResearchPlanRecord(
        project_id=project.id,
        prompt_version_id=prompt_version.id,
        schema_version_id=schema_version.id,
        plan_json=topic_plan.model_dump(mode="json"),
        selected=selected,
    )
    session.add(record)
    session.flush()
    return record


def list_research_plans(session: Session, project_id: int) -> list[ResearchPlanRecord]:
    """List research plans by durable project ID."""

    project = get_project_by_project_id(session, project_id)
    return list(
        session.scalars(
            select(ResearchPlanRecord)
            .where(ResearchPlanRecord.project_id == project.id)
            .order_by(ResearchPlanRecord.id)
        )
    )


def get_research_plan(session: Session, plan_id: int) -> ResearchPlanRecord:
    """Return a research plan by internal plan ID."""

    plan = session.get(ResearchPlanRecord, plan_id)
    if plan is None:
        raise TopicPlanningRepositoryError(f"Research plan not found: {plan_id}")
    return plan


def clear_selected_plans(session: Session, project_db_id: int) -> None:
    """Clear selected flag for all plans on one database project."""

    session.execute(
        update(ResearchPlanRecord)
        .where(ResearchPlanRecord.project_id == project_db_id)
        .values(selected=False)
    )


def select_research_plan(
    session: Session,
    *,
    project_id: int,
    plan_id: int,
) -> ResearchPlanRecord:
    """Mark exactly one plan as selected for the durable project ID."""

    project = get_project_by_project_id(session, project_id)
    plan = get_research_plan(session, plan_id)
    if plan.project_id != project.id:
        raise TopicPlanningRepositoryError(
            f"Research plan {plan_id} does not belong to project {project_id}"
        )
    clear_selected_plans(session, project.id)
    plan.selected = True
    session.flush()
    return plan


def materialize_search_queries(
    session: Session,
    *,
    project: ResearchProjectRecord,
    plan: ResearchPlanRecord,
    topic_plan: TopicPlan,
) -> list[SearchQueryRecord]:
    """Replace and create executable search query rows for a research plan."""

    session.execute(delete(SearchQueryRecord).where(SearchQueryRecord.research_plan_id == plan.id))
    records: list[SearchQueryRecord] = []
    for query in topic_plan.query_strategy:
        record = SearchQueryRecord(
            project_id=project.id,
            research_plan_id=plan.id,
            query=query.query,
            subreddit=query.subreddit,
            sort=query.sort,
            time_filter=query.time_filter,
            filters_json={"rationale": query.rationale},
            source="reddit",
            status="pending",
        )
        session.add(record)
        records.append(record)
    session.flush()
    return records
