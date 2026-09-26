"""
ImportRepository — P05b (Import Runs, Sheet Results, Findings Persistence).

Design rules (Architecture sections 31, 38):
- Returns plain dicts, never ORM entity instances.
- Session is owned by the UnitOfWork; no independent commits here.
- Methods accept domain-typed arguments (str UUIDs, datetime, int, str).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from migration_intake.persistence.models_imports import (
    ImportFinding,
    ImportRun,
    ImportSheetResult,
)


class ImportRepository:
    """
    Persistence adapter for import run, sheet result, and finding records.

    All methods operate on the session provided at construction time.
    The owning UnitOfWork controls when/whether to commit.
    """

    def __init__(self, session: Session) -> None:
        self._session = session

    # ------------------------------------------------------------------
    # import_runs — write operations
    # ------------------------------------------------------------------

    def add_run(
        self,
        *,
        run_id: str,
        application_id: str,
        intake_id: str | None,
        evidence_item_id: str | None,
        contract_name: str,
        parser_version: str,
        created_at: datetime,
        created_by_id: str,
    ) -> dict[str, Any]:
        """
        Insert an import_runs row with state=PENDING.

        Returns a plain dict of the inserted row.  The caller must commit
        the owning transaction to persist the change.
        """
        run = ImportRun(
            id=run_id,
            application_id=application_id,
            intake_id=intake_id,
            evidence_item_id=evidence_item_id,
            contract_name=contract_name,
            parser_version=parser_version,
            state="PENDING",
            total_sheets=None,
            total_candidates=0,
            total_findings=0,
            started_at=None,
            completed_at=None,
            created_at=created_at,
            created_by_id=created_by_id,
        )
        self._session.add(run)
        self._session.flush()
        return self._run_to_dict(run)

    def update_run_state(
        self,
        run_id: str,
        new_state: str,
        total_sheets: int | None = None,
        total_candidates: int | None = None,
        total_findings: int | None = None,
        completed_at: datetime | None = None,
        identity_decision: str | None = None,
        source_identity_raw: str | None = None,
        source_identity_normalized: str | None = None,
        identity_detail: Any = None,
    ) -> bool:
        """
        Update run state and optional summary fields.

        Only non-None keyword arguments are applied to the row.

        Returns:
            ``True`` if exactly one row was updated; ``False`` if not found.
        """
        values: dict[str, Any] = {"state": new_state}
        if total_sheets is not None:
            values["total_sheets"] = total_sheets
        if total_candidates is not None:
            values["total_candidates"] = total_candidates
        if total_findings is not None:
            values["total_findings"] = total_findings
        if completed_at is not None:
            values["completed_at"] = completed_at
        if identity_decision is not None:
            values["identity_decision"] = identity_decision
        if source_identity_raw is not None:
            values["source_identity_raw"] = source_identity_raw
        if source_identity_normalized is not None:
            values["source_identity_normalized"] = source_identity_normalized
        if identity_detail is not None:
            values["identity_detail"] = identity_detail

        stmt = (
            update(ImportRun)
            .where(ImportRun.id == run_id)
            .values(**values)
            .execution_options(synchronize_session=False)
        )
        result = self._session.execute(stmt)
        return result.rowcount == 1

    # ------------------------------------------------------------------
    # import_runs — read operations
    # ------------------------------------------------------------------

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        """Return the import_runs row as a plain dict, or None if not found."""
        stmt = select(ImportRun).where(ImportRun.id == run_id)
        run = self._session.execute(stmt).scalar_one_or_none()
        if run is None:
            return None
        return self._run_to_dict(run)

    def list_runs_for_intake(self, intake_id: str) -> list[dict[str, Any]]:
        """
        Return all runs for an intake, ordered by created_at descending.

        Since PortableUTC stores ISO 8601 strings, lexicographic descending
        ordering correctly reflects chronological descending order.
        """
        stmt = (
            select(ImportRun)
            .where(ImportRun.intake_id == intake_id)
            .order_by(ImportRun.created_at.desc())
        )
        rows = self._session.execute(stmt).scalars().all()
        return [self._run_to_dict(r) for r in rows]

    def list_runs_for_evidence(self, evidence_item_id: str) -> list[dict[str, Any]]:
        """
        Return all runs for an evidence item, ordered by created_at descending.
        """
        stmt = (
            select(ImportRun)
            .where(ImportRun.evidence_item_id == evidence_item_id)
            .order_by(ImportRun.created_at.desc())
        )
        rows = self._session.execute(stmt).scalars().all()
        return [self._run_to_dict(r) for r in rows]

    # ------------------------------------------------------------------
    # import_sheet_results — write operations
    # ------------------------------------------------------------------

    def add_sheet_result(
        self,
        *,
        result_id: str,
        run_id: str,
        sheet_name: str,
        outcome: str,
        candidate_count: int = 0,
        finding_count: int = 0,
        blank_rows_skipped: int = 0,
        error_message: str | None = None,
    ) -> dict[str, Any]:
        """
        Insert an import_sheet_results row.

        Returns a plain dict of the inserted row.
        """
        sheet_result = ImportSheetResult(
            id=result_id,
            run_id=run_id,
            sheet_name=sheet_name,
            outcome=outcome,
            candidate_count=candidate_count,
            finding_count=finding_count,
            blank_rows_skipped=blank_rows_skipped,
            error_message=error_message,
        )
        self._session.add(sheet_result)
        self._session.flush()
        return self._sheet_result_to_dict(sheet_result)

    # ------------------------------------------------------------------
    # import_sheet_results — read operations
    # ------------------------------------------------------------------

    def list_sheet_results_for_run(self, run_id: str) -> list[dict[str, Any]]:
        """Return all sheet results for a run."""
        stmt = select(ImportSheetResult).where(ImportSheetResult.run_id == run_id)
        rows = self._session.execute(stmt).scalars().all()
        return [self._sheet_result_to_dict(r) for r in rows]

    # ------------------------------------------------------------------
    # import_findings — write operations
    # ------------------------------------------------------------------

    def add_finding(
        self,
        *,
        finding_id: str,
        run_id: str,
        sheet_name: str,
        finding_type: str,
        severity: str = "WARNING",
        source_locator: str | None = None,
        detail: Any = None,
    ) -> dict[str, Any]:
        """
        Insert an import_findings row.

        Returns a plain dict of the inserted row.
        """
        finding = ImportFinding(
            id=finding_id,
            run_id=run_id,
            sheet_name=sheet_name,
            finding_type=finding_type,
            severity=severity,
            source_locator=source_locator,
            detail=detail,
        )
        self._session.add(finding)
        self._session.flush()
        return self._finding_to_dict(finding)

    # ------------------------------------------------------------------
    # import_findings — read operations
    # ------------------------------------------------------------------

    def list_findings_for_run(self, run_id: str) -> list[dict[str, Any]]:
        """Return all findings for a run."""
        stmt = select(ImportFinding).where(ImportFinding.run_id == run_id)
        rows = self._session.execute(stmt).scalars().all()
        return [self._finding_to_dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _run_to_dict(run: ImportRun) -> dict[str, Any]:
        """Convert an ImportRun ORM row to a plain dict."""
        return {
            "id": str(run.id),
            "application_id": str(run.application_id),
            "intake_id": str(run.intake_id) if run.intake_id is not None else None,
            "evidence_item_id": (
                str(run.evidence_item_id) if run.evidence_item_id is not None else None
            ),
            "contract_name": run.contract_name,
            "parser_version": run.parser_version,
            "state": run.state,
            "total_sheets": run.total_sheets,
            "total_candidates": run.total_candidates,
            "total_findings": run.total_findings,
            "identity_decision": run.identity_decision,
            "source_identity_raw": run.source_identity_raw,
            "source_identity_normalized": run.source_identity_normalized,
            "identity_detail": run.identity_detail,
            "started_at": run.started_at,
            "completed_at": run.completed_at,
            "created_at": run.created_at,
            "created_by_id": str(run.created_by_id),
        }

    @staticmethod
    def _sheet_result_to_dict(sheet_result: ImportSheetResult) -> dict[str, Any]:
        """Convert an ImportSheetResult ORM row to a plain dict."""
        return {
            "id": str(sheet_result.id),
            "run_id": str(sheet_result.run_id),
            "sheet_name": sheet_result.sheet_name,
            "outcome": sheet_result.outcome,
            "candidate_count": sheet_result.candidate_count,
            "finding_count": sheet_result.finding_count,
            "blank_rows_skipped": sheet_result.blank_rows_skipped,
            "error_message": sheet_result.error_message,
        }

    @staticmethod
    def _finding_to_dict(finding: ImportFinding) -> dict[str, Any]:
        """Convert an ImportFinding ORM row to a plain dict."""
        return {
            "id": str(finding.id),
            "run_id": str(finding.run_id),
            "sheet_name": finding.sheet_name,
            "finding_type": finding.finding_type,
            "severity": finding.severity,
            "source_locator": finding.source_locator,
            "detail": finding.detail,
        }
