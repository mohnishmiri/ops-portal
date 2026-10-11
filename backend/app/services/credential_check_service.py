"""Credential checks — "does this password / token still work?"

Operators here own mechIDs, ITSERVICES domain accounts, AAF identities and
JFrog tokens whose passwords expire on their own schedules.  The portal
already *tracks* those expiry dates (Infrastructure Alerts → Expiry
Tracking); this service answers the other half of the question: the date
says it is still good, but does the credential actually authenticate today?

A distinguishing AD bind result is the point of the tool.  "Wrong password"
and "password expired" and "account locked" are three very different
operational answers, and the AD sub-codes below separate them.

Safeguards.  These are what keep this a self-service check rather than a
credential-testing harness, and they are deliberate:

* **One account per request.**  There is no bulk, list or file input, and
  none should ever be added.
* **WRITE role plus the ``credential_check`` capability** — the operation is
  revocable on its own from the Permissions UI.
* **A per-user rate limit** counted in ``audit_logs``, so it holds across
  every uvicorn worker and replica rather than per process.
* **An account-lockout guard**: repeated failures against the *same* target
  are refused before they reach the directory, because a failed LDAP bind
  counts against the AD lockout policy and a careless retry loop would lock
  the very account the user is trying to verify.
* **Every attempt is audited** — who checked which target, and the outcome.
  The secret itself is never logged, never stored and never echoed back.
"""

from __future__ import annotations

import asyncio
import contextlib
import re
import ssl
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from functools import lru_cache
from typing import Literal

import certifi
import httpx
import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.auth import UserContext
from app.models.database import AuditLog

logger = structlog.get_logger(__name__)

# ldap3 is an optional import: the backend must still start (and every other
# check must still work) in an environment where it was not installed.
try:  # pragma: no cover - import guard
    from ldap3 import Connection, Server, Tls
    from ldap3.core.exceptions import LDAPException

    LDAP_AVAILABLE = True
except ModuleNotFoundError:  # pragma: no cover - import guard
    Connection = Server = Tls = None  # type: ignore[assignment]
    LDAPException = Exception  # type: ignore[assignment,misc]
    LDAP_AVAILABLE = False


AUDIT_ACTION = "credential_check"
AUDIT_RESOURCE_TYPE = "credential_check"

CheckKind = Literal["domain", "jfrog", "aaf"]

# Rate limits.  Counted from audit_logs so they are shared by every worker
# and replica — a per-process counter would multiply by workers x replicas
# exactly the way the rate-limit middleware used to.
_MAX_CHECKS_PER_WINDOW = 10
_WINDOW_MINUTES = 10
# A failed bind counts against the AD lockout policy, so the same target is
# cut off well before the directory's own threshold.
_MAX_FAILURES_PER_TARGET = 3
_TARGET_WINDOW_MINUTES = 15

# AD returns the real reason as a sub-code inside the bind diagnostic, e.g.
# "...data 532, v4563".  Without this mapping every one of these looks
# identical to the caller ("invalid credentials"), which is precisely the
# distinction an expiry check exists to make.
_AD_SUBCODES: dict[str, tuple[str, str]] = {
    "525": ("invalid", "No such user in this domain."),
    "52e": ("invalid", "Incorrect password."),
    "530": ("denied", "Correct password, but this account may not sign in at this time of day."),
    "531": ("denied", "Correct password, but this account may not sign in from this host."),
    "532": ("expired", "The password is correct but has expired and must be changed."),
    "533": ("disabled", "The account is disabled."),
    "701": ("expired", "The account itself has expired."),
    "773": ("must_change", "The password is correct but must be changed before next sign-in."),
    "775": ("locked", "The account is locked out."),
}
_SUBCODE_RE = re.compile(r"data\s+([0-9a-fA-F]{3,4})")

# Status values the UI knows how to colour.  "error" covers anything that
# says nothing about the credential itself (DNS, TLS, timeout).
VALID = "valid"
INVALID = "invalid"


@dataclass
class CheckOutcome:
    """Result of one credential check.  Never carries the secret."""

    valid: bool
    status: str
    message: str
    details: dict = field(default_factory=dict)


class CredentialCheckError(Exception):
    """Refused before any credential left the portal (rate limit, config)."""

    def __init__(self, message: str, *, status: str = "refused") -> None:
        super().__init__(message)
        self.status = status


# ── TLS / transport ────────────────────────────────────────────────────


@lru_cache(maxsize=4)
def _ssl_context_with_bundle(ca_bundle: str) -> ssl.SSLContext:
    ctx = ssl.create_default_context(cafile=certifi.where())
    ctx.load_verify_locations(cafile=ca_bundle)
    return ctx


def _verify() -> ssl.SSLContext | bool:
    """TLS verification for outbound JFrog / AAF calls.

    Mirrors the Keyfactor client: a TLS-inspecting proxy in the path needs
    the corporate root added, not verification turned off.
    """
    bundle = settings.CRED_CHECK_CA_BUNDLE.strip()
    if not bundle:
        return True
    try:
        return _ssl_context_with_bundle(bundle)
    except (OSError, ssl.SSLError) as exc:
        raise CredentialCheckError(
            "CRED_CHECK_CA_BUNDLE could not be loaded as a PEM CA file.",
            status="unconfigured",
        ) from exc


def _transport_outcome(target_name: str, exc: Exception) -> CheckOutcome:
    """A transport failure says nothing about the credential — never 'invalid'."""
    text = str(exc)
    if isinstance(exc, httpx.TimeoutException):
        message = f"Timed out contacting {target_name}."
    elif "CERTIFICATE_VERIFY_FAILED" in text:
        message = (
            f"TLS verification failed contacting {target_name}. If a TLS-inspecting proxy is in "
            "the path, set CRED_CHECK_CA_BUNDLE to the corporate root CA."
        )
    else:
        message = f"Could not reach {target_name}. The credential was not checked."
    return CheckOutcome(valid=False, status="error", message=message)


# ── Service ────────────────────────────────────────────────────────────


class CredentialCheckService:
    """Validates one credential at a time against the directory it lives in."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # ── Guards ─────────────────────────────────────────────────────────

    async def assert_within_limits(self, user: UserContext, target: str) -> None:
        """Refuse before the credential leaves the portal.

        Two independent counts, both read from ``audit_logs`` so they are
        deployment-wide: how much this user has checked lately, and how often
        this particular target has just failed.
        """
        now = datetime.utcnow()

        recent = (
            await self.db.execute(
                select(func.count())
                .select_from(AuditLog)
                .where(AuditLog.action == AUDIT_ACTION)
                .where(AuditLog.user_id == user.user_id)
                .where(AuditLog.timestamp >= now - timedelta(minutes=_WINDOW_MINUTES))
            )
        ).scalar_one()

        if recent >= _MAX_CHECKS_PER_WINDOW:
            raise CredentialCheckError(
                f"Too many credential checks — up to {_MAX_CHECKS_PER_WINDOW} every "
                f"{_WINDOW_MINUTES} minutes. Try again shortly.",
                status="rate_limited",
            )

        failures = (
            await self.db.execute(
                select(func.count())
                .select_from(AuditLog)
                .where(AuditLog.action == AUDIT_ACTION)
                .where(AuditLog.resource_id == target)
                .where(AuditLog.status == "failure")
                .where(AuditLog.timestamp >= now - timedelta(minutes=_TARGET_WINDOW_MINUTES))
            )
        ).scalar_one()

        if failures >= _MAX_FAILURES_PER_TARGET:
            raise CredentialCheckError(
                f"{target} has already failed {failures} checks in the last "
                f"{_TARGET_WINDOW_MINUTES} minutes. Further attempts are blocked here so they "
                "cannot lock the account out. Reset the password, or wait for the window to pass.",
                status="lockout_guard",
            )

    async def record(
        self,
        *,
        user: UserContext,
        ip: str | None,
        kind: CheckKind,
        target: str,
        outcome: CheckOutcome,
    ) -> None:
        """Audit the attempt.  Called for every outcome, including refusals."""
        self.db.add(
            AuditLog(
                user_id=user.user_id,
                user_email=user.email,
                action=AUDIT_ACTION,
                resource_type=AUDIT_RESOURCE_TYPE,
                resource_id=target,
                details={
                    "page": "CredentialCheckPage",
                    "feature": "credential-check",
                    "kind": kind,
                    "status": outcome.status,
                    "message": outcome.message,
                    **outcome.details,
                },
                ip_address=ip,
                status="success" if outcome.valid else "failure",
            )
        )
        try:
            await self.db.commit()
        except Exception as exc:
            await self.db.rollback()
            logger.warning("credential_check_audit_failed", kind=kind, error=str(exc)[:200])

    # ── Domain (Active Directory over LDAPS) ───────────────────────────

    async def check_domain(self, domain: str, username: str, password: str) -> CheckOutcome:
        """Simple bind as ``DOMAIN\\user``.  The bind is the whole check."""
        server_url = {
            "ITSERVICES": settings.CRED_CHECK_LDAP_ITSERVICES,
            "TESTITSERVICES": settings.CRED_CHECK_LDAP_TESTITSERVICES,
        }.get(domain, "").strip()

        if not server_url:
            raise CredentialCheckError(
                f"No LDAP server is configured for {domain}. Set CRED_CHECK_LDAP_{domain}.",
                status="unconfigured",
            )
        if not LDAP_AVAILABLE:
            raise CredentialCheckError(
                "Domain checks need the ldap3 package, which is not installed in this build.",
                status="unconfigured",
            )

        return await asyncio.to_thread(self._bind, server_url, f"{domain}\\{username}", password)

    def _bind(self, server_url: str, bind_user: str, password: str) -> CheckOutcome:
        """Blocking LDAP bind — always called through ``asyncio.to_thread``."""
        try:
            ca_file = settings.CRED_CHECK_CA_BUNDLE.strip() or certifi.where()
            tls = Tls(validate=ssl.CERT_REQUIRED, ca_certs_file=ca_file)
            server = Server(
                server_url,
                use_ssl=server_url.lower().startswith("ldaps://"),
                tls=tls,
                connect_timeout=settings.CRED_CHECK_TIMEOUT_SECONDS,
            )
            conn = Connection(
                server,
                user=bind_user,
                password=password,
                auto_bind=False,
                receive_timeout=settings.CRED_CHECK_TIMEOUT_SECONDS,
            )
            bound = conn.bind()
        except LDAPException as exc:
            logger.warning("credential_check_ldap_transport_failed", error=str(exc)[:200])
            domain_name = bind_user.split("\\")[0]
            return CheckOutcome(
                valid=False,
                status="error",
                message=f"Could not reach the {domain_name} directory. The password was not checked.",
            )

        if bound:
            with contextlib.suppress(LDAPException):
                conn.unbind()
            return CheckOutcome(
                valid=True,
                status=VALID,
                message="The password is correct and the account can sign in.",
            )

        # Not bound: read the sub-code before falling back to a generic answer.
        diagnostic = str(getattr(conn, "result", {}) or {})
        match = _SUBCODE_RE.search(diagnostic)
        if match:
            status, message = _AD_SUBCODES.get(match.group(1).lower(), (INVALID, "The password was rejected."))
            return CheckOutcome(valid=False, status=status, message=message, details={"ad_subcode": match.group(1)})
        return CheckOutcome(valid=False, status=INVALID, message="The password was rejected by the directory.")

    # ── JFrog Artifactory token ────────────────────────────────────────

    async def check_jfrog(self, token: str) -> CheckOutcome:
        """A token is valid when Artifactory answers an authenticated read."""
        base = settings.CRED_CHECK_JFROG_URL.strip().rstrip("/")
        if not base:
            raise CredentialCheckError("No JFrog URL is configured. Set CRED_CHECK_JFROG_URL.", status="unconfigured")

        url = f"{base}/artifactory/api/system/version"
        try:
            async with httpx.AsyncClient(timeout=settings.CRED_CHECK_TIMEOUT_SECONDS, verify=_verify()) as client:
                response = await client.get(url, headers={"Authorization": f"Bearer {token}"})
        except httpx.HTTPError as exc:
            return _transport_outcome("JFrog Artifactory", exc)

        if response.status_code == 200:
            version = ""
            with contextlib.suppress(ValueError):
                version = str(response.json().get("version", ""))
            return CheckOutcome(
                valid=True,
                status=VALID,
                message="The token is valid and Artifactory accepted it.",
                details={"artifactory_version": version} if version else {},
            )
        if response.status_code in (401, 403):
            return CheckOutcome(
                valid=False,
                status=INVALID,
                message="Artifactory rejected the token — it is wrong, revoked or expired.",
            )
        return CheckOutcome(
            valid=False,
            status="error",
            message=f"Artifactory answered HTTP {response.status_code}; the token could not be checked.",
        )

    # ── AAF account ────────────────────────────────────────────────────

    async def check_aaf(self, environment: str, account: str, password: str) -> CheckOutcome:
        """AAF basic auth: 200 means the credential is good, 401/403 means it is not."""
        configured = settings.CRED_CHECK_AAF_URL_PROD if environment == "prod" else settings.CRED_CHECK_AAF_URL_NONPROD
        base = configured.strip().rstrip("/")
        if not base:
            raise CredentialCheckError(
                f"No AAF URL is configured for {environment}. Set CRED_CHECK_AAF_URL_"
                f"{'PROD' if environment == 'prod' else 'NONPROD'}.",
                status="unconfigured",
            )

        url = f"{base}{settings.CRED_CHECK_AAF_PATH}"
        try:
            async with httpx.AsyncClient(timeout=settings.CRED_CHECK_TIMEOUT_SECONDS, verify=_verify()) as client:
                response = await client.get(url, auth=(account, password))
        except httpx.HTTPError as exc:
            return _transport_outcome("AAF", exc)

        if response.status_code == 200:
            return CheckOutcome(valid=True, status=VALID, message="AAF accepted the credential.")
        if response.status_code in (401, 403):
            return CheckOutcome(
                valid=False,
                status=INVALID,
                message="AAF rejected the credential — the password is wrong or has expired.",
            )
        return CheckOutcome(
            valid=False,
            status="error",
            message=f"AAF answered HTTP {response.status_code}; the credential could not be checked.",
        )

    # ── History ────────────────────────────────────────────────────────

    async def history(self, user: UserContext, *, limit: int = 200) -> list[dict]:
        """Past checks: the caller's own, or everyone's for a Super Admin."""
        stmt = (
            select(AuditLog)
            .where(AuditLog.action == AUDIT_ACTION)
            .order_by(AuditLog.timestamp.desc(), AuditLog.id.desc())
            .limit(limit)
        )
        if not user.is_admin:
            stmt = stmt.where(AuditLog.user_id == user.user_id)

        rows = (await self.db.execute(stmt)).scalars().all()
        return [
            {
                "id": row.id,
                "checked_at": row.timestamp.isoformat() if row.timestamp else None,
                "user_email": row.user_email,
                "target": row.resource_id,
                "kind": (row.details or {}).get("kind", ""),
                "status": (row.details or {}).get("status", row.status),
                "message": (row.details or {}).get("message", ""),
                "valid": row.status == "success",
            }
            for row in rows
        ]
