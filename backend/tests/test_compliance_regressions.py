import hashlib
from datetime import datetime
from types import SimpleNamespace

import pytest

from app.api.v1.endpoints import checksum_schedules
from app.models.database import ChecksumResult, ChecksumRun, SynapsePipelineChecksum
from app.schemas.checksum_schedules import ChecksumScheduleDetail
from app.schemas.compliance import ExcelExportRequest, ModuleType
from app.services.compliance_excel_service import ComplianceExcelService
from app.services.compliance_service import ComplianceService


class _FakeScalarResult:
    def __init__(self, schedule):
        self._schedule = schedule

    def scalar_one_or_none(self):
        return self._schedule


class _FakeDbSession:
    def __init__(self, schedule):
        self.schedule = schedule
        self.statement = None

    async def execute(self, statement):
        self.statement = statement
        return _FakeScalarResult(self.schedule)


class _FakeScalarListResult:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return self

    def all(self):
        return self._rows


class _FakeTupleResult:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class _QueuedDbSession:
    def __init__(self, responses):
        self._responses = list(responses)
        self.statement = None
        self.added = []

    async def execute(self, statement):
        self.statement = statement
        return self._responses.pop(0)

    def add(self, value):
        self.added.append(value)

    async def commit(self):
        return None

    async def rollback(self):
        return None

    async def refresh(self, _value):
        return None


@pytest.mark.anyio
async def test_generate_export_accepts_uppercase_module_type(monkeypatch):
    async def _empty_fetch(*_args, **_kwargs):
        return []

    def _write_sheet(workbook, *_args, **_kwargs):
        workbook.create_sheet("Stub")
        return 0

    monkeypatch.setattr("app.services.compliance_excel_service._fetch_synapse_drifts", _empty_fetch)
    monkeypatch.setattr("app.services.compliance_excel_service._fetch_aks_drifts", _empty_fetch)
    monkeypatch.setattr("app.services.compliance_excel_service._fetch_compliance_scores", _empty_fetch)
    monkeypatch.setattr("app.services.compliance_excel_service._fetch_checksum_runs", _empty_fetch)
    monkeypatch.setattr("app.services.compliance_excel_service._write_synapse_sheet", _write_sheet)
    monkeypatch.setattr("app.services.compliance_excel_service._write_aks_sheet", _write_sheet)
    monkeypatch.setattr("app.services.compliance_excel_service._write_scores_sheet", _write_sheet)
    monkeypatch.setattr("app.services.compliance_excel_service._write_checksum_runs_sheet", _write_sheet)

    buffer, metadata = await ComplianceExcelService.generate_export(
        db=None,
        request=ExcelExportRequest(
            module_type=ModuleType.SYNAPSE,
            include_scores=False,
            include_checksum_runs=False,
        ),
    )

    assert buffer.getbuffer().nbytes > 0
    assert metadata.filename.startswith("compliance_report_synapse_")


@pytest.mark.anyio
async def test_get_checksum_schedule_normalizes_string_id():
    schedule = SimpleNamespace(
        id=13,
        name="Nightly checksum",
        description="Regression test",
        module_type="synapse",
        system="attcc",
        environment="prod",
        workspace_name="attcc-eastus2-perf-synapse-wkspace",
        cluster_id=None,
        cluster_name=None,
        namespaces=[],
        schedule_type="interval",
        interval_hours=24,
        cron_expression=None,
        timezone="UTC",
        notification_emails=["ops@example.com"],
        is_enabled=True,
        last_run_at=None,
        next_run_at=None,
        created_at=None,
        created_by="dev@localhost",
    )
    fake_db = _FakeDbSession(schedule)
    service = ComplianceService(fake_db)
    service._get_allowed_synapse_workspace_names = lambda: __import__("asyncio").sleep(
        0, result={schedule.workspace_name}
    )

    result = await service.get_checksum_schedule("13")

    assert result is not None
    assert result["id"] == 13
    assert fake_db.statement is not None
    compiled = fake_db.statement.compile()
    assert 13 in compiled.params.values()


def test_normalize_schedule_id_accepts_numeric_strings():
    assert ComplianceService._normalize_schedule_id("13") == 13


def test_checksum_schedule_detail_route_uses_detail_response_model():
    detail_route = next(route for route in checksum_schedules.router.routes if route.path == "/{schedule_id}")

    assert detail_route.response_model is ChecksumScheduleDetail


@pytest.mark.anyio
async def test_resolve_scoped_subscription_ids_intersects_requested_ids(monkeypatch):
    async def _mock_monitored_ids():
        return ["sub-1", "sub-2"]

    monkeypatch.setattr(
        "app.services.compliance_service.get_monitored_subscription_ids",
        _mock_monitored_ids,
    )

    service = ComplianceService(db_session=None)

    assert await service._resolve_scoped_subscription_ids(None) == ["sub-1", "sub-2"]
    assert await service._resolve_scoped_subscription_ids(["sub-2", "sub-3"]) == ["sub-2"]


def test_cluster_scope_uses_subscription_from_cluster_resource_id():
    assert ComplianceService._cluster_matches_subscription_scope(
        "/subscriptions/sub-9/resourceGroups/rg/providers/Microsoft.ContainerService/managedClusters/aks-a",
        ["sub-9"],
    )
    assert not ComplianceService._cluster_matches_subscription_scope(
        "/subscriptions/sub-9/resourceGroups/rg/providers/Microsoft.ContainerService/managedClusters/aks-a",
        ["sub-4"],
    )


@pytest.mark.anyio
async def test_filter_workspaces_by_subscription_scope_keeps_only_monitored_items():
    workspaces = [
        {"workspace_name": "attcc-prod", "subscription_id": "sub-attcc"},
        {"workspace_name": "ces-prod", "subscription_id": "sub-ces"},
    ]

    filtered = ComplianceService._filter_workspaces_by_subscription_scope(workspaces, ["sub-ces"])

    assert filtered == [{"workspace_name": "ces-prod", "subscription_id": "sub-ces"}]


@pytest.mark.anyio
async def test_get_checksum_runs_filters_aks_clusters_to_monitored_scope(monkeypatch):
    now = datetime.utcnow()
    runs = [
        SimpleNamespace(
            run_id="run-1",
            module_type="aks",
            system="attcc",
            environment="prod",
            workspace_name="allowed-aks",
            execution_date=now,
            total_pipelines=3,
            passed=3,
            failed=0,
            status="completed",
        ),
        SimpleNamespace(
            run_id="run-2",
            module_type="aks",
            system="attcc",
            environment="prod",
            workspace_name="blocked-aks",
            execution_date=now,
            total_pipelines=4,
            passed=2,
            failed=2,
            status="completed",
        ),
    ]
    service = ComplianceService(_QueuedDbSession([_FakeScalarListResult(runs)]))

    async def _allowed_workspaces():
        return set()

    async def _allowed_aks_clusters(_subscription_ids=None):
        return {"allowed-aks"}

    monkeypatch.setattr(service, "_get_allowed_synapse_workspace_names", _allowed_workspaces)
    monkeypatch.setattr(service, "_get_allowed_aks_cluster_names", _allowed_aks_clusters)

    result = await service.get_checksum_runs(module_type="aks")

    assert [row["workspace_name"] for row in result] == ["allowed-aks"]


@pytest.mark.anyio
async def test_get_checksum_results_filters_aks_clusters_to_monitored_scope(
    monkeypatch,
):
    now = datetime.utcnow()
    run_allowed = SimpleNamespace(
        module_type="aks",
        workspace_name="allowed-aks",
        system="attcc",
        environment="prod",
        execution_date=now,
    )
    run_blocked = SimpleNamespace(
        module_type="aks",
        workspace_name="blocked-aks",
        system="attcc",
        environment="prod",
        execution_date=now,
    )
    rows = [
        (
            SimpleNamespace(
                id=1,
                run_id="run-1",
                slno=1,
                pipeline_name="pod-a",
                yesterday_hash="a",
                present_hash="a",
                last_published_date=None,
                result="PASS",
            ),
            run_allowed,
        ),
        (
            SimpleNamespace(
                id=2,
                run_id="run-2",
                slno=1,
                pipeline_name="pod-b",
                yesterday_hash="b",
                present_hash="c",
                last_published_date=None,
                result="FAIL",
            ),
            run_blocked,
        ),
    ]
    service = ComplianceService(_QueuedDbSession([_FakeTupleResult(rows)]))

    async def _allowed_workspaces():
        return set()

    async def _allowed_aks_clusters(_subscription_ids=None):
        return {"allowed-aks"}

    monkeypatch.setattr(service, "_get_allowed_synapse_workspace_names", _allowed_workspaces)
    monkeypatch.setattr(service, "_get_allowed_aks_cluster_names", _allowed_aks_clusters)

    result = await service.get_checksum_results(module_type="aks")

    assert [row["workspace_name"] for row in result] == ["allowed-aks"]


@pytest.mark.anyio
async def test_list_checksum_schedules_filters_to_monitored_scope(monkeypatch):
    schedules = [
        SimpleNamespace(
            id=1,
            name="allowed-synapse",
            description=None,
            module_type="synapse",
            system="attcc",
            environment="prod",
            workspace_name="allowed-ws",
            cluster_id=None,
            cluster_name=None,
            namespaces=[],
            schedule_type="interval",
            interval_hours=24,
            cron_expression=None,
            timezone="UTC",
            notification_emails=[],
            is_enabled=True,
            last_run_at=None,
            next_run_at=None,
            created_at=None,
            created_by="dev@localhost",
        ),
        SimpleNamespace(
            id=2,
            name="blocked-aks",
            description=None,
            module_type="aks",
            system="attcc",
            environment="prod",
            workspace_name=None,
            cluster_id="/subscriptions/sub-2/resourceGroups/rg/providers/Microsoft.ContainerService/managedClusters/blocked-aks",
            cluster_name="blocked-aks",
            namespaces=[],
            schedule_type="interval",
            interval_hours=24,
            cron_expression=None,
            timezone="UTC",
            notification_emails=[],
            is_enabled=True,
            last_run_at=None,
            next_run_at=None,
            created_at=None,
            created_by="dev@localhost",
        ),
    ]
    service = ComplianceService(_QueuedDbSession([_FakeScalarListResult(schedules)]))

    async def _resolve_scope(_subscription_ids=None):
        return ["sub-1"]

    async def _allowed_workspaces():
        return {"allowed-ws"}

    monkeypatch.setattr(service, "_resolve_scoped_subscription_ids", _resolve_scope)
    monkeypatch.setattr(service, "_get_allowed_synapse_workspace_names", _allowed_workspaces)

    result = await service.list_checksum_schedules()

    assert [row["name"] for row in result] == ["allowed-synapse"]


@pytest.mark.anyio
async def test_create_checksum_schedule_rejects_unmonitored_aks_cluster(monkeypatch):
    service = ComplianceService(_QueuedDbSession([]))

    async def _resolve_scope(_subscription_ids=None):
        return ["sub-1"]

    monkeypatch.setattr(service, "_resolve_scoped_subscription_ids", _resolve_scope)

    with pytest.raises(ValueError, match="outside the Admin monitored subscription scope"):
        await service.create_checksum_schedule(
            payload={
                "name": "blocked-aks",
                "module_type": "aks",
                "cluster_id": "/subscriptions/sub-2/resourceGroups/rg/providers/Microsoft.ContainerService/managedClusters/blocked-aks",
                "cluster_name": "blocked-aks",
                "schedule_type": "interval",
                "interval_hours": 24,
                "timezone": "UTC",
                "notification_emails": [],
                "is_enabled": True,
            },
            created_by="dev@localhost",
        )


@pytest.mark.anyio
async def test_run_checksum_verification_falls_back_to_latest_two_snapshots_when_live_fetch_fails(monkeypatch):
    previous_snapshot = datetime(2026, 4, 8, 10, 0, 0)
    latest_snapshot = datetime(2026, 4, 10, 10, 0, 0)
    fake_db = _QueuedDbSession(
        [
            _FakeTupleResult([(latest_snapshot,), (previous_snapshot,)]),
            _FakeTupleResult(
                [
                    ("pipeline-a", "hash-new", latest_snapshot),
                    ("pipeline-b", "hash-same", None),
                ]
            ),
            _FakeTupleResult(
                [
                    ("pipeline-a", "hash-old", previous_snapshot),
                    ("pipeline-b", "hash-same", None),
                ]
            ),
        ]
    )
    service = ComplianceService(fake_db)

    async def _workspace_list(*_args, **_kwargs):
        return [
            {
                "workspace_name": "ces-eastus2-prod-synapse",
                "system": "ces",
                "environment": "prod",
                "region": "eastus2",
            }
        ]

    monkeypatch.setattr(service, "get_workspace_list", _workspace_list)
    monkeypatch.setattr(
        service,
        "_list_pipelines_rest",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("network blocked")),
    )

    result = await service.run_checksum_verification("ces-eastus2-prod-synapse")

    assert result["total"] == 2
    assert result["passed"] == 1
    assert result["failed"] == 1

    run_record = next(item for item in fake_db.added if isinstance(item, ChecksumRun))
    result_records = [item for item in fake_db.added if isinstance(item, ChecksumResult)]

    assert run_record.status == "completed"
    assert run_record.total_pipelines == 2
    assert len(result_records) == 2


@pytest.mark.anyio
async def test_run_checksum_verification_persists_new_live_snapshot_against_latest_baseline(monkeypatch):
    latest_snapshot = datetime(2026, 4, 11, 10, 0, 0)
    pipeline_b_bytes = b'{"name":"pipeline-b","version":1}'
    pipeline_b_hash = hashlib.sha256(pipeline_b_bytes.rstrip(b"\n") + b"\n").hexdigest()
    fake_db = _QueuedDbSession(
        [
            _FakeTupleResult([(latest_snapshot,)]),
            _FakeTupleResult(
                [
                    ("pipeline-a", "hash-old", latest_snapshot),
                    ("pipeline-b", pipeline_b_hash, None),
                ]
            ),
        ]
    )
    service = ComplianceService(fake_db)

    async def _workspace_list(*_args, **_kwargs):
        return [
            {
                "workspace_name": "ces-eastus2-prod-synapse",
                "system": "ces",
                "environment": "prod",
                "region": "eastus2",
                "subscription_id": "sub-123",
            }
        ]

    pipeline_a_bytes = b'{"name":"pipeline-a","version":2}'

    monkeypatch.setattr(service, "get_workspace_list", _workspace_list)
    monkeypatch.setattr(
        service,
        "_list_pipelines_rest",
        lambda *_args, **_kwargs: [
            (
                pipeline_a_bytes,
                {
                    "name": "pipeline-a",
                    "properties": {"activities": [], "lastPublishTime": "2026-04-12T07:06:36Z"},
                },
            ),
            (
                pipeline_b_bytes,
                {
                    "name": "pipeline-b",
                    "properties": {"activities": [], "lastPublishTime": "2026-04-12T06:27:44Z"},
                },
            ),
        ],
    )

    result = await service.run_checksum_verification("ces-eastus2-prod-synapse")

    assert result["total"] == 2
    assert result["passed"] == 1
    assert result["failed"] == 1

    result_records = [item for item in fake_db.added if isinstance(item, ChecksumResult)]
    snapshot_records = [item for item in fake_db.added if isinstance(item, SynapsePipelineChecksum)]

    pipeline_a_result = next(item for item in result_records if item.pipeline_name == "pipeline-a")
    pipeline_b_result = next(item for item in result_records if item.pipeline_name == "pipeline-b")

    assert pipeline_a_result.yesterday_hash == "hash-old"
    assert pipeline_a_result.present_hash
    assert pipeline_a_result.result == "FAIL"
    assert pipeline_b_result.yesterday_hash == pipeline_b_hash
    assert pipeline_b_result.present_hash == pipeline_b_hash
    assert pipeline_b_result.result == "PASS"
    assert len(snapshot_records) == 2


@pytest.mark.anyio
async def test_get_dashboard_aks_summary_uses_latest_scoped_snapshot_and_drift():
    scoped_snapshot = datetime(2026, 4, 12, 8, 0, 0)
    scoped_drift = datetime(2026, 4, 12, 8, 30, 0)
    allowed_cluster_id = (
        "/subscriptions/sub-1/resourceGroups/rg/providers/Microsoft.ContainerService/managedClusters/aks-allowed"
    )

    # With the SQL-level subscription filter the DB returns only
    # scoped results, so the mock queue is:
    #   1. scalar → MAX(snapshot_date) for scoped subscriptions
    #   2. execute → pod checksums (already filtered by subscription)
    #   3. scalar → MAX(detection_date) for scoped subscriptions
    #   4. execute → drifts (already filtered by subscription)
    fake_db = _QueuedDbSessionWithScalar(
        [
            scoped_snapshot,
            _FakeScalarListResult(
                [
                    SimpleNamespace(cluster_id=allowed_cluster_id, cluster_name="aks-allowed"),
                    SimpleNamespace(cluster_id=allowed_cluster_id, cluster_name="aks-allowed"),
                ]
            ),
            scoped_drift,
            _FakeScalarListResult(
                [
                    SimpleNamespace(cluster_id=allowed_cluster_id, cluster_name="aks-allowed"),
                ]
            ),
        ]
    )
    service = ComplianceService(fake_db)

    summary = await service._get_dashboard_aks_summary(["sub-1"])

    assert summary == {
        "clusters": 1,
        "total_pods": 2,
        "compliant_clusters": 0,
        "drifted_clusters": 1,
        "drifted_pods": 1,
    }


@pytest.mark.anyio
async def test_get_compliance_dashboard_prefers_snapshot_dashboard_when_live_data_exists(monkeypatch):
    service = ComplianceService(_QueuedDbSession([]))
    snapshot_dashboard = {
        "overall_score": 56.0,
        "overall_grade": "F",
        "calculated_at": "2026-04-12T08:30:00",
        "total_resources": 2,
        "by_type": {"Synapse": {"count": 1, "avg_score": 13.0}, "AKS": {"count": 1, "avg_score": 99.0}},
        "by_grade": {"A": 1, "B": 0, "C": 0, "D": 0, "F": 1},
        "critical_issues": 0,
        "high_issues": 53,
        "score_trend": [{"date": "2026-04-12", "score": 56.0}],
        "synapse_summary": {"total_pipelines": 61, "compliant_pipelines": 8, "drifted_pipelines": 53},
        "aks_summary": {
            "clusters": 1,
            "total_pods": 8,
            "compliant_clusters": 0,
            "drifted_clusters": 1,
            "drifted_pods": 8,
        },
        "resources": [
            {
                "id": "synapse-a",
                "name": "synapse-a",
                "type": "synapse_workspace",
                "score": 13.0,
                "grade": "F",
                "critical_issues": 53,
            },
            {"id": "aks-a", "name": "aks-a", "type": "aks_cluster", "score": 99.0, "grade": "A", "critical_issues": 8},
        ],
    }

    async def _resolve_scope(_subscription_ids=None):
        return ["sub-1"]

    async def _synapse_summary(_subscription_ids=None):
        return snapshot_dashboard["synapse_summary"]

    async def _aks_summary(_subscription_ids=None):
        return snapshot_dashboard["aks_summary"]

    async def _snapshot_build(**_kwargs):
        return snapshot_dashboard

    async def _unexpected_scores(_subscription_ids=None):
        raise AssertionError("stale stored scores should not be consulted when live snapshot data exists")

    monkeypatch.setattr(service, "_resolve_scoped_subscription_ids", _resolve_scope)
    monkeypatch.setattr(service, "_get_dashboard_synapse_summary", _synapse_summary)
    monkeypatch.setattr(service, "_get_dashboard_aks_summary", _aks_summary)
    monkeypatch.setattr(service, "_build_dashboard_from_checksum_snapshots", _snapshot_build)
    monkeypatch.setattr(service, "_get_latest_compliance_scores", _unexpected_scores)

    result = await service.get_compliance_dashboard(["sub-1"])

    assert result == snapshot_dashboard


# ── AKS checksum column-width regression ─────────────────────────────


def test_image_checksum_fits_column_for_multi_container_pods():
    """Regression: pods with >1 container produced pipe-joined SHA digests
    that exceeded the String(64) DB column.  The fix hashes the sorted list
    of image digests through _compute_checksum so the result is always 64
    hex characters.
    """
    service = ComplianceService(db_session=None)

    # Simulate two image SHA256 digests from a multi-container pod
    image_shas = [
        "3f59cbe79ac72b144ed85cfad4aed4625fadfafe61283ce250e42f0269bc31ab",
        "f15166c24d4cbf3a2ed7bc5bc9388e23b8098e709065c61360b5e7e1560b448b",
    ]
    checksum = service._compute_checksum(sorted(image_shas))

    # Must be exactly 64 hex chars (SHA-256 hexdigest)
    assert len(checksum) == 64
    assert all(c in "0123456789abcdef" for c in checksum)


def test_image_checksum_single_container_also_fits():
    """Single-container pods should also produce a 64-char checksum."""
    service = ComplianceService(db_session=None)

    image_shas = [
        "9dc0c284ac65e9f8b3e4d61aeadd885f3e7ce9e0d90a2c1c35a4e57d7f3abb12",
    ]
    checksum = service._compute_checksum(sorted(image_shas))

    assert len(checksum) == 64
    assert all(c in "0123456789abcdef" for c in checksum)


def test_extract_image_shas_returns_64_char_digests():
    """_extract_image_shas should return clean 64-char hex strings."""
    shas = ComplianceService._extract_image_shas(
        SimpleNamespace(
            container_statuses=[
                SimpleNamespace(
                    image_id="mcr.microsoft.com/img@sha256:" + "a" * 64,
                ),
                SimpleNamespace(
                    image_id="mcr.microsoft.com/img@sha256:" + "b" * 64,
                ),
            ]
        )
    )

    assert len(shas) == 2
    assert all(len(s) == 64 for s in shas)


def test_comparable_image_checksum_normalizes_legacy_single_container():
    """Legacy rows stored raw SHA digest as container_images_checksum.
    _comparable_image_checksum must re-hash it to match new-format rows.
    """
    service = ComplianceService(db_session=None)
    raw_sha = "9dc0c284ac65e9f8b3e4d61aeadd885f37afa2bd1143f8ce9448fac907594701"

    # Legacy row: no image_digests, checksum is the raw sha
    legacy_row = SimpleNamespace(
        image_digests=None,
        container_images_checksum=raw_sha,
    )
    # New row: has image_digests stored
    new_row = SimpleNamespace(
        image_digests=[raw_sha],
        container_images_checksum=service._compute_checksum(sorted([raw_sha])),
    )

    legacy_result = service._comparable_image_checksum(legacy_row)
    new_result = service._comparable_image_checksum(new_row)

    assert legacy_result == new_result
    assert len(legacy_result) == 64


def test_comparable_image_checksum_normalizes_legacy_multi_container():
    """_comparable_image_checksum returns only the first actual container
    digest for new rows and falls back to the raw stored value for legacy
    rows.  Multi-container pods show a single 64-char digest (the primary
    app container), not a pipe-joined or hashed combination.
    """
    service = ComplianceService(db_session=None)
    sha_a = "a" * 64
    sha_b = "b" * 64

    # New row with image_digests: returns only the first digest
    new_row = SimpleNamespace(
        image_digests=[sha_a, sha_b],
        container_images_checksum=service._compute_checksum(sorted([sha_a, sha_b])),
    )
    new_result = service._comparable_image_checksum(new_row)
    assert new_result == sha_a  # first digest only, not joined or hashed

    # Legacy row without image_digests: returns raw stored checksum as-is
    legacy_row = SimpleNamespace(
        image_digests=None,
        container_images_checksum=f"{sha_a}|{sha_b}",
    )
    legacy_result = service._comparable_image_checksum(legacy_row)
    assert legacy_result == f"{sha_a}|{sha_b}"  # raw fallback


# ---------------------------------------------------------------------------
# Leadership sync serialisation regression
# ---------------------------------------------------------------------------


def test_leadership_dashboard_model_dump_json_roundtrips():
    """model_dump_json() output must parse back into the same model.

    Regression: full_sync() previously used ``json.dumps(data, default=str)``
    which silently corrupted Pydantic v2 models into their Python repr,
    breaking the Redis/DB caching layer.
    """
    from datetime import datetime
    from decimal import Decimal

    from app.schemas.cost import (
        CostByGroup,
        CostDataPoint,
        CostTrendDirection,
        GroupByDimension,
        KPIMetric,
        LeadershipDashboard,
        MonthlyCostPoint,
    )

    dashboard = LeadershipDashboard(
        kpis=[
            KPIMetric(
                name="Total Monthly Spend",
                value=57324,
                unit="USD",
                trend=CostTrendDirection.DOWN,
                change_pct=-47.5,
                description="Current month spend",
            ),
        ],
        cost_trend=[
            CostDataPoint(
                date="2026-03-01",
                cost=100,
                group_value="PROD-1",
                group_dimension=GroupByDimension.SUBSCRIPTION,
            ),
        ],
        top_spenders=[
            CostByGroup(
                group_dimension=GroupByDimension.SUBSCRIPTION,
                group_value="PROD-31599-ATTCC",
                total_cost=42000,
                percentage_of_total=73.7,
            ),
        ],
        six_month_trend=[
            MonthlyCostPoint(
                month="2025-10",
                month_label="Oct 2025",
                total_cost=89000,
                non_prod_cost=24000,
                prod_cost=65000,
                subscription_breakdown={"PROD-31599-ATTCC": 65000},
            ),
        ],
        savings_opportunities=Decimal("12996"),
        report_date=datetime(2026, 4, 14, 12, 0, 0),
    )

    payload_json = dashboard.model_dump_json()

    # Must round-trip back to the same model without error
    restored = LeadershipDashboard.model_validate_json(payload_json)
    assert restored.kpis[0].name == "Total Monthly Spend"
    assert restored.kpis[0].value == 57324
    assert len(restored.cost_trend) == 1
    assert len(restored.top_spenders) == 1
    assert len(restored.six_month_trend) == 1


# ---------------------------------------------------------------------------
# Compliance dashboard summary reconciliation regression
# ---------------------------------------------------------------------------

_AKS_CLUSTER_ID = "/subscriptions/sub-1/resourceGroups/rg/providers/Microsoft.ContainerService/managedClusters/aks-a"


def _synapse_checksum(workspace: str, pipeline: str, date: datetime):
    return SimpleNamespace(
        workspace_name=workspace,
        pipeline_name=pipeline,
        snapshot_date=date,
        subscription_id="sub-1",
    )


def _aks_checksum(cluster: str, pod: str, date: datetime):
    return SimpleNamespace(
        cluster_name=cluster,
        pod_name=pod,
        snapshot_date=date,
        cluster_id=_AKS_CLUSTER_ID,
    )


def _synapse_drift(workspace: str, pipeline: str, date: datetime, drift_type: str = "modified"):
    return SimpleNamespace(
        workspace_name=workspace,
        pipeline_name=pipeline,
        detection_date=date,
        acknowledged=False,
        drift_type=drift_type,
    )


def _aks_drift(cluster: str, pod: str, date: datetime, severity: str = "high"):
    return SimpleNamespace(
        cluster_name=cluster,
        pod_name=pod,
        detection_date=date,
        acknowledged=False,
        severity=severity,
        cluster_id=_AKS_CLUSTER_ID,
    )


class _QueuedDbSessionWithScalar(_QueuedDbSession):
    """Extends _QueuedDbSession with ``scalar()`` support."""

    async def scalar(self, statement):
        self.statement = statement
        return self._responses.pop(0)


@pytest.mark.anyio
async def test_dashboard_summary_reconciliation_overrides_precomputed_values():
    """Regression: The pre-computed synapse_summary and aks_summary used a
    different time window (latest-date-only) which caused KPI tiles to show
    stale or zero drifted counts while the resource table showed the correct
    numbers.  The reconciliation block in _build_dashboard_from_checksum_snapshots
    must override both summaries with the same drift data used for scores.
    """
    snap_date = datetime(2026, 4, 15)
    drift_date = datetime(2026, 4, 14)

    # 10 Synapse pipelines, 3 drifted
    synapse_checksums = [_synapse_checksum("ws-a", f"pipe-{i}", snap_date) for i in range(10)]
    synapse_drifts = [_synapse_drift("ws-a", f"pipe-{i}", drift_date) for i in range(3)]

    # 20 AKS pods in 1 cluster, 5 drifted
    aks_checksums = [_aks_checksum("aks-a", f"pod-{i}", snap_date) for i in range(20)]
    aks_drifts = [_aks_drift("aks-a", f"pod-{i}", drift_date) for i in range(5)]

    # Intentionally WRONG pre-computed summaries (what the old code produced
    # when the latest drift date had no matching drifts): drifted=0 / drifted=1
    wrong_synapse_summary: dict = {
        "total_pipelines": 10,
        "compliant_pipelines": 10,
        "drifted_pipelines": 0,
    }
    wrong_aks_summary: dict = {
        "clusters": 1,
        "total_pods": 20,
        "compliant_clusters": 1,
        "drifted_clusters": 0,
        "drifted_pods": 1,
    }

    # DB responses in call order within _build_dashboard_from_checksum_snapshots:
    #  1. scalar  → max synapse snapshot date
    #  2. execute → synapse checksums
    #  3. scalar  → max AKS snapshot date (SQL-level subscription filter)
    #  4. execute → AKS checksums (SQL-level subscription filter)
    #  5. execute → allowed synapse workspace names
    #  6. execute → synapse drifts
    #  7. execute → AKS drifts (SQL-level subscription filter)
    fake_db = _QueuedDbSessionWithScalar(
        [
            # 1. scalar: max synapse snapshot date
            snap_date,
            # 2. execute: synapse checksums
            _FakeScalarListResult(synapse_checksums),
            # 3. scalar: max AKS snapshot date (subscription-filtered)
            snap_date,
            # 4. execute: AKS checksums (subscription-filtered)
            _FakeScalarListResult(aks_checksums),
            # 5. execute: allowed synapse workspace names
            _FakeTupleResult([("ws-a",)]),
            # 6. execute: synapse drifts
            _FakeScalarListResult(synapse_drifts),
            # 7. execute: AKS drifts (subscription-filtered)
            _FakeScalarListResult(aks_drifts),
            # 8. execute: synapse trend checksums (30-day window)
            _FakeScalarListResult(synapse_checksums),
            # 9. execute: AKS trend checksums (30-day window, subscription-filtered)
            _FakeScalarListResult(aks_checksums),
        ]
    )

    service = ComplianceService(fake_db)

    result = await service._build_dashboard_from_checksum_snapshots(
        subscription_ids=["sub-1"],
        start_date=datetime(2026, 3, 15),
        synapse_summary=wrong_synapse_summary,
        aks_summary=wrong_aks_summary,
    )

    # ── Synapse summary must reflect the 3 drifted pipelines, NOT 0 ──
    syn = result["synapse_summary"]
    assert syn["total_pipelines"] == 10
    assert syn["drifted_pipelines"] == 3, (
        f"Expected 3 drifted pipelines (from drift data), got {syn['drifted_pipelines']}"
    )
    assert syn["compliant_pipelines"] == 7

    # ── AKS summary must reflect the 5 drifted pods, NOT 1 ──
    aks = result["aks_summary"]
    assert aks["total_pods"] == 20
    assert aks["drifted_pods"] == 5, f"Expected 5 drifted pods (from drift data), got {aks['drifted_pods']}"
    assert aks["clusters"] == 1
    assert aks["drifted_clusters"] == 1
    assert aks["compliant_clusters"] == 0

    # ── Overall score consistency: (30 items - 8 drifted) / 30 = 73.3% ──
    assert result["overall_score"] == 73.3

    # ── Resource table must agree with summaries ──
    resources = result["resources"]
    synapse_resource = next(r for r in resources if r["type"] == "synapse_workspace")
    assert synapse_resource["critical_issues"] == 3  # same as drifted_pipelines

    aks_resource = next(r for r in resources if r["type"] == "aks_cluster")
    assert aks_resource["critical_issues"] == 5  # same as drifted_pods
