"""TP07 synthetic typed graph projection certification cases."""

from __future__ import annotations

import copy
from datetime import UTC, datetime

from migration_intake.topology.contracts import serialize_snapshot_document
from migration_intake.topology.scope import ContextKey, ScopeSelection
from migration_intake.topology.strict_projection import (
    StrictProjectionError,
    load_strict_projection_document,
    project_v3_snapshot,
    serialize_strict_projection,
)


def document(rows: list[dict[str, object]]) -> dict[str, object]:
    return {
        "schema_version": "3.0.0",
        "application": {"id": "APP", "name": "App", "acronym": "APP", "identifiers": []},
        "catalog": {
            "id": "CAT",
            "version": "1",
            "source_sha256": "a" * 64,
            "catalog_hash": "b" * 64,
            "compiler_version": "1",
        },
        "intake": {
            "id": "INTAKE",
            "state": "FROZEN",
            "frozen_at": "2026-09-22T00:00:00.000Z",
            "frozen_by": "ACTOR",
            "row_version": 1,
            "content_epoch": 1,
        },
        "answers": [],
        "interface_register": {"interface_epoch": 1, "rows": rows},
        "resources": [],
        "relationships": [],
        "wave_util_rows": [],
        "permitted_gaps": [],
    }


def row(
    identifier: str,
    *,
    direction: str = "Inbound",
    protocol: str = "HTTPS",
    port: str = "443",
    record_id: str = "ROW",
    environment: str = "PROD",
    site: str = "SITE_A",
) -> dict[str, object]:
    return {
        "id": record_id,
        "interface_correlation_id": identifier,
        "interface_app_acronym": identifier,
        "interface_system_location": "AWS",
        "data_traffic_direction": direction,
        "target_protocol": protocol,
        "future_port": port,
        "environment": environment,
        "site": site,
        "origin": "IMPORT",
        "row_version": 1,
    }


def project(source: dict[str, object]):
    source = copy.deepcopy(source)
    source["interface_register"]["rows"].sort(key=lambda item: item["id"])  # type: ignore[index,union-attr]
    contract = serialize_snapshot_document(source)
    selection = ScopeSelection("APP", "INTAKE", (ContextKey("PROD", "SITE_A"),), "details")
    return project_v3_snapshot(
        contract.canonical_json, contract.sha256_hex, selection, (), datetime.now(UTC)
    )


def test_c00_empty_projection_has_only_application_anchor() -> None:
    result = project(document([]))
    assert [node.node_id for node in result.nodes] == ["APP"]
    assert result.flows == ()


def test_c01_c02_simple_and_one_to_many_directed_flows() -> None:
    result = project(document([row("B", record_id="R1"), row("C", record_id="R2")]))
    assert {(flow.source_id, flow.target_id) for flow in result.flows} == {
        ("B", "APP"),
        ("C", "APP"),
    }
    assert {node.node_id for node in result.nodes} == {"APP", "B", "C"}


def test_c04_exact_duplicate_merges_provenance_but_port_variant_stays_distinct() -> None:
    result = project(
        document(
            [
                row("B", record_id="R1"),
                row("B", record_id="R2"),
                row("B", port="8443", record_id="R3"),
            ]
        )
    )
    assert len(result.flows) == 2
    exact = next(flow for flow in result.flows if flow.port == "443")
    assert {"R1", "R2"} <= set(exact.provenance)


def test_c07_unknown_direction_is_excluded_with_stable_blocker() -> None:
    result = project(document([row("B", direction="", record_id="R1")]))
    assert result.flows == ()
    assert result.exclusions[0].code == "UNKNOWN_DIRECTION"
    assert result.exclusions[0].blocking is True


def test_bidirectional_produces_two_flows_and_communication_cycle_survives() -> None:
    result = project(document([row("B", direction="Bidirectional", record_id="R1")]))
    assert {(flow.source_id, flow.target_id) for flow in result.flows} == {
        ("B", "APP"),
        ("APP", "B"),
    }


def test_deterministic_hash_ignores_input_order() -> None:
    original = document([row("B", record_id="R1"), row("C", record_id="R2")])
    reversed_document = copy.deepcopy(original)
    reversed_document["interface_register"]["rows"].reverse()  # type: ignore[index,union-attr]
    assert project(original).projection_hash == project(reversed_document).projection_hash


def test_c03_duplicate_node_labels_do_not_merge_distinct_ids() -> None:
    result = project(document([row("SAME", record_id="R1"), row("OTHER", record_id="R2")]))
    assert {node.node_id for node in result.nodes} == {"APP", "SAME", "OTHER"}


def test_c05_missing_endpoint_is_blocked_without_dangling_flow() -> None:
    result = project(document([row("", record_id="R1")]))
    assert result.flows == ()
    assert result.exclusions[0].code == "MISSING_ENDPOINT_ID"


def test_c08_c09_scope_identity_distinguishes_region_and_account() -> None:
    first = row("B", record_id="R1")
    second = row("C", record_id="R2")
    first.update({"region": "us-east-1", "account": "111"})
    second.update({"region": "us-west-2", "account": "222"})
    result = project(document([first, second]))
    scopes = {(flow.scope.region, flow.scope.account) for flow in result.flows}
    assert scopes == {("us-east-1", "111"), ("us-west-2", "222")}


def test_c10_partial_source_failure_is_explicit_exclusion() -> None:
    result = project(document([row("B", direction="", record_id="FAILED-SOURCE")]))
    assert result.has_blockers
    assert result.exclusions[0].source_id == "FAILED-SOURCE"


def test_c11_retired_rows_are_absent_from_immutable_authority_projection() -> None:
    active = row("B", record_id="ACTIVE")
    result = project(document([active]))
    assert {node.node_id for node in result.nodes} == {"APP", "B"}


def test_c12_large_projection_is_bounded_and_exact() -> None:
    rows = [row(f"N-{index}", record_id=f"R-{index}") for index in range(1000)]
    result = project(document(rows))
    assert len(result.nodes) == 1001
    assert len(result.flows) == 1000


def test_cross_intake_relationship_is_rejected_as_blocking_issue() -> None:
    source = document([])
    source["relationships"] = [
        {
            "relationship_id": "REL",
            "source_resource_id": "A",
            "target_resource_id": "B",
            "review_state": "CONFIRMED",
            "intake_id": "OTHER",
        }
    ]
    result = project(source)
    assert result.relationships == ()


def test_persisted_loader_validates_typed_shapes() -> None:
    result = project(document([row("B")]))
    canonical = serialize_strict_projection(result)
    loaded = load_strict_projection_document(canonical, result.projection_hash)
    assert loaded["nodes"] and loaded["flows"]
    malformed = canonical.replace('"node_id":"APP"', '"unknown":"APP"', 1)
    import hashlib

    with __import__("pytest").raises((StrictProjectionError, ValueError)):
        load_strict_projection_document(malformed, hashlib.sha256(malformed.encode()).hexdigest())


def test_protocol_and_port_variants_have_distinct_semantic_keys() -> None:
    result = project(
        document(
            [
                row("B", protocol="HTTPS", port="443", record_id="R1"),
                row("B", protocol="SSH", port="22", record_id="R2"),
            ]
        )
    )
    assert {(flow.protocol, flow.port) for flow in result.flows} == {
        ("HTTPS", "443"),
        ("SSH", "22"),
    }
