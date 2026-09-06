"""
Tests for DELETE /api/v1/aks/pods/{namespace}/{pod_name}.

Two things are being verified, and the second matters more than the first:

  1. the happy path deletes the pod and audits it
  2. authorization is enforced by the API itself, not by the UI hiding a button

Kubernetes is faked at the service boundary so these run without a cluster.
The ``ApiException`` cases assert that each Kubernetes failure mode maps onto a
distinct, non-leaky HTTP status.
"""

from contextlib import asynccontextmanager

import pytest
from httpx import ASGITransport, AsyncClient
from kubernetes.client.rest import ApiException

from app.api.v1.endpoints.aks_operations import _get_service
from app.auth import get_current_user
from app.core.database import get_db
from app.models.database import Permission, Resource
from app.schemas.auth import UserContext, UserRole

CLUSTER_ID = "/subscriptions/s1/resourceGroups/rg1/providers/Microsoft.ContainerService/managedClusters/aks-prod-01"
POD_PATH = "/api/v1/aks/pods/com-att-prod/application-7d8f9c8b9-x2abc"


# ── Fakes ──────────────────────────────────────────────────────────────────────


class FakePodService:
    """Stands in for AKSOperationsService.delete_pod."""

    def __init__(self, *, result=None, raises=None):
        self._result = result
        self._raises = raises
        self.calls: list[dict] = []

    async def delete_pod(self, *, cluster_id, namespace, pod_name, grace_period_seconds=None):
        self.calls.append(
            {
                "cluster_id": cluster_id,
                "namespace": namespace,
                "pod_name": pod_name,
                "grace_period_seconds": grace_period_seconds,
            }
        )
        if self._raises is not None:
            raise self._raises
        return self._result


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


async def _seed_capability(db_session, *, granted_to: str | None) -> None:
    """Register aks_pod_delete, optionally granting it to a role."""
    res = Resource(
        resource_type="operation",
        resource_name="aks_pod_delete",
        description="Delete pods",
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
                permission_type="edit",
                environment_scope="all",
            )
        )
        await db_session.commit()


@asynccontextmanager
async def client(app, db_session, user: UserContext | None, service: FakePodService | None = None):
    async def _get_db_override():
        yield db_session

    app.dependency_overrides[get_db] = _get_db_override
    if user is not None:
        app.dependency_overrides[get_current_user] = lambda: user
    if service is not None:
        app.dependency_overrides[_get_service] = lambda: service
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            yield ac
    finally:
        app.dependency_overrides.clear()


# ── Happy path ─────────────────────────────────────────────────────────────────


async def test_authorized_user_can_delete_pod(app, db_session):
    await _seed_capability(db_session, granted_to="write")
    service = FakePodService(
        result={
            "success": True,
            "pod_name": "application-7d8f9c8b9-x2abc",
            "namespace": "com-att-prod",
            "phase": "Running",
            "owner": "ReplicaSet/application-7d8f9c8b9",
            "will_be_recreated": True,
        }
    )

    async with client(app, db_session, make_user(UserRole.WRITE), service) as ac:
        resp = await ac.delete(POD_PATH, params={"cluster_id": CLUSTER_ID})

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["success"] is True
    assert body["will_be_recreated"] is True
    assert service.calls == [
        {
            "cluster_id": CLUSTER_ID,
            "namespace": "com-att-prod",
            "pod_name": "application-7d8f9c8b9-x2abc",
            "grace_period_seconds": None,
        }
    ]


async def test_admin_can_delete_pod_without_explicit_grant(app, db_session):
    await _seed_capability(db_session, granted_to=None)
    service = FakePodService(result={"success": True, "pod_name": "p", "namespace": "n", "will_be_recreated": False})

    async with client(app, db_session, make_user(UserRole.ADMIN), service) as ac:
        resp = await ac.delete(POD_PATH, params={"cluster_id": CLUSTER_ID})

    assert resp.status_code == 200


async def test_delete_pod_forwards_grace_period(app, db_session):
    await _seed_capability(db_session, granted_to="write")
    service = FakePodService(result={"success": True, "pod_name": "p", "namespace": "n", "will_be_recreated": False})

    async with client(app, db_session, make_user(UserRole.WRITE), service) as ac:
        resp = await ac.delete(POD_PATH, params={"cluster_id": CLUSTER_ID, "grace_period_seconds": 0})

    assert resp.status_code == 200
    assert service.calls[0]["grace_period_seconds"] == 0


# ── Authorization ──────────────────────────────────────────────────────────────


async def test_unauthorized_user_receives_403(app, db_session):
    """A read-only account must be refused by the API, not merely by the UI."""
    await _seed_capability(db_session, granted_to="write")
    service = FakePodService(result={"success": True})

    async with client(app, db_session, make_user(UserRole.READ), service) as ac:
        resp = await ac.delete(POD_PATH, params={"cluster_id": CLUSTER_ID})

    assert resp.status_code == 403
    # The pod must never have been touched.
    assert service.calls == []
    # No hint about which capability was missing.
    assert "aks_pod_delete" not in resp.text


async def test_user_with_no_roles_receives_403(app, db_session):
    await _seed_capability(db_session, granted_to="write")
    service = FakePodService(result={"success": True})

    async with client(app, db_session, make_user(), service) as ac:
        resp = await ac.delete(POD_PATH, params={"cluster_id": CLUSTER_ID})

    assert resp.status_code == 403
    assert service.calls == []


async def test_unauthenticated_request_receives_401(app, db_session):
    """No credentials at all → 401, with the dev bypass off."""
    from app.core.config import settings

    original = settings.DEV_AUTH_BYPASS
    settings.DEV_AUTH_BYPASS = False

    async def _get_db_override():
        yield db_session

    app.dependency_overrides[get_db] = _get_db_override
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            resp = await ac.delete(POD_PATH, params={"cluster_id": CLUSTER_ID})
        assert resp.status_code == 401
    finally:
        settings.DEV_AUTH_BYPASS = original
        app.dependency_overrides.clear()


async def test_user_grant_alone_authorizes_delete(app, db_session):
    """A per-user grant works without the write role — proving the capability
    layer is what authorizes, not the coarse role."""
    res = Resource(
        resource_type="operation",
        resource_name="aks_pod_delete",
        description="Delete pods",
        is_system=True,
    )
    db_session.add(res)
    await db_session.commit()
    await db_session.refresh(res)
    db_session.add(
        Permission(
            subject_type="user",
            subject_id="u-oncall",
            resource_id=res.id,
            permission_type="edit",
            environment_scope="all",
        )
    )
    await db_session.commit()

    service = FakePodService(result={"success": True, "pod_name": "p", "namespace": "n", "will_be_recreated": False})
    async with client(app, db_session, make_user(UserRole.READ, user_id="u-oncall"), service) as ac:
        resp = await ac.delete(POD_PATH, params={"cluster_id": CLUSTER_ID})

    assert resp.status_code == 200


# ── Kubernetes failure translation ─────────────────────────────────────────────


@pytest.mark.parametrize(
    ("k8s_status", "expected_status"),
    [
        (404, 404),  # pod (or namespace) does not exist
        (403, 403),  # portal credentials lack RBAC on the cluster
        (409, 409),  # concurrent modification
        (500, 502),  # generic Kubernetes API failure
    ],
)
async def test_kubernetes_errors_map_to_distinct_statuses(app, db_session, k8s_status, expected_status):
    await _seed_capability(db_session, granted_to="write")
    service = FakePodService(raises=ApiException(status=k8s_status, reason="k8s failure"))

    async with client(app, db_session, make_user(UserRole.WRITE), service) as ac:
        resp = await ac.delete(POD_PATH, params={"cluster_id": CLUSTER_ID})

    assert resp.status_code == expected_status


async def test_pod_not_found_names_the_pod_and_namespace(app, db_session):
    await _seed_capability(db_session, granted_to="write")
    service = FakePodService(raises=ApiException(status=404, reason="Not Found"))

    async with client(app, db_session, make_user(UserRole.WRITE), service) as ac:
        resp = await ac.delete(POD_PATH, params={"cluster_id": CLUSTER_ID})

    assert resp.status_code == 404
    detail = resp.json()["detail"]
    assert "application-7d8f9c8b9-x2abc" in detail
    assert "com-att-prod" in detail


async def test_cluster_unavailable_returns_502_without_internal_detail(app, db_session):
    """An Azure credential/kubeconfig failure must not leak internals."""
    await _seed_capability(db_session, granted_to="write")
    service = FakePodService(raises=RuntimeError("DefaultAzureCredential failed: secret xyz123"))

    async with client(app, db_session, make_user(UserRole.WRITE), service) as ac:
        resp = await ac.delete(POD_PATH, params={"cluster_id": CLUSTER_ID})

    assert resp.status_code == 502
    assert "xyz123" not in resp.text
    assert "DefaultAzureCredential" not in resp.text


async def test_timeout_returns_504(app, db_session):
    await _seed_capability(db_session, granted_to="write")
    service = FakePodService(raises=TimeoutError())

    async with client(app, db_session, make_user(UserRole.WRITE), service) as ac:
        resp = await ac.delete(POD_PATH, params={"cluster_id": CLUSTER_ID})

    assert resp.status_code == 504


# ── Audit logging ──────────────────────────────────────────────────────────────


@pytest.fixture
def audit_sink():
    """Isolate the in-memory audit fallback for one test.

    ``_write_aks_audit_log`` writes through a standalone DB session; with no
    Postgres in the test environment it falls back to the in-process deque,
    which is the documented degraded path and is what we assert against.
    """
    from app.api.v1.endpoints import aks_operations

    aks_operations._in_memory_audit_log.clear()
    yield aks_operations._in_memory_audit_log
    aks_operations._in_memory_audit_log.clear()


async def test_successful_delete_is_audited(app, db_session, audit_sink):
    await _seed_capability(db_session, granted_to="write")
    service = FakePodService(
        result={
            "success": True,
            "pod_name": "application-7d8f9c8b9-x2abc",
            "namespace": "com-att-prod",
            "phase": "Running",
            "owner": "ReplicaSet/application-7d8f9c8b9",
            "will_be_recreated": True,
        }
    )

    async with client(app, db_session, make_user(UserRole.WRITE, user_id="u-operator"), service) as ac:
        resp = await ac.delete(POD_PATH, params={"cluster_id": CLUSTER_ID})
    assert resp.status_code == 200

    entries = [e for e in audit_sink if e["action"] == "delete_pod"]
    assert len(entries) == 1
    entry = entries[0]
    assert entry["status"] == "success"
    assert entry["user_id"] == "u-operator"
    assert entry["user_email"] == "u-operator@example.com"
    assert entry["resource_type"] == "pod"
    assert entry["resource_name"] == "application-7d8f9c8b9-x2abc"
    assert entry["namespace"] == "com-att-prod"
    assert entry["cluster_id"] == CLUSTER_ID
    assert entry["cluster_name"] == "aks-prod-01"
    assert entry["timestamp"]
    assert entry["details"]["phase"] == "Running"
    assert entry["details"]["owner"] == "ReplicaSet/application-7d8f9c8b9"


async def test_failed_delete_is_audited(app, db_session, audit_sink):
    """A deletion rejected by Kubernetes must still leave a trail."""
    await _seed_capability(db_session, granted_to="write")
    service = FakePodService(raises=ApiException(status=404, reason="Not Found"))

    async with client(app, db_session, make_user(UserRole.WRITE), service) as ac:
        resp = await ac.delete(POD_PATH, params={"cluster_id": CLUSTER_ID})
    assert resp.status_code == 404

    entries = [e for e in audit_sink if e["action"] == "delete_pod"]
    assert len(entries) == 1
    assert entries[0]["status"] == "failed"
    assert entries[0]["details"]["k8s_status"] == 404


async def test_denied_delete_is_not_audited_as_an_operation(app, db_session, audit_sink):
    """A 403 never reached the cluster, so it must not look like a deletion."""
    await _seed_capability(db_session, granted_to="write")
    service = FakePodService(result={"success": True})

    async with client(app, db_session, make_user(UserRole.READ), service) as ac:
        resp = await ac.delete(POD_PATH, params={"cluster_id": CLUSTER_ID})

    assert resp.status_code == 403
    assert [e for e in audit_sink if e["action"] == "delete_pod"] == []


async def test_blocked_exec_attempt_is_audited(app, db_session, audit_sink):
    """A rejected exec is exactly the event an auditor needs to see.

    Regression: the exec audit only fired on success, so blocked and failed
    attempts left no trace.
    """
    await _seed_capability(db_session, granted_to="write")
    res = Resource(
        resource_type="operation",
        resource_name="aks_pod_exec",
        description="exec",
        is_system=True,
    )
    db_session.add(res)
    await db_session.commit()
    await db_session.refresh(res)
    db_session.add(
        Permission(
            subject_type="role",
            subject_id="write",
            resource_id=res.id,
            permission_type="edit",
            environment_scope="all",
        )
    )
    await db_session.commit()

    async with client(app, db_session, make_user(UserRole.WRITE), FakePodService()) as ac:
        resp = await ac.post(
            "/api/v1/aks/pods/com-att-prod/application-7d8f9c8b9-x2abc/exec",
            json={"cluster_id": CLUSTER_ID, "command": "rm -rf / --no-preserve-root"},
        )

    assert resp.status_code == 403
    entries = [e for e in audit_sink if e["action"] == "exec_pod_command"]
    assert len(entries) == 1
    assert entries[0]["status"] == "blocked"
    assert entries[0]["details"]["error"] == "blocked_by_safety_list"


async def test_exec_requires_its_own_capability(app, db_session):
    """A read-only account must not be able to run commands inside a pod."""
    await _seed_capability(db_session, granted_to="write")
    db_session.add(
        Resource(
            resource_type="operation",
            resource_name="aks_pod_exec",
            description="exec",
            is_system=True,
        )
    )
    await db_session.commit()

    async with client(app, db_session, make_user(UserRole.READ), FakePodService()) as ac:
        resp = await ac.post(
            "/api/v1/aks/pods/com-att-prod/application-7d8f9c8b9-x2abc/exec",
            json={"cluster_id": CLUSTER_ID, "command": "ls -la"},
        )

    assert resp.status_code == 403


async def test_audit_never_records_token_material(app, db_session, audit_sink):
    """Audit details must not carry credentials, even on a credential failure."""
    await _seed_capability(db_session, granted_to="write")
    service = FakePodService(raises=RuntimeError("Bearer eyJhbGciOi.SECRETTOKEN.sig"))

    async with client(app, db_session, make_user(UserRole.WRITE), service) as ac:
        await ac.delete(POD_PATH, params={"cluster_id": CLUSTER_ID})

    serialized = str(list(audit_sink))
    assert "SECRETTOKEN" not in serialized
    assert "Bearer" not in serialized
