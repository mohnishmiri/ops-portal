"""
Tests for P10: Approval and UI.

Tests the approval workflow for topology generation:
- Capability-based authorization
- Run review with compare-and-set transitions
- Gap approval policy
- Supersession management
- Audit event generation
- Preflight checks
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest

from migration_intake.topology.approval import (
    Actor,
    ApprovalStatus,
    AuditEvent,
    AuditEventType,
    AuthorizationResult,
    Capability,
    ConcurrencyError,
    DownloadValidation,
    ERROR_CONFLICT,
    ERROR_NOT_FOUND,
    ERROR_UNAUTHORIZED,
    ERROR_VALIDATION,
    Gap,
    GapApprovalPolicy,
    GapRationale,
    GapSeverity,
    PreflightCheck,
    PreflightResult,
    ReviewDecision,
    ReviewError,
    ReviewRequest,
    ReviewResult,
    SafeError,
    SupersessionRequest,
    SupersessionResult,
    check_authorization,
    check_input_hash,
    check_official_mode,
    check_readiness_status,
    check_required_artifacts,
    check_status_agreement,
    create_audit_event,
    create_review_result,
    create_safe_error,
    create_supersession_result,
    run_preflight_checks,
    validate_artifact_download,
    validate_review_request,
    validate_supersession,
    verify_artifact_content,
)


# ─────────────────────────────────────────────────────────────────────────────
# Test Fixtures
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture
def admin_actor() -> Actor:
    """Actor with all capabilities."""
    return Actor(
        actor_id="admin-123",
        actor_type="USER",
        capabilities=frozenset(Capability),
    )


@pytest.fixture
def reviewer_actor() -> Actor:
    """Actor with review capabilities only."""
    return Actor(
        actor_id="reviewer-456",
        actor_type="USER",
        capabilities=frozenset([
            Capability.APPROVE_RUN,
            Capability.REJECT_RUN,
            Capability.DOWNLOAD_ARTIFACTS,
        ]),
    )


@pytest.fixture
def viewer_actor() -> Actor:
    """Actor with download capability only."""
    return Actor(
        actor_id="viewer-789",
        actor_type="USER",
        capabilities=frozenset([Capability.DOWNLOAD_ARTIFACTS]),
    )


@pytest.fixture
def completed_run() -> dict:
    """A completed generation run."""
    return {
        "id": str(uuid.uuid4()),
        "intake_id": str(uuid.uuid4()),
        "mode": "OFFICIAL_SNAPSHOT",
        "phase": "COMPLETED",
        "approval_status": "PENDING",
        "input_hash": "abc123def456",
        "readiness_status": "READY",
        "diagram_artifact_id": str(uuid.uuid4()),
        "report_artifact_id": str(uuid.uuid4()),
        "manifest_artifact_id": str(uuid.uuid4()),
        "status": "READY_FOR_REVIEW",
        "gaps": [],
    }


@pytest.fixture
def run_with_gaps() -> dict:
    """A completed run with gaps."""
    return {
        "id": str(uuid.uuid4()),
        "intake_id": str(uuid.uuid4()),
        "mode": "OFFICIAL_SNAPSHOT",
        "phase": "COMPLETED",
        "approval_status": "PENDING",
        "input_hash": "abc123def456",
        "readiness_status": "READY",
        "diagram_artifact_id": str(uuid.uuid4()),
        "report_artifact_id": str(uuid.uuid4()),
        "manifest_artifact_id": str(uuid.uuid4()),
        "status": "GENERATED_WITH_GAPS",
        "gaps": [
            {
                "id": "gap-1",
                "type": "UNRESOLVED_MARKER",
                "severity": "WARNING",
                "message": "Marker {{APP_NAME}} not resolved",
                "marker": "{{APP_NAME}}",
            },
        ],
    }


# ─────────────────────────────────────────────────────────────────────────────
# Test: Capabilities
# ─────────────────────────────────────────────────────────────────────────────


class TestCapabilities:
    """Test capability enum."""

    def test_all_capabilities_defined(self) -> None:
        """All expected capabilities are defined."""
        caps = [c.value for c in Capability]
        assert "topology:base:upload" in caps
        assert "topology:run:approve" in caps
        assert "topology:artifacts:download" in caps

    def test_capability_count(self) -> None:
        """Expected number of capabilities."""
        assert len(Capability) == 9


# ─────────────────────────────────────────────────────────────────────────────
# Test: Authorization
# ─────────────────────────────────────────────────────────────────────────────


class TestAuthorization:
    """Test authorization checks."""

    def test_authorized_with_capability(self, admin_actor: Actor) -> None:
        """Actor with capability is authorized."""
        result = check_authorization(admin_actor, Capability.APPROVE_RUN)
        assert result.authorized is True
        assert result.reason is None

    def test_unauthorized_without_capability(self, viewer_actor: Actor) -> None:
        """Actor without capability is not authorized."""
        result = check_authorization(viewer_actor, Capability.APPROVE_RUN)
        assert result.authorized is False
        assert "Missing capability" in result.reason

    def test_authorization_result_includes_actor(self, admin_actor: Actor) -> None:
        """Authorization result includes actor ID."""
        result = check_authorization(admin_actor, Capability.APPROVE_RUN)
        assert result.actor_id == admin_actor.actor_id


# ─────────────────────────────────────────────────────────────────────────────
# Test: Gap Policy
# ─────────────────────────────────────────────────────────────────────────────


class TestGapPolicy:
    """Test gap approval policy."""

    def test_blocker_gap_not_approvable(self) -> None:
        """Blocker gaps cannot be approved."""
        policy = GapApprovalPolicy()
        gap = Gap(
            gap_id="gap-1",
            gap_type="MISSING_REQUIRED_SLOT",
            severity=GapSeverity.BLOCKER,
            message="Required slot missing",
        )

        can_approve, reason = policy.can_approve_gap(gap)
        assert can_approve is False
        assert "Blocker" in reason

    def test_warning_gap_approvable(self) -> None:
        """Warning gaps can be approved."""
        policy = GapApprovalPolicy()
        gap = Gap(
            gap_id="gap-1",
            gap_type="UNRESOLVED_MARKER",
            severity=GapSeverity.WARNING,
            message="Marker not resolved",
        )

        can_approve, reason = policy.can_approve_gap(gap)
        assert can_approve is True

    def test_warning_requires_rationale(self) -> None:
        """Warning gaps require rationale."""
        policy = GapApprovalPolicy()
        gap = Gap(
            gap_id="gap-1",
            gap_type="UNRESOLVED_MARKER",
            severity=GapSeverity.WARNING,
            message="Marker not resolved",
        )

        assert policy.requires_rationale(gap) is True

    def test_info_gap_no_rationale(self) -> None:
        """Info gaps don't require rationale."""
        policy = GapApprovalPolicy()
        gap = Gap(
            gap_id="gap-1",
            gap_type="STYLE_SUGGESTION",
            severity=GapSeverity.INFO,
            message="Consider using title case",
        )

        assert policy.requires_rationale(gap) is False


# ─────────────────────────────────────────────────────────────────────────────
# Test: Preflight Checks
# ─────────────────────────────────────────────────────────────────────────────


class TestPreflightChecks:
    """Test preflight checks before approval."""

    def test_check_official_mode_passes(self, completed_run: dict) -> None:
        """Official mode check passes for official run."""
        result = check_official_mode(completed_run)
        assert result.passed is True

    def test_check_official_mode_fails_preview(self) -> None:
        """Official mode check fails for preview run."""
        run = {"mode": "DRAFT_PREVIEW"}
        result = check_official_mode(run)
        assert result.passed is False

    def test_check_readiness_passes(self, completed_run: dict) -> None:
        """Readiness check passes for ready run."""
        result = check_readiness_status(completed_run)
        assert result.passed is True

    def test_check_readiness_fails(self) -> None:
        """Readiness check fails for not ready run."""
        run = {"readiness_status": "NOT_READY"}
        result = check_readiness_status(run)
        assert result.passed is False

    def test_check_required_artifacts_passes(self, completed_run: dict) -> None:
        """Required artifacts check passes when all present."""
        result = check_required_artifacts(completed_run)
        assert result.passed is True

    def test_check_required_artifacts_fails(self) -> None:
        """Required artifacts check fails when missing."""
        run = {"diagram_artifact_id": "123"}
        result = check_required_artifacts(run)
        assert result.passed is False
        assert "report" in result.details["missing"]

    def test_check_input_hash_passes(self, completed_run: dict) -> None:
        """Input hash check passes when matching."""
        result = check_input_hash(completed_run, "abc123def456")
        assert result.passed is True

    def test_check_input_hash_fails(self, completed_run: dict) -> None:
        """Input hash check fails when mismatched."""
        result = check_input_hash(completed_run, "wrong_hash")
        assert result.passed is False

    def test_check_status_agreement_passes(self, completed_run: dict) -> None:
        """Status agreement check passes when matching."""
        manifest = {"status": "READY_FOR_REVIEW"}
        result = check_status_agreement(completed_run, manifest)
        assert result.passed is True

    def test_check_status_agreement_fails(self, completed_run: dict) -> None:
        """Status agreement check fails when mismatched."""
        manifest = {"status": "FAILED"}
        result = check_status_agreement(completed_run, manifest)
        assert result.passed is False


class TestPreflightResult:
    """Test combined preflight result."""

    def test_all_checks_pass(self, completed_run: dict) -> None:
        """All checks pass for valid run."""
        manifest = {"status": "READY_FOR_REVIEW"}
        result = run_preflight_checks(
            run=completed_run,
            expected_input_hash="abc123def456",
            manifest=manifest,
        )

        assert result.can_approve is True
        assert len(result.blockers) == 0

    def test_blocker_prevents_approval(self) -> None:
        """Blocker prevents approval."""
        run = {
            "mode": "DRAFT_PREVIEW",
            "phase": "COMPLETED",
            "approval_status": "PENDING",
            "readiness_status": "READY",
            "gaps": [],
        }
        result = run_preflight_checks(run=run)

        assert result.can_approve is False
        assert len(result.blockers) > 0

    def test_gap_blocker_prevents_approval(self) -> None:
        """Blocker gap prevents approval."""
        run = {
            "mode": "OFFICIAL_SNAPSHOT",
            "phase": "COMPLETED",
            "approval_status": "PENDING",
            "readiness_status": "READY",
            "diagram_artifact_id": "123",
            "report_artifact_id": "456",
            "manifest_artifact_id": "789",
            "gaps": [
                {
                    "id": "gap-1",
                    "type": "MISSING_REQUIRED_SLOT",
                    "severity": "BLOCKER",
                    "message": "Required slot missing",
                },
            ],
        }
        result = run_preflight_checks(run=run)

        assert result.can_approve is False
        assert any("gap" in b.lower() for b in result.blockers)


# ─────────────────────────────────────────────────────────────────────────────
# Test: Review Validation
# ─────────────────────────────────────────────────────────────────────────────


class TestReviewValidation:
    """Test review request validation."""

    def test_valid_approval_request(self, completed_run: dict) -> None:
        """Valid approval request passes validation."""
        request = ReviewRequest(
            run_id=completed_run["id"],
            decision=ReviewDecision.APPROVED,
            rationale="Looks good",
        )
        policy = GapApprovalPolicy()

        valid, errors = validate_review_request(request, completed_run, policy)
        assert valid is True
        assert len(errors) == 0

    def test_reject_non_pending_run(self, completed_run: dict) -> None:
        """Cannot review non-pending run."""
        completed_run["approval_status"] = "APPROVED"
        request = ReviewRequest(
            run_id=completed_run["id"],
            decision=ReviewDecision.APPROVED,
            rationale="Looks good",
        )
        policy = GapApprovalPolicy()

        valid, errors = validate_review_request(request, completed_run, policy)
        assert valid is False
        assert any("pending" in e.lower() for e in errors)

    def test_reject_incomplete_run(self, completed_run: dict) -> None:
        """Cannot review incomplete run."""
        completed_run["phase"] = "RENDERING"
        request = ReviewRequest(
            run_id=completed_run["id"],
            decision=ReviewDecision.APPROVED,
            rationale="Looks good",
        )
        policy = GapApprovalPolicy()

        valid, errors = validate_review_request(request, completed_run, policy)
        assert valid is False
        assert any("completed" in e.lower() for e in errors)

    def test_gap_requires_rationale(self, run_with_gaps: dict) -> None:
        """Gap approval requires rationale."""
        request = ReviewRequest(
            run_id=run_with_gaps["id"],
            decision=ReviewDecision.APPROVED_WITH_GAPS,
            rationale="Approving with gaps",
            gap_rationales=[],  # Missing rationale
        )
        policy = GapApprovalPolicy()

        valid, errors = validate_review_request(request, run_with_gaps, policy)
        assert valid is False
        assert any("rationale" in e.lower() for e in errors)

    def test_gap_with_rationale_valid(self, run_with_gaps: dict) -> None:
        """Gap approval with rationale is valid."""
        request = ReviewRequest(
            run_id=run_with_gaps["id"],
            decision=ReviewDecision.APPROVED_WITH_GAPS,
            rationale="Approving with gaps",
            gap_rationales=[
                GapRationale(
                    gap_id="gap-1",
                    rationale="Marker will be filled manually",
                    approved_by="reviewer-123",
                    approved_at=datetime.now(tz=timezone.utc),
                ),
            ],
        )
        policy = GapApprovalPolicy()

        valid, errors = validate_review_request(request, run_with_gaps, policy)
        assert valid is True


# ─────────────────────────────────────────────────────────────────────────────
# Test: Review Result
# ─────────────────────────────────────────────────────────────────────────────


class TestReviewResult:
    """Test review result creation."""

    def test_successful_approval(self, reviewer_actor: Actor) -> None:
        """Successful approval creates correct result."""
        request = ReviewRequest(
            run_id="run-123",
            decision=ReviewDecision.APPROVED,
            rationale="Looks good",
        )

        result = create_review_result(request, reviewer_actor, success=True)

        assert result.success is True
        assert result.new_status == ApprovalStatus.APPROVED
        assert result.reviewer_id == reviewer_actor.actor_id
        assert result.error is None

    def test_successful_rejection(self, reviewer_actor: Actor) -> None:
        """Successful rejection creates correct result."""
        request = ReviewRequest(
            run_id="run-123",
            decision=ReviewDecision.REJECTED,
            rationale="Issues found",
        )

        result = create_review_result(request, reviewer_actor, success=True)

        assert result.success is True
        assert result.new_status == ApprovalStatus.REJECTED

    def test_failed_review(self, reviewer_actor: Actor) -> None:
        """Failed review creates error result."""
        request = ReviewRequest(
            run_id="run-123",
            decision=ReviewDecision.APPROVED,
            rationale="Looks good",
        )

        result = create_review_result(
            request, reviewer_actor, success=False, error="Concurrent modification"
        )

        assert result.success is False
        assert result.new_status is None
        assert result.error == "Concurrent modification"


# ─────────────────────────────────────────────────────────────────────────────
# Test: Supersession
# ─────────────────────────────────────────────────────────────────────────────


class TestSupersession:
    """Test supersession validation."""

    def test_valid_supersession(self) -> None:
        """Valid supersession passes validation."""
        intake_id = str(uuid.uuid4())
        predecessor = {
            "id": "run-1",
            "intake_id": intake_id,
            "approval_status": "APPROVED",
        }
        successor = {
            "id": "run-2",
            "intake_id": intake_id,
            "approval_status": "APPROVED",
        }

        valid, errors = validate_supersession(predecessor, successor)
        assert valid is True

    def test_predecessor_must_be_approved(self) -> None:
        """Predecessor must be approved."""
        intake_id = str(uuid.uuid4())
        predecessor = {
            "id": "run-1",
            "intake_id": intake_id,
            "approval_status": "PENDING",
        }
        successor = {
            "id": "run-2",
            "intake_id": intake_id,
            "approval_status": "APPROVED",
        }

        valid, errors = validate_supersession(predecessor, successor)
        assert valid is False
        assert any("predecessor" in e.lower() for e in errors)

    def test_successor_must_be_approved(self) -> None:
        """Successor must be approved."""
        intake_id = str(uuid.uuid4())
        predecessor = {
            "id": "run-1",
            "intake_id": intake_id,
            "approval_status": "APPROVED",
        }
        successor = {
            "id": "run-2",
            "intake_id": intake_id,
            "approval_status": "PENDING",
        }

        valid, errors = validate_supersession(predecessor, successor)
        assert valid is False
        assert any("successor" in e.lower() for e in errors)

    def test_same_intake_required(self) -> None:
        """Predecessor and successor must be for same intake."""
        predecessor = {
            "id": "run-1",
            "intake_id": str(uuid.uuid4()),
            "approval_status": "APPROVED",
        }
        successor = {
            "id": "run-2",
            "intake_id": str(uuid.uuid4()),
            "approval_status": "APPROVED",
        }

        valid, errors = validate_supersession(predecessor, successor)
        assert valid is False
        assert any("intake" in e.lower() for e in errors)

    def test_already_superseded(self) -> None:
        """Cannot supersede already superseded run."""
        intake_id = str(uuid.uuid4())
        predecessor = {
            "id": "run-1",
            "intake_id": intake_id,
            "approval_status": "SUPERSEDED",
        }
        successor = {
            "id": "run-2",
            "intake_id": intake_id,
            "approval_status": "APPROVED",
        }

        valid, errors = validate_supersession(predecessor, successor)
        assert valid is False


# ─────────────────────────────────────────────────────────────────────────────
# Test: Audit Events
# ─────────────────────────────────────────────────────────────────────────────


class TestAuditEvents:
    """Test audit event creation."""

    def test_create_audit_event(self, admin_actor: Actor) -> None:
        """Audit event is created with correct fields."""
        event = create_audit_event(
            event_type=AuditEventType.RUN_APPROVED,
            entity_type="GENERATION_RUN",
            entity_id="run-123",
            actor=admin_actor,
            old_state="PENDING",
            new_state="APPROVED",
            details={"rationale": "Looks good"},
        )

        assert event.event_id is not None
        assert event.event_type == AuditEventType.RUN_APPROVED
        assert event.entity_type == "GENERATION_RUN"
        assert event.entity_id == "run-123"
        assert event.actor_id == admin_actor.actor_id
        assert event.old_state == "PENDING"
        assert event.new_state == "APPROVED"
        assert event.details["rationale"] == "Looks good"

    def test_audit_event_types(self) -> None:
        """All expected audit event types are defined."""
        types = [t.value for t in AuditEventType]
        assert "RUN_APPROVED" in types
        assert "RUN_REJECTED" in types
        assert "RUN_SUPERSEDED" in types
        assert "BASE_APPROVED" in types


# ─────────────────────────────────────────────────────────────────────────────
# Test: Download Validation
# ─────────────────────────────────────────────────────────────────────────────


class TestDownloadValidation:
    """Test artifact download validation."""

    def test_valid_download(self) -> None:
        """Valid artifact can be downloaded."""
        run_id = str(uuid.uuid4())
        artifact = {
            "id": "artifact-123",
            "generation_run_id": run_id,
            "sha256_hex": "abc123",
        }
        run = {"id": run_id}

        result = validate_artifact_download(artifact, run)
        assert result.valid is True
        assert result.content_hash == "abc123"

    def test_artifact_not_found(self) -> None:
        """Missing artifact fails validation."""
        run = {"id": "run-123"}

        result = validate_artifact_download({}, run)
        assert result.valid is False
        assert "not found" in result.error.lower()

    def test_artifact_wrong_run(self) -> None:
        """Artifact from different run fails validation."""
        artifact = {
            "id": "artifact-123",
            "generation_run_id": "other-run",
            "sha256_hex": "abc123",
        }
        run = {"id": "run-123"}

        result = validate_artifact_download(artifact, run)
        assert result.valid is False
        assert "belong" in result.error.lower()

    def test_verify_content_hash(self) -> None:
        """Content hash verification works."""
        content = b"test content"
        import hashlib
        expected = hashlib.sha256(content).hexdigest()

        assert verify_artifact_content(content, expected) is True
        assert verify_artifact_content(content, "wrong_hash") is False


# ─────────────────────────────────────────────────────────────────────────────
# Test: Safe Errors
# ─────────────────────────────────────────────────────────────────────────────


class TestSafeErrors:
    """Test safe error handling."""

    def test_create_safe_error(self) -> None:
        """Safe error is created with request ID."""
        error = create_safe_error(ERROR_NOT_FOUND, "Resource not found")

        assert error.error_code == ERROR_NOT_FOUND
        assert error.message == "Resource not found"
        assert error.request_id is not None

    def test_error_codes_defined(self) -> None:
        """All expected error codes are defined."""
        assert ERROR_NOT_FOUND == "NOT_FOUND"
        assert ERROR_UNAUTHORIZED == "UNAUTHORIZED"
        assert ERROR_CONFLICT == "CONFLICT"
        assert ERROR_VALIDATION == "VALIDATION_ERROR"
