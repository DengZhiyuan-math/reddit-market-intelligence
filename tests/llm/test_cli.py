from contextlib import contextmanager
from pathlib import Path

from typer.testing import CliRunner

import app.cli as cli
from app.cli import app
from app.llm.models import LlmReviewRunSummary
from app.llm.service import LlmReviewServiceError


runner = CliRunner()


@contextmanager
def fake_session_scope():
    yield object()


def test_llm_review_prints_summary(monkeypatch) -> None:
    monkeypatch.setattr(cli, "session_scope", fake_session_scope)

    def review(session, project_id, limit=None, dry_run=False):
        assert project_id == 1
        assert limit == 10
        assert dry_run is True
        return LlmReviewRunSummary(
            reviewed=2,
            relevant=1,
            irrelevant=1,
            failed=0,
            skipped=3,
            remaining=4,
            errors=0,
        )

    monkeypatch.setattr(cli, "run_llm_review", review)

    result = runner.invoke(
        app,
        ["llm", "review", "--project-id", "1", "--limit", "10", "--dry-run"],
    )

    assert result.exit_code == 0
    assert "LLM review summary" in result.output
    assert "reviewed" in result.output
    assert "remaining" in result.output


def test_llm_review_failure_is_readable(monkeypatch) -> None:
    monkeypatch.setattr(cli, "session_scope", fake_session_scope)

    def fail(session, project_id, limit=None, dry_run=False):
        raise LlmReviewServiceError("provider crashed")

    monkeypatch.setattr(cli, "run_llm_review", fail)

    result = runner.invoke(app, ["llm", "review", "--project-id", "1"])

    assert result.exit_code == 1
    assert "LLM review failed" in result.output
    assert "provider crashed" in result.output


def test_llm_export_review_queue_prints_output_path(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(cli, "session_scope", fake_session_scope)
    output = tmp_path / "queue.md"

    def export(session, project_id, output_path=None, *, limit=50):
        assert project_id == 1
        assert output_path == output
        assert limit == 7
        return output

    monkeypatch.setattr(cli, "export_review_queue", export)

    result = runner.invoke(
        app,
        [
            "llm",
            "export-review-queue",
            "--project-id",
            "1",
            "--output-path",
            str(output),
            "--limit",
            "7",
        ],
    )

    assert result.exit_code == 0
    assert "Exported LLM review queue to" in result.output
    assert "queue.md" in result.output


def test_llm_export_review_queue_failure_is_readable(monkeypatch) -> None:
    monkeypatch.setattr(cli, "session_scope", fake_session_scope)

    def fail(session, project_id, output_path=None, *, limit=50):
        raise ValueError("Project 404 was not found")

    monkeypatch.setattr(cli, "export_review_queue", fail)

    result = runner.invoke(app, ["llm", "export-review-queue", "--project-id", "404"])

    assert result.exit_code == 1
    assert "LLM review queue export failed" in result.output
    assert "Project 404 was not found" in result.output
