"""
Amortized Cost Sync Service — DB-backed cache for Azure Cost API data.

The sync path:
1. Queries Azure Cost Management for the monitored subscriptions, one date
   range at a time (missing months, holes, and a rolling correction window).
2. Reconciles each range day by day against Azure's own totals; a range that
   does not reconcile keeps its previous data and is reported as a failure.
3. Replaces each range in a single transaction, so a reader never sees a range
   half-deleted.

Dashboards aggregate in SQL and resolve subscription names and Prod/Non-Prod
from the Admin panel at read time, so a rename or reclassification applies to
historical rows immediately. All date logic uses UTC days, the unit Azure
reports usage in.
"""

from __future__ import annotations

import asyncio
import contextlib
import csv
import hashlib
import io
import json
from calendar import monthrange
from collections import defaultdict
from collections.abc import AsyncIterator, Iterable
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from time import perf_counter
from typing import TYPE_CHECKING

import structlog
from sqlalchemy import case, delete, distinct, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.admin_config import get_effective_cache_ttl_seconds
from app.core.db_cache import cache_manager
from app.core.subscription_resolver import get_monitored_subscription_ids
from app.core.subscription_scope import get_scoped_subscription_ids
from app.models.database import (
    AdminSubscription,
    AmortizedCostDailySummary,
    AmortizedCostMonthlySummary,
    AmortizedCostPricingDaily,
    AmortizedCostRecord,
    AmortizedCostSyncStatus,
    AmortizedCostWeeklySummary,
)
from app.services.cost_service import AmortizedCostDetail, CostService

if TYPE_CHECKING:
    from app.schemas.cost import LeadershipDashboard

logger = structlog.get_logger(__name__)

# Data older than this many hours triggers an automatic re-sync.
# Set conservatively to avoid background syncs colliding with manual
# syncs and overwhelming Azure Cost Management's per-subscription rate
# limit (~10 req/min). The correction window still re-fetches the last
# CORRECTION_WINDOW_DAYS days on every run, so freshness is preserved.
STALE_HOURS = 2
RUNNING_SYNC_TIMEOUT_MINUTES = 180

# Azure Cost Management can retroactively adjust costs for recent days.
# Re-sync the last N days on every run to pick up those corrections,
# while leaving stable historical data untouched.
CORRECTION_WINDOW_DAYS = 7

# Azure keeps adding usage to a UTC day for up to ~72 hours after it closes;
# days inside this window are flagged as preliminary on the dashboards.
PRELIMINARY_DAYS = 3

# A range is written only when its resource-level rows add up to Azure's own
# daily total, within this tolerance, for every closed day in the range.
RECONCILE_ABS_TOLERANCE = 0.05
RECONCILE_REL_TOLERANCE = 0.0001
RANGE_FETCH_ATTEMPTS = 2

# Pricing models that represent committed (discounted) spend.
COMMITMENT_PRICING_MODELS = frozenset({"Reservation", "SavingsPlan"})

EXPORT_LEVELS = ("resources", "daily")

# Strong references so fire-and-forget syncs aren't garbage-collected mid-run.
_background_tasks: set[asyncio.Task] = set()


def utc_today() -> date:
    """Today's date in UTC — Azure reports usage by UTC day, not server-local day."""
    return datetime.now(UTC).date()


def _compress_dates(days: Iterable[date]) -> list[tuple[date, date]]:
    """Collapse sorted dates into inclusive (start, end) runs."""
    runs: list[tuple[date, date]] = []
    for d in days:
        if runs and d == runs[-1][1] + timedelta(days=1):
            runs[-1] = (runs[-1][0], d)
        else:
            runs.append((d, d))
    return runs


def _shift_month(d: date, months: int) -> date:
    """First day of the month ``months`` away from ``d``'s month."""
    index = d.year * 12 + (d.month - 1) + months
    return date(index // 12, index % 12 + 1, 1)


def _fmt_period(start: date, end: date) -> str:
    """'Oct 1 – Oct 7, 2026' (year shown once when both ends share it)."""
    if start.year == end.year:
        return f"{start:%b} {start.day} – {end:%b} {end.day}, {end.year}"
    return f"{start:%b} {start.day}, {start.year} – {end:%b} {end.day}, {end.year}"


def _pct_change(current: float, base: float) -> float | None:
    return (current - base) / base * 100 if base else None


def _breakdown(costs: dict[str, float], total: float) -> list[dict]:
    return sorted(
        (
            {"name": name, "cost": round(cost, 2), "pct": round(cost / total * 100, 2) if total else 0}
            for name, cost in costs.items()
        ),
        key=lambda item: item["cost"],
        reverse=True,
    )


class AmortizedCostSyncService:
    """Syncs amortized cost data from Azure Cost Management into PostgreSQL."""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db
        self._cost_service = CostService(db)

    # ── Staleness check ───────────────────────────────────────────────

    async def _expire_abandoned_running_rows(self) -> int:
        """Flip orphaned 'running' rows to 'failed' once they exceed the timeout.

        A row stays 'running' forever if the process is killed mid-sync or
        the HTTP request is cancelled before the except handler fires. Without
        this sweep the dashboard banner would stay on 'Syncing' indefinitely.
        """
        cutoff = datetime.utcnow() - timedelta(minutes=RUNNING_SYNC_TIMEOUT_MINUTES)
        result = await self._db.execute(
            update(AmortizedCostSyncStatus)
            .where(
                AmortizedCostSyncStatus.status == "running",
                AmortizedCostSyncStatus.started_at < cutoff,
            )
            .values(
                status="failed",
                completed_at=datetime.utcnow(),
                error_message="abandoned: process restarted or timed out",
            )
        )
        expired = getattr(result, "rowcount", 0) or 0
        if expired:
            await self._db.commit()
            logger.warning("amortized_sync_expired_running_rows", count=expired)
        return expired

    async def is_data_stale(self) -> bool:
        """Return True when the DB has no data or hasn't been refreshed recently."""
        result = await self._db.execute(
            select(AmortizedCostSyncStatus)
            .where(AmortizedCostSyncStatus.status == "completed")
            .order_by(AmortizedCostSyncStatus.completed_at.desc())
            .limit(1)
        )
        last = result.scalars().first()
        if not last or not last.completed_at:
            return True
        age = datetime.utcnow() - last.completed_at
        return age > timedelta(hours=STALE_HOURS)

    async def is_sync_running(self) -> bool:
        """Return True when a recent amortized sync is still marked as running."""
        result = await self._db.execute(
            select(AmortizedCostSyncStatus)
            .where(AmortizedCostSyncStatus.status == "running")
            .order_by(AmortizedCostSyncStatus.started_at.desc())
            .limit(1)
        )
        running = result.scalars().first()
        if not running or not running.started_at:
            return False
        return running.started_at >= datetime.utcnow() - timedelta(minutes=RUNNING_SYNC_TIMEOUT_MINUTES)

    @classmethod
    def schedule_background_sync(
        cls,
        months: int = 2,
        triggered_by: str = "request",
    ) -> None:
        """Fire-and-forget amortized sync using a fresh DB session."""
        task = asyncio.create_task(cls._run_background_sync(months=months, triggered_by=triggered_by))
        _background_tasks.add(task)
        task.add_done_callback(_background_tasks.discard)

    @classmethod
    async def _run_background_sync(
        cls,
        months: int = 2,
        triggered_by: str = "request",
    ) -> None:
        from app.core.database import get_db_session

        try:
            async for db in get_db_session():
                svc = cls(db)
                result = await svc.full_sync(months=months, triggered_by=triggered_by)
                logger.info(
                    "amortized_background_sync_finished",
                    status=result.get("status", "unknown"),
                    months=months,
                    triggered_by=triggered_by,
                )
                break
        except Exception as exc:
            logger.error(
                "amortized_background_sync_failed",
                error=str(exc)[:500],
                months=months,
                triggered_by=triggered_by,
            )

    async def _fetch_subscription_metadata(self, monitored_ids: list[str]) -> dict[str, dict]:
        """Fetch subscription display name and environment from AdminSubscription table."""
        result = await self._db.execute(
            select(
                AdminSubscription.subscription_id,
                AdminSubscription.subscription_name,
                AdminSubscription.environment,
            ).where(AdminSubscription.subscription_id.in_(monitored_ids))
        )
        return {sub_id: {"subscription_name": name, "environment": env} for sub_id, name, env in result.all()}

    async def _subscription_labels(self) -> dict[str, tuple[str | None, str]]:
        """sub_id → (Admin display name or None, resolved Prod/Non-Prod).

        The Admin panel is the source of truth. The stored ``subscription_name``
        and ``env_label`` columns hold whatever was known at sync time and can
        be stale — e.g. a GUID name and the default "Prod" label written before
        the subscription was registered — so read paths resolve through this.
        """
        result = await self._db.execute(
            select(
                AdminSubscription.subscription_id,
                AdminSubscription.subscription_name,
                AdminSubscription.environment,
            )
        )
        labels: dict[str, tuple[str | None, str]] = {}
        for sub_id, name, environment in result.all():
            if not sub_id:
                continue
            clean_name = str(name or "").strip() or None
            labels[str(sub_id).strip()] = (clean_name, self.resolve_env_label(environment, clean_name))
        return labels

    async def _compute_fetch_ranges(
        self,
        monitored_ids: list[str],
        full_start_date: date,
        end_date: date,
    ) -> dict[str, list[tuple[date, date]]]:
        """Return the per-subscription list of (start, end) date ranges to fetch.

        Each range is an independent fetch+delete unit:
          • One range per MISSING calendar month.
          • Extra ranges for any multi-day holes WITHIN months that have
            partial data — e.g. Jan 1-29 present + Feb 14-28 present means
            Jan 30 - Feb 13 is detected and added as a gap range.
          • The CORRECTION WINDOW (last CORRECTION_WINDOW_DAYS days) is
            always included so retroactive Azure adjustments are captured.
        """
        correction_cutoff = end_date - timedelta(days=CORRECTION_WINDOW_DAYS)

        # Calendar months to check for gaps (first of each month < correction_cutoff)
        all_months_in_range: list[str] = []
        cur = full_start_date.replace(day=1)
        while cur < correction_cutoff:
            all_months_in_range.append(cur.strftime("%Y-%m"))
            month = cur.month + 1
            year = cur.year
            if month > 12:
                month = 1
                year += 1
            cur = cur.replace(year=year, month=month)

        # Which months already have data per subscription? (month-level check)
        months_result = await self._db.execute(
            select(
                AmortizedCostRecord.subscription_id,
                func.substr(AmortizedCostRecord.cost_date, 1, 7).label("month_year"),
            )
            .where(
                AmortizedCostRecord.subscription_id.in_(monitored_ids),
                AmortizedCostRecord.cost_date >= full_start_date.isoformat(),
                AmortizedCostRecord.cost_date < correction_cutoff.isoformat(),
            )
            .distinct()
        )
        months_per_sub: dict[str, set[str]] = {}
        for row in months_result:
            months_per_sub.setdefault(row.subscription_id, set()).add(row.month_year)

        # All distinct dates per subscription — needed to detect intra-month gaps
        # where BOTH flanking months have some data but there is a multi-day hole
        # at or near the month boundary (e.g. Jan 30 - Feb 13 missing while Jan
        # 1-29 and Feb 14-28 exist).  The result set is small (≤365 rows per sub).
        dates_result = await self._db.execute(
            select(
                AmortizedCostRecord.subscription_id,
                AmortizedCostRecord.cost_date,
            )
            .where(
                AmortizedCostRecord.subscription_id.in_(monitored_ids),
                AmortizedCostRecord.cost_date >= full_start_date.isoformat(),
                AmortizedCostRecord.cost_date < correction_cutoff.isoformat(),
            )
            .distinct()
            .order_by(AmortizedCostRecord.subscription_id, AmortizedCostRecord.cost_date)
        )
        dates_per_sub: dict[str, list[date]] = {}
        for row in dates_result:
            try:
                d = date.fromisoformat(str(row.cost_date))
            except (ValueError, TypeError):
                continue
            dates_per_sub.setdefault(row.subscription_id, []).append(d)

        per_sub_ranges: dict[str, list[tuple[date, date]]] = {}
        for sub_id in monitored_ids:
            existing_months = months_per_sub.get(sub_id, set())
            missing_months = sorted(m for m in all_months_in_range if m not in existing_months)
            missing_months_set = set(missing_months)

            ranges: list[tuple[date, date]] = []

            # ── 1. Missing complete months ─────────────────────────────
            for month_str in missing_months:
                year, mon = int(month_str[:4]), int(month_str[5:7])
                month_first = date(year, mon, 1)
                range_start = max(full_start_date, month_first)
                if mon == 12:
                    month_last = date(year, 12, 31)
                else:
                    month_last = date(year, mon + 1, 1) - timedelta(days=1)
                range_end = min(month_last, correction_cutoff - timedelta(days=1))
                ranges.append((range_start, range_end))

            # ── 2. Intra-range gap detection ───────────────────────────
            # Scan consecutive existing dates; any gap > 1 day is a hole
            # that must be re-fetched.  Holes that fall inside a month
            # already queued as "missing" are skipped (already covered).
            existing_dates = dates_per_sub.get(sub_id, [])

            def _add_gap(
                gap_s: date,
                gap_e: date,
                _mms: set = missing_months_set,
                _rng: list = ranges,
            ) -> None:
                """Split [gap_s, gap_e] at month boundaries; add segments not
                already covered by a full missing-month range."""
                seg = gap_s
                while seg <= gap_e:
                    sy, sm = seg.year, seg.month
                    seg_month = f"{sy:04d}-{sm:02d}"
                    seg_last = date(sy, 12, 31) if sm == 12 else date(sy, sm + 1, 1) - timedelta(days=1)
                    seg_end = min(seg_last, gap_e)
                    if seg_month not in _mms:
                        _rng.append((seg, seg_end))
                    seg = date(sy + 1, 1, 1) if sm == 12 else date(sy, sm + 1, 1)

            # 2a. Gaps between consecutive existing dates
            for i in range(len(existing_dates) - 1):
                prev_d = existing_dates[i]
                next_d = existing_dates[i + 1]
                if (next_d - prev_d).days > 1:
                    _add_gap(prev_d + timedelta(days=1), next_d - timedelta(days=1))

            # 2b. Trailing gap — from the last existing date to the correction
            # window start.  Covers the case where a partial month's data ends
            # before the end of that month and no later month is flagged missing.
            if existing_dates:
                last_d = existing_dates[-1]
                trail_end = correction_cutoff - timedelta(days=1)
                if last_d + timedelta(days=1) <= trail_end:
                    _add_gap(last_d + timedelta(days=1), trail_end)

            # ── 3. Correction window (always) ──────────────────────────
            ranges.append((correction_cutoff, end_date))

            per_sub_ranges[sub_id] = ranges
            logger.debug(
                "amortized_sync_fetch_ranges",
                subscription_id=sub_id,
                missing_months=missing_months,
                range_count=len(ranges),
                has_gap=bool(missing_months) or len(ranges) > 1,
            )
        return per_sub_ranges

    async def _delete_fetch_ranges(
        self,
        per_sub_ranges: dict[str, list[tuple[date, date]]],
    ) -> None:
        """Delete resource rows and pricing rollups for each (start, end) range.

        Does not commit: the caller deletes and inserts in one transaction, so a
        range is never visible half-replaced and a failed insert loses nothing.
        """
        for sub_id, ranges in per_sub_ranges.items():
            for range_start, range_end in ranges:
                for model in (AmortizedCostRecord, AmortizedCostPricingDaily):
                    await self._db.execute(
                        delete(model).where(
                            model.subscription_id == sub_id,
                            model.cost_date >= range_start.isoformat(),
                            model.cost_date <= range_end.isoformat(),
                        )
                    )

    @staticmethod
    def _split_into_monthly_chunks(start: date, end: date) -> list[tuple[date, date]]:
        """Split [start, end] into monthly sub-ranges for resilient per-month fetching.

        Fetching one month at a time means a 429 rate-limit on one month
        does not block all subsequent months from being synced.
        """
        chunks: list[tuple[date, date]] = []
        cur = start
        while cur <= end:
            year, month = cur.year, cur.month
            if month == 12:
                last_day = date(year, 12, 31)
                next_start = date(year + 1, 1, 1)
            else:
                last_day = date(year, month + 1, 1) - timedelta(days=1)
                next_start = date(year, month + 1, 1)
            chunk_end = min(last_day, end)
            chunks.append((cur, chunk_end))
            if next_start > end:
                break
            cur = next_start
        return chunks

    # ── Range fetch → reconcile → replace ─────────────────────────────

    @staticmethod
    def _reconcile(detail: AmortizedCostDetail, as_of: date) -> list[str]:
        """Days whose resource-level rows don't add up to Azure's own total.

        The current UTC day is skipped: it is still being ingested, can change
        between the two queries, and no dashboard shows it.
        """
        rows = detail.daily_totals()
        reference = detail.reference_daily_totals()
        today = as_of.isoformat()
        mismatches: list[str] = []
        for day in sorted(set(rows) | set(reference)):
            if day >= today:
                continue
            got, expected = rows.get(day, 0.0), reference.get(day, 0.0)
            tolerance = max(RECONCILE_ABS_TOLERANCE, abs(expected) * RECONCILE_REL_TOLERANCE)
            if abs(got - expected) > tolerance:
                mismatches.append(f"{day}: resource rows ${got:,.2f} vs Azure total ${expected:,.2f}")
        return mismatches

    async def _fetch_range(self, scope: str, start: date, end: date, as_of: date) -> AmortizedCostDetail:
        """Fetch a range and prove it complete; refetch once if it doesn't reconcile."""
        mismatches: list[str] = []
        lo, hi = start.isoformat(), end.isoformat()
        for attempt in range(1, RANGE_FETCH_ATTEMPTS + 1):
            detail = await self._cost_service.query_amortized_cost_detail(scope, start, end)
            # Only this range's rows are deleted before insert, so a row dated
            # outside it would be stored twice. Azure shouldn't send any.
            rows = [r for r in detail.rows if lo <= r["date"] <= hi]
            pricing = [p for p in detail.pricing_rows if lo <= p["date"] <= hi]
            dropped = len(detail.rows) - len(rows) + len(detail.pricing_rows) - len(pricing)
            if dropped:
                logger.warning(
                    "amortized_range_rows_outside_window_dropped",
                    scope=scope,
                    start=lo,
                    end=hi,
                    dropped=dropped,
                )
                detail.rows, detail.pricing_rows = rows, pricing
            mismatches = self._reconcile(detail, as_of)
            if not mismatches:
                return detail
            logger.warning(
                "amortized_range_reconcile_mismatch",
                scope=scope,
                start=start.isoformat(),
                end=end.isoformat(),
                attempt=attempt,
                mismatched_days=len(mismatches),
                first_mismatch=mismatches[0],
            )
        raise RuntimeError(
            f"rows did not reconcile with Azure totals on {len(mismatches)} day(s), e.g. {mismatches[0]}"
        )

    async def _replace_range(
        self,
        sub_id: str,
        sub_name: str,
        env_label: str,
        start: date,
        end: date,
        detail: AmortizedCostDetail,
    ) -> None:
        """Swap a range's stored rows for freshly fetched, reconciled ones in one transaction."""
        now = datetime.utcnow()
        try:
            if not detail.location_enriched and detail.rows:
                await self._carry_over_locations(sub_id, detail)
            await self._delete_fetch_ranges({sub_id: [(start, end)]})
            batch: list[AmortizedCostRecord] = []
            for r in detail.rows:
                batch.append(
                    AmortizedCostRecord(
                        cost_date=r["date"],
                        cost_amount=r["cost"],
                        meter_category=r.get("meter_category", ""),
                        meter_subcategory=r.get("meter_subcategory", ""),
                        meter_name=r.get("meter_name", ""),
                        resource_group=r.get("resource_group", ""),
                        resource_name=self._normalize_resource_name(
                            r.get("resource_name"),
                            meter_name=r.get("meter_name"),
                            meter_category=r.get("meter_category"),
                            resource_group=r.get("resource_group"),
                        ),
                        resource_type=r.get("resource_type", ""),
                        resource_location=r.get("resource_location", ""),
                        subscription_name=sub_name,
                        subscription_id=sub_id,
                        service_name=r.get("service_name", ""),
                        charge_type=r.get("charge_type", ""),
                        pricing_model=r.get("pricing_model", ""),
                        publisher_type=r.get("publisher_type", ""),
                        frequency=r.get("frequency", ""),
                        currency=r.get("currency") or "USD",
                        env_label=env_label,
                        synced_at=now,
                    )
                )
                if len(batch) >= 5000:
                    self._db.add_all(batch)
                    await self._db.flush()
                    batch = []
            if batch:
                self._db.add_all(batch)
            self._db.add_all(
                [
                    AmortizedCostPricingDaily(
                        cost_date=p["date"],
                        subscription_id=sub_id,
                        pricing_model=p.get("pricing_model", ""),
                        charge_type=p.get("charge_type", ""),
                        cost_amount=p["cost"],
                        currency=p.get("currency") or "USD",
                        synced_at=now,
                    )
                    for p in detail.pricing_rows
                ]
            )
            await self._db.commit()
        except Exception:
            await self._db.rollback()
            raise

    async def _carry_over_locations(self, sub_id: str, detail: AmortizedCostDetail) -> None:
        """Reuse stored regions when Azure's best-effort location query failed.

        Without this, replacing a range would overwrite every known location
        with blank, and historical months are not refetched to repair it.
        """
        R = AmortizedCostRecord  # noqa: N806
        result = await self._db.execute(
            select(R.resource_group, R.resource_name, func.max(R.resource_location))
            .where(R.subscription_id == sub_id, R.resource_location != "")
            .group_by(R.resource_group, R.resource_name)
        )
        known = {((rg or "").lower(), (name or "").lower()): loc for rg, name, loc in result.all() if loc}
        for row in detail.rows:
            if not row.get("resource_location"):
                key = ((row.get("resource_group") or "").lower(), (row.get("resource_name") or "").lower())
                row["resource_location"] = known.get(key, "")

    async def _sync_ranges(
        self,
        sub_metadata: dict[str, dict],
        per_sub_ranges: dict[str, list[tuple[date, date]]],
        as_of: date,
    ) -> dict:
        """Fetch, reconcile and write every range; one failure never aborts the rest.

        Ranges run newest-first across all subscriptions, so the correction
        window — what the dashboards show first — lands before a long backfill.
        A failed range keeps its previous rows and is reported in ``failures``.
        """
        work = sorted(
            ((sub_id, start, end) for sub_id, ranges in per_sub_ranges.items() for start, end in ranges),
            key=lambda item: item[2],
            reverse=True,
        )
        rows_synced = 0
        total_cost = 0.0
        ok_per_sub: dict[str, int] = defaultdict(int)
        failures: list[dict] = []

        for sub_id, start, end in work:
            metadata = sub_metadata.get(sub_id, {})
            sub_name = str(metadata.get("subscription_name") or "").strip() or sub_id
            # AdminSubscription.environment is preferred; when admin hasn't
            # tagged the sub, fall back to the name pattern (ACC-NPRD-… / ACC-PROD-…).
            env_label = self.resolve_env_label(metadata.get("environment"), sub_name)
            logger.info(
                "amortized_cost_range_fetching",
                subscription_id=sub_id,
                start=start.isoformat(),
                end=end.isoformat(),
            )
            try:
                detail = await self._fetch_range(f"/subscriptions/{sub_id}", start, end, as_of)
                if not detail.rows:
                    # An empty answer for a range we already hold data for is
                    # almost always a transient Azure problem, not real $0 spend.
                    existing = await self._db.scalar(
                        select(func.count(AmortizedCostRecord.id)).where(
                            AmortizedCostRecord.subscription_id == sub_id,
                            AmortizedCostRecord.cost_date >= start.isoformat(),
                            AmortizedCostRecord.cost_date <= end.isoformat(),
                        )
                    )
                    if existing:
                        raise RuntimeError(f"Azure returned no rows but {existing} rows are stored — kept prior data")
                await self._replace_range(sub_id, sub_name, env_label, start, end, detail)
            except Exception as exc:
                failures.append(
                    {
                        "subscription_id": sub_id,
                        "subscription_name": sub_name,
                        "start": start.isoformat(),
                        "end": end.isoformat(),
                        "error": f"{type(exc).__name__}: {str(exc)[:300]}",
                    }
                )
                logger.error(
                    "amortized_cost_range_failed",
                    subscription_id=sub_id,
                    start=start.isoformat(),
                    end=end.isoformat(),
                    error=str(exc)[:300],
                )
                continue

            ok_per_sub[sub_id] += 1
            rows_synced += len(detail.rows)
            total_cost += sum(r["cost"] for r in detail.rows)
            logger.info(
                "amortized_cost_range_loaded",
                subscription_id=sub_id,
                start=start.isoformat(),
                end=end.isoformat(),
                rows=len(detail.rows),
                cost=round(sum(r["cost"] for r in detail.rows), 2),
            )

        return {
            "rows_synced": rows_synced,
            "total_cost": total_cost,
            "ranges_total": len(work),
            "ranges_ok": sum(ok_per_sub.values()),
            "failures": failures,
            "failed_sub_ids": [sid for sid, ranges in per_sub_ranges.items() if ranges and not ok_per_sub.get(sid)],
        }

    async def _refresh_subscription_labels(self, sub_metadata: dict[str, dict]) -> int:
        """Rewrite stored names and Prod/Non-Prod labels that drifted from the Admin panel.

        Rows synced before a subscription was registered carry its GUID as the
        name and the default "Prod" label; without this, one subscription shows
        up twice in breakdowns and non-prod spend is counted as prod.
        """
        updated = 0
        for sub_id, metadata in sub_metadata.items():
            name = str(metadata.get("subscription_name") or "").strip()
            if not name:
                continue
            label = self.resolve_env_label(metadata.get("environment"), name)
            result = await self._db.execute(
                update(AmortizedCostRecord)
                .where(
                    AmortizedCostRecord.subscription_id == sub_id,
                    or_(
                        AmortizedCostRecord.subscription_name.is_(None),
                        AmortizedCostRecord.subscription_name != name,
                        AmortizedCostRecord.env_label != label,
                    ),
                )
                .values(subscription_name=name, env_label=label)
            )
            updated += getattr(result, "rowcount", 0) or 0
        if updated:
            await self._db.commit()
            logger.info("amortized_subscription_labels_refreshed", rows=updated)
        return updated

    @staticmethod
    def _summarize_failures(failures: list[dict], limit: int = 3) -> str:
        parts = [f"{f['subscription_name']} {f['start']}..{f['end']}: {f['error']}" for f in failures[:limit]]
        if len(failures) > limit:
            parts.append(f"+{len(failures) - limit} more")
        return "; ".join(parts)

    async def _finish_sync_record(self, sync_id: int | None, **values) -> None:
        """Close the sync-status row with a direct UPDATE.

        A rolled-back range leaves ORM instances expired; updating by primary
        key avoids an implicit refresh of the in-memory record.
        """
        await self._db.execute(
            update(AmortizedCostSyncStatus).where(AmortizedCostSyncStatus.id == sync_id).values(**values)
        )
        await self._db.commit()

    async def _rebuild_leadership_snapshot(self, triggered_by: str) -> None:
        """Rebuild the Cost Forecast snapshot so it never lags the cost data."""
        from app.services.leadership_sync_service import LeadershipSyncService

        try:
            result = await LeadershipSyncService(self._db).full_sync(
                triggered_by=f"amortized-sync:{triggered_by}"[:100],
            )
            logger.info("amortized_sync_leadership_rebuilt", status=result.get("status"))
        except Exception as exc:
            logger.warning("amortized_sync_leadership_rebuild_failed", error=str(exc)[:300])

    @staticmethod
    def _normalize_resource_name(
        resource_name: str | None,
        *,
        meter_name: str | None = None,
        meter_category: str | None = None,
        resource_group: str | None = None,
    ) -> str:
        """Return a user-facing resource name without fabricating group/service combinations."""
        normalized = str(resource_name or "").strip()
        if normalized:
            if normalized.startswith("/subscriptions/"):
                parts = [part for part in normalized.split("/") if part]
                if parts:
                    return parts[-1]
            return normalized

        value = str(meter_name or "").strip()
        if value:
            return value

        return ""

    @staticmethod
    def _get_rolling_start_date(end_date: date, months: int) -> date:
        """Return the exact calendar-month-aligned rolling start date.

        Example: if end_date is Apr 19 and months is 3, start date is Jan 19.
        The day component is clamped for shorter months.
        """
        target_month = end_date.month - months
        target_year = end_date.year
        while target_month <= 0:
            target_month += 12
            target_year -= 1

        target_day = min(end_date.day, monthrange(target_year, target_month)[1])
        return date(target_year, target_month, target_day)

    # ── Full sync (azure api → DB, incremental) ──────────────────────

    async def full_sync(
        self,
        months: int = 2,
        triggered_by: str = "manual",
        force: bool = False,
        subscription_ids: list[str] | None = None,
        rebuild_leadership: bool = True,
    ) -> dict:
        """Download Azure Cost API data, reconcile it, and store it in PostgreSQL.

        Normal mode (force=False): incremental — only fetches date ranges
        missing from the DB, plus the last CORRECTION_WINDOW_DAYS days per
        subscription to capture retroactive Azure cost adjustments.

        Force mode (force=True): re-fetches every month of the rolling window.
        Use this after enrichment logic changes to rewrite historical records.

        Each range is replaced only after it reconciles with Azure's totals.
        Ranges that fail keep their previous data; the run still completes,
        and ``error_message`` / ``failed_ranges`` say exactly what is missing.

        When ``subscription_ids`` is set (manual user sync with narrowed scope),
        only those subscriptions are fetched/updated. Scheduler and startup jobs
        omit this parameter and sync the full admin-monitored set.
        """
        from app.core.sync_lock import release_advisory_lock, try_acquire_advisory_lock

        await self._expire_abandoned_running_rows()
        if not await try_acquire_advisory_lock(self._db, "sync:amortized"):
            return {
                "status": "already_running",
                "message": "Another amortized cost sync is in progress",
            }
        if await self.is_sync_running():
            await release_advisory_lock(self._db, "sync:amortized")
            return {
                "status": "already_running",
                "message": "An amortized cost sync is already marked running",
            }

        sync_record = AmortizedCostSyncStatus(
            sync_type="force" if force else "full",
            status="running",
            started_at=datetime.utcnow(),
            triggered_by=triggered_by,
        )
        self._db.add(sync_record)
        await self._db.commit()
        sync_id = sync_record.id
        started_at = sync_record.started_at or datetime.utcnow()

        try:
            end_date = utc_today()
            full_start_date = self._get_rolling_start_date(end_date, months)

            monitored_ids = await get_monitored_subscription_ids()
            if subscription_ids is not None:
                monitored_set = set(monitored_ids)
                sync_ids = [sub_id for sub_id in subscription_ids if sub_id in monitored_set]
                ignored = sorted(set(subscription_ids) - monitored_set)
                if ignored:
                    logger.warning(
                        "amortized_sync_ignored_unmonitored_subscription_ids",
                        ignored=ignored,
                    )
            else:
                sync_ids = list(monitored_ids)

            partial_scope = subscription_ids is not None
            sync_scope = "partial" if partial_scope else "full_monitored"
            if not sync_ids:
                logger.info("amortized_cost_sync_skipped_no_target_subscriptions")
                completed_at = datetime.utcnow()
                await self._finish_sync_record(
                    sync_id,
                    status="completed",
                    completed_at=completed_at,
                    months_synced=months,
                    rows_synced=0,
                    total_cost=0.0,
                )
                await cache_manager.invalidate("pagecache:amortized:*")
                return {
                    "status": "completed",
                    "months_synced": months,
                    "rows_synced": 0,
                    "total_cost": 0.0,
                    "started_at": started_at.isoformat(),
                    "completed_at": completed_at.isoformat(),
                    "duration_seconds": round(max(0.0, (completed_at - started_at).total_seconds()), 2),
                    "note": "no_target_subscriptions",
                    "subscription_ids": [],
                    "sync_scope": sync_scope,
                }

            # Step 1: Subscription metadata (names, environments)
            sub_metadata = await self._fetch_subscription_metadata(sync_ids)

            # Step 2: Compute fetch ranges.
            # Force mode: every calendar month in the window for every
            # subscription. Normal mode: only missing months + correction window.
            if force:
                monthly_chunks = self._split_into_monthly_chunks(full_start_date, end_date)
                per_sub_ranges = {sub_id: list(monthly_chunks) for sub_id in sync_ids}
                logger.info(
                    "amortized_cost_sync_force_mode",
                    months=months,
                    chunks=len(monthly_chunks),
                    subscriptions=len(sync_ids),
                    partial_scope=partial_scope,
                )
            else:
                per_sub_ranges = await self._compute_fetch_ranges(sync_ids, full_start_date, end_date)
                await self._add_pricing_backfill_ranges(per_sub_ranges, sync_ids, full_start_date, end_date)

            # Step 3: Fetch, reconcile and replace each range on its own.
            outcome = await self._sync_ranges(sub_metadata, per_sub_ranges, end_date)

            # Step 4: Repair stored names / Prod-Non-Prod labels for these subs.
            relabeled = await self._refresh_subscription_labels(sub_metadata)

            failures = outcome["failures"]
            if failures and not outcome["ranges_ok"]:
                raise RuntimeError(f"Azure amortized sync failed — {self._summarize_failures(failures)}")

            warning = (
                f"Partial sync: {len(failures)} of {outcome['ranges_total']} date ranges failed and kept "
                f"their previous data — {self._summarize_failures(failures)}"
                if failures
                else None
            )
            completed_at = datetime.utcnow()
            await self._finish_sync_record(
                sync_id,
                status="completed",
                completed_at=completed_at,
                months_synced=months,
                rows_synced=outcome["rows_synced"],
                total_cost=round(outcome["total_cost"], 2),
                error_message=warning[:2000] if warning else None,
            )

            logger.info(
                "amortized_cost_sync_completed",
                months=months,
                rows=outcome["rows_synced"],
                total_cost=round(outcome["total_cost"], 2),
                triggered_by=triggered_by,
                ranges_ok=outcome["ranges_ok"],
                ranges_failed=len(failures),
                relabeled_rows=relabeled,
                subscription_count=len(sync_ids),
                partial_scope=partial_scope,
            )

            await cache_manager.invalidate("pagecache:amortized:*")

            if outcome["ranges_ok"] or relabeled:
                # Rebuild time-series aggregation summaries
                try:
                    await self._aggregate_cost_summaries()
                except Exception as agg_exc:
                    # An aborted transaction would also sink the leadership rebuild.
                    with contextlib.suppress(Exception):
                        await self._db.rollback()
                    logger.warning(
                        "amortized_cost_aggregation_failed",
                        error=str(agg_exc)[:500],
                    )
                if rebuild_leadership:
                    await self._rebuild_leadership_snapshot(triggered_by)

            return {
                "status": "completed",
                "months_synced": months,
                "rows_synced": outcome["rows_synced"],
                "total_cost": round(outcome["total_cost"], 2),
                "started_at": started_at.isoformat(),
                "completed_at": completed_at.isoformat(),
                "duration_seconds": round(max(0.0, (completed_at - started_at).total_seconds()), 2),
                "ranges_synced": outcome["ranges_ok"],
                "partial_failures": len(failures),
                "failed_ranges": failures[:25],
                "relabeled_rows": relabeled,
                "subscription_ids": sync_ids,
                "sync_scope": sync_scope,
            }

        except Exception as exc:
            with contextlib.suppress(Exception):
                await self._db.rollback()
            completed_at = datetime.utcnow()
            await self._finish_sync_record(
                sync_id,
                status="failed",
                completed_at=completed_at,
                error_message=str(exc)[:2000],
            )
            logger.error(
                "amortized_cost_sync_failed",
                error=str(exc)[:500],
                triggered_by=triggered_by,
            )
            return {
                "status": "failed",
                "error": str(exc)[:500],
                "started_at": started_at.isoformat(),
                "completed_at": completed_at.isoformat(),
                "duration_seconds": round(max(0.0, (completed_at - started_at).total_seconds()), 2),
            }
        finally:
            await release_advisory_lock(self._db, "sync:amortized")

    # ── Time-Series Aggregation ──────────────────────────────────────

    async def _aggregate_cost_summaries(self) -> None:
        """Aggregate raw amortized cost records into daily/weekly/monthly summaries."""
        # ── Daily Summary ──────────────────────────────────────────
        daily_result = await self._db.execute(
            select(
                AmortizedCostRecord.cost_date,
                func.sum(AmortizedCostRecord.cost_amount).label("total_cost"),
                func.sum(
                    case(
                        (AmortizedCostRecord.env_label == "Prod", AmortizedCostRecord.cost_amount),
                        else_=0.0,
                    )
                ).label("prod_cost"),
                func.sum(
                    case(
                        (AmortizedCostRecord.env_label == "Non-Prod", AmortizedCostRecord.cost_amount),
                        else_=0.0,
                    )
                ).label("nonprod_cost"),
                func.count(distinct(AmortizedCostRecord.service_name)).label("service_count"),
                func.count(distinct(AmortizedCostRecord.resource_name)).label("resource_count"),
            ).group_by(AmortizedCostRecord.cost_date)
        )
        daily_rows = daily_result.all()

        # Clear existing daily summaries and bulk insert new ones
        await self._db.execute(delete(AmortizedCostDailySummary))
        if daily_rows:
            daily_summaries = []
            for cost_date, total, prod, nonprod, svc_count, res_count in daily_rows:
                daily_summaries.append(
                    AmortizedCostDailySummary(
                        cost_date=str(cost_date),
                        total_cost=float(total or 0.0),
                        production_cost=float(prod or 0.0),
                        non_production_cost=float(nonprod or 0.0),
                        service_count=int(svc_count or 0),
                        resource_count=int(res_count or 0),
                    )
                )
            self._db.add_all(daily_summaries)

        # ── Weekly Summary ─────────────────────────────────────────
        # Load all daily summaries in one query, aggregate in Python.
        # (The previous approach issued 3 DB queries per day — O(n) — which
        # is extremely slow with 12 months of data.)
        all_daily_result = await self._db.execute(
            select(
                AmortizedCostDailySummary.cost_date,
                AmortizedCostDailySummary.total_cost,
                AmortizedCostDailySummary.production_cost,
                AmortizedCostDailySummary.non_production_cost,
            ).order_by(AmortizedCostDailySummary.cost_date)
        )
        all_daily_rows = all_daily_result.all()

        weeks = defaultdict(
            lambda: {
                "total_cost": 0.0,
                "production_cost": 0.0,
                "non_production_cost": 0.0,
            }
        )

        for cost_date, total, prod, nonprod in all_daily_rows:
            try:
                d = datetime.strptime(str(cost_date), "%Y-%m-%d")
                week_start = (d - timedelta(days=d.weekday())).strftime("%Y-%m-%d")
                weeks[week_start]["total_cost"] += float(total or 0.0)
                weeks[week_start]["production_cost"] += float(prod or 0.0)
                weeks[week_start]["non_production_cost"] += float(nonprod or 0.0)
            except Exception as e:
                logger.warning("week_start_calculation_failed", date=cost_date, error=str(e))

        await self._db.execute(delete(AmortizedCostWeeklySummary))
        if weeks:
            weekly_summaries = []
            for week_start, data in weeks.items():
                weekly_summaries.append(
                    AmortizedCostWeeklySummary(
                        week_start_date=week_start,
                        total_cost=float(data["total_cost"]),
                        production_cost=float(data["production_cost"]),
                        non_production_cost=float(data["non_production_cost"]),
                        service_count=0,
                        resource_count=0,
                    )
                )
            self._db.add_all(weekly_summaries)

        # ── Monthly Summary ────────────────────────────────────────
        # Build from the in-memory daily data to avoid a PostgreSQL GROUP BY
        # parameter-binding mismatch that causes "column must appear in GROUP BY".
        months_agg: dict[str, dict[str, float]] = {}
        for cost_date, total, prod, nonprod in all_daily_rows:
            month_key = str(cost_date)[:7]
            if month_key not in months_agg:
                months_agg[month_key] = {"total": 0.0, "prod": 0.0, "nonprod": 0.0}
            months_agg[month_key]["total"] += float(total or 0.0)
            months_agg[month_key]["prod"] += float(prod or 0.0)
            months_agg[month_key]["nonprod"] += float(nonprod or 0.0)
        monthly_rows = [(month_key, d["total"], d["prod"], d["nonprod"]) for month_key, d in sorted(months_agg.items())]

        await self._db.execute(delete(AmortizedCostMonthlySummary))
        if monthly_rows:
            monthly_summaries = []
            for month_year, total, prod, nonprod in monthly_rows:
                monthly_summaries.append(
                    AmortizedCostMonthlySummary(
                        month_year=str(month_year),
                        total_cost=float(total or 0.0),
                        production_cost=float(prod or 0.0),
                        non_production_cost=float(nonprod or 0.0),
                        service_count=0,
                        resource_count=0,
                    )
                )
            self._db.add_all(monthly_summaries)

        await self._db.commit()
        logger.info(
            "amortized_cost_aggregation_completed",
            daily_rows=len(daily_rows or []),
            weekly_rows=len(weeks or {}),
            monthly_rows=len(monthly_rows or []),
        )

    async def _add_pricing_backfill_ranges(
        self,
        per_sub_ranges: dict[str, list[tuple[date, date]]],
        sub_ids: list[str],
        full_start_date: date,
        end_date: date,
    ) -> int:
        """Queue days that have cost rows but no pricing rollup for a refetch.

        Days synced before the pricing rollup existed lack it and were written
        with per-row rounding; refetching backfills the pricing mix and restores
        full-precision, reconciled totals. Detection is per day, so a month that
        an earlier, shorter sync window only partly repaired is finished later.
        One range per month spans its first to last unpriced day (holes between
        are refetched too); existing ranges inside it are dropped. Returns the
        number of ranges added.
        """
        correction_cutoff = end_date - timedelta(days=CORRECTION_WINDOW_DAYS)
        if not sub_ids or correction_cutoff <= full_start_date:
            return 0

        def days_with_rows(model) -> object:
            return (
                select(model.subscription_id, model.cost_date)
                .where(
                    model.subscription_id.in_(sub_ids),
                    model.cost_date >= full_start_date.isoformat(),
                    model.cost_date < correction_cutoff.isoformat(),
                )
                .distinct()
            )

        record_days = {(sid, str(d)) for sid, d in (await self._db.execute(days_with_rows(AmortizedCostRecord))).all()}
        priced_days = {
            (sid, str(d)) for sid, d in (await self._db.execute(days_with_rows(AmortizedCostPricingDaily))).all()
        }
        unpriced_by_month: dict[tuple[str, str], list[str]] = defaultdict(list)
        for sid, day in record_days - priced_days:
            unpriced_by_month[(sid, day[:7])].append(day)

        added = 0
        for (sid, _month), days in sorted(unpriced_by_month.items()):
            lo, hi = date.fromisoformat(min(days)), date.fromisoformat(max(days))
            kept = [(s, e) for s, e in per_sub_ranges.get(sid, []) if not (s >= lo and e <= hi)]
            per_sub_ranges[sid] = [*kept, (lo, hi)]
            added += 1
        if added:
            logger.info("amortized_sync_pricing_backfill_ranges", ranges=added)
        return added

    # ── Read side: window, scope and SQL aggregates ───────────────────

    @classmethod
    def _analysis_window(cls, months: int, as_of: date) -> tuple[date, date]:
        """ "Last N months": the rolling start through the last closed UTC day.

        The current UTC day is excluded everywhere — it is still being ingested
        and showed up as a misleading drop to ~$0 at the end of every chart.
        """
        return cls._get_rolling_start_date(as_of, months), as_of - timedelta(days=1)

    async def _analysis_scope(
        self,
        env: str,
        scoped_ids: list[str] | None,
        since: date,
    ) -> tuple[list[str], dict[str, str], dict[str, str]]:
        """Subscriptions an analysis covers, with display names and Prod/Non-Prod.

        Returns ``(subscription_ids, name_by_sub, env_by_sub)``. The Admin panel
        wins; subscriptions unknown to it fall back to what their rows store.
        An empty ``scoped_ids`` means "every subscription with data".
        """
        labels = await self._subscription_labels()
        stmt = (
            select(
                AmortizedCostRecord.subscription_id,
                func.max(AmortizedCostRecord.subscription_name),
                func.max(AmortizedCostRecord.env_label),
            )
            .where(AmortizedCostRecord.cost_date >= since.isoformat())
            .group_by(AmortizedCostRecord.subscription_id)
        )
        if scoped_ids:
            stmt = stmt.where(AmortizedCostRecord.subscription_id.in_(scoped_ids))
        stored = {sid: (name, label) for sid, name, label in (await self._db.execute(stmt)).all() if sid}

        candidates = list(dict.fromkeys(scoped_ids)) if scoped_ids else sorted(stored)
        name_by_sub: dict[str, str] = {}
        env_by_sub: dict[str, str] = {}
        for sid in candidates:
            admin_name, admin_env = labels.get(sid, (None, None))
            stored_name, stored_env = stored.get(sid, (None, None))
            if stored_name == sid:
                stored_name = None
            name_by_sub[sid] = admin_name or stored_name or sid
            if admin_env:
                env_by_sub[sid] = admin_env
            else:
                env_by_sub[sid] = stored_env if stored_env in ("Prod", "Non-Prod") else "Prod"

        wanted = {"PROD": "Prod", "NONPROD": "Non-Prod"}.get((env or "ALL").upper())
        if wanted:
            candidates = [sid for sid in candidates if env_by_sub[sid] == wanted]
        return candidates, name_by_sub, env_by_sub

    @staticmethod
    def _window_clauses(model, sub_ids: list[str], start: date, end: date) -> list:
        # cost_date is stored as String(10) 'YYYY-MM-DD', so compare with ISO
        # strings — a date object raises "operator does not exist: character
        # varying >= date" on PostgreSQL.
        return [
            model.subscription_id.in_(sub_ids),
            model.cost_date >= start.isoformat(),
            model.cost_date <= end.isoformat(),
        ]

    @staticmethod
    def _match_text(column, value: str):
        """Case-insensitive match; "Unknown" also matches blanks, as breakdowns label them."""
        needle = value.strip().lower()
        clause = func.lower(column) == needle
        if needle == "unknown":
            clause = or_(clause, column.is_(None), column == "")
        return clause

    async def _query_daily_rows(self, sub_ids: list[str], start: date, end: date, extra: Iterable = ()) -> list[dict]:
        """Cost per (day, subscription, service) — the grain of every time series."""
        R = AmortizedCostRecord  # noqa: N806
        result = await self._db.execute(
            select(R.cost_date, R.subscription_id, R.meter_category, func.sum(R.cost_amount), func.count(R.id))
            .where(*self._window_clauses(R, sub_ids, start, end), *extra)
            .group_by(R.cost_date, R.subscription_id, R.meter_category)
        )
        return [
            {
                "date": str(day),
                "subscription_id": sid,
                "service": category or "Unknown",
                "cost": float(cost or 0.0),
                "rows": int(count or 0),
            }
            for day, sid, category, cost, count in result.all()
        ]

    async def _query_resource_rows(
        self, sub_ids: list[str], start: date, end: date, extra: Iterable = ()
    ) -> list[dict]:
        """Cost per resource (subscription, group, name, service) over the window."""
        R = AmortizedCostRecord  # noqa: N806
        result = await self._db.execute(
            select(
                R.subscription_id,
                R.resource_group,
                R.resource_name,
                R.meter_category,
                func.max(R.resource_type),
                func.max(R.resource_location),
                func.sum(R.cost_amount),
                func.count(distinct(R.cost_date)),
                func.min(R.cost_date),
                func.max(R.cost_date),
            )
            .where(*self._window_clauses(R, sub_ids, start, end), *extra)
            .group_by(R.subscription_id, R.resource_group, R.resource_name, R.meter_category)
        )
        return [
            {
                "subscription_id": sid,
                "resource_group": rg or "",
                "resource_name": name or "",
                "meter_category": category or "",
                "resource_type": rtype or "",
                "location": location or "",
                "cost": float(cost or 0.0),
                "active_days": int(days or 0),
                "first_date": str(first or ""),
                "last_date": str(last or ""),
            }
            for sid, rg, name, category, rtype, location, cost, days, first, last in result.all()
        ]

    async def _query_pricing_rows(self, sub_ids: list[str], start: date, end: date) -> list[dict]:
        """Daily pricing-model / charge-type rollup for the window."""
        P = AmortizedCostPricingDaily  # noqa: N806
        result = await self._db.execute(
            select(P.cost_date, P.subscription_id, P.pricing_model, P.charge_type, func.sum(P.cost_amount))
            .where(*self._window_clauses(P, sub_ids, start, end))
            .group_by(P.cost_date, P.subscription_id, P.pricing_model, P.charge_type)
        )
        return [
            {
                "date": str(day),
                "subscription_id": sid,
                "pricing_model": model or "",
                "charge_type": charge or "",
                "cost": float(cost or 0.0),
            }
            for day, sid, model, charge, cost in result.all()
        ]

    @staticmethod
    def _build_coverage(
        daily_rows: list[dict],
        expected_subs: list[str],
        names: dict[str, str],
        start: date,
        end: date,
    ) -> dict:
        """Which expected subscriptions have no data on some days of [start, end].

        Active Azure subscriptions accrue cost every day (storage alone), so a
        day without rows means the sync never loaded it — not that it was free.
        """
        days_by_sub: dict[str, set[str]] = defaultdict(set)
        for row in daily_rows:
            days_by_sub[row["subscription_id"]].add(row["date"])
        all_days = [start + timedelta(days=i) for i in range((end - start).days + 1)]
        issues = []
        for sid in sorted(expected_subs, key=lambda s: names.get(s, s).lower()):
            have = days_by_sub.get(sid, set())
            missing = [d for d in all_days if d.isoformat() not in have]
            if not missing:
                continue
            runs = _compress_dates(missing)
            issues.append(
                {
                    "subscription_id": sid,
                    "subscription_name": names.get(sid, sid),
                    # No rows at all: either genuinely no spend or never synced —
                    # the dashboard can't tell which, so it says both.
                    "no_data": not have,
                    "missing_days": len(missing),
                    "total_days": len(all_days),
                    "missing_ranges": [{"start": a.isoformat(), "end": b.isoformat()} for a, b in runs[:10]],
                    "missing_range_count": len(runs),
                }
            )
        return {
            "window_start": start.isoformat(),
            "window_end": end.isoformat(),
            "expected_subscriptions": len(expected_subs),
            "complete": not issues,
            "issues": issues,
        }

    # ── Analytics from DB ─────────────────────────────────────────────

    async def get_amortized_cost_data(
        self,
        env: str = "ALL",
        months: int = 2,
    ) -> dict:
        """Amortized analytics payload for the dashboard, aggregated in SQL.

        The table holds one row per resource, service and day — ~600k rows for
        a year — so it is never loaded into Python whole.
        """
        started = perf_counter()
        as_of = utc_today()
        scoped_ids = await get_scoped_subscription_ids()
        cache_key = self._summary_cache_key(env, months, scoped_ids, as_of)
        cached = await cache_manager.get_cached(cache_key)
        if cached:
            try:
                payload = json.loads(cached)
                logger.info(
                    "amortized_summary_served",
                    source="cache",
                    environment=env,
                    months=months,
                    elapsed_ms=round((perf_counter() - started) * 1000, 2),
                )
                return payload
            except (json.JSONDecodeError, TypeError):
                pass

        window_start, window_end = self._analysis_window(months, as_of)
        sub_ids, names, envs = await self._analysis_scope(env, scoped_ids, window_start)
        daily_rows = await self._query_daily_rows(sub_ids, window_start, window_end)
        resource_rows = await self._query_resource_rows(sub_ids, window_start, window_end)
        pricing_rows = await self._query_pricing_rows(sub_ids, window_start, window_end)
        payload = self._build_analytics(
            daily_rows,
            resource_rows,
            pricing_rows,
            env=env,
            window_start=window_start,
            window_end=window_end,
            as_of=as_of,
            names=names,
            envs=envs,
            expected_subs=sub_ids,
        )
        ttl = await get_effective_cache_ttl_seconds(self._db)
        await cache_manager.set_cached(cache_key, json.dumps(payload, default=str), ttl=ttl)
        logger.info(
            "amortized_summary_served",
            source="database",
            environment=env,
            months=months,
            row_count=payload["row_count"],
            elapsed_ms=round((perf_counter() - started) * 1000, 2),
        )
        return payload

    @staticmethod
    def _build_analytics(
        daily_rows: list[dict],
        resource_rows: list[dict],
        pricing_rows: list[dict],
        *,
        env: str,
        window_start: date,
        window_end: date,
        as_of: date,
        names: dict[str, str],
        envs: dict[str, str],
        expected_subs: list[str],
    ) -> dict:
        """Build the amortized dashboard payload from SQL aggregates.

        ``daily_rows`` are (day, subscription, service) totals, ``resource_rows``
        per-resource totals for the window, ``pricing_rows`` the pricing-model
        rollup. All three cover the same subscriptions and dates, so every
        breakdown adds up to the same total.
        """
        preliminary_from = (as_of - timedelta(days=PRELIMINARY_DAYS)).isoformat()
        span = (window_end - window_start).days + 1
        trend_dates = [(window_start + timedelta(days=i)).isoformat() for i in range(span)]
        base = {
            "environment": env,
            "date_range": {"start": window_start.isoformat(), "end": window_end.isoformat()},
            "as_of": as_of.isoformat(),
            "preliminary_from": preliminary_from,
            "coverage": AmortizedCostSyncService._build_coverage(
                daily_rows, expected_subs, names, window_start, window_end
            ),
            "generated_at": datetime.utcnow().isoformat(),
        }
        if not daily_rows:
            return {
                **base,
                "total_cost": 0,
                "row_count": 0,
                "data_through": None,
                "daily_trend": [],
                "service_breakdown": [],
                "resource_group_breakdown": [],
                "resource_type_breakdown": [],
                "location_breakdown": [],
                "subscription_breakdown": [],
                "top_resources": [],
                "service_count": 0,
                "resource_count": 0,
                "resource_group_count": 0,
                "subscription_count": 0,
                "monthly_pivot": {},
                "env_comparison": {},
                "charge_type_breakdown": [],
                "pricing_model_breakdown": [],
                "commitment": None,
                "daily_by_service": [],
                "top_service_names": [],
                "source_date_range": {"start": "", "end": ""},
                "latest_available_date": None,
                "has_pending_source_data": False,
            }

        def env_of(sid: str) -> str:
            return envs.get(sid, "Prod")

        def name_of(sid: str) -> str:
            return names.get(sid, sid)

        total_cost = sum(r["cost"] for r in daily_rows)
        row_count = sum(r["rows"] for r in daily_rows)
        present_days = sorted({r["date"] for r in daily_rows})
        data_through = present_days[-1]

        day_total: dict[str, float] = defaultdict(float)
        day_prod: dict[str, float] = defaultdict(float)
        day_nonprod: dict[str, float] = defaultdict(float)
        svc_cost: dict[str, float] = defaultdict(float)
        sub_cost: dict[str, float] = defaultdict(float)
        month_svc: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
        env_totals: dict[str, float] = defaultdict(float)
        env_by_month: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
        for r in daily_rows:
            day, sid, svc, cost = r["date"], r["subscription_id"], r["service"], r["cost"]
            label = env_of(sid)
            day_total[day] += cost
            (day_prod if label == "Prod" else day_nonprod)[day] += cost
            svc_cost[svc] += cost
            sub_cost[sid] += cost
            month_svc[day[:7]][svc] += cost
            env_totals[label] += cost
            env_by_month[day[:7]][label] += cost

        # ── 1. Daily trend — a day with no data is a gap (null), not a fake $0 ──
        daily_trend = [
            {
                "date": d,
                "cost": round(day_total[d], 2) if d in day_total else None,
                "prod": round(day_prod.get(d, 0.0), 2) if d in day_total else None,
                "non_prod": round(day_nonprod.get(d, 0.0), 2) if d in day_total else None,
                "preliminary": d >= preliminary_from,
            }
            for d in trend_dates
        ]

        # ── 2. Service and subscription breakdowns ───────────────────
        service_breakdown = _breakdown(svc_cost, total_cost)
        subscription_breakdown = sorted(
            (
                {
                    "name": name_of(sid),
                    "subscription_id": sid,
                    "environment": env_of(sid),
                    "cost": round(cost, 2),
                    "pct": round(cost / total_cost * 100, 2) if total_cost else 0,
                }
                for sid, cost in sub_cost.items()
            ),
            key=lambda item: item["cost"],
            reverse=True,
        )

        # ── 3. Resource-level breakdowns ─────────────────────────────
        rg_cost: dict[str, float] = defaultdict(float)
        rt_cost: dict[str, float] = defaultdict(float)
        loc_cost: dict[str, float] = defaultdict(float)
        resource_keys: set[tuple[str, str, str]] = set()
        for r in resource_rows:
            rg_cost[r["resource_group"] or "Unknown"] += r["cost"]
            rt_cost[r["resource_type"] or "Unknown"] += r["cost"]
            loc_cost[r["location"] or "Unknown"] += r["cost"]
            if r["resource_name"]:
                resource_keys.add((r["subscription_id"], r["resource_group"].lower(), r["resource_name"].lower()))

        top_resources = []
        for r in sorted(resource_rows, key=lambda item: item["cost"], reverse=True)[:50]:
            if r["resource_name"]:
                rname = r["resource_name"]
            elif r["meter_category"]:
                rname = f"Subscription-level ({r['meter_category']})"
            else:
                rname = "Subscription-level"
            top_resources.append(
                {
                    "resource_name": rname,
                    "resource_group": r["resource_group"],
                    "resource_type": r["resource_type"],
                    "meter_category": r["meter_category"],
                    "location": r["location"],
                    "subscription": name_of(r["subscription_id"]),
                    "cost": round(r["cost"], 2),
                    "active_days": r["active_days"],
                }
            )

        # ── 4. Monthly pivot (service × month), flagging partial months ──
        all_months = sorted(month_svc)
        pivot_services = sorted(
            (
                {
                    "service_name": svc,
                    "monthly_costs": {mk: round(month_svc[mk].get(svc, 0.0), 2) for mk in all_months},
                    "total": round(cost, 2),
                }
                for svc, cost in svc_cost.items()
            ),
            key=lambda item: item["total"],
            reverse=True,
        )
        month_coverage = {}
        for mk in all_months:
            first = date(int(mk[:4]), int(mk[5:7]), 1)
            last = date(first.year, first.month, monthrange(first.year, first.month)[1])
            lo, hi = max(first, window_start), min(last, window_end)
            month_coverage[mk] = {
                "start": lo.isoformat(),
                "end": hi.isoformat(),
                "days": (hi - lo).days + 1,
                "days_in_month": last.day,
                "partial": lo > first or hi < last,
            }
        monthly_pivot = {
            "months": all_months,
            "month_labels": {mk: date(int(mk[:4]), int(mk[5:7]), 1).strftime("%Y %b") for mk in all_months},
            "month_coverage": month_coverage,
            "services": pivot_services,
            "monthly_totals": {mk: round(sum(month_svc[mk].values()), 2) for mk in all_months},
            "grand_total": round(total_cost, 2),
        }

        # ── 5. Env comparison (Prod vs Non-Prod) ─────────────────────
        env_comparison = {
            "totals": {k: round(v, 2) for k, v in env_totals.items()},
            "monthly": {mk: {k: round(v, 2) for k, v in envs_.items()} for mk, envs_ in sorted(env_by_month.items())},
        }

        # ── 6. Pricing model / charge type (from the daily rollup) ───
        pricing_total = sum(p["cost"] for p in pricing_rows)
        pm_cost: dict[str, float] = defaultdict(float)
        ct_cost: dict[str, float] = defaultdict(float)
        for p in pricing_rows:
            pm_cost[p["pricing_model"] or "Unknown"] += p["cost"]
            ct_cost[p["charge_type"] or "Unknown"] += p["cost"]
        covered = sum(cost for name, cost in pm_cost.items() if name in COMMITMENT_PRICING_MODELS)
        commitment = (
            {
                "covered_cost": round(covered, 2),
                "covered_pct": round(covered / pricing_total * 100, 2) if pricing_total else 0,
                "pricing_total": round(pricing_total, 2),
                "pricing_coverage_pct": round(pricing_total / total_cost * 100, 2) if total_cost else 0,
                "complete": abs(pricing_total - total_cost) <= max(1.0, abs(total_cost) * 0.005),
            }
            if pricing_rows
            else None
        )

        # ── 7. Daily cost by top services (for stacked area) ─────────
        top_svc_names = [str(s["name"]) for s in service_breakdown[:8]]
        top_set = set(top_svc_names)
        daily_by_svc: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
        for r in daily_rows:
            daily_by_svc[r["date"]][r["service"] if r["service"] in top_set else "Other"] += r["cost"]
        daily_by_service = []
        for d in trend_dates:
            entry: dict[str, str | float | None] = {"date": d}
            for svc_name in [*top_svc_names, "Other"]:
                entry[svc_name] = round(daily_by_svc[d].get(svc_name, 0.0), 2) if d in day_total else None
            daily_by_service.append(entry)

        return {
            **base,
            "total_cost": round(total_cost, 2),
            "row_count": row_count,
            "data_through": data_through,
            "daily_trend": daily_trend,
            "service_breakdown": service_breakdown,
            "resource_group_breakdown": _breakdown(rg_cost, total_cost),
            "resource_type_breakdown": _breakdown(rt_cost, total_cost),
            "location_breakdown": _breakdown(loc_cost, total_cost),
            "subscription_breakdown": subscription_breakdown,
            "top_resources": top_resources,
            "service_count": len(svc_cost),
            "resource_count": len(resource_keys),
            "resource_group_count": len(rg_cost),
            "subscription_count": len(sub_cost),
            "monthly_pivot": monthly_pivot,
            "env_comparison": env_comparison,
            "charge_type_breakdown": _breakdown(ct_cost, pricing_total),
            "pricing_model_breakdown": _breakdown(pm_cost, pricing_total),
            "commitment": commitment,
            "daily_by_service": daily_by_service,
            "top_service_names": top_svc_names,
            "source_date_range": {"start": present_days[0], "end": data_through},
            "latest_available_date": data_through,
            "has_pending_source_data": data_through < window_end.isoformat(),
        }

    async def get_resource_drilldown(
        self,
        env: str = "ALL",
        months: int = 2,
        resource_group: str | None = None,
        meter_category: str | None = None,
        subscription: str | None = None,
    ) -> dict:
        """Resource-level drill-down, aggregated in SQL on every request."""
        started = perf_counter()
        as_of = utc_today()
        window_start, window_end = self._analysis_window(months, as_of)
        scoped_ids = await get_scoped_subscription_ids()
        sub_ids, names, _envs = await self._analysis_scope(env, scoped_ids, window_start)
        if subscription:
            needle = subscription.strip().lower()
            sub_ids = [sid for sid in sub_ids if needle in (sid.lower(), names.get(sid, sid).lower())]

        R = AmortizedCostRecord  # noqa: N806
        extra = []
        if resource_group:
            extra.append(self._match_text(R.resource_group, resource_group))
        if meter_category:
            extra.append(self._match_text(R.meter_category, meter_category))

        resource_rows = await self._query_resource_rows(sub_ids, window_start, window_end, extra)
        daily_rows = await self._query_daily_rows(sub_ids, window_start, window_end, extra)

        daily: dict[str, float] = defaultdict(float)
        for r in daily_rows:
            daily[r["date"]] += r["cost"]
        resources = [
            {
                "resource_name": r["resource_name"] if r["resource_name"] != r["meter_category"] else "",
                "resource_group": r["resource_group"],
                # Azure omits ResourceType for some charges (reservations, AKS
                # managed VMs); fall back to the service so the column is useful.
                "resource_type": r["resource_type"] or r["meter_category"],
                "meter_category": r["meter_category"],
                "location": r["location"],
                "subscription": names.get(r["subscription_id"], r["subscription_id"]),
                "cost": round(r["cost"], 2),
                "active_days": r["active_days"],
            }
            for r in sorted(resource_rows, key=lambda item: item["cost"], reverse=True)[:200]
        ]
        payload = {
            "filters": {
                "environment": env,
                "resource_group": resource_group,
                "meter_category": meter_category,
                "subscription": subscription,
            },
            "date_range": {"start": window_start.isoformat(), "end": window_end.isoformat()},
            "total_cost": round(sum(r["cost"] for r in resource_rows), 2),
            "row_count": sum(r["rows"] for r in daily_rows),
            "resource_count": len(resource_rows),
            "resources": resources,
            "daily_trend": [{"date": d, "cost": round(c, 2)} for d, c in sorted(daily.items())],
            "generated_at": datetime.utcnow().isoformat(),
        }
        logger.info(
            "amortized_drilldown_served",
            source="database",
            environment=env,
            months=months,
            resource_group=resource_group,
            meter_category=meter_category,
            subscription=subscription,
            resource_count=len(resource_rows),
            elapsed_ms=round((perf_counter() - started) * 1000, 2),
        )
        return payload

    # ── CSV export ────────────────────────────────────────────────────

    async def build_export_spec(self, env: str, months: int) -> dict:
        """Resolve window and subscription scope for an export (needs request context)."""
        as_of = utc_today()
        window_start, window_end = self._analysis_window(months, as_of)
        scoped_ids = await get_scoped_subscription_ids()
        sub_ids, names, envs = await self._analysis_scope(env, scoped_ids, window_start)
        return {
            "env": (env or "ALL").upper(),
            "sub_ids": sub_ids,
            "names": names,
            "envs": envs,
            "start": window_start,
            "end": window_end,
            "preliminary_from": as_of - timedelta(days=PRELIMINARY_DAYS),
        }

    @staticmethod
    def export_filename(spec: dict, level: str) -> str:
        env, start, end = spec["env"].lower(), spec["start"].isoformat(), spec["end"].isoformat()
        return f"amortized-cost-{level}-{env}-{start}-to-{end}.csv"

    async def iter_export_csv(self, spec: dict, level: str) -> AsyncIterator[str]:
        """Stream the export as CSV text chunks.

        ``resources``: one row per resource and service for the window.
        ``daily``: every stored row (resource, service, day).

        Costs carry enough decimals that the column sums to the dashboard total
        to the cent: Azure reports thousands of sub-microcent rows, so rounding
        each row (even to 6 places) drifts the total.
        """
        names, envs = spec["names"], spec["envs"]
        buffer = io.StringIO()
        writer = csv.writer(buffer)

        def drain() -> str:
            text = buffer.getvalue()
            buffer.seek(0)
            buffer.truncate(0)
            return text

        if level == "resources":
            writer.writerow(
                [
                    "Subscription",
                    "Subscription ID",
                    "Environment",
                    "Resource Group",
                    "Resource Name",
                    "Resource Type",
                    "Service (Meter Category)",
                    "Location",
                    "Active Days",
                    "First Date",
                    "Last Date",
                    "Cost (USD)",
                ]
            )
            rows = await self._query_resource_rows(spec["sub_ids"], spec["start"], spec["end"])
            for r in sorted(rows, key=lambda item: item["cost"], reverse=True):
                sid = r["subscription_id"]
                writer.writerow(
                    [
                        names.get(sid, sid),
                        sid,
                        envs.get(sid, ""),
                        r["resource_group"],
                        r["resource_name"],
                        r["resource_type"],
                        r["meter_category"],
                        r["location"],
                        r["active_days"],
                        r["first_date"],
                        r["last_date"],
                        f"{r['cost']:.6f}",
                    ]
                )
            yield drain()
            return

        writer.writerow(
            [
                "Date",
                "Subscription",
                "Subscription ID",
                "Environment",
                "Resource Group",
                "Resource Name",
                "Resource Type",
                "Service (Meter Category)",
                "Location",
                "Cost (USD)",
                "Preliminary",
            ]
        )
        yield drain()
        R = AmortizedCostRecord  # noqa: N806
        preliminary_from = spec["preliminary_from"].isoformat()
        stmt = (
            select(
                R.cost_date,
                R.subscription_id,
                R.resource_group,
                R.resource_name,
                R.resource_type,
                R.meter_category,
                R.resource_location,
                R.cost_amount,
            )
            .where(*self._window_clauses(R, spec["sub_ids"], spec["start"], spec["end"]))
            .order_by(R.cost_date, R.subscription_id, R.resource_group, R.resource_name)
            .execution_options(yield_per=5000)
        )
        result = await self._db.stream(stmt)
        async for partition in result.partitions(5000):
            for day, sid, rg, name, rtype, category, location, cost in partition:
                writer.writerow(
                    [
                        day,
                        names.get(sid, sid),
                        sid,
                        envs.get(sid, ""),
                        rg or "",
                        name or "",
                        rtype or "",
                        category or "",
                        location or "",
                        f"{float(cost or 0.0):.10f}",
                        "Yes" if str(day) >= preliminary_from else "No",
                    ]
                )
            yield drain()

    # ── Leadership dashboard builder ──────────────────────────────────

    async def build_leadership_dashboard(
        self,
        subscription_ids: list[str] | None = None,
    ) -> LeadershipDashboard | None:
        """Build the Cost Forecast payload from ``amortized_cost_records``.

        Returns None when there is no data for the last ~15 closed days (the
        caller then falls back to live Azure). ``subscription_ids`` limits the
        scope: the per-user picker, or the monitored set for the snapshot.

        Every figure runs through the last closed UTC day that has data, and
        month-over-month compares the same days of each month. Comparing a
        partial month to a full one reported a fake ~-78% drop a week in.
        """
        from app.schemas.cost import (
            CostByGroup,
            CostDataPoint,
            CostTrendDirection,
            DataQualityIssue,
            GroupByDimension,
            KPIMetric,
            LeadershipDashboard,
            MonthlyCostPoint,
            PricingMixItem,
        )

        R, P = AmortizedCostRecord, AmortizedCostPricingDaily  # noqa: N806
        as_of = utc_today()
        last_closed = as_of - timedelta(days=1)

        def scoped(stmt, model=R):
            return stmt.where(model.subscription_id.in_(subscription_ids)) if subscription_ids else stmt

        latest = await self._db.scalar(
            scoped(select(func.max(R.cost_date)).where(R.cost_date <= last_closed.isoformat()))
        )
        if not latest:
            return None
        data_end = date.fromisoformat(str(latest))
        if data_end < last_closed - timedelta(days=15):
            return None

        month_start = data_end.replace(day=1)
        days_elapsed = data_end.day
        days_in_month = monthrange(data_end.year, data_end.month)[1]
        prev_start = _shift_month(month_start, -1)
        prev_end = month_start - timedelta(days=1)
        prev2_start = _shift_month(month_start, -2)
        prev2_end = prev_start - timedelta(days=1)
        lfl_end = prev_start + timedelta(days=min(days_elapsed, prev_end.day) - 1)
        six_start = _shift_month(month_start, -6)

        sub_ids, names, envs = await self._analysis_scope("ALL", subscription_ids, six_start)
        result = await self._db.execute(
            scoped(
                select(R.cost_date, R.subscription_id, func.sum(R.cost_amount))
                .where(R.cost_date >= six_start.isoformat(), R.cost_date <= data_end.isoformat())
                .group_by(R.cost_date, R.subscription_id)
            )
        )
        daily: dict[tuple[date, str], float] = {
            (date.fromisoformat(str(day)), sid): float(cost or 0.0) for day, sid, cost in result.all()
        }

        def total(lo: date, hi: date) -> float:
            return sum(cost for (day, _), cost in daily.items() if lo <= day <= hi)

        def money(value: float) -> Decimal:
            return Decimal(str(round(value, 2)))

        def direction(pct: float | None) -> CostTrendDirection:
            if pct is None:
                return CostTrendDirection.STABLE
            if pct > 5:
                return CostTrendDirection.UP
            if pct < -5:
                return CostTrendDirection.DOWN
            return CostTrendDirection.STABLE

        mtd = total(month_start, data_end)
        like_for_like = total(prev_start, lfl_end)
        last_month = total(prev_start, prev_end)
        month_before = total(prev2_start, prev2_end)
        daily_avg = mtd / days_elapsed
        projected = daily_avg * days_in_month
        lfl_days = (lfl_end - prev_start).days + 1
        # Same days of each month; when last month is shorter (Mar 30 vs Feb 28)
        # compare daily averages so the extra days don't read as growth.
        mom = _pct_change(mtd / days_elapsed, like_for_like / lfl_days) if like_for_like else None
        projected_vs_last = _pct_change(projected, last_month)
        last_vs_before = _pct_change(last_month, month_before)

        sub_count = len(sub_ids)
        scope_suffix = f" · {sub_count} subscription{'s' if sub_count != 1 else ''}"
        mtd_period = _fmt_period(month_start, data_end)
        lfl_period = _fmt_period(prev_start, lfl_end)
        kpis = [
            KPIMetric(
                name="Month-to-Date Spend",
                value=money(mtd),
                unit="USD",
                trend=direction(mom),
                change_pct=round(mom or 0.0, 1),
                description=f"{mtd_period} · {days_elapsed} of {days_in_month} days{scope_suffix}",
                comparison_label=f"vs {lfl_period}" if mom is not None else None,
            ),
            KPIMetric(
                name="Projected Monthly Spend",
                value=money(projected),
                unit="USD",
                trend=direction(projected_vs_last),
                change_pct=round(projected_vs_last or 0.0, 1),
                description=f"{data_end:%B} run-rate: ${daily_avg:,.0f}/day × {days_in_month} days",
                comparison_label=f"vs {prev_start:%B} actual" if projected_vs_last is not None else None,
            ),
            KPIMetric(
                name="Last Month Spend",
                value=money(last_month),
                unit="USD",
                trend=direction(last_vs_before),
                change_pct=round(last_vs_before or 0.0, 1),
                description=f"{prev_start:%B %Y} · full month{scope_suffix}",
                comparison_label=f"vs {prev2_start:%B}" if last_vs_before is not None else None,
            ),
            KPIMetric(
                name="Month-over-Month Change",
                value=round(mom or 0.0, 1),
                unit="%",
                trend=direction(mom),
                change_pct=round(mom or 0.0, 1),
                description=(
                    f"Like-for-like: {mtd_period} vs {lfl_period}"
                    + (" (daily average)" if lfl_days != days_elapsed else "")
                    if mom is not None
                    else f"No data for {lfl_period} to compare against"
                ),
            ),
        ]

        # Daily cost trend: the last 15 closed days, one series per subscription.
        trend_start = data_end - timedelta(days=14)
        cost_trend = [
            CostDataPoint(
                date=day,
                cost=money(cost),
                currency="USD",
                group_value=names.get(sid, sid),
                group_dimension=GroupByDimension.SUBSCRIPTION,
            )
            for (day, sid), cost in sorted(daily.items())
            if day >= trend_start
        ]

        # Top spenders: month to date, as a share of the true MTD total.
        mtd_by_sub: dict[str, float] = defaultdict(float)
        for (day, sid), cost in daily.items():
            if month_start <= day <= data_end:
                mtd_by_sub[sid] += cost
        top_spenders = [
            CostByGroup(
                group_dimension=GroupByDimension.SUBSCRIPTION,
                group_value=names.get(sid, sid),
                total_cost=money(cost),
                percentage_of_total=round(cost / mtd * 100, 2) if mtd else 0.0,
                currency="USD",
            )
            for sid, cost in sorted(mtd_by_sub.items(), key=lambda kv: kv[1], reverse=True)[:10]
        ]

        # Six full months before the current one. The partial current month is
        # excluded — it poisoned the forecast's anchor — and each month says
        # whether every subscription has data for every day.
        days_by_sub: dict[str, set[date]] = defaultdict(set)
        for day, sid in daily:
            days_by_sub[sid].add(day)
        # A subscription with no rows at all is reported under data_quality; it
        # can't make individual months look incomplete relative to each other.
        subs_with_data = [sid for sid in sub_ids if days_by_sub.get(sid)]
        six_month_trend: list[MonthlyCostPoint] = []
        cursor = six_start
        while cursor <= prev_start:
            month_end = date(cursor.year, cursor.month, monthrange(cursor.year, cursor.month)[1])
            prod = nonprod = 0.0
            by_sub: dict[str, float] = defaultdict(float)
            for (day, sid), cost in daily.items():
                if cursor <= day <= month_end:
                    by_sub[names.get(sid, sid)] += cost
                    if envs.get(sid, "Prod") == "Non-Prod":
                        nonprod += cost
                    else:
                        prod += cost
            missing_days = sum(
                1
                for sid in subs_with_data
                for offset in range(month_end.day)
                if cursor + timedelta(days=offset) not in days_by_sub.get(sid, set())
            )
            if by_sub:
                six_month_trend.append(
                    MonthlyCostPoint(
                        month=cursor.strftime("%Y-%m"),
                        month_label=cursor.strftime("%b %Y"),
                        total_cost=money(prod) + money(nonprod),
                        prod_cost=money(prod),
                        non_prod_cost=money(nonprod),
                        subscription_breakdown={k: money(v) for k, v in by_sub.items()},
                        complete=missing_days == 0,
                        missing_days=missing_days,
                    )
                )
            cursor = _shift_month(cursor, 1)

        # Data quality: stale data and per-subscription gaps leadership must know about.
        data_quality: list[DataQualityIssue] = []
        lag_days = (last_closed - data_end).days
        if lag_days >= 2:
            data_quality.append(
                DataQualityIssue(
                    kind="stale",
                    missing_days=lag_days,
                    message=(
                        f"Cost data ends {data_end:%b} {data_end.day}, {data_end.year}; "
                        f"the {lag_days} most recent closed days have not been synced yet."
                    ),
                )
            )
        coverage = self._build_coverage(
            [{"date": day.isoformat(), "subscription_id": sid} for day, sid in daily],
            sub_ids,
            names,
            six_start,
            data_end,
        )
        for issue in coverage["issues"]:
            data_quality.append(
                DataQualityIssue(
                    kind="missing_data",
                    subscription_id=issue["subscription_id"],
                    subscription_name=issue["subscription_name"],
                    no_data=issue["no_data"],
                    missing_days=issue["missing_days"],
                    missing_ranges=[
                        r["start"] if r["start"] == r["end"] else f"{r['start']} → {r['end']}"
                        for r in issue["missing_ranges"]
                    ],
                    message=(
                        f"{issue['subscription_name']} has no cost data since {six_start:%b %Y} — "
                        "either it had no spend or it has not been synced yet."
                        if issue["no_data"]
                        else f"{issue['subscription_name']} has no cost data for {issue['missing_days']} day(s) "
                        f"since {six_start:%b %Y}; totals exclude those days until the sync backfills them."
                    ),
                )
            )

        # Pricing mix (commitment coverage) for the last full month.
        pm_result = await self._db.execute(
            scoped(
                select(P.pricing_model, func.sum(P.cost_amount))
                .where(P.cost_date >= prev_start.isoformat(), P.cost_date <= prev_end.isoformat())
                .group_by(P.pricing_model),
                P,
            )
        )
        pm_costs: dict[str, float] = defaultdict(float)
        for model_name, cost in pm_result.all():
            pm_costs[model_name or "Unknown"] += float(cost or 0.0)
        pm_total = sum(pm_costs.values())
        pricing_mix = [
            PricingMixItem(name=name, cost=money(cost), pct=round(cost / pm_total * 100, 2))
            for name, cost in sorted(pm_costs.items(), key=lambda kv: kv[1], reverse=True)
            if pm_total
        ]

        return LeadershipDashboard(
            kpis=kpis,
            cost_trend=cost_trend,
            top_spenders=top_spenders,
            six_month_trend=six_month_trend,
            savings_opportunities=Decimal("0"),
            report_date=datetime.utcnow(),
            data_through=data_end,
            preliminary_from=as_of - timedelta(days=PRELIMINARY_DAYS),
            data_quality=data_quality,
            pricing_mix=pricing_mix,
            pricing_mix_month=prev_start.strftime("%b %Y") if pricing_mix else None,
            pricing_mix_complete=bool(pm_total) and abs(pm_total - last_month) <= max(1.0, last_month * 0.005),
        )

    # ── Sync-status endpoint helper ───────────────────────────────────

    async def get_sync_status(self) -> dict:
        """Return latest sync status for the dashboard header."""
        await self._expire_abandoned_running_rows()
        monitored_subscription_ids = await get_monitored_subscription_ids()
        scoped_subscription_ids = await get_scoped_subscription_ids()
        data_through_stmt = select(func.max(AmortizedCostRecord.cost_date)).where(
            AmortizedCostRecord.cost_date < utc_today().isoformat()
        )
        if monitored_subscription_ids:
            data_through_stmt = data_through_stmt.where(
                AmortizedCostRecord.subscription_id.in_(monitored_subscription_ids)
            )
        data_through = await self._db.scalar(data_through_stmt)
        result = await self._db.execute(
            select(AmortizedCostSyncStatus).order_by(AmortizedCostSyncStatus.started_at.desc()).limit(1)
        )
        rec = result.scalars().first()
        if not rec:
            return {
                "last_sync": None,
                "started_at": None,
                "status": None,
                "data_through": str(data_through) if data_through else None,
                "warning": None,
                "monitored_subscription_ids": monitored_subscription_ids,
                "monitored_subscription_count": len(monitored_subscription_ids),
                "scoped_subscription_ids": scoped_subscription_ids,
                "scoped_subscription_count": len(scoped_subscription_ids),
            }

        duration_seconds: float | None = None
        if rec.completed_at and rec.started_at:
            duration_seconds = (rec.completed_at - rec.started_at).total_seconds()

        return {
            "last_sync": rec.completed_at.isoformat() if rec.completed_at else None,
            "started_at": rec.started_at.isoformat() if rec.started_at else None,
            "status": rec.status,
            "months_synced": rec.months_synced,
            "rows_synced": rec.rows_synced,
            "total_cost": rec.total_cost,
            "triggered_by": rec.triggered_by,
            "duration_seconds": duration_seconds,
            "error_message": rec.error_message,
            # A completed run that skipped some ranges records why here.
            "warning": rec.error_message if rec.status == "completed" and rec.error_message else None,
            "data_through": str(data_through) if data_through else None,
            "monitored_subscription_ids": monitored_subscription_ids,
            "monitored_subscription_count": len(monitored_subscription_ids),
            "scoped_subscription_ids": scoped_subscription_ids,
            "scoped_subscription_count": len(scoped_subscription_ids),
        }

    # ── Private helpers ───────────────────────────────────────────────

    def _summary_cache_key(
        self,
        env: str,
        months: int,
        subscription_scope: list[str] | None = None,
        as_of: date | None = None,
    ) -> str:
        scope = ",".join(sorted(subscription_scope or []))
        digest = hashlib.md5(scope.encode()).hexdigest()[:8] if scope else "all"
        # The window rolls at UTC midnight; never serve yesterday's window from cache.
        day = (as_of or utc_today()).isoformat()
        return f"pagecache:amortized:summary:{env.upper()}:{months}:{digest}:{day}"

    # The legacy non-prod token list lives in this module so every consumer
    # (sync writer, dashboard query, /nonprod-vs-prod) classifies the same way.
    _NON_PROD_TOKENS: frozenset[str] = frozenset(
        {
            "nonprod",
            "non-prod",
            "non_prod",
            "nprd",
            "nprod",
            "dev",
            "development",
            "test",
            "qa",
            "uat",
            "stg",
            "stage",
            "staging",
            "perf",
            "sandbox",
        }
    )
    _PROD_TOKENS: frozenset[str] = frozenset({"prod", "prd", "production"})

    @staticmethod
    def resolve_env_label(environment: str | None, subscription_name: str | None) -> str:
        """Best-effort Prod/Non-Prod for a subscription.

        Preferred input: ``AdminSubscription.environment`` set in the Admin
        panel. When that is empty (very common — ATT typically discovers
        subscriptions in bulk and admins forget the Environment field), we
        fall back to the subscription name. Names that follow the standard
        ATT pattern (``ACC-NPRD-…``, ``ACC-PROD-…``) classify correctly
        from the name alone, which is why this fallback exists.
        """
        env_value = (environment or "").strip()
        if env_value:
            return AmortizedCostSyncService.normalize_environment(env_value)
        return AmortizedCostSyncService.normalize_environment(subscription_name)

    @staticmethod
    def normalize_environment(environment: str | None) -> str:
        """Map a free-text ``environment`` value to ``Prod`` or ``Non-Prod``.

        ``environment`` comes from ``AdminSubscription.environment`` — the
        value an admin sets in the Admin panel. That is the single source
        of truth for prod/non-prod classification (no budget_config.json,
        no subscription-name guessing).

        Returns ``Prod`` for unset/unknown values so leadership reports never
        silently hide spend; admins who haven't tagged a subscription get
        Prod with a default-safe interpretation.
        """
        raw = str(environment or "").strip().lower()
        if not raw:
            return "Prod"

        # Collapse separators so 'non-prod' / 'non_prod' / 'NON PROD' /
        # 'non production' all normalise to 'nonprod' / 'nonproduction'.
        flat = raw.replace(" ", "").replace("_", "").replace("-", "")

        # Non-prod tokens MUST be checked first — 'nonproduction' contains
        # both 'nonprod' (non-prod) and 'production' (prod). Whichever runs
        # first wins; we want non-prod to win.
        flat_non_prod = {t.replace("-", "").replace("_", "") for t in AmortizedCostSyncService._NON_PROD_TOKENS}
        for token in flat_non_prod:
            if token in flat:
                return "Non-Prod"
        for token in AmortizedCostSyncService._PROD_TOKENS:
            if token in flat:
                return "Prod"
        return "Prod"

    @staticmethod
    def _derive_env_label(row: dict) -> str:
        """Derive Prod/Non-Prod from the row's ``environment`` value.

        ``environment`` is populated from ``AdminSubscription.environment``
        at sync time (see ``_fetch_subscription_metadata``). That is the
        sole input — no budget_config.json, no subscription-name guessing
        when ``environment`` is set. The name keyword fallback only runs
        when neither ``environment`` nor a previously stored ``env_label``
        is available, e.g. live Azure responses that don't carry admin
        metadata.
        """
        explicit_environment = str(row.get("environment") or "").strip()
        if explicit_environment:
            return AmortizedCostSyncService.normalize_environment(explicit_environment)

        el = row.get("env_label", "")
        if el in ("Prod", "Non-Prod"):
            return el

        # Last-resort: best-effort guess from the subscription name. Only
        # reached when admin metadata is missing entirely.
        return AmortizedCostSyncService.normalize_environment(row.get("subscription_name") or "")
