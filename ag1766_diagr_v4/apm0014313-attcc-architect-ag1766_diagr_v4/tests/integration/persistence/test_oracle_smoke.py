"""Opt-in Oracle integration smoke tests."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import text

from pathlib import Path

from migration_intake.persistence.database import (
    check_schema_current,
    configure_oracle_client,
    create_engine_from_url,
)

if TYPE_CHECKING:
    from collections.abc import Generator

    from sqlalchemy.engine import Engine


pytestmark = pytest.mark.oracle


@pytest.fixture
def oracle_engine() -> Generator[Engine, None, None]:
    """Create an Oracle engine from the opt-in integration-test URL."""
    database_url = os.environ.get("DATABASE_URL") or os.environ.get("ORACLE_TEST_URL")
    if not database_url:
        pytest.skip("ORACLE_TEST_URL is not configured")

    client_dir = os.environ.get("AWS_OUTPOST_ORACLE_CLIENT_LIB_DIR") or os.environ.get(
        "ORACLE_CLIENT_LIB_DIR"
    )
    configure_oracle_client(Path(client_dir) if client_dir else None)
    engine = create_engine_from_url(database_url)
    try:
        yield engine
    finally:
        engine.dispose()


def test_oracle_schema_is_current_and_queryable(oracle_engine: Engine) -> None:
    """Verify the migrated Oracle schema and a basic connection query."""
    assert check_schema_current(oracle_engine)

    with oracle_engine.connect() as connection:
        result = connection.execute(text("SELECT 1 FROM dual"))
        assert result.scalar_one() == 1
