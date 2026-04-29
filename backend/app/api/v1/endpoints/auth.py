"""Auth API — authenticated user context, roles, and effective permissions."""

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.core.database import get_db
from app.models.auth import UserContext, UserRole
from app.models.database import Permission, Resource

router = APIRouter()


@router.get(
    "/me",
    summary="Current user context",
    response_model=None,
)
async def get_me(user: UserContext = Depends(get_current_user)) -> dict:
    """Return the authenticated user's identity and mapped roles."""
    return {
        "user_id": user.user_id,
        "display_name": user.display_name,
        "email": user.email,
        "roles": [r.value for r in user.roles],
        "is_admin": user.is_admin,
        "can_write": user.can_write,
        "tenant_id": user.tenant_id,
    }


@router.get(
    "/my-permissions",
    summary="Current user's effective module/page permissions",
    response_model=None,
)
async def get_my_permissions(
    user: UserContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """
    Return the calling user's effective access for every registered resource.

    Admins implicitly have 'view' and 'edit' on all resources — no DB lookup
    needed.  For non-admin users the effective permissions are the union of:
      • user-specific permission records (subject_type='user', subject_id=user_id)
      • role-based permission records for any role the user holds

    Parent module access is inherited by child pages: if a role has 'view' on
    a module resource, that access also covers every page that belongs to it.

    Response shape:
    {
      "is_admin": true,
      "modules": {"aks_operations": ["view", "edit"], ...},
      "pages":   {"aks_main": ["view"], ...}
    }
    """
    if user.is_admin:
        # Admin sees everything — fetch all resources and grant full access
        result = await db.execute(select(Resource))
        resources = result.scalars().all()
        modules: dict[str, list[str]] = {}
        pages: dict[str, list[str]] = {}
        for r in resources:
            target = modules if r.resource_type == "module" else pages
            target[r.resource_name] = ["view", "edit"]
        return {"is_admin": True, "modules": modules, "pages": pages}

    # ── Collect direct permission records ─────────────────────────────────
    subject_ids_for_user = [user.user_id]
    role_subject_ids = [role.value for role in user.roles]

    result = await db.execute(
        select(Permission, Resource)
        .join(Resource, Permission.resource_id == Resource.id)
        .where(
            (
                (Permission.subject_type == "user") & (Permission.subject_id == user.user_id)
            )
            | (
                (Permission.subject_type == "role")
                & Permission.subject_id.in_(role_subject_ids)
            )
        )
    )
    rows = result.all()

    # ── Build raw access map: resource_id → set of permission types ───────
    resource_access: dict[int, set[str]] = {}
    resource_map: dict[int, Resource] = {}
    for perm, resource in rows:
        resource_map[resource.id] = resource
        resource_access.setdefault(resource.id, set()).add(perm.permission_type)

    # ── Load all resources to resolve parent inheritance ──────────────────
    all_res_result = await db.execute(select(Resource))
    all_resources = all_res_result.scalars().all()
    id_to_resource: dict[int, Resource] = {r.id: r for r in all_resources}

    # Module access inherits to all child pages
    for r in all_resources:
        if r.parent_id and r.parent_id in resource_access:
            # Parent module has access → child page inherits
            resource_access.setdefault(r.id, set()).update(resource_access[r.parent_id])
            resource_map[r.id] = r

    # ── Split into modules / pages ────────────────────────────────────────
    modules_out: dict[str, list[str]] = {}
    pages_out: dict[str, list[str]] = {}

    for res_id, perms in resource_access.items():
        resource = id_to_resource.get(res_id)
        if not resource:
            continue
        perms_sorted = sorted(perms)  # deterministic order
        if resource.resource_type == "module":
            modules_out[resource.resource_name] = perms_sorted
        else:
            pages_out[resource.resource_name] = perms_sorted

    return {
        "is_admin": False,
        "modules": modules_out,
        "pages": pages_out,
    }
