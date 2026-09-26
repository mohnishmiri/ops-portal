"""Template admin upload/preview/publish routes."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, cast

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session, sessionmaker

from migration_intake.application.dto import ActorContext
from migration_intake.application.services.template_admin_publish import (
    TemplateAdminPublishService,
    TemplateCompileError,
    TemplateVersionConflictError,
)
from migration_intake.web.routes._nav import global_nav_items
from migration_intake.web.security import (
    CONFIGURED_ACTOR_CAPABILITIES,
    Capability,
    generate_csrf_token,
    require_capability,
    validate_csrf_token,
)

router = APIRouter(tags=["template-admin-publish"])

_template_dir = Path(__file__).parent.parent / "templates"
templates = Jinja2Templates(directory=str(_template_dir))


def get_session_factory(request: Request) -> sessionmaker[Session]:
    return cast("sessionmaker[Session]", request.app.state.session_factory)


def get_actor_context(request: Request) -> ActorContext:
    settings = request.app.state.settings
    return ActorContext(
        actor_id=str(settings.actor_id),
        role_codes=CONFIGURED_ACTOR_CAPABILITIES,
    )


SessionFactoryDep = Annotated[sessionmaker[Session], Depends(get_session_factory)]
ActorContextDep = Annotated[ActorContext, Depends(get_actor_context)]


@router.get("/admin/templates/upload", response_class=HTMLResponse)
async def upload_form(request: Request) -> HTMLResponse:
    csrf_token = generate_csrf_token(request.app.state.settings.csrf_secret)
    return templates.TemplateResponse(
        request=request,
        name="template_admin/upload.html",
        context={
            "csrf_token": csrf_token,
            "title": "Upload Topology Template",
            "nav_items": global_nav_items("template_admin"),
            "active_nav": "template_admin",
            "command_actions": {"cancel_href": "/admin/templates"},
        },
    )


@router.post("/admin/templates/preview")
async def preview_template(
    request: Request,
    session_factory: SessionFactoryDep,
    actor_ctx: ActorContextDep,
    file: UploadFile = File(...),
    csrf_token: Annotated[str | None, Form(alias="_csrf_token")] = None,
) -> JSONResponse:
    require_capability(set(actor_ctx.role_codes), Capability.TEMPLATE_MANAGE)
    if not csrf_token or not validate_csrf_token(
        csrf_token, request.app.state.settings.csrf_secret
    ):
        raise HTTPException(status_code=403, detail="Invalid CSRF token")

    content = await file.read()
    service = TemplateAdminPublishService(
        session_factory, storage_root=request.app.state.settings.evidence_root
    )
    result = service.preview(content, file.filename or "template.drawio")
    return JSONResponse(
        content={
            "is_valid": result.is_valid,
            "tab_count": result.tab_count,
            "diagnostics": result.diagnostics,
            "variant_manifest": result.variant_manifest,
        }
    )


@router.post("/admin/templates/publish")
async def publish_template(
    request: Request,
    session_factory: SessionFactoryDep,
    actor_ctx: ActorContextDep,
    template_version: Annotated[str, Form()],
    file: UploadFile = File(...),
    csrf_token: Annotated[str | None, Form(alias="_csrf_token")] = None,
) -> JSONResponse:
    require_capability(set(actor_ctx.role_codes), Capability.TEMPLATE_MANAGE)
    if not csrf_token or not validate_csrf_token(
        csrf_token, request.app.state.settings.csrf_secret
    ):
        raise HTTPException(status_code=403, detail="Invalid CSRF token")

    content = await file.read()
    service = TemplateAdminPublishService(
        session_factory, storage_root=request.app.state.settings.evidence_root
    )
    try:
        release = service.publish(
            content,
            file.filename or "template.drawio",
            template_version=template_version,
            actor=actor_ctx,
        )
    except TemplateCompileError as error:
        raise HTTPException(
            status_code=400,
            detail={"message": str(error), "diagnostics": error.diagnostics},
        ) from error
    except TemplateVersionConflictError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error

    return JSONResponse(
        status_code=201,
        content={
            "id": release["id"],
            "template_version": release["template_version"],
            "pub_state": release["pub_state"],
        },
    )


@router.post("/admin/templates/{release_id}/activate")
async def activate_template(
    request: Request,
    release_id: str,
    session_factory: SessionFactoryDep,
    actor_ctx: ActorContextDep,
    csrf_token: Annotated[str | None, Form(alias="_csrf_token")] = None,
) -> JSONResponse:
    require_capability(set(actor_ctx.role_codes), Capability.TEMPLATE_MANAGE)
    if not csrf_token or not validate_csrf_token(
        csrf_token, request.app.state.settings.csrf_secret
    ):
        raise HTTPException(status_code=403, detail="Invalid CSRF token")

    service = TemplateAdminPublishService(
        session_factory, storage_root=request.app.state.settings.evidence_root
    )
    try:
        release = service.activate(release_id, actor=actor_ctx)
    except TemplateVersionConflictError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    return JSONResponse(content={"id": release["id"], "pub_state": release["pub_state"]})


@router.post("/admin/templates/{release_id}/retire")
async def retire_template(
    request: Request,
    release_id: str,
    session_factory: SessionFactoryDep,
    actor_ctx: ActorContextDep,
    csrf_token: Annotated[str | None, Form(alias="_csrf_token")] = None,
) -> JSONResponse:
    require_capability(set(actor_ctx.role_codes), Capability.TEMPLATE_MANAGE)
    if not csrf_token or not validate_csrf_token(
        csrf_token, request.app.state.settings.csrf_secret
    ):
        raise HTTPException(status_code=403, detail="Invalid CSRF token")

    service = TemplateAdminPublishService(
        session_factory, storage_root=request.app.state.settings.evidence_root
    )
    try:
        release = service.retire(release_id, actor=actor_ctx)
    except TemplateVersionConflictError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    return JSONResponse(content={"id": release["id"], "pub_state": release["pub_state"]})
