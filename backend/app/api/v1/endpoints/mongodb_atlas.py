"""
MongoDB Atlas — clusters, start/stop schedules, utilization and administration.

Every call reaches Atlas through the portal's own API key
(``MONGODB_ATLAS_PUBLIC_KEY`` / ``_PRIVATE_KEY``); users never hold an Atlas
credential. Who may do what is therefore decided here, not by the key's Atlas
roles:

* the whole prefix is gated by the ``mongodb_atlas`` module (router-level,
  ``enforce_module_access``) — no Azure subscription grant is needed;
* reads are open to every role with module access;
* each change needs a capability, revocable on its own in the Permissions UI:
  ``atlas_cluster_power`` (stop / start), ``atlas_schedule_manage``,
  ``atlas_cluster_admin`` (tier, test failover, snapshots, alerts) and
  ``atlas_database_access`` (database users, IP access list).

Every change — refused by Atlas or not — is written to ``audit_logs`` with
``resource_type="mongodb_atlas"``; the page's Audit tab reads them back.
Production clusters need their name typed again before a stop, tier change or
test failover.
"""

from __future__ import annotations

import functools
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any, Literal

import structlog
from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.core.authz import require_capability
from app.core.database import get_db
from app.models.auth import UserContext
from app.models.database import AtlasOperation, AtlasSchedule, AuditLog
from app.schemas.mongodb_atlas import (
    CLUSTER_NAME_PATTERN,
    PROJECT_ID_PATTERN,
    AccessListEntryCreate,
    AlertAcknowledgeRequest,
    ConfirmRequest,
    DatabaseUserCreate,
    DatabaseUserUpdate,
    PowerRequest,
    ScheduleCreate,
    ScheduleLegRequest,
    ScheduleSkipRequest,
    ScheduleUpdate,
    SnapshotRequest,
    TierChangeRequest,
)
from app.services.mongodb_atlas_scheduler import (
    LEGS,
    AtlasScheduleError,
    ScheduleDraft,
    describe_leg,
    initial_next_runs,
    paused_since,
    recipients_of,
    run_schedule_leg,
    start_operation,
    target_key,
    upcoming_leg_runs,
    validate_timing,
    write_audit,
)
from app.services.mongodb_atlas_service import METRIC_PERIODS, AtlasError, AtlasService, get_atlas_service

logger = structlog.get_logger(__name__)
router = APIRouter()

_POWER = require_capability("atlas_cluster_power")
_SCHEDULES = require_capability("atlas_schedule_manage")
_ADMIN = require_capability("atlas_cluster_admin")
_DB_ACCESS = require_capability("atlas_database_access")

ProjectId = Path(..., pattern=PROJECT_ID_PATTERN)
ClusterName = Path(..., pattern=CLUSTER_NAME_PATTERN)
# Atlas auto-resumes a cluster after 30 days paused; warn this many days ahead.
AUTO_RESUME_DAYS = 30
AUTO_RESUME_WARN_DAYS = 25


def _service() -> AtlasService:
    return get_atlas_service()


def _client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


def _http_error(exc: AtlasError) -> HTTPException:
    """Atlas's answer → a status the portal UI handles.

    Atlas 401/403 mean the *portal's key* was refused; passing them through
    would make the browser think the user's own session expired.
    """
    if exc.status_code in (401, 403):
        return HTTPException(status_code=502, detail=f"Atlas refused the portal's API key: {exc.user_message}")
    if exc.status_code == 429:
        return HTTPException(status_code=503, detail=exc.user_message)
    if exc.status_code in (400, 404, 409, 503):
        return HTTPException(status_code=exc.status_code, detail=exc.user_message)
    return HTTPException(status_code=502, detail=f"Atlas error: {exc.user_message}")


async def _atlas(call: Awaitable[Any]) -> Any:
    try:
        return await call
    except AtlasError as exc:
        raise _http_error(exc) from exc


async def _audited(
    db: AsyncSession,
    request: Request,
    user: UserContext,
    *,
    action: str,
    resource_id: str,
    feature: str,
    details: dict,
    call: Callable[[], Awaitable[Any]],
    audit_result: Callable[[Any], Any] | None = None,
) -> Any:
    """Run an Atlas change and record its outcome either way."""
    record = functools.partial(
        write_audit,
        db,
        user_id=user.user_id,
        user_email=user.email,
        action=action,
        resource_id=resource_id,
        ip_address=_client_ip(request),
    )
    try:
        result = await call()
    except AtlasError as exc:
        await record(
            status="failure",
            details={"feature": feature, **details, "error": exc.user_message, "error_code": exc.error_code},
        )
        raise _http_error(exc) from exc
    except HTTPException as exc:
        await record(status="failure", details={"feature": feature, **details, "error": str(exc.detail)[:500]})
        raise
    summary = audit_result(result) if audit_result else None
    await record(status="success", details={"feature": feature, **details, **({"result": summary} if summary else {})})
    return result


def _require_confirmation(cluster: dict, confirm_name: str | None, what: str) -> None:
    if cluster.get("is_production") and (confirm_name or "").strip() != cluster["name"]:
        raise HTTPException(
            status_code=400,
            detail=f"{cluster['name']} is a production cluster. Type its name to confirm the {what}.",
        )


# ── Connection & inventory ──────────────────────────────────────────────


@router.get("/status", summary="Whether the Atlas API key is configured and accepted")
async def get_status(
    user: UserContext = Depends(get_current_user),
    service: AtlasService = Depends(_service),
) -> dict:
    return await service.status()


@router.get("/projects", summary="Atlas projects the portal's API key can see")
async def list_projects(
    refresh: bool = Query(False),
    user: UserContext = Depends(get_current_user),
    service: AtlasService = Depends(_service),
) -> dict:
    projects = await _atlas(service.list_projects(fresh=refresh))
    return {"projects": projects, "count": len(projects)}


@router.get("/clusters", summary="Every cluster, with its schedules and how long it has been paused")
async def list_clusters(
    project_id: str | None = Query(None, pattern=PROJECT_ID_PATTERN),
    refresh: bool = Query(False),
    user: UserContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    service: AtlasService = Depends(_service),
) -> dict:
    result = await _atlas(service.list_clusters(project_id, fresh=refresh))
    clusters: list[dict] = result["clusters"]

    schedules = (await db.execute(select(AtlasSchedule))).scalars().all()
    by_cluster: dict[tuple[str, str], list[dict]] = {}
    for schedule in schedules:
        for target in schedule.targets or []:
            by_cluster.setdefault((target.get("project_id"), target.get("cluster_name")), []).append(
                {
                    "id": schedule.id,
                    "name": schedule.name,
                    "is_enabled": schedule.is_enabled,
                    "next_stop_at": _iso(schedule.next_stop_at),
                    "next_start_at": _iso(schedule.next_start_at),
                }
            )

    paused_keys = [(c["project_id"], c["name"]) for c in clusters if c.get("paused")]
    since = await paused_since(db, paused_keys)
    busy = await _in_progress_by_cluster(db)
    now = datetime.now(UTC).replace(tzinfo=None)
    for cluster in clusters:
        key = (cluster["project_id"], cluster["name"])
        cluster["schedules"] = by_cluster.get(key, [])
        cluster["paused_since"] = _iso(since.get(key))
        days = (now - since[key]).days if key in since else None
        cluster["paused_days"] = days
        cluster["auto_resume_warning"] = days is not None and days >= AUTO_RESUME_WARN_DAYS
        cluster["operation_in_progress"] = busy.get(key)
    return result


async def _in_progress_by_cluster(db: AsyncSession) -> dict[tuple[str, str], dict]:
    ops = (
        (await db.execute(select(AtlasOperation).where(AtlasOperation.status == "in_progress").limit(200)))
        .scalars()
        .all()
    )
    found: dict[tuple[str, str], dict] = {}
    for op in ops:
        for row in op.targets or []:
            if row.get("status") == "in_progress":
                found[(row.get("project_id"), row.get("cluster_name"))] = {"id": op.id, "action": op.action}
    return found


@router.get("/projects/{project_id}/clusters/{cluster_name}", summary="One cluster in detail")
async def get_cluster(
    project_id: str = ProjectId,
    cluster_name: str = ClusterName,
    user: UserContext = Depends(get_current_user),
    service: AtlasService = Depends(_service),
) -> dict:
    return await _atlas(service.get_cluster(project_id, cluster_name, fresh=True))


@router.get("/utilization", summary="Latest CPU and memory of every running cluster (busiest node)")
async def get_fleet_utilization(
    refresh: bool = Query(False),
    user: UserContext = Depends(get_current_user),
    service: AtlasService = Depends(_service),
) -> dict:
    return await _atlas(service.fleet_utilization(fresh=refresh))


@router.get(
    "/projects/{project_id}/clusters/{cluster_name}/metrics",
    summary="CPU, memory, connections and disk of each node over time",
)
async def get_cluster_metrics(
    project_id: str = ProjectId,
    cluster_name: str = ClusterName,
    period: str = Query("PT24H", description=f"One of {sorted(METRIC_PERIODS)}"),
    user: UserContext = Depends(get_current_user),
    service: AtlasService = Depends(_service),
) -> dict:
    if period not in METRIC_PERIODS:
        raise HTTPException(status_code=400, detail=f"period must be one of {sorted(METRIC_PERIODS)}")
    return await _atlas(service.cluster_metrics(project_id, cluster_name, period))


# ── Stop / start ────────────────────────────────────────────────────────


async def _power(
    action: Literal["pause", "resume"],
    project_id: str,
    cluster_name: str,
    body: PowerRequest,
    request: Request,
    user: UserContext,
    db: AsyncSession,
    service: AtlasService,
) -> dict:
    cluster = await _atlas(service.get_cluster(project_id, cluster_name, fresh=True))
    if action == "pause":
        try:
            _require_confirmation(cluster, body.confirm_name, "stop")
        except HTTPException as exc:
            await write_audit(
                db,
                user_id=user.user_id,
                user_email=user.email,
                action="atlas_cluster_pause",
                resource_id=f"{cluster.get('project_name')}/{cluster_name}",
                status="failure",
                details={"feature": "cluster_power", "project_id": project_id, "error": exc.detail},
                ip_address=_client_ip(request),
            )
            raise
    recipients = recipients_of(user.email if body.notify else None, body.notification_emails)
    op = await start_operation(
        db,
        action=action,
        targets=[{"project_id": project_id, "project_name": cluster.get("project_name"), "cluster_name": cluster_name}],
        trigger="manual",
        requested_by=user.user_id,
        requested_by_email=user.email,
        reason=body.reason,
        notify_on="always" if recipients else "never",
        notification_emails=recipients,
        ip_address=_client_ip(request),
    )
    return _operation_out(op)


@router.post(
    "/projects/{project_id}/clusters/{cluster_name}/pause",
    summary="Stop (pause) a cluster",
    dependencies=[Depends(_POWER)],
)
async def pause_cluster(
    body: PowerRequest,
    request: Request,
    project_id: str = ProjectId,
    cluster_name: str = ClusterName,
    user: UserContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    service: AtlasService = Depends(_service),
) -> dict:
    return await _power("pause", project_id, cluster_name, body, request, user, db, service)


@router.post(
    "/projects/{project_id}/clusters/{cluster_name}/resume",
    summary="Start (resume) a cluster",
    dependencies=[Depends(_POWER)],
)
async def resume_cluster(
    body: PowerRequest,
    request: Request,
    project_id: str = ProjectId,
    cluster_name: str = ClusterName,
    user: UserContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    service: AtlasService = Depends(_service),
) -> dict:
    return await _power("resume", project_id, cluster_name, body, request, user, db, service)


# ── Cluster administration ──────────────────────────────────────────────


@router.patch(
    "/projects/{project_id}/clusters/{cluster_name}/tier",
    summary="Change the cluster tier (instance size)",
    dependencies=[Depends(_ADMIN)],
)
async def change_tier(
    body: TierChangeRequest,
    request: Request,
    project_id: str = ProjectId,
    cluster_name: str = ClusterName,
    user: UserContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    service: AtlasService = Depends(_service),
) -> dict:
    cluster = await _atlas(service.get_cluster(project_id, cluster_name, fresh=True))
    resource = f"{cluster.get('project_name')}/{cluster_name}"

    async def _call() -> dict:
        _require_confirmation(cluster, body.confirm_name, "tier change")
        return await service.change_tier(project_id, cluster_name, body.instance_size)

    return await _audited(
        db,
        request,
        user,
        action="atlas_cluster_tier_change",
        resource_id=resource,
        feature="cluster_admin",
        details={
            "project_id": project_id,
            "cluster_name": cluster_name,
            "from_tier": cluster.get("tier"),
            "to_tier": body.instance_size,
            "reason": body.reason,
        },
        call=_call,
        audit_result=lambda r: {"state": r.get("state"), "tier": r.get("tier")},
    )


@router.post(
    "/projects/{project_id}/clusters/{cluster_name}/test-failover",
    summary="Test failover: restart the primary so a secondary takes over",
    dependencies=[Depends(_ADMIN)],
)
async def test_failover(
    body: ConfirmRequest,
    request: Request,
    project_id: str = ProjectId,
    cluster_name: str = ClusterName,
    user: UserContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    service: AtlasService = Depends(_service),
) -> dict:
    cluster = await _atlas(service.get_cluster(project_id, cluster_name, fresh=True))

    async def _call() -> dict:
        _require_confirmation(cluster, body.confirm_name, "test failover")
        return await service.test_failover(project_id, cluster_name)

    return await _audited(
        db,
        request,
        user,
        action="atlas_cluster_test_failover",
        resource_id=f"{cluster.get('project_name')}/{cluster_name}",
        feature="cluster_admin",
        details={"project_id": project_id, "cluster_name": cluster_name, "reason": body.reason},
        call=_call,
    )


@router.get("/projects/{project_id}/clusters/{cluster_name}/snapshots", summary="Cloud backup snapshots")
async def list_snapshots(
    project_id: str = ProjectId,
    cluster_name: str = ClusterName,
    user: UserContext = Depends(get_current_user),
    service: AtlasService = Depends(_service),
) -> dict:
    return await _atlas(service.list_snapshots(project_id, cluster_name))


@router.post(
    "/projects/{project_id}/clusters/{cluster_name}/snapshots",
    summary="Take an on-demand snapshot",
    dependencies=[Depends(_ADMIN)],
)
async def take_snapshot(
    body: SnapshotRequest,
    request: Request,
    project_id: str = ProjectId,
    cluster_name: str = ClusterName,
    user: UserContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    service: AtlasService = Depends(_service),
) -> dict:
    project = await _atlas(service.ensure_project(project_id))
    return await _audited(
        db,
        request,
        user,
        action="atlas_snapshot_create",
        resource_id=f"{project['name']}/{cluster_name}",
        feature="backup",
        details={
            "project_id": project_id,
            "cluster_name": cluster_name,
            "description": body.description,
            "retention_days": body.retention_days,
        },
        call=lambda: service.take_snapshot(project_id, cluster_name, body.description, body.retention_days),
        audit_result=lambda r: {"snapshot_id": r.get("id"), "status": r.get("status")},
    )


# ── Project administration ──────────────────────────────────────────────


@router.get("/projects/{project_id}/alerts", summary="Atlas alerts for a project")
async def list_alerts(
    project_id: str = ProjectId,
    status: Literal["OPEN", "TRACKING", "CLOSED"] | None = Query("OPEN"),
    user: UserContext = Depends(get_current_user),
    service: AtlasService = Depends(_service),
) -> dict:
    return await _atlas(service.list_alerts(project_id, status))


@router.post(
    "/projects/{project_id}/alerts/{alert_id}/acknowledge",
    summary="Acknowledge (or un-acknowledge) an Atlas alert",
    dependencies=[Depends(_ADMIN)],
)
async def acknowledge_alert(
    body: AlertAcknowledgeRequest,
    request: Request,
    project_id: str = ProjectId,
    alert_id: str = Path(..., pattern=PROJECT_ID_PATTERN),
    user: UserContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    service: AtlasService = Depends(_service),
) -> dict:
    project = await _atlas(service.ensure_project(project_id))
    return await _audited(
        db,
        request,
        user,
        action="atlas_alert_unacknowledge" if body.unacknowledge else "atlas_alert_acknowledge",
        resource_id=f"{project['name']}/alert/{alert_id}",
        feature="alerts",
        details={
            "project_id": project_id,
            "alert_id": alert_id,
            "until": _iso(body.acknowledged_until),
            "comment": body.comment,
        },
        call=lambda: service.acknowledge_alert(
            project_id,
            alert_id,
            until=body.acknowledged_until,
            comment=body.comment or f"Acknowledged in OpsPortal by {user.email or user.user_id}",
            unacknowledge=body.unacknowledge,
        ),
    )


@router.get("/projects/{project_id}/events", summary="Atlas activity feed for a project")
async def list_events(
    project_id: str = ProjectId,
    cluster_name: str | None = Query(None, pattern=CLUSTER_NAME_PATTERN),
    page: int = Query(1, ge=1, le=100),
    page_size: int = Query(100, ge=10, le=500),
    user: UserContext = Depends(get_current_user),
    service: AtlasService = Depends(_service),
) -> dict:
    return await _atlas(service.list_events(project_id, cluster_name=cluster_name, page=page, page_size=page_size))


@router.get("/projects/{project_id}/database-users", summary="Database users of a project")
async def list_database_users(
    project_id: str = ProjectId,
    user: UserContext = Depends(get_current_user),
    service: AtlasService = Depends(_service),
) -> dict:
    return await _atlas(service.list_database_users(project_id))


def _audit_db_user(body: DatabaseUserCreate | DatabaseUserUpdate) -> dict:
    # Never the password: only what was granted.
    details: dict[str, Any] = {}
    if body.roles is not None:
        details["roles"] = [f"{r.role_name}@{r.database_name}" for r in body.roles]
    if body.scopes is not None:
        details["scopes"] = [s.name for s in body.scopes]
    return details


@router.post(
    "/projects/{project_id}/database-users",
    summary="Create a SCRAM database user (password returned once)",
    dependencies=[Depends(_DB_ACCESS)],
)
async def create_database_user(
    body: DatabaseUserCreate,
    request: Request,
    project_id: str = ProjectId,
    user: UserContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    service: AtlasService = Depends(_service),
) -> dict:
    project = await _atlas(service.ensure_project(project_id))
    return await _audited(
        db,
        request,
        user,
        action="atlas_database_user_create",
        resource_id=f"{project['name']}/dbuser/{body.username}",
        feature="database_users",
        details={
            "project_id": project_id,
            "username": body.username,
            "password_generated": body.password is None,
            "temporary_until": _iso(body.delete_after_date),
            **_audit_db_user(body),
        },
        call=lambda: service.create_database_user(project_id, body),
    )


@router.patch(
    "/projects/{project_id}/database-users/{username}",
    summary="Change a database user's roles or reset its password",
    dependencies=[Depends(_DB_ACCESS)],
)
async def update_database_user(
    body: DatabaseUserUpdate,
    request: Request,
    project_id: str = ProjectId,
    username: str = Path(..., min_length=1, max_length=1024),
    auth_database: str = Query("admin", pattern=r"^(admin|\$external)$"),
    user: UserContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    service: AtlasService = Depends(_service),
) -> dict:
    project = await _atlas(service.ensure_project(project_id))
    return await _audited(
        db,
        request,
        user,
        action="atlas_database_user_update",
        resource_id=f"{project['name']}/dbuser/{username}",
        feature="database_users",
        details={
            "project_id": project_id,
            "username": username,
            "password_reset": body.reset_password,
            **_audit_db_user(body),
        },
        call=lambda: service.update_database_user(project_id, username, auth_database, body),
    )


@router.delete(
    "/projects/{project_id}/database-users/{username}",
    summary="Delete a database user",
    dependencies=[Depends(_DB_ACCESS)],
)
async def delete_database_user(
    request: Request,
    project_id: str = ProjectId,
    username: str = Path(..., min_length=1, max_length=1024),
    auth_database: str = Query("admin", pattern=r"^(admin|\$external)$"),
    user: UserContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    service: AtlasService = Depends(_service),
) -> dict:
    project = await _atlas(service.ensure_project(project_id))
    await _audited(
        db,
        request,
        user,
        action="atlas_database_user_delete",
        resource_id=f"{project['name']}/dbuser/{username}",
        feature="database_users",
        details={"project_id": project_id, "username": username, "auth_database": auth_database},
        call=lambda: service.delete_database_user(project_id, username, auth_database),
    )
    return {"deleted": username}


@router.get("/projects/{project_id}/access-list", summary="Project IP access list")
async def list_access_list(
    project_id: str = ProjectId,
    user: UserContext = Depends(get_current_user),
    service: AtlasService = Depends(_service),
) -> dict:
    return await _atlas(service.list_access_list(project_id))


@router.post(
    "/projects/{project_id}/access-list",
    summary="Add an IP address or CIDR block to the project access list",
    dependencies=[Depends(_DB_ACCESS)],
)
async def add_access_list_entry(
    body: AccessListEntryCreate,
    request: Request,
    project_id: str = ProjectId,
    user: UserContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    service: AtlasService = Depends(_service),
) -> dict:
    project = await _atlas(service.ensure_project(project_id))
    return await _audited(
        db,
        request,
        user,
        action="atlas_access_list_add",
        resource_id=f"{project['name']}/access-list/{body.entry}",
        feature="network_access",
        details={
            "project_id": project_id,
            "entry": body.entry,
            "comment": body.comment,
            "temporary_until": _iso(body.delete_after_date),
        },
        call=lambda: service.add_access_list_entry(
            project_id, body.entry, comment=body.comment, delete_after=body.delete_after_date
        ),
    )


@router.delete(
    "/projects/{project_id}/access-list/{entry:path}",
    summary="Remove an IP address or CIDR block from the project access list",
    dependencies=[Depends(_DB_ACCESS)],
)
async def delete_access_list_entry(
    request: Request,
    project_id: str = ProjectId,
    entry: str = Path(..., max_length=64),
    user: UserContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    service: AtlasService = Depends(_service),
) -> dict:
    project = await _atlas(service.ensure_project(project_id))
    await _audited(
        db,
        request,
        user,
        action="atlas_access_list_delete",
        resource_id=f"{project['name']}/access-list/{entry}",
        feature="network_access",
        details={"project_id": project_id, "entry": entry},
        call=lambda: service.delete_access_list_entry(project_id, entry),
    )
    return {"deleted": entry}


# ── Schedules ───────────────────────────────────────────────────────────


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() + "Z" if value else None


def _local_iso(value: datetime | None) -> str | None:
    """Wall-clock fields (one-time legs) carry no zone; the schedule's timezone applies."""
    return value.isoformat() if value else None


def _schedule_out(schedule: AtlasSchedule) -> dict:
    return {
        "id": schedule.id,
        "name": schedule.name,
        "description": schedule.description,
        "targets": schedule.targets or [],
        "schedule_type": schedule.schedule_type,
        "timezone": schedule.timezone,
        "stop_cron": schedule.stop_cron,
        "start_cron": schedule.start_cron,
        "stop_at": _local_iso(schedule.stop_at),
        "start_at": _local_iso(schedule.start_at),
        "stop_description": describe_leg(schedule, "stop"),
        "start_description": describe_leg(schedule, "start"),
        "next_stop_at": _iso(schedule.next_stop_at),
        "next_start_at": _iso(schedule.next_start_at),
        "skip_next_stop": schedule.skip_next_stop,
        "skip_next_start": schedule.skip_next_start,
        "is_enabled": schedule.is_enabled,
        "notify_on": schedule.notify_on,
        "notification_emails": schedule.notification_emails,
        "remind_minutes_before": schedule.remind_minutes_before,
        "last_stop_run_at": _iso(schedule.last_stop_run_at),
        "last_start_run_at": _iso(schedule.last_start_run_at),
        "last_run_status": schedule.last_run_status,
        "created_by": schedule.created_by_email or schedule.created_by,
        "created_at": _iso(schedule.created_at),
        "updated_by": schedule.updated_by,
        "updated_at": _iso(schedule.updated_at),
    }


def _operation_out(op: AtlasOperation) -> dict:
    return {
        "id": op.id,
        "action": op.action,
        "trigger": op.trigger,
        "schedule_id": op.schedule_id,
        "schedule_name": op.schedule_name,
        "status": op.status,
        "targets": op.targets or [],
        "reason": op.reason,
        "requested_by": op.requested_by_email or op.requested_by,
        "requested_at": _iso(op.requested_at),
        "completed_at": _iso(op.completed_at),
        "duration_seconds": (
            round((op.completed_at - op.requested_at).total_seconds()) if op.completed_at and op.requested_at else None
        ),
        "error_message": op.error_message,
    }


async def _validated_targets(
    service: AtlasService, targets: list, acknowledge_production: bool
) -> tuple[list[dict], list[str]]:
    """Check each target exists and can be paused; returns (targets, production cluster names)."""
    seen: set[tuple[str, str]] = set()
    clean: list[dict] = []
    production: list[str] = []
    problems: list[str] = []
    for target in targets:
        key = (target.project_id.lower(), target.cluster_name)
        if key in seen:
            continue
        seen.add(key)
        try:
            cluster = await service.get_cluster(target.project_id, target.cluster_name)
        except AtlasError as exc:
            if exc.status_code == 404:
                problems.append(f"{target.cluster_name}: not found in that project")
                continue
            raise _http_error(exc) from exc
        if not cluster.get("pausable"):
            problems.append(f"{target.cluster_name}: {cluster.get('pause_blocker') or 'cannot be paused'}")
            continue
        if cluster.get("is_production"):
            production.append(cluster["name"])
        clean.append(
            {
                "project_id": cluster["project_id"],
                "project_name": cluster.get("project_name"),
                "cluster_name": cluster["name"],
            }
        )
    if problems:
        raise HTTPException(status_code=400, detail="Cannot schedule: " + "; ".join(problems))
    if production and not acknowledge_production:
        raise HTTPException(
            status_code=400,
            detail=(
                f"{', '.join(production)} {'is a production cluster' if len(production) == 1 else 'are production clusters'}. "
                "Confirm that this schedule may stop production."
            ),
        )
    return clean, production


def _draft(fields: dict) -> ScheduleDraft:
    return ScheduleDraft(
        schedule_type=fields["schedule_type"],
        timezone=fields["timezone"],
        stop_cron=fields.get("stop_cron") if fields["schedule_type"] == "recurring" else None,
        start_cron=fields.get("start_cron") if fields["schedule_type"] == "recurring" else None,
        stop_at=fields.get("stop_at") if fields["schedule_type"] == "one_time" else None,
        start_at=fields.get("start_at") if fields["schedule_type"] == "one_time" else None,
    )


def _naive_local(value: datetime | None) -> datetime | None:
    """A one-time leg is wall-clock time in the schedule's timezone, stored without a zone."""
    return value.replace(tzinfo=None) if value and value.tzinfo else value


@router.get("/schedules", summary="Start/stop schedules with their next runs")
async def list_schedules(
    user: UserContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    rows = (await db.execute(select(AtlasSchedule).order_by(AtlasSchedule.name))).scalars().all()
    return {"schedules": [_schedule_out(s) for s in rows], "count": len(rows)}


@router.get("/schedules/preview", summary="When a draft schedule would run")
async def preview_schedule(
    schedule_type: Literal["recurring", "one_time"] = Query("recurring"),
    timezone: str = Query("UTC", max_length=100),
    stop_cron: str | None = Query(None, max_length=120),
    start_cron: str | None = Query(None, max_length=120),
    stop_at: datetime | None = Query(None),
    start_at: datetime | None = Query(None),
    user: UserContext = Depends(get_current_user),
) -> dict:
    draft = _draft(
        {
            "schedule_type": schedule_type,
            "timezone": timezone,
            "stop_cron": " ".join((stop_cron or "").split()) or None,
            "start_cron": " ".join((start_cron or "").split()) or None,
            "stop_at": _naive_local(stop_at),
            "start_at": _naive_local(start_at),
        }
    )
    try:
        validate_timing(draft)
    except AtlasScheduleError as exc:
        return {"valid": False, "error": str(exc), "stop": [], "start": []}
    return {
        "valid": True,
        "error": None,
        "stop_description": describe_leg(draft, "stop"),
        "start_description": describe_leg(draft, "start"),
        **{leg: [_iso(t) for t in upcoming_leg_runs(draft, leg, count=5)] for leg in LEGS},
    }


@router.post("/schedules", summary="Create a start/stop schedule", dependencies=[Depends(_SCHEDULES)])
async def create_schedule(
    body: ScheduleCreate,
    request: Request,
    user: UserContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    service: AtlasService = Depends(_service),
) -> dict:
    fields = body.model_dump()
    fields["stop_at"] = _naive_local(fields.get("stop_at"))
    fields["start_at"] = _naive_local(fields.get("start_at"))
    draft = _draft(fields)
    try:
        validate_timing(draft)
    except AtlasScheduleError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if (await db.execute(select(AtlasSchedule.id).where(AtlasSchedule.name == body.name))).first():
        raise HTTPException(status_code=409, detail=f"A schedule named '{body.name}' already exists")
    targets, production = await _validated_targets(service, body.targets, body.acknowledge_production)

    schedule = AtlasSchedule(
        name=body.name,
        description=body.description,
        targets=targets,
        schedule_type=draft.schedule_type,
        timezone=draft.timezone,
        stop_cron=draft.stop_cron,
        start_cron=draft.start_cron,
        stop_at=draft.stop_at,
        start_at=draft.start_at,
        is_enabled=body.is_enabled,
        notify_on=body.notify_on,
        notification_emails=body.notification_emails,
        remind_minutes_before=body.remind_minutes_before,
        created_by=user.user_id,
        created_by_email=user.email,
        updated_by=user.email or user.user_id,
    )
    initial_next_runs(schedule)
    db.add(schedule)
    await db.flush()
    await write_audit(
        db,
        user_id=user.user_id,
        user_email=user.email,
        action="atlas_schedule_create",
        resource_id=f"schedule/{schedule.name}",
        status="success",
        details={
            "feature": "schedules",
            "schedule_id": schedule.id,
            "targets": [target_key(t) for t in targets],
            "production_targets": production,
            "stop": describe_leg(schedule, "stop"),
            "start": describe_leg(schedule, "start"),
            "timezone": schedule.timezone,
            "enabled": schedule.is_enabled,
        },
        ip_address=_client_ip(request),
    )
    await db.refresh(schedule)
    return _schedule_out(schedule)


async def _load_schedule(db: AsyncSession, schedule_id: int) -> AtlasSchedule:
    schedule = (await db.execute(select(AtlasSchedule).where(AtlasSchedule.id == schedule_id))).scalar_one_or_none()
    if schedule is None:
        raise HTTPException(status_code=404, detail="Schedule not found")
    return schedule


@router.put("/schedules/{schedule_id}", summary="Edit a schedule", dependencies=[Depends(_SCHEDULES)])
async def update_schedule(
    body: ScheduleUpdate,
    request: Request,
    schedule_id: int = Path(..., ge=1),
    user: UserContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    service: AtlasService = Depends(_service),
) -> dict:
    schedule = await _load_schedule(db, schedule_id)
    changes = body.model_dump(exclude_unset=True)
    changes.pop("acknowledge_production", None)
    for key in ("stop_at", "start_at"):
        if key in changes:
            changes[key] = _naive_local(changes[key])

    merged = {
        "schedule_type": changes.get("schedule_type", schedule.schedule_type),
        "timezone": changes.get("timezone", schedule.timezone),
        **{
            key: changes[key] if key in changes else getattr(schedule, key)
            for key in ("stop_cron", "start_cron", "stop_at", "start_at")
        },
    }
    timing_changed = any(
        key in changes for key in ("schedule_type", "timezone", "stop_cron", "start_cron", "stop_at", "start_at")
    )
    draft = _draft(merged)
    enabling = changes.get("is_enabled") is True and not schedule.is_enabled
    if timing_changed or enabling:
        try:
            validate_timing(draft)
        except AtlasScheduleError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    if "name" in changes and changes["name"] != schedule.name:
        clash = (
            await db.execute(
                select(AtlasSchedule.id).where(AtlasSchedule.name == changes["name"], AtlasSchedule.id != schedule.id)
            )
        ).first()
        if clash:
            raise HTTPException(status_code=409, detail=f"A schedule named '{changes['name']}' already exists")

    production: list[str] = []
    if "targets" in changes:
        changes["targets"], production = await _validated_targets(
            service, body.targets or [], body.acknowledge_production
        )

    before = _schedule_out(schedule)
    for key in ("name", "description", "targets", "is_enabled", "notify_on", "notification_emails"):
        if key in changes:
            setattr(schedule, key, changes[key])
    if "remind_minutes_before" in changes and changes["remind_minutes_before"] is not None:
        schedule.remind_minutes_before = changes["remind_minutes_before"]
    schedule.schedule_type = draft.schedule_type
    schedule.timezone = draft.timezone
    schedule.stop_cron, schedule.start_cron = draft.stop_cron, draft.start_cron
    schedule.stop_at, schedule.start_at = draft.stop_at, draft.start_at
    schedule.updated_by = user.email or user.user_id
    if timing_changed or enabling:
        # From now: an edit or a re-enable never fires a catch-up run.
        initial_next_runs(schedule)
        if schedule.schedule_type == "one_time" and not (schedule.next_stop_at or schedule.next_start_at):
            schedule.is_enabled = False

    after = _schedule_out(schedule)
    changed = {k: {"from": before[k], "to": after[k]} for k in after if before.get(k) != after[k] and k != "updated_at"}
    await write_audit(
        db,
        user_id=user.user_id,
        user_email=user.email,
        action="atlas_schedule_update",
        resource_id=f"schedule/{schedule.name}",
        status="success",
        details={
            "feature": "schedules",
            "schedule_id": schedule.id,
            "changes": changed,
            "production_targets": production,
        },
        ip_address=_client_ip(request),
    )
    await db.refresh(schedule)
    return _schedule_out(schedule)


@router.delete("/schedules/{schedule_id}", summary="Delete a schedule", dependencies=[Depends(_SCHEDULES)])
async def delete_schedule(
    request: Request,
    schedule_id: int = Path(..., ge=1),
    user: UserContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    schedule = await _load_schedule(db, schedule_id)
    snapshot = _schedule_out(schedule)
    await db.delete(schedule)
    await write_audit(
        db,
        user_id=user.user_id,
        user_email=user.email,
        action="atlas_schedule_delete",
        resource_id=f"schedule/{snapshot['name']}",
        status="success",
        details={"feature": "schedules", "schedule": snapshot},
        ip_address=_client_ip(request),
    )
    return {"deleted": schedule_id}


@router.post(
    "/schedules/{schedule_id}/skip",
    summary="Skip (or un-skip) the next stop or start of a schedule",
    dependencies=[Depends(_SCHEDULES)],
)
async def skip_schedule_leg(
    body: ScheduleSkipRequest,
    request: Request,
    schedule_id: int = Path(..., ge=1),
    user: UserContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    schedule = await _load_schedule(db, schedule_id)
    if getattr(schedule, f"next_{body.leg}_at") is None:
        raise HTTPException(status_code=400, detail=f"This schedule has no upcoming {body.leg}")
    setattr(schedule, f"skip_next_{body.leg}", body.skip)
    schedule.updated_by = user.email or user.user_id
    await write_audit(
        db,
        user_id=user.user_id,
        user_email=user.email,
        action="atlas_schedule_skip" if body.skip else "atlas_schedule_unskip",
        resource_id=f"schedule/{schedule.name}",
        status="success",
        details={
            "feature": "schedules",
            "schedule_id": schedule.id,
            "leg": body.leg,
            "run_at": _iso(getattr(schedule, f"next_{body.leg}_at")),
        },
        ip_address=_client_ip(request),
    )
    await db.refresh(schedule)
    return _schedule_out(schedule)


@router.post(
    "/schedules/{schedule_id}/run",
    summary="Run a schedule's stop or start now (its timetable is unchanged)",
    dependencies=[Depends(_SCHEDULES), Depends(_POWER)],
)
async def run_schedule_now(
    body: ScheduleLegRequest,
    request: Request,
    schedule_id: int = Path(..., ge=1),
    user: UserContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    schedule = await _load_schedule(db, schedule_id)
    op = await run_schedule_leg(
        db,
        schedule,
        body.leg,
        trigger="run_now",
        requested_by=user.user_id,
        requested_by_email=user.email,
        ip_address=_client_ip(request),
    )
    return _operation_out(op)


# ── Operations & audit ──────────────────────────────────────────────────


@router.get("/operations", summary="Recent stop/start operations")
async def list_operations(
    status: str | None = Query(None, pattern=r"^(in_progress|completed|partial|failed|skipped)$"),
    limit: int = Query(200, ge=1, le=1000),
    user: UserContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    query = select(AtlasOperation).order_by(AtlasOperation.requested_at.desc()).limit(limit)
    if status:
        query = query.where(AtlasOperation.status == status)
    rows = (await db.execute(query)).scalars().all()
    in_progress = (
        await db.execute(select(func.count(AtlasOperation.id)).where(AtlasOperation.status == "in_progress"))
    ).scalar_one()
    return {"operations": [_operation_out(op) for op in rows], "count": len(rows), "in_progress": in_progress}


@router.get("/operations/{operation_id}", summary="One operation, for polling while it runs")
async def get_operation(
    operation_id: int = Path(..., ge=1),
    user: UserContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    op = (await db.execute(select(AtlasOperation).where(AtlasOperation.id == operation_id))).scalar_one_or_none()
    if op is None:
        raise HTTPException(status_code=404, detail="Operation not found")
    return _operation_out(op)


@router.get("/audit", summary="Audit trail of every MongoDB Atlas change made through the portal")
async def list_audit(
    limit: int = Query(500, ge=1, le=2000),
    user: UserContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    rows = (
        (
            await db.execute(
                select(AuditLog)
                .where(AuditLog.resource_type == "mongodb_atlas")
                .order_by(AuditLog.timestamp.desc(), AuditLog.id.desc())
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    entries = []
    for row in rows:
        details = row.details
        if isinstance(details, str):  # SQLite test database stores TEXT
            import json

            try:
                details = json.loads(details)
            except ValueError:
                details = {"raw": details}
        entries.append(
            {
                "id": row.id,
                "timestamp": _iso(row.timestamp),
                "user": row.user_email or row.user_id,
                "action": row.action,
                "resource": row.resource_id,
                "status": row.status,
                "ip_address": row.ip_address,
                "details": details or {},
            }
        )
    return {"entries": entries, "count": len(entries)}
