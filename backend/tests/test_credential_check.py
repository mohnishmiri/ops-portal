"""Credential checks: the AD verdicts, the lockout guard, and what never happens.

No directory, Artifactory or AAF is contacted — httpx and the LDAP bind are
faked. What is covered for real is the guard that decides whether a
credential leaves the portal at all, and the mapping that turns a bind
failure into an operationally useful answer.
"""

import httpx
import pytest

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
    """Minimal ldap3 Connection stand-in."""

    def __init__(self, bound: bool, result: dict | None = None):
        self._bound = bound
        self.result = result or {}
        self.unbound = False

    def bind(self):
        return self._bound

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


def _http(monkeypatch, *, status_code: int, payload: dict | None = None, raises: Exception | None = None):
    seen: list[tuple[str, object]] = []

    class _Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url, **kwargs):
            seen.append((url, kwargs.get("auth")))
            if raises is not None:
                raise raises
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
    assert seen[0][1] == ("m52142@att.com", "tok")


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

    assert seen[0][0].startswith(settings.CRED_CHECK_AAF_URL_PROD)
    assert seen[1][0].startswith(settings.CRED_CHECK_AAF_URL_NONPROD)
