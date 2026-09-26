"""Standalone ASGI factory for reviewing non-production design concepts."""

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from migration_intake.web.routes.design_options import router


def create_design_preview_app() -> FastAPI:
    """Create the dependency-free design preview application."""
    app = FastAPI(
        title="Migration Intake Design Lab",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.include_router(router)
    static_dir = Path(__file__).parent / "static"
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")
    return app
