from pathlib import Path

from typer.testing import CliRunner

from app.cli import app


runner = CliRunner()


def _registry_arg(path: Path) -> list[str]:
    return ["--registry-path", str(path)]


def test_projects_create_writes_project(tmp_path) -> None:
    registry_path = tmp_path / "projects.json"

    result = runner.invoke(
        app,
        [
            "projects",
            "create",
            "--topic",
            "Swiss tutoring market in Zurich",
            "--region",
            "Switzerland, Zurich",
            "--language",
            "en",
            "--language",
            "de",
            "--target-user",
            "parents",
            "--limit",
            "25",
            *_registry_arg(registry_path),
        ],
    )

    assert result.exit_code == 0
    assert "project_id" in result.output
    assert "swiss-tutoring-market-in-zurich" in result.output
    assert registry_path.exists()


def test_projects_create_dry_run_does_not_write(tmp_path) -> None:
    registry_path = tmp_path / "projects.json"

    result = runner.invoke(
        app,
        [
            "projects",
            "create",
            "--topic",
            "Swiss tutoring market",
            "--dry-run",
            *_registry_arg(registry_path),
        ],
    )

    assert result.exit_code == 0
    assert "Dry run" in result.output
    assert registry_path.exists() is False


def test_projects_show_prints_stored_project(tmp_path) -> None:
    registry_path = tmp_path / "projects.json"
    create_result = runner.invoke(
        app,
        [
            "projects",
            "create",
            "--topic",
            "Swiss tutoring market",
            *_registry_arg(registry_path),
        ],
    )

    result = runner.invoke(
        app,
        ["projects", "show", "--project-id", "1", *_registry_arg(registry_path)],
    )

    assert create_result.exit_code == 0
    assert result.exit_code == 0
    assert "Swiss tutoring market" in result.output
    assert "project_id" in result.output
    assert "Stage runs: none" in result.output


def test_projects_create_invalid_access_mode_is_readable_error(tmp_path) -> None:
    result = runner.invoke(
        app,
        [
            "projects",
            "create",
            "--topic",
            "Swiss tutoring market",
            "--access-mode",
            "enterprise",
            *_registry_arg(tmp_path / "projects.json"),
        ],
    )

    assert result.exit_code != 0
    assert "commercial-approved" in result.output


def test_projects_show_unknown_project_is_readable_error(tmp_path) -> None:
    result = runner.invoke(
        app,
        ["projects", "show", "--project-id", "999", *_registry_arg(tmp_path / "projects.json")],
    )

    assert result.exit_code != 0
    assert "Project not found" in result.output


def test_projects_show_displays_stage_runs(tmp_path) -> None:
    registry_path = tmp_path / "projects.json"
    create_result = runner.invoke(
        app,
        [
            "projects",
            "create",
            "--topic",
            "Swiss tutoring market",
            *_registry_arg(registry_path),
        ],
    )
    record_result = runner.invoke(
        app,
        [
            "projects",
            "record-stage",
            "--project-id",
            "1",
            "--stage",
            "topic_planning",
            "--status",
            "succeeded",
            "--limit",
            "25",
            *_registry_arg(registry_path),
        ],
    )

    show_result = runner.invoke(
        app,
        ["projects", "show", "--project-id", "1", *_registry_arg(registry_path)],
    )

    assert create_result.exit_code == 0
    assert record_result.exit_code == 0
    assert show_result.exit_code == 0
    assert "topic_planning" in show_result.output
    assert "succeeded" in show_result.output
