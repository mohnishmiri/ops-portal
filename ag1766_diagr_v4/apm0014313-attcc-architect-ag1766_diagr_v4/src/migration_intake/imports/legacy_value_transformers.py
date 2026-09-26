"""
Legacy intake workbook value transformers.

Deterministic parsers for converting legacy response values to canonical
response schema format.
"""
from __future__ import annotations

from typing import Any


class LegacyValueTransformError(ValueError):
    """Raised when a value cannot be transformed."""


def parse_text(raw_value: Any) -> dict[str, Any]:
    """
    Parse a simple text response.

    Returns:
        {"value": str}
    """
    if raw_value is None or str(raw_value).strip() == "":
        return {"value": None}

    return {"value": str(raw_value).strip()}


def parse_long_text(raw_value: Any) -> dict[str, Any]:
    """
    Parse a long text response.

    Returns:
        {"value": str}
    """
    return parse_text(raw_value)


def parse_text_pair(raw_value: Any) -> dict[str, Any]:
    """
    Parse a pipe-separated text pair (e.g., "Name|Acronym").

    Returns:
        {"first": str, "second": str}
    """
    if raw_value is None or str(raw_value).strip() == "":
        return {"first": None, "second": None}

    value_str = str(raw_value).strip()

    if "|" in value_str:
        parts = value_str.split("|", 1)
        return {
            "first": parts[0].strip() if parts[0] else None,
            "second": parts[1].strip() if len(parts) > 1 and parts[1] else None,
        }

    # No pipe separator - treat as first value only
    return {"first": value_str, "second": None}


def parse_single_select(raw_value: Any) -> dict[str, Any]:
    """
    Parse a single-select response.

    Returns:
        {"value": str}
    """
    if raw_value is None or str(raw_value).strip() == "":
        return {"value": None}

    return {"value": str(raw_value).strip().upper()}


def parse_multi_select(raw_value: Any) -> dict[str, Any]:
    """
    Parse a pipe-separated multi-select response (e.g., "TOPOLOGY|ADS").

    Returns:
        {"values": [str, ...]}
    """
    if raw_value is None or str(raw_value).strip() == "":
        return {"values": []}

    value_str = str(raw_value).strip()

    if "|" in value_str:
        values = [v.strip().upper() for v in value_str.split("|") if v.strip()]
        return {"values": values}

    # Single value
    return {"values": [value_str.upper()]}


def parse_boolean(raw_value: Any) -> dict[str, Any]:
    """
    Parse a boolean response (YES/NO/UNKNOWN).

    Returns:
        {"value": "YES" | "NO" | "UNKNOWN" | None}
    """
    if raw_value is None or str(raw_value).strip() == "":
        return {"value": None}

    value_str = str(raw_value).strip().upper()

    # Normalize common variations
    if value_str in ("YES", "Y", "TRUE", "1"):
        return {"value": "YES"}
    elif value_str in ("NO", "N", "FALSE", "0"):
        return {"value": "NO"}
    elif value_str in ("UNKNOWN", "UNK", "?", "N/A", "NA"):
        return {"value": "UNKNOWN"}

    # Unknown format - preserve as-is but flag
    return {"value": value_str}


def parse_controlled_pair(raw_value: Any) -> dict[str, Any]:
    """
    Parse a controlled pair (e.g., "HIGH|TIER1").

    Returns:
        {"first": str, "second": str}
    """
    return parse_text_pair(raw_value)


def parse_people_list(raw_value: Any) -> dict[str, Any]:
    """
    Parse a people list (names, emails, etc.).

    Returns:
        {"people": [{"name": str, "role_code": "UNKNOWN"}, ...]}
    """
    if raw_value is None or str(raw_value).strip() == "":
        return {"people": []}

    value_str = str(raw_value).strip()

    # Try common separators
    for separator in ["|", ";", ",", "\n"]:
        if separator in value_str:
            names = [p.strip() for p in value_str.split(separator) if p.strip()]
            return {
                "people": [
                    {"name": name, "role_code": "UNKNOWN"}
                    for name in names
                ]
            }

    # Single person
    return {"people": [{"name": value_str, "role_code": "UNKNOWN"}]}


def parse_duration(raw_value: Any) -> dict[str, Any]:
    """
    Parse a duration value (e.g., "4 hours", "24h", "1 day").

    Returns:
        {"value": str, "normalized_hours": float | None}
    """
    if raw_value is None or str(raw_value).strip() == "":
        return {"value": None, "normalized_hours": None}

    value_str = str(raw_value).strip().lower()

    # Try to extract numeric value and unit
    import re

    match = re.match(
        r"(?P<qualifier><=|>=)?\s*"
        r"(?P<number>\d+(?:\.\d+)?)\s*"
        r"(?P<unit>hour|hr|h|day|d|minute|min|m)?s?",
        value_str,
    )

    if match:
        number = float(match.group("number"))
        unit = match.group("unit") or "hour"

        # Normalize to hours
        if unit in ("hour", "hr", "h"):
            normalized_hours = number
        elif unit in ("day", "d"):
            normalized_hours = number * 24
        elif unit in ("minute", "min", "m"):
            normalized_hours = number / 60
        else:
            normalized_hours = number  # Assume hours

        result = {
            "value": str(raw_value).strip(),
            "normalized_hours": normalized_hours,
        }
        if match.group("qualifier"):
            result["qualifier"] = (
                "maximum" if match.group("qualifier") == "<=" else "minimum"
            )
        return result

    # Could not parse - preserve original
    return {
        "value": str(raw_value).strip(),
        "normalized_hours": None,
    }


# Registry of transformer functions
TRANSFORMERS: dict[str, Any] = {
    "parse_text": parse_text,
    "parse_long_text": parse_long_text,
    "parse_text_pair": parse_text_pair,
    "parse_single_select": parse_single_select,
    "parse_multi_select": parse_multi_select,
    "parse_boolean": parse_boolean,
    "parse_controlled_pair": parse_controlled_pair,
    "parse_people_list": parse_people_list,
    "parse_duration": parse_duration,
}


def transform_value(transformer_name: str, raw_value: Any) -> dict[str, Any]:
    """
    Transform a raw value using the named transformer.

    Args:
        transformer_name: Name of the transformer function
        raw_value: Raw value from the workbook

    Returns:
        Transformed value dict

    Raises:
        LegacyValueTransformError: If transformer not found or transformation fails
    """
    if transformer_name not in TRANSFORMERS:
        raise LegacyValueTransformError(f"Unknown transformer: {transformer_name}")

    try:
        return TRANSFORMERS[transformer_name](raw_value)
    except Exception as e:
        raise LegacyValueTransformError(
            f"Failed to transform value with {transformer_name}: {e}"
        ) from e
