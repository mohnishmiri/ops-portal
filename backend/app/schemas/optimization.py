"""
Pydantic data models for FinOps optimization and recommendations.

Covers idle resources, wastage detection, reservation recommendations,
and confidence scoring.
"""

from datetime import datetime
from decimal import Decimal
from enum import Enum

from pydantic import BaseModel, Field

# ── Enums ──────────────────────────────────────────────────────────────


class RecommendationCategory(str, Enum):
    """Category of cost optimization recommendation."""

    IDLE_RESOURCES = "idle_resources"
    UNDERUTILIZED_VMS = "underutilized_vms"
    UNATTACHED_DISKS = "unattached_disks"
    ORPHANED_SNAPSHOTS = "orphaned_snapshots"
    OVERPROVISIONED_SKUS = "overprovisioned_skus"
    RESERVED_INSTANCES = "reserved_instances"
    SAVINGS_PLANS = "savings_plans"
    RIGHT_SIZING = "right_sizing"
    STORAGE_OPTIMIZATION = "storage_optimization"
    NETWORK_OPTIMIZATION = "network_optimization"


class RecommendationPriority(str, Enum):
    """Priority level for recommendations."""

    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class RecommendationStatus(str, Enum):
    """Status of a recommendation."""

    OPEN = "open"
    IN_PROGRESS = "in_progress"
    IMPLEMENTED = "implemented"
    DISMISSED = "dismissed"


class ConfidenceLevel(str, Enum):
    """Confidence level for recommendation accuracy."""

    HIGH = "high"  # >85% confidence
    MEDIUM = "medium"  # 60-85% confidence
    LOW = "low"  # <60% confidence


# ── Models ─────────────────────────────────────────────────────────────


class ResourceInfo(BaseModel):
    """Azure resource identification."""

    resource_id: str = Field(description="Full Azure resource ID")
    resource_name: str
    resource_type: str
    resource_group: str
    subscription_id: str
    subscription_name: str
    location: str
    sku: str | None = None
    tags: dict[str, str] = Field(default_factory=dict)


class UtilizationMetrics(BaseModel):
    """Resource utilization metrics."""

    cpu_avg_pct: float | None = Field(default=None, ge=0, le=100)
    cpu_max_pct: float | None = Field(default=None, ge=0, le=100)
    memory_avg_pct: float | None = Field(default=None, ge=0, le=100)
    disk_read_ops: float | None = None
    disk_write_ops: float | None = None
    network_in_bytes: float | None = None
    network_out_bytes: float | None = None
    observation_period_days: int = 14


class CostRecommendation(BaseModel):
    """Single cost optimization recommendation."""

    id: str = Field(description="Unique recommendation ID")
    category: RecommendationCategory
    priority: RecommendationPriority
    title: str
    description: str
    resource: ResourceInfo
    current_monthly_cost: Decimal = Field(ge=0)
    estimated_monthly_savings: Decimal = Field(ge=0)
    estimated_annual_savings: Decimal = Field(ge=0)
    confidence: ConfidenceLevel
    confidence_score: float = Field(ge=0, le=100, description="Numeric confidence score 0-100")
    action_required: str = Field(description="Recommended action to take")
    risk_level: str = Field(description="Risk of implementing the recommendation")
    utilization: UtilizationMetrics | None = None
    recommended_sku: str | None = Field(default=None, description="Recommended SKU for right-sizing")
    status: RecommendationStatus = RecommendationStatus.OPEN
    source: str = Field(description="Source: azure_advisor | custom_analysis | resource_graph")
    created_at: datetime
    expires_at: datetime | None = None


class WastageDetailItem(BaseModel):
    """Per-category wastage detail for the enhanced wastage tile."""

    category: str = Field(description="Category label e.g. 'Idle VMs'")
    count: int = 0
    monthly_waste: Decimal = Field(ge=0, default=Decimal("0"))
    annual_waste: Decimal = Field(ge=0, default=Decimal("0"))
    resources: list[dict] = Field(
        default_factory=list,
        description="List of affected resources [{name, resource_group, subscription_id, monthly_cost}]",
    )


class WastageSummary(BaseModel):
    """Summary of detected resource wastage."""

    total_monthly_waste: Decimal = Field(ge=0)
    total_annual_waste: Decimal = Field(ge=0)
    idle_vms_count: int = 0
    unattached_disks_count: int = 0
    orphaned_snapshots_count: int = 0
    overprovisioned_count: int = 0
    details: list["WastageDetailItem"] = Field(
        default_factory=list,
        description="Per-category wastage breakdown with resource lists",
    )
    currency: str = "USD"


class OptimizationSummary(BaseModel):
    """Overall optimization summary for dashboards."""

    total_recommendations: int
    total_estimated_monthly_savings: Decimal
    total_estimated_annual_savings: Decimal
    wastage: WastageSummary
    recommendations_by_category: dict[RecommendationCategory, int]
    recommendations_by_priority: dict[RecommendationPriority, int]
    top_recommendations: list[CostRecommendation] = Field(max_length=10)
    generated_at: datetime
    subscriptions_analyzed: int


class ReservationRecommendation(BaseModel):
    """Reserved Instance or Savings Plan recommendation."""

    resource_type: str
    sku: str
    location: str
    term_months: int = Field(description="1-year (12) or 3-year (36)")
    current_pay_as_you_go_cost: Decimal
    estimated_reservation_cost: Decimal
    estimated_savings: Decimal
    savings_percentage: float
    recommended_quantity: int
    confidence: ConfidenceLevel
    break_even_months: int


class OptimizationDashboardResponse(BaseModel):
    """Complete optimization dashboard response."""

    summary: OptimizationSummary
    recommendations: list[CostRecommendation]
    reservation_recommendations: list[ReservationRecommendation]
    generated_at: datetime
