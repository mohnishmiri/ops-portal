"""Deployment and Pod detail views for AKS.

Mirrors the StatefulSet/DaemonSet detail in ``aks_workload_operations``: a live
read of the object plus the pods, revisions (ReplicaSets), events, and manifest
an operator needs to diagnose it.  Supporting lookups fail soft — a missing
HPA or a forbidden event list must not hide the rest of the detail.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable
from typing import Any, TypeVar

import structlog
from kubernetes import client as k8s_client
from kubernetes.client.rest import ApiException

from app.services.aks_workload_operations import (
    _iso,
    _label_selector,
    _owned_by,
    newest_events,
    pod_status_reason,
    serialize_event,
    serialize_pod,
    workload_status,
)

logger = structlog.get_logger(__name__)

T = TypeVar("T")

REVISION_ANNOTATION = "deployment.kubernetes.io/revision"
# Duplicates the whole manifest; the YAML tab already shows it.
_HIDDEN_ANNOTATIONS = {"kubectl.kubernetes.io/last-applied-configuration"}


# ── Pure helpers ──────────────────────────────────────────────────────


def _annotations(meta: Any) -> dict[str, str]:
    return {k: v for k, v in (meta.annotations or {}).items() if k not in _HIDDEN_ANNOTATIONS}


def _resources(container: Any | None) -> dict[str, str]:
    res = container.resources if container else None
    requests = dict(res.requests) if res and res.requests else {}
    limits = dict(res.limits) if res and res.limits else {}
    return {
        "cpu_request": requests.get("cpu", ""),
        "cpu_limit": limits.get("cpu", ""),
        "memory_request": requests.get("memory", ""),
        "memory_limit": limits.get("memory", ""),
    }


def _ports(container: Any) -> list[str]:
    return [
        f"{p.container_port}/{p.protocol or 'TCP'}" + (f" ({p.name})" if p.name else "")
        for p in (container.ports or [])
    ]


def _conditions(conditions: Any) -> list[dict[str, Any]]:
    return [
        {
            "type": c.type,
            "status": c.status,
            "reason": c.reason,
            "message": c.message,
            "last_transition_time": _iso(c.last_transition_time),
        }
        for c in (conditions or [])
    ]


def _str_or_none(value: Any) -> str | None:
    return str(value) if value is not None else None


def spec_dict(obj: Any) -> Any:
    """Kubernetes client model → manifest-style dict (camelCase keys, unset fields dropped)."""
    if obj is None or isinstance(obj, str | int | float | bool):
        return obj
    if isinstance(obj, list):
        return [spec_dict(v) for v in obj]
    if isinstance(obj, dict):
        return {k: spec_dict(v) for k, v in obj.items() if v is not None}
    attribute_map = getattr(obj, "attribute_map", None)
    if not isinstance(attribute_map, dict):
        return str(obj)
    return {
        key: spec_dict(value) for attr, key in attribute_map.items() if (value := getattr(obj, attr, None)) is not None
    }


def image_checksum(image_id: str | None) -> str | None:
    """The 64-hex sha256 digest of the image a container is actually running.

    Parsed from ``containerStatus.imageID`` exactly as Compliance → AKS Checksum
    does (``ComplianceService._extract_image_shas``), so the values match.
    Docker/CRI-O report ``repo@sha256:<hex>``; some containerd versions ``sha256:<hex>``.
    """
    if not image_id:
        return None
    if "@sha256:" in image_id:
        return image_id.split("@sha256:", 1)[1]
    if image_id.startswith("sha256:"):
        return image_id[len("sha256:") :]
    return None


def probe_summary(probe: Any) -> str:
    """One-line ``kubectl describe``-style probe summary."""
    exec_action = getattr(probe, "_exec", None) or getattr(probe, "exec", None)
    if probe.http_get:
        h = probe.http_get
        action = f"http-get {(h.scheme or 'HTTP').lower()}://:{h.port}{h.path or '/'}"
    elif probe.tcp_socket:
        action = f"tcp-socket :{probe.tcp_socket.port}"
    elif exec_action:
        action = "exec [" + " ".join(exec_action.command or []) + "]"
    elif getattr(probe, "grpc", None):
        action = f"grpc :{probe.grpc.port}"
    else:
        action = "unknown"
    return (
        f"{action} delay={probe.initial_delay_seconds or 0}s timeout={probe.timeout_seconds or 1}s "
        f"period={probe.period_seconds or 10}s #success={probe.success_threshold or 1} "
        f"#failure={probe.failure_threshold or 3}"
    )


def container_state(state: Any) -> dict[str, Any] | None:
    if not state:
        return None
    if state.running:
        return {"state": "running", "started_at": _iso(state.running.started_at)}
    if state.waiting:
        return {"state": "waiting", "reason": state.waiting.reason, "message": state.waiting.message}
    if state.terminated:
        t = state.terminated
        return {
            "state": "terminated",
            "reason": t.reason,
            "message": t.message,
            "exit_code": t.exit_code,
            "signal": t.signal,
            "started_at": _iso(t.started_at),
            "finished_at": _iso(t.finished_at),
        }
    return None


def serialize_container(container: Any, status: Any, *, init: bool) -> dict[str, Any]:
    probes = (
        ("liveness", container.liveness_probe),
        ("readiness", container.readiness_probe),
        ("startup", container.startup_probe),
    )
    return {
        "name": container.name,
        "image": container.image,
        "image_id": status.image_id if status else None,
        "image_checksum": image_checksum(status.image_id) if status else None,
        "init": init,
        "sidecar": init and getattr(container, "restart_policy", None) == "Always",
        "ready": bool(status.ready) if status else False,
        "restart_count": (status.restart_count or 0) if status else 0,
        "state": container_state(status.state) if status else None,
        "last_state": container_state(status.last_state) if status else None,
        "ports": _ports(container),
        **_resources(container),
        "probes": {kind: probe_summary(p) for kind, p in probes if p},
        "volume_mounts": [
            {
                "name": m.name,
                "mount_path": m.mount_path,
                "read_only": bool(m.read_only),
                "sub_path": m.sub_path or None,
            }
            for m in (container.volume_mounts or [])
        ],
    }


# (attribute on V1Volume, display type, attribute holding the source name)
_VOLUME_SOURCES: tuple[tuple[str, str, str | None], ...] = (
    ("config_map", "ConfigMap", "name"),
    ("secret", "Secret", "secret_name"),
    ("persistent_volume_claim", "PersistentVolumeClaim", "claim_name"),
    ("empty_dir", "EmptyDir", "medium"),
    ("host_path", "HostPath", "path"),
    ("projected", "Projected", None),
    ("csi", "CSI", "driver"),
    ("downward_api", "DownwardAPI", None),
    ("azure_file", "AzureFile", "share_name"),
    ("azure_disk", "AzureDisk", "disk_name"),
    ("nfs", "NFS", "path"),
    ("ephemeral", "Ephemeral", None),
)


def _projected_sources(projected: Any) -> str | None:
    parts = []
    for s in projected.sources or []:
        if s.config_map:
            parts.append(f"configMap:{s.config_map.name}")
        elif s.secret:
            parts.append(f"secret:{s.secret.name}")
        elif s.service_account_token:
            parts.append("serviceAccountToken")
        elif s.downward_api:
            parts.append("downwardAPI")
    return ", ".join(parts) or None


def serialize_volume(volume: Any) -> dict[str, Any]:
    for attr, label, name_attr in _VOLUME_SOURCES:
        source = getattr(volume, attr, None)
        if source is None:
            continue
        if attr == "projected":
            detail = _projected_sources(source)
        else:
            detail = _str_or_none(getattr(source, name_attr, None)) if name_attr else None
        return {"name": volume.name, "type": label, "source": detail, "spec": spec_dict(source)}
    spec = spec_dict(volume)
    spec.pop("name", None)
    return {"name": volume.name, "type": "Other", "source": None, "spec": spec}


def serialize_claim(pvc: Any) -> dict[str, Any]:
    spec, status = pvc.spec, pvc.status
    requests = dict(spec.resources.requests or {}) if spec.resources else {}
    capacity = dict(status.capacity or {}) if status else {}
    return {
        "name": pvc.metadata.name,
        "phase": status.phase if status else None,
        "capacity": capacity.get("storage"),
        "requested": requests.get("storage"),
        "access_modes": list(spec.access_modes or []),
        "storage_class": spec.storage_class_name,
        "volume_name": spec.volume_name,
        "volume_mode": spec.volume_mode,
        "created_at": _iso(pvc.metadata.creation_timestamp),
    }


def _toleration(t: Any) -> str:
    if t.operator == "Exists" and not t.key:
        target = "*"
    elif t.operator == "Exists":
        target = t.key
    else:
        target = f"{t.key}={t.value or ''}"
    text = f"{target}:{t.effect or 'All'}"
    return f"{text} for {t.toleration_seconds}s" if t.toleration_seconds is not None else text


def serialize_pod_detail(pod: Any) -> dict[str, Any]:
    meta, spec, status = pod.metadata, pod.spec, pod.status
    statuses = {cs.name: cs for cs in (status.container_statuses or [])}
    init_statuses = {cs.name: cs for cs in (status.init_container_statuses or [])}
    containers = [serialize_container(c, statuses.get(c.name), init=False) for c in (spec.containers or [])]
    init_containers = [
        serialize_container(c, init_statuses.get(c.name), init=True) for c in (spec.init_containers or [])
    ]
    owners = meta.owner_references or []
    owner = next((r for r in owners if r.controller), owners[0] if owners else None)
    # Compliance fingerprints a pod by the first digest in status order (the kubelet sorts
    # statuses by container name), so take it the same way for a value users can compare.
    checksums = [image_checksum(cs.image_id) for cs in (status.container_statuses or [])]
    return {
        "name": meta.name,
        "namespace": meta.namespace,
        "uid": meta.uid,
        "phase": status.phase,
        "status": pod_status_reason(pod),
        "status_message": status.message,
        "ready_containers": sum(1 for c in containers if c["ready"]),
        "total_containers": len(containers),
        "restarts": sum(c["restart_count"] for c in containers),
        "image_checksum": next((c for c in checksums if c), None),
        "node": spec.node_name,
        "pod_ip": status.pod_ip,
        "pod_ips": [ip.ip for ip in (getattr(status, "pod_i_ps", None) or [])],
        "host_ip": status.host_ip,
        "qos_class": status.qos_class,
        "service_account": spec.service_account_name,
        "restart_policy": spec.restart_policy,
        "priority_class": spec.priority_class_name,
        "termination_grace_period_seconds": spec.termination_grace_period_seconds,
        "created_at": _iso(meta.creation_timestamp),
        "started_at": _iso(status.start_time),
        "deletion_timestamp": _iso(meta.deletion_timestamp),
        "owner": {"kind": owner.kind, "name": owner.name} if owner else None,
        "workload": None,
        "labels": dict(meta.labels or {}),
        "annotations": _annotations(meta),
        "node_selector": dict(spec.node_selector or {}),
        "tolerations": [_toleration(t) for t in (spec.tolerations or [])],
        "conditions": _conditions(status.conditions),
        "init_containers": init_containers,
        "containers": containers,
        "volumes": [serialize_volume(v) for v in (spec.volumes or [])],
    }


def deployment_status(
    desired: int,
    ready: int,
    updated: int,
    generation: int | None,
    observed_generation: int | None,
    conditions: list[dict[str, Any]],
) -> str:
    status = workload_status(desired, ready, updated, desired, generation, observed_generation)
    stalled = any(c["type"] == "Progressing" and c["reason"] == "ProgressDeadlineExceeded" for c in conditions)
    if stalled and status in ("Updating", "Healthy"):
        return "Degraded"
    return status


def serialize_deployment(dep: Any) -> dict[str, Any]:
    meta, spec, status = dep.metadata, dep.spec, dep.status
    pod_spec = spec.template.spec if spec.template else None
    containers = (pod_spec.containers if pod_spec else None) or []
    strategy = spec.strategy
    rolling = strategy.rolling_update if strategy else None
    desired = spec.replicas if spec.replicas is not None else 1
    ready = status.ready_replicas or 0
    updated = status.updated_replicas or 0
    conditions = _conditions(status.conditions)
    annotations = _annotations(meta)
    return {
        "kind": "Deployment",
        "name": meta.name,
        "namespace": meta.namespace,
        "uid": meta.uid,
        "labels": dict(meta.labels or {}),
        "annotations": annotations,
        "selector": dict(spec.selector.match_labels or {}) if spec.selector else {},
        "images": [c.image for c in containers],
        "containers": [{"name": c.name, "image": c.image, "ports": _ports(c), **_resources(c)} for c in containers],
        "created_at": _iso(meta.creation_timestamp),
        "generation": meta.generation,
        "observed_generation": status.observed_generation,
        "desired": desired,
        "ready": ready,
        "updated": updated,
        "available": status.available_replicas or 0,
        "unavailable": status.unavailable_replicas or 0,
        "update_strategy": strategy.type if strategy else None,
        "max_surge": _str_or_none(getattr(rolling, "max_surge", None)),
        "max_unavailable": _str_or_none(getattr(rolling, "max_unavailable", None)),
        "min_ready_seconds": spec.min_ready_seconds or 0,
        "revision_history_limit": spec.revision_history_limit,
        "progress_deadline_seconds": spec.progress_deadline_seconds,
        "paused": bool(spec.paused),
        "revision": annotations.get(REVISION_ANNOTATION),
        "node_selector": dict(pod_spec.node_selector or {}) if pod_spec else {},
        "service_account": pod_spec.service_account_name if pod_spec else None,
        **_resources(containers[0] if containers else None),
        "conditions": conditions,
        "status": deployment_status(desired, ready, updated, meta.generation, status.observed_generation, conditions),
    }


def serialize_replica_set(rs: Any) -> dict[str, Any]:
    revision = (rs.metadata.annotations or {}).get(REVISION_ANNOTATION, "")
    pod_spec = rs.spec.template.spec if rs.spec.template else None
    return {
        "name": rs.metadata.name,
        "revision": int(revision) if revision.isdigit() else 0,
        "desired": rs.spec.replicas or 0,
        "ready": rs.status.ready_replicas or 0,
        "available": rs.status.available_replicas or 0,
        "images": [c.image for c in ((pod_spec.containers if pod_spec else None) or [])],
        "created_at": _iso(rs.metadata.creation_timestamp),
        "pod_template_hash": (rs.metadata.labels or {}).get("pod-template-hash"),
    }


def _metric_value(value: Any) -> str | None:
    if value is None:
        return None
    if getattr(value, "average_utilization", None) is not None:
        return f"{value.average_utilization}%"
    for attr in ("average_value", "value"):
        if getattr(value, attr, None) is not None:
            return str(getattr(value, attr))
    return None


def serialize_hpa(hpa: Any) -> dict[str, Any]:
    current: dict[str, Any] = {}
    for m in hpa.status.current_metrics or []:
        if m.type == "Resource" and m.resource:
            current[m.resource.name] = m.resource.current
    metrics = []
    for m in hpa.spec.metrics or []:
        if m.type == "Resource" and m.resource:
            metrics.append(
                {
                    "name": m.resource.name,
                    "target": _metric_value(m.resource.target),
                    "current": _metric_value(current.get(m.resource.name)),
                }
            )
        else:
            metrics.append({"name": m.type, "target": None, "current": None})
    return {
        "name": hpa.metadata.name,
        "min_replicas": hpa.spec.min_replicas or 1,
        "max_replicas": hpa.spec.max_replicas,
        "current_replicas": hpa.status.current_replicas,
        "desired_replicas": hpa.status.desired_replicas,
        "last_scale_time": _iso(hpa.status.last_scale_time),
        "metrics": metrics,
    }


# ── Service mixin ─────────────────────────────────────────────────────


class AKSDetailOperationsMixin:
    """Deployment and Pod detail, plus the ownership lookups the log archive reuses."""

    @staticmethod
    async def _soft(call: Awaitable[T], default: T, event: str, **context: Any) -> T:
        try:
            return await call
        except ApiException as e:
            logger.warning(event, status=e.status, **context)
            return default

    async def _owned_replica_sets(self, apps_v1: Any, namespace: str, selector: str | None, uid: str) -> list[Any]:
        rs_list = await asyncio.to_thread(apps_v1.list_namespaced_replica_set, namespace, label_selector=selector)
        return [rs for rs in rs_list.items if _owned_by(rs.metadata, uid)]

    async def _owned_pods(self, core_v1: Any, namespace: str, selector: str | None, owner_uids: set[str]) -> list[Any]:
        pod_list = await asyncio.to_thread(core_v1.list_namespaced_pod, namespace, label_selector=selector)
        return [p for p in pod_list.items if any(ref.uid in owner_uids for ref in (p.metadata.owner_references or []))]

    async def _replica_set_events(self, core_v1: Any, namespace: str, names: set[str]) -> list[dict[str, Any]]:
        """Events of a Deployment's ReplicaSets — where FailedCreate (quota, admission) surfaces."""
        if not names:
            return []
        ev_list = await self._soft(
            asyncio.to_thread(
                core_v1.list_namespaced_event, namespace, field_selector="involvedObject.kind=ReplicaSet"
            ),
            None,
            "replicaset_events_failed",
            namespace=namespace,
        )
        if ev_list is None:
            return []
        return [serialize_event(ev) for ev in ev_list.items if ev.involved_object.name in names]

    async def _deployment_hpa(self, apps_v1: Any, namespace: str, name: str) -> dict[str, Any] | None:
        api_client = getattr(apps_v1, "api_client", None)
        if api_client is None:
            return None
        try:
            autoscaling = k8s_client.AutoscalingV2Api(api_client)
            hpas = await asyncio.to_thread(autoscaling.list_namespaced_horizontal_pod_autoscaler, namespace)
        except Exception as exc:
            logger.warning("deployment_hpa_lookup_failed", namespace=namespace, error=str(exc))
            return None
        for hpa in hpas.items:
            ref = hpa.spec.scale_target_ref
            if ref and ref.kind == "Deployment" and ref.name == name:
                return serialize_hpa(hpa)
        return None

    async def get_deployment_detail(
        self,
        cluster_id: str,
        namespace: str,
        deployment_name: str,
    ) -> dict[str, Any]:
        """Live Deployment detail: overview, pods, ReplicaSet revisions, events, HPA, and YAML."""
        apps_v1, core_v1, _ = await self._get_k8s_clients(cluster_id)  # type: ignore[attr-defined]
        dep = await asyncio.to_thread(apps_v1.read_namespaced_deployment, deployment_name, namespace)
        detail = serialize_deployment(dep)
        selector = _label_selector(detail["selector"])

        replica_sets = await self._soft(
            self._owned_replica_sets(apps_v1, namespace, selector, dep.metadata.uid),
            [],
            "deployment_replicasets_failed",
            namespace=namespace,
            name=deployment_name,
        )
        pods, dep_events, rs_events, hpa = await asyncio.gather(
            self._soft(
                self._owned_pods(core_v1, namespace, selector, {rs.metadata.uid for rs in replica_sets}),
                [],
                "deployment_pods_failed",
                namespace=namespace,
                name=deployment_name,
            ),
            self._workload_events(core_v1, namespace, "Deployment", deployment_name),  # type: ignore[attr-defined]
            self._replica_set_events(core_v1, namespace, {rs.metadata.name for rs in replica_sets}),
            self._deployment_hpa(apps_v1, namespace, deployment_name),
        )

        revisions = sorted((serialize_replica_set(rs) for rs in replica_sets), key=lambda r: -r["revision"])
        for rev in revisions:
            rev["is_current"] = str(rev["revision"]) == detail["revision"]
        revision_by_hash = {r["pod_template_hash"]: str(r["revision"]) for r in revisions if r["pod_template_hash"]}
        pod_rows = []
        for pod in sorted(pods, key=lambda p: p.metadata.name):
            row = serialize_pod(pod)
            row["revision"] = revision_by_hash.get(row["revision"], row["revision"])
            pod_rows.append(row)

        detail.update(
            {
                "pods": pod_rows,
                "revisions": revisions,
                "events": newest_events(dep_events + rs_events),
                "hpa": hpa,
                "yaml": self._manifest_yaml(apps_v1, dep),  # type: ignore[attr-defined]
            }
        )
        return detail

    async def get_pod_detail(self, cluster_id: str, namespace: str, name: str) -> dict[str, Any]:
        """Live Pod detail: status, containers (with last termination), volumes, events, and YAML."""
        apps_v1, core_v1, _ = await self._get_k8s_clients(cluster_id)  # type: ignore[attr-defined]
        pod = await asyncio.to_thread(core_v1.read_namespaced_pod, name, namespace)
        detail = serialize_pod_detail(pod)
        claim_volumes = [v for v in detail["volumes"] if v["type"] == "PersistentVolumeClaim" and v["source"]]
        events, *claims = await asyncio.gather(
            self._workload_events(core_v1, namespace, "Pod", name),  # type: ignore[attr-defined]
            *(
                self._soft(
                    asyncio.to_thread(core_v1.read_namespaced_persistent_volume_claim, v["source"], namespace),
                    None,
                    "pod_pvc_lookup_failed",
                    namespace=namespace,
                    claim=v["source"],
                )
                for v in claim_volumes
            ),
        )
        detail["events"] = events
        for volume, pvc in zip(claim_volumes, claims, strict=True):
            volume["claim"] = serialize_claim(pvc) if pvc else None

        # A ReplicaSet owner is an implementation detail — surface the Deployment behind it.
        owner = detail["owner"]
        if owner and owner["kind"] == "ReplicaSet":
            rs = await self._soft(
                asyncio.to_thread(apps_v1.read_namespaced_replica_set, owner["name"], namespace),
                None,
                "pod_owner_lookup_failed",
                namespace=namespace,
                name=name,
            )
            rs_owner = next((r for r in (rs.metadata.owner_references or []) if r.controller), None) if rs else None
            if rs_owner:
                detail["workload"] = {"kind": rs_owner.kind, "name": rs_owner.name}
        elif owner:
            detail["workload"] = owner

        detail["yaml"] = self._manifest_yaml(apps_v1, pod)  # type: ignore[attr-defined]
        return detail
