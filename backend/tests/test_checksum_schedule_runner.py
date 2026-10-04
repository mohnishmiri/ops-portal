from datetime import datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.ext.compiler import compiles

from app.models.database import ChecksumScheduleConfig
from app.services import scheduler_service


@compiles(JSONB, "sqlite")
def _jsonb_as_json_on_sqlite(_type, _compiler, **_kw):
    return "JSON"


@pytest.fixture
async def session_factory(tmp_path):
    # File-backed so separate sessions behave like separate replicas' connections.
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'schedules.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(lambda c: ChecksumScheduleConfig.__table__.create(c))
    yield async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    await engine.dispose()


async def _add_schedule(factory, **overrides) -> int:
    now = datetime.utcnow()
    values = {
        "created_by": "test",
        "name": "nightly",
        "module_type": "synapse",
        "workspace_name": "ws-a",
        "schedule_type": "interval",
        "interval_hours": 24,
        "is_enabled": True,
        "next_run_at": now - timedelta(minutes=1),
        **overrides,
    }
    async with factory() as db:
        schedule = ChecksumScheduleConfig(**values)
        db.add(schedule)
        await db.commit()
        return schedule.id


async def _load(db, schedule_id):
    return (
        await db.execute(select(ChecksumScheduleConfig).where(ChecksumScheduleConfig.id == schedule_id))
    ).scalar_one()


@pytest.mark.anyio
async def test_only_one_replica_claims_a_due_schedule(session_factory):
    schedule_id = await _add_schedule(session_factory)
    now = datetime.utcnow()

    async with session_factory() as replica_a, session_factory() as replica_b:
        seen_by_a = await _load(replica_a, schedule_id)
        seen_by_b = await _load(replica_b, schedule_id)

        assert await scheduler_service._claim_checksum_schedule(replica_a, seen_by_a, now) is True
        assert await scheduler_service._claim_checksum_schedule(replica_b, seen_by_b, now) is False

    async with session_factory() as db:
        stored = await _load(db, schedule_id)
    assert stored.last_run_at == now
    assert stored.next_run_at == now + timedelta(hours=24)


@pytest.mark.anyio
async def test_schedule_disabled_mid_tick_is_not_claimed(session_factory):
    schedule_id = await _add_schedule(session_factory)

    async with session_factory() as runner, session_factory() as editor:
        stale = await _load(runner, schedule_id)
        (await _load(editor, schedule_id)).is_enabled = False
        await editor.commit()

        assert await scheduler_service._claim_checksum_schedule(runner, stale, datetime.utcnow()) is False


@pytest.mark.anyio
async def test_runner_executes_each_due_schedule_once_across_replicas(session_factory, monkeypatch):
    await _add_schedule(session_factory, name="due")
    await _add_schedule(session_factory, name="later", next_run_at=datetime.utcnow() + timedelta(hours=1))
    executed: list[str] = []

    async def _sessions():
        async with session_factory() as db:
            yield db

    async def _execute(*, db, schedule, compliance_service):
        executed.append(schedule.name)

    monkeypatch.setattr(scheduler_service, "get_db_session", _sessions)
    monkeypatch.setattr(scheduler_service, "_execute_schedule_checksum", _execute)

    for _replica in range(3):
        await scheduler_service.run_checksum_schedules_job()

    assert executed == ["due"]
