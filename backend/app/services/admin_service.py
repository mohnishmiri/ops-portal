"""
Admin Service — DB-backed subscription management, admin config, and system health.
"""

import asyncio
import time
import urllib.request
from datetime import datetime

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.azure_auth import get_azure_credential
from app.core.config import settings
from app.core.db_cache import cache_manager
from app.models.auth import UserContext
from app.models.database import AdminConfig, AdminSubscription, AuditLog

logger = structlog.get_logger(__name__)

# The Admin dashboard polls every 2 minutes per open tab and each probe is a
# token fetch plus an ARM round-trip, so a worker re-probes at most once a
# minute. (monotonic timestamp, reachable)
_AZURE_PROBE_TTL_SECONDS = 60
_azure_probe_result: tuple[float, bool] | None = None

# audit_logs.resource_type values for changes made from the Admin page; the
# certificate-collection picker on the same page already writes
# "certificate_config".
ADMIN_ACTIVITY_RESOURCE_TYPES = ("admin_config", "admin_subscription", "admin_cache", "certificate_config")

# Environment values offered by the Admin page. Free text is still accepted;
# AmortizedCostSyncService.normalize_environment maps any value to Prod / Non-Prod.
ENVIRONMENT_OPTIONS = (
    ("production", "Production"),
    ("non-production", "Non-Production"),
    ("development", "Development"),
    ("staging", "Staging"),
    ("dr", "DR"),
)

# Page caches whose payloads depend on which subscriptions are in scope or on
# their Environment (the Prod / Non-Prod cost split).
_SCOPE_DEPENDENT_CACHE_PATTERNS = ("pagecache:leadership%", "pagecache:amortized%", "pagecache:env%")


class AdminService:
    """Administrative operations with DB persistence."""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db
        self._credential = get_azure_credential()

    # ── Subscription CRUD ──────────────────────────────────────────────

    async def list_subscriptions(self) -> list[dict]:
        """Return all managed subscriptions from the database."""
        result = await self._db.execute(select(AdminSubscription).order_by(AdminSubscription.subscription_name))
        rows = result.scalars().all()
        return [
            {
                "id": row.id,
                "subscription_id": row.subscription_id,
                "subscription_name": row.subscription_name,
                "state": row.state or "Unknown",
                "enabled": row.enabled,
                "monitored": row.monitored,
                "environment": row.environment,
                "app_id": row.app_id,
                "tier": row.tier,
                "notes": row.notes,
                "created_at": row.created_at.isoformat() if row.created_at else None,
                "updated_at": row.updated_at.isoformat() if row.updated_at else None,
                "created_by": row.created_by,
            }
            for row in rows
        ]

    async def add_subscription(
        self,
        subscription_id: str,
        subscription_name: str,
        *,
        state: str = "Unknown",
        enabled: bool = True,
        monitored: bool = True,
        environment: str | None = None,
        notes: str | None = None,
        created_by: str | None = None,
    ) -> dict:
        """Add a new subscription to the database."""
        # Check for duplicates
        existing = await self._db.execute(
            select(AdminSubscription).where(AdminSubscription.subscription_id == subscription_id)
        )
        if existing.scalar_one_or_none():
            raise ValueError(f"Subscription {subscription_id} already exists")

        row = AdminSubscription(
            subscription_id=subscription_id,
            subscription_name=subscription_name,
            state=state,
            enabled=enabled,
            monitored=monitored,
            environment=environment,
            notes=notes,
            created_by=created_by,
            updated_by=created_by,
        )
        self._db.add(row)
        # Names carrying a known AppID (ACC-PROD-31599-ATTCC) are placed in
        # that app straight away; anything else stays Super Admin only.
        from app.services.access_service import AccessService

        await AccessService(self._db).auto_place([row])
        await self._db.commit()
        await self._db.refresh(row)

        logger.info(
            "subscription_added",
            subscription_id=subscription_id,
            subscription_name=subscription_name,
            created_by=created_by,
        )
        return {
            "id": row.id,
            "subscription_id": row.subscription_id,
            "subscription_name": row.subscription_name,
            "state": row.state,
            "enabled": row.enabled,
            "monitored": row.monitored,
            "environment": row.environment,
            "notes": row.notes,
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "created_by": row.created_by,
        }

    async def toggle_subscription(
        self,
        subscription_id: str,
        *,
        enabled: bool | None = None,
        monitored: bool | None = None,
        updated_by: str | None = None,
    ) -> dict:
        """Toggle the enabled / monitored flags of a subscription."""
        result = await self._db.execute(
            select(AdminSubscription).where(AdminSubscription.subscription_id == subscription_id)
        )
        row = result.scalar_one_or_none()
        if not row:
            raise ValueError(f"Subscription {subscription_id} not found")

        if enabled is not None:
            row.enabled = enabled
        if monitored is not None:
            row.monitored = monitored
        row.updated_at = datetime.utcnow()
        row.updated_by = updated_by
        await self._db.commit()
        await self._db.refresh(row)
        await self.invalidate_scope_dependent_caches()

        logger.info(
            "subscription_toggled",
            subscription_id=subscription_id,
            enabled=row.enabled,
            monitored=row.monitored,
            updated_by=updated_by,
        )
        return {
            "subscription_id": row.subscription_id,
            "subscription_name": row.subscription_name,
            "enabled": row.enabled,
            "monitored": row.monitored,
        }

    async def update_subscription(
        self,
        subscription_id: str,
        *,
        subscription_name: str | None = None,
        environment: str | None = None,
        notes: str | None = None,
        updated_by: str | None = None,
    ) -> dict:
        """Update metadata of a subscription.

        ``None`` leaves a field unchanged; an empty string clears Environment
        or Notes. The returned ``changes`` maps each changed field to
        ``[old, new]`` for the audit trail.
        """
        result = await self._db.execute(
            select(AdminSubscription).where(AdminSubscription.subscription_id == subscription_id)
        )
        row = result.scalar_one_or_none()
        if not row:
            raise ValueError(f"Subscription {subscription_id} not found")

        updates: dict[str, str | None] = {}
        if subscription_name is not None:
            updates["subscription_name"] = subscription_name.strip()
        if environment is not None:
            updates["environment"] = environment.strip() or None
        if notes is not None:
            updates["notes"] = notes.strip() or None

        changes: dict[str, list[str | None]] = {}
        for field, value in updates.items():
            current = getattr(row, field)
            if current != value:
                changes[field] = [current, value]
                setattr(row, field, value)

        if changes:
            row.updated_at = datetime.utcnow()
            row.updated_by = updated_by
            await self._db.commit()
            await self._db.refresh(row)
            # Name and Environment decide the Prod / Non-Prod cost split.
            if changes.keys() & {"subscription_name", "environment"}:
                await self.invalidate_scope_dependent_caches()

        return {
            "subscription_id": row.subscription_id,
            "subscription_name": row.subscription_name,
            "environment": row.environment,
            "notes": row.notes,
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
            "changes": changes,
        }

    async def remove_subscription(self, subscription_id: str) -> dict:
        """Remove a subscription from DB."""
        result = await self._db.execute(
            select(AdminSubscription).where(AdminSubscription.subscription_id == subscription_id)
        )
        row = result.scalar_one_or_none()
        if not row:
            raise ValueError(f"Subscription {subscription_id} not found")

        name = row.subscription_name
        await self._db.delete(row)
        await self._db.commit()

        from app.core.access_scope import invalidate_access_topology

        invalidate_access_topology()
        await self.invalidate_scope_dependent_caches()
        logger.info("subscription_removed", subscription_id=subscription_id)
        return {"subscription_id": subscription_id, "subscription_name": name, "removed": True}

    async def get_enabled_subscription_ids(self) -> list[str]:
        """Return a list of subscription IDs that are enabled AND monitored.

        This is used by other services (dashboard, cost) to know which
        subscriptions to query Azure for.
        """
        result = await self._db.execute(
            select(AdminSubscription.subscription_id).where(
                AdminSubscription.enabled.is_(True),
                AdminSubscription.monitored.is_(True),
            )
        )
        return list(result.scalars().all())

    # ── Discover from Azure ─────────────────────────────────────────────

    async def discover_subscriptions(
        self,
        *,
        created_by: str | None = None,
        sync_only: bool = False,
    ) -> dict:
        """Query Azure ARM for all available subscriptions and upsert
        them into the database.

        When *sync_only* is ``True`` only existing DB records are
        updated (name / state from Azure) — no new rows are inserted.
        When ``False`` (default) new subscriptions are also added as
        disabled so the admin can review and enable them.

        Returns a summary dict with counts.
        """
        import json as _json

        discovered: list[dict] = []
        new_rows: list[AdminSubscription] = []
        new_count = 0
        updated_count = 0
        try:
            token = await asyncio.to_thread(lambda: self._credential.get_token("https://management.azure.com/.default"))
            req = urllib.request.Request(
                "https://management.azure.com/subscriptions?api-version=2022-12-01",
                headers={"Authorization": f"Bearer {token.token}"},
            )

            def _fetch():
                opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
                with opener.open(req, timeout=15) as resp:
                    return _json.loads(resp.read())

            body = await asyncio.to_thread(_fetch)

            for sub in body.get("value", []):
                sid = sub.get("subscriptionId", "")
                name = sub.get("displayName", sid)
                state = sub.get("state", "Unknown")

                # Check if already in DB
                existing = await self._db.execute(
                    select(AdminSubscription).where(AdminSubscription.subscription_id == sid)
                )
                row = existing.scalar_one_or_none()

                if row:
                    # Update name / state from Azure
                    row.subscription_name = name
                    row.state = state
                    row.updated_at = datetime.utcnow()
                    updated_count += 1
                    discovered.append(
                        {
                            "subscription_id": sid,
                            "subscription_name": name,
                            "state": state,
                            "is_new": False,
                        }
                    )
                elif not sync_only:
                    # Insert as disabled so admin can review
                    row = AdminSubscription(
                        subscription_id=sid,
                        subscription_name=name,
                        state=state,
                        enabled=False,
                        monitored=False,
                        created_by=created_by,
                        updated_by=created_by,
                    )
                    self._db.add(row)
                    new_rows.append(row)
                    new_count += 1
                    discovered.append(
                        {
                            "subscription_id": sid,
                            "subscription_name": name,
                            "state": state,
                            "is_new": True,
                        }
                    )

            if new_rows:
                from app.services.access_service import AccessService

                await AccessService(self._db).auto_place(new_rows)
            await self._db.commit()
            action = "sync" if sync_only else "discover"
            logger.info(
                f"subscriptions_{action}",
                total=len(discovered),
                new_count=new_count,
                updated_count=updated_count,
            )

        except Exception as e:
            logger.error("discover_subscriptions_failed", error=str(e))
            raise

        return {
            "discovered": len(discovered),
            "new_count": new_count,
            "updated_count": updated_count,
            "subscriptions": discovered,
        }

    # ── Admin Config CRUD ──────────────────────────────────────────────

    async def list_admin_configs(self) -> list[dict]:
        """Return all admin config entries."""
        result = await self._db.execute(select(AdminConfig).order_by(AdminConfig.config_key))
        rows = result.scalars().all()
        return [
            {
                "id": row.id,
                "config_key": row.config_key,
                "config_value": row.config_value,
                "config_type": row.config_type,
                "description": row.description,
                "updated_at": row.updated_at.isoformat() if row.updated_at else None,
                "updated_by": row.updated_by,
            }
            for row in rows
        ]

    async def get_admin_config(self, key: str) -> dict | None:
        """Retrieve a single admin config by key."""
        result = await self._db.execute(select(AdminConfig).where(AdminConfig.config_key == key))
        row = result.scalar_one_or_none()
        if not row:
            return None
        return {
            "config_key": row.config_key,
            "config_value": row.config_value,
            "config_type": row.config_type,
            "description": row.description,
        }

    async def upsert_admin_config(
        self,
        key: str,
        value: str,
        *,
        config_type: str = "string",
        description: str | None = None,
        updated_by: str | None = None,
    ) -> dict:
        """Create or update an admin config entry."""
        result = await self._db.execute(select(AdminConfig).where(AdminConfig.config_key == key))
        row = result.scalar_one_or_none()
        if row:
            row.config_value = value
            row.config_type = config_type
            if description is not None:
                row.description = description
            row.updated_at = datetime.utcnow()
            row.updated_by = updated_by
        else:
            row = AdminConfig(
                config_key=key,
                config_value=value,
                config_type=config_type,
                description=description,
                updated_by=updated_by,
            )
            self._db.add(row)

        await self._db.commit()
        await self._db.refresh(row)

        logger.info("admin_config_upserted", key=key, updated_by=updated_by)
        return {
            "config_key": row.config_key,
            "config_value": row.config_value,
            "config_type": row.config_type,
            "description": row.description,
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        }

    # ── Audit trail ────────────────────────────────────────────────────

    async def record_audit(
        self,
        user: UserContext,
        action: str,
        *,
        resource_type: str,
        resource_id: str | None,
        summary: str,
        details: dict | None = None,
        ip_address: str | None = None,
        status: str = "success",
    ) -> None:
        """Write an ``audit_logs`` row for an Admin page change.

        Called after the change has committed; never raises, so a failed audit
        write cannot turn a successful change into an error response.
        """
        try:
            self._db.add(
                AuditLog(
                    user_id=user.user_id,
                    user_email=user.email,
                    action=action,
                    resource_type=resource_type,
                    resource_id=resource_id,
                    details={"page": "AdminDashboard", "summary": summary, **(details or {})},
                    ip_address=ip_address,
                    status=status,
                )
            )
            await self._db.commit()
        except Exception as exc:
            await self._db.rollback()
            logger.warning("admin_audit_failed", action=action, error=str(exc)[:200])

    async def list_admin_activity(self, limit: int = 200) -> list[dict]:
        """Most recent changes made from the Admin page, newest first."""
        result = await self._db.execute(
            select(AuditLog)
            .where(AuditLog.resource_type.in_(ADMIN_ACTIVITY_RESOURCE_TYPES))
            .order_by(AuditLog.timestamp.desc(), AuditLog.id.desc())
            .limit(limit)
        )
        return [
            {
                "id": row.id,
                "timestamp": row.timestamp.isoformat() if row.timestamp else None,
                "user_email": row.user_email or row.user_id,
                "action": row.action,
                "resource_type": row.resource_type,
                "resource_id": row.resource_id,
                "summary": (row.details or {}).get("summary") or row.action,
                "status": row.status,
            }
            for row in result.scalars().all()
        ]

    async def invalidate_scope_dependent_caches(self) -> int:
        """Drop page caches built from the old subscription scope / environments."""
        released = 0
        for pattern in _SCOPE_DEPENDENT_CACHE_PATTERNS:
            released += await cache_manager.invalidate(pattern)
        return released

    # ── System Health ──────────────────────────────────────────────────

    async def check_system_health(self) -> dict:
        """Check health of all system components."""
        cache_ok = await cache_manager.ping()

        # Check PostgreSQL connectivity
        db_ok = False
        try:
            from sqlalchemy import text

            await self._db.execute(text("SELECT 1"))
            db_ok = True
        except Exception as e:
            logger.warning("database_health_check_failed", error=str(e))

        azure_ok = await self.check_azure_api()

        all_ok = cache_ok and db_ok and azure_ok

        return {
            "status": "healthy" if all_ok else "degraded",
            "components": {
                "database": {"status": "connected" if db_ok else "disconnected"},
                "cache": {"status": "connected" if cache_ok else "disconnected"},
                "azure_api": {"status": "connected" if azure_ok else "disconnected"},
                "smtp": {
                    "status": "configured",
                    "host": settings.SMTP_HOST,
                },
            },
            "version": settings.APP_VERSION,
            "environment": settings.ENVIRONMENT,
            "checked_at": datetime.utcnow().isoformat(),
        }

    async def check_azure_api(self) -> bool:
        """Return whether the service principal can list subscriptions via ARM.

        Runs in a thread: ``get_token`` and ``urlopen`` are blocking and would
        otherwise stall every request on this worker for up to the timeout.
        """
        global _azure_probe_result  # noqa: PLW0603
        if _azure_probe_result and time.monotonic() - _azure_probe_result[0] < _AZURE_PROBE_TTL_SECONDS:
            return _azure_probe_result[1]

        def _probe() -> bool:
            token = self._credential.get_token("https://management.azure.com/.default")
            req = urllib.request.Request(
                "https://management.azure.com/subscriptions?api-version=2022-12-01",
                headers={"Authorization": f"Bearer {token.token}"},
            )
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            with opener.open(req, timeout=8) as resp:
                return resp.status == 200

        try:
            # The socket timeout doesn't cover token acquisition, so cap the whole probe.
            reachable = await asyncio.wait_for(asyncio.to_thread(_probe), timeout=10)
        except Exception as e:
            logger.warning("azure_health_check_failed", error=str(e)[:200] or type(e).__name__)
            reachable = False
        _azure_probe_result = (time.monotonic(), reachable)
        return reachable

    async def release_cached_data(self) -> dict:
        """Release page-cache payloads and cost query caches."""
        patterns = ["pagecache:%", "cost:%"]
        released: dict[str, int] = {}
        total = 0

        for pattern in patterns:
            count = await cache_manager.invalidate(pattern)
            released[pattern] = count
            total += count

        logger.info("admin_cache_release_completed", released=total)
        return {
            "status": "completed",
            "released_keys": total,
            "patterns": released,
            "released_at": datetime.utcnow().isoformat(),
        }
