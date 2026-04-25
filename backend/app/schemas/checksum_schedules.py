"""
Checksum Schedule Schemas

Pydantic models for checksum schedule requests and responses.
"""

from pydantic import BaseModel, Field


class ChecksumScheduleCreateRequest(BaseModel):
    """Request schema for creating a checksum schedule."""

    name: str = Field(..., min_length=1, max_length=255, description="Schedule name")
    description: str | None = Field(None, max_length=1000, description="Schedule description")
    module_type: str = Field(
        ...,
        description="Module type: 'synapse' or 'aks'",
        pattern="^(synapse|aks)$",
    )
    system: str | None = Field(None, description="System name (e.g., 'ATTCC', 'CE')")
    environment: str | None = Field(
        None,
        description="Environment name (e.g., 'prod', 'dev')",
    )
    workspace_name: str | None = Field(None, description="Synapse workspace name")
    cluster_id: str | None = Field(None, description="AKS cluster ID")
    cluster_name: str | None = Field(None, description="AKS cluster name")
    namespaces: list[str] = Field(
        default_factory=list,
        description="AKS namespaces to include",
    )
    schedule_type: str = Field(
        ...,
        description="Schedule type: 'interval' or 'cron'",
        pattern="^(interval|cron)$",
    )
    interval_hours: int | None = Field(
        default=24,
        ge=1,
        le=8760,
        description="Hours between runs (for interval-based)",
    )
    cron_expression: str | None = Field(None, description="Cron expression (for cron-based)")
    timezone: str = Field(default="UTC", description="Timezone for schedule")
    notification_emails: list[str] = Field(
        default_factory=list,
        description="Email addresses for notifications",
    )
    is_enabled: bool = Field(default=True, description="Whether schedule is active")

    class Config:
        """Pydantic config."""

        json_schema_extra = {
            "example": {
                "name": "Daily ATTCC Checksum",
                "description": "Daily checksum verification for ATTCC Synapse",
                "module_type": "synapse",
                "system": "ATTCC",
                "environment": "prod",
                "workspace_name": "attcc-workspace",
                "namesp aces": [],
                "schedule_type": "interval",
                "interval_hours": 24,
                "timezone": "America/Chicago",
                "notification_emails": ["admin@company.com"],
                "is_enabled": True,
            }
        }


class ChecksumScheduleResponse(BaseModel):
    """Response schema for checksum schedule operations."""

    success: bool = Field(..., description="Operation success status")
    schedule_id: str | None = Field(None, description="Schedule ID")
    name: str | None = Field(None, description="Schedule name")
    message: str = Field(..., description="Status message")

    class Config:
        """Pydantic config."""

        json_schema_extra = {
            "example": {
                "success": True,
                "schedule_id": "sched_abc123def456",
                "name": "Daily ATTCC Checksum",
                "message": "Schedule created successfully",
            }
        }


class ChecksumScheduleDetail(BaseModel):
    """Detailed checksum schedule information."""

    id: int | str = Field(..., description="Schedule ID")
    name: str = Field(..., description="Schedule name")
    description: str | None = Field(None, description="Schedule description")
    module_type: str = Field(..., description="Module type")
    system: str | None = Field(None, description="System name")
    environment: str | None = Field(None, description="Environment name")
    workspace_name: str | None = Field(None, description="Workspace name")
    cluster_id: str | None = Field(None, description="AKS cluster ID")
    cluster_name: str | None = Field(None, description="Cluster name")
    namespaces: list[str] = Field(default_factory=list, description="AKS namespaces")
    schedule_type: str = Field(..., description="Schedule type")
    interval_hours: int | None = Field(None, description="Interval in hours")
    cron_expression: str | None = Field(None, description="Cron expression")
    timezone: str = Field(..., description="Timezone")
    notification_emails: list[str] = Field(default_factory=list, description="Notification emails")
    is_enabled: bool = Field(..., description="Is enabled")
    last_run_at: str | None = Field(None, description="Last run timestamp")
    next_run_at: str | None = Field(None, description="Next run timestamp")
    created_at: str | None = Field(None, description="Created timestamp")
    created_by: str | None = Field(None, description="Created by user")

    class Config:
        """Pydantic config."""

        json_schema_extra = {
            "example": {
                "id": "sched_abc123def456",
                "name": "Daily ATTCC Checksum",
                "description": "Daily checksum verification",
                "module_type": "synapse",
                "system": "ATTCC",
                "environment": "prod",
                "workspace_name": "attcc-workspace",
                "cluster_name": None,
                "schedule_type": "interval",
                "interval_hours": 24,
                "cron_expression": None,
                "timezone": "America/Chicago",
                "notification_emails": ["admin@company.com"],
                "is_enabled": True,
                "last_run_at": "2024-01-15T08:00:00Z",
                "next_run_at": "2024-01-16T08:00:00Z",
                "created_at": "2024-01-01T12:00:00Z",
                "created_by": "admin@company.com",
            }
        }


class ChecksumScheduleListResponse(BaseModel):
    """Response schema for listing checksum schedules."""

    success: bool = Field(default=True, description="Operation success status")
    count: int = Field(..., description="Number of schedules")
    schedules: list[ChecksumScheduleDetail] = Field(..., description="List of schedules")

    class Config:
        """Pydantic config."""

        json_schema_extra = {
            "example": {
                "success": True,
                "count": 2,
                "schedules": [
                    {
                        "id": "sched_abc123def456",
                        "name": "Daily ATTCC Checksum",
                        "module_type": "synapse",
                        "system": "ATTCC",
                        "is_enabled": True,
                    }
                ],
            }
        }
