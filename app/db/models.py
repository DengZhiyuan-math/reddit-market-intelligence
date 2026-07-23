"""SQLAlchemy ORM schema for project state, provenance, and derived artifacts."""

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

POSTGRES_JSON = JSONB().with_variant(JSON(), "sqlite")


def utc_now() -> datetime:
    """Return the current UTC timestamp for ORM defaults."""

    return datetime.now(UTC)


class ResearchProjectRecord(Base):
    """Database source-of-truth project record."""

    __tablename__ = "research_projects"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(Integer, unique=True, nullable=False, index=True)
    slug: Mapped[str] = mapped_column(String(200), unique=True, nullable=False)
    topic: Mapped[str] = mapped_column(Text, nullable=False)
    region: Mapped[str | None] = mapped_column(Text)
    languages: Mapped[dict[str, Any]] = mapped_column(POSTGRES_JSON, default=list, nullable=False)
    target_users: Mapped[dict[str, Any]] = mapped_column(POSTGRES_JSON, default=list, nullable=False)
    business_context: Mapped[str | None] = mapped_column(Text)
    time_range: Mapped[str | None] = mapped_column(Text)
    access_mode: Mapped[str] = mapped_column(String(64), nullable=False)
    run_config: Mapped[dict[str, Any]] = mapped_column(POSTGRES_JSON, default=dict, nullable=False)
    collection_eligibility: Mapped[dict[str, Any]] = mapped_column(POSTGRES_JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    stage_runs: Mapped[list["ProjectStageRunRecord"]] = relationship(
        back_populates="project",
        cascade="all, delete-orphan",
    )


class RetentionPolicyRecord(Base):
    """Persisted retention policy for a project."""

    __tablename__ = "retention_policies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("research_projects.id"), nullable=False)
    retention_days: Mapped[int] = mapped_column(Integer, nullable=False)
    delete_removed_content: Mapped[bool] = mapped_column(Boolean, nullable=False)
    targets: Mapped[dict[str, Any]] = mapped_column(POSTGRES_JSON, default=list, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class ProjectStageRunRecord(Base):
    """Metadata-only history for rerunnable pipeline stages."""

    __tablename__ = "project_stage_runs"
    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "stage",
            "started_at",
            name="uq_project_stage_runs_project_stage_started",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("research_projects.id"), nullable=False)
    stage: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(64), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    run_limit: Mapped[int | None] = mapped_column(Integer)
    message: Mapped[str | None] = mapped_column(Text)

    project: Mapped[ResearchProjectRecord] = relationship(back_populates="stage_runs")


class PipelineRunRecord(Base):
    """A concrete execution of one pipeline stage or end-to-end flow."""

    __tablename__ = "pipeline_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("research_projects.id"), nullable=False)
    stage: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(64), nullable=False, default="pending")
    run_config: Mapped[dict[str, Any]] = mapped_column(POSTGRES_JSON, default=dict, nullable=False)
    summary: Mapped[dict[str, Any]] = mapped_column(POSTGRES_JSON, default=dict, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class ArtifactVersionRecord(Base):
    """Unified version metadata for prompts, schemas, models, templates, and stages."""

    __tablename__ = "artifact_versions"
    __table_args__ = (
        UniqueConstraint("artifact_type", "name", "version", name="uq_artifact_versions_identity"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    artifact_type: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    version: Mapped[str] = mapped_column(String(100), nullable=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(POSTGRES_JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class ResearchPlanRecord(Base):
    """Persisted structured Reddit research plan."""

    __tablename__ = "research_plans"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("research_projects.id"), nullable=False)
    run_id: Mapped[int | None] = mapped_column(ForeignKey("pipeline_runs.id"))
    prompt_version_id: Mapped[int | None] = mapped_column(ForeignKey("artifact_versions.id"))
    schema_version_id: Mapped[int | None] = mapped_column(ForeignKey("artifact_versions.id"))
    plan_json: Mapped[dict[str, Any]] = mapped_column(POSTGRES_JSON, nullable=False)
    selected: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class SearchQueryRecord(Base):
    """Search query/subreddit strategy executed by collection phases."""

    __tablename__ = "search_queries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("research_projects.id"), nullable=False)
    run_id: Mapped[int | None] = mapped_column(ForeignKey("pipeline_runs.id"))
    research_plan_id: Mapped[int | None] = mapped_column(ForeignKey("research_plans.id"))
    query: Mapped[str] = mapped_column(Text, nullable=False)
    subreddit: Mapped[str | None] = mapped_column(String(200))
    sort: Mapped[str | None] = mapped_column(String(64))
    time_filter: Mapped[str | None] = mapped_column(String(64))
    filters_json: Mapped[dict[str, Any]] = mapped_column(POSTGRES_JSON, default=dict, nullable=False)
    source: Mapped[str] = mapped_column(String(64), default="reddit", nullable=False)
    status: Mapped[str] = mapped_column(String(64), default="pending", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class RedditApiRequestRecord(Base):
    """Request-level Reddit/API provenance ledger."""

    __tablename__ = "reddit_api_requests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("research_projects.id"), nullable=False)
    run_id: Mapped[int | None] = mapped_column(ForeignKey("pipeline_runs.id"))
    search_query_id: Mapped[int | None] = mapped_column(ForeignKey("search_queries.id"))
    endpoint: Mapped[str] = mapped_column(String(300), nullable=False)
    action: Mapped[str] = mapped_column(String(128), nullable=False)
    subreddit: Mapped[str | None] = mapped_column(String(200))
    query: Mapped[str | None] = mapped_column(Text)
    request_params: Mapped[dict[str, Any]] = mapped_column(POSTGRES_JSON, default=dict, nullable=False)
    status_code: Mapped[int | None] = mapped_column(Integer)
    error: Mapped[str | None] = mapped_column(Text)
    elapsed_ms: Mapped[int | None] = mapped_column(Integer)
    rate_limit_used: Mapped[float | None] = mapped_column(Float)
    rate_limit_remaining: Mapped[float | None] = mapped_column(Float)
    rate_limit_reset: Mapped[float | None] = mapped_column(Float)
    response_headers: Mapped[dict[str, Any]] = mapped_column(POSTGRES_JSON, default=dict, nullable=False)
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class DiscoveredUrlRecord(Base):
    """Search-discovered public URL before content ingestion."""

    __tablename__ = "discovered_urls"
    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "provider",
            "normalized_url",
            name="uq_discovered_urls_project_provider_url",
        ),
        Index("ix_discovered_urls_project_provider", "project_id", "provider"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("research_projects.id"), nullable=False)
    run_id: Mapped[int | None] = mapped_column(ForeignKey("pipeline_runs.id"))
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    query: Mapped[str] = mapped_column(Text, nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_url: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str | None] = mapped_column(Text)
    snippet: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(64), default="discovered", nullable=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(POSTGRES_JSON, default=dict, nullable=False)
    discovered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class WebFallbackFetchRecord(Base):
    """HTTP/browser fetch provenance for public-web fallback collection."""

    __tablename__ = "web_fallback_fetches"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("research_projects.id"), nullable=False)
    discovered_url_id: Mapped[int | None] = mapped_column(ForeignKey("discovered_urls.id"))
    acquisition_method: Mapped[str] = mapped_column(String(64), nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    final_url: Mapped[str | None] = mapped_column(Text)
    http_status: Mapped[int | None] = mapped_column(Integer)
    parser_version: Mapped[str] = mapped_column(String(64), nullable=False)
    content_available: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    risk_flags: Mapped[dict[str, Any]] = mapped_column(POSTGRES_JSON, default=list, nullable=False)
    error: Mapped[str | None] = mapped_column(Text)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(POSTGRES_JSON, default=dict, nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class RedditPostRawRecord(Base):
    """Globally deduplicated raw Reddit post."""

    __tablename__ = "reddit_posts_raw"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    reddit_post_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    reddit_fullname: Mapped[str | None] = mapped_column(String(80), unique=True)
    subreddit: Mapped[str | None] = mapped_column(String(200))
    title: Mapped[str | None] = mapped_column(Text)
    body: Mapped[str | None] = mapped_column(Text)
    author: Mapped[str | None] = mapped_column(Text)
    score: Mapped[int | None] = mapped_column(Integer)
    upvote_ratio: Mapped[float | None] = mapped_column(Float)
    num_comments: Mapped[int | None] = mapped_column(Integer)
    created_utc: Mapped[int | None] = mapped_column(BigInteger)
    permalink: Mapped[str | None] = mapped_column(Text)
    url: Mapped[str | None] = mapped_column(Text)
    raw_json: Mapped[dict[str, Any]] = mapped_column(POSTGRES_JSON, default=dict, nullable=False)
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class RedditCommentRawRecord(Base):
    """Globally deduplicated raw Reddit top-level comment."""

    __tablename__ = "reddit_comments_raw"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    reddit_comment_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    reddit_fullname: Mapped[str | None] = mapped_column(String(80), unique=True)
    reddit_post_id: Mapped[str] = mapped_column(String(64), nullable=False)
    parent_id: Mapped[str | None] = mapped_column(String(80))
    body: Mapped[str | None] = mapped_column(Text)
    author: Mapped[str | None] = mapped_column(Text)
    score: Mapped[int | None] = mapped_column(Integer)
    depth: Mapped[int | None] = mapped_column(Integer)
    created_utc: Mapped[int | None] = mapped_column(BigInteger)
    permalink: Mapped[str | None] = mapped_column(Text)
    raw_json: Mapped[dict[str, Any]] = mapped_column(POSTGRES_JSON, default=dict, nullable=False)
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class ProjectRedditPostRecord(Base):
    """Project/run/query provenance for a discovered Reddit post."""

    __tablename__ = "project_reddit_posts"
    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "reddit_post_raw_id",
            "search_query_id",
            name="uq_project_reddit_posts_discovery",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("research_projects.id"), nullable=False)
    run_id: Mapped[int | None] = mapped_column(ForeignKey("pipeline_runs.id"))
    search_query_id: Mapped[int | None] = mapped_column(ForeignKey("search_queries.id"))
    request_id: Mapped[int | None] = mapped_column(ForeignKey("reddit_api_requests.id"))
    reddit_post_raw_id: Mapped[int] = mapped_column(ForeignKey("reddit_posts_raw.id"), nullable=False)
    subreddit: Mapped[str | None] = mapped_column(String(200))
    query: Mapped[str | None] = mapped_column(Text)
    sort: Mapped[str | None] = mapped_column(String(64))
    time_filter: Mapped[str | None] = mapped_column(String(64))
    filters_json: Mapped[dict[str, Any]] = mapped_column(POSTGRES_JSON, default=dict, nullable=False)
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class ProjectRedditCommentRecord(Base):
    """Project/run/query provenance for a discovered Reddit comment."""

    __tablename__ = "project_reddit_comments"
    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "reddit_comment_raw_id",
            "search_query_id",
            name="uq_project_reddit_comments_discovery",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("research_projects.id"), nullable=False)
    run_id: Mapped[int | None] = mapped_column(ForeignKey("pipeline_runs.id"))
    search_query_id: Mapped[int | None] = mapped_column(ForeignKey("search_queries.id"))
    request_id: Mapped[int | None] = mapped_column(ForeignKey("reddit_api_requests.id"))
    reddit_comment_raw_id: Mapped[int] = mapped_column(
        ForeignKey("reddit_comments_raw.id"),
        nullable=False,
    )
    subreddit: Mapped[str | None] = mapped_column(String(200))
    query: Mapped[str | None] = mapped_column(Text)
    sort: Mapped[str | None] = mapped_column(String(64))
    time_filter: Mapped[str | None] = mapped_column(String(64))
    filters_json: Mapped[dict[str, Any]] = mapped_column(POSTGRES_JSON, default=dict, nullable=False)
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class ContentItemRecord(Base):
    """Unified post/comment content item used by filtering and analysis."""

    __tablename__ = "content_items"
    __table_args__ = (
        UniqueConstraint("project_id", "source_type", "source_id", name="uq_content_items_source"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("research_projects.id"), nullable=False)
    run_id: Mapped[int | None] = mapped_column(ForeignKey("pipeline_runs.id"))
    source_type: Mapped[str] = mapped_column(String(64), nullable=False)
    source_id: Mapped[str] = mapped_column(String(128), nullable=False)
    source_table: Mapped[str | None] = mapped_column(String(128))
    source_mode: Mapped[str] = mapped_column(String(64), default="reddit_api", nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    language: Mapped[str | None] = mapped_column(String(32))
    cleaned_text: Mapped[str | None] = mapped_column(Text)
    relevance_score: Mapped[float | None] = mapped_column(Float)
    quality_score: Mapped[float | None] = mapped_column(Float)
    ambiguity_score: Mapped[float | None] = mapped_column(Float)
    llm_review_required: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    final_status: Mapped[str] = mapped_column(String(64), default="pending", nullable=False)
    reason_codes: Mapped[dict[str, Any]] = mapped_column(POSTGRES_JSON, default=list, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class ContentEmbeddingRecord(Base):
    """Embedding metadata for a content item."""

    __tablename__ = "content_embeddings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    content_item_id: Mapped[int] = mapped_column(ForeignKey("content_items.id"), nullable=False)
    project_id: Mapped[int] = mapped_column(ForeignKey("research_projects.id"), nullable=False)
    embedding_version_id: Mapped[int | None] = mapped_column(ForeignKey("artifact_versions.id"))
    embedding_model: Mapped[str] = mapped_column(String(200), nullable=False)
    dimensions: Mapped[int | None] = mapped_column(Integer)
    vector_json: Mapped[dict[str, Any] | None] = mapped_column(POSTGRES_JSON)
    text_hash: Mapped[str | None] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class RelevanceDecisionRecord(Base):
    """Rule, embedding, or LLM relevance decision."""

    __tablename__ = "relevance_decisions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    content_item_id: Mapped[int] = mapped_column(ForeignKey("content_items.id"), nullable=False)
    project_id: Mapped[int] = mapped_column(ForeignKey("research_projects.id"), nullable=False)
    run_id: Mapped[int | None] = mapped_column(ForeignKey("pipeline_runs.id"))
    decision_type: Mapped[str] = mapped_column(String(64), nullable=False)
    decision: Mapped[str] = mapped_column(String(64), nullable=False)
    score: Mapped[float | None] = mapped_column(Float)
    reason: Mapped[str | None] = mapped_column(Text)
    output_json: Mapped[dict[str, Any]] = mapped_column(POSTGRES_JSON, default=dict, nullable=False)
    schema_version_id: Mapped[int | None] = mapped_column(ForeignKey("artifact_versions.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class LlmCallRecord(Base):
    """Central LLM call audit record."""

    __tablename__ = "llm_calls"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("research_projects.id"), nullable=False)
    run_id: Mapped[int | None] = mapped_column(ForeignKey("pipeline_runs.id"))
    content_item_id: Mapped[int | None] = mapped_column(ForeignKey("content_items.id"))
    call_type: Mapped[str] = mapped_column(String(128), nullable=False)
    provider: Mapped[str | None] = mapped_column(String(128))
    model_name: Mapped[str] = mapped_column(String(200), nullable=False)
    prompt_version_id: Mapped[int | None] = mapped_column(ForeignKey("artifact_versions.id"))
    schema_version_id: Mapped[int | None] = mapped_column(ForeignKey("artifact_versions.id"))
    input_json: Mapped[dict[str, Any]] = mapped_column(POSTGRES_JSON, default=dict, nullable=False)
    output_json: Mapped[dict[str, Any] | None] = mapped_column(POSTGRES_JSON)
    raw_response_json: Mapped[dict[str, Any] | None] = mapped_column(POSTGRES_JSON)
    validation_status: Mapped[str] = mapped_column(String(64), default="pending", nullable=False)
    input_tokens: Mapped[int | None] = mapped_column(Integer)
    output_tokens: Mapped[int | None] = mapped_column(Integer)
    cost_estimate: Mapped[float | None] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class LlmJudgementRecord(Base):
    """Validated judgement returned by an LLM call."""

    __tablename__ = "llm_judgements"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    content_item_id: Mapped[int] = mapped_column(ForeignKey("content_items.id"), nullable=False)
    llm_call_id: Mapped[int | None] = mapped_column(ForeignKey("llm_calls.id"))
    judgement_type: Mapped[str] = mapped_column(String(128), nullable=False)
    output_json: Mapped[dict[str, Any]] = mapped_column(POSTGRES_JSON, nullable=False)
    model_name: Mapped[str] = mapped_column(String(200), nullable=False)
    prompt_version_id: Mapped[int | None] = mapped_column(ForeignKey("artifact_versions.id"))
    schema_version_id: Mapped[int | None] = mapped_column(ForeignKey("artifact_versions.id"))
    validation_status: Mapped[str] = mapped_column(String(64), default="validated", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class MarketSignalRecord(Base):
    """Structured market signal extracted from evidence."""

    __tablename__ = "market_signals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("research_projects.id"), nullable=False)
    run_id: Mapped[int | None] = mapped_column(ForeignKey("pipeline_runs.id"))
    content_item_id: Mapped[int] = mapped_column(ForeignKey("content_items.id"), nullable=False)
    llm_judgement_id: Mapped[int | None] = mapped_column(ForeignKey("llm_judgements.id"))
    source_mode: Mapped[str] = mapped_column(String(64), default="reddit_api", nullable=False)
    intent_label: Mapped[str | None] = mapped_column(String(128))
    persona_label: Mapped[str | None] = mapped_column(String(128))
    pain_point: Mapped[str | None] = mapped_column(Text)
    urgency_level: Mapped[str | None] = mapped_column(String(64))
    buying_signal: Mapped[bool | None] = mapped_column(Boolean)
    quote: Mapped[str | None] = mapped_column(Text)
    confidence: Mapped[float | None] = mapped_column(Float)
    signal_json: Mapped[dict[str, Any]] = mapped_column(POSTGRES_JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class ReportArtifactRecord(Base):
    """Generated report artifact metadata."""

    __tablename__ = "report_artifacts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("research_projects.id"), nullable=False)
    run_id: Mapped[int | None] = mapped_column(ForeignKey("pipeline_runs.id"))
    template_version_id: Mapped[int | None] = mapped_column(ForeignKey("artifact_versions.id"))
    artifact_path: Mapped[str | None] = mapped_column(Text)
    format: Mapped[str] = mapped_column(String(64), default="markdown", nullable=False)
    dataset_summary: Mapped[dict[str, Any]] = mapped_column(POSTGRES_JSON, default=dict, nullable=False)
    report_json: Mapped[dict[str, Any]] = mapped_column(POSTGRES_JSON, default=dict, nullable=False)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class RetentionAuditEventRecord(Base):
    """Audit event for retention/deletion handling."""

    __tablename__ = "retention_audit_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int | None] = mapped_column(ForeignKey("research_projects.id"))
    run_id: Mapped[int | None] = mapped_column(ForeignKey("pipeline_runs.id"))
    target_type: Mapped[str] = mapped_column(String(128), nullable=False)
    target_id: Mapped[str | None] = mapped_column(String(128))
    action: Mapped[str] = mapped_column(String(128), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(POSTGRES_JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


Index("ix_project_reddit_posts_project_run", ProjectRedditPostRecord.project_id, ProjectRedditPostRecord.run_id)
Index(
    "ix_project_reddit_comments_project_run",
    ProjectRedditCommentRecord.project_id,
    ProjectRedditCommentRecord.run_id,
)
