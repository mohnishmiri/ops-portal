"""Unit tests for the Keyfactor client and Azure AD token provider.

External HTTP is mocked by replacing ``httpx.AsyncClient`` in the client module
with a fake that returns queued responses. No live network calls are made.
"""

import pytest

from app.core.config import settings
from app.services import keyfactor_client as kc
from app.services.keyfactor_client import (
    KeyfactorAuthError,
    KeyfactorClient,
    KeyfactorNotFoundError,
    KeyfactorServerError,
    KeyfactorTokenProvider,
)


class FakeResponse:
    def __init__(
        self,
        status_code: int,
        json_data: dict | list | None = None,
        headers: dict | None = None,
        content: bytes = b"",
    ):
        self.status_code = status_code
        self._json = json_data if json_data is not None else {}
        self.headers = headers or {}
        self.content = content

    def json(self):
        return self._json


class FakeAsyncClient:
    """Drop-in replacement for httpx.AsyncClient that pops queued responses."""

    responses: list = []
    calls: list = []

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def post(self, url, data=None, json=None, headers=None, params=None):
        FakeAsyncClient.calls.append(("POST", url, params, json))
        return FakeAsyncClient.responses.pop(0)

    async def request(self, method, url, params=None, json=None, headers=None):
        FakeAsyncClient.calls.append((method, url, params, json, headers))
        return FakeAsyncClient.responses.pop(0)


@pytest.fixture(autouse=True)
def _configure(monkeypatch):
    monkeypatch.setattr(settings, "KEYFACTOR_BASE_URL", "https://keyfactor.test")
    monkeypatch.setattr(settings, "KEYFACTOR_CLIENT_ID", "client-id")
    monkeypatch.setattr(settings, "KEYFACTOR_CLIENT_SECRET", "secret")
    monkeypatch.setattr(settings, "KEYFACTOR_OAUTH_SCOPE", "api://keyfactor/.default")
    monkeypatch.setattr(kc.httpx, "AsyncClient", FakeAsyncClient)

    async def _no_sleep(_seconds):
        return None

    monkeypatch.setattr(kc.asyncio, "sleep", _no_sleep)
    FakeAsyncClient.responses = []
    FakeAsyncClient.calls = []
    yield
    FakeAsyncClient.responses = []
    FakeAsyncClient.calls = []


# ── Token provider ─────────────────────────────────────────────────────


async def test_token_provider_acquires_and_caches():
    FakeAsyncClient.responses = [FakeResponse(200, {"access_token": "tok-1", "expires_in": 3600})]
    provider = KeyfactorTokenProvider()

    token1 = await provider.get_token()
    token2 = await provider.get_token()  # cached — no second POST

    assert token1 == "tok-1"
    assert token2 == "tok-1"
    assert len([c for c in FakeAsyncClient.calls if c[0] == "POST"]) == 1


async def test_token_provider_force_refresh_reacquires():
    FakeAsyncClient.responses = [
        FakeResponse(200, {"access_token": "tok-1", "expires_in": 3600}),
        FakeResponse(200, {"access_token": "tok-2", "expires_in": 3600}),
    ]
    provider = KeyfactorTokenProvider()
    assert await provider.get_token() == "tok-1"
    assert await provider.get_token(force_refresh=True) == "tok-2"


async def test_token_provider_missing_config_raises(monkeypatch):
    monkeypatch.setattr(settings, "KEYFACTOR_CLIENT_SECRET", "")
    provider = KeyfactorTokenProvider()
    with pytest.raises(KeyfactorAuthError):
        await provider.get_token()


async def test_token_provider_http_error_raises():
    FakeAsyncClient.responses = [FakeResponse(400, {"error": "invalid_client"})]
    provider = KeyfactorTokenProvider()
    with pytest.raises(KeyfactorAuthError):
        await provider.get_token()


# ── Client requests ────────────────────────────────────────────────────


async def test_search_certificates_parses_total_header():
    FakeAsyncClient.responses = [
        FakeResponse(200, {"access_token": "tok", "expires_in": 3600}),
        FakeResponse(200, [{"Id": 1}, {"Id": 2}], headers={"x-total-count": "42"}),
    ]
    client = KeyfactorClient(token_provider=KeyfactorTokenProvider())
    certs, total = await client.search_certificates(query=None, page=1, page_size=25)
    assert len(certs) == 2
    assert total == 42


async def test_request_reauths_once_on_401():
    FakeAsyncClient.responses = [
        FakeResponse(200, {"access_token": "tok-1", "expires_in": 3600}),  # initial token
        FakeResponse(401, {"Message": "expired"}),  # first cert call
        FakeResponse(200, {"access_token": "tok-2", "expires_in": 3600}),  # re-acquire
        FakeResponse(200, {"Id": 5}),  # retried cert call
    ]
    client = KeyfactorClient(token_provider=KeyfactorTokenProvider())
    result = await client.get_certificate(5)
    assert result["Id"] == 5


async def test_request_maps_404_to_not_found():
    FakeAsyncClient.responses = [
        FakeResponse(200, {"access_token": "tok", "expires_in": 3600}),
        FakeResponse(404, {"Message": "not found"}),
    ]
    client = KeyfactorClient(token_provider=KeyfactorTokenProvider())
    with pytest.raises(KeyfactorNotFoundError):
        await client.get_certificate(999)


async def test_request_retries_5xx_then_raises_server_error():
    FakeAsyncClient.responses = [
        FakeResponse(200, {"access_token": "tok", "expires_in": 3600}),
        FakeResponse(500, {"Message": "boom"}),  # attempt 0 → retry
        FakeResponse(500, {"Message": "boom"}),  # attempt 1 → raise
    ]
    client = KeyfactorClient(token_provider=KeyfactorTokenProvider())
    with pytest.raises(KeyfactorServerError):
        await client.get_certificate(1)


async def test_error_detail_never_returns_secret_body():
    resp = FakeResponse(403, {"Message": "Access denied"})
    detail = KeyfactorClient._safe_error_detail(resp)  # type: ignore[arg-type]
    assert detail == "Access denied"


# ── Collection-scoped permission plumbing ──────────────────────────────


async def test_renew_sends_collection_id_query_param():
    FakeAsyncClient.responses = [
        FakeResponse(200, {"access_token": "tok", "expires_in": 3600}),
        FakeResponse(200, {"CertificateInformation": {"Thumbprint": "NEW"}}),
    ]
    client = KeyfactorClient(token_provider=KeyfactorTokenProvider())
    await client.renew_certificate({"CertificateId": 1}, collection_id=7)
    renew_calls = [c for c in FakeAsyncClient.calls if "/Enrollment/Renew" in c[1]]
    assert renew_calls[-1][2] == {"collectionId": 7}


async def test_get_certificate_sends_collection_context_for_renewal():
    FakeAsyncClient.responses = [
        FakeResponse(200, {"access_token": "tok", "expires_in": 3600}),
        FakeResponse(200, {"Id": 1, "OwnerRoleId": 17}),
    ]
    client = KeyfactorClient(token_provider=KeyfactorTokenProvider())
    await client.get_certificate(1, collection_id=7)
    certificate_calls = [c for c in FakeAsyncClient.calls if "/Certificates/1" in c[1]]
    assert certificate_calls[-1][2] == {
        "verbose": 2,
        "includeMetadata": "true",
        "includeLocations": "true",
        "collectionId": 7,
    }


async def test_pfx_renew_requests_replacement_in_existing_locations():
    FakeAsyncClient.responses = [
        FakeResponse(200, {"access_token": "tok", "expires_in": 3600}),
        FakeResponse(200, {"CertificateInformation": {"Thumbprint": "NEW"}}),
    ]
    client = KeyfactorClient(token_provider=KeyfactorTokenProvider())
    await client.enroll_pfx({"RenewalCertificateId": 1}, replace_existing=True)
    pfx_calls = [c for c in FakeAsyncClient.calls if "/Enrollment/PFX" in c[1]]
    assert pfx_calls[-1][4]["X-CertificateFormat"] == "REPLACE"


async def test_revoke_sends_collection_id_query_param():
    FakeAsyncClient.responses = [
        FakeResponse(200, {"access_token": "tok", "expires_in": 3600}),
        FakeResponse(204),
    ]
    client = KeyfactorClient(token_provider=KeyfactorTokenProvider())
    await client.revoke_certificate({"CertificateIds": [1]}, collection_id=8)
    revoke_calls = [c for c in FakeAsyncClient.calls if "/Certificates/Revoke" in c[1]]
    assert revoke_calls[-1][2] == {"collectionId": 8}


async def test_download_sends_collection_id_query_param():
    FakeAsyncClient.responses = [
        FakeResponse(200, {"access_token": "tok", "expires_in": 3600}),
        FakeResponse(200, content=b"pem-bytes"),
    ]
    client = KeyfactorClient(token_provider=KeyfactorTokenProvider())
    data = await client.download_certificate(1, collection_id=9)
    assert data == b"pem-bytes"
    download_calls = [c for c in FakeAsyncClient.calls if "/Certificates/Download" in c[1]]
    assert download_calls[-1][2] == {"collectionId": 9}


async def test_renew_omits_collection_param_when_unscoped():
    FakeAsyncClient.responses = [
        FakeResponse(200, {"access_token": "tok", "expires_in": 3600}),
        FakeResponse(200, {"CertificateInformation": {"Thumbprint": "NEW"}}),
    ]
    client = KeyfactorClient(token_provider=KeyfactorTokenProvider())
    await client.renew_certificate({"CertificateId": 1})
    renew_calls = [c for c in FakeAsyncClient.calls if "/Enrollment/Renew" in c[1]]
    assert renew_calls[-1][2] is None
