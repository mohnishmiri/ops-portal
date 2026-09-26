"""
Catalog admin upload → validate → publish routes — CAT-B3.

This router is deliberately separate from ``catalog_admin.py`` (CAT-B2's
read-only viewer router), even though both are mounted under the same
``/admin/catalog`` URL prefix, so the two packets can be built in parallel
without touching one shared route file.

Every state-changing handler here:
1. Checks ``require_capability(actor_ctx.role_codes, Capability.CATALOG_MANAGE)``
   as the FIRST line — before reading the CSRF token or the uploaded file.
2. Validates the multipart ``_csrf_token`` field (same pattern as
   ``gap_workbook.py``).
3. Only then reads and compiles the uploaded content.

This ordering matters: an actor without the capability must never cause the
uploaded file to be read or compiled, regardless of CSRF validity.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import sessionmaker

from migration_intake.application.dto import ActorContext
from migration_intake.application.errors import CatalogVersionConflictError
from migration_intake.application.services.catalog_admin_publish import (
    CatalogAdminPublishService,
    CatalogCompileError,
)
from migration_intake.web.routes._nav import global_nav_items
from migration_intake.web.security import (
    CONFIGURED_ACTOR_CAPABILITIES,
    Capability,
    generate_csrf_token,
    require_capability,
    validate_csrf_token,
)

router = APIRouter(tags=["catalog-admin-publish"])

_template_dir = Path(__file__).parent.parent / "templates"
templates = Jinja2Templates(directory=str(_template_dir))


def get_session_factory(request: Request) -> sessionmaker:
    """Dependency to get session factory from app state."""
    return request.app.state.session_factory


def get_actor_context(request: Request) -> ActorContext:
    """
    Dependency to get actor context.

    For now, uses the configured actor from settings. In production, this
    would come from authentication/session. The configured actor is granted
    every capability (including ``Capability.CATALOG_MANAGE``), matching the
    single-actor, no-multi-tenant-auth phase this application is currently
    in — see CAT-SEC1b in ``src/docs/plan_catalog_automation.md``.
    """
    settings = request.app.state.settings
    return ActorContext(
        actor_id=str(settings.actor_id),
        role_codes=CONFIGURED_ACTOR_CAPABILITIES,
    )


SessionFactoryDep = Annotated[sessionmaker, Depends(get_session_factory)]
ActorContextDep = Annotated[ActorContext, Depends(get_actor_context)]


def _diagnostics_body(error: CatalogCompileError) -> dict[str, Any]:
    return {"message": str(error), "diagnostics": error.diagnostics}


@router.get("/admin/catalog/upload", response_class=HTMLResponse)
async def upload_form(
    request: Request,
) -> HTMLResponse:
    """GET /admin/catalog/upload — render the CSV upload form."""
    csrf_token = generate_csrf_token(request.app.state.settings.csrf_secret)
    return templates.TemplateResponse(
        request=request,
        name="catalog_admin/upload.html",
        context={
            "csrf_token": csrf_token,
            "title": "Upload Catalog",
            "nav_items": global_nav_items("catalog_admin"),
            "active_nav": "catalog_admin",
            "command_actions": {"cancel_href": "/admin/catalog"},
        },
    )


@router.post("/admin/catalog/preview")
async def preview_catalog(
    request: Request,
    session_factory: SessionFactoryDep,
    actor_ctx: ActorContextDep,
    csrf_token: Annotated[str, Form(alias="_csrf_token")],
    semantic_version: Annotated[str, Form()],
    file: UploadFile = File(...),
) -> JSONResponse:
    """
    POST /admin/catalog/preview — compile an uploaded CSV without persisting.

    Returns the full diagnostics report as JSON. Never writes to the
    database.
    """
    require_capability(set(actor_ctx.role_codes), Capability.CATALOG_MANAGE)

    if not validate_csrf_token(csrf_token, request.app.state.settings.csrf_secret):
        raise HTTPException(status_code=403, detail="Invalid CSRF token")

    content = await file.read()
    service = CatalogAdminPublishService(session_factory)
    result = service.preview(
        content=content,
        filename=file.filename or "catalog.csv",
        semantic_version=semantic_version,
    )

    return JSONResponse(
        content={
            "is_success": result.report.is_success,
            "diagnostics": result.report.diagnostics.to_list(),
            "section_count": result.report.section_count,
            "question_count": result.report.question_count,
            "type_counts": result.report.type_counts,
        }
    )


@router.post("/admin/catalog/publish")
async def publish_catalog_route(
    request: Request,
    session_factory: SessionFactoryDep,
    actor_ctx: ActorContextDep,
    csrf_token: Annotated[str, Form(alias="_csrf_token")],
    semantic_version: Annotated[str, Form()],
    file: UploadFile = File(...),
) -> JSONResponse:
    """
    POST /admin/catalog/publish — compile and publish an uploaded CSV.

    Never trusts a client-held preview result — the compile step is re-run
    from the raw uploaded bytes inside the service before anything is
    persisted.
    """
    require_capability(set(actor_ctx.role_codes), Capability.CATALOG_MANAGE)

    if not validate_csrf_token(csrf_token, request.app.state.settings.csrf_secret):
        raise HTTPException(status_code=403, detail="Invalid CSRF token")

    content = await file.read()
    service = CatalogAdminPublishService(session_factory)
    try:
        release = service.publish(
            content=content,
            filename=file.filename or "catalog.csv",
            semantic_version=semantic_version,
            actor=actor_ctx,
        )
    except CatalogCompileError as error:
        raise HTTPException(status_code=400, detail=_diagnostics_body(error)) from error
    except CatalogVersionConflictError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error

    return JSONResponse(
        status_code=201,
        content={
            "id": release["id"],
            "semantic_version": release["semantic_version"],
            "pub_state": release["pub_state"],
        },
    )
