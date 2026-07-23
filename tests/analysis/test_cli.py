from contextlib import contextmanager
from pathlib import Path

from typer.testing import CliRunner

import app.cli as cli
from app.analysis.models import SignalExtractionRunSummary
from app.analysis.service import SignalExtractionServiceError
from app.cli import app


runner = CliRunner()


@contextmanager
def fake_session_scope():
    yield object()


def test_analysis_extract_signals_prints_summary(monkeypatch) -> None:
    monkeypatch.setattr(cli, "session_scope", fake_session_scope)

    def extract(session, project_id, limit=None, dry_run=False):
        assert project_id == 1
        assert limit == 10
        assert dry_run is True
        return SignalExtractionRunSummary(
            candidates=2,
            extracted_signals=3,
            abstained=1,
            failed=0,
            skipped_duplicates=4,
            remaining=5,
            errors=0,
        )

    monkeypatch.setattr(cli, "run_signal_extraction", extract)

    result = runner.invoke(
        app,
        ["analysis", "extract-signals", "--project-id", "1", "--limit", "10", "--dry-run"],
    )

    assert result.exit_code == 0
    assert "extraction" in result.output
    assert "summary" in result.output
    assert "extracted_signals" in result.output
    assert "skipped_duplicates" in result.output


def test_analysis_extract_signals_failure_is_readable(monkeypatch) -> None:
    monkeypatch.setattr(cli, "session_scope", fake_session_scope)

    def fail(session, project_id, limit=None, dry_run=False):
        raise SignalExtractionServiceError("provider crashed")

    monkeypatch.setattr(cli, "run_signal_extraction", fail)

    result = runner.invoke(app, ["analysis", "extract-signals", "--project-id", "1"])

    assert result.exit_code == 1
    assert "Market signal extraction failed" in result.output
    assert "provider crashed" in result.output


def test_analysis_export_signals_prints_output_path(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(cli, "session_scope", fake_session_scope)
    output = tmp_path / "signals.md"

    def export(session, project_id, output_path=None, *, limit=50):
        assert project_id == 1
        assert output_path == output
        assert limit == 7
        return output

    monkeypatch.setattr(cli, "export_market_signals", export)

    result = runner.invoke(
        app,
        [
            "analysis",
            "export-signals",
            "--project-id",
            "1",
            "--output-path",
            str(output),
            "--limit",
            "7",
        ],
    )

    assert result.exit_code == 0
    assert "Exported market signals to" in result.output
    assert "signals.md" in result.output


def test_analysis_export_signals_failure_is_readable(monkeypatch) -> None:
    monkeypatch.setattr(cli, "session_scope", fake_session_scope)

    def fail(session, project_id, output_path=None, *, limit=50):
        raise ValueError("Project 404 was not found")

    monkeypatch.setattr(cli, "export_market_signals", fail)

    result = runner.invoke(app, ["analysis", "export-signals", "--project-id", "404"])

    assert result.exit_code == 1
    assert "Market signal export failed" in result.output
    assert "Project 404 was not found" in result.output
