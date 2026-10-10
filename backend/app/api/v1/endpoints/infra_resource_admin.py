"""
Infrastructure Alerts — resource utilization and administration.

Mounted under ``/infra-alerts`` beside the alert routes, so the module and
target-access (Prod / Non-Prod grant) checks on that prefix apply here too.

Reads are open to every role. Changes need a capability:
- ``infra_vm_run_command`` — Azure Run Command on a VM (its output is gated
  the same way, since it can contain secrets);
- ``infra_resource_admin`` — resize / redeploy VMs, snapshot / expand disks,
  edit tags.

Every change, refused or not, is written to ``audit_logs``.
"""

from __future__ import annotations

import functools

import structlog
from fastapi import APIRouter, Body, Depends, HTTPException, Path, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.core.access_scope import assert_resource_access
from app.core.authz import require_capability
from app.core.database import get_db
from app.models.auth import UserContext
from app.models.database import AuditLog
from app.services.infra_resource_admin_service import HISTORY_GRAINS, InfraResourceAdminService

logger = structlog.get_logger(__name__)
router = APIRouter()

RESOURCE_TYPES = {
    "virtual_machine": "Microsoft.Compute/virtualMachines",
    "pg_flex_server": "Microsoft.DBforPostgreSQL/flexibleServers",
    "storage_account": "Microsoft.Storage/storageAccounts",
    "managed_disk": "Microsoft.Compute/disks",
}


async def _service(db: AsyncSession = Depends(get_db)) -> InfraResourceAdminService:
    return InfraResourceAdminService(db)


async def _audit(
    db: AsyncSession | None,
    request: Request,
    user: UserContext,
    *,
    action: str,
    resource_type: str,
    name: str,
    status: str,
    details: dict,
) -> None:
    if db is None:
        return
    db.add(
        AuditLog(
            user_id=user.user_id,
            user_email=user.email,
            action=action,
            resource_type=resource_type,
            resource_id=name,
            details={"page": "InfraAlertPage", "feature": "resource_admin", **details},
            ip_address=request.client.host if request.client else None,
            status=status,
        )
    )
    try:
        await db.commit()
    except Exception as exc:
        await db.rollback()
        logger.warning("resource_admin_audit_failed", action=action, resource=name, error=str(exc)[:200])


async def _audited(db, request, user, *, action, resource_type, name, details, call):
    """Run an Azure change and audit its outcome either way."""
    record = functools.partial(_audit, db, request, user, action=action, resource_type=resource_type, name=name)
    try:
        result = await call()
    except HTTPException as exc:
        await record(status="failure", details={**details, "error": str(exc.detail)[:500]})
        raise
    except Exception as exc:
        await record(status="failure", details={**details, "error": str(exc)[:500]})
        raise HTTPException(status_code=502, detail=f"Azure rejected the change: {str(exc)[:300]}")
    await record(status="success", details={**details, "result": result})
    return result


# ── Utilization ────────────────────────────────────────────────────────


@router.get("/resources/utilization", summary="Current CPU / memory of every running VM or PG server")
async def get_utilization(
    kind: str = Query(..., pattern="^(vm|pg)$"),
    user: UserContext = Depends(get_current_user),
    service: InfraResourceAdminService = Depends(_service),
) -> dict:
    return await service.utilization(kind)


@router.get(
    "/resources/vms/{subscription_id}/{resource_group}/{vm_name}/metrics/history",
    summary="VM CPU, memory and disk I/O over time",
)
async def get_vm_metrics_history(
    subscription_id: str = Path(...),
    resource_group: str = Path(...),
    vm_name: str = Path(...),
    hours: int = Query(24, description=f"One of {sorted(HISTORY_GRAINS)}"),
    user: UserContext = Depends(get_current_user),
    service: InfraResourceAdminService = Depends(_service),
) -> dict:
    assert_resource_access(subscription_id, "read", context=f"vm metrics history {vm_name}")
    return await service.metrics_history("vm", subscription_id, resource_group, vm_name, hours)


@router.get(
    "/resources/pg-servers/{subscription_id}/{resource_group}/{server_name}/metrics/history",
    summary="PG Flexible Server CPU, memory, storage and connections over time",
)
async def get_pg_metrics_history(
    subscription_id: str = Path(...),
    resource_group: str = Path(...),
    server_name: str = Path(...),
    hours: int = Query(24, description=f"One of {sorted(HISTORY_GRAINS)}"),
    user: UserContext = Depends(get_current_user),
    service: InfraResourceAdminService = Depends(_service),
) -> dict:
    assert_resource_access(subscription_id, "read", context=f"pg metrics history {server_name}")
    return await service.metrics_history("pg", subscription_id, resource_group, server_name, hours)


# ── VM Run Command ─────────────────────────────────────────────────────


class RunCommandRequest(BaseModel):
    subscription_id: str
    resource_group: str
    vm_name: str
    script: str = Field(..., min_length=1, max_length=16_000)
    timeout_seconds: int = Field(default=300, ge=30, le=3600)
    # Production VMs: the VM name typed again, as an explicit confirmation.
    confirm_name: str | None = None


@router.post("/resources/vms/run-command", summary="Start a command on a VM (Azure Run Command)")
async def start_run_command(
    request: Request,
    body: RunCommandRequest = Body(...),
    user: UserContext = Depends(require_capability("infra_vm_run_command")),
    service: InfraResourceAdminService = Depends(_service),
) -> dict:
    assert_resource_access(body.subscription_id, "write", context=f"vm run command {body.vm_name}")
    return await service.start_run_command(
        user=user,
        ip=request.client.host if request.client else None,
        subscription_id=body.subscription_id,
        resource_group=body.resource_group,
        vm_name=body.vm_name,
        script=body.script,
        timeout_seconds=body.timeout_seconds,
        confirm_name=body.confirm_name,
    )


@router.get("/resources/vms/run-command/{run_id}", summary="State and output of a VM run command")
async def get_run_command(
    run_id: str = Path(...),
    subscription_id: str = Query(...),
    resource_group: str = Query(...),
    vm_name: str = Query(...),
    user: UserContext = Depends(require_capability("infra_vm_run_command")),
    service: InfraResourceAdminService = Depends(_service),
) -> dict:
    assert_resource_access(subscription_id, "write", context=f"vm run command {vm_name}")
    return await service.get_run_command(
        subscription_id=subscription_id, resource_group=resource_group, vm_name=vm_name, run_id=run_id
    )


@router.get("/resources/vms/run-command-history", summary="Recent run commands on a VM (from the audit log)")
async def get_run_command_history(
    subscription_id: str = Query(...),
    resource_group: str = Query(...),
    vm_name: str = Query(...),
    user: UserContext = Depends(require_capability("infra_vm_run_command")),
    service: InfraResourceAdminService = Depends(_service),
) -> list[dict]:
    assert_resource_access(subscription_id, "write", context=f"vm run command history {vm_name}")
    return await service.run_command_history(subscription_id=subscription_id, vm_name=vm_name)


# ── VM administration ──────────────────────────────────────────────────


class VMTarget(BaseModel):
    subscription_id: str
    resource_group: str
    vm_name: str


class ResizeRequest(VMTarget):
    size: str = Field(..., min_length=3, max_length=100)


@router.get("/resources/vms/available-sizes", summary="Sizes a VM can be resized to")
async def get_available_sizes(
    subscription_id: str = Query(...),
    resource_group: str = Query(...),
    vm_name: str = Query(...),
    user: UserContext = Depends(get_current_user),
    service: InfraResourceAdminService = Depends(_service),
) -> list[dict]:
    assert_resource_access(subscription_id, "read", context=f"vm sizes {vm_name}")
    return await service.available_sizes(subscription_id, resource_group, vm_name)


@router.post("/resources/vms/resize", summary="Resize a VM (restarts it)")
async def resize_vm(
    request: Request,
    body: ResizeRequest = Body(...),
    user: UserContext = Depends(require_capability("infra_resource_admin")),
    db: AsyncSession = Depends(get_db),
    service: InfraResourceAdminService = Depends(_service),
) -> dict:
    assert_resource_access(body.subscription_id, "write", context=f"vm resize {body.vm_name}")
    return await _audited(
        db,
        request,
        user,
        action="virtual_machine_resize",
        resource_type="virtual_machine",
        name=body.vm_name,
        details=body.model_dump(),
        call=lambda: service.resize_vm(body.subscription_id, body.resource_group, body.vm_name, body.size),
    )


@router.post("/resources/vms/redeploy", summary="Redeploy a VM to a new Azure host (restarts it)")
async def redeploy_vm(
    request: Request,
    body: VMTarget = Body(...),
    user: UserContext = Depends(require_capability("infra_resource_admin")),
    db: AsyncSession = Depends(get_db),
    service: InfraResourceAdminService = Depends(_service),
) -> dict:
    assert_resource_access(body.subscription_id, "write", context=f"vm redeploy {body.vm_name}")
    return await _audited(
        db,
        request,
        user,
        action="virtual_machine_redeploy",
        resource_type="virtual_machine",
        name=body.vm_name,
        details=body.model_dump(),
        call=lambda: service.redeploy_vm(body.subscription_id, body.resource_group, body.vm_name),
    )


@router.get("/resources/vms/boot-diagnostics", summary="Serial console log of a VM")
async def get_boot_diagnostics(
    subscription_id: str = Query(...),
    resource_group: str = Query(...),
    vm_name: str = Query(...),
    user: UserContext = Depends(get_current_user),
    service: InfraResourceAdminService = Depends(_service),
) -> dict:
    assert_resource_access(subscription_id, "read", context=f"vm boot diagnostics {vm_name}")
    return await service.boot_diagnostics(subscription_id, resource_group, vm_name)


# ── Tags ───────────────────────────────────────────────────────────────


class TagsRequest(BaseModel):
    resource_id: str = Field(..., min_length=20)
    resource_type: str = Field(..., pattern="^(virtual_machine|pg_flex_server|storage_account|managed_disk)$")
    tags: dict[str, str] = Field(default_factory=dict)


@router.put("/resources/tags", summary="Replace a resource's tags")
async def replace_tags(
    request: Request,
    body: TagsRequest = Body(...),
    user: UserContext = Depends(require_capability("infra_resource_admin")),
    db: AsyncSession = Depends(get_db),
    service: InfraResourceAdminService = Depends(_service),
) -> dict:
    parts = body.resource_id.split("/")
    provider = "/".join(parts[6:8]) if len(parts) > 8 else ""
    if len(parts) != 9 or parts[1] != "subscriptions" or provider.lower() != RESOURCE_TYPES[body.resource_type].lower():
        raise HTTPException(status_code=422, detail="resource_id is not a resource of the given type")
    assert_resource_access(body.resource_id, "write", context=f"tags {parts[-1]}")
    return await _audited(
        db,
        request,
        user,
        action=f"{body.resource_type}_tags_update",
        resource_type=body.resource_type,
        name=parts[-1],
        details={"resource_id": body.resource_id, "subscription_id": parts[2], "tags": body.tags},
        call=lambda: service.replace_tags(body.resource_id, body.resource_type, body.tags),
    )


# ── Disks ──────────────────────────────────────────────────────────────


class DiskTarget(BaseModel):
    subscription_id: str
    resource_group: str
    disk_name: str


class ExpandDiskRequest(DiskTarget):
    size_gb: int = Field(..., ge=1, le=65536)


@router.post("/resources/disks/snapshot", summary="Create an incremental snapshot of a managed disk")
async def snapshot_disk(
    request: Request,
    body: DiskTarget = Body(...),
    user: UserContext = Depends(require_capability("infra_resource_admin")),
    db: AsyncSession = Depends(get_db),
    service: InfraResourceAdminService = Depends(_service),
) -> dict:
    assert_resource_access(body.subscription_id, "write", context=f"disk snapshot {body.disk_name}")
    return await _audited(
        db,
        request,
        user,
        action="managed_disk_snapshot",
        resource_type="managed_disk",
        name=body.disk_name,
        details=body.model_dump(),
        call=lambda: service.snapshot_disk(
            body.subscription_id, body.resource_group, body.disk_name, user.email or user.user_id
        ),
    )


@router.post("/resources/disks/expand", summary="Grow a managed disk")
async def expand_disk(
    request: Request,
    body: ExpandDiskRequest = Body(...),
    user: UserContext = Depends(require_capability("infra_resource_admin")),
    db: AsyncSession = Depends(get_db),
    service: InfraResourceAdminService = Depends(_service),
) -> dict:
    assert_resource_access(body.subscription_id, "write", context=f"disk expand {body.disk_name}")
    return await _audited(
        db,
        request,
        user,
        action="managed_disk_expand",
        resource_type="managed_disk",
        name=body.disk_name,
        details=body.model_dump(),
        call=lambda: service.expand_disk(body.subscription_id, body.resource_group, body.disk_name, body.size_gb),
    )


# ── PG Flexible Server ─────────────────────────────────────────────────


@router.get(
    "/resources/pg-servers/{subscription_id}/{resource_group}/{server_name}/overview",
    summary="Databases and firewall rules of a PG Flexible Server",
)
async def get_pg_overview(
    subscription_id: str = Path(...),
    resource_group: str = Path(...),
    server_name: str = Path(...),
    user: UserContext = Depends(get_current_user),
    service: InfraResourceAdminService = Depends(_service),
) -> dict:
    assert_resource_access(subscription_id, "read", context=f"pg overview {server_name}")
    return await service.pg_overview(subscription_id, resource_group, server_name)
