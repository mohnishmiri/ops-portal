"""Tests for bundled template loading (Slice 6)."""

from __future__ import annotations

import xml.etree.ElementTree as ET

import pytest

from migration_intake.topology.haf_pipeline import HafProfileError


class TestLoadBundledTemplate:
    """load_bundled_template extracts the correct tab."""

    def test_basic_returns_valid_xml(self) -> None:
        from migration_intake.topology.template_loader import load_bundled_template

        data = load_bundled_template("basic")
        tree = ET.fromstring(data)
        assert tree.tag == "mxfile"

    def test_basic_has_one_diagram(self) -> None:
        from migration_intake.topology.template_loader import load_bundled_template

        data = load_bundled_template("basic")
        tree = ET.fromstring(data)
        diagrams = tree.findall("diagram")
        assert len(diagrams) == 1
        assert diagrams[0].get("name") == "Without LBs"

    def test_tlgw_returns_correct_tab(self) -> None:
        from migration_intake.topology.template_loader import load_bundled_template

        data = load_bundled_template("tlgw")
        tree = ET.fromstring(data)
        diagrams = tree.findall("diagram")
        assert len(diagrams) == 1
        assert diagrams[0].get("name") == "tLGW Load Balancer"

    def test_f5_returns_correct_tab(self) -> None:
        from migration_intake.topology.template_loader import load_bundled_template

        data = load_bundled_template("f5")
        tree = ET.fromstring(data)
        diagrams = tree.findall("diagram")
        assert len(diagrams) == 1
        assert diagrams[0].get("name") == "F5 Load Balancer"

    def test_hadr_returns_correct_tab(self) -> None:
        from migration_intake.topology.template_loader import load_bundled_template

        data = load_bundled_template("hadr")
        tree = ET.fromstring(data)
        diagrams = tree.findall("diagram")
        assert len(diagrams) == 1
        assert diagrams[0].get("name") == "HA/DR with Global Load Balancer"

    def test_unknown_variant_raises(self) -> None:
        from migration_intake.topology.template_loader import load_bundled_template

        with pytest.raises(HafProfileError, match="Unknown variant"):
            load_bundled_template("nonexistent")

    def test_basic_has_haf_roles(self) -> None:
        from migration_intake.topology.template_loader import load_bundled_template
        from migration_intake.topology.haf_pipeline import parse_haf_template

        data = load_bundled_template("basic")
        index = parse_haf_template(data)
        assert len(index.all_roles) >= 40
