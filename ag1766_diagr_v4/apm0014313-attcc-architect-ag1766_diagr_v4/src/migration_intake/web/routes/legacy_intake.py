"""
Legacy intake workbook upload routes (L03/L06).

Routes:
- POST /applications/{app}/intakes/{intake}/legacy-intake/upload
- GET  /applications/{app}/intakes/{intake}/legacy-intake/{run}/identity
- POST /applications/{app}/intakes/{intake}/legacy-intake/{run}/process
"""
from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Any
from urllib.parse import urlencode

import openpyxl
from fastapi import APIRouter, Depends, Form, HTTPException, Request, UploadFile, status
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import update as sql_update

from migration_intake.application.commands import CreateIntakeCommand
from migration_intake.application.dto import ActorContext
from migration_intake.application.errors import (
    EvidenceMediaTypeNotAllowedError,
    EvidenceTooLargeError,
)
from migration_intake.application.services.applications import ApplicationService
from migration_intake.application.services.catalogs import CatalogPublicationService
from migration_intake.application.services.evidence import EvidenceService
from migration_intake.imports.legacy_identity_resolver import (
    resolve_legacy_intake_identity,
)
from migration_intake.imports.legacy_intake_contract import (
    LegacyIntakeContractError,
    inspect_legacy_intake_contract,
)
from migration_intake.imports.legacy_intake_identity import (
    extract_legacy_intake_identifiers,
    normalize_identifier,
)
from migration_intake.imports.legacy_intake_mappings_v1 import (
    TargetKind,
    canonical_target_key,
    get_all_mapped_fields,
    get_mapping_for_field,
)
from migration_intake.imports.legacy_value_transformers import (
    LegacyValueTransformError,
    transform_value,
)
from migration_intake.imports.source_identity import IdentityDecision
from migration_intake.persistence.models import Actor
from migration_intake.persistence.models_candidates import Candidate
from migration_intake.persistence.models_evidence import EvidenceItem
from migration_intake.persistence.models_imports import ImportFinding
from migration_intake.persistence.models_imports import ImportRun as ImportRunModel
from migration_intake.persistence.repositories.answers import AnswerRepository
from migration_intake.persistence.repositories.applications import ApplicationRepository
from migration_intake.persistence.repositories.catalogs import CatalogRepository
from migration_intake.persistence.repositories.evidence import EvidenceRepository
from migration_intake.persistence.repositories.imports import ImportRepository
from migration_intake.persistence.repositories.intakes import IntakeRepository
from migration_intake.storage.filesystem import FilesystemStore
from migration_intake.web.security import (
    CONFIGURED_ACTOR_CAPABILITIES,
    generate_csrf_token,
    validate_csrf_token,
)

if TYPE_CHECKING:
    from starlette.responses import Response

router = APIRouter(tags=["Legacy Intake"])
logger = logging.getLogger(__name__)

# Templates
_template_dir = Path(__file__).parent.parent / "templates"
templates = Jinja2Templates(directory=str(_template_dir))


def _normalize_legacy_question_value(
    source_target_key: str,
    raw_value: object,
    transformed: dict[str, Any],
) -> dict[str, Any]:
    """Adapt legacy field values to the canonical catalog response shape."""
    if source_target_key == "APP_SOX_FSA_SCOPE":
        return {
            "items": [
                {
                    "code": "SOX_FSA",
                    "detail": str(raw_value).strip().upper(),
                }
            ]
        }

    if source_target_key.startswith("APP_DR_"):
        metric = source_target_key.removeprefix("APP_DR_").lower()
        value = transformed.get("normalized_hours")
        if value is None:
            value = transformed.get("value")
        return {
            "measurements": [
                {
                    "metric": f"dr_{metric}",
                    "value": value,
                    "unit": "hours" if metric in {"rto", "rpo"} else "priority",
                    **(
                        {"qualifier": transformed["qualifier"]}
                        if transformed.get("qualifier")
                        else {}
                    ),
                }
            ]
        }

    return transformed


def _short_datetime(value: object) -> str:
    """Render a timestamp as ``10 Sep, 19:04`` — microseconds help nobody scan a list."""
    if isinstance(value, datetime):
        return f"{value.day} {value:%b}, {value:%H:%M}"
    return str(value) if value else "—"


templates.env.filters["short_datetime"] = _short_datetime


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


# ─────────────────────────────────────────────────────────────────────────────
# POST /applications/{app}/intakes/{intake}/legacy-intake/upload
# ─────────────────────────────────────────────────────────────────────────────


@router.post("/applications/{app_id}/intakes/{intake_id}/legacy-intake/upload")
async def upload_legacy_intake(
    request: Request,
    app_id: str,
    intake_id: str,
    actor: Annotated[ActorContext, Depends(get_actor_context)],
    csrf_token: Annotated[str, Form(alias="_csrf_token")],
    file: UploadFile,
) -> RedirectResponse:
    """
    Upload a legacy completed intake workbook.

    Steps:
    1. Validate file size and type
    2. Store file as evidence
    3. Inspect contract (seven-sheet structure)
    4. Extract identity (Correlation, MOTS, iTAP)
    5. Resolve application identity
    6. Redirect to identity result screen
    """
    session_factory = request.app.state.session_factory
    settings = request.app.state.settings

    # Validate CSRF
    validate_csrf_token(csrf_token, settings.csrf_secret)

    # Validate file
    if not file.filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No file provided",
        )

    if not file.filename.endswith(".xlsx"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Legacy intake workbooks must be .xlsx files",
        )

    # Read file content
    content = await file.read()

    if len(content) > settings.max_upload_bytes:
        raise EvidenceTooLargeError(
            f"File size {len(content)} exceeds maximum {settings.max_upload_bytes}"
        )

    # Store evidence using the current service contract.
    evidence_service = EvidenceService(
        session_factory,
        FilesystemStore(settings.evidence_root),
    )
    try:
        evidence_result = evidence_service.upload_evidence(
            stream=BytesIO(content),
            filename=file.filename,
            media_type=(
                file.content_type
                or "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            ),
            size_bytes=len(content),
            application_id=app_id,
            intake_id=intake_id,
            actor=actor,
        )
        evidence_id = evidence_result["evidence_id"]
    except (EvidenceMediaTypeNotAllowedError, EvidenceTooLargeError) as e:
        query = urlencode({
            "upload_message": str(e),
            "upload_message_type": "error",
            "uploaded_filename": file.filename,
        })
        return RedirectResponse(
            url=f"/applications/{app_id}/intakes/{intake_id}/sources?{query}",
            status_code=status.HTTP_303_SEE_OTHER,
        )

    with session_factory() as session:

        # Inspect workbook contract
        try:
            wb = openpyxl.load_workbook(BytesIO(content), read_only=True, data_only=True)
            sheet_names = wb.sheetnames

            # Get headers for structured sheets
            sheet_headers: dict[str, tuple[Any, ...] | None] = {}
            for sheet_name in ["App", "iTAP"]:
                if sheet_name in wb.sheetnames:
                    sheet = wb[sheet_name]
                    if sheet.max_row >= 1:
                        headers = tuple(
                            sheet.cell(1, col).value
                            for col in range(1, sheet.max_column + 1)
                        )
                        sheet_headers[sheet_name] = headers

            # Inspect contract
            contract_version = inspect_legacy_intake_contract(sheet_names, sheet_headers)

            # Extract identity from App and iTAP sheets
            app_rows: list[dict[str, Any]] = []
            if "App" in wb.sheetnames:
                app_sheet = wb["App"]
                for row_idx in range(2, min(app_sheet.max_row + 1, 100)):  # First 100 rows
                    row_dict: dict[str, Any] = {}
                    columns = [
                        "No",
                        "Question",
                        "Response_Type",
                        "Response",
                        "Allowed_Values_or_Unit",
                    ]
                    for col_idx, col_name in enumerate(columns, start=1):
                        cell_value = app_sheet.cell(row_idx, col_idx).value
                        row_dict[col_name] = cell_value if cell_value is not None else ""
                    if any(row_dict.values()):  # Skip empty rows
                        app_rows.append(row_dict)

            itap_rows = []
            if "iTAP" in wb.sheetnames:
                itap_sheet = wb["iTAP"]
                for row_idx in range(2, min(itap_sheet.max_row + 1, 100)):
                    item = itap_sheet.cell(row_idx, 1).value
                    details = itap_sheet.cell(row_idx, 2).value
                    if item or details:
                        itap_rows.append((str(item or ""), str(details or "")))

            wb.close()

            # Extract identifiers
            extracted_identifiers = extract_legacy_intake_identifiers(app_rows, itap_rows)

            # Get application identifiers from database
            app_repo = ApplicationRepository(session)
            app_identifiers = [
                (app_id, ident["identifier_type"], ident["raw_value"])
                for ident in app_repo.list_identifiers(app_id)
            ]

            # Resolve identity
            identity_result = resolve_legacy_intake_identity(
                extracted_identifiers=extracted_identifiers,
                application_identifiers=app_identifiers,
                selected_application_id=app_id,
            )

            # Create import run record
            import_repo = ImportRepository(session)
            run_id = str(uuid.uuid4())
            created_at = datetime.now(UTC)

            # The evidence service may return a deduplicated record without
            # creating the actor, so ensure the import-run FK is satisfied.
            if session.get(Actor, actor.actor_id) is None:
                session.add(
                    Actor(
                        id=actor.actor_id,
                        display_name=actor.display_name or "Unknown",
                        attuid=None,
                        created_at=created_at,
                    )
                )
                session.flush()

            # Add the run
            import_repo.add_run(
                run_id=run_id,
                application_id=app_id,
                intake_id=intake_id,
                evidence_item_id=evidence_id,
                contract_name=str(contract_version),
                parser_version="1.0.0",
                created_at=created_at,
                created_by_id=actor.actor_id,
            )

            # Update with identity information and lane
            identity_detail = {
                "extracted_identifiers": [
                    {
                        "type": ident.identifier_type,
                        "raw_value": ident.raw_value,
                        "normalized_value": ident.normalized_value,
                        "source_sheet": ident.source_sheet,
                        "source_row": ident.source_row,
                        "source_column": ident.source_column,
                        "source_label": ident.source_label,
                    }
                    for ident in identity_result.all_extracted_identifiers
                ],
                "matched_application_ids": list(identity_result.matched_application_ids),
                "conflict_detail": identity_result.conflict_detail,
            }

            import_repo.update_run_state(
                run_id=run_id,
                new_state="PENDING",
                identity_decision=str(identity_result.outcome.value),
                source_identity_raw=identity_result.selected_raw_value,
                source_identity_normalized=identity_result.selected_normalized_value,
                identity_detail=identity_detail,
            )

            # Set import_lane and matched_identifier_type using direct SQL update
            # (these fields aren't in update_run_state yet)
            stmt = (
                sql_update(ImportRunModel)
                .where(ImportRunModel.id == run_id)
                .values(
                    import_lane="LEGACY_INTAKE",
                    matched_identifier_type=identity_result.selected_identifier_type,
                )
            )
            session.execute(stmt)

            session.commit()

            # Redirect based on identity outcome
            if identity_result.outcome == IdentityDecision.MATCHED:
                with session_factory() as target_session:
                    target_intake = IntakeRepository(
                        target_session
                    ).get_open_intake_for_application(app_id)
                intake_service = ApplicationService(session_factory)
                target_intake_id = target_intake["id"] if target_intake else None

                if target_intake_id is None:
                    catalog = CatalogPublicationService(session_factory).get_latest_published()
                    if catalog is None:
                        raise HTTPException(
                            status_code=status.HTTP_400_BAD_REQUEST,
                            detail="No published catalog available for intake creation",
                        )
                    created_intake = intake_service.create_intake(
                        CreateIntakeCommand(
                            application_id=app_id,
                            catalog_release_id=catalog["id"],
                            actor=actor,
                        )
                    )
                    target_intake_id = created_intake["id"]

                session.execute(
                    sql_update(EvidenceItem)
                    .where(EvidenceItem.id == evidence_id)
                    .values(intake_id=target_intake_id)
                )
                session.commit()

                return await process_legacy_intake(
                    request=request,
                    app_id=app_id,
                    intake_id=target_intake_id,
                    run_id=run_id,
                    actor=actor,
                    csrf_token=csrf_token,
                    target_intake_id=target_intake_id,
                )
            else:
                # Identity problem: show identity result screen
                return RedirectResponse(
                    url=f"/applications/{app_id}/intakes/{intake_id}/legacy-intake/{run_id}/identity",
                    status_code=status.HTTP_303_SEE_OTHER,
                )

        except LegacyIntakeContractError as e:
            # Contract validation failed
            query = urlencode({
                "upload_message": f"Not a valid legacy intake workbook: {e}",
                "upload_message_type": "error",
                "uploaded_filename": file.filename,
            })
            return RedirectResponse(
                url=f"/applications/{app_id}/intakes/{intake_id}/sources?{query}",
                status_code=status.HTTP_303_SEE_OTHER,
            )
        except Exception as e:
            logger.exception("Failed to process legacy intake workbook")
            query = urlencode({
                "upload_message": f"Failed to process workbook: {e}",
                "upload_message_type": "error",
                "uploaded_filename": file.filename,
            })
            return RedirectResponse(
                url=f"/applications/{app_id}/intakes/{intake_id}/sources?{query}",
                status_code=status.HTTP_303_SEE_OTHER,
            )


# ─────────────────────────────────────────────────────────────────────────────
# GET /applications/{app}/intakes/{intake}/legacy-intake/{run}/identity
# ─────────────────────────────────────────────────────────────────────────────


@router.get("/applications/{app_id}/intakes/{intake_id}/legacy-intake/{run_id}/identity")
async def show_identity_result(
    request: Request,
    app_id: str,
    intake_id: str,
    run_id: str,
) -> Response:
    """
    Show identity resolution result for a legacy intake upload.

    Displays:
    - Identity outcome (MISSING, MISMATCH, AMBIGUOUS, SOURCE_CONFLICT)
    - Extracted identifiers with source locations
    - Remediation steps
    """
    session_factory = request.app.state.session_factory
    csrf_token = generate_csrf_token(request.app.state.settings.csrf_secret)

    with session_factory() as session:
        import_repo = ImportRepository(session)
        run = import_repo.get_run(run_id)

        if not run:
            raise HTTPException(status_code=404, detail="Import run not found")

        identity_detail = run.get("identity_detail") or {}
        extracted_identifiers = identity_detail.get("extracted_identifiers", [])
        conflict_detail = identity_detail.get("conflict_detail")

        # Get application info
        app_repo = ApplicationRepository(session)
        app_identifiers = app_repo.list_identifiers(app_id)
        matched_application_ids = identity_detail.get("matched_application_ids", [])
        matched_applications = [
            application
            for matched_id in matched_application_ids
            if (application := app_repo.get(matched_id)) is not None
        ]

        return templates.TemplateResponse(
            request=request,
            name="legacy_intake/identity_result.html",
            context={
                "csrf_token": csrf_token,
                "app_id": app_id,
                "intake_id": intake_id,
                "run_id": run_id,
                "run": run,
                "identity_decision": run.get("identity_decision"),
                "extracted_identifiers": extracted_identifiers,
                "app_identifiers": app_identifiers,
                "matched_applications": matched_applications,
                "conflict_detail": conflict_detail,
            },
        )


# ─────────────────────────────────────────────────────────────────────────────
# POST /applications/{app}/intakes/{intake}/legacy-intake/{run}/process
# ─────────────────────────────────────────────────────────────────────────────


@router.post("/applications/{app_id}/intakes/{intake_id}/legacy-intake/{run_id}/process")
async def process_legacy_intake(
    request: Request,
    app_id: str,
    intake_id: str,
    run_id: str,
    actor: Annotated[ActorContext, Depends(get_actor_context)],
    csrf_token: Annotated[str, Form(alias="_csrf_token")],
    target_intake_id: Annotated[str, Form()],
) -> RedirectResponse:
    """
    Process legacy intake workbook and create candidates.

    Steps:
    1. Load workbook from evidence storage
    2. Parse App and iTAP sheets using field mappings
    3. Transform values using value transformers
    4. Create candidates for mapped fields
    5. Create findings for unknown fields
    6. Capture baseline answer revisions (L05)
    7. Redirect to import review page
    """
    session_factory = request.app.state.session_factory
    settings = request.app.state.settings
    del intake_id, actor

    # Validate CSRF
    validate_csrf_token(csrf_token, settings.csrf_secret)

    with session_factory() as session:
        import_repo = ImportRepository(session)
        run = import_repo.get_run(run_id)

        if not run:
            raise HTTPException(status_code=404, detail="Import run not found")

        # Get evidence file
        evidence_id = run["evidence_item_id"]
        evidence_repo = EvidenceRepository(session)
        evidence = evidence_repo.get(evidence_id)

        if not evidence:
            raise HTTPException(status_code=404, detail="Evidence file not found")

        # Load workbook content
        filesystem = FilesystemStore(settings.evidence_root)
        with filesystem.retrieve(evidence["storage_key"]) as stored_file:
            content = stored_file.read()

        wb = openpyxl.load_workbook(BytesIO(content), read_only=True, data_only=True)

        # Parse App sheet
        app_sheet_data: list[dict[str, Any]] = []
        if "App" in wb.sheetnames:
            app_sheet = wb["App"]
            for row_idx in range(2, min(app_sheet.max_row + 1, 100)):
                no = str(app_sheet.cell(row_idx, 1).value or "")
                question = str(app_sheet.cell(row_idx, 2).value or "")
                response_type = str(app_sheet.cell(row_idx, 3).value or "")
                response = app_sheet.cell(row_idx, 4).value

                if no and question:
                    app_sheet_data.append({
                        "no": no,
                        "question": question,
                        "response_type": response_type,
                        "response": response,
                        "row": row_idx,
                    })

        # Parse iTAP sheet
        itap_sheet_data: list[dict[str, Any]] = []
        if "iTAP" in wb.sheetnames:
            itap_sheet = wb["iTAP"]
            for row_idx in range(2, min(itap_sheet.max_row + 1, 100)):
                item = str(itap_sheet.cell(row_idx, 1).value or "").strip()
                details = itap_sheet.cell(row_idx, 2).value

                if item:
                    itap_sheet_data.append({
                        "item": item,
                        "details": details,
                        "row": row_idx,
                    })

        wb.close()

        # Get current answer revisions for baseline capture (L05)
        answer_repo = AnswerRepository(session)
        answer_baselines = {}  # question_code -> revision
        target_intake = IntakeRepository(session).get(target_intake_id)
        if target_intake is None:
            raise HTTPException(status_code=404, detail="Target intake not found")
        catalog_repo = CatalogRepository(session)
        question_ids: dict[str, str] = {}

        def question_id_for_code(question_code: str) -> str | None:
            if question_code not in question_ids:
                question = catalog_repo.get_question_by_code(
                    target_intake["catalog_id"], question_code
                )
                if question is not None:
                    question_ids[question_code] = question["id"]
            return question_ids.get(question_code)

        # Create candidates from mapped fields
        candidates_created = 0
        findings_created = 0

        mapped_fields_app = get_all_mapped_fields("App")

        # Process App sheet
        for field_data in app_sheet_data:
            field_no = field_data["no"]
            mapping = get_mapping_for_field("App", field_no)

            if mapping and mapping.target_kind == TargetKind.QUESTION:
                source_target_key = mapping.target_key
                if source_target_key is None:
                    continue
                target_key = canonical_target_key(source_target_key)
                # This is a mapped question field
                if field_data["response"]:
                    try:
                        # Transform the value
                        if mapping.value_transformer:
                            transformed = transform_value(
                                mapping.value_transformer,
                                field_data["response"],
                            )
                        else:
                            transformed = {"value": str(field_data["response"])}
                        transformed = _normalize_legacy_question_value(
                            source_target_key,
                            field_data["response"],
                            transformed,
                        )
                        if target_key == "CTL-001":
                            raw_identifier = str(field_data["response"]).strip()
                            identifier_type = (
                                "MOTS_ID"
                                if raw_identifier.casefold().startswith("mots")
                                else "CORRELATION_ID"
                            )
                            transformed = {
                                "identifier_type": identifier_type,
                                "value": raw_identifier,
                                "normalized_value": normalize_identifier(raw_identifier),
                            }

                        # Get baseline revision if answer exists
                        if target_key not in answer_baselines:
                            question_id = question_id_for_code(target_key)
                            answer_instance = (
                                answer_repo.get_instance(target_intake_id, question_id)
                                if question_id is not None
                                else None
                            )
                            if answer_instance:
                                answer_baselines[target_key] = answer_instance.get(
                                    "revision", 1
                                )

                        # Create candidate
                        candidate_id = str(uuid.uuid4())
                        created_at = datetime.now(UTC)

                        candidate = Candidate(
                            id=candidate_id,
                            import_run_id=run_id,
                            application_id=app_id,
                            intake_id=target_intake_id,
                            evidence_item_id=evidence_id,
                            target_kind="QUESTION",
                            target_key=target_key,
                            origin="legacy_intake_v1",
                            extractor_version="1.0.0",
                            contract_version="APP_DATA_CAPTURE_LEGACY_V1",
                            response_schema_version=None,
                            source_locator={
                                "sheet": "App",
                                "row": field_data["row"],
                                "field_no": field_no,
                                "question": field_data["question"],
                                "source_target_key": source_target_key,
                            },
                            raw_value_json={"value": field_data["response"]},
                            normalized_value_json=transformed,
                            scope_json={"scope": "APPLICATION"},
                            confidence=1.0,
                            reconciliation_outcome="UNIQUE",
                            validation_json=None,
                            base_answer_revision=answer_baselines.get(target_key),
                            state="PROPOSED",
                            row_version=1,
                            created_at=created_at,
                            decided_by_id=None,
                            decided_at=None,
                            decision_rationale=None,
                            accepted_value_json=None,
                        )
                        session.add(candidate)
                        candidates_created += 1

                    except LegacyValueTransformError as e:
                        # Create finding for transformation error
                        finding_id = str(uuid.uuid4())
                        finding = ImportFinding(
                            id=finding_id,
                            run_id=run_id,
                            sheet_name="App",
                            finding_type="VALUE_TRANSFORM_ERROR",
                            severity="WARNING",
                            source_locator=f"App row {field_data['row']}, field {field_no}",
                            detail={
                                "field_no": field_no,
                                "question": field_data["question"],
                                "error": str(e),
                            },
                        )
                        session.add(finding)
                        findings_created += 1

            elif (
                not mapping
                and field_no not in mapped_fields_app
                and field_data["response"]
            ):
                # Unknown field - create finding
                finding_id = str(uuid.uuid4())
                finding = ImportFinding(
                    id=finding_id,
                    run_id=run_id,
                    sheet_name="App",
                    finding_type="UNKNOWN_FIELD",
                    severity="INFO",
                    source_locator=f"App row {field_data['row']}, field {field_no}",
                    detail={
                        "field_no": field_no,
                        "question": field_data["question"],
                        "response": str(field_data["response"]),
                    },
                )
                session.add(finding)
                findings_created += 1

        # Process iTAP sheet
        for field_data in itap_sheet_data:
            item = field_data["item"]
            mapping = get_mapping_for_field("iTAP", item)

            if (
                mapping
                and mapping.target_kind == TargetKind.QUESTION
                and field_data["details"]
            ):
                    source_target_key = mapping.target_key
                    if source_target_key is None:
                        continue
                    target_key = canonical_target_key(source_target_key)
                    try:
                        # Transform the value
                        if mapping.value_transformer:
                            transformed = transform_value(
                                mapping.value_transformer,
                                field_data["details"],
                            )
                        else:
                            transformed = {"value": str(field_data["details"])}
                        transformed = _normalize_legacy_question_value(
                            source_target_key,
                            field_data["details"],
                            transformed,
                        )
                        if target_key == "CTL-001":
                            raw_identifier = str(field_data["details"]).strip()
                            identifier_type = (
                                "MOTS_ID"
                                if raw_identifier.casefold().startswith("mots")
                                else "CORRELATION_ID"
                            )
                            transformed = {
                                "identifier_type": identifier_type,
                                "value": raw_identifier,
                                "normalized_value": normalize_identifier(raw_identifier),
                            }

                        # Get baseline revision
                        if target_key not in answer_baselines:
                            question_id = question_id_for_code(target_key)
                            answer_instance = (
                                answer_repo.get_instance(target_intake_id, question_id)
                                if question_id is not None
                                else None
                            )
                            if answer_instance:
                                answer_baselines[target_key] = answer_instance.get(
                                    "revision", 1
                                )

                        # Create candidate
                        candidate_id = str(uuid.uuid4())
                        created_at = datetime.now(UTC)

                        candidate = Candidate(
                            id=candidate_id,
                            import_run_id=run_id,
                            application_id=app_id,
                            intake_id=target_intake_id,
                            evidence_item_id=evidence_id,
                            target_kind="QUESTION",
                            target_key=target_key,
                            origin="legacy_intake_v1",
                            extractor_version="1.0.0",
                            contract_version="APP_DATA_CAPTURE_LEGACY_V1",
                            response_schema_version=None,
                            source_locator={
                                "sheet": "iTAP",
                                "row": field_data["row"],
                                "item": item,
                                "source_target_key": source_target_key,
                            },
                            raw_value_json={"value": field_data["details"]},
                            normalized_value_json=transformed,
                            scope_json={"scope": "APPLICATION"},
                            confidence=1.0,
                            reconciliation_outcome="UNIQUE",
                            validation_json=None,
                            base_answer_revision=answer_baselines.get(target_key),
                            state="PROPOSED",
                            row_version=1,
                            created_at=created_at,
                            decided_by_id=None,
                            decided_at=None,
                            decision_rationale=None,
                            accepted_value_json=None,
                        )
                        session.add(candidate)
                        candidates_created += 1

                    except LegacyValueTransformError as e:
                        finding_id = str(uuid.uuid4())
                        finding = ImportFinding(
                            id=finding_id,
                            run_id=run_id,
                            sheet_name="iTAP",
                            finding_type="VALUE_TRANSFORM_ERROR",
                            severity="WARNING",
                            source_locator=f"iTAP row {field_data['row']}, item {item}",
                            detail={
                                "item": item,
                                "error": str(e),
                            },
                        )
                        session.add(finding)
                        findings_created += 1

        # Update run state
        import_repo.update_run_state(
            run_id=run_id,
            new_state="COMPLETED",
            total_candidates=candidates_created,
            total_findings=findings_created,
            completed_at=datetime.now(UTC),
        )

        # Update intake_id on the run to point to the selected intake
        stmt = (
            sql_update(ImportRunModel)
            .where(ImportRunModel.id == run_id)
            .values(intake_id=target_intake_id)
        )
        session.execute(stmt)

        session.commit()

        # Redirect to import review page
        return RedirectResponse(
            url=f"/applications/{app_id}/intakes/{target_intake_id}/imports/{run_id}",
            status_code=status.HTTP_303_SEE_OTHER,
        )
