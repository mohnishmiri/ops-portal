"""
Topology Orchestration — P8 Implementation.

Implements the orchestration layer for topology generation:
- OFFICIAL_SNAPSHOT and DRAFT_PREVIEW modes
- Immutable topology-input records
- Phased transaction protocol
- Idempotency fingerprinting

Design rules:
- Official mode uses snapshot JSON, no live answer queries
- Preview mode captures canonical heads once, then renders
- Every run has immutable input hash and profile hash
- Process failures leave recoverable RUNNING/FAILED records
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from migration_intake.topology.contracts import (
    GenerationMode,
    ReadinessStatus,
    RunPhase,
)

# ─────────────────────────────────────────────────────────────────────────────
# Enums
# ─────────────────────────────────────────────────────────────────────────────


# ─────────────────────────────────────────────────────────────────────────────
# Data Classes - Input Records
# ─────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class TopologyInputRecord:
    """
    Immutable topology-input record.

    Contains all inputs required for deterministic rendering.
    """

    # Identity
    input_id: str
    input_hash: str  # SHA-256 of all inputs

    # Mode
    mode: GenerationMode

    # Projection
    projection_schema_version: str
    projection_json: str
    projection_hash: str

    # Source (for OFFICIAL_SNAPSHOT mode)
    snapshot_id: str | None
    snapshot_hash: str | None

    # Catalog
    catalog_id: str
    catalog_version: str
    catalog_hash: str

    # Base diagram
    base_diagram_id: str
    base_diagram_hash: str

    # Profile
    profile_id: str
    profile_version: str
    profile_hash: str

    # Target context
    environment: str
    site: str | None
    variant: str

    # Generator
    generator_version: str

    # Audit
    created_by: str
    created_at: datetime


@dataclass(frozen=True)
class ReadinessCheck:
    """Result of a single readiness check."""

    check_id: str
    check_type: str  # DATA, BASE, PROFILE, STORAGE
    status: ReadinessStatus
    message: str
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class ReadinessResult:
    """Complete readiness check result."""

    # Overall status
    is_ready: bool
    status: ReadinessStatus

    # Individual checks
    checks: list[ReadinessCheck] = field(default_factory=list)

    # Blockers
    blockers: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    # Hash for persistence
    result_hash: str = ""

    def compute_hash(self) -> str:
        """Compute hash of readiness result."""
        data = {
            "is_ready": self.is_ready,
            "status": self.status.value,
            "checks": [
                {
                    "check_id": c.check_id,
                    "check_type": c.check_type,
                    "status": c.status.value,
                    "message": c.message,
                }
                for c in self.checks
            ],
            "blockers": self.blockers,
        }
        return hashlib.sha256(
            json.dumps(data, sort_keys=True).encode()
        ).hexdigest()


@dataclass(frozen=True)
class IdempotencyKey:
    """
    Idempotency fingerprint for generation runs.

    Two runs with the same key produce identical outputs.
    """

    mode: GenerationMode
    projection_hash: str
    base_hash: str
    profile_hash: str
    generator_version: str

    def compute_fingerprint(self) -> str:
        """Compute idempotency fingerprint."""
        data = f"{self.mode.value}:{self.projection_hash}:{self.base_hash}:{self.profile_hash}:{self.generator_version}"
        return hashlib.sha256(data.encode()).hexdigest()


# ─────────────────────────────────────────────────────────────────────────────
# Data Classes - Run Records
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class GenerationRun:
    """A topology generation run."""

    # Identity
    run_id: str
    intake_id: str

    # Mode and phase
    mode: GenerationMode
    phase: RunPhase

    # Input reference
    input_id: str
    input_hash: str

    # Idempotency
    idempotency_fingerprint: str
    rerun_reason: str | None = None

    # Readiness
    readiness_hash: str | None = None

    # Metrics
    slots_matched: int = 0
    slots_total: int = 0
    mutations_attempted: int = 0
    mutations_effective: int = 0
    markers_before: int = 0
    markers_after: int = 0

    # Artifacts
    diagram_artifact_id: str | None = None
    diagram_hash: str | None = None
    report_artifact_id: str | None = None
    report_hash: str | None = None
    manifest_artifact_id: str | None = None
    manifest_hash: str | None = None

    # Status
    error_message: str | None = None
    error_phase: str | None = None

    # Audit
    created_by: str = ""
    created_at: datetime = field(default_factory=lambda: datetime.now(tz=UTC))
    started_at: datetime | None = None
    completed_at: datetime | None = None


# ─────────────────────────────────────────────────────────────────────────────
# Orchestration Service
# ─────────────────────────────────────────────────────────────────────────────


class OrchestrationError(Exception):
    """Base class for orchestration errors."""

    pass


class InputCaptureError(OrchestrationError):
    """Failed to capture inputs."""

    pass


class ReadinessError(OrchestrationError):
    """Readiness check failed."""

    pass


class RenderingError(OrchestrationError):
    """Rendering failed."""

    pass


class StorageError(OrchestrationError):
    """Storage operation failed."""

    pass


class IdempotencyError(OrchestrationError):
    """Duplicate run without rerun reason."""

    pass


GENERATOR_VERSION = "1.0.0"


def compute_input_hash(
    mode: GenerationMode,
    projection_hash: str,
    snapshot_hash: str | None,
    catalog_hash: str,
    base_hash: str,
    profile_hash: str,
    environment: str,
    site: str | None,
    variant: str,
) -> str:
    """Compute hash of all inputs."""
    data = {
        "mode": mode.value,
        "projection_hash": projection_hash,
        "snapshot_hash": snapshot_hash,
        "catalog_hash": catalog_hash,
        "base_hash": base_hash,
        "profile_hash": profile_hash,
        "environment": environment,
        "site": site,
        "variant": variant,
    }
    return hashlib.sha256(
        json.dumps(data, sort_keys=True).encode()
    ).hexdigest()


def create_input_record(
    mode: GenerationMode,
    projection_json: str,
    projection_hash: str,
    projection_schema_version: str,
    snapshot_id: str | None,
    snapshot_hash: str | None,
    catalog_id: str,
    catalog_version: str,
    catalog_hash: str,
    base_diagram_id: str,
    base_diagram_hash: str,
    profile_id: str,
    profile_version: str,
    profile_hash: str,
    environment: str,
    site: str | None,
    variant: str,
    created_by: str,
    created_at: datetime,
) -> TopologyInputRecord:
    """Create an immutable topology input record."""
    input_id = str(uuid.uuid4())

    input_hash = compute_input_hash(
        mode=mode,
        projection_hash=projection_hash,
        snapshot_hash=snapshot_hash,
        catalog_hash=catalog_hash,
        base_hash=base_diagram_hash,
        profile_hash=profile_hash,
        environment=environment,
        site=site,
        variant=variant,
    )

    return TopologyInputRecord(
        input_id=input_id,
        input_hash=input_hash,
        mode=mode,
        projection_schema_version=projection_schema_version,
        projection_json=projection_json,
        projection_hash=projection_hash,
        snapshot_id=snapshot_id,
        snapshot_hash=snapshot_hash,
        catalog_id=catalog_id,
        catalog_version=catalog_version,
        catalog_hash=catalog_hash,
        base_diagram_id=base_diagram_id,
        base_diagram_hash=base_diagram_hash,
        profile_id=profile_id,
        profile_version=profile_version,
        profile_hash=profile_hash,
        environment=environment,
        site=site,
        variant=variant,
        generator_version=GENERATOR_VERSION,
        created_by=created_by,
        created_at=created_at,
    )


def compute_idempotency_key(
    mode: GenerationMode,
    projection_hash: str,
    base_hash: str,
    profile_hash: str,
) -> IdempotencyKey:
    """Compute idempotency key for a run."""
    return IdempotencyKey(
        mode=mode,
        projection_hash=projection_hash,
        base_hash=base_hash,
        profile_hash=profile_hash,
        generator_version=GENERATOR_VERSION,
    )


def check_data_readiness(
    projection: dict[str, Any],
    mode: GenerationMode,
) -> ReadinessCheck:
    """Check data readiness."""
    check_id = str(uuid.uuid4())

    # Check projection has required fields
    if not projection.get("identifiers"):
        return ReadinessCheck(
            check_id=check_id,
            check_type="DATA",
            status=ReadinessStatus.NOT_READY,
            message="Projection missing identifiers",
        )

    # For official mode, check snapshot reference
    if mode == GenerationMode.OFFICIAL_SNAPSHOT:
        if not projection.get("snapshot_id"):
            return ReadinessCheck(
                check_id=check_id,
                check_type="DATA",
                status=ReadinessStatus.NOT_READY,
                message="Official mode requires snapshot reference",
            )

    return ReadinessCheck(
        check_id=check_id,
        check_type="DATA",
        status=ReadinessStatus.READY,
        message="Data is ready",
    )


def check_base_readiness(
    base_diagram: dict[str, Any],
    mode: GenerationMode,
) -> ReadinessCheck:
    """Check base diagram readiness."""
    check_id = str(uuid.uuid4())

    state = base_diagram.get("state", "")

    # For official mode, base must be APPROVED
    if mode == GenerationMode.OFFICIAL_SNAPSHOT:
        if state != "APPROVED":
            return ReadinessCheck(
                check_id=check_id,
                check_type="BASE",
                status=ReadinessStatus.BLOCKED,
                message=f"Official mode requires APPROVED base, got {state}",
            )
    else:
        # For preview, COMPATIBLE or APPROVED is OK
        if state not in ("COMPATIBLE", "APPROVED"):
            return ReadinessCheck(
                check_id=check_id,
                check_type="BASE",
                status=ReadinessStatus.NOT_READY,
                message=f"Preview requires COMPATIBLE or APPROVED base, got {state}",
            )

    return ReadinessCheck(
        check_id=check_id,
        check_type="BASE",
        status=ReadinessStatus.READY,
        message="Base diagram is ready",
    )


def check_profile_readiness(
    profile: Any,
    projection_version: str,
) -> ReadinessCheck:
    """Check profile readiness."""
    check_id = str(uuid.uuid4())

    if profile is None:
        return ReadinessCheck(
            check_id=check_id,
            check_type="PROFILE",
            status=ReadinessStatus.NOT_READY,
            message="Profile not loaded",
        )

    # Check version compatibility
    if hasattr(profile, "manifest"):
        manifest = profile.manifest
        min_version = getattr(manifest, "min_projection_version", "0.0.0")
        max_version = getattr(manifest, "max_projection_version", "999.x")

        # Simple version check (could be more sophisticated)
        if projection_version < min_version:
            return ReadinessCheck(
                check_id=check_id,
                check_type="PROFILE",
                status=ReadinessStatus.NOT_READY,
                message=f"Projection version {projection_version} below minimum {min_version}",
            )

    return ReadinessCheck(
        check_id=check_id,
        check_type="PROFILE",
        status=ReadinessStatus.READY,
        message="Profile is ready",
    )


def check_storage_readiness(
    storage_backend: str,
    is_shared_environment: bool,
) -> ReadinessCheck:
    """Check storage readiness."""
    check_id = str(uuid.uuid4())

    # Shared environments require durable storage
    if is_shared_environment:
        if storage_backend == "local":
            return ReadinessCheck(
                check_id=check_id,
                check_type="STORAGE",
                status=ReadinessStatus.BLOCKED,
                message="Shared environment requires durable storage backend",
            )

    return ReadinessCheck(
        check_id=check_id,
        check_type="STORAGE",
        status=ReadinessStatus.READY,
        message="Storage is ready",
    )


def run_readiness_checks(
    projection: dict[str, Any],
    base_diagram: dict[str, Any],
    profile: Any,
    mode: GenerationMode,
    projection_version: str,
    storage_backend: str = "local",
    is_shared_environment: bool = False,
) -> ReadinessResult:
    """Run all readiness checks."""
    checks = [
        check_data_readiness(projection, mode),
        check_base_readiness(base_diagram, mode),
        check_profile_readiness(profile, projection_version),
        check_storage_readiness(storage_backend, is_shared_environment),
    ]

    blockers = [c.message for c in checks if c.status == ReadinessStatus.BLOCKED]
    not_ready = [c.message for c in checks if c.status == ReadinessStatus.NOT_READY]

    if blockers:
        status = ReadinessStatus.BLOCKED
        is_ready = False
    elif not_ready:
        status = ReadinessStatus.NOT_READY
        is_ready = False
    else:
        status = ReadinessStatus.READY
        is_ready = True

    result = ReadinessResult(
        is_ready=is_ready,
        status=status,
        checks=checks,
        blockers=blockers,
        warnings=not_ready,
    )
    result.result_hash = result.compute_hash()

    return result


def create_generation_run(
    intake_id: str,
    input_record: TopologyInputRecord,
    idempotency_key: IdempotencyKey,
    created_by: str,
    rerun_reason: str | None = None,
) -> GenerationRun:
    """Create a new generation run."""
    return GenerationRun(
        run_id=str(uuid.uuid4()),
        intake_id=intake_id,
        mode=input_record.mode,
        phase=RunPhase.PENDING,
        input_id=input_record.input_id,
        input_hash=input_record.input_hash,
        idempotency_fingerprint=idempotency_key.compute_fingerprint(),
        rerun_reason=rerun_reason,
        created_by=created_by,
        created_at=datetime.now(tz=UTC),
    )


def transition_run_phase(
    run: GenerationRun,
    new_phase: RunPhase,
    error_message: str | None = None,
) -> GenerationRun:
    """Transition a run to a new phase."""
    run.phase = new_phase

    if new_phase == RunPhase.CAPTURING:
        run.started_at = datetime.now(tz=UTC)
    elif new_phase in (RunPhase.COMPLETED, RunPhase.FAILED):
        run.completed_at = datetime.now(tz=UTC)

    if new_phase == RunPhase.FAILED and error_message:
        run.error_message = error_message
        run.error_phase = run.phase.value

    return run


def can_approve_run(run: GenerationRun) -> tuple[bool, str | None]:
    """Check if a run can be approved."""
    if run.mode == GenerationMode.DRAFT_PREVIEW:
        return False, "Draft preview runs cannot be approved"

    if run.phase != RunPhase.COMPLETED:
        return False, f"Run is in phase {run.phase.value}, must be COMPLETED"

    return True, None
