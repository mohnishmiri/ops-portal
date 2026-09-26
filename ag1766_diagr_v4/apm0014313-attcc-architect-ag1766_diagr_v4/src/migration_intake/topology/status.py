"""
Topology generation status policy.

This module owns the single status decision used by both persistence and report
rendering so run status cannot diverge across surfaces.
"""

from __future__ import annotations

from typing import Any

from migration_intake.domain.topology import GenerationStatus
from migration_intake.topology.report import ReportIssue

NO_EFFECTIVE_MUTATION_ISSUE_ID = "NO_EFFECTIVE_MUTATION"


def evaluate_generation_status(
    *,
    issues: list[ReportIssue],
    mutations: list[dict[str, Any]],
) -> tuple[str, list[ReportIssue]]:
    """
    Return one status decision and the finalized issue list for a generation run.

    The policy marks runs as ``GENERATED_WITH_GAPS`` when any open issue remains
    or a semantic no-op is detected.
    """
    normalized_issues = list(issues)
    _add_no_effective_mutation_issue(issues=normalized_issues, mutations=mutations)

    has_open_issues = any(issue.status.upper() == "OPEN" for issue in normalized_issues)
    has_blocking_severity = any(
        issue.severity.upper() in {"BLOCKER", "CRITICAL", "HIGH"}
        for issue in normalized_issues
    )

    if has_open_issues or has_blocking_severity:
        return GenerationStatus.GENERATED_WITH_GAPS.value, normalized_issues
    return GenerationStatus.READY_FOR_REVIEW.value, normalized_issues


def _add_no_effective_mutation_issue(
    *,
    issues: list[ReportIssue],
    mutations: list[dict[str, Any]],
) -> None:
    """Append a semantic no-op issue when governed markers exist but values did not change."""
    if not mutations:
        return
    if any(issue.issue_id == NO_EFFECTIVE_MUTATION_ISSUE_ID for issue in issues):
        return

    effective_mutation_count = sum(
        1
        for mutation in mutations
        if str(mutation.get("original_value", "")) != str(mutation.get("new_value", ""))
    )
    if effective_mutation_count > 0:
        return

    issues.append(
        ReportIssue(
            issue_id=NO_EFFECTIVE_MUTATION_ISSUE_ID,
            issue_type="INVALID",
            severity="HIGH",
            status="OPEN",
            message=(
                "Diagram generation produced no effective value changes for governed markers."
            ),
            action_required=(
                "Verify slot bindings and confirm the selected base diagram version matches "
                "the active topology profile."
            ),
        )
    )
