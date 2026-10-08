"""
Email summaries for Environment Scheduler runs.

One template for every run — a manual namespace scale, a sequence started
from the Sequences tab, a scheduled run, or "Run now" — so production
support always gets the same, complete summary: outcome, what triggered it,
when it ran (in the schedule's timezone when there is one), each step's
replica change and result, and the failure reason.

Sending is best effort: a mail outage is logged and never fails the run.
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

import structlog

logger = structlog.get_logger(__name__)

NOTIFY_ALWAYS = "always"
NOTIFY_FAILURE = "failure"
NOTIFY_NEVER = "never"
NOTIFY_CHOICES = (NOTIFY_ALWAYS, NOTIFY_FAILURE, NOTIFY_NEVER)

MAX_STEP_ROWS = 60
_EMAIL_RE = re.compile(r"^[^@\s,;]+@[^@\s,;]+\.[^@\s,;]+$")


# ── Recipients ──────────────────────────────────────────────────────────


def parse_recipients(*sources: str | None) -> list[str]:
    """Addresses from comma/semicolon/space separated strings, de-duplicated
    case-insensitively in first-seen order. Invalid entries are skipped."""
    seen: dict[str, str] = {}
    for source in sources:
        for part in re.split(r"[,;\s]+", source or ""):
            address = part.strip()
            if address and _EMAIL_RE.match(address) and address.lower() not in seen:
                seen[address.lower()] = address
    return list(seen.values())


def normalize_recipients(value: str | None) -> str | None:
    """Validate a recipients field for storage; raises ValueError naming the bad entries."""
    parts = [p for p in re.split(r"[,;\s]+", value or "") if p]
    if not parts:
        return None
    invalid = [p for p in parts if not _EMAIL_RE.match(p)]
    if invalid:
        raise ValueError(f"Not a valid email address: {', '.join(invalid[:5])}")
    normalized = ", ".join(parse_recipients(value))
    if len(normalized) > 1000:
        raise ValueError("Too many notification recipients (1000 characters maximum)")
    return normalized


def should_notify(notify_on: str | None, status: str) -> bool:
    choice = notify_on or NOTIFY_ALWAYS
    if choice == NOTIFY_NEVER:
        return False
    if choice == NOTIFY_FAILURE:
        return status != "completed"
    return True


# ── Report ──────────────────────────────────────────────────────────────


@dataclass
class RunReport:
    """Everything the email says about one run."""

    status: str  # completed | failed | rolled_back
    operation: str  # scale_up | scale_down | sequence_startup | sequence_shutdown
    cluster_id: str
    namespace: str
    trigger: str  # e.g. "Started manually by a@b.com", "Schedule \"nightly\" (cron 0 20 * * 1-5)"
    name: str | None = None  # sequence or schedule name
    execution_id: int | None = None
    started_at: datetime | None = None  # naive UTC
    finished_at: datetime | None = None  # naive UTC
    duration_seconds: float | None = None
    timezone: str = "UTC"
    steps: list[dict[str, Any]] = field(default_factory=list)
    error_message: str | None = None
    portal_url: str | None = None


_STATUS_STYLE = {
    "completed": ("Completed", "#027a48", "#ecfdf3", "#abefc6"),
    "failed": ("Failed", "#b42318", "#fef3f2", "#fecdca"),
    "rolled_back": ("Failed &middot; rolled back", "#b54708", "#fffaeb", "#fedf89"),
}
_STEP_STATUS = {
    "completed": ("Completed", "#027a48"),
    "skipped": ("Skipped (already at target)", "#667085"),
    "failed": ("Failed", "#b42318"),
    "not_run": ("Not run", "#667085"),
    "pending": ("Not run", "#667085"),
    "interrupted": ("Interrupted", "#b54708"),
    "running": ("Interrupted", "#b54708"),
}
_WAIT_LABELS = {
    "pods_ready": "Pods ready",
    "health_endpoint": "Pods ready",
    "deployment_available": "Deployment available",
    "pods_terminated": "Pods stopped",
    "fixed_time": "Fixed wait",
    "skip": "No wait",
}
_OPERATION_LABELS = {
    "scale_up": "Scale up",
    "scale_down": "Scale down",
    "sequence_startup": "Startup sequence",
    "sequence_shutdown": "Shutdown sequence",
}
_FONT = "-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,'Helvetica Neue',Arial,sans-serif"
_MONO = "Consolas,'Courier New',monospace"


def _esc(value: Any) -> str:
    return (
        str(value if value is not None else "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _zone(name: str | None) -> ZoneInfo:
    try:
        return ZoneInfo(name or "UTC")
    except Exception:
        return ZoneInfo("UTC")


def format_time(value: datetime | None, timezone: str | None) -> str:
    """Naive UTC → "Oct 08, 2026 08:00 AM CDT" in the given timezone."""
    if value is None:
        return "—"
    local = value.replace(tzinfo=UTC).astimezone(_zone(timezone))
    return local.strftime("%b %d, %Y %I:%M %p ") + (local.tzname() or "UTC")


def format_duration(seconds: float | None) -> str:
    if seconds is None:
        return "—"
    total = max(0, int(round(seconds)))
    hours, rest = divmod(total, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f"{hours}h {minutes}m"
    if minutes:
        return f"{minutes}m {secs}s" if secs else f"{minutes}m"
    return f"{secs}s"


def cluster_display_name(cluster_id: str) -> str:
    return (cluster_id or "").rstrip("/").split("/")[-1] or cluster_id


def _effective_step_status(step: dict) -> str:
    status = step.get("status", "")
    # Very old executors marked never-run steps "rolled_back".
    if status == "rolled_back" and step.get("duration_seconds") is None:
        return "not_run"
    return status


def _counts(steps: list[dict]) -> dict[str, int]:
    counts = {"total": len(steps), "completed": 0, "failed": 0, "not_run": 0, "rolled_back": 0}
    for step in steps:
        status = _effective_step_status(step)
        if status in ("completed", "skipped"):
            counts["completed"] += 1
        elif status in ("failed", "interrupted", "running"):
            counts["failed"] += 1
        elif status in ("not_run", "pending"):
            counts["not_run"] += 1
        if step.get("rollback_status") == "rolled_back":
            counts["rolled_back"] += 1
    return counts


def subject_for(report: RunReport) -> str:
    label = _OPERATION_LABELS.get(report.operation, report.operation.replace("_", " ").title())
    outcome = {"completed": "Completed", "failed": "FAILED", "rolled_back": "FAILED (rolled back)"}.get(
        report.status, report.status.replace("_", " ").title()
    )
    what = f"{label} {report.name}" if report.name else label
    return f"[OpsPortal] {outcome}: {what} | {report.namespace} ({cluster_display_name(report.cluster_id)})"


def _headline(report: RunReport) -> str:
    label = _OPERATION_LABELS.get(report.operation, report.operation.replace("_", " ").title())
    verb = {"completed": "completed", "failed": "failed", "rolled_back": "failed and was rolled back"}.get(
        report.status, report.status
    )
    return f"{label} {verb}"


def _step_rows(steps: list[dict]) -> str:
    rows = []
    for index, step in enumerate(steps[:MAX_STEP_ROWS], start=1):
        status = _effective_step_status(step)
        label, color = _STEP_STATUS.get(status, (status.replace("_", " ").title() or "—", "#344054"))
        before = step.get("current_replicas")
        target = step.get("target_replicas", "")
        change = f"{_esc(before)} &rarr; <b>{_esc(target)}</b>" if before is not None else f"<b>{_esc(target)}</b>"
        wait = _WAIT_LABELS.get(step.get("wait_condition") or "", "")
        notes = []
        if step.get("error"):
            notes.append(f'<span style="color:#b42318;">{_esc(step["error"])}</span>')
        if step.get("note"):
            notes.append(_esc(step["note"]))
        if step.get("rollback_status") == "rolled_back":
            to = step.get("rolled_back_to")
            notes.append(
                f'<span style="color:#b54708;">Rolled back{f" to {_esc(to)}" if to is not None else ""}</span>'
            )
        elif step.get("rollback_status") == "rollback_failed":
            notes.append(f'<span style="color:#b42318;">Rollback failed: {_esc(step.get("rollback_error", ""))}</span>')
        shade = "#ffffff" if index % 2 else "#f9fafb"
        cell = "padding:9px 12px;border-bottom:1px solid #eaecf0;font-size:12px;color:#344054;vertical-align:top;"
        rows.append(
            f'<tr style="background:{shade};">'
            f'<td style="{cell}color:#667085;">{_esc(step.get("step") or step.get("order") or index)}</td>'
            f'<td style="{cell}font-family:{_MONO};color:#101828;word-break:break-all;">{_esc(step.get("deployment", ""))}</td>'
            f'<td style="{cell}text-align:center;white-space:nowrap;">{change}</td>'
            f'<td style="{cell}color:#667085;">{_esc(wait)}</td>'
            f'<td style="{cell}font-weight:600;color:{color};white-space:nowrap;">{label}</td>'
            f'<td style="{cell}text-align:right;white-space:nowrap;">{_esc(format_duration(step.get("duration_seconds")))}</td>'
            f'<td style="{cell}">{"<br>".join(notes)}</td>'
            "</tr>"
        )
    return "".join(rows)


def render_email(report: RunReport) -> tuple[str, str]:
    """(subject, html) for one run."""
    title, accent, tint, border = _STATUS_STYLE.get(
        report.status, (_esc(report.status), "#344054", "#f9fafb", "#eaecf0")
    )
    counts = _counts(report.steps)
    is_scale = report.operation in ("scale_up", "scale_down")
    unit = "Deployments" if is_scale else "Steps"

    def tile(value: int, label: str, color: str) -> str:
        return (
            f'<td style="width:20%;text-align:center;padding:16px 4px;border-right:1px solid #eaecf0;">'
            f'<div style="font-size:26px;font-weight:700;color:{color};line-height:1;">{value}</div>'
            f'<div style="margin-top:6px;font-size:10px;font-weight:700;color:#667085;text-transform:uppercase;letter-spacing:.8px;">{label}</div></td>'
        )

    tiles = (
        tile(counts["total"], unit, "#101828")
        + tile(counts["completed"], "Completed", "#027a48")
        + tile(counts["failed"], "Failed", "#b42318")
        + tile(counts["not_run"], "Not run", "#667085")
        + tile(counts["rolled_back"], "Rolled back", "#b54708")
    )

    def info(label: str, value: str, mono: bool = False) -> str:
        style = f"font-family:{_MONO};" if mono else ""
        return (
            '<tr><td style="padding:8px 14px;font-size:12px;font-weight:600;color:#475467;width:150px;'
            f'border-bottom:1px solid #eaecf0;background:#f9fafb;">{label}</td>'
            f'<td style="padding:8px 14px;font-size:13px;color:#101828;border-bottom:1px solid #eaecf0;{style}">{value}</td></tr>'
        )

    details = "".join(
        [
            info("Outcome", f'<b style="color:{accent};">{title}</b>'),
            info("Operation", _esc(_OPERATION_LABELS.get(report.operation, report.operation))),
            info("Name", _esc(report.name)) if report.name else "",
            info("Triggered by", _esc(report.trigger)),
            info("Cluster", _esc(cluster_display_name(report.cluster_id)), mono=True),
            info("Namespace", _esc(report.namespace), mono=True),
            info("Started", _esc(format_time(report.started_at, report.timezone))),
            info("Finished", _esc(format_time(report.finished_at, report.timezone))),
            info("Duration", f"<b>{_esc(format_duration(report.duration_seconds))}</b>"),
            info("Execution", f"#{report.execution_id}") if report.execution_id else "",
        ]
    )

    error_block = ""
    if report.error_message:
        error_block = (
            f'<tr><td style="padding:0 32px 20px;"><div style="background:#fef3f2;border:1px solid #fecdca;border-radius:8px;padding:14px 16px;">'
            f'<div style="font-size:11px;font-weight:700;color:#b42318;text-transform:uppercase;letter-spacing:.6px;margin-bottom:6px;">What went wrong</div>'
            f'<div style="font-size:13px;color:#7a271a;line-height:1.5;word-break:break-word;">{_esc(report.error_message)}</div>'
            "</div></td></tr>"
        )

    steps_block = ""
    if report.steps:
        overflow = (
            f'<p style="margin:8px 0 0;font-size:12px;color:#667085;">Showing {MAX_STEP_ROWS} of {len(report.steps)}; the rest are in History.</p>'
            if len(report.steps) > MAX_STEP_ROWS
            else ""
        )
        head = "padding:9px 12px;font-size:10px;font-weight:700;color:#475467;text-transform:uppercase;letter-spacing:.6px;border-bottom:1px solid #eaecf0;background:#f9fafb;"
        steps_block = (
            f'<tr><td style="padding:0 32px 24px;"><div style="font-size:13px;font-weight:700;color:#101828;margin-bottom:10px;">{"Deployments" if is_scale else "Steps (in run order)"}</div>'
            '<table width="100%" cellpadding="0" cellspacing="0" style="border:1px solid #eaecf0;border-collapse:collapse;">'
            f'<tr><th style="{head}text-align:left;">#</th><th style="{head}text-align:left;">Deployment</th>'
            f'<th style="{head}text-align:center;">Replicas</th><th style="{head}text-align:left;">Wait</th>'
            f'<th style="{head}text-align:left;">Status</th><th style="{head}text-align:right;">Duration</th>'
            f'<th style="{head}text-align:left;">Details</th></tr>'
            f"{_step_rows(report.steps)}</table>{overflow}</td></tr>"
        )

    button = ""
    if report.portal_url:
        button = (
            '<tr><td style="padding:0 32px 28px;">'
            f'<a href="{_esc(report.portal_url)}" style="display:inline-block;background:#246690;color:#ffffff;text-decoration:none;'
            'font-size:13px;font-weight:600;padding:10px 18px;border-radius:6px;">Open Environment Scheduler</a></td></tr>'
        )

    html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1.0"></head>
<body style="margin:0;padding:0;background:#f2f4f7;">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#f2f4f7;padding:32px 0;font-family:{_FONT};">
<tr><td align="center">
<table width="720" cellpadding="0" cellspacing="0" style="background:#ffffff;border-radius:10px;overflow:hidden;border:1px solid #eaecf0;">
  <tr><td style="height:4px;background:{accent};font-size:0;line-height:0;">&nbsp;</td></tr>
  <tr><td style="padding:28px 32px 20px;">
    <table width="100%" cellpadding="0" cellspacing="0"><tr>
      <td style="vertical-align:top;">
        <div style="font-size:11px;font-weight:700;color:#98a2b3;text-transform:uppercase;letter-spacing:1.4px;">AT&amp;T OpsPortal &middot; Environment Scheduler</div>
        <div style="margin-top:8px;font-size:22px;font-weight:700;color:#101828;">{_esc(_headline(report))}</div>
        <div style="margin-top:4px;font-size:14px;color:#475467;">{_esc(report.name or report.namespace)}</div>
      </td>
      <td style="vertical-align:top;text-align:right;">
        <span style="display:inline-block;background:{tint};border:1px solid {border};color:{accent};border-radius:999px;padding:6px 14px;font-size:12px;font-weight:700;">{title}</span>
      </td>
    </tr></table>
  </td></tr>
  <tr><td style="padding:0 32px 20px;">
    <table width="100%" cellpadding="0" cellspacing="0" style="border:1px solid #eaecf0;border-radius:8px;"><tr>{tiles}</tr></table>
  </td></tr>
  {error_block}
  <tr><td style="padding:0 32px 24px;">
    <table width="100%" cellpadding="0" cellspacing="0" style="border:1px solid #eaecf0;border-collapse:collapse;">{details}</table>
  </td></tr>
  {steps_block}
  {button}
  <tr><td style="padding:18px 32px;border-top:1px solid #eaecf0;background:#f9fafb;">
    <div style="font-size:11px;color:#98a2b3;line-height:1.6;">Automated notification from AT&amp;T OpsPortal. Times are shown in {_esc(report.timezone or "UTC")}.
    Change who receives these on the sequence or schedule in the Environment Scheduler.</div>
  </td></tr>
</table>
</td></tr></table>
</body></html>"""
    return subject_for(report), html


# Summaries are sent in the background: a slow or unreachable mail server must
# not hold a run (or the namespace lock of the schedule runner) open.
_pending: set[asyncio.Task] = set()


def queue_run_email(recipients: list[str], report: RunReport) -> None:
    if not recipients:
        return
    task = asyncio.create_task(send_run_email(recipients, report))
    _pending.add(task)
    task.add_done_callback(_pending.discard)


async def wait_for_pending_emails() -> None:
    """For tests and shutdown: let queued summaries finish."""
    while _pending:
        await asyncio.gather(*list(_pending), return_exceptions=True)


async def send_run_email(recipients: list[str], report: RunReport) -> int:
    """Email the run summary; returns how many were sent. Never raises."""
    if not recipients:
        return 0
    try:
        from app.services.email_notification_service import EmailNotificationService

        mailer = EmailNotificationService(None)
        if report.portal_url is None:
            report.portal_url = f"{mailer.portal_base_url.rstrip('/')}/env-scheduler"
        subject, html = render_email(report)
        sent = 0
        for recipient in recipients:
            result = await mailer._send_single_email(recipient=recipient, subject=subject, html_body=html)
            sent += result.get("status") == "sent"
        logger.info(
            "environment_run_email_sent",
            execution_id=report.execution_id,
            status=report.status,
            recipients=recipients,
            sent=sent,
        )
        return sent
    except Exception as exc:
        logger.warning("environment_run_email_failed", execution_id=report.execution_id, error=str(exc)[:200])
        return 0
