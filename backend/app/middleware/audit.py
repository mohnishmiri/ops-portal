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


class AuditLogMiddleware(BaseHTTPMiddleware):
    """Log all API requests with user context for audit compliance."""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:  # type: ignore[type-arg]
        start_time = time.perf_counter()

        # Extract user info from request state (set by auth dependency)
        user_id = "anonymous"
        user_email = "unknown"
        if hasattr(request.state, "user"):
            user_id = request.state.user.user_id
            user_email = request.state.user.email

        try:
            response: Response = await call_next(request)
        except Exception as exc:
            duration_ms = (time.perf_counter() - start_time) * 1000
            tb = traceback.format_exc()
            logger.error(
                "unhandled_exception_in_request",
                method=request.method,
                path=request.url.path,
                error=str(exc),
                error_type=type(exc).__name__,
                traceback=tb,
                duration_ms=round(duration_ms, 2),
            )
            return JSONResponse(
                status_code=500,
                content={"detail": f"Internal Server Error: {type(exc).__name__}: {str(exc)}"},
            )

        duration_ms = (time.perf_counter() - start_time) * 1000

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
