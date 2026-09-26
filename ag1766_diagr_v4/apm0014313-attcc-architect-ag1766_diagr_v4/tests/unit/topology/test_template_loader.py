"""Tests for template_loader — tab extraction from multi-tab draw.io templates."""

from __future__ import annotations

from pathlib import Path

import pytest

from migration_intake.topology.template_loader import extract_tab, list_tabs

_MASTER = Path(__file__).resolve().parents[3] / "docs" / "AWS_Outpost_Topology_Template_1-v1.7.drawio"


# ── Slice 1a ─────────────────────────────────────────────────────────────


class TestListTabs:
    """list_tabs() should enumerate diagram tabs from a multi-tab mxfile."""

    @pytest.fixture()
    def master_bytes(self) -> bytes:
        return _MASTER.read_bytes()

    def test_returns_five_entries(self, master_bytes: bytes) -> None:
        tabs = list_tabs(master_bytes)
        assert len(tabs) == 5

    def test_first_tab_is_without_lbs(self, master_bytes: bytes) -> None:
        tabs = list_tabs(master_bytes)
        assert tabs[0]["name"] == "Without LBs"
        assert tabs[0]["index"] == 0

    def test_last_variant_tab_is_hadr(self, master_bytes: bytes) -> None:
        tabs = list_tabs(master_bytes)
        assert tabs[3]["name"] == "HA/DR with Global Load Balancer"
        assert tabs[3]["index"] == 3

    def test_definitions_tab_is_last(self, master_bytes: bytes) -> None:
        tabs = list_tabs(master_bytes)
        assert tabs[4]["name"] == "Definitions"
        assert tabs[4]["index"] == 4

    def test_raises_on_non_mxfile_xml(self) -> None:
        with pytest.raises(ValueError, match="not a valid mxfile"):
            list_tabs(b"<root><child/></root>")

    def test_raises_on_non_xml(self) -> None:
        with pytest.raises(Exception):
            list_tabs(b"this is not xml")


# ── Slice 1b ─────────────────────────────────────────────────────────────

_ET = __import__("xml.etree.ElementTree", fromlist=["ElementTree"])


class TestExtractTabByName:
    """extract_tab(tab_name=...) should return a single-diagram mxfile."""

    @pytest.fixture()
    def master_bytes(self) -> bytes:
        return _MASTER.read_bytes()

    def test_returns_single_diagram(self, master_bytes: bytes) -> None:
        tab0 = extract_tab(master_bytes, tab_name="Without LBs")
        root = _ET.fromstring(tab0)
        assert root.tag == "mxfile"
        assert len(root.findall("diagram")) == 1

    def test_diagram_name_preserved(self, master_bytes: bytes) -> None:
        tab0 = extract_tab(master_bytes, tab_name="Without LBs")
        root = _ET.fromstring(tab0)
        assert root.findall("diagram")[0].get("name") == "Without LBs"

    def test_preserves_cell_count(self, master_bytes: bytes) -> None:
        tab0 = extract_tab(master_bytes, tab_name="Without LBs")
        cells = list(_ET.fromstring(tab0).iter("mxCell"))
        assert len(cells) == 151

    def test_preserves_mxfile_attributes(self, master_bytes: bytes) -> None:
        tab0 = extract_tab(master_bytes, tab_name="Without LBs")
        root = _ET.fromstring(tab0)
        original = _ET.fromstring(master_bytes)
        # host and type attributes should be preserved
        assert root.get("host") == original.get("host")

    def test_missing_name_raises(self, master_bytes: bytes) -> None:
        with pytest.raises(ValueError, match="not found"):
            extract_tab(master_bytes, tab_name="NonExistent Tab")


# ── Slice 1c ─────────────────────────────────────────────────────────────


class TestExtractTabByIndex:
    """extract_tab(tab_index=...) and error-handling edge cases."""

    @pytest.fixture()
    def master_bytes(self) -> bytes:
        return _MASTER.read_bytes()

    def test_extract_by_index_zero(self, master_bytes: bytes) -> None:
        tab0 = extract_tab(master_bytes, tab_index=0)
        root = _ET.fromstring(tab0)
        assert root.findall("diagram")[0].get("name") == "Without LBs"

    def test_extract_by_index_two(self, master_bytes: bytes) -> None:
        tab2 = extract_tab(master_bytes, tab_index=2)
        root = _ET.fromstring(tab2)
        assert root.findall("diagram")[0].get("name") == "F5 Load Balancer"

    def test_extract_by_index_preserves_cell_count(self, master_bytes: bytes) -> None:
        tab2 = extract_tab(master_bytes, tab_index=2)
        cells = list(_ET.fromstring(tab2).iter("mxCell"))
        assert len(cells) == 174

    def test_both_args_raises(self, master_bytes: bytes) -> None:
        with pytest.raises(ValueError, match="exactly one"):
            extract_tab(master_bytes, tab_name="Without LBs", tab_index=0)

    def test_neither_args_raises(self, master_bytes: bytes) -> None:
        with pytest.raises(ValueError, match="exactly one"):
            extract_tab(master_bytes)

    def test_out_of_range_raises(self, master_bytes: bytes) -> None:
        with pytest.raises(ValueError, match="out of range"):
            extract_tab(master_bytes, tab_index=99)

    def test_negative_index_raises(self, master_bytes: bytes) -> None:
        with pytest.raises(ValueError, match="out of range"):
            extract_tab(master_bytes, tab_index=-1)
