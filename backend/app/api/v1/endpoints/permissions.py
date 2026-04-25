"""
Admin endpoints for managing resources and permissions (granular RBAC).
"""
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel, Field
from app.core.database import get_db
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from app.auth import require_role
from app.models.database import Resource, Permission
from app.models.auth import UserRole
import structlog
from sqlalchemy.exc import IntegrityError

router = APIRouter()

logger = structlog.get_logger(__name__)

class ResourceCreateRequest(BaseModel):
    resource_type: str = Field(..., description="module or page")
    resource_name: str = Field(...)
    description: str | None = None

class PermissionCreateRequest(BaseModel):
    subject_type: str = Field(..., description="user or role")
    subject_id: str = Field(...)
    resource_id: int = Field(...)
    permission_type: str = Field(..., description="view or edit")

@router.post("/resources", dependencies=[Depends(require_role(UserRole.ADMIN))])
async def create_resource(req: ResourceCreateRequest, db: AsyncSession = Depends(get_db)):
    resource = Resource(
        resource_type=req.resource_type,
        resource_name=req.resource_name,
        description=req.description,
    )
    db.add(resource)
    try:
        await db.commit()
        await db.refresh(resource)
    except IntegrityError:
        await db.rollback()
        # Resource already exists — load and return existing record
        res = await db.execute(Resource.__table__.select().where(Resource.resource_name == req.resource_name))
        row = res.mappings().first()
        if row:
            resource = dict(row)
            content = jsonable_encoder({
                "id": resource.get("id"),
                "resource_type": resource.get("resource_type"),
                "resource_name": resource.get("resource_name"),
                "description": resource.get("description"),
            })
            return JSONResponse(content=content)
        raise
    # return plain dict for safe JSON serialization
    content = jsonable_encoder({
        "id": resource.id,
        "resource_type": resource.resource_type,
        "resource_name": resource.resource_name,
        "description": resource.description,
    })
    return JSONResponse(content=content)

@router.get("/resources", dependencies=[Depends(require_role(UserRole.ADMIN))])
async def list_resources(db: AsyncSession = Depends(get_db)):
    result = await db.execute(Resource.__table__.select())
    # return list of plain dicts to ensure JSON serialization
    rows = result.mappings().all()
    content = [dict(r) for r in rows]
    try:
        logger.debug("list_resources.content_sample", type=type(content), sample=content[:3])
    except Exception:
        logger.exception("failed to log list_resources sample")
    return JSONResponse(content=jsonable_encoder(content))

@router.post("/permissions", dependencies=[Depends(require_role(UserRole.ADMIN))])
async def create_permission(req: PermissionCreateRequest, db: AsyncSession = Depends(get_db)):
    perm = Permission(
        subject_type=req.subject_type,
        subject_id=req.subject_id,
        resource_id=req.resource_id,
        permission_type=req.permission_type,
    )
    db.add(perm)
    await db.commit()
    await db.refresh(perm)
    content = jsonable_encoder({
        "id": perm.id,
        "subject_type": perm.subject_type,
        "subject_id": perm.subject_id,
        "resource_id": perm.resource_id,
        "permission_type": perm.permission_type,
    })
    return JSONResponse(content=content)

@router.get("/permissions", dependencies=[Depends(require_role(UserRole.ADMIN))])
async def list_permissions(db: AsyncSession = Depends(get_db)):
    result = await db.execute(Permission.__table__.select())
    rows = result.mappings().all()
    content = [dict(r) for r in rows]
    try:
        logger.debug("list_permissions.content_sample", type=type(content), sample=content[:3])
    except Exception:
        logger.exception("failed to log list_permissions sample")
    return JSONResponse(content=jsonable_encoder(content))
