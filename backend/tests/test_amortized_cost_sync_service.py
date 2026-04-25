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
async def test_full_sync_filters_rows_to_monitored_subscriptions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = _FakeSession()
    service = AmortizedCostSyncService(db)

    sample_rows = [
        {
            "date": "2026-03-01",
            "cost": 10.5,
            "meter_category": "Compute",
            "meter_subcategory": "VM",
            "meter_name": "D2s_v5",
            "resource_group": "rg-a",
            "resource_name": "vm-a",
            "resource_type": "Microsoft.Compute/virtualMachines",
            "resource_location": "eastus",
            "subscription_name": "Subscription A",
            "subscription_id": "sub-a",
            "service_name": "Virtual Machines",
            "charge_type": "Usage",
            "pricing_model": "OnDemand",
            "publisher_type": "Azure",
            "frequency": "UsageBased",
            "currency": "USD",
            "env_label": "Prod",
        },
        {
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
        },
    ]

    async def fake_load_rows_from_azure_api(months: int) -> list[dict]:
        assert months == 2
        return [sample_rows[1]]

    async def fake_invalidate(_pattern: str) -> None:
        return None

    monkeypatch.setattr(
        service,
        "_load_rows_from_azure_api",
        fake_load_rows_from_azure_api,
    )
    monkeypatch.setattr(
        "app.services.amortized_cost_sync_service.cache_manager.invalidate",
        fake_invalidate,
    )

    result = await service.full_sync(months=2, triggered_by="manual")

    assert result["status"] == "completed"
    assert result["rows_synced"] == 1
    assert result["total_cost"] == 22.0
    assert result["duration_seconds"] >= 0
    assert any("amortized_cost_records" in str(statement) for statement in db.executed)
    assert len(db.bulk_added) == 1
    assert db.bulk_added[0].subscription_id == "sub-b"


@pytest.mark.anyio
async def test_load_rows_from_azure_api_uses_query_api_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = _FakeSession(execute_results=[[("sub-a", "Subscription A", "production")]])
    service = AmortizedCostSyncService(db)
    call_count = 0

    async def fake_get_monitored_subscription_ids() -> list[str]:
        return ["sub-a"]

    async def fake_query_amortized_cost_rows(scope: str, start_date, end_date) -> list[dict]:
        nonlocal call_count
        call_count += 1
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

    monkeypatch.setattr(
        "app.services.amortized_cost_sync_service.get_monitored_subscription_ids",
        fake_get_monitored_subscription_ids,
    )
    monkeypatch.setattr(service._cost_service, "query_amortized_cost_rows", fake_query_amortized_cost_rows)

    rows = await service._load_rows_from_azure_api(months=2)

    assert len(rows) == 1
    assert call_count >= 1
    assert rows[0]["subscription_id"] == "sub-a"
    assert rows[0]["subscription_name"] == "Subscription A"
    assert rows[0]["resource_name"] == "Storage"


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
