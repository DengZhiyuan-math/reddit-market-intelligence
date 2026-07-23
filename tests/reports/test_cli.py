from contextlib import contextmanager
from pathlib import Path

from typer.testing import CliRunner

import app.cli as cli
from app.cli import app
from app.reports.models import ReportGenerationSummary
from app.reports.service import ReportGenerationServiceError


runner = CliRunner()


@contextmanager
def fake_session_scope():
    yield object()


def test_reports_generate_prints_summary(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(cli, "session_scope", fake_session_scope)
    expected_output_path = tmp_path / "report.md"

    def generate(session, project_id, output_path=None, limit=100):
        assert project_id == 1
        assert output_path == expected_output_path
        assert limit == 7
        return ReportGenerationSummary(
            market_signal_count=3,
            report_path=str(output_path),
            artifact_id=9,
            warnings=[],
            errors=0,
        )

    monkeypatch.setattr(cli, "generate_market_report", generate)

    result = runner.invoke(
        app,
        [
            "reports",
            "generate",
            "--project-id",
            "1",
            "--output-path",
            str(expected_output_path),
            "--limit",
            "7",
        ],
    )

    assert result.exit_code == 0
    assert "Report generation summary" in result.output
    assert "market_signal_count" in result.output
    assert "artifact_id" in result.output


def test_reports_generate_failure_is_readable(monkeypatch) -> None:
    monkeypatch.setattr(cli, "session_scope", fake_session_scope)

    def fail(session, project_id, output_path=None, limit=100):
        raise ReportGenerationServiceError("generator crashed")

    monkeypatch.setattr(cli, "generate_market_report", fail)

    result = runner.invoke(app, ["reports", "generate", "--project-id", "1"])

    assert result.exit_code == 1
    assert "Report generation failed" in result.output
    assert "generator crashed" in result.output


def test_reports_export_evidence_prints_paths(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(cli, "session_scope", fake_session_scope)
    expected_output_dir = tmp_path / "exports"

    def export(session, project_id, output_dir=None, *, limit=100):
        assert project_id == 1
        assert output_dir == expected_output_dir
        assert limit == 5
        return output_dir / "report-evidence.md", output_dir / "report-evidence.csv"

    monkeypatch.setattr(cli, "export_report_evidence", export)

    result = runner.invoke(
        app,
        [
            "reports",
            "export-evidence",
            "--project-id",
            "1",
            "--output-dir",
            str(expected_output_dir),
            "--limit",
            "5",
        ],
    )

    assert result.exit_code == 0
    assert "report-evidence.md" in result.output
    assert "report-evidence.csv" in result.output


def test_reports_export_evidence_failure_is_readable(monkeypatch) -> None:
    monkeypatch.setattr(cli, "session_scope", fake_session_scope)

    def fail(session, project_id, output_dir=None, *, limit=100):
        raise ValueError("Project 404 was not found")

    monkeypatch.setattr(cli, "export_report_evidence", fail)

    result = runner.invoke(app, ["reports", "export-evidence", "--project-id", "404"])

    assert result.exit_code == 1
    assert "Report evidence export failed" in result.output
    assert "Project 404 was not found" in result.output
