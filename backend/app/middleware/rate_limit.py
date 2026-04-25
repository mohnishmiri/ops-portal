"""
Rate limiting middleware using an in-memory sliding window.

Protects API from abuse while allowing legitimate burst traffic.
The effective limit can be changed at runtime via the admin config
(``rate_limit_rpm`` key in ``admin_configs`` table).
"""

import time
from collections import defaultdict
from collections.abc import Callable

import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

logger = structlog.get_logger(__name__)

# In-memory store: ip → list of request timestamps (epoch seconds)
_request_log: dict[str, list[float]] = defaultdict(list)

# Admin-overridden RPM value — updated from DB on startup and admin upsert.
_admin_rpm_override: int | None = None


def set_rate_limit_override(rpm: int | None) -> None:
    """Set the admin-overridden RPM value (called from admin config / startup)."""
    global _admin_rpm_override  # noqa: PLW0603
    _admin_rpm_override = rpm


def get_rate_limit_override() -> int | None:
    """Return the current admin RPM override (or None)."""
    return _admin_rpm_override


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Sliding-window rate limiter backed by in-memory counters."""

    def __init__(self, app: object, requests_per_minute: int = 120) -> None:  # noqa: ANN001
        super().__init__(app)  # type: ignore[arg-type]
        self.rpm = requests_per_minute

    def _get_effective_rpm(self) -> int:
        """Return the current rate limit — admin override or startup default."""
        if _admin_rpm_override is not None:
            return _admin_rpm_override
        return self.rpm

    @staticmethod
    def _check_rate_limit(client_ip: str) -> int:
        """Return the request count for *client_ip* in the current 60-second window."""
        now = time.monotonic()
        window_start = now - 60.0

        log = _request_log[client_ip]
        # Prune entries older than the window
        _request_log[client_ip] = [ts for ts in log if ts > window_start]
        _request_log[client_ip].append(now)
        return len(_request_log[client_ip])

    async def dispatch(self, request: Request, call_next: Callable) -> Response:  # type: ignore[type-arg]
        # Skip rate limiting for health checks
        if request.url.path in ("/healthz", "/readyz", "/metrics"):
            return await call_next(request)

        client_ip = request.client.host if request.client else "unknown"

        effective_rpm = self._get_effective_rpm()
        count = self._check_rate_limit(client_ip)

        if count > effective_rpm:
            logger.warning("rate_limit_exceeded", client_ip=client_ip, count=count, rpm=effective_rpm)
            return JSONResponse(
                status_code=429,
                content={"detail": "Rate limit exceeded. Please retry after 60 seconds."},
                headers={"Retry-After": "60"},
            )

        return await call_next(request)
