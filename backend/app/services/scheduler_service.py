"""
Background Scheduler Service — Periodic Alert Checking and Notification Dispatch.

Uses APScheduler for:
- Periodic VM metric threshold checks
- Daily expiry alert generation
- Email digest delivery
- Azure resource inventory sync
"""

from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db_session
from app.models.database import (
    AlertScheduleConfig,
    ChecksumScheduleConfig,
    CustomExpiryAlert,
    CustomExpiryAlertConfig,
    VMThresholdAlert,
    VMThresholdAlertConfig,
)
from app.services.azure_resource_service import AzureResourceService
from app.services.compliance_service import ComplianceService
from app.services.email_notification_service import EmailNotificationService
from app.services.env_cost_sync_service import EnvCostSyncService
from app.services.infra_alert_service import InfraAlertService
from app.services.keyvault_sync_service import KeyVaultSyncService
from app.services.leadership_sync_service import LeadershipSyncService

logger = structlog.get_logger(__name__)

# Global scheduler instance
_scheduler: AsyncIOScheduler | None = None
ALERT_SCHEDULE_JOB_PREFIX = "alert_schedule_config:"
LEGACY_ALERT_JOB_IDS = {"vm_threshold_check", "expiry_alert_check", "daily_digest"}


def get_scheduler() -> AsyncIOScheduler:
    """Get or create the global scheduler instance."""
    global _scheduler
    if _scheduler is None:
        _scheduler = AsyncIOScheduler()
    return _scheduler


async def start_scheduler() -> None:
    """Start the background scheduler with configured jobs."""
    scheduler = get_scheduler()

    if scheduler.running:
        logger.info("scheduler_already_running")
        _register_platform_jobs(scheduler)
        _remove_legacy_alert_jobs(scheduler)
        await sync_alert_schedule_jobs()
        return

    _register_platform_jobs(scheduler)
    _remove_legacy_alert_jobs(scheduler)

    scheduler.start()
    await sync_alert_schedule_jobs()
    logger.info("scheduler_started", jobs=len(scheduler.get_jobs()))


async def stop_scheduler() -> None:
    """Stop the background scheduler."""
    scheduler = get_scheduler()
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("scheduler_stopped")


def _register_platform_jobs(scheduler: AsyncIOScheduler) -> None:
    """Register fixed non-alert scheduler jobs."""
    scheduler.add_job(
        sync_azure_resources_job,
        IntervalTrigger(hours=6),
        id="azure_resource_sync",
        name="Azure Resource Sync",
        replace_existing=True,
    )

    scheduler.add_job(
        sync_keyvault_data_job,
        IntervalTrigger(minutes=30),
        id="keyvault_data_sync",
        name="KeyVault Data Sync",
        replace_existing=True,
    )

    scheduler.add_job(
        sync_env_cost_data_job,
        IntervalTrigger(hours=6),
        id="env_cost_data_sync",
        name="Environment Cost Data Sync",
        replace_existing=True,
    )

    scheduler.add_job(
        sync_amortized_cost_job,
        IntervalTrigger(minutes=15),
        id="amortized_cost_sync",
        name="Amortized Cost Data Sync",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )

    scheduler.add_job(
        sync_leadership_dashboard_job,
        IntervalTrigger(minutes=15),
        id="leadership_dashboard_sync",
        name="Leadership Dashboard Sync",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )

    scheduler.add_job(
        run_checksum_schedules_job,
        IntervalTrigger(minutes=1),
        id="checksum_schedule_runner",
        name="Checksum Schedule Runner",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )

    scheduler.add_job(
        run_environment_schedules_job,
        IntervalTrigger(minutes=1),
        id="environment_schedule_runner",
        name="Environment Schedule Runner",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )

    # Certificate automation ticks hourly but each config runs at most once a
    # day (enforced in the service), so a restart cannot skip or duplicate a day.
    scheduler.add_job(
        run_certificate_expiry_alerts_job,
        IntervalTrigger(hours=1),
        id="certificate_expiry_alerts",
        name="Certificate Expiry Alerts",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )

    scheduler.add_job(
        run_certificate_auto_renewal_job,
        IntervalTrigger(hours=1),
        id="certificate_auto_renewal",
        name="Certificate Auto-Renewal",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )


def _remove_legacy_alert_jobs(scheduler: AsyncIOScheduler) -> None:
    """Remove pre-migration hard-coded alert jobs from a running scheduler."""
    for job_id in LEGACY_ALERT_JOB_IDS:
        try:
            if scheduler.get_job(job_id):
                scheduler.remove_job(job_id)
        except Exception as exc:
            logger.warning("legacy_alert_job_remove_failed", job_id=job_id, error=str(exc)[:200])


def _alert_schedule_job_id(config_id: int) -> str:
    return f"{ALERT_SCHEDULE_JOB_PREFIX}{config_id}"


def _normalize_run_time(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value
    return value.astimezone(UTC).replace(tzinfo=None)


def _build_alert_schedule_trigger(config: AlertScheduleConfig):
    if config.schedule_type == "cron" and config.cron_expression:
        return CronTrigger.from_crontab(config.cron_expression, timezone=UTC)
    return IntervalTrigger(minutes=max(config.interval_minutes or 1, 1), timezone=UTC)


async def ensure_default_alert_schedule_configs() -> dict[str, Any]:
    """Seed default alert schedules for empty environments."""
    async for db in get_db_session():
        service = InfraAlertService(db)
        return await service.seed_default_alert_schedules()
    return {"created": 0, "skipped": 0, "error": "database unavailable"}


async def sync_alert_schedule_jobs() -> dict[str, Any]:
    """Reload runtime APScheduler jobs from persisted alert schedule configs."""
    scheduler = get_scheduler()
    _remove_legacy_alert_jobs(scheduler)

    if not scheduler.running:
        logger.info("alert_schedule_sync_skipped", reason="scheduler_not_running")
        return {"synced": 0, "removed": 0, "running": False}

    async for db in get_db_session():
        result = await db.execute(select(AlertScheduleConfig).order_by(AlertScheduleConfig.id.asc()))
        configs = result.scalars().all()

        active_job_ids: set[str] = set()
        synced = 0

        for config in configs:
            job_id = _alert_schedule_job_id(config.id)

            if not config.is_enabled:
                if scheduler.get_job(job_id):
                    scheduler.remove_job(job_id)
                config.next_run_at = None
                continue

            trigger = _build_alert_schedule_trigger(config)
            job = scheduler.add_job(
                execute_alert_schedule_job,
                trigger,
                id=job_id,
                name=config.name,
                args=[config.id],
                replace_existing=True,
                max_instances=1,
                coalesce=True,
            )
            config.next_run_at = _normalize_run_time(job.next_run_time)
            active_job_ids.add(job_id)
            synced += 1

        removed = 0
        for job in list(scheduler.get_jobs()):
            if not job.id.startswith(ALERT_SCHEDULE_JOB_PREFIX):
                continue
            if job.id in active_job_ids:
                continue
            scheduler.remove_job(job.id)
            removed += 1

        await db.commit()
        logger.info("alert_schedule_jobs_synced", synced=synced, removed=removed)
        return {"synced": synced, "removed": removed, "running": True}

    return {"synced": 0, "removed": 0, "running": scheduler.running}


# ── Scheduled Jobs ───────────────────────────────────────────────────────


async def check_vm_thresholds_job() -> None:
    """Check VM thresholds and generate alerts."""
    logger.info("vm_threshold_check_started")

    try:
        async for db in get_db_session():
            alert_service = InfraAlertService(db)
            email_service = EmailNotificationService(db)

            # Get all enabled VM threshold configs
            configs = await alert_service.list_vm_threshold_configs(is_enabled=True)

            alerts_generated = 0

            for config in configs:
                try:
                    # Skip snoozed configs
                    if config.get("snooze_until"):
                        snooze_until = datetime.fromisoformat(config["snooze_until"])
                        if snooze_until > datetime.utcnow():
                            continue

                    # Get current VM metrics
                    metrics = await alert_service.get_vm_metrics(
                        subscription_id=config["subscription_id"],
                        resource_group=config["resource_group"],
                        vm_name=config["vm_name"],
                    )

                    if not metrics:
                        continue

                    # Check CPU threshold
                    cpu_value = metrics.get("cpu_percent", 0)
                    await _check_and_create_alert(
                        db=db,
                        config=config,
                        metric_type="cpu",
                        current_value=cpu_value,
                        warning_threshold=config["cpu_warning_threshold"],
                        critical_threshold=config["cpu_critical_threshold"],
                        email_service=email_service,
                    )

                    # Check Memory threshold
                    memory_value = metrics.get("memory_percent", 0)
                    await _check_and_create_alert(
                        db=db,
                        config=config,
                        metric_type="memory",
                        current_value=memory_value,
                        warning_threshold=config["memory_warning_threshold"],
                        critical_threshold=config["memory_critical_threshold"],
                        email_service=email_service,
                    )

                    # Check Disk threshold
                    disk_value = metrics.get("disk_percent", 0)
                    await _check_and_create_alert(
                        db=db,
                        config=config,
                        metric_type="disk",
                        current_value=disk_value,
                        warning_threshold=config["disk_warning_threshold"],
                        critical_threshold=config["disk_critical_threshold"],
                        email_service=email_service,
                    )

                except Exception as e:
                    logger.error(
                        "vm_threshold_check_error",
                        vm=config.get("vm_name"),
                        error=str(e),
                    )

            logger.info(
                "vm_threshold_check_completed",
                configs=len(configs),
                alerts=alerts_generated,
            )

    except Exception as e:
        logger.error("vm_threshold_job_failed", error=str(e))


async def sync_leadership_dashboard_job() -> None:
    """Refresh leadership dashboard snapshots when data is stale."""
    logger.info("leadership_dashboard_sync_started")

    try:
        async for db in get_db_session():
            sync_service = LeadershipSyncService(db)
            result = await sync_service.ensure_fresh_data(triggered_by="scheduler")
            logger.info(
                "leadership_dashboard_sync_completed",
                status=result.get("status", "unknown"),
            )
            break
    except Exception as exc:
        logger.error("leadership_dashboard_sync_failed", error=str(exc)[:300])


async def _check_and_create_alert(
    db: AsyncSession,
    config: dict,
    metric_type: str,
    current_value: float,
    warning_threshold: float,
    critical_threshold: float,
    email_service: EmailNotificationService,
) -> VMThresholdAlert | None:
    """Check if alert needs to be created and send notification."""
    if current_value < warning_threshold:
        return None

    severity = "critical" if current_value >= critical_threshold else "warning"
    threshold_value = critical_threshold if severity == "critical" else warning_threshold

    # Check for existing active alert
    existing = await db.execute(
        select(VMThresholdAlert).where(
            VMThresholdAlert.config_id == config["id"],
            VMThresholdAlert.metric_type == metric_type,
            VMThresholdAlert.status == "active",
        )
    )
    existing_alert = existing.scalar_one_or_none()

    if existing_alert:
        # Update existing alert
        existing_alert.current_value = current_value
        existing_alert.severity = severity
        existing_alert.threshold_value = threshold_value
        existing_alert.updated_at = datetime.utcnow()
        await db.commit()
        return existing_alert

    # Create new alert
    alert = VMThresholdAlert(
        config_id=config["id"],
        vm_id=config["vm_id"],
        vm_name=config["vm_name"],
        metric_type=metric_type,
        current_value=current_value,
        threshold_value=threshold_value,
        severity=severity,
        status="active",
    )
    db.add(alert)
    await db.commit()
    await db.refresh(alert)

    # Send email notification
    notification_emails = config.get("notification_emails", [])
    if notification_emails:
        await email_service.send_vm_threshold_alert(
            recipient_emails=notification_emails,
            vm_name=config["vm_name"],
            resource_group=config["resource_group"],
            subscription_id=config["subscription_id"],
            metric_type=metric_type,
            current_value=current_value,
            threshold_value=threshold_value,
            severity=severity,
            alert_id=alert.id,
        )

    logger.info(
        "vm_threshold_alert_created",
        vm=config["vm_name"],
        metric=metric_type,
        value=current_value,
        severity=severity,
    )

    return alert


async def check_expiry_alerts_job() -> None:
    """Check for upcoming expirations and generate alerts."""
    logger.info("expiry_alert_check_started")

    try:
        async for db in get_db_session():
            email_service = EmailNotificationService(db)

            # Get all enabled expiry configs
            result = await db.execute(
                select(CustomExpiryAlertConfig).where(CustomExpiryAlertConfig.is_enabled.is_(True))
            )
            configs = result.scalars().all()

            alerts_generated = 0
            now = datetime.utcnow()

            for config in configs:
                try:
                    # Skip snoozed configs
                    if config.snooze_until and config.snooze_until > now:
                        continue

                    days_until_expiry = (config.expiry_date - now).days

                    # Determine severity
                    if days_until_expiry <= config.critical_days_before:
                        severity = "critical"
                    elif days_until_expiry <= config.warning_days_before:
                        severity = "warning"
                    else:
                        continue  # No alert needed

                    # Check for existing active alert
                    existing = await db.execute(
                        select(CustomExpiryAlert).where(
                            CustomExpiryAlert.config_id == config.id,
                            CustomExpiryAlert.status == "active",
                        )
                    )
                    existing_alert = existing.scalar_one_or_none()

                    if existing_alert:
                        # Update existing alert
                        existing_alert.days_until_expiry = days_until_expiry
                        existing_alert.severity = severity
                        existing_alert.updated_at = now
                        await db.commit()
                    else:
                        # Create new alert
                        alert = CustomExpiryAlert(
                            config_id=config.id,
                            alert_type=config.alert_type,
                            resource_name=config.resource_name,
                            expiry_date=config.expiry_date,
                            days_until_expiry=days_until_expiry,
                            severity=severity,
                            status="active",
                        )
                        db.add(alert)
                        await db.commit()
                        await db.refresh(alert)
                        alerts_generated += 1

                        # Send email notification
                        notification_emails = config.notification_emails or []
                        if notification_emails:
                            await email_service.send_expiry_alert(
                                recipient_emails=notification_emails,
                                resource_name=config.resource_name,
                                resource_identifier=config.resource_identifier,
                                alert_type=config.alert_type,
                                expiry_date=config.expiry_date,
                                days_until_expiry=days_until_expiry,
                                severity=severity,
                                description=config.description,
                                alert_id=alert.id,
                            )

                except Exception as e:
                    logger.error(
                        "expiry_check_error",
                        resource=config.resource_name,
                        error=str(e),
                    )

            logger.info(
                "expiry_alert_check_completed",
                configs=len(configs),
                alerts=alerts_generated,
            )

    except Exception as e:
        logger.error("expiry_alert_job_failed", error=str(e))


async def check_pg_thresholds_job() -> None:
    """Check PostgreSQL Flexible Server thresholds and generate alerts."""
    logger.info("pg_threshold_check_started")

    try:
        async for db in get_db_session():
            alert_service = InfraAlertService(db)
            result = await alert_service.check_and_generate_pg_alerts()
            logger.info(
                "pg_threshold_check_completed",
                alerts_created=result.get("alerts_created", 0),
                errors=len(result.get("errors", [])),
            )
    except Exception as e:
        logger.error("pg_threshold_job_failed", error=str(e))


async def execute_alert_schedule_job(schedule_config_id: int) -> None:
    """Execute a persisted infra alert schedule configuration."""
    logger.info("alert_schedule_job_started", schedule_config_id=schedule_config_id)

    try:
        async for db in get_db_session():
            result = await db.execute(select(AlertScheduleConfig).where(AlertScheduleConfig.id == schedule_config_id))
            config = result.scalar_one_or_none()

            if config is None:
                logger.warning("alert_schedule_job_missing", schedule_config_id=schedule_config_id)
                break

            if not config.is_enabled:
                logger.info("alert_schedule_job_skipped", schedule=config.name, reason="disabled")
                config.next_run_at = None
                await db.commit()
                break

            unsupported_checks: list[str] = []
            if config.check_vm_thresholds:
                await check_vm_thresholds_job()
            if config.check_expiry_alerts:
                await check_expiry_alerts_job()
            if config.check_pg_thresholds:
                await check_pg_thresholds_job()
            if config.send_daily_digest:
                await send_daily_digest_job()
            if config.check_storage_thresholds:
                unsupported_checks.append("storage")
            if config.check_disk_thresholds:
                unsupported_checks.append("disk")

            config.last_run_at = datetime.utcnow()
            job = get_scheduler().get_job(_alert_schedule_job_id(config.id))
            config.next_run_at = _normalize_run_time(job.next_run_time if job else None)
            await db.commit()

            logger.info(
                "alert_schedule_job_completed",
                schedule=config.name,
                schedule_config_id=schedule_config_id,
                unsupported_checks=unsupported_checks,
            )
            break
    except Exception as exc:
        logger.error(
            "alert_schedule_job_failed",
            schedule_config_id=schedule_config_id,
            error=str(exc)[:300],
        )


async def send_daily_digest_job() -> None:
    """Send daily digest email with all active alerts."""
    logger.info("daily_digest_started")

    try:
        async for db in get_db_session():
            email_service = EmailNotificationService(db)

            # Get active VM threshold alerts
            vm_result = await db.execute(select(VMThresholdAlert).where(VMThresholdAlert.status == "active"))
            vm_alerts = vm_result.scalars().all()

            # Get active expiry alerts
            expiry_result = await db.execute(select(CustomExpiryAlert).where(CustomExpiryAlert.status == "active"))
            expiry_alerts = expiry_result.scalars().all()

            if not vm_alerts and not expiry_alerts:
                logger.info("daily_digest_skipped", reason="no_active_alerts")
                return

            # Get digest recipients from schedule config
            schedule_result = await db.execute(
                select(AlertScheduleConfig).where(
                    AlertScheduleConfig.send_daily_digest.is_(True),
                    AlertScheduleConfig.is_enabled.is_(True),
                )
            )
            schedule_configs = schedule_result.scalars().all()

            recipients = set()
            for config in schedule_configs:
                recipients.update(config.digest_recipients or [])

            if not recipients:
                # Fallback: use all unique notification emails from configs
                vm_config_result = await db.execute(select(VMThresholdAlertConfig.notification_emails))
                for row in vm_config_result.scalars().all():
                    if row:
                        recipients.update(row)

                expiry_config_result = await db.execute(select(CustomExpiryAlertConfig.notification_emails))
                for row in expiry_config_result.scalars().all():
                    if row:
                        recipients.update(row)

            if not recipients:
                logger.info("daily_digest_skipped", reason="no_recipients")
                return

            # Send digest
            vm_alert_data = [
                {
                    "vm_name": a.vm_name,
                    "metric_type": a.metric_type,
                    "current_value": a.current_value,
                    "severity": a.severity,
                }
                for a in vm_alerts
            ]

            expiry_alert_data = [
                {
                    "resource_name": a.resource_name,
                    "alert_type": a.alert_type,
                    "days_until_expiry": a.days_until_expiry,
                    "severity": a.severity,
                }
                for a in expiry_alerts
            ]

            await email_service.send_alert_digest(
                recipient_emails=list(recipients),
                vm_alerts=vm_alert_data,
                expiry_alerts=expiry_alert_data,
            )

            logger.info(
                "daily_digest_sent",
                vm_alerts=len(vm_alerts),
                expiry_alerts=len(expiry_alerts),
                recipients=len(recipients),
            )

    except Exception as e:
        logger.error("daily_digest_job_failed", error=str(e))


async def sync_azure_resources_job() -> None:
    """Sync Azure resources to local database inventory."""
    logger.info("azure_resource_sync_started")

    try:
        async for db in get_db_session():
            resource_service = AzureResourceService(db)

            # Use sync_all_resources_to_db for accurate power_state via individual VM fetch
            result = await resource_service.sync_all_resources_to_db()

            logger.info("azure_resource_sync_completed", totals=result.get("total_synced", 0))

    except Exception as e:
        logger.error("azure_resource_sync_failed", error=str(e))


async def sync_keyvault_data_job() -> None:
    """Sync Azure Key Vault vaults, secrets, keys, and certificates to PG."""
    logger.info("keyvault_data_sync_started")

    try:
        async for db in get_db_session():
            sync_service = KeyVaultSyncService(db)
            result = await sync_service.full_sync(triggered_by="scheduler")
            logger.info(
                "keyvault_data_sync_completed",
                vaults=result.get("vaults_synced", 0),
                secrets=result.get("secrets_synced", 0),
                keys=result.get("keys_synced", 0),
                certs=result.get("certificates_synced", 0),
                duration=result.get("duration_seconds", 0),
            )
    except Exception as e:
        logger.error("keyvault_data_sync_failed", error=str(e))


async def sync_env_cost_data_job() -> None:
    """Sync daily environment cost data from Azure Cost Management to PG."""
    logger.info("env_cost_data_sync_started")

    try:
        async for db in get_db_session():
            sync_service = EnvCostSyncService(db)
            result = await sync_service.full_sync(days=7, triggered_by="scheduler")
            logger.info(
                "env_cost_data_sync_completed",
                days_synced=result.get("days_synced", 0),
                envs_synced=result.get("environments_synced", 0),
                total_cost=result.get("total_cost", 0),
                duration=result.get("duration_seconds", 0),
            )
    except Exception as e:
        logger.error("env_cost_data_sync_failed", error=str(e))


async def sync_amortized_cost_job() -> None:
    """Sync amortized cost data from Azure Cost Management API to PostgreSQL."""
    logger.info("amortized_cost_sync_started")

    try:
        async for db in get_db_session():
            from app.services.amortized_cost_sync_service import AmortizedCostSyncService

            sync_service = AmortizedCostSyncService(db)
            # Sync 12 months to ensure all time-period filters have data available
            result = await sync_service.full_sync(months=12, triggered_by="scheduler")
            logger.info(
                "amortized_cost_sync_completed",
                months_synced=result.get("months_synced", 0),
                rows_synced=result.get("rows_synced", 0),
                total_cost=result.get("total_cost", 0),
                duration=result.get("duration_seconds", 0),
            )
    except Exception as e:
        logger.error("amortized_cost_sync_failed", error=str(e))


async def run_checksum_schedules_job() -> None:
    """Execute due checksum schedules."""
    logger.info("checksum_schedule_job_started")

    try:
        async for db in get_db_session():
            compliance_service = ComplianceService(db)

            now = datetime.utcnow()
            result = await db.execute(select(ChecksumScheduleConfig).where(ChecksumScheduleConfig.is_enabled.is_(True)))
            schedules = result.scalars().all()

            for schedule in schedules:
                if schedule.next_run_at and schedule.next_run_at > now:
                    logger.debug(
                        "checksum_schedule_not_due",
                        schedule=schedule.name,
                        next_run_at=str(schedule.next_run_at),
                        now=str(now),
                    )
                    continue

                logger.info(
                    "checksum_schedule_executing",
                    schedule=schedule.name,
                    module_type=schedule.module_type,
                    next_run_at=str(schedule.next_run_at),
                    now=str(now),
                )

                try:
                    # Execute checksum collection and comparison
                    await _execute_schedule_checksum(
                        db=db,
                        schedule=schedule,
                        compliance_service=compliance_service,
                    )

                    schedule.last_run_at = now
                    schedule.next_run_at = _compute_next_run_time(schedule, now)
                    await db.commit()

                except Exception as e:
                    await db.rollback()
                    logger.error(
                        "checksum_schedule_run_failed",
                        schedule_id=schedule.id,
                        schedule_name=schedule.name,
                        error=str(e),
                    )

    except Exception as e:
        logger.error("checksum_schedule_job_failed", error=str(e))


async def run_certificate_expiry_alerts_job() -> None:
    """Send the certificate expiry report for every enabled alert rule."""
    logger.info("certificate_expiry_alert_job_started")
    try:
        async for db in get_db_session():
            from app.services.certificate_automation_service import CertificateAutomationService

            result = await CertificateAutomationService(db).run_expiry_alerts(trigger="schedule")
            logger.info(
                "certificate_expiry_alert_job_finished",
                configs_evaluated=result.get("configs_evaluated", 0),
            )
    except Exception as e:
        logger.error("certificate_expiry_alert_job_failed", error=str(e)[:300])


async def run_certificate_auto_renewal_job() -> None:
    """Run every enabled auto-renewal schedule that is due."""
    logger.info("certificate_auto_renewal_job_started")
    try:
        async for db in get_db_session():
            from app.services.certificate_automation_service import CertificateAutomationService

            result = await CertificateAutomationService(db).run_auto_renewals(trigger="schedule")
            logger.info(
                "certificate_auto_renewal_job_finished",
                schedules_run=result.get("schedules_run", 0),
            )
    except Exception as e:
        logger.error("certificate_auto_renewal_job_failed", error=str(e)[:300])


async def _execute_schedule_checksum(
    db: AsyncSession,
    schedule: ChecksumScheduleConfig,
    compliance_service: ComplianceService,
) -> None:
    """Execute a single checksum schedule using native Python SDK.

    Supports both Synapse and AKS module types.  Uses the same
    Azure-SDK-based flow that powers the manual "Run Checksum" / "Run
    AKS Verification" buttons and ``_execute_checksum_schedule()`` inside
    the compliance service.
    """
    try:
        if schedule.module_type == "synapse":
            if not schedule.workspace_name:
                return
            sdk_result = await compliance_service.run_checksum_verification(
                workspace_name=schedule.workspace_name,
            )
        elif schedule.module_type == "aks":
            sdk_result = await compliance_service.run_aks_checksum(
                cluster_id=schedule.cluster_id or "",
                system=schedule.system or "attcc",
                environment=schedule.environment or "prod",
                namespaces=schedule.namespaces or None,
            )
        else:
            logger.warning(
                "unknown_schedule_module_type",
                module_type=schedule.module_type,
                schedule=schedule.name,
            )
            return

        logger.info(
            "checksum_schedule_verification_complete",
            schedule=schedule.name,
            module_type=schedule.module_type,
            workspace=schedule.workspace_name,
            run_id=sdk_result.get("run_id"),
            total=sdk_result.get("total_pipelines", 0),
            passed=sdk_result.get("passed", 0),
            failed=sdk_result.get("failed", 0),
        )

        # Send email report if recipients configured
        if schedule.notification_emails:
            run_id = sdk_result.get("run_id", "")
            if run_id:
                try:
                    await compliance_service.send_checksum_report(
                        run_id=run_id,
                        recipient_emails=list(schedule.notification_emails),
                    )
                    logger.info(
                        "checksum_schedule_email_sent",
                        schedule=schedule.name,
                        recipients=len(schedule.notification_emails),
                    )
                except Exception as e:
                    logger.error(
                        "checksum_email_failed",
                        schedule=schedule.name,
                        recipients=schedule.notification_emails,
                        error=str(e),
                    )
            else:
                logger.warning(
                    "checksum_schedule_no_run_id",
                    schedule=schedule.name,
                )

    except Exception as exc:
        logger.error(
            "checksum_schedule_verification_failed",
            schedule=schedule.name,
            workspace=schedule.workspace_name,
            error=str(exc)[:300],
        )


def _compute_next_run_time(schedule: ChecksumScheduleConfig, now: datetime) -> datetime:
    """Compute next run time based on schedule configuration.

    Returns a **naive UTC** datetime so it can be compared directly
    against ``datetime.utcnow()`` in ``run_checksum_schedules_job``.
    """
    if schedule.schedule_type == "cron" and schedule.cron_expression:
        try:
            tz = ZoneInfo(schedule.timezone or "UTC")
            trigger = CronTrigger.from_crontab(
                schedule.cron_expression,
                timezone=tz,
            )
            # Pass timezone-aware now so APScheduler can compute correctly
            now_aware = now.replace(tzinfo=UTC) if now.tzinfo is None else now
            next_time = trigger.get_next_fire_time(None, now_aware)
            if next_time is None:
                return now + timedelta(hours=24)
            # Convert to naive UTC for DB storage and comparison
            if next_time.tzinfo is not None:
                next_time = next_time.astimezone(UTC).replace(tzinfo=None)
            return next_time
        except Exception as e:
            logger.error("cron_parse_failed", cron=schedule.cron_expression, error=str(e))
            return now + timedelta(hours=24)
    else:
        # Interval-based
        hours = schedule.interval_hours or 24
        return now + timedelta(hours=hours)


# ── Manual Job Triggers ──────────────────────────────────────────────────


async def trigger_vm_threshold_check() -> dict[str, Any]:
    """Manually trigger VM threshold check."""
    await check_vm_thresholds_job()
    return {"status": "completed", "job": "vm_threshold_check"}


async def trigger_expiry_check() -> dict[str, Any]:
    """Manually trigger expiry alert check."""
    await check_expiry_alerts_job()
    return {"status": "completed", "job": "expiry_alert_check"}


async def trigger_daily_digest() -> dict[str, Any]:
    """Manually trigger daily digest."""
    await send_daily_digest_job()
    return {"status": "completed", "job": "daily_digest"}


async def trigger_resource_sync() -> dict[str, Any]:
    """Manually trigger Azure resource sync."""
    await sync_azure_resources_job()
    return {"status": "completed", "job": "azure_resource_sync"}


async def trigger_keyvault_sync() -> dict[str, Any]:
    """Manually trigger KeyVault data sync."""
    await sync_keyvault_data_job()
    return {"status": "completed", "job": "keyvault_data_sync"}


async def trigger_env_cost_sync() -> dict[str, Any]:
    """Manually trigger environment cost data sync."""
    await sync_env_cost_data_job()
    return {"status": "completed", "job": "env_cost_data_sync"}


def get_scheduler_status() -> dict[str, Any]:
    """Get current scheduler status and job information."""
    scheduler = get_scheduler()

    jobs = []
    for job in scheduler.get_jobs():
        next_run = job.next_run_time
        jobs.append(
            {
                "job_id": job.id,
                "name": job.name,
                "next_run_time": next_run.isoformat() if next_run else None,
                "trigger": str(job.trigger),
                "status": "running" if next_run else "paused",
            }
        )

    return {
        "scheduler_running": scheduler.running,
        "jobs": jobs,
        "job_count": len(jobs),
    }


# ── Environment Scaling Schedule Runner ───────────────────────────────


async def run_environment_schedules_job() -> None:
    """Execute due environment scaling schedules."""
    from app.models.database import EnvironmentExecutionHistory, EnvironmentSchedule
    from app.services.environment_scaling_service import get_environment_scaling_service

    try:
        async for db in get_db_session():
            now = datetime.utcnow()
            result = await db.execute(select(EnvironmentSchedule).where(EnvironmentSchedule.is_enabled.is_(True)))
            schedules = result.scalars().all()

            for schedule in schedules:
                if schedule.next_run_at and schedule.next_run_at > now:
                    continue

                if schedule.end_date and now > schedule.end_date:
                    schedule.is_enabled = False
                    await db.commit()
                    continue

                if schedule.start_date and now < schedule.start_date:
                    continue

                # Skip if there's already a running execution for this schedule
                running_check = await db.execute(
                    select(EnvironmentExecutionHistory.id)
                    .where(EnvironmentExecutionHistory.schedule_id == schedule.id)
                    .where(EnvironmentExecutionHistory.status == "running")
                    .limit(1)
                )
                if running_check.scalar_one_or_none() is not None:
                    logger.debug(
                        "environment_schedule_skipped_already_running",
                        schedule_id=schedule.id,
                        job_name=schedule.job_name,
                    )
                    continue

                # Update next_run_at BEFORE execution to prevent re-trigger
                schedule.next_run_at = _compute_env_schedule_next_run(schedule, now)
                await db.commit()

                logger.info(
                    "environment_schedule_executing",
                    schedule_id=schedule.id,
                    job_name=schedule.job_name,
                )

                try:
                    service = get_environment_scaling_service(db)
                    await service.execute_scheduled_job(schedule.id)
                    await db.commit()
                except Exception as exc:
                    await db.rollback()
                    logger.error(
                        "environment_schedule_run_failed",
                        schedule_id=schedule.id,
                        error=str(exc)[:200],
                    )

    except Exception as exc:
        logger.error("environment_schedule_job_failed", error=str(exc)[:200])


def _compute_env_schedule_next_run(
    schedule,
    now: datetime,
) -> datetime | None:
    """Compute the next run time for an environment schedule in UTC."""
    from zoneinfo import ZoneInfo

    if schedule.schedule_type == "one_time":
        return None

    # Use the schedule's timezone for cron computation
    tz = ZoneInfo(schedule.timezone) if schedule.timezone else UTC

    if schedule.schedule_type == "cron" and schedule.cron_expression:
        try:
            trigger = CronTrigger.from_crontab(schedule.cron_expression, timezone=tz)
            next_fire = trigger.get_next_fire_time(None, now.replace(tzinfo=UTC))
            if next_fire and next_fire.tzinfo:
                return next_fire.astimezone(UTC).replace(tzinfo=None)
            return next_fire
        except Exception:
            return now + timedelta(hours=24)

    intervals = {
        "daily": timedelta(days=1),
        "weekly": timedelta(weeks=1),
        "monthly": timedelta(days=30),
    }
    delta = intervals.get(schedule.schedule_type, timedelta(days=1))
    return now + delta
