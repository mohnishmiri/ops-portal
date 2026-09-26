"""
Security foundation — SEC01a.

This module provides:
- Capability codes for authorization
- CSRF token generation and validation
- Security headers middleware
- Configured actor mode indicator

Architecture rules (section 28):
- Application capabilities, not enterprise roles
- Local configured-actor mode must be visibly non-production
- CSRF protection for all state-changing routes
- Security headers for all responses
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import time
from collections.abc import Callable
from enum import Enum
from typing import Any

from fastapi import HTTPException, Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

# ---------------------------------------------------------------------------
# Capability codes
# ---------------------------------------------------------------------------


class Capability(str, Enum):
    """
    Application capability codes for the first slice.

    These are application-level capabilities, not final enterprise roles.
    The configured-actor mode receives an explicit configured capability set.
    """

    APPLICATION_CREATE = "APPLICATION_CREATE"
    INTAKE_CREATE = "INTAKE_CREATE"
    ANSWER_EDIT = "ANSWER_EDIT"
    ANSWER_CONFIRM = "ANSWER_CONFIRM"
    EVIDENCE_UPLOAD = "EVIDENCE_UPLOAD"
    CANDIDATE_REVIEW = "CANDIDATE_REVIEW"
    AI_MAPPING_RUN = "AI_MAPPING_RUN"
    WAVEUTIL_REVIEW = "WAVEUTIL_REVIEW"
    INTAKE_FREEZE = "INTAKE_FREEZE"
    CATALOG_MANAGE = "CATALOG_MANAGE"
    TOPOLOGY_APPROVE = "TOPOLOGY_APPROVE"
    TOPOLOGY_BASE_UPLOAD = "TOPOLOGY_BASE_UPLOAD"
    TOPOLOGY_BASE_REVIEW = "TOPOLOGY_BASE_REVIEW"
    TOPOLOGY_GENERATE = "TOPOLOGY_GENERATE"
    TOPOLOGY_ARTIFACT_DOWNLOAD = "TOPOLOGY_ARTIFACT_DOWNLOAD"
    TOPOLOGY_RUN_APPROVE = "TOPOLOGY_RUN_APPROVE"
    TOPOLOGY_RUN_REJECT = "TOPOLOGY_RUN_REJECT"
    TOPOLOGY_RUN_SUPERSEDE = "TOPOLOGY_RUN_SUPERSEDE"
    TEMPLATE_MANAGE = "TEMPLATE_MANAGE"


# Default capabilities for configured-actor mode (development/testing)
CONFIGURED_ACTOR_CAPABILITIES: frozenset[Capability] = frozenset(Capability)


def has_capability(actor_capabilities: set[str], required: Capability) -> bool:
    """Check if the actor has the required capability."""
    return required.value in actor_capabilities


def require_capability(actor_capabilities: set[str], required: Capability) -> None:
    """Raise HTTPException 403 if the actor lacks the required capability."""
    if not has_capability(actor_capabilities, required):
        raise HTTPException(
            status_code=403,
            detail=f"Missing required capability: {required.value}",
        )


# ---------------------------------------------------------------------------
# CSRF protection
# ---------------------------------------------------------------------------

# CSRF token validity period (1 hour)
CSRF_TOKEN_VALIDITY_SECONDS = 3600

# CSRF secret key - in production, this should come from environment
# For now, we generate a random key per process (acceptable for single-instance dev)
_csrf_secret: bytes | None = None


def _get_csrf_secret() -> bytes:
    """Get or generate the CSRF secret key."""
    global _csrf_secret
    if _csrf_secret is None:
        _csrf_secret = secrets.token_bytes(32)
    return _csrf_secret


def set_csrf_secret(secret: bytes) -> None:
    """Set the CSRF secret key (for testing or production configuration)."""
    global _csrf_secret
    _csrf_secret = secret


def generate_csrf_token(session_id: str | None = None) -> str:
    """
    Generate a CSRF token.

    The token includes a timestamp for expiration checking.
    Format: timestamp.signature

    Args:
        session_id: Optional session identifier for binding token to session

    Returns:
        CSRF token string
    """
    timestamp = str(int(time.time()))
    data = f"{timestamp}:{session_id or ''}"
    signature = hmac.new(
        _get_csrf_secret(),
        data.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return f"{timestamp}.{signature}"


def validate_csrf_token(
    token: str,
    session_id: str | None = None,
    max_age: int = CSRF_TOKEN_VALIDITY_SECONDS,
) -> bool:
    """
    Validate a CSRF token.

    Args:
        token: The CSRF token to validate
        session_id: Optional session identifier for binding validation
        max_age: Maximum token age in seconds

    Returns:
        True if valid, False otherwise
    """
    if not token or "." not in token:
        return False

    try:
        timestamp_str, signature = token.split(".", 1)
        timestamp = int(timestamp_str)
    except (ValueError, AttributeError):
        return False

    # Check expiration
    if time.time() - timestamp > max_age:
        return False

    # Verify signature
    data = f"{timestamp_str}:{session_id or ''}"
    expected_signature = hmac.new(
        _get_csrf_secret(),
        data.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    return hmac.compare_digest(signature, expected_signature)


def get_csrf_token_from_request(request: Request) -> str | None:
    """
    Extract CSRF token from request.

    Checks:
    1. Form field '_csrf_token'
    2. Header 'X-CSRF-Token' (for HTMX/AJAX)
    """
    # Check form data (if available)
    if hasattr(request, "_form") and request._form:
        token = request._form.get("_csrf_token")
        if token:
            return token

    # Check header
    return request.headers.get("X-CSRF-Token")


async def require_csrf_token(request: Request) -> None:
    """
    Dependency that validates CSRF token for state-changing requests.

    Raises HTTPException 403 if token is missing or invalid.
    """
    # Only check for state-changing methods
    if request.method in ("GET", "HEAD", "OPTIONS"):
        return

    # Get form data
    form = await request.form()
    token = form.get("_csrf_token") or request.headers.get("X-CSRF-Token")

    if not token:
        raise HTTPException(
            status_code=403,
            detail="CSRF token missing",
        )

    if not validate_csrf_token(str(token)):
        raise HTTPException(
            status_code=403,
            detail="CSRF token invalid or expired",
        )


# ---------------------------------------------------------------------------
# Security headers middleware
# ---------------------------------------------------------------------------

# Security headers for all responses
SECURITY_HEADERS = {
    # Prevent MIME type sniffing
    "X-Content-Type-Options": "nosniff",
    # Prevent clickjacking
    "X-Frame-Options": "DENY",
    # Control referrer information
    "Referrer-Policy": "strict-origin-when-cross-origin",
    # Prevent XSS (legacy, but still useful)
    "X-XSS-Protection": "1; mode=block",
}

# Additional headers for sensitive pages (forms, user data)
SENSITIVE_PAGE_HEADERS = {
    **SECURITY_HEADERS,
    # Prevent caching of sensitive data
    "Cache-Control": "private, no-store, must-revalidate",
    "Pragma": "no-cache",
}

# Content Security Policy for HTML pages
CSP_POLICY = (
    "default-src 'self'; "
    "script-src 'self'; "
    "style-src 'self' 'unsafe-inline'; "  # unsafe-inline needed for some CSS
    "img-src 'self' data:; "
    "font-src 'self'; "
    "form-action 'self'; "
    "frame-ancestors 'none'; "
    "base-uri 'self'"
)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Middleware that adds security headers to all responses."""

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Any]
    ) -> Response:
        response = await call_next(request)

        # Add base security headers
        for header, value in SECURITY_HEADERS.items():
            response.headers[header] = value

        # Add CSP for HTML responses
        content_type = response.headers.get("content-type", "")
        if "text/html" in content_type:
            response.headers["Content-Security-Policy"] = CSP_POLICY

        return response


def add_sensitive_headers(response: Response) -> Response:
    """Add sensitive page headers to a response."""
    for header, value in SENSITIVE_PAGE_HEADERS.items():
        response.headers[header] = value
    return response


# ---------------------------------------------------------------------------
# Configured actor mode indicator
# ---------------------------------------------------------------------------


def is_configured_actor_mode(app_env: str = "local") -> bool:
    """
    Check if running in configured-actor mode (non-production).

    In production, this would check for SSO/enterprise auth.
    For now, we're always in configured-actor mode.
    """
    return app_env in {"local", "test"}


def get_non_production_indicator(app_env: str = "local") -> str:
    """
    Get a visible indicator that the system is in non-production mode.

    This should be displayed prominently in the UI.
    """
    if is_configured_actor_mode(app_env):
        return "DEVELOPMENT MODE - NOT FOR PRODUCTION USE"
    return ""
