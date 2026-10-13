"""Bounded Reddit public JSON using mocked network responses and SQLite."""

from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import pytest
from sqlalchemy import select

from app.db.models import PipelineRunRecord
from app.llm.transport import RunBudget
from app.topic_planning.models import PlannedSearchQuery
from tests.reddit.test_export_import import make_session, listing, post


def strategy():
    return [
        PlannedSearchQuery(
            query="math & tutor",
            subreddit="zurich",
            sort="new",
            time_filter="month",
            rationale="Synthetic probe",
        )
    ]


def response(payload, status=200, content_type="application/json"):
    return SimpleNamespace(
        status_code=status, headers={"Content-Type": content_type}, json=lambda: payload
    )


def test_public_json_reuses_importer_and_returns_only_new_project_scope(monkeypatch):
    import requests
    from app.reddit.public_json import acquire_public_json

    calls = []

    def get(url, **kwargs):
        calls.append(url)
        assert kwargs["allow_redirects"] is False
        assert "Cookie" not in kwargs["headers"]
        if "search.json" in url:
            assert parse_qs(urlsplit(url).query)["q"] == ["math & tutor"]
            return response(listing([post()]))
        return response(
            [
                listing([post()]),
                listing(
                    [
                        {
                            "kind": "t1",
                            "data": {
                                "id": "c1",
                                "link_id": "t3_abc",
                                "parent_id": "t3_abc",
                                "body": "Can anyone recommend a math tutor in Zurich?",
                            },
                        },
                        {
                            "kind": "more",
                            "data": {"count": 5, "parent_id": "t3_abc", "children": ["c2"]},
                        },
                    ]
                ),
            ]
        )

    monkeypatch.setattr(requests, "get", get)
    session = make_session()
    result = acquire_public_json(
        session,
        project_id=1,
        queries=strategy(),
        budget=RunBudget(max_items=3, max_requests=4),
        max_queries=1,
    )
    assert result.status == "completed"
    assert result.scope == {"reddit_post": ["abc"], "reddit_comment": ["c1"]}
    repeat = acquire_public_json(
        session,
        project_id=1,
        queries=strategy(),
        budget=RunBudget(max_items=3, max_requests=4),
        max_queries=1,
    )
    assert repeat.status == "no_evidence"
    assert repeat.scope == {"reddit_post": [], "reddit_comment": []}
    run = session.get(PipelineRunRecord, repeat.run_id)
    assert run.summary["repeat_ids"] == {"reddit_post": ["abc"], "reddit_comment": ["c1"]}
    assert len(calls) == 4


@pytest.mark.parametrize("failure", ["403", "429", "html", "schema", "budget"])
def test_public_source_partial_failure_stops_durably(monkeypatch, failure):
    import requests
    from app.reddit.public_json import acquire_public_json

    calls = []

    def get(url, **kwargs):
        calls.append(url)
        if len(calls) == 1:
            return response(listing([post()]))
        if failure in {"403", "429"}:
            return response({}, int(failure))
        return response(
            {"error": "bad"}, content_type="text/html" if failure == "html" else "application/json"
        )

    monkeypatch.setattr(requests, "get", get)
    session = make_session()
    result = acquire_public_json(
        session,
        project_id=1,
        queries=strategy(),
        budget=RunBudget(max_items=3, max_requests=1 if failure == "budget" else 4),
        max_queries=1,
    )
    assert result.status in {"failed", "blocked"}
    assert len(calls) == (1 if failure == "budget" else 2)
    session.rollback()
    assert session.get(PipelineRunRecord, result.run_id).status == result.status


def test_public_json_cross_project_reuses_global_rows_as_new_associations(monkeypatch):
    import requests
    from app.db.models import ResearchProjectRecord
    from app.reddit.public_json import acquire_public_json

    monkeypatch.setattr(
        requests,
        "get",
        lambda url, **kwargs: response(
            listing([post()]) if "search.json" in url else [listing([post()]), listing([])]
        ),
    )
    session = make_session()
    session.add(
        ResearchProjectRecord(project_id=2, slug="second", topic="Tutoring", access_mode="personal")
    )
    session.commit()
    acquire_public_json(
        session, project_id=1, queries=strategy(), budget=RunBudget(max_items=3), max_queries=1
    )
    second = acquire_public_json(
        session, project_id=2, queries=strategy(), budget=RunBudget(max_items=3), max_queries=1
    )
    assert second.status == "completed"
    assert second.scope["reddit_post"] == ["abc"]


def test_oauth_route_is_query_item_request_bounded_and_audits_same_project_repeats():
    from app.config import Settings
    from app.db.models import SearchQueryRecord
    from app.reddit.service import run_reddit_collection
    from tests.reddit.test_collector_posts import make_session, seed_project_with_query
    from tests.reddit.fakes import FakeReddit, FakeSubmission, FakeSubreddit

    session = make_session()
    project, query = seed_project_with_query(session)
    session.add(
        SearchQueryRecord(
            project_id=project.id, query="unselected", subreddit="ignored", source="reddit"
        )
    )
    session.commit()
    client = FakeReddit(
        {"askswitzerland": FakeSubreddit([FakeSubmission(id="abc"), FakeSubmission(id="def")])}
    )
    settings = Settings(
        _env_file=None,
        reddit_client_id="synthetic-id",
        reddit_client_secret="synthetic-secret",
        reddit_user_agent="reddit-market-intel/0.1 contact@example.test",
    )
    budget = RunBudget(max_items=1, max_requests=1)
    run_reddit_collection(
        session,
        1,
        10,
        0,
        False,
        settings=settings,
        reddit_client=client,
        selected_query_ids=[query.id],
        budget=budget,
        strict_stop=True,
    )
    first = session.scalar(select(PipelineRunRecord).order_by(PipelineRunRecord.id.desc()))
    assert first.summary["scope"] == {"reddit_post": ["abc"], "reddit_comment": []}
    assert budget.requests == 1
    run_reddit_collection(
        session,
        1,
        10,
        0,
        False,
        settings=settings,
        reddit_client=client,
        selected_query_ids=[query.id],
        budget=RunBudget(max_items=1),
        strict_stop=True,
    )
    repeated = session.scalar(select(PipelineRunRecord).order_by(PipelineRunRecord.id.desc()))
    assert repeated.status == "no_evidence"
    assert repeated.summary["repeat_ids"]["reddit_post"] == ["abc"]
