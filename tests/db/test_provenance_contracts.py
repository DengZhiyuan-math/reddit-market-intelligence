"""Hard contract tests for Phase 3 provenance, JSONB, uniqueness, and versions."""

from sqlalchemy import UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB

from app.db.base import Base
import app.db.models  # noqa: F401


def table(name: str):
    return Base.metadata.tables[name]


def unique_names(table_name: str) -> set[str]:
    return {
        constraint.name
        for constraint in table(table_name).constraints
        if isinstance(constraint, UniqueConstraint)
    }


def test_data_02_raw_payload_contract_uses_postgresql_jsonb() -> None:
    assert isinstance(table("reddit_posts_raw").c.raw_json.type, JSONB)
    assert isinstance(table("reddit_comments_raw").c.raw_json.type, JSONB)
    assert isinstance(table("reddit_api_requests").c.response_headers.type, JSONB)


def test_data_03_duplicate_prevention_contracts_are_present() -> None:
    assert table("reddit_posts_raw").c.reddit_post_id.unique is True
    assert table("reddit_comments_raw").c.reddit_comment_id.unique is True
    assert "uq_project_reddit_posts_discovery" in unique_names("project_reddit_posts")
    assert "uq_project_reddit_comments_discovery" in unique_names("project_reddit_comments")
    assert "uq_content_items_source" in unique_names("content_items")


def test_data_04_collected_item_provenance_contract_is_complete() -> None:
    required_columns = {
        "project_id",
        "run_id",
        "search_query_id",
        "request_id",
        "subreddit",
        "query",
        "sort",
        "time_filter",
        "filters_json",
        "collected_at",
    }
    assert required_columns.issubset(table("project_reddit_posts").c.keys())
    assert required_columns.issubset(table("project_reddit_comments").c.keys())


def test_data_04_request_ledger_records_rate_limit_and_error_context() -> None:
    required_columns = {
        "endpoint",
        "action",
        "subreddit",
        "query",
        "status_code",
        "error",
        "elapsed_ms",
        "rate_limit_used",
        "rate_limit_remaining",
        "rate_limit_reset",
        "requested_at",
        "completed_at",
    }
    assert required_columns.issubset(table("reddit_api_requests").c.keys())


def test_data_05_version_contract_is_unified_and_linked() -> None:
    assert "uq_artifact_versions_identity" in unique_names("artifact_versions")
    assert "prompt_version_id" in table("llm_calls").c
    assert "schema_version_id" in table("llm_calls").c
    assert "schema_version_id" in table("llm_judgements").c
    assert "embedding_version_id" in table("content_embeddings").c
    assert "template_version_id" in table("report_artifacts").c
