"""
TSS register sheet adapter (B04).

Parses rows from the TSS worksheet of the APP_DATA_CAPTURE_V1 workbook into
typed TSSCandidate objects.  Blank rows are silently discarded.  Lifecycle
assertions always produce an UNVERIFIED_LIFECYCLE finding because portal
provenance is unavailable in this slice (section 14.2).

Zero-width Unicode format characters in column headers are stripped via
_normalize_header before any key lookup.
"""
from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from enum import Enum

# ---------------------------------------------------------------------------
# Column contract
# ---------------------------------------------------------------------------

#: Expected column names after zero-width-char stripping + whitespace strip.
TSS_COLUMNS: list[str] = [
    "Manufacturer",
    "Source Tech Stack",
    "Source Version",
    "Target Tech Stack",
    "Target Version",
    "TSS Version Lifecycle",
    "Notes",
]

#: Required fields — rows missing all of these (or with all empty values)
#: are treated as blank and skipped.
_REQUIRED_FIELDS: frozenset[str] = frozenset(
    {"Manufacturer", "Source Tech Stack", "Source Version"}
)


# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------


class TSSFindingType(str, Enum):
    """Classification of a finding raised during TSS sheet parsing."""

    BLANK_ROW = "BLANK_ROW"
    MISSING_COLUMN = "MISSING_COLUMN"
    UNVERIFIED_LIFECYCLE = "UNVERIFIED_LIFECYCLE"


@dataclass(frozen=True)
class TSSCandidate:
    """
    A technology-stack candidate extracted from a single TSS sheet row.

    Stable matching key: normalized manufacturer + source_tech + source_version.
    Lifecycle and exception assertions are unverified in this slice.
    """

    row_number: int
    manufacturer: str
    source_tech: str
    source_version: str
    target_tech: str
    target_version: str
    lifecycle: str
    notes: str
    source_locator: str   # Format: "Sheet:TSS/Row:{n}"
    origin: str = "DETERMINISTIC"


@dataclass(frozen=True)
class TSSFinding:
    """A single finding raised against a TSS sheet row."""

    row_number: int
    finding_type: TSSFindingType
    detail: str


@dataclass(frozen=True)
class TSSSheetResult:
    """Aggregate result of parsing a TSS register sheet."""

    outcome: str               # "VALID" | "QUARANTINED"
    candidates: tuple[TSSCandidate, ...]
    findings: tuple[TSSFinding, ...]
    blank_rows_skipped: int


# ---------------------------------------------------------------------------
# Adapter
# ---------------------------------------------------------------------------


class TSSSheetAdapter:
    """Parses TSS register rows into typed candidates and findings."""

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def parse(self, rows: list[dict]) -> TSSSheetResult:
        """
        Parse a list of row dicts from the TSS sheet.

        Args:
            rows: Each dict maps column header (possibly containing zero-width
                  characters) to the cell value string.  Blank rows — those
                  where every value is empty after stripping — are silently
                  discarded.

        Returns:
            TSSSheetResult with candidates, findings, and blank_rows_skipped.
        """
        candidates: list[TSSCandidate] = []
        findings: list[TSSFinding] = []
        blank_rows_skipped: int = 0

        for row_index, raw_row in enumerate(rows, start=1):
            # Normalize all keys in the row (strip zero-width format chars)
            row = {self._normalize_header(k): v for k, v in raw_row.items()}

            # ── Blank-row guard ────────────────────────────────────────
            if self._is_blank(row):
                blank_rows_skipped += 1
                continue

            # ── Field extraction ───────────────────────────────────────
            manufacturer = self._get(row, "Manufacturer")
            source_tech = self._get(row, "Source Tech Stack")
            source_version = self._get(row, "Source Version")
            target_tech = self._get(row, "Target Tech Stack")
            target_version = self._get(row, "Target Version")
            lifecycle = self._get(row, "TSS Version Lifecycle")
            notes = self._get(row, "Notes")

            source_locator = f"Sheet:TSS/Row:{row_index}"

            candidate = TSSCandidate(
                row_number=row_index,
                manufacturer=manufacturer,
                source_tech=source_tech,
                source_version=source_version,
                target_tech=target_tech,
                target_version=target_version,
                lifecycle=lifecycle,
                notes=notes,
                source_locator=source_locator,
                origin="DETERMINISTIC",
            )
            candidates.append(candidate)

            # ── Lifecycle assertion ────────────────────────────────────
            # Per section 14.2: lifecycle values cannot be verified against
            # portal authority in this slice → always raise UNVERIFIED_LIFECYCLE
            # when a lifecycle value is present.
            if lifecycle:
                findings.append(
                    TSSFinding(
                        row_number=row_index,
                        finding_type=TSSFindingType.UNVERIFIED_LIFECYCLE,
                        detail=(
                            f"Lifecycle {lifecycle!r} asserted but cannot be "
                            "verified without portal provenance"
                        ),
                    )
                )

        return TSSSheetResult(
            outcome="VALID",
            candidates=tuple(candidates),
            findings=tuple(findings),
            blank_rows_skipped=blank_rows_skipped,
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _normalize_header(self, raw: str) -> str:
        """
        Strip Unicode format characters (category Cf) and surrounding
        whitespace from a column header string.

        Removes zero-width space (U+200B), BOM / zero-width no-break space
        (U+FEFF), zero-width non-joiner (U+200C), zero-width joiner (U+200D),
        and all other Cf-category code points.
        """
        cleaned = "".join(
            c for c in raw if unicodedata.category(c) != "Cf"
        )
        return cleaned.strip()

    @staticmethod
    def _is_blank(row: dict) -> bool:
        """Return True when every value in the row is empty after stripping."""
        return all(not str(v).strip() for v in row.values())

    @staticmethod
    def _get(row: dict, key: str) -> str:
        """Return stripped string value for key, or empty string if absent."""
        return str(row.get(key, "")).strip()
