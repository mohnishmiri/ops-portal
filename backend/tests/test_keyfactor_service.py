"""Unit tests for the CertificateService business layer.

The low-level Keyfactor client is replaced with an in-memory fake so we can
assert normalization, validation, and error mapping without any network calls.
"""

from datetime import UTC, datetime, timedelta

import pytest

from app.services.keyfactor_client import KeyfactorNotFoundError, KeyfactorValidationError
from app.services.keyfactor_service import (
    CertificateService,
    CertificateServiceError,
    normalize_certificate,
)


class FakeClient:
    def __init__(self):
        self.calls = []

    async def search_certificates(self, *, query, page, page_size, collection_id=None):
        self.calls.append(("search", query, page, page_size))
        return [{"Id": 1, "CN": "a.example.com"}], 1

    async def get_certificate(self, certificate_id, *, collection_id=None):
        self.calls.append(("get", certificate_id, collection_id))
        return {
            "Id": certificate_id,
            "CN": "a.example.com",
            "IssuedDN": "CN=a.example.com,O=AT&T Services, Inc.,L=Dallas,ST=Texas,C=US",
            "OwnerRoleId": 17,
            "OwnerRoleName": "Certificate Owners",
            "Metadata": {
                "MOTS-Profile-ID": "12345",
                "Requester-ATT-User-ID": "ab1234",
                "Requester-ATT-Manager-User-ID": "cd5678",
                "Server-Type": "Linux",
                "Environment": "Production",
                "TLS-Port-Services-Internet-Traffic": "Yes",
                "Port": "443",
                "PCI-Data": "No",
            },
        }

    async def enroll_csr(self, payload):
        self.calls.append(("enroll_csr", payload))
        return {"CertificateInformation": {"Thumbprint": "ABC", "SerialNumber": "01"}}

    async def enroll_pfx(self, payload):
        self.calls.append(("enroll_pfx", payload))
        return {"CertificateInformation": {"Thumbprint": "DEF", "Pkcs12Blob": "BLOB"}}

    async def renew_certificate(self, payload, *, collection_id=None):
        self.calls.append(("renew", payload, collection_id))
        return {"CertificateInformation": {"Thumbprint": "NEW"}}

    async def revoke_certificate(self, payload, *, collection_id=None):
        self.calls.append(("revoke", payload, collection_id))

    async def update_metadata(self, payload):
        self.calls.append(("metadata", payload))

    async def delete_certificate(self, certificate_id):
        self.calls.append(("delete", certificate_id))

    async def download_certificate(self, certificate_id, **kwargs):
        self.calls.append(("download", certificate_id, kwargs))
        return b"pem"


# ── Normalization ──────────────────────────────────────────────────────


def test_normalize_computes_valid_status():
    future = (datetime.now(UTC) + timedelta(days=120)).isoformat()
    cert = normalize_certificate({"Id": 1, "CN": "x", "NotAfter": future, "CertStateString": "Active"})
    assert cert["status"] == "valid"
    assert cert["revoked"] is False


def test_normalize_computes_expiring_soon():
    soon = (datetime.now(UTC) + timedelta(days=5)).isoformat()
    cert = normalize_certificate({"Id": 1, "NotAfter": soon})
    assert cert["status"] == "expiring_soon"


def test_normalize_computes_expired():
    past = (datetime.now(UTC) - timedelta(days=2)).isoformat()
    cert = normalize_certificate({"Id": 1, "NotAfter": past})
    assert cert["status"] == "expired"


def test_normalize_detects_revoked():
    cert = normalize_certificate({"Id": 1, "CertStateString": "Revoked", "RevocationReason": 1})
    assert cert["status"] == "revoked"
    assert cert["revoked"] is True


def test_normalize_extracts_sans():
    cert = normalize_certificate(
        {"Id": 1, "SubjectAltNameElements": [{"Value": "a.example.com"}, {"Value": "b.example.com"}]}
    )
    assert cert["sans"] == ["a.example.com", "b.example.com"]


def test_normalize_extracts_certificate_authority_name():
    cert = normalize_certificate({"Id": 1, "CertificateAuthorityName": "DigicertEP"})
    assert cert["certificate_authority"] == "DigicertEP"


# ── Service behaviour ──────────────────────────────────────────────────


async def test_list_certificates_shapes_response():
    svc = CertificateService(client=FakeClient())
    result = await svc.list_certificates(query=None, page=1, page_size=25)
    assert result["total"] == 1
    assert result["items"][0]["common_name"] == "a.example.com"


async def test_enroll_pfx_passes_key_material_through_once():
    svc = CertificateService(client=FakeClient())
    result = await svc.enroll_pfx(
        subject="CN=x",
        certificate_authority="ca",
        template="tmpl",
        password="pw",
        key_type="RSA",
        key_length=2048,
        sans=None,
        metadata=None,
        include_chain=True,
    )
    assert result["pfx_base64"] == "BLOB"


async def test_revoke_rejects_invalid_reason():
    svc = CertificateService(client=FakeClient())
    with pytest.raises(CertificateServiceError) as exc:
        await svc.revoke_certificate(certificate_id=1, reason="notARealReason", comment="", effective_date=None)
    assert exc.value.status_code == 422


async def test_update_metadata_rejects_empty():
    svc = CertificateService(client=FakeClient())
    with pytest.raises(CertificateServiceError) as exc:
        await svc.update_metadata(certificate_id=1, metadata={})
    assert exc.value.status_code == 422


async def test_renew_passes_collection_id_to_client():
    client = FakeClient()
    svc = CertificateService(client=client)
    await svc.renew_certificate(
        certificate_id=1,
        mode="one_click",
        certificate_authority=None,
        template=None,
        collection_id=42,
    )
    assert client.calls[-1][0] == "renew"
    assert client.calls[-1][1]["CollectionId"] == 42
    assert client.calls[-1][2] == 42


async def test_pfx_renew_targets_only_the_selected_certificate():
    client = FakeClient()
    svc = CertificateService(client=client)
    await svc.renew_certificate(
        certificate_id=7,
        mode="pfx",
        certificate_authority="ca",
        template="template",
        password="validpassword",
        key_type="RSA",
        key_length=4096,
        collection_id=42,
    )
    assert client.calls[-1] == (
        "enroll_pfx",
        {
            "RenewalCertificateId": 7,
            "Password": "validpassword",
            "IncludeChain": True,
            "Timestamp": client.calls[-1][1]["Timestamp"],
            "CertificateAuthority": "ca",
            "Template": "template",
            "KeyType": "RSA",
            "KeyLength": 4096,
            "OwnerRoleId": 17,
            "Metadata": {
                "MOTS-Profile-ID": "12345",
                "Requester-ATT-User-ID": "ab1234",
                "Requester-ATT-Manager-User-ID": "cd5678",
                "Server-Type": "Linux",
                "Environment": "Production",
                "TLS-Port-Services-Internet-Traffic": "Yes",
                "Port": "443",
                "PCI-Data": "No",
            },
            "Subject": "CN=a.example.com,O=AT&T Services, Inc.,L=Dallas,ST=Texas,C=US",
            "PopulateMissingValuesFromAD": False,
        },
    )
    assert client.calls[-2] == ("get", 7, 42)


async def test_renew_runs_only_the_selected_mode():
    # One-click renewal must not also trigger PFX/CSR enrollment, and must target
    # just the chosen certificate id.
    client = FakeClient()
    svc = CertificateService(client=client)
    await svc.renew_certificate(
        certificate_id=7,
        mode="one_click",
        certificate_authority=None,
        template=None,
        collection_id=42,
    )
    assert [c[0] for c in client.calls] == ["renew"]
    assert client.calls[-1][1]["CertificateId"] == 7


async def test_csr_renew_runs_only_the_selected_mode():
    client = FakeClient()
    svc = CertificateService(client=client)
    await svc.renew_certificate(
        certificate_id=7,
        mode="csr",
        certificate_authority="ca",
        template="template",
        csr="-----BEGIN CERTIFICATE REQUEST-----",
    )
    assert [c[0] for c in client.calls] == ["get", "enroll_csr"]
    assert client.calls[-1][1]["RenewalCertificateId"] == 7


async def test_pfx_renew_preserves_source_subject_dn():
    client = FakeClient()
    svc = CertificateService(client=client)
    await svc.renew_certificate(
        certificate_id=7,
        mode="pfx",
        certificate_authority="ca",
        template="template",
        password="validpassword",
    )
    payload = client.calls[-1][1]
    assert payload["Subject"] == "CN=a.example.com,O=AT&T Services, Inc.,L=Dallas,ST=Texas,C=US"
    assert payload["PopulateMissingValuesFromAD"] is False


async def test_csr_renew_does_not_set_subject():
    # CSR enrollment derives the subject from the CSR itself, so no Subject key is sent.
    client = FakeClient()
    svc = CertificateService(client=client)
    await svc.renew_certificate(
        certificate_id=7,
        mode="csr",
        certificate_authority="ca",
        template="template",
        csr="-----BEGIN CERTIFICATE REQUEST-----",
    )
    assert "Subject" not in client.calls[-1][1]


async def test_pfx_renew_falls_back_to_existing_owner_role_name():
    class NameOnlyOwnerClient(FakeClient):
        async def get_certificate(self, certificate_id, *, collection_id=None):
            return {"Id": certificate_id, "OwnerRoleName": "Certificate Owners"}

    client = NameOnlyOwnerClient()
    svc = CertificateService(client=client)
    await svc.renew_certificate(
        certificate_id=7,
        mode="pfx",
        certificate_authority="ca",
        template="template",
        password="validpassword",
    )
    assert client.calls[-1][1]["OwnerRoleName"] == "Certificate Owners"


async def test_pfx_renew_explicit_owner_role_overrides_source_owner():
    client = FakeClient()
    svc = CertificateService(client=client)
    await svc.renew_certificate(
        certificate_id=7,
        mode="pfx",
        certificate_authority="ca",
        template="template",
        password="validpassword",
        owner_role_name="Replacement Owners",
    )
    assert client.calls[-1][1]["OwnerRoleName"] == "Replacement Owners"
    assert "OwnerRoleId" not in client.calls[-1][1]


async def test_csr_renew_preserves_source_owner_and_metadata():
    client = FakeClient()
    svc = CertificateService(client=client)
    await svc.renew_certificate(
        certificate_id=7,
        mode="csr",
        certificate_authority="ca",
        template="template",
        csr="-----BEGIN CERTIFICATE REQUEST-----",
    )
    payload = client.calls[-1][1]
    assert payload["OwnerRoleId"] == 17
    assert payload["Metadata"]["MOTS-Profile-ID"] == "12345"
    assert payload["Metadata"]["PCI-Data"] == "No"


async def test_pfx_renew_rejects_blank_password():
    svc = CertificateService(client=FakeClient())
    with pytest.raises(CertificateServiceError, match="Password must contain at least 12"):
        await svc.renew_certificate(
            certificate_id=7,
            mode="pfx",
            certificate_authority="ca",
            template="template",
            password="            ",
        )


async def test_revoke_passes_collection_id_to_client():
    client = FakeClient()
    svc = CertificateService(client=client)
    await svc.revoke_certificate(
        certificate_id=1,
        reason="unspecified",
        comment="",
        effective_date=None,
        collection_id=42,
    )
    assert client.calls[-1][0] == "revoke"
    assert client.calls[-1][1]["CollectionId"] == 42
    assert client.calls[-1][2] == 42


async def test_revoke_substitutes_a_comment_when_none_is_given():
    # Keyfactor rejects a blank Comment, so an "optional" comment field in the UI
    # only works if the service fills one in.
    client = FakeClient()
    svc = CertificateService(client=client)
    result = await svc.revoke_certificate(
        certificate_id=1,
        reason="keyCompromise",
        comment="   ",
        effective_date=None,
        actor="admin@example.com",
    )
    sent = client.calls[-1][1]["Comment"]
    assert sent
    assert "admin@example.com" in sent
    assert "keyCompromise" in sent
    # The caller is told what Keyfactor actually recorded, for the audit trail.
    assert result["comment"] == sent


async def test_revoke_substitutes_a_comment_without_an_actor():
    client = FakeClient()
    svc = CertificateService(client=client)
    await svc.revoke_certificate(certificate_id=1, reason="superseded", comment="", effective_date=None)
    assert client.calls[-1][1]["Comment"] == "Revoked via OpsPortal (reason: superseded)"


async def test_revoke_preserves_a_supplied_comment():
    client = FakeClient()
    svc = CertificateService(client=client)
    result = await svc.revoke_certificate(
        certificate_id=1,
        reason="unspecified",
        comment="replaced by CR-1234",
        effective_date=None,
        actor="admin@example.com",
    )
    assert client.calls[-1][1]["Comment"] == "replaced by CR-1234"
    assert result["comment"] == "replaced by CR-1234"


async def test_download_passes_collection_id_to_client():
    client = FakeClient()
    svc = CertificateService(client=client)
    data = await svc.download_certificate(1, collection_id=42)
    assert data == b"pem"
    assert client.calls[-1] == (
        "download",
        1,
        {
            "file_format": "PEM",
            "include_chain": True,
            "chain_order": "EndEntityFirst",
            "collection_id": 42,
            "pfx_password": None,
        },
    )


async def test_service_maps_not_found_error(monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "ENVIRONMENT", "production")

    class NotFoundClient(FakeClient):
        async def get_certificate(self, certificate_id):
            raise KeyfactorNotFoundError("missing", status_code=404)

    svc = CertificateService(client=NotFoundClient())
    with pytest.raises(CertificateServiceError) as exc:
        await svc.get_certificate(123)
    assert exc.value.status_code == 404


async def test_service_maps_validation_error():
    class BadClient(FakeClient):
        async def enroll_csr(self, payload):
            raise KeyfactorValidationError("bad csr", status_code=400)

    svc = CertificateService(client=BadClient())
    with pytest.raises(CertificateServiceError) as exc:
        await svc.enroll_csr(
            csr="x",
            certificate_authority="ca",
            template="tmpl",
            sans=None,
            metadata=None,
            include_chain=True,
        )
    assert exc.value.status_code == 400
