"""AKS node pools: Azure agent pool configuration joined with live Kubernetes node state.

Azure (ARM) is the source for each pool's configuration and node count; the
Kubernetes API adds per-node readiness and the pods running on each node. The
Kubernetes part is best-effort and time-bounded: when the API server can't be
reached (e.g. a private cluster from outside its network) the pools are still
saved with their Azure data and flagged ``node_details_available: false`` —
never reported as zero pods.
"""

from __future__ import annotations

import asyncio
import json
import re
from collections import Counter
from datetime import UTC, datetime, timedelta
from typing import Any

import structlog
from azure.mgmt.compute import ComputeManagementClient
from azure.mgmt.containerservice import ContainerServiceClient
from azure.mgmt.containerservice.models import PowerState
from azure.mgmt.monitor import MonitorManagementClient
from kubernetes import client as k8s_client
from kubernetes.client.rest import ApiException
from sqlalchemy import delete, func, select

from app.models.database import AzureResourceInventory
from app.services.data_cache_service import TTL, CacheKeys, data_cache
from app.services.k8s_usage import json_pod_requests, to_bytes, to_millicores

logger = structlog.get_logger(__name__)

INVENTORY_TYPE = "aks_nodepool"
# Completed Job pods and evicted pods hold no node resources; `kubectl describe
# node` counts the same non-terminated set.
ACTIVE_POD_SELECTOR = "status.phase!=Succeeded,status.phase!=Failed"
# Upper bound for the whole Kubernetes read. A sync job that never finishes
# blocks later syncs of the same pools (they reuse the running job).
K8S_SNAPSHOT_TIMEOUT_SECONDS = 90
MAX_NODES_PER_POOL = 1000
PRESSURE_CONDITIONS = ("MemoryPressure", "DiskPressure", "PIDPressure")
# Azure Monitor platform metrics of the pool's scale set (averaged across its VMs).
CPU_METRIC = "Percentage CPU"
MEMORY_METRIC = "Available Memory Percentage"
# AKS platform metrics on the managed cluster: averaged across its nodes.
CLUSTER_CPU_METRIC = "node_cpu_usage_percentage"
CLUSTER_MEMORY_METRIC = "node_memory_working_set_percentage"
UTILISATION_LOOKBACK = timedelta(minutes=20)
UTILISATION_TIMEOUT_SECONDS = 20
# range → (lookback, grain) for the utilisation history chart.
METRIC_RANGES: dict[str, tuple[timedelta, str]] = {
    "1h": (timedelta(hours=1), "PT1M"),
    "6h": (timedelta(hours=6), "PT5M"),
    "24h": (timedelta(hours=24), "PT15M"),
    "7d": (timedelta(days=7), "PT1H"),
    "30d": (timedelta(days=30), "PT6H"),
}


TAINT_EFFECTS = ("NoSchedule", "PreferNoSchedule", "NoExecute")
# Label/taint keys AKS manages itself (e.g. the Spot taint); they can't be set or changed.
AKS_MANAGED_PREFIX = "kubernetes.azure.com/"
# AKS and Kubernetes reserve these label domains and reject pools that set them.
RESERVED_LABEL_DOMAINS = ("kubernetes.azure.com", "kubernetes.io", "k8s.io")
_LABEL_NAME = r"[A-Za-z0-9]([-A-Za-z0-9_.]{0,61}[A-Za-z0-9])?"
_DNS_PREFIX = r"[a-z0-9]([-a-z0-9]*[a-z0-9])?(\.[a-z0-9]([-a-z0-9]*[a-z0-9])?)*"
LABEL_KEY_RE = re.compile(rf"^(?:(?P<prefix>{_DNS_PREFIX})/)?{_LABEL_NAME}$")
LABEL_VALUE_RE = re.compile(rf"^(?:{_LABEL_NAME})?$")


class NodePoolChangeError(ValueError):
    """A node pool change that Azure would reject or that changes nothing."""


# ── Pure helpers ──────────────────────────────────────────────────────


def cluster_parts(cluster_id: str) -> tuple[str, str, str]:
    """(subscription, resource group, cluster name) from an AKS resource ID."""
    parts = cluster_id.strip("/").split("/")
    lowered = [p.lower() for p in parts]
    try:
        return (
            parts[lowered.index("subscriptions") + 1],
            parts[lowered.index("resourcegroups") + 1],
            parts[lowered.index("managedclusters") + 1],
        )
    except (ValueError, IndexError) as e:
        raise ValueError(f"Not an AKS cluster resource ID: {cluster_id}") from e


def _iso(ts: Any) -> str | None:
    if ts is None:
        return None
    return ts.isoformat() if hasattr(ts, "isoformat") else str(ts)


def _int(value: Any) -> int:
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return 0


def _pct(part: float | None, whole: float) -> float | None:
    return round(part * 100 / whole, 1) if part is not None and whole else None


def serialize_pool_node(
    node: Any, pod_count: int, requests: tuple[int, int] = (0, 0), usage: dict[str, Any] | None = None
) -> dict[str, Any]:
    """One Kubernetes node with its readiness, running pods, pod requests, and live usage (metrics-server)."""
    meta, spec, status = node.metadata, node.spec, node.status
    labels = dict(meta.labels or {})
    conditions = {c.type: c.status for c in (status.conditions or [])} if status else {}
    allocatable = (status.allocatable or {}) if status else {}
    info = status.node_info if status else None
    alloc_cpu, alloc_memory = to_millicores(allocatable.get("cpu")), to_bytes(allocatable.get("memory"))
    cpu_used = to_millicores(usage.get("cpu")) if usage else None
    memory_used = to_bytes(usage.get("memory")) if usage else None
    return {
        "name": meta.name,
        "pool": labels.get("kubernetes.azure.com/agentpool") or labels.get("agentpool"),
        "ready": conditions.get("Ready") == "True",
        "unschedulable": bool(spec and spec.unschedulable),
        "pressure": [c for c in PRESSURE_CONDITIONS if conditions.get(c) == "True"],
        "pod_count": pod_count,
        "allocatable_pods": _int(allocatable.get("pods")),
        "allocatable_cpu": allocatable.get("cpu"),
        "allocatable_memory": allocatable.get("memory"),
        "allocatable_cpu_m": alloc_cpu,
        "allocatable_memory_bytes": alloc_memory,
        "cpu_request_m": requests[0],
        "memory_request_bytes": requests[1],
        "cpu_request_pct": _pct(requests[0], alloc_cpu),
        "memory_request_pct": _pct(requests[1], alloc_memory),
        "cpu_usage_m": cpu_used,
        "memory_usage_bytes": memory_used,
        "cpu_usage_pct": _pct(cpu_used, alloc_cpu),
        "memory_usage_pct": _pct(memory_used, alloc_memory),
        "zone": labels.get("topology.kubernetes.io/zone"),
        "kubelet_version": info.kubelet_version if info else None,
        "node_image_version": labels.get("kubernetes.azure.com/node-image-version"),
        "created_at": _iso(meta.creation_timestamp),
        "labels": labels,
    }


def describe_k8s_error(exc: BaseException) -> str:
    """Why node details are missing, in terms an operator can act on."""
    text = str(exc)
    if isinstance(exc, TimeoutError) or "timed out" in text.lower():
        return "The Kubernetes API did not respond in time."
    if isinstance(exc, ApiException):
        if exc.status in (401, 403):
            return f"The portal's cluster credentials were rejected (HTTP {exc.status})."
        return f"The Kubernetes API returned an error (HTTP {exc.status})."
    if any(s in text for s in ("Failed to resolve", "NameResolutionError", "Max retries exceeded", "Connection")):
        return "The cluster's Kubernetes API can't be reached from the portal (private cluster or network path)."
    return "Node details could not be read from the Kubernetes API."


def build_node_pool(
    pool: Any,
    vmss_count: int | None,
    nodes: list[dict[str, Any]] | None,
    k8s_error: str | None,
    utilisation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Grid/detail record for one agent pool.

    ``nodes`` is None when Kubernetes was unavailable; ``utilisation`` is the
    scale set's current CPU / memory from Azure Monitor.
    """
    available = nodes is not None
    pool_nodes = sorted((n for n in nodes or [] if n.get("pool") == pool.name), key=lambda n: n["name"])
    upgrade = pool.upgrade_settings
    alloc_cpu = sum(n.get("allocatable_cpu_m") or 0 for n in pool_nodes)
    alloc_memory = sum(n.get("allocatable_memory_bytes") or 0 for n in pool_nodes)
    return {
        "name": pool.name,
        "vm_size": pool.vm_size,
        # Scale-set capacity is the live node count; the agent pool count goes
        # stale once the cluster autoscaler resizes a pool.
        "count": vmss_count if vmss_count is not None else (pool.count or 0),
        "min_count": pool.min_count,
        "max_count": pool.max_count,
        "enable_auto_scaling": bool(pool.enable_auto_scaling),
        "mode": pool.mode or "User",
        "os_type": pool.os_type or "Linux",
        "os_sku": pool.os_sku,
        "os_disk_size_gb": pool.os_disk_size_gb,
        "os_disk_type": pool.os_disk_type,
        # The version the nodes run; orchestrator_version is the requested one.
        "kubernetes_version": pool.current_orchestrator_version or pool.orchestrator_version,
        "provisioning_state": pool.provisioning_state,
        "power_state": pool.power_state.code if pool.power_state else "Running",
        "max_pods": pool.max_pods,
        "node_labels": dict(pool.node_labels or {}),
        "node_taints": list(pool.node_taints or []),
        "availability_zones": list(pool.availability_zones or []),
        "node_image_version": pool.node_image_version,
        "scale_set_priority": pool.scale_set_priority or "Regular",
        "scale_down_mode": pool.scale_down_mode or "Delete",
        "max_surge": upgrade.max_surge if upgrade else None,
        "node_details_available": available,
        "node_details_error": k8s_error,
        "total_pods": sum(n["pod_count"] for n in pool_nodes) if available else None,
        "pod_capacity": sum(n["allocatable_pods"] for n in pool_nodes) if available else None,
        "ready_nodes": sum(1 for n in pool_nodes if n["ready"]) if available else None,
        "cordoned_nodes": sum(1 for n in pool_nodes if n["unschedulable"]) if available else None,
        # Share of the pool's allocatable CPU / memory that pods have reserved.
        "cpu_request_pct": _pct(sum(n.get("cpu_request_m") or 0 for n in pool_nodes), alloc_cpu) if available else None,
        "memory_request_pct": _pct(sum(n.get("memory_request_bytes") or 0 for n in pool_nodes), alloc_memory)
        if available
        else None,
        "utilisation": utilisation,
        "nodes": pool_nodes,
    }


def scale_set_pool_name(vmss: Any) -> str | None:
    """The AKS pool a node resource group scale set belongs to."""
    tags = vmss.tags or {}
    name = tags.get("aks-managed-poolName") or tags.get("poolName")
    if not name and vmss.name:
        # AKS names scale sets "aks-<poolName>-<hash>-vmss"; pool names have no hyphens.
        segments = vmss.name.split("-")
        name = segments[1] if len(segments) >= 2 else None
    return name


def _metric_points(response: Any) -> dict[str, list[Any]]:
    return {m.name.value: (m.timeseries[0].data if m.timeseries else []) for m in response.value}


def _timespan(lookback: timedelta) -> str:
    end = datetime.now(UTC)
    return f"{end - lookback:%Y-%m-%dT%H:%M:%SZ}/{end:%Y-%m-%dT%H:%M:%SZ}"


def utilisation_series(points: dict[str, list[Any]]) -> list[dict[str, Any]]:
    """Merged CPU / memory-used points; memory used = 100 - available (peak = 100 - lowest available)."""
    rows: dict[str, dict[str, Any]] = {}
    for p in points.get(CPU_METRIC, []):
        row = rows.setdefault(p.time_stamp.isoformat(), {"t": p.time_stamp.isoformat()})
        row["cpu_avg"] = round(p.average, 1) if p.average is not None else None
        row["cpu_max"] = round(p.maximum, 1) if getattr(p, "maximum", None) is not None else None
    for p in points.get(MEMORY_METRIC, []):
        row = rows.setdefault(p.time_stamp.isoformat(), {"t": p.time_stamp.isoformat()})
        row["memory_avg"] = round(100 - p.average, 1) if p.average is not None else None
        row["memory_max"] = round(100 - p.minimum, 1) if getattr(p, "minimum", None) is not None else None
    return [rows[k] for k in sorted(rows)]


def latest_average(points: list[Any]) -> tuple[float | None, str | None]:
    """The newest non-empty average and its timestamp."""
    for p in reversed(points):
        if p.average is not None:
            return round(p.average, 1), p.time_stamp.isoformat()
    return None, None


def summarize_series(series: list[dict[str, Any]], key: str) -> dict[str, Any] | None:
    averages = [r[f"{key}_avg"] for r in series if r.get(f"{key}_avg") is not None]
    if not averages:
        return None
    peaks = [r[f"{key}_max"] for r in series if r.get(f"{key}_max") is not None] or averages
    return {"current": averages[-1], "average": round(sum(averages) / len(averages), 1), "peak": max(peaks)}


def _power(resource: Any) -> str:
    return resource.power_state.code if resource.power_state else "Running"


def _check_not_stopped(pool: Any) -> None:
    # Resizing a stopped pool is unsupported and confuses the cluster autoscaler.
    if _power(pool) == "Stopped":
        raise NodePoolChangeError(f"{pool.name} is stopped. Start it before changing its size.")


def check_scale_request(pool: Any, node_count: int) -> None:
    _check_not_stopped(pool)
    if pool.enable_auto_scaling:
        raise NodePoolChangeError(
            f"The cluster autoscaler manages {pool.name} ({pool.min_count}–{pool.max_count} nodes). "
            "Change its autoscaling range, or turn autoscaling off to set a fixed node count."
        )
    if (pool.mode or "User") == "System" and node_count < 1:
        raise NodePoolChangeError(f"{pool.name} is a System node pool and needs at least 1 node.")
    if node_count == (pool.count or 0):
        raise NodePoolChangeError(f"{pool.name} already has {node_count} nodes.")


def check_autoscaling_request(pool: Any, enable: bool, min_count: int | None, max_count: int | None) -> None:
    _check_not_stopped(pool)
    if not enable:
        if not pool.enable_auto_scaling:
            raise NodePoolChangeError(f"Autoscaling is already off for {pool.name}.")
        return
    if min_count is None or max_count is None:
        raise NodePoolChangeError("Set both a minimum and a maximum node count.")
    if min_count > max_count:
        raise NodePoolChangeError(f"The minimum ({min_count}) can't be greater than the maximum ({max_count}).")
    if max_count > MAX_NODES_PER_POOL:
        raise NodePoolChangeError(f"A node pool can have at most {MAX_NODES_PER_POOL} nodes.")
    if (pool.mode or "User") == "System" and min_count < 1:
        raise NodePoolChangeError(f"{pool.name} is a System node pool; its minimum must be at least 1 node.")
    if pool.enable_auto_scaling and (pool.min_count, pool.max_count) == (min_count, max_count):
        raise NodePoolChangeError(f"{pool.name} already autoscales between {min_count} and {max_count} nodes.")


def check_power_request(cluster: Any, pool: Any, start: bool) -> None:
    """Azure's preconditions for starting or stopping a node pool."""
    if _power(cluster) != "Running":
        raise NodePoolChangeError(
            "The cluster is stopped. Start the cluster before starting or stopping its node pools."
        )
    nap = getattr(cluster, "node_provisioning_profile", None)
    if nap is not None and str(getattr(nap, "mode", "") or "").lower() == "auto":
        raise NodePoolChangeError(
            "Node pools can't be started or stopped on a cluster that uses node auto-provisioning."
        )
    power = _power(pool)
    if start:
        if power != "Stopped":
            raise NodePoolChangeError(f"{pool.name} is already running.")
        return
    if (pool.mode or "User") == "System":
        raise NodePoolChangeError(f"{pool.name} is a System node pool. System pools can't be stopped.")
    if power == "Stopped":
        raise NodePoolChangeError(f"{pool.name} is already stopped.")
    if pool.provisioning_state != "Succeeded":
        raise NodePoolChangeError(
            f"{pool.name} is {pool.provisioning_state}. Wait for it to finish before stopping the pool."
        )


def label_key_error(key: str) -> str | None:
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


def check_labels_and_taints(labels: dict[str, str], taints: list[str]) -> None:
    """Kubernetes syntax and AKS's reserved domains for node pool labels and taints."""
    for key, value in labels.items():
        error = label_key_error(key)
        if error:
            raise NodePoolChangeError(error)
        if not LABEL_VALUE_RE.match(value):
            raise NodePoolChangeError(f"Label value '{value}' for {key} isn't a valid Kubernetes label value.")
    seen: set[tuple[str, str]] = set()
    for taint in taints:
        parsed = parse_taint(taint)
        if not parsed or not LABEL_KEY_RE.match(parsed[0]) or not LABEL_VALUE_RE.match(parsed[1]):
            raise NodePoolChangeError(f"Taint '{taint}' must look like key=value:Effect.")
        if parsed[2] not in TAINT_EFFECTS:
            raise NodePoolChangeError(f"Taint effect must be one of {', '.join(TAINT_EFFECTS)}.")
        if (parsed[0], parsed[2]) in seen:
            raise NodePoolChangeError(f"Taint {parsed[0]} with effect {parsed[2]} is set twice.")
        seen.add((parsed[0], parsed[2]))


def _aks_managed(key: str) -> bool:
    return key.startswith(AKS_MANAGED_PREFIX)


def _taint_key(taint: str) -> str:
    parsed = parse_taint(taint)
    return parsed[0] if parsed else taint


def merge_labels_and_taints(
    pool: Any, labels: dict[str, str], taints: list[str]
) -> tuple[dict[str, str], list[str], dict[str, list[str]]]:
    """The pool's new labels and taints: the user's, plus the AKS-managed ones it already has.

    Updating a pool replaces its labels and taints, so AKS-managed entries (such
    as the Spot taint) are carried over unchanged. Returns (labels, taints, diff).
    """
    current_labels = dict(pool.node_labels or {})
    current_taints = list(pool.node_taints or [])
    for key, value in labels.items():
        if _aks_managed(key) and current_labels.get(key) != value:
            raise NodePoolChangeError(f"Label {key} is managed by AKS and can't be changed.")
    for taint in taints:
        if _aks_managed(_taint_key(taint)) and taint not in current_taints:
            raise NodePoolChangeError(f"Taint {taint} is managed by AKS and can't be changed.")
    user_labels = {k: v for k, v in labels.items() if not _aks_managed(k)}
    user_taints = [t for t in dict.fromkeys(taints) if not _aks_managed(_taint_key(t))]
    check_labels_and_taints(user_labels, user_taints)

    new_labels = {**{k: v for k, v in current_labels.items() if _aks_managed(k)}, **user_labels}
    new_taints = [t for t in current_taints if _aks_managed(_taint_key(t))] + user_taints
    diff = {
        "labels_added": sorted(k for k in new_labels if k not in current_labels),
        "labels_removed": sorted(k for k in current_labels if k not in new_labels),
        "labels_changed": sorted(k for k in new_labels if k in current_labels and current_labels[k] != new_labels[k]),
        "taints_added": [t for t in new_taints if t not in current_taints],
        "taints_removed": [t for t in current_taints if t not in new_taints],
    }
    if not any(diff.values()):
        raise NodePoolChangeError(f"{pool.name} already has these labels and taints.")
    return new_labels, new_taints, diff


def azure_error_message(exc: Exception) -> str:
    return (getattr(exc, "message", None) or str(exc))[:500]


# ── Service mixin ─────────────────────────────────────────────────────


class AKSNodePoolOperationsMixin:
    """Node pool inventory, scaling, and autoscaling."""

    async def get_node_pools(self, cluster_id: str, bypass_cache: bool = False) -> list[dict[str, Any]]:
        """Live node pools (Azure + Kubernetes), cached for a few minutes unless ``bypass_cache``."""
        if bypass_cache:
            return await self._fetch_node_pools_live(cluster_id)
        cached, _tier = await data_cache.get_or_fetch(
            key=CacheKeys.node_pools(cluster_id),
            ttl=TTL.NODE_POOLS,
            fetch_fn=lambda: self._fetch_node_pools_live(cluster_id),
        )
        return cached  # type: ignore[no-any-return]

    async def _fetch_node_pools_live(self, cluster_id: str) -> list[dict[str, Any]]:
        subscription_id, resource_group, cluster_name = cluster_parts(cluster_id)
        aks_client = ContainerServiceClient(self.credential, subscription_id)  # type: ignore[attr-defined]
        try:
            pools, scale_sets, (nodes, k8s_error) = await asyncio.gather(
                asyncio.to_thread(lambda: list(aks_client.agent_pools.list(resource_group, cluster_name))),
                self._pool_scale_sets(aks_client, subscription_id, resource_group, cluster_name),
                self._node_pool_k8s_snapshot(cluster_id),
            )
        except Exception as e:
            logger.error("node_pools_list_failed", cluster_id=cluster_id, error=str(e))
            raise
        utilisation = await self._pool_utilisation(subscription_id, scale_sets)
        records = [
            build_node_pool(
                p,
                scale_sets[p.name]["capacity"] if p.name in scale_sets else None,
                nodes,
                k8s_error,
                utilisation.get(p.name),
            )
            for p in pools
        ]
        logger.info(
            "node_pools_listed",
            cluster=cluster_name,
            count=len(records),
            node_details=k8s_error is None,
        )
        return records

    async def _pool_scale_sets(
        self, aks_client: Any, subscription_id: str, resource_group: str, cluster_name: str
    ) -> dict[str, dict[str, Any]]:
        """pool name → {"id", "capacity"} for the cluster's scale sets; empty when they can't be read."""
        try:
            cluster = await asyncio.to_thread(aks_client.managed_clusters.get, resource_group, cluster_name)
            if not cluster.node_resource_group:
                return {}
            compute = ComputeManagementClient(self.credential, subscription_id)  # type: ignore[attr-defined]
            scale_sets = await asyncio.to_thread(
                lambda: list(compute.virtual_machine_scale_sets.list(cluster.node_resource_group))
            )
        except Exception as e:
            logger.warning("node_pool_scale_sets_unavailable", cluster=cluster_name, error=str(e)[:200])
            return {}
        result: dict[str, dict[str, Any]] = {}
        for vmss in scale_sets:
            name = scale_set_pool_name(vmss)
            if name:
                entry = result.setdefault(name, {"id": vmss.id, "capacity": 0})
                entry["capacity"] += (vmss.sku.capacity if vmss.sku else 0) or 0
        return result

    def _read_vmss_metrics(
        self, subscription_id: str, vmss_id: str, lookback: timedelta, grain: str, aggregation: str
    ) -> tuple[dict[str, list[Any]], str | None]:
        """Blocking Azure Monitor read; falls back to CPU alone when the memory metric isn't published."""
        client = MonitorManagementClient(self.credential, subscription_id)  # type: ignore[attr-defined]
        kwargs = {"timespan": _timespan(lookback), "interval": grain, "aggregation": aggregation}
        try:
            return _metric_points(
                client.metrics.list(vmss_id, metricnames=f"{CPU_METRIC},{MEMORY_METRIC}", **kwargs)
            ), None
        except Exception as e:
            logger.info("vmss_memory_metric_unavailable", vmss=vmss_id.rsplit("/", 1)[-1], error=str(e)[:200])
            points = _metric_points(client.metrics.list(vmss_id, metricnames=CPU_METRIC, **kwargs))
            return points, "Azure Monitor doesn't publish memory for this scale set."

    async def _pool_utilisation(
        self, subscription_id: str, scale_sets: dict[str, dict[str, Any]]
    ) -> dict[str, dict[str, Any]]:
        """pool → current CPU / memory-used % (latest 5-minute average from Azure Monitor)."""

        async def _one(pool: str, vmss_id: str) -> tuple[str, dict[str, Any] | None]:
            try:
                points, _memory_error = await asyncio.to_thread(
                    self._read_vmss_metrics, subscription_id, vmss_id, UTILISATION_LOOKBACK, "PT5M", "Average"
                )
            except Exception as e:
                logger.warning("node_pool_utilisation_failed", pool=pool, error=str(e)[:200])
                return pool, None
            series = utilisation_series(points)
            cpu = next((r["cpu_avg"] for r in reversed(series) if r.get("cpu_avg") is not None), None)
            memory = next((r["memory_avg"] for r in reversed(series) if r.get("memory_avg") is not None), None)
            at = next((r["t"] for r in reversed(series) if r.get("cpu_avg") is not None), None)
            if cpu is None and memory is None:
                return pool, None
            return pool, {"cpu_pct": cpu, "memory_pct": memory, "at": at, "source": "azure-monitor"}

        try:
            results = await asyncio.wait_for(
                asyncio.gather(*(_one(pool, s["id"]) for pool, s in scale_sets.items() if s.get("capacity"))),
                timeout=UTILISATION_TIMEOUT_SECONDS,
            )
        except TimeoutError:
            logger.warning("node_pool_utilisation_timeout", pools=len(scale_sets))
            return {}
        return {pool: value for pool, value in results if value}

    async def attach_cluster_utilisation(self, clusters: list[dict[str, Any]]) -> None:
        """Set each running cluster's ``utilisation`` from its AKS platform metrics (Azure Monitor)."""

        async def _one(cluster: dict[str, Any]) -> None:
            cluster["utilisation"] = None
            if cluster.get("power_state") != "Running":
                return
            try:
                client = MonitorManagementClient(self.credential, cluster["subscription_id"])  # type: ignore[attr-defined]
                response = await asyncio.to_thread(
                    client.metrics.list,
                    cluster["id"],
                    timespan=_timespan(UTILISATION_LOOKBACK),
                    interval="PT5M",
                    metricnames=f"{CLUSTER_CPU_METRIC},{CLUSTER_MEMORY_METRIC}",
                    aggregation="Average",
                )
            except Exception as e:
                logger.warning("cluster_utilisation_failed", cluster=cluster.get("name"), error=str(e)[:200])
                return
            points = _metric_points(response)
            cpu, at = latest_average(points.get(CLUSTER_CPU_METRIC, []))
            memory, _ = latest_average(points.get(CLUSTER_MEMORY_METRIC, []))
            if cpu is not None or memory is not None:
                cluster["utilisation"] = {"cpu_pct": cpu, "memory_pct": memory, "at": at, "source": "azure-monitor"}

        try:
            await asyncio.wait_for(asyncio.gather(*(_one(c) for c in clusters)), timeout=UTILISATION_TIMEOUT_SECONDS)
        except TimeoutError:
            logger.warning("cluster_utilisation_timeout", clusters=len(clusters))

    async def get_node_pool_metrics(
        self, cluster_id: str, nodepool_name: str, range_key: str = "24h"
    ) -> dict[str, Any]:
        """CPU and memory-used history of a pool's scale set from Azure Monitor."""
        lookback, grain = METRIC_RANGES[range_key]
        subscription_id, resource_group, cluster_name = cluster_parts(cluster_id)
        aks_client = ContainerServiceClient(self.credential, subscription_id)  # type: ignore[attr-defined]
        scale_sets = await self._pool_scale_sets(aks_client, subscription_id, resource_group, cluster_name)
        if nodepool_name not in scale_sets:
            raise LookupError(f"No scale set was found for node pool {nodepool_name}.")
        vmss_id = scale_sets[nodepool_name]["id"]

        async def _fetch() -> dict[str, Any]:
            points, memory_error = await asyncio.to_thread(
                self._read_vmss_metrics, subscription_id, vmss_id, lookback, grain, "Average,Maximum,Minimum"
            )
            series = utilisation_series(points)
            return {
                "nodepool_name": nodepool_name,
                "scale_set": vmss_id.rsplit("/", 1)[-1],
                "range": range_key,
                "interval": grain,
                "series": series,
                "cpu": summarize_series(series, "cpu"),
                "memory": summarize_series(series, "memory"),
                "memory_error": memory_error,
            }

        result, _tier = await data_cache.get_or_fetch(
            key=CacheKeys.node_pool_metrics(vmss_id, range_key), ttl=60, fetch_fn=_fetch
        )
        return result  # type: ignore[no-any-return]

    async def _node_pool_k8s_snapshot(self, cluster_id: str) -> tuple[list[dict[str, Any]] | None, str | None]:
        """(nodes, None), or (None, reason) when the Kubernetes API couldn't be read in time."""
        try:
            nodes = await asyncio.wait_for(self._read_pool_nodes(cluster_id), timeout=K8S_SNAPSHOT_TIMEOUT_SECONDS)
        except Exception as e:
            reason = describe_k8s_error(e)
            logger.warning(
                "node_pool_k8s_details_unavailable", cluster_id=cluster_id, reason=reason, error=str(e)[:300]
            )
            return None, reason
        return nodes, None

    async def _node_metrics(self, core_v1: Any) -> dict[str, dict[str, Any]]:
        """node → live CPU / memory usage from metrics-server; empty when it isn't installed."""
        try:
            custom = k8s_client.CustomObjectsApi(core_v1.api_client)
            body = await asyncio.to_thread(
                custom.list_cluster_custom_object, "metrics.k8s.io", "v1beta1", "nodes", _request_timeout=(5, 20)
            )
        except Exception as e:
            logger.info("node_metrics_unavailable", error=str(e)[:200])
            return {}
        return {(m.get("metadata") or {}).get("name"): m.get("usage") or {} for m in body.get("items") or []}

    async def _read_pool_nodes(self, cluster_id: str) -> list[dict[str, Any]]:
        _, core_v1, _ = await self._get_k8s_clients(cluster_id)  # type: ignore[attr-defined]
        node_list, pod_response, usage = await asyncio.gather(
            asyncio.to_thread(core_v1.list_node, _request_timeout=(5, 30)),
            # Raw JSON: deserializing thousands of V1Pod objects only to read a few fields is slow.
            asyncio.to_thread(
                core_v1.list_pod_for_all_namespaces,
                field_selector=ACTIVE_POD_SELECTOR,
                _request_timeout=(5, 60),
                _preload_content=False,
            ),
            self._node_metrics(core_v1),
        )
        pods = json.loads(pod_response.data).get("items") or []
        per_node: Counter[str] = Counter()
        requests: dict[str, list[int]] = {}
        for pod in pods:
            node = (pod.get("spec") or {}).get("nodeName")
            if not node:
                continue
            per_node[node] += 1
            cpu, memory = json_pod_requests(pod)
            totals = requests.setdefault(node, [0, 0])
            totals[0] += cpu
            totals[1] += memory
        return [
            serialize_pool_node(
                n,
                per_node.get(n.metadata.name, 0),
                tuple(requests.get(n.metadata.name, (0, 0))),  # type: ignore[arg-type]
                usage.get(n.metadata.name),
            )
            for n in node_list.items
        ]

    # ── Mutations ──────────────────────────────────────────────────────

    async def scale_node_pool(self, cluster_id: str, nodepool_name: str, node_count: int) -> dict[str, Any]:
        """Start scaling a manually-sized pool; Azure applies it in the background."""
        result: dict[str, Any] = {
            "success": False,
            "cluster_id": cluster_id,
            "nodepool_name": nodepool_name,
            "previous_count": None,
            "new_count": node_count,
        }
        try:
            subscription_id, resource_group, cluster_name = cluster_parts(cluster_id)
            aks_client = ContainerServiceClient(self.credential, subscription_id)  # type: ignore[attr-defined]
            pool = await asyncio.to_thread(aks_client.agent_pools.get, resource_group, cluster_name, nodepool_name)
            result["previous_count"] = pool.count or 0
            check_scale_request(pool, node_count)
            pool.count = node_count
            await asyncio.to_thread(
                aks_client.agent_pools.begin_create_or_update, resource_group, cluster_name, nodepool_name, pool
            )
        except NodePoolChangeError as e:
            return {**result, "error": str(e)}
        except Exception as e:
            logger.error("node_pool_scale_failed", nodepool=nodepool_name, error=str(e))
            return {**result, "error": azure_error_message(e)}

        logger.info(
            "node_pool_scale_initiated",
            cluster=cluster_name,
            nodepool=nodepool_name,
            previous=result["previous_count"],
            new=node_count,
        )
        await data_cache.invalidate_for_nodepools(cluster_id)
        return {**result, "success": True}

    async def update_node_pool_autoscaling(
        self,
        cluster_id: str,
        nodepool_name: str,
        enable_auto_scaling: bool,
        min_count: int | None = None,
        max_count: int | None = None,
    ) -> dict[str, Any]:
        """Turn the cluster autoscaler on or off for a pool, or change its range."""
        result: dict[str, Any] = {
            "success": False,
            "cluster_id": cluster_id,
            "nodepool_name": nodepool_name,
            "enable_auto_scaling": enable_auto_scaling,
            "min_count": min_count if enable_auto_scaling else None,
            "max_count": max_count if enable_auto_scaling else None,
        }
        try:
            subscription_id, resource_group, cluster_name = cluster_parts(cluster_id)
            aks_client = ContainerServiceClient(self.credential, subscription_id)  # type: ignore[attr-defined]
            pool = await asyncio.to_thread(aks_client.agent_pools.get, resource_group, cluster_name, nodepool_name)
            result["previous"] = {
                "enable_auto_scaling": bool(pool.enable_auto_scaling),
                "min_count": pool.min_count,
                "max_count": pool.max_count,
                "count": pool.count,
            }
            check_autoscaling_request(pool, enable_auto_scaling, min_count, max_count)
            pool.enable_auto_scaling = enable_auto_scaling
            pool.min_count = result["min_count"]
            pool.max_count = result["max_count"]
            await asyncio.to_thread(
                aks_client.agent_pools.begin_create_or_update, resource_group, cluster_name, nodepool_name, pool
            )
        except NodePoolChangeError as e:
            return {**result, "error": str(e)}
        except Exception as e:
            logger.error("node_pool_autoscaling_failed", nodepool=nodepool_name, error=str(e))
            return {**result, "error": azure_error_message(e)}

        logger.info(
            "node_pool_autoscaling_updated",
            cluster=cluster_name,
            nodepool=nodepool_name,
            enabled=enable_auto_scaling,
        )
        await data_cache.invalidate_for_nodepools(cluster_id)
        return {**result, "success": True}

    async def set_node_pool_power(self, cluster_id: str, nodepool_name: str, start: bool) -> dict[str, Any]:
        """Start or stop a pool's nodes; Azure applies it in the background.

        Stopping deallocates the nodes and pauses the pool's cluster autoscaler;
        starting brings the nodes back and resumes it.
        """
        action = "start" if start else "stop"
        result: dict[str, Any] = {
            "success": False,
            "cluster_id": cluster_id,
            "nodepool_name": nodepool_name,
            "action": action,
        }
        try:
            subscription_id, resource_group, cluster_name = cluster_parts(cluster_id)
            aks_client = ContainerServiceClient(self.credential, subscription_id)  # type: ignore[attr-defined]
            cluster, pool = await asyncio.gather(
                asyncio.to_thread(aks_client.managed_clusters.get, resource_group, cluster_name),
                asyncio.to_thread(aks_client.agent_pools.get, resource_group, cluster_name, nodepool_name),
            )
            result["node_count"] = pool.count
            check_power_request(cluster, pool, start)
            pool.power_state = PowerState(code="Running" if start else "Stopped")
            await asyncio.to_thread(
                aks_client.agent_pools.begin_create_or_update, resource_group, cluster_name, nodepool_name, pool
            )
        except NodePoolChangeError as e:
            return {**result, "error": str(e)}
        except Exception as e:
            logger.error("node_pool_power_failed", nodepool=nodepool_name, action=action, error=str(e))
            return {**result, "error": azure_error_message(e)}

        logger.info("node_pool_power_initiated", cluster=cluster_name, nodepool=nodepool_name, action=action)
        await data_cache.invalidate_for_nodepools(cluster_id)
        return {**result, "success": True}

    async def update_node_pool_labels_taints(
        self, cluster_id: str, nodepool_name: str, labels: dict[str, str], taints: list[str]
    ) -> dict[str, Any]:
        """Replace a pool's labels and taints; AKS applies them to its nodes in the background."""
        result: dict[str, Any] = {"success": False, "cluster_id": cluster_id, "nodepool_name": nodepool_name}
        try:
            subscription_id, resource_group, cluster_name = cluster_parts(cluster_id)
            aks_client = ContainerServiceClient(self.credential, subscription_id)  # type: ignore[attr-defined]
            pool = await asyncio.to_thread(aks_client.agent_pools.get, resource_group, cluster_name, nodepool_name)
            if _power(pool) == "Stopped":
                raise NodePoolChangeError(f"{pool.name} is stopped. Start it before changing its labels or taints.")
            if pool.provisioning_state != "Succeeded":
                raise NodePoolChangeError(f"{pool.name} is {pool.provisioning_state}. Wait for it to finish.")
            new_labels, new_taints, diff = merge_labels_and_taints(pool, labels, taints)
            result["changes"] = diff
            # Empty values (not None) so removing the last label or taint clears it.
            pool.node_labels = new_labels
            pool.node_taints = new_taints
            await asyncio.to_thread(
                aks_client.agent_pools.begin_create_or_update, resource_group, cluster_name, nodepool_name, pool
            )
        except NodePoolChangeError as e:
            return {**result, "error": str(e)}
        except Exception as e:
            logger.error("node_pool_labels_taints_failed", nodepool=nodepool_name, error=str(e))
            return {**result, "error": azure_error_message(e)}

        logger.info(
            "node_pool_labels_taints_updated", cluster=cluster_name, nodepool=nodepool_name, **result["changes"]
        )
        await data_cache.invalidate_for_nodepools(cluster_id)
        return {**result, "success": True, "node_labels": new_labels, "node_taints": new_taints}

    # ── DB inventory ───────────────────────────────────────────────────

    async def sync_node_pools_to_db(self, cluster_id: str) -> dict[str, Any]:
        """Replace this cluster's node pool rows in AzureResourceInventory with a fresh read."""
        node_pools = await self._fetch_node_pools_live(cluster_id)
        result: dict[str, Any] = {
            "synced_count": len(node_pools),
            "resource_type": INVENTORY_TYPE,
            "cluster_id": cluster_id,
            "last_sync": datetime.utcnow().isoformat(),
            "node_details_error": next((p["node_details_error"] for p in node_pools if p["node_details_error"]), None),
            "resources": node_pools,
            "db_saved": False,
        }
        if not self.db:  # type: ignore[attr-defined]
            return result

        subscription_id, resource_group, _ = cluster_parts(cluster_id)
        try:
            await self.db.execute(  # type: ignore[attr-defined]
                delete(AzureResourceInventory).where(
                    AzureResourceInventory.resource_type == INVENTORY_TYPE,
                    AzureResourceInventory.resource_id.like(f"{cluster_id}/nodepool/%"),
                )
            )
            for np in node_pools:
                self.db.add(  # type: ignore[attr-defined]
                    AzureResourceInventory(
                        resource_id=f"{cluster_id}/nodepool/{np['name']}",
                        name=np["name"],
                        resource_type=INVENTORY_TYPE,
                        resource_group=resource_group,
                        location="",
                        subscription_id=subscription_id,
                        provisioning_state=np.get("provisioning_state") or "Unknown",
                        tags={},
                        resource_details={**np, "_cluster_id": cluster_id},
                    )
                )
            await self.db.commit()  # type: ignore[attr-defined]
        except Exception as e:
            logger.error("aks_node_pools_sync_failed", cluster_id=cluster_id, error=str(e))
            await self.db.rollback()  # type: ignore[attr-defined]
            raise
        logger.info("aks_node_pools_synced_to_db", cluster_id=cluster_id, count=len(node_pools))
        return {**result, "db_saved": True}

    async def get_node_pools_from_db(self, cluster_id: str) -> list[dict[str, Any]]:
        """Node pools as last synced — no Azure or Kubernetes call."""
        if not self.db:  # type: ignore[attr-defined]
            return []
        try:
            result = await self.db.execute(  # type: ignore[attr-defined]
                select(AzureResourceInventory)
                .where(
                    AzureResourceInventory.resource_type == INVENTORY_TYPE,
                    AzureResourceInventory.resource_id.like(f"{cluster_id}/nodepool/%"),
                )
                .order_by(AzureResourceInventory.name, AzureResourceInventory.last_sync.desc())
            )
            pools: dict[str, dict[str, Any]] = {}
            for r in result.scalars().all():
                # Two overlapping syncs can briefly leave duplicate rows; keep the newest.
                if r.name in pools:
                    continue
                details = dict(r.resource_details or {})
                details["_last_sync"] = r.last_sync.isoformat() if r.last_sync else None
                pools[r.name] = details
            return list(pools.values())
        except Exception as e:
            logger.error("get_node_pools_from_db_failed", cluster_id=cluster_id, error=str(e))
            return []

    async def get_node_pools_last_sync_time(self, cluster_id: str) -> str | None:
        if not self.db:  # type: ignore[attr-defined]
            return None
        try:
            result = await self.db.execute(  # type: ignore[attr-defined]
                select(func.max(AzureResourceInventory.last_sync)).where(
                    AzureResourceInventory.resource_type == INVENTORY_TYPE,
                    AzureResourceInventory.resource_id.like(f"{cluster_id}/nodepool/%"),
                )
            )
            last_sync = result.scalar()
            return last_sync.isoformat() if last_sync else None
        except Exception as e:
            logger.error("get_node_pools_last_sync_failed", cluster_id=cluster_id, error=str(e))
            return None
