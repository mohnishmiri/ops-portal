"""Applies the SQL migrations in ``backend/migrations/`` at startup.

``Base.metadata.create_all`` creates *missing tables* but never adds a *column*
to a table that already exists. Those columns were previously backfilled by
hand-written ``ALTER TABLE`` calls in ``create_tables()`` — a second place to
remember, and forgetting it is silent: the model has the attribute, the database
does not, and every query touching it fails at runtime.

That is what happened to ``cert_certificates.deleted_at``: the migration file was
written, never applied, and certificate sync failed against a column Postgres had
never heard of.

So the migration files apply themselves. Dropping a ``.sql`` file in
``backend/migrations/`` is now sufficient; applied filenames are recorded in
``schema_migrations`` so each runs once.

Migrations must be idempotent (``IF NOT EXISTS`` / ``IF EXISTS``) — a file may be
re-run against a database that was already migrated by hand.
"""

from __future__ import annotations

from pathlib import Path

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

logger = structlog.get_logger(__name__)

MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "migrations"

# Serializes migrations across workers: several uvicorn processes starting at
# once would otherwise run the same DDL concurrently and deadlock.
_ADVISORY_LOCK_KEY = 4_190_231_776

_TRACKING_TABLE = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    filename   VARCHAR(255) PRIMARY KEY,
    applied_at TIMESTAMP NOT NULL DEFAULT NOW()
)
"""


def _split_statements(sql: str) -> list[str]:
    """Split a migration file into individual statements.

    asyncpg sends one statement per round trip, so a multi-statement file has to
    be split. Comments are stripped *before* splitting: these files document
    their own ``psql`` invocation in a header comment, and prose there contains
    semicolons that would otherwise cut a comment in half and send the remainder
    to the server as SQL.

    A dollar-quoted body (``$$ ... $$``) may legitimately contain semicolons, so
    a file using one is sent whole rather than mis-split. ``--`` inside a string
    literal is not handled; no migration needs one.
    """
    uncommented = "\n".join(line.split("--", 1)[0] for line in sql.splitlines())

    if "$$" in uncommented:
        stripped = uncommented.strip()
        return [stripped] if stripped else []

    return [chunk.strip() for chunk in uncommented.split(";") if chunk.strip()]


async def run_sql_migrations(conn: AsyncConnection) -> list[str]:
    """Apply any unapplied migration files. Returns the filenames applied.

    PostgreSQL only — the files use Postgres DDL, and the SQLite test database is
    built from model metadata instead.
    """
    if conn.dialect.name != "postgresql":
        return []
    if not MIGRATIONS_DIR.is_dir():
        logger.warning("sql_migrations_dir_missing", path=str(MIGRATIONS_DIR))
        return []

    await conn.execute(text(_TRACKING_TABLE))
    # Held until the surrounding transaction ends.
    await conn.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": _ADVISORY_LOCK_KEY})

    result = await conn.execute(text("SELECT filename FROM schema_migrations"))
    already_applied = {row[0] for row in result}

    applied: list[str] = []
    for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
        if path.name in already_applied:
            continue
        try:
            for statement in _split_statements(path.read_text()):
                await conn.execute(text(statement))
            await conn.execute(
                text("INSERT INTO schema_migrations (filename) VALUES (:f) ON CONFLICT DO NOTHING"),
                {"f": path.name},
            )
            applied.append(path.name)
            logger.info("sql_migration_applied", filename=path.name)
        except Exception as exc:
            # Left unrecorded so the next start retries it. Logged at error
            # because the alternative — a model column the database lacks — fails
            # far away from the cause.
            logger.error("sql_migration_failed", filename=path.name, error=str(exc)[:300])
            raise

    return applied
