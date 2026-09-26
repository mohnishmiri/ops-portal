"""
WaveUtilRepository — P05 (Evidence and WaveUtil Persistence).

Design rules (Architecture sections 31, 38):
- Returns plain dicts, never ORM entity instances.
- Session is owned by the UnitOfWork; no independent commits here.
- Insertion cycle for (wave_util_rows, wave_util_revisions) is broken by:
    1. add_row()                — inserts row with current_rev_id=None
    2. add_revision()           — inserts revision
    3. advance_current_pointer() — sets current_rev_id and increments row_version
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from migration_intake.persistence.models_evidence import WaveUtilRevision, WaveUtilRow
from migration_intake.persistence.repositories.intakes import IntakeRepository


class WaveUtilRepository:
    """
    Persistence adapter for WaveUtilRow and WaveUtilRevision records.

    All methods operate on the session provided at construction time.
    The owning UnitOfWork controls when/whether to commit.
    """

    def __init__(self, session: Session) -> None:
        self._session = session

    # ------------------------------------------------------------------
    # Write operations
    # ------------------------------------------------------------------

    def add_row(
        self,
        *,
        row_id: str,
        application_id: str,
        intake_id: str | None,
        server_name: str,
        normalized_server_name: str,
        environment: str | None,
        scope: str | None,
        created_at: datetime,
        created_by_id: str,
    ) -> dict[str, Any]:
        """
        Insert a wave_util_rows row with current_rev_id=None.

        Returns a plain dict of the inserted row.  Callers must call
        ``add_revision`` then ``advance_current_pointer`` to link the first
        revision, then commit via the owning UnitOfWork.

        Raises:
            sqlalchemy.exc.IntegrityError: on duplicate
            (application_id, normalized_server_name).
        """
        if intake_id is not None:
            IntakeRepository(self._session).lock_content_epoch(intake_id)
        row = WaveUtilRow(
            id=row_id,
            application_id=application_id,
            intake_id=intake_id,
            server_name=server_name,
            normalized_server_name=normalized_server_name,
            environment=environment,
            scope=scope,
            state="ACTIVE",
            current_rev_id=None,
            created_at=created_at,
            updated_at=created_at,
            row_version=1,
            created_by_id=created_by_id,
        )
        self._session.add(row)
        self._session.flush()
        return self._row_to_dict(row)

    def add_revision(
        self,
        *,
        revision_id: str,
        row_id: str,
        revision_number: int,
        field_values_json: dict[str, Any],
        authored_at: datetime,
        authored_by_id: str,
    ) -> dict[str, Any]:
        """
        Insert a wave_util_revisions row (append-only).

        Returns a plain dict of the inserted revision.

        Raises:
            sqlalchemy.exc.IntegrityError: on duplicate (row_id, revision_number).
        """
        intake_id = self._session.execute(
            select(WaveUtilRow.intake_id).where(WaveUtilRow.id == row_id)
        ).scalar_one_or_none()
        if intake_id is not None:
            IntakeRepository(self._session).lock_content_epoch(str(intake_id))
        revision = WaveUtilRevision(
            id=revision_id,
            row_id=row_id,
            revision_number=revision_number,
            field_values_json=field_values_json,
            authored_at=authored_at,
            authored_by_id=authored_by_id,
        )
        self._session.add(revision)
        self._session.flush()
        return self._revision_to_dict(revision)

    def advance_current_pointer(self, row_id: str, revision_id: str) -> None:
        """
        Set wave_util_rows.current_rev_id = revision_id and increment row_version.

        Must be called after ``add_revision`` to complete the cycle:
          add_row → add_revision → advance_current_pointer → commit.
        """
        stmt = (
            update(WaveUtilRow)
            .where(WaveUtilRow.id == row_id)
            .values(
                current_rev_id=revision_id,
                row_version=WaveUtilRow.row_version + 1,
            )
            .execution_options(synchronize_session=False)
        )
        result = self._session.execute(stmt)
        if result.rowcount != 1:
            raise RuntimeError(f"WaveUtil row {row_id} not found")
        intake_id = self._session.execute(
            select(WaveUtilRow.intake_id).where(WaveUtilRow.id == row_id)
        ).scalar_one_or_none()
        if intake_id is not None:
            IntakeRepository(self._session).bump_content_epoch(str(intake_id))

    def retire_row(
        self,
        *,
        row_id: str,
        rationale: str,
        evidence_reference: str | None,
        retired_at: datetime,
        retired_by_id: str,
    ) -> None:
        """
        Retire a WaveUtil row with rationale and evidence reference.

        Sets state to RETIRED and increments row_version.
        """
        intake_id = self._session.execute(
            select(WaveUtilRow.intake_id).where(WaveUtilRow.id == row_id)
        ).scalar_one_or_none()
        if intake_id is not None:
            IntakeRepository(self._session).lock_content_epoch(str(intake_id))
        stmt = (
            update(WaveUtilRow)
            .where(WaveUtilRow.id == row_id)
            .values(
                state="RETIRED",
                updated_at=retired_at,
                row_version=WaveUtilRow.row_version + 1,
            )
            .execution_options(synchronize_session=False)
        )
        result = self._session.execute(stmt)
        if result.rowcount != 1:
            raise RuntimeError(f"WaveUtil row {row_id} not found")
        if intake_id is not None:
            IntakeRepository(self._session).bump_content_epoch(str(intake_id))

    # ------------------------------------------------------------------
    # Read operations
    # ------------------------------------------------------------------

    def get_row(self, row_id: str) -> dict[str, Any] | None:
        """Return the wave_util_rows row as a plain dict, or None if not found."""
        stmt = select(WaveUtilRow).where(WaveUtilRow.id == row_id)
        row = self._session.execute(stmt).scalar_one_or_none()
        if row is None:
            return None
        return self._row_to_dict(row)

    def get_by_normalized_name(
        self, application_id: str, normalized_server_name: str
    ) -> dict[str, Any] | None:
        """Return the row for (application_id, normalized_server_name), or None."""
        stmt = select(WaveUtilRow).where(
            WaveUtilRow.application_id == application_id,
            WaveUtilRow.normalized_server_name == normalized_server_name,
        )
        row = self._session.execute(stmt).scalar_one_or_none()
        if row is None:
            return None
        return self._row_to_dict(row)

    def get_current_revision(self, row_id: str) -> dict[str, Any] | None:
        """
        Return the current revision plain dict for the given row, or None.

        Looks up the row's current_rev_id then fetches that revision.
        Returns None when the row does not exist or current_rev_id is NULL.
        """
        row_stmt = select(WaveUtilRow).where(WaveUtilRow.id == row_id)
        row = self._session.execute(row_stmt).scalar_one_or_none()
        if row is None or row.current_rev_id is None:
            return None

        rev_stmt = select(WaveUtilRevision).where(
            WaveUtilRevision.id == row.current_rev_id
        )
        revision = self._session.execute(rev_stmt).scalar_one_or_none()
        if revision is None:
            return None
        return self._revision_to_dict(revision)

    def list_rows_for_application(
        self, application_id: str, state: str = "ACTIVE"
    ) -> list[dict[str, Any]]:
        """Return all rows for the application, filtered by state (default ACTIVE)."""
        stmt = select(WaveUtilRow).where(
            WaveUtilRow.application_id == application_id,
            WaveUtilRow.state == state,
        )
        rows = self._session.execute(stmt).scalars().all()
        return [self._row_to_dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _row_to_dict(row: WaveUtilRow) -> dict[str, Any]:
        """Convert a WaveUtilRow ORM row to a plain dict."""
        return {
            "id": str(row.id),
            "application_id": str(row.application_id),
            "intake_id": str(row.intake_id) if row.intake_id is not None else None,
            "server_name": row.server_name,
            "normalized_server_name": row.normalized_server_name,
            "environment": row.environment,
            "scope": row.scope,
            "state": row.state,
            "current_rev_id": (
                str(row.current_rev_id) if row.current_rev_id is not None else None
            ),
            "created_at": row.created_at,
            "updated_at": row.updated_at,
            "row_version": row.row_version,
            "created_by_id": str(row.created_by_id),
        }

    @staticmethod
    def _revision_to_dict(revision: WaveUtilRevision) -> dict[str, Any]:
        """Convert a WaveUtilRevision ORM row to a plain dict."""
        return {
            "id": str(revision.id),
            "row_id": str(revision.row_id),
            "revision_number": revision.revision_number,
            "field_values_json": revision.field_values_json,
            "authored_at": revision.authored_at,
            "authored_by_id": str(revision.authored_by_id),
        }
