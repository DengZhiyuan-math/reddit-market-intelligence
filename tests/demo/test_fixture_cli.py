from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from app.cli import app


runner = CliRunner()


def test_demo_run_fixture_help_mentions_synthetic_and_no_credentials() -> None:
    result = runner.invoke(app, ["demo", "run-fixture", "--help"])

    assert result.exit_code == 0
    assert "run-fixture" in result.output
    assert "synthetic" in result.output.lower()
    assert "no reddit credentials" in result.output.lower()


def test_demo_run_fixture_command_writes_outputs_without_credentials(
    monkeypatch,
    tmp_path: Path,
) -> None:
    for key in (
        "REDDIT_CLIENT_ID",
        "REDDIT_CLIENT_SECRET",
        "REDDIT_USER_AGENT",
        "OPENAI_API_KEY",
    ):
        monkeypatch.delenv(key, raising=False)
    database_url = f"sqlite:///{tmp_path / 'fixture-demo.sqlite3'}"
    output_dir = tmp_path / "outputs"

    result = runner.invoke(
        app,
        [
            "demo",
            "run-fixture",
            "--database-url",
            database_url,
            "--output-dir",
            str(output_dir),
        ],
    )

    assert result.exit_code == 0
    assert "Synthetic fixture demo" in result.output
    assert "market-report.md" in result.output
    assert "report-evidence.csv" in result.output
    assert (output_dir / "market-report.md").exists()
    assert (output_dir / "evidence" / "report-evidence.csv").exists()


def test_demo_run_fixture_defaults_database_under_output_dir(tmp_path: Path) -> None:
    output_dir = tmp_path / "isolated-demo"

    result = runner.invoke(
        app,
        [
            "demo",
            "run-fixture",
            "--output-dir",
            str(output_dir),
        ],
    )

    assert result.exit_code == 0
    assert (output_dir / "fixture-demo.sqlite3").exists()
