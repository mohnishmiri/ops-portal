"""Global Azure API rate-limiter.

Two layers protect against HTTP 429 throttling from Azure Cost Management:

1. ``AZURE_API_SEMAPHORE`` — a global concurrency cap (how many Azure calls
   can be *in flight* at once across the whole process). Prevents CPU/network
   blow-up when many syncs run concurrently.

2. ``acquire_for_scope`` — a per-subscription token bucket sized to stay
   under Azure's ~10 req/min/subscription rate limit. Before each Cost
   Management call we await a token for the target subscription so one
   subscription's burst cannot starve another (previously the global
   Semaphore(2) had no per-sub awareness — two queries against the same
   sub would happily fire and 429).
"""

from __future__ import annotations

import asyncio
import time

import structlog

logger = structlog.get_logger(__name__)

# Global concurrency cap. Raised from 2 to 4 because the per-sub token
# bucket below now prevents per-subscription overrun — the semaphore is
# just a guard against runaway parallelism in the whole process.
AZURE_API_SEMAPHORE = asyncio.Semaphore(4)


class _TokenBucket:
    """Async token bucket: ``CAPACITY`` tokens, refilled at ``REFILL_PER_MIN``/min.

    Azure Cost Management throttles at roughly 10 requests/min/subscription.
    We size the bucket at 8 with an 8/min refill — burst-friendly for normal
    operation but provably safe under sustained load.
    """

    CAPACITY = 8
    REFILL_PER_MIN = 8
    REFILL_PER_SEC = REFILL_PER_MIN / 60.0

    def __init__(self) -> None:
        self._tokens = float(self.CAPACITY)
        self._last_refill = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        async with self._lock:
            while True:
                now = time.monotonic()
                elapsed = now - self._last_refill
                self._tokens = min(self.CAPACITY, self._tokens + elapsed * self.REFILL_PER_SEC)
                self._last_refill = now
                if self._tokens >= 1.0:
                    self._tokens -= 1.0
                    return
                # Wait long enough for one more token. Cap the single sleep
                # so cancellation propagates quickly during shutdown.
                deficit = 1.0 - self._tokens
                wait = deficit / self.REFILL_PER_SEC
                await asyncio.sleep(min(wait, 5.0))


_buckets_lock = asyncio.Lock()
_buckets: dict[str, _TokenBucket] = {}


def _subscription_id_from_scope(scope: str) -> str:
    """Extract the subscription GUID from an Azure scope path.

    ``/subscriptions/{sub_id}`` → ``sub_id``. Anything else gets bucketed
    under ``"global"`` so we still rate-limit non-subscription scopes.
    """
    parts = scope.split("/")
    if len(parts) > 2 and parts[1] == "subscriptions" and parts[2]:
        return parts[2]
    return "global"


async def acquire_for_scope(scope: str) -> None:
    """Block until a rate-limit token is available for ``scope``.

    Call this immediately before issuing an Azure Cost Management request.
    Cheap when tokens are available; sleeps up to ~7.5s per token when the
    bucket is empty.
    """
    sub_id = _subscription_id_from_scope(scope)
    async with _buckets_lock:
        bucket = _buckets.get(sub_id)
        if bucket is None:
            bucket = _TokenBucket()
            _buckets[sub_id] = bucket
    await bucket.acquire()
