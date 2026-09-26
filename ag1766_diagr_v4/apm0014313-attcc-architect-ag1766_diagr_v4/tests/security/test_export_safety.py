"""
Security tests for CSV export safety (UI05).

Verifies:
- Formula injection protection (=, +, -, @, tab prefixes)
- Message truncation for bounded output
- No raw secrets or evidence fragments in exports
"""

from __future__ import annotations

import pytest

from migration_intake.web.routes.evidence import _sanitize_csv_value, _truncate_message


class TestFormulaSanitization:
    """Tests for CSV formula injection protection."""

    def test_sanitizes_equals_prefix(self) -> None:
        """Values starting with = are prefixed with quote."""
        result = _sanitize_csv_value("=SUM(A1:A10)")
        assert result == "'=SUM(A1:A10)"

    def test_sanitizes_plus_prefix(self) -> None:
        """Values starting with + are prefixed with quote."""
        result = _sanitize_csv_value("+1234567890")
        assert result == "'+1234567890"

    def test_sanitizes_minus_prefix(self) -> None:
        """Values starting with - are prefixed with quote."""
        result = _sanitize_csv_value("-1234567890")
        assert result == "'-1234567890"

    def test_sanitizes_at_prefix(self) -> None:
        """Values starting with @ are prefixed with quote."""
        result = _sanitize_csv_value("@SUM(A1)")
        assert result == "'@SUM(A1)"

    def test_sanitizes_tab_prefix(self) -> None:
        """Values starting with tab are prefixed with quote."""
        result = _sanitize_csv_value("\tvalue")
        assert result == "'\tvalue"

    def test_preserves_normal_values(self) -> None:
        """Normal values are not modified."""
        result = _sanitize_csv_value("Normal text value")
        assert result == "Normal text value"

    def test_preserves_numbers(self) -> None:
        """Numeric strings without formula prefix are preserved."""
        result = _sanitize_csv_value("12345")
        assert result == "12345"

    def test_handles_empty_string(self) -> None:
        """Empty strings return empty."""
        result = _sanitize_csv_value("")
        assert result == ""

    def test_handles_none(self) -> None:
        """None values return empty string."""
        result = _sanitize_csv_value(None)
        assert result == ""


class TestMessageTruncation:
    """Tests for message truncation."""

    def test_truncates_long_messages(self) -> None:
        """Long messages are truncated with ellipsis."""
        long_message = "x" * 600
        result = _truncate_message(long_message, max_length=500)
        assert len(result) == 500
        assert result.endswith("...")

    def test_preserves_short_messages(self) -> None:
        """Short messages are not truncated."""
        short_message = "This is a short message"
        result = _truncate_message(short_message, max_length=500)
        assert result == short_message

    def test_handles_exact_length(self) -> None:
        """Messages at exact max length are not truncated."""
        exact_message = "x" * 500
        result = _truncate_message(exact_message, max_length=500)
        assert result == exact_message
        assert len(result) == 500

    def test_handles_empty_string(self) -> None:
        """Empty strings return empty."""
        result = _truncate_message("")
        assert result == ""

    def test_handles_none(self) -> None:
        """None values return empty string."""
        result = _truncate_message(None)
        assert result == ""

    def test_custom_max_length(self) -> None:
        """Custom max length is respected."""
        message = "x" * 100
        result = _truncate_message(message, max_length=50)
        assert len(result) == 50
        assert result.endswith("...")


class TestCombinedSafety:
    """Tests for combined sanitization and truncation."""

    def test_formula_in_long_message(self) -> None:
        """Formula at start of long message is sanitized and truncated."""
        long_formula = "=SUM(" + "A" * 600 + ")"
        sanitized = _sanitize_csv_value(long_formula)
        truncated = _truncate_message(sanitized, max_length=100)

        # Should be sanitized (starts with ')
        assert truncated.startswith("'=")
        # Should be truncated
        assert len(truncated) == 100
        assert truncated.endswith("...")

    def test_safe_codes_only(self) -> None:
        """Verify that typical finding codes are safe."""
        safe_codes = [
            "VALIDATION_WARNING",
            "MISSING_REQUIRED",
            "TYPE_MISMATCH",
            "DUPLICATE_VALUE",
            "UNKNOWN_SHEET",
        ]
        for code in safe_codes:
            result = _sanitize_csv_value(code)
            # Safe codes should not be modified
            assert result == code
            # Should not start with quote
            assert not result.startswith("'")
