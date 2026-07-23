"""Pydantic models for synthetic fixture demo runs."""

from pathlib import Path

from pydantic import BaseModel, Field


class DemoRunSummary(BaseModel):
    """User-facing summary for a no-credential synthetic fixture demo run."""

    project_id: int
    run_id: int | None = None
    sample_count: int = 0
    content_item_count: int = 0
    market_signal_count: int = 0
    report_path: str
    evidence_markdown_path: str
    evidence_csv_path: str
    market_signals_path: str
    summary_path: str
    output_dir: str
    warnings: list[str] = Field(default_factory=list)

    @property
    def artifact_paths(self) -> list[Path]:
        """Return all demo artifact paths."""

        return [
            Path(self.report_path),
            Path(self.evidence_markdown_path),
            Path(self.evidence_csv_path),
            Path(self.market_signals_path),
            Path(self.summary_path),
        ]
