"""
Admin endpoints for managing resources and permissions (granular RBAC).

Resources represent modules or pages in the portal.  Permissions grant a
subject (role or user) a specific access level (view/edit) to a resource.

All write operations require the ADMIN role.  Read operations are also
admin-only since they expose the full permission matrix.

Every mutating operation writes a row to the shared audit_logs table so
admins have a queryable, tamper-evident trail of who changed what and when.
"""

from datetime import UTC, datetime, timedelta

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import desc, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user, require_role
from app.core.database import get_db
from app.models.auth import UserContext, UserRole
from app.models.database import AuditLog, Permission, Resource

router = APIRouter()
logger = structlog.get_logger(__name__)

_AUDIT_ACTIONS = {
    "permission_granted",
    "permission_revoked",
    "resource_created",
    "resource_deleted",
    "resource_updated",
}


# ── Request / response schemas ────────────────────────────────────────────────


class ResourceCreateRequest(BaseModel):
    resource_type: str = Field(..., description="'module' or 'page'")
    resource_name: str = Field(...)
    description: str | None = None
    parent_id: int | None = Field(None, description="ID of parent module (for pages)")
    route_path: str | None = Field(None, description="Frontend route, e.g. '/aks'")


class ResourceUpdateRequest(BaseModel):
    description: str | None = None
    route_path: str | None = None
    parent_id: int | None = None


class PermissionCreateRequest(BaseModel):
    subject_type: str = Field(..., description="'user', 'role', or 'group'")
    subject_id: str = Field(..., description="user_id, role name (admin/write/read), or team name")
    resource_id: int = Field(...)
    permission_type: str = Field(..., description="'view' or 'edit'")
    environment_scope: str = Field(default="all", description="'all', 'prod', or 'nonprod'")


def _resource_to_dict(r) -> dict:
    return {
        "id": r.id,
        "resource_type": r.resource_type,
        "resource_name": r.resource_name,
        "description": r.description,
        "parent_id": r.parent_id,
        "route_path": r.route_path,
        "is_system": r.is_system,
        "created_at": r.created_at.isoformat() if r.created_at else None,
        "updated_at": r.updated_at.isoformat() if r.updated_at else None,
    }


def _permission_to_dict(p: Permission) -> dict:
    return {
        "id": p.id,
        "subject_type": p.subject_type,
        "subject_id": p.subject_id,
        "resource_id": p.resource_id,
        "resource_name": p.resource.resource_name if p.resource else None,
        "resource_type": p.resource.resource_type if p.resource else None,
        "permission_type": p.permission_type,
        "environment_scope": p.environment_scope,
        "created_at": p.created_at.isoformat() if p.created_at else None,
    }


async def _write_audit(
    db: AsyncSession,
    *,
    request: Request,
    user: UserContext,
    action: str,
    summary: str,
    details: dict,
) -> None:
    """Write a single row to audit_logs in its own transaction.

    Always called AFTER the main operation has been committed so an audit
    failure can never roll back the operation itself.  Errors are logged
    and swallowed — the session is always left in a clean state.
    """
    try:
        entry = AuditLog(
            user_id=user.user_id,
            user_email=user.email,
            action=action,
            resource_type="access_management",
            resource_id=None,
            details={"summary": summary, **details},
            ip_address=request.client.host if request.client else None,
            status="success",
        )
        db.add(entry)
        await db.commit()
    except Exception as exc:
        await db.rollback()
        logger.warning("permissions_audit_log_failed", action=action, error=str(exc)[:200])


# ── Resource endpoints ────────────────────────────────────────────────────────


@router.post("/resources", dependencies=[Depends(require_role(UserRole.ADMIN))])
async def create_resource(
    request: Request,
    req: ResourceCreateRequest,
    db: AsyncSession = Depends(get_db),
    user: UserContext = Depends(get_current_user),
):
    resource = Resource(
        resource_type=req.resource_type,
        resource_name=req.resource_name,
        description=req.description,
        parent_id=req.parent_id,
        route_path=req.route_path,
        is_system=False,
    )
    db.add(resource)
    try:
        await db.commit()
        await db.refresh(resource)
    except IntegrityError:
        await db.rollback()
        result = await db.execute(select(Resource).where(Resource.resource_name == req.resource_name))
        existing = result.scalar_one_or_none()
        if existing:
            return JSONResponse(content=jsonable_encoder(_resource_to_dict(existing)))
        raise
    logger.info("resource_created", resource_name=req.resource_name, by=user.user_id)
    await _write_audit(
        db,
        request=request,
        user=user,
        action="resource_created",
        summary=f"Created {req.resource_type} resource '{req.resource_name}'",
        details={"resource_name": req.resource_name, "resource_type": req.resource_type, "route_path": req.route_path},
    )
    return JSONResponse(content=jsonable_encoder(_resource_to_dict(resource)))


@router.get("/resources", dependencies=[Depends(require_role(UserRole.ADMIN))])
async def list_resources(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Resource).order_by(Resource.resource_type, Resource.resource_name))
    rows = result.scalars().all()
    return JSONResponse(content=jsonable_encoder([_resource_to_dict(r) for r in rows]))


@router.get("/resources/{resource_id}", dependencies=[Depends(require_role(UserRole.ADMIN))])
async def get_resource(resource_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Resource).where(Resource.id == resource_id))
    resource = result.scalar_one_or_none()
    if not resource:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Resource not found")
    return JSONResponse(content=jsonable_encoder(_resource_to_dict(resource)))


@router.patch("/resources/{resource_id}", dependencies=[Depends(require_role(UserRole.ADMIN))])
async def update_resource(
    resource_id: int,
    request: Request,
    req: ResourceUpdateRequest,
    db: AsyncSession = Depends(get_db),
    user: UserContext = Depends(get_current_user),
):
    result = await db.execute(select(Resource).where(Resource.id == resource_id))
    resource = result.scalar_one_or_none()
    if not resource:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Resource not found")
    if req.description is not None:
        resource.description = req.description
    if req.route_path is not None:
        resource.route_path = req.route_path
    if req.parent_id is not None:
        resource.parent_id = req.parent_id
    await db.commit()
    await db.refresh(resource)
    logger.info("resource_updated", resource_id=resource_id, by=user.user_id)
    await _write_audit(
        db,
        request=request,
        user=user,
        action="resource_updated",
        summary=f"Updated resource '{resource.resource_name}'",
        details={"resource_name": resource.resource_name, "resource_type": resource.resource_type},
    )
    return JSONResponse(content=jsonable_encoder(_resource_to_dict(resource)))


@router.delete("/resources/{resource_id}", dependencies=[Depends(require_role(UserRole.ADMIN))])
async def delete_resource(
    resource_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: UserContext = Depends(get_current_user),
):
    result = await db.execute(select(Resource).where(Resource.id == resource_id))
    resource = result.scalar_one_or_none()
    if not resource:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Resource not found")
    if resource.is_system:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="System resources cannot be deleted. Remove permission records instead.",
        )
    name = resource.resource_name
    rtype = resource.resource_type
    await db.delete(resource)
    await db.commit()
    logger.info("resource_deleted", resource_id=resource_id, resource_name=name, by=user.user_id)
    await _write_audit(
        db,
        request=request,
        user=user,
        action="resource_deleted",
        summary=f"Deleted {rtype} resource '{name}'",
        details={"resource_name": name, "resource_type": rtype},
    )
    return JSONResponse(content={"deleted": True, "resource_id": resource_id})


# ── Permission endpoints ──────────────────────────────────────────────────────


@router.post("/permissions", dependencies=[Depends(require_role(UserRole.ADMIN))])
async def create_permission(
    request: Request,
    req: PermissionCreateRequest,
    db: AsyncSession = Depends(get_db),
    user: UserContext = Depends(get_current_user),
):
    if req.subject_type not in ("user", "role", "group"):
        raise HTTPException(status_code=400, detail="subject_type must be 'user', 'role', or 'group'")
    if req.permission_type not in ("view", "edit"):
        raise HTTPException(status_code=400, detail="permission_type must be 'view' or 'edit'")
    if req.environment_scope not in ("all", "prod", "nonprod"):
        raise HTTPException(status_code=400, detail="environment_scope must be 'all', 'prod', or 'nonprod'")

    res = await db.execute(select(Resource).where(Resource.id == req.resource_id))
    resource = res.scalar_one_or_none()
    if not resource:
        raise HTTPException(status_code=404, detail="Resource not found")

    perm = Permission(
        subject_type=req.subject_type,
        subject_id=req.subject_id,
        resource_id=req.resource_id,
        permission_type=req.permission_type,
        environment_scope=req.environment_scope,
    )
    db.add(perm)
    try:
        await db.commit()
        await db.refresh(perm)
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail="Permission already exists")

    logger.info(
        "permission_granted",
        subject=f"{req.subject_type}:{req.subject_id}",
        resource=resource.resource_name,
        permission=req.permission_type,
        by=user.user_id,
    )
    perm.resource = resource
    await _write_audit(
        db,
        request=request,
        user=user,
        action="permission_granted",
        summary=(f"Granted {req.permission_type} on '{resource.resource_name}' to {req.subject_type}:{req.subject_id}"),
        details={
            "subject_type": req.subject_type,
            "subject_id": req.subject_id,
            "resource_name": resource.resource_name,
            "resource_type": resource.resource_type,
            "permission_type": req.permission_type,
        },
    )
    return JSONResponse(content=jsonable_encoder(_permission_to_dict(perm)))


@router.get("/permissions", dependencies=[Depends(require_role(UserRole.ADMIN))])
async def list_permissions(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Permission, Resource)
        .outerjoin(Resource, Permission.resource_id == Resource.id)
        .order_by(Permission.subject_type, Permission.subject_id)
    )
    rows = result.all()
    output = []
    for perm, resource in rows:
        perm.resource = resource
        output.append(_permission_to_dict(perm))
    return JSONResponse(content=jsonable_encoder(output))


@router.delete("/permissions/{permission_id}", dependencies=[Depends(require_role(UserRole.ADMIN))])
async def delete_permission(
    permission_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: UserContext = Depends(get_current_user),
):
    result = await db.execute(
        select(Permission, Resource)
        .outerjoin(Resource, Permission.resource_id == Resource.id)
        .where(Permission.id == permission_id)
    )
    row = result.one_or_none()
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Permission not found")
    perm, resource = row

    subject = f"{perm.subject_type}:{perm.subject_id}"
    resource_name = resource.resource_name if resource else str(perm.resource_id)
    resource_type = resource.resource_type if resource else "unknown"
    perm_type = perm.permission_type
    sub_type = perm.subject_type
    sub_id = perm.subject_id

    await db.delete(perm)
    await db.commit()
    logger.info("permission_revoked", permission_id=permission_id, subject=subject, by=user.user_id)
    await _write_audit(
        db,
        request=request,
        user=user,
        action="permission_revoked",
        summary=f"Revoked {perm_type} on '{resource_name}' from {sub_type}:{sub_id}",
        details={
            "subject_type": sub_type,
            "subject_id": sub_id,
            "resource_name": resource_name,
            "resource_type": resource_type,
            "permission_type": perm_type,
        },
    )
    return JSONResponse(content={"deleted": True, "permission_id": permission_id})


# ── Audit Log endpoint ────────────────────────────────────────────────────────


def _audit_to_dict(entry: AuditLog) -> dict:
    details = entry.details or {}
    return {
        "id": entry.id,
        "timestamp": entry.timestamp.isoformat() if entry.timestamp else None,
        "actor_user_id": entry.user_id,
        "actor_email": entry.user_email or entry.user_id,
        "action": entry.action,
        "summary": details.get("summary", entry.action),
        "subject_type": details.get("subject_type"),
        "subject_id": details.get("subject_id"),
        "resource_name": details.get("resource_name"),
        "resource_type": details.get("resource_type"),
        "permission_type": details.get("permission_type"),
        "ip_address": entry.ip_address,
    }


@router.get("/audit-log", dependencies=[Depends(require_role(UserRole.ADMIN))])
async def list_audit_log(
    days: int = Query(default=30, ge=1, le=365, description="Days of history"),
    limit: int = Query(default=200, ge=1, le=1000, description="Max records"),
    action: str | None = Query(default=None, description="Filter by action"),
    db: AsyncSession = Depends(get_db),
):
    """Return the access-management audit trail: permission grants/revokes and resource changes."""
    since = datetime.now(UTC).replace(tzinfo=None) - timedelta(days=days)

    stmt = (
        select(AuditLog)
        .where(AuditLog.action.in_(_AUDIT_ACTIONS))
        .where(AuditLog.timestamp >= since)
        .order_by(desc(AuditLog.timestamp))
        .limit(limit)
    )
    if action and action in _AUDIT_ACTIONS:
        stmt = stmt.where(AuditLog.action == action)

    result = await db.execute(stmt)
    entries = [_audit_to_dict(e) for e in result.scalars().all()]
    return JSONResponse(content={"entries": entries, "total": len(entries)})


# ── Team management endpoints ─────────────────────────────────────────────────


class TeamCreateRequest(BaseModel):
    team_name: str = Field(..., min_length=1, max_length=255)
    description: str | None = None


class TeamMemberRequest(BaseModel):
    user_id: str = Field(..., min_length=1)
    user_email: str | None = None


def _team_to_dict(t, include_members: bool = False) -> dict:
    members = []
    if include_members:
        members = [
            {
                "id": m.id,
                "user_id": m.user_id,
                "user_email": m.user_email,
                "created_at": m.created_at.isoformat() if m.created_at else None,
            }
            for m in t.members
        ]
    return {
        "id": t.id,
        "team_name": t.team_name,
        "description": t.description,
        "member_count": len(members),
        "members": members,
        "created_at": t.created_at.isoformat() if t.created_at else None,
        "updated_at": t.updated_at.isoformat() if t.updated_at else None,
    }


def _team_to_dict_raw(team_id, team_name, description, created_at, updated_at) -> dict:
    """Build team dict from plain values (avoids lazy-loading expired ORM objects)."""
    return {
        "id": team_id,
        "team_name": team_name,
        "description": description,
        "member_count": 0,
        "members": [],
        "created_at": created_at.isoformat() if created_at else None,
        "updated_at": updated_at.isoformat() if updated_at else None,
    }


@router.post("/teams", dependencies=[Depends(require_role(UserRole.ADMIN))])
async def create_team(
    request: Request,
    req: TeamCreateRequest,
    db: AsyncSession = Depends(get_db),
    user: UserContext = Depends(get_current_user),
):
    """Create an app-managed team for group-based permission grants."""
    from app.models.database import Team

    team = Team(team_name=req.team_name, description=req.description)
    db.add(team)
    try:
        await db.commit()
        await db.refresh(team, attribute_names=["id", "team_name", "description", "created_at", "updated_at"])
    except IntegrityError:
        await db.rollback()
        result = await db.execute(select(Team).where(Team.team_name == req.team_name))
        existing = result.scalar_one_or_none()
        if existing:
            response_data = _team_to_dict_raw(
                existing.id, existing.team_name, existing.description, existing.created_at, existing.updated_at
            )
            return JSONResponse(content=jsonable_encoder(response_data))
        raise

    # Capture data BEFORE audit write (which commits and may expire the object)
    response_data = _team_to_dict_raw(team.id, team.team_name, team.description, team.created_at, team.updated_at)

    logger.info("team_created", team_name=req.team_name, by=user.user_id)
    await _write_audit(
        db,
        request=request,
        user=user,
        action="resource_created",
        summary=f"Created team '{req.team_name}'",
        details={"team_name": req.team_name, "resource_type": "team"},
    )
    return JSONResponse(content=jsonable_encoder(response_data))


@router.get("/teams", dependencies=[Depends(require_role(UserRole.ADMIN))])
async def list_teams(db: AsyncSession = Depends(get_db)):
    """List all teams with their members."""
    from sqlalchemy.orm import selectinload

    from app.models.database import Team

    result = await db.execute(select(Team).options(selectinload(Team.members)).order_by(Team.team_name))
    teams = result.scalars().all()
    return JSONResponse(content=jsonable_encoder([_team_to_dict(t, include_members=True) for t in teams]))


@router.get("/teams/{team_id}", dependencies=[Depends(require_role(UserRole.ADMIN))])
async def get_team(team_id: int, db: AsyncSession = Depends(get_db)):
    """Get a single team with members."""
    from sqlalchemy.orm import selectinload

    from app.models.database import Team

    result = await db.execute(select(Team).options(selectinload(Team.members)).where(Team.id == team_id))
    team = result.scalar_one_or_none()
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")
    return JSONResponse(content=jsonable_encoder(_team_to_dict(team, include_members=True)))


@router.delete("/teams/{team_id}", dependencies=[Depends(require_role(UserRole.ADMIN))])
async def delete_team(
    team_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: UserContext = Depends(get_current_user),
):
    """Delete a team (cascades to memberships; revokes group permissions manually if desired)."""
    from app.models.database import Team

    result = await db.execute(select(Team).where(Team.id == team_id))
    team = result.scalar_one_or_none()
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")

    team_name = team.team_name
    await db.delete(team)
    await db.commit()
    logger.info("team_deleted", team_id=team_id, team_name=team_name, by=user.user_id)
    await _write_audit(
        db,
        request=request,
        user=user,
        action="resource_deleted",
        summary=f"Deleted team '{team_name}'",
        details={"team_name": team_name, "resource_type": "team"},
    )
    return JSONResponse(content={"deleted": True, "team_id": team_id})


@router.post("/teams/{team_id}/members", dependencies=[Depends(require_role(UserRole.ADMIN))])
async def add_team_member(
    team_id: int,
    request: Request,
    req: TeamMemberRequest,
    db: AsyncSession = Depends(get_db),
    user: UserContext = Depends(get_current_user),
):
    """Add a user to a team."""
    from app.models.database import Team, TeamMembership

    result = await db.execute(select(Team).where(Team.id == team_id))
    team = result.scalar_one_or_none()
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")

    # Capture before commit/audit expires the object
    team_name_val = team.team_name

    membership = TeamMembership(team_id=team_id, user_id=req.user_id, user_email=req.user_email)
    db.add(membership)
    try:
        await db.commit()
        await db.refresh(membership, attribute_names=["id", "team_id", "user_id", "user_email", "created_at"])
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail="User is already a member of this team")

    # Capture membership data before audit write
    mem_id = membership.id
    mem_user_id = membership.user_id
    mem_user_email = membership.user_email

    logger.info("team_member_added", team=team_name_val, user_id=req.user_id, by=user.user_id)
    await _write_audit(
        db,
        request=request,
        user=user,
        action="permission_granted",
        summary=f"Added user '{req.user_id}' to team '{team_name_val}'",
        details={"team_name": team_name_val, "user_id": req.user_id, "resource_type": "team_membership"},
    )
    return JSONResponse(
        content={
            "id": mem_id,
            "team_id": team_id,
            "team_name": team_name_val,
            "user_id": mem_user_id,
            "user_email": mem_user_email,
        }
    )


@router.delete("/teams/{team_id}/members/{member_user_id}", dependencies=[Depends(require_role(UserRole.ADMIN))])
async def remove_team_member(
    team_id: int,
    member_user_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: UserContext = Depends(get_current_user),
):
    """Remove a user from a team."""
    from app.models.database import Team, TeamMembership

    result = await db.execute(select(Team).where(Team.id == team_id))
    team = result.scalar_one_or_none()
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")

    mem_result = await db.execute(
        select(TeamMembership).where(TeamMembership.team_id == team_id, TeamMembership.user_id == member_user_id)
    )
    membership = mem_result.scalar_one_or_none()
    if not membership:
        raise HTTPException(status_code=404, detail="Membership not found")

    # Capture before commit expires the object
    team_name_val = team.team_name

    await db.delete(membership)
    await db.commit()
    logger.info("team_member_removed", team=team_name_val, user_id=member_user_id, by=user.user_id)
    await _write_audit(
        db,
        request=request,
        user=user,
        action="permission_revoked",
        summary=f"Removed user '{member_user_id}' from team '{team_name_val}'",
        details={"team_name": team_name_val, "user_id": member_user_id, "resource_type": "team_membership"},
    )
    return JSONResponse(content={"deleted": True, "team_id": team_id, "user_id": member_user_id})


# ── Resource sync endpoint ─────────────────────────────────────────────────────


@router.post("/resources/sync", dependencies=[Depends(require_role(UserRole.ADMIN))])
async def sync_resources(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: UserContext = Depends(get_current_user),
):
    """
    Trigger a re-seed of the resource registry.

    Runs the same seeder that fires on startup — useful after deploying new
    plugins or modules without restarting the backend.
    """
    from app.core.resource_registry import seed_permissions, seed_resources

    await seed_resources(db)
    await seed_permissions(db)
    logger.info("resource_sync_triggered", by=user.user_id)
    await _write_audit(
        db,
        request=request,
        user=user,
        action="resource_updated",
        summary="Manual resource registry sync triggered",
        details={"action": "sync"},
    )
    # Return updated resource list
    result = await db.execute(select(Resource).order_by(Resource.resource_type, Resource.resource_name))
    rows = result.scalars().all()
    return JSONResponse(content={"synced": True, "resources": jsonable_encoder([_resource_to_dict(r) for r in rows])})
