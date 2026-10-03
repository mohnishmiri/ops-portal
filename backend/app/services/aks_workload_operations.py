"""StatefulSet / DaemonSet operations for AKS.

Workloads are read and mutated through ``AppsV1Api``.  Like Deployments, the
grid reads from the ``AzureResourceInventory`` table, which background
``aks_resource_sync`` jobs refresh from the live cluster.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any, Literal

import structlog
import yaml
from kubernetes import client as k8s_client
from kubernetes.client.rest import ApiException

from app.services.data_cache_service import TTL, CacheKeys, data_cache

logger = structlog.get_logger(__name__)

WorkloadKind = Literal["statefulset", "daemonset"]

KIND_LABEL: dict[str, str] = {"statefulset": "StatefulSet", "daemonset": "DaemonSet"}
_API_SUFFIX: dict[str, str] = {"statefulset": "stateful_set", "daemonset": "daemon_set"}


# ── Pure helpers ──────────────────────────────────────────────────────


def _iso(ts: Any) -> str | None:
    if not ts:
        return None
    return ts.isoformat() if hasattr(ts, "isoformat") else str(ts)


def _int_or_str(value: str) -> int | str:
    return int(value) if value.isdigit() else value


def _label_selector(match_labels: dict[str, str]) -> str | None:
    return ",".join(f"{k}={v}" for k, v in match_labels.items()) or None


def workload_status(
    desired: int,
    ready: int,
    updated: int,
    expected_updated: int,
    generation: int | None,
    observed_generation: int | None,
) -> str:
    """Single display status for a StatefulSet or DaemonSet."""
    if desired == 0:
        return "Idle"
    if ready == 0:
        return "Unavailable"
    if generation is not None and observed_generation is not None and observed_generation < generation:
        return "Updating"
    if updated < expected_updated:
        return "Updating"
    if ready < desired:
        return "Degraded"
    return "Healthy"


def serialize_workload(kind: str, obj: Any) -> dict[str, Any]:
    """Grid/detail fields shared by StatefulSets and DaemonSets plus kind-specific extras."""
    meta = obj.metadata
    spec = obj.spec
    status = obj.status
    pod_spec = spec.template.spec if spec.template else None
    containers = (pod_spec.containers if pod_spec else None) or []
    first = containers[0] if containers else None
    resources = first.resources if first else None
    requests = dict(resources.requests) if resources and resources.requests else {}
    limits = dict(resources.limits) if resources and resources.limits else {}
    strategy = spec.update_strategy
    strategy_type = strategy.type if strategy else None
    rolling = strategy.rolling_update if strategy else None
    max_unavailable = getattr(rolling, "max_unavailable", None) if rolling else None

    item: dict[str, Any] = {
        "kind": KIND_LABEL[kind],
        "name": meta.name,
        "namespace": meta.namespace,
        "uid": meta.uid,
        "labels": dict(meta.labels or {}),
        "selector": dict(spec.selector.match_labels or {}) if spec.selector else {},
        "images": [c.image for c in containers],
        "containers": [{"name": c.name, "image": c.image} for c in containers],
        "created_at": _iso(meta.creation_timestamp),
        "generation": meta.generation,
        "observed_generation": status.observed_generation,
        "update_strategy": strategy_type,
        "max_unavailable": str(max_unavailable) if max_unavailable is not None else None,
        "min_ready_seconds": spec.min_ready_seconds or 0,
        "node_selector": dict(pod_spec.node_selector or {}) if pod_spec else {},
        "service_account": pod_spec.service_account_name if pod_spec else None,
        "cpu_request": requests.get("cpu", ""),
        "cpu_limit": limits.get("cpu", ""),
        "memory_request": requests.get("memory", ""),
        "memory_limit": limits.get("memory", ""),
        "conditions": [
            {
                "type": c.type,
                "status": c.status,
                "reason": c.reason,
                "message": c.message,
                "last_transition_time": _iso(c.last_transition_time),
            }
            for c in (status.conditions or [])
        ],
    }

    if kind == "statefulset":
        desired = spec.replicas if spec.replicas is not None else 1
        current_rev = status.current_revision
        update_rev = status.update_revision
        updated = status.updated_replicas or 0
        if current_rev and current_rev == update_rev:
            # Every pod is on the update revision once the two converge.
            updated = max(updated, status.replicas or 0)
        partition = (rolling.partition or 0) if rolling else 0
        expected_updated = 0 if strategy_type == "OnDelete" else max(desired - partition, 0)
        retention = getattr(spec, "persistent_volume_claim_retention_policy", None)
        item.update(
            {
                "desired": desired,
                "ready": status.ready_replicas or 0,
                "updated": updated,
                "available": status.available_replicas or 0,
                "current": status.current_replicas or 0,
                "service_name": spec.service_name,
                "pod_management_policy": spec.pod_management_policy,
                "partition": partition,
                "current_revision": current_rev,
                "update_revision": update_rev,
                "volume_claim_templates": [
                    {
                        "name": t.metadata.name,
                        "storage_class": t.spec.storage_class_name,
                        "access_modes": list(t.spec.access_modes or []),
                        "storage": (
                            dict(t.spec.resources.requests).get("storage")
                            if t.spec.resources and t.spec.resources.requests
                            else None
                        ),
                    }
                    for t in (spec.volume_claim_templates or [])
                ],
                "pvc_retention_policy": (
                    {"when_deleted": retention.when_deleted, "when_scaled": retention.when_scaled}
                    if retention
                    else None
                ),
            }
        )
    else:
        desired = status.desired_number_scheduled or 0
        max_surge = getattr(rolling, "max_surge", None) if rolling else None
        expected_updated = 0 if strategy_type == "OnDelete" else desired
        item.update(
            {
                "desired": desired,
                "ready": status.number_ready or 0,
                "updated": status.updated_number_scheduled or 0,
                "available": status.number_available or 0,
                "current": status.current_number_scheduled or 0,
                "unavailable": status.number_unavailable or 0,
                "misscheduled": status.number_misscheduled or 0,
                "max_surge": str(max_surge) if max_surge is not None else None,
                "tolerations": len(pod_spec.tolerations or []) if pod_spec else 0,
            }
        )

    item["status"] = workload_status(
        item["desired"],
        item["ready"],
        item["updated"],
        expected_updated,
        meta.generation,
        status.observed_generation,
    )
    item["update_pending"] = item["updated"] < item["desired"]
    return item


def pod_status_reason(pod: Any) -> str:
    """The pod's display status, derived the way ``kubectl get pods`` derives its STATUS column."""
    status = pod.status
    if getattr(pod.metadata, "deletion_timestamp", None):
        return "Terminating"
    init_specs = {c.name: c for c in (getattr(pod.spec, "init_containers", None) or [])}
    for i, cs in enumerate(getattr(status, "init_container_statuses", None) or []):
        state = cs.state
        if state and state.terminated and state.terminated.exit_code == 0:
            continue
        # Sidecar init containers (restartPolicy: Always) keep running alongside the app.
        sidecar = getattr(init_specs.get(cs.name), "restart_policy", None) == "Always"
        if sidecar and state and state.running and getattr(cs, "started", False):
            continue
        if state and state.terminated:
            term = state.terminated
            return f"Init:{term.reason or f'ExitCode:{term.exit_code}'}"
        if state and state.waiting and state.waiting.reason and state.waiting.reason != "PodInitializing":
            return f"Init:{state.waiting.reason}"
        return f"Init:{i}/{len(init_specs)}"

    reason = getattr(status, "reason", None) or status.phase or "Unknown"
    running = False
    # Like kubectl, walk containers in reverse so the first container's state wins.
    for cs in reversed(status.container_statuses or []):
        state = cs.state
        if not state:
            continue
        if state.waiting and state.waiting.reason:
            reason = state.waiting.reason
        elif state.terminated:
            term = state.terminated
            reason = term.reason or (f"Signal:{term.signal}" if term.signal else f"ExitCode:{term.exit_code}")
        elif state.running and cs.ready:
            running = True
    if reason == "Completed" and running:
        reason = "Running"
    return reason


def serialize_pod(pod: Any) -> dict[str, Any]:
    statuses = pod.status.container_statuses or []
    labels = pod.metadata.labels or {}
    return {
        "pod_name": pod.metadata.name,
        "namespace": pod.metadata.namespace,
        "phase": pod.status.phase,
        "status": pod_status_reason(pod),
        "ready": bool(statuses) and all(cs.ready for cs in statuses),
        "node": pod.spec.node_name,
        "pod_ip": pod.status.pod_ip,
        "started_at": _iso(pod.status.start_time),
        "restarts": sum(cs.restart_count or 0 for cs in statuses),
        "containers": [cs.name for cs in statuses] or [c.name for c in (pod.spec.containers or [])],
        # StatefulSet/DaemonSet pods carry controller-revision-hash; Deployment pods carry pod-template-hash.
        "revision": labels.get("controller-revision-hash") or labels.get("pod-template-hash"),
    }


def _owned_by(obj_meta: Any, owner_uid: str | None) -> bool:
    if not owner_uid:
        return True
    return any(ref.uid == owner_uid for ref in (obj_meta.owner_references or []))


def _revision_images(data: Any) -> list[str]:
    try:
        containers = data["spec"]["template"]["spec"]["containers"]
        return [str(c.get("image")) for c in containers if isinstance(c, dict)]
    except (KeyError, TypeError):
        return []


def _event_time(event: Any) -> Any:
    return event.last_timestamp or event.event_time or event.first_timestamp


def serialize_event(event: Any) -> dict[str, Any]:
    involved = getattr(event, "involved_object", None)
    return {
        "type": event.type,
        "reason": event.reason,
        "message": event.message,
        "count": event.count or 1,
        "last_seen": _iso(_event_time(event)),
        "object": f"{involved.kind}/{involved.name}" if involved else None,
    }


def newest_events(events: list[dict[str, Any]], limit: int = 50) -> list[dict[str, Any]]:
    return sorted(events, key=lambda e: e["last_seen"] or "", reverse=True)[:limit]


# ── Service mixin ─────────────────────────────────────────────────────


class AKSWorkloadOperationsMixin:
    """StatefulSet / DaemonSet management."""

    @staticmethod
    def _apps_call(apps_v1: Any, kind: str, template: str) -> Any:
        return getattr(apps_v1, template.format(_API_SUFFIX[kind]))

    @staticmethod
    def _manifest_yaml(apps_v1: Any, obj: Any) -> str:
        try:
            api_client = getattr(apps_v1, "api_client", None) or k8s_client.ApiClient()
            data = api_client.sanitize_for_serialization(obj)
            data.get("metadata", {}).pop("managedFields", None)
            return yaml.safe_dump(data, sort_keys=False, default_flow_style=False)
        except Exception as exc:
            logger.warning("workload_manifest_render_failed", error=str(exc))
            return ""

    # ── Workloads: read ────────────────────────────────────────────────

    async def list_workloads(
        self,
        kind: str,
        cluster_id: str,
        namespace: str | None = None,
        bypass_cache: bool = False,
    ) -> list[dict[str, Any]]:
        if not bypass_cache:
            cached, _tier = await data_cache.get_or_fetch(
                key=CacheKeys.workloads(kind, cluster_id, namespace),
                ttl=TTL.WORKLOADS,
                fetch_fn=lambda: self._fetch_workloads_live(kind, cluster_id, namespace),
            )
            return cached
        return await self._fetch_workloads_live(kind, cluster_id, namespace)

    async def _fetch_workloads_live(
        self,
        kind: str,
        cluster_id: str,
        namespace: str | None = None,
    ) -> list[dict[str, Any]]:
        apps_v1, _, _ = await self._get_k8s_clients(cluster_id)  # type: ignore[attr-defined]
        try:
            if namespace:
                result = await asyncio.to_thread(self._apps_call(apps_v1, kind, "list_namespaced_{}"), namespace)
            else:
                result = await asyncio.wait_for(
                    asyncio.to_thread(self._apps_call(apps_v1, kind, "list_{}_for_all_namespaces")),
                    timeout=45.0,
                )
        except ApiException as e:
            logger.error("list_workloads_failed", kind=kind, cluster_id=cluster_id, error=str(e))
            raise
        return [serialize_workload(kind, item) for item in result.items]

    async def get_workload_detail(
        self,
        kind: str,
        cluster_id: str,
        namespace: str,
        name: str,
    ) -> dict[str, Any]:
        apps_v1, core_v1, _ = await self._get_k8s_clients(cluster_id)  # type: ignore[attr-defined]
        obj = await asyncio.to_thread(self._apps_call(apps_v1, kind, "read_namespaced_{}"), name, namespace)
        detail = serialize_workload(kind, obj)
        detail["annotations"] = dict(obj.metadata.annotations or {})
        selector = _label_selector(detail["selector"])
        uid = obj.metadata.uid

        pods, revisions, events = await asyncio.gather(
            self._workload_pods(core_v1, namespace, selector, uid),
            self._workload_revisions(apps_v1, namespace, selector, uid),
            self._workload_events(core_v1, namespace, KIND_LABEL[kind], name),
        )
        current_name = detail.get("update_revision")
        top = max((r["revision"] for r in revisions), default=None)
        for rev in revisions:
            rev["is_current"] = rev["name"] == current_name if current_name else rev["revision"] == top
        detail["pods"] = pods
        detail["revisions"] = revisions
        detail["events"] = events
        if kind == "statefulset":
            detail["pvcs"] = await self._statefulset_pvcs(core_v1, namespace, name, detail["volume_claim_templates"])
        detail["yaml"] = self._manifest_yaml(apps_v1, obj)
        return detail

    async def _workload_pods(self, core_v1: Any, namespace: str, selector: str | None, uid: str) -> list[dict]:
        try:
            pod_list = await asyncio.to_thread(core_v1.list_namespaced_pod, namespace, label_selector=selector)
        except ApiException as e:
            logger.warning("workload_pods_failed", namespace=namespace, error=str(e))
            return []
        return [serialize_pod(p) for p in pod_list.items if _owned_by(p.metadata, uid)]

    async def _workload_revisions(self, apps_v1: Any, namespace: str, selector: str | None, uid: str) -> list[dict]:
        try:
            rev_list = await asyncio.to_thread(
                apps_v1.list_namespaced_controller_revision, namespace, label_selector=selector
            )
        except ApiException as e:
            logger.warning("workload_revisions_failed", namespace=namespace, error=str(e))
            return []
        revisions = [
            {
                "name": r.metadata.name,
                "revision": r.revision,
                "created_at": _iso(r.metadata.creation_timestamp),
                "images": _revision_images(r.data),
            }
            for r in rev_list.items
            if _owned_by(r.metadata, uid)
        ]
        return sorted(revisions, key=lambda r: r["revision"], reverse=True)

    async def _workload_events(self, core_v1: Any, namespace: str, kind_label: str, name: str) -> list[dict]:
        try:
            ev_list = await asyncio.to_thread(
                core_v1.list_namespaced_event,
                namespace,
                field_selector=f"involvedObject.kind={kind_label},involvedObject.name={name}",
            )
        except ApiException as e:
            logger.warning("workload_events_failed", namespace=namespace, error=str(e))
            return []
        return newest_events([serialize_event(ev) for ev in ev_list.items])

    async def _statefulset_pvcs(
        self, core_v1: Any, namespace: str, name: str, templates: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        if not templates:
            return []
        try:
            pvc_list = await asyncio.to_thread(core_v1.list_namespaced_persistent_volume_claim, namespace)
        except ApiException as e:
            logger.warning("statefulset_pvcs_failed", namespace=namespace, error=str(e))
            return []
        prefixes = [f"{t['name']}-{name}-" for t in templates]
        pvcs = []
        for pvc in pvc_list.items:
            pvc_name = pvc.metadata.name
            prefix = next((p for p in prefixes if pvc_name.startswith(p)), None)
            if not prefix or not pvc_name[len(prefix) :].isdigit():
                continue
            capacity = dict(pvc.status.capacity or {}) if pvc.status else {}
            pvcs.append(
                {
                    "name": pvc_name,
                    "template": prefix[: -len(name) - 2],
                    "ordinal": int(pvc_name[len(prefix) :]),
                    "phase": pvc.status.phase if pvc.status else None,
                    "capacity": capacity.get("storage"),
                    "storage_class": pvc.spec.storage_class_name,
                    "access_modes": list(pvc.spec.access_modes or []),
                    "volume_name": pvc.spec.volume_name,
                    "created_at": _iso(pvc.metadata.creation_timestamp),
                }
            )
        return sorted(pvcs, key=lambda p: (p["template"], p["ordinal"]))

    # ── Workloads: mutations ───────────────────────────────────────────

    async def _read_workload(self, apps_v1: Any, kind: str, namespace: str, name: str) -> Any:
        return await asyncio.to_thread(self._apps_call(apps_v1, kind, "read_namespaced_{}"), name, namespace)

    async def _patch_workload(self, apps_v1: Any, kind: str, namespace: str, name: str, body: Any) -> None:
        await asyncio.to_thread(self._apps_call(apps_v1, kind, "patch_namespaced_{}"), name, namespace, body)

    async def scale_statefulset(
        self,
        cluster_id: str,
        namespace: str,
        name: str,
        replicas: int,
    ) -> dict[str, Any]:
        apps_v1, _, _ = await self._get_k8s_clients(cluster_id)  # type: ignore[attr-defined]
        current = await self._read_workload(apps_v1, "statefulset", namespace, name)
        previous = current.spec.replicas
        await asyncio.to_thread(
            apps_v1.patch_namespaced_stateful_set_scale, name, namespace, {"spec": {"replicas": replicas}}
        )
        await self._after_workload_change("statefulset", cluster_id, namespace)
        logger.info("statefulset_scaled", namespace=namespace, name=name, previous=previous, new=replicas)
        return {
            "success": True,
            "name": name,
            "namespace": namespace,
            "previous_replicas": previous,
            "new_replicas": replicas,
        }

    async def restart_workload(self, kind: str, cluster_id: str, namespace: str, name: str) -> dict[str, Any]:
        apps_v1, _, _ = await self._get_k8s_clients(cluster_id)  # type: ignore[attr-defined]
        now = datetime.now(UTC).isoformat()
        body = {"spec": {"template": {"metadata": {"annotations": {"kubectl.kubernetes.io/restartedAt": now}}}}}
        await self._patch_workload(apps_v1, kind, namespace, name, body)
        await self._after_workload_change(kind, cluster_id, namespace)
        logger.info("workload_restarted", kind=kind, namespace=namespace, name=name)
        return {"success": True, "name": name, "namespace": namespace, "restarted_at": now}

    async def update_workload_image(
        self,
        kind: str,
        cluster_id: str,
        namespace: str,
        name: str,
        container: str,
        image: str,
    ) -> dict[str, Any]:
        apps_v1, _, _ = await self._get_k8s_clients(cluster_id)  # type: ignore[attr-defined]
        current = await self._read_workload(apps_v1, kind, namespace, name)
        existing = {c.name: c.image for c in (current.spec.template.spec.containers or [])}
        if container not in existing:
            raise ValueError(f"Container '{container}' does not exist in {KIND_LABEL[kind]} '{name}'.")
        body = {"spec": {"template": {"spec": {"containers": [{"name": container, "image": image}]}}}}
        await self._patch_workload(apps_v1, kind, namespace, name, body)
        await self._after_workload_change(kind, cluster_id, namespace)
        logger.info("workload_image_updated", kind=kind, namespace=namespace, name=name, container=container)
        return {
            "success": True,
            "name": name,
            "namespace": namespace,
            "container": container,
            "previous_image": existing[container],
            "new_image": image,
        }

    async def update_workload_strategy(
        self,
        kind: str,
        cluster_id: str,
        namespace: str,
        name: str,
        strategy_type: str,
        partition: int | None = None,
        max_unavailable: str | None = None,
        max_surge: str | None = None,
    ) -> dict[str, Any]:
        apps_v1, _, _ = await self._get_k8s_clients(cluster_id)  # type: ignore[attr-defined]
        current = await self._read_workload(apps_v1, kind, namespace, name)
        previous = current.spec.update_strategy.type if current.spec.update_strategy else None

        strategy: dict[str, Any]
        if strategy_type == "OnDelete":
            strategy = {"type": "OnDelete", "rollingUpdate": None}
        else:
            rolling: dict[str, Any] = {}
            if kind == "statefulset" and partition is not None:
                rolling["partition"] = partition
            if kind == "daemonset":
                if max_unavailable is not None:
                    rolling["maxUnavailable"] = _int_or_str(max_unavailable)
                if max_surge is not None:
                    rolling["maxSurge"] = _int_or_str(max_surge)
            strategy = {"type": "RollingUpdate"}
            if rolling:
                strategy["rollingUpdate"] = rolling

        await self._patch_workload(apps_v1, kind, namespace, name, {"spec": {"updateStrategy": strategy}})
        await self._after_workload_change(kind, cluster_id, namespace)
        logger.info("workload_strategy_updated", kind=kind, namespace=namespace, name=name, strategy=strategy_type)
        return {
            "success": True,
            "name": name,
            "namespace": namespace,
            "previous_strategy": previous,
            "strategy": strategy,
        }

    async def rollback_workload(
        self,
        kind: str,
        cluster_id: str,
        namespace: str,
        name: str,
        revision: int,
    ) -> dict[str, Any]:
        """Equivalent of ``kubectl rollout undo --to-revision``: re-apply a ControllerRevision's template."""
        apps_v1, _, _ = await self._get_k8s_clients(cluster_id)  # type: ignore[attr-defined]
        current = await self._read_workload(apps_v1, kind, namespace, name)
        selector = _label_selector(dict(current.spec.selector.match_labels or {}) if current.spec.selector else {})
        rev_list = await asyncio.to_thread(
            apps_v1.list_namespaced_controller_revision, namespace, label_selector=selector
        )
        owned = [r for r in rev_list.items if _owned_by(r.metadata, current.metadata.uid)]
        target = next((r for r in owned if r.revision == revision), None)
        if target is None:
            raise LookupError(f"Revision {revision} was not found for {KIND_LABEL[kind]} '{name}'.")
        latest = max(r.revision for r in owned)
        if revision == latest:
            raise ValueError(f"{KIND_LABEL[kind]} '{name}' is already at revision {revision}.")
        await self._patch_workload(apps_v1, kind, namespace, name, target.data)
        await self._after_workload_change(kind, cluster_id, namespace)
        logger.info("workload_rolled_back", kind=kind, namespace=namespace, name=name, revision=revision)
        return {
            "success": True,
            "name": name,
            "namespace": namespace,
            "from_revision": latest,
            "to_revision": revision,
            "images": _revision_images(target.data),
        }

    async def delete_workload(
        self,
        kind: str,
        cluster_id: str,
        namespace: str,
        name: str,
        propagation_policy: str = "Background",
    ) -> dict[str, Any]:
        apps_v1, _, _ = await self._get_k8s_clients(cluster_id)  # type: ignore[attr-defined]
        current = await self._read_workload(apps_v1, kind, namespace, name)
        previous_status = serialize_workload(kind, current)["status"]
        await asyncio.to_thread(
            self._apps_call(apps_v1, kind, "delete_namespaced_{}"),
            name=name,
            namespace=namespace,
            propagation_policy=propagation_policy,
        )
        await self._delete_inventory_item(cluster_id, kind, namespace, name)  # type: ignore[attr-defined]
        await data_cache.invalidate_for_workloads(cluster_id)
        logger.info("workload_deleted", kind=kind, namespace=namespace, name=name, policy=propagation_policy)
        return {
            "success": True,
            "name": name,
            "namespace": namespace,
            "previous_status": previous_status,
            "propagation_policy": propagation_policy,
        }

    # ── Workloads: DB inventory (same pattern as Deployments) ──────────

    async def sync_workloads_to_db(self, kind: str, cluster_id: str, namespace: str | None = None) -> dict[str, Any]:
        items = await self._fetch_workloads_live(kind, cluster_id, namespace)
        result = await self._sync_inventory(  # type: ignore[attr-defined]
            cluster_id, f"aks_{kind}", kind, items, namespace
        )
        result.pop("resources", None)
        return result

    async def get_workloads_from_db(
        self, kind: str, cluster_id: str, namespace: str | None = None
    ) -> list[dict[str, Any]]:
        return await self._get_inventory_from_db(  # type: ignore[attr-defined, no-any-return]
            cluster_id, f"aks_{kind}", kind, namespace
        )

    async def get_workloads_last_sync_time(self, kind: str, cluster_id: str) -> str | None:
        return await self._get_inventory_last_sync_time(  # type: ignore[attr-defined, no-any-return]
            cluster_id, f"aks_{kind}", kind
        )

    async def _after_workload_change(self, kind: str, cluster_id: str, namespace: str) -> None:
        await data_cache.invalidate_for_workloads(cluster_id)
        # The grid reads the DB inventory, so refresh the namespace now rather than waiting for the next sync.
        try:
            await self.sync_workloads_to_db(kind, cluster_id, namespace)
        except Exception as exc:
            logger.warning("workload_inventory_refresh_failed", kind=kind, namespace=namespace, error=str(exc))
