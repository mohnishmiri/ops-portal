import pytest

from app.models.optimization import RecommendationCategory
from app.services.optimization_service import (
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
            {"sku": "Azure_Redis_Cache_Premium_P1_Cache", "region": "eastus2", "recommendedQuantity": "5", "term": "P1Y"},
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
async def test_detect_idle_resources_filters_non_orphaned_snapshots(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = OptimizationService()

    monkeypatch.setattr(OptimizationService, "_run_resource_graph_query", _fake_resource_graph)

    recommendations = await service.detect_idle_resources(["sub-1"])

    orphaned = [r for r in recommendations if r.category == RecommendationCategory.ORPHANED_SNAPSHOTS]

    assert len(orphaned) == 1
    assert orphaned[0].resource.resource_name == "orphaned-snap"
    assert orphaned[0].title == "Orphaned snapshot: orphaned-snap"


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
