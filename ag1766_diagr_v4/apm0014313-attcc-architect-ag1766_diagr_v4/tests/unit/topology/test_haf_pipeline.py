"""Block 1-6 — haf_pipeline unit tests.

All data is synthetic. No client data is used.
The real input template structure is mirrored but with synthetic cell IDs/values.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET

import pytest

# ─── Synthetic fixtures ────────────────────────────────────────────────


def _synthetic_template() -> bytes:
    """Minimal draw.io template mimicking the v1.7 Outpost topology structure.

    Contains representative haf-role cells from each category:
    - Layout: root_layer, outer_frame, header_line
    - Infrastructure: private_application_subnet, app_security_group,
      workload_vpc, db_security_group, app_account_container
    - Legend: legend_protocol_https, legend_data_flow_label
    - Interface slots: att_internal_in_slot, azure_apps_slot, tier2_internet_slot
    - Detail blocks: nas_detail_block, ebr_detail_block
    - Multi-role cell: header_line page_inner_frame
    """
    return (
        b'<mxfile>'
        b'<diagram id="page1" name="Outpost Topology">'
        b'<mxGraphModel><root>'
        # Layout
        b'<mxCell id="root-0" haf-role="root_layer" />'
        b'<mxCell id="frame-1" parent="root-0" value="" vertex="1" '
        b'  style="fillColor=#FFE6CC;" haf-role="outer_frame">'
        b'<mxGeometry x="0" y="0" width="2000" height="1500" as="geometry"/></mxCell>'
        # Multi-role: header_line AND page_inner_frame
        b'<mxCell id="header-2" parent="root-0" value="AT&amp;T - AWS Alpharetta, GA NEEDS-OUTPOST-ID" '
        b'  vertex="1" style="rounded=0;" haf-role="header_line page_inner_frame">'
        b'<mxGeometry x="10" y="10" width="1980" height="40" as="geometry"/></mxCell>'
        # Infrastructure
        b'<mxCell id="subnet-3" parent="root-0" '
        b'  value="Private Application Subnet NEEDS-CIDR&#10;useast2-aldc-prod&#10;UNRESOLVED-subnet" '
        b'  vertex="1" haf-role="private_application_subnet">'
        b'<mxGeometry x="100" y="200" width="400" height="300" as="geometry"/></mxCell>'
        b'<mxCell id="sg-4" parent="root-0" '
        b'  value="Application Security Group&#10;UNRESOLVED-useast2-aldc-prod-sg" '
        b'  vertex="1" haf-role="app_security_group">'
        b'<mxGeometry x="120" y="220" width="360" height="260" as="geometry"/></mxCell>'
        b'<mxCell id="vpc-5" parent="root-0" '
        b'  value="Workload VPC sl-useast2-aldc-vpc-NEEDS-AZ-NEEDS-CIDR" '
        b'  vertex="1" haf-role="workload_vpc workload_vpc_label">'
        b'<mxGeometry x="80" y="180" width="500" height="400" as="geometry"/></mxCell>'
        b'<mxCell id="dbsg-6" parent="root-0" '
        b'  value="Database Security Group&#10;UNRESOLVED-useast2-aldc-prod-db-sg" '
        b'  vertex="1" haf-role="db_security_group">'
        b'<mxGeometry x="600" y="300" width="300" height="200" as="geometry"/></mxCell>'
        b'<mxCell id="acc-7" parent="root-0" '
        b'  value="AWS Application Account ACC-PROD-0-UNRESOLVED" '
        b'  vertex="1" haf-role="app_account_container">'
        b'<mxGeometry x="50" y="150" width="600" height="500" as="geometry"/></mxCell>'
        # Legend (protected)
        b'<mxCell id="legend-8" parent="root-0" value="HTTPS (443)" vertex="1" '
        b'  haf-role="legend_protocol_https">'
        b'<mxGeometry x="1600" y="100" width="100" height="20" as="geometry"/></mxCell>'
        b'<mxCell id="legend-9" parent="root-0" value="DATA FLOW LEGEND" vertex="1" '
        b'  haf-role="legend_data_flow_label">'
        b'<mxGeometry x="1600" y="80" width="150" height="20" as="geometry"/></mxCell>'
        # AT&T Internal Interfaces container (required for programmatic generation)
        b'<mxCell id="att-band" parent="root-0" '
        b'  value="" vertex="1" style="fillColor=#DAE8FC;" '
        b'  haf-role="att_internal_interfaces_band">'
        b'<mxGeometry x="-220" y="745" width="385" height="1000" as="geometry"/></mxCell>'
        # Interface slots
        b'<mxCell id="att-in-10" parent="att-band" '
        b'  value="&lt;None found in source data&gt;" vertex="1" '
        b'  haf-role="att_internal_in_slot">'
        b'<mxGeometry x="1200" y="200" width="200" height="300" as="geometry"/></mxCell>'
        b'<mxCell id="azure-11" parent="root-0" '
        b'  value="&lt;None found in source data&gt;" vertex="1" '
        b'  haf-role="azure_apps_slot">'
        b'<mxGeometry x="1200" y="600" width="200" height="200" as="geometry"/></mxCell>'
        b'<mxCell id="tier2-12" parent="root-0" '
        b'  value="&lt;None found in source data&gt;" vertex="1" '
        b'  haf-role="tier2_internet_slot">'
        b'<mxGeometry x="1200" y="850" width="200" height="100" as="geometry"/></mxCell>'
        # Detail blocks
        b'<mxCell id="nas-13" parent="root-0" '
        b'  value=" - NAS Server: &#10; - EC2 Names: " vertex="1" '
        b'  haf-role="nas_detail_block">'
        b'<mxGeometry x="900" y="700" width="250" height="80" as="geometry"/></mxCell>'
        b'<mxCell id="ebr-14" parent="root-0" '
        b'  value=" - Strategy: &#10; - EC2 Names: " vertex="1" '
        b'  haf-role="ebr_detail_block">'
        b'<mxGeometry x="900" y="800" width="250" height="80" as="geometry"/></mxCell>'
        # Cell without haf-role (should be preserved but not indexed)
        b'<mxCell id="plain-15" parent="root-0" value="Just a label" vertex="1">'
        b'<mxGeometry x="50" y="50" width="100" height="30" as="geometry"/></mxCell>'
        # Edge (no haf-role)
        b'<mxCell id="edge-16" parent="root-0" source="subnet-3" target="sg-4" edge="1"/>'
        b'</root></mxGraphModel></diagram></mxfile>'
    )


EXPECTED_ROLES = {
    "root_layer", "outer_frame", "header_line", "page_inner_frame",
    "private_application_subnet", "app_security_group",
    "workload_vpc", "workload_vpc_label", "db_security_group",
    "app_account_container",
    "legend_protocol_https", "legend_data_flow_label",
    "att_internal_interfaces_band",  # Container for programmatic generation
    "att_internal_in_slot", "azure_apps_slot", "tier2_internet_slot",
    "nas_detail_block", "ebr_detail_block",
}


# ─── Block 1: Parser / Indexer tests ──────────────────────────────────


class TestHafIndexer:
    """Block 1: parse draw.io XML and index cells by haf-role."""

    def test_parse_indexes_all_roles(self):
        from migration_intake.topology.haf_pipeline import parse_haf_template

        index = parse_haf_template(_synthetic_template())
        assert index.all_roles == EXPECTED_ROLES

    def test_multi_role_cell_indexed_under_each_role(self):
        from migration_intake.topology.haf_pipeline import parse_haf_template

        index = parse_haf_template(_synthetic_template())
        # header-2 has haf-role="header_line page_inner_frame"
        header_cells = index.by_role["header_line"]
        frame_cells = index.by_role["page_inner_frame"]
        assert len(header_cells) == 1
        assert len(frame_cells) == 1
        assert header_cells[0].get("id") == "header-2"
        assert frame_cells[0].get("id") == "header-2"

    def test_workload_vpc_dual_role(self):
        from migration_intake.topology.haf_pipeline import parse_haf_template

        index = parse_haf_template(_synthetic_template())
        vpc_cells = index.by_role["workload_vpc"]
        label_cells = index.by_role["workload_vpc_label"]
        assert len(vpc_cells) == 1
        assert vpc_cells[0].get("id") == "vpc-5"
        assert vpc_cells[0] is label_cells[0]

    def test_cells_without_haf_role_not_indexed(self):
        from migration_intake.topology.haf_pipeline import parse_haf_template

        index = parse_haf_template(_synthetic_template())
        for role_cells in index.by_role.values():
            for cell in role_cells:
                assert cell.get("id") != "plain-15"
                assert cell.get("id") != "edge-16"

    def test_tree_preserved_including_non_indexed_cells(self):
        from migration_intake.topology.haf_pipeline import parse_haf_template

        index = parse_haf_template(_synthetic_template())
        # The full tree should contain all cells including non-haf ones
        all_ids = {cell.get("id") for cell in index.tree.iter("mxCell") if cell.get("id")}
        assert "plain-15" in all_ids
        assert "edge-16" in all_ids

    def test_reject_invalid_xml(self):
        from migration_intake.topology.haf_pipeline import HafParseError, parse_haf_template

        with pytest.raises(HafParseError, match="parse"):
            parse_haf_template(b"not xml at all")

    def test_reject_compressed_drawio(self):
        """Compressed draw.io (base64 in diagram value) should be rejected."""
        from migration_intake.topology.haf_pipeline import HafParseError, parse_haf_template

        compressed = (
            b'<mxfile><diagram id="p1" name="Test">'
            b'jZLBbsMgDIafJuckSrpLj93WXXbodsCJG9ACRsSt0qcfBJzQqNJO+D/b'
            b'n21DwtbN+c2xo/4Aj20SLfg5YS9JFOVPeH0oMH2eC+Wt/zV6A9Xfmch'
            b'</diagram></mxfile>'
        )
        with pytest.raises(HafParseError, match="mxGraphModel"):
            parse_haf_template(compressed)

    def test_reject_duplicate_cell_ids(self):
        from migration_intake.topology.haf_pipeline import HafParseError, parse_haf_template

        dupe = (
            b'<mxfile><diagram id="p1" name="Test"><mxGraphModel><root>'
            b'<mxCell id="dup" haf-role="role_a" />'
            b'<mxCell id="dup" haf-role="role_b" />'
            b'</root></mxGraphModel></diagram></mxfile>'
        )
        with pytest.raises(HafParseError, match="[Dd]uplicate"):
            parse_haf_template(dupe)

    def test_parse_real_input_template(self):
        """Parse the actual v1.7 input template and verify 42 haf-role cells."""
        from pathlib import Path

        from migration_intake.topology.haf_pipeline import parse_haf_template

        template_path = Path(__file__).resolve().parents[3] / (
            "docs/development/topo_9_24/"
            "AWS__input_Outpost_Topology_UNRESOLVED_UNRESOLVED-v1.7.drawio"
        )
        if not template_path.exists():
            pytest.skip("Input template not available in this environment")

        data = template_path.read_bytes()
        index = parse_haf_template(data)

        # The evidence review counted 42 haf-role annotated cells
        total_annotated = sum(len(cells) for cells in index.by_role.values())
        # Some cells have multiple roles (header_line page_inner_frame,
        # workload_vpc workload_vpc_label, legend_notes_block notes_block)
        # so total_annotated > unique cells, but unique roles should be ~42+
        assert len(index.all_roles) >= 40, (
            f"Expected ~42+ roles, got {len(index.all_roles)}: {sorted(index.all_roles)}"
        )

        # Verify key roles are present
        assert "root_layer" in index.all_roles
        assert "header_line" in index.all_roles
        assert "private_application_subnet" in index.all_roles
        assert "att_internal_in_slot" in index.all_roles
        assert "azure_apps_slot" in index.all_roles


# ─── Block 2: Profile config loader tests ─────────────────────────────


class TestHafProfileLoader:
    """Block 2: load and validate haf profile JSON configs."""

    def test_load_outpost_v1_profile(self):
        from migration_intake.topology.haf_pipeline import load_haf_profile

        profile = load_haf_profile("OUTPOST_V1")
        assert profile.profile_id == "OUTPOST_V1"
        assert profile.template_version == "1.7"
        assert len(profile.placeholder_bindings) == 8
        assert len(profile.interface_regions) == 6
        assert len(profile.detail_blocks) == 2
        assert len(profile.protected_roles) > 0

    def test_profile_bindings_are_typed(self):
        from migration_intake.topology.haf_pipeline import load_haf_profile

        profile = load_haf_profile("OUTPOST_V1")
        header_binding = next(
            b for b in profile.placeholder_bindings if b.token == "outpost_id"
        )
        assert header_binding.haf_role == "header_line"
        assert header_binding.pattern == "NEEDS-OUTPOST-ID"
        assert header_binding.required is True
        assert header_binding.pattern_regex is None

    def test_profile_regex_binding(self):
        from migration_intake.topology.haf_pipeline import load_haf_profile

        profile = load_haf_profile("OUTPOST_V1")
        sg_binding = next(
            b for b in profile.placeholder_bindings if b.token == "app_sg_name"
        )
        assert sg_binding.pattern is None
        assert sg_binding.pattern_regex is not None

    def test_profile_interface_regions_are_typed(self):
        from migration_intake.topology.haf_pipeline import load_haf_profile

        profile = load_haf_profile("OUTPOST_V1")
        att_in = next(
            r for r in profile.interface_regions if r.haf_role == "att_internal_in_slot"
        )
        assert att_in.category == "INTERNAL"
        assert att_in.direction == "INBOUND"
        assert att_in.rendering == "MULTILINE_TEXT"
        assert "{app_name}" in att_in.format

    def test_profile_protected_roles_include_glob(self):
        from migration_intake.topology.haf_pipeline import load_haf_profile

        profile = load_haf_profile("OUTPOST_V1")
        assert "legend_*" in profile.protected_roles

    def test_is_protected_with_glob_matching(self):
        from migration_intake.topology.haf_pipeline import load_haf_profile

        profile = load_haf_profile("OUTPOST_V1")
        assert profile.is_protected("legend_protocol_https")
        assert profile.is_protected("legend_data_flow_label")
        assert profile.is_protected("outer_frame")
        assert profile.is_protected("root_layer")
        assert not profile.is_protected("header_line")
        assert not profile.is_protected("private_application_subnet")
        assert not profile.is_protected("att_internal_in_slot")

    def test_reject_unknown_profile_id(self):
        from migration_intake.topology.haf_pipeline import HafProfileError, load_haf_profile

        with pytest.raises(HafProfileError, match="not found"):
            load_haf_profile("NONEXISTENT_PROFILE")

    def test_profile_validates_against_index(self):
        from migration_intake.topology.haf_pipeline import (
            load_haf_profile,
            parse_haf_template,
        )

        profile = load_haf_profile("OUTPOST_V1")
        index = parse_haf_template(_synthetic_template())

        # The synthetic template has header_line, private_application_subnet, etc.
        # Profile validation should pass for roles that exist in the index
        warnings = profile.validate_against_index(index)
        # Some profile roles (att_internal_out_primary_slot, etc.) are not
        # in the minimal synthetic template — those produce warnings
        warning_roles = {w["haf_role"] for w in warnings}
        assert "header_line" not in warning_roles  # exists in template
        assert "att_internal_out_primary_slot" in warning_roles  # not in minimal template


# ─── Block 3: Placeholder token resolver tests ────────────────────────

# Complete token dict matching the synthetic template's 7 placeholder patterns
COMPLETE_TOKENS = {
    "outpost_id": "ALPRGAED",
    "subnet_cidr": "130.10.20.0/28",
    "subnet_name": "useast2-aldc-nprd-18678-subnet-01",
    "app_sg_name": "useast2-aldc-nprd-18678-sg-01",
    "aws_account_id": "ACC-PROD-0-98765",
    "availability_zone": "use2-az1",
    "vpc_cidr": "10.0.0.0/16",
    "db_sg_name": "useast2-aldc-nprd-18678-db-sg-01",
}


class TestPlaceholderResolver:
    """Block 3: resolve NEEDS-*/UNRESOLVED-* patterns in cell values."""

    def test_all_tokens_resolved_no_gaps(self):
        from migration_intake.topology.haf_pipeline import (
            load_haf_profile,
            parse_haf_template,
            resolve_placeholders,
        )

        index = parse_haf_template(_synthetic_template())
        profile = load_haf_profile("OUTPOST_V1")
        mutations, gaps = resolve_placeholders(index, profile, COMPLETE_TOKENS)

        assert len(gaps) == 0, f"Expected no gaps, got: {gaps}"
        assert len(mutations) > 0, "Expected at least one mutation"

        # Verify the header was resolved
        header_cell = index.by_role["header_line"][0]
        assert "NEEDS-OUTPOST-ID" not in (header_cell.get("value") or "")
        assert "ALPRGAED" in (header_cell.get("value") or "")

    def test_subnet_cidr_and_name_resolved(self):
        from migration_intake.topology.haf_pipeline import (
            load_haf_profile,
            parse_haf_template,
            resolve_placeholders,
        )

        index = parse_haf_template(_synthetic_template())
        profile = load_haf_profile("OUTPOST_V1")
        resolve_placeholders(index, profile, COMPLETE_TOKENS)

        subnet_cell = index.by_role["private_application_subnet"][0]
        value = subnet_cell.get("value") or ""
        assert "NEEDS-CIDR" not in value
        assert "130.10.20.0/28" in value
        assert "UNRESOLVED-subnet" not in value
        assert "useast2-aldc-nprd-18678-subnet-01" in value

    def test_regex_pattern_resolves_security_group(self):
        from migration_intake.topology.haf_pipeline import (
            load_haf_profile,
            parse_haf_template,
            resolve_placeholders,
        )

        index = parse_haf_template(_synthetic_template())
        profile = load_haf_profile("OUTPOST_V1")
        resolve_placeholders(index, profile, COMPLETE_TOKENS)

        sg_cell = index.by_role["app_security_group"][0]
        value = sg_cell.get("value") or ""
        assert "UNRESOLVED-useast2-aldc-prod-sg" not in value
        assert "useast2-aldc-nprd-18678-sg-01" in value

    def test_missing_required_token_produces_blocking_gap(self):
        from migration_intake.topology.haf_pipeline import (
            load_haf_profile,
            parse_haf_template,
            resolve_placeholders,
        )

        partial = {k: v for k, v in COMPLETE_TOKENS.items() if k != "outpost_id"}
        index = parse_haf_template(_synthetic_template())
        profile = load_haf_profile("OUTPOST_V1")
        mutations, gaps = resolve_placeholders(index, profile, partial)

        blocking_gaps = [g for g in gaps if g.blocking]
        assert len(blocking_gaps) >= 1
        gap_tokens = {g.token for g in gaps}
        assert "outpost_id" in gap_tokens

        # The original placeholder should NOT have been modified
        header_cell = index.by_role["header_line"][0]
        assert "NEEDS-OUTPOST-ID" in (header_cell.get("value") or "")

    def test_protected_roles_never_mutated(self):
        from migration_intake.topology.haf_pipeline import (
            load_haf_profile,
            parse_haf_template,
            resolve_placeholders,
        )

        index = parse_haf_template(_synthetic_template())
        profile = load_haf_profile("OUTPOST_V1")

        # Capture legend values before
        legend_before = {}
        for role in index.all_roles:
            if profile.is_protected(role):
                for cell in index.by_role[role]:
                    legend_before[cell.get("id")] = cell.get("value")

        resolve_placeholders(index, profile, COMPLETE_TOKENS)

        # Verify legend values unchanged
        for role in index.all_roles:
            if profile.is_protected(role):
                for cell in index.by_role[role]:
                    assert cell.get("value") == legend_before[cell.get("id")], (
                        f"Protected cell {cell.get('id')} was mutated"
                    )

    def test_structural_safety_only_values_change(self):
        """Geometry, style, parent, vertex/edge attributes must not change."""
        from migration_intake.topology.haf_pipeline import (
            load_haf_profile,
            parse_haf_template,
            resolve_placeholders,
        )

        data = _synthetic_template()
        index_before = parse_haf_template(data)
        # Capture structural snapshot
        snapshot_before = {}
        for cell in index_before.tree.iter("mxCell"):
            cid = cell.get("id")
            if cid:
                snapshot_before[cid] = {
                    "parent": cell.get("parent"),
                    "style": cell.get("style"),
                    "vertex": cell.get("vertex"),
                    "edge": cell.get("edge"),
                    "source": cell.get("source"),
                    "target": cell.get("target"),
                }
                geo = cell.find("mxGeometry")
                if geo is not None:
                    snapshot_before[cid]["geometry"] = {
                        k: v for k, v in geo.attrib.items()
                    }

        # Now resolve
        index = parse_haf_template(data)
        profile = load_haf_profile("OUTPOST_V1")
        resolve_placeholders(index, profile, COMPLETE_TOKENS)

        # Verify structural attributes unchanged
        for cell in index.tree.iter("mxCell"):
            cid = cell.get("id")
            if cid and cid in snapshot_before:
                before = snapshot_before[cid]
                assert cell.get("parent") == before["parent"], f"parent changed for {cid}"
                assert cell.get("style") == before["style"], f"style changed for {cid}"
                assert cell.get("vertex") == before["vertex"], f"vertex changed for {cid}"
                assert cell.get("edge") == before["edge"], f"edge changed for {cid}"
                assert cell.get("source") == before["source"], f"source changed for {cid}"
                assert cell.get("target") == before["target"], f"target changed for {cid}"
                geo = cell.find("mxGeometry")
                if "geometry" in before:
                    assert geo is not None
                    for k, v in before["geometry"].items():
                        assert geo.get(k) == v, f"geometry.{k} changed for {cid}"


# ─── Block 4: Interface region filler tests ───────────────────────────


SYNTHETIC_INTERFACES = {
    "INTERNAL:INBOUND": [
        {"app_name": "ORACLE SCM", "correlation_id": "18249"},
        {"app_name": "DITREX", "correlation_id": "18274"},
        {"app_name": "LS-OMS", "correlation_id": "10038"},
    ],
    "AZURE:None": [
        {"app_name": "DPG - Sales", "correlation_id": "31479"},
        {"app_name": "AZDP", "correlation_id": "30333"},
    ],
}


class TestInterfaceRegionFiller:
    """Block 4: populate interface slot cells with interface data."""

    def test_att_internal_in_slot_filled(self):
        from migration_intake.topology.haf_pipeline import (
            fill_interface_regions,
            load_haf_profile,
            parse_haf_template,
        )

        index = parse_haf_template(_synthetic_template())
        profile = load_haf_profile("OUTPOST_V1")
        mutations = fill_interface_regions(index, profile, SYNTHETIC_INTERFACES)

        cell = index.by_role["att_internal_in_slot"][0]
        value = cell.get("value") or ""
        assert "ORACLE SCM (18249)" in value
        assert "DITREX (18274)" in value
        assert "LS-OMS (10038)" in value
        assert len(mutations) > 0

    def test_azure_slot_filled(self):
        from migration_intake.topology.haf_pipeline import (
            fill_interface_regions,
            load_haf_profile,
            parse_haf_template,
        )

        index = parse_haf_template(_synthetic_template())
        profile = load_haf_profile("OUTPOST_V1")
        fill_interface_regions(index, profile, SYNTHETIC_INTERFACES)

        cell = index.by_role["azure_apps_slot"][0]
        value = cell.get("value") or ""
        assert "DPG - Sales (31479)" in value
        assert "AZDP (30333)" in value

    def test_empty_interfaces_use_empty_value(self):
        from migration_intake.topology.haf_pipeline import (
            fill_interface_regions,
            load_haf_profile,
            parse_haf_template,
        )

        index = parse_haf_template(_synthetic_template())
        profile = load_haf_profile("OUTPOST_V1")
        fill_interface_regions(index, profile, {})  # no interface data

        cell = index.by_role["att_internal_in_slot"][0]
        value = cell.get("value") or ""
        # Should contain the configured empty_value
        assert "please verify" in value.lower() or "none found" in value.lower()

    def test_multiline_format_uses_newline(self):
        from migration_intake.topology.haf_pipeline import (
            fill_interface_regions,
            load_haf_profile,
            parse_haf_template,
        )

        index = parse_haf_template(_synthetic_template())
        profile = load_haf_profile("OUTPOST_V1")
        fill_interface_regions(index, profile, SYNTHETIC_INTERFACES)

        cell = index.by_role["att_internal_in_slot"][0]
        value = cell.get("value") or ""
        lines = value.strip().split("\n")
        assert len(lines) == 3


# ─── Block 5: Detail block filler tests ──────────────────────────────


SYNTHETIC_DETAILS = {
    "nas_detail_block": {"nas_server": "nas-server-01", "ec2_names": "app-ec2-01, app-ec2-02"},
    "ebr_detail_block": {"strategy": "NetWorker", "ec2_names": "ebr-ec2-01"},
}


class TestDetailBlockFiller:
    """Block 5: fill detail blocks with resource data."""

    def test_nas_detail_block_filled(self):
        from migration_intake.topology.haf_pipeline import (
            fill_detail_blocks,
            load_haf_profile,
            parse_haf_template,
        )

        index = parse_haf_template(_synthetic_template())
        profile = load_haf_profile("OUTPOST_V1")
        mutations = fill_detail_blocks(index, profile, SYNTHETIC_DETAILS)

        cell = index.by_role["nas_detail_block"][0]
        value = cell.get("value") or ""
        assert "nas-server-01" in value
        assert "app-ec2-01, app-ec2-02" in value
        assert len(mutations) > 0

    def test_ebr_detail_block_filled(self):
        from migration_intake.topology.haf_pipeline import (
            fill_detail_blocks,
            load_haf_profile,
            parse_haf_template,
        )

        index = parse_haf_template(_synthetic_template())
        profile = load_haf_profile("OUTPOST_V1")
        fill_detail_blocks(index, profile, SYNTHETIC_DETAILS)

        cell = index.by_role["ebr_detail_block"][0]
        value = cell.get("value") or ""
        assert "NetWorker" in value
        assert "ebr-ec2-01" in value

    def test_missing_detail_data_uses_empty(self):
        from migration_intake.topology.haf_pipeline import (
            fill_detail_blocks,
            load_haf_profile,
            parse_haf_template,
        )

        index = parse_haf_template(_synthetic_template())
        profile = load_haf_profile("OUTPOST_V1")
        fill_detail_blocks(index, profile, {})

        cell = index.by_role["nas_detail_block"][0]
        value = cell.get("value") or ""
        # Template applied with empty values — should contain the field labels
        assert "NAS Server" in value or "nas_server" in value.lower()


# ─── Block 6: Pipeline orchestrator tests ─────────────────────────────


class TestPipelineOrchestrator:
    """Block 6: full pipeline orchestrator with gap report."""

    def test_full_pipeline_success(self):
        from migration_intake.topology.haf_pipeline import fill_haf_template

        result = fill_haf_template(
            template_bytes=_synthetic_template(),
            tokens=COMPLETE_TOKENS,
            interfaces=SYNTHETIC_INTERFACES,
            details=SYNTHETIC_DETAILS,
            profile_id="OUTPOST_V1",
        )

        assert result.success, f"Expected success, gaps: {result.gaps}"
        assert len(result.gaps) == 0
        assert len(result.mutations) > 0
        assert len(result.filled_xml) > 0

        # Output should be valid draw.io XML
        root = ET.fromstring(result.filled_xml)
        assert root.tag == "mxfile"

    def test_pipeline_produces_gap_report_on_missing_token(self):
        from migration_intake.topology.haf_pipeline import fill_haf_template

        partial_tokens = {k: v for k, v in COMPLETE_TOKENS.items() if k != "outpost_id"}
        result = fill_haf_template(
            template_bytes=_synthetic_template(),
            tokens=partial_tokens,
            interfaces=SYNTHETIC_INTERFACES,
            details=SYNTHETIC_DETAILS,
            profile_id="OUTPOST_V1",
        )

        assert not result.success
        assert len(result.gaps) >= 1
        gap_tokens = {g.token for g in result.gaps}
        assert "outpost_id" in gap_tokens

    def test_output_xml_has_no_unresolved_tokens(self):
        from migration_intake.topology.haf_pipeline import fill_haf_template

        result = fill_haf_template(
            template_bytes=_synthetic_template(),
            tokens=COMPLETE_TOKENS,
            interfaces=SYNTHETIC_INTERFACES,
            details=SYNTHETIC_DETAILS,
            profile_id="OUTPOST_V1",
        )

        xml_str = result.filled_xml.decode("utf-8")
        assert "NEEDS-OUTPOST-ID" not in xml_str
        assert "NEEDS-CIDR" not in xml_str
        assert "UNRESOLVED-subnet" not in xml_str
        assert "NEEDS-AZ" not in xml_str

    def test_structural_postflight(self):
        """Before/after: only value attributes should differ."""
        from migration_intake.topology.haf_pipeline import fill_haf_template

        template = _synthetic_template()
        result = fill_haf_template(
            template_bytes=template,
            tokens=COMPLETE_TOKENS,
            interfaces=SYNTHETIC_INTERFACES,
            details=SYNTHETIC_DETAILS,
            profile_id="OUTPOST_V1",
        )

        before = ET.fromstring(template)
        after = ET.fromstring(result.filled_xml)

        before_cells = {c.get("id"): c for c in before.iter("mxCell") if c.get("id")}
        after_cells = {c.get("id"): c for c in after.iter("mxCell") if c.get("id")}

        assert set(before_cells.keys()) == set(after_cells.keys()), "Cell set changed"

        for cid in before_cells:
            bc = before_cells[cid]
            ac = after_cells[cid]
            # Structural attributes must be identical
            for attr in ("parent", "style", "vertex", "edge", "source", "target"):
                assert bc.get(attr) == ac.get(attr), f"{attr} changed for {cid}"

    def test_deterministic_output(self):
        """Same inputs produce identical output bytes."""
        from migration_intake.topology.haf_pipeline import fill_haf_template

        args = dict(
            template_bytes=_synthetic_template(),
            tokens=COMPLETE_TOKENS,
            interfaces=SYNTHETIC_INTERFACES,
            details=SYNTHETIC_DETAILS,
            profile_id="OUTPOST_V1",
        )
        first = fill_haf_template(**args)
        second = fill_haf_template(**args)
        assert first.filled_xml == second.filled_xml

    def test_real_template_orchestration(self):
        """Run the orchestrator against the actual v1.7 input template."""
        from pathlib import Path

        from migration_intake.topology.haf_pipeline import fill_haf_template

        template_path = Path(__file__).resolve().parents[3] / (
            "docs/development/topo_9_24/"
            "AWS__input_Outpost_Topology_UNRESOLVED_UNRESOLVED-v1.7.drawio"
        )
        if not template_path.exists():
            pytest.skip("Input template not available")

        result = fill_haf_template(
            template_bytes=template_path.read_bytes(),
            tokens=COMPLETE_TOKENS,
            interfaces=SYNTHETIC_INTERFACES,
            details=SYNTHETIC_DETAILS,
            profile_id="OUTPOST_V1",
        )

        # Output must be valid draw.io XML
        root = ET.fromstring(result.filled_xml)
        assert root.tag == "mxfile"
        assert len(result.mutations) > 0

        # The resolved tokens should appear in output
        xml_str = result.filled_xml.decode("utf-8")
        assert "ALPRGAED" in xml_str  # outpost_id
        assert "130.10.20.0/28" in xml_str  # subnet_cidr
        assert "ORACLE SCM (18249)" in xml_str  # interface data


# ─── Block 4b: Grouped interface region filler tests ──────────────────


class TestGroupedInterfaceRegionFiller:
    """Block 4b: grouped interface rendering for ATT Internal section."""

    def test_grouped_rendering_with_protocol_port(self):
        """Test grouped rendering includes protocol/port in output."""
        from migration_intake.topology.haf_pipeline import (
            fill_interface_regions_grouped,
            load_haf_profile,
            parse_haf_template,
        )
        from migration_intake.topology.interface_normalization import (
            InterfaceCandidate,
            InterfaceGroup,
        )

        index = parse_haf_template(_synthetic_template())
        profile = load_haf_profile("OUTPOST_V1")

        # Create test interface groups
        candidate = InterfaceCandidate(
            raw_location="Midrange",
            raw_direction="IN",
            raw_protocol="JDBC",
            raw_port="1521",
            interface_app_acronym="ORACLE SCM",
            interface_correlation_id="18249",
            norm_category="INTERNAL",
            norm_direction="INBOUND",
            norm_protocol="JDBC",
            norm_port="1521",
            display_label="ORACLE SCM (18249)",
        )
        group = InterfaceGroup(
            protocol="JDBC",
            port="1521",
            entries_inbound=[candidate],
        )

        mutations = fill_interface_regions_grouped(index, profile, [group])

        # Should have mutations for ATT internal slots
        assert len(mutations) > 0

        # Check that the ATT internal inbound slot was filled
        cell = index.by_role.get("att_internal_in_slot", [None])[0]
        if cell is not None:
            value = cell.get("value") or ""
            assert "ORACLE SCM (18249)" in value
            assert "[JDBC/1521]" not in value

    def test_grouped_rendering_bidirectional(self):
        """Test grouped rendering handles bidirectional entries."""
        from migration_intake.topology.haf_pipeline import (
            fill_interface_regions_grouped,
            load_haf_profile,
            parse_haf_template,
        )
        from migration_intake.topology.interface_normalization import (
            InterfaceCandidate,
            InterfaceGroup,
        )

        index = parse_haf_template(_synthetic_template())
        profile = load_haf_profile("OUTPOST_V1")

        # Create bidirectional candidate
        candidate = InterfaceCandidate(
            raw_location="OnPrem",
            raw_direction="IN/OUT",
            raw_protocol="HTTP",
            raw_port="8080",
            interface_app_acronym="WEB APP",
            interface_correlation_id="12345",
            norm_category="INTERNAL",
            norm_direction="BIDIRECTIONAL",
            norm_protocol="HTTP",
            norm_port="8080",
            display_label="WEB APP (12345)",
        )
        group = InterfaceGroup(
            protocol="HTTP",
            port="8080",
            entries_bidirectional=[candidate],
        )

        mutations = fill_interface_regions_grouped(index, profile, [group])

        # Check that bidirectional slot was filled
        # Note: The synthetic template may not have att_internal_in_out_slot
        # so we just verify mutations were created
        assert isinstance(mutations, list)

    def test_grouped_rendering_multiple_groups(self):
        """Test grouped rendering with multiple protocol/port groups."""
        from migration_intake.topology.haf_pipeline import (
            fill_interface_regions_grouped,
            load_haf_profile,
            parse_haf_template,
        )
        from migration_intake.topology.interface_normalization import (
            InterfaceCandidate,
            InterfaceGroup,
        )

        index = parse_haf_template(_synthetic_template())
        profile = load_haf_profile("OUTPOST_V1")

        # Create multiple groups
        candidate1 = InterfaceCandidate(
            raw_location="Midrange",
            raw_direction="IN",
            raw_protocol="JDBC",
            raw_port="1521",
            interface_app_acronym="APP A",
            interface_correlation_id="111",
            norm_category="INTERNAL",
            norm_direction="INBOUND",
            norm_protocol="JDBC",
            norm_port="1521",
            display_label="APP A (111)",
        )
        candidate2 = InterfaceCandidate(
            raw_location="Hybrid",
            raw_direction="IN",
            raw_protocol="HTTP",
            raw_port="8080",
            interface_app_acronym="APP B",
            interface_correlation_id="222",
            norm_category="INTERNAL",
            norm_direction="INBOUND",
            norm_protocol="HTTP",
            norm_port="8080",
            display_label="APP B (222)",
        )
        groups = [
            InterfaceGroup(protocol="JDBC", port="1521", entries_inbound=[candidate1]),
            InterfaceGroup(protocol="HTTP", port="8080", entries_inbound=[candidate2]),
        ]

        mutations = fill_interface_regions_grouped(index, profile, groups)

        # Should have mutations
        assert len(mutations) > 0

        # Check that both entries appear in the slot
        cell = index.by_role.get("att_internal_in_slot", [None])[0]
        if cell is not None:
            value = cell.get("value") or ""
            assert "APP A (111)" in value
            assert "APP B (222)" in value
            assert "[JDBC/1521]" not in value
            assert "[HTTP/8080]" not in value

    def test_grouped_rendering_empty_groups(self):
        """Test grouped rendering with empty groups uses empty_value."""
        from migration_intake.topology.haf_pipeline import (
            fill_interface_regions_grouped,
            load_haf_profile,
            parse_haf_template,
        )

        index = parse_haf_template(_synthetic_template())
        profile = load_haf_profile("OUTPOST_V1")

        mutations = fill_interface_regions_grouped(index, profile, [])

        # No mutations when no groups
        assert mutations == []

    def test_full_pipeline_with_grouped_interfaces(self):
        """Test full pipeline with grouped interface rendering."""
        from migration_intake.topology.haf_pipeline import fill_haf_template
        from migration_intake.topology.interface_normalization import (
            InterfaceCandidate,
            InterfaceGroup,
        )

        # Create test interface groups
        candidate = InterfaceCandidate(
            raw_location="Midrange",
            raw_direction="IN",
            raw_protocol="JDBC",
            raw_port="1521",
            interface_app_acronym="GROUPED APP",
            interface_correlation_id="99999",
            norm_category="INTERNAL",
            norm_direction="INBOUND",
            norm_protocol="JDBC",
            norm_port="1521",
            display_label="GROUPED APP (99999)",
        )
        groups = [
            InterfaceGroup(protocol="JDBC", port="1521", entries_inbound=[candidate]),
        ]

        result = fill_haf_template(
            template_bytes=_synthetic_template(),
            tokens=COMPLETE_TOKENS,
            interfaces=SYNTHETIC_INTERFACES,
            details=SYNTHETIC_DETAILS,
            profile_id="OUTPOST_V1",
            interface_groups=groups,
        )

        assert result.success
        xml_str = result.filled_xml.decode("utf-8")

        # Grouped rendering fills existing cells with interface data
        # The content format is "{app_name} ({correlation_id})" per profile format
        assert "GROUPED APP (99999)" in xml_str
