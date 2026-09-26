"""
Workbook orchestration service — ProcessIntakeWorkbook (B06).

Architecture (sections 16, 25.3):
1.  Confirm evidence item belongs to the application via EvidenceRepository.
    - Raises EvidenceNotFoundError if evidence_item_id is unknown.
    - Raises EvidenceApplicationMismatchError if it belongs to another app.
2.  Idempotency: if a COMPLETED run for (evidence_item_id, APP_DATA_CAPTURE_V1)
    already exists under the given intake, return it without re-parsing.
3.  Create ImportRun record (state=PENDING, updated to COMPLETED at commit).
4.  Run sheet adapters outside the persistence transaction (deterministic,
    no SQL involvement).
5.  Persist ImportSheetResult + ImportFinding rows.  Update ImportRun to
    state=COMPLETED with totals.  Commit all in a single transaction.
6.  Return ProcessWorkbookResult with counts.

The caller supplies pre-extracted ``sheet_rows: dict[str, list[dict]]``
(sheet_name → list of row dicts keyed by column header), avoiding any
openpyxl dependency in this orchestration layer.

Unknown sheet names in sheet_rows are silently skipped.
"""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import sessionmaker

from migration_intake.application.dto import ActorContext
from migration_intake.application.errors import (
    EvidenceApplicationMismatchError,
    EvidenceNotFoundError,
)
from migration_intake.catalog.response_types import get_default_registry
from migration_intake.imports.app_sheet import AppSheetAdapter
from migration_intake.imports.database_sheet import DatabaseSheetAdapter
from migration_intake.imports.infra_sheet import InfraSheetAdapter
from migration_intake.imports.interface_sheet import InterfaceSheetAdapter
from migration_intake.imports.interface_tracking_v1 import (
    InterfaceAggregateCandidate,
    InterfaceRecord,
    InterfaceTrackingV1Adapter,
)
from migration_intake.imports.itap_sheet import ITAPSheetAdapter
from migration_intake.imports.provisioning_sheet import ProvisioningSheetAdapter
from migration_intake.imports.source_identity import (
    IdentityDecision,
    compare_source_identity,
    normalize_identifier,
)
from migration_intake.imports.tss_sheet import TSSSheetAdapter
from migration_intake.imports.uaq_sheet import UAQSheetAdapter
from migration_intake.imports.wave_util_sheet import WAVEUTIL_HEADERS, WaveUtilSheetAdapter
from migration_intake.persistence.repositories.applications import ApplicationRepository
from migration_intake.persistence.repositories.candidates import CandidateRepository
from migration_intake.persistence.repositories.catalogs import CatalogRepository
from migration_intake.persistence.repositories.evidence import EvidenceRepository
from migration_intake.persistence.repositories.imports import ImportRepository
from migration_intake.persistence.repositories.intakes import IntakeRepository

# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------


@dataclass
class ProcessWorkbookResult:
    """
    Result returned by WorkbookService.process_workbook().

    Attributes:
        run_id:           UUID string of the ImportRun record.
        state:            "COMPLETED" | "QUARANTINED" | "IDEMPOTENT"
        total_sheets:     Number of sheets that were processed.
        total_candidates: Sum of candidates across all processed sheets.
        total_findings:   Sum of findings across all processed sheets.
        sheet_results:    One plain dict per processed sheet (from ImportRepository).
        deduplicated:     True when the idempotency path was taken (no re-parsing).
    """

    run_id: str
    state: str
    total_sheets: int
    total_candidates: int
    total_findings: int
    sheet_results: list[dict] = field(default_factory=list)
    deduplicated: bool = False


# ---------------------------------------------------------------------------
# Known sheet names (contract-defined)
# ---------------------------------------------------------------------------

_KNOWN_SHEETS: frozenset[str] = frozenset(
    {
        "App", "iTAP", "TSS", "Provisioning", "Infra", "Database", "WaveUtil", "UAQ",
        "Interface",
        "Migrating App Data", "Interfaces", "Contact & Data Impact", "Scan Data",
        "Sample Interface Data", "Read Me",
    }
)


#: Excel truncates worksheet names to this length. A real UAQ export named
#: "UAQ - Unified Assessment Questionnaire" (39 characters) is silently
#: saved by Excel as "UAQ - Unified Assessment Questi" (31 characters).
_MAX_EXCEL_SHEET_NAME_LENGTH = 31

_UAQ_SHEET_ALIASES: frozenset[str] = frozenset(
    {
        "uaqquestionnaire",
        "unifiedassessmentquestionnaire",
        # Real-world SharePoint/Excel export naming convention (see
        # _MAX_EXCEL_SHEET_NAME_LENGTH docstring above for why the
        # as-saved sheet name is frequently a truncated prefix of this).
        "uaqunifiedassessmentquestionnaire",
    }
)


def _canonical_sheet_name(sheet_name: str) -> str | None:
    """Map supported worksheet aliases to their canonical importer names."""
    if sheet_name in _KNOWN_SHEETS:
        return sheet_name

    normalized = "".join(character for character in sheet_name.casefold() if character.isalnum())
    if normalized in _UAQ_SHEET_ALIASES:
        return "UAQ"
    aliases = {
        "migratingappdata": "Migrating App Data",
        "interfaces": "Interfaces",
        "interface": "Interface",
        "contactdataimpact": "Contact & Data Impact",
        "scandata": "Scan Data",
        "sampleinterfacedata": "Sample Interface Data",
        "readme": "Read Me",
    }
    if normalized in aliases:
        return aliases[normalized]

    if normalized and len(sheet_name) == _MAX_EXCEL_SHEET_NAME_LENGTH:
        for alias in _UAQ_SHEET_ALIASES:
            if alias.startswith(normalized):
                return "UAQ"

    return None


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class WorkbookService:
    """
    Orchestrates workbook import parsing and persistence.

    The service validates evidence via the database (EvidenceRepository),
    invokes the appropriate sheet adapter for each known sheet, and
    persists the resulting ImportRun / ImportSheetResult / ImportFinding
    records in a single transaction.

    The ``evidence_store`` parameter is accepted for API compatibility but
    is not used in this implementation; evidence validation is done via
    the database only.
    """

    _CONTRACT_NAME = "APP_DATA_CAPTURE_V1"
    _PARSER_VERSION = "1.0.1"

    def __init__(
        self,
        session_factory: sessionmaker,
        evidence_store: Any = None,
    ) -> None:
        self._session_factory = session_factory
        self._store = evidence_store  # reserved for future use

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def process_workbook(
        self,
        application_id: str,
        intake_id: str,
        evidence_item_id: str,
        sheet_rows: dict[str, list[dict]],
        actor: ActorContext,
    ) -> ProcessWorkbookResult:
        """
        Orchestrate workbook parsing and persist results.

        Args:
            application_id:   UUID string of the owning application.
            intake_id:        UUID string of the intake being processed.
            evidence_item_id: UUID string of the EvidenceItem to import.
            sheet_rows:       Pre-extracted rows per sheet:
                              ``{"TSS": [{"Manufacturer": ...}, ...], ...}``.
                              Unknown sheet names are silently skipped.
            actor:            Actor performing the operation.

        Returns:
            ProcessWorkbookResult with run_id, state, counts, and sheet results.

        Raises:
            EvidenceNotFoundError:           evidence_item_id not found in DB.
            EvidenceApplicationMismatchError: evidence belongs to a different app.
        """
        now = datetime.now(tz=UTC)

        # ── Step 1: validate evidence + idempotency check ─────────────
        session = self._session_factory()
        try:
            evidence_repo = EvidenceRepository(session)
            import_repo = ImportRepository(session)

            evidence = evidence_repo.get(evidence_item_id)
            if evidence is None:
                raise EvidenceNotFoundError(
                    f"Evidence item {evidence_item_id!r} not found."
                )
            if evidence["application_id"] != application_id:
                raise EvidenceApplicationMismatchError(
                    f"Evidence item {evidence_item_id!r} belongs to application "
                    f"{evidence['application_id']!r}, not {application_id!r}."
                )

            # Idempotency: look for a COMPLETED run with the same evidence + contract
            if intake_id:
                existing_runs = import_repo.list_runs_for_intake(intake_id)
                for run in existing_runs:
                    if (
                        run["evidence_item_id"] == evidence_item_id
                        and run["contract_name"] == self._CONTRACT_NAME
                        and run["parser_version"] == self._PARSER_VERSION
                        and run["state"] == "COMPLETED"
                    ):
                        existing_sheet_results = (
                            import_repo.list_sheet_results_for_run(run["id"])
                        )
                        return ProcessWorkbookResult(
                            run_id=run["id"],
                            state="COMPLETED",
                            total_sheets=run["total_sheets"] or 0,
                            total_candidates=run["total_candidates"] or 0,
                            total_findings=run["total_findings"] or 0,
                            sheet_results=existing_sheet_results,
                            deduplicated=True,
                        )
        finally:
            session.close()

        # ── Step 2: parse sheets outside any transaction ───────────────
        # This is deterministic (no SQL) and may be slow for large files,
        # so it runs independently of the persistence transaction.
        run_id = str(uuid.uuid4())
        parse_results: dict[str, tuple[str, list, list]] = {}
        interface_tracking_rows: dict[str, list[dict]] = {}
        unrecognized_sheets: list[str] = []
        for sheet_name, rows in sheet_rows.items():
            canonical_name = _canonical_sheet_name(sheet_name)
            if canonical_name is None:
                # Never drop a sheet silently. A supplier renaming a tab, or
                # Excel truncating a long sheet name, otherwise produces an
                # import with no results and no explanation — indistinguishable
                # from a file that genuinely contained nothing.
                unrecognized_sheets.append(sheet_name)
                continue
            if canonical_name in {
                "Migrating App Data", "Interfaces", "Contact & Data Impact", "Scan Data",
                "Sample Interface Data", "Read Me",
            }:
                interface_tracking_rows[canonical_name] = rows
                continue
            outcome, candidates, findings = self._invoke_sheet(canonical_name, rows)
            parse_results[canonical_name] = (outcome, candidates, findings)
        if interface_tracking_rows:
            outcome, candidates, findings = self._invoke_interface_tracking(
                interface_tracking_rows
            )
            parse_results["Interface Tracking"] = (outcome, candidates, findings)

        identity_decision = None
        source_identity_raw = None
        source_identity_normalized = None
        identity_detail = None
        source_ids = self._source_identity_values(sheet_rows)
        source_sheets_present = any(
            _canonical_sheet_name(sheet_name) in {"UAQ", "Migrating App Data"}
            for sheet_name in sheet_rows
        )
        if source_sheets_present:
            source_identity_raw = source_ids[0][1] if source_ids else None
            identity_session = self._session_factory()
            try:
                identifiers = ApplicationRepository(identity_session).list_identifiers(
                    application_id
                )
            finally:
                identity_session.close()
            decisions = [
                compare_source_identity(
                    source_id=raw_value,
                    application_identifiers=[
                        (
                            identifier["application_id"],
                            identifier["identifier_type"],
                            identifier["raw_value"],
                        )
                        for identifier in identifiers
                    ],
                    selected_application_id=application_id,
                )
                for _, raw_value in source_ids
            ]
            normalized_ids = {
                normalize_identifier(raw_value) for _, raw_value in source_ids
                if normalize_identifier(raw_value)
            }
            if len(normalized_ids) > 1:
                identity_decision = IdentityDecision.SOURCE_CONFLICT.value
                source_identity_normalized = ",".join(sorted(normalized_ids))
            else:
                decision = decisions[0] if decisions else compare_source_identity(
                    source_id=None,
                    application_identifiers=[],
                    selected_application_id=application_id,
                )
                identity_decision = decision.outcome.value
                source_identity_normalized = decision.normalized_source_id
            identity_detail = {
                "source_ids": [
                    {"sheet": sheet, "raw_value": raw_value}
                    for sheet, raw_value in source_ids
                ],
            }

        # ── Step 3: persist everything in a single transaction ─────────
        total_candidates = 0
        total_findings = 0
        sheet_result_dicts: list[dict] = []

        session = self._session_factory()
        try:
            import_repo = ImportRepository(session)

            # Create the ImportRun (starts as PENDING, updated to COMPLETED below)
            import_repo.add_run(
                run_id=run_id,
                application_id=application_id,
                intake_id=intake_id,
                evidence_item_id=evidence_item_id,
                contract_name=self._CONTRACT_NAME,
                parser_version=self._PARSER_VERSION,
                created_at=now,
                created_by_id=actor.actor_id,
            )

            candidate_repo = CandidateRepository(session)

            quarantined = identity_decision is not None and identity_decision != (
                "APPLICATION_MATCHED"
            )
            if quarantined:
                import_repo.add_finding(
                    finding_id=str(uuid.uuid4()),
                    run_id=run_id,
                    sheet_name=source_ids[0][0] if source_ids else "UAQ",
                    finding_type=identity_decision,
                    severity="ERROR",
                    source_locator="source identity",
                    detail={
                        "raw_value": source_identity_raw,
                        "normalized_value": source_identity_normalized,
                    },
                )
                total_findings += 1

            for unrecognized in unrecognized_sheets:
                import_repo.add_finding(
                    finding_id=str(uuid.uuid4()),
                    run_id=run_id,
                    sheet_name=unrecognized,
                    finding_type="UNRECOGNIZED_SHEET",
                    severity="WARNING",
                    source_locator=f"Sheet:{unrecognized}",
                    detail={
                        "message": (
                            "Sheet name does not match any supported source contract, "
                            "so nothing in it was imported. Rename the tab to a "
                            "recognized name or add a reviewed mapping for it."
                        ),
                        "sheet": unrecognized,
                    },
                )
                total_findings += 1

            # Persist sheet results, candidates, and findings
            for sheet_name, (outcome, candidates, findings) in parse_results.items():
                if quarantined:
                    candidates = []
                normalized_candidates: dict[int, tuple[dict, str | None]] = {}
                if sheet_name == "UAQ" and not quarantined:
                    candidates, type_findings, normalized_candidates = (
                        self._validate_uaq_candidates(session, intake_id, candidates)
                    )
                    findings = [*findings, *type_findings]
                candidate_count = len(candidates)
                finding_count = len(findings)
                total_candidates += candidate_count
                total_findings += finding_count

                result_id = str(uuid.uuid4())
                sheet_result = import_repo.add_sheet_result(
                    result_id=result_id,
                    run_id=run_id,
                    sheet_name=sheet_name,
                    outcome=outcome,
                    candidate_count=candidate_count,
                    finding_count=finding_count,
                )
                sheet_result_dicts.append(sheet_result)

                # Persist candidates (P06)
                for candidate in candidates:
                    self._persist_candidate(
                        candidate_repo=candidate_repo,
                        run_id=run_id,
                        application_id=application_id,
                        intake_id=intake_id,
                        evidence_item_id=evidence_item_id,
                        sheet_name=sheet_name,
                        candidate=candidate,
                        normalized_value=normalized_candidates.get(id(candidate), (None, None))[0],
                        response_schema_version=normalized_candidates.get(id(candidate), (None, None))[1],
                    )

                for finding in findings:
                    finding_id = str(uuid.uuid4())
                    finding_type, severity, source_locator, detail = (
                        self._extract_finding_attrs(sheet_name, finding)
                    )
                    import_repo.add_finding(
                        finding_id=finding_id,
                        run_id=run_id,
                        sheet_name=sheet_name,
                        finding_type=finding_type,
                        severity=severity,
                        source_locator=source_locator,
                        detail=detail,
                    )

            # Update run to COMPLETED with aggregate totals
            import_repo.update_run_state(
                run_id,
                "QUARANTINED" if quarantined else "COMPLETED",
                total_sheets=len(parse_results),
                total_candidates=total_candidates,
                total_findings=total_findings,
                completed_at=datetime.now(tz=UTC),
                identity_decision=identity_decision,
                source_identity_raw=source_identity_raw,
                source_identity_normalized=source_identity_normalized,
                identity_detail=identity_detail,
            )
            session.commit()

        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

        return ProcessWorkbookResult(
            run_id=run_id,
            state="QUARANTINED" if identity_decision not in (None, "APPLICATION_MATCHED") else "COMPLETED",
            total_sheets=len(parse_results),
            total_candidates=total_candidates,
            total_findings=total_findings,
            sheet_results=sheet_result_dicts,
            deduplicated=False,
        )

    # ------------------------------------------------------------------
    # Sheet invocation dispatch
    # ------------------------------------------------------------------

    def _invoke_sheet(
        self, sheet_name: str, rows: list[dict]
    ) -> tuple[str, list, list]:
        """
        Invoke the appropriate adapter for the given sheet.

        Returns:
            (outcome, candidates, findings) where outcome is one of
            "VALID" / "QUARANTINED" / "FAILED", candidates and findings
            are lists of adapter-specific result objects.
        """
        if sheet_name == "App":
            return self._invoke_app(rows)
        elif sheet_name == "iTAP":
            return self._invoke_itap(rows)
        elif sheet_name == "TSS":
            return self._invoke_tss(rows)
        elif sheet_name == "Provisioning":
            return self._invoke_provisioning(rows)
        elif sheet_name == "Infra":
            return self._invoke_infra(rows)
        elif sheet_name == "Database":
            return self._invoke_database(rows)
        elif sheet_name == "WaveUtil":
            return self._invoke_waveutil(rows)
        elif sheet_name == "UAQ":
            return self._invoke_uaq(rows)
        elif sheet_name == "Interface":
            return self._invoke_interface(rows)
        # Unreachable due to _KNOWN_SHEETS guard, but defensive:
        return "VALID", [], []

    def _invoke_app(self, rows: list[dict]) -> tuple[str, list, list]:
        """
        Invoke AppSheetAdapter with an empty catalog.

        With no catalog rows, all sheet rows become ADDITIONAL_ROW drift
        (WARNING severity) and no candidates are produced.  Findings are
        the non-OK drift records.
        """
        adapter = AppSheetAdapter(catalog_rows=[])
        result = adapter.parse(rows)
        # Drift records serve as findings; filter out OK-level (none expected here)
        findings = [d for d in result.drift if d.severity.value != "OK"]
        return result.outcome, list(result.candidates), findings

    def _invoke_itap(self, rows: list[dict]) -> tuple[str, list, list]:
        """
        Invoke ITAPSheetAdapter.

        Converts list[dict] → list[tuple[str, str]] by taking the first
        two column values from each row dict as (label, value).
        """
        adapter = ITAPSheetAdapter()
        tuples: list[tuple[str, str]] = []
        for row in rows:
            values = list(row.values())
            label = str(values[0]) if len(values) > 0 else ""
            value = str(values[1]) if len(values) > 1 else ""
            tuples.append((label, value))
        result = adapter.parse(tuples)
        return result.outcome, list(result.candidates), list(result.findings)

    def _invoke_tss(self, rows: list[dict]) -> tuple[str, list, list]:
        """Invoke TSSSheetAdapter."""
        adapter = TSSSheetAdapter()
        result = adapter.parse(rows)
        return result.outcome, list(result.candidates), list(result.findings)

    def _invoke_provisioning(self, rows: list[dict]) -> tuple[str, list, list]:
        """Invoke ProvisioningSheetAdapter."""
        adapter = ProvisioningSheetAdapter()
        result = adapter.parse(rows)
        return result.outcome, list(result.candidates), list(result.findings)

    def _invoke_infra(self, rows: list[dict]) -> tuple[str, list, list]:
        """Invoke InfraSheetAdapter."""
        adapter = InfraSheetAdapter()
        result = adapter.parse(rows)
        return result.outcome, list(result.candidates), list(result.findings)

    def _invoke_database(self, rows: list[dict]) -> tuple[str, list, list]:
        """Invoke DatabaseSheetAdapter."""
        adapter = DatabaseSheetAdapter()
        result = adapter.parse(rows)
        return result.outcome, list(result.candidates), list(result.findings)

    def _invoke_waveutil(self, rows: list[dict]) -> tuple[str, list, list]:
        """
        Invoke WaveUtilSheetAdapter.

        Extracts raw headers from the first row's keys, validates them,
        builds a raw→canonical mapping, then parses each row individually.
        Rows where WaveUtilRowResult.values is not None count as candidates.
        """
        if not rows:
            return "VALID", [], []

        adapter = WaveUtilSheetAdapter()
        raw_headers = list(rows[0].keys())
        _, missing_required, _ = adapter.validate_headers(raw_headers)

        # Build raw header → canonical field name mapping
        raw_to_canonical: dict[str, str] = {
            raw: WAVEUTIL_HEADERS[raw]
            for raw in raw_headers
            if raw in WAVEUTIL_HEADERS
        }

        candidates: list = []
        all_findings: list = []
        for i, row in enumerate(rows, 1):
            canonical_row = {
                raw_to_canonical.get(k, k): v for k, v in row.items()
            }
            row_result = adapter.parse_row(canonical_row, i)
            if row_result.values is not None:
                candidates.append(row_result)
            all_findings.extend(row_result.findings)

        outcome = "QUARANTINED" if missing_required else "VALID"
        return outcome, candidates, all_findings

    def _invoke_uaq(self, rows: list[dict]) -> tuple[str, list, list]:
        """
        Invoke UAQSheetAdapter for Unified Assessment Questionnaire data.

        Parses UAQ CSV exports and extracts candidates from INV* columns.
        """
        if not rows:
            return "VALID", [], []

        adapter = UAQSheetAdapter()
        result = adapter.parse(rows)
        return "VALID", list(result.candidates), list(result.findings)

    def _invoke_interface_tracking(
        self, sheet_rows: dict[str, list[dict]]
    ) -> tuple[str, list, list]:
        """Parse Interface Tracking as one source contract with scoped outputs."""
        result = InterfaceTrackingV1Adapter().parse(sheet_rows)
        return "VALID", [*result.interfaces, *result.aggregates], list(result.findings)

    def _invoke_interface(self, rows: list[dict]) -> tuple[str, list, list]:
        """Invoke InterfaceSheetAdapter for the App Data Capture Interface sheet."""
        adapter = InterfaceSheetAdapter()
        result = adapter.parse(rows)
        return "VALID", list(result.interfaces), list(result.findings)

    @staticmethod
    def _source_identity_values(
        sheet_rows: dict[str, list[dict]],
    ) -> list[tuple[str, str]]:
        """Collect authoritative correlation IDs from recognized source formats."""
        values: list[tuple[str, str]] = []
        for sheet_name, rows in sheet_rows.items():
            canonical_name = _canonical_sheet_name(sheet_name)
            if canonical_name not in {"UAQ", "Migrating App Data"} or not rows:
                continue
            for key, value in rows[0].items():
                normalized_key = "".join(
                    character for character in str(key).casefold() if character.isalnum()
                )
                if normalized_key in {"correlationid", "migratingappcorrelationid"}:
                    if value not in (None, ""):
                        values.append((canonical_name, str(value)))
                    break
        return values

    # ------------------------------------------------------------------
    # Candidate persistence (P06)
    # ------------------------------------------------------------------

    def _persist_candidate(
        self,
        candidate_repo: CandidateRepository,
        run_id: str,
        application_id: str,
        intake_id: str,
        evidence_item_id: str,
        sheet_name: str,
        candidate: Any,
        normalized_value: dict | None = None,
        response_schema_version: str | None = None,
    ) -> None:
        """
        Normalize and persist an adapter-specific candidate to the P06 contract.

        Each adapter produces different candidate types (AppCandidate, TSSCandidate,
        etc.). This method extracts common fields and persists them uniformly.
        """
        # Extract target information
        target_kind = "QUESTION"
        if isinstance(candidate, InterfaceRecord):
            target_kind = "INTERFACE_REGISTER"
        target_key = self._extract_target_key(sheet_name, candidate)

        # Extract source locator
        source_locator = self._extract_source_locator(sheet_name, candidate)

        # Extract raw value
        raw_value = self._extract_raw_value(candidate)

        # Scope is always stamped explicitly, never left null for a reader to
        # infer. A QUESTION candidate proposes an answer about the application
        # itself, so it is APPLICATION-scoped and eligible for reviewer
        # acceptance; an interface row carries its own narrower scope and is
        # never acceptable as a questionnaire answer.
        scope: dict[str, Any]
        if isinstance(candidate, InterfaceRecord):
            scope = {"scope": "INTERFACE", "direction": candidate.direction}
            # The canonical interfaces register stores all 33 Interface-sheet
            # columns (see interface_sheet.py) — nothing on this row is
            # evidence-only.
            normalized_value = {
                "migrating_app_correlation_id": candidate.migrating_application_id,
                "migrating_app_acronym": candidate.migrating_app_acronym,
                "consumer_or_provider": candidate.consumer_or_provider,
                "interface_correlation_id": candidate.interface_correlation_id,
                "interface_app_acronym": candidate.interface_app_acronym,
                "interface_migration_wave": candidate.interface_migration_wave,
                "interface_system_location": candidate.interface_system_location,
                "end_point_name": candidate.endpoint,
                "data_traffic_direction": candidate.direction,
                "connection_owner": candidate.connection_owner,
                "sync_async": candidate.sync_async,
                "current_protocol": candidate.current_protocol,
                "current_interface_type": candidate.current_interface_type,
                "target_protocol": candidate.target_protocol,
                "target_interface_type": candidate.target_interface_type,
                "interface_impact_change_type": candidate.interface_impact_change_type,
                "current_port": candidate.current_port,
                "future_port": candidate.target_port,
                "encrypted_solution_cloud": candidate.encrypted_solution_cloud,
                "low_latency_required": candidate.low_latency_required,
                "throughput_volume_req": candidate.throughput_volume_req,
                "att_architecture_validated": candidate.att_architecture_validated,
                "listed_in_itap": candidate.listed_in_itap,
                "engagement_email_sent_on": candidate.engagement_email_sent_on,
                "funding_template_sent": candidate.funding_template_sent,
                "interface_commitment_date": candidate.interface_commitment_date,
                "interface_included_in_crp": candidate.interface_included_in_crp,
                "funding_approved_epic": candidate.funding_approved_epic,
                "connectivity_tested": candidate.connectivity_tested,
                "uat_tested": candidate.uat_tested,
                "interface_contact": candidate.interface_contact,
                "interface_cutover_contact": candidate.interface_cutover_contact,
                "notes": candidate.notes,
            }
        else:
            scope = {"scope": "APPLICATION"}
        if isinstance(candidate, InterfaceAggregateCandidate):
            normalized_value = {"value": candidate.proposed_value}
        elif target_kind == "QUESTION":
            scope = {"scope": "APPLICATION"}

        # Extract confidence (if available)
        confidence = getattr(candidate, "confidence", None)

        # Determine origin
        origin = getattr(candidate, "origin", f"{sheet_name.lower()}_sheet_adapter")

        candidate_repo.create_candidate(
            import_run_id=run_id,
            application_id=application_id,
            intake_id=intake_id,
            evidence_item_id=evidence_item_id,
            target_kind=target_kind,
            target_key=target_key,
            origin=origin,
            extractor_version=self._PARSER_VERSION,
            contract_version=self._CONTRACT_NAME,
            raw_value_json=raw_value,
            normalized_value_json=normalized_value,
            scope_json=scope,
            source_locator=source_locator,
            confidence=confidence,
            response_schema_version=response_schema_version,
        )

    @staticmethod
    def _validate_uaq_candidates(
        session: Any, intake_id: str, candidates: list[Any]
    ) -> tuple[list[Any], list[dict[str, Any]], dict[int, tuple[dict, str | None]]]:
        """Validate UAQ proposals against the intake's pinned catalog before storage."""
        intake = IntakeRepository(session).get(intake_id)
        if intake is None:
            return [], [], {}
        catalog = CatalogRepository(session)
        registry = get_default_registry()
        valid_candidates: list[Any] = []
        findings: list[dict[str, Any]] = []
        normalized: dict[int, tuple[dict, str | None]] = {}
        for candidate in candidates:
            question = catalog.get_question_by_code(
                intake["catalog_id"], candidate.question_code
            )
            if question is None:
                findings.append({
                    "finding_type": "UNMAPPED_TARGET",
                    "severity": "ERROR",
                    "source_locator": candidate.source_locator,
                    "detail": {"question_code": candidate.question_code},
                })
                continue
            response_type = registry.get(question["response_type"])
            if response_type is None:
                findings.append({
                    "finding_type": "TYPE_MISMATCH",
                    "severity": "ERROR",
                    "source_locator": candidate.source_locator,
                    "detail": {"response_type": question["response_type"]},
                })
                continue
            parsed = response_type.parse_workbook(candidate.raw_value)
            validation = (
                response_type.validate(parsed.value) if parsed.is_success else None
            )
            if not parsed.is_success or validation is None or not validation.is_valid:
                findings.append({
                    "finding_type": "TYPE_MISMATCH",
                    "severity": "ERROR",
                    "source_locator": candidate.source_locator,
                    "detail": {
                        "question_code": candidate.question_code,
                        "errors": parsed.errors if not parsed.is_success else validation.errors,
                    },
                })
                continue
            valid_candidates.append(candidate)
            normalized[id(candidate)] = (
                response_type.normalize(parsed.value or {}),
                question["response_schema_version"],
            )
        return valid_candidates, findings, normalized

    def _extract_target_key(self, sheet_name: str, candidate: Any) -> str:
        """Extract the target key (question code) from an adapter candidate."""
        # AppCandidate: uses question_index
        if hasattr(candidate, "question_index"):
            return f"APP-{candidate.question_index:03d}"

        # TSSCandidate: uses question_code
        if hasattr(candidate, "question_code"):
            return candidate.question_code

        # ITAPCandidate: uses field_name
        if hasattr(candidate, "field_name"):
            return f"ITAP-{candidate.field_name}"

        # ProvisioningCandidate: uses field_name
        if hasattr(candidate, "field_name"):
            return f"PROV-{candidate.field_name}"

        # InfraCandidate: uses resource_type + row
        if hasattr(candidate, "resource_type"):
            row = getattr(candidate, "row_number", 0)
            return f"INFRA-{candidate.resource_type}-{row}"

        # DatabaseCandidate: uses db_name + row
        if hasattr(candidate, "db_name"):
            row = getattr(candidate, "row_number", 0)
            return f"DB-{candidate.db_name}-{row}"

        # WaveUtilRowResult: uses row_number
        if hasattr(candidate, "row_number") and sheet_name == "WaveUtil":
            return f"WAVEUTIL-{candidate.row_number}"

        # UAQCandidate: uses question_code directly
        if sheet_name == "UAQ" and hasattr(candidate, "question_code"):
            return candidate.question_code

        if isinstance(candidate, InterfaceRecord):
            return "|".join(
                str(value or "") for value in (
                    candidate.interface_correlation_id,
                    candidate.direction,
                    candidate.endpoint,
                    candidate.current_protocol,
                    candidate.current_port,
                )
            )

        if isinstance(candidate, InterfaceAggregateCandidate):
            return candidate.question_code

        # Fallback
        return f"{sheet_name.upper()}-UNKNOWN"

    def _extract_source_locator(self, sheet_name: str, candidate: Any) -> dict:
        """Extract source locator from an adapter candidate."""
        locator: dict[str, Any] = {"sheet": sheet_name}

        # Most candidates have row_number
        if hasattr(candidate, "row_number"):
            locator["row"] = candidate.row_number

        # AppCandidate has source_locator string
        if hasattr(candidate, "source_locator") and isinstance(
            candidate.source_locator, str
        ):
            locator["cell"] = candidate.source_locator

        # Some have column info
        if hasattr(candidate, "column"):
            locator["column"] = candidate.column

        # UAQCandidate has source_locator dict
        if hasattr(candidate, "source_locator") and isinstance(
            candidate.source_locator, dict
        ):
            locator.update(candidate.source_locator)

        if isinstance(candidate, InterfaceRecord) or isinstance(candidate, InterfaceAggregateCandidate):
            locator.update(candidate.source_locator)

        return locator

    def _extract_raw_value(self, candidate: Any) -> dict:
        """Extract raw value from an adapter candidate."""
        # AppCandidate: raw_value is a string
        if hasattr(candidate, "raw_value"):
            return {"value": candidate.raw_value}

        # TSSCandidate: has manufacturer, model, etc.
        if hasattr(candidate, "manufacturer"):
            return {
                "manufacturer": getattr(candidate, "manufacturer", None),
                "model": getattr(candidate, "model", None),
                "quantity": getattr(candidate, "quantity", None),
            }

        # ITAPCandidate: has label and value
        if hasattr(candidate, "label") and hasattr(candidate, "value"):
            return {"label": candidate.label, "value": candidate.value}

        # ProvisioningCandidate: has field_name and value
        if hasattr(candidate, "field_name") and hasattr(candidate, "value"):
            return {"field_name": candidate.field_name, "value": candidate.value}

        # InfraCandidate: has resource_type and attributes
        if hasattr(candidate, "resource_type"):
            return {
                "resource_type": getattr(candidate, "resource_type", None),
                "name": getattr(candidate, "name", None),
                "attributes": getattr(candidate, "attributes", {}),
            }

        # DatabaseCandidate: has db_name and attributes
        if hasattr(candidate, "db_name"):
            return {
                "db_name": getattr(candidate, "db_name", None),
                "db_type": getattr(candidate, "db_type", None),
                "attributes": getattr(candidate, "attributes", {}),
            }

        # WaveUtilRowResult: has values dict
        if hasattr(candidate, "values") and candidate.values is not None:
            return dict(candidate.values)

        if isinstance(candidate, InterfaceRecord):
            return candidate.raw_values

        if isinstance(candidate, InterfaceAggregateCandidate):
            return {"value": candidate.proposed_value}

        # Fallback: try to convert to dict
        if hasattr(candidate, "__dict__"):
            return {k: v for k, v in candidate.__dict__.items() if not k.startswith("_")}

        return {"raw": str(candidate)}

    # ------------------------------------------------------------------
    # Finding attribute extraction (cross-adapter, defensive)
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_finding_attrs(
        sheet_name: str, finding: Any
    ) -> tuple[str, str, str | None, Any]:
        """
        Extract persistence-ready attributes from any finding/drift object.

        Returns:
            (finding_type, severity, source_locator, detail)
        """
        if isinstance(finding, dict):
            source_locator = finding.get("source_locator")
            return (
                str(finding.get("finding_type", "UNKNOWN")),
                str(finding.get("severity", "WARNING")),
                json.dumps(source_locator, sort_keys=True)
                if isinstance(source_locator, dict)
                else source_locator,
                {
                    **(finding.get("detail") or {}),
                    "source_locator": source_locator,
                },
            )

        # finding_type: some adapters use .finding_type, App uses .drift_type
        ft = getattr(finding, "finding_type", None) or getattr(
            finding, "drift_type", None
        )
        if ft is not None:
            finding_type = ft.value if hasattr(ft, "value") else str(ft)
        else:
            finding_type = "UNKNOWN"

        # severity: App drift has .severity (RowDriftSeverity); others default to WARNING
        sev = getattr(finding, "severity", "WARNING")
        severity = sev.value if hasattr(sev, "value") else str(sev)

        # source_locator: some objects carry it directly; fall back to row_number
        source_locator: str | None = getattr(finding, "source_locator", None)
        if source_locator is None:
            row_num = getattr(finding, "row_number", 0)
            # WaveUtilFinding also has field_name
            field_name = getattr(finding, "field_name", None)
            if field_name:
                source_locator = f"Sheet:{sheet_name}/Row:{row_num}/Field:{field_name}"
            else:
                source_locator = f"Sheet:{sheet_name}/Row:{row_num}"

        # Never persist a Python repr as user-facing detail: adapters that
        # carry no `detail` still expose the fields a reviewer needs, so build
        # a structured payload from them instead of stringifying the object.
        detail: Any = getattr(finding, "detail", None)
        if detail is None:
            detail = {
                key: value
                for key, value in (
                    ("message", getattr(finding, "message", None)),
                    ("column", getattr(finding, "column", None)),
                    ("row", getattr(finding, "row_number", None)),
                    ("field", getattr(finding, "field_name", None)),
                )
                if value is not None
            } or {"message": str(finding)}

        return finding_type, severity, source_locator, detail
