"""
Pydantic data models for Azure Cost data.

These models define the API contract for cost visibility and analytics.
"""

from datetime import date, datetime
from decimal import Decimal
from enum import Enum

from pydantic import BaseModel, Field

# ── Enums ──────────────────────────────────────────────────────────────


class TimeGranularity(str, Enum):
    """Time granularity for cost aggregation."""

    DAILY = "daily"
    MONTHLY = "monthly"
    QUARTERLY = "quarterly"
    YEARLY = "yearly"


class GroupByDimension(str, Enum):
    """Dimensions for cost grouping."""

    SUBSCRIPTION = "subscription"
    RESOURCE_GROUP = "resource_group"
    RESOURCE_TYPE = "resource_type"
    SERVICE_CATEGORY = "service_category"
    METER_CATEGORY = "meter_category"
    LOCATION = "location"
    RESOURCE_ID = "resource_id"


class CostTrendDirection(str, Enum):
    """Cost trend direction."""

    UP = "up"
    DOWN = "down"
    STABLE = "stable"


# ── Request Models ─────────────────────────────────────────────────────


class CostQueryRequest(BaseModel):
    """Request model for cost queries."""

    subscription_ids: list[str] | None = Field(
        default=None,
        description="Specific subscription IDs to query. If None, queries all configured subscriptions.",
    )
    start_date: date = Field(description="Start date for cost query (inclusive)")
    end_date: date = Field(description="End date for cost query (inclusive)")
    granularity: TimeGranularity = Field(default=TimeGranularity.DAILY)
    group_by: list[GroupByDimension] = Field(
        default=[GroupByDimension.SUBSCRIPTION],
        max_length=3,
        description="Group cost data by these dimensions (max 3)",
    )
    resource_group_filter: str | None = Field(default=None, description="Filter by resource group name")
    resource_type_filter: str | None = Field(default=None, description="Filter by resource type")


class DateRangePreset(str, Enum):
    """Preset date ranges for dashboard queries."""

    LAST_7_DAYS = "last_7_days"
    LAST_30_DAYS = "last_30_days"
    CURRENT_MONTH = "current_month"
    LAST_MONTH = "last_month"
    LAST_3_MONTHS = "last_3_months"
    LAST_6_MONTHS = "last_6_months"
    LAST_12_MONTHS = "last_12_months"
    YEAR_TO_DATE = "year_to_date"


class DashboardQueryRequest(BaseModel):
    """Simplified request for dashboard views."""

    preset: DateRangePreset = Field(default=DateRangePreset.CURRENT_MONTH)
    subscription_ids: list[str] | None = None
    group_by: GroupByDimension = Field(default=GroupByDimension.SUBSCRIPTION)


# ── Response Models ────────────────────────────────────────────────────


class CostDataPoint(BaseModel):
    """Single cost data point."""

    date: date
    cost: Decimal = Field(ge=0, decimal_places=2)
    currency: str = "USD"
    group_value: str = Field(description="Value of the grouping dimension")
    group_dimension: GroupByDimension


class CostSummary(BaseModel):
    """Cost summary with aggregated totals."""

    total_cost: Decimal = Field(ge=0, decimal_places=2)
    previous_period_cost: Decimal = Field(ge=0, decimal_places=2)
    cost_change_pct: float = Field(description="Percentage change from previous period")
    trend: CostTrendDirection
    currency: str = "USD"
    period_start: date
    period_end: date
    subscription_count: int


class CostByGroup(BaseModel):
    """Cost breakdown by a grouping dimension."""

    group_dimension: GroupByDimension
    group_value: str
    total_cost: Decimal = Field(ge=0, decimal_places=2)
    percentage_of_total: float
    currency: str = "USD"


class CostTimeSeriesResponse(BaseModel):
    """Time series cost data response."""

    data_points: list[CostDataPoint]
    summary: CostSummary
    query: CostQueryRequest


class CostBreakdownResponse(BaseModel):
    """Cost breakdown by dimension response."""

    breakdown: list[CostByGroup]
    summary: CostSummary
    group_dimension: GroupByDimension


class SubscriptionCostOverview(BaseModel):
    """Cost overview for a single subscription."""

    subscription_id: str
    subscription_name: str
    current_month_cost: Decimal
    previous_month_cost: Decimal
    cost_change_pct: float
    trend: CostTrendDirection
    top_resource_groups: list[CostByGroup] = Field(max_length=10)
    top_services: list[CostByGroup] = Field(max_length=10)
    currency: str = "USD"


class MultiSubscriptionOverview(BaseModel):
    """Cost overview across all subscriptions."""

    total_cost: Decimal
    subscriptions: list[SubscriptionCostOverview]
    generated_at: datetime
    period_start: date
    period_end: date


# ── Dashboard KPI Models ──────────────────────────────────────────────


class KPIMetric(BaseModel):
    """Key Performance Indicator for leadership dashboard."""

    name: str
    value: Decimal | float
    unit: str = Field(description="e.g., USD, %, count")
    trend: CostTrendDirection
    change_pct: float
    description: str


class MonthlyCostPoint(BaseModel):
    """Aggregated monthly cost for the 6-month trend tile."""

    month: str = Field(description="YYYY-MM format")
    month_label: str = Field(description="Human-readable label e.g. 'Sep 2025'")
    total_cost: Decimal = Field(ge=0, decimal_places=2)
    non_prod_cost: Decimal = Field(default=Decimal("0"), ge=0, decimal_places=2)
    prod_cost: Decimal = Field(default=Decimal("0"), ge=0, decimal_places=2)
    subscription_breakdown: dict[str, Decimal] = Field(
        default_factory=dict,
        description="cost per subscription_id",
    )
    currency: str = "USD"


class LeadershipDashboard(BaseModel):
    """Leadership-ready dashboard response."""

    kpis: list[KPIMetric]
    cost_trend: list[CostDataPoint]
    top_spenders: list[CostByGroup]
    six_month_trend: list[MonthlyCostPoint] = Field(
        default_factory=list,
        description="Monthly aggregated cost for the last 6 months",
    )
    savings_opportunities: Decimal = Field(description="Total estimated savings")
    report_date: datetime


class LeadershipAdvisorSyncStatus(BaseModel):
    """Latest leadership snapshot sync status."""

    last_sync: str | None = None
    status: str | None = None
    triggered_by: str | None = None


class LeadershipAdvisorResource(BaseModel):
    """Resource summary for optimization recommendations."""

    resource_name: str
    resource_type: str
    resource_group: str
    subscription_id: str
    location: str


class LeadershipAdvisorRecommendation(BaseModel):
    """Optimization recommendation used by the advisor."""

    id: str
    category: str
    priority: str
    title: str
    description: str
    resource: LeadershipAdvisorResource
    current_monthly_cost: Decimal | float
    estimated_monthly_savings: Decimal | float
    estimated_annual_savings: Decimal | float
    confidence: str
    confidence_score: float
    action_required: str
    risk_level: str
    status: str
    source: str


class LeadershipAdvisorWastageResource(BaseModel):
    """Resource entry within a wastage detail category."""

    name: str | None = None
    resource_group: str | None = None
    subscription_id: str | None = None
    monthly_cost: str | None = None
    title: str | None = None
    recommendation: str | None = None
    current_sku: str | None = None
    recommended_sku: str | None = None
    priority: str | None = None
    resource_type: str | None = None
    confidence: str | None = None


class LeadershipAdvisorWastageDetail(BaseModel):
    """Wastage breakdown category for advisor context."""

    category: str
    count: int
    monthly_waste: Decimal | float
    annual_waste: Decimal | float
    resources: list[LeadershipAdvisorWastageResource] = Field(default_factory=list)


class LeadershipAdvisorWastage(BaseModel):
    """Wastage totals for advisor context."""

    total_monthly_waste: Decimal | float
    idle_vms_count: int
    unattached_disks_count: int
    disconnected_private_endpoints_count: int = 0
    orphaned_snapshots_count: int
    overprovisioned_count: int
    details: list[LeadershipAdvisorWastageDetail] = Field(default_factory=list)


class LeadershipAdvisorOptimizationSummary(BaseModel):
    """Optimization summary used as LLM context."""

    total_recommendations: int
    total_estimated_monthly_savings: Decimal | float
    total_estimated_annual_savings: Decimal | float
    wastage: LeadershipAdvisorWastage
    top_recommendations: list[LeadershipAdvisorRecommendation] = Field(default_factory=list)


class NonProdVsProdPoint(BaseModel):
    """Prod vs non-prod trend point for advisor context."""

    month_key: str
    month: str
    non_prod: Decimal | float
    prod: Decimal | float
    total: Decimal | float


class LeadershipAdvisorTrend(BaseModel):
    """Prod vs non-prod trend payload."""

    months: int
    data: list[NonProdVsProdPoint] = Field(default_factory=list)
    generated_at: str | None = None


class LeadershipAdvisorRequest(BaseModel):
    """Payload posted by the Leadership dashboard for AI advice generation."""

    dashboard: LeadershipDashboard
    optimization: LeadershipAdvisorOptimizationSummary | None = None
    trend: LeadershipAdvisorTrend | None = None
    sync_status: LeadershipAdvisorSyncStatus | None = None

    @property
    def report_date(self) -> datetime:
        """Expose the dashboard report date at the request level for legacy callers."""
        return self.dashboard.report_date


class LeadershipForecastPoint(BaseModel):
    """Combined historical and forecast point for leadership forecasting."""

    month_key: str
    month_label: str
    prod_actual: Decimal | float | None = None
    non_prod_actual: Decimal | float | None = None
    total_actual: Decimal | float | None = None
    prod_forecast: Decimal | float | None = None
    non_prod_forecast: Decimal | float | None = None
    total_forecast: Decimal | float | None = None


class LeadershipForecastResponse(BaseModel):
    """Structured Ollama-backed forecast for the Leadership dashboard."""

    source: str
    model: str
    generated_at: str
    summary: str
    historical_months: int
    forecast_months: int
    forecast_year: int
    points: list[LeadershipForecastPoint] = Field(default_factory=list)


class LeadershipAdvisorInsight(BaseModel):
    """Single actionable advisor recommendation."""

    title: str
    detail: str
    estimated_savings: str | None = None


class AzurePricingEnrichmentStatus(BaseModel):
    """Azure pricing enrichment status returned alongside advisor output."""

    status: str
    details: str
    resources_considered: int = 0


class LeadershipAdvisorResponse(BaseModel):
    """Structured output for the Leadership AI advisor."""

    source: str
    model: str
    generated_at: str
    summary: str
    focus_areas: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    opportunities: list[LeadershipAdvisorInsight] = Field(default_factory=list)
    azure_pricing: AzurePricingEnrichmentStatus
