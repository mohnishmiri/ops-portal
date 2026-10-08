"""
AKS node pools: counts and pods are accurate, an unreachable Kubernetes API is
reported as unavailable (not as zero pods), syncs can't hang, and scale /
autoscaling changes are validated, permission-checked, and audited.
"""

import asyncio
import json
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.v1.endpoints import aks_operations, sync_jobs
from app.api.v1.endpoints.aks_operations import _get_service
from app.auth import get_current_user
from app.core.database import get_db
from app.models.database import Permission, Resource, SyncJob
from app.schemas.auth import UserContext, UserRole
from app.services import aks_nodepool_operations as np_ops
from app.services.aks_operations_service import AKSOperationsService

CLUSTER_ID = "/subscriptions/s1/resourceGroups/rg1/providers/Microsoft.ContainerService/managedClusters/aks-prod-01"


# ── Builders ──────────────────────────────────────────────────────────


def make_pool(name="userpool", *, mode="User", count=3, auto=False, min_count=None, max_count=None, **extra):
    fields = {
        "name": name,
        "vm_size": "Standard_D32s_v3",
        "count": count,
        "min_count": min_count,
        "max_count": max_count,
        "enable_auto_scaling": auto,
        "mode": mode,
        "os_type": "Linux",
        "os_sku": "Ubuntu",
        "os_disk_size_gb": 128,
        "os_disk_type": "Managed",
        "current_orchestrator_version": "1.34.1",
        "orchestrator_version": "1.34",
        "provisioning_state": "Succeeded",
        "power_state": SimpleNamespace(code="Running"),
        "max_pods": 30,
        "node_labels": {"nodepool": "elk"},
        "node_taints": [],
        "availability_zones": ["1", "2", "3"],
        "node_image_version": "AKSUbuntu-2204gen2containerd-202602.13.0",
        "scale_set_priority": None,
        "scale_down_mode": None,
        "upgrade_settings": SimpleNamespace(max_surge="10%"),
    }
    fields.update(extra)
    return SimpleNamespace(**fields)


def make_node(name, pool="userpool", *, ready=True, cordoned=False, pods_allocatable="30"):
    return SimpleNamespace(
        metadata=SimpleNamespace(
            name=name,
            labels={"kubernetes.azure.com/agentpool": pool, "topology.kubernetes.io/zone": "eastus2-1"},
            creation_timestamp=datetime(2026, 10, 1, tzinfo=UTC),
        ),
        spec=SimpleNamespace(unschedulable=cordoned),
        status=SimpleNamespace(
            conditions=[SimpleNamespace(type="Ready", status="True" if ready else "False")],
            allocatable={"pods": pods_allocatable, "cpu": "31580m", "memory": "123456Ki"},
            node_info=SimpleNamespace(kubelet_version="v1.34.1"),
        ),
    )


class FakeCore:
    def __init__(self, nodes, pods_by_node):
        self.nodes = nodes
        self.pods_by_node = pods_by_node
        self.calls: dict[str, dict] = {}

    def list_node(self, **kwargs):
        self.calls["list_node"] = kwargs
        return SimpleNamespace(items=self.nodes)

    def list_pod_for_all_namespaces(self, **kwargs):
        self.calls["list_pod"] = kwargs
        items = [{"spec": {"nodeName": node}} for node, n in self.pods_by_node.items() for _ in range(n)]
        return SimpleNamespace(data=json.dumps({"items": items}).encode())


def service_with(core=None, k8s_error: Exception | None = None) -> AKSOperationsService:
    svc = AKSOperationsService.__new__(AKSOperationsService)
    svc.db = None

    async def _clients(_cluster_id):
        if k8s_error:
            raise k8s_error
        return None, core, None

    svc._get_k8s_clients = _clients
    return svc


# ── Accuracy ──────────────────────────────────────────────────────────


async def test_pool_counts_running_pods_and_node_health():
    core = FakeCore(
        [make_node("n1"), make_node("n2", ready=False), make_node("n3", cordoned=True), make_node("s1", pool="sys")],
        {"n1": 12, "n2": 3, "n3": 1, "s1": 9},
    )
    nodes, error = await service_with(core)._node_pool_k8s_snapshot(CLUSTER_ID)

    pool = np_ops.build_node_pool(make_pool(), vmss_count=3, nodes=nodes, k8s_error=error)

    # Terminated pods (completed Jobs, evictions) are excluded at the API, with a bounded request.
    assert core.calls["list_pod"]["field_selector"] == "status.phase!=Succeeded,status.phase!=Failed"
    assert core.calls["list_pod"]["_request_timeout"] and core.calls["list_node"]["_request_timeout"]
    assert pool["total_pods"] == 16
    assert pool["pod_capacity"] == 90
    assert pool["ready_nodes"] == 2
    assert pool["cordoned_nodes"] == 1
    assert [n["name"] for n in pool["nodes"]] == ["n1", "n2", "n3"]
    assert pool["node_details_available"] is True


def test_pool_reports_the_running_kubernetes_version_and_live_node_count():
    pool = np_ops.build_node_pool(make_pool(count=3), vmss_count=6, nodes=[], k8s_error=None)

    assert pool["kubernetes_version"] == "1.34.1"
    assert pool["count"] == 6
    assert pool["max_surge"] == "10%"
    assert pool["scale_set_priority"] == "Regular"


def test_pool_falls_back_to_azure_count_without_scale_set_data():
    assert np_ops.build_node_pool(make_pool(count=4), vmss_count=None, nodes=[], k8s_error=None)["count"] == 4


async def test_unreachable_cluster_marks_node_details_unavailable_not_zero():
    svc = service_with(k8s_error=ConnectionError("Max retries exceeded: Failed to resolve 'aks.privatelink'"))

    nodes, error = await svc._node_pool_k8s_snapshot(CLUSTER_ID)
    pool = np_ops.build_node_pool(make_pool(), vmss_count=3, nodes=nodes, k8s_error=error)

    assert pool["node_details_available"] is False
    assert pool["total_pods"] is None
    assert pool["ready_nodes"] is None
    assert "can't be reached" in pool["node_details_error"]
    assert pool["count"] == 3  # Azure data is still current


async def test_hung_kubernetes_api_cannot_hold_the_sync(monkeypatch):
    monkeypatch.setattr(np_ops, "K8S_SNAPSHOT_TIMEOUT_SECONDS", 0.05)
    svc = service_with(FakeCore([], {}))

    async def _hang(_cluster_id):
        await asyncio.sleep(10)

    svc._read_pool_nodes = _hang

    nodes, error = await svc._node_pool_k8s_snapshot(CLUSTER_ID)

    assert nodes is None
    assert error == "The Kubernetes API did not respond in time."


class FakeAgentPools:
    def __init__(self, pools):
        self.pools = {p.name: p for p in pools}
        self.updates: list[tuple[str, SimpleNamespace]] = []

    def list(self, resource_group, cluster_name):
        return list(self.pools.values())

    def get(self, resource_group, cluster_name, name):
        return self.pools[name]

    def begin_create_or_update(self, resource_group, cluster_name, name, pool):
        self.updates.append((name, SimpleNamespace(**vars(pool))))


@pytest.fixture
def azure(monkeypatch):
    agent_pools = FakeAgentPools(
        [
            make_pool("sys", mode="System", count=2),
            make_pool("manual", count=3),
            make_pool("auto", count=5, auto=True, min_count=1, max_count=10),
        ]
    )
    client = SimpleNamespace(
        agent_pools=agent_pools,
        managed_clusters=SimpleNamespace(get=lambda rg, name: SimpleNamespace(node_resource_group="MC_rg")),
    )
    monkeypatch.setattr(np_ops, "ContainerServiceClient", lambda credential, subscription: client)
    monkeypatch.setattr(AKSOperationsService, "credential", None, raising=False)
    monkeypatch.setattr(np_ops.data_cache, "invalidate_for_nodepools", _noop)
    return agent_pools


async def _noop(*_args, **_kwargs):
    return None


async def test_live_read_keeps_azure_data_when_kubernetes_fails(azure):
    svc = service_with(k8s_error=TimeoutError())
    svc._actual_node_counts_from_vmss = lambda sub, rg: (9, {"auto": 7})

    pools = {p["name"]: p for p in await svc._fetch_node_pools_live(CLUSTER_ID)}

    assert pools["auto"]["count"] == 7
    assert pools["manual"]["count"] == 3
    assert all(p["node_details_available"] is False for p in pools.values())


# ── Scale / autoscaling validation ────────────────────────────────────


async def test_scale_manual_pool(azure):
    result = await service_with().scale_node_pool(CLUSTER_ID, "manual", 5)

    assert result["success"] is True
    assert result["previous_count"] == 3
    assert azure.updates[0][0] == "manual" and azure.updates[0][1].count == 5


@pytest.mark.parametrize(
    ("pool", "count", "message"),
    [
        ("auto", 6, "cluster autoscaler manages auto"),
        ("sys", 0, "needs at least 1 node"),
        ("manual", 3, "already has 3 nodes"),
    ],
)
async def test_scale_is_rejected_before_azure(azure, pool, count, message):
    result = await service_with().scale_node_pool(CLUSTER_ID, pool, count)

    assert result["success"] is False
    assert message in result["error"]
    assert azure.updates == []


async def test_enable_autoscaling(azure):
    result = await service_with().update_node_pool_autoscaling(CLUSTER_ID, "manual", True, 0, 8)

    updated = azure.updates[0][1]
    assert result["success"] is True
    assert (updated.enable_auto_scaling, updated.min_count, updated.max_count) == (True, 0, 8)
    assert result["previous"]["enable_auto_scaling"] is False


async def test_disable_autoscaling_clears_the_range(azure):
    result = await service_with().update_node_pool_autoscaling(CLUSTER_ID, "auto", False, 4, 9)

    updated = azure.updates[0][1]
    assert result["success"] is True
    assert (updated.enable_auto_scaling, updated.min_count, updated.max_count) == (False, None, None)


@pytest.mark.parametrize(
    ("pool", "enable", "min_count", "max_count", "message"),
    [
        ("manual", True, 5, 2, "can't be greater than the maximum"),
        ("sys", True, 0, 5, "minimum must be at least 1"),
        ("manual", True, None, 5, "Set both"),
        ("auto", True, 1, 10, "already autoscales between 1 and 10"),
        ("manual", False, None, None, "already off"),
    ],
)
async def test_invalid_autoscaling_is_rejected_before_azure(azure, pool, enable, min_count, max_count, message):
    result = await service_with().update_node_pool_autoscaling(CLUSTER_ID, pool, enable, min_count, max_count)

    assert result["success"] is False
    assert message in result["error"]
    assert azure.updates == []


# ── API: permissions and audit ────────────────────────────────────────


class FakeNodePoolService:
    def __init__(self, success=True):
        self.success = success
        self.calls: list[tuple] = []

    async def scale_node_pool(self, cluster_id, nodepool_name, node_count):
        self.calls.append(("scale", nodepool_name, node_count))
        if not self.success:
            return {"success": False, "previous_count": 3, "error": "already has 3 nodes."}
        return {"success": True, "previous_count": 3, "new_count": node_count}

    async def update_node_pool_autoscaling(self, cluster_id, nodepool_name, enable_auto_scaling, min_count, max_count):
        self.calls.append(("autoscale", nodepool_name, enable_auto_scaling, min_count, max_count))
        return {"success": True, "previous": {"enable_auto_scaling": False}}


def make_user(*roles: UserRole) -> UserContext:
    return UserContext(
        user_id="u-op",
        object_id="00000000-0000-0000-0000-000000000000",
        display_name="Operator",
        email="op@example.com",
        roles=list(roles),
        raw_roles=[r.value for r in roles],
        tenant_id="tenant-test",
        allowed_subscriptions=[],
    )


async def _seed_manage(db_session) -> None:
    res = Resource(resource_type="operation", resource_name="aks_nodepool_manage", description="x", is_system=True)
    db_session.add(res)
    await db_session.commit()
    await db_session.refresh(res)
    db_session.add(
        Permission(
            subject_type="role",
            subject_id="write",
            resource_id=res.id,
            permission_type="edit",
            environment_scope="all",
        )
    )
    await db_session.commit()


@asynccontextmanager
async def client(app, db_session, user, service=None):
    async def _db():
        yield db_session

    app.dependency_overrides[get_db] = _db
    app.dependency_overrides[get_current_user] = lambda: user
    if service is not None:
        app.dependency_overrides[_get_service] = lambda: service
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            yield ac
    finally:
        app.dependency_overrides.clear()


SCALE_BODY = {"cluster_id": CLUSTER_ID, "nodepool_name": "manual", "node_count": 5}


async def test_read_user_cannot_scale_node_pool(app, db_session):
    await _seed_manage(db_session)
    service = FakeNodePoolService()

    async with client(app, db_session, make_user(UserRole.READ), service) as ac:
        resp = await ac.post("/api/v1/aks/nodepools/scale", json=SCALE_BODY)

    assert resp.status_code == 403
    assert service.calls == []


async def test_scale_node_pool_is_audited(app, db_session):
    aks_operations._in_memory_audit_log.clear()
    await _seed_manage(db_session)
    service = FakeNodePoolService()

    async with client(app, db_session, make_user(UserRole.WRITE), service) as ac:
        resp = await ac.post("/api/v1/aks/nodepools/scale", json=SCALE_BODY)

    entries = [e for e in aks_operations._in_memory_audit_log if e["action"] == "scale_nodepool"]
    aks_operations._in_memory_audit_log.clear()
    assert resp.status_code == 200
    assert len(entries) == 1
    assert entries[0]["status"] == "success"
    assert entries[0]["details"]["previous_count"] == 3


async def test_rejected_scale_is_audited_as_failed(app, db_session):
    aks_operations._in_memory_audit_log.clear()
    await _seed_manage(db_session)

    async with client(app, db_session, make_user(UserRole.WRITE), FakeNodePoolService(success=False)) as ac:
        resp = await ac.post("/api/v1/aks/nodepools/scale", json=SCALE_BODY)

    entries = [e for e in aks_operations._in_memory_audit_log if e["action"] == "scale_nodepool"]
    aks_operations._in_memory_audit_log.clear()
    assert resp.status_code == 400
    assert resp.json()["detail"] == "already has 3 nodes."
    assert entries[0]["status"] == "failed"


async def test_autoscaling_change_is_audited(app, db_session):
    aks_operations._in_memory_audit_log.clear()
    await _seed_manage(db_session)
    service = FakeNodePoolService()
    body = {
        "cluster_id": CLUSTER_ID,
        "nodepool_name": "manual",
        "enable_auto_scaling": True,
        "min_count": 0,
        "max_count": 8,
    }

    async with client(app, db_session, make_user(UserRole.WRITE), service) as ac:
        resp = await ac.post("/api/v1/aks/nodepools/autoscaling", json=body)

    entries = [e for e in aks_operations._in_memory_audit_log if e["action"] == "update_nodepool_autoscaling"]
    aks_operations._in_memory_audit_log.clear()
    assert resp.status_code == 200
    assert service.calls == [("autoscale", "manual", True, 0, 8)]
    assert entries[0]["details"]["summary"] == "Set node pool manual to autoscaling 0–8 nodes"


async def test_invalid_node_pool_name_is_rejected(app, db_session):
    await _seed_manage(db_session)
    service = FakeNodePoolService()

    async with client(app, db_session, make_user(UserRole.WRITE), service) as ac:
        resp = await ac.post("/api/v1/aks/nodepools/scale", json={**SCALE_BODY, "nodepool_name": "../Pool"})

    assert resp.status_code == 422
    assert service.calls == []


# ── Sync jobs ─────────────────────────────────────────────────────────


async def test_non_admin_can_request_an_immediate_aks_sync(app, db_engine, db_session, monkeypatch):
    async with db_engine.begin() as conn:
        await conn.run_sync(lambda c: SyncJob.__table__.create(c, checkfirst=True))
    started: list[int] = []

    async def _enqueue(job_type, **_kwargs):
        return 41

    async def _run(job_id, payload):
        started.append(job_id)

    monkeypatch.setattr(sync_jobs, "enqueue_job", _enqueue)
    monkeypatch.setattr(sync_jobs, "_run_aks_sync_inline", _run)
    body = {"job_type": "aks_resource_sync", "resource_type": "nodepools", "cluster_id": CLUSTER_ID, "force": True}

    async with client(app, db_session, make_user(UserRole.WRITE)) as ac:
        resp = await ac.post("/api/v1/sync-jobs", json=body)
        await asyncio.sleep(0)

    assert resp.status_code in (200, 201, 202)
    assert resp.json()["job_id"] == 41
    assert started == [41]
