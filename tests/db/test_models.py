"""Schema contract tests for Phase 3 ORM models."""

from sqlalchemy import UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB

from app.db.base import Base
from app.db import models


REQUIRED_TABLES = {
    "research_projects",
    "retention_policies",
    "project_stage_runs",
    "pipeline_runs",
    "search_queries",
    "research_plans",
    "reddit_api_requests",
    "discovered_urls",
    "web_fallback_fetches",
    "reddit_posts_raw",
    "reddit_comments_raw",
    "project_reddit_posts",
    "project_reddit_comments",
    "content_items",
    "content_embeddings",
    "relevance_decisions",
    "llm_calls",
    "llm_judgements",
    "market_signals",
    "report_artifacts",
    "retention_audit_events",
    "artifact_versions",
}


def table(name: str):
    return Base.metadata.tables[name]


def unique_constraint_names(table_name: str) -> set[str]:
    return {
        constraint.name
        for constraint in table(table_name).constraints
        if isinstance(constraint, UniqueConstraint)
    }


def test_data_01_required_tables_exist() -> None:
    assert REQUIRED_TABLES.issubset(Base.metadata.tables)
    assert models.ResearchProjectRecord.__tablename__ == "research_projects"


def test_data_02_raw_payloads_and_outputs_use_jsonb() -> None:
    assert isinstance(table("reddit_posts_raw").c.raw_json.type, JSONB)
    assert isinstance(table("reddit_comments_raw").c.raw_json.type, JSONB)
    assert isinstance(table("llm_calls").c.input_json.type, JSONB)
    assert isinstance(table("report_artifacts").c.dataset_summary.type, JSONB)


def test_data_03_uniqueness_constraints_prevent_duplicate_collection() -> None:
    assert table("research_projects").c.slug.unique is True
    assert table("reddit_posts_raw").c.reddit_post_id.unique is True
    assert table("reddit_comments_raw").c.reddit_comment_id.unique is True
    assert "uq_project_reddit_posts_discovery" in unique_constraint_names("project_reddit_posts")
    assert "uq_project_reddit_comments_discovery" in unique_constraint_names(
        "project_reddit_comments"
    )
    assert "uq_content_items_source" in unique_constraint_names("content_items")


def test_data_04_project_item_provenance_columns_exist() -> None:
    for table_name in ("project_reddit_posts", "project_reddit_comments"):
        columns = table(table_name).c
        for column_name in (
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
        ):
            assert column_name in columns


def test_data_05_unified_artifact_version_metadata_exists() -> None:
    assert "uq_artifact_versions_identity" in unique_constraint_names("artifact_versions")
    assert "prompt_version_id" in table("llm_calls").c
    assert "schema_version_id" in table("llm_judgements").c
    assert "embedding_version_id" in table("content_embeddings").c
    assert "template_version_id" in table("report_artifacts").c


def test_data_06_discovered_url_provenance_columns_exist() -> None:
    columns = table("discovered_urls").c
    for column_name in (
        "project_id",
        "run_id",
        "provider",
        "query",
        "url",
        "normalized_url",
        "title",
        "snippet",
        "status",
        "metadata_json",
        "discovered_at",
    ):
        assert column_name in columns
    assert "uq_discovered_urls_project_provider_url" in unique_constraint_names("discovered_urls")


def test_data_07_web_fallback_fetch_columns_exist() -> None:
    columns = table("web_fallback_fetches").c
    for column_name in (
        "project_id",
        "discovered_url_id",
        "acquisition_method",
        "url",
        "final_url",
        "http_status",
        "parser_version",
        "content_available",
        "risk_flags",
        "error",
        "metadata_json",
        "fetched_at",
    ):
        assert column_name in columns


def test_data_08_source_mode_provenance_columns_exist() -> None:
    assert "source_mode" in table("content_items").c
    assert "source_mode" in table("market_signals").c
