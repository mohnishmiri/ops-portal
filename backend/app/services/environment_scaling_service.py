"""
Environment Scaling & Scheduling Service.

Provides:
- Manual environment scale up / down (namespace or selected deployments)
- Scheduled auto-scaling with cron, daily, weekly, monthly, one-time triggers
- Sequence-based startup/shutdown with dependency ordering
- Execution history and audit logging
"""

import asyncio
import json
import math
from collections import Counter
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import structlog
from apscheduler.triggers.cron import CronTrigger
from kubernetes.client.rest import ApiException
from sqlalchemy import delete, desc, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.access_scope import arm_scope_clause, assert_resource_access
from app.core.cron import cron_trigger_from_crontab
from app.models.database import (
    AuditLog,
    EnvironmentExecutionHistory,
    EnvironmentSchedule,
    EnvironmentSequence,
)
from app.services import environment_notifications as notifications
from app.services.aks_operations_service import (
    AKSOperationsService,
    get_aks_operations_service,
)
from app.services.environment_notifications import RunReport, parse_recipients, should_notify

logger = structlog.get_logger(__name__)

# A run executes in the process that started it. If that replica restarts
# mid-run nothing updates the row again, so a "running" row is treated as
# abandoned once it has made no progress for longer than its current step
# could legitimately take, plus this grace.
ABANDONED_GRACE_SECONDS = 300
# Plain namespace scales have no per-step waits and finish in seconds.
ABANDONED_SCALE_SECONDS = 900
DEFAULT_STEP_TIMEOUT_SECONDS = 600
# A pod wait restarts its timeout on every newly ready pod; this caps the total.
STEP_WAIT_HARD_CAP_SECONDS = 7200
POLL_SECONDS = 5
# How long a pod wait goes without progress before it reports why, and how often.
DIAGNOSE_AFTER_SECONDS = 60

# (pods counted, pods required, diagnosis or None) — persisted for live progress.
ProgressCallback = Callable[[int, int, str | None], Awaitable[None]]


def required_ready_count(desired: int, min_ready_percent: int | None) -> int:
    """Pods that must be ready before the next step: 80% of 60 is 48."""
    percent = min(100, max(1, int(min_ready_percent or 100)))
    return max(1, math.ceil(desired * percent / 100)) if desired > 0 else 0


def _pod_not_ready_reason(pod) -> str | None:
    status = pod.status
    if status is None:
        return None
    if status.phase == "Pending":
        for cond in status.conditions or []:
            if cond.type == "PodScheduled" and cond.status == "False":
                return f"unschedulable ({(cond.message or cond.reason or 'no node fits')[:160].rstrip('.')})"
    for cs in [*(status.init_container_statuses or []), *(status.container_statuses or [])]:
        waiting = cs.state.waiting if cs.state else None
        if waiting and waiting.reason and waiting.reason not in ("ContainerCreating", "PodInitializing"):
            return waiting.reason
        terminated = cs.last_state.terminated if cs.last_state else None
        if terminated and terminated.reason in ("OOMKilled", "Error") and not cs.ready and cs.restart_count:
            return f"restarting ({terminated.reason})"
    if status.phase == "Pending":
        return "starting (pulling image / creating containers)"
    if status.phase == "Running" and any(not cs.ready for cs in status.container_statuses or []):
        return "running but failing the readiness probe"
    return None


def _diagnosis_hint(reasons: Counter) -> str:
    text = " ".join(reasons)
    if "Insufficient" in text or "Too many pods" in text or "didn't have free ports" in text:
        return (
            "The cluster has no room for more pods: check the node pool autoscaler maximum or the requested CPU/memory."
        )
    if "ImagePull" in text or "ErrImage" in text or "InvalidImageName" in text:
        return "Image cannot be pulled: check the image tag and registry access; waiting longer won't help."
    if "CrashLoopBackOff" in text or "restarting" in text:
        return "Containers are crashing: check the pod logs; waiting longer won't help."
    if "CreateContainerConfigError" in text:
        return "A referenced ConfigMap or Secret is missing or invalid."
    if "readiness probe" in text:
        return "Pods run but don't pass readiness; check the app's dependencies and probe settings."
    return ""


# Holds references so background sequence runs are not garbage-collected.
_background_runs: set[asyncio.Task] = set()


class SequenceAlreadyRunningError(Exception):
    """A sequence may only have one live execution at a time."""


class SequenceValidationError(ValueError):
    """The sequence exists but cannot be run as stored."""


class SequenceInUseError(Exception):
    """Schedules still reference the sequence."""


class ScheduleValidationError(ValueError):
    """The schedule's timing can't produce a sensible run."""


# ── Schedule timing ────────────────────────────────────────────────────
#
# start_date / end_date are wall-clock times in the schedule's timezone (what
# the form shows next to the timezone picker); next_run_at is stored in UTC.
# Daily / weekly / monthly runs are anchored to the start time — "daily from
# Oct 8 08:00 US/Central" runs at 08:00 Central every day, across DST — instead
# of "24h after the last tick", which drifted and skipped the first day.

_WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


def schedule_zone(name: str | None) -> ZoneInfo:
    try:
        return ZoneInfo(name or "UTC")
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ScheduleValidationError(f"Unknown timezone: {name}") from exc


def local_to_utc(value: datetime | None, tz_name: str | None) -> datetime | None:
    """A wall-clock time in the schedule's timezone → naive UTC."""
    if value is None:
        return None
    return value.replace(tzinfo=schedule_zone(tz_name)).astimezone(UTC).replace(tzinfo=None)


def to_schedule_local(value: Any, tz_name: str | None) -> datetime | None:
    """Parse a form/API date into wall-clock time in the schedule's timezone.
    Naive input already is; an explicit offset ("Z", "+05:30") is converted."""
    if value is None or value == "":
        return None
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ScheduleValidationError(f"Not a valid date and time: {value}") from exc
    if value.tzinfo is not None:
        return value.astimezone(schedule_zone(tz_name)).replace(tzinfo=None)
    return value


def schedule_trigger(schedule) -> CronTrigger | None:
    """The cron trigger behind a recurring schedule; None for one-time."""
    tz = schedule_zone(schedule.timezone)
    if schedule.schedule_type == "cron":
        if not schedule.cron_expression:
            raise ScheduleValidationError("A cron schedule needs a cron expression")
        try:
            return cron_trigger_from_crontab(schedule.cron_expression, timezone=tz)
        except ValueError as exc:
            raise ScheduleValidationError(f"Invalid cron expression '{schedule.cron_expression}': {exc}") from exc
    if schedule.schedule_type in ("daily", "weekly", "monthly"):
        anchor = schedule.start_date
        if anchor is None:  # no start given: the time of day it was created
            created = getattr(schedule, "created_at", None) or _utc_now()
            anchor = created.replace(tzinfo=UTC).astimezone(tz).replace(tzinfo=None)
        fields: dict[str, Any] = {"hour": anchor.hour, "minute": anchor.minute, "second": 0}
        if schedule.schedule_type == "weekly":
            fields["day_of_week"] = _WEEKDAYS[anchor.weekday()]
        elif schedule.schedule_type == "monthly":
            # The 29th–31st don't exist every month; run on the month's last day then.
            fields["day"] = anchor.day if anchor.day <= 28 else "last"
        return CronTrigger(timezone=tz, **fields)
    return None


def next_schedule_run(schedule, after: datetime) -> datetime | None:
    """First run at or after `after` (naive UTC), never before the start. One-time: its start."""
    start_utc = local_to_utc(schedule.start_date, schedule.timezone)
    if schedule.schedule_type == "one_time":
        return start_utc
    trigger = schedule_trigger(schedule)
    if trigger is None:
        return None
    base = max(after, start_utc) if start_utc else after
    fire = trigger.get_next_fire_time(None, base.replace(tzinfo=UTC))
    return fire.astimezone(UTC).replace(tzinfo=None) if fire else None


def upcoming_schedule_runs(schedule, count: int = 5, after: datetime | None = None) -> list[datetime]:
    """The next few runs (naive UTC), stopping at the end date."""
    after = after or _utc_now()
    end_utc = local_to_utc(schedule.end_date, schedule.timezone)
    runs: list[datetime] = []
    cursor = after
    while len(runs) < count:
        nxt = next_schedule_run(schedule, cursor)
        if nxt is None or (end_utc and nxt > end_utc) or (runs and nxt <= runs[-1]):
            break
        if nxt >= after or schedule.schedule_type == "one_time":
            runs.append(nxt)
        if schedule.schedule_type == "one_time":
            break
        cursor = nxt + timedelta(seconds=1)
    return runs


def describe_schedule(schedule) -> str:
    """ "Weekdays… cron 0 8 * * 1-5 (US/Central)", "Daily at 08:00 (US/Central)"."""
    tz = schedule.timezone or "UTC"
    anchor = schedule.start_date
    at = anchor.strftime("%H:%M") if anchor else None
    if schedule.schedule_type == "cron":
        return f"cron {schedule.cron_expression} ({tz})"
    if schedule.schedule_type == "daily":
        return f"Daily{f' at {at}' if at else ''} ({tz})"
    if schedule.schedule_type == "weekly":
        day = anchor.strftime("%A") + "s " if anchor else ""
        return f"Weekly{f' on {day}at {at}' if anchor else ''} ({tz})"
    if schedule.schedule_type == "monthly":
        return f"Monthly{f' on day {anchor.day} at {at}' if anchor else ''} ({tz})"
    if schedule.schedule_type == "one_time":
        return f"Once at {anchor.strftime('%b %d, %Y %H:%M') if anchor else '—'} ({tz})"
    return schedule.schedule_type


def _utc_now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _iso_z(dt: datetime) -> str:
    return dt.replace(tzinfo=None).isoformat() + "Z"


def _parse_iso(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.rstrip("Z")).replace(tzinfo=None)
    except ValueError:
        return None


def build_run_report(
    *,
    status: str,
    trigger: str,
    name: str | None,
    execution: EnvironmentExecutionHistory | None = None,
    result: dict[str, Any] | None = None,
    operation: str | None = None,
    cluster_id: str | None = None,
    namespace: str | None = None,
    timezone: str = "UTC",
    error: str | None = None,
) -> RunReport:
    """What a run summary email says, from the execution row when there is one."""
    result = result or {}
    steps = (execution.step_details if execution is not None else None) or result.get("details") or []
    return RunReport(
        status=status,
        operation=operation or (execution.operation if execution is not None else "scale_up"),
        cluster_id=cluster_id or (execution.cluster_id if execution is not None else ""),
        namespace=namespace or (execution.namespace if execution is not None else ""),
        trigger=trigger,
        name=name,
        execution_id=(execution.id if execution is not None else None) or result.get("execution_id") or None,
        started_at=execution.started_at if execution is not None else None,
        finished_at=(execution.completed_at if execution is not None else None) or _utc_now(),
        duration_seconds=(execution.duration_seconds if execution is not None else None)
        or result.get("duration_seconds"),
        timezone=timezone or "UTC",
        steps=[dict(s) for s in steps],
        error_message=error
        or (execution.error_message if execution is not None else None)
        or result.get("error")
        or None,
    )


def _stored_step(s: dict, index: int) -> dict:
    """A sequence step as saved on create and update."""
    return {
        "order": s.get("order", index + 1),
        "deployment_name": s["deployment_name"],
        "replicas": s.get("replicas", 1),
        "wait_condition": s.get("wait_condition", "pods_ready"),
        "timeout_seconds": s.get("timeout_seconds", DEFAULT_STEP_TIMEOUT_SECONDS),
        "min_ready_percent": s.get("min_ready_percent", 100),
        "health_endpoint": s.get("health_endpoint"),
        "retry_count": s.get("retry_count", 3),
        "on_failure": s.get("on_failure", "abort"),
    }


def _describe_error(exc: Exception) -> str:
    """One readable line for History: a raw ApiException is HTTP headers and JSON."""
    if isinstance(exc, ApiException):
        message = exc.reason or "Kubernetes API error"
        try:
            body = json.loads(exc.body or "{}")
            if isinstance(body, dict) and body.get("message"):
                message = body["message"]
        except (TypeError, ValueError):
            pass
        return f"Kubernetes API {exc.status}: {message}"[:500]
    return (str(exc) or exc.__class__.__name__)[:500]


class EnvironmentScalingService:
    """Handles environment-level scaling, scheduling, and sequencing."""

    def __init__(self, db: AsyncSession | None):
        self.db = db
        self._aks: AKSOperationsService | None = None

    @property
    def aks(self) -> AKSOperationsService:
        if self._aks is None:
            self._aks = get_aks_operations_service(self.db)
        return self._aks

    # ── Manual Environment Scale ──────────────────────────────────────

    async def scale_environment(
        self,
        *,
        cluster_id: str,
        namespace: str,
        operation: str,
        scope: str,
        deployment_names: list[str] | None,
        replica_count: int,
        dry_run: bool,
        user_id: str,
        user_email: str,
        execution_type: str = "manual",
        schedule_id: int | None = None,
    ) -> dict[str, Any]:
        """Scale all or selected deployments in a namespace."""
        target_replicas = 0 if operation == "scale_down" else replica_count

        # Fetch deployments
        all_deployments = await self.aks.list_deployments(cluster_id, namespace, bypass_cache=True)
        if scope == "selected" and deployment_names:
            name_set = set(deployment_names)
            targets = [d for d in all_deployments if d["name"] in name_set]
        else:
            targets = all_deployments

        if not targets:
            return {
                "execution_id": 0,
                "status": "completed",
                "total_deployments": 0,
                "completed": 0,
                "failed": 0,
                "skipped": 0,
                "details": [],
            }

        # Create execution record
        execution = EnvironmentExecutionHistory(
            execution_type=execution_type,
            cluster_id=cluster_id,
            namespace=namespace,
            operation=operation,
            status="running",
            total_deployments=len(targets),
            replica_count=target_replicas,
            schedule_id=schedule_id,
            initiated_by=user_id,
            initiated_by_email=user_email,
            started_at=datetime.now(UTC).replace(tzinfo=None),
        )
        if self.db:
            self.db.add(execution)
            await self.db.commit()
            await self.db.refresh(execution)

        if dry_run:
            details = [
                {
                    "deployment": d["name"],
                    "current_replicas": d["replicas"],
                    "target_replicas": target_replicas,
                    "status": "dry_run",
                }
                for d in targets
            ]
            if self.db and execution.id:
                execution.status = "completed"
                execution.step_details = details
                execution.completed_at = datetime.now(UTC).replace(tzinfo=None)
                execution.completed_count = len(targets)
                await self.db.commit()
            return {
                "execution_id": execution.id if execution.id else 0,
                "status": "dry_run",
                "total_deployments": len(targets),
                "completed": len(targets),
                "failed": 0,
                "skipped": 0,
                "details": details,
            }

        # Execute scaling
        completed = 0
        failed = 0
        skipped = 0
        details: list[dict] = []

        for dep in targets:
            dep_name = dep["name"]
            current = dep["replicas"]

            if current == target_replicas:
                skipped += 1
                details.append(
                    {
                        "deployment": dep_name,
                        "current_replicas": current,
                        "target_replicas": target_replicas,
                        "status": "skipped",
                    }
                )
                continue

            try:
                await self.aks.scale_deployment(
                    cluster_id=cluster_id,
                    namespace=namespace,
                    deployment_name=dep_name,
                    replicas=target_replicas,
                    user_id=user_id,
                    user_email=user_email,
                )
                completed += 1
                details.append(
                    {
                        "deployment": dep_name,
                        "current_replicas": current,
                        "target_replicas": target_replicas,
                        "status": "completed",
                    }
                )
            except Exception as exc:
                failed += 1
                details.append(
                    {
                        "deployment": dep_name,
                        "current_replicas": current,
                        "target_replicas": target_replicas,
                        "status": "failed",
                        "error": _describe_error(exc),
                    }
                )
                logger.error("env_scale_deployment_failed", deployment=dep_name, error=str(exc)[:200])

        # Finalize execution record
        final_status = "completed" if failed == 0 else "failed"
        now = _utc_now()
        duration = (now - execution.started_at).total_seconds()
        if self.db and execution.id:
            execution.status = final_status
            execution.completed_count = completed
            execution.failed_count = failed
            execution.skipped_count = skipped
            execution.step_details = details
            execution.completed_at = now
            execution.duration_seconds = duration
            if failed:
                execution.error_message = f"{failed} of {len(targets)} deployment(s) failed to scale"
            await self.db.commit()

        # Write audit log
        await self._write_audit(
            user_id=user_id,
            user_email=user_email,
            action=f"environment_{operation}",
            resource_type="environment",
            resource_id=f"{cluster_id}/{namespace}",
            status=final_status,
            details={
                "cluster_id": cluster_id,
                "namespace": namespace,
                "scope": scope,
                "target_replicas": target_replicas,
                "total": len(targets),
                "completed": completed,
                "failed": failed,
                "skipped": skipped,
            },
        )

        return {
            "execution_id": execution.id if execution.id else 0,
            "status": final_status,
            "total_deployments": len(targets),
            "completed": completed,
            "failed": failed,
            "skipped": skipped,
            "duration_seconds": round(duration, 1),
            "details": details,
        }

    # ── Sequence Execution ────────────────────────────────────────────

    async def execute_sequence(
        self,
        *,
        sequence_id: int,
        replica_count: int,
        dry_run: bool,
        user_id: str,
        user_email: str,
        execution_type: str = "sequence",
        schedule_id: int | None = None,
    ) -> dict[str, Any]:
        """Execute a startup or shutdown sequence to completion.

        Used by the scheduler and for dry runs. The API runs real executions in
        the background instead (begin_sequence_execution + launch_sequence_run)
        so a long sequence is not bound to one HTTP request.
        """
        if not self.db:
            raise ValueError("Database required for sequence execution")
        if dry_run:
            return await self._dry_run_sequence(
                sequence_id=sequence_id, replica_count=replica_count, user_id=user_id, user_email=user_email
            )

        sequence, execution = await self.begin_sequence_execution(
            sequence_id=sequence_id,
            replica_count=replica_count,
            user_id=user_id,
            user_email=user_email,
            execution_type=execution_type,
            schedule_id=schedule_id,
        )
        return await self.run_sequence_execution(sequence, execution, user_id=user_id, user_email=user_email)

    async def _load_sequence(self, sequence_id: int) -> EnvironmentSequence:
        result = await self.db.execute(select(EnvironmentSequence).where(EnvironmentSequence.id == sequence_id))
        sequence = result.scalar_one_or_none()
        if not sequence:
            raise ValueError(f"Sequence {sequence_id} not found")
        assert_resource_access(sequence.cluster_id, "write", context=f"execute_sequence {sequence_id}")
        return sequence

    @staticmethod
    def _plan_steps(sequence: EnvironmentSequence, fallback_replicas: int = 1) -> list[dict]:
        """The steps in execution order — the order shown in the designer, top to bottom.

        A deployment may appear more than once (scale to 1 early, to 50 later),
        so steps are identified by position, never by deployment name.
        """
        is_shutdown = sequence.sequence_type == "shutdown"
        ordered = sorted(sequence.steps or [], key=lambda s: s.get("order", 0))
        return [
            {
                "step": position,
                "order": step.get("order", position),
                "deployment": step.get("deployment_name", ""),
                "target_replicas": 0 if is_shutdown else step.get("replicas", fallback_replicas),
                # Scale-downs never waited; record that instead of a condition that is ignored.
                "wait_condition": "skip" if is_shutdown else step.get("wait_condition", "pods_ready"),
                "timeout_seconds": step.get("timeout_seconds", DEFAULT_STEP_TIMEOUT_SECONDS),
                "min_ready_percent": step.get("min_ready_percent") or 100,
                "on_failure": step.get("on_failure", "abort"),
                "status": "pending",
            }
            for position, step in enumerate(ordered, start=1)
        ]

    async def _dry_run_sequence(
        self, *, sequence_id: int, replica_count: int, user_id: str, user_email: str
    ) -> dict[str, Any]:
        sequence = await self._load_sequence(sequence_id)
        details = [{**step, "status": "dry_run"} for step in self._plan_steps(sequence, replica_count)]
        now = _utc_now()
        execution = EnvironmentExecutionHistory(
            execution_type="sequence",
            cluster_id=sequence.cluster_id,
            namespace=sequence.namespace,
            operation=f"sequence_{sequence.sequence_type}",
            status="completed",
            total_deployments=len(details),
            completed_count=len(details),
            sequence_id=sequence_id,
            step_details=details,
            initiated_by=user_id,
            initiated_by_email=user_email,
            started_at=now,
            completed_at=now,
            duration_seconds=0,
        )
        self.db.add(execution)
        await self.db.commit()
        await self.db.refresh(execution)
        return {
            "execution_id": execution.id,
            "status": "dry_run",
            "total_deployments": len(details),
            "completed": len(details),
            "failed": 0,
            "skipped": 0,
            "details": details,
        }

    async def begin_sequence_execution(
        self,
        *,
        sequence_id: int,
        user_id: str,
        user_email: str,
        replica_count: int = 1,
        execution_type: str = "sequence",
        schedule_id: int | None = None,
    ) -> tuple[EnvironmentSequence, EnvironmentExecutionHistory]:
        """Validate the sequence and record its execution as running, every step pending.

        Raises SequenceAlreadyRunningError while another run of the same sequence
        is live: two runs would scale the same deployments against each other.
        """
        if not self.db:
            raise ValueError("Database required for sequence execution")
        sequence = await self._load_sequence(sequence_id)
        plan = self._plan_steps(sequence, replica_count)
        if not plan:
            raise SequenceValidationError(f"Sequence '{sequence.name}' has no steps to run")

        await self._expire_abandoned_executions()
        running = (
            await self.db.execute(
                select(EnvironmentExecutionHistory)
                .where(
                    EnvironmentExecutionHistory.sequence_id == sequence_id,
                    EnvironmentExecutionHistory.status == "running",
                )
                .order_by(desc(EnvironmentExecutionHistory.started_at))
                .limit(1)
            )
        ).scalar_one_or_none()
        if running is not None:
            who = running.initiated_by_email or running.initiated_by
            raise SequenceAlreadyRunningError(
                f"Sequence '{sequence.name}' is already running (execution #{running.id}, started by {who}). "
                "Wait for it to finish before starting it again."
            )

        execution = EnvironmentExecutionHistory(
            execution_type=execution_type,
            cluster_id=sequence.cluster_id,
            namespace=sequence.namespace,
            operation=f"sequence_{sequence.sequence_type}",
            status="running",
            total_deployments=len(plan),
            replica_count=0 if sequence.sequence_type == "shutdown" else replica_count,
            sequence_id=sequence_id,
            schedule_id=schedule_id,
            step_details=plan,
            initiated_by=user_id,
            initiated_by_email=user_email,
            started_at=_utc_now(),
        )
        self.db.add(execution)
        await self.db.commit()
        await self.db.refresh(execution)
        return sequence, execution

    async def run_sequence_execution(
        self,
        sequence: EnvironmentSequence,
        execution: EnvironmentExecutionHistory,
        *,
        user_id: str,
        user_email: str,
    ) -> dict[str, Any]:
        """Run the recorded steps in order, persisting after every transition so
        History shows live progress."""
        steps = [dict(s) for s in (execution.step_details or [])]
        completed = 0
        failed = 0
        failures: list[str] = []
        abort_index: int | None = None

        async def persist() -> None:
            execution.step_details = [dict(s) for s in steps]
            execution.completed_count = completed
            execution.failed_count = failed
            await self.db.commit()

        try:
            for idx, step in enumerate(steps):
                dep_name = step.get("deployment", "")
                target = int(step.get("target_replicas") or 0)
                step_start = datetime.now(UTC)
                step["status"] = "running"
                step["started_at"] = _iso_z(step_start)
                await persist()

                try:
                    scaled = await self.aks.scale_deployment(
                        cluster_id=sequence.cluster_id,
                        namespace=sequence.namespace,
                        deployment_name=dep_name,
                        replicas=target,
                        user_id=user_id,
                        user_email=user_email,
                    )
                    # The "before" value: History shows it as 0 → 60, and rollback restores it.
                    step["current_replicas"] = (scaled or {}).get("previous_replicas")
                    step["scaled"] = True
                    wait_condition = step.get("wait_condition", "pods_ready")
                    if wait_condition == "pods_terminated":

                        async def on_stopping(remaining: int, step=step) -> None:
                            step["pods_remaining"] = remaining
                            step["last_progress_at"] = _iso_z(datetime.now(UTC))
                            await persist()

                        await self._wait_for_scale_down(
                            cluster_id=sequence.cluster_id,
                            namespace=sequence.namespace,
                            deployment_name=dep_name,
                            desired_replicas=target,
                            timeout_seconds=int(step.get("timeout_seconds") or 0),
                            on_progress=on_stopping,
                        )
                    # A fixed wait also applies after scaling to 0 ("stop X, wait 30s").
                    elif target > 0 or wait_condition == "fixed_time":

                        async def on_progress(ready: int, required: int, issue: str | None, step=step) -> None:
                            # Live "37/60 ready" in the UI; last_progress_at also tells
                            # the abandoned-run sweep this step is alive.
                            step["ready_replicas"] = ready
                            step["required_ready"] = required
                            if issue is None:
                                step["last_progress_at"] = _iso_z(datetime.now(UTC))
                                step.pop("pod_issues", None)
                            else:
                                step["pod_issues"] = issue
                            await persist()

                        reached = await self._wait_for_deployment(
                            cluster_id=sequence.cluster_id,
                            namespace=sequence.namespace,
                            deployment_name=dep_name,
                            desired_replicas=target,
                            timeout_seconds=int(step.get("timeout_seconds") or 0),
                            wait_condition=wait_condition,
                            min_ready_percent=int(step.get("min_ready_percent") or 100),
                            on_progress=on_progress,
                        )
                        if 0 < reached < target:
                            step["note"] = (
                                f"Continued with {reached}/{target} ready ({step.get('min_ready_percent')}% threshold); "
                                "the remaining pods keep starting"
                            )
                    step.pop("pod_issues", None)
                    completed += 1
                    step["status"] = "completed"
                except Exception as exc:
                    failed += 1
                    step["status"] = "failed"
                    step["error"] = _describe_error(exc)
                    failures.append(f"step {step.get('step', idx + 1)} ({dep_name}): {step['error']}")
                    logger.error("sequence_step_failed", deployment=dep_name, error=step["error"][:200])

                step["duration_seconds"] = round((datetime.now(UTC) - step_start).total_seconds(), 1)
                await persist()

                if step["status"] == "failed" and step.get("on_failure", "abort") == "abort":
                    abort_index = idx
                    for later in steps[idx + 1 :]:
                        later["status"] = "not_run"
                    break
        except asyncio.CancelledError:
            # The portal is shutting down mid-run. Say so rather than leave it "running".
            await self._finalize_interrupted(execution, steps)
            raise

        rolled_back = 0
        # Rollback undoes a startup. A failed shutdown is left as-is: restarting
        # what was already stopped is not what anyone running a shutdown wants.
        if abort_index is not None and sequence.rollback_on_failure and sequence.sequence_type != "shutdown":
            rolled_back = await self._rollback_steps(
                [s for s in steps[: abort_index + 1] if s.get("scaled")],
                cluster_id=sequence.cluster_id,
                namespace=sequence.namespace,
                user_id=user_id,
                user_email=user_email,
            )

        if failed == 0:
            status = "completed"
            error_message = None
        elif rolled_back:
            status = "rolled_back"
            error_message = f"Aborted at {failures[-1].rstrip('.')}. Rolled back {rolled_back} scaled step(s)."
        elif abort_index is not None:
            status = "failed"
            error_message = f"Aborted at {failures[-1]}"
        else:
            status = "failed"
            error_message = (
                f"{failed} step(s) failed; the sequence continued because they are set to "
                f"'Continue on failure'. First failure: {failures[0]}"
            )

        now = _utc_now()
        execution.status = status
        execution.error_message = error_message[:2000] if error_message else None
        execution.completed_count = completed
        execution.failed_count = failed
        execution.skipped_count = 0
        execution.step_details = [dict(s) for s in steps]
        execution.completed_at = now
        execution.duration_seconds = (now - execution.started_at).total_seconds()
        await self.db.commit()

        not_run = sum(1 for s in steps if s.get("status") == "not_run")
        await self._write_audit(
            user_id=user_id,
            user_email=user_email,
            action="sequence_execution_finished",
            resource_type="environment_sequence",
            resource_id=str(sequence.id),
            status=status,
            details={
                "name": sequence.name,
                "execution_id": execution.id,
                "namespace": sequence.namespace,
                "total": len(steps),
                "completed": completed,
                "failed": failed,
                "not_run": not_run,
                "rolled_back": rolled_back,
            },
        )

        # Scheduled runs are reported by finish_scheduled_job (schedule recipients).
        if execution.schedule_id is None:
            await self._email_run_summary(
                recipients=parse_recipients(user_email, sequence.notification_emails),
                notify_on=sequence.notify_on,
                status=status,
                execution=execution,
                trigger=f"Started manually by {user_email or user_id}",
                name=sequence.name,
            )

        return {
            "execution_id": execution.id,
            "status": status,
            "total_deployments": len(steps),
            "completed": completed,
            "failed": failed,
            "skipped": 0,
            "not_run": not_run,
            "duration_seconds": round(execution.duration_seconds, 1),
            "error": error_message or "",
            "details": steps,
        }

    @staticmethod
    def execution_started_result(execution: EnvironmentExecutionHistory) -> dict[str, Any]:
        """Response for a run that has just been launched in the background."""
        return {
            "execution_id": execution.id,
            "status": "running",
            "total_deployments": execution.total_deployments,
            "completed": 0,
            "failed": 0,
            "skipped": 0,
            "details": execution.step_details or [],
        }

    async def _finalize_interrupted(self, execution: EnvironmentExecutionHistory, steps: list[dict]) -> None:
        try:
            for s in steps:
                if s.get("status") == "running":
                    s["status"] = "interrupted"
                elif s.get("status") == "pending":
                    s["status"] = "not_run"
            now = _utc_now()
            execution.status = "failed"
            execution.error_message = (
                "Execution interrupted: the portal instance running it was stopped. "
                "Check the deployments' current replica counts before re-running."
            )
            execution.step_details = [dict(s) for s in steps]
            execution.completed_at = now
            execution.duration_seconds = (now - execution.started_at).total_seconds()
            await self.db.commit()
        except Exception as exc:  # best effort; the abandoned-run sweep is the backstop
            logger.warning("sequence_interrupt_record_failed", execution_id=execution.id, error=str(exc)[:200])

    async def _wait_for_deployment(
        self,
        *,
        cluster_id: str,
        namespace: str,
        deployment_name: str,
        desired_replicas: int,
        timeout_seconds: int,
        wait_condition: str,
        min_ready_percent: int = 100,
        on_progress: ProgressCallback | None = None,
    ) -> int:
        """Wait until enough pods meet the step's condition; returns the count reached.

        The timeout is a no-progress window, not a total: it restarts whenever
        another pod becomes ready, so a 60-pod scale-up that keeps coming up is
        not failed halfway (nodes being added by the autoscaler take minutes).
        A step fails when nothing improves for the whole window, or at the
        STEP_WAIT_HARD_CAP_SECONDS safety limit. Raises TimeoutError with what
        is holding the pods back.
        """
        if wait_condition == "skip":
            return 0
        if wait_condition == "fixed_time":
            await asyncio.sleep(max(0, timeout_seconds))
            return 0

        # "health_endpoint" steps carry no URL to probe. Readiness probes are the
        # health check Kubernetes already runs, so they wait for ready pods.
        use_available = wait_condition == "deployment_available"
        label = "available" if use_available else "ready"
        required = required_ready_count(desired_replicas, min_ready_percent)
        loop = asyncio.get_running_loop()
        started = loop.time()
        hard_deadline = started + max(timeout_seconds, STEP_WAIT_HARD_CAP_SECONDS)
        stall_deadline = started + timeout_seconds
        last_progress = started
        last_diagnosis = started
        apps_v1, core_v1, _ = await self.aks._get_k8s_clients(cluster_id)
        best = -1
        observed = 0
        dep = None

        while True:
            try:
                dep = await asyncio.to_thread(apps_v1.read_namespaced_deployment_status, deployment_name, namespace)
                ready = dep.status.ready_replicas or 0
                available = dep.status.available_replicas or 0
                observed = available if use_available else ready
            except ApiException:
                pass
            now = loop.time()
            if observed >= required:
                if on_progress:
                    await on_progress(observed, required, None)
                return observed
            if observed > best:
                best = observed
                last_progress = now
                stall_deadline = now + timeout_seconds
                if on_progress:
                    await on_progress(observed, required, None)
            elif (
                on_progress
                and now - last_progress >= DIAGNOSE_AFTER_SECONDS
                and now - last_diagnosis >= DIAGNOSE_AFTER_SECONDS
            ):
                # Stuck for a while: say why while it is still waiting, so
                # someone can add nodes or fix the image before it fails.
                last_diagnosis = now
                await on_progress(observed, required, await self._diagnose_unready_pods(core_v1, dep, namespace))
            if now >= stall_deadline or now >= hard_deadline:
                break
            await asyncio.sleep(max(0, min(POLL_SECONDS, stall_deadline - now, hard_deadline - now)))

        if now >= hard_deadline and now < stall_deadline:
            message = f"only {observed}/{desired_replicas} pods {label} after the {STEP_WAIT_HARD_CAP_SECONDS // 60} min maximum wait"
        else:
            message = (
                f"only {observed}/{desired_replicas} pods {label}; no new pod became {label} for {timeout_seconds}s"
            )
        if required < desired_replicas:
            message += f" (needed {required})"
        diagnosis = await self._diagnose_unready_pods(core_v1, dep, namespace)
        raise TimeoutError(f"{message}. {diagnosis}" if diagnosis else message)

    async def _wait_for_scale_down(
        self,
        *,
        cluster_id: str,
        namespace: str,
        deployment_name: str,
        desired_replicas: int,
        timeout_seconds: int,
        on_progress: Callable[[int], Awaitable[None]] | None = None,
    ) -> int:
        """Wait until the deployment is down to its target number of pods.

        Counts pods that are still terminating: a startup that first stops one
        service to free CPU and memory for the next must not start the next
        while the old pods still hold it. Same no-progress timeout as pod waits,
        restarting each time another pod goes. Returns the pods left.
        """
        loop = asyncio.get_running_loop()
        started = loop.time()
        hard_deadline = started + max(timeout_seconds, STEP_WAIT_HARD_CAP_SECONDS)
        stall_deadline = started + timeout_seconds
        apps_v1, core_v1, _ = await self.aks._get_k8s_clients(cluster_id)
        selector: str | None = None
        fewest: int | None = None
        remaining: int | None = None

        while True:
            try:
                if selector is None:
                    dep = await asyncio.to_thread(apps_v1.read_namespaced_deployment, deployment_name, namespace)
                    labels = dep.spec.selector.match_labels if dep.spec and dep.spec.selector else None
                    if not labels:
                        return 0  # its pods can't be identified; nothing to wait on
                    selector = ",".join(f"{k}={v}" for k, v in labels.items())
                pods = await asyncio.to_thread(
                    core_v1.list_namespaced_pod, namespace, label_selector=selector, _request_timeout=15
                )
                # Evicted/completed pods linger as Failed/Succeeded but hold no resources.
                remaining = sum(
                    1 for p in pods.items or [] if not (p.status and p.status.phase in ("Succeeded", "Failed"))
                )
            except ApiException as exc:
                if exc.status == 404:
                    return 0
            now = loop.time()
            if remaining is not None:
                if remaining <= desired_replicas:
                    if on_progress:
                        await on_progress(remaining)
                    return remaining
                if fewest is None or remaining < fewest:
                    fewest = remaining
                    stall_deadline = now + timeout_seconds
                    if on_progress:
                        await on_progress(remaining)
            if now >= stall_deadline or now >= hard_deadline:
                break
            await asyncio.sleep(max(0, min(POLL_SECONDS, stall_deadline - now, hard_deadline - now)))

        left = "?" if remaining is None else remaining
        raise TimeoutError(
            f"{left} pods still running or terminating (target {desired_replicas}); none stopped for "
            f"{timeout_seconds}s. Pods stuck terminating usually wait on a finalizer or a long termination grace period."
        )

    async def _diagnose_unready_pods(self, core_v1, dep, namespace: str) -> str:
        """Why pods aren't ready, in a sentence: unschedulable (no capacity),
        image or crash problems, failing readiness probes, or a quota that stops
        pods from being created at all. Empty when it can't tell."""
        try:
            for cond in (dep.status.conditions or []) if dep is not None and dep.status else []:
                # Quota and admission errors: the pods are never created.
                if cond.type == "ReplicaFailure" and cond.status == "True":
                    return f"Pods cannot be created: {(cond.message or cond.reason or '')[:220]}"
            labels = dep.spec.selector.match_labels if dep is not None and dep.spec and dep.spec.selector else None
            if not labels:
                return ""
            selector = ",".join(f"{k}={v}" for k, v in labels.items())
            pods = await asyncio.to_thread(
                core_v1.list_namespaced_pod, namespace, label_selector=selector, _request_timeout=15
            )
        except Exception:
            return ""

        reasons: Counter[str] = Counter()
        for pod in pods.items or []:
            if pod.metadata and pod.metadata.deletion_timestamp:
                continue
            reason = _pod_not_ready_reason(pod)
            if reason:
                reasons[reason] += 1
        if not reasons:
            return ""
        parts = [f"{count} pod{'s' if count != 1 else ''} {reason}" for reason, count in reasons.most_common(3)]
        summary = "; ".join(parts)
        hint = _diagnosis_hint(reasons)
        return (f"Not ready: {summary}." + (f" {hint}" if hint else ""))[:420]

    async def _rollback_steps(
        self,
        scaled_steps: list[dict],
        *,
        cluster_id: str,
        namespace: str,
        user_id: str,
        user_email: str,
    ) -> int:
        """Undo scaled steps newest-first, restoring each to its replica count
        before the step. Walking backwards makes repeated steps for the same
        deployment unwind correctly (50 → 1, then 1 → 0)."""
        undone = 0
        for step in reversed(scaled_steps):
            dep_name = step.get("deployment", "")
            restore_to = step.get("current_replicas")
            restore_to = int(restore_to) if restore_to is not None else 0
            try:
                if restore_to != step.get("target_replicas"):
                    await self.aks.scale_deployment(
                        cluster_id=cluster_id,
                        namespace=namespace,
                        deployment_name=dep_name,
                        replicas=restore_to,
                        user_id=user_id,
                        user_email=user_email,
                    )
                step["rollback_status"] = "rolled_back"
                step["rolled_back_to"] = restore_to
                undone += 1
            except Exception as exc:
                step["rollback_status"] = "rollback_failed"
                step["rollback_error"] = _describe_error(exc)
                logger.error("rollback_step_failed", deployment=dep_name, error=str(exc)[:200])
        return undone

    async def _expire_abandoned_executions(self) -> int:
        """Fail "running" executions whose executor has gone away (see ABANDONED_GRACE_SECONDS)."""
        if not self.db:
            return 0
        rows = (
            (
                await self.db.execute(
                    select(EnvironmentExecutionHistory).where(EnvironmentExecutionHistory.status == "running")
                )
            )
            .scalars()
            .all()
        )
        now = _utc_now()
        expired = 0
        for row in rows:
            if now < self._abandon_deadline(row):
                continue
            steps = [dict(s) for s in (row.step_details or [])]
            for s in steps:
                if s.get("status") == "running":
                    s["status"] = "interrupted"
                elif s.get("status") == "pending":
                    s["status"] = "not_run"
            row.step_details = steps
            row.status = "failed"
            row.completed_at = now
            row.duration_seconds = (now - row.started_at).total_seconds() if row.started_at else None
            row.error_message = (
                "Execution stopped unexpectedly: the portal instance running it restarted or lost its "
                "connection. Check the deployments' current replica counts before re-running."
            )
            if row.schedule_id:
                # Otherwise the Schedules tab keeps showing this run as "running".
                await self.db.execute(
                    update(EnvironmentSchedule)
                    .where(
                        EnvironmentSchedule.id == row.schedule_id,
                        EnvironmentSchedule.last_run_status == "running",
                    )
                    .values(last_run_status="failed")
                    .execution_options(synchronize_session=False)
                )
            expired += 1
        if expired:
            await self.db.commit()
            logger.warning("environment_executions_expired", count=expired)
        return expired

    @staticmethod
    def _abandon_deadline(row: EnvironmentExecutionHistory) -> datetime:
        started = row.started_at or _utc_now()
        steps = row.step_details or []
        if row.execution_type != "sequence" and not any(isinstance(s, dict) and "step" in s for s in steps):
            return started + timedelta(seconds=ABANDONED_SCALE_SECONDS)
        last_activity = started
        for s in steps:
            if not isinstance(s, dict):
                continue
            step_started = _parse_iso(s.get("started_at"))
            if step_started is None:
                continue
            if s.get("status") == "running":
                # Pod waits restart their timeout on progress (see _wait_for_deployment).
                progressed = _parse_iso(s.get("last_progress_at"))
                base = max(step_started, progressed) if progressed else step_started
                end = base + timedelta(seconds=s.get("timeout_seconds") or DEFAULT_STEP_TIMEOUT_SECONDS)
            else:
                end = step_started + timedelta(seconds=s.get("duration_seconds") or 0)
            last_activity = max(last_activity, end)
        return last_activity + timedelta(seconds=ABANDONED_GRACE_SECONDS)

    # ── Environment Status ────────────────────────────────────────────

    async def get_environment_status(
        self,
        cluster_id: str,
        namespace: str,
    ) -> dict[str, Any]:
        """Get current deployment status for a namespace."""
        deployments = await self.aks.list_deployments(cluster_id, namespace, bypass_cache=True)

        running = 0
        stopped = 0
        scaling = 0
        failed_count = 0

        for dep in deployments:
            replicas = dep.get("replicas", 0)
            ready = dep.get("ready_replicas", 0)
            available = dep.get("available_replicas", 0)

            if replicas == 0:
                stopped += 1
            elif ready >= replicas and available >= replicas:
                running += 1
            elif ready < replicas:
                scaling += 1
            else:
                failed_count += 1

        return {
            "cluster_id": cluster_id,
            "namespace": namespace,
            "total_deployments": len(deployments),
            "running": running,
            "stopped": stopped,
            "scaling": scaling,
            "failed": failed_count,
            "deployments": deployments,
        }

    # ── Schedule CRUD ─────────────────────────────────────────────────

    async def _assert_linked_sequence_writable(self, sequence_id: int | None) -> None:
        """A schedule runs its linked sequence with the portal's own authority
        later, so the person linking it must be allowed to change that
        sequence's cluster now."""
        if not sequence_id:
            return
        seq = (
            await self.db.execute(select(EnvironmentSequence).where(EnvironmentSequence.id == sequence_id))
        ).scalar_one_or_none()
        if seq is not None:
            assert_resource_access(seq.cluster_id, "write", context=f"link sequence {sequence_id}")

    async def create_schedule(self, data: dict, user_id: str, user_email: str) -> dict:
        """Create a new environment schedule."""
        if not self.db:
            raise ValueError("Database required")
        await self._assert_linked_sequence_writable(data.get("sequence_id"))

        schedule = EnvironmentSchedule(
            job_name=data["job_name"],
            cluster_id=data["cluster_id"],
            namespace=data["namespace"],
            operation=data["operation"],
            replica_count=data.get("replica_count", 1),
            schedule_type=data["schedule_type"],
            cron_expression=data.get("cron_expression"),
            timezone=data.get("timezone", "UTC"),
            start_date=to_schedule_local(data.get("start_date"), data.get("timezone")),
            end_date=to_schedule_local(data.get("end_date"), data.get("timezone")),
            is_enabled=data.get("is_enabled", True),
            retry_count=data.get("retry_count", 3),
            failure_notification=data.get("failure_notification"),
            notify_on=data.get("notify_on", "always"),
            sequence_id=data.get("sequence_id"),
            created_by=user_id,
            created_by_email=user_email,
            created_at=_utc_now(),
        )
        self._validate_schedule_timing(schedule)
        schedule.next_run_at = self._compute_next_run(schedule)
        self.db.add(schedule)
        await self.db.commit()
        await self.db.refresh(schedule)
        return self._schedule_to_dict(schedule)

    async def update_schedule(self, schedule_id: int, data: dict) -> dict:
        """Update an existing schedule."""
        if not self.db:
            raise ValueError("Database required")

        result = await self.db.execute(select(EnvironmentSchedule).where(EnvironmentSchedule.id == schedule_id))
        schedule = result.scalar_one_or_none()
        if not schedule:
            raise ValueError(f"Schedule {schedule_id} not found")
        assert_resource_access(schedule.cluster_id, "write", context=f"update_schedule {schedule_id}")
        if data.get("sequence_id") and data.get("sequence_id") != schedule.sequence_id:
            await self._assert_linked_sequence_writable(data["sequence_id"])

        timing_fields = {"schedule_type", "cron_expression", "timezone", "start_date", "end_date"}
        # Sent as null to clear them (other fields ignore null).
        clearable = {"cron_expression", "start_date", "end_date", "failure_notification", "sequence_id"}
        was_enabled = schedule.is_enabled
        before = {f: getattr(schedule, f) for f in timing_fields}
        tz_name = data.get("timezone") or schedule.timezone
        for field in [
            "job_name",
            "operation",
            "replica_count",
            "schedule_type",
            "cron_expression",
            "timezone",
            "start_date",
            "end_date",
            "is_enabled",
            "retry_count",
            "failure_notification",
            "notify_on",
            "sequence_id",
        ]:
            if field not in data or (data[field] is None and field not in clearable):
                continue
            value = data[field]
            if field in ("start_date", "end_date"):
                value = to_schedule_local(value, tz_name)
            elif value == "" and field in clearable:
                value = None
            setattr(schedule, field, value)

        timing_changed = any(getattr(schedule, f) != before[f] for f in timing_fields)
        re_enabled = schedule.is_enabled and not was_enabled
        if schedule.is_enabled and (timing_changed or re_enabled):
            # Without this an edited time kept the old next run, and re-enabling
            # a paused schedule fired it at once for the missed run.
            self._validate_schedule_timing(schedule)
            schedule.next_run_at = self._compute_next_run(schedule)

        schedule.updated_at = datetime.now(UTC).replace(tzinfo=None)
        await self.db.commit()
        await self.db.refresh(schedule)
        return self._schedule_to_dict(schedule)

    async def delete_schedule(self, schedule_id: int) -> bool:
        """Delete a schedule."""
        if not self.db:
            raise ValueError("Database required")

        cluster = (
            await self.db.execute(select(EnvironmentSchedule.cluster_id).where(EnvironmentSchedule.id == schedule_id))
        ).scalar_one_or_none()
        if cluster is not None:
            assert_resource_access(cluster, "write", context=f"delete_schedule {schedule_id}")
        await self.db.execute(delete(EnvironmentSchedule).where(EnvironmentSchedule.id == schedule_id))
        await self.db.commit()
        return True

    async def list_schedules(
        self,
        cluster_id: str | None = None,
        namespace: str | None = None,
    ) -> list[dict]:
        """List schedules, optionally filtered by cluster/namespace."""
        if not self.db:
            return []

        stmt = select(EnvironmentSchedule).order_by(desc(EnvironmentSchedule.created_at))
        clause = arm_scope_clause(EnvironmentSchedule.cluster_id)
        if clause is not None:
            stmt = stmt.where(clause)
        if cluster_id:
            stmt = stmt.where(EnvironmentSchedule.cluster_id == cluster_id)
        if namespace:
            stmt = stmt.where(EnvironmentSchedule.namespace == namespace)

        result = await self.db.execute(stmt)
        return [self._schedule_to_dict(s) for s in result.scalars().all()]

    async def get_schedule(self, schedule_id: int) -> dict | None:
        """Get a single schedule by ID."""
        if not self.db:
            return None

        result = await self.db.execute(select(EnvironmentSchedule).where(EnvironmentSchedule.id == schedule_id))
        schedule = result.scalar_one_or_none()
        if schedule:
            assert_resource_access(schedule.cluster_id, "read", context=f"get_schedule {schedule_id}")
        return self._schedule_to_dict(schedule) if schedule else None

    # ── Sequence CRUD ─────────────────────────────────────────────────

    async def create_sequence(self, data: dict, user_id: str, user_email: str) -> dict:
        """Create a startup/shutdown sequence."""
        if not self.db:
            raise ValueError("Database required")

        steps = [_stored_step(s, i) for i, s in enumerate(data.get("steps", []))]

        sequence = EnvironmentSequence(
            name=data["name"],
            cluster_id=data["cluster_id"],
            namespace=data["namespace"],
            sequence_type=data["sequence_type"],
            steps=steps,
            rollback_on_failure=data.get("rollback_on_failure", True),
            notification_emails=data.get("notification_emails"),
            notify_on=data.get("notify_on", "always"),
            created_by=user_id,
            created_by_email=user_email,
        )
        self.db.add(sequence)
        try:
            await self.db.commit()
        except Exception:
            await self.db.rollback()
            raise
        await self.db.refresh(sequence)
        return self._sequence_to_dict(sequence)

    async def update_sequence(self, sequence_id: int, data: dict) -> dict:
        """Update a sequence."""
        if not self.db:
            raise ValueError("Database required")

        result = await self.db.execute(select(EnvironmentSequence).where(EnvironmentSequence.id == sequence_id))
        sequence = result.scalar_one_or_none()
        if not sequence:
            raise ValueError(f"Sequence {sequence_id} not found")
        assert_resource_access(sequence.cluster_id, "write", context=f"update_sequence {sequence_id}")

        if "name" in data and data["name"] is not None:
            sequence.name = data["name"]
        if "rollback_on_failure" in data and data["rollback_on_failure"] is not None:
            sequence.rollback_on_failure = data["rollback_on_failure"]
        if "notification_emails" in data and data["notification_emails"] is not None:
            sequence.notification_emails = data["notification_emails"] or None
        if "notify_on" in data and data["notify_on"] is not None:
            sequence.notify_on = data["notify_on"]
        if "steps" in data and data["steps"] is not None:
            sequence.steps = [_stored_step(s, i) for i, s in enumerate(data["steps"])]

        sequence.updated_at = datetime.now(UTC).replace(tzinfo=None)
        try:
            await self.db.commit()
        except IntegrityError:
            # Renamed onto another sequence's name; the endpoint reports 409.
            await self.db.rollback()
            raise
        await self.db.refresh(sequence)
        return self._sequence_to_dict(sequence)

    async def delete_sequence(self, sequence_id: int) -> bool:
        """Delete a sequence."""
        if not self.db:
            raise ValueError("Database required")

        cluster = (
            await self.db.execute(select(EnvironmentSequence.cluster_id).where(EnvironmentSequence.id == sequence_id))
        ).scalar_one_or_none()
        if cluster is not None:
            assert_resource_access(cluster, "write", context=f"delete_sequence {sequence_id}")
        # environment_schedules.sequence_id is a foreign key: deleting a linked
        # sequence used to surface as a 500 with the raw constraint error.
        linked = (
            (
                await self.db.execute(
                    select(EnvironmentSchedule.job_name).where(EnvironmentSchedule.sequence_id == sequence_id)
                )
            )
            .scalars()
            .all()
        )
        if linked:
            names = ", ".join(sorted(linked))
            raise SequenceInUseError(
                f"This sequence is used by schedule(s): {names}. Unlink or delete those schedules first."
            )
        await self.db.execute(delete(EnvironmentSequence).where(EnvironmentSequence.id == sequence_id))
        await self.db.commit()
        return True

    async def list_sequences(
        self,
        cluster_id: str | None = None,
        namespace: str | None = None,
    ) -> list[dict]:
        """List sequences, optionally filtered."""
        if not self.db:
            return []

        stmt = select(EnvironmentSequence).order_by(desc(EnvironmentSequence.created_at))
        clause = arm_scope_clause(EnvironmentSequence.cluster_id)
        if clause is not None:
            stmt = stmt.where(clause)
        if cluster_id:
            stmt = stmt.where(EnvironmentSequence.cluster_id == cluster_id)
        if namespace:
            stmt = stmt.where(EnvironmentSequence.namespace == namespace)

        result = await self.db.execute(stmt)
        return [self._sequence_to_dict(s) for s in result.scalars().all()]

    async def get_sequence(self, sequence_id: int) -> dict | None:
        """Get a single sequence by ID."""
        if not self.db:
            return None

        result = await self.db.execute(select(EnvironmentSequence).where(EnvironmentSequence.id == sequence_id))
        seq = result.scalar_one_or_none()
        if seq:
            assert_resource_access(seq.cluster_id, "read", context=f"get_sequence {sequence_id}")
        return self._sequence_to_dict(seq) if seq else None

    # ── Execution History ─────────────────────────────────────────────

    async def get_execution_history(
        self,
        cluster_id: str | None = None,
        namespace: str | None = None,
        limit: int = 50,
    ) -> list[dict]:
        """Get execution history, optionally filtered."""
        if not self.db:
            return []
        await self.sweep_abandoned_executions()

        stmt = select(EnvironmentExecutionHistory).order_by(desc(EnvironmentExecutionHistory.started_at)).limit(limit)
        clause = arm_scope_clause(EnvironmentExecutionHistory.cluster_id)
        if clause is not None:
            stmt = stmt.where(clause)
        if cluster_id:
            stmt = stmt.where(EnvironmentExecutionHistory.cluster_id == cluster_id)
        if namespace:
            stmt = stmt.where(EnvironmentExecutionHistory.namespace == namespace)

        result = await self.db.execute(stmt)
        executions = result.scalars().all()
        sequence_names, schedule_names = await self._names_for(executions)
        return [
            self._execution_to_dict(
                e,
                sequence_name=sequence_names.get(e.sequence_id),
                schedule_name=schedule_names.get(e.schedule_id),
            )
            for e in executions
        ]

    async def get_execution(self, execution_id: int) -> dict | None:
        """One execution, for polling a run's live progress."""
        if not self.db:
            return None
        await self.sweep_abandoned_executions()
        execution = (
            await self.db.execute(
                select(EnvironmentExecutionHistory).where(EnvironmentExecutionHistory.id == execution_id)
            )
        ).scalar_one_or_none()
        if execution is None:
            return None
        assert_resource_access(execution.cluster_id, "read", context=f"get_execution {execution_id}")
        sequence_names, schedule_names = await self._names_for([execution])
        return self._execution_to_dict(
            execution,
            sequence_name=sequence_names.get(execution.sequence_id),
            schedule_name=schedule_names.get(execution.schedule_id),
        )

    async def sweep_abandoned_executions(self) -> None:
        # Reads must keep working even if the sweep cannot write.
        try:
            await self._expire_abandoned_executions()
        except Exception as exc:
            await self.db.rollback()
            logger.warning("environment_execution_sweep_failed", error=str(exc)[:200])

    async def _names_for(self, executions) -> tuple[dict[int, str], dict[int, str]]:
        """Sequence and schedule names, so History says which one ran."""
        sequence_ids = {e.sequence_id for e in executions if e.sequence_id}
        schedule_ids = {e.schedule_id for e in executions if e.schedule_id}
        sequence_names: dict[int, str] = {}
        schedule_names: dict[int, str] = {}
        if sequence_ids:
            rows = await self.db.execute(
                select(EnvironmentSequence.id, EnvironmentSequence.name).where(EnvironmentSequence.id.in_(sequence_ids))
            )
            sequence_names = {row[0]: row[1] for row in rows.all()}
        if schedule_ids:
            rows = await self.db.execute(
                select(EnvironmentSchedule.id, EnvironmentSchedule.job_name).where(
                    EnvironmentSchedule.id.in_(schedule_ids)
                )
            )
            schedule_names = {row[0]: row[1] for row in rows.all()}
        return sequence_names, schedule_names

    async def get_audit_logs(self, limit: int = 100) -> list[dict]:
        """Get audit logs for environment scheduler operations."""
        if not self.db:
            return []

        env_resource_types = ("environment", "environment_schedule", "environment_sequence")
        stmt = (
            select(AuditLog)
            .where(AuditLog.resource_type.in_(env_resource_types))
            .order_by(desc(AuditLog.timestamp))
            .limit(limit)
        )
        result = await self.db.execute(stmt)
        return [
            {
                "id": log.id,
                "timestamp": (log.timestamp.isoformat() + "Z") if log.timestamp else None,
                "user_id": log.user_id,
                "user_email": log.user_email,
                "action": log.action,
                "resource_type": log.resource_type,
                "resource_id": log.resource_id,
                "status": log.status,
                "details": log.details,
            }
            for log in result.scalars().all()
        ]

    # ── Scheduled Job Execution ───────────────────────────────────────

    async def load_schedule_for_run(self, schedule_id: int) -> EnvironmentSchedule:
        if not self.db:
            raise ValueError("Database required")
        result = await self.db.execute(select(EnvironmentSchedule).where(EnvironmentSchedule.id == schedule_id))
        schedule = result.scalar_one_or_none()
        if not schedule:
            raise ValueError(f"Schedule {schedule_id} not found")
        # "Run now" from the UI; the background scheduler has no request scope.
        assert_resource_access(schedule.cluster_id, "write", context=f"run_schedule {schedule_id}")
        return schedule

    async def _mark_schedule_started(self, schedule: EnvironmentSchedule) -> None:
        schedule.last_run_at = _utc_now()
        schedule.last_run_status = "running"
        await self.db.commit()

    async def begin_scheduled_sequence(
        self, schedule: EnvironmentSchedule, *, user_id: str, user_email: str
    ) -> tuple[EnvironmentSequence, EnvironmentExecutionHistory]:
        """Record a sequence-linked schedule's run as started.

        The execution carries schedule_id from the start, so the runner sees an
        in-flight run and History labels it scheduled rather than manual.
        """
        sequence, execution = await self.begin_sequence_execution(
            sequence_id=schedule.sequence_id,
            replica_count=schedule.replica_count,
            user_id=user_id,
            user_email=user_email,
            execution_type="scheduled",
            schedule_id=schedule.id,
        )
        await self._mark_schedule_started(schedule)
        return sequence, execution

    async def execute_scheduled_job(
        self,
        schedule_id: int,
        *,
        user_id: str | None = None,
        user_email: str | None = None,
    ) -> dict[str, Any]:
        """Run a schedule to completion: a scheduler tick, or "Run now" of a plain scale.

        Runs act as the schedule's creator unless a user triggered them.
        """
        schedule = await self.load_schedule_for_run(schedule_id)
        run_as_id = user_id or schedule.created_by
        run_as_email = (user_email or "") if user_id else (schedule.created_by_email or "")

        try:
            if schedule.sequence_id:
                sequence, execution = await self.begin_scheduled_sequence(
                    schedule, user_id=run_as_id, user_email=run_as_email
                )
                result = await self.run_sequence_execution(
                    sequence, execution, user_id=run_as_id, user_email=run_as_email
                )
            else:
                await self._mark_schedule_started(schedule)
                result = await self.scale_environment(
                    cluster_id=schedule.cluster_id,
                    namespace=schedule.namespace,
                    operation=schedule.operation,
                    scope="namespace",
                    deployment_names=None,
                    replica_count=schedule.replica_count,
                    dry_run=False,
                    user_id=run_as_id,
                    user_email=run_as_email,
                    execution_type="scheduled",
                    schedule_id=schedule_id,
                )
        except Exception as exc:
            await self.finish_scheduled_job(schedule, error=exc, triggered_by_email=user_email if user_id else None)
            raise

        await self.finish_scheduled_job(schedule, result, triggered_by_email=user_email if user_id else None)
        return result

    async def finish_scheduled_job(
        self,
        schedule: EnvironmentSchedule,
        result: dict[str, Any] | None = None,
        *,
        error: Exception | None = None,
        triggered_by_email: str | None = None,
    ) -> None:
        """Record a scheduled run's outcome on the schedule and email the recipients:
        the schedule's creator, its notification list, the linked sequence's list,
        and whoever pressed Run now."""
        status = result["status"] if result else "failed"
        try:
            if schedule.last_run_status != "running" or schedule.last_run_at is None:
                schedule.last_run_at = _utc_now()
            schedule.last_run_status = status
            await self.db.commit()
        except Exception as exc:
            logger.warning("schedule_status_update_failed", schedule_id=schedule.id, error=str(exc)[:200])

        if error is not None:
            logger.error(
                "scheduled_job_failed",
                schedule_id=schedule.id,
                job_name=schedule.job_name,
                error=str(error)[:200],
            )

        sequence = await self.db.get(EnvironmentSequence, schedule.sequence_id) if schedule.sequence_id else None
        execution = None
        if result and result.get("execution_id"):
            execution = await self.db.get(EnvironmentExecutionHistory, result["execution_id"])
        if triggered_by_email:
            trigger = f'Run now of schedule "{schedule.job_name}" by {triggered_by_email}'
        else:
            trigger = f'Schedule "{schedule.job_name}" · {describe_schedule(schedule)}'
        await self._email_run_summary(
            recipients=parse_recipients(
                schedule.created_by_email,
                schedule.failure_notification,
                sequence.notification_emails if sequence else None,
                triggered_by_email,
            ),
            notify_on=schedule.notify_on,
            status=status,
            execution=execution,
            result=result,
            trigger=trigger,
            name=sequence.name if sequence else schedule.job_name,
            operation=(f"sequence_{sequence.sequence_type}" if sequence else schedule.operation),
            cluster_id=schedule.cluster_id,
            namespace=schedule.namespace,
            timezone=schedule.timezone or "UTC",
            error=_describe_error(error) if error is not None else None,
        )

    async def _email_run_summary(
        self,
        *,
        recipients: list[str],
        notify_on: str | None,
        status: str,
        trigger: str,
        name: str | None,
        execution: EnvironmentExecutionHistory | None = None,
        result: dict[str, Any] | None = None,
        operation: str | None = None,
        cluster_id: str | None = None,
        namespace: str | None = None,
        timezone: str = "UTC",
        error: str | None = None,
    ) -> None:
        """Best effort: never raises, never fails the run."""
        if not recipients or not should_notify(notify_on, status):
            return
        try:
            report = build_run_report(
                status=status,
                trigger=trigger,
                name=name,
                execution=execution,
                result=result,
                operation=operation,
                cluster_id=cluster_id,
                namespace=namespace,
                timezone=timezone,
                error=error,
            )
            notifications.queue_run_email(recipients, report)
        except Exception as exc:
            logger.warning("environment_run_email_skipped", error=str(exc)[:200])

    async def manual_scale_report(
        self, result: dict[str, Any], *, cluster_id: str, namespace: str, operation: str, user_email: str
    ) -> RunReport:
        """Report for a manual namespace scale, built while the request's session is open."""
        execution = None
        if result.get("execution_id"):
            execution = await self.db.get(EnvironmentExecutionHistory, result["execution_id"]) if self.db else None
        return build_run_report(
            status=result.get("status", "failed"),
            trigger=f"Started manually by {user_email}",
            name=None,
            execution=execution,
            result=result,
            operation=operation,
            cluster_id=cluster_id,
            namespace=namespace,
        )

    # ── Helpers ────────────────────────────────────────────────────────

    @staticmethod
    def _compute_next_run(schedule) -> datetime | None:
        """First run of a new, edited or re-enabled schedule (naive UTC)."""
        return next_schedule_run(schedule, _utc_now())

    @staticmethod
    def _validate_schedule_timing(schedule) -> None:
        schedule_zone(schedule.timezone)
        schedule_trigger(schedule)  # raises for a bad cron expression
        if schedule.start_date and schedule.end_date and schedule.end_date <= schedule.start_date:
            raise ScheduleValidationError("The end date must be after the start date")
        if schedule.schedule_type == "one_time" and schedule.is_enabled:
            start_utc = local_to_utc(schedule.start_date, schedule.timezone)
            if start_utc is None:
                raise ScheduleValidationError("A one-time schedule needs a start date and time")
            if start_utc < _utc_now() - timedelta(minutes=1):
                raise ScheduleValidationError("The start time of a one-time schedule is in the past")
        if schedule.end_date and schedule.is_enabled:
            end_utc = local_to_utc(schedule.end_date, schedule.timezone)
            if end_utc < _utc_now():
                raise ScheduleValidationError("The end date is in the past")

    @staticmethod
    def _format_dt_with_tz(dt: datetime | None, timezone: str | None) -> str | None:
        """Format a UTC datetime to the schedule's local timezone for display."""
        if dt is None:
            return None
        if not timezone or timezone == "UTC":
            return dt.isoformat()
        try:
            from zoneinfo import ZoneInfo

            utc_dt = dt.replace(tzinfo=UTC)
            local_dt = utc_dt.astimezone(ZoneInfo(timezone))
            return local_dt.strftime("%Y-%m-%dT%H:%M:%S")
        except Exception:
            return dt.isoformat()

    def _schedule_to_dict(self, s: EnvironmentSchedule) -> dict:
        return {
            "id": s.id,
            "job_name": s.job_name,
            "cluster_id": s.cluster_id,
            "namespace": s.namespace,
            "operation": s.operation,
            "replica_count": s.replica_count,
            "schedule_type": s.schedule_type,
            "cron_expression": s.cron_expression,
            "timezone": s.timezone,
            "start_date": s.start_date.isoformat() if s.start_date else None,
            "end_date": s.end_date.isoformat() if s.end_date else None,
            "is_enabled": s.is_enabled,
            "retry_count": s.retry_count,
            "failure_notification": s.failure_notification,
            "notify_on": s.notify_on or "always",
            "sequence_id": s.sequence_id,
            "created_by": s.created_by,
            "created_by_email": s.created_by_email,
            "created_at": (s.created_at.isoformat() + "Z") if s.created_at else None,
            "updated_at": (s.updated_at.isoformat() + "Z") if s.updated_at else None,
            "last_run_at": (s.last_run_at.isoformat() + "Z") if s.last_run_at else None,
            "next_run_at": self._format_dt_with_tz(s.next_run_at, s.timezone),
            "next_run_at_utc": (s.next_run_at.isoformat() + "Z") if s.next_run_at else None,
            "schedule_description": describe_schedule(s),
            "last_run_status": s.last_run_status,
        }

    def _sequence_to_dict(self, s: EnvironmentSequence) -> dict:
        return {
            "id": s.id,
            "name": s.name,
            "cluster_id": s.cluster_id,
            "namespace": s.namespace,
            "sequence_type": s.sequence_type,
            "steps": s.steps or [],
            "rollback_on_failure": s.rollback_on_failure,
            "notification_emails": s.notification_emails,
            "notify_on": s.notify_on or "always",
            "created_by": s.created_by,
            "created_by_email": s.created_by_email,
            "created_at": s.created_at.isoformat() if s.created_at else None,
            "updated_at": s.updated_at.isoformat() if s.updated_at else None,
        }

    def _execution_to_dict(
        self,
        e: EnvironmentExecutionHistory,
        *,
        sequence_name: str | None = None,
        schedule_name: str | None = None,
    ) -> dict:
        return {
            "id": e.id,
            "execution_type": e.execution_type,
            "cluster_id": e.cluster_id,
            "namespace": e.namespace,
            "operation": e.operation,
            "sequence_name": sequence_name,
            "schedule_name": schedule_name,
            "status": e.status,
            "total_deployments": e.total_deployments,
            "completed_count": e.completed_count,
            "failed_count": e.failed_count,
            "skipped_count": e.skipped_count,
            "replica_count": e.replica_count,
            "schedule_id": e.schedule_id,
            "sequence_id": e.sequence_id,
            "step_details": e.step_details,
            "initiated_by": e.initiated_by,
            "initiated_by_email": e.initiated_by_email,
            "started_at": (e.started_at.isoformat() + "Z") if e.started_at else None,
            "completed_at": (e.completed_at.isoformat() + "Z") if e.completed_at else None,
            "duration_seconds": e.duration_seconds,
            "error_message": e.error_message,
        }

    async def _write_audit(
        self,
        *,
        user_id: str,
        user_email: str,
        action: str,
        resource_type: str,
        resource_id: str,
        status: str,
        details: dict,
    ) -> None:
        """Write an audit log entry."""
        if not self.db:
            return
        try:
            entry = AuditLog(
                user_id=user_id,
                user_email=user_email,
                action=action,
                resource_type=resource_type,
                resource_id=resource_id,
                status=status,
                details=details,
            )
            self.db.add(entry)
            await self.db.commit()
        except Exception as exc:
            logger.warning("audit_write_failed", error=str(exc)[:200])


def get_environment_scaling_service(db: AsyncSession | None) -> EnvironmentScalingService:
    """Factory for EnvironmentScalingService."""
    return EnvironmentScalingService(db)


def launch_sequence_run(
    *,
    sequence_id: int,
    execution_id: int,
    user_id: str,
    user_email: str,
    schedule_id: int | None = None,
) -> None:
    """Run a recorded execution in the background on its own DB session.

    Startups wait for pods per step and can take many minutes — far past the
    ingress timeout if held inside the HTTP request. The task inherits the
    caller's context, so it acts with the access scope of the user who started
    it. With schedule_id, the schedule's last-run status and email follow.
    """
    task = asyncio.create_task(
        _run_sequence_in_background(
            sequence_id=sequence_id,
            execution_id=execution_id,
            user_id=user_id,
            user_email=user_email,
            schedule_id=schedule_id,
        )
    )
    _background_runs.add(task)
    task.add_done_callback(_background_runs.discard)


async def _run_sequence_in_background(
    *,
    sequence_id: int,
    execution_id: int,
    user_id: str,
    user_email: str,
    schedule_id: int | None = None,
) -> None:
    from app.core.database import get_db_session

    try:
        async for db in get_db_session():
            sequence = await db.get(EnvironmentSequence, sequence_id)
            execution = await db.get(EnvironmentExecutionHistory, execution_id)
            schedule = await db.get(EnvironmentSchedule, schedule_id) if schedule_id else None
            if sequence is None or execution is None:
                logger.error("sequence_background_run_missing", sequence_id=sequence_id, execution_id=execution_id)
                return
            service = EnvironmentScalingService(db)
            try:
                result = await service.run_sequence_execution(
                    sequence, execution, user_id=user_id, user_email=user_email
                )
            except Exception as exc:
                if schedule is not None:
                    await service.finish_scheduled_job(schedule, error=exc, triggered_by_email=user_email)
                raise
            if schedule is not None:
                await service.finish_scheduled_job(schedule, result, triggered_by_email=user_email)
            logger.info("sequence_background_run_finished", execution_id=execution_id, status=result["status"])
    except Exception as exc:
        # The row stays "running"; the abandoned-run sweep fails it later.
        logger.error("sequence_background_run_failed", execution_id=execution_id, error=str(exc)[:300])
