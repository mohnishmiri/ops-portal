"""Test-only CCPM profile; every source value and diagram is synthetic."""

from __future__ import annotations

import hashlib
import json
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from pathlib import Path

import pytest
from scripts import ccpm_test_profile as subject

from migration_intake.topology.compatibility import inspect_base
from migration_intake.topology.contracts import RenderCapability, serialize_snapshot_document
from migration_intake.topology.profiles.loader import (
    ProfileHashMismatchError,
    ProfileNotFoundError,
    list_available_profiles,
    load_profile,
    load_profile_from_path,
)
from migration_intake.topology.renderer import (
    RenderContext,
    RenderInput,
    RunMode,
    XmlParserLimits,
    render_label_only,
)
from migration_intake.topology.renderer.core import parse_diagram_safely
from migration_intake.topology.scope import ContextKey, ScopeSelection
from migration_intake.topology.strict_projection import project_v3_snapshot

NOW = datetime(2026, 9, 21, tzinfo=UTC)
SELECTION = ScopeSelection(
    "synthetic-app", "synthetic-intake", (ContextKey("TEST", "SYNTHETIC_SITE"),),
    "combined-overview-with-details",
)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def source():
    # No client template is read, even when it exists on the developer machine.
    return (
        b'<mxfile><diagram id="p1" name="Synthetic A"><mxGraphModel><root>'
        b'<mxCell id="r1"/><mxCell id="l1" parent="r1"/>'
        b'<mxCell id="n1" parent="l1" value="Protected A" vertex="1" style="fillColor=blue;">'
        b'<mxGeometry x="10" y="20" width="30" height="40" as="geometry"/></mxCell>'
        b'<mxCell vertex="1"><mxGeometry as="geometry"/></mxCell>'
        b'</root></mxGraphModel></diagram>'
        b'<diagram id="p2" name="Synthetic B"><mxGraphModel><root>'
        b'<mxCell id="r2"/><mxCell id="l2" parent="r2"/>'
        b'<mxCell id="n2" parent="l2" value="Protected B" vertex="1"/>'
        b'<mxCell id="e2" parent="l2" source="l2" target="n2" edge="1"/>'
        b'</root></mxGraphModel></diagram></mxfile>'
    )


def prepared():
    data = source()
    return subject.prepare_test_base(data, expected_sha256=digest(data))


def compatibility(data, profile):
    return inspect_base(
        data, profile, SELECTION, capability=RenderCapability.LABEL_ONLY,
        parser_policy=XmlParserLimits(),
        partition_views={SELECTION.ordered_contexts[0]: subject.CONTROL_PAGE},
    )


def projection(*, confirmed=True, acronym="SYN"):
    document = {
        "schema_version": "3.0.0",
        "application": {
            "id": "synthetic-app", "name": "Synthetic", "acronym": "SYN", "identifiers": [],
        },
        "catalog": {"id": "catalog", "version": "1.0.0", "source_sha256": "a" * 64,
                    "catalog_hash": "b" * 64, "compiler_version": "1.0.0"},
        "intake": {
            "id": "synthetic-intake", "state": "FROZEN", "frozen_at": "2026-09-21T00:00:00.000Z",
            "frozen_by": "actor", "row_version": 1, "content_epoch": 1,
        },
        "answers": [{"question_code": "CTL-002", "response_type": "TEXT_PAIR",
                     "value": {"first": "Synthetic Test App", "second": acronym},
                     "confirm_state": "CONFIRMED" if confirmed else "UNCONFIRMED",
                     "provenance_references": ["synthetic-evidence"]}],
        "interface_register": {"interface_epoch": 1, "rows": []},
        "resources": [], "relationships": [], "wave_util_rows": [], "permitted_gaps": [],
    }
    contract = serialize_snapshot_document(document)
    return project_v3_snapshot(
        contract.canonical_json, contract.sha256_hex, SELECTION, subject.fact_mappings(), NOW,
    )


def render(data, profile, projected):
    return render_label_only(
        RenderInput(
            projection=projected, projection_hash=projected.projection_hash,
            base_diagram_bytes=data, base_diagram_hash=digest(data),
            profile=profile, profile_hash=profile.profile_hash,
            render_context=RenderContext(
                "TEST", "SYNTHETIC_SITE", "LABEL_ONLY", "synthetic-run", RunMode.PREVIEW,
                "synthetic", "ACTIVE", "READY",
            ),
            recorded_timestamp=NOW,
        ),
        compatibility(data, profile),
    )


def test_profile_is_hash_verified_external_and_not_production_registered():
    profile = subject.load_test_profile()
    assert profile.profile_id == subject.PROFILE_ID
    assert profile.manifest.variant == "LABEL_ONLY"
    assert profile.manifest.approved_by is None
    assert len(profile.slots) == 2
    assert not profile.generated_regions
    assert subject.PROFILE_ID not in list_available_profiles()
    with pytest.raises(ProfileNotFoundError):
        load_profile(subject.PROFILE_ID)


def test_preparation_is_deterministic_and_preserves_normalized_source_pages():
    original = source()
    before = digest(original)
    first = subject.prepare_test_base(original, expected_sha256=before)
    assert first == subject.prepare_test_base(original, expected_sha256=before)
    original_pages = parse_diagram_safely(original).findall("./diagram")
    result_pages = parse_diagram_safely(first).findall("./diagram")
    assert len(result_pages) == 3
    assert [ET.tostring(p) for p in result_pages[:2]] == [ET.tostring(p) for p in original_pages]
    assert result_pages[-1].get("name") == subject.CONTROL_PAGE
    assert digest(original) == before


def test_render_changes_exactly_two_labels_and_preserves_source_and_geometry():
    data = prepared()
    profile = subject.load_test_profile()
    projected = projection()
    first = render(data, profile, projected)
    second = render(data, profile, projected)
    assert first.success
    assert first.diagnostics.changed_cells == 2
    assert {m.cell_id for m in first.diagnostics.mutations} == {
        "ccpm-test-name", "ccpm-test-acronym",
    }
    assert first.diagram_bytes == second.diagram_bytes
    assert first.manifest_hash == second.manifest_hash
    assert first.report_html == second.report_html
    assert first.manifest.run_mode == RunMode.PREVIEW.value
    assert b"Synthetic Test App" in first.diagram_bytes
    assert b"Acronym: SYN" in first.diagram_bytes
    before = parse_diagram_safely(data)
    after = parse_diagram_safely(first.diagram_bytes)
    assert [ET.tostring(p) for p in before.findall("./diagram")[:2]] == [
        ET.tostring(p) for p in after.findall("./diagram")[:2]
    ]
    for cell in after.iter("mxCell"):
        old = next(c for c in before.iter("mxCell") if c.get("id") == cell.get("id"))
        if cell.get("id") in {"ccpm-test-name", "ccpm-test-acronym"}:
            cell.set("value", old.get("value"))
        assert ET.tostring(cell) == ET.tostring(old)


@pytest.mark.parametrize("confirmed,acronym", [(False, "SYN"), (True, None)])
def test_missing_or_unconfirmed_facts_cannot_render(confirmed, acronym):
    output = render(
        prepared(), subject.load_test_profile(), projection(confirmed=confirmed, acronym=acronym),
    )
    assert not output.success


@pytest.mark.parametrize("replacement", [b"No marker", b"{{APPLICATION_NAME}}"])
def test_missing_or_duplicate_markers_are_incompatible(replacement):
    data = prepared().replace(b"{{APPLICATION_ACRONYM}}", replacement)
    assert not compatibility(data, subject.load_test_profile()).is_compatible


@pytest.mark.parametrize("data", [
    b"not xml",
    source().replace(b'id="n1"', b'id="ccpm-test-name"'),
    source().replace(b'Protected A', b'{{UNREVIEWED}}'),
    source().replace(b'name="Synthetic A"', b'name="CCPM Test Controls"'),
    source().replace(b'name="Synthetic B"', b'name="Synthetic A"'),
    source().replace(b'id="n1"', b'id="n2"'),
    source().replace(b'id="n1"', b''),
])
def test_unsafe_or_ambiguous_preparation_is_rejected(data):
    with pytest.raises(subject.TestBasePreparationError):
        subject.prepare_test_base(data, expected_sha256=digest(data))


def test_unprepared_base_wrong_digest_and_repreparation_are_rejected():
    assert not compatibility(source(), subject.load_test_profile()).is_compatible
    with pytest.raises(subject.TestBasePreparationError, match="digest"):
        subject.prepare_test_base(source(), expected_sha256="0" * 64)
    data = prepared()
    with pytest.raises(subject.TestBasePreparationError, match="already exists"):
        subject.prepare_test_base(data, expected_sha256=digest(data))


def test_modified_component_fails_hash_validation(tmp_path):
    for file in subject.PROFILE_PATH.glob("*.json"):
        (tmp_path / file.name).write_bytes(file.read_bytes())
    (tmp_path / "slots.json").write_bytes(b'{}')
    with pytest.raises(ProfileHashMismatchError):
        load_profile_from_path(tmp_path)


def test_cli_dry_run_and_explicit_write_never_overwrite_source(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(subject, "WORKSPACE", tmp_path)
    path = tmp_path / "synthetic.drawio"
    path.write_bytes(source())
    args = ["--source", str(path), "--expected-sha256", digest(source())]
    assert subject.main(args) == 0
    assert not json.loads(capsys.readouterr().out)["written"]
    assert list(tmp_path.iterdir()) == [path]
    with pytest.raises(SystemExit) as error:
        subject.main([*args, "--write", "--output", str(path)])
    assert error.value.code == 2
    assert path.read_bytes() == source()
    output = tmp_path / "derived.drawio"
    assert subject.main([*args, "--write", "--output", str(output)]) == 0
    assert output.read_bytes() == prepared()
    with pytest.raises(SystemExit):
        subject.main([*args, "--write", "--output", str(tmp_path.parent / "outside.drawio")])


def test_cli_handles_readable_file_with_denied_leaf_realpath(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(subject, "WORKSPACE", tmp_path)
    path = tmp_path / "synthetic.drawio"
    path.write_bytes(source())
    original_resolve = Path.resolve

    def restricted_resolve(self, *args, **kwargs):
        if self == path:
            raise PermissionError("Synthetic Windows leaf realpath restriction")
        return original_resolve(self, *args, **kwargs)

    monkeypatch.setattr(Path, "resolve", restricted_resolve)
    assert subject.main(["--source", str(path), "--expected-sha256", digest(source())]) == 0
    assert not json.loads(capsys.readouterr().out)["written"]
    assert path.read_bytes() == source()


def test_leaf_links_are_rejected_without_reading_target(tmp_path, monkeypatch):
    monkeypatch.setattr(subject, "WORKSPACE", tmp_path)
    monkeypatch.setattr(Path, "is_symlink", lambda _self: True)
    with pytest.raises(subject.TestBasePreparationError, match="not a link"):
        subject._workspace_file(tmp_path / "link.drawio")


def test_directory_links_and_traversal_cannot_escape_workspace(tmp_path, monkeypatch):
    monkeypatch.setattr(subject, "WORKSPACE", tmp_path)
    with pytest.raises(subject.TestBasePreparationError, match="inside this workspace"):
        subject._workspace_file(tmp_path / ".." / "outside.drawio")
    monkeypatch.setattr(Path, "is_symlink", lambda self: self.name == "linked")
    with pytest.raises(subject.TestBasePreparationError, match="not a link"):
        subject._workspace_file(tmp_path / "linked" / "input.drawio")


