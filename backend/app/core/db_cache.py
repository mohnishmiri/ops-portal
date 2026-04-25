"""Database-backed cache manager replacing Redis.

Provides the same ``get_cached`` / ``set_cached`` / ``invalidate`` interface
that ``RedisManager`` exposed, but stores data in the ``page_cache``
PostgreSQL table.  A circuit-breaker guards against repeated DB failures.
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta
from typing import Any

import structlog
from sqlalchemy import delete, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings

logger = structlog.get_logger(__name__)

# Circuit-breaker: skip cache DB ops for N seconds after a failure
_CIRCUIT_BREAKER_COOLDOWN = 30  # seconds


def _get_session_factory() -> Any:
    """Lazy import to avoid circular dependency at module level."""
    from app.core.database import _SessionLocal

    return _SessionLocal


class DbCacheManager:
    """Async database-backed cache manager.

    Drop-in replacement for RedisManager — callers keep using
    ``get_cached``, ``set_cached``, ``invalidate``, and ``ping``.
    """

    def __init__(self) -> None:
        self._circuit_open_until: float = 0.0

    def _circuit_is_open(self) -> bool:
        return time.monotonic() < self._circuit_open_until

    def _trip_circuit(self) -> None:
        self._circuit_open_until = time.monotonic() + _CIRCUIT_BREAKER_COOLDOWN

    async def _session(self) -> AsyncSession | None:
        factory = _get_session_factory()
        if factory is None:
            return None
        return factory()

    async def ping(self) -> bool:
        """Health-check: verify DB is reachable."""
        session = await self._session()
        if session is None:
            return False
        try:
            async with session:
                await session.execute(text("SELECT 1"))
            return True
        except Exception:
            return False

    async def get_cached(self, key: str) -> str | None:
        """Fetch a cached payload by key.  Returns ``None`` on miss or error."""
        if self._circuit_is_open():
            return None
        session = await self._session()
        if session is None:
            return None
        try:
            from app.models.database import PageCache

            async with session:
                result = await session.execute(
                    select(PageCache.payload, PageCache.expires_at).where(PageCache.cache_key == key)
                )
                row = result.first()
                if row is None:
                    return None
                payload, expires_at = row
                if expires_at is not None and expires_at < datetime.utcnow():
                    # Expired — delete lazily and return miss
                    await session.execute(delete(PageCache).where(PageCache.cache_key == key))
                    await session.commit()
                    return None
                return payload
        except Exception as exc:
            self._trip_circuit()
            logger.warning("db_cache_get_error", key=key, error=str(exc)[:200])
            return None

    async def set_cached(self, key: str, value: str, ttl: int | None = None) -> None:
        """Upsert a cache entry.  ``ttl`` in seconds; 0 or None → no expiry."""
        if self._circuit_is_open():
            return
        session = await self._session()
        if session is None:
            return
        try:
            from app.models.database import PageCache

            if ttl is not None and ttl > 0:
                expires = datetime.utcnow() + timedelta(seconds=ttl)
            elif ttl is None:
                expires = datetime.utcnow() + timedelta(seconds=settings.CACHE_TTL_SECONDS)
            else:
                expires = None

            now = datetime.utcnow()
            stmt = (
                pg_insert(PageCache)
                .values(cache_key=key, payload=value, expires_at=expires, created_at=now)
                .on_conflict_do_update(
                    index_elements=["cache_key"],
                    set_={"payload": value, "expires_at": expires, "created_at": now},
                )
            )
            async with session:
                await session.execute(stmt)
                await session.commit()
        except Exception as exc:
            self._trip_circuit()
            logger.warning("db_cache_set_error", key=key, error=str(exc)[:200])

    async def invalidate(self, pattern: str) -> int:
        """Delete cache entries matching a SQL LIKE pattern.

        Converts Redis-style glob (``prefix:*``) to SQL ``prefix:%``.
        Returns the number of deleted rows, or 0 on error.
        """
        if self._circuit_is_open():
            return 0
        session = await self._session()
        if session is None:
            return 0
        try:
            from app.models.database import PageCache

            like_pattern = pattern.replace("*", "%")
            async with session:
                result = await session.execute(delete(PageCache).where(PageCache.cache_key.like(like_pattern)))
                await session.commit()
                return result.rowcount  # type: ignore[return-value]
        except Exception as exc:
            logger.warning("db_cache_invalidate_error", pattern=pattern, error=str(exc)[:200])
            return 0

    async def cleanup_expired(self) -> int:
        """Remove all expired cache entries.  Call periodically or at startup."""
        session = await self._session()
        if session is None:
            return 0
        try:
            from app.models.database import PageCache

            async with session:
                result = await session.execute(delete(PageCache).where(PageCache.expires_at < datetime.utcnow()))
                await session.commit()
                return result.rowcount  # type: ignore[return-value]
        except Exception as exc:
            logger.warning("db_cache_cleanup_error", error=str(exc)[:200])
            return 0


cache_manager = DbCacheManager()


# ── Admin-controlled cache toggle ────────────────────────────────────
_cache_admin_enabled: bool = True


async def refresh_cache_enabled_flag(db: Any) -> bool:
    """Re-read the ``cache_enabled`` admin config and cache the result.

    Returns the current enabled state.
    """
    global _cache_admin_enabled  # noqa: PLW0603
    from app.core.admin_config import get_cache_enabled

    _cache_admin_enabled = await get_cache_enabled(db)
    return _cache_admin_enabled


def is_cache_enabled_for_key(key: str) -> bool:
    """Return whether a cache key is allowed for page/application data.

    When the admin ``cache_enabled`` flag is False, all page-cache keys are
    bypassed so dashboards read from DB / Azure API instead.
    """
    if not _cache_admin_enabled and key.startswith("pagecache:"):
        logger.debug("cache_admin_disabled", key=key)
        return False
    return True
