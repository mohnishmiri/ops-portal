"""Startup sequences that scale some deployments down (even to 0) before
scaling others up: the next step waits until the stopped pods are gone."""

import time
from types import SimpleNamespace

import pytest
from kubernetes.client.rest import ApiException
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.ext.compiler import compiles

from app.models.database import AuditLog, EnvironmentExecutionHistory, EnvironmentSchedule, EnvironmentSequence
from app.services import environment_scaling_service as env_module
from app.services.environment_scaling_service import EnvironmentScalingService


@compiles(JSONB, "sqlite")
def _jsonb_as_json_on_sqlite(_type, _compiler, **_kw):
    return "JSON"


@pytest.fixture(autouse=True)
def _fast_polling(monkeypatch):
    monkeypatch.setattr(env_module, "POLL_SECONDS", 0.02)


def _pod(phase="Running"):
    return SimpleNamespace(status=SimpleNamespace(phase=phase))


class Cluster:
    """Records the order of events. Stopped pods linger for a few listings."""

    def __init__(self, replicas, terminating_listings=2, extra_pods=()):
        self.replicas = dict(replicas)
        self.terminating = {}  # name -> listings left before the old pods are gone
        self.terminating_listings = terminating_listings
        self.extra_pods = list(extra_pods)
        self.events: list[str] = []

    async def scale_deployment(self, *, cluster_id, namespace, deployment_name, replicas, user_id, user_email):
        previous = self.replicas.get(deployment_name, 0)
        self.events.append(f"scale {deployment_name} {previous}->{replicas}")
        if replicas < previous:
            self.terminating[deployment_name] = (previous, self.terminating_listings)
        self.replicas[deployment_name] = replicas
        return {"previous_replicas": previous}

    async def _get_k8s_clients(self, cluster_id):
        def read_deployment(name, namespace):
            return SimpleNamespace(spec=SimpleNamespace(selector=SimpleNamespace(match_labels={"app": name})))

        def read_status(name, namespace):
            n = self.replicas.get(name, 0)
            return SimpleNamespace(
                spec=None, status=SimpleNamespace(ready_replicas=n, available_replicas=n, conditions=[])
            )

        def list_pods(namespace, label_selector=None, _request_timeout=None):
            name = label_selector.split("=", 1)[1]
            count = self.replicas.get(name, 0)
            if name in self.terminating:
                previous, left = self.terminating[name]
                if left > 0:
                    count = previous  # old pods still terminating
                    self.terminating[name] = (previous, left - 1)
            self.events.append(f"list {name} {count}")
            return SimpleNamespace(items=[_pod() for _ in range(count)] + self.extra_pods)

        return (
            SimpleNamespace(read_namespaced_deployment=read_deployment, read_namespaced_deployment_status=read_status),
            SimpleNamespace(list_namespaced_pod=list_pods),
            None,
        )


@pytest.fixture
async def factory(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'env.db'}")
    async with engine.begin() as conn:
        for model in (EnvironmentSequence, EnvironmentSchedule, EnvironmentExecutionHistory, AuditLog):
            await conn.run_sync(lambda c, m=model: m.__table__.create(c))
    yield async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    await engine.dispose()


def _step(order, name, replicas, wait, timeout=1):
    return {
        "order": order,
        "deployment_name": name,
        "replicas": replicas,
        "wait_condition": wait,
        "timeout_seconds": timeout,
        "min_ready_percent": 100,
        "on_failure": "abort",
    }


async def _run(factory, steps, cluster, *, rollback=True):
    async with factory() as db:
        seq = EnvironmentSequence(
            name="SCAL-Up-UI",
            cluster_id="c1",
            namespace="apps",
            sequence_type="startup",
            rollback_on_failure=rollback,
            created_by="u1",
            steps=steps,
        )
        db.add(seq)
        await db.commit()
        service = EnvironmentScalingService(db)
        service._aks = cluster
        return await service.execute_sequence(
            sequence_id=seq.id, replica_count=1, dry_run=False, user_id="u1", user_email="u1@example.com"
        )


@pytest.mark.anyio
async def test_a_startup_can_stop_one_deployment_before_scaling_up_another(factory):
    cluster = Cluster({"compadmin": 30, "administration": 0})

    result = await _run(
        factory,
        [
            _step(1, "compadmin", 0, "pods_terminated"),
            _step(2, "administration", 60, "pods_ready"),
        ],
        cluster,
    )

    assert result["status"] == "completed"
    first, second = result["details"]
    assert (first["current_replicas"], first["target_replicas"], first["pods_remaining"]) == (30, 0, 0)
    # administration was only scaled once compadmin's terminating pods were gone.
    events = cluster.events
    assert events.index("list compadmin 0") < events.index("scale administration 0->60")
    assert second["status"] == "completed"


@pytest.mark.anyio
async def test_a_fixed_wait_after_scaling_to_zero_is_honoured(factory):
    started = time.monotonic()
    # Timeouts are whole seconds.
    result = await _run(factory, [_step(1, "compadmin", 0, "fixed_time", timeout=1)], Cluster({"compadmin": 5}))
    assert result["status"] == "completed"
    assert time.monotonic() - started >= 1


@pytest.mark.anyio
async def test_evicted_pods_do_not_hold_up_a_scale_down(factory):
    cluster = Cluster({"compadmin": 4}, terminating_listings=0, extra_pods=[_pod("Failed"), _pod("Succeeded")])
    result = await _run(factory, [_step(1, "compadmin", 0, "pods_terminated")], cluster)
    assert result["status"] == "completed"


@pytest.mark.anyio
async def test_pods_stuck_terminating_fail_the_step_and_roll_back(factory):
    # Old pods never finish terminating.
    cluster = Cluster({"compadmin": 3, "administration": 0}, terminating_listings=10_000)

    result = await _run(
        factory,
        [
            _step(1, "compadmin", 0, "pods_terminated", timeout=1),
            _step(2, "administration", 60, "pods_ready"),
        ],
        cluster,
    )

    assert result["status"] == "rolled_back"
    assert "3 pods still running or terminating (target 0)" in result["details"][0]["error"]
    assert result["details"][1]["status"] == "not_run"
    assert cluster.replicas["compadmin"] == 3  # rollback restored it


@pytest.mark.anyio
async def test_scale_down_wait_treats_a_missing_deployment_as_done():
    class Gone:
        async def _get_k8s_clients(self, cluster_id):
            def read_deployment(name, namespace):
                raise ApiException(status=404, reason="Not Found")

            return SimpleNamespace(read_namespaced_deployment=read_deployment), SimpleNamespace(), None

    service = EnvironmentScalingService(None)
    service._aks = Gone()
    assert (
        await service._wait_for_scale_down(
            cluster_id="c1", namespace="apps", deployment_name="compadmin", desired_replicas=0, timeout_seconds=1
        )
        == 0
    )
