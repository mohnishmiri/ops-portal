"""Environment schedules: standard cron weekdays, Run Now of sequence-linked
schedules in the background, and the runner launching runs concurrently but
one at a time per namespace."""

import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.ext.compiler import compiles

from app.models.database import AuditLog, EnvironmentExecutionHistory, EnvironmentSchedule, EnvironmentSequence
from app.services import environment_scaling_service as env_module
from app.services import scheduler_service
from app.services.environment_scaling_service import EnvironmentScalingService


@compiles(JSONB, "sqlite")
def _jsonb_as_json_on_sqlite(_type, _compiler, **_kw):
    return "JSON"


ENV_TABLES = (EnvironmentSequence, EnvironmentSchedule, EnvironmentExecutionHistory)


@pytest.fixture
async def factory(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'env.db'}")
    async with engine.begin() as conn:
        for model in (*ENV_TABLES, AuditLog):
            await conn.run_sync(lambda c, m=model: m.__table__.create(c))
    yield async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    await engine.dispose()


def _sessions_from(factory):
    async def _get_db_session():
        async with factory() as db:
            yield db

    return _get_db_session


class FakeAks:
    def __init__(self):
        self.replicas: dict[str, int] = {}

    async def scale_deployment(self, *, cluster_id, namespace, deployment_name, replicas, user_id, user_email):
        previous = self.replicas.get(deployment_name, 0)
        self.replicas[deployment_name] = replicas
        return {"previous_replicas": previous}

    async def _get_k8s_clients(self, cluster_id):
        def read_status(name, namespace):
            ready = self.replicas.get(name, 0)
            return SimpleNamespace(status=SimpleNamespace(ready_replicas=ready, available_replicas=ready))

        return SimpleNamespace(read_namespaced_deployment_status=read_status), None, None


async def _add(factory, obj):
    async with factory() as db:
        db.add(obj)
        await db.commit()
        return obj.id


def _schedule(**overrides) -> EnvironmentSchedule:
    values = {
        "job_name": "weekday-start",
        "cluster_id": "c1",
        "namespace": "apps",
        "operation": "scale_up",
        "schedule_type": "cron",
        "cron_expression": "0 8 * * 1-5",
        "timezone": "UTC",
        "created_by": "creator",
        "created_by_email": "creator@example.com",
        "is_enabled": True,
        "next_run_at": datetime.utcnow() - timedelta(minutes=1),
        **overrides,
    }
    return EnvironmentSchedule(**values)


def _sequence(**overrides) -> EnvironmentSequence:
    values = {
        "name": "SCAL-Up-RTL",
        "cluster_id": "c1",
        "namespace": "apps",
        "sequence_type": "startup",
        "rollback_on_failure": True,
        "created_by": "u1",
        "steps": [
            {
                "order": 1,
                "deployment_name": "api",
                "replicas": 2,
                "wait_condition": "pods_ready",
                "timeout_seconds": 0,
                "on_failure": "abort",
            }
        ],
        **overrides,
    }
    return EnvironmentSequence(**values)


# ── 1. Standard crontab weekdays ─────────────────────────────────────────────

# 2026-10-09 is a Friday, 2026-10-12 a Monday.
FRIDAY_9AM = datetime(2026, 10, 9, 9, 0)


def test_weekday_cron_runs_monday_to_friday():
    schedule = SimpleNamespace(schedule_type="cron", cron_expression="0 8 * * 1-5", timezone="UTC")
    # The old reading (0=Mon) made "1-5" Tue–Sat, so the next run was Saturday.
    assert scheduler_service._compute_env_schedule_next_run(schedule, FRIDAY_9AM) == datetime(2026, 10, 12, 8, 0)


def test_weekday_cron_respects_the_schedule_timezone():
    schedule = SimpleNamespace(schedule_type="cron", cron_expression="0 8 * * 1-5", timezone="America/Chicago")
    # 08:00 CDT on Monday is 13:00 UTC.
    assert scheduler_service._compute_env_schedule_next_run(schedule, FRIDAY_9AM + timedelta(hours=6)) == datetime(
        2026, 10, 12, 13, 0
    )


def test_new_schedule_first_run_uses_standard_weekdays():
    schedule = SimpleNamespace(schedule_type="cron", cron_expression="0 8 * * 0", timezone="UTC", start_date=None)
    assert EnvironmentScalingService._compute_next_run(schedule).weekday() == 6  # Sunday, not Monday


def test_alert_schedule_cron_uses_standard_weekdays():
    config = SimpleNamespace(schedule_type="cron", cron_expression="0 8 * * 0", interval_minutes=None)
    trigger = scheduler_service._build_alert_schedule_trigger(config)
    assert trigger.get_next_fire_time(None, datetime(2026, 10, 7, tzinfo=UTC)).weekday() == 6


@pytest.mark.anyio
async def test_realign_moves_future_runs_to_the_correct_day_once(factory, monkeypatch):
    monkeypatch.setattr(scheduler_service, "get_db_session", _sessions_from(factory))
    now = datetime.utcnow()
    days_to_saturday = (5 - now.weekday()) % 7 or 7
    wrong_saturday = datetime.combine(now.date() + timedelta(days=days_to_saturday), datetime.min.time()).replace(
        hour=8
    )
    due = now - timedelta(minutes=1)

    shifted = await _add(factory, _schedule(next_run_at=wrong_saturday))
    already_due = await _add(factory, _schedule(job_name="due", next_run_at=due))
    daily = await _add(factory, _schedule(job_name="daily", schedule_type="daily", next_run_at=wrong_saturday))
    invalid = await _add(factory, _schedule(job_name="bad", cron_expression="not a cron", next_run_at=wrong_saturday))
    disabled = await _add(factory, _schedule(job_name="off", is_enabled=False, next_run_at=wrong_saturday))

    assert await scheduler_service.realign_env_cron_schedules() == 1
    assert await scheduler_service.realign_env_cron_schedules() == 0  # idempotent

    async with factory() as db:
        rows = {s.id: s for s in (await db.execute(select(EnvironmentSchedule))).scalars().all()}
    corrected = rows[shifted].next_run_at
    assert corrected.weekday() < 5 and corrected.hour == 8 and now < corrected <= now + timedelta(days=4)
    assert rows[already_due].next_run_at == due
    for untouched in (daily, invalid, disabled):
        assert rows[untouched].next_run_at == wrong_saturday


# ── 2. Run Now of a sequence-linked schedule ─────────────────────────────────


@pytest.mark.anyio
async def test_run_now_records_the_clicking_user_and_marks_the_schedule_running(factory):
    seq_id = await _add(factory, _sequence())
    schedule_id = await _add(factory, _schedule(sequence_id=seq_id))

    async with factory() as db:
        service = EnvironmentScalingService(db)
        schedule = await service.load_schedule_for_run(schedule_id)
        _, execution = await service.begin_scheduled_sequence(schedule, user_id="clicker", user_email="ops@example.com")

    assert execution.execution_type == "scheduled"
    assert execution.schedule_id == schedule_id
    assert execution.initiated_by_email == "ops@example.com"
    assert execution.status == "running"
    assert schedule.last_run_status == "running"


@pytest.mark.anyio
async def test_background_run_finishes_the_schedule_and_notifies(factory, monkeypatch):
    import app.core.database as database

    seq_id = await _add(factory, _sequence())
    schedule_id = await _add(factory, _schedule(sequence_id=seq_id))
    async with factory() as db:
        service = EnvironmentScalingService(db)
        schedule = await service.load_schedule_for_run(schedule_id)
        _, execution = await service.begin_scheduled_sequence(schedule, user_id="clicker", user_email="ops@example.com")

    notified: list[str] = []

    async def _notify(self, schedule, result):
        notified.append(result["status"])

    monkeypatch.setattr(database, "get_db_session", _sessions_from(factory))
    monkeypatch.setattr(env_module, "get_aks_operations_service", lambda db: FakeAks())
    monkeypatch.setattr(EnvironmentScalingService, "_send_schedule_notification", _notify)

    await env_module._run_sequence_in_background(
        sequence_id=seq_id,
        execution_id=execution.id,
        user_id="clicker",
        user_email="ops@example.com",
        schedule_id=schedule_id,
    )

    async with factory() as db:
        stored_schedule = await db.get(EnvironmentSchedule, schedule_id)
        stored_execution = await db.get(EnvironmentExecutionHistory, execution.id)
    assert stored_execution.status == "completed"
    assert stored_schedule.last_run_status == "completed"
    assert notified == ["completed"]


@pytest.mark.anyio
async def test_run_now_endpoint_returns_at_once_for_a_sequence_schedule(
    admin_client, db_engine, db_session, monkeypatch
):
    async with db_engine.begin() as conn:
        for model in ENV_TABLES:
            await conn.run_sync(lambda c, m=model: m.__table__.create(c, checkfirst=True))
    seq = _sequence()
    db_session.add(seq)
    await db_session.commit()
    schedule = _schedule(sequence_id=seq.id)
    db_session.add(schedule)
    await db_session.commit()

    launched: list[dict] = []
    monkeypatch.setattr("app.api.v1.endpoints.environment.launch_sequence_run", lambda **kw: launched.append(kw))

    response = await admin_client.post(f"/api/v1/environment/schedule/{schedule.id}/run")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "running"
    assert launched == [
        {
            "sequence_id": seq.id,
            "execution_id": body["execution_id"],
            "user_id": "test-admin",
            "user_email": "admin@example.com",
            "schedule_id": schedule.id,
        }
    ]

    # A second click while it runs is refused instead of starting a parallel run.
    again = await admin_client.post(f"/api/v1/environment/schedule/{schedule.id}/run")
    assert again.status_code == 409
    assert "already running" in again.json()["detail"]


@pytest.mark.anyio
async def test_an_abandoned_scheduled_run_does_not_leave_the_schedule_running(factory):
    schedule_id = await _add(factory, _schedule(last_run_status="running"))
    await _add(
        factory,
        EnvironmentExecutionHistory(
            execution_type="scheduled",
            cluster_id="c1",
            namespace="apps",
            operation="scale_up",
            status="running",
            total_deployments=1,
            schedule_id=schedule_id,
            initiated_by="u1",
            started_at=datetime.utcnow() - timedelta(hours=2),
        ),
    )

    async with factory() as db:
        assert await EnvironmentScalingService(db)._expire_abandoned_executions() == 1
    async with factory() as db:
        assert (await db.get(EnvironmentSchedule, schedule_id)).last_run_status == "failed"


# ── 3. Runner: concurrent, one run per namespace ─────────────────────────────


@pytest.mark.anyio
async def test_runner_launches_due_schedules_without_waiting_for_them(factory, monkeypatch):
    monkeypatch.setattr(scheduler_service, "get_db_session", _sessions_from(factory))
    launched: list[tuple[int, str]] = []
    monkeypatch.setattr(
        scheduler_service, "_launch_env_schedule_run", lambda sid, cluster, ns: launched.append((sid, ns))
    )

    first = await _add(factory, _schedule(job_name="a", namespace="apps"))
    second = await _add(factory, _schedule(job_name="b", namespace="batch"))
    busy = await _add(factory, _schedule(job_name="c", namespace="busy"))
    await _add(
        factory,
        EnvironmentExecutionHistory(
            execution_type="manual",
            cluster_id="c1",
            namespace="busy",
            operation="scale_up",
            status="running",
            total_deployments=1,
            initiated_by="u1",
            started_at=datetime.utcnow(),
        ),
    )

    await scheduler_service.run_environment_schedules_job()

    assert sorted(launched) == sorted([(first, "apps"), (second, "batch")])
    async with factory() as db:
        waiting = await db.get(EnvironmentSchedule, busy)
    # Not claimed: it stays due and starts once the namespace is free.
    assert waiting.next_run_at <= datetime.utcnow()


@pytest.mark.anyio
async def test_runs_in_one_namespace_never_overlap_but_other_namespaces_do(monkeypatch):
    namespaces = {1: "apps", 2: "apps", 3: "batch"}
    active: dict[str, int] = {}
    overlaps: list[str] = []
    peak = {"now": 0, "max": 0}

    class FakeService:
        async def execute_scheduled_job(self, schedule_id):
            ns = namespaces[schedule_id]
            active[ns] = active.get(ns, 0) + 1
            peak["now"] += 1
            peak["max"] = max(peak["max"], peak["now"])
            if active[ns] > 1:
                overlaps.append(ns)
            await asyncio.sleep(0.02)
            active[ns] -= 1
            peak["now"] -= 1

    async def _sessions():
        yield None

    monkeypatch.setattr(scheduler_service, "get_db_session", _sessions)
    monkeypatch.setattr(env_module, "get_environment_scaling_service", lambda db: FakeService())

    await asyncio.gather(*(scheduler_service._run_env_schedule(sid, "c1", ns) for sid, ns in namespaces.items()))

    assert overlaps == []
    assert peak["max"] == 2  # apps and batch ran side by side
