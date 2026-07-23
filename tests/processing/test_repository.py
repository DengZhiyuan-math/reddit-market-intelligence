from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.db.base import Base
from app.db.models import (
    ContentItemRecord,
    PipelineRunRecord,
    ProjectRedditCommentRecord,
    ProjectRedditPostRecord,
    RedditCommentRawRecord,
    RedditPostRawRecord,
    ResearchPlanRecord,
    ResearchProjectRecord,
    SearchQueryRecord,
)
import app.db.models  # noqa: F401
from app.processing.models import DELETED_CONTENT, REJECTED
from app.processing.repository import ProcessingRepository


def make_session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def seed_project(session: Session) -> tuple[ResearchProjectRecord, SearchQueryRecord]:
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
    plan = ResearchPlanRecord(
        project_id=project.id,
        plan_json={"core_topic": "Swiss tutoring market"},
        selected=True,
    )
    session.add(plan)
    session.flush()
    query = SearchQueryRecord(
        project_id=project.id,
        research_plan_id=plan.id,
        query="math tutor Zurich",
        subreddit="askswitzerland",
        sort="new",
        time_filter="year",
        filters_json={"rationale": "test"},
        source="reddit",
        status="completed",
    )
    session.add(query)
    session.commit()
    return project, query


def seed_raw_post(session: Session, project: ResearchProjectRecord, query: SearchQueryRecord):
    raw_post = RedditPostRawRecord(
        reddit_post_id="post1",
        reddit_fullname="t3_post1",
        subreddit="askswitzerland",
        title="Looking for a math tutor",
        body="My child needs school help in Zurich with algebra.",
        permalink="/r/askswitzerland/comments/post1",
        raw_json={},
    )
    session.add(raw_post)
    session.flush()
    project_post = ProjectRedditPostRecord(
        project_id=project.id,
        search_query_id=query.id,
        reddit_post_raw_id=raw_post.id,
        subreddit=query.subreddit,
        query=query.query,
        sort=query.sort,
        time_filter=query.time_filter,
        filters_json=query.filters_json,
    )
    session.add(project_post)
    session.commit()
    return raw_post, project_post


def seed_raw_comment(session: Session, project: ResearchProjectRecord, query: SearchQueryRecord):
    raw_comment = RedditCommentRawRecord(
        reddit_comment_id="comment1",
        reddit_fullname="t1_comment1",
        reddit_post_id="post1",
        body="I recommend asking the school for tutor recommendations.",
        raw_json={},
    )
    session.add(raw_comment)
    session.flush()
    project_comment = ProjectRedditCommentRecord(
        project_id=project.id,
        search_query_id=query.id,
        reddit_comment_raw_id=raw_comment.id,
        subreddit=query.subreddit,
        query=query.query,
        sort=query.sort,
        time_filter=query.time_filter,
        filters_json=query.filters_json,
    )
    session.add(project_comment)
    session.commit()
    return raw_comment, project_comment


def test_repository_loads_project_and_selected_plan() -> None:
    session = make_session()
    project, _query = seed_project(session)
    repository = ProcessingRepository(session)

    assert repository.get_project_by_project_id(1) == project
    assert repository.get_selected_research_plan(project.id) is not None


def test_repository_lists_raw_project_posts_and_comments() -> None:
    session = make_session()
    project, query = seed_project(session)
    raw_post, project_post = seed_raw_post(session, project, query)
    raw_comment, project_comment = seed_raw_comment(session, project, query)
    repository = ProcessingRepository(session)

    posts = repository.list_raw_project_posts(project.id)
    comments = repository.list_raw_project_comments(project.id)

    assert posts[0].raw_post == raw_post
    assert posts[0].project_post == project_post
    assert comments[0].raw_comment == raw_comment
    assert comments[0].project_comment == project_comment


def test_start_filtering_run_creates_running_pipeline_run() -> None:
    session = make_session()
    project, _query = seed_project(session)
    repository = ProcessingRepository(session)

    run = repository.start_filtering_run(project.id, {"limit": 10})

    assert run.stage == "filtering"
    assert run.status == "running"
    assert session.scalar(select(PipelineRunRecord)) == run


def test_materialization_is_idempotent_for_posts_and_comments() -> None:
    session = make_session()
    project, query = seed_project(session)
    seed_raw_post(session, project, query)
    seed_raw_comment(session, project, query)
    repository = ProcessingRepository(session)

    first = repository.materialize_raw_content_items(project=project)
    second = repository.materialize_raw_content_items(project=project)

    assert [inserted for _item, inserted in first] == [True, True]
    assert [inserted for _item, inserted in second] == [False, False]
    assert len(session.scalars(select(ContentItemRecord)).all()) == 2


def test_materialized_post_combines_title_and_body() -> None:
    session = make_session()
    project, query = seed_project(session)
    seed_raw_post(session, project, query)
    repository = ProcessingRepository(session)

    [(item, inserted)] = repository.materialize_raw_content_items(project=project)

    assert inserted is True
    assert item.source_type == "reddit_post"
    assert item.source_id == "post1"
    assert "Looking for a math tutor" in item.text
    assert "algebra" in item.cleaned_text
    assert item.language == "en"
    assert item.source_mode == "reddit_api"


def test_materialized_fallback_post_preserves_source_mode() -> None:
    session = make_session()
    project, query = seed_project(session)
    raw_post, _project_post = seed_raw_post(session, project, query)
    raw_post.raw_json = {"acquisition_method": "web_static"}
    session.commit()
    repository = ProcessingRepository(session)

    [(item, _inserted)] = repository.materialize_raw_content_items(project=project)

    assert item.source_mode == "web_static"


def test_materialized_comment_uses_body_text() -> None:
    session = make_session()
    project, query = seed_project(session)
    seed_raw_comment(session, project, query)
    repository = ProcessingRepository(session)

    [(item, inserted)] = repository.materialize_raw_content_items(project=project)

    assert inserted is True
    assert item.source_type == "reddit_comment"
    assert item.source_id == "comment1"
    assert "recommend" in item.cleaned_text


def test_deleted_raw_content_is_rejected_with_explanation() -> None:
    session = make_session()
    project, query = seed_project(session)
    raw_post = RedditPostRawRecord(
        reddit_post_id="post_deleted",
        title="[deleted]",
        body=None,
        raw_json={},
    )
    session.add(raw_post)
    session.flush()
    session.add(
        ProjectRedditPostRecord(
            project_id=project.id,
            search_query_id=query.id,
            reddit_post_raw_id=raw_post.id,
        )
    )
    session.commit()
    repository = ProcessingRepository(session)

    [(item, _inserted)] = repository.materialize_raw_content_items(project=project)

    assert item.final_status == REJECTED
    assert item.llm_review_required is False
    assert item.reason_codes[0]["code"] == DELETED_CONTENT
    assert item.reason_codes[0]["explanation"]
