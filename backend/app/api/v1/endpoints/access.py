"""
Access API — projects, apps, subscription grants, and access requests.

``/access/*`` is for every signed-in user: see your own access, browse the
project/app catalog, and request access.  ``/access/admin/*`` is for Project
Admins (Entra Admin role, limited to their projects) and Super Admins; the
service enforces which project each call may touch.

These routes are exempt from the subscription target check
(``app.core.target_access``) because they authorize their own targets — a
request *for* a subscription must not require access to it already.
"""

from __future__ import annotations

from typing import Literal

import structlog
from fastapi import APIRouter, BackgroundTasks, Depends, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user, require_role
from app.core.access_scope import resolve_access_scope
from app.core.database import get_db
from app.schemas.auth import UserContext, UserRole
from app.services.access_service import AccessService, Actor

logger = structlog.get_logger(__name__)

router = APIRouter()

Tier = Literal["prod", "nonprod"]
Level = Literal["read", "write"]


async def _actor(request: Request, user: UserContext, db: AsyncSession) -> Actor:
    return Actor(user=user, scope=await resolve_access_scope(request, user, db))


# ── Notifications ─────────────────────────────────────────────────────────


async def _notify(recipients: list[str], subject: str, heading: str, lines: list[str], path: str) -> None:
    if not recipients:
        return
    try:
        from app.services.email_notification_service import EmailNotificationService

        await EmailNotificationService().send_access_notification(recipients, subject, heading, lines, path)
    except Exception as exc:
        logger.warning("access_notification_failed", subject=subject, error=str(exc)[:200])


def _item_label(item: dict) -> str:
    target = item["app_name"] if item["scope_type"] == "app" else f"{item['project_name']} (all apps)"
    tier = "Prod" if item["tier"] == "prod" else "Non-Prod"
    return f"{target} · {tier} · {item['requested_level'].title()}"


# ── Self-service ──────────────────────────────────────────────────────────


@router.get("/me", summary="My access: grants, admin projects, pending requests")
async def get_my_access(
    request: Request,
    user: UserContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    scope = await resolve_access_scope(request, user, db)
    return await AccessService(db).my_access(user, scope)


@router.get("/catalog", summary="Projects and apps that access can be requested for")
async def get_catalog(
    user: UserContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    return await AccessService(db).catalog()


class RequestItemIn(BaseModel):
    scope_type: Literal["project", "app"]
    project_id: int | None = None
    app_id: int | None = None
    tier: Tier
    level: Level = "read"


class AccessRequestIn(BaseModel):
    justification: str = Field(min_length=1, max_length=2000)
    items: list[RequestItemIn] = Field(min_length=1, max_length=50)


@router.post("/requests", summary="Request access to projects or apps")
async def submit_request(
    body: AccessRequestIn,
    background: BackgroundTasks,
    user: UserContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    svc = AccessService(db)
    result = await svc.submit_request(
        user,
        justification=body.justification,
        items=[i.model_dump() for i in body.items],
    )
    approvers = await svc.approver_emails({i["project_id"] for i in result["items"]})
    background.add_task(
        _notify,
        [e for e in approvers if e.lower() != (user.email or "").lower()],
        f"Ops Portal access request from {user.display_name}",
        f"{user.display_name} ({user.email}) requested access",
        [*(_item_label(i) for i in result["items"]), f"Reason: {body.justification}"],
        "/access/requests",
    )
    return result


@router.get("/requests/mine", summary="My access requests")
async def list_my_requests(
    user: UserContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    return await AccessService(db).my_requests(user)


@router.post("/requests/{request_id}/cancel", summary="Cancel my pending request")
async def cancel_request(
    request_id: int,
    user: UserContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    return await AccessService(db).cancel_request(user, request_id)


# ── Administration (Project Admin / Super Admin) ──────────────────────────

_admin = require_role(UserRole.ADMIN)


@router.get("/admin/projects", summary="Projects I administer (all, for a Super Admin)")
async def admin_list_projects(
    request: Request,
    user: UserContext = Depends(_admin),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    actor = await _actor(request, user, db)
    return await AccessService(db).list_projects(actor)


class ProjectIn(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str | None = None
    project_key: str | None = Field(default=None, max_length=64)


class ProjectPatch(BaseModel):
    name: str | None = Field(default=None, max_length=255)
    description: str | None = None
    is_active: bool | None = None


@router.post("/admin/projects", summary="Create a project (Super Admin)")
async def admin_create_project(
    body: ProjectIn,
    request: Request,
    user: UserContext = Depends(_admin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    actor = await _actor(request, user, db)
    return await AccessService(db).create_project(
        actor, name=body.name, description=body.description, project_key=body.project_key
    )


@router.patch("/admin/projects/{project_id}", summary="Rename or (de)activate a project (Super Admin)")
async def admin_update_project(
    project_id: int,
    body: ProjectPatch,
    request: Request,
    user: UserContext = Depends(_admin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    actor = await _actor(request, user, db)
    return await AccessService(db).update_project(
        actor, project_id, name=body.name, description=body.description, is_active=body.is_active
    )


@router.delete("/admin/projects/{project_id}", summary="Delete an empty project (Super Admin)")
async def admin_delete_project(
    project_id: int,
    request: Request,
    user: UserContext = Depends(_admin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    actor = await _actor(request, user, db)
    return await AccessService(db).delete_project(actor, project_id)


class AppIn(BaseModel):
    app_code: str = Field(min_length=1, max_length=32)
    name: str = Field(min_length=1, max_length=255)
    description: str | None = None
    place_matching: bool = True


class AppPatch(BaseModel):
    name: str | None = Field(default=None, max_length=255)
    description: str | None = None
    project_id: int | None = None


@router.post("/admin/projects/{project_id}/apps", summary="Add an app to a project (Super Admin)")
async def admin_create_app(
    project_id: int,
    body: AppIn,
    request: Request,
    user: UserContext = Depends(_admin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    actor = await _actor(request, user, db)
    return await AccessService(db).create_app(
        actor,
        project_id,
        app_code=body.app_code,
        name=body.name,
        description=body.description,
        place_matching=body.place_matching,
    )


@router.patch("/admin/apps/{app_id}", summary="Rename an app or move it to another project (Super Admin)")
async def admin_update_app(
    app_id: int,
    body: AppPatch,
    request: Request,
    user: UserContext = Depends(_admin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    actor = await _actor(request, user, db)
    return await AccessService(db).update_app(
        actor, app_id, name=body.name, description=body.description, project_id=body.project_id
    )


@router.delete("/admin/apps/{app_id}", summary="Delete an app with no subscriptions (Super Admin)")
async def admin_delete_app(
    app_id: int,
    request: Request,
    user: UserContext = Depends(_admin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    actor = await _actor(request, user, db)
    return await AccessService(db).delete_app(actor, app_id)


class ProjectAdminIn(BaseModel):
    user_id: str = Field(min_length=1, max_length=255)


@router.post("/admin/projects/{project_id}/admins", summary="Appoint a project admin (Super Admin)")
async def admin_add_project_admin(
    project_id: int,
    body: ProjectAdminIn,
    request: Request,
    user: UserContext = Depends(_admin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    actor = await _actor(request, user, db)
    return await AccessService(db).add_project_admin(actor, project_id, body.user_id)


@router.delete("/admin/projects/{project_id}/admins/{user_id}", summary="Remove a project admin (Super Admin)")
async def admin_remove_project_admin(
    project_id: int,
    user_id: str,
    request: Request,
    user: UserContext = Depends(_admin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    actor = await _actor(request, user, db)
    return await AccessService(db).remove_project_admin(actor, project_id, user_id)


@router.get("/admin/subscriptions", summary="Every subscription with its app, tier and suggestion (Super Admin)")
async def admin_list_subscriptions(
    request: Request,
    user: UserContext = Depends(_admin),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    actor = await _actor(request, user, db)
    return await AccessService(db).list_subscription_placements(actor)


class PlacementIn(BaseModel):
    app_id: int | None = None
    tier: Tier


@router.put("/admin/subscriptions/{subscription_id}", summary="Place a subscription in an app and tier (Super Admin)")
async def admin_place_subscription(
    subscription_id: str,
    body: PlacementIn,
    request: Request,
    user: UserContext = Depends(_admin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    actor = await _actor(request, user, db)
    return await AccessService(db).place_subscription(actor, subscription_id, app_id=body.app_id, tier=body.tier)


@router.get("/admin/users", summary="Users who have signed in (for granting access)")
async def admin_list_users(
    search: str | None = Query(default=None, max_length=100),
    user: UserContext = Depends(_admin),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    return await AccessService(db).list_users(search)


@router.get("/admin/grants", summary="Grants in the projects I administer")
async def admin_list_grants(
    request: Request,
    project_id: int | None = Query(default=None),
    user_id: str | None = Query(default=None, max_length=255),
    user: UserContext = Depends(_admin),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    actor = await _actor(request, user, db)
    return await AccessService(db).list_grants(actor, project_id=project_id, user_id=user_id)


class GrantIn(BaseModel):
    user_ids: list[str] = Field(default_factory=list, max_length=200)
    everyone: bool = False
    scope_type: Literal["project", "app", "subscription"]
    project_id: int | None = None
    app_id: int | None = None
    subscription_id: str | None = None
    tiers: list[Tier] = Field(default_factory=list)
    level: Level


class GrantPatch(BaseModel):
    level: Level


@router.post("/admin/grants", summary="Grant users access to a project, app or subscription")
async def admin_create_grants(
    body: GrantIn,
    request: Request,
    user: UserContext = Depends(_admin),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    actor = await _actor(request, user, db)
    return await AccessService(db).create_grants(
        actor,
        user_ids=body.user_ids,
        everyone=body.everyone,
        scope_type=body.scope_type,
        project_id=body.project_id,
        app_id=body.app_id,
        subscription_id=body.subscription_id,
        tiers=list(body.tiers),
        level=body.level,
    )


@router.patch("/admin/grants/{grant_id}", summary="Change a grant's level")
async def admin_update_grant(
    grant_id: int,
    body: GrantPatch,
    request: Request,
    user: UserContext = Depends(_admin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    actor = await _actor(request, user, db)
    return await AccessService(db).update_grant(actor, grant_id, level=body.level)


@router.delete("/admin/grants/{grant_id}", summary="Revoke a grant")
async def admin_revoke_grant(
    grant_id: int,
    request: Request,
    user: UserContext = Depends(_admin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    actor = await _actor(request, user, db)
    return await AccessService(db).revoke_grant(actor, grant_id)


@router.get("/admin/requests", summary="Access requests I can decide")
async def admin_list_requests(
    request: Request,
    status: Literal["pending", "approved", "rejected", "partially_approved", "cancelled", "all"] = "pending",
    user: UserContext = Depends(_admin),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    actor = await _actor(request, user, db)
    return await AccessService(db).list_requests_for_approver(actor, status_filter=None if status == "all" else status)


class DecisionIn(BaseModel):
    decision: Literal["approve", "reject"]
    level: Level | None = None
    comment: str | None = Field(default=None, max_length=1000)


@router.post("/admin/requests/{request_id}/items/{item_id}/decision", summary="Approve or reject one requested item")
async def admin_decide_item(
    request_id: int,
    item_id: int,
    body: DecisionIn,
    background: BackgroundTasks,
    request: Request,
    user: UserContext = Depends(_admin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    actor = await _actor(request, user, db)
    result = await AccessService(db).decide_item(
        actor,
        request_id,
        item_id,
        approve=body.decision == "approve",
        level=body.level,
        comment=body.comment,
    )
    item = next(i for i in result["items"] if i["id"] == item_id)
    outcome = f"approved ({item['granted_level']})" if item["status"] == "approved" else "rejected"
    lines = [f"{_item_label(item)} — {outcome} by {user.display_name}"]
    if item.get("decision_comment"):
        lines.append(f"Comment: {item['decision_comment']}")
    background.add_task(
        _notify,
        [result["requester_email"]] if result.get("requester_email") else [],
        f"Ops Portal access request {outcome.split(' ')[0]}",
        "Your access request was updated",
        lines,
        "/access",
    )
    return result
