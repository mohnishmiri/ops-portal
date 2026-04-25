"""
Notification API Endpoints.

SMTP email notifications for budget alerts and monthly reports.
"""

from fastapi import APIRouter, Depends

from app.auth import require_role
from app.models.auth import UserContext, UserRole
from app.models.notification import NotificationLog, NotificationRequest
from app.services.notification_service import NotificationService

router = APIRouter()


def _get_notification_service() -> NotificationService:
    return NotificationService()


@router.post(
    "/send",
    response_model=NotificationLog,
    summary="Send a notification email",
)
async def send_notification(
    request: NotificationRequest,
    user: UserContext = Depends(require_role(UserRole.ADMIN, UserRole.WRITE)),
    service: NotificationService = Depends(_get_notification_service),
) -> NotificationLog:
    """Send email notification via SMTP relay."""
    return await service.send_notification(
        notification_type=request.notification_type,
        subject=request.subject,
        recipients=request.recipients,
        body_html=request.body_html,
        body_text=request.body_text,
        sent_by=user.display_name,
    )


@router.post(
    "/budget-alert",
    response_model=NotificationLog,
    summary="Trigger budget threshold alert",
)
async def send_budget_alert(
    subscription_id: str,
    threshold_pct: float,
    user: UserContext = Depends(require_role(UserRole.ADMIN)),
    service: NotificationService = Depends(_get_notification_service),
) -> NotificationLog:
    """Send budget threshold exceeded alert."""
    return await service.send_budget_alert(
        subscription_id=subscription_id,
        threshold_pct=threshold_pct,
    )


@router.get(
    "/history",
    response_model=list[NotificationLog],
    summary="Get notification history",
)
async def get_notification_history(
    limit: int = 50,
    user: UserContext = Depends(require_role(UserRole.ADMIN)),
    service: NotificationService = Depends(_get_notification_service),
) -> list[NotificationLog]:
    """List previously sent notifications."""
    return await service.get_history(limit=limit)
