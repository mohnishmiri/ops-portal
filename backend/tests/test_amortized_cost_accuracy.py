"""
Accuracy tests for the amortized cost pipeline: Azure fetch → reconcile →
store → dashboards / leadership / export.

Backed by an in-memory SQLite database so the real SQL aggregates run.
"""

import csv
import io
from datetime import date, timedelta
from types import SimpleNamespace

import pytest
from azure.core.exceptions import HttpResponseError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.models.database import (
    AdminSubscription,
    AmortizedCostDailySummary,
    AmortizedCostMonthlySummary,
    AmortizedCostPricingDaily,
    AmortizedCostRecord,
    AmortizedCostSyncStatus,
    AmortizedCostWeeklySummary,
)
from app.services import amortized_cost_sync_service as module
from app.services.amortized_cost_sync_service import AmortizedCostSyncService
from app.services.cost_service import AmortizedCostDetail, CostService, _throttle_wait_seconds

AS_OF = date(2026, 10, 8)  # "today" in UTC for every test
PROD, NONPROD = "sub-prod-0000", "sub-nprd-0000"

_TABLES = (
    AdminSubscription,
    AmortizedCostRecord,
    AmortizedCostPricingDaily,
    AmortizedCostSyncStatus,
    AmortizedCostDailySummary,
    AmortizedCostWeeklySummary,
    AmortizedCostMonthlySummary,
)


@pytest.fixture
async def db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", connect_args={"check_same_thread": False})
    async with engine.begin() as conn:
        for model in _TABLES:
            await conn.run_sync(lambda c, m=model: m.__table__.create(c, checkfirst=True))
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


@pytest.fixture(autouse=True)
def _environment(monkeypatch: pytest.MonkeyPatch):
    async def monitored():
        return [PROD, NONPROD]

    async def no_cache(*_args, **_kwargs):
        return None

    async def ttl(_db):
        return 60

    async def acquire(_session, _name):
        return True

    async def release(_session, _name):
        return None

    monkeypatch.setattr(module, "utc_today", lambda: AS_OF)
    monkeypatch.setattr(module, "get_monitored_subscription_ids", monitored)
    monkeypatch.setattr(module, "get_scoped_subscription_ids", monitored)
    monkeypatch.setattr(module.cache_manager, "get_cached", no_cache)
    monkeypatch.setattr(module.cache_manager, "set_cached", no_cache)
    monkeypatch.setattr(module.cache_manager, "invalidate", no_cache)
    monkeypatch.setattr(module, "get_effective_cache_ttl_seconds", ttl)
    monkeypatch.setattr("app.core.sync_lock.try_acquire_advisory_lock", acquire)
    monkeypatch.setattr("app.core.sync_lock.release_advisory_lock", release)


async def _admin(db: AsyncSession) -> None:
    db.add_all(
        [
            AdminSubscription(subscription_id=PROD, subscription_name="ACC-PROD-1", environment="production"),
            # No environment set: classified from the ACC-NPRD name.
            AdminSubscription(subscription_id=NONPROD, subscription_name="ACC-NPRD-1", environment=None),
        ]
    )
    await db.commit()


def _rec(day: str, sub: str, cost: float, **overrides) -> AmortizedCostRecord:
    values = {
        "cost_date": day,
        "cost_amount": cost,
        "subscription_id": sub,
        "subscription_name": "ACC-PROD-1" if sub == PROD else "ACC-NPRD-1",
        "env_label": "Prod" if sub == PROD else "Non-Prod",
        "resource_group": "rg-app",
        "resource_name": "vm-1",
        "meter_category": "Virtual Machines",
        "resource_type": "Microsoft.Compute/virtualMachines",
        "resource_location": "eastus2",
        "currency": "USD",
    }
    values.update(overrides)
    return AmortizedCostRecord(**values)


def _price(day: str, sub: str, model: str, cost: float) -> AmortizedCostPricingDaily:
    return AmortizedCostPricingDaily(
        cost_date=day, subscription_id=sub, pricing_model=model, charge_type="Usage", cost_amount=cost
    )


async def _rows_on(db: AsyncSession, day: str) -> list[AmortizedCostRecord]:
    return (await db.execute(select(AmortizedCostRecord).where(AmortizedCostRecord.cost_date == day))).scalars().all()


def _days(start: date, end: date):
    d = start
    while d <= end:
        yield d
        d += timedelta(days=1)


def _detail(rows: list[tuple[str, float, str]], pricing: dict[str, float] | None = None) -> AmortizedCostDetail:
    """Azure fetch result; pricing defaults to OnDemand totals that reconcile."""
    detail = AmortizedCostDetail(location_enriched=True)
    for day, cost, resource in rows:
        detail.rows.append(
            {
                "date": day,
                "cost": cost,
                "meter_category": "Storage",
                "resource_group": "rg-data",
                "resource_name": resource,
                "resource_type": "Microsoft.Storage/storageAccounts",
                "resource_location": "eastus2",
                "service_name": "Storage",
                "currency": "USD",
            }
        )
    totals = pricing if pricing is not None else {r["date"]: 0.0 for r in detail.rows}
    if pricing is None:
        for r in detail.rows:
            totals[r["date"]] += r["cost"]
    detail.pricing_rows = [
        {"date": day, "pricing_model": "OnDemand", "charge_type": "Usage", "cost": cost, "currency": "USD"}
        for day, cost in totals.items()
    ]
    return detail


def _sync_service(db, monkeypatch, ranges, fetch) -> AmortizedCostSyncService:
    service = AmortizedCostSyncService(db)

    async def fake_ranges(_ids, _start, _end):
        return ranges

    async def no_rebuild(_triggered_by):
        return None

    monkeypatch.setattr(service, "_compute_fetch_ranges", fake_ranges)
    monkeypatch.setattr(service, "_rebuild_leadership_snapshot", no_rebuild)
    monkeypatch.setattr(service._cost_service, "query_amortized_cost_detail", fetch)
    return service


# ── Sync: reconcile, replace, relabel ─────────────────────────────────


@pytest.mark.anyio
async def test_full_sync_stores_full_precision_rows_and_relabels_history(db, monkeypatch):
    await _admin(db)
    # Written before the subscription was registered: GUID name, default Prod label.
    db.add(_rec("2026-08-15", NONPROD, 40.0, subscription_name=NONPROD, env_label="Prod"))
    await db.commit()

    async def fetch(scope, start, end):
        assert scope == f"/subscriptions/{NONPROD}"
        # Sub-cent rows used to be rounded to $0.00 and dropped.
        return _detail([("2026-10-01", 1.2345, "st-a"), ("2026-10-01", 0.004, "st-b"), ("2026-10-02", 2.0, "st-a")])

    service = _sync_service(db, monkeypatch, {NONPROD: [(date(2026, 10, 1), AS_OF)]}, fetch)
    result = await service.full_sync(months=1, subscription_ids=[NONPROD])

    assert result["status"] == "completed"
    assert result["partial_failures"] == 0
    assert result["rows_synced"] == 3
    rows = await _rows_on(db, "2026-10-01") + await _rows_on(db, "2026-10-02")
    assert sum(r.cost_amount for r in rows) == pytest.approx(3.2385)
    assert {r.env_label for r in rows} == {"Non-Prod"}
    pricing = (await db.execute(select(AmortizedCostPricingDaily))).scalars().all()
    assert sum(p.cost_amount for p in pricing) == pytest.approx(3.2385)

    (historical,) = await _rows_on(db, "2026-08-15")
    assert (historical.subscription_name, historical.env_label) == ("ACC-NPRD-1", "Non-Prod")
    assert result["relabeled_rows"] == 1


@pytest.mark.anyio
async def test_range_that_does_not_reconcile_keeps_previous_data_and_is_reported(db, monkeypatch):
    await _admin(db)
    db.add(_rec("2026-09-20", PROD, 50.0))
    # Already priced, so the pricing backfill doesn't widen the range.
    db.add(_price("2026-09-20", PROD, "OnDemand", 50.0))
    await db.commit()
    calls: list[date] = []

    async def fetch(scope, start, end):
        calls.append(start)
        if start == date(2026, 9, 20):
            # Resource rows add up to $10 but Azure's total says $20: rows were lost.
            return _detail([("2026-09-20", 10.0, "vm-1")], pricing={"2026-09-20": 20.0})
        return _detail([("2026-10-01", 5.0, "vm-1")])

    ranges = {PROD: [(date(2026, 9, 20), date(2026, 9, 25)), (date(2026, 10, 1), AS_OF)]}
    service = _sync_service(db, monkeypatch, ranges, fetch)
    result = await service.full_sync(months=1, subscription_ids=[PROD])

    assert result["status"] == "completed"
    assert result["partial_failures"] == 1
    assert "did not reconcile" in result["failed_ranges"][0]["error"]
    assert calls.count(date(2026, 9, 20)) == 2  # refetched once before giving up
    (kept,) = await _rows_on(db, "2026-09-20")
    assert kept.cost_amount == 50.0
    status = (await db.execute(select(AmortizedCostSyncStatus))).scalar_one()
    assert status.status == "completed"
    assert status.error_message.startswith("Partial sync: 1 of 2 date ranges failed")


@pytest.mark.anyio
async def test_sync_fails_when_every_range_fails(db, monkeypatch):
    await _admin(db)

    async def fetch(scope, start, end):
        raise RuntimeError("HTTP 429 too many requests")

    service = _sync_service(db, monkeypatch, {PROD: [(date(2026, 10, 1), AS_OF)]}, fetch)
    result = await service.full_sync(months=1, subscription_ids=[PROD])

    assert result["status"] == "failed"
    assert "429" in result["error"]
    status = (await db.execute(select(AmortizedCostSyncStatus))).scalar_one()
    assert status.status == "failed"


@pytest.mark.anyio
async def test_ranges_run_newest_first(db, monkeypatch):
    await _admin(db)
    order: list[date] = []

    async def fetch(scope, start, end):
        order.append(start)
        return _detail([(start.isoformat(), 1.0, "vm-1")])

    ranges = {
        PROD: [(date(2026, 8, 1), date(2026, 8, 31)), (date(2026, 10, 1), AS_OF)],
        NONPROD: [(date(2026, 9, 1), date(2026, 9, 30))],
    }
    service = _sync_service(db, monkeypatch, ranges, fetch)
    await service.full_sync(months=3)

    assert order == [date(2026, 10, 1), date(2026, 9, 1), date(2026, 8, 1)]


@pytest.mark.anyio
async def test_rows_dated_outside_the_range_are_never_stored(db, monkeypatch):
    await _admin(db)

    async def fetch(scope, start, end):
        return _detail([("2026-10-01", 5.0, "vm-1"), ("2026-09-15", 9.0, "vm-1")])

    service = _sync_service(db, monkeypatch, {PROD: [(date(2026, 10, 1), AS_OF)]}, fetch)
    result = await service.full_sync(months=1, subscription_ids=[PROD])

    assert result["status"] == "completed"
    stored = (await db.execute(select(AmortizedCostRecord))).scalars().all()
    assert [(r.cost_date, r.cost_amount) for r in stored] == [("2026-10-01", 5.0)]


@pytest.mark.anyio
async def test_replace_range_rolls_back_on_insert_failure(db):
    db.add(_rec("2026-10-02", PROD, 50.0))
    await db.commit()
    service = AmortizedCostSyncService(db)
    broken = _detail([("2026-10-02", 1.0, "vm-1")])
    broken.rows[0]["date"] = None  # violates NOT NULL on cost_date

    with pytest.raises(IntegrityError):
        await service._replace_range(PROD, "ACC-PROD-1", "Prod", date(2026, 10, 1), AS_OF, broken)

    kept = (await db.execute(select(AmortizedCostRecord))).scalars().all()
    assert [r.cost_amount for r in kept] == [50.0]


@pytest.mark.anyio
async def test_days_without_pricing_rollup_are_queued_for_refetch(db):
    db.add_all([_rec("2026-08-05", PROD, 1.0), _rec("2026-08-20", PROD, 1.0), _rec("2026-09-05", PROD, 1.0)])
    db.add(_price("2026-09-05", PROD, "OnDemand", 1.0))
    await db.commit()
    service = AmortizedCostSyncService(db)
    ranges = {PROD: [(date(2026, 8, 10), date(2026, 8, 12)), (date(2026, 10, 1), AS_OF)]}

    added = await service._add_pricing_backfill_ranges(ranges, [PROD], date(2026, 7, 8), AS_OF)

    assert added == 1
    # Aug 5–20 is refetched, swallowing the Aug 10–12 hole; September is already priced.
    assert sorted(ranges[PROD]) == [(date(2026, 8, 5), date(2026, 8, 20)), (date(2026, 10, 1), AS_OF)]


@pytest.mark.anyio
async def test_partly_backfilled_month_is_finished_by_a_later_sync(db):
    # A 1-month sync on Oct 8 repaired Sep 8–30; Sep 1–7 still hold legacy rows.
    db.add_all([_rec(d.isoformat(), PROD, 1.0) for d in _days(date(2026, 9, 1), date(2026, 9, 30))])
    db.add_all([_price(d.isoformat(), PROD, "OnDemand", 1.0) for d in _days(date(2026, 9, 8), date(2026, 9, 30))])
    await db.commit()
    ranges = {PROD: [(date(2026, 10, 1), AS_OF)]}

    await AmortizedCostSyncService(db)._add_pricing_backfill_ranges(ranges, [PROD], date(2025, 10, 8), AS_OF)

    assert sorted(ranges[PROD]) == [(date(2026, 9, 1), date(2026, 9, 7)), (date(2026, 10, 1), AS_OF)]


@pytest.mark.anyio
async def test_failed_location_query_keeps_known_locations(db, monkeypatch):
    await _admin(db)
    db.add(_rec("2026-09-01", PROD, 5.0, resource_group="rg-data", resource_name="st-a", resource_location="westus3"))
    await db.commit()

    async def fetch(scope, start, end):
        detail = _detail([("2026-10-01", 2.0, "st-a")])
        detail.location_enriched = False  # the best-effort location query failed
        for row in detail.rows:
            row["resource_location"] = ""
        return detail

    service = _sync_service(db, monkeypatch, {PROD: [(date(2026, 10, 1), AS_OF)]}, fetch)
    await service.full_sync(months=1, subscription_ids=[PROD])

    (row,) = await _rows_on(db, "2026-10-01")
    assert row.resource_location == "westus3"


# ── Dashboard analytics ───────────────────────────────────────────────


async def _seed_dashboard(db: AsyncSession) -> None:
    await _admin(db)
    rows = [
        # Stale history: GUID name + wrong Prod label for the non-prod subscription.
        _rec("2026-09-10", NONPROD, 30.0, subscription_name=NONPROD, env_label="Prod", resource_name="aks-np"),
        _rec("2026-10-07", NONPROD, 20.0, resource_name="aks-np"),
        _rec("2026-09-10", PROD, 100.0),
        _rec("2026-10-07", PROD, 100.0),
        _rec("2026-10-07", PROD, 7.5, resource_group="", resource_name="", meter_category="Support", resource_type=""),
        # Today (UTC) is still being ingested and must be excluded.
        _rec("2026-10-08", PROD, 999.0),
    ]
    db.add_all(rows)
    db.add_all(
        [
            _price("2026-10-07", PROD, "SavingsPlan", 60.0),
            _price("2026-10-07", PROD, "OnDemand", 47.5),
            _price("2026-10-07", NONPROD, "Reservation", 20.0),
        ]
    )
    await db.commit()


@pytest.mark.anyio
async def test_dashboard_excludes_today_and_resolves_names_from_admin(db):
    await _seed_dashboard(db)
    payload = await AmortizedCostSyncService(db).get_amortized_cost_data(env="ALL", months=1)

    assert payload["date_range"] == {"start": "2026-09-08", "end": "2026-10-07"}
    assert payload["total_cost"] == 257.5  # the $999 row dated today is excluded
    assert payload["data_through"] == "2026-10-07"
    subs = {s["name"]: s["cost"] for s in payload["subscription_breakdown"]}
    assert subs == {"ACC-PROD-1": 207.5, "ACC-NPRD-1": 50.0}  # one row per subscription, no GUID
    # The mislabelled September row counts as Non-Prod via the Admin panel.
    assert payload["env_comparison"]["totals"] == {"Prod": 207.5, "Non-Prod": 50.0}


@pytest.mark.anyio
async def test_dashboard_env_filter_uses_admin_classification(db):
    await _seed_dashboard(db)
    payload = await AmortizedCostSyncService(db).get_amortized_cost_data(env="NONPROD", months=1)
    assert payload["total_cost"] == 50.0


@pytest.mark.anyio
async def test_dashboard_reports_gaps_instead_of_zero_days(db):
    await _seed_dashboard(db)
    payload = await AmortizedCostSyncService(db).get_amortized_cost_data(env="ALL", months=1)

    trend = {p["date"]: p for p in payload["daily_trend"]}
    assert trend["2026-09-11"]["cost"] is None  # no data: a gap, not $0
    assert trend["2026-10-07"]["cost"] == 127.5
    assert trend["2026-10-07"]["non_prod"] == 20.0
    assert trend["2026-10-04"]["preliminary"] is False
    assert trend["2026-10-05"]["preliminary"] is True
    coverage = payload["coverage"]
    assert coverage["complete"] is False
    assert {i["subscription_name"] for i in coverage["issues"]} == {"ACC-PROD-1", "ACC-NPRD-1"}
    assert coverage["issues"][0]["missing_days"] == 28


@pytest.mark.anyio
async def test_dashboard_counts_partial_months_and_pricing_mix(db):
    await _seed_dashboard(db)
    payload = await AmortizedCostSyncService(db).get_amortized_cost_data(env="ALL", months=1)

    assert payload["service_count"] == 2
    assert payload["resource_count"] == 2  # vm-1 and aks-np; the unnamed Support charge isn't a resource
    coverage = payload["monthly_pivot"]["month_coverage"]
    assert coverage["2026-09"] == {
        "start": "2026-09-08",
        "end": "2026-09-30",
        "days": 23,
        "days_in_month": 30,
        "partial": True,
    }
    assert coverage["2026-10"]["partial"] is True
    assert payload["monthly_pivot"]["grand_total"] == payload["total_cost"]
    pricing = {p["name"]: p["cost"] for p in payload["pricing_model_breakdown"]}
    assert pricing == {"SavingsPlan": 60.0, "OnDemand": 47.5, "Reservation": 20.0}
    assert payload["commitment"]["covered_pct"] == pytest.approx(62.75, abs=0.01)


@pytest.mark.anyio
async def test_drilldown_matches_unknown_groups_and_resolved_subscription_names(db):
    await _seed_dashboard(db)
    service = AmortizedCostSyncService(db)

    unknown_rg = await service.get_resource_drilldown(env="ALL", months=1, resource_group="Unknown")
    assert unknown_rg["total_cost"] == 7.5

    by_name = await service.get_resource_drilldown(env="ALL", months=1, subscription="ACC-NPRD-1")
    assert by_name["total_cost"] == 50.0  # includes the GUID-named history


@pytest.mark.anyio
async def test_daily_export_reconciles_with_dashboard_total(db):
    await _seed_dashboard(db)
    service = AmortizedCostSyncService(db)
    payload = await service.get_amortized_cost_data(env="ALL", months=1)

    spec = await service.build_export_spec(env="ALL", months=1)
    text = "".join([chunk async for chunk in service.iter_export_csv(spec, "daily")])
    rows = list(csv.DictReader(io.StringIO(text)))
    assert round(sum(float(r["Cost (USD)"]) for r in rows), 2) == payload["total_cost"]
    assert {r["Subscription"] for r in rows} == {"ACC-PROD-1", "ACC-NPRD-1"}

    text = "".join([chunk async for chunk in service.iter_export_csv(spec, "resources")])
    resources = list(csv.DictReader(io.StringIO(text)))
    assert round(sum(float(r["Cost (USD)"]) for r in resources), 2) == payload["total_cost"]
    assert service.export_filename(spec, "daily") == "amortized-cost-daily-all-2026-09-08-to-2026-10-07.csv"


# ── Leadership (Cost Forecast) ────────────────────────────────────────


async def _seed_leadership(db: AsyncSession) -> None:
    await _admin(db)
    rows = [_rec(d.isoformat(), PROD, 90.0) for d in _days(date(2026, 8, 1), date(2026, 8, 31))]
    rows += [_rec(d.isoformat(), PROD, 100.0) for d in _days(date(2026, 9, 1), date(2026, 9, 30))]
    rows += [_rec(d.isoformat(), PROD, 110.0) for d in _days(date(2026, 10, 1), date(2026, 10, 7))]
    rows.append(_rec("2026-10-08", PROD, 5.0))  # partial current UTC day
    db.add_all(rows)
    await db.commit()


@pytest.mark.anyio
async def test_leadership_compares_like_for_like_days(db):
    await _seed_leadership(db)
    dashboard = await AmortizedCostSyncService(db).build_leadership_dashboard(subscription_ids=[PROD])
    kpis = {k.name: k for k in dashboard.kpis}

    assert float(kpis["Month-to-Date Spend"].value) == 770.0  # Oct 1–7, today excluded
    # Oct 1–7 ($770) vs Sep 1–7 ($700) — not vs all of September ($3,000).
    assert kpis["Month-over-Month Change"].value == 10.0
    assert kpis["Month-to-Date Spend"].comparison_label == "vs Sep 1 – Sep 7, 2026"
    assert float(kpis["Projected Monthly Spend"].value) == 3410.0  # $110/day × 31
    assert float(kpis["Last Month Spend"].value) == 3000.0
    assert kpis["Last Month Spend"].change_pct == 7.5  # vs August's $2,790
    assert dashboard.data_through == date(2026, 10, 7)
    assert dashboard.preliminary_from == date(2026, 10, 5)
    assert max(p.date for p in dashboard.cost_trend) == date(2026, 10, 7)
    assert dashboard.top_spenders[0].percentage_of_total == 100.0


@pytest.mark.anyio
async def test_leadership_flags_missing_history_and_incomplete_months(db):
    await _seed_leadership(db)
    db.add(_rec("2026-08-15", NONPROD, 10.0))  # non-prod has one day of data, then nothing
    await db.commit()
    dashboard = await AmortizedCostSyncService(db).build_leadership_dashboard(subscription_ids=[PROD, NONPROD])

    months = {m.month: m for m in dashboard.six_month_trend}
    assert set(months) == {"2026-08", "2026-09"}
    assert months["2026-09"].complete is False  # the non-prod subscription has no September data
    issues = {i.subscription_name: i for i in dashboard.data_quality}
    assert issues["ACC-NPRD-1"].missing_days == (date(2026, 10, 7) - date(2026, 4, 1)).days
    assert issues["ACC-NPRD-1"].no_data is False
    assert issues["ACC-PROD-1"].missing_ranges == ["2026-04-01 → 2026-07-31"]


@pytest.mark.anyio
async def test_subscription_without_any_data_is_reported_but_does_not_mark_months_incomplete(db):
    await _seed_leadership(db)
    dashboard = await AmortizedCostSyncService(db).build_leadership_dashboard(subscription_ids=[PROD, NONPROD])

    months = {m.month: m for m in dashboard.six_month_trend}
    assert months["2026-09"].complete is True  # judged on subscriptions that have data
    issue = next(i for i in dashboard.data_quality if i.subscription_name == "ACC-NPRD-1")
    assert issue.no_data is True
    assert "either it had no spend or it has not been synced yet" in issue.message


@pytest.mark.anyio
async def test_month_over_month_uses_daily_average_when_last_month_is_shorter(db, monkeypatch):
    monkeypatch.setattr(module, "utc_today", lambda: date(2027, 3, 31))
    await _admin(db)
    db.add_all([_rec(d.isoformat(), PROD, 100.0) for d in _days(date(2027, 1, 1), date(2027, 3, 30))])
    await db.commit()
    dashboard = await AmortizedCostSyncService(db).build_leadership_dashboard(subscription_ids=[PROD])
    mom = next(k for k in dashboard.kpis if k.name == "Month-over-Month Change")

    # Mar 1–30 ($3,000) vs Feb 1–28 ($2,800): flat $100/day is 0%, not +7.1%.
    assert mom.value == 0.0
    assert mom.description.endswith("(daily average)")


@pytest.mark.anyio
async def test_negative_month_to_date_does_not_break_the_dashboard(db):
    await _seed_leadership(db)
    db.add_all([_rec("2026-10-01", NONPROD, -40.0), _rec("2026-09-15", NONPROD, 5.0)])  # refund
    await db.commit()
    dashboard = await AmortizedCostSyncService(db).build_leadership_dashboard(subscription_ids=[PROD, NONPROD])

    spenders = {s.group_value: float(s.total_cost) for s in dashboard.top_spenders}
    assert spenders["ACC-NPRD-1"] == -40.0


@pytest.mark.anyio
async def test_leadership_merges_stale_guid_names_into_one_series(db):
    await _admin(db)
    db.add_all(
        [
            _rec("2026-10-01", NONPROD, 10.0, subscription_name=NONPROD, env_label="Prod"),
            _rec("2026-10-02", NONPROD, 10.0),
        ]
    )
    await db.commit()
    dashboard = await AmortizedCostSyncService(db).build_leadership_dashboard(subscription_ids=[NONPROD])
    assert {p.group_value for p in dashboard.cost_trend} == {"ACC-NPRD-1"}


# ── Azure fetch layer ─────────────────────────────────────────────────


def test_throttle_wait_honours_cost_management_headers():
    headers = {
        "x-ms-ratelimit-microsoft.costmanagement-entity-retry-after": "42",
        "x-ms-ratelimit-microsoft.costmanagement-clienttype-retry-after": "5",
        "x-ms-ratelimit-remaining-microsoft.costmanagement-entity-requests": "DefaultQuota:0",
    }
    assert _throttle_wait_seconds(headers) == 43.0
    assert _throttle_wait_seconds({}) == 31.0
    assert _throttle_wait_seconds({"Retry-After": "600"}) == 121.0


class _Page:
    def __init__(self, rows, next_link=None):
        self.columns = [SimpleNamespace(name="Cost"), SimpleNamespace(name="UsageDate")]
        self.rows = rows
        self.next_link = next_link


@pytest.mark.anyio
async def test_execute_cost_query_resumes_the_throttled_page(monkeypatch):
    throttled = HttpResponseError(message="Too many requests")
    throttled.status_code = 429
    throttled.response = SimpleNamespace(headers={"x-ms-ratelimit-microsoft.costmanagement-entity-retry-after": "3"})
    responses = [
        _Page([[1.0, 20261001]], next_link="https://x/query?$skiptoken=p2"),
        throttled,
        _Page([[2.0, 20261002]]),
    ]
    calls: list[str | None] = []

    class _Query:
        def usage(self, *, scope, parameters, **kwargs):
            calls.append((kwargs.get("params") or {}).get("$skiptoken"))
            item = responses.pop(0)
            if isinstance(item, Exception):
                raise item
            return item

    client = SimpleNamespace(query=_Query(), close=lambda: None)
    sleeps: list[float] = []

    async def fake_sleep(seconds):
        sleeps.append(seconds)

    service = CostService()
    monkeypatch.setattr(service, "_get_client", lambda: client)
    monkeypatch.setattr("app.services.cost_service.asyncio.sleep", fake_sleep)

    _cols, rows = await service._execute_cost_query("/subscriptions/sub-1", object())

    assert rows == [[1.0, 20261001], [2.0, 20261002]]
    assert calls == [None, "p2", "p2"]  # resumed page 2, never restarted at page 1
    assert sleeps == [4.0]


@pytest.mark.anyio
async def test_query_amortized_cost_detail_keeps_full_precision_and_exact_location(monkeypatch):
    rid = "/subscriptions/sub-1/resourceGroups/RG-Data/providers/Microsoft.Storage/storageAccounts/stdata"
    results = [
        (
            ["Cost", "UsageDate", "ResourceId", "MeterCategory", "Currency"],
            [
                [0.004, 20261001, rid, "Storage", "USD"],
                [1.23456, 20261001, rid, "Bandwidth", "USD"],
                [0.0, 20261001, rid, "Storage", "USD"],
            ],
        ),
        (
            ["Cost", "UsageDate", "PricingModel", "ChargeType", "Currency"],
            [[1.23856, 20261001, "OnDemand", "Usage", "USD"]],
        ),
        (["Cost", "ResourceId", "ResourceLocation", "Currency"], [[1.23856, rid.upper(), "westus3", "USD"]]),
    ]

    async def fake_execute(scope, query):
        return results.pop(0)

    service = CostService()
    monkeypatch.setattr(service, "_execute_cost_query", fake_execute)
    detail = await service.query_amortized_cost_detail("/subscriptions/sub-1", date(2026, 10, 1), date(2026, 10, 1))

    assert [r["cost"] for r in detail.rows] == [0.004, 1.23456]  # only exact zeros are dropped
    assert {r["resource_location"] for r in detail.rows} == {"westus3"}
    assert detail.rows[0]["resource_group"] == "RG-Data"
    assert detail.daily_totals() == pytest.approx(detail.reference_daily_totals())
