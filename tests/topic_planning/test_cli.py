"""CLI tests for structured topic planning commands."""

from contextlib import contextmanager
from types import SimpleNamespace

from typer.testing import CliRunner

import app.cli as cli
from app.cli import app
from app.topic_planning.planner import DeterministicTopicPlanner, TopicPlanningContext


runner = CliRunner()


def sample_plan_result(plan_id: int = 7, selected: bool = True, search_query_count: int = 3):
    topic_plan = DeterministicTopicPlanner().generate(
        TopicPlanningContext(
            topic="Swiss tutoring market in Zurich",
            region="Switzerland, Zurich",
            languages=["en", "de"],
            target_users=["parents"],
        )
    )
    return SimpleNamespace(
        record=SimpleNamespace(id=plan_id, selected=selected),
        topic_plan=topic_plan,
        search_query_count=search_query_count,
    )


@contextmanager
def fake_session_scope():
    yield object()


def test_plans_generate_persists_plan(monkeypatch) -> None:
    monkeypatch.setattr(cli, "session_scope", fake_session_scope)
    monkeypatch.setattr(cli, "generate_and_persist_topic_plan", lambda session, project_id, selected=True: sample_plan_result())

    result = runner.invoke(app, ["plans", "generate", "--project-id", "1"])

    assert result.exit_code == 0
    assert "Research plan 7" in result.output
    assert "Swiss tutoring market" in result.output


def test_plans_generate_dry_run_prints_json(monkeypatch) -> None:
    monkeypatch.setattr(cli, "session_scope", fake_session_scope)
    monkeypatch.setattr(
        cli,
        "generate_topic_plan_for_project",
        lambda session, project_id: sample_plan_result().topic_plan,
    )

    result = runner.invoke(app, ["plans", "generate", "--project-id", "1", "--dry-run"])

    assert result.exit_code == 0
    assert '"core_topic"' in result.output
    assert '"query_strategy"' in result.output


def test_plans_list_prints_table(monkeypatch) -> None:
    monkeypatch.setattr(cli, "session_scope", fake_session_scope)
    monkeypatch.setattr(cli, "list_topic_plans", lambda session, project_id: [sample_plan_result()])

    result = runner.invoke(app, ["plans", "list", "--project-id", "1"])

    assert result.exit_code == 0
    assert "Topic plans for project 1" in result.output
    assert "7" in result.output


def test_plans_show_prints_summary_or_json(monkeypatch) -> None:
    monkeypatch.setattr(cli, "session_scope", fake_session_scope)
    monkeypatch.setattr(cli, "get_topic_plan", lambda session, plan_id: sample_plan_result(plan_id=plan_id))

    summary = runner.invoke(app, ["plans", "show", "--plan-id", "9"])
    json_result = runner.invoke(app, ["plans", "show", "--plan-id", "9", "--json"])

    assert summary.exit_code == 0
    assert "Research plan 9" in summary.output
    assert json_result.exit_code == 0
    assert '"core_topic"' in json_result.output


def test_plans_select_prints_confirmation(monkeypatch) -> None:
    monkeypatch.setattr(cli, "session_scope", fake_session_scope)
    monkeypatch.setattr(cli, "select_topic_plan", lambda session, project_id, plan_id: sample_plan_result(plan_id=plan_id))

    result = runner.invoke(app, ["plans", "select", "--project-id", "1", "--plan-id", "9"])

    assert result.exit_code == 0
    assert "Selected topic plan 9" in result.output


def test_plans_export_writes_valid_json(monkeypatch, tmp_path) -> None:
    output = tmp_path / "exports" / "plan.json"
    monkeypatch.setattr(cli, "session_scope", fake_session_scope)
    monkeypatch.setattr(cli, "get_topic_plan", lambda session, plan_id: sample_plan_result(plan_id=plan_id))

    result = runner.invoke(app, ["plans", "export", "--plan-id", "9", "--output", str(output)])

    assert result.exit_code == 0
    assert output.exists()
    assert '"core_topic"' in output.read_text()


def test_plans_generate_failure_is_readable(monkeypatch) -> None:
    monkeypatch.setattr(cli, "session_scope", fake_session_scope)

    def fail(session, project_id, selected=True):
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(cli, "generate_and_persist_topic_plan", fail)

    result = runner.invoke(app, ["plans", "generate", "--project-id", "1"])

    assert result.exit_code == 1
    assert "Topic plan generation failed" in result.output
    assert "database unavailable" in result.output
