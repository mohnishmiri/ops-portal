"""Tests for annotated master template — haf-role coverage validation."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from migration_intake.topology.haf_pipeline import parse_haf_template
from migration_intake.topology.template_loader import extract_tab, list_tabs

_BUNDLED = (
    Path(__file__).resolve().parents[3]
    / "src"
    / "migration_intake"
    / "topology"
    / "config"
    / "templates"
    / "outpost_v1.7.drawio"
)


def _load_tab0() -> bytes:
    """Load Tab 0 ('Without LBs') from the bundled annotated template."""
    return extract_tab(_BUNDLED.read_bytes(), tab_name="Without LBs")


# ── Slice 2a: Bundled template exists ────────────────────────────────────


class TestBundledTemplateExists:
    """The bundled template must exist and contain 5 tabs."""

    def test_bundled_template_exists(self) -> None:
        assert _BUNDLED.exists(), f"Expected bundled template at {_BUNDLED}"

    def test_bundled_template_has_five_tabs(self) -> None:
        tabs = list_tabs(_BUNDLED.read_bytes())
        assert len(tabs) == 5

    def test_bundled_template_tab_names(self) -> None:
        tabs = list_tabs(_BUNDLED.read_bytes())
        names = [t["name"] for t in tabs]
        assert names == [
            "Without LBs",
            "tLGW Load Balancer",
            "F5 Load Balancer",
            "HA/DR with Global Load Balancer",
            "Definitions",
        ]


# ── Slice 2b: Structural roles ──────────────────────────────────────────


class TestTab0StructuralRoles:
    """Tab 0 must have all structural/layout haf-roles."""

    @pytest.fixture()
    def index(self) -> object:
        return parse_haf_template(_load_tab0())

    def test_root_layer(self, index: object) -> None:
        assert "root_layer" in index.all_roles

    def test_outer_frame(self, index: object) -> None:
        assert "outer_frame" in index.all_roles

    def test_header_line(self, index: object) -> None:
        assert "header_line" in index.all_roles

    def test_page_inner_frame(self, index: object) -> None:
        assert "page_inner_frame" in index.all_roles

    def test_app_account_container(self, index: object) -> None:
        assert "app_account_container" in index.all_roles

    def test_workload_vpc(self, index: object) -> None:
        assert "workload_vpc" in index.all_roles

    def test_workload_vpc_label(self, index: object) -> None:
        assert "workload_vpc_label" in index.all_roles

    def test_private_application_subnet(self, index: object) -> None:
        assert "private_application_subnet" in index.all_roles

    def test_app_security_group(self, index: object) -> None:
        assert "app_security_group" in index.all_roles

    def test_db_security_group(self, index: object) -> None:
        assert "db_security_group" in index.all_roles

    def test_network_account_container(self, index: object) -> None:
        assert "network_account_container" in index.all_roles

    def test_all_structural_roles_present(self, index: object) -> None:
        structural = {
            "root_layer",
            "outer_frame",
            "header_line",
            "page_inner_frame",
            "app_account_container",
            "workload_vpc",
            "workload_vpc_label",
            "private_application_subnet",
            "app_security_group",
            "db_security_group",
            "network_account_container",
        }
        missing = structural - index.all_roles
        assert not missing, f"Missing structural roles: {missing}"


# ── Slice 2c: Interface slots and generators ─────────────────────────────


class TestTab0InterfaceRoles:
    """Tab 0 must have ATT Internal, Azure, AWS Tier 1, and tier2 roles."""

    @pytest.fixture()
    def index(self) -> object:
        return parse_haf_template(_load_tab0())

    def test_att_internal_band(self, index: object) -> None:
        assert "att_internal_interfaces_band" in index.all_roles

    def test_att_internal_slots(self, index: object) -> None:
        slots = {
            "att_internal_in_slot",
            "att_internal_out_primary_slot",
            "att_internal_out_secondary_slot",
            "att_internal_in_out_slot",
        }
        missing = slots - index.all_roles
        assert not missing, f"Missing ATT Internal slots: {missing}"

    def test_azure_section_roles(self, index: object) -> None:
        azure = {
            "azure_apps_container",
            "azure_apps_label",
            "azure_apps_slot",
            "azure_apps_bridge_box",
            "azure_apps_bridge_label",
            "azure_apps_icon_express_route",
        }
        missing = azure - index.all_roles
        assert not missing, f"Missing Azure roles: {missing}"

    def test_aws_tier1_roles(self, index: object) -> None:
        tier1 = {"aws_tier1_container", "aws_tier1_bg", "aws_tier1_title"}
        missing = tier1 - index.all_roles
        assert not missing, f"Missing AWS Tier 1 roles: {missing}"

    def test_tier2_internet_slot(self, index: object) -> None:
        assert "tier2_internet_slot" in index.all_roles

    def test_cloudwatch(self, index: object) -> None:
        assert "cloudwatch" in index.all_roles

    def test_directconnect(self, index: object) -> None:
        assert "directconnect" in index.all_roles

    def test_dns_phz_container(self, index: object) -> None:
        assert "dns_phz_container" in index.all_roles


# ── Slice 2d: Legend and detail blocks ───────────────────────────────────


class TestTab0LegendRoles:
    """Tab 0 must have legend and detail block haf-roles."""

    @pytest.fixture()
    def index(self) -> object:
        return parse_haf_template(_load_tab0())

    def test_legend_data_flow(self, index: object) -> None:
        assert "legend_data_flow_label" in index.all_roles
        assert "legend_data_flow_block" in index.all_roles

    def test_legend_application_specific(self, index: object) -> None:
        assert "legend_application_specific" in index.all_roles

    def test_legend_github_block(self, index: object) -> None:
        assert "legend_github_block" in index.all_roles

    def test_legend_artifactory(self, index: object) -> None:
        assert "legend_artifactory_icon" in index.all_roles

    def test_notes_block(self, index: object) -> None:
        assert "notes_block" in index.all_roles

    def test_legend_protocol_colors(self, index: object) -> None:
        protocols = {
            "legend_protocol_https",
            "legend_protocol_ssh",
            "legend_protocol_sql",
            "legend_protocol_jdbc",
            "legend_protocol_multiple",
            "legend_protocol_smtp",
            "legend_protocol_dataguard",
            "legend_protocol_gg",
        }
        missing = protocols - index.all_roles
        assert not missing, f"Missing legend protocol roles: {missing}"

    def test_nas_detail_block(self, index: object) -> None:
        assert "nas_title_label" in index.all_roles
        assert "nas_detail_block" in index.all_roles

    def test_ebr_detail_block(self, index: object) -> None:
        assert "ebr_title_label" in index.all_roles
        assert "ebr_detail_block" in index.all_roles


# ── Slice 2e: Standard section roles (new) ───────────────────────────────


class TestTab0StandardSectionRoles:
    """Tab 0 must have roles for previously missing standard sections."""

    @pytest.fixture()
    def index(self) -> object:
        return parse_haf_template(_load_tab0())

    def test_vpce_bastion(self, index: object) -> None:
        assert "vpce_bastion_label" in index.all_roles

    def test_internet(self, index: object) -> None:
        assert "internet_label" in index.all_roles

    def test_aws_tier2(self, index: object) -> None:
        assert "aws_tier2_label" in index.all_roles

    def test_directconnect_icon(self, index: object) -> None:
        assert "directconnect_icon" in index.all_roles

    def test_all_standard_sections_present(self, index: object) -> None:
        standard = {
            "vpce_bastion_label",
            "internet_label",
            "aws_tier2_label",
            "directconnect_icon",
        }
        missing = standard - index.all_roles
        assert not missing, f"Missing standard section roles: {missing}"


# ── Slice 2f: Comprehensive validation ───────────────────────────────────


class TestTab0ComprehensiveValidation:
    """Every haf_role from outpost_v1.json must exist in Tab 0."""

    @pytest.fixture()
    def index(self) -> object:
        return parse_haf_template(_load_tab0())

    def test_profile_binding_roles_present(self, index: object) -> None:
        """All placeholder_bindings haf_roles must exist in Tab 0."""
        from migration_intake.topology.haf_pipeline import load_haf_profile

        profile = load_haf_profile("OUTPOST_V1")
        binding_roles = {b.haf_role for b in profile.placeholder_bindings}
        missing = binding_roles - index.all_roles
        assert not missing, f"Tab 0 missing binding roles: {missing}"

    def test_interface_region_roles_present(self, index: object) -> None:
        """All interface_regions haf_roles must exist in Tab 0."""
        from migration_intake.topology.haf_pipeline import load_haf_profile

        profile = load_haf_profile("OUTPOST_V1")
        region_roles = {r.haf_role for r in profile.interface_regions}
        missing = region_roles - index.all_roles
        assert not missing, f"Tab 0 missing interface region roles: {missing}"

    def test_detail_block_roles_present(self, index: object) -> None:
        """All detail_blocks haf_roles must exist in Tab 0."""
        from migration_intake.topology.haf_pipeline import load_haf_profile

        profile = load_haf_profile("OUTPOST_V1")
        detail_roles = {d.haf_role for d in profile.detail_blocks}
        missing = detail_roles - index.all_roles
        assert not missing, f"Tab 0 missing detail block roles: {missing}"

    def test_minimum_role_count(self, index: object) -> None:
        """Tab 0 must have at least 40 unique roles."""
        assert len(index.all_roles) >= 40, (
            f"Expected ≥40 roles, found {len(index.all_roles)}: {sorted(index.all_roles)}"
        )


# ── Slice 3: Per-Variant Profile ─────────────────────────────────────────


class TestBasicProfile:
    """OUTPOST_V1_BASIC profile must load and validate against Tab 0."""

    def test_load_basic_profile(self) -> None:
        from migration_intake.topology.haf_pipeline import load_haf_profile

        profile = load_haf_profile("OUTPOST_V1_BASIC")
        assert profile.profile_id == "OUTPOST_V1_BASIC"

    def test_basic_profile_has_same_bindings_as_legacy(self) -> None:
        from migration_intake.topology.haf_pipeline import load_haf_profile

        legacy = load_haf_profile("OUTPOST_V1")
        basic = load_haf_profile("OUTPOST_V1_BASIC")
        legacy_roles = {b.haf_role for b in legacy.placeholder_bindings}
        basic_roles = {b.haf_role for b in basic.placeholder_bindings}
        assert legacy_roles == basic_roles

    def test_basic_profile_has_new_protected_roles(self) -> None:
        from migration_intake.topology.haf_pipeline import load_haf_profile

        profile = load_haf_profile("OUTPOST_V1_BASIC")
        new_roles = {"vpce_bastion_label", "internet_label", "aws_tier2_label",
                     "directconnect_icon", "aws_tier1_bg", "aws_tier1_title"}
        for role in new_roles:
            assert role in profile.protected_roles, f"Missing protected role: {role}"

    def test_basic_profile_resolves_against_tab0(self) -> None:
        """Every binding role in the basic profile must exist in Tab 0."""
        from migration_intake.topology.haf_pipeline import load_haf_profile

        profile = load_haf_profile("OUTPOST_V1_BASIC")
        index = parse_haf_template(_load_tab0())
        binding_roles = {b.haf_role for b in profile.placeholder_bindings}
        missing = binding_roles - index.all_roles
        assert not missing, f"Basic profile bindings reference missing roles: {missing}"

    def test_basic_profile_interface_regions_resolve(self) -> None:
        from migration_intake.topology.haf_pipeline import load_haf_profile

        profile = load_haf_profile("OUTPOST_V1_BASIC")
        index = parse_haf_template(_load_tab0())
        region_roles = {r.haf_role for r in profile.interface_regions}
        missing = region_roles - index.all_roles
        assert not missing, f"Basic profile interface regions reference missing roles: {missing}"

    def test_basic_profile_detail_blocks_resolve(self) -> None:
        from migration_intake.topology.haf_pipeline import load_haf_profile

        profile = load_haf_profile("OUTPOST_V1_BASIC")
        index = parse_haf_template(_load_tab0())
        detail_roles = {d.haf_role for d in profile.detail_blocks}
        missing = detail_roles - index.all_roles
        assert not missing, f"Basic profile detail blocks reference missing roles: {missing}"


# ── Slice 4a: Tab 1 (tLGW Load Balancer) ────────────────────────────────

def _load_master() -> bytes:
    return _BUNDLED.read_bytes()


class TestTab1TlgwRoles:
    """Tab 1 must have base roles + tLGW-specific roles."""

    @pytest.fixture()
    def index(self) -> object:
        tab1 = extract_tab(_load_master(), tab_name="tLGW Load Balancer")
        return parse_haf_template(tab1)

    def test_has_base_roles(self, index: object) -> None:
        base = {"header_line", "app_account_container", "att_internal_interfaces_band",
                "workload_vpc", "private_application_subnet"}
        missing = base - index.all_roles
        assert not missing, f"Tab 1 missing base roles: {missing}"

    def test_has_web_eni_roles(self, index: object) -> None:
        assert "web_eni_1" in index.all_roles
        assert "web_eni_2" in index.all_roles
        assert "web_eni_3" in index.all_roles

    def test_has_standard_section_roles(self, index: object) -> None:
        standard = {"vpce_bastion_label", "internet_label", "aws_tier2_label",
                     "directconnect_icon"}
        missing = standard - index.all_roles
        assert not missing, f"Tab 1 missing standard sections: {missing}"


class TestTlgwProfile:
    """OUTPOST_V1_TLGW profile must load and validate."""

    def test_load_tlgw_profile(self) -> None:
        from migration_intake.topology.haf_pipeline import load_haf_profile

        profile = load_haf_profile("OUTPOST_V1_TLGW")
        assert profile.profile_id == "OUTPOST_V1_TLGW"

    def test_tlgw_profile_resolves_against_tab1(self) -> None:
        from migration_intake.topology.haf_pipeline import load_haf_profile

        profile = load_haf_profile("OUTPOST_V1_TLGW")
        tab1 = extract_tab(_load_master(), tab_name="tLGW Load Balancer")
        index = parse_haf_template(tab1)
        binding_roles = {b.haf_role for b in profile.placeholder_bindings}
        missing = binding_roles - index.all_roles
        assert not missing, f"tLGW profile bindings reference missing roles: {missing}"


# ── Slice 4b: Tab 2 (F5 Load Balancer) ──────────────────────────────────


class TestTab2F5Roles:
    """Tab 2 must have base roles + F5-specific roles."""

    @pytest.fixture()
    def index(self) -> object:
        tab2 = extract_tab(_load_master(), tab_name="F5 Load Balancer")
        return parse_haf_template(tab2)

    def test_has_base_roles(self, index: object) -> None:
        base = {"header_line", "app_account_container", "att_internal_interfaces_band",
                "workload_vpc", "private_application_subnet"}
        missing = base - index.all_roles
        assert not missing, f"Tab 2 missing base roles: {missing}"

    def test_has_f5_roles(self, index: object) -> None:
        assert "idns_icon" in index.all_roles
        assert "f5_eni" in index.all_roles

    def test_has_standard_section_roles(self, index: object) -> None:
        standard = {"vpce_bastion_label", "internet_label", "aws_tier2_label",
                     "directconnect_icon"}
        missing = standard - index.all_roles
        assert not missing, f"Tab 2 missing standard sections: {missing}"


class TestF5Profile:
    """OUTPOST_V1_F5 profile must load and validate."""

    def test_load_f5_profile(self) -> None:
        from migration_intake.topology.haf_pipeline import load_haf_profile

        profile = load_haf_profile("OUTPOST_V1_F5")
        assert profile.profile_id == "OUTPOST_V1_F5"

    def test_f5_profile_resolves_against_tab2(self) -> None:
        from migration_intake.topology.haf_pipeline import load_haf_profile

        profile = load_haf_profile("OUTPOST_V1_F5")
        tab2 = extract_tab(_load_master(), tab_name="F5 Load Balancer")
        index = parse_haf_template(tab2)
        binding_roles = {b.haf_role for b in profile.placeholder_bindings}
        missing = binding_roles - index.all_roles
        assert not missing, f"F5 profile bindings reference missing roles: {missing}"


# ── Slice 4c: Tab 3 (HA/DR with Global Load Balancer) ────────────────────


class TestTab3HadrRoles:
    """Tab 3 must have R1 + R2 roles."""

    @pytest.fixture()
    def index(self) -> object:
        tab3 = extract_tab(_load_master(), tab_name="HA/DR with Global Load Balancer")
        return parse_haf_template(tab3)

    def test_has_r1_base_roles(self, index: object) -> None:
        base = {"header_line", "app_account_container", "att_internal_interfaces_band",
                "workload_vpc", "private_application_subnet"}
        missing = base - index.all_roles
        assert not missing, f"Tab 3 missing R1 base roles: {missing}"

    def test_has_r2_roles(self, index: object) -> None:
        r2 = {"r2_header_line", "r2_app_account_container",
              "r2_att_internal_interfaces_band", "r2_workload_vpc",
              "r2_private_application_subnet"}
        missing = r2 - index.all_roles
        assert not missing, f"Tab 3 missing R2 roles: {missing}"

    def test_has_f5_roles(self, index: object) -> None:
        assert "idns_icon" in index.all_roles
        assert "f5_eni" in index.all_roles

    def test_has_idns_global(self, index: object) -> None:
        assert "idns_global_label" in index.all_roles


class TestHadrProfile:
    """OUTPOST_V1_HADR profile must load and validate."""

    def test_load_hadr_profile(self) -> None:
        from migration_intake.topology.haf_pipeline import load_haf_profile

        profile = load_haf_profile("OUTPOST_V1_HADR")
        assert profile.profile_id == "OUTPOST_V1_HADR"

    def test_hadr_profile_has_r2_interface_regions(self) -> None:
        from migration_intake.topology.haf_pipeline import load_haf_profile

        profile = load_haf_profile("OUTPOST_V1_HADR")
        region_roles = {r.haf_role for r in profile.interface_regions}
        r2_regions = {"r2_att_internal_in_slot", "r2_att_internal_out_primary_slot",
                      "r2_att_internal_out_secondary_slot", "r2_att_internal_in_out_slot"}
        missing = r2_regions - region_roles
        assert not missing, f"HA/DR profile missing R2 interface regions: {missing}"

    def test_hadr_profile_resolves_against_tab3(self) -> None:
        from migration_intake.topology.haf_pipeline import load_haf_profile

        profile = load_haf_profile("OUTPOST_V1_HADR")
        tab3 = extract_tab(_load_master(), tab_name="HA/DR with Global Load Balancer")
        index = parse_haf_template(tab3)
        binding_roles = {b.haf_role for b in profile.placeholder_bindings}
        missing = binding_roles - index.all_roles
        assert not missing, f"HA/DR profile bindings reference missing roles: {missing}"

    def test_hadr_profile_r2_detail_blocks_resolve(self) -> None:
        from migration_intake.topology.haf_pipeline import load_haf_profile

        profile = load_haf_profile("OUTPOST_V1_HADR")
        tab3 = extract_tab(_load_master(), tab_name="HA/DR with Global Load Balancer")
        index = parse_haf_template(tab3)
        detail_roles = {d.haf_role for d in profile.detail_blocks}
        missing = detail_roles - index.all_roles
        assert not missing, f"HA/DR detail blocks reference missing roles: {missing}"
