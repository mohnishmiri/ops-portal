"""
Kubernetes Dashboard proxy endpoints.

Provides:
- GET  /environments         — list all dashboard environments with status
- GET  /{env_key}/health     — check single environment health
- POST /{env_key}/launch     — create session and return proxy URL (requires MSAL auth)
- ALL  /{env_key}/proxy/...  — reverse proxy with session-cookie auth + token injection

Authentication flow for the proxy:
1. Frontend calls POST /{env_key}/launch (authenticated via MSAL Bearer token)
2. Backend creates a short-lived session token and returns the proxy URL with ?_s=<token>
3. Frontend opens this URL in a new browser tab
4. Proxy validates the session token, sets a HttpOnly cookie, and serves the dashboard
5. Subsequent requests (assets, API calls) are authenticated via the cookie
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import secrets
import time
from typing import Any

import structlog
from fastapi import APIRouter, Cookie, Depends, HTTPException, Query, Request
from fastapi.responses import RedirectResponse, Response

from app.auth import get_current_user
from app.core.config import settings
from app.schemas.auth import TokenClaims
from app.services.k8s_dashboard_service import K8sDashboardService, get_k8s_dashboard_service

logger = structlog.get_logger(__name__)

router = APIRouter()

# ── Signed Launch And Session Tokens ───────────────────────────────────
# Browser navigation cannot send the MSAL bearer token, so launch creates a
# short-lived signed token that is exchanged for a signed HttpOnly cookie.
# Tokens are stateless so the flow works across multiple backend replicas.

SESSION_TTL = 8 * 3600  # 8 hours
LAUNCH_TOKEN_TTL = 60  # 60 seconds

COOKIE_NAME = "k8s_dash_session"


def _base64url_encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _base64url_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(f"{value}{padding}")


def _get_signing_secret() -> bytes:
    secret = settings.K8S_DASHBOARD_SESSION_SECRET or settings.AZURE_CLIENT_SECRET
    if not secret:
        if settings.ENVIRONMENT.lower() not in {"development", "dev", "local", "test", "testing"}:
            logger.error("k8s_dashboard_session_secret_missing")
            raise HTTPException(status_code=503, detail="Dashboard session signing is not configured")
        secret = "development-k8s-dashboard-session-secret"
    return secret.encode("utf-8")


def _sign_payload(payload: dict[str, Any]) -> str:
    payload_json = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    encoded_payload = _base64url_encode(payload_json)
    signature = hmac.new(
        _get_signing_secret(),
        encoded_payload.encode("ascii"),
        hashlib.sha256,
    ).digest()
    return f"{encoded_payload}.{_base64url_encode(signature)}"


def _verify_signed_token(token: str, expected_type: str, env_key: str) -> dict[str, Any] | None:
    try:
        encoded_payload, encoded_signature = token.split(".", 1)
    except ValueError:
        return None

    expected_signature = hmac.new(
        _get_signing_secret(),
        encoded_payload.encode("ascii"),
        hashlib.sha256,
    ).digest()
    try:
        actual_signature = _base64url_decode(encoded_signature)
    except ValueError:
        return None
    if not hmac.compare_digest(actual_signature, expected_signature):
        return None

    try:
        payload = json.loads(_base64url_decode(encoded_payload))
    except (ValueError, TypeError, json.JSONDecodeError):
        return None

    if payload.get("typ") != expected_type:
        return None
    if payload.get("env_key") != env_key:
        return None
    if int(payload.get("exp", 0)) < int(time.time()):
        return None
    return payload


def _create_launch_token(env_key: str, user_id: str, user_email: str) -> str:
    """Create a short-lived launch token that can be exchanged for a session."""
    return _sign_payload(
        {
            "typ": "launch",
            "env_key": env_key,
            "user_id": user_id,
            "user_email": user_email,
            "exp": int(time.time()) + LAUNCH_TOKEN_TTL,
            "nonce": secrets.token_urlsafe(16),
        }
    )


def _exchange_launch_token(token: str, env_key: str) -> str | None:
    """Exchange a launch token for a signed session token."""
    token_data = _verify_signed_token(token, "launch", env_key)
    if not token_data:
        return None

    return _sign_payload(
        {
            "typ": "session",
            "env_key": env_key,
            "user_id": token_data["user_id"],
            "user_email": token_data["user_email"],
            "exp": int(time.time()) + SESSION_TTL,
            "nonce": secrets.token_urlsafe(16),
        }
    )


def _validate_session(session_token: str | None, env_key: str) -> dict[str, Any] | None:
    """Validate a signed session cookie. Returns session data or None."""
    if not session_token:
        return None
    payload = _verify_signed_token(session_token, "session", env_key)
    if not payload:
        return None
    return {
        "env_key": env_key,
        "user_id": payload["user_id"],
        "user_email": payload["user_email"],
    }


# ── Dependency ─────────────────────────────────────────────────────────


def _get_service() -> K8sDashboardService:
    return get_k8s_dashboard_service()


# ── Metadata Endpoints (require MSAL auth) ─────────────────────────────


@router.get("/environments")
async def list_dashboard_environments(
    user: TokenClaims = Depends(get_current_user),
    service: K8sDashboardService = Depends(_get_service),
) -> list[dict]:
    """List all configured K8s Dashboard environments."""
    logger.info("k8s_dashboard_list", user=user.email)
    return service.list_environments()


@router.get("/{env_key}/health")
async def check_dashboard_health(
    env_key: str,
    user: TokenClaims = Depends(get_current_user),
    service: K8sDashboardService = Depends(_get_service),
) -> dict:
    """Check health of a specific K8s Dashboard environment."""
    env = service.get_environment(env_key)
    if not env:
        raise HTTPException(status_code=404, detail=f"Environment '{env_key}' not found")
    return await service.check_health(env_key)


# ── Launch Endpoint (requires MSAL auth) ───────────────────────────────


@router.post("/{env_key}/launch")
async def launch_dashboard(
    env_key: str,
    request: Request,
    user: TokenClaims = Depends(get_current_user),
    service: K8sDashboardService = Depends(_get_service),
) -> dict:
    """Create a session and return the proxy URL for opening in a new tab."""
    env = service.get_environment(env_key)
    if not env:
        raise HTTPException(status_code=404, detail=f"Environment '{env_key}' not found")

    token = _create_launch_token(env_key, getattr(user, "sub", None) or user.email, user.email)
    logger.info("k8s_dashboard_launch", env_key=env_key, user=user.email)

    # Use a path token instead of a query token because some production gateways
    # normalize or strip leading-underscore query params on direct navigation.
    proxy_path = f"/api/v1/aks/dashboard/{env_key}/launch/{token}"

    return {"proxy_url": proxy_path, "env_key": env_key, "display_name": env["display_name"]}


@router.get("/{env_key}/launch/{token}")
async def exchange_launch_token(
    env_key: str,
    token: str,
    service: K8sDashboardService = Depends(_get_service),
) -> RedirectResponse:
    """Exchange a one-time launch token for a proxy session cookie."""
    env = service.get_environment(env_key)
    if not env:
        raise HTTPException(status_code=404, detail=f"Environment '{env_key}' not found")

    session_id = _exchange_launch_token(token, env_key)
    if not session_id:
        raise HTTPException(status_code=401, detail="Launch token expired or invalid")

    response = RedirectResponse(url=f"/api/v1/aks/dashboard/{env_key}/proxy/")
    response.set_cookie(
        key=COOKIE_NAME,
        value=session_id,
        max_age=SESSION_TTL,
        httponly=True,
        secure=True,
        samesite="lax",
        path=f"/api/v1/aks/dashboard/{env_key}/proxy",
    )
    return response


# ── Reverse Proxy Endpoints (session-cookie auth) ──────────────────────


@router.api_route(
    "/{env_key}/proxy/{path:path}",
    methods=["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"],
)
async def proxy_dashboard(
    env_key: str,
    path: str,
    request: Request,
    launch_token: str | None = Query(default=None, alias="_s"),
    k8s_dash_session: str | None = Cookie(default=None),
    service: K8sDashboardService = Depends(_get_service),
) -> Response:
    """Reverse proxy to K8s Dashboard with session-cookie auth + token injection."""
    env = service.get_environment(env_key)
    if not env:
        raise HTTPException(status_code=404, detail=f"Environment '{env_key}' not found")

    # Authenticate: try cookie first, then launch token exchange
    new_session_id: str | None = None
    session = _validate_session(k8s_dash_session, env_key)
    if not session and launch_token:
        new_session_id = _exchange_launch_token(launch_token, env_key)
        if new_session_id:
            session = _validate_session(new_session_id, env_key)
    if not session:
        raise HTTPException(status_code=401, detail="Not authenticated — launch from portal")

    # Read request body for forwarding
    body = await request.body()

    # Extract headers (as plain dict)
    headers = dict(request.headers)

    # Query string — strip our internal _s param
    raw_query = request.url.query or ""
    query_parts = [p for p in raw_query.split("&") if not p.startswith("_s=")]
    query_string = "&".join(query_parts)

    try:
        resp = await service.proxy_request(
            env_key=env_key,
            method=request.method,
            path=path,
            headers=headers,
            body=body if body else None,
            query_string=query_string,
        )
    except ValueError as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    except Exception as exc:
        logger.error("k8s_dashboard_proxy_error", env_key=env_key, path=path, error=str(exc))
        raise HTTPException(status_code=502, detail="Dashboard unavailable")

    # Build response — strip hop-by-hop headers, rewrite URLs
    excluded_headers = {
        "transfer-encoding",
        "connection",
        "content-encoding",
        "content-length",  # Recalculated by FastAPI after content rewriting
        "set-cookie",  # Don't forward upstream dashboard cookies
    }
    response_headers: dict[str, str] = {}
    for key, value in resp.headers.multi_items():
        if key.lower() not in excluded_headers:
            response_headers[key] = value

    # Remove security headers that interfere with proxying
    response_headers.pop("x-frame-options", None)
    response_headers.pop("X-Frame-Options", None)
    response_headers.pop("content-security-policy", None)
    response_headers.pop("Content-Security-Policy", None)

    content = resp.content

    # Rewrite URLs in HTML responses so assets load through our proxy
    content_type = resp.headers.get("content-type", "")
    if "text/html" in content_type:
        base_url = env["url"].rstrip("/")
        proxy_prefix = f"/api/v1/aks/dashboard/{env_key}/proxy"

        # Replace absolute dashboard URL references with proxy path
        content = content.replace(base_url.encode(), proxy_prefix.encode())
        content = re.sub(
            rb'<base\s+href=["\'][^"\']*["\']\s*/?>',
            b'<base data-ops-proxy="1">',
            content,
            count=1,
            flags=re.IGNORECASE,
        )
        # Rewrite root-relative paths (also transforms <base href="/">)
        content = content.replace(b'href="/', f'href="{proxy_prefix}/'.encode())
        content = content.replace(b"href='/", f"href='{proxy_prefix}/".encode())
        content = content.replace(b'src="/', f'src="{proxy_prefix}/'.encode())
        content = content.replace(b"src='/", f"src='{proxy_prefix}/".encode())
        content = content.replace(b'action="/', f'action="{proxy_prefix}/'.encode())
        content = re.sub(
            rb'((?:src|href)=["\'])(?!https?:|//|/|#|data:)([^"\']+)',
            lambda match: match.group(1) + f"{proxy_prefix}/".encode() + match.group(2),
            content,
            flags=re.IGNORECASE,
        )
        content = content.replace(
            b'<base data-ops-proxy="1">',
            f'<base href="{proxy_prefix}/">'.encode(),
            1,
        )

        # If no <base> tag exists after rewrites, inject one
        if b"<base" not in content:
            if b"<head>" in content:
                content = content.replace(
                    b"<head>",
                    f'<head><base href="{proxy_prefix}/">'.encode(),
                    1,
                )
            elif b"<head " in content:
                content = re.sub(
                    rb"(<head[^>]*>)",
                    f'\\1<base href="{proxy_prefix}/">'.encode(),
                    content,
                    count=1,
                )

    # Also rewrite JavaScript/JSON API calls if content is JS
    if "javascript" in content_type or "application/json" in content_type:
        proxy_prefix = f"/api/v1/aks/dashboard/{env_key}/proxy"
        content = content.replace(b'"/api/', f'"{proxy_prefix}/api/'.encode())
        content = content.replace(b"'/api/", f"'{proxy_prefix}/api/".encode())

    # Build the final response
    response = Response(
        content=content,
        status_code=resp.status_code,
        headers=response_headers,
        media_type=resp.headers.get("content-type"),
    )

    # Set session cookie on first visit (launch token exchange)
    if new_session_id:
        response.set_cookie(
            key=COOKIE_NAME,
            value=new_session_id,
            max_age=SESSION_TTL,
            httponly=True,
            secure=True,
            samesite="lax",
            path=f"/api/v1/aks/dashboard/{env_key}/proxy",
        )

    return response


@router.api_route(
    "/{env_key}/proxy",
    methods=["GET"],
)
async def proxy_dashboard_root(
    env_key: str,
    request: Request,
    launch_token: str | None = Query(default=None, alias="_s"),
    k8s_dash_session: str | None = Cookie(default=None),
    service: K8sDashboardService = Depends(_get_service),
) -> Response:
    """Proxy the dashboard root (index page)."""
    return await proxy_dashboard(
        env_key=env_key,
        path="",
        request=request,
        launch_token=launch_token,
        k8s_dash_session=k8s_dash_session,
        service=service,
    )
