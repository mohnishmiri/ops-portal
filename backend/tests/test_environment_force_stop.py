"""Force stop of a running sequence: honoured within a poll from another
session (another replica), optional rollback, and recorded as stopped."""

import asyncio
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.ext.compiler import compiles

from app.models.database import AuditLog, EnvironmentExecutionHistory, EnvironmentSchedule, EnvironmentSequence
from app.services import environment_notifications as notifications
from app.services import environment_scaling_service as env_module
from app.services.environment_scaling_service import (
    EnvironmentScalingService,
    ExecutionNotRunningError,
    SequenceValidationError,
)


@compiles(JSONB, "sqlite")
def _jsonb_as_json_on_sqlite(_type, _compiler, **_kw):
    return "JSON"


@pytest.fixture(autouse=True)
def _fast_polling(monkeypatch):
    monkeypatch.setattr(env_module, "POLL_SECONDS", 0.02)


ENV_TABLES = (EnvironmentSequence, EnvironmentSchedule, EnvironmentExecutionHistory)


@pytest.fixture
async def factory(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'env.db'}")
    async with engine.begin() as conn:
        for model in (*ENV_TABLES, AuditLog):
            await conn.run_sync(lambda c, m=model: m.__table__.create(c))
    yield async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    await engine.dispose()


class SlowCluster:
    """Scales instantly; pods of `stuck` deployments never become ready."""

    def __init__(self, replicas, stuck=()):
        self.replicas = dict(replicas)
        self.stuck = set(stuck)
        self.calls: list[tuple[str, int]] = []

    async def scale_deployment(self, *, cluster_id, namespace, deployment_name, replicas, user_id, user_email):
        self.calls.append((deployment_name, replicas))
        previous = self.replicas.get(deployment_name, 0)
        self.replicas[deployment_name] = replicas
        return {"previous_replicas": previous}

    async def _get_k8s_clients(self, cluster_id):
        def read_status(name, namespace):
            ready = 0 if name in self.stuck else self.replicas.get(name, 0)
            return SimpleNamespace(
                spec=None, status=SimpleNamespace(ready_replicas=ready, available_replicas=ready, conditions=[])
            )

        def read_deployment(name, namespace):
            return SimpleNamespace(spec=SimpleNamespace(selector=SimpleNamespace(match_labels={"app": name})))

        def list_pods(namespace, label_selector=None, _request_timeout=None):
            name = label_selector.split("=", 1)[1]
            # Pods of a stopped deployment linger forever: a scale-down that never finishes.
            return SimpleNamespace(
                items=[SimpleNamespace(status=SimpleNamespace(phase="Running"))] * 3 if name in self.stuck else []
            )

        return (
            SimpleNamespace(read_namespaced_deployment_status=read_status, read_namespaced_deployment=read_deployment),
            SimpleNamespace(list_namespaced_pod=list_pods),
            None,
        )


def _step(order, name, replicas, wait="pods_ready", timeout=600):
    return {
        "order": order,
        "deployment_name": name,
        "replicas": replicas,
        "wait_condition": wait,
        "timeout_seconds": timeout,
        "min_ready_percent": 100,
        "on_failure": "abort",
    }


_names = iter(range(1, 1000))


async def _start(factory, steps, cluster, *, sequence_type="startup"):
    """Begin the run and execute it in a background task (its own session)."""
    async with factory() as db:
        seq = EnvironmentSequence(
            name=f"RTL-{next(_names)}",
            cluster_id="c1",
            namespace="apps",
            sequence_type=sequence_type,
            rollback_on_failure=False,
            created_by="u1",
            steps=steps,
        )
        db.add(seq)
        await db.commit()
        _, execution = await EnvironmentScalingService(db).begin_sequence_execution(
            sequence_id=seq.id, user_id="u1", user_email="starter@att.com"
        )
        seq_id, exec_id = seq.id, execution.id

    async def run():
        async with factory() as db:
            service = EnvironmentScalingService(db)
            service._aks = cluster
            return await service.run_sequence_execution(
                await db.get(EnvironmentSequence, seq_id),
                await db.get(EnvironmentExecutionHistory, exec_id),
                user_id="u1",
                user_email="starter@att.com",
            )

    return exec_id, asyncio.create_task(run())


async def _wait_until_step_runs(factory, exec_id, step_no):
    for _ in range(200):
        async with factory() as db:
            row = await db.get(EnvironmentExecutionHistory, exec_id)
            if row.step_details[step_no - 1]["status"] == "running":
                return
        await asyncio.sleep(0.02)
    raise AssertionError("step never started")


async def _stop(factory, exec_id, *, rollback=False, by="oncall@att.com"):
    # A separate session: the request may arrive on a different replica.
    async with factory() as db:
        return await EnvironmentScalingService(db).request_stop(exec_id, user_email=by, rollback=rollback)


@pytest.mark.anyio
async def test_a_stuck_scale_up_stops_within_a_poll_and_keeps_what_ran(factory, sent_run_emails):
    cluster = SlowCluster({"administration": 0, "compadmin": 0, "dataloader": 0}, stuck={"compadmin"})
    exec_id, task = await _start(
        factory, [_step(1, "administration", 2), _step(2, "compadmin", 600), _step(3, "dataloader", 1)], cluster
    )

    await _wait_until_step_runs(factory, exec_id, 2)
    requested = await _stop(factory, exec_id)
    assert requested["cancel_requested_by"] == "oncall@att.com" and requested["status"] == "running"
    result = await asyncio.wait_for(task, timeout=5)
    await notifications.wait_for_pending_emails()

    assert result["status"] == "cancelled"
    assert [s["status"] for s in result["details"]] == ["completed", "cancelled", "not_run"]
    assert result["error"].startswith("Stopped by oncall@att.com at step 2 (compadmin).")
    assert cluster.replicas == {"administration": 2, "compadmin": 600, "dataloader": 0}  # no rollback asked
    assert ("dataloader", 1) not in cluster.calls
    [(_, report)] = sent_run_emails
    assert report.status == "cancelled"


@pytest.mark.anyio
async def test_stop_and_roll_back_restores_what_the_run_scaled(factory):
    cluster = SlowCluster({"administration": 1, "compadmin": 0}, stuck={"compadmin"})
    exec_id, task = await _start(factory, [_step(1, "administration", 60), _step(2, "compadmin", 600)], cluster)

    await _wait_until_step_runs(factory, exec_id, 2)
    await _stop(factory, exec_id, rollback=True)
    result = await asyncio.wait_for(task, timeout=5)

    assert result["status"] == "cancelled"
    assert cluster.replicas == {"administration": 1, "compadmin": 0}
    assert "Rolled back 2 scaled step(s)" in result["error"]


@pytest.mark.anyio
async def test_a_fixed_wait_and_a_scale_down_wait_can_be_stopped(factory):
    for steps, stuck in (
        ([_step(1, "administration", 1, wait="fixed_time", timeout=600)], ()),
        ([_step(1, "compadmin", 0, wait="pods_terminated")], {"compadmin"}),
    ):
        exec_id, task = await _start(factory, steps, SlowCluster({"administration": 0, "compadmin": 3}, stuck=stuck))
        await _wait_until_step_runs(factory, exec_id, 1)
        await _stop(factory, exec_id)
        result = await asyncio.wait_for(task, timeout=5)  # not the full 600s
        assert result["details"][0]["status"] == "cancelled"


@pytest.mark.anyio
async def test_a_stop_before_the_first_step_runs_nothing(factory):
    cluster = SlowCluster({"web": 4, "api": 2}, stuck=set())
    exec_id, task = await _start(factory, [_step(1, "web", 0), _step(2, "api", 0)], cluster, sequence_type="shutdown")
    # Requested before the run picks up its first step: nothing is scaled, nothing to roll back.
    await _stop(factory, exec_id, rollback=True)
    result = await asyncio.wait_for(task, timeout=5)
    assert result["status"] == "cancelled"
    assert all(s["status"] == "not_run" for s in result["details"])
    assert cluster.replicas == {"web": 4, "api": 2}


@pytest.mark.anyio
async def test_only_running_sequence_runs_can_be_stopped(factory):
    async with factory() as db:
        done = EnvironmentExecutionHistory(
            execution_type="sequence",
            cluster_id="c1",
            namespace="apps",
            operation="sequence_startup",
            status="completed",
            total_deployments=1,
            sequence_id=1,
            initiated_by="u1",
            started_at=datetime.utcnow(),
        )
        scale = EnvironmentExecutionHistory(
            execution_type="manual",
            cluster_id="c1",
            namespace="apps",
            operation="scale_up",
            status="running",
            total_deployments=1,
            initiated_by="u1",
            started_at=datetime.utcnow(),
        )
        db.add_all([done, scale])
        await db.commit()
        service = EnvironmentScalingService(db)
        with pytest.raises(ExecutionNotRunningError, match="already finished"):
            await service.request_stop(done.id, user_email="x@att.com", rollback=False)
        with pytest.raises(SequenceValidationError, match="Only sequence runs"):
            await service.request_stop(scale.id, user_email="x@att.com", rollback=False)


@pytest.mark.anyio
async def test_an_unanswered_stop_is_recorded_as_stopped(factory):
    now = datetime.utcnow()
    async with factory() as db:
        row = EnvironmentExecutionHistory(
            execution_type="sequence",
            cluster_id="c1",
            namespace="apps",
            operation="sequence_startup",
            status="running",
            total_deployments=2,
            sequence_id=1,
            initiated_by="u1",
            started_at=now - timedelta(minutes=5),
            cancel_requested_at=now - timedelta(minutes=3),
            cancel_requested_by="oncall@att.com",
            step_details=[
                {
                    "step": 1,
                    "deployment": "compadmin",
                    "status": "running",
                    "timeout_seconds": 3600,
                    "started_at": (now - timedelta(minutes=5)).isoformat() + "Z",
                    "last_progress_at": (now - timedelta(seconds=10)).isoformat() + "Z",
                },
                {"step": 2, "deployment": "web", "status": "pending"},
            ],
        )
        db.add(row)
        await db.commit()
        # Its executor is gone (replica restarted): 3 minutes without acting on the stop.
        assert await EnvironmentScalingService(db)._expire_abandoned_executions() == 1
        await db.refresh(row)

    assert row.status == "cancelled"
    assert [s["status"] for s in row.step_details] == ["cancelled", "not_run"]
    assert "no longer responding" in row.error_message


@pytest.mark.anyio
async def test_stop_endpoint(admin_client, db_engine, db_session):
    async with db_engine.begin() as conn:
        for model in ENV_TABLES:
            await conn.run_sync(lambda c, m=model: m.__table__.create(c, checkfirst=True))
    running = EnvironmentExecutionHistory(
        execution_type="sequence",
        cluster_id="c1",
        namespace="apps",
        operation="sequence_startup",
        status="running",
        total_deployments=1,
        sequence_id=5,
        initiated_by="u1",
        started_at=datetime.utcnow(),
        step_details=[
            {"step": 1, "deployment": "api", "status": "running", "started_at": datetime.utcnow().isoformat() + "Z"}
        ],
    )
    db_session.add(running)
    await db_session.commit()

    response = await admin_client.post(f"/api/v1/environment/history/{running.id}/stop", json={"rollback": True})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["cancel_requested_by"] == "admin@example.com" and body["cancel_rollback"] is True

    running.status = "completed"
    await db_session.commit()
    again = await admin_client.post(f"/api/v1/environment/history/{running.id}/stop", json={})
    assert again.status_code == 409
