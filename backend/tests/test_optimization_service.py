import pytest

from app.models.optimization import RecommendationCategory
from app.services.optimization_service import OptimizationService


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
