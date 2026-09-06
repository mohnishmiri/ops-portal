"""
Enterprise 3-Tier Data Retrieval Service.

Architecture:
    L1: DB Page Cache  — fast reads from PostgreSQL ``page_cache`` table
    L2: PostgreSQL     — persistent snapshots & historical aggregates
    L3: Live API       — Azure SDK / Kubernetes API (source of truth)

Cache-aside pattern:
    1. Check DB cache (L1) — fast
    2. If miss → fetch from Live API (L3) — slow
    3. Backfill DB cache (L1) with fresh data
    4. Persist snapshots to DB (L2) on scheduled intervals

Write-through invalidation:
    After any mutation (scale, restart, suspend …) the relevant cache
    keys are invalidated so the next read goes to L3 and re-fills L1.

Graceful degradation:
    If the cache layer is unavailable (circuit-breaker open), the system
    falls through directly to L3 live calls.
"""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import Enum
from typing import Any, TypeVar

import structlog

from app.core.db_cache import cache_manager

logger = structlog.get_logger(__name__)

T = TypeVar("T")


# ─── Cache TTL Configuration ──────────────────────────────────────────


class CacheTier(str, Enum):
    """Identifies which tier served the response."""

    CACHE = "cache"
    DATABASE = "database"
    LIVE_API = "live_api"


@dataclass(frozen=True)
class CacheTTL:
    """Per-resource cache TTL configuration (seconds)."""

    CLUSTER_LIST: int = 300  # 5 min — clusters rarely change
    CLUSTER_DETAIL: int = 300  # 5 min
    DEPLOYMENTS: int = 120  # 2 min — changes on scale/restart
    POD_METRICS: int = 60  # 1 min — most volatile
    CRONJOBS: int = 120  # 2 min
    CRONJOB_DETAIL: int = 120  # 2 min
    # Jobs are short-lived and their status changes as pods run, so they are
    # cached only briefly — a manually triggered Job must appear promptly.
    JOBS: int = 30
    JOB_DETAIL: int = 30
    NODE_POOLS: int = 300  # 5 min — rarely changes
    SUBSCRIPTIONS: int = 600  # 10 min — almost static
    UNDERUTILIZED: int = 600  # 10 min — DB aggregation cache


TTL = CacheTTL()


# ─── Cache Key Builders ───────────────────────────────────────────────


def _hash_params(*args: Any) -> str:
    """Create a short, deterministic hash for variable query params."""
    raw = json.dumps(args, sort_keys=True, default=str)
    return hashlib.md5(raw.encode()).hexdigest()[:12]


class CacheKeys:
    """Centralised cache-key factory.

    Convention:  ``aks:<resource>:<scope>:<params_hash>``
    """

    PREFIX = "aks"

    @staticmethod
    def cluster_list(subscription_ids: list[str] | None = None) -> str:
        h = _hash_params(sorted(subscription_ids) if subscription_ids else [])
        return f"{CacheKeys.PREFIX}:clusters:list:{h}"

    @staticmethod
    def cluster_detail(cluster_id: str) -> str:
        return f"{CacheKeys.PREFIX}:clusters:detail:{_hash_params(cluster_id)}"

    @staticmethod
    def deployments(cluster_id: str, namespace: str | None = None) -> str:
        return f"{CacheKeys.PREFIX}:deployments:{_hash_params(cluster_id, namespace)}"

    @staticmethod
    def pod_metrics(cluster_id: str, namespace: str | None = None) -> str:
        return f"{CacheKeys.PREFIX}:pods:metrics:{_hash_params(cluster_id, namespace)}"

    @staticmethod
    def cronjobs(cluster_id: str, namespace: str | None = None) -> str:
        return f"{CacheKeys.PREFIX}:cronjobs:list:{_hash_params(cluster_id, namespace)}"

    @staticmethod
    def cronjob_detail(cluster_id: str, namespace: str, name: str) -> str:
        return f"{CacheKeys.PREFIX}:cronjobs:detail:{_hash_params(cluster_id, namespace, name)}"

    @staticmethod
    def jobs(cluster_id: str, namespace: str | None = None) -> str:
        return f"{CacheKeys.PREFIX}:jobs:list:{_hash_params(cluster_id, namespace)}"

    @staticmethod
    def job_detail(cluster_id: str, namespace: str, name: str) -> str:
        return f"{CacheKeys.PREFIX}:jobs:detail:{_hash_params(cluster_id, namespace, name)}"

    @staticmethod
    def node_pools(cluster_id: str) -> str:
        return f"{CacheKeys.PREFIX}:nodepools:{_hash_params(cluster_id)}"

    @staticmethod
    def subscriptions(subscription_ids: list[str] | None = None) -> str:
        h = _hash_params(sorted(subscription_ids) if subscription_ids else [])
        return f"{CacheKeys.PREFIX}:subscriptions:{h}"

    @staticmethod
    def underutilized(cluster_id: str, cpu_thr: int, mem_thr: int) -> str:
        return f"{CacheKeys.PREFIX}:underutilized:{_hash_params(cluster_id, cpu_thr, mem_thr)}"


# ─── Invalidation Patterns ────────────────────────────────────────────


class InvalidationPatterns:
    """Glob patterns used to invalidate groups of cache keys after mutations."""

    ALL = "aks:*"
    CLUSTERS = "aks:clusters:*"
    DEPLOYMENTS_FOR_CLUSTER = "aks:deployments:*"
    POD_METRICS_FOR_CLUSTER = "aks:pods:metrics:*"
    CRONJOBS_FOR_CLUSTER = "aks:cronjobs:*"
    NODE_POOLS_FOR_CLUSTER = "aks:nodepools:*"
    UNDERUTILIZED = "aks:underutilized:*"


# ─── Main Service ─────────────────────────────────────────────────────


class DataCacheService:
    """Enterprise data-cache orchestrator.

    Usage::

        cache = DataCacheService()
        data = await cache.get_or_fetch(
            key=CacheKeys.cluster_list(sub_ids),
            ttl=TTL.CLUSTER_LIST,
            fetch_fn=lambda: live_api_call(),
        )
    """

    def __init__(self) -> None:
        self._stats: dict[str, int] = {
            "cache_hits": 0,
            "cache_misses": 0,
            "live_api_calls": 0,
            "invalidations": 0,
        }
        self._start_time = time.monotonic()

    # ── Generic cache-aside ────────────────────────────────────────────

    async def get_or_fetch(
        self,
        key: str,
        ttl: int,
        fetch_fn: Callable[[], Awaitable[T]],
    ) -> tuple[T, CacheTier]:
        """Cache-aside: DB cache L1 → Live API L3 → backfill cache.

        Returns:
            (data, tier) — the data and which tier served it.
        """
        # L1: Try DB cache
        cached = await cache_manager.get_cached(key)
        if cached is not None:
            try:
                data = json.loads(cached)
                self._stats["cache_hits"] += 1
                logger.debug("cache_hit", key=key, tier="cache")
                return data, CacheTier.CACHE
            except (json.JSONDecodeError, TypeError):
                pass  # corrupt cache — fall through

        # L3: Call live API
        self._stats["cache_misses"] += 1
        self._stats["live_api_calls"] += 1
        logger.debug("cache_miss", key=key, tier="live_api")
        data = await fetch_fn()

        # Backfill L1
        try:
            payload = json.dumps(data, default=str)
            await cache_manager.set_cached(key, payload, ttl=ttl)
        except Exception as exc:
            logger.warning("cache_backfill_failed", key=key, error=str(exc)[:200])

        return data, CacheTier.LIVE_API

    # ── Targeted Invalidation ──────────────────────────────────────────

    async def invalidate_for_deployments(self, cluster_id: str) -> int:
        """Invalidate deployment + pod caches for a specific cluster."""
        count = 0
        # Invalidate all deployment keys that could match this cluster
        count += await cache_manager.invalidate("aks:deployments:*")
        count += await cache_manager.invalidate("aks:pods:metrics:*")
        count += await cache_manager.invalidate("aks:underutilized:*")
        self._stats["invalidations"] += count
        logger.info(
            "cache_invalidated",
            scope="deployments",
            cluster_id=cluster_id[:60],
            keys=count,
        )
        return count

    async def invalidate_for_cronjobs(self, cluster_id: str) -> int:
        """Invalidate cronjob caches for a specific cluster."""
        count = 0
        count += await cache_manager.invalidate("aks:cronjobs:*")
        self._stats["invalidations"] += count
        logger.info(
            "cache_invalidated",
            scope="cronjobs",
            cluster_id=cluster_id[:60],
            keys=count,
        )
        return count

    async def invalidate_for_nodepools(self, cluster_id: str) -> int:
        """Invalidate node pool + cluster caches."""
        count = 0
        count += await cache_manager.invalidate("aks:nodepools:*")
        count += await cache_manager.invalidate("aks:clusters:*")
        self._stats["invalidations"] += count
        logger.info(
            "cache_invalidated",
            scope="nodepools",
            cluster_id=cluster_id[:60],
            keys=count,
        )
        return count

    async def invalidate_for_clusters(self) -> int:
        """Invalidate all cluster-related caches."""
        count = await cache_manager.invalidate("aks:clusters:*")
        self._stats["invalidations"] += count
        logger.info("cache_invalidated", scope="clusters", keys=count)
        return count

    async def invalidate_for_secrets(self, cluster_id: str) -> int:
        count = await cache_manager.invalidate("aks:secrets:*")
        self._stats["invalidations"] += count
        logger.info("cache_invalidated", scope="secrets", cluster_id=cluster_id[:60], keys=count)
        return count

    async def invalidate_for_jobs(self, cluster_id: str) -> int:
        count = await cache_manager.invalidate("aks:jobs:*")
        self._stats["invalidations"] += count
        logger.info("cache_invalidated", scope="jobs", cluster_id=cluster_id[:60], keys=count)
        return count

    async def invalidate_for_pods(self, cluster_id: str) -> int:
        count = await cache_manager.invalidate("aks:pods:metrics:*")
        self._stats["invalidations"] += count
        logger.info("cache_invalidated", scope="pods", cluster_id=cluster_id[:60], keys=count)
        return count

    async def invalidate_for_services(self, cluster_id: str) -> int:
        count = await cache_manager.invalidate("aks:services:*")
        self._stats["invalidations"] += count
        logger.info("cache_invalidated", scope="services", cluster_id=cluster_id[:60], keys=count)
        return count

    async def invalidate_for_configmaps(self, cluster_id: str) -> int:
        count = await cache_manager.invalidate("aks:configmaps:*")
        self._stats["invalidations"] += count
        logger.info("cache_invalidated", scope="configmaps", cluster_id=cluster_id[:60], keys=count)
        return count

    async def invalidate_for_ingress(self, cluster_id: str) -> int:
        count = await cache_manager.invalidate("aks:ingress:*")
        self._stats["invalidations"] += count
        logger.info("cache_invalidated", scope="ingress", cluster_id=cluster_id[:60], keys=count)
        return count

    async def invalidate_all(self) -> int:
        """Nuclear option — flush all AKS caches."""
        count = await cache_manager.invalidate("aks:*")
        self._stats["invalidations"] += count
        logger.info("cache_invalidated", scope="ALL", keys=count)
        return count

    # ── Warm-up (pre-populate on startup) ──────────────────────────────

    async def warm_cache(self, fetch_clusters_fn: Callable[[], Awaitable[list]]) -> dict[str, Any]:
        """Pre-populate DB cache with cluster inventory at startup.

        Called from lifespan handler — runs once, non-blocking.
        """
        try:
            clusters = await fetch_clusters_fn()
            key = CacheKeys.cluster_list()
            payload = json.dumps(clusters, default=str)
            await cache_manager.set_cached(key, payload, ttl=TTL.CLUSTER_LIST)
            logger.info("cache_warmed", resource="clusters", count=len(clusters))
            return {"warmed": True, "clusters": len(clusters)}
        except Exception as exc:
            logger.warning("cache_warm_failed", error=str(exc)[:200])
            return {"warmed": False, "error": str(exc)[:200]}

    # ── Statistics / Health ─────────────────────────────────────────────

    def get_stats(self) -> dict[str, Any]:
        """Return live cache statistics."""
        total = self._stats["cache_hits"] + self._stats["cache_misses"]
        hit_rate = (self._stats["cache_hits"] / total * 100) if total > 0 else 0.0
        return {
            "cache_hits": self._stats["cache_hits"],
            "cache_misses": self._stats["cache_misses"],
            "live_api_calls": self._stats["live_api_calls"],
            "invalidations": self._stats["invalidations"],
            "hit_rate_pct": round(hit_rate, 1),
            "uptime_seconds": round(time.monotonic() - self._start_time),
            "cache_healthy": not cache_manager._circuit_is_open(),
        }

    def reset_stats(self) -> None:
        """Reset counters (useful after deployments)."""
        for k in self._stats:
            self._stats[k] = 0
        self._start_time = time.monotonic()


# ─── Singleton ─────────────────────────────────────────────────────────

data_cache = DataCacheService()
