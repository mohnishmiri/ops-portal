"""
FinOps Optimization & Cost Recommendation API Endpoints.

Identifies idle resources, unattached disks, overprovisioned SKUs,
and provides reservation/savings plan recommendations.
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user, require_role
from app.core.database import get_db
from app.models.auth import UserContext, UserRole
from app.models.optimization import (
    CostRecommendation,
    OptimizationDashboardResponse,
    OptimizationSummary,
    RecommendationCategory,
    RecommendationPriority,
    RecommendationStatus,
)
from app.services.optimization_service import OptimizationService

router = APIRouter()


def _get_optimization_service() -> OptimizationService:
    return OptimizationService()


@router.get(
    "/summary",
    response_model=OptimizationSummary,
    summary="Get overall optimization summary",
)
async def get_optimization_summary(
    refresh: bool = Query(
        default=False,
        description="Bypass Redis cache and fetch fresh optimization data",
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
