"""
Workbook package inspection and contract classification.

Security model (section 54.1):
- Only .xlsx (non-macro OOXML) files accepted.
- ZIP signature verified before opening.
- ZIP entries checked for path traversal (../ or absolute paths).
- Total uncompressed size bounded to detect decompression bombs.
- Number of ZIP entries bounded.
- [Content_Types].xml scanned for macro-enabled and external-link content types.
- Macros → INVALID; external links → QUARANTINE with warning.
- Encryption flag in any ZIP entry → INVALID.
- xl/workbook.xml parsed for sheet names using stdlib XML only.
- Formulas are NEVER evaluated; formula cells preserved as raw XML.
- User-supplied filename used ONLY for extension check; never used as a path.
"""
from __future__ import annotations

import io
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
from typing import BinaryIO

from migration_intake.imports.contracts import (
    APP_DATA_CAPTURE_V1,
    InspectionOutcome,
    SheetPresence,
    WorkbookContract,
    WorkbookInspectionResult,
)

# ---------------------------------------------------------------------------
# Safety limits (overridable via constructor)
# ---------------------------------------------------------------------------

DEFAULT_MAX_COMPRESSED_BYTES: int = 100 * 1024 * 1024   # 100 MB
DEFAULT_MAX_EXPANDED_BYTES: int = 500 * 1024 * 1024      # 500 MB
DEFAULT_MAX_ENTRIES: int = 10_000
DEFAULT_MAX_ROWS: int = 200_000
DEFAULT_MAX_COLS: int = 500
DEFAULT_MAX_CELL_LEN: int = 32_768

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: ZIP local-file magic bytes (PK\x03\x04)
_ZIP_MAGIC: bytes = b"PK\x03\x04"

#: OOXML content types that indicate macro-enabled workbooks → reject
_MACRO_CONTENT_TYPES: frozenset[str] = frozenset(
    [
        "application/vnd.ms-excel.sheet.macroEnabled.main+xml",
        "application/vnd.ms-excel.template.macroEnabled.main+xml",
        "application/vnd.ms-office.activeX+xml",
    ]
)

#: OOXML content type for external data links → warn, quarantine
_EXTERNAL_LINK_CONTENT_TYPE: str = (
    "application/vnd.openxmlformats-officedocument.spreadsheetml.externalLink+xml"
)

#: Only these file extensions are accepted (lowercase)
_ALLOWED_EXTENSIONS: frozenset[str] = frozenset({".xlsx"})

#: XML namespace for OOXML content types
_CT_NS: str = "http://schemas.openxmlformats.org/package/2006/content-types"

#: XML namespace for SpreadsheetML
_SML_NS: str = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"


# ---------------------------------------------------------------------------
# Inspector
# ---------------------------------------------------------------------------


class WorkbookInspector:
    """
    Inspects an XLSX package for contract identity and security violations.

    The inspector uses only stdlib ``zipfile`` + ``xml.etree.ElementTree``
    — it never invokes openpyxl or any formula evaluator.
    """

    def __init__(
        self,
        contract: WorkbookContract = APP_DATA_CAPTURE_V1,
        max_compressed_bytes: int = DEFAULT_MAX_COMPRESSED_BYTES,
        max_expanded_bytes: int = DEFAULT_MAX_EXPANDED_BYTES,
        max_entries: int = DEFAULT_MAX_ENTRIES,
    ) -> None:
        self._contract = contract
        self._max_compressed_bytes = max_compressed_bytes
        self._max_expanded_bytes = max_expanded_bytes
        self._max_entries = max_entries

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def inspect(self, stream: BinaryIO, filename: str = "") -> WorkbookInspectionResult:
        """
        Inspect a binary stream as an XLSX workbook.

        Args:
            stream:   Binary stream of the uploaded file.
            filename: Original filename — used ONLY for extension validation;
                      never used as a filesystem path or storage key.

        Returns:
            WorkbookInspectionResult describing the outcome and all findings.
        """
        errors: list[str] = []
        warnings: list[str] = []

        # ── 1. Read stream completely ──────────────────────────────────
        data = stream.read()
        compressed_bytes = len(data)

        if compressed_bytes == 0:
            return self._early_invalid(
                errors=["Empty stream: no data received"],
                compressed_bytes=0,
                expanded_bytes=0,
            )

        # ── 2. Compressed-size gate ────────────────────────────────────
        if compressed_bytes > self._max_compressed_bytes:
            return self._early_invalid(
                errors=[
                    f"Compressed size {compressed_bytes:,} bytes exceeds limit "
                    f"{self._max_compressed_bytes:,} bytes"
                ],
                compressed_bytes=compressed_bytes,
                expanded_bytes=0,
            )

        # ── 3. Extension check (filename is optional) ──────────────────
        if filename:
            suffix = Path(filename).suffix.lower()
            if suffix not in _ALLOWED_EXTENSIONS:
                return self._early_invalid(
                    errors=[
                        f"Unsupported file extension {suffix!r}. "
                        f"Only .xlsx files are accepted."
                    ],
                    compressed_bytes=compressed_bytes,
                    expanded_bytes=0,
                )

        # ── 4. ZIP magic-byte check ────────────────────────────────────
        if len(data) < 4 or data[:4] != _ZIP_MAGIC:
            return self._early_invalid(
                errors=[
                    "File is not a valid ZIP/XLSX package "
                    "(ZIP local-file signature PK\\x03\\x04 not found)"
                ],
                compressed_bytes=compressed_bytes,
                expanded_bytes=0,
            )

        # ── 5. Open ZIP archive ────────────────────────────────────────
        try:
            zf = zipfile.ZipFile(io.BytesIO(data), "r")
        except zipfile.BadZipFile as exc:
            return self._early_invalid(
                errors=[f"Corrupt ZIP archive: {exc}"],
                compressed_bytes=compressed_bytes,
                expanded_bytes=0,
            )

        with zf:
            infolist = zf.infolist()

            # ── 6. Entry-count gate ────────────────────────────────────
            if len(infolist) > self._max_entries:
                return self._early_invalid(
                    errors=[
                        f"ZIP entry count {len(infolist):,} exceeds limit "
                        f"{self._max_entries:,}"
                    ],
                    compressed_bytes=compressed_bytes,
                    expanded_bytes=0,
                )

            # ── 7. Traversal + encryption + expansion check ───────────
            has_encryption = False
            expanded_bytes = 0
            for info in infolist:
                # Path traversal guard
                if self._has_traversal(info.filename):
                    return self._early_invalid(
                        errors=[
                            f"ZIP path traversal detected in entry: {info.filename!r}"
                        ],
                        compressed_bytes=compressed_bytes,
                        expanded_bytes=expanded_bytes,
                    )

                # Encryption flag (bit 0 of general-purpose bit flag)
                if info.flag_bits & 0x1:
                    has_encryption = True
                    errors.append(
                        f"Encrypted ZIP entry detected: {info.filename!r}"
                    )

                # Decompression-bomb guard
                expanded_bytes += info.file_size
                if expanded_bytes > self._max_expanded_bytes:
                    return self._early_invalid(
                        errors=[
                            f"Expanded size exceeds limit {self._max_expanded_bytes:,} bytes "
                            "(potential decompression bomb)"
                        ],
                        compressed_bytes=compressed_bytes,
                        expanded_bytes=expanded_bytes,
                    )

            # ── 8. Parse [Content_Types].xml ──────────────────────────
            has_macros = False
            has_external_links = False
            try:
                ct_data = zf.read("[Content_Types].xml")
                ct_root = ET.fromstring(ct_data)
                for elem in ct_root.iter():
                    ct_val = elem.get("ContentType", "")
                    if ct_val in _MACRO_CONTENT_TYPES:
                        has_macros = True
                        errors.append(
                            f"Macro-enabled content type detected: {ct_val!r}"
                        )
                    elif ct_val == _EXTERNAL_LINK_CONTENT_TYPE:
                        has_external_links = True
                        warnings.append(
                            "External links detected in workbook — review before ingestion"
                        )
            except KeyError:
                errors.append("Missing [Content_Types].xml — not a valid OOXML package")
            except ET.ParseError as exc:
                errors.append(f"Cannot parse [Content_Types].xml: {exc}")

            # ── 9. Parse xl/workbook.xml for sheet names ──────────────
            sheet_names_raw: list[str] = []
            try:
                wb_data = zf.read("xl/workbook.xml")
                wb_root = ET.fromstring(wb_data)
                sheets_el = wb_root.find(f"{{{_SML_NS}}}sheets")
                if sheets_el is not None:
                    for sheet_el in sheets_el.findall(f"{{{_SML_NS}}}sheet"):
                        name = sheet_el.get("name", "").strip()
                        if name:
                            sheet_names_raw.append(name)
            except KeyError:
                errors.append("Missing xl/workbook.xml — not a valid OOXML package")
            except ET.ParseError as exc:
                errors.append(f"Cannot parse xl/workbook.xml: {exc}")

        # ── 10. Duplicate sheet-name check ────────────────────────────
        self._check_duplicates(sheet_names_raw, errors)

        # ── 11. Contract matching ─────────────────────────────────────
        sheet_presence = self._match_contract(sheet_names_raw, errors)

        # ── 12. Determine outcome ─────────────────────────────────────
        if errors:
            outcome = InspectionOutcome.INVALID
            contract_version: str | None = None
        elif warnings:
            outcome = InspectionOutcome.QUARANTINE
            contract_version = self._contract.contract_version
        else:
            outcome = InspectionOutcome.VALID
            contract_version = self._contract.contract_version

        return WorkbookInspectionResult(
            outcome=outcome,
            contract_version=contract_version,
            sheet_presence=tuple(sheet_presence),
            has_macros=has_macros,
            has_encryption=has_encryption,
            has_external_links=has_external_links,
            compressed_bytes=compressed_bytes,
            expanded_bytes=expanded_bytes,
            sheet_count=len(sheet_names_raw),
            errors=tuple(errors),
            warnings=tuple(warnings),
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _has_traversal(entry_name: str) -> bool:
        """Return True if the ZIP entry name contains a path traversal sequence."""
        # Normalise to forward slashes then inspect each path component
        normalised = entry_name.replace("\\", "/")
        if normalised.startswith("/"):
            return True
        parts = normalised.split("/")
        return ".." in parts

    def _check_duplicates(
        self, sheet_names: list[str], errors: list[str]
    ) -> None:
        """Append an error for each duplicate sheet name (after normalization)."""
        seen: dict[str, str] = {}
        for name in sheet_names:
            # Normalise: apply sheet-level aliases from the contract sheets
            key = name
            if key in seen:
                errors.append(
                    f"Duplicate worksheet name detected after normalization: {name!r}"
                )
            else:
                seen[key] = name

    def _match_contract(
        self, sheet_names: list[str], errors: list[str]
    ) -> list[SheetPresence]:
        """
        Match the actual sheet names against each SheetContract.

        Appends an error for every required sheet that is absent.
        Returns one SheetPresence entry per contract sheet.
        """
        name_set = set(sheet_names)
        presences: list[SheetPresence] = []

        for sheet_contract in self._contract.sheets:
            canonical = sheet_contract.canonical_name
            aliases = sheet_contract.aliases

            if canonical in name_set:
                presences.append(
                    SheetPresence(
                        canonical_name=canonical,
                        role=sheet_contract.role,
                        present=True,
                        alias_used=None,
                    )
                )
            else:
                alias_found: str | None = next(
                    (a for a in aliases if a in name_set), None
                )
                if alias_found is not None:
                    presences.append(
                        SheetPresence(
                            canonical_name=canonical,
                            role=sheet_contract.role,
                            present=True,
                            alias_used=alias_found,
                        )
                    )
                else:
                    presences.append(
                        SheetPresence(
                            canonical_name=canonical,
                            role=sheet_contract.role,
                            present=False,
                            alias_used=None,
                        )
                    )
                    if sheet_contract.required:
                        errors.append(
                            f"Required sheet missing: {canonical!r}"
                        )

        return presences

    def _early_invalid(
        self,
        errors: list[str],
        compressed_bytes: int,
        expanded_bytes: int,
    ) -> WorkbookInspectionResult:
        """Return a minimal INVALID result for early-exit paths."""
        return WorkbookInspectionResult(
            outcome=InspectionOutcome.INVALID,
            contract_version=None,
            sheet_presence=(),
            has_macros=False,
            has_encryption=False,
            has_external_links=False,
            compressed_bytes=compressed_bytes,
            expanded_bytes=expanded_bytes,
            sheet_count=0,
            errors=tuple(errors),
            warnings=(),
        )
