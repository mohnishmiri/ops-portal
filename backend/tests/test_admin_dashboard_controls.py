"""Admin dashboard controls: health probe, config validation and audit trail,
subscription edit/delete, rate limiting shared across workers, and the
page-cache toggle for advisor payloads."""

from collections import defaultdict
from types import SimpleNamespace

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError
from sqlalchemy import select
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route

from app.api.v1.endpoints.admin import AddSubscriptionRequest, UpdateSubscriptionRequest
from app.core.config import settings
from app.middleware import rate_limit
from app.models.database import AdminSubscription, AuditLog
from app.services import admin_service
from app.services.admin_service import AdminService
from app.services.dashboard_service import DashboardService
from app.services.leadership_advisor_service import LeadershipAdvisorService

SUB_ID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"


async def _audit_rows(db_session) -> list[AuditLog]:  # noqa: ANN001
    return list((await db_session.execute(select(AuditLog).order_by(AuditLog.id))).scalars().all())


# ── Request models ────────────────────────────────────────────────────


def test_add_subscription_normalises_guid_and_allows_blank_name() -> None:
    body = AddSubscriptionRequest(subscription_id="  AAAAAAAA-BBBB-CCCC-DDDD-EEEEEEEEEEEE ")

    assert body.subscription_id == SUB_ID
    assert body.subscription_name is None


def test_add_subscription_rejects_non_guid() -> None:
    with pytest.raises(ValidationError, match="subscription GUID"):
        AddSubscriptionRequest(subscription_id="ACC-PROD-31599-ATTCC")


def test_update_subscription_rejects_blank_name() -> None:
    with pytest.raises(ValidationError, match="cannot be blank"):
        UpdateSubscriptionRequest(subscription_name="   ")


# ── Config validation and audit ───────────────────────────────────────


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("cache_ttl_seconds", "abc"),
        ("cache_ttl_seconds", "30"),
        ("cache_ttl_seconds", "604801"),
        ("portal_timezone", "India Standard Time"),
        ("smtp_password", "hunter2"),
    ],
)
async def test_config_rejects_invalid_values_and_unknown_keys(admin_client, key: str, value: str) -> None:  # noqa: ANN001
    response = await admin_client.put("/api/v1/admin/config", json={"config_key": key, "config_value": value})
    assert response.status_code == 400


async def test_config_change_is_audited_with_old_and_new_value(admin_client, db_session) -> None:  # noqa: ANN001
    for value in ("120", "120", "300"):
        response = await admin_client.put(
            "/api/v1/admin/config", json={"config_key": "cache_ttl_seconds", "config_value": value}
        )
        assert response.status_code == 200

    rows = await _audit_rows(db_session)
    # Saving the same value twice records one change, not two.
    assert [row.details["new_value"] for row in rows] == ["120", "300"]
    assert rows[1].action == "admin_config_update"
    assert rows[1].resource_id == "cache_ttl_seconds"
    assert rows[1].details["old_value"] == "120"
    assert rows[1].user_email == "admin@example.com"

    tz = await admin_client.put(
        "/api/v1/admin/config", json={"config_key": "portal_timezone", "config_value": " Asia/Kolkata "}
    )
    assert tz.json()["config_value"] == "Asia/Kolkata"


# ── Subscription add / edit / delete ──────────────────────────────────


async def test_subscription_lifecycle_is_audited_and_listed(admin_client, db_session) -> None:  # noqa: ANN001
    added = await admin_client.post("/api/v1/admin/subscriptions", json={"subscription_id": SUB_ID.upper()})
    assert added.status_code == 201
    assert added.json()["subscription_name"] == SUB_ID  # blank name defaults to the ID

    edited = await admin_client.put(
        f"/api/v1/admin/subscriptions/{SUB_ID}",
        json={"subscription_name": "ACC-NPRD-31599-ATTCC", "environment": "development", "notes": ""},
    )
    assert edited.status_code == 200
    assert edited.json()["changes"] == {
        "subscription_name": [SUB_ID, "ACC-NPRD-31599-ATTCC"],
        "environment": [None, "development"],
    }

    # Clearing Environment stores NULL rather than "".
    await admin_client.put(f"/api/v1/admin/subscriptions/{SUB_ID}", json={"environment": ""})
    row = (await db_session.execute(select(AdminSubscription))).scalar_one()
    assert row.environment is None

    deleted = await admin_client.delete(f"/api/v1/admin/subscriptions/{SUB_ID}")
    assert deleted.json() == {"subscription_id": SUB_ID, "subscription_name": "ACC-NPRD-31599-ATTCC", "removed": True}

    activity = (await admin_client.get("/api/v1/admin/audit")).json()
    assert [entry["action"] for entry in activity] == [
        "admin_subscription_delete",
        "admin_subscription_update",
        "admin_subscription_update",
        "admin_subscription_add",
    ]
    assert activity[0]["summary"] == "Removed subscription ACC-NPRD-31599-ATTCC"
    assert activity[2]["summary"] == "Edited subscription_name, environment on ACC-NPRD-31599-ATTCC"


async def test_unchanged_edit_writes_no_audit(admin_client, db_session) -> None:  # noqa: ANN001
    await admin_client.post("/api/v1/admin/subscriptions", json={"subscription_id": SUB_ID, "subscription_name": "X"})
    response = await admin_client.put(f"/api/v1/admin/subscriptions/{SUB_ID}", json={"subscription_name": "X"})

    assert response.json()["changes"] == {}
    assert [row.action for row in await _audit_rows(db_session)] == ["admin_subscription_add"]


async def test_admin_activity_is_super_admin_only(reader_client, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: ANN001
    # The local .env may turn on the dev bypass, which skips role checks.
    monkeypatch.setattr(settings, "DEV_AUTH_BYPASS", False)
    assert (await reader_client.get("/api/v1/admin/audit")).status_code == 403


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


async def test_admin_dashboard_reports_probe_and_cost_classification(
    monkeypatch: pytest.MonkeyPatch,
    fresh_probe,  # noqa: ANN001, ARG001
) -> None:
    async def unreachable(_self) -> bool:
        return False

    async def ping() -> bool:
        return True

    monkeypatch.setattr(AdminService, "check_azure_api", unreachable)
    monkeypatch.setattr("app.services.dashboard_service.cache_manager.ping", ping)

    service = DashboardService.__new__(DashboardService)
    payload = await service.get_admin_dashboard(db=None)

    assert payload["system_health"]["api"] == "unreachable"
    options = {option["value"]: option["cost_env"] for option in payload["environment_options"]}
    assert options["production"] == "Prod"
    assert options["development"] == "Non-Prod"


# ── Rate limiting shared across workers ───────────────────────────────


def _limited_app(rpm: int) -> Starlette:
    async def ok(_request):  # noqa: ANN001
        return JSONResponse({"ok": True})

    app = Starlette(routes=[Route("/x", ok)])
    app.add_middleware(rate_limit.RateLimitMiddleware, requests_per_minute=rpm)
    return app


def _shared_table(seed: dict | None = None):
    """Stand-in for rate_limit_windows: adds each batch, returns cumulative totals like RETURNING."""
    store: dict = defaultdict(int, seed or {})

    async def flush(batch, *, prune_before):  # noqa: ANN001, ARG001
        for key, count in batch.items():
            store[key] += count
        return {key: store[key] for key in batch}

    return flush, store


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch):
    """A controllable wall clock, 10 s into a minute, with flushing on every request."""
    now = {"t": 60_000.0 * 60 + 10}
    monkeypatch.setattr(rate_limit, "_wall_clock", lambda: now["t"])
    monkeypatch.setattr(rate_limit, "_FLUSH_SECONDS", 0.0)
    monkeypatch.setattr(rate_limit, "_admin_rpm_override", None)
    return now


async def test_other_workers_traffic_counts_toward_the_limit(monkeypatch: pytest.MonkeyPatch, clock) -> None:  # noqa: ANN001
    window = int(clock["t"] // 60)
    # Other workers have already served this client 9 requests this minute.
    flush, store = _shared_table({(window, "127.0.0.1"): 9})
    monkeypatch.setattr(rate_limit, "_flush_counts", flush)

    async with AsyncClient(transport=ASGITransport(app=_limited_app(10)), base_url="http://test") as client:
        assert (await client.get("/x")).status_code == 200  # 0 known + 1 local; flush learns the total is 10
        assert (await client.get("/x")).status_code == 429  # 10 shared + 1 local > 10

    assert store[(window, "127.0.0.1")] == 11


async def test_falls_back_to_local_counts_when_db_is_down(monkeypatch: pytest.MonkeyPatch, clock) -> None:  # noqa: ANN001, ARG001
    async def failing_flush(batch, *, prune_before):  # noqa: ANN001, ARG001
        raise RuntimeError("Database not connected")

    monkeypatch.setattr(rate_limit, "_flush_counts", failing_flush)

    async with AsyncClient(transport=ASGITransport(app=_limited_app(3)), base_url="http://test") as client:
        statuses = [(await client.get("/x")).status_code for _ in range(4)]

    assert statuses == [200, 200, 200, 429]


async def test_previous_minute_is_weighted_by_overlap(monkeypatch: pytest.MonkeyPatch, clock) -> None:  # noqa: ANN001
    monkeypatch.setattr(rate_limit, "_flush_counts", _shared_table()[0])

    async with AsyncClient(transport=ASGITransport(app=_limited_app(4)), base_url="http://test") as client:
        for _ in range(4):
            assert (await client.get("/x")).status_code == 200
        # 15 s into the next minute, 3/4 of the previous minute still counts:
        # 0.75 x 4 + 1 = 4 is allowed, 0.75 x 4 + 2 = 5 is not.
        clock["t"] += 65
        assert (await client.get("/x")).status_code == 200
        assert (await client.get("/x")).status_code == 429


def test_flush_statement_adds_to_shared_counts_in_key_order() -> None:
    from sqlalchemy.dialects import postgresql

    stmt = rate_limit._upsert_statement({(2, "10.0.0.9"): 3, (1, "10.0.0.9"): 1, (2, "10.0.0.1"): 5})
    compiled = stmt.compile(dialect=postgresql.dialect())
    sql = str(compiled)

    assert "ON CONFLICT (client_ip, window_start) DO UPDATE" in sql
    assert "rate_limit_windows.request_count + excluded.request_count" in sql
    assert "RETURNING" in sql
    rows = [(compiled.params[f"client_ip_m{i}"], compiled.params[f"request_count_m{i}"]) for i in range(3)]
    assert rows == [("10.0.0.9", 1), ("10.0.0.1", 5), ("10.0.0.9", 3)]


async def test_rate_limit_override_refreshes_from_db(monkeypatch: pytest.MonkeyPatch, clock) -> None:  # noqa: ANN001, ARG001
    async def fake_get_db_session():
        yield object()

    async def fake_config_value(_db, key, default=None):  # noqa: ANN001
        return "25" if key == "rate_limit_rpm" else default

    monkeypatch.setattr(rate_limit, "get_db_session", fake_get_db_session)
    monkeypatch.setattr(rate_limit, "get_admin_config_value", fake_config_value)
    monkeypatch.setattr(rate_limit, "_flush_counts", _shared_table()[0])
    monkeypatch.setattr(rate_limit, "_admin_rpm_override", 10000)
    monkeypatch.setattr(rate_limit, "_OVERRIDE_REFRESH_SECONDS", 0.0)

    async with AsyncClient(transport=ASGITransport(app=_limited_app(120)), base_url="http://test") as client:
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
