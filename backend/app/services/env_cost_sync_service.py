"""
Environment Daily Cost Sync Service.

Fetches daily costs from Azure Cost Management API, maps resource groups
to environment names, and stores aggregated daily totals per environment
in PostgreSQL for fast page loading.

Environments are derived from resource-group naming convention:
  attcc-eastus2-{env_lower}-*

Prod subscription resources that don't match a known RG prefix
are bucketed as PROD; non-prod resources without a known prefix
go to MISC.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import structlog
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.subscription_resolver import get_monitored_subscription_ids
from app.models.database import EnvCostSyncStatus, EnvDailyCost
from app.services.cost_service import CostService

logger = structlog.get_logger(__name__)

# ── Constants ────────────────────────────────────────────────────────────

# Environment mapping: RG name patterns → canonical environment label.
# Keys are checked as substrings (lowered); first match wins.
_ENV_PATTERNS: list[tuple[str, str]] = [
    # DEV
    ("-dev-", "DEV"),
    ("-dev1-", "DEV"),
    # PERF
    ("-perf-", "PERF"),
    ("-perf1-", "PERF"),
    ("-prf1-", "PERF"),
    # UAT
    ("-uat-", "UAT"),
    ("-uat1-", "UAT"),
    # STAGING
    ("-stg1-", "STAGING"),
    ("-stge-", "STAGING"),
    ("-stage-", "STAGING"),
    ("-staging-", "STAGING"),
    # POC
    ("-poc-", "POC"),
    # PROD
    ("-prod-", "PROD"),
    ("-prd1-", "PROD"),
    # DR
    ("-dr-", "DR"),
    ("-dr1-", "DR"),
    # TEST
    ("-test-", "TEST"),
]

# Resource groups that should be classified as SHARED (infra / devops / managed).
_SHARED_RG_PATTERNS = (
    "devops",
    "law-rg",
    "networkwatcher",
    "synapseworkspace-managedrg",
    "azurebackuprg",
    "cloud-shell-storage",
    "cso-astra-lumberjack",
)

# Default number of days to sync (current week = 7)
DEFAULT_SYNC_DAYS = 7

# Stale data threshold in hours before auto-re-sync
STALE_HOURS = 6


async def _load_subscription_config() -> tuple[list[str], list[str], set[str]]:
    """Load prod / non-prod subscription IDs from admin DB (or env fallback).

    Returns:
        (all_sub_ids, prod_sub_ids, non_prod_sub_ids_set)
    """
    cfg_path = Path(__file__).resolve().parents[2] / "config" / "budget_config.json"
    non_prod_set: set[str] = set()
    all_sub_ids: list[str] = list(await get_monitored_subscription_ids())

    if cfg_path.exists():
        with open(cfg_path, encoding="utf-8") as f:
            cfg = json.load(f)
        for app in cfg.get("applications", []):
            for sid in app.get("non_prod_subscription_ids", []):
                non_prod_set.add(sid)

    prod_ids = [s for s in all_sub_ids if s not in non_prod_set]
    return all_sub_ids, prod_ids, non_prod_set


def _rg_to_env(rg_name: str) -> str | None:
    """Map a resource-group name to an environment label.

    Checks for known environment substring patterns in the RG name, then
    shared / infrastructure patterns.  Returns None if unrecognised.
    """
    rg_lower = rg_name.lower()

    # Check for shared / infra RGs first
    for pat in _SHARED_RG_PATTERNS:
        if pat in rg_lower:
            return "SHARED"

    # Check environment patterns (substring match)
    for pattern, env_label in _ENV_PATTERNS:
        if pattern in rg_lower:
            return env_label

    return None


class EnvCostSyncService:
    """Syncs daily environment cost data from Azure to PostgreSQL."""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db
        self._cost_service = CostService()

    # ── Public API ───────────────────────────────────────────────────

    async def is_data_stale(self) -> bool:
        """Check if the cached env-cost data is stale or missing."""
        result = await self._db.execute(
            select(EnvCostSyncStatus)
            .where(EnvCostSyncStatus.status.in_(["completed", "partial"]))
            .order_by(EnvCostSyncStatus.completed_at.desc())
            .limit(1)
        )
        last_sync = result.scalars().first()
        if not last_sync or not last_sync.completed_at:
            return True
        age = datetime.utcnow() - last_sync.completed_at
        return age > timedelta(hours=STALE_HOURS)

    async def full_sync(
        self,
        days: int = DEFAULT_SYNC_DAYS,
        triggered_by: str = "manual",
    ) -> dict:
        """Sync daily costs for all environments over the last *days* days.

        Steps:
        1. Query Azure Cost Management API per subscription, grouped by
           ResourceGroup, with daily granularity.
        2. Map each resource-group to an environment.
        3. Upsert aggregated daily totals into ``env_daily_costs``.
        4. Record sync status.
        """
        sync_record = EnvCostSyncStatus(
            sync_type="full",
            status="running",
            started_at=datetime.utcnow(),
            triggered_by=triggered_by,
        )
        self._db.add(sync_record)
        await self._db.commit()

        try:
            all_sub_ids, prod_ids, non_prod_set = await _load_subscription_config()

            end_date = date.today()
            start_date = end_date - timedelta(days=days - 1)

            # Build Azure Cost Management query grouped by ResourceGroup
            from app.models.cost import GroupByDimension, TimeGranularity
            from app.services.cost_service import _build_cost_query

            query_def = _build_cost_query(
                start_date,
                end_date,
                TimeGranularity.DAILY,
                [GroupByDimension.RESOURCE_GROUP],
            )

            # Accumulate: (sub_type, env, date) → cost
            env_cost_map: dict[tuple[str, str, date], Decimal] = {}

            for sub_id in all_sub_ids:
                is_prod_sub = sub_id not in non_prod_set
                sub_type = "prod" if is_prod_sub else "nonprod"
                scope = f"/subscriptions/{sub_id}"

                try:
                    col_names, rows = await self._cost_service._execute_cost_query(
                        scope,
                        query_def,
                    )
                    col_idx = {name: i for i, name in enumerate(col_names)}
                    cost_i = col_idx.get("Cost", col_idx.get("PreTaxCost", 0))
                    date_i = col_idx.get("UsageDate", col_idx.get("BillingPeriod", -1))
                    rg_i = col_idx.get("ResourceGroup", -1)

                    for row in rows:
                        cost = Decimal(str(row[cost_i])).quantize(Decimal("0.01"))
                        if cost == 0:
                            continue

                        # Parse date
                        raw_date = row[date_i] if date_i >= 0 else None
                        if raw_date is not None:
                            ds = str(raw_date)
                            if ds.isdigit() and len(ds) == 8:
                                row_date = date(int(ds[:4]), int(ds[4:6]), int(ds[6:8]))
                            else:
                                row_date = date.fromisoformat(ds[:10])
                        else:
                            row_date = start_date

                        # Map RG → environment
                        rg_name = str(row[rg_i]) if rg_i >= 0 else ""
                        env = _rg_to_env(rg_name)

                        if env is None:
                            # Resources without a known env prefix
                            if is_prod_sub:
                                env = "PROD"
                            else:
                                env = "MISC"

                        # DR might live on non-prod subscription
                        # but we want it in the prod table
                        if env == "DR":
                            sub_type_for_record = "prod"
                        else:
                            sub_type_for_record = sub_type

                        key = (sub_type_for_record, env, row_date)
                        env_cost_map[key] = env_cost_map.get(key, Decimal("0")) + cost

                    logger.debug(
                        "env_cost_sub_queried",
                        subscription_id=sub_id,
                        sub_type=sub_type,
                        rows=len(rows),
                    )

                except Exception as exc:
                    logger.error(
                        "env_cost_sub_query_failed",
                        subscription_id=sub_id,
                        error=str(exc)[:300],
                    )

            # ── Upsert into DB ────────────────────────────────────────
            upserted = 0
            total_cost = Decimal("0")
            envs_seen: set[str] = set()
            now = datetime.utcnow()

            # Delete existing data for the date range then bulk-insert
            await self._db.execute(
                delete(EnvDailyCost).where(
                    EnvDailyCost.cost_date >= datetime.combine(start_date, datetime.min.time()),
                    EnvDailyCost.cost_date <= datetime.combine(end_date, datetime.min.time()),
                )
            )

            for (sub_type, env, cost_date), cost in env_cost_map.items():
                row = EnvDailyCost(
                    subscription_type=sub_type,
                    environment=env,
                    cost_date=datetime.combine(cost_date, datetime.min.time()),
                    cost_amount=float(cost),
                    currency="USD",
                    synced_at=now,
                )
                self._db.add(row)
                upserted += 1
                total_cost += cost
                envs_seen.add(env)

            await self._db.commit()

            # ── Update sync status ────────────────────────────────────
            sync_record.status = "completed"
            sync_record.completed_at = datetime.utcnow()
            sync_record.days_synced = days
            sync_record.environments_synced = len(envs_seen)
            sync_record.total_cost = float(total_cost)
            await self._db.commit()

            result = {
                "status": "completed",
                "days_synced": days,
                "environments_synced": len(envs_seen),
                "records_upserted": upserted,
                "total_cost": float(total_cost),
                "date_range": f"{start_date} → {end_date}",
            }
            logger.info("env_cost_sync_completed", **result)
            return result

        except Exception as exc:
            sync_record.status = "failed"
            sync_record.completed_at = datetime.utcnow()
            sync_record.error_message = str(exc)[:500]
            await self._db.commit()
            logger.error("env_cost_sync_failed", error=str(exc)[:300])
            raise

    async def get_daily_cost_table(
        self,
        days: int = DEFAULT_SYNC_DAYS,
    ) -> dict:
        """Return Prod and Non-Prod daily cost tables from the DB cache.

        Response shape:
        {
          "prod": { "title": "...", "environments": [...], "dates": [...],
                    "date_labels": [...], "data": { env: { date_str: cost } },
                    "row_totals": { env: total }, "col_totals": { date_str: total },
                    "grand_total": ... },
          "nonprod": { ... same shape ... },
          "sync_status": { ... },
          "generated_at": "..."
        }
        """
        end_date = date.today()
        start_date = end_date - timedelta(days=days - 1)

        rows = (
            (
                await self._db.execute(
                    select(EnvDailyCost)
                    .where(
                        EnvDailyCost.cost_date >= datetime.combine(start_date, datetime.min.time()),
                        EnvDailyCost.cost_date <= datetime.combine(end_date, datetime.min.time()),
                    )
                    .order_by(EnvDailyCost.cost_date)
                )
            )
            .scalars()
            .all()
        )

        # Build tables
        prod_data: dict[str, dict[str, float]] = {}
        nonprod_data: dict[str, dict[str, float]] = {}

        all_dates: set[str] = set()

        for row in rows:
            cost_d = row.cost_date.strftime("%Y-%m-%d") if isinstance(row.cost_date, datetime) else str(row.cost_date)
            all_dates.add(cost_d)
            target = prod_data if row.subscription_type == "prod" else nonprod_data
            target.setdefault(row.environment, {})
            target[row.environment][cost_d] = target[row.environment].get(cost_d, 0.0) + row.cost_amount

        # Sorted dates
        dates_sorted = sorted(all_dates)

        # Day-of-week labels (array, same order as dates_sorted)
        date_labels: list[str] = []
        for ds in dates_sorted:
            dt = datetime.strptime(ds, "%Y-%m-%d")
            day_name = dt.strftime("%a")
            date_labels.append(f"{day_name} {ds}")

        def _build_table(
            data: dict[str, dict[str, float]],
            title: str,
            env_order: list[str],
        ) -> dict:
            # Only include envs with data + keep order
            envs_with_data = [e for e in env_order if e in data]
            # Add any extra envs not in known order
            for e in sorted(data.keys()):
                if e not in envs_with_data:
                    envs_with_data.append(e)

            # Build 2-D data matrix: data_matrix[envIdx][dateIdx] = cost
            data_matrix: list[list[float]] = []
            row_totals_list: list[float] = []
            col_totals_list: list[float] = [0.0] * len(dates_sorted)

            for env in envs_with_data:
                row: list[float] = []
                row_total = 0.0
                for col_idx, ds in enumerate(dates_sorted):
                    val = round(data.get(env, {}).get(ds, 0.0), 2)
                    row.append(val)
                    row_total += val
                    col_totals_list[col_idx] += val
                data_matrix.append(row)
                row_totals_list.append(round(row_total, 2))

            col_totals_list = [round(v, 2) for v in col_totals_list]
            grand_total = round(sum(row_totals_list), 2)

            return {
                "title": title,
                "environments": envs_with_data,
                "dates": dates_sorted,
                "date_labels": date_labels,
                "data": data_matrix,
                "row_totals": row_totals_list,
                "col_totals": col_totals_list,
                "grand_total": grand_total,
            }

        prod_table = _build_table(
            prod_data,
            "ATTCC Azure Prod Cost Details",
            ["PROD", "DR", "SHARED", "MISC"],
        )
        nonprod_table = _build_table(
            nonprod_data,
            "ATTCC Azure Non-Prod Cost Details",
            ["DEV", "PERF", "UAT", "STAGING", "POC", "TEST", "SHARED", "MISC"],
        )

        # Last sync status
        sync_result = await self._db.execute(
            select(EnvCostSyncStatus).order_by(EnvCostSyncStatus.started_at.desc()).limit(1)
        )
        last_sync = sync_result.scalars().first()
        sync_info = None
        if last_sync:
            sync_info = {
                "last_sync": (
                    last_sync.completed_at.isoformat()
                    if last_sync.completed_at
                    else (last_sync.started_at.isoformat() if last_sync.started_at else None)
                ),
                "status": last_sync.status,
                "triggered_by": last_sync.triggered_by,
                "days_synced": last_sync.days_synced,
                "environments_synced": last_sync.environments_synced,
            }
        else:
            sync_info = {
                "last_sync": None,
                "status": None,
                "triggered_by": None,
                "days_synced": None,
                "environments_synced": None,
            }

        return {
            "prod": prod_table,
            "nonprod": nonprod_table,
            "sync_status": sync_info,
            "date_range": {
                "start": start_date.isoformat(),
                "end": end_date.isoformat(),
                "days": days,
            },
            "generated_at": datetime.utcnow().isoformat(),
        }
