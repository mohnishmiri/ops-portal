from datetime import date

import pytest

from app.services.amortized_cost_sync_service import AmortizedCostSyncService


class _FakeScalarResult:
    def __init__(self, item) -> None:
        self._item = item

    def first(self):
        return self._item


class _FakeResult:
    def __init__(self, item) -> None:
        self._item = item

    def scalars(self):
        return _FakeScalarResult(self._item)

    def all(self):
        return self._item


class _FakeSession:
    def __init__(self, execute_results: list[object] | None = None) -> None:
        self.added = []
        self.bulk_added = []
        self.executed = []
        self._execute_results = list(execute_results or [])

    def add(self, item) -> None:
        self.added.append(item)

    def add_all(self, items) -> None:
        self.bulk_added.extend(items)

    async def execute(self, statement):
        self.executed.append(statement)
        if self._execute_results:
            return _FakeResult(self._execute_results.pop(0))
        return _FakeResult(None)

    async def commit(self) -> None:
        return None

    async def flush(self) -> None:
        return None


@pytest.mark.anyio
async def test_full_sync_inserts_only_targeted_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """full_sync inserts the rows returned by _load_rows_incremental."""

    db = _FakeSession()
    service = AmortizedCostSyncService(db)

    sample_row = {
        "date": "2026-03-01",
        "cost": 22.0,
        "meter_category": "Storage",
        "meter_subcategory": "Blob",
        "meter_name": "Hot LRS",
        "resource_group": "rg-b",
        "resource_name": "storage-b",
        "resource_type": "Microsoft.Storage/storageAccounts",
        "resource_location": "eastus2",
        "subscription_name": "Subscription B",
        "subscription_id": "sub-b",
        "service_name": "Storage",
        "charge_type": "Usage",
        "pricing_model": "OnDemand",
        "publisher_type": "Azure",
        "frequency": "UsageBased",
        "currency": "USD",
        "env_label": "Non-Prod",
    }

    async def fake_get_monitored_ids():
        return ["sub-b"]

    async def fake_fetch_metadata(ids):
        return {"sub-b": {"subscription_name": "Sub B", "environment": "nonprod"}}

    async def fake_compute_fetch_ranges(ids, full_start, end_date):
        return {"sub-b": [(full_start, end_date)]}

    async def fake_delete_fetch_ranges(per_sub):
        pass

    async def fake_load_rows_incremental(sub_meta, per_sub, end_date):
        return [sample_row], [], per_sub

    async def fake_invalidate(_pattern):
        pass

    async def fake_aggregate():
        pass

    monkeypatch.setattr(
        "app.services.amortized_cost_sync_service.get_monitored_subscription_ids",
        fake_get_monitored_ids,
    )
    monkeypatch.setattr(service, "_fetch_subscription_metadata", fake_fetch_metadata)
    monkeypatch.setattr(service, "_compute_fetch_ranges", fake_compute_fetch_ranges)
    monkeypatch.setattr(service, "_delete_fetch_ranges", fake_delete_fetch_ranges)
    monkeypatch.setattr(service, "_load_rows_incremental", fake_load_rows_incremental)
    monkeypatch.setattr(
        "app.services.amortized_cost_sync_service.cache_manager.invalidate",
        fake_invalidate,
    )
    monkeypatch.setattr(service, "_aggregate_cost_summaries", fake_aggregate)

    result = await service.full_sync(months=2, triggered_by="manual")

    assert result["status"] == "completed"
    assert result["rows_synced"] == 1
    assert result["total_cost"] == 22.0
    assert result["duration_seconds"] >= 0
    assert len(db.bulk_added) == 1
    assert db.bulk_added[0].subscription_id == "sub-b"


@pytest.mark.anyio
async def test_load_rows_incremental_uses_query_api_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """_load_rows_incremental calls query_amortized_cost_rows once per monthly chunk."""
    from datetime import date as _date

    db = _FakeSession()
    service = AmortizedCostSyncService(db)
    call_args: list[tuple] = []

    async def fake_query_amortized_cost_rows(scope: str, start_date, end_date) -> list[dict]:
        call_args.append((scope, start_date, end_date))
        assert scope == "/subscriptions/sub-a"
        return [
            {
                "date": "2026-03-01",
                "cost": 12.5,
                "meter_category": "Storage",
                "meter_subcategory": "",
                "meter_name": "",
                "resource_group": "rg-a",
                "resource_name": "",
                "resource_type": "",
                "resource_location": "",
                "subscription_name": "",
                "subscription_id": "",
                "service_name": "Storage",
                "charge_type": "Usage",
                "pricing_model": "",
                "publisher_type": "Azure",
                "frequency": "UsageBased",
                "currency": "USD",
            },
        ]

    monkeypatch.setattr(service._cost_service, "query_amortized_cost_rows", fake_query_amortized_cost_rows)

    sub_metadata = {"sub-a": {"subscription_name": "Subscription A", "environment": "production"}}
    per_sub_ranges = {
        "sub-a": [
            (_date(2026, 1, 1), _date(2026, 1, 31)),
            (_date(2026, 2, 1), _date(2026, 2, 28)),
            (_date(2026, 3, 1), _date(2026, 3, 31)),
        ]
    }
    end_date = _date(2026, 3, 31)

    rows, failures, successful = await service._load_rows_incremental(sub_metadata, per_sub_ranges, end_date)

    # 3 explicit ranges → 3 API calls, one per range
    scope = "/subscriptions/sub-a"
    assert len(call_args) == 3
    assert call_args[0] == (scope, _date(2026, 1, 1), _date(2026, 1, 31))
    assert call_args[1] == (scope, _date(2026, 2, 1), _date(2026, 2, 28))
    assert call_args[2] == (scope, _date(2026, 3, 1), _date(2026, 3, 31))

    # One row returned per range → 3 total rows
    assert len(rows) == 3
    assert len(failures) == 0
    assert rows[0]["subscription_id"] == "sub-a"
    assert rows[0]["subscription_name"] == "Subscription A"
    assert rows[0]["resource_name"] == ""  # no real resource name; empty instead of meter_category fallback


@pytest.mark.anyio
async def test_get_sync_status_includes_monitored_subscription_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _SyncRecord:
        started_at = None
        completed_at = None
        status = "completed"
        months_synced = 2
        rows_synced = 12
        total_cost = 145.6
        triggered_by = "manual"
        error_message = None

    db = _FakeSession(execute_results=[_SyncRecord()])
    service = AmortizedCostSyncService(db)

    async def fake_get_monitored_subscription_ids() -> list[str]:
        return ["sub-a", "sub-b"]

    monkeypatch.setattr(
        "app.services.amortized_cost_sync_service.get_monitored_subscription_ids",
        fake_get_monitored_subscription_ids,
    )

    payload = await service.get_sync_status()

    assert payload["status"] == "completed"
    assert payload["monitored_subscription_count"] == 2
    assert payload["monitored_subscription_ids"] == ["sub-a", "sub-b"]


def test_derive_env_label_prefers_admin_environment_metadata() -> None:
    assert (
        AmortizedCostSyncService._derive_env_label(
            {
                "environment": "non-production",
                "subscription_name": "ATTCC Production Shared",
                "subscription_id": "sub-nonprod",
            }
        )
        == "Non-Prod"
    )

    assert (
        AmortizedCostSyncService._derive_env_label(
            {
                "environment": "production",
                "subscription_name": "ATTCC Sandbox",
                "subscription_id": "sub-prod",
            }
        )
        == "Prod"
    )


def test_get_rolling_start_date_uses_today_aligned_calendar_months() -> None:
    assert AmortizedCostSyncService._get_rolling_start_date(date(2026, 4, 19), 2) == date(2026, 2, 19)
    assert AmortizedCostSyncService._get_rolling_start_date(date(2026, 4, 19), 3) == date(2026, 1, 19)


def test_get_rolling_start_date_clamps_day_for_shorter_month() -> None:
    # Jan 31 minus two months should clamp to Nov 30.
    assert AmortizedCostSyncService._get_rolling_start_date(date(2026, 1, 31), 2) == date(2025, 11, 30)


def test_derive_env_label_uses_budget_config_non_prod_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        AmortizedCostSyncService,
        "_load_non_prod_subscription_ids",
        staticmethod(lambda: {"sub-nonprod"}),
    )

    assert (
        AmortizedCostSyncService._derive_env_label(
            {
                "environment": "",
                "subscription_name": "ATTCC Production Shared",
                "subscription_id": "sub-nonprod",
            }
        )
        == "Non-Prod"
    )


@pytest.mark.anyio
async def test_load_rows_from_db_compares_cost_date_as_string_not_date() -> None:
    """Regression: cost_date is VARCHAR(10). The WHERE clause must compare with a
    string, not a datetime.date, to avoid 'operator does not exist: character
    varying >= date' on PostgreSQL.
    """
    captured_statements: list = []

    class _ScalarsProxy:
        def all(self):
            return []

    class _ResultProxy:
        def scalars(self):
            return _ScalarsProxy()

    class _CapturingSession:
        async def execute(self, statement):
            captured_statements.append(statement)
            return _ResultProxy()

    svc = AmortizedCostSyncService(_CapturingSession())  # type: ignore[arg-type]
    await svc._load_rows_from_db(env="ALL", months=2)

    assert len(captured_statements) == 1
    compiled = captured_statements[0].compile(compile_kwargs={"literal_binds": True})
    sql_text = str(compiled)
    # The bound value must be a quoted string like '2026-02-19', not a bare
    # date literal that SQLAlchemy would cast via $1::DATE.
    assert "'>=" in sql_text or ">= '" in sql_text, f"Expected string comparison in WHERE clause, got: {sql_text}"


def test_derive_env_label_treats_nprd_subscription_name_as_non_prod(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        AmortizedCostSyncService,
        "_load_non_prod_subscription_ids",
        staticmethod(lambda: set()),
    )

    assert (
        AmortizedCostSyncService._derive_env_label(
            {
                "environment": "",
                "subscription_name": "ACC-NPRD-17805-DWS",
                "subscription_id": "sub-dws-nprd",
            }
        )
        == "Non-Prod"
    )

    assert (
        AmortizedCostSyncService._derive_env_label(
            {
                "environment": "",
                "subscription_name": "ACC-PROD-17805-DWS",
                "subscription_id": "sub-dws-prod",
            }
        )
        == "Prod"
    )


def test_build_analytics_extends_date_range_to_today_for_selected_months() -> None:
    rows = [
        {
            "date": "2026-03-30",
            "cost": 10.0,
            "meter_category": "Compute",
            "meter_subcategory": "",
            "meter_name": "",
            "resource_group": "rg-a",
            "resource_name": "vm-a",
            "resource_type": "Microsoft.Compute/virtualMachines",
            "resource_location": "eastus",
            "subscription_name": "Sub A",
            "subscription_id": "sub-a",
            "service_name": "Compute",
            "charge_type": "Usage",
            "pricing_model": "OnDemand",
            "publisher_type": "Azure",
            "frequency": "UsageBased",
            "currency": "USD",
            "env_label": "Prod",
        },
        {
            "date": "2026-03-31",
            "cost": 20.0,
            "meter_category": "Compute",
            "meter_subcategory": "",
            "meter_name": "",
            "resource_group": "rg-a",
            "resource_name": "vm-a",
            "resource_type": "Microsoft.Compute/virtualMachines",
            "resource_location": "eastus",
            "subscription_name": "Sub A",
            "subscription_id": "sub-a",
            "service_name": "Compute",
            "charge_type": "Usage",
            "pricing_model": "OnDemand",
            "publisher_type": "Azure",
            "frequency": "UsageBased",
            "currency": "USD",
            "env_label": "Prod",
        },
    ]

    payload = AmortizedCostSyncService._build_analytics(
        rows,
        env="ALL",
        months=2,
        as_of=date(2026, 4, 19),
    )

    assert payload["date_range"] == {"start": "2026-02-19", "end": "2026-04-19"}
    assert payload["source_date_range"] == {"start": "2026-03-30", "end": "2026-03-31"}
    assert payload["latest_available_date"] == "2026-03-31"
    assert payload["has_pending_source_data"] is True
    assert payload["daily_trend"][-1]["date"] == "2026-04-19"
    assert payload["daily_trend"][-1]["cost"] == 0.0
    assert payload["daily_trend"][-1]["prod"] == 0.0
    assert payload["daily_by_service"][-1]["Compute"] == 0.0


def test_build_analytics_returns_requested_window_when_rows_are_empty() -> None:
    payload = AmortizedCostSyncService._build_analytics(
        [],
        env="ALL",
        months=3,
        as_of=date(2026, 4, 19),
    )

    assert payload["date_range"] == {"start": "2026-01-19", "end": "2026-04-19"}
    assert payload["source_date_range"] == {"start": "", "end": ""}
    assert payload["latest_available_date"] is None
    assert payload["has_pending_source_data"] is False


def test_split_into_monthly_chunks_covers_all_months() -> None:
    chunks = AmortizedCostSyncService._split_into_monthly_chunks(date(2026, 1, 15), date(2026, 3, 31))
    assert chunks == [
        (date(2026, 1, 15), date(2026, 1, 31)),
        (date(2026, 2, 1), date(2026, 2, 28)),
        (date(2026, 3, 1), date(2026, 3, 31)),
    ]


def test_split_into_monthly_chunks_single_month() -> None:
    chunks = AmortizedCostSyncService._split_into_monthly_chunks(date(2026, 4, 20), date(2026, 4, 27))
    assert chunks == [(date(2026, 4, 20), date(2026, 4, 27))]


def test_split_into_monthly_chunks_year_boundary() -> None:
    chunks = AmortizedCostSyncService._split_into_monthly_chunks(date(2025, 12, 15), date(2026, 1, 31))
    assert chunks == [
        (date(2025, 12, 15), date(2025, 12, 31)),
        (date(2026, 1, 1), date(2026, 1, 31)),
    ]


@pytest.mark.anyio
async def test_load_rows_incremental_partial_month_failure_preserves_successful_chunks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If one monthly chunk gets 429, rows from other chunks are still returned.
    The sub is NOT added to failed_sub_ids as long as at least one chunk succeeded.
    """
    from datetime import date as _date

    db = _FakeSession()
    service = AmortizedCostSyncService(db)

    call_num = 0

    async def fake_query(scope: str, start_date, end_date) -> list[dict]:
        nonlocal call_num
        call_num += 1
        if call_num == 1:
            raise RuntimeError("(429) Too many requests")
        return [
            {
                "date": start_date.isoformat(),
                "cost": 5.0,
                "meter_category": "Compute",
                "meter_subcategory": "",
                "meter_name": "",
                "resource_group": "rg",
                "resource_name": "vm",
                "resource_type": "",
                "resource_location": "",
                "subscription_name": "",
                "subscription_id": "",
                "service_name": "Compute",
                "charge_type": "Usage",
                "pricing_model": "",
                "publisher_type": "Azure",
                "frequency": "UsageBased",
                "currency": "USD",
            }
        ]

    monkeypatch.setattr(service._cost_service, "query_amortized_cost_rows", fake_query)

    sub_metadata = {"sub-x": {"subscription_name": "Sub X", "environment": "production"}}
    per_sub_ranges = {
        "sub-x": [
            (_date(2026, 1, 1), _date(2026, 1, 31)),
            (_date(2026, 2, 1), _date(2026, 2, 28)),
        ]
    }
    end_date = _date(2026, 2, 28)

    rows, failures, successful = await service._load_rows_incremental(sub_metadata, per_sub_ranges, end_date)

    # Jan chunk failed (429), Feb chunk succeeded → sub-x not in failures
    assert "sub-x" not in failures
    assert len(rows) == 1  # Only Feb row returned
    assert rows[0]["subscription_id"] == "sub-x"
