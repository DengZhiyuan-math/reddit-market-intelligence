"""Pydantic models for durable research project runtime state."""

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from app.compliance.policies import (
    AccessMode,
    CollectionEligibility,
    RetentionPolicy,
)


class RunConfig(BaseModel):
    """Reusable run configuration shared by pipeline stages."""

    limit: int = Field(default=100, ge=1)
    dry_run: bool = False


class StageStatus(StrEnum):
    """Metadata-only execution status for rerunnable pipeline stages."""

    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SKIPPED = "skipped"


class StageRun(BaseModel):
    """Stored status record for a pipeline stage run."""

    model_config = ConfigDict(use_enum_values=False)

    stage: str
    status: StageStatus
    started_at: datetime | None = None
    completed_at: datetime | None = None
    run_limit: int | None = Field(default=None, ge=1)
    message: str | None = None


class ProjectCreateInput(BaseModel):
    """User-provided metadata for creating a market research project."""

    model_config = ConfigDict(use_enum_values=False)

    topic: str = Field(min_length=1)
    region: str | None = None
    languages: list[str] = Field(default_factory=list)
    target_users: list[str] = Field(default_factory=list)
    business_context: str | None = None
    time_range: str | None = None
    access_mode: AccessMode = AccessMode.PERSONAL


class ResearchProject(BaseModel):
    """Durable project record persisted by the Phase 2 local registry."""

    model_config = ConfigDict(use_enum_values=False)

    project_id: int
    slug: str
    topic: str
    region: str | None = None
    languages: list[str] = Field(default_factory=list)
    target_users: list[str] = Field(default_factory=list)
    business_context: str | None = None
    time_range: str | None = None
    access_mode: AccessMode
    retention_policy: RetentionPolicy
    collection_eligibility: CollectionEligibility
    run_config: RunConfig
    stage_runs: list[StageRun] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class ProjectRegistry(BaseModel):
    """Local Phase 2 persistence before Phase 3 database migration."""

    next_project_id: int = 1
    projects: list[ResearchProject] = Field(default_factory=list)
