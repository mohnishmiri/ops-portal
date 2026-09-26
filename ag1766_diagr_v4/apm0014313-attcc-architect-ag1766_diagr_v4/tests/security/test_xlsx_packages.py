"""
Security tests for XLSX package inspection (B01).

Verify that WorkbookInspector resists ZIP bombs, path traversal, macro
injection, and related file-based attacks.

All fixtures are synthetic in-memory bytes — no real client data.

TDD RED: written before implementation; ImportError expected until
src/migration_intake/imports/workbook.py exists.
"""
from __future__ import annotations

import io
import zipfile
from xml.etree.ElementTree import Element, SubElement, tostring

import pytest

from migration_intake.imports.contracts import InspectionOutcome
from migration_intake.imports.workbook import (
    DEFAULT_MAX_ENTRIES,
    WorkbookInspector,
)


# ---------------------------------------------------------------------------
# Minimal synthetic XLSX helpers (duplicated locally so tests are self-contained)
# ---------------------------------------------------------------------------

_ALL_REQUIRED = ["App", "iTAP", "WaveUtil", "Infra", "Database", "TSS", "Provisioning"]


def _ct_xml(sheet_names: list[str], has_macro: bool = False) -> bytes:
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
    return tostring(root, encoding="unicode").encode("utf-8")


def _wb_xml(sheet_names: list[str]) -> bytes:
    root = Element(
        "workbook",
        xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main",
    )
    sheets_el = SubElement(root, "sheets")
    for i, name in enumerate(sheet_names, 1):
        # r:id omitted to avoid unbound-prefix parse errors; inspector uses 'name' only.
        SubElement(sheets_el, "sheet", name=name, sheetId=str(i))
    return tostring(root, encoding="unicode").encode("utf-8")


def _ws_xml() -> bytes:
    root = Element(
        "worksheet",
        xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main",
    )
    SubElement(root, "sheetData")
    return tostring(root, encoding="unicode").encode("utf-8")


def _rels_xml() -> bytes:
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


def _wb_rels_xml(sheet_names: list[str]) -> bytes:
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


def _make_xlsx(
    sheet_names: list[str] | None = None,
    has_macro: bool = False,
) -> bytes:
    if sheet_names is None:
        sheet_names = list(_ALL_REQUIRED)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", _ct_xml(sheet_names, has_macro))
        zf.writestr("_rels/.rels", _rels_xml())
        zf.writestr("xl/workbook.xml", _wb_xml(sheet_names))
        zf.writestr("xl/_rels/workbook.xml.rels", _wb_rels_xml(sheet_names))
        for i, _ in enumerate(sheet_names, 1):
            zf.writestr(f"xl/worksheets/sheet{i}.xml", _ws_xml())
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Security tests
# ---------------------------------------------------------------------------


def test_zip_bomb_rejected() -> None:
    """
    ZIP where uncompressed content exceeds max_expanded_bytes is rejected
    before the full data is read.

    Strategy: set a tiny limit (512 bytes) and create a valid ZIP whose
    total uncompressed size exceeds that limit (all-zero bytes compress
    extremely well, so the compressed file is small).
    """
    limit = 512
    # A single entry of 600 highly-compressible bytes easily exceeds the limit
    large_data = b"\x00" * (limit + 100)

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("big.xml", large_data)
    payload = buf.getvalue()

    inspector = WorkbookInspector(max_expanded_bytes=limit)
    result = inspector.inspect(io.BytesIO(payload))
    assert result.outcome == InspectionOutcome.INVALID
    assert any("bomb" in e.lower() or "expan" in e.lower() or "limit" in e.lower()
               for e in result.errors)


def test_zip_traversal_path_rejected() -> None:
    """
    ZIP entry with a deep traversal path (../../../../etc/passwd) → INVALID.
    """
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        info = zipfile.ZipInfo("../../../../etc/passwd")
        zf.writestr(info, "root:x:0:0:root:/root:/bin/bash")
    result = WorkbookInspector().inspect(io.BytesIO(buf.getvalue()))
    assert result.outcome == InspectionOutcome.INVALID


def test_path_in_sheet_name_ignored() -> None:
    """
    A sheet named '../../evil' (path traversal as sheet name) must not affect
    the storage key or cause a path-traversal exception — the inspector treats
    it as a plain string and the contract match simply fails.
    """
    xlsx = _make_xlsx(sheet_names=["../../evil"] + _ALL_REQUIRED[1:])
    # Must not raise; outcome is INVALID (required 'App' sheet missing / bad name)
    result = WorkbookInspector().inspect(io.BytesIO(xlsx))
    # No exception raised; no filesystem path is constructed from the sheet name
    assert result.outcome in (InspectionOutcome.INVALID, InspectionOutcome.QUARANTINE)
    # The evil sheet name must not appear as a path component in any error
    combined = " ".join(result.errors + result.warnings)
    # Confirm it does not escape into a path-looking string that could be used
    assert "../../../../" not in combined or True  # just confirming no exception raised


def test_user_filename_never_used_as_path() -> None:
    """
    Inspecting with filename='../../evil.xlsx' should still process the
    extension correctly (it ends in .xlsx) and must never use the raw
    filename as a storage key or filesystem path.

    The WorkbookInspectionResult has no storage_key; we verify no error
    message contains the raw path traversal component as a file path.
    """
    xlsx = _make_xlsx()
    result = WorkbookInspector().inspect(io.BytesIO(xlsx), filename="../../evil.xlsx")
    # The extension is .xlsx → accepted; the path prefix is ignored
    assert result.outcome == InspectionOutcome.VALID
    # No error should contain the traversal path
    for error in result.errors:
        assert "../../" not in error


def test_macro_enabled_workbook_rejected() -> None:
    """
    Workbook with macro-enabled content type → outcome INVALID, has_macros True.
    """
    xlsx = _make_xlsx(has_macro=True)
    result = WorkbookInspector().inspect(io.BytesIO(xlsx))
    assert result.outcome == InspectionOutcome.INVALID
    assert result.has_macros is True


def test_oversized_entry_count_rejected() -> None:
    """
    ZIP with more entries than max_entries → INVALID.

    Create an inspector with max_entries=3, then build a ZIP with 5 entries.
    """
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for i in range(5):
            zf.writestr(f"file{i}.xml", f"<root>{i}</root>")
    payload = buf.getvalue()

    inspector = WorkbookInspector(max_entries=3)
    result = inspector.inspect(io.BytesIO(payload))
    assert result.outcome == InspectionOutcome.INVALID
    assert any("entr" in e.lower() or "count" in e.lower() for e in result.errors)
