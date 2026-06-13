"""
AKS Live Sync Hub — WebSocket fan-out with Azure polling and workload sync.

Clusters and node pools are polled via Azure SDK (ARM resources).
In-cluster workloads are synced on interval when subscribed (reliable vs raw watch).
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import structlog
from fastapi import WebSocket, WebSocketDisconnect

from app.core.database import get_db_session
from app.models.auth import UserContext
from app.services.aks_operations_service import get_aks_operations_service

logger = structlog.get_logger(__name__)

POLL_INTERVAL_SECONDS = 60


@dataclass
class LiveSubscription:
    cluster_id: str | None
    namespace: str | None
    resources: set[str]


@dataclass
class ConnectedClient:
    websocket: WebSocket
    user: UserContext
    subscription: LiveSubscription | None = None


def _fingerprint(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, default=str)


class AKSLiveSyncHub:
    """In-process live sync hub (one instance per uvicorn worker)."""

    def __init__(self) -> None:
        self._clients: dict[str, ConnectedClient] = {}
        self._poll_tasks: dict[str, asyncio.Task] = {}
        self._watch_tasks: dict[str, asyncio.Task] = {}
        self._client_counter = 0
        self._cluster_fingerprints: dict[str, str] = {}
        self._nodepool_fingerprints: dict[str, dict[str, str]] = {}
        self._workload_fingerprints: dict[str, dict[str, str]] = {}

    async def handle_client(self, websocket: WebSocket, user: UserContext) -> None:
        await websocket.accept()
        self._client_counter += 1
        client_id = f"aks-{self._client_counter}"
        self._clients[client_id] = ConnectedClient(websocket=websocket, user=user)
        try:
            await websocket.send_json({"type": "connected", "client_id": client_id})
            while True:
                raw = await websocket.receive_text()
                msg = json.loads(raw)
                if msg.get("type") != "subscribe":
                    continue
                sub = LiveSubscription(
                    cluster_id=msg.get("cluster_id"),
                    namespace=msg.get("namespace"),
                    resources={str(r) for r in (msg.get("resources") or [])},
                )
                self._clients[client_id].subscription = sub
                await self._ensure_tasks(sub)
                await websocket.send_json(
                    {
                        "type": "subscribed",
                        "resources": sorted(sub.resources),
                        "cluster_id": sub.cluster_id,
                        "namespace": sub.namespace,
                    }
                )
        except WebSocketDisconnect:
            pass
        except Exception as exc:
            logger.warning("aks_live_ws_client_error", error=str(exc))
        finally:
            self._clients.pop(client_id, None)
            await self._cleanup_idle_tasks()

    async def _ensure_tasks(self, sub: LiveSubscription) -> None:
        if "clusters" in sub.resources:
            key = "azure:clusters"
            if key not in self._poll_tasks or self._poll_tasks[key].done():
                self._poll_tasks[key] = asyncio.create_task(self._poll_clusters_loop())
        if "nodepools" in sub.resources and sub.cluster_id:
            key = f"azure:nodepools:{sub.cluster_id}"
            if key not in self._poll_tasks or self._poll_tasks[key].done():
                self._poll_tasks[key] = asyncio.create_task(self._poll_nodepools_loop(sub.cluster_id))
        if sub.cluster_id:
            for resource in sub.resources:
                if resource in {
                    "deployments",
                    "pods",
                    "services",
                    "secrets",
                    "configmaps",
                    "ingress",
                    "cronjobs",
                }:
                    ns = sub.namespace or ""
                    key = f"k8s:{resource}:{sub.cluster_id}:{ns}"
                    if key not in self._watch_tasks or self._watch_tasks[key].done():
                        self._watch_tasks[key] = asyncio.create_task(
                            self._sync_k8s_resource_loop(sub.cluster_id, ns, resource)
                        )

    async def _cleanup_idle_tasks(self) -> None:
        wanted_poll: set[str] = set()
        wanted_watch: set[str] = set()
        for client in self._clients.values():
            sub = client.subscription
            if not sub:
                continue
            if "clusters" in sub.resources:
                wanted_poll.add("azure:clusters")
            if "nodepools" in sub.resources and sub.cluster_id:
                wanted_poll.add(f"azure:nodepools:{sub.cluster_id}")
            if sub.cluster_id:
                for resource in sub.resources:
                    if resource in {
                        "deployments",
                        "pods",
                        "services",
                        "secrets",
                        "configmaps",
                        "ingress",
                        "cronjobs",
                    }:
                        ns = sub.namespace or ""
                        wanted_watch.add(f"k8s:{resource}:{sub.cluster_id}:{ns}")

        for key, task in list(self._poll_tasks.items()):
            if key not in wanted_poll:
                task.cancel()
                self._poll_tasks.pop(key, None)
        for key, task in list(self._watch_tasks.items()):
            if key not in wanted_watch:
                task.cancel()
                self._watch_tasks.pop(key, None)

    def _any_subscriber_wants(self, resource: str, cluster_id: str | None = None) -> bool:
        for client in self._clients.values():
            sub = client.subscription
            if not sub or resource not in sub.resources:
                continue
            if cluster_id and sub.cluster_id and sub.cluster_id != cluster_id:
                continue
            return True
        return False

    def _matches(self, sub: LiveSubscription | None, event: dict[str, Any]) -> bool:
        if sub is None:
            return False
        rt = event.get("resource_type")
        if rt not in sub.resources:
            return False
        if rt == "clusters":
            return True
        event_cluster = event.get("cluster_id")
        if sub.cluster_id and event_cluster and sub.cluster_id != event_cluster:
            return False
        event_ns = event.get("namespace")
        return not (sub.namespace and event_ns and sub.namespace != event_ns)

    async def _broadcast(self, event: dict[str, Any]) -> None:
        dead: list[str] = []
        for cid, client in self._clients.items():
            if not self._matches(client.subscription, event):
                continue
            try:
                await client.websocket.send_json(event)
            except Exception:
                dead.append(cid)
        for cid in dead:
            self._clients.pop(cid, None)

    async def _poll_clusters_loop(self) -> None:
        while self._any_subscriber_wants("clusters"):
            try:
                async for db in get_db_session():
                    svc = get_aks_operations_service(db)
                    result = await svc.sync_clusters_to_db()
                    for cluster in result.get("resources") or []:
                        cid = cluster.get("id", "")
                        fp = _fingerprint(cluster)
                        prev = self._cluster_fingerprints.get(cid)
                        if prev == fp:
                            continue
                        self._cluster_fingerprints[cid] = fp
                        await self._broadcast(
                            {
                                "type": "live_event",
                                "resource_type": "clusters",
                                "event_type": "ADDED" if prev is None else "MODIFIED",
                                "cluster_id": cid,
                                "name": cluster.get("name"),
                                "summary": f"Cluster {cluster.get('name')} synced",
                                "timestamp": datetime.now(UTC).isoformat(),
                            }
                        )
                    break
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("aks_cluster_poll_failed", error=str(exc))
            await asyncio.sleep(POLL_INTERVAL_SECONDS)
        self._poll_tasks.pop("azure:clusters", None)

    async def _poll_nodepools_loop(self, cluster_id: str) -> None:
        if cluster_id not in self._nodepool_fingerprints:
            self._nodepool_fingerprints[cluster_id] = {}
        while self._any_subscriber_wants("nodepools", cluster_id):
            try:
                async for db in get_db_session():
                    svc = get_aks_operations_service(db)
                    result = await svc.sync_node_pools_to_db(cluster_id)
                    prev_map = self._nodepool_fingerprints[cluster_id]
                    for pool in result.get("resources") or []:
                        name = pool.get("name", "")
                        fp = _fingerprint(pool)
                        prev = prev_map.get(name)
                        if prev == fp:
                            continue
                        prev_map[name] = fp
                        await self._broadcast(
                            {
                                "type": "live_event",
                                "resource_type": "nodepools",
                                "event_type": "ADDED" if prev is None else "MODIFIED",
                                "cluster_id": cluster_id,
                                "name": name,
                                "summary": f"Node pool {name} synced",
                                "timestamp": datetime.now(UTC).isoformat(),
                            }
                        )
                    break
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("aks_nodepool_poll_failed", cluster_id=cluster_id, error=str(exc))
            await asyncio.sleep(POLL_INTERVAL_SECONDS)
        self._poll_tasks.pop(f"azure:nodepools:{cluster_id}", None)

    async def _sync_k8s_resource_loop(self, cluster_id: str, namespace: str, resource: str) -> None:
        fp_store_key = f"{cluster_id}:{namespace}:{resource}"
        if fp_store_key not in self._workload_fingerprints:
            self._workload_fingerprints[fp_store_key] = {}

        sync_map = {
            "deployments": "sync_deployments_to_db",
            "cronjobs": "sync_cronjobs_to_db",
            "services": "sync_services_to_db",
            "secrets": "sync_secrets_to_db",
            "configmaps": "sync_configmaps_to_db",
            "ingress": "sync_ingress_to_db",
            "pods": "sync_pods_to_db",
        }
        sync_method = sync_map.get(resource)
        if not sync_method:
            return

        while self._any_subscriber_wants(resource, cluster_id):
            try:
                async for db in get_db_session():
                    svc = get_aks_operations_service(db)
                    sync_fn = getattr(svc, sync_method, None)
                    if sync_fn is None:
                        await asyncio.sleep(POLL_INTERVAL_SECONDS * 2)
                        break
                    ns_arg = namespace or None
                    result = await sync_fn(cluster_id, ns_arg)
                    prev_map = self._workload_fingerprints[fp_store_key]
                    for item in result.get("resources") or []:
                        name = item.get("name", "")
                        ns = item.get("namespace", namespace)
                        item_key = f"{ns}/{name}"
                        fp = _fingerprint(item)
                        prev = prev_map.get(item_key)
                        if prev == fp:
                            continue
                        prev_map[item_key] = fp
                        await self._broadcast(
                            {
                                "type": "live_event",
                                "resource_type": resource,
                                "event_type": "ADDED" if prev is None else "MODIFIED",
                                "cluster_id": cluster_id,
                                "namespace": ns,
                                "name": name,
                                "summary": f"{resource.rstrip('s')} {name} synced",
                                "timestamp": datetime.now(UTC).isoformat(),
                            }
                        )
                    break
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning(
                    "aks_k8s_resource_poll_failed",
                    cluster_id=cluster_id,
                    resource=resource,
                    error=str(exc),
                )
            await asyncio.sleep(POLL_INTERVAL_SECONDS)
        watch_key = f"k8s:{resource}:{cluster_id}:{namespace}"
        self._watch_tasks.pop(watch_key, None)


aks_live_sync_hub = AKSLiveSyncHub()
