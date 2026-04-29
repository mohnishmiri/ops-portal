"""
Admin endpoints for managing resources and permissions (granular RBAC).

Resources represent modules or pages in the portal.  Permissions grant a
subject (role or user) a specific access level (view/edit) to a resource.

All write operations require the ADMIN role.  Read operations are also
admin-only since they expose the full permission matrix.
"""

import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user, require_role
from app.core.database import get_db
from app.models.auth import UserContext, UserRole
from app.models.database import Permission, Resource

router = APIRouter()
logger = structlog.get_logger(__name__)


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


# ── Resource endpoints ────────────────────────────────────────────────────────

@router.post("/resources", dependencies=[Depends(require_role(UserRole.ADMIN))])
async def create_resource(
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
    return JSONResponse(content=jsonable_encoder(_resource_to_dict(resource)))


@router.delete("/resources/{resource_id}", dependencies=[Depends(require_role(UserRole.ADMIN))])
async def delete_resource(
    resource_id: int,
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
    await db.delete(resource)
    await db.commit()
    logger.info("resource_deleted", resource_id=resource_id, resource_name=resource.resource_name, by=user.user_id)
    return JSONResponse(content={"deleted": True, "resource_id": resource_id})


# ── Permission endpoints ──────────────────────────────────────────────────────

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


@router.post("/permissions", dependencies=[Depends(require_role(UserRole.ADMIN))])
async def create_permission(
    req: PermissionCreateRequest,
    db: AsyncSession = Depends(get_db),
    user: UserContext = Depends(get_current_user),
):
    # Validate subject_type and permission_type
    if req.subject_type not in ("user", "role"):
        raise HTTPException(status_code=400, detail="subject_type must be 'user' or 'role'")
    if req.permission_type not in ("view", "edit"):
        raise HTTPException(status_code=400, detail="permission_type must be 'view' or 'edit'")

    # Verify resource exists
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
    # Attach resource for the response (async sessions can't lazy-load)
    perm.resource = resource
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
        perm.resource = resource  # attach for _permission_to_dict
        output.append(_permission_to_dict(perm))
    return JSONResponse(content=jsonable_encoder(output))


@router.delete("/permissions/{permission_id}", dependencies=[Depends(require_role(UserRole.ADMIN))])
async def delete_permission(
    permission_id: int,
    db: AsyncSession = Depends(get_db),
    user: UserContext = Depends(get_current_user),
):
    result = await db.execute(select(Permission).where(Permission.id == permission_id))
    perm = result.scalar_one_or_none()
    if not perm:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Permission not found")
    subject = f"{perm.subject_type}:{perm.subject_id}"
    resource_id = perm.resource_id
    await db.delete(perm)
    await db.commit()
    logger.info("permission_revoked", permission_id=permission_id, subject=subject, resource_id=resource_id, by=user.user_id)
    return JSONResponse(content={"deleted": True, "permission_id": permission_id})
