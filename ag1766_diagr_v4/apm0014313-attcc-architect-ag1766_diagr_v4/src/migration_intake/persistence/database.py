"""
SQLAlchemy engine factory, session factory, and diagnostic utilities.

Responsibilities:
- Create dialect-appropriate SQLAlchemy engines.
- Register the SQLite pragma listener (foreign_keys, WAL, synchronous,
  busy_timeout) on every new connection for SQLite engines.
- Provide a session factory with explicit-commit discipline.
- Redact credentials from database URLs before logging.
- Provide check_schema_current() for readiness-check / startup validation.

Design rules:
- Application services call commit() explicitly; repositories do not commit.
- Sessions are not shared across requests, threads, or background tasks.
- Engine diagnostics must never expose credentials.
- check_schema_current() NEVER runs migrations — it only reads alembic_version.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

#: Absolute path to the Alembic migrations directory (robust regardless of cwd).
_MIGRATIONS_DIR: Path = Path(__file__).parent / "migrations"

# ---------------------------------------------------------------------------
# SQLite pragma constants
# ---------------------------------------------------------------------------

#: Milliseconds SQLite waits before raising OperationalError on a locked DB.
SQLITE_BUSY_TIMEOUT_MS: int = 5_000

_SQLITE_JOURNAL_MODE: str = "WAL"
_SQLITE_SYNCHRONOUS: str = "NORMAL"


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _is_sqlite_url(database_url: str) -> bool:
    """Return True when the URL targets a SQLite database."""
    return database_url.startswith("sqlite")


def configure_oracle_client(client_lib_dir: Path | None) -> None:
    """Enable python-oracledb thick mode when an Instant Client path is configured."""
    if client_lib_dir is None:
        return

    import oracledb

    if oracledb.is_thin_mode():
        oracledb.init_oracle_client(lib_dir=str(client_lib_dir))


def _configure_sqlite_connection(dbapi_conn: Any, connection_record: Any) -> None:
    """
    Apply required SQLite pragmas on every new connection.

    Called automatically via SQLAlchemy's 'connect' event.  The pragmas must
    be applied per-connection, not per-engine, because SQLite resets them
    when a connection is recycled from the pool.

    Pragmas set:
    - ``foreign_keys=ON``    — enforce referential integrity
    - ``journal_mode=WAL``   — enable concurrent reads and writes
    - ``synchronous=NORMAL`` — balanced durability/performance for development
    - ``busy_timeout=<ms>``  — wait before raising on a locked database
    """
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute(f"PRAGMA journal_mode={_SQLITE_JOURNAL_MODE}")
    cursor.execute(f"PRAGMA synchronous={_SQLITE_SYNCHRONOUS}")
    cursor.execute(f"PRAGMA busy_timeout={SQLITE_BUSY_TIMEOUT_MS}")
    cursor.close()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def create_engine_from_url(database_url: str, **kwargs: Any) -> Engine:
    """
    Create a SQLAlchemy engine configured for the target dialect.

    For SQLite URLs the 'connect' event listener is registered so that
    foreign-key enforcement, WAL mode, and busy-timeout are applied on
    every connection checkout.  Oracle and PostgreSQL engines receive no
    extra dialect-specific setup in this slice.

    Args:
        database_url: SQLAlchemy-compatible database URL.
        **kwargs: Additional keyword arguments forwarded to ``create_engine``.

    Returns:
        A fully configured :class:`sqlalchemy.engine.Engine`.

    Example::

        engine = create_engine_from_url("sqlite:///data/app.db")
        engine = create_engine_from_url(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
        )
    """
    engine = create_engine(database_url, **kwargs)
    if _is_sqlite_url(database_url):
        event.listen(engine, "connect", _configure_sqlite_connection)
    return engine


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    """
    Create a session factory bound to the given engine.

    Sessions produced by this factory:
    - Do **not** autoflush (the application controls when to flush).
    - Do **not** autocommit (application services call ``commit()`` explicitly).
    - Expire objects after commit so the next access reloads from the database.

    Args:
        engine: A configured SQLAlchemy :class:`~sqlalchemy.engine.Engine`.

    Returns:
        A :class:`~sqlalchemy.orm.sessionmaker` callable.

    Example::

        Session = create_session_factory(engine)
        with Session() as session:
            ...
            session.commit()
    """
    return sessionmaker(
        bind=engine,
        autoflush=False,
        autocommit=False,
        expire_on_commit=True,
    )


def redact_url(database_url: str) -> str:
    """
    Return a copy of the database URL with credentials replaced.

    Replaces the ``username:password`` userinfo component with ``***:***``
    so the URL can be safely written to logs or diagnostic responses without
    exposing credentials.

    Args:
        database_url: A SQLAlchemy database URL, possibly containing credentials.

    Returns:
        The URL string with userinfo replaced by ``***:***``, or the original
        string unchanged when no credentials are present (e.g. SQLite).

    Examples::

        redact_url("postgresql://user:s3cr3t@host/db") -> "postgresql://***:***@host/db"
        redact_url("sqlite:///path/to/db.sqlite3")     -> "sqlite:///path/to/db.sqlite3"
    """
    return re.sub(r"://([^:@/\s]+:[^@/\s]+)@", "://***:***@", database_url)


def check_schema_current(engine: Engine) -> bool:
    """
    Return True if the database schema is at the current Alembic head revision.

    Compares the revision recorded in ``alembic_version`` against the head
    revision(s) declared by the migration scripts in this codebase.

    This is the **readiness-check hook** for application startup.  It performs
    a read-only query and does **not** run or apply any migrations.

    Returns False when:
    - The ``alembic_version`` table does not exist (fresh / unmanaged database).
    - The table is empty (partially initialised database).
    - The recorded revision(s) do not match the current head.
    - Any unexpected error occurs while reading the schema state.

    Args:
        engine: A configured :class:`~sqlalchemy.engine.Engine`.

    Returns:
        ``True`` if the schema is at head; ``False`` otherwise.

    Example::

        engine = create_engine_from_url(settings.effective_database_url)
        if not check_schema_current(engine):
            raise RuntimeError("Database schema is behind — run 'alembic upgrade head'.")
    """
    # Lazy imports: keep the alembic dependency out of the module-level import
    # graph so that alembic is only loaded when this function is called.
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    try:
        with engine.connect() as conn:
            result = conn.execute(text("SELECT version_num FROM alembic_version"))
            current_versions: set[str] = {str(row[0]).strip() for row in result}

        if not current_versions:
            return False

        cfg = Config()
        cfg.set_main_option("script_location", str(_MIGRATIONS_DIR))
        script = ScriptDirectory.from_config(cfg)
        head_revisions: set[str] = {
            rev.revision for rev in script.get_revisions("heads")
        }

        return bool(head_revisions) and head_revisions.issubset(current_versions)

    except Exception:
        # OperationalError (no such table), or any unexpected error — treat as
        # schema-behind so the readiness check fails safely.
        return False
