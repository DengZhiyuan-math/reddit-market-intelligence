"""Deterministic evidence-grounded report generation and Markdown rendering."""

from app.reports.models import (
    MarketReport,
    ReportDatasetSummary,
    ReportEvidenceItem,
    ReportSection,
)

INSUFFICIENT_EVIDENCE = (
    "insufficient evidence: no trusted extracted market signals are available for this project"
)


def build_market_report(
    project_id: int,
    topic: str,
    evidence_items: list[ReportEvidenceItem],
    dataset_summary: ReportDatasetSummary,
) -> MarketReport:
    """Build a fixed-template market report from stored evidence only."""

    evidence_ids = [item.signal_id for item in evidence_items]
    provenance_caveats = _source_mode_caveats(dataset_summary)
    if not evidence_items:
        caveats = [INSUFFICIENT_EVIDENCE, *provenance_caveats]
        return MarketReport(
            project_id=project_id,
            topic=topic,
            dataset_summary=dataset_summary,
            executive_summary=ReportSection(
                title="Executive Summary",
                body=(
                    "Observed evidence: 0 trusted market signals are available. "
                    "No market conclusions, demand categories, or strategy recommendations "
                    "should be treated as supported until more evidence is collected."
                ),
                caveats=caveats,
            ),
            dataset_overview=_dataset_overview_section(dataset_summary),
            demand_categories=_unsupported_section("Main Demand Categories", caveats),
            persona_analysis=_unsupported_section("Persona Analysis", caveats),
            pain_point_analysis=_unsupported_section("Pain Point Analysis", caveats),
            posting_style_analysis=_unsupported_section("Posting Style Analysis", caveats),
            market_gaps=_unsupported_section("Market Gaps", caveats),
            content_strategy=_unsupported_section("Content Strategy", caveats),
            community_participation_strategy=_community_section([], caveats),
            actionable_recommendations=_unsupported_section("Actionable Recommendations", caveats),
            methodology=_methodology_section(dataset_summary),
            limitations=_limitations_section(dataset_summary, caveats),
        )

    top_persona = _top_label(dataset_summary.persona_counts)
    top_pain = _top_label(dataset_summary.pain_point_counts)
    top_urgency = _top_label(dataset_summary.urgency_counts)
    signal_ids_text = _signal_ids_text(evidence_ids)
    quotes = [item.quote for item in evidence_items if item.quote]

    return MarketReport(
        project_id=project_id,
        topic=topic,
        dataset_summary=dataset_summary,
        executive_summary=ReportSection(
            title="Executive Summary",
            body=(
                f"Observed evidence: {dataset_summary.market_signal_count} trusted market "
                f"signals support this report. Top observed persona: {top_persona}; "
                f"top observed pain point: {top_pain}; top urgency label: {top_urgency}. "
                f"Evidence: {signal_ids_text}."
            ),
            evidence_ids=evidence_ids,
            caveats=provenance_caveats,
        ),
        dataset_overview=_dataset_overview_section(dataset_summary),
        demand_categories=ReportSection(
            title="Main Demand Categories",
            body=(
                f"Observed evidence: demand categories are derived from stored pain-point "
                f"and intent fields, not inferred market size. Top pain point: {top_pain}; "
                f"Signal IDs: {signal_ids_text}."
            ),
            evidence_ids=evidence_ids,
        ),
        persona_analysis=ReportSection(
            title="Persona Analysis",
            body=(
                f"Observed evidence: persona distribution is {dataset_summary.persona_counts}. "
                f"Interpretation: the strongest observed persona is {top_persona}. "
                f"Signal IDs: {signal_ids_text}."
            ),
            evidence_ids=evidence_ids,
        ),
        pain_point_analysis=ReportSection(
            title="Pain Point Analysis",
            body=(
                f"Observed evidence: pain-point distribution is {dataset_summary.pain_point_counts}. "
                f"Interpretation: prioritize messaging around {top_pain} only as an "
                f"evidence-backed hypothesis. Signal IDs: {signal_ids_text}."
            ),
            evidence_ids=evidence_ids,
        ),
        posting_style_analysis=ReportSection(
            title="Posting Style Analysis",
            body=(
                "Observed evidence: posting style should be reviewed from the appendix quotes, "
                f"not generalized beyond the sample. Representative quote count: {len(quotes)}. "
                f"Signal IDs: {signal_ids_text}."
            ),
            evidence_ids=evidence_ids,
        ),
        market_gaps=ReportSection(
            title="Market Gaps",
            body=(
                f"Interpretation: possible gaps should be treated as hypotheses from "
                f"{dataset_summary.market_signal_count} trusted signals, especially around "
                f"{top_pain}. Evidence: {signal_ids_text}."
            ),
            evidence_ids=evidence_ids,
            caveats=[
                "Market gaps are interpretive hypotheses, not measured market size.",
                *provenance_caveats,
            ],
        ),
        content_strategy=ReportSection(
            title="Content Strategy",
            body=(
                f"Recommendation: create content that directly answers the observed pain "
                f"point '{top_pain}' for persona '{top_persona}'. This is an evidence-backed "
                f"hypothesis from Signal IDs: {signal_ids_text}."
            ),
            evidence_ids=evidence_ids,
            caveats=[
                "Content strategy recommendations require human review before posting.",
                *provenance_caveats,
            ],
        ),
        community_participation_strategy=_community_section(evidence_ids, []),
        actionable_recommendations=ReportSection(
            title="Actionable Recommendations",
            body=(
                f"Recommendation: use the observed persona, pain point, and urgency counts "
                f"as positioning inputs, not as representative market statistics. "
                f"Evidence: {signal_ids_text}."
            ),
            evidence_ids=evidence_ids,
            caveats=["Recommendations are evidence-backed hypotheses, not definitive strategy."],
        ),
        evidence_appendix=evidence_items,
        methodology=_methodology_section(dataset_summary),
        limitations=_limitations_section(dataset_summary, provenance_caveats),
    )


def render_market_report_markdown(report: MarketReport) -> str:
    """Render the fixed report template as Markdown."""

    lines = [
        "# Market Intelligence Report",
        "",
        f"- Project ID: {report.project_id}",
        f"- Topic: {report.topic}",
        "",
    ]
    for section in _ordered_sections(report):
        lines.extend(_render_section(section))
    lines.extend(_render_evidence_appendix(report.evidence_appendix))
    lines.extend(_render_section(report.methodology))
    lines.extend(_render_section(report.limitations))
    return "\n".join(lines).rstrip() + "\n"


def _ordered_sections(report: MarketReport) -> list[ReportSection]:
    return [
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
    ]


def _render_section(section: ReportSection) -> list[str]:
    lines = [f"## {section.title}", "", section.body, ""]
    if section.evidence_ids:
        lines.extend([f"Evidence IDs: {_signal_ids_text(section.evidence_ids)}", ""])
    if section.caveats:
        lines.extend(["Caveats:", ""])
        lines.extend(f"- {caveat}" for caveat in section.caveats)
        lines.append("")
    return lines


def _render_evidence_appendix(evidence_items: list[ReportEvidenceItem]) -> list[str]:
    lines = ["## Evidence Appendix", ""]
    if not evidence_items:
        return [*lines, "No trusted market signals available.", ""]

    for item in evidence_items:
        lines.extend(
            [
                f"### Signal {item.signal_id}",
                "",
                f"- content_item_id: {item.content_item_id}",
                f"- llm_judgement_id: {item.llm_judgement_id or 'none'}",
                f"- source_type: {item.source_type or 'unknown'}",
                f"- source_id: {item.source_id or 'unknown'}",
                f"- source_mode: {item.source_mode or 'unknown'}",
                f"- quote: {item.quote or 'n/a'}",
                f"- persona: {item.persona or 'unknown'}",
                f"- pain_point: {item.pain_point or 'unknown'}",
                f"- urgency: {item.urgency or 'unknown'}",
                f"- buying_signal: {_format_bool(item.buying_signal)}",
                f"- confidence: {_format_float(item.confidence)}",
                "",
            ]
        )
    return lines


def _dataset_overview_section(summary: ReportDatasetSummary) -> ReportSection:
    return ReportSection(
        title="Dataset Overview",
        body=(
            f"Observed evidence counts: {summary.market_signal_count} trusted market "
            f"signals; content statuses: {summary.content_status_counts}; personas: "
            f"{summary.persona_counts}; pain points: {summary.pain_point_counts}; "
            f"urgency labels: {summary.urgency_counts}; buying signals: "
            f"{summary.buying_signal_counts}; source modes: {summary.source_mode_counts}; "
            f"abstained extraction calls: "
            f"{summary.abstained_count}; uncertain extraction calls: {summary.uncertain_count}."
        ),
    )


def _unsupported_section(title: str, caveats: list[str]) -> ReportSection:
    return ReportSection(
        title=title,
        body=(
            "Observed evidence: no trusted extracted market signals are available, "
            "so this section refuses unsupported conclusions."
        ),
        caveats=caveats,
    )


def _community_section(evidence_ids: list[int], caveats: list[str]) -> ReportSection:
    if not evidence_ids:
        return ReportSection(
            title="Community Participation Strategy",
            body=(
                "Recommendation: do not post promotional Reddit content from this report. "
                "First collect trusted evidence and review subreddit rules manually."
            ),
            caveats=caveats,
        )
    return ReportSection(
        title="Community Participation Strategy",
        body=(
            "Recommendation: participate transparently, avoid automation, avoid spam, "
            f"and use specific helpful answers informed by Evidence: {_signal_ids_text(evidence_ids)}."
        ),
        evidence_ids=evidence_ids,
        caveats=["Every Reddit participation action should remain manual and subreddit-rule-aware."],
    )


def _methodology_section(summary: ReportDatasetSummary) -> ReportSection:
    return ReportSection(
        title="Methodology",
        body=(
            "This report uses stored Phase 8 extracted market signals as trusted "
            "evidence. Abstained and uncertain LLM extraction calls are counted in "
            f"metadata ({summary.abstained_count} abstained, {summary.uncertain_count} "
            "uncertain) but are not used as evidence for claims. Reddit evidence is "
            "qualitative and not representative market truth."
        ),
    )


def _limitations_section(summary: ReportDatasetSummary, caveats: list[str]) -> ReportSection:
    return ReportSection(
        title="Limitations",
        body=(
            "Reddit discussions are qualitative directional evidence and not representative "
            "of the whole market. The report does not estimate market size, willingness to "
            f"pay, or population-level demand from {summary.market_signal_count} trusted signals."
        ),
        caveats=caveats,
    )


def _source_mode_caveats(summary: ReportDatasetSummary) -> list[str]:
    fallback_count = summary.source_mode_counts.get("web_static", 0) + summary.source_mode_counts.get(
        "web_browser",
        0,
    )
    if fallback_count == 0:
        return []
    return [
        (
            f"{fallback_count} content item(s) came from public-web fallback collection, "
            "not official Reddit API collection; treat them as separately caveated evidence."
        )
    ]


def _top_label(counts: dict[str, int]) -> str:
    if not counts:
        return "unknown"
    return sorted(counts.items(), key=lambda item: (-item[1], item[0]))[0][0]


def _signal_ids_text(evidence_ids: list[int]) -> str:
    return ", ".join(str(evidence_id) for evidence_id in evidence_ids)


def _format_float(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value:.3f}"


def _format_bool(value: bool | None) -> str:
    if value is None:
        return "unknown"
    return str(value).lower()
