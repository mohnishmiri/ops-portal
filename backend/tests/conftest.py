"""
Shared test fixtures for the OpsPortal backend test suite.

Uses SQLite in-memory (via aiosqlite) for endpoints that exercise RBAC DB
logic.  Only the Resource and Permission tables are created — they are the
only RBAC tables that have no PostgreSQL-specific JSONB columns.

Fixtures exposed:
  db_engine       — fresh async SQLite engine (function scope)
  db_session      — async session against that engine (function scope)
  admin_user      — coroutine that returns an ADMIN UserContext
  app             — FastAPI app instance (no DB override)
  admin_client    — AsyncClient with get_db + get_current_user overridden
"""

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.auth import get_current_user
from app.core.database import get_db
from app.main import create_application
from app.models.database import (
    CertificateKeyEscrow,
    Permission,
    Resource,
    Team,
    TeamMembership,
)
from app.schemas.auth import UserContext, UserRole

# audit_logs uses JSONB which SQLite can't compile.  We create an equivalent
# table using TEXT for the details column so the audit writes in the
# permissions endpoints succeed inside the test suite.
_AUDIT_LOGS_SQLITE_DDL = """
CREATE TABLE IF NOT EXISTS audit_logs (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp    DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    user_id      VARCHAR(255) NOT NULL,
    user_email   VARCHAR(255),
    action       VARCHAR(100) NOT NULL,
    resource_type VARCHAR(100) NOT NULL,
    resource_id  VARCHAR(500),
    details      TEXT,
    ip_address   VARCHAR(50),
    status       VARCHAR(20) DEFAULT 'success'
)
"""


# cert_certificates uses JSONB too.  The certificate audit trail resolves a
# common name from this snapshot, so an equivalent TEXT-column table is created
# to exercise that lookup instead of only its "not cached" fallback.
_CERT_CERTIFICATES_SQLITE_DDL = """
CREATE TABLE IF NOT EXISTS cert_certificates (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    collection_id  INTEGER NOT NULL,
    certificate_id INTEGER NOT NULL,
    common_name    VARCHAR(500),
    subject_dn     TEXT,
    issuer_dn      TEXT,
    serial_number  VARCHAR(255),
    thumbprint     VARCHAR(100),
    template       VARCHAR(500),
    certificate_authority VARCHAR(500),
    not_before     VARCHAR(50),
    not_after      VARCHAR(50),
    import_date    VARCHAR(50),
    effective_date VARCHAR(50),
    sans           TEXT,
    san_count      INTEGER,
    revoked        BOOLEAN,
    revocation_reason INTEGER,
    status         VARCHAR(30),
    cert_metadata  TEXT,
    key_algorithm  VARCHAR(50),
    key_size       INTEGER,
    key_usage      VARCHAR(500),
    extended_key_usage VARCHAR(500),
    signing_algorithm  VARCHAR(100),
    requester      VARCHAR(255),
    principal_name VARCHAR(255),
    locations      TEXT,
    location_count INTEGER,
    collection     VARCHAR(500),
    has_private_key BOOLEAN,
    synced_at      DATETIME
)
"""


# ── In-memory SQLite engine ────────────────────────────────────────────────────


@pytest.fixture
async def db_engine():
    """Fresh in-memory SQLite engine — RBAC, audit_logs and cert escrow tables."""
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        echo=False,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(lambda c: Resource.__table__.create(c, checkfirst=True))
        await conn.run_sync(lambda c: Permission.__table__.create(c, checkfirst=True))
        await conn.run_sync(lambda c: Team.__table__.create(c, checkfirst=True))
        await conn.run_sync(lambda c: TeamMembership.__table__.create(c, checkfirst=True))
        # cert_key_escrow holds no JSONB, so it compiles on SQLite as-is.
        await conn.run_sync(lambda c: CertificateKeyEscrow.__table__.create(c, checkfirst=True))
        await conn.execute(text(_AUDIT_LOGS_SQLITE_DDL))
        await conn.execute(text(_CERT_CERTIFICATES_SQLITE_DDL))
    yield engine
    await engine.dispose()


@pytest.fixture
async def db_session(db_engine):
    """Async session against the in-memory SQLite engine."""
    factory = async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session
        await session.rollback()


# ── User helpers ───────────────────────────────────────────────────────────────


async def make_admin_user() -> UserContext:
    return UserContext(
        user_id="test-admin",
        object_id="00000000-0000-0000-0000-000000000000",
        display_name="Test Admin",
        email="admin@example.com",
        roles=[UserRole.ADMIN],
        raw_roles=["admin"],
        tenant_id="tenant-test",
        allowed_subscriptions=[],
    )


async def make_read_user() -> UserContext:
    return UserContext(
        user_id="test-reader",
        object_id="11111111-1111-1111-1111-111111111111",
        display_name="Test Reader",
        email="reader@example.com",
        roles=[UserRole.READ],
        raw_roles=["read"],
        tenant_id="tenant-test",
        allowed_subscriptions=[],
    )


# ── FastAPI app + clients ──────────────────────────────────────────────────────


@pytest.fixture
def app():
    return create_application()


@pytest.fixture
async def admin_client(app, db_session):
    """Client with admin auth and SQLite DB."""

    async def _get_db_override():
        yield db_session

    app.dependency_overrides[get_db] = _get_db_override
    app.dependency_overrides[get_current_user] = make_admin_user

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()


@pytest.fixture
async def reader_client(app, db_session):
    """Client with read-only auth and SQLite DB."""

    async def _get_db_override():
        yield db_session

    app.dependency_overrides[get_db] = _get_db_override
    app.dependency_overrides[get_current_user] = make_read_user

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()


@pytest.fixture
async def client(app):
    """Unauthenticated client — no DB override (for health / public tests)."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
