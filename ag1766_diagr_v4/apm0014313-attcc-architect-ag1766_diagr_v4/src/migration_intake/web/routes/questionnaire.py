"""
Questionnaire routes (UI04).

Routes:
- GET /applications/{app}/intakes/{intake}/questionnaire
    -> redirect to first applicable section
- GET /applications/{app}/intakes/{intake}/questionnaire/{section}
    -> section page with questions
- POST /applications/{app}/intakes/{intake}/questions/{code}/answer
    -> save answer
- POST /applications/{app}/intakes/{intake}/questions/{code}/clear
    -> clear answer
- POST /applications/{app}/intakes/{intake}/questions/{code}/confirm
    -> confirm answer
- POST /applications/{app}/intakes/{intake}/questions/{code}/not-applicable
    -> mark not applicable

Following Jinja2 + HTMX patterns for server-rendered UI.
"""

from __future__ import annotations

import re
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Form, HTTPException, Request, Response, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import sessionmaker

from migration_intake.application.dto import ActorContext
from migration_intake.application.errors import (
    ConcurrencyConflictError,
    IntakeNotOpenError,
    NoCurrentRevisionError,
    QuestionNotFoundError,
)
from migration_intake.application.queries import ApplicationQueryService
from migration_intake.application.services.answers import AnswerService
from migration_intake.web.security import (
    CONFIGURED_ACTOR_CAPABILITIES,
    generate_csrf_token,
    validate_csrf_token,
)

# Router for questionnaire routes
router = APIRouter(tags=["questionnaire"])

# Templates - use absolute path resolution
from pathlib import Path

_template_dir = Path(__file__).parent.parent / "templates"
templates = Jinja2Templates(directory=str(_template_dir))


def get_session_factory(request: Request) -> sessionmaker:
    """Get session factory from app state."""
    return request.app.state.session_factory


def get_query_service(
    session_factory: Annotated[sessionmaker, Depends(get_session_factory)]
) -> ApplicationQueryService:
    """Get query service."""
    return ApplicationQueryService(session_factory)


def get_answer_service(request: Request) -> AnswerService:
    """Get answer service from app state."""
    return request.app.state.answer_service


#: ``name[index].field`` inputs, the HTML shape for a list-of-objects payload
#: such as CONTROLLED_SET's ``items`` or PEOPLE_LIST's ``people``.
_INDEXED_FIELD = re.compile(r"^(?P<name>[A-Za-z_]\w*)\[(?P<index>\d+)\]\.(?P<field>\w+)$")


def _shape_submitted_fields(items: list[tuple[str, Any]]) -> dict[str, Any]:
    """
    Shape raw form items into the structure the response types parse.

    ``FormData.items()`` keeps only the **last** value of a repeated key, so a
    checkbox group posting ``values=A&values=C`` reached the response type as
    ``{"values": "C"}`` and silently stored a single selection. Repeated keys
    are therefore grouped into a list here, and ``name[index].field`` inputs
    are folded into the list-of-objects shape the collection types require.

    Underscore-prefixed fields are the form's own hidden plumbing (CSRF,
    schema version, concurrency token) and never part of the payload.
    """
    flat: dict[str, list[Any]] = {}
    rows: dict[str, dict[int, dict[str, Any]]] = {}

    for key, value in items:
        if key.startswith("_"):
            continue
        indexed = _INDEXED_FIELD.match(key)
        if indexed is not None:
            group = rows.setdefault(indexed["name"], {})
            group.setdefault(int(indexed["index"]), {})[indexed["field"]] = value
            continue
        flat.setdefault(key, []).append(value)

    shaped: dict[str, Any] = {
        key: (values[0] if len(values) == 1 else values)
        for key, values in flat.items()
    }
    for name, group in rows.items():
        shaped[name] = [group[index] for index in sorted(group)]
    return shaped


def _parse_submitted_answer(
    request: Request,
    intake_id: str,
    question_code: str,
    submitted: dict,
) -> dict:
    """
    Turn raw form fields into the question's canonical response payload.

    Raises 400 when the submitted field names map to nothing this response
    type understands — that means the editor template and the response type
    disagree, and storing the result would silently blank the answer.
    """
    from migration_intake.catalog.response_types import get_default_registry
    from migration_intake.persistence.repositories.catalogs import CatalogRepository
    from migration_intake.persistence.repositories.intakes import IntakeRepository

    session = request.app.state.session_factory()
    try:
        intake = IntakeRepository(session).get(intake_id)
        if intake is None:
            return submitted
        question = CatalogRepository(session).get_question_by_code(
            intake["catalog_id"], question_code
        )
    finally:
        session.close()

    if question is None:
        return submitted
    response_type = get_default_registry().get(question["response_type"])
    if response_type is None:
        return submitted

    parsed = response_type.parse_form_strict(submitted)
    if not parsed.is_success:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"{question_code} ({question['response_type']}): "
                + "; ".join(parsed.errors)
            ),
        )
    return parsed.value or submitted


def _wants_json(request: Request) -> bool:
    """
    True when the caller asked for JSON rather than a redirect.

    Autosave cannot use the redirect response: the browser would follow it and
    throw away the page the user is still typing into. More importantly the
    client has to learn the **new revision number**, because
    ``AnswerService.save_answer`` compares ``expected_version`` against the
    current revision number — re-posting the token the page was rendered with
    makes the second edit of the same field a 409.
    """
    return "application/json" in request.headers.get("accept", "")


def get_actor_context(request: Request) -> ActorContext:
    """Get actor context from app state."""
    # ActorContext.actor_id is a plain string: wrapping it in the ActorId
    # value object reaches persistence as an unsupported bind parameter and
    # 500s every questionnaire write.
    return ActorContext(
        actor_id=str(request.app.state.settings.actor_id),
        display_name=request.app.state.settings.actor_display_name,
        role_codes=CONFIGURED_ACTOR_CAPABILITIES,
    )


# ---------------------------------------------------------------------------
# GET /applications/{app}/intakes/{intake}/questionnaire
# ---------------------------------------------------------------------------


@router.get(
    "/applications/{app_id}/intakes/{intake_id}/questionnaire",
    response_class=HTMLResponse,
)
async def questionnaire_redirect(
    request: Request,
    app_id: str,
    intake_id: str,
    query_service: Annotated[ApplicationQueryService, Depends(get_query_service)],
) -> RedirectResponse:
    """
    Redirect to first applicable section.

    If no sections exist, render an empty catalog state page.
    """
    page = query_service.get_questionnaire_page(intake_id)

    if page is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Intake not found",
        )

    if not page["sections"]:
        # No sections - render empty state
        csrf_token = generate_csrf_token(request.app.state.settings.csrf_secret)
        return templates.TemplateResponse(
            request=request,
            name="questionnaire/empty.html",
            context={
                "csrf_token": csrf_token,
                "application": page["application"],
                "intake": page["intake"],
            },
        )

    # Redirect to first section
    first_section = page["sections"][0]["code"]
    return RedirectResponse(
        url=f"/applications/{app_id}/intakes/{intake_id}/questionnaire/{first_section}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


# ---------------------------------------------------------------------------
# GET /applications/{app}/intakes/{intake}/questionnaire/{section}
# ---------------------------------------------------------------------------


@router.get(
    "/applications/{app_id}/intakes/{intake_id}/questionnaire/{section_code}",
    response_class=HTMLResponse,
)
async def questionnaire_section(
    request: Request,
    app_id: str,
    intake_id: str,
    section_code: str,
    query_service: Annotated[ApplicationQueryService, Depends(get_query_service)],
) -> HTMLResponse:
    """
    Render a questionnaire section page.
    """
    page = query_service.get_questionnaire_page(intake_id, section_code)

    if page is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Intake or section not found",
        )

    csrf_token = generate_csrf_token(request.app.state.settings.csrf_secret)

    return templates.TemplateResponse(
        request=request,
        name="questionnaire/section.html",
        context={
            "csrf_token": csrf_token,
            "app_id": app_id,
            "intake_id": intake_id,
            # base.html's command bar reads app_name; without it the
            # questionnaire showed no application identity at all.
            "app_name": page["application"]["display_name"],
            "application": page["application"],
            "intake": page["intake"],
            "sections": page["sections"],
            "overall_status": page["overall_status"],
            "current_section": page["current_section"],
            "questions": page["questions"],
        },
    )


# ---------------------------------------------------------------------------
# POST /applications/{app}/intakes/{intake}/questions/{code}/answer
# ---------------------------------------------------------------------------


@router.post(
    "/applications/{app_id}/intakes/{intake_id}/questions/{question_code}/answer",
)
async def save_answer(
    request: Request,
    app_id: str,
    intake_id: str,
    question_code: str,
    answer_service: Annotated[AnswerService, Depends(get_answer_service)],
    actor: Annotated[ActorContext, Depends(get_actor_context)],
    csrf_token: Annotated[str, Form(alias="_csrf_token")],
    schema_version: Annotated[str, Form(alias="_schema_version")] = "1.0",
    row_version: Annotated[int | None, Form(alias="_row_version")] = None,
) -> Response:
    """
    Save an answer for a question.

    Form data is parsed based on response type.

    Returns a 303 redirect for a plain form post, and JSON carrying the new
    revision number when the caller asked for it (autosave) — see
    ``_wants_json``.
    """
    as_json = _wants_json(request)

    # Validate CSRF
    if not validate_csrf_token(csrf_token, request.app.state.settings.csrf_secret):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid CSRF token",
        )

    # Parse form data (excluding hidden fields)
    form_data = await request.form()
    response_data = _shape_submitted_fields(form_data.multi_items())

    # Coerce the submitted field names into this question's canonical payload
    # at the boundary. Passing raw form names through meant an editor whose
    # inputs disagreed with the canonical keys silently stored a blank answer.
    try:
        response_data = _parse_submitted_answer(
            request, intake_id, question_code, response_data
        )

        # Call answer service directly (not via command)
        result = answer_service.save_answer(
            intake_id=intake_id,
            question_code=question_code,
            response_json=response_data,
            actor=actor,
            expected_version=row_version,
            change_reason="",
            response_schema_version=schema_version,
        )

    except HTTPException as exc:
        # A validation rejection from _parse_submitted_answer. Autosave has to
        # render this beside the field rather than replacing the page with an
        # error document the user cannot type their way out of.
        if not as_json:
            raise
        return JSONResponse(
            {"ok": False, "error": str(exc.detail)}, status_code=exc.status_code
        )
    except IntakeNotOpenError:
        if as_json:
            return JSONResponse(
                {"ok": False, "error": "This intake is closed for editing."},
                status_code=status.HTTP_400_BAD_REQUEST,
            )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Intake is not open for editing",
        )
    except QuestionNotFoundError:
        if as_json:
            return JSONResponse(
                {"ok": False, "error": "Question not found."},
                status_code=status.HTTP_404_NOT_FOUND,
            )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Question not found",
        )
    except ConcurrencyConflictError:
        if as_json:
            return JSONResponse(
                {
                    "ok": False,
                    "conflict": True,
                    "error": (
                        "Someone else changed this answer. "
                        "Reload the section to see the current value."
                    ),
                },
                status_code=status.HTTP_409_CONFLICT,
            )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Answer was modified by another user",
        )

    if as_json:
        # ``revision_number`` is absent when the save was a semantic no-op, in
        # which case the token the client already holds is still current.
        return JSONResponse(
            {
                "ok": True,
                "changed": bool(result.get("changed")),
                "revision_number": result.get("revision_number"),
                "question_code": question_code,
            }
        )

    # Redirect back to section (determine section from question)
    # For now, redirect to questionnaire root which will go to first section
    return RedirectResponse(
        url=f"/applications/{app_id}/intakes/{intake_id}/questionnaire",
        status_code=status.HTTP_303_SEE_OTHER,
    )


# ---------------------------------------------------------------------------
# POST /applications/{app}/intakes/{intake}/questions/{code}/clear
# ---------------------------------------------------------------------------


@router.post(
    "/applications/{app_id}/intakes/{intake_id}/questions/{question_code}/clear",
)
async def clear_answer(
    request: Request,
    app_id: str,
    intake_id: str,
    question_code: str,
    answer_service: Annotated[AnswerService, Depends(get_answer_service)],
    actor: Annotated[ActorContext, Depends(get_actor_context)],
    csrf_token: Annotated[str, Form(alias="_csrf_token")],
) -> RedirectResponse:
    """
    Clear an answer for a question.
    """
    # Validate CSRF
    if not validate_csrf_token(csrf_token, request.app.state.settings.csrf_secret):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid CSRF token",
        )

    try:
        # Clear by saving empty response
        answer_service.save_answer(
            intake_id=intake_id,
            question_code=question_code,
            response_json={},
            actor=actor,
            expected_version=None,
            change_reason="Cleared by user",
            response_schema_version="1.0",
        )

    except IntakeNotOpenError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Intake is not open for editing",
        )
    except QuestionNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Question not found",
        )

    return RedirectResponse(
        url=f"/applications/{app_id}/intakes/{intake_id}/questionnaire",
        status_code=status.HTTP_303_SEE_OTHER,
    )


# ---------------------------------------------------------------------------
# POST /applications/{app}/intakes/{intake}/questions/{code}/confirm
# ---------------------------------------------------------------------------


@router.post(
    "/applications/{app_id}/intakes/{intake_id}/questions/{question_code}/confirm",
)
async def confirm_answer(
    request: Request,
    app_id: str,
    intake_id: str,
    question_code: str,
    answer_service: Annotated[AnswerService, Depends(get_answer_service)],
    actor: Annotated[ActorContext, Depends(get_actor_context)],
    csrf_token: Annotated[str, Form(alias="_csrf_token")],
) -> RedirectResponse:
    """
    Confirm an answer for a question.

    Confirm the current answer revision when one has been saved.
    """
    # Validate CSRF
    if not validate_csrf_token(csrf_token, request.app.state.settings.csrf_secret):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid CSRF token",
        )

    try:
        answer_service.confirm_answer(
            intake_id=intake_id,
            question_code=question_code,
            actor=actor,
        )
    except NoCurrentRevisionError:
        # Keep the form post idempotent when the question has not been saved.
        pass

    return RedirectResponse(
        url=f"/applications/{app_id}/intakes/{intake_id}/questionnaire",
        status_code=status.HTTP_303_SEE_OTHER,
    )


# ---------------------------------------------------------------------------
# POST /applications/{app}/intakes/{intake}/questions/{code}/not-applicable
# ---------------------------------------------------------------------------


@router.post(
    "/applications/{app_id}/intakes/{intake_id}/questions/{question_code}/not-applicable",
)
async def mark_not_applicable(
    request: Request,
    app_id: str,
    intake_id: str,
    question_code: str,
    csrf_token: Annotated[str, Form(alias="_csrf_token")],
) -> RedirectResponse:
    """
    Mark a question as not applicable.

    TODO: Implement N/A logic in answer service.
    """
    # Validate CSRF
    if not validate_csrf_token(csrf_token, request.app.state.settings.csrf_secret):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid CSRF token",
        )

    # TODO: Implement N/A in answer service

    return RedirectResponse(
        url=f"/applications/{app_id}/intakes/{intake_id}/questionnaire",
        status_code=status.HTTP_303_SEE_OTHER,
    )
