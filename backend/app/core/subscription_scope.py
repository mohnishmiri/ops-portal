"""
Per-request subscription scope via context variables.

Router dependency ``bind_subscription_scope`` resolves scope from the
``subscription_ids`` query param, else the user's saved preference, then
intersects with admin-monitored subscriptions and the subscriptions the user
has been granted (``app.core.access_scope``).

Background sync jobs (no HTTP request) fall back to monitored-only scope.
"""

from __future__ import annotations

from contextvars import ContextVar, Token

import structlog
from fastapi import Depends, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.core.access_scope import UNRESTRICTED, bind_access_scope, resolve_access_scope
from app.core.authz import _module_for_path
from app.core.database import get_db
from app.core.subscription_resolver import get_monitored_subscription_ids
from app.models.auth import UserContext, UserRole

logger = structlog.get_logger(__name__)

_scoped_subscription_ids: ContextVar[list[str] | None] = ContextVar(
    "scoped_subscription_ids",
    default=None,
)


def set_scoped_subscription_ids(ids: list[str] | None) -> Token:
    return _scoped_subscription_ids.set(ids)


def reset_scoped_subscription_ids(token: Token) -> None:
    _scoped_subscription_ids.reset(token)


def get_active_scoped_subscription_ids() -> list[str] | None:
    return _scoped_subscription_ids.get()


async def resolve_effective_subscription_ids(
    *,
    allowed_subscriptions: list[str] | frozenset[str] | None = None,
    selected_subscription_ids: list[str] | None = None,
    strict_selection: bool = True,
) -> list[str]:
    """Intersect monitored, user-allowed, and user-selected subscription IDs.

    ``allowed_subscriptions`` is ``None`` for an unrestricted user; an empty
    collection means the user may see no subscription at all.

    With ``strict_selection`` (an explicit ``subscription_ids`` parameter) a
    selection outside the monitored or allowed set is an error.  Without it
    (a saved preference) out-of-scope entries are dropped silently, and an
    empty result falls back to everything allowed — so revoking access never
    leaves a user stuck behind a stale picker preference.
    """
    monitored = await get_monitored_subscription_ids()
    if not monitored:
        return []

    base = list(monitored)
    if allowed_subscriptions is not None:
        allowed_set = {sub_id.lower() for sub_id in allowed_subscriptions}
        base = [sub_id for sub_id in base if sub_id.lower() in allowed_set]

    if selected_subscription_ids:
        selected_set = {sub_id.lower() for sub_id in selected_subscription_ids}
        if strict_selection:
            invalid = selected_set - {sub_id.lower() for sub_id in monitored}
            if invalid:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=(f"One or more subscription IDs are not in the monitored set: {', '.join(sorted(invalid))}"),
                )
            if selected_set - {sub_id.lower() for sub_id in base}:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Subscription access denied for the requested scope.",
                )
        narrowed = [sub_id for sub_id in base if sub_id.lower() in selected_set]
        if narrowed or strict_selection:
            base = narrowed

    return base


async def get_scoped_subscription_ids() -> list[str]:
    """Effective subscription IDs for the current request or monitored-only fallback."""
    active = get_active_scoped_subscription_ids()
    if active is not None:
        return list(active)
    return await get_monitored_subscription_ids()


async def scope_is_full() -> bool:
    """True when the current scope covers every monitored subscription.

    Pre-computed portal-wide snapshots (compliance dashboard, ...) may only be
    served then; anyone with a narrower scope needs a scoped computation.
    """
    scoped = {s.lower() for s in await get_scoped_subscription_ids()}
    monitored = {s.lower() for s in await get_monitored_subscription_ids()}
    return scoped == monitored


async def bind_subscription_scope(
    request: Request,
    user: UserContext | None = Depends(get_current_user),
    subscription_ids: list[str] | None = Query(
        default=None,
        description="Optional subscription scope filter (repeat param for multiple)",
    ),
    db: AsyncSession | None = Depends(get_db),
) -> list[str]:
    """FastAPI dependency: authenticate, resolve scope, store on context for services."""
    dashboard_session = user is None
    if user is None:
        path = request.url.path
        if path.startswith("/api/v1/aks/dashboard/") and ("/launch/" in path or "/proxy" in path):
            user = UserContext(
                user_id="k8s-dashboard-browser-session",
                object_id="00000000-0000-0000-0000-000000000000",
                display_name="K8s Dashboard Browser Session",
                email="k8s-dashboard@localhost",
                roles=[UserRole.READ],
                raw_roles=["dashboard-session"],
                tenant_id="dashboard-session",
                allowed_subscriptions=[],
            )
        else:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Not authenticated",
            )

    # A signed K8s Dashboard session was checked against its cluster's
    # subscription when it was launched, and it can reach only that cluster;
    # its synthetic user holds no grants of its own.
    access = UNRESTRICTED if dashboard_session else await resolve_access_scope(request, user, db)
    access_token = bind_access_scope(access)
    request.state._access_scope_token = access_token

    # The ``subscription_ids`` parameter is a view filter the UI adds from its
    # picker.  It is narrowed to what the user may see rather than rejected:
    # it can never widen access, and rejecting it would 403 every request —
    # including the one that refreshes the picker — for a user whose access
    # was just revoked.
    selected = subscription_ids
    if selected is None and db is not None:
        try:
            from app.services.user_preference_service import UserPreferenceService

            prefs = await UserPreferenceService(db).get_selected_subscription_ids(user.user_id)
            if prefs:
                selected = prefs
        except Exception as exc:
            logger.warning(
                "subscription_scope_pref_load_failed",
                user_id=user.user_id,
                error=str(exc)[:200],
            )

    effective = await resolve_effective_subscription_ids(
        allowed_subscriptions=None if access.unrestricted else access.readable,
        selected_subscription_ids=selected,
        strict_selection=False,
    )

    # A user with no subscription in scope has nothing to see in any module.
    # Refusing here, before a service runs, matters: several services treat
    # an empty scope as "not configured yet" and fall back to every
    # subscription they can find.
    if not access.unrestricted and not effective and _module_for_path(request.url.path) is not None:
        logger.info("subscription_scope_empty_denied", user_id=user.user_id, path=request.url.path)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have access to any subscription yet. Request access from the Access page.",
        )

    token = set_scoped_subscription_ids(effective)
    request.state.scoped_subscription_ids = effective
    request.state._subscription_scope_token = token
    logger.debug(
        "subscription_scope_bound",
        user_id=user.user_id,
        selected_count=len(selected or []),
        effective_count=len(effective),
    )
    return effective


async def subscription_ids_for_manual_amortized_sync(request: Request) -> list[str] | None:
    """Subscription IDs for a user-triggered amortized sync when narrower than full monitored.

    Returns ``None`` when the job should sync all admin-monitored subscriptions
    (scheduler, startup, or user with no narrowed picker selection).
    """
    scoped = getattr(request.state, "scoped_subscription_ids", None)
    if not scoped:
        return None
    monitored = await get_monitored_subscription_ids()
    if not monitored:
        return None
    scoped_list = sorted(set(scoped))
    monitored_set = set(monitored)
    if set(scoped_list) == monitored_set:
        return None
    return [sub_id for sub_id in scoped_list if sub_id in monitored_set]
