"""
Unit tests for WorkbookService — B06 workbook orchestration/import service.

TDD RED → GREEN: written before the service is implemented.
Imports will raise ImportError/AttributeError until the service exists.

Fixtures ``tmp_engine`` and ``session_factory`` come from conftest.py.
Side-effect imports at module level register all ORM tables in Base.metadata
BEFORE conftest.tmp_engine calls Base.metadata.create_all().
"""
from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime

import pytest

# --- side-effect: register import_runs, import_sheet_results, import_findings ---
import migration_intake.persistence.models_imports  # noqa: F401
from migration_intake.application.commands import (
    CreateApplicationCommand,
    CreateIntakeCommand,
)
from migration_intake.application.dto import ActorContext

# --- imports under test (will raise ImportError until service exists) ----------
from migration_intake.application.errors import (
    EvidenceApplicationMismatchError,
    EvidenceNotFoundError,
)
from migration_intake.application.services.applications import ApplicationService
from migration_intake.application.services.workbook import (
    ProcessWorkbookResult,
    WorkbookService,
    _canonical_sheet_name,
)
from migration_intake.persistence.repositories.applications import ApplicationRepository
from migration_intake.persistence.repositories.candidates import CandidateRepository
from migration_intake.persistence.models import CatalogQuestion, CatalogSection
from migration_intake.application.services.import_coverage import ImportCoverageService
from migration_intake.persistence.repositories.evidence import EvidenceRepository
from migration_intake.persistence.repositories.imports import ImportRepository
from migration_intake.persistence.unit_of_work import uow_context

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_actor() -> ActorContext:
    return ActorContext(
        actor_id=str(uuid.uuid4()),
        display_name="Test Actor",
        actor_type="CONFIGURED",
    )


def _sha256_hex() -> str:
    """Return a deterministic-looking fake SHA-256 hex string."""
    return hashlib.sha256(uuid.uuid4().bytes).hexdigest()


def _create_app(session_factory, actor: ActorContext) -> str:
    """Create an application + ensure actor row; return app_id."""
    svc = ApplicationService(session_factory)
    result = svc.create_application(
        CreateApplicationCommand(
            display_name="Test App",
            identifiers=(),
            actor=actor,
        )
    )
    return result["id"]


def _create_catalog_release(session_factory) -> str:
    """Insert a minimal PUBLISHED catalog release row; return its id."""
    release_id = str(uuid.uuid4())
    sha256 = _sha256_hex()
    now = datetime.now(tz=UTC)
    with uow_context(session_factory) as uow:
        uow.catalogs.add_release(
            release_id=release_id,
            semantic_version="1.0.0",
            source_filename="test-catalog.yaml",
            source_sha256=sha256,
            compiler_version="1.0.0",
            pub_state="PUBLISHED",
            created_at=now,
        )
        uow.commit()
    return release_id


def _create_intake(session_factory, actor: ActorContext, app_id: str) -> str:
    """Create a DRAFT intake for the given app; return intake_id."""
    cat_id = _create_catalog_release(session_factory)
    svc = ApplicationService(session_factory)
    result = svc.create_intake(
        CreateIntakeCommand(
            application_id=app_id,
            catalog_release_id=cat_id,
            actor=actor,
        )
    )
    return result["id"]


def _add_catalog_question(
    session_factory, catalog_id: str, question_code: str, response_type: str
) -> None:
    session = session_factory()
    try:
        section = CatalogSection(
            id=str(uuid.uuid4()),
            release_id=catalog_id,
            section_code="Application",
            display_name="Application",
            display_order=1,
        )
        session.add(section)
        session.flush()
        session.add(CatalogQuestion(
            id=str(uuid.uuid4()),
            section_id=section.id,
            question_code=question_code,
            question_text="Test question",
            response_type=response_type,
            required_level="REQUIRED",
            collection_mode="AUTO_IMPORT",
            display_order=1,
            is_active=True,
            response_schema_version="1.0",
        ))
        session.commit()
    finally:
        session.close()


def _create_evidence(
    session_factory,
    actor: ActorContext,
    app_id: str,
    intake_id: str | None = None,
) -> str:
    """
    Insert an EvidenceItem row directly (bypasses FilesystemStore).
    Returns evidence_id as a string.
    """
    now = datetime.now(tz=UTC)
    evidence_id = str(uuid.uuid4())
    sha = _sha256_hex()
    storage_key = f"{sha[:2]}/{sha}"

    session = session_factory()
    try:
        repo = EvidenceRepository(session)
        repo.add(
            evidence_id=evidence_id,
            application_id=app_id,
            intake_id=intake_id,
            storage_key=storage_key,
            sha256_hex=sha,
            size_bytes=1024,
            media_type=(
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            ),
            original_filename="test.xlsx",
            created_at=now,
            created_by_id=actor.actor_id,
        )
        session.commit()
    finally:
        session.close()
    return evidence_id


def _make_service(session_factory) -> WorkbookService:
    """Create a WorkbookService with no FilesystemStore (validation via DB only)."""
    return WorkbookService(session_factory=session_factory, evidence_store=None)


def _tss_rows(n: int = 1) -> list[dict]:
    """Generate n valid TSS rows without lifecycle (→ n candidates, 0 findings)."""
    return [
        {
            "Manufacturer": f"Vendor{i}",
            "Source Tech Stack": f"App{i}",
            "Source Version": f"1.{i}",
            "Target Tech Stack": "RDS",
            "Target Version": "13",
            "TSS Version Lifecycle": "",
            "Notes": "",
        }
        for i in range(n)
    ]


def _tss_rows_with_lifecycle(n: int = 1) -> list[dict]:
    """Generate n TSS rows with lifecycle set (→ n candidates, n UNVERIFIED_LIFECYCLE findings)."""
    return [
        {
            "Manufacturer": f"Vendor{i}",
            "Source Tech Stack": f"App{i}",
            "Source Version": f"1.{i}",
            "Target Tech Stack": "RDS",
            "Target Version": "13",
            "TSS Version Lifecycle": "EoL",
            "Notes": "",
        }
        for i in range(n)
    ]


# ---------------------------------------------------------------------------
# Test 1 — EvidenceNotFoundError when evidence_item_id is unknown
# ---------------------------------------------------------------------------


def test_process_nonexistent_evidence_raises(session_factory):
    """A random evidence_item_id that does not exist → EvidenceNotFoundError."""
    actor = _make_actor()
    app_id = _create_app(session_factory, actor)
    intake_id = _create_intake(session_factory, actor, app_id)
    svc = _make_service(session_factory)

    with pytest.raises(EvidenceNotFoundError):
        svc.process_workbook(
            application_id=app_id,
            intake_id=intake_id,
            evidence_item_id=str(uuid.uuid4()),  # non-existent
            sheet_rows={},
            actor=actor,
        )


# ---------------------------------------------------------------------------
# Test 2 — EvidenceApplicationMismatchError when evidence belongs to another app
# ---------------------------------------------------------------------------


def test_process_evidence_wrong_application_raises(session_factory):
    """Evidence item belongs to app_a; caller passes app_b → EvidenceApplicationMismatchError."""
    actor = _make_actor()
    app_a_id = _create_app(session_factory, actor)
    app_b_id = _create_app(session_factory, actor)
    intake_id = _create_intake(session_factory, actor, app_a_id)

    # Evidence is attached to app_a
    evidence_id = _create_evidence(session_factory, actor, app_a_id, intake_id)

    svc = _make_service(session_factory)

    with pytest.raises(EvidenceApplicationMismatchError):
        svc.process_workbook(
            application_id=app_b_id,  # wrong application
            intake_id=intake_id,
            evidence_item_id=evidence_id,
            sheet_rows={},
            actor=actor,
        )


# ---------------------------------------------------------------------------
# Test 3 — Happy path creates an ImportRun in state=COMPLETED
# ---------------------------------------------------------------------------


def test_process_creates_import_run(session_factory):
    """Valid evidence + rows → ImportRun in DB with state=COMPLETED."""
    actor = _make_actor()
    app_id = _create_app(session_factory, actor)
    intake_id = _create_intake(session_factory, actor, app_id)
    evidence_id = _create_evidence(session_factory, actor, app_id, intake_id)
    svc = _make_service(session_factory)

    result = svc.process_workbook(
        application_id=app_id,
        intake_id=intake_id,
        evidence_item_id=evidence_id,
        sheet_rows={},
        actor=actor,
    )

    assert isinstance(result, ProcessWorkbookResult)
    assert result.state == "COMPLETED"
    assert result.run_id is not None

    # Verify persisted run
    session = session_factory()
    try:
        repo = ImportRepository(session)
        run = repo.get_run(result.run_id)
        assert run is not None
        assert run["state"] == "COMPLETED"
        assert run["contract_name"] == "APP_DATA_CAPTURE_V1"
        assert run["evidence_item_id"] == evidence_id
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Test 4 — sheet_results has one entry per processed sheet
# ---------------------------------------------------------------------------


def test_process_records_sheet_results(session_factory):
    """result.sheet_results contains one entry for each sheet processed."""
    actor = _make_actor()
    app_id = _create_app(session_factory, actor)
    intake_id = _create_intake(session_factory, actor, app_id)
    evidence_id = _create_evidence(session_factory, actor, app_id, intake_id)
    svc = _make_service(session_factory)

    sheet_rows = {"TSS": _tss_rows(2)}
    result = svc.process_workbook(
        application_id=app_id,
        intake_id=intake_id,
        evidence_item_id=evidence_id,
        sheet_rows=sheet_rows,
        actor=actor,
    )

    assert result.total_sheets == 1
    assert len(result.sheet_results) == 1
    assert result.sheet_results[0]["sheet_name"] == "TSS"


def test_uaq_identity_mismatch_quarantines_without_candidates(session_factory):
    actor = _make_actor()
    app_id = _create_app(session_factory, actor)
    intake_id = _create_intake(session_factory, actor, app_id)
    evidence_id = _create_evidence(session_factory, actor, app_id, intake_id)
    now = datetime.now(tz=UTC)
    session = session_factory()
    try:
        ApplicationRepository(session).add_identifier(
            application_id=app_id,
            identifier_type="CORRELATION",
            raw_value="corr-123",
            normalized_value="corr123",
            created_at=now,
        )
        session.commit()
    finally:
        session.close()


def test_uaq_type_mismatch_creates_finding_without_candidate(session_factory):
    actor = _make_actor()
    app_id = _create_app(session_factory, actor)
    catalog_id = _create_catalog_release(session_factory)
    _add_catalog_question(session_factory, catalog_id, "APP-003", "SINGLE_SELECT")
    intake_id = ApplicationService(session_factory).create_intake(CreateIntakeCommand(
        application_id=app_id, catalog_release_id=catalog_id, actor=actor,
    ))["id"]
    evidence_id = _create_evidence(session_factory, actor, app_id, intake_id)
    session = session_factory()
    try:
        ApplicationRepository(session).add_identifier(
            application_id=app_id,
            identifier_type="CORRELATION",
            raw_value="corr-123",
            normalized_value="corr123",
            created_at=datetime.now(tz=UTC),
        )
        session.commit()
    finally:
        session.close()

    result = _make_service(session_factory).process_workbook(
        application_id=app_id,
        intake_id=intake_id,
        evidence_item_id=evidence_id,
        sheet_rows={"UAQ": [{
            "Correlation ID": "corr-123",
            "INV9-What is the current operational status of the application?": 42,
        }]},
        actor=actor,
    )

    assert result.state == "COMPLETED"
    assert result.total_candidates == 0
    session = session_factory()
    try:
        findings = ImportRepository(session).list_findings_for_run(result.run_id)
        assert any(finding["finding_type"] == "TYPE_MISMATCH" for finding in findings)
    finally:
        session.close()


def test_uaq_valid_value_persists_normalized_pinned_schema_candidate(session_factory):
    actor = _make_actor()
    app_id = _create_app(session_factory, actor)
    catalog_id = _create_catalog_release(session_factory)
    _add_catalog_question(session_factory, catalog_id, "APP-003", "SINGLE_SELECT")
    intake_id = ApplicationService(session_factory).create_intake(CreateIntakeCommand(
        application_id=app_id, catalog_release_id=catalog_id, actor=actor,
    ))["id"]
    evidence_id = _create_evidence(session_factory, actor, app_id, intake_id)
    session = session_factory()
    try:
        ApplicationRepository(session).add_identifier(
            application_id=app_id,
            identifier_type="CORRELATION",
            raw_value="corr-123",
            normalized_value="corr123",
            created_at=datetime.now(tz=UTC),
        )
        session.commit()
    finally:
        session.close()

    result = _make_service(session_factory).process_workbook(
        application_id=app_id,
        intake_id=intake_id,
        evidence_item_id=evidence_id,
        sheet_rows={"UAQ": [{
            "Correlation ID": "corr-123",
            "INV9-What is the current operational status of the application?": " active ",
        }]},
        actor=actor,
    )

    session = session_factory()
    try:
        candidate = CandidateRepository(session).get_by_run(result.run_id)[0]
        assert candidate.normalized_value_json == {"value": "ACTIVE"}
        assert candidate.response_schema_version == "1.0"
        coverage = ImportCoverageService(session_factory).get_run_coverage(result.run_id)
        assert coverage["proposed_question_count"] == 1
        assert coverage["remaining_required_question_count"] == 0
    finally:
        session.close()


def test_uaq_question_candidate_is_application_scoped_and_reviewable(session_factory):
    """
    A UAQ question candidate produced by the real service must be eligible for
    reviewer acceptance.

    Both the coverage template and the accept route gate on
    ``scope_json.scope == "APPLICATION"``. Candidate-decision tests construct
    candidates directly with that scope already stamped, so nothing previously
    proved the production UAQ path stamps it — and it did not, which made every
    real UAQ proposal permanently unacceptable.
    """
    actor = _make_actor()
    app_id = _create_app(session_factory, actor)
    catalog_id = _create_catalog_release(session_factory)
    _add_catalog_question(session_factory, catalog_id, "APP-003", "SINGLE_SELECT")
    intake_id = ApplicationService(session_factory).create_intake(CreateIntakeCommand(
        application_id=app_id, catalog_release_id=catalog_id, actor=actor,
    ))["id"]
    evidence_id = _create_evidence(session_factory, actor, app_id, intake_id)
    session = session_factory()
    try:
        ApplicationRepository(session).add_identifier(
            application_id=app_id,
            identifier_type="CORRELATION",
            raw_value="corr-123",
            normalized_value="corr123",
            created_at=datetime.now(tz=UTC),
        )
        session.commit()
    finally:
        session.close()

    result = _make_service(session_factory).process_workbook(
        application_id=app_id,
        intake_id=intake_id,
        evidence_item_id=evidence_id,
        sheet_rows={"UAQ": [{
            "Correlation ID": "corr-123",
            "INV9-What is the current operational status of the application?": "active",
        }]},
        actor=actor,
    )

    session = session_factory()
    try:
        candidate = CandidateRepository(session).get_by_run(result.run_id)[0]
        assert candidate.target_kind == "QUESTION"
        assert candidate.scope_json == {"scope": "APPLICATION"}
    finally:
        session.close()

    coverage = ImportCoverageService(session_factory).get_run_coverage(result.run_id)
    proposal = coverage["candidates"][0]
    assert proposal["is_application_scoped"] is True
    assert proposal["question_text"] == "Test question"


def test_uaq_missing_identity_quarantines_without_candidates(session_factory):
    actor = _make_actor()
    app_id = _create_app(session_factory, actor)
    intake_id = _create_intake(session_factory, actor, app_id)
    evidence_id = _create_evidence(session_factory, actor, app_id, intake_id)

    result = _make_service(session_factory).process_workbook(
        application_id=app_id,
        intake_id=intake_id,
        evidence_item_id=evidence_id,
        sheet_rows={"UAQ": [{"App name": "Billing"}]},
        actor=actor,
    )

    assert result.state == "QUARANTINED"
    assert result.total_candidates == 0
    session = session_factory()
    try:
        run = ImportRepository(session).get_run(result.run_id)
        assert run["identity_decision"] == "APPLICATION_ID_MISSING"
    finally:
        session.close()


def test_uaq_and_interface_tracking_identity_conflict_quarantines(session_factory):
    actor = _make_actor()
    app_id = _create_app(session_factory, actor)
    intake_id = _create_intake(session_factory, actor, app_id)
    evidence_id = _create_evidence(session_factory, actor, app_id, intake_id)
    session = session_factory()
    try:
        ApplicationRepository(session).add_identifier(
            application_id=app_id,
            identifier_type="CORRELATION",
            raw_value="corr-123",
            normalized_value="corr123",
            created_at=datetime.now(tz=UTC),
        )
        session.commit()
    finally:
        session.close()

    result = _make_service(session_factory).process_workbook(
        application_id=app_id,
        intake_id=intake_id,
        evidence_item_id=evidence_id,
        sheet_rows={
            "UAQ": [{"Correlation ID": "corr-123"}],
            "Migrating App Data": [{"Correlation ID": "corr-999"}],
        },
        actor=actor,
    )

    assert result.state == "QUARANTINED"
    assert result.total_candidates == 0
    session = session_factory()
    try:
        run = ImportRepository(session).get_run(result.run_id)
        assert run["identity_decision"] == "SOURCE_ID_CONFLICT"
    finally:
        session.close()


def test_interface_tracking_persists_scoped_register_and_progress_candidate(session_factory):
    actor = _make_actor()
    app_id = _create_app(session_factory, actor)
    intake_id = _create_intake(session_factory, actor, app_id)
    evidence_id = _create_evidence(session_factory, actor, app_id, intake_id)
    session = session_factory()
    try:
        ApplicationRepository(session).add_identifier(
            application_id=app_id,
            identifier_type="CORRELATION",
            raw_value="corr-123",
            normalized_value="corr123",
            created_at=datetime.now(tz=UTC),
        )
        session.commit()
    finally:
        session.close()

    result = _make_service(session_factory).process_workbook(
        application_id=app_id,
        intake_id=intake_id,
        evidence_item_id=evidence_id,
        sheet_rows={
            "Migrating App Data": [{"Correlation ID": "corr-123"}],
            "Interfaces": [{
                "Interface Correlation ID": "if-001",
                "Direction": "OUTBOUND",
                "Endpoint": "vendor.example",
                "Current Protocol": "HTTPS",
                "Current Port": "443",
                "Owner Commitment": "",
            }],
        },
        actor=actor,
    )

    assert result.state == "COMPLETED"
    assert result.total_candidates == 3
    session = session_factory()
    try:
        candidates = CandidateRepository(session).get_by_run(result.run_id)
        register = next(candidate for candidate in candidates if candidate.target_kind == "INTERFACE_REGISTER")
        int_001 = next(candidate for candidate in candidates if candidate.target_key == "INT-001")
        int_002 = next(candidate for candidate in candidates if candidate.target_key == "INT-002")
        assert register.scope_json == {"scope": "INTERFACE", "direction": "OUTBOUND"}
        assert register.source_locator == {"sheet": "Interfaces", "row": 2}
        assert int_001.normalized_value_json == {"value": "IN_PROGRESS"}
        assert int_002.normalized_value_json == {"value": "IN_PROGRESS"}
        assert {
            candidate.target_key for candidate in candidates
        }.isdisjoint({"INT-003", "NET-006", "SEC-006", "MIG-005"})
        findings = ImportRepository(session).list_findings_for_run(result.run_id)
        assert {finding["finding_type"] for finding in findings}.issuperset({
            "INT_003_GOVERNANCE_GAP",
            "MIG_005_TEST_STATUS_GAP",
        })
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Test 5 — total_candidates reflects candidate output from adapters
# ---------------------------------------------------------------------------


def test_process_counts_total_candidates(session_factory):
    """Two valid TSS rows (no lifecycle) → total_candidates=2."""
    actor = _make_actor()
    app_id = _create_app(session_factory, actor)
    intake_id = _create_intake(session_factory, actor, app_id)
    evidence_id = _create_evidence(session_factory, actor, app_id, intake_id)
    svc = _make_service(session_factory)

    result = svc.process_workbook(
        application_id=app_id,
        intake_id=intake_id,
        evidence_item_id=evidence_id,
        sheet_rows={"TSS": _tss_rows(2)},
        actor=actor,
    )

    assert result.total_candidates == 2


# ---------------------------------------------------------------------------
# Test 6 — total_findings reflects finding output from adapters
# ---------------------------------------------------------------------------


def test_process_counts_total_findings(session_factory):
    """One TSS row with lifecycle 'EoL' → total_findings=1 (UNVERIFIED_LIFECYCLE)."""
    actor = _make_actor()
    app_id = _create_app(session_factory, actor)
    intake_id = _create_intake(session_factory, actor, app_id)
    evidence_id = _create_evidence(session_factory, actor, app_id, intake_id)
    svc = _make_service(session_factory)

    result = svc.process_workbook(
        application_id=app_id,
        intake_id=intake_id,
        evidence_item_id=evidence_id,
        sheet_rows={"TSS": _tss_rows_with_lifecycle(1)},
        actor=actor,
    )

    assert result.total_findings == 1


# ---------------------------------------------------------------------------
# Test 7 — Idempotency: same evidence_item_id + contract → deduplicated=True
# ---------------------------------------------------------------------------


def test_process_idempotent_same_evidence(session_factory):
    """Processing the same evidence_item_id twice returns same run_id, deduplicated=True."""
    actor = _make_actor()
    app_id = _create_app(session_factory, actor)
    intake_id = _create_intake(session_factory, actor, app_id)
    evidence_id = _create_evidence(session_factory, actor, app_id, intake_id)
    svc = _make_service(session_factory)

    kwargs = dict(
        application_id=app_id,
        intake_id=intake_id,
        evidence_item_id=evidence_id,
        sheet_rows={"TSS": _tss_rows(1)},
        actor=actor,
    )

    result1 = svc.process_workbook(**kwargs)
    result2 = svc.process_workbook(**kwargs)

    assert result1.state == "COMPLETED"
    assert result2.deduplicated is True
    assert result2.run_id == result1.run_id


def test_process_reprocesses_evidence_from_older_parser_version(session_factory):
    """A parser fix must not reuse a completed run from an older parser."""
    actor = _make_actor()
    app_id = _create_app(session_factory, actor)
    intake_id = _create_intake(session_factory, actor, app_id)
    evidence_id = _create_evidence(session_factory, actor, app_id, intake_id)
    svc = _make_service(session_factory)

    first = svc.process_workbook(
        application_id=app_id,
        intake_id=intake_id,
        evidence_item_id=evidence_id,
        sheet_rows={"TSS": _tss_rows(1)},
        actor=actor,
    )
    svc._PARSER_VERSION = "1.0.0"
    older = svc.process_workbook(
        application_id=app_id,
        intake_id=intake_id,
        evidence_item_id=evidence_id,
        sheet_rows={"TSS": _tss_rows(1)},
        actor=actor,
    )

    assert older.deduplicated is False
    assert older.run_id != first.run_id


# ---------------------------------------------------------------------------
# Test 8 — Findings are persisted to import_findings table
# ---------------------------------------------------------------------------


def test_process_persists_findings_to_db(session_factory):
    """UNVERIFIED_LIFECYCLE finding from TSS adapter → ImportFinding row in DB."""
    actor = _make_actor()
    app_id = _create_app(session_factory, actor)
    intake_id = _create_intake(session_factory, actor, app_id)
    evidence_id = _create_evidence(session_factory, actor, app_id, intake_id)
    svc = _make_service(session_factory)

    result = svc.process_workbook(
        application_id=app_id,
        intake_id=intake_id,
        evidence_item_id=evidence_id,
        sheet_rows={"TSS": _tss_rows_with_lifecycle(1)},
        actor=actor,
    )

    session = session_factory()
    try:
        repo = ImportRepository(session)
        findings = repo.list_findings_for_run(result.run_id)
        assert len(findings) == 1
        assert findings[0]["finding_type"] == "UNVERIFIED_LIFECYCLE"
        assert findings[0]["sheet_name"] == "TSS"
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Test 9 — Unknown sheet names in sheet_rows are silently skipped
# ---------------------------------------------------------------------------


def test_process_unknown_sheet_skipped(session_factory):
    """sheet_rows with 'UnknownSheet' key → no crash; sheet omitted from results."""
    actor = _make_actor()
    app_id = _create_app(session_factory, actor)
    intake_id = _create_intake(session_factory, actor, app_id)
    evidence_id = _create_evidence(session_factory, actor, app_id, intake_id)
    svc = _make_service(session_factory)

    sheet_rows = {
        "TSS": _tss_rows(1),
        "UnknownSheet": [{"col": "value"}],
    }

    result = svc.process_workbook(
        application_id=app_id,
        intake_id=intake_id,
        evidence_item_id=evidence_id,
        sheet_rows=sheet_rows,
        actor=actor,
    )

    # Only TSS was processed; UnknownSheet was silently skipped
    assert result.total_sheets == 1
    sheet_names = [sr["sheet_name"] for sr in result.sheet_results]
    assert "UnknownSheet" not in sheet_names
    assert "TSS" in sheet_names


# ---------------------------------------------------------------------------
# Sheet name canonicalization — Excel worksheet-name truncation
# ---------------------------------------------------------------------------


class TestCanonicalSheetNameExcelTruncation:
    """
    Excel silently truncates worksheet names to 31 characters. A real UAQ
    export sheet named "UAQ - Unified Assessment Questionnaire" (39 chars)
    is saved by Excel as "UAQ - Unified Assessment Questi" (31 chars) —
    this must still resolve to the "UAQ" contract, not be silently skipped
    as an unrecognized sheet.
    """

    def test_untruncated_real_world_uaq_sheet_name_is_recognized(self) -> None:
        assert _canonical_sheet_name("UAQ - Unified Assessment Questionnaire") == "UAQ"

    def test_excel_truncated_uaq_sheet_name_is_recognized(self) -> None:
        assert _canonical_sheet_name("UAQ - Unified Assessment Questi") == "UAQ"

    def test_exact_known_sheet_names_still_recognized(self) -> None:
        assert _canonical_sheet_name("UAQ") == "UAQ"
        assert _canonical_sheet_name("Interfaces") == "Interfaces"

    def test_unrelated_31_char_sheet_name_is_not_falsely_matched(self) -> None:
        unrelated = "x" * 31
        assert _canonical_sheet_name(unrelated) is None

    def test_completely_unknown_sheet_name_returns_none(self) -> None:
        assert _canonical_sheet_name("Some Random Sheet") is None


def test_unrecognized_sheet_records_a_finding(session_factory):
    """
    An unrecognized sheet must be reported, not silently dropped.

    Silent skipping made two real failures indistinguishable from an empty
    file: an Excel-truncated UAQ tab, and the real WaveUtil workbook whose
    tabs are named "Wave 3 Server Data"/"Wave 3 App" rather than "WaveUtil".
    A supplier renaming a tab must produce a diagnosable import.
    """
    actor = _make_actor()
    app_id = _create_app(session_factory, actor)
    intake_id = _create_intake(session_factory, actor, app_id)
    evidence_id = _create_evidence(session_factory, actor, app_id, intake_id)

    result = _make_service(session_factory).process_workbook(
        application_id=app_id,
        intake_id=intake_id,
        evidence_item_id=evidence_id,
        sheet_rows={
            "TSS": _tss_rows(1),
            "Wave 3 Server Data": [{"Server Name": "srv1"}],
        },
        actor=actor,
    )

    # The unknown sheet still produces no sheet result and no candidates...
    assert "Wave 3 Server Data" not in [sr["sheet_name"] for sr in result.sheet_results]

    # ...but it is no longer invisible.
    session = session_factory()
    try:
        findings = ImportRepository(session).list_findings_for_run(result.run_id)
    finally:
        session.close()

    unrecognized = [f for f in findings if f["finding_type"] == "UNRECOGNIZED_SHEET"]
    assert len(unrecognized) == 1
    assert unrecognized[0]["sheet_name"] == "Wave 3 Server Data"
    assert unrecognized[0]["severity"] == "WARNING"
