"""
Tests for the Jobs API and the CronJob → Job integration.

Three concerns:

  • status derivation — Kubernetes has no Job "status" field, so
    ``_job_status`` infers one from conditions/counters. Getting this wrong
    mislabels every row in the Jobs grid.
  • authorization — Job listing and deletion are separately gated, so viewing
    Jobs must not imply being able to delete them.
  • trigger idempotency — a double-clicked "Run Now" must not start the
    workload twice.
"""

from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from httpx import ASGITransport, AsyncClient
from kubernetes.client.rest import ApiException

from app.api.v1.endpoints.aks_operations import _get_service
from app.auth import get_current_user
from app.core.database import get_db
from app.models.database import Permission, Resource
from app.schemas.auth import UserContext, UserRole
from app.services.aks_operations_service import AKSOperationsService

CLUSTER_ID = "/subscriptions/s1/resourceGroups/rg1/providers/Microsoft.ContainerService/managedClusters/aks-prod-01"


# ── Builders for fake Kubernetes objects ───────────────────────────────────────


def make_job(
    *,
    name="report-job",
    namespace="com-att-prod",
    uid="uid-1",
    conditions=(),
    active=0,
    succeeded=0,
    failed=0,
    suspend=False,
    completions=1,
    parallelism=1,
    backoff_limit=6,
    labels=None,
    owner_kind=None,
    created=None,
    start_time=None,
    completion_time=None,
):
    return SimpleNamespace(
        metadata=SimpleNamespace(
            name=name,
            namespace=namespace,
            uid=uid,
            labels=labels or {},
            annotations={},
            creation_timestamp=created or datetime(2026, 8, 20, 12, 0, tzinfo=UTC),
            owner_references=(
                [SimpleNamespace(kind=owner_kind, name="nightly-report", uid="cj-uid")] if owner_kind else []
            ),
        ),
        spec=SimpleNamespace(
            completions=completions,
            parallelism=parallelism,
            backoff_limit=backoff_limit,
            completion_mode="NonIndexed",
            ttl_seconds_after_finished=None,
            suspend=suspend,
            template=SimpleNamespace(spec=SimpleNamespace(containers=[SimpleNamespace(image="repo/img:1")])),
        ),
        status=SimpleNamespace(
            active=active,
            succeeded=succeeded,
            failed=failed,
            start_time=start_time,
            completion_time=completion_time,
            conditions=[
                SimpleNamespace(
                    type=c[0],
                    status=c[1],
                    reason=None,
                    message=None,
                    last_transition_time=None,
                )
                for c in conditions
            ],
        ),
    )


class FakeJobService:
    def __init__(self, *, jobs=None, detail=None, pods=None, raises=None, delete_result=None):
        self._jobs = jobs if jobs is not None else []
        self._detail = detail
        self._pods = pods if pods is not None else []
        self._raises = raises
        self._delete_result = delete_result
        self.delete_calls: list[dict] = []

    async def get_jobs(self, cluster_id, namespace=None, bypass_cache=False):
        if self._raises:
            raise self._raises
        return self._jobs

    async def get_job_detail(self, cluster_id, namespace, name):
        if self._raises:
            raise self._raises
        return self._detail

    async def get_job_pods(self, cluster_id, namespace, job_name, job_uid=None):
        if self._raises:
            raise self._raises
        return self._pods

    async def delete_job(self, *, cluster_id, namespace, job_name, propagation_policy="Background"):
        self.delete_calls.append(
            {"namespace": namespace, "job_name": job_name, "propagation_policy": propagation_policy}
        )
        if self._raises:
            raise self._raises
        return self._delete_result


def make_user(*roles: UserRole, user_id: str = "u-test") -> UserContext:
    return UserContext(
        user_id=user_id,
        object_id="00000000-0000-0000-0000-000000000000",
        display_name="Test User",
        email=f"{user_id}@example.com",
        roles=list(roles),
        raw_roles=[r.value for r in roles],
        tenant_id="tenant-test",
        allowed_subscriptions=[],
    )


async def _seed(db_session, capability: str, *, granted_to: str | None, permission_type: str) -> None:
    res = Resource(
        resource_type="operation",
        resource_name=capability,
        description=capability,
        is_system=True,
    )
    db_session.add(res)
    await db_session.commit()
    await db_session.refresh(res)
    if granted_to:
        db_session.add(
            Permission(
                subject_type="role",
                subject_id=granted_to,
                resource_id=res.id,
                permission_type=permission_type,
                environment_scope="all",
            )
        )
        await db_session.commit()


@asynccontextmanager
async def client(app, db_session, user: UserContext, service=None):
    async def _get_db_override():
        yield db_session

    app.dependency_overrides[get_db] = _get_db_override
    app.dependency_overrides[get_current_user] = lambda: user
    if service is not None:
        app.dependency_overrides[_get_service] = lambda: service
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            yield ac
    finally:
        app.dependency_overrides.clear()


# ── Status derivation ──────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("kwargs", "expected"),
    [
        ({"conditions": [("Complete", "True")], "succeeded": 1}, "Completed"),
        ({"conditions": [("Failed", "True")], "failed": 1}, "Failed"),
        ({"active": 2}, "Running"),
        ({"suspend": True}, "Suspended"),
        ({}, "Unknown"),
        # A False condition must not be treated as terminal.
        ({"conditions": [("Complete", "False")], "active": 1}, "Running"),
        # Suspension outranks a stale active count.
        ({"suspend": True, "active": 1}, "Suspended"),
        # Counters are the fallback when conditions have not landed yet.
        ({"succeeded": 1}, "Completed"),
        ({"failed": 3}, "Failed"),
    ],
)
def test_job_status_derivation(kwargs, expected):
    assert AKSOperationsService._job_status(make_job(**kwargs)) == expected


def test_serialize_job_exposes_grid_fields():
    job = make_job(
        conditions=[("Complete", "True")],
        succeeded=1,
        completions=1,
        start_time=datetime(2026, 8, 20, 12, 0, tzinfo=UTC),
        completion_time=datetime(2026, 8, 20, 12, 5, tzinfo=UTC),
    )
    out = AKSOperationsService._serialize_job(job)

    assert out["name"] == "report-job"
    assert out["namespace"] == "com-att-prod"
    assert out["status"] == "Completed"
    assert out["succeeded"] == 1
    assert out["completions"] == 1
    assert out["start_time"] == "2026-08-20T12:00:00+00:00"
    assert out["completion_time"] == "2026-08-20T12:05:00+00:00"
    assert out["image"] == "repo/img:1"


def test_serialize_job_attributes_manual_trigger():
    """A manually triggered Job must be traceable back to its CronJob."""
    job = make_job(labels={"triggered-by": "manual", "cronjob-name": "nightly-report"})
    out = AKSOperationsService._serialize_job(job)
    assert out["created_by"] == "nightly-report"
    assert out["trigger"] == "manual"


def test_serialize_job_attributes_scheduled_run():
    job = make_job(owner_kind="CronJob")
    out = AKSOperationsService._serialize_job(job)
    assert out["created_by"] == "nightly-report"
    assert out["trigger"] == "schedule"


def test_serialize_job_handles_standalone_job():
    out = AKSOperationsService._serialize_job(make_job())
    assert out["created_by"] is None
    assert out["trigger"] is None


# ── Listing / detail ──────────────────────────────────────────────────────────


async def test_list_jobs_returns_jobs(app, db_session):
    await _seed(db_session, "aks_job_view", granted_to="read", permission_type="view")
    service = FakeJobService(jobs=[{"name": "j1"}, {"name": "j2"}])

    async with client(app, db_session, make_user(UserRole.READ), service) as ac:
        resp = await ac.get("/api/v1/aks/jobs", params={"cluster_id": CLUSTER_ID})

    assert resp.status_code == 200
    assert resp.json()["count"] == 2


async def test_list_jobs_requires_view_capability(app, db_session):
    await _seed(db_session, "aks_job_view", granted_to="write", permission_type="view")
    service = FakeJobService(jobs=[])

    async with client(app, db_session, make_user(UserRole.READ), service) as ac:
        resp = await ac.get("/api/v1/aks/jobs", params={"cluster_id": CLUSTER_ID})

    assert resp.status_code == 403


async def test_job_detail_404_when_missing(app, db_session):
    await _seed(db_session, "aks_job_view", granted_to="read", permission_type="view")
    service = FakeJobService(raises=ApiException(status=404, reason="Not Found"))

    async with client(app, db_session, make_user(UserRole.READ), service) as ac:
        resp = await ac.get(
            "/api/v1/aks/jobs/detail",
            params={"cluster_id": CLUSTER_ID, "namespace": "com-att-prod", "name": "gone"},
        )

    assert resp.status_code == 404
    assert "gone" in resp.json()["detail"]


async def test_job_pods_listed(app, db_session):
    await _seed(db_session, "aks_job_view", granted_to="read", permission_type="view")
    service = FakeJobService(pods=[{"pod_name": "report-job-abc"}])

    async with client(app, db_session, make_user(UserRole.READ), service) as ac:
        resp = await ac.get(
            "/api/v1/aks/jobs/com-att-prod/report-job/pods",
            params={"cluster_id": CLUSTER_ID},
        )

    assert resp.status_code == 200
    assert resp.json()["pods"][0]["pod_name"] == "report-job-abc"


# ── Deletion + authorization ──────────────────────────────────────────────────


async def test_authorized_user_can_delete_job(app, db_session):
    await _seed(db_session, "aks_job_delete", granted_to="write", permission_type="edit")
    service = FakeJobService(
        delete_result={
            "success": True,
            "job_name": "report-job",
            "namespace": "com-att-prod",
            "previous_status": "Completed",
            "propagation_policy": "Background",
        }
    )

    async with client(app, db_session, make_user(UserRole.WRITE), service) as ac:
        resp = await ac.delete(
            "/api/v1/aks/jobs/com-att-prod/report-job",
            params={"cluster_id": CLUSTER_ID},
        )

    assert resp.status_code == 200
    assert service.delete_calls[0]["propagation_policy"] == "Background"


async def test_delete_job_honours_orphan_policy(app, db_session):
    await _seed(db_session, "aks_job_delete", granted_to="write", permission_type="edit")
    service = FakeJobService(delete_result={"success": True, "job_name": "j", "namespace": "n"})

    async with client(app, db_session, make_user(UserRole.WRITE), service) as ac:
        resp = await ac.delete(
            "/api/v1/aks/jobs/com-att-prod/report-job",
            params={"cluster_id": CLUSTER_ID, "propagation_policy": "Orphan"},
        )

    assert resp.status_code == 200
    assert service.delete_calls[0]["propagation_policy"] == "Orphan"


async def test_delete_job_rejects_unknown_propagation_policy(app, db_session):
    await _seed(db_session, "aks_job_delete", granted_to="write", permission_type="edit")
    service = FakeJobService(delete_result={"success": True})

    async with client(app, db_session, make_user(UserRole.WRITE), service) as ac:
        resp = await ac.delete(
            "/api/v1/aks/jobs/com-att-prod/report-job",
            params={"cluster_id": CLUSTER_ID, "propagation_policy": "Nonsense"},
        )

    assert resp.status_code == 422
    assert service.delete_calls == []


async def test_unauthorized_user_cannot_delete_job(app, db_session):
    """Job view access must not confer Job deletion."""
    await _seed(db_session, "aks_job_view", granted_to="read", permission_type="view")
    await _seed(db_session, "aks_job_delete", granted_to="write", permission_type="edit")
    service = FakeJobService(delete_result={"success": True})

    async with client(app, db_session, make_user(UserRole.READ), service) as ac:
        resp = await ac.delete(
            "/api/v1/aks/jobs/com-att-prod/report-job",
            params={"cluster_id": CLUSTER_ID},
        )

    assert resp.status_code == 403
    assert service.delete_calls == []


async def test_unauthenticated_job_delete_receives_401(app, db_session):
    from app.core.config import settings

    original = settings.DEV_AUTH_BYPASS
    settings.DEV_AUTH_BYPASS = False

    async def _get_db_override():
        yield db_session

    app.dependency_overrides[get_db] = _get_db_override
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            resp = await ac.delete(
                "/api/v1/aks/jobs/com-att-prod/report-job",
                params={"cluster_id": CLUSTER_ID},
            )
        assert resp.status_code == 401
    finally:
        settings.DEV_AUTH_BYPASS = original
        app.dependency_overrides.clear()


async def test_delete_job_is_audited(app, db_session):
    from app.api.v1.endpoints import aks_operations

    aks_operations._in_memory_audit_log.clear()
    await _seed(db_session, "aks_job_delete", granted_to="write", permission_type="edit")
    service = FakeJobService(
        delete_result={
            "success": True,
            "job_name": "report-job",
            "namespace": "com-att-prod",
            "previous_status": "Failed",
        }
    )

    async with client(app, db_session, make_user(UserRole.WRITE, user_id="u-op"), service) as ac:
        await ac.delete("/api/v1/aks/jobs/com-att-prod/report-job", params={"cluster_id": CLUSTER_ID})

    entries = [e for e in aks_operations._in_memory_audit_log if e["action"] == "delete_job"]
    aks_operations._in_memory_audit_log.clear()

    assert len(entries) == 1
    assert entries[0]["status"] == "success"
    assert entries[0]["user_id"] == "u-op"
    assert entries[0]["resource_type"] == "job"
    assert entries[0]["details"]["previous_status"] == "Failed"


# ── CronJob trigger idempotency ───────────────────────────────────────────────


class FakeBatchForTrigger:
    """Minimal BatchV1Api stand-in for trigger_cronjob."""

    def __init__(self, existing_jobs=None, create_conflict=False):
        self.existing_jobs = existing_jobs or []
        self.create_conflict = create_conflict
        self.created: list[str] = []

    def read_namespaced_cron_job(self, name, namespace):
        return SimpleNamespace(
            metadata=SimpleNamespace(labels={}),
            spec=SimpleNamespace(
                schedule="0 2 * * *",
                suspend=False,
                job_template=SimpleNamespace(spec=SimpleNamespace()),
            ),
        )

    def list_namespaced_job(self, namespace, label_selector=None):
        return SimpleNamespace(items=self.existing_jobs)

    def create_namespaced_job(self, namespace, job):
        if self.create_conflict:
            raise ApiException(status=409, reason="AlreadyExists")
        self.created.append(job.metadata.name)


@pytest.fixture
def trigger_service(monkeypatch):
    """AKSOperationsService with Kubernetes and side effects stubbed out."""

    def _build(batch):
        svc = AKSOperationsService.__new__(AKSOperationsService)
        svc.db = None

        async def _clients(_cluster_id):
            return (None, None, batch)

        svc._get_k8s_clients = _clients
        svc._extract_cluster_name = lambda cid: "aks-prod-01"

        async def _noop(*args, **kwargs):
            return True

        svc._db_add_and_commit = _noop
        svc._refresh_cronjob_db_cache = _noop

        from app.services import aks_operations_service as mod

        monkeypatch.setattr(mod.data_cache, "invalidate_for_cronjobs", _noop)
        monkeypatch.setattr(mod.data_cache, "invalidate_for_jobs", _noop)
        return svc

    return _build


async def test_trigger_creates_a_job(trigger_service):
    batch = FakeBatchForTrigger()
    svc = trigger_service(batch)

    result = await svc.trigger_cronjob(CLUSTER_ID, "com-att-prod", "nightly-report")

    assert result["success"] is True
    assert result["deduplicated"] is False
    assert result["job_name"].startswith("nightly-report-manual-")
    assert len(batch.created) == 1


async def test_repeated_trigger_reuses_the_recent_job(trigger_service):
    """A double-clicked Run Now must not launch the workload twice."""
    recent = make_job(
        name="nightly-report-manual-20260820120000",
        created=datetime.now(UTC) - timedelta(seconds=5),
        labels={"triggered-by": "manual", "cronjob-name": "nightly-report"},
    )
    batch = FakeBatchForTrigger(existing_jobs=[recent])
    svc = trigger_service(batch)

    result = await svc.trigger_cronjob(CLUSTER_ID, "com-att-prod", "nightly-report")

    assert result["success"] is True
    assert result["deduplicated"] is True
    assert result["job_name"] == "nightly-report-manual-20260820120000"
    assert batch.created == []


async def test_finished_job_does_not_suppress_a_rerun(trigger_service):
    """A completed short-lived Job must not be mistaken for an in-flight run.

    Regression: dedup only checked the creation timestamp, so re-running a
    CronJob seconds after a fast run finished was silently dropped and reported
    back as "already running".
    """
    finished = make_job(
        name="nightly-report-manual-done",
        created=datetime.now(UTC) - timedelta(seconds=3),
        labels={"triggered-by": "manual", "cronjob-name": "nightly-report"},
        conditions=[("Complete", "True")],
        succeeded=1,
    )
    batch = FakeBatchForTrigger(existing_jobs=[finished])
    svc = trigger_service(batch)

    result = await svc.trigger_cronjob(CLUSTER_ID, "com-att-prod", "nightly-report")

    assert result["deduplicated"] is False
    assert len(batch.created) == 1


async def test_active_job_suppresses_a_rerun(trigger_service):
    active = make_job(
        name="nightly-report-manual-active",
        created=datetime.now(UTC) - timedelta(seconds=3),
        labels={"triggered-by": "manual", "cronjob-name": "nightly-report"},
        active=1,
    )
    batch = FakeBatchForTrigger(existing_jobs=[active])
    svc = trigger_service(batch)

    result = await svc.trigger_cronjob(CLUSTER_ID, "com-att-prod", "nightly-report")

    assert result["deduplicated"] is True
    assert result["job_name"] == "nightly-report-manual-active"
    assert batch.created == []


async def test_trigger_creates_again_once_the_window_passes(trigger_service):
    """Dedup is a double-click guard, not a rate limit on legitimate reruns."""
    old = make_job(
        name="nightly-report-manual-old",
        created=datetime.now(UTC) - timedelta(minutes=10),
        labels={"triggered-by": "manual", "cronjob-name": "nightly-report"},
    )
    batch = FakeBatchForTrigger(existing_jobs=[old])
    svc = trigger_service(batch)

    result = await svc.trigger_cronjob(CLUSTER_ID, "com-att-prod", "nightly-report")

    assert result["deduplicated"] is False
    assert len(batch.created) == 1


async def test_trigger_treats_name_collision_as_success(trigger_service):
    """Two racing requests must not surface a spurious failure."""
    batch = FakeBatchForTrigger(create_conflict=True)
    svc = trigger_service(batch)

    result = await svc.trigger_cronjob(CLUSTER_ID, "com-att-prod", "nightly-report")

    assert result["success"] is True
    assert result["deduplicated"] is True


async def test_dedup_lookup_failure_does_not_block_trigger(trigger_service):
    """A failed dedup probe must never be why a legitimate trigger fails."""

    class ExplodingBatch(FakeBatchForTrigger):
        def list_namespaced_job(self, namespace, label_selector=None):
            raise ApiException(status=500, reason="boom")

    batch = ExplodingBatch()
    svc = trigger_service(batch)

    result = await svc.trigger_cronjob(CLUSTER_ID, "com-att-prod", "nightly-report")

    assert result["success"] is True
    assert len(batch.created) == 1
