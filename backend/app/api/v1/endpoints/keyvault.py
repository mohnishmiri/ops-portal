"""
Key Vault API Endpoints.

Full management interface for Azure Key Vault: vault discovery,
secrets, keys, and certificates across all monitored subscriptions.

Reads are served from PostgreSQL for fast response times.
Data is kept in sync via periodic background jobs and immediate
post-mutation updates.
"""

from datetime import UTC, datetime, timedelta

import structlog
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user, require_role
from app.core.database import get_db
from app.models.auth import UserContext, UserRole
from app.models.database import AuditLog
from app.services.keyvault_service import KeyVaultService
from app.services.keyvault_sync_service import KeyVaultSyncService

logger = structlog.get_logger(__name__)
router = APIRouter()


def _get_kv_service() -> KeyVaultService:
    return KeyVaultService()


def _get_sync_service(db: AsyncSession = Depends(get_db)) -> KeyVaultSyncService:
    return KeyVaultSyncService(db)


def _vault_name_from_uri(vault_uri: str) -> str:
    trimmed = vault_uri.rstrip("/")
    if "//" not in trimmed:
        return trimmed
    host = trimmed.split("//", 1)[1]
    return host.split(".", 1)[0]


def _audit_summary(action: str, resource_type: str, resource_name: str) -> str:
    verb = {
        "create_secret": "Created",
        "update_secret": "Updated",
        "delete_secret": "Deleted",
        "create_key": "Created",
        "update_key": "Updated",
        "delete_key": "Deleted",
    }.get(action, "Changed")
    return f"{verb} {resource_type} {resource_name}"


def _dashboard_cache_looks_zeroed(payload: dict | None) -> bool:
    if not payload:
        return False
    return (
        (payload.get("total_vaults") or 0) > 0
        and (payload.get("total_secrets") or 0) == 0
        and (payload.get("total_keys") or 0) == 0
        and (payload.get("total_certificates") or 0) == 0
    )


def _serialize_audit_entry(entry: AuditLog) -> dict:
    details = entry.details if isinstance(entry.details, dict) else {}
    resource_name = details.get("resource_name") or entry.resource_id or "unknown"
    resource_type = details.get("resource_type") or entry.resource_type or "item"
    summary = details.get("summary") or _audit_summary(entry.action, resource_type, resource_name)
    vault_uri = details.get("vault_uri") or ""
    vault_name = details.get("vault_name") or _vault_name_from_uri(vault_uri)

    return {
        "id": entry.id,
        "timestamp": entry.timestamp.isoformat() if entry.timestamp else None,
        "user_id": entry.user_id,
        "user_email": entry.user_email,
        "action": entry.action,
        "resource_type": resource_type,
        "resource_id": entry.resource_id,
        "resource_name": resource_name,
        "vault_uri": vault_uri,
        "vault_name": vault_name,
        "status": entry.status,
        "summary": summary,
        "details": details,
    }


async def _write_keyvault_audit_log(
    db: AsyncSession | None,
    *,
    request: Request | None,
    user: UserContext,
    action: str,
    resource_type: str,
    resource_name: str,
    vault_uri: str,
    status: str,
    details: dict,
) -> None:
    if db is None:
        return

    audit = AuditLog(
        user_id=user.user_id,
        user_email=user.email,
        action=action,
        resource_type=resource_type,
        resource_id=resource_name,
        details={
            "page": "KeyVaultPage",
            "feature": "keyvault_audit_history",
            "vault_uri": vault_uri,
            "vault_name": _vault_name_from_uri(vault_uri),
            "resource_type": resource_type,
            "resource_name": resource_name,
            "summary": details.get("summary") or _audit_summary(action, resource_type, resource_name),
            **details,
        },
        ip_address=request.client.host if request and request.client else None,
        status=status,
    )

    try:
        db.add(audit)
        await db.commit()
    except Exception as exc:
        await db.rollback()
        logger.warning(
            "keyvault_audit_log_failed",
            action=action,
            resource_type=resource_type,
            resource_name=resource_name,
            error=str(exc),
        )


async def _item_exists_in_cache(
    sync_service: KeyVaultSyncService,
    vault_uri: str,
    resource_type: str,
    resource_name: str,
) -> bool:
    try:
        if resource_type == "secret":
            items = await sync_service.get_secrets_from_db(vault_uri)
        elif resource_type == "key":
            items = await sync_service.get_keys_from_db(vault_uri)
        else:
            items = []
    except Exception:
        return False

    return any(item.get("name") == resource_name for item in (items or []))


# ── Request Models ─────────────────────────────────────────────────────


class CreateSecretRequest(BaseModel):
    """Request to create or update a secret."""

    vault_uri: str
    name: str = Field(min_length=1, max_length=127, pattern=r"^[a-zA-Z0-9-]+$")
    value: str
    content_type: str | None = None
    tags: dict[str, str] = Field(default_factory=dict)
    encode_base64: bool = False
    not_before: str | None = None  # ISO-8601 date (defaults to now)
    expires: str | None = None  # ISO-8601 date (defaults to now + 360 days)


class DeleteSecretRequest(BaseModel):
    """Request to delete a secret."""

    vault_uri: str
    name: str


class CreateKeyRequest(BaseModel):
    """Request to create or update a key."""

    vault_uri: str
    name: str = Field(min_length=1, max_length=127, pattern=r"^[a-zA-Z0-9-]+$")
    kty: str = "RSA"  # RSA, EC, oct, RSA-HSM, EC-HSM
    key_size: int | None = None  # 2048, 3072, 4096 for RSA
    key_ops: list[str] | None = None  # encrypt, decrypt, sign, verify, wrapKey, unwrapKey
    not_before: str | None = None  # ISO-8601 date (defaults to now)
    expires: str | None = None  # ISO-8601 date (defaults to now + 360 days)


class ExtendSecretExpiryRequest(BaseModel):
    """Extend a single secret's expiry by 360 days from its current expiry."""

    vault_uri: str
    name: str


class BulkExtendSecretExpiryRequest(BaseModel):
    """Extend expiry for multiple secrets (each +360 days from current expiry)."""

    secrets: list[ExtendSecretExpiryRequest]


# ── Dashboard ──────────────────────────────────────────────────────────


@router.get(
    "/dashboard",
    summary="Key Vault dashboard summary",
    description="Aggregate summary of all vaults, counts, and expiring items. Served from DB for fast load.",
)
async def keyvault_dashboard(
    refresh: bool = Query(default=False, description="Bypass DB cache and fetch fresh data from Azure"),
    user: UserContext = Depends(get_current_user),
    service: KeyVaultService = Depends(_get_kv_service),
    sync_service: KeyVaultSyncService = Depends(_get_sync_service),
) -> dict:
    """Key Vault dashboard — reads from PG; falls back to Azure if DB empty."""
    try:
        if not refresh:
            db_data = await sync_service.get_dashboard_from_db()
            if db_data:
                if _dashboard_cache_looks_zeroed(db_data):
                    try:
                        return await service.get_dashboard_summary(refresh=True)
                    except Exception as live_error:
                        logger.warning("keyvault_dashboard_live_recovery_failed", error=str(live_error))
                return db_data
    except Exception as e:
        logger.warning("keyvault_dashboard_db_fallback", error=str(e))

    try:
        # Fallback: live Azure API (also used for explicit refresh)
        return await service.get_dashboard_summary(refresh=refresh)
    except Exception as e:
        logger.warning("keyvault_dashboard_error", error=str(e))
        raise HTTPException(
            status_code=502,
            detail=f"Cannot load Key Vault dashboard: {_friendly_error(e)}",
        )


# ── Vaults ─────────────────────────────────────────────────────────────


@router.get(
    "/vaults",
    summary="List all Key Vaults",
    description="Discover vaults across all monitored subscriptions. Served from DB.",
)
async def list_vaults(
    refresh: bool = Query(default=False, description="Bypass DB and fetch fresh data from Azure"),
    user: UserContext = Depends(get_current_user),
    service: KeyVaultService = Depends(_get_kv_service),
    sync_service: KeyVaultSyncService = Depends(_get_sync_service),
) -> list[dict]:
    """List all Key Vaults — reads from PG; falls back to Azure if DB empty."""
    try:
        if not refresh:
            db_data = await sync_service.get_vaults_from_db()
            if db_data is not None:
                return db_data
    except Exception as e:
        logger.warning("list_vaults_db_fallback", error=str(e))

    try:
        return await service.list_vaults(refresh=refresh)
    except Exception as e:
        logger.warning("list_vaults_error", error=str(e))
        raise HTTPException(
            status_code=502,
            detail=f"Cannot load Key Vault vaults: {_friendly_error(e)}",
        )


# ── Secrets ────────────────────────────────────────────────────────────


@router.get(
    "/secrets",
    summary="List secrets in a vault",
)
async def list_secrets(
    vault_uri: str = Query(description="Key Vault URI (e.g. https://myvault.vault.azure.net/)"),
    search: str | None = Query(default=None, description="Filter by name"),
    refresh: bool = Query(default=False, description="Bypass DB and fetch fresh data from Azure"),
    user: UserContext = Depends(get_current_user),
    service: KeyVaultService = Depends(_get_kv_service),
    sync_service: KeyVaultSyncService = Depends(_get_sync_service),
) -> list[dict]:
    """List secrets (names/metadata only, never values). Served from DB."""
    try:
        if not refresh:
            db_data = await sync_service.get_secrets_from_db(vault_uri, search)
            if db_data is not None:
                if not db_data:
                    try:
                        return await service.list_secrets(vault_uri, search, refresh=False)
                    except Exception as live_error:
                        logger.warning("list_secrets_live_recovery_failed", vault_uri=vault_uri, error=str(live_error))
                return db_data
        return await service.list_secrets(vault_uri, search, refresh=refresh)
    except Exception as e:
        logger.warning("list_secrets_error", vault_uri=vault_uri, error=str(e))
        raise HTTPException(
            status_code=502,
            detail=f"Cannot access vault data plane: {_friendly_error(e)}",
        )


@router.get(
    "/secrets/{name}",
    summary="Get secret value",
)
async def get_secret(
    name: str,
    vault_uri: str = Query(description="Key Vault URI"),
    user: UserContext = Depends(get_current_user),
    service: KeyVaultService = Depends(_get_kv_service),
) -> dict:
    """Get a secret value. Any authenticated user."""
    try:
        return await service.get_secret_value(vault_uri, name)
    except Exception as e:
        logger.warning("get_secret_error", vault_uri=vault_uri, name=name, error=str(e))
        raise HTTPException(status_code=502, detail=f"Cannot retrieve secret: {_friendly_error(e)}")


@router.post(
    "/secrets",
    summary="Create or update a secret (Write)",
)
async def create_secret(
    request: CreateSecretRequest,
    background_tasks: BackgroundTasks,
    http_request: Request,
    user: UserContext = Depends(require_role(UserRole.WRITE)),
    service: KeyVaultService = Depends(_get_kv_service),
    sync_service: KeyVaultSyncService = Depends(_get_sync_service),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Create or update a secret. Write role required. Triggers vault sync."""
    existing = await _item_exists_in_cache(sync_service, request.vault_uri, "secret", request.name)
    action = "update_secret" if existing else "create_secret"

    try:
        result = await service.create_or_update_secret(
            vault_uri=request.vault_uri,
            name=request.name,
            value=request.value,
            content_type=request.content_type,
            tags=request.tags,
            encode_base64=request.encode_base64,
            not_before=request.not_before,
            expires=request.expires,
        )
        await _write_keyvault_audit_log(
            db,
            request=http_request,
            user=user,
            action=action,
            resource_type="secret",
            resource_name=request.name,
            vault_uri=request.vault_uri,
            status="success",
            details={
                "content_type": request.content_type,
                "encode_base64": request.encode_base64,
                "tag_keys": sorted((request.tags or {}).keys()),
                "not_before": request.not_before,
                "expires": request.expires,
            },
        )
        # Sync vault in background after mutation
        background_tasks.add_task(sync_service.sync_vault, request.vault_uri, triggered_by="mutation")
        return result
    except Exception as e:
        await _write_keyvault_audit_log(
            db,
            request=http_request,
            user=user,
            action=action,
            resource_type="secret",
            resource_name=request.name,
            vault_uri=request.vault_uri,
            status="failed",
            details={
                "content_type": request.content_type,
                "encode_base64": request.encode_base64,
                "tag_keys": sorted((request.tags or {}).keys()),
                "not_before": request.not_before,
                "expires": request.expires,
                "error": str(e),
            },
        )
        logger.warning("create_secret_error", vault_uri=request.vault_uri, error=str(e))
        raise HTTPException(status_code=502, detail=f"Cannot create secret: {_friendly_error(e)}")


@router.delete(
    "/secrets/{name}",
    summary="Delete a secret (Write)",
)
async def delete_secret(
    name: str,
    vault_uri: str = Query(description="Key Vault URI"),
    background_tasks: BackgroundTasks = BackgroundTasks(),
    http_request: Request = None,
    user: UserContext = Depends(require_role(UserRole.WRITE)),
    service: KeyVaultService = Depends(_get_kv_service),
    sync_service: KeyVaultSyncService = Depends(_get_sync_service),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Soft-delete a secret. Write role required. Triggers vault sync."""
    try:
        result = await service.delete_secret(vault_uri, name)
        await _write_keyvault_audit_log(
            db,
            request=http_request,
            user=user,
            action="delete_secret",
            resource_type="secret",
            resource_name=name,
            vault_uri=vault_uri,
            status="success",
            details={
                "recovery_id": result.get("recovery_id"),
            },
        )
        background_tasks.add_task(sync_service.sync_vault, vault_uri, triggered_by="mutation")
        return result
    except Exception as e:
        await _write_keyvault_audit_log(
            db,
            request=http_request,
            user=user,
            action="delete_secret",
            resource_type="secret",
            resource_name=name,
            vault_uri=vault_uri,
            status="failed",
            details={"error": str(e)},
        )
        logger.warning("delete_secret_error", vault_uri=vault_uri, name=name, error=str(e))
        raise HTTPException(status_code=502, detail=f"Cannot delete secret: {_friendly_error(e)}")


@router.post(
    "/secrets/extend-expiry",
    summary="Extend a secret's expiry by 360 days (Write)",
)
async def extend_secret_expiry(
    request: ExtendSecretExpiryRequest,
    background_tasks: BackgroundTasks,
    http_request: Request,
    user: UserContext = Depends(require_role(UserRole.WRITE)),
    service: KeyVaultService = Depends(_get_kv_service),
    sync_service: KeyVaultSyncService = Depends(_get_sync_service),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Fetch current secret value and update its expiry to today + 360 days."""
    try:
        current = await service.get_secret_value(request.vault_uri, request.name)
        current_expires = current.get("expires")
        new_expiry = (datetime.now(UTC) + timedelta(days=360)).isoformat()

        result = await service.create_or_update_secret(
            vault_uri=request.vault_uri,
            name=request.name,
            value=current["value"],
            content_type=current.get("content_type") or None,
            expires=new_expiry,
        )
        await _write_keyvault_audit_log(
            db,
            request=http_request,
            user=user,
            action="update_secret",
            resource_type="secret",
            resource_name=request.name,
            vault_uri=request.vault_uri,
            status="success",
            details={"extended_expiry": new_expiry, "previous_expiry": current_expires},
        )
        background_tasks.add_task(sync_service.sync_vault, request.vault_uri, triggered_by="mutation")
        return {**result, "new_expiry": new_expiry, "previous_expiry": current_expires}
    except Exception as e:
        logger.warning("extend_secret_expiry_error", vault_uri=request.vault_uri, name=request.name, error=str(e))
        raise HTTPException(status_code=502, detail=f"Cannot extend secret expiry: {_friendly_error(e)}")


@router.post(
    "/secrets/bulk-extend-expiry",
    summary="Extend expiry for multiple secrets by 360 days (Write)",
)
async def bulk_extend_secret_expiry(
    request: BulkExtendSecretExpiryRequest,
    background_tasks: BackgroundTasks,
    http_request: Request,
    user: UserContext = Depends(require_role(UserRole.WRITE)),
    service: KeyVaultService = Depends(_get_kv_service),
    sync_service: KeyVaultSyncService = Depends(_get_sync_service),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Extend expiry for multiple secrets by 360 days each. Returns success/failure per secret."""
    results = []
    vaults_touched: set[str] = set()

    for item in request.secrets:
        try:
            current = await service.get_secret_value(item.vault_uri, item.name)
            current_expires = current.get("expires")
            new_expiry = (datetime.now(UTC) + timedelta(days=360)).isoformat()

            await service.create_or_update_secret(
                vault_uri=item.vault_uri,
                name=item.name,
                value=current["value"],
                content_type=current.get("content_type") or None,
                expires=new_expiry,
            )
            await _write_keyvault_audit_log(
                db,
                request=http_request,
                user=user,
                action="update_secret",
                resource_type="secret",
                resource_name=item.name,
                vault_uri=item.vault_uri,
                status="success",
                details={"extended_expiry": new_expiry, "previous_expiry": current_expires, "bulk": True},
            )
            vaults_touched.add(item.vault_uri)
            results.append(
                {"name": item.name, "vault_uri": item.vault_uri, "status": "success", "new_expiry": new_expiry}
            )
        except Exception as e:
            logger.warning("bulk_extend_secret_error", vault_uri=item.vault_uri, name=item.name, error=str(e))
            results.append(
                {"name": item.name, "vault_uri": item.vault_uri, "status": "failed", "error": _friendly_error(e)}
            )

    for vault_uri in vaults_touched:
        background_tasks.add_task(sync_service.sync_vault, vault_uri, triggered_by="mutation")

    success_count = sum(1 for r in results if r["status"] == "success")
    return {"results": results, "success_count": success_count, "failed_count": len(results) - success_count}


# ── Keys ───────────────────────────────────────────────────────────────


@router.get(
    "/keys",
    summary="List keys in a vault",
)
async def list_keys(
    vault_uri: str = Query(description="Key Vault URI"),
    refresh: bool = Query(default=False, description="Bypass DB and fetch fresh data from Azure"),
    user: UserContext = Depends(get_current_user),
    service: KeyVaultService = Depends(_get_kv_service),
    sync_service: KeyVaultSyncService = Depends(_get_sync_service),
) -> list[dict]:
    """List cryptographic keys. Served from DB."""
    try:
        if not refresh:
            db_data = await sync_service.get_keys_from_db(vault_uri)
            if db_data is not None:
                if not db_data:
                    try:
                        return await service.list_keys(vault_uri, refresh=False)
                    except Exception as live_error:
                        logger.warning("list_keys_live_recovery_failed", vault_uri=vault_uri, error=str(live_error))
                return db_data
        return await service.list_keys(vault_uri, refresh=refresh)
    except Exception as e:
        logger.warning("list_keys_error", vault_uri=vault_uri, error=str(e))
        raise HTTPException(
            status_code=502,
            detail=f"Cannot access vault data plane: {_friendly_error(e)}",
        )


@router.get(
    "/keys/{name}",
    summary="Get key details",
)
async def get_key(
    name: str,
    vault_uri: str = Query(description="Key Vault URI"),
    user: UserContext = Depends(get_current_user),
    service: KeyVaultService = Depends(_get_kv_service),
) -> dict:
    """Get key metadata and public key info."""
    try:
        return await service.get_key(vault_uri, name)
    except Exception as e:
        logger.warning("get_key_error", vault_uri=vault_uri, name=name, error=str(e))
        raise HTTPException(status_code=502, detail=f"Cannot retrieve key: {_friendly_error(e)}")


@router.post(
    "/keys",
    summary="Create or update a key (Write)",
)
async def create_key(
    request: CreateKeyRequest,
    background_tasks: BackgroundTasks,
    http_request: Request,
    user: UserContext = Depends(require_role(UserRole.WRITE)),
    service: KeyVaultService = Depends(_get_kv_service),
    sync_service: KeyVaultSyncService = Depends(_get_sync_service),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Create or update a cryptographic key. Write role required. Triggers vault sync."""
    existing = await _item_exists_in_cache(sync_service, request.vault_uri, "key", request.name)
    action = "update_key" if existing else "create_key"

    try:
        result = await service.create_or_update_key(
            vault_uri=request.vault_uri,
            name=request.name,
            kty=request.kty,
            key_size=request.key_size,
            key_ops=request.key_ops,
            not_before=request.not_before,
            expires=request.expires,
        )
        await _write_keyvault_audit_log(
            db,
            request=http_request,
            user=user,
            action=action,
            resource_type="key",
            resource_name=request.name,
            vault_uri=request.vault_uri,
            status="success",
            details={
                "kty": request.kty,
                "key_size": request.key_size,
                "key_ops": request.key_ops or [],
                "not_before": request.not_before,
                "expires": request.expires,
            },
        )
        background_tasks.add_task(sync_service.sync_vault, request.vault_uri, triggered_by="mutation")
        return result
    except Exception as e:
        await _write_keyvault_audit_log(
            db,
            request=http_request,
            user=user,
            action=action,
            resource_type="key",
            resource_name=request.name,
            vault_uri=request.vault_uri,
            status="failed",
            details={
                "kty": request.kty,
                "key_size": request.key_size,
                "key_ops": request.key_ops or [],
                "not_before": request.not_before,
                "expires": request.expires,
                "error": str(e),
            },
        )
        logger.warning("create_key_error", vault_uri=request.vault_uri, error=str(e))
        raise HTTPException(status_code=502, detail=f"Cannot create key: {_friendly_error(e)}")


@router.delete(
    "/keys/{name}",
    summary="Delete a key (Write)",
)
async def delete_key(
    name: str,
    vault_uri: str = Query(description="Key Vault URI"),
    background_tasks: BackgroundTasks = BackgroundTasks(),
    http_request: Request = None,
    user: UserContext = Depends(require_role(UserRole.WRITE)),
    service: KeyVaultService = Depends(_get_kv_service),
    sync_service: KeyVaultSyncService = Depends(_get_sync_service),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Soft-delete a key. Write role required. Triggers vault sync."""
    try:
        result = await service.delete_key(vault_uri, name)
        await _write_keyvault_audit_log(
            db,
            request=http_request,
            user=user,
            action="delete_key",
            resource_type="key",
            resource_name=name,
            vault_uri=vault_uri,
            status="success",
            details={
                "recovery_id": result.get("recovery_id"),
            },
        )
        background_tasks.add_task(sync_service.sync_vault, vault_uri, triggered_by="mutation")
        return result
    except Exception as e:
        await _write_keyvault_audit_log(
            db,
            request=http_request,
            user=user,
            action="delete_key",
            resource_type="key",
            resource_name=name,
            vault_uri=vault_uri,
            status="failed",
            details={"error": str(e)},
        )
        logger.warning("delete_key_error", vault_uri=vault_uri, name=name, error=str(e))
        raise HTTPException(status_code=502, detail=f"Cannot delete key: {_friendly_error(e)}")


# ── Certificates ───────────────────────────────────────────────────────


@router.get(
    "/certificates",
    summary="List certificates in a vault",
)
async def list_certificates(
    vault_uri: str = Query(description="Key Vault URI"),
    refresh: bool = Query(default=False, description="Bypass DB and fetch fresh data from Azure"),
    user: UserContext = Depends(get_current_user),
    service: KeyVaultService = Depends(_get_kv_service),
    sync_service: KeyVaultSyncService = Depends(_get_sync_service),
) -> list[dict]:
    """List certificates. Served from DB."""
    try:
        if not refresh:
            db_data = await sync_service.get_certificates_from_db(vault_uri)
            if db_data is not None:
                if not db_data:
                    try:
                        return await service.list_certificates(vault_uri, refresh=False)
                    except Exception as live_error:
                        logger.warning(
                            "list_certificates_live_recovery_failed", vault_uri=vault_uri, error=str(live_error)
                        )
                return db_data
        return await service.list_certificates(vault_uri, refresh=refresh)
    except Exception as e:
        logger.warning("list_certs_error", vault_uri=vault_uri, error=str(e))
        raise HTTPException(
            status_code=502,
            detail=f"Cannot access vault data plane: {_friendly_error(e)}",
        )


@router.get(
    "/certificates/{name}",
    summary="Get certificate details",
)
async def get_certificate(
    name: str,
    vault_uri: str = Query(description="Key Vault URI"),
    user: UserContext = Depends(get_current_user),
    service: KeyVaultService = Depends(_get_kv_service),
) -> dict:
    """Get certificate details and policy."""
    try:
        return await service.get_certificate(vault_uri, name)
    except Exception as e:
        logger.warning("get_cert_error", vault_uri=vault_uri, name=name, error=str(e))
        raise HTTPException(status_code=502, detail=f"Cannot retrieve certificate: {_friendly_error(e)}")


@router.get(
    "/history",
    summary="Get Key Vault CRUD audit history",
    description="Returns create, update, and delete history for Key Vault secrets and keys from the shared audit log.",
)
async def get_audit_history(
    vault_uri: str | None = Query(default=None, description="Filter by Key Vault URI"),
    days: int = Query(default=90, ge=1, le=365, description="Number of days of history to return"),
    limit: int = Query(default=200, ge=1, le=1000, description="Maximum records to return"),
    user: UserContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Get Key Vault create, update, and delete history for audit review."""
    if db is None:
        return {"history": [], "count": 0}

    actions = (
        "create_secret",
        "update_secret",
        "delete_secret",
        "create_key",
        "update_key",
        "delete_key",
    )
    since = datetime.now(UTC).replace(tzinfo=None) - timedelta(days=days)

    statement = (
        select(AuditLog)
        .where(AuditLog.action.in_(actions))
        .where(AuditLog.timestamp >= since)
        .order_by(desc(AuditLog.timestamp))
        .limit(limit)
    )
    if vault_uri:
        statement = statement.where(AuditLog.details["vault_uri"].astext == vault_uri)

    result = await db.execute(statement)
    history = [_serialize_audit_entry(entry) for entry in result.scalars().all()]
    return {
        "history": history,
        "count": len(history),
    }


# ── Sync Endpoints ─────────────────────────────────────────────────────


@router.post(
    "/sync",
    summary="Trigger full KeyVault sync (Write)",
    description="Pulls all vaults and their items from Azure into PG",
)
async def trigger_sync(
    user: UserContext = Depends(require_role(UserRole.WRITE)),
    sync_service: KeyVaultSyncService = Depends(_get_sync_service),
) -> dict:
    """Trigger a full KeyVault sync from Azure to PG."""
    try:
        return await sync_service.full_sync(triggered_by="manual")
    except Exception as e:
        logger.error("kv_sync_trigger_error", error=str(e))
        raise HTTPException(status_code=502, detail=f"Sync failed: {str(e)[:300]}")


@router.post(
    "/sync/{vault_name}",
    summary="Sync a single vault (Write)",
    description="Re-sync one vault's secrets, keys, and certificates",
)
async def trigger_vault_sync(
    vault_name: str,
    vault_uri: str = Query(description="Key Vault URI"),
    user: UserContext = Depends(require_role(UserRole.WRITE)),
    sync_service: KeyVaultSyncService = Depends(_get_sync_service),
) -> dict:
    """Sync a single vault to PG."""
    try:
        return await sync_service.sync_vault(vault_uri, triggered_by="manual")
    except Exception as e:
        logger.error("kv_vault_sync_error", vault=vault_name, error=str(e))
        raise HTTPException(status_code=502, detail=f"Vault sync failed: {str(e)[:300]}")


@router.get(
    "/sync/status",
    summary="Get sync status",
    description="Returns recent sync history and counts of cached data",
)
async def get_sync_status(
    limit: int = 5,
    user: UserContext = Depends(get_current_user),
    sync_service: KeyVaultSyncService = Depends(_get_sync_service),
) -> dict:
    """Get KeyVault sync status."""
    return await sync_service.get_sync_status(limit=limit)


# ── Helpers ────────────────────────────────────────────────────────────


def _friendly_error(exc: Exception) -> str:
    """Extract a user-friendly message from Key Vault errors."""
    msg = str(exc)
    if "403" in msg or "Forbidden" in msg:
        if "caller is not a trusted service" in msg or "not authorized" in msg:
            return (
                "Access denied. Client IP is not authorized by the vault's network rules (private endpoint / firewall)."
            )
        return "Access denied. Service principal needs Key Vault data plane access policies (Get, List) or RBAC roles."
    if "400" in msg or "Bad Request" in msg:
        if "not authorized" in msg or "firewall" in msg.lower():
            return "Vault firewall is blocking this request. Your IP is not in the vault's allowed list."
        if "ForbiddenByConnection" in msg or "public network access" in msg.lower():
            return "Vault has public network access disabled. Only accessible via private endpoint within the VNet."
        return f"Vault data plane rejected the request. This usually means the vault has network restrictions (private endpoint / firewall). Detail: {msg[:200]}"
    if "401" in msg or "Unauthorized" in msg:
        return "Authentication failed. The service principal token may be invalid or expired."
    if "404" in msg or "Not Found" in msg:
        return "Vault or item not found."
    if "timeout" in msg.lower() or "timed out" in msg.lower():
        return "Request timed out. Vault may be behind a private endpoint."
    return msg[:300]
