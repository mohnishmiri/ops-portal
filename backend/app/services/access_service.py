"""
Project / app / subscription access management.

Owns the data behind ``app.core.access_scope``: projects and their apps,
where each subscription sits, project admins, grants, and the access request
and approval workflow.  Authorization rules enforced here:

* Super Admin — everything.
* Project Admin — grants, approvals and the user list for *their* projects
  only.  They cannot create projects or apps, move subscriptions, appoint
  other project admins, or grant to "everyone".
* Nobody decides their own request.

Every change is written to ``audit_logs`` (resource_type ``access_management``)
after it commits, and drops the cached topology when placement changes.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime

import structlog
from fastapi import HTTPException, status
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.access_scope import (
    EVERYONE_SUBJECT,
    LEVELS,
    TIERS,
    AccessScope,
    classify_subscription,
    compute_access_scope,
    invalidate_access_topology,
    load_topology,
    subscriptions_for_grant,
)
from app.models.database import (
    AccessGrant,
    AccessRequest,
    AccessRequestItem,
    AdminConfig,
    AdminSubscription,
    AuditLog,
    PortalUser,
    Project,
    ProjectAdmin,
    ProjectApp,
)
from app.schemas.auth import UserContext, UserRole

logger = structlog.get_logger(__name__)

BOOTSTRAP_MARKER_KEY = "access_model_bootstrapped_at"
DEFAULT_PROJECT_KEY = "commissions"
DEFAULT_PROJECT_NAME = "Commissions"
UNCLASSIFIED_APP_CODE = "UNCLASSIFIED"


def _bad_request(message: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=message)


def _forbidden(message: str = "You do not have permission to manage access for this project.") -> HTTPException:
    return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=message)


def _not_found(what: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"{what} not found")


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.strip().lower()).strip("-")[:64]


@dataclass(frozen=True)
class Actor:
    """Who is making an access-management call, and what they administer."""

    user: UserContext
    scope: AccessScope

    @property
    def is_super_admin(self) -> bool:
        return self.user.is_super_admin

    def administers(self, project_id: int) -> bool:
        return self.is_super_admin or project_id in self.scope.admin_project_ids

    def require_project_admin(self, project_id: int) -> None:
        if not self.administers(project_id):
            raise _forbidden()

    def require_super_admin(self) -> None:
        if not self.is_super_admin:
            raise _forbidden("Only a Super Admin can do this.")


class AccessService:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    # ── Audit ──────────────────────────────────────────────────────────

    async def _audit(self, actor: UserContext | None, action: str, summary: str, details: dict) -> None:
        """Record an access change.  Called after commit; never raises."""
        try:
            self._db.add(
                AuditLog(
                    user_id=actor.user_id if actor else "system",
                    user_email=actor.email if actor else None,
                    action=action,
                    resource_type="access_management",
                    resource_id=None,
                    details={"summary": summary, **details},
                    status="success",
                )
            )
            await self._db.commit()
        except Exception as exc:
            await self._db.rollback()
            logger.warning("access_audit_failed", action=action, error=str(exc)[:200])

    # ── Portal users ───────────────────────────────────────────────────

    async def record_sign_in(self, user: UserContext) -> None:
        """Upsert the user into ``portal_users``.  Best effort."""
        try:
            row = await self._db.get(PortalUser, user.user_id)
            now = datetime.utcnow()
            roles = ",".join(r.value for r in user.roles)
            if row is None:
                self._db.add(
                    PortalUser(
                        user_id=user.user_id,
                        object_id=user.object_id,
                        email=user.email,
                        display_name=user.display_name,
                        roles=roles,
                        first_seen_at=now,
                        last_seen_at=now,
                    )
                )
            else:
                row.object_id = user.object_id
                row.email = user.email or row.email
                row.display_name = user.display_name or row.display_name
                row.roles = roles
                row.last_seen_at = now
            await self._db.commit()
        except Exception as exc:
            await self._db.rollback()
            logger.warning("portal_user_record_failed", user_id=user.user_id, error=str(exc)[:200])

    async def list_users(self, search: str | None = None, limit: int = 200) -> list[dict]:
        stmt = select(PortalUser).order_by(PortalUser.display_name)
        if search:
            like = f"%{search.strip().lower()}%"
            stmt = stmt.where(
                or_(func.lower(PortalUser.email).like(like), func.lower(PortalUser.display_name).like(like))
            )
        rows = (await self._db.execute(stmt.limit(limit))).scalars().all()
        return [
            {
                "user_id": r.user_id,
                "email": r.email,
                "display_name": r.display_name,
                "roles": [x for x in (r.roles or "").split(",") if x],
                "last_seen_at": _iso(r.last_seen_at),
            }
            for r in rows
        ]

    async def _portal_user(self, user_id: str) -> PortalUser:
        row = await self._db.get(PortalUser, user_id)
        if row is None:
            raise _bad_request("That user has not signed in to the portal yet.")
        return row

    # ── Projects & apps ────────────────────────────────────────────────

    async def _project(self, project_id: int) -> Project:
        row = await self._db.get(Project, project_id)
        if row is None:
            raise _not_found("Project")
        return row

    async def _app(self, app_id: int) -> ProjectApp:
        row = await self._db.get(ProjectApp, app_id)
        if row is None:
            raise _not_found("App")
        return row

    async def list_projects(self, actor: Actor | None = None) -> list[dict]:
        """Projects with their apps and subscription counts per tier.

        With an ``actor`` that is not a Super Admin, only projects they
        administer are returned.
        """
        projects = (await self._db.execute(select(Project).order_by(Project.name))).scalars().all()
        apps = (await self._db.execute(select(ProjectApp).order_by(ProjectApp.name))).scalars().all()
        counts = (
            await self._db.execute(
                select(AdminSubscription.app_id, AdminSubscription.tier, func.count())
                .where(AdminSubscription.app_id.is_not(None))
                .group_by(AdminSubscription.app_id, AdminSubscription.tier)
            )
        ).all()
        tier_counts: dict[int, dict[str, int]] = {}
        for app_id, tier, n in counts:
            t = tier if tier in TIERS else "prod"
            tier_counts.setdefault(app_id, {"prod": 0, "nonprod": 0})[t] += n

        admins = (await self._db.execute(select(ProjectAdmin))).scalars().all()
        admins_by_project: dict[int, list[dict]] = {}
        for a in admins:
            admins_by_project.setdefault(a.project_id, []).append({"user_id": a.user_id, "email": a.user_email})

        out = []
        for p in projects:
            if actor is not None and not actor.administers(p.id):
                continue
            out.append(
                {
                    "id": p.id,
                    "project_key": p.project_key,
                    "name": p.name,
                    "description": p.description,
                    "is_active": p.is_active,
                    "admins": admins_by_project.get(p.id, []),
                    "apps": [
                        {
                            "id": a.id,
                            "app_code": a.app_code,
                            "name": a.name,
                            "description": a.description,
                            "subscription_counts": tier_counts.get(a.id, {"prod": 0, "nonprod": 0}),
                        }
                        for a in apps
                        if a.project_id == p.id
                    ],
                }
            )
        return out

    async def catalog(self) -> list[dict]:
        """Active projects and apps, for the access request form.

        Names only — no subscription IDs — so it is safe to show every user.
        """
        projects = await self.list_projects()
        return [
            {
                "id": p["id"],
                "name": p["name"],
                "description": p["description"],
                "apps": [
                    {
                        "id": a["id"],
                        "name": a["name"],
                        "app_code": a["app_code"],
                        "tiers": [t for t in TIERS if a["subscription_counts"][t] > 0],
                    }
                    for a in p["apps"]
                ],
            }
            for p in projects
            if p["is_active"]
        ]

    async def create_project(
        self, actor: Actor, *, name: str, description: str | None, project_key: str | None
    ) -> dict:
        actor.require_super_admin()
        name = name.strip()
        if not name:
            raise _bad_request("Project name is required.")
        key = slugify(project_key or name)
        if not key:
            raise _bad_request("Project key is required.")
        if (await self._db.execute(select(Project.id).where(Project.project_key == key))).first():
            raise _bad_request(f"A project with key '{key}' already exists.")
        row = Project(
            project_key=key,
            name=name,
            description=description,
            created_by=actor.user.email,
            updated_by=actor.user.email,
        )
        self._db.add(row)
        await self._db.commit()
        await self._audit(actor.user, "access_project_create", f"Created project {name}", {"project_id": row.id})
        return {"id": row.id, "project_key": key, "name": name}

    async def update_project(
        self,
        actor: Actor,
        project_id: int,
        *,
        name: str | None,
        description: str | None,
        is_active: bool | None,
    ) -> dict:
        actor.require_super_admin()
        row = await self._project(project_id)
        if name is not None and name.strip():
            row.name = name.strip()
        if description is not None:
            row.description = description
        if is_active is not None:
            row.is_active = is_active
        row.updated_by = actor.user.email
        await self._db.commit()
        invalidate_access_topology()
        await self._audit(
            actor.user,
            "access_project_update",
            f"Updated project {row.name}",
            {"project_id": project_id, "is_active": row.is_active},
        )
        return {"id": row.id, "name": row.name, "is_active": row.is_active}

    async def delete_project(self, actor: Actor, project_id: int) -> dict:
        actor.require_super_admin()
        row = await self._project(project_id)
        if (await self._db.execute(select(ProjectApp.id).where(ProjectApp.project_id == project_id))).first():
            raise _bad_request("Move or delete the project's apps first.")
        name = row.name
        await self._db.delete(row)
        await self._db.commit()
        invalidate_access_topology()
        await self._audit(actor.user, "access_project_delete", f"Deleted project {name}", {"project_id": project_id})
        return {"deleted": True}

    async def create_app(
        self,
        actor: Actor,
        project_id: int,
        *,
        app_code: str,
        name: str,
        description: str | None,
        place_matching: bool = True,
    ) -> dict:
        """Add an app.  With ``place_matching`` unplaced subscriptions whose
        name carries this AppID are placed into it straight away."""
        actor.require_super_admin()
        await self._project(project_id)
        code = app_code.strip().upper()
        if not code or not name.strip():
            raise _bad_request("App code and name are required.")
        if (await self._db.execute(select(ProjectApp.id).where(ProjectApp.app_code == code))).first():
            raise _bad_request(f"An app with code '{code}' already exists.")
        row = ProjectApp(
            project_id=project_id,
            app_code=code,
            name=name.strip(),
            description=description,
            created_by=actor.user.email,
            updated_by=actor.user.email,
        )
        self._db.add(row)
        await self._db.flush()

        placed: list[str] = []
        if place_matching:
            unplaced = (
                (await self._db.execute(select(AdminSubscription).where(AdminSubscription.app_id.is_(None))))
                .scalars()
                .all()
            )
            for sub in unplaced:
                c = classify_subscription(sub.subscription_name, sub.environment)
                if c.app_code == code:
                    sub.app_id = row.id
                    sub.tier = c.tier
                    placed.append(sub.subscription_id)

        await self._db.commit()
        invalidate_access_topology()
        await self._audit(
            actor.user,
            "access_app_create",
            f"Created app {row.name} ({code})",
            {"project_id": project_id, "app_id": row.id, "placed_subscriptions": placed},
        )
        return {"id": row.id, "app_code": code, "name": row.name, "placed_subscriptions": placed}

    async def update_app(
        self,
        actor: Actor,
        app_id: int,
        *,
        name: str | None,
        description: str | None,
        project_id: int | None,
    ) -> dict:
        actor.require_super_admin()
        row = await self._app(app_id)
        if project_id is not None and project_id != row.project_id:
            await self._project(project_id)
            # Grants are anchored to a project; app grants follow the app.
            for grant in (
                (await self._db.execute(select(AccessGrant).where(AccessGrant.app_id == app_id))).scalars().all()
            ):
                grant.project_id = project_id
            row.project_id = project_id
        if name is not None and name.strip():
            row.name = name.strip()
        if description is not None:
            row.description = description
        row.updated_by = actor.user.email
        await self._db.commit()
        invalidate_access_topology()
        await self._audit(
            actor.user,
            "access_app_update",
            f"Updated app {row.name}",
            {"app_id": app_id, "project_id": row.project_id},
        )
        return {"id": row.id, "name": row.name, "project_id": row.project_id}

    async def delete_app(self, actor: Actor, app_id: int) -> dict:
        actor.require_super_admin()
        row = await self._app(app_id)
        if (await self._db.execute(select(AdminSubscription.id).where(AdminSubscription.app_id == app_id))).first():
            raise _bad_request("Move the app's subscriptions to another app first.")
        name = row.name
        await self._db.delete(row)
        await self._db.commit()
        invalidate_access_topology()
        await self._audit(actor.user, "access_app_delete", f"Deleted app {name}", {"app_id": app_id})
        return {"deleted": True}

    # ── Subscription placement ─────────────────────────────────────────

    async def list_subscription_placements(self, actor: Actor) -> list[dict]:
        actor.require_super_admin()
        rows = (
            await self._db.execute(
                select(AdminSubscription, ProjectApp, Project)
                .outerjoin(ProjectApp, AdminSubscription.app_id == ProjectApp.id)
                .outerjoin(Project, ProjectApp.project_id == Project.id)
                .order_by(AdminSubscription.subscription_name)
            )
        ).all()
        codes = {
            code: app_id for app_id, code in (await self._db.execute(select(ProjectApp.id, ProjectApp.app_code))).all()
        }
        out = []
        for sub, app, project in rows:
            suggestion = classify_subscription(sub.subscription_name, sub.environment)
            out.append(
                {
                    "subscription_id": sub.subscription_id,
                    "subscription_name": sub.subscription_name,
                    "enabled": sub.enabled,
                    "monitored": sub.monitored,
                    "environment": sub.environment,
                    "tier": sub.tier,
                    "app_id": app.id if app else None,
                    "app_name": app.name if app else None,
                    "project_id": project.id if project else None,
                    "project_name": project.name if project else None,
                    "suggested_tier": suggestion.tier,
                    "suggested_app_code": suggestion.app_code,
                    "suggested_app_name": suggestion.app_name,
                    "suggested_app_id": codes.get((suggestion.app_code or "").upper()),
                }
            )
        return out

    async def place_subscription(self, actor: Actor, subscription_id: str, *, app_id: int | None, tier: str) -> dict:
        actor.require_super_admin()
        if tier not in TIERS:
            raise _bad_request("Tier must be 'prod' or 'nonprod'.")
        row = (
            await self._db.execute(
                select(AdminSubscription).where(
                    func.lower(AdminSubscription.subscription_id) == subscription_id.lower()
                )
            )
        ).scalar_one_or_none()
        if row is None:
            raise _not_found("Subscription")
        if app_id is not None:
            await self._app(app_id)
        before = {"app_id": row.app_id, "tier": row.tier}
        row.app_id = app_id
        row.tier = tier
        row.updated_by = actor.user.email
        await self._db.commit()
        invalidate_access_topology()
        await self._audit(
            actor.user,
            "access_subscription_place",
            f"Placed subscription {row.subscription_name}",
            {"subscription_id": row.subscription_id, "before": before, "after": {"app_id": app_id, "tier": tier}},
        )
        return {"subscription_id": row.subscription_id, "app_id": app_id, "tier": tier}

    async def auto_place(self, rows: list[AdminSubscription]) -> list[str]:
        """Place unplaced subscriptions whose name carries a known AppID.

        Does not commit — callers commit with their own change.  Subscriptions
        with no recognisable AppID stay unplaced (Super Admin only).
        """
        if not rows:
            return []
        codes = {
            code.upper(): app_id
            for app_id, code in (await self._db.execute(select(ProjectApp.id, ProjectApp.app_code))).all()
        }
        placed = []
        for row in rows:
            if row.app_id is not None:
                continue
            c = classify_subscription(row.subscription_name, row.environment)
            if c.app_code and c.app_code.upper() in codes:
                row.app_id = codes[c.app_code.upper()]
                row.tier = c.tier
                placed.append(row.subscription_id)
        if placed:
            invalidate_access_topology()
        return placed

    # ── Project admins ─────────────────────────────────────────────────

    async def add_project_admin(self, actor: Actor, project_id: int, user_id: str) -> dict:
        actor.require_super_admin()
        project = await self._project(project_id)
        user = await self._portal_user(user_id)
        roles = set((user.roles or "").split(","))
        if not roles & {UserRole.ADMIN.value, UserRole.SUPER_ADMIN.value}:
            raise _bad_request(
                "Project admins need the Ops Portal Admin role in Entra first (the user's last sign-in had none)."
            )
        existing = (
            await self._db.execute(
                select(ProjectAdmin).where(ProjectAdmin.project_id == project_id, ProjectAdmin.user_id == user_id)
            )
        ).scalar_one_or_none()
        if existing is None:
            self._db.add(
                ProjectAdmin(
                    project_id=project_id,
                    user_id=user_id,
                    user_email=user.email,
                    granted_by=actor.user.email,
                )
            )
            await self._db.commit()
            await self._audit(
                actor.user,
                "access_project_admin_add",
                f"Made {user.email} an admin of {project.name}",
                {"project_id": project_id, "user_id": user_id},
            )
        return {"project_id": project_id, "user_id": user_id}

    async def remove_project_admin(self, actor: Actor, project_id: int, user_id: str) -> dict:
        actor.require_super_admin()
        row = (
            await self._db.execute(
                select(ProjectAdmin).where(ProjectAdmin.project_id == project_id, ProjectAdmin.user_id == user_id)
            )
        ).scalar_one_or_none()
        if row is None:
            raise _not_found("Project admin")
        email = row.user_email
        await self._db.delete(row)
        await self._db.commit()
        await self._audit(
            actor.user,
            "access_project_admin_remove",
            f"Removed {email} as a project admin",
            {"project_id": project_id, "user_id": user_id},
        )
        return {"removed": True}

    # ── Grants ─────────────────────────────────────────────────────────

    async def _grant_dict(self, grants: list[AccessGrant]) -> list[dict]:
        if not grants:
            return []
        projects = {p.id: p.name for p in (await self._db.execute(select(Project))).scalars().all()}
        apps = {a.id: a.name for a in (await self._db.execute(select(ProjectApp))).scalars().all()}
        sub_ids = [g.subscription_id for g in grants if g.subscription_id]
        sub_names: dict[str, str] = {}
        if sub_ids:
            sub_names = {
                s.lower(): n
                for s, n in (
                    await self._db.execute(
                        select(AdminSubscription.subscription_id, AdminSubscription.subscription_name).where(
                            AdminSubscription.subscription_id.in_(sub_ids)
                        )
                    )
                ).all()
            }
        topology = await load_topology(self._db)
        return [
            {
                "id": g.id,
                "subject_type": g.subject_type,
                "subject_id": g.subject_id,
                "subject_email": g.subject_email,
                "scope_type": g.scope_type,
                "project_id": g.project_id,
                "project_name": projects.get(g.project_id),
                "app_id": g.app_id,
                "app_name": apps.get(g.app_id) if g.app_id else None,
                "subscription_id": g.subscription_id,
                "subscription_name": sub_names.get((g.subscription_id or "").lower()),
                "tier": g.tier,
                "level": g.level,
                "subscription_count": len(subscriptions_for_grant(topology, g)),
                "request_item_id": g.request_item_id,
                "granted_by": g.granted_by_email or g.granted_by,
                "created_at": _iso(g.created_at),
            }
            for g in grants
        ]

    async def list_grants(
        self, actor: Actor, *, project_id: int | None = None, user_id: str | None = None
    ) -> list[dict]:
        stmt = select(AccessGrant).order_by(AccessGrant.subject_email, AccessGrant.id)
        if project_id is not None:
            actor.require_project_admin(project_id)
            stmt = stmt.where(AccessGrant.project_id == project_id)
        elif not actor.is_super_admin:
            if not actor.scope.admin_project_ids:
                raise _forbidden()
            stmt = stmt.where(AccessGrant.project_id.in_(sorted(actor.scope.admin_project_ids)))
        if user_id is not None:
            stmt = stmt.where(AccessGrant.subject_type == "user", AccessGrant.subject_id == user_id)
        grants = (await self._db.execute(stmt)).scalars().all()
        return await self._grant_dict(list(grants))

    async def _resolve_scope_target(
        self,
        *,
        scope_type: str,
        project_id: int | None,
        app_id: int | None,
        subscription_id: str | None,
        tier: str | None,
    ) -> tuple[int, int | None, str | None, str | None]:
        """Validate a grant/request target.  Returns (project_id, app_id, subscription_id, tier)."""
        if scope_type == "project":
            if project_id is None:
                raise _bad_request("project_id is required.")
            await self._project(project_id)
            if tier not in TIERS:
                raise _bad_request("Tier must be 'prod' or 'nonprod'.")
            return project_id, None, None, tier
        if scope_type == "app":
            if app_id is None:
                raise _bad_request("app_id is required.")
            app = await self._app(app_id)
            if tier not in TIERS:
                raise _bad_request("Tier must be 'prod' or 'nonprod'.")
            return app.project_id, app_id, None, tier
        if scope_type == "subscription":
            if not subscription_id:
                raise _bad_request("subscription_id is required.")
            row = (
                await self._db.execute(
                    select(AdminSubscription).where(
                        func.lower(AdminSubscription.subscription_id) == subscription_id.lower()
                    )
                )
            ).scalar_one_or_none()
            if row is None or row.app_id is None:
                raise _bad_request("Only subscriptions placed in an app can be granted.")
            app = await self._app(row.app_id)
            return app.project_id, None, row.subscription_id, None
        raise _bad_request("scope_type must be 'project', 'app' or 'subscription'.")

    async def _upsert_grant(
        self,
        *,
        subject_type: str,
        subject_id: str,
        subject_email: str | None,
        scope_type: str,
        project_id: int,
        app_id: int | None,
        subscription_id: str | None,
        tier: str | None,
        level: str,
        granted_by: UserContext,
        request_item_id: int | None = None,
    ) -> tuple[AccessGrant, bool]:
        """Create the grant, or raise an existing identical one to ``level``.

        Never lowers an existing grant: approving a read request must not
        downgrade write access granted earlier.  Returns (grant, created).
        """
        stmt = select(AccessGrant).where(
            AccessGrant.subject_type == subject_type,
            AccessGrant.subject_id == subject_id,
            AccessGrant.scope_type == scope_type,
            AccessGrant.project_id == project_id,
        )
        stmt = (
            stmt.where(AccessGrant.app_id == app_id) if app_id is not None else stmt.where(AccessGrant.app_id.is_(None))
        )
        stmt = (
            stmt.where(func.lower(AccessGrant.subscription_id) == subscription_id.lower())
            if subscription_id
            else stmt.where(AccessGrant.subscription_id.is_(None))
        )
        stmt = stmt.where(AccessGrant.tier == tier) if tier else stmt.where(AccessGrant.tier.is_(None))
        existing = (await self._db.execute(stmt)).scalars().first()
        if existing is not None:
            if level == "write" and existing.level != "write":
                existing.level = "write"
                existing.granted_by = granted_by.user_id
                existing.granted_by_email = granted_by.email
                if request_item_id is not None:
                    existing.request_item_id = request_item_id
            return existing, False
        grant = AccessGrant(
            subject_type=subject_type,
            subject_id=subject_id,
            subject_email=subject_email,
            scope_type=scope_type,
            project_id=project_id,
            app_id=app_id,
            subscription_id=subscription_id,
            tier=tier,
            level=level,
            request_item_id=request_item_id,
            granted_by=granted_by.user_id,
            granted_by_email=granted_by.email,
        )
        self._db.add(grant)
        await self._db.flush()
        return grant, True

    async def create_grants(
        self,
        actor: Actor,
        *,
        user_ids: list[str],
        everyone: bool,
        scope_type: str,
        project_id: int | None,
        app_id: int | None,
        subscription_id: str | None,
        tiers: list[str],
        level: str,
    ) -> list[dict]:
        """Grant one or more users (or everyone) a scope, for each tier given."""
        if level not in LEVELS:
            raise _bad_request("Level must be 'read' or 'write'.")
        if everyone:
            actor.require_super_admin()
        elif not user_ids:
            raise _bad_request("Choose at least one user.")
        tier_list: list[str | None] = [None] if scope_type == "subscription" else list(dict.fromkeys(tiers))
        if not tier_list:
            raise _bad_request("Choose Prod, Non-Prod, or both.")

        subjects: list[tuple[str, str, str | None]] = []
        if everyone:
            subjects.append(("everyone", EVERYONE_SUBJECT, None))
        for uid in dict.fromkeys(user_ids):
            pu = await self._portal_user(uid)
            subjects.append(("user", pu.user_id, pu.email))

        created: list[AccessGrant] = []
        for tier in tier_list:
            pid, aid, sid, t = await self._resolve_scope_target(
                scope_type=scope_type,
                project_id=project_id,
                app_id=app_id,
                subscription_id=subscription_id,
                tier=tier,
            )
            actor.require_project_admin(pid)
            for subject_type, subject_id, email in subjects:
                grant, _ = await self._upsert_grant(
                    subject_type=subject_type,
                    subject_id=subject_id,
                    subject_email=email,
                    scope_type=scope_type,
                    project_id=pid,
                    app_id=aid,
                    subscription_id=sid,
                    tier=t,
                    level=level,
                    granted_by=actor.user,
                )
                created.append(grant)
        await self._db.commit()
        await self._audit(
            actor.user,
            "access_grant_create",
            f"Granted {level} on {scope_type} to {len(subjects)} subject(s)",
            {
                "grant_ids": [g.id for g in created],
                "subjects": [s[1] for s in subjects],
                "scope_type": scope_type,
                "project_id": project_id,
                "app_id": app_id,
                "subscription_id": subscription_id,
                "tiers": tier_list,
                "level": level,
            },
        )
        return await self._grant_dict(created)

    async def _grant(self, grant_id: int) -> AccessGrant:
        row = await self._db.get(AccessGrant, grant_id)
        if row is None:
            raise _not_found("Grant")
        return row

    async def update_grant(self, actor: Actor, grant_id: int, *, level: str) -> dict:
        if level not in LEVELS:
            raise _bad_request("Level must be 'read' or 'write'.")
        grant = await self._grant(grant_id)
        actor.require_project_admin(grant.project_id)
        if grant.subject_type == "everyone":
            actor.require_super_admin()
        before = grant.level
        grant.level = level
        grant.granted_by = actor.user.user_id
        grant.granted_by_email = actor.user.email
        await self._db.commit()
        await self._audit(
            actor.user,
            "access_grant_update",
            f"Changed grant {grant_id} from {before} to {level}",
            {"grant_id": grant_id, "subject_id": grant.subject_id, "before": before, "after": level},
        )
        return (await self._grant_dict([grant]))[0]

    async def revoke_grant(self, actor: Actor, grant_id: int) -> dict:
        grant = await self._grant(grant_id)
        actor.require_project_admin(grant.project_id)
        if grant.subject_type == "everyone":
            actor.require_super_admin()
        snapshot = (await self._grant_dict([grant]))[0]
        await self._db.delete(grant)
        await self._db.commit()
        await self._audit(
            actor.user,
            "access_grant_revoke",
            f"Revoked grant {grant_id} from {grant.subject_email or grant.subject_id}",
            {"grant": snapshot},
        )
        return {"revoked": True}

    # ── My access ──────────────────────────────────────────────────────

    async def my_access(self, user: UserContext, scope: AccessScope) -> dict:
        grants = (
            (
                await self._db.execute(
                    select(AccessGrant).where(
                        or_(
                            (AccessGrant.subject_type == "user") & (AccessGrant.subject_id == user.user_id),
                            AccessGrant.subject_type == "everyone",
                        )
                    )
                )
            )
            .scalars()
            .all()
        )
        admin_projects = []
        if scope.admin_project_ids:
            admin_projects = [
                {"id": p.id, "name": p.name}
                for p in (
                    await self._db.execute(select(Project).where(Project.id.in_(sorted(scope.admin_project_ids))))
                ).scalars()
            ]
        pending = (
            await self._db.execute(
                select(func.count())
                .select_from(AccessRequest)
                .where(AccessRequest.requester_id == user.user_id, AccessRequest.status == "pending")
            )
        ).scalar_one()
        return {
            "is_super_admin": user.is_super_admin,
            "role_ceiling": "write" if user.can_write else "read",
            "has_subscription_access": scope.has_any_access,
            "readable_count": None if scope.unrestricted else len(scope.readable),
            "writable_count": None if scope.unrestricted else len(scope.writable),
            "admin_projects": admin_projects,
            "grants": await self._grant_dict(list(grants)),
            "pending_requests": pending,
        }

    # ── Requests ───────────────────────────────────────────────────────

    async def _request_dict(self, req: AccessRequest, actor: Actor | None = None) -> dict:
        projects = {p.id: p.name for p in (await self._db.execute(select(Project))).scalars().all()}
        apps = {a.id: a.name for a in (await self._db.execute(select(ProjectApp))).scalars().all()}
        return {
            "id": req.id,
            "requester_id": req.requester_id,
            "requester_email": req.requester_email,
            "requester_name": req.requester_name,
            "justification": req.justification,
            "status": req.status,
            "created_at": _iso(req.created_at),
            "updated_at": _iso(req.updated_at),
            "items": [
                {
                    "id": i.id,
                    "scope_type": i.scope_type,
                    "project_id": i.project_id,
                    "project_name": projects.get(i.project_id),
                    "app_id": i.app_id,
                    "app_name": apps.get(i.app_id) if i.app_id else None,
                    "tier": i.tier,
                    "requested_level": i.requested_level,
                    "status": i.status,
                    "granted_level": i.granted_level,
                    "decided_by": i.decided_by_email or i.decided_by,
                    "decided_at": _iso(i.decided_at),
                    "decision_comment": i.decision_comment,
                    "can_decide": (
                        actor is not None
                        and i.status == "pending"
                        and actor.administers(i.project_id)
                        and actor.user.user_id != req.requester_id
                    ),
                }
                for i in req.items
            ],
        }

    async def _load_request(self, request_id: int) -> AccessRequest:
        req = (
            await self._db.execute(
                select(AccessRequest).options(selectinload(AccessRequest.items)).where(AccessRequest.id == request_id)
            )
        ).scalar_one_or_none()
        if req is None:
            raise _not_found("Request")
        return req

    async def submit_request(self, user: UserContext, *, justification: str, items: list[dict]) -> dict:
        justification = (justification or "").strip()
        if len(justification) < 10:
            raise _bad_request("Please explain why you need this access (at least 10 characters).")
        if not items:
            raise _bad_request("Choose at least one project or app.")
        if len(items) > 50:
            raise _bad_request("Too many items in one request.")
        ceiling = "write" if user.can_write else "read"

        pending_keys = {
            (i.scope_type, i.project_id, i.app_id, i.tier)
            for i in (
                await self._db.execute(
                    select(AccessRequestItem)
                    .join(AccessRequest, AccessRequestItem.request_id == AccessRequest.id)
                    .where(AccessRequest.requester_id == user.user_id, AccessRequestItem.status == "pending")
                )
            )
            .scalars()
            .all()
        }

        new_items: list[AccessRequestItem] = []
        seen: set[tuple] = set()
        for raw in items:
            scope_type = raw.get("scope_type")
            if scope_type not in ("project", "app"):
                raise _bad_request("Request a project or an app.")
            level = raw.get("level", "read")
            if level not in LEVELS:
                raise _bad_request("Level must be 'read' or 'write'.")
            if level == "write" and ceiling == "read":
                raise _bad_request(
                    "Your Ops Portal role is read-only, so you can only request read access. "
                    "Write access needs membership of the Ops Portal Write group in Entra first."
                )
            pid, aid, _sid, tier = await self._resolve_scope_target(
                scope_type=scope_type,
                project_id=raw.get("project_id"),
                app_id=raw.get("app_id"),
                subscription_id=None,
                tier=raw.get("tier"),
            )
            key = (scope_type, pid, aid, tier)
            if key in seen:
                continue
            if key in pending_keys:
                raise _bad_request("You already have a pending request for one of these items.")
            seen.add(key)
            new_items.append(
                AccessRequestItem(
                    scope_type=scope_type,
                    project_id=pid,
                    app_id=aid,
                    tier=tier,
                    requested_level=level,
                    status="pending",
                )
            )

        req = AccessRequest(
            requester_id=user.user_id,
            requester_email=user.email,
            requester_name=user.display_name,
            justification=justification,
            status="pending",
            items=new_items,
        )
        self._db.add(req)
        await self._db.commit()
        await self._audit(
            user,
            "access_request_submit",
            f"Requested access ({len(new_items)} item(s))",
            {"request_id": req.id},
        )
        return await self._request_dict(await self._load_request(req.id))

    async def my_requests(self, user: UserContext) -> list[dict]:
        reqs = (
            (
                await self._db.execute(
                    select(AccessRequest)
                    .options(selectinload(AccessRequest.items))
                    .where(AccessRequest.requester_id == user.user_id)
                    .order_by(AccessRequest.created_at.desc())
                    .limit(100)
                )
            )
            .scalars()
            .all()
        )
        return [await self._request_dict(r) for r in reqs]

    async def cancel_request(self, user: UserContext, request_id: int) -> dict:
        req = await self._load_request(request_id)
        if req.requester_id != user.user_id:
            raise _not_found("Request")
        if req.status != "pending" or any(i.status != "pending" for i in req.items):
            raise _bad_request("Only a request nobody has acted on yet can be cancelled.")
        req.status = "cancelled"
        for item in req.items:
            item.status = "cancelled"
        await self._db.commit()
        await self._audit(user, "access_request_cancel", f"Cancelled request {request_id}", {"request_id": request_id})
        return await self._request_dict(req)

    async def list_requests_for_approver(self, actor: Actor, *, status_filter: str | None = "pending") -> list[dict]:
        if not actor.is_super_admin and not actor.scope.admin_project_ids:
            raise _forbidden()
        stmt = (
            select(AccessRequest).options(selectinload(AccessRequest.items)).order_by(AccessRequest.created_at.desc())
        )
        if status_filter:
            stmt = stmt.where(AccessRequest.status == status_filter)
        if not actor.is_super_admin:
            stmt = stmt.where(
                AccessRequest.id.in_(
                    select(AccessRequestItem.request_id).where(
                        AccessRequestItem.project_id.in_(sorted(actor.scope.admin_project_ids))
                    )
                )
            )
        reqs = (await self._db.execute(stmt.limit(200))).scalars().all()
        return [await self._request_dict(r, actor) for r in reqs]

    async def decide_item(
        self,
        actor: Actor,
        request_id: int,
        item_id: int,
        *,
        approve: bool,
        level: str | None,
        comment: str | None,
    ) -> dict:
        req = await self._load_request(request_id)
        item = next((i for i in req.items if i.id == item_id), None)
        if item is None:
            raise _not_found("Request item")
        actor.require_project_admin(item.project_id)
        if actor.user.user_id == req.requester_id:
            raise _forbidden("You cannot approve or reject your own request.")
        if item.status != "pending":
            raise _bad_request("This item has already been decided.")

        now = datetime.utcnow()
        item.decided_by = actor.user.user_id
        item.decided_by_email = actor.user.email
        item.decided_at = now
        item.decision_comment = (comment or "").strip() or None

        if approve:
            granted = level or item.requested_level
            if granted not in LEVELS:
                raise _bad_request("Level must be 'read' or 'write'.")
            if granted == "write" and item.requested_level == "read":
                raise _bad_request("You can approve at the requested level or lower, not higher.")
            requester = await self._db.get(PortalUser, req.requester_id)
            grant, _ = await self._upsert_grant(
                subject_type="user",
                subject_id=req.requester_id,
                subject_email=(requester.email if requester else None) or req.requester_email,
                scope_type=item.scope_type,
                project_id=item.project_id,
                app_id=item.app_id,
                subscription_id=None,
                tier=item.tier,
                level=granted,
                granted_by=actor.user,
                request_item_id=item.id,
            )
            item.status = "approved"
            item.granted_level = granted
            item.grant_id = grant.id
        else:
            item.status = "rejected"

        statuses = {i.status for i in req.items}
        if "pending" not in statuses:
            if statuses == {"approved"}:
                req.status = "approved"
            elif "approved" in statuses:
                req.status = "partially_approved"
            else:
                req.status = "rejected"
        await self._db.commit()
        await self._audit(
            actor.user,
            "access_request_approve" if approve else "access_request_reject",
            f"{'Approved' if approve else 'Rejected'} item {item_id} of request {request_id} for {req.requester_email}",
            {
                "request_id": request_id,
                "item_id": item_id,
                "requester_id": req.requester_id,
                "granted_level": item.granted_level,
                "grant_id": item.grant_id,
                "comment": item.decision_comment,
            },
        )
        return await self._request_dict(req, actor)

    async def approver_emails(self, project_ids: set[int]) -> list[str]:
        """Emails of Super Admins and of the admins of ``project_ids``."""
        emails: set[str] = set()
        for roles, email in (await self._db.execute(select(PortalUser.roles, PortalUser.email))).all():
            if email and UserRole.SUPER_ADMIN.value in (roles or "").split(","):
                emails.add(email)
        if project_ids:
            for (email,) in (
                await self._db.execute(
                    select(ProjectAdmin.user_email).where(ProjectAdmin.project_id.in_(sorted(project_ids)))
                )
            ).all():
                if email:
                    emails.add(email)
        return sorted(emails)

    # ── Go-live bootstrap ──────────────────────────────────────────────

    async def bootstrap(self) -> dict | None:
        """One-time move to the project model.  Safe to call on every start.

        Runs only when no project exists and the marker is absent:

        1. creates the Commissions project (every *monitored* subscription
           today belongs to a Commissions app);
        2. creates an app per AppID found in monitored subscription names
           (``ACC-PROD-31599-ATTCC`` → app 31599 "ATTCC") and places each
           with its tier; names without an AppID go to an "Unclassified" app
           for a Super Admin to sort out;
        3. grants **everyone** write on Commissions Prod and Non-Prod, capped
           by each user's Entra role — exactly today's access, so nobody is
           locked out.  A Super Admin narrows access and then removes this
           transition grant.

        Only enabled + monitored subscriptions are placed.  Discovery adds
        every subscription the portal's identity can see — other projects'
        included — and placing those in Commissions would hand them to
        everyone through the transition grant.  They stay unplaced (Super
        Admin only) until someone puts them in the right project.

        With no monitored subscription row yet (fresh database) nothing is
        done and the marker is not set, so a later start does the move once
        there is something to place.
        """
        marker = (
            await self._db.execute(select(AdminConfig).where(AdminConfig.config_key == BOOTSTRAP_MARKER_KEY))
        ).scalar_one_or_none()
        if marker is not None:
            return None
        if (await self._db.execute(select(Project.id).limit(1))).first():
            self._db.add(
                AdminConfig(
                    config_key=BOOTSTRAP_MARKER_KEY,
                    config_value=datetime.utcnow().isoformat(),
                    config_type="string",
                    description="Projects already existed; bootstrap skipped",
                    updated_by="system",
                )
            )
            await self._db.commit()
            return None

        subs = (
            (
                await self._db.execute(
                    select(AdminSubscription).where(
                        AdminSubscription.enabled.is_(True),
                        AdminSubscription.monitored.is_(True),
                    )
                )
            )
            .scalars()
            .all()
        )
        if not subs:
            logger.info("access_bootstrap_deferred", reason="no_monitored_subscriptions")
            return None

        project = Project(
            project_key=DEFAULT_PROJECT_KEY,
            name=DEFAULT_PROJECT_NAME,
            description="Commissions apps (created when project access was introduced)",
            created_by="system",
            updated_by="system",
        )
        self._db.add(project)
        await self._db.flush()

        apps: dict[str, ProjectApp] = {}
        placed: dict[str, list[str]] = {}
        for sub in subs:
            c = classify_subscription(sub.subscription_name, sub.environment)
            code = (c.app_code or UNCLASSIFIED_APP_CODE).upper()
            if code not in apps:
                apps[code] = ProjectApp(
                    project_id=project.id,
                    app_code=code,
                    name=c.app_name or ("Unclassified" if code == UNCLASSIFIED_APP_CODE else code),
                    description=(
                        "Subscriptions whose names carry no AppID — move them to the right app"
                        if code == UNCLASSIFIED_APP_CODE
                        else None
                    ),
                    created_by="system",
                    updated_by="system",
                )
                self._db.add(apps[code])
                await self._db.flush()
            sub.app_id = apps[code].id
            sub.tier = c.tier
            placed.setdefault(code, []).append(sub.subscription_id)

        everyone_grants = []
        for tier in TIERS:
            grant = AccessGrant(
                subject_type="everyone",
                subject_id=EVERYONE_SUBJECT,
                subject_email=None,
                scope_type="project",
                project_id=project.id,
                tier=tier,
                level="write",
                granted_by="system",
                granted_by_email=None,
            )
            self._db.add(grant)
            everyone_grants.append(grant)

        self._db.add(
            AdminConfig(
                config_key=BOOTSTRAP_MARKER_KEY,
                config_value=datetime.utcnow().isoformat(),
                config_type="string",
                description="Project access model bootstrapped (Commissions + transition grant)",
                updated_by="system",
            )
        )
        await self._db.commit()
        invalidate_access_topology()

        summary = {
            "project_id": project.id,
            "apps": {code: len(ids) for code, ids in placed.items()},
            "everyone_grant_ids": [g.id for g in everyone_grants],
        }
        await self._audit(None, "access_bootstrap", "Created Commissions project and transition grant", summary)
        logger.info("access_model_bootstrapped", **summary)
        return summary


async def actor_for(db: AsyncSession, user: UserContext, scope: AccessScope | None = None) -> Actor:
    return Actor(user=user, scope=scope or await compute_access_scope(db, user))
