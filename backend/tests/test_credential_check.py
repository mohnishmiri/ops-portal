"""Credential checks: the guards, the audit trail, and the AD verdicts.

No directory, Artifactory or AAF is contacted — httpx and the LDAP bind are
faked. What is exercised for real is everything that decides whether a
credential leaves the portal at all, because that is the part that must not
regress.
"""

from datetime import datetime, timedelta
from types import SimpleNamespace

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.ext.compiler import compiles

from app.core.config import settings
from app.models.database import AuditLog
from app.services import credential_check_service as module
from app.services.credential_check_service import (
    AUDIT_ACTION,
    CheckOutcome,
    CredentialCheckError,
    CredentialCheckService,
)


@compiles(JSONB, "sqlite")
def _jsonb_as_json_on_sqlite(_type, _compiler, **_kw):
    return "JSON"


@pytest.fixture
async def factory(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'cred.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(lambda c: AuditLog.__table__.create(c))
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False, autoflush=False)
    yield maker
    await engine.dispose()


USER = SimpleNamespace(user_id="u1", email="ops@att.com", is_admin=False)
OTHER = SimpleNamespace(user_id="u2", email="other@att.com", is_admin=False)
ADMIN = SimpleNamespace(user_id="admin", email="admin@att.com", is_admin=True)


async def _audit(db, *, user=USER, target="ITSERVICES\\m1", status="failure", when=None):
    db.add(
        AuditLog(
            user_id=user.user_id,
            user_email=user.email,
            action=AUDIT_ACTION,
            resource_type="credential_check",
            resource_id=target,
            details={"kind": "domain", "status": "invalid", "message": "nope"},
            status=status,
            timestamp=when or datetime.utcnow(),
        )
    )
    await db.commit()


# ── Rate limit and lockout guard ───────────────────────────────────────


@pytest.mark.anyio
async def test_user_is_rate_limited_after_the_window_fills(factory):
    async with factory() as db:
        for i in range(module._MAX_CHECKS_PER_WINDOW):
            await _audit(db, target=f"ITSERVICES\\u{i}", status="success")
        with pytest.raises(CredentialCheckError) as excinfo:
            await CredentialCheckService(db).assert_within_limits(USER, "ITSERVICES\\new")
    assert excinfo.value.status == "rate_limited"


@pytest.mark.anyio
async def test_older_checks_fall_out_of_the_window(factory):
    stale = datetime.utcnow() - timedelta(minutes=module._WINDOW_MINUTES + 1)
    async with factory() as db:
        for i in range(module._MAX_CHECKS_PER_WINDOW):
            await _audit(db, target=f"ITSERVICES\\u{i}", status="success", when=stale)
        await CredentialCheckService(db).assert_within_limits(USER, "ITSERVICES\\new")


@pytest.mark.anyio
async def test_another_users_checks_do_not_consume_the_limit(factory):
    async with factory() as db:
        for i in range(module._MAX_CHECKS_PER_WINDOW):
            await _audit(db, user=OTHER, target=f"ITSERVICES\\u{i}", status="success")
        await CredentialCheckService(db).assert_within_limits(USER, "ITSERVICES\\new")


@pytest.mark.anyio
async def test_repeated_failures_against_one_target_are_blocked(factory):
    """The guard that keeps a retry loop from locking the account out."""
    async with factory() as db:
        for _ in range(module._MAX_FAILURES_PER_TARGET):
            await _audit(db, target="ITSERVICES\\m52142", status="failure")
        with pytest.raises(CredentialCheckError) as excinfo:
            await CredentialCheckService(db).assert_within_limits(USER, "ITSERVICES\\m52142")
    assert excinfo.value.status == "lockout_guard"


@pytest.mark.anyio
async def test_the_lockout_guard_counts_every_users_failures(factory):
    """One account, two people guessing: the account is what gets locked."""
    async with factory() as db:
        for _ in range(module._MAX_FAILURES_PER_TARGET):
            await _audit(db, user=OTHER, target="ITSERVICES\\m52142", status="failure")
        with pytest.raises(CredentialCheckError) as excinfo:
            await CredentialCheckService(db).assert_within_limits(USER, "ITSERVICES\\m52142")
    assert excinfo.value.status == "lockout_guard"


@pytest.mark.anyio
async def test_successful_checks_of_a_target_do_not_block_it(factory):
    """Only failures risk a lockout, so only failures close the target off."""
    async with factory() as db:
        for _ in range(module._MAX_FAILURES_PER_TARGET + 1):
            await _audit(db, target="ITSERVICES\\m52142", status="success")
        # Below the per-user volume limit, so if this raises it is the target
        # guard miscounting successes as failures.
        await CredentialCheckService(db).assert_within_limits(USER, "ITSERVICES\\m52142")


# ── Audit trail ────────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_the_audit_row_records_the_outcome_and_never_the_secret(factory):
    async with factory() as db:
        await CredentialCheckService(db).record(
            user=USER,
            ip="10.0.0.1",
            kind="domain",
            target="ITSERVICES\\m52142",
            outcome=CheckOutcome(valid=False, status="expired", message="The password is correct but has expired."),
        )
        rows = list((await db.execute(select(AuditLog))).scalars().all())

    assert len(rows) == 1
    row = rows[0]
    assert row.status == "failure"
    assert row.resource_id == "ITSERVICES\\m52142"
    assert row.details["status"] == "expired"
    assert row.details["kind"] == "domain"
    serialised = str(row.details) + str(row.resource_id)
    assert "password" not in serialised.lower() or "hunter2" not in serialised


@pytest.mark.anyio
async def test_history_is_scoped_to_the_caller_but_admins_see_everyone(factory):
    async with factory() as db:
        await _audit(db, user=USER, target="ITSERVICES\\mine")
        await _audit(db, user=OTHER, target="ITSERVICES\\theirs")

        mine = await CredentialCheckService(db).history(USER)
        everyone = await CredentialCheckService(db).history(ADMIN)

    assert [row["target"] for row in mine] == ["ITSERVICES\\mine"]
    assert {row["target"] for row in everyone} == {"ITSERVICES\\mine", "ITSERVICES\\theirs"}


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
    service = CredentialCheckService(db=None)  # type: ignore[arg-type]
    monkeypatch.setattr(module, "Server", lambda *a, **k: object())
    monkeypatch.setattr(module, "Tls", lambda *a, **k: object())
    monkeypatch.setattr(
        module,
        "Connection",
        lambda *a, **k: _Conn(False, {"message": f"80090308: data {subcode}, v4563"}),
    )

    outcome = service._bind("ldaps://dc.example.com:636", "ITSERVICES\\m52142", "secret")

    assert outcome.valid is False
    assert outcome.status == status
    assert outcome.details["ad_subcode"] == subcode


def test_a_successful_bind_is_valid_and_unbinds(monkeypatch):
    conn = _Conn(True)
    monkeypatch.setattr(module, "Server", lambda *a, **k: object())
    monkeypatch.setattr(module, "Tls", lambda *a, **k: object())
    monkeypatch.setattr(module, "Connection", lambda *a, **k: conn)

    outcome = CredentialCheckService(db=None)._bind("ldaps://dc:636", "ITSERVICES\\m1", "s")  # type: ignore[arg-type]

    assert outcome.valid is True
    assert outcome.status == "valid"
    assert conn.unbound is True


def test_an_unreachable_directory_is_an_error_not_a_rejection(monkeypatch):
    """A network failure must never be reported as a bad password."""

    def _raise(*_a, **_k):
        raise module.LDAPException("no route to host")

    monkeypatch.setattr(module, "Tls", lambda *a, **k: object())
    monkeypatch.setattr(module, "Server", _raise)

    outcome = CredentialCheckService(db=None)._bind("ldaps://dc:636", "ITSERVICES\\m1", "s")  # type: ignore[arg-type]

    assert outcome.status == "error"
    assert outcome.valid is False


@pytest.mark.anyio
async def test_an_unconfigured_domain_is_refused_before_any_bind():
    with pytest.raises(CredentialCheckError) as excinfo:
        await CredentialCheckService(db=None).check_domain("ITSERVICES", "m1", "s")  # type: ignore[arg-type]
    assert excinfo.value.status == "unconfigured"


# ── JFrog and AAF ──────────────────────────────────────────────────────


def _http(monkeypatch, *, status_code: int, payload: dict | None = None, raises: Exception | None = None):
    class _Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, _url, **_kwargs):
            if raises is not None:
                raise raises
            return httpx.Response(status_code, json=payload if payload is not None else {})

    monkeypatch.setattr(module.httpx, "AsyncClient", _Client)


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("code", "valid", "status"),
    [(200, True, "valid"), (401, False, "invalid"), (403, False, "invalid"), (502, False, "error")],
)
async def test_jfrog_token_verdicts(monkeypatch, code, valid, status):
    _http(monkeypatch, status_code=code, payload={"version": "7.77.3"})
    outcome = await CredentialCheckService(db=None).check_jfrog("tok")  # type: ignore[arg-type]
    assert (outcome.valid, outcome.status) == (valid, status)


@pytest.mark.anyio
async def test_jfrog_timeout_is_not_reported_as_an_invalid_token(monkeypatch):
    _http(monkeypatch, status_code=200, raises=httpx.TimeoutException("timed out"))
    outcome = await CredentialCheckService(db=None).check_jfrog("tok")  # type: ignore[arg-type]
    assert outcome.status == "error"
    assert "Timed out" in outcome.message


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("code", "valid", "status"),
    [(200, True, "valid"), (401, False, "invalid"), (403, False, "invalid"), (500, False, "error")],
)
async def test_aaf_account_verdicts(monkeypatch, code, valid, status):
    _http(monkeypatch, status_code=code)
    outcome = await CredentialCheckService(db=None).check_aaf("prod", "m1@com.att.attcc", "s")  # type: ignore[arg-type]
    assert (outcome.valid, outcome.status) == (valid, status)


@pytest.mark.anyio
async def test_aaf_uses_the_environment_specific_host(monkeypatch):
    seen: list[str] = []

    class _Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url, **_kwargs):
            seen.append(url)
            return httpx.Response(200)

    monkeypatch.setattr(module.httpx, "AsyncClient", _Client)
    service = CredentialCheckService(db=None)  # type: ignore[arg-type]

    await service.check_aaf("prod", "m1@com.att.attcc", "s")
    await service.check_aaf("nonprod", "m1@com.att.attcc", "s")

    assert seen[0].startswith(settings.CRED_CHECK_AAF_URL_PROD)
    assert seen[1].startswith(settings.CRED_CHECK_AAF_URL_NONPROD)
