"""
AKS Insights Plugin — Operational intelligence for Azure Kubernetes Service.

Provides cluster health, node pool status, and workload metrics.
"""

import structlog
from fastapi import APIRouter, Depends

from app.auth import get_current_user
from app.core.azure_auth import get_azure_credential
from app.core.subscription_resolver import get_monitored_subscription_ids
from app.models.auth import UserContext
from app.plugins import PluginBase, PluginMetadata

logger = structlog.get_logger(__name__)

router = APIRouter()


@router.get("/clusters", summary="List AKS clusters")
async def list_clusters(
    user: UserContext = Depends(get_current_user),
) -> list[dict]:
    """List all AKS clusters across monitored subscriptions."""
    from azure.mgmt.containerservice import ContainerServiceClient

    credential = get_azure_credential()
    clusters = []

    for sub_id in await get_monitored_subscription_ids():
        try:
            client = ContainerServiceClient(credential, sub_id)
            for cluster in client.managed_clusters.list():
                clusters.append(
                    {
                        "name": cluster.name,
                        "resource_group": (cluster.id.split("/")[4] if cluster.id else ""),
                        "subscription_id": sub_id,
                        "location": cluster.location,
                        "kubernetes_version": cluster.kubernetes_version,
                        "provisioning_state": cluster.provisioning_state,
                        "node_count": sum((pool.count or 0) for pool in (cluster.agent_pool_profiles or [])),
                        "power_state": (cluster.power_state.code if cluster.power_state else "unknown"),
                    }
                )
            client.close()
        except Exception as e:
            logger.error("aks_list_failed", subscription_id=sub_id, error=str(e))

    return clusters


@router.get("/clusters/{resource_group}/{cluster_name}/nodepools", summary="Get node pools")
async def get_node_pools(
    resource_group: str,
    cluster_name: str,
    subscription_id: str | None = None,
    user: UserContext = Depends(get_current_user),
) -> list[dict]:
    """Get node pool details for a specific AKS cluster."""
    from azure.mgmt.containerservice import ContainerServiceClient

    monitored = await get_monitored_subscription_ids()
    sub_id = subscription_id or (monitored[0] if monitored else "")
    credential = get_azure_credential()
    client = ContainerServiceClient(credential, sub_id)

    pools = []
    try:
        for pool in client.agent_pools.list(resource_group, cluster_name):
            pools.append(
                {
                    "name": pool.name,
                    "vm_size": pool.vm_size,
                    "count": pool.count,
                    "min_count": pool.min_count,
                    "max_count": pool.max_count,
                    "os_type": pool.os_type,
                    "mode": pool.mode,
                    "provisioning_state": pool.provisioning_state,
                    "enable_auto_scaling": pool.enable_auto_scaling,
                    "kubernetes_version": pool.orchestrator_version,
                }
            )
    finally:
        client.close()

    return pools


class AKSInsightsPlugin(PluginBase):
    """AKS operational insights plugin."""

    def get_metadata(self) -> PluginMetadata:
        return PluginMetadata(
            name="AKS Insights",
            version="1.0.0",
            description="Azure Kubernetes Service operational intelligence — cluster health, node pools, workloads",
            required_roles=["read"],
            dashboard_widgets=[
                {"id": "aks-cluster-list", "title": "AKS Clusters", "type": "table"},
                {
                    "id": "aks-node-health",
                    "title": "Node Pool Health",
                    "type": "status",
                },
            ],
        )

    def get_router(self) -> APIRouter:
        return router


def create_plugin() -> PluginBase:
    """Plugin factory function."""
    return AKSInsightsPlugin()
