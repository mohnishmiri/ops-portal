from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.models.optimization import RecommendationCategory, RecommendationPriority
from app.services.optimization_service import (
    QUERY_ORPHANED_NICS,
    OptimizationService,
    _advisor_display_name,
    _iso_duration_label,
    _looks_like_guid,
    _looks_like_region,
    _parse_resource_id,
)

# ── Advisor resource-id / display-name helpers ─────────────────────────


def test_parse_resource_id_extracts_rg_name_type() -> None:
    parsed = _parse_resource_id(
        "/subscriptions/abc/resourceGroups/rg-prod/providers/Microsoft.Compute/virtualMachines/vm-web-01"
    )
    assert parsed == {
        "resource_group": "rg-prod",
        "resource_name": "vm-web-01",
        "resource_type": "Microsoft.Compute/virtualMachines",
    }


def test_parse_resource_id_handles_empty_and_garbage() -> None:
    assert _parse_resource_id("")["resource_name"] == ""
    assert _parse_resource_id("not-a-real-id")["resource_name"] == ""


def test_looks_like_guid() -> None:
    assert _looks_like_guid("d1516897-3b06-465d-8d78-d1e572eb2e9c")
    assert not _looks_like_guid("vm-web-01")
    assert not _looks_like_guid("")


def test_looks_like_region() -> None:
    assert _looks_like_region("eastus2")
    assert _looks_like_region("WestEurope")  # case-insensitive
    assert not _looks_like_region("vm-eastus2-prod")
    assert not _looks_like_region("")


def test_advisor_display_name_prefers_parsed_resource_name_over_impacted_value() -> None:
    """ARM resource ID is more authoritative than impacted_value (which is
    sometimes a region or subscription GUID for aggregate recs)."""
    parsed = {"resource_group": "rg", "resource_name": "vm-web-01", "resource_type": ""}
    assert _advisor_display_name("eastus2", parsed, {}) == "vm-web-01"


def test_advisor_display_name_falls_back_to_parsed_when_guid() -> None:
    parsed = {"resource_group": "rg", "resource_name": "vm-web-01", "resource_type": ""}
    name = _advisor_display_name("d1516897-3b06-465d-8d78-d1e572eb2e9c", parsed, {})
    assert name == "vm-web-01"


def test_iso_duration_label() -> None:
    assert _iso_duration_label("P1Y") == "1yr"
    assert _iso_duration_label("P3Y") == "3yr"
    assert _iso_duration_label("P1M") == "1mo"
    assert _iso_duration_label("") == ""


def test_advisor_display_name_uses_sku_key_for_reservations() -> None:
    """Azure Advisor uses 'sku' (not 'targetSku') in extended_properties for
    BuyCachesReservedCapacity and BuyVirtualMachineReservedInstances recs.
    Format: 'Nx SKU · Nyr RI' when quantity > 1, 'SKU · Nyr RI' when qty == 1.
    The term suffix (e.g. '· 3yr RI') distinguishes rows with the same SKU but
    different reservation terms and makes it clear these are RI recs, not VM names."""
    parsed = {"resource_group": "", "resource_name": "", "resource_type": ""}
    # With quantity and term
    assert (
        _advisor_display_name(
            "eastus2",
            parsed,
            {
                "sku": "Azure_Redis_Cache_Premium_P1_Cache",
                "region": "eastus2",
                "recommendedQuantity": "5",
                "term": "P1Y",
            },
        )
        == "5× Azure_Redis_Cache_Premium_P1_Cache · 1yr RI"
    )
    assert (
        _advisor_display_name(
            "eastus2",
            parsed,
            {"sku": "Standard_D64s_v3", "region": "eastus2", "recommendedQuantity": "3.0", "term": "P3Y"},
        )
        == "3× Standard_D64s_v3 · 3yr RI"
    )
    # Quantity == 1 with term → no qty prefix, term suffix present
    assert (
        _advisor_display_name("eastus2", parsed, {"sku": "Standard_D64s_v3", "recommendedQuantity": "1", "term": "P1Y"})
        == "Standard_D64s_v3 · 1yr RI"
    )
    # No term key → bare "RI" suffix
    assert _advisor_display_name("eastus2", parsed, {"sku": "Standard_D64s_v3"}) == "Standard_D64s_v3 RI"
    # Real API uses "qty" key, not "recommendedQuantity"
    assert (
        _advisor_display_name("eastus2", parsed, {"sku": "Standard_D64s_v3", "qty": "3", "term": "P3Y"})
        == "3× Standard_D64s_v3 · 3yr RI"
    )
    # Fallback key: "targetSku" (older Advisor rec shapes)
    assert (
        _advisor_display_name(
            "d1516897-3b06-465d-8d78-d1e572eb2e9c",
            parsed,
            {"targetSku": "Standard_D4s_v3", "region": "eastus", "term": "P1Y"},
        )
        == "Standard_D4s_v3 · 1yr RI"
    )


def test_advisor_display_name_uses_impacted_value_when_meaningful() -> None:
    """If impacted_value is a real resource name (not GUID, not region),
    and there's no parsed name or targetSku, use it."""
    parsed = {"resource_group": "", "resource_name": "", "resource_type": ""}
    assert _advisor_display_name("my-vm-01", parsed, {}) == "my-vm-01"


def test_advisor_display_name_drops_region_when_no_better_option() -> None:
    """A bare region string is never a useful Resource column value."""
    parsed = {"resource_group": "", "resource_name": "", "resource_type": ""}
    # No targetSku, no parsed name, impacted_value is a region → fallback string.
    assert _advisor_display_name("eastus2", parsed, {}) == "Recommendation"


async def _fake_resource_graph(self, query: str, subscription_ids=None):
    if "microsoft.compute/snapshots" in query:
        return [
            {
                "id": "/subscriptions/sub-1/resourceGroups/rg/providers/Microsoft.Compute/snapshots/orphaned-snap",
                "name": "orphaned-snap",
                "resourceGroup": "rg",
                "subscriptionId": "sub-1",
                "location": "eastus2",
                "diskSizeGB": "128",
                "sourceResourceId": "/subscriptions/sub-1/resourceGroups/rg/providers/Microsoft.Compute/disks/deleted-disk",
                "sourceExists": False,
            },
            {
                "id": "/subscriptions/sub-1/resourceGroups/rg/providers/Microsoft.Compute/snapshots/attached-snap",
                "name": "attached-snap",
                "resourceGroup": "rg",
                "subscriptionId": "sub-1",
                "location": "eastus2",
                "diskSizeGB": "64",
                "sourceResourceId": "/subscriptions/sub-1/resourceGroups/rg/providers/Microsoft.Compute/disks/live-disk",
                "sourceExists": True,
            },
            {
                "id": "/subscriptions/sub-1/resourceGroups/rg/providers/Microsoft.Compute/snapshots/manual-snap",
                "name": "manual-snap",
                "resourceGroup": "rg",
                "subscriptionId": "sub-1",
                "location": "eastus2",
                "diskSizeGB": "32",
                "sourceResourceId": "",
                "sourceExists": False,
            },
        ]
    if "microsoft.compute/disks" in query:
        return []
    if "microsoft.network/privateendpoints" in query:
        return [
            {
                "id": "/subscriptions/sub-1/resourceGroups/rg/providers/Microsoft.Network/privateEndpoints/pe-disconnected",
                "name": "pe-disconnected",
                "resourceGroup": "rg",
                "subscriptionId": "sub-1",
                "location": "eastus2",
                "connectionStatus": "Disconnected",
            },
            {
                "id": "/subscriptions/sub-1/resourceGroups/rg/providers/Microsoft.Network/privateEndpoints/pe-disconnected",
                "name": "pe-disconnected",
                "resourceGroup": "rg",
                "subscriptionId": "sub-1",
                "location": "eastus2",
                "connectionStatus": "Disconnected",
            },
        ]
    if "microsoft.network/networkinterfaces" in query:
        return []
    return []


@pytest.mark.anyio
async def test_every_snapshot_past_the_age_threshold_is_flagged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The query returns snapshots older than 30 days; all are retirable, orphans ranked higher."""
    service = OptimizationService()
    monkeypatch.setattr(OptimizationService, "_run_resource_graph_query", _fake_resource_graph)

    recommendations = await service.detect_idle_resources(["sub-1"])
    snaps = {
        r.resource.resource_name: r for r in recommendations if r.category == RecommendationCategory.ORPHANED_SNAPSHOTS
    }

    assert set(snaps) == {"orphaned-snap", "attached-snap", "manual-snap"}
    assert snaps["orphaned-snap"].orphaned is True
    assert snaps["orphaned-snap"].title == "Orphaned snapshot: orphaned-snap"
    assert snaps["orphaned-snap"].priority == RecommendationPriority.MEDIUM
    assert snaps["attached-snap"].orphaned is False
    assert snaps["attached-snap"].title == "Old snapshot: attached-snap"
    assert snaps["attached-snap"].priority == RecommendationPriority.LOW
    assert snaps["manual-snap"].orphaned is False  # no recorded source is not "orphaned"
    assert "estimated from size" in snaps["orphaned-snap"].description


@pytest.mark.anyio
async def test_snapshot_cost_uses_billed_amount_when_synced(monkeypatch: pytest.MonkeyPatch) -> None:
    service = OptimizationService()
    monkeypatch.setattr(OptimizationService, "_run_resource_graph_query", _fake_resource_graph)

    async def billed(self, resource_type, subscription_ids, db):
        if resource_type == "microsoft.compute/snapshots":
            return {("sub-1", "rg", "orphaned-snap"): Decimal("8.19")}
        return {}

    monkeypatch.setattr(OptimizationService, "_billed_monthly_costs", billed)
    recommendations = await service.detect_idle_resources(["sub-1"])
    snap = next(r for r in recommendations if r.resource.resource_name == "orphaned-snap")

    # 128 GB x $0.05 would claim $6.40; Azure billed $8.19.
    assert snap.estimated_monthly_savings == Decimal("8.19")
    assert "billed cost, last 30 days" in snap.description


@pytest.mark.anyio
async def test_failed_check_is_reported_unavailable_not_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    async def flaky(self, query: str, subscription_ids=None):
        if "microsoft.compute/snapshots" in query:
            raise RuntimeError("Resource Graph 429")
        return await _fake_resource_graph(self, query, subscription_ids)

    async def no_advisor(self, subscription_ids=None, unavailable=None):
        return []

    service = OptimizationService()
    monkeypatch.setattr(OptimizationService, "_run_resource_graph_query", flaky)
    monkeypatch.setattr(OptimizationService, "_get_advisor_recommendations", no_advisor)

    summary = await service._optimization_summary_live(["sub-1"])

    assert summary.wastage.unavailable_checks == ["Snapshots"]
    assert summary.wastage.orphaned_snapshots_count == 0
    # The other checks still ran.
    assert summary.wastage.disconnected_private_endpoints_count == 1


@pytest.mark.anyio
async def test_summary_counts_every_recommendation_not_the_first_50(monkeypatch: pytest.MonkeyPatch) -> None:
    async def many_nics(self, query: str, subscription_ids=None):
        if "microsoft.network/networkinterfaces" in query:
            return [
                {"id": f"nic-{i}", "name": f"nic-{i}", "resourceGroup": "rg", "subscriptionId": "sub-1"}
                for i in range(60)
            ]
        return await _fake_resource_graph(self, query, subscription_ids)

    async def no_advisor(self, subscription_ids=None, unavailable=None):
        return []

    service = OptimizationService()
    monkeypatch.setattr(OptimizationService, "_run_resource_graph_query", many_nics)
    monkeypatch.setattr(OptimizationService, "_get_advisor_recommendations", no_advisor)

    summary = await service._optimization_summary_live(["sub-1"])

    assert summary.total_recommendations == 60 + 3 + 1  # NICs + snapshots + private endpoint
    idle = next(d for d in summary.wastage.details if d.category == "Idle Resources")
    assert idle.count == 60
    assert summary.wastage.snapshots_source_deleted_count == 1


@pytest.mark.anyio
async def test_resource_graph_query_follows_every_page(monkeypatch: pytest.MonkeyPatch) -> None:
    pages = [
        SimpleNamespace(data=[{"id": "a"}, {"id": "b"}], skip_token="page-2"),
        SimpleNamespace(data=[{"id": "c"}], skip_token=None),
    ]
    tokens: list[str | None] = []

    class _Client:
        def resources(self, request):
            tokens.append(request.options.skip_token)
            return pages.pop(0)

        def close(self):
            return None

    monkeypatch.setattr("app.services.optimization_service._get_resource_graph_client", lambda _cred: _Client())
    rows = await OptimizationService()._run_resource_graph_query("Resources", ["sub-1"])

    assert [r["id"] for r in rows] == ["a", "b", "c"]
    assert tokens == [None, "page-2"]


def test_orphaned_nic_query_excludes_nics_owned_by_private_endpoints() -> None:
    # 532 of 535 VM-less NICs in ATTCC belonged to private endpoints / private link services.
    assert "isnull(properties.privateEndpoint)" in QUERY_ORPHANED_NICS
    assert "isnull(properties.privateLinkService)" in QUERY_ORPHANED_NICS
    assert "isempty(managedBy)" in QUERY_ORPHANED_NICS


@pytest.mark.anyio
async def test_detect_idle_resources_maps_disconnected_private_endpoints(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = OptimizationService()
    monkeypatch.setattr(OptimizationService, "_run_resource_graph_query", _fake_resource_graph)

    recommendations = await service.detect_idle_resources(["sub-1"])

    disconnected = [r for r in recommendations if r.category == RecommendationCategory.NETWORK_OPTIMIZATION]

    assert len(disconnected) == 1
    assert disconnected[0].resource.resource_name == "pe-disconnected"
    assert disconnected[0].action_required.startswith("Delete disconnected private endpoint")
