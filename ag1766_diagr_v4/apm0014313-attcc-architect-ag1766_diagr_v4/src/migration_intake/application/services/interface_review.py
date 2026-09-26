"""Interface register review service.

Three ways an interfaces row gets written:
1. Candidate-first acceptance — import-derived INTERFACE_REGISTER candidates
   (see workbook.py, from the full App Data Capture workbook) are reviewed
   and accepted, exactly like WaveUtil.
2. Direct manual create/edit — a reviewer fills in the form themselves;
   this register has no import-only restriction because, unlike WaveUtil
   hostnames, no fuzzy-matching step is required to place a row.
3. Direct "Upload from Excel" — a standalone workbook containing only the
   Interface sheet is parsed and every row is inserted immediately, with
   no candidate/review step (same rationale as #2).

No natural-key uniqueness is enforced (the source sheet can legitimately
contain multiple distinct rows sharing the same ``interface_correlation_id``
— different directions/connections recorded under one shared counterpart
ID). All three paths converge on the same **insert-if-not-an-exact-
duplicate** logic (``_create_if_new``): a row is only skipped if every
field already matches an existing row for the same application exactly;
otherwise a new row is always created. Editing a specific row by
``record_id`` is the only way an existing row's fields ever change.

Linking key: ``migrating_app_correlation_id`` is the sheet's own value
(e.g. "18678"), not ``applications.id``. Manual saves and workbook uploads
both resolve it from the target application's CORRELATION identifier
(``app_identifiers``); workbook rows whose own "Migrating App Correlation
ID" column disagrees with that are rejected, never silently imported
(never mix another application's interfaces into this one). The internal
``application_id`` FK (``ON DELETE CASCADE``) is resolved and stamped on
every row alongside it, purely so deleting an application also removes its
interfaces — never shown to a user.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from io import BytesIO
from zipfile import BadZipFile

from openpyxl.utils.exceptions import InvalidFileException
from sqlalchemy.orm import Session, sessionmaker

from migration_intake.application.dto import ActorContext
from migration_intake.application.errors import ConcurrencyConflictError
from migration_intake.imports.interface_sheet import InterfaceSheetAdapter
from migration_intake.persistence.repositories.applications import ApplicationRepository
from migration_intake.persistence.repositories.candidates import CandidateRepository
from migration_intake.persistence.repositories.interfaces import (
    INTERFACE_FIELD_NAMES,
    InterfaceRepository,
)
from migration_intake.persistence.unit_of_work import uow_context

# ---------------------------------------------------------------------------
# Command data classes
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class InterfaceCandidateAcceptItem:
    """A single candidate acceptance request within an accept_candidates call."""

    candidate_id: str
    expected_candidate_version: int


@dataclass(frozen=True)
class InterfaceFields:
    """
    All 33 Interface-sheet fields, as submitted by a form, candidate, or
    workbook row.

    ``migrating_app_correlation_id``/``migrating_app_acronym`` are normally
    resolved server-side from the target application's own identifiers
    (see ``_get_application_correlation_id``) rather than supplied by a
    manual-entry caller — they are still plain fields here so candidate
    acceptance and workbook import (which read them off the sheet) can set
    them directly.
    """

    interface_correlation_id: str
    migrating_app_correlation_id: str | None = None
    migrating_app_acronym: str | None = None
    consumer_or_provider: str | None = None
    interface_app_acronym: str | None = None
    interface_migration_wave: str | None = None
    interface_system_location: str | None = None
    end_point_name: str | None = None
    data_traffic_direction: str | None = None
    connection_owner: str | None = None
    sync_async: str | None = None
    current_protocol: str | None = None
    current_interface_type: str | None = None
    target_protocol: str | None = None
    target_interface_type: str | None = None
    interface_impact_change_type: str | None = None
    current_port: str | None = None
    future_port: str | None = None
    encrypted_solution_cloud: str | None = None
    low_latency_required: str | None = None
    throughput_volume_req: str | None = None
    att_architecture_validated: str | None = None
    listed_in_itap: str | None = None
    engagement_email_sent_on: str | None = None
    funding_template_sent: str | None = None
    interface_commitment_date: str | None = None
    interface_included_in_crp: str | None = None
    funding_approved_epic: str | None = None
    connectivity_tested: str | None = None
    uat_tested: str | None = None
    interface_contact: str | None = None
    interface_cutover_contact: str | None = None
    notes: str | None = None

    def as_dict(self) -> dict:
        return {name: getattr(self, name) for name in INTERFACE_FIELD_NAMES}


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class CandidateNotProposedError(Exception):
    """Raised when trying to accept a candidate that is not in PROPOSED state."""


class InterfaceCorrelationIdRequiredError(Exception):
    """Raised when a manual save omits the required natural key."""


class ApplicationCorrelationIdMissingError(Exception):
    """Raised when the target application has no CORRELATION identifier set."""


class InvalidInterfaceWorkbookError(Exception):
    """Raised when an uploaded file cannot be read as an Interface sheet."""


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class InterfaceReviewService:
    """Accepts INTERFACE_REGISTER candidates and handles manual create/edit/retire."""

    def __init__(self, session_factory: sessionmaker) -> None:
        self._session_factory = session_factory

    # ------------------------------------------------------------------
    # Candidate-first acceptance
    # ------------------------------------------------------------------

    def accept_candidates(
        self,
        items: list[InterfaceCandidateAcceptItem],
        actor: ActorContext,
    ) -> dict:
        """
        Accept all candidate items atomically or fail all.

        Returns:
            {"accepted": N, "candidate_ids": [...], "record_ids": [...]}

        Raises:
            ConcurrencyConflictError: candidate not found or version mismatch.
            CandidateNotProposedError: candidate is not in PROPOSED state.
        """
        if not items:
            return {"accepted": 0, "candidate_ids": [], "record_ids": []}

        now = datetime.now(tz=UTC)
        record_ids: list[str] = []

        with uow_context(self._session_factory) as uow:
            interface_repo = InterfaceRepository(uow._session)
            candidate_repo = CandidateRepository(uow._session)

            candidates_to_process = []
            for item in items:
                candidate = candidate_repo.get_by_id(item.candidate_id)
                if candidate is None:
                    raise ConcurrencyConflictError(
                        f"Candidate {item.candidate_id!r} not found."
                    )
                if candidate.state != "PROPOSED":
                    raise CandidateNotProposedError(
                        f"Candidate {item.candidate_id!r} is in state "
                        f"{candidate.state!r}, not PROPOSED."
                    )
                if candidate.row_version != item.expected_candidate_version:
                    raise ConcurrencyConflictError(
                        f"Candidate {item.candidate_id!r}: expected version="
                        f"{item.expected_candidate_version}, current version="
                        f"{candidate.row_version}; stale acceptance rejected."
                    )
                candidates_to_process.append((item, candidate))

            for item, candidate in candidates_to_process:
                sheet_fields = candidate.normalized_value_json or {}
                migrating_app_correlation_id = sheet_fields.get(
                    "migrating_app_correlation_id"
                ) or self._get_application_correlation_id(
                    uow._session, str(candidate.application_id)
                )
                record_id, _outcome = self._create_if_new(
                    interface_repo,
                    application_id=str(candidate.application_id),
                    fields=InterfaceFields(
                        **{
                            **{
                                name: sheet_fields.get(name)
                                for name in INTERFACE_FIELD_NAMES
                            },
                            "interface_correlation_id": sheet_fields.get(
                                "interface_correlation_id", ""
                            ),
                            "migrating_app_correlation_id": migrating_app_correlation_id,
                        }
                    ),
                    origin="IMPORT",
                    now=now,
                    actor_id=actor.actor_id,
                )
                record_ids.append(record_id)

                candidate.state = "ACCEPTED"
                candidate.decided_by_id = actor.actor_id
                candidate.decided_at = now
                candidate.row_version += 1

            uow.commit()

        return {
            "accepted": len(items),
            "candidate_ids": [item.candidate_id for item in items],
            "record_ids": record_ids,
        }

    # ------------------------------------------------------------------
    # Manual create / edit
    # ------------------------------------------------------------------

    def save_manual(
        self,
        *,
        application_id: str,
        record_id: str | None,
        expected_row_version: int | None,
        fields: InterfaceFields,
        actor: ActorContext,
    ) -> dict:
        """
        Create a new interface record, or edit an existing one, in place.

        ``record_id=None`` creates; a provided ``record_id`` edits and requires
        a matching ``expected_row_version`` (optimistic concurrency).

        ``migrating_app_correlation_id``/``migrating_app_acronym`` are always
        resolved from ``application_id`` here, overriding anything set on
        ``fields`` — a manual add/edit is always for the application whose
        page the reviewer is on.

        Raises:
            ApplicationCorrelationIdMissingError: the application has no
                CORRELATION identifier to link this interface against.
        """
        if not fields.interface_correlation_id or not fields.interface_correlation_id.strip():
            raise InterfaceCorrelationIdRequiredError(
                "Interface Correlation ID is required."
            )

        now = datetime.now(tz=UTC)

        with uow_context(self._session_factory) as uow:
            app_correlation_id = self._get_application_correlation_id(
                uow._session, application_id
            )
            if not app_correlation_id:
                raise ApplicationCorrelationIdMissingError(
                    "This application has no CORRELATION identifier configured; "
                    "interfaces cannot be linked without one."
                )
            app_acronym = self._get_application_acronym(uow._session, application_id)
            resolved_fields = InterfaceFields(
                **{
                    **fields.as_dict(),
                    "migrating_app_correlation_id": app_correlation_id,
                    "migrating_app_acronym": app_acronym,
                }
            )

            interface_repo = InterfaceRepository(uow._session)

            if record_id is not None:
                existing = interface_repo.get_record(record_id)
                if existing is None:
                    raise ConcurrencyConflictError(
                        f"Interface record {record_id!r} not found."
                    )
                if existing["row_version"] != expected_row_version:
                    raise ConcurrencyConflictError(
                        f"Interface record {record_id!r}: expected version="
                        f"{expected_row_version}, current version="
                        f"{existing['row_version']}; stale edit rejected."
                    )
                interface_repo.update_record(
                    record_id=record_id,
                    fields=resolved_fields.as_dict(),
                    origin="MANUAL",
                    updated_at=now,
                    updated_by_id=actor.actor_id,
                )
                out_id = record_id
            else:
                out_id, _outcome = self._create_if_new(
                    interface_repo,
                    application_id=application_id,
                    fields=resolved_fields,
                    origin="MANUAL",
                    now=now,
                    actor_id=actor.actor_id,
                )

            uow.commit()

        with self._session_factory() as session:
            return InterfaceRepository(session).get_record(out_id)  # type: ignore[return-value]

    def retire_record(
        self,
        *,
        record_id: str,
        expected_row_version: int,
        actor: ActorContext,
    ) -> None:
        """Retire an interface record (state=RETIRED)."""
        now = datetime.now(tz=UTC)

        with uow_context(self._session_factory) as uow:
            interface_repo = InterfaceRepository(uow._session)
            existing = interface_repo.get_record(record_id)
            if existing is None:
                raise ConcurrencyConflictError(
                    f"Interface record {record_id!r} not found."
                )
            if existing["row_version"] != expected_row_version:
                raise ConcurrencyConflictError(
                    f"Interface record {record_id!r}: expected version="
                    f"{expected_row_version}, current version="
                    f"{existing['row_version']}; stale retirement rejected."
                )
            interface_repo.retire_record(
                record_id=record_id, retired_at=now, retired_by_id=actor.actor_id
            )
            uow.commit()

    # ------------------------------------------------------------------
    # Upload from Excel — standalone Interface-sheet workbook
    # ------------------------------------------------------------------

    def import_from_workbook(
        self,
        *,
        content: bytes,
        application_id: str,
        actor: ActorContext,
    ) -> dict:
        """
        Parse a standalone workbook's Interface sheet and upsert every row
        that belongs to this application directly into the register (no
        candidate/review step — the correlation ID is already a stable
        natural key, per §2 of the design).

        Rows whose own "Migrating App Correlation ID" column names a
        *different* application than ``application_id`` are rejected and
        counted separately, never silently imported. Rows whose values
        exactly match an existing record for this application are left
        untouched (reported as ``unchanged``, not re-written) so
        re-uploading the same file is a safe no-op. Rows sharing an
        ``interface_correlation_id`` with an existing row but differing in
        any other field are **not** treated as duplicates — each becomes
        its own row (no data is silently discarded).

        Returns:
            {"created": N, "unchanged": N, "mismatched_app": N,
             "skipped": N, "findings": [...]}
        """
        rows = self._read_interface_sheet_rows(content)
        result = InterfaceSheetAdapter().parse(rows)

        with self._session_factory() as session:
            app_correlation_id = self._get_application_correlation_id(session, application_id)
            app_acronym = self._get_application_acronym(session, application_id)
        if not app_correlation_id:
            raise InvalidInterfaceWorkbookError(
                "This application has no CORRELATION identifier configured; "
                "interfaces cannot be linked without one."
            )
        normalized_app_correlation_id = app_correlation_id.strip().lower()

        now = datetime.now(tz=UTC)
        created = 0
        unchanged = 0
        mismatched_app = 0

        with uow_context(self._session_factory) as uow:
            interface_repo = InterfaceRepository(uow._session)
            existing_signatures = {
                self._field_signature(record)
                for record in interface_repo.list_records_for_application(application_id)
            }
            for record in result.interfaces:
                row_app_correlation_id = (record.migrating_application_id or "").strip()
                if (
                    row_app_correlation_id
                    and row_app_correlation_id.lower() != normalized_app_correlation_id
                ):
                    mismatched_app += 1
                    continue

                fields = InterfaceFields(
                    migrating_app_correlation_id=app_correlation_id,
                    migrating_app_acronym=record.migrating_app_acronym or app_acronym,
                    consumer_or_provider=record.consumer_or_provider,
                    interface_correlation_id=record.interface_correlation_id,
                    interface_app_acronym=record.interface_app_acronym,
                    interface_migration_wave=record.interface_migration_wave,
                    interface_system_location=record.interface_system_location,
                    end_point_name=record.endpoint,
                    data_traffic_direction=record.direction,
                    connection_owner=record.connection_owner,
                    sync_async=record.sync_async,
                    current_protocol=record.current_protocol,
                    current_interface_type=record.current_interface_type,
                    target_protocol=record.target_protocol,
                    target_interface_type=record.target_interface_type,
                    interface_impact_change_type=record.interface_impact_change_type,
                    current_port=record.current_port,
                    future_port=record.target_port,
                    encrypted_solution_cloud=record.encrypted_solution_cloud,
                    low_latency_required=record.low_latency_required,
                    throughput_volume_req=record.throughput_volume_req,
                    att_architecture_validated=record.att_architecture_validated,
                    listed_in_itap=record.listed_in_itap,
                    engagement_email_sent_on=record.engagement_email_sent_on,
                    funding_template_sent=record.funding_template_sent,
                    interface_commitment_date=record.interface_commitment_date,
                    interface_included_in_crp=record.interface_included_in_crp,
                    funding_approved_epic=record.funding_approved_epic,
                    connectivity_tested=record.connectivity_tested,
                    uat_tested=record.uat_tested,
                    interface_contact=record.interface_contact,
                    interface_cutover_contact=record.interface_cutover_contact,
                    notes=record.notes,
                )
                signature = self._field_signature(fields.as_dict())
                if signature in existing_signatures:
                    unchanged += 1
                    continue

                interface_repo.create_record(
                    record_id=str(uuid.uuid4()),
                    application_id=application_id,
                    fields=fields.as_dict(),
                    origin="IMPORT",
                    created_at=now,
                    created_by_id=actor.actor_id,
                )
                existing_signatures.add(signature)
                created += 1
            uow.commit()

        return {
            "created": created,
            "unchanged": unchanged,
            "mismatched_app": mismatched_app,
            "skipped": len(result.findings),
            "findings": [
                {"finding_type": f.finding_type, "message": f.message, "row_number": f.row_number}
                for f in result.findings
            ],
        }

    @staticmethod
    def _read_interface_sheet_rows(content: bytes) -> list[dict]:
        """Read the workbook's ``Interface`` sheet (or its first sheet) as header-keyed rows."""
        try:
            import openpyxl
        except ImportError as e:
            raise InvalidInterfaceWorkbookError("openpyxl is not available") from e

        try:
            workbook = openpyxl.load_workbook(BytesIO(content), read_only=True, data_only=True)
        except (BadZipFile, InvalidFileException, OSError, KeyError) as e:
            raise InvalidInterfaceWorkbookError(
                "File could not be read as an Excel workbook"
            ) from e

        sheet_name = next(
            (name for name in workbook.sheetnames if name.strip().casefold() == "interface"),
            workbook.sheetnames[0] if workbook.sheetnames else None,
        )
        if sheet_name is None:
            raise InvalidInterfaceWorkbookError("Workbook has no sheets")

        worksheet = workbook[sheet_name]
        rows_iter = worksheet.iter_rows(values_only=True)
        try:
            headers = next(rows_iter)
        except StopIteration:
            return []
        headers = [str(h) if h is not None else f"col_{i}" for i, h in enumerate(headers)]

        rows: list[dict] = []
        for row_values in rows_iter:
            if all(v is None for v in row_values):
                continue
            rows.append({
                headers[i]: row_values[i] for i in range(min(len(headers), len(row_values)))
            })
        return rows

    @staticmethod
    def _field_signature(fields: dict) -> tuple[str, ...]:
        """Return the normalized all-field identity used for exact de-duplication."""
        return tuple(
            str(fields.get(name) or "").strip() for name in INTERFACE_FIELD_NAMES
        )

    # ------------------------------------------------------------------
    # Shared insert-if-not-exact-duplicate
    # ------------------------------------------------------------------

    @staticmethod
    def _create_if_new(
        interface_repo: InterfaceRepository,
        *,
        application_id: str,
        fields: InterfaceFields,
        origin: str,
        now: datetime,
        actor_id: str,
    ) -> tuple[str, str]:
        """
        Create an interfaces row for ``fields``, unless an exact duplicate
        (every field matching, for this application) already exists.

        Rows are never updated in place through this path — two rows
        sharing an ``interface_correlation_id`` but differing in any other
        field are both kept, per the "exact values" de-dup requirement.

        Returns:
            (record_id, outcome) where outcome is one of
            "created" | "unchanged".
        """
        existing = interface_repo.find_exact_duplicate(application_id, fields.as_dict())
        if existing is not None:
            return str(existing["id"]), "unchanged"

        record_id = str(uuid.uuid4())
        interface_repo.create_record(
            record_id=record_id,
            application_id=application_id,
            fields=fields.as_dict(),
            origin=origin,
            created_at=now,
            created_by_id=actor_id,
        )
        return record_id, "created"

    # ------------------------------------------------------------------
    # Application identity resolution
    # ------------------------------------------------------------------

    @staticmethod
    def _get_application_correlation_id(session: Session, application_id: str) -> str | None:
        """Return the application's own CORRELATION identifier raw value, or None."""
        for identifier in ApplicationRepository(session).list_identifiers(application_id):
            if identifier["identifier_type"] == "CORRELATION":
                return identifier["raw_value"]
        return None

    @staticmethod
    def _get_application_acronym(session: Session, application_id: str) -> str | None:
        """Return the application's display name, used as its acronym on interface rows."""
        app = ApplicationRepository(session).get(application_id)
        return app["display_name"] if app else None
