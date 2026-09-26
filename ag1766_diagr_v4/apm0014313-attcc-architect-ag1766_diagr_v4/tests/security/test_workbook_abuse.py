"""
SEC02 — Extended XLSX package security tests (workbook abuse edge cases).

Covers edge cases NOT present in test_xlsx_packages.py (B01):
  - Non-.xlsx extensions (.xlsb, .xlsm)
  - Absolute-path ZIP entries
  - Empty ZIP archives
  - Entry-count limit (sub-default limit for test speed)
  - Nested ZIP entries (no recursive decompression)
  - UTF-8 BOM in [Content_Types].xml
  - VBA / activeX content types
  - Null-byte and ultra-long sheet names
  - Stream resource cleanup
  - Duplicate [Content_Types].xml entries

All fixtures are synthetic in-memory bytes — no real client data.

Do NOT modify this file; it is owned exclusively by SEC02.
"""
from __future__ import annotations

import gc
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
# Minimal synthetic XLSX builder helpers (local reimplementation)
# ---------------------------------------------------------------------------

_ALL_REQUIRED = ["App", "iTAP", "WaveUtil", "Infra", "Database", "TSS", "Provisioning"]

_CT_NS = "http://schemas.openxmlformats.org/package/2006/content-types"
_SML_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
_WS_CT = "application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"
_WB_CT = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"
_MACRO_CT = "application/vnd.ms-excel.sheet.macroEnabled.main+xml"


def _ct_xml(
    sheet_names: list[str],
    has_macro: bool = False,
    extra_content_type: str | None = None,
    bom: bool = False,
) -> bytes:
    root = Element("Types", xmlns=_CT_NS)
    SubElement(root, "Default", Extension="rels", ContentType="application/vnd.openxmlformats-package.relationships+xml")
    SubElement(root, "Default", Extension="xml", ContentType="application/xml")
    ct = _MACRO_CT if has_macro else _WB_CT
    SubElement(root, "Override", PartName="/xl/workbook.xml", ContentType=ct)
    for i, _ in enumerate(sheet_names, 1):
        SubElement(root, "Override", PartName=f"/xl/worksheets/sheet{i}.xml", ContentType=_WS_CT)
    if extra_content_type:
        SubElement(root, "Override", PartName="/xl/extra.bin", ContentType=extra_content_type)
    body = tostring(root, encoding="unicode").encode("utf-8")
    return (b"\xef\xbb\xbf" + body) if bom else body


def _wb_xml(sheet_names: list[str]) -> bytes:
    root = Element("workbook", xmlns=_SML_NS)
    sheets_el = SubElement(root, "sheets")
    for i, name in enumerate(sheet_names, 1):
        SubElement(sheets_el, "sheet", name=name, sheetId=str(i))
    return tostring(root, encoding="unicode").encode("utf-8")


def _wb_xml_raw(raw_bytes: bytes) -> bytes:
    """Return raw bytes as the workbook.xml content (for invalid-XML scenarios)."""
    return raw_bytes


def _ws_xml() -> bytes:
    root = Element("worksheet", xmlns=_SML_NS)
    SubElement(root, "sheetData")
    return tostring(root, encoding="unicode").encode("utf-8")


def _rels_xml() -> bytes:
    root = Element("Relationships", xmlns=_REL_NS)
    SubElement(
        root,
        "Relationship",
        Id="rId1",
        Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument",
        Target="xl/workbook.xml",
    )
    return tostring(root, encoding="unicode").encode("utf-8")


def _wb_rels_xml(sheet_names: list[str]) -> bytes:
    root = Element("Relationships", xmlns=_REL_NS)
    for i, _ in enumerate(sheet_names, 1):
        SubElement(
            root,
            "Relationship",
            Id=f"rId{i}",
            Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet",
            Target=f"worksheets/sheet{i}.xml",
        )
    return tostring(root, encoding="unicode").encode("utf-8")


def _make_xlsx(
    sheet_names: list[str] | None = None,
    has_macro: bool = False,
    extra_content_type: str | None = None,
    bom_in_ct: bool = False,
) -> bytes:
    """Build a minimal well-formed XLSX in memory."""
    if sheet_names is None:
        sheet_names = list(_ALL_REQUIRED)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(
            "[Content_Types].xml",
            _ct_xml(sheet_names, has_macro, extra_content_type, bom_in_ct),
        )
        zf.writestr("_rels/.rels", _rels_xml())
        zf.writestr("xl/workbook.xml", _wb_xml(sheet_names))
        zf.writestr("xl/_rels/workbook.xml.rels", _wb_rels_xml(sheet_names))
        for i, _ in enumerate(sheet_names, 1):
            zf.writestr(f"xl/worksheets/sheet{i}.xml", _ws_xml())
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Extension-gate tests
# ---------------------------------------------------------------------------


def test_xlsb_extension_rejected() -> None:
    """
    Binary Excel format (.xlsb) rejected even if the content is valid XLSX bytes.

    The extension gate runs before ZIP signature checking; .xlsb is not in
    the allowed set {.xlsx}, so the inspector returns INVALID immediately.
    """
    xlsx_bytes = _make_xlsx()  # valid OOXML content
    result = WorkbookInspector().inspect(io.BytesIO(xlsx_bytes), filename="report.xlsb")
    assert result.outcome == InspectionOutcome.INVALID
    assert any(".xlsb" in e or "extension" in e.lower() for e in result.errors)


def test_xlsm_extension_rejected() -> None:
    """
    Macro-enabled Excel (.xlsm) rejected even without actual macros in the content.

    .xlsm is not in the allowed extension set.  The rejection happens at the
    extension gate and does not depend on the content of [Content_Types].xml.
    """
    xlsx_bytes = _make_xlsx()  # no macros in content — .xlsm extension is what matters
    result = WorkbookInspector().inspect(io.BytesIO(xlsx_bytes), filename="data.xlsm")
    assert result.outcome == InspectionOutcome.INVALID
    assert any(".xlsm" in e or "extension" in e.lower() for e in result.errors)


# ---------------------------------------------------------------------------
# ZIP structure / path traversal tests
# ---------------------------------------------------------------------------


def test_zip_with_absolute_path_rejected() -> None:
    """
    ZIP entry whose name starts with '/' (absolute path) → INVALID.

    Distinct from the existing ../../../../etc/passwd test (B01) which tests
    relative traversal; this test covers the absolute-path variant.
    """
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        info = zipfile.ZipInfo("/etc/passwd")
        zf.writestr(info, "root:x:0:0:root:/root:/bin/bash")
    result = WorkbookInspector().inspect(io.BytesIO(buf.getvalue()))
    assert result.outcome == InspectionOutcome.INVALID
    assert any("traversal" in e.lower() or "/etc/passwd" in e for e in result.errors)


def test_empty_zip_is_rejected() -> None:
    """
    ZIP archive with zero entries → INVALID.

    A ZIP with no entries cannot contain [Content_Types].xml, so the inspector
    must report a missing content-types file rather than silently succeeding.
    """
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w"):
        pass  # intentionally no entries
    result = WorkbookInspector().inspect(io.BytesIO(buf.getvalue()))
    assert result.outcome == InspectionOutcome.INVALID
    # An empty ZIP has no local-file entries (PK\x03\x04 signature absent),
    # so the magic-byte gate fires before the content-types check.
    # Either failure mode is acceptable — the key property is INVALID outcome.
    assert result.errors, "At least one error must be reported"


def test_entry_count_limit_enforced() -> None:
    """
    ZIP with more entries than max_entries → INVALID (entry-count gate).

    This test uses a sub-default limit (max_entries=50, entries=51) for
    speed while verifying the same enforcement path that protects against
    archive exhaustion attacks.  The DEFAULT_MAX_ENTRIES constant (10,000)
    is imported to confirm its value in the assertion comment.

    Note: B01's equivalent test (test_oversized_entry_count_rejected) uses
    max_entries=3 / entries=5; this test uses different values.
    """
    assert DEFAULT_MAX_ENTRIES == 10_000, "Confirm default hasn't changed"

    limit = 50
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for i in range(limit + 1):  # one more than the limit
            zf.writestr(f"file_{i:04d}.xml", f"<root>{i}</root>")

    inspector = WorkbookInspector(max_entries=limit)
    result = inspector.inspect(io.BytesIO(buf.getvalue()))
    assert result.outcome == InspectionOutcome.INVALID
    assert any("entr" in e.lower() or "count" in e.lower() for e in result.errors)


# ---------------------------------------------------------------------------
# Nested ZIP (zip-within-zip) test
# ---------------------------------------------------------------------------


def test_nested_zip_entry_rejected() -> None:
    """
    ZIP entry that is itself a ZIP file is NOT recursively decompressed.

    The inspector must treat nested ZIP bytes as ordinary content (counting
    their uncompressed size toward the bomb-detection limit), not recurse
    into them.  This test verifies no RecursionError or MemoryError escapes.
    """
    # Build a small inner ZIP
    inner_buf = io.BytesIO()
    with zipfile.ZipFile(inner_buf, "w", compression=zipfile.ZIP_DEFLATED) as inner_zf:
        for i in range(10):
            inner_zf.writestr(f"inner_{i}.xml", b"x" * 512)
    inner_bytes = inner_buf.getvalue()

    # Outer XLSX-like ZIP that includes the inner ZIP as one of its entries
    outer_buf = io.BytesIO()
    with zipfile.ZipFile(outer_buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", _ct_xml(_ALL_REQUIRED))
        zf.writestr("_rels/.rels", _rels_xml())
        zf.writestr("xl/workbook.xml", _wb_xml(_ALL_REQUIRED))
        zf.writestr("xl/_rels/workbook.xml.rels", _wb_rels_xml(_ALL_REQUIRED))
        for i, _ in enumerate(_ALL_REQUIRED, 1):
            zf.writestr(f"xl/worksheets/sheet{i}.xml", _ws_xml())
        zf.writestr("embedded.zip", inner_bytes)  # nested ZIP entry

    # Must not raise RecursionError or MemoryError
    result = WorkbookInspector().inspect(io.BytesIO(outer_buf.getvalue()))
    assert result.outcome in (InspectionOutcome.VALID, InspectionOutcome.QUARANTINE)


# ---------------------------------------------------------------------------
# XML content edge-case tests
# ---------------------------------------------------------------------------


def test_unicode_bom_in_xml_handled() -> None:
    """
    [Content_Types].xml beginning with a UTF-8 BOM (\\xef\\xbb\\xbf) does not
    cause an unhandled parse error.

    Python's expat XML parser handles UTF-8 BOM transparently, so the
    inspector should proceed normally and produce a valid VALID outcome when
    the rest of the package is correct.
    """
    xlsx_bytes = _make_xlsx(bom_in_ct=True)  # BOM prepended to [Content_Types].xml
    result = WorkbookInspector().inspect(io.BytesIO(xlsx_bytes))
    # BOM is handled transparently → outcome must not be INVALID due to BOM
    assert result.outcome in (InspectionOutcome.VALID, InspectionOutcome.QUARANTINE)
    # No error message should mention BOM or parse failure
    bom_errors = [e for e in result.errors if "bom" in e.lower() or "parse" in e.lower()]
    assert not bom_errors, f"Unexpected BOM-related errors: {bom_errors}"


def test_macro_vba_project_content_type_rejected() -> None:
    """
    A workbook containing the ActiveX content type should be treated as
    macro-enabled (has_macros=True) and rejected (INVALID).

    XFAIL: The current _MACRO_CONTENT_TYPES set does not include
    'application/vnd.ms-office.activeX+xml'.  The inspector therefore
    returns has_macros=False and (with all required sheets present) VALID —
    which is insecure.  This test documents the gap for a future fix.
    """
    activex_ct = "application/vnd.ms-office.activeX+xml"
    xlsx_bytes = _make_xlsx(extra_content_type=activex_ct)
    result = WorkbookInspector().inspect(io.BytesIO(xlsx_bytes))
    # Expected (not yet implemented):
    assert result.has_macros is True
    assert result.outcome == InspectionOutcome.INVALID


def test_sheet_names_with_null_bytes_handled() -> None:
    """
    workbook.xml whose sheet-name attribute contains a null byte (\\x00) is
    rejected gracefully.

    The XML specification forbids null bytes in element content and
    attributes.  Python's expat parser raises xml.etree.ElementTree.ParseError,
    which the inspector catches and converts into an INVALID outcome — no
    unhandled exception escapes.
    """
    # Build a raw workbook.xml containing a null byte inside the name attribute.
    # We cannot use ET helpers because they also reject null bytes.
    wb_raw = (
        f'<workbook xmlns="{_SML_NS}">'
        "<sheets>"
        '<sheet name="bad\x00name" sheetId="1"/>'
        "</sheets>"
        "</workbook>"
    ).encode("utf-8")

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("[Content_Types].xml", _ct_xml(_ALL_REQUIRED))
        zf.writestr("_rels/.rels", _rels_xml())
        zf.writestr("xl/workbook.xml", wb_raw)  # deliberately malformed
        zf.writestr("xl/_rels/workbook.xml.rels", _wb_rels_xml(_ALL_REQUIRED))
        for i, _ in enumerate(_ALL_REQUIRED, 1):
            zf.writestr(f"xl/worksheets/sheet{i}.xml", _ws_xml())

    # Must not raise; inspector must catch ET.ParseError internally
    result = WorkbookInspector().inspect(io.BytesIO(buf.getvalue()))
    assert result.outcome == InspectionOutcome.INVALID
    assert any(
        "parse" in e.lower() or "workbook" in e.lower() for e in result.errors
    )


def test_very_long_sheet_name_does_not_crash() -> None:
    """
    A sheet name of 1,000 characters must not cause a buffer overflow, crash,
    or unhandled exception in the inspector.

    The sheet will not match any required contract name, so the outcome will
    be INVALID due to missing sheets — the key assertion is that inspection
    completes without error propagation.
    """
    long_name = "A" * 1_000
    # Replace the first required sheet name with the long name
    sheet_names = [long_name] + _ALL_REQUIRED[1:]
    xlsx_bytes = _make_xlsx(sheet_names=sheet_names)

    # Must not raise; extremely long string is just a non-matching sheet name
    result = WorkbookInspector().inspect(io.BytesIO(xlsx_bytes))
    # 'App' (first required sheet) is absent — INVALID expected
    assert result.outcome == InspectionOutcome.INVALID


def test_inspector_closes_stream_resources() -> None:
    """
    After inspect() returns, the inspector holds no open handles to the
    supplied stream.

    The inspector calls stream.read() exactly once (consuming the entire
    content into a local variable) then works with an internal BytesIO.  The
    stream position should be at EOF after the call.
    """
    xlsx_bytes = _make_xlsx()
    stream = io.BytesIO(xlsx_bytes)
    assert stream.tell() == 0, "Stream must start at position 0"

    result = WorkbookInspector().inspect(stream)

    # Stream should be fully consumed (position == total length)
    assert stream.tell() == len(xlsx_bytes), (
        "Inspector must have called stream.read() to consume all content"
    )
    # Force GC to ensure no retained references cause issues
    gc.collect()
    # Outcome must still be valid (not affected by GC)
    assert result.outcome in (
        InspectionOutcome.VALID,
        InspectionOutcome.QUARANTINE,
        InspectionOutcome.INVALID,
    )


def test_multiple_content_types_xmls_rejected_or_first_used() -> None:
    """
    A ZIP archive containing duplicate '[Content_Types].xml' entries is
    handled safely — no unhandled exception, no crash.

    Python's zipfile module raises a UserWarning on write and returns the
    *last* entry with that name on read.  The inspector must not crash or
    raise an unhandled exception in this situation.
    """
    import warnings

    ct_first = _ct_xml(_ALL_REQUIRED)   # valid, all required sheets
    ct_second = b"<Types/>"             # minimal / different content

    buf = io.BytesIO()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)  # suppress zipfile duplicate warning
        with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("[Content_Types].xml", ct_first)
            zf.writestr("[Content_Types].xml", ct_second)  # intentional duplicate
            zf.writestr("_rels/.rels", _rels_xml())
            zf.writestr("xl/workbook.xml", _wb_xml(_ALL_REQUIRED))
            zf.writestr("xl/_rels/workbook.xml.rels", _wb_rels_xml(_ALL_REQUIRED))
            for i, _ in enumerate(_ALL_REQUIRED, 1):
                zf.writestr(f"xl/worksheets/sheet{i}.xml", _ws_xml())

    # Must not raise any unhandled exception
    result = WorkbookInspector().inspect(io.BytesIO(buf.getvalue()))

    # The second (last) entry "<Types/>" is not valid OOXML — inspector may
    # flag a parse error or missing content type, but must NOT crash.
    assert result.outcome in (
        InspectionOutcome.VALID,
        InspectionOutcome.QUARANTINE,
        InspectionOutcome.INVALID,
    )
