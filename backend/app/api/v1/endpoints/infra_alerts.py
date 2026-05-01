"""
Infrastructure Alert API Endpoints.

Full management interface for infrastructure alerts:
- VM Threshold Alerts (CPU, Memory, Disk)
- Custom Expiry Alerts (MechID, Certificate, AAF, Database, ITServices Domain)
"""

import traceback
from datetime import datetime

import structlog
from fastapi import APIRouter, Body, Depends, HTTPException, Path, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user, require_role
from app.core.database import get_db
from app.models.auth import UserContext, UserRole
from app.services.infra_alert_service import InfraAlertService

logger = structlog.get_logger(__name__)
router = APIRouter()


async def _get_service(db: AsyncSession = Depends(get_db)) -> InfraAlertService:
    return InfraAlertService(db)


# ── Request/Response Models ────────────────────────────────────────────


class CreateVMThresholdConfigRequest(BaseModel):
    """Request to create a VM threshold alert configuration."""

    subscription_id: str = Field(..., description="Azure subscription ID")
    resource_group: str = Field(..., description="Resource group name")
    vm_name: str = Field(..., description="Virtual machine name")
    vm_id: str = Field(..., description="Full Azure resource ID of the VM")
    cpu_warning_threshold: float = Field(default=70.0, ge=0, le=100)
    cpu_critical_threshold: float = Field(default=90.0, ge=0, le=100)
    memory_warning_threshold: float = Field(default=75.0, ge=0, le=100)
    memory_critical_threshold: float = Field(default=90.0, ge=0, le=100)
    disk_warning_threshold: float = Field(default=80.0, ge=0, le=100)
    disk_critical_threshold: float = Field(default=95.0, ge=0, le=100)
    notification_emails: list[str] = Field(default=[])


class UpdateVMThresholdConfigRequest(BaseModel):
    """Request to update a VM threshold alert configuration."""

    cpu_warning_threshold: float | None = Field(default=None, ge=0, le=100)
    cpu_critical_threshold: float | None = Field(default=None, ge=0, le=100)
    memory_warning_threshold: float | None = Field(default=None, ge=0, le=100)
    memory_critical_threshold: float | None = Field(default=None, ge=0, le=100)
    disk_warning_threshold: float | None = Field(default=None, ge=0, le=100)
    disk_critical_threshold: float | None = Field(default=None, ge=0, le=100)
    is_enabled: bool | None = None
    notification_emails: list[str] | None = None
    snooze_until: datetime | None = None


class CreateExpiryConfigRequest(BaseModel):
    """Request to create a custom expiry alert configuration."""

    alert_type: str = Field(
        ...,
        description="Type: mech_id, certificate, aaf_account, database_account, itservices_domain",
    )
    resource_name: str = Field(..., description="Name of the resource to monitor")
    resource_identifier: str = Field(..., description="Unique identifier for the resource")
    expiry_date: datetime = Field(..., description="Expiry date of the resource")
    description: str | None = Field(default=None)
    warning_days_before: int = Field(default=30, ge=1)
    critical_days_before: int = Field(default=7, ge=1)
    notification_emails: list[str] = Field(default=[])
    metadata: dict | None = Field(default=None)


class UpdateExpiryConfigRequest(BaseModel):
    """Request to update a custom expiry alert configuration."""

    resource_name: str | None = None
    description: str | None = None
    expiry_date: datetime | None = None
    warning_days_before: int | None = Field(default=None, ge=1)
    critical_days_before: int | None = Field(default=None, ge=1)
    is_enabled: bool | None = None
    notification_emails: list[str] | None = None
    snooze_until: datetime | None = None
    metadata: dict | None = None


class AcknowledgeAlertRequest(BaseModel):
    """Request to acknowledge an alert."""

    pass  # User context provides the acknowledger


class ResolveAlertRequest(BaseModel):
    """Request to resolve an alert."""

    resolution_notes: str | None = Field(default=None, description="Notes about the resolution")


# ── Storage Alert Request/Response Models ──────────────────────────────


class CreateStorageAlertConfigRequest(BaseModel):
    """Request to create a storage alert configuration."""

    subscription_id: str = Field(..., description="Azure subscription ID")
    resource_group: str = Field(..., description="Resource group name")
    account_name: str = Field(..., description="Storage account name")
    account_id: str = Field(..., description="Full Azure resource ID of the storage account")
    capacity_warning_gb: float = Field(default=100.0, ge=0)
    capacity_critical_gb: float = Field(default=500.0, ge=0)
    transactions_warning: int = Field(default=100000, ge=0)
    transactions_critical: int = Field(default=500000, ge=0)
    egress_warning_gb: float = Field(default=50.0, ge=0)
    egress_critical_gb: float = Field(default=200.0, ge=0)
    notification_emails: list[str] = Field(default=[])


class UpdateStorageAlertConfigRequest(BaseModel):
    """Request to update a storage alert configuration."""

    capacity_warning_gb: float | None = Field(default=None, ge=0)
    capacity_critical_gb: float | None = Field(default=None, ge=0)
    transactions_warning: int | None = Field(default=None, ge=0)
    transactions_critical: int | None = Field(default=None, ge=0)
    egress_warning_gb: float | None = Field(default=None, ge=0)
    egress_critical_gb: float | None = Field(default=None, ge=0)
    is_enabled: bool | None = None
    notification_emails: list[str] | None = None
    snooze_until: datetime | None = None


# ── PG Flex Server Alert Request/Response Models ───────────────────────


class CreatePGFlexConfigRequest(BaseModel):
    """Request to create a PG Flexible Server alert configuration."""

    subscription_id: str = Field(..., description="Azure subscription ID")
    resource_group: str = Field(..., description="Resource group name")
    server_name: str = Field(..., description="PostgreSQL Flexible Server name")
    server_id: str = Field(..., description="Full Azure resource ID of the server")
    cpu_warning_threshold: float = Field(default=70.0, ge=0, le=100)
    cpu_critical_threshold: float = Field(default=90.0, ge=0, le=100)
    memory_warning_threshold: float = Field(default=75.0, ge=0, le=100)
    memory_critical_threshold: float = Field(default=90.0, ge=0, le=100)
    storage_warning_threshold: float = Field(default=80.0, ge=0, le=100)
    storage_critical_threshold: float = Field(default=95.0, ge=0, le=100)
    notification_emails: list[str] = Field(default=[])


class UpdatePGFlexConfigRequest(BaseModel):
    """Request to update a PG Flexible Server alert configuration."""

    cpu_warning_threshold: float | None = Field(default=None, ge=0, le=100)
    cpu_critical_threshold: float | None = Field(default=None, ge=0, le=100)
    memory_warning_threshold: float | None = Field(default=None, ge=0, le=100)
    memory_critical_threshold: float | None = Field(default=None, ge=0, le=100)
    storage_warning_threshold: float | None = Field(default=None, ge=0, le=100)
    storage_critical_threshold: float | None = Field(default=None, ge=0, le=100)
    is_enabled: bool | None = None
    notification_emails: list[str] | None = None
    snooze_until: datetime | None = None


class CreateAlertScheduleConfigRequest(BaseModel):
    """Request to create a persisted infra alert schedule configuration."""

    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = None
    schedule_type: str = Field(default="interval", pattern="^(interval|cron)$")
    interval_minutes: int = Field(default=15, ge=1, le=10080)
    cron_expression: str | None = Field(default=None, max_length=100)
    check_vm_thresholds: bool = True
    check_storage_thresholds: bool = True
    check_disk_thresholds: bool = True
    check_expiry_alerts: bool = True
    check_pg_thresholds: bool = True
    send_daily_digest: bool = True
    digest_time_utc: str = Field(default="08:00", pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    digest_recipients: list[str] = Field(default=[])
    is_enabled: bool = True


class UpdateAlertScheduleConfigRequest(BaseModel):
    """Request to update a persisted infra alert schedule configuration."""

    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    schedule_type: str | None = Field(default=None, pattern="^(interval|cron)$")
    interval_minutes: int | None = Field(default=None, ge=1, le=10080)
    cron_expression: str | None = Field(default=None, max_length=100)
    check_vm_thresholds: bool | None = None
    check_storage_thresholds: bool | None = None
    check_disk_thresholds: bool | None = None
    check_expiry_alerts: bool | None = None
    check_pg_thresholds: bool | None = None
    send_daily_digest: bool | None = None
    digest_time_utc: str | None = Field(default=None, pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    digest_recipients: list[str] | None = None
    is_enabled: bool | None = None


# ── Alert Summary / Dashboard ──────────────────────────────────────────


@router.get(
    "/summary",
    summary="Get alert summary dashboard",
    description="Returns summary counts of all active alerts by type and severity",
)
async def get_alert_summary(
    user: UserContext = Depends(get_current_user),
    service: InfraAlertService = Depends(_get_service),
) -> dict:
    """Get summary of all infrastructure alerts."""
    try:
        return await service.get_alert_summary()
    except Exception as e:
        logger.warning("get_alert_summary_db_error", error=str(e))
        return {"error": "Database temporarily unavailable", "total_active_alerts": 0}


@router.get(
    "/scheduler/configs",
    summary="List persisted alert schedule configurations",
    description="Returns DB-backed infra alert schedule configurations used for scheduler planning",
)
async def list_alert_schedule_configs(
    user: UserContext = Depends(require_role(UserRole.ADMIN)),
    service: InfraAlertService = Depends(_get_service),
) -> list[dict]:
    """List persisted infra alert schedule configurations."""
    try:
        return await service.list_alert_schedule_configs()
    except Exception as e:
        logger.warning("list_alert_schedule_configs_db_error", error=str(e))
        return JSONResponse(status_code=200, content=[])


@router.post(
    "/scheduler/configs",
    summary="Create persisted alert schedule configuration",
    description="Create a new DB-backed infra alert schedule configuration",
)
async def create_alert_schedule_config(
    request: CreateAlertScheduleConfigRequest = Body(...),
    user: UserContext = Depends(require_role(UserRole.WRITE)),
    service: InfraAlertService = Depends(_get_service),
) -> dict:
    """Create a persisted infra alert schedule configuration."""
    result = await service.create_alert_schedule_config(
        name=request.name,
        created_by=user.email or user.user_id,
        description=request.description,
        schedule_type=request.schedule_type,
        interval_minutes=request.interval_minutes,
        cron_expression=request.cron_expression,
        check_vm_thresholds=request.check_vm_thresholds,
        check_storage_thresholds=request.check_storage_thresholds,
        check_disk_thresholds=request.check_disk_thresholds,
        check_expiry_alerts=request.check_expiry_alerts,
        check_pg_thresholds=request.check_pg_thresholds,
        send_daily_digest=request.send_daily_digest,
        digest_time_utc=request.digest_time_utc,
        digest_recipients=request.digest_recipients,
        is_enabled=request.is_enabled,
    )
    try:
        from app.services.scheduler_service import sync_alert_schedule_jobs

        await sync_alert_schedule_jobs()
    except Exception as e:
        logger.warning("sync_alert_schedule_jobs_after_create_failed", error=str(e))
    return result


@router.put(
    "/scheduler/configs/{config_id}",
    summary="Update persisted alert schedule configuration",
    description="Update an existing DB-backed infra alert schedule configuration",
)
async def update_alert_schedule_config(
    config_id: int = Path(..., description="Configuration ID"),
    request: UpdateAlertScheduleConfigRequest = Body(...),
    user: UserContext = Depends(require_role(UserRole.WRITE)),
    service: InfraAlertService = Depends(_get_service),
) -> dict:
    """Update a persisted infra alert schedule configuration."""
    updates = request.model_dump(exclude_none=True)
    result = await service.update_alert_schedule_config(config_id, **updates)
    try:
        from app.services.scheduler_service import sync_alert_schedule_jobs

        await sync_alert_schedule_jobs()
    except Exception as e:
        logger.warning("sync_alert_schedule_jobs_after_update_failed", error=str(e))
    return result


@router.delete(
    "/scheduler/configs/{config_id}",
    summary="Delete persisted alert schedule configuration",
    description="Delete a DB-backed infra alert schedule configuration",
)
async def delete_alert_schedule_config(
    config_id: int = Path(..., description="Configuration ID"),
    user: UserContext = Depends(require_role(UserRole.ADMIN)),
    service: InfraAlertService = Depends(_get_service),
) -> dict:
    """Delete a persisted infra alert schedule configuration."""
    result = await service.delete_alert_schedule_config(config_id)
    try:
        from app.services.scheduler_service import sync_alert_schedule_jobs

        await sync_alert_schedule_jobs()
    except Exception as e:
        logger.warning("sync_alert_schedule_jobs_after_delete_failed", error=str(e))
    return result


# ── VM Threshold Alert Configuration ───────────────────────────────────


@router.get(
    "/vm-thresholds/configs",
    summary="List VM threshold alert configurations",
    description="Returns all VM threshold alert configurations",
)
async def list_vm_threshold_configs(
    subscription_id: str | None = Query(default=None, description="Filter by subscription"),
    is_enabled: bool | None = Query(default=None, description="Filter by enabled status"),
    user: UserContext = Depends(get_current_user),
    service: InfraAlertService = Depends(_get_service),
) -> list[dict]:
    """List VM threshold alert configurations."""
    try:
        return await service.list_vm_threshold_configs(
            subscription_id=subscription_id,
            is_enabled=is_enabled,
        )
    except Exception as e:
        logger.warning("list_vm_threshold_configs_db_error", error=str(e))
        return JSONResponse(status_code=200, content=[])


@router.post(
    "/vm-thresholds/configs",
    summary="Create VM threshold alert configuration",
    description="Create a new VM threshold alert configuration",
)
async def create_vm_threshold_config(
    request: CreateVMThresholdConfigRequest = Body(...),
    user: UserContext = Depends(require_role(UserRole.WRITE)),
    service: InfraAlertService = Depends(_get_service),
) -> dict:
    """Create a VM threshold alert configuration."""
    return await service.create_vm_threshold_config(
        subscription_id=request.subscription_id,
        resource_group=request.resource_group,
        vm_name=request.vm_name,
        vm_id=request.vm_id,
        created_by=user.email or user.user_id,
        cpu_warning=request.cpu_warning_threshold,
        cpu_critical=request.cpu_critical_threshold,
        memory_warning=request.memory_warning_threshold,
        memory_critical=request.memory_critical_threshold,
        disk_warning=request.disk_warning_threshold,
        disk_critical=request.disk_critical_threshold,
        notification_emails=request.notification_emails,
    )


@router.put(
    "/vm-thresholds/configs/{config_id}",
    summary="Update VM threshold alert configuration",
    description="Update an existing VM threshold alert configuration",
)
async def update_vm_threshold_config(
    config_id: int = Path(..., description="Configuration ID"),
    request: UpdateVMThresholdConfigRequest = Body(...),
    user: UserContext = Depends(require_role(UserRole.WRITE)),
    service: InfraAlertService = Depends(_get_service),
) -> dict:
    """Update a VM threshold alert configuration."""
    updates = request.model_dump(exclude_none=True)
    return await service.update_vm_threshold_config(config_id, **updates)


@router.delete(
    "/vm-thresholds/configs/{config_id}",
    summary="Delete VM threshold alert configuration",
    description="Delete a VM threshold alert configuration",
)
async def delete_vm_threshold_config(
    config_id: int = Path(..., description="Configuration ID"),
    user: UserContext = Depends(require_role(UserRole.ADMIN)),
    service: InfraAlertService = Depends(_get_service),
) -> dict:
    """Delete a VM threshold alert configuration."""
    return await service.delete_vm_threshold_config(config_id)


# ── VM Threshold Alerts ────────────────────────────────────────────────


@router.get(
    "/vm-thresholds/alerts",
    summary="List VM threshold alerts",
    description="Returns active and historical VM threshold alerts",
)
async def list_vm_threshold_alerts(
    status: str | None = Query(default=None, description="Filter by status: active, acknowledged, resolved"),
    severity: str | None = Query(default=None, description="Filter by severity: warning, critical"),
    limit: int = Query(default=100, ge=1, le=500),
    user: UserContext = Depends(get_current_user),
    service: InfraAlertService = Depends(_get_service),
) -> list[dict]:
    """List VM threshold alerts."""
    try:
        return await service.list_vm_threshold_alerts(
            status=status,
            severity=severity,
            limit=limit,
        )
    except Exception as e:
        logger.warning("list_vm_threshold_alerts_db_error", error=str(e))
        return JSONResponse(status_code=200, content=[])


@router.post(
    "/vm-thresholds/alerts/{alert_id}/acknowledge",
    summary="Acknowledge VM threshold alert",
    description="Acknowledge an active VM threshold alert",
)
async def acknowledge_vm_alert(
    alert_id: int = Path(..., description="Alert ID"),
    user: UserContext = Depends(require_role(UserRole.WRITE)),
    service: InfraAlertService = Depends(_get_service),
) -> dict:
    """Acknowledge a VM threshold alert."""
    return await service.acknowledge_vm_alert(
        alert_id=alert_id,
        acknowledged_by=user.email or user.user_id,
    )


@router.post(
    "/vm-thresholds/alerts/{alert_id}/resolve",
    summary="Resolve VM threshold alert",
    description="Resolve a VM threshold alert",
)
async def resolve_vm_alert(
    alert_id: int = Path(..., description="Alert ID"),
    request: ResolveAlertRequest = Body(default=ResolveAlertRequest()),
    user: UserContext = Depends(require_role(UserRole.WRITE)),
    service: InfraAlertService = Depends(_get_service),
) -> dict:
    """Resolve a VM threshold alert."""
    return await service.resolve_vm_alert(
        alert_id=alert_id,
        resolution_notes=request.resolution_notes,
        resolved_by=user.email or user.user_id,
    )


# ── VM Discovery ───────────────────────────────────────────────────────


@router.get(
    "/vms",
    summary="List VMs in subscription",
    description="List all VMs available for monitoring in a subscription",
)
async def list_vms(
    subscription_id: str = Query(..., description="Azure subscription ID"),
    user: UserContext = Depends(get_current_user),
    service: InfraAlertService = Depends(_get_service),
) -> list[dict]:
    """List VMs in a subscription."""
    return await service.list_vms(subscription_id)


@router.get(
    "/vms/{subscription_id}/{resource_group}/{vm_name}/metrics",
    summary="Get VM metrics",
    description="Get current CPU, memory, and disk metrics for a VM",
)
async def get_vm_metrics(
    subscription_id: str = Path(..., description="Azure subscription ID"),
    resource_group: str = Path(..., description="Resource group name"),
    vm_name: str = Path(..., description="VM name"),
    user: UserContext = Depends(get_current_user),
    service: InfraAlertService = Depends(_get_service),
) -> dict:
    """Get current VM metrics."""
    return await service.get_vm_metrics(subscription_id, resource_group, vm_name)


# ── Custom Expiry Alert Configuration ──────────────────────────────────


@router.get(
    "/expiry/configs",
    summary="List expiry alert configurations",
    description="Returns all custom expiry alert configurations",
)
async def list_expiry_configs(
    alert_type: str | None = Query(
        default=None,
        description="Filter by type: mech_id, certificate, aaf_account, database_account, itservices_domain",
    ),
    is_enabled: bool | None = Query(default=None, description="Filter by enabled status"),
    user: UserContext = Depends(get_current_user),
    service: InfraAlertService = Depends(_get_service),
) -> list[dict]:
    """List custom expiry alert configurations."""
    try:
        return await service.list_expiry_configs(
            alert_type=alert_type,
            is_enabled=is_enabled,
        )
    except Exception as e:
        logger.warning("list_expiry_configs_db_error", error=str(e))
        return JSONResponse(status_code=200, content=[])


@router.post(
    "/expiry/configs",
    summary="Create expiry alert configuration",
    description="Create a new custom expiry alert configuration",
)
async def create_expiry_config(
    request: CreateExpiryConfigRequest = Body(...),
    user: UserContext = Depends(require_role(UserRole.WRITE)),
    service: InfraAlertService = Depends(_get_service),
) -> dict:
    """Create a custom expiry alert configuration."""
    return await service.create_expiry_config(
        alert_type=request.alert_type,
        resource_name=request.resource_name,
        resource_identifier=request.resource_identifier,
        expiry_date=request.expiry_date,
        created_by=user.email or user.user_id,
        description=request.description,
        warning_days_before=request.warning_days_before,
        critical_days_before=request.critical_days_before,
        notification_emails=request.notification_emails,
        metadata=request.metadata,
    )


@router.put(
    "/expiry/configs/{config_id}",
    summary="Update expiry alert configuration",
    description="Update an existing custom expiry alert configuration",
)
async def update_expiry_config(
    config_id: int = Path(..., description="Configuration ID"),
    request: UpdateExpiryConfigRequest = Body(...),
    user: UserContext = Depends(require_role(UserRole.WRITE)),
    service: InfraAlertService = Depends(_get_service),
) -> dict:
    """Update a custom expiry alert configuration."""
    updates = request.model_dump(exclude_none=True)
    return await service.update_expiry_config(config_id, **updates)


@router.delete(
    "/expiry/configs/{config_id}",
    summary="Delete expiry alert configuration",
    description="Delete a custom expiry alert configuration",
)
async def delete_expiry_config(
    config_id: int = Path(..., description="Configuration ID"),
    user: UserContext = Depends(require_role(UserRole.ADMIN)),
    service: InfraAlertService = Depends(_get_service),
) -> dict:
    """Delete a custom expiry alert configuration."""
    return await service.delete_expiry_config(config_id)


# ── Custom Expiry Alerts ───────────────────────────────────────────────


@router.get(
    "/expiry/alerts",
    summary="List expiry alerts",
    description="Returns active and historical custom expiry alerts",
)
async def list_expiry_alerts(
    alert_type: str | None = Query(default=None, description="Filter by type"),
    status: str | None = Query(
        default=None,
        description="Filter by status: active, acknowledged, resolved, expired",
    ),
    severity: str | None = Query(default=None, description="Filter by severity: warning, critical"),
    limit: int = Query(default=100, ge=1, le=500),
    user: UserContext = Depends(get_current_user),
    service: InfraAlertService = Depends(_get_service),
) -> list[dict]:
    """List custom expiry alerts."""
    try:
        return await service.list_expiry_alerts(
            alert_type=alert_type,
            status=status,
            severity=severity,
            limit=limit,
        )
    except Exception as e:
        logger.warning("list_expiry_alerts_db_error", error=str(e))
        return JSONResponse(status_code=200, content=[])


@router.post(
    "/expiry/alerts/{alert_id}/acknowledge",
    summary="Acknowledge expiry alert",
    description="Acknowledge an active expiry alert",
)
async def acknowledge_expiry_alert(
    alert_id: int = Path(..., description="Alert ID"),
    user: UserContext = Depends(require_role(UserRole.WRITE)),
    service: InfraAlertService = Depends(_get_service),
) -> dict:
    """Acknowledge a custom expiry alert."""
    return await service.acknowledge_expiry_alert(
        alert_id=alert_id,
        acknowledged_by=user.email or user.user_id,
    )


@router.post(
    "/expiry/alerts/{alert_id}/resolve",
    summary="Resolve expiry alert",
    description="Resolve a custom expiry alert",
)
async def resolve_expiry_alert(
    alert_id: int = Path(..., description="Alert ID"),
    request: ResolveAlertRequest = Body(default=ResolveAlertRequest()),
    user: UserContext = Depends(require_role(UserRole.WRITE)),
    service: InfraAlertService = Depends(_get_service),
) -> dict:
    """Resolve a custom expiry alert."""
    return await service.resolve_expiry_alert(
        alert_id=alert_id,
        resolution_notes=request.resolution_notes,
        resolved_by=user.email or user.user_id,
    )


@router.post(
    "/expiry/check",
    summary="Check and generate expiry alerts",
    description="Manually trigger expiry alert generation based on configured thresholds",
)
async def check_expiry_alerts(
    user: UserContext = Depends(require_role(UserRole.WRITE)),
    service: InfraAlertService = Depends(_get_service),
) -> dict:
    """Check all expiry configs and generate alerts if needed."""
    return await service.check_and_generate_expiry_alerts()


# ── Storage Alert Configuration ────────────────────────────────────────


@router.get(
    "/storage/configs",
    summary="List storage alert configurations",
    description="Returns all storage alert configurations",
)
async def list_storage_alert_configs(
    subscription_id: str | None = Query(default=None, description="Filter by subscription"),
    is_enabled: bool | None = Query(default=None, description="Filter by enabled status"),
    user: UserContext = Depends(get_current_user),
    service: InfraAlertService = Depends(_get_service),
) -> list[dict]:
    """List storage alert configurations."""
    try:
        return await service.list_storage_alert_configs(
            subscription_id=subscription_id,
            is_enabled=is_enabled,
        )
    except Exception as e:
        logger.warning("list_storage_alert_configs_db_error", error=str(e))
        return JSONResponse(status_code=200, content=[])


@router.post(
    "/storage/configs",
    summary="Create storage alert configuration",
    description="Create a new storage alert configuration",
)
async def create_storage_alert_config(
    request: CreateStorageAlertConfigRequest = Body(...),
    user: UserContext = Depends(require_role(UserRole.WRITE)),
    service: InfraAlertService = Depends(_get_service),
) -> dict:
    """Create a storage alert configuration."""
    return await service.create_storage_alert_config(
        subscription_id=request.subscription_id,
        resource_group=request.resource_group,
        account_name=request.account_name,
        account_id=request.account_id,
        created_by=user.email or user.user_id,
        capacity_warning_gb=request.capacity_warning_gb,
        capacity_critical_gb=request.capacity_critical_gb,
        transactions_warning=request.transactions_warning,
        transactions_critical=request.transactions_critical,
        egress_warning_gb=request.egress_warning_gb,
        egress_critical_gb=request.egress_critical_gb,
        notification_emails=request.notification_emails,
    )


@router.put(
    "/storage/configs/{config_id}",
    summary="Update storage alert configuration",
    description="Update an existing storage alert configuration",
)
async def update_storage_alert_config(
    config_id: int = Path(..., description="Configuration ID"),
    request: UpdateStorageAlertConfigRequest = Body(...),
    user: UserContext = Depends(require_role(UserRole.WRITE)),
    service: InfraAlertService = Depends(_get_service),
) -> dict:
    """Update a storage alert configuration."""
    updates = request.model_dump(exclude_none=True)
    return await service.update_storage_alert_config(config_id, **updates)


@router.delete(
    "/storage/configs/{config_id}",
    summary="Delete storage alert configuration",
    description="Delete a storage alert configuration",
)
async def delete_storage_alert_config(
    config_id: int = Path(..., description="Configuration ID"),
    user: UserContext = Depends(require_role(UserRole.ADMIN)),
    service: InfraAlertService = Depends(_get_service),
) -> dict:
    """Delete a storage alert configuration."""
    return await service.delete_storage_alert_config(config_id)


# ── PG Flex Server Alert Configuration ─────────────────────────────────


@router.get(
    "/pg-thresholds/configs",
    summary="List PG Flexible Server alert configurations",
    description="Returns all PostgreSQL Flexible Server alert configurations",
)
async def list_pg_flex_configs(
    subscription_id: str | None = Query(default=None, description="Filter by subscription"),
    is_enabled: bool | None = Query(default=None, description="Filter by enabled status"),
    user: UserContext = Depends(get_current_user),
    service: InfraAlertService = Depends(_get_service),
) -> list[dict]:
    """List PG Flexible Server alert configurations."""
    try:
        return await service.list_pg_flex_configs(
            subscription_id=subscription_id,
            is_enabled=is_enabled,
        )
    except Exception as e:
        logger.warning("list_pg_flex_configs_db_error", error=str(e))
        return JSONResponse(status_code=200, content=[])


@router.post(
    "/pg-thresholds/configs",
    summary="Create PG Flexible Server alert configuration",
    description="Create a new PG Flexible Server threshold alert configuration",
)
async def create_pg_flex_config(
    request: CreatePGFlexConfigRequest = Body(...),
    user: UserContext = Depends(require_role(UserRole.WRITE)),
    service: InfraAlertService = Depends(_get_service),
) -> dict:
    """Create a PG Flexible Server alert configuration."""
    return await service.create_pg_flex_config(
        subscription_id=request.subscription_id,
        resource_group=request.resource_group,
        server_name=request.server_name,
        server_id=request.server_id,
        created_by=user.email or user.user_id,
        cpu_warning_threshold=request.cpu_warning_threshold,
        cpu_critical_threshold=request.cpu_critical_threshold,
        memory_warning_threshold=request.memory_warning_threshold,
        memory_critical_threshold=request.memory_critical_threshold,
        storage_warning_threshold=request.storage_warning_threshold,
        storage_critical_threshold=request.storage_critical_threshold,
        notification_emails=request.notification_emails,
    )


@router.put(
    "/pg-thresholds/configs/{config_id}",
    summary="Update PG Flexible Server alert configuration",
    description="Update an existing PG Flexible Server alert configuration",
)
async def update_pg_flex_config(
    config_id: int = Path(..., description="Configuration ID"),
    request: UpdatePGFlexConfigRequest = Body(...),
    user: UserContext = Depends(require_role(UserRole.WRITE)),
    service: InfraAlertService = Depends(_get_service),
) -> dict:
    """Update a PG Flexible Server alert configuration."""
    updates = request.model_dump(exclude_none=True)
    return await service.update_pg_flex_config(config_id, **updates)


@router.delete(
    "/pg-thresholds/configs/{config_id}",
    summary="Delete PG Flexible Server alert configuration",
    description="Delete a PG Flexible Server alert configuration",
)
async def delete_pg_flex_config(
    config_id: int = Path(..., description="Configuration ID"),
    user: UserContext = Depends(require_role(UserRole.ADMIN)),
    service: InfraAlertService = Depends(_get_service),
) -> dict:
    """Delete a PG Flexible Server alert configuration."""
    return await service.delete_pg_flex_config(config_id)


# ── PG Flex Server Alerts ──────────────────────────────────────────────


@router.get(
    "/pg-thresholds/alerts",
    summary="List PG Flexible Server alerts",
    description="Returns active and historical PG Flexible Server threshold alerts",
)
async def list_pg_flex_alerts(
    status: str | None = Query(default=None, description="Filter by status: active, acknowledged, resolved"),
    severity: str | None = Query(default=None, description="Filter by severity: warning, critical"),
    limit: int = Query(default=100, ge=1, le=500),
    user: UserContext = Depends(get_current_user),
    service: InfraAlertService = Depends(_get_service),
) -> list[dict]:
    """List PG Flexible Server alerts."""
    try:
        return await service.list_pg_flex_alerts(
            status=status,
            severity=severity,
            limit=limit,
        )
    except Exception as e:
        logger.warning("list_pg_flex_alerts_db_error", error=str(e))
        return JSONResponse(status_code=200, content=[])


@router.post(
    "/pg-thresholds/alerts/{alert_id}/acknowledge",
    summary="Acknowledge PG Flexible Server alert",
    description="Acknowledge an active PG Flexible Server alert",
)
async def acknowledge_pg_flex_alert(
    alert_id: int = Path(..., description="Alert ID"),
    user: UserContext = Depends(require_role(UserRole.WRITE)),
    service: InfraAlertService = Depends(_get_service),
) -> dict:
    """Acknowledge a PG Flexible Server alert."""
    return await service.acknowledge_pg_flex_alert(
        alert_id=alert_id,
        acknowledged_by=user.email or user.user_id,
    )


@router.post(
    "/pg-thresholds/alerts/{alert_id}/resolve",
    summary="Resolve PG Flexible Server alert",
    description="Resolve a PG Flexible Server alert",
)
async def resolve_pg_flex_alert(
    alert_id: int = Path(..., description="Alert ID"),
    request: ResolveAlertRequest = Body(default=ResolveAlertRequest()),
    user: UserContext = Depends(require_role(UserRole.WRITE)),
    service: InfraAlertService = Depends(_get_service),
) -> dict:
    """Resolve a PG Flexible Server alert."""
    return await service.resolve_pg_flex_alert(
        alert_id=alert_id,
        resolution_notes=request.resolution_notes,
        resolved_by=user.email or user.user_id,
    )


@router.get(
    "/pg-servers/{subscription_id}/{resource_group}/{server_name}/metrics",
    summary="Get PG Flexible Server metrics",
    description="Get current CPU, memory, and storage metrics for a PG Flexible Server",
)
async def get_pg_metrics(
    subscription_id: str = Path(..., description="Azure subscription ID"),
    resource_group: str = Path(..., description="Resource group name"),
    server_name: str = Path(..., description="Server name"),
    user: UserContext = Depends(get_current_user),
    service: InfraAlertService = Depends(_get_service),
) -> dict:
    """Get current PG Flexible Server metrics."""
    return await service.get_pg_metrics(subscription_id, resource_group, server_name)


@router.post(
    "/pg-thresholds/check",
    summary="Check and generate PG Flexible Server alerts",
    description="Manually trigger PG Flexible Server alert generation based on configured thresholds",
)
async def check_pg_flex_alerts(
    user: UserContext = Depends(require_role(UserRole.WRITE)),
    service: InfraAlertService = Depends(_get_service),
) -> dict:
    """Check all PG configs and generate alerts if thresholds are exceeded."""
    return await service.check_and_generate_pg_alerts()


# ── Azure Resource Listing ─────────────────────────────────────────────


@router.get(
    "/resources/vms",
    summary="List all VMs (from DB first, fallback to Azure)",
    description="Get VMs from database cache. If DB is empty, fetches live from Azure.",
)
async def list_azure_vms(
    resource_group: str | None = Query(default=None, description="Filter by resource group"),
    source: str = Query(default="db", description="Source: 'db' for cached, 'azure' for live"),
    save_to_db: bool = Query(default=False, description="Save resources to database"),
    user: UserContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """List all VMs — DB first, Azure fallback."""
    _empty = {"source": "db", "last_sync": None, "count": 0, "resources": []}
    try:
        from app.services.azure_resource_service import AzureResourceService

        resource_service = AzureResourceService(db)

        # DB-first: try DB cache unless user explicitly asks for Azure
        if source == "db" and db is not None:
            try:
                db_results = await resource_service.get_vms_from_db()
                if db_results:
                    last_sync = await resource_service.get_last_sync_time("virtual_machine")
                    return JSONResponse(
                        content={
                            "source": "db",
                            "last_sync": last_sync,
                            "count": len(db_results),
                            "resources": db_results,
                        }
                    )
            except Exception as db_err:
                logger.warning("list_vms_db_failed_falling_back_to_azure", error=str(db_err))

        # Azure live fetch (fallback or explicit)
        try:
            result = await resource_service.list_vms(resource_group=resource_group, save_to_db=save_to_db)
            return JSONResponse(
                content={
                    "source": "azure",
                    "last_sync": None,
                    "count": len(result),
                    "resources": result,
                }
            )
        except Exception as az_err:
            logger.warning("list_vms_azure_fallback_also_failed", error=str(az_err))
            return JSONResponse(content={**_empty, "error": f"Both DB and Azure unavailable: {az_err}"})
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        logger.error(
            "list_azure_vms_failed",
            error=str(e),
            error_type=type(e).__name__,
            tb=traceback.format_exc(),
        )
        return JSONResponse(content={**_empty, "error": str(e)})


@router.get(
    "/resources/storage-accounts",
    summary="List all storage accounts (from DB first, fallback to Azure)",
    description="Get storage accounts from database cache. If DB is empty, fetches live from Azure.",
)
async def list_azure_storage_accounts(
    resource_group: str | None = Query(default=None, description="Filter by resource group"),
    source: str = Query(default="db", description="Source: 'db' for cached, 'azure' for live"),
    save_to_db: bool = Query(default=False, description="Save resources to database"),
    user: UserContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """List all storage accounts — DB first, Azure fallback."""
    _empty = {"source": "db", "last_sync": None, "count": 0, "resources": []}
    try:
        from app.services.azure_resource_service import AzureResourceService

        resource_service = AzureResourceService(db)

        if source == "db" and db is not None:
            try:
                db_results = await resource_service.get_storage_accounts_from_db()
                if db_results:
                    last_sync = await resource_service.get_last_sync_time("storage_account")
                    return JSONResponse(
                        content={
                            "source": "db",
                            "last_sync": last_sync,
                            "count": len(db_results),
                            "resources": db_results,
                        }
                    )
            except Exception as db_err:
                logger.warning("list_storage_db_failed_falling_back_to_azure", error=str(db_err))

        try:
            result = await resource_service.list_storage_accounts(resource_group=resource_group, save_to_db=save_to_db)
            return JSONResponse(
                content={
                    "source": "azure",
                    "last_sync": None,
                    "count": len(result),
                    "resources": result,
                }
            )
        except Exception as az_err:
            logger.warning("list_storage_azure_fallback_also_failed", error=str(az_err))
            return JSONResponse(content={**_empty, "error": f"Both DB and Azure unavailable: {az_err}"})
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        logger.error(
            "list_azure_storage_failed",
            error=str(e),
            error_type=type(e).__name__,
            tb=traceback.format_exc(),
        )
        return JSONResponse(content={**_empty, "error": str(e)})


@router.get(
    "/resources/disks",
    summary="List all managed disks (from DB first, fallback to Azure)",
    description="Get managed disks from database cache. If DB is empty, fetches live from Azure.",
)
async def list_azure_disks(
    resource_group: str | None = Query(default=None, description="Filter by resource group"),
    source: str = Query(default="db", description="Source: 'db' for cached, 'azure' for live"),
    save_to_db: bool = Query(default=False, description="Save resources to database"),
    user: UserContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """List all managed disks — DB first, Azure fallback."""
    _empty = {"source": "db", "last_sync": None, "count": 0, "resources": []}
    try:
        from app.services.azure_resource_service import AzureResourceService

        resource_service = AzureResourceService(db)

        if source == "db" and db is not None:
            try:
                db_results = await resource_service.get_disks_from_db()
                if db_results:
                    last_sync = await resource_service.get_last_sync_time("managed_disk")
                    return JSONResponse(
                        content={
                            "source": "db",
                            "last_sync": last_sync,
                            "count": len(db_results),
                            "resources": db_results,
                        }
                    )
            except Exception as db_err:
                logger.warning("list_disks_db_failed_falling_back_to_azure", error=str(db_err))

        try:
            result = await resource_service.list_disks(resource_group=resource_group, save_to_db=save_to_db)
            return JSONResponse(
                content={
                    "source": "azure",
                    "last_sync": None,
                    "count": len(result),
                    "resources": result,
                }
            )
        except Exception as az_err:
            logger.warning("list_disks_azure_fallback_also_failed", error=str(az_err))
            return JSONResponse(content={**_empty, "error": f"Both DB and Azure unavailable: {az_err}"})
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        logger.error(
            "list_azure_disks_failed",
            error=str(e),
            error_type=type(e).__name__,
            tb=traceback.format_exc(),
        )
        return JSONResponse(content={**_empty, "error": str(e)})


@router.get(
    "/resources/pg-servers",
    summary="List all PG Flexible Servers (from DB first, fallback to Azure)",
    description="Get PG Flexible Servers from database cache. If DB is empty, fetches live from Azure.",
)
async def list_azure_pg_servers(
    resource_group: str | None = Query(default=None, description="Filter by resource group"),
    source: str = Query(default="db", description="Source: 'db' for cached, 'azure' for live"),
    save_to_db: bool = Query(default=False, description="Save resources to database"),
    user: UserContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """List all PG Flexible Servers — DB first, Azure fallback."""
    _empty = {"source": "db", "last_sync": None, "count": 0, "resources": []}
    try:
        from app.services.azure_resource_service import AzureResourceService

        resource_service = AzureResourceService(db)

        if source == "db" and db is not None:
            try:
                db_results = await resource_service.get_pg_servers_from_db()
                if db_results:
                    last_sync = await resource_service.get_last_sync_time("pg_flex_server")
                    return JSONResponse(
                        content={
                            "source": "db",
                            "last_sync": last_sync,
                            "count": len(db_results),
                            "resources": db_results,
                        }
                    )
            except Exception as db_err:
                logger.warning("list_pg_servers_db_failed_falling_back_to_azure", error=str(db_err))

        try:
            result = await resource_service.list_pg_flex_servers(resource_group=resource_group, save_to_db=save_to_db)
            return JSONResponse(
                content={
                    "source": "azure",
                    "last_sync": None,
                    "count": len(result),
                    "resources": result,
                }
            )
        except Exception as az_err:
            logger.warning("list_pg_servers_azure_fallback_also_failed", error=str(az_err))
            return JSONResponse(content={**_empty, "error": f"Both DB and Azure unavailable: {az_err}"})
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        logger.error(
            "list_azure_pg_servers_failed",
            error=str(e),
            error_type=type(e).__name__,
            tb=traceback.format_exc(),
        )
        return JSONResponse(content={**_empty, "error": str(e)})


@router.post(
    "/resources/sync",
    summary="Sync all resources from Azure to DB",
    description="Fetch VMs (with power_state), Storage Accounts, Disks from Azure and save to database",
)
async def sync_resources_to_db(
    resource_type: str | None = Query(default=None, description="Sync specific type: vm, storage, disk, pg. None=all"),
    user: UserContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Sync resources from Azure live to DB."""
    if db is None:
        return JSONResponse(
            status_code=503,
            content={"error": "Database unavailable — cannot sync", "synced": False},
        )
    try:
        from app.services.azure_resource_service import AzureResourceService

        resource_service = AzureResourceService(db)

        if resource_type == "vm":
            result = await resource_service.sync_vms_to_db()
        elif resource_type == "storage":
            result = await resource_service.sync_storage_accounts_to_db()
        elif resource_type == "disk":
            result = await resource_service.sync_disks_to_db()
        elif resource_type == "pg":
            result = await resource_service.sync_pg_servers_to_db()
        else:
            result = await resource_service.sync_all_resources_to_db()

        return JSONResponse(content=result)
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        logger.error(
            "sync_resources_failed",
            error=str(e),
            error_type=type(e).__name__,
            tb=traceback.format_exc(),
        )
        return JSONResponse(
            status_code=500,
            content={"error": f"Sync failed: {str(e)}", "synced": False},
        )


@router.get(
    "/resources/nsgs",
    summary="List all network security groups from Azure",
    description="List all NSGs from Azure subscription with option to save to DB",
)
async def list_azure_nsgs(
    resource_group: str | None = Query(default=None, description="Filter by resource group"),
    save_to_db: bool = Query(default=False, description="Save resources to database"),
    user: UserContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """List all Azure network security groups."""
    try:
        from app.services.azure_resource_service import AzureResourceService

        resource_service = AzureResourceService(db)
        result = await resource_service.list_network_security_groups(
            resource_group=resource_group, save_to_db=save_to_db
        )
        return JSONResponse(content=result)
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        logger.error(
            "list_azure_nsgs_failed",
            error=str(e),
            error_type=type(e).__name__,
            tb=traceback.format_exc(),
        )
        raise HTTPException(status_code=500, detail=f"Failed to list NSGs: {str(e)}")


@router.get(
    "/resources/public-ips",
    summary="List all public IPs from Azure",
    description="List all public IP addresses from Azure subscription",
)
async def list_azure_public_ips(
    resource_group: str | None = Query(default=None, description="Filter by resource group"),
    save_to_db: bool = Query(default=False, description="Save resources to database"),
    user: UserContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """List all Azure public IPs."""
    try:
        from app.services.azure_resource_service import AzureResourceService

        resource_service = AzureResourceService(db)
        result = await resource_service.list_public_ips(resource_group=resource_group, save_to_db=save_to_db)
        return JSONResponse(content=result)
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        logger.error(
            "list_azure_ips_failed",
            error=str(e),
            error_type=type(e).__name__,
            tb=traceback.format_exc(),
        )
        raise HTTPException(status_code=500, detail=f"Failed to list public IPs: {str(e)}")


@router.get(
    "/resources/load-balancers",
    summary="List all load balancers from Azure",
    description="List all load balancers from Azure subscription",
)
async def list_azure_load_balancers(
    resource_group: str | None = Query(default=None, description="Filter by resource group"),
    save_to_db: bool = Query(default=False, description="Save resources to database"),
    user: UserContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """List all Azure load balancers."""
    try:
        from app.services.azure_resource_service import AzureResourceService

        resource_service = AzureResourceService(db)
        result = await resource_service.list_load_balancers(resource_group=resource_group, save_to_db=save_to_db)
        return JSONResponse(content=result)
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        logger.error(
            "list_azure_lbs_failed",
            error=str(e),
            error_type=type(e).__name__,
            tb=traceback.format_exc(),
        )
        raise HTTPException(status_code=500, detail=f"Failed to list load balancers: {str(e)}")


@router.get(
    "/resources/all",
    summary="List all supported Azure resources",
    description="List all supported Azure resources (VMs, Storage, Disks, etc.)",
)
async def list_all_azure_resources(
    resource_group: str | None = Query(default=None, description="Filter by resource group"),
    save_to_db: bool = Query(default=True, description="Save resources to database"),
    user: UserContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """List all supported Azure resources."""
    try:
        from app.services.azure_resource_service import AzureResourceService

        resource_service = AzureResourceService(db)
        result = await resource_service.list_all_resources(resource_group=resource_group, save_to_db=save_to_db)
        return JSONResponse(content=result)
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        logger.error(
            "list_all_resources_failed",
            error=str(e),
            error_type=type(e).__name__,
            tb=traceback.format_exc(),
        )
        raise HTTPException(status_code=500, detail=f"Failed to list resources: {str(e)}")


@router.get(
    "/resources/inventory",
    summary="Get resource inventory from database",
    description="Get cached resource inventory from the database",
)
async def get_resource_inventory(
    resource_type: str | None = Query(default=None, description="Filter by resource type"),
    resource_group: str | None = Query(default=None, description="Filter by resource group"),
    user: UserContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    """Get resource inventory from database."""
    try:
        from app.services.azure_resource_service import AzureResourceService

        resource_service = AzureResourceService(db)
        return await resource_service.get_inventory_from_db(
            resource_type=resource_type,
            resource_group=resource_group,
        )
    except Exception as e:
        logger.error("get_inventory_failed", error=str(e))
        raise HTTPException(status_code=500, detail=f"Failed to get inventory: {str(e)}")


@router.get(
    "/resources/inventory/summary",
    summary="Get resource inventory summary",
    description="Get summary counts of cached resources by type",
)
async def get_inventory_summary(
    user: UserContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Get resource inventory summary."""
    if db is None:
        return JSONResponse(
            status_code=200,
            content={"error": "Database unavailable", "total": 0, "by_type": {}},
        )
    try:
        from app.services.azure_resource_service import AzureResourceService

        resource_service = AzureResourceService(db)
        return await resource_service.get_inventory_summary()
    except OSError as e:
        logger.warning("get_inventory_summary_connection_error", error=str(e))
        return JSONResponse(
            status_code=200,
            content={
                "error": f"Database connection lost: {e}",
                "total": 0,
                "by_type": {},
            },
        )
    except Exception as e:
        logger.error("get_inventory_summary_failed", error=str(e))
        return JSONResponse(
            status_code=500,
            content={"detail": f"Failed to get inventory summary: {str(e)}"},
        )


# ── Scheduler Control ──────────────────────────────────────────────────


@router.get(
    "/scheduler/status",
    summary="Get scheduler status",
    description="Get current status of the background alert scheduler",
)
async def get_scheduler_status_endpoint(
    user: UserContext = Depends(require_role(UserRole.ADMIN)),
) -> JSONResponse:
    """Get scheduler status."""
    try:
        from app.services.scheduler_service import get_scheduler_status

        result = get_scheduler_status()
        return JSONResponse(content=result)
    except Exception as e:
        logger.error(
            "get_scheduler_status_failed",
            error=str(e),
            error_type=type(e).__name__,
            tb=traceback.format_exc(),
        )
        raise HTTPException(status_code=500, detail=f"Failed to get scheduler status: {str(e)}")


@router.post(
    "/scheduler/start",
    summary="Start scheduler",
    description="Start the background alert scheduler",
)
async def start_scheduler_endpoint(
    user: UserContext = Depends(require_role(UserRole.ADMIN)),
) -> JSONResponse:
    """Start the background scheduler."""
    try:
        from app.services.scheduler_service import start_scheduler

        await start_scheduler()
        from app.services.scheduler_service import get_scheduler_status

        result = get_scheduler_status()
        return JSONResponse(content={"status": "started", **result})
    except Exception as e:
        logger.error("start_scheduler_failed", error=str(e), tb=traceback.format_exc())
        raise HTTPException(status_code=500, detail=f"Failed to start scheduler: {str(e)}")


@router.post(
    "/scheduler/stop",
    summary="Stop scheduler",
    description="Stop the background alert scheduler",
)
async def stop_scheduler_endpoint(
    user: UserContext = Depends(require_role(UserRole.ADMIN)),
) -> JSONResponse:
    """Stop the background scheduler."""
    try:
        from app.services.scheduler_service import stop_scheduler

        await stop_scheduler()
        from app.services.scheduler_service import get_scheduler_status

        result = get_scheduler_status()
        return JSONResponse(content={"status": "stopped", **result})
    except Exception as e:
        logger.error("stop_scheduler_failed", error=str(e), tb=traceback.format_exc())
        raise HTTPException(status_code=500, detail=f"Failed to stop scheduler: {str(e)}")


@router.post(
    "/scheduler/trigger/vm-check",
    summary="Trigger VM threshold check",
    description="Manually trigger VM threshold check job",
)
async def trigger_vm_check(
    user: UserContext = Depends(require_role(UserRole.ADMIN)),
) -> JSONResponse:
    """Trigger VM threshold check job."""
    try:
        from app.services.scheduler_service import trigger_vm_threshold_check

        result = await trigger_vm_threshold_check()
        return JSONResponse(content=result)
    except Exception as e:
        logger.error("trigger_vm_check_failed", error=str(e), tb=traceback.format_exc())
        raise HTTPException(status_code=500, detail=f"Failed to trigger VM check: {str(e)}")


@router.post(
    "/scheduler/trigger/expiry-check",
    summary="Trigger expiry check",
    description="Manually trigger expiry alert check job",
)
async def trigger_expiry_check(
    user: UserContext = Depends(require_role(UserRole.ADMIN)),
) -> JSONResponse:
    """Trigger expiry check job."""
    try:
        from app.services.scheduler_service import trigger_expiry_check

        result = await trigger_expiry_check()
        return JSONResponse(content=result)
    except Exception as e:
        logger.error("trigger_expiry_check_failed", error=str(e), tb=traceback.format_exc())
        raise HTTPException(status_code=500, detail=f"Failed to trigger expiry check: {str(e)}")


@router.post(
    "/scheduler/trigger/daily-digest",
    summary="Trigger daily digest",
    description="Manually trigger daily alert digest email",
)
async def trigger_daily_digest(
    user: UserContext = Depends(require_role(UserRole.ADMIN)),
) -> JSONResponse:
    """Trigger daily digest job."""
    try:
        from app.services.scheduler_service import trigger_daily_digest

        result = await trigger_daily_digest()
        return JSONResponse(content=result)
    except Exception as e:
        logger.error("trigger_daily_digest_failed", error=str(e), tb=traceback.format_exc())
        raise HTTPException(status_code=500, detail=f"Failed to trigger daily digest: {str(e)}")


@router.post(
    "/scheduler/trigger/resource-sync",
    summary="Trigger resource sync",
    description="Manually trigger Azure resource sync job",
)
async def trigger_resource_sync(
    user: UserContext = Depends(require_role(UserRole.ADMIN)),
) -> JSONResponse:
    """Trigger resource sync job."""
    try:
        from app.services.scheduler_service import trigger_resource_sync

        result = await trigger_resource_sync()
        return JSONResponse(content=result)
    except Exception as e:
        logger.error("trigger_resource_sync_failed", error=str(e), tb=traceback.format_exc())
        raise HTTPException(status_code=500, detail=f"Failed to trigger resource sync: {str(e)}")


@router.post(
    "/scheduler/trigger/pg-check",
    summary="Trigger PG Flexible Server threshold check",
    description="Manually trigger PG Flexible Server threshold check job",
)
async def trigger_pg_check(
    user: UserContext = Depends(require_role(UserRole.ADMIN)),
    service: InfraAlertService = Depends(_get_service),
) -> JSONResponse:
    """Trigger PG Flexible Server threshold check job."""
    try:
        result = await service.check_and_generate_pg_alerts()
        return JSONResponse(content=result)
    except Exception as e:
        logger.error("trigger_pg_check_failed", error=str(e), tb=traceback.format_exc())
        raise HTTPException(status_code=500, detail=f"Failed to trigger PG check: {str(e)}")


# ── Notification History ───────────────────────────────────────────────


@router.get(
    "/notifications/history",
    summary="Get notification history",
    description="Get history of sent alert notifications",
)
async def get_notification_history(
    notification_type: str | None = Query(default=None, description="Filter by notification type"),
    alert_type: str | None = Query(default=None, description="Filter by alert type"),
    alert_id: int | None = Query(default=None, description="Filter by alert ID"),
    status: str | None = Query(default=None, description="Filter by delivery status"),
    limit: int = Query(default=100, ge=1, le=500),
    user: UserContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    """Get notification history."""
    if db is None:
        return JSONResponse(status_code=200, content=[])
    try:
        from app.services.email_notification_service import EmailNotificationService

        effective_alert_type = notification_type or alert_type
        if effective_alert_type == "expiry":
            effective_alert_type = "custom_expiry"

        email_service = EmailNotificationService(db)
        return await email_service.get_notification_history(
            alert_type=effective_alert_type,
            alert_id=alert_id,
            status=status,
            limit=limit,
            exclude_alert_types=(None if effective_alert_type else ["checksum_report", "checksum_verification"]),
        )
    except OSError as e:
        logger.warning("get_notification_history_connection_error", error=str(e))
        return JSONResponse(status_code=200, content=[])
    except Exception as e:
        logger.error("get_notification_history_failed", error=str(e))
        return JSONResponse(
            status_code=500,
            content={"detail": f"Failed to get notification history: {str(e)}"},
        )


# ── Send Test Notification ─────────────────────────────────────────────


class TestNotificationRequest(BaseModel):
    """Request to send a test notification."""

    recipient_email: str = Field(..., description="Email address to send test to")
    notification_type: str = Field(default="vm_threshold", description="Type: vm_threshold or expiry")


@router.post(
    "/notifications/test",
    summary="Send test notification",
    description="Send a test notification email to verify configuration",
)
async def send_test_notification(
    request: TestNotificationRequest = Body(...),
    user: UserContext = Depends(require_role(UserRole.ADMIN)),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Send a test notification."""
    try:
        from app.services.email_notification_service import EmailNotificationService

        email_service = EmailNotificationService(db)

        if request.notification_type == "vm_threshold":
            result = await email_service.send_vm_threshold_alert(
                recipient_emails=[request.recipient_email],
                vm_name="test-vm-001",
                resource_group="test-rg",
                subscription_id="00000000-0000-0000-0000-000000000000",
                metric_type="cpu",
                current_value=95.0,
                threshold_value=90.0,
                severity="critical",
                alert_id=0,
            )
        else:
            from datetime import datetime, timedelta

            result = await email_service.send_expiry_alert(
                recipient_emails=[request.recipient_email],
                resource_name="test-mechid-001",
                resource_identifier="TEST-001",
                alert_type="mech_id",
                expiry_date=datetime.utcnow() + timedelta(days=7),
                days_until_expiry=7,
                severity="warning",
                description="Test expiry alert",
                alert_id=0,
            )

        return {"status": "sent", "result": result}
    except Exception as e:
        logger.error("send_test_notification_failed", error=str(e))
        raise HTTPException(status_code=500, detail=f"Failed to send test notification: {str(e)}")


# ── VM Power Management ───────────────────────────────────────────────


class VMActionRequest(BaseModel):
    """Request body for VM power actions."""

    resource_group: str = Field(..., description="Resource group containing the VM")
    vm_name: str = Field(..., description="Name of the virtual machine")


@router.post(
    "/resources/vms/start",
    summary="Start a VM",
    description="Start a virtual machine",
)
async def start_vm_endpoint(
    request: VMActionRequest = Body(...),
    user: UserContext = Depends(require_role(UserRole.ADMIN)),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Start a VM."""
    try:
        from app.services.azure_resource_service import AzureResourceService

        svc = AzureResourceService(db_session=db)
        result = await svc.start_vm(request.resource_group, request.vm_name)
        return JSONResponse(content=result)
    except Exception as e:
        logger.error(
            "start_vm_endpoint_failed",
            vm=request.vm_name,
            error=str(e),
            tb=traceback.format_exc(),
        )
        raise HTTPException(status_code=500, detail=f"Failed to start VM '{request.vm_name}': {str(e)}")


@router.post(
    "/resources/vms/stop",
    summary="Stop (deallocate) a VM",
    description="Stop and deallocate a virtual machine",
)
async def stop_vm_endpoint(
    request: VMActionRequest = Body(...),
    user: UserContext = Depends(require_role(UserRole.ADMIN)),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Stop (deallocate) a VM."""
    try:
        from app.services.azure_resource_service import AzureResourceService

        svc = AzureResourceService(db_session=db)
        result = await svc.stop_vm(request.resource_group, request.vm_name)
        return JSONResponse(content=result)
    except Exception as e:
        logger.error(
            "stop_vm_endpoint_failed",
            vm=request.vm_name,
            error=str(e),
            tb=traceback.format_exc(),
        )
        raise HTTPException(status_code=500, detail=f"Failed to stop VM '{request.vm_name}': {str(e)}")


@router.post(
    "/resources/vms/restart",
    summary="Restart a VM",
    description="Restart a virtual machine",
)
async def restart_vm_endpoint(
    request: VMActionRequest = Body(...),
    user: UserContext = Depends(require_role(UserRole.ADMIN)),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Restart a VM."""
    try:
        from app.services.azure_resource_service import AzureResourceService

        svc = AzureResourceService(db_session=db)
        result = await svc.restart_vm(request.resource_group, request.vm_name)
        return JSONResponse(content=result)
    except Exception as e:
        logger.error(
            "restart_vm_endpoint_failed",
            vm=request.vm_name,
            error=str(e),
            tb=traceback.format_exc(),
        )
        raise HTTPException(
            status_code=500,
            detail=f"Failed to restart VM '{request.vm_name}': {str(e)}",
        )


# ── PG Flexible Server Power Management ───────────────────────────────


class PGServerActionRequest(BaseModel):
    """Request body for PG server power actions."""

    resource_group: str = Field(..., description="Resource group containing the PG server")
    server_name: str = Field(..., description="Name of the PostgreSQL Flexible Server")


@router.post(
    "/resources/pg-servers/start",
    summary="Start a PG Flexible Server",
    description="Start a PostgreSQL Flexible Server",
)
async def start_pg_server_endpoint(
    request: PGServerActionRequest = Body(...),
    user: UserContext = Depends(require_role(UserRole.ADMIN)),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Start a PG Flexible Server."""
    try:
        from app.services.azure_resource_service import AzureResourceService

        svc = AzureResourceService(db_session=db)
        result = await svc.start_pg_server(request.resource_group, request.server_name)
        return JSONResponse(content=result)
    except Exception as e:
        logger.error(
            "start_pg_server_endpoint_failed",
            server=request.server_name,
            error=str(e),
            tb=traceback.format_exc(),
        )
        raise HTTPException(
            status_code=500,
            detail=f"Failed to start PG server '{request.server_name}': {str(e)}",
        )


@router.post(
    "/resources/pg-servers/stop",
    summary="Stop a PG Flexible Server",
    description="Stop a PostgreSQL Flexible Server",
)
async def stop_pg_server_endpoint(
    request: PGServerActionRequest = Body(...),
    user: UserContext = Depends(require_role(UserRole.ADMIN)),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Stop a PG Flexible Server."""
    try:
        from app.services.azure_resource_service import AzureResourceService

        svc = AzureResourceService(db_session=db)
        result = await svc.stop_pg_server(request.resource_group, request.server_name)
        return JSONResponse(content=result)
    except Exception as e:
        logger.error(
            "stop_pg_server_endpoint_failed",
            server=request.server_name,
            error=str(e),
            tb=traceback.format_exc(),
        )
        raise HTTPException(
            status_code=500,
            detail=f"Failed to stop PG server '{request.server_name}': {str(e)}",
        )


@router.post(
    "/resources/pg-servers/restart",
    summary="Restart a PG Flexible Server",
    description="Restart a PostgreSQL Flexible Server",
)
async def restart_pg_server_endpoint(
    request: PGServerActionRequest = Body(...),
    user: UserContext = Depends(require_role(UserRole.ADMIN)),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Restart a PG Flexible Server."""
    try:
        from app.services.azure_resource_service import AzureResourceService

        svc = AzureResourceService(db_session=db)
        result = await svc.restart_pg_server(request.resource_group, request.server_name)
        return JSONResponse(content=result)
    except Exception as e:
        logger.error(
            "restart_pg_server_endpoint_failed",
            server=request.server_name,
            error=str(e),
            tb=traceback.format_exc(),
        )
        raise HTTPException(
            status_code=500,
            detail=f"Failed to restart PG server '{request.server_name}': {str(e)}",
        )
