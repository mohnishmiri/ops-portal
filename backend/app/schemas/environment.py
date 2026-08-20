"""
Pydantic schemas for Environment Scaling & Scheduling module.
"""

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field

# ── Enums ──


class ScaleScope(str, Enum):
    NAMESPACE = "namespace"
    SELECTED = "selected"


class ScaleOperation(str, Enum):
    SCALE_UP = "scale_up"
    SCALE_DOWN = "scale_down"


class ScheduleType(str, Enum):
    ONE_TIME = "one_time"
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    CRON = "cron"


class WaitCondition(str, Enum):
    PODS_READY = "pods_ready"
    HEALTH_ENDPOINT = "health_endpoint"
    FIXED_TIME = "fixed_time"
    DEPLOYMENT_AVAILABLE = "deployment_available"
    SKIP = "skip"


class ExecutionStatus(str, Enum):
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    ROLLED_BACK = "rolled_back"


class SequenceType(str, Enum):
    STARTUP = "startup"
    SHUTDOWN = "shutdown"


# ── Scale Requests ──


class EnvironmentScaleRequest(BaseModel):
    cluster_id: str
    namespace: str
    operation: ScaleOperation
    scope: ScaleScope = ScaleScope.NAMESPACE
    deployment_names: list[str] | None = None
    replica_count: int = Field(default=1, ge=0, le=100)
    dry_run: bool = False


class EnvironmentScaleResponse(BaseModel):
    execution_id: int
    status: str
    total_deployments: int
    completed: int
    failed: int
    skipped: int
    details: list[dict]


# ── Schedule CRUD ──


class ScheduleCreate(BaseModel):
    job_name: str = Field(min_length=1, max_length=255)
    cluster_id: str
    namespace: str
    operation: ScaleOperation
    replica_count: int = Field(default=1, ge=0, le=100)
    schedule_type: ScheduleType
    cron_expression: str | None = None
    timezone: str = "UTC"
    start_date: datetime | None = None
    end_date: datetime | None = None
    is_enabled: bool = True
    retry_count: int = Field(default=3, ge=0, le=10)
    failure_notification: str | None = None
    sequence_id: int | None = None


class ScheduleUpdate(BaseModel):
    job_name: str | None = None
    operation: ScaleOperation | None = None
    replica_count: int | None = Field(default=None, ge=0, le=100)
    schedule_type: ScheduleType | None = None
    cron_expression: str | None = None
    timezone: str | None = None
    start_date: datetime | None = None
    end_date: datetime | None = None
    is_enabled: bool | None = None
    retry_count: int | None = None
    failure_notification: str | None = None
    sequence_id: int | None = None


class ScheduleResponse(BaseModel):
    id: int
    job_name: str
    cluster_id: str
    namespace: str
    operation: str
    replica_count: int
    schedule_type: str
    cron_expression: str | None
    timezone: str
    start_date: datetime | None
    end_date: datetime | None
    is_enabled: bool
    retry_count: int
    failure_notification: str | None
    sequence_id: int | None
    created_by: str
    created_by_email: str | None
    created_at: datetime
    updated_at: datetime
    last_run_at: datetime | None
    next_run_at: datetime | None
    last_run_status: str | None


# ── Sequence CRUD ──


class SequenceStep(BaseModel):
    order: int = Field(ge=1)
    deployment_name: str
    replicas: int = Field(default=1, ge=0, le=100)
    wait_condition: WaitCondition = WaitCondition.PODS_READY
    timeout_seconds: int = Field(default=600, ge=0, le=3600)
    health_endpoint: str | None = None
    retry_count: int = Field(default=3, ge=0, le=10)
    on_failure: str = "abort"  # abort or continue


class SequenceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    cluster_id: str
    namespace: str
    sequence_type: SequenceType
    steps: list[SequenceStep]
    rollback_on_failure: bool = True


class SequenceUpdate(BaseModel):
    name: str | None = None
    steps: list[SequenceStep] | None = None
    rollback_on_failure: bool | None = None


class SequenceResponse(BaseModel):
    id: int
    name: str
    cluster_id: str
    namespace: str
    sequence_type: str
    steps: list[dict]
    rollback_on_failure: bool
    created_by: str
    created_by_email: str | None
    created_at: datetime
    updated_at: datetime


# ── Sequence Execution ──


class SequenceExecuteRequest(BaseModel):
    sequence_id: int
    replica_count: int = Field(default=1, ge=0, le=100)
    dry_run: bool = False


# ── Execution History ──


class ExecutionHistoryResponse(BaseModel):
    id: int
    execution_type: str
    cluster_id: str
    namespace: str
    operation: str
    status: str
    total_deployments: int
    completed_count: int
    failed_count: int
    skipped_count: int
    replica_count: int | None
    schedule_id: int | None
    sequence_id: int | None
    step_details: list[dict] | None
    initiated_by: str
    initiated_by_email: str | None
    started_at: datetime
    completed_at: datetime | None
    duration_seconds: float | None
    error_message: str | None


# ── Environment Status ──


class EnvironmentStatusResponse(BaseModel):
    cluster_id: str
    namespace: str
    total_deployments: int
    running: int
    stopped: int
    scaling: int
    failed: int
    deployments: list[dict]
