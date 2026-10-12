"""Credential checks: the AD verdicts, the lockout guard, and what never happens.

No directory, Artifactory or AAF is contacted — httpx and the LDAP bind are
faked. What is covered for real is the guard that decides whether a
credential leaves the portal at all, and the mapping that turns a bind
failure into an operationally useful answer.
"""

from datetime import UTC, datetime, timedelta

import httpx
import pytest
from jose import jwt as jose_jwt

from app.core.config import settings
from app.services import credential_check_service as module
from app.services.credential_check_service import (
    CheckOutcome,
    CredentialCheckError,
    CredentialCheckService,
    assert_target_not_blocked,
    record_outcome,
)

TARGET = "ITSERVICES\\m52142"


@pytest.fixture(autouse=True)
def _clean_guard():
    """The guard is process state, so each test starts from empty."""
    module.reset_guard()
    yield
    module.reset_guard()


def _service() -> CredentialCheckService:
    return CredentialCheckService()


def _fail(status: str = "invalid") -> CheckOutcome:
    return CheckOutcome(valid=False, status=status, message="nope")


# ── Lockout guard ──────────────────────────────────────────────────────


def test_a_clean_target_is_allowed():
    assert_target_not_blocked(TARGET)


def test_repeated_failures_pause_a_target():
    """The guard that keeps a retry loop from locking the account out."""
    for _ in range(module._MAX_FAILURES_PER_TARGET):
        record_outcome(TARGET, _fail())

    with pytest.raises(CredentialCheckError) as excinfo:
        assert_target_not_blocked(TARGET)
    assert excinfo.value.status == "lockout_guard"


def test_one_failure_short_of_the_limit_still_runs():
    for _ in range(module._MAX_FAILURES_PER_TARGET - 1):
        record_outcome(TARGET, _fail())
    assert_target_not_blocked(TARGET)


def test_a_success_clears_the_count():
    """Someone who mistypes once then gets it right must not be left blocked."""
    for _ in range(module._MAX_FAILURES_PER_TARGET - 1):
        record_outcome(TARGET, _fail())
    record_outcome(TARGET, CheckOutcome(valid=True, status="valid", message="ok"))

    for _ in range(module._MAX_FAILURES_PER_TARGET - 1):
        record_outcome(TARGET, _fail())
    assert_target_not_blocked(TARGET)


def test_unreachable_services_do_not_count_toward_a_block():
    """A network failure says nothing about the password, so it cannot lock it out."""
    for _ in range(module._MAX_FAILURES_PER_TARGET * 2):
        record_outcome(TARGET, _fail(status="error"))
    assert_target_not_blocked(TARGET)


def test_the_block_expires(monkeypatch):
    for _ in range(module._MAX_FAILURES_PER_TARGET):
        record_outcome(TARGET, _fail())
    with pytest.raises(CredentialCheckError):
        assert_target_not_blocked(TARGET)

    later = module.time.monotonic() + module._TARGET_BLOCK_SECONDS + 1
    monkeypatch.setattr(module.time, "monotonic", lambda: later)
    assert_target_not_blocked(TARGET)


def test_the_guard_is_per_target():
    for _ in range(module._MAX_FAILURES_PER_TARGET):
        record_outcome(TARGET, _fail())
    assert_target_not_blocked("ITSERVICES\\someone-else")


# ── Nothing is persisted ───────────────────────────────────────────────


def test_the_service_needs_no_database():
    """A check writes nothing, so it takes no session and has no history."""
    service = CredentialCheckService()
    assert not hasattr(service, "db")
    for gone in ("record", "history", "assert_within_limits"):
        assert not hasattr(service, gone), f"{gone} should have gone with the audit trail"


# ── Active Directory verdicts ──────────────────────────────────────────


class _Conn:
    """Minimal ldap3 Connection stand-in.

    ``entries`` maps a search base to the raw attributes it returns; the
    root DSE is the empty base.
    """

    def __init__(self, bound: bool, result: dict | None = None, entries: dict | None = None, search_error=None):
        self._bound = bound
        self.result = result or {}
        self.unbound = False
        self.entries = entries or {}
        self.search_error = search_error
        self.searches: list[tuple[str, str]] = []
        self.response: list = []

    def bind(self):
        return self._bound

    def search(self, base, search_filter, **_kwargs):
        self.searches.append((base, search_filter))
        if self.search_error is not None:
            raise self.search_error
        raw = self.entries.get(base)
        self.response = [] if raw is None else [{"type": "searchResEntry", "dn": base or "", "raw_attributes": raw}]
        return bool(self.response)

    def unbind(self):
        self.unbound = True


@pytest.mark.parametrize(
    ("subcode", "status"),
    [
        ("52e", "invalid"),
        ("532", "expired"),
        ("533", "disabled"),
        ("775", "locked"),
        ("773", "must_change"),
        ("525", "invalid"),
        ("701", "expired"),
    ],
)
def test_ad_subcodes_separate_wrong_from_expired_locked_and_disabled(monkeypatch, subcode, status):
    """The whole point of the tool: 'wrong password' is not the only answer."""
    monkeypatch.setattr(module, "Server", lambda *a, **k: object())
    monkeypatch.setattr(module, "Tls", lambda *a, **k: object())
    monkeypatch.setattr(
        module,
        "Connection",
        lambda *a, **k: _Conn(False, {"message": f"80090308: data {subcode}, v4563"}),
    )

    outcome = _service()._bind("ldaps://dc.example.com:636", TARGET, "secret")

    assert outcome.valid is False
    assert outcome.status == status
    assert outcome.details["ad_subcode"] == subcode


def test_a_successful_bind_is_valid_and_unbinds(monkeypatch):
    conn = _Conn(True)
    monkeypatch.setattr(module, "Server", lambda *a, **k: object())
    monkeypatch.setattr(module, "Tls", lambda *a, **k: object())
    monkeypatch.setattr(module, "Connection", lambda *a, **k: conn)

    outcome = _service()._bind("ldaps://dc:636", TARGET, "s")

    assert outcome.valid is True
    assert outcome.status == "valid"
    assert conn.unbound is True


def test_an_unreachable_directory_is_an_error_not_a_rejection(monkeypatch):
    """A network failure must never be reported as a bad password."""

    def _raise(*_a, **_k):
        raise module.LDAPException("no route to host")

    monkeypatch.setattr(module, "Tls", lambda *a, **k: object())
    monkeypatch.setattr(module, "Server", _raise)

    outcome = _service()._bind("ldaps://dc:636", TARGET, "s")

    assert outcome.status == "error"
    assert outcome.valid is False


@pytest.mark.anyio
async def test_an_unconfigured_domain_is_refused_before_any_bind():
    with pytest.raises(CredentialCheckError) as excinfo:
        await _service().check_domain("ITSERVICES", "m1", "s")
    assert excinfo.value.status == "unconfigured"


# ── JFrog and AAF ──────────────────────────────────────────────────────


def _http(
    monkeypatch,
    *,
    status_code: int,
    payload: dict | None = None,
    raises: Exception | None = None,
    routes: dict[str, tuple[int, object]] | None = None,
):
    """Fake httpx.  ``routes`` answers any URL containing the key differently.

    Only ``get`` exists, so a test fails loudly if anything else is sent —
    a DELETE on the JFrog token path would revoke the token.
    """
    seen: list[tuple[str, object, dict]] = []

    class _Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url, **kwargs):
            seen.append((url, kwargs.get("auth"), kwargs.get("headers") or {}))
            if raises is not None:
                raise raises
            for fragment, (code, body) in (routes or {}).items():
                if fragment in url:
                    return httpx.Response(code, json=body)
            return httpx.Response(status_code, json=payload if payload is not None else {})

    monkeypatch.setattr(module.httpx, "AsyncClient", _Client)
    return seen


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("code", "valid", "status"),
    [(200, True, "valid"), (401, False, "invalid"), (403, False, "invalid"), (502, False, "error")],
)
async def test_jfrog_verdicts(monkeypatch, code, valid, status):
    _http(monkeypatch, status_code=code, payload={"version": "7.77.3"})
    outcome = await _service().check_jfrog("m52142@att.com", "tok")
    assert (outcome.valid, outcome.status) == (valid, status)


@pytest.mark.anyio
async def test_jfrog_sends_the_username_and_token_as_basic_auth(monkeypatch):
    seen = _http(monkeypatch, status_code=200, payload={"version": "7.77.3"})
    await _service().check_jfrog("m52142@att.com", "tok")
    verdict = next(call for call in seen if call[0].endswith("/api/system/version"))
    assert verdict[1] == ("m52142@att.com", "tok")


@pytest.mark.anyio
async def test_jfrog_timeout_is_not_reported_as_an_invalid_token(monkeypatch):
    _http(monkeypatch, status_code=200, raises=httpx.TimeoutException("timed out"))
    outcome = await _service().check_jfrog("m52142@att.com", "tok")
    assert outcome.status == "error"
    assert "timed out" in outcome.message.lower()


# ── Diagnosing an unreachable service ──────────────────────────────────


@pytest.mark.parametrize(
    ("exc", "expected"),
    [
        (httpx.TimeoutException("timed out"), "timed out"),
        (httpx.ConnectError("[Errno 8] nodename nor servname provided"), "did not resolve"),
        (httpx.ConnectError("[Errno 61] Connection refused"), "refused"),
        (httpx.ConnectError("[Errno 65] No route to host"), "unreachable"),
        (httpx.ConnectError("CERTIFICATE_VERIFY_FAILED: unable to get local issuer"), "CRED_CHECK_CA_BUNDLE"),
    ],
)
def test_transport_failures_name_the_actual_cause(exc, expected):
    """'Could not reach it' is not actionable; DNS, refused and TLS differ."""
    assert expected in module._transport_reason(exc)


@pytest.mark.anyio
async def test_an_unreachable_service_names_the_url_it_tried(monkeypatch):
    _http(monkeypatch, status_code=200, raises=httpx.ConnectError("[Errno 8] nodename nor servname provided"))
    outcome = await _service().check_aaf("nonprod", "m1@com.att.attcc", "s")

    assert outcome.status == "error"
    assert settings.CRED_CHECK_AAF_URL_NONPROD in outcome.message
    assert "did not resolve" in outcome.message


def test_an_unreachable_directory_names_the_server_and_cause(monkeypatch):
    def _raise(*_a, **_k):
        raise module.LDAPException("socket connection error: [Errno 61] Connection refused")

    monkeypatch.setattr(module, "Tls", lambda *a, **k: object())
    monkeypatch.setattr(module, "Server", _raise)

    outcome = _service()._bind("ldaps://dc.example.com:636", TARGET, "s")

    assert outcome.status == "error"
    assert "ldaps://dc.example.com:636" in outcome.message
    assert "refused" in outcome.message


@pytest.mark.anyio
async def test_an_unconfigured_domain_says_what_to_set():
    with pytest.raises(CredentialCheckError) as excinfo:
        await _service().check_domain("TESTITSERVICES", "m1", "s")
    message = str(excinfo.value)
    assert "CRED_CHECK_LDAP_TESTITSERVICES" in message
    assert "ldaps://" in message


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("code", "valid", "status"),
    [(200, True, "valid"), (401, False, "invalid"), (403, False, "invalid"), (500, False, "error")],
)
async def test_aaf_account_verdicts(monkeypatch, code, valid, status):
    _http(monkeypatch, status_code=code)
    outcome = await _service().check_aaf("prod", "m1@com.att.attcc", "s")
    assert (outcome.valid, outcome.status) == (valid, status)


@pytest.mark.anyio
async def test_aaf_uses_the_environment_specific_host(monkeypatch):
    seen = _http(monkeypatch, status_code=200)
    service = _service()

    await service.check_aaf("prod", "m1@com.att.attcc", "s")
    await service.check_aaf("nonprod", "m1@com.att.attcc", "s")

    verdicts = [url for url, *_ in seen if url.endswith(settings.CRED_CHECK_AAF_PATH)]
    assert verdicts[0].startswith(settings.CRED_CHECK_AAF_URL_PROD)
    assert verdicts[1].startswith(settings.CRED_CHECK_AAF_URL_NONPROD)


# ── Account details: expiry and last use ───────────────────────────────

NOW = datetime(2026, 10, 12, 12, 0, tzinfo=UTC)
BASE_DN = "DC=itservices,DC=example,DC=com"


def _filetime(when: datetime) -> bytes:
    """AD FILETIME (100 ns ticks since 1601) as the directory sends it."""
    ticks = int((when - datetime(1601, 1, 1, tzinfo=UTC)).total_seconds()) * 10_000_000
    return str(ticks).encode()


def _ad_entry(**raw: bytes) -> dict:
    return {"type": "searchResEntry", "raw_attributes": {name: [value] for name, value in raw.items()}}


def test_ad_details_read_expiry_last_change_and_last_sign_in():
    entry = _ad_entry(
        displayName=b"Miri, Mohnish",
        pwdLastSet=_filetime(datetime(2026, 9, 15, tzinfo=UTC)),
        **{"msDS-UserPasswordExpiryTimeComputed": _filetime(datetime(2026, 12, 14, tzinfo=UTC))},
        accountExpires=b"9223372036854775807",
        lastLogonTimestamp=_filetime(datetime(2026, 10, 1, tzinfo=UTC)),
        userAccountControl=b"512",
    )

    details = module.ad_account_details(entry, now=NOW)

    assert details.display_name == "Miri, Mohnish"
    assert details.expires_at == datetime(2026, 12, 14, tzinfo=UTC)
    assert details.never_expires is False
    assert details.last_changed_at == datetime(2026, 9, 15, tzinfo=UTC)
    assert details.last_used_at == datetime(2026, 10, 1, tzinfo=UTC)
    assert "9 to 14 days" in details.last_used_note
    assert details.account_expires_at is None  # max int64 = the account never expires


@pytest.mark.parametrize(
    "raw",
    [
        {"msDS-UserPasswordExpiryTimeComputed": b"9223372036854775807", "userAccountControl": b"512"},
        {"userAccountControl": str(512 | 0x10000).encode()},  # DONT_EXPIRE_PASSWORD
    ],
)
def test_ad_password_that_never_expires_says_so(raw):
    details = module.ad_account_details(_ad_entry(**raw), now=NOW)
    assert details.never_expires is True
    assert details.expires_at is None


def test_ad_sign_in_written_by_the_check_itself_is_not_reported_as_use():
    """The bind refreshes a stale lastLogonTimestamp — 'just now' would be a lie."""
    entry = _ad_entry(lastLogonTimestamp=_filetime(NOW - timedelta(seconds=20)))

    details = module.ad_account_details(entry, now=NOW)

    assert details.last_used_at is None
    assert "before this check" in details.last_used_note


def _bind_with(monkeypatch, conn):
    monkeypatch.setattr(module, "Server", lambda *a, **k: object())
    monkeypatch.setattr(module, "Tls", lambda *a, **k: object())
    monkeypatch.setattr(module, "Connection", lambda *a, **k: conn)


def test_a_successful_bind_reads_the_accounts_own_entry(monkeypatch):
    conn = _Conn(
        True,
        entries={
            "": {"defaultNamingContext": [BASE_DN.encode()]},
            BASE_DN: {"pwdLastSet": [_filetime(datetime(2026, 9, 15, tzinfo=UTC))]},
        },
    )
    _bind_with(monkeypatch, conn)

    outcome = _service()._bind("ldaps://dc:636", "ITSERVICES\\m5*2142", "s")

    assert outcome.valid is True
    assert outcome.account.last_changed_at == datetime(2026, 9, 15, tzinfo=UTC)
    # The user search is scoped to the domain and the username is escaped.
    assert conn.searches[1] == (BASE_DN, "(&(objectClass=user)(sAMAccountName=m5\\2a2142))")
    assert conn.unbound is True


def test_a_directory_that_refuses_the_read_still_gives_the_verdict(monkeypatch):
    conn = _Conn(True, search_error=module.LDAPException("insufficientAccessRights"))
    _bind_with(monkeypatch, conn)

    outcome = _service()._bind("ldaps://dc:636", TARGET, "s")

    assert outcome.valid is True
    assert outcome.account.expires_at is None
    assert "did not return details" in outcome.account.notes[0]
    assert conn.unbound is True


def test_a_failed_bind_reads_nothing(monkeypatch):
    conn = _Conn(False, {"message": "80090308: data 52e, v4563"})
    _bind_with(monkeypatch, conn)

    outcome = _service()._bind("ldaps://dc:636", TARGET, "s")

    assert outcome.account is None
    assert conn.searches == []


TOKEN_RECORD = {
    "token_id": "8d1c",
    "subject": "jfac@01/users/m52142@att.com",
    "expiry": int(datetime(2027, 1, 1, tzinfo=UTC).timestamp()),
    "issued_at": int(datetime(2026, 1, 1, tzinfo=UTC).timestamp()),
    "last_used": int(datetime(2026, 10, 10, tzinfo=UTC).timestamp()),
    "description": "pipeline token",
}


@pytest.mark.anyio
async def test_jfrog_reads_the_token_record_before_using_the_token(monkeypatch):
    """The check is itself a use; read first, or 'last used' is always 'now'."""
    seen = _http(monkeypatch, status_code=200, routes={"/tokens/me": (200, TOKEN_RECORD)})

    outcome = await _service().check_jfrog("m52142@att.com", "tok")

    assert seen[0][0].endswith("/access/api/v1/tokens/me")
    assert seen[0][2] == {"Authorization": "Bearer tok"}
    assert seen[1][0].endswith("/artifactory/api/system/version")
    assert outcome.account.expires_at == datetime(2027, 1, 1, tzinfo=UTC)
    assert outcome.account.last_changed_at == datetime(2026, 1, 1, tzinfo=UTC)
    assert outcome.account.last_used_at == datetime(2026, 10, 10, tzinfo=UTC)
    assert outcome.account.display_name == "pipeline token"


@pytest.mark.anyio
async def test_jfrog_token_with_no_expiry_never_expires(monkeypatch):
    record = {key: value for key, value in TOKEN_RECORD.items() if key not in ("expiry", "last_used")}
    _http(monkeypatch, status_code=200, routes={"/tokens/me": (200, record)})

    outcome = await _service().check_jfrog("m52142@att.com", "tok")

    assert outcome.account.never_expires is True
    assert outcome.account.last_used_at is None
    assert "7.108.3" in outcome.account.last_used_note


@pytest.mark.anyio
async def test_jfrog_falls_back_to_the_tokens_own_claims(monkeypatch):
    token = jose_jwt.encode({"exp": 1798761600, "iat": 1767225600, "sub": "m52142"}, "k")
    _http(monkeypatch, status_code=200, routes={"/tokens/me": (404, {})})

    outcome = await _service().check_jfrog("m52142@att.com", token)

    assert outcome.account.expires_at == datetime(2027, 1, 1, tzinfo=UTC)
    assert "token itself" in outcome.account.notes[0]


@pytest.mark.anyio
async def test_jfrog_does_not_mistake_another_payload_for_a_token_record(monkeypatch):
    """A proxy page answering 200 must not read as 'this token never expires'."""
    _http(monkeypatch, status_code=200, payload={"version": "7.77.3"})

    outcome = await _service().check_jfrog("m52142@att.com", "tok")

    assert outcome.account.never_expires is False
    assert "did not return details" in outcome.account.notes[0]


@pytest.mark.anyio
async def test_a_rejected_jwt_past_its_expiry_is_reported_as_expired(monkeypatch):
    token = jose_jwt.encode({"exp": int(datetime(2026, 10, 3, 14, 0, tzinfo=UTC).timestamp())}, "k")
    _http(monkeypatch, status_code=401)

    outcome = await _service().check_jfrog("m52142@att.com", token)

    assert outcome.status == "expired"
    assert "03 Oct 2026" in outcome.message
    assert outcome.account.expires_at == datetime(2026, 10, 3, 14, 0, tzinfo=UTC)


@pytest.mark.anyio
async def test_a_jwt_rejected_before_its_expiry_stays_invalid(monkeypatch):
    """A revoked token is rejected while its exp is still ahead — that is not 'expired'."""
    token = jose_jwt.encode({"exp": int((datetime.now(UTC) + timedelta(days=30)).timestamp())}, "k")
    _http(monkeypatch, status_code=401)

    outcome = await _service().check_jfrog("m52142@att.com", token)

    assert outcome.status == "invalid"


def test_aaf_details_show_the_latest_live_password_and_name_the_others():
    payload = {
        "user": [
            {"id": "m1@com.att.attcc", "type": 2, "expires": "2026-12-01T10:00:00.000-05:00", "tag": "a"},
            {"id": "m1@com.att.attcc", "type": 2, "expires": "2026-10-20T10:00:00.000-05:00", "tag": "b"},
            {"id": "m1@com.att.attcc", "type": 2, "expires": "2026-09-01T10:00:00.000-05:00", "tag": "old"},
            {"id": "m1@com.att.attcc", "type": 200, "expires": "2027-06-01T00:00:00.000-05:00", "tag": "cert"},
        ]
    }

    details = module.aaf_account_details(payload, now=NOW)

    assert details.expires_at == datetime(2026, 12, 1, 15, 0, tzinfo=UTC)  # the certificate is ignored
    assert "2 passwords" in details.notes[0]
    assert "AAF does not record" in details.last_used_note


@pytest.mark.anyio
async def test_aaf_expiry_refused_to_a_non_admin_is_a_note_not_a_failure(monkeypatch):
    _http(monkeypatch, status_code=200, routes={"/authn/creds/id/": (403, {})})

    outcome = await _service().check_aaf("prod", "m1@com.att.attcc", "s")

    assert outcome.status == "valid"
    assert "admins of the identity's namespace" in outcome.account.notes[0]


@pytest.mark.anyio
async def test_aaf_asks_for_expiry_only_after_the_password_worked(monkeypatch):
    """Never a second attempt with a wrong password."""
    seen = _http(monkeypatch, status_code=401)

    outcome = await _service().check_aaf("prod", "m1@com.att.attcc", "s")

    assert outcome.status == "invalid"
    assert outcome.account is None
    assert len(seen) == 1


@pytest.mark.anyio
async def test_aaf_expiry_lookup_targets_the_checked_identity(monkeypatch):
    seen = _http(monkeypatch, status_code=200, routes={"/authn/creds/id/": (200, {"user": []})})

    await _service().check_aaf("nonprod", "m1@com.att.attcc", "s")

    assert seen[1][0] == f"{settings.CRED_CHECK_AAF_URL_NONPROD}/authn/creds/id/m1@com.att.attcc"
    assert seen[1][1] == ("m1@com.att.attcc", "s")
