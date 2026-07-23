"""Markdown QA exports for extracted market signals."""

from pathlib import Path
import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.analysis.repository import MARKET_SIGNAL_EXTRACTION, SignalExtractionRepository
from app.db.models import ContentItemRecord, LlmCallRecord, MarketSignalRecord


def export_market_signals(
    session: Session,
    project_id: int,
    output_path: Path | None = None,
    *,
    limit: int = 50,
) -> Path:
    """Export extracted market signals for reviewer QA before Phase 9 reporting."""

    repository = SignalExtractionRepository(session)
    project = repository.get_project_by_project_id(project_id)
    statement = (
        select(MarketSignalRecord)
        .where(MarketSignalRecord.project_id == project.id)
        .order_by(MarketSignalRecord.id)
        .limit(limit)
    )
    signals = list(session.scalars(statement))
    abstentions = _list_abstentions(session, project.id, limit)

    resolved_output = output_path or Path(
        f"outputs/exports/project-{project_id}/market-signals.md"
    )
    resolved_output.parent.mkdir(parents=True, exist_ok=True)

    lines = [
        "# Market Signal QA Export",
        "",
        f"- Project ID: {project_id}",
        f"- Topic: {project.topic}",
        f"- Limit: {limit}",
        f"- Signal count: {len(signals)}",
        f"- Abstention/uncertain call count: {len(abstentions)}",
        "",
        "## Extracted Signals",
        "",
    ]
    if not signals:
        lines.extend(["No extracted market signals found.", ""])
    else:
        for signal in signals:
            lines.extend(_render_signal(session, signal))

    lines.extend(["## Abstentions And Uncertain Calls", ""])
    if not abstentions:
        lines.extend(["No abstained or uncertain extraction calls found.", ""])
    else:
        for call in abstentions:
            lines.extend(_render_abstention(call))

    resolved_output.write_text("\n".join(lines).rstrip() + "\n")
    return resolved_output


def _list_abstentions(session: Session, project_db_id: int, limit: int) -> list[LlmCallRecord]:
    statement = (
        select(LlmCallRecord)
        .where(
            LlmCallRecord.project_id == project_db_id,
            LlmCallRecord.call_type == MARKET_SIGNAL_EXTRACTION,
        )
        .order_by(LlmCallRecord.id)
        .limit(limit)
    )
    calls = []
    for call in session.scalars(statement):
        status = (call.output_json or {}).get("status")
        if status in {"abstained", "uncertain"}:
            calls.append(call)
    return calls


def _render_signal(session: Session, signal: MarketSignalRecord) -> list[str]:
    content_item = session.get(ContentItemRecord, signal.content_item_id)
    lines = [
        f"### Market signal {signal.id}",
        "",
        f"- content_item_id: {signal.content_item_id}",
        f"- llm_judgement_id: {signal.llm_judgement_id or 'none'}",
        f"- persona: {signal.persona_label or 'unknown'}",
        f"- pain_point: {signal.pain_point or 'n/a'}",
        f"- urgency: {signal.urgency_level or 'n/a'}",
        f"- buying_signal: {signal.buying_signal}",
        f"- confidence: {_format_float(signal.confidence)}",
        f"- quote: {signal.quote or 'n/a'}",
    ]
    if content_item is not None:
        lines.extend(
            [
                f"- source_type: {content_item.source_type}",
                f"- source_id: {content_item.source_id}",
            ]
        )
    lines.extend(
        [
            "",
            "<details>",
            "<summary>Signal JSON</summary>",
            "",
            "```json",
            json.dumps(signal.signal_json, ensure_ascii=False, indent=2, sort_keys=True),
            "```",
            "",
            "</details>",
            "",
        ]
    )
    return lines


def _render_abstention(call: LlmCallRecord) -> list[str]:
    output = call.output_json or {}
    return [
        f"### Extraction call {call.id}",
        "",
        f"- content_item_id: {call.content_item_id or 'none'}",
        f"- status: {output.get('status', 'unknown')}",
        f"- reason: {output.get('abstention_reason') or 'n/a'}",
        f"- confidence: {_format_float(output.get('confidence'))}",
        "",
    ]


def _format_float(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value:.3f}"
