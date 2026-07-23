from __future__ import annotations

from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.db.base import Base
from app.db.models import ContentItemRecord, MarketSignalRecord, PipelineRunRecord
import app.db.models  # noqa: F401
from app.demo.service import SYNTHETIC_NOTICE, run_fixture_demo


def make_session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def test_fixture_demo_creates_synthetic_records_and_artifacts(tmp_path: Path) -> None:
    session = make_session()

    summary = run_fixture_demo(session, output_dir=tmp_path)

    content_items = session.scalars(select(ContentItemRecord)).all()
    market_signals = session.scalars(select(MarketSignalRecord)).all()
    run = session.get(PipelineRunRecord, summary.run_id)

    assert summary.project_id >= 900000
    assert summary.sample_count == 12
    assert summary.content_item_count == 12
    assert summary.market_signal_count == 9
    assert len(content_items) == 12
    assert len(market_signals) == 9
    assert run is not None
    assert run.stage == "fixture_demo"
    assert run.status == "completed"
    assert summary.report_path.startswith(str(tmp_path))
    assert summary.evidence_csv_path.startswith(str(tmp_path))
    assert summary.market_signals_path.startswith(str(tmp_path))
    assert summary.summary_path.startswith(str(tmp_path))

    for artifact_path in summary.artifact_paths:
        assert artifact_path.exists()


def test_fixture_demo_outputs_are_marked_synthetic(tmp_path: Path) -> None:
    session = make_session()

    summary = run_fixture_demo(session, output_dir=tmp_path)

    assert SYNTHETIC_NOTICE in Path(summary.report_path).read_text(encoding="utf-8")
    assert SYNTHETIC_NOTICE in Path(summary.evidence_markdown_path).read_text(encoding="utf-8")
    assert SYNTHETIC_NOTICE in Path(summary.market_signals_path).read_text(encoding="utf-8")
    assert SYNTHETIC_NOTICE in Path(summary.summary_path).read_text(encoding="utf-8")
    assert SYNTHETIC_NOTICE in summary.warnings


def test_fixture_demo_does_not_require_reddit_or_llm_credentials(monkeypatch, tmp_path: Path) -> None:
    for key in (
        "REDDIT_CLIENT_ID",
        "REDDIT_CLIENT_SECRET",
        "REDDIT_USER_AGENT",
        "OPENAI_API_KEY",
    ):
        monkeypatch.delenv(key, raising=False)
    session = make_session()

    summary = run_fixture_demo(session, output_dir=tmp_path)

    assert summary.market_signal_count > 0
    assert Path(summary.report_path).exists()
