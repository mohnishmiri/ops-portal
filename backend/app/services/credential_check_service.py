"""Credential checks — "does this password / token still work?"

Operators here own mechIDs, ITSERVICES domain accounts, AAF identities and
JFrog tokens whose passwords expire on their own schedules.  Compliance ->
Expiry Tracking already *tracks* those dates; this answers the other half of
the question: the date says it is still good, but does the credential
actually authenticate today?

A distinguishing AD bind result is the point of the tool.  "Wrong password",
"password expired" and "account locked" are three very different operational
answers, and the AD sub-codes below separate them.

This service persists nothing.  A check is a question asked and answered: no
audit row, no history, no record of the credential.  The secret is held only
for the duration of the call and is never logged.  (The endpoint copies the
verdict — never the secret — onto the account's inventory row when it is
listed; see ``credential_inventory_service``.)

The one piece of state kept here is the **lockout guard** below, in memory.  A
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
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from typing import Any, Literal
from urllib.parse import quote

import certifi
import httpx
import structlog
from jose import JWTError
from jose import jwt as jose_jwt

from app.core.config import settings
from app.schemas.tools import CredentialAccountDetails

logger = structlog.get_logger(__name__)

# ldap3 is an optional import: the backend must still start (and every other
# check must still work) in an environment where it was not installed.
try:  # pragma: no cover - import guard
    from ldap3 import BASE, SUBTREE, Connection, Server, Tls
    from ldap3 import NONE as NO_SERVER_INFO
    from ldap3.core.exceptions import LDAPException
    from ldap3.utils.conv import escape_filter_chars

    LDAP_AVAILABLE = True
except ModuleNotFoundError:  # pragma: no cover - import guard
    Connection = Server = Tls = None  # type: ignore[assignment]
    BASE = SUBTREE = NO_SERVER_INFO = None  # type: ignore[assignment]
    escape_filter_chars = None  # type: ignore[assignment]
    LDAPException = Exception  # type: ignore[assignment,misc]
    LDAP_AVAILABLE = False


CheckKind = Literal["domain", "jfrog", "aaf"]
JFROG_INSTANCE_LABELS = {"bronze": "Bronze", "gold": "Gold"}

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
    # Expiry / last-use details, when the source would report them.
    account: CredentialAccountDetails | None = None


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


# ── Account details: expiry and last use ───────────────────────────────
#
# Each source is asked, after (or alongside) the verdict, what it knows about
# the credential.  This is always best effort: a refusal or an unexpected
# payload becomes a note on the result, never a different verdict.

# A details lookup is a nicety, so it gets a shorter leash than the check:
# a slow lookup must not double the wait on an unreachable host.
_DETAILS_TIMEOUT_SECONDS = 5

# A last-use time this close to "now" may have been written by the check.
_THIS_CHECK_WINDOW = timedelta(minutes=2)


def _epoch(value: Any) -> datetime | None:
    """Epoch seconds (Artifactory, JWT claims) as UTC; 0 and junk are None."""
    if isinstance(value, bool) or not isinstance(value, int | float) or value <= 0:
        return None
    try:
        return datetime.fromtimestamp(value, tz=UTC)
    except (OverflowError, OSError, ValueError):
        return None


# Active Directory stores times as FILETIME: 100 ns ticks since 1601-01-01
# UTC.  0 and the largest int64 both mean "never".
_FILETIME_EPOCH = datetime(1601, 1, 1, tzinfo=UTC)
_FILETIME_NEVER = 0x7FFFFFFFFFFFFFFF
_UF_DONT_EXPIRE_PASSWD = 0x10000

_AD_ACCOUNT_ATTRIBUTES = [
    "displayName",
    "pwdLastSet",
    # Computed by the DC, so it honours fine-grained password policies.
    "msDS-UserPasswordExpiryTimeComputed",
    "accountExpires",
    "lastLogonTimestamp",
    "userAccountControl",
]


def _filetime(value: int | None) -> datetime | None:
    if value is None or value <= 0 or value >= _FILETIME_NEVER:
        return None
    try:
        return _FILETIME_EPOCH + timedelta(microseconds=value // 10)
    except OverflowError:
        return None


def _ad_raw(entry: dict, name: str) -> bytes | None:
    """First raw value of an attribute.

    Raw rather than ldap3's formatted values, so the result does not depend
    on whether the directory schema was loaded.
    """
    for key, values in (entry.get("raw_attributes") or {}).items():
        if key.lower() == name.lower() and values:
            value = values[0]
            return value if isinstance(value, bytes) else str(value).encode()
    return None


def _ad_int(entry: dict, name: str) -> int | None:
    raw = _ad_raw(entry, name)
    try:
        return int(raw) if raw is not None else None
    except ValueError:
        return None


def _ad_text(entry: dict, name: str) -> str | None:
    raw = _ad_raw(entry, name)
    return (raw.decode("utf-8", errors="replace").strip() or None) if raw is not None else None


def _first_entry(response: Any) -> dict | None:
    """First real entry of a search, skipping referrals."""
    return next((item for item in response or [] if item.get("type") == "searchResEntry"), None)


def ad_account_details(entry: dict, *, now: datetime) -> CredentialAccountDetails:
    """Expiry, last change and last sign-in from the account's own AD entry."""
    computed = _ad_int(entry, "msDS-UserPasswordExpiryTimeComputed")
    uac = _ad_int(entry, "userAccountControl") or 0
    never_expires = computed == _FILETIME_NEVER or bool(uac & _UF_DONT_EXPIRE_PASSWD)

    # The bind is itself a sign-in.  lastLogonTimestamp is only rewritten
    # once it is 9-14 days old, so a value written seconds ago is this check
    # — which also means none had been recorded for 9+ days before it.
    last_logon = _filetime(_ad_int(entry, "lastLogonTimestamp"))
    if last_logon is None:
        last_used_at, last_used_note = None, "No earlier sign-in is recorded in the directory."
    elif now - last_logon <= _THIS_CHECK_WINDOW:
        last_used_at, last_used_note = (
            None,
            ("None recorded in the 9+ days before this check — the check itself is now the latest sign-in."),
        )
    else:
        last_used_at = last_logon
        last_used_note = "Approximate — Active Directory records sign-ins only every 9 to 14 days."

    return CredentialAccountDetails(
        display_name=_ad_text(entry, "displayName"),
        expires_at=None if never_expires else _filetime(computed),
        never_expires=never_expires,
        last_changed_at=_filetime(_ad_int(entry, "pwdLastSet")),
        last_used_at=last_used_at,
        last_used_note=last_used_note,
        account_expires_at=_filetime(_ad_int(entry, "accountExpires")),
    )


# Artifactory's record of the calling token.  GET only: DELETE on this same
# path revokes the token making the call.
_JFROG_TOKEN_INFO_PATH = "/access/api/v1/tokens/me"
_JFROG_NO_LAST_USE = "Not reported — needs Artifactory 7.108.3+ with token last-used tracking enabled."


def _jwt_claims(token: str) -> dict:
    """Unverified claims of a JWT access token; {} for any other kind.

    Used only to *describe* a token.  Whether it works is always
    Artifactory's answer, never these claims'.
    """
    try:
        claims = jose_jwt.get_unverified_claims(token)
    except JWTError:
        return {}
    return claims if isinstance(claims, dict) else {}


def jfrog_token_details(info: dict | None, claims: dict, *, now: datetime) -> CredentialAccountDetails | None:
    """Artifactory's record of the token, filled in from its own claims.

    The record wins: it is the only source of last use, and identity /
    reference tokens carry no claims at all.
    """
    if not info and not claims:
        return None
    info = info or {}

    expiry = _epoch(info.get("expiry")) or _epoch(claims.get("exp"))
    last_used = _epoch(info.get("last_used"))
    if last_used is None:
        last_used_note = _JFROG_NO_LAST_USE
    elif now - last_used <= _THIS_CHECK_WINDOW:
        last_used_note = "This may be the check itself."
    else:
        last_used_note = None

    return CredentialAccountDetails(
        display_name=str(info.get("description") or "").strip() or None,
        expires_at=expiry,
        # Artifactory omits the expiry of a non-expiring token.
        never_expires=expiry is None,
        last_changed_at=_epoch(info.get("issued_at")) or _epoch(claims.get("iat")),
        last_used_at=last_used,
        last_used_note=last_used_note,
        notes=[] if info else ["Read from the token itself — Artifactory did not return its record of it."],
    )


# CredDAO types for a password (MD5 and salted SHA-256); the rest are
# certificates and placeholders, which do not answer a basic-auth check.
_AAF_PASSWORD_TYPES = {1, 2}
_AAF_ACCEPT = "application/Users+json;charset=utf-8;version=2.1,application/json;version=2.1,*/*"
_AAF_NO_LAST_USE = "AAF does not record when a credential was last used."


def _aaf_time(value: Any) -> datetime | None:
    """AAF's xs:dateTime as UTC; epoch milliseconds accepted too."""
    if isinstance(value, int | float) and not isinstance(value, bool):
        return _epoch(value / 1000 if value > 1e11 else value)
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip())
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def aaf_account_details(payload: Any, *, now: datetime) -> CredentialAccountDetails:
    """Password expiry from AAF's credential list for one identity.

    AAF keeps one row per password (and certificate), each with its own
    expiry, and several passwords can be live at once — so when more than one
    still works, the latest is shown and the rest are named.
    """
    details = CredentialAccountDetails(last_used_note=_AAF_NO_LAST_USE)
    entries = payload.get("user") if isinstance(payload, dict) else None

    expiries: list[datetime] = []
    for entry in entries if isinstance(entries, list) else []:
        if not isinstance(entry, dict):
            continue
        try:
            kind = int(entry.get("type"))
        except (TypeError, ValueError):
            continue
        expires = _aaf_time(entry.get("expires"))
        if kind in _AAF_PASSWORD_TYPES and expires is not None and expires > now:
            expiries.append(expires)

    if not expiries:
        details.notes.append("AAF returned no current password for this identity.")
        return details

    expiries.sort()
    details.expires_at = expiries[-1]
    if len(expiries) > 1:
        dates = ", ".join(f"{when:%d %b %Y}" for when in expiries)
        details.notes.append(
            f"This identity has {len(expiries)} passwords that still work (expiring {dates}). "
            "AAF does not say which one was checked, so the latest is shown."
        )
    return details


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
                # The default downloads the whole AD schema on every bind;
                # the account details below read raw values instead.
                get_info=NO_SERVER_INFO,
            )
            conn = Connection(
                server,
                user=bind_user,
                password=password,
                auto_bind=False,
                receive_timeout=settings.CRED_CHECK_TIMEOUT_SECONDS,
                # Following a referral would present the password to another server.
                auto_referrals=False,
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
            try:
                account = self._read_ad_account(conn, bind_user.split("\\", 1)[-1])
            finally:
                with contextlib.suppress(LDAPException):
                    conn.unbind()
            return CheckOutcome(
                valid=True,
                status=VALID,
                message="The password is correct and the account can sign in.",
                account=account,
            )

        # Not bound: read the sub-code before falling back to a generic answer.
        diagnostic = str(getattr(conn, "result", {}) or {})
        match = _SUBCODE_RE.search(diagnostic)
        if match:
            status, message = _AD_SUBCODES.get(match.group(1).lower(), (INVALID, "The password was rejected."))
            return CheckOutcome(valid=False, status=status, message=message, details={"ad_subcode": match.group(1)})
        return CheckOutcome(valid=False, status=INVALID, message="The password was rejected by the directory.")

    @staticmethod
    def _read_ad_account(conn: Any, username: str) -> CredentialAccountDetails:
        """Read the account's own entry over the connection it just bound.

        Best effort: the bind has already given the verdict, and a hardened
        directory may not let an account read itself — that is a note, not a
        failure.  Only possible after a successful bind, so an expired or
        locked account gets its verdict without details.
        """
        unavailable = CredentialAccountDetails(notes=["The directory did not return details for this account."])
        try:
            conn.search("", "(objectClass=*)", search_scope=BASE, attributes=["defaultNamingContext"])
            root = _first_entry(conn.response)
            base_dn = _ad_text(root, "defaultNamingContext") if root else None
            if not base_dn:
                return unavailable
            conn.search(
                base_dn,
                f"(&(objectClass=user)(sAMAccountName={escape_filter_chars(username)}))",
                search_scope=SUBTREE,
                attributes=_AD_ACCOUNT_ATTRIBUTES,
            )
            entry = _first_entry(conn.response)
        except LDAPException as exc:
            logger.info("credential_check_ad_details_unavailable", error=str(exc)[:200])
            return unavailable
        return ad_account_details(entry, now=datetime.now(UTC)) if entry else unavailable

    # ── JFrog Artifactory ──────────────────────────────────────────────

    async def check_jfrog(self, username: str, token: str, instance: str = "bronze") -> CheckOutcome:
        """Username + token, checked with basic auth against Artifactory Bronze or Gold.

        Basic auth rather than a bearer header: an Artifactory identity token
        or API key belongs to a named user and is presented alongside it, and
        the same call still works when an access token is used as the
        password.  Bronze and Gold are separate instances with their own
        users and tokens, so a token is only ever checked where it was issued.
        """
        setting = "CRED_CHECK_JFROG_URL_GOLD" if instance == "gold" else "CRED_CHECK_JFROG_URL"
        base = str(getattr(settings, setting)).strip().rstrip("/")
        if not base:
            raise CredentialCheckError(
                f"No JFrog {JFROG_INSTANCE_LABELS[instance]} URL is configured. Set {setting}.",
                status="unconfigured",
            )

        url = f"{base}/artifactory/api/system/version"
        claims = _jwt_claims(token)
        try:
            async with httpx.AsyncClient(timeout=settings.CRED_CHECK_TIMEOUT_SECONDS, verify=_verify()) as client:
                # Before the check, not after: the check is itself a use of
                # the token and would otherwise be the "last used" reported.
                info = await self._jfrog_token_info(client, base, token)
                response = await client.get(url, auth=(username, token))
        except httpx.HTTPError as exc:
            return _transport_outcome(f"JFrog Artifactory {JFROG_INSTANCE_LABELS[instance]}", url, exc)

        now = datetime.now(UTC)
        if response.status_code == 200:
            version = ""
            with contextlib.suppress(ValueError, AttributeError):
                version = str(response.json().get("version", ""))
            return CheckOutcome(
                valid=True,
                status=VALID,
                message="Artifactory accepted the username and token.",
                details={"artifactory_version": version} if version else {},
                account=jfrog_token_details(info, claims, now=now)
                or CredentialAccountDetails(
                    notes=[
                        "Artifactory did not return details for this token. Legacy API keys have none, "
                        "and older Artifactory versions do not report them."
                    ]
                ),
            )
        if response.status_code in (401, 403):
            # A JWT says when it expires, which turns "rejected" into the
            # actual reason.  The claims only explain the rejection; they
            # never make a token valid.
            expired_at = _epoch(claims.get("exp"))
            if expired_at is not None and expired_at <= now:
                return CheckOutcome(
                    valid=False,
                    status="expired",
                    message=f"Artifactory rejected the token — it expired on {expired_at:%d %b %Y, %H:%M} UTC.",
                    account=jfrog_token_details(None, claims, now=now),
                )
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

    @staticmethod
    async def _jfrog_token_info(client: httpx.AsyncClient, base: str, token: str) -> dict | None:
        """Artifactory's record of the token (expiry, issued, last used), or None.

        The documented auth for this endpoint is a bearer token.  Anything
        other than a token record — a legacy API key, an older Artifactory, a
        timeout — is None, and the verdict call that follows decides.
        """
        url = f"{base}{_JFROG_TOKEN_INFO_PATH}"
        try:
            response = await client.get(
                url,
                headers={"Authorization": f"Bearer {token}"},
                timeout=_DETAILS_TIMEOUT_SECONDS,
            )
            data = response.json() if response.status_code == 200 else None
        except (httpx.HTTPError, ValueError) as exc:
            logger.info("credential_check_jfrog_token_info_unavailable", url=url, error=str(exc)[:200])
            return None
        # Only a token record: a proxy page or another payload must not be
        # read as "this token never expires".
        if isinstance(data, dict) and ("token_id" in data or "subject" in data):
            return data
        return None

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
                # Only once the password is known to work — never a second
                # attempt with a wrong one.
                details = (
                    await self._aaf_account(client, base, account, password) if response.status_code == 200 else None
                )
        except httpx.HTTPError as exc:
            return _transport_outcome("AAF", url, exc)

        if response.status_code == 200:
            return CheckOutcome(valid=True, status=VALID, message="AAF accepted the credential.", account=details)
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

    @staticmethod
    async def _aaf_account(
        client: httpx.AsyncClient, base: str, account: str, password: str
    ) -> CredentialAccountDetails:
        """Password expiry from AAF's credential list for the identity.

        AAF answers this only to someone with read on the identity's
        namespace (an admin of it), and an identity reading itself gets no
        exemption — so a 403 here is common, and is a note, not an error.
        """
        path = settings.CRED_CHECK_AAF_CREDS_PATH.replace("{id}", quote(account, safe="@."))
        url = f"{base}{path}"

        def _unavailable(note: str) -> CredentialAccountDetails:
            return CredentialAccountDetails(last_used_note=_AAF_NO_LAST_USE, notes=[note])

        try:
            response = await client.get(
                url,
                auth=(account, password),
                headers={"Accept": _AAF_ACCEPT},
                timeout=_DETAILS_TIMEOUT_SECONDS,
            )
        except httpx.HTTPError as exc:
            logger.info("credential_check_aaf_details_unavailable", url=url, error=str(exc)[:200])
            return _unavailable("AAF did not answer the request for the password's expiry.")

        if response.status_code == 403:
            return _unavailable(
                "AAF shows password expiry only to admins of the identity's namespace, and this identity is not one."
            )
        if response.status_code != 200:
            return _unavailable(f"AAF answered HTTP {response.status_code} when asked for the password's expiry.")
        try:
            payload = response.json()
        except ValueError:
            return _unavailable("AAF's answer about the password's expiry was not JSON.")
        return aaf_account_details(payload, now=datetime.now(UTC))
