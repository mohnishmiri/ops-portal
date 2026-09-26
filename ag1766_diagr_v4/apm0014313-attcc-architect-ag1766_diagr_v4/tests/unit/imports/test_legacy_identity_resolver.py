"""Tests for legacy intake identity resolution with precedence."""
import pytest

from migration_intake.imports.legacy_identity_resolver import (
    LegacyIdentityResolution,
    resolve_legacy_intake_identity,
)
from migration_intake.imports.legacy_intake_identity import ExtractedIdentifier
from migration_intake.imports.source_identity import IdentityDecision


class TestResolveLegacyIntakeIdentity:
    """Identity resolution with precedence and cross-ID consistency."""

    def test_correlation_only_matches(self) -> None:
        extracted = [
            ExtractedIdentifier("CORRELATION", "CORR-123", "corr123", "App", 2, "D", "Q1"),
        ]
        app_identifiers = [
            ("app-uuid-1", "CORRELATION", "CORR-123"),
        ]

        result = resolve_legacy_intake_identity(
            extracted_identifiers=extracted,
            application_identifiers=app_identifiers,
        )

        assert result.outcome == IdentityDecision.MATCHED
        assert result.selected_identifier_type == "CORRELATION"
        assert result.selected_raw_value == "CORR-123"
        assert result.selected_normalized_value == "corr123"
        assert result.matched_application_ids == ("app-uuid-1",)

    def test_mots_fallback_when_correlation_absent(self) -> None:
        extracted = [
            ExtractedIdentifier("MOTS", "MOTS-456", "mots456", "iTAP", 3, "B", "MOTS ID"),
        ]
        app_identifiers = [
            ("app-uuid-2", "MOTS", "MOTS-456"),
        ]

        result = resolve_legacy_intake_identity(
            extracted_identifiers=extracted,
            application_identifiers=app_identifiers,
        )

        assert result.outcome == IdentityDecision.MATCHED
        assert result.selected_identifier_type == "MOTS"
        assert result.selected_raw_value == "MOTS-456"

    def test_itap_fallback_when_both_higher_priority_absent(self) -> None:
        extracted = [
            ExtractedIdentifier("ITAP", "APM-789", "apm789", "iTAP", 4, "B", "APM Number"),
        ]
        app_identifiers = [
            ("app-uuid-3", "ITAP", "APM-789"),
        ]

        result = resolve_legacy_intake_identity(
            extracted_identifiers=extracted,
            application_identifiers=app_identifiers,
        )

        assert result.outcome == IdentityDecision.MATCHED
        assert result.selected_identifier_type == "ITAP"

    def test_correlation_preferred_over_mots(self) -> None:
        """When both Correlation and MOTS are present, Correlation is used."""
        extracted = [
            ExtractedIdentifier("CORRELATION", "CORR-123", "corr123", "App", 2, "D", "Q1"),
            ExtractedIdentifier("MOTS", "MOTS-456", "mots456", "iTAP", 3, "B", "MOTS ID"),
        ]
        app_identifiers = [
            ("app-uuid-1", "CORRELATION", "CORR-123"),
            ("app-uuid-1", "MOTS", "MOTS-456"),
        ]

        result = resolve_legacy_intake_identity(
            extracted_identifiers=extracted,
            application_identifiers=app_identifiers,
        )

        assert result.outcome == IdentityDecision.MATCHED
        assert result.selected_identifier_type == "CORRELATION"
        assert result.selected_raw_value == "CORR-123"

    def test_correlation_preferred_over_itap(self) -> None:
        extracted = [
            ExtractedIdentifier("CORRELATION", "CORR-123", "corr123", "App", 2, "D", "Q1"),
            ExtractedIdentifier("ITAP", "APM-789", "apm789", "iTAP", 4, "B", "APM Number"),
        ]
        app_identifiers = [
            ("app-uuid-1", "CORRELATION", "CORR-123"),
            ("app-uuid-1", "ITAP", "APM-789"),
        ]

        result = resolve_legacy_intake_identity(
            extracted_identifiers=extracted,
            application_identifiers=app_identifiers,
        )

        assert result.selected_identifier_type == "CORRELATION"

    def test_missing_identifier(self) -> None:
        extracted = []
        app_identifiers = []

        result = resolve_legacy_intake_identity(
            extracted_identifiers=extracted,
            application_identifiers=app_identifiers,
        )

        assert result.outcome == IdentityDecision.MISSING
        assert result.selected_identifier_type is None

    def test_unknown_identifier(self) -> None:
        """Identifier not registered on any application."""
        extracted = [
            ExtractedIdentifier("CORRELATION", "CORR-999", "corr999", "App", 2, "D", "Q1"),
        ]
        app_identifiers = [
            ("app-uuid-1", "CORRELATION", "CORR-123"),
        ]

        result = resolve_legacy_intake_identity(
            extracted_identifiers=extracted,
            application_identifiers=app_identifiers,
        )

        assert result.outcome == IdentityDecision.MISMATCH

    def test_selected_application_mismatch_reports_matching_application(self) -> None:
        """A workbook matched to another application retains that match for recovery UI."""
        extracted = [
            ExtractedIdentifier("CORRELATION", "CORR-123", "corr123", "App", 2, "D", "Q1"),
        ]
        app_identifiers = [
            ("app-uuid-1", "CORRELATION", "CORR-123"),
        ]

        result = resolve_legacy_intake_identity(
            extracted_identifiers=extracted,
            application_identifiers=app_identifiers,
            selected_application_id="app-uuid-2",
        )

        assert result.outcome == IdentityDecision.MISMATCH
        assert result.matched_application_ids == ("app-uuid-1",)

    def test_ambiguous_identifier(self) -> None:
        """Same identifier registered on multiple applications."""
        extracted = [
            ExtractedIdentifier("CORRELATION", "CORR-123", "corr123", "App", 2, "D", "Q1"),
        ]
        app_identifiers = [
            ("app-uuid-1", "CORRELATION", "CORR-123"),
            ("app-uuid-2", "CORRELATION", "CORR-123"),
        ]

        result = resolve_legacy_intake_identity(
            extracted_identifiers=extracted,
            application_identifiers=app_identifiers,
        )

        assert result.outcome == IdentityDecision.AMBIGUOUS
        assert len(result.matched_application_ids) == 2

    def test_selected_application_mismatch(self) -> None:
        """Matched application doesn't equal the selected application."""
        extracted = [
            ExtractedIdentifier("CORRELATION", "CORR-123", "corr123", "App", 2, "D", "Q1"),
        ]
        app_identifiers = [
            ("app-uuid-1", "CORRELATION", "CORR-123"),
        ]

        result = resolve_legacy_intake_identity(
            extracted_identifiers=extracted,
            application_identifiers=app_identifiers,
            selected_application_id="app-uuid-2",  # Different app
        )

        assert result.outcome == IdentityDecision.MISMATCH

    def test_conflicting_values_of_same_type(self) -> None:
        """Two different Correlation IDs in the workbook."""
        extracted = [
            ExtractedIdentifier("CORRELATION", "CORR-123", "corr123", "App", 2, "D", "Q1"),
            ExtractedIdentifier("CORRELATION", "CORR-456", "corr456", "iTAP", 5, "B", "Correlation ID"),
        ]
        app_identifiers = []

        result = resolve_legacy_intake_identity(
            extracted_identifiers=extracted,
            application_identifiers=app_identifiers,
        )

        assert result.outcome == IdentityDecision.SOURCE_CONFLICT
        assert "Conflicting CORRELATION identifiers" in result.conflict_detail

    def test_cross_id_consistency_success(self) -> None:
        """All supplied IDs resolve to the same application."""
        extracted = [
            ExtractedIdentifier("CORRELATION", "CORR-123", "corr123", "App", 2, "D", "Q1"),
            ExtractedIdentifier("MOTS", "MOTS-456", "mots456", "iTAP", 3, "B", "MOTS ID"),
            ExtractedIdentifier("ITAP", "APM-789", "apm789", "iTAP", 4, "B", "APM Number"),
        ]
        app_identifiers = [
            ("app-uuid-1", "CORRELATION", "CORR-123"),
            ("app-uuid-1", "MOTS", "MOTS-456"),
            ("app-uuid-1", "ITAP", "APM-789"),
        ]

        result = resolve_legacy_intake_identity(
            extracted_identifiers=extracted,
            application_identifiers=app_identifiers,
        )

        assert result.outcome == IdentityDecision.MATCHED
        assert result.selected_identifier_type == "CORRELATION"  # Precedence
        assert result.matched_application_ids == ("app-uuid-1",)

    def test_cross_id_consistency_failure(self) -> None:
        """Correlation matches app-1, but MOTS matches app-2."""
        extracted = [
            ExtractedIdentifier("CORRELATION", "CORR-123", "corr123", "App", 2, "D", "Q1"),
            ExtractedIdentifier("MOTS", "MOTS-456", "mots456", "iTAP", 3, "B", "MOTS ID"),
        ]
        app_identifiers = [
            ("app-uuid-1", "CORRELATION", "CORR-123"),
            ("app-uuid-2", "MOTS", "MOTS-456"),  # Different app!
        ]

        result = resolve_legacy_intake_identity(
            extracted_identifiers=extracted,
            application_identifiers=app_identifiers,
        )

        assert result.outcome == IdentityDecision.SOURCE_CONFLICT
        assert "MOTS identifier resolves to different application" in result.conflict_detail

    def test_ignores_unregistered_lower_priority_id(self) -> None:
        """Correlation matches, MOTS is not registered anywhere - should still succeed."""
        extracted = [
            ExtractedIdentifier("CORRELATION", "CORR-123", "corr123", "App", 2, "D", "Q1"),
            ExtractedIdentifier("MOTS", "MOTS-999", "mots999", "iTAP", 3, "B", "MOTS ID"),
        ]
        app_identifiers = [
            ("app-uuid-1", "CORRELATION", "CORR-123"),
            # MOTS-999 is not registered anywhere
        ]

        result = resolve_legacy_intake_identity(
            extracted_identifiers=extracted,
            application_identifiers=app_identifiers,
        )

        # Should succeed because unregistered IDs don't conflict
        assert result.outcome == IdentityDecision.MATCHED
        assert result.selected_identifier_type == "CORRELATION"

    def test_preserves_all_extracted_identifiers(self) -> None:
        """All extracted identifiers are preserved in the result."""
        extracted = [
            ExtractedIdentifier("CORRELATION", "CORR-123", "corr123", "App", 2, "D", "Q1"),
            ExtractedIdentifier("MOTS", "MOTS-456", "mots456", "iTAP", 3, "B", "MOTS ID"),
        ]
        app_identifiers = [
            ("app-uuid-1", "CORRELATION", "CORR-123"),
        ]

        result = resolve_legacy_intake_identity(
            extracted_identifiers=extracted,
            application_identifiers=app_identifiers,
        )

        assert len(result.all_extracted_identifiers) == 2
        assert result.all_extracted_identifiers[0].identifier_type == "CORRELATION"
        assert result.all_extracted_identifiers[1].identifier_type == "MOTS"
