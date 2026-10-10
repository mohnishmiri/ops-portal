"""
Infrastructure Alert Service — VM / PG Flexible Server thresholds and custom expiry alerts.

Alert lifecycle, the same for VM, PG and expiry alerts:

- A config has at most one *open* alert per metric (status ``active`` or
  ``acknowledged``). Every check updates that alert in place, so acknowledging
  silences it instead of a fresh copy being raised (and emailed) on the next run.
- A worse severity (warning -> critical, or an expiry date passing) re-opens an
  acknowledged alert and notifies again.
- A metric back under its warning threshold, or an expiry date moved out of the
  warning window (renewed), resolves the open alert automatically.
- An expiry alert resolved by a person stays resolved for that expiry date
  unless it gets worse.
"""

import asyncio
from datetime import UTC, date, datetime, timedelta
from typing import Any

import structlog
from azure.mgmt.compute import ComputeManagementClient
from azure.mgmt.monitor import MonitorManagementClient
from fastapi import HTTPException
from sqlalchemy import delete, desc, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.access_scope import assert_resource_access
from app.core.azure_auth import get_azure_credential
from app.core.cron import cron_trigger_from_crontab
from app.core.subscription_scope import get_scoped_subscription_ids
from app.models.database import (
    AlertScheduleConfig,
    CustomExpiryAlert,
    CustomExpiryAlertConfig,
    PGFlexServerAlert,
    PGFlexServerAlertConfig,
    StorageAlertConfig,
    VMThresholdAlert,
    VMThresholdAlertConfig,
)
from app.services.email_notification_service import EmailNotificationService

logger = structlog.get_logger(__name__)

OPEN_ALERT_STATUSES = ("active", "acknowledged")
SEVERITY_RANK = {"warning": 1, "critical": 2}
EXPIRY_ALERT_TYPES = ("mech_id", "certificate", "aaf_account", "database_account", "itservices_domain")
SYSTEM_ACTOR = "system"

# Azure Monitor platform metrics (verified against a live VM, Oct 2026). Memory
# used = 100 - "Available Memory Percentage"; disk = the busiest of the OS/data
# disk IOPS and bandwidth consumed percentages. Disk *space* is a guest metric
# that needs the Azure Monitor Agent, so it is not available here.
VM_CPU_METRIC = "Percentage CPU"
VM_MEMORY_METRIC = "Available Memory Percentage"
VM_DISK_METRICS = (
    "OS Disk IOPS Consumed Percentage",
    "OS Disk Bandwidth Consumed Percentage",
    "Data Disk IOPS Consumed Percentage",
    "Data Disk Bandwidth Consumed Percentage",
)
PG_METRICS = ("cpu_percent", "memory_percent", "storage_percent")
# Platform metrics land a few minutes late, and storage_percent only every few
# minutes, so the window is wide and the newest non-empty point is used.
VM_METRIC_WINDOW = timedelta(minutes=15)
PG_METRIC_WINDOW = timedelta(minutes=30)


def days_until_expiry(expiry_date: datetime, today: date | None = None) -> int:
    """Calendar days from today (UTC) to the expiry date: 0 = today, negative = expired.

    Subtracting datetimes floors partial days, so something expiring tomorrow
    used to read as 0 ("EXPIRED") for most of today.
    """
    return (expiry_date.date() - (today or datetime.utcnow().date())).days


def expiry_severity(days: int, warning_days: int, critical_days: int) -> str | None:
    if days <= critical_days:
        return "critical"
    if days <= warning_days:
        return "warning"
    return None


def threshold_severity(value: float | None, warning: float, critical: float) -> tuple[str | None, float | None]:
    if value is None:
        return None, None
    if value >= critical:
        return "critical", critical
    if value >= warning:
        return "warning", warning
    return None, None


def _latest_average(metric: Any) -> tuple[float | None, datetime | None]:
    """Newest non-empty average across a metric's time series."""
    latest: float | None = None
    stamp: datetime | None = None
    for series in metric.timeseries or []:
        for point in series.data or []:
            if point.average is not None and (stamp is None or point.time_stamp >= stamp):
                latest, stamp = point.average, point.time_stamp
    return latest, stamp


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _naive_utc(value: datetime) -> datetime:
    """The DateTime columns are naive UTC; a browser sends aware ISO strings."""
    return value.astimezone(UTC).replace(tzinfo=None) if value.tzinfo else value


def _apply_updates(row: Any, updates: dict[str, Any], allowed: set[str]) -> None:
    """Copy allowed fields onto a row; ``clear_snooze`` removes an existing snooze."""
    for key, value in updates.items():
        if key in allowed:
            setattr(row, key, _naive_utc(value) if isinstance(value, datetime) else value)
    if updates.get("clear_snooze"):
        row.snooze_until = None


def _conflict(detail: str) -> HTTPException:
    return HTTPException(status_code=409, detail=detail)


def _not_found(what: str) -> HTTPException:
    return HTTPException(status_code=404, detail=f"{what} not found")


def _validate_pairs(pairs: list[tuple[str, float | None, float | None]]) -> None:
    """Warning must sit below critical, or the warning level can never be reached."""
    for label, warning, critical in pairs:
        if warning is not None and critical is not None and warning >= critical:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"{label}: the warning threshold ({warning:g}) must be lower than "
                    f"the critical threshold ({critical:g})."
                ),
            )


class InfraAlertService:
    """VM / PG threshold alerts, custom expiry alerts, and the schedules that check them."""

    def __init__(self, db_session: AsyncSession | None):
        self.db = db_session
        self.credential = get_azure_credential()
        self._compute_clients: dict[str, ComputeManagementClient] = {}
        self._monitor_clients: dict[str, MonitorManagementClient] = {}

    # ── DB helpers ─────────────────────────────────────────────────────

    def _require_db(self) -> AsyncSession:
        if self.db is None:
            raise HTTPException(status_code=503, detail="Database unavailable")
        return self.db

    async def _save_new(self, record: Any, conflict_detail: str) -> None:
        """Insert a row; a unique-key clash is a 409 rather than a silent no-op."""
        db = self._require_db()
        db.add(record)
        try:
            await db.commit()
        except IntegrityError:
            await db.rollback()
            raise _conflict(conflict_detail)

    async def _db_commit(self) -> bool:
        """Commit current transaction. Returns False if DB is unavailable."""
        if self.db is None:
            return False
        try:
            await self.db.commit()
            return True
        except Exception as e:
            logger.error("db_commit_failed", error=str(e))
            await self.db.rollback()
            return False

    async def _get(self, model: Any, row_id: int, what: str) -> Any:
        row = (await self._require_db().execute(select(model).where(model.id == row_id))).scalar_one_or_none()
        if row is None:
            raise _not_found(what)
        return row

    def _get_compute_client(self, subscription_id: str) -> ComputeManagementClient:
        """Get or create cached Compute client for subscription."""
        if subscription_id not in self._compute_clients:
            self._compute_clients[subscription_id] = ComputeManagementClient(self.credential, subscription_id)
        return self._compute_clients[subscription_id]

    def _get_monitor_client(self, subscription_id: str) -> MonitorManagementClient:
        """Get or create cached Monitor client for subscription."""
        if subscription_id not in self._monitor_clients:
            self._monitor_clients[subscription_id] = MonitorManagementClient(self.credential, subscription_id)
        return self._monitor_clients[subscription_id]

    async def _resolve_scoped_subscription_ids(
        self,
        subscription_id: str | None = None,
    ) -> list[str]:
        monitored_subscription_ids = await get_scoped_subscription_ids()
        if subscription_id is None:
            return monitored_subscription_ids

        monitored_set = set(monitored_subscription_ids)
        return [subscription_id] if subscription_id in monitored_set else []

    async def _assert_row_writable(self, config_model, *, config_id=None, alert_model=None, alert_id=None) -> None:
        """403 unless the caller may change the subscription a config (or an
        alert's config) belongs to.  These routes address rows by database ID,
        so the request itself names no subscription to check."""
        stmt = select(config_model.subscription_id)
        if alert_model is not None:
            stmt = stmt.join(alert_model, alert_model.config_id == config_model.id).where(alert_model.id == alert_id)
        else:
            stmt = stmt.where(config_model.id == config_id)
        subscription_id = (await self.db.execute(stmt)).scalar_one_or_none()
        if subscription_id is not None:
            context = f"{(alert_model or config_model).__tablename__} {alert_id or config_id}"
            assert_resource_access(subscription_id, "write", context=context)

    async def _delete_config_with_alerts(
        self, config_model: Any, alert_model: Any | None, config_id: int, what: str
    ) -> dict:
        """Delete a config and its alert history (alerts reference it with a NOT NULL key)."""
        db = self._require_db()
        if (await db.execute(select(config_model.id).where(config_model.id == config_id))).scalar_one_or_none() is None:
            raise _not_found(what)
        removed = 0
        if alert_model is not None:
            removed = (await db.execute(delete(alert_model).where(alert_model.config_id == config_id))).rowcount or 0
        await db.execute(delete(config_model).where(config_model.id == config_id))
        await db.commit()
        return {"id": config_id, "status": "deleted", "alerts_removed": removed}

    # ── Shared alert lifecycle ─────────────────────────────────────────

    async def _open_alerts(self, alert_model: Any, config_id: int, metric_type: str | None = None) -> list[Any]:
        """Open alerts for a config, newest first."""
        stmt = select(alert_model).where(
            alert_model.config_id == config_id,
            alert_model.status.in_(OPEN_ALERT_STATUSES),
        )
        if metric_type is not None:
            stmt = stmt.where(alert_model.metric_type == metric_type)
        stmt = stmt.order_by(desc(alert_model.created_at), desc(alert_model.id))
        return list((await self.db.execute(stmt)).scalars().all())

    @staticmethod
    def _close(alert: Any, now: datetime, note: str, by: str = SYSTEM_ACTOR) -> None:
        alert.status = "resolved"
        alert.resolved_at = now
        alert.resolved_by = by
        alert.resolution_notes = note
        alert.updated_at = now

    async def _close_open_alerts(self, alert_model: Any, config_id: int, now: datetime, note: str) -> int:
        alerts = await self._open_alerts(alert_model, config_id)
        for alert in alerts:
            self._close(alert, now, note)
        return len(alerts)

    async def _apply_threshold_reading(
        self,
        *,
        alert_model: Any,
        config: Any,
        metric_type: str,
        value: float | None,
        warning: float,
        critical: float,
        new_alert_fields: dict[str, Any],
        now: datetime,
    ) -> list[tuple[str, Any]]:
        """Fold one metric reading into the config's open alert for that metric.

        Returns ``(event, alert)`` pairs worth notifying about: ``created``,
        ``escalated`` (worse severity) or ``resolved`` (back under warning).
        """
        if value is None:
            return []  # no data (e.g. a deallocated VM) — leave things as they are
        open_alerts = await self._open_alerts(alert_model, config.id, metric_type)
        severity, threshold = threshold_severity(value, warning, critical)
        label = metric_type.upper()

        if severity is None:
            for alert in open_alerts:
                alert.current_value = value
                self._close(
                    alert, now, f"Auto-resolved: {label} at {value:.1f}% is below the {warning:g}% warning threshold."
                )
            return [("resolved", alert) for alert in open_alerts]

        if not open_alerts:
            alert = alert_model(
                config_id=config.id,
                metric_type=metric_type,
                current_value=value,
                threshold_value=threshold,
                severity=severity,
                status="active",
                created_at=now,
                updated_at=now,
                **new_alert_fields,
            )
            self.db.add(alert)
            return [("created", alert)]

        primary, duplicates = open_alerts[0], open_alerts[1:]
        for duplicate in duplicates:
            self._close(duplicate, now, f"Closed automatically: duplicate of alert #{primary.id}.")
        escalated = SEVERITY_RANK[severity] > SEVERITY_RANK.get(primary.severity, 0)
        primary.current_value = value
        primary.threshold_value = threshold
        primary.severity = severity
        primary.updated_at = now
        if escalated:
            primary.status = "active"
            return [("escalated", primary)]
        return []

    # =========================================================================
    # A. VM THRESHOLD ALERT CONFIGURATION
    # =========================================================================

    async def list_vm_threshold_configs(
        self,
        subscription_id: str | None = None,
        is_enabled: bool | None = None,
    ) -> list[dict[str, Any]]:
        """List all VM threshold alert configurations."""
        if self.db is None:
            return []

        scoped_subscription_ids = await self._resolve_scoped_subscription_ids(subscription_id)

        query = select(VMThresholdAlertConfig).where(
            VMThresholdAlertConfig.subscription_id.in_(scoped_subscription_ids)
        )
        if is_enabled is not None:
            query = query.where(VMThresholdAlertConfig.is_enabled == is_enabled)

        query = query.order_by(desc(VMThresholdAlertConfig.created_at))
        result = await self.db.execute(query)
        configs = result.scalars().all()

        return [
            {
                "id": c.id,
                "subscription_id": c.subscription_id,
                "resource_group": c.resource_group,
                "vm_name": c.vm_name,
                "vm_id": c.vm_id,
                "cpu_warning_threshold": c.cpu_warning_threshold,
                "cpu_critical_threshold": c.cpu_critical_threshold,
                "memory_warning_threshold": c.memory_warning_threshold,
                "memory_critical_threshold": c.memory_critical_threshold,
                "disk_warning_threshold": c.disk_warning_threshold,
                "disk_critical_threshold": c.disk_critical_threshold,
                "is_enabled": c.is_enabled,
                "notification_emails": c.notification_emails or [],
                "snooze_until": _iso(c.snooze_until),
                "created_at": c.created_at.isoformat(),
                "updated_at": _iso(c.updated_at),
                "created_by": c.created_by,
            }
            for c in configs
        ]

    async def create_vm_threshold_config(
        self,
        subscription_id: str,
        resource_group: str,
        vm_name: str,
        vm_id: str,
        created_by: str,
        cpu_warning: float = 70.0,
        cpu_critical: float = 90.0,
        memory_warning: float = 75.0,
        memory_critical: float = 90.0,
        disk_warning: float = 80.0,
        disk_critical: float = 95.0,
        notification_emails: list[str] | None = None,
        is_enabled: bool = True,
    ) -> dict[str, Any]:
        """Create a new VM threshold alert configuration."""
        assert_resource_access(subscription_id, "write", context=f"vm threshold config {vm_name}")
        _validate_pairs(
            [
                ("CPU", cpu_warning, cpu_critical),
                ("Memory", memory_warning, memory_critical),
                ("Disk", disk_warning, disk_critical),
            ]
        )
        config = VMThresholdAlertConfig(
            subscription_id=subscription_id,
            resource_group=resource_group,
            vm_name=vm_name,
            vm_id=vm_id,
            created_by=created_by,
            cpu_warning_threshold=cpu_warning,
            cpu_critical_threshold=cpu_critical,
            memory_warning_threshold=memory_warning,
            memory_critical_threshold=memory_critical,
            disk_warning_threshold=disk_warning,
            disk_critical_threshold=disk_critical,
            notification_emails=notification_emails or [],
            is_enabled=is_enabled,
        )

        await self._save_new(
            config, f"VM '{vm_name}' already has a threshold configuration — edit the existing one instead."
        )
        logger.info("vm_threshold_config_created", vm_id=vm_id, created_by=created_by)

        return {
            "id": config.id,
            "vm_id": vm_id,
            "vm_name": vm_name,
            "status": "created",
        }

    async def update_vm_threshold_config(
        self,
        config_id: int,
        **updates,
    ) -> dict[str, Any]:
        """Update a VM threshold alert configuration."""
        self._require_db()
        await self._assert_row_writable(VMThresholdAlertConfig, config_id=config_id)
        config = await self._get(VMThresholdAlertConfig, config_id, "VM threshold configuration")

        allowed_fields = {
            "cpu_warning_threshold",
            "cpu_critical_threshold",
            "memory_warning_threshold",
            "memory_critical_threshold",
            "disk_warning_threshold",
            "disk_critical_threshold",
            "is_enabled",
            "notification_emails",
            "snooze_until",
        }
        _apply_updates(config, updates, allowed_fields)
        _validate_pairs(
            [
                ("CPU", config.cpu_warning_threshold, config.cpu_critical_threshold),
                ("Memory", config.memory_warning_threshold, config.memory_critical_threshold),
                ("Disk", config.disk_warning_threshold, config.disk_critical_threshold),
            ]
        )
        if not config.is_enabled:
            await self._close_open_alerts(
                VMThresholdAlert,
                config_id,
                datetime.utcnow(),
                "Closed automatically: monitoring for this VM was disabled.",
            )

        await self.db.commit()
        logger.info("vm_threshold_config_updated", config_id=config_id)
        return {"id": config_id, "status": "updated"}

    async def delete_vm_threshold_config(self, config_id: int) -> dict[str, Any]:
        """Delete a VM threshold alert configuration and its alert history."""
        self._require_db()
        await self._assert_row_writable(VMThresholdAlertConfig, config_id=config_id)
        result = await self._delete_config_with_alerts(
            VMThresholdAlertConfig, VMThresholdAlert, config_id, "VM threshold configuration"
        )
        logger.info("vm_threshold_config_deleted", config_id=config_id)
        return result

    # =========================================================================
    # B. VM THRESHOLD ALERTS
    # =========================================================================

    async def list_vm_threshold_alerts(
        self,
        status: str | None = None,
        severity: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """List VM threshold alerts."""
        if self.db is None:
            return []

        scoped_subscription_ids = await self._resolve_scoped_subscription_ids()

        query = (
            select(VMThresholdAlert)
            .join(
                VMThresholdAlertConfig,
                VMThresholdAlert.config_id == VMThresholdAlertConfig.id,
            )
            .where(VMThresholdAlertConfig.subscription_id.in_(scoped_subscription_ids))
        )
        if status:
            query = query.where(VMThresholdAlert.status == status)
        if severity:
            query = query.where(VMThresholdAlert.severity == severity)

        query = query.order_by(desc(VMThresholdAlert.created_at)).limit(limit)
        result = await self.db.execute(query)
        alerts = result.scalars().all()

        return [
            {
                "id": a.id,
                "config_id": a.config_id,
                "vm_id": a.vm_id,
                "vm_name": a.vm_name,
                "metric_type": a.metric_type,
                "current_value": a.current_value,
                "threshold_value": a.threshold_value,
                "severity": a.severity,
                "status": a.status,
                "created_at": a.created_at.isoformat(),
                "updated_at": _iso(a.updated_at),
                "acknowledged_by": a.acknowledged_by,
                "acknowledged_at": _iso(a.acknowledged_at),
                "resolved_at": _iso(a.resolved_at),
                "resolved_by": a.resolved_by,
                "resolution_notes": a.resolution_notes,
            }
            for a in alerts
        ]

    async def _acknowledge(self, alert: Any, acknowledged_by: str) -> bool:
        """Mark an alert acknowledged; False when nothing changed."""
        if alert.status == "resolved":
            raise _conflict("This alert is already resolved.")
        if alert.status == "acknowledged":
            return False
        alert.status = "acknowledged"
        alert.acknowledged_by = acknowledged_by
        alert.acknowledged_at = datetime.utcnow()
        await self.db.commit()
        return True

    async def _resolve(self, alert: Any, resolved_by: str | None, resolution_notes: str | None) -> bool:
        """Resolve an alert by hand; False when it already was."""
        if alert.status == "resolved":
            return False
        self._close(alert, datetime.utcnow(), resolution_notes or "", by=resolved_by or SYSTEM_ACTOR)
        alert.resolution_notes = resolution_notes
        await self.db.commit()
        return True

    async def _notify_status_change(
        self,
        config_model: Any,
        alert: Any,
        *,
        alert_type: str,
        resource_name: str,
        action: str,
        action_by: str,
        extra: dict[str, Any],
    ) -> None:
        try:
            config = (
                await self.db.execute(select(config_model).where(config_model.id == alert.config_id))
            ).scalar_one_or_none()
            emails = (config.notification_emails or []) if config else []
            if emails:
                await EmailNotificationService(self.db).send_alert_status_change(
                    recipient_emails=emails,
                    alert_type=alert_type,
                    resource_name=resource_name,
                    action=action,
                    action_by=action_by,
                    alert_id=alert.id,
                    extra_details=extra,
                )
        except Exception as exc:
            logger.warning("alert_status_email_failed", alert_id=alert.id, action=action, error=str(exc)[:200])

    async def acknowledge_vm_alert(
        self,
        alert_id: int,
        acknowledged_by: str,
    ) -> dict[str, Any]:
        """Acknowledge a VM threshold alert."""
        self._require_db()
        await self._assert_row_writable(VMThresholdAlertConfig, alert_model=VMThresholdAlert, alert_id=alert_id)
        alert = await self._get(VMThresholdAlert, alert_id, "Alert")
        if await self._acknowledge(alert, acknowledged_by):
            logger.info("vm_alert_acknowledged", alert_id=alert_id, by=acknowledged_by)
            await self._notify_status_change(
                VMThresholdAlertConfig,
                alert,
                alert_type="vm_threshold",
                resource_name=alert.vm_name,
                action="acknowledged",
                action_by=acknowledged_by,
                extra={"Metric": alert.metric_type.upper(), "Severity": alert.severity},
            )
        return {"id": alert_id, "status": "acknowledged"}

    async def resolve_vm_alert(
        self,
        alert_id: int,
        resolution_notes: str | None = None,
        resolved_by: str | None = None,
    ) -> dict[str, Any]:
        """Resolve a VM threshold alert."""
        self._require_db()
        await self._assert_row_writable(VMThresholdAlertConfig, alert_model=VMThresholdAlert, alert_id=alert_id)
        alert = await self._get(VMThresholdAlert, alert_id, "Alert")
        if await self._resolve(alert, resolved_by, resolution_notes):
            logger.info("vm_alert_resolved", alert_id=alert_id)
            extra = {"Metric": alert.metric_type.upper(), "Severity": alert.severity}
            if resolution_notes:
                extra["Resolution Notes"] = resolution_notes
            await self._notify_status_change(
                VMThresholdAlertConfig,
                alert,
                alert_type="vm_threshold",
                resource_name=alert.vm_name,
                action="resolved",
                action_by=resolved_by or SYSTEM_ACTOR,
                extra=extra,
            )
        return {"id": alert_id, "status": "resolved"}

    def _read_metrics(
        self,
        subscription_id: str,
        resource_id: str,
        metric_names: list[str],
        window: timedelta,
    ) -> dict[str, tuple[float | None, datetime | None]]:
        """Blocking Azure Monitor read — run it in a thread."""
        end = datetime.utcnow()
        start = end - window
        response = self._get_monitor_client(subscription_id).metrics.list(
            resource_id,
            timespan=f"{start:%Y-%m-%dT%H:%M:%S}Z/{end:%Y-%m-%dT%H:%M:%S}Z",
            interval="PT1M",
            metricnames=",".join(metric_names),
            aggregation="Average",
        )
        return {item.name.value: _latest_average(item) for item in response.value}

    async def get_vm_metrics(
        self,
        subscription_id: str,
        resource_group: str,
        vm_name: str,
    ) -> dict[str, Any]:
        """Current CPU, memory-used and disk-I/O percentages for a VM from Azure Monitor."""
        resource_id = (
            f"/subscriptions/{subscription_id}"
            f"/resourceGroups/{resource_group}"
            f"/providers/Microsoft.Compute/virtualMachines/{vm_name}"
        )
        names = [VM_CPU_METRIC, VM_MEMORY_METRIC, *VM_DISK_METRICS]
        try:
            try:
                readings = await asyncio.to_thread(
                    self._read_metrics, subscription_id, resource_id, names, VM_METRIC_WINDOW
                )
            except Exception as first_error:
                # One unknown metric name fails the whole request, and older VMs
                # do not publish the memory percentage — retry without it.
                logger.info("vm_metrics_retry_without_memory", vm=vm_name, error=str(first_error)[:200])
                readings = await asyncio.to_thread(
                    self._read_metrics,
                    subscription_id,
                    resource_id,
                    [VM_CPU_METRIC, *VM_DISK_METRICS],
                    VM_METRIC_WINDOW,
                )
        except Exception as e:
            logger.error("vm_metrics_fetch_failed", vm=vm_name, error=str(e)[:300])
            return {"error": str(e)[:300]}

        def _value(name: str) -> float | None:
            return readings.get(name, (None, None))[0]

        cpu = _value(VM_CPU_METRIC)
        available_memory = _value(VM_MEMORY_METRIC)
        disk_values = [v for v in (_value(name) for name in VM_DISK_METRICS) if v is not None]
        stamps = [stamp for _value_, stamp in readings.values() if stamp is not None]
        return {
            "cpu": round(cpu, 2) if cpu is not None else None,
            "memory": round(100 - available_memory, 2) if available_memory is not None else None,
            "disk": round(max(disk_values), 2) if disk_values else None,
            "collected_at": _iso(max(stamps)) if stamps else None,
            "metrics": {name: (round(v, 2) if v is not None else None) for name, (v, _stamp) in readings.items()},
        }

    async def check_and_generate_vm_alerts(self) -> dict[str, Any]:
        """Read every enabled VM config's metrics and update its alerts."""
        if self.db is None:
            return {"error": "Database unavailable"}

        scoped = await self._resolve_scoped_subscription_ids()
        configs = (
            (
                await self.db.execute(
                    select(VMThresholdAlertConfig).where(
                        VMThresholdAlertConfig.is_enabled.is_(True),
                        VMThresholdAlertConfig.subscription_id.in_(scoped),
                    )
                )
            )
            .scalars()
            .all()
        )
        now = datetime.utcnow()
        summary: dict[str, Any] = {
            "checked": 0,
            "created": 0,
            "escalated": 0,
            "resolved": 0,
            "snoozed": 0,
            "errors": [],
        }
        events: list[tuple[str, Any, Any]] = []

        for config in configs:
            if config.snooze_until and config.snooze_until > now:
                summary["snoozed"] += 1
                continue
            metrics = await self.get_vm_metrics(config.subscription_id, config.resource_group, config.vm_name)
            if "error" in metrics:
                summary["errors"].append(f"{config.vm_name}: {metrics['error']}")
                continue
            summary["checked"] += 1
            for metric_type, warning, critical in (
                ("cpu", config.cpu_warning_threshold, config.cpu_critical_threshold),
                ("memory", config.memory_warning_threshold, config.memory_critical_threshold),
                ("disk", config.disk_warning_threshold, config.disk_critical_threshold),
            ):
                for event, alert in await self._apply_threshold_reading(
                    alert_model=VMThresholdAlert,
                    config=config,
                    metric_type=metric_type,
                    value=metrics.get(metric_type),
                    warning=warning,
                    critical=critical,
                    new_alert_fields={"vm_id": config.vm_id, "vm_name": config.vm_name},
                    now=now,
                ):
                    summary[event] += 1
                    events.append((event, alert, config))

        await self.db.commit()
        await self._notify_threshold_events(events, kind="VM")
        counts = {k: v for k, v in summary.items() if k != "errors"}
        logger.info("vm_alerts_checked", **counts, errors=len(summary["errors"]))
        return summary

    async def _notify_threshold_events(self, events: list[tuple[str, Any, Any]], *, kind: str) -> None:
        """Email a config's recipients about new, escalated and recovered alerts."""
        if not events:
            return
        email = EmailNotificationService(self.db)
        is_pg = kind == "PG"
        notification_type = "pg_flex_server" if is_pg else "vm_threshold"
        for event, alert, config in events:
            recipients = config.notification_emails or []
            if not recipients:
                continue
            resource_name = config.server_name if is_pg else config.vm_name
            try:
                if event in ("created", "escalated"):
                    await email.send_vm_threshold_alert(
                        recipient_emails=recipients,
                        vm_name=resource_name,
                        resource_group=config.resource_group,
                        subscription_id=config.subscription_id,
                        metric_type=alert.metric_type,
                        current_value=round(alert.current_value, 1),
                        threshold_value=alert.threshold_value,
                        severity=alert.severity,
                        alert_id=alert.id,
                        resource_kind="PostgreSQL Flexible Server" if is_pg else "VM",
                        notification_type=notification_type,
                        link_prefix="pg" if is_pg else "vm",
                    )
                elif event == "resolved":
                    await email.send_alert_status_change(
                        recipient_emails=recipients,
                        alert_type=notification_type,
                        resource_name=resource_name,
                        action="resolved",
                        action_by="system (auto-resolved)",
                        alert_id=alert.id,
                        extra_details={"Metric": alert.metric_type.upper(), "Reason": alert.resolution_notes},
                    )
            except Exception as exc:
                logger.warning("threshold_alert_email_failed", alert_id=alert.id, event=event, error=str(exc)[:200])

    async def list_vms(self, subscription_id: str) -> list[dict[str, Any]]:
        """List all VMs in a subscription."""
        assert_resource_access(subscription_id, "read", context="vm list")
        try:
            compute_client = self._get_compute_client(subscription_id)

            def _list() -> list[dict[str, Any]]:
                return [
                    {
                        "id": vm.id,
                        "name": vm.name,
                        "location": vm.location,
                        "resource_group": (
                            vm.id.split("/resourceGroups/")[1].split("/")[0] if "/resourceGroups/" in vm.id else None
                        ),
                        "vm_size": (vm.hardware_profile.vm_size if vm.hardware_profile else None),
                        "power_state": next(
                            (
                                s.code.replace("PowerState/", "")
                                for s in (vm.instance_view.statuses if vm.instance_view else [])
                                if s.code and s.code.startswith("PowerState/")
                            ),
                            "Unknown",
                        ),
                    }
                    for vm in compute_client.virtual_machines.list_all(expand="instanceView")
                ]

            return await asyncio.to_thread(_list)
        except Exception as e:
            logger.error("vm_list_failed", error=str(e))
            return []

    # =========================================================================
    # C. CUSTOM EXPIRY ALERT CONFIGURATION
    # =========================================================================

    async def list_expiry_configs(
        self,
        alert_type: str | None = None,
        is_enabled: bool | None = None,
    ) -> list[dict[str, Any]]:
        """List all custom expiry alert configurations, soonest expiry first."""
        if self.db is None:
            return []

        query = select(CustomExpiryAlertConfig)
        if alert_type:
            query = query.where(CustomExpiryAlertConfig.alert_type == alert_type)
        if is_enabled is not None:
            query = query.where(CustomExpiryAlertConfig.is_enabled == is_enabled)

        query = query.order_by(CustomExpiryAlertConfig.expiry_date)
        result = await self.db.execute(query)
        configs = result.scalars().all()
        today = datetime.utcnow().date()

        return [
            {
                "id": c.id,
                "alert_type": c.alert_type,
                "resource_name": c.resource_name,
                "resource_identifier": c.resource_identifier,
                "description": c.description,
                "environment": c.environment,
                "expiry_date": c.expiry_date.isoformat(),
                "days_until_expiry": days_until_expiry(c.expiry_date, today),
                "warning_days_before": c.warning_days_before,
                "critical_days_before": c.critical_days_before,
                "is_enabled": c.is_enabled,
                "notification_emails": c.notification_emails or [],
                "snooze_until": _iso(c.snooze_until),
                "metadata": c.extra_data or {},
                "created_at": c.created_at.isoformat(),
                "updated_at": _iso(c.updated_at),
                "created_by": c.created_by,
            }
            for c in configs
        ]

    async def create_expiry_config(
        self,
        alert_type: str,
        resource_name: str,
        resource_identifier: str,
        expiry_date: datetime,
        created_by: str,
        description: str | None = None,
        warning_days_before: int = 30,
        critical_days_before: int = 7,
        notification_emails: list[str] | None = None,
        metadata: dict | None = None,
        environment: str | None = None,
        is_enabled: bool = True,
    ) -> dict[str, Any]:
        """Create an expiry config and raise its alert right away when it is already due."""
        if alert_type not in EXPIRY_ALERT_TYPES:
            raise HTTPException(
                status_code=422, detail=f"Invalid alert_type. Must be one of: {list(EXPIRY_ALERT_TYPES)}"
            )
        if critical_days_before >= warning_days_before:
            raise HTTPException(
                status_code=422,
                detail="Critical days must be fewer than warning days (e.g. warn at 30 days, critical at 7).",
            )

        config = CustomExpiryAlertConfig(
            alert_type=alert_type,
            resource_name=resource_name,
            resource_identifier=resource_identifier,
            description=description,
            environment=environment,
            expiry_date=_naive_utc(expiry_date),
            warning_days_before=warning_days_before,
            critical_days_before=critical_days_before,
            notification_emails=notification_emails or [],
            extra_data=metadata or {},
            created_by=created_by,
            is_enabled=is_enabled,
        )

        await self._save_new(
            config, f"An expiry configuration for '{resource_identifier}' of this type already exists."
        )
        logger.info("expiry_config_created", alert_type=alert_type, resource_name=resource_name)
        reconciled = await self.reconcile_expiry_alerts([config.id])

        return {
            "id": config.id,
            "alert_type": alert_type,
            "resource_name": resource_name,
            "status": "created",
            "alert": reconciled.get("created", 0) > 0,
        }

    async def update_expiry_config(
        self,
        config_id: int,
        **updates,
    ) -> dict[str, Any]:
        """Update an expiry config, then bring its alert in line straight away."""
        db = self._require_db()
        config = await self._get(CustomExpiryAlertConfig, config_id, "Expiry configuration")

        allowed_fields = {
            "resource_name",
            "description",
            "environment",
            "expiry_date",
            "warning_days_before",
            "critical_days_before",
            "is_enabled",
            "notification_emails",
            "snooze_until",
        }
        _apply_updates(config, updates, allowed_fields)
        if "metadata" in updates:
            # The model column is extra_data; "metadata" is SQLAlchemy's own attribute.
            config.extra_data = updates["metadata"]
        if config.critical_days_before >= config.warning_days_before:
            await db.rollback()
            raise HTTPException(status_code=422, detail="Critical days must be fewer than warning days.")

        await db.commit()
        logger.info("expiry_config_updated", config_id=config_id)
        await self.reconcile_expiry_alerts([config_id])
        return {"id": config_id, "status": "updated"}

    async def delete_expiry_config(self, config_id: int) -> dict[str, Any]:
        """Delete a custom expiry alert configuration and its alert history."""
        result = await self._delete_config_with_alerts(
            CustomExpiryAlertConfig, CustomExpiryAlert, config_id, "Expiry configuration"
        )
        logger.info("expiry_config_deleted", config_id=config_id)
        return result

    # =========================================================================
    # D. CUSTOM EXPIRY ALERTS
    # =========================================================================

    async def list_expiry_alerts(
        self,
        alert_type: str | None = None,
        status: str | None = None,
        severity: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """List custom expiry alerts. Days left are computed now, never read from a stale column."""
        if self.db is None:
            return []

        query = select(CustomExpiryAlert)
        if alert_type:
            query = query.where(CustomExpiryAlert.alert_type == alert_type)
        if status:
            query = query.where(CustomExpiryAlert.status == status)
        if severity:
            query = query.where(CustomExpiryAlert.severity == severity)

        query = query.order_by(desc(CustomExpiryAlert.created_at)).limit(limit)
        result = await self.db.execute(query)
        alerts = result.scalars().all()
        today = datetime.utcnow().date()

        return [
            {
                "id": a.id,
                "config_id": a.config_id,
                "alert_type": a.alert_type,
                "resource_name": a.resource_name,
                "expiry_date": a.expiry_date.isoformat(),
                "days_until_expiry": days_until_expiry(a.expiry_date, today),
                "severity": a.severity,
                "status": a.status,
                "created_at": a.created_at.isoformat(),
                "updated_at": _iso(a.updated_at),
                "acknowledged_by": a.acknowledged_by,
                "acknowledged_at": _iso(a.acknowledged_at),
                "resolved_at": _iso(a.resolved_at),
                "resolved_by": a.resolved_by,
                "resolution_notes": a.resolution_notes,
            }
            for a in alerts
        ]

    async def acknowledge_expiry_alert(
        self,
        alert_id: int,
        acknowledged_by: str,
    ) -> dict[str, Any]:
        """Acknowledge a custom expiry alert."""
        alert = await self._get(CustomExpiryAlert, alert_id, "Alert")
        if await self._acknowledge(alert, acknowledged_by):
            logger.info("expiry_alert_acknowledged", alert_id=alert_id, by=acknowledged_by)
            await self._notify_status_change(
                CustomExpiryAlertConfig,
                alert,
                alert_type=alert.alert_type,
                resource_name=alert.resource_name,
                action="acknowledged",
                action_by=acknowledged_by,
                extra={"Days Until Expiry": days_until_expiry(alert.expiry_date), "Severity": alert.severity},
            )
        return {"id": alert_id, "status": "acknowledged"}

    async def resolve_expiry_alert(
        self,
        alert_id: int,
        resolution_notes: str | None = None,
        resolved_by: str | None = None,
    ) -> dict[str, Any]:
        """Resolve a custom expiry alert; it stays resolved for this expiry date unless it gets worse."""
        alert = await self._get(CustomExpiryAlert, alert_id, "Alert")
        if await self._resolve(alert, resolved_by, resolution_notes):
            logger.info("expiry_alert_resolved", alert_id=alert_id)
            extra: dict[str, Any] = {
                "Days Until Expiry": days_until_expiry(alert.expiry_date),
                "Severity": alert.severity,
            }
            if resolution_notes:
                extra["Resolution Notes"] = resolution_notes
            await self._notify_status_change(
                CustomExpiryAlertConfig,
                alert,
                alert_type=alert.alert_type,
                resource_name=alert.resource_name,
                action="resolved",
                action_by=resolved_by or SYSTEM_ACTOR,
                extra=extra,
            )
        return {"id": alert_id, "status": "resolved"}

    async def reconcile_expiry_alerts(
        self, config_ids: list[int] | None = None, *, notify: bool = True
    ) -> dict[str, Any]:
        """Bring every expiry config's alert in line with its expiry date.

        The one implementation behind the scheduled check, the "Check Expiry
        Alerts" button, and config create/update — previously two diverging
        copies, one of which never emailed or honoured snoozes.
        """
        if self.db is None:
            return {"error": "Database unavailable"}

        stmt = select(CustomExpiryAlertConfig)
        if config_ids is not None:
            stmt = stmt.where(CustomExpiryAlertConfig.id.in_(config_ids))
        configs = (await self.db.execute(stmt)).scalars().all()

        now = datetime.utcnow()
        today = now.date()
        summary = dict.fromkeys(("checked", "created", "escalated", "updated", "resolved", "snoozed", "suppressed"), 0)
        events: list[tuple[str, Any, Any]] = []

        for config in configs:
            open_alerts = await self._open_alerts(CustomExpiryAlert, config.id)
            if not config.is_enabled:
                for alert in open_alerts:
                    self._close(alert, now, "Closed automatically: monitoring for this configuration was disabled.")
                summary["resolved"] += len(open_alerts)
                continue
            if config.snooze_until and config.snooze_until > now:
                summary["snoozed"] += 1
                continue

            summary["checked"] += 1
            days = days_until_expiry(config.expiry_date, today)
            severity = expiry_severity(days, config.warning_days_before, config.critical_days_before)

            if severity is None:
                for alert in open_alerts:
                    alert.expiry_date = config.expiry_date
                    alert.days_until_expiry = days
                    self._close(
                        alert,
                        now,
                        f"Auto-resolved: expiry date is now {config.expiry_date:%Y-%m-%d}, outside the "
                        f"{config.warning_days_before}-day warning window.",
                    )
                    events.append(("resolved", alert, config))
                summary["resolved"] += len(open_alerts)
                continue

            if open_alerts:
                primary = open_alerts[0]
                for duplicate in open_alerts[1:]:
                    self._close(duplicate, now, f"Closed automatically: duplicate of alert #{primary.id}.")
                # Days as of the previous check, to notice the day it passes expiry.
                previous_days = primary.days_until_expiry if primary.days_until_expiry is not None else days
                same_cycle = primary.expiry_date == config.expiry_date
                expired_now = days < 0 <= previous_days
                escalated = same_cycle and (
                    SEVERITY_RANK[severity] > SEVERITY_RANK.get(primary.severity, 0) or expired_now
                )
                primary.expiry_date = config.expiry_date
                primary.resource_name = config.resource_name
                primary.days_until_expiry = days
                primary.severity = severity
                primary.updated_at = now
                if escalated:
                    primary.status = "active"
                    summary["escalated"] += 1
                    events.append(("escalated", primary, config))
                else:
                    summary["updated"] += 1
                continue

            # A person resolved this expiry date's alert: respect that unless it got worse.
            last = (
                (
                    await self.db.execute(
                        select(CustomExpiryAlert)
                        .where(
                            CustomExpiryAlert.config_id == config.id,
                            CustomExpiryAlert.expiry_date == config.expiry_date,
                        )
                        .order_by(desc(CustomExpiryAlert.created_at), desc(CustomExpiryAlert.id))
                        .limit(1)
                    )
                )
                .scalars()
                .first()
            )
            if (
                last is not None
                and last.resolved_by not in (None, SYSTEM_ACTOR)
                and SEVERITY_RANK.get(last.severity, 0) >= SEVERITY_RANK[severity]
                and not (days < 0 <= (last.days_until_expiry if last.days_until_expiry is not None else 0))
            ):
                summary["suppressed"] += 1
                continue

            alert = CustomExpiryAlert(
                config_id=config.id,
                alert_type=config.alert_type,
                resource_name=config.resource_name,
                expiry_date=config.expiry_date,
                days_until_expiry=days,
                severity=severity,
                status="active",
                created_at=now,
                updated_at=now,
            )
            self.db.add(alert)
            summary["created"] += 1
            events.append(("created", alert, config))

        await self.db.commit()
        if notify:
            await self._notify_expiry_events(events)
        logger.info("expiry_alerts_reconciled", **summary)
        return summary

    async def _notify_expiry_events(self, events: list[tuple[str, Any, Any]]) -> None:
        if not events:
            return
        email = EmailNotificationService(self.db)
        for event, alert, config in events:
            recipients = config.notification_emails or []
            if not recipients:
                continue
            try:
                if event in ("created", "escalated"):
                    await email.send_expiry_alert(
                        recipient_emails=recipients,
                        resource_name=config.resource_name,
                        resource_identifier=config.resource_identifier,
                        alert_type=config.alert_type,
                        expiry_date=config.expiry_date,
                        days_until_expiry=alert.days_until_expiry,
                        severity=alert.severity,
                        description=config.description,
                        alert_id=alert.id,
                    )
                else:
                    await email.send_alert_status_change(
                        recipient_emails=recipients,
                        alert_type=config.alert_type,
                        resource_name=config.resource_name,
                        action="resolved",
                        action_by="system (auto-resolved)",
                        alert_id=alert.id,
                        extra_details={
                            "New Expiry Date": f"{config.expiry_date:%Y-%m-%d}",
                            "Reason": alert.resolution_notes,
                        },
                    )
            except Exception as exc:
                logger.warning("expiry_alert_email_failed", alert_id=alert.id, event=event, error=str(exc)[:200])

    async def check_and_generate_expiry_alerts(self) -> dict[str, Any]:
        """Backward-compatible name for :meth:`reconcile_expiry_alerts`."""
        result = await self.reconcile_expiry_alerts()
        return {"alerts_created": result.get("created", 0), **result}

    # =========================================================================
    # E. ALERT DASHBOARD / SUMMARY
    # =========================================================================

    async def get_alert_summary(self) -> dict[str, Any]:
        """Get summary of all alerts for dashboard."""
        if self.db is None:
            return {"error": "Database unavailable"}

        scoped_subscription_ids = await self._resolve_scoped_subscription_ids()

        # Count VM threshold alerts by status
        vm_query = (
            select(
                VMThresholdAlert.status,
                VMThresholdAlert.severity,
                func.count(VMThresholdAlert.id).label("count"),
            )
            .join(
                VMThresholdAlertConfig,
                VMThresholdAlert.config_id == VMThresholdAlertConfig.id,
            )
            .where(VMThresholdAlertConfig.subscription_id.in_(scoped_subscription_ids))
            .group_by(VMThresholdAlert.status, VMThresholdAlert.severity)
        )

        vm_result = await self.db.execute(vm_query)
        vm_counts = vm_result.all()

        # Count expiry alerts by type and status
        expiry_query = select(
            CustomExpiryAlert.alert_type,
            CustomExpiryAlert.status,
            func.count(CustomExpiryAlert.id).label("count"),
        ).group_by(CustomExpiryAlert.alert_type, CustomExpiryAlert.status)

        expiry_result = await self.db.execute(expiry_query)
        expiry_counts = expiry_result.all()

        # Count PG Flex Server alerts by status
        pg_query = (
            select(
                PGFlexServerAlert.status,
                PGFlexServerAlert.severity,
                func.count(PGFlexServerAlert.id).label("count"),
            )
            .join(
                PGFlexServerAlertConfig,
                PGFlexServerAlert.config_id == PGFlexServerAlertConfig.id,
            )
            .where(PGFlexServerAlertConfig.subscription_id.in_(scoped_subscription_ids))
            .group_by(PGFlexServerAlert.status, PGFlexServerAlert.severity)
        )

        pg_result = await self.db.execute(pg_query)
        pg_counts = pg_result.all()

        def _aggregate(rows: list[Any], key: str) -> dict[str, int]:
            counts: dict[str, int] = {}
            for row in rows:
                value = getattr(row, key, None)
                if not value:
                    continue
                counts[str(value)] = counts.get(str(value), 0) + int(row.count or 0)
            return counts

        def _family(by_status: dict[str, int], **extra: dict[str, int]) -> dict[str, Any]:
            return {
                "by_status": by_status,
                **extra,
                "total": sum(by_status.values()),
                "active": by_status.get("active", 0),
                "acknowledged": by_status.get("acknowledged", 0),
                "open": by_status.get("active", 0) + by_status.get("acknowledged", 0),
            }

        vm_by_status = _aggregate(vm_counts, "status")
        expiry_by_status = _aggregate(expiry_counts, "status")
        pg_by_status = _aggregate(pg_counts, "status")
        families = {
            "vm_threshold_alerts": _family(vm_by_status, by_severity=_aggregate(vm_counts, "severity")),
            "expiry_alerts": _family(expiry_by_status, by_type=_aggregate(expiry_counts, "alert_type")),
            "pg_flex_alerts": _family(pg_by_status, by_severity=_aggregate(pg_counts, "severity")),
        }

        return {
            **families,
            "total_active_alerts": sum(f["active"] for f in families.values()),
            "total_open_alerts": sum(f["open"] for f in families.values()),
            "last_updated": datetime.utcnow().isoformat(),
        }

    async def collect_digest(self) -> dict[str, list[dict[str, Any]]]:
        """Open alerts of every kind for the digest email."""
        db = self._require_db()
        today = datetime.utcnow().date()
        vm_alerts = (
            (await db.execute(select(VMThresholdAlert).where(VMThresholdAlert.status.in_(OPEN_ALERT_STATUSES))))
            .scalars()
            .all()
        )
        pg_alerts = (
            (await db.execute(select(PGFlexServerAlert).where(PGFlexServerAlert.status.in_(OPEN_ALERT_STATUSES))))
            .scalars()
            .all()
        )
        expiry_alerts = (
            (await db.execute(select(CustomExpiryAlert).where(CustomExpiryAlert.status.in_(OPEN_ALERT_STATUSES))))
            .scalars()
            .all()
        )
        return {
            "vm_alerts": [
                {
                    "vm_name": a.vm_name,
                    "metric_type": a.metric_type,
                    "current_value": round(a.current_value, 1),
                    "severity": a.severity,
                    "status": a.status,
                }
                for a in vm_alerts
            ],
            "pg_alerts": [
                {
                    "server_name": a.server_name,
                    "metric_type": a.metric_type,
                    "current_value": round(a.current_value, 1),
                    "severity": a.severity,
                    "status": a.status,
                }
                for a in pg_alerts
            ],
            "expiry_alerts": sorted(
                (
                    {
                        "resource_name": a.resource_name,
                        "alert_type": a.alert_type,
                        "days_until_expiry": days_until_expiry(a.expiry_date, today),
                        "severity": a.severity,
                        "status": a.status,
                    }
                    for a in expiry_alerts
                ),
                key=lambda row: row["days_until_expiry"],
            ),
        }

    # =========================================================================
    # F. ALERT SCHEDULES
    # =========================================================================

    async def list_alert_schedule_configs(self) -> list[dict[str, Any]]:
        """List all persisted infra alert schedule configurations."""
        if self.db is None:
            return []

        result = await self.db.execute(select(AlertScheduleConfig).order_by(desc(AlertScheduleConfig.updated_at)))
        configs = result.scalars().all()

        return [
            {
                "id": config.id,
                "name": config.name,
                "description": config.description,
                "schedule_type": config.schedule_type,
                "interval_minutes": config.interval_minutes,
                "cron_expression": config.cron_expression,
                "check_vm_thresholds": config.check_vm_thresholds,
                "check_storage_thresholds": config.check_storage_thresholds,
                "check_disk_thresholds": config.check_disk_thresholds,
                "check_expiry_alerts": config.check_expiry_alerts,
                "check_pg_thresholds": config.check_pg_thresholds,
                "send_daily_digest": config.send_daily_digest,
                "digest_time_utc": config.digest_time_utc,
                "digest_recipients": config.digest_recipients or [],
                "is_enabled": config.is_enabled,
                "last_run_at": config.last_run_at.isoformat() if config.last_run_at else None,
                "next_run_at": config.next_run_at.isoformat() if config.next_run_at else None,
                "created_at": config.created_at.isoformat(),
                "updated_at": config.updated_at.isoformat() if config.updated_at else None,
                "created_by": config.created_by,
            }
            for config in configs
        ]

    @staticmethod
    def _validate_schedule(schedule_type: str, cron_expression: str | None, interval_minutes: int | None) -> None:
        """A schedule the scheduler cannot load used to save fine and then never run."""
        if schedule_type == "cron":
            if not (cron_expression or "").strip():
                raise HTTPException(
                    status_code=422, detail="A cron schedule needs a cron expression, e.g. '0 8 * * *'."
                )
            try:
                cron_trigger_from_crontab(cron_expression.strip(), timezone="UTC")
            except Exception as exc:
                raise HTTPException(status_code=422, detail=f"Invalid cron expression '{cron_expression}': {exc}")
        elif not interval_minutes or interval_minutes < 1:
            raise HTTPException(status_code=422, detail="Interval must be at least 1 minute.")

    async def create_alert_schedule_config(
        self,
        *,
        name: str,
        created_by: str,
        description: str | None = None,
        schedule_type: str = "interval",
        interval_minutes: int = 15,
        cron_expression: str | None = None,
        check_vm_thresholds: bool = True,
        check_storage_thresholds: bool = False,
        check_disk_thresholds: bool = False,
        check_expiry_alerts: bool = True,
        check_pg_thresholds: bool = True,
        send_daily_digest: bool = True,
        digest_time_utc: str = "08:00",
        digest_recipients: list[str] | None = None,
        is_enabled: bool = True,
    ) -> dict[str, Any]:
        """Create a persisted infra alert schedule configuration."""
        self._validate_schedule(schedule_type, cron_expression, interval_minutes)
        config = AlertScheduleConfig(
            name=name,
            description=description,
            schedule_type=schedule_type,
            interval_minutes=interval_minutes,
            cron_expression=(cron_expression or "").strip() or None if schedule_type == "cron" else None,
            check_vm_thresholds=check_vm_thresholds,
            check_storage_thresholds=check_storage_thresholds,
            check_disk_thresholds=check_disk_thresholds,
            check_expiry_alerts=check_expiry_alerts,
            check_pg_thresholds=check_pg_thresholds,
            send_daily_digest=send_daily_digest,
            digest_time_utc=digest_time_utc,
            digest_recipients=digest_recipients or [],
            is_enabled=is_enabled,
            # The scheduler fills this from the real trigger on its next sync.
            next_run_at=None,
            created_by=created_by,
        )

        await self._save_new(config, f"A schedule named '{name}' already exists.")
        logger.info("alert_schedule_config_created", schedule_name=name, created_by=created_by)
        return {"id": config.id, "name": config.name, "status": "created"}

    async def update_alert_schedule_config(self, config_id: int, **updates) -> dict[str, Any]:
        """Update a persisted infra alert schedule configuration."""
        db = self._require_db()
        config = await self._get(AlertScheduleConfig, config_id, "Schedule")

        allowed_fields = {
            "name",
            "description",
            "schedule_type",
            "interval_minutes",
            "cron_expression",
            "check_vm_thresholds",
            "check_storage_thresholds",
            "check_disk_thresholds",
            "check_expiry_alerts",
            "check_pg_thresholds",
            "send_daily_digest",
            "digest_time_utc",
            "digest_recipients",
            "is_enabled",
        }
        for key, value in updates.items():
            if key in allowed_fields:
                setattr(config, key, value)
        try:
            self._validate_schedule(config.schedule_type, config.cron_expression, config.interval_minutes)
        except HTTPException:
            await db.rollback()
            raise
        if config.schedule_type != "cron":
            config.cron_expression = None
        # The scheduler's next sync recomputes this from the job's actual trigger.
        config.next_run_at = None

        try:
            await db.commit()
        except IntegrityError:
            await db.rollback()
            raise _conflict(f"A schedule named '{updates.get('name')}' already exists.")
        logger.info("alert_schedule_config_updated", config_id=config_id)
        return {"id": config_id, "status": "updated"}

    async def delete_alert_schedule_config(self, config_id: int) -> dict[str, Any]:
        """Delete a persisted infra alert schedule configuration."""
        return await self._delete_config_with_alerts(AlertScheduleConfig, None, config_id, "Schedule")

    async def seed_default_alert_schedules(self) -> dict[str, Any]:
        """Seed baseline infra alert schedules when none exist."""
        if self.db is None:
            return {"created": 0, "skipped": 0, "error": "database unavailable"}

        existing_count = (await self.db.execute(select(func.count(AlertScheduleConfig.id)))).scalar_one()
        if existing_count:
            logger.info(
                "seed_default_alert_schedules_skipped",
                reason="existing_schedules_present",
                existing_count=existing_count,
            )
            return {"created": 0, "skipped": existing_count}

        defaults = [
            AlertScheduleConfig(
                name="Infra Alert Checks",
                description="Auto-seeded schedule for VM, PG, and expiry alert checks",
                schedule_type="interval",
                interval_minutes=15,
                cron_expression=None,
                check_vm_thresholds=True,
                check_storage_thresholds=False,
                check_disk_thresholds=False,
                check_expiry_alerts=True,
                check_pg_thresholds=True,
                send_daily_digest=False,
                digest_time_utc="08:00",
                digest_recipients=[],
                is_enabled=True,
                created_by="system-auto-seed",
                next_run_at=datetime.utcnow(),
            ),
            AlertScheduleConfig(
                name="Daily Alert Digest",
                description="Auto-seeded schedule for the daily infra alert digest",
                schedule_type="cron",
                interval_minutes=1440,
                cron_expression="0 8 * * *",
                check_vm_thresholds=False,
                check_storage_thresholds=False,
                check_disk_thresholds=False,
                check_expiry_alerts=False,
                check_pg_thresholds=False,
                send_daily_digest=True,
                digest_time_utc="08:00",
                digest_recipients=[],
                is_enabled=True,
                created_by="system-auto-seed",
            ),
        ]

        for schedule in defaults:
            self.db.add(schedule)

        await self.db.commit()
        logger.info("seed_default_alert_schedules_completed", created=len(defaults), skipped=0)
        return {"created": len(defaults), "skipped": 0}

    # =========================================================================
    # G. STORAGE ALERT CONFIGS
    # =========================================================================

    async def list_storage_alert_configs(
        self,
        subscription_id: str | None = None,
        is_enabled: bool | None = None,
    ) -> list[dict[str, Any]]:
        """List all storage alert configurations."""
        if self.db is None:
            return []

        scoped_subscription_ids = await self._resolve_scoped_subscription_ids(subscription_id)

        query = select(StorageAlertConfig).where(StorageAlertConfig.subscription_id.in_(scoped_subscription_ids))
        if is_enabled is not None:
            query = query.where(StorageAlertConfig.is_enabled == is_enabled)

        query = query.order_by(desc(StorageAlertConfig.created_at))
        result = await self.db.execute(query)
        configs = result.scalars().all()

        return [
            {
                "id": c.id,
                "subscription_id": c.subscription_id,
                "resource_group": c.resource_group,
                "account_name": c.account_name,
                "account_id": c.account_id,
                "capacity_warning_gb": c.capacity_warning_gb,
                "capacity_critical_gb": c.capacity_critical_gb,
                "transactions_warning": c.transactions_warning,
                "transactions_critical": c.transactions_critical,
                "egress_warning_gb": c.egress_warning_gb,
                "egress_critical_gb": c.egress_critical_gb,
                "is_enabled": c.is_enabled,
                "notification_emails": c.notification_emails or [],
                "snooze_until": _iso(c.snooze_until),
                "created_at": c.created_at.isoformat(),
                "updated_at": _iso(c.updated_at),
                "created_by": c.created_by,
            }
            for c in configs
        ]

    async def create_storage_alert_config(
        self,
        subscription_id: str,
        resource_group: str,
        account_name: str,
        account_id: str,
        created_by: str,
        capacity_warning_gb: float = 100.0,
        capacity_critical_gb: float = 500.0,
        transactions_warning: int = 100000,
        transactions_critical: int = 500000,
        egress_warning_gb: float = 50.0,
        egress_critical_gb: float = 200.0,
        notification_emails: list[str] | None = None,
        is_enabled: bool = True,
    ) -> dict[str, Any]:
        """Create a new storage alert configuration."""
        assert_resource_access(subscription_id, "write", context=f"storage alert config {account_name}")
        _validate_pairs(
            [
                ("Capacity", capacity_warning_gb, capacity_critical_gb),
                ("Transactions", transactions_warning, transactions_critical),
                ("Egress", egress_warning_gb, egress_critical_gb),
            ]
        )
        config = StorageAlertConfig(
            subscription_id=subscription_id,
            resource_group=resource_group,
            account_name=account_name,
            account_id=account_id,
            capacity_warning_gb=capacity_warning_gb,
            capacity_critical_gb=capacity_critical_gb,
            transactions_warning=transactions_warning,
            transactions_critical=transactions_critical,
            egress_warning_gb=egress_warning_gb,
            egress_critical_gb=egress_critical_gb,
            notification_emails=notification_emails or [],
            created_by=created_by,
            is_enabled=is_enabled,
        )

        await self._save_new(config, f"Storage account '{account_name}' already has an alert configuration.")
        logger.info("storage_alert_config_created", account_name=account_name)

        return {
            "id": config.id,
            "account_name": account_name,
            "status": "created",
        }

    async def update_storage_alert_config(
        self,
        config_id: int,
        **updates,
    ) -> dict[str, Any]:
        """Update a storage alert configuration."""
        self._require_db()
        await self._assert_row_writable(StorageAlertConfig, config_id=config_id)
        config = await self._get(StorageAlertConfig, config_id, "Storage alert configuration")

        allowed_fields = {
            "capacity_warning_gb",
            "capacity_critical_gb",
            "transactions_warning",
            "transactions_critical",
            "egress_warning_gb",
            "egress_critical_gb",
            "is_enabled",
            "notification_emails",
            "snooze_until",
        }
        _apply_updates(config, updates, allowed_fields)
        _validate_pairs(
            [
                ("Capacity", config.capacity_warning_gb, config.capacity_critical_gb),
                ("Transactions", config.transactions_warning, config.transactions_critical),
                ("Egress", config.egress_warning_gb, config.egress_critical_gb),
            ]
        )

        await self.db.commit()
        logger.info("storage_alert_config_updated", config_id=config_id)
        return {"id": config_id, "status": "updated"}

    async def delete_storage_alert_config(self, config_id: int) -> dict[str, Any]:
        """Delete a storage alert configuration."""
        self._require_db()
        await self._assert_row_writable(StorageAlertConfig, config_id=config_id)
        result = await self._delete_config_with_alerts(
            StorageAlertConfig, None, config_id, "Storage alert configuration"
        )
        logger.info("storage_alert_config_deleted", config_id=config_id)
        return result

    # =========================================================================
    # H. PG FLEX SERVER ALERT CONFIGS
    # =========================================================================

    async def list_pg_flex_configs(
        self,
        subscription_id: str | None = None,
        is_enabled: bool | None = None,
    ) -> list[dict[str, Any]]:
        """List all PostgreSQL Flexible Server alert configurations."""
        if self.db is None:
            return []

        scoped_subscription_ids = await self._resolve_scoped_subscription_ids(subscription_id)

        query = select(PGFlexServerAlertConfig).where(
            PGFlexServerAlertConfig.subscription_id.in_(scoped_subscription_ids)
        )
        if is_enabled is not None:
            query = query.where(PGFlexServerAlertConfig.is_enabled == is_enabled)

        query = query.order_by(desc(PGFlexServerAlertConfig.created_at))
        result = await self.db.execute(query)
        configs = result.scalars().all()

        return [
            {
                "id": c.id,
                "subscription_id": c.subscription_id,
                "resource_group": c.resource_group,
                "server_name": c.server_name,
                "server_id": c.server_id,
                "cpu_warning_threshold": c.cpu_warning_threshold,
                "cpu_critical_threshold": c.cpu_critical_threshold,
                "memory_warning_threshold": c.memory_warning_threshold,
                "memory_critical_threshold": c.memory_critical_threshold,
                "storage_warning_threshold": c.storage_warning_threshold,
                "storage_critical_threshold": c.storage_critical_threshold,
                "is_enabled": c.is_enabled,
                "notification_emails": c.notification_emails or [],
                "snooze_until": _iso(c.snooze_until),
                "created_at": c.created_at.isoformat(),
                "updated_at": _iso(c.updated_at),
                "created_by": c.created_by,
            }
            for c in configs
        ]

    async def create_pg_flex_config(
        self,
        subscription_id: str,
        resource_group: str,
        server_name: str,
        server_id: str,
        created_by: str,
        cpu_warning_threshold: float = 70.0,
        cpu_critical_threshold: float = 90.0,
        memory_warning_threshold: float = 75.0,
        memory_critical_threshold: float = 90.0,
        storage_warning_threshold: float = 80.0,
        storage_critical_threshold: float = 95.0,
        notification_emails: list[str] | None = None,
        is_enabled: bool = True,
    ) -> dict[str, Any]:
        """Create a new PG Flexible Server alert configuration."""
        assert_resource_access(subscription_id, "write", context=f"pg alert config {server_name}")
        _validate_pairs(
            [
                ("CPU", cpu_warning_threshold, cpu_critical_threshold),
                ("Memory", memory_warning_threshold, memory_critical_threshold),
                ("Storage", storage_warning_threshold, storage_critical_threshold),
            ]
        )
        config = PGFlexServerAlertConfig(
            subscription_id=subscription_id,
            resource_group=resource_group,
            server_name=server_name,
            server_id=server_id,
            cpu_warning_threshold=cpu_warning_threshold,
            cpu_critical_threshold=cpu_critical_threshold,
            memory_warning_threshold=memory_warning_threshold,
            memory_critical_threshold=memory_critical_threshold,
            storage_warning_threshold=storage_warning_threshold,
            storage_critical_threshold=storage_critical_threshold,
            notification_emails=notification_emails or [],
            created_by=created_by,
            is_enabled=is_enabled,
        )

        await self._save_new(config, f"PG server '{server_name}' already has an alert configuration.")
        logger.info("pg_flex_config_created", server_name=server_name)

        return {
            "id": config.id,
            "server_name": server_name,
            "status": "created",
        }

    async def update_pg_flex_config(
        self,
        config_id: int,
        **updates,
    ) -> dict[str, Any]:
        """Update a PG Flexible Server alert configuration."""
        self._require_db()
        await self._assert_row_writable(PGFlexServerAlertConfig, config_id=config_id)
        config = await self._get(PGFlexServerAlertConfig, config_id, "PG alert configuration")

        allowed_fields = {
            "cpu_warning_threshold",
            "cpu_critical_threshold",
            "memory_warning_threshold",
            "memory_critical_threshold",
            "storage_warning_threshold",
            "storage_critical_threshold",
            "is_enabled",
            "notification_emails",
            "snooze_until",
        }
        _apply_updates(config, updates, allowed_fields)
        _validate_pairs(
            [
                ("CPU", config.cpu_warning_threshold, config.cpu_critical_threshold),
                ("Memory", config.memory_warning_threshold, config.memory_critical_threshold),
                ("Storage", config.storage_warning_threshold, config.storage_critical_threshold),
            ]
        )
        if not config.is_enabled:
            await self._close_open_alerts(
                PGFlexServerAlert,
                config_id,
                datetime.utcnow(),
                "Closed automatically: monitoring for this server was disabled.",
            )

        await self.db.commit()
        logger.info("pg_flex_config_updated", config_id=config_id)
        return {"id": config_id, "status": "updated"}

    async def delete_pg_flex_config(self, config_id: int) -> dict[str, Any]:
        """Delete a PG Flexible Server alert configuration and its alert history."""
        self._require_db()
        await self._assert_row_writable(PGFlexServerAlertConfig, config_id=config_id)
        result = await self._delete_config_with_alerts(
            PGFlexServerAlertConfig, PGFlexServerAlert, config_id, "PG alert configuration"
        )
        logger.info("pg_flex_config_deleted", config_id=config_id)
        return result

    # =========================================================================
    # I. PG FLEX SERVER ALERTS
    # =========================================================================

    async def list_pg_flex_alerts(
        self,
        status: str | None = None,
        severity: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """List PG Flexible Server threshold alerts."""
        if self.db is None:
            return []

        scoped_subscription_ids = await self._resolve_scoped_subscription_ids()

        query = (
            select(PGFlexServerAlert)
            .join(
                PGFlexServerAlertConfig,
                PGFlexServerAlert.config_id == PGFlexServerAlertConfig.id,
            )
            .where(PGFlexServerAlertConfig.subscription_id.in_(scoped_subscription_ids))
        )
        if status:
            query = query.where(PGFlexServerAlert.status == status)
        if severity:
            query = query.where(PGFlexServerAlert.severity == severity)

        query = query.order_by(desc(PGFlexServerAlert.created_at)).limit(limit)
        result = await self.db.execute(query)
        alerts = result.scalars().all()

        return [
            {
                "id": a.id,
                "config_id": a.config_id,
                "server_id": a.server_id,
                "server_name": a.server_name,
                "metric_type": a.metric_type,
                "current_value": a.current_value,
                "threshold_value": a.threshold_value,
                "severity": a.severity,
                "status": a.status,
                "created_at": a.created_at.isoformat(),
                "updated_at": _iso(a.updated_at),
                "acknowledged_by": a.acknowledged_by,
                "acknowledged_at": _iso(a.acknowledged_at),
                "resolved_at": _iso(a.resolved_at),
                "resolved_by": a.resolved_by,
                "resolution_notes": a.resolution_notes,
            }
            for a in alerts
        ]

    async def acknowledge_pg_flex_alert(
        self,
        alert_id: int,
        acknowledged_by: str,
    ) -> dict[str, Any]:
        """Acknowledge a PG Flexible Server alert."""
        self._require_db()
        await self._assert_row_writable(PGFlexServerAlertConfig, alert_model=PGFlexServerAlert, alert_id=alert_id)
        alert = await self._get(PGFlexServerAlert, alert_id, "Alert")
        if await self._acknowledge(alert, acknowledged_by):
            logger.info("pg_flex_alert_acknowledged", alert_id=alert_id, by=acknowledged_by)
            await self._notify_status_change(
                PGFlexServerAlertConfig,
                alert,
                alert_type="pg_flex_server",
                resource_name=alert.server_name,
                action="acknowledged",
                action_by=acknowledged_by,
                extra={"Metric": alert.metric_type.upper(), "Severity": alert.severity},
            )
        return {"id": alert_id, "status": "acknowledged"}

    async def resolve_pg_flex_alert(
        self,
        alert_id: int,
        resolution_notes: str | None = None,
        resolved_by: str | None = None,
    ) -> dict[str, Any]:
        """Resolve a PG Flexible Server alert."""
        self._require_db()
        await self._assert_row_writable(PGFlexServerAlertConfig, alert_model=PGFlexServerAlert, alert_id=alert_id)
        alert = await self._get(PGFlexServerAlert, alert_id, "Alert")
        if await self._resolve(alert, resolved_by, resolution_notes):
            logger.info("pg_flex_alert_resolved", alert_id=alert_id)
            extra = {"Metric": alert.metric_type.upper(), "Severity": alert.severity}
            if resolution_notes:
                extra["Resolution Notes"] = resolution_notes
            await self._notify_status_change(
                PGFlexServerAlertConfig,
                alert,
                alert_type="pg_flex_server",
                resource_name=alert.server_name,
                action="resolved",
                action_by=resolved_by or SYSTEM_ACTOR,
                extra=extra,
            )
        return {"id": alert_id, "status": "resolved"}

    # =========================================================================
    # J. PG FLEX SERVER METRICS
    # =========================================================================

    async def get_pg_metrics(
        self,
        subscription_id: str,
        resource_group: str,
        server_name: str,
    ) -> dict[str, Any]:
        """Current CPU, memory and storage percentages for a PG Flexible Server."""
        resource_id = (
            f"/subscriptions/{subscription_id}"
            f"/resourceGroups/{resource_group}"
            f"/providers/Microsoft.DBforPostgreSQL/flexibleServers/{server_name}"
        )
        try:
            readings = await asyncio.to_thread(
                self._read_metrics, subscription_id, resource_id, list(PG_METRICS), PG_METRIC_WINDOW
            )
        except Exception as e:
            logger.error("pg_metrics_fetch_failed", server=server_name, error=str(e)[:300])
            return {"error": str(e)[:300]}

        def _value(name: str) -> float | None:
            value = readings.get(name, (None, None))[0]
            return round(value, 2) if value is not None else None

        stamps = [stamp for _value_, stamp in readings.values() if stamp is not None]
        return {
            "cpu": _value("cpu_percent"),
            "memory": _value("memory_percent"),
            "storage": _value("storage_percent"),
            "collected_at": _iso(max(stamps)) if stamps else None,
        }

    async def check_and_generate_pg_alerts(self) -> dict[str, Any]:
        """Read every enabled PG config's metrics and update its alerts."""
        if self.db is None:
            return {"error": "Database unavailable"}

        scoped = await self._resolve_scoped_subscription_ids()
        configs = (
            (
                await self.db.execute(
                    select(PGFlexServerAlertConfig).where(
                        PGFlexServerAlertConfig.is_enabled.is_(True),
                        PGFlexServerAlertConfig.subscription_id.in_(scoped),
                    )
                )
            )
            .scalars()
            .all()
        )
        now = datetime.utcnow()
        summary: dict[str, Any] = {
            "checked": 0,
            "created": 0,
            "escalated": 0,
            "resolved": 0,
            "snoozed": 0,
            "errors": [],
        }
        events: list[tuple[str, Any, Any]] = []

        for config in configs:
            if config.snooze_until and config.snooze_until > now:
                summary["snoozed"] += 1
                continue
            metrics = await self.get_pg_metrics(config.subscription_id, config.resource_group, config.server_name)
            if "error" in metrics:
                summary["errors"].append(f"{config.server_name}: {metrics['error']}")
                continue
            summary["checked"] += 1
            for metric_type, warning, critical in (
                ("cpu", config.cpu_warning_threshold, config.cpu_critical_threshold),
                ("memory", config.memory_warning_threshold, config.memory_critical_threshold),
                ("storage", config.storage_warning_threshold, config.storage_critical_threshold),
            ):
                for event, alert in await self._apply_threshold_reading(
                    alert_model=PGFlexServerAlert,
                    config=config,
                    metric_type=metric_type,
                    value=metrics.get(metric_type),
                    warning=warning,
                    critical=critical,
                    new_alert_fields={"server_id": config.server_id, "server_name": config.server_name},
                    now=now,
                ):
                    summary[event] += 1
                    events.append((event, alert, config))

        await self.db.commit()
        await self._notify_threshold_events(events, kind="PG")
        counts = {k: v for k, v in summary.items() if k != "errors"}
        logger.info("pg_alerts_checked", **counts, errors=len(summary["errors"]))
        # "alerts_created" kept for existing callers.
        return {"alerts_created": summary["created"], **summary}
