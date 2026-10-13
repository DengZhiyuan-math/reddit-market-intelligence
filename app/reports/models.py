"""Pydantic contracts for evidence-grounded market reports."""

from typing import Any

from pydantic import BaseModel, Field


class ReportEvidenceItem(BaseModel):
    """One trusted market signal with source traceability for report claims."""

    signal_id: int
    content_item_id: int
    llm_judgement_id: int | None = None
    source_type: str | None = None
    source_id: str | None = None
    source_mode: str | None = None
    source_url: str | None = None
    persona: str | None = None
    pain_point: str | None = None
    urgency: str | None = None
    buying_signal: bool | None = None
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    quote: str | None = None
    signal_json: dict[str, Any] = Field(default_factory=dict)


class ReportDatasetSummary(BaseModel):
    """Aggregate counts used to keep report claims grounded."""

    market_signal_count: int = 0
    content_status_counts: dict[str, int] = Field(default_factory=dict)
    persona_counts: dict[str, int] = Field(default_factory=dict)
    pain_point_counts: dict[str, int] = Field(default_factory=dict)
    urgency_counts: dict[str, int] = Field(default_factory=dict)
    buying_signal_counts: dict[str, int] = Field(default_factory=dict)
    source_mode_counts: dict[str, int] = Field(default_factory=dict)
    abstained_count: int = 0
    uncertain_count: int = 0
    import_batches: list[dict[str, Any]] = Field(default_factory=list)
    import_unique_posts: int = 0
    import_unique_comments: int = 0
    import_discussions: int = 0
    import_coverage: dict[str, dict[str, Any]] = Field(default_factory=dict)


class ReportSection(BaseModel):
    """A report section that separates narrative, evidence links, and caveats."""

    title: str = Field(min_length=1)
    body: str = Field(min_length=1)
    evidence_ids: list[int] = Field(default_factory=list)
    caveats: list[str] = Field(default_factory=list)


class MarketReport(BaseModel):
    """Full structured report contract for Phase 9 Markdown rendering."""

    project_id: int
    topic: str
    dataset_summary: ReportDatasetSummary
    executive_summary: ReportSection
    dataset_overview: ReportSection
    demand_categories: ReportSection
    persona_analysis: ReportSection
    pain_point_analysis: ReportSection
    posting_style_analysis: ReportSection
    market_gaps: ReportSection
    content_strategy: ReportSection
    community_participation_strategy: ReportSection
    actionable_recommendations: ReportSection
    evidence_appendix: list[ReportEvidenceItem] = Field(default_factory=list)
    methodology: ReportSection
    limitations: ReportSection


class ReportGenerationSummary(BaseModel):
    """User-facing and persisted summary for one report generation run."""

    market_signal_count: int = 0
    report_path: str | None = None
    artifact_id: int | None = None
    warnings: list[str] = Field(default_factory=list)
    errors: int = 0
