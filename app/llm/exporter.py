"""Markdown exports for pending LLM ambiguity review queues."""

from pathlib import Path
import re

from sqlalchemy.orm import Session

from app.llm.repository import LlmReviewRepository


def export_review_queue(
    session: Session,
    project_id: int,
    output_path: Path | None = None,
    *,
    limit: int = 50,
) -> Path:
    """Export pending ambiguous items that still require LLM review."""

    repository = LlmReviewRepository(session)
    project = repository.get_project_by_project_id(project_id)
    items = repository.list_pending_ambiguity_items(project.id, limit=limit)

    resolved_output = output_path or Path(
        f"outputs/exports/project-{project_id}/llm-review-queue.md"
    )
    resolved_output.parent.mkdir(parents=True, exist_ok=True)

    lines = [
        "# LLM Review Queue",
        "",
        f"- Project ID: {project_id}",
        f"- Topic: {project.topic}",
        f"- Limit: {limit}",
        f"- Pending item count: {len(items)}",
        "",
        "## Pending Ambiguous Items",
        "",
    ]
    if not items:
        lines.extend(["No pending ambiguous items require LLM review.", ""])
    else:
        for item in items:
            lines.extend(_render_item(item))

    resolved_output.write_text("\n".join(lines).rstrip() + "\n")
    return resolved_output


def _render_item(item) -> list[str]:
    return [
        f"### Content item {item.id}",
        "",
        f"- source_type: {item.source_type}",
        f"- source_id: {item.source_id}",
        f"- language: {item.language or 'unknown'}",
        f"- relevance_score: {_format_float(item.relevance_score)}",
        f"- ambiguity_score: {_format_float(item.ambiguity_score)}",
        f"- quality_score: {_format_float(item.quality_score)}",
        "",
        "```text",
        _excerpt(item.cleaned_text or item.text),
        "```",
        "",
    ]


def _format_float(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value:.3f}"


def _excerpt(text: str, *, max_length: int = 700) -> str:
    compact = re.sub(r"\s+", " ", text).strip()
    if len(compact) <= max_length:
        return compact
    return compact[: max_length - 3].rstrip() + "..."
