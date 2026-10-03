"""Shared fixtures for project / app / subscription access tests.

Builds two projects the way the user described them:

    Commissions → ATTCC (31599), DWS (17805)  — each with a Prod and a Non-Prod subscription
    BDS         → BDSAPP (55555)               — Prod and Non-Prod

plus one subscription that has not been placed in any app yet.
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from app.auth import get_current_user
from app.core.database import get_db
from app.models.database import AccessGrant, AdminSubscription, PortalUser, Project, ProjectAdmin, ProjectApp
from app.schemas.auth import UserContext, UserRole

SUB = {
    "attcc_prod": "11111111-0000-0000-0000-000000000001",
    "attcc_nprd": "11111111-0000-0000-0000-000000000002",
    "dws_prod": "22222222-0000-0000-0000-000000000001",
    "dws_nprd": "22222222-0000-0000-0000-000000000002",
    "bds_prod": "33333333-0000-0000-0000-000000000001",
    "bds_nprd": "33333333-0000-0000-0000-000000000002",
    "unplaced": "44444444-0000-0000-0000-000000000001",
}

COMMISSIONS_NONPROD = {SUB["attcc_nprd"], SUB["dws_nprd"]}
COMMISSIONS_PROD = {SUB["attcc_prod"], SUB["dws_prod"]}
COMMISSIONS_ALL = COMMISSIONS_NONPROD | COMMISSIONS_PROD
BDS_ALL = {SUB["bds_prod"], SUB["bds_nprd"]}


def cluster_id(sub: str, name: str = "aks-1") -> str:
    return f"/subscriptions/{sub}/resourceGroups/rg/providers/Microsoft.ContainerService/managedClusters/{name}"


def make_user(user_id: str, *roles: UserRole, email: str | None = None) -> UserContext:
    return UserContext(
        user_id=user_id,
        object_id=f"oid-{user_id}",
        display_name=user_id.replace("-", " ").title(),
        email=email or f"{user_id}@example.com",
        roles=list(roles),
        raw_roles=[r.value for r in roles],
        tenant_id="tenant-test",
    )


class World:
    """IDs of the objects created by :func:`build_world`."""

    commissions: int
    bds: int
    attcc: int
    dws: int
    bdsapp: int


async def build_world(db) -> World:
    world = World()
    commissions = Project(project_key="commissions", name="Commissions")
    bds = Project(project_key="bds", name="BDS")
    db.add_all([commissions, bds])
    await db.flush()
    attcc = ProjectApp(project_id=commissions.id, app_code="31599", name="ATTCC")
    dws = ProjectApp(project_id=commissions.id, app_code="17805", name="DWS")
    bdsapp = ProjectApp(project_id=bds.id, app_code="55555", name="BDSAPP")
    db.add_all([attcc, dws, bdsapp])
    await db.flush()
    placements = [
        (SUB["attcc_prod"], "ACC-PROD-31599-ATTCC", attcc.id, "prod"),
        (SUB["attcc_nprd"], "ACC-NPRD-31599-ATTCC", attcc.id, "nonprod"),
        (SUB["dws_prod"], "ACC-PROD-17805-DWS", dws.id, "prod"),
        (SUB["dws_nprd"], "ACC-NPRD-17805-DWS", dws.id, "nonprod"),
        (SUB["bds_prod"], "ACC-PROD-55555-BDSAPP", bdsapp.id, "prod"),
        (SUB["bds_nprd"], "ACC-NPRD-55555-BDSAPP", bdsapp.id, "nonprod"),
        (SUB["unplaced"], "Some Shared Sub", None, None),
    ]
    for sid, name, app_id, tier in placements:
        db.add(AdminSubscription(subscription_id=sid, subscription_name=name, app_id=app_id, tier=tier))
    await db.commit()
    world.commissions, world.bds = commissions.id, bds.id
    world.attcc, world.dws, world.bdsapp = attcc.id, dws.id, bdsapp.id
    return world


async def grant(db, user_id: str, *, project_id: int, scope_type: str = "project", **kw) -> AccessGrant:
    row = AccessGrant(
        subject_type="user",
        subject_id=user_id,
        subject_email=f"{user_id}@example.com",
        scope_type=scope_type,
        project_id=project_id,
        app_id=kw.get("app_id"),
        subscription_id=kw.get("subscription_id"),
        tier=kw.get("tier"),
        level=kw.get("level", "read"),
    )
    db.add(row)
    await db.commit()
    return row


async def make_project_admin(db, user: UserContext, project_id: int) -> None:
    db.add(ProjectAdmin(project_id=project_id, user_id=user.user_id, user_email=user.email))
    await db.commit()


async def sign_in(db, user: UserContext) -> None:
    """Record the user as having signed in (admins can only pick these)."""
    db.add(
        PortalUser(
            user_id=user.user_id,
            email=user.email,
            display_name=user.display_name,
            roles=",".join(r.value for r in user.roles),
        )
    )
    await db.commit()


KV_VAULTS_SQLITE_DDL = """
CREATE TABLE IF NOT EXISTS kv_vaults (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    vault_uri       VARCHAR(500) NOT NULL,
    name            VARCHAR(255) NOT NULL,
    subscription_id VARCHAR(100)
)
"""

INVENTORY_SQLITE_DDL = """
CREATE TABLE IF NOT EXISTS azure_resource_inventory (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    resource_id     VARCHAR(1000) NOT NULL,
    name            VARCHAR(255) NOT NULL,
    resource_type   VARCHAR(100) NOT NULL,
    resource_group  VARCHAR(255) NOT NULL DEFAULT 'rg',
    subscription_id VARCHAR(50) NOT NULL,
    last_sync       DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
)
"""


async def add_vault(db, name: str, sub: str) -> None:
    await db.execute(text(KV_VAULTS_SQLITE_DDL))
    await db.execute(
        text("INSERT INTO kv_vaults (vault_uri, name, subscription_id) VALUES (:u, :n, :s)"),
        {"u": f"https://{name}.vault.azure.net/", "n": name, "s": sub},
    )
    await db.commit()


async def add_cluster(db, name: str, sub: str) -> None:
    await db.execute(text(INVENTORY_SQLITE_DDL))
    await db.execute(
        text(
            "INSERT INTO azure_resource_inventory (resource_id, name, resource_type, subscription_id) "
            "VALUES (:r, :n, 'aks_cluster', :s)"
        ),
        {"r": cluster_id(sub, name), "n": name, "s": sub},
    )
    await db.commit()


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
