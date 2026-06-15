"""K8s resource operations mixin for AKS — secrets, services, configmaps, ingress, pods."""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any

import structlog
from kubernetes import client as k8s_client
from sqlalchemy import delete, select
from sqlalchemy import func as sa_func

from app.models.database import AzureResourceInventory

logger = structlog.get_logger(__name__)

MASK = "***"
_K8S_CALL_TIMEOUT_SECONDS = 15


def _k8s_updated_at(metadata: Any) -> str | None:
    """Best-effort last-modified timestamp from K8s object metadata."""
    if metadata is None:
        return None
    managed = getattr(metadata, "managed_fields", None) or []
    times = [mf.time for mf in managed if getattr(mf, "time", None)]
    if times:
        return max(times).isoformat()
    created = getattr(metadata, "creation_timestamp", None)
    return created.isoformat() if created else None


class AKSResourceOperationsMixin:
    """Secrets, Services, ConfigMaps, Ingress, and Pod inventory operations."""

    _networking_clients: dict[str, k8s_client.NetworkingV1Api]

    async def _get_networking_client(self, cluster_id: str) -> k8s_client.NetworkingV1Api:
        if not hasattr(self, "_networking_clients"):
            self._networking_clients = {}
        if cluster_id not in self._networking_clients:
            _, core_v1, _ = await self._get_k8s_clients(cluster_id)
            self._networking_clients[cluster_id] = k8s_client.NetworkingV1Api(core_v1.api_client)
        return self._networking_clients[cluster_id]

    def _cluster_parts(self, cluster_id: str) -> tuple[str, str]:
        sub_id, rg = "", ""
        parts = cluster_id.split("/")
        for i, p in enumerate(parts):
            if p.lower() == "subscriptions" and i + 1 < len(parts):
                sub_id = parts[i + 1]
            if p.lower() == "resourcegroups" and i + 1 < len(parts):
                rg = parts[i + 1]
        return sub_id, rg

    async def _get_inventory_last_sync_time(
        self,
        cluster_id: str,
        resource_type: str,
        id_segment: str,
    ) -> str | None:
        if not self.db:
            return None
        try:
            query = select(sa_func.max(AzureResourceInventory.last_sync)).where(
                AzureResourceInventory.resource_type == resource_type,
                AzureResourceInventory.resource_id.like(f"{cluster_id}/{id_segment}/%"),
            )
            result = await self.db.execute(query)
            last_sync = result.scalar()
            return last_sync.isoformat() if last_sync else None
        except Exception as exc:
            logger.error(
                "get_inventory_last_sync_failed",
                cluster_id=cluster_id,
                resource_type=resource_type,
                error=str(exc),
            )
            return None

    async def _sync_inventory(
        self,
        cluster_id: str,
        resource_type: str,
        id_segment: str,
        items: list[dict[str, Any]],
        namespace: str | None = None,
    ) -> dict[str, Any]:
        if not self.db:
            return {
                "synced_count": len(items),
                "resource_type": resource_type,
                "cluster_id": cluster_id,
                "last_sync": datetime.utcnow().isoformat(),
                "resources": items,
                "db_saved": False,
            }

        sub_id, rg = self._cluster_parts(cluster_id)
        try:
            delete_query = delete(AzureResourceInventory).where(
                AzureResourceInventory.resource_type == resource_type,
                AzureResourceInventory.resource_id.like(f"{cluster_id}/{id_segment}/%"),
            )
            if namespace:
                delete_query = delete_query.where(
                    AzureResourceInventory.resource_id.like(f"{cluster_id}/{id_segment}/{namespace}/%"),
                )
            await self.db.execute(delete_query)
            for item in items:
                ns = item.get("namespace", "")
                name = item.get("name", "")
                record = AzureResourceInventory(
                    resource_id=f"{cluster_id}/{id_segment}/{ns}/{name}",
                    name=name,
                    resource_type=resource_type,
                    resource_group=rg,
                    location="",
                    subscription_id=sub_id,
                    provisioning_state=item.get("status") or item.get("type") or "Active",
                    tags={},
                    resource_details={**item, "_cluster_id": cluster_id},
                )
                self.db.add(record)
            await self.db.commit()
        except Exception as exc:
            logger.error("aks_inventory_sync_failed", resource_type=resource_type, error=str(exc))
            await self.db.rollback()
            raise

        return {
            "synced_count": len(items),
            "resource_type": resource_type,
            "cluster_id": cluster_id,
            "last_sync": datetime.utcnow().isoformat(),
            "resources": items,
            "db_saved": True,
        }

    async def _k8s_call(self, fn, *args, **kwargs):
        """Run a blocking K8s SDK call with a hard timeout."""
        return await asyncio.wait_for(asyncio.to_thread(fn, *args, **kwargs), timeout=_K8S_CALL_TIMEOUT_SECONDS)

    async def _get_inventory_record(
        self,
        cluster_id: str,
        resource_type: str,
        id_segment: str,
        namespace: str,
        name: str,
    ):
        if not self.db:
            return None
        resource_id = f"{cluster_id}/{id_segment}/{namespace}/{name}"
        query = select(AzureResourceInventory).where(
            AzureResourceInventory.resource_type == resource_type,
            AzureResourceInventory.resource_id == resource_id,
        )
        result = await self.db.execute(query)
        return result.scalars().first()

    async def _get_inventory_from_db(
        self,
        cluster_id: str,
        resource_type: str,
        id_segment: str,
        namespace: str | None = None,
    ) -> list[dict[str, Any]]:
        if not self.db:
            return []
        query = select(AzureResourceInventory).where(
            AzureResourceInventory.resource_type == resource_type,
            AzureResourceInventory.resource_id.like(f"{cluster_id}/{id_segment}/%"),
        )
        result = await self.db.execute(query)
        rows = result.scalars().all()
        items = [row.resource_details for row in rows if row.resource_details]
        if namespace:
            items = [i for i in items if i.get("namespace") == namespace]
        return items

    async def list_namespaces_for_cluster(self, cluster_id: str) -> list[str]:
        """Aggregate unique namespaces from synced inventory."""
        if not self.db:
            return []
        segments = ("deployment", "service", "secret", "configmap", "ingress", "cronjob", "pod")
        namespaces: set[str] = set()
        for seg in segments:
            query = select(AzureResourceInventory.resource_details).where(
                AzureResourceInventory.resource_id.like(f"{cluster_id}/{seg}/%"),
            )
            result = await self.db.execute(query)
            for (details,) in result.all():
                if isinstance(details, dict) and details.get("namespace"):
                    namespaces.add(details["namespace"])
        return sorted(namespaces)

    # ── Secrets ────────────────────────────────────────────────────────

    async def _fetch_secrets_live(self, cluster_id: str, namespace: str | None) -> list[dict[str, Any]]:
        _, core_v1, _ = await self._get_k8s_clients(cluster_id)
        items: list[dict[str, Any]] = []
        if namespace:
            resp = await self._k8s_call(core_v1.list_namespaced_secret, namespace)
            secrets = resp.items
        else:
            resp = await self._k8s_call(core_v1.list_secret_for_all_namespaces)
            secrets = resp.items
        for sec in secrets:
            keys = list(sec.data.keys()) if sec.data else []
            items.append(
                {
                    "name": sec.metadata.name,
                    "namespace": sec.metadata.namespace,
                    "type": sec.type,
                    "keys": keys,
                    "key_count": len(keys),
                    "created_at": (
                        sec.metadata.creation_timestamp.isoformat() if sec.metadata.creation_timestamp else None
                    ),
                    "labels": dict(sec.metadata.labels) if sec.metadata.labels else {},
                }
            )
        return items

    async def list_secrets(self, cluster_id: str, namespace: str | None = None) -> list[dict[str, Any]]:
        cached = await self.get_secrets_from_db(cluster_id, namespace)
        if cached:
            return cached
        return await self._fetch_secrets_live(cluster_id, namespace)

    async def _get_secret_detail_from_db(
        self,
        cluster_id: str,
        namespace: str,
        name: str,
        *,
        reveal: bool = False,
    ) -> dict[str, Any] | None:
        record = await self._get_inventory_record(cluster_id, "aks_secret", "secret", namespace, name)
        if record is None:
            return None

        details = dict(record.resource_details or {})
        keys = list(details.get("keys") or [])
        data: dict[str, str] = {}
        if reveal:
            stored_data = details.get("data")
            if isinstance(stored_data, dict) and stored_data:
                data = dict(stored_data)
            else:
                return None
        else:
            data = dict.fromkeys(keys, MASK)

        return {
            "name": details.get("name", name),
            "namespace": details.get("namespace", namespace),
            "type": details.get("type", "Opaque"),
            "data": data,
            "keys": keys,
            "labels": details.get("labels") if isinstance(details.get("labels"), dict) else {},
            "created_at": details.get("created_at"),
            "detail_source": "db",
            "_last_sync": record.last_sync.isoformat() if record.last_sync else None,
        }

    async def _fetch_secret_detail_live(
        self,
        cluster_id: str,
        namespace: str,
        name: str,
        *,
        reveal: bool = False,
    ) -> dict[str, Any]:
        _, core_v1, _ = await self._get_k8s_clients(cluster_id)
        sec = await self._k8s_call(core_v1.read_namespaced_secret, name, namespace)
        data: dict[str, str] = {}
        if sec.data:
            for k, v in sec.data.items():
                if reveal:
                    import base64

                    data[k] = base64.b64decode(v).decode("utf-8", errors="replace")
                else:
                    data[k] = MASK
        return {
            "name": sec.metadata.name,
            "namespace": sec.metadata.namespace,
            "type": sec.type,
            "data": data,
            "keys": list(sec.data.keys()) if sec.data else [],
            "labels": dict(sec.metadata.labels) if sec.metadata.labels else {},
            "created_at": (sec.metadata.creation_timestamp.isoformat() if sec.metadata.creation_timestamp else None),
            "detail_source": "live",
        }

    async def get_secret_detail(
        self,
        cluster_id: str,
        namespace: str,
        name: str,
        *,
        reveal: bool = False,
        bypass_cache: bool = False,
    ) -> dict:
        if not reveal:
            db_detail = await self._get_secret_detail_from_db(cluster_id, namespace, name, reveal=False)
            if db_detail is not None:
                return db_detail

        cache_key = CacheKeys.secret_detail(cluster_id, namespace, name, reveal=reveal)
        try:
            if not bypass_cache:
                cached, _tier = await data_cache.get_or_fetch(
                    key=cache_key,
                    ttl=TTL.K8S_RESOURCE_DETAIL,
                    fetch_fn=lambda: self._fetch_secret_detail_live(cluster_id, namespace, name, reveal=reveal),
                )
                return cached
            return await self._fetch_secret_detail_live(cluster_id, namespace, name, reveal=reveal)
        except Exception as exc:
            fallback = await self._get_secret_detail_from_db(cluster_id, namespace, name, reveal=False)
            if fallback is not None:
                logger.warning(
                    "secret_detail_live_failed_using_db_fallback",
                    cluster_id=cluster_id,
                    namespace=namespace,
                    name=name,
                    reveal=reveal,
                    error=str(exc),
                )
                if reveal:
                    fallback["detail_source"] = "db_masked"
                    fallback["data_unavailable_reason"] = "Live cluster unreachable; secret values not stored in cache"
                return fallback
            raise

    async def create_secret(
        self, cluster_id: str, namespace: str, name: str, data: dict[str, str], secret_type: str = "Opaque"
    ) -> dict[str, Any]:
        _, core_v1, _ = await self._get_k8s_clients(cluster_id)
        body = k8s_client.V1Secret(
            metadata=k8s_client.V1ObjectMeta(name=name, namespace=namespace),
            type=secret_type,
            string_data=data,
        )
        await asyncio.to_thread(core_v1.create_namespaced_secret, namespace, body)
        await data_cache.invalidate_for_secrets(cluster_id)
        return {"success": True, "name": name, "namespace": namespace}

    async def update_secret(self, cluster_id: str, namespace: str, name: str, data: dict[str, str]) -> dict[str, Any]:
        _, core_v1, _ = await self._get_k8s_clients(cluster_id)
        existing = await self._k8s_call(core_v1.read_namespaced_secret, name, namespace)
        existing.string_data = data
        await self._k8s_call(core_v1.replace_namespaced_secret, name, namespace, existing)
        await data_cache.invalidate_for_secrets(cluster_id)
        return {"success": True, "name": name, "namespace": namespace}

    async def delete_secret(self, cluster_id: str, namespace: str, name: str) -> dict[str, Any]:
        _, core_v1, _ = await self._get_k8s_clients(cluster_id)
        await asyncio.to_thread(core_v1.delete_namespaced_secret, name, namespace)
        await data_cache.invalidate_for_secrets(cluster_id)
        return {"success": True, "name": name, "namespace": namespace}

    async def sync_secrets_to_db(self, cluster_id: str, namespace: str | None = None) -> dict[str, Any]:
        items = await self._fetch_secrets_live(cluster_id, namespace)
        return await self._sync_inventory(cluster_id, "aks_secret", "secret", items, namespace)

    async def get_secrets_from_db(self, cluster_id: str, namespace: str | None = None) -> list[dict[str, Any]]:
        return await self._get_inventory_from_db(cluster_id, "aks_secret", "secret", namespace)

    async def get_secrets_last_sync_time(self, cluster_id: str) -> str | None:
        return await self._get_inventory_last_sync_time(cluster_id, "aks_secret", "secret")

    # ── Services ───────────────────────────────────────────────────────

    async def _fetch_services_live(self, cluster_id: str, namespace: str | None) -> list[dict[str, Any]]:
        _, core_v1, _ = await self._get_k8s_clients(cluster_id)
        if namespace:
            resp = await self._k8s_call(core_v1.list_namespaced_service, namespace)
            svcs = resp.items
        else:
            resp = await self._k8s_call(core_v1.list_service_for_all_namespaces)
            svcs = resp.items
        items = []
        for svc in svcs:
            ports = []
            for p in svc.spec.ports or []:
                ports.append({"port": p.port, "target_port": str(p.target_port), "protocol": p.protocol})
            items.append(
                {
                    "name": svc.metadata.name,
                    "namespace": svc.metadata.namespace,
                    "type": svc.spec.type,
                    "cluster_ip": svc.spec.cluster_ip,
                    "external_ip": (
                        svc.status.load_balancer.ingress[0].ip
                        if svc.status.load_balancer and svc.status.load_balancer.ingress
                        else None
                    ),
                    "ports": ports,
                    "selector": dict(svc.spec.selector) if svc.spec.selector else {},
                    "created_at": (
                        svc.metadata.creation_timestamp.isoformat() if svc.metadata.creation_timestamp else None
                    ),
                }
            )
        return items

    async def list_services(self, cluster_id: str, namespace: str | None = None) -> list[dict[str, Any]]:
        cached = await self.get_services_from_db(cluster_id, namespace)
        if cached:
            return cached
        return await self._fetch_services_live(cluster_id, namespace)

    async def _get_service_detail_from_db(
        self,
        cluster_id: str,
        namespace: str,
        name: str,
    ) -> dict[str, Any] | None:
        record = await self._get_inventory_record(cluster_id, "aks_service", "service", namespace, name)
        if record is None:
            return None

        details = dict(record.resource_details or {})
        details.pop("_cluster_id", None)
        return {
            "name": details.get("name", name),
            "namespace": details.get("namespace", namespace),
            "type": details.get("type"),
            "cluster_ip": details.get("cluster_ip"),
            "ports": list(details.get("ports") or []),
            "selector": details.get("selector") if isinstance(details.get("selector"), dict) else {},
            "labels": details.get("labels") if isinstance(details.get("labels"), dict) else {},
            "annotations": details.get("annotations") if isinstance(details.get("annotations"), dict) else {},
            "detail_source": "db",
            "_last_sync": record.last_sync.isoformat() if record.last_sync else None,
        }

    async def _fetch_service_detail_live(self, cluster_id: str, namespace: str, name: str) -> dict[str, Any]:
        _, core_v1, _ = await self._get_k8s_clients(cluster_id)
        svc = await self._k8s_call(core_v1.read_namespaced_service, name, namespace)
        ports = []
        for p in svc.spec.ports or []:
            ports.append({"port": p.port, "target_port": str(p.target_port), "protocol": p.protocol, "name": p.name})
        return {
            "name": svc.metadata.name,
            "namespace": svc.metadata.namespace,
            "type": svc.spec.type,
            "cluster_ip": svc.spec.cluster_ip,
            "ports": ports,
            "selector": dict(svc.spec.selector) if svc.spec.selector else {},
            "labels": dict(svc.metadata.labels) if svc.metadata.labels else {},
            "annotations": dict(svc.metadata.annotations) if svc.metadata.annotations else {},
            "detail_source": "live",
        }

    async def get_service_detail(
        self,
        cluster_id: str,
        namespace: str,
        name: str,
        *,
        bypass_cache: bool = False,
    ) -> dict[str, Any]:
        db_detail = await self._get_service_detail_from_db(cluster_id, namespace, name)
        if db_detail is not None and not bypass_cache:
            return db_detail

        cache_key = CacheKeys.service_detail(cluster_id, namespace, name)
        try:
            if not bypass_cache:
                cached, _tier = await data_cache.get_or_fetch(
                    key=cache_key,
                    ttl=TTL.K8S_RESOURCE_DETAIL,
                    fetch_fn=lambda: self._fetch_service_detail_live(cluster_id, namespace, name),
                )
                return cached
            return await self._fetch_service_detail_live(cluster_id, namespace, name)
        except Exception as exc:
            if db_detail is not None:
                logger.warning(
                    "service_detail_live_failed_using_db_fallback",
                    cluster_id=cluster_id,
                    namespace=namespace,
                    name=name,
                    error=str(exc),
                )
                return db_detail
            raise

    async def create_service(
        self,
        cluster_id: str,
        namespace: str,
        name: str,
        port: int,
        target_port: int | str,
        selector: dict[str, str],
        service_type: str = "ClusterIP",
    ) -> dict[str, Any]:
        _, core_v1, _ = await self._get_k8s_clients(cluster_id)
        body = k8s_client.V1Service(
            metadata=k8s_client.V1ObjectMeta(name=name, namespace=namespace),
            spec=k8s_client.V1ServiceSpec(
                type=service_type,
                selector=selector,
                ports=[k8s_client.V1ServicePort(port=port, target_port=target_port)],
            ),
        )
        await asyncio.to_thread(core_v1.create_namespaced_service, namespace, body)
        await data_cache.invalidate_for_services(cluster_id)
        return {"success": True, "name": name, "namespace": namespace}

    async def delete_service(self, cluster_id: str, namespace: str, name: str) -> dict[str, Any]:
        _, core_v1, _ = await self._get_k8s_clients(cluster_id)
        await asyncio.to_thread(core_v1.delete_namespaced_service, name, namespace)
        await data_cache.invalidate_for_services(cluster_id)
        return {"success": True, "name": name, "namespace": namespace}

    async def sync_services_to_db(self, cluster_id: str, namespace: str | None = None) -> dict[str, Any]:
        items = await self._fetch_services_live(cluster_id, namespace)
        return await self._sync_inventory(cluster_id, "aks_service", "service", items, namespace)

    async def get_services_from_db(self, cluster_id: str, namespace: str | None = None) -> list[dict[str, Any]]:
        return await self._get_inventory_from_db(cluster_id, "aks_service", "service", namespace)

    async def get_services_last_sync_time(self, cluster_id: str) -> str | None:
        return await self._get_inventory_last_sync_time(cluster_id, "aks_service", "service")

    # ── ConfigMaps (extended) ──────────────────────────────────────────

    async def _fetch_configmaps_live(self, cluster_id: str, namespace: str | None) -> list[dict[str, Any]]:
        _, core_v1, _ = await self._get_k8s_clients(cluster_id)
        if namespace:
            resp = await self._k8s_call(core_v1.list_namespaced_config_map, namespace)
            cms = resp.items
        else:
            resp = await self._k8s_call(core_v1.list_config_map_for_all_namespaces)
            cms = resp.items
        return [
            {
                "name": cm.metadata.name,
                "namespace": cm.metadata.namespace,
                "data": dict(cm.data) if cm.data else {},
                "data_keys": list(cm.data.keys()) if cm.data else [],
                "binary_data_keys": list(cm.binary_data.keys()) if cm.binary_data else [],
                "created_at": (cm.metadata.creation_timestamp.isoformat() if cm.metadata.creation_timestamp else None),
                "labels": dict(cm.metadata.labels) if cm.metadata.labels else {},
                "annotations": dict(cm.metadata.annotations) if cm.metadata.annotations else {},
            }
            for cm in cms
        ]

    async def create_configmap(
        self, cluster_id: str, namespace: str, name: str, data: dict[str, str]
    ) -> dict[str, Any]:
        _, core_v1, _ = await self._get_k8s_clients(cluster_id)
        body = k8s_client.V1ConfigMap(
            metadata=k8s_client.V1ObjectMeta(name=name, namespace=namespace),
            data=data,
        )
        await asyncio.to_thread(core_v1.create_namespaced_config_map, namespace, body)
        await data_cache.invalidate_for_configmaps(cluster_id)
        return {"success": True, "name": name, "namespace": namespace}

    async def update_configmap(
        self, cluster_id: str, namespace: str, name: str, data: dict[str, str]
    ) -> dict[str, Any]:
        _, core_v1, _ = await self._get_k8s_clients(cluster_id)
        existing = await asyncio.to_thread(core_v1.read_namespaced_config_map, name, namespace)
        existing.data = data
        await asyncio.to_thread(core_v1.replace_namespaced_config_map, name, namespace, existing)
        await data_cache.invalidate_for_configmaps(cluster_id)
        return {"success": True, "name": name, "namespace": namespace}

    async def delete_configmap(self, cluster_id: str, namespace: str, name: str) -> dict[str, Any]:
        _, core_v1, _ = await self._get_k8s_clients(cluster_id)
        await asyncio.to_thread(core_v1.delete_namespaced_config_map, name, namespace)
        await data_cache.invalidate_for_configmaps(cluster_id)
        return {"success": True, "name": name, "namespace": namespace}

    async def sync_configmaps_to_db(self, cluster_id: str, namespace: str | None = None) -> dict[str, Any]:
        items = await self._fetch_configmaps_live(cluster_id, namespace)
        return await self._sync_inventory(cluster_id, "aks_configmap", "configmap", items, namespace)

    async def get_configmaps_from_db(self, cluster_id: str, namespace: str | None = None) -> list[dict[str, Any]]:
        return await self._get_inventory_from_db(cluster_id, "aks_configmap", "configmap", namespace)

    async def get_configmaps_last_sync_time(self, cluster_id: str) -> str | None:
        return await self._get_inventory_last_sync_time(cluster_id, "aks_configmap", "configmap")

    # ── Ingress ────────────────────────────────────────────────────────

    async def _fetch_ingress_live(self, cluster_id: str, namespace: str | None) -> list[dict[str, Any]]:
        net_v1 = await self._get_networking_client(cluster_id)
        if namespace:
            resp = await self._k8s_call(net_v1.list_namespaced_ingress, namespace)
            ing_list = resp.items
        else:
            resp = await self._k8s_call(net_v1.list_ingress_for_all_namespaces)
            ing_list = resp.items
        items = []
        for ing in ing_list:
            hosts: list[str] = []
            services: list[str] = []
            rules: list[dict[str, Any]] = []
            for rule in ing.spec.rules or []:
                if rule.host:
                    hosts.append(rule.host)
                for path in rule.http.paths if rule.http else []:
                    svc_name = path.backend.service.name if path.backend and path.backend.service else None
                    if svc_name:
                        services.append(svc_name)
                    rules.append(
                        {
                            "host": rule.host,
                            "path": path.path,
                            "path_type": path.path_type,
                            "service_name": svc_name,
                            "service_port": path.backend.service.port.number
                            if path.backend and path.backend.service and path.backend.service.port
                            else None,
                        }
                    )
            tls_secrets = [t.secret_name for t in ing.spec.tls or [] if t.secret_name]
            tls_blocks = [{"hosts": t.hosts or [], "secret_name": t.secret_name} for t in ing.spec.tls or []]
            address = None
            if ing.status and ing.status.load_balancer and ing.status.load_balancer.ingress:
                lb = ing.status.load_balancer.ingress[0]
                address = lb.ip or lb.hostname
            items.append(
                {
                    "name": ing.metadata.name,
                    "namespace": ing.metadata.namespace,
                    "ingress_class": ing.spec.ingress_class_name,
                    "hosts": hosts,
                    "backend_services": sorted(set(services)),
                    "linked_services": sorted(set(services)),
                    "tls_secrets": tls_secrets,
                    "linked_secrets": tls_secrets,
                    "rules": rules,
                    "tls": tls_blocks,
                    "address": address,
                    "labels": dict(ing.metadata.labels) if ing.metadata.labels else {},
                    "annotations": dict(ing.metadata.annotations) if ing.metadata.annotations else {},
                    "created_at": (
                        ing.metadata.creation_timestamp.isoformat() if ing.metadata.creation_timestamp else None
                    ),
                    "updated": _k8s_updated_at(ing.metadata),
                }
            )
        return items

    async def _get_ingress_detail_from_db(
        self,
        cluster_id: str,
        namespace: str,
        name: str,
    ) -> dict[str, Any] | None:
        record = await self._get_inventory_record(cluster_id, "aks_ingress", "ingress", namespace, name)
        if record is None:
            return None

        details = dict(record.resource_details or {})
        details.pop("_cluster_id", None)
        linked_services = list(details.get("linked_services") or details.get("backend_services") or [])
        linked_secrets = list(details.get("linked_secrets") or details.get("tls_secrets") or [])
        return {
            "name": details.get("name", name),
            "namespace": details.get("namespace", namespace),
            "ingress_class": details.get("ingress_class"),
            "rules": list(details.get("rules") or []),
            "tls": list(details.get("tls") or []),
            "linked_services": linked_services,
            "linked_secrets": linked_secrets,
            "address": details.get("address"),
            "labels": details.get("labels") if isinstance(details.get("labels"), dict) else {},
            "annotations": details.get("annotations") if isinstance(details.get("annotations"), dict) else {},
            "detail_source": "db",
            "_last_sync": record.last_sync.isoformat() if record.last_sync else None,
        }

    async def _fetch_ingress_detail_live(self, cluster_id: str, namespace: str, name: str) -> dict[str, Any]:
        net_v1 = await self._get_networking_client(cluster_id)
        ing = await self._k8s_call(net_v1.read_namespaced_ingress, name, namespace)
        rules = []
        linked_services: list[str] = []
        for rule in ing.spec.rules or []:
            for path in rule.http.paths if rule.http else []:
                svc = path.backend.service if path.backend else None
                svc_name = svc.name if svc else None
                if svc_name:
                    linked_services.append(svc_name)
                rules.append(
                    {
                        "host": rule.host,
                        "path": path.path,
                        "path_type": path.path_type,
                        "service_name": svc_name,
                        "service_port": svc.port.number if svc and svc.port else None,
                    }
                )
        tls_blocks = [{"hosts": t.hosts or [], "secret_name": t.secret_name} for t in ing.spec.tls or []]
        linked_secrets = [t.secret_name for t in ing.spec.tls or [] if t.secret_name]
        address = None
        if ing.status and ing.status.load_balancer and ing.status.load_balancer.ingress:
            lb = ing.status.load_balancer.ingress[0]
            address = lb.ip or lb.hostname
        return {
            "name": ing.metadata.name,
            "namespace": ing.metadata.namespace,
            "ingress_class": ing.spec.ingress_class_name,
            "rules": rules,
            "tls": tls_blocks,
            "linked_services": sorted(set(linked_services)),
            "linked_secrets": linked_secrets,
            "address": address,
            "labels": dict(ing.metadata.labels) if ing.metadata.labels else {},
            "annotations": dict(ing.metadata.annotations) if ing.metadata.annotations else {},
            "detail_source": "live",
        }

    async def get_ingress_detail(
        self,
        cluster_id: str,
        namespace: str,
        name: str,
        *,
        bypass_cache: bool = False,
    ) -> dict[str, Any]:
        db_detail = await self._get_ingress_detail_from_db(cluster_id, namespace, name)
        if db_detail is not None and not bypass_cache:
            return db_detail

        cache_key = CacheKeys.ingress_detail(cluster_id, namespace, name)
        try:
            if not bypass_cache:
                cached, _tier = await data_cache.get_or_fetch(
                    key=cache_key,
                    ttl=TTL.K8S_RESOURCE_DETAIL,
                    fetch_fn=lambda: self._fetch_ingress_detail_live(cluster_id, namespace, name),
                )
                return cached
            return await self._fetch_ingress_detail_live(cluster_id, namespace, name)
        except Exception as exc:
            if db_detail is not None:
                logger.warning(
                    "ingress_detail_live_failed_using_db_fallback",
                    cluster_id=cluster_id,
                    namespace=namespace,
                    name=name,
                    error=str(exc),
                )
                return db_detail
            raise

    async def create_ingress(
        self,
        cluster_id: str,
        namespace: str,
        name: str,
        rules: list[dict[str, Any]],
        tls: list[dict[str, Any]] | None = None,
        ingress_class: str | None = None,
    ) -> dict[str, Any]:
        net_v1 = await self._get_networking_client(cluster_id)
        http_rules = []
        for rule in rules:
            paths = []
            for p in rule.get("paths", []):
                paths.append(
                    k8s_client.V1HTTPIngressPath(
                        path=p.get("path", "/"),
                        path_type=p.get("path_type", "Prefix"),
                        backend=k8s_client.V1IngressBackend(
                            service=k8s_client.V1IngressServiceBackend(
                                name=p["service_name"],
                                port=k8s_client.V1ServiceBackendPort(number=int(p["service_port"])),
                            )
                        ),
                    )
                )
            http_rules.append(
                k8s_client.V1IngressRule(host=rule.get("host"), http=k8s_client.V1HTTPIngressRuleValue(paths=paths))
            )
        tls_rules = None
        if tls:
            tls_rules = [k8s_client.V1IngressTLS(hosts=t.get("hosts"), secret_name=t.get("secret_name")) for t in tls]
        body = k8s_client.V1Ingress(
            metadata=k8s_client.V1ObjectMeta(name=name, namespace=namespace),
            spec=k8s_client.V1IngressSpec(
                ingress_class_name=ingress_class,
                rules=http_rules,
                tls=tls_rules,
            ),
        )
        await asyncio.to_thread(net_v1.create_namespaced_ingress, namespace, body)
        await data_cache.invalidate_for_ingress(cluster_id)
        return {"success": True, "name": name, "namespace": namespace}

    async def delete_ingress(self, cluster_id: str, namespace: str, name: str) -> dict[str, Any]:
        net_v1 = await self._get_networking_client(cluster_id)
        await asyncio.to_thread(net_v1.delete_namespaced_ingress, name, namespace)
        await data_cache.invalidate_for_ingress(cluster_id)
        return {"success": True, "name": name, "namespace": namespace}

    async def sync_ingress_to_db(self, cluster_id: str, namespace: str | None = None) -> dict[str, Any]:
        items = await self._fetch_ingress_live(cluster_id, namespace)
        return await self._sync_inventory(cluster_id, "aks_ingress", "ingress", items, namespace)

    async def get_ingress_from_db(self, cluster_id: str, namespace: str | None = None) -> list[dict[str, Any]]:
        return await self._get_inventory_from_db(cluster_id, "aks_ingress", "ingress", namespace)

    async def get_ingress_last_sync_time(self, cluster_id: str) -> str | None:
        return await self._get_inventory_last_sync_time(cluster_id, "aks_ingress", "ingress")

    # ── Pods inventory ─────────────────────────────────────────────────

    async def sync_pods_to_db(self, cluster_id: str, namespace: str | None = None) -> dict[str, Any]:
        """Sync full pod metrics inventory from live K8s into DB for fast cached reads."""
        metrics = await self._fetch_pod_metrics_live(cluster_id, namespace)
        items = [{**pod, "name": pod["pod_name"]} for pod in metrics]
        return await self._sync_inventory(cluster_id, "aks_pod", "pod", items, namespace)

    async def get_pods_from_db(self, cluster_id: str, namespace: str | None = None) -> list[dict[str, Any]]:
        return await self._get_inventory_from_db(cluster_id, "aks_pod", "pod", namespace)

    async def get_pod_metrics_from_db(
        self, cluster_id: str, namespace: str | None = None
    ) -> list[dict[str, Any]]:
        items = await self._get_inventory_from_db(cluster_id, "aks_pod", "pod", namespace)
        pods: list[dict[str, Any]] = []
        for item in items:
            pod = dict(item)
            pod.pop("_cluster_id", None)
            if "pod_name" not in pod and pod.get("name"):
                pod["pod_name"] = pod["name"]
            pods.append(pod)
        return pods

    async def get_pods_last_sync_time(self, cluster_id: str) -> str | None:
        return await self._get_inventory_last_sync_time(cluster_id, "aks_pod", "pod")


# Late import to avoid circular dependency at module load
from app.services.data_cache_service import (  # noqa: E402
    TTL,
    CacheKeys,
    data_cache,
)
