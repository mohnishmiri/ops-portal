"""
Tests for collection response types (R02).

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

from migration_intake.catalog.response_types.base import (
    ComparisonResult,
    ParseResult,
    ResponseTypeCodes,
    ValidationResult,
)
from migration_intake.catalog.response_types.collections import (
    ControlledPairType,
    CountPairType,
    MultiSelectType,
    PeopleListType,
    TextPairType,
)


class TestMultiSelectType:
    """Tests for MULTI_SELECT response type."""

    def test_code_is_multi_select(self) -> None:
        """MultiSelectType should have MULTI_SELECT code."""
        t = MultiSelectType()
        assert t.code == ResponseTypeCodes.MULTI_SELECT

    def test_is_not_computed(self) -> None:
        """MultiSelectType should not be computed."""
        t = MultiSelectType()
        assert t.is_computed is False

    def test_has_editor_and_display_keys(self) -> None:
        """MultiSelectType should have editor and display keys."""
        t = MultiSelectType()
        assert t.editor_key == "multi_select_editor"
        assert t.display_key == "multi_select_display"

    # Valid shapes
    def test_validate_valid_single_value(self) -> None:
        """Valid single selection should pass validation."""
        t = MultiSelectType()
        result = t.validate({"values": ["CODE1"]})
        assert result.is_valid

    def test_validate_valid_multiple_values(self) -> None:
        """Valid multiple selections should pass validation."""
        t = MultiSelectType()
        result = t.validate({"values": ["CODE1", "CODE2", "CODE3"]})
        assert result.is_valid

    def test_validate_empty_values_list(self) -> None:
        """Empty values list should be valid."""
        t = MultiSelectType()
        result = t.validate({"values": []})
        assert result.is_valid

    def test_validate_with_other_text(self) -> None:
        """OTHER with other_text should be valid when allowed."""
        t = MultiSelectType(other_allowed=True)
        result = t.validate({"values": ["OTHER"], "other_text": "Custom option"})
        assert result.is_valid

    # Invalid shapes
    def test_validate_missing_values_field(self) -> None:
        """Missing values field should fail validation."""
        t = MultiSelectType()
        result = t.validate({})
        assert not result.is_valid
        assert "values" in str(result.errors)

    def test_validate_values_not_list(self) -> None:
        """Non-list values should fail validation."""
        t = MultiSelectType()
        result = t.validate({"values": "CODE1"})
        assert not result.is_valid

    def test_validate_non_string_values(self) -> None:
        """Non-string items in values should fail validation."""
        t = MultiSelectType()
        result = t.validate({"values": [123, "CODE1"]})
        assert not result.is_valid

    def test_validate_none_exclusivity(self) -> None:
        """NONE with other values should fail when none_exclusive is True."""
        t = MultiSelectType(none_exclusive=True)
        result = t.validate({"values": ["NONE", "CODE1"]})
        assert not result.is_valid
        assert "NONE" in str(result.errors)

    def test_validate_none_alone_is_valid(self) -> None:
        """NONE alone should be valid."""
        t = MultiSelectType(none_exclusive=True)
        result = t.validate({"values": ["NONE"]})
        assert result.is_valid

    def test_validate_other_without_text(self) -> None:
        """OTHER without other_text should fail when other_allowed."""
        t = MultiSelectType(other_allowed=True)
        result = t.validate({"values": ["OTHER"]})
        assert not result.is_valid
        assert "other_text" in str(result.errors)

    def test_validate_other_not_allowed(self) -> None:
        """OTHER should fail when other_allowed is False."""
        t = MultiSelectType(other_allowed=False)
        result = t.validate({"values": ["OTHER"], "other_text": "Custom"})
        assert not result.is_valid

    def test_validate_allowed_values(self) -> None:
        """Values not in allowed list should fail."""
        t = MultiSelectType(allowed_values=["A", "B", "C"])
        result = t.validate({"values": ["A", "D"]})
        assert not result.is_valid

    # Normalization
    def test_normalize_case_folds_to_uppercase(self) -> None:
        """Normalization should case-fold codes to uppercase."""
        t = MultiSelectType()
        result = t.normalize({"values": ["code1", "Code2", "CODE3"]})
        assert result["values"] == ["CODE1", "CODE2", "CODE3"]

    def test_normalize_trims_whitespace(self) -> None:
        """Normalization should trim whitespace."""
        t = MultiSelectType()
        result = t.normalize({"values": [" CODE1 ", "CODE2 "]})
        assert result["values"] == ["CODE1", "CODE2"]

    def test_normalize_sorts_values(self) -> None:
        """Normalization should sort values for stable comparison."""
        t = MultiSelectType()
        result = t.normalize({"values": ["C", "A", "B"]})
        assert result["values"] == ["A", "B", "C"]

    def test_normalize_trims_other_text(self) -> None:
        """Normalization should trim other_text whitespace."""
        t = MultiSelectType()
        result = t.normalize({"values": ["OTHER"], "other_text": "  Custom  "})
        assert result["other_text"] == "Custom"

    # Empty and unknown
    def test_empty_value(self) -> None:
        """Empty value should be empty list."""
        t = MultiSelectType()
        empty = t.empty_value()
        assert empty == {"values": []}

    def test_unknown_value(self) -> None:
        """Unknown value should have _unknown marker."""
        t = MultiSelectType()
        unknown = t.unknown_value()
        assert unknown["_unknown"] is True
        assert unknown["values"] == []

    # Form parsing
    def test_parse_form_single_value(self) -> None:
        """Form parsing should handle single value."""
        t = MultiSelectType()
        result = t.parse_form({"values": "CODE1"})
        assert result.is_success
        assert result.value["values"] == ["CODE1"]

    def test_parse_form_multiple_values(self) -> None:
        """Form parsing should handle multiple values."""
        t = MultiSelectType()
        result = t.parse_form({"values": ["CODE1", "CODE2"]})
        assert result.is_success
        assert set(result.value["values"]) == {"CODE1", "CODE2"}

    def test_parse_form_with_other_text(self) -> None:
        """Form parsing should handle other_text."""
        t = MultiSelectType()
        result = t.parse_form({"values": ["OTHER"], "other_text": "Custom"})
        assert result.is_success
        assert result.value["other_text"] == "Custom"

    def test_parse_form_empty_values(self) -> None:
        """Form parsing should handle empty values."""
        t = MultiSelectType()
        result = t.parse_form({"values": []})
        assert result.is_success
        assert result.value["values"] == []

    # Workbook parsing
    def test_parse_workbook_comma_separated(self) -> None:
        """Workbook parsing should handle comma-separated values."""
        t = MultiSelectType()
        result = t.parse_workbook("CODE1, CODE2, CODE3")
        assert result.is_success
        assert set(result.value["values"]) == {"CODE1", "CODE2", "CODE3"}

    def test_parse_workbook_semicolon_separated(self) -> None:
        """Workbook parsing should handle semicolon-separated values."""
        t = MultiSelectType()
        result = t.parse_workbook("CODE1; CODE2; CODE3")
        assert result.is_success
        assert set(result.value["values"]) == {"CODE1", "CODE2", "CODE3"}

    def test_parse_workbook_single_value(self) -> None:
        """Workbook parsing should handle single value."""
        t = MultiSelectType()
        result = t.parse_workbook("CODE1")
        assert result.is_success
        assert result.value["values"] == ["CODE1"]

    def test_parse_workbook_empty(self) -> None:
        """Workbook parsing should handle empty cell."""
        t = MultiSelectType()
        result = t.parse_workbook(None)
        assert result.is_success
        assert result.value["values"] == []

    def test_parse_workbook_other_with_description(self) -> None:
        """Workbook parsing should handle OTHER: description format."""
        t = MultiSelectType()
        result = t.parse_workbook("CODE1, OTHER: Custom option")
        assert result.is_success
        assert "OTHER" in result.value["values"]
        assert result.value["other_text"] == "Custom option"

    # Comparison
    def test_compare_equal_values(self) -> None:
        """Equal values should compare as equal."""
        t = MultiSelectType()
        result = t.compare(
            {"values": ["A", "B"]},
            {"values": ["B", "A"]},  # Different order
        )
        assert result.is_equal
        assert result.is_noop

    def test_compare_different_values(self) -> None:
        """Different values should compare as different."""
        t = MultiSelectType()
        result = t.compare(
            {"values": ["A", "B"]},
            {"values": ["A", "C"]},
        )
        assert not result.is_equal
        assert len(result.differences) > 0

    def test_compare_different_other_text(self) -> None:
        """Different other_text should compare as different."""
        t = MultiSelectType()
        result = t.compare(
            {"values": ["OTHER"], "other_text": "Old"},
            {"values": ["OTHER"], "other_text": "New"},
        )
        assert not result.is_equal

    # Serialization
    def test_serialize_canonical(self) -> None:
        """Serialization should produce canonical JSON."""
        t = MultiSelectType()
        value = {"values": ["B", "A"], "other_text": "Custom"}
        serialized = t.serialize(t.normalize(value))
        # Should be sorted keys
        assert '"other_text"' in serialized
        assert '"values"' in serialized

    def test_deserialize_roundtrip(self) -> None:
        """Deserialization should roundtrip correctly."""
        t = MultiSelectType()
        value = {"values": ["A", "B"]}
        serialized = t.serialize(value)
        deserialized = t.deserialize(serialized)
        assert deserialized == value


class TestTextPairType:
    """Tests for TEXT_PAIR response type."""

    def test_code_is_text_pair(self) -> None:
        """TextPairType should have TEXT_PAIR code."""
        t = TextPairType()
        assert t.code == ResponseTypeCodes.TEXT_PAIR

    def test_is_not_computed(self) -> None:
        """TextPairType should not be computed."""
        t = TextPairType()
        assert t.is_computed is False

    def test_custom_field_names(self) -> None:
        """TextPairType should support custom field names."""
        t = TextPairType(first_field="application_name", second_field="acronym")
        empty = t.empty_value()
        assert "application_name" in empty
        assert "acronym" in empty

    # Valid shapes
    def test_validate_valid_both_fields(self) -> None:
        """Valid text pair with both fields should pass."""
        t = TextPairType(first_field="application_name", second_field="acronym")
        result = t.validate({"application_name": "My App", "acronym": "MA"})
        assert result.is_valid

    def test_validate_valid_one_field(self) -> None:
        """Text pair with one field should pass when not required."""
        t = TextPairType(first_field="application_name", second_field="acronym")
        result = t.validate({"application_name": "My App", "acronym": None})
        assert result.is_valid

    def test_validate_null_value(self) -> None:
        """Null value should be valid when not required."""
        t = TextPairType()
        result = t.validate(None)
        assert result.is_valid

    # Invalid shapes
    def test_validate_required_first_missing(self) -> None:
        """Missing required first field should fail."""
        t = TextPairType(first_field="name", first_required=True)
        result = t.validate({"name": "", "second": "value"})
        assert not result.is_valid
        assert "name" in result.field_errors

    def test_validate_required_second_missing(self) -> None:
        """Missing required second field should fail."""
        t = TextPairType(second_field="acronym", second_required=True)
        result = t.validate({"first": "value", "acronym": None})
        assert not result.is_valid
        assert "acronym" in result.field_errors

    def test_validate_max_length_exceeded(self) -> None:
        """Exceeding max length should fail."""
        t = TextPairType(first_max_length=5)
        result = t.validate({"first": "Too Long Value", "second": "OK"})
        assert not result.is_valid

    # Normalization
    def test_normalize_trims_whitespace(self) -> None:
        """Normalization should trim whitespace."""
        t = TextPairType(first_field="name", second_field="acronym")
        result = t.normalize({"name": "  My App  ", "acronym": " MA "})
        assert result["name"] == "My App"
        assert result["acronym"] == "MA"

    def test_normalize_preserves_null(self) -> None:
        """Normalization should preserve null values."""
        t = TextPairType()
        result = t.normalize({"first": None, "second": "value"})
        assert result["first"] is None
        assert result["second"] == "value"

    # Empty and unknown
    def test_empty_value(self) -> None:
        """Empty value should have null fields."""
        t = TextPairType(first_field="name", second_field="acronym")
        empty = t.empty_value()
        assert empty == {"name": None, "acronym": None}

    def test_unknown_value(self) -> None:
        """Unknown value should have _unknown marker."""
        t = TextPairType()
        unknown = t.unknown_value()
        assert unknown["_unknown"] is True

    # Form parsing
    def test_parse_form_both_fields(self) -> None:
        """Form parsing should handle both fields."""
        t = TextPairType(first_field="name", second_field="acronym")
        result = t.parse_form({"name": "My App", "acronym": "MA"})
        assert result.is_success
        assert result.value["name"] == "My App"
        assert result.value["acronym"] == "MA"

    def test_parse_form_empty_fields(self) -> None:
        """Form parsing should handle empty fields."""
        t = TextPairType()
        result = t.parse_form({"first": "", "second": ""})
        assert result.is_success

    # Workbook parsing
    def test_parse_workbook_pipe_separated(self) -> None:
        """Workbook parsing should handle pipe-separated values."""
        t = TextPairType(first_field="name", second_field="acronym")
        result = t.parse_workbook("My Application | MA")
        assert result.is_success
        assert result.value["name"] == "My Application"
        assert result.value["acronym"] == "MA"

    def test_parse_workbook_single_value(self) -> None:
        """Workbook parsing should handle single value."""
        t = TextPairType()
        result = t.parse_workbook("Single Value")
        assert result.is_success
        assert result.value["first"] == "Single Value"
        assert result.value["second"] is None

    def test_parse_workbook_with_context(self) -> None:
        """Workbook parsing should use context values."""
        t = TextPairType(first_field="name", second_field="acronym")
        result = t.parse_workbook(
            "ignored",
            context={"name": "From Context", "acronym": "FC"}
        )
        assert result.is_success
        assert result.value["name"] == "From Context"

    def test_parse_workbook_empty(self) -> None:
        """Workbook parsing should handle empty cell."""
        t = TextPairType()
        result = t.parse_workbook(None)
        assert result.is_success

    # Comparison
    def test_compare_equal_values(self) -> None:
        """Equal values should compare as equal."""
        t = TextPairType()
        result = t.compare(
            {"first": "Value", "second": "Other"},
            {"first": "Value", "second": "Other"},
        )
        assert result.is_equal
        assert result.is_noop

    def test_compare_different_first(self) -> None:
        """Different first field should compare as different."""
        t = TextPairType()
        result = t.compare(
            {"first": "Old", "second": "Same"},
            {"first": "New", "second": "Same"},
        )
        assert not result.is_equal
        assert any(d["field"] == "first" for d in result.differences)

    def test_compare_whitespace_normalized(self) -> None:
        """Comparison should normalize whitespace."""
        t = TextPairType()
        result = t.compare(
            {"first": "  Value  ", "second": "Other"},
            {"first": "Value", "second": "Other"},
        )
        assert result.is_equal


class TestCountPairType:
    """Tests for COUNT_PAIR response type."""

    def test_code_is_count_pair(self) -> None:
        """CountPairType should have COUNT_PAIR code."""
        t = CountPairType()
        assert t.code == ResponseTypeCodes.COUNT_PAIR

    def test_is_not_computed(self) -> None:
        """CountPairType should not be computed."""
        t = CountPairType()
        assert t.is_computed is False

    def test_custom_field_names(self) -> None:
        """CountPairType should support custom field names."""
        t = CountPairType(first_field="internal_users", second_field="external_users")
        empty = t.empty_value()
        assert "internal_users" in empty
        assert "external_users" in empty

    # Valid shapes
    def test_validate_valid_both_integers(self) -> None:
        """Valid count pair with both integers should pass."""
        t = CountPairType(first_field="internal", second_field="external")
        result = t.validate({"internal": 100, "external": 50})
        assert result.is_valid

    def test_validate_valid_with_null(self) -> None:
        """Count pair with null values should pass (null differs from zero)."""
        t = CountPairType()
        result = t.validate({"first": None, "second": 0})
        assert result.is_valid

    def test_validate_zero_is_valid(self) -> None:
        """Zero should be a valid count."""
        t = CountPairType()
        result = t.validate({"first": 0, "second": 0})
        assert result.is_valid

    # Invalid shapes
    def test_validate_negative_value(self) -> None:
        """Negative values should fail validation."""
        t = CountPairType()
        result = t.validate({"first": -1, "second": 10})
        assert not result.is_valid
        assert "first" in result.field_errors

    def test_validate_non_integer(self) -> None:
        """Non-integer values should fail validation."""
        t = CountPairType()
        result = t.validate({"first": "not a number", "second": 10})
        assert not result.is_valid

    def test_validate_float_value(self) -> None:
        """Float values should fail validation (must be integer)."""
        t = CountPairType()
        result = t.validate({"first": 10.5, "second": 10})
        assert not result.is_valid

    def test_validate_boolean_not_integer(self) -> None:
        """Boolean should not be treated as integer."""
        t = CountPairType()
        result = t.validate({"first": True, "second": 10})
        assert not result.is_valid

    def test_validate_max_value_exceeded(self) -> None:
        """Exceeding max value should fail."""
        t = CountPairType(max_value=100)
        result = t.validate({"first": 150, "second": 50})
        assert not result.is_valid

    # Null differs from zero
    def test_null_differs_from_zero(self) -> None:
        """Null and zero should be semantically different."""
        t = CountPairType()
        result = t.compare(
            {"first": None, "second": 0, "unit": "count"},
            {"first": 0, "second": 0, "unit": "count"},
        )
        assert not result.is_equal

    # Normalization
    def test_normalize_includes_unit(self) -> None:
        """Normalization should include unit."""
        t = CountPairType(unit="users")
        result = t.normalize({"first": 10, "second": 20})
        assert result["unit"] == "users"

    def test_normalize_converts_strings_to_int(self) -> None:
        """Normalization should convert string numbers to int."""
        t = CountPairType()
        result = t.normalize({"first": "10", "second": "20"})
        assert result["first"] == 10
        assert result["second"] == 20

    # Empty and unknown
    def test_empty_value(self) -> None:
        """Empty value should have null counts and unit."""
        t = CountPairType(first_field="internal", second_field="external", unit="users")
        empty = t.empty_value()
        assert empty["internal"] is None
        assert empty["external"] is None
        assert empty["unit"] == "users"

    def test_unknown_value(self) -> None:
        """Unknown value should have _unknown marker."""
        t = CountPairType()
        unknown = t.unknown_value()
        assert unknown["_unknown"] is True

    # Form parsing
    def test_parse_form_valid_integers(self) -> None:
        """Form parsing should handle valid integers."""
        t = CountPairType(first_field="internal", second_field="external")
        result = t.parse_form({"internal": "100", "external": "50"})
        assert result.is_success
        assert result.value["internal"] == 100
        assert result.value["external"] == 50

    def test_parse_form_empty_as_null(self) -> None:
        """Form parsing should treat empty string as null."""
        t = CountPairType()
        result = t.parse_form({"first": "", "second": "10"})
        assert result.is_success
        assert result.value["first"] is None
        assert result.value["second"] == 10

    def test_parse_form_invalid_integer(self) -> None:
        """Form parsing should fail on invalid integer."""
        t = CountPairType()
        result = t.parse_form({"first": "not a number", "second": "10"})
        assert not result.is_success

    # Workbook parsing
    def test_parse_workbook_slash_separated(self) -> None:
        """Workbook parsing should handle slash-separated values."""
        t = CountPairType(first_field="internal", second_field="external")
        result = t.parse_workbook("100 / 50")
        assert result.is_success
        assert result.value["internal"] == 100
        assert result.value["external"] == 50

    def test_parse_workbook_single_value(self) -> None:
        """Workbook parsing should handle single value."""
        t = CountPairType()
        result = t.parse_workbook("100")
        assert result.is_success
        assert result.value["first"] == 100
        assert result.value["second"] is None

    def test_parse_workbook_empty(self) -> None:
        """Workbook parsing should handle empty cell."""
        t = CountPairType()
        result = t.parse_workbook(None)
        assert result.is_success
        assert result.value["first"] is None

    # Comparison
    def test_compare_equal_values(self) -> None:
        """Equal values should compare as equal."""
        t = CountPairType()
        result = t.compare(
            {"first": 100, "second": 50, "unit": "count"},
            {"first": 100, "second": 50, "unit": "count"},
        )
        assert result.is_equal
        assert result.is_noop

    def test_compare_different_values(self) -> None:
        """Different values should compare as different."""
        t = CountPairType()
        result = t.compare(
            {"first": 100, "second": 50, "unit": "count"},
            {"first": 100, "second": 75, "unit": "count"},
        )
        assert not result.is_equal


class TestControlledPairType:
    """Tests for CONTROLLED_PAIR response type."""

    def test_code_is_controlled_pair(self) -> None:
        """ControlledPairType should have CONTROLLED_PAIR code."""
        t = ControlledPairType()
        assert t.code == ResponseTypeCodes.CONTROLLED_PAIR

    def test_is_not_computed(self) -> None:
        """ControlledPairType should not be computed."""
        t = ControlledPairType()
        assert t.is_computed is False

    def test_custom_field_names(self) -> None:
        """ControlledPairType should support custom field names."""
        t = ControlledPairType(
            first_field="business_criticality",
            second_field="emergency_tier"
        )
        empty = t.empty_value()
        assert "business_criticality" in empty
        assert "emergency_tier" in empty

    # Valid shapes
    def test_validate_valid_both_codes(self) -> None:
        """Valid controlled pair with both codes should pass."""
        t = ControlledPairType(
            first_field="criticality",
            second_field="tier",
            first_allowed=["HIGH", "MEDIUM", "LOW"],
            second_allowed=["TIER_1", "TIER_2", "TIER_3"],
        )
        result = t.validate({"criticality": "HIGH", "tier": "TIER_1"})
        assert result.is_valid

    def test_validate_case_insensitive(self) -> None:
        """Validation should be case-insensitive for codes."""
        t = ControlledPairType(
            first_allowed=["HIGH", "LOW"],
            second_allowed=["TIER_1", "TIER_2"],
        )
        result = t.validate({"first": "high", "second": "tier_1"})
        assert result.is_valid

    def test_validate_null_values(self) -> None:
        """Null values should be valid."""
        t = ControlledPairType()
        result = t.validate({"first": None, "second": None})
        assert result.is_valid

    # Invalid shapes
    def test_validate_invalid_first_code(self) -> None:
        """Invalid first code should fail validation."""
        t = ControlledPairType(first_allowed=["HIGH", "LOW"])
        result = t.validate({"first": "INVALID", "second": "value"})
        assert not result.is_valid
        assert "first" in result.field_errors

    def test_validate_invalid_second_code(self) -> None:
        """Invalid second code should fail validation."""
        t = ControlledPairType(second_allowed=["TIER_1", "TIER_2"])
        result = t.validate({"first": "value", "second": "TIER_99"})
        assert not result.is_valid
        assert "second" in result.field_errors

    def test_validate_cross_field_validation(self) -> None:
        """Cross-field validation should be applied."""
        def cross_validate(first: str, second: str) -> list:
            if first == "CRITICAL" and second != "TIER_1":
                return ["CRITICAL requires TIER_1"]
            return []

        t = ControlledPairType(cross_validation=cross_validate)
        result = t.validate({"first": "CRITICAL", "second": "TIER_2"})
        assert not result.is_valid
        assert "CRITICAL requires TIER_1" in result.errors

    # Normalization
    def test_normalize_case_folds_to_uppercase(self) -> None:
        """Normalization should case-fold codes to uppercase."""
        t = ControlledPairType(first_field="criticality", second_field="tier")
        result = t.normalize({"criticality": "high", "tier": "tier_1"})
        assert result["criticality"] == "HIGH"
        assert result["tier"] == "TIER_1"

    def test_normalize_trims_whitespace(self) -> None:
        """Normalization should trim whitespace."""
        t = ControlledPairType()
        result = t.normalize({"first": "  HIGH  ", "second": " TIER_1 "})
        assert result["first"] == "HIGH"
        assert result["second"] == "TIER_1"

    # Empty and unknown
    def test_empty_value(self) -> None:
        """Empty value should have null fields."""
        t = ControlledPairType(first_field="criticality", second_field="tier")
        empty = t.empty_value()
        assert empty == {"criticality": None, "tier": None}

    def test_unknown_value(self) -> None:
        """Unknown value should have _unknown marker."""
        t = ControlledPairType()
        unknown = t.unknown_value()
        assert unknown["_unknown"] is True

    # Form parsing
    def test_parse_form_both_codes(self) -> None:
        """Form parsing should handle both codes."""
        t = ControlledPairType(first_field="criticality", second_field="tier")
        result = t.parse_form({"criticality": "high", "tier": "tier_1"})
        assert result.is_success
        assert result.value["criticality"] == "HIGH"
        assert result.value["tier"] == "TIER_1"

    def test_parse_form_empty_as_null(self) -> None:
        """Form parsing should treat empty string as null."""
        t = ControlledPairType()
        result = t.parse_form({"first": "", "second": "TIER_1"})
        assert result.is_success
        assert result.value["first"] is None

    # Workbook parsing
    def test_parse_workbook_slash_separated(self) -> None:
        """Workbook parsing should handle slash-separated values."""
        t = ControlledPairType(first_field="criticality", second_field="tier")
        result = t.parse_workbook("HIGH / TIER_1")
        assert result.is_success
        assert result.value["criticality"] == "HIGH"
        assert result.value["tier"] == "TIER_1"

    def test_parse_workbook_single_value(self) -> None:
        """Workbook parsing should handle single value."""
        t = ControlledPairType()
        result = t.parse_workbook("HIGH")
        assert result.is_success
        assert result.value["first"] == "HIGH"
        assert result.value["second"] is None

    def test_parse_workbook_with_context(self) -> None:
        """Workbook parsing should use context values."""
        t = ControlledPairType(first_field="criticality", second_field="tier")
        result = t.parse_workbook(
            "ignored",
            context={"criticality": "MEDIUM", "tier": "TIER_2"}
        )
        assert result.is_success
        assert result.value["criticality"] == "MEDIUM"
        assert result.value["tier"] == "TIER_2"

    # Comparison
    def test_compare_equal_values(self) -> None:
        """Equal values should compare as equal."""
        t = ControlledPairType()
        result = t.compare(
            {"first": "HIGH", "second": "TIER_1"},
            {"first": "HIGH", "second": "TIER_1"},
        )
        assert result.is_equal
        assert result.is_noop

    def test_compare_case_normalized(self) -> None:
        """Comparison should normalize case."""
        t = ControlledPairType()
        result = t.compare(
            {"first": "high", "second": "tier_1"},
            {"first": "HIGH", "second": "TIER_1"},
        )
        assert result.is_equal

    def test_compare_different_values(self) -> None:
        """Different values should compare as different."""
        t = ControlledPairType()
        result = t.compare(
            {"first": "HIGH", "second": "TIER_1"},
            {"first": "MEDIUM", "second": "TIER_1"},
        )
        assert not result.is_equal


class TestPeopleListType:
    """Tests for PEOPLE_LIST response type."""

    def test_code_is_people_list(self) -> None:
        """PeopleListType should have PEOPLE_LIST code."""
        t = PeopleListType()
        assert t.code == ResponseTypeCodes.PEOPLE_LIST

    def test_is_not_computed(self) -> None:
        """PeopleListType should not be computed."""
        t = PeopleListType()
        assert t.is_computed is False

    # Valid shapes
    def test_validate_valid_single_person(self) -> None:
        """Valid single person should pass validation."""
        t = PeopleListType()
        result = t.validate({
            "people": [{
                "role_code": "APPLICATION_OWNER",
                "name": "John Doe",
                "attuid": None,
                "email": None,
                "primary": True,
            }]
        })
        assert result.is_valid

    def test_validate_valid_multiple_people(self) -> None:
        """Valid multiple people should pass validation."""
        t = PeopleListType()
        result = t.validate({
            "people": [
                {"role_code": "OWNER", "name": "John Doe", "primary": True},
                {"role_code": "CONTACT", "name": "Jane Doe", "primary": False},
            ]
        })
        assert result.is_valid

    def test_validate_empty_people_list(self) -> None:
        """Empty people list should be valid."""
        t = PeopleListType()
        result = t.validate({"people": []})
        assert result.is_valid

    def test_validate_with_email(self) -> None:
        """Valid email should pass validation."""
        t = PeopleListType()
        result = t.validate({
            "people": [{
                "role_code": "OWNER",
                "name": "John Doe",
                "email": "john.doe@example.com",
                "primary": True,
            }]
        })
        assert result.is_valid

    def test_validate_with_attuid(self) -> None:
        """Valid ATTUID should pass validation."""
        t = PeopleListType()
        result = t.validate({
            "people": [{
                "role_code": "OWNER",
                "name": "John Doe",
                "attuid": "jd1234",
                "primary": True,
            }]
        })
        assert result.is_valid

    # Invalid shapes
    def test_validate_missing_people_field(self) -> None:
        """Missing people field should fail validation."""
        t = PeopleListType()
        result = t.validate({})
        assert not result.is_valid
        assert "people" in str(result.errors)

    def test_validate_people_not_list(self) -> None:
        """Non-list people should fail validation."""
        t = PeopleListType()
        result = t.validate({"people": "not a list"})
        assert not result.is_valid

    def test_validate_missing_role_code(self) -> None:
        """Missing role_code should fail validation."""
        t = PeopleListType()
        result = t.validate({
            "people": [{"name": "John Doe", "primary": True}]
        })
        assert not result.is_valid

    def test_validate_missing_name(self) -> None:
        """Missing name should fail validation."""
        t = PeopleListType()
        result = t.validate({
            "people": [{"role_code": "OWNER", "primary": True}]
        })
        assert not result.is_valid

    def test_validate_invalid_role_code(self) -> None:
        """Invalid role code should fail when allowed_roles specified."""
        t = PeopleListType(allowed_roles=["OWNER", "CONTACT"])
        result = t.validate({
            "people": [{"role_code": "INVALID", "name": "John", "primary": True}]
        })
        assert not result.is_valid

    def test_validate_invalid_email_format(self) -> None:
        """Invalid email format should fail validation."""
        t = PeopleListType()
        result = t.validate({
            "people": [{
                "role_code": "OWNER",
                "name": "John Doe",
                "email": "not-an-email",
                "primary": True,
            }]
        })
        assert not result.is_valid

    def test_validate_invalid_attuid_format(self) -> None:
        """Invalid ATTUID format should fail validation."""
        t = PeopleListType()
        result = t.validate({
            "people": [{
                "role_code": "OWNER",
                "name": "John Doe",
                "attuid": "invalid@attuid!",
                "primary": True,
            }]
        })
        assert not result.is_valid

    def test_validate_max_people_exceeded(self) -> None:
        """Exceeding max people should fail validation."""
        t = PeopleListType(max_people=2)
        result = t.validate({
            "people": [
                {"role_code": "OWNER", "name": "Person 1", "primary": True},
                {"role_code": "CONTACT", "name": "Person 2", "primary": False},
                {"role_code": "CONTACT", "name": "Person 3", "primary": False},
            ]
        })
        assert not result.is_valid

    def test_validate_require_primary(self) -> None:
        """Missing primary when required should fail validation."""
        t = PeopleListType(require_primary=True)
        result = t.validate({
            "people": [
                {"role_code": "OWNER", "name": "Person 1", "primary": False},
            ]
        })
        assert not result.is_valid
        assert "primary" in str(result.errors)

    # Normalization
    def test_normalize_role_code_uppercase(self) -> None:
        """Normalization should uppercase role codes."""
        t = PeopleListType()
        result = t.normalize({
            "people": [{"role_code": "owner", "name": "John", "primary": True}]
        })
        assert result["people"][0]["role_code"] == "OWNER"

    def test_normalize_name_trimmed(self) -> None:
        """Normalization should trim name whitespace."""
        t = PeopleListType()
        result = t.normalize({
            "people": [{"role_code": "OWNER", "name": "  John Doe  ", "primary": True}]
        })
        assert result["people"][0]["name"] == "John Doe"

    def test_normalize_email_lowercase(self) -> None:
        """Normalization should lowercase email."""
        t = PeopleListType()
        result = t.normalize({
            "people": [{
                "role_code": "OWNER",
                "name": "John",
                "email": "John.Doe@Example.COM",
                "primary": True,
            }]
        })
        assert result["people"][0]["email"] == "john.doe@example.com"

    def test_normalize_attuid_lowercase(self) -> None:
        """Normalization should lowercase ATTUID."""
        t = PeopleListType()
        result = t.normalize({
            "people": [{
                "role_code": "OWNER",
                "name": "John",
                "attuid": "JD1234",
                "primary": True,
            }]
        })
        assert result["people"][0]["attuid"] == "jd1234"

    def test_normalize_primary_boolean(self) -> None:
        """Normalization should ensure primary is boolean."""
        t = PeopleListType()
        result = t.normalize({
            "people": [{"role_code": "OWNER", "name": "John", "primary": 1}]
        })
        assert result["people"][0]["primary"] is True

    # Empty and unknown
    def test_empty_value(self) -> None:
        """Empty value should be empty people list."""
        t = PeopleListType()
        empty = t.empty_value()
        assert empty == {"people": []}

    def test_unknown_value(self) -> None:
        """Unknown value should have _unknown marker."""
        t = PeopleListType()
        unknown = t.unknown_value()
        assert unknown["_unknown"] is True
        assert unknown["people"] == []

    # Form parsing
    def test_parse_form_people_list(self) -> None:
        """Form parsing should handle people list."""
        t = PeopleListType()
        result = t.parse_form({
            "people": [
                {"role_code": "owner", "name": "John Doe", "primary": True}
            ]
        })
        assert result.is_success
        assert result.value["people"][0]["role_code"] == "OWNER"

    def test_parse_form_indexed_fields(self) -> None:
        """Form parsing should handle indexed form fields."""
        t = PeopleListType()
        result = t.parse_form({
            "people[0].role_code": "OWNER",
            "people[0].name": "John Doe",
            "people[0].primary": True,
            "people[1].role_code": "CONTACT",
            "people[1].name": "Jane Doe",
            "people[1].primary": False,
        })
        assert result.is_success
        assert len(result.value["people"]) == 2

    # Workbook parsing
    def test_parse_workbook_role_name_format(self) -> None:
        """Workbook parsing should handle 'Role: Name' format."""
        t = PeopleListType()
        result = t.parse_workbook("Application Owner: John Doe")
        assert result.is_success
        assert result.value["people"][0]["role_code"] == "APPLICATION_OWNER"
        assert result.value["people"][0]["name"] == "John Doe"

    def test_parse_workbook_multiple_semicolon(self) -> None:
        """Workbook parsing should handle semicolon-separated entries."""
        t = PeopleListType()
        result = t.parse_workbook("Owner: John Doe; Contact: Jane Doe")
        assert result.is_success
        assert len(result.value["people"]) == 2

    def test_parse_workbook_name_role_format(self) -> None:
        """Workbook parsing should handle 'Name (Role)' format."""
        t = PeopleListType()
        result = t.parse_workbook("John Doe (Owner)")
        assert result.is_success
        assert result.value["people"][0]["name"] == "John Doe"
        assert result.value["people"][0]["role_code"] == "OWNER"

    def test_parse_workbook_empty(self) -> None:
        """Workbook parsing should handle empty cell."""
        t = PeopleListType()
        result = t.parse_workbook(None)
        assert result.is_success
        assert result.value["people"] == []

    def test_parse_workbook_with_context(self) -> None:
        """Workbook parsing should use context people list."""
        t = PeopleListType()
        result = t.parse_workbook(
            "ignored",
            context={"people": [{"role_code": "OWNER", "name": "Context Person"}]}
        )
        assert result.is_success
        assert result.value["people"][0]["name"] == "Context Person"

    # Comparison
    def test_compare_equal_people(self) -> None:
        """Equal people lists should compare as equal."""
        t = PeopleListType()
        person = {
            "role_code": "OWNER",
            "name": "John Doe",
            "attuid": None,
            "email": None,
            "primary": True,
        }
        result = t.compare(
            {"people": [person]},
            {"people": [person]},
        )
        assert result.is_equal
        assert result.is_noop

    def test_compare_different_people(self) -> None:
        """Different people lists should compare as different."""
        t = PeopleListType()
        result = t.compare(
            {"people": [{"role_code": "OWNER", "name": "John", "primary": True}]},
            {"people": [{"role_code": "OWNER", "name": "Jane", "primary": True}]},
        )
        assert not result.is_equal

    def test_compare_different_order_same_people(self) -> None:
        """Same people in different order should compare as equal."""
        t = PeopleListType()
        result = t.compare(
            {"people": [
                {"role_code": "OWNER", "name": "John", "attuid": None, "email": None, "primary": True},
                {"role_code": "CONTACT", "name": "Jane", "attuid": None, "email": None, "primary": False},
            ]},
            {"people": [
                {"role_code": "CONTACT", "name": "Jane", "attuid": None, "email": None, "primary": False},
                {"role_code": "OWNER", "name": "John", "attuid": None, "email": None, "primary": True},
            ]},
        )
        assert result.is_equal

    # Serialization
    def test_serialize_canonical(self) -> None:
        """Serialization should produce canonical JSON."""
        t = PeopleListType()
        value = {"people": [{"role_code": "OWNER", "name": "John", "primary": True}]}
        serialized = t.serialize(t.normalize(value))
        assert '"people"' in serialized
        assert '"role_code"' in serialized

    def test_deserialize_roundtrip(self) -> None:
        """Deserialization should roundtrip correctly."""
        t = PeopleListType()
        value = {"people": [{"role_code": "OWNER", "name": "John", "attuid": None, "email": None, "primary": True}]}
        normalized = t.normalize(value)
        serialized = t.serialize(normalized)
        deserialized = t.deserialize(serialized)
        assert deserialized == normalized


class TestCollectionTypeRegistration:
    """Tests for collection type registration compatibility."""

    def test_all_collection_types_have_required_attributes(self) -> None:
        """All collection types should have required ResponseType attributes."""
        types = [
            MultiSelectType(),
            TextPairType(),
            CountPairType(),
            ControlledPairType(),
            PeopleListType(),
        ]

        for t in types:
            assert hasattr(t, "code")
            assert hasattr(t, "schema_version")
            assert hasattr(t, "editor_key")
            assert hasattr(t, "display_key")
            assert hasattr(t, "is_computed")
            assert hasattr(t, "validate")
            assert hasattr(t, "normalize")
            assert hasattr(t, "compare")
            assert hasattr(t, "serialize")
            assert hasattr(t, "deserialize")
            assert hasattr(t, "parse_form")
            assert hasattr(t, "parse_workbook")
            assert hasattr(t, "empty_value")
            assert hasattr(t, "unknown_value")

    def test_all_collection_types_are_not_computed(self) -> None:
        """All collection types should not be computed."""
        types = [
            MultiSelectType(),
            TextPairType(),
            CountPairType(),
            ControlledPairType(),
            PeopleListType(),
        ]

        for t in types:
            assert t.is_computed is False

    def test_all_collection_types_have_schema_version(self) -> None:
        """All collection types should have schema version 1.0."""
        types = [
            MultiSelectType(),
            TextPairType(),
            CountPairType(),
            ControlledPairType(),
            PeopleListType(),
        ]

        for t in types:
            assert t.schema_version == "1.0"
