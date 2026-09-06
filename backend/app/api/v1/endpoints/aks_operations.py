"""
AKS Operations API Endpoints.

Full management interface for Azure Kubernetes Service operations:
- Cluster inventory and health
- Deployment management and scaling
- Pod observability and metrics
- CronJob management
- 3-Tier cached data retrieval (Redis L1 → DB L2 → Live API L3)
"""

from collections import deque
from datetime import UTC, datetime

import structlog
from fastapi import APIRouter, Body, Depends, HTTPException, Path, Query, Request
from kubernetes.client.rest import ApiException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.endpoints.aks_extended_endpoints import register_extended_routes
from app.auth import get_current_user, require_role
from app.core.authz import require_capability
from app.core.database import get_db, get_standalone_session
from app.models.auth import UserContext, UserRole
from app.models.database import AuditLog
from app.services.aks_operations_service import (
    AKSOperationsService,
    get_aks_operations_service,
)
from app.services.data_cache_service import data_cache

logger = structlog.get_logger(__name__)
router = APIRouter()

# In-memory audit store — used when PostgreSQL is unavailable (local dev).
# Capped at 500 entries to avoid unbounded memory growth.
_in_memory_audit_log: deque[dict] = deque(maxlen=500)
_next_audit_id: int = 1


def _get_service(db: AsyncSession = Depends(get_db)) -> AKSOperationsService:
    return get_aks_operations_service(db)


def _cluster_name_from_id(cluster_id: str) -> str:
    """Extract short cluster name from Azure resource ID."""
    return cluster_id.rstrip("/").rsplit("/", 1)[-1]


def _audit_summary(action: str, resource_type: str, resource_name: str) -> str:
    verb = {
        "create_deployment": "Created",
        "update_deployment": "Updated",
        "delete_deployment": "Deleted",
        "scale_deployment": "Scaled",
        "restart_deployment": "Restarted",
        "create_secret": "Created",
        "update_secret": "Updated",
        "delete_secret": "Deleted",
        "reveal_secret": "Revealed",
        "create_service": "Created",
        "delete_service": "Deleted",
        "create_configmap": "Created",
        "update_configmap": "Updated",
        "delete_configmap": "Deleted",
        "create_ingress": "Created",
        "update_ingress": "Updated",
        "delete_ingress": "Deleted",
        "create_cronjob": "Created",
        "update_cronjob": "Updated",
        "delete_cronjob": "Deleted",
        "suspend_cronjob": "Suspended",
        "resume_cronjob": "Resumed",
        "trigger_cronjob": "Triggered",
        "start_cluster": "Started",
        "stop_cluster": "Stopped",
        "scale_nodepool": "Scaled",
        "autoscale_nodepool": "Autoscale changed",
        "helm_install": "Installed",
        "helm_upgrade": "Upgraded",
        "helm_uninstall": "Uninstalled",
        "helm_rollback": "Rolled back",
    }.get(action, "Changed")
    return f"{verb} {resource_type} {resource_name}"


def _serialize_aks_audit_entry(entry: AuditLog) -> dict:
    details = entry.details if isinstance(entry.details, dict) else {}
    resource_name = details.get("resource_name") or entry.resource_id or "unknown"
    resource_type = details.get("resource_type") or entry.resource_type or "item"
    summary = details.get("summary") or _audit_summary(entry.action, resource_type, resource_name)
    return {
        "id": entry.id,
        "timestamp": entry.timestamp.isoformat() if entry.timestamp else None,
        "user_id": entry.user_id,
        "user_email": entry.user_email,
        "action": entry.action,
        "resource_type": resource_type,
        "resource_id": entry.resource_id,
        "resource_name": resource_name,
        "cluster_id": details.get("cluster_id"),
        "cluster_name": details.get("cluster_name"),
        "namespace": details.get("namespace"),
        "status": entry.status,
        "summary": summary,
        "details": details,
    }


async def _write_aks_audit_log(
    db: AsyncSession | None,
    *,
    request: Request | None = None,
    user: UserContext,
    action: str,
    resource_type: str,
    resource_name: str,
    cluster_id: str,
    namespace: str,
    status: str,
    details: dict,
) -> None:
    """Write an AuditLog entry for AKS operations.

    Uses a dedicated session to avoid conflicts with the request's session.
    Falls back to in-memory storage when the DB is entirely unavailable.
    """
    global _next_audit_id

    timestamp = datetime.now(UTC).replace(tzinfo=None)
    audit_details = {
        "page": "AKSOperationsPage",
        "feature": "aks_audit_history",
        "cluster_id": cluster_id,
        "cluster_name": _cluster_name_from_id(cluster_id) if cluster_id else "",
        "namespace": namespace,
        "resource_name": resource_name,
        "resource_type": resource_type,
        "summary": details.get("summary") or _audit_summary(action, resource_type, resource_name),
        **details,
    }
    ip_address = request.client.host if request and request.client else None

    # Try writing to PostgreSQL using a dedicated session
    session = await get_standalone_session()
    if session is not None:
        try:
            entry = AuditLog(
                user_id=user.user_id,
                user_email=user.email,
                action=action,
                resource_type=resource_type,
                resource_id=resource_name,
                details=audit_details,
                ip_address=ip_address,
                status=status,
                timestamp=timestamp,
            )
            session.add(entry)
            await session.commit()
            logger.info(
                "aks_audit_log_written",
                action=action,
                resource=resource_name,
                status=status,
            )
            return
        except Exception as exc:
            await session.rollback()
            logger.warning(
                "aks_audit_log_db_failed",
                action=action,
                resource=resource_name,
                error=str(exc),
            )
        finally:
            await session.close()

    # Fallback: store in memory when DB is unavailable
    entry_dict = {
        "id": _next_audit_id,
        "timestamp": timestamp.isoformat(),
        "user_id": user.user_id,
        "user_email": user.email,
        "action": action,
        "resource_type": resource_type,
        "resource_id": resource_name,
        "resource_name": resource_name,
        "cluster_id": cluster_id,
        "cluster_name": _cluster_name_from_id(cluster_id) if cluster_id else "",
        "namespace": namespace,
        "status": status,
        "summary": audit_details["summary"],
        "details": audit_details,
        "ip_address": ip_address,
    }
    _next_audit_id += 1
    _in_memory_audit_log.appendleft(entry_dict)
    logger.info("aks_audit_log_memory", action=action, resource=resource_name, status=status)


# ── Request/Response Models ────────────────────────────────────────────


class ScaleDeploymentRequest(BaseModel):
    """Request to scale a deployment."""

    cluster_id: str = Field(..., description="Full Azure resource ID of the AKS cluster")
    namespace: str = Field(..., description="Kubernetes namespace")
    deployment_name: str = Field(..., description="Deployment name")
    replicas: int = Field(..., ge=0, le=100, description="Target replica count")


class RestartDeploymentRequest(BaseModel):
    """Request to restart a deployment."""

    cluster_id: str = Field(..., description="Full Azure resource ID of the AKS cluster")
    namespace: str = Field(..., description="Kubernetes namespace")
    deployment_name: str = Field(..., description="Deployment name")


class SuspendCronJobRequest(BaseModel):
    """Request to suspend/resume a CronJob."""

    cluster_id: str = Field(..., description="Full Azure resource ID of the AKS cluster")
    namespace: str = Field(..., description="Kubernetes namespace")
    cronjob_name: str = Field(..., description="CronJob name")
    suspend: bool = Field(..., description="True to suspend, False to resume")


class TriggerCronJobRequest(BaseModel):
    """Request to manually trigger a CronJob."""

    cluster_id: str = Field(..., description="Full Azure resource ID of the AKS cluster")
    namespace: str = Field(..., description="Kubernetes namespace")
    cronjob_name: str = Field(..., description="CronJob name")


class CreateDeploymentRequest(BaseModel):
    """Request to create a new deployment."""

    cluster_id: str = Field(..., description="Full Azure resource ID of the AKS cluster")
    namespace: str = Field(..., description="Kubernetes namespace")
    name: str = Field(..., min_length=1, max_length=63, pattern=r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?$")
    image: str = Field(..., description="Container image")
    replicas: int = Field(default=1, ge=0, le=100, description="Replica count")
    labels: dict[str, str] = Field(default_factory=dict, description="Pod labels")
    cpu_request: str = Field(default="100m", description="CPU request")
    cpu_limit: str = Field(default="500m", description="CPU limit")
    memory_request: str = Field(default="128Mi", description="Memory request")
    memory_limit: str = Field(default="512Mi", description="Memory limit")
    port: int | None = Field(default=None, description="Container port")
    env_vars: dict[str, str] = Field(default_factory=dict, description="Environment variables")


class UpdateDeploymentRequest(BaseModel):
    """Request to update an existing deployment."""

    cluster_id: str = Field(..., description="Full Azure resource ID of the AKS cluster")
    namespace: str = Field(..., description="Kubernetes namespace")
    name: str = Field(..., description="Deployment name")
    image: str | None = Field(default=None, description="Container image")
    replicas: int | None = Field(default=None, ge=0, le=100, description="Replica count")
    cpu_request: str | None = Field(default=None, description="CPU request")
    cpu_limit: str | None = Field(default=None, description="CPU limit")
    memory_request: str | None = Field(default=None, description="Memory request")
    memory_limit: str | None = Field(default=None, description="Memory limit")
    env_vars: dict[str, str] | None = Field(default=None, description="Environment variables")


class DeleteDeploymentRequest(BaseModel):
    """Request to delete a deployment."""

    cluster_id: str = Field(..., description="Full Azure resource ID of the AKS cluster")
    namespace: str = Field(..., description="Kubernetes namespace")
    name: str = Field(..., description="Deployment name")


class CreateCronJobRequest(BaseModel):
    """Request to create a new CronJob."""

    cluster_id: str = Field(..., description="Full Azure resource ID of the AKS cluster")
    namespace: str = Field(..., description="Kubernetes namespace")
    name: str = Field(..., min_length=1, max_length=63, pattern=r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?$")
    schedule: str = Field(..., description="Cron schedule expression")
    image: str = Field(..., description="Container image")
    command: list[str] | None = Field(default=None, description="Command to run")
    args: list[str] | None = Field(default=None, description="Command arguments")
    restart_policy: str = Field(default="OnFailure", description="Restart policy (Never or OnFailure)")
    labels: dict[str, str] = Field(default_factory=dict, description="Pod labels")
    cpu_request: str = Field(default="100m", description="CPU request")
    cpu_limit: str = Field(default="500m", description="CPU limit")
    memory_request: str = Field(default="128Mi", description="Memory request")
    memory_limit: str = Field(default="256Mi", description="Memory limit")
    concurrency_policy: str = Field(default="Forbid", description="Allow, Forbid, or Replace")
    successful_jobs_history_limit: int = Field(default=3, ge=0, description="Successful jobs history limit")
    failed_jobs_history_limit: int = Field(default=1, ge=0, description="Failed jobs history limit")
    backoff_limit: int = Field(default=6, ge=0, description="Job backoff limit")
    active_deadline_seconds: int | None = Field(default=None, description="Active deadline in seconds")
    ttl_seconds_after_finished: int | None = Field(default=None, description="TTL after job finished")
    service_account_name: str | None = Field(default=None, description="Service account name")


class UpdateCronJobRequest(BaseModel):
    """Request to update an existing CronJob."""

    cluster_id: str = Field(..., description="Full Azure resource ID of the AKS cluster")
    namespace: str = Field(..., description="Kubernetes namespace")
    name: str = Field(..., description="CronJob name")
    schedule: str | None = Field(default=None, description="Cron schedule expression")
    image: str | None = Field(default=None, description="Container image")
    command: list[str] | None = Field(default=None, description="Command to run")
    args: list[str] | None = Field(default=None, description="Command arguments")
    suspended: bool | None = Field(default=None, description="Suspend state")
    concurrency_policy: str | None = Field(default=None, description="Allow, Forbid, or Replace")
    successful_jobs_history_limit: int | None = Field(default=None, ge=0, description="Successful jobs history limit")
    failed_jobs_history_limit: int | None = Field(default=None, ge=0, description="Failed jobs history limit")
    cpu_request: str | None = Field(default=None, description="CPU request")
    cpu_limit: str | None = Field(default=None, description="CPU limit")
    memory_request: str | None = Field(default=None, description="Memory request")
    memory_limit: str | None = Field(default=None, description="Memory limit")


class ScaleNodePoolRequest(BaseModel):
    """Request to scale a node pool."""

    cluster_id: str = Field(..., description="Full Azure resource ID of the AKS cluster")
    nodepool_name: str = Field(..., description="Node pool name")
    node_count: int = Field(..., ge=0, le=1000, description="Target node count")


class UpdateAutoscalingRequest(BaseModel):
    """Request to update node pool autoscaling."""

    cluster_id: str = Field(..., description="Full Azure resource ID of the AKS cluster")
    nodepool_name: str = Field(..., description="Node pool name")
    enable_auto_scaling: bool = Field(..., description="Whether to enable autoscaling")
    min_count: int | None = Field(default=None, description="Minimum node count")
    max_count: int | None = Field(default=None, description="Maximum node count")


class ClusterActionRequest(BaseModel):
    """Request to start or stop a cluster."""

    cluster_id: str = Field(..., description="Full Azure resource ID of the AKS cluster")


# ── Cluster Inventory ──────────────────────────────────────────────────


@router.get(
    "/clusters",
    summary="List all AKS clusters",
    description="Discover clusters across all or specified subscriptions. Pass refresh=true to bypass Redis cache.",
)
async def list_clusters(
    subscription_ids: list[str] | None = Query(default=None, description="Filter by subscription IDs"),
    environment: str | None = Query(default=None, description="Filter by environment tag"),
    refresh: bool = Query(default=False, description="Bypass cache and fetch fresh data"),
    user: UserContext = Depends(require_capability("aks_view", permission_type="view", fallback_role=UserRole.READ)),
    service: AKSOperationsService = Depends(_get_service),
) -> dict:
    """Get all AKS clusters with metadata."""
    clusters = await service.get_all_clusters(subscription_ids, bypass_cache=refresh)

    if environment:
        clusters = [c for c in clusters if c.get("environment") == environment]

    return {
        "clusters": clusters,
        "count": len(clusters),
    }


@router.get(
    "/clusters/cached",
    summary="List AKS clusters from DB cache (fast)",
    description="Get clusters from database inventory. If DB is empty, falls back to live Azure API.",
)
async def list_cached_clusters(
    environment: str | None = Query(default=None, description="Filter by environment tag"),
    user: UserContext = Depends(require_capability("aks_view", permission_type="view", fallback_role=UserRole.READ)),
    service: AKSOperationsService = Depends(_get_service),
) -> dict:
    """Get all AKS clusters from DB cache — fast, no Azure API call."""
    try:
        clusters = await service.get_clusters_from_db()
        last_sync = await service.get_clusters_last_sync_time()
        if environment:
            clusters = [c for c in clusters if c.get("environment") == environment]
        return {
            "source": "db",
            "last_sync": last_sync,
            "clusters": clusters,
            "count": len(clusters),
        }
    except Exception as e:
        logger.warning("cached_clusters_db_failed", error=str(e))
        return {
            "source": "db",
            "last_sync": None,
            "clusters": [],
            "count": 0,
        }


@router.post(
    "/clusters/sync",
    summary="Sync AKS clusters from Azure to DB",
    description="Fetch all AKS clusters from Azure live API and save to database for fast cached access.",
)
async def sync_clusters_to_db(
    user: UserContext = Depends(get_current_user),
    service: AKSOperationsService = Depends(_get_service),
) -> dict:
    """Sync AKS clusters from Azure to database."""
    return await service.sync_clusters_to_db()


@router.get(
    "/clusters/{cluster_id:path}",
    summary="Get cluster details",
    description="Get detailed information about a specific AKS cluster",
)
async def get_cluster_details(
    cluster_id: str = Path(..., description="Full Azure resource ID of the AKS cluster"),
    user: UserContext = Depends(get_current_user),
    service: AKSOperationsService = Depends(_get_service),
) -> dict:
    """Get detailed cluster information."""
    details = await service.get_cluster_details(cluster_id)
    if not details:
        raise HTTPException(status_code=404, detail="Cluster not found")
    return details


@router.post(
    "/clusters/snapshot",
    summary="Snapshot cluster state",
    description="Create a point-in-time snapshot of all clusters for historical tracking",
)
async def snapshot_clusters(
    subscription_ids: list[str] = Body(default=None, description="Subscription IDs to snapshot"),
    user: UserContext = Depends(require_role(UserRole.ADMIN)),
    service: AKSOperationsService = Depends(_get_service),
) -> dict:
    """Create cluster snapshots for compliance tracking."""
    return await service.snapshot_clusters(
        subscription_ids=subscription_ids,
        user_id=user.user_id,
        user_email=user.email,
    )


# ── Deployment Management ──────────────────────────────────────────────


@router.get(
    "/deployments/cached",
    summary="List Deployments from DB cache (fast)",
    description="Get Deployments from database inventory. If DB is empty, falls back to live Kubernetes API.",
)
async def list_cached_deployments(
    cluster_id: str = Query(..., description="Full Azure resource ID of the AKS cluster"),
    namespace: str = Query(default=None, description="Filter by namespace"),
    user: UserContext = Depends(get_current_user),
    service: AKSOperationsService = Depends(_get_service),
) -> dict:
    """Get Deployments from DB cache — fast, no Kubernetes API call."""
    try:
        deployments = await service.get_deployments_from_db(cluster_id, namespace)
        last_sync = await service.get_deployments_last_sync_time(cluster_id)
        return {
            "source": "db",
            "last_sync": last_sync,
            "deployments": deployments,
            "count": len(deployments),
        }
    except Exception as e:
        logger.warning("cached_deployments_db_failed", cluster_id=cluster_id, error=str(e))
        return {
            "source": "db",
            "last_sync": None,
            "deployments": [],
            "count": 0,
        }


@router.get(
    "/deployments/status",
    summary="Lightweight deployment status poll",
    description="Returns only name, namespace, replicas, and ready_replicas for each deployment. "
    "Use live=true to fetch directly from Kubernetes instead of DB cache.",
)
async def list_deployment_status(
    cluster_id: str = Query(..., description="Full Azure resource ID of the AKS cluster"),
    namespace: str = Query(default=None, description="Filter by namespace"),
    live: bool = Query(default=False, description="Fetch live status from Kubernetes instead of DB"),
    user: UserContext = Depends(get_current_user),
    service: AKSOperationsService = Depends(_get_service),
) -> dict:
    """Lightweight status-only endpoint for smooth real-time updates."""
    try:
        if live:
            # Fetch directly from Kubernetes for immediate status after mutations
            deployments = await service.list_deployments(cluster_id, namespace, bypass_cache=True)
        else:
            deployments = await service.get_deployments_from_db(cluster_id, namespace)
        statuses = [
            {
                "name": d.get("name"),
                "namespace": d.get("namespace"),
                "replicas": d.get("replicas", 0),
                "ready_replicas": d.get("ready_replicas", 0),
            }
            for d in deployments
        ]
        return {"statuses": statuses, "count": len(statuses)}
    except Exception as e:
        logger.warning("deployment_status_poll_failed", cluster_id=cluster_id, error=str(e))
        return {"statuses": [], "count": 0}


@router.post(
    "/deployments/sync",
    summary="Sync Deployments from Kubernetes to DB",
    description="Fetch Deployments from live Kubernetes API and save to database for fast cached access.",
)
async def sync_deployments_to_db(
    cluster_id: str = Query(..., description="Full Azure resource ID of the AKS cluster"),
    namespace: str = Query(default=None, description="Filter by namespace"),
    user: UserContext = Depends(get_current_user),
    service: AKSOperationsService = Depends(_get_service),
) -> dict:
    """Sync Deployments from Kubernetes to database."""
    return await service.sync_deployments_to_db(cluster_id, namespace)


@router.get(
    "/deployments",
    summary="List deployments",
    description="List all deployments in a cluster or namespace. Pass refresh=true to bypass cache.",
)
async def list_deployments(
    cluster_id: str = Query(..., description="Full Azure resource ID of the AKS cluster"),
    namespace: str = Query(default=None, description="Filter by namespace"),
    refresh: bool = Query(default=False, description="Bypass cache and fetch fresh data"),
    user: UserContext = Depends(get_current_user),
    service: AKSOperationsService = Depends(_get_service),
) -> dict:
    """List Kubernetes deployments."""
    try:
        deployments = await service.list_deployments(cluster_id, namespace, bypass_cache=refresh)
        return {
            "deployments": deployments,
            "count": len(deployments),
        }
    except Exception as e:
        logger.error("list_deployments_failed", cluster_id=cluster_id, error=str(e))
        raise HTTPException(status_code=502, detail=f"Failed to connect to cluster: {str(e)}") from e


@router.get(
    "/deployments/details",
    summary="Get deployment details",
    description="Get a live YAML manifest view for a specific deployment.",
)
async def get_deployment_detail(
    cluster_id: str = Query(..., description="Full Azure resource ID of the AKS cluster"),
    namespace: str = Query(..., description="Kubernetes namespace"),
    name: str = Query(..., description="Deployment name"),
    user: UserContext = Depends(get_current_user),
    service: AKSOperationsService = Depends(_get_service),
) -> dict:
    """Get live deployment detail including YAML manifest."""
    try:
        return await service.get_deployment_detail(cluster_id, namespace, name)
    except Exception as e:
        logger.error("get_deployment_detail_failed", name=name, namespace=namespace, error=str(e))
        raise HTTPException(status_code=502, detail=f"Failed to fetch deployment detail: {str(e)}") from e


@router.post(
    "/deployments/scale",
    summary="Scale deployment",
    description="Scale a deployment to the specified replica count",
)
async def scale_deployment(
    request: ScaleDeploymentRequest,
    http_request: Request,
    user: UserContext = Depends(require_capability("aks_deployment_scale")),
    service: AKSOperationsService = Depends(_get_service),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Scale a deployment with audit logging."""
    result = await service.scale_deployment(
        cluster_id=request.cluster_id,
        namespace=request.namespace,
        deployment_name=request.deployment_name,
        replicas=request.replicas,
        user_id=user.user_id,
        user_email=user.email,
    )

    success = result.get("success", False)
    prev = result.get("previous_replicas")
    new_r = result.get("new_replicas", request.replicas)
    action = "scale_up" if (prev is None or request.replicas >= (prev or 0)) else "scale_down"

    await _write_aks_audit_log(
        db,
        user=user,
        action=action,
        resource_type="deployment",
        resource_name=request.deployment_name,
        cluster_id=request.cluster_id,
        namespace=request.namespace,
        status="success" if success else "failed",
        details={
            "previous_replicas": prev,
            "new_replicas": new_r,
            "operation_id": result.get("operation_id"),
            "error": result.get("error"),
        },
    )

    if not success:
        raise HTTPException(status_code=400, detail=result.get("error", "Scale operation failed"))

    return result


@router.post(
    "/deployments/restart",
    summary="Restart deployment",
    description="Perform a rolling restart of a deployment",
)
async def restart_deployment(
    request: RestartDeploymentRequest,
    http_request: Request,
    user: UserContext = Depends(require_capability("aks_deployment_scale")),
    service: AKSOperationsService = Depends(_get_service),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Restart a deployment with rolling update."""
    result = await service.restart_deployment(
        cluster_id=request.cluster_id,
        namespace=request.namespace,
        deployment_name=request.deployment_name,
        user_id=user.user_id,
        user_email=user.email,
    )

    success = result.get("success", False)
    await _write_aks_audit_log(
        db,
        request=http_request,
        user=user,
        action="restart_deployment",
        resource_type="deployment",
        resource_name=request.deployment_name,
        cluster_id=request.cluster_id,
        namespace=request.namespace,
        status="success" if success else "failed",
        details={"error": result.get("error")},
    )

    if not success:
        raise HTTPException(status_code=400, detail=result.get("error", "Restart operation failed"))

    return result


@router.post(
    "/deployments/create",
    summary="Create deployment",
    description="Create a new Kubernetes deployment with audit logging",
)
async def create_deployment(
    request: CreateDeploymentRequest,
    http_request: Request = None,
    user: UserContext = Depends(require_role(UserRole.WRITE)),
    service: AKSOperationsService = Depends(_get_service),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Create a new deployment."""
    result = await service.create_deployment(
        cluster_id=request.cluster_id,
        namespace=request.namespace,
        name=request.name,
        image=request.image,
        replicas=request.replicas,
        labels=request.labels or None,
        cpu_request=request.cpu_request,
        cpu_limit=request.cpu_limit,
        memory_request=request.memory_request,
        memory_limit=request.memory_limit,
        port=request.port,
        env_vars=request.env_vars or None,
        user_id=user.user_id,
        user_email=user.email,
    )
    success = result.get("success", False)
    await _write_aks_audit_log(
        db,
        user=user,
        action="create_deployment",
        resource_type="deployment",
        resource_name=request.name,
        cluster_id=request.cluster_id,
        namespace=request.namespace,
        status="success" if success else "failed",
        details={"image": request.image, "replicas": request.replicas, "error": result.get("error")},
    )
    if not success:
        raise HTTPException(status_code=400, detail=result.get("error", "Create failed"))
    return result


@router.put(
    "/deployments/update",
    summary="Update deployment",
    description="Update an existing Kubernetes deployment with audit logging",
)
async def update_deployment(
    request: UpdateDeploymentRequest,
    http_request: Request = None,
    user: UserContext = Depends(require_role(UserRole.WRITE)),
    service: AKSOperationsService = Depends(_get_service),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Update an existing deployment."""
    result = await service.update_deployment(
        cluster_id=request.cluster_id,
        namespace=request.namespace,
        name=request.name,
        image=request.image,
        replicas=request.replicas,
        cpu_request=request.cpu_request,
        cpu_limit=request.cpu_limit,
        memory_request=request.memory_request,
        memory_limit=request.memory_limit,
        env_vars=request.env_vars,
        user_id=user.user_id,
        user_email=user.email,
    )
    success = result.get("success", False)
    await _write_aks_audit_log(
        db,
        user=user,
        action="update_deployment",
        resource_type="deployment",
        resource_name=request.name,
        cluster_id=request.cluster_id,
        namespace=request.namespace,
        status="success" if success else "failed",
        details={"image": request.image, "replicas": request.replicas, "error": result.get("error")},
    )
    if not success:
        raise HTTPException(status_code=400, detail=result.get("error", "Update failed"))
    return result


@router.delete(
    "/deployments/delete",
    summary="Delete deployment",
    description="Delete a Kubernetes deployment with audit logging",
)
async def delete_deployment(
    cluster_id: str = Query(..., description="Full Azure resource ID of the AKS cluster"),
    namespace: str = Query(..., description="Kubernetes namespace"),
    name: str = Query(..., description="Deployment name"),
    http_request: Request = None,
    user: UserContext = Depends(require_capability("aks_deployment_scale")),
    service: AKSOperationsService = Depends(_get_service),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Delete a deployment."""
    result = await service.delete_deployment(
        cluster_id=cluster_id,
        namespace=namespace,
        name=name,
        user_id=user.user_id,
        user_email=user.email,
    )
    success = result.get("success", False)
    await _write_aks_audit_log(
        db,
        user=user,
        action="delete_deployment",
        resource_type="deployment",
        resource_name=name,
        cluster_id=cluster_id,
        namespace=namespace,
        status="success" if success else "failed",
        details={"error": result.get("error")},
    )
    if not success:
        raise HTTPException(status_code=400, detail=result.get("error", "Delete failed"))
    return result


# ── Pod Observability ──────────────────────────────────────────────────


@router.get(
    "/pods/metrics",
    summary="Get pod metrics",
    description="Get real-time CPU and memory metrics for pods. Pass refresh=true to bypass cache.",
)
async def get_pod_metrics(
    cluster_id: str = Query(..., description="Full Azure resource ID of the AKS cluster"),
    namespace: str = Query(default=None, description="Filter by namespace"),
    refresh: bool = Query(default=False, description="Bypass cache and fetch fresh data"),
    user: UserContext = Depends(
        require_capability("aks_pod_view", permission_type="view", fallback_role=UserRole.READ)
    ),
    service: AKSOperationsService = Depends(_get_service),
) -> dict:
    """Get pod CPU/memory metrics."""
    try:
        metrics = await service.get_pod_metrics(cluster_id, namespace, bypass_cache=refresh)
        return {
            "pods": metrics,
            "count": len(metrics),
        }
    except Exception as e:
        logger.error("get_pod_metrics_failed", cluster_id=cluster_id, error=str(e))
        raise HTTPException(status_code=502, detail=f"Failed to connect to cluster: {str(e)}") from e


@router.delete(
    "/pods/{namespace}/{pod_name}",
    summary="Delete pod",
    description=(
        "Delete a Kubernetes pod. Requires the aks_pod_delete capability. "
        "Pods owned by a controller (Deployment, Job, StatefulSet) will be "
        "recreated by Kubernetes."
    ),
)
async def delete_pod(
    namespace: str,
    pod_name: str,
    cluster_id: str = Query(..., description="Full Azure resource ID of the AKS cluster"),
    grace_period_seconds: int | None = Query(
        default=None,
        ge=0,
        description="Override the pod's termination grace period (0 forces immediate deletion)",
    ),
    http_request: Request = None,
    user: UserContext = Depends(require_capability("aks_pod_delete")),
    service: AKSOperationsService = Depends(_get_service),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Delete a pod, translating Kubernetes failures into precise HTTP statuses.

    Authorization is enforced here by ``require_capability`` and does not rely
    on the caller having been offered the action in the UI.
    """
    try:
        result = await service.delete_pod(
            cluster_id=cluster_id,
            namespace=namespace,
            pod_name=pod_name,
            grace_period_seconds=grace_period_seconds,
        )
    except ApiException as exc:
        # Map the Kubernetes API status onto a meaningful HTTP response rather
        # than collapsing every failure into a 400/502.
        status_map = {
            404: (404, f"Pod '{pod_name}' was not found in namespace '{namespace}'."),
            403: (403, "The portal's cluster credentials are not permitted to delete this pod."),
            409: (409, f"Pod '{pod_name}' is being modified by another operation. Try again."),
        }
        code, detail = status_map.get(exc.status, (502, "Unable to delete pod. Kubernetes API returned an error."))
        await _write_aks_audit_log(
            db,
            request=http_request,
            user=user,
            action="delete_pod",
            resource_type="pod",
            resource_name=pod_name,
            cluster_id=cluster_id,
            namespace=namespace,
            status="failed",
            details={"error": detail, "k8s_status": exc.status},
        )
        logger.error(
            "delete_pod_api_error",
            cluster_id=cluster_id,
            namespace=namespace,
            pod=pod_name,
            k8s_status=exc.status,
            error=str(exc),
        )
        raise HTTPException(status_code=code, detail=detail) from exc
    except TimeoutError as exc:
        await _write_aks_audit_log(
            db,
            request=http_request,
            user=user,
            action="delete_pod",
            resource_type="pod",
            resource_name=pod_name,
            cluster_id=cluster_id,
            namespace=namespace,
            status="failed",
            details={"error": "timeout"},
        )
        raise HTTPException(
            status_code=504,
            detail="The cluster did not respond in time. The pod may still have been deleted.",
        ) from exc
    except Exception as exc:
        # Cluster unreachable, Azure credential failure, kubeconfig retrieval
        # failure — all surface as an upstream error with no internal detail.
        await _write_aks_audit_log(
            db,
            request=http_request,
            user=user,
            action="delete_pod",
            resource_type="pod",
            resource_name=pod_name,
            cluster_id=cluster_id,
            namespace=namespace,
            status="failed",
            details={"error": "cluster_unavailable"},
        )
        logger.error(
            "delete_pod_failed",
            cluster_id=cluster_id,
            namespace=namespace,
            pod=pod_name,
            error=str(exc),
            error_type=type(exc).__name__,
        )
        raise HTTPException(
            status_code=502,
            detail="Unable to reach the cluster to delete the pod.",
        ) from exc

    await _write_aks_audit_log(
        db,
        request=http_request,
        user=user,
        action="delete_pod",
        resource_type="pod",
        resource_name=pod_name,
        cluster_id=cluster_id,
        namespace=namespace,
        status="success",
        details={
            "phase": result.get("phase"),
            "owner": result.get("owner"),
            "grace_period_seconds": grace_period_seconds,
        },
    )
    return result


@router.get(
    "/pods/utilization/history",
    summary="Get pod utilization history",
    description="Get historical CPU and memory utilization for pods",
)
async def get_pod_utilization_history(
    cluster_id: str = Query(..., description="Full Azure resource ID of the AKS cluster"),
    namespace: str = Query(default=None, description="Filter by namespace"),
    days: int = Query(default=7, ge=1, le=90, description="Number of days of history"),
    user: UserContext = Depends(get_current_user),
    service: AKSOperationsService = Depends(_get_service),
) -> dict:
    """Get historical pod utilization data."""
    try:
        history = await service.get_pod_utilization_history(
            cluster_id=cluster_id,
            namespace=namespace or "",
            hours=days * 24,
        )
        return {
            "history": history,
            "count": len(history),
            "days": days,
        }
    except Exception as e:
        logger.error("get_pod_utilization_history_failed", cluster_id=cluster_id, error=str(e))
        raise HTTPException(status_code=502, detail=f"Failed to fetch utilization history: {str(e)}") from e


@router.get(
    "/pods/underutilized",
    summary="Identify underutilized workloads",
    description="Find pods with consistently low resource utilization",
)
async def get_underutilized_workloads(
    cluster_id: str = Query(..., description="Full Azure resource ID of the AKS cluster"),
    namespace: str = Query(default=None, description="Filter by namespace"),
    cpu_threshold: int = Query(default=20, ge=1, le=100, description="CPU utilization threshold %"),
    memory_threshold: int = Query(default=30, ge=1, le=100, description="Memory utilization threshold %"),
    user: UserContext = Depends(get_current_user),
    service: AKSOperationsService = Depends(_get_service),
) -> dict:
    """Identify underutilized workloads for optimization."""
    workloads = await service.identify_underutilized_workloads(
        cluster_id=cluster_id,
        cpu_threshold_pct=cpu_threshold,
        memory_threshold_pct=memory_threshold,
    )
    return {
        "underutilized_workloads": workloads,
        "count": len(workloads),
        "thresholds": {
            "cpu": cpu_threshold,
            "memory": memory_threshold,
        },
    }


# ── Pod Logs, Exec & Details ───────────────────────────────────────────


@router.get(
    "/pods/{namespace}/{pod_name}/logs",
    summary="Get pod logs",
    description="Fetch logs from a pod container with tail lines and time filtering.",
)
async def get_pod_logs(
    namespace: str = Path(..., description="Pod namespace"),
    pod_name: str = Path(..., description="Pod name"),
    cluster_id: str = Query(..., description="Full Azure resource ID of the AKS cluster"),
    container: str | None = Query(default=None, description="Container name (uses first container if omitted)"),
    tail_lines: int = Query(default=500, ge=10, le=10000, description="Number of lines to tail"),
    since_seconds: int | None = Query(
        default=None,
        ge=60,
        le=86400,
        description="Only return logs newer than this many seconds",
    ),
    user: UserContext = Depends(
        require_capability("aks_pod_view", permission_type="view", fallback_role=UserRole.READ)
    ),
    service: AKSOperationsService = Depends(_get_service),
) -> dict:
    """Get pod logs."""
    try:
        return await service.get_pod_logs(
            cluster_id,
            namespace,
            pod_name,
            container=container,
            tail_lines=tail_lines,
            since_seconds=since_seconds,
        )
    except Exception as e:
        logger.error(
            "get_pod_logs_failed",
            pod=pod_name,
            namespace=namespace,
            container=container,
            error=str(e),
        )
        detail = f"Failed to fetch pod logs for {namespace}/{pod_name}"
        if "Forbidden" in str(e):
            detail += ": insufficient permissions to read pod logs"
        elif "not found" in str(e).lower():
            detail += ": pod or container not found"
        else:
            detail += f": {str(e)}"
        raise HTTPException(status_code=502, detail=detail) from e


@router.get(
    "/pods/{namespace}/{pod_name}/logs/search",
    summary="Search pod logs for errors/patterns",
    description="Search pod logs for error patterns and return matching lines with severity classification.",
)
async def search_pod_logs(
    namespace: str = Path(..., description="Pod namespace"),
    pod_name: str = Path(..., description="Pod name"),
    cluster_id: str = Query(..., description="Full Azure resource ID of the AKS cluster"),
    pattern: str = Query(
        default="error|exception|fail|panic|crash|oom|kill",
        description="Regex pattern to search for",
    ),
    container: str | None = Query(default=None, description="Container name"),
    tail_lines: int = Query(
        default=2000,
        ge=100,
        le=10000,
        description="Number of log lines to search through",
    ),
    user: UserContext = Depends(get_current_user),
    service: AKSOperationsService = Depends(_get_service),
) -> dict:
    """Search pod logs for error patterns."""
    try:
        return await service.search_pod_logs(
            cluster_id,
            namespace,
            pod_name,
            pattern=pattern,
            container=container,
            tail_lines=tail_lines,
        )
    except Exception as e:
        logger.error("search_pod_logs_failed", pod=pod_name, error=str(e))
        raise HTTPException(status_code=502, detail=f"Failed to search pod logs: {str(e)}") from e


class PodExecRequest(BaseModel):
    """Request to execute a command in a pod."""

    cluster_id: str = Field(..., description="Full Azure resource ID of the AKS cluster")
    command: str = Field(..., description="Command to execute (e.g. 'ls -la /app')")
    container: str | None = Field(default=None, description="Container name (uses first container if omitted)")


@router.post(
    "/pods/{namespace}/{pod_name}/exec",
    summary="Execute command in a pod",
    description="Run a command inside a pod container and return the output.",
)
async def exec_pod_command(
    namespace: str = Path(..., description="Pod namespace"),
    pod_name: str = Path(..., description="Pod name"),
    body: PodExecRequest = Body(...),
    http_request: Request = None,
    # Executing arbitrary commands inside a running container is a privileged
    # operation — it previously required only an authenticated user, meaning any
    # read-only account could run commands in production pods, unaudited.
    user: UserContext = Depends(require_capability("aks_pod_exec")),
    service: AKSOperationsService = Depends(_get_service),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Execute a command in a pod.

    Every outcome is audited — including rejected and failed attempts. An
    in-pod exec is the most sensitive operation the portal exposes, and a
    blocked attempt is precisely the event an auditor needs to see.
    """

    async def _audit(status: str, details: dict) -> None:
        await _write_aks_audit_log(
            db,
            request=http_request,
            user=user,
            action="exec_pod_command",
            resource_type="pod",
            resource_name=pod_name,
            cluster_id=body.cluster_id,
            namespace=namespace,
            status=status,
            details={"command": body.command, "container": body.container, **details},
        )

    import shlex

    try:
        cmd_list = shlex.split(body.command)
    except ValueError as e:
        await _audit("failed", {"error": "unparseable_command"})
        raise HTTPException(status_code=400, detail="Command could not be parsed.") from e

    if not cmd_list:
        await _audit("failed", {"error": "empty_command"})
        raise HTTPException(status_code=400, detail="Command cannot be empty")

    # Security: block obviously destructive commands.
    dangerous = {"rm -rf /", "mkfs", "dd if=", ":(){", "fork bomb"}
    cmd_lower = body.command.lower()
    if any(d in cmd_lower for d in dangerous):
        await _audit("blocked", {"error": "blocked_by_safety_list"})
        logger.warning(
            "exec_pod_command_blocked",
            pod=pod_name,
            namespace=namespace,
            user_id=user.user_id,
        )
        raise HTTPException(status_code=403, detail="Command blocked for safety")

    try:
        result = await service.exec_pod_command(
            body.cluster_id,
            namespace,
            pod_name,
            command=cmd_list,
            container=body.container,
        )
    except Exception as e:
        await _audit("failed", {"error": "exec_failed"})
        logger.error("exec_pod_command_failed", pod=pod_name, error=str(e))
        raise HTTPException(status_code=502, detail="Failed to execute command in pod.") from e

    await _audit("success" if result.get("success", True) else "failed", {})
    return result


@router.get(
    "/pods/{namespace}/{pod_name}/containers",
    summary="List pod containers",
    description="Get list of containers in a pod with their status.",
)
async def get_pod_containers(
    namespace: str = Path(..., description="Pod namespace"),
    pod_name: str = Path(..., description="Pod name"),
    cluster_id: str = Query(..., description="Full Azure resource ID of the AKS cluster"),
    user: UserContext = Depends(
        require_capability("aks_pod_view", permission_type="view", fallback_role=UserRole.READ)
    ),
    service: AKSOperationsService = Depends(_get_service),
) -> dict:
    """Get pod container list."""
    try:
        containers = await service.get_pod_containers(
            cluster_id,
            namespace,
            pod_name,
        )
        return {"containers": containers, "count": len(containers)}
    except Exception as e:
        logger.error("get_pod_containers_failed", pod=pod_name, error=str(e))
        raise HTTPException(status_code=502, detail=f"Failed to fetch containers: {str(e)}") from e


# ── CronJob Management ─────────────────────────────────────────────────


@router.get(
    "/cronjobs/cached",
    summary="List CronJobs from DB cache (fast)",
    description="Get CronJobs from database inventory. If DB is empty, falls back to live Kubernetes API.",
)
async def list_cached_cronjobs(
    cluster_id: str = Query(..., description="Full Azure resource ID of the AKS cluster"),
    namespace: str = Query(default=None, description="Filter by namespace"),
    user: UserContext = Depends(
        require_capability("aks_cronjob_view", permission_type="view", fallback_role=UserRole.READ)
    ),
    service: AKSOperationsService = Depends(_get_service),
) -> dict:
    """Get CronJobs from DB cache — fast, no Kubernetes API call."""
    try:
        cronjobs = await service.get_cronjobs_from_db(cluster_id, namespace)
        last_sync = await service.get_cronjobs_last_sync_time(cluster_id)
        return {
            "source": "db",
            "last_sync": last_sync,
            "cronjobs": cronjobs,
            "count": len(cronjobs),
        }
    except Exception as e:
        logger.warning("cached_cronjobs_db_failed", cluster_id=cluster_id, error=str(e))
        return {
            "source": "db",
            "last_sync": None,
            "cronjobs": [],
            "count": 0,
        }


@router.post(
    "/cronjobs/sync",
    summary="Sync CronJobs from Kubernetes to DB",
    description="Fetch CronJobs from live Kubernetes API and save to database for fast cached access.",
)
async def sync_cronjobs_to_db(
    cluster_id: str = Query(..., description="Full Azure resource ID of the AKS cluster"),
    namespace: str = Query(default=None, description="Filter by namespace"),
    user: UserContext = Depends(get_current_user),
    service: AKSOperationsService = Depends(_get_service),
) -> dict:
    """Sync CronJobs from Kubernetes to database."""
    return await service.sync_cronjobs_to_db(cluster_id, namespace)


@router.get(
    "/cronjobs",
    summary="List CronJobs",
    description="List all CronJobs in a cluster or namespace. Pass refresh=true to bypass cache.",
)
async def list_cronjobs(
    cluster_id: str = Query(..., description="Full Azure resource ID of the AKS cluster"),
    namespace: str = Query(default=None, description="Filter by namespace"),
    refresh: bool = Query(default=False, description="Bypass cache and fetch fresh data"),
    user: UserContext = Depends(
        require_capability("aks_cronjob_view", permission_type="view", fallback_role=UserRole.READ)
    ),
    service: AKSOperationsService = Depends(_get_service),
) -> dict:
    """List Kubernetes CronJobs."""
    try:
        cronjobs = await service.list_cronjobs(cluster_id, namespace, bypass_cache=refresh)
        return {
            "cronjobs": cronjobs,
            "count": len(cronjobs),
        }
    except Exception as e:
        logger.error("list_cronjobs_failed", cluster_id=cluster_id, error=str(e))
        raise HTTPException(status_code=502, detail=f"Failed to connect to cluster: {str(e)}") from e


@router.post(
    "/cronjobs/suspend",
    summary="Suspend or resume CronJob",
    description="Suspend or resume a CronJob with audit logging",
)
async def suspend_cronjob(
    request: SuspendCronJobRequest,
    http_request: Request,
    user: UserContext = Depends(require_role(UserRole.WRITE)),
    service: AKSOperationsService = Depends(_get_service),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Suspend or resume a CronJob."""
    result = await service.suspend_cronjob(
        cluster_id=request.cluster_id,
        namespace=request.namespace,
        cronjob_name=request.cronjob_name,
        suspend=request.suspend,
        user_id=user.user_id,
        user_email=user.email,
    )

    success = result.get("success", False)
    action = "suspend_cronjob" if request.suspend else "resume_cronjob"
    await _write_aks_audit_log(
        db,
        request=http_request,
        user=user,
        action=action,
        resource_type="cronjob",
        resource_name=request.cronjob_name,
        cluster_id=request.cluster_id,
        namespace=request.namespace,
        status="success" if success else "failed",
        details={"suspend": request.suspend, "error": result.get("error")},
    )

    if not success:
        raise HTTPException(status_code=400, detail=result.get("error", "Operation failed"))

    return result


@router.post(
    "/cronjobs",
    summary="Create CronJob",
    description="Create a new CronJob with audit logging",
)
async def create_cronjob(
    request: CreateCronJobRequest,
    http_request: Request,
    user: UserContext = Depends(require_role(UserRole.WRITE)),
    service: AKSOperationsService = Depends(_get_service),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Create a new CronJob."""
    result = await service.create_cronjob(
        cluster_id=request.cluster_id,
        namespace=request.namespace,
        name=request.name,
        schedule=request.schedule,
        image=request.image,
        command=request.command,
        args=request.args,
        restart_policy=request.restart_policy,
        labels=request.labels or None,
        cpu_request=request.cpu_request,
        cpu_limit=request.cpu_limit,
        memory_request=request.memory_request,
        memory_limit=request.memory_limit,
        concurrency_policy=request.concurrency_policy,
        successful_jobs_history_limit=request.successful_jobs_history_limit,
        failed_jobs_history_limit=request.failed_jobs_history_limit,
        backoff_limit=request.backoff_limit,
        active_deadline_seconds=request.active_deadline_seconds,
        ttl_seconds_after_finished=request.ttl_seconds_after_finished,
        service_account_name=request.service_account_name,
        user_id=user.user_id,
        user_email=user.email,
    )

    success = result.get("success", False)
    await _write_aks_audit_log(
        db,
        request=http_request,
        user=user,
        action="create_cronjob",
        resource_type="cronjob",
        resource_name=request.name,
        cluster_id=request.cluster_id,
        namespace=request.namespace,
        status="success" if success else "failed",
        details={
            "schedule": request.schedule,
            "image": request.image,
            "error": result.get("error"),
        },
    )

    if not success:
        raise HTTPException(status_code=400, detail=result.get("error", "Create failed"))

    return result


@router.get(
    "/cronjobs/details",
    summary="Get CronJob details",
    description="Get detailed information about a specific CronJob. Pass refresh=true to bypass cache.",
)
async def get_cronjob_detail(
    cluster_id: str = Query(..., description="Full Azure resource ID of the AKS cluster"),
    namespace: str = Query(..., description="Kubernetes namespace"),
    name: str = Query(..., description="CronJob name"),
    refresh: bool = Query(default=False, description="Bypass cache and fetch fresh data"),
    user: UserContext = Depends(get_current_user),
    service: AKSOperationsService = Depends(_get_service),
) -> dict:
    """Get detailed CronJob information."""
    try:
        return await service.get_cronjob_detail(cluster_id, namespace, name, bypass_cache=refresh)
    except Exception as e:
        logger.error("get_cronjob_detail_failed", name=name, error=str(e))
        raise HTTPException(status_code=502, detail=f"Failed to fetch cronjob detail: {str(e)}") from e


@router.put(
    "/cronjobs/update",
    summary="Update CronJob",
    description="Update an existing CronJob with audit logging",
)
async def update_cronjob(
    request: UpdateCronJobRequest,
    http_request: Request,
    user: UserContext = Depends(require_role(UserRole.WRITE)),
    service: AKSOperationsService = Depends(_get_service),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Update an existing CronJob."""
    result = await service.update_cronjob(
        cluster_id=request.cluster_id,
        namespace=request.namespace,
        name=request.name,
        schedule=request.schedule,
        image=request.image,
        command=request.command,
        args=request.args,
        suspended=request.suspended,
        user_id=user.user_id,
        user_email=user.email,
    )
    success = result.get("success", False)
    await _write_aks_audit_log(
        db,
        request=http_request,
        user=user,
        action="update_cronjob",
        resource_type="cronjob",
        resource_name=request.name,
        cluster_id=request.cluster_id,
        namespace=request.namespace,
        status="success" if success else "failed",
        details={
            "schedule": request.schedule,
            "image": request.image,
            "suspended": request.suspended,
            "error": result.get("error"),
        },
    )
    if not success:
        raise HTTPException(status_code=400, detail=result.get("error", "Update failed"))
    return result


@router.delete(
    "/cronjobs/delete",
    summary="Delete CronJob",
    description="Delete a CronJob with audit logging",
)
async def delete_cronjob(
    cluster_id: str = Query(..., description="Full Azure resource ID of the AKS cluster"),
    namespace: str = Query(..., description="Kubernetes namespace"),
    name: str = Query(..., description="CronJob name"),
    http_request: Request = None,
    user: UserContext = Depends(require_role(UserRole.WRITE)),
    service: AKSOperationsService = Depends(_get_service),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Delete a CronJob."""
    result = await service.delete_cronjob(
        cluster_id=cluster_id,
        namespace=namespace,
        name=name,
        user_id=user.user_id,
        user_email=user.email,
    )
    success = result.get("success", False)
    await _write_aks_audit_log(
        db,
        request=http_request,
        user=user,
        action="delete_cronjob",
        resource_type="cronjob",
        resource_name=name,
        cluster_id=cluster_id,
        namespace=namespace,
        status="success" if success else "failed",
        details={"error": result.get("error")},
    )
    if not success:
        raise HTTPException(status_code=400, detail=result.get("error", "Delete failed"))
    return result


@router.post(
    "/cronjobs/trigger",
    summary="Trigger CronJob",
    description="Manually trigger a CronJob by creating a Job from its template",
)
async def trigger_cronjob(
    request: TriggerCronJobRequest,
    http_request: Request,
    user: UserContext = Depends(require_capability("aks_cronjob_trigger")),
    service: AKSOperationsService = Depends(_get_service),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Manually trigger a CronJob.

    The response carries the created Job's name and namespace so the UI can
    offer a "View Job" action that deep-links into the Jobs tab.
    """
    result = await service.trigger_cronjob(
        cluster_id=request.cluster_id,
        namespace=request.namespace,
        cronjob_name=request.cronjob_name,
        user_id=user.user_id,
        user_email=user.email,
    )
    success = result.get("success", False)
    await _write_aks_audit_log(
        db,
        request=http_request,
        user=user,
        action="trigger_cronjob",
        resource_type="cronjob",
        resource_name=request.cronjob_name,
        cluster_id=request.cluster_id,
        namespace=request.namespace,
        status="success" if success else "failed",
        details={
            "job_name": result.get("job_name"),
            # Records that a repeated click reused an existing Job rather than
            # launching the workload twice.
            "deduplicated": result.get("deduplicated", False),
            "error": result.get("error"),
        },
    )
    if not success:
        raise HTTPException(status_code=400, detail=result.get("error", "Trigger failed"))
    return result


# ── ConfigMaps ─────────────────────────────────────────────────────────


# ── Jobs ───────────────────────────────────────────────────────────────


def _job_api_error(exc: ApiException, *, job_name: str, namespace: str) -> HTTPException:
    """Translate a Kubernetes error on a Job into a precise HTTP response."""
    status_map = {
        404: (404, f"Job '{job_name}' was not found in namespace '{namespace}'."),
        403: (403, "The portal's cluster credentials are not permitted to act on this Job."),
        409: (409, f"Job '{job_name}' is being modified by another operation. Try again."),
    }
    code, detail = status_map.get(exc.status, (502, "Unable to complete the operation. Kubernetes returned an error."))
    return HTTPException(status_code=code, detail=detail)


@router.get(
    "/jobs",
    summary="List Kubernetes Jobs",
    description="List Jobs across a cluster or a single namespace. Pass refresh=true to bypass cache.",
)
async def list_jobs(
    cluster_id: str = Query(..., description="Full Azure resource ID of the AKS cluster"),
    namespace: str = Query(default=None, description="Filter by namespace"),
    refresh: bool = Query(default=False, description="Bypass cache and fetch fresh data"),
    user: UserContext = Depends(
        require_capability("aks_job_view", permission_type="view", fallback_role=UserRole.READ)
    ),
    service: AKSOperationsService = Depends(_get_service),
) -> dict:
    """List Jobs for the Jobs tab."""
    try:
        jobs = await service.get_jobs(cluster_id, namespace, bypass_cache=refresh)
        return {"jobs": jobs, "count": len(jobs)}
    except ApiException as e:
        logger.error("list_jobs_failed", cluster_id=cluster_id, k8s_status=e.status, error=str(e))
        raise HTTPException(
            status_code=502,
            detail="Unable to list Jobs. Kubernetes API returned an error.",
        ) from e
    except Exception as e:
        logger.error("list_jobs_failed", cluster_id=cluster_id, error=str(e))
        raise HTTPException(status_code=502, detail="Failed to connect to cluster.") from e


@router.get(
    "/jobs/detail",
    summary="Get Job detail",
    description="Full detail for a single Job, including its execution counters and pods.",
)
async def get_job_detail(
    cluster_id: str = Query(..., description="Full Azure resource ID of the AKS cluster"),
    namespace: str = Query(..., description="Kubernetes namespace"),
    name: str = Query(..., description="Job name"),
    user: UserContext = Depends(
        require_capability("aks_job_view", permission_type="view", fallback_role=UserRole.READ)
    ),
    service: AKSOperationsService = Depends(_get_service),
) -> dict:
    """Get one Job's full detail."""
    try:
        return await service.get_job_detail(cluster_id, namespace, name)
    except ApiException as e:
        raise _job_api_error(e, job_name=name, namespace=namespace) from e
    except Exception as e:
        logger.error("get_job_detail_failed", job=name, namespace=namespace, error=str(e))
        raise HTTPException(status_code=502, detail="Failed to connect to cluster.") from e


@router.get(
    "/jobs/{namespace}/{job_name}/pods",
    summary="List pods for a Job",
    description="Pods created by a Job, for log access and per-pod actions.",
)
async def get_job_pods(
    namespace: str = Path(..., description="Job namespace"),
    job_name: str = Path(..., description="Job name"),
    cluster_id: str = Query(..., description="Full Azure resource ID of the AKS cluster"),
    user: UserContext = Depends(
        require_capability("aks_job_view", permission_type="view", fallback_role=UserRole.READ)
    ),
    service: AKSOperationsService = Depends(_get_service),
) -> dict:
    """List a Job's pods."""
    try:
        pods = await service.get_job_pods(cluster_id, namespace, job_name)
        return {"pods": pods, "count": len(pods)}
    except ApiException as e:
        raise _job_api_error(e, job_name=job_name, namespace=namespace) from e
    except Exception as e:
        logger.error("get_job_pods_failed", job=job_name, namespace=namespace, error=str(e))
        raise HTTPException(status_code=502, detail="Failed to connect to cluster.") from e


@router.delete(
    "/jobs/{namespace}/{job_name}",
    summary="Delete a Job",
    description=(
        "Delete a Kubernetes Job. Requires the aks_job_delete capability. "
        "The default Background propagation policy also deletes the Job's pods; "
        "pass propagation_policy=Orphan to retain them."
    ),
)
async def delete_job(
    namespace: str = Path(..., description="Job namespace"),
    job_name: str = Path(..., description="Job name"),
    cluster_id: str = Query(..., description="Full Azure resource ID of the AKS cluster"),
    propagation_policy: str = Query(
        default="Background",
        pattern="^(Background|Foreground|Orphan)$",
        description="Kubernetes deletion propagation policy",
    ),
    http_request: Request = None,
    user: UserContext = Depends(require_capability("aks_job_delete")),
    service: AKSOperationsService = Depends(_get_service),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Delete a Job, auditing the outcome either way."""

    async def _audit(status: str, details: dict) -> None:
        await _write_aks_audit_log(
            db,
            request=http_request,
            user=user,
            action="delete_job",
            resource_type="job",
            resource_name=job_name,
            cluster_id=cluster_id,
            namespace=namespace,
            status=status,
            details=details,
        )

    try:
        result = await service.delete_job(
            cluster_id=cluster_id,
            namespace=namespace,
            job_name=job_name,
            propagation_policy=propagation_policy,
        )
    except ApiException as e:
        http_exc = _job_api_error(e, job_name=job_name, namespace=namespace)
        await _audit("failed", {"error": http_exc.detail, "k8s_status": e.status})
        logger.error("delete_job_api_error", job=job_name, namespace=namespace, k8s_status=e.status)
        raise http_exc from e
    except TimeoutError as e:
        await _audit("failed", {"error": "timeout"})
        raise HTTPException(
            status_code=504,
            detail="The cluster did not respond in time. The Job may still have been deleted.",
        ) from e
    except Exception as e:
        await _audit("failed", {"error": "cluster_unavailable"})
        logger.error(
            "delete_job_failed",
            job=job_name,
            namespace=namespace,
            error=str(e),
            error_type=type(e).__name__,
        )
        raise HTTPException(status_code=502, detail="Unable to reach the cluster to delete the Job.") from e

    await _audit(
        "success",
        {
            "previous_status": result.get("previous_status"),
            "propagation_policy": propagation_policy,
        },
    )
    return result


@router.get(
    "/configmaps",
    summary="List ConfigMaps",
    description="List ConfigMaps in a namespace",
)
async def list_configmaps(
    cluster_id: str = Query(..., description="Full Azure resource ID of the AKS cluster"),
    namespace: str = Query(..., description="Kubernetes namespace"),
    user: UserContext = Depends(get_current_user),
    service: AKSOperationsService = Depends(_get_service),
) -> dict:
    """List ConfigMaps in a namespace."""
    try:
        configmaps = await service.list_configmaps(cluster_id, namespace)
        return {"configmaps": configmaps, "count": len(configmaps)}
    except Exception as e:
        logger.error("list_configmaps_failed", namespace=namespace, error=str(e))
        raise HTTPException(status_code=502, detail=f"Failed to list configmaps: {str(e)}") from e


@router.get(
    "/configmaps/detail",
    summary="Get ConfigMap detail",
    description="Get detailed ConfigMap content including data",
)
async def get_configmap_detail(
    cluster_id: str = Query(..., description="Full Azure resource ID of the AKS cluster"),
    namespace: str = Query(..., description="Kubernetes namespace"),
    name: str = Query(..., description="ConfigMap name"),
    user: UserContext = Depends(get_current_user),
    service: AKSOperationsService = Depends(_get_service),
) -> dict:
    """Get ConfigMap detail with data content."""
    try:
        return await service.get_configmap_detail(cluster_id, namespace, name)
    except Exception as e:
        logger.error("get_configmap_detail_failed", name=name, namespace=namespace, error=str(e))
        raise HTTPException(status_code=502, detail=f"Failed to fetch configmap detail: {str(e)}") from e


# ── Scale History ──────────────────────────────────────────────────────


@router.get(
    "/scale-history",
    summary="Get scaling history",
    description="Get deployment scaling audit history",
)
async def get_scale_history(
    cluster_id: str | None = Query(default=None, description="Filter by cluster ID"),
    namespace: str | None = Query(default=None, description="Filter by namespace"),
    deployment_name: str | None = Query(default=None, description="Filter by deployment"),
    days: int = Query(default=30, ge=1, le=365, description="Number of days of history"),
    limit: int = Query(default=100, ge=1, le=1000, description="Maximum records to return"),
    user: UserContext = Depends(get_current_user),
    service: AKSOperationsService = Depends(_get_service),
) -> dict:
    """Get deployment scaling history for audit."""
    history = await service.get_scale_history(
        cluster_id=cluster_id,
        namespace=namespace,
        deployment_name=deployment_name,
        days=days,
        limit=limit,
    )
    return {
        "history": history,
        "count": len(history),
    }


# ── Node Pool Operations ──────────────────────────────────────────────


@router.get(
    "/nodepools",
    summary="List node pools",
    description="List all node pools for a specific AKS cluster. Pass refresh=true to bypass cache.",
)
async def list_node_pools(
    cluster_id: str = Query(..., description="Full Azure resource ID of the AKS cluster"),
    refresh: bool = Query(default=False, description="Bypass cache and fetch fresh data"),
    user: UserContext = Depends(get_current_user),
    service: AKSOperationsService = Depends(_get_service),
) -> dict:
    """Get node pools for a cluster."""
    try:
        node_pools = await service.get_node_pools(cluster_id, bypass_cache=refresh)
        return {
            "node_pools": node_pools,
            "count": len(node_pools),
        }
    except Exception as e:
        logger.error("list_node_pools_failed", cluster_id=cluster_id, error=str(e))
        raise HTTPException(status_code=502, detail=f"Failed to fetch node pools: {str(e)}") from e


@router.get(
    "/nodepools/cached",
    summary="List Node Pools from DB cache (fast)",
    description="Get Node Pools from database inventory. If DB is empty, falls back to live Azure/K8s API.",
)
async def list_cached_node_pools(
    cluster_id: str = Query(..., description="Full Azure resource ID of the AKS cluster"),
    user: UserContext = Depends(get_current_user),
    service: AKSOperationsService = Depends(_get_service),
) -> dict:
    """Get Node Pools from DB cache — fast, no Azure/K8s API call."""
    try:
        node_pools = await service.get_node_pools_from_db(cluster_id)
        last_sync = await service.get_node_pools_last_sync_time(cluster_id)
        return {
            "source": "db",
            "last_sync": last_sync,
            "node_pools": node_pools,
            "count": len(node_pools),
        }
    except Exception as e:
        logger.warning("cached_node_pools_db_failed", cluster_id=cluster_id, error=str(e))
        return {
            "source": "db",
            "last_sync": None,
            "node_pools": [],
            "count": 0,
        }


@router.post(
    "/nodepools/sync",
    summary="Sync Node Pools from Azure/K8s to DB",
    description="Fetch Node Pools from live Azure/K8s API and save to database for fast cached access.",
)
async def sync_node_pools_to_db(
    cluster_id: str = Query(..., description="Full Azure resource ID of the AKS cluster"),
    user: UserContext = Depends(get_current_user),
    service: AKSOperationsService = Depends(_get_service),
) -> dict:
    """Sync Node Pools from Azure/K8s to database."""
    return await service.sync_node_pools_to_db(cluster_id)


@router.post(
    "/nodepools/scale",
    summary="Scale node pool",
    description="Scale a node pool to the specified node count",
)
async def scale_node_pool(
    request: ScaleNodePoolRequest,
    user: UserContext = Depends(require_role(UserRole.WRITE)),
    service: AKSOperationsService = Depends(_get_service),
) -> dict:
    """Scale a node pool."""
    result = await service.scale_node_pool(
        cluster_id=request.cluster_id,
        nodepool_name=request.nodepool_name,
        node_count=request.node_count,
    )
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error", "Scale failed"))
    return result


@router.post(
    "/nodepools/autoscaling",
    summary="Update node pool autoscaling",
    description="Enable/disable or configure autoscaling for a node pool",
)
async def update_node_pool_autoscaling(
    request: UpdateAutoscalingRequest,
    user: UserContext = Depends(require_role(UserRole.WRITE)),
    service: AKSOperationsService = Depends(_get_service),
) -> dict:
    """Update autoscaling configuration."""
    result = await service.update_node_pool_autoscaling(
        cluster_id=request.cluster_id,
        nodepool_name=request.nodepool_name,
        enable_auto_scaling=request.enable_auto_scaling,
        min_count=request.min_count,
        max_count=request.max_count,
    )
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error", "Update failed"))
    return result


# ── Cluster Start / Stop ──────────────────────────────────────────────


@router.post(
    "/clusters/start",
    summary="Start cluster",
    description="Start a stopped AKS cluster",
)
async def start_cluster(
    request: ClusterActionRequest,
    user: UserContext = Depends(require_role(UserRole.WRITE)),
    service: AKSOperationsService = Depends(_get_service),
) -> dict:
    """Start a stopped AKS cluster."""
    result = await service.start_cluster(request.cluster_id)
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error", "Start failed"))
    return result


@router.post(
    "/clusters/stop",
    summary="Stop cluster",
    description="Stop a running AKS cluster",
)
async def stop_cluster(
    request: ClusterActionRequest,
    user: UserContext = Depends(require_role(UserRole.WRITE)),
    service: AKSOperationsService = Depends(_get_service),
) -> dict:
    """Stop a running AKS cluster."""
    result = await service.stop_cluster(request.cluster_id)
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error", "Stop failed"))
    return result


# ── Cache Management ──────────────────────────────────────────────────


@router.get(
    "/cache/stats",
    summary="Cache statistics",
    description="Get cache hit/miss stats, Redis health, and TTL configuration",
)
async def get_cache_stats(
    user: UserContext = Depends(get_current_user),
) -> dict:
    """Return cache health and performance metrics."""
    return data_cache.get_stats()


@router.post(
    "/cache/invalidate",
    summary="Invalidate cache",
    description="Flush all cached data. Requires ADMIN role.",
)
async def invalidate_cache(
    user: UserContext = Depends(require_role(UserRole.ADMIN)),
) -> dict:
    """Flush entire AKS cache. Admin only."""
    await data_cache.invalidate_all()
    return {"success": True, "message": "All AKS cache entries invalidated"}


register_extended_routes(
    router,
    get_service=_get_service,
    write_audit=_write_aks_audit_log,
    serialize_audit=_serialize_aks_audit_entry,
)
