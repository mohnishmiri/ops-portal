"""C4.3 strict v3 projection tests."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from migration_intake.topology.contracts import serialize_snapshot_document
from migration_intake.topology.scope import ContextKey, ScopeSelection
from migration_intake.topology.strict_projection import (
    ProjectionIdentityMismatchError,
    ProjectionMappingError,
    StrictFactMapping,
    StrictProjectionError,
    load_strict_projection_document,
    project_v3_snapshot,
    serialize_strict_projection,
)


def _snapshot() -> tuple[str, str]:
    document = {
        "schema_version": "3.0.0",
        "application": {"id": "app", "name": "Synthetic", "acronym": "SYN", "identifiers": []},
        "catalog": {
            "id": "catalog",
            "version": "1.0.0",
            "source_sha256": "a" * 64,
            "catalog_hash": "b" * 64,
            "compiler_version": "1.0.0",
        },
        "intake": {
            "id": "intake",
            "state": "FROZEN",
            "frozen_at": "2026-09-18T00:00:00.000Z",
            "frozen_by": "actor",
            "row_version": 1,
            "content_epoch": 1,
        },
        "answers": [
            {
                "question_code": "CTL-002",
                "response_type": "TEXT_PAIR",
                "value": {"first": "Synthetic", "second": "SYN"},
                "confirm_state": "CONFIRMED",
                "provenance_references": ["evidence-1"],
            }
        ],
        "interface_register": {"interface_epoch": 1, "rows": []},
        "resources": [
            {
                "resource_id": "dev-vpc",
                "logical_key": "vpc-main",
                "kind": "VPC",
                "lifecycle": "TARGET",
                "scope": {
                    "environment": "DEV",
                    "site_id": "SITE_A",
                    "environment_state": "KNOWN",
                    "site_state": "KNOWN",
                },
                "global_scope": False,
                "review_state": "CONFIRMED",
                "attributes": {"vpc_id": "synthetic-vpc"},
            },
            {
                "resource_id": "prod-vpc",
                "logical_key": "vpc-main",
                "kind": "VPC",
                "lifecycle": "TARGET",
                "scope": {
                    "environment": "PROD",
                    "site_id": "SITE_A",
                    "environment_state": "KNOWN",
                    "site_state": "KNOWN",
                },
                "global_scope": False,
                "review_state": "CONFIRMED",
                "attributes": {"vpc_id": "synthetic-prod-vpc"},
            },
        ],
        "relationships": [],
        "wave_util_rows": [],
        "permitted_gaps": [],
    }
    contract = serialize_snapshot_document(document)
    return contract.canonical_json, contract.sha256_hex


def _selection() -> ScopeSelection:
    return ScopeSelection(
        "app",
        "intake",
        (ContextKey("PROD", "SITE_A"), ContextKey("DEV", "SITE_A")),
        "combined-overview-with-details",
    )


def test_projection_keeps_same_name_resources_in_distinct_partitions():
    snapshot, digest = _snapshot()
    projection = project_v3_snapshot(
        snapshot,
        digest,
        _selection(),
        (
            StrictFactMapping("CTL-002", "TEXT_PAIR", "app.name", "TEXT_PAIR.first"),
            StrictFactMapping("CTL-002", "TEXT_PAIR", "app.acronym", "TEXT_PAIR.second"),
        ),
        datetime.now(UTC),
    )
    assert [item.context.environment for item in projection.partitions] == ["DEV", "PROD"]
    assert projection.partitions[0].resources[0]["resource_id"] == "dev-vpc"
    assert projection.partitions[1].resources[0]["resource_id"] == "prod-vpc"
    assert projection.partitions[0].facts[0].provenance == ("evidence-1",)
    assert {fact.output_key for fact in projection.partitions[0].facts} == {
        "app.acronym",
        "app.name",
    }


def test_projection_rejects_identity_mismatch():
    snapshot, digest = _snapshot()
    selection = ScopeSelection("other-app", "intake", (ContextKey("DEV", "SITE_A"),), "details")
    with pytest.raises(ProjectionIdentityMismatchError):
        project_v3_snapshot(snapshot, digest, selection, (), datetime.now(UTC))


def test_projection_rejects_unknown_mapping_shape():
    snapshot, digest = _snapshot()
    with pytest.raises(ProjectionMappingError):
        project_v3_snapshot(
            snapshot,
            digest,
            _selection(),
            (StrictFactMapping("CTL-002", "TEXT_PAIR", "app.name", "ARBITRARY"),),
            datetime.now(UTC),
        )


def test_persisted_projection_round_trip_is_strict():
    snapshot, digest = _snapshot()
    projection = project_v3_snapshot(
        snapshot,
        digest,
        _selection(),
        (StrictFactMapping("CTL-002", "TEXT_PAIR", "app.name", "TEXT_PAIR.first"),),
        datetime.now(UTC),
    )
    canonical = serialize_strict_projection(projection)

    loaded = load_strict_projection_document(canonical, projection.projection_hash)

    assert loaded["application_id"] == "app"
    malformed = __import__("json").loads(canonical)
    malformed["unknown"] = True
    malformed_json = __import__("json").dumps(malformed, sort_keys=True, separators=(",", ":"))
    with pytest.raises(StrictProjectionError, match="fields mismatch"):
        load_strict_projection_document(
            malformed_json,
            __import__("hashlib").sha256(malformed_json.encode()).hexdigest(),
        )
