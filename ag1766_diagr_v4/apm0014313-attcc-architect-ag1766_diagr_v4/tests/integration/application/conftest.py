"""
Shared pytest fixtures for integration/application tests.

Uses create_engine_from_url so SQLite FK enforcement, WAL mode, and
busy-timeout pragmas are applied on every connection.
"""

from __future__ import annotations

import pytest
from sqlalchemy.orm import sessionmaker

from migration_intake.persistence.database import create_engine_from_url
from migration_intake.persistence.naming import Base

# Side-effect import: registers all ORM tables in Base.metadata.
import migration_intake.persistence.models  # noqa: F401


@pytest.fixture(scope="function")
def tmp_engine(tmp_path):
    """File-based SQLite engine with all tables created fresh per test."""
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
