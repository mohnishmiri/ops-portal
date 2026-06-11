"""
Azure Resource Listing Service — Lists VMs, Storage Accounts, Disks, and other cloud resources.

Caches Azure SDK clients for performance.
Saves discovered resources to PostgreSQL for inventory tracking.
"""

import asyncio
from datetime import datetime
from typing import Any

import structlog
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.subscription_scope import get_scoped_subscription_ids
from app.models.database import AzureResourceInventory

logger = structlog.get_logger(__name__)

# Lazy imports for Azure SDK — avoids hard failure if packages missing
_azure_available = False
_pg_flex_available = False
try:
    from azure.identity import DefaultAzureCredential
    from azure.mgmt.compute import ComputeManagementClient
    from azure.mgmt.network import NetworkManagementClient
    from azure.mgmt.storage import StorageManagementClient

    _azure_available = True
except ImportError as _import_err:
    logger.warning(
        "azure_sdk_not_available",
        error=str(_import_err),
        hint="Install azure-mgmt-compute, azure-mgmt-storage, azure-mgmt-network",
    )

try:
    from azure.mgmt.rdbms.postgresql_flexibleservers import (
        PostgreSQLManagementClient as PostgreSQLFlexibleManagementClient,
    )

    _pg_flex_available = True
except ImportError as _pg_err:
    logger.warning(
        "azure_pg_flex_sdk_not_available",
        error=str(_pg_err),
        hint="Install azure-mgmt-rdbms",
    )


class AzureResourceService:
    """
    Service for listing and caching Azure resources.

    Supports:
    - Virtual Machines
    - Storage Accounts (with containers/blobs)
    - Managed Disks
    - Network Security Groups
    - Public IP Addresses
    - Load Balancers
    """

    def __init__(self, db_session: AsyncSession | None = None):
        self.db = db_session
        self._credential = None
        self._compute_client = None
        self._storage_client = None
        self._network_client = None
        self._pg_client = None
        # Use first subscription from AZURE_SUBSCRIPTION_IDS (comma-separated)
        sub_ids = settings.subscription_ids if hasattr(settings, "subscription_ids") else []
        self.subscription_id = sub_ids[0] if sub_ids else ""
        self._subscription_resolved = False

    async def _ensure_ready(self) -> None:
        """Resolve subscription from admin DB (once) then validate Azure."""
        if not self._subscription_resolved:
            try:
                monitored = await get_scoped_subscription_ids()
                if monitored:
                    self.subscription_id = monitored[0]
            except Exception:
                pass  # keep env fallback set in __init__
            self._subscription_resolved = True
        self._ensure_azure_available()

    async def _resolve_scoped_subscription_ids(self) -> list[str]:
        return await get_scoped_subscription_ids()

    async def _get_target_subscription_ids(self) -> list[str]:
        await self._ensure_ready()
        subscription_ids = await self._resolve_scoped_subscription_ids()
        if subscription_ids:
            return subscription_ids
        return [self.subscription_id] if self.subscription_id else []

    def _ensure_azure_available(self) -> None:
        """Raise a clear error if Azure SDK packages are not installed."""
        if not _azure_available:
            raise RuntimeError(
                "Azure SDK packages not installed. Run: "
                "uv add azure-identity azure-mgmt-compute azure-mgmt-storage azure-mgmt-network"
            )
        if not self.subscription_id:
            raise RuntimeError(
                "AZURE_SUBSCRIPTION_IDS is not configured. Set it in .env (comma-separated subscription IDs)."
            )

    def _get_credential(self):
        """Get or create Azure credential."""
        self._ensure_azure_available()
        if self._credential is None:
            self._credential = DefaultAzureCredential()
        return self._credential

    def _get_compute_client(self):
        """Get or create Compute Management client."""
        if self._compute_client is None:
            self._compute_client = ComputeManagementClient(
                credential=self._get_credential(),
                subscription_id=self.subscription_id,
            )
        return self._compute_client

    def _get_storage_client(self):
        """Get or create Storage Management client."""
        if self._storage_client is None:
            self._storage_client = StorageManagementClient(
                credential=self._get_credential(),
                subscription_id=self.subscription_id,
            )
        return self._storage_client

    def _get_network_client(self):
        """Get or create Network Management client."""
        if self._network_client is None:
            self._network_client = NetworkManagementClient(
                credential=self._get_credential(),
                subscription_id=self.subscription_id,
            )
        return self._network_client

    def _get_pg_client(self):
        """Get or create PostgreSQL Flexible Server Management client."""
        if not _pg_flex_available:
            raise RuntimeError("azure-mgmt-rdbms package not installed. Run: uv add azure-mgmt-rdbms")
        if self._pg_client is None:
            self._pg_client = PostgreSQLFlexibleManagementClient(
                credential=self._get_credential(),
                subscription_id=self.subscription_id,
            )
        return self._pg_client

    # ── Virtual Machines ─────────────────────────────────────────────────

    async def list_vms(
        self,
        resource_group: str | None = None,
        save_to_db: bool = False,
    ) -> list[dict[str, Any]]:
        """List all VMs in subscription or resource group."""
        try:
            subscription_ids = await self._get_target_subscription_ids()

            def _fetch_vms() -> list[dict[str, Any]]:
                results = []
                for subscription_id in subscription_ids:
                    compute = ComputeManagementClient(
                        credential=self._get_credential(),
                        subscription_id=subscription_id,
                    )

                    try:
                        if resource_group:
                            vms = list(compute.virtual_machines.list(resource_group, expand="instanceView"))
                        else:
                            vms = list(compute.virtual_machines.list_all(expand="instanceView"))
                        has_instance_view = True
                    except Exception:
                        logger.warning(
                            "instanceView_expand_failed_fallback",
                            subscription_id=subscription_id,
                        )
                        if resource_group:
                            vms = list(compute.virtual_machines.list(resource_group))
                        else:
                            vms = list(compute.virtual_machines.list_all())
                        has_instance_view = False

                    for vm in vms:
                        power_state = None
                        if has_instance_view and vm.instance_view and vm.instance_view.statuses:
                            for status in vm.instance_view.statuses:
                                if status.code and status.code.startswith("PowerState/"):
                                    power_state = status.code.replace("PowerState/", "")
                                    break

                        vm_data = {
                            "id": vm.id,
                            "name": vm.name,
                            "location": vm.location,
                            "resource_group": vm.id.split("/")[4] if vm.id else "",
                            "vm_size": (
                                str(vm.hardware_profile.vm_size)
                                if vm.hardware_profile and vm.hardware_profile.vm_size
                                else None
                            ),
                            "os_type": (
                                str(vm.storage_profile.os_disk.os_type)
                                if vm.storage_profile
                                and vm.storage_profile.os_disk
                                and vm.storage_profile.os_disk.os_type
                                else None
                            ),
                            "provisioning_state": (str(vm.provisioning_state) if vm.provisioning_state else None),
                            "tags": dict(vm.tags) if vm.tags else {},
                            "power_state": power_state,
                            "subscription_id": subscription_id,
                            "resource_type": "virtual_machine",
                        }
                        results.append(vm_data)
                return results

            results = await asyncio.to_thread(_fetch_vms)

            logger.info("vms_listed", count=len(results), resource_group=resource_group)

            if save_to_db and self.db:
                await self._save_resources_to_db(results, "virtual_machine")

            return results

        except Exception as e:
            logger.error("list_vms_failed", error=str(e))
            raise

    async def get_vm_details(
        self,
        resource_group: str,
        vm_name: str,
        subscription_id: str | None = None,
    ) -> dict[str, Any] | None:
        """Get detailed VM information including power state."""
        try:
            await self._ensure_ready()
            effective_subscription_id = subscription_id or self.subscription_id
            compute = ComputeManagementClient(
                credential=self._get_credential(),
                subscription_id=effective_subscription_id,
            )

            def _fetch() -> dict[str, Any]:
                vm = compute.virtual_machines.get(resource_group, vm_name, expand="instanceView")

                power_state = None
                if vm.instance_view and vm.instance_view.statuses:
                    for status in vm.instance_view.statuses:
                        if status.code and status.code.startswith("PowerState/"):
                            power_state = status.code.replace("PowerState/", "")
                            break

                return {
                    "id": vm.id,
                    "name": vm.name,
                    "location": vm.location,
                    "resource_group": resource_group,
                    "vm_size": (vm.hardware_profile.vm_size if vm.hardware_profile else None),
                    "os_type": (
                        str(vm.storage_profile.os_disk.os_type)
                        if vm.storage_profile and vm.storage_profile.os_disk
                        else None
                    ),
                    "os_disk_name": (
                        vm.storage_profile.os_disk.name if vm.storage_profile and vm.storage_profile.os_disk else None
                    ),
                    "os_disk_size_gb": (
                        vm.storage_profile.os_disk.disk_size_gb
                        if vm.storage_profile and vm.storage_profile.os_disk
                        else None
                    ),
                    "data_disks": (
                        [
                            {"name": d.name, "size_gb": d.disk_size_gb, "lun": d.lun}
                            for d in (vm.storage_profile.data_disks or [])
                        ]
                        if vm.storage_profile
                        else []
                    ),
                    "provisioning_state": vm.provisioning_state,
                    "power_state": power_state,
                    "tags": dict(vm.tags) if vm.tags else {},
                    "subscription_id": effective_subscription_id,
                }

            return await asyncio.to_thread(_fetch)

        except Exception as e:
            logger.error("get_vm_details_failed", vm=vm_name, error=str(e))
            return None

    # ── VM Power Management ──────────────────────────────────────────────

    async def start_vm(self, resource_group: str, vm_name: str) -> dict[str, Any]:
        """Start a virtual machine."""
        try:
            self._ensure_azure_available()
            compute = self._get_compute_client()

            def _start() -> None:
                poller = compute.virtual_machines.begin_start(resource_group, vm_name)
                poller.wait()

            await asyncio.to_thread(_start)
            logger.info("vm_started", vm=vm_name, resource_group=resource_group)
            return {
                "status": "success",
                "action": "start",
                "vm_name": vm_name,
                "resource_group": resource_group,
            }
        except Exception as e:
            logger.error("start_vm_failed", vm=vm_name, error=str(e))
            raise

    async def stop_vm(self, resource_group: str, vm_name: str) -> dict[str, Any]:
        """Stop (deallocate) a virtual machine."""
        try:
            self._ensure_azure_available()
            compute = self._get_compute_client()

            def _deallocate() -> None:
                poller = compute.virtual_machines.begin_deallocate(resource_group, vm_name)
                poller.wait()

            await asyncio.to_thread(_deallocate)
            logger.info("vm_stopped", vm=vm_name, resource_group=resource_group)
            return {
                "status": "success",
                "action": "deallocate",
                "vm_name": vm_name,
                "resource_group": resource_group,
            }
        except Exception as e:
            logger.error("stop_vm_failed", vm=vm_name, error=str(e))
            raise

    async def restart_vm(self, resource_group: str, vm_name: str) -> dict[str, Any]:
        """Restart a virtual machine."""
        try:
            self._ensure_azure_available()
            compute = self._get_compute_client()

            def _restart() -> None:
                poller = compute.virtual_machines.begin_restart(resource_group, vm_name)
                poller.wait()

            await asyncio.to_thread(_restart)
            logger.info("vm_restarted", vm=vm_name, resource_group=resource_group)
            return {
                "status": "success",
                "action": "restart",
                "vm_name": vm_name,
                "resource_group": resource_group,
            }
        except Exception as e:
            logger.error("restart_vm_failed", vm=vm_name, error=str(e))
            raise

    # ── PG Flex Server Power Management ──────────────────────────────────

    async def start_pg_server(self, resource_group: str, server_name: str) -> dict[str, Any]:
        """Start a PostgreSQL Flexible Server."""
        try:
            self._ensure_azure_available()
            pg_client = self._get_pg_client()

            def _start() -> None:
                poller = pg_client.servers.begin_start(resource_group, server_name)
                poller.wait()

            await asyncio.to_thread(_start)
            logger.info("pg_server_started", server=server_name, resource_group=resource_group)
            return {
                "status": "success",
                "action": "start",
                "server_name": server_name,
                "resource_group": resource_group,
            }
        except Exception as e:
            logger.error("start_pg_server_failed", server=server_name, error=str(e))
            raise

    async def stop_pg_server(self, resource_group: str, server_name: str) -> dict[str, Any]:
        """Stop a PostgreSQL Flexible Server."""
        try:
            self._ensure_azure_available()
            pg_client = self._get_pg_client()

            def _stop() -> None:
                poller = pg_client.servers.begin_stop(resource_group, server_name)
                poller.wait()

            await asyncio.to_thread(_stop)
            logger.info("pg_server_stopped", server=server_name, resource_group=resource_group)
            return {
                "status": "success",
                "action": "stop",
                "server_name": server_name,
                "resource_group": resource_group,
            }
        except Exception as e:
            logger.error("stop_pg_server_failed", server=server_name, error=str(e))
            raise

    async def restart_pg_server(self, resource_group: str, server_name: str) -> dict[str, Any]:
        """Restart a PostgreSQL Flexible Server."""
        try:
            self._ensure_azure_available()
            pg_client = self._get_pg_client()

            def _restart() -> None:
                poller = pg_client.servers.begin_restart(resource_group, server_name, None)
                poller.wait()

            await asyncio.to_thread(_restart)
            logger.info("pg_server_restarted", server=server_name, resource_group=resource_group)
            return {
                "status": "success",
                "action": "restart",
                "server_name": server_name,
                "resource_group": resource_group,
            }
        except Exception as e:
            logger.error("restart_pg_server_failed", server=server_name, error=str(e))
            raise

    # ── Storage Accounts ─────────────────────────────────────────────────

    async def list_storage_accounts(
        self,
        resource_group: str | None = None,
        save_to_db: bool = False,
    ) -> list[dict[str, Any]]:
        """List all storage accounts."""
        try:
            subscription_ids = await self._get_target_subscription_ids()

            def _fetch() -> list[dict[str, Any]]:
                results = []
                for subscription_id in subscription_ids:
                    storage = StorageManagementClient(
                        credential=self._get_credential(),
                        subscription_id=subscription_id,
                    )
                    if resource_group:
                        accounts = storage.storage_accounts.list_by_resource_group(resource_group)
                    else:
                        accounts = storage.storage_accounts.list()

                    for acc in accounts:
                        acc_data = {
                            "id": acc.id,
                            "name": acc.name,
                            "location": acc.location,
                            "resource_group": acc.id.split("/")[4] if acc.id else "",
                            "kind": str(acc.kind) if acc.kind else None,
                            "sku_name": acc.sku.name if acc.sku else None,
                            "sku": acc.sku.name if acc.sku else None,
                            "sku_tier": str(acc.sku.tier) if acc.sku else None,
                            "access_tier": (str(acc.access_tier) if acc.access_tier else None),
                            "provisioning_state": (str(acc.provisioning_state) if acc.provisioning_state else None),
                            "creation_time": (acc.creation_time.isoformat() if acc.creation_time else None),
                            "primary_location": acc.primary_location,
                            "https_only": acc.enable_https_traffic_only,
                            "allow_blob_public_access": acc.allow_blob_public_access,
                            "minimum_tls_version": (str(acc.minimum_tls_version) if acc.minimum_tls_version else None),
                            "tags": dict(acc.tags) if acc.tags else {},
                            "subscription_id": subscription_id,
                            "resource_type": "storage_account",
                        }
                        results.append(acc_data)
                return results

            results = await asyncio.to_thread(_fetch)

            logger.info("storage_accounts_listed", count=len(results))

            if save_to_db and self.db:
                await self._save_resources_to_db(results, "storage_account")

            return results

        except Exception as e:
            logger.error("list_storage_accounts_failed", error=str(e))
            raise

    async def get_storage_account_details(
        self,
        resource_group: str,
        account_name: str,
    ) -> dict[str, Any] | None:
        """Get detailed storage account info."""
        try:
            self._ensure_azure_available()
            storage = self._get_storage_client()

            def _fetch() -> dict[str, Any]:
                acc = storage.storage_accounts.get_properties(resource_group, account_name)
                return {
                    "id": acc.id,
                    "name": acc.name,
                    "location": acc.location,
                    "resource_group": resource_group,
                    "kind": str(acc.kind) if acc.kind else None,
                    "sku_name": acc.sku.name if acc.sku else None,
                    "sku_tier": str(acc.sku.tier) if acc.sku else None,
                    "access_tier": str(acc.access_tier) if acc.access_tier else None,
                    "provisioning_state": (str(acc.provisioning_state) if acc.provisioning_state else None),
                    "creation_time": (acc.creation_time.isoformat() if acc.creation_time else None),
                    "primary_location": acc.primary_location,
                    "secondary_location": acc.secondary_location,
                    "primary_endpoints": (
                        {
                            "blob": (acc.primary_endpoints.blob if acc.primary_endpoints else None),
                            "file": (acc.primary_endpoints.file if acc.primary_endpoints else None),
                            "table": (acc.primary_endpoints.table if acc.primary_endpoints else None),
                            "queue": (acc.primary_endpoints.queue if acc.primary_endpoints else None),
                        }
                        if acc.primary_endpoints
                        else {}
                    ),
                    "https_only": acc.enable_https_traffic_only,
                    "allow_blob_public_access": acc.allow_blob_public_access,
                    "minimum_tls_version": (str(acc.minimum_tls_version) if acc.minimum_tls_version else None),
                    "network_rules": (
                        {
                            "default_action": (
                                str(acc.network_rule_set.default_action) if acc.network_rule_set else None
                            ),
                            "bypass": (str(acc.network_rule_set.bypass) if acc.network_rule_set else None),
                        }
                        if acc.network_rule_set
                        else {}
                    ),
                    "tags": dict(acc.tags) if acc.tags else {},
                    "subscription_id": self.subscription_id,
                }

            return await asyncio.to_thread(_fetch)

        except Exception as e:
            logger.error("get_storage_account_failed", account=account_name, error=str(e))
            return None

    # ── Managed Disks ────────────────────────────────────────────────────

    async def list_disks(
        self,
        resource_group: str | None = None,
        save_to_db: bool = False,
    ) -> list[dict[str, Any]]:
        """List all managed disks."""
        try:
            subscription_ids = await self._get_target_subscription_ids()

            def _fetch() -> list[dict[str, Any]]:
                results = []
                for subscription_id in subscription_ids:
                    compute = ComputeManagementClient(
                        credential=self._get_credential(),
                        subscription_id=subscription_id,
                    )
                    if resource_group:
                        disks = compute.disks.list_by_resource_group(resource_group)
                    else:
                        disks = compute.disks.list()

                    for disk in disks:
                        disk_data = {
                            "id": disk.id,
                            "name": disk.name,
                            "location": disk.location,
                            "resource_group": disk.id.split("/")[4] if disk.id else "",
                            "sku_name": disk.sku.name if disk.sku else None,
                            "sku": disk.sku.name if disk.sku else None,
                            "sku_tier": disk.sku.tier if disk.sku else None,
                            "disk_size_gb": disk.disk_size_gb,
                            "size_gb": disk.disk_size_gb,
                            "disk_state": (str(disk.disk_state) if disk.disk_state else None),
                            "os_type": str(disk.os_type) if disk.os_type else None,
                            "provisioning_state": disk.provisioning_state,
                            "time_created": (disk.time_created.isoformat() if disk.time_created else None),
                            "disk_iops_read_write": disk.disk_iops_read_write,
                            "disk_mbps_read_write": disk.disk_m_bps_read_write,
                            "encryption_type": (str(disk.encryption.type) if disk.encryption else None),
                            "managed_by": disk.managed_by,
                            "zones": list(disk.zones) if disk.zones else [],
                            "tags": dict(disk.tags) if disk.tags else {},
                            "subscription_id": subscription_id,
                            "resource_type": "managed_disk",
                        }
                        results.append(disk_data)
                return results

            results = await asyncio.to_thread(_fetch)

            logger.info("disks_listed", count=len(results))

            if save_to_db and self.db:
                await self._save_resources_to_db(results, "managed_disk")

            return results

        except Exception as e:
            logger.error("list_disks_failed", error=str(e))
            raise

    async def get_disk_details(
        self,
        resource_group: str,
        disk_name: str,
    ) -> dict[str, Any] | None:
        """Get detailed disk information."""
        try:
            self._ensure_azure_available()
            compute = self._get_compute_client()

            def _fetch() -> dict[str, Any]:
                disk = compute.disks.get(resource_group, disk_name)
                return {
                    "id": disk.id,
                    "name": disk.name,
                    "location": disk.location,
                    "resource_group": resource_group,
                    "sku_name": disk.sku.name if disk.sku else None,
                    "sku": disk.sku.name if disk.sku else None,  # alias for frontend
                    "sku_tier": disk.sku.tier if disk.sku else None,
                    "disk_size_gb": disk.disk_size_gb,
                    "size_gb": disk.disk_size_gb,  # alias for frontend
                    "disk_state": str(disk.disk_state) if disk.disk_state else None,
                    "os_type": str(disk.os_type) if disk.os_type else None,
                    "provisioning_state": disk.provisioning_state,
                    "time_created": (disk.time_created.isoformat() if disk.time_created else None),
                    "disk_iops_read_write": disk.disk_iops_read_write,
                    "disk_mbps_read_write": disk.disk_m_bps_read_write,
                    "encryption_type": (str(disk.encryption.type) if disk.encryption else None),
                    "managed_by": disk.managed_by,
                    "network_access_policy": (str(disk.network_access_policy) if disk.network_access_policy else None),
                    "zones": list(disk.zones) if disk.zones else [],
                    "tags": dict(disk.tags) if disk.tags else {},
                    "subscription_id": self.subscription_id,
                }

            return await asyncio.to_thread(_fetch)

        except Exception as e:
            logger.error("get_disk_details_failed", disk=disk_name, error=str(e))
            return None

    def _get_compute_client_for_subscription(self, subscription_id: str):
        """Create a Compute client scoped to a specific subscription."""
        return ComputeManagementClient(
            credential=self._get_credential(),
            subscription_id=subscription_id,
        )

    def _get_network_client_for_subscription(self, subscription_id: str):
        """Create a Network client scoped to a specific subscription."""
        return NetworkManagementClient(
            credential=self._get_credential(),
            subscription_id=subscription_id,
        )

    async def delete_unattached_disk(
        self,
        subscription_id: str,
        resource_group: str,
        disk_name: str,
    ) -> dict[str, Any]:
        """Delete a managed disk only when it is unattached."""
        self._ensure_azure_available()
        compute = self._get_compute_client_for_subscription(subscription_id)

        def _delete() -> dict[str, Any]:
            disk = compute.disks.get(resource_group, disk_name)
            disk_state = str(disk.disk_state) if disk.disk_state else ""
            managed_by = disk.managed_by or ""
            if disk_state != "Unattached" or managed_by:
                raise ValueError(
                    f"Disk '{disk_name}' is not unattached (state={disk_state or 'unknown'}). "
                    "Only unattached disks can be deleted."
                )
            poller = compute.disks.begin_delete(resource_group, disk_name)
            poller.wait()
            return {
                "status": "success",
                "action": "delete",
                "resource_name": disk_name,
                "resource_group": resource_group,
                "subscription_id": subscription_id,
            }

        try:
            result = await asyncio.to_thread(_delete)
            logger.info(
                "disk_deleted",
                disk=disk_name,
                resource_group=resource_group,
                subscription_id=subscription_id,
            )
            return result
        except ValueError:
            raise
        except Exception as e:
            logger.error("delete_unattached_disk_failed", disk=disk_name, error=str(e))
            raise

    async def delete_disconnected_private_endpoint(
        self,
        subscription_id: str,
        resource_group: str,
        endpoint_name: str,
    ) -> dict[str, Any]:
        """Delete a private endpoint only when all connections are disconnected."""
        self._ensure_azure_available()
        network = self._get_network_client_for_subscription(subscription_id)

        def _connection_statuses(endpoint) -> list[str]:
            statuses: list[str] = []
            for conn in endpoint.private_link_service_connections or []:
                state = conn.private_link_service_connection_state
                if state and state.status:
                    statuses.append(str(state.status))
            for conn in endpoint.manual_private_link_service_connections or []:
                state = conn.private_link_service_connection_state
                if state and state.status:
                    statuses.append(str(state.status))
            return statuses

        def _delete() -> dict[str, Any]:
            endpoint = network.private_endpoints.get(resource_group, endpoint_name)
            statuses = _connection_statuses(endpoint)
            if not statuses:
                raise ValueError(
                    f"Private endpoint '{endpoint_name}' has no private link connections to evaluate."
                )
            active = {s for s in statuses if s.lower() not in ("disconnected", "rejected")}
            if active:
                raise ValueError(
                    f"Private endpoint '{endpoint_name}' has active connections ({', '.join(sorted(active))}). "
                    "Only fully disconnected endpoints can be deleted."
                )
            if not any(s.lower() == "disconnected" for s in statuses):
                raise ValueError(
                    f"Private endpoint '{endpoint_name}' has no disconnected connections."
                )
            poller = network.private_endpoints.begin_delete(resource_group, endpoint_name)
            poller.wait()
            return {
                "status": "success",
                "action": "delete",
                "resource_name": endpoint_name,
                "resource_group": resource_group,
                "subscription_id": subscription_id,
            }

        try:
            result = await asyncio.to_thread(_delete)
            logger.info(
                "private_endpoint_deleted",
                endpoint=endpoint_name,
                resource_group=resource_group,
                subscription_id=subscription_id,
            )
            return result
        except ValueError:
            raise
        except Exception as e:
            logger.error(
                "delete_disconnected_private_endpoint_failed",
                endpoint=endpoint_name,
                error=str(e),
            )
            raise

    # ── PostgreSQL Flexible Servers ──────────────────────────────────────

    async def list_pg_flex_servers(
        self,
        resource_group: str | None = None,
        save_to_db: bool = False,
    ) -> list[dict[str, Any]]:
        """List all PostgreSQL Flexible Servers in subscription or resource group."""
        try:
            subscription_ids = await self._get_target_subscription_ids()

            def _fetch() -> list[dict[str, Any]]:
                results = []
                for subscription_id in subscription_ids:
                    pg_client = PostgreSQLFlexibleManagementClient(
                        credential=self._get_credential(),
                        subscription_id=subscription_id,
                    )
                    if resource_group:
                        servers = list(pg_client.servers.list_by_resource_group(resource_group))
                    else:
                        servers = list(pg_client.servers.list())

                    for srv in servers:
                        storage_gb = None
                        if srv.storage and srv.storage.storage_size_gb:
                            storage_gb = srv.storage.storage_size_gb

                        srv_data = {
                            "id": srv.id,
                            "name": srv.name,
                            "location": srv.location,
                            "resource_group": srv.id.split("/")[4] if srv.id else "",
                            "sku_name": srv.sku.name if srv.sku else None,
                            "sku_tier": (str(srv.sku.tier) if srv.sku and srv.sku.tier else None),
                            "version": str(srv.version) if srv.version else None,
                            "state": str(srv.state) if srv.state else None,
                            "fully_qualified_domain_name": srv.fully_qualified_domain_name,
                            "storage_size_gb": storage_gb,
                            "backup_retention_days": (srv.backup.backup_retention_days if srv.backup else None),
                            "geo_redundant_backup": (str(srv.backup.geo_redundant_backup) if srv.backup else None),
                            "high_availability_mode": (
                                str(srv.high_availability.mode) if srv.high_availability else None
                            ),
                            "high_availability_state": (
                                str(srv.high_availability.state) if srv.high_availability else None
                            ),
                            "admin_login": srv.administrator_login,
                            "provisioning_state": str(srv.state) if srv.state else None,
                            "tags": dict(srv.tags) if srv.tags else {},
                            "subscription_id": subscription_id,
                            "resource_type": "pg_flex_server",
                        }
                        results.append(srv_data)
                return results

            results = await asyncio.to_thread(_fetch)
            logger.info("pg_flex_servers_listed", count=len(results))

            if save_to_db and self.db:
                await self._save_resources_to_db(results, "pg_flex_server")

            return results

        except Exception as e:
            logger.error("list_pg_flex_servers_failed", error=str(e))
            raise

    # ── Network Resources ────────────────────────────────────────────────

    async def list_network_security_groups(
        self,
        resource_group: str | None = None,
        save_to_db: bool = False,
    ) -> list[dict[str, Any]]:
        """List all network security groups."""
        try:
            self._ensure_azure_available()
            network = self._get_network_client()

            def _fetch() -> list[dict[str, Any]]:
                if resource_group:
                    nsgs = network.network_security_groups.list(resource_group)
                else:
                    nsgs = network.network_security_groups.list_all()

                results = []
                for nsg in nsgs:
                    nsg_data = {
                        "id": nsg.id,
                        "name": nsg.name,
                        "location": nsg.location,
                        "resource_group": nsg.id.split("/")[4] if nsg.id else "",
                        "provisioning_state": (str(nsg.provisioning_state) if nsg.provisioning_state else None),
                        "security_rules_count": (len(nsg.security_rules) if nsg.security_rules else 0),
                        "default_rules_count": (len(nsg.default_security_rules) if nsg.default_security_rules else 0),
                        "subnets": [s.id for s in (nsg.subnets or [])],
                        "network_interfaces": [ni.id for ni in (nsg.network_interfaces or [])],
                        "tags": dict(nsg.tags) if nsg.tags else {},
                        "subscription_id": self.subscription_id,
                        "resource_type": "network_security_group",
                    }
                    results.append(nsg_data)
                return results

            results = await asyncio.to_thread(_fetch)

            logger.info("nsgs_listed", count=len(results))

            if save_to_db and self.db:
                await self._save_resources_to_db(results, "network_security_group")

            return results

        except Exception as e:
            logger.error("list_nsgs_failed", error=str(e))
            raise

    async def list_public_ips(
        self,
        resource_group: str | None = None,
        save_to_db: bool = False,
    ) -> list[dict[str, Any]]:
        """List all public IP addresses."""
        try:
            self._ensure_azure_available()
            network = self._get_network_client()

            def _fetch() -> list[dict[str, Any]]:
                if resource_group:
                    pips = network.public_ip_addresses.list(resource_group)
                else:
                    pips = network.public_ip_addresses.list_all()

                results = []
                for pip in pips:
                    pip_data = {
                        "id": pip.id,
                        "name": pip.name,
                        "location": pip.location,
                        "resource_group": pip.id.split("/")[4] if pip.id else "",
                        "sku_name": pip.sku.name if pip.sku else None,
                        "sku_tier": pip.sku.tier if pip.sku else None,
                        "ip_address": pip.ip_address,
                        "public_ip_allocation_method": (
                            str(pip.public_ip_allocation_method) if pip.public_ip_allocation_method else None
                        ),
                        "public_ip_address_version": (
                            str(pip.public_ip_address_version) if pip.public_ip_address_version else None
                        ),
                        "provisioning_state": (str(pip.provisioning_state) if pip.provisioning_state else None),
                        "dns_fqdn": pip.dns_settings.fqdn if pip.dns_settings else None,
                        "idle_timeout_minutes": pip.idle_timeout_in_minutes,
                        "zones": list(pip.zones) if pip.zones else [],
                        "tags": dict(pip.tags) if pip.tags else {},
                        "subscription_id": self.subscription_id,
                        "resource_type": "public_ip",
                    }
                    results.append(pip_data)
                return results

            results = await asyncio.to_thread(_fetch)

            logger.info("public_ips_listed", count=len(results))

            if save_to_db and self.db:
                await self._save_resources_to_db(results, "public_ip")

            return results

        except Exception as e:
            logger.error("list_public_ips_failed", error=str(e))
            raise

    async def list_load_balancers(
        self,
        resource_group: str | None = None,
        save_to_db: bool = False,
    ) -> list[dict[str, Any]]:
        """List all load balancers."""
        try:
            self._ensure_azure_available()
            network = self._get_network_client()

            def _fetch() -> list[dict[str, Any]]:
                if resource_group:
                    lbs = network.load_balancers.list(resource_group)
                else:
                    lbs = network.load_balancers.list_all()

                results = []
                for lb in lbs:
                    lb_data = {
                        "id": lb.id,
                        "name": lb.name,
                        "location": lb.location,
                        "resource_group": lb.id.split("/")[4] if lb.id else "",
                        "sku_name": lb.sku.name if lb.sku else None,
                        "sku_tier": lb.sku.tier if lb.sku else None,
                        "provisioning_state": (str(lb.provisioning_state) if lb.provisioning_state else None),
                        "frontend_ip_count": (
                            len(lb.frontend_ip_configurations) if lb.frontend_ip_configurations else 0
                        ),
                        "backend_pool_count": (len(lb.backend_address_pools) if lb.backend_address_pools else 0),
                        "probe_count": len(lb.probes) if lb.probes else 0,
                        "rule_count": (len(lb.load_balancing_rules) if lb.load_balancing_rules else 0),
                        "nat_rule_count": (len(lb.inbound_nat_rules) if lb.inbound_nat_rules else 0),
                        "tags": dict(lb.tags) if lb.tags else {},
                        "subscription_id": self.subscription_id,
                        "resource_type": "load_balancer",
                    }
                    results.append(lb_data)
                return results

            results = await asyncio.to_thread(_fetch)

            logger.info("load_balancers_listed", count=len(results))

            if save_to_db and self.db:
                await self._save_resources_to_db(results, "load_balancer")

            return results

        except Exception as e:
            logger.error("list_load_balancers_failed", error=str(e))
            raise

    # ── Combined Resource Inventory ──────────────────────────────────────

    async def list_all_resources(
        self,
        resource_group: str | None = None,
        save_to_db: bool = True,
    ) -> dict[str, Any]:
        """List all supported Azure resources."""
        results = {
            "virtual_machines": await self.list_vms(resource_group, save_to_db),
            "storage_accounts": await self.list_storage_accounts(resource_group, save_to_db),
            "managed_disks": await self.list_disks(resource_group, save_to_db),
            "network_security_groups": await self.list_network_security_groups(resource_group, save_to_db),
            "public_ips": await self.list_public_ips(resource_group, save_to_db),
            "load_balancers": await self.list_load_balancers(resource_group, save_to_db),
            "last_sync": datetime.utcnow().isoformat(),
        }

        totals = {k: len(v) for k, v in results.items() if isinstance(v, list)}
        logger.info("all_resources_listed", totals=totals, resource_group=resource_group)

        return results

    # ── Database Operations ──────────────────────────────────────────────

    async def _save_resources_to_db(
        self,
        resources: list[dict[str, Any]],
        resource_type: str,
    ) -> None:
        """Save resources to database inventory table."""
        if not self.db:
            return

        try:
            # Delete existing resources of this type
            await self.db.execute(
                delete(AzureResourceInventory).where(AzureResourceInventory.resource_type == resource_type)
            )

            # Insert new resources
            for res in resources:
                record = AzureResourceInventory(
                    resource_id=res.get("id", ""),
                    name=res.get("name", ""),
                    resource_type=resource_type,
                    resource_group=res.get("resource_group", ""),
                    location=res.get("location", ""),
                    subscription_id=res.get("subscription_id", ""),
                    provisioning_state=res.get("provisioning_state"),
                    tags=res.get("tags", {}),
                    resource_details=res,
                )
                self.db.add(record)

            await self.db.commit()
            logger.info(
                "resources_saved_to_db",
                resource_type=resource_type,
                count=len(resources),
            )

        except Exception as e:
            logger.error("save_resources_failed", resource_type=resource_type, error=str(e))
            await self.db.rollback()
            raise

    async def get_inventory_from_db(
        self,
        resource_type: str | None = None,
        resource_group: str | None = None,
    ) -> list[dict[str, Any]]:
        """Get resource inventory from database."""
        if not self.db:
            return []

        scoped_subscription_ids = await self._resolve_scoped_subscription_ids()

        query = select(AzureResourceInventory).where(
            AzureResourceInventory.subscription_id.in_(scoped_subscription_ids)
        )

        if resource_type:
            query = query.where(AzureResourceInventory.resource_type == resource_type)
        if resource_group:
            query = query.where(AzureResourceInventory.resource_group == resource_group)

        query = query.order_by(AzureResourceInventory.name)
        result = await self.db.execute(query)
        records = result.scalars().all()

        return [
            {
                "id": r.id,
                "resource_id": r.resource_id,
                "name": r.name,
                "resource_type": r.resource_type,
                "resource_group": r.resource_group,
                "location": r.location,
                "subscription_id": r.subscription_id,
                "provisioning_state": r.provisioning_state,
                "tags": r.tags,
                "resource_details": r.resource_details,
                "last_sync": r.last_sync.isoformat() if r.last_sync else None,
            }
            for r in records
        ]

    async def get_inventory_summary(self) -> dict[str, Any]:
        """Get summary counts of resource inventory."""
        if not self.db:
            return {}

        scoped_subscription_ids = await self._resolve_scoped_subscription_ids()
        query = select(AzureResourceInventory).where(
            AzureResourceInventory.subscription_id.in_(scoped_subscription_ids)
        )

        result = await self.db.execute(query)
        rows = result.scalars().all()

        by_type: dict[str, int] = {}
        by_location: dict[str, int] = {}
        by_subscription: dict[str, int] = {}
        latest_sync = None

        for row in rows:
            by_type[row.resource_type] = by_type.get(row.resource_type, 0) + 1
            by_location[row.location or "unknown"] = by_location.get(row.location or "unknown", 0) + 1
            by_subscription[row.subscription_id] = by_subscription.get(row.subscription_id, 0) + 1
            if row.last_sync and (latest_sync is None or row.last_sync > latest_sync):
                latest_sync = row.last_sync

        return {
            "total_resources": len(rows),
            "by_type": by_type,
            "by_location": by_location,
            "by_subscription": by_subscription,
            "last_sync_at": latest_sync.isoformat() if latest_sync else None,
        }

    # ── DB-First Resource Access ─────────────────────────────────────────

    async def get_vms_from_db(self) -> list[dict[str, Any]]:
        """Get VMs from database inventory (fast, no Azure API call)."""
        records = await self.get_inventory_from_db(resource_type="virtual_machine")
        results = []
        for r in records:
            details = r.get("resource_details") or {}
            details["_last_sync"] = r.get("last_sync")
            results.append(details)
        return results

    async def get_storage_accounts_from_db(self) -> list[dict[str, Any]]:
        """Get storage accounts from database inventory."""
        records = await self.get_inventory_from_db(resource_type="storage_account")
        results = []
        for r in records:
            details = r.get("resource_details") or {}
            details["_last_sync"] = r.get("last_sync")
            # Normalize field names for frontend compatibility
            details.setdefault("sku", details.get("sku_name"))
            results.append(details)
        return results

    async def get_disks_from_db(self) -> list[dict[str, Any]]:
        """Get managed disks from database inventory."""
        records = await self.get_inventory_from_db(resource_type="managed_disk")
        results = []
        for r in records:
            details = r.get("resource_details") or {}
            details["_last_sync"] = r.get("last_sync")
            # Normalize field names for frontend compatibility
            details.setdefault("sku", details.get("sku_name"))
            details.setdefault("size_gb", details.get("disk_size_gb"))
            results.append(details)
        return results

    async def get_pg_servers_from_db(self) -> list[dict[str, Any]]:
        """Get PostgreSQL Flexible Servers from database inventory."""
        records = await self.get_inventory_from_db(resource_type="pg_flex_server")
        results = []
        for r in records:
            details = r.get("resource_details") or {}
            details["_last_sync"] = r.get("last_sync")
            results.append(details)
        return results

    async def get_last_sync_time(self, resource_type: str | None = None) -> str | None:
        """Get the last sync time for a resource type."""
        if not self.db:
            return None
        from sqlalchemy import func

        query = select(func.max(AzureResourceInventory.last_sync))
        if resource_type:
            query = query.where(AzureResourceInventory.resource_type == resource_type)
        result = await self.db.execute(query)
        last_sync = result.scalar()
        return last_sync.isoformat() if last_sync else None

    # ── Azure → DB Sync Methods ──────────────────────────────────────────

    async def sync_vms_to_db(self) -> dict[str, Any]:
        """
        Sync VMs from Azure to DB with accurate power_state.

        Strategy:
        1. Try batch list with expand=instanceView (fast)
        2. If power_state is missing, fetch each VM individually (slow but accurate)
        3. Save enriched data to DB
        """
        vms_data = await self.list_vms(save_to_db=False)

        # Check if batch got power_state
        has_power_state = any(vm.get("power_state") for vm in vms_data)

        if not has_power_state and vms_data:
            logger.info("batch_missing_power_state_fetching_individually", count=len(vms_data))
            enriched = []
            for vm_data in vms_data:
                rg = vm_data.get("resource_group", "")
                name = vm_data.get("name", "")
                subscription_id = vm_data.get("subscription_id")
                if rg and name:
                    try:
                        detail = await self.get_vm_details(rg, name, subscription_id=subscription_id)
                        if detail:
                            detail["resource_type"] = "virtual_machine"
                            enriched.append(detail)
                            continue
                    except Exception as e:
                        logger.warning("individual_vm_detail_failed", vm=name, error=str(e))
                enriched.append(vm_data)
            vms_data = enriched

        # Save to DB
        if self.db:
            await self._save_resources_to_db(vms_data, "virtual_machine")

        sync_time = datetime.utcnow().isoformat()
        logger.info("vms_synced_to_db", count=len(vms_data))
        return {
            "synced_count": len(vms_data),
            "resource_type": "virtual_machine",
            "last_sync": sync_time,
            "resources": vms_data,
        }

    async def sync_storage_accounts_to_db(self) -> dict[str, Any]:
        """Sync storage accounts from Azure to DB."""
        data = await self.list_storage_accounts(save_to_db=False)
        if self.db:
            await self._save_resources_to_db(data, "storage_account")
        sync_time = datetime.utcnow().isoformat()
        logger.info("storage_accounts_synced_to_db", count=len(data))
        return {
            "synced_count": len(data),
            "resource_type": "storage_account",
            "last_sync": sync_time,
            "resources": data,
        }

    async def sync_disks_to_db(self) -> dict[str, Any]:
        """Sync managed disks from Azure to DB."""
        data = await self.list_disks(save_to_db=False)
        if self.db:
            await self._save_resources_to_db(data, "managed_disk")
        sync_time = datetime.utcnow().isoformat()
        logger.info("disks_synced_to_db", count=len(data))
        return {
            "synced_count": len(data),
            "resource_type": "managed_disk",
            "last_sync": sync_time,
            "resources": data,
        }

    async def sync_pg_servers_to_db(self) -> dict[str, Any]:
        """Sync PostgreSQL Flexible Servers from Azure to DB."""
        data = await self.list_pg_flex_servers(save_to_db=False)
        if self.db:
            await self._save_resources_to_db(data, "pg_flex_server")
        sync_time = datetime.utcnow().isoformat()
        logger.info("pg_flex_servers_synced_to_db", count=len(data))
        return {
            "synced_count": len(data),
            "resource_type": "pg_flex_server",
            "last_sync": sync_time,
            "resources": data,
        }

    async def sync_all_resources_to_db(self) -> dict[str, Any]:
        """Sync all resources (VMs, Storage, Disks, PG Servers) from Azure to DB."""
        vm_result = await self.sync_vms_to_db()
        storage_result = await self.sync_storage_accounts_to_db()
        disk_result = await self.sync_disks_to_db()

        # PG Flex Servers — best-effort (sdk may not be installed)
        pg_result = {
            "synced_count": 0,
            "resource_type": "pg_flex_server",
            "last_sync": None,
            "resources": [],
        }
        try:
            pg_result = await self.sync_pg_servers_to_db()
        except Exception as e:
            logger.warning("sync_pg_servers_skipped", error=str(e))

        return {
            "last_sync": datetime.utcnow().isoformat(),
            "virtual_machines": vm_result,
            "storage_accounts": storage_result,
            "managed_disks": disk_result,
            "pg_flex_servers": pg_result,
            "total_synced": (
                vm_result["synced_count"]
                + storage_result["synced_count"]
                + disk_result["synced_count"]
                + pg_result["synced_count"]
            ),
        }
