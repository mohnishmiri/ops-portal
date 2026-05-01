"""
Admin endpoints for managing resources and permissions (granular RBAC).

Resources represent modules or pages in the portal.  Permissions grant a
subject (role or user) a specific access level (view/edit) to a resource.

All write operations require the ADMIN role.  Read operations are also
admin-only since they expose the full permission matrix.

Every mutating operation writes a row to the shared audit_logs table so
admins have a queryable, tamper-evident trail of who changed what and when.
"""

import structlog
from datetime import UTC, datetime, timedelta
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
    subject_type: str = Field(..., description="'user' or 'role'")
    subject_id: str = Field(..., description="user_id or role name (admin/write/read)")
    resource_id: int = Field(...)
    permission_type: str = Field(..., description="'view' or 'edit'")


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
        db, request=request, user=user,
        action="resource_created",
        summary=f"Created {req.resource_type} resource '{req.resource_name}'",
        details={"resource_name": req.resource_name, "resource_type": req.resource_type,
                 "route_path": req.route_path},
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
        db, request=request, user=user,
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
        db, request=request, user=user,
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
    if req.subject_type not in ("user", "role"):
        raise HTTPException(status_code=400, detail="subject_type must be 'user' or 'role'")
    if req.permission_type not in ("view", "edit"):
        raise HTTPException(status_code=400, detail="permission_type must be 'view' or 'edit'")

    res = await db.execute(select(Resource).where(Resource.id == req.resource_id))
    resource = res.scalar_one_or_none()
    if not resource:
        raise HTTPException(status_code=404, detail="Resource not found")

    perm = Permission(
        subject_type=req.subject_type,
        subject_id=req.subject_id,
        resource_id=req.resource_id,
        permission_type=req.permission_type,
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
        db, request=request, user=user,
        action="permission_granted",
        summary=(
            f"Granted {req.permission_type} on '{resource.resource_name}' "
            f"to {req.subject_type}:{req.subject_id}"
        ),
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
        db, request=request, user=user,
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
