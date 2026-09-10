"""
Certificate Sync Service — caches Keyfactor Command data into PostgreSQL.

Provides:
- Full sync: all collections + their certificates → PG
- Per-collection sync: refresh a single collection's certificates
- Fast list/collection queries served from PG (DB-first, live fallback)
- Sync-status tracking and staleness checks for startup/scheduled syncs
- Robust, best-effort behavior: a failing collection never aborts the whole sync
"""

from datetime import UTC, datetime, timedelta
from typing import Any

import structlog
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.database import (
    CertificateCollectionSnapshot,
    CertificateSnapshot,
    CertificateSyncStatus,
)
from app.services.keyfactor_service import CertificateService, CertificateServiceError

logger = structlog.get_logger(__name__)

# Sync tuning
_PAGE_SIZE = 200  # Keyfactor page size while walking a collection
_MAX_CERTS_PER_COLLECTION = 10000  # Safety cap so one huge collection can't stall a sync
# Keyfactor lookups a single collection sync will spend confirming that a
# certificate missing from the collection really was deleted, rather than merely
# revoked out of the saved search.
_MAX_ABSENCE_CHECKS = 50
_STALE_THRESHOLD_MINUTES = 60
_RUNNING_SYNC_TIMEOUT_MINUTES = 30  # A 'running' row older than this is treated as abandoned


class CertificateSyncService:
    """Manages syncing Keyfactor certificate data to PostgreSQL."""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.service = CertificateService()

    # ── Sync ───────────────────────────────────────────────────────────

    async def full_sync(self, *, triggered_by: str = "manual") -> dict[str, Any]:
        """Sync all collections and their certificates from Keyfactor → PG."""
        await self._expire_abandoned_running_rows()
        record = CertificateSyncStatus(sync_type="full", status="running", triggered_by=triggered_by)
        self.db.add(record)
        await self.db.commit()
        await self.db.refresh(record)
        record_id, started_at = record.id, record.started_at

        collections_synced = 0
        certificates_synced = 0
        failures: list[str] = []
        final_status = "completed"
        error_message: str | None = None
        try:
            collections = await self.service.list_collections()
            await self._replace_collections(collections)
            collections_synced = len(collections)

            for col in collections:
                col_id = col.get("id")
                if col_id is None:
                    continue
                try:
                    certificates_synced += await self._sync_collection_certs(int(col_id), col.get("name") or "")
                except Exception as exc:
                    # Roll back the poisoned transaction so the next collection — and
                    # the final status write — start from a clean session.
                    await self.db.rollback()
                    failures.append(str(col.get("name") or col_id))
                    logger.warning("cert_sync_collection_failed", collection=col.get("name"), error=str(exc)[:300])

            if failures:
                final_status = "partial" if certificates_synced > 0 else "failed"
                error_message = ("Failed collections: " + ", ".join(failures))[:500]

            # The fresh snapshot is the only place escrow pointers can learn a
            # certificate's expiry, so reconcile (backfill + purge expired keys)
            # right after it lands. Never allowed to fail the sync.
            try:
                from app.services.certificate_escrow_service import CertificateEscrowService

                await CertificateEscrowService(self.db).reconcile()
            except Exception as exc:
                await self.db.rollback()
                logger.warning("cert_escrow_reconcile_failed", error=str(exc)[:300])
        except CertificateServiceError as exc:
            await self.db.rollback()
            final_status = "failed"
            error_message = exc.message[:500]
            logger.warning("cert_sync_failed", error=exc.message)
        except Exception as exc:
            await self.db.rollback()
            final_status = "failed"
            error_message = str(exc)[:500]
            logger.error("cert_sync_unexpected_error", error=str(exc)[:300])

        completed_at = datetime.utcnow()
        await self._finalize_status(
            record_id,
            status=final_status,
            completed_at=completed_at,
            collections_synced=collections_synced,
            certificates_synced=certificates_synced,
            error_message=error_message,
        )
        return self._result_dict(
            record_id,
            "full",
            final_status,
            started_at,
            completed_at,
            collections_synced,
            certificates_synced,
            error_message,
            triggered_by,
        )

    async def sync_collection(self, collection_id: int, *, triggered_by: str = "manual") -> dict[str, Any]:
        """Refresh a single collection's certificates from Keyfactor → PG."""
        await self._expire_abandoned_running_rows()
        record = CertificateSyncStatus(sync_type="collection", status="running", triggered_by=triggered_by)
        self.db.add(record)
        await self.db.commit()
        await self.db.refresh(record)
        record_id, started_at = record.id, record.started_at

        certificates_synced = 0
        collections_synced = 0
        final_status = "completed"
        error_message: str | None = None
        try:
            name = await self._refresh_collection_meta(collection_id)
            certificates_synced = await self._sync_collection_certs(collection_id, name)
            collections_synced = 1
        except CertificateServiceError as exc:
            await self.db.rollback()
            final_status = "failed"
            error_message = exc.message[:500]
            logger.warning("cert_sync_collection_failed", collection_id=collection_id, error=exc.message)
        except Exception as exc:
            await self.db.rollback()
            final_status = "failed"
            error_message = str(exc)[:500]
            logger.error("cert_sync_collection_unexpected", collection_id=collection_id, error=str(exc)[:300])

        completed_at = datetime.utcnow()
        await self._finalize_status(
            record_id,
            status=final_status,
            completed_at=completed_at,
            collections_synced=collections_synced,
            certificates_synced=certificates_synced,
            error_message=error_message,
        )
        return self._result_dict(
            record_id,
            "collection",
            final_status,
            started_at,
            completed_at,
            collections_synced,
            certificates_synced,
            error_message,
            triggered_by,
        )

    async def _finalize_status(
        self,
        record_id: int,
        *,
        status: str,
        completed_at: datetime,
        collections_synced: int,
        certificates_synced: int,
        error_message: str | None,
    ) -> None:
        """Write the terminal sync-status row via a Core UPDATE.

        Deliberately avoids mutating the ORM ``record`` object: a mid-sync
        rollback expires that instance, and reading its attributes afterwards
        would trigger disallowed async lazy-load IO. A status-write failure is
        swallowed so it can never surface to the caller as a 500.
        """
        try:
            await self.db.execute(
                update(CertificateSyncStatus)
                .where(CertificateSyncStatus.id == record_id)
                .values(
                    status=status,
                    completed_at=completed_at,
                    collections_synced=collections_synced,
                    certificates_synced=certificates_synced,
                    error_message=error_message,
                )
            )
            await self.db.commit()
        except Exception as exc:
            await self.db.rollback()
            logger.error("cert_sync_status_write_failed", record_id=record_id, error=str(exc)[:300])

    @staticmethod
    def _result_dict(
        record_id: int,
        sync_type: str,
        status: str,
        started_at: datetime | None,
        completed_at: datetime | None,
        collections_synced: int,
        certificates_synced: int,
        error_message: str | None,
        triggered_by: str | None,
    ) -> dict[str, Any]:
        return {
            "id": record_id,
            "sync_type": sync_type,
            "status": status,
            "started_at": started_at.isoformat() if started_at else None,
            "completed_at": completed_at.isoformat() if completed_at else None,
            "collections_synced": collections_synced,
            "certificates_synced": certificates_synced,
            "error_message": error_message,
            "triggered_by": triggered_by,
        }

    async def _sync_collection_certs(self, collection_id: int, collection_name: str) -> int:
        """Replace a collection's cached certificates with a fresh Keyfactor snapshot.

        Also persists the authoritative collection size (Keyfactor's ``x-total-count``,
        surfaced as ``total``) onto the collection snapshot so tiles show an accurate
        certificate count *before* the collection is opened — even for collections
        larger than the local cache cap.
        """
        collected: list[dict[str, Any]] = []
        keyfactor_total = 0
        page = 1
        while len(collected) < _MAX_CERTS_PER_COLLECTION:
            result = await self.service.list_certificates(
                query=None, page=page, page_size=_PAGE_SIZE, collection_id=collection_id
            )
            if page == 1:
                keyfactor_total = int(result.get("total") or 0)
            items = result.get("items", [])
            if not items:
                break
            collected.extend(items)
            if len(items) < _PAGE_SIZE:
                break
            page += 1

        now = datetime.utcnow()

        # An empty response is far more likely a transient Keyfactor failure
        # than every certificate in the collection disappearing at once. Both
        # the snapshot replacement and the orphan calculation below read
        # "absent from the response" as "gone", so acting on an empty one would
        # blank the active grid *and* mass soft-delete certificates that still
        # exist. Keep the last good snapshot instead.
        if not collected:
            existing = await self.db.execute(
                select(func.count(CertificateSnapshot.id))
                .where(CertificateSnapshot.collection_id == collection_id)
                .where(CertificateSnapshot.deleted_at.is_(None))
            )
            retained = existing.scalar() or 0
            if retained:
                logger.warning(
                    "cert_sync_empty_response_ignored",
                    collection_id=collection_id,
                    retained=retained,
                )
                return retained

        # De-duplicate by Keyfactor certificate id before insert: pagination
        # overlap or missing ids (which collapse to 0) would otherwise violate the
        # (collection_id, certificate_id) unique constraint and abort the flush.
        seen_ids: set[int] = set()
        unique_certs: list[dict[str, Any]] = []
        for cert in collected[:_MAX_CERTS_PER_COLLECTION]:
            cert_id = int(cert.get("id") or 0)
            if cert_id in seen_ids:
                continue
            seen_ids.add(cert_id)
            unique_certs.append(cert)

        # Only non-zero IDs are meaningful for soft-delete tracking;
        # certs with id=0 (missing Keyfactor ID) are kept for insertion but
        # excluded from the orphan / revival calculation.
        fresh_ids = {cid for cid in seen_ids if cid != 0}

        # ── Soft-delete certs no longer in Keyfactor ──────────────────
        # Fetch the IDs of currently active (non-deleted) rows so we know
        # which ones have disappeared since the last sync.
        active_result = await self.db.execute(
            select(CertificateSnapshot.certificate_id)
            .where(CertificateSnapshot.collection_id == collection_id)
            .where(CertificateSnapshot.deleted_at.is_(None))
        )
        active_ids: set[int] = {row[0] for row in active_result}

        # Only a complete snapshot can say anything about what is missing. If
        # the walk stopped short of Keyfactor's own total (a mid-pagination
        # failure) or hit the local cap, the missing ids were simply never
        # fetched.
        snapshot_complete = len(collected) < _MAX_CERTS_PER_COLLECTION and (
            not keyfactor_total or len(collected) >= keyfactor_total
        )
        missing_ids = (active_ids - fresh_ids) if snapshot_complete else set()
        if not snapshot_complete and active_ids - fresh_ids:
            logger.warning(
                "cert_sync_partial_snapshot_orphans_skipped",
                collection_id=collection_id,
                fetched=len(collected),
                keyfactor_total=keyfactor_total,
            )

        # Absence from a collection is not deletion, and this is where the
        # portal previously guessed. A collection is a saved search; revoking a
        # certificate drops it out of one while the certificate still exists.
        # Guessing filed real revocations under "Deleted". Keyfactor is asked
        # instead, so a row is only ever marked deleted on a definite 404.
        gone_ids, still_held = await self._classify_missing(missing_ids, collection_id=collection_id)
        if gone_ids:
            await self.db.execute(
                update(CertificateSnapshot)
                .where(CertificateSnapshot.collection_id == collection_id)
                .where(CertificateSnapshot.certificate_id.in_(list(gone_ids)))
                .values(deleted_at=now)
            )

        # Repair rows an earlier sync mis-filed: anything marked deleted that
        # Keyfactor still holds comes back, so existing bad data corrects itself
        # instead of needing a manual UPDATE.
        restored = await self._restore_mis_deleted(
            collection_id, budget=_MAX_ABSENCE_CHECKS - len(missing_ids), exclude=fresh_ids
        )
        still_held.update(restored)

        # ── Remove stale deleted rows for certs that reappeared ────────
        # A cert previously soft-deleted (e.g. removed temporarily) that is
        # now back in Keyfactor needs its deleted row cleaned up so the fresh
        # INSERT does not violate the (collection_id, certificate_id) UNIQUE
        # constraint.
        previously_deleted_result = await self.db.execute(
            select(CertificateSnapshot.certificate_id)
            .where(CertificateSnapshot.collection_id == collection_id)
            .where(CertificateSnapshot.deleted_at.isnot(None))
        )
        previously_deleted_ids: set[int] = {row[0] for row in previously_deleted_result}
        revived_ids = fresh_ids & previously_deleted_ids
        if revived_ids:
            await self.db.execute(
                delete(CertificateSnapshot)
                .where(CertificateSnapshot.collection_id == collection_id)
                .where(CertificateSnapshot.certificate_id.in_(list(revived_ids)))
                .where(CertificateSnapshot.deleted_at.isnot(None))
            )

        # ── Replace active snapshot ────────────────────────────────────
        # Certificates that left the collection but still exist are written back
        # from Keyfactor's own record, so their revoked flag is authoritative
        # rather than whatever the cache last believed.
        snapshot_certs = unique_certs + [still_held[cid] for cid in sorted(still_held)]
        await self.db.execute(
            delete(CertificateSnapshot)
            .where(CertificateSnapshot.collection_id == collection_id)
            .where(CertificateSnapshot.deleted_at.is_(None))
        )
        for cert in snapshot_certs:
            self.db.add(self._to_row(cert, collection_id, collection_name, now))
        # The tile must agree with the grid, and the grid counts cached rows.
        # Keyfactor's own collection total lags a renewal by some minutes, so
        # trusting it showed "32 certs" on the tile beside a grid listing 33.
        # It is only the better number when the walk was capped and the cache
        # holds a slice of a larger collection.
        truncated = len(collected) >= _MAX_CERTS_PER_COLLECTION
        # The card should predict the grid, and the grid shows active
        # certificates only — so preserved revoked rows are deliberately absent
        # from this count, as are any revoked certs the response carried.
        cached_rows = sum(1 for cert in snapshot_certs if not cert.get("revoked"))
        await self.db.execute(
            update(CertificateCollectionSnapshot)
            .where(CertificateCollectionSnapshot.collection_id == collection_id)
            .values(
                certificate_count=(keyfactor_total if truncated and keyfactor_total else cached_rows),
                synced_at=now,
            )
        )
        await self.db.commit()
        return len(unique_certs)

    async def _classify_missing(
        self, missing_ids: set[int], *, collection_id: int
    ) -> tuple[set[int], dict[int, dict[str, Any]]]:
        """Split certificates missing from a collection into gone vs still held.

        A collection is a saved search, so a certificate can leave it while
        still existing — revoking one does exactly that. Only Keyfactor can tell
        the two apart, so every missing id is looked up: a definite 404 means
        deleted, anything still returned merely left the collection.

        An id whose lookup fails for any other reason lands in neither set and
        is left untouched, because an outage must never read as a deletion.
        """
        if not missing_ids:
            return set(), {}
        if len(missing_ids) > _MAX_ABSENCE_CHECKS:
            # This many disappearing at once is a collection-definition change,
            # not a burst of deletions. Verifying is unaffordable and guessing
            # is what caused the problem, so nothing is marked deleted.
            logger.warning(
                "cert_sync_absence_check_skipped",
                collection_id=collection_id,
                missing=len(missing_ids),
                cap=_MAX_ABSENCE_CHECKS,
            )
            return set(), {}

        gone: set[int] = set()
        still_held: dict[int, dict[str, Any]] = {}
        for cert_id in sorted(missing_ids):
            try:
                still_held[cert_id] = await self.service.get_certificate(cert_id, collection_id=collection_id)
            except CertificateServiceError as exc:
                if exc.status_code == 404:
                    gone.add(cert_id)
                else:
                    logger.warning(
                        "cert_sync_absence_check_failed",
                        certificate_id=cert_id,
                        error=exc.message[:200],
                    )
            except Exception as exc:  # noqa: BLE001 - never infer deletion from a failure
                logger.warning("cert_sync_absence_check_error", certificate_id=cert_id, error=str(exc)[:200])
        return gone, still_held

    async def _restore_mis_deleted(
        self, collection_id: int, *, budget: int, exclude: set[int]
    ) -> dict[int, dict[str, Any]]:
        """Bring back soft-deleted rows that Keyfactor still holds.

        Earlier syncs inferred deletion from absence alone, so revoked
        certificates were filed under "Deleted". Re-checking those rows is what
        lets already-wrong data correct itself on the next sync rather than
        needing a hand-written UPDATE.

        Newest deletions are checked first, since those are the ones a user is
        most likely looking at right now.
        """
        if budget <= 0:
            return {}
        result = await self.db.execute(
            select(CertificateSnapshot.certificate_id)
            .where(CertificateSnapshot.collection_id == collection_id)
            .where(CertificateSnapshot.deleted_at.isnot(None))
            .order_by(CertificateSnapshot.deleted_at.desc())
            .limit(budget)
        )
        candidates = [row[0] for row in result if row[0] not in exclude]
        if not candidates:
            return {}

        restored: dict[int, dict[str, Any]] = {}
        for cert_id in candidates:
            try:
                restored[cert_id] = await self.service.get_certificate(cert_id, collection_id=collection_id)
            except CertificateServiceError as exc:
                if exc.status_code != 404:
                    logger.warning("cert_sync_restore_check_failed", certificate_id=cert_id, error=exc.message[:200])
            except Exception as exc:  # noqa: BLE001 - a failed check just leaves the row deleted
                logger.warning("cert_sync_restore_check_error", certificate_id=cert_id, error=str(exc)[:200])

        if restored:
            # Drop the deleted rows so the caller's re-insert does not collide
            # with the (collection_id, certificate_id) unique constraint.
            await self.db.execute(
                delete(CertificateSnapshot)
                .where(CertificateSnapshot.collection_id == collection_id)
                .where(CertificateSnapshot.certificate_id.in_(list(restored)))
                .where(CertificateSnapshot.deleted_at.isnot(None))
            )
            logger.info(
                "cert_sync_restored_mis_deleted",
                collection_id=collection_id,
                restored=len(restored),
            )
        return restored

    async def _replace_collections(self, collections: list[dict[str, Any]]) -> None:
        now = datetime.utcnow()
        await self.db.execute(delete(CertificateCollectionSnapshot))
        for col in collections:
            if col.get("id") is None:
                continue
            self.db.add(
                CertificateCollectionSnapshot(
                    collection_id=int(col["id"]),
                    name=col.get("name") or "",
                    description=col.get("description") or "",
                    query=col.get("query") or "",
                    certificate_count=int(col.get("certificate_count") or 0),
                    synced_at=now,
                )
            )
        await self.db.commit()

    async def _refresh_collection_meta(self, collection_id: int) -> str:
        """Upsert a single collection's metadata; returns its name."""
        collections = await self.service.list_collections()
        match = next((c for c in collections if c.get("id") == collection_id), None)
        name = (match or {}).get("name") or ""
        existing = await self.db.execute(
            select(CertificateCollectionSnapshot).where(CertificateCollectionSnapshot.collection_id == collection_id)
        )
        row = existing.scalar_one_or_none()
        now = datetime.utcnow()
        if row is None:
            self.db.add(
                CertificateCollectionSnapshot(
                    collection_id=collection_id,
                    name=name,
                    description=(match or {}).get("description") or "",
                    query=(match or {}).get("query") or "",
                    certificate_count=int((match or {}).get("certificate_count") or 0),
                    synced_at=now,
                )
            )
        elif match is not None:
            row.name = name
            row.description = match.get("description") or ""
            row.certificate_count = int(match.get("certificate_count") or 0)
            row.synced_at = now
        await self.db.commit()
        return name

    @staticmethod
    def _clip(value: Any, max_len: int) -> str:
        """Coerce to str and clip to a bounded column's max length.

        Keyfactor returns some fields (e.g. ``KeyUsage``) as ints/lists; feeding a
        non-str or over-long value into a ``String`` column raises an asyncpg
        ``DataError`` that poisons the whole sync transaction. Coercing + clipping
        keeps every row insertable.
        """
        if value is None:
            return ""
        text = value if isinstance(value, str) else str(value)
        return text[:max_len]

    @staticmethod
    def _int_or_none(value: Any) -> int | None:
        """Best-effort int coercion (Keyfactor sometimes sends numerics as strings)."""
        try:
            if value is None or (isinstance(value, str) and not value.strip()):
                return None
            return int(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _to_row(
        cert: dict[str, Any], collection_id: int, collection_name: str, synced_at: datetime
    ) -> CertificateSnapshot:
        clip = CertificateSyncService._clip
        int_or_none = CertificateSyncService._int_or_none
        sans = cert.get("sans")
        locations = cert.get("locations")
        metadata = cert.get("metadata")
        return CertificateSnapshot(
            collection_id=collection_id,
            certificate_id=int(cert.get("id") or 0),
            common_name=clip(cert.get("common_name"), 500),
            subject_dn=str(cert.get("subject_dn") or ""),
            issuer_dn=str(cert.get("issuer_dn") or ""),
            serial_number=clip(cert.get("serial_number"), 255),
            thumbprint=clip(cert.get("thumbprint"), 100),
            template=clip(cert.get("template"), 500),
            certificate_authority=clip(cert.get("certificate_authority"), 500),
            not_before=clip(cert.get("not_before"), 50) if cert.get("not_before") else None,
            not_after=clip(cert.get("not_after"), 50) if cert.get("not_after") else None,
            import_date=clip(cert.get("import_date"), 50) if cert.get("import_date") else None,
            effective_date=clip(cert.get("effective_date"), 50) if cert.get("effective_date") else None,
            sans=sans if isinstance(sans, list) else [],
            san_count=int_or_none(cert.get("san_count")) or 0,
            revoked=bool(cert.get("revoked")),
            revocation_reason=int_or_none(cert.get("revocation_reason")),
            status=clip(cert.get("status") or "unknown", 30),
            cert_metadata=metadata if isinstance(metadata, dict) else {},
            key_algorithm=clip(cert.get("key_algorithm"), 50),
            key_size=int_or_none(cert.get("key_size")) or 0,
            key_usage=clip(cert.get("key_usage"), 500),
            extended_key_usage=clip(cert.get("extended_key_usage"), 500),
            signing_algorithm=clip(cert.get("signing_algorithm"), 100),
            requester=clip(cert.get("requester"), 255),
            principal_name=clip(cert.get("principal_name"), 255),
            locations=locations if isinstance(locations, list) else [],
            location_count=int_or_none(cert.get("location_count")) or 0,
            collection=clip(cert.get("collection") or collection_name, 500),
            has_private_key=cert.get("has_private_key", False),
            synced_at=synced_at,
        )

    # ── DB-first reads ─────────────────────────────────────────────────

    @staticmethod
    def _tile_count(cached_rows: int, stored_total: int) -> int:
        """Certificate count for a collection tile.

        The tile should say what opening the collection will list, so the cached
        row count wins. The stored total is only the better answer when nothing
        is cached yet, or when the cache holds a truncated slice of a collection
        larger than the walk cap.
        """
        if cached_rows == 0 or cached_rows >= _MAX_CERTS_PER_COLLECTION:
            return stored_total or cached_rows
        return cached_rows

    async def list_collections_from_db(self) -> list[dict[str, Any]]:
        # Actual cached certificate counts per collection. The tile is derived
        # from these rather than the stored total so it always matches the grid,
        # and so a stored total left stale by an earlier sync self-heals without
        # waiting for the next one.
        counts_result = await self.db.execute(
            select(CertificateSnapshot.collection_id, func.count(CertificateSnapshot.id))
            # Revoked and soft-deleted rows are hidden from the grid, so counting
            # them here would put a number on the card the grid never reaches.
            .where(CertificateSnapshot.deleted_at.is_(None))
            .where(CertificateSnapshot.revoked.isnot(True))
            .group_by(CertificateSnapshot.collection_id)
        )
        cached_counts = {row[0]: row[1] for row in counts_result.all()}

        result = await self.db.execute(
            select(CertificateCollectionSnapshot).order_by(CertificateCollectionSnapshot.name)
        )
        return [
            {
                "id": r.collection_id,
                "name": r.name,
                "description": r.description or "",
                "certificate_count": self._tile_count(cached_counts.get(r.collection_id, 0), r.certificate_count or 0),
                "query": r.query or "",
            }
            for r in result.scalars().all()
        ]

    async def has_collections(self) -> bool:
        result = await self.db.execute(select(func.count(CertificateCollectionSnapshot.id)))
        return (result.scalar() or 0) > 0

    async def count_collections(self, enabled_ids: list[int] | None = None) -> int:
        """Count cached collections, scoped to the admin-enabled set when configured.

        An empty/None ``enabled_ids`` means no admin restriction, so every cached
        collection is counted (mirrors ``_filter_enabled_collections``).
        """
        stmt = select(func.count(CertificateCollectionSnapshot.id))
        if enabled_ids:
            stmt = stmt.where(CertificateCollectionSnapshot.collection_id.in_(enabled_ids))
        result = await self.db.execute(stmt)
        return result.scalar() or 0

    async def has_certificates(self, collection_id: int) -> bool:
        result = await self.db.execute(
            select(func.count(CertificateSnapshot.id)).where(CertificateSnapshot.collection_id == collection_id)
        )
        return (result.scalar() or 0) > 0

    async def mark_certificate_revoked(
        self,
        certificate_id: int,
        *,
        collection_id: int | None = None,
        reason: int | None = None,
    ) -> int:
        """Flag a cached cert as revoked so the DB-backed grid reflects it at once.

        The certificate grid reads from this cache, so without this the revoked
        status would not appear until the next eventually-consistent sync.
        Best-effort: a failure here never breaks the revoke response.
        """
        conditions = [CertificateSnapshot.certificate_id == certificate_id]
        if collection_id is not None:
            conditions.append(CertificateSnapshot.collection_id == collection_id)
        try:
            result = await self.db.execute(
                update(CertificateSnapshot)
                .where(*conditions)
                .values(
                    revoked=True,
                    status="revoked",
                    revocation_reason=reason,
                    synced_at=datetime.utcnow(),
                )
            )
            await self.db.commit()
            return result.rowcount or 0
        except Exception as exc:  # pragma: no cover - cache update must never break revoke
            await self.db.rollback()
            logger.warning("cert_mark_revoked_failed", certificate_id=certificate_id, error=str(exc)[:200])
            return 0

    async def count_due_certificates(
        self,
        *,
        collection_id: int,
        days_before_expiry: int,
        certificate_ids: list[int] | None = None,
    ) -> int:
        """Count cached certs in a collection expiring within the renewal window.

        Optionally restricted to specific certificate ids (a schedule scoped to
        individual certs rather than the whole collection).
        """
        cutoff = (datetime.now(UTC) + timedelta(days=days_before_expiry)).strftime("%Y-%m-%dT%H:%M:%S%z")
        conditions = [
            CertificateSnapshot.collection_id == collection_id,
            CertificateSnapshot.not_after.isnot(None),
            CertificateSnapshot.not_after <= cutoff,
        ]
        if certificate_ids:
            conditions.append(CertificateSnapshot.certificate_id.in_(certificate_ids))
        result = await self.db.execute(select(func.count(CertificateSnapshot.id)).where(*conditions))
        return result.scalar() or 0

    async def list_due_certificates(
        self,
        *,
        collection_id: int | None,
        days_before_expiry: int,
        certificate_ids: list[int] | None = None,
        include_expired: bool = True,
    ) -> list[dict[str, Any]]:
        """Cached certificates expiring within a window, soonest first.

        ``collection_id=None`` spans every cached collection, which is what an
        alert rule scoped to "all collections" needs. Already-expired
        certificates are included by default: they are the most urgent thing a
        report can surface, and silently dropping them would be worse than
        noise.
        """
        now = datetime.now(UTC)
        cutoff = (now + timedelta(days=days_before_expiry)).strftime("%Y-%m-%dT%H:%M:%S%z")
        conditions = [
            CertificateSnapshot.not_after.isnot(None),
            CertificateSnapshot.not_after <= cutoff,
            CertificateSnapshot.revoked.is_(False),
        ]
        if collection_id is not None:
            conditions.append(CertificateSnapshot.collection_id == collection_id)
        if certificate_ids:
            conditions.append(CertificateSnapshot.certificate_id.in_(certificate_ids))
        if not include_expired:
            conditions.append(CertificateSnapshot.not_after >= now.strftime("%Y-%m-%dT%H:%M:%S%z"))

        result = await self.db.execute(
            select(CertificateSnapshot).where(*conditions).order_by(CertificateSnapshot.not_after)
        )
        return [self._serialize_cert(r) for r in result.scalars().all()]

    async def list_certificates_from_db(
        self,
        *,
        collection_id: int,
        cn: str | None = None,
        thumbprint: str | None = None,
        issuer: str | None = None,
        cert_status: str | None = None,
        expires_in_days: int | None = None,
        deleted_only: bool = False,
        page: int = 1,
        page_size: int = 25,
    ) -> dict[str, Any]:
        """Fast, filtered, paginated certificate list served from PostgreSQL.

        By default only *active* certificates are returned — neither revoked nor
        soft-deleted. Both are reachable on request: pass ``cert_status="revoked"``
        or ``deleted_only=True``. A revoked certificate is not something anyone
        acts on from the main grid, and leaving it in inflated every expiry
        window it happened to fall inside.
        """
        conditions = [CertificateSnapshot.collection_id == collection_id]
        if deleted_only:
            conditions.append(CertificateSnapshot.deleted_at.isnot(None))
        else:
            conditions.append(CertificateSnapshot.deleted_at.is_(None))
        if cn:
            conditions.append(CertificateSnapshot.common_name.ilike(f"%{cn}%"))
        if thumbprint:
            conditions.append(CertificateSnapshot.thumbprint.ilike(f"%{thumbprint}%"))
        if issuer:
            conditions.append(CertificateSnapshot.issuer_dn.ilike(f"%{issuer}%"))
        if cert_status and not deleted_only:
            conditions.append(CertificateSnapshot.status == cert_status.lower())
        elif not deleted_only:
            # ``isnot(True)`` rather than ``is_(False)`` so rows cached before the
            # column was populated (NULL) still count as not revoked.
            conditions.append(CertificateSnapshot.revoked.isnot(True))
        if expires_in_days is not None and not deleted_only:
            cutoff = (datetime.now(UTC) + timedelta(days=expires_in_days)).strftime("%Y-%m-%dT%H:%M:%S%z")
            conditions.append(CertificateSnapshot.not_after.isnot(None))
            conditions.append(CertificateSnapshot.not_after <= cutoff)

        total_result = await self.db.execute(select(func.count(CertificateSnapshot.id)).where(*conditions))
        total = total_result.scalar() or 0

        offset = max(0, (page - 1) * page_size)
        rows_result = await self.db.execute(
            select(CertificateSnapshot)
            .where(*conditions)
            .order_by(CertificateSnapshot.common_name, CertificateSnapshot.certificate_id)
            .offset(offset)
            .limit(page_size)
        )
        items = [self._serialize_cert(r) for r in rows_result.scalars().all()]
        return {"items": items, "total": total, "page": page, "page_size": page_size}

    @staticmethod
    def _serialize_cert(r: CertificateSnapshot) -> dict[str, Any]:
        return {
            "id": r.certificate_id,
            "common_name": r.common_name or "",
            "subject_dn": r.subject_dn or "",
            "issuer_dn": r.issuer_dn or "",
            "serial_number": r.serial_number or "",
            "thumbprint": r.thumbprint or "",
            "template": r.template or "",
            "certificate_authority": r.certificate_authority or "",
            "not_before": r.not_before,
            "not_after": r.not_after,
            "import_date": r.import_date,
            "effective_date": r.effective_date,
            "sans": r.sans or [],
            "san_count": r.san_count or 0,
            "revoked": bool(r.revoked),
            "revocation_reason": r.revocation_reason,
            "status": r.status or "unknown",
            "metadata": r.cert_metadata or {},
            "key_algorithm": r.key_algorithm or "",
            "key_size": r.key_size or 0,
            "key_usage": r.key_usage or "",
            "extended_key_usage": r.extended_key_usage or "",
            "signing_algorithm": r.signing_algorithm or "",
            "requester": r.requester or "",
            "principal_name": r.principal_name or "",
            "locations": r.locations or [],
            "location_count": r.location_count or 0,
            "collection": r.collection or "",
            "has_private_key": bool(r.has_private_key) if r.has_private_key is not None else None,
            "deleted_at": r.deleted_at.isoformat() if r.deleted_at else None,
        }

    # ── Status / staleness ─────────────────────────────────────────────

    async def is_data_stale(self) -> bool:
        """True when no collections are cached or the last sync is older than the threshold."""
        if not await self.has_collections():
            return True
        last = await self.db.execute(
            select(CertificateSyncStatus.completed_at)
            .where(CertificateSyncStatus.status.in_(["completed", "partial"]))
            .order_by(CertificateSyncStatus.completed_at.desc())
            .limit(1)
        )
        completed = last.scalar_one_or_none()
        if completed is None:
            return True
        return (datetime.utcnow() - completed) > timedelta(minutes=_STALE_THRESHOLD_MINUTES)

    async def is_sync_running(self) -> bool:
        result = await self.db.execute(
            select(CertificateSyncStatus.started_at)
            .where(CertificateSyncStatus.status == "running")
            .order_by(CertificateSyncStatus.started_at.desc())
            .limit(1)
        )
        started = result.scalar_one_or_none()
        if started is None:
            return False
        # An older 'running' row was abandoned by a crashed/restarted process;
        # ignore it so lazy syncs and the UI aren't blocked forever.
        return started >= datetime.utcnow() - timedelta(minutes=_RUNNING_SYNC_TIMEOUT_MINUTES)

    async def _expire_abandoned_running_rows(self) -> int:
        """Flip orphaned 'running' rows to 'failed' once they exceed the timeout.

        A row stays 'running' forever if the process is killed mid-sync or the
        request is cancelled before the except handler fires. Without this sweep
        the certificate page's sync badge would stay on 'Syncing…' indefinitely
        and lazy cache refreshes would keep skipping.
        """
        cutoff = datetime.utcnow() - timedelta(minutes=_RUNNING_SYNC_TIMEOUT_MINUTES)
        result = await self.db.execute(
            update(CertificateSyncStatus)
            .where(
                CertificateSyncStatus.status == "running",
                CertificateSyncStatus.started_at < cutoff,
            )
            .values(
                status="failed",
                completed_at=datetime.utcnow(),
                error_message="abandoned: process restarted or timed out",
            )
        )
        expired = getattr(result, "rowcount", 0) or 0
        if expired:
            await self.db.commit()
            logger.warning("cert_sync_expired_running_rows", count=expired)
        return expired

    async def get_sync_status(self, limit: int = 5, enabled_ids: list[int] | None = None) -> dict[str, Any]:
        await self._expire_abandoned_running_rows()
        rows_result = await self.db.execute(
            select(CertificateSyncStatus).order_by(CertificateSyncStatus.started_at.desc()).limit(limit)
        )
        rows = rows_result.scalars().all()
        cert_count_result = await self.db.execute(select(func.count(CertificateSnapshot.id)))
        collections_in_db = await self.count_collections(enabled_ids)
        last_completed_result = await self.db.execute(
            select(CertificateSyncStatus.completed_at)
            .where(CertificateSyncStatus.status.in_(["completed", "partial"]))
            .order_by(CertificateSyncStatus.completed_at.desc())
            .limit(1)
        )
        last_completed = last_completed_result.scalar_one_or_none()
        return {
            "certificates_in_db": cert_count_result.scalar() or 0,
            "collections_in_db": collections_in_db,
            "last_completed_at": last_completed.isoformat() if last_completed else None,
            "is_stale": await self.is_data_stale(),
            "recent_syncs": [self._status_dict(r) for r in rows],
        }

    @staticmethod
    def _status_dict(r: CertificateSyncStatus) -> dict[str, Any]:
        return {
            "id": r.id,
            "sync_type": r.sync_type,
            "status": r.status,
            "started_at": r.started_at.isoformat() if r.started_at else None,
            "completed_at": r.completed_at.isoformat() if r.completed_at else None,
            "collections_synced": r.collections_synced or 0,
            "certificates_synced": r.certificates_synced or 0,
            "error_message": r.error_message,
            "triggered_by": r.triggered_by,
        }
