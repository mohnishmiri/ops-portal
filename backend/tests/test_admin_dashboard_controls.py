"""Admin dashboard controls: health probe, config validation, rate-limit
propagation across workers, and the page-cache toggle for advisor payloads."""

from collections import defaultdict
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route

from app.api.v1.endpoints import admin as admin_endpoints
from app.api.v1.endpoints.admin import AddSubscriptionRequest, UpsertConfigRequest
from app.middleware import rate_limit
from app.services import admin_service
from app.services.admin_service import AdminService
from app.services.dashboard_service import DashboardService
from app.services.leadership_advisor_service import LeadershipAdvisorService

# ── Add subscription request ──────────────────────────────────────────


def test_add_subscription_normalises_guid_and_allows_blank_name() -> None:
    body = AddSubscriptionRequest(subscription_id="  AAAAAAAA-BBBB-CCCC-DDDD-EEEEEEEEEEEE ")

    assert body.subscription_id == "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    assert body.subscription_name is None


def test_add_subscription_rejects_non_guid() -> None:
    with pytest.raises(ValidationError, match="subscription GUID"):
        AddSubscriptionRequest(subscription_id="ACC-PROD-31599-ATTCC")


# ── Config validation ─────────────────────────────────────────────────


class _RecordingService:
    def __init__(self) -> None:
        self.saved: list[dict] = []

    async def upsert_admin_config(self, key, value, *, config_type, description, updated_by):  # noqa: ANN001
        self.saved.append({"key": key, "value": value, "config_type": config_type})
        return {"config_key": key, "config_value": value}


_ADMIN = SimpleNamespace(email="admin@example.com", display_name="Admin")


async def _upsert(key: str, value: str) -> _RecordingService:
    service = _RecordingService()
    await admin_endpoints.upsert_admin_config(
        UpsertConfigRequest(config_key=key, config_value=value),
        user=_ADMIN,
        service=service,
        db=None,
    )
    return service


@pytest.mark.parametrize("value", ["abc", "-60", "30", "604801"])
async def test_cache_ttl_rejects_values_outside_contract(value: str) -> None:
    with pytest.raises(HTTPException) as exc:
        await _upsert("cache_ttl_seconds", value)
    assert exc.value.status_code == 400


@pytest.mark.parametrize("value", ["0", "60", "604800"])
async def test_cache_ttl_accepts_unlimited_and_bounds(value: str) -> None:
    service = await _upsert("cache_ttl_seconds", value)
    assert service.saved == [{"key": "cache_ttl_seconds", "value": value, "config_type": "integer"}]


async def test_portal_timezone_must_be_iana() -> None:
    with pytest.raises(HTTPException) as exc:
        await _upsert("portal_timezone", "India Standard Time")
    assert exc.value.status_code == 400

    service = await _upsert("portal_timezone", " Asia/Kolkata ")
    assert service.saved[0]["value"] == "Asia/Kolkata"


# ── Azure health probe ────────────────────────────────────────────────


@pytest.fixture
def fresh_probe(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(admin_service, "_azure_probe_result", None)
    monkeypatch.setattr(admin_service, "get_azure_credential", lambda: None)


async def test_azure_probe_reports_failure_and_is_memoised(fresh_probe) -> None:  # noqa: ANN001, ARG001
    calls = 0

    class _FailingCredential:
        def get_token(self, *_args):
            nonlocal calls
            calls += 1
            raise RuntimeError("AADSTS7000215: invalid client secret")

    service = AdminService(db=None)
    service._credential = _FailingCredential()

    assert await service.check_azure_api() is False
    assert await service.check_azure_api() is False
    assert calls == 1


async def test_admin_dashboard_api_status_follows_probe(monkeypatch: pytest.MonkeyPatch, fresh_probe) -> None:  # noqa: ANN001, ARG001
    async def unreachable(_self) -> bool:
        return False

    async def ping() -> bool:
        return True

    monkeypatch.setattr(AdminService, "check_azure_api", unreachable)
    monkeypatch.setattr("app.services.dashboard_service.cache_manager.ping", ping)

    service = DashboardService.__new__(DashboardService)
    payload = await service.get_admin_dashboard(db=None)

    assert payload["system_health"]["api"] == "unreachable"


# ── Rate limit override reaches every worker ──────────────────────────


async def test_rate_limit_override_refreshes_from_db(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_get_db_session():
        yield object()

    async def fake_config_value(_db, key, default=None):  # noqa: ANN001
        return "25" if key == "rate_limit_rpm" else default

    monkeypatch.setattr(rate_limit, "get_db_session", fake_get_db_session)
    monkeypatch.setattr(rate_limit, "get_admin_config_value", fake_config_value)
    monkeypatch.setattr(rate_limit, "_admin_rpm_override", 10000)
    monkeypatch.setattr(rate_limit, "_OVERRIDE_REFRESH_SECONDS", 0.0)
    # Earlier tests share this process-wide log; start clean so 25 rpm isn't already spent.
    monkeypatch.setattr(rate_limit, "_request_log", defaultdict(list))

    async def ok(_request):  # noqa: ANN001
        return JSONResponse({"ok": True})

    app = Starlette(routes=[Route("/x", ok)])
    app.add_middleware(rate_limit.RateLimitMiddleware, requests_per_minute=120)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        assert (await client.get("/x")).status_code == 200

    # Another worker saved 25 rpm; this worker picked it up from the DB.
    assert rate_limit.get_rate_limit_override() == 25


# ── Page cache toggle covers advisor / forecast ───────────────────────


async def test_advisor_cache_bypassed_when_page_cache_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    touched: list[str] = []

    async def disabled(_db) -> bool:  # noqa: ANN001
        return False

    async def get_cached(key: str):
        touched.append(f"get:{key}")
        return "{}"

    async def set_cached(key: str, *_args, **_kwargs):
        touched.append(f"set:{key}")

    monkeypatch.setattr("app.services.leadership_advisor_service.get_cache_enabled", disabled)
    monkeypatch.setattr("app.services.leadership_advisor_service.cache_manager.get_cached", get_cached)
    monkeypatch.setattr("app.services.leadership_advisor_service.cache_manager.set_cached", set_cached)

    service = LeadershipAdvisorService(db=None)
    assert await service._get_cached("pagecache:leadership:advisor:2026-10-01") is None
    await service._cache_model("pagecache:leadership:advisor:2026-10-01", SimpleNamespace(model_dump_json=lambda: "{}"))

    assert touched == []
