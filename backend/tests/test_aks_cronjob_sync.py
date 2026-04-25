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
