"""
Centralised subscription resolver.

All read paths MUST call ``get_scoped_subscription_ids()`` (from
``app.core.subscription_scope``) so per-user subscription selection applies.
Background sync jobs use ``get_monitored_subscription_ids()`` directly.

The resolver:

1. Queries the ``admin_subscriptions`` table for rows with
   ``enabled = True AND monitored = True``.
2. Caches the result in-memory for ``_CACHE_TTL_SECONDS`` to avoid repeated
   DB round-trips.
3. Falls back to ``settings.subscription_ids`` (env-var) when the database is
   unavailable or returns an empty list.

Call ``invalidate_subscription_cache()`` after any admin mutation
(toggle / add / remove / discover / sync) so the next caller picks up
the fresh state immediately.
"""

from __future__ import annotations

import time

import structlog
from sqlalchemy import select

from app.core.config import settings

logger = structlog.get_logger(__name__)

# ── In-memory cache ────────────────────────────────────────────────────

_CACHE_TTL_SECONDS: float = 60.0
_cached_ids: list[str] = []
_cache_ts: float = 0.0


def invalidate_subscription_cache() -> None:
    """Clear the in-memory cache so the next call re-queries the DB."""
    global _cached_ids, _cache_ts
    _cached_ids = []
    _cache_ts = 0.0
    logger.debug("subscription_cache_invalidated")


async def get_monitored_subscription_ids() -> list[str]:
    """Return the list of subscription IDs that are enabled **and** monitored.

    Resolution order:
        1. In-memory cache (if still fresh)
        2. Database query (``AdminSubscription`` table)
        3. Fall back to ``settings.subscription_ids`` (env-var)
    """
    global _cached_ids, _cache_ts

    # 1. Serve from cache if still fresh
    now = time.monotonic()
    if _cached_ids and (now - _cache_ts) < _CACHE_TTL_SECONDS:
        return list(_cached_ids)

    # 2. Try DB
    try:
        # Late import to break circular dependencies
        import app.core.database as _db_mod

        if _db_mod._db_connected and _db_mod._SessionLocal is not None:
            from app.models.database import AdminSubscription

            async with _db_mod._SessionLocal() as session:
                result = await session.execute(
                    select(AdminSubscription.subscription_id).where(
                        AdminSubscription.enabled.is_(True),
                        AdminSubscription.monitored.is_(True),
                    )
                )
                ids = [row[0] for row in result.all()]

            if ids:
                _cached_ids = ids
                _cache_ts = now
                logger.debug(
                    "subscription_ids_resolved_from_db",
                    count=len(ids),
                )
                return list(ids)
            logger.debug(
                "subscription_ids_db_empty_fallback_env",
            )
    except Exception:
        logger.warning(
            "subscription_resolver_db_error_fallback_env",
            exc_info=True,
        )

    # 3. Fallback to env-var
    env_ids = settings.subscription_ids
    if env_ids:
        _cached_ids = env_ids
        _cache_ts = now
    return list(env_ids)
