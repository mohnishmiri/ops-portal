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


def _DOMAIN_SERVERS() -> dict[str, str]:  # noqa: N802 - settings are read per call, not at import
    return {
        "ITSERVICES": settings.CRED_CHECK_LDAP_ITSERVICES,
        "TESTITSERVICES": settings.CRED_CHECK_LDAP_TESTITSERVICES,
    }


def _qualified_bind_user(domain: str, reader: str) -> str:
    """The reader as Active Directory will accept it for a bind.

    A bare ``m47355`` is what people naturally configure — it is what the
    check form takes — but a simple bind needs a qualified name, and an
    unqualified one is refused as if the password were wrong.  So qualify it
    here, while leaving a name that is already ``DOMAIN\\user``, a UPN or a
    full DN exactly as it was given.
    """
    reader = reader.strip()
    if not reader or "\\" in reader or "@" in reader or "=" in reader:
        return reader
    return f"{domain}\\{reader}"


def _DOMAIN_READERS() -> dict[str, tuple[str, str]]:  # noqa: N802
    return {
        "ITSERVICES": (
            settings.CRED_CHECK_LDAP_READER_ITSERVICES,
            settings.CRED_CHECK_LDAP_READER_PASSWORD_ITSERVICES,
        ),
        "TESTITSERVICES": (
            settings.CRED_CHECK_LDAP_READER_TESTITSERVICES,
            settings.CRED_CHECK_LDAP_READER_PASSWORD_TESTITSERVICES,
        ),
    }


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

# LDAP resultCode 34.  Active Directory accepts DOMAIN\user as a bind name, so
# this answer means the configured server is some other directory (e.g. an
# AAF LDAP endpoint) and no password was ever compared.
_INVALID_DN_SYNTAX = 34


def _not_active_directory(conn: Any) -> bool:
    result = getattr(conn, "result", None) or {}
    return result.get("result") == _INVALID_DN_SYNTAX or result.get("description") == "invalidDNSyntax"


def _not_active_directory_message(domain: str, server_url: str, bind_user: str) -> str:
    return (
        f"The server at {server_url} refused {bind_user} as a sign-in name, so it is not the {domain} "
        f"Active Directory. Point CRED_CHECK_LDAP_{domain} at a {domain} domain controller and restart "
        "the backend. The password was not checked."
    )


# Status values the UI knows how to colour.  "error" covers anything that
# says nothing about the credential itself (DNS, TLS, timeout).
VALID = "valid"
INVALID = "invalid"


@dataclass
class DirectoryLookup:
    """What a reader-bound lookup found.  Never carries a credential.

    ``status`` is ``ok`` | ``unconfigured`` | ``not_found`` | ``error``; only
    ``ok`` carries details, and only an operator-facing reason otherwise.
    """

    status: str
    reason: str | None = None
    details: CredentialAccountDetails | None = None


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
_UF_ACCOUNTDISABLE = 0x0002

# An account that has not signed in for this long is reported as inactive.
# Active Directory has no such flag — this is the portal drawing a line, so
# the number is said out loud wherever the status is shown.
INACTIVE_AFTER_DAYS = 90

_AD_ACCOUNT_ATTRIBUTES = [
    "displayName",
    "pwdLastSet",
    # Computed by the DC, so it honours fine-grained password policies.
    "msDS-UserPasswordExpiryTimeComputed",
    "accountExpires",
    "lastLogonTimestamp",
    "userAccountControl",
    # Failed sign-ins.  Neither is replicated between domain controllers, so
    # both describe the DC that answered this bind, not the domain.
    "badPwdCount",
    "badPasswordTime",
    # Non-zero while the account is locked out; cleared when it unlocks.
    "lockoutTime",
]


def _account_status(entry: dict, *, uac: int, last_logon: datetime | None, now: datetime) -> tuple[str, str | None]:
    """Is this account usable at all?  ``(status, note)``.

    Reported in the order that matters operationally: a disabled account is
    disabled whatever else is true of it, and a locked one cannot sign in even
    though everything about it is otherwise in order.  "Inactive" is the
    portal's own reading of a stale sign-in, not a flag the directory holds,
    so it says the threshold it used.
    """
    if uac & _UF_ACCOUNTDISABLE:
        return "disabled", "The account is disabled in Active Directory and cannot sign in."
    if _filetime(_ad_int(entry, "lockoutTime")) is not None:
        return "locked", "Locked out on the domain controller that answered; it unlocks on the lockout policy's timer."
    account_expires = _filetime(_ad_int(entry, "accountExpires"))
    if account_expires is not None and account_expires <= now:
        return "expired", f"The account itself expired on {account_expires:%d %b %Y} — this is not its password expiry."
    if last_logon is not None and (now - last_logon) > timedelta(days=INACTIVE_AFTER_DAYS):
        return "inactive", (
            f"Enabled, but no sign-in recorded in {INACTIVE_AFTER_DAYS} days. Active Directory records sign-ins only "
            "every 9 to 14 days, so a little older than it looks."
        )
    return "active", None


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
    """Expiry, last change, last sign-in and failed sign-ins from the account's own AD entry."""
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

    # badPwdCount is reset by a successful sign-in, so after a correct
    # password it is the count since that sign-in, not a running total.
    failed = _ad_int(entry, "badPwdCount")
    last_failed = _filetime(_ad_int(entry, "badPasswordTime"))
    if failed is None:
        failed_note = "Not reported — the directory did not return a failed sign-in count."
    elif failed == 0:
        failed_note = "None on the domain controller that answered, since the last successful sign-in."
    else:
        failed_note = (
            "Counted by the domain controller that answered, since the last successful sign-in. "
            "Each controller keeps its own count."
        )

    status, status_note = _account_status(entry, uac=uac, last_logon=last_logon, now=now)

    return CredentialAccountDetails(
        display_name=_ad_text(entry, "displayName"),
        account_status=status,
        account_status_note=status_note,
        expires_at=None if never_expires else _filetime(computed),
        never_expires=never_expires,
        last_changed_at=_filetime(_ad_int(entry, "pwdLastSet")),
        last_used_at=last_used_at,
        last_used_note=last_used_note,
        account_expires_at=_filetime(_ad_int(entry, "accountExpires")),
        failed_sign_ins=failed,
        last_failed_at=last_failed,
        failed_sign_ins_note=failed_note,
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
        server_url = _DOMAIN_SERVERS().get(domain, "").strip()

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

    @staticmethod
    def _connect(server_url: str, bind_user: str, password: str) -> Any:
        """An unbound ldap3 Connection over LDAPS.  Shared by every bind here."""
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
        return Connection(
            server,
            user=bind_user,
            password=password,
            auto_bind=False,
            receive_timeout=settings.CRED_CHECK_TIMEOUT_SECONDS,
            # Following a referral would present the password to another server.
            auto_referrals=False,
        )

    def _bind(self, server_url: str, bind_user: str, password: str) -> CheckOutcome:
        """Blocking LDAP bind — always called through ``asyncio.to_thread``."""
        try:
            conn = self._connect(server_url, bind_user, password)
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

        if _not_active_directory(conn):
            domain_name = bind_user.split("\\")[0]
            logger.warning("credential_check_server_not_ad", domain=domain_name, server=server_url)
            # "error" keeps this out of the lockout guard: no password was compared.
            return CheckOutcome(
                valid=False,
                status="error",
                message=_not_active_directory_message(domain_name, server_url, bind_user),
            )

        # Not bound: read the sub-code before falling back to a generic answer.
        diagnostic = str(getattr(conn, "result", {}) or {})
        match = _SUBCODE_RE.search(diagnostic)
        if match:
            status, message = _AD_SUBCODES.get(match.group(1).lower(), (INVALID, "The password was rejected."))
            return CheckOutcome(valid=False, status=status, message=message, details={"ad_subcode": match.group(1)})
        return CheckOutcome(valid=False, status=INVALID, message="The password was rejected by the directory.")

    @staticmethod
    def _read_ad_account(conn: Any, username: str, *, found_only: bool = False) -> Any:
        """Read one account's entry over an already-bound connection.

        Used two ways: by a check, over the account's own connection, where a
        hardened directory may refuse the read and that is a note rather than
        a failure; and by a lookup, over the reader's connection, where
        ``found_only`` returns None instead so "no such account" can be told
        apart from "could not read".
        """
        unavailable = (
            None
            if found_only
            else CredentialAccountDetails(notes=["The directory did not return details for this account."])
        )
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

    # ── Domain lookup (no password for the account itself) ─────────────

    async def lookup_domain_account(self, domain: str, username: str) -> DirectoryLookup:
        """What the directory says about ``username``, read with the portal's reader account.

        The companion to ``check_domain``: that one proves a password and
        learns the details as a side effect; this one just reads the details,
        for an account the team has listed but holds no password for here.

        It only ever *reads* account attributes — the same ones a check
        reports.  No password is read (AD does not expose one), nothing is
        written, and a missing reader account simply means "not configured".
        """
        server_url = _DOMAIN_SERVERS().get(domain, "").strip()
        reader, reader_password = _DOMAIN_READERS().get(domain, ("", ""))
        reader, reader_password = _qualified_bind_user(domain, reader), reader_password.strip()

        if not LDAP_AVAILABLE:
            return DirectoryLookup("unconfigured", "Domain lookups need the ldap3 package, absent from this build.")
        if not server_url:
            return DirectoryLookup(
                "unconfigured",
                f"No LDAP server is configured for {domain}. Set CRED_CHECK_LDAP_{domain}.",
            )
        if not (reader and reader_password):
            return DirectoryLookup(
                "unconfigured",
                f"No directory reader is configured for {domain}, so details can only come from a check of the "
                f"account itself. Set CRED_CHECK_LDAP_READER_{domain} and its password.",
            )

        return await asyncio.to_thread(self._lookup, server_url, reader, reader_password, domain, username)

    def _lookup(
        self, server_url: str, reader: str, reader_password: str, domain: str, username: str
    ) -> DirectoryLookup:
        """Blocking reader bind + one search — always called through ``asyncio.to_thread``."""
        try:
            conn = self._connect(server_url, reader, reader_password)
            bound = conn.bind()
        except LDAPException as exc:
            logger.warning("credential_lookup_transport_failed", domain=domain, server=server_url, error=str(exc)[:300])
            return DirectoryLookup(
                "error", f"Could not reach the {domain} directory at {server_url} — {_transport_reason(exc)}."
            )

        if not bound and _not_active_directory(conn):
            logger.warning("credential_lookup_server_not_ad", domain=domain, server=server_url)
            return DirectoryLookup("error", _not_active_directory_message(domain, server_url, reader))

        if not bound:
            # The reader's own credential is wrong or expired — an operator
            # problem, and never reported as something about the account.
            # Naming the account it tried saves guessing at the format.
            logger.warning("credential_lookup_reader_rejected", domain=domain, reader=reader)
            return DirectoryLookup(
                "error",
                f"The {domain} directory rejected the portal's reader account, binding as {reader}. Check "
                f"CRED_CHECK_LDAP_READER_{domain} and its password — the account name may be a plain username, "
                f"{domain}\\name, or a UPN.",
            )

        try:
            details = self._read_ad_account(conn, username, found_only=True)
        finally:
            with contextlib.suppress(LDAPException):
                conn.unbind()

        if details is None:
            return DirectoryLookup("not_found", f"{domain}\\{username} was not found in the directory.")
        return DirectoryLookup("ok", None, details)

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
