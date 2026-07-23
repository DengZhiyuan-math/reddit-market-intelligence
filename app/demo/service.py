"""Synthetic fixture demo service for no-credential first-run smoke tests."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.analysis.exporter import export_market_signals
from app.db.models import (
    ContentItemRecord,
    MarketSignalRecord,
    PipelineRunRecord,
    ResearchProjectRecord,
    utc_now,
)
from app.demo.eval_sample import EvalSampleRow, load_eval_samples
from app.demo.models import DemoRunSummary
from app.observability import log_event
from app.processing.models import ACCEPTED, REJECTED
from app.reports.exporter import export_report_evidence
from app.reports.service import generate_market_report


logger = logging.getLogger(__name__)
SYNTHETIC_NOTICE = (
    "Synthetic fixture/demo data only. This output is not observed Reddit evidence."
)


def run_fixture_demo(
    session: Session,
    *,
    output_dir: Path | str = Path("outputs/demo"),
    sample_path: Path | str | None = None,
) -> DemoRunSummary:
    """Run the local synthetic fixture demo through report and evidence exports."""

    resolved_output_dir = Path(output_dir)
    resolved_output_dir.mkdir(parents=True, exist_ok=True)
    samples = load_eval_samples(sample_path)
    project = _create_demo_project(session)
    run = _create_demo_run(session, project, resolved_output_dir, sample_path)
    content_items = _create_content_items(session, project, run, samples)
    market_signals = _create_market_signals(session, project, run, samples, content_items)
    session.flush()

    report_path = resolved_output_dir / "market-report.md"
    report_summary = generate_market_report(
        session,
        project.project_id,
        output_path=report_path,
        limit=max(len(market_signals), 1),
    )
    _prepend_notice(report_path)

    evidence_dir = resolved_output_dir / "evidence"
    evidence_markdown_path, evidence_csv_path = export_report_evidence(
        session,
        project.project_id,
        output_dir=evidence_dir,
        limit=max(len(market_signals), 1),
    )
    _prepend_notice(evidence_markdown_path)

    market_signals_path = export_market_signals(
        session,
        project.project_id,
        resolved_output_dir / "market-signals.md",
        limit=max(len(market_signals), 1),
    )
    _prepend_notice(market_signals_path)

    warnings = [SYNTHETIC_NOTICE, *report_summary.warnings]
    summary = DemoRunSummary(
        project_id=project.project_id,
        run_id=run.id,
        sample_count=len(samples),
        content_item_count=len(content_items),
        market_signal_count=len(market_signals),
        report_path=str(report_path),
        evidence_markdown_path=str(evidence_markdown_path),
        evidence_csv_path=str(evidence_csv_path),
        market_signals_path=str(market_signals_path),
        summary_path=str(resolved_output_dir / "demo-summary.json"),
        output_dir=str(resolved_output_dir),
        warnings=warnings,
    )
    Path(summary.summary_path).write_text(
        json.dumps(summary.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    run.status = "completed"
    run.completed_at = utc_now()
    run.summary = summary.model_dump(mode="json")
    log_event(
        logger,
        "demo.fixture.completed",
        stage="fixture_demo",
        project_id=project.project_id,
        run_id=run.id,
        status="completed",
        item_count_in=len(samples),
        item_count_out=len(market_signals),
        artifact_path=str(resolved_output_dir),
    )
    return summary


def _create_demo_project(session: Session) -> ResearchProjectRecord:
    max_project_id = session.scalar(select(func.max(ResearchProjectRecord.project_id))) or 0
    project_id = max(900000, max_project_id + 1)
    project = ResearchProjectRecord(
        project_id=project_id,
        slug=f"fixture-demo-zurich-tutoring-{project_id}",
        topic="Synthetic Zurich tutoring fixture demo",
        region="Switzerland, Zurich",
        languages=["en", "de"],
        target_users=["parents", "students", "expat families"],
        business_context="Synthetic AI + human tutor platform demo",
        time_range="fixture sample",
        access_mode="personal",
        run_config={"fixture_demo": True, "synthetic": True},
        collection_eligibility={"allowed": False, "reason": "synthetic_fixture_demo"},
    )
    session.add(project)
    session.flush()
    return project


def _create_demo_run(
    session: Session,
    project: ResearchProjectRecord,
    output_dir: Path,
    sample_path: Path | str | None,
) -> PipelineRunRecord:
    run = PipelineRunRecord(
        project_id=project.id,
        stage="fixture_demo",
        status="running",
        run_config={
            "synthetic": True,
            "sample_path": str(sample_path) if sample_path is not None else None,
            "output_dir": str(output_dir),
        },
        summary={},
        started_at=utc_now(),
    )
    session.add(run)
    session.flush()
    return run


def _create_content_items(
    session: Session,
    project: ResearchProjectRecord,
    run: PipelineRunRecord,
    samples: list[EvalSampleRow],
) -> dict[str, ContentItemRecord]:
    content_items: dict[str, ContentItemRecord] = {}
    for sample in samples:
        item = ContentItemRecord(
            project_id=project.id,
            run_id=run.id,
            source_type=sample.source_type,
            source_id=sample.sample_id,
            source_table="synthetic_fixture",
            source_mode="synthetic_fixture",
            text=sample.text,
            cleaned_text=sample.text,
            language=sample.language,
            relevance_score=0.90 if sample.expected_relevance else 0.10,
            quality_score=0.85,
            ambiguity_score=0.05 if sample.expected_relevance else 0.0,
            llm_review_required=False,
            final_status=ACCEPTED if sample.expected_relevance else REJECTED,
            reason_codes=["SYNTHETIC_FIXTURE"],
        )
        session.add(item)
        content_items[sample.sample_id] = item
    session.flush()
    return content_items


def _create_market_signals(
    session: Session,
    project: ResearchProjectRecord,
    run: PipelineRunRecord,
    samples: list[EvalSampleRow],
    content_items: dict[str, ContentItemRecord],
) -> list[MarketSignalRecord]:
    signals: list[MarketSignalRecord] = []
    for sample in samples:
        if not sample.expected_relevance:
            continue
        signal = MarketSignalRecord(
            project_id=project.id,
            run_id=run.id,
            content_item_id=content_items[sample.sample_id].id,
            llm_judgement_id=None,
            source_mode="synthetic_fixture",
            intent_label=sample.expected_intent_label,
            persona_label=sample.expected_persona_label,
            pain_point=", ".join(sample.expected_pain_points) or None,
            urgency_level=sample.expected_urgency_level,
            buying_signal=sample.expected_buying_signal,
            quote=sample.body,
            confidence=0.90,
            signal_json={
                "synthetic_fixture": True,
                "sample_id": sample.sample_id,
                "user_persona": sample.expected_persona_label,
                "explicit_need": sample.expected_intent_label,
                "pain_points": sample.expected_pain_points,
                "urgency": sample.expected_urgency_level,
                "buying_signal": sample.expected_buying_signal,
                "useful_quote": sample.body,
                "notes": sample.notes,
                "confidence": 0.90,
            },
        )
        session.add(signal)
        signals.append(signal)
    session.flush()
    return signals


def _prepend_notice(path: Path) -> None:
    if not path.exists():
        return
    original = path.read_text(encoding="utf-8")
    path.write_text(f"> {SYNTHETIC_NOTICE}\n\n{original}", encoding="utf-8")
