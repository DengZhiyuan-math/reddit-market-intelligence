"""Tests for topic plan persistence and query materialization."""

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.db.base import Base
from app.db.models import (
    ArtifactVersionRecord,
    ResearchPlanRecord,
    ResearchProjectRecord,
    SearchQueryRecord,
)
import app.db.models  # noqa: F401
from app.topic_planning.service import (
    generate_and_persist_topic_plan,
    generate_topic_plan_for_project,
    select_topic_plan,
)


def make_session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def seed_project(session: Session, project_id: int = 1) -> ResearchProjectRecord:
    project = ResearchProjectRecord(
        project_id=project_id,
        slug=f"project-{project_id}",
        topic="Swiss tutoring market in Zurich",
        region="Switzerland, Zurich",
        languages=["en", "de"],
        target_users=["parents", "students", "expat families"],
        business_context="AI + human tutor platform",
        time_range="last 12 months",
        access_mode="commercial-approved",
        run_config={"limit": 100, "dry_run": False},
        collection_eligibility={"allowed": True},
    )
    session.add(project)
    session.commit()
    return project


def test_generate_topic_plan_persists_research_plan() -> None:
    session = make_session()
    seed_project(session)

    result = generate_and_persist_topic_plan(session, 1)
    session.commit()

    plan = session.get(ResearchPlanRecord, result.record.id)
    artifacts = session.scalars(select(ArtifactVersionRecord)).all()
    assert plan is not None
    assert plan.selected is True
    assert plan.plan_json["core_topic"].startswith("Swiss tutoring market")
    assert plan.prompt_version_id is not None
    assert plan.schema_version_id is not None
    assert {artifact.artifact_type for artifact in artifacts} == {"prompt", "schema"}


def test_select_topic_plan_clears_previous_selection() -> None:
    session = make_session()
    seed_project(session)
    first = generate_and_persist_topic_plan(session, 1, selected=True)
    second_plan = generate_topic_plan_for_project(session, 1)
    second = generate_and_persist_topic_plan(session, 1, selected=False)

    selected = select_topic_plan(session, 1, second.record.id)
    session.commit()

    plans = session.scalars(select(ResearchPlanRecord).order_by(ResearchPlanRecord.id)).all()
    assert second_plan.core_topic == second.topic_plan.core_topic
    assert selected.record.id == second.record.id
    assert [(plan.id, plan.selected) for plan in plans] == [
        (first.record.id, False),
        (second.record.id, True),
    ]


def test_materializes_search_queries_for_phase_5() -> None:
    session = make_session()
    seed_project(session)

    result = generate_and_persist_topic_plan(session, 1)
    session.commit()

    queries = session.scalars(select(SearchQueryRecord)).all()
    assert result.search_query_count == len(result.topic_plan.query_strategy)
    assert len(queries) == result.search_query_count
    assert {query.research_plan_id for query in queries} == {result.record.id}
    assert all(query.status == "pending" for query in queries)


def test_unknown_project_is_readable_service_error() -> None:
    session = make_session()

    try:
        generate_topic_plan_for_project(session, 999)
    except ValueError as exc:
        assert "Project not found" in str(exc)
    else:
        raise AssertionError("Expected missing project error")
