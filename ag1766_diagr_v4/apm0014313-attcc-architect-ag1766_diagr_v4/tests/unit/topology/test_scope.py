"""Synthetic C2.2 multi-context graph contract tests."""

from __future__ import annotations

import pytest

from migration_intake.topology.scope import (
    ContextKey,
    RelationshipType,
    ResourceLifecycle,
    ScopeContractError,
    ScopeSelection,
    ScopedResourceRef,
    TopologyGraph,
    TopologyRelationship,
)


def _selection() -> ScopeSelection:
    return ScopeSelection(
        application_id="app-synthetic",
        intake_id="intake-synthetic",
        contexts=(ContextKey("PROD", "SITE_B"), ContextKey("DEV", "SITE_A")),
        view_variant="combined-overview-with-details",
    )


def test_selection_hash_and_order_are_request_order_independent():
    first = _selection()
    second = ScopeSelection(
        application_id=first.application_id,
        intake_id=first.intake_id,
        contexts=tuple(reversed(first.contexts)),
        view_variant=first.view_variant,
    )
    assert first.ordered_contexts == tuple(sorted(first.contexts))
    assert first.selection_hash == second.selection_hash


def test_duplicate_context_is_rejected():
    with pytest.raises(ScopeContractError, match="Duplicate"):
        ScopeSelection(
            application_id="app",
            intake_id="intake",
            contexts=(ContextKey("DEV", "SITE_A"), ContextKey("DEV", "SITE_A")),
            view_variant="overview",
        )


def test_repeated_logical_names_in_contexts_have_distinct_scope_keys():
    first = ScopedResourceRef(
        "resource-dev", "vpc-main", "VPC", ResourceLifecycle.TARGET, ContextKey("DEV", "SITE_A")
    )
    second = ScopedResourceRef(
        "resource-prod", "vpc-main", "VPC", ResourceLifecycle.TARGET, ContextKey("PROD", "SITE_A")
    )
    assert first.logical_key == second.logical_key
    assert first.scope_key != second.scope_key


def test_valid_reviewed_dr_relation_survives_once_semantically():
    selection = ScopeSelection(
        application_id="app-synthetic",
        intake_id="intake-synthetic",
        contexts=(ContextKey("PROD", "SITE_A"), ContextKey("PROD", "SITE_B")),
        view_variant="combined-overview-with-details",
    )
    primary = ScopedResourceRef(
        "placement-a", "primary", "PLACEMENT", ResourceLifecycle.TARGET, ContextKey("PROD", "SITE_A")
    )
    dr = ScopedResourceRef(
        "placement-b", "dr", "PLACEMENT", ResourceLifecycle.TARGET, ContextKey("PROD", "SITE_B")
    )
    relation = TopologyRelationship(
        "dr-relation", RelationshipType.DR_PAIR, primary.resource_id, dr.resource_id, reviewed=True
    )
    graph = TopologyGraph(selection, (primary, dr), (relation,))
    reversed_graph = TopologyGraph(selection, (dr, primary), (relation,))
    assert graph.graph_hash == reversed_graph.graph_hash


def test_containment_cannot_cross_contexts():
    selection = _selection()
    parent = ScopedResourceRef(
        "vpc-dev", "vpc-main", "VPC", ResourceLifecycle.TARGET, ContextKey("DEV", "SITE_A")
    )
    child = ScopedResourceRef(
        "subnet-prod", "subnet-main", "SUBNET", ResourceLifecycle.TARGET, ContextKey("PROD", "SITE_B")
    )
    relation = TopologyRelationship(
        "invalid-containment", RelationshipType.CONTAINS, parent.resource_id, child.resource_id, reviewed=True
    )
    with pytest.raises(ScopeContractError, match="context boundaries"):
        TopologyGraph(selection, (parent, child), (relation,))


def test_unreviewed_or_missing_endpoint_relationship_is_rejected():
    selection = _selection()
    resource = ScopedResourceRef(
        "compute-dev", "compute", "COMPUTE", ResourceLifecycle.TARGET, ContextKey("DEV", "SITE_A")
    )
    with pytest.raises(ScopeContractError, match="Unreviewed"):
        TopologyGraph(
            selection,
            (resource,),
            (TopologyRelationship("unreviewed", RelationshipType.COMPUTE_USES_SECURITY_GROUP, resource.resource_id, "missing"),),
        )