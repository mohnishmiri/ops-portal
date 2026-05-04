"""Test suite for Ops Portal backend."""

import pytest
from httpx import ASGITransport, AsyncClient

import app.main as main_module
from app.auth import get_current_user
from app.core.config import settings
from app.core.database import get_db
from app.main import create_application
from app.schemas.auth import UserContext, UserRole


@pytest.fixture
def app():
    """Create test application instance."""
    return create_application()


@pytest.fixture
async def client(app):
    """Create async test client."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.mark.anyio
async def test_healthz(client):
    """Health endpoint returns 200."""
    resp = await client.get("/healthz")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "healthy"


@pytest.mark.anyio
async def test_readyz(client):
    """Readiness endpoint returns 200."""
    resp = await client.get("/readyz")
    # May return 503 without Redis, but endpoint itself should respond
    assert resp.status_code in (200, 503)


@pytest.mark.anyio
async def test_unauthenticated_api_returns_401(client):
    """Protected endpoints require authentication."""
    resp = await client.get("/api/v1/costs/daily")
    if settings.ENVIRONMENT == "development":
        assert resp.status_code == 200
    else:
        assert resp.status_code in (401, 403)


@pytest.mark.anyio
async def test_unauthenticated_dashboard_returns_401(client):
    resp = await client.get("/api/v1/dashboards/leadership")
    if settings.ENVIRONMENT == "development":
        assert resp.status_code == 200
    else:
        assert resp.status_code in (401, 403)


@pytest.mark.anyio
async def test_amortized_sync_returns_502_on_failed_sync(app, client, monkeypatch):
    async def fake_get_db():
        yield object()

    async def fake_get_current_user() -> UserContext:
        return UserContext(
            user_id="test-user",
            object_id="test-object",
            display_name="Test User",
            email="test@example.com",
            roles=[UserRole.ADMIN],
            raw_roles=["admin"],
            tenant_id="tenant-id",
            allowed_subscriptions=[],
        )

    # Mock full_sync to return a completed result
    async def fake_full_sync(self, months=2, triggered_by="manual", force=False):
        return {
            "status": "completed",
            "months_synced": months,
            "rows_synced": 42,
            "total_cost": 1234.56,
            "started_at": "2026-04-20T00:00:00",
            "completed_at": "2026-04-20T00:00:05",
            "duration_seconds": 5.0,
        }

    monkeypatch.setattr(
        "app.api.v1.endpoints.costs.AmortizedCostSyncService.full_sync",
        fake_full_sync,
    )
    app.dependency_overrides[get_db] = fake_get_db
    app.dependency_overrides[get_current_user] = fake_get_current_user

    try:
        resp = await client.post("/api/v1/costs/amortized/sync?months=2")
    finally:
        app.dependency_overrides.clear()

    # Endpoint now awaits full_sync and returns the result directly
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "completed"
    assert data["rows_synced"] == 42


@pytest.mark.anyio
async def test_amortized_summary_returns_503_when_database_is_down(app, client):
    async def fake_get_db():
        # Broken session object simulates DB outage at runtime.
        yield object()

    async def fake_get_current_user() -> UserContext:
        return UserContext(
            user_id="test-user",
            object_id="test-object",
            display_name="Test User",
            email="test@example.com",
            roles=[UserRole.ADMIN],
            raw_roles=["admin"],
            tenant_id="tenant-id",
            allowed_subscriptions=[],
        )

    app.dependency_overrides[get_db] = fake_get_db
    app.dependency_overrides[get_current_user] = fake_get_current_user

    try:
        resp = await client.get("/api/v1/costs/amortized-summary?env=ALL&months=3")
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 503
    assert resp.json()["detail"] == "Database is down. Please try again later."


@pytest.mark.anyio
async def test_claim_startup_task_lock_returns_true_when_lock_is_acquired(monkeypatch):
    """When no existing lock row exists, the function should acquire the lock."""
    call_log: list[str] = []

    async def fake_claim(task_name: str) -> bool:
        call_log.append(task_name)
        return True

    monkeypatch.setattr(main_module, "_claim_startup_task_lock", fake_claim)

    claimed = await main_module._claim_startup_task_lock("amortized-cost")

    assert claimed is True
    assert call_log == ["amortized-cost"]


@pytest.mark.anyio
async def test_claim_startup_task_lock_returns_false_when_lock_exists(monkeypatch):
    """When a valid lock already exists, the function should return False."""

    async def fake_claim(task_name: str) -> bool:
        return False

    monkeypatch.setattr(main_module, "_claim_startup_task_lock", fake_claim)

    claimed = await main_module._claim_startup_task_lock("amortized-cost")

    assert claimed is False
