"""
Collection response types (R02).

This module implements the five collection response types:
- MULTI_SELECT: Checkbox group with stable order, NONE exclusivity
- TEXT_PAIR: Two named text fields (e.g., application_name, acronym)
- COUNT_PAIR: Two nonnegative integers with unit, null differs from zero
- CONTROLLED_PAIR: Two controlled inputs with cross-field validation
- PEOPLE_LIST: Repeatable people with role, name, identity fields
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

from migration_intake.catalog.response_types.base import (
    ComparisonResult,
    ParseResult,
    ResponseTypeBase,
    ResponseTypeCodes,
    ValidationResult,
)


class MultiSelectType(ResponseTypeBase):
    """
    Multi-select checkbox group response type.

    Canonical shape: {values: [code], other_text?}

    Features:
    - Checkbox group with stable catalog order
    - NONE exclusivity: if NONE is selected, no other values allowed
    - Optional other_text for OTHER selection
    - Values are case-folded to uppercase for normalization
    """

    code = ResponseTypeCodes.MULTI_SELECT
    schema_version = "1.0"
    editor_key = "multi_select_editor"
    display_key = "multi_select_display"
    is_computed = False

    def __init__(
        self,
        allowed_values: list[str] | None = None,
        none_exclusive: bool = True,
        other_allowed: bool = False,
    ) -> None:
        """
        Initialize multi-select type.

        Args:
            allowed_values: List of allowed code values (optional for validation)
            none_exclusive: Whether NONE selection excludes other values
            other_allowed: Whether OTHER with other_text is allowed
        """
        self._allowed_values = allowed_values
        self._none_exclusive = none_exclusive
        self._other_allowed = other_allowed

    def validate(self, value: dict[str, Any]) -> ValidationResult:
        """Validate multi-select value."""
        if value is None:
            return ValidationResult.valid()

        errors: list[str] = []
        field_errors: dict[str, list[str]] = {}

        # Check required structure
        if not isinstance(value, dict):
            return ValidationResult.invalid(["Value must be a dictionary"])

        values = value.get("values")
        if values is None:
            return ValidationResult.invalid(["Missing required field: values"])

        if not isinstance(values, list):
            return ValidationResult.invalid(["Field 'values' must be a list"])

        # Check all values are strings
        for i, v in enumerate(values):
            if not isinstance(v, str):
                field_errors.setdefault("values", []).append(
                    f"Item {i} must be a string"
                )

        if field_errors:
            return ValidationResult.invalid(
                ["Invalid value types in list"], field_errors
            )

        # Check NONE exclusivity
        if self._none_exclusive and "NONE" in values and len(values) > 1:
            errors.append("NONE cannot be combined with other selections")

        # Check allowed values
        if self._allowed_values:
            for v in values:
                if v not in self._allowed_values:
                    field_errors.setdefault("values", []).append(
                        f"Value '{v}' is not allowed"
                    )

        # Check OTHER requires other_text
        other_text = value.get("other_text")
        if "OTHER" in values:
            if not self._other_allowed:
                errors.append("OTHER selection is not allowed for this control")
            elif not other_text or not other_text.strip():
                errors.append("OTHER selection requires other_text")
        elif other_text:
            errors.append("other_text should only be provided with OTHER selection")

        if errors or field_errors:
            return ValidationResult.invalid(errors, field_errors)

        return ValidationResult.valid()

    def normalize(self, value: dict[str, Any]) -> dict[str, Any]:
        """Normalize multi-select value."""
        if value is None:
            return self.empty_value() or {}

        if not isinstance(value, dict):
            return value

        values = value.get("values", [])
        if not isinstance(values, list):
            return value

        # Case-fold codes to uppercase and sort for stable comparison
        normalized_values = sorted([str(v).upper().strip() for v in values])

        result: dict[str, Any] = {"values": normalized_values}

        # Normalize other_text if present
        other_text = value.get("other_text")
        if other_text is not None:
            result["other_text"] = str(other_text).strip()

        return result

    def parse_form(self, form_data: dict[str, Any]) -> ParseResult:
        """Parse HTML form submission for multi-select."""
        try:
            # Form data may have values as list or single value
            values = form_data.get("values", [])
            if isinstance(values, str):
                values = [values] if values else []
            elif not isinstance(values, list):
                values = []

            # Filter empty strings
            values = [v for v in values if v and str(v).strip()]

            result: dict[str, Any] = {"values": values}

            other_text = form_data.get("other_text")
            if other_text is not None and str(other_text).strip():
                result["other_text"] = str(other_text).strip()

            return ParseResult.success(self.normalize(result), raw_input=form_data)

        except Exception as e:
            return ParseResult.failure([f"Failed to parse form data: {e}"], form_data)

    def parse_workbook(
        self, cell_value: Any, context: dict[str, Any] | None = None
    ) -> ParseResult:
        """
        Parse workbook cell value for multi-select.

        Expected formats:
        - Comma-separated codes: "CODE1, CODE2, CODE3"
        - Semicolon-separated: "CODE1; CODE2"
        - Single value: "CODE1"
        - Empty/None: empty selection
        """
        if cell_value is None or (isinstance(cell_value, str) and not cell_value.strip()):
            return ParseResult.success(self.empty_value() or {}, raw_input=cell_value)

        try:
            cell_str = str(cell_value).strip()

            # Split by comma or semicolon
            if ";" in cell_str:
                values = [v.strip() for v in cell_str.split(";")]
            else:
                values = [v.strip() for v in cell_str.split(",")]

            # Filter empty values
            values = [v for v in values if v]

            result: dict[str, Any] = {"values": values}

            # Check for OTHER pattern like "OTHER: description"
            for i, v in enumerate(values):
                if v.upper().startswith("OTHER:"):
                    other_text = v[6:].strip()
                    values[i] = "OTHER"
                    result["other_text"] = other_text
                    break

            result["values"] = values
            return ParseResult.success(self.normalize(result), raw_input=cell_value)

        except Exception as e:
            return ParseResult.failure(
                [f"Failed to parse workbook value: {e}"], cell_value
            )

    def empty_value(self) -> dict[str, Any] | None:
        """Return empty multi-select value."""
        return {"values": []}

    def unknown_value(self) -> dict[str, Any] | None:
        """Return explicit unknown value."""
        return {"values": [], "_unknown": True}

    def compare(
        self, old: dict[str, Any], new: dict[str, Any]
    ) -> ComparisonResult:
        """Compare two multi-select values for semantic equality."""
        old_norm = self.normalize(old) if old else self.empty_value() or {}
        new_norm = self.normalize(new) if new else self.empty_value() or {}

        # Compare normalized values (sorted lists)
        old_values = set(old_norm.get("values", []))
        new_values = set(new_norm.get("values", []))

        old_other = old_norm.get("other_text", "")
        new_other = new_norm.get("other_text", "")

        if old_values == new_values and old_other == new_other:
            return ComparisonResult.equal()

        differences = []
        if old_values != new_values:
            differences.append({
                "field": "values",
                "old": sorted(old_values),
                "new": sorted(new_values),
            })
        if old_other != new_other:
            differences.append({
                "field": "other_text",
                "old": old_other,
                "new": new_other,
            })

        return ComparisonResult.different(differences)


class TextPairType(ResponseTypeBase):
    """
    Text pair response type with two named text fields.

    Canonical shape: {first: str, second: str} with named fields
    Example: {application_name: "App Name", acronym: "APP"}

    Features:
    - Two named text fields
    - Whitespace trimming
    - Both fields optional but tracked separately
    """

    code = ResponseTypeCodes.TEXT_PAIR
    schema_version = "1.0"
    editor_key = "text_pair_editor"
    display_key = "text_pair_display"
    is_computed = False

    def __init__(
        self,
        first_field: str = "first",
        second_field: str = "second",
        first_required: bool = False,
        second_required: bool = False,
        first_max_length: int | None = None,
        second_max_length: int | None = None,
    ) -> None:
        """
        Initialize text pair type.

        Args:
            first_field: Name of the first field (e.g., 'application_name')
            second_field: Name of the second field (e.g., 'acronym')
            first_required: Whether first field is required
            second_required: Whether second field is required
            first_max_length: Maximum length for first field
            second_max_length: Maximum length for second field
        """
        self._first_field = first_field
        self._second_field = second_field
        self._first_required = first_required
        self._second_required = second_required
        self._first_max_length = first_max_length
        self._second_max_length = second_max_length

    def validate(self, value: dict[str, Any]) -> ValidationResult:
        """Validate text pair value."""
        if value is None:
            if self._first_required or self._second_required:
                return ValidationResult.invalid(["Value is required"])
            return ValidationResult.valid()

        if not isinstance(value, dict):
            return ValidationResult.invalid(["Value must be a dictionary"])

        errors: list[str] = []
        field_errors: dict[str, list[str]] = {}

        first = value.get(self._first_field)
        second = value.get(self._second_field)

        # Check required fields
        if self._first_required and (first is None or not str(first).strip()):
            field_errors[self._first_field] = [f"{self._first_field} is required"]

        if self._second_required and (second is None or not str(second).strip()):
            field_errors[self._second_field] = [f"{self._second_field} is required"]

        # Check max lengths
        if first is not None and self._first_max_length:
            if len(str(first)) > self._first_max_length:
                field_errors.setdefault(self._first_field, []).append(
                    f"{self._first_field} exceeds maximum length of {self._first_max_length}"
                )

        if second is not None and self._second_max_length:
            if len(str(second)) > self._second_max_length:
                field_errors.setdefault(self._second_field, []).append(
                    f"{self._second_field} exceeds maximum length of {self._second_max_length}"
                )

        if errors or field_errors:
            return ValidationResult.invalid(errors, field_errors)

        return ValidationResult.valid()

    def normalize(self, value: dict[str, Any]) -> dict[str, Any]:
        """Normalize text pair value by trimming whitespace."""
        if value is None:
            return self.empty_value() or {}

        if not isinstance(value, dict):
            return value

        result: dict[str, Any] = {}

        first = value.get(self._first_field)
        if first is not None:
            result[self._first_field] = str(first).strip()
        else:
            result[self._first_field] = None

        second = value.get(self._second_field)
        if second is not None:
            result[self._second_field] = str(second).strip()
        else:
            result[self._second_field] = None

        return result

    def parse_form(self, form_data: dict[str, Any]) -> ParseResult:
        """Parse HTML form submission for text pair."""
        try:
            result: dict[str, Any] = {}

            first = form_data.get(self._first_field)
            if first is not None:
                result[self._first_field] = str(first).strip()
            else:
                result[self._first_field] = None

            second = form_data.get(self._second_field)
            if second is not None:
                result[self._second_field] = str(second).strip()
            else:
                result[self._second_field] = None

            return ParseResult.success(result, raw_input=form_data)

        except Exception as e:
            return ParseResult.failure([f"Failed to parse form data: {e}"], form_data)

    def parse_workbook(
        self, cell_value: Any, context: dict[str, Any] | None = None
    ) -> ParseResult:
        """
        Parse workbook cell value for text pair.

        Context should provide the field mapping or second cell value.
        Expected context: {first_value: ..., second_value: ...}
        Or single cell with separator: "First Value | Second Value"
        """
        if cell_value is None:
            return ParseResult.success(self.empty_value() or {}, raw_input=cell_value)

        try:
            # If context provides both values
            if context and self._first_field in context:
                result = {
                    self._first_field: context.get(self._first_field),
                    self._second_field: context.get(self._second_field),
                }
                return ParseResult.success(self.normalize(result), raw_input=cell_value)

            # Try to parse from single cell with separator
            cell_str = str(cell_value).strip()
            if "|" in cell_str:
                parts = cell_str.split("|", 1)
                result = {
                    self._first_field: parts[0].strip() if parts[0].strip() else None,
                    self._second_field: parts[1].strip() if len(parts) > 1 and parts[1].strip() else None,
                }
            else:
                # Single value goes to first field
                result = {
                    self._first_field: cell_str if cell_str else None,
                    self._second_field: None,
                }

            return ParseResult.success(self.normalize(result), raw_input=cell_value)

        except Exception as e:
            return ParseResult.failure(
                [f"Failed to parse workbook value: {e}"], cell_value
            )

    def empty_value(self) -> dict[str, Any] | None:
        """Return empty text pair value."""
        return {self._first_field: None, self._second_field: None}

    def unknown_value(self) -> dict[str, Any] | None:
        """Return explicit unknown value."""
        return {self._first_field: None, self._second_field: None, "_unknown": True}

    def compare(
        self, old: dict[str, Any], new: dict[str, Any]
    ) -> ComparisonResult:
        """Compare two text pair values for semantic equality."""
        old_norm = self.normalize(old) if old else self.empty_value() or {}
        new_norm = self.normalize(new) if new else self.empty_value() or {}

        old_first = old_norm.get(self._first_field) or ""
        old_second = old_norm.get(self._second_field) or ""
        new_first = new_norm.get(self._first_field) or ""
        new_second = new_norm.get(self._second_field) or ""

        if old_first == new_first and old_second == new_second:
            return ComparisonResult.equal()

        differences = []
        if old_first != new_first:
            differences.append({
                "field": self._first_field,
                "old": old_first,
                "new": new_first,
            })
        if old_second != new_second:
            differences.append({
                "field": self._second_field,
                "old": old_second,
                "new": new_second,
            })

        return ComparisonResult.different(differences)


class CountPairType(ResponseTypeBase):
    """
    Count pair response type for two nonnegative integers.

    Canonical shape: {first: int|null, second: int|null, unit: str}
    Example: {internal_users: 100, external_users: 50, unit: "users"}

    Features:
    - Two nonnegative integer fields
    - null differs from zero (null = unknown, 0 = zero count)
    - Optional unit field for context
    """

    code = ResponseTypeCodes.COUNT_PAIR
    schema_version = "1.0"
    editor_key = "count_pair_editor"
    display_key = "count_pair_display"
    is_computed = False

    def __init__(
        self,
        first_field: str = "first",
        second_field: str = "second",
        unit: str = "count",
        max_value: int | None = None,
    ) -> None:
        """
        Initialize count pair type.

        Args:
            first_field: Name of the first count field (e.g., 'internal_users')
            second_field: Name of the second count field (e.g., 'external_users')
            unit: Unit label for the counts
            max_value: Maximum allowed value
        """
        self._first_field = first_field
        self._second_field = second_field
        self._unit = unit
        self._max_value = max_value

    def validate(self, value: dict[str, Any]) -> ValidationResult:
        """Validate count pair value."""
        if value is None:
            return ValidationResult.valid()

        if not isinstance(value, dict):
            return ValidationResult.invalid(["Value must be a dictionary"])

        errors: list[str] = []
        field_errors: dict[str, list[str]] = {}

        for field_name in [self._first_field, self._second_field]:
            field_value = value.get(field_name)

            if field_value is None:
                # null is valid (represents unknown)
                continue

            # Must be an integer
            if not isinstance(field_value, int) or isinstance(field_value, bool):
                field_errors.setdefault(field_name, []).append(
                    f"{field_name} must be an integer or null"
                )
                continue

            # Must be nonnegative
            if field_value < 0:
                field_errors.setdefault(field_name, []).append(
                    f"{field_name} must be nonnegative"
                )

            # Check max value
            if self._max_value is not None and field_value > self._max_value:
                field_errors.setdefault(field_name, []).append(
                    f"{field_name} exceeds maximum value of {self._max_value}"
                )

        if errors or field_errors:
            return ValidationResult.invalid(errors, field_errors)

        return ValidationResult.valid()

    def normalize(self, value: dict[str, Any]) -> dict[str, Any]:
        """Normalize count pair value."""
        if value is None:
            return self.empty_value() or {}

        if not isinstance(value, dict):
            return value

        result: dict[str, Any] = {
            self._first_field: value.get(self._first_field),
            self._second_field: value.get(self._second_field),
            "unit": value.get("unit", self._unit),
        }

        # Ensure integers are properly typed
        for field_name in [self._first_field, self._second_field]:
            field_value = result[field_name]
            if field_value is not None:
                try:
                    result[field_name] = int(field_value)
                except (ValueError, TypeError):
                    result[field_name] = None

        return result

    def parse_form(self, form_data: dict[str, Any]) -> ParseResult:
        """Parse HTML form submission for count pair."""
        try:
            result: dict[str, Any] = {"unit": self._unit}

            for field_name in [self._first_field, self._second_field]:
                field_value = form_data.get(field_name)

                if field_value is None or field_value == "":
                    result[field_name] = None
                else:
                    try:
                        result[field_name] = int(field_value)
                    except (ValueError, TypeError):
                        return ParseResult.failure(
                            [f"Invalid integer value for {field_name}: {field_value}"],
                            form_data,
                        )

            return ParseResult.success(result, raw_input=form_data)

        except Exception as e:
            return ParseResult.failure([f"Failed to parse form data: {e}"], form_data)

    def parse_workbook(
        self, cell_value: Any, context: dict[str, Any] | None = None
    ) -> ParseResult:
        """
        Parse workbook cell value for count pair.

        Context should provide both values or cell contains "first / second" format.
        """
        if cell_value is None:
            return ParseResult.success(self.empty_value() or {}, raw_input=cell_value)

        try:
            # If context provides both values
            if context and self._first_field in context:
                first = context.get(self._first_field)
                second = context.get(self._second_field)
            else:
                # Try to parse from single cell with separator
                cell_str = str(cell_value).strip()
                if "/" in cell_str:
                    parts = cell_str.split("/", 1)
                    first = parts[0].strip() if parts[0].strip() else None
                    second = parts[1].strip() if len(parts) > 1 and parts[1].strip() else None
                else:
                    # Single value goes to first field
                    first = cell_str if cell_str else None
                    second = None

            result: dict[str, Any] = {"unit": self._unit}

            # Parse first value
            if first is None or first == "":
                result[self._first_field] = None
            else:
                try:
                    result[self._first_field] = int(first)
                except (ValueError, TypeError):
                    return ParseResult.failure(
                        [f"Invalid integer value for {self._first_field}: {first}"],
                        cell_value,
                    )

            # Parse second value
            if second is None or second == "":
                result[self._second_field] = None
            else:
                try:
                    result[self._second_field] = int(second)
                except (ValueError, TypeError):
                    return ParseResult.failure(
                        [f"Invalid integer value for {self._second_field}: {second}"],
                        cell_value,
                    )

            return ParseResult.success(result, raw_input=cell_value)

        except Exception as e:
            return ParseResult.failure(
                [f"Failed to parse workbook value: {e}"], cell_value
            )

    def empty_value(self) -> dict[str, Any] | None:
        """Return empty count pair value (null differs from zero)."""
        return {
            self._first_field: None,
            self._second_field: None,
            "unit": self._unit,
        }

    def unknown_value(self) -> dict[str, Any] | None:
        """Return explicit unknown value."""
        return {
            self._first_field: None,
            self._second_field: None,
            "unit": self._unit,
            "_unknown": True,
        }

    def compare(
        self, old: dict[str, Any], new: dict[str, Any]
    ) -> ComparisonResult:
        """Compare two count pair values for semantic equality."""
        old_norm = self.normalize(old) if old else self.empty_value() or {}
        new_norm = self.normalize(new) if new else self.empty_value() or {}

        old_first = old_norm.get(self._first_field)
        old_second = old_norm.get(self._second_field)
        new_first = new_norm.get(self._first_field)
        new_second = new_norm.get(self._second_field)

        if old_first == new_first and old_second == new_second:
            return ComparisonResult.equal()

        differences = []
        if old_first != new_first:
            differences.append({
                "field": self._first_field,
                "old": old_first,
                "new": new_first,
            })
        if old_second != new_second:
            differences.append({
                "field": self._second_field,
                "old": old_second,
                "new": new_second,
            })

        return ComparisonResult.different(differences)


class ControlledPairType(ResponseTypeBase):
    """
    Controlled pair response type with two controlled vocabulary fields.

    Canonical shape: {first: code, second: code} with named schema fields
    Example: {business_criticality: "HIGH", emergency_tier: "TIER_2"}

    Features:
    - Two controlled vocabulary fields
    - Cross-field validation support
    - Case-folded code normalization
    """

    code = ResponseTypeCodes.CONTROLLED_PAIR
    schema_version = "1.0"
    editor_key = "controlled_pair_editor"
    display_key = "controlled_pair_display"
    is_computed = False

    def __init__(
        self,
        first_field: str = "first",
        second_field: str = "second",
        first_allowed: list[str] | None = None,
        second_allowed: list[str] | None = None,
        cross_validation: Callable[[str, str], list[str]] | None = None,
    ) -> None:
        """
        Initialize controlled pair type.

        Args:
            first_field: Name of the first field (e.g., 'business_criticality')
            second_field: Name of the second field (e.g., 'emergency_tier')
            first_allowed: Allowed values for first field
            second_allowed: Allowed values for second field
            cross_validation: Optional function for cross-field validation
        """
        self._first_field = first_field
        self._second_field = second_field
        self._first_allowed = first_allowed
        self._second_allowed = second_allowed
        self._cross_validation = cross_validation

    def validate(self, value: dict[str, Any]) -> ValidationResult:
        """Validate controlled pair value."""
        if value is None:
            return ValidationResult.valid()

        if not isinstance(value, dict):
            return ValidationResult.invalid(["Value must be a dictionary"])

        errors: list[str] = []
        field_errors: dict[str, list[str]] = {}

        first = value.get(self._first_field)
        second = value.get(self._second_field)

        # Validate first field
        if first is not None:
            if not isinstance(first, str):
                field_errors[self._first_field] = [f"{self._first_field} must be a string"]
            elif self._first_allowed and first.upper() not in self._first_allowed:
                field_errors[self._first_field] = [
                    f"'{first}' is not a valid value for {self._first_field}"
                ]

        # Validate second field
        if second is not None:
            if not isinstance(second, str):
                field_errors[self._second_field] = [f"{self._second_field} must be a string"]
            elif self._second_allowed and second.upper() not in self._second_allowed:
                field_errors[self._second_field] = [
                    f"'{second}' is not a valid value for {self._second_field}"
                ]

        # Cross-field validation
        if self._cross_validation and first and second:
            cross_errors = self._cross_validation(first, second)
            if cross_errors:
                errors.extend(cross_errors)

        if errors or field_errors:
            return ValidationResult.invalid(errors, field_errors)

        return ValidationResult.valid()

    def normalize(self, value: dict[str, Any]) -> dict[str, Any]:
        """Normalize controlled pair value by case-folding codes."""
        if value is None:
            return self.empty_value() or {}

        if not isinstance(value, dict):
            return value

        result: dict[str, Any] = {}

        first = value.get(self._first_field)
        if first is not None:
            result[self._first_field] = str(first).upper().strip()
        else:
            result[self._first_field] = None

        second = value.get(self._second_field)
        if second is not None:
            result[self._second_field] = str(second).upper().strip()
        else:
            result[self._second_field] = None

        return result

    def parse_form(self, form_data: dict[str, Any]) -> ParseResult:
        """Parse HTML form submission for controlled pair."""
        try:
            result: dict[str, Any] = {}

            first = form_data.get(self._first_field)
            if first is not None and str(first).strip():
                result[self._first_field] = str(first).upper().strip()
            else:
                result[self._first_field] = None

            second = form_data.get(self._second_field)
            if second is not None and str(second).strip():
                result[self._second_field] = str(second).upper().strip()
            else:
                result[self._second_field] = None

            return ParseResult.success(result, raw_input=form_data)

        except Exception as e:
            return ParseResult.failure([f"Failed to parse form data: {e}"], form_data)

    def parse_workbook(
        self, cell_value: Any, context: dict[str, Any] | None = None
    ) -> ParseResult:
        """
        Parse workbook cell value for controlled pair.

        Context should provide both values or cell contains "first / second" format.
        """
        if cell_value is None:
            return ParseResult.success(self.empty_value() or {}, raw_input=cell_value)

        try:
            # If context provides both values
            if context and self._first_field in context:
                result = {
                    self._first_field: context.get(self._first_field),
                    self._second_field: context.get(self._second_field),
                }
                return ParseResult.success(self.normalize(result), raw_input=cell_value)

            # Try to parse from single cell with separator
            cell_str = str(cell_value).strip()
            if "/" in cell_str:
                parts = cell_str.split("/", 1)
                result = {
                    self._first_field: parts[0].strip().upper() if parts[0].strip() else None,
                    self._second_field: parts[1].strip().upper() if len(parts) > 1 and parts[1].strip() else None,
                }
            else:
                # Single value goes to first field
                result = {
                    self._first_field: cell_str.upper() if cell_str else None,
                    self._second_field: None,
                }

            return ParseResult.success(result, raw_input=cell_value)

        except Exception as e:
            return ParseResult.failure(
                [f"Failed to parse workbook value: {e}"], cell_value
            )

    def empty_value(self) -> dict[str, Any] | None:
        """Return empty controlled pair value."""
        return {self._first_field: None, self._second_field: None}

    def unknown_value(self) -> dict[str, Any] | None:
        """Return explicit unknown value."""
        return {self._first_field: None, self._second_field: None, "_unknown": True}

    def compare(
        self, old: dict[str, Any], new: dict[str, Any]
    ) -> ComparisonResult:
        """Compare two controlled pair values for semantic equality."""
        old_norm = self.normalize(old) if old else self.empty_value() or {}
        new_norm = self.normalize(new) if new else self.empty_value() or {}

        old_first = old_norm.get(self._first_field)
        old_second = old_norm.get(self._second_field)
        new_first = new_norm.get(self._first_field)
        new_second = new_norm.get(self._second_field)

        if old_first == new_first and old_second == new_second:
            return ComparisonResult.equal()

        differences = []
        if old_first != new_first:
            differences.append({
                "field": self._first_field,
                "old": old_first,
                "new": new_first,
            })
        if old_second != new_second:
            differences.append({
                "field": self._second_field,
                "old": old_second,
                "new": new_second,
            })

        return ComparisonResult.different(differences)


class PeopleListType(ResponseTypeBase):
    """
    People list response type for repeatable people entries.

    Canonical shape: {people: [{role_code, name, attuid?, email?, primary}]}
    Example: {people: [{role_code: "APPLICATION_OWNER", name: "John Doe", primary: true}]}

    Features:
    - Repeatable people entries
    - Role code from controlled vocabulary
    - Optional identity fields (attuid, email)
    - Primary role designation
    - Identity format validation
    """

    code = ResponseTypeCodes.PEOPLE_LIST
    schema_version = "1.0"
    editor_key = "people_list_editor"
    display_key = "people_list_display"
    is_computed = False

    # Email validation pattern
    EMAIL_PATTERN = re.compile(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$")
    # ATTUID pattern (alphanumeric, typically 6-8 characters)
    ATTUID_PATTERN = re.compile(r"^[a-zA-Z0-9]{2,10}$")

    def __init__(
        self,
        allowed_roles: list[str] | None = None,
        require_primary: bool = False,
        max_people: int | None = None,
    ) -> None:
        """
        Initialize people list type.

        Args:
            allowed_roles: List of allowed role codes
            require_primary: Whether at least one primary person is required
            max_people: Maximum number of people allowed
        """
        self._allowed_roles = allowed_roles
        self._require_primary = require_primary
        self._max_people = max_people

    def validate(self, value: dict[str, Any]) -> ValidationResult:
        """Validate people list value."""
        if value is None:
            return ValidationResult.valid()

        if not isinstance(value, dict):
            return ValidationResult.invalid(["Value must be a dictionary"])

        people = value.get("people")
        if people is None:
            return ValidationResult.invalid(["Missing required field: people"])

        if not isinstance(people, list):
            return ValidationResult.invalid(["Field 'people' must be a list"])

        errors: list[str] = []
        field_errors: dict[str, list[str]] = {}

        # Check max people
        if self._max_people is not None and len(people) > self._max_people:
            errors.append(f"Maximum {self._max_people} people allowed")

        primary_count = 0

        for i, person in enumerate(people):
            if not isinstance(person, dict):
                field_errors.setdefault(f"people[{i}]", []).append(
                    "Person entry must be a dictionary"
                )
                continue

            # Validate role_code
            role_code = person.get("role_code")
            if not role_code:
                field_errors.setdefault(f"people[{i}].role_code", []).append(
                    "role_code is required"
                )
            elif self._allowed_roles and role_code.upper() not in self._allowed_roles:
                field_errors.setdefault(f"people[{i}].role_code", []).append(
                    f"'{role_code}' is not a valid role"
                )

            # Validate name
            name = person.get("name")
            if not name or not str(name).strip():
                field_errors.setdefault(f"people[{i}].name", []).append(
                    "name is required"
                )

            # Validate email format if provided
            email = person.get("email")
            if email and not self.EMAIL_PATTERN.match(str(email)):
                field_errors.setdefault(f"people[{i}].email", []).append(
                    "Invalid email format"
                )

            # Validate attuid format if provided
            attuid = person.get("attuid")
            if attuid and not self.ATTUID_PATTERN.match(str(attuid)):
                field_errors.setdefault(f"people[{i}].attuid", []).append(
                    "Invalid ATTUID format"
                )

            # Track primary
            if person.get("primary"):
                primary_count += 1

        # Check primary requirement
        if self._require_primary and primary_count == 0 and len(people) > 0:
            errors.append("At least one person must be marked as primary")

        if errors or field_errors:
            return ValidationResult.invalid(errors, field_errors)

        return ValidationResult.valid()

    def normalize(self, value: dict[str, Any]) -> dict[str, Any]:
        """Normalize people list value."""
        if value is None:
            return self.empty_value() or {}

        if not isinstance(value, dict):
            return value

        people = value.get("people", [])
        if not isinstance(people, list):
            return value

        normalized_people = []
        for person in people:
            if not isinstance(person, dict):
                continue

            normalized_person: dict[str, Any] = {}

            # Normalize role_code
            role_code = person.get("role_code")
            if role_code:
                normalized_person["role_code"] = str(role_code).upper().strip()

            # Normalize name
            name = person.get("name")
            if name:
                normalized_person["name"] = str(name).strip()

            # Normalize attuid (lowercase)
            attuid = person.get("attuid")
            if attuid:
                normalized_person["attuid"] = str(attuid).lower().strip()
            else:
                normalized_person["attuid"] = None

            # Normalize email (lowercase)
            email = person.get("email")
            if email:
                normalized_person["email"] = str(email).lower().strip()
            else:
                normalized_person["email"] = None

            # Normalize primary (boolean)
            normalized_person["primary"] = bool(person.get("primary", False))

            normalized_people.append(normalized_person)

        return {"people": normalized_people}

    def parse_form(self, form_data: dict[str, Any]) -> ParseResult:
        """Parse HTML form submission for people list."""
        try:
            people_data = form_data.get("people")
            if people_data is None or not isinstance(people_data, list):
                # Try to parse from indexed form fields
                people_data = self._parse_indexed_form_fields(form_data)

            # If still empty, use empty list
            if not people_data:
                people_data = []

            result = {"people": people_data}
            return ParseResult.success(self.normalize(result), raw_input=form_data)

        except Exception as e:
            return ParseResult.failure([f"Failed to parse form data: {e}"], form_data)

    def _parse_indexed_form_fields(self, form_data: dict[str, Any]) -> list[dict[str, Any]]:
        """Parse indexed form fields like people[0].name, people[1].name, etc."""
        people: dict[int, dict[str, Any]] = {}

        for key, value in form_data.items():
            # Match patterns like people[0].name or people_0_name
            match = re.match(r"people\[(\d+)\]\.(\w+)", key)
            if not match:
                match = re.match(r"people_(\d+)_(\w+)", key)

            if match:
                idx = int(match.group(1))
                field = match.group(2)
                if idx not in people:
                    people[idx] = {}
                people[idx][field] = value

        # Convert to sorted list
        return [people[i] for i in sorted(people.keys())]

    def parse_workbook(
        self, cell_value: Any, context: dict[str, Any] | None = None
    ) -> ParseResult:
        """
        Parse workbook cell value for people list.

        Expected formats:
        - Context with people list: {people: [...]}
        - Semicolon-separated entries: "Role: Name; Role: Name"
        - Single entry: "Role: Name"
        """
        if cell_value is None:
            return ParseResult.success(self.empty_value() or {}, raw_input=cell_value)

        try:
            # If context provides people list
            if context and "people" in context:
                return ParseResult.success(
                    self.normalize({"people": context["people"]}),
                    raw_input=cell_value,
                )

            # Parse from cell string
            cell_str = str(cell_value).strip()
            if not cell_str:
                return ParseResult.success(self.empty_value() or {}, raw_input=cell_value)

            people: list[dict[str, Any]] = []
            entries = cell_str.split(";")

            for entry in entries:
                entry = entry.strip()
                if not entry:
                    continue

                # Try to parse "Role: Name" or "Name (Role)"
                if ":" in entry:
                    parts = entry.split(":", 1)
                    role_code = parts[0].strip()
                    name = parts[1].strip()
                elif "(" in entry and ")" in entry:
                    # "Name (Role)" format
                    match = re.match(r"(.+)\s*\(([^)]+)\)", entry)
                    if match:
                        name = match.group(1).strip()
                        role_code = match.group(2).strip()
                    else:
                        name = entry
                        role_code = "UNKNOWN"
                else:
                    name = entry
                    role_code = "UNKNOWN"

                people.append({
                    "role_code": role_code.upper().replace(" ", "_"),
                    "name": name,
                    "attuid": None,
                    "email": None,
                    "primary": len(people) == 0,  # First person is primary
                })

            return ParseResult.success(
                self.normalize({"people": people}),
                raw_input=cell_value,
            )

        except Exception as e:
            return ParseResult.failure(
                [f"Failed to parse workbook value: {e}"], cell_value
            )

    def empty_value(self) -> dict[str, Any] | None:
        """Return empty people list value."""
        return {"people": []}

    def unknown_value(self) -> dict[str, Any] | None:
        """Return explicit unknown value."""
        return {"people": [], "_unknown": True}

    def compare(
        self, old: dict[str, Any], new: dict[str, Any]
    ) -> ComparisonResult:
        """Compare two people list values for semantic equality."""
        old_norm = self.normalize(old) if old else self.empty_value() or {}
        new_norm = self.normalize(new) if new else self.empty_value() or {}

        old_people = old_norm.get("people", [])
        new_people = new_norm.get("people", [])

        # Compare by converting to comparable tuples
        def person_key(p: dict[str, Any]) -> tuple[str, str, str, str, bool]:
            return (
                p.get("role_code", ""),
                p.get("name", ""),
                p.get("attuid") or "",
                p.get("email") or "",
                p.get("primary", False),
            )

        old_set = set(person_key(p) for p in old_people)
        new_set = set(person_key(p) for p in new_people)

        if old_set == new_set:
            return ComparisonResult.equal()

        differences = [{
            "field": "people",
            "old": old_people,
            "new": new_people,
        }]

        return ComparisonResult.different(differences)
