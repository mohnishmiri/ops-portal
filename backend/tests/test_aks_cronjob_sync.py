from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.services.aks_operations_service import AKSOperationsService


class _WriteDbSession:
    def __init__(self) -> None:
        self.statements = []
        self.added = []
        self.commit_calls = 0
        self.rollback_calls = 0

    async def execute(self, statement):
        self.statements.append(statement)
        return

    def add(self, record) -> None:
        self.added.append(record)

    async def commit(self) -> None:
        self.commit_calls += 1

    async def rollback(self) -> None:
        self.rollback_calls += 1


class _FakeScalarResult:
    def __init__(self, item) -> None:
        self._item = item

    def first(self):
        return self._item


class _FakeExecuteResult:
    def __init__(self, item) -> None:
        self._item = item

    def scalars(self):
        return _FakeScalarResult(self._item)


class _DetailDbSession:
    def __init__(self, item) -> None:
        self._item = item
        self.statements = []

    async def execute(self, statement):
        self.statements.append(statement)
        return _FakeExecuteResult(self._item)


@pytest.mark.anyio
async def test_sync_cronjobs_to_db_scopes_delete_to_namespace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cluster_id = (
        "/subscriptions/sub-1/resourceGroups/rg-1/providers/Microsoft.ContainerService/managedClusters/cluster-1"
    )
    namespace = "team-a"
    fake_db = _WriteDbSession()
    service = AKSOperationsService(fake_db)

    monkeypatch.setattr(
        service,
        "_fetch_cronjobs_live",
        AsyncMock(
            return_value=[
                {
                    "name": "nightly-job",
                    "namespace": namespace,
                    "schedule": "0 0 * * *",
                    "suspended": False,
                    "last_schedule_time": "2026-04-02T05:00:00Z",
                    "active_count": 0,
                    "created_at": "2026-04-01T00:00:00Z",
                }
            ]
        ),
    )

    result = await service.sync_cronjobs_to_db(cluster_id, namespace)

    compiled = fake_db.statements[0].compile()

    assert f"{cluster_id}/cronjob/{namespace}/%" in str(compiled.params)
    assert fake_db.added[0].resource_id == f"{cluster_id}/cronjob/{namespace}/nightly-job"
    assert fake_db.commit_calls == 1
    assert result["synced_count"] == 1
    assert result["db_saved"] is True


@pytest.mark.anyio
async def test_get_cronjob_detail_falls_back_to_db_when_live_fetch_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cluster_id = (
        "/subscriptions/sub-1/resourceGroups/rg-1/providers/Microsoft.ContainerService/managedClusters/cluster-1"
    )
    namespace = "automation"
    name = "aks-checksum-cron"

    record = SimpleNamespace(
        resource_details={
            "name": name,
            "namespace": namespace,
            "schedule": "0 2 * * *",
            "suspended": False,
            "concurrency_policy": "Forbid",
            "last_schedule_time": "2026-04-02T05:00:00Z",
            "last_successful_time": "2026-04-02T05:05:00Z",
            "active_count": 0,
            "image": "registry/aks-checksum:1.0.0",
            "created_at": "2026-04-01T00:00:00Z",
            "_cluster_id": cluster_id,
        },
        last_sync=datetime(2026, 4, 2, 9, 57, 54),
    )
    fake_db = _DetailDbSession(record)
    service = AKSOperationsService(fake_db)

    monkeypatch.setattr(
        service,
        "_fetch_cronjob_detail_live",
        AsyncMock(side_effect=RuntimeError("kubernetes api unavailable")),
    )

    result = await service.get_cronjob_detail(cluster_id, namespace, name, bypass_cache=True)

    assert result["name"] == name
    assert result["namespace"] == namespace
    assert result["schedule"] == "0 2 * * *"
    assert result["detail_source"] == "db"
    assert result["labels"] == {}
    assert result["resources"] == {"requests": {}, "limits": {}}
    assert result["configmap_refs"] == []
    assert result["volume_mounts"] == []
    assert result["env_configmap_refs"] == []
    assert result["_last_sync"] == "2026-04-02T09:57:54"


class _FailingCoreV1:
    def read_namespaced_config_map(self, name: str, namespace: str):
        raise RuntimeError(f"configmap {namespace}/{name} not reachable")


@pytest.mark.anyio
async def test_get_configmap_detail_returns_placeholder_when_live_fetch_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cluster_id = (
        "/subscriptions/sub-1/resourceGroups/rg-1/providers/Microsoft.ContainerService/managedClusters/cluster-1"
    )
    service = AKSOperationsService(db_session=None)

    monkeypatch.setattr(
        service,
        "_get_k8s_clients",
        AsyncMock(return_value=(None, _FailingCoreV1(), None)),
    )

    result = await service.get_configmap_detail(cluster_id, "kube-system", "aks-checksum-script")

    assert result["name"] == "aks-checksum-script"
    assert result["namespace"] == "kube-system"
    assert result["data"] == {}
    assert result["detail_source"] == "unavailable"
    assert "not reachable" in result["data_unavailable_reason"]


@pytest.mark.anyio
async def test_get_secret_detail_uses_db_for_masked_view(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cluster_id = (
        "/subscriptions/sub-1/resourceGroups/rg-1/providers/Microsoft.ContainerService/managedClusters/cluster-1"
    )
    namespace = "default"
    name = "app-credentials"

    record = SimpleNamespace(
        resource_details={
            "name": name,
            "namespace": namespace,
            "type": "Opaque",
            "keys": ["aaf_id", "aaf_password", "keyfile"],
            "labels": {"app": "demo"},
            "created_at": "2026-04-01T00:00:00Z",
        },
        last_sync=datetime(2026, 4, 2, 9, 57, 54),
    )
    fake_db = _DetailDbSession(record)
    service = AKSOperationsService(fake_db)

    live_fetch = AsyncMock(side_effect=AssertionError("live fetch should not run for masked secret detail"))
    monkeypatch.setattr(service, "_fetch_secret_detail_live", live_fetch)

    result = await service.get_secret_detail(cluster_id, namespace, name, reveal=False)

    assert result["detail_source"] == "db"
    assert result["keys"] == ["aaf_id", "aaf_password", "keyfile"]
    assert result["data"] == {
        "aaf_id": "***",
        "aaf_password": "***",
        "keyfile": "***",
    }
    live_fetch.assert_not_called()


@pytest.mark.anyio
async def test_get_pod_metrics_from_db_normalizes_pod_name(monkeypatch: pytest.MonkeyPatch) -> None:
    cluster_id = (
        "/subscriptions/sub-1/resourceGroups/rg-1/providers/Microsoft.ContainerService/managedClusters/cluster-1"
    )
    service = AKSOperationsService(db_session=None)

    monkeypatch.setattr(
        service,
        "_get_inventory_from_db",
        AsyncMock(
            return_value=[
                {
                    "name": "api-pod-1",
                    "namespace": "default",
                    "phase": "Running",
                    "total_cpu_millicores": 100,
                    "total_memory_mb": 256,
                }
            ]
        ),
    )

    pods = await service.get_pod_metrics_from_db(cluster_id)

    assert len(pods) == 1
    assert pods[0]["pod_name"] == "api-pod-1"
    assert pods[0]["namespace"] == "default"


@pytest.mark.anyio
async def test_sync_pods_to_db_uses_full_metrics(monkeypatch: pytest.MonkeyPatch) -> None:
    cluster_id = (
        "/subscriptions/sub-1/resourceGroups/rg-1/providers/Microsoft.ContainerService/managedClusters/cluster-1"
    )
    fake_db = _WriteDbSession()
    service = AKSOperationsService(fake_db)
    metrics = [
        {
            "pod_name": "worker-0",
            "namespace": "team-a",
            "phase": "Running",
            "total_cpu_millicores": 50,
            "total_memory_mb": 128,
            "containers": [],
        }
    ]

    monkeypatch.setattr(service, "_fetch_pod_metrics_live", AsyncMock(return_value=metrics))
    sync_inventory = AsyncMock(return_value={"synced_count": 1, "db_saved": True})
    monkeypatch.setattr(service, "_sync_inventory", sync_inventory)

    result = await service.sync_pods_to_db(cluster_id, "team-a")

    service._fetch_pod_metrics_live.assert_awaited_once_with(cluster_id, "team-a")
    sync_inventory.assert_awaited_once()
    synced_items = sync_inventory.await_args.args[3]
    assert synced_items[0]["name"] == "worker-0"
    assert synced_items[0]["pod_name"] == "worker-0"
    assert result["synced_count"] == 1


def test_k8s_updated_at_prefers_managed_fields_time() -> None:
    from app.services.aks_resource_operations import _k8s_updated_at

    metadata = SimpleNamespace(
        creation_timestamp=datetime(2026, 4, 1, 0, 0, 0),
        managed_fields=[
            SimpleNamespace(time=datetime(2026, 4, 1, 8, 0, 0)),
            SimpleNamespace(time=datetime(2026, 4, 2, 12, 30, 0)),
        ],
    )

    assert _k8s_updated_at(metadata) == "2026-04-02T12:30:00"

