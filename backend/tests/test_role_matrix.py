"""
Portal-wide role policy: READ users view, WRITE and ADMIN users change things.

The structural tests walk every API route's dependency tree, so a new route
must either enforce the policy or be listed below with the reason it differs.
The behavioural tests cover the places where the policy is enforced inside a
handler rather than by a dependency.
"""

import inspect
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from fastapi.routing import APIRoute
from httpx import ASGITransport, AsyncClient

from app.api.v1.endpoints import infra_alerts
from app.api.v1.endpoints.aks_dashboard import _create_launch_token
from app.auth import get_current_user
from app.core.config import settings
from app.core.database import get_db
from app.core.resource_registry import CAPABILITY_SEEDS
from app.main import create_application
from app.schemas.auth import UserContext, UserRole
from app.services.k8s_dashboard_service import K8sDashboardService

MUTATING = {"POST", "PUT", "PATCH", "DELETE"}
ADMIN_CONSOLE_PREFIXES = ("/api/v1/admin", "/api/v1/permissions")
_SEEDED_ROLES = {name: set(roles) for name, _desc, _ptype, roles, _parent in CAPABILITY_SEEDS}

# State-changing HTTP methods that a READ user may call, and why that is safe.
READ_PERMITTED_MUTATIONS: dict[tuple[str, str], str] = {
    **{
        ("POST", f"/api/v1/{path}"): "refreshes the portal's cached copy from Azure/Kubernetes; changes nothing there"
        for path in (
            "aks/clusters/sync",
            "aks/deployments/sync",
            "aks/cronjobs/sync",
            "aks/nodepools/sync",
            "certificates/sync",
            "infra-alerts/resources/sync",
        )
    },
    (
        "POST",
        "/api/v1/sync-jobs",
    ): "AKS cache refresh is open to every role; other job types check WRITE in the handler",
    (
        "POST",
        "/api/v1/aks/dashboard/{env_key}/launch",
    ): "issues a Dashboard session that carries the user's write access",
    **{
        (method, "/api/v1/aks/dashboard/{env_key}/proxy/{path:path}"): "proxy refuses changes from read-only sessions"
        for method in ("POST", "PUT", "PATCH", "DELETE")
    },
    ("POST", "/api/v1/aks/helm/lint"): "lints a chart locally; nothing is applied to a cluster",
    ("POST", "/api/v1/aks/helm/template"): "renders a chart locally; nothing is applied to a cluster",
    ("POST", "/api/v1/aks/logs/archive"): "downloads pod logs (aks_pod_view)",
    ("PUT", "/api/v1/auth/subscription-scope"): "the caller's own view preference",
    ("POST", "/api/v1/certificates/{certificate_id}/download"): "public formats are reads; private keys check WRITE",
    ("POST", "/api/v1/costs/query"): "read-only cost query",
    ("POST", "/api/v1/dashboards/leadership/advisor"): "read-only AI summary of existing data",
    ("POST", "/api/v1/dashboards/leadership/forecast"): "read-only forecast of existing data",
    ("POST", "/api/v1/reports/generate"): "read-only report over existing data",
}

# Admin-only operations outside the Admin console.  None is offered in the UI to
# non-admins; everything else that changes state is available to WRITE users.
ADMIN_ONLY_OUTSIDE_CONSOLE: dict[tuple[str, str], str] = {
    ("POST", "/api/v1/aks/cache/invalidate"): "internal maintenance, not exposed in the UI",
    ("POST", "/api/v1/aks/clusters/snapshot"): "internal maintenance, not exposed in the UI",
    ("PUT", "/api/v1/certificates/collections/enabled"): "configured from the Admin console",
    ("POST", "/api/v1/compliance/dashboard/sync"): "internal maintenance, not exposed in the UI",
    ("POST", "/api/v1/notifications/budget-alert"): "internal maintenance, not exposed in the UI",
}

# Read endpoints a READ user may not call, and why.
READ_BLOCKED_VIEWS: dict[str, str] = {
    "/api/v1/keyvault/secrets/{name}": "returns a secret's plaintext value",
    "/api/v1/dashboards/admin": "Admin console data",
    "/api/v1/notifications/history": "Admin console data",
}


def _checks(dependant, found: list[tuple[set[UserRole], str]]) -> list[tuple[set[UserRole], str]]:
    """(roles admitted, description) for every role/capability check in a route's dependency tree."""
    for dep in dependant.dependencies:
        name = getattr(dep.call, "__qualname__", "")
        if name.endswith("_role_checker"):
            required = set(inspect.getclosurevars(dep.call).nonlocals["roles"])
            admitted = {r for r in UserRole if r == UserRole.ADMIN or _implies(r) & required}
            found.append((admitted, f"role {sorted(r.value for r in required)}"))
        elif name.endswith("_capability_checker"):
            nonlocals = inspect.getclosurevars(dep.call).nonlocals
            capability = nonlocals["capability"]
            if capability in _SEEDED_ROLES:
                granted = {UserRole(r) for r in _SEEDED_ROLES[capability]}
            else:
                granted = _implies_reverse(nonlocals["fallback_role"])
            found.append((granted | {UserRole.ADMIN}, f"capability {capability}"))
        _checks(dep, found)
    return found


def _implies(role: UserRole) -> set[UserRole]:
    return {
        UserRole.ADMIN: {UserRole.ADMIN, UserRole.WRITE, UserRole.READ},
        UserRole.WRITE: {UserRole.WRITE, UserRole.READ},
        UserRole.READ: {UserRole.READ},
    }[role]


def _implies_reverse(required: UserRole) -> set[UserRole]:
    return {r for r in UserRole if required in _implies(r)}


def _admits(route: APIRoute, role: UserRole) -> bool:
    return all(role in admitted for admitted, _desc in _checks(route.dependant, []))


@pytest.fixture(scope="module")
def routes() -> list[APIRoute]:
    return [r for r in create_application().routes if isinstance(r, APIRoute)]


def test_read_only_users_cannot_change_anything(routes):
    open_to_read = {(method, r.path) for r in routes for method in r.methods & MUTATING if _admits(r, UserRole.READ)}
    unexpected = open_to_read - READ_PERMITTED_MUTATIONS.keys()
    stale = READ_PERMITTED_MUTATIONS.keys() - open_to_read
    assert not unexpected, f"State-changing routes open to READ users: {sorted(unexpected)}"
    assert not stale, f"Allow-list entries no longer open to READ (remove them): {sorted(stale)}"


def test_write_users_can_make_every_change_outside_the_admin_console(routes):
    admin_only = {
        (method, r.path)
        for r in routes
        for method in r.methods & MUTATING
        if not r.path.startswith(ADMIN_CONSOLE_PREFIXES) and not _admits(r, UserRole.WRITE)
    }
    unexpected = admin_only - ADMIN_ONLY_OUTSIDE_CONSOLE.keys()
    stale = ADMIN_ONLY_OUTSIDE_CONSOLE.keys() - admin_only
    assert not unexpected, f"Operations WRITE users cannot perform: {sorted(unexpected)}"
    assert not stale, f"Allow-list entries WRITE users can now perform (remove them): {sorted(stale)}"


def test_read_only_users_can_view_everything_else(routes):
    blocked = {r.path for r in routes if "GET" in r.methods and not _admits(r, UserRole.READ)}
    blocked = {p for p in blocked if not p.startswith(ADMIN_CONSOLE_PREFIXES)}
    assert blocked == READ_BLOCKED_VIEWS.keys()


def test_admin_console_is_admin_only(routes):
    for r in routes:
        if r.path.startswith(ADMIN_CONSOLE_PREFIXES) and r.methods & MUTATING:
            assert not _admits(r, UserRole.WRITE), f"{sorted(r.methods)} {r.path} is open to WRITE"


# ── Behaviour ───────────────────────────────────────────────────────


def make_user(role: UserRole) -> UserContext:
    return UserContext(
        user_id=f"u-{role.value}",
        object_id="00000000-0000-0000-0000-000000000000",
        display_name="Test User",
        email=f"{role.value}@example.com",
        roles=[role],
        raw_roles=[role.value],
        tenant_id="tenant-test",
        allowed_subscriptions=[],
    )


@pytest.fixture
def strict_auth(monkeypatch):
    """Turn the dev bypass off — require_role skips every check while it is on."""
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    monkeypatch.setattr(settings, "DEV_AUTH_BYPASS", False)
    monkeypatch.setattr(settings, "K8S_DASHBOARD_SESSION_SECRET", "test-dashboard-session-secret")


@asynccontextmanager
async def client_as(app, db_session, user: UserContext, overrides=None):
    async def _get_db_override():
        yield db_session

    app.dependency_overrides[get_db] = _get_db_override
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides.update(overrides or {})
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            yield ac
    finally:
        app.dependency_overrides.clear()


def _dashboard_html():
    return httpx.Response(200, content=b"<html>ok</html>", headers={"content-type": "text/html"})


async def _dashboard_session(ac) -> tuple[str, bool]:
    launch = await ac.post("/api/v1/aks/dashboard/dev/launch")
    assert launch.status_code == 200
    exchange = await ac.get(launch.json()["proxy_url"], follow_redirects=False)
    return exchange.cookies.get("k8s_dash_session"), launch.json()["read_only"]


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE"])
async def test_read_only_dashboard_session_cannot_change_resources(app, db_session, strict_auth, method):
    with patch.object(
        K8sDashboardService, "proxy_request", new_callable=AsyncMock, return_value=_dashboard_html()
    ) as proxy:
        async with client_as(app, db_session, make_user(UserRole.READ)) as ac:
            cookie, read_only = await _dashboard_session(ac)
            viewed = await ac.get("/api/v1/aks/dashboard/dev/proxy/", cookies={"k8s_dash_session": cookie})
            changed = await ac.request(
                method,
                "/api/v1/aks/dashboard/dev/proxy/api/v1/_raw/deployment/namespace/apps/name/web",
                cookies={"k8s_dash_session": cookie},
            )

    assert read_only is True
    assert viewed.status_code == 200
    assert changed.status_code == 403
    assert [c.kwargs["method"] for c in proxy.await_args_list] == ["GET"]


async def test_write_dashboard_session_can_change_resources(app, db_session, strict_auth):
    with patch.object(
        K8sDashboardService, "proxy_request", new_callable=AsyncMock, return_value=_dashboard_html()
    ) as proxy:
        async with client_as(app, db_session, make_user(UserRole.WRITE)) as ac:
            cookie, read_only = await _dashboard_session(ac)
            resp = await ac.put(
                "/api/v1/aks/dashboard/dev/proxy/api/v1/scale/deployment/apps/web",
                cookies={"k8s_dash_session": cookie},
            )

    assert read_only is False
    assert resp.status_code == 200
    assert proxy.await_args.kwargs["method"] == "PUT"


async def test_dashboard_session_without_write_claim_is_read_only(app, db_session, strict_auth):
    """Sessions minted before write access was recorded must not keep full access."""
    legacy_launch = _create_launch_token("dev", "u-old", "old@example.com")  # no can_write
    with patch.object(K8sDashboardService, "proxy_request", new_callable=AsyncMock, return_value=_dashboard_html()):
        async with client_as(app, db_session, make_user(UserRole.ADMIN)) as ac:
            exchange = await ac.get(f"/api/v1/aks/dashboard/dev/launch/{legacy_launch}", follow_redirects=False)
            resp = await ac.delete(
                "/api/v1/aks/dashboard/dev/proxy/api/v1/_raw/pod/namespace/apps/name/web-1",
                cookies={"k8s_dash_session": exchange.cookies.get("k8s_dash_session")},
            )

    assert resp.status_code == 403


class _FakeInfraAlertService:
    def __init__(self):
        self.deleted: list[int] = []

    async def delete_vm_threshold_config(self, config_id: int) -> dict:
        self.deleted.append(config_id)
        return {"deleted": True, "id": config_id}

    async def list_alert_schedule_configs(self) -> list[dict]:
        return [{"id": 1, "name": "nightly"}]


@pytest.mark.parametrize(("role", "status"), [(UserRole.READ, 403), (UserRole.WRITE, 200)])
async def test_alert_config_delete_needs_write_not_admin(app, db_session, strict_auth, role, status):
    service = _FakeInfraAlertService()
    async with client_as(app, db_session, make_user(role), {infra_alerts._get_service: lambda: service}) as ac:
        resp = await ac.delete("/api/v1/infra-alerts/vm-thresholds/configs/7")

    assert resp.status_code == status
    assert service.deleted == ([7] if status == 200 else [])


async def test_read_only_users_can_view_alert_schedules(app, db_session, strict_auth):
    service = _FakeInfraAlertService()
    async with client_as(app, db_session, make_user(UserRole.READ), {infra_alerts._get_service: lambda: service}) as ac:
        resp = await ac.get("/api/v1/infra-alerts/scheduler/configs")

    assert resp.status_code == 200
    assert resp.json() == [{"id": 1, "name": "nightly"}]


@pytest.mark.parametrize(("role", "status"), [(UserRole.READ, 403), (UserRole.WRITE, 200)])
async def test_cost_cleanup_needs_write(app, db_session, strict_auth, monkeypatch, role, status):
    class FakeAzureResourceService:
        def __init__(self, db_session=None):
            pass

        async def delete_unattached_disk(self, subscription_id, resource_group, disk_name):
            return {"deleted": disk_name}

    monkeypatch.setattr("app.services.azure_resource_service.AzureResourceService", FakeAzureResourceService)
    body = {"subscription_id": "sub-1", "resource_group": "rg", "disk_name": "disk-01"}

    async with client_as(app, db_session, make_user(role)) as ac:
        resp = await ac.post("/api/v1/optimize/cleanup/disks", json=body)

    assert resp.status_code == status
