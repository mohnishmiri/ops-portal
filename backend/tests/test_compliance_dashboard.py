"""Compliance dashboard: queries run against a real (SQLite) database."""

import asyncio
from datetime import datetime, timedelta

import pytest
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.ext.compiler import compiles

from app.api.v1.endpoints import compliance as compliance_endpoints
from app.core.subscription_scope import (
    get_active_scoped_subscription_ids,
    reset_scoped_subscription_ids,
    set_scoped_subscription_ids,
)
from app.models.database import AKSPodChecksum, AKSPodDrift, SynapsePipelineChecksum, SynapsePipelineDrift
from app.schemas.compliance import ExcelExportRequest
from app.services import compliance_excel_service as excel_service
from app.services import compliance_sync_service
from app.services.compliance_excel_service import ExportScope
from app.services.compliance_service import ComplianceService
from app.services.compliance_sync_service import ComplianceSyncService


@compiles(JSONB, "sqlite")
def _jsonb_as_json_on_sqlite(_type, _compiler, **_kw):
    return "JSON"


_TABLES = (SynapsePipelineChecksum, SynapsePipelineDrift, AKSPodChecksum, AKSPodDrift)

NOW = datetime.utcnow().replace(microsecond=0)
START = NOW - timedelta(days=30)


def _cluster_id(sub: str, name: str) -> str:
    return f"/subscriptions/{sub}/resourceGroups/rg/providers/Microsoft.ContainerService/managedClusters/{name}"


@pytest.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        for model in _TABLES:
            await conn.run_sync(lambda c, m=model: m.__table__.create(c))
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as db:
        yield db
    await engine.dispose()


def _pipeline(workspace: str, pipeline: str, when: datetime, sub: str = "sub-1") -> SynapsePipelineChecksum:
    return SynapsePipelineChecksum(
        snapshot_date=when,
        subscription_id=sub,
        workspace_name=workspace,
        workspace_id=f"/subscriptions/{sub}/workspaces/{workspace}",
        pipeline_name=pipeline,
        checksum_sha256="a" * 64,
        pipeline_definition={"large": "payload"},
    )


def _pod(cluster: str, namespace: str, pod: str, when: datetime, sub: str = "sub-1") -> AKSPodChecksum:
    return AKSPodChecksum(
        snapshot_date=when,
        cluster_id=_cluster_id(sub, cluster),
        cluster_name=cluster,
        namespace=namespace,
        pod_name=pod,
        checksum_sha256="b" * 64,
    )


def _pipeline_drift(workspace: str, pipeline: str, when: datetime, drift_type: str = "modified"):
    return SynapsePipelineDrift(
        detection_date=when,
        workspace_id=f"/subscriptions/sub-1/workspaces/{workspace}",
        workspace_name=workspace,
        pipeline_name=pipeline,
        drift_type=drift_type,
        acknowledged=False,
    )


def _pod_drift(cluster: str, namespace: str, pod: str, when: datetime, severity: str = "high", sub: str = "sub-1"):
    return AKSPodDrift(
        detection_date=when,
        cluster_id=_cluster_id(sub, cluster),
        cluster_name=cluster,
        namespace=namespace,
        pod_name=pod,
        drift_type="image_change",
        drift_category="container_image",
        severity=severity,
        acknowledged=False,
    )


async def _build(db: AsyncSession, subscription_ids=("sub-1",)) -> dict:
    return await ComplianceService(db)._build_dashboard_from_checksum_snapshots(
        subscription_ids=list(subscription_ids),
        start_date=START,
    )


@pytest.mark.anyio
async def test_each_workspace_uses_its_own_latest_snapshot(session):
    # Verification runs one workspace at a time, so each has its own snapshot_date.
    older, newer = NOW - timedelta(hours=6), NOW - timedelta(hours=1)
    session.add_all(
        [
            _pipeline("ws-a", "stale-pipe", NOW - timedelta(days=3)),
            *[_pipeline("ws-a", f"pipe-{i}", older) for i in range(4)],
            *[_pipeline("ws-b", f"pipe-{i}", newer) for i in range(2)],
            _pipeline("ws-other-sub", "pipe-0", newer, sub="sub-2"),
        ]
    )
    await session.commit()

    result = await _build(session)

    names = {r["name"] for r in result["resources"]}
    assert names == {"ws-a", "ws-b"}
    assert result["synapse_summary"]["total_pipelines"] == 6
    assert result["total_resources"] == 2


@pytest.mark.anyio
async def test_each_cluster_namespace_uses_its_own_latest_snapshot(session):
    # A namespace-scoped AKS run must not hide the cluster's other namespaces.
    session.add_all(
        [
            *[_pod("aks-a", "ns-1", f"pod-{i}", NOW - timedelta(hours=5)) for i in range(3)],
            *[_pod("aks-a", "ns-2", f"pod-{i}", NOW - timedelta(hours=1)) for i in range(2)],
            _pod("aks-a", "ns-2", "old-pod", NOW - timedelta(days=2)),
            _pod("aks-elsewhere", "ns-1", "pod-0", NOW, sub="sub-2"),
        ]
    )
    await session.commit()

    result = await _build(session)

    assert result["aks_summary"]["clusters"] == 1
    assert result["aks_summary"]["total_pods"] == 5


@pytest.mark.anyio
async def test_summaries_scores_and_resources_agree(session):
    snap, drift_at = NOW - timedelta(hours=1), NOW - timedelta(days=1)
    session.add_all(
        [
            *[_pipeline("ws-a", f"pipe-{i}", snap) for i in range(10)],
            *[_pipeline_drift("ws-a", f"pipe-{i}", drift_at) for i in range(3)],
            *[_pod("aks-a", "ns", f"pod-{i}", snap) for i in range(20)],
            *[_pod_drift("aks-a", "ns", f"pod-{i}", drift_at) for i in range(5)],
        ]
    )
    await session.commit()

    result = await _build(session)

    assert result["synapse_summary"] == {"total_pipelines": 10, "drifted_pipelines": 3, "compliant_pipelines": 7}
    assert result["aks_summary"] == {
        "clusters": 1,
        "total_pods": 20,
        "drifted_pods": 5,
        "drifted_clusters": 1,
        "compliant_clusters": 0,
    }
    assert result["overall_score"] == 73.3
    assert result["high_issues"] == 8
    by_id = {r["id"]: r for r in result["resources"]}
    assert by_id["ws-a"]["critical_issues"] == 3
    assert by_id["aks-a"]["critical_issues"] == 5


@pytest.mark.anyio
async def test_resource_score_never_goes_negative(session):
    # Pods are replaced over time, so 30 days of drifted pod names can outnumber current pods.
    session.add_all(
        [
            *[_pod("aks-a", "ns", f"pod-{i}", NOW) for i in range(2)],
            *[_pod_drift("aks-a", "ns", f"gone-{i}", NOW - timedelta(days=2)) for i in range(5)],
        ]
    )
    await session.commit()

    result = await _build(session)

    assert result["resources"][0]["score"] == 0.0
    assert result["resources"][0]["grade"] == "F"


@pytest.mark.anyio
async def test_all_resources_are_returned(session):
    session.add_all([_pipeline(f"ws-{i:02d}", "pipe", NOW) for i in range(12)])
    await session.commit()

    result = await _build(session)

    assert result["total_resources"] == 12
    assert len(result["resources"]) == 12


@pytest.mark.anyio
async def test_trend_counts_distinct_items_per_day(session):
    day1 = (NOW - timedelta(days=2)).replace(hour=8)
    day2 = (NOW - timedelta(days=1)).replace(hour=8)
    session.add_all(
        [
            # two runs on day1 must not double-count the same pipelines
            *[_pipeline("ws-a", f"pipe-{i}", day1) for i in range(4)],
            *[_pipeline("ws-a", f"pipe-{i}", day1 + timedelta(hours=2)) for i in range(4)],
            *[_pipeline("ws-a", f"pipe-{i}", day2) for i in range(4)],
            _pipeline_drift("ws-a", "pipe-0", day2),
        ]
    )
    await session.commit()

    result = await _build(session)

    trend = {point["date"]: point["score"] for point in result["score_trend"]}
    assert trend == {day1.strftime("%Y-%m-%d"): 100.0, day2.strftime("%Y-%m-%d"): 75.0}


@pytest.mark.anyio
async def test_get_compliance_dashboard_uses_bound_scope(session):
    session.add_all([_pipeline("ws-a", "pipe", NOW), _pipeline("ws-b", "pipe", NOW, sub="sub-2")])
    await session.commit()

    token = set_scoped_subscription_ids(["sub-2"])
    try:
        result = await ComplianceService(session).get_compliance_dashboard()
    finally:
        reset_scoped_subscription_ids(token)

    assert [r["name"] for r in result["resources"]] == ["ws-b"]


class _RowsResult:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class _RowsDb:
    def __init__(self, rows):
        self._rows = rows

    async def execute(self, _statement):
        return _RowsResult(self._rows)


@pytest.mark.anyio
async def test_aks_cluster_cache_does_not_leak_between_scopes(monkeypatch):
    monkeypatch.setattr(ComplianceService, "_aks_cluster_cache", {})
    rows = [("aks-1", _cluster_id("sub-1", "aks-1")), ("aks-2", _cluster_id("sub-2", "aks-2"))]
    service = ComplianceService(_RowsDb(rows))

    async def _allowed_for(scope):
        token = set_scoped_subscription_ids(scope)
        try:
            return await service._get_allowed_aks_cluster_names()
        finally:
            reset_scoped_subscription_ids(token)

    assert await _allowed_for(["sub-1", "sub-2"]) == {"aks-1", "aks-2"}
    assert await _allowed_for(["sub-2"]) == {"aks-2"}
    assert await _allowed_for(["sub-1", "sub-2"]) == {"aks-1", "aks-2"}


@pytest.mark.anyio
async def test_excel_export_only_includes_drifts_in_scope(session):
    session.add_all(
        [
            _pipeline_drift("ws-mine", "pipe", NOW),
            _pipeline_drift("ws-theirs", "pipe", NOW),
            _pod_drift("aks-mine", "ns", "pod", NOW),
            _pod_drift("aks-theirs", "ns", "pod", NOW, sub="sub-2"),
        ]
    )
    await session.commit()
    scope = ExportScope(frozenset({"sub-1"}), frozenset({"ws-mine"}), frozenset({"aks-mine"}))
    request = ExcelExportRequest(date_from=START)

    synapse = await excel_service._fetch_synapse_drifts(session, request, scope)
    aks = await excel_service._fetch_aks_drifts(session, request, scope)

    assert [d.workspace_name for d in synapse] == ["ws-mine"]
    assert [d.cluster_name for d in aks] == ["aks-mine"]


# ── Endpoint: cached snapshot vs. live computation ──────────────────────────


class _LiveService:
    def __init__(self):
        self.calls = []

    async def get_compliance_dashboard(self, subscription_ids=None):
        self.calls.append(subscription_ids)
        return {"source": "live"}


def _patch_endpoint(monkeypatch, *, full_scope: bool):
    scheduled = []

    async def _scope_is_full():
        return full_scope

    async def _cached(_self):
        return {"source": "snapshot"}

    async def _not_running(_self):
        return False

    monkeypatch.setattr(compliance_endpoints, "scope_is_full", _scope_is_full)
    monkeypatch.setattr(ComplianceSyncService, "get_dashboard_from_db", _cached)
    monkeypatch.setattr(ComplianceSyncService, "is_sync_running", _not_running)
    monkeypatch.setattr(
        ComplianceSyncService,
        "schedule_background_sync",
        classmethod(lambda _cls, triggered_by="": scheduled.append(triggered_by)),
    )
    return scheduled


@pytest.mark.anyio
async def test_dashboard_serves_snapshot_when_picker_selects_every_subscription(monkeypatch):
    # The UI sends its picker selection on every GET; a full selection must still hit the snapshot.
    _patch_endpoint(monkeypatch, full_scope=True)
    live = _LiveService()

    result = await compliance_endpoints.get_compliance_dashboard(
        subscription_ids=["sub-1", "sub-2"], refresh=False, user=None, service=live, db=None
    )

    assert result == {"source": "snapshot"}
    assert live.calls == []


@pytest.mark.anyio
async def test_dashboard_computes_live_for_narrowed_scope_without_scheduling_sync(monkeypatch):
    scheduled = _patch_endpoint(monkeypatch, full_scope=False)
    live = _LiveService()

    result = await compliance_endpoints.get_compliance_dashboard(
        subscription_ids=["sub-1"], refresh=False, user=None, service=live, db=None
    )

    assert result == {"source": "live"}
    assert scheduled == []


@pytest.mark.anyio
async def test_background_sync_does_not_inherit_request_scope(monkeypatch):
    seen = []

    async def _record(cls, triggered_by="request"):
        seen.append(get_active_scoped_subscription_ids())

    monkeypatch.setattr(ComplianceSyncService, "_run_background_sync", classmethod(_record))

    token = set_scoped_subscription_ids(["narrow-sub"])
    try:
        ComplianceSyncService.schedule_background_sync(triggered_by="test")
    finally:
        reset_scoped_subscription_ids(token)
    await asyncio.gather(*compliance_sync_service._background_tasks)

    assert seen == [None]
