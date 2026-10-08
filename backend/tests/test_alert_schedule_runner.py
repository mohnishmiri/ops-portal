"""Infra alert schedules run once per firing, however many workers fire them.

Every uvicorn worker on every replica runs its own scheduler, so each firing of
an alert schedule arrives several times within seconds (cron) or at each
worker's start-up offset (interval). Each copy used to run the checks and send
its own email.
"""

from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.ext.compiler import compiles

from app.models.database import AlertScheduleConfig
from app.services import scheduler_service


@compiles(JSONB, "sqlite")
def _jsonb_as_json_on_sqlite(_type, _compiler, **_kw):
    return "JSON"


@pytest.fixture
async def session_factory(tmp_path):
    # File-backed so separate sessions behave like separate workers' connections.
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'alert_schedules.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(lambda c: AlertScheduleConfig.__table__.create(c))
    yield async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    await engine.dispose()


async def _add_schedule(factory, **overrides) -> int:
    values = {
        "created_by": "test",
        "name": "Daily Alert Digest",
        "schedule_type": "cron",
        "interval_minutes": 1440,
        "cron_expression": "0 8 * * *",
        "check_vm_thresholds": False,
        "check_storage_thresholds": False,
        "check_disk_thresholds": False,
        "check_expiry_alerts": False,
        "check_pg_thresholds": False,
        "send_daily_digest": True,
        "digest_recipients": ["ops@att.com"],
        "is_enabled": True,
        **overrides,
    }
    async with factory() as db:
        schedule = AlertScheduleConfig(**values)
        db.add(schedule)
        await db.commit()
        return schedule.id


async def _load(db, schedule_id):
    return (await db.execute(select(AlertScheduleConfig).where(AlertScheduleConfig.id == schedule_id))).scalar_one()


def _config(**overrides):
    defaults = {"schedule_type": "interval", "interval_minutes": 15, "cron_expression": None}
    return SimpleNamespace(**{**defaults, **overrides})


@pytest.mark.parametrize(
    ("config", "expected"),
    [
        (_config(interval_minutes=15), timedelta(minutes=7, seconds=30)),
        (_config(interval_minutes=1), timedelta(seconds=30)),
        (_config(schedule_type="cron", cron_expression="0 8 * * *"), timedelta(hours=12)),
        # Uneven spacing: the shortest gap decides, or the 09:00 run would be blocked.
        (_config(schedule_type="cron", cron_expression="0 8,9 * * *"), timedelta(minutes=30)),
        (_config(schedule_type="cron", cron_expression="0 8 * * 1-5"), timedelta(hours=12)),
        (_config(schedule_type="cron", cron_expression="* * * * *"), timedelta(seconds=30)),
    ],
)
def test_min_gap_is_half_the_shortest_spacing(config, expected):
    assert scheduler_service._alert_schedule_min_gap(config) == expected


@pytest.mark.anyio
async def test_only_one_worker_claims_a_firing(session_factory):
    schedule_id = await _add_schedule(session_factory)
    now = datetime.utcnow()

    async with session_factory() as worker_a, session_factory() as worker_b:
        seen_by_a = await _load(worker_a, schedule_id)
        seen_by_b = await _load(worker_b, schedule_id)

        assert await scheduler_service._claim_alert_schedule(worker_a, seen_by_a, now) is True
        assert await scheduler_service._claim_alert_schedule(worker_b, seen_by_b, now + timedelta(seconds=2)) is False

    # The next day's firing is a new run.
    async with session_factory() as worker_b:
        seen = await _load(worker_b, schedule_id)
        assert await scheduler_service._claim_alert_schedule(worker_b, seen, now + timedelta(days=1)) is True


@pytest.mark.anyio
async def test_disabled_schedule_is_not_claimed(session_factory):
    schedule_id = await _add_schedule(session_factory, is_enabled=False)

    async with session_factory() as db:
        seen = await _load(db, schedule_id)
        assert await scheduler_service._claim_alert_schedule(db, seen, datetime.utcnow()) is False


@pytest.mark.anyio
async def test_a_firing_runs_once_across_workers(session_factory, monkeypatch):
    schedule_id = await _add_schedule(session_factory, check_vm_thresholds=True)
    digests: list[list[str] | None] = []
    vm_checks: list[bool] = []

    async def _sessions():
        async with session_factory() as db:
            yield db

    async def _digest(digest_recipients=None):
        digests.append(digest_recipients)

    async def _vm_check():
        vm_checks.append(True)

    monkeypatch.setattr(scheduler_service, "get_db_session", _sessions)
    monkeypatch.setattr(scheduler_service, "send_daily_digest_job", _digest)
    monkeypatch.setattr(scheduler_service, "check_vm_thresholds_job", _vm_check)

    for _worker in range(4):
        await scheduler_service.execute_alert_schedule_job(schedule_id)

    assert vm_checks == [True]
    # The schedule's own recipients, not every digest schedule's pooled list.
    assert digests == [["ops@att.com"]]


class _Job:
    def __init__(self, job_id, name, trigger, next_run_time):
        self.id = job_id
        self.name = name
        self.trigger = trigger
        self.next_run_time = next_run_time


class _CountingScheduler:
    running = True

    def __init__(self, jobs):
        self.jobs = {job.id: job for job in jobs}
        self.added: list[str] = []

    def add_job(self, func, trigger, *, id=None, name=None, **kwargs):  # noqa: A002
        self.added.append(id)
        job = _Job(id, name, trigger, datetime.utcnow() + timedelta(minutes=15))
        self.jobs[id] = job
        return job

    def get_job(self, job_id):
        return self.jobs.get(job_id)

    def get_jobs(self):
        return list(self.jobs.values())

    def remove_job(self, job_id):
        self.jobs.pop(job_id, None)


@pytest.mark.anyio
async def test_resync_leaves_an_unchanged_job_alone(session_factory, monkeypatch):
    # The resync runs every minute; re-adding an interval job restarts its
    # countdown, so a 15-minute schedule would never fire.
    schedule_id = await _add_schedule(
        session_factory, schedule_type="interval", interval_minutes=15, cron_expression=None
    )
    async with session_factory() as db:
        config = await _load(db, schedule_id)
    job_id = scheduler_service._alert_schedule_job_id(schedule_id)
    due_at = datetime.utcnow() + timedelta(minutes=3)
    scheduler = _CountingScheduler(
        [_Job(job_id, config.name, scheduler_service._build_alert_schedule_trigger(config), due_at)]
    )

    async def _sessions():
        async with session_factory() as db:
            yield db

    monkeypatch.setattr(scheduler_service, "get_scheduler", lambda: scheduler)
    monkeypatch.setattr(scheduler_service, "get_db_session", _sessions)

    await scheduler_service.sync_alert_schedule_jobs()
    assert scheduler.added == []
    assert scheduler.jobs[job_id].next_run_time == due_at

    # An edit made through another worker is picked up on the next resync.
    async with session_factory() as db:
        (await _load(db, schedule_id)).interval_minutes = 30
        await db.commit()
    await scheduler_service.sync_alert_schedule_jobs()
    assert scheduler.added == [job_id]


class _Rows:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return self

    def all(self):
        return self._rows


class _DigestDb:
    def __init__(self):
        self.queries = 0

    async def execute(self, _statement):
        self.queries += 1
        # Active VM alerts, then active expiry alerts.
        if self.queries == 1:
            return _Rows([SimpleNamespace(vm_name="vm-1", metric_type="cpu", current_value=97.0, severity="critical")])
        return _Rows([])


@pytest.mark.anyio
async def test_digest_sends_one_copy_per_inbox(monkeypatch):
    sent: list[list[str]] = []

    class _Email:
        def __init__(self, _db):
            pass

        async def send_alert_digest(self, *, recipient_emails, vm_alerts, expiry_alerts):
            sent.append(recipient_emails)

    db = _DigestDb()

    async def _sessions():
        yield db

    monkeypatch.setattr(scheduler_service, "get_db_session", _sessions)
    monkeypatch.setattr(scheduler_service, "EmailNotificationService", _Email)

    await scheduler_service.send_daily_digest_job(digest_recipients=["Ops@att.com", " ops@att.com ", "lead@att.com"])

    assert sent == [["Ops@att.com", "lead@att.com"]]
