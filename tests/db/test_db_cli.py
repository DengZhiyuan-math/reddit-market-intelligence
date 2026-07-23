"""CLI tests for database commands."""

from contextlib import contextmanager
from pathlib import Path

from typer.testing import CliRunner

import app.cli as cli
from app.cli import app
from app.db.import_registry import RegistryImportResult


runner = CliRunner()


def test_db_upgrade_invokes_alembic(monkeypatch) -> None:
    calls = []

    def fake_upgrade(config, revision):
        calls.append((config, revision))

    monkeypatch.setattr(cli.command, "upgrade", fake_upgrade)

    result = runner.invoke(app, ["db", "upgrade", "--database-url", "postgresql+psycopg://u:p@h/db"])

    assert result.exit_code == 0
    assert "Database upgraded to head" in result.output
    assert calls[0][1] == "head"


def test_db_upgrade_failure_is_readable(monkeypatch) -> None:
    def fake_upgrade(config, revision):
        raise RuntimeError("connection refused")

    monkeypatch.setattr(cli.command, "upgrade", fake_upgrade)

    result = runner.invoke(app, ["db", "upgrade"])

    assert result.exit_code == 1
    assert "Database upgrade failed" in result.output
    assert "connection refused" in result.output


def test_db_status_prints_redacted_url(monkeypatch) -> None:
    monkeypatch.setattr(
        cli,
        "_database_status",
        lambda database_url: ("0001_initial_pipeline_schema", "0001_initial_pipeline_schema"),
    )

    result = runner.invoke(
        app,
        ["db", "status", "--database-url", "postgresql+psycopg://user:secret@localhost/db"],
    )

    assert result.exit_code == 0
    assert "Database status" in result.output
    assert "0001_initial_pipeline_schema" in result.output
    assert "secret" not in result.output
    assert "***" in result.output


def test_db_status_failure_is_readable(monkeypatch) -> None:
    def fake_status(database_url):
        raise RuntimeError("no database")

    monkeypatch.setattr(cli, "_database_status", fake_status)

    result = runner.invoke(app, ["db", "status"])

    assert result.exit_code == 1
    assert "Database status failed" in result.output


def test_db_preflight_passes_when_runtime_ready(monkeypatch) -> None:
    monkeypatch.setenv("REDDIT_CLIENT_ID", "client-id")
    monkeypatch.setenv("REDDIT_CLIENT_SECRET", "client-secret")
    monkeypatch.setenv("REDDIT_USER_AGENT", "reddit-market-intel/0.1 by contact@example.com")
    monkeypatch.setattr(
        cli,
        "_database_status",
        lambda database_url: ("0001_initial_pipeline_schema", "0001_initial_pipeline_schema"),
    )
    monkeypatch.setattr("app.runtime.preflight.shutil.which", lambda command: "/usr/bin/docker")

    class Completed:
        returncode = 0

    monkeypatch.setattr("app.runtime.preflight.subprocess.run", lambda *args, **kwargs: Completed())

    result = runner.invoke(app, ["db", "preflight"])

    assert result.exit_code == 0
    assert "Runtime preflight" in result.output
    assert "database_connection" in result.output
    assert "pass" in result.output


def test_db_preflight_fails_with_database_connection_guidance(monkeypatch) -> None:
    def fake_status(database_url):
        raise RuntimeError("connection refused")

    monkeypatch.setattr(cli, "_database_status", fake_status)
    monkeypatch.setattr("app.runtime.preflight.shutil.which", lambda command: None)

    result = runner.invoke(app, ["db", "preflight"])

    assert result.exit_code == 1
    assert "Database status check failed" in result.output
    assert "connection refused" in result.output
    assert "Start Postgres" in result.output
    assert "No Docker Compose command" in result.output


def test_projects_import_json_invokes_import_service(monkeypatch, tmp_path) -> None:
    registry_path = tmp_path / "projects.json"

    @contextmanager
    def fake_session_scope():
        yield object()

    def fake_import(path: Path, session) -> RegistryImportResult:
        assert path == registry_path
        assert session is not None
        return RegistryImportResult(
            imported_projects=1,
            updated_projects=2,
            skipped_projects=0,
            imported_stage_runs=3,
        )

    monkeypatch.setattr(cli, "session_scope", fake_session_scope)
    monkeypatch.setattr(cli, "import_project_registry", fake_import)

    result = runner.invoke(app, ["projects", "import-json", "--registry-path", str(registry_path)])

    assert result.exit_code == 0
    assert "JSON registry import complete" in result.output
    assert "Imported projects: 1" in result.output
    assert "Updated projects: 2" in result.output
    assert "Imported stage runs: 3" in result.output
