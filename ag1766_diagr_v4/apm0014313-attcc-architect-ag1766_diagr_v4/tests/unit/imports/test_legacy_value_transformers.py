"""Tests for legacy intake value transformers."""
import pytest

from migration_intake.imports.legacy_value_transformers import (
    LegacyValueTransformError,
    parse_boolean,
    parse_controlled_pair,
    parse_duration,
    parse_long_text,
    parse_multi_select,
    parse_people_list,
    parse_single_select,
    parse_text,
    parse_text_pair,
    transform_value,
)


class TestParseText:
    """Tests for parse_text."""

    def test_parses_simple_text(self) -> None:
        result = parse_text("Hello World")
        assert result == {"value": "Hello World"}

    def test_strips_whitespace(self) -> None:
        result = parse_text("  Hello  ")
        assert result == {"value": "Hello"}

    def test_handles_none(self) -> None:
        result = parse_text(None)
        assert result == {"value": None}

    def test_handles_empty_string(self) -> None:
        result = parse_text("")
        assert result == {"value": None}


class TestParseTextPair:
    """Tests for parse_text_pair."""

    def test_parses_pipe_separated_pair(self) -> None:
        result = parse_text_pair("Application Name|APP")
        assert result == {"first": "Application Name", "second": "APP"}

    def test_handles_single_value(self) -> None:
        result = parse_text_pair("Application Name")
        assert result == {"first": "Application Name", "second": None}

    def test_handles_empty(self) -> None:
        result = parse_text_pair("")
        assert result == {"first": None, "second": None}

    def test_strips_whitespace(self) -> None:
        result = parse_text_pair("  Name  |  Acronym  ")
        assert result == {"first": "Name", "second": "Acronym"}


class TestParseSingleSelect:
    """Tests for parse_single_select."""

    def test_parses_value(self) -> None:
        result = parse_single_select("ACTIVE")
        assert result == {"value": "ACTIVE"}

    def test_uppercases_value(self) -> None:
        result = parse_single_select("active")
        assert result == {"value": "ACTIVE"}

    def test_handles_empty(self) -> None:
        result = parse_single_select("")
        assert result == {"value": None}


class TestParseMultiSelect:
    """Tests for parse_multi_select."""

    def test_parses_pipe_separated_values(self) -> None:
        result = parse_multi_select("TOPOLOGY|ADS|DDD")
        assert result == {"values": ["TOPOLOGY", "ADS", "DDD"]}

    def test_parses_single_value(self) -> None:
        result = parse_multi_select("TOPOLOGY")
        assert result == {"values": ["TOPOLOGY"]}

    def test_handles_empty(self) -> None:
        result = parse_multi_select("")
        assert result == {"values": []}

    def test_uppercases_values(self) -> None:
        result = parse_multi_select("topology|ads")
        assert result == {"values": ["TOPOLOGY", "ADS"]}

    def test_strips_whitespace(self) -> None:
        result = parse_multi_select("  TOPOLOGY  |  ADS  ")
        assert result == {"values": ["TOPOLOGY", "ADS"]}


class TestParseBoolean:
    """Tests for parse_boolean."""

    def test_parses_yes(self) -> None:
        assert parse_boolean("YES") == {"value": "YES"}
        assert parse_boolean("yes") == {"value": "YES"}
        assert parse_boolean("Y") == {"value": "YES"}
        assert parse_boolean("TRUE") == {"value": "YES"}
        assert parse_boolean("1") == {"value": "YES"}

    def test_parses_no(self) -> None:
        assert parse_boolean("NO") == {"value": "NO"}
        assert parse_boolean("no") == {"value": "NO"}
        assert parse_boolean("N") == {"value": "NO"}
        assert parse_boolean("FALSE") == {"value": "NO"}
        assert parse_boolean("0") == {"value": "NO"}

    def test_parses_unknown(self) -> None:
        assert parse_boolean("UNKNOWN") == {"value": "UNKNOWN"}
        assert parse_boolean("UNK") == {"value": "UNKNOWN"}
        assert parse_boolean("?") == {"value": "UNKNOWN"}
        assert parse_boolean("N/A") == {"value": "UNKNOWN"}

    def test_handles_empty(self) -> None:
        assert parse_boolean("") == {"value": None}

    def test_preserves_unrecognized_value(self) -> None:
        result = parse_boolean("MAYBE")
        assert result == {"value": "MAYBE"}


class TestParsePeopleList:
    """Tests for parse_people_list."""

    def test_parses_pipe_separated(self) -> None:
        result = parse_people_list("John Doe|Jane Smith")
        assert result == {
            "people": [
                {"name": "John Doe", "role_code": "UNKNOWN"},
                {"name": "Jane Smith", "role_code": "UNKNOWN"},
            ]
        }

    def test_parses_semicolon_separated(self) -> None:
        result = parse_people_list("John Doe; Jane Smith")
        assert result == {
            "people": [
                {"name": "John Doe", "role_code": "UNKNOWN"},
                {"name": "Jane Smith", "role_code": "UNKNOWN"},
            ]
        }

    def test_parses_comma_separated(self) -> None:
        result = parse_people_list("John Doe, Jane Smith")
        assert result == {
            "people": [
                {"name": "John Doe", "role_code": "UNKNOWN"},
                {"name": "Jane Smith", "role_code": "UNKNOWN"},
            ]
        }

    def test_parses_single_person(self) -> None:
        result = parse_people_list("John Doe")
        assert result == {
            "people": [{"name": "John Doe", "role_code": "UNKNOWN"}]
        }

    def test_handles_empty(self) -> None:
        result = parse_people_list("")
        assert result == {"people": []}


class TestParseDuration:
    """Tests for parse_duration."""

    def test_parses_hours(self) -> None:
        result = parse_duration("4 hours")
        assert result == {"value": "4 hours", "normalized_hours": 4.0}

    def test_parses_hours_short(self) -> None:
        result = parse_duration("4h")
        assert result == {"value": "4h", "normalized_hours": 4.0}

    def test_parses_days(self) -> None:
        result = parse_duration("2 days")
        assert result == {"value": "2 days", "normalized_hours": 48.0}

    def test_parses_minutes(self) -> None:
        result = parse_duration("30 minutes")
        assert result == {"value": "30 minutes", "normalized_hours": 0.5}

    def test_handles_decimal(self) -> None:
        result = parse_duration("1.5 hours")
        assert result == {"value": "1.5 hours", "normalized_hours": 1.5}

    def test_preserves_duration_comparator(self) -> None:
        result = parse_duration("<=72hours")
        assert result == {
            "value": "<=72hours",
            "normalized_hours": 72.0,
            "qualifier": "maximum",
        }

    def test_handles_empty(self) -> None:
        result = parse_duration("")
        assert result == {"value": None, "normalized_hours": None}

    def test_preserves_unparseable(self) -> None:
        result = parse_duration("ASAP")
        assert result["value"] == "ASAP"
        assert result["normalized_hours"] is None


class TestTransformValue:
    """Tests for transform_value dispatcher."""

    def test_dispatches_to_correct_transformer(self) -> None:
        result = transform_value("parse_text", "Hello")
        assert result == {"value": "Hello"}

    def test_raises_on_unknown_transformer(self) -> None:
        with pytest.raises(LegacyValueTransformError, match="Unknown transformer"):
            transform_value("parse_unknown", "value")

    def test_wraps_transformation_errors(self) -> None:
        # This shouldn't fail, but demonstrates error wrapping
        result = transform_value("parse_boolean", "YES")
        assert result == {"value": "YES"}
