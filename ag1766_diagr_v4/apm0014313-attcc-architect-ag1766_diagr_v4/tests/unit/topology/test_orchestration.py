"""
Tests for P8: Orchestration and Pinning.

Tests the orchestration layer for topology generation:
- Generation modes (OFFICIAL_SNAPSHOT, DRAFT_PREVIEW)
- Immutable input records
- Readiness checks
- Idempotency fingerprinting
- Run phase transitions
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

import pytest

from migration_intake.topology.orchestration import (
    GenerationMode,
    GenerationRun,
    IdempotencyKey,
    IdempotencyError,
    ReadinessCheck,
    ReadinessResult,
    ReadinessStatus,
    RunPhase,
    TopologyInputRecord,
    can_approve_run,
    check_base_readiness,
    check_data_readiness,
    check_profile_readiness,
    check_storage_readiness,
    compute_idempotency_key,
    compute_input_hash,
    create_generation_run,
    create_input_record,
    run_readiness_checks,
    transition_run_phase,
)


# ─────────────────────────────────────────────────────────────────────────────
# Test Fixtures
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture
def sample_projection() -> dict:
    """Sample projection data."""
    return {
        "schema_version": "2.0.0",
        "projection_hash": "abc123",
        "snapshot_id": str(uuid.uuid4()),
        "identifiers": {
            "application_id": str(uuid.uuid4()),
            "application_acronym": "TEST",
        },
        "confirmed_answers": {},
        "target_resources": [],
    }


@pytest.fixture
def sample_base_diagram() -> dict:
    """Sample base diagram data."""
    return {
        "id": str(uuid.uuid4()),
        "state": "APPROVED",
        "sha256_hex": "def456",
        "profile_id": "CCPM_OUTPOST_V1",
        "profile_version": "1.0.0",
    }


class MockProfile:
    """Mock profile for testing."""

    class Manifest:
        min_projection_version = "1.0.0"
        max_projection_version = "999.x"

    manifest = Manifest()


# ─────────────────────────────────────────────────────────────────────────────
# Test: Generation Modes
# ─────────────────────────────────────────────────────────────────────────────


class TestGenerationModes:
    """Test generation mode enum."""

    def test_official_snapshot_mode(self) -> None:
        """Official snapshot mode uses frozen snapshot."""
        mode = GenerationMode.OFFICIAL_SNAPSHOT
        assert mode.value == "OFFICIAL_SNAPSHOT"

    def test_draft_preview_mode(self) -> None:
        """Draft preview mode uses current canonical heads."""
        mode = GenerationMode.DRAFT_PREVIEW
        assert mode.value == "DRAFT_PREVIEW"

    def test_modes_are_distinct(self) -> None:
        """Modes are distinct values."""
        assert GenerationMode.OFFICIAL_SNAPSHOT != GenerationMode.DRAFT_PREVIEW


# ─────────────────────────────────────────────────────────────────────────────
# Test: Run Phases
# ─────────────────────────────────────────────────────────────────────────────


class TestRunPhases:
    """Test run phase enum."""

    def test_all_phases_defined(self) -> None:
        """All expected phases are defined."""
        phases = [p.value for p in RunPhase]
        assert "PENDING" in phases
        assert "CAPTURING" in phases
        assert "RENDERING" in phases
        assert "STORING" in phases
        assert "VERIFYING" in phases
        assert "COMPLETED" in phases
        assert "FAILED" in phases

    def test_phase_count(self) -> None:
        """Expected number of phases."""
        assert len(RunPhase) == 7


# ─────────────────────────────────────────────────────────────────────────────
# Test: Input Hash Computation
# ─────────────────────────────────────────────────────────────────────────────


class TestInputHash:
    """Test input hash computation."""

    def test_compute_input_hash(self) -> None:
        """Input hash is computed from all inputs."""
        hash1 = compute_input_hash(
            mode=GenerationMode.OFFICIAL_SNAPSHOT,
            projection_hash="proj123",
            snapshot_hash="snap456",
            catalog_hash="cat789",
            base_hash="base000",
            profile_hash="prof111",
            environment="PROD",
            site="DFW",
            variant="STANDARD",
        )
        assert len(hash1) == 64  # SHA-256 hex

    def test_same_inputs_same_hash(self) -> None:
        """Same inputs produce same hash."""
        kwargs = {
            "mode": GenerationMode.OFFICIAL_SNAPSHOT,
            "projection_hash": "proj123",
            "snapshot_hash": "snap456",
            "catalog_hash": "cat789",
            "base_hash": "base000",
            "profile_hash": "prof111",
            "environment": "PROD",
            "site": "DFW",
            "variant": "STANDARD",
        }
        hash1 = compute_input_hash(**kwargs)
        hash2 = compute_input_hash(**kwargs)
        assert hash1 == hash2

    def test_different_mode_different_hash(self) -> None:
        """Different mode produces different hash."""
        common = {
            "projection_hash": "proj123",
            "snapshot_hash": "snap456",
            "catalog_hash": "cat789",
            "base_hash": "base000",
            "profile_hash": "prof111",
            "environment": "PROD",
            "site": "DFW",
            "variant": "STANDARD",
        }
        hash1 = compute_input_hash(mode=GenerationMode.OFFICIAL_SNAPSHOT, **common)
        hash2 = compute_input_hash(mode=GenerationMode.DRAFT_PREVIEW, **common)
        assert hash1 != hash2

    def test_different_environment_different_hash(self) -> None:
        """Different environment produces different hash."""
        common = {
            "mode": GenerationMode.OFFICIAL_SNAPSHOT,
            "projection_hash": "proj123",
            "snapshot_hash": "snap456",
            "catalog_hash": "cat789",
            "base_hash": "base000",
            "profile_hash": "prof111",
            "site": "DFW",
            "variant": "STANDARD",
        }
        hash1 = compute_input_hash(environment="PROD", **common)
        hash2 = compute_input_hash(environment="DEV", **common)
        assert hash1 != hash2


# ─────────────────────────────────────────────────────────────────────────────
# Test: Input Record Creation
# ─────────────────────────────────────────────────────────────────────────────


class TestInputRecord:
    """Test topology input record creation."""

    def test_create_input_record(self) -> None:
        """Input record is created with all fields."""
        now = datetime.now(tz=timezone.utc)
        record = create_input_record(
            mode=GenerationMode.OFFICIAL_SNAPSHOT,
            projection_json='{"test": true}',
            projection_hash="proj123",
            projection_schema_version="2.0.0",
            snapshot_id="snap-id",
            snapshot_hash="snap456",
            catalog_id="cat-id",
            catalog_version="1.0.0",
            catalog_hash="cat789",
            base_diagram_id="base-id",
            base_diagram_hash="base000",
            profile_id="CCPM_OUTPOST_V1",
            profile_version="1.0.0",
            profile_hash="prof111",
            environment="PROD",
            site="DFW",
            variant="STANDARD",
            created_by="user-123",
            created_at=now,
        )

        assert record.input_id is not None
        assert len(record.input_hash) == 64
        assert record.mode == GenerationMode.OFFICIAL_SNAPSHOT
        assert record.projection_hash == "proj123"
        assert record.snapshot_id == "snap-id"
        assert record.environment == "PROD"
        assert record.created_by == "user-123"

    def test_input_record_is_frozen(self) -> None:
        """Input record is immutable."""
        now = datetime.now(tz=timezone.utc)
        record = create_input_record(
            mode=GenerationMode.OFFICIAL_SNAPSHOT,
            projection_json='{"test": true}',
            projection_hash="proj123",
            projection_schema_version="2.0.0",
            snapshot_id="snap-id",
            snapshot_hash="snap456",
            catalog_id="cat-id",
            catalog_version="1.0.0",
            catalog_hash="cat789",
            base_diagram_id="base-id",
            base_diagram_hash="base000",
            profile_id="CCPM_OUTPOST_V1",
            profile_version="1.0.0",
            profile_hash="prof111",
            environment="PROD",
            site="DFW",
            variant="STANDARD",
            created_by="user-123",
            created_at=now,
        )

        with pytest.raises(AttributeError):
            record.environment = "DEV"  # type: ignore


# ─────────────────────────────────────────────────────────────────────────────
# Test: Idempotency Key
# ─────────────────────────────────────────────────────────────────────────────


class TestIdempotencyKey:
    """Test idempotency key computation."""

    def test_compute_idempotency_key(self) -> None:
        """Idempotency key is computed from mode, hashes, and version."""
        key = compute_idempotency_key(
            mode=GenerationMode.OFFICIAL_SNAPSHOT,
            projection_hash="proj123",
            base_hash="base000",
            profile_hash="prof111",
        )

        assert key.mode == GenerationMode.OFFICIAL_SNAPSHOT
        assert key.projection_hash == "proj123"
        assert key.base_hash == "base000"
        assert key.profile_hash == "prof111"

    def test_same_inputs_same_fingerprint(self) -> None:
        """Same inputs produce same fingerprint."""
        key1 = compute_idempotency_key(
            mode=GenerationMode.OFFICIAL_SNAPSHOT,
            projection_hash="proj123",
            base_hash="base000",
            profile_hash="prof111",
        )
        key2 = compute_idempotency_key(
            mode=GenerationMode.OFFICIAL_SNAPSHOT,
            projection_hash="proj123",
            base_hash="base000",
            profile_hash="prof111",
        )

        assert key1.compute_fingerprint() == key2.compute_fingerprint()

    def test_different_mode_different_fingerprint(self) -> None:
        """Different mode produces different fingerprint."""
        key1 = compute_idempotency_key(
            mode=GenerationMode.OFFICIAL_SNAPSHOT,
            projection_hash="proj123",
            base_hash="base000",
            profile_hash="prof111",
        )
        key2 = compute_idempotency_key(
            mode=GenerationMode.DRAFT_PREVIEW,
            projection_hash="proj123",
            base_hash="base000",
            profile_hash="prof111",
        )

        assert key1.compute_fingerprint() != key2.compute_fingerprint()


# ─────────────────────────────────────────────────────────────────────────────
# Test: Readiness Checks
# ─────────────────────────────────────────────────────────────────────────────


class TestDataReadiness:
    """Test data readiness checks."""

    def test_ready_with_identifiers(self, sample_projection: dict) -> None:
        """Data is ready when projection has identifiers."""
        result = check_data_readiness(sample_projection, GenerationMode.OFFICIAL_SNAPSHOT)
        assert result.status == ReadinessStatus.READY

    def test_not_ready_without_identifiers(self) -> None:
        """Data is not ready without identifiers."""
        projection = {"schema_version": "2.0.0"}
        result = check_data_readiness(projection, GenerationMode.OFFICIAL_SNAPSHOT)
        assert result.status == ReadinessStatus.NOT_READY
        assert "identifiers" in result.message.lower()

    def test_official_requires_snapshot(self) -> None:
        """Official mode requires snapshot reference."""
        projection = {"identifiers": {"app_id": "123"}}
        result = check_data_readiness(projection, GenerationMode.OFFICIAL_SNAPSHOT)
        assert result.status == ReadinessStatus.NOT_READY
        assert "snapshot" in result.message.lower()


class TestBaseReadiness:
    """Test base diagram readiness checks."""

    def test_official_requires_approved(self) -> None:
        """Official mode requires APPROVED base."""
        base = {"state": "COMPATIBLE"}
        result = check_base_readiness(base, GenerationMode.OFFICIAL_SNAPSHOT)
        assert result.status == ReadinessStatus.BLOCKED
        assert "APPROVED" in result.message

    def test_official_with_approved(self) -> None:
        """Official mode accepts APPROVED base."""
        base = {"state": "APPROVED"}
        result = check_base_readiness(base, GenerationMode.OFFICIAL_SNAPSHOT)
        assert result.status == ReadinessStatus.READY

    def test_preview_accepts_compatible(self) -> None:
        """Preview mode accepts COMPATIBLE base."""
        base = {"state": "COMPATIBLE"}
        result = check_base_readiness(base, GenerationMode.DRAFT_PREVIEW)
        assert result.status == ReadinessStatus.READY

    def test_preview_accepts_approved(self) -> None:
        """Preview mode accepts APPROVED base."""
        base = {"state": "APPROVED"}
        result = check_base_readiness(base, GenerationMode.DRAFT_PREVIEW)
        assert result.status == ReadinessStatus.READY

    def test_preview_rejects_draft(self) -> None:
        """Preview mode rejects DRAFT base."""
        base = {"state": "UPLOADED_DRAFT"}
        result = check_base_readiness(base, GenerationMode.DRAFT_PREVIEW)
        assert result.status == ReadinessStatus.NOT_READY


class TestProfileReadiness:
    """Test profile readiness checks."""

    def test_ready_with_profile(self) -> None:
        """Profile is ready when loaded."""
        profile = MockProfile()
        result = check_profile_readiness(profile, "2.0.0")
        assert result.status == ReadinessStatus.READY

    def test_not_ready_without_profile(self) -> None:
        """Profile is not ready when None."""
        result = check_profile_readiness(None, "2.0.0")
        assert result.status == ReadinessStatus.NOT_READY

    def test_not_ready_version_too_low(self) -> None:
        """Profile is not ready when version is too low."""
        profile = MockProfile()
        result = check_profile_readiness(profile, "0.5.0")
        assert result.status == ReadinessStatus.NOT_READY


class TestStorageReadiness:
    """Test storage readiness checks."""

    def test_local_ok_for_non_shared(self) -> None:
        """Local storage is OK for non-shared environment."""
        result = check_storage_readiness("local", is_shared_environment=False)
        assert result.status == ReadinessStatus.READY

    def test_local_blocked_for_shared(self) -> None:
        """Local storage is blocked for shared environment."""
        result = check_storage_readiness("local", is_shared_environment=True)
        assert result.status == ReadinessStatus.BLOCKED

    def test_durable_ok_for_shared(self) -> None:
        """Durable storage is OK for shared environment."""
        result = check_storage_readiness("s3", is_shared_environment=True)
        assert result.status == ReadinessStatus.READY


class TestReadinessResult:
    """Test combined readiness result."""

    def test_all_ready(self, sample_projection: dict, sample_base_diagram: dict) -> None:
        """All checks pass when everything is ready."""
        result = run_readiness_checks(
            projection=sample_projection,
            base_diagram=sample_base_diagram,
            profile=MockProfile(),
            mode=GenerationMode.OFFICIAL_SNAPSHOT,
            projection_version="2.0.0",
        )

        assert result.is_ready is True
        assert result.status == ReadinessStatus.READY
        assert len(result.blockers) == 0

    def test_blocked_overrides_not_ready(self) -> None:
        """BLOCKED status overrides NOT_READY."""
        result = run_readiness_checks(
            projection={"identifiers": {}},  # Missing snapshot
            base_diagram={"state": "COMPATIBLE"},  # Not approved
            profile=MockProfile(),
            mode=GenerationMode.OFFICIAL_SNAPSHOT,
            projection_version="2.0.0",
        )

        assert result.is_ready is False
        assert result.status == ReadinessStatus.BLOCKED

    def test_result_hash_computed(self, sample_projection: dict, sample_base_diagram: dict) -> None:
        """Result hash is computed."""
        result = run_readiness_checks(
            projection=sample_projection,
            base_diagram=sample_base_diagram,
            profile=MockProfile(),
            mode=GenerationMode.OFFICIAL_SNAPSHOT,
            projection_version="2.0.0",
        )

        assert len(result.result_hash) == 64


# ─────────────────────────────────────────────────────────────────────────────
# Test: Generation Run
# ─────────────────────────────────────────────────────────────────────────────


class TestGenerationRun:
    """Test generation run creation and transitions."""

    def test_create_run(self) -> None:
        """Run is created with correct initial state."""
        now = datetime.now(tz=timezone.utc)
        input_record = create_input_record(
            mode=GenerationMode.OFFICIAL_SNAPSHOT,
            projection_json='{"test": true}',
            projection_hash="proj123",
            projection_schema_version="2.0.0",
            snapshot_id="snap-id",
            snapshot_hash="snap456",
            catalog_id="cat-id",
            catalog_version="1.0.0",
            catalog_hash="cat789",
            base_diagram_id="base-id",
            base_diagram_hash="base000",
            profile_id="CCPM_OUTPOST_V1",
            profile_version="1.0.0",
            profile_hash="prof111",
            environment="PROD",
            site="DFW",
            variant="STANDARD",
            created_by="user-123",
            created_at=now,
        )

        key = compute_idempotency_key(
            mode=GenerationMode.OFFICIAL_SNAPSHOT,
            projection_hash="proj123",
            base_hash="base000",
            profile_hash="prof111",
        )

        run = create_generation_run(
            intake_id="intake-123",
            input_record=input_record,
            idempotency_key=key,
            created_by="user-123",
        )

        assert run.run_id is not None
        assert run.intake_id == "intake-123"
        assert run.mode == GenerationMode.OFFICIAL_SNAPSHOT
        assert run.phase == RunPhase.PENDING
        assert run.input_id == input_record.input_id
        assert run.idempotency_fingerprint == key.compute_fingerprint()

    def test_transition_to_capturing(self) -> None:
        """Transition to CAPTURING sets started_at."""
        run = GenerationRun(
            run_id=str(uuid.uuid4()),
            intake_id="intake-123",
            mode=GenerationMode.OFFICIAL_SNAPSHOT,
            phase=RunPhase.PENDING,
            input_id="input-123",
            input_hash="hash123",
            idempotency_fingerprint="fp123",
            created_by="user-123",
        )

        transition_run_phase(run, RunPhase.CAPTURING)

        assert run.phase == RunPhase.CAPTURING
        assert run.started_at is not None

    def test_transition_to_completed(self) -> None:
        """Transition to COMPLETED sets completed_at."""
        run = GenerationRun(
            run_id=str(uuid.uuid4()),
            intake_id="intake-123",
            mode=GenerationMode.OFFICIAL_SNAPSHOT,
            phase=RunPhase.VERIFYING,
            input_id="input-123",
            input_hash="hash123",
            idempotency_fingerprint="fp123",
            created_by="user-123",
        )

        transition_run_phase(run, RunPhase.COMPLETED)

        assert run.phase == RunPhase.COMPLETED
        assert run.completed_at is not None

    def test_transition_to_failed(self) -> None:
        """Transition to FAILED sets error info."""
        run = GenerationRun(
            run_id=str(uuid.uuid4()),
            intake_id="intake-123",
            mode=GenerationMode.OFFICIAL_SNAPSHOT,
            phase=RunPhase.RENDERING,
            input_id="input-123",
            input_hash="hash123",
            idempotency_fingerprint="fp123",
            created_by="user-123",
        )

        transition_run_phase(run, RunPhase.FAILED, error_message="Render failed")

        assert run.phase == RunPhase.FAILED
        assert run.completed_at is not None
        assert run.error_message == "Render failed"


# ─────────────────────────────────────────────────────────────────────────────
# Test: Run Approval
# ─────────────────────────────────────────────────────────────────────────────


class TestRunApproval:
    """Test run approval checks."""

    def test_official_completed_can_approve(self) -> None:
        """Official completed run can be approved."""
        run = GenerationRun(
            run_id=str(uuid.uuid4()),
            intake_id="intake-123",
            mode=GenerationMode.OFFICIAL_SNAPSHOT,
            phase=RunPhase.COMPLETED,
            input_id="input-123",
            input_hash="hash123",
            idempotency_fingerprint="fp123",
            created_by="user-123",
        )

        can_approve, reason = can_approve_run(run)
        assert can_approve is True
        assert reason is None

    def test_preview_cannot_approve(self) -> None:
        """Preview run cannot be approved."""
        run = GenerationRun(
            run_id=str(uuid.uuid4()),
            intake_id="intake-123",
            mode=GenerationMode.DRAFT_PREVIEW,
            phase=RunPhase.COMPLETED,
            input_id="input-123",
            input_hash="hash123",
            idempotency_fingerprint="fp123",
            created_by="user-123",
        )

        can_approve, reason = can_approve_run(run)
        assert can_approve is False
        assert "preview" in reason.lower()

    def test_incomplete_cannot_approve(self) -> None:
        """Incomplete run cannot be approved."""
        run = GenerationRun(
            run_id=str(uuid.uuid4()),
            intake_id="intake-123",
            mode=GenerationMode.OFFICIAL_SNAPSHOT,
            phase=RunPhase.RENDERING,
            input_id="input-123",
            input_hash="hash123",
            idempotency_fingerprint="fp123",
            created_by="user-123",
        )

        can_approve, reason = can_approve_run(run)
        assert can_approve is False
        assert "COMPLETED" in reason
