"""Multi-app stress tests for topology pipeline scalability.

Validates that the normalization, grouping, and rendering pipeline handles
diverse application profiles correctly — from zero interfaces to maximum
group counts. All data is synthetic. No client data is used.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from migration_intake.topology.att_internal_generator import (
    generate_att_internal_rows,
)
from migration_intake.topology.interface_normalization import (
    InterfaceCandidate,
    ProtocolFamilyGroup,
    create_interface_candidate,
    group_interfaces_by_protocol_family,
    normalize_location,
    normalize_protocol_family,
)


def _candidate(
    *,
    app: str = "APP",
    corr: str = "100",
    location: str = "Midrange",
    direction: str = "Inbound",
    protocol: str = "HTTPS(TLSv1.2)",
    port: str = "443",
) -> InterfaceCandidate:
    return create_interface_candidate(
        interface_system_location=location,
        data_traffic_direction=direction,
        target_protocol=protocol,
        future_port=port,
        interface_app_acronym=app,
        interface_correlation_id=corr,
    )


def _minimal_template() -> ET.ElementTree:
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


class TestZeroInterfaces:
    """App with no interfaces: no crash, no generated rows."""

    def test_empty_candidates_produces_no_groups(self):
        groups = group_interfaces_by_protocol_family([])
        assert groups == []

    def test_generator_with_empty_groups(self):
        tree = _minimal_template()
        result = generate_att_internal_rows(tree, [])
        assert result.rows_generated == 0
        assert result.elements_created == []


class TestUnknownLocationHandling:
    """Interfaces with unrecognized locations go to UNKNOWN category."""

    def test_unrecognized_location_mapped_to_unknown(self):
        assert normalize_location("Alpha Centauri") == "UNKNOWN"

    def test_unknown_location_excluded_from_internal_groups(self):
        candidates = [
            _candidate(location="Alpha Centauri", app="APP1", corr="1"),
            _candidate(location="Midrange", app="APP2", corr="2"),
        ]
        groups = group_interfaces_by_protocol_family(candidates, category_filter="INTERNAL")
        # Only APP2 (Midrange -> INTERNAL) should appear
        all_labels = []
        for g in groups:
            all_labels.extend(g.labels)
        assert any("APP2" in lbl for lbl in all_labels)
        assert not any("APP1" in lbl for lbl in all_labels)


class TestUnknownProtocolHandling:
    """Interfaces with unrecognized protocols go to OTHER family."""

    def test_unrecognized_protocol_returns_other(self):
        assert normalize_protocol_family("Proprietary Widget Protocol") == "OTHER"

    def test_other_family_grouped_separately(self):
        candidates = [
            _candidate(protocol="HTTPS(TLSv1.2)", app="A", corr="1"),
            _candidate(protocol="Proprietary Widget", app="B", corr="2", port="9999"),
        ]
        groups = group_interfaces_by_protocol_family(candidates)
        families = [g.family for g in groups]
        assert "HTTPS" in families
        assert "OTHER" in families


class TestLargeGroupLabels:
    """App with 50 interfaces in one family: labels comma-separated."""

    def test_50_interfaces_per_family(self):
        candidates = [
            _candidate(app=f"APP{i:03d}", corr=str(10000 + i))
            for i in range(50)
        ]
        groups = group_interfaces_by_protocol_family(candidates)
        assert len(groups) == 1
        g = groups[0]
        assert len(g.labels) == 50
        # All labels present
        assert "APP000 (10000)" in g.labels
        assert "APP049 (10049)" in g.labels


class TestAllProtocolFamilies:
    """App with one interface per known family: all families generated."""

    FAMILIES = [
        ("HTTPS(TLSv1.2)", "443", "HTTPS"),
        ("JDBC over TLS", "1521", "ORACLE_DB"),
        ("Oracle GoldenGate", "7809", "ORACLE_GG"),
        ("ODBC(TCPS)", "1433", "SQL_DB"),
        ("SFTP using OpenSSH", "22", "SFTP"),
        ("SMTP over TLS", "25", "SMTP"),
        ("Connect:Direct Secure+", "1364", "CONNECT_DIRECT"),
        ("AMQP 1.0 over TLS", "5672", "AMQP"),
        ("PostgreSQL SSL", "5432", "POSTGRESQL"),
        ("DataGuard over TLS", "1521", "DATAGUARD"),
    ]

    def test_all_families_produce_groups(self):
        candidates = [
            _candidate(
                app=f"FAM-{family}",
                corr=str(idx),
                protocol=proto,
                port=port,
            )
            for idx, (proto, port, family) in enumerate(self.FAMILIES)
        ]
        groups = group_interfaces_by_protocol_family(candidates)
        result_families = {g.family for g in groups}
        expected = {f for _, _, f in self.FAMILIES}
        assert expected == result_families

    def test_all_families_render_without_crash(self):
        candidates = [
            _candidate(
                app=f"FAM-{family}",
                corr=str(idx),
                protocol=proto,
                port=port,
            )
            for idx, (proto, port, family) in enumerate(self.FAMILIES)
        ]
        groups = group_interfaces_by_protocol_family(candidates)
        tree = _minimal_template()
        result = generate_att_internal_rows(tree, groups)
        assert result.rows_generated == len(self.FAMILIES)


class TestMissingProtocolAndPort:
    """Interfaces with empty protocol/port go to UNKNOWN group."""

    def test_missing_protocol_goes_to_unknown(self):
        candidates = [
            _candidate(protocol="", port="", app="ORPHAN", corr="999"),
        ]
        groups = group_interfaces_by_protocol_family(candidates)
        assert len(groups) == 1
        assert groups[0].family == "UNKNOWN"

    def test_missing_port_goes_to_unknown(self):
        candidates = [
            _candidate(protocol="HTTPS", port="", app="NO-PORT", corr="888"),
        ]
        groups = group_interfaces_by_protocol_family(candidates)
        assert len(groups) == 1
        assert groups[0].family == "UNKNOWN"

    def test_unknown_group_has_question_marks(self):
        candidates = [
            _candidate(protocol="", port="", app="ORPHAN", corr="999"),
        ]
        groups = group_interfaces_by_protocol_family(candidates)
        g = groups[0]
        assert g.port_display == "?"


class TestDeterministicOutput:
    """Same inputs must produce identical outputs across multiple runs."""

    def test_grouping_deterministic(self):
        candidates = [
            _candidate(app="B", corr="2", protocol="SFTP", port="22"),
            _candidate(app="A", corr="1", protocol="HTTPS", port="443"),
            _candidate(app="C", corr="3", protocol="SFTP", port="22"),
        ]
        run1 = group_interfaces_by_protocol_family(candidates)
        run2 = group_interfaces_by_protocol_family(candidates)
        assert [g.family for g in run1] == [g.family for g in run2]
        assert [g.labels for g in run1] == [g.labels for g in run2]

    def test_generator_deterministic(self):
        candidates = [
            _candidate(app="X", corr="10", protocol="HTTPS", port="443"),
            _candidate(app="Y", corr="20", protocol="SFTP", port="22"),
        ]
        groups = group_interfaces_by_protocol_family(candidates)

        tree1 = _minimal_template()
        r1 = generate_att_internal_rows(tree1, groups)
        xml1 = ET.tostring(tree1.getroot(), encoding="unicode")

        tree2 = _minimal_template()
        r2 = generate_att_internal_rows(tree2, groups)
        xml2 = ET.tostring(tree2.getroot(), encoding="unicode")

        assert xml1 == xml2


class TestNoCcpmDataLeaks:
    """Generated output must never contain CCPM-specific app data."""

    CCPM_IDENTIFIERS = [
        "18249", "18274", "10038", "19166", "30358", "15977",
        "ORACLE SCM", "DITREX", "LS-OMS", "MyTracker", "ImE FLEX",
    ]

    def test_generated_xml_contains_no_ccpm_data(self):
        candidates = [
            _candidate(app="SYNTH-A", corr="99901"),
            _candidate(app="SYNTH-B", corr="99902", protocol="SFTP", port="22"),
        ]
        groups = group_interfaces_by_protocol_family(candidates)
        tree = _minimal_template()
        generate_att_internal_rows(tree, groups)
        xml_str = ET.tostring(tree.getroot(), encoding="unicode")
        for identifier in self.CCPM_IDENTIFIERS:
            assert identifier not in xml_str, (
                f"Generated XML leaks CCPM data: '{identifier}'"
            )


class TestCategoryFiltering:
    """Grouping correctly filters by category."""

    def test_aws_category_filter(self):
        candidates = [
            _candidate(location="AWS", app="AWS-A", corr="1"),
            _candidate(location="Midrange", app="INT-B", corr="2"),
        ]
        aws_groups = group_interfaces_by_protocol_family(candidates, category_filter="AWS")
        assert len(aws_groups) == 1
        assert any("AWS-A" in lbl for lbl in aws_groups[0].labels)

    def test_internal_filter_excludes_aws(self):
        candidates = [
            _candidate(location="AWS", app="AWS-A", corr="1"),
            _candidate(location="Midrange", app="INT-B", corr="2"),
        ]
        int_groups = group_interfaces_by_protocol_family(candidates, category_filter="INTERNAL")
        all_labels = [lbl for g in int_groups for lbl in g.labels]
        assert not any("AWS-A" in lbl for lbl in all_labels)
        assert any("INT-B" in lbl for lbl in all_labels)

    def test_no_filter_includes_all(self):
        candidates = [
            _candidate(location="AWS", app="AWS-A", corr="1"),
            _candidate(location="Midrange", app="INT-B", corr="2"),
        ]
        groups = group_interfaces_by_protocol_family(candidates, category_filter=None)
        all_labels = [lbl for g in groups for lbl in g.labels]
        assert any("AWS-A" in lbl for lbl in all_labels)
        assert any("INT-B" in lbl for lbl in all_labels)
