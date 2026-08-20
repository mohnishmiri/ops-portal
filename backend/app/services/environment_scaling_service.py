"""
Environment Scaling & Scheduling Service.

Provides:
- Manual environment scale up / down (namespace or selected deployments)
- Scheduled auto-scaling with cron, daily, weekly, monthly, one-time triggers
- Sequence-based startup/shutdown with dependency ordering
- Execution history and audit logging
"""

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

import structlog
from kubernetes.client.rest import ApiException
from sqlalchemy import delete, desc, select, update
from sqlalchemy.ext.asyncio import AsyncSession

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
            execution_type="manual",
            cluster_id=cluster_id,
            namespace=namespace,
            operation=operation,
            status="running",
            total_deployments=len(targets),
            replica_count=target_replicas,
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
                        "error": str(exc)[:500],
                    }
                )
                logger.error("env_scale_deployment_failed", deployment=dep_name, error=str(exc)[:200])

        # Finalize execution record
        final_status = "completed" if failed == 0 else "failed"
        if self.db and execution.id:
            execution.status = final_status
            execution.completed_count = completed
            execution.failed_count = failed
            execution.skipped_count = skipped
            execution.step_details = details
            now = datetime.now(UTC).replace(tzinfo=None)
            execution.completed_at = now
            execution.duration_seconds = (now - execution.started_at).total_seconds()
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
    ) -> dict[str, Any]:
        """Execute a startup or shutdown sequence."""
        if not self.db:
            raise ValueError("Database required for sequence execution")

        result = await self.db.execute(select(EnvironmentSequence).where(EnvironmentSequence.id == sequence_id))
        sequence = result.scalar_one_or_none()
        if not sequence:
            raise ValueError(f"Sequence {sequence_id} not found")

        steps = sequence.steps or []
        sorted_steps = sorted(steps, key=lambda s: s.get("order", 0))
        if sequence.sequence_type == "shutdown":
            sorted_steps = list(reversed(sorted_steps))

        target_replicas = 0 if sequence.sequence_type == "shutdown" else replica_count

        execution = EnvironmentExecutionHistory(
            execution_type="sequence",
            cluster_id=sequence.cluster_id,
            namespace=sequence.namespace,
            operation=f"sequence_{sequence.sequence_type}",
            status="running",
            total_deployments=len(sorted_steps),
            replica_count=target_replicas,
            sequence_id=sequence_id,
            initiated_by=user_id,
            initiated_by_email=user_email,
            started_at=datetime.now(UTC).replace(tzinfo=None),
        )
        self.db.add(execution)
        await self.db.commit()
        await self.db.refresh(execution)

        if dry_run:
            details = [
                {
                    "order": step.get("order"),
                    "deployment": step.get("deployment_name"),
                    "target_replicas": step.get("replicas", target_replicas)
                    if sequence.sequence_type != "shutdown"
                    else 0,
                    "wait_condition": step.get("wait_condition", "pods_ready"),
                    "status": "dry_run",
                }
                for step in sorted_steps
            ]
            execution.status = "completed"
            execution.step_details = details
            execution.completed_count = len(sorted_steps)
            execution.completed_at = datetime.now(UTC).replace(tzinfo=None)
            await self.db.commit()
            return {
                "execution_id": execution.id,
                "status": "dry_run",
                "total_deployments": len(sorted_steps),
                "completed": len(sorted_steps),
                "failed": 0,
                "skipped": 0,
                "details": details,
            }

        completed = 0
        failed = 0
        skipped = 0
        step_details: list[dict] = []

        # Pre-populate step_details with "pending" for all steps so frontend can show the list
        for step in sorted_steps:
            step_details.append(
                {
                    "order": step.get("order"),
                    "deployment": step.get("deployment_name", ""),
                    "target_replicas": 0
                    if sequence.sequence_type == "shutdown"
                    else step.get("replicas", target_replicas),
                    "status": "pending",
                }
            )
        execution.step_details = [dict(s) for s in step_details]
        await self.db.commit()

        for idx, step in enumerate(sorted_steps):
            dep_name = step.get("deployment_name", "")
            step_replicas = 0 if sequence.sequence_type == "shutdown" else step.get("replicas", target_replicas)
            timeout = step.get("timeout_seconds", 600)
            wait_condition = step.get("wait_condition", "pods_ready")
            on_failure = step.get("on_failure", "abort")

            # Mark current step as "running"
            step_start = datetime.now(UTC)
            step_details[idx]["status"] = "running"
            step_details[idx]["started_at"] = step_start.replace(tzinfo=None).isoformat() + "Z"
            execution.step_details = [dict(s) for s in step_details]
            execution.completed_count = completed
            await self.db.commit()

            try:
                await self.aks.scale_deployment(
                    cluster_id=sequence.cluster_id,
                    namespace=sequence.namespace,
                    deployment_name=dep_name,
                    replicas=step_replicas,
                    user_id=user_id,
                    user_email=user_email,
                )

                # Wait for condition if scaling up
                if step_replicas > 0 and wait_condition != "skip":
                    await self._wait_for_deployment(
                        cluster_id=sequence.cluster_id,
                        namespace=sequence.namespace,
                        deployment_name=dep_name,
                        desired_replicas=step_replicas,
                        timeout_seconds=timeout,
                        wait_condition=wait_condition,
                    )

                completed += 1
                step_duration = (datetime.now(UTC) - step_start).total_seconds()
                step_details[idx]["status"] = "completed"
                step_details[idx]["duration_seconds"] = round(step_duration, 1)
                execution.step_details = [dict(s) for s in step_details]
                execution.completed_count = completed
                await self.db.commit()

            except Exception as exc:
                failed += 1
                step_duration = (datetime.now(UTC) - step_start).total_seconds()
                step_details[idx]["status"] = "failed"
                step_details[idx]["error"] = str(exc)[:500]
                step_details[idx]["duration_seconds"] = round(step_duration, 1)
                execution.step_details = [dict(s) for s in step_details]
                execution.failed_count = failed
                await self.db.commit()
                logger.error("sequence_step_failed", deployment=dep_name, error=str(exc)[:200])

                if on_failure == "abort":
                    if sequence.rollback_on_failure and completed > 0:
                        await self._rollback_sequence(
                            step_details=step_details,
                            cluster_id=sequence.cluster_id,
                            namespace=sequence.namespace,
                            user_id=user_id,
                            user_email=user_email,
                        )
                        execution.status = "rolled_back"
                    else:
                        execution.status = "failed"
                    break

        if execution.status == "running":
            execution.status = "completed" if failed == 0 else "failed"

        execution.completed_count = completed
        execution.failed_count = failed
        execution.skipped_count = skipped
        execution.step_details = [dict(s) for s in step_details]
        now = datetime.now(UTC).replace(tzinfo=None)
        execution.completed_at = now
        execution.duration_seconds = (now - execution.started_at).total_seconds()
        await self.db.commit()

        return {
            "execution_id": execution.id,
            "status": execution.status,
            "total_deployments": len(sorted_steps),
            "completed": completed,
            "failed": failed,
            "skipped": skipped,
            "details": step_details,
        }

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
        """Wait until a deployment meets the specified condition."""
        deadline = asyncio.get_event_loop().time() + timeout_seconds
        apps_v1, _, _ = await self.aks._get_k8s_clients(cluster_id)

        while asyncio.get_event_loop().time() < deadline:
            try:
                dep = await asyncio.to_thread(apps_v1.read_namespaced_deployment_status, deployment_name, namespace)
                ready = dep.status.ready_replicas or 0
                available = dep.status.available_replicas or 0

                if wait_condition == "pods_ready" and ready >= desired_replicas:
                    return
                if wait_condition == "deployment_available" and available >= desired_replicas:
                    return
                if wait_condition == "fixed_time":
                    await asyncio.sleep(min(timeout_seconds, 30))
                    return
            except ApiException:
                pass

            await asyncio.sleep(5)

        raise TimeoutError(f"Deployment {deployment_name} did not reach ready state within {timeout_seconds}s")

    async def _rollback_sequence(
        self,
        *,
        step_details: list[dict],
        cluster_id: str,
        namespace: str,
        user_id: str,
        user_email: str,
    ) -> None:
        """Rollback completed steps by scaling back to 0."""
        completed_steps = [s for s in step_details if s.get("status") == "completed"]
        for step in reversed(completed_steps):
            dep_name = step.get("deployment", "")
            try:
                await self.aks.scale_deployment(
                    cluster_id=cluster_id,
                    namespace=namespace,
                    deployment_name=dep_name,
                    replicas=0,
                    user_id=user_id,
                    user_email=user_email,
                )
                step["rollback_status"] = "rolled_back"
            except Exception as exc:
                step["rollback_status"] = "rollback_failed"
                step["rollback_error"] = str(exc)[:500]
                logger.error("rollback_step_failed", deployment=dep_name, error=str(exc)[:200])

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

    async def create_schedule(self, data: dict, user_id: str, user_email: str) -> dict:
        """Create a new environment schedule."""
        if not self.db:
            raise ValueError("Database required")

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
        await self.db.commit()
        await self.db.refresh(sequence)
        return self._sequence_to_dict(sequence)

    async def delete_sequence(self, sequence_id: int) -> bool:
        """Delete a sequence."""
        if not self.db:
            raise ValueError("Database required")

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

        stmt = select(EnvironmentExecutionHistory).order_by(desc(EnvironmentExecutionHistory.started_at)).limit(limit)
        if cluster_id:
            stmt = stmt.where(EnvironmentExecutionHistory.cluster_id == cluster_id)
        if namespace:
            stmt = stmt.where(EnvironmentExecutionHistory.namespace == namespace)

        result = await self.db.execute(stmt)
        return [self._execution_to_dict(e) for e in result.scalars().all()]

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

    async def execute_scheduled_job(self, schedule_id: int) -> dict[str, Any]:
        """Execute a scheduled scaling job (called by the scheduler)."""
        if not self.db:
            raise ValueError("Database required")

        result = await self.db.execute(select(EnvironmentSchedule).where(EnvironmentSchedule.id == schedule_id))
        schedule = result.scalar_one_or_none()
        if not schedule:
            raise ValueError(f"Schedule {schedule_id} not found")

        try:
            # If linked to a sequence, execute the sequence instead of plain scale
            if schedule.sequence_id:
                scale_result = await self.execute_sequence(
                    sequence_id=schedule.sequence_id,
                    replica_count=schedule.replica_count,
                    dry_run=False,
                    user_id=schedule.created_by,
                    user_email=schedule.created_by_email or "",
                )
            else:
                scale_result = await self.scale_environment(
                    cluster_id=schedule.cluster_id,
                    namespace=schedule.namespace,
                    operation=schedule.operation,
                    scope="namespace",
                    deployment_names=None,
                    replica_count=schedule.replica_count,
                    dry_run=False,
                    user_id=schedule.created_by,
                    user_email=schedule.created_by_email or "",
                )

            schedule.last_run_at = datetime.now(UTC).replace(tzinfo=None)
            schedule.last_run_status = scale_result["status"]

            # Update execution record with schedule_id
            if self.db and scale_result.get("execution_id"):
                stmt = (
                    update(EnvironmentExecutionHistory)
                    .where(EnvironmentExecutionHistory.id == scale_result["execution_id"])
                    .values(schedule_id=schedule_id)
                )
                await self.db.execute(stmt)
                await self.db.commit()

            # Send notification email on completion or failure
            await self._send_schedule_notification(schedule, scale_result)

            return scale_result

        except Exception as exc:
            schedule.last_run_at = datetime.now(UTC).replace(tzinfo=None)
            schedule.last_run_status = "failed"
            await self.db.commit()

            # Send failure notification
            await self._send_schedule_notification(
                schedule,
                {
                    "status": "failed",
                    "total_deployments": 0,
                    "completed": 0,
                    "failed": 0,
                    "skipped": 0,
                    "error": str(exc)[:500],
                },
            )

            logger.error(
                "scheduled_job_failed",
                schedule_id=schedule_id,
                job_name=schedule.job_name,
                error=str(exc)[:200],
            )
            raise

    # ── Helpers ────────────────────────────────────────────────────────

    @staticmethod
    def _compute_next_run(schedule) -> datetime | None:
        """Compute initial next_run_at for a new schedule using its timezone."""
        from zoneinfo import ZoneInfo

        from apscheduler.triggers.cron import CronTrigger

        if schedule.schedule_type == "one_time":
            return schedule.start_date

        tz = ZoneInfo(schedule.timezone) if schedule.timezone else UTC
        now = datetime.now(UTC)

        if schedule.schedule_type == "cron" and schedule.cron_expression:
            try:
                trigger = CronTrigger.from_crontab(schedule.cron_expression, timezone=tz)
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
        """Send professional email notification after a scheduled job execution."""
        if not schedule.failure_notification:
            return

        try:
            from app.services.email_notification_service import EmailNotificationService

            email_service = EmailNotificationService(self.db)
            recipients = [e.strip() for e in schedule.failure_notification.split(",") if e.strip()]
            if not recipients:
                return

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

    def _execution_to_dict(self, e: EnvironmentExecutionHistory) -> dict:
        return {
            "id": e.id,
            "execution_type": e.execution_type,
            "cluster_id": e.cluster_id,
            "namespace": e.namespace,
            "operation": e.operation,
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
