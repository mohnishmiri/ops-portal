"""Tests for Key Vault secret search by name and by value.

Value search reads every secret in the vault, so the cases below pin the
three things that make that safe: values never leave the service, the scan
is role-gated, and the audit trail records the search without the term.
"""

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from app.api.v1.endpoints.keyvault import _get_kv_service
from app.auth import get_current_user
from app.core.config import settings
from app.core.database import get_db
from app.services.keyvault_service import KeyVaultService, _value_contains

from .conftest import make_read_user

VAULT = "https://demo-kv.vault.azure.net/"


def _secret(name: str, *, enabled: bool = True) -> dict:
    return {
        "name": name,
        "id": f"{VAULT}secrets/{name}",
        "content_type": "",
        "enabled": enabled,
        "created": None,
        "updated": None,
        "expires": None,
        "not_before": None,
        "tags": {},
        "managed": False,
    }


def _service_with(values: dict, *, listed: list | None = None) -> KeyVaultService:
    """A service whose vault reads are backed by an in-memory secret map.

    A ``None`` value stands for a secret that cannot be read back.
    """
    service = KeyVaultService()
    secrets = listed if listed is not None else [_secret(n) for n in values]
    service.value_reads = []

    async def _list_secrets(vault_uri, search=None, *, refresh=False):
        return secrets

    async def _get_vault_token():
        return "token"

    async def _vault_get(url, *, token=None):
        name = url.split("/secrets/")[1].split("?")[0]
        service.value_reads.append(name)
        value = values.get(name)
        if value is None:
            raise RuntimeError("HTTP Error 403: Forbidden")
        return {"value": value}

    service.list_secrets = _list_secrets
    service._get_vault_token = _get_vault_token
    service._vault_get = _vault_get
    return service


# ── Value matching ─────────────────────────────────────────────────────


def test_value_contains_matches_raw_value_case_insensitively():
    assert _value_contains("SuperSecret123", "secret") is True
    assert _value_contains("SuperSecret123", "absent") is False


def test_value_contains_matches_base64_encoded_values():
    # "hunter2-password" stored via the portal's encode-as-Base64 option.
    assert _value_contains("aHVudGVyMi1wYXNzd29yZA==", "hunter2") is True


def test_value_contains_ignores_empty_values():
    assert _value_contains("", "anything") is False


# ── Service: name scope ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_name_scope_matches_names_without_reading_values():
    service = _service_with({"db-password": "abc", "api-key": "xyz"})

    result = await service.search_secrets(VAULT, "pass")

    assert result["scope"] == "name"
    assert [r["name"] for r in result["results"]] == ["db-password"]
    assert result["results"][0]["matched_in"] == ["name"]
    assert result["scanned"] == 0
    assert service.value_reads == []


# ── Service: value scope ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_value_scope_matches_on_value_case_insensitively():
    service = _service_with({"api-key": "AKIA-PROD-TOKEN", "unrelated": "nothing"})

    result = await service.search_secrets(VAULT, "prod-token", include_values=True)

    assert result["scope"] == "name_and_value"
    assert [r["name"] for r in result["results"]] == ["api-key"]
    assert result["results"][0]["matched_in"] == ["value"]
    assert result["scanned"] == 2


@pytest.mark.asyncio
async def test_value_scope_reports_matches_on_both_name_and_value():
    service = _service_with({"prod-token": "prod-token-value", "other": "x"})

    result = await service.search_secrets(VAULT, "prod-token", include_values=True)

    assert result["results"][0]["matched_in"] == ["name", "value"]


@pytest.mark.asyncio
async def test_value_scope_never_returns_secret_values():
    service = _service_with({"api-key": "match-me"})

    result = await service.search_secrets(VAULT, "match-me", include_values=True)

    assert result["results"], "expected a match to assert on"
    for entry in result["results"]:
        assert "value" not in entry
        assert "match-me" not in str({k: v for k, v in entry.items() if k != "matched_in"})


@pytest.mark.asyncio
async def test_value_scope_skips_disabled_secrets():
    service = _service_with(
        {"live": "needle", "retired": "needle"},
        listed=[_secret("live"), _secret("retired", enabled=False)],
    )

    result = await service.search_secrets(VAULT, "needle", include_values=True)

    assert [r["name"] for r in result["results"]] == ["live"]
    assert result["skipped_disabled"] == 1
    assert service.value_reads == ["live"]


@pytest.mark.asyncio
async def test_value_scope_counts_unreadable_secrets_without_failing():
    service = _service_with({"readable": "needle", "forbidden": None})

    result = await service.search_secrets(VAULT, "needle", include_values=True)

    assert [r["name"] for r in result["results"]] == ["readable"]
    assert result["unreadable"] == 1


@pytest.mark.asyncio
async def test_blank_query_returns_no_matches_and_reads_nothing():
    service = _service_with({"api-key": "abc"})

    result = await service.search_secrets(VAULT, "   ", include_values=True)

    assert result["results"] == []
    assert service.value_reads == []


# ── Endpoint ───────────────────────────────────────────────────────────


@pytest.fixture
def no_dev_bypass():
    """Pin the dev auth bypass off so role checks actually run."""
    original_env, original_bypass = settings.ENVIRONMENT, settings.DEV_AUTH_BYPASS
    settings.ENVIRONMENT, settings.DEV_AUTH_BYPASS = "production", False
    yield
    settings.ENVIRONMENT, settings.DEV_AUTH_BYPASS = original_env, original_bypass


@pytest.mark.asyncio
async def test_value_search_is_forbidden_for_read_only_users(app, db_session, no_dev_bypass):
    service = _service_with({"api-key": "needle"})

    async def _get_db_override():
        yield db_session

    app.dependency_overrides[get_db] = _get_db_override
    app.dependency_overrides[get_current_user] = make_read_user
    app.dependency_overrides[_get_kv_service] = lambda: service

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            "/api/v1/keyvault/secrets/search",
            params={"vault_uri": VAULT, "q": "needle", "scope": "name_and_value"},
        )

    app.dependency_overrides.clear()
    assert response.status_code == 403
    assert service.value_reads == []


@pytest.mark.asyncio
async def test_name_search_is_allowed_for_read_only_users(reader_client, app, no_dev_bypass):
    service = _service_with({"api-key": "needle"})
    app.dependency_overrides[_get_kv_service] = lambda: service

    response = await reader_client.get(
        "/api/v1/keyvault/secrets/search",
        params={"vault_uri": VAULT, "q": "api", "scope": "name"},
    )

    assert response.status_code == 200
    assert [r["name"] for r in response.json()["results"]] == ["api-key"]


@pytest.mark.asyncio
async def test_search_route_is_not_captured_by_the_secret_name_route(admin_client, app):
    """``/secrets/search`` must reach the search handler, not ``/secrets/{name}``."""
    service = _service_with({"api-key": "needle"})
    app.dependency_overrides[_get_kv_service] = lambda: service

    response = await admin_client.get(
        "/api/v1/keyvault/secrets/search",
        params={"vault_uri": VAULT, "q": "api", "scope": "name"},
    )

    assert response.status_code == 200
    assert "results" in response.json()


@pytest.mark.asyncio
async def test_value_search_rejects_terms_that_are_too_short(admin_client, app):
    service = _service_with({"api-key": "needle"})
    app.dependency_overrides[_get_kv_service] = lambda: service

    response = await admin_client.get(
        "/api/v1/keyvault/secrets/search",
        params={"vault_uri": VAULT, "q": "ab", "scope": "name_and_value"},
    )

    assert response.status_code == 400
    assert service.value_reads == []


@pytest.mark.asyncio
async def test_value_search_audits_the_scan_without_storing_the_term(admin_client, app, db_session):
    service = _service_with({"api-key": "needle-value"})
    app.dependency_overrides[_get_kv_service] = lambda: service

    response = await admin_client.get(
        "/api/v1/keyvault/secrets/search",
        params={"vault_uri": VAULT, "q": "needle-value", "scope": "name_and_value"},
    )
    assert response.status_code == 200

    rows = (
        await db_session.execute(
            text("SELECT action, resource_id, details FROM audit_logs WHERE action = 'search_secret_values'")
        )
    ).all()

    assert len(rows) == 1
    _action, resource_id, details = rows[0]
    assert resource_id == "demo-kv"
    assert "needle-value" not in details
    assert '"query_length": 12' in details
    assert '"matched_count": 1' in details
