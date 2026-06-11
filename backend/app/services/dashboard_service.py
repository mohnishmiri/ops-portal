"""
Dashboard Service — pre-aggregated dashboard data.

Combines cost and optimization data for Leadership, Ops, and Admin views.
Falls back to realistic demo data in development mode when Azure APIs
are unreachable so the UI can be exercised locally.
"""

import asyncio
import traceback
from datetime import date, datetime, timedelta
from decimal import Decimal

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.azure_auth import get_azure_credential
from app.core.config import settings
from app.core.db_cache import cache_manager
from app.core.subscription_scope import get_scoped_subscription_ids
from app.models.cost import (
    CostByGroup,
    CostDataPoint,
    CostTrendDirection,
    GroupByDimension,
    KPIMetric,
    LeadershipDashboard,
    MonthlyCostPoint,
)
from app.services.cost_service import CostService
from app.services.optimization_service import OptimizationService

logger = structlog.get_logger(__name__)


# ── Demo / mock data generators ────────────────────────────────────────


def _demo_leadership_dashboard() -> LeadershipDashboard:
    """Return realistic sample data for local development."""
    import random

    today = date.today()
    trend_start = today - timedelta(days=15)  # Last 16 days

    # Generate a plausible daily cost trend
    data_points: list[CostDataPoint] = []
    day = trend_start
    while day <= today:
        data_points.append(
            CostDataPoint(
                date=day,
                cost=Decimal(str(round(random.uniform(1800, 2600), 2))),
                currency="USD",
                group_value="demo-subscription",
                group_dimension=GroupByDimension.SUBSCRIPTION,
            )
        )
        day += timedelta(days=1)

    total_spend = sum(dp.cost for dp in data_points)

    kpis = [
        KPIMetric(
            name="Total Monthly Spend",
            value=total_spend,
            unit="USD",
            trend=CostTrendDirection.UP,
            change_pct=8.3,
            description="Current month Azure spend across all subscriptions",
        ),
        KPIMetric(
            name="Month-over-Month Change",
            value=8.3,
            unit="%",
            trend=CostTrendDirection.UP,
            change_pct=8.3,
            description="Cost change compared to previous month",
        ),
        KPIMetric(
            name="Total Savings Opportunities",
            value=Decimal("14250.00"),
            unit="USD/year",
            trend=CostTrendDirection.DOWN,
            change_pct=0.0,
            description="Estimated annual savings from all recommendations",
        ),
        KPIMetric(
            name="Active Recommendations",
            value=Decimal("17"),
            unit="count",
            trend=CostTrendDirection.STABLE,
            change_pct=0.0,
            description="Number of actionable cost optimization recommendations",
        ),
        KPIMetric(
            name="Subscriptions Monitored",
            value=Decimal("1"),
            unit="count",
            trend=CostTrendDirection.STABLE,
            change_pct=0.0,
            description="Number of Azure subscriptions under cost monitoring",
        ),
    ]

    top_spenders = [
        CostByGroup(
            group_dimension=GroupByDimension.SUBSCRIPTION,
            group_value="AKS Production",
            total_cost=Decimal("12450.00"),
            percentage_of_total=38.5,
            currency="USD",
        ),
        CostByGroup(
            group_dimension=GroupByDimension.SUBSCRIPTION,
            group_value="Data Platform",
            total_cost=Decimal("8920.00"),
            percentage_of_total=27.6,
            currency="USD",
        ),
        CostByGroup(
            group_dimension=GroupByDimension.SUBSCRIPTION,
            group_value="DevTest",
            total_cost=Decimal("5340.00"),
            percentage_of_total=16.5,
            currency="USD",
        ),
        CostByGroup(
            group_dimension=GroupByDimension.SUBSCRIPTION,
            group_value="Networking",
            total_cost=Decimal("3220.00"),
            percentage_of_total=10.0,
            currency="USD",
        ),
        CostByGroup(
            group_dimension=GroupByDimension.SUBSCRIPTION,
            group_value="Security",
            total_cost=Decimal("2400.00"),
            percentage_of_total=7.4,
            currency="USD",
        ),
    ]

    # Generate 6-month trend demo data
    six_month_trend: list[MonthlyCostPoint] = []
    for i in range(6, 0, -1):
        m = (today.month - i - 1) % 12 + 1
        y = today.year + (today.month - i - 1) // 12
        ym = f"{y}-{m:02d}"
        label = date(y, m, 1).strftime("%b %Y")
        np_val = Decimal(str(round(random.uniform(18000, 24000), 2)))
        pr_val = Decimal(str(round(random.uniform(25000, 35000), 2)))
        six_month_trend.append(
            MonthlyCostPoint(
                month=ym,
                month_label=label,
                total_cost=np_val + pr_val,
                non_prod_cost=np_val,
                prod_cost=pr_val,
                subscription_breakdown={"demo-nonprod": np_val, "demo-prod": pr_val},
            )
        )

    return LeadershipDashboard(
        kpis=kpis,
        cost_trend=data_points,
        top_spenders=top_spenders,
        six_month_trend=six_month_trend,
        savings_opportunities=Decimal("14250.00"),
        report_date=datetime.utcnow(),
    )


class DashboardService:
    """Service for constructing dashboard responses."""

    def __init__(self) -> None:
        self._cost_service = CostService()
        self._optimization_service = OptimizationService()

    async def get_leadership_dashboard(
        self,
        subscription_ids: list[str] | None = None,
        refresh: bool = False,
    ) -> LeadershipDashboard:
        """
        Leadership Dashboard — executive KPIs, trends, savings.

        Falls back to demo data when Azure APIs are unreachable
        and ENVIRONMENT=development.
        """
        try:
            return await self._leadership_dashboard_live(subscription_ids, refresh=refresh)
        except Exception as exc:
            if settings.ENVIRONMENT == "development":
                logger.warning(
                    "azure_api_unreachable_using_demo_data",
                    endpoint="leadership",
                    error=str(exc),
                    error_type=type(exc).__name__,
                    traceback=traceback.format_exc(),
                )
                return _demo_leadership_dashboard()
            raise

    async def _leadership_dashboard_live(
        self,
        subscription_ids: list[str] | None = None,
        refresh: bool = False,
    ) -> LeadershipDashboard:
        """Live implementation that queries Azure Cost Management.

        Only fetches cost data here.  Optimization data is fetched
        independently via GET /optimize/summary by the frontend so
        we avoid Azure API throttling from too many concurrent calls.
        """
        today = date.today()
        month_start = today.replace(day=1)
        trend_start = today - timedelta(days=15)  # Last 16 days
        prev_month_end = month_start - timedelta(days=1)
        prev_month_start = prev_month_end.replace(day=1)

        # 6-month trend: first day of 6 months ago to end of previous month
        six_months_ago = (month_start - timedelta(days=180)).replace(day=1)

        # When refresh=True, flush ALL cost:* cache entries so every
        # downstream query_costs call hits Azure afresh.
        if refresh:
            logger.info("leadership_live_step", step="cache_flush_start")
            await cache_manager.invalidate("cost:*")
            logger.info("leadership_live_step", step="cache_flush_done")

        logger.info("leadership_live_step", step="cost_queries_start")

        # Run cost queries in parallel
        current, previous, breakdown, six_month_raw = await asyncio.gather(
            self._cost_service.query_costs(
                subscription_ids=subscription_ids,
                start_date=trend_start,
                end_date=today,
            ),
            self._cost_service.query_costs(
                subscription_ids=subscription_ids,
                start_date=prev_month_start,
                end_date=prev_month_end,
            ),
            self._cost_service.get_cost_breakdown(
                subscription_ids=subscription_ids,
                dimension=GroupByDimension.SUBSCRIPTION,
                start_date=month_start,
                end_date=today,
            ),
            self._cost_service.query_costs(
                subscription_ids=subscription_ids,
                start_date=six_months_ago,
                end_date=prev_month_end,
            ),
        )

        logger.info(
            "leadership_live_step",
            step="cost_queries_done",
            current_cost=str(current.summary.total_cost),
            previous_cost=str(previous.summary.total_cost),
            spender_count=len(breakdown.breakdown),
        )

        # ── Build 6-month trend ───────────────────────────────────────
        monthly_buckets: dict[str, dict[str, Decimal]] = {}  # "YYYY-MM" → {sub_id: cost}
        for dp in six_month_raw.data_points:
            key = dp.date.strftime("%Y-%m")
            if key not in monthly_buckets:
                monthly_buckets[key] = {}
            sub = dp.group_value
            monthly_buckets[key][sub] = monthly_buckets[key].get(sub, Decimal("0")) + dp.cost

        # Determine non-prod subscription IDs from budget config
        non_prod_sub_ids: set[str] = set()
        try:
            import json as _json
            from pathlib import Path as _Path

            _cfg_path = _Path(__file__).resolve().parents[2] / "config" / "budget_config.json"
            if _cfg_path.exists():
                with open(_cfg_path, encoding="utf-8") as _f:
                    _cfg = _json.load(_f)
                for app in _cfg.get("applications", []):
                    for sid in app.get("non_prod_subscription_ids", []):
                        non_prod_sub_ids.add(sid)
        except Exception:
            pass  # fall back to treating all as prod

        six_month_trend: list[MonthlyCostPoint] = []
        for ym in sorted(monthly_buckets.keys()):
            parts = ym.split("-")
            label = date(int(parts[0]), int(parts[1]), 1).strftime("%b %Y")
            sub_costs = monthly_buckets[ym]
            np_cost = sum(v for k, v in sub_costs.items() if k in non_prod_sub_ids)
            pr_cost = sum(v for k, v in sub_costs.items() if k not in non_prod_sub_ids)
            six_month_trend.append(
                MonthlyCostPoint(
                    month=ym,
                    month_label=label,
                    total_cost=sum(sub_costs.values()),
                    non_prod_cost=np_cost,
                    prod_cost=pr_cost,
                    subscription_breakdown=sub_costs,
                )
            )

        current_total = current.summary.total_cost
        previous_total = previous.summary.total_cost
        change_pct = float((current_total - previous_total) / previous_total * 100) if previous_total else 0.0

        trend = (
            CostTrendDirection.UP
            if change_pct > 5
            else (CostTrendDirection.DOWN if change_pct < -5 else CostTrendDirection.STABLE)
        )

        kpis = [
            KPIMetric(
                name="Total Monthly Spend",
                value=current_total,
                unit="USD",
                trend=trend,
                change_pct=change_pct,
                description="Current month Azure spend across all subscriptions",
            ),
            KPIMetric(
                name="Month-over-Month Change",
                value=round(change_pct, 1),
                unit="%",
                trend=trend,
                change_pct=change_pct,
                description="Cost change compared to previous month",
            ),
            KPIMetric(
                name="Subscriptions Monitored",
                value=len(subscription_ids or await get_scoped_subscription_ids()),
                unit="count",
                trend=CostTrendDirection.STABLE,
                change_pct=0.0,
                description="Number of Azure subscriptions under cost monitoring",
            ),
        ]

        # ── Resolve subscription IDs → display names ─────────────────
        sub_name_map = await self._resolve_subscription_names(
            subscription_ids or await get_scoped_subscription_ids()
        )
        for spender in breakdown.breakdown:
            if spender.group_value in sub_name_map:
                spender.group_value = sub_name_map[spender.group_value]
        for dp in current.data_points:
            if dp.group_value in sub_name_map:
                dp.group_value = sub_name_map[dp.group_value]

        logger.info("leadership_live_step", step="returning_live_data")
        return LeadershipDashboard(
            kpis=kpis,
            cost_trend=current.data_points,
            top_spenders=breakdown.breakdown[:10],
            six_month_trend=six_month_trend,
            savings_opportunities=Decimal("0"),
            report_date=datetime.utcnow(),
        )

    async def _resolve_subscription_names(
        self,
        subscription_ids: list[str],
    ) -> dict[str, str]:
        """Resolve subscription IDs to display names via ARM REST API.

        Returns a mapping of {subscription_id: display_name}.
        Falls back to using the ID itself when resolution fails.
        """
        import urllib.error
        import urllib.request

        name_map: dict[str, str] = {}
        try:
            credential = get_azure_credential()
            token = credential.get_token("https://management.azure.com/.default")

            for sub_id in subscription_ids:
                try:
                    url = f"https://management.azure.com/subscriptions/{sub_id}?api-version=2022-12-01"
                    req = urllib.request.Request(
                        url,
                        headers={
                            "Authorization": f"Bearer {token.token}",
                            "Content-Type": "application/json",
                        },
                    )
                    # Bypass corporate proxy for Azure management API
                    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
                    with opener.open(req, timeout=10) as resp:
                        import json as _json

                        data = _json.loads(resp.read().decode())
                        display_name = data.get("displayName", sub_id)
                        name_map[sub_id] = display_name
                        logger.debug(
                            "subscription_name_resolved",
                            subscription_id=sub_id,
                            display_name=display_name,
                        )
                except Exception as e:
                    logger.warning(
                        "subscription_name_single_failed",
                        subscription_id=sub_id,
                        error=str(e),
                    )
        except Exception as e:
            logger.warning("subscription_name_resolution_failed", error=str(e))
        return name_map

    async def get_ops_dashboard(
        self,
        subscription_ids: list[str] | None = None,
    ) -> dict:
        """Operations dashboard with deep resource insights."""
        try:
            return await self._ops_dashboard_live(subscription_ids)
        except Exception:
            if settings.ENVIRONMENT == "development":
                logger.warning("azure_api_unreachable_using_demo_data", endpoint="ops")
                return {
                    "demo": True,
                    "message": "Demo ops data",
                    "generated_at": datetime.utcnow().isoformat(),
                }
            raise

    async def _ops_dashboard_live(
        self,
        subscription_ids: list[str] | None = None,
    ) -> dict:
        """Live ops dashboard implementation."""
        today = date.today()
        month_start = today.replace(day=1)
        prev_month_end = month_start - timedelta(days=1)
        prev_month_start = prev_month_end.replace(day=1)

        logger.info("ops_live_step", step="queries_start")

        # Run cost queries in parallel
        by_type, by_rg, by_location, daily_trend, prev_daily = await asyncio.gather(
            self._cost_service.get_cost_breakdown(
                subscription_ids=subscription_ids,
                dimension=GroupByDimension.RESOURCE_TYPE,
                start_date=month_start,
                end_date=today,
            ),
            self._cost_service.get_cost_breakdown(
                subscription_ids=subscription_ids,
                dimension=GroupByDimension.RESOURCE_GROUP,
                start_date=month_start,
                end_date=today,
            ),
            self._cost_service.get_cost_breakdown(
                subscription_ids=subscription_ids,
                dimension=GroupByDimension.LOCATION,
                start_date=month_start,
                end_date=today,
            ),
            self._cost_service.query_costs(
                subscription_ids=subscription_ids,
                start_date=month_start,
                end_date=today,
            ),
            self._cost_service.query_costs(
                subscription_ids=subscription_ids,
                start_date=prev_month_start,
                end_date=prev_month_end,
            ),
        )

        logger.info("ops_live_step", step="queries_done")

        # ── Daily spend analysis (current month) ─────────────────────
        daily_map: dict[str, Decimal] = {}
        for dp in daily_trend.data_points:
            key = dp.date.isoformat()
            daily_map[key] = daily_map.get(key, Decimal("0")) + dp.cost
        daily_spend = [{"date": k, "cost": str(v)} for k, v in sorted(daily_map.items())]

        # Compute avg & detect anomalies (>1.5x average)
        if daily_map:
            avg_daily = sum(daily_map.values()) / len(daily_map)
            anomalies = [
                {"date": k, "cost": str(v), "avg": str(round(avg_daily, 2))}
                for k, v in sorted(daily_map.items())
                if v > avg_daily * Decimal("1.5")
            ]
        else:
            avg_daily = Decimal("0")
            anomalies = []

        # ── Previous month daily for comparison ──────────────────────
        prev_daily_map: dict[str, Decimal] = {}
        for dp in prev_daily.data_points:
            key = dp.date.isoformat()
            prev_daily_map[key] = prev_daily_map.get(key, Decimal("0")) + dp.cost
        prev_avg_daily = sum(prev_daily_map.values()) / len(prev_daily_map) if prev_daily_map else Decimal("0")

        # ── Subscription breakdown ───────────────────────────────────
        sub_map: dict[str, Decimal] = {}
        for dp in daily_trend.data_points:
            sub_map[dp.group_value] = sub_map.get(dp.group_value, Decimal("0")) + dp.cost
        subscription_costs = [
            {"subscription_id": sid, "cost": str(c)}
            for sid, c in sorted(sub_map.items(), key=lambda x: x[1], reverse=True)
        ]

        return {
            "cost_by_resource_type": by_type.model_dump(),
            "cost_by_resource_group": by_rg.model_dump(),
            "cost_by_location": by_location.model_dump(),
            "daily_spend": daily_spend,
            "daily_avg": str(round(avg_daily, 2)),
            "prev_month_daily_avg": str(round(prev_avg_daily, 2)),
            "anomalies": anomalies,
            "subscription_costs": subscription_costs,
            "subscriptions_monitored": len(subscription_ids or await get_scoped_subscription_ids()),
            "generated_at": datetime.utcnow().isoformat(),
        }

    async def get_admin_dashboard(self, db: "AsyncSession | None" = None) -> dict:
        """Admin dashboard with subscription and system info.

        When *db* is provided the subscription list is read from the
        AdminSubscription table.  Falls back to the env-var list when
        no DB session is available (e.g. in dev/demo mode).
        """
        from sqlalchemy import select as _sel

        from app.models.database import AdminConfig as _AdminCfg
        from app.models.database import AdminSubscription as _AdminSub

        cache_ok = await cache_manager.ping()

        # ── Database health ────────────────────────────────────────────
        db_ok = False
        if db is not None:
            try:
                from sqlalchemy import text as _text

                await db.execute(_text("SELECT 1"))
                db_ok = True
            except Exception as e:
                logger.warning("admin_dashboard_db_health_failed", error=str(e))

        # ── Subscriptions from DB ──────────────────────────────────────
        sub_details: list[dict] = []
        enabled_count = 0
        if db is not None:
            try:
                result = await db.execute(_sel(_AdminSub).order_by(_AdminSub.subscription_name))
                for row in result.scalars().all():
                    sub_details.append(
                        {
                            "id": row.id,
                            "subscription_id": row.subscription_id,
                            "subscription_name": row.subscription_name or row.subscription_id,
                            "name": row.subscription_name or row.subscription_id,
                            "state": row.state or "Unknown",
                            "enabled": row.enabled,
                            "monitored": row.monitored,
                            "environment": row.environment,
                            "notes": row.notes,
                            "created_at": (row.created_at.isoformat() if row.created_at else None),
                            "updated_at": (row.updated_at.isoformat() if row.updated_at else None),
                            "created_by": row.created_by,
                        }
                    )
                    if row.enabled:
                        enabled_count += 1
            except Exception as e:
                logger.warning("admin_sub_list_db_failed", error=str(e))

        # Fallback: read from env-var when DB has nothing
        if not sub_details:
            sub_details = [
                {
                    "subscription_id": sid,
                    "subscription_name": sid,
                    "name": sid,
                    "state": "Unknown",
                    "enabled": True,
                    "monitored": True,
                    "environment": None,
                    "notes": None,
                    "created_at": None,
                    "updated_at": None,
                    "created_by": None,
                }
                for sid in settings.subscription_ids
            ]
            enabled_count = len(sub_details)

        # ── Read cache TTL from DB, fall back to env setting ──────────
        cache_ttl = settings.CACHE_TTL_SECONDS
        if db is not None:
            try:
                cfg_result = await db.execute(_sel(_AdminCfg).where(_AdminCfg.config_key == "cache_ttl_seconds"))
                cfg_row = cfg_result.scalar_one_or_none()
                if cfg_row and cfg_row.config_value:
                    cache_ttl = int(cfg_row.config_value)
            except Exception:
                pass  # keep default from settings

        # ── Read rate limit from DB, fall back to env setting ─────────
        rate_limit_rpm = settings.RATE_LIMIT_RPM
        if db is not None:
            try:
                rpm_result = await db.execute(_sel(_AdminCfg).where(_AdminCfg.config_key == "rate_limit_rpm"))
                rpm_row = rpm_result.scalar_one_or_none()
                if rpm_row and rpm_row.config_value:
                    rate_limit_rpm = int(rpm_row.config_value)
            except Exception:
                pass  # keep default from settings

        from app.core.admin_config import get_cache_enabled, get_effective_cors_origins, get_ollama_enabled

        cors_origins = await get_effective_cors_origins(db)
        cache_enabled = await get_cache_enabled(db)
        ollama_llm_enabled = await get_ollama_enabled(db)

        return {
            "subscriptions": sub_details,
            "subscription_count": len(sub_details),
            "enabled_count": enabled_count,
            "environment": settings.ENVIRONMENT,
            "version": settings.APP_VERSION,
            "rate_limit_rpm": rate_limit_rpm,
            "cache_ttl_seconds": cache_ttl,
            "cache_enabled": cache_enabled,
            "ollama_enabled": ollama_llm_enabled,
            "system_health": {
                "database": "connected" if db_ok else "disconnected",
                "cache": "connected" if cache_ok else "disconnected",
                "api": "healthy",
            },
            "cors_origins": cors_origins,
            "generated_at": datetime.utcnow().isoformat(),
        }
