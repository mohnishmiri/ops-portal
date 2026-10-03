"""
Compliance dashboard sync: a 'running' row left behind by a killed process is
expired before the next sync, and a full sync runs end to end.
"""

from datetime import datetime, timedelta

import pytest
from sqlalchemy import select

from app.core.db_cache import cache_manager
from app.models.database import ComplianceDashboardSnapshot, ComplianceSyncStatus
from app.services import compliance_sync_service as module
from app.services.compliance_sync_service import ComplianceSyncService


@pytest.fixture
async def db(db_engine, db_session):
    async with db_engine.begin() as conn:
        await conn.run_sync(lambda c: ComplianceSyncStatus.__table__.create(c, checkfirst=True))
        await conn.run_sync(lambda c: ComplianceDashboardSnapshot.__table__.create(c, checkfirst=True))
    return db_session


async def _add_running(db, minutes_ago: int) -> ComplianceSyncStatus:
    row = ComplianceSyncStatus(
        sync_type="full",
        status="running",
        started_at=datetime.utcnow() - timedelta(minutes=minutes_ago),
        triggered_by="scheduler",
    )
    db.add(row)
    await db.commit()
    return row


async def test_abandoned_running_rows_are_expired(db):
    abandoned = await _add_running(db, minutes_ago=120)
    in_progress = await _add_running(db, minutes_ago=5)

    expired = await ComplianceSyncService(db)._expire_abandoned_running_rows()

    await db.refresh(abandoned)
    await db.refresh(in_progress)
    assert expired == 1
    assert abandoned.status == "failed"
    assert abandoned.completed_at is not None
    assert "abandoned" in abandoned.error_message
    assert in_progress.status == "running"


class FakeComplianceService:
    def __init__(self, _db):
        pass

    async def get_compliance_dashboard(self, subscription_ids=None):
        return {"summary": {"total": 3}}

    async def get_checksum_metrics(self, days=30, module_type=None):
        return {"days": days}


async def test_full_sync_runs_after_an_abandoned_sync(db, monkeypatch):
    abandoned = await _add_running(db, minutes_ago=120)
    monkeypatch.setattr(module, "ComplianceService", FakeComplianceService)

    async def _no_collection(self, _svc):
        return None

    async def _invalidate(_pattern):
        return 0

    monkeypatch.setattr(ComplianceSyncService, "_collect_compliance_data", _no_collection)
    monkeypatch.setattr(cache_manager, "invalidate", _invalidate)

    result = await ComplianceSyncService(db).full_sync(triggered_by="startup")

    await db.refresh(abandoned)
    snapshots = (await db.execute(select(ComplianceDashboardSnapshot.snapshot_type))).scalars().all()
    assert result["status"] == "completed"
    assert abandoned.status == "failed"
    assert sorted(snapshots) == ["dashboard", "metrics"]
