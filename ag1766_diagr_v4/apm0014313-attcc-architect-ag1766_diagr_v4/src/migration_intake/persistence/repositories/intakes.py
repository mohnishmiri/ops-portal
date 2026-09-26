"""
IntakeRepository — P04 (Repositories and Unit of Work).

"Open" intake definition: state NOT IN ('FROZEN', 'CANCELLED', 'SUPERSEDED').
An application may only have one open intake at a time; this constraint is
enforced at the application-service layer rather than the database.

Design rules (Architecture sections 31, 38):
- Returns plain dicts, never ORM entity instances.
- Optimistic concurrency via row_version predicate (same pattern as Application).
- Session is owned by the UnitOfWork; no independent commits here.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from sqlalchemy import func, select, text, update

from migration_intake.persistence.models import Intake

if TYPE_CHECKING:
    from datetime import datetime

    from sqlalchemy.engine import CursorResult
    from sqlalchemy.orm import Session

# Terminal states for "open intake" query.
_TERMINAL_INTAKE_STATES: tuple[str, ...] = ("FROZEN", "CANCELLED", "SUPERSEDED")


class IntakeRepository:
    """Persistence adapter for the Intake aggregate."""

    def __init__(self, session: Session) -> None:
        self._session = session

    # ------------------------------------------------------------------
    # Write operations
    # ------------------------------------------------------------------

    def add(
        self,
        intake_id: str,
        application_id: str,
        catalog_id: str,
        state: str,
        created_by_id: str,
        created_at: datetime,
    ) -> str:
        """
        Insert a new intake row and return ``intake_id``.

        ``updated_at`` defaults to ``created_at``; ``row_version`` starts at 1.
        """
        intake = Intake(
            id=intake_id,
            application_id=application_id,
            catalog_id=catalog_id,
            state=state,
            created_at=created_at,
            updated_at=created_at,
            row_version=1,
            content_epoch=1,
            created_by_id=created_by_id,
        )
        self._session.add(intake)
        self._session.flush()
        return intake_id

    def update_state(
        self,
        intake_id: str,
        new_state: str,
        expected_version: int,
        updated_at: datetime,
    ) -> bool:
        """
        Atomically update intake state using optimistic concurrency.

        Returns ``True`` on success (1 row affected), ``False`` on version
        mismatch (0 rows affected — concurrent conflict detected).
        """
        stmt = (
            update(Intake)
            .where(
                Intake.id == intake_id,
                Intake.row_version == expected_version,
            )
            .values(
                state=new_state,
                row_version=Intake.row_version + 1,
                content_epoch=Intake.content_epoch + 1,
                updated_at=updated_at,
            )
            .execution_options(synchronize_session=False)
        )
        result = cast("CursorResult[Any]", self._session.execute(stmt))
        return bool(result.rowcount == 1)

    def bump_content_epoch(self, intake_id: str) -> None:
        """Advance the canonical-content epoch in the caller's transaction."""
        result = self._session.execute(
            update(Intake)
            .where(Intake.id == intake_id)
            .values(content_epoch=Intake.content_epoch + 1)
            .execution_options(synchronize_session=False)
        )
        if result.rowcount != 1:
            raise RuntimeError(f"Intake {intake_id} not found for content epoch update")

    def lock_content_epoch(self, intake_id: str) -> None:
        """Lock an intake before a canonical write without changing its epoch."""
        result = self._session.execute(
            update(Intake)
            .where(Intake.id == intake_id)
            .values(content_epoch=Intake.content_epoch)
            .execution_options(synchronize_session=False)
        )
        if result.rowcount != 1:
            raise RuntimeError(f"Intake {intake_id} not found for content lock")

    def bump_application_content_epochs(self, application_id: str) -> None:
        """Advance every intake affected by a shared application identity edit."""
        self._session.execute(
            update(Intake)
            .where(Intake.application_id == application_id)
            .values(content_epoch=Intake.content_epoch + 1)
            .execution_options(synchronize_session=False)
        )

    def begin_capture_fence(self) -> None:
        """Acquire SQLite's write fence before canonical capture reads."""
        if self._session.get_bind().dialect.name == "sqlite":
            if self._session.in_transaction():
                raise RuntimeError("SQLite capture fence must be the first transaction operation")
            self._session.execute(text("BEGIN IMMEDIATE"))

    # ------------------------------------------------------------------
    # Read operations
    # ------------------------------------------------------------------

    def get(self, intake_id: str) -> dict[str, Any] | None:
        """Return the intake as a plain dict, or None if not found."""
        stmt = select(Intake).where(Intake.id == intake_id)
        intake = self._session.execute(stmt).scalar_one_or_none()
        if intake is None:
            return None
        return self._to_dict(intake)

    def get_for_update(self, intake_id: str) -> dict[str, Any] | None:
        """Return an intake under a dialect-supported write lock when available."""
        stmt = select(Intake).where(Intake.id == intake_id).with_for_update()
        intake = self._session.execute(stmt).scalar_one_or_none()
        if intake is None:
            return None
        return self._to_dict(intake)

    def get_open_intake_for_application(
        self, application_id: str
    ) -> dict[str, Any] | None:
        """
        Return the single open intake for an application, or None.

        "Open" means state is NOT one of FROZEN, CANCELLED, or SUPERSEDED.
        If multiple open intakes exist (data integrity issue), the first row
        returned by the DB is used; upper layers should ensure invariant.
        """
        stmt = select(Intake).where(
            Intake.application_id == application_id,
            Intake.state.not_in(_TERMINAL_INTAKE_STATES),
        )
        intake = self._session.execute(stmt).scalar_one_or_none()
        if intake is None:
            return None
        return self._to_dict(intake)

    def list_for_application(self, application_id: str) -> list[dict[str, Any]]:
        """Return all intakes for an application, newest first."""
        stmt = (
            select(Intake)
            .where(Intake.application_id == application_id)
            .order_by(Intake.created_at.desc(), Intake.id.desc())
        )
        intakes = self._session.execute(stmt).scalars().all()
        return [self._to_dict(intake) for intake in intakes]

    def count_by_catalog_id(self, catalog_id: str) -> int:
        """Return the number of intakes pinned to the given catalog release."""
        stmt = select(func.count()).select_from(Intake).where(
            Intake.catalog_id == catalog_id
        )
        return int(self._session.execute(stmt).scalar_one())

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _to_dict(intake: Intake) -> dict[str, Any]:
        return {
            "id": str(intake.id),
            "application_id": str(intake.application_id),
            "catalog_id": str(intake.catalog_id),
            "state": intake.state,
            "created_at": intake.created_at,
            "updated_at": intake.updated_at,
            "row_version": intake.row_version,
            "content_epoch": intake.content_epoch,
            "created_by_id": str(intake.created_by_id),
        }
