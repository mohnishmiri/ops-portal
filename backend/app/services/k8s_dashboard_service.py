"""
Kubernetes Dashboard proxy service.

Provides environment metadata, health checks, and proxied requests to
K8s Dashboard instances. Tokens are sourced exclusively from environment
variables — they are never exposed to API consumers.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import httpx
import structlog

from app.core.config import settings

logger = structlog.get_logger(__name__)

_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "dashboard_config.json"

# Mapping from env_key to the Settings attribute holding the token
_TOKEN_ATTR_MAP: dict[str, str] = {
    "prod": "K8S_DASHBOARD_TOKEN_PROD",
    "preprod": "K8S_DASHBOARD_TOKEN_PREPROD",
    "perf": "K8S_DASHBOARD_TOKEN_PERF",
    "uat": "K8S_DASHBOARD_TOKEN_UAT",
    "dev": "K8S_DASHBOARD_TOKEN_DEV",
    "dr": "K8S_DASHBOARD_TOKEN_DR",
}


def _load_dashboard_config() -> list[dict[str, Any]]:
    """Load dashboard environment configuration from JSON file."""
    if not _CONFIG_PATH.exists():
        logger.warning("dashboard_config_missing", path=str(_CONFIG_PATH))
        return []
    with open(_CONFIG_PATH) as f:
        return json.load(f)  # type: ignore[no-any-return]


class K8sDashboardService:
    """Service for K8s Dashboard proxy operations."""

    def __init__(self) -> None:
        self._environments: list[dict[str, Any]] = _load_dashboard_config()
        self._client: httpx.AsyncClient | None = None
        self._dashboard_tokens: dict[str, tuple[str, float]] = {}

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(settings.K8S_DASHBOARD_PROXY_TIMEOUT),
                follow_redirects=True,
                verify=False,  # Internal dashboards may use self-signed certs
            )
        return self._client

    def list_environments(self) -> list[dict[str, Any]]:
        """Return all configured dashboard environments (without tokens)."""
        results = []
        for env in self._environments:
            token_configured = bool(self._get_token(env["env_key"]))
            results.append(
                {
                    "env_key": env["env_key"],
                    "display_name": env["display_name"],
                    "url": env["url"],
                    "cluster_name": env["cluster_name"],
                    "namespace": env.get("namespace", "default"),
                    "token_configured": token_configured,
                }
            )
        return results

    def get_environment(self, env_key: str) -> dict[str, Any] | None:
        """Return a single environment config by key."""
        for env in self._environments:
            if env["env_key"] == env_key:
                return env
        return None

    def _get_token(self, env_key: str) -> str:
        """Retrieve the bearer token from environment variable."""
        attr_name = _TOKEN_ATTR_MAP.get(env_key, "")
        if not attr_name:
            return ""
        return getattr(settings, attr_name, "") or ""

    async def _get_dashboard_token(self, env_key: str, raw_token: str, *, force_refresh: bool = False) -> str:
        """Exchange the Kubernetes token for a Dashboard API token.

        Kubernetes Dashboard v2 authenticates data API calls with the JWE token
        returned by its own login endpoint. The raw service-account token remains
        server-side and is never returned to the browser.
        """
        cached = self._dashboard_tokens.get(env_key)
        now = time.time()
        if not force_refresh and cached and cached[1] > now:
            return cached[0]

        env = self.get_environment(env_key)
        if not env:
            raise ValueError(f"Unknown environment: {env_key}")

        client = await self._get_client()
        login_url = f"{env['url'].rstrip('/')}/api/v1/login"
        response = await client.post(
            login_url,
            json={"token": raw_token},
            headers={"content-type": "application/json"},
        )
        if response.status_code >= 400:
            logger.warning(
                "k8s_dashboard_login_failed",
                env_key=env_key,
                status_code=response.status_code,
            )
        response.raise_for_status()
        payload = response.json()
        dashboard_token = payload.get("jweToken") or payload.get("token")
        if not isinstance(dashboard_token, str) or not dashboard_token:
            raise ValueError("Dashboard login did not return an auth token")

        self._dashboard_tokens[env_key] = (dashboard_token, now + 900)
        return dashboard_token

    async def check_health(self, env_key: str) -> dict[str, Any]:
        """Check if a dashboard is reachable."""
        env = self.get_environment(env_key)
        if not env:
            return {"env_key": env_key, "status": "unknown", "error": "Environment not configured"}

        client = await self._get_client()
        try:
            resp = await client.head(env["url"], timeout=10.0)
            status = "online" if resp.status_code < 500 else "degraded"
            return {"env_key": env_key, "status": status, "status_code": resp.status_code}
        except httpx.TimeoutException:
            return {"env_key": env_key, "status": "offline", "error": "Timeout"}
        except httpx.ConnectError:
            return {"env_key": env_key, "status": "offline", "error": "Connection refused"}
        except Exception as exc:
            return {"env_key": env_key, "status": "offline", "error": str(exc)}

    async def proxy_request(
        self,
        env_key: str,
        method: str,
        path: str,
        headers: dict[str, str],
        body: bytes | None = None,
        query_string: str = "",
    ) -> httpx.Response:
        """Proxy a request to the target K8s Dashboard with token injection."""
        env = self.get_environment(env_key)
        if not env:
            raise ValueError(f"Unknown environment: {env_key}")

        token = self._get_token(env_key)
        if not token:
            raise ValueError(f"No token configured for environment: {env_key}")

        base_url = env["url"].rstrip("/")
        target_url = f"{base_url}/{path.lstrip('/')}" if path else base_url + "/"
        if query_string:
            target_url = f"{target_url}?{query_string}"

        # Build outbound headers — inject Dashboard auth, strip hop-by-hop
        proxy_headers: dict[str, str] = {}
        skip_headers = {"host", "authorization", "cookie", "connection", "transfer-encoding"}
        for k, v in headers.items():
            if k.lower() not in skip_headers:
                proxy_headers[k] = v

        request_path = path.lstrip("/")
        if request_path.startswith("api/"):
            dashboard_token = await self._get_dashboard_token(env_key, token)
            proxy_headers["Authorization"] = f"Bearer {dashboard_token}"
        else:
            proxy_headers["Authorization"] = f"Bearer {token}"

        client = await self._get_client()
        response = await client.request(
            method=method,
            url=target_url,
            headers=proxy_headers,
            content=body,
        )
        if response.status_code == 401 and request_path.startswith("api/"):
            dashboard_token = await self._get_dashboard_token(env_key, token, force_refresh=True)
            proxy_headers["Authorization"] = f"Bearer {dashboard_token}"
            response = await client.request(
                method=method,
                url=target_url,
                headers=proxy_headers,
                content=body,
            )
            if response.status_code == 401:
                logger.warning(
                    "k8s_dashboard_api_unauthorized",
                    env_key=env_key,
                    path=request_path,
                )
        return response

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()


# ── Singleton factory ──────────────────────────────────────────────────

_service_instance: K8sDashboardService | None = None


def get_k8s_dashboard_service() -> K8sDashboardService:
    """Get or create the singleton K8sDashboardService."""
    global _service_instance  # noqa: PLW0603
    if _service_instance is None:
        _service_instance = K8sDashboardService()
    return _service_instance
