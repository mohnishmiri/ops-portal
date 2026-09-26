"""AT&T Internal Interfaces dynamic generator.

Generates ATT internal rows inside the existing template container:
- left dashed app box
- port/direction label box
- connector line with protocol color and direction-aware arrows

The generator is idempotent:
- removes prior generated elements (prefix ``att_internal_gen_``)
- removes legacy static ATT slot cells
- recreates deterministic rows from normalized interface groups
"""

from __future__ import annotations

import hashlib
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from migration_intake.topology.interface_normalization import (
        InterfaceGroup,
        ProtocolFamilyGroup,
    )


GENERATED_ID_PREFIX = "att_internal_gen_"

STATIC_SLOT_ROLES = {
    "att_internal_in_slot",
    "att_internal_out_primary_slot",
    "att_internal_out_secondary_slot",
    "att_internal_in_out_slot",
}

LAYOUT = {
    "container_role": "att_internal_interfaces_band",
    "start_x": 15.0,
    "start_y": 40.0,
    "row_spacing": 12.0,
    "left_min_height": 60.0,
    "line_height": 16.0,
    "padding": 8.0,
    "left_width": 180.0,
    "label_width": 70.0,
    "label_height": 48.0,
    "label_right_margin": 28.0,
    "label_gap_from_left": 26.0,
    "max_rows": 15,
    "max_interfaces_per_group": 20,
}

LEFT_STYLE = (
    "rounded=1;whiteSpace=wrap;html=1;fillColor=#f5f5f5;fontColor=#333333;"
    "strokeColor=#666666;dashed=1;fontSize=10;align=left;verticalAlign=top;spacing=4;"
)
LABEL_STYLE = (
    "rounded=1;whiteSpace=wrap;html=1;fillColor=#FFFFFF;fontColor=#000000;"
    "strokeColor=#000000;fontSize=11;fontStyle=1;align=center;verticalAlign=middle;"
)
CONNECTOR_STYLE = (
    "endArrow={end_arrow};startArrow={start_arrow};html=1;rounded=0;"
    "exitX=1;exitY=0.5;exitDx=0;exitDy=0;"
    "entryX=1;entryY={entry_y};entryDx=0;entryDy=0;entryPerimeter=0;"
    "strokeColor={color};strokeWidth=2;"
)

PROTOCOL_COLORS = {
    "JDBC": "#67AB9F",
    "ORACLE": "#67AB9F",
    "ORACLE NET": "#67AB9F",
    "HTTPS": "#6666FF",
    "HTTP": "#6666FF",
    "SSH": "#00CC66",
    "SFTP": "#00CC66",
    "SQL": "#FF8000",
    "ODBC": "#FF8000",
    "SMTP": "#CC0000",
    "ORACLE GOLDENGATE": "#99004D",
    "GG": "#99004D",
    "DATAGUARD": "#CCCC00",
    "DEFAULT": "#000000",
}


@dataclass
class GeneratedElement:
    """A generated mxCell element for the ATT Internal section."""

    element_id: str
    element_type: str
    group_key: str
    xml_element: ET.Element


@dataclass
class GenerationResult:
    """Result of ATT Internal section generation."""

    elements_created: list[GeneratedElement] = field(default_factory=list)
    elements_deleted: int = 0
    static_slots_removed: int = 0
    rows_generated: int = 0
    issues: list[str] = field(default_factory=list)


def _stable_id(kind: str, key: str) -> str:
    digest = hashlib.md5(f"{kind}|{key}".encode("utf-8")).hexdigest()[:12]
    return f"{GENERATED_ID_PREFIX}{digest}"


def _find_parent(root: ET.Element, child: ET.Element) -> ET.Element | None:
    for candidate in root.iter():
        for c in list(candidate):
            if c is child:
                return candidate
    return None


def _find_container(root: ET.Element) -> ET.Element | None:
    for cell in root.iter("mxCell"):
        if LAYOUT["container_role"] in cell.get("haf-role", "").split():
            return cell
    return None


def _find_graph_root(root: ET.Element) -> ET.Element | None:
    for elem in root.iter("root"):
        return elem
    return None


def _delete_generated(root: ET.Element) -> int:
    targets: list[tuple[ET.Element, ET.Element]] = []
    for parent in root.iter():
        for child in list(parent):
            if child.tag == "mxCell" and child.get("id", "").startswith(GENERATED_ID_PREFIX):
                targets.append((parent, child))
    for parent, child in targets:
        parent.remove(child)
    return len(targets)


def _remove_static_slots(root: ET.Element) -> int:
    targets: list[tuple[ET.Element, ET.Element]] = []
    for parent in root.iter():
        for child in list(parent):
            if child.tag != "mxCell":
                continue
            roles = set(child.get("haf-role", "").split())
            if roles & STATIC_SLOT_ROLES:
                targets.append((parent, child))
    for parent, child in targets:
        parent.remove(child)
    return len(targets)


def _protocol_color(protocol: str) -> str:
    value = (protocol or "").upper().strip()
    if not value:
        return PROTOCOL_COLORS["DEFAULT"]
    if value in PROTOCOL_COLORS:
        return PROTOCOL_COLORS[value]
    for key in sorted((k for k in PROTOCOL_COLORS if k != "DEFAULT"), key=len, reverse=True):
        if re.search(rf"(?<![A-Z0-9]){re.escape(key)}(?![A-Z0-9])", value):
            return PROTOCOL_COLORS[key]
    if "22" in value:
        return PROTOCOL_COLORS["SFTP"]
    if "443" in value:
        return PROTOCOL_COLORS["HTTPS"]
    return PROTOCOL_COLORS["DEFAULT"]


def _direction_label(direction: str) -> str:
    key = (direction or "").upper()
    if key == "INBOUND":
        return "IN"
    if key == "OUTBOUND":
        return "OUT"
    if key == "BIDIRECTIONAL":
        return "IN/OUT"
    return "?"


def _arrow_config(direction: str) -> tuple[str, str]:
    key = (direction or "").upper()
    if key == "INBOUND":
        return ("classic", "none")
    if key == "OUTBOUND":
        return ("none", "classic")
    if key == "BIDIRECTIONAL":
        return ("classic", "classic")
    return ("none", "classic")


def _left_height(interface_count: int) -> float:
    h = interface_count * LAYOUT["line_height"] + (2 * LAYOUT["padding"])
    return max(LAYOUT["left_min_height"], h)


def _left_height_wrapped(label_count: int, left_width: float) -> float:
    """Estimate left box height for comma-separated wrapped labels.

    Adapted from drawpyo List.autosize() pattern — computes height from
    estimated line wrapping rather than child object count.

    At fontSize=10, approximately 6.5px per character.
    Average label: ~20 chars including ", " separator.
    """
    if label_count == 0:
        return LAYOUT["left_min_height"]
    avg_label_chars = 20
    chars_per_line = max(1, left_width / 6.5)
    labels_per_line = max(1, chars_per_line / avg_label_chars)
    lines = max(1, -(-label_count // int(labels_per_line)))  # ceil division
    h = lines * LAYOUT["line_height"] + 2 * LAYOUT["padding"]
    return max(LAYOUT["left_min_height"], h)


def _all_group_entries(group: "InterfaceGroup") -> list[tuple[str, str]]:
    entries: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()

    def add(app: str | None, corr: str | None) -> None:
        pair = ((app or "UNKNOWN").strip(), (corr or "?").strip())
        if pair in seen:
            return
        seen.add(pair)
        entries.append(pair)

    for e in group.entries_inbound:
        add(e.interface_app_acronym, e.interface_correlation_id)
    for e in group.entries_outbound:
        add(e.interface_app_acronym, e.interface_correlation_id)
    for e in group.entries_bidirectional:
        add(e.interface_app_acronym, e.interface_correlation_id)

    if not entries:
        for app, corr in getattr(group, "entries", []):
            add(app, corr)
    return entries


def _is_family_group(group: object) -> bool:
    """Check if a group is a ProtocolFamilyGroup (duck typing to avoid import)."""
    return hasattr(group, "family") and hasattr(group, "label_display")


def generate_att_internal_rows(
    tree: ET.ElementTree,
    interface_groups: list,
) -> GenerationResult:
    """Generate ATT internal rows inside the existing container.

    Accepts both InterfaceGroup (legacy per-protocol/port) and
    ProtocolFamilyGroup (new per-family) inputs.  When a
    ProtocolFamilyGroup is detected, uses comma-separated labels,
    multi-port display, aggregated direction, family-based connector
    color, and wrapping-aware height estimation.
    """
    result = GenerationResult()
    root = tree.getroot()
    graph_root = _find_graph_root(root)
    container = _find_container(root)

    if graph_root is None:
        result.issues.append("Graph root not found in template")
        return result
    if container is None:
        result.issues.append("ATT Internal container not found in template")
        return result

    result.elements_deleted = _delete_generated(root)
    result.static_slots_removed = _remove_static_slots(root)

    if not interface_groups:
        return result

    container_id = container.get("id", "")
    geometry = container.find("mxGeometry")
    container_width = float(geometry.get("width", "385")) if geometry is not None else 385.0
    container_height = float(geometry.get("height", "1000")) if geometry is not None else 1000.0

    label_x = max(
        LAYOUT["start_x"] + 120.0,
        container_width - LAYOUT["label_width"] - LAYOUT["label_right_margin"],
    )
    left_width = max(
        140.0,
        min(LAYOUT["left_width"], label_x - LAYOUT["start_x"] - LAYOUT["label_gap_from_left"]),
    )

    current_y = LAYOUT["start_y"]
    for idx, group in enumerate(interface_groups[: LAYOUT["max_rows"]]):
        # Branch: ProtocolFamilyGroup or legacy InterfaceGroup
        if _is_family_group(group):
            names = list(group.labels)
            if len(names) > LAYOUT["max_interfaces_per_group"]:
                overflow = len(names) - LAYOUT["max_interfaces_per_group"]
                names = names[: LAYOUT["max_interfaces_per_group"]]
                names.append(f"(+{overflow} more)")
            left_value = ", ".join(names)
            row_height = _left_height_wrapped(len(names), left_width)
            group_key = f"{group.family}_{idx}"
            port_display = group.port_display
            direction_display = group.direction_display
            connector_color = group.connector_color
            direction_for_arrows = {
                "IN": "INBOUND",
                "OUT": "OUTBOUND",
                "IN/OUT": "BIDIRECTIONAL",
            }.get(direction_display, "OUTBOUND")
        else:
            # Legacy InterfaceGroup path
            entries = _all_group_entries(group)
            if not entries:
                continue
            names = [f"{app} ({corr})" for app, corr in entries]
            if len(names) > LAYOUT["max_interfaces_per_group"]:
                overflow = len(names) - LAYOUT["max_interfaces_per_group"]
                names = names[: LAYOUT["max_interfaces_per_group"]]
                names.append(f"(+{overflow} more)")
            left_value = "&#10;".join(names)
            row_height = _left_height(len(names))
            group_key = f"{group.protocol}_{group.port}_{idx}"
            port_display = group.port or "?"
            direction = (
                "BIDIRECTIONAL"
                if group.entries_bidirectional
                else ("INBOUND" if group.entries_inbound and not group.entries_outbound else "OUTBOUND")
            )
            direction_display = _direction_label(direction)
            connector_color = _protocol_color(group.protocol)
            direction_for_arrows = direction

        if not names:
            continue

        left_id = _stable_id("left", group_key)
        left = ET.SubElement(
            graph_root,
            "mxCell",
            {
                "id": left_id,
                "value": left_value,
                "style": LEFT_STYLE,
                "vertex": "1",
                "parent": container_id,
            },
        )
        ET.SubElement(
            left,
            "mxGeometry",
            {
                "x": f"{LAYOUT['start_x']}",
                "y": f"{current_y}",
                "width": f"{left_width}",
                "height": f"{row_height}",
                "as": "geometry",
            },
        )
        result.elements_created.append(GeneratedElement(left_id, "left_box", group_key, left))

        label_id = _stable_id("label", group_key)
        label_y = current_y + (row_height - LAYOUT["label_height"]) / 2
        label = ET.SubElement(
            graph_root,
            "mxCell",
            {
                "id": label_id,
                "value": f"{port_display}&#10;{direction_display}",
                "style": LABEL_STYLE,
                "vertex": "1",
                "parent": container_id,
            },
        )
        ET.SubElement(
            label,
            "mxGeometry",
            {
                "x": f"{label_x}",
                "y": f"{label_y}",
                "width": f"{LAYOUT['label_width']}",
                "height": f"{LAYOUT['label_height']}",
                "as": "geometry",
            },
        )
        result.elements_created.append(GeneratedElement(label_id, "edge_label", group_key, label))

        edge_id = _stable_id("edge", group_key)
        start_arrow, end_arrow = _arrow_config(direction_for_arrows)
        entry_y = (current_y + row_height / 2) / max(container_height, 1.0)

        # Calculate waypoints for proper connector routing
        source_x = LAYOUT["start_x"] + left_width
        source_y = current_y + row_height / 2
        target_x = container_width
        target_y = source_y

        edge = ET.SubElement(
            graph_root,
            "mxCell",
            {
                "id": edge_id,
                "value": "",
                "style": CONNECTOR_STYLE.format(
                    color=connector_color,
                    start_arrow=start_arrow,
                    end_arrow=end_arrow,
                    entry_y=entry_y,
                ),
                "edge": "1",
                "parent": container_id,
                "source": left_id,
                "target": container_id,
            },
        )
        geom = ET.SubElement(edge, "mxGeometry", {"relative": "1", "as": "geometry"})
        ET.SubElement(geom, "mxPoint", {"x": str(source_x), "y": str(source_y), "as": "sourcePoint"})
        ET.SubElement(geom, "mxPoint", {"x": str(target_x), "y": str(target_y), "as": "targetPoint"})

        result.elements_created.append(GeneratedElement(edge_id, "connector", group_key, edge))

        current_y += row_height + LAYOUT["row_spacing"]
        result.rows_generated += 1

    if len(interface_groups) > LAYOUT["max_rows"]:
        result.issues.append(
            f"Truncated {len(interface_groups) - LAYOUT['max_rows']} groups due to max_rows limit"
        )

    # Auto-resize container if generated content exceeds current height.
    required_height = current_y + LAYOUT["row_spacing"]
    if required_height > container_height and geometry is not None:
        geometry.set("height", str(required_height))

    return result
