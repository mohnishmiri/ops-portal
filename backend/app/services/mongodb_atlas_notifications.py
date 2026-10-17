"""
Emails for MongoDB Atlas stop/start operations.

Two kinds, both in the Environment Scheduler's visual language:

* **Summary** — sent once an operation reaches its final status (completed,
  partial, failed or skipped), listing every cluster and what happened to it.
  Scheduled runs go to the schedule's creator and its "also send to" list;
  manual ones to whoever started them plus any extra addresses they gave.
* **Heads-up** — ``remind_minutes_before`` a scheduled stop or start, so the
  team can skip that run from the portal if they still need the cluster.

Sending is best effort and happens in the background: a mail outage is
logged and never fails or delays an operation.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any

import structlog

from app.services.environment_notifications import _esc, format_duration, format_time, parse_recipients

logger = structlog.get_logger(__name__)

_FONT = "-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,'Helvetica Neue',Arial,sans-serif"
_MONO = "Consolas,'Courier New',monospace"

_STATUS_STYLE = {
    "completed": ("Completed", "#027a48", "#ecfdf3", "#abefc6"),
    "partial": ("Partly failed", "#b54708", "#fffaeb", "#fedf89"),
    "failed": ("Failed", "#b42318", "#fef3f2", "#fecdca"),
    "skipped": ("Skipped", "#344054", "#f2f4f7", "#d0d5dd"),
    "in_progress": ("In progress", "#175cd3", "#eff8ff", "#b2ddff"),
}
_TARGET_STATUS = {
    "completed": ("Done", "#027a48"),
    "no_change": ("Already in that state", "#667085"),
    "skipped": ("Skipped", "#667085"),
    "failed": ("Failed", "#b42318"),
    "in_progress": ("In progress", "#175cd3"),
    "pending": ("Not started", "#667085"),
}
_ACTION_LABEL = {"pause": "Stop (pause)", "resume": "Start (resume)"}
_ACTION_VERB = {"pause": "stopped", "resume": "started"}
_TRIGGER_LABEL = {"manual": "Manual", "scheduled": "Schedule", "run_now": "Schedule — run now"}


def should_email(notify_on: str | None, status: str) -> bool:
    choice = notify_on or "always"
    if choice == "never":
        return False
    if choice == "failure":
        return status in ("failed", "partial")
    return True


def _portal_url() -> str:
    from app.core.config import settings

    return f"{(getattr(settings, 'PORTAL_BASE_URL', '') or 'http://localhost:5177').rstrip('/')}/mongodb-atlas"


def _parse(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.rstrip("Z")).replace(tzinfo=None)
    except ValueError:
        return None


def _frame(*, accent: str, eyebrow: str, headline: str, sub: str, badge: str, tint: str, border: str, body: str) -> str:
    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1.0"></head>
<body style="margin:0;padding:0;background:#f2f4f7;">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#f2f4f7;padding:32px 0;font-family:{_FONT};">
<tr><td align="center">
<table width="720" cellpadding="0" cellspacing="0" style="background:#ffffff;border-radius:10px;overflow:hidden;border:1px solid #eaecf0;">
  <tr><td style="height:4px;background:{accent};font-size:0;line-height:0;">&nbsp;</td></tr>
  <tr><td style="padding:28px 32px 20px;">
    <table width="100%" cellpadding="0" cellspacing="0"><tr>
      <td style="vertical-align:top;">
        <div style="font-size:11px;font-weight:700;color:#98a2b3;text-transform:uppercase;letter-spacing:1.4px;">AT&amp;T OpsPortal &middot; {eyebrow}</div>
        <div style="margin-top:8px;font-size:22px;font-weight:700;color:#101828;">{headline}</div>
        <div style="margin-top:4px;font-size:14px;color:#475467;">{sub}</div>
      </td>
      <td style="vertical-align:top;text-align:right;">
        <span style="display:inline-block;background:{tint};border:1px solid {border};color:{accent};border-radius:999px;padding:6px 14px;font-size:12px;font-weight:700;">{badge}</span>
      </td>
    </tr></table>
  </td></tr>
  {body}
  <tr><td style="padding:0 32px 28px;">
    <a href="{_esc(_portal_url())}" style="display:inline-block;background:#246690;color:#ffffff;text-decoration:none;font-size:13px;font-weight:600;padding:10px 18px;border-radius:6px;">Open MongoDB Atlas in OpsPortal</a>
  </td></tr>
  <tr><td style="padding:18px 32px;border-top:1px solid #eaecf0;background:#f9fafb;">
    <div style="font-size:11px;color:#98a2b3;line-height:1.6;">Automated notification from AT&amp;T OpsPortal.
    Change who receives these on the schedule in OpsPortal &rarr; MongoDB Atlas &rarr; Schedules.</div>
  </td></tr>
</table>
</td></tr></table>
</body></html>"""


def _info_table(rows: list[tuple[str, str]]) -> str:
    cells = "".join(
        '<tr><td style="padding:8px 14px;font-size:12px;font-weight:600;color:#475467;width:150px;'
        f'border-bottom:1px solid #eaecf0;background:#f9fafb;">{label}</td>'
        f'<td style="padding:8px 14px;font-size:13px;color:#101828;border-bottom:1px solid #eaecf0;">{value}</td></tr>'
        for label, value in rows
        if value
    )
    return (
        '<tr><td style="padding:0 32px 24px;"><table width="100%" cellpadding="0" cellspacing="0" '
        f'style="border:1px solid #eaecf0;border-collapse:collapse;">{cells}</table></td></tr>'
    )


def _cluster_table(targets: list[dict], *, with_status: bool) -> str:
    head = (
        "padding:9px 12px;font-size:10px;font-weight:700;color:#475467;text-transform:uppercase;"
        "letter-spacing:.6px;border-bottom:1px solid #eaecf0;background:#f9fafb;text-align:left;"
    )
    cell = "padding:9px 12px;border-bottom:1px solid #eaecf0;font-size:12px;color:#344054;vertical-align:top;"
    rows = []
    for index, target in enumerate(targets[:100], start=1):
        shade = "#ffffff" if index % 2 else "#f9fafb"
        status_cells = ""
        if with_status:
            label, color = _TARGET_STATUS.get(target.get("status") or "", (target.get("status") or "—", "#344054"))
            status_cells = (
                f'<td style="{cell}font-weight:600;color:{color};white-space:nowrap;">{_esc(label)}</td>'
                f'<td style="{cell}text-align:right;white-space:nowrap;">{_esc(format_duration(target.get("duration_seconds")))}</td>'
                f'<td style="{cell}">{_esc(target.get("message") or "")}</td>'
            )
        rows.append(
            f'<tr style="background:{shade};">'
            f'<td style="{cell}font-family:{_MONO};color:#101828;">{_esc(target.get("cluster_name"))}</td>'
            f'<td style="{cell}color:#667085;">{_esc(target.get("project_name") or target.get("project_id"))}</td>'
            f"{status_cells}</tr>"
        )
    status_head = (
        f'<th style="{head}">Result</th><th style="{head}text-align:right;">Took</th><th style="{head}">Details</th>'
        if with_status
        else ""
    )
    return (
        '<tr><td style="padding:0 32px 24px;"><div style="font-size:13px;font-weight:700;color:#101828;margin-bottom:10px;">Clusters</div>'
        '<table width="100%" cellpadding="0" cellspacing="0" style="border:1px solid #eaecf0;border-collapse:collapse;">'
        f'<tr><th style="{head}">Cluster</th><th style="{head}">Atlas project</th>{status_head}</tr>'
        f"{''.join(rows)}</table></td></tr>"
    )


def render_operation_email(op: dict) -> tuple[str, str]:
    """(subject, html) for one finished operation (a plain dict of its columns)."""
    status = op.get("status") or "completed"
    title, accent, tint, border = _STATUS_STYLE.get(status, (status, "#344054", "#f9fafb", "#eaecf0"))
    action = op.get("action") or "pause"
    targets = op.get("targets") or []
    names = [t.get("cluster_name") for t in targets]
    what = op.get("schedule_name") or (names[0] if len(names) == 1 else f"{len(names)} clusters")
    outcome = {"completed": "Completed", "partial": "PARTLY FAILED", "failed": "FAILED", "skipped": "Skipped"}.get(
        status, status.title()
    )
    subject = f"[OpsPortal] {outcome}: MongoDB Atlas {_ACTION_LABEL.get(action, action).lower()} | {what}"

    tz = op.get("timezone") or "UTC"
    started = op.get("requested_at")
    finished = op.get("completed_at")
    duration = (finished - started).total_seconds() if started and finished else None
    headline = f"Clusters {_ACTION_VERB.get(action, action)}" if status == "completed" else f"{title}"
    if status == "skipped":
        headline = f"Scheduled {_ACTION_LABEL.get(action, action).lower()} skipped"
    trigger = _TRIGGER_LABEL.get(op.get("trigger") or "", op.get("trigger") or "")
    if op.get("schedule_name"):
        trigger = f"{trigger} &ldquo;{_esc(op['schedule_name'])}&rdquo;"
    requested_by = op.get("requested_by_email") or op.get("requested_by") or ""
    if requested_by.startswith("system:"):
        requested_by = "OpsPortal scheduler"

    error_block = ""
    if op.get("error_message"):
        error_block = (
            '<tr><td style="padding:0 32px 20px;"><div style="background:#fef3f2;border:1px solid #fecdca;border-radius:8px;padding:14px 16px;">'
            '<div style="font-size:11px;font-weight:700;color:#b42318;text-transform:uppercase;letter-spacing:.6px;margin-bottom:6px;">What went wrong</div>'
            f'<div style="font-size:13px;color:#7a271a;line-height:1.5;word-break:break-word;">{_esc(op["error_message"])}</div>'
            "</div></td></tr>"
        )
    body = (
        error_block
        + _info_table(
            [
                ("Outcome", f'<b style="color:{accent};">{_esc(title)}</b>'),
                ("Action", _esc(_ACTION_LABEL.get(action, action))),
                ("Triggered by", trigger),
                ("Requested by", _esc(requested_by)),
                ("Reason", _esc(op.get("reason") or "")),
                ("Started", _esc(format_time(started, tz))),
                ("Finished", _esc(format_time(finished, tz))),
                ("Duration", f"<b>{_esc(format_duration(duration))}</b>" if duration is not None else ""),
                ("Operation", f"#{op.get('id')}" if op.get("id") else ""),
            ]
        )
        + _cluster_table(targets, with_status=True)
    )
    html = _frame(
        accent=accent,
        eyebrow="MongoDB Atlas",
        headline=_esc(headline),
        sub=_esc(what),
        badge=_esc(title),
        tint=tint,
        border=border,
        body=body,
    )
    return subject, html


def render_reminder_email(schedule: dict, leg: str, run_at: datetime) -> tuple[str, str]:
    action = "pause" if leg == "stop" else "resume"
    tz = schedule.get("timezone") or "UTC"
    minutes = schedule.get("remind_minutes_before") or 0
    when = format_time(run_at, tz)
    targets = schedule.get("targets") or []
    subject = f"[OpsPortal] Heads-up: MongoDB Atlas {leg} at {when} | {schedule.get('name')}"
    note = (
        '<tr><td style="padding:0 32px 20px;"><div style="background:#eff8ff;border:1px solid #b2ddff;border-radius:8px;padding:14px 16px;'
        'font-size:13px;color:#175cd3;line-height:1.5;">'
        f"Still need {'these clusters' if len(targets) != 1 else 'this cluster'}? Open the schedule in OpsPortal and choose "
        f"<b>Skip next {leg}</b> before {_esc(when)}. Only this run is skipped; the schedule carries on afterwards."
        "</div></td></tr>"
    )
    body = (
        note
        + _info_table(
            [
                ("Schedule", _esc(schedule.get("name"))),
                ("Action", _esc(_ACTION_LABEL.get(action, action))),
                ("Runs at", f"<b>{_esc(when)}</b>"),
                ("Notice", f"{minutes} minutes"),
            ]
        )
        + _cluster_table(targets, with_status=False)
    )
    html = _frame(
        accent="#175cd3",
        eyebrow="MongoDB Atlas schedule",
        headline=_esc(f"{len(targets)} cluster{'s' if len(targets) != 1 else ''} will {leg} at {when}"),
        sub=_esc(schedule.get("name")),
        badge="Upcoming",
        tint="#eff8ff",
        border="#b2ddff",
        body=body,
    )
    return subject, html


# ── Sending ─────────────────────────────────────────────────────────────

_pending: set[asyncio.Task] = set()


async def send_email(recipients: list[str], subject: str, html: str) -> int:
    """Send to each recipient; returns how many succeeded. Never raises."""
    if not recipients:
        return 0
    try:
        from app.services.email_notification_service import EmailNotificationService

        mailer = EmailNotificationService(None)
        sent = 0
        for recipient in recipients:
            result = await mailer._send_single_email(recipient=recipient, subject=subject, html_body=html)
            sent += result.get("status") == "sent"
        logger.info("atlas_email_sent", subject=subject[:120], recipients=recipients, sent=sent)
        return sent
    except Exception as exc:
        logger.warning("atlas_email_failed", subject=subject[:120], error=str(exc)[:200])
        return 0


def _queue(recipients: list[str], subject: str, html: str) -> None:
    if not recipients:
        return
    task = asyncio.create_task(send_email(recipients, subject, html))
    _pending.add(task)
    task.add_done_callback(_pending.discard)


async def wait_for_pending_emails() -> None:
    """For tests and shutdown: let queued emails finish."""
    while _pending:
        await asyncio.gather(*list(_pending), return_exceptions=True)


def _operation_dict(op: Any) -> dict:
    return {
        "id": op.id,
        "action": op.action,
        "trigger": op.trigger,
        "status": op.status,
        "schedule_name": op.schedule_name,
        "targets": [dict(t) for t in op.targets or []],
        "reason": op.reason,
        "requested_by": op.requested_by,
        "requested_by_email": op.requested_by_email,
        "requested_at": op.requested_at,
        "completed_at": op.completed_at,
        "timezone": op.timezone,
        "error_message": op.error_message,
    }


def queue_operation_email(op: Any) -> None:
    recipients = parse_recipients(op.notification_emails)
    if not recipients:
        logger.info("atlas_operation_email_no_recipients", operation_id=op.id)
        return
    subject, html = render_operation_email(_operation_dict(op))
    _queue(recipients, subject, html)


def queue_reminder_email(schedule: Any, leg: str, run_at: datetime) -> None:
    recipients = parse_recipients(schedule.created_by_email, schedule.notification_emails)
    if not recipients:
        return
    subject, html = render_reminder_email(
        {
            "name": schedule.name,
            "timezone": schedule.timezone,
            "remind_minutes_before": schedule.remind_minutes_before,
            "targets": [dict(t) for t in schedule.targets or []],
        },
        leg,
        run_at,
    )
    _queue(recipients, subject, html)
