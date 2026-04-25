"""
Compliance Excel Export Service
===============================

Generates audit-ready, multi-sheet .xlsx workbooks for compliance data
(Synapse drift, AKS pod drift, compliance scores, checksum runs).

Features:
  - AT&T Proprietary branding header on every sheet
  - Per-column auto-width, freeze panes, auto-filter
  - Conditional formatting (red CRITICAL/FAIL, amber HIGH, gold MEDIUM, green PASS)
  - Filter support via ExcelExportRequest (date range, severity, status, module, system)
  - Returns (BytesIO, ExportMetadata) for streaming via FastAPI StreamingResponse
"""

from __future__ import annotations

import io
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

import structlog
from openpyxl import Workbook
from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.database import (
    AKSPodDrift,
    ChecksumResult,
    ChecksumRun,
    ComplianceScore,
    SynapsePipelineDrift,
)
from app.schemas.compliance import (
    ExcelExportRequest,
    ExportMetadata,
    ModuleType,
)

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Style constants
# ---------------------------------------------------------------------------

_ATT_BLUE = "00066297"
_HEADER_FILL = PatternFill(start_color=_ATT_BLUE, end_color=_ATT_BLUE, fill_type="solid")
_HEADER_FONT = Font(name="Calibri", bold=True, color="FFFFFF", size=11)
_TITLE_FONT = Font(name="Calibri", bold=True, color=_ATT_BLUE, size=14)
_SUBTITLE_FONT = Font(name="Calibri", italic=True, color="666666", size=10)
_DATA_FONT = Font(name="Calibri", size=10)
_THIN_BORDER = Border(
    left=Side(style="thin", color="D9D9D9"),
    right=Side(style="thin", color="D9D9D9"),
    top=Side(style="thin", color="D9D9D9"),
    bottom=Side(style="thin", color="D9D9D9"),
)

# Conditional fills
_CRITICAL_FILL = PatternFill(start_color="FFC00000", end_color="FFC00000", fill_type="solid")
_CRITICAL_FONT = Font(name="Calibri", bold=True, color="FFFFFF", size=10)
_HIGH_FILL = PatternFill(start_color="FFFF6600", end_color="FFFF6600", fill_type="solid")
_HIGH_FONT = Font(name="Calibri", bold=True, color="FFFFFF", size=10)
_MEDIUM_FILL = PatternFill(start_color="FFFFC000", end_color="FFFFC000", fill_type="solid")
_MEDIUM_FONT = Font(name="Calibri", bold=True, color="000000", size=10)
_LOW_FILL = PatternFill(start_color="FFA9D18E", end_color="FFA9D18E", fill_type="solid")
_PASS_FILL = PatternFill(start_color="FF70AD47", end_color="FF70AD47", fill_type="solid")
_PASS_FONT = Font(name="Calibri", bold=True, color="FFFFFF", size=10)
_FAIL_FILL = PatternFill(start_color="FFC00000", end_color="FFC00000", fill_type="solid")

_SEVERITY_STYLES: dict[str, tuple[PatternFill, Font]] = {
    "critical": (_CRITICAL_FILL, _CRITICAL_FONT),
    "high": (_HIGH_FILL, _HIGH_FONT),
    "medium": (_MEDIUM_FILL, _MEDIUM_FONT),
    "low": (_LOW_FILL, _DATA_FONT),
}

_RESULT_STYLES: dict[str, tuple[PatternFill, Font]] = {
    "PASS": (_PASS_FILL, _PASS_FONT),
    "FAIL": (_FAIL_FILL, _CRITICAL_FONT),
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_branding_header(ws: Worksheet, title: str, generated_at: datetime) -> int:
    """Write AT&T Proprietary branding rows.  Returns the next writable row."""
    ws.merge_cells("A1:H1")
    cell = ws.cell(row=1, column=1, value="AT&T Proprietary (Restricted)")
    cell.font = _TITLE_FONT
    cell.alignment = Alignment(horizontal="left", vertical="center")

    ws.merge_cells("A2:H2")
    ws.cell(
        row=2,
        column=1,
        value=f"{title}  |  Generated: {generated_at:%Y-%m-%d %H:%M:%S UTC}",
    ).font = _SUBTITLE_FONT

    ws.row_dimensions[1].height = 28
    ws.row_dimensions[2].height = 18
    return 4  # leave a blank row (row 3) before data


def _write_column_headers(ws: Worksheet, row: int, headers: list[str]) -> None:
    """Write styled column header row."""
    for col_idx, header in enumerate(headers, start=1):
        cell = ws.cell(row=row, column=col_idx, value=header)
        cell.font = _HEADER_FONT
        cell.fill = _HEADER_FILL
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cell.border = _THIN_BORDER
    ws.row_dimensions[row].height = 24


def _write_data_cell(
    ws: Worksheet,
    row: int,
    col: int,
    value: Any,
    *,
    conditional_key: str | None = None,
    style_map: dict[str, tuple[PatternFill, Font]] | None = None,
) -> None:
    """Write a single data cell with optional conditional formatting."""
    if isinstance(value, str):
        value = ILLEGAL_CHARACTERS_RE.sub("", value)

    cell = ws.cell(row=row, column=col, value=value)
    cell.font = _DATA_FONT
    cell.border = _THIN_BORDER
    cell.alignment = Alignment(vertical="center", wrap_text=False)

    if conditional_key and style_map:
        styles = style_map.get(str(conditional_key).lower() if conditional_key else "")
        if styles:
            cell.fill, cell.font = styles


def _auto_fit_columns(ws: Worksheet, header_row: int, data_end_row: int) -> None:
    """Resize columns based on content width (capped at 50 chars)."""
    for col_cells in ws.iter_cols(min_row=header_row, max_row=data_end_row):
        max_length = 0
        col_letter = get_column_letter(col_cells[0].column)
        for cell in col_cells:
            try:
                cell_len = len(str(cell.value)) if cell.value is not None else 0
                max_length = max(max_length, cell_len)
            except Exception:  # noqa: BLE001
                pass
        adjusted = min(max_length + 4, 50)
        ws.column_dimensions[col_letter].width = max(adjusted, 10)


def _apply_freeze_and_filter(ws: Worksheet, header_row: int, last_col: int) -> None:
    """Freeze panes below header and enable auto-filter."""
    ws.freeze_panes = ws.cell(row=header_row + 1, column=1)
    ws.auto_filter.ref = f"A{header_row}:{get_column_letter(last_col)}{ws.max_row}"


def _fmt_dt(dt: datetime | str | None) -> str:
    """Format a datetime for the spreadsheet, returning '' for None.
    Accepts datetime objects or ISO-format strings (from DB varchar columns).
    """
    if dt is None:
        return ""
    if isinstance(dt, str):
        return dt  # already a formatted string from the DB
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def _fmt_date(dt: datetime | str | None) -> str:
    """Format date-only. Accepts datetime objects or date strings."""
    if dt is None:
        return ""
    if isinstance(dt, str):
        return dt
    return dt.strftime("%Y-%m-%d")


# ---------------------------------------------------------------------------
# Query helpers
# ---------------------------------------------------------------------------


async def _fetch_synapse_drifts(
    db: AsyncSession,
    request: ExcelExportRequest,
) -> Sequence[SynapsePipelineDrift]:
    """Query SynapsePipelineDrift with request filters."""
    stmt = select(SynapsePipelineDrift).order_by(SynapsePipelineDrift.detection_date.desc())
    if request.date_from:
        stmt = stmt.where(SynapsePipelineDrift.detection_date >= request.date_from)
    if request.date_to:
        stmt = stmt.where(SynapsePipelineDrift.detection_date <= request.date_to)
    if request.status_filter:
        stmt = stmt.where(SynapsePipelineDrift.compliance_status.in_(request.status_filter))
    result = await db.execute(stmt)
    return result.scalars().all()


async def _fetch_aks_drifts(
    db: AsyncSession,
    request: ExcelExportRequest,
) -> Sequence[AKSPodDrift]:
    """Query AKSPodDrift with request filters."""
    stmt = select(AKSPodDrift).order_by(AKSPodDrift.detection_date.desc())
    if request.date_from:
        stmt = stmt.where(AKSPodDrift.detection_date >= request.date_from)
    if request.date_to:
        stmt = stmt.where(AKSPodDrift.detection_date <= request.date_to)
    if request.severity_filter:
        stmt = stmt.where(AKSPodDrift.severity.in_(request.severity_filter))
    if request.status_filter:
        stmt = stmt.where(AKSPodDrift.compliance_status.in_(request.status_filter))
    result = await db.execute(stmt)
    return result.scalars().all()


async def _fetch_compliance_scores(
    db: AsyncSession,
    request: ExcelExportRequest,
) -> Sequence[ComplianceScore]:
    """Query ComplianceScore with request filters."""
    stmt = select(ComplianceScore).order_by(ComplianceScore.score_date.desc())
    if request.date_from:
        stmt = stmt.where(ComplianceScore.score_date >= request.date_from)
    if request.date_to:
        stmt = stmt.where(ComplianceScore.score_date <= request.date_to)
    result = await db.execute(stmt)
    return result.scalars().all()


async def _fetch_checksum_runs(
    db: AsyncSession,
    request: ExcelExportRequest,
) -> Sequence[ChecksumRun]:
    """Query ChecksumRun (with results) matching request filters."""
    stmt = select(ChecksumRun).options(selectinload(ChecksumRun.results)).order_by(ChecksumRun.created_at.desc())
    if request.module_type:
        stmt = stmt.where(ChecksumRun.module_type == request.module_type.value)
    if request.system:
        stmt = stmt.where(ChecksumRun.system == request.system.value)
    if request.date_from:
        stmt = stmt.where(ChecksumRun.created_at >= request.date_from)
    if request.date_to:
        stmt = stmt.where(ChecksumRun.created_at <= request.date_to)
    result = await db.execute(stmt)
    return result.scalars().unique().all()


# ---------------------------------------------------------------------------
# Sheet writers
# ---------------------------------------------------------------------------


def _write_synapse_sheet(
    wb: Workbook,
    drifts: Sequence[SynapsePipelineDrift],
    generated_at: datetime,
) -> int:
    """Write 'Synapse Drift' sheet.  Returns row count written."""
    ws = wb.create_sheet("Synapse Drift")
    data_start = _write_branding_header(ws, "Synapse Pipeline Drift Report", generated_at)

    headers = [
        "#",
        "Detection Date",
        "Workspace",
        "Pipeline Name",
        "Drift Type",
        "Previous Checksum",
        "Current Checksum",
        "Status",
        "Acknowledged",
        "Acknowledged By",
        "Acknowledged At",
    ]
    _write_column_headers(ws, data_start, headers)

    for idx, d in enumerate(drifts, start=1):
        row = data_start + idx
        _write_data_cell(ws, row, 1, idx)
        _write_data_cell(ws, row, 2, _fmt_dt(d.detection_date))
        _write_data_cell(ws, row, 3, d.workspace_name)
        _write_data_cell(ws, row, 4, d.pipeline_name)
        _write_data_cell(
            ws,
            row,
            5,
            d.drift_type,
            conditional_key=d.drift_type,
            style_map={
                "modified": (_MEDIUM_FILL, _MEDIUM_FONT),
                "deleted": (_CRITICAL_FILL, _CRITICAL_FONT),
            },
        )
        _write_data_cell(ws, row, 6, d.previous_checksum or "")
        _write_data_cell(ws, row, 7, d.current_checksum or "")
        _write_data_cell(
            ws,
            row,
            8,
            d.compliance_status,
            conditional_key=d.compliance_status,
            style_map={
                "pending_review": (_MEDIUM_FILL, _MEDIUM_FONT),
                "resolved": (_PASS_FILL, _PASS_FONT),
                "waived": (_LOW_FILL, _DATA_FONT),
            },
        )
        _write_data_cell(ws, row, 9, "Yes" if d.acknowledged else "No")
        _write_data_cell(ws, row, 10, d.acknowledged_by or "")
        _write_data_cell(ws, row, 11, _fmt_dt(d.acknowledged_at))

    last_row = data_start + len(drifts)
    _auto_fit_columns(ws, data_start, last_row)
    _apply_freeze_and_filter(ws, data_start, len(headers))
    return len(drifts)


def _write_aks_sheet(
    wb: Workbook,
    drifts: Sequence[AKSPodDrift],
    generated_at: datetime,
) -> int:
    """Write 'AKS Pod Drift' sheet.  Returns row count written."""
    ws = wb.create_sheet("AKS Pod Drift")
    data_start = _write_branding_header(ws, "AKS Pod Drift Report", generated_at)

    headers = [
        "#",
        "Detection Date",
        "Cluster",
        "Namespace",
        "Pod Name",
        "Owner",
        "Drift Type",
        "Drift Category",
        "Severity",
        "Status",
        "Acknowledged",
        "Acknowledged By",
        "Acknowledged At",
    ]
    _write_column_headers(ws, data_start, headers)

    for idx, d in enumerate(drifts, start=1):
        row = data_start + idx
        _write_data_cell(ws, row, 1, idx)
        _write_data_cell(ws, row, 2, _fmt_dt(d.detection_date))
        _write_data_cell(ws, row, 3, d.cluster_name)
        _write_data_cell(ws, row, 4, d.namespace)
        _write_data_cell(ws, row, 5, d.pod_name)
        owner = f"{d.owner_kind}/{d.owner_name}" if d.owner_kind else ""
        _write_data_cell(ws, row, 6, owner)
        _write_data_cell(ws, row, 7, d.drift_type)
        _write_data_cell(ws, row, 8, d.drift_category)
        _write_data_cell(
            ws,
            row,
            9,
            d.severity,
            conditional_key=d.severity,
            style_map=_SEVERITY_STYLES,
        )
        _write_data_cell(
            ws,
            row,
            10,
            d.compliance_status,
            conditional_key=d.compliance_status,
            style_map={
                "pending_review": (_MEDIUM_FILL, _MEDIUM_FONT),
                "resolved": (_PASS_FILL, _PASS_FONT),
                "waived": (_LOW_FILL, _DATA_FONT),
            },
        )
        _write_data_cell(ws, row, 11, "Yes" if d.acknowledged else "No")
        _write_data_cell(ws, row, 12, d.acknowledged_by or "")
        _write_data_cell(ws, row, 13, _fmt_dt(d.acknowledged_at))

    last_row = data_start + len(drifts)
    _auto_fit_columns(ws, data_start, last_row)
    _apply_freeze_and_filter(ws, data_start, len(headers))
    return len(drifts)


def _grade_from_score(score: float | None) -> str:
    """Map 0-100 score to letter grade."""
    if score is None:
        return "N/A"
    if score >= 90:
        return "A"
    if score >= 80:
        return "B"
    if score >= 70:
        return "C"
    if score >= 60:
        return "D"
    return "F"


def _write_scores_sheet(
    wb: Workbook,
    scores: Sequence[ComplianceScore],
    generated_at: datetime,
) -> int:
    """Write 'Compliance Scores' sheet.  Returns row count written."""
    ws = wb.create_sheet("Compliance Scores")
    data_start = _write_branding_header(ws, "Compliance Scores Report", generated_at)

    headers = [
        "#",
        "Score Date",
        "Resource Name",
        "Resource Type",
        "Overall Score",
        "Grade",
        "Image Score",
        "Config Score",
        "Drift Score",
        "Total Resources",
        "Compliant",
        "Drifted",
        "Critical Issues",
        "High Issues",
        "Medium Issues",
        "Low Issues",
    ]
    _write_column_headers(ws, data_start, headers)

    for idx, s in enumerate(scores, start=1):
        row = data_start + idx
        grade = _grade_from_score(s.overall_score)
        _write_data_cell(ws, row, 1, idx)
        _write_data_cell(ws, row, 2, _fmt_date(s.score_date))
        _write_data_cell(ws, row, 3, s.resource_name)
        _write_data_cell(ws, row, 4, s.resource_type)
        _write_data_cell(
            ws,
            row,
            5,
            round(s.overall_score, 1) if s.overall_score is not None else "",
        )
        _write_data_cell(
            ws,
            row,
            6,
            grade,
            conditional_key=grade.lower(),
            style_map={
                "a": (_PASS_FILL, _PASS_FONT),
                "b": (_LOW_FILL, _DATA_FONT),
                "c": (_MEDIUM_FILL, _MEDIUM_FONT),
                "d": (_HIGH_FILL, _HIGH_FONT),
                "f": (_CRITICAL_FILL, _CRITICAL_FONT),
            },
        )
        _write_data_cell(
            ws,
            row,
            7,
            round(s.image_compliance_score, 1) if s.image_compliance_score else "",
        )
        _write_data_cell(
            ws,
            row,
            8,
            round(s.config_compliance_score, 1) if s.config_compliance_score else "",
        )
        _write_data_cell(ws, row, 9, round(s.drift_score, 1) if s.drift_score else "")
        _write_data_cell(ws, row, 10, s.total_resources or 0)
        _write_data_cell(ws, row, 11, s.compliant_resources or 0)
        _write_data_cell(ws, row, 12, s.drifted_resources or 0)
        _write_data_cell(
            ws,
            row,
            13,
            s.critical_issues or 0,
            conditional_key="critical" if (s.critical_issues or 0) > 0 else None,
            style_map=_SEVERITY_STYLES,
        )
        _write_data_cell(
            ws,
            row,
            14,
            s.high_issues or 0,
            conditional_key="high" if (s.high_issues or 0) > 0 else None,
            style_map=_SEVERITY_STYLES,
        )
        _write_data_cell(ws, row, 15, s.medium_issues or 0)
        _write_data_cell(ws, row, 16, s.low_issues or 0)

    last_row = data_start + len(scores)
    _auto_fit_columns(ws, data_start, last_row)
    _apply_freeze_and_filter(ws, data_start, len(headers))
    return len(scores)


def _write_checksum_runs_sheet(
    wb: Workbook,
    runs: Sequence[ChecksumRun],
    generated_at: datetime,
) -> int:
    """Write 'Checksum Runs' sheet with per-run summary rows
    and an optional detail sub-table for each run's results."""
    ws = wb.create_sheet("Checksum Runs")
    data_start = _write_branding_header(ws, "Checksum Verification Runs", generated_at)

    # -- Summary headers
    summary_headers = [
        "#",
        "Run Date",
        "Run ID",
        "Module",
        "System",
        "Workspace / Cluster",
        "Total Pipelines",
        "Passed",
        "Failed",
        "Status",
    ]
    _write_column_headers(ws, data_start, summary_headers)
    total_rows = 0
    current_row = data_start + 1

    for idx, run in enumerate(runs, start=1):
        _write_data_cell(ws, current_row, 1, idx)
        _write_data_cell(ws, current_row, 2, _fmt_dt(run.created_at))
        _write_data_cell(ws, current_row, 3, run.run_id)
        _write_data_cell(ws, current_row, 4, run.module_type or "")
        _write_data_cell(ws, current_row, 5, run.system or "")
        _write_data_cell(ws, current_row, 6, run.workspace_name or "")
        _write_data_cell(ws, current_row, 7, run.total_pipelines or 0)
        _write_data_cell(ws, current_row, 8, run.passed or 0)
        _write_data_cell(
            ws,
            current_row,
            9,
            run.failed or 0,
            conditional_key="critical" if (run.failed or 0) > 0 else None,
            style_map=_SEVERITY_STYLES,
        )
        _write_data_cell(
            ws,
            current_row,
            10,
            run.status or "",
            conditional_key=run.status,
            style_map={
                "completed": (_PASS_FILL, _PASS_FONT),
                "failed": (_FAIL_FILL, _CRITICAL_FONT),
                "timeout": (_MEDIUM_FILL, _MEDIUM_FONT),
                "running": (_LOW_FILL, _DATA_FONT),
            },
        )
        total_rows += 1
        current_row += 1

        # Write individual results if present
        results: list[ChecksumResult] = sorted(run.results or [], key=lambda r: r.slno or 0)
        if results:
            detail_headers = [
                "",
                "Sl.No",
                "Pipeline Name",
                "Yesterday Hash",
                "Present Hash",
                "Last Published",
                "Result",
            ]
            _write_column_headers(ws, current_row, detail_headers)
            current_row += 1

            for res in results:
                _write_data_cell(ws, current_row, 1, "")
                _write_data_cell(ws, current_row, 2, res.slno)
                _write_data_cell(ws, current_row, 3, res.pipeline_name or "")
                _write_data_cell(ws, current_row, 4, res.yesterday_hash or "")
                _write_data_cell(ws, current_row, 5, res.present_hash or "")
                _write_data_cell(ws, current_row, 6, _fmt_dt(res.last_published_date))
                _write_data_cell(
                    ws,
                    current_row,
                    7,
                    res.result or "",
                    conditional_key=res.result,
                    style_map=_RESULT_STYLES,
                )
                total_rows += 1
                current_row += 1

            # Blank separator row between runs
            current_row += 1

    _auto_fit_columns(ws, data_start, current_row)
    _apply_freeze_and_filter(ws, data_start, len(summary_headers))
    return total_rows


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


class ComplianceExcelService:
    """Stateless service producing compliance .xlsx exports."""

    @staticmethod
    async def generate_export(
        db: AsyncSession,
        request: ExcelExportRequest,
    ) -> tuple[io.BytesIO, ExportMetadata]:
        """Build a multi-sheet workbook filtered by *request* and return it
        as an in-memory buffer alongside export metadata.

        Sheets included depend on ``request.module_type``:
          - ``synapse``  → Synapse Drift + Scores + Checksum Runs
          - ``aks``      → AKS Pod Drift + Scores + Checksum Runs
          - ``None``     → All sheets

        Pass ``include_scores=False`` / ``include_checksum_runs=False``
        to omit those sheets.
        """
        generated_at = datetime.now(UTC)
        wb = Workbook()
        # Remove the default sheet created by openpyxl
        wb.remove(wb.active)  # type: ignore[arg-type]

        total_rows = 0
        include_synapse = request.module_type in (None, ModuleType.SYNAPSE)
        include_aks = request.module_type in (None, ModuleType.AKS)

        # -- Synapse Drift sheet
        if include_synapse:
            logger.info(
                "excel_export.synapse_drift",
                date_from=request.date_from,
                date_to=request.date_to,
            )
            synapse_drifts = await _fetch_synapse_drifts(db, request)
            total_rows += _write_synapse_sheet(wb, synapse_drifts, generated_at)

        # -- AKS Pod Drift sheet
        if include_aks:
            logger.info(
                "excel_export.aks_drift",
                date_from=request.date_from,
                date_to=request.date_to,
            )
            aks_drifts = await _fetch_aks_drifts(db, request)
            total_rows += _write_aks_sheet(wb, aks_drifts, generated_at)

        # -- Compliance Scores sheet
        if request.include_scores:
            logger.info("excel_export.compliance_scores")
            scores = await _fetch_compliance_scores(db, request)
            total_rows += _write_scores_sheet(wb, scores, generated_at)

        # -- Checksum Runs sheet
        if request.include_checksum_runs:
            logger.info("excel_export.checksum_runs")
            runs = await _fetch_checksum_runs(db, request)
            total_rows += _write_checksum_runs_sheet(wb, runs, generated_at)

        # -- Fallback: if all sheets were excluded, add a placeholder
        if len(wb.sheetnames) == 0:
            ws = wb.create_sheet("Info")
            ws.cell(row=1, column=1, value="No data matched the selected filters.")

        # Serialise to BytesIO
        buf = io.BytesIO()
        wb.save(buf)
        buf.seek(0)

        # Build filename
        parts = ["compliance_report"]
        if request.module_type:
            parts.append(request.module_type.value)
        if request.system:
            parts.append(request.system.value)
        parts.append(generated_at.strftime("%Y%m%d_%H%M%S"))
        filename = "_".join(parts) + ".xlsx"

        filters_applied: dict[str, Any] = {}
        if request.module_type:
            filters_applied["module_type"] = request.module_type.value
        if request.system:
            filters_applied["system"] = request.system.value
        if request.date_from:
            filters_applied["date_from"] = request.date_from.isoformat()
        if request.date_to:
            filters_applied["date_to"] = request.date_to.isoformat()
        if request.severity_filter:
            filters_applied["severity"] = request.severity_filter
        if request.status_filter:
            filters_applied["status"] = request.status_filter

        metadata = ExportMetadata(
            filename=filename,
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            total_rows=total_rows,
            file_size_bytes=buf.getbuffer().nbytes,
            sheet_names=list(wb.sheetnames),
            generated_at=generated_at,
            filters_applied=filters_applied,
        )

        logger.info(
            "excel_export.complete",
            filename=filename,
            total_rows=total_rows,
            sheets=wb.sheetnames,
        )
        return buf, metadata
