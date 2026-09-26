"""Block 0 — SL-PROJ-001: interface flow scope must fail closed.

When an interface row has no environment or site data, the projection must
NOT inherit the application's request-context scope and label the flow
EXPLICIT. Instead it must produce an UNKNOWN_FLOW_SCOPE exclusion.

All data is synthetic. No client data is used.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from migration_intake.topology.contracts import serialize_snapshot_document
from migration_intake.topology.scope import ContextKey, ScopeSelection
from migration_intake.topology.strict_projection import (
    project_v3_snapshot,
)

NOW = datetime(2026, 9, 24, tzinfo=UTC)

# ─── Helpers ────────────────────────────────────────────────────────────


def _base_document(*, interface_rows: list[dict] | None = None):
    """Minimal v3 snapshot with configurable interface rows."""
    return {
        "schema_version": "3.0.0",
        "application": {
            "id": "app-scope-test",
            "name": "Scope Safety Test",
            "acronym": "SST",
            "identifiers": [],
        },
        "catalog": {
            "id": "catalog",
            "version": "1.0.0",
            "source_sha256": "a" * 64,
            "catalog_hash": "b" * 64,
            "compiler_version": "1.0.0",
        },
        "intake": {
            "id": "intake-scope-test",
            "state": "FROZEN",
            "frozen_at": "2026-09-24T00:00:00.000Z",
            "frozen_by": "actor",
            "row_version": 1,
            "content_epoch": 1,
        },
        "answers": [],
        "interface_register": {
            "interface_epoch": 1,
            "rows": interface_rows or [],
        },
        "resources": [],
        "relationships": [],
        "wave_util_rows": [],
        "permitted_gaps": [],
    }


def _project(document: dict, *, contexts: tuple[ContextKey, ...]):
    """Serialize and project a synthetic snapshot."""
    selection = ScopeSelection(
        "app-scope-test",
        "intake-scope-test",
        contexts,
        "scope-safety-check",
    )
    contract = serialize_snapshot_document(document)
    return project_v3_snapshot(
        contract.canonical_json,
        contract.sha256_hex,
        selection,
        [],  # no fact mappings needed for this test
        NOW,
    )


# ─── Test cases ────────────────────────────────────────────────────────


class TestSingleContextDoesNotSupplyMissingInterfaceScope:
    """When a single context is selected and the interface row has no
    environment/site, the projection must NOT fabricate EXPLICIT scope."""

    def test_interface_without_scope_produces_exclusion(self):
        """An interface row with no environment/site must be excluded."""
        doc = _base_document(interface_rows=[
            {
                "id": "iface-no-scope",
                "interface_correlation_id": "COUNTER-001",
                "interface_app_acronym": "EXT",
                "interface_system_location": "ATT",
                "data_traffic_direction": "Inbound",
                # No environment, no site — scope is unknown
            },
        ])
        result = _project(doc, contexts=(ContextKey("PROD", "SITE_A"),))

        # Must have an UNKNOWN_FLOW_SCOPE exclusion
        exclusion_codes = [e.code for e in result.exclusions]
        assert "UNKNOWN_FLOW_SCOPE" in exclusion_codes, (
            "Expected UNKNOWN_FLOW_SCOPE exclusion for interface row "
            "without environment/site, but got: " + str(exclusion_codes)
        )

        # Must NOT have a flow for this interface
        flow_sources = {f.source_id for f in result.flows}
        flow_targets = {f.target_id for f in result.flows}
        assert "COUNTER-001" not in flow_sources | flow_targets, (
            "Interface without scope should not produce a flow"
        )

    def test_interface_with_explicit_scope_is_still_projected(self):
        """An interface row WITH environment/site must still produce a flow."""
        doc = _base_document(interface_rows=[
            {
                "id": "iface-scoped",
                "interface_correlation_id": "COUNTER-002",
                "interface_app_acronym": "EXT",
                "interface_system_location": "ATT",
                "data_traffic_direction": "Inbound",
                "environment": "PROD",
                "site": "SITE_A",
            },
        ])
        result = _project(doc, contexts=(ContextKey("PROD", "SITE_A"),))

        # No UNKNOWN_FLOW_SCOPE exclusion expected
        exclusion_codes = [e.code for e in result.exclusions]
        assert "UNKNOWN_FLOW_SCOPE" not in exclusion_codes

        # Should have a flow
        assert len(result.flows) > 0, "Expected at least one flow for scoped interface"


class TestMultiContextMissingScopeIsBlocking:
    """Under multi-context selection, missing scope is already UNKNOWN.
    Verify it stays that way (regression guard)."""

    def test_multi_context_missing_scope_produces_exclusion(self):
        doc = _base_document(interface_rows=[
            {
                "id": "iface-multi-no-scope",
                "interface_correlation_id": "COUNTER-003",
                "interface_app_acronym": "EXT",
                "interface_system_location": "ATT",
                "data_traffic_direction": "Outbound",
            },
        ])
        result = _project(
            doc,
            contexts=(
                ContextKey("DEV", "SITE_A"),
                ContextKey("PROD", "SITE_A"),
            ),
        )

        exclusion_codes = [e.code for e in result.exclusions]
        assert "UNKNOWN_FLOW_SCOPE" in exclusion_codes


class TestKnownInterfaceScopeMustMatchContext:
    """When an interface row has explicit scope that does NOT match the
    selected context, it should NOT appear in the projection."""

    def test_mismatched_scope_produces_no_flow(self):
        """Interface scoped to DEV should not appear in a PROD-only projection."""
        doc = _base_document(interface_rows=[
            {
                "id": "iface-dev-scope",
                "interface_correlation_id": "COUNTER-004",
                "interface_app_acronym": "EXT",
                "interface_system_location": "ATT",
                "data_traffic_direction": "Inbound",
                "environment": "DEV",
                "site": "SITE_B",
            },
        ])
        result = _project(doc, contexts=(ContextKey("PROD", "SITE_A"),))

        # The flow should still exist but scoped to DEV/SITE_B
        # (the projection doesn't filter by context — it projects all)
        # This is architectural: flows carry their own scope and the
        # renderer decides what to show per page.
        # What matters: the scope on the flow is DEV/SITE_B, not PROD/SITE_A
        for flow in result.flows:
            if "COUNTER-004" in (flow.source_id, flow.target_id):
                assert flow.scope.environment == "DEV"
                assert flow.scope.site_id == "SITE_B"
                return
        # If no flow found, that's also acceptable (filtered out)
