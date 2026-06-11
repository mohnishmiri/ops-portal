"""Per-user subscription scope preferences."""

from __future__ import annotations

import json
from datetime import datetime

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.subscription_resolver import get_monitored_subscription_ids
from app.models.database import AdminSubscription, UserSubscriptionPreference

logger = structlog.get_logger(__name__)


class UserPreferenceService:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def get_selected_subscription_ids(self, user_id: str) -> list[str]:
        result = await self._db.execute(
            select(UserSubscriptionPreference).where(UserSubscriptionPreference.user_id == user_id)
        )
        row = result.scalar_one_or_none()
        if not row or not row.selected_subscription_ids:
            return []
        try:
            parsed = json.loads(row.selected_subscription_ids)
            return [str(item) for item in parsed] if isinstance(parsed, list) else []
        except json.JSONDecodeError:
            return []

    async def save_selected_subscription_ids(
        self,
        user_id: str,
        selected_subscription_ids: list[str],
    ) -> list[str]:
        monitored = await get_monitored_subscription_ids()
        monitored_set = set(monitored)
        cleaned = [sub_id for sub_id in selected_subscription_ids if sub_id in monitored_set]

        result = await self._db.execute(
            select(UserSubscriptionPreference).where(UserSubscriptionPreference.user_id == user_id)
        )
        row = result.scalar_one_or_none()
        payload = json.dumps(cleaned)
        if row:
            row.selected_subscription_ids = payload
            row.updated_at = datetime.utcnow()
        else:
            row = UserSubscriptionPreference(
                user_id=user_id,
                selected_subscription_ids=payload,
            )
            self._db.add(row)
        await self._db.commit()
        logger.info(
            "user_subscription_preference_saved",
            user_id=user_id,
            selected_count=len(cleaned),
        )
        return cleaned

    async def list_available_subscriptions(self, user_id: str) -> list[dict]:
        """Monitored subscriptions available for the picker."""
        monitored = await get_monitored_subscription_ids()
        if not monitored:
            return []

        result = await self._db.execute(
            select(AdminSubscription).where(
                AdminSubscription.subscription_id.in_(monitored),
                AdminSubscription.enabled.is_(True),
                AdminSubscription.monitored.is_(True),
            )
        )
        rows = result.scalars().all()
        by_id = {row.subscription_id: row for row in rows}
        selected = set(await self.get_selected_subscription_ids(user_id))

        available: list[dict] = []
        for sub_id in monitored:
            row = by_id.get(sub_id)
            available.append(
                {
                    "subscription_id": sub_id,
                    "subscription_name": row.subscription_name if row else sub_id,
                    "environment": row.environment if row else None,
                    "state": row.state if row else "Unknown",
                    "selected": sub_id in selected if selected else True,
                }
            )
        return available
