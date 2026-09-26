"""
Application entry point and composition root.

This module creates the FastAPI application with all dependencies wired.
It is the only location that:
- Loads and validates configuration
- Creates database engine and session factory
- Selects concrete adapter implementations
- Registers routes and exception handlers

Routes should not inspect environment variables or instantiate adapters.

Usage:
    # Development server (module-level `app` is intentionally None so tests
    # can control settings before creation; use the `get_app` factory instead)
    uvicorn migration_intake.main:get_app --factory --reload

    # Or via the CLI entry point
    migration-intake
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import TYPE_CHECKING

from fastapi import FastAPI
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from migration_intake import __version__
from migration_intake.application.services.answers import AnswerService
from migration_intake.catalog.bootstrap import ensure_catalog_published
from migration_intake.config import Settings
from migration_intake.persistence.database import (
    configure_oracle_client,
    create_engine_from_url,
    create_session_factory,
)
from migration_intake.web.health import liveness, readiness
from migration_intake.web.routes import (
    applications,
    catalog_admin,
    catalog_admin_publish,
    evidence,
    gap_workbook,
    intake_hub,
    interfaces,
    legacy_intake,
    questionnaire,
    template_admin,
    template_admin_publish,
    topology,
    wave_util,
)
from migration_intake.web.routes import readiness as readiness_routes

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

logger = logging.getLogger(__name__)


def configure_logging(settings: Settings) -> None:
    """
    Configure application logging based on settings.

    Sets up structured logging for shared environments and
    human-readable logging for local development.
    """
    log_level = getattr(logging, settings.log_level.upper(), logging.INFO)

    if settings.log_format == "json":
        # Structured JSON logging for shared/production
        logging.basicConfig(
            level=log_level,
            format='{"time":"%(asctime)s","level":"%(levelname)s","logger":"%(name)s","message":"%(message)s"}',
        )
    else:
        # Human-readable for local development
        logging.basicConfig(
            level=log_level,
            format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        )


def create_app(settings: Settings | None = None) -> FastAPI:
    """
    Create and configure the FastAPI application.

    This is the composition root that wires all dependencies.

    Creates a SQLAlchemy engine from the effective database URL and stores it
    in app.state.engine so that health probes and future route dependencies
    can access it without re-reading environment variables.

    SQLite engines receive connect_args={"check_same_thread": False} so that
    the TestClient (which runs in a separate thread) can safely share the
    engine with the async handler thread.

    Args:
        settings: Optional settings instance. If not provided,
                  settings are loaded from environment variables.

    Returns:
        Configured FastAPI application instance.
    """
    if settings is None:
        settings = Settings()

    configure_logging(settings)
    configure_oracle_client(settings.oracle_client_lib_dir)

    # Create the SQLAlchemy engine.  Engine creation is lazy (no connection is
    # established here), so this is safe even if the database does not yet exist.
    db_url = settings.effective_database_url
    engine_kwargs: dict[str, object] = {}

    if db_url.startswith("sqlite"):
        # Allow the engine to be used across threads (required by TestClient and
        # any sync-in-async usage patterns that rely on a thread-pool executor).
        engine_kwargs["connect_args"] = {"check_same_thread": False}
    else:
        # Apply pool settings for non-SQLite databases (Oracle, PostgreSQL)
        engine_kwargs["pool_size"] = settings.db_pool_size
        engine_kwargs["max_overflow"] = settings.db_max_overflow
        engine_kwargs["pool_recycle"] = settings.db_pool_recycle_seconds
        # Network databases (VPN/corporate links) can silently drop pooled
        # connections; pre_ping validates before use instead of surfacing a 500.
        engine_kwargs["pool_pre_ping"] = True

    # Apply SQL echo setting (useful for debugging)
    engine_kwargs["echo"] = settings.sql_echo

    engine = create_engine_from_url(db_url, **engine_kwargs)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
        """Application lifespan handler for startup/shutdown."""
        logger.info(
            "Starting Migration Intake application",
            extra={
                "version": __version__,
                "environment": settings.app_env,
                "database": settings.redacted_database_url(),
            },
        )
        ensure_catalog_published(session_factory)
        yield
        logger.info("Shutting down Migration Intake application")
        # Dispose of the engine to close all connections
        engine.dispose()
        logger.info("Database engine disposed")

    app = FastAPI(
        title="Migration Intake",
        description="AWS Outposts Migration Intake Application",
        version=__version__,
        lifespan=lifespan,
        docs_url="/docs" if settings.app_env in ("local", "test") else None,
        redoc_url="/redoc" if settings.app_env in ("local", "test") else None,
    )

    # Create session factory
    session_factory = create_session_factory(engine)

    # Create services
    answer_service = AnswerService(session_factory)

    # Store settings, engine, session factory, and services in app state for access by route dependencies.
    # Health probes read app.state.engine and app.state.settings via Request.
    app.state.settings = settings
    app.state.engine = engine
    app.state.session_factory = session_factory
    app.state.answer_service = answer_service

    # Register health check routes (O02 — Liveness and Readiness probes).
    # Routes are added via add_api_route() rather than include_router() so
    # that app.routes contains plain APIRoute objects (each has a .path
    # attribute).  Using include_router() in Starlette 1.3+ injects an
    # _IncludedRouter marker without .path, which breaks any code that
    # iterates app.routes expecting all objects to be addressable by path.
    app.add_api_route(
        "/health/live",
        liveness,
        methods=["GET"],
        tags=["Health"],
        response_class=JSONResponse,
    )
    app.add_api_route(
        "/health/ready",
        readiness,
        methods=["GET"],
        tags=["Health"],
        response_class=JSONResponse,
    )

    # Register root redirect (UI02b)
    @app.get("/", include_in_schema=False)
    async def root_redirect() -> RedirectResponse:
        """Redirect root to applications list."""
        return RedirectResponse(url="/applications", status_code=303)

    # Register application routes (UI02)
    app.include_router(applications.router)

    # Register catalog admin upload/validate/publish routes (CAT-B3). Must be
    # registered BEFORE catalog_admin.router below: that router's
    # GET /admin/catalog/{release_id} is a wildcard that would otherwise
    # swallow GET /admin/catalog/upload (Starlette matches routes in
    # registration order, not by specificity).
    app.include_router(catalog_admin_publish.router)

    # Register catalog admin read-only viewer routes (CAT-B2)
    app.include_router(catalog_admin.router)

    # Register template admin upload/publish routes before read-only detail route.
    app.include_router(template_admin_publish.router)
    app.include_router(template_admin.router)

    app.include_router(intake_hub.router)  # Intake hub landing page (UX-2)

    # Register questionnaire routes (UI04)
    app.include_router(questionnaire.router)

    # Register evidence routes (UI05)
    app.include_router(evidence.router)

    # Register interface register routes.
    # FastAPI 0.141 with Starlette 1.6 leaves included routers as markers;
    # register these routes directly so Starlette dispatches them.
    app.router.routes.extend(interfaces.router.routes)

    # Register legacy intake routes (L03)
    app.include_router(legacy_intake.router)

    # Register WaveUtil routes (UI07)
    app.include_router(wave_util.router)

    # Register readiness and snapshot routes (UI08)
    app.include_router(readiness_routes.router)

    # Register unresolved-question workbook export routes.
    app.include_router(gap_workbook.router)

    # Register topology generation routes (T05)
    app.include_router(topology.router)

    # Mount static assets (design tokens, base/layout/component CSS, app.js).
    # Local files only — no CDN — per UI01's CSP-compatible shell contract.
    static_dir = Path(__file__).parent / "web" / "static"
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    return app


# Create the default application instance for uvicorn
# This loads settings from environment at import time only when
# running as the main ASGI application
app: FastAPI | None = None


def get_app() -> FastAPI:
    """
    Get or create the application instance.

    This factory pattern allows tests to control environment via monkeypatching
    before the app is created (unlike creating `app` at module level which
    would bind the app to environment variables before tests can intercept them).
    """
    global app
    if app is None:
        app = create_app()
    return app


def run() -> None:
    """
    Run the application using uvicorn.

    This is the entry point for the `migration-intake` CLI command.
    """
    import uvicorn

    settings = Settings()

    uvicorn.run(
        "migration_intake.main:get_app",
        factory=True,
        host="127.0.0.1",
        port=8000,
        reload=settings.app_env == "local",
        log_level=settings.log_level.lower(),
    )


if __name__ == "__main__":
    run()
