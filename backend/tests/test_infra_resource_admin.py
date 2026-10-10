"""Infra Alerts resource administration: VM Run Command, utilization, history, tags, disks.

Azure SDK clients are faked; audit rows, inventory rows and subscription tiers
use real queries against SQLite (JSONB compiled as JSON).
"""

from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.ext.compiler import compiles

from app.models.database import AdminSubscription, AuditLog, AzureResourceInventory
from app.services import infra_resource_admin_service as admin_module
from app.services.infra_resource_admin_service import InfraResourceAdminService

PROD = "169cc835-0000-0000-0000-000000000000"
NPRD = "d1516897-0000-0000-0000-000000000000"


@compiles(JSONB, "sqlite")
def _jsonb_as_json_on_sqlite(_type, _compiler, **_kw):
    return "JSON"


@pytest.fixture
async def factory(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'admin.db'}")
    async with engine.begin() as conn:
        for model in (AuditLog, AzureResourceInventory, AdminSubscription):
            await conn.run_sync(lambda c, table=model.__table__: table.create(c))
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False, autoflush=False)
    async with maker() as db:
        db.add_all(
            [
                AdminSubscription(subscription_id=PROD, subscription_name="ACC-PROD-31599-ATTCC"),
                AdminSubscription(subscription_id=NPRD, subscription_name="ACC-NPRD-31599-ATTCC"),
            ]
        )
        await db.commit()
    yield maker
    await engine.dispose()


USER = SimpleNamespace(user_id="u1", email="ops@att.com")


class _Poller:
    def result(self):
        return None


class _FakeCompute:
    """Records calls; a VM whose run command finishes on the second poll."""

    def __init__(self, power="running", os_type="Linux"):
        self.created: list[tuple] = []
        self.deleted: list[str] = []
        self.polls = 0
        statuses = [SimpleNamespace(code="ProvisioningState/succeeded"), SimpleNamespace(code=f"PowerState/{power}")]
        vm = SimpleNamespace(
            location="eastus2",
            instance_view=SimpleNamespace(statuses=statuses),
            storage_profile=SimpleNamespace(os_disk=SimpleNamespace(os_type=os_type)),
        )
        outer = self

        class _VMs:
            def get(self, rg, name, expand=None):
                return vm

        class _RunCommands:
            def begin_create_or_update(self, rg, vm_name, run_name, command):
                outer.created.append((rg, vm_name, run_name, command))
                return _Poller()

            def get_by_virtual_machine(self, rg, vm_name, run_name, expand=None):
                outer.polls += 1
                started = datetime(2026, 10, 11, 2, 0)
                view = SimpleNamespace(
                    execution_state="Running",
                    exit_code=None,
                    output="",
                    error="",
                    execution_message=None,
                    start_time=started,
                    end_time=None,
                )
                if outer.polls > 1:
                    view.execution_state, view.exit_code = "Succeeded", 0
                    view.output, view.end_time = " 02:01:00 up 9 days\n", started + timedelta(seconds=4)
                return SimpleNamespace(provisioning_state="Succeeded", instance_view=view)

            def begin_delete(self, rg, vm_name, run_name):
                outer.deleted.append(run_name)
                return _Poller()

        self.virtual_machines = _VMs()
        self.virtual_machine_run_commands = _RunCommands()


def _service(db, compute) -> InfraResourceAdminService:
    service = InfraResourceAdminService(db)
    service._compute = lambda _sub: compute
    return service


async def _audits(factory):
    async with factory() as db:
        return list((await db.execute(select(AuditLog).order_by(AuditLog.id))).scalars().all())


async def _start(service, **overrides):
    values = {
        "user": USER,
        "ip": "10.0.0.1",
        "subscription_id": NPRD,
        "resource_group": "RG",
        "vm_name": "nprd-vm",
        "script": "uptime",
        "timeout_seconds": 120,
        "confirm_name": None,
        **overrides,
    }
    return await service.start_run_command(**values)


# ── Run Command ────────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_run_command_starts_async_and_finishes_on_one_audit_row(factory):
    compute = _FakeCompute()
    async with factory() as db:
        service = _service(db, compute)
        started = await _start(service)
        [(_rg, _vm, run_name, command)] = compute.created
        # The request only starts the script; Azure runs it.
        assert command.async_execution is True
        assert command.source.script == "uptime"
        assert started == {"run_id": run_name, "state": "Pending", "shell": "bash", "tier": "nonprod"}

        target = {"subscription_id": NPRD, "resource_group": "RG", "vm_name": "nprd-vm", "run_id": run_name}
        assert (await service.get_run_command(**target))["state"] == "Running"
        done = await service.get_run_command(**target)
        assert (done["state"], done["exit_code"], done["output"]) == ("Succeeded", 0, " 02:01:00 up 9 days\n")
        # Finished: recorded, cleaned up in Azure, and later polls come from the audit row.
        assert compute.deleted == [run_name]
        assert (await service.get_run_command(**target))["output"] == done["output"]
        assert compute.polls == 2

        history = await service.run_command_history(subscription_id=NPRD, vm_name="nprd-vm")

    [audit] = await _audits(factory)
    assert (audit.action, audit.status, audit.user_email) == ("virtual_machine_run_command", "success", "ops@att.com")
    assert (audit.details["script"], audit.details["exit_code"], audit.details["tier"]) == ("uptime", 0, "nonprod")
    assert [(h["run_id"], h["state"]) for h in history] == [(run_name, "Succeeded")]


@pytest.mark.anyio
async def test_production_vm_needs_its_name_typed(factory):
    compute = _FakeCompute()
    async with factory() as db:
        service = _service(db, compute)
        with pytest.raises(HTTPException) as exc:
            await _start(service, subscription_id=PROD, vm_name="prd-vm", confirm_name="yes")
        assert exc.value.status_code == 422
        assert compute.created == []
        await _start(service, subscription_id=PROD, vm_name="prd-vm", confirm_name="PRD-VM")
        assert len(compute.created) == 1

    blocked, running = await _audits(factory)
    assert (blocked.status, blocked.details["error"]) == ("blocked", "production_not_confirmed")
    assert running.status == "running"


@pytest.mark.anyio
async def test_unknown_subscription_counts_as_production(factory):
    async with factory() as db:
        assert await InfraResourceAdminService(db).subscription_tier("aaaaaaaa-0000-0000-0000-000000000000") == "prod"
        assert await InfraResourceAdminService(db).subscription_tier(NPRD.upper()) == "nonprod"


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("overrides", "compute", "status"),
    [
        ({"script": "rm -rf / --no-preserve-root"}, _FakeCompute(), 403),
        ({"script": "   "}, _FakeCompute(), 400),
        ({}, _FakeCompute(power="deallocated"), 409),
    ],
)
async def test_refused_runs_are_audited_and_never_reach_azure(factory, overrides, compute, status):
    async with factory() as db:
        with pytest.raises(HTTPException) as exc:
            await _start(_service(db, compute), **overrides)
    assert exc.value.status_code == status
    assert compute.created == []
    [audit] = await _audits(factory)
    assert audit.status == "blocked"


@pytest.mark.anyio
async def test_windows_vm_runs_powershell(factory):
    async with factory() as db:
        started = await _start(_service(db, _FakeCompute(os_type="OperatingSystemTypes.WINDOWS")), script="Get-Service")
    assert started["shell"] == "PowerShell"


@pytest.mark.anyio
async def test_unknown_run_ids_are_404(factory):
    async with factory() as db:
        service = _service(db, _FakeCompute())
        for run_id in ("../../etc", "opsportal-never-started"):
            with pytest.raises(HTTPException) as exc:
                service._compute = lambda _sub: SimpleNamespace(
                    virtual_machine_run_commands=SimpleNamespace(get_by_virtual_machine=_raise)
                )
                await service.get_run_command(subscription_id=NPRD, resource_group="RG", vm_name="vm", run_id=run_id)
            assert exc.value.status_code == 404


def _raise(*_args, **_kwargs):
    raise RuntimeError("ResourceNotFound")


# ── Utilization and history ────────────────────────────────────────────


def _vm_row(name, power, sub=NPRD):
    return AzureResourceInventory(
        resource_id=f"/subscriptions/{sub}/resourceGroups/RG/providers/Microsoft.Compute/virtualMachines/{name}",
        name=name,
        resource_type="virtual_machine",
        resource_group="RG",
        subscription_id=sub,
        resource_details={"name": name, "power_state": power},
    )


@pytest.mark.anyio
async def test_utilization_reads_running_vms_once_per_ttl(factory, monkeypatch):
    async with factory() as db:
        db.add_all([_vm_row("app-vm", "running"), _vm_row("dev-vm", "deallocated")])
        await db.commit()
    calls = []

    async def _metrics(self, sub, rg, name):
        calls.append(name)
        return {"cpu": 41.2, "memory": 63.0, "disk": 2.0}

    async def _scope():
        return [NPRD]

    admin_module._utilization_cache.clear()
    monkeypatch.setattr(admin_module, "get_scoped_subscription_ids", _scope)
    monkeypatch.setattr(admin_module.InfraAlertService, "get_vm_metrics", _metrics)
    async with factory() as db:
        service = InfraResourceAdminService(db)
        first = await service.utilization("vm")
        await service.utilization("vm")

    assert calls == ["app-vm"]  # stopped VMs are not queried; the second call is cached
    items = {key.rsplit("/", 1)[-1]: value for key, value in first["items"].items()}
    assert items["app-vm"]["cpu"] == 41.2
    assert items["dev-vm"] == {"state": "deallocated", "cpu": None, "memory": None}


@pytest.mark.anyio
async def test_history_reports_memory_used_and_the_busiest_disk(monkeypatch):
    t0, t1 = datetime(2026, 10, 11, 1, 0), datetime(2026, 10, 11, 1, 15)

    def _series(self, sub, rid, names, hours):
        return {
            "Percentage CPU": [(t0, 40.0, 70.0, 10.0), (t1, 60.0, 95.0, 20.0)],
            "Available Memory Percentage": [(t0, 70.0, 80.0, 60.0), (t1, 50.0, 55.0, 30.0)],
            "OS Disk IOPS Consumed Percentage": [(t0, 2.0, 5.0, 0.0), (t1, 3.0, 4.0, 0.0)],
            "Data Disk Bandwidth Consumed Percentage": [(t0, 12.0, 30.0, 0.0), (t1, 1.0, 2.0, 0.0)],
        }

    monkeypatch.setattr(InfraResourceAdminService, "_metric_series", _series)
    history = await InfraResourceAdminService(None).metrics_history("vm", NPRD, "RG", "vm", 24)

    first, second = history["points"]
    assert (first["memory"], first["memory_max"]) == (30.0, 40.0)  # used = 100 - available; peak from the minimum
    assert (first["disk"], first["disk_max"]) == (12.0, 30.0)
    assert history["summary"]["cpu"] == {"average": 50.0, "peak": 95.0, "latest": 60.0}
    assert history["summary"]["memory"]["latest"] == 50.0
    assert history["interval"] == "PT15M"

    with pytest.raises(HTTPException):
        await InfraResourceAdminService(None).metrics_history("vm", NPRD, "RG", "vm", 5)


# ── Tags and disks ─────────────────────────────────────────────────────


def test_tag_validation():
    assert InfraResourceAdminService.validate_tags({" env ": " prd1 ", "owner": ""}) == {"env": "prd1", "owner": ""}
    for bad in ({"": "x"}, {"a/b": "x"}, {"k": "v" * 257}, {f"k{i}": "v" for i in range(51)}):
        with pytest.raises(HTTPException):
            InfraResourceAdminService.validate_tags(bad)


@pytest.mark.anyio
async def test_replace_tags_uses_replace_and_updates_the_inventory(factory):
    patched = []

    class _Tags:
        def begin_update_at_scope(self, scope, patch):
            patched.append((scope, patch.operation, patch.properties.tags))
            return _Poller()

    resource_id = f"/subscriptions/{NPRD}/resourceGroups/RG/providers/Microsoft.Compute/virtualMachines/app-vm"
    async with factory() as db:
        db.add(_vm_row("app-vm", "running"))
        await db.commit()
        service = InfraResourceAdminService(db)
        service._resources = lambda _sub: SimpleNamespace(tags=_Tags())
        await service.replace_tags(resource_id, "virtual_machine", {"env": "prf1"})
        row = (await db.execute(select(AzureResourceInventory))).scalar_one()

    assert patched == [(resource_id, "Replace", {"env": "prf1"})]
    assert row.tags == {"env": "prf1"}
    assert row.resource_details["tags"] == {"env": "prf1"}


@pytest.mark.anyio
async def test_disks_only_grow():
    service = InfraResourceAdminService(None)
    disk = SimpleNamespace(disk_size_gb=512)
    service._compute = lambda _sub: SimpleNamespace(disks=SimpleNamespace(get=lambda rg, name: disk))
    with pytest.raises(HTTPException) as exc:
        await service.expand_disk(NPRD, "RG", "data-disk", 256)
    assert exc.value.status_code == 422
    assert "already 512 GB" in exc.value.detail


def test_history_grains_cover_the_ui_ranges():
    assert set(admin_module.HISTORY_GRAINS) >= {1, 6, 24, 168}
    assert all(timedelta(hours=h) > timedelta(0) for h in admin_module.HISTORY_GRAINS)
