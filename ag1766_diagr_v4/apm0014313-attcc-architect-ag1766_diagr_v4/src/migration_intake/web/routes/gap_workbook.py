"""Gap workbook export routes."""
from __future__ import annotations

from typing import Annotated, cast

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    UploadFile,
)
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session, sessionmaker  # noqa: TC002 -- needed at runtime by FastAPI
from starlette.responses import Response

from migration_intake.application.services.gap_workbook import (
    GAP_WORKBOOK_INCLUDE_MODES,
    GapWorkbookService,
    GapWorkbookValidationError,
)
from migration_intake.web.security import validate_csrf_token

router = APIRouter(tags=["gap-workbook"])


def get_session_factory(request: Request) -> sessionmaker[Session]:
    """Get the configured database session factory."""
    return cast("sessionmaker[Session]", request.app.state.session_factory)


@router.get("/applications/{app_id}/intakes/{intake_id}/gap-workbook.xlsx")
async def export_gap_workbook(
    app_id: str,
    intake_id: str,
    session_factory: Annotated[sessionmaker[Session], Depends(get_session_factory)],
    include: Annotated[
        str,
        Query(
            description=(
                "Which questions to export. One of: "
                f"{', '.join(GAP_WORKBOOK_INCLUDE_MODES)}. "
                "'unresolved' (default) keeps unanswered required questions, "
                "'required' adds answered required questions, and 'all' "
                "exports the full intake form including optional questions."
            ),
        ),
    ] = "unresolved",
) -> Response:
    """Download intake questions for an application intake as a fillable form."""
    try:
        result = GapWorkbookService(session_factory).export_unresolved(
            intake_id, app_id, include=include
        )
    except GapWorkbookValidationError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    if result is None:
        raise HTTPException(status_code=404, detail="Application intake not found")

    content, metadata = result
    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": 'attachment; filename="gap-workbook.xlsx"',
            "X-Catalog-Release-ID": metadata["catalog_id"],
            "X-Catalog-Version": metadata["catalog_version"],
            "X-Unresolved-Question-Count": str(metadata["question_count"]),
            "X-Include-Mode": metadata["include"],
        },
    )


@router.post("/applications/{app_id}/intakes/{intake_id}/gap-workbook/reimport")
async def reimport_gap_workbook(
    request: Request,
    app_id: str,
    intake_id: str,
    csrf_token: str = Form(..., alias="_csrf_token"),
    file: UploadFile = File(...),
) -> Response:
    """Validate a completed gap workbook and create proposed candidates."""
    if not validate_csrf_token(
        csrf_token, request.app.state.settings.csrf_secret
    ):
        raise HTTPException(status_code=403, detail="Invalid CSRF token")
    content = await file.read()
    actor_id = request.app.state.settings.actor_id
    try:
        result = GapWorkbookService(request.app.state.session_factory).reimport(
            content=content,
            filename=file.filename or "gap-workbook.xlsx",
            application_id=app_id,
            intake_id=intake_id,
            actor_id=actor_id,
        )
    except GapWorkbookValidationError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except (ValueError, KeyError) as error:
        raise HTTPException(status_code=400, detail="Invalid gap workbook") from error

    return JSONResponse(
        content=result,
        headers={"X-Import-Run-ID": result["run_id"]},
    )
