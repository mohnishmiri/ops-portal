"""TP09 repeated node/edge structural renderer tests."""

from __future__ import annotations

import copy
import hashlib
from datetime import UTC, datetime
from types import SimpleNamespace

from migration_intake.topology.profiles import load_profile
from migration_intake.topology.renderer import (
    RenderContext,
    RenderInput,
    RunMode,
    render_structural,
)


def base() -> bytes:
    return b'<mxfile><diagram name="Overview"><mxGraphModel><root><mxCell id="0"/><mxCell id="1" parent="0"/><mxCell id="2" parent="1" value="{{APPLICATION_NAME}}" vertex="1"><mxGeometry x="0" y="0" width="180" height="30" as="geometry"/></mxCell><mxCell id="3" parent="1" edge="1" source="2" target="2"/></root></mxGraphModel></diagram></mxfile>'


def projection(nodes: int = 2) -> dict[str, object]:
    return {
        "application": {"name": "Synthetic"},
        "nodes": [
            {"node_id": f"NODE-{index}", "kind": "ENDPOINT", "scope": {}, "provenance": []}
            for index in range(nodes)
        ],
        "flows": [
            {
                "source_id": "NODE-0",
                "target_id": "NODE-1",
                "direction": "OUTBOUND",
                "relationship_type": "INTERFACE_FLOW",
                "protocol": "HTTPS",
                "port": "443",
                "scope": {},
                "provenance": [],
            }
        ]
        if nodes >= 2
        else [],
    }


def render(source: dict[str, object]):
    raw = base()
    digest = hashlib.sha256(
        __import__("json").dumps(source, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    profile = load_profile("SYNTHETIC_STRUCTURAL")
    return render_structural(
        RenderInput(
            projection=source,
            projection_hash=digest,
            base_diagram_bytes=raw,
            base_diagram_hash=hashlib.sha256(raw).hexdigest(),
            profile=profile,
            profile_hash=profile.profile_hash,
            render_context=RenderContext(
                "PROD",
                "SITE_A",
                profile.profile_id,
                "run",
                RunMode.PREVIEW,
                "actor",
                "FROZEN",
                "READY",
            ),
            recorded_timestamp=datetime(2026, 9, 22, tzinfo=UTC),
        ),
        SimpleNamespace(
            is_compatible=True,
            base_hash=hashlib.sha256(raw).hexdigest(),
            profile_hash=profile.profile_hash,
            slot_matches=(
                SimpleNamespace(slot_id="APPLICATION_NAME", page_name="Overview", cell_ids=("2",)),
            ),
        ),
    )


def test_repeated_nodes_and_edges_have_stable_ids_and_endpoints() -> None:
    output = render(projection())
    assert output.success
    text = output.diagram_bytes.decode()
    assert "structural-node-" in text
    assert "structural-edge-" in text
    assert 'source="structural-node-' in text
    assert 'target="structural-node-' in text


def test_same_projection_is_byte_deterministic() -> None:
    source = projection()
    assert render(source).diagram_bytes == render(copy.deepcopy(source)).diagram_bytes


def test_capacity_overflow_fails_without_partial_output() -> None:
    output = render(projection(101))
    assert not output.success
    assert output.diagram_bytes == b""
    assert "capacity" in (output.error_message or "")
