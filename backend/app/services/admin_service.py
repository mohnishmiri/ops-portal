"""
Admin Service — DB-backed subscription management, admin config, and system health.
"""

from datetime import datetime

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.azure_auth import get_azure_credential
from app.core.config import settings
from app.core.db_cache import cache_manager
from app.models.database import AdminConfig, AdminSubscription

logger = structlog.get_logger(__name__)


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

        logger.info(
            "subscription_toggled",
            subscription_id=subscription_id,
            enabled=row.enabled,
            monitored=row.monitored,
            updated_by=updated_by,
        )
        return {
            "subscription_id": row.subscription_id,
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
        """Update metadata of a subscription."""
        result = await self._db.execute(
            select(AdminSubscription).where(AdminSubscription.subscription_id == subscription_id)
        )
        row = result.scalar_one_or_none()
        if not row:
            raise ValueError(f"Subscription {subscription_id} not found")

        if subscription_name is not None:
            row.subscription_name = subscription_name
        if environment is not None:
            row.environment = environment
        if notes is not None:
            row.notes = notes
        row.updated_at = datetime.utcnow()
        row.updated_by = updated_by
        await self._db.commit()
        await self._db.refresh(row)

        return {
            "subscription_id": row.subscription_id,
            "subscription_name": row.subscription_name,
            "environment": row.environment,
            "notes": row.notes,
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        }

    async def remove_subscription(self, subscription_id: str) -> dict:
        """Remove a subscription from DB."""
        result = await self._db.execute(
            select(AdminSubscription).where(AdminSubscription.subscription_id == subscription_id)
        )
        row = result.scalar_one_or_none()
        if not row:
            raise ValueError(f"Subscription {subscription_id} not found")

        await self._db.delete(row)
        await self._db.commit()

        logger.info("subscription_removed", subscription_id=subscription_id)
        return {"subscription_id": subscription_id, "removed": True}

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
        import asyncio
        import json as _json
        import urllib.request

        discovered: list[dict] = []
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
                    new_count += 1
                    discovered.append(
                        {
                            "subscription_id": sid,
                            "subscription_name": name,
                            "state": state,
                            "is_new": True,
                        }
                    )

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

        # Check Azure connectivity
        azure_ok = False
        try:
            import urllib.request

            token = self._credential.get_token("https://management.azure.com/.default")
            url = "https://management.azure.com/subscriptions?api-version=2022-12-01"
            req = urllib.request.Request(
                url,
                headers={"Authorization": f"Bearer {token.token}"},
            )
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            with opener.open(req, timeout=10) as resp:
                azure_ok = resp.status == 200
        except Exception as e:
            logger.warning("azure_health_check_failed", error=str(e))

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
