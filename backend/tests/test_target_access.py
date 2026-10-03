"""A request naming a subscription outside the user's scope is refused.

The subscription scope narrows lists; these tests cover the other half — a
cluster ID, Key Vault, or subscription ID named directly in a request.
"""

import pytest
from fastapi import APIRouter, Depends, FastAPI

from app.core.subscription_scope import resolve_effective_subscription_ids
from app.core.target_access import enforce_target_access
from app.schemas.auth import UserRole
from tests.access_helpers import (
    SUB,
    add_vault,
    build_world,
    client_as,
    cluster_id,
    grant,
    make_user,
)

pytestmark = pytest.mark.real_access

DEV = make_user("dev", UserRole.WRITE)


def _probe_app() -> FastAPI:
    """Minimal routes shaped like the portal's, behind the real dependency."""
    app = FastAPI()
    router = APIRouter(prefix="/api/v1", dependencies=[Depends(enforce_target_access)])

    @router.get("/aks/pods")
    async def list_pods(cluster_id: str):
        return {"ok": True}

    @router.post("/aks/deployments/scale")
    async def scale(body: dict):
        return {"ok": True}

    @router.post("/costs/query")  # read-only mutation (route_policy)
    async def cost_query(body: dict):
        return {"ok": True}

    @router.get("/keyvault/secrets")
    async def secrets(vault_uri: str):
        return {"ok": True}

    @router.delete("/keyvault/vaults/{vault_name}/secrets/{name}")
    async def delete_secret(vault_name: str, name: str):
        return {"ok": True}

    @router.post("/access/requests")  # exempt: authorizes its own targets
    async def request_access(body: dict):
        return {"ok": True}

    app.include_router(router)
    return app


@pytest.fixture
async def dev_nonprod(db_session):
    w = await build_world(db_session)
    await grant(db_session, "dev", project_id=w.commissions, tier="nonprod", level="write")
    await grant(db_session, "dev", project_id=w.commissions, tier="prod", level="read")
    return w


async def test_cluster_in_query_needs_read(db_session, dev_nonprod):
    async with client_as(_probe_app(), db_session, DEV) as ac:
        ok = await ac.get("/api/v1/aks/pods", params={"cluster_id": cluster_id(SUB["attcc_prod"])})
        other_project = await ac.get("/api/v1/aks/pods", params={"cluster_id": cluster_id(SUB["bds_nprd"])})
    assert ok.status_code == 200
    assert other_project.status_code == 403


async def test_change_needs_write_on_the_target(db_session, dev_nonprod):
    async with client_as(_probe_app(), db_session, DEV) as ac:
        nonprod = await ac.post("/api/v1/aks/deployments/scale", json={"cluster_id": cluster_id(SUB["dws_nprd"])})
        prod = await ac.post("/api/v1/aks/deployments/scale", json={"cluster_id": cluster_id(SUB["dws_prod"])})
    assert nonprod.status_code == 200
    assert prod.status_code == 403
    assert "change" in prod.json()["detail"]


async def test_targets_nested_anywhere_in_the_body_are_checked(db_session, dev_nonprod):
    body = {"items": [{"target": {"resourceId": cluster_id(SUB["dws_nprd"])}}, {"sub_id": SUB["attcc_prod"]}]}
    async with client_as(_probe_app(), db_session, DEV) as ac:
        resp = await ac.post("/api/v1/aks/deployments/scale", json=body)
    assert resp.status_code == 403


async def test_malformed_subscription_id_is_refused_not_ignored(db_session, dev_nonprod):
    async with client_as(_probe_app(), db_session, DEV) as ac:
        resp = await ac.post("/api/v1/aks/deployments/scale", json={"subscription_id": "not-a-guid"})
    assert resp.status_code == 403


async def test_read_only_mutation_needs_only_read(db_session, dev_nonprod):
    async with client_as(_probe_app(), db_session, DEV) as ac:
        resp = await ac.post("/api/v1/costs/query", json={"subscription_ids": [SUB["attcc_prod"]]})
    assert resp.status_code == 200


async def test_key_vault_resolved_through_inventory(db_session, dev_nonprod):
    await add_vault(db_session, "kv-attcc-prod", SUB["attcc_prod"])
    await add_vault(db_session, "kv-attcc-nprd", SUB["attcc_nprd"])
    async with client_as(_probe_app(), db_session, DEV) as ac:
        view_prod = await ac.get(
            "/api/v1/keyvault/secrets", params={"vault_uri": "https://kv-attcc-prod.vault.azure.net/"}
        )
        delete_prod = await ac.delete("/api/v1/keyvault/vaults/kv-attcc-prod/secrets/s1")
        delete_nprd = await ac.delete("/api/v1/keyvault/vaults/KV-ATTCC-NPRD/secrets/s1")
    assert view_prod.status_code == 200
    assert delete_prod.status_code == 403
    assert delete_nprd.status_code == 200


async def test_unknown_vault_is_refused(db_session, dev_nonprod):
    await add_vault(db_session, "kv-attcc-nprd", SUB["attcc_nprd"])
    async with client_as(_probe_app(), db_session, DEV) as ac:
        resp = await ac.get("/api/v1/keyvault/secrets", params={"vault_uri": "https://kv-mystery.vault.azure.net/"})
    assert resp.status_code == 403
    assert "inventory" in resp.json()["detail"]


async def test_access_requests_are_exempt(db_session, dev_nonprod):
    async with client_as(_probe_app(), db_session, DEV) as ac:
        resp = await ac.post("/api/v1/access/requests", json={"subscription_id": SUB["bds_prod"]})
    assert resp.status_code == 200


async def test_super_admin_is_not_checked(db_session, dev_nonprod):
    boss = make_user("boss", UserRole.SUPER_ADMIN)
    async with client_as(_probe_app(), db_session, boss) as ac:
        resp = await ac.post("/api/v1/aks/deployments/scale", json={"cluster_id": cluster_id(SUB["bds_prod"])})
    assert resp.status_code == 200


# ── Through the real application ────────────────────────────────────


@pytest.fixture
def monitored_all(monkeypatch):
    async def _monitored():
        return list(SUB.values())

    monkeypatch.setattr("app.core.subscription_scope.get_monitored_subscription_ids", _monitored)


@pytest.mark.parametrize(("sub_key", "status"), [("dws_nprd", 200), ("dws_prod", 403), ("bds_nprd", 403)])
async def test_cost_cleanup_respects_subscription_write(
    app, db_session, dev_nonprod, monitored_all, monkeypatch, sub_key, status
):
    deleted = []

    class FakeAzureResourceService:
        def __init__(self, db_session=None):
            pass

        async def delete_unattached_disk(self, subscription_id, resource_group, disk_name):
            deleted.append(subscription_id)
            return {"deleted": disk_name}

    monkeypatch.setattr("app.services.azure_resource_service.AzureResourceService", FakeAzureResourceService)
    body = {"subscription_id": SUB[sub_key], "resource_group": "rg", "disk_name": "disk-01"}

    async with client_as(app, db_session, DEV) as ac:
        resp = await ac.post("/api/v1/optimize/cleanup/disks", json=body)

    assert resp.status_code == status
    assert deleted == ([SUB[sub_key]] if status == 200 else [])


async def test_user_without_grants_is_refused_before_any_service_runs(app, db_session, monitored_all):
    await build_world(db_session)
    async with client_as(app, db_session, make_user("newbie", UserRole.WRITE)) as ac:
        resp = await ac.get("/api/v1/aks/clusters/cached")
    assert resp.status_code == 403
    assert "Request access" in resp.json()["detail"]


async def test_picker_lists_only_granted_subscriptions_grouped(
    app, db_session, dev_nonprod, monitored_all, monkeypatch
):
    monkeypatch.setattr(
        "app.services.user_preference_service.get_monitored_subscription_ids", _async(list(SUB.values()))
    )
    async with client_as(app, db_session, DEV) as ac:
        resp = await ac.get("/api/v1/auth/available-subscriptions")
    assert resp.status_code == 200
    subs = {s["subscription_id"]: s for s in resp.json()["subscriptions"]}
    assert set(subs) == {SUB["attcc_prod"], SUB["attcc_nprd"], SUB["dws_prod"], SUB["dws_nprd"]}
    assert subs[SUB["dws_nprd"]]["project_name"] == "Commissions"
    assert subs[SUB["dws_nprd"]]["app_name"] == "DWS"
    assert subs[SUB["dws_nprd"]]["tier"] == "nonprod"


def _async(value):
    async def _f():
        return value

    return _f


# ── Scope resolution: explicit vs saved selection ───────────────────


async def test_explicit_selection_outside_scope_is_refused(monitored_all):
    with pytest.raises(Exception) as exc:
        await resolve_effective_subscription_ids(
            allowed_subscriptions=frozenset({SUB["dws_nprd"]}),
            selected_subscription_ids=[SUB["dws_prod"]],
        )
    assert exc.value.status_code == 403


async def test_stale_saved_selection_falls_back_to_everything_allowed(monitored_all):
    """Revoking access must not leave a user stuck behind an old picker choice."""
    result = await resolve_effective_subscription_ids(
        allowed_subscriptions=frozenset({SUB["dws_nprd"]}),
        selected_subscription_ids=[SUB["dws_prod"]],
        strict_selection=False,
    )
    assert result == [SUB["dws_nprd"]]


async def test_empty_allowed_set_means_nothing_not_everything(monitored_all):
    assert await resolve_effective_subscription_ids(allowed_subscriptions=frozenset()) == []


async def test_stale_picker_filter_does_not_lock_the_user_out(app, db_session, dev_nonprod, monitored_all, monkeypatch):
    """After a revocation the UI may still send the old picker selection."""
    monkeypatch.setattr(
        "app.services.user_preference_service.get_monitored_subscription_ids", _async(list(SUB.values()))
    )
    async with client_as(app, db_session, DEV) as ac:
        resp = await ac.get("/api/v1/auth/available-subscriptions", params={"subscription_ids": [SUB["bds_prod"]]})
        mine = await ac.get("/api/v1/access/me", params={"subscription_ids": [SUB["bds_prod"]]})
    assert resp.status_code == 200
    assert SUB["bds_prod"] not in {s["subscription_id"] for s in resp.json()["subscriptions"]}
    assert mine.status_code == 200
