"""
MongoDB Atlas — start/stop schedules and the operations they create.

Stopping an Atlas cluster is a *pause*, starting it a *resume*. Atlas accepts
either at once and then takes minutes to carry it out, so every request —
manual or scheduled — becomes an :class:`AtlasOperation` row that a background
tick watches until each cluster settles. The summary email goes out when the
operation reaches its final status, so it reports what actually happened, not
just what was asked for.

Every uvicorn worker of every replica runs the ticks below, so each step that
must happen once is a compare-and-swap UPDATE:

* a due schedule leg is claimed by moving ``next_<leg>_at`` forward from the
  exact value that was read — one worker wins, the rest see zero rows;
* an operation is checked under a short lease (``lease_until``);
* a heads-up email is claimed by writing the run time it announces.

Behaviour worth knowing:

* If both legs of a schedule are due at once (the portal was down across a
  stop *and* the following start), only the later one runs — the earlier is
  recorded as skipped, because the most recent intent is the one that counts.
* "Skip next stop/start" records that run as skipped and then clears itself.
* A one-time schedule disables itself once both of its legs have run.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import structlog
from sqlalchemy import and_, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.cron import cron_trigger_from_crontab
from app.models.database import AtlasOperation, AtlasSchedule, AuditLog
from app.services.environment_scaling_service import local_to_utc, schedule_zone

logger = structlog.get_logger(__name__)

LEGS = ("stop", "start")
ACTION_FOR_LEG = {"stop": "pause", "start": "resume"}
LEG_FOR_ACTION = {action: leg for leg, action in ACTION_FOR_LEG.items()}
TERMINAL_TARGET_STATUSES = frozenset({"completed", "no_change", "skipped", "failed"})
SCHEDULER_USER = "system:atlas-scheduler"
MAX_TARGETS = 50
# Atlas refuses to pause a cluster that was resumed less than an hour ago.
MIN_STOP_AFTER_START = timedelta(minutes=60)
# A leg may fire at most this often: a cron such as "*/5 * * * *" would pause
# and resume a cluster all day.
MIN_LEG_INTERVAL = timedelta(hours=1)
LEASE = timedelta(minutes=2)
# Atlas may still report the old state for a moment after accepting a change;
# a cluster is not called settled before this.
SETTLE_GRACE = timedelta(seconds=90)


class AtlasScheduleError(ValueError):
    """A schedule that cannot be saved as given (HTTP 400)."""


def _utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


# ── Schedule timing ─────────────────────────────────────────────────────


def leg_next_run(schedule: Any, leg: str, after: datetime) -> datetime | None:
    """The leg's first run at or after ``after`` (naive UTC); None when it has none.

    A one-time leg runs at its own date and time, or never once that has passed.
    """
    if schedule.schedule_type == "one_time":
        at = getattr(schedule, f"{leg}_at")
        if at is None:
            return None
        utc = local_to_utc(at, schedule.timezone)
        return utc if utc and utc >= after else None
    expression = getattr(schedule, f"{leg}_cron")
    if not expression:
        return None
    trigger = cron_trigger_from_crontab(expression, timezone=schedule_zone(schedule.timezone))
    fire = trigger.get_next_fire_time(None, after.replace(tzinfo=UTC))
    return fire.astimezone(UTC).replace(tzinfo=None) if fire else None


def upcoming_leg_runs(schedule: Any, leg: str, count: int = 5, after: datetime | None = None) -> list[datetime]:
    runs: list[datetime] = []
    cursor = after or _utcnow()
    while len(runs) < count:
        nxt = leg_next_run(schedule, leg, cursor)
        if nxt is None or (runs and nxt <= runs[-1]):
            break
        runs.append(nxt)
        if schedule.schedule_type == "one_time":
            break
        cursor = nxt + timedelta(seconds=1)
    return runs


@dataclass
class ScheduleDraft:
    """The timing fields of a schedule, validated before they are stored."""

    schedule_type: str
    timezone: str
    stop_cron: str | None = None
    start_cron: str | None = None
    stop_at: datetime | None = None
    start_at: datetime | None = None


def validate_timing(draft: ScheduleDraft, now: datetime | None = None) -> None:
    """Raise :class:`AtlasScheduleError` for timing Atlas or the runner can't honour."""
    now = now or _utcnow()
    try:
        schedule_zone(draft.timezone)
    except Exception as exc:
        raise AtlasScheduleError(f"Unknown timezone '{draft.timezone}'") from exc

    if draft.schedule_type not in ("recurring", "one_time"):
        raise AtlasScheduleError("Schedule type must be 'recurring' or 'one_time'")

    if draft.schedule_type == "recurring":
        if not (draft.stop_cron or draft.start_cron):
            raise AtlasScheduleError("Give a stop time, a start time, or both")
        for leg in LEGS:
            expression = getattr(draft, f"{leg}_cron")
            if not expression:
                continue
            if len(expression.split()) != 5:
                raise AtlasScheduleError(
                    f"The {leg} cron '{expression}' needs five fields: minute hour day-of-month month day-of-week"
                )
            try:
                cron_trigger_from_crontab(expression, timezone=schedule_zone(draft.timezone))
            except ValueError as exc:
                raise AtlasScheduleError(f"Invalid {leg} cron '{expression}': {exc}") from exc
            runs = upcoming_leg_runs(draft, leg, count=6, after=now)
            if not runs:
                raise AtlasScheduleError(f"The {leg} cron '{expression}' never runs")
            gaps = [b - a for a, b in zip(runs, runs[1:], strict=False)]
            if gaps and min(gaps) < MIN_LEG_INTERVAL:
                raise AtlasScheduleError(
                    f"The {leg} cron '{expression}' runs more than once an hour; "
                    "a cluster takes several minutes to stop or start"
                )
    else:
        if not (draft.stop_at or draft.start_at):
            raise AtlasScheduleError("Give a stop time, a start time, or both")
        for leg in LEGS:
            at = getattr(draft, f"{leg}_at")
            if at is not None and (local_to_utc(at, draft.timezone) or now) <= now:
                raise AtlasScheduleError(f"The {leg} time {at:%Y-%m-%d %H:%M} ({draft.timezone}) is in the past")

    _check_stop_after_start(draft, now)


def _check_stop_after_start(draft: ScheduleDraft, now: datetime) -> None:
    """A stop less than an hour after a start would be refused by Atlas."""
    starts = upcoming_leg_runs(draft, "start", count=14, after=now)
    stops = upcoming_leg_runs(draft, "stop", count=14, after=now)
    for stop in stops:
        recent = [s for s in starts if s <= stop]
        if recent and stop - recent[-1] < MIN_STOP_AFTER_START:
            gap = int((stop - recent[-1]).total_seconds() // 60)
            raise AtlasScheduleError(
                f"A stop runs {gap} minutes after a start. Atlas will not pause a cluster that was "
                "resumed less than 60 minutes ago — leave at least an hour between them."
            )


def initial_next_runs(schedule: AtlasSchedule, now: datetime | None = None) -> None:
    """Set next_stop_at / next_start_at for a new or edited schedule.

    Recomputed from now, so an edit or a re-enable never fires a catch-up run.
    """
    now = now or _utcnow()
    schedule.next_stop_at = leg_next_run(schedule, "stop", now)
    schedule.next_start_at = leg_next_run(schedule, "start", now)
    schedule.stop_reminded_for = None
    schedule.start_reminded_for = None


def describe_leg(schedule: Any, leg: str) -> str:
    if schedule.schedule_type == "one_time":
        at = getattr(schedule, f"{leg}_at")
        return f"once at {at:%b %d, %Y %H:%M}" if at else ""
    return describe_cron(getattr(schedule, f"{leg}_cron") or "")


_DAY_NAMES = {
    "*": "every day",
    "1-5": "weekdays",
    "0,6": "weekends",
    "6,0": "weekends",
    "0-6": "every day",
    "1-6": "Monday to Saturday",
}
_WEEKDAY = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def describe_cron(expression: str) -> str:
    """ "0 20 * * 1-5" → "weekdays at 20:00"; anything unusual → "cron …"."""
    parts = expression.split()
    if len(parts) != 5:
        return f"cron {expression}" if expression else ""
    minute, hour, dom, month, dow = parts
    if minute.isdigit() and hour.isdigit() and dom == "*" and month == "*":
        at = f"{int(hour):02d}:{int(minute):02d}"
        if dow in _DAY_NAMES:
            return f"{_DAY_NAMES[dow]} at {at}"
        if dow.isdigit() and int(dow) <= 7:
            return f"{_WEEKDAY[int(dow)]}s at {at}"
    return f"cron {expression}"


# ── Recipients / audit ──────────────────────────────────────────────────


def recipients_of(*sources: str | None) -> str | None:
    """Comma-joined, de-duplicated addresses for ``AtlasOperation.notification_emails``."""
    from app.services.environment_notifications import parse_recipients

    joined = ", ".join(parse_recipients(*sources))
    return joined[:1000] or None


async def write_audit(
    db: AsyncSession,
    *,
    user_id: str,
    user_email: str | None,
    action: str,
    resource_id: str,
    status: str,
    details: dict,
    ip_address: str | None = None,
    commit: bool = True,
) -> None:
    """One ``audit_logs`` row for an Atlas change. Never raises."""
    db.add(
        AuditLog(
            user_id=user_id,
            user_email=user_email,
            action=action,
            resource_type="mongodb_atlas",
            resource_id=resource_id[:500],
            details={"page": "MongoDBAtlasPage", **details},
            ip_address=ip_address,
            status=status,
        )
    )
    if not commit:
        return
    try:
        await db.commit()
    except Exception as exc:
        await db.rollback()
        logger.warning("atlas_audit_write_failed", action=action, resource=resource_id, error=str(exc)[:200])


def target_key(target: dict) -> str:
    return f"{target.get('project_name') or target.get('project_id')}/{target.get('cluster_name')}"


# ── Operations ──────────────────────────────────────────────────────────


def operation_status(targets: list[dict]) -> str:
    """Final status from the per-cluster outcomes."""
    statuses = [t.get("status") for t in targets]
    succeeded = sum(s in ("completed", "no_change") for s in statuses)
    failed = sum(s == "failed" for s in statuses)
    if failed and succeeded:
        return "partial"
    if failed:
        return "failed"
    if succeeded:
        return "completed"
    return "skipped"


async def start_operation(
    db: AsyncSession,
    *,
    action: str,
    targets: list[dict],
    trigger: str,
    requested_by: str,
    requested_by_email: str | None,
    schedule: AtlasSchedule | None = None,
    reason: str | None = None,
    notify_on: str = "always",
    notification_emails: str | None = None,
    skip_reason: str | None = None,
    ip_address: str | None = None,
) -> AtlasOperation:
    """Ask Atlas to pause or resume each target and record the operation.

    Returns at once; clusters that Atlas accepted are ``in_progress`` and the
    verify tick finishes them. ``skip_reason`` records the whole run as
    skipped without calling Atlas. ``notification_emails`` is the complete
    recipient list for the summary — the requester is not added to it here.
    """
    from app.services.mongodb_atlas_service import AtlasError, get_atlas_service

    now = _utcnow()
    rows: list[dict] = []
    for target in targets:
        row = {
            "project_id": target["project_id"],
            "project_name": target.get("project_name"),
            "cluster_name": target["cluster_name"],
            "status": "pending",
            "message": None,
            "state": None,
            "started_at": None,
            "completed_at": None,
        }
        rows.append(row)

    op = AtlasOperation(
        action=action,
        trigger=trigger,
        schedule_id=schedule.id if schedule else None,
        schedule_name=schedule.name if schedule else None,
        status="in_progress",
        targets=rows,
        reason=(reason or None) and reason[:500],
        requested_by=requested_by,
        requested_by_email=requested_by_email,
        requested_at=now,
        timezone=schedule.timezone if schedule else None,
        notify_on=notify_on or "always",
        notification_emails=notification_emails,
    )

    if skip_reason:
        for row in rows:
            row.update(status="skipped", message=skip_reason, completed_at=now.isoformat())
    else:
        service = get_atlas_service()
        for row in rows:
            row["started_at"] = _utcnow().isoformat()
            try:
                outcome = await service.request_power(row["project_id"], row["cluster_name"], pause=action == "pause")
            except AtlasError as exc:
                row.update(status="failed", message=exc.user_message, completed_at=_utcnow().isoformat())
                continue
            except Exception as exc:  # network failure, bug — never lose the record
                logger.exception("atlas_power_request_crashed", cluster=row["cluster_name"])
                row.update(status="failed", message=str(exc)[:300], completed_at=_utcnow().isoformat())
                continue
            if outcome == "no_change":
                verb = "paused" if action == "pause" else "running"
                row.update(status="no_change", message=f"Already {verb}", completed_at=_utcnow().isoformat())
            else:
                row.update(status="in_progress", message="Requested — waiting for Atlas")

    op.targets = rows
    if all(r["status"] in TERMINAL_TARGET_STATUSES for r in rows):
        op.status = operation_status(rows)
        op.completed_at = _utcnow()
        op.error_message = _failure_summary(rows)

    db.add(op)
    await db.flush()

    for row in rows:
        await write_audit(
            db,
            user_id=requested_by,
            user_email=requested_by_email,
            action=f"atlas_cluster_{action}",
            resource_id=target_key(row),
            status="failure" if row["status"] == "failed" else "success",
            details={
                "feature": "cluster_power",
                "operation_id": op.id,
                "trigger": trigger,
                "schedule_id": op.schedule_id,
                "schedule_name": op.schedule_name,
                "project_id": row["project_id"],
                "cluster_name": row["cluster_name"],
                "outcome": row["status"],
                "message": row["message"],
                "reason": op.reason,
            },
            ip_address=ip_address,
            commit=False,
        )
    await db.commit()
    await db.refresh(op)

    if op.completed_at is not None:
        await _notify_finished(db, op)
    logger.info(
        "atlas_operation_started",
        operation_id=op.id,
        action=action,
        trigger=trigger,
        targets=[target_key(r) for r in rows],
        status=op.status,
    )
    return op


def _failure_summary(rows: list[dict]) -> str | None:
    failed = [f"{target_key(r)}: {r.get('message') or 'failed'}" for r in rows if r.get("status") == "failed"]
    return "; ".join(failed)[:2000] or None


async def _claim_operation_lease(db: AsyncSession, op_id: int, now: datetime) -> bool:
    claimed = await db.execute(
        update(AtlasOperation)
        .where(
            AtlasOperation.id == op_id,
            AtlasOperation.status == "in_progress",
            or_(AtlasOperation.lease_until.is_(None), AtlasOperation.lease_until < now),
        )
        .values(lease_until=now + LEASE)
        .returning(AtlasOperation.id)
        .execution_options(synchronize_session=False)
    )
    won = claimed.scalar_one_or_none() is not None
    await db.commit()
    return won


async def check_operation(db: AsyncSession, op_id: int, now: datetime | None = None) -> AtlasOperation | None:
    """Look at each in-progress cluster once; finish the operation when all settle.

    Returns the operation, or None when another worker holds it.
    """
    from app.services.mongodb_atlas_service import AtlasError, get_atlas_service

    now = now or _utcnow()
    if not await _claim_operation_lease(db, op_id, now):
        return None
    # populate_existing: sessions keep objects across commits (expire_on_commit=False).
    op = (
        await db.execute(
            select(AtlasOperation).where(AtlasOperation.id == op_id).execution_options(populate_existing=True)
        )
    ).scalar_one()
    service = get_atlas_service()
    timeout = timedelta(minutes=max(5, settings.MONGODB_ATLAS_OPERATION_TIMEOUT_MINUTES))
    want_paused = op.action == "pause"

    rows = [dict(r) for r in op.targets or []]
    for row in rows:
        if row.get("status") != "in_progress":
            continue
        started = _parse(row.get("started_at")) or op.requested_at
        try:
            cluster = await service.get_cluster(row["project_id"], row["cluster_name"], fresh=True)
        except AtlasError as exc:
            if exc.status_code == 404:
                row.update(status="failed", message="The cluster no longer exists", completed_at=now.isoformat())
            elif now - started > timeout:
                row.update(
                    status="failed", message=f"Could not confirm: {exc.user_message}", completed_at=now.isoformat()
                )
            else:
                row["message"] = f"Waiting — last check failed: {exc.user_message}"
            continue
        row["state"] = cluster.get("state")
        settled = (
            cluster.get("paused") is want_paused and cluster.get("state") == "IDLE" and now - started >= SETTLE_GRACE
        )
        if settled:
            row.update(
                status="completed",
                message="Paused" if want_paused else "Running",
                completed_at=now.isoformat(),
                duration_seconds=round((now - started).total_seconds()),
            )
        elif now - started > timeout:
            row.update(
                status="failed",
                message=(
                    f"Did not finish within {int(timeout.total_seconds() // 60)} minutes "
                    f"(Atlas state {cluster.get('state')}, paused={cluster.get('paused')})"
                ),
                completed_at=now.isoformat(),
            )
        else:
            row["message"] = f"In progress — Atlas state {cluster.get('state')}"

    op.targets = rows
    op.lease_until = None
    finished = all(r.get("status") in TERMINAL_TARGET_STATUSES for r in rows)
    if finished:
        op.status = operation_status(rows)
        op.completed_at = now
        op.error_message = _failure_summary(rows)
        await write_audit(
            db,
            user_id=op.requested_by,
            user_email=op.requested_by_email,
            action=f"atlas_cluster_{op.action}_finished",
            resource_id=", ".join(target_key(r) for r in rows),
            status={"completed": "success", "skipped": "success"}.get(op.status, "failure"),
            details={
                "feature": "cluster_power",
                "operation_id": op.id,
                "trigger": op.trigger,
                "schedule_id": op.schedule_id,
                "final_status": op.status,
                "targets": [
                    {"cluster": target_key(r), "status": r.get("status"), "message": r.get("message")} for r in rows
                ],
            },
            commit=False,
        )
    await db.commit()
    await db.refresh(op)
    if finished:
        await _notify_finished(db, op)
        await _record_schedule_outcome(db, op)
    return op


async def _record_schedule_outcome(db: AsyncSession, op: AtlasOperation) -> None:
    if op.schedule_id is None or op.trigger != "scheduled":
        return
    await db.execute(
        update(AtlasSchedule)
        .where(AtlasSchedule.id == op.schedule_id)
        .values(last_run_status=op.status)
        .execution_options(synchronize_session=False)
    )
    await db.commit()


async def _notify_finished(db: AsyncSession, op: AtlasOperation) -> None:
    """Email the summary once — whichever worker gets here first claims it."""
    from app.services.mongodb_atlas_notifications import queue_operation_email, should_email

    if not should_email(op.notify_on, op.status):
        return
    claimed = await db.execute(
        update(AtlasOperation)
        .where(AtlasOperation.id == op.id, AtlasOperation.notified_at.is_(None))
        .values(notified_at=_utcnow())
        .returning(AtlasOperation.id)
        .execution_options(synchronize_session=False)
    )
    won = claimed.scalar_one_or_none() is not None
    await db.commit()
    if won:
        queue_operation_email(op)


def _parse(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.rstrip("Z")).replace(tzinfo=None)
    except ValueError:
        return None


# ── Schedule legs ───────────────────────────────────────────────────────


def schedule_recipients(schedule: AtlasSchedule, *extra: str | None) -> str | None:
    return recipients_of(schedule.created_by_email, schedule.notification_emails, *extra)


async def run_schedule_leg(
    db: AsyncSession,
    schedule: AtlasSchedule,
    leg: str,
    *,
    trigger: str,
    requested_by: str = SCHEDULER_USER,
    requested_by_email: str | None = None,
    skip_reason: str | None = None,
    ip_address: str | None = None,
) -> AtlasOperation:
    return await start_operation(
        db,
        action=ACTION_FOR_LEG[leg],
        targets=list(schedule.targets or []),
        trigger=trigger,
        requested_by=requested_by,
        requested_by_email=requested_by_email,
        schedule=schedule,
        notify_on=schedule.notify_on,
        notification_emails=schedule_recipients(schedule, requested_by_email),
        skip_reason=skip_reason,
        ip_address=ip_address,
    )


async def _claim_leg(db: AsyncSession, schedule: AtlasSchedule, leg: str, now: datetime) -> bool:
    """Advance the leg's next run from the value just read; True for the one winner."""
    next_col = getattr(AtlasSchedule, f"next_{leg}_at")
    skip_col = getattr(AtlasSchedule, f"skip_next_{leg}")
    claimed_for = getattr(schedule, f"next_{leg}_at")
    skip = bool(getattr(schedule, f"skip_next_{leg}"))

    if schedule.schedule_type == "one_time":
        new_next = None
        other = "start" if leg == "stop" else "stop"
        still_enabled = getattr(schedule, f"next_{other}_at") is not None
    else:
        try:
            new_next = leg_next_run(schedule, leg, now + timedelta(seconds=1))
        except Exception:
            new_next = None
        # A NULL next run reads as "never due"; a recurring leg must keep one.
        new_next = new_next or now + timedelta(hours=24)
        still_enabled = True

    claimed = await db.execute(
        update(AtlasSchedule)
        .where(
            AtlasSchedule.id == schedule.id,
            AtlasSchedule.is_enabled.is_(True),
            next_col == claimed_for,
            skip_col.is_(skip),
        )
        .values(
            **{
                f"next_{leg}_at": new_next,
                f"skip_next_{leg}": False,
                f"last_{leg}_run_at": now,
            },
            is_enabled=still_enabled,
        )
        .returning(AtlasSchedule.id)
        .execution_options(synchronize_session=False)
    )
    won = claimed.scalar_one_or_none() is not None
    if not won:
        await db.rollback()
        return False
    await db.commit()
    return True


async def run_due_schedules(db: AsyncSession, now: datetime | None = None) -> list[int]:
    """Claim and start every due leg. Returns the operation ids started here."""
    now = now or _utcnow()
    due = (
        (
            await db.execute(
                select(AtlasSchedule)
                .execution_options(populate_existing=True)
                .where(
                    AtlasSchedule.is_enabled.is_(True),
                    or_(
                        and_(AtlasSchedule.next_stop_at.is_not(None), AtlasSchedule.next_stop_at <= now),
                        and_(AtlasSchedule.next_start_at.is_not(None), AtlasSchedule.next_start_at <= now),
                    ),
                )
            )
        )
        .scalars()
        .all()
    )
    started: list[int] = []
    for schedule in due:
        due_legs = sorted(
            (getattr(schedule, f"next_{leg}_at"), leg)
            for leg in LEGS
            if getattr(schedule, f"next_{leg}_at") is not None and getattr(schedule, f"next_{leg}_at") <= now
        )
        for index, (due_at, leg) in enumerate(due_legs):
            # Snapshot before the claim refreshes the row.
            skip_requested = bool(getattr(schedule, f"skip_next_{leg}"))
            superseded = index < len(due_legs) - 1
            if not await _claim_leg(db, schedule, leg, now):
                logger.info("atlas_schedule_leg_claimed_elsewhere", schedule_id=schedule.id, leg=leg)
                continue
            if superseded:
                skip_reason = f"Missed at {due_at:%Y-%m-%d %H:%M} UTC; a later scheduled run replaces it"
            elif skip_requested:
                skip_reason = f'Skipped on request ("skip next {leg}")'
            else:
                skip_reason = None
            logger.info(
                "atlas_schedule_leg_launched",
                schedule_id=schedule.id,
                schedule=schedule.name,
                leg=leg,
                due_at=due_at.isoformat(),
                skipped=bool(skip_reason),
            )
            try:
                op = await run_schedule_leg(db, schedule, leg, trigger="scheduled", skip_reason=skip_reason)
                started.append(op.id)
            except Exception as exc:
                logger.error("atlas_schedule_leg_failed", schedule_id=schedule.id, leg=leg, error=str(exc)[:300])
            await db.refresh(schedule)
    return started


async def send_due_reminders(db: AsyncSession, now: datetime | None = None) -> int:
    """Heads-up emails ``remind_minutes_before`` a leg runs. Returns how many were sent."""
    from app.services.mongodb_atlas_notifications import queue_reminder_email

    now = now or _utcnow()
    rows = (
        (
            await db.execute(
                select(AtlasSchedule)
                .execution_options(populate_existing=True)
                .where(
                    AtlasSchedule.is_enabled.is_(True),
                    AtlasSchedule.remind_minutes_before > 0,
                    AtlasSchedule.notify_on != "never",
                )
            )
        )
        .scalars()
        .all()
    )
    sent = 0
    for schedule in rows:
        for leg in LEGS:
            run_at = getattr(schedule, f"next_{leg}_at")
            if run_at is None or getattr(schedule, f"skip_next_{leg}"):
                continue
            if not (run_at - timedelta(minutes=schedule.remind_minutes_before) <= now < run_at):
                continue
            if getattr(schedule, f"{leg}_reminded_for") == run_at:
                continue
            reminded_col = getattr(AtlasSchedule, f"{leg}_reminded_for")
            claimed = await db.execute(
                update(AtlasSchedule)
                .where(
                    AtlasSchedule.id == schedule.id,
                    getattr(AtlasSchedule, f"next_{leg}_at") == run_at,
                    or_(reminded_col.is_(None), reminded_col != run_at),
                )
                .values(**{f"{leg}_reminded_for": run_at})
                .returning(AtlasSchedule.id)
                .execution_options(synchronize_session=False)
            )
            won = claimed.scalar_one_or_none() is not None
            await db.commit()
            if won:
                queue_reminder_email(schedule, leg, run_at)
                sent += 1
    return sent


# ── Background ticks (APScheduler, every worker) ────────────────────────


async def run_atlas_schedules_job() -> None:
    """Every minute: reminders, then due legs."""
    if not settings.mongodb_atlas_configured:
        return
    from app.core.database import get_db_session

    try:
        async for db in get_db_session():
            await send_due_reminders(db)
            await run_due_schedules(db)
    except Exception as exc:
        logger.error("atlas_schedule_job_failed", error=str(exc)[:300])


async def verify_atlas_operations_job() -> None:
    """Every minute: check clusters that are still stopping or starting."""
    if not settings.mongodb_atlas_configured:
        return
    from app.core.database import get_db_session

    try:
        async for db in get_db_session():
            now = _utcnow()
            ids = (
                (
                    await db.execute(
                        select(AtlasOperation.id)
                        .where(
                            AtlasOperation.status == "in_progress",
                            or_(AtlasOperation.lease_until.is_(None), AtlasOperation.lease_until < now),
                        )
                        .order_by(AtlasOperation.requested_at)
                        .limit(25)
                    )
                )
                .scalars()
                .all()
            )
            for op_id in ids:
                try:
                    await check_operation(db, op_id, now)
                except Exception as exc:
                    await db.rollback()
                    logger.error("atlas_operation_check_failed", operation_id=op_id, error=str(exc)[:300])
    except Exception as exc:
        logger.error("atlas_verify_job_failed", error=str(exc)[:300])


async def paused_since(db: AsyncSession, clusters: list[tuple[str, str]]) -> dict[tuple[str, str], datetime]:
    """When the portal last paused each cluster (naive UTC), for the ones it knows about.

    Atlas resumes a cluster by itself after 30 days paused; the page warns
    ahead of that. A cluster paused outside the portal has no entry.
    """
    wanted = set(clusters)
    if not wanted:
        return {}
    ops = (
        (
            await db.execute(
                select(AtlasOperation)
                .where(AtlasOperation.action.in_(("pause", "resume")), AtlasOperation.completed_at.is_not(None))
                .order_by(AtlasOperation.completed_at.desc())
                .limit(500)
            )
        )
        .scalars()
        .all()
    )
    found: dict[tuple[str, str], datetime] = {}
    seen: set[tuple[str, str]] = set()
    for op in ops:
        for row in op.targets or []:
            key = (row.get("project_id"), row.get("cluster_name"))
            if key not in wanted or key in seen or row.get("status") != "completed":
                continue
            seen.add(key)
            if op.action == "pause":
                found[key] = _parse(row.get("completed_at")) or op.completed_at
    return found
