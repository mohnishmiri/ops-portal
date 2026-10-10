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
from kubernetes.client.rest import ApiException

from app.api.v1.endpoints import aks_operations, sync_jobs
from app.api.v1.endpoints.aks_operations import _get_service
from app.auth import get_current_user
from app.core.database import get_db
from app.models.database import Permission, Resource, SyncJob
from app.schemas.auth import UserContext, UserRole
from app.services import aks_node_operations as node_ops
from app.services import aks_nodepool_create as np_create
from app.services import aks_nodepool_operations as np_ops
from app.services.aks_operations_service import AKSOperationsService

CLUSTER_ID = "/subscriptions/s1/resourceGroups/rg1/providers/Microsoft.ContainerService/managedClusters/aks-prod-01"
SUBNET_ID = "/subscriptions/s1/resourceGroups/rg1/providers/Microsoft.Network/virtualNetworks/vnet1/subnets/aks-snet"


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
        "vnet_subnet_id": SUBNET_ID,
        "pod_subnet_id": None,
        "enable_encryption_at_host": None,
        "enable_fips": False,
    }
    fields.update(extra)
    return SimpleNamespace(**fields)


def make_cluster(power="Running", **extra):
    fields = {
        "node_resource_group": "MC_rg",
        "power_state": SimpleNamespace(code=power),
        "location": "eastus2",
        "current_kubernetes_version": "1.34.1",
        "kubernetes_version": "1.34",
        "network_profile": SimpleNamespace(network_plugin="azure", network_plugin_mode=None),
        "windows_profile": None,
        "node_provisioning_profile": None,
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
        # A snapshot of existing pools (mutated in place); new SDK models as sent.
        self.updates.append((name, SimpleNamespace(**vars(pool)) if isinstance(pool, SimpleNamespace) else pool))


@pytest.fixture
def azure(monkeypatch):
    agent_pools = FakeAgentPools(
        [
            make_pool("sys", mode="System", count=2),
            make_pool("manual", count=3),
            make_pool("auto", count=5, auto=True, min_count=1, max_count=10),
        ]
    )
    agent_pools.cluster = make_cluster()
    client = SimpleNamespace(
        agent_pools=agent_pools,
        managed_clusters=SimpleNamespace(get=lambda rg, name: agent_pools.cluster),
    )
    monkeypatch.setattr(np_ops, "ContainerServiceClient", lambda credential, subscription: client)
    monkeypatch.setattr(np_create, "ContainerServiceClient", lambda credential, subscription: client)
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


# ── Start / stop ──────────────────────────────────────────────────────


async def test_stop_user_pool(azure):
    result = await service_with().set_node_pool_power(CLUSTER_ID, "manual", start=False)

    assert result["success"] is True
    assert azure.updates[0][0] == "manual"
    assert azure.updates[0][1].power_state.code == "Stopped"


async def test_start_stopped_pool(azure):
    azure.pools["manual"].power_state = SimpleNamespace(code="Stopped")

    result = await service_with().set_node_pool_power(CLUSTER_ID, "manual", start=True)

    assert result["success"] is True
    assert azure.updates[0][1].power_state.code == "Running"


@pytest.mark.parametrize(
    ("pool", "start", "setup", "message"),
    [
        ("sys", False, None, "System pools can't be stopped"),
        ("manual", True, None, "already running"),
        ("manual", False, "cluster-stopped", "Start the cluster"),
        ("manual", False, "scaling", "Wait for it to finish"),
        ("manual", False, "nap", "node auto-provisioning"),
    ],
)
async def test_power_change_is_rejected_before_azure(azure, pool, start, setup, message):
    if setup == "cluster-stopped":
        azure.cluster = make_cluster(power="Stopped")
    elif setup == "scaling":
        azure.pools[pool].provisioning_state = "Scaling"
    elif setup == "nap":
        azure.cluster = make_cluster(node_provisioning_profile=SimpleNamespace(mode="Auto"))

    result = await service_with().set_node_pool_power(CLUSTER_ID, pool, start=start)

    assert result["success"] is False
    assert message in result["error"]
    assert azure.updates == []


async def test_stopped_pool_cannot_be_resized(azure):
    azure.pools["manual"].power_state = SimpleNamespace(code="Stopped")

    result = await service_with().scale_node_pool(CLUSTER_ID, "manual", 5)

    assert "Start it before changing its size" in result["error"]
    assert azure.updates == []


# ── Create ────────────────────────────────────────────────────────────


def make_sku(
    name, *, vcpus=8, memory=32, zones=("1", "2", "3"), ephemeral=True, cache_gb=200, spot=True, restricted=False
):
    caps = {
        "vCPUs": str(vcpus),
        "MemoryGB": str(memory),
        "EphemeralOSDiskSupported": str(ephemeral),
        "CachedDiskBytes": str(cache_gb * 2**30),
        "MaxResourceVolumeMB": "65536",
        "LowPriorityCapable": str(spot),
        "CpuArchitectureType": "x64",
    }
    restrictions = (
        [SimpleNamespace(type="Location", reason_code="NotAvailableForSubscription", restriction_info=None)]
        if restricted
        else []
    )
    return SimpleNamespace(
        resource_type="virtualMachines",
        name=name,
        family="standardDSv3Family",
        capabilities=[SimpleNamespace(name=k, value=v) for k, v in caps.items()],
        location_info=[SimpleNamespace(location="eastus2", zones=list(zones))],
        restrictions=restrictions,
    )


SKUS = [
    make_sku("Standard_D8s_v3"),
    make_sku("Standard_D32s_v3", vcpus=32, memory=128, cache_gb=800),
    make_sku("Standard_D2_v2", zones=("1",), ephemeral=False, spot=False),
    make_sku("Standard_A1", vcpus=1, memory=2),
    make_sku("Standard_M416", vcpus=416, memory=11400, restricted=True),
]


@pytest.fixture
def create_env(azure, monkeypatch):
    azure.pools["sys"].enable_encryption_at_host = True
    usage = {"used": 196, "limit": 4091}
    compute = SimpleNamespace(resource_skus=SimpleNamespace(list=lambda **_kwargs: SKUS))
    network = SimpleNamespace(
        virtual_networks=SimpleNamespace(
            list_usage=lambda rg, vnet: [
                SimpleNamespace(id=SUBNET_ID, current_value=usage["used"], limit=usage["limit"])
            ]
        )
    )

    async def _get_or_fetch(key, ttl, fetch_fn):
        return await fetch_fn(), "live"

    monkeypatch.setattr(np_create, "ComputeManagementClient", lambda credential, subscription: compute)
    monkeypatch.setattr(np_create, "NetworkManagementClient", lambda credential, subscription: network)
    monkeypatch.setattr(np_create.data_cache, "get_or_fetch", _get_or_fetch)
    monkeypatch.setattr(np_create.data_cache, "invalidate_for_nodepools", _noop)
    azure.usage = usage
    return azure


def spec(**overrides):
    base = {
        "name": "rules",
        "mode": "User",
        "os_type": "Linux",
        "os_sku": "Ubuntu",
        "kubernetes_version": "1.34.1",
        "availability_zones": ["1", "2", "3"],
        "spot": False,
        "vm_size": "Standard_D32s_v3",
        "os_disk_type": "Ephemeral",
        "os_disk_size_gb": 512,
        "enable_auto_scaling": True,
        "node_count": None,
        "min_count": 1,
        "max_count": 200,
        "max_pods": 50,
        "max_surge": "33%",
        "subnet_id": None,
        "node_labels": {"nodepool": "ruleengine"},
        "node_taints": ["dedicated=rules:NoSchedule"],
        "tags": {"team": "attcc"},
    }
    return {**base, **overrides}


async def test_create_options_describe_what_azure_allows(create_env):
    options = await service_with().get_node_pool_create_options(CLUSTER_ID)

    sizes = {s["name"]: s for s in options["vm_sizes"]}
    # Sizes under 2 vCPUs and sizes the subscription can't deploy are left out.
    assert set(sizes) == {"Standard_D8s_v3", "Standard_D32s_v3", "Standard_D2_v2"}
    assert sizes["Standard_D32s_v3"]["max_ephemeral_os_disk_gb"] == 800
    assert options["subnets"] == [
        {
            "id": SUBNET_ID,
            "name": "aks-snet",
            "free_ips": 3895,
            "total_ips": 4091,
            "pools": ["sys", "manual", "auto"],
            "pod_subnet": False,
        }
    ]
    assert options["kubernetes_versions"] == ["1.34.1"]
    assert options["inherited"] == {"source_pool": "sys", "encryption_at_host": True, "fips": False}
    assert options["defaults"]["max_surge"] == "10%"
    assert options["power_state"] == "Running"


async def test_create_pool_on_the_clusters_subnet(create_env):
    result = await service_with().create_node_pool(CLUSTER_ID, spec())

    name, pool = create_env.updates[0]
    assert result["success"] is True
    assert name == "rules"
    assert (pool.vm_size, pool.mode, pool.count, pool.min_count, pool.max_count) == (
        "Standard_D32s_v3",
        "User",
        1,
        1,
        200,
    )
    assert pool.vnet_subnet_id == SUBNET_ID
    assert pool.enable_encryption_at_host is True  # follows the system pool
    assert pool.enable_node_public_ip is False
    assert pool.upgrade_settings.max_surge == "33%"
    assert pool.node_taints == ["dedicated=rules:NoSchedule"]
    assert pool.orchestrator_version == "1.34.1"
    assert result["inherited_from"] == "sys"


async def test_create_spot_pool(create_env):
    await service_with().create_node_pool(CLUSTER_ID, spec(spot=True, vm_size="Standard_D8s_v3", os_disk_size_gb=128))

    pool = create_env.updates[0][1]
    assert (pool.scale_set_priority, pool.scale_set_eviction_policy, pool.spot_max_price) == ("Spot", "Delete", -1)


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"name": "manual"}, "already has a node pool named manual"),
        ({"name": "toolongforlinux1"}, "1–12 lowercase"),
        ({"vm_size": "Standard_M416"}, "isn't available to this subscription"),
        ({"vm_size": "Standard_D2_v2", "os_disk_type": None}, "isn't offered in zone(s) 1, 2, 3"),
        ({"os_disk_size_gb": 1024}, "can be at most 800 GiB"),
        ({"mode": "System", "spot": True}, "Spot node pools must be User pools"),
        (
            {"spot": True, "vm_size": "Standard_D2_v2", "availability_zones": ["1"], "os_disk_type": None},
            "can't run as Spot",
        ),
        ({"os_type": "Windows", "name": "win"}, "wasn't created with Windows support"),
        ({"kubernetes_version": "1.35.0"}, "isn't available for new pools"),
        ({"min_count": 5, "max_count": 2}, "can't be greater than the maximum"),
        ({"enable_auto_scaling": False, "node_count": None}, "Set the node count"),
        ({"node_labels": {"kubernetes.azure.com/mode": "user"}}, "reserved by Kubernetes or AKS"),
        ({"node_labels": {"bad key": "x"}}, "isn't a valid Kubernetes label key"),
        ({"node_taints": ["dedicated=rules"]}, "key=value:Effect"),
        ({"node_taints": ["dedicated=rules:Sometimes"]}, "Taint effect must be one of"),
        ({"tags": {"a/b": "x"}}, "Tag name 'a/b'"),
        ({"subnet_id": SUBNET_ID.replace("aks-snet", "db-snet")}, "already use"),
    ],
)
async def test_invalid_create_is_rejected_before_azure(create_env, overrides, message):
    result = await service_with().create_node_pool(CLUSTER_ID, spec(**overrides))

    assert result["success"] is False
    assert message in result["error"]
    assert create_env.updates == []


async def test_create_is_rejected_when_the_subnet_is_out_of_ips(create_env):
    create_env.usage["used"] = 4091 - 40  # 40 free; 1 node with 50 pods needs 51

    result = await service_with().create_node_pool(CLUSTER_ID, spec())

    assert "has 40 free IPs" in result["error"]
    assert create_env.updates == []


async def test_create_on_a_stopped_cluster_is_rejected(create_env):
    create_env.cluster = make_cluster(power="Stopped")

    result = await service_with().create_node_pool(CLUSTER_ID, spec())

    assert "Start it before adding node pools" in result["error"]


async def test_create_without_vm_size_data_still_validates_the_rest(create_env, monkeypatch):
    def _denied(credential, subscription):
        raise PermissionError("AuthorizationFailed")

    monkeypatch.setattr(np_create, "ComputeManagementClient", _denied)

    options = await service_with().get_node_pool_create_options(CLUSTER_ID)
    result = await service_with().create_node_pool(CLUSTER_ID, spec(name="manual"))

    assert options["vm_sizes"] == [] and "enter a size by name" in options["vm_sizes_error"]
    assert "already has a node pool" in result["error"]


# ── API: create and power permissions ─────────────────────────────────


class FakeLifecycleService:
    def __init__(self):
        self.calls: list[tuple] = []

    async def create_node_pool(self, cluster_id, spec):
        self.calls.append(("create", spec["name"], spec["vm_size"]))
        return {"success": True, "nodepool_name": spec["name"], "inherited_from": "sys", "subnet": "aks-snet"}

    async def set_node_pool_power(self, cluster_id, nodepool_name, start):
        self.calls.append(("power", nodepool_name, start))
        return {"success": True, "node_count": 3}

    async def get_node_pool_create_options(self, cluster_id):
        return {"vm_sizes": [], "existing_pools": ["sys"]}


async def _seed(db_session, capability: str) -> None:
    res = Resource(resource_type="operation", resource_name=capability, description="x", is_system=True)
    db_session.add(res)
    await db_session.commit()
    await db_session.refresh(res)
    db_session.add(
        Permission(
            subject_type="role", subject_id="write", resource_id=res.id, permission_type="edit", environment_scope="all"
        )
    )
    await db_session.commit()


CREATE_BODY = {
    "cluster_id": CLUSTER_ID,
    "name": "rules",
    "vm_size": "Standard_D32s_v3",
    "min_count": 1,
    "max_count": 20,
}


async def test_read_user_cannot_create_node_pool(app, db_session):
    await _seed(db_session, "aks_nodepool_create")
    service = FakeLifecycleService()

    async with client(app, db_session, make_user(UserRole.READ), service) as ac:
        resp = await ac.post("/api/v1/aks/nodepools", json=CREATE_BODY)

    assert resp.status_code == 403
    assert service.calls == []


async def test_create_node_pool_is_audited(app, db_session):
    aks_operations._in_memory_audit_log.clear()
    await _seed(db_session, "aks_nodepool_create")
    service = FakeLifecycleService()

    async with client(app, db_session, make_user(UserRole.WRITE), service) as ac:
        resp = await ac.post("/api/v1/aks/nodepools", json=CREATE_BODY)

    entries = [e for e in aks_operations._in_memory_audit_log if e["action"] == "create_nodepool"]
    aks_operations._in_memory_audit_log.clear()
    assert resp.status_code == 200
    assert service.calls == [("create", "rules", "Standard_D32s_v3")]
    assert entries[0]["details"]["summary"] == "Created node pool rules (User, Standard_D32s_v3, autoscaling 1–20)"
    assert entries[0]["details"]["inherited_from"] == "sys"


async def test_stop_node_pool_is_audited(app, db_session):
    aks_operations._in_memory_audit_log.clear()
    await _seed_manage(db_session)
    service = FakeLifecycleService()

    async with client(app, db_session, make_user(UserRole.WRITE), service) as ac:
        resp = await ac.post("/api/v1/aks/nodepools/stop", json={"cluster_id": CLUSTER_ID, "nodepool_name": "manual"})

    entries = [e for e in aks_operations._in_memory_audit_log if e["action"] == "stop_nodepool"]
    aks_operations._in_memory_audit_log.clear()
    assert resp.status_code == 200
    assert service.calls == [("power", "manual", False)]
    assert entries[0]["status"] == "success"


async def test_read_user_cannot_start_node_pool(app, db_session):
    await _seed_manage(db_session)
    service = FakeLifecycleService()

    async with client(app, db_session, make_user(UserRole.READ), service) as ac:
        resp = await ac.post("/api/v1/aks/nodepools/start", json={"cluster_id": CLUSTER_ID, "nodepool_name": "manual"})

    assert resp.status_code == 403
    assert service.calls == []


async def test_read_user_can_view_create_options(app, db_session):
    async with client(app, db_session, make_user(UserRole.READ), FakeLifecycleService()) as ac:
        resp = await ac.get("/api/v1/aks/nodepools/options", params={"cluster_id": CLUSTER_ID})

    assert resp.status_code == 200
    assert resp.json()["existing_pools"] == ["sys"]


# ── Labels and taints ─────────────────────────────────────────────────

SPOT_TAINT = "kubernetes.azure.com/scalesetpriority=spot:NoSchedule"


def test_label_and_taint_update_keeps_aks_managed_entries():
    pool = make_pool(
        "spot",
        node_labels={"kubernetes.azure.com/scalesetpriority": "spot", "nodepool": "batch"},
        node_taints=[SPOT_TAINT, "dedicated=batch:NoSchedule"],
    )

    labels, taints, diff = np_ops.merge_labels_and_taints(
        pool, {"nodepool": "rules", "team": "attcc"}, ["dedicated=rules:NoExecute"]
    )

    assert labels == {"kubernetes.azure.com/scalesetpriority": "spot", "nodepool": "rules", "team": "attcc"}
    assert taints == [SPOT_TAINT, "dedicated=rules:NoExecute"]
    assert diff == {
        "labels_added": ["team"],
        "labels_removed": [],
        "labels_changed": ["nodepool"],
        "taints_added": ["dedicated=rules:NoExecute"],
        "taints_removed": ["dedicated=batch:NoSchedule"],
    }


@pytest.mark.parametrize(
    ("labels", "taints", "message"),
    [
        ({"kubernetes.azure.com/scalesetpriority": "regular"}, [], "managed by AKS"),
        ({}, ["kubernetes.azure.com/mode=x:NoSchedule"], "managed by AKS"),
        ({"topology.kubernetes.io/zone": "1"}, [], "reserved by Kubernetes or AKS"),
        ({"nodepool": "bad value!"}, [], "isn't a valid Kubernetes label value"),
        ({}, ["a=b:NoSchedule", "a=c:NoSchedule"], "is set twice"),
        ({"nodepool": "elk"}, [], "already has these labels and taints"),
    ],
)
def test_invalid_label_or_taint_update(labels, taints, message):
    pool = make_pool(node_labels={"nodepool": "elk", "kubernetes.azure.com/scalesetpriority": "spot"}, node_taints=[])

    with pytest.raises(np_ops.NodePoolChangeError, match=message):
        np_ops.merge_labels_and_taints(pool, labels, taints)


async def test_clearing_labels_and_taints_sends_empty_values(azure):
    azure.pools["manual"].node_taints = ["dedicated=x:NoSchedule"]

    result = await service_with().update_node_pool_labels_taints(CLUSTER_ID, "manual", {}, [])

    sent = azure.updates[0][1]
    assert result["success"] is True
    assert (sent.node_labels, sent.node_taints) == ({}, [])
    assert result["changes"]["labels_removed"] == ["nodepool"]


async def test_labels_of_a_stopped_pool_cannot_change(azure):
    azure.pools["manual"].power_state = SimpleNamespace(code="Stopped")

    result = await service_with().update_node_pool_labels_taints(CLUSTER_ID, "manual", {"nodepool": "x"}, [])

    assert "Start it before changing its labels or taints" in result["error"]
    assert azure.updates == []


class FakeMetadataService:
    def __init__(self):
        self.calls: list[tuple] = []

    async def update_node_pool_labels_taints(self, cluster_id, nodepool_name, labels, taints):
        self.calls.append((nodepool_name, labels, taints))
        return {
            "success": True,
            "changes": {
                "labels_added": ["team"],
                "labels_changed": [],
                "labels_removed": [],
                "taints_added": [],
                "taints_removed": [],
            },
        }


LT_BODY = {"cluster_id": CLUSTER_ID, "nodepool_name": "manual", "node_labels": {"team": "attcc"}, "node_taints": []}


async def test_read_user_cannot_edit_labels_and_taints(app, db_session):
    await _seed_manage(db_session)
    service = FakeMetadataService()

    async with client(app, db_session, make_user(UserRole.READ), service) as ac:
        resp = await ac.post("/api/v1/aks/nodepools/labels-taints", json=LT_BODY)

    assert resp.status_code == 403
    assert service.calls == []


async def test_label_and_taint_edit_is_audited(app, db_session):
    aks_operations._in_memory_audit_log.clear()
    await _seed_manage(db_session)
    service = FakeMetadataService()

    async with client(app, db_session, make_user(UserRole.WRITE), service) as ac:
        resp = await ac.post("/api/v1/aks/nodepools/labels-taints", json=LT_BODY)

    entries = [e for e in aks_operations._in_memory_audit_log if e["action"] == "update_nodepool_labels_taints"]
    aks_operations._in_memory_audit_log.clear()
    assert resp.status_code == 200
    assert service.calls == [("manual", {"team": "attcc"}, [])]
    assert entries[0]["details"]["summary"] == "Updated labels and taints of node pool manual (1 label(s) added)"


async def test_default_os_disk_size_is_left_to_azure(create_env):
    await service_with().create_node_pool(CLUSTER_ID, spec(os_disk_size_gb=None))

    assert create_env.updates[0][1].os_disk_size_gb is None


# ── Node detail ───────────────────────────────────────────────────────


def make_k8s_pod(
    name,
    *,
    node="aks-np-1",
    phase="Running",
    cpu="250m",
    memory="256Mi",
    init_cpu=None,
    owner=("ReplicaSet", "web-abc"),
):
    resources = SimpleNamespace(requests={"cpu": cpu, "memory": memory}, limits={"cpu": "1", "memory": "512Mi"})
    init = (
        [SimpleNamespace(name="init", resources=SimpleNamespace(requests={"cpu": init_cpu}, limits={}))]
        if init_cpu
        else []
    )
    return SimpleNamespace(
        metadata=SimpleNamespace(
            name=name,
            namespace="apps",
            labels={},
            owner_references=[SimpleNamespace(kind=owner[0], name=owner[1], controller=True)],
        ),
        spec=SimpleNamespace(
            node_name=node, containers=[SimpleNamespace(name="app", resources=resources)], init_containers=init
        ),
        status=SimpleNamespace(
            phase=phase,
            pod_ip="10.0.0.5",
            start_time=datetime(2026, 10, 1, tzinfo=UTC),
            qos_class="Burstable",
            container_statuses=[SimpleNamespace(name="app", ready=phase == "Running", restart_count=1, state=None)],
            conditions=None,
            reason=None,
            init_container_statuses=None,
        ),
    )


def make_k8s_node():
    return SimpleNamespace(
        metadata=SimpleNamespace(
            name="aks-np-1",
            labels={
                "kubernetes.azure.com/agentpool": "np",
                "topology.kubernetes.io/zone": "eastus2-2",
                "node.kubernetes.io/instance-type": "Standard_B2ms",
            },
            annotations={},
            creation_timestamp=datetime(2026, 10, 1, tzinfo=UTC),
        ),
        spec=SimpleNamespace(
            unschedulable=False,
            taints=[SimpleNamespace(key="CriticalAddonsOnly", value="true", effect="NoSchedule")],
            provider_id="azure:///x",
            pod_cidr=None,
        ),
        status=SimpleNamespace(
            conditions=[
                SimpleNamespace(
                    type="Ready", status="True", reason="KubeletReady", message="ok", last_transition_time=None
                ),
                SimpleNamespace(
                    type="MemoryPressure", status="False", reason=None, message=None, last_transition_time=None
                ),
            ],
            allocatable={"cpu": "1900m", "memory": "7Gi", "pods": "30", "ephemeral-storage": "100Gi"},
            capacity={"cpu": "2", "memory": "8Gi", "pods": "30"},
            node_info=SimpleNamespace(
                os_image="Ubuntu 22.04.5 LTS",
                kernel_version="5.15.0",
                container_runtime_version="containerd://1.7",
                kubelet_version="v1.36.3",
                kube_proxy_version="v1.36.3",
                architecture="amd64",
                operating_system="linux",
            ),
            addresses=[SimpleNamespace(type="InternalIP", address="10.224.0.4")],
        ),
    )


def test_node_detail_counts_what_the_scheduler_counts():
    pods = [
        make_k8s_pod("web-1"),
        make_k8s_pod("migrate-1", init_cpu="1"),  # init container needs more than the app
        make_k8s_pod("job-1", phase="Succeeded", cpu="4"),  # finished: holds nothing
    ]

    detail = node_ops.serialize_node_detail(make_k8s_node(), pods, events=[], usage=None)

    assert detail["ready"] is True and detail["pool"] == "np"
    assert detail["taints"] == ["CriticalAddonsOnly=true:NoSchedule"]
    assert detail["allocatable"]["cpu_m"] == 1900
    assert detail["allocated"]["pods"] == 2
    assert detail["allocated"]["cpu_request_m"] == 1250
    assert detail["allocated"]["cpu_request_pct"] == 65.8
    pod = next(p for p in detail["pods"] if p["pod_name"] == "migrate-1")
    assert (pod["cpu_request_m"], pod["memory_request_bytes"], pod["owner_kind"]) == (1000, 256 * 2**20, "ReplicaSet")
    assert next(p for p in detail["pods"] if p["pod_name"] == "job-1")["terminated"] is True


async def test_node_detail_without_metrics_server():
    class Core:
        api_client = None

        def read_node(self, name, **kwargs):
            return make_k8s_node()

        def list_pod_for_all_namespaces(self, **kwargs):
            assert kwargs["field_selector"] == "spec.nodeName=aks-np-1"
            return SimpleNamespace(items=[make_k8s_pod("web-1")])

        def list_event_for_all_namespaces(self, **kwargs):
            raise ApiException(status=403, reason="Forbidden")

    svc = service_with(Core())

    async def _no_metrics(core_v1, name, allocatable):
        return None

    svc._node_usage = _no_metrics
    detail = await svc.get_node_detail(CLUSTER_ID, "aks-np-1")

    assert detail["usage"] is None
    assert detail["events"] == []
    assert [p["pod_name"] for p in detail["pods"]] == ["web-1"]


class FakeNodeService:
    async def get_node_detail(self, cluster_id, name):
        raise ApiException(status=404, reason="Not Found")


async def test_missing_node_is_404(app, db_session):
    res = Resource(resource_type="operation", resource_name="aks_pod_view", description="x", is_system=True)
    db_session.add(res)
    await db_session.commit()
    await db_session.refresh(res)
    db_session.add(
        Permission(
            subject_type="role", subject_id="read", resource_id=res.id, permission_type="view", environment_scope="all"
        )
    )
    await db_session.commit()

    async with client(app, db_session, make_user(UserRole.READ), FakeNodeService()) as ac:
        resp = await ac.get("/api/v1/aks/nodes/detail", params={"cluster_id": CLUSTER_ID, "name": "aks-np-9"})

    assert resp.status_code == 404
    assert "aks-np-9" in resp.json()["detail"]
