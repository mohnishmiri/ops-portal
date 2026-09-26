"""
Tests for measurement response types (R03).

Tests cover:
- MeasurementType: Single decimal value with unit
- MeasurementPairType: Two named measurements
- MeasurementSetType: Repeatable metrics with unique metric/scope
- MeasurementContextType: Structured metrics with evidence window
"""

from __future__ import annotations

import math
from decimal import Decimal
from typing import Any, Dict

import pytest

from migration_intake.catalog.response_types.base import ResponseTypeCodes
from migration_intake.catalog.response_types.measurements import (
    MeasurementType,
    MeasurementPairType,
    MeasurementSetType,
    MeasurementContextType,
)


class TestMeasurementType:
    """Tests for MEASUREMENT response type."""

    def test_code_is_measurement(self) -> None:
        """Type code should be MEASUREMENT."""
        t = MeasurementType()
        assert t.code == ResponseTypeCodes.MEASUREMENT
        assert t.code == "MEASUREMENT"

    def test_schema_version(self) -> None:
        """Schema version should be defined."""
        t = MeasurementType()
        assert t.schema_version == "1.0"

    def test_is_not_computed(self) -> None:
        """MEASUREMENT is not a computed type."""
        t = MeasurementType()
        assert t.is_computed is False

    def test_has_editor_and_display_keys(self) -> None:
        """Type should have editor and display keys."""
        t = MeasurementType()
        assert t.editor_key == "measurement_editor"
        assert t.display_key == "measurement_display"

    # Validation tests

    def test_validate_none_is_valid(self) -> None:
        """None value should be valid."""
        t = MeasurementType()
        result = t.validate(None)
        assert result.is_valid

    def test_validate_valid_measurement(self) -> None:
        """Valid measurement should pass validation."""
        t = MeasurementType()
        result = t.validate({
            "value": "150.5",
            "unit": "ms",
            "qualifier": "p99",
            "observed_at": "2024-01-15"
        })
        assert result.is_valid

    def test_validate_minimal_measurement(self) -> None:
        """Measurement with just value and unit should be valid."""
        t = MeasurementType()
        result = t.validate({"value": "100", "unit": "ms"})
        assert result.is_valid

    def test_validate_null_value_is_valid(self) -> None:
        """Null value (blank) should be valid."""
        t = MeasurementType()
        result = t.validate({"value": None, "unit": None})
        assert result.is_valid

    def test_validate_unknown_marker_is_valid(self) -> None:
        """Unknown marker should be valid."""
        t = MeasurementType()
        result = t.validate({"_unknown": True})
        assert result.is_valid

    def test_validate_rejects_non_dict(self) -> None:
        """Non-dict value should be rejected."""
        t = MeasurementType()
        result = t.validate("not a dict")  # type: ignore
        assert not result.is_valid
        assert "Expected dict" in result.errors[0]

    def test_validate_rejects_nan(self) -> None:
        """NaN value should be rejected."""
        t = MeasurementType()
        result = t.validate({"value": float("nan"), "unit": "ms"})
        assert not result.is_valid
        assert any("NaN" in e for e in result.errors)

    def test_validate_rejects_infinity(self) -> None:
        """Infinity value should be rejected."""
        t = MeasurementType()
        result = t.validate({"value": float("inf"), "unit": "ms"})
        assert not result.is_valid
        assert any("infinity" in e for e in result.errors)

    def test_validate_rejects_invalid_decimal(self) -> None:
        """Invalid decimal string should be rejected."""
        t = MeasurementType()
        result = t.validate({"value": "not-a-number", "unit": "ms"})
        assert not result.is_valid
        assert "value" in result.field_errors

    def test_validate_rejects_invalid_qualifier(self) -> None:
        """Invalid qualifier should be rejected."""
        t = MeasurementType()
        result = t.validate({
            "value": "100",
            "unit": "ms",
            "qualifier": "invalid_qualifier"
        })
        assert not result.is_valid
        assert "qualifier" in result.field_errors

    def test_validate_rejects_invalid_observed_at(self) -> None:
        """Invalid observed_at format should be rejected."""
        t = MeasurementType()
        result = t.validate({
            "value": "100",
            "unit": "ms",
            "observed_at": "not-a-date"
        })
        assert not result.is_valid
        assert "observed_at" in result.field_errors

    def test_validate_accepts_iso_date(self) -> None:
        """ISO date format should be accepted."""
        t = MeasurementType()
        result = t.validate({
            "value": "100",
            "unit": "ms",
            "observed_at": "2024-01-15"
        })
        assert result.is_valid

    def test_validate_accepts_iso_datetime(self) -> None:
        """ISO datetime format should be accepted."""
        t = MeasurementType()
        result = t.validate({
            "value": "100",
            "unit": "ms",
            "observed_at": "2024-01-15T10:30:00Z"
        })
        assert result.is_valid

    # Normalization tests

    def test_normalize_decimal_value(self) -> None:
        """Decimal values should be normalized."""
        t = MeasurementType()
        result = t.normalize({"value": "150.500", "unit": "ms"})
        assert result["value"] == "150.5"

    def test_normalize_integer_value(self) -> None:
        """Integer values should be normalized."""
        t = MeasurementType()
        result = t.normalize({"value": 100, "unit": "ms"})
        assert result["value"] == "100"

    def test_normalize_trims_whitespace(self) -> None:
        """Whitespace should be trimmed."""
        t = MeasurementType()
        result = t.normalize({
            "value": "100",
            "unit": "  ms  ",
            "qualifier": "  P99  "
        })
        assert result["unit"] == "ms"
        assert result["qualifier"] == "p99"

    def test_normalize_lowercases_qualifier(self) -> None:
        """Qualifier should be lowercased."""
        t = MeasurementType()
        result = t.normalize({
            "value": "100",
            "unit": "ms",
            "qualifier": "P99"
        })
        assert result["qualifier"] == "p99"

    def test_normalize_unknown_marker(self) -> None:
        """Unknown marker should be preserved."""
        t = MeasurementType()
        result = t.normalize({"_unknown": True})
        assert result == {"_unknown": True}

    def test_normalize_none_returns_empty(self) -> None:
        """None should return empty value."""
        t = MeasurementType()
        result = t.normalize(None)
        assert result == {"value": None, "unit": None}

    # Form parsing tests

    def test_parse_form_valid_data(self) -> None:
        """Valid form data should parse successfully."""
        t = MeasurementType()
        result = t.parse_form({
            "value": "150.5",
            "unit": "ms",
            "qualifier": "p99"
        })
        assert result.is_success
        assert result.value["value"] == "150.5"
        assert result.value["unit"] == "ms"
        assert result.value["qualifier"] == "p99"

    def test_parse_form_empty_returns_empty_value(self) -> None:
        """Empty form data should return empty value."""
        t = MeasurementType()
        result = t.parse_form({})
        assert result.is_success
        assert result.value == {"value": None, "unit": None}

    def test_parse_form_trims_whitespace(self) -> None:
        """Form parsing should trim whitespace."""
        t = MeasurementType()
        result = t.parse_form({
            "value": "  100  ",
            "unit": "  ms  "
        })
        assert result.is_success
        assert result.value["value"] == "100"
        assert result.value["unit"] == "ms"

    def test_parse_form_rejects_invalid_decimal(self) -> None:
        """Invalid decimal in form should fail."""
        t = MeasurementType()
        result = t.parse_form({"value": "not-a-number", "unit": "ms"})
        assert not result.is_success
        assert len(result.errors) > 0

    # Workbook parsing tests

    def test_parse_workbook_numeric_value(self) -> None:
        """Numeric cell value should parse with context unit."""
        t = MeasurementType()
        result = t.parse_workbook(150.5, {"unit": "ms"})
        assert result.is_success
        assert result.value["value"] == "150.5"
        assert result.value["unit"] == "ms"

    def test_parse_workbook_string_with_unit(self) -> None:
        """String like '150 ms' should parse value and unit."""
        t = MeasurementType()
        result = t.parse_workbook("150 ms")
        assert result.is_success
        assert result.value["value"] == "150"
        assert result.value["unit"] == "ms"

    def test_parse_workbook_string_no_space(self) -> None:
        """String like '150ms' should parse value and unit."""
        t = MeasurementType()
        result = t.parse_workbook("150ms")
        assert result.is_success
        assert result.value["value"] == "150"
        assert result.value["unit"] == "ms"

    def test_parse_workbook_empty_returns_empty(self) -> None:
        """Empty cell should return empty value."""
        t = MeasurementType()
        result = t.parse_workbook(None)
        assert result.is_success
        assert result.value == {"value": None, "unit": None}

    def test_parse_workbook_whitespace_returns_empty(self) -> None:
        """Whitespace-only cell should return empty value."""
        t = MeasurementType()
        result = t.parse_workbook("   ")
        assert result.is_success
        assert result.value == {"value": None, "unit": None}

    def test_parse_workbook_rejects_invalid(self) -> None:
        """Invalid cell value should fail."""
        t = MeasurementType()
        result = t.parse_workbook("not a measurement")
        assert not result.is_success

    def test_parse_workbook_decimal_type(self) -> None:
        """Decimal type should be handled."""
        t = MeasurementType()
        result = t.parse_workbook(Decimal("150.5"), {"unit": "ms"})
        assert result.is_success
        assert result.value["value"] == "150.5"

    # Empty and unknown value tests

    def test_empty_value(self) -> None:
        """Empty value should have null value and unit."""
        t = MeasurementType()
        empty = t.empty_value()
        assert empty == {"value": None, "unit": None}

    def test_unknown_value(self) -> None:
        """Unknown value should have marker."""
        t = MeasurementType()
        unknown = t.unknown_value()
        assert unknown == {"_unknown": True}

    # Comparison tests

    def test_compare_equal_values(self) -> None:
        """Equal values should compare as equal."""
        t = MeasurementType()
        result = t.compare(
            {"value": "150", "unit": "ms"},
            {"value": "150", "unit": "ms"}
        )
        assert result.is_equal
        assert result.is_noop

    def test_compare_different_values(self) -> None:
        """Different values should compare as different."""
        t = MeasurementType()
        result = t.compare(
            {"value": "150", "unit": "ms"},
            {"value": "200", "unit": "ms"}
        )
        assert not result.is_equal
        assert not result.is_noop

    def test_compare_normalized_equality(self) -> None:
        """Values that normalize to same should be equal."""
        t = MeasurementType()
        result = t.compare(
            {"value": "150.00", "unit": "ms"},
            {"value": "150", "unit": "ms"}
        )
        assert result.is_equal

    # Serialization tests

    def test_serialize_canonical(self) -> None:
        """Serialization should produce canonical JSON."""
        t = MeasurementType()
        json_str = t.serialize({"value": "150", "unit": "ms"})
        assert '"unit": "ms"' in json_str
        assert '"value": "150"' in json_str

    def test_deserialize(self) -> None:
        """Deserialization should restore value."""
        t = MeasurementType()
        original = {"value": "150", "unit": "ms"}
        json_str = t.serialize(original)
        restored = t.deserialize(json_str)
        assert restored == original


class TestMeasurementPairType:
    """Tests for MEASUREMENT_PAIR response type."""

    def test_code_is_measurement_pair(self) -> None:
        """Type code should be MEASUREMENT_PAIR."""
        t = MeasurementPairType()
        assert t.code == ResponseTypeCodes.MEASUREMENT_PAIR
        assert t.code == "MEASUREMENT_PAIR"

    def test_is_not_computed(self) -> None:
        """MEASUREMENT_PAIR is not a computed type."""
        t = MeasurementPairType()
        assert t.is_computed is False

    # Validation tests

    def test_validate_valid_pair(self) -> None:
        """Valid measurement pair should pass validation."""
        t = MeasurementPairType()
        result = t.validate({
            "first": {"value": "150", "unit": "ms"},
            "second": {"value": "100", "unit": "Mbps"},
            "evidence_window": "2024-Q1"
        })
        assert result.is_valid

    def test_validate_null_values_valid(self) -> None:
        """Null values in pair should be valid."""
        t = MeasurementPairType()
        result = t.validate({
            "first": {"value": None, "unit": None},
            "second": {"value": None, "unit": None}
        })
        assert result.is_valid

    def test_validate_unknown_marker(self) -> None:
        """Unknown marker should be valid."""
        t = MeasurementPairType()
        result = t.validate({"_unknown": True})
        assert result.is_valid

    def test_validate_rejects_nan_in_first(self) -> None:
        """NaN in first measurement should be rejected."""
        t = MeasurementPairType()
        result = t.validate({
            "first": {"value": float("nan"), "unit": "ms"},
            "second": {"value": "100", "unit": "Mbps"}
        })
        assert not result.is_valid

    def test_validate_rejects_nan_in_second(self) -> None:
        """NaN in second measurement should be rejected."""
        t = MeasurementPairType()
        result = t.validate({
            "first": {"value": "150", "unit": "ms"},
            "second": {"value": float("nan"), "unit": "Mbps"}
        })
        assert not result.is_valid

    def test_validate_rejects_non_dict_first(self) -> None:
        """Non-dict first should be rejected."""
        t = MeasurementPairType()
        result = t.validate({
            "first": "not a dict",
            "second": {"value": "100", "unit": "Mbps"}
        })
        assert not result.is_valid
        assert "first" in result.field_errors

    # Normalization tests

    def test_normalize_pair(self) -> None:
        """Pair values should be normalized."""
        t = MeasurementPairType()
        result = t.normalize({
            "first": {"value": "150.00", "unit": "  ms  "},
            "second": {"value": 100, "unit": "Mbps"},
            "evidence_window": "  2024-Q1  "
        })
        assert result["first"]["value"] == "150"
        assert result["first"]["unit"] == "ms"
        assert result["second"]["value"] == "100"
        assert result["evidence_window"] == "2024-Q1"

    def test_normalize_unknown_marker(self) -> None:
        """Unknown marker should be preserved."""
        t = MeasurementPairType()
        result = t.normalize({"_unknown": True})
        assert result == {"_unknown": True}

    # Form parsing tests

    def test_parse_form_valid_pair(self) -> None:
        """Valid form data should parse successfully."""
        t = MeasurementPairType()
        result = t.parse_form({
            "first_value": "150",
            "first_unit": "ms",
            "second_value": "100",
            "second_unit": "Mbps",
            "evidence_window": "2024-Q1"
        })
        assert result.is_success
        assert result.value["first"]["value"] == "150"
        assert result.value["second"]["value"] == "100"
        assert result.value["evidence_window"] == "2024-Q1"

    def test_parse_form_empty_returns_empty(self) -> None:
        """Empty form should return empty value."""
        t = MeasurementPairType()
        result = t.parse_form({})
        assert result.is_success
        assert result.value["first"]["value"] is None
        assert result.value["second"]["value"] is None

    # Workbook parsing tests

    def test_parse_workbook_dict_value(self) -> None:
        """Dict cell value should be normalized."""
        t = MeasurementPairType()
        result = t.parse_workbook({
            "first": {"value": "150", "unit": "ms"},
            "second": {"value": "100", "unit": "Mbps"}
        })
        assert result.is_success
        assert result.value["first"]["value"] == "150"

    def test_parse_workbook_string_with_separator(self) -> None:
        """String with separator should parse both values."""
        t = MeasurementPairType()
        result = t.parse_workbook("150 ms / 100 Mbps")
        assert result.is_success
        assert result.value["first"]["value"] == "150"
        assert result.value["first"]["unit"] == "ms"
        assert result.value["second"]["value"] == "100"
        assert result.value["second"]["unit"] == "Mbps"

    def test_parse_workbook_empty_returns_empty(self) -> None:
        """Empty cell should return empty value."""
        t = MeasurementPairType()
        result = t.parse_workbook(None)
        assert result.is_success
        assert result.value["first"]["value"] is None

    # Empty and unknown value tests

    def test_empty_value(self) -> None:
        """Empty value should have null measurements."""
        t = MeasurementPairType()
        empty = t.empty_value()
        assert empty["first"]["value"] is None
        assert empty["second"]["value"] is None

    def test_unknown_value(self) -> None:
        """Unknown value should have marker."""
        t = MeasurementPairType()
        unknown = t.unknown_value()
        assert unknown == {"_unknown": True}

    # Comparison tests

    def test_compare_equal_pairs(self) -> None:
        """Equal pairs should compare as equal."""
        t = MeasurementPairType()
        result = t.compare(
            {
                "first": {"value": "150", "unit": "ms"},
                "second": {"value": "100", "unit": "Mbps"}
            },
            {
                "first": {"value": "150", "unit": "ms"},
                "second": {"value": "100", "unit": "Mbps"}
            }
        )
        assert result.is_equal

    def test_compare_different_pairs(self) -> None:
        """Different pairs should compare as different."""
        t = MeasurementPairType()
        result = t.compare(
            {
                "first": {"value": "150", "unit": "ms"},
                "second": {"value": "100", "unit": "Mbps"}
            },
            {
                "first": {"value": "200", "unit": "ms"},
                "second": {"value": "100", "unit": "Mbps"}
            }
        )
        assert not result.is_equal


class TestMeasurementSetType:
    """Tests for MEASUREMENT_SET response type."""

    def test_code_is_measurement_set(self) -> None:
        """Type code should be MEASUREMENT_SET."""
        t = MeasurementSetType()
        assert t.code == ResponseTypeCodes.MEASUREMENT_SET
        assert t.code == "MEASUREMENT_SET"

    def test_is_not_computed(self) -> None:
        """MEASUREMENT_SET is not a computed type."""
        t = MeasurementSetType()
        assert t.is_computed is False

    # Validation tests

    def test_validate_valid_set(self) -> None:
        """Valid measurement set should pass validation."""
        t = MeasurementSetType()
        result = t.validate({
            "measurements": [
                {"metric": "cpu_usage", "value": "75", "unit": "%", "scope": "prod"},
                {"metric": "memory_usage", "value": "8", "unit": "GB", "scope": "prod"}
            ]
        })
        assert result.is_valid

    def test_validate_empty_measurements_valid(self) -> None:
        """Empty measurements array should be valid."""
        t = MeasurementSetType()
        result = t.validate({"measurements": []})
        assert result.is_valid

    def test_validate_unknown_marker(self) -> None:
        """Unknown marker should be valid."""
        t = MeasurementSetType()
        result = t.validate({"_unknown": True})
        assert result.is_valid

    def test_validate_rejects_duplicate_metric_scope(self) -> None:
        """Duplicate metric/scope combination should be rejected."""
        t = MeasurementSetType()
        result = t.validate({
            "measurements": [
                {"metric": "cpu_usage", "value": "75", "unit": "%", "scope": "prod"},
                {"metric": "cpu_usage", "value": "80", "unit": "%", "scope": "prod"}
            ]
        })
        assert not result.is_valid
        assert any("Duplicate" in e for e in result.errors)

    def test_validate_allows_same_metric_different_scope(self) -> None:
        """Same metric with different scope should be valid."""
        t = MeasurementSetType()
        result = t.validate({
            "measurements": [
                {"metric": "cpu_usage", "value": "75", "unit": "%", "scope": "prod"},
                {"metric": "cpu_usage", "value": "50", "unit": "%", "scope": "dev"}
            ]
        })
        assert result.is_valid

    def test_validate_rejects_nan(self) -> None:
        """NaN value should be rejected."""
        t = MeasurementSetType()
        result = t.validate({
            "measurements": [
                {"metric": "cpu_usage", "value": float("nan"), "unit": "%"}
            ]
        })
        assert not result.is_valid

    def test_validate_rejects_missing_metric(self) -> None:
        """Missing metric should be rejected."""
        t = MeasurementSetType()
        result = t.validate({
            "measurements": [
                {"value": "75", "unit": "%"}
            ]
        })
        assert not result.is_valid
        assert any("metric" in e.lower() for e in result.errors)

    def test_validate_rejects_non_list_measurements(self) -> None:
        """Non-list measurements should be rejected."""
        t = MeasurementSetType()
        result = t.validate({"measurements": "not a list"})
        assert not result.is_valid

    # Normalization tests

    def test_normalize_set(self) -> None:
        """Set values should be normalized."""
        t = MeasurementSetType()
        result = t.normalize({
            "measurements": [
                {"metric": "  cpu_usage  ", "value": "75.00", "unit": "  %  ", "qualifier": "AVERAGE"},
                {"metric": "memory_usage", "value": 8, "unit": "GB"}
            ]
        })
        assert result["measurements"][0]["metric"] == "cpu_usage"
        assert result["measurements"][0]["value"] == "75"
        assert result["measurements"][0]["unit"] == "%"
        assert result["measurements"][0]["qualifier"] == "average"

    def test_normalize_sorts_by_metric_scope(self) -> None:
        """Measurements should be sorted by metric, then scope."""
        t = MeasurementSetType()
        result = t.normalize({
            "measurements": [
                {"metric": "memory", "value": "8", "unit": "GB", "scope": "prod"},
                {"metric": "cpu", "value": "75", "unit": "%", "scope": "prod"},
                {"metric": "cpu", "value": "50", "unit": "%", "scope": "dev"}
            ]
        })
        assert result["measurements"][0]["metric"] == "cpu"
        assert result["measurements"][0]["scope"] == "dev"
        assert result["measurements"][1]["metric"] == "cpu"
        assert result["measurements"][1]["scope"] == "prod"
        assert result["measurements"][2]["metric"] == "memory"

    # Form parsing tests

    def test_parse_form_valid_set(self) -> None:
        """Valid form data should parse successfully."""
        t = MeasurementSetType()
        result = t.parse_form({
            "metrics": ["cpu_usage", "memory_usage"],
            "values": ["75", "8"],
            "units": ["%", "GB"],
            "scopes": ["prod", "prod"]
        })
        assert result.is_success
        assert len(result.value["measurements"]) == 2
        assert result.value["measurements"][0]["metric"] == "cpu_usage"

    def test_parse_form_empty_returns_empty(self) -> None:
        """Empty form should return empty value."""
        t = MeasurementSetType()
        result = t.parse_form({})
        assert result.is_success
        assert result.value == {"measurements": []}

    def test_parse_form_skips_empty_metrics(self) -> None:
        """Empty metric entries should be skipped."""
        t = MeasurementSetType()
        result = t.parse_form({
            "metrics": ["cpu_usage", "", "memory_usage"],
            "values": ["75", "50", "8"],
            "units": ["%", "%", "GB"]
        })
        assert result.is_success
        assert len(result.value["measurements"]) == 2

    # Workbook parsing tests

    def test_parse_workbook_dict_value(self) -> None:
        """Dict cell value should be normalized."""
        t = MeasurementSetType()
        result = t.parse_workbook({
            "measurements": [
                {"metric": "cpu", "value": "75", "unit": "%"}
            ]
        })
        assert result.is_success
        assert len(result.value["measurements"]) == 1

    def test_parse_workbook_list_value(self) -> None:
        """List cell value should be treated as measurements."""
        t = MeasurementSetType()
        result = t.parse_workbook([
            {"metric": "cpu", "value": "75", "unit": "%"}
        ])
        assert result.is_success
        assert len(result.value["measurements"]) == 1

    def test_parse_workbook_string_format(self) -> None:
        """String like 'cpu:75%,memory:8GB' should parse."""
        t = MeasurementSetType()
        result = t.parse_workbook("cpu:75%,memory:8GB")
        assert result.is_success
        assert len(result.value["measurements"]) == 2

    def test_parse_workbook_empty_returns_empty(self) -> None:
        """Empty cell should return empty value."""
        t = MeasurementSetType()
        result = t.parse_workbook(None)
        assert result.is_success
        assert result.value == {"measurements": []}

    # Empty and unknown value tests

    def test_empty_value(self) -> None:
        """Empty value should have empty measurements array."""
        t = MeasurementSetType()
        empty = t.empty_value()
        assert empty == {"measurements": []}

    def test_unknown_value(self) -> None:
        """Unknown value should have marker."""
        t = MeasurementSetType()
        unknown = t.unknown_value()
        assert unknown == {"_unknown": True}

    # Comparison tests

    def test_compare_equal_sets(self) -> None:
        """Equal sets should compare as equal."""
        t = MeasurementSetType()
        result = t.compare(
            {"measurements": [{"metric": "cpu", "value": "75", "unit": "%"}]},
            {"measurements": [{"metric": "cpu", "value": "75", "unit": "%"}]}
        )
        assert result.is_equal

    def test_compare_different_sets(self) -> None:
        """Different sets should compare as different."""
        t = MeasurementSetType()
        result = t.compare(
            {"measurements": [{"metric": "cpu", "value": "75", "unit": "%"}]},
            {"measurements": [{"metric": "cpu", "value": "80", "unit": "%"}]}
        )
        assert not result.is_equal


class TestMeasurementContextType:
    """Tests for MEASUREMENT_CONTEXT response type."""

    def test_code_is_measurement_context(self) -> None:
        """Type code should be MEASUREMENT_CONTEXT."""
        t = MeasurementContextType()
        assert t.code == ResponseTypeCodes.MEASUREMENT_CONTEXT
        assert t.code == "MEASUREMENT_CONTEXT"

    def test_is_not_computed(self) -> None:
        """MEASUREMENT_CONTEXT is not a computed type."""
        t = MeasurementContextType()
        assert t.is_computed is False

    # Validation tests

    def test_validate_valid_context(self) -> None:
        """Valid measurement context should pass validation."""
        t = MeasurementContextType()
        result = t.validate({
            "measurements": [
                {"metric": "latency_p99", "value": "150", "unit": "ms"}
            ],
            "window": "2024-01-01 to 2024-01-31",
            "source_context": "Production APM dashboard",
            "fallback_rule": "Use design estimates if no production data"
        })
        assert result.is_valid

    def test_validate_empty_measurements_valid(self) -> None:
        """Empty measurements with missing_reason should be valid."""
        t = MeasurementContextType()
        result = t.validate({
            "measurements": [],
            "window": None,
            "source_context": None,
            "missing_reason": "No production data available"
        })
        assert result.is_valid

    def test_validate_unknown_marker(self) -> None:
        """Unknown marker should be valid."""
        t = MeasurementContextType()
        result = t.validate({"_unknown": True})
        assert result.is_valid

    def test_validate_requires_window_with_measurements(self) -> None:
        """Window should be required when measurements are provided."""
        t = MeasurementContextType()
        result = t.validate({
            "measurements": [
                {"metric": "latency", "value": "150", "unit": "ms"}
            ],
            "source_context": "APM"
        })
        assert not result.is_valid
        assert any("window" in e.lower() for e in result.errors)

    def test_validate_requires_source_context_with_measurements(self) -> None:
        """Source context should be required when measurements are provided."""
        t = MeasurementContextType()
        result = t.validate({
            "measurements": [
                {"metric": "latency", "value": "150", "unit": "ms"}
            ],
            "window": "2024-Q1"
        })
        assert not result.is_valid
        assert any("source_context" in e.lower() for e in result.errors)

    def test_validate_rejects_nan(self) -> None:
        """NaN value should be rejected."""
        t = MeasurementContextType()
        result = t.validate({
            "measurements": [
                {"metric": "latency", "value": float("nan"), "unit": "ms"}
            ],
            "window": "2024-Q1",
            "source_context": "APM"
        })
        assert not result.is_valid

    # Normalization tests

    def test_normalize_context(self) -> None:
        """Context values should be normalized."""
        t = MeasurementContextType()
        result = t.normalize({
            "measurements": [
                {"metric": "  latency  ", "value": "150.00", "unit": "  ms  ", "qualifier": "P99"}
            ],
            "window": "  2024-Q1  ",
            "source_context": "  APM Dashboard  ",
            "fallback_rule": "  Use estimates  "
        })
        assert result["measurements"][0]["metric"] == "latency"
        assert result["measurements"][0]["value"] == "150"
        assert result["measurements"][0]["qualifier"] == "p99"
        assert result["window"] == "2024-Q1"
        assert result["source_context"] == "APM Dashboard"
        assert result["fallback_rule"] == "Use estimates"

    def test_normalize_unknown_marker(self) -> None:
        """Unknown marker should be preserved."""
        t = MeasurementContextType()
        result = t.normalize({"_unknown": True})
        assert result == {"_unknown": True}

    # Form parsing tests

    def test_parse_form_valid_context(self) -> None:
        """Valid form data should parse successfully."""
        t = MeasurementContextType()
        result = t.parse_form({
            "metrics": ["latency_p99"],
            "values": ["150"],
            "units": ["ms"],
            "window": "2024-Q1",
            "source_context": "APM Dashboard"
        })
        assert result.is_success
        assert len(result.value["measurements"]) == 1
        assert result.value["window"] == "2024-Q1"
        assert result.value["source_context"] == "APM Dashboard"

    def test_parse_form_empty_returns_empty(self) -> None:
        """Empty form should return empty value."""
        t = MeasurementContextType()
        result = t.parse_form({})
        assert result.is_success
        assert result.value["measurements"] == []

    def test_parse_form_with_missing_reason(self) -> None:
        """Form with missing_reason should parse."""
        t = MeasurementContextType()
        result = t.parse_form({
            "missing_reason": "No production data available"
        })
        assert result.is_success
        assert result.value["missing_reason"] == "No production data available"

    # Workbook parsing tests

    def test_parse_workbook_dict_value(self) -> None:
        """Dict cell value should be normalized."""
        t = MeasurementContextType()
        result = t.parse_workbook({
            "measurements": [{"metric": "latency", "value": "150", "unit": "ms"}],
            "window": "2024-Q1",
            "source_context": "APM"
        })
        assert result.is_success
        assert result.value["window"] == "2024-Q1"

    def test_parse_workbook_string_with_context(self) -> None:
        """String with context should parse measurements."""
        t = MeasurementContextType()
        result = t.parse_workbook(
            "latency:150ms",
            {"window": "2024-Q1", "source_context": "APM"}
        )
        assert result.is_success
        assert len(result.value["measurements"]) == 1
        assert result.value["window"] == "2024-Q1"

    def test_parse_workbook_empty_returns_empty(self) -> None:
        """Empty cell should return empty value."""
        t = MeasurementContextType()
        result = t.parse_workbook(None)
        assert result.is_success
        assert result.value["measurements"] == []

    # Empty and unknown value tests

    def test_empty_value(self) -> None:
        """Empty value should have empty measurements and null context."""
        t = MeasurementContextType()
        empty = t.empty_value()
        assert empty == {
            "measurements": [],
            "window": None,
            "source_context": None
        }

    def test_unknown_value(self) -> None:
        """Unknown value should have marker."""
        t = MeasurementContextType()
        unknown = t.unknown_value()
        assert unknown == {"_unknown": True}

    # Comparison tests

    def test_compare_equal_contexts(self) -> None:
        """Equal contexts should compare as equal."""
        t = MeasurementContextType()
        result = t.compare(
            {
                "measurements": [{"metric": "latency", "value": "150", "unit": "ms"}],
                "window": "2024-Q1",
                "source_context": "APM"
            },
            {
                "measurements": [{"metric": "latency", "value": "150", "unit": "ms"}],
                "window": "2024-Q1",
                "source_context": "APM"
            }
        )
        assert result.is_equal

    def test_compare_different_contexts(self) -> None:
        """Different contexts should compare as different."""
        t = MeasurementContextType()
        result = t.compare(
            {
                "measurements": [{"metric": "latency", "value": "150", "unit": "ms"}],
                "window": "2024-Q1",
                "source_context": "APM"
            },
            {
                "measurements": [{"metric": "latency", "value": "200", "unit": "ms"}],
                "window": "2024-Q1",
                "source_context": "APM"
            }
        )
        assert not result.is_equal


class TestDecimalValidation:
    """Cross-cutting tests for decimal validation across all types."""

    @pytest.mark.parametrize("value", [
        float("nan"),
        float("inf"),
        float("-inf"),
        Decimal("NaN"),
        Decimal("Infinity"),
        Decimal("-Infinity"),
    ])
    def test_measurement_rejects_special_values(self, value: Any) -> None:
        """All measurement types should reject NaN and infinity."""
        t = MeasurementType()
        result = t.validate({"value": value, "unit": "ms"})
        assert not result.is_valid

    @pytest.mark.parametrize("value,expected", [
        ("100", "100"),
        ("100.0", "100"),
        ("100.00", "100"),
        ("100.50", "100.5"),
        ("0.001", "0.001"),
        ("-50", "-50"),
        (100, "100"),
        (100.5, "100.5"),
        (Decimal("100.50"), "100.5"),
    ])
    def test_decimal_normalization(self, value: Any, expected: str) -> None:
        """Decimal values should normalize consistently."""
        t = MeasurementType()
        result = t.normalize({"value": value, "unit": "ms"})
        assert result["value"] == expected


class TestQualifierValidation:
    """Tests for qualifier validation."""

    @pytest.mark.parametrize("qualifier", [
        "exact", "approximate", "minimum", "maximum",
        "average", "median", "p50", "p90", "p95", "p99", "p999",
        "peak", "baseline", "target", "threshold",
    ])
    def test_valid_qualifiers_accepted(self, qualifier: str) -> None:
        """All valid qualifiers should be accepted."""
        t = MeasurementType()
        result = t.validate({
            "value": "100",
            "unit": "ms",
            "qualifier": qualifier
        })
        assert result.is_valid

    def test_qualifier_case_insensitive(self) -> None:
        """Qualifier validation should be case-insensitive."""
        t = MeasurementType()
        result = t.validate({
            "value": "100",
            "unit": "ms",
            "qualifier": "P99"
        })
        assert result.is_valid

    def test_qualifier_normalized_to_lowercase(self) -> None:
        """Qualifier should be normalized to lowercase."""
        t = MeasurementType()
        result = t.normalize({
            "value": "100",
            "unit": "ms",
            "qualifier": "P99"
        })
        assert result["qualifier"] == "p99"
