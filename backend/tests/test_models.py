"""Tests for Pydantic data models."""

from datetime import UTC, date, datetime
from decimal import Decimal

from app.models.auth import UserContext, UserRole
from app.models.cost import (
    CostQueryRequest,
    DashboardQueryRequest,
    GroupByDimension,
    TimeGranularity,
)
from app.models.optimization import (
    ConfidenceLevel,
    CostRecommendation,
    RecommendationCategory,
    RecommendationPriority,
    RecommendationStatus,
    ResourceInfo,
)


def test_cost_query_request_defaults():
    req = CostQueryRequest(
        subscription_ids=["sub-1"],
        start_date=date(2025, 1, 1),
        end_date=date(2025, 1, 31),
    )
    assert req.granularity == TimeGranularity.DAILY
    assert req.group_by == [GroupByDimension.SUBSCRIPTION]


def test_dashboard_query_request_defaults():
    req = DashboardQueryRequest(subscription_ids=["sub-1"])
    assert req.group_by == GroupByDimension.SUBSCRIPTION


def test_recommendation_model():
    rec = CostRecommendation(
        id="rec-001",
        category=RecommendationCategory.RIGHT_SIZING,
        priority=RecommendationPriority.HIGH,
        title="Downsize VM",
        description="VM is underutilised",
        resource=ResourceInfo(
            resource_id="/subscriptions/sub-1/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm1",
            resource_name="vm1",
            resource_type="Microsoft.Compute/virtualMachines",
            resource_group="rg",
            subscription_id="sub-1",
            subscription_name="Test Subscription",
            location="eastus2",
        ),
        current_monthly_cost=Decimal("300.00"),
        estimated_monthly_savings=Decimal("120.50"),
        estimated_annual_savings=Decimal("1446.00"),
        confidence=ConfidenceLevel.HIGH,
        confidence_score=92.0,
        action_required="Resize VM",
        risk_level="low",
        status=RecommendationStatus.OPEN,
        source="advisor",
        created_at=datetime.now(UTC),
    )
    assert rec.estimated_monthly_savings == Decimal("120.50")
    assert rec.confidence == ConfidenceLevel.HIGH


def test_user_context_roles():
    user = UserContext(
        user_id="u1",
        object_id="oid-1",
        email="test@example.com",
        display_name="Test User",
        roles=[UserRole.READ, UserRole.WRITE],
        raw_roles=["read", "write"],
        tenant_id="tenant-1",
    )
    assert user.has_role(UserRole.READ)
    assert user.can_write
    assert not user.is_admin
