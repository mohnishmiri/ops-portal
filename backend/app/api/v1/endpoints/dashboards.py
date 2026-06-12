"""
Dashboard API Endpoints.

Provides pre-aggregated data for Leadership, Ops/Infra, and Admin dashboards,
plus the Budget vs RunRate tracking view.
"""

from time import perf_counter

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user, require_role
from app.core.admin_config import get_effective_cache_ttl_seconds
from app.core.database import get_db
from app.core.db_cache import cache_manager, refresh_cache_enabled_flag
from app.core.subscription_resolver import get_monitored_subscription_ids
from app.core.subscription_scope import get_scoped_subscription_ids
from app.models.auth import UserContext, UserRole
from app.models.cost import (
    LeadershipAdvisorRequest,
    LeadershipAdvisorResponse,
    LeadershipDashboard,
    LeadershipForecastResponse,
)
from app.services.budget_service import BudgetService
from app.services.dashboard_service import DashboardService
from app.services.leadership_advisor_service import LeadershipAdvisorService
from app.services.leadership_sync_service import (
    LEADERSHIP_DASHBOARD_CACHE_KEY,
    LeadershipSyncService,
    leadership_dashboard_cache_key,
)

router = APIRouter()
logger = structlog.get_logger(__name__)


def _get_dashboard_service() -> DashboardService:
    return DashboardService()


def _get_budget_service() -> BudgetService:
    return BudgetService()


def _get_leadership_advisor_service(
    db: AsyncSession = Depends(get_db),
) -> LeadershipAdvisorService:
    return LeadershipAdvisorService(db)


async def _leadership_scope_is_full(scoped_ids: list[str]) -> bool:
    monitored_ids = await get_monitored_subscription_ids()
    if not monitored_ids:
        return True
    return set(scoped_ids) == set(monitored_ids)


async def _cache_and_return_leadership_dashboard(
    *,
    dashboard: LeadershipDashboard,
    cache_key: str,
    db: AsyncSession | None,
    cache_enabled: bool,
    source: str,
    refresh: bool,
    started: float,
    scoped_count: int | None = None,
) -> LeadershipDashboard:
    if cache_enabled and db is not None:
        ttl = await get_effective_cache_ttl_seconds(db)
        await cache_manager.set_cached(cache_key, dashboard.model_dump_json(), ttl=ttl)
    logger.info(
        "leadership_dashboard_served",
        source=source,
        refresh=refresh,
        cache_enabled=cache_enabled,
        scoped_subscription_count=scoped_count,
        elapsed_ms=round((perf_counter() - started) * 1000, 2),
    )
    return dashboard


@router.get(
    "/leadership",
    response_model=LeadershipDashboard,
    summary="Leadership KPI dashboard",
    description=("Executive-ready dashboard with KPIs, cost trends, top spenders, and total savings opportunities."),
)
async def leadership_dashboard(
    refresh: bool = Query(default=False, description="Bypass cache and fetch fresh data"),
    user: UserContext = Depends(get_current_user),
    service: DashboardService = Depends(_get_dashboard_service),
    db: AsyncSession = Depends(get_db),
) -> LeadershipDashboard:
    """Leadership dashboard — scoped cache → scoped amortized DB → snapshot/live."""
    started = perf_counter()
    scoped_ids = await get_scoped_subscription_ids()
    full_scope = await _leadership_scope_is_full(scoped_ids)
    partial_scope_ids = None if full_scope else list(scoped_ids)
    cache_key = leadership_dashboard_cache_key(partial_scope_ids)

    cache_enabled = await refresh_cache_enabled_flag(db)

    if refresh:
        await cache_manager.invalidate(cache_key)
        if full_scope:
            await cache_manager.invalidate(LEADERSHIP_DASHBOARD_CACHE_KEY)

    if not refresh and cache_enabled:
        cached_payload = await cache_manager.get_cached(cache_key)
        if cached_payload:
            try:
                return await _cache_and_return_leadership_dashboard(
                    dashboard=LeadershipDashboard.model_validate_json(cached_payload),
                    cache_key=cache_key,
                    db=None,
                    cache_enabled=False,
                    source="cache",
                    refresh=refresh,
                    started=started,
                    scoped_count=len(scoped_ids),
                )
            except Exception:
                pass

    if db is not None:
        sync_svc = LeadershipSyncService(db)

        if partial_scope_ids:
            amortized_payload = await sync_svc.get_dashboard_from_amortized(partial_scope_ids)
            if amortized_payload:
                amortized_payload.pop("_source", None)
                amortized_payload.pop("_scope", None)
                dashboard = LeadershipDashboard.model_validate(amortized_payload)
                return await _cache_and_return_leadership_dashboard(
                    dashboard=dashboard,
                    cache_key=cache_key,
                    db=db,
                    cache_enabled=cache_enabled,
                    source="amortized_database",
                    refresh=refresh,
                    started=started,
                    scoped_count=len(partial_scope_ids),
                )

        cached = await sync_svc.get_dashboard_from_db(subscription_ids=partial_scope_ids)
        if cached:
            cached.pop("_source", None)
            cached.pop("_scope", None)
            cached.pop("_synced_at", None)
            dashboard = LeadershipDashboard.model_validate(cached)
            if not refresh and await sync_svc.is_data_stale() and not await sync_svc.is_sync_running():
                LeadershipSyncService.schedule_background_sync(triggered_by="request-stale")
            return await _cache_and_return_leadership_dashboard(
                dashboard=dashboard,
                cache_key=cache_key,
                db=db,
                cache_enabled=cache_enabled,
                source="database",
                refresh=refresh,
                started=started,
                scoped_count=len(scoped_ids),
            )

    subscription_ids = scoped_ids or user.allowed_subscriptions or None
    dashboard = await service.get_leadership_dashboard(
        subscription_ids=subscription_ids,
        refresh=refresh,
    )
    return await _cache_and_return_leadership_dashboard(
        dashboard=dashboard,
        cache_key=cache_key,
        db=db,
        cache_enabled=cache_enabled,
        source="live",
        refresh=refresh,
        started=started,
        scoped_count=len(scoped_ids),
    )


@router.get(
    "/admin",
    summary="Admin dashboard (subscriptions, users, roles)",
)
async def admin_dashboard(
    user: UserContext = Depends(require_role(UserRole.ADMIN)),
    service: DashboardService = Depends(_get_dashboard_service),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Admin dashboard — requires Admin role."""
    try:
        return await service.get_admin_dashboard(db=db)
    except Exception as exc:
        logger.warning("admin_dashboard_error", error=str(exc), error_type=type(exc).__name__)
        raise HTTPException(status_code=503, detail="Admin dashboard temporarily unavailable") from exc


@router.get(
    "/budget-runrate",
    summary="Budget vs RunRate — 2026 budget tracking per app",
    description=(
        "Returns per-application 2026 budget allocation, current run rate, variance, and budget utilization percentage."
    ),
)
async def budget_runrate(
    refresh: bool = Query(default=False, description="Bypass page cache"),
    user: UserContext = Depends(get_current_user),
    service: BudgetService = Depends(_get_budget_service),
) -> dict:
    """Budget vs RunRate comparison."""
    return await service.get_budget_runrate(refresh=refresh)


# ── Leadership Dashboard Sync ────────────────────────────────────────


@router.post(
    "/leadership/sync",
    summary="Enqueue leadership dashboard sync (prefer POST /sync-jobs)",
    description="Queues a background leadership dashboard sync. Poll GET /sync-jobs/{id}.",
    status_code=202,
)
async def trigger_leadership_sync(
    user: UserContext = Depends(require_role(UserRole.ADMIN, UserRole.WRITE)),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Enqueue a leadership dashboard sync (always full admin-monitored scope)."""
    if db is None:
        return {"error": "Database unavailable"}
    from app.services.sync_worker import enqueue_job

    # Leadership snapshots are global; per-user scope applies at read time only.
    job_id = await enqueue_job("leadership", triggered_by=user.email or "manual")
    return {"status": "queued", "job_id": job_id, "job_type": "leadership"}


@router.get(
    "/leadership/sync-status",
    summary="Leadership dashboard sync status",
)
async def get_leadership_sync_status(
    user: UserContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Get latest leadership dashboard sync status."""
    if db is None:
        return {"last_sync": None, "status": None}
    svc = LeadershipSyncService(db)
    return await svc.get_sync_status()


@router.post(
    "/leadership/advisor",
    response_model=LeadershipAdvisorResponse,
    summary="Generate AI cost advice for leadership dashboard",
    description=(
        "Builds executive guidance from the current leadership dashboard context, "
        "optimization recommendations, and optional Azure MCP enrichment."
    ),
)
async def generate_leadership_advice(
    payload: LeadershipAdvisorRequest,
    user: UserContext = Depends(get_current_user),
    service: LeadershipAdvisorService = Depends(_get_leadership_advisor_service),
) -> LeadershipAdvisorResponse:
    """Generate leadership AI advisor content through the backend proxy."""
    return await service.generate_advice(payload)


@router.post(
    "/leadership/forecast",
    response_model=LeadershipForecastResponse,
    summary="Generate AI forecast for leadership dashboard",
    description=(
        "Uses the last six months of prod and non-prod dashboard history to generate "
        "the next six months of forecast through the backend Ollama proxy."
    ),
)
async def generate_leadership_forecast(
    payload: LeadershipAdvisorRequest,
    user: UserContext = Depends(get_current_user),
    service: LeadershipAdvisorService = Depends(_get_leadership_advisor_service),
) -> LeadershipForecastResponse:
    """Generate leadership forecast content through the backend proxy."""
    return await service.generate_forecast(payload)


@router.get(
    "/leadership/ollama-status",
    summary="Check Ollama LLM connectivity and admin toggle status",
)
async def check_ollama_status(
    user: UserContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Check whether the Ollama LLM endpoint is reachable and enabled."""
    import httpx

    from app.core.admin_config import get_ollama_enabled
    from app.core.config import settings

    ollama_enabled = await get_ollama_enabled(db)
    result: dict = {
        "enabled": ollama_enabled,
        "base_url": settings.OLLAMA_BASE_URL,
        "model": settings.OLLAMA_MODEL,
        "timeout_seconds": settings.OLLAMA_TIMEOUT_SECONDS,
    }

    if not ollama_enabled:
        result["status"] = "disabled"
        result["detail"] = "Ollama LLM is disabled via Admin panel."
        return result

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(10), verify=False) as client:
            resp = await client.get(settings.OLLAMA_BASE_URL.rstrip("/") + "/api/tags")
            resp.raise_for_status()
            body = resp.json()
            models = body.get("models", [])
            result["status"] = "connected"
            result["available_models"] = [m.get("name", "unknown") for m in models[:10]]
    except Exception as exc:
        result["status"] = "unreachable"
        result["detail"] = f"{type(exc).__name__}: {str(exc)[:200]}"

    return result
