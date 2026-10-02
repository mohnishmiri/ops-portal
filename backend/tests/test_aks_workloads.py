"""
Tests for StatefulSet / DaemonSet management and AKV → AKS (akv2k8s) secret sync status.
"""

from contextlib import asynccontextmanager
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from httpx import ASGITransport, AsyncClient
from kubernetes.client.rest import ApiException

from app.api.v1.endpoints.aks_operations import _get_service
from app.auth import get_current_user
from app.core.database import get_db
from app.models.database import Permission, Resource
from app.schemas.auth import UserContext, UserRole
from app.services import aks_akvs_operations as akvs
from app.services import aks_workload_operations as wl
from app.services.aks_operations_service import AKSOperationsService

CLUSTER_ID = "/subscriptions/s1/resourceGroups/rg1/providers/Microsoft.ContainerService/managedClusters/aks-prod-01"
CREATED = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)


# ── Builders ──────────────────────────────────────────────────────────


def _container(name="app", image="repo/app:1"):
    return SimpleNamespace(name=name, image=image, resources=None)


def _template(containers=None):
    return SimpleNamespace(
        spec=SimpleNamespace(
            containers=containers or [_container()],
            node_selector=None,
            service_account_name="default",
            tolerations=None,
        )
    )


def _meta(name, namespace="data", uid="uid-1", generation=1):
    return SimpleNamespace(
        name=name,
        namespace=namespace,
        uid=uid,
        labels={"app": name},
        annotations={},
        creation_timestamp=CREATED,
        generation=generation,
        owner_references=[],
    )


def make_statefulset(
    *,
    replicas=3,
    ready=3,
    updated=3,
    current_rev="web-1",
    update_rev="web-1",
    strategy="RollingUpdate",
    partition=0,
    observed_generation=1,
):
    return SimpleNamespace(
        metadata=_meta("web"),
        spec=SimpleNamespace(
            replicas=replicas,
            selector=SimpleNamespace(match_labels={"app": "web"}),
            template=_template(),
            update_strategy=SimpleNamespace(
                type=strategy,
                rolling_update=SimpleNamespace(partition=partition, max_unavailable=None)
                if strategy == "RollingUpdate"
                else None,
            ),
            min_ready_seconds=None,
            service_name="web-headless",
            pod_management_policy="OrderedReady",
            volume_claim_templates=[
                SimpleNamespace(
                    metadata=SimpleNamespace(name="data"),
                    spec=SimpleNamespace(
                        storage_class_name="managed-csi",
                        access_modes=["ReadWriteOnce"],
                        resources=SimpleNamespace(requests={"storage": "10Gi"}),
                    ),
                )
            ],
            persistent_volume_claim_retention_policy=None,
        ),
        status=SimpleNamespace(
            replicas=replicas,
            ready_replicas=ready,
            updated_replicas=updated,
            available_replicas=ready,
            current_replicas=replicas,
            current_revision=current_rev,
            update_revision=update_rev,
            observed_generation=observed_generation,
            conditions=None,
        ),
    )


def make_daemonset(*, desired=5, ready=5, updated=5):
    return SimpleNamespace(
        metadata=_meta("node-agent", namespace="kube-system"),
        spec=SimpleNamespace(
            selector=SimpleNamespace(match_labels={"app": "node-agent"}),
            template=_template(),
            update_strategy=SimpleNamespace(
                type="RollingUpdate",
                rolling_update=SimpleNamespace(max_unavailable=1, max_surge=0),
            ),
            min_ready_seconds=0,
        ),
        status=SimpleNamespace(
            desired_number_scheduled=desired,
            current_number_scheduled=desired,
            number_ready=ready,
            updated_number_scheduled=updated,
            number_available=ready,
            number_unavailable=desired - ready,
            number_misscheduled=0,
            observed_generation=1,
            conditions=None,
        ),
    )


# ── Status derivation & serialization ─────────────────────────────────


@pytest.mark.parametrize(
    ("args", "expected"),
    [
        ((0, 0, 0, 0, 1, 1), "Idle"),
        ((3, 0, 0, 3, 1, 1), "Unavailable"),
        ((3, 3, 1, 3, 2, 2), "Updating"),
        ((3, 3, 3, 3, 2, 1), "Updating"),
        ((3, 2, 3, 3, 1, 1), "Degraded"),
        ((3, 3, 3, 3, 1, 1), "Healthy"),
    ],
)
def test_workload_status(args, expected):
    assert wl.workload_status(*args) == expected


def test_serialize_statefulset_fields():
    item = wl.serialize_workload("statefulset", make_statefulset())

    assert item["kind"] == "StatefulSet"
    assert item["status"] == "Healthy"
    assert item["service_name"] == "web-headless"
    assert item["volume_claim_templates"][0] == {
        "name": "data",
        "storage_class": "managed-csi",
        "access_modes": ["ReadWriteOnce"],
        "storage": "10Gi",
    }


def test_statefulset_partition_is_not_reported_as_updating():
    """A partitioned rollout is intentionally incomplete — pods below the partition stay on the old revision."""
    sts = make_statefulset(updated=1, current_rev="web-1", update_rev="web-2", partition=2)
    item = wl.serialize_workload("statefulset", sts)

    assert item["status"] == "Healthy"
    assert item["update_pending"] is True


def test_statefulset_rollout_in_progress():
    sts = make_statefulset(updated=1, current_rev="web-1", update_rev="web-2")
    assert wl.serialize_workload("statefulset", sts)["status"] == "Updating"


def test_serialize_daemonset_fields():
    item = wl.serialize_workload("daemonset", make_daemonset(desired=5, ready=4))

    assert item["kind"] == "DaemonSet"
    assert item["desired"] == 5
    assert item["unavailable"] == 1
    assert item["max_unavailable"] == "1"
    assert item["status"] == "Degraded"


# ── Workload service mutations ────────────────────────────────────────


class FakeApps:
    def __init__(self, obj, revisions=()):
        self.obj = obj
        self.revisions = list(revisions)
        self.patches: list[tuple[str, dict]] = []

    def read_namespaced_stateful_set(self, name, namespace):
        return self.obj

    def patch_namespaced_stateful_set(self, name, namespace, body):
        self.patches.append((name, body))

    def list_namespaced_controller_revision(self, namespace, label_selector=None):
        return SimpleNamespace(items=self.revisions)


def _revision(number, image):
    return SimpleNamespace(
        metadata=SimpleNamespace(
            name=f"web-{number}",
            creation_timestamp=CREATED,
            owner_references=[SimpleNamespace(uid="uid-1")],
        ),
        revision=number,
        data={"spec": {"template": {"$patch": "replace", "spec": {"containers": [{"name": "app", "image": image}]}}}},
    )


@pytest.fixture
def workload_service(monkeypatch):
    def _build(apps):
        svc = AKSOperationsService.__new__(AKSOperationsService)
        svc.db = None

        async def _clients(_cluster_id):
            return (apps, None, None)

        async def _noop(*args, **kwargs):
            return 0

        svc._get_k8s_clients = _clients
        monkeypatch.setattr(wl.data_cache, "invalidate_for_workloads", _noop)
        return svc

    return _build


async def test_rollback_reapplies_revision_template(workload_service):
    apps = FakeApps(make_statefulset(), revisions=[_revision(1, "repo/app:1"), _revision(2, "repo/app:2")])
    svc = workload_service(apps)

    result = await svc.rollback_workload("statefulset", CLUSTER_ID, "data", "web", 1)

    assert result["to_revision"] == 1
    assert result["from_revision"] == 2
    assert apps.patches[0][1]["spec"]["template"]["spec"]["containers"][0]["image"] == "repo/app:1"


async def test_rollback_to_current_revision_is_rejected(workload_service):
    apps = FakeApps(make_statefulset(), revisions=[_revision(1, "a"), _revision(2, "b")])
    svc = workload_service(apps)

    with pytest.raises(ValueError):
        await svc.rollback_workload("statefulset", CLUSTER_ID, "data", "web", 2)
    assert apps.patches == []


async def test_rollback_unknown_revision(workload_service):
    svc = workload_service(FakeApps(make_statefulset(), revisions=[_revision(1, "a")]))

    with pytest.raises(LookupError):
        await svc.rollback_workload("statefulset", CLUSTER_ID, "data", "web", 7)


async def test_update_image_patches_named_container(workload_service):
    apps = FakeApps(make_statefulset())
    svc = workload_service(apps)

    result = await svc.update_workload_image("statefulset", CLUSTER_ID, "data", "web", "app", "repo/app:9")

    assert result["previous_image"] == "repo/app:1"
    assert apps.patches[0][1] == {
        "spec": {"template": {"spec": {"containers": [{"name": "app", "image": "repo/app:9"}]}}}
    }


async def test_update_image_unknown_container(workload_service):
    apps = FakeApps(make_statefulset())
    svc = workload_service(apps)

    with pytest.raises(ValueError):
        await svc.update_workload_image("statefulset", CLUSTER_ID, "data", "web", "sidecar", "x:1")
    assert apps.patches == []


async def test_on_delete_strategy_clears_rolling_update(workload_service):
    apps = FakeApps(make_statefulset())
    svc = workload_service(apps)

    await svc.update_workload_strategy("statefulset", CLUSTER_ID, "data", "web", "OnDelete")

    assert apps.patches[0][1] == {"spec": {"updateStrategy": {"type": "OnDelete", "rollingUpdate": None}}}


async def test_mutation_refreshes_db_inventory(workload_service, monkeypatch):
    """The grid reads the DB inventory, so a change must re-sync the namespace immediately."""
    svc = workload_service(FakeApps(make_statefulset()))
    synced: list[tuple] = []

    async def _sync(kind, cluster_id, namespace=None):
        synced.append((kind, namespace))
        return {}

    monkeypatch.setattr(svc, "sync_workloads_to_db", _sync)

    await svc.restart_workload("statefulset", CLUSTER_ID, "data", "web")

    assert synced == [("statefulset", "data")]


async def test_sync_workloads_to_db_uses_kind_specific_inventory(workload_service, monkeypatch):
    svc = workload_service(FakeApps(make_statefulset()))
    calls: list[tuple] = []

    async def _live(kind, cluster_id, namespace=None):
        return [{"name": "web", "namespace": "data", "status": "Healthy"}]

    async def _inventory(cluster_id, resource_type, id_segment, items, namespace=None):
        calls.append((resource_type, id_segment, len(items), namespace))
        return {"synced_count": len(items), "resources": items}

    monkeypatch.setattr(svc, "_fetch_workloads_live", _live)
    monkeypatch.setattr(svc, "_sync_inventory", _inventory)

    result = await svc.sync_workloads_to_db("daemonset", CLUSTER_ID, "data")

    assert calls == [("aks_daemonset", "daemonset", 1, "data")]
    assert "resources" not in result


def test_sync_jobs_support_new_resource_types():
    from app.api.v1.endpoints import sync_jobs

    svc = SimpleNamespace(
        sync_workloads_to_db=lambda kind, cid, ns: ("workloads", kind),
        sync_akvs_to_db=lambda cid, ns: ("akvs",),
    )
    assert {"statefulsets", "daemonsets", "akvs"} <= sync_jobs._AKS_RESOURCE_TYPES
    assert sync_jobs._get_aks_sync_fn(svc, "statefulsets", CLUSTER_ID, None)() == ("workloads", "statefulset")
    assert sync_jobs._get_aks_sync_fn(svc, "daemonsets", CLUSTER_ID, None)() == ("workloads", "daemonset")
    assert sync_jobs._get_aks_sync_fn(svc, "akvs", CLUSTER_ID, None)() == ("akvs",)


async def test_live_sync_hub_supports_new_resource_types():
    """The tabs subscribe to the WebSocket like Deployments; the hub must know how to re-sync them."""
    from app.services.aks_live_sync_hub import _K8S_SYNC

    calls: list[tuple] = []

    async def _workloads(kind, cid, ns):
        calls.append(("workloads", kind, ns))
        return {}

    async def _akvs(cid, ns):
        calls.append(("akvs", ns))
        return {}

    svc = SimpleNamespace(sync_workloads_to_db=_workloads, sync_akvs_to_db=_akvs)
    await _K8S_SYNC["statefulsets"](svc, CLUSTER_ID, "data")
    await _K8S_SYNC["daemonsets"](svc, CLUSTER_ID, None)
    await _K8S_SYNC["akvs"](svc, CLUSTER_ID, "data")

    assert calls == [("workloads", "statefulset", "data"), ("workloads", "daemonset", None), ("akvs", "data")]


# ── AKV → AKS sync (akv2k8s AzureKeyVaultSecret) ──────────────────────


def make_akvs(
    name="aaf-id",
    namespace="data",
    output=None,
    status=None,
    object_type="secret",
):
    return {
        "metadata": {"name": name, "namespace": namespace, "creationTimestamp": "2026-09-01T00:00:00Z"},
        "spec": {
            "vault": {"name": "attcc-eastus2-perf-kv", "object": {"name": name, "type": object_type}},
            "output": output
            if output is not None
            else {"secret": {"name": "aaf-cred", "dataKey": "aaf_id"}, "transform": ["base64decode"]},
        },
        "status": status
        if status is not None
        else {"lastAzureUpdate": "2026-10-01T16:38:58Z", "secretHash": "abc", "secretName": "aaf-cred"},
    }


def make_akvs_event(name="aaf-id", type_="Warning", reason="ErrAzureVault", when=None, message="Failed to get secret"):
    return SimpleNamespace(
        type=type_,
        reason=reason,
        message=message,
        count=2,
        last_timestamp=when or datetime(2026, 10, 1, 17, 0, tzinfo=UTC),
        event_time=None,
        first_timestamp=None,
        metadata=SimpleNamespace(namespace="data"),
        involved_object=SimpleNamespace(kind="AzureKeyVaultSecret", name=name, namespace="data"),
    )


OUTPUTS = {("secret", "data", "aaf-cred"): {"aaf_id", "aaf_password"}}


def _event_row(**kwargs):
    return akvs.serialize_event(make_akvs_event(**kwargs))


def test_akvs_synced():
    item = akvs.serialize_akvs(make_akvs(), None, OUTPUTS)

    assert item["status"] == "Synced"
    assert item["vault_name"] == "attcc-eastus2-perf-kv"
    assert item["output_kind"] == "secret"
    assert item["output_data_key"] == "aaf_id"
    assert item["transforms"] == ["base64decode"]
    assert item["key_present"] is True


def test_akvs_failed_when_controller_reports_error_without_sync():
    obj = make_akvs(status={})
    item = akvs.serialize_akvs(obj, _event_row(), OUTPUTS)

    assert item["status"] == "Failed"
    assert item["status_reason"] == "Failed to get secret"


def test_akvs_old_error_does_not_mask_a_later_sync():
    old_error = _event_row(when=datetime(2026, 10, 1, 10, 0, tzinfo=UTC))
    item = akvs.serialize_akvs(make_akvs(), old_error, OUTPUTS)

    assert item["status"] == "Synced"


def test_akvs_error_after_last_sync_is_failed():
    new_error = _event_row(when=datetime(2026, 10, 1, 18, 0, tzinfo=UTC))
    assert akvs.serialize_akvs(make_akvs(), new_error, OUTPUTS)["status"] == "Failed"


def test_akvs_pending_before_first_sync():
    assert akvs.serialize_akvs(make_akvs(status={}), None, OUTPUTS)["status"] == "Pending"


def test_akvs_degraded_when_output_secret_or_key_missing():
    assert akvs.serialize_akvs(make_akvs(), None, {})["status"] == "Degraded"
    missing_key = {("secret", "data", "aaf-cred"): {"aaf_password"}}
    item = akvs.serialize_akvs(make_akvs(), None, missing_key)
    assert item["status"] == "Degraded"
    assert "aaf_id" in item["status_reason"]


def test_akvs_env_injector_without_output():
    item = akvs.serialize_akvs(make_akvs(output={}, status={}), None, {})

    assert item["status"] == "EnvInjector"
    assert item["output_exists"] is None


def test_latest_event_per_object_wins():
    events = [
        make_akvs_event(type_="Warning", when=datetime(2026, 10, 1, 9, 0, tzinfo=UTC)),
        make_akvs_event(type_="Normal", reason="Synced", when=datetime(2026, 10, 1, 12, 0, tzinfo=UTC)),
        SimpleNamespace(
            type="Warning",
            reason="BackOff",
            message="",
            count=1,
            last_timestamp=CREATED,
            event_time=None,
            first_timestamp=None,
            metadata=SimpleNamespace(namespace="data"),
            involved_object=SimpleNamespace(kind="Pod", name="aaf-id", namespace="data"),
        ),
    ]
    latest = akvs.latest_events_by_object(events)

    assert list(latest) == [("data", "aaf-id")]
    assert latest[("data", "aaf-id")]["reason"] == "Synced"


def test_summarize_akvs():
    items = [
        akvs.serialize_akvs(make_akvs(), None, OUTPUTS),
        akvs.serialize_akvs(make_akvs(name="aaf-password", status={}), _event_row(name="aaf-password"), OUTPUTS),
    ]
    summary = akvs.summarize_akvs(items)

    assert summary["total"] == 2
    assert summary["Synced"] == 1
    assert summary["Failed"] == 1
    assert summary["vaults"] == 1
    assert summary["outputs"] == 1


@pytest.mark.parametrize(
    ("last_update", "created", "expected"),
    [
        ("2026-10-01T16:00:00Z", "2026-10-01T15:00:00+00:00", True),
        ("2026-10-01T16:00:00Z", "2026-10-01T17:00:00+00:00", False),
        (None, "2026-10-01T17:00:00+00:00", None),
    ],
)
def test_evaluate_vault_drift(last_update, created, expected):
    assert akvs.evaluate_vault_drift(last_update, created) is expected


async def test_vault_check_rejects_unsafe_vault_name():
    """The vault name comes from a cluster object and must never redirect the portal's vault token."""
    svc = AKSOperationsService.__new__(AKSOperationsService)
    result = await svc._check_akvs_vault(
        {"vault_name": "evil.example.com/x#", "object_name": "aaf-id", "object_type": "secret"}
    )

    assert result["checked"] is False


async def test_vault_check_detects_drift(monkeypatch):
    class FakeKV:
        async def _get_vault_token(self):
            return "token"

        async def _vault_get(self, url, *, token=None):
            assert url.startswith("https://attcc-eastus2-perf-kv.vault.azure.net/secrets/aaf-id/versions")
            # 1790000000 = 2026-09-21; 1791000000 = 2026-10-03, i.e. after the last sync below.
            return {
                "value": [
                    {"id": ".../v1", "attributes": {"enabled": True, "created": 1790000000}},
                    {"id": ".../v2", "attributes": {"enabled": True, "created": 1791000000}},
                ]
            }

    from app.services import keyvault_service

    monkeypatch.setattr(keyvault_service, "KeyVaultService", FakeKV)
    svc = AKSOperationsService.__new__(AKSOperationsService)
    item = akvs.serialize_akvs(make_akvs(), None, OUTPUTS)

    result = await svc._check_akvs_vault(item)

    assert result["checked"] is True
    assert result["latest_version"] == "v2"
    assert result["in_sync"] is False


class FakeCustomObjects:
    def __init__(self, served):
        self.served = served
        self.calls: list[str] = []

    def list_namespaced_custom_object(self, group, version, namespace, plural):
        self.calls.append(version)
        if version not in self.served:
            raise ApiException(status=404, reason="Not Found")
        return {"items": [make_akvs()]}


async def test_list_akvs_falls_back_to_served_version():
    svc = AKSOperationsService.__new__(AKSOperationsService)
    custom = FakeCustomObjects(served={"v1"})

    items = await svc._list_akvs(custom, "data")

    assert len(items) == 1
    assert custom.calls == ["v2beta1", "v1"]


async def test_list_akvs_returns_none_when_crd_missing():
    svc = AKSOperationsService.__new__(AKSOperationsService)
    assert await svc._list_akvs(FakeCustomObjects(served=set()), "data") is None


# ── API ───────────────────────────────────────────────────────────────


class FakeWorkloadService:
    def __init__(self, *, items=None, raises=None, akvs_items=None):
        self.items = items or []
        self.raises = raises
        self.akvs_items = akvs_items or []
        self.calls: list[tuple] = []

    async def list_workloads(self, kind, cluster_id, namespace=None, bypass_cache=False):
        self.calls.append(("list", kind))
        return self.items

    async def get_workloads_from_db(self, kind, cluster_id, namespace=None):
        self.calls.append(("cached", kind, namespace))
        return self.items

    async def get_workloads_last_sync_time(self, kind, cluster_id):
        return "2026-10-01T12:00:00"

    async def scale_statefulset(self, cluster_id, namespace, name, replicas):
        self.calls.append(("scale", name, replicas))
        if self.raises:
            raise self.raises
        return {"success": True, "name": name, "namespace": namespace, "previous_replicas": 1, "new_replicas": replicas}

    async def delete_workload(self, kind, cluster_id, namespace, name, propagation_policy="Background"):
        self.calls.append(("delete", kind, name, propagation_policy))
        return {"success": True, "name": name, "namespace": namespace}

    async def get_akvs_from_db(self, cluster_id, namespace=None):
        return self.akvs_items

    async def get_akvs_last_sync_time(self, cluster_id):
        return "2026-10-01T12:00:00"

    async def get_akvs_controller_status(self, cluster_id):
        return {"installed": True, "versions": ["v1", "v2beta1"], "components": []}

    async def get_akvs_detail(self, cluster_id, namespace, name, check_vault=False):
        raise LookupError(f"AzureKeyVaultSecret '{name}' was not found in namespace '{namespace}'.")


def make_user(*roles: UserRole, user_id: str = "u-test") -> UserContext:
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


async def _seed(db_session, capability: str, *, granted_to: str | None, permission_type: str) -> None:
    res = Resource(resource_type="operation", resource_name=capability, description=capability, is_system=True)
    db_session.add(res)
    await db_session.commit()
    await db_session.refresh(res)
    if granted_to:
        db_session.add(
            Permission(
                subject_type="role",
                subject_id=granted_to,
                resource_id=res.id,
                permission_type=permission_type,
                environment_scope="all",
            )
        )
        await db_session.commit()


@asynccontextmanager
async def client(app, db_session, user: UserContext, service):
    async def _get_db_override():
        yield db_session

    app.dependency_overrides[get_db] = _get_db_override
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[_get_service] = lambda: service
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            yield ac
    finally:
        app.dependency_overrides.clear()


async def test_list_statefulsets(app, db_session):
    await _seed(db_session, "aks_workload_view", granted_to="read", permission_type="view")
    service = FakeWorkloadService(items=[{"name": "web"}])

    async with client(app, db_session, make_user(UserRole.READ), service) as ac:
        resp = await ac.get("/api/v1/aks/workloads/statefulset", params={"cluster_id": CLUSTER_ID})

    assert resp.status_code == 200
    assert resp.json() == {"kind": "StatefulSet", "items": [{"name": "web"}], "count": 1}


async def test_list_requires_view_capability(app, db_session):
    await _seed(db_session, "aks_workload_view", granted_to="write", permission_type="view")

    async with client(app, db_session, make_user(UserRole.READ), FakeWorkloadService()) as ac:
        resp = await ac.get("/api/v1/aks/workloads/daemonset", params={"cluster_id": CLUSTER_ID})

    assert resp.status_code == 403


async def test_unknown_workload_kind_rejected(app, db_session):
    async with client(app, db_session, make_user(UserRole.ADMIN), FakeWorkloadService()) as ac:
        resp = await ac.get("/api/v1/aks/workloads/replicaset", params={"cluster_id": CLUSTER_ID})

    assert resp.status_code == 422


async def test_scale_statefulset_is_audited(app, db_session):
    from app.api.v1.endpoints import aks_operations

    aks_operations._in_memory_audit_log.clear()
    await _seed(db_session, "aks_workload_manage", granted_to="write", permission_type="edit")
    service = FakeWorkloadService()
    body = {"cluster_id": CLUSTER_ID, "namespace": "data", "name": "web", "replicas": 4}

    async with client(app, db_session, make_user(UserRole.WRITE, user_id="u-op"), service) as ac:
        resp = await ac.post("/api/v1/aks/workloads/statefulset/scale", json=body)

    entries = [e for e in aks_operations._in_memory_audit_log if e["action"] == "scale_statefulset"]
    aks_operations._in_memory_audit_log.clear()

    assert resp.status_code == 200
    assert service.calls == [("scale", "web", 4)]
    assert len(entries) == 1
    assert entries[0]["status"] == "success"
    assert entries[0]["user_id"] == "u-op"


async def test_scale_daemonset_rejected(app, db_session):
    await _seed(db_session, "aks_workload_manage", granted_to="write", permission_type="edit")
    service = FakeWorkloadService()
    body = {"cluster_id": CLUSTER_ID, "namespace": "data", "name": "agent", "replicas": 2}

    async with client(app, db_session, make_user(UserRole.WRITE), service) as ac:
        resp = await ac.post("/api/v1/aks/workloads/daemonset/scale", json=body)

    assert resp.status_code == 400
    assert service.calls == []


async def test_scale_maps_kubernetes_404(app, db_session):
    await _seed(db_session, "aks_workload_manage", granted_to="write", permission_type="edit")
    service = FakeWorkloadService(raises=ApiException(status=404, reason="Not Found"))
    body = {"cluster_id": CLUSTER_ID, "namespace": "data", "name": "gone", "replicas": 1}

    async with client(app, db_session, make_user(UserRole.WRITE), service) as ac:
        resp = await ac.post("/api/v1/aks/workloads/statefulset/scale", json=body)

    assert resp.status_code == 404
    assert "gone" in resp.json()["detail"]


async def test_invalid_resource_name_rejected(app, db_session):
    await _seed(db_session, "aks_workload_manage", granted_to="write", permission_type="edit")
    body = {"cluster_id": CLUSTER_ID, "namespace": "data", "name": "Bad,Name", "replicas": 1}

    async with client(app, db_session, make_user(UserRole.WRITE), FakeWorkloadService()) as ac:
        resp = await ac.post("/api/v1/aks/workloads/statefulset/scale", json=body)

    assert resp.status_code == 422


async def test_read_user_cannot_delete_workload(app, db_session):
    await _seed(db_session, "aks_workload_delete", granted_to="write", permission_type="edit")
    service = FakeWorkloadService()

    async with client(app, db_session, make_user(UserRole.READ), service) as ac:
        resp = await ac.delete(
            "/api/v1/aks/workloads/daemonset",
            params={"cluster_id": CLUSTER_ID, "namespace": "kube-system", "name": "agent"},
        )

    assert resp.status_code == 403
    assert service.calls == []


async def test_delete_workload_with_orphan_policy(app, db_session):
    await _seed(db_session, "aks_workload_delete", granted_to="write", permission_type="edit")
    service = FakeWorkloadService()

    async with client(app, db_session, make_user(UserRole.WRITE), service) as ac:
        resp = await ac.delete(
            "/api/v1/aks/workloads/statefulset",
            params={"cluster_id": CLUSTER_ID, "namespace": "data", "name": "web", "propagation_policy": "Orphan"},
        )

    assert resp.status_code == 200
    assert service.calls == [("delete", "statefulset", "web", "Orphan")]


async def test_list_cached_statefulsets_reads_db(app, db_session):
    await _seed(db_session, "aks_workload_view", granted_to="read", permission_type="view")
    service = FakeWorkloadService(items=[{"name": "web"}])

    async with client(app, db_session, make_user(UserRole.READ), service) as ac:
        resp = await ac.get(
            "/api/v1/aks/workloads/statefulset/cached", params={"cluster_id": CLUSTER_ID, "namespace": "data"}
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["source"] == "db"
    assert body["last_sync"] == "2026-10-01T12:00:00"
    assert body["count"] == 1
    assert service.calls == [("cached", "statefulset", "data")]


async def test_akv_sync_cached_includes_summary(app, db_session):
    await _seed(db_session, "aks_akv_sync_view", granted_to="read", permission_type="view")
    items = [akvs.serialize_akvs(make_akvs(), None, OUTPUTS)]

    async with client(app, db_session, make_user(UserRole.READ), FakeWorkloadService(akvs_items=items)) as ac:
        resp = await ac.get("/api/v1/aks/akv-sync/cached", params={"cluster_id": CLUSTER_ID})

    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 1
    assert body["summary"]["Synced"] == 1


async def test_akv_sync_controller(app, db_session):
    await _seed(db_session, "aks_akv_sync_view", granted_to="read", permission_type="view")

    async with client(app, db_session, make_user(UserRole.READ), FakeWorkloadService()) as ac:
        resp = await ac.get("/api/v1/aks/akv-sync/controller", params={"cluster_id": CLUSTER_ID})

    assert resp.status_code == 200
    assert resp.json()["installed"] is True


async def test_akv_sync_detail_404(app, db_session):
    await _seed(db_session, "aks_akv_sync_view", granted_to="read", permission_type="view")

    async with client(app, db_session, make_user(UserRole.READ), FakeWorkloadService()) as ac:
        resp = await ac.get(
            "/api/v1/aks/akv-sync/detail",
            params={"cluster_id": CLUSTER_ID, "namespace": "data", "name": "missing"},
        )

    assert resp.status_code == 404
