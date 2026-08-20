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

    async def _delete_inventory_item(self, cluster_id: str, id_segment: str, namespace: str, name: str) -> None:
        """Remove a single resource from the DB inventory after K8s deletion."""
        if not self.db:
            return
        resource_id = f"{cluster_id}/{id_segment}/{namespace}/{name}"
        try:
            await self.db.execute(
                delete(AzureResourceInventory).where(
                    AzureResourceInventory.resource_id == resource_id,
                )
            )
            await self.db.commit()
        except Exception as exc:
            logger.warning("delete_inventory_item_failed", resource_id=resource_id, error=str(exc)[:200])
            await self.db.rollback()

    async def list_namespaces_for_cluster(self, cluster_id: str) -> list[str]:
        """List all namespaces from the K8s cluster, falling back to synced inventory."""
        # Try fetching live from K8s first for the full list
        try:
            _, core_v1, _ = await self._get_k8s_clients(cluster_id)
            resp = await asyncio.to_thread(core_v1.list_namespace)
            return sorted(ns.metadata.name for ns in resp.items if ns.metadata and ns.metadata.name)
        except Exception as exc:
            logger.warning("list_namespaces_live_failed", cluster_id=cluster_id[:80], error=str(exc)[:200])

        # Fallback: aggregate from synced inventory
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
            resp = await asyncio.to_thread(core_v1.list_namespaced_secret, namespace)
            secrets = resp.items
        else:
            resp = await asyncio.to_thread(core_v1.list_secret_for_all_namespaces)
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
        return await self._fetch_secrets_live(cluster_id, namespace)

    async def get_secret_detail(self, cluster_id: str, namespace: str, name: str, *, reveal: bool = False) -> dict:
        _, core_v1, _ = await self._get_k8s_clients(cluster_id)
        sec = await asyncio.to_thread(core_v1.read_namespaced_secret, name, namespace)
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
        }

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
        existing = await asyncio.to_thread(core_v1.read_namespaced_secret, name, namespace)
        existing.string_data = data
        await asyncio.to_thread(core_v1.replace_namespaced_secret, name, namespace, existing)
        await data_cache.invalidate_for_secrets(cluster_id)
        return {"success": True, "name": name, "namespace": namespace}

    async def delete_secret(self, cluster_id: str, namespace: str, name: str) -> dict[str, Any]:
        _, core_v1, _ = await self._get_k8s_clients(cluster_id)
        await asyncio.to_thread(core_v1.delete_namespaced_secret, name, namespace)
        await self._delete_inventory_item(cluster_id, "secret", namespace, name)
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
            resp = await asyncio.to_thread(core_v1.list_namespaced_service, namespace)
            svcs = resp.items
        else:
            resp = await asyncio.to_thread(core_v1.list_service_for_all_namespaces)
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
        return await self._fetch_services_live(cluster_id, namespace)

    async def get_service_detail(self, cluster_id: str, namespace: str, name: str) -> dict[str, Any]:
        _, core_v1, _ = await self._get_k8s_clients(cluster_id)
        svc = await asyncio.to_thread(core_v1.read_namespaced_service, name, namespace)
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
        }

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

    async def update_service(
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
        await asyncio.to_thread(core_v1.replace_namespaced_service, name, namespace, body)
        await data_cache.invalidate_for_services(cluster_id)
        return {"success": True, "name": name, "namespace": namespace}

    async def delete_service(self, cluster_id: str, namespace: str, name: str) -> dict[str, Any]:
        _, core_v1, _ = await self._get_k8s_clients(cluster_id)
        await asyncio.to_thread(core_v1.delete_namespaced_service, name, namespace)
        await self._delete_inventory_item(cluster_id, "service", namespace, name)
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
            resp = await asyncio.to_thread(core_v1.list_namespaced_config_map, namespace)
            cms = resp.items
        else:
            resp = await asyncio.to_thread(core_v1.list_config_map_for_all_namespaces)
            cms = resp.items
        return [
            {
                "name": cm.metadata.name,
                "namespace": cm.metadata.namespace,
                "data_keys": list(cm.data.keys()) if cm.data else [],
                "created_at": (cm.metadata.creation_timestamp.isoformat() if cm.metadata.creation_timestamp else None),
                "labels": dict(cm.metadata.labels) if cm.metadata.labels else {},
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
        await self._delete_inventory_item(cluster_id, "configmap", namespace, name)
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
            resp = await asyncio.to_thread(net_v1.list_namespaced_ingress, namespace)
            ing_list = resp.items
        else:
            resp = await asyncio.to_thread(net_v1.list_ingress_for_all_namespaces)
            ing_list = resp.items
        items = []
        for ing in ing_list:
            hosts: list[str] = []
            services: list[str] = []
            for rule in ing.spec.rules or []:
                if rule.host:
                    hosts.append(rule.host)
                for path in rule.http.paths if rule.http else []:
                    svc_name = path.backend.service.name if path.backend and path.backend.service else None
                    if svc_name:
                        services.append(svc_name)
            tls_secrets = [t.secret_name for t in ing.spec.tls or [] if t.secret_name]
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
                    "tls_secrets": tls_secrets,
                    "address": address,
                    "created_at": (
                        ing.metadata.creation_timestamp.isoformat() if ing.metadata.creation_timestamp else None
                    ),
                }
            )
        return items

    async def get_ingress_detail(self, cluster_id: str, namespace: str, name: str) -> dict[str, Any]:
        net_v1 = await self._get_networking_client(cluster_id)
        ing = await asyncio.to_thread(net_v1.read_namespaced_ingress, name, namespace)
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
        }

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

    async def update_ingress(
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
        await asyncio.to_thread(net_v1.replace_namespaced_ingress, name, namespace, body)
        await data_cache.invalidate_for_ingress(cluster_id)
        return {"success": True, "name": name, "namespace": namespace}

    async def delete_ingress(self, cluster_id: str, namespace: str, name: str) -> dict[str, Any]:
        net_v1 = await self._get_networking_client(cluster_id)
        await asyncio.to_thread(net_v1.delete_namespaced_ingress, name, namespace)
        await self._delete_inventory_item(cluster_id, "ingress", namespace, name)
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

    async def _fetch_pods_inventory_live(self, cluster_id: str, namespace: str | None) -> list[dict[str, Any]]:
        _, core_v1, _ = await self._get_k8s_clients(cluster_id)
        if namespace:
            resp = await asyncio.to_thread(core_v1.list_namespaced_pod, namespace)
            pods = resp.items
        else:
            resp = await asyncio.wait_for(
                asyncio.to_thread(core_v1.list_pod_for_all_namespaces),
                timeout=60.0,
            )
            pods = resp.items
        items = []
        for pod in pods:
            restarts = 0
            if pod.status and pod.status.container_statuses:
                restarts = sum(cs.restart_count for cs in pod.status.container_statuses)
            items.append(
                {
                    "name": pod.metadata.name,
                    "namespace": pod.metadata.namespace,
                    "phase": pod.status.phase if pod.status else "Unknown",
                    "node": pod.spec.node_name,
                    "restarts": restarts,
                    "created_at": (
                        pod.metadata.creation_timestamp.isoformat() if pod.metadata.creation_timestamp else None
                    ),
                }
            )
        return items

    async def sync_pods_to_db(self, cluster_id: str, namespace: str | None = None) -> dict[str, Any]:
        items = await self._fetch_pods_inventory_live(cluster_id, namespace)
        return await self._sync_inventory(cluster_id, "aks_pod", "pod", items, namespace)

    async def get_pods_from_db(self, cluster_id: str, namespace: str | None = None) -> list[dict[str, Any]]:
        return await self._get_inventory_from_db(cluster_id, "aks_pod", "pod", namespace)


# Late import to avoid circular dependency at module load
from app.services.data_cache_service import data_cache  # noqa: E402
