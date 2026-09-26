"""
EvidenceRepository — P05 (Evidence and WaveUtil Persistence).

Design rules (Architecture sections 31, 38):
- Returns plain dicts, never ORM entity instances.
- Session is owned by the UnitOfWork; no independent commits here.
- Methods accept domain-typed arguments (str UUIDs, datetime, int, str).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from migration_intake.persistence.models_candidates import (
    AnswerEvidenceLink,
    Candidate,
    CandidateFinding,
)
from migration_intake.persistence.models_evidence import EvidenceItem
from migration_intake.persistence.models_imports import ImportFinding, ImportRun, ImportSheetResult


class EvidenceRepository:
    """
    Persistence adapter for EvidenceItem records.

    All methods operate on the session provided at construction time.
    The owning UnitOfWork controls when/whether to commit.
    """

    def __init__(self, session: Session) -> None:
        self._session = session

    # ------------------------------------------------------------------
    # Write operations
    # ------------------------------------------------------------------

    def add(
        self,
        *,
        evidence_id: str,
        application_id: str,
        intake_id: str | None,
        storage_key: str,
        sha256_hex: str,
        size_bytes: int,
        media_type: str,
        original_filename: str | None,
        created_at: datetime,
        created_by_id: str,
    ) -> dict[str, Any]:
        """
        Insert an evidence_items row.

        Returns a plain dict of the inserted row.  The caller must commit the
        owning transaction to persist the change.

        Raises:
            sqlalchemy.exc.IntegrityError: if ``storage_key`` is not unique.
        """
        item = EvidenceItem(
            id=evidence_id,
            application_id=application_id,
            intake_id=intake_id,
            storage_key=storage_key,
            sha256_hex=sha256_hex,
            size_bytes=size_bytes,
            media_type=media_type,
            original_filename=original_filename,
            state="ACTIVE",
            created_at=created_at,
            created_by_id=created_by_id,
        )
        self._session.add(item)
        self._session.flush()
        return self._to_dict(item)

    def update_state(
        self,
        evidence_id: str,
        new_state: str,
        expected_version: int | None = None,
    ) -> bool:
        """
        Update the state field for a given evidence item.

        Args:
            evidence_id: UUID string of the evidence item.
            new_state: Target state value (e.g. "QUARANTINED", "DELETED").
            expected_version: Reserved for future optimistic-concurrency support;
                currently unused (evidence_items has no row_version column).

        Returns:
            ``True`` if exactly one row was updated; ``False`` if not found.
        """
        stmt = (
            update(EvidenceItem)
            .where(EvidenceItem.id == evidence_id)
            .values(state=new_state)
            .execution_options(synchronize_session=False)
        )
        result = self._session.execute(stmt)
        return result.rowcount == 1

    def purge_import(self, evidence_id: str, application_id: str, intake_id: str) -> bool:
        """Delete an unaccepted evidence import aggregate in the current scope."""
        evidence = self._session.execute(
            select(EvidenceItem).where(
                EvidenceItem.id == evidence_id,
                EvidenceItem.application_id == application_id,
                EvidenceItem.intake_id == intake_id,
            )
        ).scalar_one_or_none()
        if evidence is None:
            return False

        run_ids = list(
            self._session.execute(
                select(ImportRun.id).where(ImportRun.evidence_item_id == evidence_id)
            ).scalars()
        )
        candidate_ids = list(
            self._session.execute(
                select(Candidate.id).where(Candidate.evidence_item_id == evidence_id)
            ).scalars()
        )
        candidates = list(
            self._session.execute(
                select(Candidate).where(Candidate.id.in_(candidate_ids))
            ).scalars()
        ) if candidate_ids else []
        if any(candidate.state != "PROPOSED" for candidate in candidates):
            raise ValueError("This evidence has reviewed proposals and cannot be purged.")
        if candidate_ids and self._session.execute(
            select(AnswerEvidenceLink.id).where(
                AnswerEvidenceLink.evidence_item_id == evidence_id
            )
        ).first() is not None:
            raise ValueError("This evidence is linked to accepted answers and cannot be purged.")
        if candidate_ids:
            self._session.execute(
                delete(CandidateFinding).where(CandidateFinding.candidate_id.in_(candidate_ids))
            )
            self._session.execute(
                delete(AnswerEvidenceLink).where(AnswerEvidenceLink.candidate_id.in_(candidate_ids))
            )
            self._session.execute(delete(Candidate).where(Candidate.id.in_(candidate_ids)))
        if run_ids:
            self._session.execute(delete(ImportFinding).where(ImportFinding.run_id.in_(run_ids)))
            self._session.execute(delete(ImportSheetResult).where(ImportSheetResult.run_id.in_(run_ids)))
            self._session.execute(delete(ImportRun).where(ImportRun.id.in_(run_ids)))
        self._session.delete(evidence)
        return True

    # ------------------------------------------------------------------
    # Read operations
    # ------------------------------------------------------------------

    def get(self, evidence_id: str) -> dict[str, Any] | None:
        """Return the evidence item as a plain dict, or None if not found."""
        stmt = select(EvidenceItem).where(EvidenceItem.id == evidence_id)
        item = self._session.execute(stmt).scalar_one_or_none()
        if item is None:
            return None
        return self._to_dict(item)

    def get_by_storage_key(
        self,
        storage_key: str,
        application_id: str | None = None,
        intake_id: str | None = None,
    ) -> dict[str, Any] | None:
        """Return matching evidence within an application/intake scope."""
        conditions = [EvidenceItem.storage_key == storage_key]
        if application_id is not None:
            conditions.append(EvidenceItem.application_id == application_id)
        if intake_id is not None:
            conditions.append(EvidenceItem.intake_id == intake_id)
        else:
            conditions.append(EvidenceItem.intake_id.is_(None))
        stmt = select(EvidenceItem).where(*conditions)
        item = self._session.execute(stmt).scalar_one_or_none()
        if item is None:
            return None
        return self._to_dict(item)

    def list_for_intake(self, intake_id: str) -> list[dict[str, Any]]:
        """Return all ACTIVE evidence items attached to the given intake."""
        stmt = (
            select(EvidenceItem)
            .where(
                EvidenceItem.intake_id == intake_id,
                EvidenceItem.state == "ACTIVE",
            )
        )
        rows = self._session.execute(stmt).scalars().all()
        return [self._to_dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _to_dict(item: EvidenceItem) -> dict[str, Any]:
        """Convert an EvidenceItem ORM row to a plain dict."""
        return {
            "id": str(item.id),
            "application_id": str(item.application_id),
            "intake_id": str(item.intake_id) if item.intake_id is not None else None,
            "storage_key": item.storage_key,
            "sha256_hex": item.sha256_hex,
            "size_bytes": item.size_bytes,
            "media_type": item.media_type,
            "original_filename": item.original_filename,
            "state": item.state,
            "created_at": item.created_at,
            "created_by_id": str(item.created_by_id),
        }
