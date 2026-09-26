"""Generate a safe workbook of intake questions for external completion."""
from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime
from io import BytesIO
from typing import TYPE_CHECKING, Any

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font
from sqlalchemy import and_, select

from migration_intake.catalog.response_types import get_default_registry
from migration_intake.persistence.models import (
    AnswerInstance,
    AnswerRevision,
    Application,
    CatalogOption,
    CatalogQuestion,
    CatalogRelease,
    CatalogSection,
    Intake,
)
from migration_intake.persistence.models_evidence import EvidenceItem
from migration_intake.persistence.repositories.candidates import CandidateRepository
from migration_intake.persistence.repositories.imports import ImportRepository

GAP_WORKBOOK_SCHEMA_VERSION = "1.0"
GAP_WORKBOOK_CONTRACT = "GAP_WORKBOOK_REIMPORT_V1"
GAP_WORKBOOK_ORIGIN = "gap_workbook_reimport"

#: Selection modes for the export.
#:
#: ``unresolved`` keeps the original behaviour (active REQUIRED questions with
#: no current answer), ``required`` adds already-answered REQUIRED questions so
#: the filler can confirm them, and ``all`` adds the optional questions too so
#: the workbook can serve as a complete standard intake form.
GAP_WORKBOOK_INCLUDE_MODES = ("unresolved", "required", "all")

_SHEET_TITLES = {
    "unresolved": "Unresolved Questions",
    "required": "Required Questions",
    "all": "All Questions",
}

if TYPE_CHECKING:
    from sqlalchemy.orm import sessionmaker


class GapWorkbookService:
    """Build a prefilled workbook from the pinned catalog and canonical answers."""

    #: The 12-column shape exported before provenance columns existed.  Kept so
    #: previously distributed workbooks continue to reimport.
    _LEGACY_HEADERS = (
        "Application ID",
        "Intake ID",
        "Catalog Release ID",
        "Catalog Version",
        "Response Schema Version",
        "Question Code",
        "Question",
        "Response Type",
        "Allowed Values / Unit",
        "Approved Answer Summary",
        "Row Version Token",
        "Response",
    )

    #: Optional provenance columns, appended after ``Response`` so that the
    #: legacy column offsets are unchanged.
    _PROVENANCE_HEADERS = (
        "Source File",
        "Source Locator",
        "Confidence",
    )

    _HEADERS = _LEGACY_HEADERS + _PROVENANCE_HEADERS

    def __init__(self, session_factory: sessionmaker) -> None:
        self._session_factory = session_factory

    def export_unresolved(
        self,
        intake_id: str,
        application_id: str | None = None,
        include: str = "unresolved",
    ) -> tuple[bytes, dict[str, Any]] | None:
        if include not in GAP_WORKBOOK_INCLUDE_MODES:
            raise GapWorkbookValidationError(
                "Unsupported include mode "
                f"'{include}'; expected one of {', '.join(GAP_WORKBOOK_INCLUDE_MODES)}"
            )
        session = self._session_factory()
        try:
            intake = session.execute(
                select(Intake).where(Intake.id == intake_id)
            ).scalar_one_or_none()
            if intake is None:
                return None
            application = session.execute(
                select(Application).where(Application.id == intake.application_id)
            ).scalar_one_or_none()
            catalog = session.execute(
                select(CatalogRelease).where(CatalogRelease.id == intake.catalog_id)
            ).scalar_one_or_none()
            if application is None or catalog is None:
                return None
            if application_id is not None and str(application.id) != application_id:
                return None

            conditions = [
                CatalogSection.release_id == catalog.id,
                CatalogQuestion.is_active.is_(True),
            ]
            if include != "all":
                conditions.append(CatalogQuestion.required_level == "REQUIRED")

            rows = session.execute(
                select(CatalogQuestion, AnswerInstance, AnswerRevision)
                .join(CatalogSection, CatalogSection.id == CatalogQuestion.section_id)
                .outerjoin(
                    AnswerInstance,
                    and_(
                        AnswerInstance.question_id == CatalogQuestion.id,
                        AnswerInstance.intake_id == intake_id,
                    ),
                )
                .outerjoin(
                    AnswerRevision,
                    AnswerRevision.id == AnswerInstance.current_rev_id,
                )
                .where(*conditions)
                .order_by(CatalogSection.display_order, CatalogQuestion.display_order)
            ).all()

            selected = (
                [row for row in rows if row[2] is None]
                if include == "unresolved"
                else list(rows)
            )
            question_ids = [question.id for question, _, _ in selected]
            options_by_question: dict[Any, str] = {}
            if question_ids:
                options = session.execute(
                    select(CatalogOption)
                    .where(CatalogOption.question_id.in_(question_ids))
                    .order_by(CatalogOption.question_id, CatalogOption.display_order)
                ).scalars()
                for option in options:
                    label = f"{option.option_code}: {option.display_label}"
                    existing = options_by_question.get(option.question_id)
                    options_by_question[option.question_id] = (
                        f"{existing} | {label}" if existing else label
                    )
            workbook = Workbook()
            sheet = workbook.active
            sheet.title = _SHEET_TITLES[include]
            sheet.append(self._HEADERS)
            for cell in sheet[1]:
                cell.font = Font(bold=True)
            for question, instance, revision in selected:
                allowed_or_unit = options_by_question.get(question.id, "")
                if question.units:
                    allowed_or_unit = (
                        f"{allowed_or_unit}; unit={question.units}"
                        if allowed_or_unit
                        else f"unit={question.units}"
                    )
                sheet.append(
                    [
                        str(application.id),
                        str(intake.id),
                        str(catalog.id),
                        self._safe_text(catalog.semantic_version),
                        GAP_WORKBOOK_SCHEMA_VERSION,
                        self._safe_text(question.question_code),
                        self._safe_text(question.question_text),
                        self._safe_text(question.response_type),
                        self._safe_text(allowed_or_unit),
                        self._safe_text(self._summary(revision.response_json))
                        if revision
                        else "",
                        instance.row_version if instance else 0,
                        # Response is always blank: an already-approved value is
                        # surfaced in Approved Answer Summary for confirmation,
                        # never pre-filled as the filler's own response.
                        "",
                        # Provenance columns are for the filler to complete.
                        "",
                        "",
                        "",
                    ]
                )
            sheet.freeze_panes = "A2"
            sheet.auto_filter.ref = sheet.dimensions
            for column in sheet.columns:
                width = min(max(len(str(cell.value or "")) for cell in column) + 2, 60)
                sheet.column_dimensions[column[0].column_letter].width = width

            output = BytesIO()
            workbook.save(output)
            return output.getvalue(), {
                "application_id": str(application.id),
                "intake_id": str(intake.id),
                "catalog_id": str(catalog.id),
                "catalog_version": catalog.semantic_version,
                "question_count": len(selected),
                "include": include,
            }
        finally:
            session.close()

    @staticmethod
    def _summary(value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, dict):
            return "; ".join(f"{key}={item}" for key, item in sorted(value.items()))
        return str(value)

    @staticmethod
    def _safe_text(value: Any) -> str:
        """Keep text cells from being interpreted as spreadsheet formulas."""
        text = "" if value is None else str(value)
        if text.startswith(("=", "+", "-", "@", "\t")):
            return "'" + text
        return text

    @classmethod
    def _match_headers(cls, header_row: tuple[Any, ...] | None) -> tuple[str, ...]:
        """Resolve a header row to a supported column layout.

        Both the current 15-column layout and the legacy 12-column layout
        (exported before the provenance columns existed) are accepted so that
        already-distributed workbooks keep importing.  Anything else is
        rejected.
        """
        if header_row is None:
            raise GapWorkbookValidationError("Unsupported gap workbook headers")
        values = list(header_row)
        # Excel and openpyxl pad a sheet's rows to its widest column, so drop
        # trailing empty header cells before comparing.
        while values and (values[-1] is None or str(values[-1]).strip() == ""):
            values.pop()
        candidate = tuple(values)
        for supported in (cls._HEADERS, cls._LEGACY_HEADERS):
            if candidate == supported:
                return supported
        raise GapWorkbookValidationError("Unsupported gap workbook headers")

    @staticmethod
    def _cell_text(value: Any) -> str:
        """Read an optional free-text cell as a trimmed string."""
        return "" if value is None else str(value).strip()

    @staticmethod
    def _parse_confidence(value: Any) -> tuple[float | None, str | None]:
        """Parse a filler-supplied confidence into the 0.0 to 1.0 range.

        Returns the parsed value and, when the cell could not be trusted, a
        message describing why.  A bad cell never fails the import: the value
        is treated as absent and reported as a finding.
        """
        if value is None or str(value).strip() == "":
            return None, None
        text = str(value).strip()
        try:
            parsed = float(text)
        except (TypeError, ValueError):
            return None, f"Confidence '{text}' is not a number and was ignored"
        if parsed != parsed or parsed in (float("inf"), float("-inf")):
            return None, f"Confidence '{text}' is not a finite number and was ignored"
        if not 0.0 <= parsed <= 1.0:
            return None, f"Confidence '{text}' is outside 0.0-1.0 and was ignored"
        return parsed, None

    def reimport(
        self,
        content: bytes,
        filename: str,
        application_id: str,
        intake_id: str,
        actor_id: str,
    ) -> dict[str, Any]:
        """Validate a completed gap workbook and persist proposed candidates."""
        workbook = load_workbook(BytesIO(content), read_only=True, data_only=True)
        sheet = workbook.active
        rows = list(sheet.values)
        headers = self._match_headers(rows[0] if rows else None)

        submitted: list[dict[str, Any]] = []
        for row_number, values in enumerate(rows[1:], start=2):
            row = dict(zip(headers, values, strict=False))
            response = row.get("Response")
            if response in (None, ""):
                continue
            if (
                str(row.get("Application ID")) != application_id
                or str(row.get("Intake ID")) != intake_id
            ):
                raise GapWorkbookValidationError(f"Row {row_number} targets another intake")
            if str(row.get("Catalog Release ID")) == "None":
                raise GapWorkbookValidationError(f"Row {row_number} has no catalog release")
            if (
                str(row.get("Response Schema Version"))
                != GAP_WORKBOOK_SCHEMA_VERSION
            ):
                raise GapWorkbookValidationError(
                    f"Row {row_number} has an unsupported schema version"
                )
            submitted.append({"row_number": row_number, **row})

        session = self._session_factory()
        try:
            intake = session.execute(
                select(Intake).where(Intake.id == intake_id)
            ).scalar_one_or_none()
            if intake is None or str(intake.application_id) != application_id:
                raise GapWorkbookValidationError("Application intake not found")
            catalog = session.execute(
                select(CatalogRelease).where(CatalogRelease.id == intake.catalog_id)
            ).scalar_one_or_none()
            if catalog is None:
                raise GapWorkbookValidationError("Pinned catalog not found")
            for item in submitted:
                if str(item["Catalog Release ID"]) != str(catalog.id):
                    raise GapWorkbookValidationError(
                        f"Row {item['row_number']} targets another catalog release"
                    )
                if str(item["Catalog Version"]) != str(catalog.semantic_version):
                    raise GapWorkbookValidationError(
                        f"Row {item['row_number']} targets another catalog version"
                    )

            questions = session.execute(
                select(CatalogQuestion, CatalogSection)
                .join(CatalogSection, CatalogSection.id == CatalogQuestion.section_id)
                .where(CatalogSection.release_id == catalog.id)
            ).all()
            by_code = {question.question_code: question for question, _ in questions}
            instances = {
                str(instance.question_id): instance
                for instance in session.execute(
                    select(AnswerInstance).where(AnswerInstance.intake_id == intake_id)
                ).scalars()
            }
            for item in submitted:
                question = by_code.get(str(item["Question Code"]))
                if (
                    question is None
                    or not question.is_active
                    or question.required_level != "REQUIRED"
                ):
                    raise GapWorkbookValidationError(
                        f"Row {item['row_number']} targets an invalid question"
                    )
                instance = instances.get(str(question.id))
                current_version = instance.row_version if instance else 0
                if str(item["Row Version Token"]) != str(current_version):
                    raise GapWorkbookValidationError(
                        f"Row {item['row_number']} is stale"
                    )

            now = datetime.now(tz=UTC)
            run_id = str(uuid.uuid4())
            digest = hashlib.sha256(content).hexdigest()
            storage_key = f"gap-workbook:{digest}"

            # Returning the same completed form twice is an ordinary thing for a
            # filler to do. ``storage_key`` is unique, so inserting a second
            # evidence row for identical bytes raised a raw IntegrityError;
            # reuse the existing row instead and record a fresh import run.
            existing_evidence = session.execute(
                select(EvidenceItem).where(EvidenceItem.storage_key == storage_key)
            ).scalar_one_or_none()
            if existing_evidence is not None:
                evidence_id = str(existing_evidence.id)
            else:
                evidence_id = str(uuid.uuid4())
                session.add(
                    EvidenceItem(
                        id=evidence_id,
                        application_id=application_id,
                        intake_id=intake_id,
                        storage_key=storage_key,
                        sha256_hex=digest,
                        size_bytes=len(content),
                        media_type=(
                            "application/vnd.openxmlformats-officedocument."
                            "spreadsheetml.sheet"
                        ),
                        original_filename=filename,
                        state="ACTIVE",
                        created_at=now,
                        created_by_id=actor_id,
                    )
                )
            import_repo = ImportRepository(session)
            import_repo.add_run(
                run_id=run_id,
                application_id=application_id,
                intake_id=intake_id,
                evidence_item_id=evidence_id,
                contract_name=GAP_WORKBOOK_CONTRACT,
                parser_version=GAP_WORKBOOK_SCHEMA_VERSION,
                created_at=now,
                created_by_id=actor_id,
            )
            candidates = CandidateRepository(session)
            registry = get_default_registry()
            finding_count = 0
            for item in submitted:
                source_file = self._cell_text(item.get("Source File"))
                source_ref = self._cell_text(item.get("Source Locator"))
                confidence, confidence_issue = self._parse_confidence(
                    item.get("Confidence")
                )

                locator: dict[str, Any] = {
                    "sheet": sheet.title,
                    "row": item["row_number"],
                }
                if source_file:
                    locator["source_file"] = source_file
                if source_ref:
                    locator["source_ref"] = source_ref

                # ``origin`` stays an adapter identity; the upstream file is
                # appended so a reviewer can see which source a value came from.
                origin = GAP_WORKBOOK_ORIGIN
                if source_file:
                    origin = f"{origin}:{source_file}"[:64]

                # Normalize the returned cell into the question's canonical
                # payload, exactly as the UAQ import path does. Without this a
                # candidate carries only {"response": "<text>"}, which either
                # validates as semantically empty (permissive types) or fails
                # outright (strict types) when a reviewer accepts it — so a
                # completed form could never actually reach the questionnaire.
                question = by_code.get(str(item["Question Code"]))
                response_type = (
                    registry.get(question.response_type) if question is not None else None
                )
                normalized_value: dict[str, Any] | None = None
                schema_version = GAP_WORKBOOK_SCHEMA_VERSION
                reject_reason: str | None = None

                if response_type is None:
                    reject_reason = (
                        f"response type {getattr(question, 'response_type', '?')!r} "
                        f"is not in the response registry"
                    )
                elif response_type.is_computed:
                    reject_reason = (
                        f"{question.response_type} is derived from a register or workflow "
                        f"and cannot be answered on a form"
                    )
                else:
                    parsed = response_type.parse_workbook(item["Response"])
                    validation = (
                        response_type.validate(parsed.value) if parsed.is_success else None
                    )
                    if not parsed.is_success:
                        reject_reason = f"value could not be parsed: {parsed.errors}"
                    elif validation is None or not validation.is_valid:
                        reject_reason = f"value is not valid for this question: {validation.errors}"
                    else:
                        normalized_value = response_type.normalize(parsed.value or {})
                        schema_version = (
                            question.response_schema_version or GAP_WORKBOOK_SCHEMA_VERSION
                        )

                if reject_reason is not None:
                    # Mirror the UAQ contract: an unusable value becomes a
                    # durable finding, never a candidate a reviewer could
                    # accept into a canonical answer.
                    candidates.create_finding(
                        import_run_id=run_id,
                        finding_type="TYPE_MISMATCH",
                        severity="ERROR",
                        message=(
                            f"Row {item['row_number']} "
                            f"({item['Question Code']}): {reject_reason}"
                        ),
                        source_locator=locator,
                    )
                    finding_count += 1
                    continue

                candidate = candidates.create_candidate(
                    import_run_id=run_id,
                    application_id=application_id,
                    intake_id=intake_id,
                    evidence_item_id=evidence_id,
                    target_kind="QUESTION",
                    target_key=str(item["Question Code"]),
                    origin=origin,
                    extractor_version=GAP_WORKBOOK_SCHEMA_VERSION,
                    contract_version=GAP_WORKBOOK_CONTRACT,
                    raw_value_json={"response": str(item["Response"])},
                    normalized_value_json=normalized_value,
                    # A returned intake form answers questions about the
                    # application itself. Without an explicit scope the review
                    # UI and the accept route both treat the candidate as
                    # ineligible, so the form could not be actioned.
                    scope_json={"scope": "APPLICATION"},
                    source_locator=locator,
                    confidence=confidence,
                    response_schema_version=schema_version,
                )
                if confidence_issue is not None:
                    candidates.create_finding(
                        import_run_id=run_id,
                        finding_type="INVALID_CONFIDENCE",
                        severity="WARNING",
                        message=(
                            f"Row {item['row_number']}: {confidence_issue}"
                        ),
                        candidate_id=str(candidate.id),
                        source_locator=locator,
                    )
                    finding_count += 1
            import_repo.update_run_state(
                run_id,
                "COMPLETED",
                total_sheets=1,
                total_candidates=len(submitted),
                total_findings=finding_count,
                completed_at=datetime.now(tz=UTC),
                # Identity is verified more strictly here than by the
                # correlation-ID heuristic: every row must carry this exact
                # application id, intake id and pinned catalog release, or the
                # whole file is rejected above. Recording the verdict is what
                # lets the review UI expose accept controls — without it a
                # returned form produces candidates nobody can action.
                identity_decision="APPLICATION_MATCHED",
                source_identity_raw=application_id,
                source_identity_normalized=application_id,
                identity_detail={
                    "verified_by": "gap_workbook_row_identity",
                    "intake_id": intake_id,
                },
            )
            session.commit()
            return {
                "run_id": run_id,
                "candidate_count": len(submitted),
                "finding_count": finding_count,
            }
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()


class GapWorkbookValidationError(ValueError):
    """Raised when a workbook identity or row version cannot be trusted."""
