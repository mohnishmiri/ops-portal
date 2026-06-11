"""PostgreSQL advisory locks for cross-replica sync coordination."""

from __future__ import annotations

import hashlib

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger(__name__)


def _lock_key(name: str) -> int:
    digest = hashlib.sha256(name.encode()).digest()[:8]
    return int.from_bytes(digest, "big", signed=True)


async def try_acquire_advisory_lock(session: AsyncSession, name: str) -> bool:
    """Attempt a session-scoped PostgreSQL advisory lock."""
    key = _lock_key(name)
    try:
        result = await session.execute(text("SELECT pg_try_advisory_lock(:key)"), {"key": key})
        acquired = bool(result.scalar())
    except Exception as exc:
        logger.warning("advisory_lock_unavailable", lock=name, error=str(exc)[:200])
        return True
    if not acquired:
        logger.info("advisory_lock_busy", lock=name)
    return acquired


async def release_advisory_lock(session: AsyncSession, name: str) -> None:
    key = _lock_key(name)
    try:
        await session.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": key})
    except Exception as exc:
        logger.warning("advisory_lock_release_skipped", lock=name, error=str(exc)[:200])
