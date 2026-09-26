"""
R01 Scalar response types.

This module implements the five scalar response types:
- BOOLEAN: Three-option (YES/NO/UNKNOWN), never a checkbox
- SINGLE_SELECT: Radio/select with allowed values and optional Other
- TEXT: Single-line with length/pattern validation
- LONG_TEXT: Textarea with length limits
- IDENTIFIER: Type + value + normalized_value
"""

from __future__ import annotations

import re
from typing import Any

from migration_intake.catalog.response_types.base import (
    ComparisonResult,
    ParseResult,
    ResponseTypeBase,
    ResponseTypeCodes,
    ValidationResult,
)


class BooleanValue:
    """Constants for boolean response values."""

    YES = "YES"
    NO = "NO"
    UNKNOWN = "UNKNOWN"

    ALL_VALUES: set[str] = {YES, NO, UNKNOWN}


class IdentifierTypeCodes:
    """Constants for identifier types."""

    CORRELATION_ID = "CORRELATION_ID"
    MOTS_ID = "MOTS_ID"
    ITAP_ID = "ITAP_ID"
    OTHER = "OTHER"

    ALL_TYPES: set[str] = {CORRELATION_ID, MOTS_ID, ITAP_ID, OTHER}


class BooleanType(ResponseTypeBase):
    """
    Three-option boolean response type.

    Shape: {value: YES|NO|UNKNOWN}

    This is never a checkbox - it always requires explicit selection
    of YES, NO, or UNKNOWN. UNKNOWN represents explicit acknowledgment
    that the answer is not known, distinct from blank/unanswered.
    """

    code = ResponseTypeCodes.BOOLEAN
    schema_version = "1.0"
    editor_key = "boolean_editor"
    display_key = "boolean_display"
    is_computed = False

    def validate(self, value: dict[str, Any]) -> ValidationResult:
        """Validate boolean response shape and value."""
        if value is None:
            return ValidationResult.valid()

        if not isinstance(value, dict):
            return ValidationResult.invalid(
                ["Value must be a dictionary"],
                field_errors={"value": ["Expected dictionary"]}
            )

        val = value.get("value")
        if val is None:
            # Empty/blank is valid
            return ValidationResult.valid()

        if not isinstance(val, str):
            return ValidationResult.invalid(
                ["Value must be a string"],
                field_errors={"value": ["Expected string"]}
            )

        if val not in BooleanValue.ALL_VALUES:
            return ValidationResult.invalid(
                [f"Value must be one of: {', '.join(sorted(BooleanValue.ALL_VALUES))}"],
                field_errors={"value": [f"Invalid value: {val}"]}
            )

        return ValidationResult.valid()

    def normalize(self, value: dict[str, Any]) -> dict[str, Any]:
        """Normalize boolean value - uppercase and trim."""
        if value is None:
            return self.empty_value() or {}

        val = value.get("value")
        if val is None:
            return {"value": None}

        if isinstance(val, str):
            normalized = val.strip().upper()
            return {"value": normalized if normalized in BooleanValue.ALL_VALUES else val}

        return value

    def parse_form(self, form_data: dict[str, Any]) -> ParseResult:
        """Parse HTML form submission for boolean."""
        raw_value = form_data.get("value")

        if raw_value is None or raw_value == "":
            return ParseResult.success(self.empty_value() or {}, raw_input=form_data)

        if isinstance(raw_value, str):
            normalized = raw_value.strip().upper()
            if normalized in BooleanValue.ALL_VALUES:
                return ParseResult.success({"value": normalized}, raw_input=form_data)
            return ParseResult.failure(
                [f"Invalid boolean value: {raw_value}. Must be YES, NO, or UNKNOWN."],
                raw_input=form_data
            )

        return ParseResult.failure(
            ["Boolean value must be a string"],
            raw_input=form_data
        )

    def parse_workbook(
        self, cell_value: Any, context: dict[str, Any] | None = None
    ) -> ParseResult:
        """Parse workbook cell value for boolean."""
        if cell_value is None or cell_value == "":
            return ParseResult.success(self.empty_value() or {}, raw_input=cell_value)

        if isinstance(cell_value, bool):
            return ParseResult.success(
                {"value": BooleanValue.YES if cell_value else BooleanValue.NO},
                raw_input=cell_value
            )

        if isinstance(cell_value, str):
            normalized = cell_value.strip().upper()
            # Handle common variations
            if normalized in ("Y", "YES", "TRUE", "1"):
                return ParseResult.success({"value": BooleanValue.YES}, raw_input=cell_value)
            if normalized in ("N", "NO", "FALSE", "0"):
                return ParseResult.success({"value": BooleanValue.NO}, raw_input=cell_value)
            if normalized in ("UNKNOWN", "?", "N/A", "NA", "TBD"):
                return ParseResult.success({"value": BooleanValue.UNKNOWN}, raw_input=cell_value)

            return ParseResult.failure(
                [f"Cannot parse '{cell_value}' as boolean. Expected YES, NO, or UNKNOWN."],
                raw_input=cell_value
            )

        return ParseResult.failure(
            [f"Cannot parse {type(cell_value).__name__} as boolean"],
            raw_input=cell_value
        )

    def empty_value(self) -> dict[str, Any] | None:
        """Return empty boolean value."""
        return {"value": None}

    def unknown_value(self) -> dict[str, Any] | None:
        """Return explicit unknown value."""
        return {"value": BooleanValue.UNKNOWN}

    def compare(
        self, old: dict[str, Any], new: dict[str, Any]
    ) -> ComparisonResult:
        """Compare two boolean values for semantic equality."""
        old_norm = self.normalize(old) if old else self.empty_value()
        new_norm = self.normalize(new) if new else self.empty_value()

        old_val = old_norm.get("value") if old_norm else None
        new_val = new_norm.get("value") if new_norm else None

        if old_val == new_val:
            return ComparisonResult.equal()

        return ComparisonResult.different([
            {"field": "value", "old": old_val, "new": new_val}
        ])


class SingleSelectType(ResponseTypeBase):
    """
    Single selection response type with optional Other.

    Shape: {value, other_text?}

    Used for radio buttons or select dropdowns where exactly one
    value must be chosen from allowed values. If OTHER is allowed
    and selected, other_text provides the detail.
    """

    code = ResponseTypeCodes.SINGLE_SELECT
    schema_version = "1.0"
    editor_key = "single_select_editor"
    display_key = "single_select_display"
    is_computed = False

    def __init__(
        self,
        allowed_values: list[str] | None = None,
        allow_other: bool = False,
        other_required_when_selected: bool = True,
    ):
        """
        Initialize single select type.

        Args:
            allowed_values: List of allowed value codes. If None, any value accepted.
            allow_other: Whether OTHER is a valid selection requiring other_text.
            other_required_when_selected: Whether other_text is required when OTHER selected.
        """
        self.allowed_values = set(allowed_values) if allowed_values else None
        self.allow_other = allow_other
        self.other_required_when_selected = other_required_when_selected

    def validate(self, value: dict[str, Any]) -> ValidationResult:
        """Validate single select response shape and value."""
        if value is None:
            return ValidationResult.valid()

        if not isinstance(value, dict):
            return ValidationResult.invalid(
                ["Value must be a dictionary"],
                field_errors={"value": ["Expected dictionary"]}
            )

        val = value.get("value")
        other_text = value.get("other_text")

        # Empty is valid
        if val is None:
            if other_text is not None and other_text != "":
                return ValidationResult.invalid(
                    ["other_text cannot be set without a value"],
                    field_errors={"other_text": ["Requires value to be set"]}
                )
            return ValidationResult.valid()

        if not isinstance(val, str):
            return ValidationResult.invalid(
                ["Value must be a string"],
                field_errors={"value": ["Expected string"]}
            )

        # Check allowed values if configured
        if self.allowed_values is not None:
            effective_allowed = set(self.allowed_values)
            if self.allow_other:
                effective_allowed.add("OTHER")

            if val not in effective_allowed:
                return ValidationResult.invalid(
                    [f"Value '{val}' is not in allowed values"],
                    field_errors={"value": [f"Must be one of: {', '.join(sorted(effective_allowed))}"]}
                )

        # Validate other_text
        if val == "OTHER" and self.allow_other:
            if self.other_required_when_selected:
                if other_text is None or (isinstance(other_text, str) and other_text.strip() == ""):
                    return ValidationResult.invalid(
                        ["other_text is required when OTHER is selected"],
                        field_errors={"other_text": ["Required when OTHER selected"]}
                    )
        elif other_text is not None and other_text != "":
            return ValidationResult.invalid(
                ["other_text should only be set when value is OTHER"],
                field_errors={"other_text": ["Only valid when value is OTHER"]}
            )

        return ValidationResult.valid()

    def normalize(self, value: dict[str, Any]) -> dict[str, Any]:
        """Normalize single select value - uppercase code, trim text."""
        if value is None:
            return self.empty_value() or {}

        val = value.get("value")
        other_text = value.get("other_text")

        result: dict[str, Any] = {}

        if val is not None and isinstance(val, str):
            result["value"] = val.strip().upper()
        else:
            result["value"] = val

        if other_text is not None and isinstance(other_text, str):
            trimmed = other_text.strip()
            if trimmed:
                result["other_text"] = trimmed
        elif other_text is not None:
            result["other_text"] = other_text

        return result

    def parse_form(self, form_data: dict[str, Any]) -> ParseResult:
        """Parse HTML form submission for single select."""
        raw_value = form_data.get("value")
        raw_other = form_data.get("other_text")

        if raw_value is None or raw_value == "":
            if raw_other and str(raw_other).strip():
                return ParseResult.failure(
                    ["Cannot provide other_text without selecting a value"],
                    raw_input=form_data
                )
            return ParseResult.success(self.empty_value() or {}, raw_input=form_data)

        result: dict[str, Any] = {"value": str(raw_value).strip().upper()}

        if raw_other is not None:
            other_str = str(raw_other).strip()
            if other_str:
                result["other_text"] = other_str

        return ParseResult.success(result, raw_input=form_data)

    def parse_workbook(
        self, cell_value: Any, context: dict[str, Any] | None = None
    ) -> ParseResult:
        """Parse workbook cell value for single select."""
        if cell_value is None or cell_value == "":
            return ParseResult.success(self.empty_value() or {}, raw_input=cell_value)

        if isinstance(cell_value, str):
            normalized = cell_value.strip().upper()
            return ParseResult.success({"value": normalized}, raw_input=cell_value)

        return ParseResult.failure(
            [f"Cannot parse {type(cell_value).__name__} as single select"],
            raw_input=cell_value
        )

    def empty_value(self) -> dict[str, Any] | None:
        """Return empty single select value."""
        return {"value": None}

    def unknown_value(self) -> dict[str, Any] | None:
        """Return explicit unknown value."""
        return {"value": "UNKNOWN"}

    def compare(
        self, old: dict[str, Any], new: dict[str, Any]
    ) -> ComparisonResult:
        """Compare two single select values for semantic equality."""
        old_norm = self.normalize(old) if old else self.empty_value()
        new_norm = self.normalize(new) if new else self.empty_value()

        differences = []

        old_val = old_norm.get("value") if old_norm else None
        new_val = new_norm.get("value") if new_norm else None

        if old_val != new_val:
            differences.append({"field": "value", "old": old_val, "new": new_val})

        old_other = old_norm.get("other_text") if old_norm else None
        new_other = new_norm.get("other_text") if new_norm else None

        if old_other != new_other:
            differences.append({"field": "other_text", "old": old_other, "new": new_other})

        if differences:
            return ComparisonResult.different(differences)
        return ComparisonResult.equal()


class TextType(ResponseTypeBase):
    """
    Single-line text response type.

    Shape: {text}

    Used for short text inputs with optional length and pattern validation.
    """

    code = ResponseTypeCodes.TEXT
    schema_version = "1.0"
    editor_key = "text_editor"
    display_key = "text_display"
    is_computed = False

    # Default constraints
    DEFAULT_MIN_LENGTH = 0
    DEFAULT_MAX_LENGTH = 500

    def __init__(
        self,
        min_length: int = DEFAULT_MIN_LENGTH,
        max_length: int = DEFAULT_MAX_LENGTH,
        pattern: str | None = None,
        pattern_description: str | None = None,
    ):
        """
        Initialize text type.

        Args:
            min_length: Minimum text length (after trim).
            max_length: Maximum text length.
            pattern: Optional regex pattern for validation.
            pattern_description: Human-readable description of pattern.
        """
        self.min_length = min_length
        self.max_length = max_length
        self.pattern = pattern
        self.pattern_description = pattern_description
        self._compiled_pattern = re.compile(pattern) if pattern else None

    def validate(self, value: dict[str, Any]) -> ValidationResult:
        """Validate text response shape and constraints."""
        if value is None:
            return ValidationResult.valid()

        if not isinstance(value, dict):
            return ValidationResult.invalid(
                ["Value must be a dictionary"],
                field_errors={"text": ["Expected dictionary"]}
            )

        text = value.get("text")

        # Empty/null is valid (unless min_length > 0)
        if text is None:
            if self.min_length > 0:
                return ValidationResult.invalid(
                    [f"Text is required (minimum {self.min_length} characters)"],
                    field_errors={"text": ["Required"]}
                )
            return ValidationResult.valid()

        if not isinstance(text, str):
            return ValidationResult.invalid(
                ["Text must be a string"],
                field_errors={"text": ["Expected string"]}
            )

        # Check for control characters (except common whitespace)
        if any(ord(c) < 32 and c not in '\t\n\r' for c in text):
            return ValidationResult.invalid(
                ["Text contains invalid control characters"],
                field_errors={"text": ["Invalid characters"]}
            )

        # Check for newlines (single-line only)
        if '\n' in text or '\r' in text:
            return ValidationResult.invalid(
                ["Single-line text cannot contain newlines"],
                field_errors={"text": ["Newlines not allowed"]}
            )

        trimmed = text.strip()
        length = len(trimmed)

        errors = []
        field_errors: dict[str, list[str]] = {}

        if length < self.min_length:
            msg = f"Text must be at least {self.min_length} characters"
            errors.append(msg)
            field_errors["text"] = field_errors.get("text", []) + [msg]

        if length > self.max_length:
            msg = f"Text must be at most {self.max_length} characters"
            errors.append(msg)
            field_errors["text"] = field_errors.get("text", []) + [msg]

        if self._compiled_pattern and trimmed:
            if not self._compiled_pattern.match(trimmed):
                msg = self.pattern_description or f"Text must match pattern: {self.pattern}"
                errors.append(msg)
                field_errors["text"] = field_errors.get("text", []) + [msg]

        if errors:
            return ValidationResult.invalid(errors, field_errors)
        return ValidationResult.valid()

    def normalize(self, value: dict[str, Any]) -> dict[str, Any]:
        """Normalize text value - trim whitespace."""
        if value is None:
            return self.empty_value() or {}

        text = value.get("text")

        if text is None:
            return {"text": None}

        if isinstance(text, str):
            return {"text": text.strip()}

        return value

    def parse_form(self, form_data: dict[str, Any]) -> ParseResult:
        """Parse HTML form submission for text."""
        raw_text = form_data.get("text")

        if raw_text is None or raw_text == "":
            return ParseResult.success(self.empty_value() or {}, raw_input=form_data)

        if isinstance(raw_text, str):
            return ParseResult.success({"text": raw_text.strip()}, raw_input=form_data)

        return ParseResult.failure(
            ["Text must be a string"],
            raw_input=form_data
        )

    def parse_workbook(
        self, cell_value: Any, context: dict[str, Any] | None = None
    ) -> ParseResult:
        """Parse workbook cell value for text."""
        if cell_value is None or cell_value == "":
            return ParseResult.success(self.empty_value() or {}, raw_input=cell_value)

        # Convert numbers to string
        if isinstance(cell_value, (int, float)):
            text = str(int(cell_value)) if isinstance(cell_value, float) and cell_value.is_integer() else str(cell_value)
            return ParseResult.success({"text": text.strip()}, raw_input=cell_value)

        if isinstance(cell_value, str):
            return ParseResult.success({"text": cell_value.strip()}, raw_input=cell_value)

        return ParseResult.failure(
            [f"Cannot parse {type(cell_value).__name__} as text"],
            raw_input=cell_value
        )

    def empty_value(self) -> dict[str, Any] | None:
        """Return empty text value."""
        return {"text": None}

    def unknown_value(self) -> dict[str, Any] | None:
        """Return explicit unknown value."""
        return {"text": "UNKNOWN"}

    def compare(
        self, old: dict[str, Any], new: dict[str, Any]
    ) -> ComparisonResult:
        """Compare two text values for semantic equality."""
        old_norm = self.normalize(old) if old else self.empty_value()
        new_norm = self.normalize(new) if new else self.empty_value()

        old_text = old_norm.get("text") if old_norm else None
        new_text = new_norm.get("text") if new_norm else None

        if old_text == new_text:
            return ComparisonResult.equal()

        return ComparisonResult.different([
            {"field": "text", "old": old_text, "new": new_text}
        ])


class LongTextType(ResponseTypeBase):
    """
    Multi-line text response type.

    Shape: {text}

    Used for textarea inputs with length limits. Allows newlines
    and displays with escaped formatting.
    """

    code = ResponseTypeCodes.LONG_TEXT
    schema_version = "1.0"
    editor_key = "long_text_editor"
    display_key = "long_text_display"
    is_computed = False

    # Default constraints
    DEFAULT_MIN_LENGTH = 0
    DEFAULT_MAX_LENGTH = 10000

    def __init__(
        self,
        min_length: int = DEFAULT_MIN_LENGTH,
        max_length: int = DEFAULT_MAX_LENGTH,
    ):
        """
        Initialize long text type.

        Args:
            min_length: Minimum text length (after trim).
            max_length: Maximum text length.
        """
        self.min_length = min_length
        self.max_length = max_length

    def validate(self, value: dict[str, Any]) -> ValidationResult:
        """Validate long text response shape and constraints."""
        if value is None:
            return ValidationResult.valid()

        if not isinstance(value, dict):
            return ValidationResult.invalid(
                ["Value must be a dictionary"],
                field_errors={"text": ["Expected dictionary"]}
            )

        text = value.get("text")

        # Empty/null is valid (unless min_length > 0)
        if text is None:
            if self.min_length > 0:
                return ValidationResult.invalid(
                    [f"Text is required (minimum {self.min_length} characters)"],
                    field_errors={"text": ["Required"]}
                )
            return ValidationResult.valid()

        if not isinstance(text, str):
            return ValidationResult.invalid(
                ["Text must be a string"],
                field_errors={"text": ["Expected string"]}
            )

        # Check for control characters (except common whitespace)
        if any(ord(c) < 32 and c not in '\t\n\r' for c in text):
            return ValidationResult.invalid(
                ["Text contains invalid control characters"],
                field_errors={"text": ["Invalid characters"]}
            )

        trimmed = text.strip()
        length = len(trimmed)

        errors = []
        field_errors: dict[str, list[str]] = {}

        if length < self.min_length:
            msg = f"Text must be at least {self.min_length} characters"
            errors.append(msg)
            field_errors["text"] = field_errors.get("text", []) + [msg]

        if length > self.max_length:
            msg = f"Text must be at most {self.max_length} characters"
            errors.append(msg)
            field_errors["text"] = field_errors.get("text", []) + [msg]

        if errors:
            return ValidationResult.invalid(errors, field_errors)
        return ValidationResult.valid()

    def normalize(self, value: dict[str, Any]) -> dict[str, Any]:
        """Normalize long text value - trim whitespace, normalize line endings."""
        if value is None:
            return self.empty_value() or {}

        text = value.get("text")

        if text is None:
            return {"text": None}

        if isinstance(text, str):
            # Normalize line endings to \n and trim
            normalized = text.replace('\r\n', '\n').replace('\r', '\n').strip()
            return {"text": normalized}

        return value

    def parse_form(self, form_data: dict[str, Any]) -> ParseResult:
        """Parse HTML form submission for long text."""
        raw_text = form_data.get("text")

        if raw_text is None or raw_text == "":
            return ParseResult.success(self.empty_value() or {}, raw_input=form_data)

        if isinstance(raw_text, str):
            # Normalize line endings
            normalized = raw_text.replace('\r\n', '\n').replace('\r', '\n').strip()
            return ParseResult.success({"text": normalized}, raw_input=form_data)

        return ParseResult.failure(
            ["Text must be a string"],
            raw_input=form_data
        )

    def parse_workbook(
        self, cell_value: Any, context: dict[str, Any] | None = None
    ) -> ParseResult:
        """Parse workbook cell value for long text."""
        if cell_value is None or cell_value == "":
            return ParseResult.success(self.empty_value() or {}, raw_input=cell_value)

        if isinstance(cell_value, str):
            # Normalize line endings
            normalized = cell_value.replace('\r\n', '\n').replace('\r', '\n').strip()
            return ParseResult.success({"text": normalized}, raw_input=cell_value)

        return ParseResult.failure(
            [f"Cannot parse {type(cell_value).__name__} as long text"],
            raw_input=cell_value
        )

    def empty_value(self) -> dict[str, Any] | None:
        """Return empty long text value."""
        return {"text": None}

    def unknown_value(self) -> dict[str, Any] | None:
        """Return explicit unknown value."""
        return {"text": "UNKNOWN"}

    def compare(
        self, old: dict[str, Any], new: dict[str, Any]
    ) -> ComparisonResult:
        """Compare two long text values for semantic equality."""
        old_norm = self.normalize(old) if old else self.empty_value()
        new_norm = self.normalize(new) if new else self.empty_value()

        old_text = old_norm.get("text") if old_norm else None
        new_text = new_norm.get("text") if new_norm else None

        if old_text == new_text:
            return ComparisonResult.equal()

        return ComparisonResult.different([
            {"field": "text", "old": old_text, "new": new_text}
        ])


class IdentifierType(ResponseTypeBase):
    """
    Typed identifier response type.

    Shape: {identifier_type, value, normalized_value}

    Used for external identifiers like CORRELATION_ID, MOTS_ID, ITAP_ID.
    The normalized_value is computed server-side and not directly edited.
    """

    code = ResponseTypeCodes.IDENTIFIER
    schema_version = "1.0"
    editor_key = "identifier_editor"
    display_key = "identifier_display"
    is_computed = False

    def validate(self, value: dict[str, Any]) -> ValidationResult:
        """Validate identifier response shape and constraints."""
        if value is None:
            return ValidationResult.valid()

        if not isinstance(value, dict):
            return ValidationResult.invalid(
                ["Value must be a dictionary"],
                field_errors={"value": ["Expected dictionary"]}
            )

        id_type = value.get("identifier_type")
        id_value = value.get("value")

        # Empty is valid
        if id_type is None and id_value is None:
            return ValidationResult.valid()

        errors = []
        field_errors: dict[str, list[str]] = {}

        # Both must be present or both absent
        if id_type is None and id_value is not None:
            errors.append("identifier_type is required when value is provided")
            field_errors["identifier_type"] = ["Required"]

        if id_value is None and id_type is not None:
            errors.append("value is required when identifier_type is provided")
            field_errors["value"] = ["Required"]

        # Validate identifier_type
        if id_type is not None:
            if not isinstance(id_type, str):
                errors.append("identifier_type must be a string")
                field_errors["identifier_type"] = field_errors.get("identifier_type", []) + ["Expected string"]
            elif id_type not in IdentifierTypeCodes.ALL_TYPES:
                errors.append(f"identifier_type must be one of: {', '.join(sorted(IdentifierTypeCodes.ALL_TYPES))}")
                field_errors["identifier_type"] = field_errors.get("identifier_type", []) + [f"Invalid type: {id_type}"]

        # Validate value
        if id_value is not None:
            if not isinstance(id_value, str):
                errors.append("value must be a string")
                field_errors["value"] = field_errors.get("value", []) + ["Expected string"]
            elif len(id_value.strip()) == 0:
                errors.append("value cannot be empty")
                field_errors["value"] = field_errors.get("value", []) + ["Cannot be empty"]

        if errors:
            return ValidationResult.invalid(errors, field_errors)
        return ValidationResult.valid()

    def normalize(self, value: dict[str, Any]) -> dict[str, Any]:
        """Normalize identifier value - compute normalized_value."""
        if value is None:
            return self.empty_value() or {}

        id_type = value.get("identifier_type")
        id_value = value.get("value")

        if id_type is None and id_value is None:
            return {"identifier_type": None, "value": None, "normalized_value": None}

        result: dict[str, Any] = {}

        if id_type is not None and isinstance(id_type, str):
            result["identifier_type"] = id_type.strip().upper()
        else:
            result["identifier_type"] = id_type

        if id_value is not None and isinstance(id_value, str):
            trimmed = id_value.strip()
            result["value"] = trimmed
            # Compute normalized value (uppercase, no spaces)
            result["normalized_value"] = self._compute_normalized(trimmed, result.get("identifier_type"))
        else:
            result["value"] = id_value
            result["normalized_value"] = None

        return result

    def _compute_normalized(self, value: str, id_type: str | None) -> str:
        """Compute normalized identifier value."""
        # Basic normalization: uppercase, remove leading/trailing whitespace
        normalized = value.strip().upper()

        # Type-specific normalization could be added here
        # For now, just strip and uppercase
        return normalized

    def parse_form(self, form_data: dict[str, Any]) -> ParseResult:
        """Parse HTML form submission for identifier."""
        raw_type = form_data.get("identifier_type")
        raw_value = form_data.get("value")

        if (raw_type is None or raw_type == "") and (raw_value is None or raw_value == ""):
            return ParseResult.success(self.empty_value() or {}, raw_input=form_data)

        result: dict[str, Any] = {}

        if raw_type is not None and raw_type != "":
            type_str = str(raw_type).strip().upper()
            if type_str not in IdentifierTypeCodes.ALL_TYPES:
                return ParseResult.failure(
                    [f"Invalid identifier type: {raw_type}"],
                    raw_input=form_data
                )
            result["identifier_type"] = type_str
        else:
            return ParseResult.failure(
                ["identifier_type is required when value is provided"],
                raw_input=form_data
            )

        if raw_value is not None and raw_value != "":
            value_str = str(raw_value).strip()
            if not value_str:
                return ParseResult.failure(
                    ["value cannot be empty"],
                    raw_input=form_data
                )
            result["value"] = value_str
            result["normalized_value"] = self._compute_normalized(value_str, result["identifier_type"])
        else:
            return ParseResult.failure(
                ["value is required when identifier_type is provided"],
                raw_input=form_data
            )

        return ParseResult.success(result, raw_input=form_data)

    def parse_workbook(
        self, cell_value: Any, context: dict[str, Any] | None = None
    ) -> ParseResult:
        """Parse workbook cell value for identifier."""
        if cell_value is None or cell_value == "":
            return ParseResult.success(self.empty_value() or {}, raw_input=cell_value)

        # Context should provide identifier_type
        id_type = context.get("identifier_type") if context else None

        if isinstance(cell_value, (int, float)):
            # Convert numeric IDs to string
            value_str = str(int(cell_value)) if isinstance(cell_value, float) and cell_value.is_integer() else str(cell_value)
        elif isinstance(cell_value, str):
            value_str = cell_value.strip()
        else:
            return ParseResult.failure(
                [f"Cannot parse {type(cell_value).__name__} as identifier"],
                raw_input=cell_value
            )

        if not value_str:
            return ParseResult.success(self.empty_value() or {}, raw_input=cell_value)

        # If no type provided in context, try to infer or default to OTHER
        if id_type is None:
            id_type = IdentifierTypeCodes.OTHER
            warnings = ["identifier_type not provided, defaulting to OTHER"]
        else:
            warnings = []

        result = {
            "identifier_type": id_type,
            "value": value_str,
            "normalized_value": self._compute_normalized(value_str, id_type),
        }

        return ParseResult.success(result, warnings=warnings if warnings else None, raw_input=cell_value)

    def empty_value(self) -> dict[str, Any] | None:
        """Return empty identifier value."""
        return {"identifier_type": None, "value": None, "normalized_value": None}

    def unknown_value(self) -> dict[str, Any] | None:
        """Return explicit unknown value."""
        return {
            "identifier_type": IdentifierTypeCodes.OTHER,
            "value": "UNKNOWN",
            "normalized_value": "UNKNOWN",
        }

    def compare(
        self, old: dict[str, Any], new: dict[str, Any]
    ) -> ComparisonResult:
        """Compare two identifier values for semantic equality."""
        old_norm = self.normalize(old) if old else self.empty_value()
        new_norm = self.normalize(new) if new else self.empty_value()

        differences = []

        for field in ["identifier_type", "value", "normalized_value"]:
            old_val = old_norm.get(field) if old_norm else None
            new_val = new_norm.get(field) if new_norm else None

            if old_val != new_val:
                differences.append({"field": field, "old": old_val, "new": new_val})

        if differences:
            return ComparisonResult.different(differences)
        return ComparisonResult.equal()
