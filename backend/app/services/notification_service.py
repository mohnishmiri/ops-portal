"""
Notification Service — SMTP email delivery.

Sends budget alerts, monthly cost reports, and optimization summaries
via the configured SMTP relay.
"""

import smtplib
import uuid
from datetime import datetime
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import structlog

from app.core.config import settings
from app.models.notification import NotificationLog, NotificationType

logger = structlog.get_logger(__name__)


class NotificationService:
    """SMTP-based notification service."""

    async def send_notification(
        self,
        notification_type: NotificationType,
        subject: str,
        recipients: list[str],
        body_html: str,
        body_text: str | None = None,
        sent_by: str = "system",
        attachments: list[tuple[str, bytes]] | None = None,
    ) -> NotificationLog:
        """Send an email notification via SMTP relay."""
        log_id = str(uuid.uuid4())

        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = settings.SMTP_FROM_ADDRESS
        msg["To"] = ", ".join(recipients)

        if body_text:
            msg.attach(MIMEText(body_text, "plain"))
        msg.attach(MIMEText(body_html, "html"))

        # Attach files
        if attachments:
            for filename, data in attachments:
                part = MIMEBase("application", "octet-stream")
                part.set_payload(data)
                encoders.encode_base64(part)
                part.add_header("Content-Disposition", f'attachment; filename="{filename}"')
                msg.attach(part)

        status = "sent"
        error = None

        try:
            with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=30) as server:
                server.sendmail(
                    settings.SMTP_FROM_ADDRESS,
                    recipients,
                    msg.as_string(),
                )
            logger.info(
                "notification_sent",
                notification_id=log_id,
                notification_type=notification_type.value,
                recipients=recipients,
                subject=subject,
            )
        except Exception as e:
            status = "failed"
            error = str(e)
            logger.error(
                "notification_failed",
                notification_id=log_id,
                error=error,
            )

        return NotificationLog(
            id=log_id,
            notification_type=notification_type,
            recipients=recipients,
            subject=subject,
            sent_at=datetime.utcnow(),
            status=status,
            error=error,
        )

    async def send_budget_alert(
        self,
        subscription_id: str,
        threshold_pct: float,
    ) -> NotificationLog:
        """Send a budget threshold exceeded alert."""
        subject = f"⚠️ Azure Budget Alert — Subscription {subscription_id[:8]}... at {threshold_pct:.0f}%"

        body_html = f"""
        <html>
        <body style="font-family: Arial, sans-serif; max-width: 600px; margin: auto;">
            <div style="background: #d32f2f; color: white; padding: 20px; border-radius: 8px 8px 0 0;">
                <h2 style="margin: 0;">Budget Alert</h2>
            </div>
            <div style="padding: 20px; border: 1px solid #e0e0e0; border-top: none; border-radius: 0 0 8px 8px;">
                <p><strong>Subscription:</strong> {subscription_id}</p>
                <p><strong>Budget Threshold:</strong> {threshold_pct:.0f}% utilized</p>
                <p>Your Azure spending has reached the configured budget threshold.
                   Please review your cost management dashboard for details.</p>
                <a href="#" style="display: inline-block; padding: 10px 24px; background: #1976d2;
                   color: white; text-decoration: none; border-radius: 4px; margin-top: 10px;">
                    View Dashboard
                </a>
            </div>
            <p style="color: #666; font-size: 12px; margin-top: 16px;">
                Azure Cost Intelligence Portal — Automated Alert
            </p>
        </body>
        </html>
        """

        return await self.send_notification(
            notification_type=NotificationType.BUDGET_ALERT,
            subject=subject,
            recipients=settings.NOTIFICATION_RECIPIENTS,
            body_html=body_html,
        )

    async def send_monthly_cost_report(
        self,
        total_cost: float,
        savings_opportunities: float,
        pdf_bytes: bytes | None = None,
    ) -> NotificationLog:
        """Send monthly cost summary with optional PDF attachment."""
        subject = f"📊 Monthly Azure Cost Report — ${total_cost:,.2f}"

        body_html = f"""
        <html>
        <body style="font-family: Arial, sans-serif; max-width: 600px; margin: auto;">
            <div style="background: #1976d2; color: white; padding: 20px; border-radius: 8px 8px 0 0;">
                <h2 style="margin: 0;">Monthly Cost Report</h2>
            </div>
            <div style="padding: 20px; border: 1px solid #e0e0e0; border-top: none; border-radius: 0 0 8px 8px;">
                <table style="width: 100%; border-collapse: collapse;">
                    <tr>
                        <td style="padding: 12px; border-bottom: 1px solid #e0e0e0;">
                            <strong>Total Monthly Cost</strong></td>
                        <td style="padding: 12px; border-bottom: 1px solid #e0e0e0; text-align: right;
                            font-size: 1.2em; color: #333;">${total_cost:,.2f}</td>
                    </tr>
                    <tr>
                        <td style="padding: 12px; border-bottom: 1px solid #e0e0e0;">
                            <strong>Savings Opportunities</strong></td>
                        <td style="padding: 12px; border-bottom: 1px solid #e0e0e0; text-align: right;
                            font-size: 1.2em; color: #4caf50;">${savings_opportunities:,.2f}/year</td>
                    </tr>
                </table>
                <p style="margin-top: 16px;">See attached PDF for the full executive report,
                   or visit the dashboard for interactive analysis.</p>
                <a href="#" style="display: inline-block; padding: 10px 24px; background: #1976d2;
                   color: white; text-decoration: none; border-radius: 4px; margin-top: 10px;">
                    View Dashboard
                </a>
            </div>
        </body>
        </html>
        """

        attachments = None
        if pdf_bytes:
            attachments = [("Azure_Cost_Report.pdf", pdf_bytes)]

        return await self.send_notification(
            notification_type=NotificationType.MONTHLY_REPORT,
            subject=subject,
            recipients=settings.NOTIFICATION_RECIPIENTS,
            body_html=body_html,
            attachments=attachments,
        )

    async def get_history(self, limit: int = 50) -> list[NotificationLog]:
        """Get notification history (would use persistent storage in production)."""
        return []
