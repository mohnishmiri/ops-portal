"""Node detail for AKS: a node's health, capacity, and the pods running on it.

Mirrors ``kubectl describe node``: conditions, system info, capacity and
allocatable resources, the pods scheduled on the node with their resource
requests, the share of allocatable CPU and memory those requests take, and the
node's events. Live usage from metrics-server is added when it's installed.
"""

from __future__ import annotations

import asyncio
from typing import Any

import structlog
from kubernetes import client as k8s_client
from kubernetes.client.rest import ApiException

from app.services.aks_detail_operations import _annotations, _conditions
from app.services.aks_workload_operations import _iso, newest_events, serialize_event, serialize_pod
from app.services.k8s_usage import attach_pod_usage, pod_requests, read_pod_usage, to_bytes, to_millicores

logger = structlog.get_logger(__name__)

PRESSURE_CONDITIONS = ("MemoryPressure", "DiskPressure", "PIDPressure", "NetworkUnavailable")
TERMINATED_PHASES = ("Succeeded", "Failed")


def _resource_block(resources: dict[str, Any] | None) -> dict[str, Any]:
    resources = resources or {}
    return {
        "cpu_m": to_millicores(resources.get("cpu")),
        "memory_bytes": to_bytes(resources.get("memory")),
        "pods": to_bytes(resources.get("pods")),  # a plain count
        "ephemeral_storage_bytes": to_bytes(resources.get("ephemeral-storage")),
    }


def serialize_node_pod(pod: Any) -> dict[str, Any]:
    statuses = pod.status.container_statuses or []
    owner = next((r for r in (pod.metadata.owner_references or []) if r.controller), None)
    return {
        **serialize_pod(pod),
        **pod_requests(pod),
        "ready_containers": sum(1 for cs in statuses if cs.ready),
        "total_containers": len(pod.spec.containers or []),
        "owner_kind": owner.kind if owner else None,
        "owner_name": owner.name if owner else None,
        "qos_class": pod.status.qos_class,
        "terminated": pod.status.phase in TERMINATED_PHASES,
    }


def _percent(part: int, whole: int) -> float | None:
    return round(part * 100 / whole, 1) if whole else None


def serialize_node_detail(
    node: Any,
    pods: list[Any],
    events: list[dict[str, Any]],
    usage: dict[str, Any] | None,
    pod_usage: dict[tuple[str, str], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    meta, spec, status = node.metadata, node.spec, node.status
    labels = dict(meta.labels or {})
    conditions = _conditions(status.conditions)
    condition_status = {c["type"]: c["status"] for c in conditions}
    info = status.node_info
    allocatable = _resource_block(status.allocatable)
    pod_rows = attach_pod_usage(
        sorted((serialize_node_pod(p) for p in pods), key=lambda p: (p["namespace"], p["pod_name"])), pod_usage
    )
    active = [p for p in pod_rows if not p["terminated"]]
    requested = {
        "cpu_request_m": sum(p["cpu_request_m"] for p in active),
        "cpu_limit_m": sum(p["cpu_limit_m"] for p in active),
        "memory_request_bytes": sum(p["memory_request_bytes"] for p in active),
        "memory_limit_bytes": sum(p["memory_limit_bytes"] for p in active),
    }
    taints = [f"{t.key}{'=' + t.value if t.value else ''}:{t.effect}" for t in (spec.taints or [])]
    return {
        "name": meta.name,
        "pool": labels.get("kubernetes.azure.com/agentpool") or labels.get("agentpool"),
        "ready": condition_status.get("Ready") == "True",
        "unschedulable": bool(spec.unschedulable),
        "pressure": [c for c in PRESSURE_CONDITIONS if condition_status.get(c) == "True"],
        "created_at": _iso(meta.creation_timestamp),
        "zone": labels.get("topology.kubernetes.io/zone"),
        "instance_type": labels.get("node.kubernetes.io/instance-type"),
        "node_image_version": labels.get("kubernetes.azure.com/node-image-version"),
        "provider_id": spec.provider_id,
        "pod_cidr": spec.pod_cidr,
        "addresses": [{"type": a.type, "address": a.address} for a in (status.addresses or [])],
        "system": {
            "os_image": info.os_image if info else None,
            "kernel_version": info.kernel_version if info else None,
            "container_runtime": info.container_runtime_version if info else None,
            "kubelet_version": info.kubelet_version if info else None,
            "kube_proxy_version": info.kube_proxy_version if info else None,
            "architecture": info.architecture if info else None,
            "operating_system": info.operating_system if info else None,
        },
        "capacity": _resource_block(status.capacity),
        "allocatable": allocatable,
        "allocated": {
            **requested,
            "pods": len(active),
            "cpu_request_pct": _percent(requested["cpu_request_m"], allocatable["cpu_m"]),
            "memory_request_pct": _percent(requested["memory_request_bytes"], allocatable["memory_bytes"]),
            "cpu_limit_pct": _percent(requested["cpu_limit_m"], allocatable["cpu_m"]),
            "memory_limit_pct": _percent(requested["memory_limit_bytes"], allocatable["memory_bytes"]),
        },
        "usage": usage,
        "conditions": conditions,
        "taints": taints,
        "labels": labels,
        "annotations": _annotations(meta),
        "pods": pod_rows,
        "events": events,
    }


class AKSNodeOperationsMixin:
    """Live detail for one Kubernetes node."""

    async def _node_usage(self, core_v1: Any, name: str, allocatable: dict[str, Any]) -> dict[str, Any] | None:
        """CPU and memory in use from metrics-server, or None when it isn't available."""
        try:
            custom = k8s_client.CustomObjectsApi(core_v1.api_client)
            metrics = await asyncio.to_thread(
                custom.get_cluster_custom_object, "metrics.k8s.io", "v1beta1", "nodes", name, _request_timeout=(5, 15)
            )
        except Exception as e:
            logger.info("node_metrics_unavailable", node=name, error=str(e)[:200])
            return None
        usage = metrics.get("usage") or {}
        cpu_m, memory = to_millicores(usage.get("cpu")), to_bytes(usage.get("memory"))
        return {
            "cpu_m": cpu_m,
            "memory_bytes": memory,
            "cpu_pct": _percent(cpu_m, allocatable["cpu_m"]),
            "memory_pct": _percent(memory, allocatable["memory_bytes"]),
            "timestamp": metrics.get("timestamp"),
        }

    async def get_node_detail(self, cluster_id: str, name: str) -> dict[str, Any]:
        _, core_v1, _ = await self._get_k8s_clients(cluster_id)  # type: ignore[attr-defined]
        node = await asyncio.to_thread(core_v1.read_node, name, _request_timeout=(5, 30))

        async def _events() -> list[dict[str, Any]]:
            try:
                result = await asyncio.to_thread(
                    core_v1.list_event_for_all_namespaces,
                    field_selector=f"involvedObject.kind=Node,involvedObject.name={name}",
                    _request_timeout=(5, 30),
                )
            except ApiException as e:
                logger.warning("node_events_failed", node=name, status=e.status)
                return []
            return newest_events([serialize_event(ev) for ev in result.items])

        pods, events, usage, pod_usage = await asyncio.gather(
            asyncio.to_thread(
                core_v1.list_pod_for_all_namespaces, field_selector=f"spec.nodeName={name}", _request_timeout=(5, 60)
            ),
            _events(),
            self._node_usage(core_v1, name, _resource_block(node.status.allocatable)),
            read_pod_usage(core_v1),
        )
        detail = serialize_node_detail(node, list(pods.items), events, usage, pod_usage)
        detail["pod_usage_available"] = pod_usage is not None
        return detail
