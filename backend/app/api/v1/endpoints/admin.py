"""Admin API endpoints for subscription management and portal config.

Every change made here is also written to ``audit_logs`` (resource types
``admin_subscription`` / ``admin_config`` / ``admin_cache``) and listed back
by ``GET /admin/audit`` for the Admin page's activity grid.
"""

import re
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import require_role
from app.core.admin_config import (
    CORS_CONFIG_KEY,
    parse_cors_origins,
    serialize_cors_origins,
)
from app.core.database import get_db
from app.core.subscription_resolver import invalidate_subscription_cache
from app.middleware.rate_limit import set_rate_limit_override
from app.models.auth import UserContext, UserRole
from app.services.admin_service import AdminService

router = APIRouter()


# ── Request / Response schemas ────────────────────────────────────────


_GUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")

# 0 = keep page-cache keys until released; otherwise 1 minute to 7 days.
_MAX_CACHE_TTL_SECONDS = 7 * 24 * 60 * 60

# The settings the Admin page manages. Anything else is rejected so a typo
# (or a guessed key) can't write config rows nothing reads.
_CONFIG_KEYS = frozenset(
    {
        CORS_CONFIG_KEY,
        "rate_limit_rpm",
        "cache_enabled",
        "ollama_enabled",
        "cache_ttl_seconds",
        "portal_timezone",
    }
)


class AddSubscriptionRequest(BaseModel):
    subscription_id: str = Field(..., min_length=1, description="Azure subscription GUID")
    subscription_name: str | None = Field(default=None, description="Defaults to the subscription ID")
    state: str = Field(default="Unknown")
    enabled: bool = Field(default=True)
    monitored: bool = Field(default=True)
    environment: str | None = None
    notes: str | None = None

    @field_validator("subscription_id")
    @classmethod
    def _normalise_subscription_id(cls, value: str) -> str:
        # ARM returns lower-case GUIDs and lookups are exact, so an upper-case
        # entry would sit beside the discovered row as a duplicate.
        value = value.strip().lower()
        if not _GUID_RE.match(value):
            raise ValueError("must be a subscription GUID (xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx)")
        return value


class ToggleSubscriptionRequest(BaseModel):
    enabled: bool | None = None
    monitored: bool | None = None


class UpdateSubscriptionRequest(BaseModel):
    """``None`` leaves a field unchanged; an empty string clears Environment or Notes."""

    subscription_name: str | None = Field(default=None, max_length=255)
    environment: str | None = Field(default=None, max_length=50)
    notes: str | None = None

    @field_validator("subscription_name")
    @classmethod
    def _name_not_blank(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("cannot be blank")
        return value


class UpsertConfigRequest(BaseModel):
    config_key: str = Field(..., min_length=1)
    config_value: str
    config_type: str = Field(default="string")
    description: str | None = None


# ── Dependency ─────────────────────────────────────────────────────────


def _get_admin_service(db: AsyncSession = Depends(get_db)) -> AdminService:
    return AdminService(db)


def _client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


def _actor(user: UserContext) -> str | None:
    return user.email or user.display_name


# ── Subscription endpoints ─────────────────────────────────────────────


@router.get(
    "/subscriptions",
    summary="List all managed subscriptions",
)
async def list_subscriptions(
    user: UserContext = Depends(require_role(UserRole.SUPER_ADMIN)),
    service: AdminService = Depends(_get_admin_service),
) -> list[dict]:
    """Return all subscriptions stored in the database."""
    return await service.list_subscriptions()


@router.post(
    "/subscriptions",
    summary="Add a subscription to monitor",
    status_code=201,
)
async def add_subscription(
    body: AddSubscriptionRequest,
    request: Request,
    user: UserContext = Depends(require_role(UserRole.SUPER_ADMIN)),
    service: AdminService = Depends(_get_admin_service),
) -> dict:
    """Register a new subscription for cost monitoring (persisted in DB)."""
    try:
        result = await service.add_subscription(
            subscription_id=body.subscription_id,
            subscription_name=(body.subscription_name or "").strip() or body.subscription_id,
            state=body.state,
            enabled=body.enabled,
            monitored=body.monitored,
            environment=body.environment,
            notes=body.notes,
            created_by=_actor(user),
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    invalidate_subscription_cache()
    await service.record_audit(
        user,
        "admin_subscription_add",
        resource_type="admin_subscription",
        resource_id=result["subscription_id"],
        summary=f"Added subscription {result['subscription_name']}",
        details={
            "feature": "managed_subscriptions",
            "environment": result.get("environment"),
            "enabled": result.get("enabled"),
            "monitored": result.get("monitored"),
        },
        ip_address=_client_ip(request),
    )
    return result


@router.put(
    "/subscriptions/{subscription_id}/toggle",
    summary="Toggle subscription enabled/monitored",
)
async def toggle_subscription(
    subscription_id: str,
    body: ToggleSubscriptionRequest,
    request: Request,
    user: UserContext = Depends(require_role(UserRole.SUPER_ADMIN)),
    service: AdminService = Depends(_get_admin_service),
) -> dict:
    """Enable or disable a subscription, or toggle its monitored flag."""
    try:
        result = await service.toggle_subscription(
            subscription_id,
            enabled=body.enabled,
            monitored=body.monitored,
            updated_by=_actor(user),
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    invalidate_subscription_cache()
    changed = {field: value for field, value in body.model_dump().items() if value is not None}
    if changed:
        await service.record_audit(
            user,
            "admin_subscription_toggle",
            resource_type="admin_subscription",
            resource_id=subscription_id,
            summary=f"Set {', '.join(f'{field}={value}' for field, value in changed.items())} "
            f"on {result.get('subscription_name') or subscription_id}",
            details={"feature": "managed_subscriptions", **changed},
            ip_address=_client_ip(request),
        )
    return result


@router.put(
    "/subscriptions/{subscription_id}",
    summary="Update subscription metadata",
)
async def update_subscription(
    subscription_id: str,
    body: UpdateSubscriptionRequest,
    request: Request,
    user: UserContext = Depends(require_role(UserRole.SUPER_ADMIN)),
    service: AdminService = Depends(_get_admin_service),
) -> dict:
    """Update name, environment, or notes of a subscription."""
    try:
        result = await service.update_subscription(
            subscription_id,
            subscription_name=body.subscription_name,
            environment=body.environment,
            notes=body.notes,
            updated_by=_actor(user),
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    invalidate_subscription_cache()
    changes = result.get("changes") or {}
    if changes:
        await service.record_audit(
            user,
            "admin_subscription_update",
            resource_type="admin_subscription",
            resource_id=subscription_id,
            summary=f"Edited {', '.join(changes)} on {result['subscription_name']}",
            details={"feature": "managed_subscriptions", "changes": changes},
            ip_address=_client_ip(request),
        )
    return result


@router.delete(
    "/subscriptions/{subscription_id}",
    summary="Remove a subscription",
)
async def remove_subscription(
    subscription_id: str,
    request: Request,
    user: UserContext = Depends(require_role(UserRole.SUPER_ADMIN)),
    service: AdminService = Depends(_get_admin_service),
) -> dict:
    """Remove a subscription from DB."""
    try:
        result = await service.remove_subscription(subscription_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    invalidate_subscription_cache()
    await service.record_audit(
        user,
        "admin_subscription_delete",
        resource_type="admin_subscription",
        resource_id=subscription_id,
        summary=f"Removed subscription {result.get('subscription_name') or subscription_id}",
        details={"feature": "managed_subscriptions"},
        ip_address=_client_ip(request),
    )
    return result


async def _discover(request: Request, user: UserContext, service: AdminService, *, sync_only: bool) -> dict:
    action = "admin_subscription_sync" if sync_only else "admin_subscription_discover"
    try:
        result = await service.discover_subscriptions(created_by=_actor(user), sync_only=sync_only)
    except Exception as exc:
        await service.record_audit(
            user,
            action,
            resource_type="admin_subscription",
            resource_id=None,
            summary=f"{'Sync' if sync_only else 'Discover'} from Azure failed",
            details={"feature": "managed_subscriptions", "error": str(exc)[:300]},
            ip_address=_client_ip(request),
            status="failed",
        )
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    invalidate_subscription_cache()
    new_ids = [s["subscription_id"] for s in result.get("subscriptions", []) if s.get("is_new")]
    summary = (
        f"Synced {result['updated_count']} subscriptions from Azure"
        if sync_only
        else f"Discovered {result['discovered']} subscriptions from Azure ({result['new_count']} new)"
    )
    await service.record_audit(
        user,
        action,
        resource_type="admin_subscription",
        resource_id=None,
        summary=summary,
        details={
            "feature": "managed_subscriptions",
            "discovered": result["discovered"],
            "new_count": result["new_count"],
            "updated_count": result["updated_count"],
            "new_subscription_ids": new_ids,
        },
        ip_address=_client_ip(request),
    )
    return result


@router.post(
    "/subscriptions/discover",
    summary="Discover subscriptions from Azure",
)
async def discover_subscriptions(
    request: Request,
    user: UserContext = Depends(require_role(UserRole.SUPER_ADMIN)),
    service: AdminService = Depends(_get_admin_service),
) -> dict:
    """Query Azure ARM for all subscriptions visible to the service principal
    and upsert them into the database.  New ones are added as disabled."""
    return await _discover(request, user, service, sync_only=False)


@router.post(
    "/subscriptions/sync",
    summary="Sync existing subscriptions from Azure",
)
async def sync_subscriptions(
    request: Request,
    user: UserContext = Depends(require_role(UserRole.SUPER_ADMIN)),
    service: AdminService = Depends(_get_admin_service),
) -> dict:
    """Re-sync existing subscriptions from Azure ARM.  Updates name and
    state for subscriptions already in the DB without adding new ones."""
    return await _discover(request, user, service, sync_only=True)


# ── System health ──────────────────────────────────────────────────────


@router.get(
    "/system/health",
    summary="System health overview",
)
async def system_health(
    user: UserContext = Depends(require_role(UserRole.SUPER_ADMIN)),
    service: AdminService = Depends(_get_admin_service),
) -> dict:
    """Check health of all system components."""
    return await service.check_system_health()


# ── Audit trail ────────────────────────────────────────────────────────


@router.get(
    "/audit",
    summary="Recent changes made from the Admin page",
)
async def list_admin_activity(
    limit: int = Query(default=200, ge=1, le=1000),
    user: UserContext = Depends(require_role(UserRole.SUPER_ADMIN)),
    service: AdminService = Depends(_get_admin_service),
) -> list[dict]:
    """Subscription, configuration, cache, and certificate-collection changes, newest first."""
    return await service.list_admin_activity(limit=limit)


# ── Admin Config ───────────────────────────────────────────────────────


@router.get(
    "/config",
    summary="List all admin config entries",
)
async def list_admin_config(
    user: UserContext = Depends(require_role(UserRole.SUPER_ADMIN)),
    service: AdminService = Depends(_get_admin_service),
) -> list[dict]:
    """Return all admin configuration entries from the database."""
    return await service.list_admin_configs()


@router.put(
    "/config",
    summary="Create or update an admin config entry",
)
async def upsert_admin_config(
    body: UpsertConfigRequest,
    request: Request,
    user: UserContext = Depends(require_role(UserRole.SUPER_ADMIN)),
    service: AdminService = Depends(_get_admin_service),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Upsert an admin configuration value."""
    key = body.config_key.strip()
    value = body.config_value
    config_type = body.config_type
    description = body.description

    if key not in _CONFIG_KEYS:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown config key {key!r}. Allowed: {', '.join(sorted(_CONFIG_KEYS))}.",
        )

    if key == CORS_CONFIG_KEY:
        try:
            origins = parse_cors_origins(value, strict=True)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if not origins:
            raise HTTPException(status_code=400, detail="At least one valid CORS origin is required.")
        value = serialize_cors_origins(origins)
        config_type = "json"
        if description is None:
            description = "Allowed browser origins for Ops Portal API CORS."

    if key == "rate_limit_rpm":
        try:
            rpm_val = int(value)
        except (ValueError, TypeError) as exc:
            raise HTTPException(status_code=400, detail="rate_limit_rpm must be an integer.") from exc
        if rpm_val < 10 or rpm_val > 10000:
            raise HTTPException(status_code=400, detail="rate_limit_rpm must be between 10 and 10 000.")
        value = str(rpm_val)
        config_type = "integer"
        if description is None:
            description = "Requests per minute per client IP."

    if key == "cache_enabled":
        normalised = value.strip().lower()
        if normalised not in ("true", "false", "1", "0", "yes", "no"):
            raise HTTPException(
                status_code=400,
                detail="cache_enabled must be a boolean value (true/false).",
            )
        value = "true" if normalised in ("true", "1", "yes") else "false"
        config_type = "bool"
        if description is None:
            description = "Enable or disable page caching for Leadership Dashboard."

    if key == "cache_ttl_seconds":
        try:
            ttl_val = int(value)
        except (ValueError, TypeError) as exc:
            raise HTTPException(status_code=400, detail="cache_ttl_seconds must be an integer.") from exc
        if ttl_val != 0 and not 60 <= ttl_val <= _MAX_CACHE_TTL_SECONDS:
            raise HTTPException(
                status_code=400,
                detail="cache_ttl_seconds must be 0 (unlimited) or between 60 and 604800 (7 days).",
            )
        value = str(ttl_val)
        config_type = "integer"

    if key == "portal_timezone":
        value = value.strip()
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=f"Unknown IANA timezone: {value!r}") from exc

    if key == "ollama_enabled":
        normalised = value.strip().lower()
        if normalised not in ("true", "false", "1", "0", "yes", "no"):
            raise HTTPException(
                status_code=400,
                detail="ollama_enabled must be a boolean value (true/false).",
            )
        value = "true" if normalised in ("true", "1", "yes") else "false"
        config_type = "bool"
        if description is None:
            description = "Enable or disable Ollama LLM for Leadership Dashboard forecasts and AI advisor."

    previous = await service.get_admin_config(key)
    result = await service.upsert_admin_config(
        key=key,
        value=value,
        config_type=config_type,
        description=description,
        updated_by=_actor(user),
    )

    # Push rate-limit override into in-memory store so the middleware picks
    # it up immediately without waiting for a DB read.
    if key == "rate_limit_rpm":
        import contextlib

        with contextlib.suppress(Exception):
            set_rate_limit_override(int(value))

    # Refresh the in-process cache-enabled flag immediately so subsequent
    # requests respect the toggle without a restart.
    if key == "cache_enabled":
        from app.core.db_cache import refresh_cache_enabled_flag

        await refresh_cache_enabled_flag(db)

    old_value = previous["config_value"] if previous else None
    if old_value != value:
        await service.record_audit(
            user,
            "admin_config_update",
            resource_type="admin_config",
            resource_id=key,
            summary=f"Changed {key} from {old_value if old_value is not None else '(default)'} to {value}",
            details={"feature": "portal_configuration", "old_value": old_value, "new_value": value},
            ip_address=_client_ip(request),
        )

    return result


@router.post(
    "/cache/release",
    summary="Release cached page and cost data",
)
async def release_cached_data(
    request: Request,
    user: UserContext = Depends(require_role(UserRole.SUPER_ADMIN)),
    service: AdminService = Depends(_get_admin_service),
) -> dict:
    """Release DB-backed page payload and cost query caches."""
    result = await service.release_cached_data()
    await service.record_audit(
        user,
        "admin_cache_release",
        resource_type="admin_cache",
        resource_id=None,
        summary=f"Released {result['released_keys']} cached key(s)",
        details={"feature": "cached_data_release", "patterns": result["patterns"]},
        ip_address=_client_ip(request),
    )
    return result


@router.get(
    "/portal-timezone",
    summary="Get the portal-wide display timezone",
)
async def get_portal_timezone(
    service: AdminService = Depends(_get_admin_service),
) -> dict:
    """Return the configured IANA timezone for portal-wide date display.

    This endpoint is intentionally public (no role guard) so every page
    can read the timezone without admin credentials.
    """
    cfg = await service.get_admin_config("portal_timezone")
    return {"timezone": cfg["config_value"] if cfg else "UTC"}


@router.get(
    "/portal-info",
    summary="Get non-sensitive portal information",
)
async def get_portal_info(
    user: UserContext = Depends(require_role(UserRole.SUPER_ADMIN)),
    service: AdminService = Depends(_get_admin_service),
) -> dict:
    """Return non-sensitive portal configuration (env, version, etc.)."""
    from app.core.config import settings

    subs = await service.list_subscriptions()
    enabled_count = sum(1 for s in subs if s.get("enabled"))

    return {
        "environment": settings.ENVIRONMENT,
        "version": settings.APP_VERSION,
        "subscription_count": len(subs),
        "enabled_subscription_count": enabled_count,
        "smtp_host": settings.SMTP_HOST,
        "rate_limit_rpm": settings.RATE_LIMIT_RPM,
    }
