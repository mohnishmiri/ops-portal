"""
Cost Service — Azure Cost Management API integration.

Handles multi-subscription cost queries, aggregation, caching,
and time-series data construction.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections import defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal
from urllib.parse import parse_qs, urlparse

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from app.core.admin_config import get_effective_cache_ttl_seconds
from app.core.azure_auth import get_azure_credential
from app.core.azure_throttle import AZURE_API_SEMAPHORE, acquire_for_scope
from app.core.config import settings
from app.core.db_cache import cache_manager
from app.core.subscription_resolver import get_monitored_subscription_ids
from app.models.cost import (
    CostBreakdownResponse,
    CostByGroup,
    CostDataPoint,
    CostQueryRequest,
    CostSummary,
    CostTimeSeriesResponse,
    CostTrendDirection,
    GroupByDimension,
    MultiSubscriptionOverview,
    SubscriptionCostOverview,
    TimeGranularity,
)
from app.models.database import AmortizedCostRecord

logger = structlog.get_logger(__name__)


def _build_cost_query(
    start: date,
    end: date,
    granularity: TimeGranularity,
    group_dims: list,
    cost_type: str = "actual",
):
    """Build QueryDefinition with lazy imports to avoid import-time SDK issues."""
    from azure.mgmt.costmanagement.models import (
        ExportType,
        GranularityType,
        QueryAggregation,
        QueryDataset,
        QueryDefinition,
        QueryGrouping,
        QueryTimePeriod,
        TimeframeType,
    )

    groupings = [QueryGrouping(type="Dimension", name=_DIMENSION_MAP[dim]) for dim in group_dims]

    query_type = ExportType.ACTUAL_COST
    if cost_type.lower() == "amortized" and hasattr(ExportType, "AMORTIZED_COST"):
        query_type = ExportType.AMORTIZED_COST

    return QueryDefinition(
        type=query_type,
        timeframe=TimeframeType.CUSTOM,
        time_period=QueryTimePeriod(
            from_property=datetime.combine(start, datetime.min.time()),
            to=datetime.combine(end, datetime.min.time()),
        ),
        dataset=QueryDataset(
            granularity=GranularityType.DAILY,
            aggregation={
                "totalCost": QueryAggregation(name="Cost", function="Sum"),
            },
            grouping=groupings,
        ),
    )


_DIMENSION_MAP = {
    GroupByDimension.SUBSCRIPTION: "SubscriptionId",
    GroupByDimension.RESOURCE_GROUP: "ResourceGroup",
    GroupByDimension.RESOURCE_TYPE: "ResourceType",
    GroupByDimension.SERVICE_CATEGORY: "ServiceName",
    GroupByDimension.METER_CATEGORY: "MeterCategory",
    GroupByDimension.LOCATION: "ResourceLocation",
    GroupByDimension.RESOURCE_ID: "ResourceId",
}


class CostService:
    """Service for querying Azure Cost Management API with caching."""

    def __init__(self, db: AsyncSession | None = None) -> None:
        self._credential = get_azure_credential()
        self._db = db

    def _get_client(self):
        """Create Cost Management client."""
        from azure.mgmt.costmanagement import CostManagementClient

        return CostManagementClient(credential=self._credential)

    def _cache_key(self, *parts: str) -> str:
        """Generate a deterministic cache key."""
        raw = ":".join(str(p) for p in parts)
        hashed = hashlib.md5(raw.encode()).hexdigest()  # noqa: S324
        return f"cost:{hashed}"

    def _extract_skiptoken(self, next_link: str) -> str | None:
        """Extract the Azure Cost Management skiptoken from a nextLink URL."""
        parsed = urlparse(next_link)
        params = parse_qs(parsed.query)
        return (params.get("$skiptoken") or params.get("skiptoken") or [None])[0]

    @retry(
        stop=stop_after_attempt(5),
        wait=wait_exponential(multiplier=2, min=4, max=90),
        retry=retry_if_exception(lambda exc: not isinstance(exc, ValueError)),
        reraise=True,
    )
    async def _execute_cost_query(
        self,
        scope: str,
        query,
    ) -> tuple[list[str], list[list]]:
        """Execute a cost query against Azure Cost Management API.

        Returns (column_names, rows) so callers can parse by column name.
        Uses asyncio.to_thread so multiple queries can run truly in parallel.
        Guarded by a semaphore to prevent Azure API throttling.
        On HTTP 429, honors Azure's Retry-After header (capped at 90s) so
        Cost Management's per-subscription rate limit (~10/min) is respected
        rather than burning through retries in the first 10 seconds.
        """
        from azure.core.exceptions import HttpResponseError

        def _sync_query():
            client = self._get_client()
            try:
                try:
                    result = client.query.usage(scope=scope, parameters=query)
                except HttpResponseError as exc:
                    if getattr(exc, "status_code", None) == 429:
                        retry_after = 30
                        try:
                            header_val = exc.response.headers.get("Retry-After") if exc.response else None
                            if header_val:
                                retry_after = min(int(header_val), 90)
                        except (ValueError, AttributeError):
                            pass
                        logger.warning(
                            "azure_cost_throttled_429",
                            scope=scope,
                            retry_after_seconds=retry_after,
                        )
                        import time

                        time.sleep(retry_after)
                    raise
                col_names = [c.name for c in result.columns] if result.columns else []
                rows = []
                if result.rows:
                    rows.extend(result.rows)
                next_link = getattr(result, "next_link", None)
                page_count = 1
                if next_link:
                    while next_link:
                        skiptoken = self._extract_skiptoken(next_link)
                        if not skiptoken:
                            raise RuntimeError("Azure Cost Management returned nextLink without a skiptoken")
                        result = client.query.usage(
                            scope=scope,
                            parameters=query,
                            params={"$skiptoken": skiptoken},
                        )
                        page_count += 1
                        if result.rows:
                            rows.extend(result.rows)
                        next_link = getattr(result, "next_link", None)
                    logger.debug(
                        "cost_query_pagination_complete",
                        scope=scope,
                        page_count=page_count,
                        row_count=len(rows),
                    )
                return col_names, rows
            finally:
                client.close()

        # Per-subscription rate limit (8 req/min) gates first so one sub's
        # burst can't starve another. Then the global concurrency cap keeps
        # process-wide parallelism bounded.
        await acquire_for_scope(scope)
        async with AZURE_API_SEMAPHORE:
            col_names, rows = await asyncio.to_thread(_sync_query)
        logger.debug("cost_query_result", scope=scope, columns=col_names, row_count=len(rows))
        return col_names, rows

    async def query_amortized_cost_rows(
        self,
        scope: str,
        start_date: date,
        end_date: date,
    ) -> list[dict]:
        """Query near-real-time amortized cost data via the Cost Management Query API.

        Strategy: one 2-dim primary query grouped by [ResourceId, MeterCategory]
        — every row carries its own ARM resource ID, from which we extract
        resource_name, resource_group, and resource_type. Plus one enrichment
        query for ResourceLocation grouped by [Location, ResourceGroup].

        That's 2 Azure calls per chunk total. The previous implementation
        issued up to 4 calls per chunk (primary + 2-query 1-dim fallback +
        2 enrichments), which made hitting Azure's ~10/min per-subscription
        rate limit nearly automatic on a 12-month sync. If the 2-dim primary
        fails, the chunk fails — the retry/429-aware logic in
        ``_execute_cost_query`` handles transient errors, and the
        per-range failure handling in ``_load_rows_incremental`` keeps
        other ranges from being blocked.
        """

        async def _safe_query(query, label: str):
            try:
                return await self._execute_cost_query(scope, query)
            except Exception as exc:
                logger.warning(
                    "query_amortized_enrichment_failed",
                    scope=scope,
                    label=label,
                    error=str(exc)[:300],
                )
                return [], []

        # ── 1. Primary 2-dim query ───────────────────────────────────
        two_dim_query = _build_cost_query(
            start_date,
            end_date,
            TimeGranularity.DAILY,
            [GroupByDimension.RESOURCE_ID, GroupByDimension.METER_CATEGORY],
            cost_type="amortized",
        )
        primary_cols, primary_rows = await self._execute_cost_query(scope, two_dim_query)
        logger.debug(
            "query_amortized_2dim_result",
            scope=scope,
            columns=primary_cols,
            row_count=len(primary_rows),
        )

        # ── 2. ResourceLocation enrichment (best-effort, parallel) ───
        # ResourceType is already extracted from the ResourceId path in the
        # primary rows below; no separate type query needed. When ResourceType
        # is missing (e.g. some reservation charges), the drilldown UI falls
        # back to MeterCategory.
        location_query = _build_cost_query(
            start_date,
            end_date,
            TimeGranularity.DAILY,
            [GroupByDimension.LOCATION, GroupByDimension.RESOURCE_GROUP],
            cost_type="amortized",
        )
        loc_cols, loc_rows = await _safe_query(location_query, "location")

        # ── 2. Parse primary rows ────────────────────────────────────
        parsed: list[dict] = []
        if primary_cols and primary_rows:
            col_idx = {name: i for i, name in enumerate(primary_cols)}
            cost_i = col_idx.get("Cost", col_idx.get("PreTaxCost", 0))
            date_i = col_idx.get("UsageDate", col_idx.get("BillingPeriod", -1))
            meter_i = col_idx.get("MeterCategory", col_idx.get("ServiceName"))
            rid_i = col_idx.get("ResourceId")
            rg_i = col_idx.get("ResourceGroup")

            for row in primary_rows:
                cost_val = Decimal(str(row[cost_i])).quantize(Decimal("0.01"))
                if cost_val == 0:
                    continue

                row_date = self._parse_query_row_date(row, date_i, start_date)
                meter_cat = str(row[meter_i]) if meter_i is not None and meter_i < len(row) else "Unknown"

                resource_name = ""
                rg_name = ""
                resource_type = ""

                rid_val = str(row[rid_i]) if rid_i is not None and rid_i < len(row) else ""
                if rid_val:
                    resource_name, rg_name, resource_type = self._parse_resource_id(rid_val)

                if not rg_name and rg_i is not None and rg_i < len(row):
                    rg_name = str(row[rg_i])

                parsed.append(
                    {
                        "date": row_date.isoformat(),
                        "cost": float(cost_val),
                        "meter_category": meter_cat,
                        "meter_subcategory": "",
                        "meter_name": "",
                        "resource_group": rg_name,
                        "resource_name": resource_name,
                        "resource_type": resource_type,
                        "resource_location": "",
                        "subscription_name": "",
                        "subscription_id": "",
                        "service_name": meter_cat,
                        "charge_type": "Usage",
                        "pricing_model": "",
                        "publisher_type": "Azure",
                        "frequency": "UsageBased",
                        "currency": "USD",
                    }
                )

        # ── 3. Build resource-location lookup (RG → dominant loc) ────
        rg_loc_cost: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
        if loc_cols and loc_rows:
            col_idx = {name: i for i, name in enumerate(loc_cols)}
            cost_i = col_idx.get("Cost", col_idx.get("PreTaxCost", 0))
            loc_i = col_idx.get("ResourceLocation")
            rg_i = col_idx.get("ResourceGroup")

            for row in loc_rows:
                cost_val = float(Decimal(str(row[cost_i])).quantize(Decimal("0.01")))
                if cost_val == 0:
                    continue
                loc = str(row[loc_i]) if loc_i is not None and loc_i < len(row) else ""
                rg = str(row[rg_i]) if rg_i is not None and rg_i < len(row) else ""
                if rg and loc:
                    rg_loc_cost[rg][loc] += cost_val

        rg_loc_map: dict[str, str] = {}
        for rg, loc_costs in rg_loc_cost.items():
            rg_loc_map[rg] = max(loc_costs, key=loc_costs.get)

        # ── 4. Enrich rows with location ─────────────────────────────
        for p in parsed:
            rg = p["resource_group"]
            if rg and not p["resource_location"]:
                p["resource_location"] = rg_loc_map.get(rg, "")

        logger.info(
            "query_amortized_cost_rows_loaded",
            scope=scope,
            start=start_date.isoformat(),
            end=end_date.isoformat(),
            row_count=len(parsed),
            azure_calls=2,
        )
        return parsed

    @staticmethod
    def _parse_resource_id(resource_id: str) -> tuple[str, str, str]:
        """Extract (resource_name, resource_group, resource_type) from an ARM resource ID.

        Example input:
          /subscriptions/.../resourceGroups/my-rg/providers/Microsoft.Compute/disks/my-disk
        Returns:
          ("my-disk", "my-rg", "Microsoft.Compute/disks")
        """
        parts = [p for p in resource_id.split("/") if p]
        resource_name = parts[-1] if parts else ""
        resource_group = ""
        resource_type = ""
        for i, segment in enumerate(parts):
            if segment.lower() == "resourcegroups" and i + 1 < len(parts):
                resource_group = parts[i + 1]
            if segment.lower() == "providers" and i + 2 < len(parts):
                resource_type = f"{parts[i + 1]}/{parts[i + 2]}"
        return resource_name, resource_group, resource_type

    @staticmethod
    def _parse_query_row_date(row: list, date_index: int, fallback: date) -> date:
        """Parse a UsageDate value from a Query API row."""
        raw = row[date_index] if date_index >= 0 else None
        if raw is not None:
            ds = str(raw)
            if ds.isdigit() and len(ds) == 8:
                return date(int(ds[:4]), int(ds[4:6]), int(ds[6:8]))
            return date.fromisoformat(ds[:10])
        return fallback

    async def query_costs(
        self,
        subscription_ids: list[str] | None = None,
        start_date: date | None = None,
        end_date: date | None = None,
        granularity: TimeGranularity = TimeGranularity.DAILY,
        group_by: list[GroupByDimension] | None = None,
        resource_group_filter: str | None = None,
        resource_type_filter: str | None = None,
    ) -> CostTimeSeriesResponse:
        """
        Query cost data across subscriptions.

        Uses Azure Cost Management Query API with caching.
        """
        subs = subscription_ids or await get_monitored_subscription_ids()
        group_dims = group_by or [GroupByDimension.SUBSCRIPTION]
        end = end_date or date.today()
        start = start_date or end.replace(day=1)

        # Check cache
        cache_key = self._cache_key(
            ",".join(sorted(subs)),
            str(start),
            str(end),
            granularity.value,
            ",".join(d.value for d in group_dims),
        )
        cached = await cache_manager.get_cached(cache_key)
        if cached:
            logger.debug("cache_hit", key=cache_key)
            data = json.loads(cached)
            return CostTimeSeriesResponse(**data)

        # Build query
        query_def = _build_cost_query(start, end, granularity, group_dims)

        # Execute across all subscriptions
        all_data_points: list[CostDataPoint] = []
        total_cost = Decimal("0")

        for sub_id in subs:
            scope = f"/subscriptions/{sub_id}"
            try:
                col_names, rows = await self._execute_cost_query(scope, query_def)

                # Build column-name → index map for robust parsing
                col_idx = {name: i for i, name in enumerate(col_names)}
                cost_i = col_idx.get("Cost", col_idx.get("PreTaxCost", 0))
                date_i = col_idx.get("UsageDate", col_idx.get("BillingPeriod", -1))
                # First grouping column (skip Cost, Currency, UsageDate)
                group_i: int | None = None
                for gname in (
                    "SubscriptionId",
                    "ResourceGroup",
                    "ResourceType",
                    "ServiceName",
                    "MeterCategory",
                    "ResourceLocation",
                ):
                    if gname in col_idx:
                        group_i = col_idx[gname]
                        break

                for row in rows:
                    cost = Decimal(str(row[cost_i])).quantize(Decimal("0.01"))

                    # Parse date — handle int (20260208) and string ("2026-02-08T...")
                    raw_date = row[date_i] if date_i >= 0 else None
                    if raw_date is not None:
                        ds = str(raw_date)
                        if ds.isdigit() and len(ds) == 8:
                            row_date = date(int(ds[:4]), int(ds[4:6]), int(ds[6:8]))
                        else:
                            row_date = date.fromisoformat(ds[:10])
                    else:
                        row_date = start

                    group_val = str(row[group_i]) if group_i is not None else sub_id

                    all_data_points.append(
                        CostDataPoint(
                            date=row_date,
                            cost=cost,
                            group_value=group_val,
                            group_dimension=group_dims[0],
                        )
                    )
                    total_cost += cost

            except Exception as e:
                logger.error(
                    "cost_query_failed",
                    subscription_id=sub_id,
                    scope=scope,
                    start=str(start),
                    end=str(end),
                    error=str(e),
                    error_type=type(e).__name__,
                )

        logger.info(
            "cost_query_complete",
            subscription_count=len(subs),
            data_points=len(all_data_points),
            total_cost=str(total_cost),
            start=str(start),
            end=str(end),
        )

        # Build summary
        summary = CostSummary(
            total_cost=total_cost,
            previous_period_cost=Decimal("0"),  # Would need separate query
            cost_change_pct=0.0,
            trend=CostTrendDirection.STABLE,
            period_start=start,
            period_end=end,
            subscription_count=len(subs),
        )

        query_req = CostQueryRequest(
            start_date=start,
            end_date=end,
            granularity=granularity,
            group_by=group_dims,
        )

        response = CostTimeSeriesResponse(
            data_points=all_data_points,
            summary=summary,
            query=query_req,
        )

        # Only cache responses that contain actual data — avoids locking
        # in empty results from transient Azure API failures.
        if all_data_points:
            await cache_manager.set_cached(
                cache_key,
                response.model_dump_json(),
                ttl=settings.CACHE_TTL_SECONDS,
            )
        else:
            logger.warning(
                "skipping_cache_empty_result",
                cache_key=cache_key,
                subscription_count=len(subs),
                start=str(start),
                end=str(end),
            )

        return response

    async def get_cost_breakdown(
        self,
        subscription_ids: list[str] | None,
        dimension: GroupByDimension,
        start_date: date,
        end_date: date,
    ) -> CostBreakdownResponse:
        """Get cost breakdown by a single dimension."""
        ts_response = await self.query_costs(
            subscription_ids=subscription_ids,
            start_date=start_date,
            end_date=end_date,
            group_by=[dimension],
        )

        # Aggregate by group value
        group_totals: dict[str, Decimal] = {}
        for dp in ts_response.data_points:
            group_totals[dp.group_value] = group_totals.get(dp.group_value, Decimal("0")) + dp.cost

        total = sum(group_totals.values(), Decimal("0"))
        breakdown = [
            CostByGroup(
                group_dimension=dimension,
                group_value=name,
                total_cost=cost,
                percentage_of_total=float(cost / total * 100) if total else 0.0,
            )
            for name, cost in sorted(group_totals.items(), key=lambda x: x[1], reverse=True)
        ]

        return CostBreakdownResponse(
            breakdown=breakdown,
            summary=ts_response.summary,
            group_dimension=dimension,
        )

    async def get_env_cost_details(
        self,
        environment: str,
        num_months: int = 3,
    ) -> dict:
        """
        Get monthly cost breakdown by MeterCategory for a specific environment.

        Returns a pivot-table structure: rows = service types, columns = months.
        Environment is mapped to subscription + resource-group prefix filter:
          PROD  → prod subscription (entire subscription)
          DEV / PERF / DR / etc. → non-prod subscription, filtered by RG prefix.
        """

        if self._db is not None:
            db_payload = await self._get_env_cost_details_from_db(environment, num_months)
            if db_payload is not None:
                return db_payload

        # ── Load environment config from budget_config.json ───────────
        import json as _json
        from pathlib import Path as _Path

        _cfg_path = _Path(__file__).resolve().parents[2] / "config" / "budget_config.json"
        non_prod_sub_ids: set[str] = set()
        all_sub_ids: list[str] = list(await get_monitored_subscription_ids())
        if _cfg_path.exists():
            with open(_cfg_path, encoding="utf-8") as _f:
                _cfg = _json.load(_f)
            for app in _cfg.get("applications", []):
                for sid in app.get("non_prod_subscription_ids", []):
                    non_prod_sub_ids.add(sid)

        prod_sub_ids = [s for s in all_sub_ids if s not in non_prod_sub_ids]
        np_sub_ids = [s for s in all_sub_ids if s in non_prod_sub_ids]

        # ── Environment → subscription + RG prefix mapping ───────────
        env_upper = environment.upper()
        rg_prefix: str | None = None

        if env_upper == "PROD":
            target_subs = prod_sub_ids or all_sub_ids
        elif env_upper in ("DEV", "PERF", "DR", "DEVNR3PL", "UAT", "STG"):
            target_subs = np_sub_ids or all_sub_ids
            rg_prefix = f"attcc-eastus2-{env_upper.lower()}-"
        elif env_upper == "ALL":
            target_subs = all_sub_ids
        else:
            # Fallback: treat as non-prod env with RG prefix
            target_subs = np_sub_ids or all_sub_ids
            rg_prefix = f"attcc-eastus2-{env_upper.lower()}-"

        # ── Date range covering num_months ────────────────────────────
        today = date.today()
        end = today
        # Walk back num_months from the first of the current month
        m = today.month - num_months
        y = today.year
        while m < 1:
            m += 12
            y -= 1
        start = date(y, m, 1)

        # ── Build query: group by MeterCategory (+ResourceGroup when filtering)
        group_dims: list[GroupByDimension] = [GroupByDimension.METER_CATEGORY]
        if rg_prefix:
            group_dims.append(GroupByDimension.RESOURCE_GROUP)

        query_def = _build_cost_query(start, end, TimeGranularity.DAILY, group_dims)

        # ── Execute across target subscriptions ───────────────────────
        month_service: dict[str, dict[str, Decimal]] = {}  # "YYYY-MM" → {meter: cost}

        for sub_id in target_subs:
            scope = f"/subscriptions/{sub_id}"
            try:
                col_names, rows = await self._execute_cost_query(scope, query_def)
                col_idx = {name: i for i, name in enumerate(col_names)}
                cost_i = col_idx.get("Cost", col_idx.get("PreTaxCost", 0))
                date_i = col_idx.get("UsageDate", col_idx.get("BillingPeriod", -1))
                meter_i = col_idx.get("MeterCategory", -1)
                rg_i = col_idx.get("ResourceGroup", -1)

                for row in rows:
                    # Apply RG prefix filter when needed
                    if rg_prefix and rg_i >= 0:
                        rg_name = str(row[rg_i]).lower()
                        if not rg_name.startswith(rg_prefix.lower()):
                            continue

                    cost = Decimal(str(row[cost_i])).quantize(Decimal("0.01"))
                    if cost == 0:
                        continue

                    # Parse date → month key
                    raw_date = row[date_i] if date_i >= 0 else None
                    if raw_date is not None:
                        ds = str(raw_date)
                        if ds.isdigit() and len(ds) == 8:
                            row_date = date(int(ds[:4]), int(ds[4:6]), int(ds[6:8]))
                        else:
                            row_date = date.fromisoformat(ds[:10])
                    else:
                        row_date = start

                    month_key = row_date.strftime("%Y-%m")
                    meter_cat = str(row[meter_i]) if meter_i >= 0 else "Unknown"

                    month_service.setdefault(month_key, {})
                    month_service[month_key][meter_cat] = month_service[month_key].get(meter_cat, Decimal("0")) + cost

            except Exception as e:
                logger.error(
                    "env_cost_query_failed",
                    subscription_id=sub_id,
                    environment=env_upper,
                    error=str(e),
                    error_type=type(e).__name__,
                )

        # ── Build pivot-table response ────────────────────────────────
        months = sorted(month_service.keys())

        month_labels: dict[str, str] = {}
        for m_key in months:
            parts = m_key.split("-")
            month_labels[m_key] = date(int(parts[0]), int(parts[1]), 1).strftime("%Y %b")

        # Collect all service names
        all_services: set[str] = set()
        for md in month_service.values():
            all_services.update(md.keys())

        services: list[dict] = []
        for svc in sorted(all_services):
            monthly_costs: dict[str, str] = {}
            total = Decimal("0")
            for mk in months:
                c = month_service.get(mk, {}).get(svc, Decimal("0"))
                monthly_costs[mk] = str(c)
                total += c
            services.append(
                {
                    "service_name": svc,
                    "monthly_costs": monthly_costs,
                    "total": str(total),
                }
            )

        # Sort by total cost descending
        services.sort(key=lambda x: Decimal(x["total"]), reverse=True)

        # Monthly & grand totals
        monthly_totals: dict[str, str] = {}
        grand_total = Decimal("0")
        for mk in months:
            mt = sum(month_service.get(mk, {}).values(), Decimal("0"))
            monthly_totals[mk] = str(mt)
            grand_total += mt

        available_envs = ["PROD", "DEV", "PERF", "DR", "ALL"]

        return {
            "environment": env_upper,
            "months": months,
            "month_labels": month_labels,
            "services": services,
            "monthly_totals": monthly_totals,
            "grand_total": str(grand_total),
            "available_environments": available_envs,
            "generated_at": datetime.utcnow().isoformat(),
        }

    async def _get_env_cost_details_from_db(
        self,
        environment: str,
        num_months: int,
    ) -> dict | None:
        """Build the env-breakdown payload from amortized rows already stored in PostgreSQL."""
        if self._db is None:
            return None

        env_upper = environment.upper()
        cache_key = f"pagecache:env-breakdown:{env_upper}:{num_months}"
        cached = await cache_manager.get_cached(cache_key)
        if cached:
            try:
                return json.loads(cached)
            except (TypeError, ValueError):
                pass

        today = date.today()
        m = today.month - num_months
        y = today.year
        while m < 1:
            m += 12
            y -= 1
        start = date(y, m, 1)
        start_str = start.isoformat()
        end_str = today.isoformat()

        stmt = select(
            AmortizedCostRecord.cost_date,
            AmortizedCostRecord.meter_category,
            AmortizedCostRecord.cost_amount,
            AmortizedCostRecord.resource_group,
            AmortizedCostRecord.env_label,
        ).where(
            AmortizedCostRecord.cost_date >= start_str,
            AmortizedCostRecord.cost_date <= end_str,
        )

        result = await self._db.execute(stmt)
        records = result.all()
        if not records:
            return None

        month_service: dict[str, dict[str, Decimal]] = {}
        for (
            cost_date,
            meter_category,
            cost_amount,
            resource_group,
            env_label,
        ) in records:
            if not self._env_breakdown_row_matches(
                env_upper,
                resource_group=resource_group or "",
                env_label=env_label or "",
            ):
                continue

            month_key = str(cost_date)[:7]
            service_name = meter_category or "Unknown"
            cost_decimal = Decimal(str(cost_amount)).quantize(Decimal("0.01"))
            month_service.setdefault(month_key, {})
            month_service[month_key][service_name] = (
                month_service[month_key].get(service_name, Decimal("0")) + cost_decimal
            )

        months = sorted(month_service.keys())
        month_labels: dict[str, str] = {}
        for month_key in months:
            parts = month_key.split("-")
            month_labels[month_key] = date(int(parts[0]), int(parts[1]), 1).strftime("%Y %b")

        all_services: set[str] = set()
        for monthly in month_service.values():
            all_services.update(monthly.keys())

        services: list[dict] = []
        for service_name in sorted(all_services):
            monthly_costs: dict[str, str] = {}
            total = Decimal("0")
            for month_key in months:
                cost = month_service.get(month_key, {}).get(service_name, Decimal("0"))
                monthly_costs[month_key] = str(cost)
                total += cost
            services.append(
                {
                    "service_name": service_name,
                    "monthly_costs": monthly_costs,
                    "total": str(total),
                }
            )

        services.sort(key=lambda item: Decimal(item["total"]), reverse=True)

        monthly_totals: dict[str, str] = {}
        grand_total = Decimal("0")
        for month_key in months:
            month_total = sum(month_service.get(month_key, {}).values(), Decimal("0"))
            monthly_totals[month_key] = str(month_total)
            grand_total += month_total

        payload = {
            "environment": env_upper,
            "months": months,
            "month_labels": month_labels,
            "services": services,
            "monthly_totals": monthly_totals,
            "grand_total": str(grand_total),
            "available_environments": ["PROD", "DEV", "PERF", "DR", "ALL"],
            "generated_at": datetime.utcnow().isoformat(),
        }

        ttl = await get_effective_cache_ttl_seconds(self._db)
        await cache_manager.set_cached(cache_key, json.dumps(payload), ttl=ttl)
        logger.info(
            "env_breakdown_served",
            source="database",
            environment=env_upper,
            months=num_months,
            month_count=len(months),
            service_count=len(services),
        )
        return payload

    @staticmethod
    def _env_breakdown_row_matches(
        environment: str,
        *,
        resource_group: str,
        env_label: str,
    ) -> bool:
        """Match amortized rows to the legacy env-breakdown filters."""
        if environment == "ALL":
            return True
        if environment == "PROD":
            return env_label == "Prod"

        if env_label != "Non-Prod":
            return False

        resource_group_lower = resource_group.lower()
        env_prefix_map = {
            "DEV": "attcc-eastus2-dev-",
            "PERF": "attcc-eastus2-perf-",
            "DR": "attcc-eastus2-dr-",
            "DEVNR3PL": "attcc-eastus2-devnr3pl-",
            "UAT": "attcc-eastus2-uat-",
            "STG": "attcc-eastus2-stg-",
            "STAGING": "attcc-eastus2-staging-",
            "POC": "attcc-eastus2-poc-",
            "TEST": "attcc-eastus2-test-",
        }
        prefix = env_prefix_map.get(environment, f"attcc-eastus2-{environment.lower()}-")
        return resource_group_lower.startswith(prefix)

    async def get_nonprod_vs_prod_trend(
        self,
        num_months: int = 6,
    ) -> dict:
        """
        Monthly cost trend: Non-Prod vs Prod, served from amortized_cost_records.

        Previously this issued one live Azure Cost Management query per
        subscription, which (a) cost minutes per call, (b) frequently 429'd
        when bursting, and (c) silently dropped a whole sub's contribution
        if its query failed — which is why the Executive Forecast and the
        Prod Spend Share card kept losing the Non-Prod stream.

        Classification uses ``AdminSubscription.environment`` (the value
        an admin sets in the Admin panel) — the single source of truth.
        Same DB table that powers the main dashboard, so figures stay
        consistent and we're immune to Azure throttling at request time.
        """
        # Same normaliser the leadership dashboard uses, so the Prod Spend
        # Share card / Executive Forecast and the trend endpoint never
        # disagree about which subs are prod vs non-prod.
        from app.models.database import AdminSubscription
        from app.services.amortized_cost_sync_service import AmortizedCostSyncService

        # Calendar-month window ending on the LAST FULL month. We deliberately
        # exclude the current (partial) month — including a single day of
        # data as a "complete" month produced a fake -98% drop on the
        # leadership dashboard and zeroed the Executive Forecast.
        today = date.today()
        current_month_start = today.replace(day=1)
        end = current_month_start - timedelta(days=1)  # last day of previous month
        m = end.month - (num_months - 1)
        y = end.year
        while m < 1:
            m += 12
            y -= 1
        start = date(y, m, 1)

        if self._db is None:
            logger.warning("nonprod_vs_prod_no_db_session")
            return {"months": 0, "data": [], "generated_at": datetime.utcnow().isoformat()}

        from sqlalchemy import func as _func
        from sqlalchemy import select as _select

        from app.models.database import AmortizedCostRecord

        # Per-sub env map. Admin's Environment field is preferred; falls
        # back to subscription name pattern (ACC-NPRD-… / ACC-PROD-…) when
        # admin hasn't tagged the sub. Same logic the leadership dashboard
        # uses so the two endpoints agree.
        admin_env_result = await self._db.execute(
            _select(
                AdminSubscription.subscription_id,
                AdminSubscription.environment,
                AdminSubscription.subscription_name,
            )
        )
        admin_env_by_sub: dict[str, str] = {
            sid: AmortizedCostSyncService.resolve_env_label(env, name)
            for sid, env, name in admin_env_result.all()
            if sid
        }

        # Group by full cost_date + sub_id + env_label and aggregate by month
        # in Python. asyncpg rejects ``func.substr(...)`` reused between SELECT
        # and GROUP BY because the expression objects aren't equal-text and it
        # complains "column ... must appear in GROUP BY". The row count is
        # bounded (≤ months * 31 * subs * 2 envs) so this is cheap.
        result = await self._db.execute(
            _select(
                AmortizedCostRecord.cost_date,
                AmortizedCostRecord.subscription_id,
                AmortizedCostRecord.env_label,
                _func.sum(AmortizedCostRecord.cost_amount).label("total"),
            )
            .where(
                AmortizedCostRecord.cost_date >= start.isoformat(),
                AmortizedCostRecord.cost_date <= end.isoformat(),
            )
            .group_by(
                AmortizedCostRecord.cost_date,
                AmortizedCostRecord.subscription_id,
                AmortizedCostRecord.env_label,
            )
        )

        # Aggregate: {month_key: {"np": Decimal, "prod": Decimal}}
        by_month: dict[str, dict[str, Decimal]] = {}
        np_total_seen = Decimal("0")
        prod_total_seen = Decimal("0")
        for cost_date, sub_id, stored_env, total in result.all():
            mk = str(cost_date)[:7]  # YYYY-MM
            cost = Decimal(str(round(float(total or 0), 2)))
            bucket = by_month.setdefault(mk, {"np": Decimal("0"), "prod": Decimal("0")})
            current_env = admin_env_by_sub.get(str(sub_id or "").strip())
            effective = current_env or (stored_env if stored_env in ("Prod", "Non-Prod") else "Prod")
            if effective == "Non-Prod":
                bucket["np"] += cost
                np_total_seen += cost
            else:
                bucket["prod"] += cost
                prod_total_seen += cost

        data_points: list[dict] = []
        for mk in sorted(by_month.keys()):
            np_cost = by_month[mk]["np"]
            prod_cost = by_month[mk]["prod"]
            total = np_cost + prod_cost
            parts = mk.split("-")
            label = date(int(parts[0]), int(parts[1]), 1).strftime("%b %Y")
            data_points.append(
                {
                    "month_key": mk,
                    "month": label,
                    "non_prod": str(np_cost),
                    "prod": str(prod_cost),
                    "total": str(total),
                }
            )

        logger.info(
            "nonprod_vs_prod_trend_served",
            source="amortized_db",
            months=len(data_points),
            np_total=float(np_total_seen),
            prod_total=float(prod_total_seen),
            admin_subs_mapped=len(admin_env_by_sub),
        )

        return {
            "months": len(data_points),
            "data": data_points,
            "generated_at": datetime.utcnow().isoformat(),
        }

    async def get_multi_subscription_overview(
        self,
        subscription_ids: list[str] | None = None,
    ) -> MultiSubscriptionOverview:
        """Get overview across all subscriptions with top resource groups & services."""
        subs = subscription_ids or await get_monitored_subscription_ids()
        today = date.today()
        month_start = today.replace(day=1)

        overviews: list[SubscriptionCostOverview] = []
        total = Decimal("0")

        for sub_id in subs:
            try:
                current = await self.query_costs(
                    subscription_ids=[sub_id],
                    start_date=month_start,
                    end_date=today,
                    group_by=[GroupByDimension.RESOURCE_GROUP],
                )

                current_cost = current.summary.total_cost
                total += current_cost

                # Top resource groups
                group_totals: dict[str, Decimal] = {}
                for dp in current.data_points:
                    group_totals[dp.group_value] = group_totals.get(dp.group_value, Decimal("0")) + dp.cost

                top_rgs = [
                    CostByGroup(
                        group_dimension=GroupByDimension.RESOURCE_GROUP,
                        group_value=name,
                        total_cost=cost,
                        percentage_of_total=(float(cost / current_cost * 100) if current_cost else 0),
                    )
                    for name, cost in sorted(group_totals.items(), key=lambda x: x[1], reverse=True)[:10]
                ]

                overviews.append(
                    SubscriptionCostOverview(
                        subscription_id=sub_id,
                        subscription_name=sub_id,  # Would resolve via Resource client
                        current_month_cost=current_cost,
                        previous_month_cost=Decimal("0"),
                        cost_change_pct=0.0,
                        trend=CostTrendDirection.STABLE,
                        top_resource_groups=top_rgs,
                        top_services=[],
                    )
                )
            except Exception as e:
                logger.error("subscription_overview_failed", sub_id=sub_id, error=str(e))

        return MultiSubscriptionOverview(
            total_cost=total,
            subscriptions=overviews,
            generated_at=datetime.utcnow(),
            period_start=month_start,
            period_end=today,
        )
