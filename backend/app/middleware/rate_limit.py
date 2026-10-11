"""
Rate limiting middleware, shared across every API worker.

Protects API from abuse while allowing legitimate burst traffic.
The effective limit can be changed at runtime via the admin config
(``rate_limit_rpm`` key in ``admin_configs`` table).

Production runs several uvicorn workers on several replicas, and a client's
requests are spread across all of them. Counting in process memory alone let a
client make ``rpm x workers x replicas`` requests a minute, so each worker:

* counts requests per client IP per minute locally, and
* every ``_FLUSH_SECONDS`` adds those counts to ``rate_limit_windows`` and reads
  back the deployment-wide totals in the same statement.

A request is checked against the last known deployment-wide total plus what
this worker has counted since, so other workers' traffic is seen within
``_FLUSH_SECONDS``. The limit is a sliding minute, estimated from the current
and previous fixed minutes. If the database is unreachable the worker keeps
enforcing on its own counts (fails open to per-process limiting, never closed).

The admin override is also per process, so every worker re-reads it from the
DB every ``_OVERRIDE_REFRESH_SECONDS`` (the same approach as DynamicCORSMiddleware).
"""

import asyncio
import time
from collections import defaultdict
from collections.abc import Callable
from datetime import datetime, timedelta

import structlog
from sqlalchemy import delete
from sqlalchemy.dialects.postgresql import insert as pg_insert
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.core.admin_config import get_admin_config_value
from app.core.database import get_db_session
from app.models.database import RateLimitWindow

logger = structlog.get_logger(__name__)

# Admin-overridden RPM value — updated from DB on startup, admin upsert,
# and the periodic refresh below.
_admin_rpm_override: int | None = None

_OVERRIDE_REFRESH_SECONDS = 30.0
_WINDOW_SECONDS = 60
_FLUSH_SECONDS = 5.0
# Shared rows older than this are deleted; only the current and previous
# minute are ever read.
_RETENTION_WINDOWS = 5
_FAILURE_LOG_INTERVAL_SECONDS = 60.0

_EPOCH = datetime(1970, 1, 1)

# (minute number since the epoch, client IP)
WindowKey = tuple[int, str]


def _wall_clock() -> float:
    """Epoch seconds. Windows are wall-clock minutes so every pod agrees on them."""
    return time.time()


def set_rate_limit_override(rpm: int | None) -> None:
    """Set the admin-overridden RPM value (called from admin config / startup)."""
    global _admin_rpm_override  # noqa: PLW0603
    _admin_rpm_override = rpm


def get_rate_limit_override() -> int | None:
    """Return the current admin RPM override (or None)."""
    return _admin_rpm_override


def _window_start(window: int) -> datetime:
    return _EPOCH + timedelta(seconds=window * _WINDOW_SECONDS)


def _upsert_statement(batch: dict[WindowKey, int]):  # noqa: ANN202
    """Add *batch* to the shared counts, returning the new totals.

    Rows are written in key order so concurrent flushes from other workers
    lock them in the same order (no deadlocks).
    """
    stmt = pg_insert(RateLimitWindow).values(
        [
            {"client_ip": ip, "window_start": _window_start(window), "request_count": batch[(window, ip)]}
            for window, ip in sorted(batch)
        ]
    )
    return stmt.on_conflict_do_update(
        index_elements=["client_ip", "window_start"],
        set_={"request_count": RateLimitWindow.request_count + stmt.excluded.request_count},
    ).returning(RateLimitWindow.client_ip, RateLimitWindow.window_start, RateLimitWindow.request_count)


async def _flush_counts(batch: dict[WindowKey, int], *, prune_before: int | None) -> dict[WindowKey, int]:
    """Add this worker's counts to the shared table and return the deployment-wide totals."""
    by_row = {(ip, _window_start(window)): (window, ip) for window, ip in batch}
    totals: dict[WindowKey, int] = {}
    async for db in get_db_session():
        if batch:
            for ip, start, count in (await db.execute(_upsert_statement(batch))).all():
                key = by_row.get((ip, start))
                if key is not None:
                    totals[key] = count
        if prune_before is not None:
            await db.execute(delete(RateLimitWindow).where(RateLimitWindow.window_start < _window_start(prune_before)))
    return totals


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Sliding-window rate limiter with counts shared through PostgreSQL."""

    def __init__(self, app: object, requests_per_minute: int = 120) -> None:  # noqa: ANN001
        super().__init__(app)  # type: ignore[arg-type]
        self.rpm = requests_per_minute
        # Startup already seeded the override, so the first refresh can wait.
        self._last_override_refresh = time.monotonic()
        self._refresh_lock = asyncio.Lock()

        # Counted here but not yet added to the shared table.
        self._pending: dict[WindowKey, int] = defaultdict(int)
        # Handed to an in-progress flush; still counted until it lands.
        self._inflight: dict[WindowKey, int] = {}
        # Deployment-wide totals as of this worker's last flush.
        self._shared: dict[WindowKey, int] = {}
        self._window = 0
        self._last_flush = time.monotonic()
        self._flushing = False
        self._last_pruned_window = 0
        self._last_failure_log = 0.0

    def _get_effective_rpm(self) -> int:
        """Return the current rate limit — admin override or startup default."""
        if _admin_rpm_override is not None:
            return _admin_rpm_override
        return self.rpm

    async def _refresh_override_if_due(self) -> None:
        """Pick up ``rate_limit_rpm`` changes saved through another worker."""
        if time.monotonic() - self._last_override_refresh < _OVERRIDE_REFRESH_SECONDS:
            return
        async with self._refresh_lock:
            if time.monotonic() - self._last_override_refresh < _OVERRIDE_REFRESH_SECONDS:
                return
            try:
                raw: str | None = None
                async for db in get_db_session():
                    raw = await get_admin_config_value(db, "rate_limit_rpm")
                if raw:
                    set_rate_limit_override(int(raw))
            except Exception as exc:
                logger.warning("rate_limit_override_refresh_failed", error=str(exc)[:200])
            finally:
                self._last_override_refresh = time.monotonic()

    def _roll_window(self, window: int) -> None:
        """Forget everything older than the previous minute."""
        if window == self._window:
            return
        self._window = window
        for store in (self._pending, self._shared):
            for key in [k for k in store if k[0] < window - 1]:
                del store[key]

    def _known_count(self, key: WindowKey) -> int:
        return self._shared.get(key, 0) + self._inflight.get(key, 0) + self._pending.get(key, 0)

    def _record_and_estimate(self, client_ip: str, now: float) -> float:
        """Count this request and return the client's requests over the last 60 s.

        Sliding-window estimate: all of this minute plus the share of the
        previous minute that still falls inside the trailing 60 seconds.
        """
        window = int(now // _WINDOW_SECONDS)
        self._roll_window(window)
        self._pending[(window, client_ip)] += 1
        elapsed = (now % _WINDOW_SECONDS) / _WINDOW_SECONDS
        previous = self._known_count((window - 1, client_ip))
        return previous * (1.0 - elapsed) + self._known_count((window, client_ip))

    async def _flush_if_due(self) -> None:
        if self._flushing or time.monotonic() - self._last_flush < _FLUSH_SECONDS:
            return
        self._flushing = True
        self._last_flush = time.monotonic()
        batch, self._pending = dict(self._pending), defaultdict(int)
        self._inflight = batch
        prune_before = self._window - _RETENTION_WINDOWS if self._window > self._last_pruned_window else None
        try:
            totals = await _flush_counts(batch, prune_before=prune_before)
        except Exception as exc:
            # Keep enforcing on local counts and retry the batch next flush.
            for key, count in batch.items():
                self._pending[key] += count
            if time.monotonic() - self._last_failure_log >= _FAILURE_LOG_INTERVAL_SECONDS:
                self._last_failure_log = time.monotonic()
                logger.warning("rate_limit_shared_flush_failed", error=str(exc)[:200] or type(exc).__name__)
        else:
            # The minute may have rolled over while the flush was in flight.
            self._shared.update({key: count for key, count in totals.items() if key[0] >= self._window - 1})
            if prune_before is not None:
                self._last_pruned_window = self._window
        finally:
            self._inflight = {}
            self._flushing = False

    async def dispatch(self, request: Request, call_next: Callable) -> Response:  # type: ignore[type-arg]
        # Skip rate limiting for health checks
        if request.url.path in ("/healthz", "/readyz", "/metrics"):
            return await call_next(request)

        await self._refresh_override_if_due()
        client_ip = request.client.host if request.client else "unknown"

        effective_rpm = self._get_effective_rpm()
        estimate = self._record_and_estimate(client_ip, _wall_clock())
        await self._flush_if_due()

        if estimate > effective_rpm:
            logger.warning("rate_limit_exceeded", client_ip=client_ip, count=round(estimate), rpm=effective_rpm)
            return JSONResponse(
                status_code=429,
                content={"detail": "Rate limit exceeded. Please retry after 60 seconds."},
                headers={"Retry-After": "60"},
            )

        return await call_next(request)
