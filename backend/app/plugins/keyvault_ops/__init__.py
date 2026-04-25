"""
Key Vault Operations Plugin — Secret management for Azure Key Vault.

Provides RBAC-protected secret search, add, view with Base64 encode/decode.
"""

import base64

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.auth import get_current_user, require_role
from app.core.config import settings
from app.models.auth import UserContext, UserRole
from app.plugins import PluginBase, PluginMetadata

logger = structlog.get_logger(__name__)

router = APIRouter()


# ── Request/Response Models ────────────────────────────────────────────


class SecretInfo(BaseModel):
    """Secret metadata (without value for listing)."""

    name: str
    vault_url: str
    content_type: str | None = None
    enabled: bool = True
    created_on: str | None = None
    updated_on: str | None = None
    expires_on: str | None = None
    tags: dict[str, str] = Field(default_factory=dict)


class SecretValue(BaseModel):
    """Secret with value (protected by Admin role)."""

    name: str
    value: str
    is_base64: bool = False
    decoded_value: str | None = None


class CreateSecretRequest(BaseModel):
    """Request to create or update a secret."""

    name: str = Field(min_length=1, max_length=127, pattern=r"^[a-zA-Z0-9-]+$")
    value: str
    content_type: str | None = None
    tags: dict[str, str] = Field(default_factory=dict)
    encode_base64: bool = Field(default=False, description="Base64 encode the value before storing")


class Base64Request(BaseModel):
    """Request for Base64 encode/decode."""

    value: str
    operation: str = Field(description="encode or decode")


# ── Endpoints ──────────────────────────────────────────────────────────


@router.get("/secrets", response_model=list[SecretInfo], summary="List secrets")
async def list_secrets(
    search: str | None = Query(default=None, description="Search by name prefix"),
    user: UserContext = Depends(get_current_user),
) -> list[SecretInfo]:
    """List secrets in Key Vault (names only, not values)."""
    from azure.keyvault.secrets import SecretClient

    from app.core.azure_auth import get_azure_credential

    if not settings.KEYVAULT_URL:
        raise HTTPException(status_code=400, detail="Key Vault URL not configured")

    client = SecretClient(vault_url=settings.KEYVAULT_URL, credential=get_azure_credential())
    secrets = []

    for prop in client.list_properties_of_secrets():
        if search and not prop.name.lower().startswith(search.lower()):
            continue
        secrets.append(
            SecretInfo(
                name=prop.name,
                vault_url=settings.KEYVAULT_URL,
                content_type=prop.content_type,
                enabled=prop.enabled if prop.enabled is not None else True,
                created_on=prop.created_on.isoformat() if prop.created_on else None,
                updated_on=prop.updated_on.isoformat() if prop.updated_on else None,
                expires_on=prop.expires_on.isoformat() if prop.expires_on else None,
                tags=prop.tags or {},
            )
        )

    client.close()
    return secrets


@router.get("/secrets/{name}", response_model=SecretValue, summary="Get secret value")
async def get_secret(
    name: str,
    decode_base64: bool = Query(default=False),
    user: UserContext = Depends(require_role(UserRole.READ)),
) -> SecretValue:
    """Get a secret value (Read role required). Optionally decode Base64."""
    from azure.keyvault.secrets import SecretClient

    from app.core.azure_auth import get_azure_credential

    client = SecretClient(vault_url=settings.KEYVAULT_URL, credential=get_azure_credential())

    try:
        secret = client.get_secret(name)
    except Exception as e:
        raise HTTPException(status_code=404, detail=f"Secret '{name}' not found") from e
    finally:
        client.close()

    value = secret.value or ""
    decoded = None
    is_b64 = False

    if decode_base64:
        try:
            decoded = base64.b64decode(value).decode("utf-8")
            is_b64 = True
        except Exception:
            decoded = None

    return SecretValue(
        name=name,
        value=value,
        is_base64=is_b64,
        decoded_value=decoded,
    )


@router.post("/secrets", response_model=SecretInfo, summary="Create/update a secret")
async def create_secret(
    request: CreateSecretRequest,
    user: UserContext = Depends(require_role(UserRole.ADMIN)),
) -> SecretInfo:
    """Create or update a secret in Key Vault (Admin only)."""
    from azure.keyvault.secrets import SecretClient

    from app.core.azure_auth import get_azure_credential

    client = SecretClient(vault_url=settings.KEYVAULT_URL, credential=get_azure_credential())

    value = request.value
    if request.encode_base64:
        value = base64.b64encode(value.encode("utf-8")).decode("utf-8")

    try:
        secret = client.set_secret(
            name=request.name,
            value=value,
            content_type=request.content_type,
            tags=request.tags,
        )
    finally:
        client.close()

    return SecretInfo(
        name=secret.name,
        vault_url=settings.KEYVAULT_URL,
        content_type=secret.properties.content_type,
        enabled=(secret.properties.enabled if secret.properties.enabled is not None else True),
        tags=secret.properties.tags or {},
    )


@router.post("/base64", summary="Base64 encode/decode utility")
async def base64_tool(
    request: Base64Request,
    user: UserContext = Depends(get_current_user),
) -> dict[str, str]:
    """Utility: Base64 encode or decode a string."""
    if request.operation == "encode":
        result = base64.b64encode(request.value.encode("utf-8")).decode("utf-8")
    elif request.operation == "decode":
        try:
            result = base64.b64decode(request.value).decode("utf-8")
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Invalid Base64: {e}") from e
    else:
        raise HTTPException(status_code=400, detail="Operation must be 'encode' or 'decode'")

    return {"input": request.value, "operation": request.operation, "result": result}


class KeyVaultOpsPlugin(PluginBase):
    """Key Vault operations plugin."""

    def get_metadata(self) -> PluginMetadata:
        return PluginMetadata(
            name="Key Vault Operations",
            version="1.0.0",
            description="Azure Key Vault secret management — search, add, view, Base64 encode/decode",
            required_roles=["read"],
            dashboard_widgets=[
                {"id": "kv-secret-count", "title": "Secrets", "type": "metric"},
                {
                    "id": "kv-expiring-secrets",
                    "title": "Expiring Secrets",
                    "type": "alert",
                },
            ],
        )

    def get_router(self) -> APIRouter:
        return router


def create_plugin() -> PluginBase:
    """Plugin factory function."""
    return KeyVaultOpsPlugin()
