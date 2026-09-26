"""
Measurement response types (R03).

This module implements the four measurement response types:
- MEASUREMENT: Single decimal value with unit, qualifier, and observed_at
- MEASUREMENT_PAIR: Two named measurements (e.g., latency/bandwidth)
- MEASUREMENT_SET: Repeatable metrics with unique metric/scope combinations
- MEASUREMENT_CONTEXT: Structured metrics with evidence window and source context
"""

from __future__ import annotations

import math
import re
from decimal import Decimal, InvalidOperation
from typing import Any

from migration_intake.catalog.response_types.base import (
    ParseResult,
    ResponseTypeBase,
    ResponseTypeCodes,
    ValidationResult,
)

# Common unit categories for validation
VALID_UNITS: set[str] = {
    # Time units
    "ms", "s", "sec", "min", "h", "hr", "d", "day", "days",
    # Data size units
    "B", "KB", "MB", "GB", "TB", "PB",
    "KiB", "MiB", "GiB", "TiB", "PiB",
    # Rate units
    "req/s", "rps", "tps", "qps", "ops/s",
    "B/s", "KB/s", "MB/s", "GB/s",
    "Kbps", "Mbps", "Gbps",
    # Count units
    "count", "items", "records", "rows", "users", "connections",
    # Percentage
    "%", "percent", "pct",
    # Memory/CPU
    "cores", "vCPU", "CPU",
    # Other
    "instances", "nodes", "replicas", "pods",
}

# Valid qualifiers for measurements
VALID_QUALIFIERS: set[str] = {
    "exact", "approximate", "minimum", "maximum",
    "average", "median", "p50", "p90", "p95", "p99", "p999",
    "peak", "baseline", "target", "threshold",
}


def _parse_decimal(value: Any) -> tuple[Decimal | None, str | None]:
    """
    Parse a value to Decimal.

    Returns:
        Tuple of (decimal_value, error_message).
        On success, error_message is None.
        On failure, decimal_value is None.
    """
    if value is None:
        return None, None

    if isinstance(value, Decimal):
        if value.is_nan() or value.is_infinite():
            return None, "Value cannot be NaN or infinity"
        return value, None

    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return None, "Value cannot be NaN or infinity"
        try:
            return Decimal(str(value)), None
        except InvalidOperation:
            return None, f"Cannot convert float to decimal: {value}"

    if isinstance(value, int):
        return Decimal(value), None

    if isinstance(value, str):
        value = value.strip()
        if not value:
            return None, None
        try:
            d = Decimal(value)
            if d.is_nan() or d.is_infinite():
                return None, "Value cannot be NaN or infinity"
            return d, None
        except InvalidOperation:
            return None, f"Invalid decimal value: {value}"

    return None, f"Cannot parse value of type {type(value).__name__}"


def _normalize_decimal(value: Decimal | None) -> str | None:
    """
    Normalize a Decimal to canonical string representation.

    Removes trailing zeros while preserving standard decimal notation
    (avoids scientific notation like 1E+2).
    """
    if value is None:
        return None

    # Remove trailing zeros
    # We use a technique that avoids scientific notation:
    # 1. Normalize to remove trailing zeros
    # 2. If result would be in scientific notation, convert back to fixed
    normalized = value.normalize()

    # Check if the string representation uses scientific notation
    str_val = str(normalized)
    if 'E' in str_val or 'e' in str_val:
        # Convert back to fixed-point notation
        # Get the sign, coefficient, and exponent
        sign, digits, exponent = normalized.as_tuple()

        # For special values (NaN, Inf), exponent is a string - just return str_val
        if not isinstance(exponent, int):
            return str_val

        # Calculate the number of digits
        num_digits = len(digits)

        # Build the string representation
        if exponent >= 0:
            # Positive exponent: append zeros
            digit_str = ''.join(str(d) for d in digits) + '0' * exponent
            result = digit_str
        else:
            # Negative exponent: insert decimal point
            abs_exp = abs(exponent)
            digit_str = ''.join(str(d) for d in digits)

            if abs_exp >= num_digits:
                # Need leading zeros after decimal point
                result = '0.' + '0' * (abs_exp - num_digits) + digit_str
            else:
                # Decimal point goes within the digits
                result = digit_str[:-abs_exp] + '.' + digit_str[-abs_exp:]

        # Add sign if negative
        if sign:
            result = '-' + result

        return result

    return str_val


def _validate_unit(unit: Any) -> str | None:
    """
    Validate a unit string.

    Returns error message if invalid, None if valid.
    """
    if unit is None:
        return "Unit is required"

    if not isinstance(unit, str):
        return f"Unit must be a string, got {type(unit).__name__}"

    unit = unit.strip()
    if not unit:
        return "Unit cannot be empty"

    # Allow any non-empty string as unit for flexibility
    # The VALID_UNITS set is for documentation, not strict validation
    return None


def _validate_qualifier(qualifier: Any) -> str | None:
    """
    Validate a qualifier string.

    Returns error message if invalid, None if valid.
    """
    if qualifier is None:
        return None  # Qualifier is optional

    if not isinstance(qualifier, str):
        return f"Qualifier must be a string, got {type(qualifier).__name__}"

    qualifier = qualifier.strip().lower()
    if qualifier and qualifier not in VALID_QUALIFIERS:
        valid_list = ", ".join(sorted(VALID_QUALIFIERS))
        return f"Invalid qualifier: {qualifier}. Valid values: {valid_list}"

    return None


def _validate_observed_at(observed_at: Any) -> str | None:
    """
    Validate an observed_at timestamp.

    Returns error message if invalid, None if valid.
    """
    if observed_at is None:
        return None  # observed_at is optional

    if not isinstance(observed_at, str):
        return f"observed_at must be a string, got {type(observed_at).__name__}"

    # Basic ISO 8601 date/datetime pattern
    iso_pattern = r"^\d{4}-\d{2}-\d{2}(T\d{2}:\d{2}(:\d{2})?(\.\d+)?(Z|[+-]\d{2}:\d{2})?)?$"
    if not re.match(iso_pattern, observed_at.strip()):
        return f"Invalid observed_at format: {observed_at}. Expected ISO 8601 date/datetime."

    return None


class MeasurementType(ResponseTypeBase):
    """
    Single measurement with decimal value and unit.

    Schema: {value: decimal|null, unit: str, qualifier?: str, observed_at?: str}

    Examples:
        {"value": "150", "unit": "ms", "qualifier": "p99"}
        {"value": "2.5", "unit": "GB", "observed_at": "2024-01-15"}
    """

    code = ResponseTypeCodes.MEASUREMENT
    schema_version = "1.0"
    editor_key = "measurement_editor"
    display_key = "measurement_display"
    is_computed = False

    def validate(self, value: dict[str, Any]) -> ValidationResult:
        """Validate a measurement value."""
        if value is None:
            return ValidationResult.valid()

        if not isinstance(value, dict):
            return ValidationResult.invalid(
                [f"Expected dict, got {type(value).__name__}"]
            )

        field_errors: dict[str, list[str]] = {}

        # Check for unknown marker
        if value.get("_unknown"):
            return ValidationResult.valid()

        # Validate value field
        raw_value = value.get("value")
        if raw_value is not None:
            _decimal_val, err = _parse_decimal(raw_value)
            if err:
                field_errors["value"] = [err]

        # Validate unit
        unit_err = _validate_unit(value.get("unit"))
        if unit_err and raw_value is not None:
            # Unit is required only if value is provided
            field_errors["unit"] = [unit_err]

        # Validate qualifier
        qualifier_err = _validate_qualifier(value.get("qualifier"))
        if qualifier_err:
            field_errors["qualifier"] = [qualifier_err]

        # Validate observed_at
        observed_at_err = _validate_observed_at(value.get("observed_at"))
        if observed_at_err:
            field_errors["observed_at"] = [observed_at_err]

        if field_errors:
            all_errors = []
            for _field, errs in field_errors.items():
                all_errors.extend(errs)
            return ValidationResult.invalid(all_errors, field_errors)

        return ValidationResult.valid()

    def normalize(self, value: dict[str, Any]) -> dict[str, Any]:
        """Normalize a measurement value."""
        if value is None:
            return self.empty_value() or {}

        if not isinstance(value, dict):
            return value

        if value.get("_unknown"):
            return {"_unknown": True}

        result: dict[str, Any] = {}

        # Normalize value
        raw_value = value.get("value")
        if raw_value is not None:
            decimal_val, _ = _parse_decimal(raw_value)
            result["value"] = _normalize_decimal(decimal_val)
        else:
            result["value"] = None

        # Normalize unit
        unit = value.get("unit")
        if unit is not None:
            result["unit"] = str(unit).strip()
        else:
            result["unit"] = None

        # Normalize qualifier
        qualifier = value.get("qualifier")
        if qualifier is not None:
            result["qualifier"] = str(qualifier).strip().lower()

        # Normalize observed_at
        observed_at = value.get("observed_at")
        if observed_at is not None:
            result["observed_at"] = str(observed_at).strip()

        return result

    def parse_form(self, form_data: dict[str, Any]) -> ParseResult:
        """Parse HTML form data into measurement value."""
        if not form_data:
            return ParseResult.success(self.empty_value() or {})

        result: dict[str, Any] = {}
        warnings: list[str] = []

        # Parse value
        raw_value = form_data.get("value", "")
        if isinstance(raw_value, str):
            raw_value = raw_value.strip()

        if raw_value:
            decimal_val, err = _parse_decimal(raw_value)
            if err:
                return ParseResult.failure([err], form_data)
            result["value"] = _normalize_decimal(decimal_val)
        else:
            result["value"] = None

        # Parse unit
        unit = form_data.get("unit", "")
        if isinstance(unit, str):
            unit = unit.strip()
        result["unit"] = unit if unit else None

        # Parse qualifier
        qualifier = form_data.get("qualifier", "")
        if isinstance(qualifier, str):
            qualifier = qualifier.strip().lower()
        if qualifier:
            result["qualifier"] = qualifier

        # Parse observed_at
        observed_at = form_data.get("observed_at", "")
        if isinstance(observed_at, str):
            observed_at = observed_at.strip()
        if observed_at:
            result["observed_at"] = observed_at

        return ParseResult.success(result, warnings, form_data)

    def parse_workbook(
        self, cell_value: Any, context: dict[str, Any] | None = None
    ) -> ParseResult:
        """Parse workbook cell value into measurement."""
        if cell_value is None or (isinstance(cell_value, str) and not cell_value.strip()):
            return ParseResult.success(self.empty_value() or {})

        context = context or {}
        result: dict[str, Any] = {}

        # If cell_value is a number, use it directly
        if isinstance(cell_value, (int, float, Decimal)):
            decimal_val, err = _parse_decimal(cell_value)
            if err:
                return ParseResult.failure([err], cell_value)
            result["value"] = _normalize_decimal(decimal_val)
            result["unit"] = context.get("unit")
            if context.get("qualifier"):
                result["qualifier"] = context["qualifier"]
            if context.get("observed_at"):
                result["observed_at"] = context["observed_at"]
            return ParseResult.success(result, raw_input=cell_value)

        # If cell_value is a string, try to parse "value unit" format
        if isinstance(cell_value, str):
            cell_value = cell_value.strip()

            # Try to match "123.45 ms" or "123.45ms" pattern
            match = re.match(r"^(-?[\d.]+)\s*(\S+)?$", cell_value)
            if match:
                value_str, unit = match.groups()
                decimal_val, err = _parse_decimal(value_str)
                if err:
                    return ParseResult.failure([err], cell_value)
                result["value"] = _normalize_decimal(decimal_val)
                result["unit"] = unit or context.get("unit")
                if context.get("qualifier"):
                    result["qualifier"] = context["qualifier"]
                if context.get("observed_at"):
                    result["observed_at"] = context["observed_at"]
                return ParseResult.success(result, raw_input=cell_value)

            return ParseResult.failure(
                [f"Cannot parse measurement from: {cell_value}"],
                cell_value
            )

        return ParseResult.failure(
            [f"Unexpected cell value type: {type(cell_value).__name__}"],
            cell_value
        )

    def empty_value(self) -> dict[str, Any] | None:
        """Return empty measurement value."""
        return {"value": None, "unit": None}

    def unknown_value(self) -> dict[str, Any] | None:
        """Return explicit unknown value."""
        return {"_unknown": True}


class MeasurementPairType(ResponseTypeBase):
    """
    Two named measurements (e.g., latency/bandwidth).

    Schema: {
        first: {value: decimal|null, unit: str},
        second: {value: decimal|null, unit: str},
        evidence_window?: str
    }

    Examples:
        {
            "first": {"value": "150", "unit": "ms"},
            "second": {"value": "100", "unit": "Mbps"},
            "evidence_window": "2024-Q1"
        }
    """

    code = ResponseTypeCodes.MEASUREMENT_PAIR
    schema_version = "1.0"
    editor_key = "measurement_pair_editor"
    display_key = "measurement_pair_display"
    is_computed = False

    def validate(self, value: dict[str, Any]) -> ValidationResult:
        """Validate a measurement pair value."""
        if value is None:
            return ValidationResult.valid()

        if not isinstance(value, dict):
            return ValidationResult.invalid(
                [f"Expected dict, got {type(value).__name__}"]
            )

        if value.get("_unknown"):
            return ValidationResult.valid()

        field_errors: dict[str, list[str]] = {}

        # Validate first measurement
        first = value.get("first")
        if first is not None:
            if not isinstance(first, dict):
                field_errors["first"] = [f"Expected dict, got {type(first).__name__}"]
            else:
                first_errors = self._validate_measurement(first, "first")
                if first_errors:
                    field_errors["first"] = first_errors

        # Validate second measurement
        second = value.get("second")
        if second is not None:
            if not isinstance(second, dict):
                field_errors["second"] = [f"Expected dict, got {type(second).__name__}"]
            else:
                second_errors = self._validate_measurement(second, "second")
                if second_errors:
                    field_errors["second"] = second_errors

        # Validate evidence_window
        evidence_window = value.get("evidence_window")
        if evidence_window is not None and not isinstance(evidence_window, str):
            field_errors["evidence_window"] = [
                f"evidence_window must be a string, got {type(evidence_window).__name__}"
            ]

        if field_errors:
            all_errors = []
            for _field, errs in field_errors.items():
                all_errors.extend(errs)
            return ValidationResult.invalid(all_errors, field_errors)

        return ValidationResult.valid()

    def _validate_measurement(self, m: dict[str, Any], field_name: str) -> list[str]:
        """Validate a single measurement within the pair."""
        errors: list[str] = []

        raw_value = m.get("value")
        if raw_value is not None:
            _, err = _parse_decimal(raw_value)
            if err:
                errors.append(f"{field_name}.value: {err}")

        unit_err = _validate_unit(m.get("unit"))
        if unit_err and raw_value is not None:
            errors.append(f"{field_name}.unit: {unit_err}")

        return errors

    def normalize(self, value: dict[str, Any]) -> dict[str, Any]:
        """Normalize a measurement pair value."""
        if value is None:
            return self.empty_value() or {}

        if not isinstance(value, dict):
            return value

        if value.get("_unknown"):
            return {"_unknown": True}

        result: dict[str, Any] = {}

        # Normalize first
        first = value.get("first")
        if first is not None and isinstance(first, dict):
            result["first"] = self._normalize_measurement(first)
        else:
            result["first"] = {"value": None, "unit": None}

        # Normalize second
        second = value.get("second")
        if second is not None and isinstance(second, dict):
            result["second"] = self._normalize_measurement(second)
        else:
            result["second"] = {"value": None, "unit": None}

        # Normalize evidence_window
        evidence_window = value.get("evidence_window")
        if evidence_window is not None:
            result["evidence_window"] = str(evidence_window).strip()

        return result

    def _normalize_measurement(self, m: dict[str, Any]) -> dict[str, Any]:
        """Normalize a single measurement."""
        result: dict[str, Any] = {}

        raw_value = m.get("value")
        if raw_value is not None:
            decimal_val, _ = _parse_decimal(raw_value)
            result["value"] = _normalize_decimal(decimal_val)
        else:
            result["value"] = None

        unit = m.get("unit")
        result["unit"] = str(unit).strip() if unit else None

        return result

    def parse_form(self, form_data: dict[str, Any]) -> ParseResult:
        """Parse HTML form data into measurement pair value."""
        if not form_data:
            return ParseResult.success(self.empty_value() or {})

        result: dict[str, Any] = {}

        # Parse first measurement
        first_value = form_data.get("first_value", "")
        first_unit = form_data.get("first_unit", "")
        first, err = self._parse_measurement_from_form(first_value, first_unit, "first")
        if err:
            return ParseResult.failure([err], form_data)
        result["first"] = first

        # Parse second measurement
        second_value = form_data.get("second_value", "")
        second_unit = form_data.get("second_unit", "")
        second, err = self._parse_measurement_from_form(second_value, second_unit, "second")
        if err:
            return ParseResult.failure([err], form_data)
        result["second"] = second

        # Parse evidence_window
        evidence_window = form_data.get("evidence_window", "")
        if isinstance(evidence_window, str):
            evidence_window = evidence_window.strip()
        if evidence_window:
            result["evidence_window"] = evidence_window

        return ParseResult.success(result, raw_input=form_data)

    def _parse_measurement_from_form(
        self, value: Any, unit: Any, field_name: str
    ) -> tuple[dict[str, Any], str | None]:
        """Parse a single measurement from form fields."""
        result: dict[str, Any] = {}

        if isinstance(value, str):
            value = value.strip()

        if value:
            decimal_val, err = _parse_decimal(value)
            if err:
                return {}, f"{field_name}.value: {err}"
            result["value"] = _normalize_decimal(decimal_val)
        else:
            result["value"] = None

        if isinstance(unit, str):
            unit = unit.strip()
        result["unit"] = unit if unit else None

        return result, None

    def parse_workbook(
        self, cell_value: Any, context: dict[str, Any] | None = None
    ) -> ParseResult:
        """Parse workbook cell value into measurement pair."""
        if cell_value is None or (isinstance(cell_value, str) and not cell_value.strip()):
            return ParseResult.success(self.empty_value() or {})

        context = context or {}

        # If context provides structured data, use it
        if isinstance(cell_value, dict):
            return ParseResult.success(self.normalize(cell_value), raw_input=cell_value)

        # Try to parse "value1 unit1 / value2 unit2" format
        if isinstance(cell_value, str):
            cell_value = cell_value.strip()

            # Try to split on common separators
            for sep in ["/", "|", ";"]:
                if sep in cell_value:
                    parts = cell_value.split(sep, 1)
                    if len(parts) == 2:
                        first_result = self._parse_measurement_string(parts[0].strip())
                        second_result = self._parse_measurement_string(parts[1].strip())

                        if first_result and second_result:
                            result = {
                                "first": first_result,
                                "second": second_result,
                            }
                            if context.get("evidence_window"):
                                result["evidence_window"] = context["evidence_window"]
                            return ParseResult.success(result, raw_input=cell_value)

            return ParseResult.failure(
                [f"Cannot parse measurement pair from: {cell_value}"],
                cell_value
            )

        return ParseResult.failure(
            [f"Unexpected cell value type: {type(cell_value).__name__}"],
            cell_value
        )

    def _parse_measurement_string(self, s: str) -> dict[str, Any] | None:
        """Parse a measurement from a string like '150 ms'."""
        match = re.match(r"^(-?[\d.]+)\s*(\S+)?$", s)
        if match:
            value_str, unit = match.groups()
            decimal_val, err = _parse_decimal(value_str)
            if err:
                return None
            return {
                "value": _normalize_decimal(decimal_val),
                "unit": unit,
            }
        return None

    def empty_value(self) -> dict[str, Any] | None:
        """Return empty measurement pair value."""
        return {
            "first": {"value": None, "unit": None},
            "second": {"value": None, "unit": None},
        }

    def unknown_value(self) -> dict[str, Any] | None:
        """Return explicit unknown value."""
        return {"_unknown": True}


class MeasurementSetType(ResponseTypeBase):
    """
    Repeatable metrics with unique metric/scope combinations.

    Schema: {
        measurements: [
            {metric: str, value: decimal, unit: str, qualifier?: str, scope?: str}
        ]
    }

    Examples:
        {
            "measurements": [
                {"metric": "cpu_usage", "value": "75", "unit": "%", "scope": "prod"},
                {"metric": "memory_usage", "value": "8", "unit": "GB", "scope": "prod"}
            ]
        }
    """

    code = ResponseTypeCodes.MEASUREMENT_SET
    schema_version = "1.0"
    editor_key = "measurement_set_editor"
    display_key = "measurement_set_display"
    is_computed = False

    def validate(self, value: dict[str, Any]) -> ValidationResult:
        """Validate a measurement set value."""
        if value is None:
            return ValidationResult.valid()

        if not isinstance(value, dict):
            return ValidationResult.invalid(
                [f"Expected dict, got {type(value).__name__}"]
            )

        if value.get("_unknown"):
            return ValidationResult.valid()

        measurements = value.get("measurements")
        if measurements is None:
            return ValidationResult.valid()

        if not isinstance(measurements, list):
            return ValidationResult.invalid(
                [f"measurements must be a list, got {type(measurements).__name__}"],
                {"measurements": [f"Expected list, got {type(measurements).__name__}"]}
            )

        errors: list[str] = []
        field_errors: dict[str, list[str]] = {}
        seen_keys: set[tuple[str, str | None]] = set()

        for i, m in enumerate(measurements):
            if not isinstance(m, dict):
                errors.append(f"measurements[{i}]: Expected dict, got {type(m).__name__}")
                continue

            # Validate metric (required)
            metric = m.get("metric")
            if not metric:
                errors.append(f"measurements[{i}].metric: Required")
            elif not isinstance(metric, str):
                errors.append(f"measurements[{i}].metric: Must be a string")

            # Validate value
            raw_value = m.get("value")
            if raw_value is not None:
                _, err = _parse_decimal(raw_value)
                if err:
                    errors.append(f"measurements[{i}].value: {err}")

            # Validate unit
            unit_err = _validate_unit(m.get("unit"))
            if unit_err and raw_value is not None:
                errors.append(f"measurements[{i}].unit: {unit_err}")

            # Validate qualifier
            qualifier_err = _validate_qualifier(m.get("qualifier"))
            if qualifier_err:
                errors.append(f"measurements[{i}].qualifier: {qualifier_err}")

            # Validate scope
            scope = m.get("scope")
            if scope is not None and not isinstance(scope, str):
                errors.append(f"measurements[{i}].scope: Must be a string")

            # Check for duplicate metric/scope
            if isinstance(metric, str):
                scope_val = scope if isinstance(scope, str) else None
                key = (metric.lower(), scope_val.lower() if scope_val else None)
                if key in seen_keys:
                    errors.append(
                        f"measurements[{i}]: Duplicate metric/scope combination: "
                        f"{metric}/{scope_val or '(no scope)'}"
                    )
                seen_keys.add(key)

        if errors:
            return ValidationResult.invalid(errors, field_errors)

        return ValidationResult.valid()

    def normalize(self, value: dict[str, Any]) -> dict[str, Any]:
        """Normalize a measurement set value."""
        if value is None:
            return self.empty_value() or {}

        if not isinstance(value, dict):
            return value

        if value.get("_unknown"):
            return {"_unknown": True}

        measurements = value.get("measurements")
        if not isinstance(measurements, list):
            return {"measurements": []}

        normalized_measurements: list[dict[str, Any]] = []
        for m in measurements:
            if not isinstance(m, dict):
                continue

            normalized_m: dict[str, Any] = {}

            # Normalize metric
            metric = m.get("metric")
            if metric is not None:
                normalized_m["metric"] = str(metric).strip()

            # Normalize value
            raw_value = m.get("value")
            if raw_value is not None:
                decimal_val, _ = _parse_decimal(raw_value)
                normalized_m["value"] = _normalize_decimal(decimal_val)
            else:
                normalized_m["value"] = None

            # Normalize unit
            unit = m.get("unit")
            normalized_m["unit"] = str(unit).strip() if unit else None

            # Normalize qualifier
            qualifier = m.get("qualifier")
            if qualifier is not None:
                normalized_m["qualifier"] = str(qualifier).strip().lower()

            # Normalize scope
            scope = m.get("scope")
            if scope is not None:
                normalized_m["scope"] = str(scope).strip()

            normalized_measurements.append(normalized_m)

        # Sort by metric, then scope for canonical ordering
        normalized_measurements.sort(
            key=lambda x: (x.get("metric", ""), x.get("scope") or "")
        )

        return {"measurements": normalized_measurements}

    def parse_form(self, form_data: dict[str, Any]) -> ParseResult:
        """Parse HTML form data into measurement set value."""
        if not form_data:
            return ParseResult.success(self.empty_value() or {})

        # Form data may come as arrays of values
        metrics = form_data.get("metrics", [])
        values = form_data.get("values", [])
        units = form_data.get("units", [])
        qualifiers = form_data.get("qualifiers", [])
        scopes = form_data.get("scopes", [])

        # Ensure all are lists
        if not isinstance(metrics, list):
            metrics = [metrics] if metrics else []
        if not isinstance(values, list):
            values = [values] if values else []
        if not isinstance(units, list):
            units = [units] if units else []
        if not isinstance(qualifiers, list):
            qualifiers = [qualifiers] if qualifiers else []
        if not isinstance(scopes, list):
            scopes = [scopes] if scopes else []

        measurements: list[dict[str, Any]] = []

        for i in range(len(metrics)):
            metric = metrics[i] if i < len(metrics) else ""
            if isinstance(metric, str):
                metric = metric.strip()
            if not metric:
                continue

            m: dict[str, Any] = {"metric": metric}

            # Parse value
            value = values[i] if i < len(values) else ""
            if isinstance(value, str):
                value = value.strip()
            if value:
                decimal_val, err = _parse_decimal(value)
                if err:
                    return ParseResult.failure(
                        [f"measurements[{i}].value: {err}"],
                        form_data
                    )
                m["value"] = _normalize_decimal(decimal_val)
            else:
                m["value"] = None

            # Parse unit
            unit = units[i] if i < len(units) else ""
            if isinstance(unit, str):
                unit = unit.strip()
            m["unit"] = unit if unit else None

            # Parse qualifier
            qualifier = qualifiers[i] if i < len(qualifiers) else ""
            if isinstance(qualifier, str):
                qualifier = qualifier.strip().lower()
            if qualifier:
                m["qualifier"] = qualifier

            # Parse scope
            scope = scopes[i] if i < len(scopes) else ""
            if isinstance(scope, str):
                scope = scope.strip()
            if scope:
                m["scope"] = scope

            measurements.append(m)

        return ParseResult.success({"measurements": measurements}, raw_input=form_data)

    def parse_workbook(
        self, cell_value: Any, context: dict[str, Any] | None = None
    ) -> ParseResult:
        """Parse workbook cell value into measurement set."""
        if cell_value is None or (isinstance(cell_value, str) and not cell_value.strip()):
            return ParseResult.success(self.empty_value() or {})

        context = context or {}

        # If already a dict with measurements, normalize it
        if isinstance(cell_value, dict):
            return ParseResult.success(self.normalize(cell_value), raw_input=cell_value)

        # If a list, treat as measurements array
        if isinstance(cell_value, list):
            return ParseResult.success(
                self.normalize({"measurements": cell_value}),
                raw_input=cell_value
            )

        # Try to parse from string (e.g., "cpu:75%,memory:8GB")
        if isinstance(cell_value, str):
            cell_value = cell_value.strip()
            measurements: list[dict[str, Any]] = []

            # Split on comma or semicolon
            parts = re.split(r"[,;]", cell_value)
            for part in parts:
                part = part.strip()
                if not part:
                    continue

                # Try "metric:value unit" or "metric=value unit" format
                match = re.match(r"^(\w+)\s*[:=]\s*(-?[\d.]+)\s*(\S+)?$", part)
                if match:
                    metric, value_str, unit = match.groups()
                    decimal_val, err = _parse_decimal(value_str)
                    if err:
                        return ParseResult.failure([err], cell_value)
                    measurements.append({
                        "metric": metric,
                        "value": _normalize_decimal(decimal_val),
                        "unit": unit,
                    })
                else:
                    return ParseResult.failure(
                        [f"Cannot parse measurement from: {part}"],
                        cell_value
                    )

            if measurements:
                return ParseResult.success({"measurements": measurements}, raw_input=cell_value)

            return ParseResult.failure(
                [f"Cannot parse measurement set from: {cell_value}"],
                cell_value
            )

        return ParseResult.failure(
            [f"Unexpected cell value type: {type(cell_value).__name__}"],
            cell_value
        )

    def empty_value(self) -> dict[str, Any] | None:
        """Return empty measurement set value."""
        return {"measurements": []}

    def unknown_value(self) -> dict[str, Any] | None:
        """Return explicit unknown value."""
        return {"_unknown": True}


class MeasurementContextType(ResponseTypeBase):
    """
    Structured metrics with evidence window and source context.

    Schema: {
        measurements: [{metric: str, value: decimal, unit: str, qualifier?: str}],
        window: str,
        source_context: str,
        missing_reason?: str,
        fallback_rule?: str
    }

    Examples:
        {
            "measurements": [
                {"metric": "latency_p99", "value": "150", "unit": "ms"}
            ],
            "window": "2024-01-01 to 2024-01-31",
            "source_context": "Production APM dashboard",
            "fallback_rule": "Use design estimates if no production data"
        }
    """

    code = ResponseTypeCodes.MEASUREMENT_CONTEXT
    schema_version = "1.0"
    editor_key = "measurement_context_editor"
    display_key = "measurement_context_display"
    is_computed = False

    def validate(self, value: dict[str, Any]) -> ValidationResult:
        """Validate a measurement context value."""
        if value is None:
            return ValidationResult.valid()

        if not isinstance(value, dict):
            return ValidationResult.invalid(
                [f"Expected dict, got {type(value).__name__}"]
            )

        if value.get("_unknown"):
            return ValidationResult.valid()

        errors: list[str] = []
        field_errors: dict[str, list[str]] = {}

        # Validate measurements array
        measurements = value.get("measurements")
        if measurements is not None:
            if not isinstance(measurements, list):
                field_errors["measurements"] = [
                    f"Expected list, got {type(measurements).__name__}"
                ]
            else:
                for i, m in enumerate(measurements):
                    if not isinstance(m, dict):
                        errors.append(
                            f"measurements[{i}]: Expected dict, got {type(m).__name__}"
                        )
                        continue

                    # Validate metric
                    metric = m.get("metric")
                    if not metric:
                        errors.append(f"measurements[{i}].metric: Required")
                    elif not isinstance(metric, str):
                        errors.append(f"measurements[{i}].metric: Must be a string")

                    # Validate value
                    raw_value = m.get("value")
                    if raw_value is not None:
                        _, err = _parse_decimal(raw_value)
                        if err:
                            errors.append(f"measurements[{i}].value: {err}")

                    # Validate unit
                    unit_err = _validate_unit(m.get("unit"))
                    if unit_err and raw_value is not None:
                        errors.append(f"measurements[{i}].unit: {unit_err}")

                    # Validate qualifier
                    qualifier_err = _validate_qualifier(m.get("qualifier"))
                    if qualifier_err:
                        errors.append(f"measurements[{i}].qualifier: {qualifier_err}")

        # Validate window (required if measurements present)
        window = value.get("window")
        if measurements and not window:
            errors.append("window: Required when measurements are provided")
        elif window is not None and not isinstance(window, str):
            field_errors["window"] = [f"Must be a string, got {type(window).__name__}"]

        # Validate source_context (required if measurements present)
        source_context = value.get("source_context")
        if measurements and not source_context:
            errors.append("source_context: Required when measurements are provided")
        elif source_context is not None and not isinstance(source_context, str):
            field_errors["source_context"] = [
                f"Must be a string, got {type(source_context).__name__}"
            ]

        # Validate missing_reason
        missing_reason = value.get("missing_reason")
        if missing_reason is not None and not isinstance(missing_reason, str):
            field_errors["missing_reason"] = [
                f"Must be a string, got {type(missing_reason).__name__}"
            ]

        # Validate fallback_rule
        fallback_rule = value.get("fallback_rule")
        if fallback_rule is not None and not isinstance(fallback_rule, str):
            field_errors["fallback_rule"] = [
                f"Must be a string, got {type(fallback_rule).__name__}"
            ]

        if errors or field_errors:
            all_errors = errors[:]
            for _field, errs in field_errors.items():
                all_errors.extend(errs)
            return ValidationResult.invalid(all_errors, field_errors)

        return ValidationResult.valid()

    def normalize(self, value: dict[str, Any]) -> dict[str, Any]:
        """Normalize a measurement context value."""
        if value is None:
            return self.empty_value() or {}

        if not isinstance(value, dict):
            return value

        if value.get("_unknown"):
            return {"_unknown": True}

        result: dict[str, Any] = {}

        # Normalize measurements
        measurements = value.get("measurements")
        if isinstance(measurements, list):
            normalized_measurements: list[dict[str, Any]] = []
            for m in measurements:
                if not isinstance(m, dict):
                    continue

                normalized_m: dict[str, Any] = {}

                metric = m.get("metric")
                if metric is not None:
                    normalized_m["metric"] = str(metric).strip()

                raw_value = m.get("value")
                if raw_value is not None:
                    decimal_val, _ = _parse_decimal(raw_value)
                    normalized_m["value"] = _normalize_decimal(decimal_val)
                else:
                    normalized_m["value"] = None

                unit = m.get("unit")
                normalized_m["unit"] = str(unit).strip() if unit else None

                qualifier = m.get("qualifier")
                if qualifier is not None:
                    normalized_m["qualifier"] = str(qualifier).strip().lower()

                normalized_measurements.append(normalized_m)

            result["measurements"] = normalized_measurements
        else:
            result["measurements"] = []

        # Normalize window
        window = value.get("window")
        if window is not None:
            result["window"] = str(window).strip()
        else:
            result["window"] = None

        # Normalize source_context
        source_context = value.get("source_context")
        if source_context is not None:
            result["source_context"] = str(source_context).strip()
        else:
            result["source_context"] = None

        # Normalize missing_reason
        missing_reason = value.get("missing_reason")
        if missing_reason is not None:
            result["missing_reason"] = str(missing_reason).strip()

        # Normalize fallback_rule
        fallback_rule = value.get("fallback_rule")
        if fallback_rule is not None:
            result["fallback_rule"] = str(fallback_rule).strip()

        return result

    def parse_form(self, form_data: dict[str, Any]) -> ParseResult:
        """Parse HTML form data into measurement context value."""
        if not form_data:
            return ParseResult.success(self.empty_value() or {})

        result: dict[str, Any] = {}

        # Parse measurements array (similar to MeasurementSetType)
        metrics = form_data.get("metrics", [])
        values = form_data.get("values", [])
        units = form_data.get("units", [])
        qualifiers = form_data.get("qualifiers", [])

        if not isinstance(metrics, list):
            metrics = [metrics] if metrics else []
        if not isinstance(values, list):
            values = [values] if values else []
        if not isinstance(units, list):
            units = [units] if units else []
        if not isinstance(qualifiers, list):
            qualifiers = [qualifiers] if qualifiers else []

        measurements: list[dict[str, Any]] = []

        for i in range(len(metrics)):
            metric = metrics[i] if i < len(metrics) else ""
            if isinstance(metric, str):
                metric = metric.strip()
            if not metric:
                continue

            m: dict[str, Any] = {"metric": metric}

            value = values[i] if i < len(values) else ""
            if isinstance(value, str):
                value = value.strip()
            if value:
                decimal_val, err = _parse_decimal(value)
                if err:
                    return ParseResult.failure(
                        [f"measurements[{i}].value: {err}"],
                        form_data
                    )
                m["value"] = _normalize_decimal(decimal_val)
            else:
                m["value"] = None

            unit = units[i] if i < len(units) else ""
            if isinstance(unit, str):
                unit = unit.strip()
            m["unit"] = unit if unit else None

            qualifier = qualifiers[i] if i < len(qualifiers) else ""
            if isinstance(qualifier, str):
                qualifier = qualifier.strip().lower()
            if qualifier:
                m["qualifier"] = qualifier

            measurements.append(m)

        result["measurements"] = measurements

        # Parse window
        window = form_data.get("window", "")
        if isinstance(window, str):
            window = window.strip()
        result["window"] = window if window else None

        # Parse source_context
        source_context = form_data.get("source_context", "")
        if isinstance(source_context, str):
            source_context = source_context.strip()
        result["source_context"] = source_context if source_context else None

        # Parse missing_reason
        missing_reason = form_data.get("missing_reason", "")
        if isinstance(missing_reason, str):
            missing_reason = missing_reason.strip()
        if missing_reason:
            result["missing_reason"] = missing_reason

        # Parse fallback_rule
        fallback_rule = form_data.get("fallback_rule", "")
        if isinstance(fallback_rule, str):
            fallback_rule = fallback_rule.strip()
        if fallback_rule:
            result["fallback_rule"] = fallback_rule

        return ParseResult.success(result, raw_input=form_data)

    def parse_workbook(
        self, cell_value: Any, context: dict[str, Any] | None = None
    ) -> ParseResult:
        """Parse workbook cell value into measurement context."""
        if cell_value is None or (isinstance(cell_value, str) and not cell_value.strip()):
            return ParseResult.success(self.empty_value() or {})

        context = context or {}

        # If already a dict, normalize it
        if isinstance(cell_value, dict):
            # Merge context values if not present in cell_value
            merged = dict(cell_value)
            if "window" not in merged and "window" in context:
                merged["window"] = context["window"]
            if "source_context" not in merged and "source_context" in context:
                merged["source_context"] = context["source_context"]
            return ParseResult.success(self.normalize(merged), raw_input=cell_value)

        # For string values, we need context to provide window and source_context
        if isinstance(cell_value, str):
            cell_value = cell_value.strip()

            # Try to parse measurements from string
            measurements: list[dict[str, Any]] = []
            parts = re.split(r"[,;]", cell_value)

            for part in parts:
                part = part.strip()
                if not part:
                    continue

                match = re.match(r"^(\w+)\s*[:=]\s*(-?[\d.]+)\s*(\S+)?$", part)
                if match:
                    metric, value_str, unit = match.groups()
                    decimal_val, err = _parse_decimal(value_str)
                    if err:
                        return ParseResult.failure([err], cell_value)
                    measurements.append({
                        "metric": metric,
                        "value": _normalize_decimal(decimal_val),
                        "unit": unit,
                    })
                else:
                    return ParseResult.failure(
                        [f"Cannot parse measurement from: {part}"],
                        cell_value
                    )

            if measurements:
                result = {
                    "measurements": measurements,
                    "window": context.get("window"),
                    "source_context": context.get("source_context"),
                }
                if context.get("missing_reason"):
                    result["missing_reason"] = context["missing_reason"]
                if context.get("fallback_rule"):
                    result["fallback_rule"] = context["fallback_rule"]
                return ParseResult.success(result, raw_input=cell_value)

            return ParseResult.failure(
                [f"Cannot parse measurement context from: {cell_value}"],
                cell_value
            )

        return ParseResult.failure(
            [f"Unexpected cell value type: {type(cell_value).__name__}"],
            cell_value
        )

    def empty_value(self) -> dict[str, Any] | None:
        """Return empty measurement context value."""
        return {
            "measurements": [],
            "window": None,
            "source_context": None,
        }

    def unknown_value(self) -> dict[str, Any] | None:
        """Return explicit unknown value."""
        return {"_unknown": True}
