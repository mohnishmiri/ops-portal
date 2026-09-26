"""
Intake hub route (UX-2).

Route:
- GET /applications/{app_id}/intakes/{intake_id}
    -> the intake's landing page: progress, decisions waiting, section grid

The path is the bare intake resource on purpose. Nothing else claimed it —
``applications.router`` owns ``/applications/{id}`` (two segments) and every
intake-scoped router mounts a further segment (``/questionnaire``,
``/sources``, ``/wave-util``, ``/imports/...``) — so the hub is what you get
when you name an intake and nothing more, which is what a landing page is.

All numbers come from ``IntakeHubService``; this module only shapes them for
the template.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import sessionmaker

from migration_intake.application.services.intake_hub import IntakeHubService

router = APIRouter(tags=["intake-hub"])

_template_dir = Path(__file__).parent.parent / "templates"
templates = Jinja2Templates(directory=str(_template_dir))


def get_session_factory(request: Request) -> sessionmaker:
    """Get session factory from app state."""
    return request.app.state.session_factory


def get_hub_service(
    session_factory: Annotated[sessionmaker, Depends(get_session_factory)],
) -> IntakeHubService:
    """Build the hub read-model service for this request."""
    return IntakeHubService(session_factory)


def _intake_base(app_id: str, intake_id: str) -> str:
    return f"/applications/{app_id}/intakes/{intake_id}"


def _nav_items(app_id: str, intake_id: str) -> list[dict[str, Any]]:
    """Side-rail entries for the intake, with the hub first."""
    base = _intake_base(app_id, intake_id)
    return [
        {"key": "hub", "label": "Intake overview", "href": base},
        {"key": "questionnaire", "label": "Questionnaire", "href": f"{base}/questionnaire"},
        {"key": "sources", "label": "Evidence", "href": f"{base}/sources"},
        {"key": "wave-util", "label": "WaveUtil", "href": f"{base}/wave-util"},
        {"key": "readiness", "label": "Readiness", "href": f"/intakes/{intake_id}/readiness"},
        {"key": "topology", "label": "Topology", "href": f"{base}/topology"},
    ]


@router.get(
    "/applications/{app_id}/intakes/{intake_id}",
    response_class=HTMLResponse,
)
async def intake_hub(
    request: Request,
    app_id: str,
    intake_id: str,
    hub_service: Annotated[IntakeHubService, Depends(get_hub_service)],
) -> HTMLResponse:
    """Render the intake hub."""
    hub = hub_service.get_intake_hub(intake_id)
    if hub is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Intake not found",
        )

    base = _intake_base(app_id, intake_id)

    # "Continue where I left off" aims at the first section holding an
    # unanswered required question a person can actually answer. With nothing
    # outstanding there is still somewhere sensible to go: the questionnaire
    # itself, which redirects to its first section.
    # Section codes carry spaces ("INTAKE CONTROL"), so they are percent-encoded
    # before being spliced into a path.
    continue_code = hub["continue_section"]
    continue_href = (
        f"{base}/questionnaire/{quote(continue_code)}"
        if continue_code
        else f"{base}/questionnaire"
    )

    needs_person_code = hub["needs_person_section"]
    needs_person_href = (
        f"{base}/questionnaire/{quote(needs_person_code)}"
        if needs_person_code
        else f"{base}/questionnaire"
    )

    # Proposal review uses the same sectioned questionnaire workflow.
    review_href = f"{base}/questionnaire"

    return templates.TemplateResponse(
        request=request,
        name="intake/hub.html",
        context={
            "app_id": app_id,
            "intake_id": intake_id,
            "intake_base": base,
            "application": hub["application"],
            "intake": hub["intake"],
            "totals": hub["totals"],
            "sections": hub["sections"],
            "continue_href": continue_href,
            "continue_section": continue_code,
            "needs_person_href": needs_person_href,
            "review_href": review_href,
            "app_name": hub["application"]["display_name"],
            "nav_items": _nav_items(app_id, intake_id),
            "active_nav": "hub",
            "title": f"{hub['application']['display_name']} — intake overview",
        },
    )
