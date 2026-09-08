"""Integration tests for the certificate management API endpoints.

The CertificateService is replaced with an in-memory fake via dependency
override. Covers success, validation failure, upstream auth (401), not-found
(404), and server-error (5xx) paths, plus RBAC gating for destructive actions.
"""

import pytest

from app.api.v1.endpoints.certificates import _filter_enabled_collections, _get_service
from app.core.config import settings
from app.services.keyfactor_service import CertificateServiceError
from tests.jks_reader import load_jks

CERT = {
    "id": 1,
    "common_name": "a.example.com",
    "subject_dn": "CN=a.example.com",
    "issuer_dn": "CN=Test CA",
    "serial_number": "01",
    "thumbprint": "ABC",
    "template": "WebServer",
    "certificate_authority": "ca",
    "not_before": "2026-01-01T00:00:00+00:00",
    "not_after": "2027-01-01T00:00:00+00:00",
    "sans": ["a.example.com"],
    "revoked": False,
    "revocation_reason": None,
    "status": "valid",
    "metadata": {},
}


class FakeService:
    """Configurable fake — set ``error`` to make every call raise it."""

    def __init__(self, error: CertificateServiceError | None = None):
        self.error = error
        self.last_query: str | None = None
        self.last_collection_id: int | None = None
        self.last_renew_kwargs: dict | None = None
        self.last_revoke_kwargs: dict | None = None
        # bytes, or a callable(kwargs) -> bytes for formats that depend on the
        # password the endpoint sends (Keyfactor encrypts the PFX with it).
        self.download_payload: bytes | None = None
        self.last_download_kwargs: dict | None = None
        self.download_calls: list[dict] = []
        self.renew_result: dict | None = None

    def _maybe_raise(self):
        if self.error:
            raise self.error

    async def list_certificates(self, *, query, page, page_size, collection_id=None):
        self._maybe_raise()
        self.last_query = query
        self.last_collection_id = collection_id
        return {"items": [{**CERT}], "total": 1, "page": page, "page_size": page_size}

    async def get_certificate(self, certificate_id):
        self._maybe_raise()
        return {**CERT, "id": certificate_id}

    async def enroll_csr(self, **kwargs):
        self._maybe_raise()
        return {"thumbprint": "ABC", "serial_number": "01", "certificate_id": 1}

    async def enroll_pfx(self, **kwargs):
        self._maybe_raise()
        return {"thumbprint": "DEF", "pfx_base64": "BLOB", "certificate_id": 2}

    async def renew_certificate(self, **kwargs):
        self._maybe_raise()
        self.last_renew_kwargs = kwargs
        return self.renew_result if self.renew_result is not None else {"thumbprint": "NEW"}

    async def download_certificate(self, certificate_id, **kwargs):
        self._maybe_raise()
        self.last_download_kwargs = {"certificate_id": certificate_id, **kwargs}
        self.download_calls.append(self.last_download_kwargs)
        if callable(self.download_payload):
            return self.download_payload(self.last_download_kwargs)
        if self.download_payload is not None:
            return self.download_payload
        return b"CERTIFICATE"

    async def revoke_certificate(self, **kwargs):
        self._maybe_raise()
        from app.services.keyfactor_service import default_revocation_comment

        self.last_revoke_kwargs = kwargs
        comment = (kwargs.get("comment") or "").strip() or default_revocation_comment(
            kwargs["reason"], kwargs.get("actor")
        )
        return {
            "certificate_id": kwargs["certificate_id"],
            "reason": kwargs["reason"],
            "revoked": True,
            "comment": comment,
        }

    async def update_metadata(self, **kwargs):
        self._maybe_raise()
        return {"certificate_id": kwargs["certificate_id"], "updated_fields": list(kwargs["metadata"].keys())}

    async def delete_certificate(self, certificate_id, collection_id=None):
        self._maybe_raise()
        return {"certificate_id": certificate_id, "deleted": True}

    async def list_collections(self):
        self._maybe_raise()
        return [
            {"id": 1, "name": "AP-KF-ATTCC-31599", "description": "", "certificate_count": 27},
            {"id": 2, "name": "AP-KF-OTHER-1000", "description": "", "certificate_count": 5},
            {"id": 3, "name": "AP-KF-THIRD-2000", "description": "", "certificate_count": 0},
        ]


def _use_service(app, service: FakeService) -> None:
    app.dependency_overrides[_get_service] = lambda: service


# ── Enabled-collections filter ──────────────────────────────────


def test_filter_enabled_collections_include_all_bypasses_restriction() -> None:
    cols = [{"id": 1}, {"id": 2}, {"id": 3}]
    assert _filter_enabled_collections(cols, [1], include_all=True) == cols


def test_filter_enabled_collections_returns_all_when_unconfigured() -> None:
    cols = [{"id": 1}, {"id": 2}]
    assert _filter_enabled_collections(cols, None, include_all=False) == cols
    assert _filter_enabled_collections(cols, [], include_all=False) == cols


def test_filter_enabled_collections_restricts_to_enabled_ids() -> None:
    cols = [{"id": 1}, {"id": 2}, {"id": 3}]
    assert _filter_enabled_collections(cols, [1, 3], include_all=False) == [{"id": 1}, {"id": 3}]


async def test_list_collections_include_all_returns_full_list(app, admin_client):
    # The admin panel passes include_all=true and must see every collection so it
    # can enable/disable them — never just the already-enabled subset.
    _use_service(app, FakeService())
    resp = await admin_client.get("/api/v1/certificates/collections", params={"include_all": "true"})
    assert resp.status_code == 200
    assert [c["id"] for c in resp.json()] == [1, 2, 3]


async def test_list_collections_default_returns_all_when_no_admin_config(app, admin_client):
    _use_service(app, FakeService())
    resp = await admin_client.get("/api/v1/certificates/collections")
    assert resp.status_code == 200
    assert len(resp.json()) == 3


# ── Read paths ─────────────────────────────────────────────────────────


async def test_list_certificates_success(app, admin_client):
    _use_service(app, FakeService())
    resp = await admin_client.get("/api/v1/certificates")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1
    assert body["items"][0]["common_name"] == "a.example.com"


async def test_list_certificates_with_filters(app, admin_client):
    _use_service(app, FakeService())
    resp = await admin_client.get("/api/v1/certificates", params={"cn": "example", "page": 2})
    assert resp.status_code == 200


async def test_list_cert_status_maps_to_numeric_certstate(app, admin_client):
    # Keyfactor's CertState field is numeric; "Revoked" must become CertState -eq "2"
    # (a name would make Keyfactor return "Invalid CertState value: Revoked.").
    svc = FakeService()
    _use_service(app, svc)
    resp = await admin_client.get("/api/v1/certificates", params={"cert_status": "Revoked"})
    assert resp.status_code == 200
    assert svc.last_query == 'CertState -eq "2"'


async def test_list_cert_status_non_keyfactor_state_is_ignored(app, admin_client):
    # Date-derived statuses ("expired") aren't Keyfactor states → no CertState clause.
    svc = FakeService()
    _use_service(app, svc)
    resp = await admin_client.get("/api/v1/certificates", params={"cert_status": "expired"})
    assert resp.status_code == 200
    assert svc.last_query is None


async def test_get_certificate_success(app, admin_client):
    _use_service(app, FakeService())
    resp = await admin_client.get("/api/v1/certificates/7")
    assert resp.status_code == 200
    assert resp.json()["id"] == 7


async def test_get_certificate_not_found(app, admin_client):
    _use_service(app, FakeService(error=CertificateServiceError("missing", status_code=404)))
    resp = await admin_client.get("/api/v1/certificates/999")
    assert resp.status_code == 404


# ── Enroll ─────────────────────────────────────────────────────────────


async def test_enroll_csr_success(app, admin_client):
    _use_service(app, FakeService())
    resp = await admin_client.post(
        "/api/v1/certificates/enroll",
        json={
            "enrollment_type": "csr",
            "certificate_authority": "ca",
            "template": "WebServer",
            "csr": "-----BEGIN CERTIFICATE REQUEST-----",
        },
    )
    assert resp.status_code == 201
    assert resp.json()["thumbprint"] == "ABC"


async def test_enroll_csr_missing_csr_returns_422(app, admin_client):
    _use_service(app, FakeService())
    resp = await admin_client.post(
        "/api/v1/certificates/enroll",
        json={"enrollment_type": "csr", "certificate_authority": "ca", "template": "WebServer"},
    )
    assert resp.status_code == 422


async def test_enroll_invalid_type_returns_422(app, admin_client):
    _use_service(app, FakeService())
    resp = await admin_client.post(
        "/api/v1/certificates/enroll",
        json={"enrollment_type": "bogus", "certificate_authority": "ca", "template": "t"},
    )
    assert resp.status_code == 422


async def test_enroll_upstream_5xx_returns_502(app, admin_client):
    _use_service(app, FakeService(error=CertificateServiceError("boom", status_code=500)))
    resp = await admin_client.post(
        "/api/v1/certificates/enroll",
        json={
            "enrollment_type": "csr",
            "certificate_authority": "ca",
            "template": "WebServer",
            "csr": "x",
        },
    )
    assert resp.status_code == 502


async def test_enroll_upstream_auth_error_returns_502(app, admin_client):
    _use_service(app, FakeService(error=CertificateServiceError("auth failed", status_code=401)))
    resp = await admin_client.post(
        "/api/v1/certificates/enroll",
        json={
            "enrollment_type": "csr",
            "certificate_authority": "ca",
            "template": "WebServer",
            "csr": "x",
        },
    )
    assert resp.status_code == 502


# ── Renew / revoke / update / delete ───────────────────────────────────


async def test_renew_success(app, admin_client):
    _use_service(app, FakeService())
    resp = await admin_client.post("/api/v1/certificates/1/renew", json={})
    assert resp.status_code == 200
    assert resp.json()["thumbprint"] == "NEW"


async def test_renew_passes_collection_context(app, admin_client):
    svc = FakeService()
    _use_service(app, svc)
    resp = await admin_client.post("/api/v1/certificates/1/renew", json={"collection_id": 31599})
    assert resp.status_code == 200
    assert svc.last_renew_kwargs is not None
    assert svc.last_renew_kwargs["collection_id"] == 31599


async def test_pfx_renew_requires_non_blank_12_character_password(app, admin_client):
    svc = FakeService()
    _use_service(app, svc)
    resp = await admin_client.post(
        "/api/v1/certificates/1/renew",
        json={"mode": "pfx", "password": "            "},
    )
    assert resp.status_code == 422
    assert svc.last_renew_kwargs is None


async def test_pfx_renew_forwards_replacement_fields(app, admin_client):
    svc = FakeService()
    _use_service(app, svc)
    resp = await admin_client.post(
        "/api/v1/certificates/1/renew",
        json={
            "mode": "pfx",
            "password": "validpassword",
            "key_type": "RSA",
            "key_length": 4096,
            "owner_role_name": "Certificate Owners",
        },
    )
    assert resp.status_code == 200
    assert svc.last_renew_kwargs is not None
    assert svc.last_renew_kwargs["mode"] == "pfx"
    assert svc.last_renew_kwargs["password"] == "validpassword"
    assert svc.last_renew_kwargs["owner_role_name"] == "Certificate Owners"


async def test_download_passes_collection_context(app, admin_client):
    svc = FakeService()
    _use_service(app, svc)
    resp = await admin_client.post(
        "/api/v1/certificates/1/download",
        json={
            "file_format": "PEM",
            "include_chain": True,
            "chain_order": "EndEntityFirst",
            "include_subject_header": True,
            "collection_id": 31599,
        },
    )
    assert resp.status_code == 200
    assert svc.last_download_kwargs is not None
    assert svc.last_download_kwargs["collection_id"] == 31599


async def test_upstream_permission_error_is_actionable(app, admin_client):
    # A Keyfactor 403 (service account lacks a permission) must surface an
    # admin-actionable message, not a bare pass-through, while preserving the
    # upstream detail for troubleshooting.
    upstream = "User abc123 does not have the required permissions: /certificates/collections/read/."
    _use_service(app, FakeService(error=CertificateServiceError(upstream, status_code=403)))
    resp = await admin_client.post("/api/v1/certificates/1/renew", json={})
    assert resp.status_code == 502
    detail = resp.json()["detail"]
    assert "Keyfactor administrator" in detail
    assert "required permissions" in detail  # upstream detail preserved


async def test_renew_suspended_workflow_returns_conflict(app, admin_client):
    # A prior renewal left a suspended Keyfactor workflow; surface an actionable
    # 409 telling the user to resolve the pending renewal, preserving upstream detail.
    upstream = "A suspended workflow is already attempting to renew the certificate with id '23700244'."
    _use_service(app, FakeService(error=CertificateServiceError(upstream, status_code=400)))
    resp = await admin_client.post("/api/v1/certificates/1/renew", json={})
    assert resp.status_code == 409
    detail = resp.json()["detail"]
    assert "pending renewal" in detail
    assert "23700244" in detail  # upstream detail preserved


async def test_revoke_success(app, admin_client):
    _use_service(app, FakeService())
    resp = await admin_client.post("/api/v1/certificates/1/revoke", json={"reason": "keyCompromise", "comment": "leak"})
    assert resp.status_code == 200
    assert resp.json()["revoked"] is True


# ── Load to Azure Key Vault ────────────────────────────────────────────


class _FakeKeyVaultService:
    """Captures the arguments the endpoint passes to the AKV import call."""

    imports: list[dict] = []
    deletes: list[str] = []
    fail_names: set[str] = set()

    async def import_certificate(self, vault_uri, name, cert_bytes, *, password=None, **kwargs):
        if name in type(self).fail_names:
            raise RuntimeError(f"boom for {name}")
        type(self).imports.append(
            {
                "vault_uri": vault_uri,
                "name": name,
                "cert_bytes": cert_bytes,
                "password": password,
            }
        )
        return {"id": f"https://kv.vault.azure.net/certificates/{name}/1", "attributes": {"enabled": True}}

    async def delete_certificate(self, vault_uri, name):
        type(self).deletes.append(name)
        return {"deleted": True}


@pytest.fixture
def fake_keyvault(monkeypatch):
    _FakeKeyVaultService.imports = []
    _FakeKeyVaultService.deletes = []
    _FakeKeyVaultService.fail_names = set()
    monkeypatch.setattr("app.services.keyvault_service.KeyVaultService", _FakeKeyVaultService)
    return _FakeKeyVaultService


_AKV_TARGET = {
    "subscription_id": "sub-1",
    "resource_group": "rg-1",
    "vault_name": "my-vault",
    "certificate_names": ["a-example-com"],
}


async def test_load_to_akv_exports_pfx_when_no_data_supplied(app, admin_client, fake_keyvault):
    # AKV needs the private key, so omitting certificate_data must make the
    # portal export the PFX from Keyfactor instead of demanding a paste.
    svc = FakeService()
    _use_service(app, svc)
    resp = await admin_client.post(
        "/api/v1/certificates/1/load-to-akv",
        json={**_AKV_TARGET, "collection_id": 31599},
    )
    assert resp.status_code == 200
    assert svc.last_download_kwargs is not None
    assert svc.last_download_kwargs["file_format"] == "PFX"
    assert svc.last_download_kwargs["collection_id"] == 31599
    # The generated one-time password must protect the exported PFX on import.
    generated = svc.last_download_kwargs["pfx_password"]
    assert generated
    assert fake_keyvault.imports[0]["cert_bytes"] == b"CERTIFICATE"
    assert fake_keyvault.imports[0]["password"] == generated
    # Importing must never remove an existing AKV certificate — Key Vault versions it.
    assert fake_keyvault.deletes == []


async def test_load_to_akv_fans_out_to_every_named_entry(app, admin_client, fake_keyvault):
    # A multi-SAN certificate is stored under one AKV name per SAN, and the PFX can
    # only be exported once, so every entry must be imported from that one export.
    svc = FakeService()
    _use_service(app, svc)
    names = ["attccguiperf-test-att-com", "attccelk-test-att-com", "attccgrafana-test-att-com"]
    resp = await admin_client.post(
        "/api/v1/certificates/1/load-to-akv",
        json={**_AKV_TARGET, "certificate_names": names},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "success"
    assert [c["certificate_name"] for c in body["certificates"]] == names
    # One Keyfactor export shared by every import.
    assert len(svc.download_calls) == 1
    assert [i["name"] for i in fake_keyvault.imports] == names
    assert {i["password"] for i in fake_keyvault.imports} == {svc.last_download_kwargs["pfx_password"]}


async def test_load_to_akv_reports_partial_failures(app, admin_client, fake_keyvault):
    _use_service(app, FakeService())
    fake_keyvault.fail_names = {"b-name"}
    resp = await admin_client.post(
        "/api/v1/certificates/1/load-to-akv",
        json={**_AKV_TARGET, "certificate_names": ["a-name", "b-name"]},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "partial"
    assert [c["certificate_name"] for c in body["certificates"]] == ["a-name"]
    assert body["failed"][0]["certificate_name"] == "b-name"


async def test_load_to_akv_rejects_invalid_entry_name(app, admin_client, fake_keyvault):
    _use_service(app, FakeService())
    resp = await admin_client.post(
        "/api/v1/certificates/1/load-to-akv",
        json={**_AKV_TARGET, "certificate_names": ["bad name!"]},
    )
    assert resp.status_code == 422
    assert fake_keyvault.imports == []


async def test_load_to_akv_uses_supplied_certificate_data(app, admin_client, fake_keyvault):
    import base64

    svc = FakeService()
    _use_service(app, svc)
    resp = await admin_client.post(
        "/api/v1/certificates/1/load-to-akv",
        json={
            **_AKV_TARGET,
            "certificate_data": base64.b64encode(b"RENEWED-PFX").decode(),
            "certificate_password": "renewal-password",
        },
    )
    assert resp.status_code == 200
    assert svc.last_download_kwargs is None  # no Keyfactor export needed
    assert fake_keyvault.imports[0]["cert_bytes"] == b"RENEWED-PFX"
    assert fake_keyvault.imports[0]["password"] == "renewal-password"


async def test_load_to_akv_without_private_key_is_actionable(app, admin_client, fake_keyvault):
    # No exportable private key → tell the user to generate a new PFX certificate.
    _use_service(app, FakeService(error=CertificateServiceError("Private key is not available.", status_code=400)))
    resp = await admin_client.post("/api/v1/certificates/1/load-to-akv", json=_AKV_TARGET)
    assert resp.status_code == 409
    detail = resp.json()["detail"]
    assert "private key" in detail
    assert "generate a new certificate with pfx" in detail.lower()
    assert fake_keyvault.imports == []


async def test_load_to_akv_rejects_invalid_base64(app, admin_client, fake_keyvault):
    _use_service(app, FakeService())
    resp = await admin_client.post(
        "/api/v1/certificates/1/load-to-akv",
        json={**_AKV_TARGET, "certificate_data": "not base64!!"},
    )
    assert resp.status_code == 422
    assert fake_keyvault.imports == []


async def test_revoke_without_a_comment_succeeds(app, admin_client):
    # The field is labelled optional, so omitting it must not fail — Keyfactor
    # needs a non-empty comment, which the portal supplies on the caller's behalf.
    svc = FakeService()
    _use_service(app, svc)
    resp = await admin_client.post("/api/v1/certificates/1/revoke", json={"reason": "superseded"})
    assert resp.status_code == 200
    assert resp.json()["revoked"] is True
    assert svc.last_revoke_kwargs["comment"] == ""
    # The actor is passed through so the substituted comment names who did it.
    assert svc.last_revoke_kwargs["actor"] == "admin@example.com"
    assert resp.json()["comment"] == "Revoked via OpsPortal by admin@example.com (reason: superseded)"


async def test_revoke_audits_the_comment_keyfactor_received(app, admin_client, db_session):
    from sqlalchemy import select

    from app.models.database import AuditLog

    _use_service(app, FakeService())
    resp = await admin_client.post("/api/v1/certificates/1/revoke", json={"reason": "keyCompromise"})
    assert resp.status_code == 200

    entry = (
        (await db_session.execute(select(AuditLog).where(AuditLog.action == "revoke_certificate"))).scalars().all()[-1]
    )
    assert entry.details["comment_supplied"] is False
    assert "admin@example.com" in entry.details["comment"]


async def test_revoke_invalid_reason_returns_422(app, admin_client):
    _use_service(app, FakeService())
    resp = await admin_client.post("/api/v1/certificates/1/revoke", json={"reason": "nope"})
    assert resp.status_code == 422


async def test_update_metadata_success(app, admin_client):
    _use_service(app, FakeService())
    resp = await admin_client.put("/api/v1/certificates/1/metadata", json={"metadata": {"owner": "team-a"}})
    assert resp.status_code == 200
    assert "owner" in resp.json()["updated_fields"]


async def test_update_metadata_empty_returns_422(app, admin_client):
    _use_service(app, FakeService())
    resp = await admin_client.put("/api/v1/certificates/1/metadata", json={"metadata": {}})
    assert resp.status_code == 422


async def test_delete_success(app, admin_client):
    _use_service(app, FakeService())
    resp = await admin_client.delete("/api/v1/certificates/1")
    assert resp.status_code == 200
    assert resp.json()["deleted"] is True


# ── Auto-renewal manual run ─────────────────────────────────


async def test_run_auto_renewal_config_not_found(app, admin_client):
    resp = await admin_client.post("/api/v1/certificates/auto-renewal/configs/99999/run")
    assert resp.status_code == 404


async def test_run_auto_renewal_config_records_audit(app, admin_client):
    # Create a schedule, trigger it manually, and confirm the run is persisted.
    create = await admin_client.post(
        "/api/v1/certificates/auto-renewal/configs",
        json={"collection_id": 42, "collection_name": "AP-KF-ATTCC-31599", "days_before_expiry": 60},
    )
    assert create.status_code == 200
    config_id = create.json()["id"]

    run = await admin_client.post(f"/api/v1/certificates/auto-renewal/configs/{config_id}/run")
    assert run.status_code == 200
    body = run.json()
    assert body["status"] == "triggered"
    assert body["config_id"] == config_id
    assert body["collection_name"] == "AP-KF-ATTCC-31599"
    assert body["triggered_at"]

    # The schedule now reports a last-run timestamp.
    configs = await admin_client.get("/api/v1/certificates/auto-renewal/configs")
    assert configs.status_code == 200
    match = next(c for c in configs.json() if c["id"] == config_id)
    assert match["last_run_at"]

    # The trigger is captured in the certificate audit history.
    history = await admin_client.get("/api/v1/certificates/audit-history")
    assert history.status_code == 200
    actions = [e["action"] for e in history.json()["history"]]
    assert "cert_auto_renewal_run" in actions


# ── RBAC — destructive/sensitive actions blocked without permission ────


@pytest.fixture
def _enforce_rbac(monkeypatch):
    """Disable the local dev auth bypass so require_role is enforced."""
    monkeypatch.setattr(settings, "DEV_AUTH_BYPASS", False)


async def test_reader_can_list(app, reader_client, _enforce_rbac):
    _use_service(app, FakeService())
    resp = await reader_client.get("/api/v1/certificates")
    assert resp.status_code == 200


async def test_reader_cannot_enroll(app, reader_client, _enforce_rbac):
    _use_service(app, FakeService())
    resp = await reader_client.post(
        "/api/v1/certificates/enroll",
        json={"enrollment_type": "csr", "certificate_authority": "ca", "template": "t", "csr": "x"},
    )
    assert resp.status_code == 403


async def test_reader_cannot_revoke(app, reader_client, _enforce_rbac):
    _use_service(app, FakeService())
    resp = await reader_client.post("/api/v1/certificates/1/revoke", json={"reason": "keyCompromise"})
    assert resp.status_code == 403


async def test_reader_cannot_delete(app, reader_client, _enforce_rbac):
    _use_service(app, FakeService())
    resp = await reader_client.delete("/api/v1/certificates/1")
    assert resp.status_code == 403


async def test_reader_cannot_run_auto_renewal(app, reader_client, _enforce_rbac):
    resp = await reader_client.post("/api/v1/certificates/auto-renewal/configs/1/run")
    assert resp.status_code == 403


# ── Private-key escrow ─────────────────────────────────────────────────


class _FakeEscrowVault:
    """In-memory stand-in for the escrow Key Vault."""

    def __init__(self) -> None:
        self.secrets: dict[str, str] = {}

    async def create_or_update_secret(self, vault_uri, name, value, **kwargs):
        self.secrets[name] = value
        return {"name": name, "id": f"{vault_uri}secrets/{name}/1"}

    async def get_secret_value(self, vault_uri, name):
        if name not in self.secrets:
            raise RuntimeError("SecretNotFound")
        return {"name": name, "value": self.secrets[name]}

    async def delete_secret(self, vault_uri, name):
        self.secrets.pop(name, None)
        return {"deleted": True}


@pytest.fixture
def escrow_vault(monkeypatch):
    """Enable escrow and back it with an in-memory vault."""
    fake = _FakeEscrowVault()
    monkeypatch.setattr(settings, "CERT_KEY_ESCROW_ENABLED", True)
    monkeypatch.setattr(settings, "CERT_KEY_ESCROW_VAULT", "escrow-kv")
    monkeypatch.setattr(settings, "CERT_KEY_ESCROW_VAULT_URI", "")
    monkeypatch.setattr("app.services.certificate_escrow_service.KeyVaultService", lambda: fake)
    return fake


async def _seed_escrow(db_session, *, certificate_id: int, thumbprint: str, pfx: bytes, password: str):
    import base64

    from app.services.certificate_escrow_service import CertificateEscrowService

    pointer = await CertificateEscrowService(db_session).escrow(
        certificate_id=certificate_id,
        thumbprint=thumbprint,
        common_name="a.example.com",
        pfx_base64=base64.b64encode(pfx).decode(),
        password=password,
        source="renew",
        actor="admin@example.com",
    )
    assert pointer is not None
    return pointer


async def test_load_to_akv_prefers_the_escrowed_key(app, admin_client, db_session, fake_keyvault, escrow_vault):
    # The whole point of escrow: no live Keyfactor export is needed, so the same
    # certificate can still be loaded into a second environment's vault later.
    svc = FakeService()
    _use_service(app, svc)
    await _seed_escrow(db_session, certificate_id=1, thumbprint="ABC", pfx=b"ESCROWED-PFX", password="escrow-pw")

    resp = await admin_client.post("/api/v1/certificates/1/load-to-akv", json=_AKV_TARGET)

    assert resp.status_code == 200
    assert resp.json()["key_source"] == "escrow"
    assert svc.last_download_kwargs is None  # Keyfactor never contacted
    assert fake_keyvault.imports[0]["cert_bytes"] == b"ESCROWED-PFX"
    assert fake_keyvault.imports[0]["password"] == "escrow-pw"


async def test_load_to_akv_escrowed_key_serves_repeated_loads(
    app, admin_client, db_session, fake_keyvault, escrow_vault
):
    # A multi-env certificate is loaded one vault at a time; every load must work.
    _use_service(app, FakeService())
    await _seed_escrow(db_session, certificate_id=1, thumbprint="ABC", pfx=b"ESCROWED-PFX", password="escrow-pw")

    for vault_name in ("attcc-eastus2-perf-kv", "attcc-eastus2-uat-kv"):
        resp = await admin_client.post(
            "/api/v1/certificates/1/load-to-akv",
            json={**_AKV_TARGET, "vault_name": vault_name},
        )
        assert resp.status_code == 200
        assert resp.json()["key_source"] == "escrow"

    assert len(fake_keyvault.imports) == 2
    assert {i["cert_bytes"] for i in fake_keyvault.imports} == {b"ESCROWED-PFX"}


async def test_load_to_akv_falls_back_to_keyfactor_without_escrow(app, admin_client, fake_keyvault, escrow_vault):
    svc = FakeService()
    _use_service(app, svc)
    resp = await admin_client.post("/api/v1/certificates/1/load-to-akv", json=_AKV_TARGET)
    assert resp.status_code == 200
    assert resp.json()["key_source"] == "keyfactor"
    assert svc.last_download_kwargs["file_format"] == "PFX"


async def test_load_to_akv_key_source_escrow_never_falls_back(app, admin_client, fake_keyvault, escrow_vault):
    # Explicitly asking for the escrowed key must fail loudly rather than quietly
    # exporting from Keyfactor, which would only work for key-archived certs.
    svc = FakeService()
    _use_service(app, svc)
    resp = await admin_client.post(
        "/api/v1/certificates/1/load-to-akv",
        json={**_AKV_TARGET, "key_source": "escrow"},
    )
    assert resp.status_code == 409
    assert "no escrowed private key" in resp.json()["detail"].lower()
    assert svc.last_download_kwargs is None
    assert fake_keyvault.imports == []


async def test_load_to_akv_key_source_keyfactor_bypasses_escrow(
    app, admin_client, db_session, fake_keyvault, escrow_vault
):
    svc = FakeService()
    _use_service(app, svc)
    await _seed_escrow(db_session, certificate_id=1, thumbprint="ABC", pfx=b"ESCROWED-PFX", password="escrow-pw")

    resp = await admin_client.post(
        "/api/v1/certificates/1/load-to-akv",
        json={**_AKV_TARGET, "key_source": "keyfactor"},
    )
    assert resp.status_code == 200
    assert resp.json()["key_source"] == "keyfactor"
    assert fake_keyvault.imports[0]["cert_bytes"] == b"CERTIFICATE"


async def test_load_to_akv_rejects_unknown_key_source(app, admin_client, fake_keyvault):
    _use_service(app, FakeService())
    resp = await admin_client.post(
        "/api/v1/certificates/1/load-to-akv",
        json={**_AKV_TARGET, "key_source": "somewhere-else"},
    )
    assert resp.status_code == 422


async def test_load_to_akv_export_failure_mentions_escrow(app, admin_client, fake_keyvault, escrow_vault):
    _use_service(app, FakeService(error=CertificateServiceError("Private key is not available.", status_code=400)))
    resp = await admin_client.post("/api/v1/certificates/1/load-to-akv", json=_AKV_TARGET)
    assert resp.status_code == 409
    assert "escrow" in resp.json()["detail"].lower()


async def test_renew_escrows_the_issued_pfx(app, admin_client, db_session, escrow_vault):
    from sqlalchemy import select

    from app.models.database import CertificateKeyEscrow

    svc = FakeService()
    svc.renew_result = {"thumbprint": "NEWTHUMB", "certificate_id": 77, "pfx_base64": "UEZY"}
    _use_service(app, svc)

    resp = await admin_client.post(
        "/api/v1/certificates/1/renew",
        json={"mode": "pfx", "password": "a-long-enough-password"},
    )
    assert resp.status_code == 200
    assert resp.json()["key_escrowed"] is True

    row = (await db_session.execute(select(CertificateKeyEscrow))).scalar_one()
    assert row.thumbprint == "newthumb"
    assert row.certificate_id == 77
    assert row.source == "renew"
    # The secret carries the material; the pointer row does not.
    assert escrow_vault.secrets["cert-pfx-newthumb"]


async def test_renew_without_escrow_configured_is_unchanged(app, admin_client, monkeypatch):
    monkeypatch.setattr(settings, "CERT_KEY_ESCROW_ENABLED", False)
    svc = FakeService()
    svc.renew_result = {"thumbprint": "NEWTHUMB", "certificate_id": 77, "pfx_base64": "UEZY"}
    _use_service(app, svc)
    resp = await admin_client.post(
        "/api/v1/certificates/1/renew",
        json={"mode": "pfx", "password": "a-long-enough-password"},
    )
    assert resp.status_code == 200
    assert "key_escrowed" not in resp.json()


async def test_renew_survives_an_escrow_failure(app, admin_client, monkeypatch):
    # The certificate is already issued by then — escrow problems must never
    # turn a successful renewal into an error.
    monkeypatch.setattr(settings, "CERT_KEY_ESCROW_ENABLED", True)
    monkeypatch.setattr(settings, "CERT_KEY_ESCROW_VAULT", "escrow-kv")

    class _BrokenVault:
        async def create_or_update_secret(self, *a, **k):
            raise RuntimeError("vault unreachable")

    monkeypatch.setattr("app.services.certificate_escrow_service.KeyVaultService", lambda: _BrokenVault())
    svc = FakeService()
    svc.renew_result = {"thumbprint": "NEWTHUMB", "certificate_id": 77, "pfx_base64": "UEZY"}
    _use_service(app, svc)

    resp = await admin_client.post(
        "/api/v1/certificates/1/renew",
        json={"mode": "pfx", "password": "a-long-enough-password"},
    )
    assert resp.status_code == 200
    assert resp.json()["thumbprint"] == "NEWTHUMB"
    assert "key_escrowed" not in resp.json()


async def test_enroll_pfx_escrows_the_issued_key(app, admin_client, db_session, escrow_vault):
    from sqlalchemy import select

    from app.models.database import CertificateKeyEscrow

    _use_service(app, FakeService())
    resp = await admin_client.post(
        "/api/v1/certificates/enroll",
        json={
            "enrollment_type": "pfx",
            "certificate_authority": "ca",
            "template": "WebServer",
            "common_name": "new.example.com",
            "password": "a-long-enough-password",
        },
    )
    assert resp.status_code == 201
    assert resp.json()["key_escrowed"] is True

    row = (await db_session.execute(select(CertificateKeyEscrow))).scalar_one()
    assert row.thumbprint == "def"
    assert row.source == "enroll"
    assert row.common_name == "new.example.com"


async def test_enroll_csr_has_nothing_to_escrow(app, admin_client, db_session, escrow_vault):
    from sqlalchemy import select

    from app.models.database import CertificateKeyEscrow

    _use_service(app, FakeService())
    resp = await admin_client.post(
        "/api/v1/certificates/enroll",
        json={
            "enrollment_type": "csr",
            "certificate_authority": "ca",
            "template": "WebServer",
            "csr": "-----BEGIN CERTIFICATE REQUEST-----",
        },
    )
    assert resp.status_code == 201
    # CSR enrollment keeps the key on the requester's side — no PFX exists.
    assert (await db_session.execute(select(CertificateKeyEscrow))).scalars().all() == []
    assert escrow_vault.secrets == {}


async def test_list_certificates_flags_escrowed_keys(app, admin_client, db_session, escrow_vault):
    _use_service(app, FakeService())
    await _seed_escrow(db_session, certificate_id=1, thumbprint="ABC", pfx=b"PFX", password="pw")

    resp = await admin_client.get("/api/v1/certificates")
    assert resp.status_code == 200
    assert resp.json()["items"][0]["key_escrowed"] is True


async def test_list_certificates_reports_missing_escrow_explicitly(app, admin_client, escrow_vault):
    # With escrow on, an un-escrowed certificate must say so rather than stay silent.
    _use_service(app, FakeService())
    resp = await admin_client.get("/api/v1/certificates")
    assert resp.status_code == 200
    assert resp.json()["items"][0]["key_escrowed"] is False


async def test_list_certificates_omits_escrow_flag_when_disabled(app, admin_client, monkeypatch):
    # Deployments without escrow must not show a misleading "no key" state.
    monkeypatch.setattr(settings, "CERT_KEY_ESCROW_ENABLED", False)
    _use_service(app, FakeService())
    resp = await admin_client.get("/api/v1/certificates")
    assert resp.status_code == 200
    assert "key_escrowed" not in resp.json()["items"][0]


# ── PFX download via escrow ────────────────────────────────────────────


def _pfx_fixture(password: str) -> bytes:
    """A real PKCS#12 blob so the download path exercises actual re-wrapping."""
    from datetime import UTC, datetime, timedelta

    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.hazmat.primitives.serialization import pkcs12
    from cryptography.x509.oid import NameOID

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "a.example.com")])
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.now(UTC) - timedelta(days=1))
        .not_valid_after(datetime.now(UTC) + timedelta(days=365))
        .sign(key, hashes.SHA256())
    )
    return pkcs12.serialize_key_and_certificates(
        name=None,
        key=key,
        cert=cert,
        cas=None,
        encryption_algorithm=serialization.BestAvailableEncryption(password.encode()),
    )


_NO_KEY = CertificateServiceError("Private key is not available.", status_code=400)


async def test_pfx_download_falls_back_to_the_escrowed_key(app, admin_client, db_session, escrow_vault):
    # Keyfactor refuses to export a key it never archived, which surfaced as a
    # 422 on download. The escrowed copy must serve the request instead.
    from cryptography.hazmat.primitives.serialization import pkcs12

    _use_service(app, FakeService(error=_NO_KEY))
    await _seed_escrow(
        db_session,
        certificate_id=1,
        thumbprint="ABC",
        pfx=_pfx_fixture("issuance-time-pw"),
        password="issuance-time-pw",
    )

    resp = await admin_client.post(
        "/api/v1/certificates/1/download",
        json={"file_format": "PFX", "pfx_password": "download-password-1"},
    )
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/x-pkcs12"
    # The delivered file opens with the password the caller asked for.
    key, cert, _ = pkcs12.load_key_and_certificates(resp.content, b"download-password-1")
    assert key is not None
    assert cert is not None


async def test_pfx_download_prefers_keyfactor_when_it_works(app, admin_client, db_session, escrow_vault):
    # Escrow is a fallback here, not a replacement: a working Keyfactor export
    # keeps honouring chain options exactly as before.
    svc = FakeService()
    _use_service(app, svc)
    await _seed_escrow(db_session, certificate_id=1, thumbprint="ABC", pfx=_pfx_fixture("pw"), password="pw")
    resp = await admin_client.post(
        "/api/v1/certificates/1/download",
        json={"file_format": "PFX", "pfx_password": "download-password-1"},
    )
    assert resp.status_code == 200
    assert resp.content == b"CERTIFICATE"
    assert svc.last_download_kwargs["pfx_password"] == "download-password-1"


async def test_pfx_download_without_any_key_is_actionable(app, admin_client, escrow_vault):
    # No Keyfactor key and nothing escrowed → a 409 that says what to do, rather
    # than the bare 422 that used to leak out of the Keyfactor error mapping.
    _use_service(app, FakeService(error=_NO_KEY))
    resp = await admin_client.post(
        "/api/v1/certificates/1/download",
        json={"file_format": "PFX", "pfx_password": "download-password-1"},
    )
    assert resp.status_code == 409
    detail = resp.json()["detail"]
    assert "no escrowed key" in detail.lower()
    assert "renew this certificate through the portal" in detail.lower()


async def test_non_pfx_download_error_mapping_is_unchanged(app, admin_client, escrow_vault):
    _use_service(app, FakeService(error=CertificateServiceError("Bad request.", status_code=400)))
    resp = await admin_client.post("/api/v1/certificates/1/download", json={"file_format": "PEM"})
    assert resp.status_code == 422


async def test_pfx_download_still_requires_a_password(app, admin_client, escrow_vault):
    _use_service(app, FakeService(error=_NO_KEY))
    resp = await admin_client.post("/api/v1/certificates/1/download", json={"file_format": "PFX"})
    assert resp.status_code == 422


# ── JKS download ───────────────────────────────────────────────────────


_JKS_MAGIC = bytes.fromhex("feedfeed")


def _jks_request(**overrides) -> dict:
    return {"file_format": "JKS", "pfx_password": "keystore-password-1", **overrides}


async def test_jks_download_is_built_from_a_keyfactor_pfx(app, admin_client):
    # Keyfactor has no JKS format, so it is asked for a PFX under a throwaway
    # transit password and the keystore is assembled locally.
    svc = FakeService()
    svc.download_payload = lambda kw: _pfx_fixture(kw["pfx_password"])
    _use_service(app, svc)

    resp = await admin_client.post("/api/v1/certificates/1/download", json=_jks_request())
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/x-java-keystore"
    assert resp.content[:4] == _JKS_MAGIC

    # Keyfactor was asked for PFX, never for "JKS".
    assert svc.last_download_kwargs["file_format"] == "PFX"
    # The transit password is internal and must not be the keystore password.
    assert svc.last_download_kwargs["pfx_password"] != "keystore-password-1"

    # The delivered keystore opens with the password the caller asked for.
    store = load_jks(resp.content, "keystore-password-1")
    assert store.private_keys


async def test_jks_download_falls_back_to_the_escrowed_key(app, admin_client, db_session, escrow_vault):
    _use_service(app, FakeService(error=_NO_KEY))
    await _seed_escrow(
        db_session,
        certificate_id=1,
        thumbprint="ABC",
        pfx=_pfx_fixture("issuance-time-pw"),
        password="issuance-time-pw",
    )

    resp = await admin_client.post("/api/v1/certificates/1/download", json=_jks_request())
    assert resp.status_code == 200
    assert resp.content[:4] == _JKS_MAGIC
    assert load_jks(resp.content, "keystore-password-1").private_keys


async def test_jks_download_honours_an_alias_override(app, admin_client):
    svc = FakeService()
    svc.download_payload = lambda kw: _pfx_fixture(kw["pfx_password"])
    _use_service(app, svc)
    resp = await admin_client.post("/api/v1/certificates/1/download", json=_jks_request(jks_alias="Tomcat-TLS"))
    assert resp.status_code == 200
    assert list(load_jks(resp.content, "keystore-password-1").private_keys) == ["tomcat-tls"]


async def test_jks_download_requires_a_password(app, admin_client):
    _use_service(app, FakeService())
    resp = await admin_client.post("/api/v1/certificates/1/download", json={"file_format": "JKS"})
    assert resp.status_code == 422
    assert "JKS" in str(resp.json()["detail"])


async def test_jks_download_requires_write_role(app, reader_client):
    _use_service(app, FakeService())
    resp = await reader_client.post("/api/v1/certificates/1/download", json=_jks_request())
    assert resp.status_code == 403
    assert "JKS" in resp.json()["detail"]


async def test_jks_download_without_any_key_is_actionable(app, admin_client, escrow_vault):
    _use_service(app, FakeService(error=_NO_KEY))
    resp = await admin_client.post("/api/v1/certificates/1/download", json=_jks_request())
    assert resp.status_code == 409
    detail = resp.json()["detail"].lower()
    assert "jks keystore needs the certificate's private key" in detail
    assert "renew this certificate through the portal" in detail


async def test_jks_download_reports_unusable_material(app, admin_client):
    # Keyfactor returning something that is not a PFX must not surface as a 500.
    svc = FakeService()
    svc.download_payload = b"not-a-pfx"
    _use_service(app, svc)
    resp = await admin_client.post("/api/v1/certificates/1/download", json=_jks_request())
    assert resp.status_code == 422
    assert "could not build a jks keystore" in resp.json()["detail"].lower()


# ── Audit trail names the certificate ──────────────────────────────────


async def _cache_certificate(db_session, *, certificate_id: int, common_name: str) -> None:
    """Seed the snapshot the audit trail resolves names from."""
    from sqlalchemy import text

    await db_session.execute(
        text("INSERT INTO cert_certificates (collection_id, certificate_id, common_name) VALUES (:col, :cid, :cn)"),
        {"col": 2573, "cid": certificate_id, "cn": common_name},
    )
    await db_session.commit()


async def _last_audit(db_session, action: str):
    from sqlalchemy import select

    from app.models.database import AuditLog

    rows = (await db_session.execute(select(AuditLog).where(AuditLog.action == action))).scalars().all()
    assert rows, f"no audit row written for {action}"
    return rows[-1]


async def test_revoke_audit_names_the_certificate(app, admin_client, db_session):
    # "Revoked certificate 31069046" does not say which certificate was revoked.
    _use_service(app, FakeService())
    await _cache_certificate(db_session, certificate_id=1, common_name="cesdataroutergears.dev.att.com")

    resp = await admin_client.post("/api/v1/certificates/1/revoke", json={"reason": "superseded"})
    assert resp.status_code == 200

    entry = await _last_audit(db_session, "revoke_certificate")
    assert entry.details["summary"] == "Revoked cesdataroutergears.dev.att.com (1) (superseded)"
    assert entry.details["common_name"] == "cesdataroutergears.dev.att.com"


async def test_download_audit_names_the_certificate(app, admin_client, db_session):
    _use_service(app, FakeService())
    await _cache_certificate(db_session, certificate_id=1, common_name="attcctrino.web.att.com")

    resp = await admin_client.post("/api/v1/certificates/1/download", json={"file_format": "PEM"})
    assert resp.status_code == 200

    entry = await _last_audit(db_session, "download_certificate")
    assert entry.details["summary"] == "Downloaded attcctrino.web.att.com (1) (PEM)"
    assert entry.details["common_name"] == "attcctrino.web.att.com"


async def test_jks_download_audit_names_the_certificate(app, admin_client, db_session):
    svc = FakeService()
    svc.download_payload = lambda kw: _pfx_fixture(kw["pfx_password"])
    _use_service(app, svc)
    await _cache_certificate(db_session, certificate_id=1, common_name="attccgrafana.stage.att.com")

    resp = await admin_client.post("/api/v1/certificates/1/download", json=_jks_request())
    assert resp.status_code == 200

    entry = await _last_audit(db_session, "download_certificate")
    assert entry.details["summary"] == "Downloaded attccgrafana.stage.att.com (1) (JKS)"


async def test_renew_audit_names_the_certificate(app, admin_client, db_session):
    _use_service(app, FakeService())
    await _cache_certificate(db_session, certificate_id=1, common_name="attcctrino.stage.att.com")

    resp = await admin_client.post("/api/v1/certificates/1/renew", json={"mode": "one_click"})
    assert resp.status_code == 200

    entry = await _last_audit(db_session, "renew_certificate")
    assert entry.details["summary"] == "Renewed attcctrino.stage.att.com (1)"


async def test_delete_audit_names_the_certificate(app, admin_client, db_session):
    # Resolved before the delete: afterwards the audit row is the only record
    # of which certificate this was.
    _use_service(app, FakeService())
    await _cache_certificate(db_session, certificate_id=1, common_name="attccworkday.stage.att.com")

    resp = await admin_client.delete("/api/v1/certificates/1")
    assert resp.status_code == 200

    entry = await _last_audit(db_session, "delete_certificate")
    assert entry.details["summary"] == "Deleted attccworkday.stage.att.com (1)"
    assert entry.details["common_name"] == "attccworkday.stage.att.com"


async def test_metadata_audit_names_the_certificate(app, admin_client, db_session):
    _use_service(app, FakeService())
    await _cache_certificate(db_session, certificate_id=1, common_name="a.example.com")

    resp = await admin_client.put("/api/v1/certificates/1/metadata", json={"metadata": {"owner": "team-a"}})
    assert resp.status_code == 200

    entry = await _last_audit(db_session, "update_certificate_metadata")
    assert entry.details["summary"] == "Updated metadata on a.example.com (1)"


async def test_load_to_akv_audit_names_the_certificate(app, admin_client, db_session, fake_keyvault):
    _use_service(app, FakeService())
    await _cache_certificate(db_session, certificate_id=1, common_name="cesdatarouter.stage.att.com")

    resp = await admin_client.post("/api/v1/certificates/1/load-to-akv", json=_AKV_TARGET)
    assert resp.status_code == 200

    entry = await _last_audit(db_session, "load_certificate_to_akv")
    assert entry.details["summary"].startswith("Loaded cesdatarouter.stage.att.com (1) to AKV my-vault/")
    assert entry.details["common_name"] == "cesdatarouter.stage.att.com"


async def test_enroll_audit_names_the_certificate(app, admin_client, db_session):
    # A new certificate has no cached snapshot, so the name comes from the request.
    _use_service(app, FakeService())
    resp = await admin_client.post(
        "/api/v1/certificates/enroll",
        json={
            "enrollment_type": "pfx",
            "certificate_authority": "ca",
            "template": "WebServer",
            "common_name": "new.example.com",
            "password": "a-long-enough-password",
        },
    )
    assert resp.status_code == 201

    entry = await _last_audit(db_session, "enroll_certificate")
    assert entry.details["summary"] == "Enrolled new.example.com (pfx) via WebServer"
    assert entry.details["common_name"] == "new.example.com"


async def test_audit_falls_back_to_the_id_when_the_name_is_unknown(app, admin_client, db_session):
    # An un-cached certificate must still audit cleanly, just without a name.
    _use_service(app, FakeService())
    resp = await admin_client.post("/api/v1/certificates/999/revoke", json={"reason": "superseded"})
    assert resp.status_code == 200

    entry = await _last_audit(db_session, "revoke_certificate")
    assert entry.details["summary"] == "Revoked 999 (superseded)"
    assert entry.details["common_name"] is None
