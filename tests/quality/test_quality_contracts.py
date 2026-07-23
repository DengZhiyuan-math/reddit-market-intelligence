from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
QUALITY_DOC = ROOT / "docs" / "quality-coverage.md"


def _doc_text() -> str:
    return QUALITY_DOC.read_text(encoding="utf-8").lower()


def test_quality_matrix_covers_required_mvp_seams() -> None:
    text = _doc_text()
    required_terms = [
        "settings/config",
        "db model/migration",
        "reddit dedup/rate-limit",
        "cleaning/relevance routing",
        "llm structured validation",
        "market signal extraction",
        "report rendering/export",
        "cli failure readability",
        "fixture demo",
        "observability",
    ]

    missing = [term for term in required_terms if term not in text]

    assert not missing, f"quality matrix is missing required seam(s): {missing}"


def test_quality_matrix_names_existing_or_planned_test_paths() -> None:
    text = _doc_text()
    required_paths = [
        "tests/projects/test_settings.py",
        "tests/db/test_migration_smoke.py",
        "tests/reddit/test_rate_limiter.py",
        "tests/processing/test_relevance.py",
        "tests/llm/test_models.py",
        "tests/analysis/test_service.py",
        "tests/reports/test_generator.py",
        "tests/demo/test_fixture_cli.py",
        "tests/observability/test_logging.py",
    ]

    missing = [path for path in required_paths if path.lower() not in text]

    assert not missing, f"quality matrix is missing test path(s): {missing}"


def test_quality_matrix_documents_full_validation_commands() -> None:
    text = QUALITY_DOC.read_text(encoding="utf-8")

    assert "uv run pytest -q" in text
    assert "uv run ruff check app tests" in text


def test_automated_verification_boundary_is_no_live_provider() -> None:
    text = _doc_text()

    assert "no-network" in text
    assert "no-live-llm" in text
    assert "live reddit credentials and live llm provider calls are not required" in text
    assert "reddit_client_id" in text
    assert "reddit_client_secret" in text
    assert "reddit_user_agent" in text
    assert "openai_api_key" in text


def test_key_deterministic_test_directories_exist() -> None:
    expected_dirs = [
        ROOT / "tests" / "projects",
        ROOT / "tests" / "db",
        ROOT / "tests" / "reddit",
        ROOT / "tests" / "processing",
        ROOT / "tests" / "llm",
        ROOT / "tests" / "analysis",
        ROOT / "tests" / "reports",
        ROOT / "tests" / "quality",
    ]

    missing = [str(path.relative_to(ROOT)) for path in expected_dirs if not path.is_dir()]

    assert not missing, f"missing deterministic test directories: {missing}"
