"""Tests for Key Vault secret search by name and by value.

Value search reads every secret in the vault, so the cases below pin the
three things that make that safe: values never leave the service, the scan
is role-gated, and the audit trail records the search without the term.
"""

import asyncio
import base64

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from app.api.v1.endpoints.keyvault import _get_kv_service
from app.auth import get_current_user
from app.core.config import settings
from app.core.database import get_db
from app.services import keyvault_service
from app.services.keyvault_service import KeyVaultService, _match_kind

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

    # The viewer reads one secret through _vault_get; the scan reads in bulk
    # through _read_secret_value over a pooled async client. Both are backed
    # by the same map so the two paths cannot drift apart.
    async def _vault_get(url, *, token=None):
        name = url.split("/secrets/")[1].split("?")[0]
        value = values.get(name)
        if value is None:
            raise RuntimeError("HTTP Error 403: Forbidden")
        return {"value": value}

    async def _read_secret_value(client, vault_uri, name, token):
        service.value_reads.append(name)
        value = values.get(name)
        if value is None:
            return None, "HTTP Error 403: Forbidden"
        return value, None

    service.list_secrets = _list_secrets
    service._get_vault_token = _get_vault_token
    service._vault_get = _vault_get
    service._read_secret_value = _read_secret_value
    return service


# ── Value matching ─────────────────────────────────────────────────────


PLAIN = "hunter2-password"
B64 = base64.b64encode(PLAIN.encode()).decode()


def test_match_kind_matches_raw_value_case_insensitively():
    assert _match_kind("SuperSecret123", "secret") == "value"
    assert _match_kind("SuperSecret123", "absent") is None


def test_match_kind_ignores_empty_values():
    assert _match_kind("", "anything") is None


# Vaults hold Base64 in whatever shape produced it — a shell pipeline, an SDK,
# a Windows tool, the portal's own encode option. Every one of these has to
# find the plaintext the user actually searches for.
@pytest.mark.parametrize(
    ("label", "stored"),
    [
        ("clean and padded", B64),
        ("trailing newline", B64 + "\n"),
        ("surrounding whitespace", f"  {B64}  "),
        ("line wrapped", "\n".join(B64[i : i + 8] for i in range(0, len(B64), 8))),
        ("unpadded", B64.rstrip("=")),
        ("url-safe alphabet", base64.urlsafe_b64encode(f"??>{PLAIN}".encode()).decode()),
        ("utf-16 payload", base64.b64encode(PLAIN.encode("utf-16")).decode()),
        ("utf-16-le without bom", base64.b64encode(PLAIN.encode("utf-16-le")).decode()),
        ("encoded twice", base64.b64encode(B64.encode()).decode()),
        ("wraps a properties file", base64.b64encode(f"db.pass={PLAIN}\n".encode()).decode()),
    ],
)
def test_match_kind_decodes_every_base64_shape(label, stored):
    assert _match_kind(stored, "hunter2") == "value_base64", label


@pytest.mark.parametrize(
    ("label", "stored"),
    [
        ("unrelated plaintext", "totally-different-value"),
        ("unrelated base64", base64.b64encode(b"nothing to see here at all").decode()),
        ("binary blob", base64.b64encode(bytes(range(256)) * 2).decode()),
        ("too short to be base64", "ab"),
    ],
)
def test_match_kind_does_not_invent_matches(label, stored):
    assert _match_kind(stored, "hunter2") is None, label


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
async def test_search_is_scoped_to_the_selected_vault():
    """The scan covers the chosen vault only — never other vaults in the tenant."""
    service = _service_with({"api-key": "needle"})
    listed_for: list[str] = []
    read_vaults: list[str] = []

    async def _list_secrets(vault_uri, search=None, *, refresh=False):
        listed_for.append(vault_uri)
        return [_secret("api-key")]

    async def _read_secret_value(client, vault_uri, name, token):
        read_vaults.append(vault_uri)
        return "needle", None

    service.list_secrets = _list_secrets
    service._read_secret_value = _read_secret_value

    # Passed without the trailing slash to prove normalization, not re-scoping.
    await service.search_secrets("https://demo-kv.vault.azure.net", "needle", include_values=True)

    assert listed_for == [VAULT]
    assert read_vaults == [VAULT], read_vaults


@pytest.mark.asyncio
async def test_value_scope_finds_secrets_stored_base64_encoded():
    service = _service_with({"db-password": B64 + "\n", "unrelated": "nothing"})

    result = await service.search_secrets(VAULT, "hunter2", include_values=True)

    assert [r["name"] for r in result["results"]] == ["db-password"]
    assert result["results"][0]["matched_in"] == ["value_base64"]
    assert result["base64_matches"] == 1


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
async def test_a_vault_it_can_list_but_not_read_reports_why():
    """List-but-no-Get must explain itself, not look like a search with no hits."""
    service = _service_with({"one": None, "two": None})

    result = await service.search_secrets(VAULT, "needle", include_values=True)

    assert result["results"] == []
    assert result["unreadable"] == result["scanned"] == 2
    assert "403" in result["read_error"]


@pytest.mark.asyncio
async def test_blank_query_returns_no_matches_and_reads_nothing():
    service = _service_with({"api-key": "abc"})

    result = await service.search_secrets(VAULT, "   ", include_values=True)

    assert result["results"] == []
    assert service.value_reads == []


@pytest.mark.asyncio
async def test_slow_vault_returns_partial_results_instead_of_failing(monkeypatch):
    """A scan that outruns its budget still answers — an error banner helps nobody."""
    monkeypatch.setattr(keyvault_service, "_VALUE_SEARCH_TIMEOUT", 0.2)

    service = _service_with({"fast": "needle", "slow": "needle"})
    original = service._read_secret_value

    async def _slow_for_one(client, vault_uri, name, token):
        if name == "slow":
            await asyncio.sleep(5)
        return await original(client, vault_uri, name, token)

    service._read_secret_value = _slow_for_one

    result = await service.search_secrets(VAULT, "needle", include_values=True)

    assert result["timed_out"] is True
    assert result["scanned"] == 1, "only the read that finished counts as scanned"
    assert [r["name"] for r in result["results"]] == ["fast"]


@pytest.mark.asyncio
async def test_a_slow_vault_listing_cannot_blow_the_budget(monkeypatch):
    """Listing shares the budget — otherwise the client times out before we answer."""
    monkeypatch.setattr(keyvault_service, "_VALUE_SEARCH_TIMEOUT", 0.3)
    service = _service_with({"api-key": "needle"})

    async def _slow_list(vault_uri, search=None, *, refresh=False):
        await asyncio.sleep(5)
        return [_secret("api-key")]

    service.list_secrets = _slow_list

    started = asyncio.get_running_loop().time()
    with pytest.raises(RuntimeError, match="took longer than"):
        await service.search_secrets(VAULT, "needle", include_values=True)

    assert asyncio.get_running_loop().time() - started < 3, "must give up, not wait out the list"


@pytest.mark.asyncio
async def test_listing_time_is_deducted_from_the_scan_budget(monkeypatch):
    """A slow list leaves less scan time, and the answer is still partial-but-prompt."""
    monkeypatch.setattr(keyvault_service, "_VALUE_SEARCH_TIMEOUT", 1.0)
    service = _service_with({"api-key": "needle", "other": "needle"})
    original_list = service.list_secrets

    async def _slowish_list(vault_uri, search=None, *, refresh=False):
        await asyncio.sleep(0.9)
        return await original_list(vault_uri, search, refresh=refresh)

    original_read = service._read_secret_value

    async def _slow_read(client, vault_uri, name, token):
        await asyncio.sleep(1)
        return await original_read(client, vault_uri, name, token)

    service.list_secrets = _slowish_list
    service._read_secret_value = _slow_read

    started = asyncio.get_running_loop().time()
    result = await service.search_secrets(VAULT, "needle", include_values=True)
    elapsed = asyncio.get_running_loop().time() - started

    assert result["timed_out"] is True
    assert elapsed < 2.5, f"answered in {elapsed:.1f}s; the budget must span both phases"


@pytest.mark.asyncio
async def test_completed_scan_is_not_marked_partial():
    service = _service_with({"api-key": "needle"})

    result = await service.search_secrets(VAULT, "needle", include_values=True)

    assert result["timed_out"] is False
    assert result["scanned"] == 1


@pytest.mark.asyncio
async def test_search_accepts_a_prefetched_secret_list():
    """The endpoint passes the synced snapshot so a scan skips re-listing the vault."""
    service = _service_with({"api-key": "needle"})

    async def _fail(*args, **kwargs):
        raise AssertionError("list_secrets must not be called when secrets are supplied")

    service.list_secrets = _fail

    result = await service.search_secrets(VAULT, "needle", include_values=True, secrets=[_secret("api-key")])

    assert [r["name"] for r in result["results"]] == ["api-key"]


# ── Value viewer stays consistent with search ──────────────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("label", "stored"),
    [
        ("clean and padded", B64),
        ("unpadded", B64.rstrip("=")),
        ("url-safe alphabet", base64.urlsafe_b64encode(f"??>{PLAIN}".encode()).decode()),
        ("utf-16 payload", base64.b64encode(PLAIN.encode("utf-16")).decode()),
    ],
)
async def test_viewer_decodes_what_search_flags_as_base64(label, stored):
    """A "base64 match" in the grid must show its plaintext when opened."""
    service = _service_with({"api-key": stored})

    assert _match_kind(stored, "hunter2") == "value_base64", label
    detail = await service.get_secret_value(VAULT, "api-key")

    assert detail["is_base64"] is True, label
    assert "hunter2" in detail["decoded_value"], label


@pytest.mark.asyncio
async def test_viewer_does_not_claim_plaintext_is_base64():
    service = _service_with({"api-key": "just-a-plain-password"})

    detail = await service.get_secret_value(VAULT, "api-key")

    assert detail["is_base64"] is False
    assert detail["decoded_value"] is None


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
async def test_a_stalled_vault_returns_an_explanation_not_a_client_timeout(admin_client, app, monkeypatch):
    """The whole chain: a vault too slow to list must answer with a usable reason."""
    monkeypatch.setattr(keyvault_service, "_VALUE_SEARCH_TIMEOUT", 0.3)
    service = _service_with({"api-key": "needle"})

    async def _stalled_list(vault_uri, search=None, *, refresh=False):
        await asyncio.sleep(30)
        return []

    service.list_secrets = _stalled_list
    app.dependency_overrides[_get_kv_service] = lambda: service

    started = asyncio.get_running_loop().time()
    response = await admin_client.get(
        "/api/v1/keyvault/secrets/search",
        params={"vault_uri": VAULT, "q": "needle", "scope": "name_and_value"},
    )
    elapsed = asyncio.get_running_loop().time() - started

    assert response.status_code == 502
    # The message has to survive _friendly_error untouched to be actionable.
    assert "took longer than" in response.json()["detail"]
    assert "Search: Name" in response.json()["detail"]
    assert elapsed < 5, f"answered in {elapsed:.1f}s; must not wait out the stalled list"


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
