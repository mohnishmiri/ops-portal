"""
Amortized Cost Sync Service — DB-backed cache for Azure Cost API data.

The sync path:
1. Queries Azure Cost Management for the monitored subscriptions.
2. Normalizes the grouped Azure response into ``amortized_cost_records``.
3. Rebuilds the amortized dashboard payloads from PostgreSQL.

The DB acts as a durable cache that survives Redis eviction and pod restarts.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from calendar import monthrange
from collections import defaultdict
from datetime import date, datetime, timedelta
from functools import lru_cache
from pathlib import Path
from time import perf_counter

import structlog
from sqlalchemy import case, delete, distinct, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.admin_config import get_effective_cache_ttl_seconds
from app.core.db_cache import cache_manager
from app.core.subscription_resolver import get_monitored_subscription_ids
from app.models.database import (
    AdminSubscription,
    AmortizedCostDailySummary,
    AmortizedCostMonthlySummary,
    AmortizedCostRecord,
    AmortizedCostSyncStatus,
    AmortizedCostWeeklySummary,
)
from app.services.cost_service import CostService

logger = structlog.get_logger(__name__)

# Data older than this many hours triggers an automatic re-sync.
# Azure Cost Management provides near real-time amortized cost data,
# so we sync frequently to keep the dashboard current.
STALE_HOURS = 4
RUNNING_SYNC_TIMEOUT_MINUTES = 180


class AmortizedCostSyncService:
    """Syncs amortized cost data from Azure Cost Management into PostgreSQL."""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db
        self._cost_service = CostService(db)

    # ── Staleness check ───────────────────────────────────────────────

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
        asyncio.create_task(cls._run_background_sync(months=months, triggered_by=triggered_by))

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

    async def _load_rows_from_azure_api(self, months: int) -> list[dict]:
        """Load amortized cost rows from the Azure Cost Management Query API."""
        monitored_subscription_ids = await get_monitored_subscription_ids()
        if not monitored_subscription_ids:
            logger.info("amortized_cost_sync_skipped_no_monitored_subscriptions")
            return []

        result = await self._db.execute(
            select(
                AdminSubscription.subscription_id,
                AdminSubscription.subscription_name,
                AdminSubscription.environment,
            ).where(
                AdminSubscription.subscription_id.in_(monitored_subscription_ids),
            )
        )
        subscription_metadata = {
            subscription_id: {
                "subscription_name": subscription_name,
                "environment": environment,
            }
            for subscription_id, subscription_name, environment in result.all()
        }

        end_date = date.today()
        start_date = self._get_rolling_start_date(end_date, months)

        normalized_rows: list[dict] = []
        query_failures: list[str] = []

        for subscription_id in monitored_subscription_ids:
            scope = f"/subscriptions/{subscription_id}"
            try:
                metadata = subscription_metadata.get(subscription_id, {})
                subscription_name = metadata.get("subscription_name") or subscription_id
                environment = metadata.get("environment")

                rows = await self._cost_service.query_amortized_cost_rows(scope, start_date, end_date)
                for row in rows:
                    row["subscription_name"] = str(row.get("subscription_name") or subscription_name).strip()
                    row["subscription_id"] = str(row.get("subscription_id") or subscription_id).strip()
                    row["resource_name"] = self._normalize_resource_name(
                        row.get("resource_name"),
                        meter_name=row.get("meter_name"),
                        meter_category=row.get("meter_category"),
                        resource_group=row.get("resource_group"),
                    )
                    row["env_label"] = self._derive_env_label(
                        {
                            "env_label": row.get("env_label"),
                            "environment": environment,
                            "subscription_name": subscription_name,
                            "subscription_id": subscription_id,
                        }
                    )
                    normalized_rows.append(row)

                logger.info(
                    "amortized_cost_subscription_loaded",
                    subscription_id=subscription_id,
                    normalized_count=len(normalized_rows),
                )
            except Exception as exc:
                query_failures.append(f"{subscription_id}: {str(exc)[:200]}")
                logger.error(
                    "amortized_cost_subscription_load_failed",
                    subscription_id=subscription_id,
                    error=str(exc)[:300],
                )

        if not normalized_rows and query_failures:
            raise RuntimeError(
                "Azure amortized sync failed for all monitored subscriptions: " + " | ".join(query_failures[:3])
            )

        return normalized_rows

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

        for fallback in (meter_name, meter_category, resource_group):
            value = str(fallback or "").strip()
            if value:
                return value

        return "Unknown"

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

    # ── Full sync (azure api → DB) ───────────────────────────────────

    async def full_sync(
        self,
        months: int = 2,
        triggered_by: str = "manual",
    ) -> dict:
        """Download Azure Cost API data, normalize it, and bulk-insert into PostgreSQL.

        The sync is idempotent — existing records are deleted before a
        fresh insert so there is no risk of duplicates.
        """
        sync_record = AmortizedCostSyncStatus(
            sync_type="full",
            status="running",
            started_at=datetime.utcnow(),
            triggered_by=triggered_by,
        )
        self._db.add(sync_record)
        await self._db.commit()
        started_at = sync_record.started_at or datetime.utcnow()

        try:
            rows = await self._load_rows_from_azure_api(months)

            # Always replace the current amortized cache so the dashboard
            # cannot continue serving stale rows after an empty sync.
            await self._db.execute(delete(AmortizedCostRecord))

            if not rows:
                sync_record.status = "completed"
                sync_record.completed_at = datetime.utcnow()
                sync_record.months_synced = months
                sync_record.rows_synced = 0
                sync_record.total_cost = 0.0
                await self._db.commit()
                await cache_manager.invalidate("pagecache:amortized:*")
                duration_seconds = max(
                    0.0,
                    (sync_record.completed_at - started_at).total_seconds(),
                )
                return {
                    "status": "completed",
                    "months_synced": months,
                    "rows_synced": 0,
                    "total_cost": 0.0,
                    "started_at": started_at.isoformat(),
                    "completed_at": sync_record.completed_at.isoformat(),
                    "duration_seconds": round(duration_seconds, 2),
                }

            now = datetime.utcnow()
            batch: list[AmortizedCostRecord] = []
            total_cost = 0.0

            for r in rows:
                rec = AmortizedCostRecord(
                    cost_date=r.get("date", ""),
                    cost_amount=r.get("cost", 0.0),
                    meter_category=r.get("meter_category", ""),
                    meter_subcategory=r.get("meter_subcategory", ""),
                    meter_name=r.get("meter_name", ""),
                    resource_group=r.get("resource_group", ""),
                    resource_name=r.get("resource_name", ""),
                    resource_type=r.get("resource_type", ""),
                    resource_location=r.get("resource_location", ""),
                    subscription_name=r.get("subscription_name", ""),
                    subscription_id=r.get("subscription_id", ""),
                    service_name=r.get("service_name", ""),
                    charge_type=r.get("charge_type", ""),
                    pricing_model=r.get("pricing_model", ""),
                    publisher_type=r.get("publisher_type", ""),
                    frequency=r.get("frequency", ""),
                    currency=r.get("currency", "USD"),
                    env_label=self._derive_env_label(r),
                    synced_at=now,
                )
                batch.append(rec)
                total_cost += r.get("cost", 0.0)

                # Flush in batches of 5 000 to limit memory pressure
                if len(batch) >= 5000:
                    self._db.add_all(batch)
                    await self._db.flush()
                    batch = []

            if batch:
                self._db.add_all(batch)

            await self._db.commit()

            # ── Record success ────────────────────────────────────────
            sync_record.status = "completed"
            sync_record.completed_at = datetime.utcnow()
            sync_record.months_synced = months
            sync_record.rows_synced = len(rows)
            sync_record.total_cost = round(total_cost, 2)
            await self._db.commit()
            duration_seconds = max(
                0.0,
                (sync_record.completed_at - started_at).total_seconds(),
            )

            logger.info(
                "amortized_cost_sync_completed",
                months=months,
                rows=len(rows),
                total_cost=round(total_cost, 2),
                triggered_by=triggered_by,
            )

            await cache_manager.invalidate("pagecache:amortized:*")

            # ── Aggregate into time-series summaries ───────────────────
            try:
                await self._aggregate_cost_summaries()
            except Exception as agg_exc:
                logger.warning(
                    "amortized_cost_aggregation_failed",
                    error=str(agg_exc)[:500],
                )
                # Aggregation failure is non-fatal; sync already succeeded

            return {
                "status": "completed",
                "months_synced": months,
                "rows_synced": len(rows),
                "total_cost": round(total_cost, 2),
                "started_at": started_at.isoformat(),
                "completed_at": sync_record.completed_at.isoformat(),
                "duration_seconds": round(duration_seconds, 2),
            }

        except Exception as exc:
            sync_record.status = "failed"
            sync_record.completed_at = datetime.utcnow()
            sync_record.error_message = str(exc)[:2000]
            await self._db.commit()
            duration_seconds = max(
                0.0,
                (sync_record.completed_at - started_at).total_seconds(),
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
                "completed_at": sync_record.completed_at.isoformat(),
                "duration_seconds": round(duration_seconds, 2),
            }

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
                        (AmortizedCostRecord.env_label == "PROD", AmortizedCostRecord.cost_amount),
                        else_=0.0,
                    )
                ).label("prod_cost"),
                func.sum(
                    case(
                        (AmortizedCostRecord.env_label != "PROD", AmortizedCostRecord.cost_amount),
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
        # Aggregate daily summaries into weeks (ISO week format)
        weekly_result = await self._db.execute(
            select(
                AmortizedCostDailySummary.cost_date,
            )
            .distinct()
            .order_by(AmortizedCostDailySummary.cost_date)
        )
        daily_dates = [str(row[0]) for row in weekly_result.all()]

        weeks = defaultdict(
            lambda: {
                "total_cost": 0.0,
                "production_cost": 0.0,
                "non_production_cost": 0.0,
                "service_count": set(),
                "resource_count": set(),
            }
        )

        for daily_date in daily_dates:
            # Calculate ISO week start (Monday)
            try:
                from datetime import datetime as dt

                d = dt.strptime(daily_date, "%Y-%m-%d")
                week_start = (d - timedelta(days=d.weekday())).strftime("%Y-%m-%d")
                weeks[week_start]["total_cost"] += (
                    await self._db.scalar(
                        select(func.sum(AmortizedCostDailySummary.total_cost)).where(
                            AmortizedCostDailySummary.cost_date == daily_date
                        )
                    )
                    or 0.0
                )
                weeks[week_start]["production_cost"] += (
                    await self._db.scalar(
                        select(func.sum(AmortizedCostDailySummary.production_cost)).where(
                            AmortizedCostDailySummary.cost_date == daily_date
                        )
                    )
                    or 0.0
                )
                weeks[week_start]["non_production_cost"] += (
                    await self._db.scalar(
                        select(func.sum(AmortizedCostDailySummary.non_production_cost)).where(
                            AmortizedCostDailySummary.cost_date == daily_date
                        )
                    )
                    or 0.0
                )
            except Exception as e:
                logger.warning("week_start_calculation_failed", date=daily_date, error=str(e))

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
        monthly_result = await self._db.execute(
            select(
                func.substr(AmortizedCostDailySummary.cost_date, 1, 7).label("month_year"),
                func.sum(AmortizedCostDailySummary.total_cost).label("total_cost"),
                func.sum(AmortizedCostDailySummary.production_cost).label("prod_cost"),
                func.sum(AmortizedCostDailySummary.non_production_cost).label("nonprod_cost"),
            ).group_by(func.substr(AmortizedCostDailySummary.cost_date, 1, 7))
        )
        monthly_rows = monthly_result.all()

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

    # ── Analytics from DB ─────────────────────────────────────────────

    async def get_amortized_cost_data(
        self,
        env: str = "ALL",
        months: int = 2,
    ) -> dict:
        """Build the existing amortized analytics payload,
        but sourced entirely from the PostgreSQL cache."""
        started = perf_counter()
        cache_key = self._summary_cache_key(env, months)
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

        rows = await self._load_rows_from_db(env, months)
        payload = self._build_analytics(rows, env, months=months, as_of=date.today())
        ttl = await get_effective_cache_ttl_seconds(self._db)
        await cache_manager.set_cached(cache_key, json.dumps(payload, default=str), ttl=ttl)
        logger.info(
            "amortized_summary_served",
            source="database",
            environment=env,
            months=months,
            row_count=len(rows),
            elapsed_ms=round((perf_counter() - started) * 1000, 2),
        )
        return payload

    async def get_resource_drilldown(
        self,
        env: str = "ALL",
        months: int = 2,
        resource_group: str | None = None,
        meter_category: str | None = None,
        subscription: str | None = None,
    ) -> dict:
        """Resource-level drill-down from DB-cached amortized cost rows."""
        started = perf_counter()
        cache_key = self._drilldown_cache_key(
            env,
            months,
            resource_group=resource_group,
            meter_category=meter_category,
            subscription=subscription,
        )
        cached = await cache_manager.get_cached(cache_key)
        if cached:
            try:
                payload = json.loads(cached)
                logger.info(
                    "amortized_drilldown_served",
                    source="cache",
                    environment=env,
                    months=months,
                    resource_group=resource_group,
                    meter_category=meter_category,
                    subscription=subscription,
                    elapsed_ms=round((perf_counter() - started) * 1000, 2),
                )
                return payload
            except (json.JSONDecodeError, TypeError):
                pass

        rows = await self._load_rows_from_db(env, months)

        filtered = rows
        if resource_group:
            rg_lower = resource_group.lower()
            filtered = [r for r in filtered if r["resource_group"].lower() == rg_lower]
        if meter_category:
            mc_lower = meter_category.lower()
            filtered = [r for r in filtered if r["meter_category"].lower() == mc_lower]
        if subscription:
            sub_lower = subscription.lower()
            filtered = [
                r for r in filtered if sub_lower in (r["subscription_name"].lower(), r["subscription_id"].lower())
            ]

        if not filtered:
            return {
                "filters": {
                    "environment": env,
                    "resource_group": resource_group,
                    "meter_category": meter_category,
                    "subscription": subscription,
                },
                "total_cost": 0,
                "row_count": 0,
                "resources": [],
                "daily_trend": [],
                "generated_at": datetime.utcnow().isoformat(),
            }

        total_cost = sum(r["cost"] for r in filtered)

        # Aggregate by resource
        res_agg: dict[str, dict] = {}
        for r in filtered:
            rname = r["resource_name"] or "Unknown"
            key = f"{rname}|{r['resource_group']}"
            if key not in res_agg:
                res_agg[key] = {
                    "resource_name": rname,
                    "resource_group": r["resource_group"],
                    "resource_type": r["resource_type"],
                    "meter_category": r["meter_category"],
                    "location": r["resource_location"],
                    "subscription": r["subscription_name"] or r["subscription_id"],
                    "cost": 0.0,
                    "days": set(),
                }
            res_agg[key]["cost"] += r["cost"]
            if r["date"]:
                res_agg[key]["days"].add(r["date"])

        resources = sorted(res_agg.values(), key=lambda x: x["cost"], reverse=True)[:100]
        for res in resources:
            res["cost"] = round(res["cost"], 2)
            res["active_days"] = len(res.pop("days"))

        daily: dict[str, float] = defaultdict(float)
        for r in filtered:
            if r["date"]:
                daily[r["date"]] += r["cost"]
        daily_trend = [{"date": d, "cost": round(c, 2)} for d, c in sorted(daily.items())]

        payload = {
            "filters": {
                "environment": env,
                "resource_group": resource_group,
                "meter_category": meter_category,
                "subscription": subscription,
            },
            "total_cost": round(total_cost, 2),
            "row_count": len(filtered),
            "resources": resources,
            "daily_trend": daily_trend,
            "generated_at": datetime.utcnow().isoformat(),
        }
        ttl = await get_effective_cache_ttl_seconds(self._db)
        await cache_manager.set_cached(cache_key, json.dumps(payload, default=str), ttl=ttl)
        logger.info(
            "amortized_drilldown_served",
            source="database",
            environment=env,
            months=months,
            resource_group=resource_group,
            meter_category=meter_category,
            subscription=subscription,
            row_count=len(filtered),
            elapsed_ms=round((perf_counter() - started) * 1000, 2),
        )
        return payload

    # ── Sync-status endpoint helper ───────────────────────────────────

    async def get_sync_status(self) -> dict:
        """Return latest sync status for the dashboard header."""
        monitored_subscription_ids = await get_monitored_subscription_ids()
        result = await self._db.execute(
            select(AmortizedCostSyncStatus).order_by(AmortizedCostSyncStatus.started_at.desc()).limit(1)
        )
        rec = result.scalars().first()
        if not rec:
            return {
                "last_sync": None,
                "started_at": None,
                "status": None,
                "monitored_subscription_ids": monitored_subscription_ids,
                "monitored_subscription_count": len(monitored_subscription_ids),
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
            "monitored_subscription_ids": monitored_subscription_ids,
            "monitored_subscription_count": len(monitored_subscription_ids),
        }

    # ── Private helpers ───────────────────────────────────────────────

    def _summary_cache_key(self, env: str, months: int) -> str:
        return f"pagecache:amortized:summary:{env.upper()}:{months}"

    def _drilldown_cache_key(
        self,
        env: str,
        months: int,
        *,
        resource_group: str | None,
        meter_category: str | None,
        subscription: str | None,
    ) -> str:
        raw = json.dumps(
            {
                "env": env.upper(),
                "months": months,
                "resource_group": resource_group,
                "meter_category": meter_category,
                "subscription": subscription,
            },
            sort_keys=True,
        )
        digest = hashlib.md5(raw.encode()).hexdigest()[:16]
        return f"pagecache:amortized:drilldown:{digest}"

    async def _load_rows_from_db(self, env: str, months: int) -> list[dict]:
        """Load amortized cost rows from PostgreSQL, optionally filtered by env."""
        env = env.upper()

        # Use exact rolling calendar months anchored to today.
        start_date = self._get_rolling_start_date(date.today(), months)

        # cost_date is stored as String(10) 'YYYY-MM-DD', so compare with
        # an ISO-formatted string — not a date object — to avoid a
        # PostgreSQL "operator does not exist: character varying >= date" error.
        stmt = select(AmortizedCostRecord).where(AmortizedCostRecord.cost_date >= start_date.isoformat())

        if env == "PROD":
            stmt = stmt.where(AmortizedCostRecord.env_label == "Prod")
        elif env == "NONPROD":
            stmt = stmt.where(AmortizedCostRecord.env_label == "Non-Prod")
        # else ALL — no filter

        result = await self._db.execute(stmt)
        records = result.scalars().all()

        return [
            {
                "date": rec.cost_date,
                "cost": rec.cost_amount,
                "meter_category": rec.meter_category or "",
                "meter_subcategory": rec.meter_subcategory or "",
                "meter_name": rec.meter_name or "",
                "resource_group": rec.resource_group or "",
                "resource_name": rec.resource_name or "",
                "resource_type": rec.resource_type or "",
                "resource_location": rec.resource_location or "",
                "subscription_name": rec.subscription_name or "",
                "subscription_id": rec.subscription_id or "",
                "service_name": rec.service_name or "",
                "charge_type": rec.charge_type or "",
                "pricing_model": rec.pricing_model or "",
                "publisher_type": rec.publisher_type or "",
                "frequency": rec.frequency or "",
                "currency": rec.currency or "USD",
                "env_label": rec.env_label or "Unknown",
            }
            for rec in records
        ]

    # ── Analytics builder (legacy amortized payload shape) ────────────

    @staticmethod
    @lru_cache(maxsize=1)
    def _load_non_prod_subscription_ids() -> set[str]:
        """Load non-prod subscription IDs from the shared budget config."""
        cfg_path = Path(__file__).resolve().parents[2] / "config" / "budget_config.json"
        if not cfg_path.exists():
            return set()

        try:
            with cfg_path.open(encoding="utf-8") as handle:
                cfg = json.load(handle)
        except (OSError, json.JSONDecodeError):
            logger.warning("amortized_budget_config_load_failed", path=str(cfg_path))
            return set()

        non_prod_ids: set[str] = set()
        for app in cfg.get("applications", []):
            for subscription_id in app.get("non_prod_subscription_ids", []):
                if subscription_id:
                    non_prod_ids.add(str(subscription_id).strip())
        return non_prod_ids

    @staticmethod
    def _derive_env_label(row: dict) -> str:
        """Derive Prod/Non-Prod from explicit environment metadata first."""
        el = row.get("env_label", "")
        if el in ("Prod", "Non-Prod"):
            return el

        explicit_environment = str(row.get("environment") or "").strip().lower()
        if explicit_environment:
            if explicit_environment in {"prod", "production"}:
                return "Prod"
            return "Non-Prod"

        subscription_id = str(row.get("subscription_id") or "").strip()
        if subscription_id and subscription_id in AmortizedCostSyncService._load_non_prod_subscription_ids():
            return "Non-Prod"

        # Fallback: derive from subscription name
        sub = (row.get("subscription_name") or subscription_id or "").lower()
        non_prod_keywords = (
            "nprd",
            "nprod",
            "nonprod",
            "non-prod",
            "non_prod",
            "dev",
            "test",
            "uat",
            "stg",
            "stage",
            "staging",
            "perf",
            "sandbox",
        )
        if any(kw in sub for kw in non_prod_keywords):
            return "Non-Prod"

        prod_keywords = ("prod", "prd", "production")
        if any(kw in sub for kw in prod_keywords):
            return "Prod"
        return "Non-Prod"

    @staticmethod
    def _build_analytics(
        rows: list[dict],
        env: str,
        *,
        months: int | None = None,
        as_of: date | None = None,
    ) -> dict:
        """Build a rich analytics payload from DB rows.

        Returns the existing amortized dashboard JSON shape
        so the frontend needs zero changes.
        """
        requested_end = as_of or date.today()
        requested_start = AmortizedCostSyncService._get_rolling_start_date(requested_end, months) if months else None

        if not rows:
            return {
                "environment": env,
                "total_cost": 0,
                "row_count": 0,
                "date_range": {
                    "start": requested_start.isoformat() if requested_start else "",
                    "end": requested_end.isoformat() if requested_start else "",
                },
                "daily_trend": [],
                "service_breakdown": [],
                "resource_group_breakdown": [],
                "resource_type_breakdown": [],
                "location_breakdown": [],
                "subscription_breakdown": [],
                "top_resources": [],
                "monthly_pivot": {},
                "env_comparison": {},
                "charge_type_breakdown": [],
                "pricing_model_breakdown": [],
                "daily_by_service": [],
                "top_service_names": [],
                "source_date_range": {"start": "", "end": ""},
                "latest_available_date": None,
                "has_pending_source_data": False,
                "generated_at": datetime.utcnow().isoformat(),
            }

        total_cost = sum(r["cost"] for r in rows)
        dates = sorted({r["date"] for r in rows if r["date"]})
        source_date_start = dates[0] if dates else ""
        source_date_end = dates[-1] if dates else ""
        if requested_start:
            date_start = requested_start.isoformat()
            date_end = requested_end.isoformat()
        else:
            date_start = source_date_start
            date_end = source_date_end

        latest_available_date = source_date_end or None
        has_pending_source_data = bool(
            requested_start and latest_available_date and latest_available_date < requested_end.isoformat()
        )

        # ── 1. Daily trend ────────────────────────────────────────────
        daily: dict[str, float] = defaultdict(float)
        daily_prod: dict[str, float] = defaultdict(float)
        daily_nonprod: dict[str, float] = defaultdict(float)
        for r in rows:
            d = r["date"]
            if not d:
                continue
            daily[d] += r["cost"]
            derived_label = AmortizedCostSyncService._derive_env_label(r)
            if derived_label == "Prod":
                daily_prod[d] += r["cost"]
            else:
                daily_nonprod[d] += r["cost"]

        trend_dates: list[str]
        if requested_start:
            cursor = requested_start
            trend_dates = []
            while cursor <= requested_end:
                trend_dates.append(cursor.isoformat())
                cursor += timedelta(days=1)
        else:
            trend_dates = sorted(daily.keys())

        daily_trend = [
            {
                "date": d,
                "cost": round(daily.get(d, 0.0), 2),
                "prod": round(daily_prod.get(d, 0), 2),
                "non_prod": round(daily_nonprod.get(d, 0), 2),
            }
            for d in trend_dates
        ]

        # ── 2. Service (MeterCategory) breakdown ─────────────────────
        svc_cost: dict[str, float] = defaultdict(float)
        for r in rows:
            svc_cost[r["meter_category"] or "Unknown"] += r["cost"]
        service_breakdown = sorted(
            [
                {
                    "name": k,
                    "cost": round(v, 2),
                    "pct": round(v / total_cost * 100, 2) if total_cost else 0,
                }
                for k, v in svc_cost.items()
            ],
            key=lambda x: x["cost"],
            reverse=True,
        )

        # ── 3. Resource Group breakdown ───────────────────────────────
        rg_cost: dict[str, float] = defaultdict(float)
        for r in rows:
            rg_cost[r["resource_group"] or "Unknown"] += r["cost"]
        rg_breakdown = sorted(
            [
                {
                    "name": k,
                    "cost": round(v, 2),
                    "pct": round(v / total_cost * 100, 2) if total_cost else 0,
                }
                for k, v in rg_cost.items()
            ],
            key=lambda x: x["cost"],
            reverse=True,
        )

        # ── 4. Resource Type breakdown ────────────────────────────────
        rt_cost: dict[str, float] = defaultdict(float)
        for r in rows:
            rt_cost[r["resource_type"] or "Unknown"] += r["cost"]
        rt_breakdown = sorted(
            [
                {
                    "name": k,
                    "cost": round(v, 2),
                    "pct": round(v / total_cost * 100, 2) if total_cost else 0,
                }
                for k, v in rt_cost.items()
            ],
            key=lambda x: x["cost"],
            reverse=True,
        )

        # ── 5. Location breakdown ─────────────────────────────────────
        loc_cost: dict[str, float] = defaultdict(float)
        for r in rows:
            loc_cost[r["resource_location"] or "Unknown"] += r["cost"]
        loc_breakdown = sorted(
            [
                {
                    "name": k,
                    "cost": round(v, 2),
                    "pct": round(v / total_cost * 100, 2) if total_cost else 0,
                }
                for k, v in loc_cost.items()
            ],
            key=lambda x: x["cost"],
            reverse=True,
        )

        # ── 6. Subscription breakdown ─────────────────────────────────
        sub_cost: dict[str, float] = defaultdict(float)
        for r in rows:
            label = r["subscription_name"] or r["subscription_id"] or "Unknown"
            sub_cost[label] += r["cost"]
        sub_breakdown = sorted(
            [
                {
                    "name": k,
                    "cost": round(v, 2),
                    "pct": round(v / total_cost * 100, 2) if total_cost else 0,
                }
                for k, v in sub_cost.items()
            ],
            key=lambda x: x["cost"],
            reverse=True,
        )

        # ── 7. Top resources by cost ──────────────────────────────────
        res_cost: dict[str, dict] = {}
        for r in rows:
            rname = r["resource_name"] or "Unknown"
            key = f"{rname}|{r['resource_group']}|{r['meter_category']}"
            if key not in res_cost:
                res_cost[key] = {
                    "resource_name": rname,
                    "resource_group": r["resource_group"],
                    "resource_type": r["resource_type"],
                    "meter_category": r["meter_category"],
                    "location": r["resource_location"],
                    "subscription": r["subscription_name"] or r["subscription_id"],
                    "cost": 0.0,
                }
            res_cost[key]["cost"] += r["cost"]
        top_resources = sorted(res_cost.values(), key=lambda x: x["cost"], reverse=True)[:50]
        for tr in top_resources:
            tr["cost"] = round(tr["cost"], 2)

        # ── 8. Monthly pivot (service x month) ───────────────────────
        month_svc: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
        for r in rows:
            if not r["date"]:
                continue
            mk = r["date"][:7]
            month_svc[mk][r["meter_category"] or "Unknown"] += r["cost"]

        all_months = sorted(month_svc.keys())
        all_svcs_set: set[str] = set()
        for md in month_svc.values():
            all_svcs_set.update(md.keys())

        pivot_services: list[dict] = []
        for svc in sorted(all_svcs_set):
            monthly_costs: dict[str, float] = {}
            svc_total = 0.0
            for mk in all_months:
                c = round(month_svc[mk].get(svc, 0), 2)
                monthly_costs[mk] = c
                svc_total += c
            pivot_services.append(
                {
                    "service_name": svc,
                    "monthly_costs": monthly_costs,
                    "total": round(svc_total, 2),
                }
            )
        pivot_services.sort(key=lambda x: x["total"], reverse=True)

        monthly_totals: dict[str, float] = {}
        grand_total = 0.0
        for mk in all_months:
            mt = round(sum(month_svc[mk].values()), 2)
            monthly_totals[mk] = mt
            grand_total += mt

        month_labels: dict[str, str] = {}
        for mk in all_months:
            parts = mk.split("-")
            month_labels[mk] = date(int(parts[0]), int(parts[1]), 1).strftime("%Y %b")

        monthly_pivot = {
            "months": all_months,
            "month_labels": month_labels,
            "services": pivot_services,
            "monthly_totals": monthly_totals,
            "grand_total": round(grand_total, 2),
        }

        # ── 9. Env comparison (Prod vs Non-Prod) ─────────────────────
        env_totals: dict[str, float] = defaultdict(float)
        env_by_month: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
        for r in rows:
            el = AmortizedCostSyncService._derive_env_label(r)
            env_totals[el] += r["cost"]
            if r["date"]:
                env_by_month[r["date"][:7]][el] += r["cost"]

        env_comparison = {
            "totals": {k: round(v, 2) for k, v in env_totals.items()},
            "monthly": {mk: {k: round(v, 2) for k, v in envs.items()} for mk, envs in sorted(env_by_month.items())},
        }

        # ── 10. Charge type breakdown ─────────────────────────────────
        ct_cost: dict[str, float] = defaultdict(float)
        for r in rows:
            ct_cost[r["charge_type"] or "Usage"] += r["cost"]
        charge_type_breakdown = sorted(
            [{"name": k, "cost": round(v, 2)} for k, v in ct_cost.items()],
            key=lambda x: x["cost"],
            reverse=True,
        )

        # ── 11. Pricing model breakdown ───────────────────────────────
        pm_cost: dict[str, float] = defaultdict(float)
        for r in rows:
            pm_cost[r["pricing_model"] or "Unknown"] += r["cost"]
        pricing_model_breakdown = sorted(
            [{"name": k, "cost": round(v, 2)} for k, v in pm_cost.items()],
            key=lambda x: x["cost"],
            reverse=True,
        )

        # ── 12. Daily cost by top services (for stacked area) ────────
        top_svc_names = [str(s["name"]) for s in service_breakdown[:8]]
        daily_by_svc: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
        for r in rows:
            if not r["date"]:
                continue
            svc = r["meter_category"] or "Unknown"
            if svc not in top_svc_names:
                svc = "Other"
            daily_by_svc[r["date"]][svc] += r["cost"]

        daily_by_service = []
        service_dates = trend_dates if requested_start else sorted(daily_by_svc.keys())
        for d in service_dates:
            entry: dict[str, str | float] = {"date": d}
            for svc_name in top_svc_names + ["Other"]:
                entry[svc_name] = round(daily_by_svc[d].get(svc_name, 0), 2)
            daily_by_service.append(entry)

        return {
            "environment": env,
            "total_cost": round(total_cost, 2),
            "row_count": len(rows),
            "date_range": {"start": date_start, "end": date_end},
            "daily_trend": daily_trend,
            "service_breakdown": service_breakdown,
            "resource_group_breakdown": rg_breakdown[:30],
            "resource_type_breakdown": rt_breakdown[:30],
            "location_breakdown": loc_breakdown,
            "subscription_breakdown": sub_breakdown,
            "top_resources": top_resources,
            "monthly_pivot": monthly_pivot,
            "env_comparison": env_comparison,
            "charge_type_breakdown": charge_type_breakdown,
            "pricing_model_breakdown": pricing_model_breakdown,
            "daily_by_service": daily_by_service,
            "top_service_names": top_svc_names,
            "source_date_range": {"start": source_date_start, "end": source_date_end},
            "latest_available_date": latest_available_date,
            "has_pending_source_data": has_pending_source_data,
            "generated_at": datetime.utcnow().isoformat(),
        }
