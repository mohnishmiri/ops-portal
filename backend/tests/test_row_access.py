"""Rows addressed by database ID are checked against the row's subscription.

``/schedule/{id}`` or ``/configs/{id}`` names no subscription, so the request
check cannot see it; the services check the stored row instead.
"""

import pytest
from fastapi import HTTPException
from sqlalchemy import select, text

from app.core.access_scope import AccessScope, bind_access_scope
from app.models.database import EnvironmentSchedule
from app.services.environment_scaling_service import EnvironmentScalingService
from app.services.infra_alert_service import InfraAlertService
from app.services.keyvault_sync_service import KeyVaultSyncService
from tests.access_helpers import SUB, cluster_id

pytestmark = pytest.mark.real_access

# Non-Prod write, Prod read — the dev-team shape.
DEV_SCOPE = AccessScope(
    readable=frozenset({SUB["attcc_nprd"], SUB["attcc_prod"]}),
    writable=frozenset({SUB["attcc_nprd"]}),
)


@pytest.fixture
def as_dev():
    token = bind_access_scope(DEV_SCOPE)
    yield
    from app.core.access_scope import _current_scope

    _current_scope.reset(token)


# ── Environment schedules ───────────────────────────────────────────


@pytest.fixture
async def schedules(db_engine, db_session):
    async with db_engine.begin() as conn:
        await conn.run_sync(lambda c: EnvironmentSchedule.__table__.create(c, checkfirst=True))
    rows = {}
    for key, sub in (("nprd", SUB["attcc_nprd"]), ("prod", SUB["attcc_prod"]), ("bds", SUB["bds_prod"])):
        row = EnvironmentSchedule(
            job_name=f"job-{key}",
            cluster_id=cluster_id(sub),
            namespace="apps",
            operation="scale_down",
            schedule_type="daily",
            created_by="someone",
        )
        db_session.add(row)
        rows[key] = row
    await db_session.commit()
    return {k: r.id for k, r in rows.items()}


async def test_schedule_list_shows_only_readable_clusters(db_session, schedules, as_dev):
    names = {s["job_name"] for s in await EnvironmentScalingService(db_session).list_schedules()}
    assert names == {"job-nprd", "job-prod"}


async def test_schedule_changes_need_write_on_its_cluster(db_session, schedules, as_dev):
    svc = EnvironmentScalingService(db_session)
    await svc.update_schedule(schedules["nprd"], {"replica_count": 2})

    for call in (
        lambda: svc.update_schedule(schedules["prod"], {"replica_count": 2}),
        lambda: svc.delete_schedule(schedules["prod"]),
        lambda: svc.execute_scheduled_job(schedules["prod"]),
        lambda: svc.get_schedule(schedules["bds"]),
    ):
        with pytest.raises(HTTPException) as exc:
            await call()
        assert exc.value.status_code == 403

    remaining = (await db_session.execute(select(EnvironmentSchedule.id))).scalars().all()
    assert set(remaining) == set(schedules.values())


async def test_background_scheduler_is_not_checked(db_session, schedules):
    """No request scope bound: the scheduler acts with the portal's authority."""
    assert await EnvironmentScalingService(db_session).delete_schedule(schedules["prod"]) is True


# ── Infra alert configs ─────────────────────────────────────────────

_VM_CONFIGS_DDL = "CREATE TABLE vm_threshold_alert_configs (id INTEGER PRIMARY KEY, subscription_id VARCHAR(50))"
_VM_ALERTS_DDL = "CREATE TABLE vm_threshold_alerts (id INTEGER PRIMARY KEY, config_id INTEGER)"


@pytest.fixture
async def vm_configs(db_session):
    await db_session.execute(text(_VM_CONFIGS_DDL))
    await db_session.execute(text(_VM_ALERTS_DDL))
    await db_session.execute(
        text("INSERT INTO vm_threshold_alert_configs (id, subscription_id) VALUES (1, :n), (2, :p)"),
        {"n": SUB["attcc_nprd"], "p": SUB["attcc_prod"]},
    )
    await db_session.execute(text("INSERT INTO vm_threshold_alerts (id, config_id) VALUES (10, 1), (20, 2)"))
    await db_session.commit()


async def test_alert_config_delete_checks_the_config_subscription(db_session, vm_configs, as_dev):
    svc = InfraAlertService(db_session)
    assert (await svc.delete_vm_threshold_config(1))["status"] == "deleted"
    with pytest.raises(HTTPException) as exc:
        await svc.delete_vm_threshold_config(2)
    assert exc.value.status_code == 403


async def test_alert_acknowledge_checks_its_config_subscription(db_session, vm_configs, as_dev):
    with pytest.raises(HTTPException) as exc:
        await InfraAlertService(db_session).acknowledge_vm_alert(20, acknowledged_by="dev@example.com")
    assert exc.value.status_code == 403


# ── Key Vault inventory ─────────────────────────────────────────────


async def test_vault_list_from_db_is_scoped(db_session, as_dev):
    await db_session.execute(
        text(
            "CREATE TABLE kv_vaults (id INTEGER PRIMARY KEY, vault_uri TEXT, name TEXT, resource_id TEXT, "
            "location TEXT, resource_group TEXT, subscription_id TEXT, sku TEXT, tenant_id TEXT, "
            "soft_delete_enabled BOOLEAN, purge_protection_enabled BOOLEAN, rbac_enabled BOOLEAN, "
            "provisioning_state TEXT, tags TEXT, secrets_count INTEGER, keys_count INTEGER, "
            "certificates_count INTEGER, synced_at DATETIME, created_at DATETIME)"
        )
    )
    for name, sub in (("kv-nprd", SUB["attcc_nprd"]), ("kv-bds", SUB["bds_prod"]), ("kv-orphan", None)):
        await db_session.execute(
            text("INSERT INTO kv_vaults (vault_uri, name, subscription_id) VALUES (:u, :n, :s)"),
            {"u": f"https://{name}.vault.azure.net/", "n": name, "s": sub},
        )
    await db_session.commit()

    vaults = await KeyVaultSyncService(db_session).get_vaults_from_db()

    assert [v["name"] for v in vaults] == ["kv-nprd"]


# ── AKS live-watch WebSocket ────────────────────────────────────────


async def test_live_watch_only_subscribes_to_readable_clusters(db_session, monkeypatch):
    from app.models.auth import UserRole
    from app.services.aks_live_sync_hub import AKSLiveSyncHub
    from tests.access_helpers import build_world, grant, make_user

    w = await build_world(db_session)
    await grant(db_session, "dev", project_id=w.commissions, tier="nonprod", level="write")

    async def _session():
        yield db_session

    monkeypatch.setattr("app.services.aks_live_sync_hub.get_db_session", _session)
    dev = make_user("dev", UserRole.WRITE)

    assert await AKSLiveSyncHub._may_watch(dev, cluster_id(SUB["attcc_nprd"])) is True
    assert await AKSLiveSyncHub._may_watch(dev, cluster_id(SUB["attcc_prod"])) is False
    assert await AKSLiveSyncHub._may_watch(dev, "not-an-arm-id") is False
