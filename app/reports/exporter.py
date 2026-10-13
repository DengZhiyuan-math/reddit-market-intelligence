"""Reviewer-friendly exports for report evidence."""

from pathlib import Path
import csv

from sqlalchemy.orm import Session

from app.reports.models import ReportEvidenceItem
from app.reports.repository import ReportRepository

CSV_HEADER = [
    "signal_id",
    "content_item_id",
    "llm_judgement_id",
    "source_type",
    "source_id",
    "source_mode",
    "source_url",
    "persona",
    "pain_point",
    "urgency",
    "buying_signal",
    "confidence",
    "quote",
]


def export_report_evidence(
    session: Session,
    project_id: int,
    output_dir: Path | None = None,
    *,
    limit: int = 100,
    signal_ids: list[int] | None = None,
) -> tuple[Path, Path]:
    """Export report evidence as Markdown and CSV for reviewer inspection."""

    repository = ReportRepository(session)
    project = repository.get_project_by_project_id(project_id)
    evidence_items = repository.list_evidence_items(project.id, limit=limit, signal_ids=signal_ids)
    resolved_output_dir = output_dir or Path(f"outputs/exports/project-{project_id}")
    resolved_output_dir.mkdir(parents=True, exist_ok=True)

    markdown_path = resolved_output_dir / "report-evidence.md"
    csv_path = resolved_output_dir / "report-evidence.csv"
    markdown_path.write_text(
        _render_markdown(project_id, project.topic, evidence_items, limit),
        encoding="utf-8",
    )
    _write_csv(csv_path, evidence_items)
    return markdown_path, csv_path


def _render_markdown(
    project_id: int,
    topic: str,
    evidence_items: list[ReportEvidenceItem],
    limit: int,
) -> str:
    lines = [
        "# Report Evidence Export",
        "",
        f"- Project ID: {project_id}",
        f"- Topic: {topic}",
        f"- Limit: {limit}",
        f"- Evidence count: {len(evidence_items)}",
        "",
    ]
    if not evidence_items:
        lines.extend(["No trusted market signal evidence found.", ""])
        return "\n".join(lines)

    for item in evidence_items:
        lines.extend(
            [
                f"## Signal {item.signal_id}",
                "",
                f"- content_item_id: {item.content_item_id}",
                f"- llm_judgement_id: {item.llm_judgement_id or 'none'}",
                f"- source_type: {item.source_type or 'unknown'}",
                f"- source_id: {item.source_id or 'unknown'}",
                f"- source_mode: {item.source_mode or 'unknown'}",
                f"- source_url: {item.source_url or 'unknown'}",
                f"- persona: {item.persona or 'unknown'}",
                f"- pain_point: {item.pain_point or 'unknown'}",
                f"- urgency: {item.urgency or 'unknown'}",
                f"- buying_signal: {_format_bool(item.buying_signal)}",
                f"- confidence: {_format_float(item.confidence)}",
                f"- quote: {item.quote or 'n/a'}",
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def _write_csv(path: Path, evidence_items: list[ReportEvidenceItem]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_HEADER)
        writer.writeheader()
        for item in evidence_items:
            writer.writerow(
                {
                    "signal_id": item.signal_id,
                    "content_item_id": item.content_item_id,
                    "llm_judgement_id": item.llm_judgement_id or "",
                    "source_type": item.source_type or "",
                    "source_id": item.source_id or "",
                    "source_mode": item.source_mode or "",
                    "source_url": item.source_url or "",
                    "persona": item.persona or "",
                    "pain_point": item.pain_point or "",
                    "urgency": item.urgency or "",
                    "buying_signal": _format_bool(item.buying_signal),
                    "confidence": _format_float(item.confidence),
                    "quote": item.quote or "",
                }
            )


def _format_float(value: float | None) -> str:
    if value is None:
        return ""
    return f"{value:.3f}"


def _format_bool(value: bool | None) -> str:
    if value is None:
        return ""
    return str(value).lower()
