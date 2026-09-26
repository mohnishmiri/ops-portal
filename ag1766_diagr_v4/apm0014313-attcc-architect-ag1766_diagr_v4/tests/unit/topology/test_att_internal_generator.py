"""ATT Internal Generator tests for protocol-family grouped rendering.

All data is synthetic. No client data is used.
Tests the generator with ProtocolFamilyGroup inputs: comma labels,
dynamic height, and family-based connector colors.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET

import pytest

from migration_intake.topology.att_internal_generator import (
    GENERATED_ID_PREFIX,
    LAYOUT,
    _left_height_wrapped,
    generate_att_internal_rows,
)
from migration_intake.topology.interface_normalization import (
    FAMILY_COLORS,
    ProtocolFamilyGroup,
    create_interface_candidate,
)


def _candidate(
    *,
    app: str = "APP",
    corr: str = "100",
    location: str = "Midrange",
    direction: str = "Inbound",
    protocol: str = "HTTPS(TLSv1.2)",
    port: str = "443",
):
    return create_interface_candidate(
        interface_system_location=location,
        data_traffic_direction=direction,
        target_protocol=protocol,
        future_port=port,
        interface_app_acronym=app,
        interface_correlation_id=corr,
    )


def _make_family_group(
    family: str = "HTTPS",
    candidates=None,
) -> ProtocolFamilyGroup:
    """Build a finalized ProtocolFamilyGroup."""
    g = ProtocolFamilyGroup(family=family)
    for c in (candidates or []):
        g.add_candidate(c)
    g.finalize()
    return g


def _minimal_template() -> ET.ElementTree:
    """A minimal draw.io template with ATT Internal band container."""
    xml = (
        '<mxfile><diagram id="p1" name="T">'
        '<mxGraphModel><root>'
        '<mxCell id="0"/>'
        '<mxCell id="1" parent="0"/>'
        '<mxCell id="att-band" parent="1" value="" vertex="1"'
        ' style="fillColor=#DAE8FC;" haf-role="att_internal_interfaces_band">'
        '<mxGeometry x="-220" y="745" width="385" height="1000" as="geometry"/>'
        '</mxCell>'
        '</root></mxGraphModel></diagram></mxfile>'
    )
    return ET.ElementTree(ET.fromstring(xml))


# ── Slice 3: Comma-separated labels ──────────────────────────────────


class TestGeneratorCommaLabels:
    """Slice 3: Generator renders comma-separated labels for family groups."""

    def test_comma_separated_format(self):
        """Left box value uses ', ' separator not '&#10;'."""
        group = _make_family_group(
            candidates=[
                _candidate(app="APP1", corr="100"),
                _candidate(app="APP2", corr="200"),
            ],
        )
        tree = _minimal_template()
        result = generate_att_internal_rows(tree, [group])
        assert result.rows_generated == 1
        left_box = next(
            e for e in result.elements_created if e.element_type == "left_box"
        )
        value = left_box.xml_element.get("value", "")
        assert ", " in value
        assert "&#10;" not in value
        assert "APP1 (100)" in value
        assert "APP2 (200)" in value

    def test_multi_port_in_label(self):
        """Label box shows '443 8447' for multi-port group."""
        group = _make_family_group(
            candidates=[
                _candidate(port="443"),
                _candidate(port="8447", app="B", corr="2"),
            ],
        )
        tree = _minimal_template()
        result = generate_att_internal_rows(tree, [group])
        label = next(
            e for e in result.elements_created if e.element_type == "edge_label"
        )
        value = label.xml_element.get("value", "")
        assert "443 8447" in value

    def test_single_port_in_label(self):
        """Label box shows '1521' for single-port group."""
        group = _make_family_group(
            family="ORACLE_DB",
            candidates=[
                _candidate(protocol="JDBC over TLS", port="1521"),
            ],
        )
        tree = _minimal_template()
        result = generate_att_internal_rows(tree, [group])
        label = next(
            e for e in result.elements_created if e.element_type == "edge_label"
        )
        value = label.xml_element.get("value", "")
        assert "1521" in value

    def test_direction_in_label(self):
        """Label box second line shows aggregated direction."""
        group = _make_family_group(
            candidates=[
                _candidate(direction="Inbound", app="A", corr="1"),
                _candidate(direction="Outbound", app="B", corr="2"),
            ],
        )
        tree = _minimal_template()
        result = generate_att_internal_rows(tree, [group])
        label = next(
            e for e in result.elements_created if e.element_type == "edge_label"
        )
        value = label.xml_element.get("value", "")
        assert "IN/OUT" in value

    def test_overflow_truncation(self):
        """More than max_labels → shows '(+N more)'."""
        candidates = [
            _candidate(app=f"APP{i}", corr=str(i))
            for i in range(LAYOUT["max_interfaces_per_group"] + 5)
        ]
        group = _make_family_group(candidates=candidates)
        tree = _minimal_template()
        result = generate_att_internal_rows(tree, [group])
        left_box = next(
            e for e in result.elements_created if e.element_type == "left_box"
        )
        value = left_box.xml_element.get("value", "")
        assert "(+5 more)" in value


# ── Slice 4: Dynamic height for wrapped labels ──────────────────────


class TestDynamicHeight:
    """Slice 4: Left box height scales with label count."""

    def test_single_label_min_height(self):
        assert _left_height_wrapped(1, LAYOUT["left_width"]) >= LAYOUT["left_min_height"]

    def test_seven_labels_taller(self):
        h1 = _left_height_wrapped(1, LAYOUT["left_width"])
        h7 = _left_height_wrapped(7, LAYOUT["left_width"])
        assert h7 > h1

    def test_height_scales_with_labels(self):
        h5 = _left_height_wrapped(5, LAYOUT["left_width"])
        h10 = _left_height_wrapped(10, LAYOUT["left_width"])
        assert h10 > h5

    def test_zero_labels_min_height(self):
        assert _left_height_wrapped(0, LAYOUT["left_width"]) == LAYOUT["left_min_height"]


# ── Slice 5: Connector color per family ──────────────────────────────


class TestConnectorColors:
    """Slice 5: Connector stroke color matches protocol family."""

    def test_https_family_blue(self):
        group = _make_family_group(
            family="HTTPS",
            candidates=[_candidate()],
        )
        tree = _minimal_template()
        result = generate_att_internal_rows(tree, [group])
        edge = next(
            e for e in result.elements_created if e.element_type == "connector"
        )
        style = edge.xml_element.get("style", "")
        assert FAMILY_COLORS["HTTPS"] in style

    def test_oracle_db_teal(self):
        group = _make_family_group(
            family="ORACLE_DB",
            candidates=[
                _candidate(protocol="JDBC over TLS", port="1521"),
            ],
        )
        tree = _minimal_template()
        result = generate_att_internal_rows(tree, [group])
        edge = next(
            e for e in result.elements_created if e.element_type == "connector"
        )
        style = edge.xml_element.get("style", "")
        assert FAMILY_COLORS["ORACLE_DB"] in style

    def test_unknown_family_gray(self):
        group = _make_family_group(
            family="UNKNOWN",
            candidates=[_candidate(protocol="", port="")],
        )
        tree = _minimal_template()
        result = generate_att_internal_rows(tree, [group])
        edge = next(
            e for e in result.elements_created if e.element_type == "connector"
        )
        style = edge.xml_element.get("style", "")
        assert FAMILY_COLORS["UNKNOWN"] in style


# ── Slice 7: Unknown group rendering ─────────────────────────────────


class TestUnknownGroupRendering:
    """Slice 7: Unknown group with incomplete records."""

    def test_unknown_group_shows_question_mark_port(self):
        """Unknown group label box shows '?' for port."""
        group = _make_family_group(
            family="UNKNOWN",
            candidates=[_candidate(protocol="", port="", direction="")],
        )
        tree = _minimal_template()
        result = generate_att_internal_rows(tree, [group])
        label = next(
            e for e in result.elements_created if e.element_type == "edge_label"
        )
        value = label.xml_element.get("value", "")
        assert value.startswith("?")

    def test_unknown_group_shows_question_mark_direction(self):
        """Unknown group label box shows '?' for direction."""
        group = _make_family_group(
            family="UNKNOWN",
            candidates=[_candidate(protocol="", port="", direction="")],
        )
        tree = _minimal_template()
        result = generate_att_internal_rows(tree, [group])
        label = next(
            e for e in result.elements_created if e.element_type == "edge_label"
        )
        value = label.xml_element.get("value", "")
        assert "?" in value

    def test_unknown_group_rendered_last(self):
        """Unknown group appears after other groups when rendered."""
        groups = [
            _make_family_group(
                family="UNKNOWN",
                candidates=[_candidate(protocol="", port="", app="BAD", corr="99")],
            ),
            _make_family_group(
                family="HTTPS",
                candidates=[_candidate(app="GOOD", corr="1")],
            ),
        ]
        # Re-sort to match what group_interfaces_by_protocol_family produces
        from migration_intake.topology.interface_normalization import (
            group_interfaces_by_protocol_family,
        )
        candidates = [
            _candidate(app="GOOD", corr="1", protocol="HTTPS(TLSv1.2)", port="443"),
            _candidate(app="BAD", corr="99", protocol="", port=""),
        ]
        sorted_groups = group_interfaces_by_protocol_family(candidates)
        assert sorted_groups[-1].family == "UNKNOWN"

    def test_unknown_group_has_labels(self):
        """Unknown group still generates labels for its candidates."""
        group = _make_family_group(
            family="UNKNOWN",
            candidates=[
                _candidate(protocol="", port="", app="ImE FLEX", corr="15977"),
            ],
        )
        tree = _minimal_template()
        result = generate_att_internal_rows(tree, [group])
        left_box = next(
            e for e in result.elements_created if e.element_type == "left_box"
        )
        value = left_box.xml_element.get("value", "")
        assert "ImE FLEX (15977)" in value


# ── Slice 2d: Container height auto-resize ────────────────────────────


class TestContainerAutoResize:
    """Container and its background rect expand when rows exceed height."""

    def _small_template(self, height: int = 200) -> ET.ElementTree:
        """Template with a very short container to force overflow."""
        xml = (
            '<mxfile><diagram id="p1" name="T">'
            '<mxGraphModel><root>'
            '<mxCell id="0"/>'
            '<mxCell id="1" parent="0"/>'
            '<mxCell id="att-band" parent="1" value="" vertex="1"'
            ' style="fillColor=#DAE8FC;" haf-role="att_internal_interfaces_band">'
            f'<mxGeometry x="-220" y="745" width="385" height="{height}" as="geometry"/>'
            '</mxCell>'
            '</root></mxGraphModel></diagram></mxfile>'
        )
        return ET.ElementTree(ET.fromstring(xml))

    def test_container_height_expands_when_rows_exceed(self):
        """With many groups, the container height should grow beyond initial."""
        groups = [
            _make_family_group(
                family=f"FAM{i}",
                candidates=[_candidate(app=f"APP{i}", corr=str(i), port=str(1000 + i))],
            )
            for i in range(8)
        ]
        tree = self._small_template(height=200)  # way too short for 8 rows

        container = None
        for cell in tree.getroot().iter("mxCell"):
            if "att_internal_interfaces_band" in cell.get("haf-role", ""):
                container = cell
                break
        assert container is not None
        orig_h = float(container.find("mxGeometry").get("height", "200"))

        result = generate_att_internal_rows(tree, groups)
        assert result.rows_generated == 8

        new_h = float(container.find("mxGeometry").get("height", "200"))
        assert new_h > orig_h, f"Container height {new_h} should exceed original {orig_h}"

    def test_container_not_shrunk_when_few_rows(self):
        """Container keeps its original height when rows fit."""
        groups = [
            _make_family_group(
                family="HTTPS",
                candidates=[_candidate()],
            )
        ]
        tree = self._small_template(height=1000)

        container = None
        for cell in tree.getroot().iter("mxCell"):
            if "att_internal_interfaces_band" in cell.get("haf-role", ""):
                container = cell
                break
        assert container is not None

        result = generate_att_internal_rows(tree, groups)
        new_h = float(container.find("mxGeometry").get("height", "1000"))
        assert new_h == 1000.0, "Container should not shrink"
