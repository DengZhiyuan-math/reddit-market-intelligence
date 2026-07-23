import pytest
from pydantic import ValidationError

from app.reports.models import (
    MarketReport,
    ReportDatasetSummary,
    ReportEvidenceItem,
    ReportGenerationSummary,
    ReportSection,
)


def section(title: str = "Section") -> ReportSection:
    return ReportSection(title=title, body="Evidence-grounded body.")


def test_report_evidence_item_accepts_source_linked_record() -> None:
    item = ReportEvidenceItem(
        signal_id=1,
        content_item_id=10,
        source_id="post-1",
        confidence=0.86,
    )

    assert item.signal_id == 1
    assert item.content_item_id == 10
    assert item.source_id == "post-1"
    assert item.confidence == 0.86


def test_report_evidence_item_rejects_invalid_confidence() -> None:
    with pytest.raises(ValidationError):
        ReportEvidenceItem(signal_id=1, content_item_id=10, confidence=1.2)


def test_report_section_preserves_evidence_ids() -> None:
    report_section = ReportSection(
        title="Executive Summary",
        body="Observed evidence cites source-linked signals.",
        evidence_ids=[1, 2],
    )

    assert report_section.evidence_ids == [1, 2]


def test_market_report_requires_methodology_and_limitations() -> None:
    payload = {
        "project_id": 1,
        "topic": "Swiss tutoring market",
        "dataset_summary": ReportDatasetSummary(),
        "executive_summary": section("Executive Summary"),
        "dataset_overview": section("Dataset Overview"),
        "demand_categories": section("Demand Categories"),
        "persona_analysis": section("Persona Analysis"),
        "pain_point_analysis": section("Pain Point Analysis"),
        "posting_style_analysis": section("Posting Style Analysis"),
        "market_gaps": section("Market Gaps"),
        "content_strategy": section("Content Strategy"),
        "community_participation_strategy": section("Community Participation Strategy"),
        "actionable_recommendations": section("Actionable Recommendations"),
        "evidence_appendix": [],
    }

    with pytest.raises(ValidationError):
        MarketReport(**payload)

    report = MarketReport(
        **payload,
        methodology=section("Methodology"),
        limitations=section("Limitations"),
    )
    assert report.methodology.title == "Methodology"
    assert report.limitations.title == "Limitations"


def test_report_generation_summary_contains_expected_fields() -> None:
    summary = ReportGenerationSummary(
        market_signal_count=3,
        report_path="outputs/reports/project-1/market-report.md",
        artifact_id=9,
        warnings=["thin evidence"],
        errors=0,
    )

    assert summary.market_signal_count == 3
    assert summary.report_path == "outputs/reports/project-1/market-report.md"
    assert summary.artifact_id == 9
    assert summary.warnings == ["thin evidence"]
    assert summary.errors == 0
