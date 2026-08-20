"""
Unit tests for the granular RBAC endpoints (/api/v1/permissions/*), the
effective-permissions endpoint (/api/v1/auth/my-permissions), and the
audit log endpoint (/api/v1/permissions/audit-log).

All tests use the SQLite in-memory engine from conftest.py — no live Postgres
required.  Each test function gets a fresh session (function-scoped fixture) so
tests cannot interfere with each other.

Conventions:
  • admin_client  — authenticated as ADMIN, DB wired to SQLite
  • reader_client — authenticated as READ role, DB wired to SQLite
  • Fixtures are defined in tests/conftest.py
"""

import pytest

# ── Helpers ────────────────────────────────────────────────────────────────────


async def _create_resource(client, name: str, rtype: str = "module", **kwargs) -> dict:
    resp = await client.post(
        "/api/v1/permissions/resources",
        json={"resource_type": rtype, "resource_name": name, **kwargs},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


async def _create_permission(
    client, subject_type: str, subject_id: str, resource_id: int, permission_type: str
) -> dict:
    resp = await client.post(
        "/api/v1/permissions/permissions",
        json={
            "subject_type": subject_type,
            "subject_id": subject_id,
            "resource_id": resource_id,
            "permission_type": permission_type,
        },
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


# ── Resource CRUD ──────────────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_create_resource_returns_correct_fields(admin_client):
    res = await _create_resource(
        admin_client, "test_module", rtype="module", description="A test module", route_path="/test"
    )
    assert res["resource_name"] == "test_module"
    assert res["resource_type"] == "module"
    assert res["description"] == "A test module"
    assert res["route_path"] == "/test"
    assert res["is_system"] is False
    assert "id" in res


@pytest.mark.anyio
async def test_create_resource_idempotent_on_duplicate_name(admin_client):
    r1 = await _create_resource(admin_client, "idempotent_module")
    r2 = await _create_resource(admin_client, "idempotent_module")
    assert r1["id"] == r2["id"]


@pytest.mark.anyio
async def test_list_resources_returns_all(admin_client):
    await _create_resource(admin_client, "mod_a", rtype="module")
    await _create_resource(admin_client, "mod_b", rtype="module")
    resp = await admin_client.get("/api/v1/permissions/resources")
    assert resp.status_code == 200
    names = [r["resource_name"] for r in resp.json()]
    assert "mod_a" in names
    assert "mod_b" in names


@pytest.mark.anyio
async def test_get_resource_by_id(admin_client):
    created = await _create_resource(admin_client, "get_by_id_mod")
    resp = await admin_client.get(f"/api/v1/permissions/resources/{created['id']}")
    assert resp.status_code == 200
    assert resp.json()["resource_name"] == "get_by_id_mod"


@pytest.mark.anyio
async def test_get_resource_unknown_id_returns_404(admin_client):
    resp = await admin_client.get("/api/v1/permissions/resources/99999")
    assert resp.status_code == 404


@pytest.mark.anyio
async def test_update_resource_description(admin_client):
    created = await _create_resource(admin_client, "update_me", description="old")
    resp = await admin_client.patch(
        f"/api/v1/permissions/resources/{created['id']}",
        json={"description": "updated description"},
    )
    assert resp.status_code == 200
    assert resp.json()["description"] == "updated description"


@pytest.mark.anyio
async def test_delete_custom_resource(admin_client):
    created = await _create_resource(admin_client, "deletable_module")
    del_resp = await admin_client.delete(f"/api/v1/permissions/resources/{created['id']}")
    assert del_resp.status_code == 200
    assert del_resp.json()["deleted"] is True

    get_resp = await admin_client.get(f"/api/v1/permissions/resources/{created['id']}")
    assert get_resp.status_code == 404


@pytest.mark.anyio
async def test_delete_unknown_resource_returns_404(admin_client):
    resp = await admin_client.delete("/api/v1/permissions/resources/99999")
    assert resp.status_code == 404


@pytest.mark.anyio
async def test_system_resource_cannot_be_deleted(admin_client, db_session):
    # Insert a system resource directly via the DB session
    from app.models.database import Resource as ResourceModel

    sys_res = ResourceModel(
        resource_type="module",
        resource_name="system_protected",
        description="Cannot be deleted",
        is_system=True,
    )
    db_session.add(sys_res)
    await db_session.commit()
    await db_session.refresh(sys_res)

    resp = await admin_client.delete(f"/api/v1/permissions/resources/{sys_res.id}")
    assert resp.status_code == 403
    assert "System resources" in resp.json()["detail"]


@pytest.mark.anyio
async def test_create_page_resource_with_parent(admin_client):
    module = await _create_resource(admin_client, "parent_mod", rtype="module")
    page = await _create_resource(
        admin_client, "child_page", rtype="page", parent_id=module["id"], route_path="/parent/child"
    )
    assert page["parent_id"] == module["id"]
    assert page["route_path"] == "/parent/child"


@pytest.mark.anyio
async def test_non_admin_cannot_create_resource(reader_client, monkeypatch):
    import app.auth as auth_module

    monkeypatch.setattr(auth_module.settings, "ENVIRONMENT", "production")
    resp = await reader_client.post(
        "/api/v1/permissions/resources",
        json={"resource_type": "module", "resource_name": "should_fail"},
    )
    assert resp.status_code == 403


# ── Permission CRUD ────────────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_grant_role_view_permission(admin_client):
    res = await _create_resource(admin_client, "perm_module")
    perm = await _create_permission(admin_client, "role", "read", res["id"], "view")
    assert perm["subject_type"] == "role"
    assert perm["subject_id"] == "read"
    assert perm["permission_type"] == "view"
    assert perm["resource_name"] == "perm_module"


@pytest.mark.anyio
async def test_grant_user_edit_permission(admin_client):
    res = await _create_resource(admin_client, "user_perm_module")
    perm = await _create_permission(admin_client, "user", "user-uuid-abc", res["id"], "edit")
    assert perm["subject_type"] == "user"
    assert perm["subject_id"] == "user-uuid-abc"
    assert perm["permission_type"] == "edit"


@pytest.mark.anyio
async def test_group_subject_type_is_valid(admin_client):
    res = await _create_resource(admin_client, "group_subject_module")
    resp = await admin_client.post(
        "/api/v1/permissions/permissions",
        json={"subject_type": "group", "subject_id": "dev-team", "resource_id": res["id"], "permission_type": "view"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["subject_type"] == "group"
    assert data["subject_id"] == "dev-team"


@pytest.mark.anyio
async def test_invalid_permission_type_returns_400(admin_client):
    res = await _create_resource(admin_client, "bad_perm_type_module")
    resp = await admin_client.post(
        "/api/v1/permissions/permissions",
        json={"subject_type": "role", "subject_id": "read", "resource_id": res["id"], "permission_type": "superadmin"},
    )
    assert resp.status_code == 400


@pytest.mark.anyio
async def test_grant_permission_unknown_resource_returns_404(admin_client):
    resp = await admin_client.post(
        "/api/v1/permissions/permissions",
        json={"subject_type": "role", "subject_id": "read", "resource_id": 99999, "permission_type": "view"},
    )
    assert resp.status_code == 404


@pytest.mark.anyio
async def test_list_permissions(admin_client):
    res = await _create_resource(admin_client, "list_perm_mod")
    await _create_permission(admin_client, "role", "write", res["id"], "view")
    resp = await admin_client.get("/api/v1/permissions/permissions")
    assert resp.status_code == 200
    perms = resp.json()
    assert any(p["subject_id"] == "write" and p["resource_name"] == "list_perm_mod" for p in perms)


@pytest.mark.anyio
async def test_revoke_permission(admin_client):
    res = await _create_resource(admin_client, "revoke_perm_mod")
    perm = await _create_permission(admin_client, "role", "read", res["id"], "view")
    del_resp = await admin_client.delete(f"/api/v1/permissions/permissions/{perm['id']}")
    assert del_resp.status_code == 200
    assert del_resp.json()["deleted"] is True


@pytest.mark.anyio
async def test_revoke_unknown_permission_returns_404(admin_client):
    resp = await admin_client.delete("/api/v1/permissions/permissions/99999")
    assert resp.status_code == 404


@pytest.mark.anyio
async def test_non_admin_cannot_list_permissions(reader_client, monkeypatch):
    import app.auth as auth_module

    monkeypatch.setattr(auth_module.settings, "ENVIRONMENT", "production")
    resp = await reader_client.get("/api/v1/permissions/permissions")
    assert resp.status_code == 403


# ── /auth/my-permissions ───────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_my_permissions_admin_gets_all_resources(admin_client, db_session):
    from app.models.database import Resource as Res

    for name in ("admin_mod_x", "admin_page_y"):
        db_session.add(Res(resource_type="module", resource_name=name, is_system=False))
    await db_session.commit()

    resp = await admin_client.get("/api/v1/auth/my-permissions")
    assert resp.status_code == 200
    data = resp.json()
    assert data["is_admin"] is True
    assert "admin_mod_x" in data["modules"]
    # New shape: resource_name → { env_scope: [perms] }
    assert "all" in data["modules"]["admin_mod_x"]
    assert sorted(data["modules"]["admin_mod_x"]["all"]) == ["edit", "view"]


@pytest.mark.anyio
async def test_my_permissions_reader_sees_granted_resources(app, db_session):
    from httpx import ASGITransport, AsyncClient

    from app.auth import get_current_user
    from app.core.database import get_db
    from app.models.database import Permission as Perm
    from app.models.database import Resource as Res
    from tests.conftest import make_read_user

    # Seed: one module + one role permission for 'read' role
    mod = Res(resource_type="module", resource_name="reader_accessible_mod", is_system=False)
    db_session.add(mod)
    await db_session.flush()
    perm = Perm(subject_type="role", subject_id="read", resource_id=mod.id, permission_type="view")
    db_session.add(perm)
    await db_session.commit()

    async def _override_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[get_current_user] = make_read_user

    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            resp = await ac.get("/api/v1/auth/my-permissions")
        assert resp.status_code == 200
        data = resp.json()
        assert data["is_admin"] is False
        assert "reader_accessible_mod" in data["modules"]
        # New shape: resource_name → { env_scope: [perms] }
        assert "all" in data["modules"]["reader_accessible_mod"]
        assert "view" in data["modules"]["reader_accessible_mod"]["all"]
    finally:
        app.dependency_overrides.clear()


@pytest.mark.anyio
async def test_my_permissions_reader_inherits_module_access_to_page(app, db_session):
    from httpx import ASGITransport, AsyncClient

    from app.auth import get_current_user
    from app.core.database import get_db
    from app.models.database import Permission as Perm
    from app.models.database import Resource as Res
    from tests.conftest import make_read_user

    # Seed: module → page hierarchy, permission only on module
    mod = Res(resource_type="module", resource_name="inherit_mod", is_system=False)
    db_session.add(mod)
    await db_session.flush()
    page = Res(resource_type="page", resource_name="inherit_page", parent_id=mod.id, is_system=False)
    db_session.add(page)
    perm = Perm(subject_type="role", subject_id="read", resource_id=mod.id, permission_type="view")
    db_session.add(perm)
    await db_session.commit()

    async def _override_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[get_current_user] = make_read_user

    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            resp = await ac.get("/api/v1/auth/my-permissions")
        data = resp.json()
        # Page should inherit access from parent module
        assert "inherit_page" in data["pages"], f"Page inheritance failed. pages={data['pages']}"
        # New shape: page → { env_scope: [perms] }
        assert "all" in data["pages"]["inherit_page"]
        assert "view" in data["pages"]["inherit_page"]["all"]
    finally:
        app.dependency_overrides.clear()


# ── Audit Log ──────────────────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_audit_log_records_permission_grant(admin_client):
    """Granting a permission writes a permission_granted audit entry."""
    res = await _create_resource(admin_client, "audit_grant_mod")
    await _create_permission(admin_client, "role", "read", res["id"], "view")

    resp = await admin_client.get("/api/v1/permissions/audit-log")
    assert resp.status_code == 200
    entries = resp.json()["entries"]
    grant_entries = [e for e in entries if e["action"] == "permission_granted"]
    assert any(e["resource_name"] == "audit_grant_mod" and e["subject_id"] == "read" for e in grant_entries), (
        f"Expected permission_granted entry not found in: {grant_entries}"
    )


@pytest.mark.anyio
async def test_audit_log_records_permission_revoke(admin_client):
    """Revoking a permission writes a permission_revoked audit entry."""
    res = await _create_resource(admin_client, "audit_revoke_mod")
    perm = await _create_permission(admin_client, "role", "write", res["id"], "edit")
    await admin_client.delete(f"/api/v1/permissions/permissions/{perm['id']}")

    resp = await admin_client.get("/api/v1/permissions/audit-log")
    assert resp.status_code == 200
    entries = resp.json()["entries"]
    revoke_entries = [e for e in entries if e["action"] == "permission_revoked"]
    assert any(e["resource_name"] == "audit_revoke_mod" and e["subject_id"] == "write" for e in revoke_entries), (
        f"Expected permission_revoked entry not found in: {revoke_entries}"
    )


@pytest.mark.anyio
async def test_audit_log_records_resource_creation(admin_client):
    """Creating a resource writes a resource_created audit entry."""
    await _create_resource(admin_client, "audit_create_res", rtype="module", description="For audit test")

    resp = await admin_client.get("/api/v1/permissions/audit-log")
    assert resp.status_code == 200
    entries = resp.json()["entries"]
    created_entries = [e for e in entries if e["action"] == "resource_created"]
    assert any(e["resource_name"] == "audit_create_res" for e in created_entries), (
        f"Expected resource_created entry not found in: {created_entries}"
    )


@pytest.mark.anyio
async def test_audit_log_records_resource_deletion(admin_client):
    """Deleting a custom resource writes a resource_deleted audit entry."""
    res = await _create_resource(admin_client, "audit_delete_res")
    await admin_client.delete(f"/api/v1/permissions/resources/{res['id']}")

    resp = await admin_client.get("/api/v1/permissions/audit-log")
    assert resp.status_code == 200
    entries = resp.json()["entries"]
    deleted_entries = [e for e in entries if e["action"] == "resource_deleted"]
    assert any(e["resource_name"] == "audit_delete_res" for e in deleted_entries), (
        f"Expected resource_deleted entry not found in: {deleted_entries}"
    )


@pytest.mark.anyio
async def test_audit_log_entry_has_required_fields(admin_client):
    """Every audit entry contains the mandatory fields."""
    res = await _create_resource(admin_client, "audit_fields_mod")
    await _create_permission(admin_client, "role", "read", res["id"], "view")

    resp = await admin_client.get("/api/v1/permissions/audit-log")
    assert resp.status_code == 200
    entries = resp.json()["entries"]
    assert len(entries) > 0, "Audit log should not be empty"

    entry = entries[0]
    for field in ("id", "timestamp", "actor_user_id", "actor_email", "action", "summary"):
        assert field in entry, f"Missing required field '{field}' in audit entry"
    assert entry["actor_user_id"] == "test-admin"
    assert entry["actor_email"] == "admin@example.com"


@pytest.mark.anyio
async def test_audit_log_summary_is_human_readable(admin_client):
    """The summary field describes the action in plain language."""
    res = await _create_resource(admin_client, "audit_summary_mod")
    await _create_permission(admin_client, "role", "read", res["id"], "view")

    resp = await admin_client.get("/api/v1/permissions/audit-log")
    entries = resp.json()["entries"]
    grant = next((e for e in entries if e["action"] == "permission_granted"), None)
    assert grant is not None
    assert "view" in grant["summary"]
    assert "audit_summary_mod" in grant["summary"]


@pytest.mark.anyio
async def test_audit_log_returns_newest_first(admin_client):
    """Entries are ordered from newest to oldest."""
    res = await _create_resource(admin_client, "audit_order_mod")
    await _create_permission(admin_client, "role", "read", res["id"], "view")
    await _create_permission(admin_client, "role", "write", res["id"], "edit")

    resp = await admin_client.get("/api/v1/permissions/audit-log")
    entries = resp.json()["entries"]
    timestamps = [e["timestamp"] for e in entries]
    assert timestamps == sorted(timestamps, reverse=True), "Audit entries should be ordered newest-first"


@pytest.mark.anyio
async def test_audit_log_non_admin_cannot_access(reader_client, monkeypatch):
    """Non-admin users cannot read the audit log."""
    import app.auth as auth_module

    monkeypatch.setattr(auth_module.settings, "ENVIRONMENT", "production")
    resp = await reader_client.get("/api/v1/permissions/audit-log")
    assert resp.status_code == 403


# ── Phase 1: AD Group Blocking Validation ──────────────────────────────────────


@pytest.mark.anyio
async def test_no_role_user_blocked_in_production(app, db_session, monkeypatch):
    """Users with no recognized app roles get 403 in production."""
    import app.auth as auth_module

    monkeypatch.setattr(auth_module.settings, "ENVIRONMENT", "production")

    from app.schemas.auth import UserContext

    async def make_norole_user() -> UserContext:
        return UserContext(
            user_id="no-role-user",
            object_id="22222222-2222-2222-2222-222222222222",
            display_name="No Role User",
            email="norole@example.com",
            roles=[],
            raw_roles=[],
            tenant_id="tenant-test",
            allowed_subscriptions=[],
        )

    from app.auth import get_current_user
    from app.core.database import get_db

    async def _get_db_override():
        yield db_session

    # Override with a user that has empty roles — the require_role
    # decorator on admin endpoints should reject this
    app.dependency_overrides[get_db] = _get_db_override
    app.dependency_overrides[get_current_user] = make_norole_user

    try:
        from httpx import ASGITransport, AsyncClient

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            resp = await ac.get("/api/v1/permissions/resources")
        assert resp.status_code == 403
    finally:
        app.dependency_overrides.clear()


@pytest.mark.anyio
async def test_read_role_user_can_access_auth_me(app, db_session):
    """Users with at least READ role can access /auth/me."""
    from httpx import ASGITransport, AsyncClient

    from app.auth import get_current_user
    from app.core.database import get_db
    from tests.conftest import make_read_user

    async def _get_db_override():
        yield db_session

    app.dependency_overrides[get_db] = _get_db_override
    app.dependency_overrides[get_current_user] = make_read_user

    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            resp = await ac.get("/api/v1/auth/me")
        assert resp.status_code == 200
        data = resp.json()
        assert data["user_id"] == "test-reader"
        assert "read" in data["roles"]
    finally:
        app.dependency_overrides.clear()


@pytest.mark.anyio
async def test_unauthenticated_request_returns_401(app, monkeypatch):
    """Requests without a Bearer token get 401 in production mode."""
    import app.auth as auth_module

    monkeypatch.setattr(auth_module.settings, "ENVIRONMENT", "production")
    monkeypatch.setattr(auth_module.settings, "DEV_AUTH_BYPASS", False)

    from httpx import ASGITransport, AsyncClient

    # Clear all overrides so actual auth fires
    app.dependency_overrides.clear()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.get(
            "/api/v1/auth/me",
            headers={"Authorization": ""},
        )
    # In production mode, missing/invalid token → 401 or 403
    assert resp.status_code in (401, 403)


# ── Phase 2: Environment-scoped permissions ────────────────────────────────────


@pytest.mark.anyio
async def test_create_permission_with_environment_scope(admin_client):
    """Permissions can be created with a specific environment scope."""
    res = await _create_resource(admin_client, "env_scope_module")
    resp = await admin_client.post(
        "/api/v1/permissions/permissions",
        json={
            "subject_type": "group",
            "subject_id": "dev-team",
            "resource_id": res["id"],
            "permission_type": "view",
            "environment_scope": "prod",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["environment_scope"] == "prod"
    assert data["subject_type"] == "group"


@pytest.mark.anyio
async def test_create_permission_defaults_to_all_scope(admin_client):
    """Omitting environment_scope defaults to 'all'."""
    res = await _create_resource(admin_client, "default_scope_mod")
    resp = await admin_client.post(
        "/api/v1/permissions/permissions",
        json={
            "subject_type": "role",
            "subject_id": "write",
            "resource_id": res["id"],
            "permission_type": "edit",
        },
    )
    assert resp.status_code == 200
    assert resp.json()["environment_scope"] == "all"


@pytest.mark.anyio
async def test_invalid_environment_scope_returns_400(admin_client):
    """Invalid environment_scope value returns 400."""
    res = await _create_resource(admin_client, "bad_env_scope_mod")
    resp = await admin_client.post(
        "/api/v1/permissions/permissions",
        json={
            "subject_type": "role",
            "subject_id": "read",
            "resource_id": res["id"],
            "permission_type": "view",
            "environment_scope": "staging",
        },
    )
    assert resp.status_code == 400
    assert "environment_scope" in resp.json()["detail"]


@pytest.mark.anyio
async def test_invalid_subject_type_returns_400(admin_client):
    """Invalid subject_type returns 400."""
    res = await _create_resource(admin_client, "invalid_subj_mod")
    resp = await admin_client.post(
        "/api/v1/permissions/permissions",
        json={"subject_type": "unknown", "subject_id": "x", "resource_id": res["id"], "permission_type": "view"},
    )
    assert resp.status_code == 400


@pytest.mark.anyio
async def test_my_permissions_includes_env_scope(app, db_session):
    """Effective permissions response includes environment scope."""
    from httpx import ASGITransport, AsyncClient

    from app.auth import get_current_user
    from app.core.database import get_db
    from app.models.database import Permission as Perm
    from app.models.database import Resource as Res
    from tests.conftest import make_read_user

    mod = Res(resource_type="module", resource_name="env_scoped_mod", is_system=False)
    db_session.add(mod)
    await db_session.flush()
    # Give 'read' role view access only on prod
    perm = Perm(
        subject_type="role", subject_id="read", resource_id=mod.id, permission_type="view", environment_scope="prod"
    )
    db_session.add(perm)
    await db_session.commit()

    async def _override_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[get_current_user] = make_read_user

    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            resp = await ac.get("/api/v1/auth/my-permissions")
        data = resp.json()
        assert "env_scoped_mod" in data["modules"]
        assert "prod" in data["modules"]["env_scoped_mod"]
        assert "view" in data["modules"]["env_scoped_mod"]["prod"]
        # Should NOT have 'all' or 'nonprod' scope
        assert "all" not in data["modules"]["env_scoped_mod"]
        assert "nonprod" not in data["modules"]["env_scoped_mod"]
    finally:
        app.dependency_overrides.clear()


# ── Phase 3: Team management ──────────────────────────────────────────────────


@pytest.mark.anyio
async def test_create_team(admin_client):
    """Admin can create a team."""
    resp = await admin_client.post(
        "/api/v1/permissions/teams",
        json={"team_name": "dev-team", "description": "Development team"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["team_name"] == "dev-team"
    assert data["description"] == "Development team"
    assert "id" in data


@pytest.mark.anyio
async def test_list_teams(admin_client):
    """Admin can list teams."""
    await admin_client.post("/api/v1/permissions/teams", json={"team_name": "team-a"})
    await admin_client.post("/api/v1/permissions/teams", json={"team_name": "team-b"})
    resp = await admin_client.get("/api/v1/permissions/teams")
    assert resp.status_code == 200
    names = [t["team_name"] for t in resp.json()]
    assert "team-a" in names
    assert "team-b" in names


@pytest.mark.anyio
async def test_add_and_remove_team_member(admin_client):
    """Admin can add/remove members from a team."""
    team_resp = await admin_client.post(
        "/api/v1/permissions/teams",
        json={"team_name": "member-test-team"},
    )
    team_id = team_resp.json()["id"]

    # Add member
    add_resp = await admin_client.post(
        f"/api/v1/permissions/teams/{team_id}/members",
        json={"user_id": "user-xyz", "user_email": "xyz@example.com"},
    )
    assert add_resp.status_code == 200
    assert add_resp.json()["user_id"] == "user-xyz"

    # Verify member in team
    get_resp = await admin_client.get(f"/api/v1/permissions/teams/{team_id}")
    assert get_resp.status_code == 200
    members = get_resp.json()["members"]
    assert any(m["user_id"] == "user-xyz" for m in members)

    # Remove member
    del_resp = await admin_client.delete(f"/api/v1/permissions/teams/{team_id}/members/user-xyz")
    assert del_resp.status_code == 200
    assert del_resp.json()["deleted"] is True


@pytest.mark.anyio
async def test_duplicate_team_member_returns_409(admin_client):
    """Adding the same user to a team twice returns 409."""
    team_resp = await admin_client.post(
        "/api/v1/permissions/teams",
        json={"team_name": "dup-member-team"},
    )
    team_id = team_resp.json()["id"]

    await admin_client.post(
        f"/api/v1/permissions/teams/{team_id}/members",
        json={"user_id": "dup-user"},
    )
    resp = await admin_client.post(
        f"/api/v1/permissions/teams/{team_id}/members",
        json={"user_id": "dup-user"},
    )
    assert resp.status_code == 409


@pytest.mark.anyio
async def test_delete_team(admin_client):
    """Admin can delete a team."""
    team_resp = await admin_client.post(
        "/api/v1/permissions/teams",
        json={"team_name": "deletable-team"},
    )
    team_id = team_resp.json()["id"]

    del_resp = await admin_client.delete(f"/api/v1/permissions/teams/{team_id}")
    assert del_resp.status_code == 200
    assert del_resp.json()["deleted"] is True

    # Verify it's gone
    get_resp = await admin_client.get(f"/api/v1/permissions/teams/{team_id}")
    assert get_resp.status_code == 404


@pytest.mark.anyio
async def test_team_permissions_flow(app, db_session):
    """User in a team inherits team-granted group permissions."""
    from httpx import ASGITransport, AsyncClient

    from app.auth import get_current_user
    from app.core.database import get_db
    from app.models.database import Permission as Perm
    from app.models.database import Resource as Res
    from app.models.database import Team, TeamMembership
    from app.schemas.auth import UserContext, UserRole

    # Create a module resource
    mod = Res(resource_type="module", resource_name="team_perm_mod", is_system=False)
    db_session.add(mod)
    await db_session.flush()

    # Create a team and add the reader user
    team = Team(team_name="ops-team", description="Operations team")
    db_session.add(team)
    await db_session.flush()
    db_session.add(TeamMembership(team_id=team.id, user_id="test-reader", user_email="reader@example.com"))

    # Grant group permission to the team
    perm = Perm(
        subject_type="group",
        subject_id="ops-team",
        resource_id=mod.id,
        permission_type="edit",
        environment_scope="nonprod",
    )
    db_session.add(perm)
    await db_session.commit()

    async def _override_db():
        yield db_session

    async def make_team_user() -> UserContext:
        return UserContext(
            user_id="test-reader",
            object_id="11111111-1111-1111-1111-111111111111",
            display_name="Test Reader",
            email="reader@example.com",
            roles=[UserRole.READ],
            raw_roles=["read"],
            tenant_id="tenant-test",
            allowed_subscriptions=[],
        )

    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[get_current_user] = make_team_user

    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            resp = await ac.get("/api/v1/auth/my-permissions")
        data = resp.json()
        assert "team_perm_mod" in data["modules"]
        # Team grants edit on nonprod
        assert "nonprod" in data["modules"]["team_perm_mod"]
        assert "edit" in data["modules"]["team_perm_mod"]["nonprod"]
        # User's teams are included in response
        assert "ops-team" in data["teams"]
    finally:
        app.dependency_overrides.clear()


# ── Phase 4: Resource sync endpoint ───────────────────────────────────────────


@pytest.mark.anyio
async def test_resource_sync_endpoint(admin_client):
    """Admin can trigger resource sync and get updated list."""
    resp = await admin_client.post("/api/v1/permissions/resources/sync")
    assert resp.status_code == 200
    data = resp.json()
    assert data["synced"] is True
    assert len(data["resources"]) > 0
