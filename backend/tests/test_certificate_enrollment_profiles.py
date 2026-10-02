"""Saved certificate enrollment profiles and enrollment-option fallbacks."""

from app.services.keyfactor_client import KeyfactorAuthError
from app.services.keyfactor_service import CertificateService, _ca_enrollment_value

BASE = "/api/v1/certificates/enrollment-profiles"

PROFILE = {
    "name": "ATT Standard Web Server",
    "description": "Defaults for internal AT&T web servers",
    "shared": True,
    "defaults": {
        "template": "Digicert-Standard-SHA2-4096Key",
        "certificate_authority": "internal-ca.att.com\\ATT-Internal-CA-G2",
        "organization": "AT&T Services, Inc.",
        "city": "Dallas",
        "state": "Texas",
        "country": "US",
        "environment": "Production",
        "mots_profile_id": "12345",
    },
}


# ── Profile CRUD ───────────────────────────────────────────────────────


async def test_profile_create_list_update_delete(admin_client):
    created = await admin_client.post(BASE, json=PROFILE)
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["name"] == PROFILE["name"]
    assert body["shared"] is True
    assert body["template"] == "Digicert-Standard-SHA2-4096Key"
    assert body["certificate_authority"] == "internal-ca.att.com\\ATT-Internal-CA-G2"
    assert body["defaults"]["environment"] == "Production"
    profile_id = body["id"]

    listed = await admin_client.get(BASE)
    assert listed.status_code == 200
    assert [p["id"] for p in listed.json()] == [profile_id]

    updated_payload = {**PROFILE, "description": "Updated", "defaults": {**PROFILE["defaults"], "port": "443"}}
    updated = await admin_client.put(f"{BASE}/{profile_id}", json=updated_payload)
    assert updated.status_code == 200
    assert updated.json()["description"] == "Updated"
    assert updated.json()["defaults"]["port"] == "443"

    deleted = await admin_client.delete(f"{BASE}/{profile_id}")
    assert deleted.status_code == 200
    assert deleted.json() == {"id": profile_id, "deleted": True}

    assert (await admin_client.get(BASE)).json() == []


async def test_profile_rejects_key_material(admin_client):
    payload = {**PROFILE, "defaults": {**PROFILE["defaults"], "password": "hunter2hunter2"}}
    response = await admin_client.post(BASE, json=payload)
    assert response.status_code == 422
    assert "key material" in response.text


async def test_profile_duplicate_name_conflicts(admin_client):
    assert (await admin_client.post(BASE, json=PROFILE)).status_code == 201
    duplicate = await admin_client.post(BASE, json=PROFILE)
    assert duplicate.status_code == 409


async def test_private_profile_hidden_from_other_users(app, admin_client):
    from app.auth import get_current_user

    from .conftest import make_read_user

    private = {**PROFILE, "name": "Private profile", "shared": False}
    created = await admin_client.post(BASE, json=private)
    assert created.status_code == 201
    assert created.json()["shared"] is False

    # Same client, different caller: the profile is private to its creator.
    app.dependency_overrides[get_current_user] = make_read_user
    assert (await admin_client.get(BASE)).json() == []


async def test_profile_update_missing_returns_404(admin_client):
    response = await admin_client.put(f"{BASE}/9999", json=PROFILE)
    assert response.status_code == 404


async def test_profile_update_rename_to_existing_name_conflicts(admin_client):
    assert (await admin_client.post(BASE, json=PROFILE)).status_code == 201
    other = (await admin_client.post(BASE, json={**PROFILE, "name": "Other"})).json()

    clash = await admin_client.put(f"{BASE}/{other['id']}", json=PROFILE)
    assert clash.status_code == 409

    # Keeping its own name is not a clash.
    same = await admin_client.put(f"{BASE}/{other['id']}", json={**PROFILE, "name": "Other"})
    assert same.status_code == 200


# ── Enrollment options ─────────────────────────────────────────────────


def test_ca_enrollment_value_joins_host_and_logical_name():
    assert _ca_enrollment_value({"HostName": "ca01.att.com", "LogicalName": "ATT-Issuing-CA"}) == (
        "ca01.att.com\\ATT-Issuing-CA"
    )


def test_ca_enrollment_value_leaves_qualified_name_alone():
    assert _ca_enrollment_value({"LogicalName": "ca01.att.com\\ATT-Issuing-CA"}) == "ca01.att.com\\ATT-Issuing-CA"


def test_ca_enrollment_value_without_host_uses_logical_name():
    assert _ca_enrollment_value({"Name": "ATT-Issuing-CA"}) == "ATT-Issuing-CA"


class _FailingClient:
    """Stands in for a service account that may not enumerate CAs/templates."""

    async def get_certificate_authorities(self):
        raise KeyfactorAuthError("forbidden", status_code=403)

    async def get_enrollment_templates(self):
        raise KeyfactorAuthError("forbidden", status_code=403)

    async def get_enrollment_patterns(self):
        raise KeyfactorAuthError("forbidden", status_code=403)

    async def get_pfx_enrollment_context(self):
        raise KeyfactorAuthError("forbidden", status_code=403)


# Shape of Keyfactor's /Enrollment/PFX/Context/My templates, trimmed to what the portal reads.
PFX_CONTEXT = [
    {
        "Id": 56,
        "Name": "Digicert-Standard-SHA2-4096Key",
        "DisplayName": "Digicert-Standard-SHA2-4096Key",
        "Forest": "att-ad.local",
        "CAs": [{"Id": 6, "Name": "DigicertEP"}],
        "EnrollmentTemplatePolicy": {
            "KeyInfo": {
                "RSA": {"bit_lengths": [4096], "curves": []},
                "ECDSA": {"bit_lengths": [], "curves": []},
            }
        },
    },
    {
        "Id": 1155,
        "Name": "TLSServerProfileECDSA_TLSServerProfileECDSA",
        "DisplayName": "TLSServerProfileECDSA (TLSServerProfileECDSA)",
        "Forest": "SaaS2_ATT-Intermediate-RSA-G001",
        "CAs": [{"Id": 11, "Name": "ATT-Intermediate-RSA-G001"}],
        "EnrollmentTemplatePolicy": {
            "KeyInfo": {
                "RSA": {"bit_lengths": [], "curves": []},
                "ECDSA": {"bit_lengths": [384], "curves": ["1.3.132.0.34"]},
            }
        },
    },
]


class _ContextOnlyClient(_FailingClient):
    """May read its PFX enrollment context but not list enrollment patterns."""

    async def get_pfx_enrollment_context(self):
        return PFX_CONTEXT


async def test_authority_list_falls_back_to_configured_default(monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "KEYFACTOR_DEFAULT_CA", "ca01.att.com\\ATT-Issuing-CA")
    service = CertificateService(client=_FailingClient())

    authorities = await service.list_certificate_authorities()

    assert authorities == [
        {
            "id": 0,
            "name": "ATT-Issuing-CA",
            "logical_name": "ATT-Issuing-CA",
            "host_name": "ca01.att.com",
            "value": "ca01.att.com\\ATT-Issuing-CA",
            "source": "configured-default",
        }
    ]


async def test_template_list_falls_back_to_configured_default(monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "KEYFACTOR_DEFAULT_TEMPLATE", "Digicert-Standard-SHA2-4096Key")
    service = CertificateService(client=_FailingClient())

    templates = await service.list_templates()

    assert [t["template_name"] for t in templates] == ["Digicert-Standard-SHA2-4096Key"]
    assert templates[0]["source"] == "configured-default"


async def test_authority_list_is_empty_without_a_configured_default(monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "KEYFACTOR_DEFAULT_CA", "")
    service = CertificateService(client=_FailingClient())

    assert await service.list_certificate_authorities() == []


async def test_pattern_list_falls_back_to_configured_patterns(monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(
        settings,
        "KEYFACTOR_ENROLLMENT_PATTERNS",
        "28:Digicert-Standard-SHA2-4096Key, 37:Private TLS Certificate,bad,0:zero,x:y",
    )
    service = CertificateService(client=_FailingClient())

    patterns = await service.list_enrollment_patterns()

    assert [(p["id"], p["name"]) for p in patterns] == [
        (28, "Digicert-Standard-SHA2-4096Key"),
        (37, "Private TLS Certificate"),
    ]
    assert {p["source"] for p in patterns} == {"configured"}
    # Without the enrollment context there is no policy to attach.
    assert all(p["key_algorithms"] == [] and p["certificate_authorities"] == [] for p in patterns)


async def test_configured_patterns_take_key_and_ca_policy_from_their_template(monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(
        settings,
        "KEYFACTOR_ENROLLMENT_PATTERNS",
        "28:Digicert-Standard-SHA2-4096Key (Digicert-Standard-SHA2-4096Key-att-ad.local)|"
        "Digicert-Standard-SHA2-4096Key,"
        "39:Private TLS Certificate-ECC Key|TLSServerProfileECDSA_TLSServerProfileECDSA,"
        "50:Unlinked",
    )

    patterns = await CertificateService(client=_ContextOnlyClient()).list_enrollment_patterns()

    by_id = {p["id"]: p for p in patterns}
    assert by_id[28]["group"] == "att-ad.local"
    assert by_id[28]["key_algorithms"] == [{"name": "RSA", "key_sizes": [4096], "curves": []}]
    assert by_id[28]["certificate_authorities"] == ["DigicertEP"]
    assert by_id[39]["group"] == "SaaS2_ATT-Intermediate-RSA-G001"
    assert by_id[39]["key_algorithms"] == [{"name": "ECC", "key_sizes": [384], "curves": ["1.3.132.0.34"]}]
    assert by_id[39]["certificate_authorities"] == ["ATT-Intermediate-RSA-G001"]
    assert by_id[50]["key_algorithms"] == []


async def test_pattern_list_prefers_keyfactor(monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "KEYFACTOR_ENROLLMENT_PATTERNS", "99:Configured")

    class _PatternClient(_ContextOnlyClient):
        async def get_enrollment_patterns(self):
            return [{"Id": 28, "Name": "Web", "Template": {"TemplateName": "Digicert-Standard-SHA2-4096Key"}}]

    patterns = await CertificateService(client=_PatternClient()).list_enrollment_patterns()

    assert patterns == [
        {
            "id": 28,
            "name": "Web",
            "template_name": "Digicert-Standard-SHA2-4096Key",
            "source": "keyfactor",
            "group": "att-ad.local",
            "key_algorithms": [{"name": "RSA", "key_sizes": [4096], "curves": []}],
            "certificate_authorities": ["DigicertEP"],
        }
    ]


async def test_enrollment_patterns_endpoint(app, admin_client, monkeypatch):
    from app.api.v1.endpoints.certificates import _get_service
    from app.core.config import settings

    monkeypatch.setattr(settings, "KEYFACTOR_ENROLLMENT_PATTERNS", "28:Digicert-Standard-SHA2-4096Key")
    app.dependency_overrides[_get_service] = lambda: CertificateService(client=_FailingClient())

    resp = await admin_client.get("/api/v1/certificates/enrollment-patterns")

    assert resp.status_code == 200
    assert resp.json()[0]["id"] == 28


# Shape of Keyfactor's /MetadataFields, trimmed to what the portal reads.
METADATA_FIELDS = [
    {"Name": "Description", "DataType": 1, "Options": "", "Hint": "Optional Description", "Enrollment": 0},
    {
        "Name": "Server-Type",
        "DataType": 5,
        "Options": "Apache,BEA Weblogic 8 & 9,nginx,Other",
        "Hint": "",
        "Enrollment": 1,
    },
    {"Name": "TSSE", "DataType": 1, "Options": "", "Hint": "Enter the TSSE Number", "Enrollment": 2},
    {
        "Name": "Requester-ATT-User-ID",
        "DataType": 1,
        "Options": "",
        "Hint": "AT&T User ID",
        "Validation": "^[A-Za-z][A-Za-z][0-9][0-9][0-9][A-Za-z0-9]$",
        "Enrollment": 1,
    },
    {"Name": "Auto-Renew", "DataType": 5, "Options": "True,False", "DefaultValue": "False", "Enrollment": 1},
]


class _MetadataClient(_FailingClient):
    async def get_metadata_fields(self):
        return METADATA_FIELDS


async def test_metadata_fields_mirror_keyfactor_options_and_hide_hidden_fields():
    fields = await CertificateService(client=_MetadataClient()).list_enrollment_metadata_fields()

    assert [f["name"] for f in fields] == ["Server-Type", "Requester-ATT-User-ID", "Auto-Renew", "Description"]
    by_name = {f["name"]: f for f in fields}
    assert by_name["Server-Type"]["data_type"] == "choice"
    assert by_name["Server-Type"]["options"] == ["Apache", "BEA Weblogic 8 & 9", "nginx", "Other"]
    assert by_name["Server-Type"]["required"] is True
    assert by_name["Requester-ATT-User-ID"]["validation"].startswith("^[A-Za-z]")
    assert by_name["Auto-Renew"]["default_value"] == "False"
    assert by_name["Description"]["required"] is False


async def test_metadata_fields_empty_when_keyfactor_refuses():
    class _Refusing(_FailingClient):
        async def get_metadata_fields(self):
            raise KeyfactorAuthError("forbidden", status_code=403)

    assert await CertificateService(client=_Refusing()).list_enrollment_metadata_fields() == []


async def test_metadata_fields_endpoint(app, admin_client):
    from app.api.v1.endpoints.certificates import _get_service

    app.dependency_overrides[_get_service] = lambda: CertificateService(client=_MetadataClient())

    resp = await admin_client.get("/api/v1/certificates/metadata-fields")

    assert resp.status_code == 200
    assert resp.json()[0]["name"] == "Server-Type"
