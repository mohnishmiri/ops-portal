"""
Compliance Dashboard Sync Service.

Pre-computes compliance dashboard data and persists the JSON payload
into PostgreSQL so subsequent requests read from a single DB row
instead of running 8+ sequential queries.

Follows the same pattern as ``LeadershipSyncService``.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta

import structlog
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db_cache import cache_manager
from app.models.database import (
    AKSPodChecksum,
    AzureResourceInventory,
    ComplianceDashboardSnapshot,
    ComplianceSyncStatus,
)
from app.services.compliance_service import ComplianceService

logger = structlog.get_logger(__name__)

STALE_HOURS = 1
RUNNING_SYNC_TIMEOUT_MINUTES = 30
COMPLIANCE_DASHBOARD_CACHE_KEY = "pagecache:compliance:dashboard:all"
COMPLIANCE_METRICS_CACHE_KEY = "pagecache:compliance:metrics:all"
SNAPSHOT_RETENTION_DAYS = 30


class ComplianceSyncService:
    """Syncs compliance dashboard data from DB queries into a pre-computed snapshot."""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def is_data_stale(self) -> bool:
        """Return True when the DB has no snapshot or hasn't been refreshed recently."""
        result = await self._db.execute(
            select(ComplianceSyncStatus)
            .where(ComplianceSyncStatus.status == "completed")
            .order_by(ComplianceSyncStatus.completed_at.desc())
            .limit(1)
        )
        last = result.scalars().first()
        if not last or not last.completed_at:
            return True
        age = datetime.utcnow() - last.completed_at
        return age > timedelta(hours=STALE_HOURS)

    async def is_sync_running(self) -> bool:
        """Return True when a recent sync is still marked as running."""
        result = await self._db.execute(
            select(ComplianceSyncStatus)
            .where(ComplianceSyncStatus.status == "running")
            .order_by(ComplianceSyncStatus.started_at.desc())
            .limit(1)
        )
        running = result.scalars().first()
        if not running or not running.started_at:
            return False
        return running.started_at >= datetime.utcnow() - timedelta(minutes=RUNNING_SYNC_TIMEOUT_MINUTES)

    async def ensure_fresh_data(self, triggered_by: str = "scheduler") -> dict:
        """Sync only when data is stale and another sync is not already running."""
        if await self.is_sync_running():
            return {"status": "running"}
        if not await self.is_data_stale():
            return {"status": "fresh"}
        return await self.full_sync(triggered_by=triggered_by)

    @classmethod
    def schedule_background_sync(cls, triggered_by: str = "request") -> None:
        """Fire-and-forget background sync using a fresh DB session."""
        asyncio.create_task(cls._run_background_sync(triggered_by=triggered_by))

    @classmethod
    async def _run_background_sync(cls, triggered_by: str = "request") -> None:
        from app.core.database import get_db_session

        try:
            async for db in get_db_session():
                svc = cls(db)
                result = await svc.ensure_fresh_data(triggered_by=triggered_by)
                logger.info(
                    "compliance_background_sync_finished",
                    status=result.get("status", "unknown"),
                    triggered_by=triggered_by,
                )
                break
        except Exception as exc:
            logger.error(
                "compliance_background_sync_failed",
                error=str(exc)[:500],
                triggered_by=triggered_by,
            )

    # ------------------------------------------------------------------
    # Data collection helpers
    # ------------------------------------------------------------------

    async def _collect_compliance_data(
        self,
        compliance_svc: ComplianceService,
    ) -> None:
        """Collect fresh Synapse + AKS checksum data from Azure (best-effort).

        Each collection step is wrapped in its own try/except so a single
        failure (e.g. a Synapse workspace behind a firewall) does not
        prevent the remaining collection or dashboard computation.
        """

        # ── Synapse pipeline checksums ─────────────────────────────
        try:
            result = await compliance_svc.collect_synapse_pipeline_checksums()
            logger.info(
                "compliance_sync_synapse_collected",
                workspaces=result.get("workspaces", 0),
                pipelines=result.get("pipelines", 0),
                errors=len(result.get("errors", [])),
            )
        except Exception as exc:
            logger.warning(
                "compliance_sync_synapse_collection_failed",
                error=str(exc)[:500],
            )

        # ── Synapse drift detection ────────────────────────────────
        try:
            drifts = await compliance_svc.detect_synapse_pipeline_drift()
            logger.info(
                "compliance_sync_synapse_drift_detected",
                count=len(drifts),
            )
        except Exception as exc:
            logger.warning(
                "compliance_sync_synapse_drift_failed",
                error=str(exc)[:500],
            )

        # ── AKS pod checksums + drift ─────────────────────────────
        cluster_ids = await self._discover_aks_cluster_ids(compliance_svc)
        for cluster_id in cluster_ids:
            try:
                result = await compliance_svc.collect_pod_checksums(
                    cluster_id=cluster_id,
                )
                logger.info(
                    "compliance_sync_aks_collected",
                    cluster_id=cluster_id,
                    pods=result.get("pods", 0),
                )
            except Exception as exc:
                logger.warning(
                    "compliance_sync_aks_collection_failed",
                    cluster_id=cluster_id,
                    error=str(exc)[:300],
                )
                continue  # skip drift detection for this cluster

            try:
                drifts = await compliance_svc.detect_pod_drift(
                    cluster_id=cluster_id,
                )
                logger.info(
                    "compliance_sync_aks_drift_detected",
                    cluster_id=cluster_id,
                    count=len(drifts),
                )
            except Exception as exc:
                logger.warning(
                    "compliance_sync_aks_drift_failed",
                    cluster_id=cluster_id,
                    error=str(exc)[:300],
                )

    async def _discover_aks_cluster_ids(
        self,
        compliance_svc: ComplianceService,
    ) -> list[str]:
        """Return AKS cluster resource IDs from inventory + existing checksums."""
        from app.core.subscription_resolver import get_monitored_subscription_ids

        subscription_ids = await get_monitored_subscription_ids()
        if not subscription_ids:
            return []

        cluster_ids: set[str] = set()

        # 1. From AzureResourceInventory (synced by AKS Operations)
        try:
            stmt = select(AzureResourceInventory.resource_id).where(
                AzureResourceInventory.resource_type == "aks_cluster",
            )
            result = await self._db.execute(stmt)
            for (rid,) in result.all():
                if rid and compliance_svc._cluster_matches_subscription_scope(rid, subscription_ids):
                    cluster_ids.add(rid)
        except Exception:
            logger.debug("aks_inventory_discovery_skipped")

        # 2. From existing AKSPodChecksum records
        try:
            stmt = select(AKSPodChecksum.cluster_id).distinct()
            result = await self._db.execute(stmt)
            for (cid,) in result.all():
                if cid and compliance_svc._cluster_matches_subscription_scope(cid, subscription_ids):
                    cluster_ids.add(cid)
        except Exception:
            logger.debug("aks_checksum_discovery_skipped")

        return list(cluster_ids)

    # ------------------------------------------------------------------

    async def full_sync(self, triggered_by: str = "manual") -> dict:
        """Pre-compute compliance dashboard + metrics and persist to DB.

        Collects fresh checksum data from Azure first, then computes and
        caches the dashboard payload.  Appends new snapshots and prunes
        old ones beyond the retention window.
        """
        sync_record = ComplianceSyncStatus(
            sync_type="full",
            status="running",
            started_at=datetime.utcnow(),
            triggered_by=triggered_by,
        )
        self._db.add(sync_record)
        await self._db.commit()

        try:
            compliance_svc = ComplianceService(self._db)

            # ── Step 1: collect fresh data from Azure ──────────────
            await self._collect_compliance_data(compliance_svc)

            # ── Step 2: pre-compute the expensive dashboard payload ─
            dashboard_data = await compliance_svc.get_compliance_dashboard(subscription_ids=None)
            dashboard_json = json.dumps(dashboard_data, default=str)

            # ── Step 3: pre-compute the checksum metrics payload ───
            metrics_data = await compliance_svc.get_checksum_metrics(days=30, module_type=None)
            metrics_json = json.dumps(metrics_data, default=str)

            now = datetime.utcnow()

            # Store dashboard snapshot
            self._db.add(
                ComplianceDashboardSnapshot(
                    snapshot_type="dashboard",
                    snapshot_date=now,
                    payload=dashboard_json,
                    synced_at=now,
                    triggered_by=triggered_by,
                )
            )

            # Store metrics snapshot
            self._db.add(
                ComplianceDashboardSnapshot(
                    snapshot_type="metrics",
                    snapshot_date=now,
                    payload=metrics_json,
                    synced_at=now,
                    triggered_by=triggered_by,
                )
            )

            # Prune old snapshots
            cutoff = datetime.utcnow() - timedelta(days=SNAPSHOT_RETENTION_DAYS)
            await self._db.execute(
                delete(ComplianceDashboardSnapshot).where(ComplianceDashboardSnapshot.snapshot_date < cutoff)
            )

            await self._db.commit()

            sync_record.status = "completed"
            sync_record.completed_at = datetime.utcnow()
            await self._db.commit()

            logger.info(
                "compliance_sync_completed",
                triggered_by=triggered_by,
                dashboard_size=len(dashboard_json),
                metrics_size=len(metrics_json),
            )

            # Invalidate page cache
            await cache_manager.invalidate("pagecache:compliance:*")

            return {
                "status": "completed",
                "triggered_by": triggered_by,
                "started_at": sync_record.started_at.isoformat(),
                "completed_at": sync_record.completed_at.isoformat(),
                "duration_seconds": (sync_record.completed_at - sync_record.started_at).total_seconds(),
            }

        except Exception as exc:
            sync_record.status = "failed"
            sync_record.completed_at = datetime.utcnow()
            sync_record.error_message = str(exc)[:2000]
            await self._db.commit()
            logger.error(
                "compliance_sync_failed",
                error=str(exc)[:500],
                triggered_by=triggered_by,
            )
            return {"status": "failed", "error": str(exc)[:500]}

    async def get_dashboard_from_db(self) -> dict | None:
        """Load the latest pre-computed compliance dashboard from DB."""
        result = await self._db.execute(
            select(ComplianceDashboardSnapshot)
            .where(ComplianceDashboardSnapshot.snapshot_type == "dashboard")
            .order_by(ComplianceDashboardSnapshot.snapshot_date.desc())
            .limit(1)
        )
        snapshot = result.scalars().first()
        if not snapshot:
            return None
        try:
            data = json.loads(snapshot.payload)
            data["_source"] = "database"
            data["_synced_at"] = snapshot.synced_at.isoformat()
            return data
        except (json.JSONDecodeError, TypeError):
            return None

    async def get_metrics_from_db(self) -> dict | None:
        """Load the latest pre-computed checksum metrics from DB."""
        result = await self._db.execute(
            select(ComplianceDashboardSnapshot)
            .where(ComplianceDashboardSnapshot.snapshot_type == "metrics")
            .order_by(ComplianceDashboardSnapshot.snapshot_date.desc())
            .limit(1)
        )
        snapshot = result.scalars().first()
        if not snapshot:
            return None
        try:
            data = json.loads(snapshot.payload)
            data["_source"] = "database"
            data["_synced_at"] = snapshot.synced_at.isoformat()
            return data
        except (json.JSONDecodeError, TypeError):
            return None

    async def get_sync_status(self) -> dict:
        """Return latest sync status."""
        result = await self._db.execute(
            select(ComplianceSyncStatus).order_by(ComplianceSyncStatus.started_at.desc()).limit(1)
        )
        rec = result.scalars().first()
        if not rec:
            return {"last_sync": None, "status": None}
        return {
            "last_sync": rec.completed_at.isoformat() if rec.completed_at else None,
            "status": rec.status,
            "triggered_by": rec.triggered_by,
        }
