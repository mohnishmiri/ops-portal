"""
Tests for AuditLogMiddleware.

Regression guard for an ordering bug: the middleware used to read
``request.state.user`` *before* calling the downstream app. Starlette
middleware runs ahead of route dependencies, so the auth dependency had not
populated the user yet and every audit line recorded ``anonymous`` — the audit
trail could not attribute any action to anyone.
"""

import structlog
from fastapi import FastAPI, Request
from httpx import ASGITransport, AsyncClient

from app.middleware.audit import AuditLogMiddleware
from app.schemas.auth import UserContext, UserRole


def _app_that_authenticates_downstream() -> FastAPI:
    """App whose route sets request.state.user, mimicking the auth dependency."""
    app = FastAPI()
    app.add_middleware(AuditLogMiddleware)

    @app.get("/thing")
    async def thing(request: Request) -> dict:
        request.state.user = UserContext(
            user_id="u-real",
            object_id="00000000-0000-0000-0000-000000000000",
            display_name="Real User",
            email="real@example.com",
            roles=[UserRole.WRITE],
            raw_roles=["write"],
            tenant_id="t",
        )
        return {"ok": True}

    @app.get("/boom")
    async def boom() -> dict:
        raise RuntimeError("database password is hunter2")

    return app


async def test_audit_records_the_authenticated_user():
    app = _app_that_authenticates_downstream()

    with structlog.testing.capture_logs() as logs:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            resp = await ac.get("/thing")

    assert resp.status_code == 200
    audit = [entry for entry in logs if entry.get("event") == "api_request"]
    assert len(audit) == 1
    assert audit[0]["user_id"] == "u-real"
    assert audit[0]["user_email"] == "real@example.com"
    assert audit[0]["status_code"] == 200
    assert audit[0]["method"] == "GET"
    assert audit[0]["path"] == "/thing"


async def test_audit_falls_back_to_anonymous_for_unauthenticated_routes():
    """Genuinely unauthenticated routes must log, not raise."""
    app = FastAPI()
    app.add_middleware(AuditLogMiddleware)

    @app.get("/public")
    async def public() -> dict:
        return {"ok": True}

    with structlog.testing.capture_logs() as logs:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            resp = await ac.get("/public")

    assert resp.status_code == 200
    audit = [entry for entry in logs if entry.get("event") == "api_request"]
    assert audit[0]["user_id"] == "anonymous"


async def test_unhandled_exception_does_not_leak_internals_to_the_client():
    app = _app_that_authenticates_downstream()

    async with AsyncClient(transport=ASGITransport(app=app, raise_app_exceptions=False), base_url="http://test") as ac:
        resp = await ac.get("/boom")

    assert resp.status_code == 500
    body = resp.text
    assert "hunter2" not in body
    assert "RuntimeError" not in body
    assert resp.json() == {"detail": "Internal server error."}


async def test_unhandled_exception_is_logged_with_diagnostics():
    """The detail the client does not get must still reach the log."""
    app = _app_that_authenticates_downstream()

    with structlog.testing.capture_logs() as logs:
        async with AsyncClient(
            transport=ASGITransport(app=app, raise_app_exceptions=False), base_url="http://test"
        ) as ac:
            await ac.get("/boom")

    errors = [entry for entry in logs if entry.get("event") == "unhandled_exception_in_request"]
    assert len(errors) == 1
    assert errors[0]["error_type"] == "RuntimeError"
    assert "traceback" in errors[0]
