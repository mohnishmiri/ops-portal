"""Explicit catalog maintenance and draft repinning commands."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.orm import sessionmaker

from migration_intake.application.dto import ActorContext
from migration_intake.application.errors import (
    ApplicationServiceError,
    ConcurrencyConflictError,
)
from migration_intake.persistence.models import AuditEvent, Intake
from migration_intake.persistence.models_candidates import Candidate
from migration_intake.persistence.models_evidence import EvidenceItem
from migration_intake.persistence.models_imports import ImportRun
from migration_intake.persistence.models_snapshots import IntakeSnapshot
from migration_intake.persistence.unit_of_work import uow_context


class CatalogMaintenanceError(ApplicationServiceError):
    """Catalog maintenance or repinning cannot proceed."""


@dataclass(frozen=True)
class MaintenanceResult:
    """Deterministic result of an explicit maintenance command."""

    dry_run: bool
    catalog_hashes_updated: int
    options_repaired: int


@dataclass(frozen=True)
class RepinResult:
    """Result of an eligible draft-intake repin."""

    intake_id: str
    old_catalog_id: str
    new_catalog_id: str
    new_row_version: int
    dry_run: bool


class CatalogMaintenanceService:
    """Own explicit, audited catalog repair and draft repinning commands."""

    def __init__(self, session_factory: sessionmaker) -> None:
        self._session_factory = session_factory

    def repair_packaged_release(self, *, actor: ActorContext, apply: bool) -> MaintenanceResult:
        """Repair only exact packaged-release matches; never run at startup."""
        from migration_intake.catalog.bootstrap import (
            backfill_catalog_hashes,
            repair_catalog_options,
        )

        if not apply:
            return MaintenanceResult(
                dry_run=True,
                catalog_hashes_updated=0,
                options_repaired=0,
            )

        # The legacy helpers each own a transaction. Keep this command explicit;
        # a future migration can fold them into one audited maintenance UoW.
        updated = backfill_catalog_hashes(self._session_factory)
        repaired = repair_catalog_options(self._session_factory)
        self._record_audit(actor, "CATALOG_MAINTENANCE_APPLIED", str(uuid.uuid4()))
        return MaintenanceResult(
            dry_run=False,
            catalog_hashes_updated=updated,
            options_repaired=repaired,
        )

    def repin_empty_draft(
        self,
        *,
        intake_id: str,
        new_catalog_id: str,
        expected_row_version: int,
        actor: ActorContext,
        apply: bool,
    ) -> RepinResult:
        """Repin only an empty DRAFT intake with an atomic version check."""
        with uow_context(self._session_factory) as uow:
            intake = uow.intakes.get(intake_id)
            if intake is None:
                raise CatalogMaintenanceError(f"Intake {intake_id} not found")
            if intake["state"] != "DRAFT":
                raise CatalogMaintenanceError("Only DRAFT intakes can be repinned")
            if intake["row_version"] != expected_row_version:
                raise ConcurrencyConflictError("Stale intake row version")

            catalog = uow.catalogs.get_release(new_catalog_id)
            if catalog is None or catalog["pub_state"] != "PUBLISHED":
                raise CatalogMaintenanceError("Target catalog is not PUBLISHED")

            blockers = self._empty_draft_blockers(uow._session, intake_id)
            if blockers:
                raise CatalogMaintenanceError(
                    "Intake has dependent data: " + ", ".join(blockers)
                )

            result = RepinResult(
                intake_id=intake_id,
                old_catalog_id=intake["catalog_id"],
                new_catalog_id=new_catalog_id,
                new_row_version=expected_row_version + 1,
                dry_run=not apply,
            )
            if not apply:
                return result

            stmt = (
                update(Intake)
                .where(
                    Intake.id == intake_id,
                    Intake.state == "DRAFT",
                    Intake.row_version == expected_row_version,
                )
                .values(
                    catalog_id=new_catalog_id,
                    row_version=Intake.row_version + 1,
                    content_epoch=Intake.content_epoch + 1,
                    updated_at=datetime.now(tz=UTC),
                )
            )
            if uow._session.execute(stmt).rowcount != 1:
                raise ConcurrencyConflictError("Concurrent intake repin detected")
            uow._session.add(
                AuditEvent(
                    id=str(uuid.uuid4()),
                    entity_type="intake",
                    entity_id=intake_id,
                    event_code="INTAKE_CATALOG_REPINNED",
                    actor_id=actor.actor_id,
                    occurred_at=datetime.now(tz=UTC),
                    payload={
                        "old_catalog_id": intake["catalog_id"],
                        "new_catalog_id": new_catalog_id,
                        "expected_row_version": expected_row_version,
                    },
                )
            )
            uow.commit()
            return result

    @staticmethod
    def _empty_draft_blockers(session: Any, intake_id: str) -> list[str]:
        """Find dependent rows that make repinning unsafe."""
        checks = [
            ("answers", select(1).where(_answer_intake_filter(intake_id)).limit(1)),
            ("candidates", select(1).where(Candidate.intake_id == intake_id).limit(1)),
            ("evidence", select(1).where(EvidenceItem.intake_id == intake_id).limit(1)),
            ("imports", select(1).where(ImportRun.intake_id == intake_id).limit(1)),
            ("snapshot", select(1).where(IntakeSnapshot.intake_id == intake_id).limit(1)),
        ]
        return [name for name, stmt in checks if session.execute(stmt).first() is not None]

    def _record_audit(self, actor: ActorContext, event_code: str, entity_id: str) -> None:
        with uow_context(self._session_factory) as uow:
            uow._session.add(
                AuditEvent(
                    id=str(uuid.uuid4()),
                    entity_type="catalog",
                    entity_id=entity_id,
                    event_code=event_code,
                    actor_id=actor.actor_id,
                    occurred_at=datetime.now(tz=UTC),
                    payload=None,
                )
            )
            uow.commit()


def _answer_intake_filter(intake_id: str) -> Any:
    from migration_intake.persistence.models import AnswerInstance

    return AnswerInstance.intake_id == intake_id
