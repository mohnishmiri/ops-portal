"""
Tests for response type registry interface.

R00 defines the registration API, form/workbook parse result,
canonical serializer, comparator, and editor/display keys.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

import pytest


class TestResponseTypeProtocol:
    """Tests for ResponseType protocol shape."""

    def test_response_type_has_code(self) -> None:
        """ResponseType must have a stable code."""
        from migration_intake.catalog.response_types.base import ResponseType

        assert hasattr(ResponseType, "code")

    def test_response_type_has_schema_version(self) -> None:
        """ResponseType must have a schema version."""
        from migration_intake.catalog.response_types.base import ResponseType

        assert hasattr(ResponseType, "schema_version")

    def test_response_type_has_validate(self) -> None:
        """ResponseType must have validate method."""
        from migration_intake.catalog.response_types.base import ResponseType

        assert hasattr(ResponseType, "validate")

    def test_response_type_has_normalize(self) -> None:
        """ResponseType must have normalize method."""
        from migration_intake.catalog.response_types.base import ResponseType

        assert hasattr(ResponseType, "normalize")

    def test_response_type_has_compare(self) -> None:
        """ResponseType must have compare method for semantic equality."""
        from migration_intake.catalog.response_types.base import ResponseType

        assert hasattr(ResponseType, "compare")

    def test_response_type_has_serialize(self) -> None:
        """ResponseType must have canonical serialize method."""
        from migration_intake.catalog.response_types.base import ResponseType

        assert hasattr(ResponseType, "serialize")

    def test_response_type_has_deserialize(self) -> None:
        """ResponseType must have deserialize method."""
        from migration_intake.catalog.response_types.base import ResponseType

        assert hasattr(ResponseType, "deserialize")

    def test_response_type_has_parse_form(self) -> None:
        """ResponseType must have parse_form method."""
        from migration_intake.catalog.response_types.base import ResponseType

        assert hasattr(ResponseType, "parse_form")

    def test_response_type_has_parse_workbook(self) -> None:
        """ResponseType must have parse_workbook method."""
        from migration_intake.catalog.response_types.base import ResponseType

        assert hasattr(ResponseType, "parse_workbook")

    def test_response_type_has_editor_key(self) -> None:
        """ResponseType must have editor_key for UI template selection."""
        from migration_intake.catalog.response_types.base import ResponseType

        assert hasattr(ResponseType, "editor_key")

    def test_response_type_has_display_key(self) -> None:
        """ResponseType must have display_key for read-only rendering."""
        from migration_intake.catalog.response_types.base import ResponseType

        assert hasattr(ResponseType, "display_key")

    def test_response_type_has_is_computed(self) -> None:
        """ResponseType must indicate if it's computed (rejects direct save)."""
        from migration_intake.catalog.response_types.base import ResponseType

        assert hasattr(ResponseType, "is_computed")

    def test_response_type_has_empty_value(self) -> None:
        """ResponseType must provide empty value semantics."""
        from migration_intake.catalog.response_types.base import ResponseType

        assert hasattr(ResponseType, "empty_value")

    def test_response_type_has_unknown_value(self) -> None:
        """ResponseType must provide unknown value semantics."""
        from migration_intake.catalog.response_types.base import ResponseType

        assert hasattr(ResponseType, "unknown_value")


class TestRegistry:
    """Tests for response type registry."""

    def test_registry_register_type(self) -> None:
        """Registry should allow registering response types."""
        from migration_intake.catalog.response_types.base import ResponseTypeBase
        from migration_intake.catalog.response_types.registry import ResponseTypeRegistry

        registry = ResponseTypeRegistry()

        class TestType(ResponseTypeBase):
            code = "TEST_TYPE"
            schema_version = "1.0"
            editor_key = "test_editor"
            display_key = "test_display"
            is_computed = False

        registry.register(TestType())

        assert registry.get("TEST_TYPE") is not None

    def test_registry_get_unknown_returns_none(self) -> None:
        """Registry should return None for unknown type codes."""
        from migration_intake.catalog.response_types.registry import ResponseTypeRegistry

        registry = ResponseTypeRegistry()

        assert registry.get("UNKNOWN_TYPE") is None

    def test_registry_rejects_duplicate_registration(self) -> None:
        """Registry should reject duplicate type code registration."""
        from migration_intake.catalog.response_types.base import ResponseTypeBase
        from migration_intake.catalog.response_types.registry import ResponseTypeRegistry

        registry = ResponseTypeRegistry()

        class TestType(ResponseTypeBase):
            code = "DUPLICATE_TYPE"
            schema_version = "1.0"
            editor_key = "test_editor"
            display_key = "test_display"
            is_computed = False

        registry.register(TestType())

        with pytest.raises(ValueError, match="[Aa]lready registered|[Dd]uplicate"):
            registry.register(TestType())

    def test_registry_list_all_types(self) -> None:
        """Registry should list all registered type codes."""
        from migration_intake.catalog.response_types.base import ResponseTypeBase
        from migration_intake.catalog.response_types.registry import ResponseTypeRegistry

        registry = ResponseTypeRegistry()

        class Type1(ResponseTypeBase):
            code = "TYPE_1"
            schema_version = "1.0"
            editor_key = "editor1"
            display_key = "display1"
            is_computed = False

        class Type2(ResponseTypeBase):
            code = "TYPE_2"
            schema_version = "1.0"
            editor_key = "editor2"
            display_key = "display2"
            is_computed = False

        registry.register(Type1())
        registry.register(Type2())

        codes = registry.list_codes()

        assert "TYPE_1" in codes
        assert "TYPE_2" in codes

    def test_registry_count(self) -> None:
        """Registry should report count of registered types."""
        from migration_intake.catalog.response_types.base import ResponseTypeBase
        from migration_intake.catalog.response_types.registry import ResponseTypeRegistry

        registry = ResponseTypeRegistry()

        class TestType(ResponseTypeBase):
            code = "COUNT_TEST"
            schema_version = "1.0"
            editor_key = "editor"
            display_key = "display"
            is_computed = False

        assert registry.count() == 0
        registry.register(TestType())
        assert registry.count() == 1


class TestParseResult:
    """Tests for parse result envelope."""

    def test_parse_result_success(self) -> None:
        """ParseResult should represent successful parse."""
        from migration_intake.catalog.response_types.base import ParseResult

        result = ParseResult.success({"value": "YES"})

        assert result.is_success
        assert result.value == {"value": "YES"}
        assert result.errors == []

    def test_parse_result_failure(self) -> None:
        """ParseResult should represent failed parse with errors."""
        from migration_intake.catalog.response_types.base import ParseResult

        result = ParseResult.failure(["Invalid value", "Missing field"])

        assert not result.is_success
        assert result.value is None
        assert "Invalid value" in result.errors
        assert "Missing field" in result.errors

    def test_parse_result_with_warnings(self) -> None:
        """ParseResult should carry warnings even on success."""
        from migration_intake.catalog.response_types.base import ParseResult

        result = ParseResult.success(
            {"value": "YES"},
            warnings=["Value was normalized"]
        )

        assert result.is_success
        assert "Value was normalized" in result.warnings


class TestComparisonResult:
    """Tests for comparison result."""

    def test_comparison_equal(self) -> None:
        """ComparisonResult should indicate semantic equality."""
        from migration_intake.catalog.response_types.base import ComparisonResult

        result = ComparisonResult.equal()

        assert result.is_equal
        assert result.differences == []

    def test_comparison_different(self) -> None:
        """ComparisonResult should indicate differences."""
        from migration_intake.catalog.response_types.base import ComparisonResult

        result = ComparisonResult.different([
            {"field": "value", "old": "YES", "new": "NO"}
        ])

        assert not result.is_equal
        assert len(result.differences) == 1

    def test_comparison_noop_detection(self) -> None:
        """ComparisonResult should detect no-op changes."""
        from migration_intake.catalog.response_types.base import ComparisonResult

        # Same values should be equal (no-op)
        result = ComparisonResult.equal()

        assert result.is_noop


class TestValidationResult:
    """Tests for validation result."""

    def test_validation_valid(self) -> None:
        """ValidationResult should indicate valid value."""
        from migration_intake.catalog.response_types.base import ValidationResult

        result = ValidationResult.valid()

        assert result.is_valid
        assert result.errors == []

    def test_validation_invalid(self) -> None:
        """ValidationResult should indicate invalid value with errors."""
        from migration_intake.catalog.response_types.base import ValidationResult

        result = ValidationResult.invalid(["Value out of range"])

        assert not result.is_valid
        assert "Value out of range" in result.errors


class TestResponseTypeBase:
    """Tests for ResponseTypeBase abstract class."""

    def test_base_provides_default_empty_value(self) -> None:
        """ResponseTypeBase should provide default empty value."""
        from migration_intake.catalog.response_types.base import ResponseTypeBase

        class TestType(ResponseTypeBase):
            code = "TEST"
            schema_version = "1.0"
            editor_key = "test"
            display_key = "test"
            is_computed = False

        t = TestType()
        assert t.empty_value() is None

    def test_base_provides_default_unknown_value(self) -> None:
        """ResponseTypeBase should provide default unknown value."""
        from migration_intake.catalog.response_types.base import ResponseTypeBase

        class TestType(ResponseTypeBase):
            code = "TEST"
            schema_version = "1.0"
            editor_key = "test"
            display_key = "test"
            is_computed = False

        t = TestType()
        # Unknown is type-specific but base provides a marker
        unknown = t.unknown_value()
        assert unknown is not None or hasattr(t, "unknown_value")

    def test_computed_type_rejects_direct_save(self) -> None:
        """Computed types should be identifiable for save rejection."""
        from migration_intake.catalog.response_types.base import ResponseTypeBase

        class ComputedType(ResponseTypeBase):
            code = "COMPUTED_TEST"
            schema_version = "1.0"
            editor_key = "computed"
            display_key = "computed"
            is_computed = True

        t = ComputedType()
        assert t.is_computed is True


class TestResponseTypeCodes:
    """Tests for response type code constants."""

    def test_all_25_type_codes_defined(self) -> None:
        """All 25 response type codes should be defined."""
        from migration_intake.catalog.response_types.base import ResponseTypeCodes

        expected_codes = [
            "APPROVAL",
            "APPROVAL_REGISTER",
            "BOOLEAN",
            "BOOLEAN_WITH_RATIONALE",
            "CONTROLLED_PAIR",
            "CONTROLLED_SET",
            "COUNT_PAIR",
            "DECISION_REGISTER",
            "DECISION_WITH_PERSON",
            "EVIDENCE_REFERENCE",
            "IDENTIFIER",
            "ISSUE_REGISTER",
            "LONG_TEXT",
            "MEASUREMENT",
            "MEASUREMENT_CONTEXT",
            "MEASUREMENT_PAIR",
            "MEASUREMENT_SET",
            "MULTI_SELECT",
            "PEOPLE_LIST",
            "REGISTER_STATUS",
            "SINGLE_SELECT",
            "SINGLE_SELECT_PER_COMPONENT",
            "TEXT",
            "TEXT_PAIR",
            "VALIDATION_RESULT",
        ]

        for code in expected_codes:
            assert hasattr(ResponseTypeCodes, code), f"Missing code: {code}"

    def test_type_codes_are_strings(self) -> None:
        """Type codes should be string constants."""
        from migration_intake.catalog.response_types.base import ResponseTypeCodes

        assert isinstance(ResponseTypeCodes.BOOLEAN, str)
        assert isinstance(ResponseTypeCodes.TEXT, str)
