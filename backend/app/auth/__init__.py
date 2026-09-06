"""
Azure AD (Entra ID) Authentication & RBAC Dependencies for FastAPI.

Provides:
- JWT token validation against Azure AD
- Claims extraction
- Role-based access control decorators
- Request-scoped user context
"""

import time

import httpx
import structlog
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt

from app.core.config import settings
from app.models.auth import TokenClaims, UserContext, UserRole

logger = structlog.get_logger(__name__)


def _dev_auth_enabled() -> bool:
    return settings.ENVIRONMENT == "development" and settings.DEV_AUTH_BYPASS


# Authentication dependencies decide whether a route may continue without a
# Bearer token. This lets signed browser-only dashboard launch/proxy URLs reach
# their own token validation while normal API routes still return 401.
_bearer_scheme = HTTPBearer(auto_error=False)


def _dev_user() -> UserContext:
    """Return a synthetic admin user for local development."""
    return UserContext(
        user_id="dev-user-00000000",
        object_id="00000000-0000-0000-0000-000000000000",
        display_name="Local Developer",
        email="dev@localhost",
        roles=[UserRole.ADMIN],
        raw_roles=["admin"],
        tenant_id="development",
    )


# Cache for JWKS keys — refreshed every hour or on key-not-found
_jwks_cache: dict | None = None
_jwks_cache_ts: float = 0.0
_JWKS_TTL_SECONDS: float = 3600.0  # 1 hour


async def _get_jwks(force_refresh: bool = False) -> dict:
    """Fetch and cache Azure AD JWKS (JSON Web Key Set).

    The cache has a 1-hour TTL and can be force-refreshed when a signing
    key ``kid`` is not found (Azure AD rotates keys periodically).
    """
    global _jwks_cache, _jwks_cache_ts  # noqa: PLW0603

    now = time.monotonic()
    if not force_refresh and _jwks_cache is not None and (now - _jwks_cache_ts) < _JWKS_TTL_SECONDS:
        return _jwks_cache

    openid_config_url = f"{settings.authority}/v2.0/.well-known/openid-configuration"
    # verify=False: Corporate proxy/firewall may MITM TLS connections to
    # login.microsoftonline.com, presenting a cert Python's default trust
    # store does not recognise.  The endpoint itself is a well-known
    # Microsoft URL so skipping local cert verification is acceptable.
    async with httpx.AsyncClient(verify=False) as client:
        config_resp = await client.get(openid_config_url)
        config_resp.raise_for_status()
        jwks_uri = config_resp.json()["jwks_uri"]

        jwks_resp = await client.get(jwks_uri)
        jwks_resp.raise_for_status()
        _jwks_cache = jwks_resp.json()
        _jwks_cache_ts = time.monotonic()

    logger.info("jwks_cache_refreshed", forced=force_refresh)
    return _jwks_cache


async def _decode_token(token: str) -> TokenClaims:
    """Validate and decode Azure AD JWT token."""
    try:
        jwks = await _get_jwks()

        # Get the signing key
        unverified_header = jwt.get_unverified_header(token)
        kid = unverified_header.get("kid")

        rsa_key = {}
        for key in jwks.get("keys", []):
            if key.get("kid") == kid:
                rsa_key = key
                break

        # Key not found — Azure AD may have rotated signing keys.
        # Force-refresh the JWKS cache and retry once.
        if not rsa_key:
            logger.info("jwks_kid_not_found_retrying", kid=kid)
            jwks = await _get_jwks(force_refresh=True)
            for key in jwks.get("keys", []):
                if key.get("kid") == kid:
                    rsa_key = key
                    break

        if not rsa_key:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Unable to find signing key",
            )

        payload = jwt.decode(
            token,
            rsa_key,
            algorithms=["RS256"],
            audience=settings.AZURE_CLIENT_ID,
            issuer=f"https://login.microsoftonline.com/{settings.AZURE_TENANT_ID}/v2.0",
            options={"verify_exp": True, "verify_aud": True, "verify_iss": True},
        )

        return TokenClaims(**payload)

    except JWTError as e:
        logger.warning("jwt_validation_failed", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Token validation failed: {e}",
        ) from e
    except HTTPException:
        raise
    except Exception as e:
        # Catch-all for Pydantic validation, unexpected errors, etc.
        logger.warning(
            "token_processing_failed",
            error=str(e),
            error_type=type(e).__name__,
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Token processing failed: {e}",
        ) from e


def _map_roles(raw_roles: list[str]) -> list[UserRole]:
    """Map Azure AD app roles to portal UserRole enum.

    Returns an empty list when no recognised roles are present.
    Callers must treat an empty list as "no access" in non-dev mode.
    """
    role_mapping = {
        settings.ROLE_ADMIN: UserRole.ADMIN,
        "admin": UserRole.ADMIN,
        settings.ROLE_WRITE: UserRole.WRITE,
        "write": UserRole.WRITE,
        "contributor": UserRole.WRITE,
        settings.ROLE_READ: UserRole.READ,
        "read": UserRole.READ,
        "reader": UserRole.READ,
    }

    mapped = []
    for raw in raw_roles:
        role = role_mapping.get(raw.lower()) or role_mapping.get(raw)
        if role and role not in mapped:
            mapped.append(role)

    # Only when the dev bypass is explicitly opted into do we grant a
    # fallback READ role, so local testing works without app-role
    # assignment.  Anywhere else an empty list means "no recognised app
    # role" and the caller must treat it as no portal access.
    if not mapped and _dev_auth_enabled():
        mapped.append(UserRole.READ)

    return mapped


def _is_unauthenticated_dashboard_path(path: str) -> bool:
    """True for the signed browser-only K8s dashboard launch/proxy URLs.

    Those routes carry their own HMAC-signed launch token or signed session
    cookie and validate it themselves, so they must be reachable without a
    Bearer header.  Everything else requires a token.
    """
    return path.startswith("/api/v1/aks/dashboard/") and ("/launch/" in path or "/proxy" in path)


async def get_authenticated_identity(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> UserContext | None:
    """
    FastAPI dependency: *authentication only* — proves who the caller is.

    Returns a UserContext whose ``roles`` may legitimately be empty: a valid
    corporate identity is not the same thing as portal authorization.  Callers
    that need an authorized user must use :func:`get_current_user` instead.

    This exists so the session endpoint can answer "you are authenticated but
    not authorized" instead of failing with a bare 403 the UI cannot interpret.

    Development bypass rules (deliberately narrow):
      • no Bearer token at all  → synthetic local developer
      • token present but invalid/expired → 401, never a privilege upgrade
    """
    if credentials is None:
        if _is_unauthenticated_dashboard_path(request.url.path):
            return None
        if _dev_auth_enabled():
            user = _dev_user()
            request.state.user = user
            logger.debug("dev_mode_auth_bypass", user_id=user.user_id)
            return user
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )

    # A token was supplied — it must validate on its own merits.  There is no
    # dev fallback here on purpose: silently converting a rejected token into a
    # synthetic ADMIN is a privilege-escalation path, not a convenience.
    claims = await _decode_token(credentials.credentials)

    user = UserContext(
        user_id=claims.sub,
        object_id=claims.oid,
        display_name=claims.name,
        email=claims.email or claims.preferred_username,
        roles=_map_roles(claims.roles),
        raw_roles=claims.roles,
        tenant_id=claims.tenant_id,
    )

    # Attach to request state for audit logging
    request.state.user = user
    return user


async def get_current_user(
    request: Request,
    identity: UserContext | None = Depends(get_authenticated_identity),
) -> UserContext:
    """
    FastAPI dependency: authenticated **and** portal-authorized user context.

    Authentication is delegated to :func:`get_authenticated_identity`; this
    dependency adds the portal authorization gate — an identity holding no
    recognised app role is rejected with 403.

    Usage:
        @router.get("/endpoint")
        async def endpoint(user: UserContext = Depends(get_current_user)):
            ...
    """
    if identity is None:
        # Signed dashboard launch/proxy route — it performs its own validation.
        return None

    if not identity.roles:
        logger.warning(
            "access_denied_no_roles",
            user_id=identity.user_id,
            raw_roles=identity.raw_roles,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No app role assigned. Contact your administrator to request access.",
        )

    return identity


def require_role(*roles: UserRole):  # noqa: ANN201
    """
    FastAPI dependency factory: Require specific roles.

    Usage:
        @router.post("/endpoint")
        async def endpoint(user: UserContext = Depends(require_role(UserRole.ADMIN))):
            ...
    """

    async def _role_checker(
        user: UserContext = Depends(get_current_user),
    ) -> UserContext:
        # Local dev opt-in — skip role checks entirely
        if _dev_auth_enabled():
            return user
        # ADMIN implicitly satisfies any role requirement
        if user.is_admin:
            return user
        if not any(user.has_role(r) for r in roles):
            logger.warning(
                "access_denied",
                user_id=user.user_id,
                required_roles=[r.value for r in roles],
                user_roles=[r.value for r in user.roles],
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Insufficient permissions. Required roles: {[r.value for r in roles]}",
            )
        return user

    return _role_checker


async def get_current_user_from_token(token: str | None) -> UserContext:
    """Validate Bearer token for WebSocket connections (query param or first message).

    Mirrors the HTTP path: a missing token may fall back to the synthetic
    developer only when the dev bypass is enabled, but a token that is
    present and invalid is always rejected — never upgraded.
    """
    if not token:
        if _dev_auth_enabled():
            return _dev_user()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )

    claims = await _decode_token(token)
    mapped_roles = _map_roles(claims.roles)
    if not mapped_roles:
        logger.warning("ws_access_denied_no_roles", user_id=claims.sub, raw_roles=claims.roles)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No app role assigned.",
        )
    return UserContext(
        user_id=claims.sub,
        object_id=claims.oid,
        display_name=claims.name,
        email=claims.email or claims.preferred_username,
        roles=mapped_roles,
        raw_roles=claims.roles,
        tenant_id=claims.tenant_id,
    )
