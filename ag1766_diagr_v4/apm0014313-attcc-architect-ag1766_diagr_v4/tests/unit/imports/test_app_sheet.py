"""
Unit tests for App-sheet projection adapter (B02).

All test data is purely synthetic — no real client evidence used.

TDD RED: written before implementation; ImportError is expected until
src/migration_intake/imports/app_sheet.py exists.
"""
from __future__ import annotations

import pytest

from migration_intake.imports.app_sheet import (
    AppCandidate,
    AppRowDrift,
    AppSheetAdapter,
    AppSheetResult,
    RowDriftSeverity,
    RowDriftType,
)


# ---------------------------------------------------------------------------
# Synthetic fixture helpers
# ---------------------------------------------------------------------------


def _catalog_row(
    n: int,
    question_text: str | None = None,
    response_type: str = "BOOLEAN",
    allowed_values: str = "YES/NO",
    required_level: str = "REQUIRED",
    required_when: str = "",
    preferred_source: str = "APP",
    fallback_sources: str = "",
) -> dict:
    return dict(
        display_order=n,
        question_text=question_text or f"Question {n}",
        response_type=response_type,
        allowed_values_or_unit=allowed_values,
        required_level=required_level,
        required_when=required_when,
        preferred_source=preferred_source,
        fallback_sources=fallback_sources,
    )


def _sheet_row(
    no: int,
    question: str,
    response_type: str,
    response: str = "",
    allowed: str = "YES/NO",
    required: str = "REQUIRED",
    when: str = "",
    pref: str = "APP",
    fallback: str = "",
) -> dict:
    return dict(
        No=str(no),
        Question=question,
        Response_Type=response_type,
        Response=response,
        Allowed_Values_or_Unit=allowed,
        Required_Level=required,
        Required_When=when,
        Preferred_Source=pref,
        Fallback_Sources=fallback,
    )


# ---------------------------------------------------------------------------
# 1. Blank response → no candidate, INFORMATION drift
# ---------------------------------------------------------------------------


class TestBlankResponse:
    """Blank Response cell must never produce a candidate."""

    def test_blank_response_produces_no_candidate(self) -> None:
        """Blank Response → zero candidates and exactly one INFORMATION drift."""
        catalog = [_catalog_row(1)]
        sheet = [_sheet_row(1, "Question 1", "BOOLEAN", "")]
        result = AppSheetAdapter(catalog).parse(sheet)

        assert len(result.candidates) == 0
        blank = [d for d in result.drift if d.drift_type == RowDriftType.BLANK_RESPONSE]
        assert len(blank) == 1
        assert blank[0].severity == RowDriftSeverity.INFORMATION

    def test_response_never_infers_no_from_blank(self) -> None:
        """Blank Response must never be inferred as 'No' — no candidate is created."""
        catalog = [_catalog_row(1)]
        sheet = [_sheet_row(1, "Question 1", "BOOLEAN", "")]
        result = AppSheetAdapter(catalog).parse(sheet)

        # Absolutely no candidate — the absence of a value is not treated as "No"
        assert result.candidates == ()
        assert result.populated_count == 0


# ---------------------------------------------------------------------------
# 2–3. Populated response → candidate with correct attributes / locator
# ---------------------------------------------------------------------------


class TestCandidateCreation:
    """Non-blank matching rows produce well-formed AppCandidate objects."""

    def test_populated_response_produces_candidate(self) -> None:
        """Non-blank Response → one AppCandidate carrying the raw cell value."""
        catalog = [_catalog_row(1)]
        sheet = [_sheet_row(1, "Question 1", "BOOLEAN", "YES")]
        result = AppSheetAdapter(catalog).parse(sheet)

        assert len(result.candidates) == 1
        c = result.candidates[0]
        assert c.raw_value == "YES"
        assert c.question_text == "Question 1"
        assert c.response_type == "BOOLEAN"

    def test_candidate_locator_format(self) -> None:
        """Row 2 in the sheet produces locator 'Sheet:App/Row:2/Col:D'."""
        catalog = [_catalog_row(1), _catalog_row(2)]
        sheet = [
            _sheet_row(1, "Question 1", "BOOLEAN", "YES"),
            _sheet_row(2, "Question 2", "BOOLEAN", "YES"),
        ]
        result = AppSheetAdapter(catalog).parse(sheet)

        by_row = {c.row_number: c for c in result.candidates}
        assert by_row[2].source_locator == "Sheet:App/Row:2/Col:D"

    def test_candidate_origin_is_deterministic(self) -> None:
        """Every candidate must declare origin == 'DETERMINISTIC'."""
        catalog = [_catalog_row(1)]
        sheet = [_sheet_row(1, "Question 1", "BOOLEAN", "YES")]
        result = AppSheetAdapter(catalog).parse(sheet)

        for c in result.candidates:
            assert c.origin == "DETERMINISTIC"

    def test_candidate_parser_version_is_v1(self) -> None:
        """Every candidate must declare parser_version == 'APP_DATA_CAPTURE_V1'."""
        catalog = [_catalog_row(1)]
        sheet = [_sheet_row(1, "Question 1", "BOOLEAN", "YES")]
        result = AppSheetAdapter(catalog).parse(sheet)

        for c in result.candidates:
            assert c.parser_version == "APP_DATA_CAPTURE_V1"


# ---------------------------------------------------------------------------
# 4. Changed response type → QUARANTINED + ERROR drift
# ---------------------------------------------------------------------------


class TestChangedResponseType:
    """Structural drift in the Response_Type column is fatal for the row."""

    def test_changed_response_type_produces_quarantine(self) -> None:
        """Sheet Response_Type != catalog response_type → QUARANTINED + ERROR drift."""
        catalog = [_catalog_row(1, response_type="BOOLEAN")]
        sheet = [_sheet_row(1, "Question 1", "TEXT")]   # TEXT ≠ BOOLEAN

        result = AppSheetAdapter(catalog).parse(sheet)

        assert result.outcome == "QUARANTINED"
        err = [
            d for d in result.drift
            if d.drift_type == RowDriftType.CHANGED_RESPONSE_TYPE
        ]
        assert len(err) >= 1
        assert err[0].severity == RowDriftSeverity.ERROR

    def test_changed_response_type_row_produces_no_candidate(self) -> None:
        """Drifted row must not yield any candidate even when Response is populated."""
        catalog = [_catalog_row(1, response_type="BOOLEAN")]
        sheet = [_sheet_row(1, "Question 1", "TEXT", response="YES")]

        result = AppSheetAdapter(catalog).parse(sheet)

        assert result.candidates == ()


# ---------------------------------------------------------------------------
# 5. Extra sheet rows → ADDITIONAL_ROW drift
# ---------------------------------------------------------------------------


class TestAdditionalRow:
    """Sheet rows beyond the catalog boundary produce ADDITIONAL_ROW drift."""

    def test_additional_row_beyond_catalog_produces_finding(self) -> None:
        """Sheet has one more row than catalog → ADDITIONAL_ROW drift entry."""
        catalog = [_catalog_row(1)]
        sheet = [
            _sheet_row(1, "Question 1", "BOOLEAN"),
            _sheet_row(2, "Extra Row",  "TEXT"),    # no catalog counterpart
        ]
        result = AppSheetAdapter(catalog).parse(sheet)

        additional = [d for d in result.drift if d.drift_type == RowDriftType.ADDITIONAL_ROW]
        assert len(additional) == 1


# ---------------------------------------------------------------------------
# 6. Missing catalog row → MISSING_ROW drift (ERROR)
# ---------------------------------------------------------------------------


class TestMissingRow:
    """Catalog rows absent from the sheet produce ERROR-level MISSING_ROW drift."""

    def test_missing_catalog_row_produces_error(self) -> None:
        """Catalog has 2 rows but sheet supplies only 1 → MISSING_ROW drift."""
        catalog = [_catalog_row(1), _catalog_row(2)]
        sheet   = [_sheet_row(1, "Question 1", "BOOLEAN")]   # row 2 absent

        result = AppSheetAdapter(catalog).parse(sheet)

        missing = [d for d in result.drift if d.drift_type == RowDriftType.MISSING_ROW]
        assert len(missing) == 1
        assert missing[0].severity == RowDriftSeverity.ERROR


# ---------------------------------------------------------------------------
# 7. Header alias "Resonse" → "Response"
# ---------------------------------------------------------------------------


class TestHeaderAlias:
    """Column header alias resolution maps 'Resonse' to 'Response'."""

    def test_header_alias_resonse_resolves_to_response(self) -> None:
        """Sheet column named 'Resonse' is alias-resolved; response extracted."""
        catalog = [_catalog_row(1)]

        # Build a row that uses the known misspelling as the column key
        base = _sheet_row(1, "Question 1", "BOOLEAN", "")
        aliased_row: dict = {
            (k if k != "Response" else "Resonse"): v for k, v in base.items()
        }
        aliased_row["Resonse"] = "YES"  # populate the aliased column

        adapter = AppSheetAdapter(catalog, header_aliases={"Resonse": "Response"})
        result = adapter.parse([aliased_row])

        assert result.outcome == "VALID"
        assert len(result.candidates) == 1
        assert result.candidates[0].raw_value == "YES"


# ---------------------------------------------------------------------------
# 9. Changed question text → ERROR drift + QUARANTINED
# ---------------------------------------------------------------------------


class TestChangedQuestionText:
    """Question text mismatch between sheet and catalog is a fatal drift."""

    def test_changed_question_text_quarantines(self) -> None:
        """Sheet question text differs from catalog → ERROR drift, QUARANTINED."""
        catalog = [_catalog_row(1, question_text="What is the application name?")]
        sheet   = [_sheet_row(1, "COMPLETELY DIFFERENT TEXT", "BOOLEAN")]

        result = AppSheetAdapter(catalog).parse(sheet)

        assert result.outcome == "QUARANTINED"
        err = [d for d in result.drift if d.drift_type == RowDriftType.CHANGED_QUESTION_TEXT]
        assert len(err) >= 1
        assert err[0].severity == RowDriftSeverity.ERROR


# ---------------------------------------------------------------------------
# 10. 10-row perfect match → VALID with correct candidate count
# ---------------------------------------------------------------------------


class TestPerfectMatch:
    """Complete match between sheet and catalog with populated responses."""

    def test_valid_10_row_catalog_produces_correct_candidates(self) -> None:
        """10 matching rows with non-blank responses → VALID, 10 candidates."""
        catalog = [_catalog_row(n) for n in range(1, 11)]
        sheet = [
            _sheet_row(n, f"Question {n}", "BOOLEAN", "YES")
            for n in range(1, 11)
        ]
        result = AppSheetAdapter(catalog).parse(sheet)

        assert result.outcome == "VALID"
        assert len(result.candidates) == 10
        assert result.catalog_match_count == 10
        assert result.populated_count == 10


# ---------------------------------------------------------------------------
# 13–14. Outcome rules
# ---------------------------------------------------------------------------


class TestOutcomeRules:
    """Outcome is determined solely by whether any ERROR-severity drift exists."""

    def test_drift_free_result_is_valid(self) -> None:
        """No drift at all → outcome == 'VALID'."""
        catalog = [_catalog_row(1)]
        sheet   = [_sheet_row(1, "Question 1", "BOOLEAN", "YES")]
        result  = AppSheetAdapter(catalog).parse(sheet)

        # No ERROR drift is present
        errors = [d for d in result.drift if d.severity == RowDriftSeverity.ERROR]
        assert errors == []
        assert result.outcome == "VALID"

    def test_result_with_errors_is_quarantined(self) -> None:
        """Any ERROR-severity drift → outcome == 'QUARANTINED'."""
        catalog = [_catalog_row(1, response_type="BOOLEAN")]
        sheet   = [_sheet_row(1, "Question 1", "TEXT")]   # type mismatch → ERROR

        result = AppSheetAdapter(catalog).parse(sheet)

        errors = [d for d in result.drift if d.severity == RowDriftSeverity.ERROR]
        assert len(errors) >= 1
        assert result.outcome == "QUARANTINED"

    def test_information_only_drift_does_not_quarantine(self) -> None:
        """INFORMATION-severity drift (blank response) alone keeps outcome VALID."""
        catalog = [_catalog_row(1)]
        sheet   = [_sheet_row(1, "Question 1", "BOOLEAN", "")]  # blank → INFORMATION

        result = AppSheetAdapter(catalog).parse(sheet)

        errors = [d for d in result.drift if d.severity == RowDriftSeverity.ERROR]
        assert errors == []
        assert result.outcome == "VALID"
