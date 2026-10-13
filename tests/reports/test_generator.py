from app.reports.generator import build_market_report, render_market_report_markdown
from app.reports.models import ReportDatasetSummary, ReportEvidenceItem, ReportSection


def evidence_item(
    signal_id: int,
    *,
    persona: str = "PARENT",
    pain_point: str = "Needs trusted math support.",
) -> ReportEvidenceItem:
    return ReportEvidenceItem(
        signal_id=signal_id,
        content_item_id=signal_id + 10,
        llm_judgement_id=None,
        source_type="reddit_post",
        source_id=f"post-{signal_id}",
        source_mode="reddit_api",
        persona=persona,
        pain_point=pain_point,
        urgency="medium",
        buying_signal=True,
        confidence=0.86,
        quote="Can anyone recommend a math tutor in Zurich?",
        signal_json={"fixture": signal_id},
    )


def dataset_summary(market_signal_count: int = 2) -> ReportDatasetSummary:
    return ReportDatasetSummary(
        market_signal_count=market_signal_count,
        content_status_counts={"accepted": market_signal_count},
        persona_counts={"PARENT": market_signal_count},
        pain_point_counts={"Needs trusted math support.": market_signal_count},
        urgency_counts={"medium": market_signal_count},
        buying_signal_counts={"true": market_signal_count, "false": 0, "unknown": 0},
        source_mode_counts={"reddit_api": market_signal_count},
        abstained_count=1,
        uncertain_count=1,
    )


def test_build_market_report_populates_required_sections_with_evidence() -> None:
    report = build_market_report(
        1,
        "Swiss tutoring market",
        [evidence_item(1), evidence_item(2)],
        dataset_summary(),
    )

    required_sections = [
        report.executive_summary,
        report.dataset_overview,
        report.demand_categories,
        report.persona_analysis,
        report.pain_point_analysis,
        report.posting_style_analysis,
        report.market_gaps,
        report.content_strategy,
        report.community_participation_strategy,
        report.actionable_recommendations,
        report.methodology,
        report.limitations,
    ]
    assert all(isinstance(section, ReportSection) for section in required_sections)
    assert report.executive_summary.evidence_ids == [1, 2]
    assert "Evidence:" in report.executive_summary.body
    assert len(report.executive_summary.body) <= 800


def test_build_market_report_refuses_unsupported_zero_evidence_claims() -> None:
    report = build_market_report(
        1,
        "Swiss tutoring market",
        [],
        dataset_summary(market_signal_count=0),
    )

    assert any("insufficient evidence" in caveat for caveat in report.executive_summary.caveats)
    assert "top demand category is" not in report.demand_categories.body.lower()
    assert report.content_strategy.caveats
    assert report.actionable_recommendations.caveats


def test_methodology_and_limitations_describe_qualitative_non_representative_evidence() -> None:
    report = build_market_report(
        1,
        "Swiss tutoring market",
        [evidence_item(1)],
        dataset_summary(market_signal_count=1),
    )
    combined = f"{report.methodology.body} {report.limitations.body}".lower()

    assert "qualitative" in combined
    assert "not representative" in combined


def test_render_market_report_markdown_contains_fixed_template_and_appendix() -> None:
    report = build_market_report(
        1,
        "Swiss tutoring market",
        [evidence_item(1)],
        dataset_summary(market_signal_count=1),
    )

    markdown = render_market_report_markdown(report)

    assert markdown.startswith("# Market Intelligence Report")
    for heading in [
        "## Executive Summary",
        "## Dataset Overview",
        "## Main Demand Categories",
        "## Persona Analysis",
        "## Pain Point Analysis",
        "## Posting Style Analysis",
        "## Market Gaps",
        "## Content Strategy",
        "## Community Participation Strategy",
        "## Actionable Recommendations",
        "## Evidence Appendix",
        "## Methodology",
        "## Limitations",
    ]:
        assert heading in markdown
    assert "Signal 1" in markdown
    assert "content_item_id" in markdown


def test_render_market_report_markdown_renders_caveats() -> None:
    report = build_market_report(
        1,
        "Swiss tutoring market",
        [],
        dataset_summary(market_signal_count=0),
    )

    markdown = render_market_report_markdown(report)

    assert "Caveats:" in markdown
    assert "insufficient evidence" in markdown


def test_fallback_source_mode_adds_report_caveat_and_appendix_label() -> None:
    summary = dataset_summary(market_signal_count=1)
    summary.source_mode_counts = {"web_static": 1}
    item = evidence_item(1)
    item.source_mode = "web_static"
    report = build_market_report(1, "Swiss tutoring market", [item], summary)

    markdown = render_market_report_markdown(report)

    assert "public-web fallback collection" in markdown
    assert "not official Reddit API collection" in markdown
    assert "source_mode: web_static" in markdown


def test_import_caveats_are_rendered_when_no_trusted_signal_exists() -> None:
    summary = ReportDatasetSummary(
        import_batches=[
            {
                "run_id": 1,
                "capture": {
                    "acquisition_method": "dom",
                    "filename": "empty.json",
                    "captured_at": None,
                },
                "coverage": {
                    "captured_posts": 0,
                    "captured_comments": 0,
                    "missing_fields": {"text": 1},
                },
            }
        ]
    )
    report = build_market_report(1, "No evidence", [], summary)
    markdown = render_market_report_markdown(report)
    assert "insufficient evidence" in markdown
    assert "only loaded page content" in markdown
    assert "captured_at=unknown" in markdown
    assert "missing fields={'text': 1}" in markdown
