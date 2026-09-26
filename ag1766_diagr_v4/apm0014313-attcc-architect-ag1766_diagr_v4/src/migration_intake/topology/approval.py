"""
Topology Approval and Review — P10 Implementation.

Implements the approval workflow for topology generation:
- Capability-based authorization
- Run review with compare-and-set transitions
- Gap approval policy
- Supersession management
- Audit event generation

Design rules:
- Blockers are never approvable
- Non-blocking gaps require issue-level rationale
- Superseded runs remain immutable
- Only approved official runs are eligible for downstream linkage
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any

# ─────────────────────────────────────────────────────────────────────────────
# Enums
# ─────────────────────────────────────────────────────────────────────────────


class Capability(str, Enum):
    """Capabilities for topology operations."""

    # Base diagram capabilities
    UPLOAD_BASE = "topology:base:upload"
    REVIEW_BASE_COMPATIBILITY = "topology:base:review_compatibility"
    APPROVE_BASE = "topology:base:approve"

    # Generation capabilities
    GENERATE_PREVIEW = "topology:run:preview"
    GENERATE_OFFICIAL = "topology:run:official"

    # Run review capabilities
    APPROVE_RUN = "topology:run:approve"
    REJECT_RUN = "topology:run:reject"
    SUPERSEDE_RUN = "topology:run:supersede"

    # Download capabilities
    DOWNLOAD_ARTIFACTS = "topology:artifacts:download"


class ReviewDecision(str, Enum):
    """Review decision for a generation run."""

    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    APPROVED_WITH_GAPS = "APPROVED_WITH_GAPS"


class ApprovalStatus(str, Enum):
    """Approval status for a generation run."""

    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"


class GapSeverity(str, Enum):
    """Severity of a gap in generation output."""

    BLOCKER = "BLOCKER"  # Never approvable
    WARNING = "WARNING"  # Requires rationale
    INFO = "INFO"  # Informational only


class AuditEventType(str, Enum):
    """Types of audit events."""

    # Base diagram events
    BASE_UPLOADED = "BASE_UPLOADED"
    BASE_COMPATIBILITY_CHECKED = "BASE_COMPATIBILITY_CHECKED"
    BASE_APPROVED = "BASE_APPROVED"
    BASE_REJECTED = "BASE_REJECTED"
    BASE_SUPERSEDED = "BASE_SUPERSEDED"

    # Run events
    RUN_STARTED = "RUN_STARTED"
    RUN_COMPLETED = "RUN_COMPLETED"
    RUN_FAILED = "RUN_FAILED"
    RUN_APPROVED = "RUN_APPROVED"
    RUN_REJECTED = "RUN_REJECTED"
    RUN_SUPERSEDED = "RUN_SUPERSEDED"

    # Download events
    ARTIFACT_DOWNLOADED = "ARTIFACT_DOWNLOADED"


# ─────────────────────────────────────────────────────────────────────────────
# Data Classes - Authorization
# ─────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Actor:
    """Actor performing an operation."""

    actor_id: str
    actor_type: str  # USER, SYSTEM, SERVICE
    capabilities: frozenset[Capability]


@dataclass(frozen=True)
class AuthorizationResult:
    """Result of an authorization check."""

    authorized: bool
    required_capability: Capability
    actor_id: str
    reason: str | None = None


def check_authorization(
    actor: Actor,
    required_capability: Capability,
) -> AuthorizationResult:
    """Check if an actor has a required capability."""
    if required_capability in actor.capabilities:
        return AuthorizationResult(
            authorized=True,
            required_capability=required_capability,
            actor_id=actor.actor_id,
        )
    return AuthorizationResult(
        authorized=False,
        required_capability=required_capability,
        actor_id=actor.actor_id,
        reason=f"Missing capability: {required_capability.value}",
    )


# ─────────────────────────────────────────────────────────────────────────────
# Data Classes - Gap Policy
# ─────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Gap:
    """A gap in generation output."""

    gap_id: str
    gap_type: str
    severity: GapSeverity
    message: str
    slot_id: str | None = None
    marker: str | None = None


@dataclass
class GapRationale:
    """Rationale for approving a gap."""

    gap_id: str
    rationale: str
    approved_by: str
    approved_at: datetime


@dataclass
class GapApprovalPolicy:
    """Policy for approving gaps."""

    # Gaps that can never be approved
    blocker_types: frozenset[str] = field(
        default_factory=lambda: frozenset({"MISSING_REQUIRED_SLOT", "HASH_MISMATCH"})
    )

    # Gaps that require rationale
    rationale_required_types: frozenset[str] = field(
        default_factory=lambda: frozenset({"UNRESOLVED_MARKER", "MISSING_OPTIONAL_SLOT"})
    )

    def can_approve_gap(self, gap: Gap) -> tuple[bool, str | None]:
        """Check if a gap can be approved."""
        if gap.severity == GapSeverity.BLOCKER:
            return False, "Blocker gaps cannot be approved"

        if gap.gap_type in self.blocker_types:
            return False, f"Gap type {gap.gap_type} is a blocker"

        return True, None

    def requires_rationale(self, gap: Gap) -> bool:
        """Check if a gap requires rationale for approval."""
        if gap.severity == GapSeverity.WARNING:
            return True
        return gap.gap_type in self.rationale_required_types


# ─────────────────────────────────────────────────────────────────────────────
# Data Classes - Review
# ─────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ReviewRequest:
    """Request to review a generation run."""

    run_id: str
    decision: ReviewDecision
    rationale: str
    gap_rationales: list[GapRationale] = field(default_factory=list)


@dataclass(frozen=True)
class ReviewResult:
    """Result of a review operation."""

    success: bool
    run_id: str
    new_status: ApprovalStatus | None
    reviewer_id: str
    reviewed_at: datetime
    error: str | None = None
    row_version: int | None = None


@dataclass
class PreflightCheck:
    """Preflight check before review."""

    check_type: str
    passed: bool
    message: str
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class PreflightResult:
    """Result of preflight checks."""

    can_approve: bool
    checks: list[PreflightCheck] = field(default_factory=list)
    blockers: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    gaps: list[Gap] = field(default_factory=list)


# ─────────────────────────────────────────────────────────────────────────────
# Data Classes - Supersession
# ─────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class SupersessionRequest:
    """Request to supersede a run."""

    predecessor_run_id: str
    successor_run_id: str
    reason: str


@dataclass(frozen=True)
class SupersessionResult:
    """Result of a supersession operation."""

    success: bool
    predecessor_run_id: str
    successor_run_id: str
    superseded_at: datetime
    error: str | None = None


# ─────────────────────────────────────────────────────────────────────────────
# Data Classes - Audit
# ─────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class AuditEvent:
    """Audit event for topology operations."""

    event_id: str
    event_type: AuditEventType
    entity_type: str  # BASE_DIAGRAM, GENERATION_RUN, ARTIFACT
    entity_id: str
    actor_id: str
    actor_type: str
    timestamp: datetime
    old_state: str | None = None
    new_state: str | None = None
    details: dict[str, Any] = field(default_factory=dict)


def create_audit_event(
    event_type: AuditEventType,
    entity_type: str,
    entity_id: str,
    actor: Actor,
    old_state: str | None = None,
    new_state: str | None = None,
    details: dict[str, Any] | None = None,
) -> AuditEvent:
    """Create an audit event."""
    return AuditEvent(
        event_id=str(uuid.uuid4()),
        event_type=event_type,
        entity_type=entity_type,
        entity_id=entity_id,
        actor_id=actor.actor_id,
        actor_type=actor.actor_type,
        timestamp=datetime.now(tz=UTC),
        old_state=old_state,
        new_state=new_state,
        details=details or {},
    )


# ─────────────────────────────────────────────────────────────────────────────
# Preflight Checks
# ─────────────────────────────────────────────────────────────────────────────


def check_input_hash(
    run: dict[str, Any],
    expected_hash: str,
) -> PreflightCheck:
    """Verify input hash matches."""
    actual_hash = run.get("input_hash", "")
    passed = actual_hash == expected_hash
    return PreflightCheck(
        check_type="INPUT_HASH",
        passed=passed,
        message="Input hash verified" if passed else "Input hash mismatch",
        details={"expected": expected_hash, "actual": actual_hash},
    )


def check_official_mode(run: dict[str, Any]) -> PreflightCheck:
    """Verify run is in official mode."""
    mode = run.get("mode", "")
    passed = mode == "OFFICIAL_SNAPSHOT"
    return PreflightCheck(
        check_type="OFFICIAL_MODE",
        passed=passed,
        message="Official mode verified" if passed else "Run is not in official mode",
        details={"mode": mode},
    )


def check_readiness_status(run: dict[str, Any]) -> PreflightCheck:
    """Verify run passed readiness checks."""
    status = run.get("readiness_status", "")
    passed = status == "READY"
    return PreflightCheck(
        check_type="READINESS_STATUS",
        passed=passed,
        message="Readiness verified" if passed else "Run did not pass readiness checks",
        details={"status": status},
    )


def check_required_artifacts(run: dict[str, Any]) -> PreflightCheck:
    """Verify required artifacts are present."""
    diagram_id = run.get("diagram_artifact_id")
    report_id = run.get("report_artifact_id")
    manifest_id = run.get("manifest_artifact_id")

    missing = []
    if not diagram_id:
        missing.append("diagram")
    if not report_id:
        missing.append("report")
    if not manifest_id:
        missing.append("manifest")

    passed = len(missing) == 0
    return PreflightCheck(
        check_type="REQUIRED_ARTIFACTS",
        passed=passed,
        message="All artifacts present" if passed else f"Missing artifacts: {missing}",
        details={"missing": missing},
    )


def check_status_agreement(
    run: dict[str, Any],
    manifest: dict[str, Any] | None,
) -> PreflightCheck:
    """Verify manifest and database status agree."""
    db_status = run.get("status", "")
    manifest_status = manifest.get("status", "") if manifest else ""

    passed = db_status == manifest_status
    return PreflightCheck(
        check_type="STATUS_AGREEMENT",
        passed=passed,
        message="Status agreement verified" if passed else "Status mismatch",
        details={"db_status": db_status, "manifest_status": manifest_status},
    )


def run_preflight_checks(
    run: dict[str, Any],
    expected_input_hash: str | None = None,
    manifest: dict[str, Any] | None = None,
) -> PreflightResult:
    """Run all preflight checks before approval."""
    checks = []

    # Check official mode
    mode_check = check_official_mode(run)
    checks.append(mode_check)

    # Check readiness
    readiness_check = check_readiness_status(run)
    checks.append(readiness_check)

    # Check required artifacts
    artifacts_check = check_required_artifacts(run)
    checks.append(artifacts_check)

    # Check input hash if provided
    if expected_input_hash:
        hash_check = check_input_hash(run, expected_input_hash)
        checks.append(hash_check)

    # Check status agreement if manifest provided
    if manifest:
        status_check = check_status_agreement(run, manifest)
        checks.append(status_check)

    # Collect blockers and warnings
    blockers = [c.message for c in checks if not c.passed and c.check_type in (
        "OFFICIAL_MODE", "INPUT_HASH", "STATUS_AGREEMENT"
    )]
    warnings = [c.message for c in checks if not c.passed and c.check_type not in (
        "OFFICIAL_MODE", "INPUT_HASH", "STATUS_AGREEMENT"
    )]

    # Extract gaps from run
    gaps = []
    for gap_data in run.get("gaps", []):
        gaps.append(Gap(
            gap_id=gap_data.get("id", str(uuid.uuid4())),
            gap_type=gap_data.get("type", "UNKNOWN"),
            severity=GapSeverity(gap_data.get("severity", "WARNING")),
            message=gap_data.get("message", ""),
            slot_id=gap_data.get("slot_id"),
            marker=gap_data.get("marker"),
        ))

    # Check for blocker gaps
    policy = GapApprovalPolicy()
    for gap in gaps:
        can_approve, reason = policy.can_approve_gap(gap)
        if not can_approve:
            blockers.append(f"Gap {gap.gap_id}: {reason}")

    can_approve = len(blockers) == 0

    return PreflightResult(
        can_approve=can_approve,
        checks=checks,
        blockers=blockers,
        warnings=warnings,
        gaps=gaps,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Review Operations
# ─────────────────────────────────────────────────────────────────────────────


class ReviewError(Exception):
    """Error during review operation."""

    pass


class ConcurrencyError(ReviewError):
    """Concurrent modification detected."""

    pass


class AuthorizationError(ReviewError):
    """Authorization failed."""

    pass


def validate_review_request(
    request: ReviewRequest,
    run: dict[str, Any],
    policy: GapApprovalPolicy,
) -> tuple[bool, list[str]]:
    """Validate a review request."""
    errors = []

    # Check run is in pending status
    if run.get("approval_status") != "PENDING":
        errors.append(f"Run is not pending review: {run.get('approval_status')}")

    # Check run is completed
    if run.get("phase") != "COMPLETED":
        errors.append(f"Run is not completed: {run.get('phase')}")

    # For approval, check gaps
    if request.decision in (ReviewDecision.APPROVED, ReviewDecision.APPROVED_WITH_GAPS):
        gaps = run.get("gaps", [])
        for gap_data in gaps:
            gap = Gap(
                gap_id=gap_data.get("id", ""),
                gap_type=gap_data.get("type", ""),
                severity=GapSeverity(gap_data.get("severity", "WARNING")),
                message=gap_data.get("message", ""),
            )

            can_approve, reason = policy.can_approve_gap(gap)
            if not can_approve:
                errors.append(f"Cannot approve gap {gap.gap_id}: {reason}")

            # Check rationale provided for gaps requiring it
            if policy.requires_rationale(gap):
                has_rationale = any(
                    r.gap_id == gap.gap_id for r in request.gap_rationales
                )
                if not has_rationale:
                    errors.append(f"Gap {gap.gap_id} requires rationale")

    return len(errors) == 0, errors


def create_review_result(
    request: ReviewRequest,
    actor: Actor,
    success: bool,
    error: str | None = None,
    row_version: int | None = None,
) -> ReviewResult:
    """Create a review result."""
    new_status = None
    if success:
        if request.decision == ReviewDecision.APPROVED:
            new_status = ApprovalStatus.APPROVED
        elif request.decision == ReviewDecision.REJECTED:
            new_status = ApprovalStatus.REJECTED
        elif request.decision == ReviewDecision.APPROVED_WITH_GAPS:
            new_status = ApprovalStatus.APPROVED

    return ReviewResult(
        success=success,
        run_id=request.run_id,
        new_status=new_status,
        reviewer_id=actor.actor_id,
        reviewed_at=datetime.now(tz=UTC),
        error=error,
        row_version=row_version,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Supersession Operations
# ─────────────────────────────────────────────────────────────────────────────


def validate_supersession(
    predecessor: dict[str, Any],
    successor: dict[str, Any],
) -> tuple[bool, list[str]]:
    """Validate a supersession request."""
    errors = []

    # Predecessor must be approved
    if predecessor.get("approval_status") != "APPROVED":
        errors.append("Predecessor must be approved to be superseded")

    # Successor must be approved
    if successor.get("approval_status") != "APPROVED":
        errors.append("Successor must be approved to supersede")

    # Must be for same intake
    if predecessor.get("intake_id") != successor.get("intake_id"):
        errors.append("Predecessor and successor must be for same intake")

    # Predecessor must not already be superseded
    if predecessor.get("approval_status") == "SUPERSEDED":
        errors.append("Predecessor is already superseded")

    return len(errors) == 0, errors


def create_supersession_result(
    request: SupersessionRequest,
    success: bool,
    error: str | None = None,
) -> SupersessionResult:
    """Create a supersession result."""
    return SupersessionResult(
        success=success,
        predecessor_run_id=request.predecessor_run_id,
        successor_run_id=request.successor_run_id,
        superseded_at=datetime.now(tz=UTC),
        error=error,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Download Validation
# ─────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class DownloadValidation:
    """Validation result for artifact download."""

    valid: bool
    artifact_id: str
    content_hash: str | None = None
    error: str | None = None


def validate_artifact_download(
    artifact: dict[str, Any],
    run: dict[str, Any],
) -> DownloadValidation:
    """Validate an artifact can be downloaded."""
    artifact_id = artifact.get("id", "")

    # Check artifact exists
    if not artifact:
        return DownloadValidation(
            valid=False,
            artifact_id=artifact_id,
            error="Artifact not found",
        )

    # Check artifact belongs to run
    if artifact.get("generation_run_id") != run.get("id"):
        return DownloadValidation(
            valid=False,
            artifact_id=artifact_id,
            error="Artifact does not belong to run",
        )

    # Check run is not tampered
    expected_hash = artifact.get("sha256_hex")
    if not expected_hash:
        return DownloadValidation(
            valid=False,
            artifact_id=artifact_id,
            error="Artifact hash not recorded",
        )

    return DownloadValidation(
        valid=True,
        artifact_id=artifact_id,
        content_hash=expected_hash,
    )


def verify_artifact_content(
    content: bytes,
    expected_hash: str,
) -> bool:
    """Verify artifact content matches expected hash."""
    actual_hash = hashlib.sha256(content).hexdigest()
    return actual_hash == expected_hash


# ─────────────────────────────────────────────────────────────────────────────
# Error Handling
# ─────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class SafeError:
    """Safe error response that doesn't leak sensitive information."""

    error_code: str
    message: str
    request_id: str


# Error codes
ERROR_NOT_FOUND = "NOT_FOUND"
ERROR_UNAUTHORIZED = "UNAUTHORIZED"
ERROR_CONFLICT = "CONFLICT"
ERROR_VALIDATION = "VALIDATION_ERROR"
ERROR_INTERNAL = "INTERNAL_ERROR"


def create_safe_error(
    error_code: str,
    message: str,
) -> SafeError:
    """Create a safe error response."""
    return SafeError(
        error_code=error_code,
        message=message,
        request_id=str(uuid.uuid4()),
    )
