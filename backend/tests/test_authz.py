"""
Tests for the central portal authorization layer (``app.core.authz``).

Covers the three controls that must hold independently of the frontend:

  • portal access gate      — authenticated but unentitled → 403
  • module access gate      — no module grant → 403 on that module's APIs
  • operation capabilities  — per-operation grants, with a role fallback when
                              a capability has not been seeded

Plus the session endpoint, which must report an unauthorized identity as
``authorized: false`` (HTTP 200) rather than 403, so the UI can render Access
Denied instead of a broken shell.

All tests use the in-memory SQLite engine from conftest.py.
"""

from contextlib import asynccontextmanager

import pytest
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.auth import effective_roles, get_authenticated_identity, get_current_user, require_role
from app.core.authz import assert_capability, enforce_portal_access, granted_capabilities
from app.core.database import get_db
from app.models.database import Permission, Resource
from app.schemas.auth import UserContext, UserRole

# ── Helpers ────────────────────────────────────────────────────────────────────


def make_user(*roles: UserRole, user_id: str = "u-test") -> UserContext:
    """A UserContext with exactly the given roles (possibly none)."""
    return UserContext(
        user_id=user_id,
        object_id="00000000-0000-0000-0000-000000000000",
        display_name="Test User",
        email=f"{user_id}@example.com",
        roles=list(roles),
        raw_roles=[r.value for r in roles],
        tenant_id="tenant-test",
        allowed_subscriptions=[],
    )


@asynccontextmanager
async def client_as(app, db_session, user: UserContext, *, dependency=get_current_user):
    """AsyncClient authenticated as ``user`` with the SQLite session wired in."""

    async def _get_db_override():
        yield db_session

    async def _user_override():
        return user

    app.dependency_overrides[get_db] = _get_db_override
    app.dependency_overrides[dependency] = _user_override
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            yield ac
    finally:
        app.dependency_overrides.clear()


async def _resource(db_session, name: str, *, resource_type: str = "operation") -> Resource:
    res = Resource(resource_type=resource_type, resource_name=name, description=name, is_system=True)
    db_session.add(res)
    await db_session.commit()
    await db_session.refresh(res)
    return res


async def _grant(db_session, *, subject_type: str, subject_id: str, resource_id: int, permission_type: str) -> None:
    db_session.add(
        Permission(
            subject_type=subject_type,
            subject_id=subject_id,
            resource_id=resource_id,
            permission_type=permission_type,
            environment_scope="all",
        )
    )
    await db_session.commit()


# ── Portal access gate ─────────────────────────────────────────────────────────


async def test_portal_gate_rejects_identity_with_no_roles():
    """A valid identity holding no app role is not portal access."""

    class _Req:
        url = type("U", (), {"path": "/api/v1/costs/summary"})()

    with pytest.raises(HTTPException) as exc:
        await enforce_portal_access(_Req(), user=make_user())
    assert exc.value.status_code == 403


async def test_portal_gate_allows_identity_with_a_role():
    class _Req:
        url = type("U", (), {"path": "/api/v1/costs/summary"})()

    user = make_user(UserRole.READ)
    assert await enforce_portal_access(_Req(), user=user) is user


async def test_portal_gate_passes_through_unauthenticated_dashboard_routes():
    """The signed dashboard launch/proxy carve-out validates itself."""

    class _Req:
        url = type("U", (), {"path": "/api/v1/aks/dashboard/prod/proxy/api/v1/pod"})()

    assert await enforce_portal_access(_Req(), user=None) is None


# ── Operation capabilities ─────────────────────────────────────────────────────


async def test_capability_granted_via_role(db_session):
    res = await _resource(db_session, "aks_pod_delete")
    await _grant(db_session, subject_type="role", subject_id="write", resource_id=res.id, permission_type="edit")

    # Does not raise
    await assert_capability(db_session, user=make_user(UserRole.WRITE), capability="aks_pod_delete")


async def test_capability_denied_when_role_not_granted(db_session):
    res = await _resource(db_session, "aks_pod_delete")
    await _grant(db_session, subject_type="role", subject_id="write", resource_id=res.id, permission_type="edit")

    with pytest.raises(HTTPException) as exc:
        await assert_capability(db_session, user=make_user(UserRole.READ), capability="aks_pod_delete")
    assert exc.value.status_code == 403
    # The specific capability must not leak to the client.
    assert "aks_pod_delete" not in exc.value.detail


async def test_capability_granted_directly_to_user(db_session):
    """A user-specific grant works without holding the role."""
    res = await _resource(db_session, "aks_job_delete")
    await _grant(db_session, subject_type="user", subject_id="u-special", resource_id=res.id, permission_type="edit")

    await assert_capability(
        db_session,
        user=make_user(UserRole.READ, user_id="u-special"),
        capability="aks_job_delete",
    )


async def test_admin_bypasses_capability_checks(db_session):
    """Admin needs no permission record — consistent with the rest of the portal."""
    await assert_capability(db_session, user=make_user(UserRole.ADMIN), capability="never_seeded")


async def test_unregistered_capability_falls_back_to_role(db_session):
    """A missing capability row must not open the operation up.

    It degrades to the coarse role requirement, so the effective permission is
    never weaker than the role-only checks the capability layer replaced.
    """
    await assert_capability(
        db_session,
        user=make_user(UserRole.WRITE),
        capability="not_in_db",
        fallback_role=UserRole.WRITE,
    )

    with pytest.raises(HTTPException) as exc:
        await assert_capability(
            db_session,
            user=make_user(UserRole.READ),
            capability="not_in_db",
            fallback_role=UserRole.WRITE,
        )
    assert exc.value.status_code == 403


async def test_view_and_edit_capabilities_are_distinct(db_session):
    """Holding view on a capability does not imply permission to perform it."""
    res = await _resource(db_session, "aks_secret_view")
    await _grant(db_session, subject_type="role", subject_id="read", resource_id=res.id, permission_type="view")

    await assert_capability(
        db_session, user=make_user(UserRole.READ), capability="aks_secret_view", permission_type="view"
    )

    with pytest.raises(HTTPException):
        await assert_capability(
            db_session, user=make_user(UserRole.READ), capability="aks_secret_view", permission_type="edit"
        )


async def test_granted_capabilities_lists_only_held_operations(db_session):
    allowed = await _resource(db_session, "aks_pod_delete")
    await _resource(db_session, "aks_job_delete")
    await _grant(db_session, subject_type="role", subject_id="write", resource_id=allowed.id, permission_type="edit")

    held = await granted_capabilities(db_session, make_user(UserRole.WRITE))
    assert held == ["aks_pod_delete"]


async def test_granted_capabilities_for_admin_includes_all(db_session):
    await _resource(db_session, "aks_pod_delete")
    await _resource(db_session, "aks_job_delete")

    held = await granted_capabilities(db_session, make_user(UserRole.ADMIN))
    assert held == ["aks_job_delete", "aks_pod_delete"]


async def test_capability_ignores_operations_of_other_resource_types(db_session):
    """Only resource_type='operation' rows count as capabilities."""
    await _resource(db_session, "aks_main", resource_type="page")
    held = await granted_capabilities(db_session, make_user(UserRole.ADMIN))
    assert "aks_main" not in held


async def test_edit_grant_satisfies_a_view_capability(db_session):
    """The admin UI's "View + Edit" writes only an edit row.

    Treating that as insufficient for a view capability would deny access the
    operator plainly intended to grant.
    """
    res = await _resource(db_session, "aks_secret_view")
    await _grant(db_session, subject_type="role", subject_id="write", resource_id=res.id, permission_type="edit")

    await assert_capability(
        db_session, user=make_user(UserRole.WRITE), capability="aks_secret_view", permission_type="view"
    )


async def test_granted_capabilities_respects_required_permission_type(db_session):
    """A view-only grant must not advertise an edit capability.

    Otherwise the UI shows a button that the API then rejects with 403.
    """
    res = await _resource(db_session, "aks_pod_delete")
    await _grant(db_session, subject_type="role", subject_id="read", resource_id=res.id, permission_type="view")

    held = await granted_capabilities(db_session, make_user(UserRole.READ))
    assert held == []

    with pytest.raises(HTTPException):
        await assert_capability(db_session, user=make_user(UserRole.READ), capability="aks_pod_delete")


async def test_granted_capabilities_reports_view_capability_from_edit_grant(db_session):
    res = await _resource(db_session, "aks_pod_view")
    await _grant(db_session, subject_type="role", subject_id="write", resource_id=res.id, permission_type="edit")

    held = await granted_capabilities(db_session, make_user(UserRole.WRITE))
    assert held == ["aks_pod_view"]


# ── Module access gate ─────────────────────────────────────────────────────────


async def test_module_gate_blocks_api_without_module_grant(app, db_session):
    """Direct API access must be blocked, not just the frontend route."""
    await _resource(db_session, "aks_operations", resource_type="module")

    async with client_as(app, db_session, make_user(UserRole.READ)) as ac:
        resp = await ac.get("/api/v1/aks/namespaces", params={"cluster_id": "c1"})
    assert resp.status_code == 403


async def test_module_gate_allows_api_with_module_grant(app, db_session):
    """With a view grant the request passes the gate (503/5xx from Azure is fine)."""
    res = await _resource(db_session, "aks_operations", resource_type="module")
    await _grant(db_session, subject_type="role", subject_id="read", resource_id=res.id, permission_type="view")

    async with client_as(app, db_session, make_user(UserRole.READ)) as ac:
        resp = await ac.get("/api/v1/aks/namespaces", params={"cluster_id": "c1"})
    assert resp.status_code != 403


async def test_module_gate_accepts_an_edit_only_grant(app, db_session):
    """Regression: an edit-only module grant used to 403 every API in it."""
    res = await _resource(db_session, "aks_operations", resource_type="module")
    await _grant(db_session, subject_type="role", subject_id="read", resource_id=res.id, permission_type="edit")

    async with client_as(app, db_session, make_user(UserRole.READ)) as ac:
        resp = await ac.get("/api/v1/aks/namespaces", params={"cluster_id": "c1"})
    assert resp.status_code != 403


async def test_module_gate_does_not_gate_unmapped_prefixes(app, db_session):
    """Cross-module infrastructure routes are intentionally not module-gated."""
    await _resource(db_session, "aks_operations", resource_type="module")

    async with client_as(app, db_session, make_user(UserRole.READ)) as ac:
        resp = await ac.get("/api/v1/auth/me")
    assert resp.status_code == 200


async def test_admin_bypasses_module_gate(app, db_session):
    await _resource(db_session, "aks_operations", resource_type="module")

    async with client_as(app, db_session, make_user(UserRole.ADMIN)) as ac:
        resp = await ac.get("/api/v1/aks/namespaces", params={"cluster_id": "c1"})
    assert resp.status_code != 403


# ── Session endpoint ──────────────────────────────────────────────────────────


async def test_session_reports_unauthorized_without_403(app, db_session):
    """Authenticated + unentitled must be a 200 the UI can act on."""
    async with client_as(app, db_session, make_user(), dependency=get_authenticated_identity) as ac:
        resp = await ac.get("/api/v1/auth/session")

    assert resp.status_code == 200
    body = resp.json()
    assert body["authenticated"] is True
    assert body["authorized"] is False
    assert body["permissions"] == []
    # An unauthorized caller must learn nothing privileged.
    assert body["roles"] == []
    assert body["is_admin"] is False
    assert body["can_write"] is False


async def test_session_reports_authorized_with_capabilities(app, db_session):
    res = await _resource(db_session, "aks_pod_delete")
    await _grant(db_session, subject_type="role", subject_id="write", resource_id=res.id, permission_type="edit")

    async with client_as(app, db_session, make_user(UserRole.WRITE), dependency=get_authenticated_identity) as ac:
        resp = await ac.get("/api/v1/auth/session")

    assert resp.status_code == 200
    body = resp.json()
    assert body["authorized"] is True
    assert body["can_write"] is True
    # Upper-cased for the documented frontend contract.
    assert "AKS_POD_DELETE" in body["permissions"]


# ── Development bypass hardening ───────────────────────────────────────────────


async def test_dev_bypass_does_not_upgrade_an_invalid_token():
    """The dev bypass must never turn a rejected token into a synthetic admin.

    Regression guard: the previous implementation caught the 401 from token
    validation and returned an ADMIN UserContext, so any garbage bearer token
    granted full administrative access whenever the bypass was on.
    """
    from fastapi.security import HTTPAuthorizationCredentials

    from app.core.config import settings

    original_env, original_bypass = settings.ENVIRONMENT, settings.DEV_AUTH_BYPASS
    settings.ENVIRONMENT, settings.DEV_AUTH_BYPASS = "development", True

    class _Req:
        url = type("U", (), {"path": "/api/v1/costs/summary"})()
        state = type("S", (), {})()

    try:
        with pytest.raises(HTTPException) as exc:
            await get_authenticated_identity(
                _Req(),
                credentials=HTTPAuthorizationCredentials(scheme="Bearer", credentials="not-a-real-token"),
            )
        assert exc.value.status_code == 401
    finally:
        settings.ENVIRONMENT, settings.DEV_AUTH_BYPASS = original_env, original_bypass


async def test_dev_bypass_still_allows_a_tokenless_request():
    """Local development ergonomics are preserved for requests with no token."""
    from app.core.config import settings

    original_env, original_bypass = settings.ENVIRONMENT, settings.DEV_AUTH_BYPASS
    settings.ENVIRONMENT, settings.DEV_AUTH_BYPASS = "development", True

    class _Req:
        url = type("U", (), {"path": "/api/v1/costs/summary"})()
        state = type("S", (), {})()

    try:
        user = await get_authenticated_identity(_Req(), credentials=None)
        assert user is not None
        assert user.is_admin
    finally:
        settings.ENVIRONMENT, settings.DEV_AUTH_BYPASS = original_env, original_bypass


async def test_startup_refuses_dev_bypass_outside_development():
    """Fail closed: a mis-provisioned ENVIRONMENT must not run unauthenticated."""
    from app.core.config import settings
    from app.main import create_application, lifespan

    original_env, original_bypass = settings.ENVIRONMENT, settings.DEV_AUTH_BYPASS
    settings.ENVIRONMENT, settings.DEV_AUTH_BYPASS = "production", True

    try:
        with pytest.raises(RuntimeError, match="DEV_AUTH_BYPASS"):
            async with lifespan(create_application()):
                pass
    finally:
        settings.ENVIRONMENT, settings.DEV_AUTH_BYPASS = original_env, original_bypass


async def test_session_requires_authentication(app):
    """No credentials at all → 401, never an anonymous session."""
    from app.core.config import settings

    original = settings.DEV_AUTH_BYPASS
    settings.DEV_AUTH_BYPASS = False
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            resp = await ac.get("/api/v1/auth/session")
        assert resp.status_code == 401
    finally:
        settings.DEV_AUTH_BYPASS = original


# ── Role ladder ────────────────────────────────────────────────────────────────


@pytest.fixture
def strict_auth():
    """Pin the dev bypass off for the duration of a test.

    ``require_role`` returns early when the bypass is enabled, and the local
    .env turns it on, so without this every role assertion would pass
    vacuously and prove nothing about enforcement.
    """
    from app.core.config import settings

    original_env, original_bypass = settings.ENVIRONMENT, settings.DEV_AUTH_BYPASS
    settings.ENVIRONMENT, settings.DEV_AUTH_BYPASS = "production", False
    try:
        yield
    finally:
        settings.ENVIRONMENT, settings.DEV_AUTH_BYPASS = original_env, original_bypass


async def test_write_satisfies_a_read_requirement(strict_auth):
    """WRITE implies READ.

    Entra assigns one app role per user, so a write user's token carries
    "write" and nothing else.  Before the ladder existed, a route declared as
    ``require_role(UserRole.READ)`` 403'd that user for a plain read.
    """
    checker = require_role(UserRole.READ)
    user = make_user(UserRole.WRITE)
    assert await checker(user=user) is user


async def test_admin_satisfies_a_write_requirement(strict_auth):
    checker = require_role(UserRole.WRITE)
    user = make_user(UserRole.ADMIN)
    assert await checker(user=user) is user


async def test_read_does_not_satisfy_a_write_requirement(strict_auth):
    """The ladder only runs one way — read must never imply write."""
    checker = require_role(UserRole.WRITE)
    with pytest.raises(HTTPException) as exc:
        await checker(user=make_user(UserRole.READ))
    assert exc.value.status_code == 403


async def test_effective_roles_expands_the_ladder():
    assert effective_roles(make_user(UserRole.ADMIN)) == {UserRole.ADMIN, UserRole.WRITE, UserRole.READ}
    assert effective_roles(make_user(UserRole.WRITE)) == {UserRole.WRITE, UserRole.READ}
    assert effective_roles(make_user(UserRole.READ)) == {UserRole.READ}
    assert effective_roles(make_user()) == frozenset()


async def test_capability_role_fallback_honours_the_ladder(db_session):
    """An unseeded capability with a READ fallback must admit a WRITE user."""
    await assert_capability(
        db_session,
        user=make_user(UserRole.WRITE),
        capability="not_in_db",
        permission_type="view",
        fallback_role=UserRole.READ,
    )


# ── VM / PG power capabilities ─────────────────────────────────────────────────


async def test_vm_power_capability_granted_to_write_by_default(db_session):
    """A write user must be able to stop a VM.

    The Infrastructure Alerts grid renders the power buttons for anyone who
    can write, so an admin-only backend left those users clicking a button
    that always 403'd.
    """
    from app.core.resource_registry import seed_permissions, seed_resources

    await seed_resources(db_session)
    await seed_permissions(db_session)

    await assert_capability(db_session, user=make_user(UserRole.WRITE), capability="infra_vm_power")
    await assert_capability(db_session, user=make_user(UserRole.WRITE), capability="infra_pg_server_power")


async def test_vm_power_capability_denied_to_read(db_session):
    from app.core.resource_registry import seed_permissions, seed_resources

    await seed_resources(db_session)
    await seed_permissions(db_session)

    with pytest.raises(HTTPException) as exc:
        await assert_capability(db_session, user=make_user(UserRole.READ), capability="infra_vm_power")
    assert exc.value.status_code == 403


async def test_vm_power_capability_is_revocable_per_subject(db_session):
    """Removing the write-role grant must deny write users without touching
    any other operation — the reason power control is a capability rather
    than a plain role check."""
    from sqlalchemy import delete

    from app.core.resource_registry import seed_permissions, seed_resources

    await seed_resources(db_session)
    await seed_permissions(db_session)

    resource_id = (
        await db_session.execute(select(Resource.id).where(Resource.resource_name == "infra_vm_power"))
    ).scalar_one()
    await db_session.execute(
        delete(Permission).where(Permission.resource_id == resource_id, Permission.subject_id == "write")
    )
    await db_session.commit()

    with pytest.raises(HTTPException):
        await assert_capability(db_session, user=make_user(UserRole.WRITE), capability="infra_vm_power")

    # Unrelated capability still held.
    await assert_capability(db_session, user=make_user(UserRole.WRITE), capability="aks_pod_delete")


# ── Plugin routers inherit the module gate ─────────────────────────────────────


async def test_plugin_paths_are_mapped_to_their_module():
    """Plugin routers mount outside api_router, so they must be listed
    explicitly or they become an ungated second door into a module."""
    from app.core.authz import _module_for_path

    assert _module_for_path("/api/v1/plugins/keyvault_ops/secrets") == "keyvault"
    assert _module_for_path("/api/v1/plugins/aks_insights/clusters") == "aks_operations"
