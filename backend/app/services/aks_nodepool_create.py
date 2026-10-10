"""Create AKS node pools, mirroring the Azure portal's "Add a node pool" form.

``get_node_pool_create_options`` returns everything the form offers for one
cluster: the VM sizes available to the subscription in the cluster's region
(with vCPU/memory, zones, Spot and ephemeral OS disk support), the Kubernetes
versions a new pool can run, the subnets the cluster's pools use with their
free IPs, and the defaults the existing pools follow.

``create_node_pool`` validates a request against the same facts before
calling Azure, so mistakes come back as a clear message rather than an ARM
error after a minute's wait. A new pool takes its network and host-security
settings (subnet, pod subnet, encryption at host, FIPS) from an existing pool
on the chosen subnet: AKS requires every pool in the cluster's VNet, and
security baselines usually require the rest.
"""

from __future__ import annotations

import asyncio
import re
from collections import Counter
from typing import Any

import structlog
from azure.mgmt.compute import ComputeManagementClient
from azure.mgmt.containerservice import ContainerServiceClient
from azure.mgmt.containerservice.models import AgentPool, AgentPoolUpgradeSettings
from azure.mgmt.network import NetworkManagementClient

from app.services.aks_nodepool_operations import (
    MAX_NODES_PER_POOL,
    NodePoolChangeError,
    azure_error_message,
    cluster_parts,
)
from app.services.data_cache_service import CacheKeys, data_cache

logger = structlog.get_logger(__name__)

VM_SIZES_TTL_SECONDS = 12 * 3600
MAX_POOLS_PER_CLUSTER = 100
MAX_NODES_PER_CLUSTER = 5000
LINUX_OS_SKUS = ("Ubuntu", "AzureLinux")
WINDOWS_OS_SKUS = ("Windows2022", "Windows2019")
TAINT_EFFECTS = ("NoSchedule", "PreferNoSchedule", "NoExecute")
# AKS reserves these label domains for itself and rejects pools that set them.
RESERVED_LABEL_DOMAINS = ("kubernetes.azure.com", "kubernetes.io", "k8s.io")

_LABEL_NAME = r"[A-Za-z0-9]([-A-Za-z0-9_.]{0,61}[A-Za-z0-9])?"
_DNS_PREFIX = r"[a-z0-9]([-a-z0-9]*[a-z0-9])?(\.[a-z0-9]([-a-z0-9]*[a-z0-9])?)*"
LABEL_KEY_RE = re.compile(rf"^(?:(?P<prefix>{_DNS_PREFIX})/)?{_LABEL_NAME}$")
LABEL_VALUE_RE = re.compile(rf"^(?:{_LABEL_NAME})?$")
TAG_NAME_FORBIDDEN = set("<>%&\\?/")
LINUX_NAME_RE = re.compile(r"^[a-z][a-z0-9]{0,11}$")
WINDOWS_NAME_RE = re.compile(r"^[a-z][a-z0-9]{0,5}$")


# ── Pure helpers ──────────────────────────────────────────────────────


def _text(value: Any) -> str | None:
    """Azure SDK enums as plain strings."""
    if value is None:
        return None
    return str(getattr(value, "value", value))


def version_key(version: str) -> tuple[int, ...]:
    return tuple(int(p) for p in re.findall(r"\d+", version or ""))


def _cap(caps: dict[str, str], name: str) -> str | None:
    return caps.get(name)


def _num(value: str | None) -> float:
    try:
        return float(value) if value is not None else 0.0
    except ValueError:
        return 0.0


def vm_size_records(skus: list[Any], location: str) -> list[dict[str, Any]]:
    """VM sizes AKS can use that this subscription may deploy in ``location``."""
    records = []
    for sku in skus:
        if sku.resource_type != "virtualMachines":
            continue
        restrictions = sku.restrictions or []
        if any(r.reason_code == "NotAvailableForSubscription" and r.type == "Location" for r in restrictions):
            continue
        caps = {c.name: c.value for c in sku.capabilities or []}
        vcpus = int(_num(_cap(caps, "vCPUs")))
        if vcpus < 2:  # AKS doesn't support VM sizes with fewer than 2 vCPUs.
            continue
        zones: set[str] = set()
        for info in sku.location_info or []:
            if (info.location or "").lower() == location.lower():
                zones.update(info.zones or [])
        for r in restrictions:
            if r.type == "Zone" and r.restriction_info:
                zones.difference_update(r.restriction_info.zones or [])
        cache_gb = _num(_cap(caps, "CachedDiskBytes")) / 2**30
        temp_gb = _num(_cap(caps, "MaxResourceVolumeMB")) / 1024
        records.append(
            {
                "name": sku.name,
                "vcpus": vcpus,
                "memory_gb": _num(_cap(caps, "MemoryGB")),
                "zones": sorted(zones),
                "ephemeral_os_disk": _cap(caps, "EphemeralOSDiskSupported") == "True",
                # The OS disk can live on the cache or the temp disk, whichever is larger.
                "max_ephemeral_os_disk_gb": int(max(cache_gb, temp_gb)),
                "spot": _cap(caps, "LowPriorityCapable") == "True",
                "arch": _cap(caps, "CpuArchitectureType") or "x64",
                "family": sku.family,
            }
        )
    return sorted(records, key=lambda r: r["name"])


def ips_per_node(network_plugin: str | None, plugin_mode: str | None, pod_subnet: bool, max_pods: int) -> int:
    """Subnet IPs a node reserves: Azure CNI without overlay or a pod subnet gives every pod a VNet IP."""
    if (network_plugin or "").lower() == "azure" and (plugin_mode or "").lower() != "overlay" and not pod_subnet:
        return max_pods + 1
    return 1


def subnet_name(subnet_id: str | None) -> str | None:
    return subnet_id.rstrip("/").rsplit("/", 1)[-1] if subnet_id else None


def _label_key_error(key: str) -> str | None:
    match = LABEL_KEY_RE.match(key)
    if not match or len(key) > 316:
        return f"Label key '{key}' isn't a valid Kubernetes label key."
    prefix = match.group("prefix") or ""
    if prefix and any(prefix == d or prefix.endswith(f".{d}") for d in RESERVED_LABEL_DOMAINS):
        return f"Label key '{key}' uses a domain reserved by Kubernetes or AKS."
    return None


def parse_taint(taint: str) -> tuple[str, str, str] | None:
    """'key=value:Effect' → (key, value, effect); None when malformed."""
    head, sep, effect = taint.rpartition(":")
    if not sep:
        return None
    key, _, value = head.partition("=")
    return key, value, effect


def check_create_request(spec: dict[str, Any], options: dict[str, Any]) -> dict[str, Any]:
    """Validate a create request; returns the resolved values. Raises NodePoolChangeError."""
    name = spec["name"]
    os_type = spec.get("os_type") or "Linux"
    mode = spec.get("mode") or "User"
    if os_type == "Windows":
        if not options.get("windows_supported"):
            raise NodePoolChangeError(
                "This cluster wasn't created with Windows support, so it can't run Windows node pools."
            )
        if not WINDOWS_NAME_RE.match(name):
            raise NodePoolChangeError(
                "Windows node pool names are 1–6 lowercase letters and digits, starting with a letter."
            )
        if mode == "System":
            raise NodePoolChangeError("Windows node pools must be User pools.")
    elif not LINUX_NAME_RE.match(name):
        raise NodePoolChangeError(
            "Linux node pool names are 1–12 lowercase letters and digits, starting with a letter."
        )
    if name in options["existing_pools"]:
        raise NodePoolChangeError(f"This cluster already has a node pool named {name}.")
    if len(options["existing_pools"]) >= MAX_POOLS_PER_CLUSTER:
        raise NodePoolChangeError(f"An AKS cluster can have at most {MAX_POOLS_PER_CLUSTER} node pools.")
    if options.get("power_state") != "Running":
        raise NodePoolChangeError("The cluster is stopped. Start it before adding node pools.")

    os_sku = spec.get("os_sku") or (WINDOWS_OS_SKUS[0] if os_type == "Windows" else LINUX_OS_SKUS[0])
    if os_sku not in (WINDOWS_OS_SKUS if os_type == "Windows" else LINUX_OS_SKUS):
        raise NodePoolChangeError(f"{os_sku} isn't an OS SKU for {os_type} node pools.")

    version = spec.get("kubernetes_version") or options["control_plane_version"]
    if version not in options["kubernetes_versions"]:
        raise NodePoolChangeError(
            f"Kubernetes {version} isn't available for new pools here. Use one of: {', '.join(options['kubernetes_versions'])}."
        )

    spot = bool(spec.get("spot"))
    if spot and mode == "System":
        raise NodePoolChangeError("Spot node pools must be User pools.")

    zones = sorted(set(spec.get("availability_zones") or []))
    size = next((s for s in options["vm_sizes"] if s["name"].lower() == spec["vm_size"].lower()), None)
    if options["vm_sizes"]:
        if size is None:
            raise NodePoolChangeError(
                f"{spec['vm_size']} isn't available to this subscription in {options['location']}."
            )
        if zones and not set(zones) <= set(size["zones"]):
            available = ", ".join(size["zones"]) or "none"
            raise NodePoolChangeError(
                f"{size['name']} isn't offered in zone(s) {', '.join(zones)} here (available: {available})."
            )
        if mode == "System" and (size["vcpus"] < 2 or size["memory_gb"] < 4):
            raise NodePoolChangeError("System node pools need a VM size with at least 2 vCPUs and 4 GiB of memory.")
        if spot and not size["spot"]:
            raise NodePoolChangeError(f"{size['name']} can't run as Spot capacity.")
        if os_type == "Windows" and size["arch"] != "x64":
            raise NodePoolChangeError("Windows node pools need an x64 VM size.")
        if spec.get("os_disk_type") == "Ephemeral":
            if not size["ephemeral_os_disk"]:
                raise NodePoolChangeError(f"{size['name']} doesn't support ephemeral OS disks. Use Managed.")
            if spec["os_disk_size_gb"] > size["max_ephemeral_os_disk_gb"]:
                raise NodePoolChangeError(
                    f"An ephemeral OS disk on {size['name']} can be at most {size['max_ephemeral_os_disk_gb']} GiB."
                )

    floor = 1 if mode == "System" else 0
    auto = bool(spec.get("enable_auto_scaling"))
    if auto:
        min_count, max_count = spec.get("min_count"), spec.get("max_count")
        if min_count is None or max_count is None:
            raise NodePoolChangeError("Set both a minimum and a maximum node count.")
        if min_count > max_count:
            raise NodePoolChangeError(f"The minimum ({min_count}) can't be greater than the maximum ({max_count}).")
        if max_count < 1:
            raise NodePoolChangeError("The maximum must be at least 1 node.")
        count = min_count
    else:
        min_count = max_count = None
        count = spec.get("node_count")
        if count is None:
            raise NodePoolChangeError("Set the node count.")
    if (min_count if auto else count) < floor:
        raise NodePoolChangeError("System node pools need at least 1 node.")
    if (max_count or count) > MAX_NODES_PER_POOL:
        raise NodePoolChangeError(f"A node pool can have at most {MAX_NODES_PER_POOL} nodes.")
    if options["total_nodes"] + count > MAX_NODES_PER_CLUSTER:
        raise NodePoolChangeError(f"An AKS cluster can have at most {MAX_NODES_PER_CLUSTER} nodes across its pools.")

    max_pods = spec["max_pods"]
    if max_pods > options["max_pods_limit"]:
        raise NodePoolChangeError(
            f"This cluster's network plugin allows at most {options['max_pods_limit']} pods per node."
        )

    labels = dict(spec.get("node_labels") or {})
    for key, value in labels.items():
        error = _label_key_error(key)
        if error:
            raise NodePoolChangeError(error)
        if not LABEL_VALUE_RE.match(value):
            raise NodePoolChangeError(f"Label value '{value}' for {key} isn't a valid Kubernetes label value.")
    taints = list(spec.get("node_taints") or [])
    for taint in taints:
        parsed = parse_taint(taint)
        if not parsed or not LABEL_KEY_RE.match(parsed[0]) or not LABEL_VALUE_RE.match(parsed[1]):
            raise NodePoolChangeError(f"Taint '{taint}' must look like key=value:Effect.")
        if parsed[2] not in TAINT_EFFECTS:
            raise NodePoolChangeError(f"Taint effect must be one of {', '.join(TAINT_EFFECTS)}.")
    tags = dict(spec.get("tags") or {})
    for key, value in tags.items():
        if not key or len(key) > 512 or TAG_NAME_FORBIDDEN & set(key):
            raise NodePoolChangeError(f"Tag name '{key}' must be 1–512 characters without < > % & \\ ? /.")
        if len(value) > 256:
            raise NodePoolChangeError(f"The value of tag {key} is longer than 256 characters.")

    subnets = options["subnets"]
    subnet = next((s for s in subnets if s["id"].lower() == (spec.get("subnet_id") or "").lower()), None)
    if spec.get("subnet_id") and subnet is None:
        raise NodePoolChangeError("New pools can use only a subnet that this cluster's node pools already use.")
    subnet = subnet or (subnets[0] if subnets else None)
    if subnet and subnet["free_ips"] is not None:
        needed = count * ips_per_node(
            options["network_plugin"], options["network_plugin_mode"], bool(subnet.get("pod_subnet")), max_pods
        )
        if needed > subnet["free_ips"]:
            raise NodePoolChangeError(
                f"Subnet {subnet['name']} has {subnet['free_ips']} free IPs; {count} nodes with {max_pods} pods each need {needed}."
            )

    return {
        "name": name,
        "mode": mode,
        "os_type": os_type,
        "os_sku": os_sku,
        "version": version,
        "zones": zones,
        "spot": spot,
        "vm_size": size["name"] if size else spec["vm_size"],
        "os_disk_type": spec.get("os_disk_type"),
        "os_disk_size_gb": spec["os_disk_size_gb"],
        "auto": auto,
        "count": count,
        "min_count": min_count,
        "max_count": max_count,
        "max_pods": max_pods,
        "max_surge": spec.get("max_surge"),
        "labels": labels,
        "taints": taints,
        "tags": tags,
        "subnet": subnet,
    }


def build_agent_pool(resolved: dict[str, Any], template: Any | None) -> AgentPool:
    """The AgentPool to send to Azure; network and host security follow ``template``."""
    return AgentPool(
        count=resolved["count"],
        vm_size=resolved["vm_size"],
        os_disk_size_gb=resolved["os_disk_size_gb"],
        os_disk_type=resolved["os_disk_type"],
        max_pods=resolved["max_pods"],
        os_type=resolved["os_type"],
        os_sku=resolved["os_sku"],
        type_properties_type="VirtualMachineScaleSets",
        mode=resolved["mode"],
        orchestrator_version=resolved["version"],
        availability_zones=resolved["zones"] or None,
        enable_auto_scaling=resolved["auto"],
        min_count=resolved["min_count"],
        max_count=resolved["max_count"],
        node_labels=resolved["labels"] or None,
        node_taints=resolved["taints"] or None,
        tags=resolved["tags"] or None,
        scale_set_priority="Spot" if resolved["spot"] else None,
        scale_set_eviction_policy="Delete" if resolved["spot"] else None,
        spot_max_price=-1 if resolved["spot"] else None,  # pay up to the on-demand price
        upgrade_settings=AgentPoolUpgradeSettings(max_surge=resolved["max_surge"]) if resolved["max_surge"] else None,
        vnet_subnet_id=resolved["subnet"]["id"] if resolved["subnet"] else None,
        pod_subnet_id=getattr(template, "pod_subnet_id", None),
        enable_encryption_at_host=getattr(template, "enable_encryption_at_host", None) or None,
        enable_fips=getattr(template, "enable_fips", None) or None,
        enable_node_public_ip=False,
    )


def _list_usage(client: Any, resource_group: str, vnet: str) -> list[Any]:
    return list(client.virtual_networks.list_usage(resource_group, vnet))


def pick_template(pools: list[Any], subnet_id: str | None) -> Any | None:
    """The pool a new pool on ``subnet_id`` copies network and host-security settings from (system pools first)."""
    on_subnet = [p for p in pools if p.vnet_subnet_id == subnet_id] or pools
    return next((p for p in on_subnet if p.mode == "System"), on_subnet[0] if on_subnet else None)


def _most_common(values: list[Any], default: Any) -> Any:
    values = [v for v in values if v not in (None, "", [])]
    return Counter(values).most_common(1)[0][0] if values else default


# ── Service mixin ─────────────────────────────────────────────────────


class AKSNodePoolCreateMixin:
    """Options for, and creation of, new node pools."""

    async def _vm_sizes(self, subscription_id: str, location: str) -> list[dict[str, Any]]:
        async def _fetch() -> list[dict[str, Any]]:
            client = ComputeManagementClient(self.credential, subscription_id)  # type: ignore[attr-defined]
            skus = await asyncio.to_thread(lambda: list(client.resource_skus.list(filter=f"location eq '{location}'")))
            return vm_size_records(skus, location)

        sizes, _tier = await data_cache.get_or_fetch(
            key=CacheKeys.vm_sizes(subscription_id, location), ttl=VM_SIZES_TTL_SECONDS, fetch_fn=_fetch
        )
        return sizes  # type: ignore[no-any-return]

    async def _subnet_usage(self, subnet_ids: list[str]) -> dict[str, tuple[int, int]]:
        """subnet id (lowercase) → (used IPs, total IPs) for the VNets of ``subnet_ids``."""
        usage: dict[str, tuple[int, int]] = {}
        vnets = {sid.lower().split("/subnets/")[0]: sid for sid in subnet_ids if "/subnets/" in sid.lower()}
        for vnet_id, sample in vnets.items():
            parts = sample.split("/")
            lowered = [p.lower() for p in parts]
            try:
                sub = parts[lowered.index("subscriptions") + 1]
                rg = parts[lowered.index("resourcegroups") + 1]
                vnet = parts[lowered.index("virtualnetworks") + 1]
                client = NetworkManagementClient(self.credential, sub)  # type: ignore[attr-defined]
                rows = await asyncio.to_thread(_list_usage, client, rg, vnet)
                for u in rows:
                    usage[(u.id or "").lower()] = (int(u.current_value or 0), int(u.limit or 0))
            except Exception as e:
                logger.warning("subnet_usage_unavailable", vnet=vnet_id, error=str(e)[:200])
        return usage

    async def get_node_pool_create_options(self, cluster_id: str) -> dict[str, Any]:
        options, _pools = await self._node_pool_create_context(cluster_id)
        return options

    async def _node_pool_create_context(self, cluster_id: str) -> tuple[dict[str, Any], list[Any]]:
        subscription_id, resource_group, cluster_name = cluster_parts(cluster_id)
        aks_client = ContainerServiceClient(self.credential, subscription_id)  # type: ignore[attr-defined]
        cluster, pools = await asyncio.gather(
            asyncio.to_thread(aks_client.managed_clusters.get, resource_group, cluster_name),
            asyncio.to_thread(lambda: list(aks_client.agent_pools.list(resource_group, cluster_name))),
        )
        location = cluster.location
        try:
            vm_sizes, vm_sizes_error = await self._vm_sizes(subscription_id, location), None
        except Exception as e:
            logger.warning("vm_sizes_unavailable", location=location, error=str(e)[:200])
            vm_sizes, vm_sizes_error = (
                [],
                "The VM sizes available in this region couldn't be read; enter a size by name.",
            )

        control_plane = cluster.current_kubernetes_version or cluster.kubernetes_version
        versions = {control_plane, *(p.current_orchestrator_version or p.orchestrator_version for p in pools)}
        kubernetes_versions = sorted(
            (v for v in versions if v and version_key(v) <= version_key(control_plane)), key=version_key, reverse=True
        )

        network = cluster.network_profile
        plugin = _text(getattr(network, "network_plugin", None))
        plugin_mode = _text(getattr(network, "network_plugin_mode", None))
        # The subnet most pools use comes first; it's the default for a new pool.
        subnet_ids = [sid for sid, _n in Counter(p.vnet_subnet_id for p in pools if p.vnet_subnet_id).most_common()]
        usage = await self._subnet_usage(subnet_ids) if subnet_ids else {}
        subnets = []
        for sid in subnet_ids:
            used, total = usage.get(sid.lower(), (None, None))
            on_subnet = [p for p in pools if p.vnet_subnet_id == sid]
            subnets.append(
                {
                    "id": sid,
                    "name": subnet_name(sid),
                    "free_ips": total - used if total is not None and used is not None else None,
                    "total_ips": total,
                    "pools": [p.name for p in on_subnet],
                    "pod_subnet": any(p.pod_subnet_id for p in on_subnet),
                }
            )
        template = pick_template(pools, subnets[0]["id"] if subnets else None)
        user_pools = [p for p in pools if p.mode != "System"] or pools

        options = {
            "cluster_name": cluster_name,
            "location": location,
            "power_state": _text(cluster.power_state.code) if cluster.power_state else "Running",
            "control_plane_version": control_plane,
            "kubernetes_versions": kubernetes_versions,
            "network_plugin": plugin,
            "network_plugin_mode": plugin_mode,
            "max_pods_limit": 110 if (plugin or "").lower() == "kubenet" else 250,
            "windows_supported": cluster.windows_profile is not None,
            "existing_pools": sorted(p.name for p in pools),
            "total_nodes": sum(p.count or 0 for p in pools),
            "subnets": subnets,
            "vm_sizes": vm_sizes,
            "vm_sizes_error": vm_sizes_error,
            "zones": sorted({z for s in vm_sizes for z in s["zones"]}) or ["1", "2", "3"],
            "defaults": {
                "vm_size": _most_common([p.vm_size for p in user_pools], None),
                "max_pods": _most_common([p.max_pods for p in user_pools], 30),
                "max_surge": _most_common([p.upgrade_settings.max_surge for p in pools if p.upgrade_settings], None),
                "availability_zones": list(template.availability_zones or []) if template else [],
                "os_disk_size_gb": 128,
            },
            "inherited": {
                "source_pool": template.name if template else None,
                "encryption_at_host": bool(getattr(template, "enable_encryption_at_host", False)),
                "fips": bool(getattr(template, "enable_fips", False)),
            },
        }
        return options, pools

    async def create_node_pool(self, cluster_id: str, spec: dict[str, Any]) -> dict[str, Any]:
        """Validate and start creating a node pool; Azure provisions it in the background."""
        name = spec.get("name", "")
        result: dict[str, Any] = {"success": False, "cluster_id": cluster_id, "nodepool_name": name}
        try:
            subscription_id, resource_group, cluster_name = cluster_parts(cluster_id)
            options, pools = await self._node_pool_create_context(cluster_id)
            resolved = check_create_request(spec, options)
            template = pick_template(pools, resolved["subnet"]["id"] if resolved["subnet"] else None)
            pool = build_agent_pool(resolved, template)
            aks_client = ContainerServiceClient(self.credential, subscription_id)  # type: ignore[attr-defined]
            await asyncio.to_thread(
                aks_client.agent_pools.begin_create_or_update, resource_group, cluster_name, name, pool
            )
        except NodePoolChangeError as e:
            return {**result, "error": str(e)}
        except Exception as e:
            logger.error("node_pool_create_failed", nodepool=name, error=str(e))
            return {**result, "error": azure_error_message(e)}

        logger.info("node_pool_create_initiated", cluster=cluster_name, nodepool=name, vm_size=resolved["vm_size"])
        await data_cache.invalidate_for_nodepools(cluster_id)
        return {
            **result,
            "success": True,
            "vm_size": resolved["vm_size"],
            "mode": resolved["mode"],
            "node_count": resolved["count"],
            "min_count": resolved["min_count"],
            "max_count": resolved["max_count"],
            "kubernetes_version": resolved["version"],
            "subnet": resolved["subnet"]["name"] if resolved["subnet"] else None,
            "inherited_from": template.name if template else None,
        }
