from datetime import UTC, datetime, timedelta
from typing import Any, cast

import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.endpoints import keyvault
from app.models.auth import UserContext, UserRole
from app.models.database import AuditLog


class _FakeScalarResult:
    def __init__(self, items):
        self._items = items

    def all(self):
        return self._items


class _FakeResult:
    def __init__(self, items):
        self._items = items

    def scalars(self):
        return _FakeScalarResult(self._items)


class _FakeSession:
    def __init__(self, items):
        self._items = items
        self.statement = None

    async def execute(self, statement):
        self.statement = statement
        return _FakeResult(self._items)


class _FailingSyncService:
    async def get_dashboard_from_db(self):
        raise RuntimeError("db unavailable")

    async def get_vaults_from_db(self):
        raise RuntimeError("db unavailable")

    async def get_secrets_from_db(self, vault_uri: str, search: str | None = None):
        raise RuntimeError("db unavailable")


class _DashboardService:
    async def get_dashboard_summary(self, *, refresh: bool = False):
        return {
            "total_vaults": 0,
            "total_secrets": 0,
            "total_keys": 0,
            "total_certificates": 0,
            "expiring_within_30_days": 0,
            "expiring_within_90_days": 0,
            "expiring_items": [],
            "vault_summaries": [],
            "generated_at": "2026-04-05T00:00:00",
            "source": "azure_api",
        }


class _VaultListService:
    async def list_vaults(self, *, refresh: bool = False):
        return []


class _LiveSecretsService:
    async def list_secrets(self, vault_uri: str, search: str | None = None, *, refresh: bool = False):
        return [{"name": "db-password", "id": "secret-id"}]


class _ZeroedDashboardSyncService:
    async def get_dashboard_from_db(self):
        return {
            "total_vaults": 1,
            "total_secrets": 0,
            "total_keys": 0,
            "total_certificates": 0,
            "expiring_within_30_days": 0,
            "expiring_within_90_days": 0,
            "expiring_items": [],
            "vault_summaries": [
                {
                    "name": "sample-kv",
                    "location": "eastus2",
                    "subscription_id": "sub-1",
                    "secrets_count": 0,
                    "keys_count": 0,
                    "certificates_count": 0,
                    "soft_delete": True,
                    "purge_protection": True,
                    "rbac_enabled": True,
                }
            ],
            "generated_at": "2026-04-10T00:00:00",
            "source": "database",
        }


class _EmptySecretsSyncService:
    async def get_secrets_from_db(self, vault_uri: str, search: str | None = None):
        return []


class _FailingDashboardService:
    async def get_dashboard_summary(self, *, refresh: bool = False):
        raise RuntimeError("ForbiddenByConnection")


class _FailingVaultListService:
    async def list_vaults(self, *, refresh: bool = False):
        raise RuntimeError("ForbiddenByConnection")


class _RecoveredDashboardService:
    async def get_dashboard_summary(self, *, refresh: bool = False):
        return {
            "total_vaults": 1,
            "total_secrets": 4,
            "total_keys": 2,
            "total_certificates": 1,
            "expiring_within_30_days": 0,
            "expiring_within_90_days": 0,
            "expiring_items": [],
            "vault_summaries": [],
            "generated_at": "2026-04-10T00:00:01",
            "source": "azure_api",
        }


def _as_async_session(value: Any) -> AsyncSession:
    return cast(AsyncSession, value)


def _as_service(value: Any):
    return cast(Any, value)


def _as_sync_service(value: Any):
    return cast(Any, value)


def _user() -> UserContext:
    return UserContext(
        user_id="user-1",
        object_id="object-1",
        display_name="Portal User",
        email="user@example.com",
        roles=[UserRole.ADMIN],
        raw_roles=["admin"],
        tenant_id="tenant-1",
        allowed_subscriptions=[],
    )


def test_serialize_audit_entry_uses_structured_details() -> None:
    entry = AuditLog(
        id=7,
        timestamp=datetime(2026, 3, 17, 12, 30, 0),
        user_id="user-1",
        user_email="user@example.com",
        action="update_secret",
        resource_type="secret",
        resource_id="db-password",
        status="success",
        details={
            "vault_uri": "https://sample-kv.vault.azure.net/",
            "vault_name": "sample-kv",
            "resource_type": "secret",
            "resource_name": "db-password",
            "summary": "Updated secret db-password",
        },
    )

    data = keyvault._serialize_audit_entry(entry)

    assert data["vault_name"] == "sample-kv"
    assert data["resource_name"] == "db-password"
    assert data["summary"] == "Updated secret db-password"
    assert data["timestamp"] == "2026-03-17T12:30:00"


@pytest.mark.anyio
async def test_get_audit_history_returns_serialized_entries() -> None:
    entry = AuditLog(
        id=11,
        timestamp=datetime.now(UTC).replace(tzinfo=None) - timedelta(hours=1),
        user_id="user-1",
        user_email="user@example.com",
        action="delete_key",
        resource_type="key",
        resource_id="signing-key",
        status="failed",
        details={
            "vault_uri": "https://sample-kv.vault.azure.net/",
            "vault_name": "sample-kv",
            "resource_type": "key",
            "resource_name": "signing-key",
            "summary": "Deleted key signing-key",
            "error": "Forbidden",
        },
    )
    db = _FakeSession([entry])

    payload = await keyvault.get_audit_history(
        vault_uri="https://sample-kv.vault.azure.net/",
        days=30,
        limit=50,
        user=_user(),
        db=_as_async_session(db),
    )

    assert payload["count"] == 1
    assert payload["history"][0]["action"] == "delete_key"
    assert payload["history"][0]["status"] == "failed"
    assert payload["history"][0]["details"]["error"] == "Forbidden"
    assert db.statement is not None


@pytest.mark.anyio
async def test_keyvault_dashboard_falls_back_when_db_cache_fails() -> None:
    payload = await keyvault.keyvault_dashboard(
        refresh=False,
        user=_user(),
        service=_as_service(_DashboardService()),
        sync_service=_as_sync_service(_FailingSyncService()),
    )

    assert payload["source"] == "azure_api"
    assert payload["total_vaults"] == 0


@pytest.mark.anyio
async def test_list_vaults_falls_back_when_db_cache_fails() -> None:
    payload = await keyvault.list_vaults(
        refresh=False,
        user=_user(),
        service=_as_service(_VaultListService()),
        sync_service=_as_sync_service(_FailingSyncService()),
    )

    assert payload == []


@pytest.mark.anyio
async def test_keyvault_dashboard_recovers_from_zeroed_db_cache() -> None:
    payload = await keyvault.keyvault_dashboard(
        refresh=False,
        user=_user(),
        service=_as_service(_RecoveredDashboardService()),
        sync_service=_as_sync_service(_ZeroedDashboardSyncService()),
    )

    assert payload["source"] == "azure_api"
    assert payload["total_secrets"] == 4


@pytest.mark.anyio
async def test_list_secrets_falls_back_to_live_when_db_cache_is_empty() -> None:
    payload = await keyvault.list_secrets(
        vault_uri="https://sample-kv.vault.azure.net/",
        search=None,
        refresh=False,
        user=_user(),
        service=_as_service(_LiveSecretsService()),
        sync_service=_as_sync_service(_EmptySecretsSyncService()),
    )

    assert payload == [{"name": "db-password", "id": "secret-id"}]


@pytest.mark.anyio
async def test_keyvault_dashboard_returns_502_when_fallback_fails() -> None:
    with pytest.raises(HTTPException) as exc_info:
        await keyvault.keyvault_dashboard(
            refresh=False,
            user=_user(),
            service=_as_service(_FailingDashboardService()),
            sync_service=_as_sync_service(_FailingSyncService()),
        )

    assert exc_info.value.status_code == 502
    assert "Cannot load Key Vault dashboard" in exc_info.value.detail


@pytest.mark.anyio
async def test_list_vaults_returns_502_when_fallback_fails() -> None:
    with pytest.raises(HTTPException) as exc_info:
        await keyvault.list_vaults(
            refresh=False,
            user=_user(),
            service=_as_service(_FailingVaultListService()),
            sync_service=_as_sync_service(_FailingSyncService()),
        )

    assert exc_info.value.status_code == 502
    assert "Cannot load Key Vault vaults" in exc_info.value.detail
