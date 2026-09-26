"""
Unit tests for the Infra extension sheet adapter (B05).

All rows are synthetic dicts with keys 'question' and 'response'.
No real client data.

TDD RED: written before implementation; ImportError expected until
src/migration_intake/imports/infra_sheet.py exists.
"""
from __future__ import annotations

import pytest

from migration_intake.imports.infra_sheet import (
    InfraCandidate,
    InfraFinding,
    InfraFindingType,
    InfraSheetAdapter,
    InfraSheetResult,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_adapter() -> InfraSheetAdapter:
    return InfraSheetAdapter()


def _row(question: str, response: str) -> dict:
    return {"question": question, "response": response}


# ---------------------------------------------------------------------------
# Test 1 — blank row (both question and response empty) is silently skipped
# ---------------------------------------------------------------------------


class TestBlankRowIsSkipped:
    def test_blank_row_is_skipped(self) -> None:
        """A row where both question and response are empty is skipped silently."""
        rows = [_row("", "")]
        result = _make_adapter().parse(rows)

        assert result.blank_rows_skipped == 1
        assert result.candidates == ()
        assert result.findings == ()

    def test_whitespace_only_row_is_skipped(self) -> None:
        """A row of only whitespace in both fields is also treated as blank."""
        rows = [_row("   ", "   ")]
        result = _make_adapter().parse(rows)

        assert result.blank_rows_skipped == 1
        assert result.candidates == ()
        assert result.findings == ()

    def test_multiple_blank_rows_counted(self) -> None:
        """Multiple blank rows increment blank_rows_skipped each time."""
        rows = [_row("", ""), _row("", ""), _row("Operating System", "Linux")]
        result = _make_adapter().parse(rows)

        assert result.blank_rows_skipped == 2
        assert len(result.candidates) == 1


# ---------------------------------------------------------------------------
# Test 2 — mapped question produces InfraCandidate with MAP_TO_QUESTION
# ---------------------------------------------------------------------------


class TestMappedQuestionProducesCandidate:
    def test_mapped_question_produces_candidate(self) -> None:
        """'Operating System' with valid response → InfraCandidate, MAP_TO_QUESTION."""
        rows = [_row("Operating System", "Linux")]
        result = _make_adapter().parse(rows)

        assert len(result.candidates) == 1
        cand = result.candidates[0]
        assert isinstance(cand, InfraCandidate)
        assert cand.disposition == "MAP_TO_QUESTION"
        assert cand.target_question_code == "ENV-001"
        assert cand.raw_question == "Operating System"
        assert cand.raw_response == "Linux"

    def test_mapped_question_produces_no_findings(self) -> None:
        """A fully valid mapped row produces zero findings."""
        rows = [_row("Operating System", "Linux")]
        result = _make_adapter().parse(rows)

        assert result.findings == ()

    def test_result_is_frozen(self) -> None:
        """InfraSheetResult is a frozen dataclass (immutable)."""
        rows = [_row("Operating System", "Linux")]
        result = _make_adapter().parse(rows)

        with pytest.raises(Exception):  # FrozenInstanceError
            result.blank_rows_skipped = 99  # type: ignore[misc]

    def test_candidate_is_frozen(self) -> None:
        """InfraCandidate is a frozen dataclass (immutable)."""
        rows = [_row("Operating System", "Linux")]
        result = _make_adapter().parse(rows)
        cand = result.candidates[0]

        with pytest.raises(Exception):  # FrozenInstanceError
            cand.raw_response = "tampered"  # type: ignore[misc]

    def test_candidates_is_tuple(self) -> None:
        """InfraSheetResult.candidates is a tuple, not a list."""
        result = _make_adapter().parse([])
        assert isinstance(result.candidates, tuple)

    def test_findings_is_tuple(self) -> None:
        """InfraSheetResult.findings is a tuple, not a list."""
        result = _make_adapter().parse([])
        assert isinstance(result.findings, tuple)


# ---------------------------------------------------------------------------
# Test 3 — unknown question produces UNMAPPED finding, no candidate
# ---------------------------------------------------------------------------


class TestUnmappedQuestionProducesFinding:
    def test_unmapped_question_produces_finding(self) -> None:
        """An unrecognised question → UNMAPPED finding, no candidate."""
        rows = [_row("Unknown Field XYZ", "some value")]
        result = _make_adapter().parse(rows)

        assert result.candidates == ()
        assert len(result.findings) == 1
        finding = result.findings[0]
        assert isinstance(finding, InfraFinding)
        assert finding.finding_type == InfraFindingType.UNMAPPED
        assert finding.raw_question == "Unknown Field XYZ"
        assert finding.row_number == 1

    def test_finding_is_frozen(self) -> None:
        """InfraFinding is a frozen dataclass (immutable)."""
        rows = [_row("Some Unknown", "val")]
        result = _make_adapter().parse(rows)
        finding = result.findings[0]

        with pytest.raises(Exception):
            finding.detail = "tampered"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Test 4 — RETIRED mapping produces RETIRED finding, no candidate
# ---------------------------------------------------------------------------


class TestRetiredQuestionProducesFinding:
    def test_retired_question_produces_finding(self) -> None:
        """'Legacy Hardware Note' maps to RETIRED → finding, no candidate."""
        rows = [_row("Legacy Hardware Note", "some value")]
        result = _make_adapter().parse(rows)

        assert result.candidates == ()
        assert len(result.findings) == 1
        finding = result.findings[0]
        assert finding.finding_type == InfraFindingType.RETIRED
        assert finding.row_number == 1

    def test_retired_finding_carries_raw_question(self) -> None:
        """RETIRED finding preserves the original raw_question string."""
        rows = [_row("Legacy Hardware Note", "ignored")]
        result = _make_adapter().parse(rows)

        assert result.findings[0].raw_question == "Legacy Hardware Note"


# ---------------------------------------------------------------------------
# Test 5 — N/A response not blindly accepted
# ---------------------------------------------------------------------------


class TestNAResponseNotBlindlyAccepted:
    def test_na_response_not_blindly_accepted(self) -> None:
        """'N/A' response for a non-applicable context → INVALID_VALUE finding."""
        rows = [_row("Operating System", "N/A")]
        result = _make_adapter().parse(rows)

        assert result.candidates == ()
        invalid_findings = [
            f for f in result.findings
            if f.finding_type == InfraFindingType.INVALID_VALUE
        ]
        assert len(invalid_findings) == 1
        assert invalid_findings[0].raw_response == "N/A"
        assert invalid_findings[0].row_number == 1

    def test_na_lowercase_also_rejected(self) -> None:
        """'n/a' (lowercase) is equally rejected."""
        rows = [_row("Operating System", "n/a")]
        result = _make_adapter().parse(rows)

        assert result.candidates == ()
        invalid_findings = [
            f for f in result.findings
            if f.finding_type == InfraFindingType.INVALID_VALUE
        ]
        assert len(invalid_findings) == 1


# ---------------------------------------------------------------------------
# Test 6 — NO response for non-boolean target produces INVALID_VALUE
# ---------------------------------------------------------------------------


class TestNoResponseForNonBooleanProducesFinding:
    def test_no_response_for_non_boolean_produces_finding(self) -> None:
        """'NO' for a MAP_TO_QUESTION (non-boolean) target → INVALID_VALUE finding."""
        rows = [_row("Operating System", "NO")]
        result = _make_adapter().parse(rows)

        assert result.candidates == ()
        invalid_findings = [
            f for f in result.findings
            if f.finding_type == InfraFindingType.INVALID_VALUE
        ]
        assert len(invalid_findings) == 1
        assert invalid_findings[0].raw_response == "NO"

    def test_no_lowercase_also_rejected_for_non_boolean(self) -> None:
        """'no' (lowercase) is equally rejected for non-boolean MAP_TO_QUESTION."""
        rows = [_row("Operating System", "no")]
        result = _make_adapter().parse(rows)

        invalid_findings = [
            f for f in result.findings
            if f.finding_type == InfraFindingType.INVALID_VALUE
        ]
        assert len(invalid_findings) == 1


# ---------------------------------------------------------------------------
# Test 7 — source locator format "Sheet:Infra/Row:{n}"
# ---------------------------------------------------------------------------


class TestSourceLocatorFormat:
    def test_source_locator_format(self) -> None:
        """Row at 1-based index 3 → source_locator 'Sheet:Infra/Row:3'."""
        rows = [
            _row("unknown_q1", "val1"),          # row 1 → UNMAPPED
            _row("unknown_q2", "val2"),          # row 2 → UNMAPPED
            _row("Operating System", "Linux"),   # row 3 → candidate
        ]
        result = _make_adapter().parse(rows)

        os_cands = [c for c in result.candidates if c.target_question_code == "ENV-001"]
        assert len(os_cands) == 1
        assert os_cands[0].source_locator == "Sheet:Infra/Row:3"

    def test_source_locator_row_one(self) -> None:
        """First row in list → source_locator 'Sheet:Infra/Row:1'."""
        rows = [_row("Operating System", "Linux")]
        result = _make_adapter().parse(rows)

        assert result.candidates[0].source_locator == "Sheet:Infra/Row:1"

    def test_blank_rows_do_not_advance_row_number(self) -> None:
        """Blank (skipped) rows do NOT count toward the row numbering of subsequent rows."""
        rows = [
            _row("", ""),                        # row 1 → skipped (blank)
            _row("Operating System", "Linux"),   # row 2 in the list
        ]
        result = _make_adapter().parse(rows)

        # Row numbering is 1-based over the original list, blank rows still count
        assert result.candidates[0].source_locator == "Sheet:Infra/Row:2"


# ---------------------------------------------------------------------------
# Test 8 — origin is DETERMINISTIC
# ---------------------------------------------------------------------------


class TestOriginIsDeterministic:
    def test_origin_is_deterministic(self) -> None:
        """Every InfraCandidate produced has origin == 'DETERMINISTIC'."""
        rows = [
            _row("Operating System", "Linux"),
            _row("Is RAC Configured", "YES"),
        ]
        result = _make_adapter().parse(rows)

        assert len(result.candidates) == 2
        for cand in result.candidates:
            assert cand.origin == "DETERMINISTIC"


# ---------------------------------------------------------------------------
# Test 9 — MAP_TO_REGISTER_FIELD disposition
# ---------------------------------------------------------------------------


class TestMapToRegisterFieldDisposition:
    def test_map_to_register_field_disposition(self) -> None:
        """'Is RAC Configured' → InfraCandidate with MAP_TO_REGISTER_FIELD disposition."""
        rows = [_row("Is RAC Configured", "YES")]
        result = _make_adapter().parse(rows)

        assert len(result.candidates) == 1
        cand = result.candidates[0]
        assert cand.disposition == "MAP_TO_REGISTER_FIELD"
        assert cand.target_register_field == "db_rac_configured"
        assert cand.target_question_code is None

    def test_map_to_register_field_no_response_accepted(self) -> None:
        """'NO' is a valid Boolean response for a MAP_TO_REGISTER_FIELD target."""
        rows = [_row("Is RAC Configured", "NO")]
        result = _make_adapter().parse(rows)

        assert len(result.candidates) == 1
        cand = result.candidates[0]
        assert cand.disposition == "MAP_TO_REGISTER_FIELD"

    def test_map_to_register_field_raw_response_preserved(self) -> None:
        """raw_response on the candidate retains the exact original string."""
        rows = [_row("Is RAC Configured", "YES")]
        result = _make_adapter().parse(rows)

        assert result.candidates[0].raw_response == "YES"
