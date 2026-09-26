"""
App-sheet projection adapter (B02).

Validates and parses the APP_DATA_CAPTURE_V1 'App' worksheet against
the compiled catalog projection. Produces typed candidates and findings
without any database interaction.

Row matching (section 13.2)
---------------------------
Because the workbook omits Question_ID, the v1 fingerprint requires all
rows in their expected display order.  Comparison fields are:

    Question text · Response_Type · Allowed_Values_or_Unit
    Required_Level · Required_When · Preferred_Source · Fallback_Sources

The Response column itself is EXCLUDED from structural comparison.

Drift severity (section 13.3)
------------------------------
    ERROR       → quarantine; never create a candidate from the drifted row
    WARNING     → record drift, continue processing
    INFORMATION → blank response; no candidate, not inferred as "No"

Response extraction (section 13.5)
------------------------------------
For every structurally clean row whose Response cell is non-blank:

    • Preserve raw cell value and locator  Sheet:App/Row:{n}/Col:D
    • Stage an AppCandidate with origin DETERMINISTIC
    • NEVER set answer confirmation
    • NEVER infer "No" from a blank cell
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

# ---------------------------------------------------------------------------
# Public enumerations
# ---------------------------------------------------------------------------


class RowDriftSeverity(str, Enum):
    """Severity level attached to each row-level drift record."""

    OK          = "OK"
    ERROR       = "ERROR"
    WARNING     = "WARNING"
    INFORMATION = "INFORMATION"


class RowDriftType(str, Enum):
    """Classification of a structural or data deviation in a sheet row."""

    MISSING_ROW           = "MISSING_ROW"
    CHANGED_RESPONSE_TYPE = "CHANGED_RESPONSE_TYPE"
    CHANGED_ALLOWED_VALUES = "CHANGED_ALLOWED_VALUES"
    CHANGED_REQUIRED_LEVEL = "CHANGED_REQUIRED_LEVEL"
    CHANGED_QUESTION_TEXT  = "CHANGED_QUESTION_TEXT"
    ADDITIONAL_ROW        = "ADDITIONAL_ROW"
    BLANK_RESPONSE        = "BLANK_RESPONSE"
    INVALID_RESPONSE      = "INVALID_RESPONSE"
    UNKNOWN_HEADER        = "UNKNOWN_HEADER"


# ---------------------------------------------------------------------------
# Immutable result types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AppRowDrift:
    """One structural or data deviation detected while parsing a sheet row."""

    row_number:       int
    drift_type:       RowDriftType
    severity:         RowDriftSeverity
    raw_question:     str
    catalog_question: str | None
    detail:           str


@dataclass(frozen=True)
class AppCandidate:
    """
    A single response candidate extracted from the App worksheet.

    Attributes:
        row_number:       1-based data row index (header row is not counted).
        question_index:   0-based catalog position (0–111 for a 112-row catalog).
        question_text:    Canonical question text from the verified catalog row.
        response_type:    Response type code from the verified catalog row.
        raw_value:        Verbatim cell content — never normalised or inferred.
        source_locator:   Cell address string e.g. "Sheet:App/Row:3/Col:D".
        origin:           Always "DETERMINISTIC" for workbook extractions.
        parser_version:   Contract version string ("APP_DATA_CAPTURE_V1").
    """

    row_number:     int
    question_index: int
    question_text:  str
    response_type:  str
    raw_value:      str
    source_locator: str
    origin:         str = "DETERMINISTIC"
    parser_version: str = "APP_DATA_CAPTURE_V1"


@dataclass(frozen=True)
class AppSheetResult:
    """Immutable result of parsing one App worksheet."""

    outcome:             str              # "VALID" | "QUARANTINED" | "FAILED"
    candidates:          tuple[AppCandidate, ...]
    drift:               tuple[AppRowDrift, ...]
    row_count:           int              # total sheet data rows supplied
    populated_count:     int              # rows where Response was non-blank
    catalog_match_count: int              # rows that passed all structural checks


# ---------------------------------------------------------------------------
# Column name → catalog key mapping
# ---------------------------------------------------------------------------

#: Maps normalised sheet column headers to the corresponding catalog dict key.
_COL_TO_CATALOG: dict[str, str] = {
    "Question":                "question_text",
    "Response_Type":           "response_type",
    "Allowed_Values_or_Unit":  "allowed_values_or_unit",
    "Required_Level":          "required_level",
    "Required_When":           "required_when",
    "Preferred_Source":        "preferred_source",
    "Fallback_Sources":        "fallback_sources",
}

#: Maps sheet column header → drift type produced when that column mismatches.
_COL_TO_DRIFT_TYPE: dict[str, RowDriftType] = {
    "Question":               RowDriftType.CHANGED_QUESTION_TEXT,
    "Response_Type":          RowDriftType.CHANGED_RESPONSE_TYPE,
    "Allowed_Values_or_Unit": RowDriftType.CHANGED_ALLOWED_VALUES,
    "Required_Level":         RowDriftType.CHANGED_REQUIRED_LEVEL,
    "Required_When":          RowDriftType.CHANGED_REQUIRED_LEVEL,   # same bucket
    "Preferred_Source":       RowDriftType.CHANGED_REQUIRED_LEVEL,   # no separate type
    "Fallback_Sources":       RowDriftType.CHANGED_REQUIRED_LEVEL,   # no separate type
}

#: Ordered list of columns checked for structural equivalence.
_COMPARISON_COLUMNS: tuple[str, ...] = (
    "Question",
    "Response_Type",
    "Allowed_Values_or_Unit",
    "Required_Level",
    "Required_When",
    "Preferred_Source",
    "Fallback_Sources",
)


# ---------------------------------------------------------------------------
# Adapter
# ---------------------------------------------------------------------------


class AppSheetAdapter:
    """
    Parses an App worksheet against a catalog projection.

    The adapter is intentionally stateless between ``parse`` calls — the same
    instance may be reused for multiple sheets from different workbooks.

    Args:
        catalog_rows:   List of dicts with keys:
                            display_order (1-based int), question_text,
                            response_type, allowed_values_or_unit,
                            required_level, required_when,
                            preferred_source, fallback_sources.
                        Rows are sorted by ``display_order`` on first use.
        header_aliases: Dict mapping alias column header → canonical header.
                        Applied before any structural comparison.  Defaults
                        to an empty dict (no aliases resolved).
    """

    def __init__(
        self,
        catalog_rows: list[dict],
        header_aliases: dict[str, str] | None = None,
    ) -> None:
        # Sort once so callers don't have to worry about ordering.
        self._catalog: list[dict] = sorted(
            catalog_rows, key=lambda r: r.get("display_order", 0)
        )
        self._aliases: dict[str, str] = header_aliases or {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def parse(self, sheet_rows: list[dict]) -> AppSheetResult:
        """
        Parse rows from the App worksheet.

        Args:
            sheet_rows: List of dicts keyed by raw column header (aliases
                        accepted).  Row position is 1-based starting from
                        the first data row (the header row is excluded by
                        the caller).

        Returns:
            AppSheetResult — always returned, never raised.
        """
        # ── 1. Normalise all sheet row column headers ──────────────────
        normalised_rows: list[dict] = [
            {self._normalize_header(k): v for k, v in row.items()}
            for row in sheet_rows
        ]

        n_catalog = len(self._catalog)
        n_sheet   = len(normalised_rows)
        matched   = min(n_catalog, n_sheet)

        drift_list:    list[AppRowDrift]   = []
        candidates:    list[AppCandidate]  = []
        has_errors:    bool  = False
        populated:     int   = 0
        match_count:   int   = 0

        # ── 2. Compare matched rows ────────────────────────────────────
        for idx in range(matched):
            row_number = idx + 1        # 1-based data row number
            cat = self._catalog[idx]
            srow = normalised_rows[idx]
            raw_question = str(srow.get("Question", "") or "")

            row_errors = self._compare_row(row_number, cat, srow, raw_question, drift_list)

            if row_errors:
                has_errors = True
                # Structural drift — never create a candidate from this row.
                continue

            # ── 3. Row passes structural check ─────────────────────────
            match_count += 1
            response = str(srow.get("Response", "") or "").strip()

            if not response:
                # Blank response: record INFORMATION drift, no candidate.
                # NEVER infer "No" from absence.
                drift_list.append(AppRowDrift(
                    row_number=row_number,
                    drift_type=RowDriftType.BLANK_RESPONSE,
                    severity=RowDriftSeverity.INFORMATION,
                    raw_question=raw_question,
                    catalog_question=cat.get("question_text"),
                    detail="Response cell is blank; no candidate will be created.",
                ))
            else:
                populated += 1
                candidates.append(AppCandidate(
                    row_number=row_number,
                    question_index=idx,          # 0-based catalog position
                    question_text=str(cat.get("question_text", "")),
                    response_type=str(cat.get("response_type", "")),
                    raw_value=response,
                    source_locator=f"Sheet:App/Row:{row_number}/Col:D",
                    origin="DETERMINISTIC",
                    parser_version="APP_DATA_CAPTURE_V1",
                ))

        # ── 4. Catalog rows missing from the sheet ─────────────────────
        for idx in range(matched, n_catalog):
            cat = self._catalog[idx]
            row_number = idx + 1
            drift_list.append(AppRowDrift(
                row_number=row_number,
                drift_type=RowDriftType.MISSING_ROW,
                severity=RowDriftSeverity.ERROR,
                raw_question="",
                catalog_question=cat.get("question_text"),
                detail=(
                    f"Catalog row {cat.get('display_order', row_number)} "
                    "is absent from the sheet."
                ),
            ))
            has_errors = True

        # ── 5. Sheet rows beyond the catalog boundary ──────────────────
        for idx in range(matched, n_sheet):
            row_number = idx + 1
            srow = normalised_rows[idx]
            raw_question = str(srow.get("Question", "") or "")
            drift_list.append(AppRowDrift(
                row_number=row_number,
                drift_type=RowDriftType.ADDITIONAL_ROW,
                severity=RowDriftSeverity.WARNING,
                raw_question=raw_question,
                catalog_question=None,
                detail=(
                    f"Sheet row {row_number} has no corresponding catalog entry."
                ),
            ))

        # ── 6. Determine overall outcome ───────────────────────────────
        outcome = "QUARANTINED" if has_errors else "VALID"

        return AppSheetResult(
            outcome=outcome,
            candidates=tuple(candidates),
            drift=tuple(drift_list),
            row_count=n_sheet,
            populated_count=populated,
            catalog_match_count=match_count,
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _compare_row(
        self,
        row_number: int,
        cat: dict,
        srow: dict,
        raw_question: str,
        drift_list: list[AppRowDrift],
    ) -> bool:
        """
        Compare one sheet row against its catalog counterpart.

        Appends an AppRowDrift for every mismatched comparison column and
        returns True if any ERROR-level drift was found.

        The Response column is intentionally excluded from comparison
        (section 13.2).
        """
        row_has_error = False

        for col in _COMPARISON_COLUMNS:
            cat_key   = _COL_TO_CATALOG[col]
            cat_val   = self._normalize_text(str(cat.get(cat_key, "") or ""))

            # Question text uses the same normalisation; other columns use
            # a plain strip so whitespace-only differences are still caught.
            if col == "Question":
                sheet_val = self._normalize_text(str(srow.get(col, "") or ""))
            else:
                sheet_val = str(srow.get(col, "") or "").strip()
                cat_val   = str(cat.get(cat_key, "") or "").strip()

            if cat_val != sheet_val:
                drift_type = _COL_TO_DRIFT_TYPE[col]
                drift_list.append(AppRowDrift(
                    row_number=row_number,
                    drift_type=drift_type,
                    severity=RowDriftSeverity.ERROR,
                    raw_question=raw_question,
                    catalog_question=cat.get("question_text"),
                    detail=(
                        f"Column '{col}': expected {cat_val!r}, "
                        f"got {sheet_val!r}."
                    ),
                ))
                row_has_error = True

        return row_has_error

    def _normalize_header(self, raw_header: str) -> str:
        """Apply alias resolution and whitespace normalisation to a column header."""
        stripped = raw_header.strip()
        return self._aliases.get(stripped, stripped)

    def _normalize_text(self, value: str) -> str:
        """Normalise question text: strip leading/trailing whitespace, collapse internal runs."""
        return " ".join(str(value).split())
