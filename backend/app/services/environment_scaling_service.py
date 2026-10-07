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
from datetime import UTC, datetime, timedelta
from typing import Any

import structlog
from kubernetes.client.rest import ApiException
from sqlalchemy import delete, desc, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.access_scope import arm_scope_clause, assert_resource_access
from app.models.database import (
    AuditLog,
    EnvironmentExecutionHistory,
    EnvironmentSchedule,
    EnvironmentSequence,
)
from app.services.aks_operations_service import (
    AKSOperationsService,
    get_aks_operations_service,
)

logger = structlog.get_logger(__name__)

# A run executes in the process that started it. If that replica restarts
# mid-run nothing updates the row again, so a "running" row is treated as
# abandoned once it has made no progress for longer than its current step
# could legitimately take, plus this grace.
ABANDONED_GRACE_SECONDS = 300
# Plain namespace scales have no per-step waits and finish in seconds.
ABANDONED_SCALE_SECONDS = 900
DEFAULT_STEP_TIMEOUT_SECONDS = 600

# Holds references so background sequence runs are not garbage-collected.
_background_runs: set[asyncio.Task] = set()


class SequenceAlreadyRunningError(Exception):
    """A sequence may only have one live execution at a time."""


class SequenceValidationError(ValueError):
    """The sequence exists but cannot be run as stored."""


class SequenceInUseError(Exception):
    """Schedules still reference the sequence."""


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
                    if target > 0:
                        await self._wait_for_deployment(
                            cluster_id=sequence.cluster_id,
                            namespace=sequence.namespace,
                            deployment_name=dep_name,
                            desired_replicas=target,
                            timeout_seconds=int(step.get("timeout_seconds") or 0),
                            wait_condition=step.get("wait_condition", "pods_ready"),
                        )
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
    ) -> None:
        """Wait until a deployment meets the step's condition, or raise TimeoutError."""
        if wait_condition == "skip":
            return
        if wait_condition == "fixed_time":
            await asyncio.sleep(max(0, timeout_seconds))
            return

        # "health_endpoint" steps carry no URL to probe. Readiness probes are the
        # health check Kubernetes already runs, so they wait for ready pods —
        # previously they waited out the full timeout and then failed.
        use_available = wait_condition == "deployment_available"
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout_seconds
        apps_v1, _, _ = await self.aks._get_k8s_clients(cluster_id)
        observed = 0

        while True:
            try:
                dep = await asyncio.to_thread(apps_v1.read_namespaced_deployment_status, deployment_name, namespace)
                ready = dep.status.ready_replicas or 0
                available = dep.status.available_replicas or 0
                observed = available if use_available else ready
                if observed >= desired_replicas:
                    return
            except ApiException:
                pass
            remaining = deadline - loop.time()
            if remaining <= 0:
                break
            await asyncio.sleep(min(5, remaining))

        label = "available" if use_available else "ready"
        raise TimeoutError(f"only {observed}/{desired_replicas} pods {label} after {timeout_seconds}s")

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
                end = step_started + timedelta(seconds=s.get("timeout_seconds") or DEFAULT_STEP_TIMEOUT_SECONDS)
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
            start_date=self._parse_dt(data.get("start_date")),
            end_date=self._parse_dt(data.get("end_date")),
            is_enabled=data.get("is_enabled", True),
            retry_count=data.get("retry_count", 3),
            failure_notification=data.get("failure_notification"),
            sequence_id=data.get("sequence_id"),
            created_by=user_id,
            created_by_email=user_email,
        )
        # Compute initial next_run_at using the schedule's timezone
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

        date_fields = {"start_date", "end_date"}
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
            "sequence_id",
        ]:
            if field in data and data[field] is not None:
                value = self._parse_dt(data[field]) if field in date_fields else data[field]
                setattr(schedule, field, value)

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

        steps = [
            {
                "order": s.get("order", i + 1),
                "deployment_name": s["deployment_name"],
                "replicas": s.get("replicas", 1),
                "wait_condition": s.get("wait_condition", "pods_ready"),
                "timeout_seconds": s.get("timeout_seconds", 600),
                "health_endpoint": s.get("health_endpoint"),
                "retry_count": s.get("retry_count", 3),
                "on_failure": s.get("on_failure", "abort"),
            }
            for i, s in enumerate(data.get("steps", []))
        ]

        sequence = EnvironmentSequence(
            name=data["name"],
            cluster_id=data["cluster_id"],
            namespace=data["namespace"],
            sequence_type=data["sequence_type"],
            steps=steps,
            rollback_on_failure=data.get("rollback_on_failure", True),
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
        if "steps" in data and data["steps"] is not None:
            sequence.steps = [
                {
                    "order": s.get("order", i + 1),
                    "deployment_name": s["deployment_name"],
                    "replicas": s.get("replicas", 1),
                    "wait_condition": s.get("wait_condition", "pods_ready"),
                    "timeout_seconds": s.get("timeout_seconds", 600),
                    "health_endpoint": s.get("health_endpoint"),
                    "retry_count": s.get("retry_count", 3),
                    "on_failure": s.get("on_failure", "abort"),
                }
                for i, s in enumerate(data["steps"])
            ]

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
            await self.finish_scheduled_job(schedule, error=exc)
            raise

        await self.finish_scheduled_job(schedule, result)
        return result

    async def finish_scheduled_job(
        self,
        schedule: EnvironmentSchedule,
        result: dict[str, Any] | None = None,
        *,
        error: Exception | None = None,
    ) -> None:
        """Record a scheduled run's outcome on the schedule and email the recipients."""
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
            result = {
                "status": "failed",
                "total_deployments": 0,
                "completed": 0,
                "failed": 0,
                "skipped": 0,
                "error": _describe_error(error),
            }
        await self._send_schedule_notification(schedule, result)

    # ── Helpers ────────────────────────────────────────────────────────

    @staticmethod
    def _compute_next_run(schedule) -> datetime | None:
        """Compute initial next_run_at for a new schedule using its timezone."""
        from zoneinfo import ZoneInfo

        from app.core.cron import cron_trigger_from_crontab

        if schedule.schedule_type == "one_time":
            return schedule.start_date

        tz = ZoneInfo(schedule.timezone) if schedule.timezone else UTC
        now = datetime.now(UTC)

        if schedule.schedule_type == "cron" and schedule.cron_expression:
            try:
                # Standard crontab day-of-week (0=Sun); from_crontab alone counts from Monday.
                trigger = cron_trigger_from_crontab(schedule.cron_expression, timezone=tz)
                next_fire = trigger.get_next_fire_time(None, now)
                if next_fire and next_fire.tzinfo:
                    return next_fire.astimezone(UTC).replace(tzinfo=None)
                return next_fire
            except Exception:
                return datetime.now(UTC).replace(tzinfo=None) + timedelta(hours=24)

        intervals = {
            "daily": timedelta(days=1),
            "weekly": timedelta(weeks=1),
            "monthly": timedelta(days=30),
        }
        delta = intervals.get(schedule.schedule_type, timedelta(days=1))
        base = schedule.start_date if schedule.start_date else datetime.now(UTC).replace(tzinfo=None)
        return (
            base + delta
            if base > datetime.now(UTC).replace(tzinfo=None)
            else datetime.now(UTC).replace(tzinfo=None) + delta
        )

    async def _send_schedule_notification(self, schedule, result: dict) -> None:
        """Send professional email notification after a scheduled job execution.

        Recipients are always determined by:
        1. The schedule creator's email (created_by_email) — always included.
        2. Any additional addresses in failure_notification (comma-separated) — merged in.
        """
        # Collect recipients: creator first, then any extra notification addresses
        recipient_set: set[str] = set()
        if schedule.created_by_email:
            recipient_set.add(schedule.created_by_email.strip())
        if schedule.failure_notification:
            for addr in schedule.failure_notification.split(","):
                addr = addr.strip()
                if addr:
                    recipient_set.add(addr)

        if not recipient_set:
            return

        try:
            from app.services.email_notification_service import EmailNotificationService

            email_service = EmailNotificationService(self.db)
            recipients = sorted(recipient_set)

            status = result.get("status", "unknown")
            job_name = schedule.job_name
            namespace = schedule.namespace
            completed = result.get("completed", 0)
            total = result.get("total_deployments", 0)
            failed = result.get("failed", 0)
            skipped = result.get("skipped", 0)
            error = result.get("error", "")
            duration = result.get("duration_seconds")
            duration_str = f"{duration:.1f}s" if duration else "—"
            operation = schedule.operation.replace("_", " ").title()
            exec_time = datetime.now(UTC).strftime("%b %d, %Y at %I:%M %p UTC")

            is_success = status == "completed"
            accent = "#0568AE" if is_success else "#C41E3A"
            status_label = "COMPLETED SUCCESSFULLY" if is_success else "EXECUTION FAILED"

            subject = f"Environment Scheduler | {job_name} | {status.title()}"

            # Build step rows
            step_rows = ""
            details = result.get("details", [])
            for i, step in enumerate(details[:25], 1):
                dep_name = step.get("deployment", "")
                step_status = step.get("status", "")
                target = step.get("target_replicas", "")
                if step_status == "completed":
                    s_badge = '<span style="color:#0B6E4F;font-weight:600;font-size:12px;">● Completed</span>'
                elif step_status == "failed":
                    s_badge = '<span style="color:#C41E3A;font-weight:600;font-size:12px;">● Failed</span>'
                elif step_status == "skipped":
                    s_badge = '<span style="color:#8B6914;font-weight:600;font-size:12px;">● Skipped</span>'
                else:
                    s_badge = f'<span style="color:#6C757D;font-weight:600;font-size:12px;">● {step_status}</span>'
                bg = "#FAFBFC" if i % 2 == 0 else "#FFFFFF"
                step_rows += f"""<tr style="background:{bg};">
                    <td style="padding:10px 20px;font-size:13px;color:#4A5568;border-bottom:1px solid #F0F0F0;">{i}</td>
                    <td style="padding:10px 20px;font-size:13px;color:#1A202C;font-family:'Consolas','Courier New',monospace;border-bottom:1px solid #F0F0F0;">{dep_name}</td>
                    <td style="padding:10px 20px;font-size:13px;color:#4A5568;text-align:center;border-bottom:1px solid #F0F0F0;">{target}</td>
                    <td style="padding:10px 20px;text-align:center;border-bottom:1px solid #F0F0F0;">{s_badge}</td>
                </tr>"""

            step_section = ""
            if step_rows:
                overflow_note = (
                    f'<p style="margin:12px 0 0;font-size:12px;color:#718096;">Showing {min(len(details), 25)} of {len(details)} deployments</p>'
                    if len(details) > 25
                    else ""
                )
                step_section = f"""
                <tr><td style="padding:28px 40px 20px;">
                    <p style="margin:0 0 14px;font-size:14px;font-weight:600;color:#1A202C;letter-spacing:0.3px;">DEPLOYMENT DETAILS</p>
                    <table style="width:100%;border-collapse:collapse;border:1px solid #E8ECF0;" cellpadding="0" cellspacing="0">
                        <thead><tr style="background:#F7F9FB;">
                            <th style="padding:10px 20px;text-align:left;font-size:11px;font-weight:700;color:#718096;text-transform:uppercase;letter-spacing:0.8px;border-bottom:2px solid #E8ECF0;">#</th>
                            <th style="padding:10px 20px;text-align:left;font-size:11px;font-weight:700;color:#718096;text-transform:uppercase;letter-spacing:0.8px;border-bottom:2px solid #E8ECF0;">Deployment</th>
                            <th style="padding:10px 20px;text-align:center;font-size:11px;font-weight:700;color:#718096;text-transform:uppercase;letter-spacing:0.8px;border-bottom:2px solid #E8ECF0;">Replicas</th>
                            <th style="padding:10px 20px;text-align:center;font-size:11px;font-weight:700;color:#718096;text-transform:uppercase;letter-spacing:0.8px;border-bottom:2px solid #E8ECF0;">Status</th>
                        </tr></thead>
                        <tbody>{step_rows}</tbody>
                    </table>
                    {overflow_note}
                </td></tr>"""

            error_section = ""
            if error:
                error_section = f"""
                <tr><td style="padding:0 40px 20px;">
                    <div style="background:#FFF5F5;border:1px solid #FED7D7;border-radius:6px;padding:16px 20px;">
                        <p style="margin:0 0 6px;font-size:11px;font-weight:700;color:#C41E3A;text-transform:uppercase;letter-spacing:0.5px;">Error Details</p>
                        <p style="margin:0;font-size:13px;color:#742A2A;font-family:'Consolas','Courier New',monospace;line-height:1.5;word-break:break-word;">{error[:500]}</p>
                    </div>
                </td></tr>"""

            html_body = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1.0"></head>
<body style="margin:0;padding:0;background:#F4F6F9;-webkit-font-smoothing:antialiased;">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#F4F6F9;padding:40px 0;">
<tr><td align="center">
<table width="640" cellpadding="0" cellspacing="0" style="background:#FFFFFF;border-radius:8px;overflow:hidden;box-shadow:0 1px 4px rgba(0,0,0,0.04);">
    <!-- Top accent bar -->
    <tr><td style="height:4px;background:{accent};font-size:0;line-height:0;">&nbsp;</td></tr>

    <!-- Header -->
    <tr><td style="padding:36px 40px 28px;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,'Helvetica Neue',Arial,sans-serif;">
        <table width="100%"><tr>
            <td style="vertical-align:top;">
                <p style="margin:0;font-size:11px;font-weight:600;color:#A0AEC0;text-transform:uppercase;letter-spacing:1.5px;">AT&T OpsPortal</p>
                <h1 style="margin:8px 0 0;font-size:24px;font-weight:700;color:#1A202C;letter-spacing:-0.3px;">Environment Scheduler</h1>
            </td>
            <td style="text-align:right;vertical-align:top;">
                <div style="display:inline-block;background:{("#F0FFF4" if is_success else "#FFF5F5")};border:1px solid {("#C6F6D5" if is_success else "#FED7D7")};border-radius:24px;padding:8px 18px;">
                    <span style="font-size:12px;font-weight:700;color:{("#276749" if is_success else "#C41E3A")};letter-spacing:0.3px;">{status_label}</span>
                </div>
            </td>
        </tr></table>
    </td></tr>

    <!-- Metrics -->
    <tr><td style="padding:0 40px 28px;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,'Helvetica Neue',Arial,sans-serif;">
        <table width="100%" cellpadding="0" cellspacing="0" style="border:1px solid #EDF2F7;border-radius:8px;overflow:hidden;">
            <tr>
                <td style="width:25%;text-align:center;padding:20px 0;border-right:1px solid #EDF2F7;">
                    <p style="margin:0;font-size:36px;font-weight:700;color:#2D3748;line-height:1;">{total}</p>
                    <p style="margin:8px 0 0;font-size:11px;font-weight:600;color:#A0AEC0;text-transform:uppercase;letter-spacing:1px;">Total</p>
                </td>
                <td style="width:25%;text-align:center;padding:20px 0;border-right:1px solid #EDF2F7;">
                    <p style="margin:0;font-size:36px;font-weight:700;color:#276749;line-height:1;">{completed}</p>
                    <p style="margin:8px 0 0;font-size:11px;font-weight:600;color:#A0AEC0;text-transform:uppercase;letter-spacing:1px;">Completed</p>
                </td>
                <td style="width:25%;text-align:center;padding:20px 0;border-right:1px solid #EDF2F7;">
                    <p style="margin:0;font-size:36px;font-weight:700;color:#C41E3A;line-height:1;">{failed}</p>
                    <p style="margin:8px 0 0;font-size:11px;font-weight:600;color:#A0AEC0;text-transform:uppercase;letter-spacing:1px;">Failed</p>
                </td>
                <td style="width:25%;text-align:center;padding:20px 0;">
                    <p style="margin:0;font-size:36px;font-weight:700;color:#975A16;line-height:1;">{skipped}</p>
                    <p style="margin:8px 0 0;font-size:11px;font-weight:600;color:#A0AEC0;text-transform:uppercase;letter-spacing:1px;">Skipped</p>
                </td>
            </tr>
        </table>
    </td></tr>

    <!-- Execution info -->
    <tr><td style="padding:0 40px 28px;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,'Helvetica Neue',Arial,sans-serif;">
        <table width="100%" cellpadding="0" cellspacing="0" style="border:1px solid #EDF2F7;border-radius:8px;overflow:hidden;">
            <tr style="background:#F7F9FB;"><td style="padding:12px 20px;font-size:12px;font-weight:600;color:#4A5568;width:140px;border-bottom:1px solid #EDF2F7;">Job Name</td><td style="padding:12px 20px;font-size:14px;color:#1A202C;font-weight:600;border-bottom:1px solid #EDF2F7;">{job_name}</td></tr>
            <tr><td style="padding:12px 20px;font-size:12px;font-weight:600;color:#4A5568;border-bottom:1px solid #EDF2F7;">Namespace</td><td style="padding:12px 20px;font-size:13px;color:#2D3748;font-family:'Consolas','Courier New',monospace;border-bottom:1px solid #EDF2F7;">{namespace}</td></tr>
            <tr style="background:#F7F9FB;"><td style="padding:12px 20px;font-size:12px;font-weight:600;color:#4A5568;border-bottom:1px solid #EDF2F7;">Operation</td><td style="padding:12px 20px;font-size:13px;color:#2D3748;border-bottom:1px solid #EDF2F7;">{operation}</td></tr>
            <tr><td style="padding:12px 20px;font-size:12px;font-weight:600;color:#4A5568;border-bottom:1px solid #EDF2F7;">Schedule</td><td style="padding:12px 20px;font-size:13px;color:#2D3748;border-bottom:1px solid #EDF2F7;">{schedule.schedule_type}{(" — " + schedule.cron_expression) if schedule.cron_expression else ""}</td></tr>
            <tr style="background:#F7F9FB;"><td style="padding:12px 20px;font-size:12px;font-weight:600;color:#4A5568;border-bottom:1px solid #EDF2F7;">Timezone</td><td style="padding:12px 20px;font-size:13px;color:#2D3748;border-bottom:1px solid #EDF2F7;">{schedule.timezone}</td></tr>
            <tr><td style="padding:12px 20px;font-size:12px;font-weight:600;color:#4A5568;border-bottom:1px solid #EDF2F7;">Duration</td><td style="padding:12px 20px;font-size:14px;color:#2D3748;font-weight:700;border-bottom:1px solid #EDF2F7;">{duration_str}</td></tr>
            <tr style="background:#F7F9FB;"><td style="padding:12px 20px;font-size:12px;font-weight:600;color:#4A5568;">Executed At</td><td style="padding:12px 20px;font-size:13px;color:#2D3748;">{exec_time}</td></tr>
        </table>
    </td></tr>

    {step_section}
    {error_section}

    <!-- Footer -->
    <tr><td style="padding:28px 40px;border-top:1px solid #EDF2F7;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,'Helvetica Neue',Arial,sans-serif;">
        <p style="margin:0;font-size:11px;color:#A0AEC0;text-align:center;line-height:1.8;letter-spacing:0.2px;">
            AT&T OpsPortal — Environment Scheduler<br>
            Automated notification — please do not reply
        </p>
    </td></tr>
</table>
</td></tr>
</table>
</body></html>"""

            for recipient in recipients:
                await email_service._send_single_email(
                    recipient=recipient,
                    subject=subject,
                    html_body=html_body,
                )

            logger.info("schedule_notification_sent", job_name=job_name, recipients=recipients, status=status)

        except Exception as exc:
            logger.warning("schedule_notification_failed", job_name=schedule.job_name, error=str(exc)[:200])

    @staticmethod
    def _parse_dt(value) -> datetime | None:
        """Parse a datetime value — handles strings, datetime objects, and None."""
        if value is None:
            return None
        if isinstance(value, datetime):
            return value.replace(tzinfo=None) if value.tzinfo else value
        if isinstance(value, str):
            try:
                from dateutil.parser import parse as dateutil_parse

                return dateutil_parse(value).replace(tzinfo=None)
            except (ImportError, ValueError):
                # Fallback: try fromisoformat
                return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)
        return None

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
            "sequence_id": s.sequence_id,
            "created_by": s.created_by,
            "created_by_email": s.created_by_email,
            "created_at": (s.created_at.isoformat() + "Z") if s.created_at else None,
            "updated_at": (s.updated_at.isoformat() + "Z") if s.updated_at else None,
            "last_run_at": (s.last_run_at.isoformat() + "Z") if s.last_run_at else None,
            "next_run_at": self._format_dt_with_tz(s.next_run_at, s.timezone),
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
                    await service.finish_scheduled_job(schedule, error=exc)
                raise
            if schedule is not None:
                await service.finish_scheduled_job(schedule, result)
            logger.info("sequence_background_run_finished", execution_id=execution_id, status=result["status"])
    except Exception as exc:
        # The row stays "running"; the abandoned-run sweep fails it later.
        logger.error("sequence_background_run_failed", execution_id=execution_id, error=str(exc)[:300])
