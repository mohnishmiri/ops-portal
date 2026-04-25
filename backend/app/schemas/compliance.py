"""
Compliance & Drift Detection Schemas.

Consolidated Pydantic v2 models for the compliance module.
Replaces inline models in endpoints/compliance.py and
duplicated models in schemas/checksum_schedules.py.

Sections:
  1. Enums & Literals
  2. Synapse Pipeline Drift
  3. AKS Pod Drift
  4. Compliance Scoring & Dashboard
  5. Checksum Verification (runs / results)
  6. Checksum Schedules (CRUD)
  7. Email & Notifications
  8. Excel / CSV Export
  9. Shared request helpers
"""

from __future__ import annotations

import enum
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

# ═══════════════════════════════════════════════════════════════════════
# 1. Enums & Literals
# ═══════════════════════════════════════════════════════════════════════


class ModuleType(str, enum.Enum):
    """Module type for checksum operations."""

    SYNAPSE = "synapse"
    AKS = "aks"


class SystemName(str, enum.Enum):
    """Supported system names."""

    ATTCC = "attcc"
    CES = "ces"


class EnvironmentName(str, enum.Enum):
    """Deployment environments."""

    PROD = "prod"
    UAT = "uat"
    PERF = "perf"
    POC = "poc"


class DriftType(str, enum.Enum):
    """Types of drift detected."""

    ADDED = "added"
    MODIFIED = "modified"
    DELETED = "deleted"


class AKSDriftType(str, enum.Enum):
    """AKS-specific drift types (more granular)."""

    IMAGE_CHANGE = "image_change"
    CONFIG_DRIFT = "config_drift"
    SECRET_CHANGE = "secret_change"
    RESOURCE_CHANGE = "resource_change"


class DriftCategory(str, enum.Enum):
    """Category of AKS drift for component-level tracking."""

    CONTAINER_IMAGE = "container_image"
    ENV_VARS = "env_vars"
    VOLUMES = "volumes"
    RESOURCES = "resources"


class Severity(str, enum.Enum):
    """Drift severity levels."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ComplianceStatus(str, enum.Enum):
    """Review status for a drift event."""

    PENDING_REVIEW = "pending_review"
    ACKNOWLEDGED = "acknowledged"
    RESOLVED = "resolved"
    WAIVED = "waived"


class RunStatus(str, enum.Enum):
    """Status of a checksum verification run."""

    COMPLETED = "completed"
    FAILED = "failed"
    TIMEOUT = "timeout"
    RUNNING = "running"


class CheckResult(str, enum.Enum):
    """Individual checksum comparison result."""

    PASS = "PASS"
    FAIL = "FAIL"


class ScheduleType(str, enum.Enum):
    """Schedule types."""

    INTERVAL = "interval"
    CRON = "cron"


class ResourceType(str, enum.Enum):
    """Resource types for compliance scoring."""

    AKS_CLUSTER = "aks_cluster"
    SYNAPSE_WORKSPACE = "synapse_workspace"


class OwnerKind(str, enum.Enum):
    """Kubernetes owner reference kinds."""

    DEPLOYMENT = "Deployment"
    STATEFUL_SET = "StatefulSet"
    DAEMON_SET = "DaemonSet"
    REPLICA_SET = "ReplicaSet"
    JOB = "Job"


class ComplianceGrade(str, enum.Enum):
    """Letter grades for compliance scoring."""

    A = "A"
    B = "B"
    C = "C"
    D = "D"
    F = "F"


# ═══════════════════════════════════════════════════════════════════════
# 2. Synapse Pipeline Drift
# ═══════════════════════════════════════════════════════════════════════


class SynapsePipelineChecksumItem(BaseModel):
    """A single pipeline checksum snapshot record."""

    id: int
    snapshot_date: datetime
    subscription_id: str
    subscription_name: str | None = None
    workspace_name: str
    workspace_id: str
    pipeline_name: str
    checksum_sha256: str = Field(max_length=64)
    activities_count: int | None = None
    last_modified: datetime | None = None


class SynapseDriftDetail(BaseModel):
    """Full detail for a single Synapse pipeline drift event."""

    id: int
    detection_date: datetime
    workspace_id: str
    workspace_name: str
    pipeline_name: str
    drift_type: DriftType
    previous_checksum: str | None = None
    current_checksum: str | None = None
    previous_definition: dict[str, Any] | None = None
    current_definition: dict[str, Any] | None = None
    diff_summary: dict[str, Any] | None = None
    acknowledged: bool = False
    acknowledged_by: str | None = None
    acknowledged_at: datetime | None = None
    compliance_status: ComplianceStatus = ComplianceStatus.PENDING_REVIEW


class SynapseDriftListResponse(BaseModel):
    """Paginated list of Synapse drift events."""

    success: bool = True
    total: int
    drifts: list[SynapseDriftDetail]


class SynapseDriftSummary(BaseModel):
    """Aggregated drift summary for the Synapse tab header cards."""

    total_pipelines: int = 0
    total_drifts: int = 0
    pending_review: int = 0
    acknowledged: int = 0
    added: int = 0
    modified: int = 0
    deleted: int = 0
    by_workspace: dict[str, int] = Field(default_factory=dict)


# ═══════════════════════════════════════════════════════════════════════
# 3. AKS Pod Drift
# ═══════════════════════════════════════════════════════════════════════


class AKSPodChecksumItem(BaseModel):
    """A single AKS pod checksum snapshot record."""

    id: int
    snapshot_date: datetime
    cluster_id: str
    cluster_name: str
    namespace: str
    pod_name: str
    owner_kind: str | None = None
    owner_name: str | None = None
    checksum_sha256: str = Field(max_length=64)
    spec_checksum: str | None = None
    container_images_checksum: str | None = None
    env_vars_checksum: str | None = None
    volumes_checksum: str | None = None
    resource_limits_checksum: str | None = None
    container_images: list[dict[str, Any]] | None = None
    env_vars: list[dict[str, Any]] | None = None
    volumes: list[dict[str, Any]] | None = None
    resource_limits: dict[str, Any] | None = None


class AKSPodDriftDetail(BaseModel):
    """Full detail for a single AKS pod drift event."""

    id: int
    detection_date: datetime
    cluster_id: str
    cluster_name: str
    namespace: str
    pod_name: str
    owner_kind: str | None = None
    owner_name: str | None = None
    drift_type: AKSDriftType
    drift_category: DriftCategory | None = None
    previous_value: dict[str, Any] | None = None
    current_value: dict[str, Any] | None = None
    previous_checksum: str | None = None
    current_checksum: str | None = None
    severity: Severity = Severity.MEDIUM
    acknowledged: bool = False
    acknowledged_by: str | None = None
    acknowledged_at: datetime | None = None
    compliance_status: ComplianceStatus = ComplianceStatus.PENDING_REVIEW


class AKSPodDriftListResponse(BaseModel):
    """Paginated list of AKS pod drift events."""

    success: bool = True
    total: int
    drifts: list[AKSPodDriftDetail]


class AKSDriftSummary(BaseModel):
    """Aggregated drift summary for the AKS tab header cards."""

    total_pods: int = 0
    total_drifts: int = 0
    pending_review: int = 0
    acknowledged: int = 0
    by_severity: dict[str, int] = Field(default_factory=dict)
    by_category: dict[str, int] = Field(default_factory=dict)
    by_cluster: dict[str, int] = Field(default_factory=dict)


# ═══════════════════════════════════════════════════════════════════════
# 4. Compliance Scoring & Dashboard
# ═══════════════════════════════════════════════════════════════════════


class ComplianceScoreDetail(BaseModel):
    """Compliance score record for a single resource."""

    id: int
    score_date: datetime
    resource_type: ResourceType
    resource_id: str
    resource_name: str
    subscription_id: str | None = None
    overall_score: float = Field(ge=0, le=100)
    image_compliance_score: float = Field(ge=0, le=100)
    config_compliance_score: float = Field(ge=0, le=100)
    drift_score: float = Field(ge=0, le=100)
    total_resources: int = 0
    compliant_resources: int = 0
    drifted_resources: int = 0
    critical_issues: int = 0
    high_issues: int = 0
    medium_issues: int = 0
    low_issues: int = 0

    @property
    def grade(self) -> ComplianceGrade:
        """Compute letter grade from overall score."""
        if self.overall_score >= 90:
            return ComplianceGrade.A
        if self.overall_score >= 80:
            return ComplianceGrade.B
        if self.overall_score >= 70:
            return ComplianceGrade.C
        if self.overall_score >= 60:
            return ComplianceGrade.D
        return ComplianceGrade.F


class ComplianceScoreHistoryPoint(BaseModel):
    """One data-point in the compliance score trend chart."""

    date: str  # ISO date string for chart x-axis
    overall: float
    image: float
    config: float
    drift: float


class ComplianceDashboardResponse(BaseModel):
    """Response model for the aggregated compliance dashboard."""

    success: bool = True

    # Current overall snapshot
    overall_score: float = 0.0
    grade: str = "F"

    # Summary cards
    total_resources: int = 0
    compliant_resources: int = 0
    total_drifts: int = 0
    pending_reviews: int = 0

    # Issue severity breakdown
    critical_issues: int = 0
    high_issues: int = 0
    medium_issues: int = 0
    low_issues: int = 0

    # Score breakdown for PieChart
    score_breakdown: list[dict[str, Any]] = Field(default_factory=list)

    # 30-day trend for AreaChart
    trend: list[ComplianceScoreHistoryPoint] = Field(default_factory=list)

    # Recent activity feed
    recent_activity: list[dict[str, Any]] = Field(default_factory=list)

    # Scores by resource
    resource_scores: list[ComplianceScoreDetail] = Field(default_factory=list)


# ═══════════════════════════════════════════════════════════════════════
# 5. Checksum Verification (runs / results)
# ═══════════════════════════════════════════════════════════════════════


class ChecksumResultItem(BaseModel):
    """One row in a checksum verification run."""

    id: int
    slno: int | None = None
    pipeline_name: str
    yesterday_hash: str | None = None
    present_hash: str | None = None
    last_published_date: str | None = None
    result: CheckResult
    details: dict[str, Any] | None = None


class ChecksumRunDetail(BaseModel):
    """Full detail for a checksum verification run."""

    id: int
    created_at: datetime
    run_id: str  # UUID
    module_type: ModuleType
    system: SystemName | None = None
    environment: str | None = None
    workspace_name: str | None = None
    execution_date: str | None = None
    total_pipelines: int = 0
    passed: int = 0
    failed: int = 0
    status: RunStatus = RunStatus.COMPLETED
    results: list[ChecksumResultItem] = Field(default_factory=list)


class ChecksumRunListResponse(BaseModel):
    """Paginated list of checksum runs."""

    success: bool = True
    total: int
    runs: list[ChecksumRunDetail]


class ChecksumRunSummary(BaseModel):
    """Summary metrics for checksum runs (e.g., for charts)."""

    total_runs: int = 0
    total_passed: int = 0
    total_failed: int = 0
    by_date: list[dict[str, Any]] = Field(default_factory=list)
    by_workspace: dict[str, dict[str, int]] = Field(default_factory=dict)


class ChecksumMetricsResponse(BaseModel):
    """Aggregated checksum metrics for the metrics endpoint."""

    success: bool = True
    total_runs: int = 0
    total_pipelines_checked: int = 0
    total_passed: int = 0
    total_failed: int = 0
    pass_rate: float = 0.0
    last_run_at: datetime | None = None
    by_system: dict[str, dict[str, int]] = Field(default_factory=dict)
    by_workspace: dict[str, dict[str, int]] = Field(default_factory=dict)


# ═══════════════════════════════════════════════════════════════════════
# 6. Checksum Schedules (CRUD)
# ═══════════════════════════════════════════════════════════════════════


class ChecksumScheduleCreate(BaseModel):
    """Create a new checksum schedule."""

    name: str = Field(
        ...,
        min_length=1,
        max_length=255,
        description="Unique schedule name",
    )
    description: str | None = Field(
        None,
        max_length=1000,
        description="Optional description",
    )
    module_type: ModuleType = Field(
        ...,
        description="Module type: synapse or aks",
    )
    system: SystemName | None = Field(None, description="System: attcc or ces")
    environment: str | None = Field(
        None,
        description="Target environment (prod, uat, perf, poc)",
    )
    workspace_name: str | None = Field(None, description="Synapse workspace name")
    cluster_id: str | None = Field(None, description="AKS cluster resource ID")
    cluster_name: str | None = Field(None, description="AKS cluster display name")
    namespaces: list[str] = Field(
        default_factory=list,
        description="Namespaces to scan (AKS only)",
    )
    schedule_type: ScheduleType = Field(
        ...,
        description="Schedule type: interval or cron",
    )
    interval_hours: int = Field(
        default=24,
        ge=1,
        le=8760,
        description="Hours between runs (interval schedules)",
    )
    cron_expression: str | None = Field(
        None,
        description="Cron expression (cron schedules)",
    )
    timezone: str = Field(default="UTC", description="IANA timezone")
    notification_emails: list[str] = Field(
        default_factory=list,
        description="Email addresses for notifications",
    )
    is_enabled: bool = Field(default=True, description="Whether the schedule is active")

    @model_validator(mode="after")
    def _validate_schedule_fields(self) -> ChecksumScheduleCreate:
        """Ensure cron_expression is provided for cron schedules."""
        if self.schedule_type == ScheduleType.CRON and not self.cron_expression:
            msg = "cron_expression is required when schedule_type is 'cron'"
            raise ValueError(msg)
        if self.module_type == ModuleType.SYNAPSE and not self.workspace_name:
            msg = "workspace_name is required for synapse schedules"
            raise ValueError(msg)
        return self

    model_config = {
        "json_schema_extra": {
            "example": {
                "name": "Daily ATTCC Checksum",
                "description": "Daily checksum verification for ATTCC Synapse",
                "module_type": "synapse",
                "system": "attcc",
                "environment": "prod",
                "workspace_name": "attcc-workspace",
                "schedule_type": "interval",
                "interval_hours": 24,
                "timezone": "America/Chicago",
                "notification_emails": ["admin@company.com"],
                "is_enabled": True,
            }
        }
    }


class ChecksumScheduleUpdate(BaseModel):
    """Partial update for a checksum schedule. All fields optional."""

    name: str | None = Field(None, min_length=1, max_length=255)
    description: str | None = Field(None, max_length=1000)
    module_type: ModuleType | None = None
    system: SystemName | None = None
    environment: str | None = None
    workspace_name: str | None = None
    cluster_id: str | None = None
    cluster_name: str | None = None
    namespaces: list[str] | None = None
    schedule_type: ScheduleType | None = None
    interval_hours: int | None = Field(None, ge=1, le=8760)
    cron_expression: str | None = None
    timezone: str | None = None
    notification_emails: list[str] | None = None
    is_enabled: bool | None = None


class ChecksumScheduleResponse(BaseModel):
    """Generic response for schedule mutations (create / update / delete)."""

    success: bool = True
    schedule_id: str | None = None
    name: str | None = None
    message: str = ""


class ChecksumScheduleDetail(BaseModel):
    """Full schedule detail returned from GET / list endpoints."""

    id: int
    name: str
    description: str | None = None
    module_type: str
    system: str | None = None
    environment: str | None = None
    workspace_name: str | None = None
    cluster_id: str | None = None
    cluster_name: str | None = None
    namespaces: list[str] = Field(default_factory=list)
    schedule_type: str
    interval_hours: int | None = None
    cron_expression: str | None = None
    timezone: str = "UTC"
    notification_emails: list[str] = Field(default_factory=list)
    is_enabled: bool = True
    last_run_at: datetime | None = None
    next_run_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    created_by: str | None = None

    model_config = {"from_attributes": True}


class ChecksumScheduleListResponse(BaseModel):
    """Response for listing all schedules."""

    success: bool = True
    count: int
    schedules: list[ChecksumScheduleDetail]


class ChecksumScheduleTestResponse(BaseModel):
    """Response from executing a test run on a schedule."""

    success: bool = True
    schedule_id: str
    name: str
    last_run_at: str | None = None
    message: str = ""


# ═══════════════════════════════════════════════════════════════════════
# 7. Email & Notifications
# ═══════════════════════════════════════════════════════════════════════


class SendChecksumEmailRequest(BaseModel):
    """Send a checksum verification report email."""

    run_id: str = Field(..., description="UUID of the verification run")
    recipient_email: str = Field(..., description="Email address for the report")

    @field_validator("recipient_email")
    @classmethod
    def _validate_email(cls, v: str) -> str:
        if "@" not in v:
            msg = "Invalid email address"
            raise ValueError(msg)
        return v.strip().lower()


class SendDriftAlertRequest(BaseModel):
    """Request to send drift alert notification."""

    module_type: ModuleType
    recipient_emails: list[str] = Field(..., min_length=1)
    include_acknowledged: bool = Field(
        default=False,
        description="Include already-acknowledged drifts in the report",
    )
    severity_filter: list[Severity] | None = Field(
        None,
        description="Only include drifts of these severity levels",
    )


# ═══════════════════════════════════════════════════════════════════════
# 8. Excel / CSV Export
# ═══════════════════════════════════════════════════════════════════════


class ExcelExportRequest(BaseModel):
    """Request for audit-ready Excel export.

    Supports filtering by module, date range, severity, and status.
    The response is a StreamingResponse (.xlsx), not JSON.
    """

    module_type: ModuleType | None = Field(
        None,
        description="Filter by module type (synapse / aks). None = both.",
    )
    system: SystemName | None = Field(None, description="Filter by system")
    date_from: datetime | None = Field(None, description="Start date filter (inclusive)")
    date_to: datetime | None = Field(None, description="End date filter (inclusive)")
    severity_filter: list[Severity] | None = Field(
        None,
        description="Only include drifts of these severity levels",
    )
    status_filter: list[ComplianceStatus] | None = Field(
        None,
        description="Only include drifts with these review statuses",
    )
    include_scores: bool = Field(
        default=True,
        description="Include compliance score sheet",
    )
    include_checksum_runs: bool = Field(
        default=True,
        description="Include checksum verification runs sheet",
    )


class ExportMetadata(BaseModel):
    """Metadata returned in export response headers / JSON wrapper."""

    filename: str
    content_type: str = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    total_rows: int = 0
    file_size_bytes: int = 0
    sheet_names: list[str] = Field(default_factory=list)
    generated_at: datetime
    filters_applied: dict[str, Any] = Field(default_factory=dict)


# ═══════════════════════════════════════════════════════════════════════
# 9. Shared Request / Response Helpers
# ═══════════════════════════════════════════════════════════════════════


class AcknowledgeDriftRequest(BaseModel):
    """Acknowledge one or more drift events."""

    drift_id: int | None = Field(None, description="Single drift ID to acknowledge")
    drift_ids: list[int] | None = Field(
        None,
        description="Multiple drift IDs to acknowledge in one call",
    )
    comment: str | None = Field(
        None,
        max_length=2000,
        description="Optional acknowledgement comment",
    )

    @model_validator(mode="after")
    def _require_at_least_one_id(self) -> AcknowledgeDriftRequest:
        if not self.drift_id and not self.drift_ids:
            msg = "Provide either drift_id or drift_ids"
            raise ValueError(msg)
        return self


class CollectChecksumsRequest(BaseModel):
    """Request to collect Synapse pipeline checksums."""

    subscription_ids: list[str] | None = Field(
        None,
        description="Subscription IDs to collect from; None = all configured",
    )


class CollectPodChecksumsRequest(BaseModel):
    """Request to collect AKS pod checksums."""

    cluster_id: str = Field(..., description="Full Azure resource ID of the AKS cluster")
    namespaces: list[str] | None = Field(
        None,
        description="Namespaces to scan; None = all namespaces",
    )


class CalculateComplianceRequest(BaseModel):
    """Request to (re-)calculate a compliance score for a resource."""

    resource_type: ResourceType = Field(..., description="Type of resource")
    resource_id: str = Field(..., description="Full Azure resource ID")
    resource_name: str = Field(..., description="Display name of the resource")
    subscription_id: str = Field(..., description="Subscription ID")


class RunChecksumVerificationRequest(BaseModel):
    """Run Synapse checksum verification (bash script) for a workspace."""

    workspace_name: str = Field(..., description="Full Synapse workspace name")


class SynapseWorkspaceInfo(BaseModel):
    """Metadata for a Synapse workspace in the workspace selector."""

    name: str
    system: SystemName
    environment: str
    display_label: str | None = None


class SuccessResponse(BaseModel):
    """Generic success wrapper used by simple mutation endpoints."""

    success: bool = True
    message: str = ""
    data: dict[str, Any] | None = None


class PaginationParams(BaseModel):
    """Common pagination query parameters."""

    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=50, ge=1, le=500)
    sort_by: str = "created_at"
    sort_order: Literal["asc", "desc"] = "desc"
