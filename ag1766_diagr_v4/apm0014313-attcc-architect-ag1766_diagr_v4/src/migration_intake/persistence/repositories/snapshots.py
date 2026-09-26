"""
SnapshotRepository — P07 (Snapshot Persistence).

Design rules (Architecture sections 31, 38):
- Returns plain dicts, never ORM entity instances.
- Session is owned by the UnitOfWork; no independent commits here.
- Snapshots are immutable: no update or delete methods.
- Repository APIs prevent mutation through normal application paths.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from migration_intake.persistence.models_snapshots import IntakeSnapshot


class SnapshotRepository:
    """
    Persistence adapter for IntakeSnapshot records.

    All methods operate on the session provided at construction time.
    The owning UnitOfWork controls when/whether to commit.

    Invariants:
    - Snapshots are immutable once created.
    - No update or delete methods are provided.
    - Each intake can have at most one snapshot.
    """

    def __init__(self, session: Session) -> None:
        self._session = session

    # ------------------------------------------------------------------
    # Write operations (create only, no update/delete)
    # ------------------------------------------------------------------

    def create_snapshot(
        self,
        *,
        snapshot_id: str,
        intake_id: str,
        catalog_id: str,
        schema_version: str,
        catalog_sha256: str,
        canonical_json: str,
        sha256_hex: str,
        created_at: datetime,
        created_by_id: str,
    ) -> dict[str, Any]:
        """
        Create an immutable snapshot for a frozen intake.

        Returns a plain dict of the created snapshot.

        Raises:
            sqlalchemy.exc.IntegrityError: if intake already has a snapshot
                (unique constraint violation) or FK constraint fails.
        """
        snapshot = IntakeSnapshot(
            id=snapshot_id,
            intake_id=intake_id,
            catalog_id=catalog_id,
            schema_version=schema_version,
            catalog_sha256=catalog_sha256,
            canonical_json=canonical_json,
            sha256_hex=sha256_hex,
            created_at=created_at,
            created_by_id=created_by_id,
        )
        self._session.add(snapshot)
        self._session.flush()
        return self._to_dict(snapshot)

    # ------------------------------------------------------------------
    # Read operations
    # ------------------------------------------------------------------

    def get_by_id(self, snapshot_id: str) -> dict[str, Any] | None:
        """Return the snapshot as a plain dict, or None if not found."""
        stmt = select(IntakeSnapshot).where(IntakeSnapshot.id == snapshot_id)
        snapshot = self._session.execute(stmt).scalar_one_or_none()
        if snapshot is None:
            return None
        return self._to_dict(snapshot)

    def get_by_intake_id(self, intake_id: str) -> dict[str, Any] | None:
        """Return the snapshot for an intake, or None if not found."""
        stmt = select(IntakeSnapshot).where(IntakeSnapshot.intake_id == intake_id)
        snapshot = self._session.execute(stmt).scalar_one_or_none()
        if snapshot is None:
            return None
        return self._to_dict(snapshot)

    def get_by_hash(self, sha256_hex: str) -> dict[str, Any] | None:
        """Return the snapshot with the given hash, or None if not found."""
        stmt = select(IntakeSnapshot).where(IntakeSnapshot.sha256_hex == sha256_hex)
        snapshot = self._session.execute(stmt).scalar_one_or_none()
        if snapshot is None:
            return None
        return self._to_dict(snapshot)

    def exists_for_intake(self, intake_id: str) -> bool:
        """Check if a snapshot exists for the given intake."""
        stmt = select(IntakeSnapshot.id).where(IntakeSnapshot.intake_id == intake_id)
        result = self._session.execute(stmt).scalar_one_or_none()
        return result is not None

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _to_dict(snapshot: IntakeSnapshot) -> dict[str, Any]:
        """Convert an IntakeSnapshot ORM row to a plain dict."""
        return {
            "id": str(snapshot.id),
            "intake_id": str(snapshot.intake_id),
            "catalog_id": str(snapshot.catalog_id),
            "schema_version": snapshot.schema_version,
            "catalog_sha256": snapshot.catalog_sha256,
            "canonical_json": snapshot.canonical_json,
            "sha256_hex": snapshot.sha256_hex,
            "created_at": snapshot.created_at,
            "created_by_id": str(snapshot.created_by_id),
        }
