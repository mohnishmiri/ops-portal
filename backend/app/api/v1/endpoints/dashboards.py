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
    """Leadership dashboard — loads from cache → DB → live Azure API."""
    started = perf_counter()

    # Refresh the admin cache-enabled flag so the toggle takes effect
    cache_enabled = await refresh_cache_enabled_flag(db)

    if refresh:
        await cache_manager.invalidate(LEADERSHIP_DASHBOARD_CACHE_KEY)

    # 1) Try cache (unless refresh requested or cache disabled via admin)
    if not refresh and cache_enabled:
        cached_payload = await cache_manager.get_cached(LEADERSHIP_DASHBOARD_CACHE_KEY)
        if cached_payload:
            try:
                dashboard = LeadershipDashboard.model_validate_json(cached_payload)
                logger.info(
                    "leadership_dashboard_served",
                    source="cache",
                    refresh=refresh,
                    elapsed_ms=round((perf_counter() - started) * 1000, 2),
                )
                return dashboard
            except Exception:
                pass

    # 2) Try DB — always attempt DB even during refresh so that the
    #    just-completed sync result is served instead of a redundant
    #    live Azure call.
    if db is not None:
        sync_svc = LeadershipSyncService(db)
        cached = await sync_svc.get_dashboard_from_db()
        if cached:
            dashboard = LeadershipDashboard.model_validate(cached)
            if cache_enabled:
                ttl = await get_effective_cache_ttl_seconds(db)
                await cache_manager.set_cached(
                    LEADERSHIP_DASHBOARD_CACHE_KEY,
                    dashboard.model_dump_json(),
                    ttl=ttl,
                )
            if not refresh and await sync_svc.is_data_stale() and not await sync_svc.is_sync_running():
                LeadershipSyncService.schedule_background_sync(triggered_by="request-stale")
            logger.info(
                "leadership_dashboard_served",
                source="database",
                refresh=refresh,
                cache_enabled=cache_enabled,
                elapsed_ms=round((perf_counter() - started) * 1000, 2),
            )
            return dashboard

    # 3) Fall back to live Azure API
    dashboard = await service.get_leadership_dashboard(
        subscription_ids=user.allowed_subscriptions or None,
        refresh=refresh,
    )
    if cache_enabled:
        ttl = await get_effective_cache_ttl_seconds(db)
        await cache_manager.set_cached(
            LEADERSHIP_DASHBOARD_CACHE_KEY,
            dashboard.model_dump_json(),
            ttl=ttl,
        )
    logger.info(
        "leadership_dashboard_served",
        source="live",
        refresh=refresh,
        cache_enabled=cache_enabled,
        elapsed_ms=round((perf_counter() - started) * 1000, 2),
    )
    return dashboard


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
    """Enqueue a leadership dashboard sync."""
    if db is None:
        return {"error": "Database unavailable"}
    from app.services.sync_worker import enqueue_job

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
