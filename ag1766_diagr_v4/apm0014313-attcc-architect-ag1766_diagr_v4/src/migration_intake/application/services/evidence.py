"""
Evidence upload and query service — E02.

Architecture rules applied here (section 25.3):

- Validates size_bytes BEFORE any IO (fail-fast).
- Validates media_type BEFORE any IO.
- Streams bytes to FilesystemStore (content-addressed, idempotent).
- Deduplicates by application/intake/storage_key: the same content may be
    reused by another application while repeated uploads stay idempotent.
- On metadata failure after a successful store, logs the orphan storage key
  but does NOT delete the blob (another record may share the same content).
- Returns plain dicts — no ORM entities leave this module.
"""

from __future__ import annotations

import io
import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from migration_intake.application.dto import ActorContext
from migration_intake.application.errors import (
    EvidenceMediaTypeNotAllowedError,
    EvidenceTooLargeError,
)
from migration_intake.persistence.models import Actor
from migration_intake.persistence.repositories.evidence import EvidenceRepository
from migration_intake.storage.filesystem import FilesystemStore

_log = logging.getLogger(__name__)

_MAX_SIZE_BYTES: int = 50 * 1024 * 1024  # 50 MB

_ALLOWED_MEDIA_TYPES: frozenset[str] = frozenset(
    {
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",  # .xlsx
        "application/vnd.ms-excel",  # .xls
        "text/csv",  # .csv
        "application/csv",  # .csv (alternative)
        "text/plain",  # .txt, .csv (some browsers)
        "application/octet-stream",  # fallback
    }
)


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _ensure_actor(session, actor: ActorContext, now: datetime) -> None:
    """
    Insert the actor row if it does not already exist.

    Operates on the supplied session; does not commit.
    """
    stmt = select(Actor).where(Actor.id == actor.actor_id)
    existing = session.execute(stmt).scalar_one_or_none()
    if existing is None:
        actor_row = Actor(
            id=actor.actor_id,
            display_name=actor.display_name or "Unknown",
            attuid=None,
            created_at=now,
        )
        session.add(actor_row)
        session.flush()


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class EvidenceService:
    """
    Coordinates evidence upload and query use cases — E02.

    Each public command/query opens its own session and returns plain dicts.
    The FilesystemStore is content-addressed and idempotent; the service layer
    adds an application/intake-scoped deduplication guard at the database level.
    """

    def __init__(
        self, session_factory: sessionmaker, evidence_store: FilesystemStore
    ) -> None:
        self._session_factory = session_factory
        self._store = evidence_store

    # ------------------------------------------------------------------
    # upload_evidence  (section 25.3)
    # ------------------------------------------------------------------

    def upload_evidence(
        self,
        stream: io.IOBase,
        filename: str,
        media_type: str,
        size_bytes: int,
        application_id: str,
        intake_id: str | None,
        actor: ActorContext,
    ) -> dict[str, Any]:
        """
        Stream evidence bytes to the store and create an EvidenceItem record.

        Steps:
        1. Validate size_bytes — fail-fast BEFORE any IO.
        2. Validate media_type — fail-fast BEFORE any IO.
        3. Stream bytes to FilesystemStore; receive StorageReceipt.
        4. Open DB session; check deduplication by application/intake/storage_key.
           - If duplicate: return existing evidence_id with deduplicated=True.
        5. Ensure actor row exists (upsert pattern).
        6. Insert EvidenceItem row; commit.
        7. On metadata failure: log the orphan storage_key but do NOT delete
           the blob (content-addressed — another record may share it).

        Returns:
            dict with keys: evidence_id, storage_key, sha256_hex, deduplicated.

        Raises:
            EvidenceTooLargeError: size_bytes is 0 or exceeds 50 MB.
            EvidenceMediaTypeNotAllowedError: media_type not in allowed set.
        """
        # -- 1. size guard (fail-fast, before any IO) ---------------------
        if size_bytes <= 0 or size_bytes > _MAX_SIZE_BYTES:
            raise EvidenceTooLargeError(
                f"Evidence size {size_bytes:,} bytes exceeds the maximum "
                f"allowed size of {_MAX_SIZE_BYTES:,} bytes "
                f"(or is non-positive)."
            )

        # -- 2. media type guard ------------------------------------------
        if media_type not in _ALLOWED_MEDIA_TYPES:
            raise EvidenceMediaTypeNotAllowedError(
                f"Media type {media_type!r} is not in the allowed set: "
                f"{sorted(_ALLOWED_MEDIA_TYPES)!r}."
            )

        # -- 3. stream bytes to store ------------------------------------
        receipt = self._store.store(stream, filename)

        # -- 4-6. deduplication + metadata insert ------------------------
        now = datetime.now(tz=UTC)
        evidence_id = str(uuid.uuid4())

        session = self._session_factory()
        try:
            repo = EvidenceRepository(session)

            # Deduplication is scoped to the owning application and intake.
            existing = repo.get_by_storage_key(
                receipt.storage_key,
                application_id=application_id,
                intake_id=intake_id,
            )
            if existing is not None:
                return {
                    "evidence_id": existing["id"],
                    "storage_key": existing["storage_key"],
                    "sha256_hex": existing["sha256_hex"],
                    "deduplicated": True,
                }

            # Ensure actor row is present (FK constraint)
            _ensure_actor(session, actor, now)

            repo.add(
                evidence_id=evidence_id,
                application_id=application_id,
                intake_id=intake_id,
                storage_key=receipt.storage_key,
                sha256_hex=receipt.sha256_hex,
                size_bytes=receipt.size_bytes,
                media_type=media_type,
                original_filename=filename,
                created_at=now,
                created_by_id=actor.actor_id,
            )
            session.commit()

        except Exception:
            session.rollback()
            # Log the orphan: blob stored but metadata write failed.
            # Do NOT delete the blob — content-addressed storage means
            # another record may reference the same storage_key.
            _log.error(
                "Evidence metadata insert failed after successful store. "
                "Orphan storage_key=%r (sha256=%r). "
                "Blob retained — manual reconciliation may be required.",
                receipt.storage_key,
                receipt.sha256_hex,
            )
            raise
        finally:
            session.close()

        return {
            "evidence_id": evidence_id,
            "storage_key": receipt.storage_key,
            "sha256_hex": receipt.sha256_hex,
            "deduplicated": False,
        }

    # ------------------------------------------------------------------
    # get_evidence_list  (section 25.3)
    # ------------------------------------------------------------------

    def get_evidence_list(self, intake_id: str) -> list[dict[str, Any]]:
        """
        Return all ACTIVE evidence items attached to the given intake.

        Args:
            intake_id: UUID string of the intake.

        Returns:
            List of plain dicts, each representing one ACTIVE EvidenceItem.
        """
        session = self._session_factory()
        try:
            repo = EvidenceRepository(session)
            return repo.list_for_intake(intake_id)
        finally:
            session.close()

    # ------------------------------------------------------------------
    # get_evidence  (section 25.3)
    # ------------------------------------------------------------------

    def get_evidence(self, evidence_id: str) -> dict[str, Any] | None:
        """
        Return a single evidence item by ID, or None if not found.

        Args:
            evidence_id: UUID string of the evidence item.

        Returns:
            Plain dict representing the EvidenceItem, or None.
        """
        session = self._session_factory()
        try:
            repo = EvidenceRepository(session)
            return repo.get(evidence_id)
        finally:
            session.close()
