"""Integration tests for the certificate management API endpoints.

The CertificateService is replaced with an in-memory fake via dependency
override. Covers success, validation failure, upstream auth (401), not-found
(404), and server-error (5xx) paths, plus RBAC gating for destructive actions.
"""

import pytest

from app.api.v1.endpoints.certificates import _filter_enabled_collections, _get_service
from app.core.config import settings
from app.services.keyfactor_service import CertificateServiceError

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
        self.last_download_kwargs: dict | None = None
        self.download_calls: list[dict] = []

    def _maybe_raise(self):
        if self.error:
            raise self.error

    async def list_certificates(self, *, query, page, page_size, collection_id=None):
        self._maybe_raise()
        self.last_query = query
        self.last_collection_id = collection_id
        return {"items": [CERT], "total": 1, "page": page, "page_size": page_size}

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
        return {"thumbprint": "NEW"}

    async def download_certificate(self, certificate_id, **kwargs):
        self._maybe_raise()
        self.last_download_kwargs = {"certificate_id": certificate_id, **kwargs}
        self.download_calls.append(self.last_download_kwargs)
        return b"CERTIFICATE"

    async def revoke_certificate(self, **kwargs):
        self._maybe_raise()
        return {"certificate_id": kwargs["certificate_id"], "reason": kwargs["reason"], "revoked": True}

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
