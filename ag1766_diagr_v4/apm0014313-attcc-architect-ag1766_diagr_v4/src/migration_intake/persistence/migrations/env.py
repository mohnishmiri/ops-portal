"""Alembic environment configuration.

Design rules (Architecture section 37):
- The database URL is read from AWS_OUTPOST_DATABASE_URL.
  If not set, falls back to sqlalchemy.url from the Alembic config object
  (useful for CLI invocations and test helpers that set the URL programmatically
  via cfg.set_main_option).
- Credentials are NEVER logged or embedded in alembic.ini.
- Full application Settings are NOT imported here; only the ORM models and
  Base are imported so that Alembic can build the target metadata graph.
- SQLite migrations use render_as_batch=True so that ALTER TABLE operations
  (which SQLite does not support natively) are handled via table-recreation.
"""
from __future__ import annotations

import os
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from dotenv import load_dotenv
from sqlalchemy import engine_from_config, pool

# Register all ORM models so Alembic sees every table in target_metadata.
import migration_intake.persistence.models
import migration_intake.persistence.models_evidence
import migration_intake.persistence.models_imports
import migration_intake.persistence.models_interfaces
import migration_intake.persistence.models_resources
import migration_intake.persistence.models_snapshots
import migration_intake.persistence.models_templates  # noqa: F401
import migration_intake.persistence.models_topology  # noqa: F401
from migration_intake.persistence.naming import Base

# ---------------------------------------------------------------------------
# Alembic Config object — access to alembic.ini values.
# ---------------------------------------------------------------------------

config = context.config

# Match application startup for CLI use, but preserve URLs supplied explicitly
# by callers such as isolated migration tests.
if not os.environ.get("AWS_OUTPOST_DATABASE_URL") and not config.get_main_option(
    "sqlalchemy.url"
):
    load_dotenv(Path.cwd() / ".env", override=False)

# Attach Python logging configuration from alembic.ini (if present).
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _get_url() -> str:
    """
    Return the database URL for migrations.

    Priority:
    1. AWS_OUTPOST_DATABASE_URL environment variable (production / CI).
    2. sqlalchemy.url set programmatically on the Alembic Config object
       (used by test helpers: cfg.set_main_option("sqlalchemy.url", ...)).

    Raises RuntimeError when neither source provides a URL.
    """
    url = os.environ.get("AWS_OUTPOST_DATABASE_URL", "")
    if not url:
        # Fall back to the value set on the config object (e.g. in tests or
        # when invoked via Python API rather than the CLI).
        url = config.get_main_option("sqlalchemy.url") or ""
    if not url:
        raise RuntimeError(
            "AWS_OUTPOST_DATABASE_URL environment variable is required for migrations. "
            "Set AWS_OUTPOST_DATABASE_URL before running Alembic commands."
        )
    return url


# ---------------------------------------------------------------------------
# Offline mode — generates SQL without a live connection
# ---------------------------------------------------------------------------


def run_migrations_offline() -> None:
    """Emit SQL to stdout without connecting to the database."""
    url = _get_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=url.startswith("sqlite"),
    )
    with context.begin_transaction():
        context.run_migrations()


# ---------------------------------------------------------------------------
# Online mode — executes against a live connection
# ---------------------------------------------------------------------------


def run_migrations_online() -> None:
    """Run migrations against a live database connection."""
    url = _get_url()
    is_sqlite = url.startswith("sqlite")
    is_oracle = "oracle" in url.lower()

    # Initialize Oracle thick mode if configured
    if is_oracle:
        oracle_client_lib_dir = os.environ.get("AWS_OUTPOST_ORACLE_CLIENT_LIB_DIR")
        if oracle_client_lib_dir:
            import oracledb
            if oracledb.is_thin_mode():
                oracledb.init_oracle_client(lib_dir=oracle_client_lib_dir)

    connect_args: dict[str, object] = {}
    if is_sqlite:
        connect_args["check_same_thread"] = False

    connectable = engine_from_config(
        {"sqlalchemy.url": url},
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
        connect_args=connect_args,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=is_sqlite,
        )
        with context.begin_transaction():
            context.run_migrations()


# ---------------------------------------------------------------------------
# Entry point — called by Alembic
# ---------------------------------------------------------------------------

if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
