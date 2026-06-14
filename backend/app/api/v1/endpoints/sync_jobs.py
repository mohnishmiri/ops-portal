"""Sync-job queue endpoints.

POST ``/sync-jobs`` — enqueue a sync job and return its ID immediately.
GET  ``/sync-jobs/{id}`` — fetch a job's current status, last_error,
                          and result payload.
GET  ``/sync-jobs`` — list recent jobs (newest first), filterable by type.

Legacy ``/costs/amortized/sync`` and ``/dashboards/leadership/sync`` enqueue
jobs and return ``202`` with a ``job_id``. Prefer ``POST /sync-jobs`` and poll
``GET /sync-jobs/{id}`` for long-running Azure sync work.

Manual **amortized** jobs include ``subscription_ids`` in the payload when the
user's subscription picker is narrower than the full admin-monitored set.
**Leadership** manual jobs always sync the full monitored set (shared snapshot).
Scheduled/startup jobs never pass ``subscription_ids``.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.core.database import get_db
from app.core.subscription_scope import subscription_ids_for_manual_amortized_sync
from app.models.auth import UserContext, UserRole
from app.models.database import SyncJob
from app.services.sync_worker import enqueue_job

logger = structlog.get_logger(__name__)

router = APIRouter()

_ALLOWED_JOB_TYPES = {"amortized", "leadership", "aks_resource_sync"}
_AKS_RESOURCE_TYPES = {
    "clusters",
    "nodepools",
    "deployments",
    "pods",
    "cronjobs",
    "services",
    "secrets",
    "configmaps",
    "ingress",
}
_STALE_RUNNING_MINUTES = 30


class EnqueueRequest(BaseModel):
    """Body for POST /sync-jobs."""

    job_type: str = Field(..., description="One of: amortized, leadership, aks_resource_sync")
    months: int | None = Field(None, ge=1, le=12, description="Amortized: months window (default 2)")
    force: bool = Field(False, description="Amortized: wipe + re-fetch entire window")
    cluster_id: str | None = Field(None, description="AKS sync: cluster resource ID")
    resource_type: str | None = Field(None, description="AKS sync: resource type to refresh")
    namespace: str | None = Field(None, description="AKS sync: optional namespace filter")
    idempotency_key: str | None = Field(
        None,
        max_length=120,
        description="If set, repeated POSTs with the same key reuse an existing queued/running job.",
    )


class EnqueueResponse(BaseModel):
    job_id: int
    status: str
    job_type: str
    idempotency_key: str | None
    reused: bool = False


class SyncJobDetail(BaseModel):
    id: int
    job_type: str
    status: str
    idempotency_key: str | None
    triggered_by: str | None
    attempts: int
    last_error: str | None
    result: dict | None
    enqueued_at: str | None
    started_at: str | None
    completed_at: str | None


def _job_to_detail(job: SyncJob) -> SyncJobDetail:
    parsed_result: dict | None = None
    if job.result:
        try:
            parsed_result = json.loads(job.result)
        except (ValueError, TypeError):
            parsed_result = None
    return SyncJobDetail(
        id=job.id,
        job_type=job.job_type,
        status=job.status,
        idempotency_key=job.idempotency_key,
        triggered_by=job.triggered_by,
        attempts=job.attempts or 0,
        last_error=job.last_error,
        result=parsed_result,
        enqueued_at=job.enqueued_at.isoformat() if job.enqueued_at else None,
        started_at=job.started_at.isoformat() if job.started_at else None,
        completed_at=job.completed_at.isoformat() if job.completed_at else None,
    )


@router.post(
    "",
    response_model=EnqueueResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Enqueue a sync job",
    description=(
        "Queues a background sync. Returns immediately with the job_id; "
        "poll GET /sync-jobs/{id} for status. Use idempotency_key to "
        "prevent duplicate jobs when the user double-clicks Refresh."
    ),
)
async def enqueue_sync_job(
    body: EnqueueRequest,
    request: Request,
    user: UserContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> EnqueueResponse:
    if body.job_type not in _ALLOWED_JOB_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported job_type. Allowed: {sorted(_ALLOWED_JOB_TYPES)}",
        )
    if body.job_type != "aks_resource_sync" and not (
        user.is_admin or user.has_role(UserRole.ADMIN) or user.has_role(UserRole.WRITE)
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="WRITE role required to enqueue this sync job",
        )
    if body.force and not user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Force sync requires Admin role",
        )

    payload: dict = {}
    if body.job_type == "amortized":
        payload = {"months": body.months or 2, "force": body.force}
        scoped_ids = await subscription_ids_for_manual_amortized_sync(request)
        if scoped_ids:
            payload["subscription_ids"] = scoped_ids
    elif body.job_type == "aks_resource_sync":
        resource_type = (body.resource_type or "").strip().lower()
        if resource_type not in _AKS_RESOURCE_TYPES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unsupported AKS resource_type. Allowed: {sorted(_AKS_RESOURCE_TYPES)}",
            )
        if resource_type != "clusters" and not body.cluster_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="cluster_id is required for AKS resource sync",
            )
        payload = {
            "cluster_id": body.cluster_id,
            "resource_type": resource_type,
            "namespace": body.namespace or None,
            "subscription_ids": getattr(request.state, "scoped_subscription_ids", None),
            "force": body.force,
        }

    # Detect whether we reused an existing job by checking the DB before/after.
    pre_existing_id: int | None = None
    idempotency_key = body.idempotency_key
    if body.job_type == "aks_resource_sync" and not idempotency_key:
        resource_type = payload["resource_type"]
        scope = "all" if resource_type == "clusters" else str(payload.get("cluster_id") or "")
        namespace = str(payload.get("namespace") or "all")
        idempotency_key = f"aks:{scope}:{resource_type}:{namespace}"[:120]

    if idempotency_key:
        stale_cutoff = datetime.utcnow() - timedelta(minutes=_STALE_RUNNING_MINUTES)
        await db.execute(
            update(SyncJob)
            .where(
                SyncJob.job_type == body.job_type,
                SyncJob.idempotency_key == idempotency_key,
                SyncJob.status == "running",
                SyncJob.started_at < stale_cutoff,
            )
            .values(
                status="failed",
                completed_at=datetime.utcnow(),
                last_error="stale running job expired before enqueue",
            )
        )
        await db.commit()
        result = await db.execute(
            select(SyncJob)
            .where(
                SyncJob.job_type == body.job_type,
                SyncJob.idempotency_key == idempotency_key,
                SyncJob.status.in_(["queued", "running"]),
            )
            .order_by(SyncJob.enqueued_at.desc())
            .limit(1)
        )
        existing = result.scalars().first()
        if existing:
            pre_existing_id = existing.id

    job_id = await enqueue_job(
        body.job_type,
        payload=payload,
        triggered_by=user.email or "api",
        idempotency_key=idempotency_key,
    )

    reused = pre_existing_id == job_id
    # Fetch a snapshot for the response.
    result = await db.execute(select(SyncJob).where(SyncJob.id == job_id))
    job = result.scalars().first()
    return EnqueueResponse(
        job_id=job_id,
        status=(job.status if job else "queued"),
        job_type=body.job_type,
        idempotency_key=idempotency_key,
        reused=reused,
    )


@router.get(
    "/{job_id}",
    response_model=SyncJobDetail,
    summary="Get a sync job's status",
)
async def get_sync_job(
    job_id: int,
    user: UserContext = Depends(get_current_user),  # noqa: ARG001 — auth gate
    db: AsyncSession = Depends(get_db),
) -> SyncJobDetail:
    result = await db.execute(select(SyncJob).where(SyncJob.id == job_id))
    job = result.scalars().first()
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="job not found")
    return _job_to_detail(job)


@router.get(
    "",
    response_model=list[SyncJobDetail],
    summary="List recent sync jobs",
)
async def list_sync_jobs(
    job_type: str | None = Query(default=None, description="Filter by job_type"),
    status_filter: str | None = Query(default=None, alias="status", description="Filter by status"),
    limit: int = Query(default=20, ge=1, le=100),
    hours: int = Query(default=24, ge=1, le=168, description="Look-back window in hours"),
    user: UserContext = Depends(get_current_user),  # noqa: ARG001
    db: AsyncSession = Depends(get_db),
) -> list[SyncJobDetail]:
    stmt = select(SyncJob).where(SyncJob.enqueued_at >= datetime.utcnow() - timedelta(hours=hours))
    if job_type:
        stmt = stmt.where(SyncJob.job_type == job_type)
    if status_filter:
        stmt = stmt.where(SyncJob.status == status_filter)
    stmt = stmt.order_by(SyncJob.enqueued_at.desc()).limit(limit)

    result = await db.execute(stmt)
    return [_job_to_detail(j) for j in result.scalars().all()]
