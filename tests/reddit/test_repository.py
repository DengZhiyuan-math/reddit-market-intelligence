from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.base import Base
from app.db.models import ResearchProjectRecord
import app.db.models  # noqa: F401
from app.reddit.models import CollectionRunSummary
from app.reddit.rate_limiter import parse_rate_limit_headers
from app.reddit.repository import RedditCollectionRepository


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
        target_users=["parents"],
        business_context="AI + human tutor platform",
        time_range="last 12 months",
        access_mode="commercial-approved",
        run_config={"limit": 100},
        collection_eligibility={"allowed": True},
    )
    session.add(project)
    session.commit()
    return project


def test_start_collection_run_creates_running_pipeline_run() -> None:
    session = make_session()
    project = seed_project(session)
    repository = RedditCollectionRepository(session)

    run = repository.start_collection_run(project.id, {"limit_per_query": 10})
    session.commit()

    assert run.stage == "reddit_collection"
    assert run.status == "running"
    assert run.project_id == project.id
    assert run.run_config == {"limit_per_query": 10}
    assert run.started_at is not None


def test_request_log_persists_context_timing_and_rate_limit_fields() -> None:
    session = make_session()
    project = seed_project(session)
    repository = RedditCollectionRepository(session)
    run = repository.start_collection_run(project.id, {"limit_per_query": 10})

    request = repository.create_request_log(
        project_db_id=project.id,
        run_id=run.id,
        endpoint="/r/askswitzerland/search",
        action="search_subreddit",
        search_query_id=123,
        subreddit="askswitzerland",
        query="math tutor Zurich",
        request_params={"sort": "relevance", "limit": 10},
    )
    finished = repository.finish_request_log(
        request.id,
        status_code=200,
        elapsed_ms=55,
        response_headers={
            "X-Ratelimit-Used": "1",
            "X-Ratelimit-Remaining": "99",
            "X-Ratelimit-Reset": "60",
        },
    )
    session.commit()

    assert finished.endpoint == "/r/askswitzerland/search"
    assert finished.action == "search_subreddit"
    assert finished.search_query_id == 123
    assert finished.subreddit == "askswitzerland"
    assert finished.query == "math tutor Zurich"
    assert finished.request_params == {"sort": "relevance", "limit": 10}
    assert finished.status_code == 200
    assert finished.elapsed_ms == 55
    assert finished.rate_limit_used == 1.0
    assert finished.rate_limit_remaining == 99.0
    assert finished.rate_limit_reset == 60.0
    assert finished.completed_at is not None


def test_finish_request_log_accepts_explicit_rate_limit_snapshot() -> None:
    session = make_session()
    project = seed_project(session)
    repository = RedditCollectionRepository(session)
    request = repository.create_request_log(
        project_db_id=project.id,
        run_id=None,
        endpoint="/api/v1/me",
        action="validate_credentials",
    )

    finished = repository.finish_request_log(
        request.id,
        status_code=401,
        error="Unauthorized",
        elapsed_ms=20,
        rate_limit=parse_rate_limit_headers({"X-Ratelimit-Remaining": "3"}),
    )

    assert finished.error == "Unauthorized"
    assert finished.rate_limit_remaining == 3.0


def test_complete_collection_run_persists_all_summary_keys() -> None:
    session = make_session()
    project = seed_project(session)
    repository = RedditCollectionRepository(session)
    run = repository.start_collection_run(project.id, {"limit_per_query": 10})
    summary = CollectionRunSummary(
        requested_queries=2,
        processed_queries=1,
        stored_posts=3,
        stored_comments=4,
        duplicate_posts_skipped=5,
        duplicate_comments_skipped=6,
        request_failures=7,
        permanent_failures=8,
        rate_limit_stops=9,
        elapsed_ms=10,
    )

    completed = repository.complete_collection_run(run.id, "completed", summary)
    session.commit()

    assert completed.status == "completed"
    assert completed.completed_at is not None
    assert completed.summary == {
        "requested_queries": 2,
        "processed_queries": 1,
        "stored_posts": 3,
        "stored_comments": 4,
        "duplicate_posts_skipped": 5,
        "duplicate_comments_skipped": 6,
        "request_failures": 7,
        "permanent_failures": 8,
        "rate_limit_stops": 9,
        "elapsed_ms": 10,
    }
    assert completed.summary["permanent_failures"] != completed.summary["duplicate_posts_skipped"]
