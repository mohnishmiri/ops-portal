"""StatefulSet / DaemonSet management and AKV → AKS (akv2k8s) secret sync status endpoints."""

import json
from collections.abc import Awaitable, Callable
from typing import Any, Literal

import structlog
from fastapi import Depends, HTTPException, Path, Query, Request
from kubernetes.client.rest import ApiException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.authz import require_capability
from app.core.database import get_db
from app.models.auth import UserContext, UserRole
from app.services.aks_akvs_operations import AKVS_KIND, summarize_akvs
from app.services.aks_workload_operations import KIND_LABEL

logger = structlog.get_logger(__name__)

K8S_NAME_PATTERN = r"^[a-z0-9]([-a-z0-9.]*[a-z0-9])?$"
WorkloadKind = Literal["statefulset", "daemonset"]
# Resource kinds mutated through _mutate (audit action is "<op>_<kind>").
MUTATION_LABEL: dict[str, str] = {**KIND_LABEL, "azurekeyvaultsecret": AKVS_KIND}


class WorkloadRef(BaseModel):
    cluster_id: str = Field(..., description="Full Azure resource ID of the AKS cluster")
    namespace: str = Field(..., max_length=63, pattern=K8S_NAME_PATTERN)
    name: str = Field(..., max_length=253, pattern=K8S_NAME_PATTERN)


class ScaleWorkloadRequest(WorkloadRef):
    replicas: int = Field(..., ge=0, le=100)


class UpdateImageRequest(WorkloadRef):
    container: str = Field(..., min_length=1, max_length=63)
    image: str = Field(..., min_length=1, max_length=512, pattern=r"^\S+$")


class UpdateStrategyRequest(WorkloadRef):
    strategy_type: Literal["RollingUpdate", "OnDelete"]
    partition: int | None = Field(default=None, ge=0, le=1000, description="StatefulSet only")
    max_unavailable: str | None = Field(default=None, pattern=r"^\d{1,3}%?$", description="DaemonSet only")
    max_surge: str | None = Field(default=None, pattern=r"^\d{1,3}%?$", description="DaemonSet only")


class RollbackWorkloadRequest(WorkloadRef):
    revision: int = Field(..., ge=1)


def _k8s_message(exc: ApiException) -> str | None:
    try:
        return str(json.loads(exc.body or "{}").get("message") or "")[:300] or None
    except (ValueError, AttributeError):
        return None


def _workload_api_error(exc: ApiException, *, label: str, name: str, namespace: str) -> HTTPException:
    if exc.status == 404:
        return HTTPException(status_code=404, detail=f"{label} '{name}' was not found in namespace '{namespace}'.")
    if exc.status == 403:
        return HTTPException(
            status_code=403, detail=f"The portal's cluster credentials are not permitted to act on this {label}."
        )
    if exc.status == 409:
        return HTTPException(status_code=409, detail=f"{label} '{name}' was modified concurrently. Try again.")
    if exc.status in (400, 422):
        return HTTPException(status_code=400, detail=_k8s_message(exc) or "Kubernetes rejected the request.")
    return HTTPException(status_code=502, detail="Unable to complete the operation. Kubernetes returned an error.")


def register_workload_routes(router, *, get_service, write_audit):
    """Register StatefulSet/DaemonSet and AKV sync routes on the AKS router."""

    view_workloads = require_capability("aks_workload_view", permission_type="view", fallback_role=UserRole.READ)
    view_akv_sync = require_capability("aks_akv_sync_view", permission_type="view", fallback_role=UserRole.READ)

    async def _mutate(
        *,
        op: str,
        kind: str,
        ref: WorkloadRef,
        user: UserContext,
        request: Request | None,
        db: AsyncSession | None,
        call: Callable[[], Awaitable[dict[str, Any]]],
        summary: Callable[[dict[str, Any]], str],
        details: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        label = MUTATION_LABEL[kind]

        async def _audit(status: str, extra: dict[str, Any]) -> None:
            await write_audit(
                db,
                request=request,
                user=user,
                action=f"{op}_{kind}",
                resource_type=kind,
                resource_name=ref.name,
                cluster_id=ref.cluster_id,
                namespace=ref.namespace,
                status=status,
                details={**(details or {}), **extra},
            )

        try:
            result = await call()
        except ApiException as e:
            http_exc = _workload_api_error(e, label=label, name=ref.name, namespace=ref.namespace)
            await _audit("failed", {"error": http_exc.detail, "k8s_status": e.status})
            raise http_exc from e
        except LookupError as e:
            await _audit("failed", {"error": str(e)})
            raise HTTPException(status_code=404, detail=str(e)) from e
        except ValueError as e:
            await _audit("failed", {"error": str(e)})
            raise HTTPException(status_code=400, detail=str(e)) from e
        except TimeoutError as e:
            await _audit("failed", {"error": "timeout"})
            raise HTTPException(status_code=504, detail="The cluster did not respond in time.") from e
        except Exception as e:
            await _audit("failed", {"error": "cluster_unavailable"})
            logger.error("workload_operation_failed", op=op, kind=kind, name=ref.name, error=str(e))
            raise HTTPException(status_code=502, detail="Unable to reach the cluster.") from e

        await _audit("success", {**result, "summary": summary(result)})
        return result

    # ── Workloads: read ────────────────────────────────────────────────

    @router.get("/workloads/{kind}", summary="List StatefulSets or DaemonSets")
    async def list_workloads(
        kind: WorkloadKind = Path(...),
        cluster_id: str = Query(..., description="Full Azure resource ID of the AKS cluster"),
        namespace: str | None = Query(default=None, max_length=63, pattern=K8S_NAME_PATTERN),
        refresh: bool = Query(default=False, description="Bypass cache and fetch fresh data"),
        user: UserContext = Depends(view_workloads),
        service=Depends(get_service),
    ) -> dict:
        try:
            items = await service.list_workloads(kind, cluster_id, namespace, bypass_cache=refresh)
        except ApiException as e:
            logger.error("list_workloads_failed", kind=kind, k8s_status=e.status, error=str(e))
            raise HTTPException(status_code=502, detail=f"Unable to list {KIND_LABEL[kind]}s.") from e
        except Exception as e:
            logger.error("list_workloads_failed", kind=kind, error=str(e))
            raise HTTPException(status_code=502, detail="Failed to connect to cluster.") from e
        return {"kind": KIND_LABEL[kind], "items": items, "count": len(items)}

    @router.get("/workloads/{kind}/cached", summary="List StatefulSets or DaemonSets from DB cache (fast)")
    async def list_cached_workloads(
        kind: WorkloadKind = Path(...),
        cluster_id: str = Query(..., description="Full Azure resource ID of the AKS cluster"),
        namespace: str | None = Query(default=None, max_length=63, pattern=K8S_NAME_PATTERN),
        user: UserContext = Depends(view_workloads),
        service=Depends(get_service),
    ) -> dict:
        try:
            items = await service.get_workloads_from_db(kind, cluster_id, namespace)
            last_sync = await service.get_workloads_last_sync_time(kind, cluster_id)
        except Exception as e:
            logger.warning("cached_workloads_db_failed", kind=kind, cluster_id=cluster_id, error=str(e))
            items, last_sync = [], None
        return {"source": "db", "last_sync": last_sync, "kind": KIND_LABEL[kind], "items": items, "count": len(items)}

    @router.get("/workloads/{kind}/detail", summary="StatefulSet or DaemonSet detail")
    async def get_workload_detail(
        kind: WorkloadKind = Path(...),
        cluster_id: str = Query(...),
        namespace: str = Query(..., max_length=63, pattern=K8S_NAME_PATTERN),
        name: str = Query(..., max_length=253, pattern=K8S_NAME_PATTERN),
        user: UserContext = Depends(view_workloads),
        service=Depends(get_service),
    ) -> dict:
        try:
            return await service.get_workload_detail(kind, cluster_id, namespace, name)
        except ApiException as e:
            raise _workload_api_error(e, label=KIND_LABEL[kind], name=name, namespace=namespace) from e
        except Exception as e:
            logger.error("get_workload_detail_failed", kind=kind, name=name, error=str(e))
            raise HTTPException(status_code=502, detail="Failed to connect to cluster.") from e

    # ── Workloads: mutations ───────────────────────────────────────────

    @router.post("/workloads/{kind}/scale", summary="Scale a StatefulSet")
    async def scale_workload(
        body: ScaleWorkloadRequest,
        request: Request,
        kind: WorkloadKind = Path(...),
        user: UserContext = Depends(require_capability("aks_workload_manage")),
        service=Depends(get_service),
        db: AsyncSession = Depends(get_db),
    ) -> dict:
        if kind != "statefulset":
            raise HTTPException(
                status_code=400, detail="DaemonSets cannot be scaled; they run one pod per eligible node."
            )
        return await _mutate(
            op="scale",
            kind=kind,
            ref=body,
            user=user,
            request=request,
            db=db,
            call=lambda: service.scale_statefulset(body.cluster_id, body.namespace, body.name, body.replicas),
            summary=lambda r: f"Scaled statefulset {body.name} from {r.get('previous_replicas')} to {body.replicas}",
        )

    @router.post("/workloads/{kind}/restart", summary="Rolling restart of a StatefulSet or DaemonSet")
    async def restart_workload(
        body: WorkloadRef,
        request: Request,
        kind: WorkloadKind = Path(...),
        user: UserContext = Depends(require_capability("aks_workload_manage")),
        service=Depends(get_service),
        db: AsyncSession = Depends(get_db),
    ) -> dict:
        return await _mutate(
            op="restart",
            kind=kind,
            ref=body,
            user=user,
            request=request,
            db=db,
            call=lambda: service.restart_workload(kind, body.cluster_id, body.namespace, body.name),
            summary=lambda _r: f"Restarted {kind} {body.name}",
        )

    @router.post("/workloads/{kind}/image", summary="Update a container image")
    async def update_workload_image(
        body: UpdateImageRequest,
        request: Request,
        kind: WorkloadKind = Path(...),
        user: UserContext = Depends(require_capability("aks_workload_manage")),
        service=Depends(get_service),
        db: AsyncSession = Depends(get_db),
    ) -> dict:
        return await _mutate(
            op="update_image",
            kind=kind,
            ref=body,
            user=user,
            request=request,
            db=db,
            call=lambda: service.update_workload_image(
                kind, body.cluster_id, body.namespace, body.name, body.container, body.image
            ),
            summary=lambda _r: f"Set image of {kind} {body.name}/{body.container} to {body.image}",
        )

    @router.post("/workloads/{kind}/strategy", summary="Update the rollout strategy")
    async def update_workload_strategy(
        body: UpdateStrategyRequest,
        request: Request,
        kind: WorkloadKind = Path(...),
        user: UserContext = Depends(require_capability("aks_workload_manage")),
        service=Depends(get_service),
        db: AsyncSession = Depends(get_db),
    ) -> dict:
        if kind == "statefulset" and (body.max_unavailable is not None or body.max_surge is not None):
            raise HTTPException(status_code=400, detail="maxUnavailable/maxSurge apply to DaemonSets only.")
        if kind == "daemonset" and body.partition is not None:
            raise HTTPException(status_code=400, detail="partition applies to StatefulSets only.")
        return await _mutate(
            op="update_strategy",
            kind=kind,
            ref=body,
            user=user,
            request=request,
            db=db,
            call=lambda: service.update_workload_strategy(
                kind,
                body.cluster_id,
                body.namespace,
                body.name,
                body.strategy_type,
                partition=body.partition,
                max_unavailable=body.max_unavailable,
                max_surge=body.max_surge,
            ),
            summary=lambda _r: f"Changed update strategy of {kind} {body.name} to {body.strategy_type}",
        )

    @router.post("/workloads/{kind}/rollback", summary="Roll back to a previous revision")
    async def rollback_workload(
        body: RollbackWorkloadRequest,
        request: Request,
        kind: WorkloadKind = Path(...),
        user: UserContext = Depends(require_capability("aks_workload_manage")),
        service=Depends(get_service),
        db: AsyncSession = Depends(get_db),
    ) -> dict:
        return await _mutate(
            op="rollback",
            kind=kind,
            ref=body,
            user=user,
            request=request,
            db=db,
            call=lambda: service.rollback_workload(kind, body.cluster_id, body.namespace, body.name, body.revision),
            summary=lambda _r: f"Rolled back {kind} {body.name} to revision {body.revision}",
        )

    @router.delete("/workloads/{kind}", summary="Delete a StatefulSet or DaemonSet")
    async def delete_workload(
        request: Request,
        kind: WorkloadKind = Path(...),
        cluster_id: str = Query(...),
        namespace: str = Query(..., max_length=63, pattern=K8S_NAME_PATTERN),
        name: str = Query(..., max_length=253, pattern=K8S_NAME_PATTERN),
        propagation_policy: str = Query(default="Background", pattern="^(Background|Foreground|Orphan)$"),
        user: UserContext = Depends(require_capability("aks_workload_delete")),
        service=Depends(get_service),
        db: AsyncSession = Depends(get_db),
    ) -> dict:
        ref = WorkloadRef(cluster_id=cluster_id, namespace=namespace, name=name)
        return await _mutate(
            op="delete",
            kind=kind,
            ref=ref,
            user=user,
            request=request,
            db=db,
            call=lambda: service.delete_workload(kind, cluster_id, namespace, name, propagation_policy),
            summary=lambda _r: f"Deleted {kind} {name}",
            details={"propagation_policy": propagation_policy},
        )

    # ── AKV → AKS secret sync (akv2k8s AzureKeyVaultSecret) ────────────────────

    @router.get("/akv-sync/cached", summary="AzureKeyVaultSecret sync status from DB cache (fast)")
    async def list_cached_akvs(
        cluster_id: str = Query(...),
        namespace: str | None = Query(default=None, max_length=63, pattern=K8S_NAME_PATTERN),
        user: UserContext = Depends(view_akv_sync),
        service=Depends(get_service),
    ) -> dict:
        try:
            items = await service.get_akvs_from_db(cluster_id, namespace)
            last_sync = await service.get_akvs_last_sync_time(cluster_id)
        except Exception as e:
            logger.warning("cached_akvs_db_failed", cluster_id=cluster_id, error=str(e))
            items, last_sync = [], None
        return {
            "source": "db",
            "last_sync": last_sync,
            "items": items,
            "count": len(items),
            "summary": summarize_akvs(items),
        }

    @router.get("/akv-sync/controller", summary="akv2k8s installation and controller health")
    async def get_akvs_controller(
        cluster_id: str = Query(...),
        user: UserContext = Depends(view_akv_sync),
        service=Depends(get_service),
    ) -> dict:
        try:
            return await service.get_akvs_controller_status(cluster_id)
        except Exception as e:
            logger.error("akvs_controller_status_failed", error=str(e))
            raise HTTPException(status_code=502, detail="Failed to connect to cluster.") from e

    @router.get("/akv-sync/detail", summary="Live sync detail for one AzureKeyVaultSecret")
    async def get_akvs_detail(
        cluster_id: str = Query(...),
        namespace: str = Query(..., max_length=63, pattern=K8S_NAME_PATTERN),
        name: str = Query(..., max_length=253, pattern=K8S_NAME_PATTERN),
        check_vault: bool = Query(default=False, description="Compare the last sync with Key Vault's newest version"),
        user: UserContext = Depends(view_akv_sync),
        service=Depends(get_service),
    ) -> dict:
        try:
            return await service.get_akvs_detail(cluster_id, namespace, name, check_vault=check_vault)
        except LookupError as e:
            raise HTTPException(status_code=404, detail=str(e)) from e
        except ApiException as e:
            raise _workload_api_error(e, label="AzureKeyVaultSecret", name=name, namespace=namespace) from e
        except Exception as e:
            logger.error("get_akvs_detail_failed", name=name, error=str(e))
            raise HTTPException(status_code=502, detail="Failed to connect to cluster.") from e

    @router.delete("/akv-sync", summary="Delete an AzureKeyVaultSecret")
    async def delete_akvs(
        request: Request,
        cluster_id: str = Query(...),
        namespace: str = Query(..., max_length=63, pattern=K8S_NAME_PATTERN),
        name: str = Query(..., max_length=253, pattern=K8S_NAME_PATTERN),
        keep_output: bool = Query(default=False, description="Keep the synced Secret/ConfigMap instead of removing it"),
        user: UserContext = Depends(require_capability("aks_akv_sync_delete")),
        service=Depends(get_service),
        db: AsyncSession = Depends(get_db),
    ) -> dict:
        ref = WorkloadRef(cluster_id=cluster_id, namespace=namespace, name=name)
        return await _mutate(
            op="delete",
            kind="azurekeyvaultsecret",
            ref=ref,
            user=user,
            request=request,
            db=db,
            call=lambda: service.delete_akvs(cluster_id, namespace, name, keep_output=keep_output),
            summary=lambda _r: f"Deleted AzureKeyVaultSecret {name}",
            details={"keep_output": keep_output},
        )
