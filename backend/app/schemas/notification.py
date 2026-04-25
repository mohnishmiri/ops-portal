"""
Pydantic models for notifications and reporting.
"""

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class NotificationType(str, Enum):
    """Notification types."""

    BUDGET_ALERT = "budget_alert"
    COST_ANOMALY = "cost_anomaly"
    MONTHLY_REPORT = "monthly_report"
    OPTIMIZATION_SUMMARY = "optimization_summary"
    SYSTEM_ALERT = "system_alert"


class NotificationRequest(BaseModel):
    """Request to send a notification."""

    notification_type: NotificationType
    subject: str
    recipients: list[str]
    body_html: str
    body_text: str | None = None
    priority: str = "normal"
    attachments: list[str] = Field(default_factory=list, description="File paths to attach")


class NotificationLog(BaseModel):
    """Log of sent notification."""

    id: str
    notification_type: NotificationType
    recipients: list[str]
    subject: str
    sent_at: datetime
    status: str
    error: str | None = None


class ReportType(str, Enum):
    """Report types."""

    EXECUTIVE_SUMMARY = "executive_summary"
    COST_BREAKDOWN = "cost_breakdown"
    OPTIMIZATION = "optimization"
    SUBSCRIPTION_DETAIL = "subscription_detail"


class ReportRequest(BaseModel):
    """Request to generate a report."""

    report_type: ReportType
    subscription_ids: list[str] | None = None
    include_recommendations: bool = True
    include_charts: bool = True
    title: str | None = None


class ReportMetadata(BaseModel):
    """Metadata for a generated report."""

    id: str
    report_type: ReportType
    title: str
    generated_at: datetime
    generated_by: str
    file_size_bytes: int
    download_url: str
    expires_at: datetime
