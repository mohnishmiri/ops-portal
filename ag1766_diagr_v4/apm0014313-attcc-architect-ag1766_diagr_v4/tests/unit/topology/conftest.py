"""Fixtures for topology unit tests."""

from __future__ import annotations

import pytest

from migration_intake.persistence.database import create_engine_from_url
from migration_intake.persistence.naming import Base

# Register all ORM tables before metadata creation.
import migration_intake.persistence.models  # noqa: F401,E402
import migration_intake.persistence.models_topology  # noqa: F401,E402


@pytest.fixture(scope="function")
def tmp_engine(tmp_path):
    """Create a fresh SQLite database with the complete ORM schema."""
    engine = create_engine_from_url(
        f"sqlite:///{tmp_path / 'topology.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()
