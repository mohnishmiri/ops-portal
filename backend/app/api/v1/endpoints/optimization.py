"""
FinOps Optimization & Cost Recommendation API Endpoints.

Identifies idle resources, unattached disks, overprovisioned SKUs,
and provides reservation/savings plan recommendations.

Cleanup delete endpoints require ADMIN and Azure RBAC:
  - Microsoft.Compute/disks/delete
  - Microsoft.Network/privateEndpoints/delete
"""

import structlog
from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user, require_role
from app.core.database import get_db
from app.models.auth import UserContext, UserRole
from app.models.database import AuditLog
from app.models.optimization import (
    CostRecommendation,
    OptimizationDashboardResponse,
    OptimizationSummary,
    RecommendationCategory,
    RecommendationPriority,
    RecommendationStatus,
)
from app.services.optimization_service import OptimizationService

logger = structlog.get_logger(__name__)

router = APIRouter()


def _get_optimization_service() -> OptimizationService:
    return OptimizationService()


class DiskCleanupRequest(BaseModel):
    subscription_id: str = Field(..., description="Azure subscription ID")
    resource_group: str = Field(..., description="Resource group containing the disk")
    disk_name: str = Field(..., description="Managed disk name")


class PrivateEndpointCleanupRequest(BaseModel):
    subscription_id: str = Field(..., description="Azure subscription ID")
    resource_group: str = Field(..., description="Resource group containing the private endpoint")
    endpoint_name: str = Field(..., description="Private endpoint name")


def _assert_subscription_allowed(user: UserContext, subscription_id: str) -> None:
    if user.allowed_subscriptions and subscription_id not in user.allowed_subscriptions:
        raise HTTPException(
            status_code=403,
            detail=f"Subscription '{subscription_id}' is not in your allowed scope.",
        )


async def _write_cost_cleanup_audit_log(
    db: AsyncSession,
    *,
    request: Request | None,
    user: UserContext,
    action: str,
    resource_type: str,
    resource_name: str,
    subscription_id: str,
    resource_group: str,
    status: str,
    details: dict | None = None,
) -> None:
    audit = AuditLog(
        user_id=user.user_id,
        user_email=user.email,
        action=action,
        resource_type=resource_type,
        resource_id=resource_name,
        details={
            "page": "LeadershipDashboard",
            "feature": "cost_cleanup",
            "subscription_id": subscription_id,
            "resource_group": resource_group,
            "resource_name": resource_name,
            **(details or {}),
        },
        ip_address=request.client.host if request and request.client else None,
        status=status,
    )
    try:
        db.add(audit)
        await db.commit()
    except Exception as exc:
        await db.rollback()
        logger.warning(
            "cost_cleanup_audit_log_failed",
            action=action,
            resource_name=resource_name,
            error=str(exc)[:200],
        )


@router.get(
    "/summary",
    response_model=OptimizationSummary,
    summary="Get overall optimization summary",
)
async def get_optimization_summary(
    refresh: bool = Query(
        default=False,
        description="Bypass page cache and fetch fresh optimization data",
    ),
    user: UserContext = Depends(get_current_user),
    service: OptimizationService = Depends(_get_optimization_service),
    db: AsyncSession = Depends(get_db),
) -> OptimizationSummary:
    """Get aggregated optimization summary across all subscriptions."""
    return await service.get_optimization_summary(
        subscription_ids=user.allowed_subscriptions or None,
        db=db,
        refresh=refresh,
    )


@router.get(
    "/dashboard",
    response_model=OptimizationDashboardResponse,
    summary="Full optimization dashboard data",
)
async def get_optimization_dashboard(
    user: UserContext = Depends(get_current_user),
    service: OptimizationService = Depends(_get_optimization_service),
) -> OptimizationDashboardResponse:
    """Complete optimization dashboard with all recommendations."""
    return await service.get_full_dashboard(
        subscription_ids=user.allowed_subscriptions or None,
    )


@router.get(
    "/recommendations",
    response_model=list[CostRecommendation],
    summary="List all recommendations",
)
async def list_recommendations(
    category: RecommendationCategory | None = Query(default=None),
    priority: RecommendationPriority | None = Query(default=None),
    subscription_id: str | None = Query(default=None),
    status: RecommendationStatus | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    user: UserContext = Depends(get_current_user),
    service: OptimizationService = Depends(_get_optimization_service),
) -> list[CostRecommendation]:
    """List recommendations with optional filtering."""
    return await service.list_recommendations(
        subscription_ids=[subscription_id] if subscription_id else None,
        category=category,
        priority=priority,
        status=status,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/idle-resources",
    response_model=list[CostRecommendation],
    summary="List idle/underutilized resources",
)
async def list_idle_resources(
    user: UserContext = Depends(get_current_user),
    service: OptimizationService = Depends(_get_optimization_service),
) -> list[CostRecommendation]:
    """Identify idle VMs, unattached disks, orphaned snapshots."""
    return await service.detect_idle_resources(
        subscription_ids=user.allowed_subscriptions or None,
    )


@router.patch(
    "/recommendations/{recommendation_id}/status",
    response_model=CostRecommendation,
    summary="Update recommendation status",
)
async def update_recommendation_status(
    recommendation_id: str,
    new_status: RecommendationStatus,
    user: UserContext = Depends(require_role(UserRole.ADMIN, UserRole.WRITE)),
    service: OptimizationService = Depends(_get_optimization_service),
) -> CostRecommendation:
    """Update the status of a recommendation (implement, dismiss, etc.)."""
    return await service.update_recommendation_status(
        recommendation_id=recommendation_id,
        new_status=new_status,
        updated_by=user.user_id,
    )


@router.post(
    "/cleanup/disks",
    summary="Delete an unattached managed disk",
    description="Permanently delete a managed disk that is in Unattached state.",
)
async def delete_unattached_disk_endpoint(
    body: DiskCleanupRequest = Body(...),
    request: Request = None,
    user: UserContext = Depends(require_role(UserRole.ADMIN)),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Delete an unattached disk for cost savings."""
    _assert_subscription_allowed(user, body.subscription_id)
    from app.services.azure_resource_service import AzureResourceService

    svc = AzureResourceService(db_session=db)
    try:
        result = await svc.delete_unattached_disk(
            subscription_id=body.subscription_id,
            resource_group=body.resource_group,
            disk_name=body.disk_name,
        )
        await _write_cost_cleanup_audit_log(
            db,
            request=request,
            user=user,
            action="delete_unattached_disk",
            resource_type="managed_disk",
            resource_name=body.disk_name,
            subscription_id=body.subscription_id,
            resource_group=body.resource_group,
            status="success",
            details={"summary": f"Deleted unattached disk '{body.disk_name}'"},
        )
        return result
    except ValueError as exc:
        await _write_cost_cleanup_audit_log(
            db,
            request=request,
            user=user,
            action="delete_unattached_disk",
            resource_type="managed_disk",
            resource_name=body.disk_name,
            subscription_id=body.subscription_id,
            resource_group=body.resource_group,
            status="failed",
            details={"error": str(exc)},
        )
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        await _write_cost_cleanup_audit_log(
            db,
            request=request,
            user=user,
            action="delete_unattached_disk",
            resource_type="managed_disk",
            resource_name=body.disk_name,
            subscription_id=body.subscription_id,
            resource_group=body.resource_group,
            status="failed",
            details={"error": str(exc)[:500]},
        )
        raise HTTPException(
            status_code=500,
            detail=f"Failed to delete disk '{body.disk_name}': {exc}",
        ) from exc


@router.post(
    "/cleanup/private-endpoints",
    summary="Delete a disconnected private endpoint",
    description="Permanently delete a private endpoint whose private link connection is disconnected.",
)
async def delete_disconnected_private_endpoint_endpoint(
    body: PrivateEndpointCleanupRequest = Body(...),
    request: Request = None,
    user: UserContext = Depends(require_role(UserRole.ADMIN)),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Delete a disconnected private endpoint for cost savings."""
    _assert_subscription_allowed(user, body.subscription_id)
    from app.services.azure_resource_service import AzureResourceService

    svc = AzureResourceService(db_session=db)
    try:
        result = await svc.delete_disconnected_private_endpoint(
            subscription_id=body.subscription_id,
            resource_group=body.resource_group,
            endpoint_name=body.endpoint_name,
        )
        # Invalidate optimization cache so stale PE no longer appears on refresh
        from app.core.db_cache import cache_manager
        from app.core.subscription_scope import get_scoped_subscription_ids

        opt_svc = _get_optimization_service()
        subs = await get_scoped_subscription_ids()
        cache_key = opt_svc._summary_cache_key(subs)
        await cache_manager.invalidate(cache_key)

        await _write_cost_cleanup_audit_log(
            db,
            request=request,
            user=user,
            action="delete_disconnected_private_endpoint",
            resource_type="private_endpoint",
            resource_name=body.endpoint_name,
            subscription_id=body.subscription_id,
            resource_group=body.resource_group,
            status="success",
            details={
                "summary": f"Deleted disconnected private endpoint '{body.endpoint_name}'",
                "action_type": result.get("action", "delete"),
            },
        )
        return result
    except ValueError as exc:
        await _write_cost_cleanup_audit_log(
            db,
            request=request,
            user=user,
            action="delete_disconnected_private_endpoint",
            resource_type="private_endpoint",
            resource_name=body.endpoint_name,
            subscription_id=body.subscription_id,
            resource_group=body.resource_group,
            status="failed",
            details={"error": str(exc)},
        )
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        await _write_cost_cleanup_audit_log(
            db,
            request=request,
            user=user,
            action="delete_disconnected_private_endpoint",
            resource_type="private_endpoint",
            resource_name=body.endpoint_name,
            subscription_id=body.subscription_id,
            resource_group=body.resource_group,
            status="failed",
            details={"error": str(exc)[:500]},
        )
        raise HTTPException(
            status_code=500,
            detail=f"Failed to delete private endpoint '{body.endpoint_name}': {exc}",
        ) from exc
