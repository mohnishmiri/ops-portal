"""Helm release management for AKS clusters."""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import subprocess
import tempfile
from typing import Any

import structlog
import yaml

logger = structlog.get_logger(__name__)

HELM_TIMEOUT = 120


class AKSHelmService:
    """Run Helm CLI against AKS clusters using ephemeral kubeconfig."""

    def __init__(self, aks_service: Any) -> None:
        self._aks = aks_service

    async def _kubeconfig_path(self, cluster_id: str) -> str:
        _, core_v1, _ = await self._aks._get_k8s_clients(cluster_id)
        config = core_v1.api_client.configuration
        kube_dict = {
            "apiVersion": "v1",
            "kind": "Config",
            "clusters": [{"name": "aks", "cluster": {"server": config.host, "insecure-skip-tls-verify": True}}],
            "contexts": [{"name": "aks", "context": {"cluster": "aks", "user": "aks"}}],
            "current-context": "aks",
            "users": [
                {
                    "name": "aks",
                    "user": {"token": config.api_key.get("authorization", "").replace("Bearer ", "")},
                }
            ],
        }
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as tmp:
            yaml.safe_dump(kube_dict, tmp)
            return tmp.name

    async def _run_helm(self, cluster_id: str, args: list[str]) -> dict[str, Any]:
        kubeconfig = await self._kubeconfig_path(cluster_id)
        env = {**os.environ, "KUBECONFIG": kubeconfig}
        cmd = ["helm", *args]
        try:
            proc = await asyncio.to_thread(
                subprocess.run,
                cmd,
                capture_output=True,
                text=True,
                timeout=HELM_TIMEOUT,
                env=env,
            )
            if proc.returncode != 0:
                return {"success": False, "error": proc.stderr.strip() or proc.stdout.strip()}
            if proc.stdout.strip():
                try:
                    return {"success": True, "data": json.loads(proc.stdout)}
                except json.JSONDecodeError:
                    return {"success": True, "output": proc.stdout.strip()}
            return {"success": True}
        finally:
            with contextlib.suppress(OSError):
                os.unlink(kubeconfig)

    async def list_releases(self, cluster_id: str, namespace: str | None = None) -> list[dict[str, Any]]:
        """List Helm releases — tries CLI first, falls back to K8s API secrets."""
        try:
            return await self._list_releases_cli(cluster_id, namespace)
        except FileNotFoundError:
            logger.info("helm_cli_not_found_using_k8s_api_fallback")
            return await self._list_releases_from_secrets(cluster_id, namespace)

    async def _list_releases_cli(self, cluster_id: str, namespace: str | None = None) -> list[dict[str, Any]]:
        kubeconfig = await self._kubeconfig_path(cluster_id)
        try:
            env = {**os.environ, "KUBECONFIG": kubeconfig}
            cmd = ["helm", "list", "-o", "json"]
            if namespace:
                cmd.extend(["-n", namespace])
            else:
                cmd.append("-A")
            proc = await asyncio.to_thread(
                subprocess.run, cmd, capture_output=True, text=True, timeout=HELM_TIMEOUT, env=env
            )
            if proc.returncode != 0:
                logger.warning("helm_list_failed", error=proc.stderr[:200])
                return []
            data = json.loads(proc.stdout or "[]")
            return data if isinstance(data, list) else []
        finally:
            with contextlib.suppress(OSError):
                os.unlink(kubeconfig)

    async def _list_releases_from_secrets(self, cluster_id: str, namespace: str | None = None) -> list[dict[str, Any]]:
        """Read Helm releases directly from Kubernetes secrets (owner=helm label)."""
        import base64
        import gzip

        _, core_v1, _ = await self._aks._get_k8s_clients(cluster_id)
        try:
            if namespace:
                secrets = await asyncio.to_thread(
                    core_v1.list_namespaced_secret,
                    namespace,
                    label_selector="owner=helm",
                )
            else:
                secrets = await asyncio.to_thread(
                    core_v1.list_secret_for_all_namespaces,
                    label_selector="owner=helm",
                )

            # Group by release name — pick latest revision per release
            releases_map: dict[str, dict[str, Any]] = {}
            for secret in secrets.items:
                labels = secret.metadata.labels or {}
                name = labels.get("name", "")
                status = labels.get("status", "unknown")
                version_str = labels.get("version", "0")

                key = f"{secret.metadata.namespace}/{name}"
                existing = releases_map.get(key)
                revision = int(version_str) if version_str.isdigit() else 0

                if existing and existing.get("_revision", 0) >= revision:
                    continue

                # Try to extract chart info from the release data
                chart_name = ""
                app_version = ""
                try:
                    raw = secret.data.get("release", "")
                    if raw:
                        decoded = base64.b64decode(base64.b64decode(raw))
                        release_data = json.loads(gzip.decompress(decoded))
                        chart_meta = release_data.get("chart", {}).get("metadata", {})
                        chart_name = f"{chart_meta.get('name', '')}-{chart_meta.get('version', '')}"
                        app_version = chart_meta.get("appVersion", "")
                except Exception:
                    chart_name = labels.get("name", "")

                releases_map[key] = {
                    "name": name,
                    "namespace": secret.metadata.namespace,
                    "revision": str(revision),
                    "status": status.replace("_", " ").title() if status else "Unknown",
                    "chart": chart_name,
                    "app_version": app_version,
                    "updated": (
                        secret.metadata.creation_timestamp.isoformat() if secret.metadata.creation_timestamp else ""
                    ),
                    "_revision": revision,
                }

            # Remove internal _revision field
            result = []
            for r in releases_map.values():
                r.pop("_revision", None)
                result.append(r)
            return sorted(result, key=lambda x: x.get("name", ""))
        except Exception as e:
            logger.warning("helm_list_from_secrets_failed", error=str(e))
            return []

    async def install_release(
        self,
        cluster_id: str,
        release_name: str,
        chart: str,
        namespace: str,
        *,
        version: str | None = None,
        values_yaml: str | None = None,
        create_namespace: bool = False,
    ) -> dict[str, Any]:
        args = ["install", release_name, chart, "-n", namespace]
        if create_namespace:
            args.append("--create-namespace")
        if version:
            args.extend(["--version", version])
        values_path: str | None = None
        if values_yaml:
            with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as tmp:
                tmp.write(values_yaml)
                values_path = tmp.name
            args.extend(["-f", values_path])
        try:
            return await self._run_helm(cluster_id, args)
        finally:
            if values_path:
                with contextlib.suppress(OSError):
                    os.unlink(values_path)

    async def upgrade_release(
        self,
        cluster_id: str,
        release_name: str,
        chart: str,
        namespace: str,
        *,
        version: str | None = None,
        values_yaml: str | None = None,
    ) -> dict[str, Any]:
        args = ["upgrade", release_name, chart, "-n", namespace]
        if version:
            args.extend(["--version", version])
        values_path: str | None = None
        if values_yaml:
            with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as tmp:
                tmp.write(values_yaml)
                values_path = tmp.name
            args.extend(["-f", values_path])
        try:
            return await self._run_helm(cluster_id, args)
        finally:
            if values_path:
                with contextlib.suppress(OSError):
                    os.unlink(values_path)

    async def uninstall_release(self, cluster_id: str, release_name: str, namespace: str) -> dict[str, Any]:
        return await self._run_helm(cluster_id, ["uninstall", release_name, "-n", namespace])

    async def rollback_release(
        self, cluster_id: str, release_name: str, namespace: str, revision: int
    ) -> dict[str, Any]:
        return await self._run_helm(cluster_id, ["rollback", release_name, str(revision), "-n", namespace])
