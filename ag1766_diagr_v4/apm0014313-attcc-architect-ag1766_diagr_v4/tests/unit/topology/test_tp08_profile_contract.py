"""TP08 repeated-region profile and compatibility contracts."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path

from migration_intake.topology.profiles.loader import (
    ProfileValidationError,
    load_profile_from_path,
)


def _profile(tmp_path: Path, region: dict[str, object]) -> Path:
    profile = tmp_path / "profile"
    profile.mkdir(parents=True)
    components = {
        "slots": {
            "slots": [
                {
                    "slot_id": "REPEAT",
                    "slot_type": "REPEATING",
                    "page_selector": {},
                    "cell_matcher": {
                        "match_type": "MARKER",
                        "marker_pattern": "{{APPLICATION_NAME}}",
                    },
                    "tokens": ["APPLICATION_NAME"],
                }
            ],
            "generated_regions": [region],
        },
        "mappings": {
            "tokens": [
                {"token_id": "APPLICATION_NAME", "projection_path": "application.name", "scope": {}}
            ]
        },
        "markers": {
            "governed_markers": [{"pattern": "{{APPLICATION_NAME}}", "token": "APPLICATION_NAME"}]
        },
        "issue_rules": {
            "issue_rules": [
                {
                    "rule_id": "RULE",
                    "condition": "missing",
                    "severity": "ERROR",
                    "message": "missing",
                }
            ]
        },
        "naming_rules": {
            "naming_rules": [
                {"rule_id": "NAME", "pattern": "{name}", "tokens": {"name": "APPLICATION_NAME"}}
            ]
        },
    }
    import hashlib

    entries = {}
    for name, content in components.items():
        data = json.dumps(content, separators=(",", ":")).encode()
        (profile / f"{name}.json").write_bytes(data)
        entries[name] = {"path": f"{name}.json", "sha256": hashlib.sha256(data).hexdigest()}
    manifest = {
        "profile_id": "REPEAT",
        "version": "1.0.0",
        "variant": "STRUCTURAL",
        "target_platform": "DRAWIO",
        "components": entries,
    }
    payload = dict(manifest)
    manifest["profile_sha256"] = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    (profile / "manifest.json").write_text(
        json.dumps(manifest, separators=(",", ":")), encoding="utf-8"
    )
    return profile


def _region(**overrides: object) -> dict[str, object]:
    return {
        "region_id": "FLOW_REGION",
        "page_name": "Overview",
        "container_cell_id": "container",
        "generated_id_prefix": "tp08-",
        "node_prototype_cell_id": "node-prototype",
        "edge_prototype_cell_id": "edge-prototype",
        "node_selector": "nodes",
        "edge_selector": "flows",
        "row_capacity": 25,
        "page_capacity": 100,
        "overflow_policy": "CONTINUATION_PAGE",
        "continuation_page_pattern": "Overview {page}",
        **overrides,
    }


def test_loads_typed_repeated_region_contract(tmp_path: Path) -> None:
    loaded = load_profile_from_path(_profile(tmp_path, _region()))
    region = loaded.generated_regions[0]
    assert region.region_id == "FLOW_REGION"
    assert region.row_capacity == 25
    assert region.page_capacity == 100
    assert region.generated_id_prefix == "tp08-"


def test_profile_hash_changes_when_capacity_changes(tmp_path: Path) -> None:
    first = load_profile_from_path(_profile(tmp_path / "first", _region(row_capacity=10)))
    second = load_profile_from_path(_profile(tmp_path / "second", _region(row_capacity=11)))
    assert first.profile_hash != second.profile_hash


@pytest.mark.parametrize(
    "overrides, message",
    [
        ({"row_capacity": 0}, "row_capacity"),
        ({"page_capacity": 0}, "page_capacity"),
        ({"overflow_policy": "TRUNCATE"}, "overflow_policy"),
        ({"continuation_page_pattern": None}, "Continuation"),
        ({"unknown": "value"}, "fields mismatch"),
    ],
)
def test_rejects_unsafe_region_contracts(
    tmp_path: Path, overrides: dict[str, object], message: str
) -> None:
    with pytest.raises(ProfileValidationError, match=message):
        load_profile_from_path(_profile(tmp_path, _region(**overrides)))
