"""Pod detail and complete-log archive download endpoints."""

from typing import Literal

import structlog
from fastapi import Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from kubernetes.client.rest import ApiException
from pydantic import BaseModel, Field, model_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.endpoints.aks_workload_endpoints import K8S_NAME_PATTERN, _workload_api_error
from app.core.authz import require_capability
from app.core.database import get_db
from app.models.auth import UserContext, UserRole
from app.services.aks_log_archive import MAX_ARCHIVE_PODS

logger = structlog.get_logger(__name__)

_ARCHIVE_LABEL = {"deployment": "Deployment", "statefulset": "StatefulSet", "daemonset": "DaemonSet", "pods": "Pod"}


class LogArchivePodRef(BaseModel):
    namespace: str = Field(..., max_length=63, pattern=K8S_NAME_PATTERN)
    name: str = Field(..., max_length=253, pattern=K8S_NAME_PATTERN)


class LogArchiveRequest(BaseModel):
    cluster_id: str = Field(..., description="Full Azure resource ID of the AKS cluster")
    kind: Literal["deployment", "statefulset", "daemonset", "pods"]
    namespace: str | None = Field(default=None, max_length=63, pattern=K8S_NAME_PATTERN)
    name: str | None = Field(default=None, max_length=253, pattern=K8S_NAME_PATTERN)
    pods: list[LogArchivePodRef] = Field(default_factory=list, max_length=MAX_ARCHIVE_PODS)
    include_previous: bool = Field(
        default=True, description="Also include the previous instance's log for containers that restarted"
    )

    @model_validator(mode="after")
    def _check_target(self) -> "LogArchiveRequest":
        if self.kind == "pods":
            if not self.pods:
                raise ValueError("pods is required when kind is 'pods'.")
        elif not (self.namespace and self.name):
            raise ValueError("namespace and name are required for a workload log archive.")
        return self


def register_detail_routes(router, *, get_service, write_audit):
    """Register pod detail and log archive routes on the AKS router."""

    view_pods = require_capability("aks_pod_view", permission_type="view", fallback_role=UserRole.READ)

    @router.get("/pods/detail", summary="Pod detail: containers, conditions, volumes, events, and manifest")
    async def get_pod_detail(
        cluster_id: str = Query(..., description="Full Azure resource ID of the AKS cluster"),
        namespace: str = Query(..., max_length=63, pattern=K8S_NAME_PATTERN),
        name: str = Query(..., max_length=253, pattern=K8S_NAME_PATTERN),
        user: UserContext = Depends(view_pods),
        service=Depends(get_service),
    ) -> dict:
        try:
            return await service.get_pod_detail(cluster_id, namespace, name)
        except ApiException as e:
            raise _workload_api_error(e, label="Pod", name=name, namespace=namespace) from e
        except Exception as e:
            logger.error("get_pod_detail_failed", name=name, namespace=namespace, error=str(e))
            raise HTTPException(status_code=502, detail="Failed to connect to cluster.") from e

    @router.post(
        "/logs/archive",
        summary="Download complete pod logs as a ZIP archive",
        description=(
            "Streams a ZIP with the full log of every container (init containers included) in the "
            "target's pods, plus previous-instance logs for restarted containers and a SUMMARY.txt. "
            f"Limited to {MAX_ARCHIVE_PODS} pods per archive."
        ),
        response_class=StreamingResponse,
    )
    async def download_log_archive(
        body: LogArchiveRequest,
        request: Request,
        user: UserContext = Depends(view_pods),
        service=Depends(get_service),
        db: AsyncSession = Depends(get_db),
    ) -> StreamingResponse:
        label = _ARCHIVE_LABEL[body.kind]
        pod_refs = [(p.namespace, p.name) for p in body.pods]
        try:
            plan = await service.plan_log_archive(
                body.cluster_id,
                body.kind,
                namespace=body.namespace,
                name=body.name,
                pods=pod_refs,
                include_previous=body.include_previous,
            )
        except ApiException as e:
            raise _workload_api_error(
                e,
                label=label,
                name=body.name or (pod_refs[0][1] if pod_refs else ""),
                namespace=body.namespace or (pod_refs[0][0] if pod_refs else ""),
            ) from e
        except LookupError as e:
            raise HTTPException(status_code=404, detail=str(e)) from e
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        except Exception as e:
            logger.error("log_archive_plan_failed", kind=body.kind, name=body.name, error=str(e))
            raise HTTPException(status_code=502, detail="Failed to connect to cluster.") from e

        # Bulk log export can carry sensitive output, so every archive is attributable.
        namespaces = {ns for ns, _ in pod_refs}
        await write_audit(
            db,
            request=request,
            user=user,
            action="download_logs",
            resource_type="pod" if body.kind == "pods" else body.kind,
            resource_name=body.name or (pod_refs[0][1] if len(pod_refs) == 1 else f"{plan.pod_count} pods"),
            cluster_id=body.cluster_id,
            namespace=body.namespace or (next(iter(namespaces)) if len(namespaces) == 1 else ""),
            status="success",
            details={
                "summary": f"Downloaded complete logs for {plan.target} ({plan.pod_count} pods)",
                "pod_count": plan.pod_count,
                "log_streams": len(plan.streams),
                "include_previous": body.include_previous,
                "missing_pods": plan.missing_pods,
            },
        )
        return StreamingResponse(
            service.stream_log_archive(body.cluster_id, plan),
            media_type="application/zip",
            headers={
                "Content-Disposition": f'attachment; filename="{plan.filename}"',
                "Cache-Control": "no-store",
                # Let ingress-nginx pass chunks through instead of buffering the whole archive.
                "X-Accel-Buffering": "no",
                "X-Log-Archive-Pods": str(plan.pod_count),
                "X-Log-Archive-Streams": str(len(plan.streams)),
            },
        )
