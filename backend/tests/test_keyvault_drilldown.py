"""Key Vault drill-down: vault detail, item versions, AKS references, audited
secret reads, expiry rows, the vault_uri guard, and tag-preserving expiry fixes."""

import json
from datetime import datetime, timedelta
from types import SimpleNamespace
from typing import Any, cast

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app.api.v1.endpoints import keyvault
from app.models.auth import UserContext, UserRole
from app.services import keyvault_service
from app.services.keyvault_service import KeyVaultService, expiry_counts, expiry_entry, summarize_vault_resource

VAULT_URI = "https://kv-attcc-prod.vault.azure.net/"


def _user() -> UserContext:
    return UserContext(
        user_id="user-1",
        object_id="object-1",
        display_name="Portal User",
        email="user@example.com",
        roles=[UserRole.WRITE],
        raw_roles=["write"],
        tenant_id="tenant-1",
        allowed_subscriptions=[],
    )


def _any(value: Any) -> Any:
    return cast(Any, value)


class _AuditRecordingDB:
    def __init__(self, rows: list[Any] | None = None):
        self.added: list[Any] = []
        self.rows = rows or []

    def add(self, obj: Any) -> None:
        self.added.append(obj)

    async def commit(self) -> None:
        pass

    async def rollback(self) -> None:
        pass

    async def execute(self, _statement):
        rows = self.rows
        return SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: rows))


def _request(method: str, query: str = "", body: Any = None) -> Request:
    raw = json.dumps(body).encode() if body is not None else b""
    headers = [(b"content-type", b"application/json")] if body is not None else []

    async def receive():
        return {"type": "http.request", "body": raw, "more_body": False}

    return Request(
        {"type": "http", "method": method, "path": "/", "query_string": query.encode(), "headers": headers},
        receive,
    )


# ── vault_uri guard ───────────────────────────────────────────────────


@pytest.mark.anyio
async def test_vault_uri_guard_accepts_key_vault_endpoints() -> None:
    await keyvault.require_azure_vault_uris(_request("GET", f"vault_uri={VAULT_URI}"))
    await keyvault.require_azure_vault_uris(_request("GET", "vault_uri=https://KV-X.vault.azure.net"))
    await keyvault.require_azure_vault_uris(_request("POST", body={"secrets": [{"vault_uri": VAULT_URI}]}))


@pytest.mark.anyio
@pytest.mark.parametrize(
    "uri",
    [
        "https://kv-attcc-prod.attacker.example/",
        "https://kv-attcc-prod.vault.azure.net.attacker.example/",
        "http://kv-attcc-prod.vault.azure.net/",
        "https://kv-attcc-prod.vault.azure.net/secrets/x",
    ],
)
async def test_vault_uri_guard_rejects_other_hosts_in_query(uri: str) -> None:
    """The vault bearer token must never be sent to a host that only looks like a vault."""
    with pytest.raises(HTTPException) as exc:
        await keyvault.require_azure_vault_uris(_request("GET", f"vault_uri={uri}"))
    assert exc.value.status_code == 400


@pytest.mark.anyio
async def test_vault_uri_guard_rejects_nested_body_uris() -> None:
    body = {"secrets": [{"vault_uri": VAULT_URI}, {"vault_uri": "https://kv-x.evil.example/"}]}
    with pytest.raises(HTTPException) as exc:
        await keyvault.require_azure_vault_uris(_request("POST", body=body))
    assert exc.value.status_code == 400


# ── Expiry rows ───────────────────────────────────────────────────────


def _iso(days: float) -> str:
    return (datetime.utcnow() + timedelta(days=days)).isoformat()


def test_expiry_entry_skips_certificate_backing_items() -> None:
    """A certificate's secret and key expire with it; listing them triple-counts one certificate."""
    assert expiry_entry("web-cert", "kv", "secret", _iso(3), enabled=True, managed=True) is None
    assert expiry_entry("web-cert", "kv", "certificate", _iso(3), enabled=True)["days_remaining"] in (2, 3)


def test_expiry_entry_keeps_enabled_expired_items_only() -> None:
    expired = expiry_entry("db-password", "kv", "secret", _iso(-5), enabled=True)
    assert expired is not None and expired["days_remaining"] < 0
    assert expiry_entry("old-password", "kv", "secret", _iso(-5), enabled=False) is None
    assert expiry_entry("far-away", "kv", "secret", _iso(400), enabled=True) is None
    assert expiry_entry("no-expiry", "kv", "secret", None, enabled=True) is None


def test_expiry_counts_exclude_expired_items_from_expiring_windows() -> None:
    items = [{"days_remaining": d} for d in (-3, -1, 0, 12, 45, 200)]
    assert expiry_counts(items) == {
        "expired_count": 2,
        "expiring_within_30_days": 2,
        "expiring_within_90_days": 3,
        "expiring_within_360_days": 4,
    }


# ── Expiry fix keeps tags ─────────────────────────────────────────────


class _ExtendService:
    def __init__(self, current: dict):
        self.current = current
        self.written: dict | None = None

    async def get_secret_value(self, vault_uri: str, name: str, version: str | None = None) -> dict:
        return {"name": name, **self.current}

    async def create_or_update_secret(self, **kwargs) -> dict:
        self.written = kwargs
        return {"name": kwargs["name"], "id": "new-id"}


class _NoopSync:
    async def sync_vault(self, vault_uri: str, triggered_by: str = "mutation"):
        return None


class _BackgroundTasks:
    def add_task(self, *args, **kwargs) -> None:
        pass


@pytest.mark.anyio
async def test_extend_expiry_keeps_tags_status_and_content_type() -> None:
    """A new version carries only the tags sent with it — the fix used to drop them all."""
    service = _ExtendService(
        {
            "value": "s3cret",
            "content_type": "text/plain",
            "tags": {"owner": "attcc"},
            "enabled": False,
            "managed": False,
        }
    )
    await keyvault.extend_secret_expiry(
        request=keyvault.ExtendSecretExpiryRequest(vault_uri=VAULT_URI, name="db-password"),
        background_tasks=_any(_BackgroundTasks()),
        http_request=_any(None),
        user=_user(),
        service=_any(service),
        sync_service=_any(_NoopSync()),
        db=_any(_AuditRecordingDB()),
    )
    assert service.written is not None
    assert service.written["tags"] == {"owner": "attcc"}
    assert service.written["enabled"] is False
    assert service.written["content_type"] == "text/plain"
    assert service.written["value"] == "s3cret"


@pytest.mark.anyio
async def test_extend_expiry_refuses_certificate_backing_secret() -> None:
    service = _ExtendService(
        {"value": "pfx", "managed": True, "kid": "https://kv.vault.azure.net/keys/web-cert/abc", "tags": {}}
    )
    with pytest.raises(HTTPException) as exc:
        await keyvault.extend_secret_expiry(
            request=keyvault.ExtendSecretExpiryRequest(vault_uri=VAULT_URI, name="web-cert"),
            background_tasks=_any(_BackgroundTasks()),
            http_request=_any(None),
            user=_user(),
            service=_any(service),
            sync_service=_any(_NoopSync()),
            db=_any(_AuditRecordingDB()),
        )
    assert exc.value.status_code == 400
    assert "web-cert" in exc.value.detail
    assert service.written is None


@pytest.mark.anyio
async def test_bulk_extend_reports_certificate_backing_secret_by_name() -> None:
    service = _ExtendService({"value": "pfx", "managed": True, "kid": "https://kv.vault.azure.net/keys/web-cert/abc"})
    result = await keyvault.bulk_extend_secret_expiry(
        request=keyvault.BulkExtendSecretExpiryRequest(
            secrets=[keyvault.ExtendSecretExpiryRequest(vault_uri=VAULT_URI, name="web-cert")]
        ),
        background_tasks=_any(_BackgroundTasks()),
        http_request=_any(None),
        user=_user(),
        service=_any(service),
        sync_service=_any(_NoopSync()),
        db=_any(_AuditRecordingDB()),
    )
    assert result["failed_count"] == 1
    assert "Renew the certificate" in result["results"][0]["error"]


# ── Audited secret reads ──────────────────────────────────────────────


class _SecretReadService:
    def __init__(self):
        self.calls: list[tuple] = []

    async def get_secret_value(self, vault_uri: str, name: str, version: str | None = None) -> dict:
        self.calls.append((vault_uri, name, version))
        return {"name": name, "value": "x", "version": version or "current123"}


@pytest.mark.anyio
async def test_get_secret_reads_a_version_and_audits_the_read() -> None:
    service = _SecretReadService()
    db = _AuditRecordingDB()
    result = await keyvault.get_secret(
        name="db-password",
        http_request=_any(None),
        vault_uri="https://kv-attcc-prod.vault.azure.net",
        version="abc123",
        user=_user(),
        service=_any(service),
        db=_any(db),
    )
    assert result["version"] == "abc123"
    assert service.calls == [(VAULT_URI, "db-password", "abc123")]
    assert [a.action for a in db.added] == ["view_secret_value"]
    assert db.added[0].details["version"] == "abc123"
    assert db.added[0].details["vault_uri"] == VAULT_URI


@pytest.mark.anyio
async def test_get_secret_rejects_names_that_would_change_the_url() -> None:
    with pytest.raises(HTTPException) as exc:
        await keyvault.get_secret(
            name="x?api-version=1",
            http_request=_any(None),
            vault_uri=VAULT_URI,
            version=None,
            user=_user(),
            service=_any(_SecretReadService()),
            db=_any(_AuditRecordingDB()),
        )
    assert exc.value.status_code == 400


# ── Versions ──────────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_list_item_versions_pages_and_marks_the_newest_current(monkeypatch) -> None:
    pages = {
        f"{VAULT_URI}certificates/web-cert/versions?api-version=7.4&maxresults=25": {
            "value": [{"id": f"{VAULT_URI}certificates/web-cert/old1", "x5t": "q80", "attributes": {"created": 1000}}],
            "nextLink": "page-2",
        },
        "page-2": {"value": [{"id": f"{VAULT_URI}certificates/web-cert/new2", "attributes": {"created": 2000}}]},
    }
    service = KeyVaultService()

    async def fake_token() -> str:
        return "token"

    async def fake_get(url: str, *, token: str | None = None) -> dict:
        return pages[url]

    monkeypatch.setattr(service, "_get_vault_token", fake_token)
    monkeypatch.setattr(service, "_vault_get", fake_get)

    versions = await service.list_item_versions(VAULT_URI, "certificates", "web-cert")

    assert [v["version"] for v in versions] == ["new2", "old1"]
    assert [v["is_current"] for v in versions] == [True, False]
    assert versions[1]["thumbprint"] == "ABCD"


@pytest.mark.anyio
async def test_versions_endpoint_rejects_invalid_names() -> None:
    with pytest.raises(HTTPException) as exc:
        await keyvault.list_item_versions(
            item_type="secrets", name="../keys", vault_uri=VAULT_URI, user=_user(), service=_any(None)
        )
    assert exc.value.status_code == 400


# ── Vault detail ──────────────────────────────────────────────────────


RESOURCE_ID = "/subscriptions/sub-1/resourceGroups/rg-kv/providers/Microsoft.KeyVault/vaults/kv-attcc-prod"


class _VaultSync:
    def __init__(self, vault: dict | None):
        self.vault = vault

    async def get_vault_from_db(self, vault_uri: str) -> dict | None:
        return self.vault


class _VaultService:
    def __init__(self, arm: dict | Exception, live: list[dict] | None = None):
        self.arm = arm
        self.live = live or []
        self.requested: str | None = None

    async def get_vault_resource(self, resource_id: str) -> dict:
        self.requested = resource_id
        if isinstance(self.arm, Exception):
            raise self.arm
        return self.arm

    async def list_vaults(self, *, refresh: bool = False) -> list[dict]:
        return self.live


@pytest.mark.anyio
async def test_vault_detail_reads_arm_by_the_inventory_resource_id() -> None:
    arm = {"properties": {"enableRbacAuthorization": True, "publicNetworkAccess": "Disabled"}}
    service = _VaultService(arm)
    payload = await keyvault.get_vault_detail(
        vault_uri=VAULT_URI,
        user=_user(),
        service=_any(service),
        sync_service=_any(_VaultSync({"name": "kv-attcc-prod", "id": RESOURCE_ID})),
    )
    assert service.requested == RESOURCE_ID
    assert payload["properties"]["rbac_enabled"] is True
    assert payload["properties"]["public_network_access"] == "Disabled"
    assert payload["arm_error"] is None


@pytest.mark.anyio
async def test_vault_detail_keeps_the_synced_record_when_arm_fails() -> None:
    payload = await keyvault.get_vault_detail(
        vault_uri=VAULT_URI,
        user=_user(),
        service=_any(_VaultService(RuntimeError("HTTP Error 403: Forbidden"))),
        sync_service=_any(_VaultSync({"name": "kv-attcc-prod", "id": RESOURCE_ID})),
    )
    assert payload["vault"]["name"] == "kv-attcc-prod"
    assert payload["properties"] is None
    assert "Access denied" in payload["arm_error"]


@pytest.mark.anyio
async def test_vault_detail_404s_for_vaults_outside_the_inventory() -> None:
    with pytest.raises(HTTPException) as exc:
        await keyvault.get_vault_detail(
            vault_uri=VAULT_URI,
            user=_user(),
            service=_any(_VaultService({}, live=[{"vault_uri": "https://other.vault.azure.net/"}])),
            sync_service=_any(_VaultSync(None)),
        )
    assert exc.value.status_code == 404


def test_summarize_vault_resource_flattens_network_and_policies() -> None:
    summary = summarize_vault_resource(
        {
            "properties": {
                "softDeleteRetentionInDays": 90,
                "networkAcls": {
                    "defaultAction": "Deny",
                    "bypass": "AzureServices",
                    "ipRules": [{"value": "1.2.3.4/32"}],
                },
                "privateEndpointConnections": [
                    {
                        "properties": {
                            "privateEndpoint": {
                                "id": "/subscriptions/s/providers/Microsoft.Network/privateEndpoints/pe-kv"
                            },
                            "privateLinkServiceConnectionState": {"status": "Approved"},
                        }
                    }
                ],
                "accessPolicies": [{"objectId": "obj-1", "permissions": {"secrets": ["get", "list"]}}],
            },
            "systemData": {"createdBy": "someone@example.com"},
        }
    )
    assert summary["network_default_action"] == "Deny"
    assert summary["ip_rules"] == ["1.2.3.4/32"]
    assert summary["private_endpoints"][0]["name"] == "pe-kv"
    assert summary["private_endpoints"][0]["status"] == "Approved"
    assert summary["access_policies"][0]["secrets"] == ["get", "list"]
    assert summary["soft_delete_retention_days"] == 90
    assert summary["created_by"] == "someone@example.com"


# ── AKS references ────────────────────────────────────────────────────


def _akvs_row(object_type: str, name: str = "db-password") -> Any:
    cluster_id = (
        "/subscriptions/sub-1/resourceGroups/rg-aks/providers/Microsoft.ContainerService/managedClusters/aks-prod"
    )
    return SimpleNamespace(
        resource_id=f"{cluster_id}/akvs/apps/{name}",
        resource_group="rg-aks",
        subscription_id="sub-1",
        last_sync=datetime(2026, 10, 4, 12, 0, 0),
        resource_details={
            "_cluster_id": cluster_id,
            "namespace": "apps",
            "name": name,
            "vault_name": "kv-attcc-prod",
            "object_name": name,
            "object_type": object_type,
            "output_kind": "secret",
            "output_name": "db-credentials",
            "status": "Synced",
        },
    )


@pytest.mark.anyio
async def test_aks_references_name_the_cluster_and_filter_by_object_kind() -> None:
    db = _AuditRecordingDB(rows=[_akvs_row("multi-key-value-secret"), _akvs_row("certificate", "web-cert")])
    payload = await keyvault.list_aks_references(
        vault_uri=VAULT_URI, name=None, object_type="secret", user=_user(), db=_any(db)
    )
    assert payload["count"] == 1
    ref = payload["references"][0]
    assert ref["cluster_name"] == "aks-prod"
    assert ref["object_kind"] == "secret"
    assert ref["output_name"] == "db-credentials"
    assert ref["inventory_synced_at"] == "2026-10-04T12:00:00"


def test_x5t_to_hex() -> None:
    assert keyvault_service._x5t_to_hex("q80") == "ABCD"
    assert keyvault_service._x5t_to_hex(None) == ""
