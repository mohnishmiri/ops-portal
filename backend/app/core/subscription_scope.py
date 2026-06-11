"""
Per-request subscription scope via context variables.

Router dependency ``bind_subscription_scope`` resolves scope from the
``subscription_ids`` query param, else the user's saved preference, then
intersects with admin-monitored subscriptions and optional RBAC.

Background sync jobs (no HTTP request) fall back to monitored-only scope.
"""

from __future__ import annotations

from contextvars import ContextVar, Token

import structlog
from fastapi import Depends, HTTPException, Query, Request, status

from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.core.database import get_db
from app.core.subscription_resolver import get_monitored_subscription_ids
from app.models.auth import UserContext

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
    allowed_subscriptions: list[str] | None = None,
    selected_subscription_ids: list[str] | None = None,
) -> list[str]:
    """Intersect monitored, RBAC-allowed, and user-selected subscription IDs."""
    monitored = await get_monitored_subscription_ids()
    if not monitored:
        return []

    base = list(monitored)
    if allowed_subscriptions:
        allowed_set = set(allowed_subscriptions)
        base = [sub_id for sub_id in base if sub_id in allowed_set]

    if selected_subscription_ids:
        selected_set = set(selected_subscription_ids)
        invalid = selected_set - set(monitored)
        if invalid:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "One or more subscription IDs are not in the monitored set: "
                    f"{', '.join(sorted(invalid))}"
                ),
            )
        if allowed_subscriptions:
            rbac_invalid = selected_set - set(allowed_subscriptions)
            if rbac_invalid:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Subscription access denied for the requested scope.",
                )
        base = [sub_id for sub_id in base if sub_id in selected_set]

    return base


async def get_scoped_subscription_ids() -> list[str]:
    """Effective subscription IDs for the current request or monitored-only fallback."""
    active = get_active_scoped_subscription_ids()
    if active is not None:
        return list(active)
    return await get_monitored_subscription_ids()


async def bind_subscription_scope(
    request: Request,
    user: UserContext = Depends(get_current_user),
    subscription_ids: list[str] | None = Query(
        default=None,
        description="Optional subscription scope filter (repeat param for multiple)",
    ),
    db: AsyncSession | None = Depends(get_db),
) -> list[str]:
    """FastAPI dependency: authenticate, resolve scope, store on context for services."""
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
        allowed_subscriptions=user.allowed_subscriptions or None,
        selected_subscription_ids=selected,
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
