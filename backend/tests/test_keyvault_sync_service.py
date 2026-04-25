from datetime import datetime
from typing import Any, cast

import pytest

from app.services.keyvault_sync_service import KeyVaultSyncService


class _FakeExecuteResult:
    def __init__(self, value: Any):
        self._value = value

    def scalar_one_or_none(self):
        return self._value

    def scalars(self):
        return self

    def all(self):
        if self._value is None:
            return []
        if isinstance(self._value, list):
            return self._value
        return [self._value]


class _FakeVaultRow:
    def __init__(self):
        self.name = "sample-kv"
        self.secrets_count = 5
        self.keys_count = 2
        self.certificates_count = 1
        self.synced_at = None


class _FakeDB:
    def __init__(self, row: Any):
        self._row = row
        self.commit_count = 0
        self.added: list[Any] = []

    async def execute(self, statement):
        return _FakeExecuteResult(self._row)

    async def commit(self):
        self.commit_count += 1

    async def delete(self, value: Any):
        return None

    def add(self, value: Any):
        self.added.append(value)

    async def refresh(self, value: Any):
        if getattr(value, "id", None) is None:
            value.id = 1


def _as_service(value: Any) -> Any:
    return cast(Any, value)


@pytest.mark.anyio
async def test_sync_vault_preserves_failed_item_types(monkeypatch) -> None:
    row = _FakeVaultRow()
    service = KeyVaultSyncService(cast(Any, _FakeDB(row)))

    async def fail_secrets(vault_uri: str, *, refresh: bool = False):
        raise RuntimeError("vault unavailable")

    async def ok_keys(vault_uri: str, *, refresh: bool = False):
        return [{"name": "signing-key"}]

    async def ok_certs(vault_uri: str, *, refresh: bool = False):
        return []

    async def fake_upsert(db, vault_row, secrets, keys, certs):
        assert secrets is None
        assert keys == [{"name": "signing-key"}]
        assert certs == []
        return {"secrets": 5, "keys": 1, "certs": 0}

    monkeypatch.setattr(service.kv, "list_secrets", fail_secrets)
    monkeypatch.setattr(service.kv, "list_keys", ok_keys)
    monkeypatch.setattr(service.kv, "list_certificates", ok_certs)
    monkeypatch.setattr(service, "_upsert_vault_items_with_session", fake_upsert)

    result = await service.sync_vault("https://sample-kv.vault.azure.net/", triggered_by="manual")

    assert result["status"] == "partial"
    assert result["item_failures"] == ["secrets"]
    assert row.secrets_count == 5
    assert row.keys_count == 1
    assert row.certificates_count == 0
    assert isinstance(row.synced_at, datetime)


@pytest.mark.anyio
async def test_sync_vault_treats_certificate_only_failure_as_synced(monkeypatch) -> None:
    row = _FakeVaultRow()
    service = KeyVaultSyncService(cast(Any, _FakeDB(row)))

    async def ok_secrets(vault_uri: str, *, refresh: bool = False):
        return [{"name": "db-password"}]

    async def ok_keys(vault_uri: str, *, refresh: bool = False):
        return [{"name": "signing-key"}]

    async def fail_certs(vault_uri: str, *, refresh: bool = False):
        raise RuntimeError("certificates list forbidden")

    async def fake_upsert(db, vault_row, secrets, keys, certs):
        assert secrets == [{"name": "db-password"}]
        assert keys == [{"name": "signing-key"}]
        assert certs is None
        return {"secrets": 1, "keys": 1, "certs": 1}

    monkeypatch.setattr(service.kv, "list_secrets", ok_secrets)
    monkeypatch.setattr(service.kv, "list_keys", ok_keys)
    monkeypatch.setattr(service.kv, "list_certificates", fail_certs)
    monkeypatch.setattr(service, "_upsert_vault_items_with_session", fake_upsert)

    result = await service.sync_vault("https://sample-kv.vault.azure.net/", triggered_by="manual")

    assert result["status"] == "synced"
    assert result["item_failures"] == ["certs"]
    assert row.secrets_count == 1
    assert row.keys_count == 1
    assert row.certificates_count == 1
    assert isinstance(row.synced_at, datetime)


@pytest.mark.anyio
async def test_full_sync_treats_certificate_only_failures_as_completed(monkeypatch) -> None:
    db = _FakeDB(None)
    service = KeyVaultSyncService(cast(Any, db))

    async def fake_list_vaults(*, refresh: bool = False):
        return [{"name": "sample-kv", "vault_uri": "https://sample-kv.vault.azure.net/"}]

    async def fake_sync_vault_isolated(vault: dict):
        return {"secrets": 3, "keys": 2, "certs": 1, "item_failures": ["certs"]}

    monkeypatch.setattr(service.kv, "list_vaults", fake_list_vaults)
    monkeypatch.setattr(service, "_sync_vault_isolated", fake_sync_vault_isolated)

    result = await service.full_sync(triggered_by="manual")

    assert result["status"] == "completed"
    assert result["vaults_preserved"] == 0
    assert result["certificate_access_limited"] == 1

    sync_record = db.added[0]
    assert sync_record.status == "completed"
    assert sync_record.error_message is None
