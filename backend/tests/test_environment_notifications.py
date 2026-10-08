"""Environment Scheduler: run-summary emails (who gets them, what they say) and
schedule timing (start time in the schedule's timezone, anchored repeats)."""

from datetime import datetime, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.ext.compiler import compiles

from app.models.database import AuditLog, EnvironmentExecutionHistory, EnvironmentSchedule, EnvironmentSequence
from app.services import environment_notifications as notifications
from app.services import environment_scaling_service as env_module
from app.services import scheduler_service
from app.services.environment_notifications import (
    RunReport,
    normalize_recipients,
    parse_recipients,
    render_email,
    should_notify,
)
from app.services.environment_scaling_service import (
    EnvironmentScalingService,
    ScheduleValidationError,
    describe_schedule,
    next_schedule_run,
    upcoming_schedule_runs,
)


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


class FakeAks:
    def __init__(self, replicas=None, fail=()):
        self.replicas = dict(replicas or {})
        self.fail = set(fail)

    async def list_deployments(self, cluster_id, namespace, bypass_cache=False):
        return [{"name": n, "replicas": r} for n, r in self.replicas.items()]

    async def scale_deployment(self, *, cluster_id, namespace, deployment_name, replicas, user_id, user_email):
        if deployment_name in self.fail:
            raise RuntimeError("deployment is locked")
        previous = self.replicas.get(deployment_name, 0)
        self.replicas[deployment_name] = replicas
        return {"previous_replicas": previous}

    async def _get_k8s_clients(self, cluster_id):
        def read_status(name, namespace):
            n = self.replicas.get(name, 0)
            return SimpleNamespace(
                spec=None, status=SimpleNamespace(ready_replicas=n, available_replicas=n, conditions=[])
            )

        return SimpleNamespace(read_namespaced_deployment_status=read_status), None, None


CLUSTER = "/subscriptions/s1/resourceGroups/rg/providers/Microsoft.ContainerService/managedClusters/attcc-prod-aks"


def _sequence(**overrides):
    values = {
        "name": "SCAL-Up-UI",
        "cluster_id": CLUSTER,
        "namespace": "com-att-attcc-prod",
        "sequence_type": "startup",
        "rollback_on_failure": False,
        "created_by": "u1",
        "steps": [
            {
                "order": 1,
                "deployment_name": "administration",
                "replicas": 2,
                "wait_condition": "pods_ready",
                "timeout_seconds": 0,
                "on_failure": "abort",
            }
        ],
        **overrides,
    }
    return EnvironmentSequence(**values)


# ── Email content ─────────────────────────────────────────────────────────


def _report(**overrides):
    values = {
        "status": "failed",
        "operation": "sequence_startup",
        "cluster_id": CLUSTER,
        "namespace": "com-att-attcc-prod",
        "trigger": 'Schedule "Weekday start" · cron 0 8 * * 1-5 (US/Central)',
        "name": "SCAL-Up-UI",
        "execution_id": 41,
        "started_at": datetime(2026, 10, 8, 13, 0),
        "finished_at": datetime(2026, 10, 8, 13, 12, 30),
        "duration_seconds": 750,
        "timezone": "US/Central",
        "error_message": "Aborted at step 2 (reportmanager): only 3/60 pods ready <script>",
        "steps": [
            {
                "step": 1,
                "deployment": "administration",
                "current_replicas": 0,
                "target_replicas": 60,
                "status": "completed",
                "duration_seconds": 64,
                "wait_condition": "pods_ready",
            },
            {
                "step": 2,
                "deployment": "reportmanager",
                "current_replicas": 0,
                "target_replicas": 60,
                "status": "failed",
                "duration_seconds": 600,
                "error": "only 3/60 pods ready",
                "wait_condition": "pods_ready",
            },
            {"step": 3, "deployment": "dataloader", "target_replicas": 1, "status": "not_run"},
        ],
    }
    values.update(overrides)
    return RunReport(**values)


def test_the_summary_says_what_ran_where_and_why_it_failed():
    subject, html = render_email(_report())

    assert subject == "[OpsPortal] FAILED: Startup sequence SCAL-Up-UI | com-att-attcc-prod (attcc-prod-aks)"
    for text in (
        "Startup sequence failed",
        "attcc-prod-aks",
        "Schedule &quot;Weekday start&quot;",
        "Oct 08, 2026 08:00 AM CDT",
        "12m 30s",
        "reportmanager",
        "only 3/60 pods ready",
        "Not run",
        "#41",
    ):
        assert text in html, text
    assert "<script>" not in html and "&lt;script&gt;" in html  # error text is escaped


def test_subjects_for_success_and_rollback():
    assert render_email(_report(status="completed", error_message=None))[0].startswith("[OpsPortal] Completed: ")
    assert render_email(_report(status="rolled_back"))[0].startswith("[OpsPortal] FAILED (rolled back): ")
    scale = _report(status="completed", operation="scale_down", name=None, error_message=None)
    assert render_email(scale)[0] == "[OpsPortal] Completed: Scale down | com-att-attcc-prod (attcc-prod-aks)"


def test_recipients_are_validated_and_deduplicated():
    assert parse_recipients("a@att.com; B@att.com", "b@att.com, junk", None, "c@att.com") == [
        "a@att.com",
        "B@att.com",
        "c@att.com",
    ]
    assert normalize_recipients(" ops@att.com ;dl@att.com ") == "ops@att.com, dl@att.com"
    assert normalize_recipients("") is None
    with pytest.raises(ValueError, match="not-an-address"):
        normalize_recipients("ops@att.com, not-an-address")


def test_send_when_setting():
    assert should_notify("always", "completed") and should_notify(None, "completed")
    assert not should_notify("failure", "completed") and should_notify("failure", "rolled_back")
    assert not should_notify("never", "failed")


# ── Who is emailed ────────────────────────────────────────────────────────


async def _run_sequence(factory, sequence, aks):
    async with factory() as db:
        db.add(sequence)
        await db.commit()
        service = EnvironmentScalingService(db)
        service._aks = aks
        result = await service.execute_sequence(
            sequence_id=sequence.id, replica_count=1, dry_run=False, user_id="u1", user_email="starter@att.com"
        )
    await notifications.wait_for_pending_emails()
    return result


@pytest.mark.anyio
async def test_a_manual_sequence_run_emails_the_starter_and_the_sequence_list(factory, sent_run_emails):
    await _run_sequence(factory, _sequence(notification_emails="ops-dl@att.com"), FakeAks({"administration": 0}))

    [(recipients, report)] = sent_run_emails
    assert recipients == ["starter@att.com", "ops-dl@att.com"]
    assert (report.status, report.name, report.trigger) == (
        "completed",
        "SCAL-Up-UI",
        "Started manually by starter@att.com",
    )
    assert report.steps[0]["target_replicas"] == 2


@pytest.mark.anyio
async def test_failure_only_skips_successful_runs(factory, sent_run_emails):
    await _run_sequence(factory, _sequence(notify_on="failure"), FakeAks({"administration": 0}))
    assert sent_run_emails == []

    await _run_sequence(
        factory, _sequence(name="other", notify_on="failure"), FakeAks({"administration": 0}, fail={"administration"})
    )
    assert [r.status for _, r in sent_run_emails] == ["failed"]


@pytest.mark.anyio
async def test_a_scheduled_run_emails_the_schedule_recipients_with_its_timing(factory, sent_run_emails):
    async with factory() as db:
        seq = _sequence(notification_emails="seq-dl@att.com")
        db.add(seq)
        await db.commit()
        schedule = EnvironmentSchedule(
            job_name="Weekday start",
            cluster_id=CLUSTER,
            namespace="com-att-attcc-prod",
            operation="scale_up",
            schedule_type="cron",
            cron_expression="0 8 * * 1-5",
            timezone="US/Central",
            sequence_id=seq.id,
            failure_notification="sched-dl@att.com",
            created_by="owner",
            created_by_email="owner@att.com",
        )
        db.add(schedule)
        await db.commit()
        service = EnvironmentScalingService(db)
        service._aks = FakeAks({"administration": 0})
        await service.execute_scheduled_job(schedule.id)
    await notifications.wait_for_pending_emails()

    [(recipients, report)] = sent_run_emails
    assert recipients == ["owner@att.com", "sched-dl@att.com", "seq-dl@att.com"]
    assert report.trigger == 'Schedule "Weekday start" · cron 0 8 * * 1-5 (US/Central)'
    assert report.timezone == "US/Central" and report.name == "SCAL-Up-UI"


@pytest.mark.anyio
async def test_manual_scale_endpoint_emails_the_person_scaling(admin_client, db_engine, monkeypatch, sent_run_emails):
    async with db_engine.begin() as conn:
        for model in ENV_TABLES:
            await conn.run_sync(lambda c, m=model: m.__table__.create(c, checkfirst=True))
    monkeypatch.setattr(env_module, "get_aks_operations_service", lambda db: FakeAks({"api": 1, "web": 1}))

    response = await admin_client.post(
        "/api/v1/environment/scale",
        json={
            "cluster_id": CLUSTER,
            "namespace": "apps",
            "operation": "scale_down",
            "scope": "namespace",
            "replica_count": 0,
            "notification_emails": "ops@att.com",
        },
    )
    assert response.status_code == 200, response.text
    await notifications.wait_for_pending_emails()

    [(recipients, report)] = sent_run_emails
    assert recipients == ["admin@example.com", "ops@att.com"]
    assert (report.operation, report.status, len(report.steps)) == ("scale_down", "completed", 2)


@pytest.mark.anyio
async def test_manual_scale_without_notify_sends_nothing(admin_client, db_engine, monkeypatch, sent_run_emails):
    async with db_engine.begin() as conn:
        for model in ENV_TABLES:
            await conn.run_sync(lambda c, m=model: m.__table__.create(c, checkfirst=True))
    monkeypatch.setattr(env_module, "get_aks_operations_service", lambda db: FakeAks({"api": 1}))

    response = await admin_client.post(
        "/api/v1/environment/scale",
        json={
            "cluster_id": CLUSTER,
            "namespace": "apps",
            "operation": "scale_down",
            "replica_count": 0,
            "notify": False,
        },
    )
    assert response.status_code == 200
    await notifications.wait_for_pending_emails()
    assert sent_run_emails == []


# ── Schedule timing ───────────────────────────────────────────────────────


def _timing(schedule_type, start=None, tz="US/Central", cron=None, end=None):
    return SimpleNamespace(
        schedule_type=schedule_type, cron_expression=cron, timezone=tz, start_date=start, end_date=end, created_at=None
    )


def test_a_daily_schedule_runs_at_its_start_time_in_its_timezone_from_the_first_day():
    daily = _timing("daily", start=datetime(2026, 10, 9, 8, 0))  # 08:00 Central
    # First run is the start itself (it used to be a day later), at 13:00 UTC (CDT).
    assert next_schedule_run(daily, datetime(2026, 10, 8, 20, 0)) == datetime(2026, 10, 9, 13, 0)
    # Later runs keep 08:00 Central across the DST change on Nov 1 (CST: 14:00 UTC).
    runs = upcoming_schedule_runs(daily, count=30, after=datetime(2026, 10, 25, 0, 0))
    assert datetime(2026, 10, 31, 13, 0) in runs and datetime(2026, 11, 2, 14, 0) in runs


def test_weekly_and_monthly_keep_their_weekday_and_day():
    weekly = _timing("weekly", start=datetime(2026, 10, 7, 20, 0), tz="UTC")  # a Wednesday
    assert [r.weekday() for r in upcoming_schedule_runs(weekly, count=3, after=datetime(2026, 10, 8))] == [2, 2, 2]
    monthly = _timing("monthly", start=datetime(2026, 10, 31, 6, 0), tz="UTC")
    # The 31st doesn't exist in November: the month's last day instead (not "+30 days").
    assert upcoming_schedule_runs(monthly, count=2, after=datetime(2026, 10, 30)) == [
        datetime(2026, 10, 31, 6, 0),
        datetime(2026, 11, 30, 6, 0),
    ]


def test_a_one_time_schedule_runs_at_its_local_time_and_upcoming_stops_at_the_end_date():
    once = _timing("one_time", start=datetime(2026, 10, 9, 8, 0), tz="Asia/Kolkata")
    assert next_schedule_run(once, datetime(2026, 10, 1)) == datetime(2026, 10, 9, 2, 30)
    daily = _timing("daily", start=datetime(2026, 10, 9, 8, 0), tz="UTC", end=datetime(2026, 10, 11, 9, 0))
    assert len(upcoming_schedule_runs(daily, count=5, after=datetime(2026, 10, 1))) == 3
    assert describe_schedule(daily) == "Daily at 08:00 (UTC)"


@pytest.mark.anyio
async def test_invalid_schedules_are_rejected(factory):
    future = datetime.utcnow() + timedelta(days=1)
    async with factory() as db:
        service = EnvironmentScalingService(db)
        base = {"job_name": "x", "cluster_id": "c1", "namespace": "apps", "operation": "scale_up", "timezone": "UTC"}
        for data, message in (
            ({**base, "schedule_type": "cron", "cron_expression": "every morning"}, "Invalid cron"),
            ({**base, "schedule_type": "one_time", "start_date": "2020-01-01T08:00"}, "in the past"),
            (
                {**base, "schedule_type": "daily", "start_date": future.isoformat(), "end_date": "2026-01-01T00:00"},
                "end date",
            ),
            ({**base, "schedule_type": "daily", "timezone": "Mars/Base"}, "Unknown timezone"),
        ):
            with pytest.raises(ScheduleValidationError, match=message):
                await service.create_schedule(data, "u1", "u1@att.com")


@pytest.mark.anyio
async def test_editing_the_time_or_re_enabling_recomputes_the_next_run(factory):
    async with factory() as db:
        service = EnvironmentScalingService(db)
        created = await service.create_schedule(
            {
                "job_name": "nightly",
                "cluster_id": "c1",
                "namespace": "apps",
                "operation": "scale_down",
                "schedule_type": "cron",
                "cron_expression": "0 20 * * *",
                "timezone": "UTC",
                "end_date": (datetime.utcnow() + timedelta(days=30)).isoformat(timespec="minutes"),
            },
            "u1",
            "u1@att.com",
        )
        assert created["next_run_at"].endswith("20:00:00")

        edited = await service.update_schedule(created["id"], {"cron_expression": "0 21 * * *"})
        assert edited["next_run_at"].endswith("21:00:00")  # used to keep 20:00

        await service.update_schedule(created["id"], {"is_enabled": False})
        row = await db.get(EnvironmentSchedule, created["id"])
        row.next_run_at = datetime.utcnow() - timedelta(days=3)  # paused over several runs
        await db.commit()
        resumed = await service.update_schedule(created["id"], {"is_enabled": True})
        assert datetime.fromisoformat(resumed["next_run_at"]) > datetime.utcnow()  # no catch-up run on enable

        cleared = await service.update_schedule(created["id"], {"end_date": None, "failure_notification": None})
        assert cleared["end_date"] is None and cleared["failure_notification"] is None


@pytest.mark.anyio
async def test_preview_endpoint_lists_the_next_runs(admin_client):
    response = await admin_client.get(
        "/api/v1/environment/schedule/preview",
        params={
            "schedule_type": "cron",
            "cron_expression": "0 8 * * 1-5",
            "timezone": "US/Central",
        },
    )
    assert response.status_code == 200, response.text
    runs = response.json()["runs"]
    assert len(runs) == 5
    assert all(r["local"].split()[0] in ("Mon", "Tue", "Wed", "Thu", "Fri") and "08:00 AM" in r["local"] for r in runs)

    bad = await admin_client.get(
        "/api/v1/environment/schedule/preview", params={"schedule_type": "cron", "cron_expression": "nope"}
    )
    assert bad.status_code == 400 and "Invalid cron" in bad.json()["detail"]


@pytest.mark.anyio
async def test_the_runner_reads_the_end_date_in_the_schedules_timezone(factory, monkeypatch):
    async def _sessions():
        async with factory() as db:
            yield db

    monkeypatch.setattr(scheduler_service, "get_db_session", _sessions)
    launched = []
    monkeypatch.setattr(scheduler_service, "_launch_env_schedule_run", lambda *a: launched.append(a))
    kolkata = ZoneInfo("Asia/Kolkata")
    # Ended an hour ago in real time; as a naive UTC value it would still look 4.5h away.
    end_local = (datetime.now(kolkata) - timedelta(hours=1)).replace(tzinfo=None)
    async with factory() as db:
        db.add(
            EnvironmentSchedule(
                job_name="ended",
                cluster_id="c1",
                namespace="apps",
                operation="scale_up",
                schedule_type="daily",
                timezone="Asia/Kolkata",
                end_date=end_local,
                created_by="u1",
                is_enabled=True,
                next_run_at=datetime.utcnow() - timedelta(minutes=1),
            )
        )
        await db.commit()

    await scheduler_service.run_environment_schedules_job()

    async with factory() as db:
        row = (await db.execute(select(EnvironmentSchedule))).scalar_one()
    assert launched == [] and row.is_enabled is False
