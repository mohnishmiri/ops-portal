"""
CPU and memory usage across the AKS views: live usage comes from metrics-server
(never from requests), "unavailable" is None rather than zero, and cluster
utilisation comes from AKS's Azure Monitor platform metrics.
"""

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from app.services import aks_nodepool_operations as np_ops
from app.services import k8s_usage
from app.services.aks_detail_operations import attach_container_usage
from app.services.aks_operations_service import AKSOperationsService, apply_pod_metrics_usage

METRICS_ITEMS = [
    {
        "metadata": {"namespace": "apps", "name": "web-1"},
        "timestamp": "2026-10-11T00:00:00Z",
        "containers": [
            {"name": "app", "usage": {"cpu": "12m", "memory": "200Mi"}},
            {"name": "sidecar", "usage": {"cpu": "3m", "memory": "56Mi"}},
        ],
    }
]


class FakeCustomObjects:
    def __init__(self, fail: Exception | None = None):
        self.fail = fail
        self.calls: list[tuple] = []

    def list_namespaced_custom_object(self, group, version, namespace, plural, **kwargs):
        self.calls.append(("namespaced", namespace, plural))
        if self.fail:
            raise self.fail
        return {"items": METRICS_ITEMS}

    def list_cluster_custom_object(self, group, version, plural, **kwargs):
        self.calls.append(("cluster", plural))
        if self.fail:
            raise self.fail
        return {"items": METRICS_ITEMS}

    def get_namespaced_custom_object(self, group, version, namespace, plural, name, **kwargs):
        self.calls.append(("pod", namespace, name))
        if self.fail:
            raise self.fail
        return METRICS_ITEMS[0]


@pytest.fixture
def metrics(monkeypatch):
    holder = {"api": FakeCustomObjects()}
    monkeypatch.setattr(k8s_usage.k8s_client, "CustomObjectsApi", lambda api_client: holder["api"])
    return holder


CORE = SimpleNamespace(api_client=None)


async def test_pod_usage_sums_containers(metrics):
    usage = await k8s_usage.read_pod_usage(CORE, "apps")

    sample = usage[("apps", "web-1")]
    assert (sample["cpu_m"], sample["memory_bytes"]) == (15, 256 * 2**20)
    assert sample["containers"]["sidecar"] == {"cpu_m": 3, "memory_bytes": 56 * 2**20}
    assert metrics["api"].calls == [("namespaced", "apps", "pods")]


async def test_missing_metrics_server_is_unavailable_not_zero(metrics):
    metrics["api"] = FakeCustomObjects(fail=k8s_usage.ApiException(status=503, reason="ServiceUnavailable"))

    usage = await k8s_usage.read_pod_usage(CORE)
    rows = k8s_usage.attach_pod_usage([{"namespace": "apps", "pod_name": "web-1"}], usage)

    assert usage is None
    assert rows[0]["cpu_usage_m"] is None and rows[0]["memory_usage_bytes"] is None


async def test_new_pod_without_a_sample_yet(metrics):
    metrics["api"] = FakeCustomObjects(fail=k8s_usage.ApiException(status=404, reason="NotFound"))

    assert await k8s_usage.read_pod_usage(CORE, "apps", "just-started") == {}


def test_pod_metrics_rows_show_usage_not_requests():
    row = {
        "namespace": "apps",
        "pod_name": "web-1",
        "total_cpu_request": 500.0,
        "total_cpu_millicores": 0.0,
        "total_memory_mb": 0.0,
        "containers": [
            {"name": "app", "cpu_millicores": None, "memory_mb": None},
            {"name": "sidecar", "cpu_millicores": None, "memory_mb": None},
        ],
    }
    usage = {("apps", "web-1"): k8s_usage._usage_record(METRICS_ITEMS[0])}

    apply_pod_metrics_usage(row, usage)
    assert (row["total_cpu_millicores"], row["total_memory_mb"], row["usage_available"]) == (15, 256.0, True)
    assert row["containers"][0]["cpu_millicores"] == 12

    other = {**row, "pod_name": "web-2", "containers": [{"name": "app", "cpu_millicores": None, "memory_mb": None}]}
    apply_pod_metrics_usage(other, usage)
    assert (other["total_cpu_millicores"], other["usage_available"]) == (None, False)
    assert other["containers"][0]["cpu_millicores"] is None


def test_pod_detail_containers_compare_usage_with_requests():
    detail = {
        "containers": [
            {"name": "app", "cpu_request": "250m", "cpu_limit": "1", "memory_request": "256Mi", "memory_limit": ""},
            {"name": "sidecar", "cpu_request": "", "cpu_limit": "", "memory_request": "", "memory_limit": ""},
        ]
    }

    attach_container_usage(detail, {("apps", "web-1"): k8s_usage._usage_record(METRICS_ITEMS[0])}, ("apps", "web-1"))

    app = detail["containers"][0]
    assert (detail["cpu_usage_m"], detail["usage_available"]) == (15, True)
    assert (app["cpu_usage_m"], app["cpu_request_m"], app["cpu_limit_m"], app["memory_limit_bytes"]) == (
        12,
        250,
        1000,
        0,
    )
    attach_container_usage(detail, None, ("apps", "web-1"))
    assert detail["usage_available"] is False and detail["containers"][0]["cpu_usage_m"] is None


def _point(minute, average):
    return SimpleNamespace(
        time_stamp=datetime(2026, 10, 11, 0, minute, tzinfo=UTC), average=average, maximum=None, minimum=None
    )


class FakeMonitor:
    def __init__(self, fail_for: str | None = None):
        self.fail_for = fail_for
        self.metrics = SimpleNamespace(list=self._list)

    def _list(self, resource_id, **kwargs):
        if self.fail_for and self.fail_for in resource_id:
            raise ValueError("AuthorizationFailed")
        return SimpleNamespace(
            value=[
                SimpleNamespace(
                    name=SimpleNamespace(value=np_ops.CLUSTER_CPU_METRIC),
                    timeseries=[SimpleNamespace(data=[_point(0, 7.1), _point(5, 7.5), _point(10, None)])],
                ),
                SimpleNamespace(
                    name=SimpleNamespace(value=np_ops.CLUSTER_MEMORY_METRIC),
                    timeseries=[SimpleNamespace(data=[_point(0, 26.0), _point(5, 27.04)])],
                ),
            ]
        )


async def test_cluster_utilisation_from_aks_platform_metrics(monkeypatch):
    monkeypatch.setattr(
        np_ops, "MonitorManagementClient", lambda credential, subscription: FakeMonitor(fail_for="broken")
    )
    svc = AKSOperationsService.__new__(AKSOperationsService)
    svc.credential = None
    clusters = [
        {"name": "uat", "id": "/subs/s/clusters/uat", "subscription_id": "s", "power_state": "Running"},
        {"name": "broken", "id": "/subs/s/clusters/broken", "subscription_id": "s", "power_state": "Running"},
        {"name": "dr", "id": "/subs/s/clusters/dr", "subscription_id": "s", "power_state": "Stopped"},
    ]

    await svc.attach_cluster_utilisation(clusters)

    assert clusters[0]["utilisation"] == {
        "cpu_pct": 7.5,
        "memory_pct": 27.0,
        "at": "2026-10-11T00:05:00+00:00",
        "source": "azure-monitor",
    }
    assert clusters[1]["utilisation"] is None  # one failure doesn't hide the others
    assert clusters[2]["utilisation"] is None  # a stopped cluster reports nothing


# ── Cluster / node utilisation history (AKS platform metrics) ─────────


def _series(dim, points):
    return SimpleNamespace(
        metadatavalues=[SimpleNamespace(name=SimpleNamespace(value="nodepool"), value=dim)] if dim else [], data=points
    )


def _hp(minute, average, maximum):
    return SimpleNamespace(time_stamp=datetime(2026, 10, 11, 0, minute, tzinfo=UTC), average=average, maximum=maximum)


class FakeHistoryMonitor:
    def __init__(self):
        self.calls: list[dict] = []
        self.metrics = SimpleNamespace(list=self._list)

    def _list(self, resource_id, **kwargs):
        self.calls.append(kwargs)
        split = kwargs.get("filter") == "nodepool eq '*'"
        dims = [("sys", 30.0, 40.0), ("user", 5.0, 9.0)] if split else [("", 12.0, 98.0)]

        def metric(name, offset):
            return SimpleNamespace(
                name=SimpleNamespace(value=name),
                timeseries=[
                    _series(d, [_hp(0, avg + offset, mx), _hp(15, avg + offset + 1, mx)]) for d, avg, mx in dims
                ],
            )

        return SimpleNamespace(value=[metric(np_ops.CLUSTER_CPU_METRIC, 0), metric(np_ops.CLUSTER_MEMORY_METRIC, 20)])


@pytest.fixture
def history(monkeypatch):
    monitor = FakeHistoryMonitor()
    monkeypatch.setattr(np_ops, "MonitorManagementClient", lambda credential, subscription: monitor)

    async def _get_or_fetch(key, ttl, fetch_fn):
        return await fetch_fn(), "live"

    monkeypatch.setattr(np_ops.data_cache, "get_or_fetch", _get_or_fetch)
    svc = AKSOperationsService.__new__(AKSOperationsService)
    svc.credential = None
    return svc, monitor


CLUSTER = "/subscriptions/s1/resourceGroups/rg1/providers/Microsoft.ContainerService/managedClusters/aks-01"


async def test_cluster_history_marks_the_busiest_node_as_peak(history):
    svc, monitor = history

    result = await svc.get_cluster_metrics(CLUSTER, "24h")

    assert result["scope"] == "cluster" and result["interval"] == "PT15M"
    assert result["cpu"] == {"current": 13.0, "average": 12.5, "peak": 98.0}
    assert result["memory"]["current"] == 33.0
    assert monitor.calls[0]["filter"] is None


async def test_node_history_filters_to_that_node(history):
    svc, monitor = history

    result = await svc.get_cluster_metrics(CLUSTER, "6h", node="aks-np1-123-vmss00000b")

    assert result["scope"] == "node" and result["node"] == "aks-np1-123-vmss00000b"
    assert monitor.calls[0]["filter"] == "node eq 'aks-np1-123-vmss00000b'"
    assert monitor.calls[0]["interval"] == "PT5M"


async def test_history_split_per_node_pool(history):
    svc, _monitor = history

    result = await svc.get_cluster_metrics(CLUSTER, "7d", split_by_pool=True)

    assert result["scope"] == "nodepools"
    assert [(p["name"], p["cpu"]["current"], p["memory"]["current"]) for p in result["pools"]] == [
        ("sys", 31.0, 51.0),
        ("user", 6.0, 26.0),
    ]


class FakeClusterMetricsService:
    def __init__(self):
        self.calls: list[tuple] = []

    async def get_cluster_metrics(self, cluster_id, range_key, node=None, split_by_pool=False):
        self.calls.append((range_key, node, split_by_pool))
        return {"scope": "cluster", "range": range_key, "series": []}


async def test_cluster_metrics_endpoint_validates_its_filter(app, db_session):

    from httpx import ASGITransport, AsyncClient

    from app.api.v1.endpoints.aks_operations import _get_service
    from app.auth import get_current_user
    from app.core.database import get_db
    from app.schemas.auth import UserContext, UserRole

    service = FakeClusterMetricsService()
    user = UserContext(
        user_id="u",
        object_id="00000000-0000-0000-0000-000000000000",
        display_name="u",
        email="u@example.com",
        roles=[UserRole.READ],
        raw_roles=["read"],
        tenant_id="t",
        allowed_subscriptions=[],
    )

    async def _db():
        yield db_session

    app.dependency_overrides[get_db] = _db
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[_get_service] = lambda: service
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            ok = await ac.get(
                "/api/v1/aks/cluster-metrics", params={"cluster_id": CLUSTER, "range": "7d", "split": "nodepool"}
            )
            injected = await ac.get(
                "/api/v1/aks/cluster-metrics", params={"cluster_id": CLUSTER, "node": "x' or node eq '*"}
            )
            both = await ac.get(
                "/api/v1/aks/cluster-metrics", params={"cluster_id": CLUSTER, "node": "aks-1", "split": "nodepool"}
            )
    finally:
        app.dependency_overrides.clear()

    assert ok.status_code == 200 and service.calls == [("7d", None, True)]
    assert injected.status_code == 422  # a node name can't smuggle OData into the filter
    assert both.status_code == 400
