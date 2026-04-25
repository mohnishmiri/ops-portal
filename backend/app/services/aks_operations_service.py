"""
AKS Operations Service — Cluster inventory, deployments, pods, and cronjobs management.

Provides enterprise-grade AKS operational capabilities using:
- Azure SDK for cluster inventory
- Kubernetes Python client for workload operations
- Azure Monitor for metrics
- 3-Tier data retrieval: Redis (L1) → PostgreSQL (L2) → Live API (L3)
"""

import asyncio
from datetime import datetime, timedelta
from functools import partial
from typing import Any

import httpx
import structlog
import urllib3
from azure.identity import DefaultAzureCredential
from azure.mgmt.containerservice import ContainerServiceClient
from kubernetes import client as k8s_client
from kubernetes.client.rest import ApiException
from sqlalchemy import delete, desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.subscription_resolver import get_monitored_subscription_ids
from app.models.database import (
    AKSClusterSnapshot,
    AKSNodePoolSnapshot,
    AzureResourceInventory,
    CronJobAuditHistory,
    DeploymentScaleHistory,
    PodUtilizationHistory,
)
from app.services.data_cache_service import (
    TTL,
    CacheKeys,
    data_cache,
)

# Suppress InsecureRequestWarning for private-link AKS endpoints
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

logger = structlog.get_logger(__name__)


class AKSOperationsService:
    """
    Enterprise AKS Operations Service.

    Provides:
    - Multi-subscription cluster inventory
    - Deployment management (scale, restart)
    - Pod resource observability
    - CronJob management
    """

    # K8s client cache TTL in seconds (tokens expire after ~1 hour)
    _K8S_CLIENT_TTL = 50 * 60  # 50 minutes

    def __init__(self, db_session: AsyncSession | None):
        self.db = db_session
        self.credential = DefaultAzureCredential()
        # Cached K8s clients with creation timestamps for TTL eviction
        self._k8s_clients: dict[
            str,
            tuple[k8s_client.AppsV1Api, k8s_client.CoreV1Api, k8s_client.BatchV1Api],
        ] = {}
        self._k8s_clients_ts: dict[str, float] = {}

    # ── DB helper methods (async-safe, None-tolerant) ──────────────────

    async def _db_add_and_commit(self, record) -> bool:
        """Add a record and commit. Returns False if DB is unavailable."""
        if self.db is None:
            logger.warning("db_unavailable", action="add_and_commit")
            return False
        try:
            self.db.add(record)
            await self.db.commit()
            return True
        except Exception as e:
            logger.error("db_commit_failed", error=str(e))
            await self.db.rollback()
            return False

    async def _db_commit(self) -> bool:
        """Commit current transaction. Returns False if DB is unavailable."""
        if self.db is None:
            return False
        try:
            await self.db.commit()
            return True
        except Exception as e:
            logger.error("db_commit_failed", error=str(e))
            await self.db.rollback()
            return False

    async def _refresh_cronjob_db_cache(self, cluster_id: str, namespace: str | None = None) -> None:
        """Refresh the DB-backed CronJob cache without failing the primary mutation."""
        if self.db is None:
            return

        try:
            await self.sync_cronjobs_to_db(cluster_id, namespace)
        except Exception as e:
            logger.warning(
                "cronjob_db_cache_refresh_failed",
                cluster_id=cluster_id,
                namespace=namespace,
                error=str(e),
            )

    # =========================================================================
    # A. CLUSTER INVENTORY
    # =========================================================================

    async def get_all_clusters(
        self,
        subscription_ids: list[str] | None = None,
        include_nodepools: bool = True,
        bypass_cache: bool = False,
    ) -> list[dict[str, Any]]:
        """
        Retrieve all AKS clusters across monitored subscriptions.

        Uses 3-tier cache: Redis (L1) → Live API (L3) → backfill Redis.

        Args:
            subscription_ids: Optional list of subscription IDs to filter
            include_nodepools: Whether to include node pool details
            bypass_cache: Force live API call, skip Redis

        Returns:
            List of cluster details with node pool information
        """
        cache_key = CacheKeys.cluster_list(subscription_ids)

        if not bypass_cache:
            cached, tier = await data_cache.get_or_fetch(
                key=cache_key,
                ttl=TTL.CLUSTER_LIST,
                fetch_fn=lambda: self._fetch_clusters_live(subscription_ids, include_nodepools),
            )
            return cached

        # bypass_cache — go straight to live
        return await self._fetch_clusters_live(subscription_ids, include_nodepools)

    async def _fetch_clusters_live(
        self,
        subscription_ids: list[str] | None = None,
        include_nodepools: bool = True,
    ) -> list[dict[str, Any]]:
        """Live API call to fetch all AKS clusters (L3)."""
        clusters = []
        subs = await self._get_subscriptions(subscription_ids)

        for sub in subs:
            try:
                aks_client = ContainerServiceClient(self.credential, sub["id"])
                # Run blocking Azure SDK call in a thread to avoid blocking the event loop
                cluster_list = await asyncio.to_thread(partial(list, aks_client.managed_clusters.list()))

                for cluster in cluster_list:
                    node_pools = []
                    total_node_count = 0
                    if include_nodepools and cluster.agent_pool_profiles:
                        for np in cluster.agent_pool_profiles:
                            total_node_count += np.count or 0
                            node_pools.append(
                                {
                                    "name": np.name,
                                    "vm_size": np.vm_size,
                                    "os_type": np.os_type,
                                    "count": np.count,
                                    "min_count": np.min_count,
                                    "max_count": np.max_count,
                                    "enable_auto_scaling": np.enable_auto_scaling,
                                    "node_image_version": np.node_image_version,
                                    "node_labels": (dict(np.node_labels) if np.node_labels else {}),
                                    "node_taints": (list(np.node_taints) if np.node_taints else []),
                                    "provisioning_state": np.provisioning_state,
                                    "mode": np.mode,
                                }
                            )

                    cluster_tags = dict(cluster.tags) if cluster.tags else {}
                    cluster_data = {
                        "id": cluster.id,
                        "name": cluster.name,
                        "subscription_id": sub["id"],
                        "subscription_name": sub["name"],
                        "resource_group": self._extract_resource_group(cluster.id),
                        "location": cluster.location,
                        "kubernetes_version": cluster.kubernetes_version,
                        "provisioning_state": cluster.provisioning_state,
                        "power_state": (cluster.power_state.code if cluster.power_state else None),
                        "fqdn": cluster.fqdn,
                        "node_count": total_node_count,
                        "node_pools": node_pools,
                        "tags": cluster_tags,
                        "environment": cluster_tags.get("env", "") or cluster_tags.get("environment", ""),
                    }

                    clusters.append(cluster_data)
                    logger.info("cluster_discovered", name=cluster.name, subscription=sub["id"])

            except Exception as e:
                logger.error("cluster_list_failed", subscription_id=sub["id"], error=str(e))

        logger.info("cluster_discovery_complete", total=len(clusters))
        return clusters

    async def get_cluster_details(
        self,
        cluster_id: str,
        subscription_id: str | None = None,
        resource_group: str | None = None,
        cluster_name: str | None = None,
        bypass_cache: bool = False,
    ) -> dict[str, Any] | None:
        """Get detailed information for a specific cluster.

        Uses 3-tier cache: Redis (L1) → Live API (L3) → backfill Redis.
        Accepts either a full Azure resource ID in ``cluster_id``, or individual parts.
        """
        cache_key = CacheKeys.cluster_detail(cluster_id)

        if not bypass_cache:
            cached, tier = await data_cache.get_or_fetch(
                key=cache_key,
                ttl=TTL.CLUSTER_DETAIL,
                fetch_fn=lambda: self._fetch_cluster_details_live(
                    cluster_id, subscription_id, resource_group, cluster_name
                ),
            )
            return cached

        return await self._fetch_cluster_details_live(cluster_id, subscription_id, resource_group, cluster_name)

    async def _fetch_cluster_details_live(
        self,
        cluster_id: str,
        subscription_id: str | None = None,
        resource_group: str | None = None,
        cluster_name: str | None = None,
    ) -> dict[str, Any] | None:
        """Live API call to fetch cluster details (L3)."""
        try:
            # Parse resource ID if individual parts not given
            if not all([subscription_id, resource_group, cluster_name]):
                parts = cluster_id.split("/")
                subscription_id = parts[2]
                resource_group = parts[4]
                cluster_name = parts[8]

            aks_client = ContainerServiceClient(self.credential, subscription_id)
            cluster = await asyncio.to_thread(aks_client.managed_clusters.get, resource_group, cluster_name)

            return {
                "id": cluster.id,
                "name": cluster.name,
                "subscription_id": subscription_id,
                "resource_group": resource_group,
                "location": cluster.location,
                "kubernetes_version": cluster.kubernetes_version,
                "provisioning_state": cluster.provisioning_state,
                "power_state": (cluster.power_state.code if cluster.power_state else None),
                "fqdn": cluster.fqdn,
                "dns_prefix": cluster.dns_prefix,
                "enable_rbac": cluster.enable_rbac,
                "network_profile": {
                    "network_plugin": (cluster.network_profile.network_plugin if cluster.network_profile else None),
                    "network_policy": (cluster.network_profile.network_policy if cluster.network_profile else None),
                    "service_cidr": (cluster.network_profile.service_cidr if cluster.network_profile else None),
                    "dns_service_ip": (cluster.network_profile.dns_service_ip if cluster.network_profile else None),
                },
                "addon_profiles": self._format_addon_profiles(cluster.addon_profiles),
                "identity": {
                    "type": cluster.identity.type if cluster.identity else None,
                    "principal_id": (cluster.identity.principal_id if cluster.identity else None),
                },
                "node_pools": [
                    {
                        "name": np.name,
                        "vm_size": np.vm_size,
                        "os_type": np.os_type,
                        "os_disk_size_gb": np.os_disk_size_gb,
                        "count": np.count,
                        "min_count": np.min_count,
                        "max_count": np.max_count,
                        "enable_auto_scaling": np.enable_auto_scaling,
                        "node_image_version": np.node_image_version,
                        "node_labels": dict(np.node_labels) if np.node_labels else {},
                        "node_taints": list(np.node_taints) if np.node_taints else [],
                        "provisioning_state": np.provisioning_state,
                        "mode": np.mode,
                        "max_pods": np.max_pods,
                    }
                    for np in (cluster.agent_pool_profiles or [])
                ],
                "tags": dict(cluster.tags) if cluster.tags else {},
            }

        except Exception as e:
            logger.error(
                "cluster_details_failed",
                cluster_name=cluster_name,
                error=str(e),
            )
            return None

    async def snapshot_clusters(
        self,
        subscription_ids: list[str] | None = None,
        user_id: str | None = None,
        user_email: str | None = None,
    ) -> dict[str, Any]:
        """
        Take a snapshot of all clusters for historical tracking.

        Returns:
            Dict with success status and snapshot count
        """
        clusters = await self.get_all_clusters(subscription_ids)
        snapshot_date = datetime.utcnow()
        count = 0

        for cluster in clusters:
            try:
                # Save cluster snapshot
                cluster_snapshot = AKSClusterSnapshot(
                    snapshot_date=snapshot_date,
                    cluster_id=cluster["id"],
                    cluster_name=cluster["name"],
                    subscription_id=cluster["subscription_id"],
                    subscription_name=cluster.get("subscription_name"),
                    resource_group=cluster["resource_group"],
                    location=cluster["location"],
                    kubernetes_version=cluster["kubernetes_version"],
                    provisioning_state=cluster["provisioning_state"],
                    power_state=cluster.get("power_state"),
                    fqdn=cluster.get("fqdn"),
                    node_pools=cluster.get("node_pools"),
                    tags=cluster.get("tags"),
                    raw_data=cluster,
                )
                self.db.add(cluster_snapshot)

                # Save node pool snapshots
                for np in cluster.get("node_pools", []):
                    np_snapshot = AKSNodePoolSnapshot(
                        snapshot_date=snapshot_date,
                        cluster_id=cluster["id"],
                        nodepool_name=np["name"],
                        vm_size=np["vm_size"],
                        os_type=np["os_type"],
                        node_count=np["count"],
                        min_count=np.get("min_count"),
                        max_count=np.get("max_count"),
                        enable_auto_scaling=np.get("enable_auto_scaling", False),
                        node_image_version=np.get("node_image_version"),
                        node_labels=np.get("node_labels"),
                        node_taints=np.get("node_taints"),
                        provisioning_state=np.get("provisioning_state"),
                        mode=np.get("mode"),
                        raw_data=np,
                    )
                    self.db.add(np_snapshot)

                count += 1

            except Exception as e:
                logger.error(
                    "cluster_snapshot_failed",
                    cluster_name=cluster["name"],
                    error=str(e),
                )

        await self._db_commit()
        logger.info("cluster_snapshot_completed", count=count, user=user_email)
        return {"success": True, "clusters_snapshotted": count}

    # =========================================================================
    # B. DEPLOYMENT MANAGEMENT
    # =========================================================================

    async def list_deployments(
        self,
        cluster_id: str,
        namespace: str | None = None,
        bypass_cache: bool = False,
    ) -> list[dict[str, Any]]:
        """
        List deployments in a cluster, optionally filtered by namespace.

        Uses Redis L1 cache (TTL 2 min).
        """
        cache_key = CacheKeys.deployments(cluster_id, namespace)

        if not bypass_cache:
            cached, tier = await data_cache.get_or_fetch(
                key=cache_key,
                ttl=TTL.DEPLOYMENTS,
                fetch_fn=lambda: self._fetch_deployments_live(cluster_id, namespace),
            )
            return cached

        return await self._fetch_deployments_live(cluster_id, namespace)

    async def _fetch_deployments_live(
        self,
        cluster_id: str,
        namespace: str | None = None,
    ) -> list[dict[str, Any]]:
        """Live K8s API call to list deployments (L3)."""
        apps_v1, _, _ = await self._get_k8s_clients(cluster_id)
        deployments = []

        try:
            if namespace:
                dep_list = await asyncio.to_thread(apps_v1.list_namespaced_deployment, namespace)
            else:
                dep_list = await asyncio.to_thread(apps_v1.list_deployment_for_all_namespaces)

            for dep in dep_list.items:
                # Extract resource requests/limits from the first container
                containers = dep.spec.template.spec.containers or []
                first_container = containers[0] if containers else None
                resources = first_container.resources if first_container else None
                requests = dict(resources.requests) if resources and resources.requests else {}
                limits = dict(resources.limits) if resources and resources.limits else {}

                deployments.append(
                    {
                        "name": dep.metadata.name,
                        "namespace": dep.metadata.namespace,
                        # Flat fields to match frontend Deployment interface
                        "replicas": dep.spec.replicas or 0,
                        "ready_replicas": dep.status.ready_replicas or 0,
                        "available_replicas": dep.status.available_replicas or 0,
                        "strategy": (dep.spec.strategy.type if dep.spec.strategy else None),
                        "images": [c.image for c in (dep.spec.template.spec.containers or [])],
                        "created_at": (
                            dep.metadata.creation_timestamp.isoformat() if dep.metadata.creation_timestamp else None
                        ),
                        "labels": (dict(dep.metadata.labels) if dep.metadata.labels else {}),
                        "conditions": [
                            {
                                "type": c.type,
                                "status": c.status,
                                "reason": c.reason,
                                "message": c.message,
                            }
                            for c in (dep.status.conditions or [])
                        ],
                        # Resource requests/limits for the first container
                        "cpu_request": requests.get("cpu", ""),
                        "cpu_limit": limits.get("cpu", ""),
                        "memory_request": requests.get("memory", ""),
                        "memory_limit": limits.get("memory", ""),
                    }
                )

        except ApiException as e:
            logger.error("list_deployments_failed", cluster_id=cluster_id, error=str(e))
            raise

        return deployments

    async def scale_deployment(
        self,
        cluster_id: str,
        namespace: str,
        deployment_name: str,
        replicas: int,
        user_id: str,
        user_email: str,
    ) -> dict[str, Any]:
        """
        Scale a deployment to the specified replica count.

        Args:
            cluster_id: AKS cluster resource ID
            namespace: Kubernetes namespace
            deployment_name: Name of the deployment
            replicas: Target replica count
            user_id: User initiating the action
            user_email: User email for audit

        Returns:
            Operation result with previous and new replica counts
        """
        apps_v1, _, _ = await self._get_k8s_clients(cluster_id)

        try:
            # Get current deployment
            deployment = apps_v1.read_namespaced_deployment(deployment_name, namespace)
            previous_replicas = deployment.spec.replicas

            # Record history entry
            history = DeploymentScaleHistory(
                cluster_id=cluster_id,
                cluster_name=self._extract_cluster_name(cluster_id),
                namespace=namespace,
                deployment_name=deployment_name,
                action="scale_up" if replicas > previous_replicas else "scale_down",
                previous_replicas=previous_replicas,
                new_replicas=replicas,
                initiated_by=user_id,
                initiated_by_email=user_email,
                status="pending",
            )
            await self._db_add_and_commit(history)

            # Perform scaling
            body = {"spec": {"replicas": replicas}}
            apps_v1.patch_namespaced_deployment_scale(
                deployment_name,
                namespace,
                body,
            )

            # Update history
            history.status = "completed"
            await self._db_commit()

            logger.info(
                "deployment_scaled",
                deployment=deployment_name,
                namespace=namespace,
                previous=previous_replicas,
                new=replicas,
                user=user_email,
            )

            # Invalidate deployment caches so next read gets fresh data
            await data_cache.invalidate_for_deployments(cluster_id)

            return {
                "success": True,
                "deployment": deployment_name,
                "namespace": namespace,
                "previous_replicas": previous_replicas,
                "new_replicas": replicas,
                "operation_id": history.id,
            }

        except ApiException as e:
            if history:
                history.status = "failed"
                history.error_message = str(e)
                await self._db_commit()

            logger.error(
                "deployment_scale_failed",
                deployment=deployment_name,
                error=str(e),
            )
            raise

    async def restart_deployment(
        self,
        cluster_id: str,
        namespace: str,
        deployment_name: str,
        user_id: str,
        user_email: str,
    ) -> dict[str, Any]:
        """
        Perform a rolling restart of a deployment.
        """
        apps_v1, _, _ = await self._get_k8s_clients(cluster_id)

        try:
            # Get current deployment
            deployment = apps_v1.read_namespaced_deployment(deployment_name, namespace)
            current_replicas = deployment.spec.replicas

            # Record history
            history = DeploymentScaleHistory(
                cluster_id=cluster_id,
                cluster_name=self._extract_cluster_name(cluster_id),
                namespace=namespace,
                deployment_name=deployment_name,
                action="restart",
                previous_replicas=current_replicas,
                new_replicas=current_replicas,
                initiated_by=user_id,
                initiated_by_email=user_email,
                status="pending",
            )
            await self._db_add_and_commit(history)

            # Trigger rolling restart by patching template annotation
            now = datetime.utcnow().isoformat()
            body = {"spec": {"template": {"metadata": {"annotations": {"kubectl.kubernetes.io/restartedAt": now}}}}}

            apps_v1.patch_namespaced_deployment(deployment_name, namespace, body)

            history.status = "completed"
            await self._db_commit()

            logger.info(
                "deployment_restarted",
                deployment=deployment_name,
                namespace=namespace,
                user=user_email,
            )

            # Invalidate deployment caches
            await data_cache.invalidate_for_deployments(cluster_id)

            return {
                "success": True,
                "deployment": deployment_name,
                "namespace": namespace,
                "action": "rolling_restart",
                "restarted_at": now,
                "operation_id": history.id,
            }

        except ApiException as e:
            if history:
                history.status = "failed"
                history.error_message = str(e)
                await self._db_commit()
            raise

    async def create_deployment(
        self,
        cluster_id: str,
        namespace: str,
        name: str,
        image: str,
        replicas: int = 1,
        labels: dict[str, str] | None = None,
        cpu_request: str = "100m",
        cpu_limit: str = "500m",
        memory_request: str = "128Mi",
        memory_limit: str = "512Mi",
        port: int | None = None,
        env_vars: dict[str, str] | None = None,
        user_id: str = "",
        user_email: str = "",
    ) -> dict[str, Any]:
        """Create a new Kubernetes deployment."""
        apps_v1, _, _ = await self._get_k8s_clients(cluster_id)
        pod_labels = {"app": name}
        if labels:
            pod_labels.update(labels)

        container_ports = [k8s_client.V1ContainerPort(container_port=port)] if port else None
        container_env = [k8s_client.V1EnvVar(name=k, value=v) for k, v in (env_vars or {}).items()] or None

        deployment = k8s_client.V1Deployment(
            api_version="apps/v1",
            kind="Deployment",
            metadata=k8s_client.V1ObjectMeta(name=name, labels=pod_labels),
            spec=k8s_client.V1DeploymentSpec(
                replicas=replicas,
                selector=k8s_client.V1LabelSelector(match_labels={"app": name}),
                template=k8s_client.V1PodTemplateSpec(
                    metadata=k8s_client.V1ObjectMeta(labels=pod_labels),
                    spec=k8s_client.V1PodSpec(
                        containers=[
                            k8s_client.V1Container(
                                name=name,
                                image=image,
                                ports=container_ports,
                                env=container_env,
                                resources=k8s_client.V1ResourceRequirements(
                                    requests={
                                        "cpu": cpu_request,
                                        "memory": memory_request,
                                    },
                                    limits={"cpu": cpu_limit, "memory": memory_limit},
                                ),
                            )
                        ]
                    ),
                ),
            ),
        )

        try:
            apps_v1.create_namespaced_deployment(namespace, deployment)
            history = DeploymentScaleHistory(
                cluster_id=cluster_id,
                cluster_name=self._extract_cluster_name(cluster_id),
                namespace=namespace,
                deployment_name=name,
                action="create",
                previous_replicas=0,
                new_replicas=replicas,
                initiated_by=user_id,
                initiated_by_email=user_email,
                status="completed",
            )
            await self._db_add_and_commit(history)
            await data_cache.invalidate_for_deployments(cluster_id)
            logger.info("deployment_created", name=name, namespace=namespace, user=user_email)
            return {
                "success": True,
                "deployment": name,
                "namespace": namespace,
                "replicas": replicas,
            }
        except ApiException as e:
            logger.error("deployment_create_failed", name=name, error=str(e))
            raise

    async def update_deployment(
        self,
        cluster_id: str,
        namespace: str,
        name: str,
        image: str | None = None,
        replicas: int | None = None,
        cpu_request: str | None = None,
        cpu_limit: str | None = None,
        memory_request: str | None = None,
        memory_limit: str | None = None,
        env_vars: dict[str, str] | None = None,
        user_id: str = "",
        user_email: str = "",
    ) -> dict[str, Any]:
        """Update an existing Kubernetes deployment (image, replicas, resources)."""
        apps_v1, _, _ = await self._get_k8s_clients(cluster_id)

        try:
            current = apps_v1.read_namespaced_deployment(name, namespace)
            previous_replicas = current.spec.replicas
            patch: dict[str, Any] = {"spec": {}}

            if replicas is not None:
                patch["spec"]["replicas"] = replicas

            container_patch: dict[str, Any] = {}
            if image:
                container_patch["image"] = image
            if any([cpu_request, cpu_limit, memory_request, memory_limit]):
                cur_resources = current.spec.template.spec.containers[0].resources
                reqs = dict(cur_resources.requests) if cur_resources and cur_resources.requests else {}
                lims = dict(cur_resources.limits) if cur_resources and cur_resources.limits else {}
                if cpu_request:
                    reqs["cpu"] = cpu_request
                if memory_request:
                    reqs["memory"] = memory_request
                if cpu_limit:
                    lims["cpu"] = cpu_limit
                if memory_limit:
                    lims["memory"] = memory_limit
                container_patch["resources"] = {"requests": reqs, "limits": lims}
            if env_vars is not None:
                container_patch["env"] = [{"name": k, "value": v} for k, v in env_vars.items()]

            if container_patch:
                patch["spec"]["template"] = {
                    "spec": {
                        "containers": [
                            {
                                **container_patch,
                                "name": current.spec.template.spec.containers[0].name,
                            }
                        ]
                    }
                }

            apps_v1.patch_namespaced_deployment(name, namespace, patch)

            history = DeploymentScaleHistory(
                cluster_id=cluster_id,
                cluster_name=self._extract_cluster_name(cluster_id),
                namespace=namespace,
                deployment_name=name,
                action="update",
                previous_replicas=previous_replicas,
                new_replicas=replicas if replicas is not None else previous_replicas,
                initiated_by=user_id,
                initiated_by_email=user_email,
                status="completed",
            )
            await self._db_add_and_commit(history)
            await data_cache.invalidate_for_deployments(cluster_id)
            logger.info("deployment_updated", name=name, namespace=namespace, user=user_email)
            return {"success": True, "deployment": name, "namespace": namespace}
        except ApiException as e:
            logger.error("deployment_update_failed", name=name, error=str(e))
            raise

    async def delete_deployment(
        self,
        cluster_id: str,
        namespace: str,
        name: str,
        user_id: str = "",
        user_email: str = "",
    ) -> dict[str, Any]:
        """Delete a Kubernetes deployment."""
        apps_v1, _, _ = await self._get_k8s_clients(cluster_id)

        try:
            current = apps_v1.read_namespaced_deployment(name, namespace)
            previous_replicas = current.spec.replicas

            apps_v1.delete_namespaced_deployment(name, namespace)

            history = DeploymentScaleHistory(
                cluster_id=cluster_id,
                cluster_name=self._extract_cluster_name(cluster_id),
                namespace=namespace,
                deployment_name=name,
                action="delete",
                previous_replicas=previous_replicas,
                new_replicas=0,
                initiated_by=user_id,
                initiated_by_email=user_email,
                status="completed",
            )
            await self._db_add_and_commit(history)
            await data_cache.invalidate_for_deployments(cluster_id)
            logger.info("deployment_deleted", name=name, namespace=namespace, user=user_email)
            return {"success": True, "deployment": name, "namespace": namespace}
        except ApiException as e:
            logger.error("deployment_delete_failed", name=name, error=str(e))
            raise

    # =========================================================================
    # C. POD RESOURCE OBSERVABILITY
    # =========================================================================

    async def get_pod_metrics(
        self,
        cluster_id: str,
        namespace: str | None = None,
        deployment_name: str | None = None,
        bypass_cache: bool = False,
    ) -> list[dict[str, Any]]:
        """
        Get current CPU and memory metrics for pods with full resource detail.

        Uses Redis L1 cache (TTL 1 min — most volatile data).
        """
        # Only cache when no deployment filter (filtered results are rare)
        if deployment_name or bypass_cache:
            return await self._fetch_pod_metrics_live(cluster_id, namespace, deployment_name)

        cache_key = CacheKeys.pod_metrics(cluster_id, namespace)
        cached, tier = await data_cache.get_or_fetch(
            key=cache_key,
            ttl=TTL.POD_METRICS,
            fetch_fn=lambda: self._fetch_pod_metrics_live(cluster_id, namespace, deployment_name),
        )
        return cached

    async def _fetch_pod_metrics_live(
        self,
        cluster_id: str,
        namespace: str | None = None,
        deployment_name: str | None = None,
    ) -> list[dict[str, Any]]:
        """Live K8s API call to fetch pod metrics (L3)."""
        _, core_v1, _ = await self._get_k8s_clients(cluster_id)
        pods = []

        try:
            # Get pods
            pod_list = (
                await asyncio.to_thread(core_v1.list_namespaced_pod, namespace)
                if namespace
                else await asyncio.to_thread(core_v1.list_pod_for_all_namespaces)
            )

            # Filter by deployment if specified
            for pod in pod_list.items:
                if deployment_name:
                    owner_refs = pod.metadata.owner_references or []
                    is_owned = any(ref.kind == "ReplicaSet" and deployment_name in ref.name for ref in owner_refs)
                    if not is_owned:
                        continue

                # Determine pod QoS and conditions
                conditions = {}
                for cond in pod.status.conditions or []:
                    conditions[cond.type] = cond.status

                pod_data: dict[str, Any] = {
                    "pod_name": pod.metadata.name,
                    "namespace": pod.metadata.namespace,
                    "phase": pod.status.phase,
                    "node": pod.spec.node_name,
                    "started_at": (pod.status.start_time.isoformat() if pod.status.start_time else None),
                    "qos_class": pod.status.qos_class,
                    "pod_ip": pod.status.pod_ip,
                    "host_ip": pod.status.host_ip,
                    "service_account": pod.spec.service_account_name,
                    "restart_policy": pod.spec.restart_policy,
                    "labels": dict(pod.metadata.labels) if pod.metadata.labels else {},
                    "conditions": conditions,
                    "containers": [],
                    "total_cpu_request": 0.0,
                    "total_cpu_limit": 0.0,
                    "total_memory_request_mb": 0.0,
                    "total_memory_limit_mb": 0.0,
                    "total_cpu_millicores": 0.0,
                    "total_memory_mb": 0.0,
                    "total_restarts": 0,
                }

                for container in pod.spec.containers or []:
                    container_status = next(
                        (cs for cs in (pod.status.container_statuses or []) if cs.name == container.name),
                        None,
                    )
                    container_requests = container.resources.requests if container.resources else None
                    container_limits = container.resources.limits if container.resources else None

                    # Parse CPU/memory requests
                    cpu_req = container_requests.get("cpu", "0") if container_requests else "0"
                    mem_req = container_requests.get("memory", "0") if container_requests else "0"
                    # Parse CPU/memory limits
                    cpu_lim = container_limits.get("cpu", "0") if container_limits else "0"
                    mem_lim = container_limits.get("memory", "0") if container_limits else "0"

                    cpu_req_m = self._parse_cpu_to_millicores(cpu_req)
                    mem_req_mb = self._parse_memory_to_mb(mem_req)
                    cpu_lim_m = self._parse_cpu_to_millicores(cpu_lim)
                    mem_lim_mb = self._parse_memory_to_mb(mem_lim)

                    restarts = container_status.restart_count if container_status else 0

                    # Determine container state
                    state_str = "unknown"
                    if container_status and container_status.state:
                        if container_status.state.running:
                            state_str = "running"
                        elif container_status.state.waiting:
                            state_str = f"waiting: {container_status.state.waiting.reason or ''}"
                        elif container_status.state.terminated:
                            state_str = f"terminated: {container_status.state.terminated.reason or ''}"

                    pod_data["containers"].append(
                        {
                            "name": container.name,
                            "image": container.image,
                            "ready": (container_status.ready if container_status else False),
                            "restart_count": restarts,
                            "state": state_str,
                            "cpu_request": cpu_req,
                            "cpu_limit": cpu_lim,
                            "memory_request": mem_req,
                            "memory_limit": mem_lim,
                            "cpu_request_m": cpu_req_m,
                            "cpu_limit_m": cpu_lim_m,
                            "memory_request_mb": mem_req_mb,
                            "memory_limit_mb": mem_lim_mb,
                            "cpu_millicores": cpu_req_m,
                            "memory_mb": mem_req_mb,
                        }
                    )
                    pod_data["total_cpu_request"] += cpu_req_m
                    pod_data["total_cpu_limit"] += cpu_lim_m
                    pod_data["total_memory_request_mb"] += mem_req_mb
                    pod_data["total_memory_limit_mb"] += mem_lim_mb
                    pod_data["total_cpu_millicores"] += cpu_req_m
                    pod_data["total_memory_mb"] += mem_req_mb
                    pod_data["total_restarts"] += restarts

                pods.append(pod_data)

        except ApiException as e:
            logger.error("get_pod_metrics_failed", cluster_id=cluster_id, error=str(e))
            raise

        return pods

    # ── Pod Logs & Exec ────────────────────────────────────────────────

    async def get_pod_logs(
        self,
        cluster_id: str,
        namespace: str,
        pod_name: str,
        container: str | None = None,
        tail_lines: int = 500,
        since_seconds: int | None = None,
    ) -> dict[str, Any]:
        """Fetch logs from a pod container."""
        _, core_v1, _ = await self._get_k8s_clients(cluster_id)

        try:
            kwargs: dict[str, Any] = {
                "name": pod_name,
                "namespace": namespace,
                "tail_lines": tail_lines,
                "timestamps": True,
            }
            if container:
                kwargs["container"] = container
            if since_seconds:
                kwargs["since_seconds"] = since_seconds

            logs = await asyncio.to_thread(core_v1.read_namespaced_pod_log, **kwargs)

            # Parse log lines
            log_lines = (logs or "").split("\n")
            total_lines = len([line for line in log_lines if line.strip()])

            return {
                "pod_name": pod_name,
                "namespace": namespace,
                "container": container,
                "logs": logs or "",
                "line_count": total_lines,
                "tail_lines": tail_lines,
            }
        except ApiException as e:
            logger.error("get_pod_logs_failed", pod=pod_name, namespace=namespace, error=str(e))
            raise

    async def search_pod_logs(
        self,
        cluster_id: str,
        namespace: str,
        pod_name: str,
        pattern: str = "error|exception|fail|panic|crash|oom|kill",
        container: str | None = None,
        tail_lines: int = 2000,
    ) -> dict[str, Any]:
        """Search pod logs for error patterns and return matching lines with context."""
        import re

        log_data = await self.get_pod_logs(
            cluster_id,
            namespace,
            pod_name,
            container=container,
            tail_lines=tail_lines,
        )
        raw_logs = log_data["logs"]
        lines = raw_logs.split("\n")

        try:
            regex = re.compile(pattern, re.IGNORECASE)
        except re.error:
            regex = re.compile(re.escape(pattern), re.IGNORECASE)

        matches = []
        severity_counts = {"error": 0, "warning": 0, "info": 0}

        for i, line in enumerate(lines):
            if not line.strip():
                continue
            if regex.search(line):
                # Classify severity
                line_lower = line.lower()
                if any(
                    w in line_lower
                    for w in (
                        "error",
                        "exception",
                        "panic",
                        "fatal",
                        "crash",
                        "oom",
                        "kill",
                    )
                ):
                    severity = "error"
                    severity_counts["error"] += 1
                elif any(w in line_lower for w in ("warn", "warning")):
                    severity = "warning"
                    severity_counts["warning"] += 1
                else:
                    severity = "info"
                    severity_counts["info"] += 1

                matches.append(
                    {
                        "line_number": i + 1,
                        "text": line.strip(),
                        "severity": severity,
                    }
                )

        return {
            "pod_name": pod_name,
            "namespace": namespace,
            "pattern": pattern,
            "total_log_lines": len([line for line in lines if line.strip()]),
            "match_count": len(matches),
            "severity_counts": severity_counts,
            "matches": matches[:500],  # Cap at 500 matches
        }

    async def exec_pod_command(
        self,
        cluster_id: str,
        namespace: str,
        pod_name: str,
        command: list[str],
        container: str | None = None,
        timeout: int = 30,
    ) -> dict[str, Any]:
        """Execute a command in a pod and return the output."""
        from kubernetes.stream import stream as k8s_stream

        _, core_v1, _ = await self._get_k8s_clients(cluster_id)

        try:
            kwargs: dict[str, Any] = {
                "name": pod_name,
                "namespace": namespace,
                "command": command,
                "stderr": True,
                "stdin": False,
                "stdout": True,
                "tty": False,
                "_request_timeout": timeout,
            }
            if container:
                kwargs["container"] = container

            resp = await asyncio.to_thread(k8s_stream, core_v1.connect_get_namespaced_pod_exec, **kwargs)

            return {
                "pod_name": pod_name,
                "namespace": namespace,
                "command": " ".join(command),
                "output": resp if isinstance(resp, str) else str(resp),
                "success": True,
            }
        except ApiException as e:
            logger.error("exec_pod_command_failed", pod=pod_name, error=str(e))
            return {
                "pod_name": pod_name,
                "namespace": namespace,
                "command": " ".join(command),
                "output": f"Error: {e.reason or str(e)}",
                "success": False,
            }
        except Exception as e:
            logger.error("exec_pod_command_error", pod=pod_name, error=str(e))
            return {
                "pod_name": pod_name,
                "namespace": namespace,
                "command": " ".join(command),
                "output": f"Error: {str(e)}",
                "success": False,
            }

    async def get_pod_containers(
        self,
        cluster_id: str,
        namespace: str,
        pod_name: str,
    ) -> list[dict[str, Any]]:
        """Get list of containers in a pod with their status."""
        _, core_v1, _ = await self._get_k8s_clients(cluster_id)

        try:
            pod = await asyncio.to_thread(core_v1.read_namespaced_pod, pod_name, namespace)

            containers = []
            for container in pod.spec.containers or []:
                status = next(
                    (cs for cs in (pod.status.container_statuses or []) if cs.name == container.name),
                    None,
                )
                state_str = "unknown"
                if status and status.state:
                    if status.state.running:
                        state_str = "running"
                    elif status.state.waiting:
                        state_str = f"waiting: {status.state.waiting.reason or ''}"
                    elif status.state.terminated:
                        state_str = f"terminated: {status.state.terminated.reason or ''}"

                containers.append(
                    {
                        "name": container.name,
                        "image": container.image,
                        "state": state_str,
                        "ready": status.ready if status else False,
                        "restart_count": status.restart_count if status else 0,
                    }
                )

            # Include init containers
            for container in pod.spec.init_containers or []:
                status = next(
                    (cs for cs in (pod.status.init_container_statuses or []) if cs.name == container.name),
                    None,
                )
                state_str = "init"
                if status and status.state:
                    if status.state.running:
                        state_str = "init-running"
                    elif status.state.terminated:
                        state_str = "init-done"

                containers.append(
                    {
                        "name": container.name,
                        "image": container.image,
                        "state": state_str,
                        "ready": status.ready if status else False,
                        "restart_count": status.restart_count if status else 0,
                        "is_init": True,
                    }
                )

            return containers
        except ApiException as e:
            logger.error("get_pod_containers_failed", pod=pod_name, error=str(e))
            raise

    async def get_pod_utilization_history(
        self,
        cluster_id: str,
        namespace: str,
        pod_name: str | None = None,
        hours: int = 24,
    ) -> list[dict[str, Any]]:
        """
        Get historical pod utilization data from the database.
        """
        stmt = select(PodUtilizationHistory).where(
            PodUtilizationHistory.cluster_id == cluster_id,
            PodUtilizationHistory.namespace == namespace,
            PodUtilizationHistory.timestamp >= datetime.utcnow() - timedelta(hours=hours),
        )

        if pod_name:
            stmt = stmt.where(PodUtilizationHistory.pod_name == pod_name)

        stmt = stmt.order_by(PodUtilizationHistory.timestamp)
        result = await self.db.execute(stmt)
        results = result.scalars().all()

        return [
            {
                "timestamp": r.timestamp.isoformat(),
                "pod_name": r.pod_name,
                "container_name": r.container_name,
                "cpu": {
                    "request_millicores": r.cpu_request_millicores,
                    "limit_millicores": r.cpu_limit_millicores,
                    "usage_millicores": r.cpu_usage_millicores,
                    "utilization_pct": r.cpu_utilization_pct,
                },
                "memory": {
                    "request_bytes": r.memory_request_bytes,
                    "limit_bytes": r.memory_limit_bytes,
                    "usage_bytes": r.memory_usage_bytes,
                    "utilization_pct": r.memory_utilization_pct,
                },
            }
            for r in results
        ]

    async def identify_underutilized_workloads(
        self,
        cluster_id: str,
        cpu_threshold_pct: float = 20.0,
        memory_threshold_pct: float = 30.0,
    ) -> list[dict[str, Any]]:
        """
        Identify pods with low resource utilization for optimization.
        """
        # Get average utilization over the past 24 hours
        subquery = (
            select(
                PodUtilizationHistory.namespace,
                PodUtilizationHistory.pod_name,
                func.avg(PodUtilizationHistory.cpu_utilization_pct).label("avg_cpu"),
                func.avg(PodUtilizationHistory.memory_utilization_pct).label("avg_memory"),
            )
            .where(
                PodUtilizationHistory.cluster_id == cluster_id,
                PodUtilizationHistory.timestamp >= datetime.utcnow() - timedelta(hours=24),
            )
            .group_by(
                PodUtilizationHistory.namespace,
                PodUtilizationHistory.pod_name,
            )
            .subquery()
        )

        stmt = select(subquery).where(
            (subquery.c.avg_cpu < cpu_threshold_pct) | (subquery.c.avg_memory < memory_threshold_pct)
        )
        result = await self.db.execute(stmt)
        results = result.all()

        return [
            {
                "namespace": r.namespace,
                "pod_name": r.pod_name,
                "avg_cpu_utilization_pct": round(r.avg_cpu, 2) if r.avg_cpu else None,
                "avg_memory_utilization_pct": (round(r.avg_memory, 2) if r.avg_memory else None),
                "recommendation": "Consider reducing resource requests",
            }
            for r in results
        ]

    # =========================================================================
    # D. CRONJOB MANAGEMENT
    # =========================================================================

    async def list_cronjobs(
        self,
        cluster_id: str,
        namespace: str | None = None,
        bypass_cache: bool = False,
    ) -> list[dict[str, Any]]:
        """
        List all cronjobs in a cluster.

        Uses Redis L1 cache (TTL 2 min).
        """
        cache_key = CacheKeys.cronjobs(cluster_id, namespace)

        if not bypass_cache:
            cached, tier = await data_cache.get_or_fetch(
                key=cache_key,
                ttl=TTL.CRONJOBS,
                fetch_fn=lambda: self._fetch_cronjobs_live(cluster_id, namespace),
            )
            return cached

        return await self._fetch_cronjobs_live(cluster_id, namespace)

    async def _fetch_cronjobs_live(
        self,
        cluster_id: str,
        namespace: str | None = None,
    ) -> list[dict[str, Any]]:
        """Live K8s API call to list cronjobs (L3)."""
        _, _, batch_v1 = await self._get_k8s_clients(cluster_id)
        cronjobs = []

        try:
            if namespace:
                cj_list = await asyncio.to_thread(batch_v1.list_namespaced_cron_job, namespace)
            else:
                cj_list = await asyncio.to_thread(batch_v1.list_cron_job_for_all_namespaces)

            for cj in cj_list.items:
                cronjobs.append(
                    {
                        "name": cj.metadata.name,
                        "namespace": cj.metadata.namespace,
                        "schedule": cj.spec.schedule,
                        # Frontend expects "suspended" (not "suspend")
                        "suspended": cj.spec.suspend or False,
                        "concurrency_policy": cj.spec.concurrency_policy,
                        "last_schedule_time": (
                            cj.status.last_schedule_time.isoformat() if cj.status.last_schedule_time else None
                        ),
                        "last_successful_time": (
                            cj.status.last_successful_time.isoformat() if cj.status.last_successful_time else None
                        ),
                        # Frontend expects "active_count" (not "active_jobs")
                        "active_count": (len(cj.status.active) if cj.status.active else 0),
                        "image": (
                            cj.spec.job_template.spec.template.spec.containers[0].image
                            if cj.spec.job_template.spec.template.spec.containers
                            else None
                        ),
                        "created_at": (
                            cj.metadata.creation_timestamp.isoformat() if cj.metadata.creation_timestamp else None
                        ),
                    }
                )

        except ApiException as e:
            logger.error("list_cronjobs_failed", cluster_id=cluster_id, error=str(e))
            raise

        return cronjobs

    async def suspend_cronjob(
        self,
        cluster_id: str,
        namespace: str,
        cronjob_name: str,
        suspend: bool,
        user_id: str,
        user_email: str,
    ) -> dict[str, Any]:
        """
        Suspend or resume a cronjob.
        """
        _, _, batch_v1 = await self._get_k8s_clients(cluster_id)

        try:
            # Get current state
            cj = batch_v1.read_namespaced_cron_job(cronjob_name, namespace)
            previous_state = {
                "suspend": cj.spec.suspend,
                "schedule": cj.spec.schedule,
            }

            # Record audit history
            history = CronJobAuditHistory(
                cluster_id=cluster_id,
                cluster_name=self._extract_cluster_name(cluster_id),
                namespace=namespace,
                cronjob_name=cronjob_name,
                action="suspend" if suspend else "resume",
                previous_state=previous_state,
                new_state={"suspend": suspend, "schedule": cj.spec.schedule},
                initiated_by=user_id,
                initiated_by_email=user_email,
                status="pending",
            )
            await self._db_add_and_commit(history)

            # Update cronjob
            body = {"spec": {"suspend": suspend}}
            batch_v1.patch_namespaced_cron_job(cronjob_name, namespace, body)

            history.status = "completed"
            await self._db_commit()

            logger.info(
                "cronjob_suspend_changed",
                cronjob=cronjob_name,
                suspend=suspend,
                user=user_email,
            )

            # Invalidate cronjob caches
            await data_cache.invalidate_for_cronjobs(cluster_id)
            await self._refresh_cronjob_db_cache(cluster_id, namespace)

            return {
                "success": True,
                "cronjob": cronjob_name,
                "namespace": namespace,
                "action": "suspended" if suspend else "resumed",
                "operation_id": history.id,
            }

        except ApiException as e:
            if history:
                history.status = "failed"
                history.error_message = str(e)
                await self._db_commit()
            raise

    async def create_cronjob(
        self,
        cluster_id: str,
        namespace: str,
        name: str,
        schedule: str,
        image: str,
        command: list[str] | None = None,
        args: list[str] | None = None,
        restart_policy: str = "OnFailure",
        labels: dict[str, str] | None = None,
        cpu_request: str = "100m",
        cpu_limit: str = "500m",
        memory_request: str = "128Mi",
        memory_limit: str = "512Mi",
        concurrency_policy: str = "Forbid",
        successful_jobs_history_limit: int = 3,
        failed_jobs_history_limit: int = 1,
        backoff_limit: int = 6,
        active_deadline_seconds: int | None = None,
        ttl_seconds_after_finished: int | None = None,
        service_account_name: str | None = None,
        user_id: str = "",
        user_email: str = "",
    ) -> dict[str, Any]:
        """
        Create a new cronjob with full K8s property support.
        """
        _, _, batch_v1 = await self._get_k8s_clients(cluster_id)

        pod_labels = {"app": name}
        if labels:
            pod_labels.update(labels)

        cronjob_manifest = k8s_client.V1CronJob(
            api_version="batch/v1",
            kind="CronJob",
            metadata=k8s_client.V1ObjectMeta(name=name, labels=pod_labels),
            spec=k8s_client.V1CronJobSpec(
                schedule=schedule,
                concurrency_policy=concurrency_policy,
                successful_jobs_history_limit=successful_jobs_history_limit,
                failed_jobs_history_limit=failed_jobs_history_limit,
                job_template=k8s_client.V1JobTemplateSpec(
                    spec=k8s_client.V1JobSpec(
                        backoff_limit=backoff_limit,
                        active_deadline_seconds=active_deadline_seconds,
                        ttl_seconds_after_finished=ttl_seconds_after_finished,
                        template=k8s_client.V1PodTemplateSpec(
                            metadata=k8s_client.V1ObjectMeta(labels=pod_labels),
                            spec=k8s_client.V1PodSpec(
                                restart_policy=restart_policy,
                                service_account_name=service_account_name,
                                containers=[
                                    k8s_client.V1Container(
                                        name=name,
                                        image=image,
                                        command=command,
                                        args=args,
                                        resources=k8s_client.V1ResourceRequirements(
                                            requests={
                                                "cpu": cpu_request,
                                                "memory": memory_request,
                                            },
                                            limits={
                                                "cpu": cpu_limit,
                                                "memory": memory_limit,
                                            },
                                        ),
                                    )
                                ],
                            ),
                        ),
                    )
                ),
            ),
        )

        try:
            # Record audit history
            history = CronJobAuditHistory(
                cluster_id=cluster_id,
                cluster_name=self._extract_cluster_name(cluster_id),
                namespace=namespace,
                cronjob_name=name,
                action="create",
                previous_state=None,
                new_state={
                    "name": name,
                    "schedule": schedule,
                    "image": image,
                    "resources": {
                        "cpu": {"request": cpu_request, "limit": cpu_limit},
                        "memory": {"request": memory_request, "limit": memory_limit},
                    },
                },
                initiated_by=user_id,
                initiated_by_email=user_email,
                status="pending",
            )
            await self._db_add_and_commit(history)

            batch_v1.create_namespaced_cron_job(namespace, cronjob_manifest)

            history.status = "completed"
            await self._db_commit()

            logger.info(
                "cronjob_created",
                name=name,
                namespace=namespace,
                schedule=schedule,
                user=user_email,
            )

            # Invalidate cronjob caches
            await data_cache.invalidate_for_cronjobs(cluster_id)
            await self._refresh_cronjob_db_cache(cluster_id, namespace)

            return {
                "success": True,
                "cronjob": name,
                "namespace": namespace,
                "schedule": schedule,
                "operation_id": history.id,
            }

        except ApiException as e:
            if history:
                history.status = "failed"
                history.error_message = str(e)
                await self._db_commit()
            raise

    async def update_cronjob(
        self,
        cluster_id: str,
        namespace: str,
        name: str,
        schedule: str | None = None,
        image: str | None = None,
        command: list[str] | None = None,
        args: list[str] | None = None,
        suspended: bool | None = None,
        user_id: str = "",
        user_email: str = "",
    ) -> dict[str, Any]:
        """Update an existing cronjob's schedule, image, command, or suspend state."""
        _, _, batch_v1 = await self._get_k8s_clients(cluster_id)

        try:
            cj = batch_v1.read_namespaced_cron_job(name, namespace)
            previous_state = {
                "schedule": cj.spec.schedule,
                "suspend": cj.spec.suspend,
                "image": (
                    cj.spec.job_template.spec.template.spec.containers[0].image
                    if cj.spec.job_template.spec.template.spec.containers
                    else None
                ),
            }

            if schedule is not None:
                cj.spec.schedule = schedule
            if suspended is not None:
                cj.spec.suspend = suspended
            if image is not None and cj.spec.job_template.spec.template.spec.containers:
                cj.spec.job_template.spec.template.spec.containers[0].image = image
            if command is not None and cj.spec.job_template.spec.template.spec.containers:
                cj.spec.job_template.spec.template.spec.containers[0].command = command
            if args is not None and cj.spec.job_template.spec.template.spec.containers:
                cj.spec.job_template.spec.template.spec.containers[0].args = args

            batch_v1.replace_namespaced_cron_job(name, namespace, cj)

            history = CronJobAuditHistory(
                cluster_id=cluster_id,
                cluster_name=self._extract_cluster_name(cluster_id),
                namespace=namespace,
                cronjob_name=name,
                action="update",
                previous_state=previous_state,
                new_state={
                    "schedule": cj.spec.schedule,
                    "suspend": cj.spec.suspend,
                    "image": (
                        cj.spec.job_template.spec.template.spec.containers[0].image
                        if cj.spec.job_template.spec.template.spec.containers
                        else None
                    ),
                },
                initiated_by=user_id,
                initiated_by_email=user_email,
                status="completed",
            )
            await self._db_add_and_commit(history)

            await data_cache.invalidate_for_cronjobs(cluster_id)
            await self._refresh_cronjob_db_cache(cluster_id, namespace)
            logger.info("cronjob_updated", name=name, namespace=namespace, user=user_email)
            return {"success": True, "cronjob": name, "namespace": namespace}
        except ApiException as e:
            logger.error("cronjob_update_failed", name=name, error=str(e))
            raise

    async def delete_cronjob(
        self,
        cluster_id: str,
        namespace: str,
        name: str,
        user_id: str = "",
        user_email: str = "",
    ) -> dict[str, Any]:
        """Delete a cronjob."""
        _, _, batch_v1 = await self._get_k8s_clients(cluster_id)

        try:
            cj = batch_v1.read_namespaced_cron_job(name, namespace)
            previous_state = {
                "schedule": cj.spec.schedule,
                "suspend": cj.spec.suspend,
            }

            batch_v1.delete_namespaced_cron_job(name, namespace)

            history = CronJobAuditHistory(
                cluster_id=cluster_id,
                cluster_name=self._extract_cluster_name(cluster_id),
                namespace=namespace,
                cronjob_name=name,
                action="delete",
                previous_state=previous_state,
                new_state=None,
                initiated_by=user_id,
                initiated_by_email=user_email,
                status="completed",
            )
            await self._db_add_and_commit(history)

            await data_cache.invalidate_for_cronjobs(cluster_id)
            await self._refresh_cronjob_db_cache(cluster_id, namespace)
            logger.info("cronjob_deleted", name=name, namespace=namespace, user=user_email)
            return {"success": True, "cronjob": name, "namespace": namespace}
        except ApiException as e:
            logger.error("cronjob_delete_failed", name=name, error=str(e))
            raise

    async def get_cronjob_detail(
        self,
        cluster_id: str,
        namespace: str,
        name: str,
        bypass_cache: bool = False,
    ) -> dict[str, Any]:
        """Get detailed information about a single cronjob.

        Uses Redis L1 cache (TTL 2 min).
        """
        cache_key = CacheKeys.cronjob_detail(cluster_id, namespace, name)

        try:
            if not bypass_cache:
                cached, tier = await data_cache.get_or_fetch(
                    key=cache_key,
                    ttl=TTL.CRONJOB_DETAIL,
                    fetch_fn=lambda: self._fetch_cronjob_detail_live(cluster_id, namespace, name),
                )
                return cached

            return await self._fetch_cronjob_detail_live(cluster_id, namespace, name)
        except Exception as e:
            fallback = await self._get_cronjob_detail_from_db(cluster_id, namespace, name)
            if fallback is not None:
                logger.warning(
                    "cronjob_detail_live_failed_using_db_fallback",
                    cluster_id=cluster_id,
                    namespace=namespace,
                    name=name,
                    error=str(e),
                )
                return fallback
            raise

    async def _get_cronjob_detail_from_db(
        self,
        cluster_id: str,
        namespace: str,
        name: str,
    ) -> dict[str, Any] | None:
        """Return a detail payload from the DB inventory when live lookup fails."""
        if not self.db:
            return None

        resource_id = f"{cluster_id}/cronjob/{namespace}/{name}"

        try:
            query = select(AzureResourceInventory).where(
                AzureResourceInventory.resource_type == "aks_cronjob",
                AzureResourceInventory.resource_id == resource_id,
            )
            result = await self.db.execute(query)
            record = result.scalars().first()
            if record is None:
                return None

            details = dict(record.resource_details or {})
            resources = details.get("resources") if isinstance(details.get("resources"), dict) else {}

            details.pop("_cluster_id", None)
            details.setdefault("name", name)
            details.setdefault("namespace", namespace)
            details.setdefault("schedule", "")
            details.setdefault("suspended", False)
            details.setdefault("concurrency_policy", None)
            details.setdefault("last_schedule_time", None)
            details.setdefault("last_successful_time", None)
            details.setdefault("active_count", 0)
            details.setdefault("image", None)
            details.setdefault("command", None)
            details.setdefault("args", None)
            details.setdefault("created_at", None)
            details["labels"] = details.get("labels") if isinstance(details.get("labels"), dict) else {}
            details["resources"] = {
                "requests": dict(resources.get("requests") or {}),
                "limits": dict(resources.get("limits") or {}),
            }
            details["configmap_refs"] = list(details.get("configmap_refs") or [])
            details["volume_mounts"] = list(details.get("volume_mounts") or [])
            details["env_configmap_refs"] = list(details.get("env_configmap_refs") or [])
            details["detail_source"] = "db"
            details["_last_sync"] = record.last_sync.isoformat() if record.last_sync else None
            return details
        except Exception as e:
            logger.warning(
                "cronjob_detail_db_fallback_failed",
                cluster_id=cluster_id,
                namespace=namespace,
                name=name,
                error=str(e),
            )
            return None

    async def _fetch_cronjob_detail_live(
        self,
        cluster_id: str,
        namespace: str,
        name: str,
    ) -> dict[str, Any]:
        """Live K8s API call to get cronjob detail (L3)."""
        _, _, batch_v1 = await self._get_k8s_clients(cluster_id)

        try:
            cj = await asyncio.to_thread(batch_v1.read_namespaced_cron_job, name, namespace)
            pod_spec = cj.spec.job_template.spec.template.spec
            container = pod_spec.containers[0] if pod_spec.containers else None
            status = cj.status

            # Extract ConfigMap references from volumes
            configmap_refs: list[dict[str, Any]] = []
            if pod_spec.volumes:
                for vol in pod_spec.volumes:
                    if vol.config_map:
                        configmap_refs.append(
                            {
                                "volume_name": vol.name,
                                "configmap_name": vol.config_map.name,
                                "optional": vol.config_map.optional or False,
                                "items": (
                                    [{"key": item.key, "path": item.path} for item in (vol.config_map.items or [])]
                                    if vol.config_map.items
                                    else []
                                ),
                            }
                        )

            # Extract volume mounts from the container
            volume_mounts: list[dict[str, str]] = []
            if container and container.volume_mounts:
                for vm in container.volume_mounts:
                    volume_mounts.append(
                        {
                            "name": vm.name,
                            "mount_path": vm.mount_path,
                            "sub_path": vm.sub_path or "",
                            "read_only": str(vm.read_only or False),
                        }
                    )

            # Extract env-from ConfigMap references
            env_configmap_refs: list[dict[str, Any]] = []
            if container and container.env_from:
                for ef in container.env_from:
                    if ef.config_map_ref:
                        env_configmap_refs.append(
                            {
                                "name": ef.config_map_ref.name,
                                "optional": ef.config_map_ref.optional or False,
                                "prefix": ef.prefix or "",
                            }
                        )

            return {
                "name": cj.metadata.name,
                "namespace": cj.metadata.namespace,
                "schedule": cj.spec.schedule,
                "suspended": cj.spec.suspend or False,
                "concurrency_policy": cj.spec.concurrency_policy,
                "last_schedule_time": (
                    status.last_schedule_time.isoformat() if status and status.last_schedule_time else None
                ),
                "last_successful_time": (
                    status.last_successful_time.isoformat() if status and status.last_successful_time else None
                ),
                "active_count": len(status.active) if status and status.active else 0,
                "image": container.image if container else None,
                "command": container.command if container else None,
                "args": container.args if container else None,
                "created_at": (cj.metadata.creation_timestamp.isoformat() if cj.metadata.creation_timestamp else None),
                "labels": dict(cj.metadata.labels) if cj.metadata.labels else {},
                "successful_jobs_history_limit": cj.spec.successful_jobs_history_limit,
                "failed_jobs_history_limit": cj.spec.failed_jobs_history_limit,
                "resources": {
                    "requests": (
                        dict(container.resources.requests)
                        if container and container.resources and container.resources.requests
                        else {}
                    ),
                    "limits": (
                        dict(container.resources.limits)
                        if container and container.resources and container.resources.limits
                        else {}
                    ),
                },
                "configmap_refs": configmap_refs,
                "volume_mounts": volume_mounts,
                "env_configmap_refs": env_configmap_refs,
            }
        except ApiException as e:
            logger.error(
                "cronjob_detail_failed",
                name=name,
                namespace=namespace,
                status=e.status,
                error=str(e),
            )
            raise

    async def trigger_cronjob(
        self,
        cluster_id: str,
        namespace: str,
        cronjob_name: str,
        user_id: str = "",
        user_email: str = "",
    ) -> dict[str, Any]:
        """Manually trigger a CronJob by creating a Job from its jobTemplate."""
        _, _, batch_v1 = await self._get_k8s_clients(cluster_id)

        try:
            cj = await asyncio.to_thread(batch_v1.read_namespaced_cron_job, cronjob_name, namespace)

            timestamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")
            job_name = f"{cronjob_name}-manual-{timestamp}"

            # Build a Job from the CronJob's jobTemplate
            from kubernetes.client import V1Job, V1ObjectMeta

            job_template = cj.spec.job_template
            job = V1Job(
                api_version="batch/v1",
                kind="Job",
                metadata=V1ObjectMeta(
                    name=job_name,
                    namespace=namespace,
                    labels={
                        **(dict(cj.metadata.labels) if cj.metadata.labels else {}),
                        "triggered-by": "manual",
                        "cronjob-name": cronjob_name,
                    },
                    annotations={
                        "cronjob.kubernetes.io/instantiate": "manual",
                    },
                ),
                spec=job_template.spec,
            )

            await asyncio.to_thread(batch_v1.create_namespaced_job, namespace, job)

            history = CronJobAuditHistory(
                cluster_id=cluster_id,
                cluster_name=self._extract_cluster_name(cluster_id),
                namespace=namespace,
                cronjob_name=cronjob_name,
                action="trigger",
                previous_state={
                    "schedule": cj.spec.schedule,
                    "suspend": cj.spec.suspend,
                },
                new_state={"job_name": job_name, "triggered_manually": True},
                initiated_by=user_id,
                initiated_by_email=user_email,
                status="completed",
            )
            await self._db_add_and_commit(history)

            await data_cache.invalidate_for_cronjobs(cluster_id)
            await self._refresh_cronjob_db_cache(cluster_id, namespace)
            logger.info("cronjob_triggered", cronjob=cronjob_name, job=job_name, user=user_email)

            return {
                "success": True,
                "cronjob": cronjob_name,
                "job_name": job_name,
                "namespace": namespace,
            }
        except ApiException as e:
            logger.error("cronjob_trigger_failed", cronjob=cronjob_name, error=str(e))
            raise

    # ── ConfigMap Operations ───────────────────────────────────────────

    async def list_configmaps(
        self,
        cluster_id: str,
        namespace: str,
    ) -> list[dict[str, Any]]:
        """List ConfigMaps in a namespace."""
        _, core_v1, _ = await self._get_k8s_clients(cluster_id)

        try:
            cms = await asyncio.to_thread(core_v1.list_namespaced_config_map, namespace)
            return [
                {
                    "name": cm.metadata.name,
                    "namespace": cm.metadata.namespace,
                    "data_keys": list(cm.data.keys()) if cm.data else [],
                    "created_at": (
                        cm.metadata.creation_timestamp.isoformat() if cm.metadata.creation_timestamp else None
                    ),
                    "labels": dict(cm.metadata.labels) if cm.metadata.labels else {},
                }
                for cm in cms.items
            ]
        except ApiException as e:
            logger.error("configmaps_list_failed", namespace=namespace, error=str(e))
            raise

    async def get_configmap_detail(
        self,
        cluster_id: str,
        namespace: str,
        name: str,
    ) -> dict[str, Any]:
        """Get detailed ConfigMap content including data."""
        try:
            _, core_v1, _ = await self._get_k8s_clients(cluster_id)
            cm = await asyncio.to_thread(core_v1.read_namespaced_config_map, name, namespace)
            return {
                "name": cm.metadata.name,
                "namespace": cm.metadata.namespace,
                "data": dict(cm.data) if cm.data else {},
                "binary_data_keys": (list(cm.binary_data.keys()) if cm.binary_data else []),
                "labels": dict(cm.metadata.labels) if cm.metadata.labels else {},
                "annotations": (dict(cm.metadata.annotations) if cm.metadata.annotations else {}),
                "created_at": (cm.metadata.creation_timestamp.isoformat() if cm.metadata.creation_timestamp else None),
                "detail_source": "live",
            }
        except Exception as e:
            logger.warning(
                "configmap_detail_live_failed_returning_placeholder",
                name=name,
                namespace=namespace,
                error=str(e),
            )
            return {
                "name": name,
                "namespace": namespace,
                "data": {},
                "binary_data_keys": [],
                "labels": {},
                "annotations": {},
                "created_at": None,
                "detail_source": "unavailable",
                "data_unavailable_reason": str(e),
            }

    # =========================================================================
    # F. NODE POOL OPERATIONS
    # =========================================================================

    async def get_node_pools(
        self,
        cluster_id: str,
        bypass_cache: bool = False,
    ) -> list[dict[str, Any]]:
        """
        Get node pools for a specific AKS cluster via Azure SDK.
        Enriched with per-node pod counts from the Kubernetes API.

        Uses Redis L1 cache (TTL 5 min).
        """
        cache_key = CacheKeys.node_pools(cluster_id)

        if not bypass_cache:
            cached, tier = await data_cache.get_or_fetch(
                key=cache_key,
                ttl=TTL.NODE_POOLS,
                fetch_fn=lambda: self._fetch_node_pools_live(cluster_id),
            )
            return cached

        return await self._fetch_node_pools_live(cluster_id)

    async def _fetch_node_pools_live(
        self,
        cluster_id: str,
    ) -> list[dict[str, Any]]:
        """Live Azure SDK + K8s API call to fetch node pools (L3)."""
        try:
            parts = cluster_id.split("/")
            subscription_id = parts[2]
            resource_group = parts[4]
            cluster_name = parts[8]

            aks_client = ContainerServiceClient(self.credential, subscription_id)
            pool_list = await asyncio.to_thread(lambda: list(aks_client.agent_pools.list(resource_group, cluster_name)))

            # Fetch node-level data (pod counts, labels) from K8s API
            node_pod_counts: dict[str, int] = {}
            k8s_nodes: dict[str, Any] = {}
            try:
                _, core_v1, _ = await self._get_k8s_clients(cluster_id)
                all_nodes = await asyncio.to_thread(core_v1.list_node)
                for n in all_nodes.items:
                    k8s_nodes[n.metadata.name] = {
                        "labels": dict(n.metadata.labels) if n.metadata.labels else {},
                        "allocatable_cpu": (n.status.allocatable.get("cpu", "0") if n.status.allocatable else "0"),
                        "allocatable_memory": (
                            n.status.allocatable.get("memory", "0") if n.status.allocatable else "0"
                        ),
                        "allocatable_pods": (n.status.allocatable.get("pods", "0") if n.status.allocatable else "0"),
                    }
                all_pods = await asyncio.to_thread(core_v1.list_pod_for_all_namespaces)
                for p in all_pods.items:
                    node = p.spec.node_name
                    if node:
                        node_pod_counts[node] = node_pod_counts.get(node, 0) + 1
            except Exception as e:
                logger.warning("node_pod_count_fetch_failed", error=str(e))

            node_pools = []
            for pool in pool_list:
                # Build per-node details
                pool_prefix = pool.name  # nodes are named like: aks-<pool>-<hash>-vmss<index>
                nodes_detail = []
                total_pods_in_pool = 0
                for node_name, node_info in k8s_nodes.items():
                    # Match nodes to pool by agentpool label
                    np_label = node_info.get("labels", {}).get("agentpool", "")
                    if np_label == pool_prefix:
                        pc = node_pod_counts.get(node_name, 0)
                        total_pods_in_pool += pc
                        nodes_detail.append(
                            {
                                "name": node_name,
                                "pod_count": pc,
                                "allocatable_cpu": node_info.get("allocatable_cpu"),
                                "allocatable_memory": node_info.get("allocatable_memory"),
                                "allocatable_pods": node_info.get("allocatable_pods"),
                                "labels": node_info.get("labels", {}),
                            }
                        )

                node_pools.append(
                    {
                        "name": pool.name,
                        "vm_size": pool.vm_size,
                        "count": pool.count or 0,
                        "min_count": pool.min_count,
                        "max_count": pool.max_count,
                        "enable_auto_scaling": pool.enable_auto_scaling or False,
                        "mode": pool.mode or "User",
                        "os_type": pool.os_type or "Linux",
                        "os_disk_size_gb": pool.os_disk_size_gb,
                        "kubernetes_version": pool.orchestrator_version or pool.current_orchestrator_version,
                        "provisioning_state": pool.provisioning_state,
                        "power_state": (pool.power_state.code if pool.power_state else "Running"),
                        "max_pods": pool.max_pods,
                        "node_labels": (dict(pool.node_labels) if pool.node_labels else {}),
                        "node_taints": (list(pool.node_taints) if pool.node_taints else []),
                        "availability_zones": (list(pool.availability_zones) if pool.availability_zones else []),
                        "node_image_version": pool.node_image_version,
                        "total_pods": total_pods_in_pool,
                        "nodes": nodes_detail,
                    }
                )

            logger.info("node_pools_listed", cluster=cluster_name, count=len(node_pools))
            return node_pools

        except Exception as e:
            logger.error("node_pools_list_failed", cluster_id=cluster_id, error=str(e))
            raise

    async def scale_node_pool(
        self,
        cluster_id: str,
        nodepool_name: str,
        node_count: int,
    ) -> dict[str, Any]:
        """Scale a node pool to the specified node count."""
        try:
            parts = cluster_id.split("/")
            subscription_id = parts[2]
            resource_group = parts[4]
            cluster_name = parts[8]

            aks_client = ContainerServiceClient(self.credential, subscription_id)

            # Get current pool
            current_pool = await asyncio.to_thread(
                aks_client.agent_pools.get, resource_group, cluster_name, nodepool_name
            )
            previous_count = current_pool.count or 0

            # Update count
            current_pool.count = node_count
            await asyncio.to_thread(
                aks_client.agent_pools.begin_create_or_update,
                resource_group,
                cluster_name,
                nodepool_name,
                current_pool,
            )

            logger.info(
                "node_pool_scale_initiated",
                cluster=cluster_name,
                nodepool=nodepool_name,
                previous=previous_count,
                new=node_count,
            )

            # Invalidate nodepool + cluster caches
            await data_cache.invalidate_for_nodepools(cluster_id)

            return {
                "success": True,
                "cluster_id": cluster_id,
                "nodepool_name": nodepool_name,
                "previous_count": previous_count,
                "new_count": node_count,
            }

        except Exception as e:
            logger.error("node_pool_scale_failed", nodepool=nodepool_name, error=str(e))
            return {
                "success": False,
                "cluster_id": cluster_id,
                "nodepool_name": nodepool_name,
                "previous_count": 0,
                "new_count": node_count,
                "error": str(e),
            }

    async def update_node_pool_autoscaling(
        self,
        cluster_id: str,
        nodepool_name: str,
        enable_auto_scaling: bool,
        min_count: int | None = None,
        max_count: int | None = None,
    ) -> dict[str, Any]:
        """Update autoscaling configuration for a node pool."""
        try:
            parts = cluster_id.split("/")
            subscription_id = parts[2]
            resource_group = parts[4]
            cluster_name = parts[8]

            aks_client = ContainerServiceClient(self.credential, subscription_id)

            current_pool = await asyncio.to_thread(
                aks_client.agent_pools.get, resource_group, cluster_name, nodepool_name
            )

            current_pool.enable_auto_scaling = enable_auto_scaling
            if enable_auto_scaling:
                current_pool.min_count = min_count
                current_pool.max_count = max_count
            else:
                current_pool.min_count = None
                current_pool.max_count = None

            await asyncio.to_thread(
                aks_client.agent_pools.begin_create_or_update,
                resource_group,
                cluster_name,
                nodepool_name,
                current_pool,
            )

            logger.info(
                "node_pool_autoscaling_updated",
                cluster=cluster_name,
                nodepool=nodepool_name,
                enabled=enable_auto_scaling,
            )

            # Invalidate nodepool + cluster caches
            await data_cache.invalidate_for_nodepools(cluster_id)

            return {
                "success": True,
                "cluster_id": cluster_id,
                "nodepool_name": nodepool_name,
                "enable_auto_scaling": enable_auto_scaling,
                "min_count": min_count,
                "max_count": max_count,
            }

        except Exception as e:
            logger.error("node_pool_autoscaling_failed", nodepool=nodepool_name, error=str(e))
            return {
                "success": False,
                "cluster_id": cluster_id,
                "nodepool_name": nodepool_name,
                "enable_auto_scaling": enable_auto_scaling,
                "min_count": min_count,
                "max_count": max_count,
                "error": str(e),
            }

    # =========================================================================
    # G. CLUSTER START / STOP
    # =========================================================================

    async def start_cluster(self, cluster_id: str) -> dict[str, Any]:
        """Start a stopped AKS cluster."""
        try:
            parts = cluster_id.split("/")
            subscription_id = parts[2]
            resource_group = parts[4]
            cluster_name = parts[8]

            aks_client = ContainerServiceClient(self.credential, subscription_id)
            await asyncio.to_thread(aks_client.managed_clusters.begin_start, resource_group, cluster_name)

            logger.info("cluster_start_initiated", cluster=cluster_name)
            await data_cache.invalidate_for_clusters()
            return {
                "success": True,
                "cluster_id": cluster_id,
                "action": "start",
                "message": f"Cluster {cluster_name} start initiated",
            }

        except Exception as e:
            logger.error("cluster_start_failed", cluster_id=cluster_id, error=str(e))
            return {
                "success": False,
                "cluster_id": cluster_id,
                "action": "start",
                "message": "Failed to start cluster",
                "error": str(e),
            }

    async def stop_cluster(self, cluster_id: str) -> dict[str, Any]:
        """Stop a running AKS cluster."""
        try:
            parts = cluster_id.split("/")
            subscription_id = parts[2]
            resource_group = parts[4]
            cluster_name = parts[8]

            aks_client = ContainerServiceClient(self.credential, subscription_id)
            await asyncio.to_thread(aks_client.managed_clusters.begin_stop, resource_group, cluster_name)

            logger.info("cluster_stop_initiated", cluster=cluster_name)
            await data_cache.invalidate_for_clusters()
            return {
                "success": True,
                "cluster_id": cluster_id,
                "action": "stop",
                "message": f"Cluster {cluster_name} stop initiated",
            }

        except Exception as e:
            logger.error("cluster_stop_failed", cluster_id=cluster_id, error=str(e))
            return {
                "success": False,
                "cluster_id": cluster_id,
                "action": "stop",
                "message": "Failed to stop cluster",
                "error": str(e),
            }

    # =========================================================================
    # H. SCALE HISTORY
    # =========================================================================

    async def get_scale_history(
        self,
        cluster_id: str | None = None,
        namespace: str | None = None,
        deployment_name: str | None = None,
        days: int = 30,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Get deployment scaling history from the database."""
        try:
            cutoff = datetime.utcnow() - timedelta(days=days)
            stmt = select(DeploymentScaleHistory).where(DeploymentScaleHistory.timestamp >= cutoff)

            if cluster_id:
                stmt = stmt.where(DeploymentScaleHistory.cluster_id == cluster_id)
            if namespace:
                stmt = stmt.where(DeploymentScaleHistory.namespace == namespace)
            if deployment_name:
                stmt = stmt.where(DeploymentScaleHistory.deployment_name == deployment_name)

            stmt = stmt.order_by(desc(DeploymentScaleHistory.timestamp)).limit(limit)
            result = await self.db.execute(stmt)
            records = result.scalars().all()

            return [
                {
                    "id": r.id,
                    "timestamp": r.timestamp.isoformat() if r.timestamp else None,
                    "cluster_id": r.cluster_id,
                    "cluster_name": r.cluster_name,
                    "namespace": r.namespace,
                    "deployment_name": r.deployment_name,
                    "previous_replicas": r.previous_replicas,
                    "new_replicas": r.new_replicas,
                    "user_email": r.initiated_by_email or r.initiated_by,
                }
                for r in records
            ]

        except Exception as e:
            logger.error("scale_history_query_failed", error=str(e))
            return []

    # =========================================================================
    # HELPER METHODS
    # =========================================================================

    async def _get_subscriptions(
        self,
        subscription_ids: list[str] | None = None,
    ) -> list[dict[str, str]]:
        """Get list of subscriptions to query, with display names resolved from Azure REST API.

        Uses Redis L1 cache (TTL 10 min — almost static).
        """
        cache_key = CacheKeys.subscriptions(subscription_ids)

        async def _fetch_subs_live() -> list[dict[str, str]]:
            target_ids = subscription_ids or await get_monitored_subscription_ids()
            if not target_ids:
                logger.warning("No subscriptions configured.")
                return []

            # Try to resolve real display names via Azure REST API
            try:
                token = self.credential.get_token("https://management.azure.com/.default")
                id_to_name: dict[str, str] = {}
                headers = {"Authorization": f"Bearer {token.token}"}
                async with httpx.AsyncClient(timeout=30.0) as client:
                    for sid in target_ids:
                        api_url = f"https://management.azure.com/subscriptions/{sid}?api-version=2022-12-01"
                        response = await client.get(api_url, headers=headers)
                        response.raise_for_status()
                        sub_data = response.json()
                        id_to_name[sid] = sub_data.get("displayName", sid)
                return [{"id": sid, "name": id_to_name.get(sid, sid)} for sid in target_ids]
            except Exception as e:
                logger.warning("subscription_name_resolution_failed", error=str(e))
                return [{"id": sid, "name": sid} for sid in target_ids]

        cached, tier = await data_cache.get_or_fetch(
            key=cache_key,
            ttl=TTL.SUBSCRIPTIONS,
            fetch_fn=_fetch_subs_live,
        )
        return cached

    async def _get_k8s_clients(
        self,
        cluster_id: str,
    ) -> tuple[k8s_client.AppsV1Api, k8s_client.CoreV1Api, k8s_client.BatchV1Api]:
        """Get or create Kubernetes API clients for a cluster.

        Handles both AAD-only clusters (local accounts disabled) and legacy clusters.
        Uses user credentials first; falls back to admin credentials, then direct
        cluster info when both credential methods fail.
        """
        import time as _time

        # Evict stale clients whose tokens may have expired
        if cluster_id in self._k8s_clients:
            age = _time.time() - self._k8s_clients_ts.get(cluster_id, 0)
            if age > self._K8S_CLIENT_TTL:
                del self._k8s_clients[cluster_id]
                del self._k8s_clients_ts[cluster_id]
                logger.info("k8s_client_cache_evicted", cluster_id=cluster_id, age_s=round(age))

        if cluster_id not in self._k8s_clients:
            import yaml

            # Parse cluster details from resource ID
            parts = cluster_id.split("/")
            subscription_id = parts[2]
            resource_group = parts[4]
            cluster_name = parts[8]

            aks_client = ContainerServiceClient(self.credential, subscription_id)
            kubeconfig = None

            # 1) Try user credentials (works with AAD-only / local-accounts-disabled clusters)
            try:
                creds = await asyncio.to_thread(
                    aks_client.managed_clusters.list_cluster_user_credentials,
                    resource_group,
                    cluster_name,
                )
                kubeconfig = creds.kubeconfigs[0].value.decode("utf-8")
                logger.info("k8s_user_credentials_ok", cluster=cluster_name)
            except Exception as e:
                logger.warning("k8s_user_credentials_failed", cluster=cluster_name, error=str(e))

            # 2) Fallback: admin credentials
            if kubeconfig is None:
                try:
                    creds = await asyncio.to_thread(
                        aks_client.managed_clusters.list_cluster_admin_credentials,
                        resource_group,
                        cluster_name,
                    )
                    kubeconfig = creds.kubeconfigs[0].value.decode("utf-8")
                    logger.info("k8s_admin_credentials_ok", cluster=cluster_name)
                except Exception as e:
                    logger.warning(
                        "k8s_admin_credentials_failed",
                        cluster=cluster_name,
                        error=str(e),
                    )

            configuration = k8s_client.Configuration()

            if kubeconfig:
                config_dict = yaml.safe_load(kubeconfig)
                configuration.host = config_dict["clusters"][0]["cluster"]["server"]

                ca_data = config_dict["clusters"][0]["cluster"].get("certificate-authority-data")
                if ca_data:
                    configuration.ssl_ca_cert = self._write_temp_cert(ca_data)

                # Private-link AKS endpoints use Microsoft-internal TLS certs
                # that are not in the default trust store. Skip verification for
                # privatelink endpoints (common in enterprise environments).
                if "privatelink" in configuration.host:
                    configuration.verify_ssl = False
            else:
                # 3) Last resort: fetch FQDN directly from the cluster resource
                cluster_info = await asyncio.to_thread(
                    aks_client.managed_clusters.get,
                    resource_group,
                    cluster_name,
                )
                configuration.host = f"https://{cluster_info.fqdn}:443"
                configuration.verify_ssl = False  # no CA cert available
                logger.warning("k8s_using_fqdn_fallback", cluster=cluster_name)

            # Always authenticate with Azure AD token (AKS AAD Server audience)
            token = self._get_k8s_token()
            configuration.api_key = {"authorization": f"Bearer {token}"}

            api_client = k8s_client.ApiClient(configuration)
            self._k8s_clients[cluster_id] = (
                k8s_client.AppsV1Api(api_client),
                k8s_client.CoreV1Api(api_client),
                k8s_client.BatchV1Api(api_client),
            )
            self._k8s_clients_ts[cluster_id] = _time.time()

        return self._k8s_clients[cluster_id]

    def _get_k8s_token(self) -> str:
        """Get Azure AD token for Kubernetes API authentication.

        Uses the AKS AAD Server application ID as the audience to obtain
        a token that the Kubernetes API server will accept.
        """
        # 6dae42f8-4368-4678-94ff-3960e28e3630 is the well-known Azure
        # Kubernetes Service AAD Server application ID.
        token = self.credential.get_token("6dae42f8-4368-4678-94ff-3960e28e3630/.default")
        return token.token

    def _get_azure_token(self) -> str:
        """Get Azure token for management API calls."""
        token = self.credential.get_token("https://management.azure.com/.default")
        return token.token

    def _write_temp_cert(self, cert_data: str) -> str:
        """Write certificate to temp file and return path."""
        import base64
        import tempfile

        cert_bytes = base64.b64decode(cert_data)
        with tempfile.NamedTemporaryFile(mode="wb", delete=False, suffix=".crt") as f:
            f.write(cert_bytes)
            return f.name

    def _extract_resource_group(self, resource_id: str) -> str:
        """Extract resource group from Azure resource ID."""
        parts = resource_id.split("/")
        try:
            # Azure resource IDs may use "resourceGroups" or "resourcegroups"
            lower_parts = [p.lower() for p in parts]
            rg_idx = lower_parts.index("resourcegroups") + 1
            return parts[rg_idx]
        except (ValueError, IndexError):
            return ""

    def _extract_cluster_name(self, resource_id: str) -> str:
        """Extract cluster name from resource ID."""
        parts = resource_id.split("/")
        return parts[-1] if parts else ""

    def _format_addon_profiles(self, profiles: dict | None) -> dict[str, Any]:
        """Format addon profiles for API response."""
        if not profiles:
            return {}
        return {
            name: {
                "enabled": profile.enabled,
                "config": dict(profile.config) if profile.config else {},
            }
            for name, profile in profiles.items()
        }

    @staticmethod
    def _parse_cpu_to_millicores(cpu_str: str) -> float:
        """Convert Kubernetes CPU string to millicores.

        Examples: '100m' -> 100, '0.5' -> 500, '2' -> 2000
        """
        if not cpu_str or cpu_str == "0":
            return 0.0
        cpu_str = str(cpu_str).strip()
        if cpu_str.endswith("m"):
            return float(cpu_str[:-1])
        if cpu_str.endswith("n"):
            return float(cpu_str[:-1]) / 1_000_000
        return float(cpu_str) * 1000

    @staticmethod
    def _parse_memory_to_mb(mem_str: str) -> float:
        """Convert Kubernetes memory string to megabytes.

        Examples: '128Mi' -> 128, '1Gi' -> 1024, '500000Ki' -> ~488
        """
        if not mem_str or mem_str == "0":
            return 0.0
        mem_str = str(mem_str).strip()
        if mem_str.endswith("Ki"):
            return float(mem_str[:-2]) / 1024
        if mem_str.endswith("Mi"):
            return float(mem_str[:-2])
        if mem_str.endswith("Gi"):
            return float(mem_str[:-2]) * 1024
        if mem_str.endswith("Ti"):
            return float(mem_str[:-2]) * 1024 * 1024
        if mem_str.endswith("K") or mem_str.endswith("k"):
            return float(mem_str[:-1]) / 1024
        if mem_str.endswith("M"):
            return float(mem_str[:-1])
        if mem_str.endswith("G"):
            return float(mem_str[:-1]) * 1024
        # Plain bytes
        try:
            return float(mem_str) / (1024 * 1024)
        except ValueError:
            return 0.0

    # =========================================================================
    # AKS CLUSTER DB CACHING (AzureResourceInventory)
    # =========================================================================

    async def sync_clusters_to_db(self) -> dict[str, Any]:
        """
        Sync AKS clusters from Azure live API to DB (AzureResourceInventory).

        Strategy: DELETE all existing 'aks_cluster' rows then INSERT fresh data.
        Returns sync result with count and last_sync timestamp.
        """
        clusters = await self._fetch_clusters_live()

        if not self.db:
            return {
                "synced_count": len(clusters),
                "resource_type": "aks_cluster",
                "last_sync": datetime.utcnow().isoformat(),
                "resources": clusters,
                "db_saved": False,
            }

        try:
            # Delete existing aks_cluster rows
            await self.db.execute(
                delete(AzureResourceInventory).where(AzureResourceInventory.resource_type == "aks_cluster")
            )

            # Insert fresh rows
            for cluster in clusters:
                record = AzureResourceInventory(
                    resource_id=cluster.get("id", ""),
                    name=cluster.get("name", ""),
                    resource_type="aks_cluster",
                    resource_group=cluster.get("resource_group", ""),
                    location=cluster.get("location", ""),
                    subscription_id=cluster.get("subscription_id", ""),
                    provisioning_state=cluster.get("provisioning_state"),
                    tags=cluster.get("tags", {}),
                    resource_details=cluster,  # full payload as JSONB
                )
                self.db.add(record)

            await self.db.commit()
            logger.info("aks_clusters_synced_to_db", count=len(clusters))
        except Exception as e:
            logger.error("aks_clusters_sync_failed", error=str(e))
            await self.db.rollback()
            raise

        return {
            "synced_count": len(clusters),
            "resource_type": "aks_cluster",
            "last_sync": datetime.utcnow().isoformat(),
            "resources": clusters,
            "db_saved": True,
        }

    async def get_clusters_from_db(self) -> list[dict[str, Any]]:
        """
        Get AKS clusters from database inventory (fast, no Azure API call).
        Returns the full cluster payload stored during sync.
        """
        if not self.db:
            return []

        try:
            subscription_ids = await get_monitored_subscription_ids()
            if not subscription_ids:
                return []

            query = (
                select(AzureResourceInventory)
                .where(AzureResourceInventory.resource_type == "aks_cluster")
                .where(AzureResourceInventory.subscription_id.in_(subscription_ids))
                .order_by(AzureResourceInventory.name)
            )
            result = await self.db.execute(query)
            records = result.scalars().all()

            clusters = []
            for r in records:
                details = r.resource_details or {}
                details["_last_sync"] = r.last_sync.isoformat() if r.last_sync else None
                clusters.append(details)

            return clusters
        except Exception as e:
            logger.error("get_clusters_from_db_failed", error=str(e))
            return []

    async def get_clusters_last_sync_time(self) -> str | None:
        """Get the last sync timestamp for AKS clusters in DB."""
        if not self.db:
            return None
        try:
            from sqlalchemy import func as sa_func

            subscription_ids = await get_monitored_subscription_ids()
            if not subscription_ids:
                return None

            query = select(sa_func.max(AzureResourceInventory.last_sync)).where(
                AzureResourceInventory.resource_type == "aks_cluster",
                AzureResourceInventory.subscription_id.in_(subscription_ids),
            )
            result = await self.db.execute(query)
            last_sync = result.scalar()
            return last_sync.isoformat() if last_sync else None
        except Exception as e:
            logger.error("get_clusters_last_sync_failed", error=str(e))
            return None

    # =========================================================================
    # Deployment DB Caching — Sync from K8s live API to AzureResourceInventory
    # =========================================================================

    async def sync_deployments_to_db(
        self,
        cluster_id: str,
        namespace: str | None = None,
    ) -> dict[str, Any]:
        """
        Sync Deployments from K8s live API to DB (AzureResourceInventory).

        Strategy: DELETE all existing 'aks_deployment' rows for this cluster,
        then INSERT fresh data.
        """
        deployments = await self._fetch_deployments_live(cluster_id, namespace)

        if not self.db:
            return {
                "synced_count": len(deployments),
                "resource_type": "aks_deployment",
                "cluster_id": cluster_id,
                "last_sync": datetime.utcnow().isoformat(),
                "resources": deployments,
                "db_saved": False,
            }

        try:
            # Delete existing aks_deployment rows for this cluster
            await self.db.execute(
                delete(AzureResourceInventory).where(
                    AzureResourceInventory.resource_type == "aks_deployment",
                    AzureResourceInventory.resource_id.like(f"{cluster_id}/deployment/%"),
                )
            )

            # Extract subscription_id and resource_group from cluster_id
            sub_id = ""
            rg = ""
            parts = cluster_id.split("/")
            for i, p in enumerate(parts):
                if p.lower() == "subscriptions" and i + 1 < len(parts):
                    sub_id = parts[i + 1]
                if p.lower() == "resourcegroups" and i + 1 < len(parts):
                    rg = parts[i + 1]

            # Insert fresh rows
            for dep in deployments:
                dep_with_cluster = {**dep, "_cluster_id": cluster_id}
                ready = dep.get("ready_replicas", 0)
                desired = dep.get("replicas", 0)
                state = "Ready" if ready == desired else "Progressing"
                record = AzureResourceInventory(
                    resource_id=f"{cluster_id}/deployment/{dep.get('namespace', '')}/{dep.get('name', '')}",
                    name=dep.get("name", ""),
                    resource_type="aks_deployment",
                    resource_group=rg,
                    location="",
                    subscription_id=sub_id,
                    provisioning_state=state,
                    tags={},
                    resource_details=dep_with_cluster,
                )
                self.db.add(record)

            await self.db.commit()
            logger.info(
                "aks_deployments_synced_to_db",
                cluster_id=cluster_id,
                count=len(deployments),
            )
        except Exception as e:
            logger.error("aks_deployments_sync_failed", cluster_id=cluster_id, error=str(e))
            await self.db.rollback()
            raise

        return {
            "synced_count": len(deployments),
            "resource_type": "aks_deployment",
            "cluster_id": cluster_id,
            "last_sync": datetime.utcnow().isoformat(),
            "resources": deployments,
            "db_saved": True,
        }

    async def get_deployments_from_db(
        self,
        cluster_id: str,
        namespace: str | None = None,
    ) -> list[dict[str, Any]]:
        """
        Get Deployments from database inventory (fast, no K8s API call).
        Returns the full deployment payload stored during sync.
        """
        if not self.db:
            return []

        try:
            query = (
                select(AzureResourceInventory)
                .where(
                    AzureResourceInventory.resource_type == "aks_deployment",
                    AzureResourceInventory.resource_id.like(f"{cluster_id}/deployment/%"),
                )
                .order_by(AzureResourceInventory.name)
            )
            result = await self.db.execute(query)
            records = result.scalars().all()

            deployments = []
            for r in records:
                details = r.resource_details or {}
                details["_last_sync"] = r.last_sync.isoformat() if r.last_sync else None
                if namespace and details.get("namespace") != namespace:
                    continue
                deployments.append(details)

            return deployments
        except Exception as e:
            logger.error("get_deployments_from_db_failed", cluster_id=cluster_id, error=str(e))
            return []

    async def get_deployments_last_sync_time(self, cluster_id: str) -> str | None:
        """Get the last sync timestamp for Deployments of a cluster in DB."""
        if not self.db:
            return None
        try:
            from sqlalchemy import func as sa_func

            query = select(sa_func.max(AzureResourceInventory.last_sync)).where(
                AzureResourceInventory.resource_type == "aks_deployment",
                AzureResourceInventory.resource_id.like(f"{cluster_id}/deployment/%"),
            )
            result = await self.db.execute(query)
            last_sync = result.scalar()
            return last_sync.isoformat() if last_sync else None
        except Exception as e:
            logger.error("get_deployments_last_sync_failed", cluster_id=cluster_id, error=str(e))
            return None

    # =========================================================================
    # CronJob DB Caching — Sync from K8s live API to AzureResourceInventory
    # =========================================================================

    async def sync_cronjobs_to_db(
        self,
        cluster_id: str,
        namespace: str | None = None,
    ) -> dict[str, Any]:
        """
        Sync CronJobs from K8s live API to DB (AzureResourceInventory).

        Strategy: DELETE all existing 'aks_cronjob' rows for this cluster,
        then INSERT fresh data.
        """
        cronjobs = await self._fetch_cronjobs_live(cluster_id, namespace)

        if not self.db:
            return {
                "synced_count": len(cronjobs),
                "resource_type": "aks_cronjob",
                "cluster_id": cluster_id,
                "last_sync": datetime.utcnow().isoformat(),
                "resources": cronjobs,
                "db_saved": False,
            }

        try:
            delete_stmt = delete(AzureResourceInventory).where(
                AzureResourceInventory.resource_type == "aks_cronjob",
            )
            if namespace:
                delete_stmt = delete_stmt.where(
                    AzureResourceInventory.resource_id.like(f"{cluster_id}/cronjob/{namespace}/%")
                )
            else:
                delete_stmt = delete_stmt.where(AzureResourceInventory.resource_id.like(f"{cluster_id}/cronjob/%"))

            await self.db.execute(delete_stmt)

            # Extract subscription_id from cluster_id
            # e.g. /subscriptions/<sub>/resourceGroups/<rg>/providers/...
            sub_id = ""
            rg = ""
            parts = cluster_id.split("/")
            for i, p in enumerate(parts):
                if p.lower() == "subscriptions" and i + 1 < len(parts):
                    sub_id = parts[i + 1]
                if p.lower() == "resourcegroups" and i + 1 < len(parts):
                    rg = parts[i + 1]

            # Insert fresh rows
            for cj in cronjobs:
                cj_with_cluster = {**cj, "_cluster_id": cluster_id}
                record = AzureResourceInventory(
                    resource_id=f"{cluster_id}/cronjob/{cj.get('namespace', '')}/{cj.get('name', '')}",
                    name=cj.get("name", ""),
                    resource_type="aks_cronjob",
                    resource_group=rg,
                    location="",
                    subscription_id=sub_id,
                    provisioning_state=("Active" if not cj.get("suspended") else "Suspended"),
                    tags={},
                    resource_details=cj_with_cluster,
                )
                self.db.add(record)

            await self.db.commit()
            logger.info("aks_cronjobs_synced_to_db", cluster_id=cluster_id, count=len(cronjobs))
        except Exception as e:
            logger.error("aks_cronjobs_sync_failed", cluster_id=cluster_id, error=str(e))
            await self.db.rollback()
            raise

        return {
            "synced_count": len(cronjobs),
            "resource_type": "aks_cronjob",
            "cluster_id": cluster_id,
            "last_sync": datetime.utcnow().isoformat(),
            "resources": cronjobs,
            "db_saved": True,
        }

    async def get_cronjobs_from_db(
        self,
        cluster_id: str,
        namespace: str | None = None,
    ) -> list[dict[str, Any]]:
        """
        Get CronJobs from database inventory (fast, no K8s API call).
        Returns the full cronjob payload stored during sync.
        """
        if not self.db:
            return []

        try:
            query = (
                select(AzureResourceInventory)
                .where(
                    AzureResourceInventory.resource_type == "aks_cronjob",
                    AzureResourceInventory.resource_id.like(f"{cluster_id}/cronjob/%"),
                )
                .order_by(AzureResourceInventory.name)
            )
            result = await self.db.execute(query)
            records = result.scalars().all()

            cronjobs = []
            for r in records:
                details = r.resource_details or {}
                details["_last_sync"] = r.last_sync.isoformat() if r.last_sync else None
                if namespace and details.get("namespace") != namespace:
                    continue
                cronjobs.append(details)

            return cronjobs
        except Exception as e:
            logger.error("get_cronjobs_from_db_failed", cluster_id=cluster_id, error=str(e))
            return []

    async def get_cronjobs_last_sync_time(self, cluster_id: str) -> str | None:
        """Get the last sync timestamp for CronJobs of a cluster in DB."""
        if not self.db:
            return None
        try:
            from sqlalchemy import func as sa_func

            query = select(sa_func.max(AzureResourceInventory.last_sync)).where(
                AzureResourceInventory.resource_type == "aks_cronjob",
                AzureResourceInventory.resource_id.like(f"{cluster_id}/cronjob/%"),
            )
            result = await self.db.execute(query)
            last_sync = result.scalar()
            return last_sync.isoformat() if last_sync else None
        except Exception as e:
            logger.error("get_cronjobs_last_sync_failed", cluster_id=cluster_id, error=str(e))
            return None

    # =========================================================================
    # Node Pool DB Caching — Sync from Azure/K8s live API to AzureResourceInventory
    # =========================================================================

    async def sync_node_pools_to_db(
        self,
        cluster_id: str,
    ) -> dict[str, Any]:
        """
        Sync Node Pools from Azure/K8s live API to DB (AzureResourceInventory).

        Strategy: DELETE all existing 'aks_nodepool' rows for this cluster,
        then INSERT fresh data.
        """
        node_pools = await self._fetch_node_pools_live(cluster_id)

        if not self.db:
            return {
                "synced_count": len(node_pools),
                "resource_type": "aks_nodepool",
                "cluster_id": cluster_id,
                "last_sync": datetime.utcnow().isoformat(),
                "resources": node_pools,
                "db_saved": False,
            }

        try:
            # Delete existing aks_nodepool rows for this cluster
            await self.db.execute(
                delete(AzureResourceInventory).where(
                    AzureResourceInventory.resource_type == "aks_nodepool",
                    AzureResourceInventory.resource_id.like(f"{cluster_id}/nodepool/%"),
                )
            )

            # Extract subscription_id and resource_group from cluster_id
            sub_id = ""
            rg = ""
            parts = cluster_id.split("/")
            for i, p in enumerate(parts):
                if p.lower() == "subscriptions" and i + 1 < len(parts):
                    sub_id = parts[i + 1]
                if p.lower() == "resourcegroups" and i + 1 < len(parts):
                    rg = parts[i + 1]

            # Insert fresh rows
            for np in node_pools:
                np_with_cluster = {**np, "_cluster_id": cluster_id}
                record = AzureResourceInventory(
                    resource_id=f"{cluster_id}/nodepool/{np.get('name', '')}",
                    name=np.get("name", ""),
                    resource_type="aks_nodepool",
                    resource_group=rg,
                    location="",
                    subscription_id=sub_id,
                    provisioning_state=np.get("provisioning_state", "Unknown"),
                    tags={},
                    resource_details=np_with_cluster,
                )
                self.db.add(record)

            await self.db.commit()
            logger.info(
                "aks_node_pools_synced_to_db",
                cluster_id=cluster_id,
                count=len(node_pools),
            )
        except Exception as e:
            logger.error("aks_node_pools_sync_failed", cluster_id=cluster_id, error=str(e))
            await self.db.rollback()
            raise

        return {
            "synced_count": len(node_pools),
            "resource_type": "aks_nodepool",
            "cluster_id": cluster_id,
            "last_sync": datetime.utcnow().isoformat(),
            "resources": node_pools,
            "db_saved": True,
        }

    async def get_node_pools_from_db(
        self,
        cluster_id: str,
    ) -> list[dict[str, Any]]:
        """
        Get Node Pools from database inventory (fast, no Azure/K8s API call).
        Returns the full node pool payload stored during sync.
        """
        if not self.db:
            return []

        try:
            query = (
                select(AzureResourceInventory)
                .where(
                    AzureResourceInventory.resource_type == "aks_nodepool",
                    AzureResourceInventory.resource_id.like(f"{cluster_id}/nodepool/%"),
                )
                .order_by(AzureResourceInventory.name)
            )
            result = await self.db.execute(query)
            records = result.scalars().all()

            node_pools = []
            for r in records:
                details = r.resource_details or {}
                details["_last_sync"] = r.last_sync.isoformat() if r.last_sync else None
                node_pools.append(details)

            return node_pools
        except Exception as e:
            logger.error("get_node_pools_from_db_failed", cluster_id=cluster_id, error=str(e))
            return []

    async def get_node_pools_last_sync_time(self, cluster_id: str) -> str | None:
        """Get the last sync timestamp for Node Pools of a cluster in DB."""
        if not self.db:
            return None
        try:
            from sqlalchemy import func as sa_func

            query = select(sa_func.max(AzureResourceInventory.last_sync)).where(
                AzureResourceInventory.resource_type == "aks_nodepool",
                AzureResourceInventory.resource_id.like(f"{cluster_id}/nodepool/%"),
            )
            result = await self.db.execute(query)
            last_sync = result.scalar()
            return last_sync.isoformat() if last_sync else None
        except Exception as e:
            logger.error("get_node_pools_last_sync_failed", cluster_id=cluster_id, error=str(e))
            return None


# Factory function for dependency injection
def get_aks_operations_service(db_session: AsyncSession | None) -> AKSOperationsService:
    """Create AKS Operations Service instance."""
    return AKSOperationsService(db_session)
