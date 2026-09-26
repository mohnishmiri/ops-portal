"""
Unit tests for the iTAP source-capture sheet adapter (B03).

All rows are synthetic (label, value) pairs — no real client data.

TDD RED: written before implementation; ImportError expected until
src/migration_intake/imports/itap_sheet.py exists.
"""
from __future__ import annotations

import pytest

from migration_intake.imports.itap_sheet import (
    ITAP_LABEL_MAP,
    ITAPCandidate,
    ITAPFinding,
    ITAPFindingType,
    ITAPSheetAdapter,
    ITAPSheetResult,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_adapter() -> ITAPSheetAdapter:
    """Return a default adapter using the canonical ITAP_LABEL_MAP."""
    return ITAPSheetAdapter()


def _single_row(label: str, value: str) -> list[tuple[str, str]]:
    """Convenience: one-row sheet."""
    return [(label, value)]


# ---------------------------------------------------------------------------
# Test 1 — known label maps to canonical code
# ---------------------------------------------------------------------------

class TestKnownLabelMapping:
    def test_known_label_maps_to_canonical_code(self) -> None:
        """'Application Name' row produces an ITAPCandidate with code CTL-001."""
        rows = _single_row("Application Name", "MyApp")
        result = _make_adapter().parse(rows)

        assert len(result.candidates) == 1
        cand = result.candidates[0]
        assert isinstance(cand, ITAPCandidate)
        assert cand.canonical_code == "CTL-001"
        assert cand.raw_label == "Application Name"
        assert cand.raw_value == "MyApp"


# ---------------------------------------------------------------------------
# Test 2 — source locator format
# ---------------------------------------------------------------------------

class TestSourceLocatorFormat:
    def test_source_locator_format(self) -> None:
        """Row at position 3 (1-based) gets locator 'Sheet:iTAP/Row:3/Col:B'."""
        # Pad with two dummy rows before the target so it lands on row 3
        rows = [
            ("Application Name", "First"),
            ("MOTS ID", "12345"),
            ("Business Criticality", "HIGH"),
        ]
        result = _make_adapter().parse(rows)

        # Find the candidate for row 3 (Business Criticality)
        cand = next(c for c in result.candidates if c.row_number == 3)
        assert cand.source_locator == "Sheet:iTAP/Row:3/Col:B"


# ---------------------------------------------------------------------------
# Test 3 — blank value produces no candidate
# ---------------------------------------------------------------------------

class TestBlankValue:
    def test_blank_value_produces_no_candidate(self) -> None:
        """A known label with a blank value produces no candidate but a BLANK_DETAIL finding."""
        rows = _single_row("Application Name", "")
        result = _make_adapter().parse(rows)

        assert len(result.candidates) == 0

        blank_findings = [
            f for f in result.findings
            if f.finding_type == ITAPFindingType.BLANK_DETAIL
        ]
        assert len(blank_findings) == 1
        assert blank_findings[0].raw_label == "Application Name"
        assert blank_findings[0].row_number == 1

    def test_whitespace_only_value_is_blank(self) -> None:
        """A value of only spaces/tabs is treated as blank."""
        rows = _single_row("MOTS ID", "   ")
        result = _make_adapter().parse(rows)

        assert len(result.candidates) == 0
        blank_findings = [
            f for f in result.findings
            if f.finding_type == ITAPFindingType.BLANK_DETAIL
        ]
        assert len(blank_findings) == 1


# ---------------------------------------------------------------------------
# Test 4 — unknown label produces UNMAPPED_CONTENT finding
# ---------------------------------------------------------------------------

class TestUnknownLabel:
    def test_unknown_label_produces_unmapped_finding(self) -> None:
        """An unrecognized item label produces an UNMAPPED_CONTENT finding and no candidate."""
        rows = _single_row("Legacy Field XYZ", "some value")
        result = _make_adapter().parse(rows)

        assert len(result.candidates) == 0

        unmapped = [
            f for f in result.findings
            if f.finding_type == ITAPFindingType.UNMAPPED_CONTENT
        ]
        assert len(unmapped) == 1
        assert unmapped[0].raw_label == "Legacy Field XYZ"
        assert unmapped[0].row_number == 1


# ---------------------------------------------------------------------------
# Test 5 — duplicate item same value → DUPLICATE_ITEM finding (corroborating)
# ---------------------------------------------------------------------------

class TestDuplicateItemSameValue:
    def test_duplicate_item_same_value_produces_finding(self) -> None:
        """Two rows with the same label and identical values → DUPLICATE_ITEM finding."""
        rows = [
            ("Application Name", "MyApp"),
            ("Application Name", "MyApp"),
        ]
        result = _make_adapter().parse(rows)

        dup_findings = [
            f for f in result.findings
            if f.finding_type == ITAPFindingType.DUPLICATE_ITEM
        ]
        assert len(dup_findings) >= 1

        # The detail should indicate corroborating (same value)
        assert any("corrobor" in f.detail.lower() for f in dup_findings)

    def test_duplicate_same_value_still_produces_at_least_one_candidate(self) -> None:
        """Even with a duplicate, at least one candidate for the code is returned."""
        rows = [
            ("Application Name", "MyApp"),
            ("Application Name", "MyApp"),
        ]
        result = _make_adapter().parse(rows)

        codes = [c.canonical_code for c in result.candidates]
        assert "CTL-001" in codes


# ---------------------------------------------------------------------------
# Test 6 — duplicate item different value → DUPLICATE_ITEM finding (conflict)
# ---------------------------------------------------------------------------

class TestDuplicateItemDifferentValue:
    def test_duplicate_item_different_value_produces_ambiguity(self) -> None:
        """Two rows with the same label but different values → DUPLICATE_ITEM conflict finding."""
        rows = [
            ("Application Name", "MyApp"),
            ("Application Name", "OtherApp"),
        ]
        result = _make_adapter().parse(rows)

        dup_findings = [
            f for f in result.findings
            if f.finding_type == ITAPFindingType.DUPLICATE_ITEM
        ]
        assert len(dup_findings) >= 1

        # The detail should indicate conflict (different values)
        assert any("conflict" in f.detail.lower() for f in dup_findings)

    def test_duplicate_different_value_produces_multiple_candidates(self) -> None:
        """Both conflicting values are preserved as separate candidates."""
        rows = [
            ("Application Name", "MyApp"),
            ("Application Name", "OtherApp"),
        ]
        result = _make_adapter().parse(rows)

        app_name_candidates = [
            c for c in result.candidates if c.canonical_code == "CTL-001"
        ]
        assert len(app_name_candidates) == 2


# ---------------------------------------------------------------------------
# Test 7 — all 16 known labels map without UNMAPPED findings
# ---------------------------------------------------------------------------

class TestAll16KnownLabels:
    def test_all_16_known_labels_mapped(self) -> None:
        """Feeding all 16 ITAP_LABEL_MAP keys produces zero UNMAPPED_CONTENT findings."""
        rows = [(label, "SomeValue") for label in ITAP_LABEL_MAP]
        result = _make_adapter().parse(rows)

        unmapped = [
            f for f in result.findings
            if f.finding_type == ITAPFindingType.UNMAPPED_CONTENT
        ]
        assert unmapped == []

    def test_all_16_known_labels_produce_16_candidates(self) -> None:
        """All 16 known labels each produce exactly one candidate (no duplicates)."""
        rows = [(label, "SomeValue") for label in ITAP_LABEL_MAP]
        result = _make_adapter().parse(rows)

        assert len(result.candidates) == 16

    def test_all_16_canonical_codes_present(self) -> None:
        """Every canonical code in ITAP_LABEL_MAP is represented in the candidates."""
        rows = [(label, "SomeValue") for label in ITAP_LABEL_MAP]
        result = _make_adapter().parse(rows)

        returned_codes = {c.canonical_code for c in result.candidates}
        expected_codes = set(ITAP_LABEL_MAP.values())
        assert returned_codes == expected_codes


# ---------------------------------------------------------------------------
# Test 8 — all candidates have origin == "DETERMINISTIC"
# ---------------------------------------------------------------------------

class TestOriginIsDeterministic:
    def test_origin_is_deterministic(self) -> None:
        """Every ITAPCandidate produced by the adapter has origin == 'DETERMINISTIC'."""
        rows = [(label, "SomeValue") for label in ITAP_LABEL_MAP]
        result = _make_adapter().parse(rows)

        assert all(c.origin == "DETERMINISTIC" for c in result.candidates)


# ---------------------------------------------------------------------------
# Test 9 — empty sheet returns VALID with no candidates
# ---------------------------------------------------------------------------

class TestEmptySheet:
    def test_empty_sheet_returns_valid_with_no_candidates(self) -> None:
        """Parsing an empty row list → outcome VALID, zero candidates, zero findings."""
        result = _make_adapter().parse([])

        assert result.outcome == "VALID"
        assert len(result.candidates) == 0
        assert len(result.findings) == 0

    def test_empty_sheet_counts_are_zero(self) -> None:
        """mapped_count and unmapped_count are both 0 for an empty sheet."""
        result = _make_adapter().parse([])

        assert result.mapped_count == 0
        assert result.unmapped_count == 0


# ---------------------------------------------------------------------------
# Test 10 — extra whitespace in label normalized
# ---------------------------------------------------------------------------

class TestLabelNormalization:
    def test_extra_whitespace_in_label_normalized(self) -> None:
        """'  Application Name  ' (leading/trailing spaces) maps to CTL-001."""
        rows = _single_row("  Application Name  ", "MyApp")
        result = _make_adapter().parse(rows)

        assert len(result.candidates) == 1
        assert result.candidates[0].canonical_code == "CTL-001"

    def test_internal_whitespace_collapsed(self) -> None:
        """Label with collapsed internal spaces still matches (e.g. 'MOTS  ID' → 'MOTS ID')."""
        rows = _single_row("MOTS  ID", "99999")
        result = _make_adapter().parse(rows)

        assert len(result.candidates) == 1
        assert result.candidates[0].canonical_code == "CTL-003"

    def test_raw_label_preserved_despite_normalization(self) -> None:
        """Even when normalization is applied, raw_label on the candidate is the original string."""
        raw = "  Application Name  "
        rows = _single_row(raw, "MyApp")
        result = _make_adapter().parse(rows)

        assert result.candidates[0].raw_label == raw


# ---------------------------------------------------------------------------
# Test 11 — outcome is VALID for all 16 known items
# ---------------------------------------------------------------------------

class TestOutcomeValid:
    def test_outcome_is_valid_for_all_known_items(self) -> None:
        """Parsing all 16 known items with values → outcome is 'VALID'."""
        rows = [(label, "SomeValue") for label in ITAP_LABEL_MAP]
        result = _make_adapter().parse(rows)

        assert result.outcome == "VALID"

    def test_mapped_count_equals_number_of_known_rows(self) -> None:
        """mapped_count == 16 when all 16 known labels are provided."""
        rows = [(label, "SomeValue") for label in ITAP_LABEL_MAP]
        result = _make_adapter().parse(rows)

        assert result.mapped_count == 16

    def test_unmapped_count_is_zero_for_all_known_items(self) -> None:
        """unmapped_count == 0 when only known labels are provided."""
        rows = [(label, "SomeValue") for label in ITAP_LABEL_MAP]
        result = _make_adapter().parse(rows)

        assert result.unmapped_count == 0


# ---------------------------------------------------------------------------
# Test 12 — VALID outcome even when unknown items produce findings
# ---------------------------------------------------------------------------

class TestOutcomeWithFindings:
    def test_outcome_is_valid_with_findings(self) -> None:
        """Unknown items produce UNMAPPED findings but outcome remains VALID (iTAP is supplemental)."""
        rows = [
            ("Application Name", "MyApp"),
            ("UnknownField", "SomeData"),
        ]
        result = _make_adapter().parse(rows)

        assert result.outcome == "VALID"

        unmapped = [
            f for f in result.findings
            if f.finding_type == ITAPFindingType.UNMAPPED_CONTENT
        ]
        assert len(unmapped) == 1

    def test_unmapped_count_reflects_unknown_items(self) -> None:
        """unmapped_count tracks how many unrecognized items were encountered."""
        rows = [
            ("Application Name", "MyApp"),
            ("UnknownA", "val1"),
            ("UnknownB", "val2"),
        ]
        result = _make_adapter().parse(rows)

        assert result.unmapped_count == 2

    def test_mixed_sheet_has_correct_mapped_count(self) -> None:
        """Combination of known + unknown items: mapped_count counts only known-mapped rows."""
        rows = [
            ("Application Name", "MyApp"),   # mapped
            ("MOTS ID", "1234"),             # mapped
            ("UnknownField", "data"),        # unmapped
        ]
        result = _make_adapter().parse(rows)

        assert result.mapped_count == 2
        assert result.unmapped_count == 1


# ---------------------------------------------------------------------------
# Structural / dataclass contract tests
# ---------------------------------------------------------------------------

class TestDataclassContracts:
    def test_itap_sheet_result_is_frozen(self) -> None:
        """ITAPSheetResult must be immutable (frozen dataclass)."""
        rows = _single_row("Application Name", "MyApp")
        result = _make_adapter().parse(rows)

        with pytest.raises(Exception):  # FrozenInstanceError or AttributeError
            result.outcome = "QUARANTINED"  # type: ignore[misc]

    def test_itap_candidate_is_frozen(self) -> None:
        """ITAPCandidate must be immutable (frozen dataclass)."""
        rows = _single_row("Application Name", "MyApp")
        result = _make_adapter().parse(rows)

        cand = result.candidates[0]
        with pytest.raises(Exception):
            cand.raw_value = "tampered"  # type: ignore[misc]

    def test_itap_finding_is_frozen(self) -> None:
        """ITAPFinding must be immutable (frozen dataclass)."""
        rows = _single_row("  Unknown  ", "val")
        result = _make_adapter().parse(rows)

        finding = result.findings[0]
        with pytest.raises(Exception):
            finding.detail = "tampered"  # type: ignore[misc]

    def test_candidates_is_tuple(self) -> None:
        """ITAPSheetResult.candidates is a tuple, not a list."""
        result = _make_adapter().parse([])
        assert isinstance(result.candidates, tuple)

    def test_findings_is_tuple(self) -> None:
        """ITAPSheetResult.findings is a tuple, not a list."""
        result = _make_adapter().parse([])
        assert isinstance(result.findings, tuple)
