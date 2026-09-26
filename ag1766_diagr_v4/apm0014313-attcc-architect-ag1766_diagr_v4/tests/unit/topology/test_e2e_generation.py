"""E2E generation test — verifies the complete pipeline produces valid output.

Uses the bundled annotated template with synthetic CCPM-like data and
validates the output structurally.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET

import pytest

from migration_intake.topology.haf_pipeline import fill_haf_template
from migration_intake.topology.interface_normalization import (
    create_interface_candidate,
    group_interfaces_by_protocol_family,
)
from migration_intake.topology.template_loader import load_bundled_template


def _build_synthetic_data() -> dict:
    """Build synthetic CCPM-like data for the pipeline."""
    tokens = {
        "outpost_id": "op-0123456789abcdef0",
        "vpc_cidr": "10.0.0.0/16",
        "subnet_cidr": "130.10.20.0/28",
        "subnet_name": "private-app-subnet-1",
        "app_sg_name": "ccpm-app-sg",
        "aws_account_id": "123456789012",
        "availability_zone": "us-east-1a",
        "db_sg_name": "ccpm-db-sg",
    }

    candidates = [
        create_interface_candidate(
            interface_system_location="ATT", data_traffic_direction="Inbound",
            target_protocol="HTTPS(TLSv1.2)", future_port="443",
            interface_app_acronym="ORACLE SCM", interface_correlation_id="18249",
        ),
        create_interface_candidate(
            interface_system_location="ATT", data_traffic_direction="Inbound",
            target_protocol="JDBC over TLS 1.2", future_port="1521",
            interface_app_acronym="DITREX", interface_correlation_id="18274",
        ),
        create_interface_candidate(
            interface_system_location="Midrange", data_traffic_direction="Outbound",
            target_protocol="SFTP using OpenSSH", future_port="22",
            interface_app_acronym="LS-OMS", interface_correlation_id="10038",
        ),
        create_interface_candidate(
            interface_system_location="Azure", data_traffic_direction="Outbound",
            target_protocol="HTTPS(TLSv1.2)", future_port="443",
            interface_app_acronym="DPG Sales", interface_correlation_id="31479",
        ),
        create_interface_candidate(
            interface_system_location="AWS", data_traffic_direction="Inbound",
            target_protocol="HTTPS(TLSv1.2)", future_port="443",
            interface_app_acronym="DTV-VDAS", interface_correlation_id="32387",
        ),
    ]

    interface_groups = group_interfaces_by_protocol_family(
        candidates, category_filter="INTERNAL"
    )
    aws_interface_groups = group_interfaces_by_protocol_family(
        candidates,
        category_filter="AWS",
        direction_filter=frozenset({"INBOUND", "BIDIRECTIONAL"}),
    )

    interfaces: dict[str, list[dict]] = {}
    for c in candidates:
        key = f"{c.norm_category}:{c.norm_direction}"
        interfaces.setdefault(key, []).append({
            "app_name": c.interface_app_acronym or "",
            "correlation_id": c.interface_correlation_id or "",
        })

    return {
        "tokens": tokens,
        "interfaces": interfaces,
        "interface_groups": interface_groups,
        "aws_interface_groups": aws_interface_groups,
    }


class TestE2EBasicGeneration:
    """End-to-end: basic template generation with synthetic data."""

    @pytest.fixture()
    def result(self):
        data = _build_synthetic_data()
        template_bytes = load_bundled_template("basic")
        return fill_haf_template(
            template_bytes=template_bytes,
            tokens=data["tokens"],
            interfaces=data["interfaces"],
            details={},
            profile_id="OUTPOST_V1_BASIC",
            interface_groups=data["interface_groups"],
            aws_interface_groups=data["aws_interface_groups"],
        )

    def test_pipeline_succeeds(self, result) -> None:
        assert result.success is True

    def test_produces_valid_xml(self, result) -> None:
        root = ET.fromstring(result.filled_xml)
        assert root.tag == "mxfile"

    def test_has_mutations(self, result) -> None:
        assert len(result.mutations) > 0

    def test_no_gaps(self, result) -> None:
        assert len(result.gaps) == 0

    def test_interface_data_present(self, result) -> None:
        xml_str = result.filled_xml.decode("utf-8")
        # Pipeline populates interface names in the ATT Internal section
        assert "ORACLE SCM" in xml_str
        assert "DITREX" in xml_str

    def test_att_internal_interfaces_generated(self, result) -> None:
        root = ET.fromstring(result.filled_xml)
        gen_cells = [
            c for c in root.iter("mxCell")
            if (c.get("id", "").startswith("att_internal_gen_"))
        ]
        assert len(gen_cells) > 0

    def test_aws_tier1_interfaces_generated(self, result) -> None:
        root = ET.fromstring(result.filled_xml)
        gen_cells = [
            c for c in root.iter("mxCell")
            if (c.get("id", "").startswith("aws_tier1_gen_"))
        ]
        assert len(gen_cells) > 0

    def test_static_sections_preserved(self, result) -> None:
        xml_str = result.filled_xml.decode("utf-8")
        for section in ["GitHub Runners", "JFrog", "DNS PHZ",
                        "AWS Home Region", "SMTP"]:
            assert section in xml_str, f"Static section '{section}' missing"


class TestE2ETlgwGeneration:
    """End-to-end: tLGW template generation."""

    def test_pipeline_succeeds(self) -> None:
        data = _build_synthetic_data()
        template_bytes = load_bundled_template("tlgw")
        result = fill_haf_template(
            template_bytes=template_bytes,
            tokens=data["tokens"],
            interfaces=data["interfaces"],
            details={},
            profile_id="OUTPOST_V1_TLGW",
            interface_groups=data["interface_groups"],
            aws_interface_groups=data["aws_interface_groups"],
        )
        assert result.success is True
        assert len(result.mutations) > 0


class TestE2EF5Generation:
    """End-to-end: F5 template generation."""

    def test_pipeline_succeeds(self) -> None:
        data = _build_synthetic_data()
        template_bytes = load_bundled_template("f5")
        result = fill_haf_template(
            template_bytes=template_bytes,
            tokens=data["tokens"],
            interfaces=data["interfaces"],
            details={},
            profile_id="OUTPOST_V1_F5",
            interface_groups=data["interface_groups"],
            aws_interface_groups=data["aws_interface_groups"],
        )
        assert result.success is True
        assert len(result.mutations) > 0


class TestE2EHadrGeneration:
    """End-to-end: HA/DR template generation."""

    def test_pipeline_succeeds(self) -> None:
        data = _build_synthetic_data()
        template_bytes = load_bundled_template("hadr")
        result = fill_haf_template(
            template_bytes=template_bytes,
            tokens=data["tokens"],
            interfaces=data["interfaces"],
            details={},
            profile_id="OUTPOST_V1_HADR",
            interface_groups=data["interface_groups"],
            aws_interface_groups=data["aws_interface_groups"],
        )
        assert result.success is True
        assert len(result.mutations) > 0
