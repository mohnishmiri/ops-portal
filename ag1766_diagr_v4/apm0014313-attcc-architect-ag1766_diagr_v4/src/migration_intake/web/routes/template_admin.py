"""Read-only topology template admin routes."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, cast

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session, sessionmaker

from migration_intake.application.services.template_admin_queries import (
    TemplateAdminQueryService,
)
from migration_intake.web.routes._nav import global_nav_items
from migration_intake.web.security import generate_csrf_token

router = APIRouter(prefix="/admin/templates", tags=["template-admin"])

_template_dir = Path(__file__).parent.parent / "templates"
templates = Jinja2Templates(directory=str(_template_dir))


def get_session_factory(request: Request) -> sessionmaker[Session]:
    return cast("sessionmaker[Session]", request.app.state.session_factory)


SessionFactoryDep = Annotated[sessionmaker[Session], Depends(get_session_factory)]


@router.get("/", response_class=HTMLResponse)
async def list_template_releases(
    request: Request,
    session_factory: SessionFactoryDep,
) -> HTMLResponse:
    releases = TemplateAdminQueryService(session_factory).list_releases()
    return templates.TemplateResponse(
        request=request,
        name="template_admin/list.html",
        context={
            "releases": releases,
            "nav_items": global_nav_items("template_admin"),
            "active_nav": "template_admin",
            "command_actions": {"upload_href": "/admin/templates/upload"},
        },
    )


@router.get("/{release_id}", response_class=HTMLResponse)
async def get_template_release_detail(
    request: Request,
    release_id: str,
    session_factory: SessionFactoryDep,
) -> HTMLResponse:
    detail = TemplateAdminQueryService(session_factory).get_release_detail(release_id)
    if detail is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Template release not found",
        )
    csrf_token = generate_csrf_token(request.app.state.settings.csrf_secret)
    return templates.TemplateResponse(
        request=request,
        name="template_admin/detail.html",
        context={
            "release": detail,
            "csrf_token": csrf_token,
            "nav_items": global_nav_items("template_admin"),
            "active_nav": "template_admin",
            "command_actions": {"back_href": "/admin/templates"},
        },
    )
