"""Infra alert lifecycle: one open alert per config, auto-resolve, no re-fire after acknowledge.

Runs the real queries against SQLite (JSONB compiled as JSON). Azure Monitor and
email are faked; everything else — the alert rows, their statuses, who resolved
them — is what the portal would store.
"""

from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.ext.compiler import compiles

from app.api.v1.endpoints import infra_alerts
from app.models.database import (
    AlertScheduleConfig,
    AuditLog,
    AzureResourceInventory,
    CertificateAutomationClaim,
    CustomExpiryAlert,
    CustomExpiryAlertConfig,
    PGFlexServerAlert,
    PGFlexServerAlertConfig,
    VMThresholdAlert,
    VMThresholdAlertConfig,
)
from app.services import infra_alert_service, scheduler_service
from app.services.azure_resource_service import AzureResourceService
from app.services.infra_alert_service import InfraAlertService, days_until_expiry

_TABLES = (
    VMThresholdAlertConfig,
    VMThresholdAlert,
    CustomExpiryAlertConfig,
    CustomExpiryAlert,
    PGFlexServerAlertConfig,
    PGFlexServerAlert,
    AlertScheduleConfig,
    CertificateAutomationClaim,
    AzureResourceInventory,
    AuditLog,
)


@compiles(JSONB, "sqlite")
def _jsonb_as_json_on_sqlite(_type, _compiler, **_kw):
    return "JSON"


@pytest.fixture
async def factory(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'infra_alerts.db'}")
    async with engine.begin() as conn:
        for model in _TABLES:
            await conn.run_sync(lambda c, table=model.__table__: table.create(c))
    # Same session options as the app (app.core.database).
    yield async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False, autoflush=False)
    await engine.dispose()


class _Mail:
    """Records what would have been emailed."""

    sent: list[tuple[str, dict]] = []

    def __init__(self, _db):
        pass

    async def send_vm_threshold_alert(self, **kwargs):
        _Mail.sent.append(("threshold", kwargs))

    async def send_expiry_alert(self, **kwargs):
        _Mail.sent.append(("expiry", kwargs))

    async def send_alert_status_change(self, **kwargs):
        _Mail.sent.append(("status", kwargs))


@pytest.fixture(autouse=True)
def _fakes(monkeypatch):
    _Mail.sent = []
    monkeypatch.setattr(infra_alert_service, "EmailNotificationService", _Mail)

    async def _scope():
        return ["sub-1", "sub-2"]

    monkeypatch.setattr(infra_alert_service, "get_scoped_subscription_ids", _scope)


def _kinds() -> list[str]:
    return [kind for kind, _ in _Mail.sent]


async def _add(factory, row):
    async with factory() as db:
        db.add(row)
        await db.commit()
        return row.id


async def _all(factory, model, **filters):
    async with factory() as db:
        stmt = select(model).order_by(model.id)
        for key, value in filters.items():
            stmt = stmt.where(getattr(model, key) == value)
        return list((await db.execute(stmt)).scalars().all())


def _vm_config(**overrides) -> VMThresholdAlertConfig:
    values = {
        "created_by": "t",
        "subscription_id": "sub-2",
        "resource_group": "RG",
        "vm_name": "vm-1",
        "vm_id": "/subscriptions/sub-2/resourceGroups/RG/providers/Microsoft.Compute/virtualMachines/vm-1",
        "cpu_warning_threshold": 70.0,
        "cpu_critical_threshold": 90.0,
        "memory_warning_threshold": 75.0,
        "memory_critical_threshold": 90.0,
        "disk_warning_threshold": 80.0,
        "disk_critical_threshold": 95.0,
        "notification_emails": ["ops@att.com"],
        **overrides,
    }
    return VMThresholdAlertConfig(**values)


def _expiry_config(expires_in_days: int, **overrides) -> CustomExpiryAlertConfig:
    today = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    values = {
        "created_by": "t",
        "alert_type": "itservices_domain",
        "resource_name": "m52142",
        "resource_identifier": "m52142",
        "expiry_date": today + timedelta(days=expires_in_days),
        "warning_days_before": 30,
        "critical_days_before": 7,
        "notification_emails": ["ops@att.com"],
        **overrides,
    }
    return CustomExpiryAlertConfig(**values)


def _readings(service, values: dict):
    async def _metrics(_sub, _rg, _name):
        return dict(values)

    service.get_vm_metrics = _metrics


# ── Days left ──────────────────────────────────────────────────────────


def test_days_left_counts_calendar_days_not_elapsed_hours():
    late_today = datetime(2026, 10, 11, 23, 59)
    tomorrow_midnight = datetime(2026, 10, 12)
    # (tomorrow - now).days floored this to 0 and the grid said "EXPIRED".
    assert (tomorrow_midnight - late_today).days == 0
    assert days_until_expiry(tomorrow_midnight, late_today.date()) == 1
    assert days_until_expiry(datetime(2026, 10, 11), late_today.date()) == 0
    assert days_until_expiry(datetime(2026, 6, 28), late_today.date()) == -105


# ── VM threshold alerts ────────────────────────────────────────────────


@pytest.mark.anyio
async def test_vm_check_reads_the_metric_keys_the_reader_returns(factory):
    # The scheduler looked up "cpu_percent" etc. while get_vm_metrics returns
    # "cpu" / "memory" / "disk", so every reading was 0 and no VM alert ever fired.
    await _add(factory, _vm_config())
    async with factory() as db:
        service = InfraAlertService(db)
        _readings(service, {"cpu": 93.5, "memory": 40.0, "disk": 12.0})
        summary = await service.check_and_generate_vm_alerts()

    assert summary["created"] == 1
    [alert] = await _all(factory, VMThresholdAlert)
    assert (alert.metric_type, alert.severity) == ("cpu", "critical")
    assert (alert.current_value, alert.threshold_value) == (93.5, 90.0)
    assert _kinds() == ["threshold"]


@pytest.mark.anyio
async def test_acknowledged_vm_alert_is_not_raised_again(factory):
    await _add(factory, _vm_config())
    async with factory() as db:
        service = InfraAlertService(db)
        _readings(service, {"cpu": 75.0, "memory": None, "disk": None})
        await service.check_and_generate_vm_alerts()
        [alert] = await _all(factory, VMThresholdAlert)
        await service.acknowledge_vm_alert(alert.id, "lead@att.com")
        _Mail.sent = []

        # Still breaching at the same severity: update in place, no new row, no email.
        _readings(service, {"cpu": 78.0, "memory": None, "disk": None})
        await service.check_and_generate_vm_alerts()

    [alert] = await _all(factory, VMThresholdAlert)
    assert alert.status == "acknowledged"
    assert alert.current_value == 78.0
    assert _Mail.sent == []


@pytest.mark.anyio
async def test_worse_severity_reopens_an_acknowledged_alert(factory):
    await _add(factory, _vm_config())
    async with factory() as db:
        service = InfraAlertService(db)
        _readings(service, {"cpu": 75.0, "memory": None, "disk": None})
        await service.check_and_generate_vm_alerts()
        [alert] = await _all(factory, VMThresholdAlert)
        await service.acknowledge_vm_alert(alert.id, "lead@att.com")
        _Mail.sent = []

        _readings(service, {"cpu": 96.0, "memory": None, "disk": None})
        summary = await service.check_and_generate_vm_alerts()

    [alert] = await _all(factory, VMThresholdAlert)
    assert summary["escalated"] == 1
    assert (alert.status, alert.severity) == ("active", "critical")
    assert _kinds() == ["threshold"]


@pytest.mark.anyio
async def test_recovered_metric_resolves_the_alert(factory):
    await _add(factory, _vm_config())
    async with factory() as db:
        service = InfraAlertService(db)
        _readings(service, {"cpu": 91.0, "memory": None, "disk": None})
        await service.check_and_generate_vm_alerts()
        _Mail.sent = []

        _readings(service, {"cpu": 31.0, "memory": None, "disk": None})
        summary = await service.check_and_generate_vm_alerts()

    [alert] = await _all(factory, VMThresholdAlert)
    assert summary["resolved"] == 1
    assert (alert.status, alert.resolved_by) == ("resolved", "system")
    assert "below the 70% warning threshold" in alert.resolution_notes
    assert _kinds() == ["status"]


@pytest.mark.anyio
async def test_no_metric_data_leaves_alerts_alone(factory):
    await _add(factory, _vm_config())
    async with factory() as db:
        service = InfraAlertService(db)
        _readings(service, {"cpu": 91.0, "memory": None, "disk": None})
        await service.check_and_generate_vm_alerts()
        # A deallocated VM reports nothing: that is not a recovery.
        _readings(service, {"cpu": None, "memory": None, "disk": None})
        await service.check_and_generate_vm_alerts()

    [alert] = await _all(factory, VMThresholdAlert)
    assert alert.status == "active"


@pytest.mark.anyio
async def test_existing_duplicate_open_alerts_are_merged(factory):
    config_id = await _add(factory, _vm_config())
    old = datetime.utcnow() - timedelta(hours=2)
    for status, created in (("acknowledged", old), ("active", old + timedelta(minutes=15))):
        await _add(
            factory,
            VMThresholdAlert(
                config_id=config_id,
                vm_id="x",
                vm_name="vm-1",
                metric_type="cpu",
                current_value=80.0,
                threshold_value=70.0,
                severity="warning",
                status=status,
                created_at=created,
            ),
        )
    async with factory() as db:
        service = InfraAlertService(db)
        _readings(service, {"cpu": 82.0, "memory": None, "disk": None})
        await service.check_and_generate_vm_alerts()

    older, newer = await _all(factory, VMThresholdAlert)
    assert newer.status == "active"
    assert older.status == "resolved"
    assert f"duplicate of alert #{newer.id}" in older.resolution_notes


@pytest.mark.anyio
async def test_vm_metrics_are_percentages(monkeypatch):
    service = InfraAlertService(None)
    calls = []

    def _read(_sub, _rid, names, _window):
        calls.append(list(names))
        if "Available Memory Percentage" in names:
            raise RuntimeError("Failed to find metric configuration ... metric: Available Memory Percentage")
        return {
            "Percentage CPU": (41.237, datetime(2026, 10, 11, 1, 0)),
            "OS Disk IOPS Consumed Percentage": (12.0, datetime(2026, 10, 11, 1, 1)),
            "Data Disk Bandwidth Consumed Percentage": (64.5, datetime(2026, 10, 11, 1, 1)),
            "Data Disk IOPS Consumed Percentage": (None, None),
        }

    monkeypatch.setattr(service, "_read_metrics", _read)
    metrics = await service.get_vm_metrics("sub-1", "rg", "vm")

    # A VM without the memory metric is retried without it instead of failing.
    assert len(calls) == 2
    assert metrics["cpu"] == 41.24
    assert metrics["memory"] is None
    assert metrics["disk"] == 64.5

    monkeypatch.setattr(
        service,
        "_read_metrics",
        lambda *_a: {"Percentage CPU": (5.0, None), "Available Memory Percentage": (65.0, None)},
    )
    # "Available Memory Bytes" / 1e9 (GB free) used to be compared with a % threshold.
    assert (await service.get_vm_metrics("sub-1", "rg", "vm"))["memory"] == 35.0


# ── Expiry alerts ──────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_expiry_alert_created_once_and_not_after_acknowledge(factory):
    config_id = await _add(factory, _expiry_config(20))
    async with factory() as db:
        service = InfraAlertService(db)
        assert (await service.reconcile_expiry_alerts())["created"] == 1
        [alert] = await _all(factory, CustomExpiryAlert)
        await service.acknowledge_expiry_alert(alert.id, "lead@att.com")
        _Mail.sent = []
        # Each 15-minute run used to raise (and email) a fresh "active" copy.
        for _ in range(3):
            await service.reconcile_expiry_alerts()

    alerts = await _all(factory, CustomExpiryAlert, config_id=config_id)
    assert [(a.status, a.severity, a.days_until_expiry) for a in alerts] == [("acknowledged", "warning", 20)]
    assert _Mail.sent == []


@pytest.mark.anyio
async def test_renewed_expiry_date_resolves_the_alert(factory):
    config_id = await _add(factory, _expiry_config(-105))
    async with factory() as db:
        service = InfraAlertService(db)
        await service.reconcile_expiry_alerts()
        config = (await db.execute(select(CustomExpiryAlertConfig))).scalar_one()
        _Mail.sent = []
        await service.update_expiry_config(config_id, expiry_date=datetime.utcnow() + timedelta(days=365))

    [alert] = await _all(factory, CustomExpiryAlert)
    assert config.id == config_id
    assert (alert.status, alert.resolved_by) == ("resolved", "system")
    assert "outside the 30-day warning window" in alert.resolution_notes
    assert _kinds() == ["status"]


@pytest.mark.anyio
async def test_manual_resolve_sticks_until_it_gets_worse(factory):
    await _add(factory, _expiry_config(20))
    async with factory() as db:
        service = InfraAlertService(db)
        await service.reconcile_expiry_alerts()
        [alert] = await _all(factory, CustomExpiryAlert)
        await service.resolve_expiry_alert(alert.id, "Renewal ticket CHG123 raised", "lead@att.com")

        summary = await service.reconcile_expiry_alerts()
        assert (summary["created"], summary["suppressed"]) == (0, 1)

        # Now inside the 7-day critical window: worse than what was resolved.
        config = (await db.execute(select(CustomExpiryAlertConfig))).scalar_one()
        config.expiry_date = config.expiry_date - timedelta(days=15)
        await db.commit()
        assert (await service.reconcile_expiry_alerts())["created"] == 1

    first, second = await _all(factory, CustomExpiryAlert)
    assert (first.status, first.resolved_by, first.resolution_notes) == (
        "resolved",
        "lead@att.com",
        "Renewal ticket CHG123 raised",
    )
    assert (second.status, second.severity) == ("active", "critical")


@pytest.mark.anyio
async def test_passing_the_expiry_date_reopens_and_notifies(factory):
    config_id = await _add(factory, _expiry_config(2))
    async with factory() as db:
        service = InfraAlertService(db)
        await service.reconcile_expiry_alerts()
        [alert] = await _all(factory, CustomExpiryAlert)
        await service.acknowledge_expiry_alert(alert.id, "lead@att.com")
        _Mail.sent = []
        # Two days later.
        config = await db.get(CustomExpiryAlertConfig, config_id)
        config.expiry_date = config.expiry_date - timedelta(days=3)
        await db.commit()
        open_alert = (await db.execute(select(CustomExpiryAlert))).scalar_one()
        open_alert.expiry_date = config.expiry_date  # same cycle, a day after it lapsed
        await db.commit()
        summary = await service.reconcile_expiry_alerts()

    [alert] = await _all(factory, CustomExpiryAlert)
    assert summary["escalated"] == 1
    assert (alert.status, alert.days_until_expiry) == ("active", -1)
    assert _kinds() == ["expiry"]


@pytest.mark.anyio
async def test_disabling_an_expiry_config_closes_its_alert(factory):
    config_id = await _add(factory, _expiry_config(3))
    async with factory() as db:
        service = InfraAlertService(db)
        await service.reconcile_expiry_alerts()
        await service.update_expiry_config(config_id, is_enabled=False)

    [alert] = await _all(factory, CustomExpiryAlert)
    assert alert.status == "resolved"
    assert "disabled" in alert.resolution_notes


@pytest.mark.anyio
async def test_create_raises_the_alert_immediately_and_rejects_duplicates(factory):
    async with factory() as db:
        service = InfraAlertService(db)
        result = await service.create_expiry_config(
            alert_type="mech_id",
            resource_name="m12345",
            resource_identifier="m12345",
            expiry_date=datetime.utcnow() + timedelta(days=5),
            created_by="t",
            notification_emails=["ops@att.com"],
        )
        assert result["alert"] is True

        # Used to swallow the unique-key error and answer {"id": None, "status": "created"}.
        with pytest.raises(HTTPException) as exc:
            await service.create_expiry_config(
                alert_type="mech_id",
                resource_name="m12345 again",
                resource_identifier="m12345",
                expiry_date=datetime.utcnow() + timedelta(days=50),
                created_by="t",
            )
    assert exc.value.status_code == 409
    [alert] = await _all(factory, CustomExpiryAlert)
    assert alert.severity == "critical"


@pytest.mark.anyio
async def test_unknown_ids_are_404_not_a_200_error_body(factory):
    async with factory() as db:
        service = InfraAlertService(db)
        for call in (
            service.update_expiry_config(999, resource_name="x"),
            service.acknowledge_expiry_alert(999, "x"),
            service.resolve_vm_alert(999),
            service.delete_pg_flex_config(999),
        ):
            with pytest.raises(HTTPException) as exc:
                await call
            assert exc.value.status_code == 404


@pytest.mark.anyio
async def test_deleting_a_config_removes_its_alert_history(factory):
    # The alert rows reference the config (NOT NULL foreign key), so the delete
    # used to fail on PostgreSQL for any config that had ever alerted.
    config_id = await _add(factory, _expiry_config(3))
    async with factory() as db:
        service = InfraAlertService(db)
        await service.reconcile_expiry_alerts()
        result = await service.delete_expiry_config(config_id)

    assert result["alerts_removed"] == 1
    assert await _all(factory, CustomExpiryAlert) == []
    assert await _all(factory, CustomExpiryAlertConfig) == []


@pytest.mark.anyio
async def test_list_shows_live_days_left_even_when_the_stored_value_is_old(factory):
    config_id = await _add(factory, _expiry_config(10))
    await _add(
        factory,
        CustomExpiryAlert(
            config_id=config_id,
            alert_type="itservices_domain",
            resource_name="m52142",
            expiry_date=datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=10),
            days_until_expiry=45,  # written weeks ago
            severity="warning",
            status="acknowledged",
        ),
    )
    async with factory() as db:
        [row] = await InfraAlertService(db).list_expiry_alerts()
    assert row["days_until_expiry"] == 10


# ── Schedules and the digest ───────────────────────────────────────────


@pytest.mark.anyio
async def test_invalid_cron_and_duplicate_names_are_rejected(factory):
    async with factory() as db:
        service = InfraAlertService(db)
        with pytest.raises(HTTPException) as exc:
            await service.create_alert_schedule_config(
                name="Broken", created_by="t", schedule_type="cron", cron_expression="every morning"
            )
        assert exc.value.status_code == 422

        await service.create_alert_schedule_config(name="Checks", created_by="t")
        with pytest.raises(HTTPException) as exc:
            await service.create_alert_schedule_config(name="Checks", created_by="t")
        assert exc.value.status_code == 409


@pytest.mark.anyio
async def test_interval_schedule_digest_goes_out_once_a_day_after_its_time(factory):
    schedule_id = await _add(
        factory,
        AlertScheduleConfig(
            created_by="t",
            name="Checks + digest",
            schedule_type="interval",
            interval_minutes=15,
            send_daily_digest=True,
            digest_time_utc="08:00",
            digest_recipients=["ops@att.com"],
        ),
    )
    async with factory() as db:
        schedule = await db.get(AlertScheduleConfig, schedule_id)
        before = datetime(2026, 10, 11, 7, 45)
        assert await scheduler_service._claim_daily_digest(db, schedule, before) is False
        firings = [datetime(2026, 10, 11, 8, 0) + timedelta(minutes=15 * i) for i in range(8)]
        sent = [await scheduler_service._claim_daily_digest(db, schedule, at) for at in firings]
        assert sent == [True] + [False] * 7
        assert await scheduler_service._claim_daily_digest(db, schedule, datetime(2026, 10, 12, 8, 0)) is True


@pytest.mark.anyio
async def test_cron_schedule_digest_follows_the_cron(factory):
    schedule_id = await _add(
        factory,
        AlertScheduleConfig(
            created_by="t",
            name="Digest",
            schedule_type="cron",
            cron_expression="0 6 * * *",
            send_daily_digest=True,
            digest_time_utc="08:00",
        ),
    )
    async with factory() as db:
        schedule = await db.get(AlertScheduleConfig, schedule_id)
        # 06:00 is before the digest time, but a cron schedule's own time wins.
        assert await scheduler_service._claim_daily_digest(db, schedule, datetime(2026, 10, 11, 6, 0)) is True


# ── VM / PG power actions ──────────────────────────────────────────────


def _inventory(name: str, subscription_id: str) -> AzureResourceInventory:
    return AzureResourceInventory(
        resource_id=f"/subscriptions/{subscription_id}/resourceGroups/RG/providers/x/{name}",
        name=name,
        resource_type="virtual_machine",
        resource_group="RG",
        subscription_id=subscription_id,
        resource_details={"name": name, "power_state": "running"},
    )


@pytest.mark.anyio
async def test_power_action_targets_the_vms_own_subscription_and_is_audited(factory, monkeypatch):
    await _add(factory, _inventory("prd-vm", "sub-2"))
    calls = []

    async def _scope():
        return ["sub-1", "sub-2"]

    async def _stop(self, resource_group, vm_name, *, subscription_id):
        calls.append(subscription_id)
        return {"status": "success", "action": "deallocate", "vm_name": vm_name, "resource_group": resource_group}

    async def _refresh(self, resource_type, subscription_id, resource_group, name):
        return "deallocated"

    monkeypatch.setattr("app.services.azure_resource_service.get_scoped_subscription_ids", _scope)
    monkeypatch.setattr(AzureResourceService, "stop_vm", _stop)
    monkeypatch.setattr(AzureResourceService, "refresh_inventory_power_state", _refresh)

    user = SimpleNamespace(user_id="u1", email="ops@att.com")
    request = SimpleNamespace(client=SimpleNamespace(host="10.0.0.1"))
    async with factory() as db:
        response = await infra_alerts._run_power_action(
            db=db,
            http_request=request,
            user=user,
            kind="vm",
            action="stop",
            resource_group="rg",
            name="PRD-VM",
            subscription_id=None,
        )

    # Previously always the first configured subscription (sub-1).
    assert calls == ["sub-2"]
    assert b'"power_state":"deallocated"' in response.body
    [audit] = await _all(factory, AuditLog)
    assert (audit.action, audit.status) == ("virtual_machine_stop", "success")
    assert audit.details["subscription_id"] == "sub-2"


@pytest.mark.anyio
async def test_power_action_refuses_an_ambiguous_vm_name(factory, monkeypatch):
    await _add(factory, _inventory("dup-vm", "sub-1"))
    await _add(factory, _inventory("dup-vm", "sub-2"))

    async def _scope():
        return ["sub-1", "sub-2"]

    monkeypatch.setattr("app.services.azure_resource_service.get_scoped_subscription_ids", _scope)
    async with factory() as db:
        with pytest.raises(HTTPException) as exc:
            await infra_alerts._run_power_action(
                db=db,
                http_request=SimpleNamespace(client=None),
                user=SimpleNamespace(user_id="u1", email=None),
                kind="vm",
                action="start",
                resource_group="RG",
                name="dup-vm",
                subscription_id=None,
            )
    assert exc.value.status_code == 400
    assert "2 subscriptions" in exc.value.detail
