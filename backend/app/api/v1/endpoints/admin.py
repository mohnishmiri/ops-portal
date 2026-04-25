"""Admin API endpoints for subscription management and portal config."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
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


class AddSubscriptionRequest(BaseModel):
    subscription_id: str = Field(..., min_length=1, description="Azure subscription GUID")
    subscription_name: str = Field(..., min_length=1)
    state: str = Field(default="Unknown")
    enabled: bool = Field(default=True)
    monitored: bool = Field(default=True)
    environment: str | None = None
    notes: str | None = None


class ToggleSubscriptionRequest(BaseModel):
    enabled: bool | None = None
    monitored: bool | None = None


class UpdateSubscriptionRequest(BaseModel):
    subscription_name: str | None = None
    environment: str | None = None
    notes: str | None = None


class UpsertConfigRequest(BaseModel):
    config_key: str = Field(..., min_length=1)
    config_value: str
    config_type: str = Field(default="string")
    description: str | None = None


# ── Dependency ─────────────────────────────────────────────────────────


def _get_admin_service(db: AsyncSession = Depends(get_db)) -> AdminService:
    return AdminService(db)


# ── Subscription endpoints ─────────────────────────────────────────────


@router.get(
    "/subscriptions",
    summary="List all managed subscriptions",
)
async def list_subscriptions(
    user: UserContext = Depends(require_role(UserRole.ADMIN)),
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
    user: UserContext = Depends(require_role(UserRole.ADMIN)),
    service: AdminService = Depends(_get_admin_service),
) -> dict:
    """Register a new subscription for cost monitoring (persisted in DB)."""
    try:
        result = await service.add_subscription(
            subscription_id=body.subscription_id,
            subscription_name=body.subscription_name,
            state=body.state,
            enabled=body.enabled,
            monitored=body.monitored,
            environment=body.environment,
            notes=body.notes,
            created_by=user.email or user.display_name,
        )
        invalidate_subscription_cache()
        return result
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.put(
    "/subscriptions/{subscription_id}/toggle",
    summary="Toggle subscription enabled/monitored",
)
async def toggle_subscription(
    subscription_id: str,
    body: ToggleSubscriptionRequest,
    user: UserContext = Depends(require_role(UserRole.ADMIN)),
    service: AdminService = Depends(_get_admin_service),
) -> dict:
    """Enable or disable a subscription, or toggle its monitored flag."""
    try:
        result = await service.toggle_subscription(
            subscription_id,
            enabled=body.enabled,
            monitored=body.monitored,
            updated_by=user.email or user.display_name,
        )
        invalidate_subscription_cache()
        return result
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.put(
    "/subscriptions/{subscription_id}",
    summary="Update subscription metadata",
)
async def update_subscription(
    subscription_id: str,
    body: UpdateSubscriptionRequest,
    user: UserContext = Depends(require_role(UserRole.ADMIN)),
    service: AdminService = Depends(_get_admin_service),
) -> dict:
    """Update name, environment, or notes of a subscription."""
    try:
        result = await service.update_subscription(
            subscription_id,
            subscription_name=body.subscription_name,
            environment=body.environment,
            notes=body.notes,
            updated_by=user.email or user.display_name,
        )
        invalidate_subscription_cache()
        return result
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.delete(
    "/subscriptions/{subscription_id}",
    summary="Remove a subscription",
)
async def remove_subscription(
    subscription_id: str,
    user: UserContext = Depends(require_role(UserRole.ADMIN)),
    service: AdminService = Depends(_get_admin_service),
) -> dict:
    """Remove a subscription from DB."""
    try:
        result = await service.remove_subscription(subscription_id)
        invalidate_subscription_cache()
        return result
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post(
    "/subscriptions/discover",
    summary="Discover subscriptions from Azure",
)
async def discover_subscriptions(
    user: UserContext = Depends(require_role(UserRole.ADMIN)),
    service: AdminService = Depends(_get_admin_service),
) -> dict:
    """Query Azure ARM for all subscriptions visible to the service principal
    and upsert them into the database.  New ones are added as disabled."""
    try:
        result = await service.discover_subscriptions(
            created_by=user.email or user.display_name,
            sync_only=False,
        )
        invalidate_subscription_cache()
        return result
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post(
    "/subscriptions/sync",
    summary="Sync existing subscriptions from Azure",
)
async def sync_subscriptions(
    user: UserContext = Depends(require_role(UserRole.ADMIN)),
    service: AdminService = Depends(_get_admin_service),
) -> dict:
    """Re-sync existing subscriptions from Azure ARM.  Updates name and
    state for subscriptions already in the DB without adding new ones."""
    try:
        result = await service.discover_subscriptions(
            created_by=user.email or user.display_name,
            sync_only=True,
        )
        invalidate_subscription_cache()
        return result
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


# ── System health ──────────────────────────────────────────────────────


@router.get(
    "/system/health",
    summary="System health overview",
)
async def system_health(
    user: UserContext = Depends(require_role(UserRole.ADMIN)),
    service: AdminService = Depends(_get_admin_service),
) -> dict:
    """Check health of all system components."""
    return await service.check_system_health()


# ── Admin Config ───────────────────────────────────────────────────────


@router.get(
    "/config",
    summary="List all admin config entries",
)
async def list_admin_config(
    user: UserContext = Depends(require_role(UserRole.ADMIN)),
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
    user: UserContext = Depends(require_role(UserRole.ADMIN)),
    service: AdminService = Depends(_get_admin_service),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Upsert an admin configuration value."""
    key = body.config_key.strip()
    value = body.config_value
    config_type = body.config_type
    description = body.description

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

    result = await service.upsert_admin_config(
        key=key,
        value=value,
        config_type=config_type,
        description=description,
        updated_by=user.email or user.display_name,
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

    return result


@router.post(
    "/cache/release",
    summary="Release cached page and cost data",
)
async def release_cached_data(
    user: UserContext = Depends(require_role(UserRole.ADMIN)),
    service: AdminService = Depends(_get_admin_service),
) -> dict:
    """Release Redis-backed page payload and cost query caches."""
    return await service.release_cached_data()


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
    user: UserContext = Depends(require_role(UserRole.ADMIN)),
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
