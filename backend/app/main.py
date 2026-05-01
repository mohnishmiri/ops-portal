"""
OpsPortal — Infrastructure & Cost Intelligence Portal — Main Application Entry Point.

Production-grade FastAPI application with plugin-based architecture,
Azure AD authentication, RBAC authorization, and multi-subscription
cost management capabilities.
"""

import asyncio
import traceback
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from prometheus_client import make_asgi_app

from app.api.v1.router import api_router
from app.core.config import settings
from app.core.database import close_db, init_db
from app.core.db_cache import cache_manager
from app.core.logging import setup_logging
from app.middleware.audit import AuditLogMiddleware
from app.middleware.dynamic_cors import DynamicCORSMiddleware
from app.middleware.rate_limit import RateLimitMiddleware
from app.plugins import plugin_registry
from app.services.data_cache_service import data_cache

logger = structlog.get_logger(__name__)


async def _claim_startup_task_lock(task_name: str, ttl_seconds: int = 300) -> bool:
    """Claim a short-lived DB lock so only one worker launches a startup task."""
    from datetime import datetime, timedelta

    from sqlalchemy import delete as _del
    from sqlalchemy import select as _sel

    from app.core.database import _SessionLocal
    from app.models.database import StartupTaskLock

    if _SessionLocal is None:
        return True  # DB not ready — allow the task to proceed

    try:
        async with _SessionLocal() as session:
            now = datetime.utcnow()
            # Clean up expired locks first
            await session.execute(_del(StartupTaskLock).where(StartupTaskLock.expires_at < now))
            # Try to find an existing valid lock
            result = await session.execute(
                _sel(StartupTaskLock).where(
                    StartupTaskLock.task_name == task_name,
                    StartupTaskLock.expires_at >= now,
                )
            )
            existing = result.scalars().first()
            if existing:
                await session.commit()
                logger.info("startup_task_lock_skipped", task=task_name, reason="already_claimed")
                return False

            # Insert new lock
            session.add(
                StartupTaskLock(
                    task_name=task_name,
                    locked_at=now,
                    expires_at=now + timedelta(seconds=ttl_seconds),
                )
            )
            await session.commit()
            logger.info("startup_task_lock_acquired", task=task_name, ttl_seconds=ttl_seconds)
            return True
    except Exception as exc:
        logger.warning(
            "startup_task_lock_check_failed",
            task=task_name,
            error=str(exc)[:200],
        )
        return True


async def _startup_keyvault_sync() -> None:
    """Run initial KeyVault sync in background on startup."""
    try:
        # Small delay to let the app fully start
        await asyncio.sleep(5)
        from app.core.database import get_db_session
        from app.services.keyvault_sync_service import KeyVaultSyncService

        async for db in get_db_session():
            sync_svc = KeyVaultSyncService(db)
            result = await sync_svc.full_sync(triggered_by="startup")
            logger.info(
                "keyvault_startup_sync_completed",
                vaults=result.get("vaults_synced", 0),
                secrets=result.get("secrets_synced", 0),
                keys=result.get("keys_synced", 0),
                certs=result.get("certificates_synced", 0),
                failed=result.get("vaults_failed", 0),
            )
    except Exception as exc:
        logger.error("keyvault_startup_sync_failed", error=str(exc)[:300])


async def _startup_amortized_cost_sync() -> None:
    """Run initial amortized cost sync (Azure Cost API -> DB) in background on startup."""
    try:
        await asyncio.sleep(12)  # Slight delay after other syncs
        from app.core.database import get_db_session
        from app.services.amortized_cost_sync_service import AmortizedCostSyncService

        async for db in get_db_session():
            sync_svc = AmortizedCostSyncService(db)
            if not await sync_svc.is_data_stale():
                logger.info(
                    "amortized_cost_startup_sync_skipped",
                    reason="data_fresh",
                )
                break
            if await sync_svc.is_sync_running():
                logger.info(
                    "amortized_cost_startup_sync_skipped",
                    reason="sync_already_running",
                )
                break
            result = await sync_svc.full_sync(months=2, triggered_by="startup")
            logger.info(
                "amortized_cost_startup_sync_completed",
                months=result.get("months_synced", 0),
                rows=result.get("rows_synced", 0),
                total_cost=result.get("total_cost", 0),
            )
    except Exception as exc:
        logger.error("amortized_cost_startup_sync_failed", error=str(exc)[:300])


async def _startup_leadership_sync() -> None:
    """Run initial leadership dashboard sync in background on startup."""
    try:
        await asyncio.sleep(3)
        from app.core.database import get_db_session
        from app.services.leadership_sync_service import LeadershipSyncService

        async for db in get_db_session():
            sync_svc = LeadershipSyncService(db)
            result = await sync_svc.ensure_fresh_data(triggered_by="startup")
            logger.info(
                "leadership_startup_sync_completed",
                status=result.get("status", "unknown"),
            )
    except Exception as exc:
        logger.error("leadership_startup_sync_failed", error=str(exc)[:300])


async def _startup_compliance_sync() -> None:
    """Run initial compliance dashboard sync in background on startup."""
    try:
        await asyncio.sleep(8)
        from app.core.database import get_db_session
        from app.services.compliance_sync_service import ComplianceSyncService

        async for db in get_db_session():
            sync_svc = ComplianceSyncService(db)
            result = await sync_svc.ensure_fresh_data(triggered_by="startup")
            logger.info(
                "compliance_startup_sync_completed",
                status=result.get("status", "unknown"),
            )
    except Exception as exc:
        logger.error("compliance_startup_sync_failed", error=str(exc)[:300])


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan: startup and shutdown events."""
    setup_logging()
    logger.info("Starting OpsPortal", version=settings.APP_VERSION)

    # Initialize database
    await init_db()

    # Seed canonical module/page resources + default role permissions
    try:
        from app.core.database import get_db_session
        from app.core.resource_registry import seed_permissions, seed_resources

        async for db in get_db_session():
            await seed_resources(db)
            await seed_permissions(db)
    except Exception as exc:
        logger.warning("resource_seed_failed", error=str(exc)[:300])

    # When running tests, skip non-essential background startup tasks
    skip_background = settings.ENVIRONMENT == "test"

    # Clean up expired cache entries from the DB page_cache table
    try:
        expired = await cache_manager.cleanup_expired()
        if expired:
            logger.info("expired_cache_entries_cleaned", count=expired)
    except Exception as exc:
        logger.warning("cache_cleanup_failed", error=str(exc)[:200])

    # Discover and register plugins
    await plugin_registry.discover_and_register(application)
    logger.info(
        "Plugins registered",
        count=len(plugin_registry.plugins),
        names=list(plugin_registry.plugins.keys()),
    )

    # Warm cache — pre-populate cluster inventory (non-blocking, best-effort)
    try:
        if not skip_background:
            from app.services.aks_operations_service import get_aks_operations_service

            svc = get_aks_operations_service(db_session=None)
            warm_result = await data_cache.warm_cache(svc._fetch_clusters_live)
            logger.info("cache_warm_complete", **warm_result)
    except Exception as exc:
        logger.warning("cache_warm_skipped", error=str(exc)[:200])

    # Start background alert scheduler (non-blocking, best-effort)
    try:
        if not skip_background:
            from app.services.scheduler_service import start_scheduler

            await start_scheduler()
            logger.info("alert_scheduler_started")
    except Exception as exc:
        logger.warning("alert_scheduler_start_failed", error=str(exc)[:200])

    # Auto-sync KeyVault data on startup if DB is empty or stale
    try:
        if not skip_background:
            from app.core.database import get_db_session
            from app.services.keyvault_sync_service import KeyVaultSyncService

            async for db in get_db_session():
                sync_svc = KeyVaultSyncService(db)
                if await sync_svc.is_data_stale():
                    logger.info("keyvault_startup_sync_triggered", reason="data_stale_or_missing")
                    # Run in background task so startup isn't blocked
                    asyncio.create_task(_startup_keyvault_sync())
                else:
                    logger.info("keyvault_startup_sync_skipped", reason="data_fresh")
    except Exception as exc:
        logger.warning("keyvault_startup_check_failed", error=str(exc)[:200])

    # Auto-sync amortized cost data on startup if DB is empty or stale
    try:
        if not skip_background:
            from app.core.database import get_db_session
            from app.services.amortized_cost_sync_service import AmortizedCostSyncService

            async for db in get_db_session():
                sync_svc = AmortizedCostSyncService(db)
                if await sync_svc.is_data_stale():
                    if await _claim_startup_task_lock("amortized-cost"):
                        logger.info(
                            "amortized_cost_startup_sync_triggered",
                            reason="data_stale_or_missing",
                        )
                        asyncio.create_task(_startup_amortized_cost_sync())
                    else:
                        logger.info(
                            "amortized_cost_startup_sync_skipped",
                            reason="startup_lock_already_claimed",
                        )
                else:
                    logger.info("amortized_cost_startup_sync_skipped", reason="data_fresh")
    except Exception as exc:
        logger.warning("amortized_cost_startup_check_failed", error=str(exc)[:200])

    # Auto-sync leadership dashboard data on startup if DB is empty or stale
    try:
        if not skip_background:
            from app.core.database import get_db_session
            from app.services.leadership_sync_service import LeadershipSyncService

            async for db in get_db_session():
                sync_svc = LeadershipSyncService(db)
                if await sync_svc.is_data_stale():
                    logger.info("leadership_startup_sync_triggered", reason="data_stale_or_missing")
                    asyncio.create_task(_startup_leadership_sync())
                else:
                    logger.info("leadership_startup_sync_skipped", reason="data_fresh")
    except Exception as exc:
        logger.warning("leadership_startup_check_failed", error=str(exc)[:200])

    # Auto-sync compliance dashboard data on startup if DB is empty or stale
    try:
        if not skip_background:
            from app.core.database import get_db_session
            from app.services.compliance_sync_service import ComplianceSyncService

            async for db in get_db_session():
                sync_svc = ComplianceSyncService(db)
                if await sync_svc.is_data_stale():
                    if await _claim_startup_task_lock("compliance-dashboard"):
                        logger.info(
                            "compliance_startup_sync_triggered",
                            reason="data_stale_or_missing",
                        )
                        asyncio.create_task(_startup_compliance_sync())
                    else:
                        logger.info(
                            "compliance_startup_sync_skipped",
                            reason="startup_lock_already_claimed",
                        )
                else:
                    logger.info("compliance_startup_sync_skipped", reason="data_fresh")
    except Exception as exc:
        logger.warning("compliance_startup_check_failed", error=str(exc)[:200])

    # ── Clean up any previously auto-seeded schedules ───────────────────
    # Only user-created schedules should remain.  Auto-seeded entries
    # (created_by == "system-auto-seed") are removed on every startup so
    # they never reappear even after a redeployment.
    try:
        from sqlalchemy import delete as _del

        from app.core.database import get_db_session
        from app.models.database import AlertScheduleConfig, ChecksumScheduleConfig

        async for db in get_db_session():
            cs_result = await db.execute(
                _del(ChecksumScheduleConfig).where(ChecksumScheduleConfig.created_by == "system-auto-seed")
            )
            as_result = await db.execute(
                _del(AlertScheduleConfig).where(AlertScheduleConfig.created_by == "system-auto-seed")
            )
            total_removed = (cs_result.rowcount or 0) + (as_result.rowcount or 0)
            if total_removed:
                await db.commit()
                logger.info("auto_seeded_schedules_removed", count=total_removed)
    except Exception as exc:
        logger.warning("auto_seed_cleanup_failed", error=str(exc)[:200])

    # Seed in-memory rate limit override from the DB admin config.
    try:
        from sqlalchemy import select as _sel

        from app.core.database import get_db_session
        from app.middleware.rate_limit import set_rate_limit_override
        from app.models.database import AdminConfig

        async for db in get_db_session():
            result = await db.execute(_sel(AdminConfig).where(AdminConfig.config_key == "rate_limit_rpm"))
            row = result.scalar_one_or_none()
            if row and row.config_value:
                set_rate_limit_override(int(row.config_value))
                logger.info("rate_limit_override_seeded", rpm=row.config_value)
    except Exception as exc:
        logger.warning("rate_limit_seed_failed", error=str(exc)[:200])

    yield

    # Shutdown scheduler
    try:
        from app.services.scheduler_service import stop_scheduler

        await stop_scheduler()
        logger.info("alert_scheduler_stopped")
    except Exception as exc:
        logger.warning("alert_scheduler_stop_failed", error=str(exc)[:200])

    # Shutdown
    await close_db()
    logger.info("OpsPortal shutdown complete")


def create_application() -> FastAPI:
    """Application factory."""
    application = FastAPI(
        title="OpsPortal — Infrastructure & Cost Intelligence",
        description=(
            "Production-grade operations portal providing multi-subscription "
            "Azure cost visibility, infrastructure management, optimization "
            "recommendations, and leadership-ready dashboards."
        ),
        version=settings.APP_VERSION,
        docs_url="/api/docs" if settings.ENVIRONMENT != "production" else None,
        redoc_url="/api/redoc" if settings.ENVIRONMENT != "production" else None,
        lifespan=lifespan,
    )

    # CORS
    application.add_middleware(
        DynamicCORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Custom middleware
    application.add_middleware(AuditLogMiddleware)
    application.add_middleware(RateLimitMiddleware, requests_per_minute=settings.RATE_LIMIT_RPM)

    # Prometheus metrics endpoint
    metrics_app = make_asgi_app()
    application.mount("/metrics", metrics_app)

    # Core API router
    application.include_router(api_router, prefix="/api/v1")

    # Global exception handler — catches ALL unhandled errors and logs via structlog
    @application.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        tb = traceback.format_exception(type(exc), exc, exc.__traceback__)
        logger.error(
            "unhandled_exception",
            path=request.url.path,
            method=request.method,
            error=str(exc),
            error_type=type(exc).__name__,
            traceback="".join(tb),
        )
        return JSONResponse(
            status_code=500,
            content={"detail": f"Internal Server Error: {type(exc).__name__}: {str(exc)}"},
        )

    # Health check
    @application.get("/healthz", tags=["health"])
    async def health_check() -> dict[str, str]:
        return {"status": "healthy", "version": settings.APP_VERSION}

    @application.get("/readyz", tags=["health"])
    async def readiness_check() -> dict[str, str]:
        cache_ok = await cache_manager.ping()
        return {
            "status": "ready" if cache_ok else "degraded",
            "cache": "connected" if cache_ok else "disconnected",
        }

    return application


def get_app() -> FastAPI:
    """Lazy app factory for uvicorn."""
    return create_application()


def create_app() -> FastAPI:
    """Backward-compatible app factory for tests and older imports."""
    return create_application()


app = get_app()
