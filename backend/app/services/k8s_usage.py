"""Kubernetes resource quantities, pod requests, and live usage from metrics-server.

Shared by every AKS view that shows CPU or memory, so they all count the same
way: requests as the scheduler does (the larger of the containers' sum and the
biggest init container), and usage from ``metrics.k8s.io`` when metrics-server
is installed. Usage is ``None`` — never zero — when it can't be read.
"""

from __future__ import annotations

import asyncio
from decimal import Decimal
from typing import Any

import structlog
from kubernetes import client as k8s_client
from kubernetes.client.rest import ApiException
from kubernetes.utils import parse_quantity

logger = structlog.get_logger(__name__)

METRICS_GROUP, METRICS_VERSION = "metrics.k8s.io", "v1beta1"

PodKey = tuple[str, str]  # (namespace, pod name)


def _quantity(value: Any) -> Decimal:
    try:
        return parse_quantity(value) if value not in (None, "") else Decimal(0)
    except ValueError:
        return Decimal(0)


def to_millicores(value: Any) -> int:
    return int(_quantity(value) * 1000)


def to_bytes(value: Any) -> int:
    return int(_quantity(value))


def _container_resources(container: Any, kind: str) -> dict[str, Any]:
    return (getattr(container.resources, kind, None) or {}) if container.resources else {}


def pod_requests(pod: Any) -> dict[str, int]:
    """Requests and limits of a V1Pod as the scheduler counts them."""
    containers = pod.spec.containers or []
    init = pod.spec.init_containers or []

    def effective(kind: str, resource: str, convert: Any) -> int:
        app = sum(convert(_container_resources(c, kind).get(resource)) for c in containers)
        return max(app, max((convert(_container_resources(c, kind).get(resource)) for c in init), default=0))

    return {
        "cpu_request_m": effective("requests", "cpu", to_millicores),
        "cpu_limit_m": effective("limits", "cpu", to_millicores),
        "memory_request_bytes": effective("requests", "memory", to_bytes),
        "memory_limit_bytes": effective("limits", "memory", to_bytes),
    }


def json_pod_requests(pod: dict[str, Any]) -> tuple[int, int]:
    """(CPU millicores, memory bytes) requested by a pod given as raw API JSON."""
    spec = pod.get("spec") or {}

    def request(container: dict[str, Any], resource: str) -> Any:
        return ((container.get("resources") or {}).get("requests") or {}).get(resource)

    containers, init = spec.get("containers") or [], spec.get("initContainers") or []
    cpu = max(
        sum(to_millicores(request(c, "cpu")) for c in containers),
        max((to_millicores(request(c, "cpu")) for c in init), default=0),
    )
    memory = max(
        sum(to_bytes(request(c, "memory")) for c in containers),
        max((to_bytes(request(c, "memory")) for c in init), default=0),
    )
    return cpu, memory


def _usage_record(item: dict[str, Any]) -> dict[str, Any]:
    containers = {
        c.get("name"): {
            "cpu_m": to_millicores((c.get("usage") or {}).get("cpu")),
            "memory_bytes": to_bytes((c.get("usage") or {}).get("memory")),
        }
        for c in item.get("containers") or []
    }
    return {
        "cpu_m": sum(c["cpu_m"] for c in containers.values()),
        "memory_bytes": sum(c["memory_bytes"] for c in containers.values()),
        "containers": containers,
        "timestamp": item.get("timestamp"),
    }


async def read_pod_usage(
    core_v1: Any, namespace: str | None = None, name: str | None = None
) -> dict[PodKey, dict[str, Any]] | None:
    """Live pod usage from metrics-server: one pod, one namespace, or the whole cluster.

    Returns None when metrics-server can't be read, and an empty map when it
    has no sample for the pod yet (e.g. a pod that just started).
    """
    try:
        custom = k8s_client.CustomObjectsApi(core_v1.api_client)
        if name and namespace:
            body = await asyncio.to_thread(
                custom.get_namespaced_custom_object,
                METRICS_GROUP,
                METRICS_VERSION,
                namespace,
                "pods",
                name,
                _request_timeout=(5, 15),
            )
            items = [body]
        elif namespace:
            body = await asyncio.to_thread(
                custom.list_namespaced_custom_object,
                METRICS_GROUP,
                METRICS_VERSION,
                namespace,
                "pods",
                _request_timeout=(5, 20),
            )
            items = body.get("items") or []
        else:
            body = await asyncio.to_thread(
                custom.list_cluster_custom_object, METRICS_GROUP, METRICS_VERSION, "pods", _request_timeout=(5, 30)
            )
            items = body.get("items") or []
    except ApiException as e:
        if e.status == 404 and name:
            return {}
        logger.info("pod_metrics_unavailable", namespace=namespace, status=e.status)
        return None
    except Exception as e:
        logger.info("pod_metrics_unavailable", namespace=namespace, error=str(e)[:200])
        return None
    return {
        ((i.get("metadata") or {}).get("namespace", ""), (i.get("metadata") or {}).get("name", "")): _usage_record(i)
        for i in items
    }


def attach_pod_usage(rows: list[dict[str, Any]], usage: dict[PodKey, dict[str, Any]] | None) -> list[dict[str, Any]]:
    """Add ``cpu_usage_m`` / ``memory_usage_bytes`` to pod rows (None when not measured)."""
    for row in rows:
        sample = (usage or {}).get((row.get("namespace", ""), row.get("pod_name", "")))
        row["cpu_usage_m"] = sample["cpu_m"] if sample else None
        row["memory_usage_bytes"] = sample["memory_bytes"] if sample else None
    return rows
