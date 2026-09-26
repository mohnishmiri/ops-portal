"""
Fact value normalization — ported from the validated `_data/spike` design.

This is a direct port of the POC's ``resolve.py::normalize_value`` so that
raw evidence values are normalized identically whether the evidence source
is a file (POC) or a database row (production). Do not add data types here
without a corresponding POC precedent or an explicit review decision.
"""

from __future__ import annotations

import ipaddress
import re
from typing import Any

_TRUE_VALUES = {"true", "yes", "y", "1", "enabled"}
_FALSE_VALUES = {"false", "no", "n", "0", "disabled"}


def normalize_value(value: Any, data_type: str) -> tuple[Any, str | None]:
    """
    Normalize a raw evidence value according to its declared data type.

    Returns a ``(value, inferred_unit)`` tuple. Mirrors the POC exactly so
    the same input produces the same normalized output in both pipelines.
    """
    text = re.sub(r"\s+", " ", str(value)).strip()
    lowered = text.casefold()
    if data_type == "boolean":
        if lowered in _TRUE_VALUES:
            return True, None
        if lowered in _FALSE_VALUES:
            return False, None
        if lowered in {"na", "n/a", "not applicable"}:
            return None, None
        return text, None
    if data_type == "version":
        matches = re.findall(r"\d+(?:\.\d+)+", text)
        return (matches[-1] if matches else text), None
    if data_type == "port_set":
        ports = sorted(
            {
                int(value)
                for value in re.findall(r"(?<!\d)(\d{1,5})(?!\d)", text)
                if 0 < int(value) <= 65535
            }
        )
        return ports, None
    if data_type == "string_set":
        return sorted({part.strip() for part in re.split(r"[,;]", text) if part.strip()}), None
    if data_type == "clli":
        return text.upper(), None
    if data_type == "acronym":
        return re.sub(r"[^A-Za-z0-9_-]", "", text).upper(), None
    if data_type == "region":
        return text.lower(), None
    if data_type == "cidr":
        try:
            return str(ipaddress.ip_network(text, strict=False)), None
        except ValueError:
            return text, None
    if data_type == "iops":
        number = re.search(r"[\d,]+(?:\.\d+)?", text)
        return (float(number.group(0).replace(",", "")) if number else text), None
    if data_type == "identifier":
        return text[:-2] if re.fullmatch(r"\d+\.0", text) else text, None
    return text, None
