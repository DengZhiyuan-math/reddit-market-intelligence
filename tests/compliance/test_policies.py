import pytest
from pydantic import ValidationError

from app.compliance.policies import (
    AccessMode,
    ALL_RETENTION_TARGETS,
    EligibilitySeverity,
    PROHIBITED_REDDIT_OPERATIONS,
    ProjectPolicyContext,
    RetentionPolicy,
    RetentionTarget,
    describe_prohibited_reddit_operations,
    evaluate_collection_eligibility,
    is_reddit_operation_allowed,
)


def test_access_modes_are_exactly_supported_values() -> None:
    assert {mode.value for mode in AccessMode} == {
        "personal",
        "research",
        "commercial-approved",
    }


def test_unknown_access_mode_fails_validation() -> None:
    with pytest.raises(ValidationError):
        ProjectPolicyContext(access_mode="enterprise")  # type: ignore[arg-type]


def test_business_context_requires_commercial_approved_access() -> None:
    personal = evaluate_collection_eligibility(
        ProjectPolicyContext(
            access_mode=AccessMode.PERSONAL,
            business_context="AI + human tutor platform",
        )
    )
    research = evaluate_collection_eligibility(
        ProjectPolicyContext(
            access_mode=AccessMode.RESEARCH,
            business_context="AI + human tutor platform",
        )
    )

    assert personal.allowed is False
    assert personal.severity is EligibilitySeverity.BLOCK
    assert personal.required_action is not None
    assert "commercial-approved" in personal.required_action
    assert research.allowed is False
    assert research.severity is EligibilitySeverity.BLOCK


def test_business_context_with_commercial_approved_access_is_allowed() -> None:
    eligibility = evaluate_collection_eligibility(
        ProjectPolicyContext(
            access_mode=AccessMode.COMMERCIAL_APPROVED,
            business_context="AI + human tutor platform",
            commercial_approval_reference="reddit-contract-123",
        )
    )

    assert eligibility.allowed is True
    assert eligibility.severity is EligibilitySeverity.ALLOW


def test_non_business_personal_project_is_allowed() -> None:
    eligibility = evaluate_collection_eligibility(
        ProjectPolicyContext(access_mode=AccessMode.PERSONAL)
    )

    assert eligibility.allowed is True
    assert eligibility.severity is EligibilitySeverity.ALLOW


def test_default_retention_policy_covers_all_required_targets() -> None:
    policy = RetentionPolicy()

    assert policy.retention_days == 2
    assert policy.delete_removed_content is True
    assert set(policy.targets) == set(ALL_RETENTION_TARGETS)
    assert {target.value for target in policy.targets} == {
        "raw_text",
        "cleaned_text",
        "embeddings",
        "llm_inputs",
        "llm_outputs",
        "market_signals",
        "reports",
        "exports",
        "logs",
        "caches",
        "backups",
    }


def test_retention_policy_rejects_missing_required_targets() -> None:
    with pytest.raises(ValidationError):
        RetentionPolicy(
            targets=tuple(
                target for target in RetentionTarget if target is not RetentionTarget.BACKUPS
            )
        )


@pytest.mark.parametrize("operation", describe_prohibited_reddit_operations())
def test_prohibited_reddit_operations_are_not_allowed(operation: str) -> None:
    assert is_reddit_operation_allowed(operation) is False


def test_read_only_collection_operation_is_allowed() -> None:
    assert is_reddit_operation_allowed("read_only_collection") is True


def test_expected_prohibited_operations_are_listed() -> None:
    assert set(PROHIBITED_REDDIT_OPERATIONS).issuperset(
        {
            "automatic_posting",
            "automatic_commenting",
            "private_messaging",
            "voting",
            "multi_account_operation",
            "hidden_promotion",
        }
    )
