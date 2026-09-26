"""
Computed response types (R05).

This module implements the computed response types that are read-only
and derive their values from system state rather than direct user input:
- REGISTER_STATUS: Computed status linking to mapped work
- VALIDATION_RESULT: Computed deterministic result with blocker links
- ISSUE_REGISTER: Computed issue summary
- DECISION_REGISTER: Computed decision coverage
- APPROVAL_REGISTER: Computed approval coverage
- EVIDENCE_REFERENCE: Reference to evidence (editable, not computed)
"""

from __future__ import annotations

from typing import Any

from migration_intake.catalog.response_types.base import (
    ParseResult,
    ResponseTypeBase,
    ResponseTypeCodes,
    ValidationResult,
)


class RegisterStatusType(ResponseTypeBase):
    """
    Computed register status type.

    Canonical shape: {state, total, complete, blocking}

    This type represents a read-only status linking to mapped work.
    It rejects direct saves and is computed from system state.
    """

    code = ResponseTypeCodes.REGISTER_STATUS
    schema_version = "1.0"
    editor_key = "register_status_display"
    display_key = "register_status_display"
    is_computed = True

    # Valid states for register status
    VALID_STATES = frozenset({"NOT_STARTED", "IN_PROGRESS", "COMPLETE", "BLOCKED"})

    def validate(self, value: dict[str, Any]) -> ValidationResult:
        """
        Validate register status value.

        Required fields: state, total, complete, blocking
        """
        if value is None:
            return ValidationResult.valid()

        errors: list[str] = []
        field_errors: dict[str, list[str]] = {}

        # Check required fields
        required_fields = ["state", "total", "complete", "blocking"]
        for field in required_fields:
            if field not in value:
                errors.append(f"Missing required field: {field}")
                field_errors[field] = [f"Field '{field}' is required"]

        # Validate state if present
        if "state" in value:
            state = value["state"]
            if state not in self.VALID_STATES:
                errors.append(f"Invalid state: {state}")
                field_errors["state"] = [
                    f"State must be one of: {', '.join(sorted(self.VALID_STATES))}"
                ]

        # Validate numeric fields
        for field in ["total", "complete", "blocking"]:
            if field in value:
                val = value[field]
                if not isinstance(val, int) or val < 0:
                    errors.append(f"Field '{field}' must be a non-negative integer")
                    field_errors[field] = ["Must be a non-negative integer"]

        # Validate complete <= total
        if "total" in value and "complete" in value:
            if (
                isinstance(value["total"], int)
                and isinstance(value["complete"], int)
                and value["complete"] > value["total"]
            ):
                errors.append("Complete count cannot exceed total count")
                field_errors["complete"] = ["Cannot exceed total count"]

        if errors:
            return ValidationResult.invalid(errors, field_errors)
        return ValidationResult.valid()

    def normalize(self, value: dict[str, Any]) -> dict[str, Any]:
        """Normalize register status value."""
        if value is None:
            return self.empty_value() or {}
        return {
            "state": value.get("state", "NOT_STARTED"),
            "total": value.get("total", 0),
            "complete": value.get("complete", 0),
            "blocking": value.get("blocking", 0),
        }

    def parse_form(self, form_data: dict[str, Any]) -> ParseResult:
        """
        Reject form parsing for computed type.

        Computed types cannot be directly saved from forms.
        """
        return ParseResult.failure(
            ["REGISTER_STATUS is a computed type and cannot be directly saved"],
            raw_input=form_data,
        )

    def parse_workbook(
        self, cell_value: Any, context: dict[str, Any] | None = None
    ) -> ParseResult:
        """
        Reject workbook parsing for computed type.

        Computed types cannot be imported from workbooks.
        """
        return ParseResult.failure(
            ["REGISTER_STATUS is a computed type and cannot be imported from workbook"],
            raw_input=cell_value,
        )

    def empty_value(self) -> dict[str, Any] | None:
        """Return empty register status."""
        return {
            "state": "NOT_STARTED",
            "total": 0,
            "complete": 0,
            "blocking": 0,
        }

    def unknown_value(self) -> dict[str, Any] | None:
        """Return unknown marker for computed type."""
        return {"_unknown": True, "_computed": True}


class ValidationResultType(ResponseTypeBase):
    """
    Computed validation result type.

    Canonical shape: {state, checks: [{check_id, passed, message?, blocker_ref?}]}

    This type represents a read-only deterministic validation result
    with blocker links. It rejects direct saves.
    """

    code = ResponseTypeCodes.VALIDATION_RESULT
    schema_version = "1.0"
    editor_key = "validation_result_display"
    display_key = "validation_result_display"
    is_computed = True

    # Valid states for validation result
    VALID_STATES = frozenset({"PASSED", "FAILED", "PENDING", "NOT_APPLICABLE"})

    def validate(self, value: dict[str, Any]) -> ValidationResult:
        """
        Validate validation result value.

        Required fields: state, checks
        """
        if value is None:
            return ValidationResult.valid()

        errors: list[str] = []
        field_errors: dict[str, list[str]] = {}

        # Check required fields
        if "state" not in value:
            errors.append("Missing required field: state")
            field_errors["state"] = ["Field 'state' is required"]

        if "checks" not in value:
            errors.append("Missing required field: checks")
            field_errors["checks"] = ["Field 'checks' is required"]

        # Validate state
        if "state" in value:
            state = value["state"]
            if state not in self.VALID_STATES:
                errors.append(f"Invalid state: {state}")
                field_errors["state"] = [
                    f"State must be one of: {', '.join(sorted(self.VALID_STATES))}"
                ]

        # Validate checks array
        if "checks" in value:
            checks = value["checks"]
            if not isinstance(checks, list):
                errors.append("Field 'checks' must be an array")
                field_errors["checks"] = ["Must be an array"]
            else:
                for i, check in enumerate(checks):
                    if not isinstance(check, dict):
                        errors.append(f"Check at index {i} must be an object")
                    elif "check_id" not in check:
                        errors.append(f"Check at index {i} missing 'check_id'")
                    elif "passed" not in check:
                        errors.append(f"Check at index {i} missing 'passed'")
                    elif not isinstance(check["passed"], bool):
                        errors.append(f"Check at index {i} 'passed' must be boolean")

        if errors:
            return ValidationResult.invalid(errors, field_errors)
        return ValidationResult.valid()

    def normalize(self, value: dict[str, Any]) -> dict[str, Any]:
        """Normalize validation result value."""
        if value is None:
            return self.empty_value() or {}
        return {
            "state": value.get("state", "PENDING"),
            "checks": value.get("checks", []),
        }

    def parse_form(self, form_data: dict[str, Any]) -> ParseResult:
        """Reject form parsing for computed type."""
        return ParseResult.failure(
            ["VALIDATION_RESULT is a computed type and cannot be directly saved"],
            raw_input=form_data,
        )

    def parse_workbook(
        self, cell_value: Any, context: dict[str, Any] | None = None
    ) -> ParseResult:
        """Reject workbook parsing for computed type."""
        return ParseResult.failure(
            ["VALIDATION_RESULT is a computed type and cannot be imported from workbook"],
            raw_input=cell_value,
        )

    def empty_value(self) -> dict[str, Any] | None:
        """Return empty validation result."""
        return {
            "state": "PENDING",
            "checks": [],
        }

    def unknown_value(self) -> dict[str, Any] | None:
        """Return unknown marker for computed type."""
        return {"_unknown": True, "_computed": True}


class IssueRegisterType(ResponseTypeBase):
    """
    Computed issue register type.

    Canonical shape: {total_issues, open_issues, blocking_issues, issue_refs: [...]}

    This type represents a read-only blocker summary and issue link.
    It rejects direct saves.
    """

    code = ResponseTypeCodes.ISSUE_REGISTER
    schema_version = "1.0"
    editor_key = "issue_register_display"
    display_key = "issue_register_display"
    is_computed = True

    def validate(self, value: dict[str, Any]) -> ValidationResult:
        """
        Validate issue register value.

        Required fields: total_issues, open_issues, blocking_issues, issue_refs
        """
        if value is None:
            return ValidationResult.valid()

        errors: list[str] = []
        field_errors: dict[str, list[str]] = {}

        # Check required fields
        required_fields = ["total_issues", "open_issues", "blocking_issues", "issue_refs"]
        for field in required_fields:
            if field not in value:
                errors.append(f"Missing required field: {field}")
                field_errors[field] = [f"Field '{field}' is required"]

        # Validate numeric fields
        for field in ["total_issues", "open_issues", "blocking_issues"]:
            if field in value:
                val = value[field]
                if not isinstance(val, int) or val < 0:
                    errors.append(f"Field '{field}' must be a non-negative integer")
                    field_errors[field] = ["Must be a non-negative integer"]

        # Validate issue_refs array
        if "issue_refs" in value:
            refs = value["issue_refs"]
            if not isinstance(refs, list):
                errors.append("Field 'issue_refs' must be an array")
                field_errors["issue_refs"] = ["Must be an array"]

        if errors:
            return ValidationResult.invalid(errors, field_errors)
        return ValidationResult.valid()

    def normalize(self, value: dict[str, Any]) -> dict[str, Any]:
        """Normalize issue register value."""
        if value is None:
            return self.empty_value() or {}
        return {
            "total_issues": value.get("total_issues", 0),
            "open_issues": value.get("open_issues", 0),
            "blocking_issues": value.get("blocking_issues", 0),
            "issue_refs": value.get("issue_refs", []),
        }

    def parse_form(self, form_data: dict[str, Any]) -> ParseResult:
        """Reject form parsing for computed type."""
        return ParseResult.failure(
            ["ISSUE_REGISTER is a computed type and cannot be directly saved"],
            raw_input=form_data,
        )

    def parse_workbook(
        self, cell_value: Any, context: dict[str, Any] | None = None
    ) -> ParseResult:
        """Reject workbook parsing for computed type."""
        return ParseResult.failure(
            ["ISSUE_REGISTER is a computed type and cannot be imported from workbook"],
            raw_input=cell_value,
        )

    def empty_value(self) -> dict[str, Any] | None:
        """Return empty issue register."""
        return {
            "total_issues": 0,
            "open_issues": 0,
            "blocking_issues": 0,
            "issue_refs": [],
        }

    def unknown_value(self) -> dict[str, Any] | None:
        """Return unknown marker for computed type."""
        return {"_unknown": True, "_computed": True}


class DecisionRegisterType(ResponseTypeBase):
    """
    Computed decision register type.

    Canonical shape: {total_decisions, pending_decisions, decision_refs: [...]}

    This type represents a read-only link to decision work.
    It rejects direct saves.
    """

    code = ResponseTypeCodes.DECISION_REGISTER
    schema_version = "1.0"
    editor_key = "decision_register_display"
    display_key = "decision_register_display"
    is_computed = True

    def validate(self, value: dict[str, Any]) -> ValidationResult:
        """
        Validate decision register value.

        Required fields: total_decisions, pending_decisions, decision_refs
        """
        if value is None:
            return ValidationResult.valid()

        errors: list[str] = []
        field_errors: dict[str, list[str]] = {}

        # Check required fields
        required_fields = ["total_decisions", "pending_decisions", "decision_refs"]
        for field in required_fields:
            if field not in value:
                errors.append(f"Missing required field: {field}")
                field_errors[field] = [f"Field '{field}' is required"]

        # Validate numeric fields
        for field in ["total_decisions", "pending_decisions"]:
            if field in value:
                val = value[field]
                if not isinstance(val, int) or val < 0:
                    errors.append(f"Field '{field}' must be a non-negative integer")
                    field_errors[field] = ["Must be a non-negative integer"]

        # Validate decision_refs array
        if "decision_refs" in value:
            refs = value["decision_refs"]
            if not isinstance(refs, list):
                errors.append("Field 'decision_refs' must be an array")
                field_errors["decision_refs"] = ["Must be an array"]

        if errors:
            return ValidationResult.invalid(errors, field_errors)
        return ValidationResult.valid()

    def normalize(self, value: dict[str, Any]) -> dict[str, Any]:
        """Normalize decision register value."""
        if value is None:
            return self.empty_value() or {}
        return {
            "total_decisions": value.get("total_decisions", 0),
            "pending_decisions": value.get("pending_decisions", 0),
            "decision_refs": value.get("decision_refs", []),
        }

    def parse_form(self, form_data: dict[str, Any]) -> ParseResult:
        """Reject form parsing for computed type."""
        return ParseResult.failure(
            ["DECISION_REGISTER is a computed type and cannot be directly saved"],
            raw_input=form_data,
        )

    def parse_workbook(
        self, cell_value: Any, context: dict[str, Any] | None = None
    ) -> ParseResult:
        """Reject workbook parsing for computed type."""
        return ParseResult.failure(
            ["DECISION_REGISTER is a computed type and cannot be imported from workbook"],
            raw_input=cell_value,
        )

    def empty_value(self) -> dict[str, Any] | None:
        """Return empty decision register."""
        return {
            "total_decisions": 0,
            "pending_decisions": 0,
            "decision_refs": [],
        }

    def unknown_value(self) -> dict[str, Any] | None:
        """Return unknown marker for computed type."""
        return {"_unknown": True, "_computed": True}


class ApprovalRegisterType(ResponseTypeBase):
    """
    Computed approval register type.

    Canonical shape: {total_approvals, pending_approvals, approved_count, approval_refs: [...]}

    This type represents a read-only summary linking to approval records.
    It rejects direct saves.
    """

    code = ResponseTypeCodes.APPROVAL_REGISTER
    schema_version = "1.0"
    editor_key = "approval_register_display"
    display_key = "approval_register_display"
    is_computed = True

    def validate(self, value: dict[str, Any]) -> ValidationResult:
        """
        Validate approval register value.

        Required fields: total_approvals, pending_approvals, approved_count, approval_refs
        """
        if value is None:
            return ValidationResult.valid()

        errors: list[str] = []
        field_errors: dict[str, list[str]] = {}

        # Check required fields
        required_fields = [
            "total_approvals",
            "pending_approvals",
            "approved_count",
            "approval_refs",
        ]
        for field in required_fields:
            if field not in value:
                errors.append(f"Missing required field: {field}")
                field_errors[field] = [f"Field '{field}' is required"]

        # Validate numeric fields
        for field in ["total_approvals", "pending_approvals", "approved_count"]:
            if field in value:
                val = value[field]
                if not isinstance(val, int) or val < 0:
                    errors.append(f"Field '{field}' must be a non-negative integer")
                    field_errors[field] = ["Must be a non-negative integer"]

        # Validate approval_refs array
        if "approval_refs" in value:
            refs = value["approval_refs"]
            if not isinstance(refs, list):
                errors.append("Field 'approval_refs' must be an array")
                field_errors["approval_refs"] = ["Must be an array"]

        if errors:
            return ValidationResult.invalid(errors, field_errors)
        return ValidationResult.valid()

    def normalize(self, value: dict[str, Any]) -> dict[str, Any]:
        """Normalize approval register value."""
        if value is None:
            return self.empty_value() or {}
        return {
            "total_approvals": value.get("total_approvals", 0),
            "pending_approvals": value.get("pending_approvals", 0),
            "approved_count": value.get("approved_count", 0),
            "approval_refs": value.get("approval_refs", []),
        }

    def parse_form(self, form_data: dict[str, Any]) -> ParseResult:
        """Reject form parsing for computed type."""
        return ParseResult.failure(
            ["APPROVAL_REGISTER is a computed type and cannot be directly saved"],
            raw_input=form_data,
        )

    def parse_workbook(
        self, cell_value: Any, context: dict[str, Any] | None = None
    ) -> ParseResult:
        """Reject workbook parsing for computed type."""
        return ParseResult.failure(
            ["APPROVAL_REGISTER is a computed type and cannot be imported from workbook"],
            raw_input=cell_value,
        )

    def empty_value(self) -> dict[str, Any] | None:
        """Return empty approval register."""
        return {
            "total_approvals": 0,
            "pending_approvals": 0,
            "approved_count": 0,
            "approval_refs": [],
        }

    def unknown_value(self) -> dict[str, Any] | None:
        """Return unknown marker for computed type."""
        return {"_unknown": True, "_computed": True}


class EvidenceReferenceType(ResponseTypeBase):
    """
    Evidence reference type.

    Canonical shape: {evidence_version_id, locator?, description?}

    This type allows selecting applicable evidence and is EDITABLE
    (not computed). It validates application/intake ownership.
    """

    code = ResponseTypeCodes.EVIDENCE_REFERENCE
    schema_version = "1.0"
    editor_key = "evidence_reference_editor"
    display_key = "evidence_reference_display"
    is_computed = False  # This type IS editable

    def validate(self, value: dict[str, Any]) -> ValidationResult:
        """
        Validate evidence reference value.

        Required fields: evidence_version_id
        Optional fields: locator, description
        """
        if value is None:
            return ValidationResult.valid()

        # Handle explicit unknown
        if value.get("_unknown"):
            return ValidationResult.valid()

        errors: list[str] = []
        field_errors: dict[str, list[str]] = {}

        # Check required field
        if "evidence_version_id" not in value:
            errors.append("Missing required field: evidence_version_id")
            field_errors["evidence_version_id"] = [
                "Field 'evidence_version_id' is required"
            ]
        elif value["evidence_version_id"] is not None:
            # Validate evidence_version_id is a string (UUID format expected)
            if not isinstance(value["evidence_version_id"], str):
                errors.append("Field 'evidence_version_id' must be a string")
                field_errors["evidence_version_id"] = ["Must be a string"]
            elif len(value["evidence_version_id"]) == 0:
                errors.append("Field 'evidence_version_id' cannot be empty")
                field_errors["evidence_version_id"] = ["Cannot be empty"]

        # Validate optional locator
        if "locator" in value and value["locator"] is not None:
            if not isinstance(value["locator"], str):
                errors.append("Field 'locator' must be a string")
                field_errors["locator"] = ["Must be a string"]

        # Validate optional description
        if "description" in value and value["description"] is not None:
            if not isinstance(value["description"], str):
                errors.append("Field 'description' must be a string")
                field_errors["description"] = ["Must be a string"]

        if errors:
            return ValidationResult.invalid(errors, field_errors)
        return ValidationResult.valid()

    def normalize(self, value: dict[str, Any]) -> dict[str, Any]:
        """Normalize evidence reference value."""
        if value is None:
            return self.empty_value() or {}

        # Preserve unknown marker
        if value.get("_unknown"):
            return {"_unknown": True}

        normalized = {
            "evidence_version_id": value.get("evidence_version_id"),
        }

        # Include optional fields if present
        if "locator" in value:
            locator = value["locator"]
            normalized["locator"] = locator.strip() if isinstance(locator, str) else locator
        if "description" in value:
            desc = value["description"]
            normalized["description"] = desc.strip() if isinstance(desc, str) else desc

        return normalized

    def parse_form(self, form_data: dict[str, Any]) -> ParseResult:
        """
        Parse form data for evidence reference.

        This type IS editable, so form parsing is allowed.
        """
        if form_data is None:
            return ParseResult.success(self.empty_value() or {})

        # Extract fields from form data
        evidence_version_id = form_data.get("evidence_version_id")
        locator = form_data.get("locator")
        description = form_data.get("description")

        value = {
            "evidence_version_id": evidence_version_id,
        }
        if locator:
            value["locator"] = locator
        if description:
            value["description"] = description

        # Validate the parsed value
        validation = self.validate(value)
        if not validation.is_valid:
            return ParseResult.failure(validation.errors, raw_input=form_data)

        return ParseResult.success(self.normalize(value), raw_input=form_data)

    def parse_workbook(
        self, cell_value: Any, context: dict[str, Any] | None = None
    ) -> ParseResult:
        """
        Parse workbook cell for evidence reference.

        This type IS editable, so workbook parsing is allowed.
        Expected format: evidence_version_id or structured dict.
        """
        if cell_value is None:
            return ParseResult.success(self.empty_value() or {})

        # Handle string input (just the evidence ID)
        if isinstance(cell_value, str):
            cell_value = cell_value.strip()
            if not cell_value:
                return ParseResult.success(self.empty_value() or {})
            return ParseResult.success(
                {"evidence_version_id": cell_value},
                raw_input=cell_value,
            )

        # Handle dict input
        if isinstance(cell_value, dict):
            validation = self.validate(cell_value)
            if not validation.is_valid:
                return ParseResult.failure(validation.errors, raw_input=cell_value)
            return ParseResult.success(
                self.normalize(cell_value),
                raw_input=cell_value,
            )

        return ParseResult.failure(
            ["Evidence reference must be a string or structured object"],
            raw_input=cell_value,
        )

    def empty_value(self) -> dict[str, Any] | None:
        """Return empty evidence reference."""
        return {"evidence_version_id": None}

    def unknown_value(self) -> dict[str, Any] | None:
        """Return explicit unknown value."""
        return {"_unknown": True}
