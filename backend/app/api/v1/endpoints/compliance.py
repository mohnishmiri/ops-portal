"""
Compliance & Drift Detection API Endpoints.

Full management interface for compliance monitoring:
- Synapse pipeline checksum tracking
- AKS pod drift detection
- Compliance scoring and dashboards
"""

import asyncio
from datetime import datetime

import structlog
from fastapi import APIRouter, Body, Depends, HTTPException, Path, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user, require_role
from app.core.database import get_db
from app.models.auth import UserContext, UserRole
from app.schemas.compliance import ExcelExportRequest, ModuleType
from app.services.compliance_excel_service import ComplianceExcelService
from app.services.compliance_service import ComplianceService, get_compliance_service
from app.services.compliance_sync_service import ComplianceSyncService

logger = structlog.get_logger(__name__)
router = APIRouter()


def _get_service(db: AsyncSession = Depends(get_db)) -> ComplianceService:
    return get_compliance_service(db)


# ── Request/Response Models ────────────────────────────────────────────


class AcknowledgeDriftRequest(BaseModel):
    """Request to acknowledge a drift event."""

    drift_id: int = Field(..., description="ID of the drift event to acknowledge")


class CollectChecksumsRequest(BaseModel):
    """Request to collect checksums."""

    subscription_ids: list[str] = Field(default=None, description="Subscription IDs to collect from")
    workspace_name: str | None = Field(
        default=None,
        description="Collect only this workspace (uses registry + direct SDK)",
    )


class CollectPodChecksumsRequest(BaseModel):
    """Request to collect pod checksums."""

    cluster_id: str = Field(..., description="Full Azure resource ID of the AKS cluster")
    namespaces: list[str] = Field(default=None, description="Namespaces to scan")


class CalculateComplianceRequest(BaseModel):
    """Request to calculate compliance score."""

    resource_type: str = Field(..., description="Type of resource (aks_cluster, synapse_workspace)")
    resource_id: str = Field(..., description="Full Azure resource ID")
    resource_name: str = Field(..., description="Display name of the resource")
    subscription_id: str = Field(..., description="Subscription ID")


class RunChecksumVerificationRequest(BaseModel):
    """Request to run Synapse checksum verification for a workspace."""

    workspace_name: str = Field(default="", description="Synapse workspace name (empty = run all workspaces)")
    notification_emails: list[str] | None = Field(
        default=None,
        description="Email addresses to auto-send results to after verification",
    )


class RunAKSChecksumVerificationRequest(BaseModel):
    """Request to run AKS pod checksum verification for a cluster."""

    cluster_id: str = Field(
        default="",
        description="AKS cluster resource ID (empty = run all known clusters)",
    )
    system: str = Field(default="attcc", description="System: attcc or ces")
    environment: str = Field(default="prod", description="Environment: prod, uat, perf, poc")
    namespaces: list[str] | None = Field(default=None, description="Namespaces to scan (all if omitted)")
    notification_emails: list[str] | None = Field(
        default=None,
        description="Email addresses to auto-send results to after verification",
    )


class SendChecksumEmailRequest(BaseModel):
    """Request to email checksum verification results."""

    run_id: str = Field(..., description="UUID of the verification run")
    recipient_email: str = Field(..., description="Email address for the report")


class ChecksumScheduleRequest(BaseModel):
    """Request to create a checksum schedule."""

    name: str = Field(..., description="Unique schedule name")
    description: str | None = Field(default=None, description="Optional description")
    module_type: str = Field(..., description="synapse or aks")
    system: str | None = Field(default=None, description="attcc or ces")
    environment: str | None = Field(default=None, description="prod, uat, perf, poc")
    workspace_name: str | None = Field(default=None, description="Synapse workspace name")
    cluster_id: str | None = Field(default=None, description="AKS cluster resource ID")
    cluster_name: str | None = Field(default=None, description="AKS cluster display name")
    namespaces: list[str] = Field(default_factory=list, description="Namespaces to scan")
    schedule_type: str = Field(default="interval", description="interval or cron")
    interval_hours: int = Field(default=24, description="Interval hours for interval schedule")
    cron_expression: str | None = Field(default=None, description="Cron expression for cron schedule")
    timezone: str = Field(default="UTC", description="Time zone for cron schedule")
    notification_emails: list[str] = Field(default_factory=list, description="Email recipients")
    is_enabled: bool = Field(default=True, description="Enable or disable schedule")


class ChecksumScheduleUpdateRequest(BaseModel):
    """Request to update a checksum schedule."""

    name: str | None = Field(default=None, description="Unique schedule name")
    description: str | None = Field(default=None, description="Optional description")
    module_type: str | None = Field(default=None, description="synapse or aks")
    system: str | None = Field(default=None, description="attcc or ces")
    environment: str | None = Field(default=None, description="prod, uat, perf, poc")
    workspace_name: str | None = Field(default=None, description="Synapse workspace name")
    cluster_id: str | None = Field(default=None, description="AKS cluster resource ID")
    cluster_name: str | None = Field(default=None, description="AKS cluster display name")
    namespaces: list[str] | None = Field(default=None, description="Namespaces to scan")
    schedule_type: str | None = Field(default=None, description="interval or cron")
    interval_hours: int | None = Field(default=None, description="Interval hours for interval schedule")
    cron_expression: str | None = Field(default=None, description="Cron expression for cron schedule")
    timezone: str | None = Field(default=None, description="Time zone for cron schedule")
    notification_emails: list[str] | None = Field(default=None, description="Email recipients")
    is_enabled: bool | None = Field(default=None, description="Enable or disable schedule")


# ── Synapse Pipeline Drift Detection ───────────────────────────────────


@router.get(
    "/synapse/workspaces",
    summary="List Synapse workspaces grouped by organisation",
    description=("Return available Synapse workspaces grouped into two categories: ATTCC and CES."),
)
async def list_synapse_workspaces_grouped(
    user: UserContext = Depends(get_current_user),
    service: ComplianceService = Depends(_get_service),
) -> dict:
    """Return workspaces grouped by organisation (ATTCC / CES)."""
    all_ws = await service.get_workspace_list()

    groups: dict[str, list[dict[str, str]]] = {
        "ATTCC": [],
        "CES": [],
    }

    for ws in all_ws:
        system = ws["system"].lower()
        if system == "attcc":
            groups["ATTCC"].append(ws)
        elif system == "ces":
            groups["CES"].append(ws)

    return {
        "groups": [
            {"label": label, "workspaces": wks}
            for label, wks in groups.items()
            if wks  # omit empty groups
        ],
        "total": len(all_ws),
    }


@router.get(
    "/synapse/checksum-comparison",
    summary="Get latest checksum comparison for a workspace",
    description=(
        "Return per-pipeline yesterday-vs-current hash comparison from the "
        "most recent verification run for the given workspace."
    ),
)
async def get_synapse_checksum_comparison(
    workspace_name: str = Query(..., description="Synapse workspace name"),
    user: UserContext = Depends(get_current_user),
    service: ComplianceService = Depends(_get_service),
) -> dict:
    """Fetch the latest comparison results scoped to a workspace."""
    # Re-use the existing results query, limited to latest run
    results = await service.get_checksum_results(
        workspace_name=workspace_name,
        days=7,
    )

    # Find the latest run's results
    if not results:
        return {
            "workspace_name": workspace_name,
            "results": [],
            "total": 0,
            "passed": 0,
            "failed": 0,
        }

    # Results are already ordered by execution_date desc; take the first run_id
    latest_run_id = results[0].get("run_id") if isinstance(results[0], dict) else getattr(results[0], "run_id", None)
    if latest_run_id:
        results = [
            r
            for r in results
            if (r.get("run_id") if isinstance(r, dict) else getattr(r, "run_id", None)) == latest_run_id
        ]

    passed = sum(
        1 for r in results if (r.get("result") if isinstance(r, dict) else getattr(r, "result", None)) == "PASS"
    )
    failed = sum(
        1 for r in results if (r.get("result") if isinstance(r, dict) else getattr(r, "result", None)) == "FAIL"
    )

    return {
        "workspace_name": workspace_name,
        "run_id": latest_run_id,
        "results": results,
        "total": len(results),
        "passed": passed,
        "failed": failed,
    }


@router.post(
    "/synapse/collect-checksums",
    summary="Collect Synapse pipeline checksums",
    description=(
        "Collect SHA256 checksums for Synapse pipelines. "
        "When *workspace_name* is provided only that workspace is scanned; "
        "otherwise all known ATTCC and CES workspaces are processed."
    ),
)
async def collect_synapse_checksums(
    request: CollectChecksumsRequest = Body(default=CollectChecksumsRequest()),
    user: UserContext = Depends(require_role(UserRole.WRITE)),
    service: ComplianceService = Depends(_get_service),
) -> dict:
    """Collect checksums for Synapse pipelines."""
    result = await service.collect_synapse_pipeline_checksums(
        subscription_ids=request.subscription_ids,
        workspace_name=request.workspace_name,
    )
    # Surface a clear status field so the frontend can detect failures.
    # When a specific workspace was requested and it failed, flag the result.
    if request.workspace_name and result.get("workspaces", 0) == 0 and result.get("errors"):
        result["status"] = "failed"
        result["error"] = result["errors"][0].get("error", "Unknown error during checksum collection")
    else:
        result["status"] = "success"
    return result


@router.get(
    "/synapse/drift",
    summary="Get Synapse pipeline drift",
    description="Return persisted Synapse drift events without re-running detection",
)
async def detect_synapse_drift(
    workspace_name: str = Query(default=None, description="Filter by workspace name"),
    days: int = Query(default=30, ge=1, le=365, description="Number of days of history"),
    user: UserContext = Depends(get_current_user),
    service: ComplianceService = Depends(_get_service),
) -> dict:
    """Get persisted Synapse pipeline drift events."""
    drifts = await service.get_synapse_drifts(workspace_name=workspace_name, days=days)
    return {
        "drifts": drifts,
        "count": len(drifts),
    }


@router.get(
    "/synapse/drift/summary",
    summary="Get Synapse drift summary",
    description="Get aggregated drift statistics for dashboard",
)
async def get_synapse_drift_summary(
    days: int = Query(default=7, ge=1, le=90, description="Number of days to summarize"),
    workspace_name: str = Query(default=None, description="Filter by workspace name"),
    user: UserContext = Depends(get_current_user),
    service: ComplianceService = Depends(_get_service),
) -> dict:
    """Get Synapse drift summary for dashboard."""
    return await service.get_synapse_drift_summary(days=days, workspace_name=workspace_name)


@router.post(
    "/synapse/drift/{drift_id}/acknowledge",
    summary="Acknowledge Synapse drift",
    description="Mark a drift event as acknowledged by a user",
)
async def acknowledge_synapse_drift(
    drift_id: int = Path(..., description="ID of the drift event"),
    user: UserContext = Depends(require_role(UserRole.WRITE)),
    service: ComplianceService = Depends(_get_service),
) -> dict:
    """Acknowledge a Synapse pipeline drift event."""
    result = await service.acknowledge_synapse_drift(
        drift_id=drift_id,
        user_id=user.user_id,
        user_email=user.email,
    )

    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error", "Acknowledge failed"))

    return result


# ── AKS Pod Drift Detection ────────────────────────────────────────────


@router.post(
    "/aks/collect-checksums",
    summary="Collect AKS pod checksums",
    description="Collect checksums for all pods in specified cluster/namespaces",
)
async def collect_pod_checksums(
    request: CollectPodChecksumsRequest,
    user: UserContext = Depends(require_role(UserRole.WRITE)),
    service: ComplianceService = Depends(_get_service),
) -> dict:
    """Collect checksums for AKS pods."""
    result = await service.collect_pod_checksums(
        cluster_id=request.cluster_id,
        namespaces=request.namespaces,
    )
    return result


@router.get(
    "/aks/namespaces",
    summary="List namespaces for an AKS cluster",
    description="Returns all Kubernetes namespaces accessible in the given cluster",
)
async def list_aks_namespaces(
    cluster_id: str = Query(..., description="Full Azure resource ID of the AKS cluster"),
    user: UserContext = Depends(get_current_user),
):
    """List namespaces from a live AKS cluster."""
    from app.core.database import get_db_session
    from app.services.aks_operations_service import AKSOperationsService

    try:
        async for db in get_db_session():
            aks_service = AKSOperationsService(db)
            _, core_v1, _ = await aks_service._get_k8s_clients(cluster_id)
            ns_list = await asyncio.get_event_loop().run_in_executor(
                None,
                core_v1.list_namespace,
            )
            namespaces = sorted(ns.metadata.name for ns in ns_list.items)
            return {"namespaces": namespaces, "count": len(namespaces)}
    except Exception as e:
        logger.error("list_aks_namespaces_failed", cluster_id=cluster_id, error=str(e))
        raise HTTPException(status_code=500, detail=f"Failed to list namespaces: {str(e)}")


@router.get(
    "/aks/drift",
    summary="Get AKS pod drift",
    description="Return persisted AKS pod drift events without re-running detection",
)
async def detect_pod_drift(
    cluster_id: str = Query(..., description="Full Azure resource ID of the AKS cluster"),
    namespace: str = Query(default=None, description="Filter by namespace"),
    days: int = Query(default=30, ge=1, le=365, description="Number of days of history"),
    user: UserContext = Depends(get_current_user),
    service: ComplianceService = Depends(_get_service),
) -> dict:
    """Get persisted AKS pod configuration drift events."""
    drifts = await service.get_pod_drifts(
        cluster_id=cluster_id,
        namespace=namespace,
        days=days,
    )
    return {
        "drifts": drifts,
        "count": len(drifts),
    }


@router.get(
    "/aks/drift/timeline",
    summary="Get AKS drift timeline",
    description="Get historical drift events for visualization",
)
async def get_pod_drift_timeline(
    cluster_id: str = Query(..., description="Full Azure resource ID of the AKS cluster"),
    days: int = Query(default=30, ge=1, le=365, description="Number of days of history"),
    namespace: str = Query(default=None, description="Filter by namespace"),
    user: UserContext = Depends(get_current_user),
    service: ComplianceService = Depends(_get_service),
) -> dict:
    """Get AKS pod drift timeline for charts."""
    timeline = await service.get_pod_drift_timeline(
        cluster_id=cluster_id,
        days=days,
        namespace=namespace,
    )
    return {
        "timeline": timeline,
        "count": len(timeline),
        "days": days,
    }


@router.post(
    "/aks/drift/{drift_id}/acknowledge",
    summary="Acknowledge AKS pod drift",
    description="Mark an AKS pod drift event as acknowledged by a user",
)
async def acknowledge_pod_drift(
    drift_id: int = Path(..., description="ID of the pod drift event"),
    user: UserContext = Depends(require_role(UserRole.WRITE)),
    service: ComplianceService = Depends(_get_service),
) -> dict:
    """Acknowledge an AKS pod drift event."""
    result = await service.acknowledge_pod_drift(
        drift_id=drift_id,
        user_id=user.user_id,
        user_email=user.email,
    )

    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error", "Acknowledge failed"))

    return result


# ── Compliance Scoring ─────────────────────────────────────────────────


@router.post(
    "/scores/calculate",
    summary="Calculate compliance score",
    description="Calculate and store compliance score for a resource",
)
async def calculate_compliance_score(
    request: CalculateComplianceRequest,
    user: UserContext = Depends(require_role(UserRole.WRITE)),
    service: ComplianceService = Depends(_get_service),
) -> dict:
    """Calculate compliance score for a resource."""
    try:
        result = await service.calculate_compliance_score(
            resource_type=request.resource_type,
            resource_id=request.resource_id,
            resource_name=request.resource_name,
            subscription_id=request.subscription_id,
        )
    except Exception as exc:
        logger.error(
            "compliance_score_calculation_failed",
            resource_type=request.resource_type,
            error=str(exc)[:500],
        )
        raise HTTPException(
            status_code=500,
            detail=f"Compliance score calculation failed: {str(exc)[:200]}",
        ) from exc

    if isinstance(result, dict) and "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])

    return result


@router.get(
    "/dashboard",
    summary="Get compliance dashboard",
    description="Get aggregated compliance metrics across all resources",
)
async def get_compliance_dashboard(
    subscription_ids: list[str] = Query(default=None, description="Filter by subscription IDs"),
    refresh: bool = Query(default=False, description="Force a fresh re-computation"),
    user: UserContext = Depends(get_current_user),
    service: ComplianceService = Depends(_get_service),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Get compliance dashboard — reads from pre-computed DB snapshot for speed.

    If ``refresh=true``, triggers a background sync and still returns the
    current cached data immediately.  Falls back to live computation only
    when no snapshot exists yet (first load after deployment).
    """
    sync_svc = ComplianceSyncService(db)

    # If refresh requested, kick off background recomputation
    if refresh and not await sync_svc.is_sync_running():
        ComplianceSyncService.schedule_background_sync(
            triggered_by=f"refresh:{user.display_name}",
        )

    # Fast path: serve from pre-computed DB snapshot
    try:
        cached = await sync_svc.get_dashboard_from_db()
        if cached and not subscription_ids:
            return cached
    except Exception as exc:
        logger.warning("compliance_dashboard_cache_read_failed", error=str(exc)[:200])

    # Slow path: live computation (first load or scoped query)
    try:
        data = await service.get_compliance_dashboard(subscription_ids=subscription_ids)
    except Exception as exc:
        logger.error(
            "compliance_dashboard_computation_failed",
            error=str(exc)[:500],
        )
        raise HTTPException(
            status_code=500,
            detail=f"Dashboard computation failed: {str(exc)[:200]}",
        ) from exc

    # Schedule background sync so next request is instant
    if not subscription_ids and not await sync_svc.is_sync_running():
        ComplianceSyncService.schedule_background_sync(triggered_by="auto:cache_miss")

    return data


@router.post(
    "/dashboard/sync",
    summary="Trigger compliance dashboard sync",
    description="Force a re-computation of the cached compliance dashboard data",
)
async def trigger_compliance_sync(
    user: UserContext = Depends(require_role(UserRole.ADMIN)),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Trigger a manual sync of the compliance dashboard cache."""
    sync_svc = ComplianceSyncService(db)
    if await sync_svc.is_sync_running():
        return {"status": "already_running"}
    ComplianceSyncService.schedule_background_sync(triggered_by=f"manual:{user.display_name}")
    return {"status": "sync_triggered"}


@router.get(
    "/dashboard/sync-status",
    summary="Get compliance sync status",
    description="Get the status of the last compliance dashboard sync",
)
async def get_compliance_sync_status(
    user: UserContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Get latest sync status."""
    sync_svc = ComplianceSyncService(db)
    return await sync_svc.get_sync_status()


# ── Drift Categories ───────────────────────────────────────────────────


@router.get(
    "/drift-categories",
    summary="Get drift category definitions",
    description="Get definitions for all drift categories and severities",
)
async def get_drift_categories(
    user: UserContext = Depends(get_current_user),
) -> dict:
    """Get drift category definitions for UI display."""
    return {
        "categories": [
            {
                "id": "container_image",
                "name": "Container Image Change",
                "description": "Container image tag or digest has changed",
                "severity": "high",
                "icon": "container",
            },
            {
                "id": "env_vars",
                "name": "Environment Variable Change",
                "description": "Environment variable added, removed, or modified",
                "severity": "medium",
                "icon": "settings",
            },
            {
                "id": "volumes",
                "name": "Volume Configuration Change",
                "description": "Volume mount or secret/configmap reference changed",
                "severity": "medium",
                "icon": "storage",
            },
            {
                "id": "resources",
                "name": "Resource Limit Change",
                "description": "CPU or memory requests/limits modified",
                "severity": "low",
                "icon": "cpu",
            },
            {
                "id": "pipeline_added",
                "name": "Pipeline Added",
                "description": "New Synapse pipeline detected",
                "severity": "medium",
                "icon": "add",
            },
            {
                "id": "pipeline_modified",
                "name": "Pipeline Modified",
                "description": "Synapse pipeline definition changed",
                "severity": "high",
                "icon": "edit",
            },
            {
                "id": "pipeline_deleted",
                "name": "Pipeline Deleted",
                "description": "Synapse pipeline removed from workspace",
                "severity": "critical",
                "icon": "delete",
            },
        ],
        "severities": [
            {"id": "critical", "name": "Critical", "color": "#dc2626", "priority": 1},
            {"id": "high", "name": "High", "color": "#ea580c", "priority": 2},
            {"id": "medium", "name": "Medium", "color": "#ca8a04", "priority": 3},
            {"id": "low", "name": "Low", "color": "#16a34a", "priority": 4},
        ],
        "grading_scale": {
            "A": {"min": 90, "max": 100, "description": "Excellent compliance"},
            "B": {"min": 80, "max": 89, "description": "Good compliance"},
            "C": {"min": 70, "max": 79, "description": "Fair compliance"},
            "D": {"min": 60, "max": 69, "description": "Poor compliance"},
            "F": {"min": 0, "max": 59, "description": "Failing compliance"},
        },
    }


# ── Synapse Checksum Verification (Multi-Environment) ─────────────────


@router.get(
    "/checksum/workspaces",
    summary="List available Synapse workspaces",
    description="Return the full workspace registry with optional system/env filter",
)
async def list_checksum_workspaces(
    system: str | None = Query(None, description="Filter by system: 'attcc' or 'ces'"),
    environment: str | None = Query(None, description="Filter by environment: 'prod', 'uat', etc."),
    user: UserContext = Depends(get_current_user),
    service: ComplianceService = Depends(_get_service),
):
    """Return the workspace registry."""
    workspaces = await service.get_workspace_list(system=system, environment=environment)
    return {"workspaces": workspaces, "total": len(workspaces)}


@router.post(
    "/checksum/verify",
    summary="Run Synapse checksum verification",
    description="Execute a checksum comparison for a specific Synapse workspace",
)
async def run_checksum_verification(
    request: RunChecksumVerificationRequest = Body(default=RunChecksumVerificationRequest()),
    user: UserContext = Depends(require_role(UserRole.WRITE)),
    service: ComplianceService = Depends(_get_service),
):
    """Trigger a checksum comparison run.

    When *workspace_name* is empty the service iterates **all** known
    workspaces and aggregates results (batch mode).
    """
    try:
        if request.workspace_name:
            result = await service.run_checksum_verification(request.workspace_name)
        else:
            result = await service.run_all_checksum_verifications()

        # Auto-send email report if notification_emails provided
        if request.notification_emails and result.get("run_id"):
            try:
                await service.send_checksum_report(
                    run_id=result["run_id"],
                    recipient_emails=request.notification_emails,
                )
            except Exception as email_err:
                logger.warning(
                    "auto_email_failed",
                    run_id=result.get("run_id"),
                    error=str(email_err),
                )

        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error("checksum_verification_failed", error=str(e), exc_info=True)
        raise HTTPException(status_code=500, detail=f"Checksum verification failed: {str(e)}")


@router.post(
    "/aks/checksum/verify",
    summary="Run AKS pod checksum verification",
    description="Collect AKS pod checksums, detect drift, and store results in DB",
)
async def run_aks_checksum_verification(
    request: RunAKSChecksumVerificationRequest = Body(default=RunAKSChecksumVerificationRequest()),
    user: UserContext = Depends(require_role(UserRole.WRITE)),
    service: ComplianceService = Depends(_get_service),
):
    """Trigger an AKS pod checksum collection + drift detection run.

    When *cluster_id* is empty the service discovers all known clusters
    from existing DB records and runs verification for each (batch mode).
    """
    try:
        if request.cluster_id:
            result = await service.run_aks_checksum(
                cluster_id=request.cluster_id,
                system=request.system,
                environment=request.environment,
                namespaces=request.namespaces,
            )
        else:
            result = await service.run_all_aks_checksums(
                system=request.system,
                environment=request.environment,
                namespaces=request.namespaces,
            )

        # Auto-send email report if notification_emails provided
        if request.notification_emails and result.get("run_id"):
            try:
                await service.send_checksum_report(
                    run_id=result["run_id"],
                    recipient_emails=request.notification_emails,
                )
            except Exception as email_err:
                logger.warning(
                    "auto_email_aks_failed",
                    run_id=result.get("run_id"),
                    error=str(email_err),
                )

        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        logger.error("aks_checksum_verification_failed", error=str(e))
        raise HTTPException(status_code=500, detail=f"AKS checksum verification failed: {str(e)}")


@router.get(
    "/checksum/schedules",
    summary="List checksum schedules",
    description="List configured checksum schedules",
)
async def list_checksum_schedules(
    user: UserContext = Depends(get_current_user),
    service: ComplianceService = Depends(_get_service),
) -> dict:
    schedules = await service.list_checksum_schedules()
    return {"schedules": schedules, "count": len(schedules)}


@router.post(
    "/checksum/schedules",
    summary="Create checksum schedule",
    description="Create a checksum schedule for Synapse or AKS",
)
async def create_checksum_schedule(
    request: ChecksumScheduleRequest = Body(...),
    user: UserContext = Depends(require_role(UserRole.WRITE)),
    service: ComplianceService = Depends(_get_service),
) -> dict:
    try:
        schedule = await service.create_checksum_schedule(
            payload=request.model_dump(),
            created_by=user.email or user.user_id,
        )
        return schedule
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.put(
    "/checksum/schedules/{schedule_id}",
    summary="Update checksum schedule",
    description="Update a checksum schedule",
)
async def update_checksum_schedule(
    schedule_id: int = Path(..., description="Schedule ID"),
    request: ChecksumScheduleUpdateRequest = Body(...),
    user: UserContext = Depends(require_role(UserRole.WRITE)),
    service: ComplianceService = Depends(_get_service),
) -> dict:
    try:
        schedule = await service.update_checksum_schedule(
            schedule_id=schedule_id,
            payload=request.model_dump(exclude_unset=True),
        )
        return schedule
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post(
    "/checksum/schedules/{schedule_id}/run",
    summary="Run checksum schedule now",
    description="Trigger a checksum schedule immediately",
)
async def run_checksum_schedule_now(
    schedule_id: int = Path(..., description="Schedule ID"),
    user: UserContext = Depends(require_role(UserRole.WRITE)),
    service: ComplianceService = Depends(_get_service),
) -> dict:
    try:
        return await service.run_checksum_schedule(schedule_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get(
    "/checksum/runs",
    summary="Get checksum verification runs",
    description="Query recent verification runs with optional filters",
)
async def get_checksum_runs(
    system: str | None = Query(None, description="Filter by system: 'attcc' or 'ces'"),
    environment: str | None = Query(None, description="Filter by environment"),
    workspace_name: str | None = Query(None, description="Filter by workspace name"),
    days: int = Query(30, ge=1, le=365, description="Look-back window in days"),
    module_type: str | None = Query(None, description="Filter by module type: 'synapse' or 'aks'"),
    user: UserContext = Depends(get_current_user),
    service: ComplianceService = Depends(_get_service),
):
    """Retrieve recent verification runs."""
    try:
        runs = await service.get_checksum_runs(
            system=system,
            environment=environment,
            workspace_name=workspace_name,
            days=days,
            module_type=module_type,
        )
        return {"runs": runs, "total": len(runs)}
    except Exception as e:
        logger.error("get_checksum_runs_failed", error=str(e))
        raise HTTPException(status_code=500, detail=f"Failed to retrieve runs: {str(e)}")


@router.get(
    "/checksum/results",
    summary="Get checksum verification results",
    description="Query per-pipeline checksum results with flexible filters",
)
async def get_checksum_results(
    system: str | None = Query(None, description="Filter by system: 'attcc' or 'ces'"),
    environment: str | None = Query(None, description="Filter by environment"),
    workspace_name: str | None = Query(None, description="Filter by workspace name"),
    days: int = Query(30, ge=1, le=365, description="Look-back window in days"),
    status: str | None = Query(None, description="Filter by result: 'PASS' or 'FAIL'"),
    run_id: str | None = Query(None, description="Filter by specific run ID"),
    module_type: str | None = Query(None, description="Filter by module type: 'synapse' or 'aks'"),
    user: UserContext = Depends(get_current_user),
    service: ComplianceService = Depends(_get_service),
):
    """Retrieve per-pipeline checksum verification results."""
    try:
        results = await service.get_checksum_results(
            run_id=run_id,
            system=system,
            environment=environment,
            workspace_name=workspace_name,
            status_filter=status,
            days=days,
            module_type=module_type,
        )
        return {"results": results, "total": len(results)}
    except Exception as e:
        logger.error("get_checksum_results_failed", error=str(e))
        raise HTTPException(status_code=500, detail=f"Failed to retrieve results: {str(e)}")


@router.get(
    "/checksum/metrics",
    summary="Get checksum verification metrics",
    description="Aggregated pass/fail metrics by date and system for dashboard charts",
)
async def get_checksum_metrics(
    days: int = Query(30, ge=1, le=365, description="Look-back window in days"),
    module_type: str | None = Query(None, description="Filter by module type: 'synapse' or 'aks'"),
    user: UserContext = Depends(get_current_user),
    service: ComplianceService = Depends(_get_service),
    db: AsyncSession = Depends(get_db),
):
    """Get pass/fail metrics for dashboard visualization.

    Reads from pre-computed snapshot when using default params (30 days, no filter).
    """
    try:
        if days == 30 and module_type is None:
            sync_svc = ComplianceSyncService(db)
            cached = await sync_svc.get_metrics_from_db()
            if cached is not None:
                return cached
        metrics = await service.get_checksum_metrics(days=days, module_type=module_type)
        return metrics
    except Exception as e:
        logger.error("get_checksum_metrics_failed", error=str(e))
        raise HTTPException(status_code=500, detail=f"Failed to retrieve metrics: {str(e)}")


@router.get(
    "/checksum/download/{run_id}",
    summary="Download checksum results as CSV",
    description="Download the results of a specific verification run as a CSV file",
)
async def download_checksum_csv(
    run_id: str = Path(..., description="UUID of the verification run"),
    user: UserContext = Depends(get_current_user),
    service: ComplianceService = Depends(_get_service),
):
    """Download a verification run's results as CSV."""
    try:
        csv_bytes = await service.generate_checksum_csv(run_id)
        return StreamingResponse(
            iter([csv_bytes]),
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename=checksum_{run_id}.csv"},
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error("download_checksum_csv_failed", error=str(e))
        raise HTTPException(status_code=500, detail=f"CSV generation failed: {str(e)}")


# ── Audit-Ready Excel Export ────────────────────────────────────────────


@router.get(
    "/export/excel",
    summary="Export compliance data as Excel",
    description=(
        "Generate an audit-ready, multi-sheet Excel workbook (.xlsx) with "
        "AT&T-branded formatting. Includes Synapse drift, AKS pod drift, "
        "compliance scores, and checksum run sheets. Supports filtering by "
        "module, system, date range, severity, and status."
    ),
    response_class=StreamingResponse,
    responses={
        200: {
            "content": {"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": {}},
            "description": "Excel workbook download",
        },
    },
)
async def export_compliance_excel(
    module_type: ModuleType | None = Query(None, description="Filter by module: synapse or aks"),
    system: str | None = Query(None, description="Filter by system name (e.g. attcc, ces)"),
    date_from: str | None = Query(
        None,
        description="Start date filter (ISO 8601, e.g. 2025-01-01)",
        alias="dateFrom",
    ),
    date_to: str | None = Query(
        None,
        description="End date filter (ISO 8601, e.g. 2025-12-31)",
        alias="dateTo",
    ),
    severity_filter: list[str] | None = Query(None, description="Filter by severity levels", alias="severity"),
    status_filter: list[str] | None = Query(None, description="Filter by drift status", alias="status"),
    include_scores: bool = Query(True, description="Include Compliance Scores sheet"),
    include_checksum_runs: bool = Query(True, description="Include Checksum Runs sheet"),
    db: AsyncSession = Depends(get_db),
    user: UserContext = Depends(get_current_user),
):
    """Generate and download an audit-ready Excel compliance report."""
    from datetime import datetime as dt

    logger.info(
        "excel_export_requested",
        user=user.email,
        module_type=module_type,
        system=system,
    )

    # Build the export request from query params
    parsed_date_from = None
    parsed_date_to = None
    if date_from:
        try:
            parsed_date_from = dt.fromisoformat(date_from)
        except ValueError:
            raise HTTPException(
                status_code=422,
                detail=f"Invalid dateFrom format: {date_from}. Use ISO 8601.",
            )
    if date_to:
        try:
            parsed_date_to = dt.fromisoformat(date_to)
        except ValueError:
            raise HTTPException(
                status_code=422,
                detail=f"Invalid dateTo format: {date_to}. Use ISO 8601.",
            )

    request = ExcelExportRequest(
        module_type=module_type,
        system=system,
        date_from=parsed_date_from,
        date_to=parsed_date_to,
        severity_filter=severity_filter,
        status_filter=status_filter,
        include_scores=include_scores,
        include_checksum_runs=include_checksum_runs,
    )

    try:
        excel_service = ComplianceExcelService()
        buf, metadata = await excel_service.generate_export(db, request)

        logger.info(
            "excel_export_generated",
            user=user.email,
            filename=metadata.filename,
            total_rows=metadata.total_rows,
            sheets=metadata.sheet_names,
        )

        return StreamingResponse(
            iter([buf.getvalue()]),
            media_type=metadata.content_type,
            headers={
                "Content-Disposition": f'attachment; filename="{metadata.filename}"',
                "Content-Length": str(metadata.file_size_bytes),
            },
        )
    except Exception as e:
        import traceback as _tb

        logger.error(
            "excel_export_failed",
            user=user.email,
            error=str(e),
            traceback=_tb.format_exc(),
        )
        raise HTTPException(
            status_code=500,
            detail=f"Excel export generation failed: {str(e)}",
        )


@router.post(
    "/checksum/email",
    summary="Email checksum results",
    description="Send an HTML report of checksum verification results to a recipient",
)
async def email_checksum_results(
    request: SendChecksumEmailRequest = Body(...),
    user: UserContext = Depends(require_role(UserRole.WRITE)),
    service: ComplianceService = Depends(_get_service),
):
    """Email the results of a verification run."""
    try:
        result = await service.send_checksum_email(
            run_id=request.run_id,
            recipient_email=request.recipient_email,
        )
        return result
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e))
    except Exception as e:
        logger.error("email_checksum_failed", error=str(e))
        raise HTTPException(status_code=500, detail=f"Email sending failed: {str(e)}")


# ── Synapse Bash Script Integration Endpoints ───────────────────────────


@router.post(
    "/synapse/checksum/generate",
    summary="Generate Synapse checksum (via bash script)",
    description="Execute bash script to generate fresh checksum snapshot for Synapse workspace",
)
async def generate_synapse_checksum_bash(
    system: str = Query(..., description="attcc or ces", pattern="^(attcc|ces)$"),
    workspace_name: str = Query(..., description="Synapse workspace name"),
    environment: str = Query("prod", description="Environment tag"),
    user: UserContext = Depends(require_role(UserRole.WRITE)),
) -> dict:
    """Generate Synapse checksum using bash script."""
    from app.core.database import get_db_session
    from app.services.synapse_checksum_bash_service import SynapseChecksumBashService

    try:
        async for db in get_db_session():
            bash_service = SynapseChecksumBashService(db)
            result = await bash_service.generate_checksum_snapshot(
                system=system,
                workspace_name=workspace_name,
                environment=environment,
                triggered_by=f"user:{user.email}",
            )

            # Log audit
            from app.models.database import AuditLog

            audit = AuditLog(
                timestamp=datetime.utcnow(),
                user_id=user.user_id,
                user_email=user.email,
                action="synapse_checksum_generate",
                resource_type="synapse_workspace",
                resource_id=workspace_name,
                status="success" if result.get("success") else "failed",
                details=result,
            )
            db.add(audit)
            await db.commit()

            if not result.get("success"):
                raise HTTPException(
                    status_code=500,
                    detail=f"Checksum generation failed: {result.get('error')}",
                )

            return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            "generate_synapse_checksum_failed",
            system=system,
            workspace=workspace_name,
            error=str(e),
        )
        raise HTTPException(status_code=500, detail=str(e)[:200])
    raise HTTPException(status_code=503, detail="Database unavailable")


@router.post(
    "/synapse/checksum/compare",
    summary="Compare Synapse checksums (via bash script)",
    description="Compare today's checksum with yesterday's using bash script",
)
async def compare_synapse_checksums_bash(
    system: str = Query(..., description="attcc or ces", pattern="^(attcc|ces)$"),
    workspace_name: str = Query(..., description="Synapse workspace name"),
    environment: str = Query("prod", description="Environment tag"),
    send_email: bool = Query(False, description="Send email report to recipients"),
    recipient_emails: list[str] = Query(None, description="Additional email recipients"),
    user: UserContext = Depends(require_role(UserRole.WRITE)),
) -> dict:
    """Compare Synapse checksums using bash script and optionally email results."""
    from app.core.database import get_db_session
    from app.services.email_notification_service import EmailNotificationService
    from app.services.synapse_checksum_bash_service import SynapseChecksumBashService

    try:
        async for db in get_db_session():
            bash_service = SynapseChecksumBashService(db)

            # Compare checksums
            comp_result = await bash_service.compare_checksum_snapshots(
                system=system,
                workspace_name=workspace_name,
                environment=environment,
            )

            if not comp_result.get("success"):
                raise HTTPException(
                    status_code=500,
                    detail=f"Checksum comparison failed: {comp_result.get('error')}",
                )

            # Send email if requested
            if send_email:
                email_service = EmailNotificationService(db)
                emails_to_send = recipient_emails or [user.email]

                for recipient in emails_to_send:
                    try:
                        await email_service.send_checksum_comparison_report(
                            recipient_email=recipient,
                            system=system,
                            workspace_name=workspace_name,
                            run_id=f"manual_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}",
                            total_pipelines=0,  # Would need from bash output
                            changed_count=comp_result.get("total_changed", 0),
                            added_count=comp_result.get("total_added", 0),
                            removed_count=comp_result.get("total_removed", 0),
                            environment=environment,
                        )
                    except Exception as e:
                        logger.error(
                            "checksum_email_failed",
                            system=system,
                            recipient=recipient,
                            error=str(e),
                        )

            # Log audit
            from app.models.database import AuditLog

            audit = AuditLog(
                timestamp=datetime.utcnow(),
                user_id=user.user_id,
                user_email=user.email,
                action="synapse_checksum_compare",
                resource_type="synapse_workspace",
                resource_id=workspace_name,
                status="success",
                details=comp_result,
            )
            db.add(audit)
            await db.commit()

            return {
                "success": True,
                "comparison": comp_result,
                "emails_sent": (len(recipient_emails or [user.email]) if send_email else 0),
            }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            "compare_synapse_checksums_failed",
            system=system,
            workspace=workspace_name,
            error=str(e),
        )
        raise HTTPException(status_code=500, detail=str(e)[:200])
    raise HTTPException(status_code=503, detail="Database unavailable")


@router.post(
    "/synapse/checksum/schedule",
    summary="Create/update checksum schedule",
    description="Create or update an automated checksum schedule",
)
async def create_synapse_checksum_schedule(
    request: ChecksumScheduleRequest,
    user: UserContext = Depends(require_role(UserRole.WRITE)),
    service: ComplianceService = Depends(_get_service),
) -> dict:
    """Create a new checksum schedule (Synapse bash integration)."""
    try:
        result = await service.create_checksum_schedule(
            payload=request.model_dump(),
            created_by=user.email or user.user_id,
        )
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error("create_checksum_schedule_failed", error=str(e))
        raise HTTPException(status_code=500, detail=str(e)[:200])


@router.get(
    "/synapse/checksum/schedules",
    summary="List checksum schedules",
    description="List all configured checksum schedules",
)
async def list_synapse_checksum_schedules(
    user: UserContext = Depends(get_current_user),
    service: ComplianceService = Depends(_get_service),
) -> dict:
    """List all checksum schedules (Synapse bash integration)."""
    try:
        schedules = await service.list_checksum_schedules()
        return {
            "schedules": schedules,
            "count": len(schedules),
        }
    except Exception as e:
        logger.error("list_checksum_schedules_failed", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))
