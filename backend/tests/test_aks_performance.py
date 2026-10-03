"""
AKS request cost: namespaces are cached instead of read live on every poll, and
Kubernetes clients are built once per cluster for the whole process rather than
once per request (each build is an ARM credential call plus an AAD token).
"""

import asyncio
import time
from types import SimpleNamespace

import pytest

from app.core.db_cache import cache_manager
from app.services.aks_operations_service import AKSOperationsService

CLUSTER = "/subscriptions/s1/resourceGroups/rg1/providers/Microsoft.ContainerService/managedClusters/aks-01"


@pytest.fixture
def memory_cache(monkeypatch):
    """Stand-in for the DB-backed page cache (not connected in unit tests)."""
    store: dict[str, str] = {}

    async def get_cached(key):
        return store.get(key)

    async def set_cached(key, value, ttl=None):
        store[key] = value

    monkeypatch.setattr(cache_manager, "get_cached", get_cached)
    monkeypatch.setattr(cache_manager, "set_cached", set_cached)
    return store


class FakeCore:
    def __init__(self, fail: bool = False):
        self.calls: list[dict] = []
        self.fail = fail

    def list_namespace(self, **kwargs):
        self.calls.append(kwargs)
        if self.fail:
            raise ConnectionError("Failed to resolve 'aks-01.privatelink.eastus2.azmk8s.io'")
        names = ("kube-system", "apps")
        return SimpleNamespace(items=[SimpleNamespace(metadata=SimpleNamespace(name=n)) for n in names])


def request_service(core: FakeCore) -> AKSOperationsService:
    """A service as each request builds it, with the cluster client stubbed."""
    svc = AKSOperationsService.__new__(AKSOperationsService)
    svc.db = None

    async def _clients(_cluster_id):
        return (None, core, None)

    svc._get_k8s_clients = _clients
    return svc


# ── Namespaces ────────────────────────────────────────────────────────


async def test_namespaces_are_cached_across_requests(memory_cache):
    core = FakeCore()

    first = await request_service(core).list_namespaces_for_cluster(CLUSTER)
    second = await request_service(core).list_namespaces_for_cluster(CLUSTER)

    assert first == second == ["apps", "kube-system"]
    assert len(core.calls) == 1
    # A hung cluster must fail over quickly instead of holding the request.
    assert core.calls[0]["_request_timeout"] == (5, 15)


async def test_refresh_reads_namespaces_live(memory_cache):
    core = FakeCore()
    await request_service(core).list_namespaces_for_cluster(CLUSTER)

    await request_service(core).list_namespaces_for_cluster(CLUSTER, refresh=True)

    assert len(core.calls) == 2


async def test_unreachable_cluster_is_not_retried_on_every_poll(memory_cache):
    core = FakeCore(fail=True)

    for _ in range(3):
        assert await request_service(core).list_namespaces_for_cluster(CLUSTER) == []

    assert len(core.calls) == 1


# ── Kubernetes client cache ───────────────────────────────────────────


@pytest.fixture
def client_builds(monkeypatch):
    builds: list[str] = []

    async def fake_build(self, cluster_id):
        builds.append(cluster_id)
        await asyncio.sleep(0.01)  # let concurrent callers pile up on the lock
        return ("apps", "core", "batch")

    monkeypatch.setattr(AKSOperationsService, "_build_k8s_clients", fake_build)
    monkeypatch.setattr(AKSOperationsService, "_k8s_clients", {})
    monkeypatch.setattr(AKSOperationsService, "_k8s_clients_ts", {})
    monkeypatch.setattr(AKSOperationsService, "_k8s_client_locks", {})
    return builds


def new_request_service() -> AKSOperationsService:
    return AKSOperationsService.__new__(AKSOperationsService)


async def test_clients_are_built_once_per_cluster_across_requests(client_builds):
    results = await asyncio.gather(*(new_request_service()._get_k8s_clients(CLUSTER) for _ in range(5)))
    later = await new_request_service()._get_k8s_clients(CLUSTER)

    assert client_builds == [CLUSTER]
    assert all(r == ("apps", "core", "batch") for r in results)
    assert later == ("apps", "core", "batch")


async def test_expired_clients_are_rebuilt(client_builds):
    await new_request_service()._get_k8s_clients(CLUSTER)
    AKSOperationsService._k8s_clients_ts[CLUSTER] = time.time() - AKSOperationsService._K8S_CLIENT_TTL - 1

    await new_request_service()._get_k8s_clients(CLUSTER)

    assert client_builds == [CLUSTER, CLUSTER]
