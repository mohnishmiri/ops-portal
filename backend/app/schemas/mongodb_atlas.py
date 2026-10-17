"""Request bodies for the MongoDB Atlas module (``/api/v1/mongodb-atlas``)."""

from __future__ import annotations

import ipaddress
import re
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

PROJECT_ID_PATTERN = r"^[0-9a-fA-F]{24}$"
# Atlas cluster names: letters, digits and hyphens, up to 64 characters.
CLUSTER_NAME_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9-]{0,63}$"


def _clean_recipients(value: str | None) -> str | None:
    if value is None:
        return None
    from app.services.environment_notifications import normalize_recipients

    return normalize_recipients(value)


class PowerRequest(BaseModel):
    """Stop (pause) or start (resume) one cluster."""

    confirm_name: str | None = Field(
        None, max_length=64, description="The cluster name, typed again — required for production clusters"
    )
    reason: str | None = Field(None, max_length=500)
    notify: bool = Field(True, description="Email the requester a summary when Atlas finishes")
    notification_emails: str | None = Field(None, max_length=1000, description="Extra summary recipients")

    @field_validator("notification_emails")
    @classmethod
    def _emails(cls, value: str | None) -> str | None:
        return _clean_recipients(value)


class ConfirmRequest(BaseModel):
    confirm_name: str | None = Field(None, max_length=64)
    reason: str | None = Field(None, max_length=500)


class TierChangeRequest(ConfirmRequest):
    instance_size: str = Field(..., pattern=r"^(M|R)\d{2,3}(_NVME)?$", description="e.g. M10, M30, R40")


class SnapshotRequest(BaseModel):
    description: str = Field("On-demand snapshot from OpsPortal", min_length=1, max_length=200)
    retention_days: int = Field(7, ge=1, le=365)


class AlertAcknowledgeRequest(BaseModel):
    acknowledged_until: datetime | None = Field(
        None, description="Until when (UTC). Omit to acknowledge until the alert closes."
    )
    comment: str | None = Field(None, max_length=200)
    unacknowledge: bool = False


class DatabaseUserRole(BaseModel):
    role_name: str = Field(..., min_length=1, max_length=64)
    database_name: str = Field(..., min_length=1, max_length=64)
    collection_name: str | None = Field(None, max_length=120)


class DatabaseUserScope(BaseModel):
    name: str = Field(..., pattern=CLUSTER_NAME_PATTERN)
    type: Literal["CLUSTER", "DATA_LAKE", "STREAM"] = "CLUSTER"


class DatabaseUserCreate(BaseModel):
    """A SCRAM (username + password) database user.

    Leave ``password`` empty to have the portal generate a strong one; it is
    returned once in the response and never stored or logged.
    """

    username: str = Field(..., min_length=1, max_length=1024, pattern=r"^[A-Za-z0-9._@+-]+$")
    password: str | None = Field(None, min_length=12, max_length=256)
    roles: list[DatabaseUserRole] = Field(..., min_length=1, max_length=50)
    scopes: list[DatabaseUserScope] = Field(default_factory=list, max_length=50)
    description: str | None = Field(None, max_length=100)
    delete_after_date: datetime | None = Field(None, description="Temporary user: Atlas deletes it at this time")


class DatabaseUserUpdate(BaseModel):
    roles: list[DatabaseUserRole] | None = Field(None, min_length=1, max_length=50)
    scopes: list[DatabaseUserScope] | None = Field(None, max_length=50)
    description: str | None = Field(None, max_length=100)
    reset_password: bool = Field(False, description="Generate a new password and return it once")


class AccessListEntryCreate(BaseModel):
    entry: str = Field(..., max_length=64, description="An IPv4/IPv6 address or CIDR block")
    comment: str | None = Field(None, max_length=80)
    delete_after_date: datetime | None = Field(None, description="Temporary entry: Atlas removes it at this time")

    @field_validator("entry")
    @classmethod
    def _valid_network(cls, value: str) -> str:
        value = value.strip()
        try:
            network = ipaddress.ip_network(value, strict=False)
        except ValueError as exc:
            raise ValueError(f"'{value}' is not an IP address or CIDR block") from exc
        if network.prefixlen == 0:
            raise ValueError("0.0.0.0/0 opens the project to the whole internet; add it in Atlas if you must")
        return value


class ScheduleTarget(BaseModel):
    project_id: str = Field(..., pattern=PROJECT_ID_PATTERN)
    project_name: str | None = Field(None, max_length=200)
    cluster_name: str = Field(..., pattern=CLUSTER_NAME_PATTERN)


_NAME_RE = re.compile(r"^[\w .,:()/&+-]{1,200}$")


class _ScheduleFields(BaseModel):
    @field_validator("name", check_fields=False)
    @classmethod
    def _name(cls, value: str | None) -> str | None:
        if value is None:
            return value
        value = value.strip()
        if not _NAME_RE.match(value):
            raise ValueError("Use letters, digits, spaces and . , : ( ) / & + - in the name")
        return value

    @field_validator("stop_cron", "start_cron", check_fields=False)
    @classmethod
    def _cron(cls, value: str | None) -> str | None:
        value = (value or "").strip()
        return " ".join(value.split()) or None

    @field_validator("notification_emails", check_fields=False)
    @classmethod
    def _emails(cls, value: str | None) -> str | None:
        return _clean_recipients(value)


class ScheduleCreate(_ScheduleFields):
    name: str = Field(..., min_length=1, max_length=200)
    description: str | None = Field(None, max_length=2000)
    targets: list[ScheduleTarget] = Field(..., min_length=1, max_length=50)
    schedule_type: Literal["recurring", "one_time"] = "recurring"
    timezone: str = Field("UTC", max_length=100)
    stop_cron: str | None = Field(None, max_length=120)
    start_cron: str | None = Field(None, max_length=120)
    stop_at: datetime | None = Field(None, description="One-time: wall clock in the schedule's timezone")
    start_at: datetime | None = Field(None, description="One-time: wall clock in the schedule's timezone")
    is_enabled: bool = True
    notify_on: Literal["always", "failure", "never"] = "always"
    notification_emails: str | None = Field(None, max_length=1000)
    remind_minutes_before: int = Field(0, ge=0, le=1440)
    acknowledge_production: bool = Field(False, description="Required when any target is a production cluster")


class ScheduleUpdate(_ScheduleFields):
    name: str | None = Field(None, min_length=1, max_length=200)
    description: str | None = Field(None, max_length=2000)
    targets: list[ScheduleTarget] | None = Field(None, min_length=1, max_length=50)
    schedule_type: Literal["recurring", "one_time"] | None = None
    timezone: str | None = Field(None, max_length=100)
    stop_cron: str | None = Field(None, max_length=120)
    start_cron: str | None = Field(None, max_length=120)
    stop_at: datetime | None = None
    start_at: datetime | None = None
    is_enabled: bool | None = None
    notify_on: Literal["always", "failure", "never"] | None = None
    notification_emails: str | None = Field(None, max_length=1000)
    remind_minutes_before: int | None = Field(None, ge=0, le=1440)
    acknowledge_production: bool = False


class ScheduleLegRequest(BaseModel):
    leg: Literal["stop", "start"]


class ScheduleSkipRequest(ScheduleLegRequest):
    skip: bool = True
