"""
Unit tests for workbook package inspection (B01).

All XLSX fixtures are built in memory from scratch using standard library
only — no real client data, no external files.

TDD RED: written before implementation; ImportError expected until
src/migration_intake/imports/contracts.py and workbook.py exist.
"""
from __future__ import annotations

import io
import struct
import zipfile
from xml.etree.ElementTree import Element, SubElement, tostring

import pytest

from migration_intake.imports.contracts import (
    APP_DATA_CAPTURE_V1,
    InspectionOutcome,
    SheetPresence,
    SheetRole,
    WorkbookInspectionResult,
)
from migration_intake.imports.workbook import WorkbookInspector


# ---------------------------------------------------------------------------
# Minimal synthetic XLSX factory helpers
# ---------------------------------------------------------------------------

_ALL_REQUIRED_SHEETS = ["App", "iTAP", "WaveUtil", "Infra", "Database", "TSS", "Provisioning"]


def _build_content_types_xml(
    sheet_names: list[str],
    has_macro: bool = False,
    has_ext_link: bool = False,
) -> bytes:
    root = Element(
        "Types",
        xmlns="http://schemas.openxmlformats.org/package/2006/content-types",
    )
    SubElement(
        root,
        "Default",
        Extension="rels",
        ContentType="application/vnd.openxmlformats-package.relationships+xml",
    )
    SubElement(root, "Default", Extension="xml", ContentType="application/xml")
    ct = (
        "application/vnd.ms-excel.sheet.macroEnabled.main+xml"
        if has_macro
        else "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"
    )
    SubElement(root, "Override", PartName="/xl/workbook.xml", ContentType=ct)
    for i, _ in enumerate(sheet_names, 1):
        SubElement(
            root,
            "Override",
            PartName=f"/xl/worksheets/sheet{i}.xml",
            ContentType=(
                "application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"
            ),
        )
    if has_ext_link:
        SubElement(
            root,
            "Override",
            PartName="/xl/externalLinks/externalLink1.xml",
            ContentType=(
                "application/vnd.openxmlformats-officedocument.spreadsheetml"
                ".externalLink+xml"
            ),
        )
    return tostring(root, encoding="unicode").encode("utf-8")


def _build_workbook_xml(sheet_names: list[str]) -> bytes:
    root = Element(
        "workbook",
        xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main",
    )
    sheets_el = SubElement(root, "sheets")
    for i, name in enumerate(sheet_names, 1):
        # Note: r:id is omitted here to avoid unbound-prefix parse errors;
        # the inspector only uses the 'name' attribute.
        SubElement(sheets_el, "sheet", name=name, sheetId=str(i))
    return tostring(root, encoding="unicode").encode("utf-8")


def _build_worksheet_xml(with_formula: bool = False) -> bytes:
    root = Element(
        "worksheet",
        xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main",
    )
    sheet_data = SubElement(root, "sheetData")
    if with_formula:
        # A cell with a formula that would cause ZeroDivisionError if evaluated
        row = SubElement(sheet_data, "row", r="1")
        cell = SubElement(row, "c", r="A1", t="n")
        SubElement(cell, "f").text = "1/0"
        SubElement(cell, "v").text = "0"   # cached value
    return tostring(root, encoding="unicode").encode("utf-8")


def _build_rels_xml() -> bytes:
    root = Element(
        "Relationships",
        xmlns="http://schemas.openxmlformats.org/package/2006/relationships",
    )
    SubElement(
        root,
        "Relationship",
        Id="rId1",
        Type=(
            "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
            "/officeDocument"
        ),
        Target="xl/workbook.xml",
    )
    return tostring(root, encoding="unicode").encode("utf-8")


def _build_workbook_rels_xml(sheet_names: list[str]) -> bytes:
    root = Element(
        "Relationships",
        xmlns="http://schemas.openxmlformats.org/package/2006/relationships",
    )
    for i, _ in enumerate(sheet_names, 1):
        SubElement(
            root,
            "Relationship",
            Id=f"rId{i}",
            Type=(
                "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
                "/worksheet"
            ),
            Target=f"worksheets/sheet{i}.xml",
        )
    return tostring(root, encoding="unicode").encode("utf-8")


def make_minimal_xlsx(
    sheet_names: list[str] | None = None,
    has_macro: bool = False,
    has_ext_link: bool = False,
    sheet_formula: bool = False,
) -> bytes:
    """Build a minimal valid (or intentionally limited) XLSX as bytes."""
    if sheet_names is None:
        sheet_names = list(_ALL_REQUIRED_SHEETS)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(
            "[Content_Types].xml",
            _build_content_types_xml(sheet_names, has_macro, has_ext_link),
        )
        zf.writestr("_rels/.rels", _build_rels_xml())
        zf.writestr("xl/workbook.xml", _build_workbook_xml(sheet_names))
        zf.writestr("xl/_rels/workbook.xml.rels", _build_workbook_rels_xml(sheet_names))
        for i, _ in enumerate(sheet_names, 1):
            zf.writestr(
                f"xl/worksheets/sheet{i}.xml",
                _build_worksheet_xml(with_formula=(sheet_formula and i == 1)),
            )
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestValidContract:
    """Happy-path: all required sheets present."""

    def test_valid_contract_v1_all_sheets_present(self) -> None:
        """All 7 required sheets → outcome VALID, no errors."""
        xlsx = make_minimal_xlsx()
        result = WorkbookInspector().inspect(io.BytesIO(xlsx))
        assert result.outcome == InspectionOutcome.VALID
        assert result.errors == ()

    def test_outcome_is_valid_for_minimal_complete_workbook(self) -> None:
        """Explicit outcome check for minimal complete workbook."""
        xlsx = make_minimal_xlsx()
        result = WorkbookInspector().inspect(io.BytesIO(xlsx))
        assert result.outcome == InspectionOutcome.VALID

    def test_contract_version_is_v1(self) -> None:
        """Valid workbook exposes contract_version == 'APP_DATA_CAPTURE_V1'."""
        xlsx = make_minimal_xlsx()
        result = WorkbookInspector().inspect(io.BytesIO(xlsx))
        assert result.contract_version == "APP_DATA_CAPTURE_V1"


class TestSheetPresence:
    """Sheet presence and role assignment."""

    def test_missing_required_sheet_returns_invalid(self) -> None:
        """Workbook without the 'App' sheet → INVALID."""
        sheets_without_app = [s for s in _ALL_REQUIRED_SHEETS if s != "App"]
        xlsx = make_minimal_xlsx(sheet_names=sheets_without_app)
        result = WorkbookInspector().inspect(io.BytesIO(xlsx))
        assert result.outcome == InspectionOutcome.INVALID
        # App sheet should be reported as absent
        app_presence = next(
            (p for p in result.sheet_presence if p.canonical_name == "App"), None
        )
        assert app_presence is not None
        assert app_presence.present is False

    def test_duplicate_sheet_name_returns_invalid(self) -> None:
        """Two sheets with the same name → INVALID."""
        # Include the duplicate; remove one legitimate sheet to keep length manageable
        sheets_with_dup = list(_ALL_REQUIRED_SHEETS) + ["App"]
        xlsx = make_minimal_xlsx(sheet_names=sheets_with_dup)
        result = WorkbookInspector().inspect(io.BytesIO(xlsx))
        assert result.outcome == InspectionOutcome.INVALID

    def test_sheet_role_assigned_correctly(self) -> None:
        """App sheet is assigned QUESTIONNAIRE_PROJECTION role."""
        xlsx = make_minimal_xlsx()
        result = WorkbookInspector().inspect(io.BytesIO(xlsx))
        app_presence = next(
            (p for p in result.sheet_presence if p.canonical_name == "App"), None
        )
        assert app_presence is not None
        assert app_presence.role == SheetRole.QUESTIONNAIRE_PROJECTION
        assert app_presence.present is True

    def test_all_required_sheet_roles_mapped(self) -> None:
        """All 7 required sheets have correct roles in sheet_presence."""
        xlsx = make_minimal_xlsx()
        result = WorkbookInspector().inspect(io.BytesIO(xlsx))
        presence_map = {p.canonical_name: p for p in result.sheet_presence}
        assert presence_map["App"].role == SheetRole.QUESTIONNAIRE_PROJECTION
        assert presence_map["iTAP"].role == SheetRole.SOURCE_CAPTURE
        assert presence_map["WaveUtil"].role == SheetRole.REGISTER_DATA
        assert presence_map["Infra"].role == SheetRole.LEGACY_EXTENSION
        assert presence_map["Database"].role == SheetRole.LEGACY_EXTENSION
        assert presence_map["TSS"].role == SheetRole.REGISTER_DATA
        assert presence_map["Provisioning"].role == SheetRole.REFERENCE_DATA

    def test_sheet_count_reflects_actual_sheets(self) -> None:
        """result.sheet_count matches the number of sheets in the workbook."""
        xlsx = make_minimal_xlsx()
        result = WorkbookInspector().inspect(io.BytesIO(xlsx))
        assert result.sheet_count == len(_ALL_REQUIRED_SHEETS)


class TestFormatRejection:
    """File format and signature checks."""

    def test_empty_stream_is_rejected(self) -> None:
        """Empty byte stream → INVALID."""
        result = WorkbookInspector().inspect(io.BytesIO(b""))
        assert result.outcome == InspectionOutcome.INVALID

    def test_non_xlsx_magic_bytes_rejected(self) -> None:
        """Random bytes with no ZIP magic → INVALID."""
        result = WorkbookInspector().inspect(io.BytesIO(b"\xFF\xFE\x00\x01" * 100))
        assert result.outcome == InspectionOutcome.INVALID

    def test_xlsm_extension_rejected(self) -> None:
        """Filename with .xlsm extension → INVALID (macro-enabled extension)."""
        xlsx = make_minimal_xlsx()
        result = WorkbookInspector().inspect(io.BytesIO(xlsx), filename="report.xlsm")
        assert result.outcome == InspectionOutcome.INVALID

    def test_xlsx_extension_accepted(self) -> None:
        """Filename with .xlsx extension is accepted (valid extension)."""
        xlsx = make_minimal_xlsx()
        result = WorkbookInspector().inspect(io.BytesIO(xlsx), filename="report.xlsx")
        assert result.outcome == InspectionOutcome.VALID

    def test_xlsb_extension_rejected(self) -> None:
        """Binary XLSX (.xlsb) extension is rejected."""
        xlsx = make_minimal_xlsx()
        result = WorkbookInspector().inspect(io.BytesIO(xlsx), filename="report.xlsb")
        assert result.outcome == InspectionOutcome.INVALID


class TestSizeLimits:
    """Compressed and expanded size limit enforcement."""

    def test_compressed_size_limit_enforced(self) -> None:
        """Stream larger than max_compressed_bytes → INVALID."""
        xlsx = make_minimal_xlsx()
        # Set limit smaller than any valid XLSX
        inspector = WorkbookInspector(max_compressed_bytes=10)
        result = inspector.inspect(io.BytesIO(xlsx))
        assert result.outcome == InspectionOutcome.INVALID
        assert result.compressed_bytes > 10


class TestSecurityFeatures:
    """Security-specific behaviour."""

    def test_zip_traversal_entry_rejected(self) -> None:
        """ZIP with a '../evil.xml' entry → INVALID."""
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            # Use ZipInfo to bypass any path sanitisation on write
            info = zipfile.ZipInfo("../evil.xml")
            zf.writestr(info, "malicious content")
        result = WorkbookInspector().inspect(io.BytesIO(buf.getvalue()))
        assert result.outcome == InspectionOutcome.INVALID

    def test_macro_content_type_detected(self) -> None:
        """Macro-enabled content type in [Content_Types].xml → has_macros=True, INVALID."""
        xlsx = make_minimal_xlsx(has_macro=True)
        result = WorkbookInspector().inspect(io.BytesIO(xlsx))
        assert result.has_macros is True
        assert result.outcome == InspectionOutcome.INVALID

    def test_external_link_detected(self) -> None:
        """External link content type → has_external_links=True and at least one warning."""
        xlsx = make_minimal_xlsx(has_ext_link=True)
        result = WorkbookInspector().inspect(io.BytesIO(xlsx))
        assert result.has_external_links is True
        assert len(result.warnings) > 0


class TestFormulaHandling:
    """Formula cells must never be executed."""

    def test_inspection_does_not_execute_formulas(self) -> None:
        """
        Workbook with a ZeroDivisionError formula (1/0) inspects without
        raising any exception — proof that formulas are never evaluated.
        """
        xlsx = make_minimal_xlsx(sheet_formula=True)
        # Must not raise; the formula must be ignored / treated as raw XML
        result = WorkbookInspector().inspect(io.BytesIO(xlsx))
        # The workbook is otherwise valid; formula presence doesn't change outcome
        assert result.outcome == InspectionOutcome.VALID
        assert result.errors == ()
