"""akv2k8s (``AzureKeyVaultSecret``, short name ``akvs``) sync status: Azure Key Vault → AKS.

Each AzureKeyVaultSecret names one Key Vault object and the Kubernetes Secret or
ConfigMap the akv2k8s controller writes it to.  Sync status is derived from the
object's ``status`` block (``lastAzureUpdate``/``secretName``), the controller's
events (``Synced`` / ``ErrAzureVault`` ...), and whether the output object holds
the expected key.  Like the other AKS resources, results are stored in the
``AzureResourceInventory`` table and refreshed by ``aks_resource_sync`` jobs.

Secret values are never returned — only key names and metadata.
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any

import structlog
from kubernetes import client as k8s_client
from kubernetes.client.rest import ApiException

from app.services.data_cache_service import TTL, CacheKeys, data_cache

logger = structlog.get_logger(__name__)

AKVS_GROUP = "spv.no"
AKVS_PLURAL = "azurekeyvaultsecrets"
AKVS_KIND = "AzureKeyVaultSecret"
AKVS_CRD = f"{AKVS_PLURAL}.{AKVS_GROUP}"
# Newest first; the first version the API server serves is used.
AKVS_VERSIONS = ("v2beta1", "v1", "v2alpha1", "v1alpha1")
CONTROLLER_SELECTOR = "app.kubernetes.io/name=akv2k8s"
INVENTORY_TYPE = "aks_akvs"
INVENTORY_SEGMENT = "akvs"

AKVS_STATUSES = ("Synced", "Failed", "Degraded", "Pending", "EnvInjector")

# Values below come from cluster objects and end up in a Key Vault URL that
# carries the portal's vault bearer token — validate before use.
_VAULT_NAME_RE = re.compile(r"^[a-zA-Z0-9-]{3,24}$")
_VAULT_OBJECT_RE = re.compile(r"^[0-9a-zA-Z-]{1,127}$")
_VAULT_PATHS = {
    "secret": "secrets",
    "multi-key-value-secret": "secrets",
    "certificate": "certificates",
    "key": "keys",
}
_VAULT_MAX_PAGES = 10


# ── Pure helpers ──────────────────────────────────────────────────────


def _iso(ts: Any) -> str | None:
    if not ts:
        return None
    return ts.isoformat() if hasattr(ts, "isoformat") else str(ts)


def _parse_ts(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _event_time(event: Any) -> Any:
    return event.last_timestamp or event.event_time or event.first_timestamp


def serialize_event(event: Any) -> dict[str, Any]:
    return {
        "type": event.type,
        "reason": event.reason,
        "message": event.message,
        "count": event.count or 1,
        "last_seen": _iso(_event_time(event)),
    }


def latest_events_by_object(events: Iterable[Any]) -> dict[tuple[str, str], dict[str, Any]]:
    """Most recent controller event per (namespace, AzureKeyVaultSecret name)."""
    latest: dict[tuple[str, str], dict[str, Any]] = {}
    for ev in events:
        involved = ev.involved_object
        if not involved or involved.kind != AKVS_KIND:
            continue
        key = (involved.namespace or ev.metadata.namespace or "", involved.name or "")
        row = serialize_event(ev)
        current = latest.get(key)
        if current is None or (row["last_seen"] or "") > (current["last_seen"] or ""):
            latest[key] = row
    return latest


def serialize_akvs(
    obj: dict[str, Any],
    last_event: dict[str, Any] | None,
    output_keys: dict[tuple[str, str, str], set[str]],
) -> dict[str, Any]:
    """One grid/detail record for an AzureKeyVaultSecret.

    ``output_keys`` maps (kind, namespace, name) of existing output Secrets and
    ConfigMaps to their data key names.
    """
    meta = obj.get("metadata") or {}
    spec = obj.get("spec") or {}
    status = obj.get("status") or {}
    vault = spec.get("vault") or {}
    vault_object = vault.get("object") or {}
    output = spec.get("output") or {}
    namespace = meta.get("namespace", "")

    out_secret = output.get("secret") or {}
    out_configmap = output.get("configMap") or {}
    if out_secret.get("name"):
        output_kind, output_spec = "secret", out_secret
    elif out_configmap.get("name"):
        output_kind, output_spec = "configmap", out_configmap
    else:
        output_kind, output_spec = "env-injection", {}
    output_name = output_spec.get("name")
    data_key = output_spec.get("dataKey")

    last_azure_update = status.get("lastAzureUpdate")
    synced_name = status.get("secretName") or status.get("configMapName")
    present_keys = output_keys.get((output_kind, namespace, output_name or "")) if output_name else None
    output_exists = None if output_kind == "env-injection" else present_keys is not None
    key_present = None if not data_key or present_keys is None else data_key in present_keys

    synced_at = _parse_ts(last_azure_update)
    event_at = _parse_ts(last_event.get("last_seen")) if last_event else None
    failing = bool(
        last_event
        and last_event.get("type") == "Warning"
        and (synced_at is None or (event_at and event_at >= synced_at))
    )

    if failing:
        state, reason = "Failed", (last_event or {}).get("message") or "The akv2k8s controller reported an error."
    elif output_kind == "env-injection":
        state, reason = "EnvInjector", "No output object: the env-injector reads this secret directly into pods."
    elif not last_azure_update or not synced_name:
        state, reason = "Pending", "The controller has not synced this object from Key Vault yet."
    elif not output_exists:
        state, reason = "Degraded", f"Output {output_kind} '{output_name}' does not exist."
    elif key_present is False:
        state, reason = "Degraded", f"Key '{data_key}' is missing from {output_kind} '{output_name}'."
    else:
        state, reason = "Synced", "Key Vault object is synced to Kubernetes."

    transforms = output.get("transform") or output.get("transforms") or []
    return {
        "name": meta.get("name", ""),
        "namespace": namespace,
        "vault_name": vault.get("name"),
        "object_name": vault_object.get("name"),
        "object_type": vault_object.get("type") or "secret",
        "object_version": vault_object.get("version") or None,
        "content_type": vault_object.get("contentType") or None,
        "output_kind": output_kind,
        "output_name": output_name,
        "output_data_key": data_key,
        "output_type": output_spec.get("type") or None,
        "transforms": list(transforms),
        "output_exists": output_exists,
        "key_present": key_present,
        "secret_hash": status.get("secretHash") or status.get("configMapHash"),
        "last_azure_update": last_azure_update,
        "last_event": last_event,
        "labels": dict(meta.get("labels") or {}),
        "created_at": meta.get("creationTimestamp"),
        "status": state,
        "status_reason": reason,
    }


def summarize_akvs(items: list[dict[str, Any]]) -> dict[str, int]:
    summary = {"total": len(items), **dict.fromkeys(AKVS_STATUSES, 0)}
    for item in items:
        summary[item["status"]] = summary.get(item["status"], 0) + 1
    summary["vaults"] = len({i["vault_name"] for i in items if i.get("vault_name")})
    summary["outputs"] = len(
        {(i["namespace"], i["output_kind"], i["output_name"]) for i in items if i.get("output_name")}
    )
    return summary


def evaluate_vault_drift(last_azure_update: str | None, latest_version_created: str | None) -> bool | None:
    """True when the controller synced at/after Key Vault's newest version; None when unknown."""
    synced = _parse_ts(last_azure_update)
    created = _parse_ts(latest_version_created)
    if synced is None or created is None:
        return None
    return synced >= created


# ── Service mixin ─────────────────────────────────────────────────────


class AKSAkvsOperationsMixin:
    """akv2k8s AzureKeyVaultSecret inventory and sync status."""

    async def _akvs_clients(self, cluster_id: str) -> tuple[Any, Any]:
        _, core_v1, _ = await self._get_k8s_clients(cluster_id)  # type: ignore[attr-defined]
        return core_v1, k8s_client.CustomObjectsApi(core_v1.api_client)

    async def _list_akvs(self, custom: Any, namespace: str | None) -> list[dict[str, Any]] | None:
        """List AzureKeyVaultSecrets with the first served API version; None when the CRD is absent."""
        for version in AKVS_VERSIONS:
            try:
                if namespace:
                    body = await asyncio.to_thread(
                        custom.list_namespaced_custom_object, AKVS_GROUP, version, namespace, AKVS_PLURAL
                    )
                else:
                    body = await asyncio.wait_for(
                        asyncio.to_thread(custom.list_cluster_custom_object, AKVS_GROUP, version, AKVS_PLURAL),
                        timeout=60.0,
                    )
                return list(body.get("items") or [])
            except ApiException as e:
                if e.status == 404:
                    continue
                raise
        return None

    async def _read_akvs(self, custom: Any, namespace: str, name: str) -> dict[str, Any]:
        last_error: ApiException | None = None
        for version in AKVS_VERSIONS:
            try:
                return await asyncio.to_thread(  # type: ignore[no-any-return]
                    custom.get_namespaced_custom_object, AKVS_GROUP, version, namespace, AKVS_PLURAL, name
                )
            except ApiException as e:
                if e.status != 404:
                    raise
                last_error = e
        raise LookupError(f"AzureKeyVaultSecret '{name}' was not found in namespace '{namespace}'.") from last_error

    async def _akvs_events(self, core_v1: Any, namespace: str | None, name: str | None = None) -> list[Any]:
        selector = f"involvedObject.kind={AKVS_KIND}"
        if name:
            selector += f",involvedObject.name={name}"
        try:
            if namespace:
                result = await asyncio.to_thread(core_v1.list_namespaced_event, namespace, field_selector=selector)
            else:
                result = await asyncio.to_thread(core_v1.list_event_for_all_namespaces, field_selector=selector)
            return list(result.items)
        except ApiException as e:
            logger.warning("akvs_event_list_failed", status=e.status, error=str(e))
            return []

    async def _akvs_output_keys(
        self, core_v1: Any, objects: list[dict[str, Any]]
    ) -> dict[tuple[str, str, str], set[str]]:
        """Data key names of the Secrets/ConfigMaps the objects write to; missing outputs are omitted."""
        wanted: set[tuple[str, str, str]] = set()
        for obj in objects:
            output = (obj.get("spec") or {}).get("output") or {}
            ns = (obj.get("metadata") or {}).get("namespace", "")
            if (output.get("secret") or {}).get("name"):
                wanted.add(("secret", ns, output["secret"]["name"]))
            elif (output.get("configMap") or {}).get("name"):
                wanted.add(("configmap", ns, output["configMap"]["name"]))

        # Read only the referenced outputs — listing every Secret in a namespace pulls large Helm release blobs.
        semaphore = asyncio.Semaphore(16)

        async def _read(key: tuple[str, str, str]) -> tuple[tuple[str, str, str], set[str] | None]:
            kind, ns, name = key
            fn = core_v1.read_namespaced_secret if kind == "secret" else core_v1.read_namespaced_config_map
            async with semaphore:
                try:
                    item = await asyncio.to_thread(fn, name, ns)
                except ApiException as e:
                    if e.status != 404:
                        logger.warning("akvs_output_read_failed", kind=kind, namespace=ns, status=e.status)
                    return key, None
            return key, set((item.data or {}).keys())

        results = await asyncio.gather(*(_read(key) for key in wanted))
        return {key: keys for key, keys in results if keys is not None}

    async def _fetch_akvs_live(self, cluster_id: str, namespace: str | None = None) -> dict[str, Any]:
        core_v1, custom = await self._akvs_clients(cluster_id)
        objects = await self._list_akvs(custom, namespace)
        if objects is None:
            return {"installed": False, "items": []}
        events, output_keys = await asyncio.gather(
            self._akvs_events(core_v1, namespace),
            self._akvs_output_keys(core_v1, objects),
        )
        latest = latest_events_by_object(events)
        items = [
            serialize_akvs(
                obj,
                latest.get(
                    ((obj.get("metadata") or {}).get("namespace", ""), (obj.get("metadata") or {}).get("name", ""))
                ),
                output_keys,
            )
            for obj in objects
        ]
        return {"installed": True, "items": items}

    # ── DB inventory ───────────────────────────────────────────────────

    async def sync_akvs_to_db(self, cluster_id: str, namespace: str | None = None) -> dict[str, Any]:
        live = await self._fetch_akvs_live(cluster_id, namespace)
        result = await self._sync_inventory(  # type: ignore[attr-defined]
            cluster_id, INVENTORY_TYPE, INVENTORY_SEGMENT, live["items"], namespace
        )
        result.pop("resources", None)
        result["installed"] = live["installed"]
        result["summary"] = summarize_akvs(live["items"])
        return result  # type: ignore[no-any-return]

    async def get_akvs_from_db(self, cluster_id: str, namespace: str | None = None) -> list[dict[str, Any]]:
        return await self._get_inventory_from_db(  # type: ignore[attr-defined, no-any-return]
            cluster_id, INVENTORY_TYPE, INVENTORY_SEGMENT, namespace
        )

    async def get_akvs_last_sync_time(self, cluster_id: str) -> str | None:
        return await self._get_inventory_last_sync_time(  # type: ignore[attr-defined, no-any-return]
            cluster_id, INVENTORY_TYPE, INVENTORY_SEGMENT
        )

    # ── Controller & detail ────────────────────────────────────────────

    async def get_akvs_controller_status(self, cluster_id: str) -> dict[str, Any]:
        cached, _tier = await data_cache.get_or_fetch(
            key=CacheKeys.akv_sync(cluster_id),
            ttl=TTL.AKV_SYNC,
            fetch_fn=lambda: self._fetch_akvs_controller_live(cluster_id),
        )
        return cached  # type: ignore[no-any-return]

    async def _fetch_akvs_controller_live(self, cluster_id: str) -> dict[str, Any]:
        core_v1, _ = await self._akvs_clients(cluster_id)
        ext = k8s_client.ApiextensionsV1Api(core_v1.api_client)
        installed: bool | None
        versions: list[str] = []
        try:
            crd = await asyncio.to_thread(ext.read_custom_resource_definition, AKVS_CRD)
            installed = True
            versions = [v.name for v in crd.spec.versions if v.served]
        except ApiException as e:
            installed = False if e.status == 404 else None
            if e.status != 404:
                logger.warning("akvs_crd_read_failed", status=e.status)

        components: dict[str, dict[str, Any]] = {}
        try:
            pods = await asyncio.to_thread(core_v1.list_pod_for_all_namespaces, label_selector=CONTROLLER_SELECTOR)
            for pod in pods.items:
                labels = pod.metadata.labels or {}
                name = pod.metadata.name
                component = labels.get("app.kubernetes.io/component") or (
                    "env-injector" if "envinjector" in name or "env-injector" in name else "controller"
                )
                component = component.rsplit("akv2k8s-", 1)[-1]
                statuses = pod.status.container_statuses or []
                entry = components.setdefault(
                    component,
                    {
                        "component": component,
                        "namespace": pod.metadata.namespace,
                        "pods": 0,
                        "ready": 0,
                        "image": (pod.spec.containers[0].image if pod.spec.containers else None),
                    },
                )
                entry["pods"] += 1
                if pod.status.phase == "Running" and statuses and all(cs.ready for cs in statuses):
                    entry["ready"] += 1
        except ApiException as e:
            logger.warning("akvs_controller_pods_failed", status=e.status)

        return {"installed": installed, "versions": versions, "components": list(components.values())}

    async def get_akvs_detail(
        self,
        cluster_id: str,
        namespace: str,
        name: str,
        check_vault: bool = False,
    ) -> dict[str, Any]:
        core_v1, custom = await self._akvs_clients(cluster_id)
        obj = await self._read_akvs(custom, namespace, name)
        events, output_keys = await asyncio.gather(
            self._akvs_events(core_v1, namespace, name),
            self._akvs_output_keys(core_v1, [obj]),
        )
        event_rows = sorted((serialize_event(e) for e in events), key=lambda e: e["last_seen"] or "", reverse=True)
        item = serialize_akvs(obj, event_rows[0] if event_rows else None, output_keys)
        item["events"] = event_rows[:30]
        present = output_keys.get((item["output_kind"], namespace, item["output_name"] or ""))
        item["output_keys"] = sorted(present) if present is not None else []
        if check_vault:
            item["vault_check"] = await self._check_akvs_vault(item)
        return item

    async def delete_akvs(
        self, cluster_id: str, namespace: str, name: str, keep_output: bool = False
    ) -> dict[str, Any]:
        """Delete an AzureKeyVaultSecret.

        akv2k8s sets the AzureKeyVaultSecret as controller owner of the Secret or
        ConfigMap it writes, so Kubernetes garbage-collects that output with it
        unless ``keep_output`` orphans it.
        """
        _, custom = await self._akvs_clients(cluster_id)
        obj = await self._read_akvs(custom, namespace, name)
        version = str(obj.get("apiVersion") or "").rpartition("/")[2] or AKVS_VERSIONS[0]
        item = serialize_akvs(obj, None, {})
        await asyncio.to_thread(
            custom.delete_namespaced_custom_object,
            AKVS_GROUP,
            version,
            namespace,
            AKVS_PLURAL,
            name,
            propagation_policy="Orphan" if keep_output else "Background",
        )
        await self._delete_inventory_item(cluster_id, INVENTORY_SEGMENT, namespace, name)  # type: ignore[attr-defined]
        logger.info("akvs_deleted", namespace=namespace, name=name, keep_output=keep_output)
        return {
            "success": True,
            "name": name,
            "namespace": namespace,
            "vault_name": item["vault_name"],
            "object_name": item["object_name"],
            "output_kind": item["output_kind"],
            "output_name": item["output_name"],
            "output_kept": keep_output,
        }

    async def _check_akvs_vault(self, item: dict[str, Any]) -> dict[str, Any]:
        """Compare the newest Key Vault version with the controller's last sync time (no values are read)."""
        checked_at = datetime.now(UTC).isoformat()
        vault = item.get("vault_name") or ""
        object_name = item.get("object_name") or ""
        path = _VAULT_PATHS.get(item.get("object_type") or "secret")
        if not _VAULT_NAME_RE.match(vault) or not _VAULT_OBJECT_RE.match(object_name) or not path:
            return {"checked": False, "checked_at": checked_at, "error": "Unsupported vault, object name, or type."}

        from app.services.keyvault_service import KeyVaultService

        kv = KeyVaultService()
        vault_uri = f"https://{vault.lower()}.vault.azure.net/"
        url: str | None = f"{vault_uri}{path}/{object_name}/versions?api-version=7.4&maxresults=25"
        latest: dict[str, Any] | None = None
        pages = 0
        try:
            token = await kv._get_vault_token()
            while url and pages < _VAULT_MAX_PAGES:
                body = await kv._vault_get(url, token=token)
                for version in body.get("value") or []:
                    attrs = version.get("attributes") or {}
                    if attrs.get("enabled") is False:
                        continue
                    created = int(attrs.get("created") or 0)
                    if latest is None or created > latest["created"]:
                        latest = {
                            "version": str(version.get("id", "")).rstrip("/").rsplit("/", 1)[-1],
                            "created": created,
                            "expires": attrs.get("exp"),
                        }
                next_link = body.get("nextLink")
                url = next_link if next_link and next_link.startswith(vault_uri) else None
                pages += 1
        except Exception as exc:
            logger.warning("akvs_vault_check_failed", vault=vault, error=str(exc)[:200])
            return {"checked": False, "checked_at": checked_at, "error": str(exc)[:300]}

        if latest is None:
            return {"checked": True, "checked_at": checked_at, "error": "No enabled versions found in Key Vault."}

        created_iso = datetime.fromtimestamp(latest["created"], tz=UTC).isoformat()
        pinned = item.get("object_version")
        return {
            "checked": True,
            "checked_at": checked_at,
            "vault_uri": vault_uri,
            "latest_version": latest["version"],
            "latest_version_created": created_iso,
            "latest_version_expires": (
                datetime.fromtimestamp(latest["expires"], tz=UTC).isoformat() if latest["expires"] else None
            ),
            "pinned_version": pinned,
            "in_sync": None if pinned else evaluate_vault_drift(item.get("last_azure_update"), created_iso),
        }
