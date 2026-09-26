"""
Shared pytest fixtures for contract/persistence tests.

Uses create_engine_from_url so SQLite FK enforcement, WAL mode, and
busy-timeout pragmas are applied on every connection — identical behaviour
to the production engine factory.
"""

from __future__ import annotations

import pytest
from sqlalchemy.orm import sessionmaker

from migration_intake.persistence.database import create_engine_from_url
from migration_intake.persistence.naming import Base

# Side-effect imports: register all ORM tables in Base.metadata.
import migration_intake.persistence.models  # noqa: F401
import migration_intake.persistence.models_evidence  # noqa: F401
import migration_intake.persistence.models_imports  # noqa: F401
import migration_intake.persistence.models_candidates  # noqa: F401
import migration_intake.persistence.models_snapshots  # noqa: F401
import migration_intake.persistence.models_ai  # noqa: F401


# ---------------------------------------------------------------------------
# Engine & session factory
# ---------------------------------------------------------------------------


@pytest.fixture(scope="function")
def tmp_engine(tmp_path: pytest.TempPathFactory):
    """
    File-based SQLite engine with all tables created fresh per test.

    Scoped to *function* so every test starts with an empty database,
    preventing state leaking between tests.
    """
    engine = create_engine_from_url(
        f"sqlite:///{tmp_path}/test.db",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture(scope="function")
def session_factory(tmp_engine):
    """Return a sessionmaker bound to the test engine."""
    return sessionmaker(bind=tmp_engine, autocommit=False, autoflush=False)
