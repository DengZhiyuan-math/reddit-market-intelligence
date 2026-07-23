from __future__ import annotations

import logging
from pathlib import Path

from app.analysis.service import run_signal_extraction
from app.config import Settings
from app.llm.service import run_llm_review
from app.reddit.collector import RedditCollector
from app.reddit.repository import RedditCollectionRepository
from app.reports.service import generate_market_report
from tests.analysis.test_service import add_accepted_item, seed_project as seed_analysis_project
from tests.llm.test_service import add_ambiguous_item, seed_project as seed_llm_project
from tests.reddit.fakes import FakeReddit, FakeSubmission, FakeSubreddit
from tests.reddit.test_collector_posts import make_session as make_reddit_session
from tests.reddit.test_collector_posts import seed_project_with_query
from tests.reports.test_service import seed_one_signal
from tests.reports.test_service import make_session as make_report_session


def _event_records(caplog) -> list[dict]:
    return [record.args for record in caplog.records if isinstance(record.args, dict)]


def test_reddit_collection_logs_project_stage_counts_and_rate_limit(caplog) -> None:
    session = make_reddit_session()
    seed_project_with_query(session)
    submission = FakeSubmission(id="abc", response_headers={"X-Ratelimit-Remaining": "42"})
    collector = RedditCollector(
        FakeReddit({"askswitzerland": FakeSubreddit([submission])}),
        RedditCollectionRepository(session),
        Settings(_env_file=None),
    )

    with caplog.at_level(logging.INFO, logger="app.reddit.collector"):
        collector.collect_posts(project_id=1, limit_per_query=5)

    events = _event_records(caplog)
    completed = next(event for event in events if event["event"] == "reddit.collection.posts.completed")
    rate_limit = next(event for event in events if event["event"] == "reddit.collection.posts.rate_limit")
    messages = "\n".join(record.getMessage() for record in caplog.records)

    assert completed["project_id"] == 1
    assert completed["stage"] == "reddit_collection"
    assert completed["item_count_out"] == 1
    assert rate_limit["x_ratelimit_remaining"] == 42.0
    assert "Can anyone recommend" not in messages


def test_llm_review_logs_model_validation_without_prompt_text(caplog) -> None:
    session = make_reddit_session()
    project = seed_llm_project(session)
    add_ambiguous_item(session, project)

    with caplog.at_level(logging.INFO, logger="app.llm.service"):
        run_llm_review(session, 1)

    events = _event_records(caplog)
    validation = next(event for event in events if event["event"] == "llm.review.validation")
    messages = "\n".join(record.getMessage() for record in caplog.records)

    assert validation["stage"] == "llm_review"
    assert validation["llm_model"] == "gpt-5.2-codex"
    assert validation["status"] == "validated"
    assert "Can anyone recommend a math tutor in Zurich?" not in messages
    assert "input_prompt" not in messages


def test_analysis_logs_model_and_output_counts_without_source_text(caplog) -> None:
    session = make_reddit_session()
    project = seed_analysis_project(session)
    add_accepted_item(session, project)

    with caplog.at_level(logging.INFO, logger="app.analysis.service"):
        run_signal_extraction(session, 1)

    events = _event_records(caplog)
    completed = next(
        event for event in events if event["event"] == "analysis.signal_extraction.completed"
    )
    messages = "\n".join(record.getMessage() for record in caplog.records)

    assert completed["stage"] == "market_signal_extraction"
    assert completed["llm_model"] == "gpt-5.2-codex"
    assert completed["item_count_out"] >= 1
    assert "Can anyone recommend a math tutor in Zurich?" not in messages


def test_report_generation_logs_artifact_path_and_counts(caplog, tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    session = make_report_session()
    seed_one_signal(session)
    output_path = Path("outputs/reports/project-1/market-report.md")

    with caplog.at_level(logging.INFO, logger="app.reports.service"):
        generate_market_report(session, 1, output_path=output_path)

    events = _event_records(caplog)
    completed = next(event for event in events if event["event"] == "report.generation.completed")

    assert completed["stage"] == "report_generation"
    assert completed["artifact_path"] == str(output_path)
    assert completed["item_count_out"] == 1
