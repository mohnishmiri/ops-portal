"""Tests for /sync-jobs endpoints and the SyncWorker enqueue/idempotency path."""

from __future__ import annotations

import json
from datetime import datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient

from app.auth import get_current_user
from app.core.database import get_db
from app.main import create_application
from app.models.database import SyncJob
from app.schemas.auth import UserContext, UserRole


@pytest.fixture
def app():
    return create_application()


@pytest.fixture
async def client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


def _user() -> UserContext:
    return UserContext(
        user_id="test-user",
        object_id="test-object",
        display_name="Test User",
        email="test@example.com",
        roles=[UserRole.ADMIN],
        raw_roles=["admin"],
        tenant_id="tenant-id",
        allowed_subscriptions=[],
    )


class _FakeScalars:
    def __init__(self, value):
        self._value = value

    def first(self):
        return self._value

    def all(self):
        if self._value is None:
            return []
        return self._value if isinstance(self._value, list) else [self._value]


class _FakeResult:
    def __init__(self, value):
        self._value = value

    def scalars(self):
        return _FakeScalars(self._value)


class _FakeSession:
    """Mimics AsyncSession.execute returning queued FakeResults."""

    def __init__(self, execute_results: list | None = None) -> None:
        self._results = list(execute_results or [])
        self.added: list = []
        self.committed = False

    async def execute(self, *_args, **_kwargs):
        if self._results:
            return _FakeResult(self._results.pop(0))
        return _FakeResult(None)

    def add(self, obj):
        self.added.append(obj)

    async def commit(self):
        self.committed = True

    async def refresh(self, obj):
        if getattr(obj, "id", None) is None:
            obj.id = 99


@pytest.mark.anyio
async def test_enqueue_amortized_returns_202_with_job_id(app, client, monkeypatch):
    """POST /sync-jobs returns 202 + a job_id; underlying enqueue is invoked."""
    captured: dict = {}

    async def fake_enqueue(job_type, *, payload=None, triggered_by=None, idempotency_key=None, dedup_session=None):
        captured["job_type"] = job_type
        captured["payload"] = payload
        captured["idempotency_key"] = idempotency_key
        captured["triggered_by"] = triggered_by
        return 7

    fake_db = _FakeSession(
        execute_results=[
            None,  # initial idempotency lookup (no key → won't even run, but stays safe)
            SyncJob(
                id=7,
                job_type="amortized",
                status="queued",
                idempotency_key=None,
                payload="{}",
                triggered_by="test@example.com",
                attempts=0,
                enqueued_at=datetime.utcnow(),
            ),
        ]
    )

    async def fake_get_db():
        yield fake_db

    app.dependency_overrides[get_current_user] = lambda: _user()
    app.dependency_overrides[get_db] = fake_get_db
    monkeypatch.setattr("app.api.v1.endpoints.sync_jobs.enqueue_job", fake_enqueue)

    resp = await client.post("/api/v1/sync-jobs", json={"job_type": "amortized", "months": 3, "force": True})

    assert resp.status_code == 202
    body = resp.json()
    assert body["job_id"] == 7
    assert body["job_type"] == "amortized"
    assert body["reused"] is False
    assert captured["payload"] == {"months": 3, "force": True}
    assert captured["triggered_by"] == "test@example.com"

    app.dependency_overrides.clear()


@pytest.mark.anyio
async def test_enqueue_rejects_unknown_job_type(app, client):
    async def fake_get_db():
        yield _FakeSession()

    app.dependency_overrides[get_current_user] = lambda: _user()
    app.dependency_overrides[get_db] = fake_get_db

    resp = await client.post("/api/v1/sync-jobs", json={"job_type": "bogus"})
    assert resp.status_code == 400
    assert "Unsupported job_type" in resp.json()["detail"]

    app.dependency_overrides.clear()


@pytest.mark.anyio
async def test_get_sync_job_returns_detail(app, client):
    job = SyncJob(
        id=42,
        job_type="leadership",
        status="completed",
        idempotency_key="abc",
        payload=None,
        triggered_by="test@example.com",
        attempts=1,
        last_error=None,
        result=json.dumps({"status": "completed", "rows_synced": 10}),
        enqueued_at=datetime.utcnow() - timedelta(seconds=30),
        started_at=datetime.utcnow() - timedelta(seconds=25),
        completed_at=datetime.utcnow(),
    )

    fake_db = _FakeSession(execute_results=[job])

    async def fake_get_db():
        yield fake_db

    app.dependency_overrides[get_current_user] = lambda: _user()
    app.dependency_overrides[get_db] = fake_get_db

    resp = await client.get("/api/v1/sync-jobs/42")
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == 42
    assert body["status"] == "completed"
    assert body["result"] == {"status": "completed", "rows_synced": 10}
    assert body["attempts"] == 1

    app.dependency_overrides.clear()


@pytest.mark.anyio
async def test_get_sync_job_404_when_missing(app, client):
    fake_db = _FakeSession(execute_results=[None])

    async def fake_get_db():
        yield fake_db

    app.dependency_overrides[get_current_user] = lambda: _user()
    app.dependency_overrides[get_db] = fake_get_db

    resp = await client.get("/api/v1/sync-jobs/999")
    assert resp.status_code == 404

    app.dependency_overrides.clear()
