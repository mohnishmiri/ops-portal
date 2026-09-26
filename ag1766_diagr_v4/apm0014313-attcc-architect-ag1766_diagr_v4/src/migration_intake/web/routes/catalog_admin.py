"""
Read-only catalog admin viewer (CAT-B2).

Routes:
- GET /admin/catalog                 — list every catalog release (newest-first)
- GET /admin/catalog/{release_id}    — full section/question tree + pinned intakes

Security note (deliberate, not an oversight):
    These routes are intentionally left WITHOUT a capability gate or CSRF
    protection. Both are GET-only, read-only views that mutate nothing. In
    the current phase there is a single configured actor and no
    multi-tenant authentication boundary, so gating a read-only admin page
    would add process without adding real security. Revisit this decision
    once real authentication/authorization lands (see
    ``src/docs/plan_catalog_automation.md`` Section 6, open decision 1).

    A separate, parallel packet (CAT-B3) adds POST routes for CSV
    upload/publish in a different router file
    (``catalog_admin_publish.py``); those routes DO require CSRF and a
    capability check because they mutate state. This file adds none of
    that — GET routes only.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from migration_intake.application.services.catalog_admin_queries import (
    CatalogAdminQueryService,
)
from migration_intake.web.routes._nav import global_nav_items

# Router for read-only catalog admin routes.
router = APIRouter(prefix="/admin/catalog", tags=["catalog-admin"])

# Templates — same absolute-path resolution pattern as applications.py.
_template_dir = Path(__file__).parent.parent / "templates"
templates = Jinja2Templates(directory=str(_template_dir))


def get_session_factory(request: Request) -> sessionmaker:
    """Dependency to get session factory from app state."""
    return request.app.state.session_factory


SessionFactoryDep = Annotated[sessionmaker, Depends(get_session_factory)]


def _list_pinned_intakes(
    session_factory: sessionmaker, release_id: str
) -> list[dict[str, Any]]:
    """
    Return ``{id, application_name}`` for every intake pinned to a release.

    ``CatalogAdminQueryService`` only exposes a count of pinned intakes
    (``pinned_intake_count``), not the intake rows themselves, and no
    existing repository exposes "list intakes for a catalog release" plus
    an application-name join. Per the CAT-B2 packet scope, no new
    repository/service join method is added; this composes the two
    existing tables directly (mirroring the read-model join style already
    used in ``application/queries.py``) rather than inventing a new
    persistence-layer abstraction for a single admin-only display need.
    """
    from migration_intake.persistence.models import Application, Intake

    session: Session = session_factory()
    try:
        stmt = (
            select(Intake.id, Application.display_name)
            .join(Application, Application.id == Intake.application_id)
            .where(Intake.catalog_id == release_id)
            .order_by(Intake.created_at.asc())
        )
        rows = session.execute(stmt).all()
        return [
            {"id": str(row[0]), "application_name": row[1]}
            for row in rows
        ]
    finally:
        session.close()


@router.get("/", response_class=HTMLResponse)
async def list_catalog_releases(
    request: Request,
    session_factory: SessionFactoryDep,
) -> HTMLResponse:
    """
    GET /admin/catalog — list every catalog release, newest-first.

    Renders an empty-state page (not a 500) when no releases exist.
    """
    query_service = CatalogAdminQueryService(session_factory)
    releases = query_service.list_releases()

    return templates.TemplateResponse(
        request=request,
        name="catalog_admin/list.html",
        context={
            "releases": releases,
            "nav_items": global_nav_items("catalog_admin"),
            "active_nav": "catalog_admin",
            "command_actions": {"upload_href": "/admin/catalog/upload"},
        },
    )


@router.get("/{release_id}", response_class=HTMLResponse)
async def get_catalog_release_detail(
    request: Request,
    release_id: str,
    session_factory: SessionFactoryDep,
) -> HTMLResponse:
    """
    GET /admin/catalog/{release_id} — full section/question tree + pinned intakes.

    Returns a proper 404 (not an empty 200 page) when the release id is
    unknown.
    """
    query_service = CatalogAdminQueryService(session_factory)
    detail = query_service.get_release_detail(release_id)

    if detail is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Catalog release not found",
        )

    pinned_intakes = _list_pinned_intakes(session_factory, release_id)

    return templates.TemplateResponse(
        request=request,
        name="catalog_admin/detail.html",
        context={
            "release": detail,
            "pinned_intakes": pinned_intakes,
            "nav_items": global_nav_items("catalog_admin"),
            "active_nav": "catalog_admin",
            "command_actions": {"back_href": "/admin/catalog"},
        },
    )
