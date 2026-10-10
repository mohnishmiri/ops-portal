"""
Administrative operations and utilization for the Infrastructure Alerts resources.

- Utilization: current CPU / memory for every running VM and PG server (one
  call per resource, bounded concurrency, cached briefly) and metric history
  for one resource.
- VM Run Command: Azure *managed* run commands with ``async_execution``, so the
  HTTP request only starts the script. Status is read back from Azure by run
  name — any worker on any replica can answer a poll, nothing is held in
  process memory. Every run is one ``audit_logs`` row (script, who, result).
- VM resize / redeploy / boot diagnostics, resource tags, disk snapshot and
  expansion, PG Flexible Server databases and firewall rules.

Power actions (start / stop / restart) stay in AzureResourceService.
"""

from __future__ import annotations

import asyncio
import re
import secrets
import time
from datetime import datetime, timedelta
from typing import Any

import httpx
import structlog
from fastapi import HTTPException
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.access_scope import classify_subscription, normalize_tier
from app.core.azure_auth import get_azure_credential
from app.core.subscription_scope import get_scoped_subscription_ids
from app.models.database import AdminSubscription, AuditLog, AzureResourceInventory
from app.services.infra_alert_service import (
    VM_CPU_METRIC,
    VM_DISK_METRICS,
    VM_MEMORY_METRIC,
    InfraAlertService,
)

logger = structlog.get_logger(__name__)

RUN_COMMAND_ACTION = "virtual_machine_run_command"
RUN_COMMAND_PREFIX = "opsportal-"
MAX_SCRIPT_CHARS = 16_000
MAX_STORED_OUTPUT = 16_000
TERMINAL_STATES = {"Succeeded", "Failed", "TimedOut", "Canceled"}
# A speed bump against obvious accidents, mirroring AKS pod exec — not a security boundary.
BLOCKED_COMMAND_FRAGMENTS = ("rm -rf /", "rm -rf /*", "mkfs", "dd if=", ":(){", "wipefs", "shred /dev/")

UTILIZATION_TTL_SECONDS = 120
UTILIZATION_CONCURRENCY = 8
_utilization_cache: dict[tuple[str, tuple[str, ...]], tuple[float, dict[str, Any]]] = {}

# Window (hours) -> metric grain. Coarser grains keep long ranges at a few hundred points.
HISTORY_GRAINS = {1: "PT1M", 6: "PT5M", 24: "PT15M", 72: "PT30M", 168: "PT1H", 720: "PT6H"}
PG_HISTORY_METRICS = ("cpu_percent", "memory_percent", "storage_percent", "active_connections")

_TAG_KEY_INVALID = re.compile(r"[<>%&\\?/]")


def _arm_id(subscription_id: str, resource_group: str, provider: str, name: str) -> str:
    return f"/subscriptions/{subscription_id}/resourceGroups/{resource_group}/providers/{provider}/{name}"


def _round(value: float | None) -> float | None:
    return round(value, 2) if value is not None else None


def _state_of(details: dict[str, Any], resource_type: str) -> str | None:
    return details.get("power_state") if resource_type == "virtual_machine" else details.get("state")


class InfraResourceAdminService:
    def __init__(self, db: AsyncSession | None):
        self.db = db
        self.credential = get_azure_credential()

    # ── Clients ────────────────────────────────────────────────────────

    def _compute(self, subscription_id: str):
        from azure.mgmt.compute import ComputeManagementClient

        return ComputeManagementClient(self.credential, subscription_id)

    def _monitor(self, subscription_id: str):
        from azure.mgmt.monitor import MonitorManagementClient

        return MonitorManagementClient(self.credential, subscription_id)

    def _resources(self, subscription_id: str):
        from azure.mgmt.resource import ResourceManagementClient

        return ResourceManagementClient(self.credential, subscription_id)

    def _pg(self, subscription_id: str):
        from azure.mgmt.rdbms.postgresql_flexibleservers import PostgreSQLManagementClient

        return PostgreSQLManagementClient(self.credential, subscription_id)

    # ── Helpers ────────────────────────────────────────────────────────

    async def subscription_tier(self, subscription_id: str) -> str:
        """``prod`` or ``nonprod``; unknown subscriptions count as prod (fail safe)."""
        if self.db is None:
            return "prod"
        row = (
            await self.db.execute(
                select(
                    AdminSubscription.tier, AdminSubscription.subscription_name, AdminSubscription.environment
                ).where(func.lower(AdminSubscription.subscription_id) == subscription_id.lower())
            )
        ).first()
        if row is None:
            return "prod"
        if row.tier:
            return normalize_tier(row.tier)
        return classify_subscription(row.subscription_name, row.environment).tier

    async def _inventory_row(self, resource_type: str, subscription_id: str, resource_group: str, name: str):
        if self.db is None:
            return None
        return (
            (
                await self.db.execute(
                    select(AzureResourceInventory).where(
                        AzureResourceInventory.resource_type == resource_type,
                        AzureResourceInventory.subscription_id == subscription_id,
                        func.lower(AzureResourceInventory.name) == name.lower(),
                        func.lower(AzureResourceInventory.resource_group) == resource_group.lower(),
                    )
                )
            )
            .scalars()
            .first()
        )

    async def _patch_inventory(
        self, resource_type: str, subscription_id: str, resource_group: str, name: str, **fields
    ) -> None:
        """Merge fields into an inventory row's details so grids reflect a change before the next sync."""
        row = await self._inventory_row(resource_type, subscription_id, resource_group, name)
        if row is None:
            return
        details = dict(row.resource_details or {})
        details.update(fields)
        row.resource_details = details
        if "tags" in fields:
            row.tags = fields["tags"]
        row.last_sync = datetime.utcnow()
        await self.db.commit()

    # ── Utilization ────────────────────────────────────────────────────

    async def utilization(self, kind: str) -> dict[str, Any]:
        """Current CPU / memory (and disk I/O or storage) for every running VM or PG server in scope."""
        resource_type = "virtual_machine" if kind == "vm" else "pg_flex_server"
        scoped = await get_scoped_subscription_ids()
        key = (kind, tuple(sorted(s.lower() for s in scoped)))
        cached = _utilization_cache.get(key)
        if cached and time.monotonic() - cached[0] < UTILIZATION_TTL_SECONDS:
            return cached[1]

        rows = []
        if self.db is not None:
            rows = (
                (
                    await self.db.execute(
                        select(AzureResourceInventory).where(
                            AzureResourceInventory.resource_type == resource_type,
                            AzureResourceInventory.subscription_id.in_(scoped),
                        )
                    )
                )
                .scalars()
                .all()
            )
        reader = InfraAlertService(None)
        gate = asyncio.Semaphore(UTILIZATION_CONCURRENCY)
        running = {"running"} if kind == "vm" else {"Ready"}

        async def _read(row) -> tuple[str, dict[str, Any]]:
            details = row.resource_details or {}
            state = _state_of(details, resource_type)
            if state not in running:
                return row.resource_id.lower(), {"state": state, "cpu": None, "memory": None}
            async with gate:
                if kind == "vm":
                    metrics = await reader.get_vm_metrics(row.subscription_id, row.resource_group, row.name)
                else:
                    metrics = await reader.get_pg_metrics(row.subscription_id, row.resource_group, row.name)
            return row.resource_id.lower(), {"state": state, **metrics}

        items = dict(await asyncio.gather(*(_read(row) for row in rows)))
        payload = {"kind": kind, "generated_at": datetime.utcnow().isoformat(), "items": items}
        _utilization_cache[key] = (time.monotonic(), payload)
        return payload

    def _metric_series(
        self, subscription_id: str, resource_id: str, names: list[str], hours: int
    ) -> dict[str, list[tuple[datetime, float | None, float | None, float | None]]]:
        """Blocking Azure Monitor read: name -> [(time, average, maximum, minimum)]."""
        end = datetime.utcnow()
        start = end - timedelta(hours=hours)
        response = self._monitor(subscription_id).metrics.list(
            resource_id,
            timespan=f"{start:%Y-%m-%dT%H:%M:%S}Z/{end:%Y-%m-%dT%H:%M:%S}Z",
            interval=HISTORY_GRAINS[hours],
            metricnames=",".join(names),
            aggregation="Average,Maximum,Minimum",
        )
        series: dict[str, list[tuple[datetime, float | None, float | None, float | None]]] = {}
        for item in response.value:
            points = []
            for ts in item.timeseries or []:
                for point in ts.data or []:
                    points.append((point.time_stamp, point.average, point.maximum, point.minimum))
            series[item.name.value] = sorted(points, key=lambda p: p[0])
        return series

    async def metrics_history(
        self, kind: str, subscription_id: str, resource_group: str, name: str, hours: int
    ) -> dict:
        """Utilization over time for one VM or PG server, plus average / peak / latest per metric."""
        if hours not in HISTORY_GRAINS:
            raise HTTPException(status_code=422, detail=f"hours must be one of {sorted(HISTORY_GRAINS)}")
        if kind == "vm":
            resource_id = _arm_id(subscription_id, resource_group, "Microsoft.Compute/virtualMachines", name)
            names = [VM_CPU_METRIC, VM_MEMORY_METRIC, *VM_DISK_METRICS]
        else:
            resource_id = _arm_id(subscription_id, resource_group, "Microsoft.DBforPostgreSQL/flexibleServers", name)
            names = list(PG_HISTORY_METRICS)
        try:
            try:
                series = await asyncio.to_thread(self._metric_series, subscription_id, resource_id, names, hours)
            except Exception:
                if kind != "vm":
                    raise
                # Older VMs do not publish the memory percentage; one unknown name fails the request.
                without_memory = [n for n in names if n != VM_MEMORY_METRIC]
                series = await asyncio.to_thread(
                    self._metric_series, subscription_id, resource_id, without_memory, hours
                )
        except Exception as exc:
            logger.warning("metrics_history_failed", resource=name, error=str(exc)[:300])
            raise HTTPException(status_code=502, detail=f"Azure Monitor could not return metrics: {str(exc)[:300]}")

        points: dict[datetime, dict[str, Any]] = {}

        def _put(stamp: datetime, key: str, value: float | None) -> None:
            if value is None:
                return
            row = points.setdefault(stamp, {"time": stamp.isoformat()})
            row[key] = round(value, 2)

        if kind == "vm":
            for stamp, avg, peak, _low in series.get(VM_CPU_METRIC, []):
                _put(stamp, "cpu", avg)
                _put(stamp, "cpu_max", peak)
            # Memory used = 100 - available; the peak of "used" is the minimum of "available".
            for stamp, avg, _peak, low in series.get(VM_MEMORY_METRIC, []):
                _put(stamp, "memory", 100 - avg if avg is not None else None)
                _put(stamp, "memory_max", 100 - low if low is not None else None)
            for metric in VM_DISK_METRICS:
                for stamp, avg, peak, _low in series.get(metric, []):
                    row = points.setdefault(stamp, {"time": stamp.isoformat()})
                    if avg is not None:
                        row["disk"] = max(row.get("disk", 0), round(avg, 2))
                    if peak is not None:
                        row["disk_max"] = max(row.get("disk_max", 0), round(peak, 2))
            keys = ("cpu", "memory", "disk")
        else:
            for metric, key in (("cpu_percent", "cpu"), ("memory_percent", "memory"), ("storage_percent", "storage")):
                for stamp, avg, peak, _low in series.get(metric, []):
                    _put(stamp, key, avg)
                    _put(stamp, f"{key}_max", peak)
            for stamp, avg, peak, _low in series.get("active_connections", []):
                _put(stamp, "connections", avg)
                _put(stamp, "connections_max", peak)
            keys = ("cpu", "memory", "storage", "connections")

        ordered = [points[stamp] for stamp in sorted(points)]
        summary = {}
        for key in keys:
            values = [p[key] for p in ordered if key in p]
            peaks = [p.get(f"{key}_max", p.get(key)) for p in ordered if key in p]
            summary[key] = {
                "average": _round(sum(values) / len(values)) if values else None,
                "peak": _round(max(peaks)) if peaks else None,
                "latest": values[-1] if values else None,
            }
        return {"kind": kind, "hours": hours, "interval": HISTORY_GRAINS[hours], "points": ordered, "summary": summary}

    # ── VM Run Command ─────────────────────────────────────────────────

    async def _write_audit(
        self, *, user, ip: str | None, vm_name: str, status: str, details: dict[str, Any]
    ) -> AuditLog | None:
        if self.db is None:
            return None
        row = AuditLog(
            user_id=user.user_id,
            user_email=user.email,
            action=RUN_COMMAND_ACTION,
            resource_type="virtual_machine",
            resource_id=vm_name,
            details={"page": "InfraAlertPage", "feature": "vm_run_command", **details},
            ip_address=ip,
            status=status,
        )
        try:
            self.db.add(row)
            await self.db.commit()
            return row
        except Exception as exc:
            await self.db.rollback()
            logger.warning("run_command_audit_failed", vm=vm_name, error=str(exc)[:200])
            return None

    async def start_run_command(
        self,
        *,
        user,
        ip: str | None,
        subscription_id: str,
        resource_group: str,
        vm_name: str,
        script: str,
        timeout_seconds: int,
        confirm_name: str | None,
    ) -> dict[str, Any]:
        """Start a script on a VM and return at once; poll :meth:`get_run_command` for the result."""
        base = {
            "subscription_id": subscription_id,
            "resource_group": resource_group,
            "script": script[:MAX_SCRIPT_CHARS],
        }

        async def _refuse(code: int, reason: str, message: str):
            await self._write_audit(
                user=user, ip=ip, vm_name=vm_name, status="blocked", details={**base, "error": reason}
            )
            raise HTTPException(status_code=code, detail=message)

        if not script.strip():
            await _refuse(400, "empty_script", "The command cannot be empty.")
        if len(script) > MAX_SCRIPT_CHARS:
            await _refuse(400, "script_too_long", f"Scripts are limited to {MAX_SCRIPT_CHARS:,} characters.")
        lowered = script.lower()
        if any(fragment in lowered for fragment in BLOCKED_COMMAND_FRAGMENTS):
            await _refuse(403, "blocked_by_safety_list", "Command blocked for safety.")

        tier = await self.subscription_tier(subscription_id)
        base["tier"] = tier
        if tier == "prod" and (confirm_name or "").strip().lower() != vm_name.lower():
            await _refuse(
                422, "production_not_confirmed", f"'{vm_name}' is a production VM — type its name to confirm the run."
            )

        compute = self._compute(subscription_id)
        try:
            vm = await asyncio.to_thread(compute.virtual_machines.get, resource_group, vm_name, expand="instanceView")
        except Exception as exc:
            await _refuse(404, "vm_not_found", f"VM '{vm_name}' could not be read: {str(exc)[:200]}")
        power = next(
            (
                s.code.replace("PowerState/", "")
                for s in (vm.instance_view.statuses if vm.instance_view else []) or []
                if s.code and s.code.startswith("PowerState/")
            ),
            None,
        )
        if power != "running":
            await _refuse(409, "vm_not_running", f"VM '{vm_name}' is {power or 'not running'} — start it first.")
        os_type = str(vm.storage_profile.os_disk.os_type) if vm.storage_profile and vm.storage_profile.os_disk else ""
        shell = "PowerShell" if "windows" in os_type.lower() else "bash"

        from azure.mgmt.compute.models import VirtualMachineRunCommand, VirtualMachineRunCommandScriptSource

        run_name = f"{RUN_COMMAND_PREFIX}{datetime.utcnow():%Y%m%d%H%M%S}-{secrets.token_hex(3)}"
        command = VirtualMachineRunCommand(
            location=vm.location,
            source=VirtualMachineRunCommandScriptSource(script=script),
            async_execution=True,
            timeout_in_seconds=timeout_seconds,
            treat_failure_as_deployment_failure=False,
            tags={"created-by": "opsportal", "requested-by": user.email or user.user_id},
        )
        details = {**base, "run_id": run_name, "shell": shell, "timeout_seconds": timeout_seconds}
        try:
            # begin_* sends the PUT and returns a poller; async_execution means the
            # script keeps running in Azure after this returns.
            await asyncio.to_thread(
                compute.virtual_machine_run_commands.begin_create_or_update, resource_group, vm_name, run_name, command
            )
        except Exception as exc:
            await self._write_audit(
                user=user, ip=ip, vm_name=vm_name, status="failure", details={**details, "error": str(exc)[:500]}
            )
            raise HTTPException(status_code=502, detail=f"Azure refused the run command: {str(exc)[:300]}")

        await self._write_audit(
            user=user, ip=ip, vm_name=vm_name, status="running", details={**details, "state": "Pending"}
        )
        logger.info("vm_run_command_started", vm=vm_name, run_id=run_name, user=user.email)
        return {"run_id": run_name, "state": "Pending", "shell": shell, "tier": tier}

    async def _run_audit_row(self, vm_name: str, run_id: str) -> AuditLog | None:
        if self.db is None:
            return None
        rows = (
            (
                await self.db.execute(
                    select(AuditLog)
                    .where(AuditLog.action == RUN_COMMAND_ACTION, AuditLog.resource_id == vm_name)
                    .order_by(desc(AuditLog.id))
                    .limit(100)
                )
            )
            .scalars()
            .all()
        )
        return next((r for r in rows if (r.details or {}).get("run_id") == run_id), None)

    async def get_run_command(self, *, subscription_id: str, resource_group: str, vm_name: str, run_id: str) -> dict:
        """State and output of a run. Finished runs are recorded on their audit row and removed from Azure."""
        if not run_id.startswith(RUN_COMMAND_PREFIX):
            raise HTTPException(status_code=404, detail="Unknown run")
        audit = await self._run_audit_row(vm_name, run_id)
        stored = (audit.details or {}) if audit else {}
        if stored.get("state") in TERMINAL_STATES:
            return self._run_payload(run_id, stored)

        compute = self._compute(subscription_id)
        try:
            command = await asyncio.to_thread(
                compute.virtual_machine_run_commands.get_by_virtual_machine,
                resource_group,
                vm_name,
                run_id,
                expand="instanceView",
            )
        except Exception as exc:
            if audit is None:
                raise HTTPException(status_code=404, detail="Unknown run")
            raise HTTPException(status_code=502, detail=f"Could not read the run from Azure: {str(exc)[:300]}")

        view = command.instance_view
        state = str(view.execution_state) if view and view.execution_state else "Pending"
        state = state.split(".")[-1]  # enum repr on some SDK versions
        if command.provisioning_state == "Failed" and state in ("Pending", "Unknown"):
            state = "Failed"
        result = {
            "state": state,
            "exit_code": view.exit_code if view else None,
            "output": ((view.output or "") if view else "")[-MAX_STORED_OUTPUT:],
            "error": ((view.error or "") if view else "")[-MAX_STORED_OUTPUT:],
            "message": (view.execution_message if view else None) or None,
            "started_at": view.start_time.isoformat() if view and view.start_time else None,
            "finished_at": view.end_time.isoformat() if view and view.end_time else None,
        }
        if state in TERMINAL_STATES and audit is not None:
            audit.details = {**stored, **result}
            audit.status = "success" if state == "Succeeded" and (result["exit_code"] in (0, None)) else "failure"
            await self.db.commit()
            try:
                # Fire-and-forget: the output now lives on the audit row.
                await asyncio.to_thread(
                    compute.virtual_machine_run_commands.begin_delete, resource_group, vm_name, run_id
                )
            except Exception as exc:
                logger.info("run_command_cleanup_failed", run_id=run_id, error=str(exc)[:200])
        return self._run_payload(run_id, {**stored, **result})

    @staticmethod
    def _run_payload(run_id: str, data: dict[str, Any]) -> dict[str, Any]:
        keys = (
            "state",
            "exit_code",
            "output",
            "error",
            "message",
            "started_at",
            "finished_at",
            "shell",
            "script",
            "tier",
        )
        return {"run_id": run_id, **{k: data.get(k) for k in keys}}

    async def run_command_history(self, *, subscription_id: str, vm_name: str, limit: int = 50) -> list[dict]:
        if self.db is None:
            return []
        rows = (
            (
                await self.db.execute(
                    select(AuditLog)
                    .where(AuditLog.action == RUN_COMMAND_ACTION, AuditLog.resource_id == vm_name)
                    .order_by(desc(AuditLog.id))
                    .limit(limit * 2)
                )
            )
            .scalars()
            .all()
        )
        history = []
        for row in rows:
            details = row.details or {}
            if (details.get("subscription_id") or "").lower() != subscription_id.lower():
                continue
            history.append(
                {
                    "id": row.id,
                    "run_id": details.get("run_id"),
                    "requested_at": row.timestamp.isoformat() if row.timestamp else None,
                    "requested_by": row.user_email or row.user_id,
                    "status": row.status,
                    "state": details.get("state"),
                    "exit_code": details.get("exit_code"),
                    "script": details.get("script"),
                    "output": details.get("output"),
                    "error": details.get("error"),
                    "started_at": details.get("started_at"),
                    "finished_at": details.get("finished_at"),
                }
            )
        return history[:limit]

    # ── VM administration ──────────────────────────────────────────────

    async def available_sizes(self, subscription_id: str, resource_group: str, vm_name: str) -> list[dict]:
        compute = self._compute(subscription_id)
        try:
            sizes = await asyncio.to_thread(
                lambda: list(compute.virtual_machines.list_available_sizes(resource_group, vm_name))
            )
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"Could not list sizes: {str(exc)[:300]}")
        return sorted(
            (
                {
                    "name": s.name,
                    "cores": s.number_of_cores,
                    "memory_gb": round((s.memory_in_mb or 0) / 1024, 1),
                    "max_data_disks": s.max_data_disk_count,
                }
                for s in sizes
            ),
            key=lambda s: (s["cores"] or 0, s["memory_gb"], s["name"]),
        )

    async def resize_vm(self, subscription_id: str, resource_group: str, vm_name: str, size: str) -> dict:
        from azure.mgmt.compute.models import HardwareProfile, VirtualMachineUpdate

        allowed = {s["name"] for s in await self.available_sizes(subscription_id, resource_group, vm_name)}
        if size not in allowed:
            raise HTTPException(status_code=422, detail=f"'{size}' is not available for this VM in its region/cluster.")
        compute = self._compute(subscription_id)
        await asyncio.to_thread(
            compute.virtual_machines.begin_update,
            resource_group,
            vm_name,
            VirtualMachineUpdate(hardware_profile=HardwareProfile(vm_size=size)),
        )
        await self._patch_inventory("virtual_machine", subscription_id, resource_group, vm_name, vm_size=size)
        return {"status": "accepted", "action": "resize", "vm_name": vm_name, "size": size}

    async def redeploy_vm(self, subscription_id: str, resource_group: str, vm_name: str) -> dict:
        compute = self._compute(subscription_id)
        await asyncio.to_thread(compute.virtual_machines.begin_redeploy, resource_group, vm_name)
        await self._patch_inventory(
            "virtual_machine", subscription_id, resource_group, vm_name, power_state="redeploying"
        )
        return {"status": "accepted", "action": "redeploy", "vm_name": vm_name}

    async def boot_diagnostics(
        self, subscription_id: str, resource_group: str, vm_name: str, max_bytes: int = 256_000
    ) -> dict:
        """Tail of the serial console log (fetched server-side so the SAS URL never reaches the browser)."""
        compute = self._compute(subscription_id)
        try:
            data = await asyncio.to_thread(
                compute.virtual_machines.retrieve_boot_diagnostics_data,
                resource_group,
                vm_name,
                sas_uri_expiration_time_in_minutes=5,
            )
        except Exception as exc:
            raise HTTPException(
                status_code=409,
                detail=f"Boot diagnostics are not available for '{vm_name}' (is it enabled?): {str(exc)[:200]}",
            )
        uri = data.serial_console_log_blob_uri
        if not uri:
            return {"available": False, "log": "", "truncated": False}
        async with httpx.AsyncClient(timeout=30) as client:
            head = await client.head(uri)
            size = int(head.headers.get("content-length") or 0)
            headers = {"x-ms-range": f"bytes={max(0, size - max_bytes)}-{max(size - 1, 0)}"} if size > max_bytes else {}
            response = await client.get(uri, headers=headers)
            response.raise_for_status()
        return {"available": True, "log": response.text, "truncated": size > max_bytes, "size_bytes": size}

    # ── Tags ───────────────────────────────────────────────────────────

    @staticmethod
    def validate_tags(tags: dict[str, str]) -> dict[str, str]:
        if len(tags) > 50:
            raise HTTPException(status_code=422, detail="Azure allows at most 50 tags per resource.")
        clean: dict[str, str] = {}
        for raw_key, raw_value in tags.items():
            key, value = (raw_key or "").strip(), ("" if raw_value is None else str(raw_value)).strip()
            if not key:
                raise HTTPException(status_code=422, detail="Tag names cannot be empty.")
            if len(key) > 512 or len(value) > 256:
                raise HTTPException(
                    status_code=422, detail=f"Tag '{key[:40]}' is too long (name 512, value 256 characters)."
                )
            if _TAG_KEY_INVALID.search(key):
                raise HTTPException(status_code=422, detail=f"Tag name '{key}' cannot contain < > % & \\ ? /")
            clean[key] = value
        return clean

    async def replace_tags(self, resource_id: str, resource_type: str, tags: dict[str, str]) -> dict:
        """Set a resource's tags to exactly ``tags``."""
        from azure.mgmt.resource.resources.models import Tags, TagsPatchResource

        tags = self.validate_tags(tags)
        parts = resource_id.split("/")
        subscription_id, resource_group, name = parts[2], parts[4], parts[-1]
        client = self._resources(subscription_id)
        await asyncio.to_thread(
            lambda: client.tags.begin_update_at_scope(
                resource_id, TagsPatchResource(operation="Replace", properties=Tags(tags=tags))
            ).result()
        )
        await self._patch_inventory(resource_type, subscription_id, resource_group, name, tags=tags)
        return {"status": "updated", "tags": tags}

    # ── Disks ──────────────────────────────────────────────────────────

    async def snapshot_disk(self, subscription_id: str, resource_group: str, disk_name: str, requested_by: str) -> dict:
        from azure.mgmt.compute.models import CreationData, Snapshot

        compute = self._compute(subscription_id)
        disk = await asyncio.to_thread(compute.disks.get, resource_group, disk_name)
        snapshot_name = f"{disk_name[:60]}-snap-{datetime.utcnow():%Y%m%d%H%M%S}"
        await asyncio.to_thread(
            compute.snapshots.begin_create_or_update,
            resource_group,
            snapshot_name,
            Snapshot(
                location=disk.location,
                creation_data=CreationData(create_option="Copy", source_resource_id=disk.id),
                incremental=True,
                tags={"created-by": "opsportal", "source-disk": disk_name, "requested-by": requested_by},
            ),
        )
        return {
            "status": "accepted",
            "snapshot_name": snapshot_name,
            "resource_group": resource_group,
            "incremental": True,
        }

    async def expand_disk(self, subscription_id: str, resource_group: str, disk_name: str, size_gb: int) -> dict:
        from azure.mgmt.compute.models import DiskUpdate

        compute = self._compute(subscription_id)
        disk = await asyncio.to_thread(compute.disks.get, resource_group, disk_name)
        current = disk.disk_size_gb or 0
        if size_gb <= current:
            raise HTTPException(status_code=422, detail=f"Disks can only grow: '{disk_name}' is already {current} GB.")
        try:
            await asyncio.to_thread(
                lambda: compute.disks.begin_update(resource_group, disk_name, DiskUpdate(disk_size_gb=size_gb)).result()
            )
        except Exception as exc:
            raise HTTPException(status_code=409, detail=f"Azure could not resize the disk: {str(exc)[:300]}")
        await self._patch_inventory(
            "managed_disk", subscription_id, resource_group, disk_name, size_gb=size_gb, disk_size_gb=size_gb
        )
        return {"status": "resized", "disk_name": disk_name, "previous_gb": current, "size_gb": size_gb}

    # ── PG Flexible Server ─────────────────────────────────────────────

    async def pg_overview(self, subscription_id: str, resource_group: str, server_name: str) -> dict:
        """Databases and firewall rules of a PG Flexible Server (read only)."""
        client = self._pg(subscription_id)

        def _read() -> dict:
            databases = [
                {"name": d.name, "charset": d.charset, "collation": d.collation}
                for d in client.databases.list_by_server(resource_group, server_name)
            ]
            rules = [
                {"name": r.name, "start_ip": r.start_ip_address, "end_ip": r.end_ip_address}
                for r in client.firewall_rules.list_by_server(resource_group, server_name)
            ]
            return {
                "databases": sorted(databases, key=lambda d: d["name"]),
                "firewall_rules": sorted(rules, key=lambda r: r["name"]),
            }

        try:
            return await asyncio.to_thread(_read)
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"Could not read the server: {str(exc)[:300]}")
