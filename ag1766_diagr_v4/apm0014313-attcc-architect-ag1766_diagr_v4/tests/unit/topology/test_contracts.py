"""Synthetic C2.1 tests for strict topology contracts."""

from __future__ import annotations

import json
from datetime import datetime
from types import MappingProxyType

import pytest

from migration_intake.topology.contracts import (
    DuplicateJsonKeyError,
    GenerationMode,
    HashMismatchError,
    NonCanonicalJsonError,
    NonFiniteNumberError,
    RenderCapability,
    TopologyContractError,
    TopologyInputIdentity,
    UnsupportedTopologySchemaError,
    load_snapshot_document,
    normalize_timestamp,
    serialize_snapshot_document,
)


def _snapshot() -> dict:
    return {
        "schema_version": "3.0.0",
        "application": {
            "id": "app-synthetic",
            "name": "Synthetic Application",
            "acronym": "SYN",
            "identifiers": [
                {
                    "namespace": "CORRELATION",
                    "raw_value": "raw-001",
                    "normalized_value": "raw-001",
                    "is_primary": True,
                }
            ],
        },
        "catalog": {
            "id": "catalog-synthetic",
            "version": "1.0.0",
            "source_sha256": "a" * 64,
            "catalog_hash": "b" * 64,
            "compiler_version": "1.0.0",
        },
        "intake": {
            "id": "intake-synthetic",
            "state": "FROZEN",
            "frozen_at": "2026-09-18T00:00:00.000Z",
            "frozen_by": "actor-synthetic",
            "row_version": 3,
            "content_epoch": 4,
        },
        "answers": [],
        "interface_register": {"interface_epoch": 1, "rows": []},
        "resources": [],
        "relationships": [],
        "wave_util_rows": [],
        "permitted_gaps": [],
    }


def test_snapshot_serialization_is_order_independent_and_deeply_immutable():
    document = _snapshot()
    reversed_document = dict(reversed(list(document.items())))

    first = serialize_snapshot_document(document)
    second = serialize_snapshot_document(reversed_document)

    assert first.canonical_json == second.canonical_json
    assert first.sha256_hex == second.sha256_hex
    assert isinstance(first.document, MappingProxyType)
    with pytest.raises(TypeError):
        first.document["schema_version"] = "2.0.0"


def test_snapshot_load_rejects_tampered_hash_and_noncanonical_bytes():
    contract = serialize_snapshot_document(_snapshot())

    with pytest.raises(HashMismatchError):
        load_snapshot_document(contract.canonical_json, "0" * 64)

    reordered = json.dumps(_snapshot(), ensure_ascii=False, indent=2)
    with pytest.raises(NonCanonicalJsonError):
        load_snapshot_document(reordered, __import__("hashlib").sha256(reordered.encode()).hexdigest())


def test_snapshot_load_rejects_legacy_schema_and_unknown_fields():
    legacy = _snapshot()
    legacy["schema_version"] = "2.0.0"
    legacy_contract = json.dumps(legacy, sort_keys=True, separators=(",", ":"))
    with pytest.raises(UnsupportedTopologySchemaError):
        serialize_snapshot_document(json.loads(legacy_contract))

    unknown = _snapshot()
    unknown["unexpected"] = True
    with pytest.raises(TopologyContractError):
        serialize_snapshot_document(unknown)


def test_json_duplicate_keys_and_nonfinite_numbers_fail_closed():
    duplicate = '{"schema_version":"3.0.0","schema_version":"2.0.0"}'
    with pytest.raises(DuplicateJsonKeyError):
        from migration_intake.topology.contracts import parse_canonical_json

        parse_canonical_json(duplicate)

    with pytest.raises(NonFiniteNumberError):
        from migration_intake.topology.contracts import parse_canonical_json

        parse_canonical_json("{\"value\":NaN}")


def test_input_identity_excludes_operational_ids_but_includes_capability_and_context():
    common = dict(
        mode=GenerationMode.OFFICIAL_SNAPSHOT,
        capability=RenderCapability.LABEL_ONLY,
        projection_hash="a" * 64,
        selection_hash="b" * 64,
        base_hash="c" * 64,
        compatibility_key="2" * 64,
        profile_hash="d" * 64,
        catalog_hash="e" * 64,
        generator_version="1.0.0",
        parser_policy_hash="f" * 64,
        layout_policy_hash="0" * 64,
        result_policy_hash="1" * 64,
    )
    first = TopologyInputIdentity(contexts=(("DEV", "SITE_A"),), **common)
    second = TopologyInputIdentity(contexts=(("DEV", "SITE_A"),), **common)
    structural = TopologyInputIdentity(
        contexts=(("DEV", "SITE_A"),),
        **{**common, "capability": RenderCapability.STRUCTURAL},
    )
    other_context = TopologyInputIdentity(
        contexts=(("PROD", "SITE_A"),),
        **common,
    )

    assert first.input_hash == second.input_hash
    assert first.input_hash != structural.input_hash
    assert first.input_hash != other_context.input_hash


def test_naive_timestamp_is_rejected():
    with pytest.raises(TopologyContractError, match="Naive"):
        normalize_timestamp(datetime(2026, 9, 18))
