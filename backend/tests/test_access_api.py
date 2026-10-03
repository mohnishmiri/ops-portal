"""Access management API: who can grant, request, approve — and go-live."""

from unittest.mock import AsyncMock, patch

import httpx
import pytest
from fastapi import Request
from sqlalchemy import select

from app.auth import get_authenticated_identity, get_current_user
from app.core.access_scope import compute_access_scope, invalidate_access_topology
from app.core.config import settings
from app.models.database import AccessGrant, AdminConfig, AdminSubscription, AuditLog, PortalUser, ProjectApp
from app.schemas.auth import UserRole
from app.services.access_service import AccessService
from app.services.k8s_dashboard_service import K8sDashboardService
from tests.access_helpers import (
    COMMISSIONS_NONPROD,
    SUB,
    add_cluster,
    build_world,
    client_as,
    grant,
    make_project_admin,
    make_user,
    sign_in,
)

pytestmark = pytest.mark.real_access

BOSS = make_user("boss", UserRole.SUPER_ADMIN)
C_ADMIN = make_user("cadmin", UserRole.ADMIN)  # Commissions project admin
B_ADMIN = make_user("badmin", UserRole.ADMIN)  # BDS project admin
DEV = make_user("dev", UserRole.WRITE)
READER = make_user("reader", UserRole.READ)


@pytest.fixture(autouse=True)
def _no_mail():
    with patch("app.api.v1.endpoints.access._notify", new=AsyncMock()) as notify:
        yield notify


@pytest.fixture
async def world(db_session):
    w = await build_world(db_session)
    for u in (BOSS, C_ADMIN, B_ADMIN, DEV, READER):
        await sign_in(db_session, u)
    await make_project_admin(db_session, C_ADMIN, w.commissions)
    await make_project_admin(db_session, B_ADMIN, w.bds)
    return w


# ── Administration ──────────────────────────────────────────────────


async def test_super_admin_onboards_a_project_with_an_app(app, db_session, world):
    db_session.add(
        AdminSubscription(
            subscription_id="55555555-0000-0000-0000-000000000001", subscription_name="ACC-NPRD-77777-NEWAPP"
        )
    )
    await db_session.commit()

    async with client_as(app, db_session, BOSS) as ac:
        project = await ac.post("/api/v1/access/admin/projects", json={"name": "Retail Ops"})
        pid = project.json()["id"]
        app_resp = await ac.post(
            f"/api/v1/access/admin/projects/{pid}/apps", json={"app_code": "77777", "name": "NEWAPP"}
        )

    assert project.status_code == 200 and project.json()["project_key"] == "retail-ops"
    assert app_resp.status_code == 200
    # The matching unplaced subscription was placed into the new app with its tier.
    assert app_resp.json()["placed_subscriptions"] == ["55555555-0000-0000-0000-000000000001"]
    row = (
        await db_session.execute(
            select(AdminSubscription).where(AdminSubscription.subscription_name == "ACC-NPRD-77777-NEWAPP")
        )
    ).scalar_one()
    assert row.tier == "nonprod"


async def test_project_admin_cannot_create_projects_or_move_subscriptions(app, db_session, world):
    async with client_as(app, db_session, C_ADMIN) as ac:
        create = await ac.post("/api/v1/access/admin/projects", json={"name": "Sneaky"})
        place = await ac.put(
            f"/api/v1/access/admin/subscriptions/{SUB['bds_prod']}", json={"app_id": world.attcc, "tier": "nonprod"}
        )
    assert create.status_code == 403
    assert place.status_code == 403


async def test_write_user_cannot_reach_access_admin(app, db_session, world):
    async with client_as(app, db_session, DEV) as ac:
        resp = await ac.get("/api/v1/access/admin/grants")
    assert resp.status_code == 403


async def test_project_admin_grants_within_their_project_only(app, db_session, world):
    body = {"user_ids": ["dev"], "scope_type": "project", "tiers": ["nonprod"], "level": "write"}
    async with client_as(app, db_session, C_ADMIN) as ac:
        own = await ac.post("/api/v1/access/admin/grants", json={**body, "project_id": world.commissions})
        other = await ac.post("/api/v1/access/admin/grants", json={**body, "project_id": world.bds})
        everyone = await ac.post(
            "/api/v1/access/admin/grants",
            json={**body, "user_ids": [], "everyone": True, "project_id": world.commissions},
        )
        listed = await ac.get("/api/v1/access/admin/grants")

    assert own.status_code == 200
    assert other.status_code == 403
    assert everyone.status_code == 403
    assert {g["project_name"] for g in listed.json()} == {"Commissions"}
    scope = await compute_access_scope(db_session, DEV)
    assert scope.writable == COMMISSIONS_NONPROD


async def test_grant_to_a_user_who_never_signed_in_is_refused(app, db_session, world):
    body = {
        "user_ids": ["ghost"],
        "scope_type": "project",
        "project_id": world.commissions,
        "tiers": ["prod"],
        "level": "read",
    }
    async with client_as(app, db_session, BOSS) as ac:
        resp = await ac.post("/api/v1/access/admin/grants", json=body)
    assert resp.status_code == 400


async def test_revoking_takes_effect_on_the_next_request(app, db_session, world):
    g = await grant(db_session, "dev", project_id=world.commissions, tier="nonprod", level="write")
    assert (await compute_access_scope(db_session, DEV)).has_any_access

    async with client_as(app, db_session, C_ADMIN) as ac:
        resp = await ac.delete(f"/api/v1/access/admin/grants/{g.id}")

    assert resp.status_code == 200
    assert not (await compute_access_scope(db_session, DEV)).has_any_access
    audit = (await db_session.execute(select(AuditLog.action))).scalars().all()
    assert "access_grant_revoke" in audit


async def test_only_admins_with_entra_admin_role_can_be_appointed(app, db_session, world):
    async with client_as(app, db_session, BOSS) as ac:
        resp = await ac.post(f"/api/v1/access/admin/projects/{world.bds}/admins", json={"user_id": "dev"})
    assert resp.status_code == 400
    assert "Admin role" in resp.json()["detail"]


# ── Requests and approvals ──────────────────────────────────────────


async def _submit(app, db_session, user, items, justification="Need it for the release"):
    async with client_as(app, db_session, user) as ac:
        return await ac.post("/api/v1/access/requests", json={"justification": justification, "items": items})


async def test_request_then_project_admin_approves(app, db_session, world, _no_mail):
    items = [
        {"scope_type": "project", "project_id": world.commissions, "tier": "nonprod", "level": "write"},
        {"scope_type": "project", "project_id": world.commissions, "tier": "prod", "level": "write"},
    ]
    submitted = await _submit(app, db_session, DEV, items)
    assert submitted.status_code == 200
    req = submitted.json()
    nonprod_item, prod_item = req["items"]

    async with client_as(app, db_session, C_ADMIN) as ac:
        queue = await ac.get("/api/v1/access/admin/requests")
        approve = await ac.post(
            f"/api/v1/access/admin/requests/{req['id']}/items/{nonprod_item['id']}/decision",
            json={"decision": "approve"},
        )
        reject = await ac.post(
            f"/api/v1/access/admin/requests/{req['id']}/items/{prod_item['id']}/decision",
            json={"decision": "reject", "comment": "Prod is ops only"},
        )

    assert [r["id"] for r in queue.json()] == [req["id"]]
    assert all(i["can_decide"] for i in queue.json()[0]["items"])
    assert approve.status_code == 200
    assert reject.json()["status"] == "partially_approved"
    scope = await compute_access_scope(db_session, DEV)
    assert scope.writable == COMMISSIONS_NONPROD
    # Approvers were told about the request, the requester about each decision.
    assert _no_mail.await_count == 3


async def test_admin_of_another_project_cannot_decide(app, db_session, world):
    req = (
        await _submit(
            app, db_session, DEV, [{"scope_type": "app", "app_id": world.dws, "tier": "nonprod", "level": "read"}]
        )
    ).json()
    async with client_as(app, db_session, B_ADMIN) as ac:
        queue = await ac.get("/api/v1/access/admin/requests")
        decide = await ac.post(
            f"/api/v1/access/admin/requests/{req['id']}/items/{req['items'][0]['id']}/decision",
            json={"decision": "approve"},
        )
    assert queue.json() == []
    assert decide.status_code == 403


async def test_super_admin_can_decide_any_project(app, db_session, world):
    req = (
        await _submit(
            app, db_session, DEV, [{"scope_type": "project", "project_id": world.bds, "tier": "prod", "level": "read"}]
        )
    ).json()
    async with client_as(app, db_session, BOSS) as ac:
        resp = await ac.post(
            f"/api/v1/access/admin/requests/{req['id']}/items/{req['items'][0]['id']}/decision",
            json={"decision": "approve"},
        )
    assert resp.json()["status"] == "approved"


async def test_nobody_approves_their_own_request(app, db_session, world):
    req = (
        await _submit(
            app,
            db_session,
            C_ADMIN,
            [{"scope_type": "project", "project_id": world.bds, "tier": "prod", "level": "write"}],
        )
    ).json()
    # Make the requester an admin of the project they asked for, then try.
    await make_project_admin(db_session, C_ADMIN, world.bds)
    async with client_as(app, db_session, C_ADMIN) as ac:
        resp = await ac.post(
            f"/api/v1/access/admin/requests/{req['id']}/items/{req['items'][0]['id']}/decision",
            json={"decision": "approve"},
        )
    assert resp.status_code == 403


async def test_read_role_user_cannot_request_write(app, db_session, world):
    resp = await _submit(
        app,
        db_session,
        READER,
        [{"scope_type": "project", "project_id": world.commissions, "tier": "nonprod", "level": "write"}],
    )
    assert resp.status_code == 400
    assert "read-only" in resp.json()["detail"]


async def test_approver_cannot_raise_the_requested_level(app, db_session, world):
    req = (
        await _submit(
            app, db_session, DEV, [{"scope_type": "app", "app_id": world.attcc, "tier": "prod", "level": "read"}]
        )
    ).json()
    async with client_as(app, db_session, C_ADMIN) as ac:
        resp = await ac.post(
            f"/api/v1/access/admin/requests/{req['id']}/items/{req['items'][0]['id']}/decision",
            json={"decision": "approve", "level": "write"},
        )
    assert resp.status_code == 400


async def test_duplicate_pending_request_is_refused_and_cancel_works(app, db_session, world):
    item = [{"scope_type": "app", "app_id": world.attcc, "tier": "nonprod", "level": "read"}]
    first = (await _submit(app, db_session, DEV, item)).json()
    dup = await _submit(app, db_session, DEV, item)
    async with client_as(app, db_session, DEV) as ac:
        cancel = await ac.post(f"/api/v1/access/requests/{first['id']}/cancel")
        mine = await ac.get("/api/v1/access/requests/mine")
    assert dup.status_code == 400
    assert cancel.json()["status"] == "cancelled"
    assert mine.json()[0]["status"] == "cancelled"


async def test_approving_read_never_downgrades_existing_write(app, db_session, world):
    await grant(db_session, "dev", project_id=world.commissions, tier="nonprod", level="write")
    req = (
        await _submit(
            app,
            db_session,
            DEV,
            [{"scope_type": "project", "project_id": world.commissions, "tier": "nonprod", "level": "read"}],
        )
    ).json()
    async with client_as(app, db_session, C_ADMIN) as ac:
        await ac.post(
            f"/api/v1/access/admin/requests/{req['id']}/items/{req['items'][0]['id']}/decision",
            json={"decision": "approve"},
        )
    levels = (
        (await db_session.execute(select(AccessGrant.level).where(AccessGrant.subject_id == "dev"))).scalars().all()
    )
    assert levels == ["write"]


async def test_catalog_and_my_access(app, db_session, world):
    await grant(db_session, "dev", project_id=world.commissions, tier="nonprod", level="write")
    async with client_as(app, db_session, DEV) as ac:
        catalog = await ac.get("/api/v1/access/catalog")
        me = await ac.get("/api/v1/access/me")
    names = {p["name"]: [a["name"] for a in p["apps"]] for p in catalog.json()}
    assert names == {"BDS": ["BDSAPP"], "Commissions": ["ATTCC", "DWS"]}
    assert me.json()["has_subscription_access"] is True
    assert me.json()["writable_count"] == 2
    assert me.json()["grants"][0]["subscription_count"] == 2


# ── Go-live bootstrap ───────────────────────────────────────────────


async def test_bootstrap_places_every_subscription_and_keeps_current_access(db_session):
    for sid, name in [
        (SUB["attcc_prod"], "ACC-PROD-31599-ATTCC"),
        (SUB["attcc_nprd"], "ACC-NPRD-31599-ATTCC"),
        (SUB["dws_nprd"], "ACC-NPRD-17805-DWS"),
        (SUB["unplaced"], "Legacy Shared"),
    ]:
        db_session.add(AdminSubscription(subscription_id=sid, subscription_name=name))
    await db_session.commit()

    summary = await AccessService(db_session).bootstrap()

    assert summary["apps"] == {"31599": 2, "17805": 1, "UNCLASSIFIED": 1}
    apps = {a.app_code: a.name for a in (await db_session.execute(select(ProjectApp))).scalars()}
    assert apps == {"31599": "ATTCC", "17805": "DWS", "UNCLASSIFIED": "Unclassified"}
    invalidate_access_topology()
    # Everyone keeps exactly today's access: write, capped by their Entra role.
    writer = await compute_access_scope(db_session, make_user("anyone", UserRole.WRITE))
    reader = await compute_access_scope(db_session, make_user("viewer", UserRole.READ))
    assert writer.writable == {SUB["attcc_prod"], SUB["attcc_nprd"], SUB["dws_nprd"], SUB["unplaced"]}
    assert reader.readable == writer.writable and reader.writable == frozenset()

    # Runs once: a second start changes nothing, even after the grant is removed.
    await db_session.execute(AccessGrant.__table__.delete())
    await db_session.commit()
    assert await AccessService(db_session).bootstrap() is None
    assert (await db_session.execute(select(AccessGrant))).first() is None
    assert (await db_session.execute(select(AdminConfig.config_key))).scalars().all() == [
        "access_model_bootstrapped_at"
    ]


async def test_bootstrap_skips_when_projects_already_exist(db_session):
    await build_world(db_session)
    assert await AccessService(db_session).bootstrap() is None
    assert (await db_session.execute(select(AccessGrant))).first() is None


async def test_discovered_subscription_is_placed_by_app_code(db_session):
    w = await build_world(db_session)
    row = AdminSubscription(
        subscription_id="66666666-0000-0000-0000-000000000001", subscription_name="ACC-NPRD-17805-DWS-2"
    )
    db_session.add(row)
    placed = await AccessService(db_session).auto_place([row])
    assert placed == [row.subscription_id]
    assert (row.app_id, row.tier) == (w.dws, "nonprod")


# ── Session ─────────────────────────────────────────────────────────


async def test_session_records_the_user_and_reports_access(app, db_session, world):
    await grant(db_session, "dev", project_id=world.commissions, tier="nonprod", level="write")
    async with client_as(app, db_session, DEV, {get_authenticated_identity: lambda: DEV}) as ac:
        resp = await ac.get("/api/v1/auth/session")
    body = resp.json()
    assert body["is_super_admin"] is False
    assert body["access"]["has_subscription_access"] is True
    assert body["access"]["writable_count"] == 2
    assert (await db_session.get(PortalUser, "dev")).roles == "write"


# ── K8s Dashboard ───────────────────────────────────────────────────


@pytest.fixture
def strict_auth(monkeypatch):
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    monkeypatch.setattr(settings, "DEV_AUTH_BYPASS", False)
    monkeypatch.setattr(settings, "K8S_DASHBOARD_SESSION_SECRET", "test-dashboard-session-secret")


@pytest.fixture
def monitored_all(monkeypatch):
    async def _monitored():
        return list(SUB.values())

    monkeypatch.setattr("app.core.subscription_scope.get_monitored_subscription_ids", _monitored)


async def test_dashboard_follows_cluster_subscription(app, db_session, world, strict_auth, monitored_all):
    await add_cluster(db_session, "attcc-prod-aks", SUB["attcc_prod"])
    await add_cluster(db_session, "attcc-dev-aks", SUB["attcc_nprd"])
    await grant(db_session, "dev", project_id=world.commissions, tier="nonprod", level="write")

    html = httpx.Response(200, content=b"<html/>", headers={"content-type": "text/html"})
    with patch.object(K8sDashboardService, "proxy_request", new_callable=AsyncMock, return_value=html):
        async with client_as(app, db_session, DEV) as ac:
            envs = await ac.get("/api/v1/aks/dashboard/environments")
            prod = await ac.post("/api/v1/aks/dashboard/prod/launch")
            dev = await ac.post("/api/v1/aks/dashboard/dev/launch")

    assert {e["env_key"] for e in envs.json()} == {"dev"}
    assert prod.status_code == 403
    assert dev.status_code == 200 and dev.json()["read_only"] is False


async def test_dashboard_session_is_read_only_with_read_grant(app, db_session, world, strict_auth, monitored_all):
    await add_cluster(db_session, "attcc-prod-aks", SUB["attcc_prod"])
    await grant(db_session, "dev", project_id=world.commissions, tier="prod", level="read")
    async with client_as(app, db_session, DEV) as ac:
        resp = await ac.post("/api/v1/aks/dashboard/prod/launch")
    assert resp.status_code == 200 and resp.json()["read_only"] is True


async def test_dashboard_proxy_session_works_for_a_restricted_user(app, db_session, world, strict_auth, monitored_all):
    """The browser session's synthetic user has no grants; launch already checked access."""
    await add_cluster(db_session, "attcc-dev-aks", SUB["attcc_nprd"])
    await grant(db_session, "dev", project_id=world.commissions, tier="nonprod", level="write")

    def _user(request: Request):
        # As in production: the signed launch/proxy URLs carry no bearer token.
        path = request.url.path
        return None if "/launch/" in path or "/proxy" in path else DEV

    html = httpx.Response(200, content=b"<html/>", headers={"content-type": "text/html"})
    with patch.object(K8sDashboardService, "proxy_request", new_callable=AsyncMock, return_value=html):
        async with client_as(app, db_session, DEV, {get_current_user: _user}) as ac:
            launch = await ac.post("/api/v1/aks/dashboard/dev/launch")
            exchange = await ac.get(launch.json()["proxy_url"], follow_redirects=False)
            ac.cookies.set("k8s_dash_session", exchange.cookies.get("k8s_dash_session"))
            viewed = await ac.get("/api/v1/aks/dashboard/dev/proxy/")

    assert launch.status_code == 200
    assert viewed.status_code == 200
