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
from datetime import date, datetime
from decimal import Decimal
from urllib.parse import parse_qs, urlparse

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from tenacity import retry, stop_after_attempt, wait_exponential

from app.core.admin_config import get_effective_cache_ttl_seconds
from app.core.azure_auth import get_azure_credential
from app.core.azure_throttle import AZURE_API_SEMAPHORE
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
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
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
        Retries up to 3 times with exponential backoff on transient failures.
        """

        def _sync_query():
            client = self._get_client()
            try:
                result = client.query.usage(scope=scope, parameters=query)
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

        Preferred strategy: a single query grouped by both MeterCategory and
        ResourceGroup (2-dimension).  This gives every row both service and
        resource-group attribution in a single call.

        Fallback: if the 2-dimension query fails or returns no data, we
        revert to two 1-dimension queries (MeterCategory only + ResourceGroup
        only) and merge them — this is slower but proven reliable.

        Enrichment queries for ResourceType and ResourceLocation run in
        parallel (best-effort); failures are logged but non-fatal.
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

        # ── 1. Try preferred 2-dimension primary query ───────────────
        # Group by [ResourceId, MeterCategory] so every row carries its
        # own ARM resource ID.  From the ID we extract the human-readable
        # resource_name (last path segment), resource_group, and
        # resource_type — matching what Azure's cost-export CSV provides.
        primary_cols: list[str] = []
        primary_rows: list[list] = []
        used_fallback = False

        try:
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
        except Exception as two_dim_exc:
            logger.warning(
                "query_amortized_2dim_failed_trying_fallback",
                scope=scope,
                error=str(two_dim_exc)[:300],
            )
            primary_cols, primary_rows = [], []

        # ── 2. Fallback: separate 1-dimension queries ────────────────
        rg_lookup: dict[str, list[dict]] = defaultdict(list)

        if not primary_rows:
            used_fallback = True
            svc_query = _build_cost_query(
                start_date,
                end_date,
                TimeGranularity.DAILY,
                [GroupByDimension.METER_CATEGORY],
                cost_type="amortized",
            )
            primary_cols, primary_rows = await self._execute_cost_query(scope, svc_query)
            logger.info(
                "query_amortized_fallback_result",
                scope=scope,
                columns=primary_cols,
                row_count=len(primary_rows),
            )

            rg_cols, rg_rows = await _safe_query(
                _build_cost_query(
                    start_date,
                    end_date,
                    TimeGranularity.DAILY,
                    [GroupByDimension.RESOURCE_GROUP],
                    cost_type="amortized",
                ),
                "fallback_rg",
            )
            if rg_cols and rg_rows:
                rg_col_idx = {name: i for i, name in enumerate(rg_cols)}
                rg_cost_i = rg_col_idx.get("Cost", rg_col_idx.get("PreTaxCost", 0))
                rg_date_i = rg_col_idx.get("UsageDate", rg_col_idx.get("BillingPeriod", -1))
                rg_rg_i = rg_col_idx.get("ResourceGroup")
                for row in rg_rows:
                    cost_val = Decimal(str(row[rg_cost_i])).quantize(Decimal("0.01"))
                    if cost_val == 0:
                        continue
                    row_date = self._parse_query_row_date(row, rg_date_i, start_date)
                    rg_name = str(row[rg_rg_i]) if rg_rg_i is not None and rg_rg_i < len(row) else ""
                    rg_lookup[row_date.isoformat()].append({"resource_group": rg_name, "cost": float(cost_val)})

        # ── 3. Enrichment: ResourceLocation (best-effort) ────────────
        # ResourceType is extracted from the ResourceId path when available;
        # the MeterCategory-based lookup serves as a fallback.
        type_query = _build_cost_query(
            start_date,
            end_date,
            TimeGranularity.DAILY,
            [GroupByDimension.RESOURCE_TYPE, GroupByDimension.METER_CATEGORY],
            cost_type="amortized",
        )
        location_query = _build_cost_query(
            start_date,
            end_date,
            TimeGranularity.DAILY,
            [GroupByDimension.LOCATION, GroupByDimension.RESOURCE_GROUP],
            cost_type="amortized",
        )
        (type_cols, type_rows), (loc_cols, loc_rows) = await asyncio.gather(
            _safe_query(type_query, "type"),
            _safe_query(location_query, "location"),
        )

        # ── 4. Parse primary rows ────────────────────────────────────
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

        # ── 5. Fallback RG enrichment (only in 1-dim mode) ──────────
        if used_fallback and rg_lookup:
            for p in parsed:
                if not p["resource_group"]:
                    rg_entries = rg_lookup.get(p["date"])
                    if rg_entries and len(rg_entries) == 1:
                        p["resource_group"] = rg_entries[0]["resource_group"]

        # ── 6. Build resource-type fallback (MeterCategory → dominant type)
        mc_type_cost: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
        if type_cols and type_rows:
            col_idx = {name: i for i, name in enumerate(type_cols)}
            cost_i = col_idx.get("Cost", col_idx.get("PreTaxCost", 0))
            rtype_i = col_idx.get("ResourceType")
            mc_i = col_idx.get("MeterCategory", col_idx.get("ServiceName"))

            for row in type_rows:
                cost_val = float(Decimal(str(row[cost_i])).quantize(Decimal("0.01")))
                if cost_val == 0:
                    continue
                rtype = str(row[rtype_i]) if rtype_i is not None and rtype_i < len(row) else ""
                mc = str(row[mc_i]) if mc_i is not None and mc_i < len(row) else ""
                if mc and rtype:
                    mc_type_cost[mc][rtype] += cost_val

        mc_type_map: dict[str, str] = {}
        for mc, type_costs in mc_type_cost.items():
            mc_type_map[mc] = max(type_costs, key=type_costs.get)

        # ── 7. Build resource-location lookup (RG → dominant loc) ────
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

        # ── 8. Enrich rows with fallback type and location ───────────
        for p in parsed:
            rg = p["resource_group"]
            mc = p["meter_category"]
            if not p["resource_type"]:
                p["resource_type"] = mc_type_map.get(mc, "")
            if rg and not p["resource_location"]:
                p["resource_location"] = rg_loc_map.get(rg, "")

        logger.info(
            "query_amortized_cost_rows_loaded",
            scope=scope,
            start=start_date.isoformat(),
            end=end_date.isoformat(),
            row_count=len(parsed),
            used_fallback=used_fallback,
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
        Monthly cost trend: Non-Prod vs Prod.

        Returns a list of monthly data-points, each containing:
        non_prod, prod, total, and a human-readable month label.
        Uses budget_config.json to determine which subscription IDs
        belong to non-prod vs prod.
        """
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

        prod_subs = [s for s in all_sub_ids if s not in non_prod_sub_ids]
        np_subs = [s for s in all_sub_ids if s in non_prod_sub_ids]

        # Date range
        today = date.today()
        end = today
        m = today.month - num_months
        y = today.year
        while m < 1:
            m += 12
            y -= 1
        start = date(y, m, 1)

        query_def = _build_cost_query(start, end, TimeGranularity.DAILY, [])

        # Accumulate per-subscription totals per month
        sub_monthly: dict[str, dict[str, Decimal]] = {}  # sub_id → {"YYYY-MM": cost}

        for sub_id in all_sub_ids:
            scope = f"/subscriptions/{sub_id}"
            try:
                col_names, rows = await self._execute_cost_query(scope, query_def)
                col_idx = {name: i for i, name in enumerate(col_names)}
                cost_i = col_idx.get("Cost", col_idx.get("PreTaxCost", 0))
                date_i = col_idx.get("UsageDate", col_idx.get("BillingPeriod", -1))

                for row in rows:
                    cost = Decimal(str(row[cost_i])).quantize(Decimal("0.01"))
                    if cost == 0:
                        continue
                    raw_date = row[date_i] if date_i >= 0 else None
                    if raw_date is not None:
                        ds = str(raw_date)
                        if ds.isdigit() and len(ds) == 8:
                            row_date = date(int(ds[:4]), int(ds[4:6]), int(ds[6:8]))
                        else:
                            row_date = date.fromisoformat(ds[:10])
                    else:
                        row_date = start
                    mk = row_date.strftime("%Y-%m")
                    sub_monthly.setdefault(sub_id, {})
                    sub_monthly[sub_id][mk] = sub_monthly[sub_id].get(mk, Decimal("0")) + cost
            except Exception as e:
                logger.error("nonprod_prod_query_failed", sub_id=sub_id, error=str(e))

        # Collect all month keys
        all_months: set[str] = set()
        for sm in sub_monthly.values():
            all_months.update(sm.keys())
        months_sorted = sorted(all_months)

        # Build response
        data_points: list[dict] = []
        for mk in months_sorted:
            np_cost = sum(sub_monthly.get(sid, {}).get(mk, Decimal("0")) for sid in np_subs)
            prod_cost = sum(sub_monthly.get(sid, {}).get(mk, Decimal("0")) for sid in prod_subs)
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
