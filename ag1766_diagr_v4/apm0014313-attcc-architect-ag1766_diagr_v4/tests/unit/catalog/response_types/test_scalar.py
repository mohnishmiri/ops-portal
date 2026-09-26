"""
Tests for R01 scalar response types.

Tests cover:
- Valid and invalid shapes
- Blank and unknown semantics
- HTML form parsing
- Workbook parsing
- Semantic comparison/no-op detection
- Canonical serialization
"""

from __future__ import annotations

import json
from typing import Any, Dict

import pytest


# =============================================================================
# BooleanType Tests
# =============================================================================


class TestBooleanType:
    """Tests for BOOLEAN response type."""

    def test_boolean_code_is_correct(self) -> None:
        """BooleanType should have correct code."""
        from migration_intake.catalog.response_types.scalar import BooleanType

        t = BooleanType()
        assert t.code == "BOOLEAN"

    def test_boolean_is_not_computed(self) -> None:
        """BooleanType should not be computed."""
        from migration_intake.catalog.response_types.scalar import BooleanType

        t = BooleanType()
        assert t.is_computed is False

    def test_boolean_valid_yes(self) -> None:
        """BooleanType should accept YES."""
        from migration_intake.catalog.response_types.scalar import BooleanType

        t = BooleanType()
        result = t.validate({"value": "YES"})
        assert result.is_valid

    def test_boolean_valid_no(self) -> None:
        """BooleanType should accept NO."""
        from migration_intake.catalog.response_types.scalar import BooleanType

        t = BooleanType()
        result = t.validate({"value": "NO"})
        assert result.is_valid

    def test_boolean_valid_unknown(self) -> None:
        """BooleanType should accept UNKNOWN."""
        from migration_intake.catalog.response_types.scalar import BooleanType

        t = BooleanType()
        result = t.validate({"value": "UNKNOWN"})
        assert result.is_valid

    def test_boolean_invalid_value(self) -> None:
        """BooleanType should reject invalid values."""
        from migration_intake.catalog.response_types.scalar import BooleanType

        t = BooleanType()
        result = t.validate({"value": "MAYBE"})
        assert not result.is_valid
        assert "value" in result.field_errors

    def test_boolean_empty_is_valid(self) -> None:
        """BooleanType should accept empty/null value."""
        from migration_intake.catalog.response_types.scalar import BooleanType

        t = BooleanType()
        assert t.validate({"value": None}).is_valid
        assert t.validate(None).is_valid

    def test_boolean_normalize_uppercase(self) -> None:
        """BooleanType should normalize to uppercase."""
        from migration_intake.catalog.response_types.scalar import BooleanType

        t = BooleanType()
        assert t.normalize({"value": "yes"}) == {"value": "YES"}
        assert t.normalize({"value": "  no  "}) == {"value": "NO"}

    def test_boolean_empty_value(self) -> None:
        """BooleanType should return correct empty value."""
        from migration_intake.catalog.response_types.scalar import BooleanType

        t = BooleanType()
        assert t.empty_value() == {"value": None}

    def test_boolean_unknown_value(self) -> None:
        """BooleanType should return correct unknown value."""
        from migration_intake.catalog.response_types.scalar import BooleanType

        t = BooleanType()
        assert t.unknown_value() == {"value": "UNKNOWN"}

    def test_boolean_parse_form_yes(self) -> None:
        """BooleanType should parse form YES."""
        from migration_intake.catalog.response_types.scalar import BooleanType

        t = BooleanType()
        result = t.parse_form({"value": "YES"})
        assert result.is_success
        assert result.value == {"value": "YES"}

    def test_boolean_parse_form_lowercase(self) -> None:
        """BooleanType should parse form lowercase values."""
        from migration_intake.catalog.response_types.scalar import BooleanType

        t = BooleanType()
        result = t.parse_form({"value": "yes"})
        assert result.is_success
        assert result.value == {"value": "YES"}

    def test_boolean_parse_form_empty(self) -> None:
        """BooleanType should parse form empty as blank."""
        from migration_intake.catalog.response_types.scalar import BooleanType

        t = BooleanType()
        result = t.parse_form({"value": ""})
        assert result.is_success
        assert result.value == {"value": None}

    def test_boolean_parse_form_invalid(self) -> None:
        """BooleanType should reject invalid form values."""
        from migration_intake.catalog.response_types.scalar import BooleanType

        t = BooleanType()
        result = t.parse_form({"value": "MAYBE"})
        assert not result.is_success
        assert len(result.errors) > 0

    def test_boolean_parse_workbook_true(self) -> None:
        """BooleanType should parse workbook True as YES."""
        from migration_intake.catalog.response_types.scalar import BooleanType

        t = BooleanType()
        result = t.parse_workbook(True)
        assert result.is_success
        assert result.value == {"value": "YES"}

    def test_boolean_parse_workbook_false(self) -> None:
        """BooleanType should parse workbook False as NO."""
        from migration_intake.catalog.response_types.scalar import BooleanType

        t = BooleanType()
        result = t.parse_workbook(False)
        assert result.is_success
        assert result.value == {"value": "NO"}

    def test_boolean_parse_workbook_y(self) -> None:
        """BooleanType should parse workbook 'Y' as YES."""
        from migration_intake.catalog.response_types.scalar import BooleanType

        t = BooleanType()
        result = t.parse_workbook("Y")
        assert result.is_success
        assert result.value == {"value": "YES"}

    def test_boolean_parse_workbook_n(self) -> None:
        """BooleanType should parse workbook 'N' as NO."""
        from migration_intake.catalog.response_types.scalar import BooleanType

        t = BooleanType()
        result = t.parse_workbook("N")
        assert result.is_success
        assert result.value == {"value": "NO"}

    def test_boolean_parse_workbook_tbd(self) -> None:
        """BooleanType should parse workbook 'TBD' as UNKNOWN."""
        from migration_intake.catalog.response_types.scalar import BooleanType

        t = BooleanType()
        result = t.parse_workbook("TBD")
        assert result.is_success
        assert result.value == {"value": "UNKNOWN"}

    def test_boolean_parse_workbook_empty(self) -> None:
        """BooleanType should parse workbook empty as blank."""
        from migration_intake.catalog.response_types.scalar import BooleanType

        t = BooleanType()
        result = t.parse_workbook(None)
        assert result.is_success
        assert result.value == {"value": None}

    def test_boolean_compare_equal(self) -> None:
        """BooleanType should detect equal values."""
        from migration_intake.catalog.response_types.scalar import BooleanType

        t = BooleanType()
        result = t.compare({"value": "YES"}, {"value": "YES"})
        assert result.is_equal
        assert result.is_noop

    def test_boolean_compare_different(self) -> None:
        """BooleanType should detect different values."""
        from migration_intake.catalog.response_types.scalar import BooleanType

        t = BooleanType()
        result = t.compare({"value": "YES"}, {"value": "NO"})
        assert not result.is_equal
        assert not result.is_noop
        assert len(result.differences) == 1

    def test_boolean_compare_normalized(self) -> None:
        """BooleanType should compare normalized values."""
        from migration_intake.catalog.response_types.scalar import BooleanType

        t = BooleanType()
        result = t.compare({"value": "yes"}, {"value": "YES"})
        assert result.is_equal

    def test_boolean_serialize_canonical(self) -> None:
        """BooleanType should serialize to canonical JSON."""
        from migration_intake.catalog.response_types.scalar import BooleanType

        t = BooleanType()
        serialized = t.serialize({"value": "YES"})
        assert json.loads(serialized) == {"value": "YES"}


# =============================================================================
# SingleSelectType Tests
# =============================================================================


class TestSingleSelectType:
    """Tests for SINGLE_SELECT response type."""

    def test_single_select_code_is_correct(self) -> None:
        """SingleSelectType should have correct code."""
        from migration_intake.catalog.response_types.scalar import SingleSelectType

        t = SingleSelectType()
        assert t.code == "SINGLE_SELECT"

    def test_single_select_is_not_computed(self) -> None:
        """SingleSelectType should not be computed."""
        from migration_intake.catalog.response_types.scalar import SingleSelectType

        t = SingleSelectType()
        assert t.is_computed is False

    def test_single_select_valid_any_value(self) -> None:
        """SingleSelectType without constraints should accept any value."""
        from migration_intake.catalog.response_types.scalar import SingleSelectType

        t = SingleSelectType()
        result = t.validate({"value": "OPTION_A"})
        assert result.is_valid

    def test_single_select_valid_allowed_value(self) -> None:
        """SingleSelectType should accept allowed values."""
        from migration_intake.catalog.response_types.scalar import SingleSelectType

        t = SingleSelectType(allowed_values=["OPTION_A", "OPTION_B"])
        result = t.validate({"value": "OPTION_A"})
        assert result.is_valid

    def test_single_select_invalid_not_allowed(self) -> None:
        """SingleSelectType should reject values not in allowed list."""
        from migration_intake.catalog.response_types.scalar import SingleSelectType

        t = SingleSelectType(allowed_values=["OPTION_A", "OPTION_B"])
        result = t.validate({"value": "OPTION_C"})
        assert not result.is_valid

    def test_single_select_other_allowed(self) -> None:
        """SingleSelectType should accept OTHER when allowed."""
        from migration_intake.catalog.response_types.scalar import SingleSelectType

        t = SingleSelectType(allowed_values=["OPTION_A"], allow_other=True)
        result = t.validate({"value": "OTHER", "other_text": "Custom option"})
        assert result.is_valid

    def test_single_select_other_requires_text(self) -> None:
        """SingleSelectType should require other_text when OTHER selected."""
        from migration_intake.catalog.response_types.scalar import SingleSelectType

        t = SingleSelectType(allowed_values=["OPTION_A"], allow_other=True)
        result = t.validate({"value": "OTHER"})
        assert not result.is_valid
        assert "other_text" in result.field_errors

    def test_single_select_other_text_only_with_other(self) -> None:
        """SingleSelectType should reject other_text without OTHER value."""
        from migration_intake.catalog.response_types.scalar import SingleSelectType

        t = SingleSelectType(allowed_values=["OPTION_A"], allow_other=True)
        result = t.validate({"value": "OPTION_A", "other_text": "Should not be here"})
        assert not result.is_valid

    def test_single_select_empty_is_valid(self) -> None:
        """SingleSelectType should accept empty value."""
        from migration_intake.catalog.response_types.scalar import SingleSelectType

        t = SingleSelectType(allowed_values=["OPTION_A"])
        assert t.validate({"value": None}).is_valid
        assert t.validate(None).is_valid

    def test_single_select_normalize_uppercase(self) -> None:
        """SingleSelectType should normalize value to uppercase."""
        from migration_intake.catalog.response_types.scalar import SingleSelectType

        t = SingleSelectType()
        result = t.normalize({"value": "option_a"})
        assert result["value"] == "OPTION_A"

    def test_single_select_normalize_trim_other_text(self) -> None:
        """SingleSelectType should trim other_text."""
        from migration_intake.catalog.response_types.scalar import SingleSelectType

        t = SingleSelectType()
        result = t.normalize({"value": "OTHER", "other_text": "  custom  "})
        assert result["other_text"] == "custom"

    def test_single_select_empty_value(self) -> None:
        """SingleSelectType should return correct empty value."""
        from migration_intake.catalog.response_types.scalar import SingleSelectType

        t = SingleSelectType()
        assert t.empty_value() == {"value": None}

    def test_single_select_unknown_value(self) -> None:
        """SingleSelectType should return correct unknown value."""
        from migration_intake.catalog.response_types.scalar import SingleSelectType

        t = SingleSelectType()
        assert t.unknown_value() == {"value": "UNKNOWN"}

    def test_single_select_parse_form(self) -> None:
        """SingleSelectType should parse form data."""
        from migration_intake.catalog.response_types.scalar import SingleSelectType

        t = SingleSelectType()
        result = t.parse_form({"value": "option_a"})
        assert result.is_success
        assert result.value == {"value": "OPTION_A"}

    def test_single_select_parse_form_with_other(self) -> None:
        """SingleSelectType should parse form data with other_text."""
        from migration_intake.catalog.response_types.scalar import SingleSelectType

        t = SingleSelectType()
        result = t.parse_form({"value": "OTHER", "other_text": "Custom"})
        assert result.is_success
        assert result.value == {"value": "OTHER", "other_text": "Custom"}

    def test_single_select_parse_form_empty(self) -> None:
        """SingleSelectType should parse empty form as blank."""
        from migration_intake.catalog.response_types.scalar import SingleSelectType

        t = SingleSelectType()
        result = t.parse_form({"value": ""})
        assert result.is_success
        assert result.value == {"value": None}

    def test_single_select_parse_workbook(self) -> None:
        """SingleSelectType should parse workbook cell."""
        from migration_intake.catalog.response_types.scalar import SingleSelectType

        t = SingleSelectType()
        result = t.parse_workbook("Option A")
        assert result.is_success
        assert result.value == {"value": "OPTION A"}

    def test_single_select_compare_equal(self) -> None:
        """SingleSelectType should detect equal values."""
        from migration_intake.catalog.response_types.scalar import SingleSelectType

        t = SingleSelectType()
        result = t.compare({"value": "OPTION_A"}, {"value": "OPTION_A"})
        assert result.is_equal

    def test_single_select_compare_different(self) -> None:
        """SingleSelectType should detect different values."""
        from migration_intake.catalog.response_types.scalar import SingleSelectType

        t = SingleSelectType()
        result = t.compare({"value": "OPTION_A"}, {"value": "OPTION_B"})
        assert not result.is_equal

    def test_single_select_compare_other_text_difference(self) -> None:
        """SingleSelectType should detect other_text differences."""
        from migration_intake.catalog.response_types.scalar import SingleSelectType

        t = SingleSelectType()
        result = t.compare(
            {"value": "OTHER", "other_text": "First"},
            {"value": "OTHER", "other_text": "Second"}
        )
        assert not result.is_equal
        assert any(d["field"] == "other_text" for d in result.differences)


# =============================================================================
# TextType Tests
# =============================================================================


class TestTextType:
    """Tests for TEXT response type."""

    def test_text_code_is_correct(self) -> None:
        """TextType should have correct code."""
        from migration_intake.catalog.response_types.scalar import TextType

        t = TextType()
        assert t.code == "TEXT"

    def test_text_is_not_computed(self) -> None:
        """TextType should not be computed."""
        from migration_intake.catalog.response_types.scalar import TextType

        t = TextType()
        assert t.is_computed is False

    def test_text_valid_simple(self) -> None:
        """TextType should accept simple text."""
        from migration_intake.catalog.response_types.scalar import TextType

        t = TextType()
        result = t.validate({"text": "Hello World"})
        assert result.is_valid

    def test_text_valid_empty(self) -> None:
        """TextType should accept empty text."""
        from migration_intake.catalog.response_types.scalar import TextType

        t = TextType()
        assert t.validate({"text": None}).is_valid
        assert t.validate(None).is_valid

    def test_text_invalid_too_long(self) -> None:
        """TextType should reject text exceeding max length."""
        from migration_intake.catalog.response_types.scalar import TextType

        t = TextType(max_length=10)
        result = t.validate({"text": "This is way too long"})
        assert not result.is_valid
        assert "text" in result.field_errors

    def test_text_invalid_too_short(self) -> None:
        """TextType should reject text below min length."""
        from migration_intake.catalog.response_types.scalar import TextType

        t = TextType(min_length=5)
        result = t.validate({"text": "Hi"})
        assert not result.is_valid

    def test_text_invalid_newlines(self) -> None:
        """TextType should reject newlines (single-line only)."""
        from migration_intake.catalog.response_types.scalar import TextType

        t = TextType()
        result = t.validate({"text": "Line 1\nLine 2"})
        assert not result.is_valid

    def test_text_invalid_control_chars(self) -> None:
        """TextType should reject control characters."""
        from migration_intake.catalog.response_types.scalar import TextType

        t = TextType()
        result = t.validate({"text": "Hello\x00World"})
        assert not result.is_valid

    def test_text_pattern_validation(self) -> None:
        """TextType should validate against pattern."""
        from migration_intake.catalog.response_types.scalar import TextType

        t = TextType(pattern=r"^[A-Z]{3}-\d{3}$", pattern_description="Format: XXX-000")
        assert t.validate({"text": "ABC-123"}).is_valid
        assert not t.validate({"text": "invalid"}).is_valid

    def test_text_normalize_trim(self) -> None:
        """TextType should trim whitespace."""
        from migration_intake.catalog.response_types.scalar import TextType

        t = TextType()
        result = t.normalize({"text": "  Hello  "})
        assert result["text"] == "Hello"

    def test_text_empty_value(self) -> None:
        """TextType should return correct empty value."""
        from migration_intake.catalog.response_types.scalar import TextType

        t = TextType()
        assert t.empty_value() == {"text": None}

    def test_text_unknown_value(self) -> None:
        """TextType should return correct unknown value."""
        from migration_intake.catalog.response_types.scalar import TextType

        t = TextType()
        assert t.unknown_value() == {"text": "UNKNOWN"}

    def test_text_parse_form(self) -> None:
        """TextType should parse form data."""
        from migration_intake.catalog.response_types.scalar import TextType

        t = TextType()
        result = t.parse_form({"text": "  Hello World  "})
        assert result.is_success
        assert result.value == {"text": "Hello World"}

    def test_text_parse_form_empty(self) -> None:
        """TextType should parse empty form as blank."""
        from migration_intake.catalog.response_types.scalar import TextType

        t = TextType()
        result = t.parse_form({"text": ""})
        assert result.is_success
        assert result.value == {"text": None}

    def test_text_parse_workbook_string(self) -> None:
        """TextType should parse workbook string."""
        from migration_intake.catalog.response_types.scalar import TextType

        t = TextType()
        result = t.parse_workbook("Hello World")
        assert result.is_success
        assert result.value == {"text": "Hello World"}

    def test_text_parse_workbook_number(self) -> None:
        """TextType should parse workbook number as string."""
        from migration_intake.catalog.response_types.scalar import TextType

        t = TextType()
        result = t.parse_workbook(12345)
        assert result.is_success
        assert result.value == {"text": "12345"}

    def test_text_parse_workbook_float_integer(self) -> None:
        """TextType should parse workbook float with integer value."""
        from migration_intake.catalog.response_types.scalar import TextType

        t = TextType()
        result = t.parse_workbook(123.0)
        assert result.is_success
        assert result.value == {"text": "123"}

    def test_text_compare_equal(self) -> None:
        """TextType should detect equal values."""
        from migration_intake.catalog.response_types.scalar import TextType

        t = TextType()
        result = t.compare({"text": "Hello"}, {"text": "Hello"})
        assert result.is_equal

    def test_text_compare_different(self) -> None:
        """TextType should detect different values."""
        from migration_intake.catalog.response_types.scalar import TextType

        t = TextType()
        result = t.compare({"text": "Hello"}, {"text": "World"})
        assert not result.is_equal

    def test_text_compare_normalized(self) -> None:
        """TextType should compare normalized values."""
        from migration_intake.catalog.response_types.scalar import TextType

        t = TextType()
        result = t.compare({"text": "  Hello  "}, {"text": "Hello"})
        assert result.is_equal

    def test_text_serialize_canonical(self) -> None:
        """TextType should serialize to canonical JSON."""
        from migration_intake.catalog.response_types.scalar import TextType

        t = TextType()
        serialized = t.serialize({"text": "Hello"})
        assert json.loads(serialized) == {"text": "Hello"}


# =============================================================================
# LongTextType Tests
# =============================================================================


class TestLongTextType:
    """Tests for LONG_TEXT response type."""

    def test_long_text_code_is_correct(self) -> None:
        """LongTextType should have correct code."""
        from migration_intake.catalog.response_types.scalar import LongTextType

        t = LongTextType()
        assert t.code == "LONG_TEXT"

    def test_long_text_is_not_computed(self) -> None:
        """LongTextType should not be computed."""
        from migration_intake.catalog.response_types.scalar import LongTextType

        t = LongTextType()
        assert t.is_computed is False

    def test_long_text_valid_simple(self) -> None:
        """LongTextType should accept simple text."""
        from migration_intake.catalog.response_types.scalar import LongTextType

        t = LongTextType()
        result = t.validate({"text": "Hello World"})
        assert result.is_valid

    def test_long_text_valid_multiline(self) -> None:
        """LongTextType should accept multiline text."""
        from migration_intake.catalog.response_types.scalar import LongTextType

        t = LongTextType()
        result = t.validate({"text": "Line 1\nLine 2\nLine 3"})
        assert result.is_valid

    def test_long_text_valid_empty(self) -> None:
        """LongTextType should accept empty text."""
        from migration_intake.catalog.response_types.scalar import LongTextType

        t = LongTextType()
        assert t.validate({"text": None}).is_valid
        assert t.validate(None).is_valid

    def test_long_text_invalid_too_long(self) -> None:
        """LongTextType should reject text exceeding max length."""
        from migration_intake.catalog.response_types.scalar import LongTextType

        t = LongTextType(max_length=10)
        result = t.validate({"text": "This is way too long"})
        assert not result.is_valid

    def test_long_text_invalid_control_chars(self) -> None:
        """LongTextType should reject control characters."""
        from migration_intake.catalog.response_types.scalar import LongTextType

        t = LongTextType()
        result = t.validate({"text": "Hello\x00World"})
        assert not result.is_valid

    def test_long_text_normalize_trim(self) -> None:
        """LongTextType should trim whitespace."""
        from migration_intake.catalog.response_types.scalar import LongTextType

        t = LongTextType()
        result = t.normalize({"text": "  Hello  "})
        assert result["text"] == "Hello"

    def test_long_text_normalize_line_endings(self) -> None:
        """LongTextType should normalize line endings to LF."""
        from migration_intake.catalog.response_types.scalar import LongTextType

        t = LongTextType()
        result = t.normalize({"text": "Line 1\r\nLine 2\rLine 3"})
        assert result["text"] == "Line 1\nLine 2\nLine 3"

    def test_long_text_empty_value(self) -> None:
        """LongTextType should return correct empty value."""
        from migration_intake.catalog.response_types.scalar import LongTextType

        t = LongTextType()
        assert t.empty_value() == {"text": None}

    def test_long_text_unknown_value(self) -> None:
        """LongTextType should return correct unknown value."""
        from migration_intake.catalog.response_types.scalar import LongTextType

        t = LongTextType()
        assert t.unknown_value() == {"text": "UNKNOWN"}

    def test_long_text_parse_form(self) -> None:
        """LongTextType should parse form data."""
        from migration_intake.catalog.response_types.scalar import LongTextType

        t = LongTextType()
        result = t.parse_form({"text": "Line 1\r\nLine 2"})
        assert result.is_success
        assert result.value == {"text": "Line 1\nLine 2"}

    def test_long_text_parse_form_empty(self) -> None:
        """LongTextType should parse empty form as blank."""
        from migration_intake.catalog.response_types.scalar import LongTextType

        t = LongTextType()
        result = t.parse_form({"text": ""})
        assert result.is_success
        assert result.value == {"text": None}

    def test_long_text_parse_workbook(self) -> None:
        """LongTextType should parse workbook cell."""
        from migration_intake.catalog.response_types.scalar import LongTextType

        t = LongTextType()
        result = t.parse_workbook("Line 1\nLine 2")
        assert result.is_success
        assert result.value == {"text": "Line 1\nLine 2"}

    def test_long_text_compare_equal(self) -> None:
        """LongTextType should detect equal values."""
        from migration_intake.catalog.response_types.scalar import LongTextType

        t = LongTextType()
        result = t.compare({"text": "Hello\nWorld"}, {"text": "Hello\nWorld"})
        assert result.is_equal

    def test_long_text_compare_different(self) -> None:
        """LongTextType should detect different values."""
        from migration_intake.catalog.response_types.scalar import LongTextType

        t = LongTextType()
        result = t.compare({"text": "Hello"}, {"text": "World"})
        assert not result.is_equal

    def test_long_text_compare_normalized_line_endings(self) -> None:
        """LongTextType should compare with normalized line endings."""
        from migration_intake.catalog.response_types.scalar import LongTextType

        t = LongTextType()
        result = t.compare({"text": "Hello\r\nWorld"}, {"text": "Hello\nWorld"})
        assert result.is_equal


# =============================================================================
# IdentifierType Tests
# =============================================================================


class TestIdentifierType:
    """Tests for IDENTIFIER response type."""

    def test_identifier_code_is_correct(self) -> None:
        """IdentifierType should have correct code."""
        from migration_intake.catalog.response_types.scalar import IdentifierType

        t = IdentifierType()
        assert t.code == "IDENTIFIER"

    def test_identifier_is_not_computed(self) -> None:
        """IdentifierType should not be computed."""
        from migration_intake.catalog.response_types.scalar import IdentifierType

        t = IdentifierType()
        assert t.is_computed is False

    def test_identifier_valid_correlation_id(self) -> None:
        """IdentifierType should accept CORRELATION_ID."""
        from migration_intake.catalog.response_types.scalar import IdentifierType

        t = IdentifierType()
        result = t.validate({
            "identifier_type": "CORRELATION_ID",
            "value": "8375",
            "normalized_value": "8375"
        })
        assert result.is_valid

    def test_identifier_valid_mots_id(self) -> None:
        """IdentifierType should accept MOTS_ID."""
        from migration_intake.catalog.response_types.scalar import IdentifierType

        t = IdentifierType()
        result = t.validate({
            "identifier_type": "MOTS_ID",
            "value": "MOTS-12345",
            "normalized_value": "MOTS-12345"
        })
        assert result.is_valid

    def test_identifier_valid_itap_id(self) -> None:
        """IdentifierType should accept ITAP_ID."""
        from migration_intake.catalog.response_types.scalar import IdentifierType

        t = IdentifierType()
        result = t.validate({
            "identifier_type": "ITAP_ID",
            "value": "ITAP-99999",
            "normalized_value": "ITAP-99999"
        })
        assert result.is_valid

    def test_identifier_valid_other(self) -> None:
        """IdentifierType should accept OTHER type."""
        from migration_intake.catalog.response_types.scalar import IdentifierType

        t = IdentifierType()
        result = t.validate({
            "identifier_type": "OTHER",
            "value": "custom-id",
            "normalized_value": "CUSTOM-ID"
        })
        assert result.is_valid

    def test_identifier_invalid_type(self) -> None:
        """IdentifierType should reject invalid identifier_type."""
        from migration_intake.catalog.response_types.scalar import IdentifierType

        t = IdentifierType()
        result = t.validate({
            "identifier_type": "INVALID_TYPE",
            "value": "123"
        })
        assert not result.is_valid
        assert "identifier_type" in result.field_errors

    def test_identifier_requires_both_type_and_value(self) -> None:
        """IdentifierType should require both type and value."""
        from migration_intake.catalog.response_types.scalar import IdentifierType

        t = IdentifierType()

        # Type without value
        result = t.validate({"identifier_type": "CORRELATION_ID"})
        assert not result.is_valid
        assert "value" in result.field_errors

        # Value without type
        result = t.validate({"value": "123"})
        assert not result.is_valid
        assert "identifier_type" in result.field_errors

    def test_identifier_empty_value_not_allowed(self) -> None:
        """IdentifierType should reject empty value string."""
        from migration_intake.catalog.response_types.scalar import IdentifierType

        t = IdentifierType()
        result = t.validate({
            "identifier_type": "CORRELATION_ID",
            "value": "   "
        })
        assert not result.is_valid

    def test_identifier_valid_empty(self) -> None:
        """IdentifierType should accept fully empty value."""
        from migration_intake.catalog.response_types.scalar import IdentifierType

        t = IdentifierType()
        assert t.validate({"identifier_type": None, "value": None}).is_valid
        assert t.validate(None).is_valid

    def test_identifier_normalize_computes_normalized_value(self) -> None:
        """IdentifierType should compute normalized_value."""
        from migration_intake.catalog.response_types.scalar import IdentifierType

        t = IdentifierType()
        result = t.normalize({
            "identifier_type": "correlation_id",
            "value": "  abc-123  "
        })
        assert result["identifier_type"] == "CORRELATION_ID"
        assert result["value"] == "abc-123"
        assert result["normalized_value"] == "ABC-123"

    def test_identifier_empty_value_method(self) -> None:
        """IdentifierType should return correct empty value."""
        from migration_intake.catalog.response_types.scalar import IdentifierType

        t = IdentifierType()
        assert t.empty_value() == {
            "identifier_type": None,
            "value": None,
            "normalized_value": None
        }

    def test_identifier_unknown_value(self) -> None:
        """IdentifierType should return correct unknown value."""
        from migration_intake.catalog.response_types.scalar import IdentifierType

        t = IdentifierType()
        unknown = t.unknown_value()
        assert unknown["identifier_type"] == "OTHER"
        assert unknown["value"] == "UNKNOWN"

    def test_identifier_parse_form(self) -> None:
        """IdentifierType should parse form data."""
        from migration_intake.catalog.response_types.scalar import IdentifierType

        t = IdentifierType()
        result = t.parse_form({
            "identifier_type": "CORRELATION_ID",
            "value": "8375"
        })
        assert result.is_success
        assert result.value["identifier_type"] == "CORRELATION_ID"
        assert result.value["value"] == "8375"
        assert result.value["normalized_value"] == "8375"

    def test_identifier_parse_form_empty(self) -> None:
        """IdentifierType should parse empty form as blank."""
        from migration_intake.catalog.response_types.scalar import IdentifierType

        t = IdentifierType()
        result = t.parse_form({"identifier_type": "", "value": ""})
        assert result.is_success
        assert result.value == {
            "identifier_type": None,
            "value": None,
            "normalized_value": None
        }

    def test_identifier_parse_form_invalid_type(self) -> None:
        """IdentifierType should reject invalid type in form."""
        from migration_intake.catalog.response_types.scalar import IdentifierType

        t = IdentifierType()
        result = t.parse_form({
            "identifier_type": "INVALID",
            "value": "123"
        })
        assert not result.is_success

    def test_identifier_parse_workbook_with_context(self) -> None:
        """IdentifierType should parse workbook with context."""
        from migration_intake.catalog.response_types.scalar import IdentifierType

        t = IdentifierType()
        result = t.parse_workbook("8375", context={"identifier_type": "CORRELATION_ID"})
        assert result.is_success
        assert result.value["identifier_type"] == "CORRELATION_ID"
        assert result.value["value"] == "8375"

    def test_identifier_parse_workbook_without_context(self) -> None:
        """IdentifierType should default to OTHER without context."""
        from migration_intake.catalog.response_types.scalar import IdentifierType

        t = IdentifierType()
        result = t.parse_workbook("custom-123")
        assert result.is_success
        assert result.value["identifier_type"] == "OTHER"
        assert len(result.warnings) > 0

    def test_identifier_parse_workbook_numeric(self) -> None:
        """IdentifierType should parse numeric workbook values."""
        from migration_intake.catalog.response_types.scalar import IdentifierType

        t = IdentifierType()
        result = t.parse_workbook(12345, context={"identifier_type": "CORRELATION_ID"})
        assert result.is_success
        assert result.value["value"] == "12345"

    def test_identifier_compare_equal(self) -> None:
        """IdentifierType should detect equal values."""
        from migration_intake.catalog.response_types.scalar import IdentifierType

        t = IdentifierType()
        result = t.compare(
            {"identifier_type": "CORRELATION_ID", "value": "123", "normalized_value": "123"},
            {"identifier_type": "CORRELATION_ID", "value": "123", "normalized_value": "123"}
        )
        assert result.is_equal

    def test_identifier_compare_different_type(self) -> None:
        """IdentifierType should detect different identifier_type."""
        from migration_intake.catalog.response_types.scalar import IdentifierType

        t = IdentifierType()
        result = t.compare(
            {"identifier_type": "CORRELATION_ID", "value": "123", "normalized_value": "123"},
            {"identifier_type": "MOTS_ID", "value": "123", "normalized_value": "123"}
        )
        assert not result.is_equal
        assert any(d["field"] == "identifier_type" for d in result.differences)

    def test_identifier_compare_different_value(self) -> None:
        """IdentifierType should detect different value."""
        from migration_intake.catalog.response_types.scalar import IdentifierType

        t = IdentifierType()
        result = t.compare(
            {"identifier_type": "CORRELATION_ID", "value": "123", "normalized_value": "123"},
            {"identifier_type": "CORRELATION_ID", "value": "456", "normalized_value": "456"}
        )
        assert not result.is_equal

    def test_identifier_serialize_canonical(self) -> None:
        """IdentifierType should serialize to canonical JSON."""
        from migration_intake.catalog.response_types.scalar import IdentifierType

        t = IdentifierType()
        value = {
            "identifier_type": "CORRELATION_ID",
            "value": "8375",
            "normalized_value": "8375"
        }
        serialized = t.serialize(value)
        parsed = json.loads(serialized)
        assert parsed == value


# =============================================================================
# Integration Tests
# =============================================================================


class TestScalarTypesIntegration:
    """Integration tests for scalar types."""

    def test_all_scalar_types_have_required_attributes(self) -> None:
        """All scalar types should have required attributes."""
        from migration_intake.catalog.response_types.scalar import (
            BooleanType,
            IdentifierType,
            LongTextType,
            SingleSelectType,
            TextType,
        )

        types = [
            BooleanType(),
            SingleSelectType(),
            TextType(),
            LongTextType(),
            IdentifierType(),
        ]

        for t in types:
            assert hasattr(t, "code")
            assert hasattr(t, "schema_version")
            assert hasattr(t, "editor_key")
            assert hasattr(t, "display_key")
            assert hasattr(t, "is_computed")
            assert t.is_computed is False

    def test_all_scalar_types_implement_required_methods(self) -> None:
        """All scalar types should implement required methods."""
        from migration_intake.catalog.response_types.scalar import (
            BooleanType,
            IdentifierType,
            LongTextType,
            SingleSelectType,
            TextType,
        )

        types = [
            BooleanType(),
            SingleSelectType(),
            TextType(),
            LongTextType(),
            IdentifierType(),
        ]

        for t in types:
            # All should have these methods
            assert callable(getattr(t, "validate", None))
            assert callable(getattr(t, "normalize", None))
            assert callable(getattr(t, "compare", None))
            assert callable(getattr(t, "serialize", None))
            assert callable(getattr(t, "deserialize", None))
            assert callable(getattr(t, "parse_form", None))
            assert callable(getattr(t, "parse_workbook", None))
            assert callable(getattr(t, "empty_value", None))
            assert callable(getattr(t, "unknown_value", None))

    def test_all_scalar_types_have_unique_codes(self) -> None:
        """All scalar types should have unique codes."""
        from migration_intake.catalog.response_types.scalar import (
            BooleanType,
            IdentifierType,
            LongTextType,
            SingleSelectType,
            TextType,
        )

        types = [
            BooleanType(),
            SingleSelectType(),
            TextType(),
            LongTextType(),
            IdentifierType(),
        ]

        codes = [t.code for t in types]
        assert len(codes) == len(set(codes)), "Duplicate codes found"

    def test_scalar_types_can_register_with_registry(self) -> None:
        """All scalar types should be registrable."""
        from migration_intake.catalog.response_types.registry import ResponseTypeRegistry
        from migration_intake.catalog.response_types.scalar import (
            BooleanType,
            IdentifierType,
            LongTextType,
            SingleSelectType,
            TextType,
        )

        registry = ResponseTypeRegistry()

        registry.register(BooleanType())
        registry.register(SingleSelectType())
        registry.register(TextType())
        registry.register(LongTextType())
        registry.register(IdentifierType())

        assert registry.count() == 5
        assert registry.get("BOOLEAN") is not None
        assert registry.get("SINGLE_SELECT") is not None
        assert registry.get("TEXT") is not None
        assert registry.get("LONG_TEXT") is not None
        assert registry.get("IDENTIFIER") is not None

    def test_scalar_types_roundtrip_serialization(self) -> None:
        """All scalar types should support serialize/deserialize roundtrip."""
        from migration_intake.catalog.response_types.scalar import (
            BooleanType,
            IdentifierType,
            LongTextType,
            SingleSelectType,
            TextType,
        )

        test_cases = [
            (BooleanType(), {"value": "YES"}),
            (SingleSelectType(), {"value": "OPTION_A", "other_text": "detail"}),
            (TextType(), {"text": "Hello World"}),
            (LongTextType(), {"text": "Line 1\nLine 2"}),
            (IdentifierType(), {"identifier_type": "CORRELATION_ID", "value": "123", "normalized_value": "123"}),
        ]

        for response_type, value in test_cases:
            serialized = response_type.serialize(value)
            deserialized = response_type.deserialize(serialized)
            assert deserialized == value, f"Roundtrip failed for {response_type.code}"
