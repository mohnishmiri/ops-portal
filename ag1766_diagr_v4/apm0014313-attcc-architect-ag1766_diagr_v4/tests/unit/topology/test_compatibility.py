"""Pure base/profile compatibility tests for C5.2."""

from __future__ import annotations

from dataclasses import replace

import pytest

from migration_intake.topology.compatibility import inspect_base
from migration_intake.topology.contracts import RenderCapability
from migration_intake.topology.profiles import load_profile
from migration_intake.topology.renderer import XmlParserLimits
from migration_intake.topology.scope import ContextKey, ScopeSelection


@pytest.fixture
def selection() -> ScopeSelection:
    return ScopeSelection(
        application_id="app-1",
        intake_id="intake-1",
        contexts=(ContextKey("PROD", "SITE_A"),),
        view_variant="combined-overview-with-details",
    )


@pytest.fixture
def label_profile():
    return load_profile("SYNTHETIC_LABEL_ONLY")


@pytest.fixture
def structural_profile():
    return load_profile("SYNTHETIC_STRUCTURAL")


def drawio_xml(*pages: tuple[str, str]) -> bytes:
    page_xml = []
    for index, (page_name, values) in enumerate(pages):
        root_id = index * 100
        page_xml.append(
            f'<diagram id="page-{index}" name="{page_name}">'
            "<mxGraphModel><root>"
            f'<mxCell id="{root_id}"/><mxCell id="{root_id + 1}" parent="{root_id}"/>'
            f'{values}'
            "</root></mxGraphModel></diagram>"
        )
    return f"<mxfile>{''.join(page_xml)}</mxfile>".encode()


def app_cell(cell_id: str = "2", value: str = "{{APPLICATION_NAME}}") -> str:
    return f'<mxCell id="{cell_id}" value="{value}" parent="1"/>'


def inspect(
    diagram: bytes,
    profile,
    selection: ScopeSelection,
    views: dict[ContextKey, str] | None = None,
    capability: RenderCapability = RenderCapability.LABEL_ONLY,
):
    return inspect_base(
        diagram,
        profile,
        selection,
        capability=capability,
        parser_policy=XmlParserLimits(),
        partition_views=(
            {selection.ordered_contexts[0]: "Overview"}
            if views is None
            else views
        ),
    )


def test_compatible_label_base_has_deterministic_inventory(label_profile, selection):
    diagram = drawio_xml(("Overview", app_cell()))

    first = inspect(diagram, label_profile, selection)
    second = inspect(diagram, label_profile, selection)

    assert first.is_compatible
    assert first.blocking_issues == ()
    assert first.inventory.pages[0].name == "Overview"
    assert first.inventory.cells[0].cell_id == "0"
    assert first.compatibility_key
    assert first.result_hash == second.result_hash
    assert first.inventory.inventory_hash == second.inventory.inventory_hash


def test_missing_slot_is_blocking(label_profile, selection):
    result = inspect(diagram=drawio_xml(("Overview", app_cell(value="Static"))), profile=label_profile, selection=selection)

    assert not result.is_compatible
    assert any(issue.code == "MISSING_SLOT" for issue in result.blocking_issues)


def test_duplicate_slot_match_is_blocking(label_profile, selection):
    values = app_cell("2") + app_cell("3")
    result = inspect(drawio_xml(("Overview", values)), label_profile, selection)

    assert not result.is_compatible
    assert any(issue.code == "SLOT_CARDINALITY" for issue in result.blocking_issues)


def test_ambiguous_page_binding_is_blocking(label_profile, selection):
    diagram = drawio_xml(
        ("Overview", app_cell("2")),
        ("Overview", app_cell("3")),
    )
    result = inspect(diagram, label_profile, selection)

    assert not result.is_compatible
    assert any(issue.code == "AMBIGUOUS_PAGE" for issue in result.blocking_issues)


def test_missing_partition_view_is_blocking(label_profile, selection):
    result = inspect(
        drawio_xml(("Overview", app_cell())),
        label_profile,
        selection,
        views={},
    )

    assert not result.is_compatible
    assert any(issue.code == "MISSING_PARTITION_VIEW" for issue in result.blocking_issues)


def test_unknown_marker_is_blocking(label_profile, selection):
    result = inspect(
        drawio_xml(("Overview", app_cell() + app_cell("3", "{{UNDECLARED}}"))),
        label_profile,
        selection,
    )

    assert not result.is_compatible
    assert any(issue.code == "UNRECOGNIZED_MARKER" for issue in result.blocking_issues)


def test_capability_must_match_profile_variant(label_profile, selection):
    result = inspect(
        drawio_xml(("Overview", app_cell())),
        label_profile,
        selection,
        capability=RenderCapability.STRUCTURAL,
    )

    assert not result.is_compatible
    assert any(issue.code == "CAPABILITY_MISMATCH" for issue in result.blocking_issues)


def test_parser_policy_changes_compatibility_key(label_profile, selection):
    diagram = drawio_xml(("Overview", app_cell()))
    first = inspect(diagram, label_profile, selection)
    second = inspect_base(
        diagram,
        label_profile,
        selection,
        capability=RenderCapability.LABEL_ONLY,
        parser_policy=XmlParserLimits(max_node_count=49_999),
        partition_views={selection.ordered_contexts[0]: "Overview"},
    )

    assert first.compatibility_key != second.compatibility_key


def test_profile_slot_selector_changes_result_hash(label_profile, selection):
    changed_slot = replace(
        label_profile.slots[0],
        page_selector={"page_name_pattern": "^Details$"},
    )
    changed_profile = replace(label_profile, slots=[changed_slot])
    result = inspect(drawio_xml(("Overview", app_cell())), changed_profile, selection)

    assert not result.is_compatible
    assert result.result_hash


def test_structural_profile_requires_declared_generated_region_container(
    structural_profile, selection
):
    result = inspect(
        drawio_xml(("Overview", app_cell())),
        structural_profile,
        selection,
        capability=RenderCapability.STRUCTURAL,
    )

    assert result.is_compatible
    assert result.blocking_issues == ()


def test_structural_profile_blocks_missing_generated_region_container(
    structural_profile, selection
):
    diagram = (
        b'<mxfile><diagram id="page-0" name="Overview"><mxGraphModel><root>'
        b'<mxCell id="0"/><mxCell id="2" value="{{APPLICATION_NAME}}" parent="0"/>'
        b"</root></mxGraphModel></diagram></mxfile>"
    )
    result = inspect(
        diagram,
        structural_profile,
        selection,
        capability=RenderCapability.STRUCTURAL,
    )

    assert not result.is_compatible
    assert any(issue.code == "MISSING_GENERATED_REGION" for issue in result.blocking_issues)
