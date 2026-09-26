"""TP04 synthetic fixtures for the approved guide policy."""

from migration_intake.topology.guide_policy import (
    APPROVED_AT,
    POLICY_VERSION,
    PROHIBITED_LABEL_FIELDS,
    PROJECTION_FIELDS,
    normalize_interface_flow,
)


def row(**values: str) -> dict[str, object]:
    return {
        "interface_correlation_id": "IF-001",
        "interface_system_location": "AWS",
        "data_traffic_direction": "Inbound",
        "target_protocol": "HTTPS",
        "future_port": "443",
        **values,
    }


def test_policy_is_versioned_and_approved() -> None:
    assert POLICY_VERSION == "1.0.0"
    assert APPROVED_AT == "2026-09-22"


def test_inbound_outbound_and_bidirectional_are_explicit() -> None:
    inbound = normalize_interface_flow(row(), "APP")[0]
    outbound = normalize_interface_flow(row(data_traffic_direction="Outbound"), "APP")[0]
    bidirectional = normalize_interface_flow(row(data_traffic_direction="Bidirectional"), "APP")
    assert (inbound.source_id, inbound.target_id) == ("IF-001", "APP")
    assert (outbound.source_id, outbound.target_id) == ("APP", "IF-001")
    assert {(flow.source_id, flow.target_id) for flow in bidirectional} == {
        ("IF-001", "APP"),
        ("APP", "IF-001"),
    }


def test_unknown_direction_and_identity_remain_unresolved() -> None:
    assert normalize_interface_flow(row(data_traffic_direction=""), "APP")[0].issue == (
        "UNKNOWN_DIRECTION"
    )
    assert normalize_interface_flow(row(interface_correlation_id=""), "APP")[0].issue == (
        "MISSING_ENDPOINT_ID"
    )


def test_group_aliases_and_unknown_are_explicit() -> None:
    azure = normalize_interface_flow(row(interface_system_location="Microsoft Azure"), "APP")
    unknown = normalize_interface_flow(row(interface_system_location="Other"), "APP")
    assert azure[0].group == "AZURE"
    assert unknown[0].group == "UNKNOWN"


def test_protocol_port_are_part_of_semantic_identity() -> None:
    https = normalize_interface_flow(row(), "APP")[0]
    ssh = normalize_interface_flow(row(target_protocol="SSH", future_port="22"), "APP")[0]
    assert https.semantic_key != ssh.semantic_key
    assert normalize_interface_flow(row(future_port="not-a-port"), "APP")[0].issue == "INVALID_PORT"


def test_projection_allowlist_excludes_contacts_notes_and_free_text_endpoint() -> None:
    assert PROHIBITED_LABEL_FIELDS.isdisjoint(PROJECTION_FIELDS)
    assert "end_point_name" not in PROJECTION_FIELDS
    assert {"row_version", "created_by_id", "updated_by_id"} <= set(PROJECTION_FIELDS)
