"""
Audit logging middleware — records all API requests with user identity.

Emits structured log entries for every API call including:
user identity, action, resource, status, duration.
"""

import time
import traceback
from collections.abc import Callable

import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

logger = structlog.get_logger("audit")


def _identity(request: Request) -> tuple[str, str]:
    """Best-effort (user_id, user_email) for the request.

    Falls back to anonymous for genuinely unauthenticated routes (health
    checks, the signed dashboard proxy) rather than raising.
    """
    user = getattr(request.state, "user", None)
    if user is None:
        return "anonymous", "unknown"
    return user.user_id, user.email or "unknown"


class AuditLogMiddleware(BaseHTTPMiddleware):
    """Log all API requests with user context for audit compliance."""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:  # type: ignore[type-arg]
        start_time = time.perf_counter()

        try:
            response: Response = await call_next(request)
        except Exception as exc:
            duration_ms = (time.perf_counter() - start_time) * 1000
            tb = traceback.format_exc()
            logger.error(
                "unhandled_exception_in_request",
                method=request.method,
                path=request.url.path,
                user_id=_identity(request)[0],
                error=str(exc),
                error_type=type(exc).__name__,
                traceback=tb,
                duration_ms=round(duration_ms, 2),
            )
            # The traceback goes to the application log only — the client gets
            # a generic message so internal implementation details are not
            # disclosed.
            return JSONResponse(
                status_code=500,
                content={"detail": "Internal server error."},
            )

        duration_ms = (time.perf_counter() - start_time) * 1000

        # Identity must be read AFTER call_next: request.state.user is set by
        # the auth dependency, which runs downstream of this middleware.
        # Reading it beforehand logged every request as "anonymous".
        user_id, user_email = _identity(request)

        # Skip logging for health checks and metrics
        if request.url.path in ("/healthz", "/readyz", "/metrics"):
            return response

        logger.info(
            "api_request",
            user_id=user_id,
            user_email=user_email,
            method=request.method,
            path=request.url.path,
            query=str(request.query_params),
            status_code=response.status_code,
            duration_ms=round(duration_ms, 2),
            client_ip=request.client.host if request.client else "unknown",
            user_agent=request.headers.get("user-agent", "unknown"),
        )

        return response
