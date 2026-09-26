"""C5.3 governed LABEL_ONLY renderer tests."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime

import pytest

from migration_intake.topology.compatibility import inspect_base
from migration_intake.topology.contracts import RenderCapability, serialize_snapshot_document
from migration_intake.topology.profiles import load_profile
from migration_intake.topology.renderer import (
    RenderContext,
    RenderInput,
    RunMode,
    XmlParserLimits,
    render_label_only,
)
from migration_intake.topology.scope import ContextKey, ScopeSelection
from migration_intake.topology.strict_projection import (
    StrictFactMapping,
    project_v3_snapshot,
    serialize_strict_projection,
)


@pytest.fixture
def selection() -> ScopeSelection:
    return ScopeSelection(
        "app",
        "intake",
        (ContextKey("PROD", "SITE_A"),),
        "combined-overview-with-details",
    )


def snapshot_projection() -> object:
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
        "resources": [],
        "relationships": [],
        "wave_util_rows": [],
        "permitted_gaps": [],
    }
    contract = serialize_snapshot_document(document)
    return project_v3_snapshot(
        contract.canonical_json,
        contract.sha256_hex,
        ScopeSelection(
            "app", "intake", (ContextKey("PROD", "SITE_A"),), "combined-overview-with-details"
        ),
        (StrictFactMapping("CTL-002", "TEXT_PAIR", "application.name", "TEXT_PAIR.first"),),
        datetime(2026, 9, 18, tzinfo=UTC),
    )


def base_bytes() -> bytes:
    return (
        b'<mxfile><diagram id="page-0" name="Overview"><mxGraphModel><root>'
        b'<mxCell id="0"/><mxCell id="1" parent="0"/>'
        b'<mxCell id="2" value="Name: {{APPLICATION_NAME}}" parent="1"/>'
        b'<mxCell id="3" value="Manual content" parent="1"/>'
        b"</root></mxGraphModel></diagram></mxfile>"
    )


def render_input(
    profile,
    projection,
    base: bytes,
    *,
    projection_hash: str | None = None,
    base_hash: str | None = None,
) -> RenderInput:
    return RenderInput(
        projection=projection,
        projection_hash=projection_hash or projection.projection_hash,
        base_diagram_bytes=base,
        base_diagram_hash=base_hash or hashlib.sha256(base).hexdigest(),
        profile=profile,
        profile_hash=profile.profile_hash,
        render_context=RenderContext(
            "PROD",
            "SITE_A",
            "LABEL_ONLY",
            "run-1",
            RunMode.PREVIEW,
            "synthetic",
            "ACTIVE",
            "READY",
        ),
        recorded_timestamp=datetime(2026, 9, 18, 12, 0, tzinfo=UTC),
    )


def compatible(profile, selection, base):
    return inspect_base(
        base,
        profile,
        selection,
        capability=RenderCapability.LABEL_ONLY,
        parser_policy=XmlParserLimits(),
        partition_views={selection.ordered_contexts[0]: "Overview"},
    )


def test_governed_renderer_uses_real_profile_projection_and_compatibility(selection):
    profile = load_profile("SYNTHETIC_LABEL_ONLY")
    projection = snapshot_projection()
    base = base_bytes()

    output = render_label_only(
        render_input(profile, projection, base), compatible(profile, selection, base)
    )

    assert output.success
    assert output.result_status == "READY_FOR_REVIEW"
    assert output.diagnostics.attempted_writes == 1
    assert output.diagnostics.changed_cells == 1
    assert output.diagnostics.mutation_count == 1
    assert b"Name: Synthetic" in output.diagram_bytes
    assert b"Manual content" in output.diagram_bytes


def test_governed_renderer_replay_is_byte_stable(selection):
    profile = load_profile("SYNTHETIC_LABEL_ONLY")
    projection = snapshot_projection()
    base = base_bytes()
    compatibility = compatible(profile, selection, base)
    first = render_label_only(render_input(profile, projection, base), compatibility)
    second = render_label_only(render_input(profile, projection, base), compatibility)

    assert first.diagram_bytes == second.diagram_bytes
    assert first.diagram_hash == second.diagram_hash
    assert first.report_html == second.report_html
    assert first.manifest_hash == second.manifest_hash


def test_governed_renderer_consumes_persisted_projection_bytes(selection):
    profile = load_profile("SYNTHETIC_LABEL_ONLY")
    projection = snapshot_projection()
    persisted_projection = json.loads(serialize_strict_projection(projection))
    base = base_bytes()

    output = render_label_only(
        render_input(
            profile, persisted_projection, base, projection_hash=projection.projection_hash
        ),
        compatible(profile, selection, base),
    )

    assert output.success
    assert b"Name: Synthetic" in output.diagram_bytes


def test_governed_renderer_rejects_false_input_hashes(selection):
    profile = load_profile("SYNTHETIC_LABEL_ONLY")
    projection = snapshot_projection()
    base = base_bytes()
    output = render_label_only(
        render_input(profile, projection, base, base_hash="0" * 64),
        compatible(profile, selection, base),
    )

    assert not output.success
    assert "hash mismatch" in (output.error_message or "").lower()
    assert output.result_status == "FAILED"


def test_governed_renderer_blocks_unresolved_mandatory_fact(selection):
    profile = load_profile("SYNTHETIC_LABEL_ONLY")
    projection = snapshot_projection()
    base = base_bytes()
    empty_projection = type(projection)(
        projection.schema_version,
        projection.snapshot_id,
        projection.snapshot_hash,
        projection.application_id,
        projection.intake_id,
        projection.selection,
        tuple(
            type(partition)(partition.context, (), partition.resources)
            for partition in projection.partitions
        ),
        projection.shared_resources,
        projection.relationships,
        projection.nodes,
        projection.flows,
        projection.exclusions,
        projection.issues,
        projection.projection_hash,
    )
    output = render_label_only(
        render_input(profile, empty_projection, base), compatible(profile, selection, base)
    )

    assert not output.success
    assert "could not be resolved" in (output.error_message or "")
    assert output.diagnostics.binding.slots_unresolved == 1


def test_governed_renderer_allows_verified_noop(selection):
    profile = load_profile("SYNTHETIC_LABEL_ONLY")
    projection = snapshot_projection()
    base = base_bytes()
    projection = type(projection)(
        projection.schema_version,
        projection.snapshot_id,
        projection.snapshot_hash,
        projection.application_id,
        projection.intake_id,
        projection.selection,
        tuple(
            type(partition)(
                partition.context,
                tuple(
                    type(fact)(
                        fact.output_key,
                        "{{APPLICATION_NAME}}",
                        fact.provenance,
                        fact.source_question_code,
                    )
                    for fact in partition.facts
                ),
                partition.resources,
            )
            for partition in projection.partitions
        ),
        projection.shared_resources,
        projection.relationships,
        projection.nodes,
        projection.flows,
        projection.exclusions,
        projection.issues,
        projection.projection_hash,
    )
    compatibility = compatible(profile, selection, base)

    output = render_label_only(render_input(profile, projection, base), compatibility)

    assert output.success
    assert output.diagnostics.attempted_writes == 1
    assert output.diagnostics.changed_cells == 0
