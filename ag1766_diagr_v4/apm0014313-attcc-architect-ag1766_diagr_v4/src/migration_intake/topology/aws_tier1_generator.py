"""AWS Tier 1 / PaaS Apps dynamic generator.

Generates interface boxes and connectors inside the AWS Tier 1 container.
Each ProtocolFamilyGroup produces:
- a dashed interface box with comma-separated labels
- a connector with family color and port label

The generator is idempotent:
- removes prior generated elements (prefix ``aws_tier1_gen_``)
- recreates deterministic rows from normalized interface groups

Static AWS icons (S3, KMS, Secrets Manager) are preserved in the template.
"""

from __future__ import annotations

import hashlib
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from migration_intake.topology.interface_normalization import (
        ProtocolFamilyGroup,
    )


GENERATED_ID_PREFIX = "aws_tier1_gen_"

LAYOUT = {
    "container_role": "aws_tier1_container",
    "bg_role": "aws_tier1_bg",
    "start_x": 7.0,
    "start_y": 140.0,      # below the static icons row
    "row_spacing": 10.0,
    "box_width": 170.0,
    "box_height": 46.0,
    "max_rows": 15,
    "max_interfaces_per_group": 20,
    "line_height": 16.0,
    "padding": 8.0,
}

INTERFACE_BOX_STYLE = (
    "rounded=1;whiteSpace=wrap;html=1;dashed=1;strokeColor=#000000;"
    "fillColor=#E6E6E6;fontStyle=1;fontSize=10;align=left;verticalAlign=top;spacing=4;"
)

CONNECTOR_STYLE = (
    "rounded=0;orthogonalLoop=1;jettySize=auto;html=1;"
    "startArrow={start_arrow};startFill=1;endArrow={end_arrow};endFill=0;"
    "edgeStyle=orthogonalEdgeStyle;"
    "strokeColor={color};strokeWidth=2;"
)

EDGE_LABEL_STYLE = (
    "edgeLabel;html=1;align=center;verticalAlign=middle;"
    "resizable=0;points=[];fontSize=10;fontStyle=1;"
)


@dataclass
class GeneratedElement:
    """A generated mxCell element for the AWS Tier 1 section."""

    element_id: str
    element_type: str
    group_key: str
    xml_element: ET.Element


@dataclass
class GenerationResult:
    """Result of AWS Tier 1 section generation."""

    elements_created: list[GeneratedElement] = field(default_factory=list)
    elements_deleted: int = 0
    rows_generated: int = 0
    issues: list[str] = field(default_factory=list)


def _stable_id(kind: str, key: str) -> str:
    digest = hashlib.md5(f"{kind}|{key}".encode("utf-8")).hexdigest()[:12]
    return f"{GENERATED_ID_PREFIX}{digest}"


def _find_container(root: ET.Element) -> ET.Element | None:
    for cell in root.iter("mxCell"):
        if LAYOUT["container_role"] in cell.get("haf-role", "").split():
            return cell
    return None


def _find_bg_rect(root: ET.Element) -> ET.Element | None:
    for cell in root.iter("mxCell"):
        if LAYOUT["bg_role"] in cell.get("haf-role", "").split():
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


def _box_height_wrapped(label_count: int) -> float:
    """Estimate box height for comma-separated wrapped labels."""
    if label_count <= 2:
        return LAYOUT["box_height"]
    chars_per_line = max(1, LAYOUT["box_width"] / 6.5)
    avg_label_chars = 20
    labels_per_line = max(1, chars_per_line / avg_label_chars)
    lines = max(1, -(-label_count // int(labels_per_line)))
    h = lines * LAYOUT["line_height"] + 2 * LAYOUT["padding"]
    return max(LAYOUT["box_height"], h)


def _arrow_config(direction: str) -> tuple[str, str]:
    """Return (start_arrow, end_arrow) for the connector."""
    key = (direction or "").upper()
    if key == "INBOUND" or key == "IN":
        return ("classic", "none")
    if key == "OUTBOUND" or key == "OUT":
        return ("none", "classic")
    if key in ("BIDIRECTIONAL", "IN/OUT"):
        return ("classic", "classic")
    return ("classic", "none")  # default to inbound


def generate_aws_tier1_rows(
    tree: ET.ElementTree,
    interface_groups: list["ProtocolFamilyGroup"],
) -> GenerationResult:
    """Generate AWS Tier 1 interface boxes inside the existing container.

    Each ProtocolFamilyGroup produces:
    - a dashed interface box with comma-separated app labels
    - a connector exiting the container to the right
    - an edge label with port display on the connector
    """
    result = GenerationResult()
    root = tree.getroot()
    graph_root = _find_graph_root(root)
    container = _find_container(root)

    if graph_root is None:
        result.issues.append("Graph root not found in template")
        return result
    if container is None:
        result.issues.append("AWS Tier 1 container not found in template")
        return result

    result.elements_deleted = _delete_generated(root)

    if not interface_groups:
        return result

    container_id = container.get("id", "")
    geometry = container.find("mxGeometry")
    container_width = float(geometry.get("width", "341")) if geometry is not None else 341.0
    container_height = float(geometry.get("height", "220")) if geometry is not None else 220.0

    bg_rect = _find_bg_rect(root)

    current_y = LAYOUT["start_y"]
    for idx, group in enumerate(interface_groups[: LAYOUT["max_rows"]]):
        names = list(group.labels)
        if len(names) > LAYOUT["max_interfaces_per_group"]:
            overflow = len(names) - LAYOUT["max_interfaces_per_group"]
            names = names[: LAYOUT["max_interfaces_per_group"]]
            names.append(f"(+{overflow} more)")

        left_value = ", ".join(names)
        box_h = _box_height_wrapped(len(names))
        group_key = f"{group.family}_{idx}"
        port_display = group.port_display
        connector_color = group.connector_color
        direction_display = group.direction_display
        direction_for_arrows = {
            "IN": "INBOUND",
            "OUT": "OUTBOUND",
            "IN/OUT": "BIDIRECTIONAL",
        }.get(direction_display, "INBOUND")

        # Interface box (dashed rect with app labels)
        box_id = _stable_id("box", group_key)
        box = ET.SubElement(
            graph_root,
            "mxCell",
            {
                "id": box_id,
                "value": left_value,
                "style": INTERFACE_BOX_STYLE,
                "vertex": "1",
                "parent": container_id,
            },
        )
        ET.SubElement(
            box,
            "mxGeometry",
            {
                "x": f"{LAYOUT['start_x']}",
                "y": f"{current_y}",
                "width": f"{LAYOUT['box_width']}",
                "height": f"{box_h}",
                "as": "geometry",
            },
        )
        result.elements_created.append(
            GeneratedElement(box_id, "interface_box", group_key, box)
        )

        # Connector (edge from box exiting right side of container)
        edge_id = _stable_id("edge", group_key)
        start_arrow, end_arrow = _arrow_config(direction_for_arrows)
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
                ),
                "edge": "1",
                "parent": container_id,
                "source": box_id,
            },
        )
        target_x = container_width
        source_y = current_y + box_h / 2
        geom = ET.SubElement(edge, "mxGeometry", {"relative": "1", "as": "geometry"})
        ET.SubElement(
            geom, "mxPoint",
            {"x": str(target_x), "y": str(source_y), "as": "targetPoint"},
        )
        result.elements_created.append(
            GeneratedElement(edge_id, "connector", group_key, edge)
        )

        # Edge label (port number)
        label_id = _stable_id("elabel", group_key)
        label = ET.SubElement(
            graph_root,
            "mxCell",
            {
                "id": label_id,
                "value": port_display,
                "style": EDGE_LABEL_STYLE,
                "vertex": "1",
                "connectable": "0",
                "parent": edge_id,
            },
        )
        ET.SubElement(
            label,
            "mxGeometry",
            {
                "x": "0.5",
                "y": "0",
                "relative": "1",
                "as": "geometry",
            },
        )
        result.elements_created.append(
            GeneratedElement(label_id, "edge_label", group_key, label)
        )

        current_y += box_h + LAYOUT["row_spacing"]
        result.rows_generated += 1

    if len(interface_groups) > LAYOUT["max_rows"]:
        result.issues.append(
            f"Truncated {len(interface_groups) - LAYOUT['max_rows']} groups"
        )

    # Auto-resize container and bg rect if content exceeds height
    required_height = current_y + LAYOUT["row_spacing"]
    if required_height > container_height:
        if geometry is not None:
            geometry.set("height", str(required_height))
        if bg_rect is not None:
            bg_geom = bg_rect.find("mxGeometry")
            if bg_geom is not None:
                bg_geom.set("height", str(required_height))

    return result
