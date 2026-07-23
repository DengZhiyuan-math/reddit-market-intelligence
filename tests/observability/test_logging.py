from __future__ import annotations

import logging

from app.observability.logging import REDACTED, build_event, log_event, redact_event


def test_build_event_keeps_stable_fields_and_drops_none() -> None:
    event = build_event(
        "collection.started",
        stage="reddit_collection",
        project_id=1,
        run_id=None,
    )

    assert event == {
        "event": "collection.started",
        "stage": "reddit_collection",
        "project_id": 1,
    }


def test_redact_event_redacts_sensitive_keys_recursively() -> None:
    event = redact_event(
        {
            "event": "settings.loaded",
            "api_key": "secret",
            "nested": {
                "client_secret": "secret",
                "Authorization": "Bearer secret",
            },
            "items": [{"password": "secret"}],
        }
    )

    assert event["api_key"] == REDACTED
    assert event["nested"]["client_secret"] == REDACTED
    assert event["nested"]["Authorization"] == REDACTED
    assert event["items"][0]["password"] == REDACTED


def test_log_event_emits_dict_like_message(caplog) -> None:
    logger = logging.getLogger("tests.observability")

    with caplog.at_level(logging.INFO, logger="tests.observability"):
        emitted = log_event(
            logger,
            "report.completed",
            stage="report_generation",
            project_id=1,
            artifact_path="outputs/reports/project-1/market-report.md",
            api_key="secret",
    )

    assert emitted["api_key"] == REDACTED
    assert caplog.records[0].args["event"] == "report.completed"
    assert caplog.records[0].args["artifact_path"].endswith("market-report.md")
