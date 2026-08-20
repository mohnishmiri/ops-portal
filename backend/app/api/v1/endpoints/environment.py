"""
Environment Scaling & Scheduling API Endpoints.

Provides:
- Manual environment scale up / down
- Schedule CRUD for automated scaling
- Sequence CRUD for ordered startup / shutdown
- Execution history
- Environment status
"""

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user, require_role
from app.core.database import get_db
from app.models.auth import UserContext, UserRole
from app.schemas.environment import (
    EnvironmentScaleRequest,
    ScheduleCreate,
    ScheduleUpdate,
    SequenceCreate,
    SequenceExecuteRequest,
    SequenceUpdate,
)
from app.services.environment_scaling_service import (
    EnvironmentScalingService,
    get_environment_scaling_service,
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
        return result
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
    except Exception as exc:
        logger.error("schedule_create_failed", error=str(exc)[:200])
        raise HTTPException(status_code=500, detail=str(exc)[:500])


@router.put("/schedule/{schedule_id}")
async def update_schedule(
    schedule_id: int,
    body: ScheduleUpdate,
    service: EnvironmentScalingService = Depends(_get_service),
    user: UserContext = Depends(require_role(UserRole.WRITE)),
):
    """Update an existing environment schedule."""
    try:
        result = await service.update_schedule(
            schedule_id=schedule_id,
            data=body.model_dump(mode="json", exclude_none=True),
        )
        await service._write_audit(
            user_id=user.user_id,
            user_email=user.email,
            action="update_schedule",
            resource_type="environment_schedule",
            resource_id=str(schedule_id),
            status="success",
            details={"schedule_id": schedule_id, "updated_fields": list(body.model_dump(exclude_none=True).keys())},
        )
        return result
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
    except Exception as exc:
        logger.error("sequence_delete_failed", error=str(exc)[:200])
        raise HTTPException(status_code=500, detail=str(exc)[:500])


# ── Sequence Execution ────────────────────────────────────────────────


@router.post("/start-sequence")
async def start_sequence(
    body: SequenceExecuteRequest,
    service: EnvironmentScalingService = Depends(_get_service),
    user: UserContext = Depends(require_role(UserRole.WRITE)),
):
    """Execute a startup sequence."""
    try:
        result = await service.execute_sequence(
            sequence_id=body.sequence_id,
            replica_count=body.replica_count,
            dry_run=body.dry_run,
            user_id=user.user_id,
            user_email=user.email,
        )
        await service._write_audit(
            user_id=user.user_id,
            user_email=user.email,
            action="execute_start_sequence",
            resource_type="environment_sequence",
            resource_id=str(body.sequence_id),
            status=result.get("status", "unknown"),
            details={
                "sequence_id": body.sequence_id,
                "total": result.get("total_deployments"),
                "completed": result.get("completed"),
                "failed": result.get("failed"),
                "dry_run": body.dry_run,
            },
        )
        return result
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        logger.error("start_sequence_failed", error=str(exc)[:200])
        raise HTTPException(status_code=500, detail=str(exc)[:500])


@router.post("/stop-sequence")
async def stop_sequence(
    body: SequenceExecuteRequest,
    service: EnvironmentScalingService = Depends(_get_service),
    user: UserContext = Depends(require_role(UserRole.WRITE)),
):
    """Execute a shutdown sequence."""
    try:
        result = await service.execute_sequence(
            sequence_id=body.sequence_id,
            replica_count=0,
            dry_run=body.dry_run,
            user_id=user.user_id,
            user_email=user.email,
        )
        await service._write_audit(
            user_id=user.user_id,
            user_email=user.email,
            action="execute_stop_sequence",
            resource_type="environment_sequence",
            resource_id=str(body.sequence_id),
            status=result.get("status", "unknown"),
            details={
                "sequence_id": body.sequence_id,
                "total": result.get("total_deployments"),
                "completed": result.get("completed"),
                "failed": result.get("failed"),
                "dry_run": body.dry_run,
            },
        )
        return result
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        logger.error("stop_sequence_failed", error=str(exc)[:200])
        raise HTTPException(status_code=500, detail=str(exc)[:500])


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


@router.post("/schedule/{schedule_id}/run")
async def run_schedule_now(
    schedule_id: int,
    service: EnvironmentScalingService = Depends(_get_service),
    user: UserContext = Depends(require_role(UserRole.WRITE)),
):
    """Manually trigger a scheduled job immediately."""
    try:
        result = await service.execute_scheduled_job(schedule_id)
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
