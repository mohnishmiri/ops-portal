"""
Cost Visibility & Analytics API Endpoints.

Provides multi-subscription cost data with grouping, filtering,
time-series analysis, and drill-down capabilities.
"""

from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user, require_role
from app.core.database import get_db
from app.models.auth import UserContext, UserRole
from app.models.cost import (
    CostBreakdownResponse,
    CostQueryRequest,
    CostTimeSeriesResponse,
    DateRangePreset,
    GroupByDimension,
    MultiSubscriptionOverview,
)
from app.services.amortized_cost_sync_service import AmortizedCostSyncService
from app.services.cost_service import CostService

router = APIRouter()


def _is_database_error(exc: Exception) -> bool:
    """Best-effort DB error detection to return user-friendly 503 responses."""
    if isinstance(exc, SQLAlchemyError):
        return True
    text = str(exc).lower()
    return (
        "database" in text
        or "dbapi" in text
        or "connection" in text
        or "no attribute 'execute'" in text
        or "has no attribute 'execute'" in text
    )


def _raise_database_unavailable(exc: Exception) -> None:
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="Database is down. Please try again later.",
    ) from exc


def _get_cost_service(db: AsyncSession = Depends(get_db)) -> CostService:
    return CostService(db)


@router.post(
    "/query",
    response_model=CostTimeSeriesResponse,
    summary="Query cost data with custom parameters",
    description="Flexible cost query with date range, granularity, and grouping dimensions.",
)
async def query_costs(
    request: CostQueryRequest,
    user: UserContext = Depends(get_current_user),
    service: CostService = Depends(_get_cost_service),
) -> CostTimeSeriesResponse:
    """Execute a custom cost query across subscriptions."""
    # Enforce subscription access
    subscription_ids = request.subscription_ids or user.allowed_subscriptions
    return await service.query_costs(
        subscription_ids=subscription_ids,
        start_date=request.start_date,
        end_date=request.end_date,
        granularity=request.granularity,
        group_by=request.group_by,
        resource_group_filter=request.resource_group_filter,
        resource_type_filter=request.resource_type_filter,
    )


@router.get(
    "/breakdown",
    response_model=CostBreakdownResponse,
    summary="Get cost breakdown by dimension",
)
async def get_cost_breakdown(
    dimension: GroupByDimension = Query(default=GroupByDimension.SUBSCRIPTION),
    preset: DateRangePreset = Query(default=DateRangePreset.CURRENT_MONTH),
    subscription_id: str | None = Query(default=None),
    user: UserContext = Depends(get_current_user),
    service: CostService = Depends(_get_cost_service),
) -> CostBreakdownResponse:
    """Get cost breakdown grouped by a specified dimension."""
    start_date, end_date = _resolve_preset(preset)
    subs = [subscription_id] if subscription_id else user.allowed_subscriptions or None
    return await service.get_cost_breakdown(
        subscription_ids=subs,
        dimension=dimension,
        start_date=start_date,
        end_date=end_date,
    )


@router.get(
    "/subscriptions/overview",
    response_model=MultiSubscriptionOverview,
    summary="Multi-subscription cost overview",
)
async def get_subscription_overview(
    user: UserContext = Depends(get_current_user),
    service: CostService = Depends(_get_cost_service),
) -> MultiSubscriptionOverview:
    """Get cost overview across all accessible subscriptions."""
    return await service.get_multi_subscription_overview(
        subscription_ids=user.allowed_subscriptions or None,
    )


@router.get(
    "/daily",
    response_model=CostTimeSeriesResponse,
    summary="Daily cost trend",
)
async def get_daily_costs(
    days: int = Query(default=30, ge=1, le=365),
    subscription_id: str | None = Query(default=None),
    user: UserContext = Depends(get_current_user),
    service: CostService = Depends(_get_cost_service),
) -> CostTimeSeriesResponse:
    """Get daily cost data for the specified number of days."""
    end_date = date.today()
    start_date = end_date - timedelta(days=days)
    subs = [subscription_id] if subscription_id else None
    return await service.query_costs(
        subscription_ids=subs,
        start_date=start_date,
        end_date=end_date,
    )


@router.get(
    "/nonprod-vs-prod",
    summary="Monthly cost trend: Non-Prod vs Prod",
    description="Returns monthly aggregates showing Non-Prod and Prod costs side by side.",
)
async def get_nonprod_vs_prod(
    months: int = Query(default=6, ge=1, le=12, description="Number of months to include"),
    user: UserContext = Depends(get_current_user),
    service: CostService = Depends(_get_cost_service),
) -> dict:
    """Monthly Non-Prod vs Prod cost comparison."""
    return await service.get_nonprod_vs_prod_trend(num_months=months)


@router.get(
    "/env-breakdown",
    summary="Environment-wise cost breakdown by service type",
    description=(
        "Returns a pivot-table of monthly cost by MeterCategory for a specific environment (PROD, DEV, PERF, DR, ALL)."
    ),
)
async def get_env_cost_breakdown(
    environment: str = Query(default="PROD", description="Environment name (PROD, DEV, PERF, DR, ALL)"),
    months: int = Query(default=3, ge=1, le=12, description="Number of months to include"),
    user: UserContext = Depends(get_current_user),
    service: CostService = Depends(_get_cost_service),
) -> dict:
    """Environment-wise cost details — rows = service types, columns = months."""
    return await service.get_env_cost_details(
        environment=environment,
        num_months=months,
    )


@router.get(
    "/monthly",
    response_model=CostTimeSeriesResponse,
    summary="Monthly cost trend",
)
async def get_monthly_costs(
    months: int = Query(default=12, ge=1, le=36),
    user: UserContext = Depends(get_current_user),
    service: CostService = Depends(_get_cost_service),
) -> CostTimeSeriesResponse:
    """Get monthly cost data for the specified number of months."""
    from app.models.cost import TimeGranularity

    end_date = date.today()
    start_date = end_date - timedelta(days=months * 30)
    return await service.query_costs(
        subscription_ids=None,
        start_date=start_date,
        end_date=end_date,
        granularity=TimeGranularity.MONTHLY,
    )


def _resolve_preset(preset: DateRangePreset) -> tuple[date, date]:
    """Resolve a date range preset to concrete start/end dates."""
    today = date.today()
    match preset:
        case DateRangePreset.LAST_7_DAYS:
            return today - timedelta(days=7), today
        case DateRangePreset.LAST_30_DAYS:
            return today - timedelta(days=30), today
        case DateRangePreset.CURRENT_MONTH:
            return today.replace(day=1), today
        case DateRangePreset.LAST_MONTH:
            first_of_month = today.replace(day=1)
            last_month_end = first_of_month - timedelta(days=1)
            last_month_start = last_month_end.replace(day=1)
            return last_month_start, last_month_end
        case DateRangePreset.LAST_3_MONTHS:
            return today - timedelta(days=90), today
        case DateRangePreset.LAST_6_MONTHS:
            return today - timedelta(days=180), today
        case DateRangePreset.LAST_12_MONTHS:
            return today - timedelta(days=365), today
        case DateRangePreset.YEAR_TO_DATE:
            return date(today.year, 1, 1), today


# ── Amortized Cost (DB-synced from Azure Cost Management API) ─────────


@router.get(
    "/amortized-summary",
    summary="Amortized cost summary (DB-cached)",
    description=(
        "Returns a comprehensive analytics payload built from amortized "
        "cost data stored in PostgreSQL. Data is auto-synced from "
        "Azure Cost Management API queries. Use refresh=true to trigger "
        "a background sync without blocking."
    ),
)
async def get_amortized_summary(
    env: str = Query(default="ALL", description="PROD, NONPROD, or ALL"),
    months: int = Query(default=2, ge=1, le=12, description="Number of months of data to load (1-12)"),
    refresh: bool = Query(default=False, description="Schedule background re-sync from Azure (non-blocking)"),
    user: UserContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Comprehensive amortized cost analytics from DB cache."""
    if db is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database is down. Please try again later.",
        )
    svc = AmortizedCostSyncService(db)
    try:
        if refresh:
            # Schedule background sync instead of waiting for it
            AmortizedCostSyncService.schedule_background_sync(
                months=months,
                triggered_by="manual_refresh",
            )
        elif await svc.is_data_stale() and not await svc.is_sync_running():
            # Auto-sync if data is stale and no sync is already running
            AmortizedCostSyncService.schedule_background_sync(
                months=months,
                triggered_by="request-stale",
            )
        return await svc.get_amortized_cost_data(env=env, months=months)
    except Exception as exc:
        if _is_database_error(exc):
            _raise_database_unavailable(exc)
        raise


@router.get(
    "/amortized-drilldown",
    summary="Amortized cost resource drill-down (DB-cached)",
    description=(
        "Drill into individual resources from the DB-cached amortized "
        "cost data, optionally filtered by resource group, service, "
        "or subscription."
    ),
)
async def get_amortized_drilldown(
    env: str = Query(default="ALL", description="PROD, NONPROD, or ALL"),
    months: int = Query(default=2, ge=1, le=12, description="Number of months of data to load (1-12)"),
    resource_group: str | None = Query(default=None, description="Filter by resource group"),
    meter_category: str | None = Query(default=None, description="Filter by service/meter category"),
    subscription: str | None = Query(default=None, description="Filter by subscription name or id"),
    user: UserContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Resource-level drill-down served directly from the DB."""
    if db is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database is down. Please try again later.",
        )
    svc = AmortizedCostSyncService(db)
    try:
        return await svc.get_resource_drilldown(
            env=env,
            months=months,
            resource_group=resource_group,
            meter_category=meter_category,
            subscription=subscription,
        )
    except Exception as exc:
        if _is_database_error(exc):
            _raise_database_unavailable(exc)
        raise


@router.post(
    "/amortized/sync",
    summary="Enqueue amortized cost sync (prefer POST /sync-jobs)",
    description=(
        "Queues a background amortized cost sync. Poll GET /sync-jobs/{id} "
        "or use POST /sync-jobs directly. Normal mode is incremental; "
        "force=true wipes and re-fetches the selected month window."
    ),
    status_code=status.HTTP_202_ACCEPTED,
)
async def trigger_amortized_cost_sync(
    months: int = Query(default=2, ge=1, le=12, description="Number of months to sync"),
    force: bool = Query(default=False, description="Wipe and re-fetch all months (repairs stale resource_type values)"),
    user: UserContext = Depends(require_role(UserRole.ADMIN, UserRole.WRITE)),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Enqueue amortized cost sync and return the job id."""
    if db is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database unavailable",
        )
    from app.services.sync_worker import enqueue_job

    try:
        job_id = await enqueue_job(
            "amortized",
            payload={"months": months, "force": force},
            triggered_by=user.email or "manual",
        )
        return {"status": "queued", "job_id": job_id, "job_type": "amortized"}
    except Exception as exc:
        if _is_database_error(exc):
            _raise_database_unavailable(exc)
        raise


@router.get(
    "/amortized/sync-status",
    summary="Amortized cost sync status",
    description="Returns latest sync status for the amortized cost data.",
)
async def get_amortized_sync_status(
    user: UserContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Get latest amortized cost sync status."""
    if db is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database is down. Please try again later.",
        )
    svc = AmortizedCostSyncService(db)
    try:
        return await svc.get_sync_status()
    except Exception as exc:
        if _is_database_error(exc):
            _raise_database_unavailable(exc)
        raise
