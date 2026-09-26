"""
Unit tests for the Database extension sheet adapter (B05).

All rows are synthetic dicts with keys 'question' and 'response'.
No real client data.

TDD RED: written before implementation; ImportError expected until
src/migration_intake/imports/database_sheet.py exists.
"""
from __future__ import annotations

import pytest

from migration_intake.imports.database_sheet import (
    DatabaseCandidate,
    DatabaseFinding,
    DatabaseFindingType,
    DatabaseSheetAdapter,
    DatabaseSheetResult,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_RAC_Q = "Is RAC, Data Guard, or standby DB configured?"


def _make_adapter() -> DatabaseSheetAdapter:
    return DatabaseSheetAdapter()


def _row(question: str, response: str) -> dict:
    return {"question": question, "response": response}


# ---------------------------------------------------------------------------
# Test 1 — known duplicate, same value → corroborating evidence
# ---------------------------------------------------------------------------


class TestKnownDuplicateSameValueCorroborates:
    def test_known_duplicate_same_value_corroborates(self) -> None:
        """Same question + same value twice → two DUPLICATE candidates, both locators retained."""
        rows = [
            _row(_RAC_Q, "YES"),
            _row(_RAC_Q, "YES"),
        ]
        result = _make_adapter().parse(rows)

        dup_cands = [c for c in result.candidates if c.disposition == "DUPLICATE"]
        assert len(dup_cands) == 2
        locators = {c.source_locator for c in dup_cands}
        assert "Sheet:Database/Row:1" in locators
        assert "Sheet:Database/Row:2" in locators

    def test_corroborating_produces_no_conflict_finding(self) -> None:
        """Same value twice → zero DUPLICATE_CONFLICT findings."""
        rows = [
            _row(_RAC_Q, "YES"),
            _row(_RAC_Q, "YES"),
        ]
        result = _make_adapter().parse(rows)

        conflict_findings = [
            f for f in result.findings
            if f.finding_type == DatabaseFindingType.DUPLICATE_CONFLICT
        ]
        assert len(conflict_findings) == 0

    def test_corroborating_value_case_insensitive(self) -> None:
        """'YES' and 'yes' are treated as the same normalized value (corroborating)."""
        rows = [
            _row(_RAC_Q, "YES"),
            _row(_RAC_Q, "yes"),
        ]
        result = _make_adapter().parse(rows)

        dup_cands = [c for c in result.candidates if c.disposition == "DUPLICATE"]
        assert len(dup_cands) == 2
        conflict_findings = [
            f for f in result.findings
            if f.finding_type == DatabaseFindingType.DUPLICATE_CONFLICT
        ]
        assert len(conflict_findings) == 0


# ---------------------------------------------------------------------------
# Test 2 — known duplicate, different values → intra-document conflict
# ---------------------------------------------------------------------------


class TestKnownDuplicateDifferentValueConflicts:
    def test_known_duplicate_different_value_conflicts(self) -> None:
        """Same question, different values → DUPLICATE_CONFLICT finding."""
        rows = [
            _row(_RAC_Q, "YES"),
            _row(_RAC_Q, "NO"),
        ]
        result = _make_adapter().parse(rows)

        conflict_findings = [
            f for f in result.findings
            if f.finding_type == DatabaseFindingType.DUPLICATE_CONFLICT
        ]
        assert len(conflict_findings) == 1
        assert "conflict" in conflict_findings[0].detail.lower()

    def test_conflict_preserves_both_candidates(self) -> None:
        """Both conflicting rows are still retained as DUPLICATE candidates."""
        rows = [
            _row(_RAC_Q, "YES"),
            _row(_RAC_Q, "NO"),
        ]
        result = _make_adapter().parse(rows)

        dup_cands = [c for c in result.candidates if c.disposition == "DUPLICATE"]
        assert len(dup_cands) == 2

    def test_conflict_finding_is_frozen(self) -> None:
        """DatabaseFinding is immutable (frozen dataclass)."""
        rows = [
            _row(_RAC_Q, "YES"),
            _row(_RAC_Q, "NO"),
        ]
        result = _make_adapter().parse(rows)
        finding = next(
            f for f in result.findings
            if f.finding_type == DatabaseFindingType.DUPLICATE_CONFLICT
        )
        with pytest.raises(Exception):
            finding.detail = "tampered"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Test 3 — known duplicate, one blank → use populated + report template structure
# ---------------------------------------------------------------------------


class TestKnownDuplicateOneBlankUsesPopulated:
    def test_known_duplicate_one_blank_uses_populated(self) -> None:
        """Populated row → DUPLICATE candidate; blank row → DUPLICATE_TEMPLATE finding."""
        rows = [
            _row(_RAC_Q, "YES"),
            _row(_RAC_Q, ""),
        ]
        result = _make_adapter().parse(rows)

        dup_cands = [c for c in result.candidates if c.disposition == "DUPLICATE"]
        assert len(dup_cands) == 1
        assert dup_cands[0].raw_response == "YES"

        template_findings = [
            f for f in result.findings
            if f.finding_type == DatabaseFindingType.DUPLICATE_TEMPLATE
        ]
        assert len(template_findings) == 1

    def test_blank_duplicate_does_not_increment_blank_rows_skipped(self) -> None:
        """Blank *response* in a DUPLICATE row is not a 'blank row' (question is non-blank)."""
        rows = [
            _row(_RAC_Q, "YES"),
            _row(_RAC_Q, ""),
        ]
        result = _make_adapter().parse(rows)

        # blank_rows_skipped only counts rows where BOTH question and response are blank
        assert result.blank_rows_skipped == 0

    def test_populated_candidate_source_locator_is_row_one(self) -> None:
        """When populated row is row 1, its source_locator is 'Sheet:Database/Row:1'."""
        rows = [
            _row(_RAC_Q, "YES"),  # row 1 populated
            _row(_RAC_Q, ""),     # row 2 blank
        ]
        result = _make_adapter().parse(rows)

        dup_cands = [c for c in result.candidates if c.disposition == "DUPLICATE"]
        assert dup_cands[0].source_locator == "Sheet:Database/Row:1"


# ---------------------------------------------------------------------------
# Test 4 — unknown question produces UNMAPPED finding, no candidate
# ---------------------------------------------------------------------------


class TestUnknownQuestionProducesUnmappedFinding:
    def test_unknown_question_produces_unmapped_finding(self) -> None:
        """An unrecognised question for the Database sheet → UNMAPPED finding."""
        rows = [_row("Unknown DB Field", "some value")]
        result = _make_adapter().parse(rows)

        assert result.candidates == ()
        unmapped = [
            f for f in result.findings
            if f.finding_type == DatabaseFindingType.UNMAPPED
        ]
        assert len(unmapped) == 1
        assert unmapped[0].raw_question == "Unknown DB Field"
        assert unmapped[0].row_number == 1

    def test_unmapped_finding_is_frozen(self) -> None:
        """DatabaseFinding (UNMAPPED) is immutable."""
        rows = [_row("Unknown DB Field", "val")]
        result = _make_adapter().parse(rows)
        finding = result.findings[0]

        with pytest.raises(Exception):
            finding.raw_question = "tampered"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Test 5 — blank row (both question and response empty) is silently skipped
# ---------------------------------------------------------------------------


class TestBlankRowIsSkipped:
    def test_blank_row_is_skipped(self) -> None:
        """A row where both question and response are empty → skipped silently."""
        rows = [_row("", "")]
        result = _make_adapter().parse(rows)

        assert result.blank_rows_skipped == 1
        assert result.candidates == ()
        assert result.findings == ()

    def test_whitespace_only_row_is_skipped(self) -> None:
        """A row of only whitespace in both fields is also treated as blank."""
        rows = [_row("   ", "\t")]
        result = _make_adapter().parse(rows)

        assert result.blank_rows_skipped == 1

    def test_result_is_frozen(self) -> None:
        """DatabaseSheetResult is a frozen dataclass (immutable)."""
        rows = [_row("", "")]
        result = _make_adapter().parse(rows)

        with pytest.raises(Exception):
            result.blank_rows_skipped = 99  # type: ignore[misc]

    def test_candidates_is_tuple(self) -> None:
        """DatabaseSheetResult.candidates is a tuple, not a list."""
        result = _make_adapter().parse([])
        assert isinstance(result.candidates, tuple)

    def test_findings_is_tuple(self) -> None:
        """DatabaseSheetResult.findings is a tuple, not a list."""
        result = _make_adapter().parse([])
        assert isinstance(result.findings, tuple)


# ---------------------------------------------------------------------------
# Test 6 — source locator format "Sheet:Database/Row:{n}"
# ---------------------------------------------------------------------------


class TestSourceLocatorFormat:
    def test_source_locator_format(self) -> None:
        """Row at 1-based index 2 → source_locator 'Sheet:Database/Row:2'."""
        rows = [
            _row("unknown_field", "val"),   # row 1 → UNMAPPED
            _row(_RAC_Q, "YES"),            # row 2 → DUPLICATE candidate
        ]
        result = _make_adapter().parse(rows)

        rac_cands = [
            c for c in result.candidates
            if c.target_register_field == "db_rac_configured"
        ]
        assert len(rac_cands) == 1
        assert rac_cands[0].source_locator == "Sheet:Database/Row:2"

    def test_source_locator_row_one(self) -> None:
        """First row in list → source_locator 'Sheet:Database/Row:1'."""
        rows = [_row(_RAC_Q, "YES")]
        result = _make_adapter().parse(rows)

        rac_cands = [c for c in result.candidates if c.target_register_field == "db_rac_configured"]
        assert len(rac_cands) == 1
        assert rac_cands[0].source_locator == "Sheet:Database/Row:1"

    def test_origin_is_deterministic(self) -> None:
        """Every DatabaseCandidate has origin == 'DETERMINISTIC'."""
        rows = [_row(_RAC_Q, "YES")]
        result = _make_adapter().parse(rows)

        for cand in result.candidates:
            assert cand.origin == "DETERMINISTIC"

    def test_candidate_is_frozen(self) -> None:
        """DatabaseCandidate is immutable (frozen dataclass)."""
        rows = [_row(_RAC_Q, "YES")]
        result = _make_adapter().parse(rows)
        cand = result.candidates[0]

        with pytest.raises(Exception):
            cand.raw_response = "tampered"  # type: ignore[misc]
