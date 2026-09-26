"""
WaveUtil routes (UI07) — List and detail pages for WaveUtil register.

Routes:
- GET  /applications/{app}/intakes/{intake}/wave-util
- GET  /applications/{app}/intakes/{intake}/wave-util/{row}
- POST /applications/{app}/intakes/{intake}/wave-util/accept
- POST /applications/{app}/intakes/{intake}/wave-util/reject
- POST /applications/{app}/intakes/{intake}/wave-util/{row}/retire
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request, status
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from starlette.responses import Response

from migration_intake.application.dto import ActorContext
from migration_intake.application.errors import ConcurrencyConflictError
from migration_intake.application.services.wave_util_review import (
    CandidateNotProposedError,
    WaveUtilCandidateAcceptItem,
    WaveUtilRetireItem,
    WaveUtilReviewService,
)
from migration_intake.persistence.models import Application
from migration_intake.persistence.repositories.candidates import CandidateRepository
from migration_intake.persistence.repositories.wave_util import WaveUtilRepository
from migration_intake.web.routes._nav import app_nav_items
from migration_intake.web.security import (
    CONFIGURED_ACTOR_CAPABILITIES,
    generate_csrf_token,
    validate_csrf_token,
)

router = APIRouter(tags=["WaveUtil"])

# Templates
_template_dir = Path(__file__).parent.parent / "templates"
templates = Jinja2Templates(directory=str(_template_dir))


# ─────────────────────────────────────────────────────────────────────────────
# Dependencies
# ─────────────────────────────────────────────────────────────────────────────


def get_actor_context(request: Request) -> ActorContext:
    """Get actor context from app state."""
    settings = request.app.state.settings
    return ActorContext(
        actor_id=settings.actor_id,
        display_name=settings.actor_display_name,
        role_codes=CONFIGURED_ACTOR_CAPABILITIES,
    )


def get_review_service(request: Request) -> WaveUtilReviewService:
    """Get WaveUtil review service from app state."""
    session_factory = request.app.state.session_factory
    return WaveUtilReviewService(session_factory)


# ─────────────────────────────────────────────────────────────────────────────
# GET /applications/{app}/intakes/{intake}/wave-util
# ─────────────────────────────────────────────────────────────────────────────


@router.get("/applications/{app_id}/intakes/{intake_id}/wave-util")
async def list_wave_util(
    request: Request,
    app_id: str,
    intake_id: str,
    state: Annotated[str | None, Query()] = None,
    environment: Annotated[str | None, Query()] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=10, le=100)] = 50,
) -> Response:
    """
    List WaveUtil rows for an intake.

    Supports filtering by state and environment, with stable pagination.
    """
    session_factory = request.app.state.session_factory
    csrf_token = generate_csrf_token(request.app.state.settings.csrf_secret)

    with session_factory() as session:
        wave_util_repo = WaveUtilRepository(session)
        candidate_repo = CandidateRepository(session)

        # Resolve application name (lightweight, name-only query)
        _app_name = session.execute(
            select(Application.display_name).where(Application.id == app_id)
        ).scalar_one_or_none()
        app_name = _app_name or ""

        # Get all rows for the application
        all_rows = wave_util_repo.list_rows_for_application(
            app_id, state=state or "ACTIVE"
        )

        # Filter by environment if specified
        if environment:
            all_rows = [r for r in all_rows if r.get("environment") == environment]

        # Sort by normalized_server_name for stable ordering
        all_rows.sort(key=lambda r: (r.get("normalized_server_name", ""), r.get("id", "")))

        # Paginate
        total_rows = len(all_rows)
        total_pages = (total_rows + page_size - 1) // page_size
        start_idx = (page - 1) * page_size
        end_idx = start_idx + page_size
        rows = all_rows[start_idx:end_idx]

        # Get pending candidates for this intake
        pending_candidates = candidate_repo.get_by_intake(
            intake_id, state="PROPOSED", limit=1000
        )
        pending_by_target = {
            c.target_key: c for c in pending_candidates
            if c.target_kind == "WAVEUTIL_ROW"
        }

    return templates.TemplateResponse(
        request=request,
        name="wave_util/list.html",
        context={
            "csrf_token": csrf_token,
            "app_id": app_id,
            "intake_id": intake_id,
            "app_name": app_name,
            "nav_items": app_nav_items(app_id, intake_id, "wave_util"),
            "active_nav": "wave_util",
            "command_actions": {
                "export_href": f"/applications/{app_id}/intakes/{intake_id}/wave-util/export",
            },
            "rows": rows,
            "pending_by_target": pending_by_target,
            "total_rows": total_rows,
            "total_pages": total_pages,
            "current_page": page,
            "page_size": page_size,
            "filter_state": state,
            "filter_environment": environment,
        },
    )


# ─────────────────────────────────────────────────────────────────────────────
# GET /applications/{app}/intakes/{intake}/wave-util/{row}
# ─────────────────────────────────────────────────────────────────────────────


@router.get("/applications/{app_id}/intakes/{intake_id}/wave-util/{row_id}")
async def wave_util_detail(
    request: Request,
    app_id: str,
    intake_id: str,
    row_id: str,
) -> Response:
    """
    Show WaveUtil row detail.

    Displays identity, scope, source observations, revision history,
    and review actions.
    """
    session_factory = request.app.state.session_factory
    csrf_token = generate_csrf_token(request.app.state.settings.csrf_secret)

    with session_factory() as session:
        wave_util_repo = WaveUtilRepository(session)
        candidate_repo = CandidateRepository(session)

        # Resolve application name
        _app_name = session.execute(
            select(Application.display_name).where(Application.id == app_id)
        ).scalar_one_or_none()
        app_name = _app_name or ""

        # Get the row
        row = wave_util_repo.get_row(row_id)
        if row is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="WaveUtil row not found",
            )

        # Get current revision
        current_revision = wave_util_repo.get_current_revision(row_id)

        # Get pending candidates for this row
        pending_candidates = [
            c for c in candidate_repo.get_by_intake(intake_id, state="PROPOSED", limit=100)
            if c.target_kind == "WAVEUTIL_ROW" and row_id in (c.target_key or "")
        ]

    return templates.TemplateResponse(
        request=request,
        name="wave_util/detail.html",
        context={
            "csrf_token": csrf_token,
            "app_id": app_id,
            "intake_id": intake_id,
            "app_name": app_name,
            "nav_items": app_nav_items(app_id, intake_id, "wave_util"),
            "active_nav": "wave_util",
            "list_href": f"/applications/{app_id}/intakes/{intake_id}/wave-util",
            "row": row,
            "current_revision": current_revision,
            "pending_candidates": pending_candidates,
        },
    )


# ─────────────────────────────────────────────────────────────────────────────
# POST /applications/{app}/intakes/{intake}/wave-util/accept
# ─────────────────────────────────────────────────────────────────────────────


@router.post("/applications/{app_id}/intakes/{intake_id}/wave-util/accept")
async def accept_candidates(
    request: Request,
    app_id: str,
    intake_id: str,
    review_service: Annotated[WaveUtilReviewService, Depends(get_review_service)],
    actor: Annotated[ActorContext, Depends(get_actor_context)],
    csrf_token: Annotated[str, Form(alias="_csrf_token")],
    candidate_ids: Annotated[list[str], Form()],
    expected_versions: Annotated[list[int], Form()],
) -> RedirectResponse:
    """
    Accept selected WaveUtil candidates.

    Creates canonical rows for accepted candidates.
    """
    # Validate CSRF
    if not validate_csrf_token(csrf_token, request.app.state.settings.csrf_secret):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid CSRF token",
        )

    if len(candidate_ids) != len(expected_versions):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Mismatched candidate_ids and expected_versions",
        )

    items = [
        WaveUtilCandidateAcceptItem(
            candidate_id=cid,
            expected_candidate_version=ver,
        )
        for cid, ver in zip(candidate_ids, expected_versions)
    ]

    try:
        review_service.accept_candidates(items, actor)
    except ConcurrencyConflictError as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(e),
        )
    except CandidateNotProposedError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )

    return RedirectResponse(
        url=f"/applications/{app_id}/intakes/{intake_id}/wave-util",
        status_code=status.HTTP_303_SEE_OTHER,
    )


# ─────────────────────────────────────────────────────────────────────────────
# POST /applications/{app}/intakes/{intake}/wave-util/reject
# ─────────────────────────────────────────────────────────────────────────────


@router.post("/applications/{app_id}/intakes/{intake_id}/wave-util/reject")
async def reject_candidates(
    request: Request,
    app_id: str,
    intake_id: str,
    review_service: Annotated[WaveUtilReviewService, Depends(get_review_service)],
    actor: Annotated[ActorContext, Depends(get_actor_context)],
    csrf_token: Annotated[str, Form(alias="_csrf_token")],
    candidate_ids: Annotated[list[str], Form()],
    reason: Annotated[str, Form()],
) -> RedirectResponse:
    """
    Reject selected WaveUtil candidates.

    Rejection never changes canonical state.
    """
    # Validate CSRF
    if not validate_csrf_token(csrf_token, request.app.state.settings.csrf_secret):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid CSRF token",
        )

    if not reason or not reason.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Rejection requires a reason",
        )

    try:
        review_service.reject_candidates(candidate_ids, reason, actor)
    except ConcurrencyConflictError as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(e),
        )
    except CandidateNotProposedError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )

    return RedirectResponse(
        url=f"/applications/{app_id}/intakes/{intake_id}/wave-util",
        status_code=status.HTTP_303_SEE_OTHER,
    )


# ─────────────────────────────────────────────────────────────────────────────
# POST /applications/{app}/intakes/{intake}/wave-util/{row}/retire
# ─────────────────────────────────────────────────────────────────────────────


@router.post("/applications/{app_id}/intakes/{intake_id}/wave-util/{row_id}/retire")
async def retire_row(
    request: Request,
    app_id: str,
    intake_id: str,
    row_id: str,
    review_service: Annotated[WaveUtilReviewService, Depends(get_review_service)],
    actor: Annotated[ActorContext, Depends(get_actor_context)],
    csrf_token: Annotated[str, Form(alias="_csrf_token")],
    expected_version: Annotated[int, Form()],
    rationale: Annotated[str, Form()],
    evidence_reference: Annotated[str | None, Form()] = None,
) -> RedirectResponse:
    """
    Retire a WaveUtil row.

    Retirement requires rationale and expected version.
    """
    # Validate CSRF
    if not validate_csrf_token(csrf_token, request.app.state.settings.csrf_secret):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid CSRF token",
        )

    if not rationale or not rationale.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Retirement requires a rationale",
        )

    items = [
        WaveUtilRetireItem(
            row_id=row_id,
            expected_row_version=expected_version,
            rationale=rationale,
            evidence_reference=evidence_reference,
        )
    ]

    try:
        review_service.retire_rows(items, actor)
    except ConcurrencyConflictError as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(e),
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )

    return RedirectResponse(
        url=f"/applications/{app_id}/intakes/{intake_id}/wave-util",
        status_code=status.HTTP_303_SEE_OTHER,
    )
