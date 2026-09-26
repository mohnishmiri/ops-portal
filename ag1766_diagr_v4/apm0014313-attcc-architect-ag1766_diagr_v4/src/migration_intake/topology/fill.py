"""
Topology diagram filler — ported from the validated `_data/spike` design.

This is a structural port of the POC's ``fill.py::bind_slots`` /
``fill_drawio``: cells are matched by ordinal position and visible label
(never by cell ID), the same structural snapshot is taken before and after
mutation to guarantee no non-bound cell or layout attribute changed, and
only cell ``value`` text is ever mutated.

One documented deviation from the POC: the POC's ``bind_slots`` always
raises when a configured slot has zero matches, because its slots are
authored against one specific template diagram. Production base diagrams
are user-uploaded and may legitimately omit some configured slots, so a
slot's ``required`` flag (default ``False``) controls whether a zero-match
result is a hard failure (``required: true``) or a reported warning. Any
non-zero mismatch (wrong count, double-binding) is always a hard failure
in both implementations, because that signals an ambiguous binding rather
than an absent one.

Design rules:
- Only accepts uncompressed draw.io XML.
- Binds cells by semantic label, never by ID.
- Performs value-only mutation; structure is verified unchanged.
- Escapes all evidence text.
"""

from __future__ import annotations

import copy
import html
import io
import json
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Mapping

# Versioned, editable binding config; see topology/config/slot_bindings.json.
_CONFIG_PATH = Path(__file__).resolve().parent / "config" / "slot_bindings.json"


class DiagramError(ValueError):
    """Raised for structurally unsafe or ambiguous diagram mutations."""


@dataclass
class SlotBinding:
    """A slot binding configuration for a diagram cell (POC ``slots.yaml`` shape)."""

    slot_name: str
    find: dict[str, Any]  # {"label_startswith"|"label_contains"|"label_contains_all": ...}
    template: str
    mode: str = "replace_label"
    preserve_regex: str | None = None
    expected_matches: int = 1
    required: bool = False


@dataclass
class FillResult:
    """Result of filling a diagram."""

    success: bool
    filled_xml: bytes | None = None
    mutations: list[dict[str, Any]] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


_FALLBACK_BINDINGS: list[SlotBinding] = [
    SlotBinding(
        slot_name="app_name",
        find={"label_contains": "Application Name"},
        template="Application Name: {app_name}",
    ),
    SlotBinding(
        slot_name="app_acronym",
        find={"label_contains": "App Acronym"},
        template="App Acronym: {app_acronym}",
    ),
    SlotBinding(
        slot_name="correlation_id",
        find={"label_contains": "Correlation ID"},
        template="Correlation ID: {correlation_id}",
    ),
    SlotBinding(
        slot_name="environment_region",
        find={"label_contains_all": ["Environment", "Region"]},
        template="Environment: {environment} | Region: {region}",
    ),
    SlotBinding(
        slot_name="network_cidrs",
        find={"label_contains_all": ["VPC CIDR", "Subnet CIDR"]},
        template="VPC CIDR: {vpc_cidr} | Subnet CIDR: {subnet_cidr}",
    ),
    SlotBinding(
        slot_name="database_info",
        find={"label_contains_all": ["Database Engine", "DB Version"]},
        template="Database Engine: {db_engine} | DB Version: {db_version}",
    ),
]


def _load_bindings_from_config(path: Path) -> list[SlotBinding] | None:
    """Load slot bindings from the versioned JSON config, or None if unusable."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    try:
        return [
            SlotBinding(
                slot_name=entry["slot_name"],
                find=entry["find"],
                template=entry["template"],
                mode=entry.get("mode", "replace_label"),
                preserve_regex=entry.get("preserve_regex"),
                expected_matches=entry.get("expected_matches", 1),
                required=entry.get("required", False),
            )
            for entry in raw["slots"]
        ]
    except (KeyError, TypeError):
        return None


def visible_label(value: str) -> str:
    """Strip HTML markup and decode entities to get the human-visible label."""
    text = re.sub(r"<[^>]+>", " ", value)
    decoded = html.unescape(text)
    return re.sub(r"\s+", " ", decoded).strip()


def _parse_drawio_bytes(content: bytes) -> ET.ElementTree:
    """Parse and validate uncompressed draw.io XML bytes (POC ``parse_drawio``)."""
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise DiagramError("diagram is not valid UTF-8 text") from exc
    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        raise DiagramError(f"invalid XML: {exc}") from exc
    if root.tag != "mxfile":
        raise DiagramError("root element must be 'mxfile'")
    if root.get("compressed", "false").casefold() != "false":
        raise DiagramError("compressed draw.io files are not supported")
    if not root.findall("diagram"):
        raise DiagramError("no diagram pages found in file")
    ids = [cell.get("id") for cell in root.iter("mxCell") if cell.get("id") is not None]
    if len(ids) != len(set(ids)):
        raise DiagramError("present mxCell IDs must be unique")
    return ET.ElementTree(root)


def _geometry_signature(cell: ET.Element) -> tuple[Any, ...] | None:
    geometry = cell.find("mxGeometry")
    if geometry is None:
        return None
    return (
        tuple(sorted(geometry.attrib.items())),
        tuple(ET.tostring(child, encoding="unicode") for child in geometry),
    )


def _structural_snapshot(tree: ET.ElementTree) -> dict[str, Any]:
    """A snapshot used to prove nothing but bound cell values changed."""
    root = tree.getroot()
    return {
        "mxfile": tuple(
            sorted(
                (key, value)
                for key, value in root.attrib.items()
                if key not in {"modified", "etag", "agent"}
            )
        ),
        "pages": [(diagram.get("id"), diagram.get("name")) for diagram in root.findall("diagram")],
        "cells": {
            f"{index}:{cell.get('id') or '<missing>'}": {
                "parent": cell.get("parent"),
                "style": cell.get("style"),
                "vertex": cell.get("vertex"),
                "edge": cell.get("edge"),
                "source": cell.get("source"),
                "target": cell.get("target"),
                "geometry": _geometry_signature(cell),
            }
            for index, cell in enumerate(root.iter("mxCell"))
        },
    }


def _matches(label: str, find: Mapping[str, Any]) -> bool:
    folded = label.casefold()
    if "label_startswith" in find:
        return folded.startswith(str(find["label_startswith"]).casefold())
    if "label_contains" in find:
        return str(find["label_contains"]).casefold() in folded
    if "label_contains_all" in find:
        values = find["label_contains_all"]
        if isinstance(values, list):
            return all(str(value).casefold() in folded for value in values)
        return str(values).casefold() in folded
    raise DiagramError("slot find rule is unsupported")


def _bind_slots(
    tree: ET.ElementTree,
    slots: list[SlotBinding],
    warnings: list[str],
) -> list[tuple[SlotBinding, int, ET.Element]]:
    """Bind configured slots to cells by ordinal position, never by ID."""
    cells = list(tree.getroot().iter("mxCell"))
    bindings: list[tuple[SlotBinding, int, ET.Element]] = []
    used_ordinals: set[int] = set()
    for slot in slots:
        matches = [
            (index, cell)
            for index, cell in enumerate(cells)
            if _matches(visible_label(cell.get("value", "")), slot.find)
        ]
        if len(matches) == 0 and not slot.required:
            warnings.append(f"Slot '{slot.slot_name}' found no matching cells")
            continue
        if len(matches) != slot.expected_matches:
            raise DiagramError(
                f"slot '{slot.slot_name}' matched {len(matches)} cells; "
                f"expected {slot.expected_matches}"
            )
        for ordinal, cell in matches:
            if ordinal in used_ordinals:
                raise DiagramError(f"cell ordinal {ordinal} is bound by more than one slot")
            used_ordinals.add(ordinal)
            bindings.append((slot, ordinal, cell))
    return bindings


def _render_template(template: str, tokens: Mapping[str, Any]) -> str:
    """Render a slot template and wrap it as escaped, ``<br>``-aware HTML."""
    try:
        rendered = template.format(**tokens)
    except (KeyError, IndexError) as exc:
        raise DiagramError(f"slot template references unknown token {exc}") from exc
    parts = rendered.split("<br>")
    return "<div>" + "<br>".join(html.escape(part, quote=False) for part in parts) + "</div>"


def _fill(
    diagram_xml: bytes,
    tokens: Mapping[str, Any],
    slot_bindings: list[SlotBinding],
) -> FillResult:
    warnings: list[str] = []
    try:
        source_tree = _parse_drawio_bytes(diagram_xml)
        before_structure = _structural_snapshot(source_tree)
        source_values = [cell.get("value", "") for cell in source_tree.getroot().iter("mxCell")]

        tree = copy.deepcopy(source_tree)
        bindings = _bind_slots(tree, slot_bindings, warnings)
        bound_ordinals = {ordinal for _, ordinal, _ in bindings}

        mutations: list[dict[str, Any]] = []
        for slot, _ordinal, cell in bindings:
            if slot.mode != "replace_label":
                raise DiagramError(f"slot '{slot.slot_name}' has unsupported mode")
            old_label = visible_label(cell.get("value", ""))
            render_tokens = dict(tokens)
            if slot.preserve_regex:
                match = re.search(slot.preserve_regex, old_label)
                if not match or len(match.groups()) != 1:
                    raise DiagramError(
                        f"slot '{slot.slot_name}' could not preserve its label suffix"
                    )
                render_tokens["preserved"] = match.group(1)
            new_value = _render_template(slot.template, render_tokens)
            cell.set("value", new_value)
            mutations.append(
                {
                    "slot_name": slot.slot_name,
                    "cell_id": cell.get("id", ""),
                    "original_value": old_label,
                    "new_value": visible_label(new_value),
                }
            )

        if _structural_snapshot(tree) != before_structure:
            raise DiagramError("draw.io structural postflight failed")
        for ordinal, cell in enumerate(tree.getroot().iter("mxCell")):
            if ordinal not in bound_ordinals and cell.get("value", "") != source_values[ordinal]:
                raise DiagramError(f"unbound cell ordinal {ordinal} changed")

        ET.indent(tree, space="  ")
        buffer = io.BytesIO()
        tree.write(buffer, encoding="utf-8", xml_declaration=False, short_empty_elements=True)
        filled_xml = b'<?xml version="1.0" encoding="UTF-8"?>\n' + buffer.getvalue()

        return FillResult(
            success=True, filled_xml=filled_xml, mutations=mutations, warnings=warnings
        )
    except DiagramError as exc:
        return FillResult(success=False, errors=[str(exc)], warnings=warnings)


class DiagramFiller:
    """Fills draw.io diagram labels with resolved token values."""

    def __init__(self, slot_bindings: list[SlotBinding] | None = None) -> None:
        self._slot_bindings = slot_bindings or self._default_bindings()

    def fill(self, diagram_xml: bytes, tokens: Mapping[str, Any]) -> FillResult:
        """Fill diagram labels with token values."""
        return _fill(diagram_xml, tokens, self._slot_bindings)

    def _default_bindings(self) -> list[SlotBinding]:
        """Load bindings from the versioned config, falling back to a small built-in set."""
        loaded = _load_bindings_from_config(_CONFIG_PATH)
        return loaded if loaded is not None else _FALLBACK_BINDINGS


def fill_diagram(
    diagram_xml: bytes,
    tokens: Mapping[str, Any],
    slot_bindings: list[SlotBinding] | None = None,
) -> FillResult:
    """Convenience function to fill a diagram with tokens."""
    filler = DiagramFiller(slot_bindings)
    return filler.fill(diagram_xml, tokens)
