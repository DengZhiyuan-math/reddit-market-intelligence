"""Migration and phase-boundary smoke tests."""

import importlib
from pathlib import Path

from sqlalchemy import create_engine

from app.db.base import Base
import app.db.models  # noqa: F401


def test_initial_migration_metadata_and_callables_exist() -> None:
    migration = importlib.import_module("app.db.migrations.versions.0001_initial_pipeline_schema")

    assert migration.revision == "0001_initial_pipeline_schema"
    assert migration.down_revision is None
    assert callable(migration.upgrade)
    assert callable(migration.downgrade)


def test_discovered_urls_migration_metadata_and_callables_exist() -> None:
    migration = importlib.import_module("app.db.migrations.versions.0002_discovered_urls")

    assert migration.revision == "0002_discovered_urls"
    assert migration.down_revision == "0001_initial_pipeline_schema"
    assert callable(migration.upgrade)
    assert callable(migration.downgrade)


def test_web_fallback_fetches_migration_metadata_and_callables_exist() -> None:
    migration = importlib.import_module("app.db.migrations.versions.0003_web_fallback_fetches")

    assert migration.revision == "0003_web_fallback_fetches"
    assert migration.down_revision == "0002_discovered_urls"
    assert callable(migration.upgrade)
    assert callable(migration.downgrade)


def test_source_mode_provenance_migration_metadata_and_callables_exist() -> None:
    migration = importlib.import_module("app.db.migrations.versions.0004_source_mode_provenance")

    assert migration.revision == "0004_source_mode_provenance"
    assert migration.down_revision == "0003_web_fallback_fetches"
    assert callable(migration.upgrade)
    assert callable(migration.downgrade)


def test_metadata_can_create_and_drop_on_sqlite_smoke_database() -> None:
    engine = create_engine("sqlite:///:memory:")

    Base.metadata.create_all(engine)
    assert "research_projects" in Base.metadata.tables
    assert "discovered_urls" in Base.metadata.tables
    assert "web_fallback_fetches" in Base.metadata.tables
    Base.metadata.drop_all(engine)


def test_phase_3_paths_do_not_execute_reddit_or_llm_behaviour() -> None:
    forbidden_tokens = (
        "praw",
        "asyncpraw",
        "reddit.subreddit",
        "responses.create",
        "chat.completions",
    )
    checked_paths = [Path("app/db"), Path("app/cli.py")]

    combined = ""
    for path in checked_paths:
        if path.is_file():
            combined += path.read_text()
        else:
            for file_path in path.rglob("*.py"):
                combined += file_path.read_text()

    lowered = combined.lower()
    for token in forbidden_tokens:
        assert token.lower() not in lowered
