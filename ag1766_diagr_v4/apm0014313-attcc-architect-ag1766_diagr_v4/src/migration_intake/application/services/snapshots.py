"""
Snapshot service — A05.

Handles freezing intakes and creating immutable snapshots.

Freeze workflow:
1. Reload and validate current heads within the write transaction
2. Create the canonical payload/hash once
3. Insert the immutable snapshot
4. Transition intake to FROZEN
5. Write audit atomically

Repeating an equivalent command returns the existing snapshot idempotently.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from migration_intake.application.errors import ConcurrencyConflictError
from migration_intake.application.services.readiness import ReadinessResult, ReadinessService
from migration_intake.application.snapshots import (
    SCHEMA_VERSION,
    CanonicalAnswer,
    CanonicalIdentifier,
    CanonicalIntakePayload,
    CanonicalSerializer,
    CanonicalTargetResource,
    CanonicalWaveUtilRow,
)
from migration_intake.persistence.repositories.answers import AnswerRepository
from migration_intake.persistence.repositories.applications import ApplicationRepository
from migration_intake.persistence.repositories.catalogs import CatalogRepository
from migration_intake.persistence.repositories.intakes import IntakeRepository
from migration_intake.persistence.repositories.snapshots import SnapshotRepository
from migration_intake.persistence.repositories.wave_util import WaveUtilRepository
from migration_intake.persistence.unit_of_work import uow_context

if TYPE_CHECKING:
    from sqlalchemy.orm import sessionmaker

    from migration_intake.application.dto import ActorContext

# ─────────────────────────────────────────────────────────────────────────────
# Errors
# ─────────────────────────────────────────────────────────────────────────────


class IntakeNotReadyError(Exception):
    """Raised when trying to freeze an intake that is not ready."""

    def __init__(self, readiness: ReadinessResult) -> None:
        self.readiness = readiness
        blockers = [d.name for d in readiness.blocking_dimensions]
        super().__init__(f"Intake not ready to freeze: {blockers}")


class IntakeAlreadyFrozenError(Exception):
    """Raised when trying to freeze an already-frozen intake."""
    pass


# ─────────────────────────────────────────────────────────────────────────────
# Result data class
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class FreezeResult:
    """Result of a freeze operation."""

    snapshot_id: str
    intake_id: str
    sha256_hex: str
    created_at: str
    is_new: bool  # False if idempotent return of existing snapshot


# ─────────────────────────────────────────────────────────────────────────────
# Service
# ─────────────────────────────────────────────────────────────────────────────


class SnapshotService:
    """
    Handles freezing intakes and creating immutable snapshots.

    Freeze is atomic: either all changes succeed or none do.
    Repeating freeze on an already-frozen intake is idempotent.
    """

    def __init__(self, session_factory: sessionmaker) -> None:
        self._session_factory = session_factory
        self._readiness_service = ReadinessService(session_factory)

    def freeze_intake(
        self,
        intake_id: str,
        actor: ActorContext,
        *,
        skip_readiness_check: bool = False,
    ) -> FreezeResult:
        """
        Freeze an intake and create an immutable snapshot.

        Algorithm:
        1. Check readiness (unless skip_readiness_check=True)
        2. If already frozen, return existing snapshot (idempotent)
        3. Reload and validate current state within transaction
        4. Create canonical payload and hash
        5. Insert snapshot
        6. Transition intake to FROZEN
        7. Commit atomically

        Args:
            intake_id: The intake to freeze
            actor: The actor performing the freeze
            skip_readiness_check: Skip readiness check (for testing)

        Returns:
            FreezeResult with snapshot details

        Raises:
            IntakeNotReadyError: If intake is not ready to freeze
            ConcurrencyConflictError: If intake was modified during freeze
        """
        now = datetime.now(tz=UTC)

        # Check readiness first (outside transaction)
        if not skip_readiness_check:
            readiness = self._readiness_service.check_readiness(intake_id)
            if not readiness.is_ready:
                raise IntakeNotReadyError(readiness)

        with uow_context(self._session_factory) as uow:
            session = uow._session

            intake_repo = IntakeRepository(session)
            app_repo = ApplicationRepository(session)
            catalog_repo = CatalogRepository(session)
            answer_repo = AnswerRepository(session)
            wave_util_repo = WaveUtilRepository(session)
            snapshot_repo = SnapshotRepository(session)

            # Reload intake within transaction
            intake = intake_repo.get_for_update(intake_id)
            if intake is None:
                raise ConcurrencyConflictError(f"Intake {intake_id} not found")

            # Check if already frozen (idempotent)
            if intake["state"] == "FROZEN":
                existing_snapshot = snapshot_repo.get_by_intake_id(intake_id)
                if existing_snapshot:
                    return FreezeResult(
                        snapshot_id=existing_snapshot["id"],
                        intake_id=intake_id,
                        sha256_hex=existing_snapshot["sha256_hex"],
                        created_at=str(existing_snapshot["created_at"]),
                        is_new=False,
                    )

            # Get application
            app = app_repo.get(intake["application_id"])
            if app is None:
                raise ConcurrencyConflictError(
                    f"Application {intake['application_id']} not found"
                )

            # Get catalog
            catalog = catalog_repo.get_release(intake["catalog_id"])
            if catalog is None:
                raise ConcurrencyConflictError(
                    f"Catalog {intake['catalog_id']} not found"
                )

            # Build canonical payload
            canonical_identifiers = self._build_canonical_identifiers(
                app_repo, intake["application_id"]
            )
            canonical_answers = self._build_canonical_answers(
                answer_repo, intake_id
            )
            canonical_target_resources = self._build_canonical_target_resources(
                intake["application_id"], intake_id
            )
            canonical_wave_util = self._build_canonical_wave_util(
                wave_util_repo, intake["application_id"]
            )

            frozen_at = CanonicalSerializer.normalize_timestamp(now)

            # Get catalog hash (may be None for legacy releases)
            catalog_hash = catalog.get("catalog_hash")

            payload = CanonicalIntakePayload(
                schema_version=SCHEMA_VERSION,
                application_id=intake["application_id"],
                application_name=app["display_name"],
                catalog_id=intake["catalog_id"],
                catalog_version=catalog["semantic_version"],
                catalog_sha256=catalog["source_sha256"],
                catalog_hash=catalog_hash,
                intake_id=intake_id,
                intake_state="FROZEN",
                frozen_at=frozen_at,
                frozen_by=actor.actor_id,
                application_identifiers=canonical_identifiers,
                answers=canonical_answers,
                target_resources=canonical_target_resources,
                wave_util_rows=canonical_wave_util,
                permitted_gaps=[],
            )

            # Serialize and hash
            canonical_json, sha256_hex = CanonicalSerializer.serialize(payload)

            # Create snapshot
            snapshot_id = str(uuid.uuid4())
            snapshot_repo.create_snapshot(
                snapshot_id=snapshot_id,
                intake_id=intake_id,
                catalog_id=intake["catalog_id"],
                schema_version=SCHEMA_VERSION,
                catalog_sha256=catalog["source_sha256"],
                canonical_json=canonical_json,
                sha256_hex=sha256_hex,
                created_at=now,
                created_by_id=actor.actor_id,
            )

            # Transition intake to FROZEN
            if not intake_repo.update_state(
                intake_id, "FROZEN", intake["row_version"], now
            ):
                raise ConcurrencyConflictError(
                    "Concurrent intake change detected during freeze"
                )

            uow.commit()

        return FreezeResult(
            snapshot_id=snapshot_id,
            intake_id=intake_id,
            sha256_hex=sha256_hex,
            created_at=frozen_at,
            is_new=True,
        )

    def publish_topology_authority(
        self, intake_id: str, actor: ActorContext
    ) -> dict[str, object]:
        """Publish immutable topology v3 authority without relabeling legacy snapshots."""
        from migration_intake.application.services.topology_authority import (
            TopologyAuthorityService,
        )

        return TopologyAuthorityService(self._session_factory).publish_v3(
            intake_id, actor.actor_id
        )

    def get_snapshot(self, intake_id: str) -> dict[str, Any] | None:
        """Get the snapshot for an intake, if it exists."""
        with self._session_factory() as session:
            snapshot_repo = SnapshotRepository(session)
            return snapshot_repo.get_by_intake_id(intake_id)

    def _build_canonical_identifiers(
        self,
        app_repo: ApplicationRepository,
        application_id: str,
    ) -> list[CanonicalIdentifier]:
        """Build canonical application identifiers for the payload.

        Returns typed identifiers (CORRELATION, MOTS, ITAP, etc.) sorted by type.
        The first identifier of each type is marked as primary.
        """
        identifiers = app_repo.list_identifiers(application_id)
        canonical_identifiers = []
        seen_types: set[str] = set()

        for ident in identifiers:
            id_type = ident["identifier_type"]
            is_primary = id_type not in seen_types
            seen_types.add(id_type)

            canonical_identifiers.append(
                CanonicalIdentifier(
                    identifier_type=id_type,
                    value=ident["normalized_value"] or ident["raw_value"],
                    is_primary=is_primary,
                )
            )

        return canonical_identifiers

    def _build_canonical_answers(
        self,
        answer_repo: AnswerRepository,
        intake_id: str,
    ) -> list[CanonicalAnswer]:
        """Build canonical answers for the payload.

        Returns only confirmed answers with their current revision data
        and provenance references. Empty revisions and candidates are excluded.
        """
        confirmed_answers = answer_repo.get_confirmed_answers_for_intake(intake_id)
        canonical_answers = []

        for answer in confirmed_answers:
            provenance_refs = answer_repo.get_provenance_references_for_revision(
                answer["revision_id"]
            )

            canonical_answers.append(
                CanonicalAnswer(
                    question_id=answer["question_id"],
                    question_code=answer["question_code"],
                    section_code=answer["section_code"],
                    response_type=answer["response_type"],
                    value_json=answer["response_json"],
                    review_state=answer["review_state"],
                    revision_number=answer["revision_number"],
                    confirm_state=answer["confirm_state"],
                    response_schema_version=answer["response_schema_version"],
                    provenance_references=provenance_refs,
                )
            )

        return canonical_answers

    def _build_canonical_target_resources(
        self,
        application_id: str,
        intake_id: str,
    ) -> list[CanonicalTargetResource]:
        """Build canonical target resources for the payload.

        This is a placeholder for P5 implementation. Returns an empty list
        until target-resource persistence is implemented.

        When P5 is complete, this will query the target_resources and
        target_resource_revisions tables for confirmed resources.
        """
        _ = application_id, intake_id
        return []

    def _build_canonical_wave_util(
        self,
        wave_util_repo: WaveUtilRepository,
        application_id: str,
    ) -> list[CanonicalWaveUtilRow]:
        """Build canonical WaveUtil rows for the payload."""
        rows = wave_util_repo.list_rows_for_application(application_id, state="ACTIVE")
        canonical_rows = []

        for row in rows:
            current_rev = wave_util_repo.get_current_revision(row["id"])
            canonical_rows.append(
                CanonicalWaveUtilRow(
                    row_id=row["id"],
                    server_name=row["server_name"],
                    normalized_server_name=row["normalized_server_name"],
                    environment=row["environment"],
                    scope=row["scope"],
                    state=row["state"],
                    revision_number=current_rev["revision_number"] if current_rev else 0,
                    field_values=current_rev["field_values_json"] if current_rev else {},
                )
            )

        return canonical_rows
