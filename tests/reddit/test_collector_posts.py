from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.config import Settings
from app.db.base import Base
from app.db.models import (
    ProjectRedditPostRecord,
    RedditPostRawRecord,
    ResearchPlanRecord,
    ResearchProjectRecord,
    SearchQueryRecord,
)
import app.db.models  # noqa: F401
from app.reddit.collector import RedditCollector
from app.reddit.models import RedditPostSnapshot
from app.reddit.repository import RedditCollectionRepository
from tests.reddit.fakes import FakeReddit, FakeSubmission, FakeSubreddit


class PermanentSearchError(RuntimeError):
    pass


def make_session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def seed_project_with_query(session: Session) -> tuple[ResearchProjectRecord, SearchQueryRecord]:
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
    plan = ResearchPlanRecord(project_id=project.id, plan_json={}, selected=True)
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
        status="pending",
    )
    session.add(query)
    session.commit()
    return project, query


def test_repository_upserts_raw_posts_and_links_project_provenance() -> None:
    session = make_session()
    project, query = seed_project_with_query(session)
    repository = RedditCollectionRepository(session)
    snapshot = RedditPostSnapshot.from_submission(FakeSubmission(id="abc"))

    raw_post, inserted = repository.upsert_raw_post(snapshot)
    same_post, inserted_again = repository.upsert_raw_post(snapshot)
    link, linked = repository.link_project_post(
        project_db_id=project.id,
        run_id=None,
        search_query=query,
        request_id=None,
        raw_post=raw_post,
    )
    same_link, linked_again = repository.link_project_post(
        project_db_id=project.id,
        run_id=None,
        search_query=query,
        request_id=None,
        raw_post=raw_post,
    )

    assert inserted is True
    assert inserted_again is False
    assert raw_post.id == same_post.id
    assert linked is True
    assert linked_again is False
    assert link.id == same_link.id
    assert session.scalars(select(RedditPostRawRecord)).all() == [raw_post]
    assert session.scalars(select(ProjectRedditPostRecord)).all() == [link]


def test_list_pending_search_queries_and_status_update() -> None:
    session = make_session()
    project, query = seed_project_with_query(session)
    repository = RedditCollectionRepository(session)

    queries = repository.list_pending_search_queries(project.id, limit=1)
    updated = repository.mark_search_query_status(query.id, "completed")

    assert queries == [query]
    assert updated.status == "completed"
    assert repository.list_pending_search_queries(project.id) == []


def test_post_snapshot_handles_missing_optional_submission_fields() -> None:
    class MinimalSubmission:
        id = "minimal"

    snapshot = RedditPostSnapshot.from_submission(MinimalSubmission())

    assert snapshot.reddit_post_id == "minimal"
    assert snapshot.reddit_fullname is None
    assert snapshot.title is None
    assert snapshot.raw_json["id"] == "minimal"


def test_collect_posts_executes_search_and_stores_posts() -> None:
    session = make_session()
    _project, query = seed_project_with_query(session)
    subreddit = FakeSubreddit([FakeSubmission(id="abc"), FakeSubmission(id="def")])
    collector = RedditCollector(
        FakeReddit({"askswitzerland": subreddit}),
        RedditCollectionRepository(session),
        Settings(_env_file=None),
    )

    summary = collector.collect_posts(project_id=1, limit_per_query=5)
    session.commit()

    assert subreddit.search_calls == [
        {
            "query": "math tutor Zurich",
            "sort": "new",
            "time_filter": "year",
            "limit": 5,
        }
    ]
    assert summary.requested_queries == 1
    assert summary.processed_queries == 1
    assert summary.stored_posts == 2
    assert summary.duplicate_posts_skipped == 0
    assert query.status == "completed"
    assert len(session.scalars(select(RedditPostRawRecord)).all()) == 2
    assert len(session.scalars(select(ProjectRedditPostRecord)).all()) == 2


def test_collect_posts_counts_duplicates() -> None:
    session = make_session()
    seed_project_with_query(session)
    duplicate = FakeSubmission(id="abc")
    collector = RedditCollector(
        FakeReddit({"askswitzerland": FakeSubreddit([duplicate, duplicate])}),
        RedditCollectionRepository(session),
        Settings(_env_file=None),
    )

    summary = collector.collect_posts(project_id=1, limit_per_query=5)

    assert summary.stored_posts == 1
    assert summary.duplicate_posts_skipped == 1


def test_collect_posts_records_failed_searches() -> None:
    session = make_session()
    _project, query = seed_project_with_query(session)
    collector = RedditCollector(
        FakeReddit({"askswitzerland": FakeSubreddit(PermanentSearchError("bad search"))}),
        RedditCollectionRepository(session),
        Settings(_env_file=None),
    )

    summary = collector.collect_posts(project_id=1, limit_per_query=5)

    assert summary.request_failures == 1
    assert summary.permanent_failures == 1
    assert query.status == "failed"


def test_collect_posts_stops_when_rate_limit_remaining_is_low() -> None:
    session = make_session()
    seed_project_with_query(session)
    submission = FakeSubmission(id="abc", response_headers={"X-Ratelimit-Remaining": "1"})
    collector = RedditCollector(
        FakeReddit({"askswitzerland": FakeSubreddit([submission])}),
        RedditCollectionRepository(session),
        Settings(_env_file=None, reddit_min_remaining=5),
    )

    summary = collector.collect_posts(project_id=1, limit_per_query=5)

    assert summary.rate_limit_stops == 1
