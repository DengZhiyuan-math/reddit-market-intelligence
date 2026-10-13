"""Real-stage orchestration with mocked external transports and synthetic SQLite."""

import json
from pathlib import Path
import subprocess
from types import SimpleNamespace
import pytest

from sqlalchemy import select

from app.config import Settings
from app.db.models import MarketSignalRecord, PipelineRunRecord
from app.reddit.export_import import import_reddit_export
from tests.reddit.test_export_import import make_session, listing, post, write_json
from tests.reddit.test_export_import_pipeline import analyze, QUOTE
from tests.analysis.test_service import two_signal_provider
from app.topic_planning.planner import DeterministicTopicPlanner, TopicPlanningContext


def test_builtin_pipeline_without_capture_waits_without_model_or_browser_calls(
    monkeypatch, tmp_path
):
    from app.pipeline import run_pipeline

    session = make_session()
    from app.db.models import ResearchPlanRecord

    plan = DeterministicTopicPlanner().generate(TopicPlanningContext(topic="Zurich tutoring"))
    session.add(
        ResearchPlanRecord(project_id=1, plan_json=plan.model_dump(mode="json"), selected=True)
    )
    session.commit()

    def forbidden(*args, **kwargs):
        raise AssertionError("No subprocess is allowed before a browser capture")

    monkeypatch.setattr(subprocess, "run", forbidden)
    outcome = run_pipeline(session, 1, source="builtin-browser-dom", output_dir=tmp_path)
    assert outcome["status"] == "awaiting_browser"
    assert outcome["model_calls"] == 0
    task_path = Path(outcome["artifacts"]["browser_task"])
    task = json.loads(task_path.read_text())
    assert task["project_id"] == 1
    assert task["max_items"] == 10
    assert (
        outcome["next_command"]
        == f"reddit-market-intel pipeline resume --run-id {outcome['run_id']} --browser-capture-path {task_path.parent / 'browser-capture.json'}"
    )
    assert json.loads(Path(outcome["summary_path"]).read_text())["status"] == "awaiting_browser"


def test_builtin_capture_runs_analysis_on_a_bounded_subset(monkeypatch, tmp_path):
    from app.pipeline import run_pipeline
    from app.db.models import ResearchPlanRecord
    from app.reddit.builtin_browser import prepare_browser_task
    from tests.reddit.test_browser_dom import page

    session = make_session()
    plan = DeterministicTopicPlanner().generate(TopicPlanningContext(topic="Zurich tutoring"))
    selected = ResearchPlanRecord(
        project_id=1, plan_json=plan.model_dump(mode="json"), selected=True
    )
    session.add(selected)
    session.commit()
    task = prepare_browser_task(
        project_id=1,
        plan_id=selected.id,
        queries=plan.query_strategy,
        since="2025-10-12T00:00:00Z",
        until="2026-10-12T18:00:00Z",
    )
    search = page("search.html", task["search_urls"][0])
    discussion = page("discussion.html", "https://www.reddit.com/r/zurich/comments/abc/tutor/")
    discussion["html"] = discussion["html"].replace("2021-10-31", "2026-10-01")
    search["captured_at"] = discussion["captured_at"] = "2026-10-12T18:01:00Z"
    path = tmp_path / "capture.json"
    path.write_text(json.dumps(dict(task=task, searches=[search], discussions=[discussion])))
    mock_models(monkeypatch)
    result = run_pipeline(
        session,
        1,
        source="builtin-browser-dom",
        browser_capture_path=path,
        max_analysis_items=1,
        output_dir=tmp_path / "results",
        settings=Settings(_env_file=None),
    )
    assert result["status"] == "completed", result
    assert result["source_scope"] == {"reddit_post": ["abc"], "reddit_comment": ["c1"]}
    assert result["analysis_scope"] == {"reddit_post": ["abc"], "reddit_comment": []}
    assert result["acquisition"]["records"] == 2
    assert result["model_calls"] == 3
    assert Path(result["artifacts"]["report"]).is_file()


def mock_models(monkeypatch, *, bad_report=False):
    def fake(args, **kwargs):
        schema = json.loads(Path(args[args.index("--output-schema") + 1]).read_text())
        title = schema["title"]
        if title == "TopicPlan":
            output = (
                DeterministicTopicPlanner()
                .generate(TopicPlanningContext(topic="Zurich tutoring"))
                .model_dump(mode="json")
            )
        elif title == "AmbiguityReviewOutput":
            output = {
                "is_relevant": True,
                "relevance_score": 0.9,
                "quality_score": 0.9,
                "intent_label": "LOOKING_FOR_TUTOR",
                "persona_label": "PARENT",
                "pain_points": ["MATH_DIFFICULTY"],
                "buying_signal": True,
                "urgency_level": "medium",
                "reason": "Synthetic transport response",
                "confidence": 0.9,
            }
        elif title == "SignalExtractionOutput":
            output = two_signal_provider().fixture_output
        else:
            payload = json.loads(kwargs["input"].split("\n", 1)[1])
            identifiers = [item["signal_id"] for item in payload["evidence"]]
            output = {
                "sections": [
                    {
                        "section": "executive_summary",
                        "body": "Observed parents seek local tutoring help.",
                        "evidence_ids": [999] if bad_report else identifiers,
                        "quotes": [{"signal_id": identifiers[0], "quote": QUOTE}],
                    }
                ]
            }
        Path(args[args.index("-o") + 1]).write_text(json.dumps(output))
        return SimpleNamespace(
            returncode=0,
            stdout='{"type":"turn.completed","usage":{"input_tokens":10,"output_tokens":5}}',
            stderr="",
        )

    monkeypatch.setattr(subprocess, "run", fake)


def imported_session(tmp_path):
    session = make_session()
    source = post()
    source["data"]["title"] = None
    source["data"]["selftext"] = QUOTE
    import_reddit_export(
        session,
        project_id=1,
        input_path=write_json(tmp_path, listing([source])),
        acquisition_method="manual_web",
    )
    session.commit()
    return session


def test_resume_reuses_completed_stages_and_keeps_total_call_budget(monkeypatch, tmp_path):
    from app.pipeline import run_pipeline, resume_pipeline

    session = imported_session(tmp_path)
    mock_models(monkeypatch, bad_report=True)
    failed = run_pipeline(
        session,
        1,
        source="imported",
        output_dir=tmp_path / "results",
        max_model_calls=5,
        settings=Settings(_env_file=None),
    )
    assert failed["status"] == "failed"
    assert failed["model_calls"] == 4
    mock_models(monkeypatch)
    transport = subprocess.run
    schemas = []

    def record(args, **kwargs):
        schemas.append(
            json.loads(Path(args[args.index("--output-schema") + 1]).read_text())["title"]
        )
        return transport(args, **kwargs)

    monkeypatch.setattr(subprocess, "run", record)
    resumed = resume_pipeline(session, failed["run_id"], settings=Settings(_env_file=None))
    assert resumed["status"] == "completed", resumed
    assert schemas == ["ReportNarrative"]
    assert resumed["model_calls"] == 5
    assert resumed["new_model_calls"] == 1
    assert resumed["resumed_from"] == failed["run_id"]
    assert resumed["signal_ids"] == failed["signal_ids"]
    assert session.get(PipelineRunRecord, failed["run_id"]).status == "failed"
    repeated = resume_pipeline(session, failed["run_id"], settings=Settings(_env_file=None))
    assert repeated["run_id"] == resumed["run_id"]
    assert schemas == ["ReportNarrative"]


def test_resume_refuses_changed_source_before_a_model_call(monkeypatch, tmp_path):
    from app.pipeline import run_pipeline, resume_pipeline
    from app.db.models import ContentItemRecord

    session = imported_session(tmp_path)
    mock_models(monkeypatch, bad_report=True)
    failed = run_pipeline(
        session,
        1,
        source="imported",
        output_dir=tmp_path / "results",
        settings=Settings(_env_file=None),
    )
    item = session.scalar(select(ContentItemRecord))
    item.cleaned_text = "Changed content"
    session.commit()

    def forbidden(*args, **kwargs):
        raise AssertionError("Changed content must not trigger a model call")

    monkeypatch.setattr(subprocess, "run", forbidden)
    with pytest.raises(ValueError, match="content.*changed"):
        resume_pipeline(session, failed["run_id"], settings=Settings(_env_file=None))


def test_resume_refuses_a_changed_selected_plan(monkeypatch, tmp_path):
    from app.pipeline import run_pipeline, resume_pipeline
    from app.topic_planning.service import persist_topic_plan_for_project

    session = imported_session(tmp_path)
    mock_models(monkeypatch, bad_report=True)
    failed = run_pipeline(
        session,
        1,
        source="imported",
        output_dir=tmp_path / "results",
        settings=Settings(_env_file=None),
    )
    new_plan = DeterministicTopicPlanner().generate(
        TopicPlanningContext(topic="Different research")
    )
    persist_topic_plan_for_project(session, 1, new_plan)
    session.commit()
    with pytest.raises(ValueError, match="plan.*changed"):
        resume_pipeline(session, failed["run_id"], settings=Settings(_env_file=None))


def test_resume_refuses_changed_project_context(monkeypatch, tmp_path):
    from app.pipeline import run_pipeline, resume_pipeline
    from app.db.models import ResearchProjectRecord

    session = imported_session(tmp_path)
    mock_models(monkeypatch, bad_report=True)
    failed = run_pipeline(
        session,
        1,
        source="imported",
        output_dir=tmp_path / "results",
        settings=Settings(_env_file=None),
    )
    session.scalar(select(ResearchProjectRecord)).topic = "Different research topic"
    session.commit()
    with pytest.raises(ValueError, match="Project.*changed"):
        resume_pipeline(session, failed["run_id"], settings=Settings(_env_file=None))


def test_resume_does_not_reset_exhausted_model_budget(monkeypatch, tmp_path):
    from app.pipeline import run_pipeline, resume_pipeline

    session = imported_session(tmp_path)
    mock_models(monkeypatch, bad_report=True)
    failed = run_pipeline(
        session,
        1,
        source="imported",
        max_model_calls=4,
        output_dir=tmp_path / "results",
        settings=Settings(_env_file=None),
    )

    def forbidden(*args, **kwargs):
        raise AssertionError("Exhausted budget must not call a provider")

    monkeypatch.setattr(subprocess, "run", forbidden)
    resumed = resume_pipeline(session, failed["run_id"], settings=Settings(_env_file=None))
    assert resumed["status"] == "blocked"
    assert resumed["model_calls"] == 4
    assert resumed["new_model_calls"] == 0


def test_status_returns_latest_project_report_without_calls(monkeypatch, tmp_path):
    from app.pipeline import run_pipeline, pipeline_status

    session = imported_session(tmp_path)
    mock_models(monkeypatch)
    completed = run_pipeline(
        session,
        1,
        source="imported",
        output_dir=tmp_path / "results",
        settings=Settings(_env_file=None),
    )

    def forbidden(*args, **kwargs):
        raise AssertionError("Status must not call a provider")

    monkeypatch.setattr(subprocess, "run", forbidden)
    status = pipeline_status(session, project_id=1)
    assert status["run_id"] == completed["run_id"]
    assert status["status"] == "completed"
    assert status["source_records"] == 1
    assert status["signal_count"] == 2
    assert status["artifacts"]["report"] == completed["artifacts"]["report"]
    assert "model_audit" not in status


@pytest.mark.parametrize("change_window", [False, True])
def test_browser_handoff_resumes_only_matching_task(monkeypatch, tmp_path, change_window):
    from app.pipeline import run_pipeline, resume_pipeline
    from app.db.models import ResearchPlanRecord
    from tests.reddit.test_browser_dom import page

    session = make_session()
    plan = DeterministicTopicPlanner().generate(TopicPlanningContext(topic="Zurich tutoring"))
    session.add(
        ResearchPlanRecord(project_id=1, plan_json=plan.model_dump(mode="json"), selected=True)
    )
    session.commit()
    started = run_pipeline(
        session,
        1,
        source="builtin-browser-dom",
        output_dir=tmp_path,
        since="2025-10-12T00:00:00Z",
        until="2026-10-12T18:00:00Z",
        max_analysis_items=1,
        settings=Settings(_env_file=None),
    )
    task = json.loads(Path(started["artifacts"]["browser_task"]).read_text())
    if change_window:
        task["until"] = "2026-10-15T18:00:00Z"
    search = page("search.html", task["search_urls"][0])
    discussion = page("discussion.html", "https://www.reddit.com/r/zurich/comments/abc/tutor/")
    discussion["html"] = discussion["html"].replace("2021-10-31", "2026-10-01")
    search["captured_at"] = discussion["captured_at"] = "2026-10-12T18:01:00Z"
    path = tmp_path / "capture.json"
    path.write_text(json.dumps(dict(task=task, searches=[search], discussions=[discussion])))
    mock_models(monkeypatch)
    resumed = resume_pipeline(
        session, started["run_id"], browser_capture_path=path, settings=Settings(_env_file=None)
    )
    if change_window:
        assert resumed["status"] == "failed"
        assert resumed["model_calls"] == 0
        assert not resumed["source_scope"]
    else:
        assert resumed["status"] == "completed", resumed
        assert resumed["model_calls"] == 3
        assert resumed["source_scope"] == {"reddit_post": ["abc"], "reddit_comment": ["c1"]}


def test_cli_start_resume_status_share_one_frozen_configuration(monkeypatch, tmp_path):
    from typer.testing import CliRunner
    from app.cli import app
    from app.db.models import ResearchPlanRecord
    from tests.reddit.test_browser_dom import page

    database_url = f"sqlite:///{tmp_path / 'workflow.db'}"
    session = make_session(database_url)
    plan = DeterministicTopicPlanner().generate(TopicPlanningContext(topic="Zurich tutoring"))
    session.add(
        ResearchPlanRecord(project_id=1, plan_json=plan.model_dump(mode="json"), selected=True)
    )
    session.commit()
    session.close()
    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setenv("REAL_MODEL_PROVIDER", "codex-cli")
    monkeypatch.setenv("REAL_MODEL", "gpt-6.1-sol")
    mock_models(monkeypatch)
    runner = CliRunner()
    start = runner.invoke(
        app,
        [
            "pipeline",
            "run",
            "--project-id",
            "1",
            "--source",
            "builtin-browser-dom",
            "--output-dir",
            str(tmp_path / "runtime with spaces"),
            "--max-analysis-items",
            "1",
            "--max-model-calls",
            "3",
            "--since",
            "2025-10-12T00:00:00Z",
            "--until",
            "2026-10-12T18:00:00Z",
        ],
    )
    assert start.exit_code == 0, start.output
    started = json.loads(start.stdout)
    assert started["status"] == "awaiting_browser"
    task = json.loads(Path(started["artifacts"]["browser_task"]).read_text())
    search = page("search.html", task["search_urls"][0])
    discussion = page("discussion.html", "https://www.reddit.com/r/zurich/comments/abc/tutor/")
    discussion["html"] = discussion["html"].replace("2021-10-31", "2026-10-01")
    search["captured_at"] = discussion["captured_at"] = "2026-10-12T18:01:00Z"
    capture = Path(started["artifacts"]["browser_task"]).parent / "browser-capture.json"
    capture.write_text(json.dumps(dict(searches=[search], discussions=[discussion])))
    resume = runner.invoke(
        app,
        [
            "pipeline",
            "resume",
            "--run-id",
            str(started["run_id"]),
            "--browser-capture-path",
            str(capture),
        ],
    )
    assert resume.exit_code == 0, resume.output
    completed = json.loads(resume.stdout)
    status = runner.invoke(app, ["pipeline", "status", "--project-id", "1"])
    assert status.exit_code == 0, status.output
    result = json.loads(status.stdout)
    assert result["run_id"] == completed["run_id"]
    assert result["model_calls"] == 3
    assert result["signal_count"] == 2
    assert Path(result["artifacts"]["report"]).is_file()


def test_real_pipeline_reextracts_and_excludes_all_prior_signals(monkeypatch, tmp_path):
    from app.pipeline import run_pipeline

    session = imported_session(tmp_path)
    analyze(session, 1)  # Two historical deterministic signals on the same content ID.
    old_ids = set(session.scalars(select(MarketSignalRecord.id)))
    session.commit()
    mock_models(monkeypatch)
    outcome = run_pipeline(
        session,
        1,
        source="imported",
        output_dir=tmp_path / "run",
        settings=Settings(_env_file=None),
    )
    assert outcome["status"] == "completed", outcome
    assert len(outcome["signal_ids"]) == 2
    assert not set(outcome["signal_ids"]) & old_ids
    assert set(session.scalars(select(MarketSignalRecord.id))) == old_ids | set(
        outcome["signal_ids"]
    )
    report = Path(outcome["artifacts"]["report"]).read_text()
    assert "Observed parents seek local tutoring help." in report
    assert "2 trusted market signals" in report
    for old_id in old_ids:
        assert f"### Signal {old_id}\n" not in report
    assert outcome["model_calls"] == 4  # plan, review, extraction, narrative
    assert session.get(PipelineRunRecord, outcome["run_id"]).status == "completed"


def test_cli_dry_run_has_no_calls_writes_or_artifacts(monkeypatch, tmp_path):
    import requests
    from typer.testing import CliRunner
    from app.cli import app
    from tests.reddit.test_export_import import make_session

    url = f"sqlite:///{tmp_path / 'dry.db'}"
    session = make_session(url)

    def forbidden(*args, **kwargs):
        raise AssertionError("Dry-run called an external boundary")

    monkeypatch.setattr(subprocess, "run", forbidden)
    monkeypatch.setattr(requests, "get", forbidden)
    monkeypatch.setattr(requests, "post", forbidden)
    monkeypatch.setenv("DATABASE_URL", url)
    result = CliRunner().invoke(
        app,
        [
            "pipeline",
            "run",
            "--project-id",
            "1",
            "--source",
            "public-json",
            "--dry-run",
            "--output-dir",
            str(tmp_path / "unused"),
        ],
    )
    assert result.exit_code == 0, result.output
    assert "dry_run" in result.output
    assert session.scalars(select(PipelineRunRecord)).all() == []
    assert not (tmp_path / "unused").exists()


def test_automatic_public_source_runs_real_stages_and_scopes_report(monkeypatch, tmp_path):
    import requests
    from app.pipeline import run_pipeline
    from tests.reddit.test_public_json import response

    session = make_session()
    source = post()
    source["data"]["selftext"] = QUOTE

    def get(url, **kwargs):
        return response(
            listing([source])
            if "search.json" in url
            else [
                listing([source]),
                listing(
                    [
                        {
                            "kind": "t1",
                            "data": {
                                "id": "c1",
                                "link_id": "t3_abc",
                                "parent_id": "t3_abc",
                                "body": QUOTE,
                            },
                        }
                    ]
                ),
            ]
        )

    monkeypatch.setattr(requests, "get", get)
    mock_models(monkeypatch)
    outcome = run_pipeline(
        session, 1, source="public-json", max_queries=1, max_items=3, output_dir=tmp_path
    )
    assert outcome["status"] == "completed", outcome
    assert outcome["source_scope"] == {"reddit_post": ["abc"], "reddit_comment": ["c1"]}
    assert outcome["source_requests"] == 2
    assert len(outcome["signal_ids"]) == 4
    assert "web_json" in Path(outcome["artifacts"]["report"]).read_text()


def test_duplicate_or_blocked_acquisition_cannot_reuse_stale_project_evidence(
    monkeypatch, tmp_path
):
    import requests
    from app.pipeline import run_pipeline
    from tests.reddit.test_public_json import response

    session = imported_session(tmp_path)
    analyze(session, 1)
    session.commit()
    mock_models(monkeypatch)
    source = post()
    source["data"]["selftext"] = QUOTE
    monkeypatch.setattr(
        requests,
        "get",
        lambda url, **kwargs: response(
            listing([source]) if "search.json" in url else [listing([source]), listing([])]
        ),
    )
    duplicate = run_pipeline(
        session, 1, source="public-json", max_queries=1, max_items=3, output_dir=tmp_path
    )
    assert duplicate["status"] == "no_evidence"
    assert duplicate["artifacts"] == {}
    monkeypatch.setattr(requests, "get", lambda *args, **kwargs: response({}, 403))
    blocked = run_pipeline(session, 1, source="public-json", max_queries=1, output_dir=tmp_path)
    assert blocked["status"] == "blocked"
    assert blocked["artifacts"] == {}
    session.rollback()
    assert session.get(PipelineRunRecord, blocked["run_id"]).status == "blocked"


def test_shared_model_budget_and_bad_report_preserve_prior_artifacts(monkeypatch, tmp_path):
    from app.pipeline import run_pipeline

    session = imported_session(tmp_path)
    prior = tmp_path / "market-report.md"
    prior.write_text("Previously reviewed report")
    mock_models(monkeypatch)
    budgeted = run_pipeline(session, 1, source="imported", max_model_calls=1, output_dir=tmp_path)
    assert budgeted["status"] != "completed"
    assert budgeted["model_calls"] == 1
    assert budgeted["artifacts"] == {}
    mock_models(monkeypatch, bad_report=True)
    invalid = run_pipeline(session, 1, source="imported", output_dir=tmp_path)
    assert invalid["status"] != "completed"
    assert invalid["artifacts"] == {}
    assert prior.read_text() == "Previously reviewed report"
    assert any(
        stage["stage"] == "report" and stage["status"] == "failed" for stage in invalid["stages"]
    )


def test_nonfinite_budget_is_rejected_before_writes(tmp_path):
    import pytest
    from app.pipeline import run_pipeline

    session = make_session()
    with pytest.raises(ValueError, match="finite"):
        run_pipeline(session, 1, source="imported", max_seconds=float("nan"))
    assert session.scalars(select(PipelineRunRecord)).all() == []


def test_browser_dom_source_reaches_real_transport_with_exact_scope(monkeypatch, tmp_path):
    from app.reddit.browser_dom import ConnectedBrowser
    from tests.reddit.test_browser_dom import page
    from app.pipeline import run_pipeline, pipeline_preflight

    session = make_session()
    mock_models(monkeypatch)
    monkeypatch.setattr(ConnectedBrowser, "__enter__", lambda self: self)
    monkeypatch.setattr(
        ConnectedBrowser,
        "capture",
        lambda self, url: (
            page("search.html", url) if "/search/" in url else page("discussion.html", url)
        ),
    )
    settings = Settings(_env_file=None, browser_dom_cdp_url="http://127.0.0.1:9223")
    ready = pipeline_preflight(
        session,
        1,
        source="auto",
        allow_browser_dom=True,
        allow_public_json=True,
        settings=settings,
        check_login=False,
    )
    assert ready["source"] == "browser-dom"
    assert ready["dom_compatibility"] == "unobserved"
    result = run_pipeline(
        session,
        1,
        source="browser-dom",
        settings=settings,
        max_queries=1,
        max_items=3,
        max_requests=2,
        max_model_calls=8,
        output_dir=tmp_path,
    )
    assert result["status"] == "completed", result
    assert result["source_scope"] == {"reddit_post": ["abc"], "reddit_comment": ["c1", "r1"]}
    assert len(result["signal_ids"]) == 6
    assert result["model_calls"] == 8
    report = Path(result["artifacts"]["report"]).read_text()
    assert "source_mode: dom" in report
    assert "Captured comments: 2" in report
    assert "unknown" in report


def test_browser_source_blocked_or_duplicate_does_not_report_stale_evidence(monkeypatch, tmp_path):
    from app.reddit.browser_dom import ConnectedBrowser
    from tests.reddit.test_browser_dom import page
    from app.pipeline import run_pipeline

    session = imported_session(tmp_path)
    mock_models(monkeypatch)
    monkeypatch.setattr(ConnectedBrowser, "__enter__", lambda self: self)
    monkeypatch.setattr(
        ConnectedBrowser,
        "capture",
        lambda self, url: page("blocked.html", url, "Reddit - Prove your humanity"),
    )
    settings = Settings(_env_file=None, browser_dom_cdp_url="http://127.0.0.1:9223")
    blocked = run_pipeline(
        session,
        1,
        source="browser-dom",
        settings=settings,
        max_queries=1,
        max_items=3,
        max_requests=2,
        output_dir=tmp_path,
    )
    assert blocked["status"] == "blocked"
    assert blocked["artifacts"] == {}
    monkeypatch.setattr(
        ConnectedBrowser,
        "capture",
        lambda self, url: (
            page("search.html", url) if "/search/" in url else page("discussion.html", url)
        ),
    )
    first = run_pipeline(
        session,
        1,
        source="browser-dom",
        settings=settings,
        max_queries=1,
        max_items=3,
        max_requests=2,
        output_dir=tmp_path,
    )
    assert first["status"] == "completed"
    repeated = run_pipeline(
        session,
        1,
        source="browser-dom",
        settings=settings,
        max_queries=1,
        max_items=3,
        max_requests=2,
        output_dir=tmp_path,
    )
    assert repeated["status"] == "no_evidence"
    assert repeated["artifacts"] == {}


def test_browser_opt_in_dry_run_never_invokes_boundary_or_creates_rows(monkeypatch, tmp_path):
    from app.pipeline import run_pipeline, pipeline_preflight

    session = make_session()

    def forbidden(*args, **kwargs):
        raise AssertionError("Dry-run performed subprocess work")

    monkeypatch.setattr(subprocess, "run", forbidden)
    settings = Settings(_env_file=None, browser_dom_cdp_url="http://127.0.0.1:9223")
    result = run_pipeline(
        session,
        1,
        source="auto",
        allow_browser_dom=True,
        settings=settings,
        dry_run=True,
        output_dir=tmp_path / "unused",
    )
    assert result["status"] == "dry_run"
    assert result["preflight"]["source"] == "browser-dom"
    assert session.scalars(select(PipelineRunRecord)).all() == []
    assert not (tmp_path / "unused").exists()
    no_flag = pipeline_preflight(
        session, 1, source="auto", allow_public_json=True, settings=settings, check_login=False
    )
    assert no_flag["source"] == "public-json"
    oauth = settings.model_copy(
        update={
            "reddit_client_id": "synthetic-id",
            "reddit_client_secret": "synthetic-secret",
            "reddit_user_agent": "reddit-market-intel/0.1 contact@example.test",
        }
    )
    assert (
        pipeline_preflight(
            session, 1, source="auto", allow_browser_dom=True, settings=oauth, check_login=False
        )["source"]
        == "reddit-api"
    )
