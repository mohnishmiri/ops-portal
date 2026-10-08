"""
Environment Scaling & Scheduling API Endpoints.

Provides:
- Manual environment scale up / down
- Schedule CRUD for automated scaling
- Sequence CRUD for ordered startup / shutdown
- Execution history
- Environment status
"""

from datetime import UTC
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user, require_role
from app.core.database import get_db
from app.models.auth import UserContext, UserRole
from app.schemas.environment import (
    EnvironmentScaleRequest,
    ScheduleCreate,
    SchedulePreviewRequest,
    ScheduleUpdate,
    SequenceCreate,
    SequenceExecuteRequest,
    SequenceUpdate,
)
from app.services import environment_notifications as notifications
from app.services.environment_notifications import parse_recipients
from app.services.environment_scaling_service import (
    EnvironmentScalingService,
    ScheduleValidationError,
    SequenceAlreadyRunningError,
    SequenceInUseError,
    SequenceValidationError,
    get_environment_scaling_service,
    launch_sequence_run,
    local_to_utc,
    to_schedule_local,
    upcoming_schedule_runs,
)

logger = structlog.get_logger(__name__)
router = APIRouter()


def _get_service(db: AsyncSession = Depends(get_db)) -> EnvironmentScalingService:
    return get_environment_scaling_service(db)


# ── Manual Scale ──────────────────────────────────────────────────────


@router.post("/scale")
async def scale_environment(
    body: EnvironmentScaleRequest,
    request: Request,
    service: EnvironmentScalingService = Depends(_get_service),
    user: UserContext = Depends(require_role(UserRole.WRITE)),
):
    """Scale up or down all/selected deployments in a namespace."""
    try:
        result = await service.scale_environment(
            cluster_id=body.cluster_id,
            namespace=body.namespace,
            operation=body.operation.value,
            scope=body.scope.value,
            deployment_names=body.deployment_names,
            replica_count=body.replica_count,
            dry_run=body.dry_run,
            user_id=user.user_id,
            user_email=user.email,
        )
        recipients = parse_recipients(user.email if body.notify else None, body.notification_emails)
        if recipients and not body.dry_run and result.get("total_deployments"):
            report = await service.manual_scale_report(
                result,
                cluster_id=body.cluster_id,
                namespace=body.namespace,
                operation=body.operation.value,
                user_email=user.email,
            )
            # Sent after the response: SMTP must not hold up the person scaling.
            notifications.queue_run_email(recipients, report)
        return result
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("environment_scale_failed", error=str(exc)[:200])
        raise HTTPException(status_code=500, detail=str(exc)[:500])


# ── Environment Status ────────────────────────────────────────────────


@router.get("/status")
async def get_environment_status(
    cluster_id: str = Query(...),
    namespace: str = Query(...),
    service: EnvironmentScalingService = Depends(_get_service),
    user: UserContext = Depends(get_current_user),
):
    """Get current deployment status for a namespace."""
    try:
        return await service.get_environment_status(cluster_id, namespace)
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("environment_status_failed", error=str(exc)[:200])
        raise HTTPException(status_code=500, detail=str(exc)[:500])


# ── Schedules ─────────────────────────────────────────────────────────


@router.get("/schedule")
async def list_schedules(
    cluster_id: str | None = Query(None),
    namespace: str | None = Query(None),
    service: EnvironmentScalingService = Depends(_get_service),
    user: UserContext = Depends(get_current_user),
):
    """List all environment schedules."""
    return await service.list_schedules(cluster_id=cluster_id, namespace=namespace)


@router.post("/schedule")
async def create_schedule(
    body: ScheduleCreate,
    service: EnvironmentScalingService = Depends(_get_service),
    user: UserContext = Depends(require_role(UserRole.WRITE)),
):
    """Create a new environment schedule."""
    try:
        result = await service.create_schedule(
            data=body.model_dump(mode="json", exclude_none=True),
            user_id=user.user_id,
            user_email=user.email,
        )
        await service._write_audit(
            user_id=user.user_id,
            user_email=user.email,
            action="create_schedule",
            resource_type="environment_schedule",
            resource_id=str(result.get("id", "")),
            status="success",
            details={
                "job_name": body.job_name,
                "namespace": body.namespace,
                "operation": body.operation.value,
                "schedule_type": body.schedule_type.value,
            },
        )
        return result
    except ScheduleValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("schedule_create_failed", error=str(exc)[:200])
        raise HTTPException(status_code=500, detail=str(exc)[:500])


@router.get("/schedule/preview")
async def preview_schedule(
    schedule_type: str = Query(...),
    cron_expression: str | None = Query(None),
    timezone: str = Query("UTC"),
    start_date: str | None = Query(None),
    end_date: str | None = Query(None),
    user: UserContext = Depends(get_current_user),
):
    """The next runs a schedule would make — shown in the form before saving."""
    try:
        body = SchedulePreviewRequest(
            schedule_type=schedule_type,
            cron_expression=cron_expression or None,
            timezone=timezone,
            start_date=start_date or None,
            end_date=end_date or None,
        )
        draft = SimpleNamespace(
            schedule_type=body.schedule_type.value,
            cron_expression=body.cron_expression,
            timezone=body.timezone,
            start_date=to_schedule_local(body.start_date, body.timezone),
            end_date=to_schedule_local(body.end_date, body.timezone),
            created_at=None,
        )
        runs = upcoming_schedule_runs(draft, count=5)
    except (ScheduleValidationError, ValidationError, ValueError) as exc:
        message = exc.errors()[0]["msg"] if isinstance(exc, ValidationError) else str(exc)
        raise HTTPException(status_code=400, detail=message)
    zone = ZoneInfo(body.timezone)
    return {
        "timezone": body.timezone,
        "runs": [
            {
                "utc": run.isoformat() + "Z",
                "local": run.replace(tzinfo=UTC).astimezone(zone).strftime("%a %b %d, %Y %I:%M %p %Z"),
            }
            for run in runs
        ],
        "start_utc": (local_to_utc(draft.start_date, body.timezone).isoformat() + "Z") if draft.start_date else None,
    }


@router.put("/schedule/{schedule_id}")
async def update_schedule(
    schedule_id: int,
    body: ScheduleUpdate,
    service: EnvironmentScalingService = Depends(_get_service),
    user: UserContext = Depends(require_role(UserRole.WRITE)),
):
    """Update an existing environment schedule."""
    try:
        # exclude_unset, not exclude_none: an explicit null clears an end date,
        # the notification list or the sequence link.
        result = await service.update_schedule(
            schedule_id=schedule_id,
            data=body.model_dump(mode="json", exclude_unset=True),
        )
        await service._write_audit(
            user_id=user.user_id,
            user_email=user.email,
            action="update_schedule",
            resource_type="environment_schedule",
            resource_id=str(schedule_id),
            status="success",
            details={"schedule_id": schedule_id, "updated_fields": list(body.model_dump(exclude_unset=True).keys())},
        )
        return result
    except ScheduleValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        logger.error("schedule_update_failed", error=str(exc)[:200])
        raise HTTPException(status_code=500, detail=str(exc)[:500])


@router.delete("/schedule/{schedule_id}")
async def delete_schedule(
    schedule_id: int,
    service: EnvironmentScalingService = Depends(_get_service),
    user: UserContext = Depends(require_role(UserRole.WRITE)),
):
    """Delete an environment schedule."""
    try:
        await service.delete_schedule(schedule_id)
        await service._write_audit(
            user_id=user.user_id,
            user_email=user.email,
            action="delete_schedule",
            resource_type="environment_schedule",
            resource_id=str(schedule_id),
            status="success",
            details={"schedule_id": schedule_id},
        )
        return {"deleted": True}
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("schedule_delete_failed", error=str(exc)[:200])
        raise HTTPException(status_code=500, detail=str(exc)[:500])


# ── Sequences ─────────────────────────────────────────────────────────


@router.get("/sequence")
async def list_sequences(
    cluster_id: str | None = Query(None),
    namespace: str | None = Query(None),
    service: EnvironmentScalingService = Depends(_get_service),
    user: UserContext = Depends(get_current_user),
):
    """List all startup/shutdown sequences."""
    return await service.list_sequences(cluster_id=cluster_id, namespace=namespace)


@router.post("/sequence")
async def create_sequence(
    body: SequenceCreate,
    service: EnvironmentScalingService = Depends(_get_service),
    user: UserContext = Depends(require_role(UserRole.WRITE)),
):
    """Create a startup/shutdown sequence."""
    try:
        result = await service.create_sequence(
            data=body.model_dump(mode="json"),
            user_id=user.user_id,
            user_email=user.email,
        )
        await service._write_audit(
            user_id=user.user_id,
            user_email=user.email,
            action="create_sequence",
            resource_type="environment_sequence",
            resource_id=str(result.get("id", "")),
            status="success",
            details={"name": body.name, "sequence_type": body.sequence_type.value, "steps": len(body.steps)},
        )
        return result
    except IntegrityError:
        raise HTTPException(
            status_code=409,
            detail=f"A sequence named '{body.name}' already exists for this cluster/namespace.",
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("sequence_create_failed", error=str(exc)[:200])
        raise HTTPException(status_code=500, detail=str(exc)[:500])


@router.put("/sequence/{sequence_id}")
async def update_sequence(
    sequence_id: int,
    body: SequenceUpdate,
    service: EnvironmentScalingService = Depends(_get_service),
    user: UserContext = Depends(require_role(UserRole.WRITE)),
):
    """Update a startup/shutdown sequence."""
    try:
        result = await service.update_sequence(
            sequence_id=sequence_id,
            data=body.model_dump(mode="json", exclude_none=True),
        )
        await service._write_audit(
            user_id=user.user_id,
            user_email=user.email,
            action="update_sequence",
            resource_type="environment_sequence",
            resource_id=str(sequence_id),
            status="success",
            details={"sequence_id": sequence_id, "updated_fields": list(body.model_dump(exclude_none=True).keys())},
        )
        return result
    except IntegrityError:
        raise HTTPException(
            status_code=409,
            detail=f"A sequence named '{body.name}' already exists for this cluster/namespace.",
        )
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        logger.error("sequence_update_failed", error=str(exc)[:200])
        raise HTTPException(status_code=500, detail=str(exc)[:500])


@router.delete("/sequence/{sequence_id}")
async def delete_sequence(
    sequence_id: int,
    service: EnvironmentScalingService = Depends(_get_service),
    user: UserContext = Depends(require_role(UserRole.WRITE)),
):
    """Delete a startup/shutdown sequence."""
    try:
        await service.delete_sequence(sequence_id)
        await service._write_audit(
            user_id=user.user_id,
            user_email=user.email,
            action="delete_sequence",
            resource_type="environment_sequence",
            resource_id=str(sequence_id),
            status="success",
            details={"sequence_id": sequence_id},
        )
        return {"deleted": True}
    except SequenceInUseError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("sequence_delete_failed", error=str(exc)[:200])
        raise HTTPException(status_code=500, detail=str(exc)[:500])


# ── Sequence Execution ────────────────────────────────────────────────


async def _run_sequence_request(
    body: SequenceExecuteRequest,
    service: EnvironmentScalingService,
    user: UserContext,
    *,
    action: str,
) -> dict:
    """Dry runs answer inline. Real runs are recorded, then executed in the
    background: the response carries the execution_id the UI polls for live
    step status."""
    if body.dry_run:
        result = await service.execute_sequence(
            sequence_id=body.sequence_id,
            replica_count=body.replica_count,
            dry_run=True,
            user_id=user.user_id,
            user_email=user.email,
        )
        await service._write_audit(
            user_id=user.user_id,
            user_email=user.email,
            action=action,
            resource_type="environment_sequence",
            resource_id=str(body.sequence_id),
            status="dry_run",
            details={"sequence_id": body.sequence_id, "total": result.get("total_deployments"), "dry_run": True},
        )
        return result

    sequence, execution = await service.begin_sequence_execution(
        sequence_id=body.sequence_id,
        replica_count=body.replica_count,
        user_id=user.user_id,
        user_email=user.email,
    )
    await service._write_audit(
        user_id=user.user_id,
        user_email=user.email,
        action=action,
        resource_type="environment_sequence",
        resource_id=str(sequence.id),
        status="started",
        details={
            "name": sequence.name,
            "execution_id": execution.id,
            "namespace": sequence.namespace,
            "steps": execution.total_deployments,
        },
    )
    launch_sequence_run(
        sequence_id=sequence.id,
        execution_id=execution.id,
        user_id=user.user_id,
        user_email=user.email,
    )
    return service.execution_started_result(execution)


async def _sequence_endpoint(body, service, user, *, action: str, log_event: str) -> dict:
    try:
        return await _run_sequence_request(body, service, user, action=action)
    except SequenceAlreadyRunningError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except SequenceValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        logger.error(log_event, error=str(exc)[:200])
        raise HTTPException(status_code=500, detail=str(exc)[:500])


@router.post("/start-sequence")
async def start_sequence(
    body: SequenceExecuteRequest,
    service: EnvironmentScalingService = Depends(_get_service),
    user: UserContext = Depends(require_role(UserRole.WRITE)),
):
    """Start a startup sequence; returns at once with the running execution."""
    return await _sequence_endpoint(
        body, service, user, action="execute_start_sequence", log_event="start_sequence_failed"
    )


@router.post("/stop-sequence")
async def stop_sequence(
    body: SequenceExecuteRequest,
    service: EnvironmentScalingService = Depends(_get_service),
    user: UserContext = Depends(require_role(UserRole.WRITE)),
):
    """Start a shutdown sequence; returns at once with the running execution."""
    return await _sequence_endpoint(
        body.model_copy(update={"replica_count": 0}),
        service,
        user,
        action="execute_stop_sequence",
        log_event="stop_sequence_failed",
    )


# ── Execution History ─────────────────────────────────────────────────


@router.get("/history")
async def get_execution_history(
    cluster_id: str | None = Query(None),
    namespace: str | None = Query(None),
    limit: int = Query(50, ge=1, le=500),
    service: EnvironmentScalingService = Depends(_get_service),
    user: UserContext = Depends(get_current_user),
):
    """Get environment scaling execution history."""
    return await service.get_execution_history(
        cluster_id=cluster_id,
        namespace=namespace,
        limit=limit,
    )


@router.get("/history/{execution_id}")
async def get_execution(
    execution_id: int,
    service: EnvironmentScalingService = Depends(_get_service),
    user: UserContext = Depends(get_current_user),
):
    """One execution with per-step status, polled while a sequence runs."""
    execution = await service.get_execution(execution_id)
    if execution is None:
        raise HTTPException(status_code=404, detail=f"Execution {execution_id} not found")
    return execution


@router.post("/schedule/{schedule_id}/run")
async def run_schedule_now(
    schedule_id: int,
    service: EnvironmentScalingService = Depends(_get_service),
    user: UserContext = Depends(require_role(UserRole.WRITE)),
):
    """Trigger a schedule now, as the clicking user.

    A sequence-linked schedule returns at once with the running execution (it
    can take many minutes); a plain namespace scale finishes inline.
    """
    try:
        schedule = await service.load_schedule_for_run(schedule_id)
        if schedule.sequence_id:
            sequence, execution = await service.begin_scheduled_sequence(
                schedule, user_id=user.user_id, user_email=user.email
            )
            await service._write_audit(
                user_id=user.user_id,
                user_email=user.email,
                action="run_schedule_manually",
                resource_type="environment_schedule",
                resource_id=str(schedule_id),
                status="started",
                details={
                    "schedule_id": schedule_id,
                    "job_name": schedule.job_name,
                    "sequence": sequence.name,
                    "execution_id": execution.id,
                },
            )
            launch_sequence_run(
                sequence_id=sequence.id,
                execution_id=execution.id,
                user_id=user.user_id,
                user_email=user.email,
                schedule_id=schedule_id,
            )
            return service.execution_started_result(execution)

        result = await service.execute_scheduled_job(schedule_id, user_id=user.user_id, user_email=user.email)
        await service._write_audit(
            user_id=user.user_id,
            user_email=user.email,
            action="run_schedule_manually",
            resource_type="environment_schedule",
            resource_id=str(schedule_id),
            status=result.get("status", "unknown"),
            details={
                "schedule_id": schedule_id,
                "total": result.get("total_deployments"),
                "completed": result.get("completed"),
                "failed": result.get("failed"),
            },
        )
        return result
    except SequenceAlreadyRunningError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except SequenceValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        logger.error("schedule_manual_run_failed", error=str(exc)[:200])
        raise HTTPException(status_code=500, detail=str(exc)[:500])


# ── Audit Logs ────────────────────────────────────────────────────────


@router.get("/audit-logs")
async def get_environment_audit_logs(
    limit: int = Query(100, ge=1, le=500),
    service: EnvironmentScalingService = Depends(_get_service),
    user: UserContext = Depends(get_current_user),
):
    """Get audit logs for all environment scheduler operations."""
    return await service.get_audit_logs(limit=limit)
