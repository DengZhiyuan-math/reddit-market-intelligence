from contextlib import contextmanager
from pathlib import Path

from typer.testing import CliRunner

import app.cli as cli
from app.cli import app
from app.processing.models import FilteringRunSummary
from app.processing.service import ProcessingServiceError


runner = CliRunner()


@contextmanager
def fake_session_scope():
    yield object()


def test_filtering_run_prints_summary(monkeypatch) -> None:
    monkeypatch.setattr(cli, "session_scope", fake_session_scope)
    monkeypatch.setattr(
        cli,
        "run_filtering",
        lambda session, project_id, limit=None: FilteringRunSummary(
            raw_posts_processed=2,
            raw_comments_processed=3,
            content_items_created=4,
            accepted=1,
            rejected=1,
            ambiguous=2,
            embedded=3,
            llm_review_required=2,
        ),
    )

    result = runner.invoke(app, ["filtering", "run", "--project-id", "1", "--limit", "10"])

    assert result.exit_code == 0
    assert "Filtering summary" in result.output
    assert "raw_posts_processed" in result.output
    assert "llm_review_required" in result.output


def test_filtering_run_failure_is_readable(monkeypatch) -> None:
    monkeypatch.setattr(cli, "session_scope", fake_session_scope)

    def fail(session, project_id, limit=None):
        raise ProcessingServiceError("project missing")

    monkeypatch.setattr(cli, "run_filtering", fail)

    result = runner.invoke(app, ["filtering", "run", "--project-id", "1"])

    assert result.exit_code == 1
    assert "Filtering failed" in result.output
    assert "project missing" in result.output


def test_filtering_export_samples_prints_output_path(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(cli, "session_scope", fake_session_scope)
    output = tmp_path / "samples.md"

    def export(session, project_id, output_path=None, *, limit_per_band=25):
        assert project_id == 1
        assert output_path == output
        assert limit_per_band == 2
        return output

    monkeypatch.setattr(cli, "export_calibration_samples", export)

    result = runner.invoke(
        app,
        [
            "filtering",
            "export-samples",
            "--project-id",
            "1",
            "--output-path",
            str(output),
            "--limit-per-band",
            "2",
        ],
    )

    assert result.exit_code == 0
    assert "Exported calibration samples to" in result.output
    assert "samples.md" in result.output


def test_filtering_export_samples_failure_is_readable(monkeypatch) -> None:
    monkeypatch.setattr(cli, "session_scope", fake_session_scope)

    def fail(session, project_id, output_path=None, *, limit_per_band=25):
        raise ValueError("Project 404 was not found")

    monkeypatch.setattr(cli, "export_calibration_samples", fail)

    result = runner.invoke(app, ["filtering", "export-samples", "--project-id", "404"])

    assert result.exit_code == 1
    assert "Calibration sample export failed" in result.output
    assert "Project 404 was not found" in result.output
