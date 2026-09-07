import datetime
from types import SimpleNamespace

import pytest

from app.api.v1.endpoints import infra_alerts
from app.core import database as database_core
from app.services import scheduler_service
from app.services.aks_operations_service import AKSOperationsService
from app.services.azure_resource_service import AzureResourceService
from app.services.email_notification_service import EmailNotificationService
from app.services.infra_alert_service import InfraAlertService


class _FakeScalarListResult:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return self

    def all(self):
        return self._rows


class _CapturingDbSession:
    def __init__(self, rows=None):
        self.rows = rows or []
        self.statement = None

    async def execute(self, statement):
        self.statement = statement
        return _FakeScalarListResult(self.rows)


class _FakeAllResult:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class _SequencedDbSession:
    def __init__(self, results):
        self.results = list(results)
        self.statements = []

    async def execute(self, statement):
        self.statements.append(statement)
        return self.results.pop(0)


class _FakeScalarValueResult:
    def __init__(self, value):
        self._value = value

    def scalar_one(self):
        return self._value


class _SeedableDbSession:
    def __init__(self, existing_count=0):
        self.existing_count = existing_count
        self.added = []
        self.commits = 0

    async def execute(self, statement):
        return _FakeScalarValueResult(self.existing_count)

    def add(self, record):
        self.added.append(record)

    async def commit(self):
        self.commits += 1


class _FakeSchedulerJob:
    def __init__(self, job_id, name, next_run_time):
        self.id = job_id
        self.name = name
        self.next_run_time = next_run_time
        self.trigger = "fake"


class _FakeScheduler:
    def __init__(self):
        self.running = True
        self.jobs = {
            "alert_schedule_config:99": _FakeSchedulerJob(
                "alert_schedule_config:99",
                "stale",
                datetime.datetime.now(datetime.UTC) + datetime.timedelta(minutes=5),
            )
        }

    def add_job(
        self,
        func,
        trigger,
        name=None,
        args=None,
        replace_existing=None,
        max_instances=None,
        coalesce=None,
        **kwargs,
    ):
        job_id = kwargs.get("id")
        job = _FakeSchedulerJob(
            job_id,
            name,
            datetime.datetime.now(datetime.UTC) + datetime.timedelta(minutes=15),
        )
        self.jobs[job_id] = job
        return job

    def get_job(self, job_id):
        return self.jobs.get(job_id)

    def get_jobs(self):
        return list(self.jobs.values())

    def remove_job(self, job_id):
        self.jobs.pop(job_id, None)


class _FakeBeginContext:
    def __init__(self, connection):
        self._connection = connection

    async def __aenter__(self):
        return self._connection

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _FakeConnection:
    def __init__(self):
        self.executed_sql = []
        self.ran_sync = False

    async def run_sync(self, fn):
        self.ran_sync = True

    async def execute(self, statement):
        self.executed_sql.append(str(statement))


class _FakeEngine:
    def __init__(self, connection):
        self._connection = connection

    def begin(self):
        return _FakeBeginContext(self._connection)


@pytest.mark.anyio
async def test_vm_threshold_configs_use_monitored_subscription_scope(monkeypatch):
    async def _mock_monitored_ids():
        return ["sub-1", "sub-2"]

    monkeypatch.setattr(
        "app.services.infra_alert_service.get_scoped_subscription_ids",
        _mock_monitored_ids,
    )

    fake_db = _CapturingDbSession()
    service = InfraAlertService(fake_db)

    await service.list_vm_threshold_configs()

    assert fake_db.statement is not None
    compiled = fake_db.statement.compile()
    compiled_sql = str(compiled)
    assert "vm_threshold_alert_configs.subscription_id" in compiled_sql
    assert "sub-1" in str(compiled.params)
    assert "sub-2" in str(compiled.params)


@pytest.mark.anyio
async def test_vm_threshold_alerts_join_config_scope(monkeypatch):
    async def _mock_monitored_ids():
        return ["sub-1"]

    monkeypatch.setattr(
        "app.services.infra_alert_service.get_scoped_subscription_ids",
        _mock_monitored_ids,
    )

    fake_db = _CapturingDbSession()
    service = InfraAlertService(fake_db)

    await service.list_vm_threshold_alerts(status="active")

    assert fake_db.statement is not None
    compiled_sql = str(fake_db.statement.compile())
    assert "JOIN vm_threshold_alert_configs" in compiled_sql
    assert "vm_threshold_alert_configs.subscription_id" in compiled_sql


@pytest.mark.anyio
async def test_inventory_reads_use_monitored_subscription_scope(monkeypatch):
    async def _mock_monitored_ids():
        return ["sub-1"]

    monkeypatch.setattr(
        "app.services.azure_resource_service.get_scoped_subscription_ids",
        _mock_monitored_ids,
    )

    row = SimpleNamespace(
        id=1,
        resource_id="/subscriptions/sub-1/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm-1",
        name="vm-1",
        resource_type="virtual_machine",
        resource_group="rg",
        location="eastus",
        subscription_id="sub-1",
        provisioning_state="Succeeded",
        tags={},
        resource_details={},
        last_sync=None,
    )
    fake_db = _CapturingDbSession(rows=[row])
    service = AzureResourceService(fake_db)

    await service.get_inventory_from_db(resource_type="virtual_machine")

    assert fake_db.statement is not None
    compiled_sql = str(fake_db.statement.compile())
    assert "azure_resource_inventory.subscription_id" in compiled_sql
    assert "azure_resource_inventory.resource_type" in compiled_sql


@pytest.mark.anyio
async def test_inventory_summary_matches_frontend_shape(monkeypatch):
    async def _mock_monitored_ids():
        return ["sub-1"]

    monkeypatch.setattr(
        "app.services.azure_resource_service.get_scoped_subscription_ids",
        _mock_monitored_ids,
    )

    rows = [
        SimpleNamespace(
            resource_type="virtual_machine",
            location="eastus",
            subscription_id="sub-1",
            last_sync=None,
        ),
        SimpleNamespace(
            resource_type="storage_account",
            location="eastus2",
            subscription_id="sub-1",
            last_sync=None,
        ),
    ]
    fake_db = _CapturingDbSession(rows=rows)
    service = AzureResourceService(fake_db)

    summary = await service.get_inventory_summary()

    assert summary["total_resources"] == 2
    assert summary["by_type"]["virtual_machine"] == 1
    assert summary["by_subscription"]["sub-1"] == 2


@pytest.mark.anyio
async def test_cached_aks_clusters_use_monitored_subscription_scope(monkeypatch):
    async def _mock_monitored_ids():
        return ["sub-1"]

    monkeypatch.setattr(
        "app.services.aks_operations_service.get_scoped_subscription_ids",
        _mock_monitored_ids,
    )

    row = SimpleNamespace(resource_details={"id": "cluster-1"}, last_sync=None)
    fake_db = _CapturingDbSession(rows=[row])
    service = AKSOperationsService(fake_db)

    await service.get_clusters_from_db()

    assert fake_db.statement is not None
    compiled_sql = str(fake_db.statement.compile())
    assert "azure_resource_inventory.subscription_id" in compiled_sql
    assert "azure_resource_inventory.resource_type" in compiled_sql


@pytest.mark.anyio
async def test_create_tables_backfills_alert_schedule_pg_threshold_column(monkeypatch):
    fake_connection = _FakeConnection()
    monkeypatch.setattr(database_core, "_engine", _FakeEngine(fake_connection))

    await database_core.create_tables()

    assert fake_connection.ran_sync is True
    assert any("ALTER TABLE IF EXISTS alert_schedule_configs" in sql for sql in fake_connection.executed_sql)
    assert any("ADD COLUMN IF NOT EXISTS check_pg_thresholds" in sql for sql in fake_connection.executed_sql)


@pytest.mark.anyio
async def test_create_tables_backfills_expiry_environment_column(monkeypatch):
    fake_connection = _FakeConnection()
    monkeypatch.setattr(database_core, "_engine", _FakeEngine(fake_connection))

    await database_core.create_tables()

    assert any("ALTER TABLE IF EXISTS custom_expiry_alert_configs" in sql for sql in fake_connection.executed_sql)
    assert any("ADD COLUMN IF NOT EXISTS environment" in sql for sql in fake_connection.executed_sql)


@pytest.mark.anyio
async def test_create_tables_backfills_certificate_private_key_column(monkeypatch):
    fake_connection = _FakeConnection()
    monkeypatch.setattr(database_core, "_engine", _FakeEngine(fake_connection))

    await database_core.create_tables()

    assert any("ALTER TABLE IF EXISTS cert_certificates" in sql for sql in fake_connection.executed_sql)
    assert any("ADD COLUMN IF NOT EXISTS has_private_key" in sql for sql in fake_connection.executed_sql)


@pytest.mark.anyio
async def test_create_expiry_config_persists_environment():
    fake_db = _SeedableDbSession()
    service = InfraAlertService(fake_db)

    result = await service.create_expiry_config(
        alert_type="database_account",
        resource_name="attcc-db-account",
        resource_identifier="db-acct-001",
        expiry_date=datetime.datetime(2027, 1, 1),
        created_by="tester@example.com",
        environment="prod",
    )

    assert result["status"] == "created"
    assert len(fake_db.added) == 1
    assert fake_db.added[0].environment == "prod"


@pytest.mark.anyio
async def test_list_expiry_configs_returns_environment():
    row = SimpleNamespace(
        id=1,
        alert_type="database_account",
        resource_name="attcc-db-account",
        resource_identifier="db-acct-001",
        description=None,
        environment="prod",
        expiry_date=datetime.datetime(2027, 1, 1),
        warning_days_before=30,
        critical_days_before=7,
        is_enabled=True,
        notification_emails=[],
        extra_data={},
        created_at=datetime.datetime(2026, 1, 1),
        created_by="tester@example.com",
    )
    fake_db = _CapturingDbSession(rows=[row])
    service = InfraAlertService(fake_db)

    configs = await service.list_expiry_configs()

    assert len(configs) == 1
    assert configs[0]["environment"] == "prod"


@pytest.mark.anyio
async def test_notification_history_excludes_checksum_entries_by_default():
    fake_db = _CapturingDbSession()
    service = EmailNotificationService(fake_db)

    await service.get_notification_history()

    assert fake_db.statement is not None
    compiled_sql = str(fake_db.statement.compile())
    assert "alert_notification_history.alert_type NOT IN" in compiled_sql


@pytest.mark.anyio
async def test_infra_alert_history_maps_notification_type_to_backend_filter(
    monkeypatch,
):
    captured = {}

    async def _fake_history(self, **kwargs):
        captured.update(kwargs)
        return []

    monkeypatch.setattr(
        "app.services.email_notification_service.EmailNotificationService.get_notification_history",
        _fake_history,
    )

    result = await infra_alerts.get_notification_history(
        notification_type="expiry",
        alert_type=None,
        alert_id=None,
        status="sent",
        limit=25,
        user=None,
        db=_CapturingDbSession(),
    )

    assert result == []
    assert captured["alert_type"] == "custom_expiry"
    assert captured["status"] == "sent"
    assert captured["exclude_alert_types"] is None


@pytest.mark.anyio
async def test_alert_summary_aggregates_all_statuses_and_types(monkeypatch):
    async def _mock_monitored_ids():
        return ["sub-1"]

    monkeypatch.setattr(
        "app.services.infra_alert_service.get_scoped_subscription_ids",
        _mock_monitored_ids,
    )

    fake_db = _SequencedDbSession(
        [
            _FakeAllResult(
                [
                    SimpleNamespace(status="active", severity="critical", count=2),
                    SimpleNamespace(status="acknowledged", severity="warning", count=1),
                ]
            ),
            _FakeAllResult(
                [
                    SimpleNamespace(alert_type="certificate", status="active", count=3),
                    SimpleNamespace(alert_type="certificate", status="resolved", count=1),
                    SimpleNamespace(alert_type="mech_id", status="active", count=2),
                ]
            ),
            _FakeAllResult(
                [
                    SimpleNamespace(status="active", severity="warning", count=4),
                    SimpleNamespace(status="resolved", severity="critical", count=1),
                ]
            ),
        ]
    )

    service = InfraAlertService(fake_db)
    summary = await service.get_alert_summary()

    assert summary["vm_threshold_alerts"]["by_status"] == {"active": 2, "acknowledged": 1}
    assert summary["vm_threshold_alerts"]["by_severity"] == {"critical": 2, "warning": 1}
    assert summary["expiry_alerts"]["by_status"] == {"active": 5, "resolved": 1}
    assert summary["expiry_alerts"]["by_type"] == {"certificate": 4, "mech_id": 2}
    assert summary["pg_flex_alerts"]["by_status"] == {"active": 4, "resolved": 1}
    assert summary["pg_flex_alerts"]["by_severity"] == {"warning": 4, "critical": 1}
    assert summary["total_active_alerts"] == 11


@pytest.mark.anyio
async def test_alert_schedule_configs_list_returns_expected_shape():
    row = SimpleNamespace(
        id=7,
        name="Infra Alert Checks",
        description="Runs daily checks",
        schedule_type="interval",
        interval_minutes=30,
        cron_expression=None,
        check_vm_thresholds=True,
        check_storage_thresholds=False,
        check_disk_thresholds=True,
        check_expiry_alerts=True,
        check_pg_thresholds=True,
        send_daily_digest=True,
        digest_time_utc="08:00",
        digest_recipients=["ops@att.com"],
        is_enabled=True,
        last_run_at=None,
        next_run_at=None,
        created_at=datetime.datetime(2026, 3, 17, 8, 0, 0),
        updated_at=datetime.datetime(2026, 3, 17, 9, 0, 0),
        created_by="user@att.com",
    )
    fake_db = _CapturingDbSession(rows=[row])
    service = InfraAlertService(fake_db)

    configs = await service.list_alert_schedule_configs()

    assert configs == [
        {
            "id": 7,
            "name": "Infra Alert Checks",
            "description": "Runs daily checks",
            "schedule_type": "interval",
            "interval_minutes": 30,
            "cron_expression": None,
            "check_vm_thresholds": True,
            "check_storage_thresholds": False,
            "check_disk_thresholds": True,
            "check_expiry_alerts": True,
            "check_pg_thresholds": True,
            "send_daily_digest": True,
            "digest_time_utc": "08:00",
            "digest_recipients": ["ops@att.com"],
            "is_enabled": True,
            "last_run_at": None,
            "next_run_at": None,
            "created_at": "2026-03-17T08:00:00",
            "updated_at": "2026-03-17T09:00:00",
            "created_by": "user@att.com",
        }
    ]


@pytest.mark.anyio
async def test_seed_default_alert_schedules_creates_two_defaults_when_empty():
    fake_db = _SeedableDbSession(existing_count=0)
    service = InfraAlertService(fake_db)

    result = await service.seed_default_alert_schedules()

    assert result == {"created": 2, "skipped": 0}
    assert fake_db.commits == 1
    assert [row.name for row in fake_db.added] == ["Infra Alert Checks", "Daily Alert Digest"]


@pytest.mark.anyio
async def test_sync_alert_schedule_jobs_registers_enabled_configs(monkeypatch):
    scheduler = _FakeScheduler()
    enabled = SimpleNamespace(
        id=1,
        name="Infra Alert Checks",
        schedule_type="interval",
        interval_minutes=15,
        cron_expression=None,
        is_enabled=True,
        next_run_at=None,
    )
    disabled = SimpleNamespace(
        id=2,
        name="Disabled Digest",
        schedule_type="cron",
        interval_minutes=60,
        cron_expression="0 8 * * *",
        is_enabled=False,
        next_run_at=datetime.datetime(2026, 3, 17, 8, 0, 0),
    )

    class _ScheduleDbSession:
        def __init__(self):
            self.commits = 0

        async def execute(self, statement):
            return _FakeScalarListResult([enabled, disabled])

        async def commit(self):
            self.commits += 1

    db = _ScheduleDbSession()

    async def _fake_get_db_session():
        yield db

    monkeypatch.setattr(scheduler_service, "get_scheduler", lambda: scheduler)
    monkeypatch.setattr(scheduler_service, "get_db_session", _fake_get_db_session)

    result = await scheduler_service.sync_alert_schedule_jobs()

    assert result["synced"] == 1
    assert result["removed"] == 1
    assert "alert_schedule_config:1" in scheduler.jobs
    assert "alert_schedule_config:2" not in scheduler.jobs
    assert enabled.next_run_at is not None
    assert disabled.next_run_at is None
    assert db.commits == 1
