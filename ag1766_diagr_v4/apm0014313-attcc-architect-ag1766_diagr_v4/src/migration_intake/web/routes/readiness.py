"""
Readiness and snapshot routes — UI08 / UX-4b.

Provides:
- GET /intakes/{intake_id}/readiness - Check readiness status
- POST /intakes/{intake_id}/freeze - Freeze intake and create snapshot
- GET /intakes/{intake_id}/snapshot - View snapshot details
- GET /intakes/{intake_id}/export - Export canonical package
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from migration_intake.application.dto import ActorContext
from migration_intake.application.services.export import ExportService
from migration_intake.application.services.readiness import ReadinessService
from migration_intake.application.services.snapshots import (
    IntakeNotReadyError,
    SnapshotService,
)
from migration_intake.persistence.models import Application, Intake
from migration_intake.web.routes._nav import app_nav_items
from migration_intake.web.security import (
    CONFIGURED_ACTOR_CAPABILITIES,
    generate_csrf_token,
    validate_csrf_token,
)

router = APIRouter(prefix="/intakes/{intake_id}", tags=["readiness"])

# Template setup
_TEMPLATES_DIR = Path(__file__).parent.parent / "templates"
_templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))


def get_session_factory(request: Request) -> sessionmaker:
    """Get session factory from app state."""
    return request.app.state.session_factory


def get_actor_context(request: Request) -> ActorContext:
    """Get actor context from app settings."""
    settings = request.app.state.settings
    return ActorContext(
        actor_id=settings.actor_id,
        display_name=settings.actor_display_name,
        role_codes=CONFIGURED_ACTOR_CAPABILITIES,
    )


def get_templates(request: Request) -> Jinja2Templates:
    """Get templates instance."""
    return _templates


def _resolve_app_context(
    intake_id: str, session_factory: sessionmaker
) -> tuple[str | None, str | None]:
    """Returns (app_id, app_display_name) for an intake. Returns (None, None) if not found."""
    with session_factory() as session:
        row = session.execute(
            select(Intake.application_id, Application.display_name)
            .join(Application, Application.id == Intake.application_id)
            .where(Intake.id == intake_id)
        ).first()
    if row is None:
        return None, None
    return str(row.application_id), str(row.display_name)


# ─────────────────────────────────────────────────────────────────────────────
# Readiness check
# ─────────────────────────────────────────────────────────────────────────────


@router.get("/readiness", response_class=HTMLResponse)
async def get_readiness(
    request: Request,
    intake_id: str,
    session_factory: Annotated[sessionmaker, Depends(get_session_factory)],
    templates: Annotated[object, Depends(get_templates)],
) -> HTMLResponse:
    """Check readiness status for an intake."""
    service = ReadinessService(session_factory)
    result = service.check_readiness(intake_id)

    app_id, app_name = _resolve_app_context(intake_id, session_factory)
    nav_items = app_nav_items(app_id, intake_id, "readiness") if app_id else []
    csrf_token = generate_csrf_token(request.app.state.settings.csrf_secret)

    return templates.TemplateResponse(
        request,
        "readiness/report.html",
        {
            "intake_id": intake_id,
            "readiness": result,
            "app_id": app_id,
            "app_name": app_name,
            "nav_items": nav_items,
            "active_nav": "readiness",
            "csrf_token": csrf_token,
        },
    )


@router.get("/readiness.json")
async def get_readiness_json(
    intake_id: str,
    session_factory: Annotated[sessionmaker, Depends(get_session_factory)],
) -> JSONResponse:
    """Check readiness status (JSON API)."""
    service = ReadinessService(session_factory)
    result = service.check_readiness(intake_id)

    return JSONResponse(
        content={
            "intake_id": result.intake_id,
            "is_ready": result.is_ready,
            "checked_at": result.checked_at,
            "dimensions": [
                {
                    "name": d.name,
                    "passed": d.passed,
                    "message": d.message,
                    "blockers": d.blockers,
                }
                for d in result.dimensions
            ],
        }
    )


# ─────────────────────────────────────────────────────────────────────────────
# Freeze
# ─────────────────────────────────────────────────────────────────────────────


@router.post("/freeze", response_class=HTMLResponse)
async def freeze_intake(
    request: Request,
    intake_id: str,
    session_factory: Annotated[sessionmaker, Depends(get_session_factory)],
    actor: Annotated[ActorContext, Depends(get_actor_context)],
    templates: Annotated[object, Depends(get_templates)],
    csrf_token: Annotated[str | None, Form(alias="_csrf_token")] = None,
) -> HTMLResponse:
    """Freeze an intake and create a snapshot."""
    # Validate CSRF token before any state mutation
    if not csrf_token or not validate_csrf_token(
        csrf_token, request.app.state.settings.csrf_secret
    ):
        raise HTTPException(status_code=403, detail="CSRF token missing or invalid")

    app_id, app_name = _resolve_app_context(intake_id, session_factory)
    nav_items = app_nav_items(app_id, intake_id, "readiness") if app_id else []

    service = SnapshotService(session_factory)

    try:
        result = service.freeze_intake(intake_id, actor)
    except IntakeNotReadyError as e:
        return templates.TemplateResponse(
            request,
            "readiness/freeze_error.html",
            {
                "intake_id": intake_id,
                "readiness": e.readiness,
                "app_id": app_id,
                "app_name": app_name,
                "nav_items": nav_items,
                "active_nav": "readiness",
            },
            status_code=400,
        )

    return templates.TemplateResponse(
        request,
        "readiness/freeze_success.html",
        {
            "intake_id": intake_id,
            "result": result,
            "app_id": app_id,
            "app_name": app_name,
            "nav_items": nav_items,
            "active_nav": "readiness",
        },
    )


@router.post("/freeze.json")
async def freeze_intake_json(
    intake_id: str,
    session_factory: Annotated[sessionmaker, Depends(get_session_factory)],
    actor: Annotated[ActorContext, Depends(get_actor_context)],
) -> JSONResponse:
    """Freeze an intake (JSON API)."""
    service = SnapshotService(session_factory)

    try:
        result = service.freeze_intake(intake_id, actor)
    except IntakeNotReadyError as e:
        return JSONResponse(
            content={
                "error": "intake_not_ready",
                "message": str(e),
                "readiness": {
                    "is_ready": e.readiness.is_ready,
                    "blocking_dimensions": [
                        d.name for d in e.readiness.blocking_dimensions
                    ],
                },
            },
            status_code=400,
        )

    return JSONResponse(
        content={
            "snapshot_id": result.snapshot_id,
            "intake_id": result.intake_id,
            "sha256_hex": result.sha256_hex,
            "created_at": result.created_at,
            "is_new": result.is_new,
        }
    )


# ─────────────────────────────────────────────────────────────────────────────
# Snapshot view
# ─────────────────────────────────────────────────────────────────────────────


@router.get("/snapshot", response_class=HTMLResponse)
async def get_snapshot(
    request: Request,
    intake_id: str,
    session_factory: Annotated[sessionmaker, Depends(get_session_factory)],
    templates: Annotated[object, Depends(get_templates)],
) -> HTMLResponse:
    """View snapshot details for an intake."""
    service = SnapshotService(session_factory)
    snapshot = service.get_snapshot(intake_id)

    if snapshot is None:
        raise HTTPException(status_code=404, detail="No snapshot found for intake")

    # Parse canonical JSON for display
    payload = json.loads(snapshot["canonical_json"])

    app_id, app_name = _resolve_app_context(intake_id, session_factory)
    nav_items = app_nav_items(app_id, intake_id, "readiness") if app_id else []

    return templates.TemplateResponse(
        request,
        "readiness/snapshot.html",
        {
            "intake_id": intake_id,
            "snapshot": snapshot,
            "payload": payload,
            "app_id": app_id,
            "app_name": app_name,
            "nav_items": nav_items,
            "active_nav": "readiness",
        },
    )


@router.get("/snapshot.json")
async def get_snapshot_json(
    intake_id: str,
    session_factory: Annotated[sessionmaker, Depends(get_session_factory)],
) -> JSONResponse:
    """Get snapshot details (JSON API)."""
    service = SnapshotService(session_factory)
    snapshot = service.get_snapshot(intake_id)

    if snapshot is None:
        raise HTTPException(status_code=404, detail="No snapshot found for intake")

    return JSONResponse(
        content={
            "id": snapshot["id"],
            "intake_id": snapshot["intake_id"],
            "schema_version": snapshot["schema_version"],
            "sha256_hex": snapshot["sha256_hex"],
            "catalog_sha256": snapshot["catalog_sha256"],
            "created_at": str(snapshot["created_at"]),
            "created_by_id": snapshot["created_by_id"],
        }
    )


# ─────────────────────────────────────────────────────────────────────────────
# Export
# ─────────────────────────────────────────────────────────────────────────────


@router.get("/export")
async def export_intake(
    intake_id: str,
    session_factory: Annotated[sessionmaker, Depends(get_session_factory)],
) -> Response:
    """Export canonical package for an intake."""
    service = ExportService(session_factory)
    package = service.export_intake(intake_id)

    if package is None:
        raise HTTPException(status_code=404, detail="No snapshot found for intake")

    # Return as JSON with appropriate headers
    return Response(
        content=package.canonical_json,
        media_type="application/json",
        headers={
            "Content-Disposition": f'attachment; filename="intake-{intake_id}.json"',
            "X-Payload-SHA256": package.manifest.payload_sha256,
            "X-Schema-Version": package.manifest.schema_version,
        },
    )


@router.get("/export/manifest.json")
async def export_manifest(
    intake_id: str,
    session_factory: Annotated[sessionmaker, Depends(get_session_factory)],
) -> JSONResponse:
    """Export manifest for an intake."""
    service = ExportService(session_factory)
    package = service.export_intake(intake_id)

    if package is None:
        raise HTTPException(status_code=404, detail="No snapshot found for intake")

    return JSONResponse(content=json.loads(package.manifest_json))
