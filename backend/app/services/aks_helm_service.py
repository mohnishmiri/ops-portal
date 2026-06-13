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
        except FileNotFoundError:
            logger.warning("helm_cli_not_found")
            return []
        finally:
            with contextlib.suppress(OSError):
                os.unlink(kubeconfig)

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
