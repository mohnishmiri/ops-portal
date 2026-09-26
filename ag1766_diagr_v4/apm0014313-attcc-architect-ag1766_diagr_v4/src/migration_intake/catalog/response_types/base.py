"""
Base classes and protocols for response types.

This module defines the ResponseType protocol that all 25 response types
must implement, along with result envelopes for parsing, validation,
and comparison operations.
"""

from __future__ import annotations

from abc import ABC
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


class ResponseTypeCodes:
    """
    Constants for all 25 response type codes.

    These codes are stable identifiers used in catalog definitions
    and the response type registry.
    """

    # Scalar types (R01)
    BOOLEAN = "BOOLEAN"
    SINGLE_SELECT = "SINGLE_SELECT"
    TEXT = "TEXT"
    LONG_TEXT = "LONG_TEXT"
    IDENTIFIER = "IDENTIFIER"

    # Collection types (R02)
    MULTI_SELECT = "MULTI_SELECT"
    TEXT_PAIR = "TEXT_PAIR"
    COUNT_PAIR = "COUNT_PAIR"
    CONTROLLED_PAIR = "CONTROLLED_PAIR"
    PEOPLE_LIST = "PEOPLE_LIST"

    # Measurement types (R03)
    MEASUREMENT = "MEASUREMENT"
    MEASUREMENT_PAIR = "MEASUREMENT_PAIR"
    MEASUREMENT_SET = "MEASUREMENT_SET"
    MEASUREMENT_CONTEXT = "MEASUREMENT_CONTEXT"

    # Decision types (R04)
    BOOLEAN_WITH_RATIONALE = "BOOLEAN_WITH_RATIONALE"
    CONTROLLED_SET = "CONTROLLED_SET"
    SINGLE_SELECT_PER_COMPONENT = "SINGLE_SELECT_PER_COMPONENT"
    DECISION_WITH_PERSON = "DECISION_WITH_PERSON"
    APPROVAL = "APPROVAL"

    # Computed types (R05)
    REGISTER_STATUS = "REGISTER_STATUS"
    VALIDATION_RESULT = "VALIDATION_RESULT"
    ISSUE_REGISTER = "ISSUE_REGISTER"
    DECISION_REGISTER = "DECISION_REGISTER"
    APPROVAL_REGISTER = "APPROVAL_REGISTER"
    EVIDENCE_REFERENCE = "EVIDENCE_REFERENCE"


@dataclass(frozen=True)
class ParseResult:
    """
    Result of parsing form or workbook input.

    Attributes:
        is_success: Whether parsing succeeded
        value: Parsed value if successful, None otherwise
        errors: List of error messages if failed
        warnings: List of warning messages (may be present on success)
        raw_input: Original input for diagnostics
    """

    is_success: bool
    value: dict[str, Any] | None
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    raw_input: Any | None = None

    @classmethod
    def success(
        cls,
        value: dict[str, Any],
        warnings: list[str] | None = None,
        raw_input: Any | None = None,
    ) -> ParseResult:
        """Create a successful parse result."""
        return cls(
            is_success=True,
            value=value,
            errors=[],
            warnings=warnings or [],
            raw_input=raw_input,
        )

    @classmethod
    def failure(
        cls,
        errors: list[str],
        raw_input: Any | None = None,
    ) -> ParseResult:
        """Create a failed parse result."""
        return cls(
            is_success=False,
            value=None,
            errors=errors,
            warnings=[],
            raw_input=raw_input,
        )


@dataclass(frozen=True)
class ValidationResult:
    """
    Result of validating a response value.

    Attributes:
        is_valid: Whether the value is valid
        errors: List of validation error messages
        field_errors: Dict mapping field names to their errors
    """

    is_valid: bool
    errors: list[str] = field(default_factory=list)
    field_errors: dict[str, list[str]] = field(default_factory=dict)

    @classmethod
    def valid(cls) -> ValidationResult:
        """Create a valid result."""
        return cls(is_valid=True, errors=[], field_errors={})

    @classmethod
    def invalid(
        cls,
        errors: list[str],
        field_errors: dict[str, list[str]] | None = None,
    ) -> ValidationResult:
        """Create an invalid result."""
        return cls(
            is_valid=False,
            errors=errors,
            field_errors=field_errors or {},
        )


@dataclass(frozen=True)
class ComparisonResult:
    """
    Result of comparing two response values.

    Attributes:
        is_equal: Whether values are semantically equal
        differences: List of field-level differences
        is_noop: Whether this represents a no-op change
    """

    is_equal: bool
    differences: list[dict[str, Any]] = field(default_factory=list)

    @property
    def is_noop(self) -> bool:
        """Check if this comparison represents a no-op (no change)."""
        return self.is_equal

    @classmethod
    def equal(cls) -> ComparisonResult:
        """Create an equal comparison result."""
        return cls(is_equal=True, differences=[])

    @classmethod
    def different(cls, differences: list[dict[str, Any]]) -> ComparisonResult:
        """Create a different comparison result."""
        return cls(is_equal=False, differences=differences)


@runtime_checkable
class ResponseType(Protocol):
    """
    Protocol defining the response type contract.

    All 25 response types must implement this protocol.
    """

    @property
    def code(self) -> str:
        """Stable type code (e.g., 'BOOLEAN', 'TEXT')."""
        ...

    @property
    def schema_version(self) -> str:
        """Schema version for this type (e.g., '1.0')."""
        ...

    @property
    def editor_key(self) -> str:
        """Template key for the editor component."""
        ...

    @property
    def display_key(self) -> str:
        """Template key for read-only display."""
        ...

    @property
    def is_computed(self) -> bool:
        """Whether this type rejects direct saves."""
        ...

    def validate(self, value: dict[str, Any]) -> ValidationResult:
        """Validate a value against this type's schema."""
        ...

    def normalize(self, value: dict[str, Any]) -> dict[str, Any]:
        """Normalize a value (trim whitespace, case-fold codes, etc.)."""
        ...

    def compare(
        self, old: dict[str, Any], new: dict[str, Any]
    ) -> ComparisonResult:
        """Compare two values for semantic equality."""
        ...

    def serialize(self, value: dict[str, Any]) -> str:
        """Serialize to canonical JSON string."""
        ...

    def deserialize(self, data: str) -> dict[str, Any]:
        """Deserialize from JSON string."""
        ...

    def parse_form(self, form_data: dict[str, Any]) -> ParseResult:
        """Parse HTML form submission."""
        ...

    def parse_workbook(
        self, cell_value: Any, context: dict[str, Any] | None = None
    ) -> ParseResult:
        """Parse workbook cell value."""
        ...

    def empty_value(self) -> dict[str, Any] | None:
        """Return the empty/blank value for this type."""
        ...

    def unknown_value(self) -> dict[str, Any] | None:
        """Return the explicit unknown value for this type."""
        ...


class ResponseTypeBase(ABC):
    """
    Abstract base class for response types.

    Provides default implementations for common operations.
    Subclasses must define class attributes and implement
    type-specific methods.
    """

    # Subclasses must define these
    code: str
    schema_version: str
    editor_key: str
    display_key: str
    is_computed: bool

    def validate(self, value: dict[str, Any]) -> ValidationResult:
        """
        Validate a value against this type's schema.

        Override in subclasses for type-specific validation.
        """
        return ValidationResult.valid()

    def normalize(self, value: dict[str, Any]) -> dict[str, Any]:
        """
        Normalize a value.

        Override in subclasses for type-specific normalization.
        """
        return value

    def compare(
        self, old: dict[str, Any], new: dict[str, Any]
    ) -> ComparisonResult:
        """
        Compare two values for semantic equality.

        Default implementation compares normalized values.
        Override for type-specific comparison logic.
        """
        old_normalized = self.normalize(old) if old else None
        new_normalized = self.normalize(new) if new else None

        if old_normalized == new_normalized:
            return ComparisonResult.equal()

        differences = []
        if old_normalized != new_normalized:
            differences.append({
                "field": "value",
                "old": old_normalized,
                "new": new_normalized,
            })
        return ComparisonResult.different(differences)

    def serialize(self, value: dict[str, Any]) -> str:
        """
        Serialize to canonical JSON string.

        Uses sorted keys for deterministic output.
        """
        import json
        return json.dumps(value, sort_keys=True, ensure_ascii=False)

    def deserialize(self, data: str) -> dict[str, Any]:
        """Deserialize from JSON string."""
        import json
        return json.loads(data)

    def parse_form(self, form_data: dict[str, Any]) -> ParseResult:
        """
        Parse HTML form submission.

        Override in subclasses for type-specific form parsing.
        """
        return ParseResult.success(form_data)

    def parse_form_strict(self, form_data: dict[str, Any]) -> ParseResult:
        """
        Parse a form submission, failing loudly when nothing was understood.

        ``parse_form`` implementations silently return this type's empty value
        for field names they do not recognise, so an editor template whose
        input names disagree with the canonical payload keys saves a blank
        answer with no error anywhere. That failure mode hid mismatched
        editors for twelve of nineteen response types.

        This wrapper keeps the lenient per-type parsers intact and adds the
        boundary check: if the user submitted something but the parsed result
        is indistinguishable from empty, that is a contract mismatch, not an
        empty answer.
        """
        meaningful = {
            key: value
            for key, value in (form_data or {}).items()
            if not key.startswith("_") and value not in (None, "", [], {})
        }
        result = self.parse_form(form_data)
        if not result.is_success or not meaningful:
            return result

        empty = self.empty_value()
        if empty is not None and result.value == empty:
            expected = sorted(empty.keys()) if isinstance(empty, dict) else []
            return ParseResult.failure(
                [
                    f"No recognised {self.code} fields were submitted "
                    f"(expected any of: {', '.join(expected) or 'n/a'}; "
                    f"received: {', '.join(sorted(meaningful))})"
                ],
                raw_input=form_data,
            )
        return result

    def parse_workbook(
        self, cell_value: Any, context: dict[str, Any] | None = None
    ) -> ParseResult:
        """
        Parse workbook cell value.

        Override in subclasses for type-specific workbook parsing.
        """
        if cell_value is None:
            return ParseResult.success(self.empty_value() or {})
        return ParseResult.success({"value": cell_value})

    def empty_value(self) -> dict[str, Any] | None:
        """
        Return the empty/blank value for this type.

        Override in subclasses for type-specific empty semantics.
        """
        return None

    def unknown_value(self) -> dict[str, Any] | None:
        """
        Return the explicit unknown value for this type.

        Override in subclasses for type-specific unknown semantics.
        """
        return {"_unknown": True}

    def format_summary(self, value: dict[str, Any]) -> str:
        """
        Format value for summary display.

        Override in subclasses for type-specific formatting.
        """
        return str(value) if value else ""

    def get_diff(
        self, old: dict[str, Any], new: dict[str, Any]
    ) -> list[dict[str, Any]]:
        """
        Get field-level differences for candidate reconciliation.

        Override in subclasses for type-specific diff logic.
        """
        result = self.compare(old, new)
        return result.differences
