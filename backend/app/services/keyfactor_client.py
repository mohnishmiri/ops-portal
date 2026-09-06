"""
Keyfactor Command REST client.

Low-level HTTP client for the Keyfactor Command API. Authenticates using an
Azure AD service principal via the OAuth2 client-credentials flow, caches the
bearer token, and re-acquires once on a 401 before failing.

All external calls carry a timeout and a single retry with backoff for
transient failures (connection errors, timeouts, and 5xx responses).

This module is intentionally free of FastAPI/business concerns — it only
speaks HTTP to Keyfactor and Azure AD and raises typed ``KeyfactorError``
subclasses that the service layer maps to friendly messages.

Security:
- Secrets (client secret, tokens) are never logged.
- Private key / PFX material returned by enrollment is passed straight back to
  the caller and never persisted or logged here.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

import httpx
import structlog

from app.core.config import settings

logger = structlog.get_logger(__name__)

# RFC 5280 revocation reason codes accepted by Keyfactor's revoke endpoint.
REVOCATION_REASONS: dict[str, int] = {
    "unspecified": 0,
    "keyCompromise": 1,
    "caCompromise": 2,
    "affiliationChanged": 3,
    "superseded": 4,
    "cessationOfOperation": 5,
    "certificateHold": 6,
    "removeFromCRL": 8,
    "privilegeWithdrawn": 9,
    "aaCompromise": 10,
}

_TOKEN_EXPIRY_SKEW_SECONDS = 60  # refresh a little before actual expiry
_RETRY_BACKOFF_SECONDS = 0.5


# ── Exceptions ─────────────────────────────────────────────────────────


class KeyfactorError(Exception):
    """Base error for Keyfactor client failures.

    ``status_code`` is the upstream HTTP status when available (else None).
    ``detail`` is a safe, human-readable message (never contains secrets).
    """

    def __init__(self, detail: str, status_code: int | None = None) -> None:
        super().__init__(detail)
        self.detail = detail
        self.status_code = status_code


class KeyfactorAuthError(KeyfactorError):
    """Token acquisition failed or Keyfactor rejected the token (401/403)."""


class KeyfactorNotFoundError(KeyfactorError):
    """Requested certificate or resource does not exist (404)."""


class KeyfactorValidationError(KeyfactorError):
    """Keyfactor rejected the request as invalid (400/422)."""


class KeyfactorTimeoutError(KeyfactorError):
    """Keyfactor or Azure AD did not respond within the configured timeout."""


class KeyfactorServerError(KeyfactorError):
    """Keyfactor returned a 5xx / upstream server error."""


# ── Token provider ─────────────────────────────────────────────────────


class KeyfactorTokenProvider:
    """Acquires and caches an Azure AD bearer token for the Keyfactor API.

    Uses the OAuth2 client-credentials grant. The token is cached until shortly
    before its expiry; ``get_token(force_refresh=True)`` bypasses the cache so
    the client can retry once after a 401.
    """

    def __init__(self) -> None:
        self._token: str | None = None
        self._expires_at: float = 0.0
        self._lock = asyncio.Lock()

    def _is_valid(self) -> bool:
        return bool(self._token) and time.monotonic() < (self._expires_at - _TOKEN_EXPIRY_SKEW_SECONDS)

    async def get_token(self, *, force_refresh: bool = False) -> str:
        async with self._lock:
            if not force_refresh and self._is_valid():
                return self._token  # type: ignore[return-value]
            return await self._acquire()

    async def _acquire(self) -> str:
        if not (settings.KEYFACTOR_CLIENT_ID and settings.KEYFACTOR_CLIENT_SECRET and settings.KEYFACTOR_OAUTH_SCOPE):
            raise KeyfactorAuthError(
                "Keyfactor authentication is not configured. Set KEYFACTOR_CLIENT_ID, "
                "KEYFACTOR_CLIENT_SECRET, and KEYFACTOR_OAUTH_SCOPE."
            )

        data = {
            "grant_type": "client_credentials",
            "client_id": settings.KEYFACTOR_CLIENT_ID,
            "client_secret": settings.KEYFACTOR_CLIENT_SECRET,
            "scope": settings.KEYFACTOR_OAUTH_SCOPE,
        }

        last_exc: Exception | None = None
        for attempt in range(2):  # initial try + single retry
            try:
                async with httpx.AsyncClient(
                    timeout=httpx.Timeout(settings.KEYFACTOR_TIMEOUT_SECONDS),
                    verify=settings.KEYFACTOR_VERIFY_SSL,
                ) as client:
                    resp = await client.post(settings.keyfactor_token_url, data=data)
                if resp.status_code >= 400:
                    # Do not log the response body — it may echo request params.
                    logger.warning("keyfactor_token_request_failed", status=resp.status_code, attempt=attempt)
                    raise KeyfactorAuthError(
                        "Failed to acquire an Azure AD token for Keyfactor.",
                        status_code=resp.status_code,
                    )
                payload = resp.json()
                token = payload.get("access_token")
                if not token:
                    raise KeyfactorAuthError("Azure AD token response did not contain an access token.")
                expires_in = int(payload.get("expires_in", 3600))
                self._token = token
                self._expires_at = time.monotonic() + expires_in
                logger.info("keyfactor_token_acquired", expires_in=expires_in)
                return token
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                last_exc = exc
                logger.warning("keyfactor_token_transient_error", attempt=attempt, error=type(exc).__name__)
                if attempt == 0:
                    await asyncio.sleep(_RETRY_BACKOFF_SECONDS)
                    continue
            except KeyfactorAuthError:
                raise

        raise KeyfactorTimeoutError("Timed out contacting Azure AD for a Keyfactor token.") from last_exc


# ── Client ─────────────────────────────────────────────────────────────


class KeyfactorClient:
    """Async client for the Keyfactor Command certificate API."""

    def __init__(self, token_provider: KeyfactorTokenProvider | None = None) -> None:
        self._tokens = token_provider or KeyfactorTokenProvider()

    # -- internals ------------------------------------------------------

    def _base_url(self) -> str:
        base = (settings.KEYFACTOR_BASE_URL or "").strip().rstrip("/")
        if not base:
            raise KeyfactorError("Keyfactor base URL is not configured (KEYFACTOR_BASE_URL).")
        return base

    def _headers(self, token: str) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "x-keyfactor-api-version": settings.KEYFACTOR_API_VERSION,
            "x-keyfactor-requested-with": "APIClient",
        }

    @staticmethod
    def _raise_for_status(resp: httpx.Response) -> None:
        if resp.status_code < 400:
            return
        detail = KeyfactorClient._safe_error_detail(resp)
        if resp.status_code in (401, 403):
            raise KeyfactorAuthError(detail, status_code=resp.status_code)
        if resp.status_code == 404:
            raise KeyfactorNotFoundError(detail, status_code=resp.status_code)
        if resp.status_code in (400, 422):
            raise KeyfactorValidationError(detail, status_code=resp.status_code)
        if resp.status_code >= 500:
            raise KeyfactorServerError(detail, status_code=resp.status_code)
        raise KeyfactorError(detail, status_code=resp.status_code)

    @staticmethod
    def _safe_error_detail(resp: httpx.Response) -> str:
        """Extract a concise upstream message without leaking internals."""
        try:
            body = resp.json()
        except Exception:
            return f"Keyfactor request failed (HTTP {resp.status_code})."
        if isinstance(body, dict):
            for key in ("Message", "message", "ErrorMessage", "error_description", "Detail"):
                val = body.get(key)
                if isinstance(val, str) and val:
                    return val[:500]
        return f"Keyfactor request failed (HTTP {resp.status_code})."

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
        extra_headers: dict[str, str] | None = None,
    ) -> httpx.Response:
        """Issue a request with token handling, timeout, and a single retry.

        On 401 the token is force-refreshed and the request retried once.
        On transient network/5xx errors the request is retried once with backoff.
        """
        url = f"{self._base_url()}{path}"
        token = await self._tokens.get_token()

        last_exc: Exception | None = None
        reauthed = False
        for attempt in range(2):
            try:
                async with httpx.AsyncClient(
                    timeout=httpx.Timeout(settings.KEYFACTOR_TIMEOUT_SECONDS),
                    verify=settings.KEYFACTOR_VERIFY_SSL,
                ) as client:
                    resp = await client.request(
                        method,
                        url,
                        params=params,
                        json=json_body,
                        headers={**self._headers(token), **(extra_headers or {})},
                    )

                # Token expired mid-flight — re-acquire once, then retry.
                if resp.status_code == 401 and not reauthed:
                    reauthed = True
                    token = await self._tokens.get_token(force_refresh=True)
                    continue

                if resp.status_code >= 500 and attempt == 0:
                    logger.warning("keyfactor_server_error_retry", status=resp.status_code, path=path)
                    await asyncio.sleep(_RETRY_BACKOFF_SECONDS)
                    continue

                self._raise_for_status(resp)
                return resp
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                last_exc = exc
                logger.warning("keyfactor_transient_error", attempt=attempt, path=path, error=type(exc).__name__)
                if attempt == 0:
                    await asyncio.sleep(_RETRY_BACKOFF_SECONDS)
                    continue

        raise KeyfactorTimeoutError("Timed out contacting Keyfactor.") from last_exc

    # -- operations -----------------------------------------------------

    async def search_certificates(
        self,
        *,
        query: str | None,
        page: int,
        page_size: int,
        collection_id: int | None = None,
    ) -> tuple[list[dict[str, Any]], int]:
        """Return (certificates, total_count) for a Keyfactor certificate query."""
        params: dict[str, Any] = {
            "pq.pageReturned": page,
            "pq.returnLimit": page_size,
            "verbose": 2,
            "includeMetadata": "true",
        }
        if query:
            params["pq.queryString"] = query
        if collection_id is not None:
            params["collectionId"] = collection_id
        resp = await self._request("GET", "/Certificates", params=params)
        data = resp.json()
        certs = data if isinstance(data, list) else data.get("Certificates", [])
        total = int(resp.headers.get("x-total-count", len(certs)))
        return certs, total

    async def get_certificate(
        self,
        certificate_id: int,
        *,
        collection_id: int | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {
            "verbose": 2,
            "includeMetadata": "true",
            "includeLocations": "true",
        }
        if collection_id is not None:
            params["collectionId"] = collection_id
        resp = await self._request(
            "GET",
            f"/Certificates/{certificate_id}",
            params=params,
        )
        return resp.json()

    async def enroll_csr(self, payload: dict[str, Any]) -> dict[str, Any]:
        resp = await self._request("POST", "/Enrollment/CSR", json_body=payload)
        return resp.json()

    async def enroll_pfx(self, payload: dict[str, Any], *, replace_existing: bool = False) -> dict[str, Any]:
        extra_headers = {"X-CertificateFormat": "REPLACE"} if replace_existing else None
        resp = await self._request("POST", "/Enrollment/PFX", json_body=payload, extra_headers=extra_headers)
        return resp.json()

    async def renew_certificate(self, payload: dict[str, Any], *, collection_id: int | None = None) -> dict[str, Any]:
        # Keyfactor scopes collection permissions off the collectionId query
        # param, not the body — a collection-scoped service role 403s without it.
        params = {"collectionId": collection_id} if collection_id is not None else None
        resp = await self._request("POST", "/Enrollment/Renew", params=params, json_body=payload)
        return resp.json()

    async def revoke_certificate(self, payload: dict[str, Any], *, collection_id: int | None = None) -> None:
        params = {"collectionId": collection_id} if collection_id is not None else None
        await self._request("POST", "/Certificates/Revoke", params=params, json_body=payload)

    async def update_metadata(self, payload: dict[str, Any]) -> None:
        await self._request("PUT", "/Certificates/Metadata", json_body=payload)

    async def delete_certificate(self, certificate_id: int, *, collection_id: int | None = None) -> None:
        params = {"collectionId": collection_id} if collection_id is not None else None
        await self._request("DELETE", f"/Certificates/{certificate_id}", params=params)

    async def download_certificate(
        self,
        certificate_id: int,
        *,
        file_format: str = "PEM",
        include_chain: bool = True,
        chain_order: str = "EndEntityFirst",
        collection_id: int | None = None,
        pfx_password: str | None = None,
    ) -> bytes:
        """Download a certificate in the specified format (PEM, CER, CRT, DER, P7B, PFX)."""
        payload: dict[str, Any] = {
            "CertID": certificate_id,
            "IncludeChain": include_chain,
            "ChainOrder": chain_order,
        }
        if collection_id is not None:
            payload["CollectionId"] = collection_id
        if file_format.upper() == "PFX" and pfx_password:
            payload["Password"] = pfx_password
        url = f"{self._base_url()}/Certificates/Download"
        # Collection-scoped permissions are evaluated off the collectionId query param.
        params = {"collectionId": collection_id} if collection_id is not None else None
        token = await self._tokens.get_token()
        headers = {
            **self._headers(token),
            "X-CertificateFormat": file_format,
            "Accept": "application/octet-stream",
        }
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(settings.KEYFACTOR_TIMEOUT_SECONDS),
            verify=settings.KEYFACTOR_VERIFY_SSL,
        ) as client:
            resp = await client.post(
                url,
                params=params,
                json=payload,
                headers=headers,
            )
        if resp.status_code >= 400:
            self._raise_for_status(resp)
        return resp.content

    async def get_collections(self) -> list[dict[str, Any]]:
        """Return all certificate collections the service principal can see."""
        params: dict[str, Any] = {
            "pq.returnLimit": 5000,
            "pq.pageReturned": 1,
        }
        resp = await self._request("GET", "/CertificateCollections", params=params)
        data = resp.json()
        return data if isinstance(data, list) else []

    async def get_enrollment_templates(self) -> list[dict[str, Any]]:
        """Return available certificate enrollment templates."""
        resp = await self._request("GET", "/Templates")
        data = resp.json()
        return data if isinstance(data, list) else []

    async def get_certificate_authorities(self) -> list[dict[str, Any]]:
        """Return available CAs for enrollment."""
        resp = await self._request("GET", "/CertificateAuthority")
        data = resp.json()
        return data if isinstance(data, list) else []


# Module-level singleton token provider so the token cache is shared across
# request-scoped client instances.
_shared_token_provider = KeyfactorTokenProvider()


def get_keyfactor_client() -> KeyfactorClient:
    return KeyfactorClient(token_provider=_shared_token_provider)
