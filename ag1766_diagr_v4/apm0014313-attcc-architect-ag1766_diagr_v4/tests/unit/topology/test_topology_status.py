"""Unit tests for topology generation status policy."""

from __future__ import annotations

from migration_intake.topology.report import ReportIssue
from migration_intake.topology.status import (
    NO_EFFECTIVE_MUTATION_ISSUE_ID,
    evaluate_generation_status,
)


def _issue(
    *,
    issue_id: str,
    issue_type: str = "MISSING",
    severity: str = "MEDIUM",
    status: str = "OPEN",
) -> ReportIssue:
    return ReportIssue(
        issue_id=issue_id,
        issue_type=issue_type,
        severity=severity,
        status=status,
        message=f"{issue_id} message",
    )


def test_status_policy_marks_missing_fact_as_gapped() -> None:
    run_status, issues = evaluate_generation_status(
        issues=[_issue(issue_id="GAP-ENVIRONMENT", issue_type="MISSING")],
        mutations=[{"original_value": "A", "new_value": "B"}],
    )
    assert run_status == "GENERATED_WITH_GAPS"
    assert any(issue.issue_id == "GAP-ENVIRONMENT" for issue in issues)


def test_status_policy_marks_fill_warning_as_gapped() -> None:
    run_status, _ = evaluate_generation_status(
        issues=[_issue(issue_id="FILL_WARNING_1", issue_type="UNVERIFIED", severity="LOW")],
        mutations=[{"original_value": "A", "new_value": "B"}],
    )
    assert run_status == "GENERATED_WITH_GAPS"


def test_status_policy_marks_fill_error_as_gapped() -> None:
    run_status, _ = evaluate_generation_status(
        issues=[_issue(issue_id="FILL_ERROR_1", issue_type="INVALID", severity="HIGH")],
        mutations=[{"original_value": "A", "new_value": "B"}],
    )
    assert run_status == "GENERATED_WITH_GAPS"


def test_status_policy_marks_unresolved_marker_as_gapped() -> None:
    run_status, _ = evaluate_generation_status(
        issues=[_issue(issue_id="UNRESOLVED-MARKER-1", issue_type="UNRESOLVED", severity="LOW")],
        mutations=[{"original_value": "A", "new_value": "B"}],
    )
    assert run_status == "GENERATED_WITH_GAPS"


def test_status_policy_adds_no_effective_mutation_issue() -> None:
    run_status, issues = evaluate_generation_status(
        issues=[],
        mutations=[
            {"original_value": "APP-NAME", "new_value": "APP-NAME"},
            {"original_value": "REGION", "new_value": "REGION"},
        ],
    )
    assert run_status == "GENERATED_WITH_GAPS"
    assert any(issue.issue_id == NO_EFFECTIVE_MUTATION_ISSUE_ID for issue in issues)


def test_status_policy_marks_clean_run_ready_for_review() -> None:
    run_status, issues = evaluate_generation_status(
        issues=[],
        mutations=[{"original_value": "A", "new_value": "B"}],
    )
    assert run_status == "READY_FOR_REVIEW"
    assert issues == []
