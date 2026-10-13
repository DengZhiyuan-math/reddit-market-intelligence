"""Service layer for generating and persisting topic plans."""

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.db.models import ResearchPlanRecord, LlmCallRecord
from app.config import Settings
from app.llm.providers import topic_provider
from app.topic_planning.models import TopicPlan
from app.topic_planning.planner import (
    TopicPlannerProvider,
    TopicPlanningContext,
)
from app.topic_planning.repository import (
    TopicPlanningRepositoryError,
    create_research_plan,
    get_project_by_project_id,
    get_research_plan,
    list_research_plans,
    materialize_search_queries,
    select_research_plan as repository_select_research_plan,
)


class TopicPlanningServiceError(ValueError):
    """Raised when topic-planning service operations fail."""


@dataclass(frozen=True)
class PersistedTopicPlan:
    """Generated or loaded topic plan plus database metadata."""

    record: ResearchPlanRecord
    topic_plan: TopicPlan
    search_query_count: int = 0


def _context_from_project(project) -> TopicPlanningContext:
    return TopicPlanningContext(
        topic=project.topic,
        region=project.region,
        languages=list(project.languages or []),
        target_users=list(project.target_users or []),
        business_context=project.business_context,
        time_range=project.time_range,
    )


def _topic_plan_from_record(record: ResearchPlanRecord) -> TopicPlan:
    return TopicPlan.model_validate(record.plan_json)


def generate_topic_plan_for_project(
    session: Session,
    project_id: int,
    *,
    provider: TopicPlannerProvider | None = None,
    settings: Settings | None = None,
) -> TopicPlan:
    """Generate a topic plan for a database project without persisting it."""

    project = get_project_by_project_id(session, project_id)
    planner = provider or topic_provider(settings or Settings())
    return planner.generate(_context_from_project(project))


def persist_topic_plan_for_project(
    session: Session,
    project_id: int,
    topic_plan: TopicPlan,
    *,
    selected: bool = True,
    materialize_queries: bool = True,
) -> PersistedTopicPlan:
    """Persist a topic plan and optionally materialize search query rows."""

    project = get_project_by_project_id(session, project_id)
    if selected:
        record = create_research_plan(session, project, topic_plan, selected=True)
    else:
        existing_selected = any(plan.selected for plan in list_research_plans(session, project_id))
        record = create_research_plan(
            session,
            project,
            topic_plan,
            selected=not existing_selected,
        )
    search_queries = []
    if materialize_queries:
        search_queries = materialize_search_queries(
            session,
            project=project,
            plan=record,
            topic_plan=topic_plan,
        )
    session.flush()
    return PersistedTopicPlan(
        record=record, topic_plan=topic_plan, search_query_count=len(search_queries)
    )


def generate_and_persist_topic_plan(
    session: Session,
    project_id: int,
    *,
    provider: TopicPlannerProvider | None = None,
    settings: Settings | None = None,
    selected: bool = True,
) -> PersistedTopicPlan:
    """Generate and persist a topic plan for a project."""

    planner = provider or topic_provider(settings or Settings())
    topic_plan = generate_topic_plan_for_project(session, project_id, provider=planner)
    persisted = persist_topic_plan_for_project(session, project_id, topic_plan, selected=selected)
    result = getattr(planner, "last_result", None)
    if result:
        project = get_project_by_project_id(session, project_id)
        session.add(
            LlmCallRecord(
                project_id=project.id,
                call_type="topic_planning",
                provider=result.provider,
                model_name=result.model,
                input_json={"topic": project.topic},
                output_json=result.output,
                raw_response_json=result.audit(),
                validation_status="validated",
                input_tokens=result.input_tokens,
                output_tokens=result.output_tokens,
            )
        )
        session.flush()
    return persisted


def list_topic_plans(session: Session, project_id: int) -> list[PersistedTopicPlan]:
    """List persisted topic plans for a project."""

    return [
        PersistedTopicPlan(record=record, topic_plan=_topic_plan_from_record(record))
        for record in list_research_plans(session, project_id)
    ]


def get_topic_plan(session: Session, plan_id: int) -> PersistedTopicPlan:
    """Get a persisted topic plan by internal plan ID."""

    record = get_research_plan(session, plan_id)
    return PersistedTopicPlan(record=record, topic_plan=_topic_plan_from_record(record))


def select_topic_plan(session: Session, project_id: int, plan_id: int) -> PersistedTopicPlan:
    """Select a persisted topic plan for downstream pipeline stages."""

    try:
        record = repository_select_research_plan(session, project_id=project_id, plan_id=plan_id)
    except TopicPlanningRepositoryError as exc:
        raise TopicPlanningServiceError(str(exc)) from exc
    return PersistedTopicPlan(record=record, topic_plan=_topic_plan_from_record(record))
