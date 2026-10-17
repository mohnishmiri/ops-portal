"""MongoDB Atlas module: client, normalisation, schedules, operations, routes.

Atlas is simulated with an ``httpx.MockTransport`` (``FakeAtlas``) so the real
client runs — versioned Accept headers, paging, error mapping — and the
scheduler's compare-and-swap claims run against the SQLite test database.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from urllib.parse import unquote

import httpx
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.auth import get_current_user
from app.core.authz import SUBSCRIPTION_FREE_MODULES, _module_for_path
from app.core.config import settings
from app.core.database import get_db
from app.models.database import AtlasOperation, AtlasSchedule
from app.schemas.auth import UserContext, UserRole
from app.services import mongodb_atlas_notifications as notifications
from app.services import mongodb_atlas_scheduler as scheduler
from app.services.mongodb_atlas_service import (
    AtlasClient,
    AtlasError,
    AtlasService,
    classify_environment,
    match_cluster_processes,
    normalize_cluster,
    pause_rules,
    set_atlas_service,
)

PID = "5f1a2b3c4d5e6f7a8b9c0d1e"
PID_OTHER = "6a1a2b3c4d5e6f7a8b9c0d1f"


def _raw_cluster(name: str, *, tier: str = "M30", paused: bool = False, state: str = "IDLE", tags=None) -> dict:
    host = name.lower()
    return {
        "id": f"id-{name}",
        "name": name,
        "groupId": PID,
        "stateName": state,
        "paused": paused,
        "clusterType": "REPLICASET",
        "mongoDBVersion": "7.0.14",
        "backupEnabled": True,
        "tags": tags or [],
        "connectionStrings": {
            "standard": f"mongodb://{host}-shard-00-00.ab1cd.mongodb.net:27017,{host}-shard-00-01.ab1cd.mongodb.net:27017,"
            f"{host}-shard-00-02.ab1cd.mongodb.net:27017/?ssl=true&replicaSet=atlas-x-shard-0",
            "standardSrv": f"mongodb+srv://{host}.ab1cd.mongodb.net",
        },
        "replicationSpecs": [
            {
                "id": "spec-1",
                "zoneId": "zone-1",
                "zoneName": "Zone 1",
                "regionConfigs": [
                    {
                        "providerName": "AZURE",
                        "regionName": "US_EAST_2",
                        "priority": 7,
                        "electableSpecs": {"instanceSize": tier, "nodeCount": 3, "diskSizeGB": 40},
                        "readOnlySpecs": {"instanceSize": tier, "nodeCount": 0},
                        "effectiveElectableSpecs": {"instanceSize": tier, "nodeCount": 3},
                        "autoScaling": {"compute": {"enabled": False}, "diskGB": {"enabled": True}},
                    }
                ],
            }
        ],
    }


class FakeAtlas:
    """Just enough of the Atlas Admin API v2 for the module."""

    def __init__(self) -> None:
        self.projects = [
            {"id": PID, "name": "commissions-nonprod", "orgId": "org1", "clusterCount": 2},
            {"id": PID_OTHER, "name": "commissions-prod", "orgId": "org1", "clusterCount": 1},
        ]
        self.clusters = {
            PID: {
                "dev-cluster": _raw_cluster("dev-cluster"),
                "tiny": _raw_cluster("tiny", tier="M0"),
            },
            PID_OTHER: {"prod-main": {**_raw_cluster("prod-main"), "groupId": PID_OTHER}},
        }
        self.requests: list[httpx.Request] = []
        self.access_list: list[dict] = [{"cidrBlock": "10.0.0.0/24", "comment": "vnet"}]
        self.fail_next: tuple[int, dict] | None = None
        self.transport_error: Exception | None = None

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.fail_next:
            status, body = self.fail_next
            self.fail_next = None
            return httpx.Response(status, json=body)
        if self.transport_error is not None:
            raise self.transport_error
        if "authorization" not in request.headers:
            # Atlas answers every unauthenticated call with a Digest challenge.
            return httpx.Response(
                401,
                headers={
                    "WWW-Authenticate": 'Digest realm="MMS Public API", domain="", nonce="n0nce", algorithm=MD5, qop="auth", stale=false'
                },
                json={"error": 401, "errorCode": "UNAUTHORIZED", "detail": "Current user is not authorized"},
            )
        raw_path = request.url.raw_path.decode().split("?", 1)[0]
        path = raw_path.removeprefix("/api/atlas/v2")
        parts = [unquote(p) for p in path.strip("/").split("/")] if path.strip("/") else []
        method = request.method

        if not parts:
            return httpx.Response(
                200,
                json={
                    "apiKey": {"publicKey": "abcd", "roles": [{"orgId": "org1", "roleName": "ORG_READ_ONLY"}]},
                    "ipAddress": "203.0.113.9",
                },
            )
        if parts == ["groups"]:
            return httpx.Response(200, json={"results": self.projects, "totalCount": len(self.projects)})
        if parts[0] == "groups" and len(parts) >= 3 and parts[2] == "clusters":
            gid = parts[1]
            clusters = self.clusters.get(gid, {})
            if len(parts) == 3:
                return httpx.Response(200, json={"results": list(clusters.values()), "totalCount": len(clusters)})
            name = parts[3]
            if name not in clusters:
                return httpx.Response(404, json={"error": 404, "errorCode": "CLUSTER_NOT_FOUND", "detail": "nope"})
            cluster = clusters[name]
            if len(parts) == 4 and method == "GET":
                return httpx.Response(200, json=cluster)
            if len(parts) == 4 and method == "PATCH":
                body = json.loads(request.content)
                if "paused" in body:
                    cluster["paused"] = body["paused"]
                    cluster["stateName"] = "UPDATING"
                if "replicationSpecs" in body:
                    cluster["replicationSpecs"] = body["replicationSpecs"]
                    cluster["stateName"] = "UPDATING"
                return httpx.Response(200, json=cluster)
            if parts[4:] == ["restartPrimaries"]:
                return httpx.Response(200, json={})
        if parts[0] == "groups" and parts[2:] == ["accessList"]:
            if method == "GET":
                return httpx.Response(200, json={"results": self.access_list, "totalCount": len(self.access_list)})
            self.access_list.extend(json.loads(request.content))
            return httpx.Response(201, json={"results": self.access_list})
        if parts[0] == "groups" and parts[2] == "accessList" and method == "DELETE":
            self.access_list = [e for e in self.access_list if (e.get("cidrBlock") or e.get("ipAddress")) != parts[3]]
            return httpx.Response(204)
        if parts[0] == "groups" and parts[2:] == ["processes"]:
            host = "dev-cluster-shard-00-0{}.ab1cd.mongodb.net"
            procs = [
                {
                    "id": f"{host.format(i)}:27017",
                    "hostname": host.format(i),
                    "userAlias": host.format(i),
                    "typeName": t,
                }
                for i, t in enumerate(["REPLICA_SECONDARY", "REPLICA_PRIMARY", "REPLICA_SECONDARY"])
            ]
            procs.append(
                {"id": "other:27017", "hostname": "other-shard-00-00.zz.mongodb.net", "typeName": "REPLICA_PRIMARY"}
            )
            return httpx.Response(200, json={"results": procs, "totalCount": len(procs)})
        if parts[0] == "groups" and parts[2] == "processes" and parts[-1] == "measurements" and "disks" not in parts:
            t1, t2 = "2026-10-17T10:00:00Z", "2026-10-17T10:05:00Z"
            return httpx.Response(
                200,
                json={
                    "measurements": [
                        {
                            "name": "SYSTEM_NORMALIZED_CPU_USER",
                            "units": "PERCENT",
                            "dataPoints": [{"timestamp": t1, "value": 10}, {"timestamp": t2, "value": 30}],
                        },
                        {
                            "name": "SYSTEM_NORMALIZED_CPU_KERNEL",
                            "units": "PERCENT",
                            "dataPoints": [{"timestamp": t1, "value": 2}, {"timestamp": t2, "value": 5}],
                        },
                        {
                            "name": "SYSTEM_MEMORY_USED",
                            "units": "BYTES",
                            "dataPoints": [{"timestamp": t1, "value": 6}, {"timestamp": t2, "value": 3}],
                        },
                        {
                            "name": "SYSTEM_MEMORY_AVAILABLE",
                            "units": "BYTES",
                            "dataPoints": [{"timestamp": t1, "value": 2}, {"timestamp": t2, "value": 1}],
                        },
                        {
                            "name": "CONNECTIONS",
                            "units": "SCALAR",
                            "dataPoints": [{"timestamp": t1, "value": 40}, {"timestamp": t2, "value": None}],
                        },
                    ]
                },
            )
        if parts[0] == "groups" and parts[2] == "processes" and parts[-1] == "disks":
            return httpx.Response(200, json={"results": [{"partitionName": "data"}], "totalCount": 1})
        if parts[0] == "groups" and "disks" in parts and parts[-1] == "measurements":
            return httpx.Response(
                200,
                json={
                    "measurements": [
                        {
                            "name": "DISK_PARTITION_SPACE_PERCENT_USED",
                            "dataPoints": [{"timestamp": "2026-10-17T10:05:00Z", "value": 41.26}],
                        }
                    ]
                },
            )
        return httpx.Response(
            404, json={"error": 404, "errorCode": "NOT_FOUND", "detail": f"unhandled {method} {path}"}
        )


@pytest.fixture
def fake_atlas(monkeypatch):
    monkeypatch.setattr(settings, "MONGODB_ATLAS_PUBLIC_KEY", "abcd")
    monkeypatch.setattr(settings, "MONGODB_ATLAS_PRIVATE_KEY", "secret-key")
    monkeypatch.setattr(settings, "MONGODB_ATLAS_ORG_ID", "")
    monkeypatch.setattr(settings, "MONGODB_ATLAS_PROJECT_IDS", "")
    fake = FakeAtlas()
    client = AtlasClient(
        base_url="https://cloud.mongodb.com",
        public_key="abcd",
        private_key="secret-key",
        transport=httpx.MockTransport(fake.handler),
    )
    set_atlas_service(AtlasService(client))
    yield fake
    set_atlas_service(None)


@pytest.fixture(autouse=True)
def sent_atlas_emails(monkeypatch):
    sent: list[tuple[list[str], str, str]] = []

    async def _record(recipients, subject, html):
        sent.append((list(recipients), subject, html))
        return len(recipients)

    monkeypatch.setattr(notifications, "send_email", _record)
    return sent


@pytest.fixture
async def atlas_db(db_engine, db_session):
    async with db_engine.begin() as conn:
        await conn.run_sync(lambda c: AtlasSchedule.__table__.create(c, checkfirst=True))
        await conn.run_sync(lambda c: AtlasOperation.__table__.create(c, checkfirst=True))
    return db_session


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


# ── normalisation & rules ───────────────────────────────────────────────


def test_pause_rules_follow_atlas_limits():
    assert pause_rules("M10", "AZURE") == (True, None)
    assert pause_rules("M0", "TENANT")[0] is False
    assert pause_rules("M5", "AWS")[0] is False
    assert "NVMe" in (pause_rules("M40_NVME", "AWS")[1] or "")
    assert pause_rules("R40", "AWS") == (True, None)
    assert pause_rules(None, "AWS")[0] is False


def test_environment_from_tag_then_names():
    assert classify_environment({"environment": "nonprod"}, "prod-main") == "non_production"
    assert classify_environment({"env": "Production"}, "x") == "production"
    assert classify_environment({}, "orders", "commissions-prod") == "production"
    assert classify_environment({}, "orders-dev", "commissions") == "non_production"
    assert classify_environment({}, "orders", "commissions") == "unclassified"


def test_normalize_cluster_reads_2024_08_05_shape():
    cluster = normalize_cluster(_raw_cluster("Dev-Cluster", tier="M30"), {"id": PID, "name": "commissions-nonprod"})
    assert cluster["tier"] == "M30"
    assert cluster["node_count"] == 3
    assert cluster["status"] == "running"
    assert cluster["pausable"] is True
    assert cluster["environment"] == "non_production" and cluster["is_production"] is False
    assert cluster["hosts"][0] == "dev-cluster-shard-00-00.ab1cd.mongodb.net"
    assert cluster["regions"] == ["US_EAST_2"]
    paused = normalize_cluster(_raw_cluster("x", paused=True), {"id": PID, "name": "p"})
    assert paused["status"] == "paused"
    # Unclassified counts as production for confirmations.
    assert paused["environment"] == "unclassified" and paused["is_production"] is True


def test_processes_match_by_connection_string_host_and_dedupe_mongos():
    cluster = normalize_cluster(_raw_cluster("dev-cluster"), {"id": PID, "name": "p"})
    host = "dev-cluster-shard-00-00.ab1cd.mongodb.net"
    processes = [
        {"id": f"{host}:27016", "userAlias": host, "typeName": "SHARD_MONGOS"},
        {"id": f"{host}:27017", "userAlias": host, "typeName": "REPLICA_PRIMARY"},
        {"id": "unrelated:27017", "userAlias": "other-shard-00-00.x.mongodb.net", "typeName": "REPLICA_PRIMARY"},
    ]
    nodes = match_cluster_processes(cluster, processes)
    assert [n["id"] for n in nodes] == [f"{host}:27017"]


# ── client ──────────────────────────────────────────────────────────────


async def test_client_sends_versioned_accept_and_encodes_cidr(fake_atlas):
    service = scheduler_service()
    await service.delete_access_list_entry(PID, "10.0.0.0/24")
    delete = fake_atlas.requests[-1]
    assert delete.method == "DELETE"
    assert delete.url.raw_path.decode().endswith("/accessList/10.0.0.0%2F24")
    assert delete.headers["Accept"] == "application/vnd.atlas.2023-01-01+json"
    assert fake_atlas.access_list == []

    await service.request_power(PID, "dev-cluster", pause=True)
    patch = fake_atlas.requests[-1]
    assert patch.method == "PATCH"
    assert patch.headers["Accept"] == "application/vnd.atlas.2024-10-23+json"
    assert json.loads(patch.content) == {"paused": True}


async def test_client_maps_access_list_refusal_to_a_clear_message(fake_atlas):
    fake_atlas.fail_next = (403, {"error": 403, "errorCode": "IP_ADDRESS_NOT_ON_WHITELIST", "detail": "IP 1.2.3.4"})
    with pytest.raises(AtlasError) as info:
        await scheduler_service().list_projects(fresh=True)
    assert info.value.status_code == 403
    assert "access list" in info.value.user_message


async def test_client_retries_after_429(fake_atlas, monkeypatch):
    sleeps: list[float] = []

    async def _sleep(seconds):
        sleeps.append(seconds)

    monkeypatch.setattr("app.services.mongodb_atlas_service.asyncio.sleep", _sleep)
    fake_atlas.fail_next = (429, {"error": 429, "errorCode": "RATE_LIMITED", "detail": "slow down"})
    projects = await scheduler_service().list_projects(fresh=True)
    assert len(projects) == 2 and len(sleeps) == 1


async def test_project_allowlist_hides_other_projects(fake_atlas, monkeypatch):
    monkeypatch.setattr(settings, "MONGODB_ATLAS_PROJECT_IDS", PID)
    service = scheduler_service()
    service.invalidate()
    assert [p["id"] for p in await service.list_projects(fresh=True)] == [PID]
    with pytest.raises(AtlasError) as info:
        await service.get_cluster(PID_OTHER, "prod-main")
    assert info.value.status_code == 404


async def test_power_request_rules(fake_atlas):
    service = scheduler_service()
    with pytest.raises(AtlasError, match="M10"):
        await service.request_power(PID, "tiny", pause=True)
    fake_atlas.clusters[PID]["dev-cluster"]["stateName"] = "UPDATING"
    with pytest.raises(AtlasError) as busy:
        await service.request_power(PID, "dev-cluster", pause=True)
    assert busy.value.status_code == 409
    fake_atlas.clusters[PID]["dev-cluster"].update(stateName="IDLE", paused=True)
    assert await service.request_power(PID, "dev-cluster", pause=True) == "no_change"


async def test_tier_change_keeps_spec_ids_and_drops_effective_fields(fake_atlas):
    result = await scheduler_service().change_tier(PID, "dev-cluster", "M40")
    body = json.loads(fake_atlas.requests[-1].content)
    spec = body["replicationSpecs"][0]
    assert spec["id"] == "spec-1" and "zoneId" not in spec
    region = spec["regionConfigs"][0]
    assert region["electableSpecs"]["instanceSize"] == "M40"
    assert region["readOnlySpecs"]["instanceSize"] == "M40"
    assert not any(key.startswith("effective") for key in region)
    assert result["tier"] == "M40"


async def test_cluster_metrics_per_node_with_computed_memory(fake_atlas):
    metrics = await scheduler_service().cluster_metrics(PID, "dev-cluster", "PT6H")
    assert metrics["granularity"] == "PT5M"
    assert [n["role"] for n in metrics["nodes"]] == ["Primary", "Secondary", "Secondary"]
    assert metrics["nodes"][0]["label"] == "shard-00-01"
    cpu = metrics["series"]["cpu"]
    assert cpu[-1]["n0"] == 35  # user 30 + kernel 5
    memory = metrics["series"]["memory"]
    assert memory[0]["n0"] == 75.0  # 6 / (6 + 2)
    assert metrics["latest"]["disk"] == 41.3
    assert metrics["latest"]["connections"] == 120  # last non-null per node, summed


def scheduler_service() -> AtlasService:
    from app.services.mongodb_atlas_service import get_atlas_service

    return get_atlas_service()


# ── schedule timing ─────────────────────────────────────────────────────


def test_timing_rejects_sub_hourly_and_stop_soon_after_start():
    with pytest.raises(scheduler.AtlasScheduleError, match="more than once an hour"):
        scheduler.validate_timing(scheduler.ScheduleDraft("recurring", "UTC", stop_cron="*/15 * * * *"))
    with pytest.raises(scheduler.AtlasScheduleError, match="60 minutes"):
        scheduler.validate_timing(
            scheduler.ScheduleDraft("recurring", "UTC", stop_cron="30 7 * * *", start_cron="0 7 * * *")
        )
    with pytest.raises(scheduler.AtlasScheduleError, match="past"):
        scheduler.validate_timing(scheduler.ScheduleDraft("one_time", "UTC", stop_at=datetime(2020, 1, 1)))
    with pytest.raises(scheduler.AtlasScheduleError, match="timezone"):
        scheduler.validate_timing(scheduler.ScheduleDraft("recurring", "Mars/Olympus", stop_cron="0 20 * * *"))
    scheduler.validate_timing(
        scheduler.ScheduleDraft("recurring", "America/Chicago", stop_cron="0 20 * * 1-5", start_cron="0 7 * * 1-5")
    )


def test_weekday_cron_uses_standard_day_numbers_in_the_schedule_timezone():
    draft = scheduler.ScheduleDraft("recurring", "America/Chicago", stop_cron="0 20 * * 1-5")
    # Friday 2026-10-16 21:00 Chicago → next stop is Monday 20:00 CDT = 01:00 UTC Tuesday.
    after = datetime(2026, 10, 17, 2, 0)
    assert scheduler.leg_next_run(draft, "stop", after) == datetime(2026, 10, 20, 1, 0)
    assert scheduler.describe_cron("0 20 * * 1-5") == "weekdays at 20:00"


# ── runner & verifier ───────────────────────────────────────────────────


def _schedule(**overrides) -> AtlasSchedule:
    now = _now()
    values = {
        "name": "nightly",
        "targets": [{"project_id": PID, "project_name": "commissions-nonprod", "cluster_name": "dev-cluster"}],
        "schedule_type": "recurring",
        "timezone": "UTC",
        "stop_cron": "0 20 * * *",
        "start_cron": "0 7 * * *",
        "next_stop_at": now - timedelta(minutes=1),
        "next_start_at": now + timedelta(hours=5),
        "is_enabled": True,
        "notify_on": "always",
        "notification_emails": "team@example.com",
        "remind_minutes_before": 0,
        "skip_next_stop": False,
        "skip_next_start": False,
        "created_by": "u1",
        "created_by_email": "owner@example.com",
    }
    values.update(overrides)
    return AtlasSchedule(**values)


async def test_due_leg_runs_once_even_with_a_stale_second_worker(fake_atlas, atlas_db):
    schedule = _schedule()
    atlas_db.add(schedule)
    await atlas_db.commit()
    stale_due = schedule.next_stop_at

    started = await scheduler.run_due_schedules(atlas_db)
    assert len(started) == 1
    op = (await atlas_db.execute(select(AtlasOperation))).scalar_one()
    assert op.action == "pause" and op.status == "in_progress"
    assert op.targets[0]["status"] == "in_progress"
    assert fake_atlas.clusters[PID]["dev-cluster"]["paused"] is True

    # A second worker read the row before the claim (its own session, so a
    # detached copy here) and loses the compare-and-swap.
    stale = SimpleNamespace(
        id=schedule.id,
        schedule_type="recurring",
        timezone="UTC",
        stop_cron=schedule.stop_cron,
        stop_at=None,
        next_stop_at=stale_due,
        skip_next_stop=False,
    )
    assert await scheduler._claim_leg(atlas_db, stale, "stop", _now()) is False
    await atlas_db.refresh(schedule)
    assert schedule.next_stop_at > _now()


async def test_operation_completes_after_atlas_settles_and_emails_once(fake_atlas, atlas_db, sent_atlas_emails):
    atlas_db.add(_schedule())
    await atlas_db.commit()
    [op_id] = await scheduler.run_due_schedules(atlas_db)

    # Still UPDATING: stays in progress.
    op = await scheduler.check_operation(atlas_db, op_id, _now() + timedelta(minutes=2))
    assert op.status == "in_progress" and op.lease_until is None

    fake_atlas.clusters[PID]["dev-cluster"]["stateName"] = "IDLE"
    op = await scheduler.check_operation(atlas_db, op_id, _now() + timedelta(minutes=4))
    assert op.status == "completed" and op.targets[0]["status"] == "completed"
    await notifications.wait_for_pending_emails()
    assert len(sent_atlas_emails) == 1
    recipients, subject, html = sent_atlas_emails[0]
    assert set(recipients) == {"owner@example.com", "team@example.com"}
    assert "Completed" in subject and "dev-cluster" in html

    schedule = (await atlas_db.execute(select(AtlasSchedule))).scalar_one()
    await atlas_db.refresh(schedule)
    assert schedule.last_run_status == "completed"


async def test_operation_times_out(fake_atlas, atlas_db, monkeypatch):
    monkeypatch.setattr(settings, "MONGODB_ATLAS_OPERATION_TIMEOUT_MINUTES", 5)
    atlas_db.add(_schedule())
    await atlas_db.commit()
    [op_id] = await scheduler.run_due_schedules(atlas_db)
    op = await scheduler.check_operation(atlas_db, op_id, _now() + timedelta(minutes=10))
    assert op.status == "failed"
    assert "Did not finish within 5 minutes" in op.targets[0]["message"]


async def test_skip_next_stop_records_skipped_and_clears_flag(fake_atlas, atlas_db, sent_atlas_emails):
    atlas_db.add(_schedule(skip_next_stop=True))
    await atlas_db.commit()
    [op_id] = await scheduler.run_due_schedules(atlas_db)
    op = (await atlas_db.execute(select(AtlasOperation).where(AtlasOperation.id == op_id))).scalar_one()
    assert op.status == "skipped" and "skip next stop" in op.targets[0]["message"]
    assert fake_atlas.clusters[PID]["dev-cluster"]["paused"] is False
    schedule = (await atlas_db.execute(select(AtlasSchedule))).scalar_one()
    await atlas_db.refresh(schedule)
    assert schedule.skip_next_stop is False


async def test_both_legs_due_only_the_later_one_acts(fake_atlas, atlas_db):
    now = _now()
    atlas_db.add(_schedule(next_stop_at=now - timedelta(hours=10), next_start_at=now - timedelta(hours=1)))
    fake_atlas.clusters[PID]["dev-cluster"]["paused"] = True
    await atlas_db.commit()
    await scheduler.run_due_schedules(atlas_db)
    ops = (await atlas_db.execute(select(AtlasOperation).order_by(AtlasOperation.id))).scalars().all()
    assert [(o.action, o.status) for o in ops] == [("pause", "skipped"), ("resume", "in_progress")]
    assert "later scheduled run" in ops[0].targets[0]["message"]


async def test_one_time_schedule_disables_after_its_last_leg(fake_atlas, atlas_db):
    now = _now()
    atlas_db.add(
        _schedule(
            schedule_type="one_time",
            stop_cron=None,
            start_cron=None,
            stop_at=now - timedelta(minutes=1),
            next_stop_at=now - timedelta(minutes=1),
            next_start_at=None,
        )
    )
    await atlas_db.commit()
    await scheduler.run_due_schedules(atlas_db)
    schedule = (await atlas_db.execute(select(AtlasSchedule))).scalar_one()
    await atlas_db.refresh(schedule)
    assert schedule.is_enabled is False and schedule.next_stop_at is None


async def test_reminder_is_sent_once_per_run(fake_atlas, atlas_db, sent_atlas_emails):
    atlas_db.add(_schedule(next_stop_at=_now() + timedelta(minutes=10), remind_minutes_before=30))
    await atlas_db.commit()
    assert await scheduler.send_due_reminders(atlas_db) == 1
    assert await scheduler.send_due_reminders(atlas_db) == 0
    await notifications.wait_for_pending_emails()
    assert len(sent_atlas_emails) == 1
    assert "Heads-up" in sent_atlas_emails[0][1] and "Skip next stop" in sent_atlas_emails[0][2]


# ── routes ──────────────────────────────────────────────────────────────


def _user(role: UserRole) -> UserContext:
    return UserContext(
        user_id=f"u-{role.value}",
        object_id="00000000-0000-0000-0000-000000000000",
        display_name="Test",
        email=f"{role.value}@example.com",
        roles=[role],
        raw_roles=[role.value],
        tenant_id="t",
        allowed_subscriptions=[],
    )


@pytest.fixture
def strict_auth(monkeypatch):
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    monkeypatch.setattr(settings, "DEV_AUTH_BYPASS", False)


@pytest.fixture
async def client_as(app, atlas_db):
    async def _db():
        yield atlas_db

    clients = []

    async def _make(role: UserRole):
        app.dependency_overrides[get_db] = _db
        app.dependency_overrides[get_current_user] = lambda: _user(role)
        client = AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
        clients.append(client)
        return client

    yield _make
    for client in clients:
        await client.aclose()
    app.dependency_overrides.clear()


def test_module_is_gated_but_needs_no_subscription_grant():
    assert _module_for_path("/api/v1/mongodb-atlas/clusters") == "mongodb_atlas"
    assert "mongodb_atlas" in SUBSCRIPTION_FREE_MODULES


async def test_inventory_lists_clusters_with_schedules(fake_atlas, client_as):
    client = await client_as(UserRole.READ)
    response = await client.get("/api/v1/mongodb-atlas/clusters")
    assert response.status_code == 200, response.text
    body = response.json()
    names = [c["name"] for c in body["clusters"]]
    assert names == ["dev-cluster", "tiny", "prod-main"]
    prod = next(c for c in body["clusters"] if c["name"] == "prod-main")
    assert prod["environment"] == "production"


async def test_read_user_cannot_pause_or_schedule(fake_atlas, client_as, strict_auth):
    client = await client_as(UserRole.READ)
    pause = await client.post(f"/api/v1/mongodb-atlas/projects/{PID}/clusters/dev-cluster/pause", json={})
    assert pause.status_code == 403
    create = await client.post("/api/v1/mongodb-atlas/schedules", json={})
    assert create.status_code in (403, 422)
    assert fake_atlas.clusters[PID]["dev-cluster"]["paused"] is False


async def test_pause_production_needs_typed_name_and_is_audited(fake_atlas, client_as):
    client = await client_as(UserRole.ADMIN)
    url = f"/api/v1/mongodb-atlas/projects/{PID_OTHER}/clusters/prod-main/pause"
    refused = await client.post(url, json={"reason": "cost"})
    assert refused.status_code == 400 and "Type its name" in refused.json()["detail"]
    assert fake_atlas.clusters[PID_OTHER]["prod-main"]["paused"] is False

    accepted = await client.post(url, json={"confirm_name": "prod-main", "reason": "cost", "notify": False})
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["status"] == "in_progress"
    assert fake_atlas.clusters[PID_OTHER]["prod-main"]["paused"] is True

    audit = (await client.get("/api/v1/mongodb-atlas/audit")).json()["entries"]
    actions = [(e["action"], e["status"]) for e in audit]
    assert ("atlas_cluster_pause", "success") in actions
    assert ("atlas_cluster_pause", "failure") in actions


async def test_schedule_crud_validates_targets_and_production(fake_atlas, client_as):
    client = await client_as(UserRole.ADMIN)
    payload = {
        "name": "Weeknights",
        "targets": [{"project_id": PID_OTHER, "cluster_name": "prod-main"}],
        "timezone": "America/Chicago",
        "stop_cron": "0 20 * * 1-5",
        "start_cron": "0 7 * * 1-5",
        "notification_emails": "team@example.com",
        "remind_minutes_before": 15,
    }
    needs_ack = await client.post("/api/v1/mongodb-atlas/schedules", json=payload)
    assert needs_ack.status_code == 400 and "production" in needs_ack.json()["detail"]

    tiny = await client.post(
        "/api/v1/mongodb-atlas/schedules", json={**payload, "targets": [{"project_id": PID, "cluster_name": "tiny"}]}
    )
    assert tiny.status_code == 400 and "M10" in tiny.json()["detail"]

    created = await client.post("/api/v1/mongodb-atlas/schedules", json={**payload, "acknowledge_production": True})
    assert created.status_code == 200, created.text
    schedule = created.json()
    assert schedule["targets"][0]["project_name"] == "commissions-prod"
    assert schedule["stop_description"] == "weekdays at 20:00"
    assert schedule["next_stop_at"] and schedule["next_start_at"]

    dup = await client.post("/api/v1/mongodb-atlas/schedules", json={**payload, "acknowledge_production": True})
    assert dup.status_code == 409

    skipped = await client.post(f"/api/v1/mongodb-atlas/schedules/{schedule['id']}/skip", json={"leg": "stop"})
    assert skipped.json()["skip_next_stop"] is True

    edited = await client.put(f"/api/v1/mongodb-atlas/schedules/{schedule['id']}", json={"stop_cron": "0 21 * * 1-5"})
    assert edited.status_code == 200 and edited.json()["stop_description"] == "weekdays at 21:00"

    bad = await client.put(f"/api/v1/mongodb-atlas/schedules/{schedule['id']}", json={"start_cron": "30 20 * * 1-5"})
    assert bad.status_code == 400

    preview = await client.get(
        "/api/v1/mongodb-atlas/schedules/preview", params={"stop_cron": "0 20 * * 1-5", "timezone": "UTC"}
    )
    assert preview.json()["valid"] is True and len(preview.json()["stop"]) == 5

    deleted = await client.delete(f"/api/v1/mongodb-atlas/schedules/{schedule['id']}")
    assert deleted.status_code == 200
    actions = [e["action"] for e in (await client.get("/api/v1/mongodb-atlas/audit")).json()["entries"]]
    for expected in ("atlas_schedule_create", "atlas_schedule_skip", "atlas_schedule_update", "atlas_schedule_delete"):
        assert expected in actions


async def test_access_list_add_and_remove_are_audited(fake_atlas, client_as):
    client = await client_as(UserRole.WRITE)
    added = await client.post(
        f"/api/v1/mongodb-atlas/projects/{PID}/access-list", json={"entry": "192.168.10.0/24", "comment": "aks egress"}
    )
    assert added.status_code == 200, added.text
    everything = await client.post(f"/api/v1/mongodb-atlas/projects/{PID}/access-list", json={"entry": "0.0.0.0/0"})
    assert everything.status_code == 422
    removed = await client.delete(f"/api/v1/mongodb-atlas/projects/{PID}/access-list/192.168.10.0/24")
    assert removed.status_code == 200, removed.text
    assert all(e.get("cidrBlock") != "192.168.10.0/24" for e in fake_atlas.access_list)
    actions = [e["action"] for e in (await client.get("/api/v1/mongodb-atlas/audit")).json()["entries"]]
    assert "atlas_access_list_add" in actions and "atlas_access_list_delete" in actions


async def test_atlas_key_refusal_is_not_passed_through_as_401(fake_atlas, client_as):
    client = await client_as(UserRole.READ)
    set_atlas_service(None)
    fake_atlas.fail_next = (401, {"error": 401, "errorCode": "UNAUTHORIZED", "detail": "bad key"})
    client_obj = AtlasClient(
        base_url="https://cloud.mongodb.com",
        public_key="abcd",
        private_key="wrong",
        transport=httpx.MockTransport(fake_atlas.handler),
    )
    set_atlas_service(AtlasService(client_obj))
    response = await client.get("/api/v1/mongodb-atlas/projects")
    assert response.status_code == 502
    assert "API key" in response.json()["detail"]


async def test_status_reports_portal_ip_and_key_roles(fake_atlas, client_as):
    client = await client_as(UserRole.READ)
    status = (await client.get("/api/v1/mongodb-atlas/status")).json()
    assert status["configured"] and status["reachable"]
    assert status["portal_ip"] == "203.0.113.9"
    assert status["api_key_roles"][0]["role"] == "ORG_READ_ONLY"
    assert status["public_key"].startswith("abcd") and "secret" not in json.dumps(status)


@pytest.mark.real_access
async def test_user_without_any_subscription_grant_can_still_use_atlas(app, atlas_db, monkeypatch):
    """Atlas projects are not Azure subscriptions: no grant must not mean no Atlas.

    The same user is refused on an Azure module, which proves the grant check
    really ran and was skipped only for this module.
    """
    from tests.access_helpers import SUB, build_world, make_user
    from tests.access_helpers import client_as as access_client_as

    async def _monitored():
        return list(SUB.values())

    monkeypatch.setattr("app.core.subscription_scope.get_monitored_subscription_ids", _monitored)
    await build_world(atlas_db)
    async with access_client_as(app, atlas_db, make_user("newbie", UserRole.READ)) as ac:
        atlas = await ac.get("/api/v1/mongodb-atlas/schedules")
        azure = await ac.get("/api/v1/aks/clusters/cached")
    assert atlas.status_code == 200, atlas.text
    assert azure.status_code == 403


# ── reaching Atlas through a corporate network ─────────────────────────


async def test_tls_handshake_cut_by_the_network_is_explained_not_blank():
    """A firewall closing the TLS handshake surfaces in httpx as ConnectError('').

    The message must name the real cause and the fix, and the client must not
    retry a connection that cannot be made.
    """
    import asyncio

    connections = 0

    async def _drop(reader, writer):
        nonlocal connections
        connections += 1
        await reader.read(10)
        writer.close()

    server = await asyncio.start_server(_drop, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    try:
        client = AtlasClient(base_url=f"https://127.0.0.1:{port}", public_key="k", private_key="p", timeout=5)
        with pytest.raises(AtlasError) as info:
            await client.request("GET", "/groups")
    finally:
        server.close()
    error = info.value
    assert error.error_code == "UNREACHABLE" and error.status_code == 502
    assert "SSLEOFError" in error.user_message
    assert "TLS handshake" in error.user_message and "MONGODB_ATLAS_PROXY" in error.user_message
    assert connections == 1


def test_proxy_credentials_are_never_shown():
    from app.services.mongodb_atlas_service import mask_proxy

    assert mask_proxy("http://svc:s3cret@proxy.corp.example:8080") == "http://***@proxy.corp.example:8080"
    assert mask_proxy("proxy.corp.example:3128") == "http://proxy.corp.example:3128"
    assert mask_proxy("") is None


async def test_configured_proxy_is_used_and_its_refusal_explained(monkeypatch):
    """Requests go to MONGODB_ATLAS_PROXY as CONNECT cloud.mongodb.com:443."""
    import asyncio

    seen: list[bytes] = []

    async def _proxy(reader, writer):
        seen.append(await reader.readline())
        await reader.readuntil(b"\r\n\r\n")
        writer.write(b"HTTP/1.1 403 Forbidden\r\nContent-Length: 0\r\n\r\n")
        await writer.drain()
        writer.close()

    server = await asyncio.start_server(_proxy, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    monkeypatch.setattr(settings, "MONGODB_ATLAS_PUBLIC_KEY", "abcd")
    monkeypatch.setattr(settings, "MONGODB_ATLAS_PRIVATE_KEY", "secret-key")
    monkeypatch.setattr(settings, "MONGODB_ATLAS_PROXY", f"http://svc:pw@127.0.0.1:{port}")
    set_atlas_service(None)
    try:
        with pytest.raises(AtlasError) as info:
            await scheduler_service().list_projects(fresh=True)
    finally:
        server.close()
        set_atlas_service(None)
    assert seen and seen[0].startswith(b"CONNECT cloud.mongodb.com:443")
    message = info.value.user_message
    assert "through proxy http://***@127.0.0.1" in message and "pw" not in message
    assert "proxy refused" in message


async def test_status_stops_after_a_network_failure(fake_atlas):
    fake_atlas.transport_error = httpx.ConnectError("")
    status = await scheduler_service().status()
    assert status["reachable"] is False and status["error_code"] == "UNREACHABLE"
    assert "MONGODB_ATLAS_PROXY" in status["error"]
    # One attempt at the key check, and no second call for the project list.
    assert len(fake_atlas.requests) == 1


@pytest.fixture
async def no_real_network(monkeypatch):
    import asyncio

    class _Writer:
        def close(self):
            pass

        async def wait_closed(self):
            pass

    async def _open(host, port):
        return None, _Writer()

    async def _resolve(host, port, **kwargs):
        return [(2, 1, 6, "", ("192.0.2.10", port))]

    monkeypatch.setattr("app.services.mongodb_atlas_service.asyncio.open_connection", _open)
    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", _resolve)


async def test_connection_test_walks_every_step(fake_atlas, no_real_network, monkeypatch):
    monkeypatch.setattr(settings, "MONGODB_ATLAS_PROJECT_IDS", f"{PID},{'f' * 24}")
    result = await scheduler_service().connection_test()
    steps = {step["name"]: step for step in result["steps"]}
    assert [step["name"] for step in result["steps"]] == ["configuration", "dns", "tcp", "https", "api_key", "projects"]
    assert steps["https"]["status"] == "ok" and "Digest challenge" in steps["https"]["detail"]
    assert steps["api_key"]["status"] == "ok" and "203.0.113.9" in steps["api_key"]["detail"]
    # The allow-listed project the key cannot see is called out.
    assert steps["projects"]["status"] == "failed" and "f" * 24 in steps["projects"]["detail"]
    assert result["ok"] is False and "Not visible to the key" in result["summary"]


async def test_connection_test_points_at_the_broken_step(fake_atlas, no_real_network):
    fake_atlas.transport_error = httpx.ConnectError("")
    result = await scheduler_service().connection_test()
    steps = {step["name"]: step for step in result["steps"]}
    assert steps["tcp"]["status"] == "ok"
    assert steps["https"]["status"] == "failed"
    assert steps["api_key"]["status"] == "skipped" and steps["projects"]["status"] == "skipped"
    assert result["ok"] is False and result["summary"] == steps["https"]["detail"]


async def test_connection_test_route_is_open_to_readers(fake_atlas, no_real_network, client_as):
    client = await client_as(UserRole.READ)
    response = await client.get("/api/v1/mongodb-atlas/connection-test")
    assert response.status_code == 200, response.text
    assert response.json()["ok"] is True
