"""Protocol-family normalization and grouped rendering tests.

All data is synthetic. No client data is used.
Tests the protocol-family normalizer, ProtocolFamilyGroup view model,
and group_interfaces_by_protocol_family() grouping function.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from migration_intake.topology.interface_normalization import (
    FAMILY_COLORS,
    InterfaceCandidate,
    ProtocolFamilyGroup,
    create_interface_candidate,
    group_interfaces_by_protocol_family,
    normalize_location,
    normalize_protocol_family,
)


class TestProtocolFamilyNormalizer:
    """Slice 0: normalize_protocol_family() maps raw protocol strings to families."""

    # --- HTTPS family ---
    def test_https_with_tls_version(self):
        assert normalize_protocol_family("HTTPS(TLSv1.2)") == "HTTPS"

    def test_plain_http(self):
        assert normalize_protocol_family("HTTP") == "HTTPS"

    def test_https_lowercase(self):
        assert normalize_protocol_family("https(tlsv1.2)") == "HTTPS"

    # --- CONNECT_DIRECT family ---
    def test_connect_direct_secure(self):
        assert normalize_protocol_family("Connect:Direct Secure+ using TLS 1.2") == "CONNECT_DIRECT"

    # --- ORACLE_DB family (JDBC, Oracle Net, Oracle Native) ---
    def test_jdbc_over_tls(self):
        assert normalize_protocol_family("JDBC over TLS 1.2/TCP") == "ORACLE_DB"

    def test_oracle_net_tcps(self):
        assert normalize_protocol_family("Oracle Net TCPS(TLS1.2)") == "ORACLE_DB"

    def test_oracle_native_encryption(self):
        assert normalize_protocol_family("Oracle Native Encryption(TLS1.2)") == "ORACLE_DB"

    def test_oracle_native_tcps(self):
        assert normalize_protocol_family("Oracle Native TCPS") == "ORACLE_DB"

    # --- ORACLE_GG family (must match before generic Oracle) ---
    def test_oracle_goldengate(self):
        assert normalize_protocol_family("Oracle GoldenGate secured with TLS1.2") == "ORACLE_GG"

    def test_goldengate_matches_before_oracle_db(self):
        """GoldenGate must not fall through to ORACLE_DB."""
        assert normalize_protocol_family("Oracle GoldenGate TLS") == "ORACLE_GG"

    # --- SQL_DB family ---
    def test_odbc_tcps(self):
        assert normalize_protocol_family("ODBC(TCPS over TLS) TLS1.2") == "SQL_DB"

    def test_sql_server_over_tls(self):
        assert normalize_protocol_family("SQL Server over TLS 1.2/TCP") == "SQL_DB"

    # --- SFTP family ---
    def test_sftp_openssh(self):
        assert normalize_protocol_family("SFTP using OpenSSH SSH-2") == "SFTP"

    # --- AMQP family ---
    def test_amqp_over_tls(self):
        assert normalize_protocol_family("AMQP 1.0 over TLS 1.2") == "AMQP"

    # --- POSTGRESQL family ---
    def test_postgresql_ssl(self):
        assert normalize_protocol_family("PostgreSQL SSL/TLS(TLS1.2)") == "POSTGRESQL"

    # --- Edge cases ---
    def test_none_returns_unknown(self):
        assert normalize_protocol_family(None) == "UNKNOWN"

    def test_empty_string_returns_unknown(self):
        assert normalize_protocol_family("") == "UNKNOWN"

    def test_whitespace_only_returns_unknown(self):
        assert normalize_protocol_family("   ") == "UNKNOWN"

    def test_unrecognized_protocol_returns_other(self):
        assert normalize_protocol_family("FTP over TLS") == "OTHER"

    def test_leading_trailing_whitespace_stripped(self):
        assert normalize_protocol_family("  HTTPS(TLSv1.2)  ") == "HTTPS"


# ── Helpers for creating synthetic candidates ──────────────────────────


def _candidate(
    *,
    app: str = "APP",
    corr: str = "100",
    location: str = "Midrange",
    direction: str = "Inbound",
    protocol: str = "HTTPS(TLSv1.2)",
    port: str = "443",
) -> InterfaceCandidate:
    """Build a synthetic InterfaceCandidate via the normalization pipeline."""
    return create_interface_candidate(
        interface_system_location=location,
        data_traffic_direction=direction,
        target_protocol=protocol,
        future_port=port,
        interface_app_acronym=app,
        interface_correlation_id=corr,
    )


class TestProtocolFamilyGroup:
    """Slice 1: ProtocolFamilyGroup view model — finalize, dedup, direction."""

    def test_single_inbound_direction(self):
        g = ProtocolFamilyGroup(family="HTTPS")
        g.add_candidate(_candidate(direction="Inbound"))
        g.finalize()
        assert g.direction == "IN"

    def test_single_outbound_direction(self):
        g = ProtocolFamilyGroup(family="HTTPS")
        g.add_candidate(_candidate(direction="Outbound"))
        g.finalize()
        assert g.direction == "OUT"

    def test_mixed_direction_gives_in_out(self):
        g = ProtocolFamilyGroup(family="HTTPS")
        g.add_candidate(_candidate(direction="Inbound", app="A", corr="1"))
        g.add_candidate(_candidate(direction="Outbound", app="B", corr="2"))
        g.finalize()
        assert g.direction == "IN/OUT"

    def test_bidirectional_gives_in_out(self):
        g = ProtocolFamilyGroup(family="HTTPS")
        g.add_candidate(_candidate(direction="IN/OUT"))
        g.finalize()
        assert g.direction == "IN/OUT"

    def test_all_unknown_direction_gives_question_mark(self):
        g = ProtocolFamilyGroup(family="HTTPS")
        g.add_candidate(_candidate(direction=""))
        g.finalize()
        assert g.direction == "?"

    def test_dedup_same_app_different_ports(self):
        """Same (app, corr_id) on port 443 and 8447 → one label."""
        g = ProtocolFamilyGroup(family="HTTPS")
        g.add_candidate(_candidate(app="CPC", corr="101", port="443"))
        g.add_candidate(_candidate(app="CPC", corr="101", port="8447"))
        g.finalize()
        assert len(g.labels) == 1
        assert g.labels[0] == "CPC (101)"

    def test_multi_port_merged(self):
        g = ProtocolFamilyGroup(family="HTTPS")
        g.add_candidate(_candidate(port="443"))
        g.add_candidate(_candidate(port="8447"))
        g.finalize()
        assert g.ports == ["443", "8447"]

    def test_ports_sorted_numerically(self):
        g = ProtocolFamilyGroup(family="HTTPS")
        g.add_candidate(_candidate(port="8447"))
        g.add_candidate(_candidate(port="443"))
        g.finalize()
        assert g.ports == ["443", "8447"]

    def test_labels_sorted_alphabetically(self):
        g = ProtocolFamilyGroup(family="HTTPS")
        g.add_candidate(_candidate(app="Zebra", corr="3"))
        g.add_candidate(_candidate(app="Alpha", corr="1"))
        g.add_candidate(_candidate(app="Middle", corr="2"))
        g.finalize()
        assert g.labels == ["Alpha (1)", "Middle (2)", "Zebra (3)"]

    def test_port_display_multi(self):
        g = ProtocolFamilyGroup(family="HTTPS")
        g.add_candidate(_candidate(port="443"))
        g.add_candidate(_candidate(port="8447"))
        g.finalize()
        assert g.port_display == "443 8447"

    def test_port_display_single(self):
        g = ProtocolFamilyGroup(family="SFTP")
        g.add_candidate(_candidate(port="22", protocol="SFTP"))
        g.finalize()
        assert g.port_display == "22"

    def test_port_display_no_ports(self):
        g = ProtocolFamilyGroup(family="UNKNOWN")
        g.add_candidate(_candidate(port=""))
        g.finalize()
        assert g.port_display == "?"

    def test_label_display_comma_separated(self):
        g = ProtocolFamilyGroup(family="HTTPS")
        g.add_candidate(_candidate(app="APP1", corr="100"))
        g.add_candidate(_candidate(app="APP2", corr="200"))
        g.finalize()
        assert g.label_display == "APP1 (100), APP2 (200)"

    def test_direction_display_property(self):
        g = ProtocolFamilyGroup(family="HTTPS")
        g.add_candidate(_candidate(direction="Outbound"))
        g.finalize()
        assert g.direction_display == "OUT"

    def test_connector_color_from_family(self):
        g = ProtocolFamilyGroup(family="HTTPS")
        g.add_candidate(_candidate())
        g.finalize()
        assert g.connector_color == FAMILY_COLORS["HTTPS"]

    def test_connector_color_unknown_family(self):
        g = ProtocolFamilyGroup(family="UNKNOWN")
        g.add_candidate(_candidate(protocol=""))
        g.finalize()
        assert g.connector_color == FAMILY_COLORS["UNKNOWN"]

    def test_sort_key_family_then_port(self):
        g1 = ProtocolFamilyGroup(family="HTTPS")
        g1.add_candidate(_candidate(port="443"))
        g1.finalize()
        g2 = ProtocolFamilyGroup(family="SFTP")
        g2.add_candidate(_candidate(port="22", protocol="SFTP"))
        g2.finalize()
        assert g1.sort_key < g2.sort_key  # HTTPS < SFTP alphabetically

    def test_missing_acronym_shows_unknown(self):
        g = ProtocolFamilyGroup(family="HTTPS")
        g.add_candidate(_candidate(app=None, corr="100"))
        g.finalize()
        assert g.labels == ["UNKNOWN (100)"]

    def test_missing_corr_id_shows_question_mark(self):
        g = ProtocolFamilyGroup(family="HTTPS")
        g.add_candidate(_candidate(app="APP1", corr=None))
        g.finalize()
        assert g.labels == ["APP1 (?)"]


class TestGroupByProtocolFamily:
    """Slice 2: group_interfaces_by_protocol_family() integration tests."""

    def test_same_family_different_ports_merged(self):
        """HTTPS on 443 and HTTPS on 8447 → one HTTPS group."""
        candidates = [
            _candidate(app="A", corr="1", port="443", protocol="HTTPS(TLSv1.2)"),
            _candidate(app="B", corr="2", port="8447", protocol="HTTPS(TLSv1.2)"),
        ]
        groups = group_interfaces_by_protocol_family(candidates)
        families = [g.family for g in groups]
        assert families.count("HTTPS") == 1
        https_group = next(g for g in groups if g.family == "HTTPS")
        assert https_group.ports == ["443", "8447"]

    def test_different_families_same_port_separate(self):
        """ORACLE_DB and SQL_DB both on 1433 → 2 groups."""
        candidates = [
            _candidate(app="A", corr="1", port="1433", protocol="JDBC over TLS"),
            _candidate(app="B", corr="2", port="1433", protocol="ODBC over TLS"),
        ]
        groups = group_interfaces_by_protocol_family(candidates)
        families = sorted(g.family for g in groups)
        assert "ORACLE_DB" in families
        assert "SQL_DB" in families

    def test_non_internal_excluded(self):
        """Azure/AWS candidates not included in INTERNAL grouping."""
        candidates = [
            _candidate(location="Midrange", app="INTERNAL", corr="1"),
            _candidate(location="Azure", app="AZURE", corr="2"),
        ]
        groups = group_interfaces_by_protocol_family(candidates)
        all_labels = []
        for g in groups:
            all_labels.extend(g.labels)
        assert any("INTERNAL" in l for l in all_labels)
        assert not any("AZURE" in l for l in all_labels)

    def test_missing_protocol_goes_to_unknown(self):
        """Candidate with no protocol → Unknown group."""
        candidates = [
            _candidate(protocol="", port="443", app="NOPROTOCOL", corr="1"),
        ]
        groups = group_interfaces_by_protocol_family(candidates)
        assert any(g.family == "UNKNOWN" for g in groups)

    def test_missing_port_goes_to_unknown(self):
        """Candidate with no port → Unknown group."""
        candidates = [
            _candidate(protocol="HTTPS", port="", app="NOPORT", corr="1"),
        ]
        groups = group_interfaces_by_protocol_family(candidates)
        assert any(g.family == "UNKNOWN" for g in groups)

    def test_empty_input_returns_empty(self):
        groups = group_interfaces_by_protocol_family([])
        assert groups == []

    def test_deterministic_ordering(self):
        """Same input in different order → same output."""
        c1 = _candidate(app="A", corr="1", protocol="SFTP", port="22")
        c2 = _candidate(app="B", corr="2", protocol="HTTPS(TLSv1.2)", port="443")
        groups_a = group_interfaces_by_protocol_family([c1, c2])
        groups_b = group_interfaces_by_protocol_family([c2, c1])
        assert [g.family for g in groups_a] == [g.family for g in groups_b]
        assert [g.labels for g in groups_a] == [g.labels for g in groups_b]

    def test_unknown_group_at_end(self):
        """Unknown group appears after all other groups."""
        candidates = [
            _candidate(app="GOOD", corr="1", protocol="HTTPS(TLSv1.2)", port="443"),
            _candidate(app="BAD", corr="2", protocol="", port=""),
        ]
        groups = group_interfaces_by_protocol_family(candidates)
        assert groups[-1].family == "UNKNOWN"

    def test_category_filter_none_includes_all(self):
        """category_filter=None includes all categories."""
        candidates = [
            _candidate(location="Midrange", app="INT", corr="1"),
            _candidate(location="Azure", app="AZ", corr="2"),
        ]
        groups = group_interfaces_by_protocol_family(candidates, category_filter=None)
        all_labels = []
        for g in groups:
            all_labels.extend(g.labels)
        assert any("INT" in l for l in all_labels)
        assert any("AZ" in l for l in all_labels)

    def test_ccpm_like_data_produces_expected_groups(self):
        """Synthetic CCPM-like data → expected protocol families."""
        candidates = [
            _candidate(app="CPC", corr="101", protocol="HTTPS(TLSv1.2)", port="443"),
            _candidate(app="DITREX", corr="102", protocol="HTTPS(TLSv1.2)", port="8447"),
            _candidate(app="CCPM", corr="103", protocol="JDBC over TLS 1.2/TCP", port="1521"),
            _candidate(app="CCR-R", corr="104", protocol="Oracle Net TCPS(TLS1.2)", port="1521"),
            _candidate(app="EDW", corr="105", protocol="ODBC(TCPS over TLS) TLS1.2", port="1433"),
            _candidate(app="LS CRM", corr="106", protocol="Oracle GoldenGate secured with TLS1.2", port="7809"),
            _candidate(app="CCQT", corr="107", protocol="SFTP using OpenSSH SSH-2", port="22"),
            _candidate(app="Mylogin", corr="108", protocol="Connect:Direct Secure+ using TLS 1.2", port="1364"),
            _candidate(app="ImE FLEX", corr="109", protocol="", port=""),  # incomplete → unknown
        ]
        groups = group_interfaces_by_protocol_family(candidates)
        families = [g.family for g in groups]
        assert "HTTPS" in families
        assert "ORACLE_DB" in families
        assert "SQL_DB" in families
        assert "ORACLE_GG" in families
        assert "SFTP" in families
        assert "CONNECT_DIRECT" in families
        assert "UNKNOWN" in families
        # HTTPS group should merge two ports
        https_group = next(g for g in groups if g.family == "HTTPS")
        assert https_group.ports == ["443", "8447"]
        # ORACLE_DB should merge JDBC + Oracle Net (same port 1521)
        odb = next(g for g in groups if g.family == "ORACLE_DB")
        assert odb.ports == ["1521"]
        assert len(odb.labels) == 2  # CCPM + CCR-R


# ── Slice 0a: Location alias coverage ─────────────────────────────────


class TestLocationAliasCoverage:
    """Location aliases must cover all values offered in the UI form datalist.

    Form datalist (interfaces/form.html): Mainframe, Midrange, Azure, AWS,
    Conexus, Private Cloud.  Additional real-world variants must also map.
    """

    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("Mainframe", "INTERNAL"),
            ("MAINFRAME", "INTERNAL"),
            ("mainframe", "INTERNAL"),
            ("Private Cloud", "INTERNAL"),
            ("PRIVATE CLOUD", "INTERNAL"),
            ("private cloud", "INTERNAL"),
            ("On-Premises", "INTERNAL"),
            ("ON-PREMISES", "INTERNAL"),
            ("Data Center", "INTERNAL"),
            ("DATA CENTER", "INTERNAL"),
            ("Datacenter", "INTERNAL"),
            ("DATACENTER", "INTERNAL"),
        ],
    )
    def test_missing_location_aliases(self, raw, expected):
        assert normalize_location(raw) == expected

    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("Midrange", "INTERNAL"),
            ("AWS", "AWS"),
            ("Azure", "AZURE"),
            ("Conexus", "INTERNAL"),
            ("ATT", "INTERNAL"),
            ("INTERNAL", "INTERNAL"),
        ],
    )
    def test_existing_aliases_still_work(self, raw, expected):
        """Existing aliases must remain unchanged after adding new ones."""
        assert normalize_location(raw) == expected

    def test_candidate_mainframe_categorized_as_internal(self):
        """create_interface_candidate with Mainframe → norm_category INTERNAL."""
        c = create_interface_candidate(interface_system_location="Mainframe")
        assert c.norm_category == "INTERNAL"

    def test_candidate_private_cloud_categorized_as_internal(self):
        c = create_interface_candidate(interface_system_location="Private Cloud")
        assert c.norm_category == "INTERNAL"


# ── Slice 0b: DATAGUARD and SMTP protocol families ────────────────────


class TestDataguardAndSmtpFamilies:
    """DATAGUARD and SMTP must be recognized protocol families with colors."""

    def test_dataguard_plain(self):
        assert normalize_protocol_family("DataGuard") == "DATAGUARD"

    def test_dataguard_with_tls(self):
        assert normalize_protocol_family("DataGuard over TLS 1.2") == "DATAGUARD"

    def test_data_guard_two_words(self):
        assert normalize_protocol_family("Data Guard TLS1.2/TCP") == "DATAGUARD"

    def test_smtp_plain(self):
        assert normalize_protocol_family("SMTP") == "SMTP"

    def test_smtp_with_tls(self):
        assert normalize_protocol_family("SMTP over TLS 1.2") == "SMTP"

    def test_dataguard_color_present(self):
        assert "DATAGUARD" in FAMILY_COLORS
        assert FAMILY_COLORS["DATAGUARD"] == "#CCCC00"

    def test_smtp_color_present(self):
        assert "SMTP" in FAMILY_COLORS
        assert FAMILY_COLORS["SMTP"] == "#CC0000"

    def test_dataguard_does_not_match_oracle_db(self):
        """DataGuard must NOT fall through to ORACLE_DB (order matters)."""
        assert normalize_protocol_family("Oracle DataGuard") == "DATAGUARD"


# ── Slice 0c: SQL_DB color matches template legend ────────────────────


class TestSqlDbColor:
    """SQL_DB color must match template legend (#FF9933), not #FF8000."""

    def test_sql_db_color_matches_legend(self):
        assert FAMILY_COLORS["SQL_DB"] == "#FF9933"


# ── Slice 0d: tier2_internet_slot category alignment ──────────────────


class TestTier2InternetSlotCategory:
    """Profile tier2_internet_slot must use TIER2_INTERNET, not UNKNOWN."""

    def test_tier2_internet_slot_category_matches_aliases(self):
        from migration_intake.topology.haf_pipeline import load_haf_profile

        profile = load_haf_profile("OUTPOST_V1")
        tier2_regions = [
            r for r in profile.interface_regions
            if r.haf_role == "tier2_internet_slot"
        ]
        assert len(tier2_regions) == 1
        assert tier2_regions[0].category == "TIER2_INTERNET"

    def test_location_internet_normalizes_to_tier2_internet(self):
        """Ensure 'Internet' location maps to TIER2_INTERNET category."""
        assert normalize_location("Internet") == "TIER2_INTERNET"

    def test_location_tier2_normalizes_to_tier2_internet(self):
        assert normalize_location("Tier 2") == "TIER2_INTERNET"


# ── Slice 0e: Template must not contain CCPM-specific data ────────────


class TestTemplateCcpmCleanup:
    """v1.7 template must contain only generic placeholders, not CCPM data."""

    TEMPLATE_PATH = (
        Path(__file__).resolve().parents[3]
        / "docs"
        / "development"
        / "topo_9_24"
        / "AWS__input_Outpost_Topology_UNRESOLVED_UNRESOLVED-v1.7.drawio"
    )

    CCPM_IDENTIFIERS = [
        "18249", "18274", "10038", "19166",   # CCPM correlation IDs
        "30358", "15977", "21226", "17455",   # CCPM correlation IDs
        "31479", "30333", "20416",            # Azure CCPM IDs
        "ORACLE SCM", "DITREX", "LS-OMS",    # CCPM app names
        "MyTracker", "ImE FLEX", "DVT",       # CCPM app names
        "DPG - Sales", "AZDP",               # CCPM Azure app names
    ]

    @pytest.mark.skipif(
        not Path(__file__).resolve().parents[3].joinpath(
            "docs", "development", "topo_9_24",
            "AWS__input_Outpost_Topology_UNRESOLVED_UNRESOLVED-v1.7.drawio"
        ).exists(),
        reason="Template file not available",
    )
    def test_template_no_ccpm_specific_data(self):
        """No cell in the template should contain CCPM-specific app names or IDs."""
        import re
        import xml.etree.ElementTree as ET

        tree = ET.parse(str(self.TEMPLATE_PATH))
        root = tree.getroot()
        violations = []
        for cell in root.iter("mxCell"):
            val = cell.get("value", "")
            clean = re.sub(r"<[^>]+>", "", val).strip()
            for identifier in self.CCPM_IDENTIFIERS:
                if identifier in clean:
                    role = cell.get("haf-role", "no-role")
                    violations.append(
                        f"Cell role={role} contains CCPM data: '{identifier}'"
                    )
                    break
        assert violations == [], (
            f"Template contains {len(violations)} CCPM-specific cells:\n"
            + "\n".join(violations)
        )


# ── Slice 3: Static sections protection ───────────────────────────────


class TestStaticSectionsConfig:
    """Profile must list the 11 standard sections that must not be modified."""

    EXPECTED_SECTIONS = [
        "GitHub Runners",
        "GitHub JFrog Artifactory IaC",
        "DNS PHZs",
        "AWS Home Region",
        "AWS Direct Connect Region",
        "AT&T Conexus/GPN",
        "AWS Tier 2",
        "Internet",
        "SMTP Cluster - outbound email",
        "SMTP Relay",
        "SMTP Cluster - inbound email",
    ]

    def test_profile_has_standard_sections(self):
        from migration_intake.topology.haf_pipeline import load_haf_profile

        profile = load_haf_profile("OUTPOST_V1")
        assert hasattr(profile, "standard_sections"), (
            "Profile must have standard_sections attribute"
        )
        assert isinstance(profile.standard_sections, list)
        assert len(profile.standard_sections) >= 11

    def test_all_expected_sections_present(self):
        from migration_intake.topology.haf_pipeline import load_haf_profile

        profile = load_haf_profile("OUTPOST_V1")
        for section in self.EXPECTED_SECTIONS:
            assert section in profile.standard_sections, (
                f"Missing standard section: '{section}'"
            )


# ── Slice 5: Direction filter for grouping ────────────────────────────


class TestDirectionFilter:
    """group_interfaces_by_protocol_family() must accept a direction_filter."""

    def test_filter_inbound_only(self):
        candidates = [
            _candidate(direction="Inbound", app="IN", corr="1"),
            _candidate(direction="Outbound", app="OUT", corr="2", port="8080"),
        ]
        groups = group_interfaces_by_protocol_family(
            candidates,
            direction_filter=frozenset({"INBOUND"}),
        )
        all_labels = [lbl for g in groups for lbl in g.labels]
        assert any("IN" in lbl for lbl in all_labels)
        assert not any("OUT (2)" in lbl for lbl in all_labels)

    def test_filter_inbound_and_bidirectional(self):
        candidates = [
            _candidate(direction="Inbound", app="IN", corr="1"),
            _candidate(direction="Outbound", app="OUT", corr="2", port="8080"),
            _candidate(direction="IN/OUT", app="BOTH", corr="3", port="9090"),
        ]
        groups = group_interfaces_by_protocol_family(
            candidates,
            direction_filter=frozenset({"INBOUND", "BIDIRECTIONAL"}),
        )
        all_labels = [lbl for g in groups for lbl in g.labels]
        assert any("IN" in lbl for lbl in all_labels)
        assert any("BOTH" in lbl for lbl in all_labels)
        assert not any("OUT (2)" in lbl for lbl in all_labels)

    def test_no_direction_filter_includes_all(self):
        """Default direction_filter=None includes all directions."""
        candidates = [
            _candidate(direction="Inbound", app="IN", corr="1"),
            _candidate(direction="Outbound", app="OUT", corr="2", port="8080"),
        ]
        groups = group_interfaces_by_protocol_family(
            candidates,
            direction_filter=None,
        )
        all_labels = [lbl for g in groups for lbl in g.labels]
        assert any("IN" in lbl for lbl in all_labels)
        assert any("OUT" in lbl for lbl in all_labels)

    def test_aws_category_with_direction_filter(self):
        candidates = [
            _candidate(location="AWS", direction="Inbound", app="AWS-IN", corr="1"),
            _candidate(location="AWS", direction="Outbound", app="AWS-OUT", corr="2", port="8080"),
            _candidate(location="Midrange", direction="Inbound", app="INT-IN", corr="3"),
        ]
        groups = group_interfaces_by_protocol_family(
            candidates,
            category_filter="AWS",
            direction_filter=frozenset({"INBOUND"}),
        )
        all_labels = [lbl for g in groups for lbl in g.labels]
        assert any("AWS-IN" in lbl for lbl in all_labels)
        assert not any("AWS-OUT" in lbl for lbl in all_labels)
        assert not any("INT-IN" in lbl for lbl in all_labels)

    def test_backward_compatible_no_direction_arg(self):
        """Calling without direction_filter arg still works (default=None)."""
        candidates = [_candidate(app="TEST", corr="1")]
        groups = group_interfaces_by_protocol_family(candidates)
        assert len(groups) == 1


# ── Slice 4: AWS Tier 1 container in template ─────────────────────────


class TestAwsTier1TemplateContainer:
    """v1.7 template must have an AWS Tier 1 container with haf-role."""

    TEMPLATE_PATH = (
        Path(__file__).resolve().parents[3]
        / "docs"
        / "development"
        / "topo_9_24"
        / "AWS__input_Outpost_Topology_UNRESOLVED_UNRESOLVED-v1.7.drawio"
    )

    @pytest.mark.skipif(
        not Path(__file__).resolve().parents[3].joinpath(
            "docs", "development", "topo_9_24",
            "AWS__input_Outpost_Topology_UNRESOLVED_UNRESOLVED-v1.7.drawio"
        ).exists(),
        reason="Template file not available",
    )
    def test_aws_tier1_container_exists(self):
        import xml.etree.ElementTree as ET

        tree = ET.parse(str(self.TEMPLATE_PATH))
        root = tree.getroot()
        containers = [
            cell for cell in root.iter("mxCell")
            if "aws_tier1_container" in cell.get("haf-role", "")
        ]
        assert len(containers) == 1, "Template must have exactly 1 aws_tier1_container"

    @pytest.mark.skipif(
        not Path(__file__).resolve().parents[3].joinpath(
            "docs", "development", "topo_9_24",
            "AWS__input_Outpost_Topology_UNRESOLVED_UNRESOLVED-v1.7.drawio"
        ).exists(),
        reason="Template file not available",
    )
    def test_aws_tier1_has_background_rect(self):
        import xml.etree.ElementTree as ET

        tree = ET.parse(str(self.TEMPLATE_PATH))
        root = tree.getroot()
        rects = [
            cell for cell in root.iter("mxCell")
            if "aws_tier1_bg" in cell.get("haf-role", "")
        ]
        assert len(rects) == 1, "Template must have aws_tier1_bg rect"

    @pytest.mark.skipif(
        not Path(__file__).resolve().parents[3].joinpath(
            "docs", "development", "topo_9_24",
            "AWS__input_Outpost_Topology_UNRESOLVED_UNRESOLVED-v1.7.drawio"
        ).exists(),
        reason="Template file not available",
    )
    def test_aws_tier1_has_title_label(self):
        import xml.etree.ElementTree as ET

        tree = ET.parse(str(self.TEMPLATE_PATH))
        root = tree.getroot()
        labels = [
            cell for cell in root.iter("mxCell")
            if "aws_tier1_title" in cell.get("haf-role", "")
        ]
        assert len(labels) == 1
        assert "Tier 1" in labels[0].get("value", "")
