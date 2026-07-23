"""Compliance policy models for safe Reddit market research workflows."""

from enum import StrEnum

from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class AccessMode(StrEnum):
    """Supported Reddit API access postures."""

    PERSONAL = "personal"
    RESEARCH = "research"
    COMMERCIAL_APPROVED = "commercial-approved"


class EligibilitySeverity(StrEnum):
    """Machine-readable collection eligibility severity."""

    ALLOW = "allow"
    WARNING = "warning"
    BLOCK = "block"


class RetentionTarget(StrEnum):
    """Storage targets that must participate in retention/deletion policy."""

    RAW_TEXT = "raw_text"
    CLEANED_TEXT = "cleaned_text"
    EMBEDDINGS = "embeddings"
    LLM_INPUTS = "llm_inputs"
    LLM_OUTPUTS = "llm_outputs"
    MARKET_SIGNALS = "market_signals"
    REPORTS = "reports"
    EXPORTS = "exports"
    LOGS = "logs"
    CACHES = "caches"
    BACKUPS = "backups"


class ProjectPolicyContext(BaseModel):
    """Inputs needed to evaluate whether collection may proceed."""

    model_config = ConfigDict(use_enum_values=False)

    access_mode: AccessMode
    business_context: str | None = None
    is_business_use: bool = False
    commercial_approval_reference: str | None = None

    @property
    def has_business_context(self) -> bool:
        """Return true when project metadata suggests business/commercial intent."""

        return bool((self.business_context or "").strip()) or self.is_business_use


class CollectionEligibility(BaseModel):
    """Structured collection gate result consumed by later collector phases."""

    allowed: bool
    severity: EligibilitySeverity
    reasons: tuple[str, ...] = Field(default_factory=tuple)
    required_action: str | None = None


ALL_RETENTION_TARGETS: tuple[RetentionTarget, ...] = tuple(RetentionTarget)

PROHIBITED_REDDIT_OPERATIONS: tuple[str, ...] = (
    "automatic_posting",
    "automatic_commenting",
    "private_messaging",
    "voting",
    "multi_account_operation",
    "account_farming",
    "hidden_promotion",
    "ban_evasion",
)


class RetentionPolicy(BaseModel):
    """Machine-readable policy for Reddit content retention and deletion."""

    retention_days: int = Field(default=2, ge=0)
    delete_removed_content: bool = True
    targets: tuple[RetentionTarget, ...] = Field(default_factory=lambda: ALL_RETENTION_TARGETS)

    @model_validator(mode="after")
    def ensure_all_required_targets_present(self) -> Self:
        missing_targets = set(ALL_RETENTION_TARGETS).difference(self.targets)
        if missing_targets:
            missing = ", ".join(sorted(target.value for target in missing_targets))
            raise ValueError(f"Retention policy missing required targets: {missing}")
        return self


def evaluate_collection_eligibility(context: ProjectPolicyContext) -> CollectionEligibility:
    """Evaluate whether a project is eligible for Reddit collection."""

    if (
        context.has_business_context
        and context.access_mode is not AccessMode.COMMERCIAL_APPROVED
    ):
        return CollectionEligibility(
            allowed=False,
            severity=EligibilitySeverity.BLOCK,
            reasons=(
                "Business or commercial project context requires approved Reddit access.",
                f"Current access mode is {context.access_mode.value!r}.",
            ),
            required_action=(
                "Set access_mode to commercial-approved and record a Reddit commercial "
                "approval reference before collection."
            ),
        )

    return CollectionEligibility(
        allowed=True,
        severity=EligibilitySeverity.ALLOW,
        reasons=("Project access mode is eligible for the configured context.",),
        required_action=None,
    )


def _normalize_operation_name(operation: str) -> str:
    return operation.strip().lower().replace("-", "_").replace(" ", "_")


def is_reddit_operation_allowed(operation: str) -> bool:
    """Return whether a Reddit operation is inside the research-only boundary."""

    return _normalize_operation_name(operation) not in PROHIBITED_REDDIT_OPERATIONS


def describe_prohibited_reddit_operations() -> tuple[str, ...]:
    """Return prohibited Reddit operation identifiers for docs and tests."""

    return PROHIBITED_REDDIT_OPERATIONS
