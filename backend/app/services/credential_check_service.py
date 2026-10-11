"""Credential checks — "does this password / token still work?"

Operators here own mechIDs, ITSERVICES domain accounts, AAF identities and
JFrog tokens whose passwords expire on their own schedules.  Compliance ->
Expiry Tracking already *tracks* those dates; this answers the other half of
the question: the date says it is still good, but does the credential
actually authenticate today?

A distinguishing AD bind result is the point of the tool.  "Wrong password",
"password expired" and "account locked" are three very different operational
answers, and the AD sub-codes below separate them.

Nothing is persisted.  A check is a question asked and answered: no audit
row, no history, no record of the credential or the result.  The secret is
held only for the duration of the call and is never logged.

The one piece of state kept is the **lockout guard** below, in memory.  A
failed LDAP bind counts against the Active Directory lockout policy, so a
careless retry loop would lock the very account the user is verifying.  The
guard pauses a target after a few consecutive failures.  It is per process
(so several workers each allow their own few attempts) and resets on
restart; the threshold is deliberately far below a normal AD lockout
threshold so that even multiplied across workers it stays safe.
"""

from __future__ import annotations

import asyncio
import contextlib
import re
import ssl
import time
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Literal

import certifi
import httpx
import structlog

from app.core.config import settings

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


CheckKind = Literal["domain", "jfrog", "aaf"]

# Lockout guard.  Consecutive failures against one target before the portal
# stops trying, and how long that pause lasts.
_MAX_FAILURES_PER_TARGET = 3
_TARGET_BLOCK_SECONDS = 15 * 60

# target -> (consecutive failures, monotonic time of the most recent failure)
_failures: dict[str, tuple[int, float]] = {}

# AD returns the real reason as a sub-code inside the bind diagnostic, e.g.
# "...data 532, v4563".  Without this mapping every one of these looks
# identical to the caller ("invalid credentials"), which is precisely the
# distinction this tool exists to make.
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
    """Refused before any credential left the portal (lockout guard, config)."""

    def __init__(self, message: str, *, status: str = "refused") -> None:
        super().__init__(message)
        self.status = status


# ── Lockout guard ──────────────────────────────────────────────────────


def assert_target_not_blocked(target: str) -> None:
    """Refuse a target that has just failed repeatedly.

    Checked before any credential leaves the portal, because the risk being
    managed is the directory locking the account, not the portal's own load.
    """
    entry = _failures.get(target)
    if entry is None:
        return

    count, last_seen = entry
    if time.monotonic() - last_seen > _TARGET_BLOCK_SECONDS:
        _failures.pop(target, None)
        return

    if count >= _MAX_FAILURES_PER_TARGET:
        minutes = _TARGET_BLOCK_SECONDS // 60
        raise CredentialCheckError(
            f"{target} has failed {count} checks in a row. Further attempts are paused for up to "
            f"{minutes} minutes so they cannot lock the account out. Reset the password, or wait.",
            status="lockout_guard",
        )


def record_outcome(target: str, outcome: CheckOutcome) -> None:
    """Feed the guard.

    Only a verdict about the credential counts.  A transport failure says
    nothing about the password, so it must not push a target toward a pause.
    """
    if outcome.status == "error":
        return
    if outcome.valid:
        _failures.pop(target, None)
        return
    count = _failures.get(target, (0, 0.0))[0]
    _failures[target] = (count + 1, time.monotonic())


def reset_guard() -> None:
    """Clear the guard — tests only."""
    _failures.clear()


# ── TLS / transport ────────────────────────────────────────────────────


@lru_cache(maxsize=4)
def _tls_context(ca_bundle: str) -> ssl.SSLContext:
    """Trust the host's own CA store first, then public roots, then any override.

    Internal services (a domain controller, AAF) present certificates from the
    corporate PKI, which is in the host/container trust store but *not* in
    certifi.  Verifying against certifi alone fails the handshake before any
    credential is sent — and looks indistinguishable from the host being down.
    Loading the system store first fixes that without weakening verification;
    certifi is added so publicly-issued certificates still validate on a host
    with a sparse CA store.
    """
    ctx = ssl.create_default_context()  # system trust store
    with contextlib.suppress(OSError, ssl.SSLError):
        ctx.load_verify_locations(cafile=certifi.where())
    if ca_bundle:
        ctx.load_verify_locations(cafile=ca_bundle)
    return ctx


def _verify() -> ssl.SSLContext:
    """TLS verification for outbound JFrog / AAF calls."""
    bundle = settings.CRED_CHECK_CA_BUNDLE.strip()
    try:
        return _tls_context(bundle)
    except (OSError, ssl.SSLError) as exc:
        raise CredentialCheckError(
            "CRED_CHECK_CA_BUNDLE could not be loaded as a PEM CA file.",
            status="unconfigured",
        ) from exc


def _transport_reason(exc: Exception) -> str:
    """Plain-language cause of a connection failure.

    "Could not reach it" is not actionable: a DNS miss, a refused port, a
    firewall drop and a TLS-inspecting proxy need four different fixes.  All
    of these are reached only by an authenticated WRITE user against hosts
    the operator configured, so naming the cause leaks nothing useful.
    """
    text = str(exc)
    lowered = text.lower()
    if isinstance(exc, httpx.TimeoutException) or "timed out" in lowered or "timeout" in lowered:
        return "the connection timed out — the host may be firewalled from the portal"
    if "certificate_verify_failed" in lowered or "certificate verify failed" in lowered:
        return (
            "TLS verification failed — if a TLS-inspecting proxy is in the path, point "
            "CRED_CHECK_CA_BUNDLE at the corporate root CA"
        )
    if any(
        marker in lowered
        for marker in ("nodename nor servname", "name or service not known", "getaddrinfo", "name resolution")
    ):
        return "the hostname did not resolve (DNS)"
    if "refused" in lowered:
        return "the connection was refused — nothing is listening on that port"
    if "no route to host" in lowered or "network is unreachable" in lowered:
        return "the host is unreachable from the portal"
    return text[:200] if text else "no further detail was reported"


def _transport_outcome(target_name: str, target_url: str, exc: Exception) -> CheckOutcome:
    """A transport failure says nothing about the credential — never 'invalid'."""
    reason = _transport_reason(exc)
    logger.warning(
        "credential_check_transport_failed",
        target=target_name,
        url=target_url,
        error=str(exc)[:300],
    )
    return CheckOutcome(
        valid=False,
        status="error",
        message=f"Could not reach {target_name} at {target_url} — {reason}. The credential was not checked.",
    )


# ── Service ────────────────────────────────────────────────────────────


class CredentialCheckService:
    """Validates one credential at a time against the directory it lives in.

    Stateless and dependency-free: it holds no database session because it
    writes nothing.
    """

    # ── Domain (Active Directory over LDAPS) ───────────────────────────

    async def check_domain(self, domain: str, username: str, password: str) -> CheckOutcome:
        """Simple bind as ``DOMAIN\\user``.  The bind is the whole check."""
        server_url = {
            "ITSERVICES": settings.CRED_CHECK_LDAP_ITSERVICES,
            "TESTITSERVICES": settings.CRED_CHECK_LDAP_TESTITSERVICES,
        }.get(domain, "").strip()

        if not server_url:
            raise CredentialCheckError(
                f"No LDAP server is configured for {domain}. Set CRED_CHECK_LDAP_{domain} to the domain "
                f"controller, e.g. ldaps://dc.example.com:636, and restart the backend.",
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
            # None = the system trust store, which is where the corporate
            # root lives.  Pinning certifi here rejected every internal DC.
            ca_file = settings.CRED_CHECK_CA_BUNDLE.strip() or None
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
            domain_name = bind_user.split("\\")[0]
            reason = _transport_reason(exc)
            logger.warning(
                "credential_check_ldap_transport_failed",
                domain=domain_name,
                server=server_url,
                error=str(exc)[:300],
            )
            return CheckOutcome(
                valid=False,
                status="error",
                message=(
                    f"Could not reach the {domain_name} directory at {server_url} — {reason}. "
                    "The password was not checked."
                ),
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

    # ── JFrog Artifactory ──────────────────────────────────────────────

    async def check_jfrog(self, username: str, token: str) -> CheckOutcome:
        """Username + token, checked with basic auth against Artifactory.

        Basic auth rather than a bearer header: an Artifactory identity token
        or API key belongs to a named user and is presented alongside it, and
        the same call still works when an access token is used as the
        password.
        """
        base = settings.CRED_CHECK_JFROG_URL.strip().rstrip("/")
        if not base:
            raise CredentialCheckError("No JFrog URL is configured. Set CRED_CHECK_JFROG_URL.", status="unconfigured")

        url = f"{base}/artifactory/api/system/version"
        try:
            async with httpx.AsyncClient(timeout=settings.CRED_CHECK_TIMEOUT_SECONDS, verify=_verify()) as client:
                response = await client.get(url, auth=(username, token))
        except httpx.HTTPError as exc:
            return _transport_outcome("JFrog Artifactory", url, exc)

        if response.status_code == 200:
            version = ""
            with contextlib.suppress(ValueError):
                version = str(response.json().get("version", ""))
            return CheckOutcome(
                valid=True,
                status=VALID,
                message="Artifactory accepted the username and token.",
                details={"artifactory_version": version} if version else {},
            )
        if response.status_code in (401, 403):
            return CheckOutcome(
                valid=False,
                status=INVALID,
                message="Artifactory rejected it — the username or token is wrong, revoked or expired.",
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
            return _transport_outcome("AAF", url, exc)

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
