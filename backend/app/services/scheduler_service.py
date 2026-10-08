"""
Background Scheduler Service — Periodic Alert Checking and Notification Dispatch.

Uses APScheduler for:
- Periodic VM metric threshold checks
- Daily expiry alert generation
- Email digest delivery
- Azure resource inventory sync
"""

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cron import cron_trigger_from_crontab
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
    await realign_env_schedule_next_runs()
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

    # Certificate automation ticks hourly in every worker of every replica; a
    # per-day claim row in the service lets exactly one of them run each config.
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

    # An alert schedule edit reaches only the worker that served the request;
    # without this every other worker keeps firing the old trigger until restart.
    scheduler.add_job(
        sync_alert_schedule_jobs,
        IntervalTrigger(minutes=1),
        id="alert_schedule_resync",
        name="Alert Schedule Resync",
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
        # Standard crontab day-of-week (0=Sun); APScheduler's own parser counts from Monday.
        return cron_trigger_from_crontab(config.cron_expression, timezone=UTC)
    return IntervalTrigger(minutes=max(config.interval_minutes or 1, 1), timezone=UTC)


def _alert_schedule_min_gap(config: AlertScheduleConfig) -> timedelta:
    """Half the shortest spacing between two real runs of a schedule.

    Every worker on every replica fires each schedule: cron firings land within
    seconds of each other, interval firings at each worker's start-up offset.
    Anything closer than half the schedule's own period is one of those copies.
    """
    period = timedelta(minutes=max(config.interval_minutes or 1, 1))
    if config.schedule_type == "cron" and config.cron_expression:
        try:
            trigger = cron_trigger_from_crontab(config.cron_expression, timezone=UTC)
            fire = trigger.get_next_fire_time(None, datetime.now(UTC))
            spacings = []
            for _ in range(12):
                following = trigger.get_next_fire_time(fire, fire) if fire else None
                if following is None:
                    break
                spacings.append(following - fire)
                fire = following
            period = min(spacings) if spacings else timedelta(minutes=1)
        except Exception:
            period = timedelta(minutes=1)
    return max(period / 2, timedelta(seconds=30))


async def _claim_alert_schedule(db: AsyncSession, config: AlertScheduleConfig, now: datetime) -> bool:
    """Stamp last_run_at atomically so exactly one worker runs each firing."""
    claimed = await db.execute(
        update(AlertScheduleConfig)
        .where(
            AlertScheduleConfig.id == config.id,
            AlertScheduleConfig.is_enabled.is_(True),
            or_(
                AlertScheduleConfig.last_run_at.is_(None),
                AlertScheduleConfig.last_run_at <= now - _alert_schedule_min_gap(config),
            ),
        )
        .values(last_run_at=now)
        .returning(AlertScheduleConfig.id)
        .execution_options(synchronize_session=False)
    )
    if claimed.scalar_one_or_none() is None:
        await db.rollback()
        return False
    await db.commit()
    return True


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
        replaced = 0

        for config in configs:
            job_id = _alert_schedule_job_id(config.id)
            job = scheduler.get_job(job_id)

            if not config.is_enabled:
                if job:
                    scheduler.remove_job(job_id)
                config.next_run_at = None
                continue

            try:
                trigger = _build_alert_schedule_trigger(config)
            except Exception as exc:
                logger.warning("alert_schedule_trigger_invalid", schedule_config_id=config.id, error=str(exc)[:200])
                if job:
                    active_job_ids.add(job_id)
                continue

            # This runs every minute; re-adding an unchanged job would restart
            # its interval so it never fired, so only a changed trigger is replaced.
            if job is None or str(job.trigger) != str(trigger):
                replaced += 1
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
            else:
                if job.name != config.name:
                    job.modify(name=config.name)
                if config.next_run_at is None:
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
        if replaced or removed:
            logger.info("alert_schedule_jobs_synced", synced=synced, replaced=replaced, removed=removed)
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

            # Each check emails on what it finds, and copies running side by side
            # each see "no alert yet" — so they would all create one and all send.
            if not await _claim_alert_schedule(db, config, datetime.utcnow()):
                logger.info("alert_schedule_job_skipped", schedule=config.name, reason="run_by_another_worker")
                break
            await db.refresh(config)

            unsupported_checks: list[str] = []
            if config.check_vm_thresholds:
                await check_vm_thresholds_job()
            if config.check_expiry_alerts:
                await check_expiry_alerts_job()
            if config.check_pg_thresholds:
                await check_pg_thresholds_job()
            if config.send_daily_digest:
                await send_daily_digest_job(digest_recipients=list(config.digest_recipients or []))
            if config.check_storage_thresholds:
                unsupported_checks.append("storage")
            if config.check_disk_thresholds:
                unsupported_checks.append("disk")

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


async def send_daily_digest_job(digest_recipients: list[str] | None = None) -> None:
    """Send the digest of all active alerts.

    A schedule passes its own recipients. Pooling every digest schedule's list
    instead meant each schedule mailed everyone, once per schedule.
    """
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

            recipients: list[str] = []
            if digest_recipients is not None:
                recipients.extend(digest_recipients)
            else:
                schedule_result = await db.execute(
                    select(AlertScheduleConfig).where(
                        AlertScheduleConfig.send_daily_digest.is_(True),
                        AlertScheduleConfig.is_enabled.is_(True),
                    )
                )
                for config in schedule_result.scalars().all():
                    recipients.extend(config.digest_recipients or [])

            if not recipients:
                # Fallback: use all unique notification emails from configs
                vm_config_result = await db.execute(select(VMThresholdAlertConfig.notification_emails))
                for row in vm_config_result.scalars().all():
                    if row:
                        recipients.extend(row)

                expiry_config_result = await db.execute(select(CustomExpiryAlertConfig.notification_emails))
                for row in expiry_config_result.scalars().all():
                    if row:
                        recipients.extend(row)

            # "A@att.com" and "a@att.com " are one inbox; the first spelling is kept.
            by_inbox: dict[str, str] = {}
            for email in recipients:
                if isinstance(email, str) and email.strip():
                    by_inbox.setdefault(email.strip().lower(), email.strip())
            unique_recipients = list(by_inbox.values())
            if not unique_recipients:
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
                recipient_emails=unique_recipients,
                vm_alerts=vm_alert_data,
                expiry_alerts=expiry_alert_data,
            )

            logger.info(
                "daily_digest_sent",
                vm_alerts=len(vm_alerts),
                expiry_alerts=len(expiry_alerts),
                recipients=len(unique_recipients),
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
                "amortized_cost_sync_finished",
                status=result.get("status", "unknown"),
                partial_failures=result.get("partial_failures", 0),
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
                schedule_id, schedule_name = schedule.id, schedule.name
                if schedule.next_run_at and schedule.next_run_at > now:
                    logger.debug(
                        "checksum_schedule_not_due",
                        schedule=schedule_name,
                        next_run_at=str(schedule.next_run_at),
                        now=str(now),
                    )
                    continue

                try:
                    if not await _claim_checksum_schedule(db, schedule, now):
                        logger.info("checksum_schedule_claimed_elsewhere", schedule=schedule_name)
                        continue

                    logger.info(
                        "checksum_schedule_executing",
                        schedule=schedule_name,
                        module_type=schedule.module_type,
                        now=str(now),
                    )
                    await _execute_schedule_checksum(
                        db=db,
                        schedule=schedule,
                        compliance_service=compliance_service,
                    )

                except Exception as e:
                    await db.rollback()
                    logger.error(
                        "checksum_schedule_run_failed",
                        schedule_id=schedule_id,
                        schedule_name=schedule_name,
                        error=str(e),
                    )

    except Exception as e:
        logger.error("checksum_schedule_job_failed", error=str(e))


async def _claim_checksum_schedule(db: AsyncSession, schedule: ChecksumScheduleConfig, now: datetime) -> bool:
    """Advance next_run_at atomically so only one replica runs a due schedule."""
    claimed = await db.execute(
        update(ChecksumScheduleConfig)
        .where(
            ChecksumScheduleConfig.id == schedule.id,
            ChecksumScheduleConfig.is_enabled.is_(True),
            or_(ChecksumScheduleConfig.next_run_at.is_(None), ChecksumScheduleConfig.next_run_at <= now),
        )
        .values(last_run_at=now, next_run_at=_compute_next_run_time(schedule, now))
        .returning(ChecksumScheduleConfig.id)
        .execution_options(synchronize_session=False)
    )
    if claimed.scalar_one_or_none() is None:
        await db.rollback()
        return False
    await db.commit()
    # Pick up edits made since this tick loaded the schedule list.
    await db.refresh(schedule)
    return True


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
            renewed_collections = {
                r["collection_id"]
                for r in result.get("results", [])
                if r.get("renewed") and r.get("collection_id") is not None
            }
            if renewed_collections:
                from app.services.certificate_sync_service import CertificateSyncService

                for collection_id in sorted(renewed_collections):
                    try:
                        await CertificateSyncService(db).sync_collection(collection_id, triggered_by="auto_renewal")
                    except Exception as exc:  # noqa: BLE001 - the next page visit refreshes it anyway
                        await db.rollback()
                        logger.warning(
                            "certificate_auto_renewal_resync_failed",
                            collection_id=collection_id,
                            error=str(exc)[:200],
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
            trigger = cron_trigger_from_crontab(
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


# Runs launched by the runner. Each replica runs at most this many at once,
# and never two in the same cluster/namespace (they would scale against each
# other); a run waiting for its namespace does not hold one of the slots.
ENV_SCHEDULE_CONCURRENCY = 5
_env_run_tasks: set[asyncio.Task] = set()
_env_run_guards: dict[str, Any] = {}


def _env_run_slot_and_lock(cluster_id: str, namespace: str) -> tuple[asyncio.Semaphore, asyncio.Lock]:
    # Created per event loop: asyncio primitives are bound to the loop that uses them.
    loop = asyncio.get_running_loop()
    if _env_run_guards.get("loop") is not loop:
        _env_run_guards.clear()
        _env_run_guards.update(loop=loop, slots=asyncio.Semaphore(ENV_SCHEDULE_CONCURRENCY), locks={})
    locks: dict[tuple[str, str], asyncio.Lock] = _env_run_guards["locks"]
    return _env_run_guards["slots"], locks.setdefault((cluster_id, namespace), asyncio.Lock())


def _launch_env_schedule_run(schedule_id: int, cluster_id: str, namespace: str) -> asyncio.Task:
    task = asyncio.create_task(_run_env_schedule(schedule_id, cluster_id, namespace))
    _env_run_tasks.add(task)
    task.add_done_callback(_env_run_tasks.discard)
    return task


async def _run_env_schedule(schedule_id: int, cluster_id: str, namespace: str) -> None:
    """One claimed schedule, on its own DB session, under the namespace lock."""
    from app.services.environment_scaling_service import get_environment_scaling_service

    slots, namespace_lock = _env_run_slot_and_lock(cluster_id, namespace)
    async with namespace_lock, slots:
        try:
            async for db in get_db_session():
                await get_environment_scaling_service(db).execute_scheduled_job(schedule_id)
        except Exception as exc:
            logger.error("environment_schedule_run_failed", schedule_id=schedule_id, error=str(exc)[:200])


async def run_environment_schedules_job() -> None:
    """Claim due environment schedules and launch each run in its own task.

    The tick only claims and launches, so a long startup sequence no longer
    holds back every other schedule on this replica until it finishes.
    """
    from app.models.database import EnvironmentExecutionHistory, EnvironmentSchedule
    from app.services.environment_scaling_service import get_environment_scaling_service

    try:
        async for db in get_db_session():
            # A run whose replica died would otherwise keep its namespace "busy" forever.
            await get_environment_scaling_service(db).sweep_abandoned_executions()

            now = datetime.utcnow()
            result = await db.execute(select(EnvironmentSchedule).where(EnvironmentSchedule.is_enabled.is_(True)))
            schedules = result.scalars().all()

            for schedule in schedules:
                if schedule.next_run_at and schedule.next_run_at > now:
                    continue

                # Start and end dates are wall-clock times in the schedule's timezone.
                end_utc = _schedule_bound_utc(schedule.end_date, schedule.timezone)
                if end_utc and now > end_utc:
                    schedule.is_enabled = False
                    await db.commit()
                    continue

                start_utc = _schedule_bound_utc(schedule.start_date, schedule.timezone)
                if start_utc and now < start_utc:
                    continue

                # Something already running in this namespace — a sequence started
                # by hand, or another schedule — goes first. The schedule stays due
                # and starts on a later tick once the namespace is free.
                busy = (
                    await db.execute(
                        select(EnvironmentExecutionHistory.id)
                        .where(
                            EnvironmentExecutionHistory.cluster_id == schedule.cluster_id,
                            EnvironmentExecutionHistory.namespace == schedule.namespace,
                            EnvironmentExecutionHistory.status == "running",
                        )
                        .limit(1)
                    )
                ).scalar_one_or_none()
                if busy is not None:
                    logger.info(
                        "environment_schedule_waiting_for_namespace",
                        schedule_id=schedule.id,
                        job_name=schedule.job_name,
                        running_execution_id=busy,
                    )
                    continue

                # Every replica runs this job, so only an atomic claim keeps a
                # due run to one replica.
                if not await _claim_env_schedule(db, schedule, now):
                    logger.info("environment_schedule_claimed_elsewhere", schedule_id=schedule.id)
                    continue

                logger.info(
                    "environment_schedule_launched",
                    schedule_id=schedule.id,
                    job_name=schedule.job_name,
                )
                _launch_env_schedule_run(schedule.id, schedule.cluster_id, schedule.namespace)

    except Exception as exc:
        logger.error("environment_schedule_job_failed", error=str(exc)[:200])


async def realign_env_schedule_next_runs() -> int:
    """Recompute the stored next run of enabled environment schedules.

    Stored values can be wrong from earlier releases: cron read the
    day-of-week from Monday ("1-5" ran Tue–Sat), daily/weekly/monthly were
    "now + 1/7/30 days" and drifted off their start time, and start dates were
    treated as UTC rather than the schedule's timezone. A future next run is
    recomputed with today's rules; one already due is left to the runner.
    Idempotent: a correct value recomputes to itself. Each move is logged.
    """
    from app.models.database import EnvironmentSchedule
    from app.services.environment_scaling_service import next_schedule_run

    changed = 0
    try:
        async for db in get_db_session():
            now = datetime.utcnow()
            rows = (
                (await db.execute(select(EnvironmentSchedule).where(EnvironmentSchedule.is_enabled.is_(True))))
                .scalars()
                .all()
            )
            for schedule in rows:
                if not schedule.next_run_at or schedule.next_run_at <= now:
                    continue
                try:
                    corrected = next_schedule_run(schedule, now)
                except Exception:
                    continue  # invalid cron/timezone: leave it for someone to fix
                if corrected and corrected != schedule.next_run_at:
                    logger.warning(
                        "environment_schedule_next_run_realigned",
                        schedule_id=schedule.id,
                        job_name=schedule.job_name,
                        schedule_type=schedule.schedule_type,
                        cron_expression=schedule.cron_expression,
                        timezone=schedule.timezone,
                        previous_next_run_utc=schedule.next_run_at.isoformat(),
                        corrected_next_run_utc=corrected.isoformat(),
                    )
                    schedule.next_run_at = corrected
                    changed += 1
            if changed:
                await db.commit()
    except Exception as exc:
        logger.error("environment_schedule_realign_failed", error=str(exc)[:200])
    return changed


async def _claim_env_schedule(db: AsyncSession, schedule, now: datetime) -> bool:
    """Advance next_run_at atomically so only one replica runs a due environment schedule."""
    from app.models.database import EnvironmentSchedule

    claimed = await db.execute(
        update(EnvironmentSchedule)
        .where(
            EnvironmentSchedule.id == schedule.id,
            EnvironmentSchedule.is_enabled.is_(True),
            or_(EnvironmentSchedule.next_run_at.is_(None), EnvironmentSchedule.next_run_at <= now),
        )
        # A one-time schedule has no next run, and a NULL next_run_at reads as
        # due — without disabling it here it re-ran every minute.
        .values(
            next_run_at=_compute_env_schedule_next_run(schedule, now),
            is_enabled=schedule.schedule_type != "one_time",
        )
        .returning(EnvironmentSchedule.id)
        .execution_options(synchronize_session=False)
    )
    if claimed.scalar_one_or_none() is None:
        await db.rollback()
        return False
    await db.commit()
    await db.refresh(schedule)
    return True


def _compute_env_schedule_next_run(
    schedule,
    now: datetime,
) -> datetime | None:
    """The run after the one just claimed (naive UTC); None for one-time schedules."""
    from app.services.environment_scaling_service import next_schedule_run

    if schedule.schedule_type == "one_time":
        return None
    try:
        nxt = next_schedule_run(schedule, now + timedelta(seconds=1))
    except Exception:
        nxt = None
    # A NULL next_run_at reads as due: never leave a recurring schedule without one.
    return nxt or now + timedelta(hours=24)


def _schedule_bound_utc(value: datetime | None, tz_name: str | None) -> datetime | None:
    """A start/end date (wall clock in the schedule's timezone) in naive UTC."""
    from app.services.environment_scaling_service import local_to_utc

    try:
        return local_to_utc(value, tz_name)
    except Exception:
        return value
