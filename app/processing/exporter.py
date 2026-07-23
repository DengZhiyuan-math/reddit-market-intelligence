"""Markdown exports for calibrating content filtering decisions."""

from pathlib import Path
import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import ContentItemRecord, ResearchProjectRecord
from app.processing.models import ACCEPTED, AMBIGUOUS, REJECTED

_STATUS_SECTIONS = (
    (ACCEPTED, "Accepted"),
    (AMBIGUOUS, "Ambiguous"),
    (REJECTED, "Rejected"),
)


def export_calibration_samples(
    session: Session,
    project_id: int,
    output_path: Path | None = None,
    *,
    limit_per_band: int = 25,
) -> Path:
    """Export routed content samples for human threshold/rule calibration."""

    project = session.scalar(
        select(ResearchProjectRecord).where(ResearchProjectRecord.project_id == project_id)
    )
    if project is None:
        raise ValueError(f"Project {project_id} was not found.")

    resolved_output = output_path or Path(
        f"outputs/exports/project-{project_id}/calibration-samples.md"
    )
    resolved_output.parent.mkdir(parents=True, exist_ok=True)

    lines = [
        "# Calibration Samples",
        "",
        f"- Project ID: {project_id}",
        f"- Topic: {project.topic}",
        f"- Limit per band: {limit_per_band}",
        "",
    ]
    for status, heading in _STATUS_SECTIONS:
        items = _load_status_items(session, project.id, status, limit_per_band)
        lines.extend([f"## {heading}", "", f"Sample count: {len(items)}", ""])
        if not items:
            lines.extend(["No samples available.", ""])
            continue
        for item in items:
            lines.extend(_render_item(item))

    resolved_output.write_text("\n".join(lines).rstrip() + "\n")
    return resolved_output


def _load_status_items(
    session: Session,
    internal_project_id: int,
    status: str,
    limit: int,
) -> list[ContentItemRecord]:
    return list(
        session.scalars(
            select(ContentItemRecord)
            .where(
                ContentItemRecord.project_id == internal_project_id,
                ContentItemRecord.final_status == status,
            )
            .order_by(ContentItemRecord.relevance_score.desc().nullslast(), ContentItemRecord.id)
            .limit(limit)
        )
    )


def _render_item(item: ContentItemRecord) -> list[str]:
    lines = [
        f"### Content item {item.id}",
        "",
        f"- source_type: {item.source_type}",
        f"- source_id: {item.source_id}",
        f"- language: {item.language or 'unknown'}",
        f"- relevance_score: {_format_float(item.relevance_score)}",
        f"- quality_score: {_format_float(item.quality_score)}",
        f"- ambiguity_score: {_format_float(item.ambiguity_score)}",
        f"- llm_review_required: {item.llm_review_required}",
        "- reasons:",
    ]
    reasons = item.reason_codes or []
    if reasons:
        for reason in reasons:
            code = reason.get("code", "UNKNOWN")
            severity = reason.get("severity", "unknown")
            explanation = reason.get("explanation", "No explanation provided.")
            lines.append(f"  - {code} ({severity}): {explanation}")
    else:
        lines.append("  - None")
    lines.extend(
        [
            "",
            "```text",
            _excerpt(item.cleaned_text or item.text),
            "```",
            "",
        ]
    )
    return lines


def _format_float(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value:.3f}"


def _excerpt(text: str, *, max_length: int = 700) -> str:
    compact = re.sub(r"\s+", " ", text).strip()
    if len(compact) <= max_length:
        return compact
    return compact[: max_length - 3].rstrip() + "..."
