"""Environment Scheduler sequence execution: repeated steps, ordering, rollback,
concurrency guard, abandoned-run sweep, and the schedule runner claim."""

from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
from kubernetes.client.rest import ApiException
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.ext.compiler import compiles

from app.models.database import AuditLog, EnvironmentExecutionHistory, EnvironmentSchedule, EnvironmentSequence
from app.services import scheduler_service
from app.services.environment_scaling_service import (
    EnvironmentScalingService,
    SequenceAlreadyRunningError,
    SequenceInUseError,
    _describe_error,
)


@compiles(JSONB, "sqlite")
def _jsonb_as_json_on_sqlite(_type, _compiler, **_kw):
    return "JSON"


class FakeAks:
    """Records scale calls; pods become ready as soon as they are requested."""

    def __init__(self, replicas: dict[str, int], fail: set[tuple[str, int]] | None = None, ready_cap=None):
        self.replicas = dict(replicas)
        self.fail = fail or set()
        self.ready_cap = ready_cap or {}
        self.calls: list[tuple[str, int]] = []

    async def scale_deployment(self, *, cluster_id, namespace, deployment_name, replicas, user_id, user_email):
        self.calls.append((deployment_name, replicas))
        if (deployment_name, replicas) in self.fail:
            raise ApiException(status=404, reason="Not Found")
        previous = self.replicas.get(deployment_name, 0)
        self.replicas[deployment_name] = replicas
        return {"previous_replicas": previous, "new_replicas": replicas}

    async def _get_k8s_clients(self, cluster_id):
        def read_status(name, namespace):
            ready = min(self.replicas.get(name, 0), self.ready_cap.get(name, 10_000))
            return SimpleNamespace(status=SimpleNamespace(ready_replicas=ready, available_replicas=ready))

        return SimpleNamespace(read_namespaced_deployment_status=read_status), None, None


@pytest.fixture
async def factory(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'env.db'}")
    async with engine.begin() as conn:
        for model in (EnvironmentSequence, EnvironmentSchedule, EnvironmentExecutionHistory, AuditLog):
            await conn.run_sync(lambda c, m=model: m.__table__.create(c))
    yield async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    await engine.dispose()


def _step(order, name, replicas=1, **extra):
    return {
        "order": order,
        "deployment_name": name,
        "replicas": replicas,
        "wait_condition": "pods_ready",
        "timeout_seconds": 0,
        "on_failure": "abort",
        **extra,
    }


async def _add_sequence(factory, steps, *, sequence_type="startup", rollback=True, name="seq") -> int:
    async with factory() as db:
        seq = EnvironmentSequence(
            name=name,
            cluster_id="/subscriptions/s1/resourceGroups/rg/providers/Microsoft.ContainerService/managedClusters/c1",
            namespace="apps",
            sequence_type=sequence_type,
            steps=steps,
            rollback_on_failure=rollback,
            created_by="u1",
        )
        db.add(seq)
        await db.commit()
        return seq.id


async def _run(factory, sequence_id, aks):
    async with factory() as db:
        service = EnvironmentScalingService(db)
        service._aks = aks
        return await service.execute_sequence(
            sequence_id=sequence_id, replica_count=1, dry_run=False, user_id="u1", user_email="u1@example.com"
        )


@pytest.mark.anyio
async def test_same_deployment_can_be_scaled_in_several_steps(factory):
    seq_id = await _add_sequence(factory, [_step(1, "api", 1), _step(2, "db", 2), _step(3, "api", 50)])
    aks = FakeAks({"api": 0, "db": 0})

    result = await _run(factory, seq_id, aks)

    assert result["status"] == "completed"
    assert aks.calls == [("api", 1), ("db", 2), ("api", 50)]
    assert [(s["step"], s["deployment"], s["current_replicas"], s["target_replicas"]) for s in result["details"]] == [
        (1, "api", 0, 1),
        (2, "db", 0, 2),
        (3, "api", 1, 50),
    ]
    assert all(s["status"] == "completed" for s in result["details"])


@pytest.mark.anyio
async def test_shutdown_runs_top_down_as_listed(factory):
    seq_id = await _add_sequence(
        factory, [_step(1, "web", 0), _step(2, "api", 0), _step(3, "db", 0)], sequence_type="shutdown"
    )
    aks = FakeAks({"web": 2, "api": 2, "db": 1})

    result = await _run(factory, seq_id, aks)

    assert result["status"] == "completed"
    assert aks.calls == [("web", 0), ("api", 0), ("db", 0)]
    assert {s["wait_condition"] for s in result["details"]} == {"skip"}


@pytest.mark.anyio
async def test_aborted_startup_rolls_back_to_previous_counts_newest_first(factory):
    # Step 3 scales but its pods never get ready, so it times out after scaling.
    seq_id = await _add_sequence(
        factory, [_step(1, "api", 1), _step(2, "api", 5), _step(3, "db", 3), _step(4, "web", 1)]
    )
    aks = FakeAks({"api": 0, "db": 0, "web": 0}, ready_cap={"db": 1})

    result = await _run(factory, seq_id, aks)

    assert result["status"] == "rolled_back"
    statuses = [s["status"] for s in result["details"]]
    assert statuses == ["completed", "completed", "failed", "not_run"]
    assert "only 1/3 pods ready" in result["details"][2]["error"]
    # db 3 → 0 (the failed step had scaled), api 5 → 1, api 1 → 0.
    assert aks.calls[3:] == [("db", 0), ("api", 1), ("api", 0)]
    assert aks.replicas == {"api": 0, "db": 0, "web": 0}
    assert "Aborted at step 3 (db)" in result["error"]


@pytest.mark.anyio
async def test_rollback_keeps_a_deployment_that_was_already_running(factory):
    seq_id = await _add_sequence(factory, [_step(1, "api", 4), _step(2, "missing", 1)])
    aks = FakeAks({"api": 2}, fail={("missing", 1)})

    result = await _run(factory, seq_id, aks)

    assert result["status"] == "rolled_back"
    assert aks.replicas["api"] == 2  # restored, not scaled to 0
    assert result["details"][1]["error"] == "Kubernetes API 404: Not Found"


@pytest.mark.anyio
async def test_failed_shutdown_is_not_rolled_back(factory):
    seq_id = await _add_sequence(
        factory, [_step(1, "web", 0), _step(2, "missing", 0), _step(3, "db", 0)], sequence_type="shutdown"
    )
    aks = FakeAks({"web": 2, "db": 1}, fail={("missing", 0)})

    result = await _run(factory, seq_id, aks)

    assert result["status"] == "failed"
    assert aks.calls == [("web", 0), ("missing", 0)]
    assert aks.replicas["web"] == 0
    assert [s["status"] for s in result["details"]] == ["completed", "failed", "not_run"]


@pytest.mark.anyio
async def test_continue_on_failure_runs_the_remaining_steps(factory):
    seq_id = await _add_sequence(
        factory, [_step(1, "missing", 1, on_failure="continue"), _step(2, "api", 1)], rollback=True
    )
    aks = FakeAks({"api": 0}, fail={("missing", 1)})

    result = await _run(factory, seq_id, aks)

    assert result["status"] == "failed"
    assert [s["status"] for s in result["details"]] == ["failed", "completed"]
    assert aks.replicas["api"] == 1  # no rollback without an abort
    assert "Continue on failure" in result["error"]


@pytest.mark.anyio
async def test_health_endpoint_wait_finishes_when_pods_are_ready(factory):
    seq_id = await _add_sequence(factory, [_step(1, "api", 2, wait_condition="health_endpoint")])

    result = await _run(factory, seq_id, FakeAks({"api": 0}))

    assert result["status"] == "completed"


@pytest.mark.anyio
async def test_a_running_sequence_cannot_be_started_twice(factory):
    seq_id = await _add_sequence(factory, [_step(1, "api", 1)])
    async with factory() as db:
        service = EnvironmentScalingService(db)
        await service.begin_sequence_execution(sequence_id=seq_id, user_id="u1", user_email="u1@example.com")
        with pytest.raises(SequenceAlreadyRunningError):
            await service.begin_sequence_execution(sequence_id=seq_id, user_id="u2", user_email="u2@example.com")


@pytest.mark.anyio
async def test_abandoned_runs_are_failed_but_live_ones_are_left_alone(factory):
    now = datetime.utcnow()
    async with factory() as db:
        stale_step = {
            "step": 1,
            "deployment": "api",
            "status": "running",
            "timeout_seconds": 60,
            "started_at": (now - timedelta(hours=1)).isoformat() + "Z",
        }
        live_step = {**stale_step, "started_at": (now - timedelta(seconds=30)).isoformat() + "Z"}
        pending = {"step": 2, "deployment": "db", "status": "pending"}
        for steps in ([stale_step, pending], [live_step, pending]):
            db.add(
                EnvironmentExecutionHistory(
                    execution_type="sequence",
                    cluster_id="c1",
                    namespace="apps",
                    operation="sequence_startup",
                    status="running",
                    total_deployments=2,
                    step_details=steps,
                    sequence_id=1,
                    initiated_by="u1",
                    started_at=now - timedelta(hours=1),
                )
            )
        await db.commit()

        assert await EnvironmentScalingService(db)._expire_abandoned_executions() == 1
        rows = (
            (await db.execute(select(EnvironmentExecutionHistory).order_by(EnvironmentExecutionHistory.id)))
            .scalars()
            .all()
        )

    assert rows[0].status == "failed"
    assert [s["status"] for s in rows[0].step_details] == ["interrupted", "not_run"]
    assert rows[1].status == "running"


@pytest.mark.anyio
async def test_history_names_the_sequence_that_ran(factory):
    seq_id = await _add_sequence(factory, [_step(1, "api", 1)], name="SCAL-Up-RTL")
    await _run(factory, seq_id, FakeAks({"api": 0}))

    async with factory() as db:
        history = await EnvironmentScalingService(db).get_execution_history()

    assert history[0]["sequence_name"] == "SCAL-Up-RTL"
    assert history[0]["status"] == "completed"


@pytest.mark.anyio
async def test_a_sequence_used_by_a_schedule_cannot_be_deleted(factory):
    seq_id = await _add_sequence(factory, [_step(1, "api", 1)])
    async with factory() as db:
        db.add(
            EnvironmentSchedule(
                job_name="morning-start",
                cluster_id="c1",
                namespace="apps",
                operation="scale_up",
                schedule_type="daily",
                sequence_id=seq_id,
                created_by="u1",
            )
        )
        await db.commit()
        with pytest.raises(SequenceInUseError, match="morning-start"):
            await EnvironmentScalingService(db).delete_sequence(seq_id)


def test_kubernetes_errors_are_summarised_for_history():
    exc = ApiException(status=404, reason="Not Found")
    exc.body = '{"kind":"Status","message":"deployments.apps \\"api\\" not found"}'
    assert _describe_error(exc) == 'Kubernetes API 404: deployments.apps "api" not found'


async def _add_env_schedule(factory, **overrides) -> int:
    values = {
        "job_name": "nightly",
        "cluster_id": "c1",
        "namespace": "apps",
        "operation": "scale_down",
        "schedule_type": "daily",
        "created_by": "u1",
        "is_enabled": True,
        "next_run_at": datetime.utcnow() - timedelta(minutes=1),
        **overrides,
    }
    async with factory() as db:
        schedule = EnvironmentSchedule(**values)
        db.add(schedule)
        await db.commit()
        return schedule.id


@pytest.mark.anyio
async def test_only_one_replica_claims_a_due_environment_schedule(factory):
    schedule_id = await _add_env_schedule(factory)
    now = datetime.utcnow()

    async with factory() as replica_a, factory() as replica_b:
        load = select(EnvironmentSchedule).where(EnvironmentSchedule.id == schedule_id)
        seen_by_a = (await replica_a.execute(load)).scalar_one()
        seen_by_b = (await replica_b.execute(load)).scalar_one()

        assert await scheduler_service._claim_env_schedule(replica_a, seen_by_a, now) is True
        assert await scheduler_service._claim_env_schedule(replica_b, seen_by_b, now) is False


@pytest.mark.anyio
async def test_a_one_time_schedule_is_disabled_once_claimed(factory):
    schedule_id = await _add_env_schedule(factory, schedule_type="one_time")
    now = datetime.utcnow()

    async with factory() as db:
        schedule = (
            await db.execute(select(EnvironmentSchedule).where(EnvironmentSchedule.id == schedule_id))
        ).scalar_one()
        assert await scheduler_service._claim_env_schedule(db, schedule, now) is True
        # A NULL next_run_at reads as due; disabled is what stops the next tick.
        assert schedule.is_enabled is False
        assert await scheduler_service._claim_env_schedule(db, schedule, now) is False
