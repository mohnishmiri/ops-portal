"""Style helpers and registry loading for HAF-generated draw.io cells."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

_STYLE_REGISTRY_PATH = (
    Path(__file__).resolve().parent / "config" / "haf_styles" / "interface_styles.json"
)


def load_interface_styles() -> dict[str, dict[str, str]]:
    """Load interface style mappings keyed by category."""
    raw = json.loads(_STYLE_REGISTRY_PATH.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("interface_styles.json must be a JSON object")
    parsed: dict[str, dict[str, str]] = {}
    for key, value in raw.items():
        if not isinstance(key, str) or not isinstance(value, dict):
            raise ValueError("interface style entries must be object mappings")
        style = value.get("style")
        if not isinstance(style, str) or not style:
            raise ValueError(f"style for category {key!r} must be a non-empty string")
        parsed[key] = {str(k): str(v) for k, v in value.items()}
    return parsed


def update_style_by_key(style_str: str, key: str, value: str) -> str:
    """Update one draw.io style key, appending it when not present."""
    pattern = rf"{re.escape(key)}=([^;]+)"
    if re.search(pattern, style_str) is None:
        return f"{style_str}{key}={value};"
    return re.sub(pattern, f"{key}={value}", style_str)


def customize(node_template: dict[str, str], style: dict[str, str] | None = None) -> None:
    """Apply style overrides to a node template dict in place."""
    if not style:
        return
    for key, value in style.items():
        node_template["style"] = update_style_by_key(
            style_str=node_template["style"],
            key=key,
            value=str(value),
        )


def style_str_from_dict(base_style: str | None, format_dict: dict[str, Any]) -> str:
    """Build a style string from a dict, preserving draw.io `;` delimiters."""
    style_str = ""
    if base_style:
        style_str += f"{base_style};"
    style_str += ";".join([f"{k}={v}" for k, v in format_dict.items() if v is not None])
    if style_str and not style_str.endswith(";"):
        style_str += ";"
    return style_str
