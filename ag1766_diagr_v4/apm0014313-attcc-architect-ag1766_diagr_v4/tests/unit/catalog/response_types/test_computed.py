"""
Tests for computed response types (R05).

Tests cover:
- Valid and invalid shapes
- is_computed=True for computed types
- Direct save rejection for computed types
- Blank and unknown semantics
- Canonical serialization
- EVIDENCE_REFERENCE: editable (is_computed=False)
"""

from __future__ import annotations

import json

import pytest

from migration_intake.catalog.response_types.computed import (
    ApprovalRegisterType,
    DecisionRegisterType,
    EvidenceReferenceType,
    IssueRegisterType,
    RegisterStatusType,
    ValidationResultType,
)
from migration_intake.catalog.response_types.base import ResponseTypeCodes


class TestRegisterStatusType:
    """Tests for REGISTER_STATUS computed type."""

    def test_code_is_register_status(self) -> None:
        """Type code should be REGISTER_STATUS."""
        t = RegisterStatusType()
        assert t.code == ResponseTypeCodes.REGISTER_STATUS

    def test_is_computed_true(self) -> None:
        """REGISTER_STATUS should be computed (read-only)."""
        t = RegisterStatusType()
        assert t.is_computed is True

    def test_valid_shape(self) -> None:
        """Valid register status should pass validation."""
        t = RegisterStatusType()
        value = {
            "state": "IN_PROGRESS",
            "total": 10,
            "complete": 5,
            "blocking": 2,
        }
        result = t.validate(value)
        assert result.is_valid

    def test_valid_states(self) -> None:
        """All valid states should pass validation."""
        t = RegisterStatusType()
        for state in ["NOT_STARTED", "IN_PROGRESS", "COMPLETE", "BLOCKED"]:
            value = {"state": state, "total": 0, "complete": 0, "blocking": 0}
            result = t.validate(value)
            assert result.is_valid, f"State {state} should be valid"

    def test_invalid_state(self) -> None:
        """Invalid state should fail validation."""
        t = RegisterStatusType()
        value = {
            "state": "INVALID_STATE",
            "total": 10,
            "complete": 5,
            "blocking": 2,
        }
        result = t.validate(value)
        assert not result.is_valid
        assert "state" in result.field_errors

    def test_missing_required_field(self) -> None:
        """Missing required field should fail validation."""
        t = RegisterStatusType()
        value = {"state": "IN_PROGRESS", "total": 10}  # missing complete, blocking
        result = t.validate(value)
        assert not result.is_valid
        assert "complete" in result.field_errors
        assert "blocking" in result.field_errors

    def test_negative_count_invalid(self) -> None:
        """Negative counts should fail validation."""
        t = RegisterStatusType()
        value = {
            "state": "IN_PROGRESS",
            "total": -1,
            "complete": 0,
            "blocking": 0,
        }
        result = t.validate(value)
        assert not result.is_valid
        assert "total" in result.field_errors

    def test_complete_exceeds_total_invalid(self) -> None:
        """Complete count exceeding total should fail validation."""
        t = RegisterStatusType()
        value = {
            "state": "IN_PROGRESS",
            "total": 5,
            "complete": 10,
            "blocking": 0,
        }
        result = t.validate(value)
        assert not result.is_valid

    def test_rejects_form_parsing(self) -> None:
        """Computed type should reject form parsing."""
        t = RegisterStatusType()
        result = t.parse_form({"state": "COMPLETE"})
        assert not result.is_success
        assert "computed type" in result.errors[0].lower()

    def test_rejects_workbook_parsing(self) -> None:
        """Computed type should reject workbook parsing."""
        t = RegisterStatusType()
        result = t.parse_workbook("COMPLETE")
        assert not result.is_success
        assert "computed type" in result.errors[0].lower()

    def test_empty_value(self) -> None:
        """Empty value should be NOT_STARTED with zero counts."""
        t = RegisterStatusType()
        empty = t.empty_value()
        assert empty == {
            "state": "NOT_STARTED",
            "total": 0,
            "complete": 0,
            "blocking": 0,
        }

    def test_unknown_value(self) -> None:
        """Unknown value should have markers."""
        t = RegisterStatusType()
        unknown = t.unknown_value()
        assert unknown.get("_unknown") is True
        assert unknown.get("_computed") is True

    def test_normalize(self) -> None:
        """Normalize should produce consistent shape."""
        t = RegisterStatusType()
        value = {"state": "COMPLETE", "total": 5, "complete": 5, "blocking": 0}
        normalized = t.normalize(value)
        assert normalized == value

    def test_canonical_serialization(self) -> None:
        """Serialization should be deterministic with sorted keys."""
        t = RegisterStatusType()
        value = {
            "blocking": 1,
            "complete": 3,
            "state": "IN_PROGRESS",
            "total": 5,
        }
        serialized = t.serialize(value)
        # Keys should be sorted
        assert serialized == json.dumps(value, sort_keys=True, ensure_ascii=False)
        # Deserialize should round-trip
        assert t.deserialize(serialized) == value


class TestValidationResultType:
    """Tests for VALIDATION_RESULT computed type."""

    def test_code_is_validation_result(self) -> None:
        """Type code should be VALIDATION_RESULT."""
        t = ValidationResultType()
        assert t.code == ResponseTypeCodes.VALIDATION_RESULT

    def test_is_computed_true(self) -> None:
        """VALIDATION_RESULT should be computed (read-only)."""
        t = ValidationResultType()
        assert t.is_computed is True

    def test_valid_shape(self) -> None:
        """Valid validation result should pass validation."""
        t = ValidationResultType()
        value = {
            "state": "PASSED",
            "checks": [
                {"check_id": "CHK-001", "passed": True},
                {"check_id": "CHK-002", "passed": False, "message": "Failed check"},
            ],
        }
        result = t.validate(value)
        assert result.is_valid

    def test_valid_states(self) -> None:
        """All valid states should pass validation."""
        t = ValidationResultType()
        for state in ["PASSED", "FAILED", "PENDING", "NOT_APPLICABLE"]:
            value = {"state": state, "checks": []}
            result = t.validate(value)
            assert result.is_valid, f"State {state} should be valid"

    def test_invalid_state(self) -> None:
        """Invalid state should fail validation."""
        t = ValidationResultType()
        value = {"state": "INVALID", "checks": []}
        result = t.validate(value)
        assert not result.is_valid

    def test_missing_checks_field(self) -> None:
        """Missing checks field should fail validation."""
        t = ValidationResultType()
        value = {"state": "PASSED"}
        result = t.validate(value)
        assert not result.is_valid
        assert "checks" in result.field_errors

    def test_checks_must_be_array(self) -> None:
        """Checks field must be an array."""
        t = ValidationResultType()
        value = {"state": "PASSED", "checks": "not an array"}
        result = t.validate(value)
        assert not result.is_valid

    def test_check_missing_check_id(self) -> None:
        """Check without check_id should fail validation."""
        t = ValidationResultType()
        value = {"state": "PASSED", "checks": [{"passed": True}]}
        result = t.validate(value)
        assert not result.is_valid

    def test_check_missing_passed(self) -> None:
        """Check without passed field should fail validation."""
        t = ValidationResultType()
        value = {"state": "PASSED", "checks": [{"check_id": "CHK-001"}]}
        result = t.validate(value)
        assert not result.is_valid

    def test_check_passed_must_be_boolean(self) -> None:
        """Check passed field must be boolean."""
        t = ValidationResultType()
        value = {"state": "PASSED", "checks": [{"check_id": "CHK-001", "passed": "yes"}]}
        result = t.validate(value)
        assert not result.is_valid

    def test_rejects_form_parsing(self) -> None:
        """Computed type should reject form parsing."""
        t = ValidationResultType()
        result = t.parse_form({"state": "PASSED"})
        assert not result.is_success
        assert "computed type" in result.errors[0].lower()

    def test_rejects_workbook_parsing(self) -> None:
        """Computed type should reject workbook parsing."""
        t = ValidationResultType()
        result = t.parse_workbook("PASSED")
        assert not result.is_success
        assert "computed type" in result.errors[0].lower()

    def test_empty_value(self) -> None:
        """Empty value should be PENDING with empty checks."""
        t = ValidationResultType()
        empty = t.empty_value()
        assert empty == {"state": "PENDING", "checks": []}

    def test_unknown_value(self) -> None:
        """Unknown value should have markers."""
        t = ValidationResultType()
        unknown = t.unknown_value()
        assert unknown.get("_unknown") is True

    def test_canonical_serialization(self) -> None:
        """Serialization should be deterministic."""
        t = ValidationResultType()
        value = {"state": "PASSED", "checks": [{"check_id": "A", "passed": True}]}
        serialized = t.serialize(value)
        assert t.deserialize(serialized) == value


class TestIssueRegisterType:
    """Tests for ISSUE_REGISTER computed type."""

    def test_code_is_issue_register(self) -> None:
        """Type code should be ISSUE_REGISTER."""
        t = IssueRegisterType()
        assert t.code == ResponseTypeCodes.ISSUE_REGISTER

    def test_is_computed_true(self) -> None:
        """ISSUE_REGISTER should be computed (read-only)."""
        t = IssueRegisterType()
        assert t.is_computed is True

    def test_valid_shape(self) -> None:
        """Valid issue register should pass validation."""
        t = IssueRegisterType()
        value = {
            "total_issues": 5,
            "open_issues": 3,
            "blocking_issues": 1,
            "issue_refs": ["ISS-001", "ISS-002"],
        }
        result = t.validate(value)
        assert result.is_valid

    def test_missing_required_field(self) -> None:
        """Missing required field should fail validation."""
        t = IssueRegisterType()
        value = {"total_issues": 5, "open_issues": 3}
        result = t.validate(value)
        assert not result.is_valid

    def test_negative_count_invalid(self) -> None:
        """Negative counts should fail validation."""
        t = IssueRegisterType()
        value = {
            "total_issues": -1,
            "open_issues": 0,
            "blocking_issues": 0,
            "issue_refs": [],
        }
        result = t.validate(value)
        assert not result.is_valid

    def test_issue_refs_must_be_array(self) -> None:
        """Issue refs must be an array."""
        t = IssueRegisterType()
        value = {
            "total_issues": 1,
            "open_issues": 1,
            "blocking_issues": 0,
            "issue_refs": "not an array",
        }
        result = t.validate(value)
        assert not result.is_valid

    def test_rejects_form_parsing(self) -> None:
        """Computed type should reject form parsing."""
        t = IssueRegisterType()
        result = t.parse_form({})
        assert not result.is_success

    def test_rejects_workbook_parsing(self) -> None:
        """Computed type should reject workbook parsing."""
        t = IssueRegisterType()
        result = t.parse_workbook("data")
        assert not result.is_success

    def test_empty_value(self) -> None:
        """Empty value should have zero counts."""
        t = IssueRegisterType()
        empty = t.empty_value()
        assert empty == {
            "total_issues": 0,
            "open_issues": 0,
            "blocking_issues": 0,
            "issue_refs": [],
        }

    def test_unknown_value(self) -> None:
        """Unknown value should have markers."""
        t = IssueRegisterType()
        unknown = t.unknown_value()
        assert unknown.get("_unknown") is True


class TestDecisionRegisterType:
    """Tests for DECISION_REGISTER computed type."""

    def test_code_is_decision_register(self) -> None:
        """Type code should be DECISION_REGISTER."""
        t = DecisionRegisterType()
        assert t.code == ResponseTypeCodes.DECISION_REGISTER

    def test_is_computed_true(self) -> None:
        """DECISION_REGISTER should be computed (read-only)."""
        t = DecisionRegisterType()
        assert t.is_computed is True

    def test_valid_shape(self) -> None:
        """Valid decision register should pass validation."""
        t = DecisionRegisterType()
        value = {
            "total_decisions": 3,
            "pending_decisions": 1,
            "decision_refs": ["DEC-001"],
        }
        result = t.validate(value)
        assert result.is_valid

    def test_missing_required_field(self) -> None:
        """Missing required field should fail validation."""
        t = DecisionRegisterType()
        value = {"total_decisions": 3}
        result = t.validate(value)
        assert not result.is_valid

    def test_negative_count_invalid(self) -> None:
        """Negative counts should fail validation."""
        t = DecisionRegisterType()
        value = {
            "total_decisions": -1,
            "pending_decisions": 0,
            "decision_refs": [],
        }
        result = t.validate(value)
        assert not result.is_valid

    def test_decision_refs_must_be_array(self) -> None:
        """Decision refs must be an array."""
        t = DecisionRegisterType()
        value = {
            "total_decisions": 1,
            "pending_decisions": 0,
            "decision_refs": "not an array",
        }
        result = t.validate(value)
        assert not result.is_valid

    def test_rejects_form_parsing(self) -> None:
        """Computed type should reject form parsing."""
        t = DecisionRegisterType()
        result = t.parse_form({})
        assert not result.is_success

    def test_rejects_workbook_parsing(self) -> None:
        """Computed type should reject workbook parsing."""
        t = DecisionRegisterType()
        result = t.parse_workbook("data")
        assert not result.is_success

    def test_empty_value(self) -> None:
        """Empty value should have zero counts."""
        t = DecisionRegisterType()
        empty = t.empty_value()
        assert empty == {
            "total_decisions": 0,
            "pending_decisions": 0,
            "decision_refs": [],
        }

    def test_unknown_value(self) -> None:
        """Unknown value should have markers."""
        t = DecisionRegisterType()
        unknown = t.unknown_value()
        assert unknown.get("_unknown") is True


class TestApprovalRegisterType:
    """Tests for APPROVAL_REGISTER computed type."""

    def test_code_is_approval_register(self) -> None:
        """Type code should be APPROVAL_REGISTER."""
        t = ApprovalRegisterType()
        assert t.code == ResponseTypeCodes.APPROVAL_REGISTER

    def test_is_computed_true(self) -> None:
        """APPROVAL_REGISTER should be computed (read-only)."""
        t = ApprovalRegisterType()
        assert t.is_computed is True

    def test_valid_shape(self) -> None:
        """Valid approval register should pass validation."""
        t = ApprovalRegisterType()
        value = {
            "total_approvals": 4,
            "pending_approvals": 2,
            "approved_count": 2,
            "approval_refs": ["APR-001", "APR-002"],
        }
        result = t.validate(value)
        assert result.is_valid

    def test_missing_required_field(self) -> None:
        """Missing required field should fail validation."""
        t = ApprovalRegisterType()
        value = {"total_approvals": 4, "pending_approvals": 2}
        result = t.validate(value)
        assert not result.is_valid

    def test_negative_count_invalid(self) -> None:
        """Negative counts should fail validation."""
        t = ApprovalRegisterType()
        value = {
            "total_approvals": -1,
            "pending_approvals": 0,
            "approved_count": 0,
            "approval_refs": [],
        }
        result = t.validate(value)
        assert not result.is_valid

    def test_approval_refs_must_be_array(self) -> None:
        """Approval refs must be an array."""
        t = ApprovalRegisterType()
        value = {
            "total_approvals": 1,
            "pending_approvals": 0,
            "approved_count": 1,
            "approval_refs": "not an array",
        }
        result = t.validate(value)
        assert not result.is_valid

    def test_rejects_form_parsing(self) -> None:
        """Computed type should reject form parsing."""
        t = ApprovalRegisterType()
        result = t.parse_form({})
        assert not result.is_success

    def test_rejects_workbook_parsing(self) -> None:
        """Computed type should reject workbook parsing."""
        t = ApprovalRegisterType()
        result = t.parse_workbook("data")
        assert not result.is_success

    def test_empty_value(self) -> None:
        """Empty value should have zero counts."""
        t = ApprovalRegisterType()
        empty = t.empty_value()
        assert empty == {
            "total_approvals": 0,
            "pending_approvals": 0,
            "approved_count": 0,
            "approval_refs": [],
        }

    def test_unknown_value(self) -> None:
        """Unknown value should have markers."""
        t = ApprovalRegisterType()
        unknown = t.unknown_value()
        assert unknown.get("_unknown") is True


class TestEvidenceReferenceType:
    """Tests for EVIDENCE_REFERENCE type (editable, not computed)."""

    def test_code_is_evidence_reference(self) -> None:
        """Type code should be EVIDENCE_REFERENCE."""
        t = EvidenceReferenceType()
        assert t.code == ResponseTypeCodes.EVIDENCE_REFERENCE

    def test_is_computed_false(self) -> None:
        """EVIDENCE_REFERENCE should NOT be computed (is editable)."""
        t = EvidenceReferenceType()
        assert t.is_computed is False

    def test_valid_shape_minimal(self) -> None:
        """Valid evidence reference with only required field."""
        t = EvidenceReferenceType()
        value = {"evidence_version_id": "abc-123-def"}
        result = t.validate(value)
        assert result.is_valid

    def test_valid_shape_full(self) -> None:
        """Valid evidence reference with all fields."""
        t = EvidenceReferenceType()
        value = {
            "evidence_version_id": "abc-123-def",
            "locator": "page 5, section 2.1",
            "description": "Network diagram showing connectivity",
        }
        result = t.validate(value)
        assert result.is_valid

    def test_missing_evidence_version_id(self) -> None:
        """Missing evidence_version_id should fail validation."""
        t = EvidenceReferenceType()
        value = {"locator": "page 5"}
        result = t.validate(value)
        assert not result.is_valid
        assert "evidence_version_id" in result.field_errors

    def test_empty_evidence_version_id_invalid(self) -> None:
        """Empty evidence_version_id should fail validation."""
        t = EvidenceReferenceType()
        value = {"evidence_version_id": ""}
        result = t.validate(value)
        assert not result.is_valid

    def test_evidence_version_id_must_be_string(self) -> None:
        """evidence_version_id must be a string."""
        t = EvidenceReferenceType()
        value = {"evidence_version_id": 12345}
        result = t.validate(value)
        assert not result.is_valid

    def test_locator_must_be_string(self) -> None:
        """locator must be a string if provided."""
        t = EvidenceReferenceType()
        value = {"evidence_version_id": "abc-123", "locator": 123}
        result = t.validate(value)
        assert not result.is_valid

    def test_description_must_be_string(self) -> None:
        """description must be a string if provided."""
        t = EvidenceReferenceType()
        value = {"evidence_version_id": "abc-123", "description": ["not", "string"]}
        result = t.validate(value)
        assert not result.is_valid

    def test_accepts_form_parsing(self) -> None:
        """Editable type should accept form parsing."""
        t = EvidenceReferenceType()
        result = t.parse_form({
            "evidence_version_id": "abc-123",
            "locator": "page 1",
        })
        assert result.is_success
        assert result.value["evidence_version_id"] == "abc-123"
        assert result.value["locator"] == "page 1"

    def test_accepts_workbook_parsing_string(self) -> None:
        """Editable type should accept workbook parsing with string."""
        t = EvidenceReferenceType()
        result = t.parse_workbook("abc-123-def")
        assert result.is_success
        assert result.value["evidence_version_id"] == "abc-123-def"

    def test_accepts_workbook_parsing_dict(self) -> None:
        """Editable type should accept workbook parsing with dict."""
        t = EvidenceReferenceType()
        result = t.parse_workbook({
            "evidence_version_id": "abc-123",
            "description": "Test evidence",
        })
        assert result.is_success
        assert result.value["evidence_version_id"] == "abc-123"

    def test_workbook_parsing_empty_string(self) -> None:
        """Empty string in workbook should return empty value."""
        t = EvidenceReferenceType()
        result = t.parse_workbook("   ")
        assert result.is_success
        assert result.value == {"evidence_version_id": None}

    def test_workbook_parsing_none(self) -> None:
        """None in workbook should return empty value."""
        t = EvidenceReferenceType()
        result = t.parse_workbook(None)
        assert result.is_success
        assert result.value == {"evidence_version_id": None}

    def test_workbook_parsing_invalid_type(self) -> None:
        """Invalid type in workbook should fail."""
        t = EvidenceReferenceType()
        result = t.parse_workbook(12345)
        assert not result.is_success

    def test_empty_value(self) -> None:
        """Empty value should have null evidence_version_id."""
        t = EvidenceReferenceType()
        empty = t.empty_value()
        assert empty == {"evidence_version_id": None}

    def test_unknown_value(self) -> None:
        """Unknown value should have marker."""
        t = EvidenceReferenceType()
        unknown = t.unknown_value()
        assert unknown.get("_unknown") is True

    def test_unknown_value_validates(self) -> None:
        """Unknown value should pass validation."""
        t = EvidenceReferenceType()
        unknown = t.unknown_value()
        result = t.validate(unknown)
        assert result.is_valid

    def test_normalize_trims_whitespace(self) -> None:
        """Normalize should trim whitespace from strings."""
        t = EvidenceReferenceType()
        value = {
            "evidence_version_id": "abc-123",
            "locator": "  page 5  ",
            "description": "  test  ",
        }
        normalized = t.normalize(value)
        assert normalized["locator"] == "page 5"
        assert normalized["description"] == "test"

    def test_canonical_serialization(self) -> None:
        """Serialization should be deterministic."""
        t = EvidenceReferenceType()
        value = {
            "evidence_version_id": "abc-123",
            "locator": "page 1",
            "description": "Test",
        }
        serialized = t.serialize(value)
        assert t.deserialize(serialized) == value


class TestComputedTypesComparison:
    """Tests for comparison behavior of computed types."""

    def test_register_status_comparison_equal(self) -> None:
        """Equal register status values should compare as equal."""
        t = RegisterStatusType()
        value = {"state": "COMPLETE", "total": 5, "complete": 5, "blocking": 0}
        result = t.compare(value, value.copy())
        assert result.is_equal

    def test_register_status_comparison_different(self) -> None:
        """Different register status values should compare as different."""
        t = RegisterStatusType()
        old = {"state": "IN_PROGRESS", "total": 5, "complete": 3, "blocking": 0}
        new = {"state": "COMPLETE", "total": 5, "complete": 5, "blocking": 0}
        result = t.compare(old, new)
        assert not result.is_equal
        assert len(result.differences) > 0

    def test_validation_result_comparison_equal(self) -> None:
        """Equal validation results should compare as equal."""
        t = ValidationResultType()
        value = {"state": "PASSED", "checks": []}
        result = t.compare(value, value.copy())
        assert result.is_equal

    def test_evidence_reference_comparison_equal(self) -> None:
        """Equal evidence references should compare as equal."""
        t = EvidenceReferenceType()
        value = {"evidence_version_id": "abc-123", "locator": "page 1"}
        result = t.compare(value, value.copy())
        assert result.is_equal

    def test_evidence_reference_comparison_different(self) -> None:
        """Different evidence references should compare as different."""
        t = EvidenceReferenceType()
        old = {"evidence_version_id": "abc-123"}
        new = {"evidence_version_id": "def-456"}
        result = t.compare(old, new)
        assert not result.is_equal


class TestComputedTypesNullHandling:
    """Tests for null/None handling in computed types."""

    def test_register_status_validates_none(self) -> None:
        """None value should pass validation."""
        t = RegisterStatusType()
        result = t.validate(None)
        assert result.is_valid

    def test_validation_result_validates_none(self) -> None:
        """None value should pass validation."""
        t = ValidationResultType()
        result = t.validate(None)
        assert result.is_valid

    def test_issue_register_validates_none(self) -> None:
        """None value should pass validation."""
        t = IssueRegisterType()
        result = t.validate(None)
        assert result.is_valid

    def test_decision_register_validates_none(self) -> None:
        """None value should pass validation."""
        t = DecisionRegisterType()
        result = t.validate(None)
        assert result.is_valid

    def test_approval_register_validates_none(self) -> None:
        """None value should pass validation."""
        t = ApprovalRegisterType()
        result = t.validate(None)
        assert result.is_valid

    def test_evidence_reference_validates_none(self) -> None:
        """None value should pass validation."""
        t = EvidenceReferenceType()
        result = t.validate(None)
        assert result.is_valid

    def test_normalize_none_returns_empty(self) -> None:
        """Normalizing None should return empty value."""
        t = RegisterStatusType()
        normalized = t.normalize(None)
        assert normalized == t.empty_value()


class TestEditorAndDisplayKeys:
    """Tests for editor and display key attributes."""

    def test_register_status_keys(self) -> None:
        """REGISTER_STATUS should have appropriate keys."""
        t = RegisterStatusType()
        assert t.editor_key == "register_status_display"
        assert t.display_key == "register_status_display"

    def test_validation_result_keys(self) -> None:
        """VALIDATION_RESULT should have appropriate keys."""
        t = ValidationResultType()
        assert t.editor_key == "validation_result_display"
        assert t.display_key == "validation_result_display"

    def test_issue_register_keys(self) -> None:
        """ISSUE_REGISTER should have appropriate keys."""
        t = IssueRegisterType()
        assert t.editor_key == "issue_register_display"
        assert t.display_key == "issue_register_display"

    def test_decision_register_keys(self) -> None:
        """DECISION_REGISTER should have appropriate keys."""
        t = DecisionRegisterType()
        assert t.editor_key == "decision_register_display"
        assert t.display_key == "decision_register_display"

    def test_approval_register_keys(self) -> None:
        """APPROVAL_REGISTER should have appropriate keys."""
        t = ApprovalRegisterType()
        assert t.editor_key == "approval_register_display"
        assert t.display_key == "approval_register_display"

    def test_evidence_reference_keys(self) -> None:
        """EVIDENCE_REFERENCE should have editor and display keys."""
        t = EvidenceReferenceType()
        assert t.editor_key == "evidence_reference_editor"
        assert t.display_key == "evidence_reference_display"


class TestSchemaVersions:
    """Tests for schema version attributes."""

    def test_all_computed_types_have_schema_version(self) -> None:
        """All computed types should have schema version 1.0."""
        types = [
            RegisterStatusType(),
            ValidationResultType(),
            IssueRegisterType(),
            DecisionRegisterType(),
            ApprovalRegisterType(),
            EvidenceReferenceType(),
        ]
        for t in types:
            assert t.schema_version == "1.0", f"{t.code} should have schema_version 1.0"
