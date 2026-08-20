"""
Tests for Kubernetes Dashboard proxy service and endpoints.
"""

from unittest.mock import AsyncMock, patch

import httpx
import pytest
from httpx import ASGITransport, AsyncClient

from app.api.v1.endpoints.aks_dashboard import _create_launch_token
from app.auth import get_current_user
from app.main import create_application
from app.services.k8s_dashboard_service import K8sDashboardService

# ── Fixtures ───────────────────────────────────────────────────────────


@pytest.fixture
def app():
    return create_application()


@pytest.fixture
def dashboard_service():
    return K8sDashboardService()


async def _admin_user():
    from app.schemas.auth import UserContext, UserRole

    return UserContext(
        user_id="test-admin",
        object_id="00000000-0000-0000-0000-000000000000",
        display_name="Test Admin",
        email="admin@example.com",
        roles=[UserRole.ADMIN],
        raw_roles=["admin"],
        tenant_id="tenant-test",
        allowed_subscriptions=[],
    )


@pytest.fixture
async def client(app):
    """Client with admin auth override."""
    app.dependency_overrides[get_current_user] = _admin_user
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


# ── Service Tests ──────────────────────────────────────────────────────


class TestK8sDashboardService:
    """Unit tests for K8sDashboardService."""

    def test_list_environments_returns_all_configured(self, dashboard_service):
        """Should return all 6 environments from config."""
        envs = dashboard_service.list_environments()
        assert len(envs) == 6
        env_keys = [e["env_key"] for e in envs]
        assert "prod" in env_keys
        assert "preprod" in env_keys
        assert "perf" in env_keys
        assert "uat" in env_keys
        assert "dev" in env_keys
        assert "dr" in env_keys

    def test_list_environments_excludes_tokens(self, dashboard_service):
        """Tokens must never appear in the metadata response."""
        envs = dashboard_service.list_environments()
        for env in envs:
            assert "token" not in str(env).lower() or "token_configured" in env

    def test_get_environment_returns_known_env(self, dashboard_service):
        """Should return config for a known environment key."""
        env = dashboard_service.get_environment("dev")
        assert env is not None
        assert env["display_name"] == "Development"
        assert "attccdashboardcnr.dev.att.com" in env["url"]

    def test_get_environment_returns_none_for_unknown(self, dashboard_service):
        """Should return None for an unknown environment key."""
        assert dashboard_service.get_environment("nonexistent") is None

    @pytest.mark.asyncio
    async def test_check_health_online(self, dashboard_service):
        """Should return online status when dashboard is reachable."""
        mock_response = httpx.Response(200)
        with patch.object(dashboard_service, "_get_client") as mock_client:
            client_instance = AsyncMock()
            client_instance.head = AsyncMock(return_value=mock_response)
            mock_client.return_value = client_instance

            result = await dashboard_service.check_health("dev")
            assert result["status"] == "online"
            assert result["env_key"] == "dev"

    @pytest.mark.asyncio
    async def test_check_health_offline_on_timeout(self, dashboard_service):
        """Should return offline status on timeout."""
        with patch.object(dashboard_service, "_get_client") as mock_client:
            client_instance = AsyncMock()
            client_instance.head = AsyncMock(side_effect=httpx.TimeoutException("timeout"))
            mock_client.return_value = client_instance

            result = await dashboard_service.check_health("dev")
            assert result["status"] == "offline"
            assert "Timeout" in result["error"]

    @pytest.mark.asyncio
    async def test_check_health_unknown_env(self, dashboard_service):
        """Should return unknown status for unconfigured env."""
        result = await dashboard_service.check_health("nonexistent")
        assert result["status"] == "unknown"

    @pytest.mark.asyncio
    async def test_proxy_request_injects_token(self, dashboard_service):
        """Should inject Authorization header in proxied requests."""
        mock_response = httpx.Response(200, content=b"OK", headers={"content-type": "text/plain"})

        with (
            patch.object(dashboard_service, "_get_token", return_value="test-bearer-token"),
            patch.object(dashboard_service, "_get_client") as mock_client,
        ):
            client_instance = AsyncMock()
            client_instance.request = AsyncMock(return_value=mock_response)
            mock_client.return_value = client_instance

            await dashboard_service.proxy_request(
                env_key="dev",
                method="GET",
                path="static/main.js",
                headers={"accept": "application/json"},
            )

            call_kwargs = client_instance.request.call_args[1]
            assert call_kwargs["headers"]["Authorization"] == "Bearer test-bearer-token"

    @pytest.mark.asyncio
    async def test_proxy_request_exchanges_dashboard_token_for_api_calls(self, dashboard_service):
        """Dashboard API calls should use the dashboard login JWE token."""
        login_response = httpx.Response(
            200,
            json={"jweToken": "dashboard-jwe-token"},
            request=httpx.Request("POST", "https://dashboard.test/api/v1/login"),
        )
        api_response = httpx.Response(200, content=b"{}", headers={"content-type": "application/json"})

        with (
            patch.object(dashboard_service, "_get_token", return_value="raw-k8s-token"),
            patch.object(dashboard_service, "_get_client") as mock_client,
        ):
            client_instance = AsyncMock()
            client_instance.post = AsyncMock(return_value=login_response)
            client_instance.request = AsyncMock(return_value=api_response)
            mock_client.return_value = client_instance

            await dashboard_service.proxy_request(
                env_key="dev",
                method="GET",
                path="api/v1/deployment/default",
                headers={"cookie": "k8s_dash_session=session-token", "accept": "application/json"},
            )

            client_instance.post.assert_awaited_once()
            call_kwargs = client_instance.request.call_args[1]
            assert call_kwargs["headers"]["Authorization"] == "Bearer dashboard-jwe-token"
            assert "cookie" not in {key.lower() for key in call_kwargs["headers"]}

    @pytest.mark.asyncio
    async def test_proxy_request_strips_incoming_auth(self, dashboard_service):
        """Should not forward the user's Authorization header."""
        mock_response = httpx.Response(200, content=b"OK", headers={"content-type": "text/plain"})

        with (
            patch.object(dashboard_service, "_get_token", return_value="service-token"),
            patch.object(dashboard_service, "_get_client") as mock_client,
        ):
            client_instance = AsyncMock()
            client_instance.request = AsyncMock(return_value=mock_response)
            mock_client.return_value = client_instance

            await dashboard_service.proxy_request(
                env_key="dev",
                method="GET",
                path="static/main.js",
                headers={"authorization": "Bearer user-token", "accept": "text/html"},
            )

            call_kwargs = client_instance.request.call_args[1]
            # Should use service token, not user token
            assert call_kwargs["headers"]["Authorization"] == "Bearer service-token"

    @pytest.mark.asyncio
    async def test_proxy_request_raises_on_unknown_env(self, dashboard_service):
        """Should raise ValueError for unknown environment."""
        with pytest.raises(ValueError, match="Unknown environment"):
            await dashboard_service.proxy_request(
                env_key="nonexistent",
                method="GET",
                path="/",
                headers={},
            )

    @pytest.mark.asyncio
    async def test_proxy_request_raises_on_missing_token(self, dashboard_service):
        """Should raise ValueError when token is not configured."""
        with (
            patch.object(dashboard_service, "_get_token", return_value=""),
            pytest.raises(ValueError, match="No token configured"),
        ):
            await dashboard_service.proxy_request(
                env_key="dev",
                method="GET",
                path="/",
                headers={},
            )


# ── API Endpoint Tests ─────────────────────────────────────────────────


class TestK8sDashboardAPI:
    """Integration tests for the K8s Dashboard API endpoints."""

    @pytest.mark.asyncio
    async def test_list_environments_endpoint(self, client):
        """GET /aks/dashboard/environments should return environment list."""
        resp = await client.get("/api/v1/aks/dashboard/environments")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) == 6
        # Verify no tokens in response
        raw = resp.text
        assert "Bearer" not in raw

    @pytest.mark.asyncio
    async def test_health_endpoint_valid_env(self, client):
        """GET /aks/dashboard/{env}/health should return health for known env."""
        with patch.object(
            K8sDashboardService,
            "check_health",
            new_callable=AsyncMock,
            return_value={"env_key": "dev", "status": "online", "status_code": 200},
        ):
            resp = await client.get("/api/v1/aks/dashboard/dev/health")
            assert resp.status_code == 200
            assert resp.json()["status"] == "online"

    @pytest.mark.asyncio
    async def test_health_endpoint_unknown_env(self, client):
        """GET /aks/dashboard/{env}/health should 404 for unknown env."""
        resp = await client.get("/api/v1/aks/dashboard/nonexistent/health")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_launch_endpoint_returns_proxy_url(self, client):
        """POST /aks/dashboard/{env}/launch should return a proxy URL with session token."""
        resp = await client.post("/api/v1/aks/dashboard/dev/launch")
        assert resp.status_code == 200
        data = resp.json()
        assert "proxy_url" in data
        assert "/launch/" in data["proxy_url"]
        assert "dev" in data["proxy_url"]

    @pytest.mark.asyncio
    async def test_launch_token_route_allows_browser_navigation_without_bearer(self, app):
        """GET /launch/{token} should rely on signed token auth, not MSAL bearer auth."""
        token = _create_launch_token("preprod", "test-user", "test@example.com")
        app.dependency_overrides.clear()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as anonymous_client:
            resp = await anonymous_client.get(
                f"/api/v1/aks/dashboard/preprod/launch/{token}",
                follow_redirects=False,
            )

        assert resp.status_code in (302, 307)
        assert resp.headers["location"] == "/api/v1/aks/dashboard/preprod/proxy/"
        assert resp.cookies.get("k8s_dash_session")

    @pytest.mark.asyncio
    async def test_proxy_endpoint_returns_502_on_service_error(self, client):
        """Proxy should return 502 when dashboard service raises an error."""
        # First get a session via launch
        launch_resp = await client.post("/api/v1/aks/dashboard/dev/launch")
        proxy_url = launch_resp.json()["proxy_url"]

        with patch.object(
            K8sDashboardService,
            "proxy_request",
            new_callable=AsyncMock,
            side_effect=Exception("Connection refused"),
        ):
            launch = await client.get(proxy_url, follow_redirects=False)
            assert launch.status_code in (302, 307)
            session_cookie = launch.cookies.get("k8s_dash_session")
            resp = await client.get(
                "/api/v1/aks/dashboard/dev/proxy/some-path",
                cookies={"k8s_dash_session": session_cookie},
            )
            assert resp.status_code == 502

    @pytest.mark.asyncio
    async def test_proxy_endpoint_forwards_request(self, client):
        """Proxy should forward requests to the dashboard."""
        # First get a session via launch
        launch_resp = await client.post("/api/v1/aks/dashboard/dev/launch")
        proxy_url = launch_resp.json()["proxy_url"]

        mock_response = httpx.Response(
            200,
            content=b"<html><body>Dashboard</body></html>",
            headers={"content-type": "text/html"},
        )
        with patch.object(
            K8sDashboardService,
            "proxy_request",
            new_callable=AsyncMock,
            return_value=mock_response,
        ):
            launch = await client.get(proxy_url, follow_redirects=False)
            assert launch.status_code in (302, 307)
            session_cookie = launch.cookies.get("k8s_dash_session")
            resp = await client.get(
                "/api/v1/aks/dashboard/dev/proxy/",
                cookies={"k8s_dash_session": session_cookie},
            )
            assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_proxy_endpoint_rewrites_relative_dashboard_assets(self, client):
        """Dashboard HTML should load relative JS/CSS bundles through the proxy."""
        launch_resp = await client.post("/api/v1/aks/dashboard/dev/launch")
        proxy_url = launch_resp.json()["proxy_url"]

        mock_response = httpx.Response(
            200,
            content=(
                b'<html><head><base href="/">'
                b'<link rel="stylesheet" href="styles.abc123.css">'
                b'</head><body><script src="runtime.abc123.js"></script>'
                b'<script src="main.def456.js"></script></body></html>'
            ),
            headers={"content-type": "text/html"},
        )
        with patch.object(
            K8sDashboardService,
            "proxy_request",
            new_callable=AsyncMock,
            return_value=mock_response,
        ):
            launch = await client.get(proxy_url, follow_redirects=False)
            session_cookie = launch.cookies.get("k8s_dash_session")
            resp = await client.get(
                "/api/v1/aks/dashboard/dev/proxy/",
                cookies={"k8s_dash_session": session_cookie},
            )

        assert resp.status_code == 200
        assert 'base href="/api/v1/aks/dashboard/dev/proxy/"' in resp.text
        assert 'href="/api/v1/aks/dashboard/dev/proxy/styles.abc123.css"' in resp.text
        assert 'src="/api/v1/aks/dashboard/dev/proxy/runtime.abc123.js"' in resp.text
        assert 'src="/api/v1/aks/dashboard/dev/proxy/main.def456.js"' in resp.text

    @pytest.mark.asyncio
    async def test_proxy_endpoint_unknown_env_returns_404(self, client):
        """Proxy should return 404 for unknown environment."""
        resp = await client.get("/api/v1/aks/dashboard/nonexistent/proxy/test")
        assert resp.status_code == 404
