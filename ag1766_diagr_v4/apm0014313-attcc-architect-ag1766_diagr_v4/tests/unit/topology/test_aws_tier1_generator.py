"""AWS Tier 1 Generator tests.

All data is synthetic. No client data is used.
Tests the AWS Tier 1 generator with ProtocolFamilyGroup inputs:
dynamic interface boxes, connectors with port labels, container auto-resize.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET

import pytest

from migration_intake.topology.interface_normalization import (
    FAMILY_COLORS,
    ProtocolFamilyGroup,
    create_interface_candidate,
)


def _candidate(
    *,
    app: str = "APP",
    corr: str = "100",
    location: str = "AWS",
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
    """A minimal draw.io template with AWS Tier 1 container."""
    xml = (
        '<mxfile><diagram id="p1" name="T">'
        '<mxGraphModel><root>'
        '<mxCell id="0"/>'
        '<mxCell id="1" parent="0"/>'
        '<mxCell id="aws-group" parent="1" value="" vertex="1"'
        ' connectable="0" style="group" haf-role="aws_tier1_container">'
        '<mxGeometry x="-1303" y="251" width="341" height="220" as="geometry"/>'
        '</mxCell>'
        '<mxCell id="aws-bg" parent="aws-group" value="" vertex="1"'
        ' style="rounded=0;whiteSpace=wrap;html=1;strokeColor=#6c8ebf;fillColor=#FFCC99;"'
        ' haf-role="aws_tier1_bg">'
        '<mxGeometry width="341" height="220" as="geometry"/>'
        '</mxCell>'
        '<mxCell id="aws-title" parent="aws-group" value="&lt;b&gt;AWS Tier 1 / PaaS Apps&lt;/b&gt;"'
        ' vertex="1" style="text;html=1;" haf-role="aws_tier1_title">'
        '<mxGeometry x="34" y="6" width="143" height="30" as="geometry"/>'
        '</mxCell>'
        '</root></mxGraphModel></diagram></mxfile>'
    )
    return ET.ElementTree(ET.fromstring(xml))


# ── Slice 6a: Module exists and basic generation ─────────────────────


class TestAwsTier1GeneratorExists:
    """Generator module can be imported and produces output."""

    def test_import(self):
        from migration_intake.topology.aws_tier1_generator import (
            generate_aws_tier1_rows,
        )
        assert callable(generate_aws_tier1_rows)

    def test_empty_groups_no_crash(self):
        from migration_intake.topology.aws_tier1_generator import (
            generate_aws_tier1_rows,
        )
        tree = _minimal_template()
        result = generate_aws_tier1_rows(tree, [])
        assert result.rows_generated == 0
        assert result.elements_created == []


# ── Slice 6b: Interface box rendering ────────────────────────────────


class TestAwsTier1InterfaceBoxes:
    """Generator creates dashed interface boxes with correct labels."""

    def test_single_group_generates_one_row(self):
        from migration_intake.topology.aws_tier1_generator import (
            generate_aws_tier1_rows,
        )
        group = _make_family_group(
            family="HTTPS",
            candidates=[_candidate(app="DTV-VDAS", corr="32387")],
        )
        tree = _minimal_template()
        result = generate_aws_tier1_rows(tree, [group])
        assert result.rows_generated == 1

    def test_interface_box_has_dashed_style(self):
        from migration_intake.topology.aws_tier1_generator import (
            generate_aws_tier1_rows,
        )
        group = _make_family_group(
            candidates=[_candidate(app="DTV-VDAS", corr="32387")],
        )
        tree = _minimal_template()
        result = generate_aws_tier1_rows(tree, [group])
        box = next(
            e for e in result.elements_created if e.element_type == "interface_box"
        )
        style = box.xml_element.get("style", "")
        assert "dashed=1" in style

    def test_interface_box_label_format(self):
        from migration_intake.topology.aws_tier1_generator import (
            generate_aws_tier1_rows,
        )
        group = _make_family_group(
            candidates=[_candidate(app="DTV-VDAS", corr="32387")],
        )
        tree = _minimal_template()
        result = generate_aws_tier1_rows(tree, [group])
        box = next(
            e for e in result.elements_created if e.element_type == "interface_box"
        )
        value = box.xml_element.get("value", "")
        assert "DTV-VDAS (32387)" in value

    def test_multi_label_comma_separated(self):
        from migration_intake.topology.aws_tier1_generator import (
            generate_aws_tier1_rows,
        )
        group = _make_family_group(
            candidates=[
                _candidate(app="APP1", corr="100"),
                _candidate(app="APP2", corr="200"),
            ],
        )
        tree = _minimal_template()
        result = generate_aws_tier1_rows(tree, [group])
        box = next(
            e for e in result.elements_created if e.element_type == "interface_box"
        )
        value = box.xml_element.get("value", "")
        assert ", " in value
        assert "APP1 (100)" in value
        assert "APP2 (200)" in value


# ── Slice 6c: Connector with port label ──────────────────────────────


class TestAwsTier1Connectors:
    """Generator creates connectors with port labels."""

    def test_connector_created(self):
        from migration_intake.topology.aws_tier1_generator import (
            generate_aws_tier1_rows,
        )
        group = _make_family_group(
            candidates=[_candidate(app="A", corr="1")],
        )
        tree = _minimal_template()
        result = generate_aws_tier1_rows(tree, [group])
        connectors = [e for e in result.elements_created if e.element_type == "connector"]
        assert len(connectors) == 1

    def test_connector_has_family_color(self):
        from migration_intake.topology.aws_tier1_generator import (
            generate_aws_tier1_rows,
        )
        group = _make_family_group(
            family="HTTPS",
            candidates=[_candidate()],
        )
        tree = _minimal_template()
        result = generate_aws_tier1_rows(tree, [group])
        edge = next(e for e in result.elements_created if e.element_type == "connector")
        style = edge.xml_element.get("style", "")
        assert FAMILY_COLORS["HTTPS"] in style

    def test_edge_label_has_port(self):
        from migration_intake.topology.aws_tier1_generator import (
            generate_aws_tier1_rows,
        )
        group = _make_family_group(
            candidates=[_candidate(port="443")],
        )
        tree = _minimal_template()
        result = generate_aws_tier1_rows(tree, [group])
        labels = [e for e in result.elements_created if e.element_type == "edge_label"]
        assert len(labels) == 1
        value = labels[0].xml_element.get("value", "")
        assert "443" in value

    def test_connector_direction_inbound(self):
        """Inbound: arrow points FROM the connector back to source."""
        from migration_intake.topology.aws_tier1_generator import (
            generate_aws_tier1_rows,
        )
        group = _make_family_group(
            candidates=[_candidate(direction="Inbound")],
        )
        tree = _minimal_template()
        result = generate_aws_tier1_rows(tree, [group])
        edge = next(e for e in result.elements_created if e.element_type == "connector")
        style = edge.xml_element.get("style", "")
        assert "startArrow=classic" in style


# ── Slice 6d: Container auto-resize and multiple groups ──────────────


class TestAwsTier1AutoResize:
    """Container expands when interface boxes exceed height."""

    def test_container_expands_with_many_groups(self):
        from migration_intake.topology.aws_tier1_generator import (
            generate_aws_tier1_rows,
        )
        groups = [
            _make_family_group(
                family=f"FAM{i}",
                candidates=[_candidate(app=f"APP{i}", corr=str(i), port=str(1000 + i))],
            )
            for i in range(5)
        ]
        tree = _minimal_template()

        container = None
        for cell in tree.getroot().iter("mxCell"):
            if "aws_tier1_container" in cell.get("haf-role", ""):
                container = cell
                break
        orig_h = float(container.find("mxGeometry").get("height", "220"))

        result = generate_aws_tier1_rows(tree, groups)
        assert result.rows_generated == 5

        new_h = float(container.find("mxGeometry").get("height", "220"))
        # 5 groups starting at y=140 with ~58px each + spacing should exceed 220
        assert new_h > orig_h

    def test_bg_rect_also_expands(self):
        from migration_intake.topology.aws_tier1_generator import (
            generate_aws_tier1_rows,
        )
        groups = [
            _make_family_group(
                family=f"FAM{i}",
                candidates=[_candidate(app=f"APP{i}", corr=str(i), port=str(1000 + i))],
            )
            for i in range(5)
        ]
        tree = _minimal_template()

        bg = None
        for cell in tree.getroot().iter("mxCell"):
            if "aws_tier1_bg" in cell.get("haf-role", ""):
                bg = cell
                break
        orig_h = float(bg.find("mxGeometry").get("height", "220"))

        result = generate_aws_tier1_rows(tree, groups)
        new_h = float(bg.find("mxGeometry").get("height", "220"))
        assert new_h > orig_h

    def test_idempotent_regeneration(self):
        """Running generator twice produces same output."""
        from migration_intake.topology.aws_tier1_generator import (
            generate_aws_tier1_rows,
        )
        group = _make_family_group(
            candidates=[_candidate(app="TEST", corr="1")],
        )
        tree = _minimal_template()
        r1 = generate_aws_tier1_rows(tree, [group])
        assert r1.rows_generated == 1

        # Run again on same tree — should clean up and regenerate
        r2 = generate_aws_tier1_rows(tree, [group])
        assert r2.rows_generated == 1
        assert r2.elements_deleted > 0  # cleaned up previous run
