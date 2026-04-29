"""
Unit tests for AmortizedCostSyncService incremental logic.

Tests the _compute_fetch_ranges and _delete_fetch_ranges helpers
using an in-memory SQLite engine (AmortizedCostRecord has no JSONB columns).
"""

from datetime import date, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.models.database import AmortizedCostRecord
from app.services.amortized_cost_sync_service import (
    CORRECTION_WINDOW_DAYS,
    AmortizedCostSyncService,
)


# ── Fixture: SQLite engine with amortized_cost_records table ──────────────────

@pytest.fixture
async def amortized_db():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        echo=False,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(lambda c: AmortizedCostRecord.__table__.create(c, checkfirst=True))
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session
        await session.rollback()
    await engine.dispose()


def _make_record(cost_date: str, subscription_id: str = "sub-a") -> AmortizedCostRecord:
    return AmortizedCostRecord(
        cost_date=cost_date,
        cost_amount=100.0,
        subscription_id=subscription_id,
        subscription_name="Test Sub",
        env_label="Prod",
        currency="USD",
    )


# ── _compute_fetch_ranges — per-range gap detection ───────────────────────────

@pytest.mark.anyio
async def test_compute_fetch_ranges_no_existing_data(amortized_db):
    """Subscription with no data → each missing month is its own range + correction window."""
    svc = AmortizedCostSyncService(amortized_db)
    end_date = date.today()
    full_start = end_date - timedelta(days=90)
    correction_cutoff = end_date - timedelta(days=CORRECTION_WINDOW_DAYS)

    result = await svc._compute_fetch_ranges(["sub-a"], full_start, end_date)

    ranges = result["sub-a"]
    # Last range is always the correction window
    assert ranges[-1] == (correction_cutoff, end_date)
    # First range starts at full_start (the earliest missing month, clamped)
    assert ranges[0][0] == full_start
    # More than just the correction window (has missing month ranges too)
    assert len(ranges) > 1


@pytest.mark.anyio
async def test_compute_fetch_ranges_all_months_present_only_correction_window(amortized_db):
    """When all months have dense daily data (no gaps), only the correction window is returned."""
    today = date.today()
    end_date = today
    full_start = (today.replace(day=1) - timedelta(days=32)).replace(day=1)
    correction_cutoff = today - timedelta(days=CORRECTION_WINDOW_DAYS)

    # Add a record for EVERY day in [full_start, correction_cutoff) so the
    # gap detector finds no holes.  One record per month is insufficient now
    # that we detect intra-month gaps.
    day = full_start
    while day < correction_cutoff:
        amortized_db.add(_make_record(day.isoformat(), "sub-c"))
        day += timedelta(days=1)
    await amortized_db.commit()

    svc = AmortizedCostSyncService(amortized_db)
    result = await svc._compute_fetch_ranges(["sub-c"], full_start, end_date)

    # No missing months, no gaps → only correction window
    assert result["sub-c"] == [(correction_cutoff, end_date)]


@pytest.mark.anyio
async def test_compute_fetch_ranges_missing_old_months_has_range_from_gap(amortized_db):
    """Missing months produce individual ranges; the first starts at full_start_date."""
    today = date.today()
    end_date = today
    full_start = (today.replace(day=1) - timedelta(days=120)).replace(day=1)
    correction_cutoff = today - timedelta(days=CORRECTION_WINDOW_DAYS)

    # Only add data for the current month (most recent)
    current_month_mid = today.replace(day=15).isoformat() if today.day >= 15 else today.isoformat()
    amortized_db.add(_make_record(current_month_mid, "sub-d"))
    await amortized_db.commit()

    svc = AmortizedCostSyncService(amortized_db)
    result = await svc._compute_fetch_ranges(["sub-d"], full_start, end_date)

    ranges = result["sub-d"]
    # First range covers the oldest missing month, starting at full_start
    assert ranges[0][0] == full_start
    # Last range is the correction window
    assert ranges[-1] == (correction_cutoff, end_date)
    # Has missing month ranges in addition to correction window
    assert len(ranges) > 1


@pytest.mark.anyio
async def test_compute_fetch_ranges_multiple_subscriptions_independent(amortized_db):
    """Each subscription's ranges are computed independently."""
    today = date.today()
    end_date = today
    full_start = (today.replace(day=1) - timedelta(days=60)).replace(day=1)
    correction_cutoff = today - timedelta(days=CORRECTION_WINDOW_DAYS)

    # sub-has-all: add a record for every day (dense — no gaps for detector to find)
    day = full_start.replace(day=1)
    while day < correction_cutoff:
        amortized_db.add(_make_record(day.isoformat(), "sub-has-all"))
        day += timedelta(days=1)
    await amortized_db.commit()

    svc = AmortizedCostSyncService(amortized_db)
    result = await svc._compute_fetch_ranges(["sub-has-all", "sub-no-data"], full_start, end_date)

    # sub-has-all: all months present → only correction window
    assert result["sub-has-all"] == [(correction_cutoff, end_date)]
    # sub-no-data: missing months + correction window
    assert result["sub-no-data"][0][0] == full_start
    assert result["sub-no-data"][-1] == (correction_cutoff, end_date)
    assert len(result["sub-no-data"]) > 1


@pytest.mark.anyio
async def test_compute_fetch_ranges_mid_range_gap_has_isolated_range(amortized_db):
    """A gap in a middle month produces a range only for that month — not from the start."""
    today = date.today()
    end_date = today
    m0 = (today.replace(day=1) - timedelta(days=62)).replace(day=1)
    m1 = (m0.replace(day=28) + timedelta(days=4)).replace(day=1)   # missing month
    m2 = (m1.replace(day=28) + timedelta(days=4)).replace(day=1)
    correction_cutoff = today - timedelta(days=CORRECTION_WINDOW_DAYS)

    # Add data for m0 and m2, skip m1
    amortized_db.add(_make_record(m0.strftime("%Y-%m-10"), "sub-gap"))
    if m2 < correction_cutoff:
        amortized_db.add(_make_record(m2.strftime("%Y-%m-10"), "sub-gap"))
    await amortized_db.commit()

    svc = AmortizedCostSyncService(amortized_db)
    result = await svc._compute_fetch_ranges(["sub-gap"], m0, end_date)

    ranges = result["sub-gap"]
    # One of the ranges should cover m1 (the missing middle month)
    missing_month_ranges = [r for r in ranges if r != (correction_cutoff, end_date)]
    assert any(r[0] <= m1 <= r[1] for r in missing_month_ranges)
    # m0 is present — no range starting at m0 (only the missing month gets a range)
    assert not any(r[0] == m0 for r in missing_month_ranges)


# ── _delete_fetch_ranges ──────────────────────────────────────────────────────

@pytest.mark.anyio
async def test_delete_fetch_ranges_removes_only_targeted_records(amortized_db):
    """Only records within the specified range are deleted."""
    today = date.today()
    old_date = (today - timedelta(days=30)).isoformat()
    recent_date = (today - timedelta(days=3)).isoformat()

    amortized_db.add(_make_record(old_date, "sub-a"))
    amortized_db.add(_make_record(recent_date, "sub-a"))
    await amortized_db.commit()

    svc = AmortizedCostSyncService(amortized_db)
    fetch_start = today - timedelta(days=7)
    # Pass a range: [fetch_start, today] — only touches records in this window
    await svc._delete_fetch_ranges({"sub-a": [(fetch_start, today)]})

    remaining = (await amortized_db.execute(
        select(AmortizedCostRecord).where(AmortizedCostRecord.subscription_id == "sub-a")
    )).scalars().all()

    dates_remaining = {r.cost_date for r in remaining}
    assert old_date in dates_remaining        # 30 days ago — outside range, untouched
    assert recent_date not in dates_remaining  # 3 days ago — inside range, deleted


@pytest.mark.anyio
async def test_delete_fetch_ranges_leaves_other_subscription_intact(amortized_db):
    """Deleting sub-a's range must not affect sub-b's records."""
    recent_date = (date.today() - timedelta(days=3)).isoformat()

    amortized_db.add(_make_record(recent_date, "sub-a"))
    amortized_db.add(_make_record(recent_date, "sub-b"))
    await amortized_db.commit()

    svc = AmortizedCostSyncService(amortized_db)
    fetch_start = date.today() - timedelta(days=7)
    await svc._delete_fetch_ranges({"sub-a": [(fetch_start, date.today())]})

    sub_b_records = (await amortized_db.execute(
        select(AmortizedCostRecord).where(AmortizedCostRecord.subscription_id == "sub-b")
    )).scalars().all()
    assert len(sub_b_records) == 1  # sub-b untouched


# ── Historical preservation ───────────────────────────────────────────────────

@pytest.mark.anyio
async def test_historical_records_outside_fetch_range_preserved(amortized_db):
    """Records outside the specified range are never deleted."""
    today = date.today()
    very_old = (today - timedelta(days=60)).isoformat()
    recent = (today - timedelta(days=3)).isoformat()

    amortized_db.add(_make_record(very_old, "sub-x"))
    amortized_db.add(_make_record(recent, "sub-x"))
    await amortized_db.commit()

    svc = AmortizedCostSyncService(amortized_db)
    fetch_start = today - timedelta(days=7)
    await svc._delete_fetch_ranges({"sub-x": [(fetch_start, today)]})

    remaining = (await amortized_db.execute(
        select(AmortizedCostRecord).where(AmortizedCostRecord.subscription_id == "sub-x")
    )).scalars().all()

    dates_remaining = {r.cost_date for r in remaining}
    assert very_old in dates_remaining  # outside range — preserved
    assert recent not in dates_remaining  # inside range — deleted


# ── Intra-month gap detection ─────────────────────────────────────────────────

@pytest.mark.anyio
async def test_compute_fetch_ranges_detects_intra_month_gap(amortized_db):
    """A multi-day hole within months that both have partial data must be detected.

    Scenario mirrors the real Jan 30 - Feb 13 production bug:
      • Data exists on either side of a gap (dense daily records)
      • The gap spans > 1 day and crosses a month boundary
      • The gap must appear as a fetch range even though both flanking
        months are considered 'present' by the month-level check.
    """
    today = date.today()
    end_date = today
    correction_cutoff = today - timedelta(days=CORRECTION_WINDOW_DAYS)

    # full_start: 3 months before today (first of that month)
    full_start = (today.replace(day=1) - timedelta(days=90)).replace(day=1)

    # Place a 14-day gap ending ~35 days before the correction window so it
    # is well outside the auto-refreshed correction window.
    gap_end = correction_cutoff - timedelta(days=35)
    gap_start = gap_end - timedelta(days=13)  # 14-day gap: [gap_start, gap_end]

    # Dense records before the gap
    day = full_start
    while day < gap_start:
        amortized_db.add(_make_record(day.isoformat(), "sub-intra"))
        day += timedelta(days=1)

    # Dense records after the gap (up to but not including correction_cutoff)
    day = gap_end + timedelta(days=1)
    while day < correction_cutoff:
        amortized_db.add(_make_record(day.isoformat(), "sub-intra"))
        day += timedelta(days=1)

    await amortized_db.commit()

    svc = AmortizedCostSyncService(amortized_db)
    result = await svc._compute_fetch_ranges(["sub-intra"], full_start, end_date)

    ranges = result["sub-intra"]
    non_correction = [r for r in ranges if r != (correction_cutoff, end_date)]

    # The midpoint of the gap must be covered by at least one fetch range
    gap_mid = gap_start + timedelta(days=6)
    assert any(r[0] <= gap_mid <= r[1] for r in non_correction), (
        f"Expected gap around {gap_mid} to be covered; got ranges: {non_correction}"
    )

    # The correction window must still be last
    assert ranges[-1] == (correction_cutoff, end_date)
