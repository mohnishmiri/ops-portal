import pytest
from httpx import ASGITransport, AsyncClient

from app.main import create_application
from app.auth import get_current_user
from app.schemas.auth import UserContext, UserRole


@pytest.fixture
def app():
    return create_application()


@pytest.fixture
async def client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


async def _admin_user() -> UserContext:
    return UserContext(
        user_id="test-admin",
        object_id="00000000-0000-0000-0000-000000000000",
        display_name="Test Admin",
        email="admin@example.com",
        roles=[UserRole.ADMIN],
        raw_roles=["admin"],
        tenant_id="tenant-1",
        allowed_subscriptions=[],
    )


@pytest.mark.anyio
async def test_create_and_list_resources_and_permissions(app, client, monkeypatch):
    # Override get_current_user to be admin
    app.dependency_overrides[get_current_user] = _admin_user

    try:
        # Create a resource
        resp = await client.post(
            "/api/v1/permissions/resources",
            json={"resource_type": "page", "resource_name": "test_page", "description": "Test page"},
        )
        assert resp.status_code == 200
        res = resp.json()
        assert res["resource_name"] == "test_page" or res.get("resource_name") == "test_page"
        resource_id = res.get("id") or res[0].get("id")

        # Grant permission to role 'admin'
        resp2 = await client.post(
            "/api/v1/permissions/permissions",
            json={
                "subject_type": "role",
                "subject_id": "admin",
                "resource_id": resource_id,
                "permission_type": "view",
            },
        )
        assert resp2.status_code == 200
        perm = resp2.json()
        assert perm["subject_type"] == "role" or perm.get("subject_type") == "role"

        # List permissions
        resp3 = await client.get("/api/v1/permissions/permissions")
        assert resp3.status_code == 200
        perms = resp3.json()
        assert any((p.get("resource_id") == resource_id) for p in perms)
    finally:
        app.dependency_overrides.clear()
