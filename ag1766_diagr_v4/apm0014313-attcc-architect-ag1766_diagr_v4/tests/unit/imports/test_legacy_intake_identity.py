"""Tests for legacy intake identity extraction."""
import pytest

from migration_intake.imports.legacy_intake_identity import (
    ExtractedIdentifier,
    consolidate_identifiers_by_type,
    extract_legacy_intake_identifiers,
    get_unique_identifier_value,
    normalize_identifier,
)


class TestNormalizeIdentifier:
    """Identifier normalization policy."""

    def test_removes_hyphens(self) -> None:
        assert normalize_identifier("ABC-123-XYZ") == "abc123xyz"

    def test_removes_spaces(self) -> None:
        assert normalize_identifier("ABC 123 XYZ") == "abc123xyz"

    def test_lowercases(self) -> None:
        assert normalize_identifier("AbC123XyZ") == "abc123xyz"

    def test_removes_special_characters(self) -> None:
        assert normalize_identifier("ABC@123#XYZ!") == "abc123xyz"

    def test_preserves_alphanumeric(self) -> None:
        assert normalize_identifier("abc123xyz") == "abc123xyz"


class TestExtractLegacyIntakeIdentifiers:
    """Identity extraction from App and iTAP sheets."""

    def test_extracts_correlation_from_app_q1(self) -> None:
        app_rows = [
            {
                "No": "1",
                "Question": "What is the application correlation or MOTS ID?",
                "Response_Type": "IDENTIFIER",
                "Response": "CORR-12345",
            }
        ]
        itap_rows = []

        result = extract_legacy_intake_identifiers(app_rows, itap_rows)

        assert len(result) == 1
        assert result[0].identifier_type == "CORRELATION"
        assert result[0].raw_value == "CORR-12345"
        assert result[0].normalized_value == "corr12345"
        assert result[0].source_sheet == "App"
        assert result[0].source_row == 2
        assert result[0].source_column == "D"

    def test_extracts_correlation_from_itap(self) -> None:
        app_rows = []
        itap_rows = [
            ("Correlation ID", "CORR-67890"),
        ]

        result = extract_legacy_intake_identifiers(app_rows, itap_rows)

        assert len(result) == 1
        assert result[0].identifier_type == "CORRELATION"
        assert result[0].raw_value == "CORR-67890"
        assert result[0].normalized_value == "corr67890"
        assert result[0].source_sheet == "iTAP"
        assert result[0].source_row == 2
        assert result[0].source_column == "B"

    def test_extracts_itap_from_apm_number(self) -> None:
        app_rows = []
        itap_rows = [
            ("APM Number", "APM-54321"),
        ]

        result = extract_legacy_intake_identifiers(app_rows, itap_rows)

        assert len(result) == 1
        assert result[0].identifier_type == "ITAP"
        assert result[0].raw_value == "APM-54321"
        assert result[0].normalized_value == "apm54321"

    def test_extracts_mots_from_itap(self) -> None:
        app_rows = []
        itap_rows = [
            ("MOTS ID", "MOTS-99999"),
        ]

        result = extract_legacy_intake_identifiers(app_rows, itap_rows)

        assert len(result) == 1
        assert result[0].identifier_type == "MOTS"
        assert result[0].raw_value == "MOTS-99999"

    def test_extracts_multiple_identifiers(self) -> None:
        app_rows = [
            {
                "No": "1",
                "Question": "What is the application correlation or MOTS ID?",
                "Response_Type": "IDENTIFIER",
                "Response": "CORR-12345",
            }
        ]
        itap_rows = [
            ("Correlation ID", "CORR-12345"),
            ("APM Number", "APM-54321"),
        ]

        result = extract_legacy_intake_identifiers(app_rows, itap_rows)

        assert len(result) == 3
        types = {r.identifier_type for r in result}
        assert types == {"CORRELATION", "ITAP"}

    def test_ignores_blank_responses(self) -> None:
        app_rows = [
            {
                "No": "1",
                "Question": "What is the application correlation or MOTS ID?",
                "Response_Type": "IDENTIFIER",
                "Response": "",
            }
        ]
        itap_rows = [
            ("Correlation ID", ""),
            ("APM Number", ""),
        ]

        result = extract_legacy_intake_identifiers(app_rows, itap_rows)

        assert len(result) == 0

    def test_ignores_non_identifier_questions(self) -> None:
        app_rows = [
            {
                "No": "2",
                "Question": "What is the application name?",
                "Response_Type": "TEXT",
                "Response": "My App",
            }
        ]
        itap_rows = []

        result = extract_legacy_intake_identifiers(app_rows, itap_rows)

        assert len(result) == 0


class TestConsolidateIdentifiersByType:
    """Grouping identifiers by type."""

    def test_groups_by_type(self) -> None:
        identifiers = [
            ExtractedIdentifier("CORRELATION", "C1", "c1", "App", 2, "D", "Q1"),
            ExtractedIdentifier("CORRELATION", "C1", "c1", "iTAP", 5, "B", "Correlation ID"),
            ExtractedIdentifier("ITAP", "I1", "i1", "iTAP", 4, "B", "APM Number"),
        ]

        result = consolidate_identifiers_by_type(identifiers)

        assert set(result.keys()) == {"CORRELATION", "ITAP"}
        assert len(result["CORRELATION"]) == 2
        assert len(result["ITAP"]) == 1


class TestGetUniqueIdentifierValue:
    """Unique value extraction with conflict detection."""

    def test_returns_unique_value(self) -> None:
        identifiers = [
            ExtractedIdentifier("CORRELATION", "CORR-123", "corr123", "App", 2, "D", "Q1"),
            ExtractedIdentifier("CORRELATION", "CORR-123", "corr123", "iTAP", 5, "B", "Correlation ID"),
        ]

        result = get_unique_identifier_value(identifiers)

        assert result == ("CORR-123", "corr123")

    def test_raises_on_conflict(self) -> None:
        identifiers = [
            ExtractedIdentifier("CORRELATION", "CORR-123", "corr123", "App", 2, "D", "Q1"),
            ExtractedIdentifier("CORRELATION", "CORR-456", "corr456", "iTAP", 5, "B", "Correlation ID"),
        ]

        with pytest.raises(ValueError, match="Conflicting CORRELATION identifiers"):
            get_unique_identifier_value(identifiers)

    def test_returns_none_for_empty_list(self) -> None:
        result = get_unique_identifier_value([])

        assert result is None
