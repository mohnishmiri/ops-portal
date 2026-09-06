"""
Central portal authorization.

Authentication ("is this a valid identity?") lives in ``app.auth``.  This
module owns *authorization* ("is this identity allowed in, and allowed to do
this particular thing?").  The two are deliberately separate controls: a valid
corporate identity does not imply Ops Portal access.

Two layers, both enforced server-side:

1. :func:`enforce_portal_access` — router-level dependency applied to every
   ``/api/v1/*`` route.  Rejects an authenticated identity that holds no
   recognised portal app role.  This is the gate that stops an authenticated
   but unentitled user from reaching any protected API.

2. :func:`require_capability` — route-level dependency factory for individual
   operations (delete a pod, trigger a CronJob, ...).  Capabilities are
   ordinary ``Resource`` rows of type ``operation``, so the existing admin
   Permissions UI and matrix manage them with no new tables and no parallel
   RBAC system.

Design notes
------------
* Admins bypass capability checks (consistent with the rest of the portal).
* A capability whose ``Resource`` row is missing — fresh DB, failed seed —
  falls back to the coarse role requirement rather than opening up.  The
  effective permission is therefore never weaker than the role-only checks
  that preceded the capability layer.
* Denials are logged with the subject and capability but never with token
  material, and the client-facing detail is intentionally generic.
"""

from __future__ import annotations

import structlog
from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.core.database import get_db
from app.models.auth import UserContext, UserRole
from app.models.database import Permission, Resource

logger = structlog.get_logger(__name__)

# Client-facing text for an authorization failure.  Deliberately generic —
# the specific capability that was missing goes to the application log only.
_FORBIDDEN_DETAIL = "You do not have permission to perform this operation."


def _forbidden() -> HTTPException:
    return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=_FORBIDDEN_DETAIL)


def _accepted_permission_types(required: str) -> tuple[str, ...]:
    """Permission types that satisfy a requirement for ``required``.

    ``edit`` implies ``view``: the admin UI's "View + Edit" option writes a
    single ``edit`` row, so treating an edit grant as insufficient for a view
    requirement would deny access the operator clearly intended to give.
    The reverse does not hold — a view grant never permits an edit.
    """
    return ("view", "edit") if required == "view" else ("edit",)


async def enforce_portal_access(
    request: Request,
    user: UserContext | None = Depends(get_current_user),
) -> UserContext | None:
    """Router-level dependency: the Ops Portal access gate.

    ``get_current_user`` already rejects an identity with no recognised app
    role.  Declaring the gate here as well makes the control explicit and
    central rather than an incidental side effect of the auth dependency, so
    it cannot be lost if that dependency is refactored.

    Returns ``None`` for the signed K8s dashboard launch/proxy routes, which
    authenticate themselves via an HMAC-signed token or session cookie.
    """
    if user is None:
        return None

    if not user.roles:
        logger.warning(
            "portal_access_denied",
            user_id=user.user_id,
            path=request.url.path,
            reason="no_portal_role",
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are not authorized to access the Ops Portal.",
        )

    return user


# API path prefix → module resource that guards it.  Longest prefix wins.
#
# This closes the gap where the frontend's ProtectedRoute blocked a module's
# *page* while its APIs stayed reachable via curl.  Only module **view** access
# is required here — "may this identity use this module at all".  Authorization
# for state changes remains with require_role/require_capability on the
# individual routes, so a read-only user keeps the same abilities as before.
#
# Prefixes intentionally absent (and therefore not gated here): /auth,
# /admin and /permissions (role-gated), /notifications, /sync-jobs and
# /checksum-schedules (cross-module infrastructure).
_API_MODULE_PREFIXES: tuple[tuple[str, str], ...] = (
    ("/api/v1/aks", "aks_operations"),
    ("/api/v1/environment", "aks_operations"),
    ("/api/v1/keyvault", "keyvault"),
    ("/api/v1/certificates", "certificates"),
    ("/api/v1/compliance", "compliance"),
    ("/api/v1/infra-alerts", "infra_alerts"),
    ("/api/v1/costs", "cost_management"),
    ("/api/v1/dashboards", "cost_management"),
    ("/api/v1/optimize", "cost_management"),
    ("/api/v1/reports", "cost_management"),
)


def _module_for_path(path: str) -> str | None:
    """Module resource guarding ``path``, or None when the path is not gated."""
    best: str | None = None
    best_len = -1
    for prefix, module in _API_MODULE_PREFIXES:
        if (path == prefix or path.startswith(prefix + "/")) and len(prefix) > best_len:
            best, best_len = module, len(prefix)
    return best


async def enforce_module_access(
    request: Request,
    user: UserContext | None = Depends(enforce_portal_access),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Router-level dependency: module-scoped API authorization.

    Replaces the never-registered ``AccessControlMiddleware``, which could not
    have worked as written — Starlette middleware runs before route
    dependencies, so the ``request.state.user`` it read was always None, and it
    compared API paths against frontend ``route_path`` values that never match.

    Grants of either ``view`` or ``edit`` satisfy the gate: the admin UI can
    record an edit-only grant, and treating that as "no access to the module"
    would 403 every API in a module the operator had deliberately opened up.
    """
    if user is None or user.is_admin:
        return

    module = _module_for_path(request.url.path)
    if module is None:
        return

    # Single joined query: resolving the resource and the grant separately cost
    # an extra round trip on every request to a gated module.
    if await _has_permission_by_resource_name(
        db,
        request=request,
        user=user,
        resource_name=module,
        permission_types=("view", "edit"),
        missing_resource_result=True,
    ):
        return

    logger.warning(
        "module_access_denied",
        module=module,
        path=request.url.path,
        user_id=user.user_id,
        user_roles=[r.value for r in user.roles],
    )
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="You do not have access to this module.",
    )


async def _team_names_for_user(
    db: AsyncSession,
    user_id: str,
    *,
    request: Request | None = None,
) -> list[str]:
    """Team names the user belongs to, used to resolve group-subject grants.

    Memoized on ``request.state`` because several authorization checks can run
    for one request (module gate plus a capability check) and the membership
    cannot change mid-request.
    """
    if request is not None:
        cached = getattr(request.state, "_authz_team_names", None)
        if cached is not None:
            return cached

    from app.models.database import Team, TeamMembership

    membership = await db.execute(select(TeamMembership.team_id).where(TeamMembership.user_id == user_id))
    team_ids = [row.team_id for row in membership]
    names: list[str] = []
    if team_ids:
        result = await db.execute(select(Team.team_name).where(Team.id.in_(team_ids)))
        names = [row.team_name for row in result]

    if request is not None:
        request.state._authz_team_names = names
    return names


async def _subject_clause(
    db: AsyncSession,
    *,
    user: UserContext,
    request: Request | None = None,
):
    """OR-clause matching every permission subject this user acts as.

    Subjects considered: the user themselves, each role they hold, and each
    team they belong to — matching the union used by ``/auth/my-permissions``.
    """
    subjects = [
        (Permission.subject_type == "user") & (Permission.subject_id == user.user_id),
        (Permission.subject_type == "role") & Permission.subject_id.in_([r.value for r in user.roles]),
    ]
    team_names = await _team_names_for_user(db, user.user_id, request=request)
    if team_names:
        subjects.append((Permission.subject_type == "group") & Permission.subject_id.in_(team_names))
    return or_(*subjects)


async def _has_permission_by_resource_name(
    db: AsyncSession,
    *,
    user: UserContext,
    resource_name: str,
    permission_types: tuple[str, ...],
    request: Request | None = None,
    missing_resource_result: bool = False,
) -> bool:
    """True when the user holds any of ``permission_types`` on ``resource_name``.

    ``missing_resource_result`` is returned when the resource is not registered
    at all: the module gate treats that as "nothing to enforce" (True), while
    capability checks handle absence separately via a role fallback.
    """
    resource_exists = (
        await db.execute(select(Resource.id).where(Resource.resource_name == resource_name).limit(1))
    ).scalar_one_or_none()
    if resource_exists is None:
        return missing_resource_result

    clause = await _subject_clause(db, user=user, request=request)
    granted = (
        await db.execute(
            select(Permission.id)
            .join(Resource, Permission.resource_id == Resource.id)
            .where(Resource.resource_name == resource_name)
            .where(Permission.permission_type.in_(permission_types))
            .where(clause)
            .limit(1)
        )
    ).scalar_one_or_none()
    return granted is not None


async def assert_capability(
    db: AsyncSession,
    *,
    user: UserContext,
    capability: str,
    permission_type: str = "edit",
    fallback_role: UserRole = UserRole.WRITE,
    request: Request | None = None,
) -> None:
    """Raise 403 unless ``user`` holds ``capability``.

    Usable directly from a service or endpoint body when the capability name
    is only known at runtime; prefer :func:`require_capability` for the
    common case of a fixed capability on a route.
    """
    if user.is_admin:
        return

    resource_exists = (
        await db.execute(select(Resource.id).where(Resource.resource_name == capability).limit(1))
    ).scalar_one_or_none()

    if resource_exists is None:
        # Capability not registered yet (fresh DB or a seed failure).  Fall
        # back to the coarse role requirement so behaviour is never more
        # permissive than the role-only checks this layer replaced.
        logger.warning(
            "capability_not_registered",
            capability=capability,
            fallback_role=fallback_role.value,
            user_id=user.user_id,
        )
        if not user.has_role(fallback_role):
            raise _forbidden()
        return

    if await _has_permission_by_resource_name(
        db,
        request=request,
        user=user,
        resource_name=capability,
        permission_types=_accepted_permission_types(permission_type),
    ):
        return

    logger.warning(
        "capability_denied",
        capability=capability,
        permission_type=permission_type,
        user_id=user.user_id,
        user_roles=[r.value for r in user.roles],
    )
    raise _forbidden()


def require_capability(
    capability: str,
    *,
    permission_type: str = "edit",
    fallback_role: UserRole = UserRole.WRITE,
):  # noqa: ANN201 — FastAPI dependency factory
    """Dependency factory enforcing a single named capability.

    Usage::

        @router.delete(
            "/pods",
            dependencies=[Depends(require_capability("aks_pod_delete"))],
        )
        async def delete_pod(...): ...

    ``permission_type`` is ``"edit"`` for operations that change state and
    ``"view"`` for read capabilities.  ``fallback_role`` is the role required
    if the capability has not been seeded into the database yet.
    """

    async def _capability_checker(
        request: Request,
        user: UserContext = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
    ) -> UserContext:
        await assert_capability(
            db,
            request=request,
            user=user,
            capability=capability,
            permission_type=permission_type,
            fallback_role=fallback_role,
        )
        return user

    return _capability_checker


async def granted_capabilities(db: AsyncSession, user: UserContext) -> list[str]:
    """Every capability name the user effectively holds.

    Used by the session/permissions endpoints so the frontend can hide
    actions the user cannot perform.  Frontend hiding is UX only — the
    server-side checks above remain authoritative.
    """
    capability_rows = (
        await db.execute(select(Resource.id, Resource.resource_name).where(Resource.resource_type == "operation"))
    ).all()

    if user.is_admin:
        return sorted(row.resource_name for row in capability_rows)

    if not capability_rows:
        return []

    clause = await _subject_clause(db, user=user)
    id_to_name = {row.id: row.resource_name for row in capability_rows}

    granted = (
        await db.execute(
            select(Permission.resource_id, Permission.permission_type)
            .where(Permission.resource_id.in_(list(id_to_name)))
            .where(clause)
            .distinct()
        )
    ).all()

    # A capability is only "held" when the grant's permission_type matches what
    # require_capability will check for.  Reporting an edit capability that the
    # user only has 'view' on would show the user an action the API then 403s.
    from app.core.resource_registry import CAPABILITY_PERMISSION_TYPES

    held: set[str] = set()
    for row in granted:
        name = id_to_name.get(row.resource_id)
        if name is None:
            continue
        required = CAPABILITY_PERMISSION_TYPES.get(name)
        # Unknown capability (added directly in the DB): fall back to accepting
        # any grant rather than hiding it entirely.
        if required is None or row.permission_type in _accepted_permission_types(required):
            held.add(name)

    return sorted(held)
