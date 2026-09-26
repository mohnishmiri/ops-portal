"""
Unit tests for TSS register sheet adapter (B04).

All rows are synthetic — no client data used.
TDD RED: written before implementation; ImportError expected until
src/migration_intake/imports/tss_sheet.py exists.
"""
from __future__ import annotations

import pytest

from migration_intake.imports.tss_sheet import (
    TSSCandidate,
    TSSFinding,
    TSSFindingType,
    TSSSheetAdapter,
    TSSSheetResult,
)


# ---------------------------------------------------------------------------
# Synthetic row factories — no client data
# ---------------------------------------------------------------------------


def _make_full_row(**overrides: str) -> dict:
    """Return a complete synthetic TSS row."""
    row: dict = {
        "Manufacturer": "Acme Corp",
        "Source Tech Stack": "Oracle DB",
        "Source Version": "12.2",
        "Target Tech Stack": "Aurora PostgreSQL",
        "Target Version": "15.3",
        "TSS Version Lifecycle": "Supported",
        "Notes": "See exception EXC-001",
    }
    row.update(overrides)
    return row


def _make_blank_row() -> dict:
    """Return a row where every value is an empty string."""
    return {
        "Manufacturer": "",
        "Source Tech Stack": "",
        "Source Version": "",
        "Target Tech Stack": "",
        "Target Version": "",
        "TSS Version Lifecycle": "",
        "Notes": "",
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestTSSSheetAdapter:
    # 1. Blank row is silently skipped; blank_rows_skipped incremented.
    def test_blank_row_is_skipped(self) -> None:
        adapter = TSSSheetAdapter()
        result = adapter.parse([_make_blank_row()])
        assert result.blank_rows_skipped == 1
        assert len(result.candidates) == 0

    # 2. Full row produces a TSSCandidate with correct field values.
    def test_valid_row_produces_candidate(self) -> None:
        adapter = TSSSheetAdapter()
        result = adapter.parse([_make_full_row()])
        assert len(result.candidates) == 1
        c = result.candidates[0]
        assert c.manufacturer == "Acme Corp"
        assert c.source_tech == "Oracle DB"
        assert c.source_version == "12.2"
        assert c.target_tech == "Aurora PostgreSQL"
        assert c.target_version == "15.3"
        assert c.lifecycle == "Supported"
        assert c.notes == "See exception EXC-001"

    # 3. source_locator uses "Sheet:TSS/Row:{n}" format; row numbering starts at 1.
    def test_source_locator_format(self) -> None:
        adapter = TSSSheetAdapter()
        result = adapter.parse([_make_full_row(), _make_full_row()])
        assert result.candidates[0].source_locator == "Sheet:TSS/Row:1"
        assert result.candidates[1].source_locator == "Sheet:TSS/Row:2"

    # 4. origin field is always "DETERMINISTIC".
    def test_origin_is_deterministic(self) -> None:
        adapter = TSSSheetAdapter()
        result = adapter.parse([_make_full_row()])
        assert result.candidates[0].origin == "DETERMINISTIC"

    # 5. A non-empty lifecycle value creates an UNVERIFIED_LIFECYCLE finding
    #    because portal provenance is absent in the first slice.
    def test_lifecycle_assertion_creates_unverified_finding(self) -> None:
        adapter = TSSSheetAdapter()
        result = adapter.parse([_make_full_row()])
        unverified = [
            f for f in result.findings
            if f.finding_type == TSSFindingType.UNVERIFIED_LIFECYCLE
        ]
        assert len(unverified) == 1
        assert unverified[0].row_number == 1

    # 6. _normalize_header strips Unicode format characters (zero-width space,
    #    BOM) so that column lookup works correctly.
    def test_zero_width_chars_stripped_from_headers(self) -> None:
        adapter = TSSSheetAdapter()
        # U+200B  ZERO WIDTH SPACE — suffix
        assert adapter._normalize_header("Manufacturer\u200b") == "Manufacturer"
        # U+FEFF  ZERO WIDTH NO-BREAK SPACE (BOM) — prefix
        assert adapter._normalize_header("\ufeffSource Tech Stack") == "Source Tech Stack"
        # U+200B  ZERO WIDTH SPACE — embedded between words (no space added on removal)
        assert adapter._normalize_header("TSS\u200b Version Lifecycle") == "TSS Version Lifecycle"
        # U+200D  ZERO WIDTH JOINER — trailing
        assert adapter._normalize_header("Notes\u200d") == "Notes"

    # 7. Parsing an empty list returns VALID with zero candidates.
    def test_empty_sheet_returns_valid(self) -> None:
        adapter = TSSSheetAdapter()
        result = adapter.parse([])
        assert result.outcome == "VALID"
        assert len(result.candidates) == 0
        assert result.blank_rows_skipped == 0

    # 8. Three valid rows produce exactly three candidates.
    def test_multiple_rows_all_candidates(self) -> None:
        adapter = TSSSheetAdapter()
        rows = [_make_full_row() for _ in range(3)]
        result = adapter.parse(rows)
        assert len(result.candidates) == 3
        # Row numbers are sequential from 1
        assert [c.row_number for c in result.candidates] == [1, 2, 3]
