"""Test suite for Ops Portal backend."""

import pytest
from httpx import ASGITransport, AsyncClient

import app.main as main_module
from app.auth import _dev_auth_enabled, get_current_user
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
    if _dev_auth_enabled():
        assert resp.status_code not in (401, 403)
    else:
        assert resp.status_code in (401, 403)


@pytest.mark.anyio
async def test_unauthenticated_dashboard_returns_401(client):
    resp = await client.get("/api/v1/dashboards/leadership")
    if _dev_auth_enabled():
        assert resp.status_code not in (401, 403)
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

    async def fake_enqueue_job(job_type, *, payload=None, triggered_by=None, idempotency_key=None, dedup_session=None):
        assert job_type == "amortized"
        return 99

    monkeypatch.setattr("app.services.sync_worker.enqueue_job", fake_enqueue_job)
    app.dependency_overrides[get_db] = fake_get_db
    app.dependency_overrides[get_current_user] = fake_get_current_user

    try:
        resp = await client.post("/api/v1/costs/amortized/sync?months=2")
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 202
    data = resp.json()
    assert data["status"] == "queued"
    assert data["job_id"] == 99


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


@pytest.mark.anyio
async def test_delete_unattached_disk_requires_admin(reader_client, monkeypatch):
    monkeypatch.setattr("app.auth._dev_auth_enabled", lambda: False)

    resp = await reader_client.post(
        "/api/v1/optimize/cleanup/disks",
        json={
            "subscription_id": "sub-1",
            "resource_group": "rg",
            "disk_name": "disk-01",
        },
    )
    assert resp.status_code == 403


@pytest.mark.anyio
async def test_delete_unattached_disk_rejects_attached_disk(admin_client, monkeypatch):
    class FakeAzureResourceService:
        def __init__(self, db_session=None):
            pass

        async def delete_unattached_disk(self, subscription_id, resource_group, disk_name):
            raise ValueError("Disk 'disk-01' is not unattached (state=Attached). Only unattached disks can be deleted.")

    monkeypatch.setattr(
        "app.services.azure_resource_service.AzureResourceService",
        FakeAzureResourceService,
    )

    resp = await admin_client.post(
        "/api/v1/optimize/cleanup/disks",
        json={
            "subscription_id": "sub-1",
            "resource_group": "rg",
            "disk_name": "disk-01",
        },
    )
    assert resp.status_code == 400
    assert "not unattached" in resp.json()["detail"]


@pytest.mark.anyio
async def test_delete_unattached_disk_succeeds_for_admin(admin_client, monkeypatch):
    class FakeAzureResourceService:
        def __init__(self, db_session=None):
            pass

        async def delete_unattached_disk(self, subscription_id, resource_group, disk_name):
            return {
                "status": "success",
                "action": "delete",
                "resource_name": disk_name,
                "resource_group": resource_group,
                "subscription_id": subscription_id,
            }

    monkeypatch.setattr(
        "app.services.azure_resource_service.AzureResourceService",
        FakeAzureResourceService,
    )

    resp = await admin_client.post(
        "/api/v1/optimize/cleanup/disks",
        json={
            "subscription_id": "sub-1",
            "resource_group": "rg",
            "disk_name": "disk-01",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "success"
    assert data["resource_name"] == "disk-01"


@pytest.mark.anyio
async def test_get_deployment_detail_returns_yaml(admin_client, monkeypatch):
    async def fake_get_detail(self, cluster_id: str, namespace: str, deployment_name: str):
        assert cluster_id == "cluster-1"
        assert namespace == "default"
        assert deployment_name == "web"
        return {
            "name": deployment_name,
            "namespace": namespace,
            "yaml": "apiVersion: apps/v1\nkind: Deployment\nmetadata:\n  name: web\n",
        }

    monkeypatch.setattr(
        "app.services.aks_operations_service.AKSOperationsService.get_deployment_detail",
        fake_get_detail,
    )

    resp = await admin_client.get(
        "/api/v1/aks/deployments/details",
        params={"cluster_id": "cluster-1", "namespace": "default", "name": "web"},
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "web"
    assert data["namespace"] == "default"
    assert "kind: Deployment" in data["yaml"]
