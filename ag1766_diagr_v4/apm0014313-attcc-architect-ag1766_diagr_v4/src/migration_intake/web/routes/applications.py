"""
Application list/create/workspace routes (UI02 + UI02b, UX-4a).

Routes:
- GET /applications — list view with card grid and counts
- GET /applications/new — create form page (full shell)
- POST /applications — create new application
- GET /applications/{id} — workspace view (full app nav + action grid)
- GET /applications/{id}/edit — edit form page (full shell)
- POST /applications/{id}/edit — save identity changes
- POST /applications/{id}/intakes — create intake

Following Jinja2 + HTMX patterns for server-rendered UI.
Design-system rules: tokens only, no inline styles, no inline handlers.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import sessionmaker

from migration_intake.application.commands import (
    CreateApplicationCommand,
    CreateIntakeCommand,
    IdentifierInput,
    UpdateApplicationIdentityCommand,
)
from migration_intake.application.dto import ActorContext
from migration_intake.application.errors import (
    ApplicationNotFoundError,
    CatalogNotPublishedError,
    DuplicateIdentifierError,
    OpenIntakeExistsError,
)
from migration_intake.application.queries import ApplicationQueryService
from migration_intake.application.services.application_summary import (
    get_application_list_stats,
    get_workspace_summary,
)
from migration_intake.application.services.applications import ApplicationService
from migration_intake.application.services.catalogs import CatalogPublicationService
from migration_intake.domain.ids import ApplicationId
from migration_intake.web.routes._nav import app_nav_items, global_nav_items
from migration_intake.web.security import (
    CONFIGURED_ACTOR_CAPABILITIES,
    generate_csrf_token,
    validate_csrf_token,
)

# Router for application routes
router = APIRouter(prefix="/applications", tags=["applications"])

# Templates - use absolute path resolution
_template_dir = Path(__file__).parent.parent / "templates"
templates = Jinja2Templates(directory=str(_template_dir))


def get_session_factory(request: Request) -> sessionmaker:
    """Dependency to get session factory from app state."""
    return request.app.state.session_factory


def get_actor_context(request: Request) -> ActorContext:
    """
    Dependency to get actor context.

    For now, uses the configured actor from settings.
    In production, this would come from authentication/session.
    """
    settings = request.app.state.settings
    return ActorContext(
        actor_id=str(settings.actor_id),
        role_codes=CONFIGURED_ACTOR_CAPABILITIES,
    )


SessionFactoryDep = Annotated[sessionmaker, Depends(get_session_factory)]
ActorContextDep = Annotated[ActorContext, Depends(get_actor_context)]


def _application_preview_rows(session_factory: sessionmaker[object]) -> list[dict[str, object]]:
    query_service = ApplicationQueryService(session_factory)
    applications = query_service.list_applications(
        state_filter=None,
        limit=50,
        offset=0,
    )
    app_ids = [app["id"] for app in applications]
    stats = get_application_list_stats(session_factory, app_ids)
    return [{**app, **stats.get(app["id"], {})} for app in applications]


@router.get("/design-options", response_class=HTMLResponse)
async def application_design_options(
    request: Request,
    session_factory: SessionFactoryDep,
) -> HTMLResponse:
    """Render the isolated applications-list design comparison."""
    return templates.TemplateResponse(
        request=request,
        name="applications/design_options/index.html",
        context={
            "applications": _application_preview_rows(session_factory),
            "app_name": None,
            "nav_items": global_nav_items("applications"),
            "active_nav": "applications",
        },
    )


@router.get("/design-options/{option}", response_class=HTMLResponse)
async def application_design_option(
    request: Request,
    option: str,
    session_factory: SessionFactoryDep,
) -> HTMLResponse:
    """Render one isolated applications-list design option."""
    if option not in {"a", "b", "c"}:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return templates.TemplateResponse(
        request=request,
        name="applications/design_options/option.html",
        context={
            "applications": _application_preview_rows(session_factory),
            "option": option,
            "app_name": None,
            "nav_items": global_nav_items("applications"),
            "active_nav": "applications",
        },
    )


@router.get("/new", response_class=HTMLResponse)
async def new_application_form(
    request: Request,
    session_factory: SessionFactoryDep,
) -> HTMLResponse:
    """
    GET /applications/new — create form page.

    Returns:
        HTML page with application create form (full shell, global nav).
    """
    csrf_token = generate_csrf_token()

    return templates.TemplateResponse(
        request=request,
        name="applications/new.html",
        context={
            "csrf_token": csrf_token,
            "title": "New Application",
            "app_name": None,
            "nav_items": global_nav_items("applications"),
            "active_nav": "applications",
        },
    )


@router.get("/", response_class=HTMLResponse)
async def list_applications(
    request: Request,
    session_factory: SessionFactoryDep,
    limit: int = 50,
    offset: int = 0,
) -> HTMLResponse:
    """
    GET /applications — list view with card grid and per-app counts.

    Query parameters:
        limit: Maximum number of applications to return (default: 50)
        offset: Number of applications to skip (default: 0)

    Returns:
        HTML page with application card grid
    """
    query_service = ApplicationQueryService(session_factory)

    # Get applications
    applications = query_service.list_applications(
        state_filter=None,
        limit=limit,
        offset=offset,
    )

    # Enrich each app dict with evidence and proposal counts.
    app_ids = [app["id"] for app in applications]
    stats = get_application_list_stats(session_factory, app_ids)
    enriched = [{**app, **stats.get(app["id"], {})} for app in applications]

    return templates.TemplateResponse(
        request=request,
        name="applications/list.html",
        context={
            "applications": enriched,
            "limit": limit,
            "offset": offset,
            "app_name": None,
            "nav_items": global_nav_items("applications"),
            "active_nav": "applications",
        },
    )


@router.post("/", status_code=status.HTTP_303_SEE_OTHER)
async def create_application(
    request: Request,
    session_factory: SessionFactoryDep,
    actor_ctx: ActorContextDep,
    display_name: Annotated[str, Form()],
    identifier_type: Annotated[str | None, Form()] = None,
    identifier_value: Annotated[str | None, Form()] = None,
) -> RedirectResponse:
    """
    POST /applications — create new application.

    Form data:
        display_name: Application display name (required)
        identifier_type: Optional identifier type (ITAP, CORRELATION, MOTS)
        identifier_value: Optional identifier value

    Returns:
        Redirect to workspace page (303 See Other)

    Raises:
        HTTPException 400: If validation fails or duplicate identifier
    """
    # Validate display name
    if not display_name or not display_name.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Display name is required",
        )

    # Build identifiers list
    identifiers = []
    if identifier_type and identifier_value:
        identifiers.append(
            IdentifierInput(identifier_type=identifier_type, raw_value=identifier_value)
        )

    # Create application
    service = ApplicationService(session_factory)
    cmd = CreateApplicationCommand(
        display_name=display_name.strip(),
        identifiers=tuple(identifiers),
        actor=actor_ctx,
    )

    try:
        result = service.create_application(cmd)
    except DuplicateIdentifierError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Duplicate identifier: {e}",
        ) from e

    # Redirect to workspace
    return RedirectResponse(
        url=f"/applications/{result['id']}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.get("/{application_id}/edit", response_class=HTMLResponse)
async def edit_application_form(
    request: Request,
    application_id: str,
    session_factory: SessionFactoryDep,
) -> HTMLResponse:
    """Render the application identity and identifier edit form (full shell)."""
    query_service = ApplicationQueryService(session_factory)
    workspace = query_service.get_application_workspace(application_id)
    if workspace is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Application not found")

    open_intake = workspace.get("open_intake")
    intake_id = open_intake["id"] if open_intake else None

    if intake_id:
        nav_items = app_nav_items(application_id, intake_id, "hub")
        active_nav = "hub"
    else:
        nav_items = global_nav_items("applications")
        active_nav = "applications"

    return templates.TemplateResponse(
        request=request,
        name="applications/edit.html",
        context={
            "workspace": workspace,
            "app_name": workspace["display_name"],
            "nav_items": nav_items,
            "active_nav": active_nav,
            "intake_id": intake_id,
            "csrf_token": generate_csrf_token(),
        },
    )


@router.post("/{application_id}/edit", status_code=status.HTTP_303_SEE_OTHER)
async def update_application_form(
    request: Request,
    application_id: str,
    session_factory: SessionFactoryDep,
    actor_ctx: ActorContextDep,
    csrf_token: Annotated[str, Form(alias="_csrf_token")],
    display_name: Annotated[str, Form()],
    expected_version: Annotated[int, Form()],
    identifier_type: Annotated[list[str], Form()] = [],
    identifier_value: Annotated[list[str], Form()] = [],
) -> RedirectResponse:
    """Update application identity and replace its identifiers."""
    if not validate_csrf_token(csrf_token):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="CSRF token invalid or expired")
    identifiers = tuple(
        IdentifierInput(identifier_type=kind, raw_value=value)
        for kind, value in zip(identifier_type, identifier_value)
        if kind.strip() and value.strip()
    )
    service = ApplicationService(session_factory)
    try:
        service.update_application_identity(
            UpdateApplicationIdentityCommand(
                application_id=application_id,
                display_name=display_name.strip(),
                identifiers=identifiers,
                expected_version=expected_version,
                actor=actor_ctx,
            )
        )
    except DuplicateIdentifierError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return RedirectResponse(url=f"/applications/{application_id}", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/{application_id}", response_class=HTMLResponse)
async def get_application_workspace(
    request: Request,
    application_id: str,
    session_factory: SessionFactoryDep,
) -> HTMLResponse:
    """
    GET /applications/{id} — workspace view with full app nav and action grid.

    Path parameters:
        application_id: Application UUID

    Returns:
        HTML page with application workspace (hub entry point)

    Raises:
        HTTPException 404: If application not found
    """
    try:
        app_id = ApplicationId(application_id)
    except (ValueError, TypeError) as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Application not found",
        ) from e

    # Get enriched workspace data (includes hub_href, proposal_count).
    workspace = get_workspace_summary(session_factory, str(app_id))

    if workspace is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Application not found",
        )

    open_intake = workspace.get("open_intake")
    intake_id = open_intake["id"] if open_intake else None

    if intake_id:
        nav_items = app_nav_items(str(app_id), intake_id, "hub")
        active_nav = "hub"
    else:
        nav_items = global_nav_items("applications")
        active_nav = "applications"

    # Get latest published catalog for intake creation
    catalog_service = CatalogPublicationService(session_factory)
    latest_catalog = catalog_service.get_latest_published()

    # Generate CSRF token for intake creation form
    csrf_token = generate_csrf_token()

    return templates.TemplateResponse(
        request=request,
        name="applications/workspace.html",
        context={
            "workspace": workspace,
            "app_name": workspace["display_name"],
            "nav_items": nav_items,
            "active_nav": active_nav,
            "application_id": str(app_id),
            "intake_id": intake_id,
            "hub_href": workspace.get("hub_href"),
            "proposal_count": workspace.get("proposal_count", 0),
            "evidence_count": workspace.get("evidence_count", 0),
            "interface_count": workspace.get("interface_count", 0),
            "interface_proposal_count": workspace.get("interface_proposal_count", 0),
            "latest_catalog": latest_catalog,
            "csrf_token": csrf_token,
        },
    )


@router.post("/{application_id}/intakes", status_code=status.HTTP_303_SEE_OTHER)
async def create_intake(
    request: Request,
    application_id: str,
    session_factory: SessionFactoryDep,
    actor_ctx: ActorContextDep,
    csrf_token: Annotated[str, Form(alias="_csrf_token")],
    catalog_id: Annotated[str | None, Form()] = None,
) -> RedirectResponse:
    """
    POST /applications/{id}/intakes — create intake.

    Form data:
        _csrf_token: CSRF token (required)
        catalog_id: Catalog release ID (optional, uses latest if not provided)

    Returns:
        Redirect to workspace page (303 See Other)

    Raises:
        HTTPException 403: If CSRF token invalid
        HTTPException 400: If no published catalog or open intake exists
        HTTPException 404: If application not found
    """
    # Validate CSRF token
    if not validate_csrf_token(csrf_token):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="CSRF token invalid or expired",
        )

    # Validate application ID
    try:
        app_id = ApplicationId(application_id)
    except (ValueError, TypeError) as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Application not found",
        ) from e

    # Get catalog ID - use provided or get latest
    if not catalog_id:
        catalog_service = CatalogPublicationService(session_factory)
        latest_catalog = catalog_service.get_latest_published()
        if latest_catalog is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No published catalog available. Please publish a catalog first.",
            )
        catalog_id = latest_catalog["id"]

    # Create intake
    service = ApplicationService(session_factory)
    cmd = CreateIntakeCommand(
        application_id=str(app_id),
        catalog_release_id=catalog_id,
        actor=actor_ctx,
    )

    try:
        result = service.create_intake(cmd)
    except ApplicationNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Application not found",
        ) from e
    except CatalogNotPublishedError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Catalog is not published",
        ) from e
    except OpenIntakeExistsError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="An open intake already exists for this application",
        ) from e

    # Redirect back to workspace
    return RedirectResponse(
        url=f"/applications/{application_id}",
        status_code=status.HTTP_303_SEE_OTHER,
    )
