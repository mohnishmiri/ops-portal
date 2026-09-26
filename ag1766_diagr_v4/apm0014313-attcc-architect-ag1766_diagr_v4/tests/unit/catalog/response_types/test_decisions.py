"""
Tests for R04 decision response types.

Tests cover:
- Valid and invalid shapes
- Blank and unknown semantics
- HTML form parsing
- Workbook parsing
- Semantic comparison/no-op detection
- Canonical serialization
- APPROVAL: is_computed=True (rejects direct save)
"""

from __future__ import annotations

import json
from typing import Any, Dict

import pytest

from migration_intake.catalog.response_types.base import ResponseTypeCodes
from migration_intake.catalog.response_types.decisions import (
    ApprovalType,
    BooleanWithRationaleType,
    ControlledSetType,
    DecisionWithPersonType,
    SingleSelectPerComponentType,
)


class TestBooleanWithRationaleType:
    """Tests for BOOLEAN_WITH_RATIONALE response type."""

    @pytest.fixture
    def response_type(self) -> BooleanWithRationaleType:
        return BooleanWithRationaleType()

    # --- Type metadata ---

    def test_code_is_boolean_with_rationale(self, response_type: BooleanWithRationaleType) -> None:
        """Type code should be BOOLEAN_WITH_RATIONALE."""
        assert response_type.code == ResponseTypeCodes.BOOLEAN_WITH_RATIONALE

    def test_is_not_computed(self, response_type: BooleanWithRationaleType) -> None:
        """BOOLEAN_WITH_RATIONALE is not computed (allows direct save)."""
        assert response_type.is_computed is False

    def test_has_editor_key(self, response_type: BooleanWithRationaleType) -> None:
        """Type should have editor key for UI template."""
        assert response_type.editor_key == "boolean_with_rationale_editor"

    def test_has_display_key(self, response_type: BooleanWithRationaleType) -> None:
        """Type should have display key for read-only rendering."""
        assert response_type.display_key == "boolean_with_rationale_display"

    # --- Valid shapes ---

    def test_validate_yes_with_rationale(self, response_type: BooleanWithRationaleType) -> None:
        """YES with rationale should be valid."""
        value = {"value": "YES", "rationale": "Policy requires this"}
        result = response_type.validate(value)
        assert result.is_valid

    def test_validate_no_with_rationale(self, response_type: BooleanWithRationaleType) -> None:
        """NO with rationale should be valid."""
        value = {"value": "NO", "rationale": "Not applicable to this app"}
        result = response_type.validate(value)
        assert result.is_valid

    def test_validate_unknown_without_rationale(self, response_type: BooleanWithRationaleType) -> None:
        """UNKNOWN without rationale should be valid."""
        value = {"value": "UNKNOWN"}
        result = response_type.validate(value)
        assert result.is_valid

    def test_validate_none_is_valid(self, response_type: BooleanWithRationaleType) -> None:
        """None value should be valid (empty)."""
        result = response_type.validate(None)
        assert result.is_valid

    # --- Invalid shapes ---

    def test_validate_yes_without_rationale_invalid(self, response_type: BooleanWithRationaleType) -> None:
        """YES without rationale should be invalid."""
        value = {"value": "YES"}
        result = response_type.validate(value)
        assert not result.is_valid
        assert "rationale" in str(result.errors).lower()

    def test_validate_no_without_rationale_invalid(self, response_type: BooleanWithRationaleType) -> None:
        """NO without rationale should be invalid."""
        value = {"value": "NO", "rationale": ""}
        result = response_type.validate(value)
        assert not result.is_valid

    def test_validate_invalid_value(self, response_type: BooleanWithRationaleType) -> None:
        """Invalid value should fail validation."""
        value = {"value": "MAYBE", "rationale": "Some reason"}
        result = response_type.validate(value)
        assert not result.is_valid
        assert "value" in result.field_errors

    def test_validate_missing_value(self, response_type: BooleanWithRationaleType) -> None:
        """Missing value field should fail validation."""
        value = {"rationale": "Some reason"}
        result = response_type.validate(value)
        assert not result.is_valid

    # --- Blank and unknown semantics ---

    def test_empty_value_is_none(self, response_type: BooleanWithRationaleType) -> None:
        """Empty value should be None."""
        assert response_type.empty_value() is None

    def test_unknown_value_has_unknown_marker(self, response_type: BooleanWithRationaleType) -> None:
        """Unknown value should have UNKNOWN value."""
        unknown = response_type.unknown_value()
        assert unknown is not None
        assert unknown.get("value") == "UNKNOWN"

    def test_validate_unknown_marker(self, response_type: BooleanWithRationaleType) -> None:
        """_unknown marker should be valid."""
        value = {"_unknown": True}
        result = response_type.validate(value)
        assert result.is_valid

    # --- Normalization ---

    def test_normalize_trims_whitespace(self, response_type: BooleanWithRationaleType) -> None:
        """Normalize should trim whitespace."""
        value = {"value": "  yes  ", "rationale": "  Some reason  "}
        normalized = response_type.normalize(value)
        assert normalized["value"] == "YES"
        assert normalized["rationale"] == "Some reason"

    def test_normalize_uppercases_value(self, response_type: BooleanWithRationaleType) -> None:
        """Normalize should uppercase value."""
        value = {"value": "yes", "rationale": "reason"}
        normalized = response_type.normalize(value)
        assert normalized["value"] == "YES"

    def test_normalize_unknown_marker(self, response_type: BooleanWithRationaleType) -> None:
        """Normalize should preserve _unknown marker."""
        value = {"_unknown": True}
        normalized = response_type.normalize(value)
        assert normalized == {"_unknown": True}

    # --- Form parsing ---

    def test_parse_form_valid(self, response_type: BooleanWithRationaleType) -> None:
        """Form parsing should extract value and rationale."""
        form_data = {"value": "yes", "rationale": "Policy reason"}
        result = response_type.parse_form(form_data)
        assert result.is_success
        assert result.value["value"] == "YES"
        assert result.value["rationale"] == "Policy reason"

    def test_parse_form_preserves_raw_input(self, response_type: BooleanWithRationaleType) -> None:
        """Form parsing should preserve raw input."""
        form_data = {"value": "YES", "rationale": "reason"}
        result = response_type.parse_form(form_data)
        assert result.raw_input == form_data

    # --- Workbook parsing ---

    def test_parse_workbook_value_with_rationale(self, response_type: BooleanWithRationaleType) -> None:
        """Workbook parsing should handle 'VALUE: rationale' format."""
        result = response_type.parse_workbook("YES: Policy requires this")
        assert result.is_success
        assert result.value["value"] == "YES"
        assert result.value["rationale"] == "Policy requires this"

    def test_parse_workbook_value_only(self, response_type: BooleanWithRationaleType) -> None:
        """Workbook parsing should handle value only."""
        result = response_type.parse_workbook("NO")
        assert result.is_success
        assert result.value["value"] == "NO"

    def test_parse_workbook_empty(self, response_type: BooleanWithRationaleType) -> None:
        """Workbook parsing should handle empty cell."""
        result = response_type.parse_workbook("")
        assert result.is_success

    def test_parse_workbook_invalid_format(self, response_type: BooleanWithRationaleType) -> None:
        """Workbook parsing should reject invalid format."""
        result = response_type.parse_workbook("MAYBE: some reason")
        assert not result.is_success

    # --- Comparison ---

    def test_compare_equal_values(self, response_type: BooleanWithRationaleType) -> None:
        """Equal values should compare as equal."""
        old = {"value": "YES", "rationale": "reason"}
        new = {"value": "YES", "rationale": "reason"}
        result = response_type.compare(old, new)
        assert result.is_equal
        assert result.is_noop

    def test_compare_different_value(self, response_type: BooleanWithRationaleType) -> None:
        """Different values should compare as different."""
        old = {"value": "YES", "rationale": "reason"}
        new = {"value": "NO", "rationale": "reason"}
        result = response_type.compare(old, new)
        assert not result.is_equal
        assert any(d["field"] == "value" for d in result.differences)

    def test_compare_different_rationale(self, response_type: BooleanWithRationaleType) -> None:
        """Different rationale should compare as different."""
        old = {"value": "YES", "rationale": "old reason"}
        new = {"value": "YES", "rationale": "new reason"}
        result = response_type.compare(old, new)
        assert not result.is_equal
        assert any(d["field"] == "rationale" for d in result.differences)

    def test_compare_whitespace_normalized(self, response_type: BooleanWithRationaleType) -> None:
        """Whitespace differences should be normalized before comparison."""
        old = {"value": "  YES  ", "rationale": "reason"}
        new = {"value": "YES", "rationale": "reason"}
        result = response_type.compare(old, new)
        assert result.is_equal

    # --- Serialization ---

    def test_serialize_canonical(self, response_type: BooleanWithRationaleType) -> None:
        """Serialization should produce canonical JSON."""
        value = {"value": "YES", "rationale": "reason"}
        serialized = response_type.serialize(value)
        # Should be valid JSON with sorted keys
        parsed = json.loads(serialized)
        assert parsed == value

    def test_deserialize_roundtrip(self, response_type: BooleanWithRationaleType) -> None:
        """Deserialize should roundtrip with serialize."""
        value = {"value": "YES", "rationale": "reason"}
        serialized = response_type.serialize(value)
        deserialized = response_type.deserialize(serialized)
        assert deserialized == value


class TestControlledSetType:
    """Tests for CONTROLLED_SET response type."""

    @pytest.fixture
    def response_type(self) -> ControlledSetType:
        return ControlledSetType()

    # --- Type metadata ---

    def test_code_is_controlled_set(self, response_type: ControlledSetType) -> None:
        """Type code should be CONTROLLED_SET."""
        assert response_type.code == ResponseTypeCodes.CONTROLLED_SET

    def test_is_not_computed(self, response_type: ControlledSetType) -> None:
        """CONTROLLED_SET is not computed."""
        assert response_type.is_computed is False

    # --- Valid shapes ---

    def test_validate_single_item(self, response_type: ControlledSetType) -> None:
        """Single item should be valid."""
        value = {"items": [{"code": "OUTPOST"}]}
        result = response_type.validate(value)
        assert result.is_valid

    def test_validate_multiple_items(self, response_type: ControlledSetType) -> None:
        """Multiple items with unique codes should be valid."""
        value = {"items": [
            {"code": "OUTPOST", "detail": "Primary target"},
            {"code": "AWS_REGION", "detail": "Backup"},
        ]}
        result = response_type.validate(value)
        assert result.is_valid

    def test_validate_items_with_scope(self, response_type: ControlledSetType) -> None:
        """Items with different scopes should be valid."""
        value = {"items": [
            {"code": "OUTPOST", "scope": {"environment": "PROD"}},
            {"code": "OUTPOST", "scope": {"environment": "DEV"}},
        ]}
        result = response_type.validate(value)
        assert result.is_valid

    def test_validate_empty_items(self, response_type: ControlledSetType) -> None:
        """Empty items list should be valid."""
        value = {"items": []}
        result = response_type.validate(value)
        assert result.is_valid

    def test_validate_none_is_valid(self, response_type: ControlledSetType) -> None:
        """None value should be valid."""
        result = response_type.validate(None)
        assert result.is_valid

    # --- Invalid shapes ---

    def test_validate_duplicate_code_invalid(self, response_type: ControlledSetType) -> None:
        """Duplicate codes without different scope should be invalid."""
        value = {"items": [
            {"code": "OUTPOST"},
            {"code": "OUTPOST"},
        ]}
        result = response_type.validate(value)
        assert not result.is_valid
        assert "duplicate" in str(result.errors).lower()

    def test_validate_missing_code_invalid(self, response_type: ControlledSetType) -> None:
        """Item without code should be invalid."""
        value = {"items": [{"detail": "Some detail"}]}
        result = response_type.validate(value)
        assert not result.is_valid

    def test_validate_items_not_list_invalid(self, response_type: ControlledSetType) -> None:
        """Items not being a list should be invalid."""
        value = {"items": "not a list"}
        result = response_type.validate(value)
        assert not result.is_valid

    # --- Blank and unknown semantics ---

    def test_empty_value_has_empty_items(self, response_type: ControlledSetType) -> None:
        """Empty value should have empty items list."""
        empty = response_type.empty_value()
        assert empty == {"items": []}

    def test_unknown_value_has_marker(self, response_type: ControlledSetType) -> None:
        """Unknown value should have _unknown marker."""
        unknown = response_type.unknown_value()
        assert unknown == {"_unknown": True}

    # --- Normalization ---

    def test_normalize_uppercases_codes(self, response_type: ControlledSetType) -> None:
        """Normalize should uppercase codes."""
        value = {"items": [{"code": "outpost", "detail": "  detail  "}]}
        normalized = response_type.normalize(value)
        assert normalized["items"][0]["code"] == "OUTPOST"
        assert normalized["items"][0]["detail"] == "detail"

    def test_normalize_sorts_by_code(self, response_type: ControlledSetType) -> None:
        """Normalize should sort items by code."""
        value = {"items": [
            {"code": "ZEBRA"},
            {"code": "ALPHA"},
        ]}
        normalized = response_type.normalize(value)
        assert normalized["items"][0]["code"] == "ALPHA"
        assert normalized["items"][1]["code"] == "ZEBRA"

    # --- Form parsing ---

    def test_parse_form_valid(self, response_type: ControlledSetType) -> None:
        """Form parsing should extract items."""
        form_data = {"items": [
            {"code": "outpost", "detail": "Primary"},
        ]}
        result = response_type.parse_form(form_data)
        assert result.is_success
        assert result.value["items"][0]["code"] == "OUTPOST"

    # --- Workbook parsing ---

    def test_parse_workbook_comma_separated(self, response_type: ControlledSetType) -> None:
        """Workbook parsing should handle comma-separated codes."""
        result = response_type.parse_workbook("OUTPOST, AWS_REGION")
        assert result.is_success
        assert len(result.value["items"]) == 2
        codes = [i["code"] for i in result.value["items"]]
        assert "OUTPOST" in codes
        assert "AWS_REGION" in codes

    def test_parse_workbook_with_details(self, response_type: ControlledSetType) -> None:
        """Workbook parsing should handle code: detail format."""
        result = response_type.parse_workbook("OUTPOST: Primary target; AWS_REGION: Backup")
        assert result.is_success
        assert len(result.value["items"]) == 2

    def test_parse_workbook_empty(self, response_type: ControlledSetType) -> None:
        """Workbook parsing should handle empty cell."""
        result = response_type.parse_workbook("")
        assert result.is_success
        assert result.value["items"] == []

    # --- Comparison ---

    def test_compare_equal_items(self, response_type: ControlledSetType) -> None:
        """Equal items should compare as equal."""
        old = {"items": [{"code": "OUTPOST"}]}
        new = {"items": [{"code": "OUTPOST"}]}
        result = response_type.compare(old, new)
        assert result.is_equal

    def test_compare_different_items(self, response_type: ControlledSetType) -> None:
        """Different items should compare as different."""
        old = {"items": [{"code": "OUTPOST"}]}
        new = {"items": [{"code": "AWS_REGION"}]}
        result = response_type.compare(old, new)
        assert not result.is_equal

    def test_compare_order_independent(self, response_type: ControlledSetType) -> None:
        """Comparison should be order-independent after normalization."""
        old = {"items": [{"code": "ZEBRA"}, {"code": "ALPHA"}]}
        new = {"items": [{"code": "ALPHA"}, {"code": "ZEBRA"}]}
        result = response_type.compare(old, new)
        assert result.is_equal

    # --- Serialization ---

    def test_serialize_canonical(self, response_type: ControlledSetType) -> None:
        """Serialization should produce canonical JSON."""
        value = {"items": [{"code": "OUTPOST"}]}
        serialized = response_type.serialize(value)
        parsed = json.loads(serialized)
        assert parsed == value


class TestSingleSelectPerComponentType:
    """Tests for SINGLE_SELECT_PER_COMPONENT response type."""

    @pytest.fixture
    def response_type(self) -> SingleSelectPerComponentType:
        return SingleSelectPerComponentType()

    # --- Type metadata ---

    def test_code_is_single_select_per_component(self, response_type: SingleSelectPerComponentType) -> None:
        """Type code should be SINGLE_SELECT_PER_COMPONENT."""
        assert response_type.code == ResponseTypeCodes.SINGLE_SELECT_PER_COMPONENT

    def test_is_not_computed(self, response_type: SingleSelectPerComponentType) -> None:
        """SINGLE_SELECT_PER_COMPONENT is not computed."""
        assert response_type.is_computed is False

    # --- Valid shapes ---

    def test_validate_single_component(self, response_type: SingleSelectPerComponentType) -> None:
        """Single component should be valid."""
        value = {"components": [
            {"component_key": "DB", "selection": "OUTPOST"}
        ]}
        result = response_type.validate(value)
        assert result.is_valid

    def test_validate_multiple_components(self, response_type: SingleSelectPerComponentType) -> None:
        """Multiple components with unique keys should be valid."""
        value = {"components": [
            {"component_key": "DB", "selection": "OUTPOST"},
            {"component_key": "APP", "selection": "AWS_REGION"},
        ]}
        result = response_type.validate(value)
        assert result.is_valid

    def test_validate_component_with_rationale(self, response_type: SingleSelectPerComponentType) -> None:
        """Component with rationale should be valid."""
        value = {"components": [
            {"component_key": "DB", "selection": "OUTPOST", "rationale": "Latency requirements"}
        ]}
        result = response_type.validate(value)
        assert result.is_valid

    # --- Invalid shapes ---

    def test_validate_duplicate_component_key_invalid(self, response_type: SingleSelectPerComponentType) -> None:
        """Duplicate component keys should be invalid."""
        value = {"components": [
            {"component_key": "DB", "selection": "OUTPOST"},
            {"component_key": "DB", "selection": "AWS_REGION"},
        ]}
        result = response_type.validate(value)
        assert not result.is_valid
        assert "duplicate" in str(result.errors).lower()

    def test_validate_missing_component_key_invalid(self, response_type: SingleSelectPerComponentType) -> None:
        """Missing component_key should be invalid."""
        value = {"components": [{"selection": "OUTPOST"}]}
        result = response_type.validate(value)
        assert not result.is_valid

    def test_validate_missing_selection_invalid(self, response_type: SingleSelectPerComponentType) -> None:
        """Missing selection should be invalid."""
        value = {"components": [{"component_key": "DB"}]}
        result = response_type.validate(value)
        assert not result.is_valid

    # --- Blank and unknown semantics ---

    def test_empty_value_has_empty_components(self, response_type: SingleSelectPerComponentType) -> None:
        """Empty value should have empty components list."""
        empty = response_type.empty_value()
        assert empty == {"components": []}

    def test_unknown_value_has_marker(self, response_type: SingleSelectPerComponentType) -> None:
        """Unknown value should have _unknown marker."""
        unknown = response_type.unknown_value()
        assert unknown == {"_unknown": True}

    # --- Normalization ---

    def test_normalize_uppercases_keys_and_selections(self, response_type: SingleSelectPerComponentType) -> None:
        """Normalize should uppercase component_key and selection."""
        value = {"components": [
            {"component_key": "db", "selection": "outpost", "rationale": "  reason  "}
        ]}
        normalized = response_type.normalize(value)
        assert normalized["components"][0]["component_key"] == "DB"
        assert normalized["components"][0]["selection"] == "OUTPOST"
        assert normalized["components"][0]["rationale"] == "reason"

    def test_normalize_sorts_by_component_key(self, response_type: SingleSelectPerComponentType) -> None:
        """Normalize should sort by component_key."""
        value = {"components": [
            {"component_key": "WEB", "selection": "X"},
            {"component_key": "APP", "selection": "Y"},
        ]}
        normalized = response_type.normalize(value)
        assert normalized["components"][0]["component_key"] == "APP"
        assert normalized["components"][1]["component_key"] == "WEB"

    # --- Form parsing ---

    def test_parse_form_valid(self, response_type: SingleSelectPerComponentType) -> None:
        """Form parsing should extract components."""
        form_data = {"components": [
            {"component_key": "db", "selection": "outpost"}
        ]}
        result = response_type.parse_form(form_data)
        assert result.is_success
        assert result.value["components"][0]["component_key"] == "DB"

    # --- Workbook parsing ---

    def test_parse_workbook_key_value_format(self, response_type: SingleSelectPerComponentType) -> None:
        """Workbook parsing should handle KEY=VALUE format."""
        result = response_type.parse_workbook("DB=OUTPOST; APP=AWS_REGION")
        assert result.is_success
        assert len(result.value["components"]) == 2

    def test_parse_workbook_with_rationale(self, response_type: SingleSelectPerComponentType) -> None:
        """Workbook parsing should handle KEY=VALUE: rationale format."""
        result = response_type.parse_workbook("DB=OUTPOST: Latency requirements")
        assert result.is_success
        assert result.value["components"][0]["rationale"] == "Latency requirements"

    def test_parse_workbook_empty(self, response_type: SingleSelectPerComponentType) -> None:
        """Workbook parsing should handle empty cell."""
        result = response_type.parse_workbook("")
        assert result.is_success
        assert result.value["components"] == []

    # --- Comparison ---

    def test_compare_equal_components(self, response_type: SingleSelectPerComponentType) -> None:
        """Equal components should compare as equal."""
        old = {"components": [{"component_key": "DB", "selection": "OUTPOST"}]}
        new = {"components": [{"component_key": "DB", "selection": "OUTPOST"}]}
        result = response_type.compare(old, new)
        assert result.is_equal

    def test_compare_different_selection(self, response_type: SingleSelectPerComponentType) -> None:
        """Different selection should compare as different."""
        old = {"components": [{"component_key": "DB", "selection": "OUTPOST"}]}
        new = {"components": [{"component_key": "DB", "selection": "AWS_REGION"}]}
        result = response_type.compare(old, new)
        assert not result.is_equal


class TestDecisionWithPersonType:
    """Tests for DECISION_WITH_PERSON response type."""

    @pytest.fixture
    def response_type(self) -> DecisionWithPersonType:
        return DecisionWithPersonType()

    # --- Type metadata ---

    def test_code_is_decision_with_person(self, response_type: DecisionWithPersonType) -> None:
        """Type code should be DECISION_WITH_PERSON."""
        assert response_type.code == ResponseTypeCodes.DECISION_WITH_PERSON

    def test_is_not_computed(self, response_type: DecisionWithPersonType) -> None:
        """DECISION_WITH_PERSON is not computed."""
        assert response_type.is_computed is False

    # --- Valid shapes ---

    def test_validate_decision_with_owner(self, response_type: DecisionWithPersonType) -> None:
        """Decision with owner should be valid."""
        value = {"decision": "APPROVED", "owner": "John Smith"}
        result = response_type.validate(value)
        assert result.is_valid

    def test_validate_with_rationale(self, response_type: DecisionWithPersonType) -> None:
        """Decision with rationale should be valid."""
        value = {
            "decision": "APPROVED",
            "owner": "John Smith",
            "rationale": "Meets all requirements"
        }
        result = response_type.validate(value)
        assert result.is_valid

    def test_validate_with_decided_at(self, response_type: DecisionWithPersonType) -> None:
        """Decision with decided_at should be valid."""
        value = {
            "decision": "APPROVED",
            "owner": "John Smith",
            "decided_at": "2024-01-15T10:30:00Z"
        }
        result = response_type.validate(value)
        assert result.is_valid

    def test_validate_none_is_valid(self, response_type: DecisionWithPersonType) -> None:
        """None value should be valid."""
        result = response_type.validate(None)
        assert result.is_valid

    # --- Invalid shapes ---

    def test_validate_missing_decision_invalid(self, response_type: DecisionWithPersonType) -> None:
        """Missing decision should be invalid."""
        value = {"owner": "John Smith"}
        result = response_type.validate(value)
        assert not result.is_valid
        assert "decision" in result.field_errors

    def test_validate_missing_owner_invalid(self, response_type: DecisionWithPersonType) -> None:
        """Missing owner should be invalid."""
        value = {"decision": "APPROVED"}
        result = response_type.validate(value)
        assert not result.is_valid
        assert "owner" in result.field_errors

    def test_validate_invalid_datetime_invalid(self, response_type: DecisionWithPersonType) -> None:
        """Invalid datetime format should be invalid."""
        value = {
            "decision": "APPROVED",
            "owner": "John Smith",
            "decided_at": "not-a-date"
        }
        result = response_type.validate(value)
        assert not result.is_valid
        assert "decided_at" in result.field_errors

    # --- Blank and unknown semantics ---

    def test_empty_value_is_none(self, response_type: DecisionWithPersonType) -> None:
        """Empty value should be None."""
        assert response_type.empty_value() is None

    def test_unknown_value_has_marker(self, response_type: DecisionWithPersonType) -> None:
        """Unknown value should have _unknown marker."""
        unknown = response_type.unknown_value()
        assert unknown == {"_unknown": True}

    # --- Normalization ---

    def test_normalize_uppercases_decision(self, response_type: DecisionWithPersonType) -> None:
        """Normalize should uppercase decision."""
        value = {"decision": "approved", "owner": "  John Smith  "}
        normalized = response_type.normalize(value)
        assert normalized["decision"] == "APPROVED"
        assert normalized["owner"] == "John Smith"

    def test_normalize_preserves_owner_case(self, response_type: DecisionWithPersonType) -> None:
        """Normalize should preserve owner name case."""
        value = {"decision": "APPROVED", "owner": "John Smith"}
        normalized = response_type.normalize(value)
        assert normalized["owner"] == "John Smith"

    # --- Form parsing ---

    def test_parse_form_valid(self, response_type: DecisionWithPersonType) -> None:
        """Form parsing should extract decision and owner."""
        form_data = {"decision": "approved", "owner": "John Smith"}
        result = response_type.parse_form(form_data)
        assert result.is_success
        assert result.value["decision"] == "APPROVED"
        assert result.value["owner"] == "John Smith"

    # --- Workbook parsing ---

    def test_parse_workbook_decision_by_owner(self, response_type: DecisionWithPersonType) -> None:
        """Workbook parsing should handle 'DECISION by Owner' format."""
        result = response_type.parse_workbook("APPROVED by John Smith")
        assert result.is_success
        assert result.value["decision"] == "APPROVED"
        assert result.value["owner"] == "John Smith"

    def test_parse_workbook_with_rationale(self, response_type: DecisionWithPersonType) -> None:
        """Workbook parsing should handle rationale."""
        result = response_type.parse_workbook("APPROVED by John Smith: Meets requirements")
        assert result.is_success
        assert result.value["rationale"] == "Meets requirements"

    def test_parse_workbook_empty(self, response_type: DecisionWithPersonType) -> None:
        """Workbook parsing should handle empty cell."""
        result = response_type.parse_workbook("")
        assert result.is_success

    def test_parse_workbook_invalid_format(self, response_type: DecisionWithPersonType) -> None:
        """Workbook parsing should reject invalid format."""
        result = response_type.parse_workbook("Just some text")
        assert not result.is_success

    # --- Comparison ---

    def test_compare_equal_values(self, response_type: DecisionWithPersonType) -> None:
        """Equal values should compare as equal."""
        old = {"decision": "APPROVED", "owner": "John Smith"}
        new = {"decision": "APPROVED", "owner": "John Smith"}
        result = response_type.compare(old, new)
        assert result.is_equal

    def test_compare_different_decision(self, response_type: DecisionWithPersonType) -> None:
        """Different decision should compare as different."""
        old = {"decision": "APPROVED", "owner": "John Smith"}
        new = {"decision": "REJECTED", "owner": "John Smith"}
        result = response_type.compare(old, new)
        assert not result.is_equal
        assert any(d["field"] == "decision" for d in result.differences)

    def test_compare_different_owner(self, response_type: DecisionWithPersonType) -> None:
        """Different owner should compare as different."""
        old = {"decision": "APPROVED", "owner": "John Smith"}
        new = {"decision": "APPROVED", "owner": "Jane Doe"}
        result = response_type.compare(old, new)
        assert not result.is_equal
        assert any(d["field"] == "owner" for d in result.differences)


class TestApprovalType:
    """Tests for APPROVAL response type."""

    @pytest.fixture
    def response_type(self) -> ApprovalType:
        return ApprovalType()

    # --- Type metadata ---

    def test_code_is_approval(self, response_type: ApprovalType) -> None:
        """Type code should be APPROVAL."""
        assert response_type.code == ResponseTypeCodes.APPROVAL

    def test_is_computed(self, response_type: ApprovalType) -> None:
        """APPROVAL is computed (rejects direct save)."""
        assert response_type.is_computed is True

    def test_has_editor_key(self, response_type: ApprovalType) -> None:
        """Type should have editor key."""
        assert response_type.editor_key == "approval_editor"

    def test_has_display_key(self, response_type: ApprovalType) -> None:
        """Type should have display key."""
        assert response_type.display_key == "approval_display"

    # --- Valid shapes ---

    def test_validate_complete_approval(self, response_type: ApprovalType) -> None:
        """Complete approval should be valid."""
        value = {
            "decision": "APPROVED",
            "decided_by": "admin_user",
            "decided_at": "2024-01-15T10:30:00Z",
            "rationale": "All requirements met",
            "evidence_refs": ["ev-001", "ev-002"]
        }
        result = response_type.validate(value)
        assert result.is_valid

    def test_validate_minimal_approval(self, response_type: ApprovalType) -> None:
        """Minimal approval (required fields only) should be valid."""
        value = {
            "decision": "APPROVED",
            "decided_by": "admin_user",
            "decided_at": "2024-01-15T10:30:00Z"
        }
        result = response_type.validate(value)
        assert result.is_valid

    def test_validate_rejected_decision(self, response_type: ApprovalType) -> None:
        """REJECTED decision should be valid."""
        value = {
            "decision": "REJECTED",
            "decided_by": "admin_user",
            "decided_at": "2024-01-15T10:30:00Z"
        }
        result = response_type.validate(value)
        assert result.is_valid

    def test_validate_none_is_valid(self, response_type: ApprovalType) -> None:
        """None value should be valid."""
        result = response_type.validate(None)
        assert result.is_valid

    # --- Invalid shapes ---

    def test_validate_missing_decision_invalid(self, response_type: ApprovalType) -> None:
        """Missing decision should be invalid."""
        value = {
            "decided_by": "admin_user",
            "decided_at": "2024-01-15T10:30:00Z"
        }
        result = response_type.validate(value)
        assert not result.is_valid
        assert "decision" in result.field_errors

    def test_validate_invalid_decision_invalid(self, response_type: ApprovalType) -> None:
        """Invalid decision value should be invalid."""
        value = {
            "decision": "MAYBE",
            "decided_by": "admin_user",
            "decided_at": "2024-01-15T10:30:00Z"
        }
        result = response_type.validate(value)
        assert not result.is_valid
        assert "decision" in result.field_errors

    def test_validate_missing_decided_by_invalid(self, response_type: ApprovalType) -> None:
        """Missing decided_by should be invalid."""
        value = {
            "decision": "APPROVED",
            "decided_at": "2024-01-15T10:30:00Z"
        }
        result = response_type.validate(value)
        assert not result.is_valid
        assert "decided_by" in result.field_errors

    def test_validate_missing_decided_at_invalid(self, response_type: ApprovalType) -> None:
        """Missing decided_at should be invalid."""
        value = {
            "decision": "APPROVED",
            "decided_by": "admin_user"
        }
        result = response_type.validate(value)
        assert not result.is_valid
        assert "decided_at" in result.field_errors

    def test_validate_invalid_datetime_invalid(self, response_type: ApprovalType) -> None:
        """Invalid datetime format should be invalid."""
        value = {
            "decision": "APPROVED",
            "decided_by": "admin_user",
            "decided_at": "not-a-date"
        }
        result = response_type.validate(value)
        assert not result.is_valid
        assert "decided_at" in result.field_errors

    def test_validate_evidence_refs_not_list_invalid(self, response_type: ApprovalType) -> None:
        """evidence_refs not being a list should be invalid."""
        value = {
            "decision": "APPROVED",
            "decided_by": "admin_user",
            "decided_at": "2024-01-15T10:30:00Z",
            "evidence_refs": "not-a-list"
        }
        result = response_type.validate(value)
        assert not result.is_valid
        assert "evidence_refs" in result.field_errors

    # --- Blank and unknown semantics ---

    def test_empty_value_is_none(self, response_type: ApprovalType) -> None:
        """Empty value should be None."""
        assert response_type.empty_value() is None

    def test_unknown_value_has_marker(self, response_type: ApprovalType) -> None:
        """Unknown value should have _unknown marker."""
        unknown = response_type.unknown_value()
        assert unknown == {"_unknown": True}

    # --- Normalization ---

    def test_normalize_uppercases_decision(self, response_type: ApprovalType) -> None:
        """Normalize should uppercase decision."""
        value = {
            "decision": "approved",
            "decided_by": "  admin_user  ",
            "decided_at": "2024-01-15T10:30:00Z"
        }
        normalized = response_type.normalize(value)
        assert normalized["decision"] == "APPROVED"
        assert normalized["decided_by"] == "admin_user"

    # --- Form parsing ---

    def test_parse_form_valid(self, response_type: ApprovalType) -> None:
        """Form parsing should extract approval fields."""
        form_data = {
            "decision": "approved",
            "decided_by": "admin_user",
            "decided_at": "2024-01-15T10:30:00Z"
        }
        result = response_type.parse_form(form_data)
        assert result.is_success
        assert result.value["decision"] == "APPROVED"

    # --- Workbook parsing (REJECTS) ---

    def test_parse_workbook_rejects_import(self, response_type: ApprovalType) -> None:
        """Workbook parsing should reject all imports."""
        result = response_type.parse_workbook("APPROVED by admin")
        assert not result.is_success
        assert "cannot be imported" in result.errors[0].lower()

    def test_parse_workbook_rejects_empty(self, response_type: ApprovalType) -> None:
        """Workbook parsing should reject even empty cells."""
        result = response_type.parse_workbook("")
        assert not result.is_success

    def test_parse_workbook_rejects_none(self, response_type: ApprovalType) -> None:
        """Workbook parsing should reject None."""
        result = response_type.parse_workbook(None)
        assert not result.is_success

    # --- Comparison ---

    def test_compare_equal_approvals(self, response_type: ApprovalType) -> None:
        """Equal approvals should compare as equal."""
        old = {
            "decision": "APPROVED",
            "decided_by": "admin_user",
            "decided_at": "2024-01-15T10:30:00Z"
        }
        new = {
            "decision": "APPROVED",
            "decided_by": "admin_user",
            "decided_at": "2024-01-15T10:30:00Z"
        }
        result = response_type.compare(old, new)
        assert result.is_equal

    def test_compare_different_decision(self, response_type: ApprovalType) -> None:
        """Different decision should compare as different."""
        old = {
            "decision": "APPROVED",
            "decided_by": "admin_user",
            "decided_at": "2024-01-15T10:30:00Z"
        }
        new = {
            "decision": "REJECTED",
            "decided_by": "admin_user",
            "decided_at": "2024-01-15T10:30:00Z"
        }
        result = response_type.compare(old, new)
        assert not result.is_equal
        assert any(d["field"] == "decision" for d in result.differences)

    # --- Serialization ---

    def test_serialize_canonical(self, response_type: ApprovalType) -> None:
        """Serialization should produce canonical JSON."""
        value = {
            "decision": "APPROVED",
            "decided_by": "admin_user",
            "decided_at": "2024-01-15T10:30:00Z"
        }
        serialized = response_type.serialize(value)
        parsed = json.loads(serialized)
        assert parsed == value

    def test_deserialize_roundtrip(self, response_type: ApprovalType) -> None:
        """Deserialize should roundtrip with serialize."""
        value = {
            "decision": "APPROVED",
            "decided_by": "admin_user",
            "decided_at": "2024-01-15T10:30:00Z",
            "evidence_refs": ["ev-001"]
        }
        serialized = response_type.serialize(value)
        deserialized = response_type.deserialize(serialized)
        assert deserialized == value


class TestDecisionTypesRegistration:
    """Tests for registering decision types in the registry."""

    def test_all_decision_types_have_unique_codes(self) -> None:
        """All decision types should have unique codes."""
        types = [
            BooleanWithRationaleType(),
            ControlledSetType(),
            SingleSelectPerComponentType(),
            DecisionWithPersonType(),
            ApprovalType(),
        ]
        codes = [t.code for t in types]
        assert len(codes) == len(set(codes))

    def test_all_decision_types_have_schema_version(self) -> None:
        """All decision types should have schema version."""
        types = [
            BooleanWithRationaleType(),
            ControlledSetType(),
            SingleSelectPerComponentType(),
            DecisionWithPersonType(),
            ApprovalType(),
        ]
        for t in types:
            assert t.schema_version == "1.0"

    def test_only_approval_is_computed(self) -> None:
        """Only APPROVAL should be computed."""
        assert BooleanWithRationaleType().is_computed is False
        assert ControlledSetType().is_computed is False
        assert SingleSelectPerComponentType().is_computed is False
        assert DecisionWithPersonType().is_computed is False
        assert ApprovalType().is_computed is True

    def test_register_all_decision_types(self) -> None:
        """All decision types should be registerable."""
        from migration_intake.catalog.response_types.registry import ResponseTypeRegistry

        registry = ResponseTypeRegistry()
        registry.register(BooleanWithRationaleType())
        registry.register(ControlledSetType())
        registry.register(SingleSelectPerComponentType())
        registry.register(DecisionWithPersonType())
        registry.register(ApprovalType())

        assert registry.count() == 5
        assert registry.get(ResponseTypeCodes.BOOLEAN_WITH_RATIONALE) is not None
        assert registry.get(ResponseTypeCodes.CONTROLLED_SET) is not None
        assert registry.get(ResponseTypeCodes.SINGLE_SELECT_PER_COMPONENT) is not None
        assert registry.get(ResponseTypeCodes.DECISION_WITH_PERSON) is not None
        assert registry.get(ResponseTypeCodes.APPROVAL) is not None

    def test_computed_types_filter(self) -> None:
        """Registry should correctly filter computed types."""
        from migration_intake.catalog.response_types.registry import ResponseTypeRegistry

        registry = ResponseTypeRegistry()
        registry.register(BooleanWithRationaleType())
        registry.register(ApprovalType())

        computed = registry.computed_types()
        editable = registry.editable_types()

        assert len(computed) == 1
        assert computed[0].code == ResponseTypeCodes.APPROVAL
        assert len(editable) == 1
        assert editable[0].code == ResponseTypeCodes.BOOLEAN_WITH_RATIONALE
