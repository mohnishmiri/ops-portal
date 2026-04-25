"""Runtime-refreshing CORS middleware backed by admin_config."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Sequence

import structlog
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.cors import ALL_METHODS, SAFELISTED_HEADERS
from starlette.types import ASGIApp, Receive, Scope, Send

from app.core.admin_config import get_effective_cors_origins
from app.core.database import get_db_session

logger = structlog.get_logger(__name__)


class DynamicCORSMiddleware(CORSMiddleware):
    """CORSMiddleware that refreshes allowed origins from the database."""

    def __init__(
        self,
        app: ASGIApp,
        allow_origins: Sequence[str] = (),
        allow_methods: Sequence[str] = ("GET",),
        allow_headers: Sequence[str] = (),
        allow_credentials: bool = False,
        allow_origin_regex: str | None = None,
        allow_private_network: bool = False,
        expose_headers: Sequence[str] = (),
        max_age: int = 600,
        refresh_seconds: int = 30,
    ) -> None:
        self._configured_allow_methods = list(allow_methods)
        self._configured_allow_headers = list(allow_headers)
        self._configured_expose_headers = list(expose_headers)
        self._configured_allow_credentials = allow_credentials
        self._configured_max_age = max_age
        self._refresh_seconds = max(refresh_seconds, 5)
        self._last_refresh = 0.0
        self._refresh_lock = asyncio.Lock()

        super().__init__(
            app,
            allow_origins=allow_origins,
            allow_methods=allow_methods,
            allow_headers=allow_headers,
            allow_credentials=allow_credentials,
            allow_origin_regex=allow_origin_regex,
            allow_private_network=allow_private_network,
            expose_headers=expose_headers,
            max_age=max_age,
        )

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            await self._refresh_allowed_origins_if_needed()
        await super().__call__(scope, receive, send)

    async def _refresh_allowed_origins_if_needed(self) -> None:
        now = time.monotonic()
        if now - self._last_refresh < self._refresh_seconds:
            return

        async with self._refresh_lock:
            now = time.monotonic()
            if now - self._last_refresh < self._refresh_seconds:
                return

            try:
                origins: list[str] | None = None
                async for db in get_db_session():
                    origins = await get_effective_cors_origins(db)
                    break
                if origins:
                    self._apply_allowed_origins(origins)
            except Exception as exc:
                logger.warning("dynamic_cors_refresh_failed", error=str(exc))
            finally:
                self._last_refresh = time.monotonic()

    def _apply_allowed_origins(self, allow_origins: Sequence[str]) -> None:
        methods = ALL_METHODS if "*" in self._configured_allow_methods else list(self._configured_allow_methods)
        allow_all_origins = "*" in allow_origins
        allow_all_headers = "*" in self._configured_allow_headers
        preflight_explicit_allow_origin = not allow_all_origins or self._configured_allow_credentials

        simple_headers: dict[str, str] = {}
        if allow_all_origins:
            simple_headers["Access-Control-Allow-Origin"] = "*"
        if self._configured_allow_credentials:
            simple_headers["Access-Control-Allow-Credentials"] = "true"
        if self._configured_expose_headers:
            simple_headers["Access-Control-Expose-Headers"] = ", ".join(self._configured_expose_headers)

        preflight_headers: dict[str, str] = {}
        if preflight_explicit_allow_origin:
            preflight_headers["Vary"] = "Origin"
        else:
            preflight_headers["Access-Control-Allow-Origin"] = "*"
        preflight_headers.update(
            {
                "Access-Control-Allow-Methods": ", ".join(methods),
                "Access-Control-Max-Age": str(self._configured_max_age),
            }
        )

        computed_headers = sorted(SAFELISTED_HEADERS | set(self._configured_allow_headers))
        if computed_headers and not allow_all_headers:
            preflight_headers["Access-Control-Allow-Headers"] = ", ".join(computed_headers)
        if self._configured_allow_credentials:
            preflight_headers["Access-Control-Allow-Credentials"] = "true"

        self.allow_origins = list(allow_origins)
        self.allow_methods = methods
        self.allow_headers = [header.lower() for header in computed_headers]
        self.allow_all_origins = allow_all_origins
        self.allow_all_headers = allow_all_headers
        self.preflight_explicit_allow_origin = preflight_explicit_allow_origin
        self.simple_headers = simple_headers
        self.preflight_headers = preflight_headers
