"""Helm release management for AKS clusters."""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import re
import subprocess
import tempfile
from typing import Any
from urllib.parse import urlparse

import structlog
import yaml

logger = structlog.get_logger(__name__)

HELM_TIMEOUT = 120

# Every value below is spliced into a subprocess argv. We never use shell=True, so
# shell metacharacters are inert, but a value starting with "-" would still be read
# by Helm as a flag — these patterns block that and keep names to what Helm accepts.
_SAFE_NAME = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]{0,252}$")
_SAFE_CHART_REF = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._\-/:+@]{0,510}$")
_ALLOWED_REPO_SCHEMES = {"http", "https", "oci"}


class HelmValidationError(ValueError):
    """Raised when a caller-supplied Helm argument fails validation."""


def _validate_name(value: str, field: str) -> str:
    """Names for releases, namespaces, and repos."""
    if not value or not _SAFE_NAME.match(value):
        raise HelmValidationError(
            f"Invalid {field}: use letters, digits, '.', '_' or '-', starting with a letter or digit."
        )
    return value


def _validate_chart_ref(value: str, field: str = "chart") -> str:
    """Chart references — 'repo/chart', 'oci://registry/chart', or a packaged name."""
    if not value or not _SAFE_CHART_REF.match(value):
        raise HelmValidationError(f"Invalid {field} reference.")
    return value


def _validate_repo_url(value: str) -> str:
    """Repository URLs are fetched by the server, so restrict the scheme."""
    parsed = urlparse(value)
    if parsed.scheme not in _ALLOWED_REPO_SCHEMES or not parsed.netloc:
        raise HelmValidationError(f"Repository URL must be an absolute {'/'.join(sorted(_ALLOWED_REPO_SCHEMES))} URL.")
    return value


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

    async def _run_helm_local(self, args: list[str]) -> dict[str, Any]:
        """Run a Helm command that needs no cluster context (repo, search, lint).

        Note: Helm keeps its repository list in the client's home directory, so
        repos added here live on whichever replica served the request. In a
        multi-replica deployment, add a repo then use it in the same session, or
        bake the repo list into the image.
        """
        cmd = ["helm", *args]
        try:
            proc = await asyncio.to_thread(subprocess.run, cmd, capture_output=True, text=True, timeout=HELM_TIMEOUT)
        except FileNotFoundError as exc:
            raise HelmValidationError(
                "The Helm CLI is not available on the server, so this operation cannot run."
            ) from exc
        if proc.returncode != 0:
            return {"success": False, "error": proc.stderr.strip() or proc.stdout.strip()}
        if proc.stdout.strip():
            try:
                return {"success": True, "data": json.loads(proc.stdout)}
            except json.JSONDecodeError:
                return {"success": True, "output": proc.stdout.strip()}
        return {"success": True}

    # ── Repositories ──────────────────────────────────────────────────

    async def repo_add(
        self,
        name: str,
        url: str,
        *,
        username: str | None = None,
        password: str | None = None,
    ) -> dict[str, Any]:
        """helm repo add — registers a chart repository with the Helm client."""
        _validate_name(name, "repository name")
        _validate_repo_url(url)
        args = ["repo", "add", name, url, "--force-update"]
        if username:
            args.extend(["--username", username])
        if password:
            args.extend(["--password", password])
        return await self._run_helm_local(args)

    async def repo_update(self, name: str | None = None) -> dict[str, Any]:
        """helm repo update — refreshes cached chart indexes."""
        args = ["repo", "update"]
        if name:
            args.append(_validate_name(name, "repository name"))
        return await self._run_helm_local(args)

    async def repo_remove(self, name: str) -> dict[str, Any]:
        """helm repo remove."""
        _validate_name(name, "repository name")
        return await self._run_helm_local(["repo", "remove", name])

    async def repo_list(self) -> list[dict[str, Any]]:
        """helm repo list — empty list when no repos are configured."""
        result = await self._run_helm_local(["repo", "list", "-o", "json"])
        if not result.get("success"):
            # Helm exits non-zero with "no repositories to show" when none exist.
            return []
        data = result.get("data")
        return data if isinstance(data, list) else []

    async def search_repo(self, keyword: str | None = None, *, versions: bool = False) -> list[dict[str, Any]]:
        """helm search repo — searches the client's configured repositories."""
        args = ["search", "repo"]
        if keyword:
            # A bare keyword must not be read as a flag.
            args.append(_validate_chart_ref(keyword, "search keyword"))
        if versions:
            args.append("--versions")
        args.extend(["-o", "json"])
        result = await self._run_helm_local(args)
        if not result.get("success"):
            return []
        data = result.get("data")
        return data if isinstance(data, list) else []

    # ── Release inspection ────────────────────────────────────────────

    async def release_status(self, cluster_id: str, release_name: str, namespace: str) -> dict[str, Any]:
        """helm status — current state, notes, and rendered resources."""
        _validate_name(release_name, "release name")
        _validate_name(namespace, "namespace")
        return await self._run_helm(cluster_id, ["status", release_name, "-n", namespace, "-o", "json"])

    async def release_history(self, cluster_id: str, release_name: str, namespace: str) -> list[dict[str, Any]]:
        """helm history — every revision of a release, newest last."""
        _validate_name(release_name, "release name")
        _validate_name(namespace, "namespace")
        result = await self._run_helm(cluster_id, ["history", release_name, "-n", namespace, "-o", "json"])
        if not result.get("success"):
            return []
        data = result.get("data")
        return data if isinstance(data, list) else []

    # ── Chart authoring helpers ───────────────────────────────────────

    async def template_chart(
        self,
        chart: str,
        *,
        release_name: str = "release-name",
        namespace: str | None = None,
        version: str | None = None,
        values_yaml: str | None = None,
    ) -> dict[str, Any]:
        """helm template — renders manifests locally without touching the cluster."""
        _validate_chart_ref(chart)
        _validate_name(release_name, "release name")
        args = ["template", release_name, chart]
        if namespace:
            args.extend(["-n", _validate_name(namespace, "namespace")])
        if version:
            args.extend(["--version", _validate_name(version, "version")])
        return await self._with_values_file(args, values_yaml, self._run_helm_local)

    async def lint_chart(self, chart: str, *, values_yaml: str | None = None) -> dict[str, Any]:
        """helm lint — validates a chart without installing it."""
        _validate_chart_ref(chart)
        return await self._with_values_file(["lint", chart], values_yaml, self._run_helm_local)

    @staticmethod
    async def _with_values_file(args: list[str], values_yaml: str | None, runner: Any) -> dict[str, Any]:
        """Run `args`, appending a temporary -f values file when one is supplied."""
        values_path: str | None = None
        if values_yaml:
            with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as tmp:
                tmp.write(values_yaml)
                values_path = tmp.name
            args = [*args, "-f", values_path]
        try:
            return await runner(args)
        finally:
            if values_path:
                with contextlib.suppress(OSError):
                    os.unlink(values_path)

    async def list_releases_detailed(self, cluster_id: str, namespace: str | None = None) -> dict[str, Any]:
        """List Helm releases, reporting which source answered and why.

        The CLI is absent from most container images and can also fail for
        unrelated reasons (non-zero exit, timeout, unparseable output), so any
        CLI failure falls through to reading Helm's own release secrets, which
        needs no extra tooling.

        Neither source raises to the caller. "No releases" and "could not
        determine" are different answers, so the second is returned as a
        ``warning`` rather than an empty list that looks like success.
        """
        try:
            releases = await self._list_releases_cli(cluster_id, namespace)
            return {"releases": releases, "source": "helm-cli", "warning": None}
        except Exception as exc:
            cli_error = str(exc)[:300]
            logger.info("helm_cli_unavailable_using_k8s_api_fallback", error=cli_error)

        try:
            releases = await self._list_releases_from_secrets(cluster_id, namespace)
            return {"releases": releases, "source": "k8s-secrets", "warning": None}
        except Exception as exc:
            detail = str(exc)[:300]
            logger.warning(
                "helm_list_unavailable",
                cluster_id=cluster_id,
                namespace=namespace or "all",
                error=detail,
            )
            scope = f"namespace '{namespace}'" if namespace else "all namespaces"
            return {
                "releases": [],
                "source": "unavailable",
                "warning": (
                    f"Could not list Helm releases for {scope}. The Helm CLI is unavailable and "
                    f"reading Helm's release secrets failed: {detail}"
                ),
            }

    async def list_releases(self, cluster_id: str, namespace: str | None = None) -> list[dict[str, Any]]:
        """Releases only. Prefer list_releases_detailed when the reason matters."""
        result = await self.list_releases_detailed(cluster_id, namespace)
        return result["releases"]

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
                # Raise rather than return [] so list_releases falls back to the
                # secrets reader; an empty list here is indistinguishable from
                # "this cluster genuinely has no releases".
                raise RuntimeError(f"helm list exited {proc.returncode}: {proc.stderr[:200]}")
            data = json.loads(proc.stdout or "[]")
            return data if isinstance(data, list) else []
        finally:
            with contextlib.suppress(OSError):
                os.unlink(kubeconfig)

    async def _list_releases_from_secrets(self, cluster_id: str, namespace: str | None = None) -> list[dict[str, Any]]:
        """Read Helm releases directly from Kubernetes secrets (owner=helm label)."""
        import base64
        import gzip

        # _get_k8s_clients must be inside the try: it performs auth and can raise,
        # and an escape here would 500 the endpoint instead of degrading.
        try:
            _, core_v1, _ = await self._aks._get_k8s_clients(cluster_id)
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
            # Raise so list_releases_detailed can explain the failure. Returning []
            # here made a permissions error look like a cluster with no releases.
            logger.warning("helm_list_from_secrets_failed", error=str(e)[:300])
            raise

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
        _validate_name(release_name, "release name")
        _validate_name(namespace, "namespace")
        _validate_chart_ref(chart)
        if version:
            _validate_name(version, "version")
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
        _validate_name(release_name, "release name")
        _validate_name(namespace, "namespace")
        _validate_chart_ref(chart)
        if version:
            _validate_name(version, "version")
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
        _validate_name(release_name, "release name")
        _validate_name(namespace, "namespace")
        return await self._run_helm(cluster_id, ["uninstall", release_name, "-n", namespace])

    async def rollback_release(
        self, cluster_id: str, release_name: str, namespace: str, revision: int
    ) -> dict[str, Any]:
        _validate_name(release_name, "release name")
        _validate_name(namespace, "namespace")
        if revision < 1:
            raise HelmValidationError("Revision must be 1 or greater.")
        return await self._run_helm(cluster_id, ["rollback", release_name, str(revision), "-n", namespace])
