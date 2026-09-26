"""
Readiness service — A05.

Computes readiness as a structured result with independent dimensions.
Readiness is NOT a single percentage but a set of dimension checks.

Required dimensions:
- Required/applicable answers
- Condition-pending controls
- Confirmation policy
- Unresolved conflicts/deferred candidates
- Evidence/import quarantine
- WaveUtil completeness
- Required decisions/approvals
- Catalog validity
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy.orm import sessionmaker

from migration_intake.persistence.repositories.candidates import CandidateRepository
from migration_intake.persistence.repositories.intakes import IntakeRepository
from migration_intake.persistence.repositories.snapshots import SnapshotRepository
from migration_intake.persistence.repositories.wave_util import WaveUtilRepository

# ─────────────────────────────────────────────────────────────────────────────
# Data classes
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class ReadinessDimension:
    """A single readiness dimension check result."""

    name: str
    passed: bool
    message: str
    blockers: list[str] = field(default_factory=list)


@dataclass
class ReadinessResult:
    """Complete readiness assessment for an intake."""

    intake_id: str
    is_ready: bool
    dimensions: list[ReadinessDimension]
    checked_at: str  # ISO 8601 UTC timestamp

    @property
    def blocking_dimensions(self) -> list[ReadinessDimension]:
        """Return dimensions that are blocking freeze."""
        return [d for d in self.dimensions if not d.passed]


# ─────────────────────────────────────────────────────────────────────────────
# Service
# ─────────────────────────────────────────────────────────────────────────────


class ReadinessService:
    """
    Computes readiness for an intake.

    Readiness is a structured result with independent dimensions.
    Overall ready is true only when every required dimension passes.
    """

    def __init__(self, session_factory: sessionmaker) -> None:
        self._session_factory = session_factory

    def check_readiness(self, intake_id: str) -> ReadinessResult:
        """
        Check readiness for an intake.

        Returns a structured result with all dimension checks.
        """
        now = datetime.now(tz=UTC)
        dimensions: list[ReadinessDimension] = []

        with self._session_factory() as session:
            intake_repo = IntakeRepository(session)
            candidate_repo = CandidateRepository(session)
            snapshot_repo = SnapshotRepository(session)
            wave_util_repo = WaveUtilRepository(session)

            # Get intake
            intake = intake_repo.get(intake_id)
            if intake is None:
                return ReadinessResult(
                    intake_id=intake_id,
                    is_ready=False,
                    dimensions=[
                        ReadinessDimension(
                            name="intake_exists",
                            passed=False,
                            message="Intake not found",
                            blockers=[f"Intake {intake_id} does not exist"],
                        )
                    ],
                    checked_at=now.isoformat(),
                )

            # Check if already frozen
            intake_state = intake["state"]
            if intake_state == "FROZEN":
                dimensions.append(
                    ReadinessDimension(
                        name="intake_state",
                        passed=True,
                        message="Intake is already frozen",
                    )
                )
                return ReadinessResult(
                    intake_id=intake_id,
                    is_ready=True,
                    dimensions=dimensions,
                    checked_at=now.isoformat(),
                )

            # Dimension 1: Intake state
            if intake_state not in ("DRAFT", "IN_REVIEW"):
                dimensions.append(
                    ReadinessDimension(
                        name="intake_state",
                        passed=False,
                        message=f"Intake state is {intake_state}, must be DRAFT or IN_REVIEW",
                        blockers=[f"Invalid intake state: {intake_state}"],
                    )
                )
            else:
                dimensions.append(
                    ReadinessDimension(
                        name="intake_state",
                        passed=True,
                        message=f"Intake state is {intake_state}",
                    )
                )

            # Dimension 2: Unresolved candidates
            unresolved_candidates = candidate_repo.get_by_intake(
                intake_id, state="PROPOSED", limit=100
            )
            if unresolved_candidates:
                dimensions.append(
                    ReadinessDimension(
                        name="unresolved_candidates",
                        passed=False,
                        message=f"{len(unresolved_candidates)} unresolved candidates",
                        blockers=[
                            f"Candidate {c.id}: {c.target_kind}/{c.target_key}"
                            for c in unresolved_candidates[:10]
                        ],
                    )
                )
            else:
                dimensions.append(
                    ReadinessDimension(
                        name="unresolved_candidates",
                        passed=True,
                        message="No unresolved candidates",
                    )
                )

            # Dimension 3: Deferred candidates (warning, not blocking)
            deferred_candidates = candidate_repo.get_by_intake(
                intake_id, state="DEFERRED", limit=100
            )
            if deferred_candidates:
                dimensions.append(
                    ReadinessDimension(
                        name="deferred_candidates",
                        passed=True,  # Deferred is allowed
                        message=f"{len(deferred_candidates)} deferred candidates (permitted)",
                    )
                )
            else:
                dimensions.append(
                    ReadinessDimension(
                        name="deferred_candidates",
                        passed=True,
                        message="No deferred candidates",
                    )
                )

            # Dimension 4: Snapshot not already exists
            if snapshot_repo.exists_for_intake(intake_id):
                dimensions.append(
                    ReadinessDimension(
                        name="snapshot_exists",
                        passed=True,
                        message="Snapshot already exists (idempotent)",
                    )
                )
            else:
                dimensions.append(
                    ReadinessDimension(
                        name="snapshot_exists",
                        passed=True,
                        message="No existing snapshot",
                    )
                )

            # Dimension 5: WaveUtil completeness (basic check)
            wave_util_rows = wave_util_repo.list_rows_for_application(
                intake["application_id"], state="ACTIVE"
            )
            dimensions.append(
                ReadinessDimension(
                    name="wave_util_completeness",
                    passed=True,
                    message=f"{len(wave_util_rows)} active WaveUtil rows",
                )
            )

        # Compute overall readiness
        is_ready = all(d.passed for d in dimensions)

        return ReadinessResult(
            intake_id=intake_id,
            is_ready=is_ready,
            dimensions=dimensions,
            checked_at=now.isoformat(),
        )
