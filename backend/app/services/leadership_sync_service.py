"""
Leadership Dashboard Sync Service.

Pulls cost data from Azure Cost Management APIs via DashboardService,
persists pre-computed dashboard payloads into PostgreSQL, and serves
subsequent requests from DB instead of live Azure queries.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta

import structlog
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.admin_config import get_cache_enabled, get_effective_cache_ttl_seconds
from app.core.db_cache import cache_manager
from app.core.subscription_resolver import get_monitored_subscription_ids
from app.models.database import LeadershipDashboardSnapshot, LeadershipSyncStatus
from app.services.dashboard_service import DashboardService

logger = structlog.get_logger(__name__)

STALE_HOURS = 6
RUNNING_SYNC_TIMEOUT_MINUTES = 90
LEADERSHIP_DASHBOARD_CACHE_KEY = "pagecache:leadership:dashboard:all"
SNAPSHOT_RETENTION_DAYS = 90


class LeadershipSyncService:
    """Syncs leadership dashboard data from Azure APIs into PostgreSQL."""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db
        self._dashboard_svc = DashboardService()

    async def is_data_stale(self) -> bool:
        """Return True when the DB has no data or hasn't been refreshed recently."""
        result = await self._db.execute(
            select(LeadershipSyncStatus)
            .where(LeadershipSyncStatus.status == "completed")
            .order_by(LeadershipSyncStatus.completed_at.desc())
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
            select(LeadershipSyncStatus)
            .where(LeadershipSyncStatus.status == "running")
            .order_by(LeadershipSyncStatus.started_at.desc())
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
                    "leadership_background_sync_finished",
                    status=result.get("status", "unknown"),
                    triggered_by=triggered_by,
                )
                break
        except Exception as exc:
            logger.error(
                "leadership_background_sync_failed",
                error=str(exc)[:500],
                triggered_by=triggered_by,
            )

    async def full_sync(self, triggered_by: str = "manual") -> dict:
        """Pull leadership data from Azure APIs and persist to DB.

        Appends a new snapshot instead of deleting old ones so that
        time-series history is preserved.  Records older than
        ``SNAPSHOT_RETENTION_DAYS`` are pruned to prevent unbounded
        growth.
        """
        sync_record = LeadershipSyncStatus(
            sync_type="full",
            status="running",
            started_at=datetime.utcnow(),
            triggered_by=triggered_by,
        )
        self._db.add(sync_record)
        await self._db.commit()

        try:
            # Resolve monitored subscriptions from Admin Control Panel
            monitored_ids = await get_monitored_subscription_ids()

            # Fetch live data from Azure via DashboardService
            data = await self._dashboard_svc.get_leadership_dashboard(
                subscription_ids=monitored_ids or None,
                refresh=True,
            )
            payload_json = data.model_dump_json()

            # Append the new snapshot (preserve history for time-series)
            snapshot = LeadershipDashboardSnapshot(
                snapshot_date=datetime.utcnow(),
                payload=payload_json,
                environment="ALL",
                synced_at=datetime.utcnow(),
                triggered_by=triggered_by,
            )
            self._db.add(snapshot)

            # Prune snapshots older than the retention window
            cutoff = datetime.utcnow() - timedelta(days=SNAPSHOT_RETENTION_DAYS)
            await self._db.execute(
                delete(LeadershipDashboardSnapshot).where(LeadershipDashboardSnapshot.snapshot_date < cutoff)
            )

            await self._db.commit()

            sync_record.status = "completed"
            sync_record.completed_at = datetime.utcnow()
            await self._db.commit()

            logger.info(
                "leadership_sync_completed",
                triggered_by=triggered_by,
                payload_size=len(payload_json),
            )

            cache_enabled = await get_cache_enabled(self._db)
            if cache_enabled:
                ttl = await get_effective_cache_ttl_seconds(self._db)
                await cache_manager.invalidate("pagecache:leadership:*")
                await cache_manager.set_cached(
                    LEADERSHIP_DASHBOARD_CACHE_KEY,
                    payload_json,
                    ttl=ttl,
                )
            else:
                await cache_manager.invalidate("pagecache:leadership:*")

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
                "leadership_sync_failed",
                error=str(exc)[:500],
                triggered_by=triggered_by,
            )
            return {"status": "failed", "error": str(exc)[:500]}

    async def get_dashboard_from_db(self) -> dict | None:
        """Load the latest leadership dashboard snapshot from DB."""
        result = await self._db.execute(
            select(LeadershipDashboardSnapshot)
            .where(LeadershipDashboardSnapshot.environment == "ALL")
            .order_by(LeadershipDashboardSnapshot.snapshot_date.desc())
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
        """Return latest sync status with enriched detail."""
        monitored_ids = await get_monitored_subscription_ids()
        result = await self._db.execute(
            select(LeadershipSyncStatus).order_by(LeadershipSyncStatus.started_at.desc()).limit(1)
        )
        rec = result.scalars().first()
        if not rec:
            return {
                "last_sync": None,
                "status": None,
                "triggered_by": None,
                "monitored_subscription_count": len(monitored_ids),
            }

        duration_seconds: float | None = None
        if rec.completed_at and rec.started_at:
            duration_seconds = (rec.completed_at - rec.started_at).total_seconds()

        return {
            "last_sync": rec.completed_at.isoformat() if rec.completed_at else None,
            "started_at": rec.started_at.isoformat() if rec.started_at else None,
            "status": rec.status,
            "triggered_by": rec.triggered_by,
            "duration_seconds": duration_seconds,
            "error_message": rec.error_message,
            "monitored_subscription_count": len(monitored_ids),
        }
