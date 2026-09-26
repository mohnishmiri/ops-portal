"""
Topology generation routes — T05.

Routes:
- GET  /applications/{app_id}/intakes/{intake_id}/topology
      -> Topology generation landing page
- POST /applications/{app_id}/intakes/{intake_id}/topology/upload-base
      -> Upload base diagram
- POST /applications/{app_id}/intakes/{intake_id}/topology/generate
    -> Generate topology from an official snapshot or draft answers
- POST /applications/{app_id}/intakes/{intake_id}/topology/generate-standard
    -> Generate topology from bundled standard template
- GET  /applications/{app_id}/intakes/{intake_id}/topology/runs/{run_id}
      -> View generation run details
- GET  /applications/{app_id}/intakes/{intake_id}/topology/runs/{run_id}/diagram
      -> Download generated diagram
- GET  /applications/{app_id}/intakes/{intake_id}/topology/runs/{run_id}/report
      -> Download gap report
- POST /applications/{app_id}/intakes/{intake_id}/topology/runs/{run_id}/approval
    -> Approve or reject an official generation run
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Annotated, cast

from fastapi import APIRouter, Depends, Form, HTTPException, Request, UploadFile, status
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from sqlalchemy import select

from migration_intake.application.dto import ActorContext
from migration_intake.application.services.topology_generation import (
    IntakeNotFrozenError,
    InvalidBaseDiagramError,
    NoSnapshotError,
    TopologyApprovalError,
    TopologyGenerationService,
    TopologyNotReadyError,
)
from migration_intake.application.services.topology_review import TopologyReviewService
from migration_intake.application.services.topology_runner import (
    GovernedRunnerError,
    GovernedTopologyRunner,
    PersistedLabelRenderer,
)
from migration_intake.persistence.models import Application, Intake
from migration_intake.persistence.repositories.snapshots import SnapshotRepository
from migration_intake.persistence.repositories.topology import TopologyRepository
from migration_intake.storage.filesystem import FilesystemStore
from migration_intake.topology.contracts import RenderCapability
from migration_intake.topology.scope import ContextKey, ScopeSelection
from migration_intake.topology.strict_projection import StrictFactMapping
from migration_intake.web.routes._nav import app_nav_items
from migration_intake.web.security import (
    CONFIGURED_ACTOR_CAPABILITIES,
    Capability,
    generate_csrf_token,
    require_capability,
    validate_csrf_token,
)

if TYPE_CHECKING:
    from sqlalchemy.orm import Session, sessionmaker

router = APIRouter(tags=["topology"])

# Template setup
_TEMPLATES_DIR = Path(__file__).parent.parent / "templates"
_templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))


def get_session_factory(request: Request) -> sessionmaker[Session]:
    """Get session factory from app state."""
    return cast("sessionmaker[Session]", request.app.state.session_factory)


def get_actor_context(request: Request) -> ActorContext:
    """Get actor context from app settings."""
    settings = request.app.state.settings
    return ActorContext(
        actor_id=settings.actor_id,
        display_name=settings.actor_display_name,
        role_codes=CONFIGURED_ACTOR_CAPABILITIES,
    )


def get_topology_service(
    request: Request,
    session_factory: Annotated[object, Depends(get_session_factory)],
) -> TopologyGenerationService:
    """Get topology generation service."""
    return TopologyGenerationService(
        cast("sessionmaker[Session]", session_factory),
        request.app.state.settings.evidence_root,
    )


_PREVIEW_MAPPINGS = (
    StrictFactMapping("CTL-002", "TEXT_PAIR", "application.name", "TEXT_PAIR.first"),
    StrictFactMapping("CTL-002", "TEXT_PAIR", "application.acronym", "TEXT_PAIR.second"),
)


def get_topology_review_service(request: Request) -> TopologyReviewService:
    """Build receipt-verifying artifact delivery service."""
    storage = FilesystemStore(request.app.state.settings.evidence_root / "topology")
    return TopologyReviewService(request.app.state.session_factory, storage)


def get_governed_preview_runner(request: Request) -> GovernedTopologyRunner:
    """Build the governed preview runner; official generation remains separate."""
    storage = FilesystemStore(request.app.state.settings.evidence_root / "topology")
    factory = request.app.state.session_factory
    return GovernedTopologyRunner(
        factory,
        storage,
        PersistedLabelRenderer(factory, storage),
    )


def _resolve_app_context(
    intake_id: str, session_factory: object
) -> tuple[str | None, str | None]:
    """Returns (app_id, app_display_name) for an intake."""
    factory = cast("sessionmaker[Session]", session_factory)
    with factory() as session:
        row = session.execute(
            select(Intake.application_id, Application.display_name)
            .join(Application, Application.id == Intake.application_id)
            .where(Intake.id == intake_id)
        ).first()
    if row is None:
        return None, None
    return str(row.application_id), str(row.display_name)


def _require_intake_scope(
    app_id: str, intake_id: str, session_factory: object
) -> tuple[str, str]:
    """Resolve and validate the application/intake URL scope."""
    resolved_app_id, app_name = _resolve_app_context(intake_id, session_factory)
    if resolved_app_id is None or resolved_app_id != app_id:
        raise HTTPException(status_code=404, detail="Intake not found")
    return resolved_app_id, app_name or ""


def _get_intake_state(intake_id: str, session_factory: object) -> str | None:
    """Get the state of an intake."""
    factory = cast("sessionmaker[Session]", session_factory)
    with factory() as session:
        row = session.execute(select(Intake.state).where(Intake.id == intake_id)).first()
    if row is None:
        return None
    return str(row.state)


# ─────────────────────────────────────────────────────────────────────────────
# Landing page
# ─────────────────────────────────────────────────────────────────────────────


@router.get(
    "/applications/{app_id}/intakes/{intake_id}/topology",
    response_class=HTMLResponse,
)
async def topology_landing(
    request: Request,
    app_id: str,
    intake_id: str,
    session_factory: Annotated[object, Depends(get_session_factory)],
    topology_service: Annotated[TopologyGenerationService, Depends(get_topology_service)],
) -> HTMLResponse:
    """Render the topology generation landing page."""
    _, app_name = _require_intake_scope(app_id, intake_id, session_factory)

    nav_items = app_nav_items(app_id, intake_id, "topology")
    csrf_token = generate_csrf_token(request.app.state.settings.csrf_secret)

    # Get intake state
    intake_state = _get_intake_state(intake_id, session_factory)

    # Get snapshot if frozen
    snapshot = None
    if intake_state == "FROZEN":
        factory = cast("sessionmaker[Session]", session_factory)
        with factory() as session:
            snapshot_repo = SnapshotRepository(session)
            snapshot = snapshot_repo.get_by_intake_id(intake_id)

    # Get base artifacts and generation runs
    base_artifacts = topology_service.list_base_artifacts(intake_id)
    runs = topology_service.list_generation_runs(intake_id)

    # Add status tone for display
    for run in runs:
        run["status_tone"] = _status_to_tone(run["status"])
        run["authority"] = run.get("authority") or (
            "SNAPSHOT_PINNED" if run.get("snapshot_id") else "LEGACY_UNPINNED"
        )

    return _templates.TemplateResponse(
        request,
        "topology/index.html",
        {
            "app_id": app_id,
            "app_name": app_name,
            "intake_id": intake_id,
            "intake_state": intake_state,
            "intake_base": f"/applications/{app_id}/intakes/{intake_id}",
            "snapshot": snapshot,
            "base_artifacts": base_artifacts,
            "runs": runs,
            "nav_items": nav_items,
            "active_nav": "topology",
            "csrf_token": csrf_token,
            "readiness_href": f"/intakes/{intake_id}/readiness",
            "generation_enabled": request.app.state.settings.topology_generation_enabled,
        },
    )


# ─────────────────────────────────────────────────────────────────────────────
# Upload base diagram
# ─────────────────────────────────────────────────────────────────────────────


@router.post(
    "/applications/{app_id}/intakes/{intake_id}/topology/upload-base",
    response_class=HTMLResponse,
)
async def upload_base_diagram(
    request: Request,
    app_id: str,
    intake_id: str,
    session_factory: Annotated[object, Depends(get_session_factory)],
    topology_service: Annotated[TopologyGenerationService, Depends(get_topology_service)],
    actor: Annotated[ActorContext, Depends(get_actor_context)],
    csrf_token: Annotated[str | None, Form(alias="_csrf_token")] = None,
    base_diagram: UploadFile | None = None,
    environment: Annotated[str | None, Form()] = None,
    site: Annotated[str | None, Form()] = None,
    variant: Annotated[str | None, Form()] = "default",
) -> Response:
    """Upload a base diagram for topology generation."""
    _require_intake_scope(app_id, intake_id, session_factory)
    require_capability(set(actor.role_codes), Capability.TOPOLOGY_BASE_UPLOAD)

    # Validate CSRF
    if not csrf_token or not validate_csrf_token(
        csrf_token, request.app.state.settings.csrf_secret
    ):
        raise HTTPException(status_code=403, detail="CSRF token missing or invalid")

    if base_diagram is None:
        raise HTTPException(status_code=400, detail="No file uploaded")

    content = await _read_upload_with_limit(
        base_diagram,
        request.app.state.settings.max_topology_base_bytes,
    )
    if len(content) == 0:
        raise HTTPException(status_code=400, detail="Empty file uploaded")

    try:
        topology_service.upload_base_diagram(
            intake_id=intake_id,
            file_bytes=content,
            filename=base_diagram.filename or "diagram.drawio",
            actor=actor,
            environment=environment,
            site=site,
            variant=variant,
        )
    except InvalidBaseDiagramError as e:
        raise HTTPException(
            status_code=400,
            detail=f"{e}: {'; '.join(e.details)}" if e.details else str(e),
        ) from e
    except Exception as error:
        raise HTTPException(status_code=500, detail="Base diagram upload failed") from error

    # Redirect back to topology page
    return RedirectResponse(
        url=f"/applications/{app_id}/intakes/{intake_id}/topology",
        status_code=status.HTTP_303_SEE_OTHER,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Generate topology
# ─────────────────────────────────────────────────────────────────────────────


@router.post(
    "/applications/{app_id}/intakes/{intake_id}/topology/generate",
    response_class=HTMLResponse,
)
async def generate_topology(
    request: Request,
    app_id: str,
    intake_id: str,
    session_factory: Annotated[object, Depends(get_session_factory)],
    topology_service: Annotated[TopologyGenerationService, Depends(get_topology_service)],
    actor: Annotated[ActorContext, Depends(get_actor_context)],
    csrf_token: Annotated[str | None, Form(alias="_csrf_token")] = None,
    base_artifact_id: Annotated[str | None, Form()] = None,
) -> Response:
    """Generate topology from a frozen snapshot or current draft answers."""
    _require_intake_scope(app_id, intake_id, session_factory)
    require_capability(set(actor.role_codes), Capability.TOPOLOGY_GENERATE)

    # Validate CSRF
    if not csrf_token or not validate_csrf_token(
        csrf_token, request.app.state.settings.csrf_secret
    ):
        raise HTTPException(status_code=403, detail="CSRF token missing or invalid")

    if not base_artifact_id:
        raise HTTPException(status_code=400, detail="No base diagram selected")

    try:
        run = topology_service.generate_topology(
            intake_id=intake_id,
            base_artifact_id=base_artifact_id,
            actor=actor,
        )
    except TopologyNotReadyError as e:
        _, app_name = _require_intake_scope(app_id, intake_id, session_factory)
        nav_items = app_nav_items(app_id, intake_id, "topology")
        return _templates.TemplateResponse(
            request,
            "topology/not_ready.html",
            {
                "app_id": app_id,
                "app_name": app_name,
                "intake_id": intake_id,
                "intake_base": f"/applications/{app_id}/intakes/{intake_id}",
                "readiness": e.readiness,
                "nav_items": nav_items,
                "active_nav": "topology",
            },
            status_code=400,
        )
    except InvalidBaseDiagramError as e:
        detail = str(e)
        if e.details:
            detail = f"{detail}: {'; '.join(e.details)}"
        raise HTTPException(status_code=400, detail=detail) from e
    except (IntakeNotFrozenError, NoSnapshotError) as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    # Redirect to run detail page
    return RedirectResponse(
        url=f"/applications/{app_id}/intakes/{intake_id}/topology/runs/{run['id']}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Generate from standard (bundled) template
# ─────────────────────────────────────────────────────────────────────────────


@router.post(
    "/applications/{app_id}/intakes/{intake_id}/topology/generate-standard",
    response_class=HTMLResponse,
)
async def generate_from_standard_template(
    request: Request,
    app_id: str,
    intake_id: str,
    session_factory: Annotated[object, Depends(get_session_factory)],
    topology_service: Annotated[TopologyGenerationService, Depends(get_topology_service)],
    actor: Annotated[ActorContext, Depends(get_actor_context)],
    csrf_token: Annotated[str | None, Form(alias="_csrf_token")] = None,
    variant: Annotated[str | None, Form()] = None,
) -> Response:
    """Generate topology using the bundled standard template."""
    _require_intake_scope(app_id, intake_id, session_factory)
    require_capability(set(actor.role_codes), Capability.TOPOLOGY_GENERATE)

    if not csrf_token or not validate_csrf_token(
        csrf_token, request.app.state.settings.csrf_secret
    ):
        raise HTTPException(status_code=403, detail="CSRF token missing or invalid")

    if not variant:
        raise HTTPException(status_code=400, detail="No variant selected")

    try:
        run = topology_service.generate_from_standard_template(
            intake_id=intake_id,
            variant=variant,
            actor=actor,
        )
    except TopologyNotReadyError as e:
        _, app_name = _require_intake_scope(app_id, intake_id, session_factory)
        nav_items = app_nav_items(app_id, intake_id, "topology")
        return _templates.TemplateResponse(
            request,
            "topology/not_ready.html",
            {
                "app_id": app_id,
                "app_name": app_name,
                "intake_id": intake_id,
                "intake_base": f"/applications/{app_id}/intakes/{intake_id}",
                "readiness": e.readiness,
                "nav_items": nav_items,
                "active_nav": "topology",
            },
            status_code=400,
        )
    except (IntakeNotFrozenError, NoSnapshotError) as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    return RedirectResponse(
        url=f"/applications/{app_id}/intakes/{intake_id}/topology/runs/{run['id']}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post(
    "/applications/{app_id}/intakes/{intake_id}/topology/preview",
    response_class=HTMLResponse,
)
async def generate_governed_preview(
    request: Request,
    app_id: str,
    intake_id: str,
    session_factory: Annotated[object, Depends(get_session_factory)],
    actor: Annotated[ActorContext, Depends(get_actor_context)],
    runner: Annotated[GovernedTopologyRunner, Depends(get_governed_preview_runner)],
    csrf_token: Annotated[str | None, Form(alias="_csrf_token")] = None,
    base_artifact_id: Annotated[str | None, Form()] = None,
    capability: Annotated[str, Form()] = "LABEL_ONLY",
    environment: Annotated[str, Form()] = "PROD",
    site_id: Annotated[str, Form()] = "SITE_A",
    page_name: Annotated[str, Form()] = "Overview",
) -> Response:
    """Generate only a governed immutable draft preview."""
    _require_intake_scope(app_id, intake_id, session_factory)
    require_capability(set(actor.role_codes), Capability.TOPOLOGY_GENERATE)
    if not csrf_token or not validate_csrf_token(
        csrf_token, request.app.state.settings.csrf_secret
    ):
        raise HTTPException(status_code=403, detail="CSRF token missing or invalid")
    if not base_artifact_id:
        raise HTTPException(status_code=400, detail="No governed base diagram selected")
    try:
        selected_capability = RenderCapability(capability)
    except ValueError as error:
        raise HTTPException(status_code=400, detail="Unknown topology capability") from error
    selection = ScopeSelection(
        app_id,
        intake_id,
        (ContextKey(environment, site_id),),
        "combined-overview-with-details",
    )
    factory = cast("sessionmaker[Session]", session_factory)
    with factory() as session:
        base = TopologyRepository(session).get_base_artifact(base_artifact_id)
        if base is None or base["application_id"] != app_id or base["intake_id"] != intake_id:
            raise HTTPException(status_code=404, detail="Governed base diagram not found")
        if base["review_state"] != "APPROVED" or not base["compatibility_id"]:
            raise HTTPException(status_code=409, detail="Governed base diagram is not approved")
        compatibility = TopologyRepository(session).get_topology_compatibility(
            str(base["compatibility_id"])
        )
    if compatibility is None:
        raise HTTPException(status_code=409, detail="Governed compatibility pin is unavailable")
    try:
        run = runner.run_preview(
            selection=selection,
            partition_views={selection.ordered_contexts[0]: page_name},
            mappings=_PREVIEW_MAPPINGS,
            capability=selected_capability,
            base_artifact_id=base_artifact_id,
            requested_by_id=actor.actor_id,
            generator_version="governed-preview-v1",
            parser_policy_hash=str(compatibility["parser_policy_hash"]),
            layout_policy_hash="0" * 64,
            result_policy_hash="1" * 64,
        )
    except GovernedRunnerError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    return RedirectResponse(
        url=f"/applications/{app_id}/intakes/{intake_id}/topology/runs/{run['id']}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


# ─────────────────────────────────────────────────────────────────────────────
# View generation run
# ─────────────────────────────────────────────────────────────────────────────


@router.get(
    "/applications/{app_id}/intakes/{intake_id}/topology/runs/{run_id}",
    response_class=HTMLResponse,
)
async def view_generation_run(
    request: Request,
    app_id: str,
    intake_id: str,
    run_id: str,
    session_factory: Annotated[object, Depends(get_session_factory)],
    topology_service: Annotated[TopologyGenerationService, Depends(get_topology_service)],
) -> HTMLResponse:
    """View details of a generation run."""
    _, app_name = _require_intake_scope(app_id, intake_id, session_factory)

    run = topology_service.get_generation_run_for_intake(
        run_id,
        app_id,
        intake_id,
    )
    if run is None:
        raise HTTPException(status_code=404, detail="Generation run not found")

    artifacts = topology_service.get_run_artifacts(run_id)

    nav_items = app_nav_items(app_id, intake_id, "topology")
    csrf_token = generate_csrf_token(request.app.state.settings.csrf_secret)

    # Separate artifacts by type
    diagram_artifact = next((a for a in artifacts if a["artifact_type"] == "DIAGRAM"), None)
    report_artifact = next((a for a in artifacts if a["artifact_type"] == "GAP_REPORT"), None)
    manifest_artifact = next((a for a in artifacts if a["artifact_type"] == "MANIFEST"), None)
    authority = run.get("authority") or (
        "SNAPSHOT_PINNED" if run.get("snapshot_id") else "LEGACY_UNPINNED"
    )
    phase = run.get("phase") or run.get("status")
    preview = run.get("mode") == "DRAFT_PREVIEW" or authority == "DRAFT_PREVIEW"
    inspection_ready = (
        phase == "COMPLETED"
        and run.get("status") in {"READY_FOR_REVIEW", "GENERATED_WITH_GAPS"}
        and diagram_artifact is not None
        and report_artifact is not None
        and manifest_artifact is not None
    )

    return _templates.TemplateResponse(
        request,
        "topology/run_detail.html",
        {
            "app_id": app_id,
            "app_name": app_name,
            "intake_id": intake_id,
            "intake_base": f"/applications/{app_id}/intakes/{intake_id}",
            "run": run,
            "run_status_tone": _status_to_tone(run["status"]),
            "diagram_artifact": diagram_artifact,
            "report_artifact": report_artifact,
            "manifest_artifact": manifest_artifact,
            "authority": authority,
            "phase": phase,
            "is_preview": preview,
            "inspection_ready": inspection_ready,
            "approval_available": False,
            "nav_items": nav_items,
            "active_nav": "topology",
            "csrf_token": csrf_token,
            "generation_enabled": request.app.state.settings.topology_generation_enabled,
        },
    )


@router.post(
    "/applications/{app_id}/intakes/{intake_id}/topology/runs/{run_id}/approval",
    response_class=HTMLResponse,
)
async def review_generation_run(
    request: Request,
    app_id: str,
    intake_id: str,
    run_id: str,
    session_factory: Annotated[object, Depends(get_session_factory)],
    topology_service: Annotated[TopologyGenerationService, Depends(get_topology_service)],
    actor: Annotated[ActorContext, Depends(get_actor_context)],
    csrf_token: Annotated[str | None, Form(alias="_csrf_token")] = None,
    decision: Annotated[str, Form()] = "REJECTED",
    rationale: Annotated[str | None, Form()] = None,
) -> Response:
    """Approve or reject an official topology generation run."""
    _require_intake_scope(app_id, intake_id, session_factory)
    _require_topology_generation_enabled(request)
    if not csrf_token or not validate_csrf_token(
        csrf_token, request.app.state.settings.csrf_secret
    ):
        raise HTTPException(status_code=403, detail="CSRF token missing or invalid")
    require_capability(set(actor.role_codes), Capability.TOPOLOGY_APPROVE)
    if decision not in {"APPROVED", "REJECTED"}:
        raise HTTPException(status_code=400, detail="Invalid approval decision")

    try:
        topology_service.approve_generation_run(
            run_id,
            app_id,
            intake_id,
            actor,
            approved=decision == "APPROVED",
            rationale=rationale or "",
        )
    except TopologyApprovalError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    return RedirectResponse(
        url=f"/applications/{app_id}/intakes/{intake_id}/topology/runs/{run_id}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Download artifacts
# ─────────────────────────────────────────────────────────────────────────────


@router.get(
    "/applications/{app_id}/intakes/{intake_id}/topology/runs/{run_id}/diagram",
)
async def download_diagram(
    app_id: str,
    intake_id: str,
    run_id: str,
    topology_service: Annotated[TopologyGenerationService, Depends(get_topology_service)],
    review_service: Annotated[TopologyReviewService, Depends(get_topology_review_service)],
    actor: Annotated[ActorContext, Depends(get_actor_context)],
) -> Response:
    """Download the generated diagram."""
    require_capability(set(actor.role_codes), Capability.TOPOLOGY_ARTIFACT_DOWNLOAD)
    run = topology_service.get_generation_run_for_intake(
        run_id,
        app_id,
        intake_id,
    )
    if run is None:
        raise HTTPException(status_code=404, detail="Generation run not found")

    if run.get("mode") == "DRAFT_PREVIEW":
        content = review_service.verified_preview_artifact(
            run_id=run_id,
            application_id=app_id,
            intake_id=intake_id,
            artifact_type="DIAGRAM",
        )
    else:
        artifacts = topology_service.get_run_artifacts(run_id)
        diagram = next((a for a in artifacts if a["artifact_type"] == "DIAGRAM"), None)
        if diagram is None:
            raise HTTPException(status_code=404, detail="Diagram not found")
        legacy_content = topology_service.get_artifact_content(diagram["id"])
        if legacy_content is None:
            raise HTTPException(status_code=500, detail="Stored diagram artifact is unavailable")
        content = legacy_content

    return Response(
        content=content[0],
        media_type=content[2],
        headers={
            "Content-Disposition": f'attachment; filename="{content[1]}"',
        },
    )


@router.get(
    "/applications/{app_id}/intakes/{intake_id}/topology/runs/{run_id}/manifest",
)
async def download_manifest(
    app_id: str,
    intake_id: str,
    run_id: str,
    topology_service: Annotated[TopologyGenerationService, Depends(get_topology_service)],
    review_service: Annotated[TopologyReviewService, Depends(get_topology_review_service)],
    actor: Annotated[ActorContext, Depends(get_actor_context)],
) -> Response:
    """Download a receipt-verified governed preview manifest."""
    require_capability(set(actor.role_codes), Capability.TOPOLOGY_ARTIFACT_DOWNLOAD)
    run = topology_service.get_generation_run_for_intake(run_id, app_id, intake_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Generation run not found")
    content = review_service.verified_preview_artifact(
        run_id=run_id,
        application_id=app_id,
        intake_id=intake_id,
        artifact_type="MANIFEST",
    )
    return Response(
        content=content[0],
        media_type=content[2],
        headers={"Content-Disposition": f'attachment; filename="{content[1]}"'},
    )


@router.get(
    "/applications/{app_id}/intakes/{intake_id}/topology/runs/{run_id}/report",
)
async def download_report(
    app_id: str,
    intake_id: str,
    run_id: str,
    topology_service: Annotated[TopologyGenerationService, Depends(get_topology_service)],
    review_service: Annotated[TopologyReviewService, Depends(get_topology_review_service)],
    actor: Annotated[ActorContext, Depends(get_actor_context)],
) -> Response:
    """Download the gap report."""
    require_capability(set(actor.role_codes), Capability.TOPOLOGY_ARTIFACT_DOWNLOAD)
    run = topology_service.get_generation_run_for_intake(
        run_id,
        app_id,
        intake_id,
    )
    if run is None:
        raise HTTPException(status_code=404, detail="Generation run not found")

    if run.get("mode") == "DRAFT_PREVIEW":
        content = review_service.verified_preview_artifact(
            run_id=run_id,
            application_id=app_id,
            intake_id=intake_id,
            artifact_type="GAP_REPORT",
        )
    else:
        artifacts = topology_service.get_run_artifacts(run_id)
        report = next((a for a in artifacts if a["artifact_type"] == "GAP_REPORT"), None)
        if report is None:
            raise HTTPException(status_code=404, detail="Gap report not found")
        legacy_content = topology_service.get_artifact_content(report["id"])
        if legacy_content is None:
            raise HTTPException(status_code=500, detail="Stored report artifact is unavailable")
        content = legacy_content

    return Response(
        content=content[0],
        media_type=content[2],
        headers={
            "Content-Disposition": f'attachment; filename="{content[1]}"',
        },
    )


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────


async def _read_upload_with_limit(upload: UploadFile, max_bytes: int) -> bytes:
    """Read an upload in bounded chunks and reject oversized content."""
    chunks: list[bytes] = []
    total = 0
    chunk_size = 64 * 1024
    while True:
        chunk = await upload.read(min(chunk_size, max_bytes - total + 1))
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            raise HTTPException(
                status_code=413,
                detail=f"File too large (max {max_bytes} bytes)",
            )
        chunks.append(chunk)
    return b"".join(chunks)


def _require_topology_generation_enabled(request: Request) -> None:
    """Block legacy generation until the immutable pipeline is certified."""
    if not request.app.state.settings.topology_generation_enabled:
        raise HTTPException(
            status_code=503,
            detail="Topology generation is disabled pending immutable pipeline certification",
        )


def _status_to_tone(status: str) -> str:
    """Map generation status to CSS tone class."""
    return {
        "PENDING": "neutral",
        "RUNNING": "progress",
        "SUCCESS": "success",
        "FAILED": "danger",
        "READY_FOR_REVIEW": "success",
        "GENERATED_WITH_GAPS": "warning",
    }.get(status, "neutral")
