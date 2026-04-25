"""
Infrastructure Alert Service — VM Threshold & Custom Expiry Alerts.

Provides enterprise-grade alerting capabilities:
- VM CPU, Memory, Disk threshold monitoring
- Custom expiry alerts (MechID, Certificates, AAF, Database, ITServices)
- 3-Tier data retrieval: Redis (L1) → PostgreSQL (L2) → Live API (L3)
"""

from datetime import datetime, timedelta
from typing import Any

import structlog
from azure.identity import DefaultAzureCredential
from azure.mgmt.compute import ComputeManagementClient
from azure.mgmt.monitor import MonitorManagementClient
from sqlalchemy import delete, desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.subscription_resolver import get_monitored_subscription_ids
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

logger = structlog.get_logger(__name__)


class InfraAlertService:
    """
    Infrastructure Alert Service.

    Provides:
    - VM threshold alert configuration and monitoring
    - Custom expiry alert management
    - Alert status tracking and notifications
    """

    def __init__(self, db_session: AsyncSession | None):
        self.db = db_session
        self.credential = DefaultAzureCredential()
        self._compute_clients: dict[str, ComputeManagementClient] = {}
        self._monitor_clients: dict[str, MonitorManagementClient] = {}

    # ── DB helper methods ──────────────────────────────────────────────

    async def _db_add_and_commit(self, record) -> bool:
        """Add a record and commit. Returns False if DB is unavailable."""
        if self.db is None:
            logger.warning("db_unavailable", action="add_and_commit")
            return False
        try:
            self.db.add(record)
            await self.db.commit()
            return True
        except Exception as e:
            logger.error("db_commit_failed", error=str(e))
            await self.db.rollback()
            return False

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
        monitored_subscription_ids = await get_monitored_subscription_ids()
        if subscription_id is None:
            return monitored_subscription_ids

        monitored_set = set(monitored_subscription_ids)
        return [subscription_id] if subscription_id in monitored_set else []

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
                "snooze_until": c.snooze_until.isoformat() if c.snooze_until else None,
                "created_at": c.created_at.isoformat(),
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
    ) -> dict[str, Any]:
        """Create a new VM threshold alert configuration."""
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
        )

        await self._db_add_and_commit(config)
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
        if self.db is None:
            return {"error": "Database unavailable"}

        result = await self.db.execute(select(VMThresholdAlertConfig).where(VMThresholdAlertConfig.id == config_id))
        config = result.scalar_one_or_none()
        if not config:
            return {"error": "Configuration not found"}

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
        for key, value in updates.items():
            if key in allowed_fields:
                setattr(config, key, value)

        await self._db_commit()
        logger.info("vm_threshold_config_updated", config_id=config_id)
        return {"id": config_id, "status": "updated"}

    async def delete_vm_threshold_config(self, config_id: int) -> dict[str, Any]:
        """Delete a VM threshold alert configuration."""
        if self.db is None:
            return {"error": "Database unavailable"}

        await self.db.execute(delete(VMThresholdAlertConfig).where(VMThresholdAlertConfig.id == config_id))
        await self._db_commit()
        logger.info("vm_threshold_config_deleted", config_id=config_id)
        return {"id": config_id, "status": "deleted"}

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
                "acknowledged_by": a.acknowledged_by,
                "acknowledged_at": (a.acknowledged_at.isoformat() if a.acknowledged_at else None),
                "resolved_at": a.resolved_at.isoformat() if a.resolved_at else None,
            }
            for a in alerts
        ]

    async def acknowledge_vm_alert(
        self,
        alert_id: int,
        acknowledged_by: str,
    ) -> dict[str, Any]:
        """Acknowledge a VM threshold alert."""
        if self.db is None:
            return {"error": "Database unavailable"}

        result = await self.db.execute(select(VMThresholdAlert).where(VMThresholdAlert.id == alert_id))
        alert = result.scalar_one_or_none()
        if not alert:
            return {"error": "Alert not found"}

        alert.status = "acknowledged"
        alert.acknowledged_by = acknowledged_by
        alert.acknowledged_at = datetime.utcnow()
        await self._db_commit()

        logger.info("vm_alert_acknowledged", alert_id=alert_id, by=acknowledged_by)
        return {"id": alert_id, "status": "acknowledged"}

    async def resolve_vm_alert(
        self,
        alert_id: int,
        resolution_notes: str | None = None,
    ) -> dict[str, Any]:
        """Resolve a VM threshold alert."""
        if self.db is None:
            return {"error": "Database unavailable"}

        result = await self.db.execute(select(VMThresholdAlert).where(VMThresholdAlert.id == alert_id))
        alert = result.scalar_one_or_none()
        if not alert:
            return {"error": "Alert not found"}

        alert.status = "resolved"
        alert.resolved_at = datetime.utcnow()
        alert.resolution_notes = resolution_notes
        await self._db_commit()

        logger.info("vm_alert_resolved", alert_id=alert_id)
        return {"id": alert_id, "status": "resolved"}

    async def get_vm_metrics(
        self,
        subscription_id: str,
        resource_group: str,
        vm_name: str,
    ) -> dict[str, Any]:
        """Fetch current VM metrics from Azure Monitor."""
        try:
            monitor_client = self._get_monitor_client(subscription_id)
            resource_id = (
                f"/subscriptions/{subscription_id}"
                f"/resourceGroups/{resource_group}"
                f"/providers/Microsoft.Compute/virtualMachines/{vm_name}"
            )

            end_time = datetime.utcnow()
            start_time = end_time - timedelta(minutes=5)
            timespan = f"{start_time.isoformat()}Z/{end_time.isoformat()}Z"

            metrics = monitor_client.metrics.list(
                resource_id,
                timespan=timespan,
                interval="PT1M",
                metricnames="Percentage CPU,Available Memory Bytes,OS Disk Write Bytes/sec",
                aggregation="Average",
            )

            result = {"cpu": None, "memory": None, "disk": None}
            for item in metrics.value:
                if item.name.localized_value == "Percentage CPU":
                    for ts in item.timeseries:
                        for data in ts.data:
                            if data.average is not None:
                                result["cpu"] = round(data.average, 2)
                elif "Memory" in item.name.localized_value:
                    for ts in item.timeseries:
                        for data in ts.data:
                            if data.average is not None:
                                # Convert to percentage (assuming typical VM memory)
                                result["memory"] = round(data.average / 1e9, 2)
                elif "Disk" in item.name.localized_value:
                    for ts in item.timeseries:
                        for data in ts.data:
                            if data.average is not None:
                                result["disk"] = round(data.average, 2)

            return result
        except Exception as e:
            logger.error("vm_metrics_fetch_failed", error=str(e))
            return {"error": str(e)}

    async def list_vms(self, subscription_id: str) -> list[dict[str, Any]]:
        """List all VMs in a subscription."""
        try:
            compute_client = self._get_compute_client(subscription_id)
            vms = compute_client.virtual_machines.list_all()

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
                        (s.display_status for s in (vm.instance_view.statuses if vm.instance_view else [])),
                        "Unknown",
                    ),
                }
                for vm in vms
            ]
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
        """List all custom expiry alert configurations."""
        if self.db is None:
            return []

        query = select(CustomExpiryAlertConfig)
        if alert_type:
            query = query.where(CustomExpiryAlertConfig.alert_type == alert_type)
        if is_enabled is not None:
            query = query.where(CustomExpiryAlertConfig.is_enabled == is_enabled)

        query = query.order_by(desc(CustomExpiryAlertConfig.expiry_date))
        result = await self.db.execute(query)
        configs = result.scalars().all()

        return [
            {
                "id": c.id,
                "alert_type": c.alert_type,
                "resource_name": c.resource_name,
                "resource_identifier": c.resource_identifier,
                "description": c.description,
                "expiry_date": c.expiry_date.isoformat(),
                "warning_days_before": c.warning_days_before,
                "critical_days_before": c.critical_days_before,
                "is_enabled": c.is_enabled,
                "notification_emails": c.notification_emails or [],
                "metadata": c.extra_data or {},
                "created_at": c.created_at.isoformat(),
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
    ) -> dict[str, Any]:
        """Create a new custom expiry alert configuration."""
        valid_types = [
            "mech_id",
            "certificate",
            "aaf_account",
            "database_account",
            "itservices_domain",
        ]
        if alert_type not in valid_types:
            return {"error": f"Invalid alert_type. Must be one of: {valid_types}"}

        config = CustomExpiryAlertConfig(
            alert_type=alert_type,
            resource_name=resource_name,
            resource_identifier=resource_identifier,
            description=description,
            expiry_date=expiry_date,
            warning_days_before=warning_days_before,
            critical_days_before=critical_days_before,
            notification_emails=notification_emails or [],
            extra_data=metadata or {},
            created_by=created_by,
        )

        await self._db_add_and_commit(config)
        logger.info("expiry_config_created", alert_type=alert_type, resource_name=resource_name)

        return {
            "id": config.id,
            "alert_type": alert_type,
            "resource_name": resource_name,
            "status": "created",
        }

    async def update_expiry_config(
        self,
        config_id: int,
        **updates,
    ) -> dict[str, Any]:
        """Update a custom expiry alert configuration."""
        if self.db is None:
            return {"error": "Database unavailable"}

        result = await self.db.execute(select(CustomExpiryAlertConfig).where(CustomExpiryAlertConfig.id == config_id))
        config = result.scalar_one_or_none()
        if not config:
            return {"error": "Configuration not found"}

        allowed_fields = {
            "resource_name",
            "description",
            "expiry_date",
            "warning_days_before",
            "critical_days_before",
            "is_enabled",
            "notification_emails",
            "snooze_until",
            "metadata",
        }
        for key, value in updates.items():
            if key in allowed_fields:
                setattr(config, key, value)

        await self._db_commit()
        logger.info("expiry_config_updated", config_id=config_id)
        return {"id": config_id, "status": "updated"}

    async def delete_expiry_config(self, config_id: int) -> dict[str, Any]:
        """Delete a custom expiry alert configuration."""
        if self.db is None:
            return {"error": "Database unavailable"}

        await self.db.execute(delete(CustomExpiryAlertConfig).where(CustomExpiryAlertConfig.id == config_id))
        await self._db_commit()
        logger.info("expiry_config_deleted", config_id=config_id)
        return {"id": config_id, "status": "deleted"}

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
        """List custom expiry alerts."""
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

        return [
            {
                "id": a.id,
                "config_id": a.config_id,
                "alert_type": a.alert_type,
                "resource_name": a.resource_name,
                "expiry_date": a.expiry_date.isoformat(),
                "days_until_expiry": a.days_until_expiry,
                "severity": a.severity,
                "status": a.status,
                "created_at": a.created_at.isoformat(),
                "acknowledged_by": a.acknowledged_by,
                "acknowledged_at": (a.acknowledged_at.isoformat() if a.acknowledged_at else None),
                "resolved_at": a.resolved_at.isoformat() if a.resolved_at else None,
            }
            for a in alerts
        ]

    async def acknowledge_expiry_alert(
        self,
        alert_id: int,
        acknowledged_by: str,
    ) -> dict[str, Any]:
        """Acknowledge a custom expiry alert."""
        if self.db is None:
            return {"error": "Database unavailable"}

        result = await self.db.execute(select(CustomExpiryAlert).where(CustomExpiryAlert.id == alert_id))
        alert = result.scalar_one_or_none()
        if not alert:
            return {"error": "Alert not found"}

        alert.status = "acknowledged"
        alert.acknowledged_by = acknowledged_by
        alert.acknowledged_at = datetime.utcnow()
        await self._db_commit()

        logger.info("expiry_alert_acknowledged", alert_id=alert_id, by=acknowledged_by)
        return {"id": alert_id, "status": "acknowledged"}

    async def resolve_expiry_alert(
        self,
        alert_id: int,
        resolution_notes: str | None = None,
    ) -> dict[str, Any]:
        """Resolve a custom expiry alert."""
        if self.db is None:
            return {"error": "Database unavailable"}

        result = await self.db.execute(select(CustomExpiryAlert).where(CustomExpiryAlert.id == alert_id))
        alert = result.scalar_one_or_none()
        if not alert:
            return {"error": "Alert not found"}

        alert.status = "resolved"
        alert.resolved_at = datetime.utcnow()
        alert.resolution_notes = resolution_notes
        await self._db_commit()

        logger.info("expiry_alert_resolved", alert_id=alert_id)
        return {"id": alert_id, "status": "resolved"}

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

        vm_by_status = _aggregate(vm_counts, "status")
        vm_by_severity = _aggregate(vm_counts, "severity")
        expiry_by_type = _aggregate(expiry_counts, "alert_type")
        expiry_by_status = _aggregate(expiry_counts, "status")
        pg_by_status = _aggregate(pg_counts, "status")
        pg_by_severity = _aggregate(pg_counts, "severity")

        return {
            "vm_threshold_alerts": {
                "by_status": vm_by_status,
                "by_severity": vm_by_severity,
                "total": sum(vm_by_status.values()),
                "active": vm_by_status.get("active", 0),
            },
            "expiry_alerts": {
                "by_type": expiry_by_type,
                "by_status": expiry_by_status,
                "total": sum(expiry_by_status.values()),
                "active": expiry_by_status.get("active", 0),
            },
            "pg_flex_alerts": {
                "by_status": pg_by_status,
                "by_severity": pg_by_severity,
                "total": sum(pg_by_status.values()),
                "active": pg_by_status.get("active", 0),
            },
            "total_active_alerts": vm_by_status.get("active", 0)
            + expiry_by_status.get("active", 0)
            + pg_by_status.get("active", 0),
            "last_updated": datetime.utcnow().isoformat(),
        }

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
        check_storage_thresholds: bool = True,
        check_disk_thresholds: bool = True,
        check_expiry_alerts: bool = True,
        check_pg_thresholds: bool = True,
        send_daily_digest: bool = True,
        digest_time_utc: str = "08:00",
        digest_recipients: list[str] | None = None,
        is_enabled: bool = True,
    ) -> dict[str, Any]:
        """Create a persisted infra alert schedule configuration."""
        next_run_at = None
        if is_enabled and schedule_type == "interval":
            next_run_at = datetime.utcnow() + timedelta(minutes=max(interval_minutes, 1))

        config = AlertScheduleConfig(
            name=name,
            description=description,
            schedule_type=schedule_type,
            interval_minutes=interval_minutes,
            cron_expression=cron_expression,
            check_vm_thresholds=check_vm_thresholds,
            check_storage_thresholds=check_storage_thresholds,
            check_disk_thresholds=check_disk_thresholds,
            check_expiry_alerts=check_expiry_alerts,
            check_pg_thresholds=check_pg_thresholds,
            send_daily_digest=send_daily_digest,
            digest_time_utc=digest_time_utc,
            digest_recipients=digest_recipients or [],
            is_enabled=is_enabled,
            next_run_at=next_run_at,
            created_by=created_by,
        )

        await self._db_add_and_commit(config)
        logger.info("alert_schedule_config_created", schedule_name=name, created_by=created_by)
        return {"id": config.id, "name": config.name, "status": "created"}

    async def update_alert_schedule_config(self, config_id: int, **updates) -> dict[str, Any]:
        """Update a persisted infra alert schedule configuration."""
        if self.db is None:
            return {"error": "Database unavailable"}

        result = await self.db.execute(select(AlertScheduleConfig).where(AlertScheduleConfig.id == config_id))
        config = result.scalar_one_or_none()
        if not config:
            return {"error": "Configuration not found"}

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

        if not config.is_enabled:
            config.next_run_at = None
        elif config.schedule_type == "interval":
            config.next_run_at = datetime.utcnow() + timedelta(minutes=max(config.interval_minutes, 1))

        await self._db_commit()
        logger.info("alert_schedule_config_updated", config_id=config_id)
        return {"id": config_id, "status": "updated"}

    async def delete_alert_schedule_config(self, config_id: int) -> dict[str, Any]:
        """Delete a persisted infra alert schedule configuration."""
        if self.db is None:
            return {"error": "Database unavailable"}

        await self.db.execute(delete(AlertScheduleConfig).where(AlertScheduleConfig.id == config_id))
        await self._db_commit()
        logger.info("alert_schedule_config_deleted", config_id=config_id)
        return {"id": config_id, "status": "deleted"}

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

    async def check_and_generate_expiry_alerts(self) -> dict[str, Any]:
        """Check all expiry configs and generate alerts if needed."""
        if self.db is None:
            return {"error": "Database unavailable"}

        now = datetime.utcnow()
        configs_result = await self.db.execute(
            select(CustomExpiryAlertConfig).where(CustomExpiryAlertConfig.is_enabled.is_(True))
        )
        configs = configs_result.scalars().all()

        alerts_created = 0
        for config in configs:
            days_until_expiry = (config.expiry_date - now).days

            # Determine severity based on days until expiry
            severity = None
            if days_until_expiry <= 0:
                severity = "critical"  # Already expired
            elif days_until_expiry <= config.critical_days_before:
                severity = "critical"
            elif days_until_expiry <= config.warning_days_before:
                severity = "warning"

            if severity:
                # Check if an active alert already exists
                existing = await self.db.execute(
                    select(CustomExpiryAlert).where(
                        CustomExpiryAlert.config_id == config.id,
                        CustomExpiryAlert.status == "active",
                    )
                )
                if existing.scalar_one_or_none() is None:
                    alert = CustomExpiryAlert(
                        config_id=config.id,
                        alert_type=config.alert_type,
                        resource_name=config.resource_name,
                        expiry_date=config.expiry_date,
                        days_until_expiry=days_until_expiry,
                        severity=severity,
                        status="active",
                    )
                    self.db.add(alert)
                    alerts_created += 1

        await self._db_commit()
        logger.info("expiry_alerts_checked", alerts_created=alerts_created)
        return {"alerts_created": alerts_created}

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
                "snooze_until": c.snooze_until.isoformat() if c.snooze_until else None,
                "created_at": c.created_at.isoformat(),
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
    ) -> dict[str, Any]:
        """Create a new storage alert configuration."""
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
        )

        await self._db_add_and_commit(config)
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
        if self.db is None:
            return {"error": "Database unavailable"}

        result = await self.db.execute(select(StorageAlertConfig).where(StorageAlertConfig.id == config_id))
        config = result.scalar_one_or_none()
        if not config:
            return {"error": "Configuration not found"}

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
        for key, value in updates.items():
            if key in allowed_fields:
                setattr(config, key, value)

        await self._db_commit()
        logger.info("storage_alert_config_updated", config_id=config_id)
        return {"id": config_id, "status": "updated"}

    async def delete_storage_alert_config(self, config_id: int) -> dict[str, Any]:
        """Delete a storage alert configuration."""
        if self.db is None:
            return {"error": "Database unavailable"}

        await self.db.execute(delete(StorageAlertConfig).where(StorageAlertConfig.id == config_id))
        await self._db_commit()
        logger.info("storage_alert_config_deleted", config_id=config_id)
        return {"id": config_id, "status": "deleted"}

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
                "snooze_until": c.snooze_until.isoformat() if c.snooze_until else None,
                "created_at": c.created_at.isoformat(),
                "updated_at": c.updated_at.isoformat() if c.updated_at else None,
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
    ) -> dict[str, Any]:
        """Create a new PG Flexible Server alert configuration."""
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
        )

        await self._db_add_and_commit(config)
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
        if self.db is None:
            return {"error": "Database unavailable"}

        result = await self.db.execute(select(PGFlexServerAlertConfig).where(PGFlexServerAlertConfig.id == config_id))
        config = result.scalar_one_or_none()
        if not config:
            return {"error": "Configuration not found"}

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
        for key, value in updates.items():
            if key in allowed_fields:
                setattr(config, key, value)

        await self._db_commit()
        logger.info("pg_flex_config_updated", config_id=config_id)
        return {"id": config_id, "status": "updated"}

    async def delete_pg_flex_config(self, config_id: int) -> dict[str, Any]:
        """Delete a PG Flexible Server alert configuration."""
        if self.db is None:
            return {"error": "Database unavailable"}

        await self.db.execute(delete(PGFlexServerAlertConfig).where(PGFlexServerAlertConfig.id == config_id))
        await self._db_commit()
        logger.info("pg_flex_config_deleted", config_id=config_id)
        return {"id": config_id, "status": "deleted"}

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
                "acknowledged_by": a.acknowledged_by,
                "acknowledged_at": (a.acknowledged_at.isoformat() if a.acknowledged_at else None),
                "resolved_at": a.resolved_at.isoformat() if a.resolved_at else None,
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
        if self.db is None:
            return {"error": "Database unavailable"}

        result = await self.db.execute(select(PGFlexServerAlert).where(PGFlexServerAlert.id == alert_id))
        alert = result.scalar_one_or_none()
        if not alert:
            return {"error": "Alert not found"}

        alert.status = "acknowledged"
        alert.acknowledged_by = acknowledged_by
        alert.acknowledged_at = datetime.utcnow()
        await self._db_commit()

        logger.info("pg_flex_alert_acknowledged", alert_id=alert_id, by=acknowledged_by)
        return {"id": alert_id, "status": "acknowledged"}

    async def resolve_pg_flex_alert(
        self,
        alert_id: int,
        resolution_notes: str | None = None,
    ) -> dict[str, Any]:
        """Resolve a PG Flexible Server alert."""
        if self.db is None:
            return {"error": "Database unavailable"}

        result = await self.db.execute(select(PGFlexServerAlert).where(PGFlexServerAlert.id == alert_id))
        alert = result.scalar_one_or_none()
        if not alert:
            return {"error": "Alert not found"}

        alert.status = "resolved"
        alert.resolved_at = datetime.utcnow()
        alert.resolution_notes = resolution_notes
        await self._db_commit()

        logger.info("pg_flex_alert_resolved", alert_id=alert_id)
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
        """Fetch current PG Flexible Server metrics from Azure Monitor."""
        try:
            monitor_client = self._get_monitor_client(subscription_id)
            resource_id = (
                f"/subscriptions/{subscription_id}"
                f"/resourceGroups/{resource_group}"
                f"/providers/Microsoft.DBforPostgreSQL/flexibleServers/{server_name}"
            )

            end_time = datetime.utcnow()
            start_time = end_time - timedelta(minutes=5)
            timespan = f"{start_time.isoformat()}Z/{end_time.isoformat()}Z"

            metrics = monitor_client.metrics.list(
                resource_id,
                timespan=timespan,
                interval="PT1M",
                metricnames="cpu_percent,memory_percent,storage_percent",
                aggregation="Average",
            )

            result: dict[str, Any] = {"cpu": None, "memory": None, "storage": None}
            for item in metrics.value:
                metric_name = item.name.value  # cpu_percent, memory_percent, storage_percent
                for ts in item.timeseries:
                    for data in ts.data:
                        if data.average is not None:
                            if "cpu" in metric_name:
                                result["cpu"] = round(data.average, 2)
                            elif "memory" in metric_name:
                                result["memory"] = round(data.average, 2)
                            elif "storage" in metric_name:
                                result["storage"] = round(data.average, 2)

            return result
        except Exception as e:
            logger.error("pg_metrics_fetch_failed", error=str(e))
            return {"error": str(e)}

    async def check_and_generate_pg_alerts(self) -> dict[str, Any]:
        """Check all PG Flex configs and generate alerts if thresholds are exceeded."""
        if self.db is None:
            return {"error": "Database unavailable"}

        configs_result = await self.db.execute(
            select(PGFlexServerAlertConfig).where(PGFlexServerAlertConfig.is_enabled.is_(True))
        )
        configs = configs_result.scalars().all()

        alerts_created = 0
        errors = []

        for config in configs:
            # Skip if snoozed
            if config.snooze_until and config.snooze_until > datetime.utcnow():
                continue

            try:
                metrics = await self.get_pg_metrics(
                    config.subscription_id,
                    config.resource_group,
                    config.server_name,
                )

                if "error" in metrics:
                    errors.append(f"{config.server_name}: {metrics['error']}")
                    continue

                # Check each metric
                checks = [
                    (
                        "cpu",
                        metrics.get("cpu"),
                        config.cpu_warning_threshold,
                        config.cpu_critical_threshold,
                    ),
                    (
                        "memory",
                        metrics.get("memory"),
                        config.memory_warning_threshold,
                        config.memory_critical_threshold,
                    ),
                    (
                        "storage",
                        metrics.get("storage"),
                        config.storage_warning_threshold,
                        config.storage_critical_threshold,
                    ),
                ]

                for (
                    metric_type,
                    current_value,
                    warning_threshold,
                    critical_threshold,
                ) in checks:
                    if current_value is None:
                        continue

                    severity = None
                    threshold_value = None
                    if current_value >= critical_threshold:
                        severity = "critical"
                        threshold_value = critical_threshold
                    elif current_value >= warning_threshold:
                        severity = "warning"
                        threshold_value = warning_threshold

                    if severity:
                        # Check if an active alert already exists for this metric
                        existing = await self.db.execute(
                            select(PGFlexServerAlert).where(
                                PGFlexServerAlert.config_id == config.id,
                                PGFlexServerAlert.metric_type == metric_type,
                                PGFlexServerAlert.status == "active",
                            )
                        )
                        if existing.scalar_one_or_none() is None:
                            alert = PGFlexServerAlert(
                                config_id=config.id,
                                server_id=config.server_id,
                                server_name=config.server_name,
                                metric_type=metric_type,
                                current_value=current_value,
                                threshold_value=threshold_value,
                                severity=severity,
                                status="active",
                            )
                            self.db.add(alert)
                            alerts_created += 1

            except Exception as e:
                errors.append(f"{config.server_name}: {str(e)}")

        await self._db_commit()
        logger.info("pg_alerts_checked", alerts_created=alerts_created, errors=len(errors))
        return {"alerts_created": alerts_created, "errors": errors}
