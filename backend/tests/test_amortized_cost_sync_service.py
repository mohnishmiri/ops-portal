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

    async def rollback(self) -> None:
        return None

    async def scalar(self, statement):
        self.executed.append(statement)
        return

    async def flush(self) -> None:
        return None


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

    # First execute is the UPDATE that expires abandoned 'running' rows
    # (consumes its slot with no scalars), second is the SELECT for status.
    db = _FakeSession(execute_results=[None, _SyncRecord()])
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


def test_derive_env_label_uses_admin_environment_value() -> None:
    """AdminSubscription.environment (passed via the row's 'environment' key)
    is the source of truth. No budget_config.json lookup, no subscription_id
    list — just normalise whatever the admin tagged the sub with."""
    assert (
        AmortizedCostSyncService._derive_env_label(
            {
                "environment": "non-production",
                "subscription_name": "ATTCC Production Shared",
                "subscription_id": "any-sub-id",
            }
        )
        == "Non-Prod"
    )
    assert (
        AmortizedCostSyncService._derive_env_label(
            {
                "environment": "production",
                "subscription_name": "ATTCC Sandbox",
                "subscription_id": "any-sub-id",
            }
        )
        == "Prod"
    )


def test_resolve_env_label_uses_name_when_admin_env_empty() -> None:
    """When AdminSubscription.environment is empty (very common after bulk
    Discover-from-Azure), fall back to the subscription name pattern.
    This is the contract that lets ACC-NPRD-… subs classify as Non-Prod
    even without an admin manually tagging them."""
    r = AmortizedCostSyncService.resolve_env_label

    # Admin env empty → name decides.
    assert r("", "ACC-NPRD-31599-ATTCC") == "Non-Prod"
    assert r(None, "ACC-PROD-31599-ATTCC") == "Prod"
    assert r("   ", "ACC-NPRD-17805-DWS") == "Non-Prod"

    # Admin env set → wins over name.
    assert r("production", "ACC-NPRD-31599-ATTCC") == "Prod"
    assert r("non-production", "ACC-PROD-31599-ATTCC") == "Non-Prod"

    # Both empty → defaults to Prod (never hide spend).
    assert r(None, None) == "Prod"
    assert r("", "") == "Prod"


def test_normalize_environment_recognises_common_aliases() -> None:
    n = AmortizedCostSyncService.normalize_environment
    assert n("prod") == "Prod"
    assert n("Production") == "Prod"
    assert n("PRD") == "Prod"
    assert n("non-prod") == "Non-Prod"
    assert n("Non Production") == "Non-Prod"
    assert n("nprd") == "Non-Prod"
    assert n("Development") == "Non-Prod"
    assert n("staging") == "Non-Prod"
    assert n("UAT") == "Non-Prod"
    # Unknown / empty → default to Prod so spend is never hidden.
    assert n(None) == "Prod"
    assert n("") == "Prod"
    assert n("   ") == "Prod"
    assert n("something-completely-different") == "Prod"


def test_get_rolling_start_date_uses_today_aligned_calendar_months() -> None:
    assert AmortizedCostSyncService._get_rolling_start_date(date(2026, 4, 19), 2) == date(2026, 2, 19)
    assert AmortizedCostSyncService._get_rolling_start_date(date(2026, 4, 19), 3) == date(2026, 1, 19)


def test_get_rolling_start_date_clamps_day_for_shorter_month() -> None:
    # Jan 31 minus two months should clamp to Nov 30.
    assert AmortizedCostSyncService._get_rolling_start_date(date(2026, 1, 31), 2) == date(2025, 11, 30)


def test_derive_env_label_falls_back_to_name_when_environment_missing() -> None:
    """When AdminSubscription.environment is empty and no prior env_label is
    set, fall back to the subscription name. Used for live Azure responses
    that don't carry admin metadata yet."""
    assert (
        AmortizedCostSyncService._derive_env_label(
            {
                "environment": "",
                "subscription_name": "ATTCC NPRD Shared",
                "subscription_id": "any-sub-id",
            }
        )
        == "Non-Prod"
    )


def test_derive_env_label_admin_environment_wins_over_name() -> None:
    """If admin tagged a sub as 'production' in the Admin panel, that beats
    a 'NPRD' substring in the name. AdminSubscription.environment is the
    source of truth."""
    assert (
        AmortizedCostSyncService._derive_env_label(
            {
                "environment": "production",
                "subscription_name": "ACC-NPRD-17805-DWS",
                "subscription_id": "any-sub-id",
            }
        )
        == "Prod"
    )

    # Conversely, admin tagging as 'non-production' beats a 'PROD' name.
    assert (
        AmortizedCostSyncService._derive_env_label(
            {
                "environment": "non-production",
                "subscription_name": "ACC-PROD-17805-DWS",
                "subscription_id": "any-sub-id",
            }
        )
        == "Non-Prod"
    )


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
