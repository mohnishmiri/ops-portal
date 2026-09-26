"""
Contract tests for ImportRepository — P05b (Import runs, sheet results, findings).

TDD discipline: written BEFORE implementation; fails with ImportError at
collection time until the repository is implemented.

Coverage:
  1. test_add_run_and_get              — add run state=PENDING, get by ID → correct dict.
  2. test_update_run_state_to_completed — add run, update to COMPLETED with counts → shows COMPLETED.
  3. test_list_runs_for_intake         — add 2 runs for same intake → list returns 2, newest first.
  4. test_add_sheet_result             — add_sheet_result for a run → list_sheet_results_for_run returns it.
  5. test_add_finding_and_list         — add 2 findings for a run → list_findings_for_run returns 2.
  6. test_run_state_invalid_run_returns_false — update_run_state for nonexistent ID → False.
  7. test_sheet_result_outcome_values  — all outcome values (VALID, QUARANTINED, SKIPPED, ERROR) insertable.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.orm import Session

# ── RED import — fails with ImportError until the module is implemented ──────
from migration_intake.persistence.repositories.imports import ImportRepository  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_NOW = datetime(2025, 6, 1, 10, 0, 0, tzinfo=timezone.utc)
_SHA256 = "a" * 64  # valid 64-char hex string


def _uid() -> str:
    return str(uuid.uuid4())


def _seed_actor(engine, actor_id: str) -> None:
    """Insert a minimal Actor row."""
    from migration_intake.persistence.models import Actor

    with Session(engine) as session:
        session.add(Actor(id=actor_id, display_name="Import Test Actor", created_at=_NOW))
        session.commit()


def _seed_application(engine, app_id: str, actor_id: str) -> None:
    """Insert a minimal Application row."""
    from migration_intake.persistence.models import Application

    with Session(engine) as session:
        session.add(
            Application(
                id=app_id,
                state="ACTIVE",
                display_name="Import Test App",
                created_at=_NOW,
                updated_at=_NOW,
                row_version=1,
                created_by_id=actor_id,
            )
        )
        session.commit()


def _seed_intake(engine, intake_id: str, app_id: str, actor_id: str) -> str:
    """Insert a minimal CatalogRelease + Intake row. Returns intake_id."""
    from migration_intake.persistence.models import CatalogRelease, Intake

    cat_id = _uid()
    with Session(engine) as session:
        session.add(
            CatalogRelease(
                id=cat_id,
                semantic_version="1.0.0",
                source_filename="v1.yaml",
                source_sha256="b" * 64,
                compiler_version="1.0",
                pub_state="PUBLISHED",
                created_at=_NOW,
            )
        )
        session.flush()
        session.add(
            Intake(
                id=intake_id,
                application_id=app_id,
                catalog_id=cat_id,
                state="OPEN",
                created_at=_NOW,
                updated_at=_NOW,
                row_version=1,
                created_by_id=actor_id,
            )
        )
        session.commit()
    return intake_id


def _seed_evidence_item(engine, evidence_id: str, app_id: str, intake_id: str, actor_id: str) -> None:
    """Insert a minimal EvidenceItem row."""
    from migration_intake.persistence.models_evidence import EvidenceItem

    sha = "c" * 64
    with Session(engine) as session:
        session.add(
            EvidenceItem(
                id=evidence_id,
                application_id=app_id,
                intake_id=intake_id,
                storage_key=f"imports/{sha}",
                sha256_hex=sha,
                size_bytes=1024,
                media_type="application/vnd.ms-excel",
                original_filename="data_capture.xlsx",
                state="ACTIVE",
                created_at=_NOW,
                created_by_id=actor_id,
            )
        )
        session.commit()


# ---------------------------------------------------------------------------
# Test 1 — add_run + get_run round-trip
# ---------------------------------------------------------------------------


def test_add_run_and_get(tmp_engine) -> None:
    """add_run inserts with state=PENDING; get_run in new session returns correct dict."""
    actor_id = _uid()
    app_id = _uid()
    intake_id = _uid()
    evidence_id = _uid()
    run_id = _uid()

    _seed_actor(tmp_engine, actor_id)
    _seed_application(tmp_engine, app_id, actor_id)
    _seed_intake(tmp_engine, intake_id, app_id, actor_id)
    _seed_evidence_item(tmp_engine, evidence_id, app_id, intake_id, actor_id)

    # Write
    with Session(tmp_engine) as session:
        repo = ImportRepository(session)
        result = repo.add_run(
            run_id=run_id,
            application_id=app_id,
            intake_id=intake_id,
            evidence_item_id=evidence_id,
            contract_name="APP_DATA_CAPTURE_V1",
            parser_version="1.0.0",
            created_at=_NOW,
            created_by_id=actor_id,
        )
        session.commit()

    # add_run must return a plain dict
    assert isinstance(result, dict)
    assert result["id"] == run_id
    assert result["state"] == "PENDING"
    assert result["contract_name"] == "APP_DATA_CAPTURE_V1"
    assert result["parser_version"] == "1.0.0"
    assert result["total_candidates"] == 0
    assert result["total_findings"] == 0

    # Read in a fresh session
    with Session(tmp_engine) as session:
        fetched = ImportRepository(session).get_run(run_id)

    assert fetched is not None
    assert fetched["id"] == run_id
    assert fetched["application_id"] == app_id
    assert fetched["intake_id"] == intake_id
    assert fetched["evidence_item_id"] == evidence_id
    assert fetched["state"] == "PENDING"
    assert fetched["contract_name"] == "APP_DATA_CAPTURE_V1"
    assert fetched["parser_version"] == "1.0.0"
    assert fetched["created_by_id"] == actor_id
    assert fetched["total_candidates"] == 0
    assert fetched["total_findings"] == 0


# ---------------------------------------------------------------------------
# Test 2 — update_run_state to COMPLETED
# ---------------------------------------------------------------------------


def test_update_run_state_to_completed(tmp_engine) -> None:
    """update_run_state changes state and optional summary fields; get_run shows COMPLETED."""
    actor_id = _uid()
    app_id = _uid()
    run_id = _uid()

    _seed_actor(tmp_engine, actor_id)
    _seed_application(tmp_engine, app_id, actor_id)

    with Session(tmp_engine) as session:
        ImportRepository(session).add_run(
            run_id=run_id,
            application_id=app_id,
            intake_id=None,
            evidence_item_id=None,
            contract_name="APP_DATA_CAPTURE_V1",
            parser_version="1.0.0",
            created_at=_NOW,
            created_by_id=actor_id,
        )
        session.commit()

    completed_at = _NOW + timedelta(seconds=30)
    with Session(tmp_engine) as session:
        updated = ImportRepository(session).update_run_state(
            run_id,
            "COMPLETED",
            total_sheets=5,
            total_candidates=42,
            total_findings=3,
            completed_at=completed_at,
        )
        session.commit()

    assert updated is True

    with Session(tmp_engine) as session:
        fetched = ImportRepository(session).get_run(run_id)

    assert fetched is not None
    assert fetched["state"] == "COMPLETED"
    assert fetched["total_sheets"] == 5
    assert fetched["total_candidates"] == 42
    assert fetched["total_findings"] == 3
    assert fetched["completed_at"] is not None


# ---------------------------------------------------------------------------
# Test 3 — list_runs_for_intake: 2 runs, newest first
# ---------------------------------------------------------------------------


def test_list_runs_for_intake(tmp_engine) -> None:
    """add 2 runs for same intake → list_runs_for_intake returns 2, newest first."""
    actor_id = _uid()
    app_id = _uid()
    intake_id = _uid()
    run_id_1 = _uid()
    run_id_2 = _uid()

    _seed_actor(tmp_engine, actor_id)
    _seed_application(tmp_engine, app_id, actor_id)
    _seed_intake(tmp_engine, intake_id, app_id, actor_id)

    earlier = _NOW
    later = _NOW + timedelta(minutes=5)

    with Session(tmp_engine) as session:
        repo = ImportRepository(session)
        repo.add_run(
            run_id=run_id_1,
            application_id=app_id,
            intake_id=intake_id,
            evidence_item_id=None,
            contract_name="APP_DATA_CAPTURE_V1",
            parser_version="1.0.0",
            created_at=earlier,
            created_by_id=actor_id,
        )
        repo.add_run(
            run_id=run_id_2,
            application_id=app_id,
            intake_id=intake_id,
            evidence_item_id=None,
            contract_name="APP_DATA_CAPTURE_V1",
            parser_version="1.0.1",
            created_at=later,
            created_by_id=actor_id,
        )
        session.commit()

    with Session(tmp_engine) as session:
        runs = ImportRepository(session).list_runs_for_intake(intake_id)

    assert len(runs) == 2
    # Newest first: run_id_2 (later created_at) should come first
    assert runs[0]["id"] == run_id_2
    assert runs[1]["id"] == run_id_1


# ---------------------------------------------------------------------------
# Test 4 — add_sheet_result + list_sheet_results_for_run
# ---------------------------------------------------------------------------


def test_add_sheet_result(tmp_engine) -> None:
    """add_sheet_result for a run → list_sheet_results_for_run returns it."""
    actor_id = _uid()
    app_id = _uid()
    run_id = _uid()
    result_id = _uid()

    _seed_actor(tmp_engine, actor_id)
    _seed_application(tmp_engine, app_id, actor_id)

    with Session(tmp_engine) as session:
        ImportRepository(session).add_run(
            run_id=run_id,
            application_id=app_id,
            intake_id=None,
            evidence_item_id=None,
            contract_name="APP_DATA_CAPTURE_V1",
            parser_version="1.0.0",
            created_at=_NOW,
            created_by_id=actor_id,
        )
        session.commit()

    with Session(tmp_engine) as session:
        sheet_result = ImportRepository(session).add_sheet_result(
            result_id=result_id,
            run_id=run_id,
            sheet_name="Server Inventory",
            outcome="VALID",
            candidate_count=10,
            finding_count=1,
            blank_rows_skipped=3,
            error_message=None,
        )
        session.commit()

    assert isinstance(sheet_result, dict)
    assert sheet_result["id"] == result_id
    assert sheet_result["run_id"] == run_id
    assert sheet_result["sheet_name"] == "Server Inventory"
    assert sheet_result["outcome"] == "VALID"
    assert sheet_result["candidate_count"] == 10
    assert sheet_result["finding_count"] == 1
    assert sheet_result["blank_rows_skipped"] == 3
    assert sheet_result["error_message"] is None

    with Session(tmp_engine) as session:
        results = ImportRepository(session).list_sheet_results_for_run(run_id)

    assert len(results) == 1
    assert results[0]["id"] == result_id
    assert results[0]["outcome"] == "VALID"


# ---------------------------------------------------------------------------
# Test 5 — add_finding + list_findings_for_run: 2 findings
# ---------------------------------------------------------------------------


def test_add_finding_and_list(tmp_engine) -> None:
    """add 2 findings for a run → list_findings_for_run returns 2."""
    actor_id = _uid()
    app_id = _uid()
    run_id = _uid()
    finding_id_1 = _uid()
    finding_id_2 = _uid()

    _seed_actor(tmp_engine, actor_id)
    _seed_application(tmp_engine, app_id, actor_id)

    with Session(tmp_engine) as session:
        ImportRepository(session).add_run(
            run_id=run_id,
            application_id=app_id,
            intake_id=None,
            evidence_item_id=None,
            contract_name="APP_DATA_CAPTURE_V1",
            parser_version="1.0.0",
            created_at=_NOW,
            created_by_id=actor_id,
        )
        session.commit()

    with Session(tmp_engine) as session:
        repo = ImportRepository(session)
        f1 = repo.add_finding(
            finding_id=finding_id_1,
            run_id=run_id,
            sheet_name="Server Inventory",
            finding_type="MISSING_ROW",
            severity="ERROR",
            source_locator="Sheet1!A5",
            detail={"row": 5, "column": "hostname"},
        )
        f2 = repo.add_finding(
            finding_id=finding_id_2,
            run_id=run_id,
            sheet_name="Server Inventory",
            finding_type="DUPLICATE_ITEM",
            severity="WARNING",
            source_locator=None,
            detail=None,
        )
        session.commit()

    assert f1["id"] == finding_id_1
    assert f1["finding_type"] == "MISSING_ROW"
    assert f1["severity"] == "ERROR"
    assert f1["detail"] == {"row": 5, "column": "hostname"}

    assert f2["id"] == finding_id_2
    assert f2["severity"] == "WARNING"
    assert f2["detail"] is None

    with Session(tmp_engine) as session:
        findings = ImportRepository(session).list_findings_for_run(run_id)

    assert len(findings) == 2
    finding_ids = {f["id"] for f in findings}
    assert finding_id_1 in finding_ids
    assert finding_id_2 in finding_ids


# ---------------------------------------------------------------------------
# Test 6 — update_run_state for nonexistent ID → False
# ---------------------------------------------------------------------------


def test_run_state_invalid_run_returns_false(tmp_engine) -> None:
    """update_run_state for a nonexistent run_id returns False."""
    with Session(tmp_engine) as session:
        result = ImportRepository(session).update_run_state(
            _uid(), "FAILED"
        )
        session.commit()

    assert result is False


# ---------------------------------------------------------------------------
# Test 7 — all sheet result outcome values are insertable
# ---------------------------------------------------------------------------


def test_sheet_result_outcome_values(tmp_engine) -> None:
    """All outcome values (VALID, QUARANTINED, SKIPPED, ERROR) can be inserted."""
    actor_id = _uid()
    app_id = _uid()
    run_id = _uid()

    _seed_actor(tmp_engine, actor_id)
    _seed_application(tmp_engine, app_id, actor_id)

    with Session(tmp_engine) as session:
        ImportRepository(session).add_run(
            run_id=run_id,
            application_id=app_id,
            intake_id=None,
            evidence_item_id=None,
            contract_name="APP_DATA_CAPTURE_V1",
            parser_version="1.0.0",
            created_at=_NOW,
            created_by_id=actor_id,
        )
        session.commit()

    outcomes = ["VALID", "QUARANTINED", "SKIPPED", "ERROR"]
    with Session(tmp_engine) as session:
        repo = ImportRepository(session)
        for outcome in outcomes:
            repo.add_sheet_result(
                result_id=_uid(),
                run_id=run_id,
                sheet_name=f"Sheet_{outcome}",
                outcome=outcome,
            )
        session.commit()

    with Session(tmp_engine) as session:
        results = ImportRepository(session).list_sheet_results_for_run(run_id)

    assert len(results) == 4
    found_outcomes = {r["outcome"] for r in results}
    assert found_outcomes == set(outcomes)
