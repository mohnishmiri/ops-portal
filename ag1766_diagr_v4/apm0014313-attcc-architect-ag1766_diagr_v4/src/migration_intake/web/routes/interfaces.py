"""
Interface register routes — list, manual add/edit, candidate accept, retire.

Routes:
- GET  /applications/{app}/intakes/{intake}/interfaces
- GET  /applications/{app}/intakes/{intake}/interfaces/new
- POST /applications/{app}/intakes/{intake}/interfaces
- GET  /applications/{app}/intakes/{intake}/interfaces/{record}
- POST /applications/{app}/intakes/{intake}/interfaces/{record}
- POST /applications/{app}/intakes/{intake}/interfaces/accept
- POST /applications/{app}/intakes/{intake}/interfaces/{record}/retire
- POST /applications/{app}/intakes/{intake}/interfaces/upload
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from starlette.responses import Response

from migration_intake.application.dto import ActorContext
from migration_intake.application.errors import ConcurrencyConflictError
from migration_intake.application.services.interface_review import (
    ApplicationCorrelationIdMissingError,
    CandidateNotProposedError,
    InterfaceCandidateAcceptItem,
    InterfaceCorrelationIdRequiredError,
    InterfaceFields,
    InterfaceReviewService,
    InvalidInterfaceWorkbookError,
)
from migration_intake.persistence.models import Application
from migration_intake.persistence.repositories.candidates import CandidateRepository
from migration_intake.persistence.repositories.interfaces import InterfaceRepository
from migration_intake.web.routes._nav import app_nav_items
from migration_intake.web.security import (
    CONFIGURED_ACTOR_CAPABILITIES,
    generate_csrf_token,
    validate_csrf_token,
)

router = APIRouter(tags=["Interfaces"])

_template_dir = Path(__file__).parent.parent / "templates"
templates = Jinja2Templates(directory=str(_template_dir))


# ─────────────────────────────────────────────────────────────────────────────
# Dependencies
# ─────────────────────────────────────────────────────────────────────────────


def get_actor_context(request: Request) -> ActorContext:
    settings = request.app.state.settings
    return ActorContext(
        actor_id=settings.actor_id,
        display_name=settings.actor_display_name,
        role_codes=CONFIGURED_ACTOR_CAPABILITIES,
    )


def get_review_service(request: Request) -> InterfaceReviewService:
    session_factory = request.app.state.session_factory
    return InterfaceReviewService(session_factory)


def _resolve_app_name(session, app_id: str) -> str:
    return (
        session.execute(
            select(Application.display_name).where(Application.id == app_id)
        ).scalar_one_or_none()
        or ""
    )


def _base_context(app_id: str, intake_id: str, app_name: str, csrf_token: str) -> dict:
    return {
        "csrf_token": csrf_token,
        "app_id": app_id,
        "intake_id": intake_id,
        "app_name": app_name,
        "nav_items": app_nav_items(app_id, intake_id, "interfaces"),
        "active_nav": "interfaces",
        "list_href": f"/applications/{app_id}/intakes/{intake_id}/interfaces",
    }


# ─────────────────────────────────────────────────────────────────────────────
# GET /applications/{app}/intakes/{intake}/interfaces
# ─────────────────────────────────────────────────────────────────────────────


@router.get("/applications/{app_id}/intakes/{intake_id}/interfaces")
async def list_interfaces(
    request: Request,
    app_id: str,
    intake_id: str,
    upload_message: str | None = None,
    upload_message_type: str | None = None,
) -> Response:
    """List the interface register plus any pending import proposals."""
    session_factory = request.app.state.session_factory
    csrf_token = generate_csrf_token(request.app.state.settings.csrf_secret)

    with session_factory() as session:
        interface_repo = InterfaceRepository(session)
        candidate_repo = CandidateRepository(session)

        app_name = _resolve_app_name(session, app_id)
        records = interface_repo.list_records_for_application(app_id, state="ACTIVE")
        records.sort(key=lambda r: r["interface_correlation_id"])

        pending_candidates = [
            candidate
            for candidate in candidate_repo.get_by_intake(intake_id, state="PROPOSED", limit=1000)
            if candidate.target_kind == "INTERFACE_REGISTER"
        ]

    context = _base_context(app_id, intake_id, app_name, csrf_token)
    context.update({
        "records": records,
        "total_records": len(records),
        "upload_message": upload_message,
        "upload_message_type": upload_message_type or "error",
        "pending_candidates": [
            {
                "id": str(c.id),
                "row_version": c.row_version,
                "fields": c.normalized_value_json or {},
            }
            for c in pending_candidates
        ],
    })
    return templates.TemplateResponse(request=request, name="interfaces/list.html", context=context)


def _is_interface_in_scope(record: dict[str, object]) -> bool:
    """Return whether an active interface should appear in scoped views."""
    notes = str(record.get("notes") or "").strip().casefold()
    return "expired" not in notes and "not in scope" not in notes


# ─────────────────────────────────────────────────────────────────────────────
# POST /applications/{app}/intakes/{intake}/interfaces/upload
# ─────────────────────────────────────────────────────────────────────────────


@router.post("/applications/{app_id}/intakes/{intake_id}/interfaces/upload")
async def upload_interfaces_excel(
    request: Request,
    app_id: str,
    intake_id: str,
    review_service: Annotated[InterfaceReviewService, Depends(get_review_service)],
    actor: Annotated[ActorContext, Depends(get_actor_context)],
    csrf_token: Annotated[str, Form(alias="_csrf_token")],
    file: Annotated[UploadFile, File()],
) -> RedirectResponse:
    """Upload a standalone workbook's Interface sheet and populate the register directly."""
    if not validate_csrf_token(csrf_token, request.app.state.settings.csrf_secret):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid CSRF token")

    content = await file.read()
    base_url = f"/applications/{app_id}/intakes/{intake_id}/interfaces"
    if not content:
        return RedirectResponse(
            url=f"{base_url}?upload_message=The+file+is+empty&upload_message_type=error",
            status_code=status.HTTP_303_SEE_OTHER,
        )

    try:
        summary = review_service.import_from_workbook(
            content=content, application_id=app_id, actor=actor
        )
    except InvalidInterfaceWorkbookError as e:
        return RedirectResponse(
            url=f"{base_url}?upload_message={e!s}&upload_message_type=error",
            status_code=status.HTTP_303_SEE_OTHER,
        )

    message = (
        f"Imported {summary['created']} new, {summary['unchanged']} already up to date "
        f"({summary['skipped']} rows skipped, {summary['mismatched_app']} for another application)"
    )
    return RedirectResponse(
        url=f"{base_url}?upload_message={message}&upload_message_type=success",
        status_code=status.HTTP_303_SEE_OTHER,
    )


# ─────────────────────────────────────────────────────────────────────────────
# GET /applications/{app}/intakes/{intake}/interfaces/new
# ─────────────────────────────────────────────────────────────────────────────


@router.get("/applications/{app_id}/intakes/{intake_id}/interfaces/new")
async def new_interface_form(request: Request, app_id: str, intake_id: str) -> Response:
    """Blank add-interface form."""
    session_factory = request.app.state.session_factory
    csrf_token = generate_csrf_token(request.app.state.settings.csrf_secret)

    with session_factory() as session:
        app_name = _resolve_app_name(session, app_id)

    context = _base_context(app_id, intake_id, app_name, csrf_token)
    context.update({"record": None})
    return templates.TemplateResponse(request=request, name="interfaces/form.html", context=context)


# ─────────────────────────────────────────────────────────────────────────────
# POST /applications/{app}/intakes/{intake}/interfaces
# ─────────────────────────────────────────────────────────────────────────────


@router.post("/applications/{app_id}/intakes/{intake_id}/interfaces")
async def create_interface(
    request: Request,
    app_id: str,
    intake_id: str,
    review_service: Annotated[InterfaceReviewService, Depends(get_review_service)],
    actor: Annotated[ActorContext, Depends(get_actor_context)],
    csrf_token: Annotated[str, Form(alias="_csrf_token")],
    interface_correlation_id: Annotated[str, Form()],
    consumer_or_provider: Annotated[str | None, Form()] = None,
    interface_app_acronym: Annotated[str | None, Form()] = None,
    interface_migration_wave: Annotated[str | None, Form()] = None,
    interface_system_location: Annotated[str | None, Form()] = None,
    end_point_name: Annotated[str | None, Form()] = None,
    data_traffic_direction: Annotated[str | None, Form()] = None,
    connection_owner: Annotated[str | None, Form()] = None,
    sync_async: Annotated[str | None, Form()] = None,
    current_protocol: Annotated[str | None, Form()] = None,
    current_interface_type: Annotated[str | None, Form()] = None,
    target_protocol: Annotated[str | None, Form()] = None,
    target_interface_type: Annotated[str | None, Form()] = None,
    interface_impact_change_type: Annotated[str | None, Form()] = None,
    current_port: Annotated[str | None, Form()] = None,
    future_port: Annotated[str | None, Form()] = None,
    encrypted_solution_cloud: Annotated[str | None, Form()] = None,
    low_latency_required: Annotated[str | None, Form()] = None,
    throughput_volume_req: Annotated[str | None, Form()] = None,
    att_architecture_validated: Annotated[str | None, Form()] = None,
    listed_in_itap: Annotated[str | None, Form()] = None,
    engagement_email_sent_on: Annotated[str | None, Form()] = None,
    funding_template_sent: Annotated[str | None, Form()] = None,
    interface_commitment_date: Annotated[str | None, Form()] = None,
    interface_included_in_crp: Annotated[str | None, Form()] = None,
    funding_approved_epic: Annotated[str | None, Form()] = None,
    connectivity_tested: Annotated[str | None, Form()] = None,
    uat_tested: Annotated[str | None, Form()] = None,
    interface_contact: Annotated[str | None, Form()] = None,
    interface_cutover_contact: Annotated[str | None, Form()] = None,
    notes: Annotated[str | None, Form()] = None,
) -> RedirectResponse:
    """Create a new interface record manually."""
    if not validate_csrf_token(csrf_token, request.app.state.settings.csrf_secret):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid CSRF token")

    try:
        review_service.save_manual(
            application_id=app_id,
            record_id=None,
            expected_row_version=None,
            fields=InterfaceFields(
                interface_correlation_id=interface_correlation_id,
                consumer_or_provider=consumer_or_provider,
                interface_app_acronym=interface_app_acronym,
                interface_migration_wave=interface_migration_wave,
                interface_system_location=interface_system_location,
                end_point_name=end_point_name,
                data_traffic_direction=data_traffic_direction,
                connection_owner=connection_owner,
                sync_async=sync_async,
                current_protocol=current_protocol,
                current_interface_type=current_interface_type,
                target_protocol=target_protocol,
                target_interface_type=target_interface_type,
                interface_impact_change_type=interface_impact_change_type,
                current_port=current_port,
                future_port=future_port,
                encrypted_solution_cloud=encrypted_solution_cloud,
                low_latency_required=low_latency_required,
                throughput_volume_req=throughput_volume_req,
                att_architecture_validated=att_architecture_validated,
                listed_in_itap=listed_in_itap,
                engagement_email_sent_on=engagement_email_sent_on,
                funding_template_sent=funding_template_sent,
                interface_commitment_date=interface_commitment_date,
                interface_included_in_crp=interface_included_in_crp,
                funding_approved_epic=funding_approved_epic,
                connectivity_tested=connectivity_tested,
                uat_tested=uat_tested,
                interface_contact=interface_contact,
                interface_cutover_contact=interface_cutover_contact,
                notes=notes,
            ),
            actor=actor,
        )
    except InterfaceCorrelationIdRequiredError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except ApplicationCorrelationIdMissingError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    return RedirectResponse(
        url=f"/applications/{app_id}/intakes/{intake_id}/interfaces",
        status_code=status.HTTP_303_SEE_OTHER,
    )


# ─────────────────────────────────────────────────────────────────────────────
# GET /applications/{app}/intakes/{intake}/interfaces/{record_id}
# ─────────────────────────────────────────────────────────────────────────────


@router.get("/applications/{app_id}/intakes/{intake_id}/interfaces/{record_id}")
async def edit_interface_form(
    request: Request, app_id: str, intake_id: str, record_id: str
) -> Response:
    """Edit form for an existing interface record, prepopulated from its current values."""
    session_factory = request.app.state.session_factory
    csrf_token = generate_csrf_token(request.app.state.settings.csrf_secret)

    with session_factory() as session:
        app_name = _resolve_app_name(session, app_id)
        record = InterfaceRepository(session).get_record(record_id)

    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Interface not found")

    context = _base_context(app_id, intake_id, app_name, csrf_token)
    context.update({"record": record})
    return templates.TemplateResponse(request=request, name="interfaces/form.html", context=context)


# ─────────────────────────────────────────────────────────────────────────────
# POST /applications/{app}/intakes/{intake}/interfaces/{record_id}
# ─────────────────────────────────────────────────────────────────────────────


@router.post("/applications/{app_id}/intakes/{intake_id}/interfaces/{record_id}")
async def update_interface(
    request: Request,
    app_id: str,
    intake_id: str,
    record_id: str,
    review_service: Annotated[InterfaceReviewService, Depends(get_review_service)],
    actor: Annotated[ActorContext, Depends(get_actor_context)],
    csrf_token: Annotated[str, Form(alias="_csrf_token")],
    expected_row_version: Annotated[int, Form()],
    interface_correlation_id: Annotated[str, Form()],
    consumer_or_provider: Annotated[str | None, Form()] = None,
    interface_app_acronym: Annotated[str | None, Form()] = None,
    interface_migration_wave: Annotated[str | None, Form()] = None,
    interface_system_location: Annotated[str | None, Form()] = None,
    end_point_name: Annotated[str | None, Form()] = None,
    data_traffic_direction: Annotated[str | None, Form()] = None,
    connection_owner: Annotated[str | None, Form()] = None,
    sync_async: Annotated[str | None, Form()] = None,
    current_protocol: Annotated[str | None, Form()] = None,
    current_interface_type: Annotated[str | None, Form()] = None,
    target_protocol: Annotated[str | None, Form()] = None,
    target_interface_type: Annotated[str | None, Form()] = None,
    interface_impact_change_type: Annotated[str | None, Form()] = None,
    current_port: Annotated[str | None, Form()] = None,
    future_port: Annotated[str | None, Form()] = None,
    encrypted_solution_cloud: Annotated[str | None, Form()] = None,
    low_latency_required: Annotated[str | None, Form()] = None,
    throughput_volume_req: Annotated[str | None, Form()] = None,
    att_architecture_validated: Annotated[str | None, Form()] = None,
    listed_in_itap: Annotated[str | None, Form()] = None,
    engagement_email_sent_on: Annotated[str | None, Form()] = None,
    funding_template_sent: Annotated[str | None, Form()] = None,
    interface_commitment_date: Annotated[str | None, Form()] = None,
    interface_included_in_crp: Annotated[str | None, Form()] = None,
    funding_approved_epic: Annotated[str | None, Form()] = None,
    connectivity_tested: Annotated[str | None, Form()] = None,
    uat_tested: Annotated[str | None, Form()] = None,
    interface_contact: Annotated[str | None, Form()] = None,
    interface_cutover_contact: Annotated[str | None, Form()] = None,
    notes: Annotated[str | None, Form()] = None,
) -> RedirectResponse:
    """Save edits to an existing interface record."""
    if not validate_csrf_token(csrf_token, request.app.state.settings.csrf_secret):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid CSRF token")

    try:
        review_service.save_manual(
            application_id=app_id,
            record_id=record_id,
            expected_row_version=expected_row_version,
            fields=InterfaceFields(
                interface_correlation_id=interface_correlation_id,
                consumer_or_provider=consumer_or_provider,
                interface_app_acronym=interface_app_acronym,
                interface_migration_wave=interface_migration_wave,
                interface_system_location=interface_system_location,
                end_point_name=end_point_name,
                data_traffic_direction=data_traffic_direction,
                connection_owner=connection_owner,
                sync_async=sync_async,
                current_protocol=current_protocol,
                current_interface_type=current_interface_type,
                target_protocol=target_protocol,
                target_interface_type=target_interface_type,
                interface_impact_change_type=interface_impact_change_type,
                current_port=current_port,
                future_port=future_port,
                encrypted_solution_cloud=encrypted_solution_cloud,
                low_latency_required=low_latency_required,
                throughput_volume_req=throughput_volume_req,
                att_architecture_validated=att_architecture_validated,
                listed_in_itap=listed_in_itap,
                engagement_email_sent_on=engagement_email_sent_on,
                funding_template_sent=funding_template_sent,
                interface_commitment_date=interface_commitment_date,
                interface_included_in_crp=interface_included_in_crp,
                funding_approved_epic=funding_approved_epic,
                connectivity_tested=connectivity_tested,
                uat_tested=uat_tested,
                interface_contact=interface_contact,
                interface_cutover_contact=interface_cutover_contact,
                notes=notes,
            ),
            actor=actor,
        )
    except ConcurrencyConflictError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    except InterfaceCorrelationIdRequiredError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except ApplicationCorrelationIdMissingError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    return RedirectResponse(
        url=f"/applications/{app_id}/intakes/{intake_id}/interfaces",
        status_code=status.HTTP_303_SEE_OTHER,
    )


# ─────────────────────────────────────────────────────────────────────────────
# POST /applications/{app}/intakes/{intake}/interfaces/accept
# ─────────────────────────────────────────────────────────────────────────────


@router.post("/applications/{app_id}/intakes/{intake_id}/interfaces/accept")
async def accept_interface_candidates(
    request: Request,
    app_id: str,
    intake_id: str,
    review_service: Annotated[InterfaceReviewService, Depends(get_review_service)],
    actor: Annotated[ActorContext, Depends(get_actor_context)],
    csrf_token: Annotated[str, Form(alias="_csrf_token")],
    candidate_ids: Annotated[list[str], Form()],
    expected_versions: Annotated[list[int], Form()],
) -> RedirectResponse:
    """Accept selected import-derived interface candidates into the register."""
    if not validate_csrf_token(csrf_token, request.app.state.settings.csrf_secret):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid CSRF token")

    if len(candidate_ids) != len(expected_versions):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Mismatched candidate_ids and expected_versions",
        )

    items = [
        InterfaceCandidateAcceptItem(candidate_id=cid, expected_candidate_version=ver)
        for cid, ver in zip(candidate_ids, expected_versions)
    ]

    try:
        review_service.accept_candidates(items, actor)
    except ConcurrencyConflictError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    except CandidateNotProposedError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    return RedirectResponse(
        url=f"/applications/{app_id}/intakes/{intake_id}/interfaces",
        status_code=status.HTTP_303_SEE_OTHER,
    )


# ─────────────────────────────────────────────────────────────────────────────
# POST /applications/{app}/intakes/{intake}/interfaces/{record_id}/retire
# ─────────────────────────────────────────────────────────────────────────────


@router.post("/applications/{app_id}/intakes/{intake_id}/interfaces/{record_id}/retire")
async def retire_interface(
    request: Request,
    app_id: str,
    intake_id: str,
    record_id: str,
    review_service: Annotated[InterfaceReviewService, Depends(get_review_service)],
    actor: Annotated[ActorContext, Depends(get_actor_context)],
    csrf_token: Annotated[str, Form(alias="_csrf_token")],
    expected_row_version: Annotated[int, Form()],
) -> RedirectResponse:
    """Retire an interface record."""
    if not validate_csrf_token(csrf_token, request.app.state.settings.csrf_secret):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid CSRF token")

    try:
        review_service.retire_record(
            record_id=record_id, expected_row_version=expected_row_version, actor=actor
        )
    except ConcurrencyConflictError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))

    return RedirectResponse(
        url=f"/applications/{app_id}/intakes/{intake_id}/interfaces",
        status_code=status.HTTP_303_SEE_OTHER,
    )
