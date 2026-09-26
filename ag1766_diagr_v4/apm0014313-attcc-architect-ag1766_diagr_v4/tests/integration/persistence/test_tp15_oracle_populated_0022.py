"""TP15 populated Oracle 0021-to-0022 migration contract without schema reset."""

from __future__ import annotations

import os
import uuid
from pathlib import Path

import pytest
from sqlalchemy import inspect, text

from migration_intake.persistence.database import configure_oracle_client, create_engine_from_url

pytestmark = pytest.mark.oracle


def test_populated_oracle_0022_objects_preserve_existing_application() -> None:
    url = os.environ.get("DATABASE_URL") or os.environ.get("ORACLE_TEST_URL")
    if not url:
        pytest.skip("Oracle certification URL is not configured")
    client = os.environ.get("AWS_OUTPOST_ORACLE_CLIENT_LIB_DIR") or os.environ.get(
        "ORACLE_CLIENT_LIB_DIR"
    )
    configure_oracle_client(Path(client) if client else None)
    engine = create_engine_from_url(url)
    synthetic_id = str(uuid.uuid4())
    try:
        inspector = inspect(engine)
        columns = {item["name"].lower() for item in inspector.get_columns("applications")}
        assert "interface_epoch" in columns
        indexes = {item["name"] for item in inspector.get_indexes("interfaces")}
        assert "ix_irec_app_state_id" in indexes
        with engine.begin() as connection:
            actor_id = connection.execute(
                text("SELECT id FROM actors WHERE ROWNUM = 1")
            ).scalar_one_or_none()
            if actor_id is None:
                pytest.skip("Authorized schema has no synthetic actor fixture")
            connection.execute(
                text(
                    "INSERT INTO applications "
                    "(id,state,display_name,created_at,updated_at,row_version,created_by_id,interface_epoch) "
                    "VALUES (:id,'ACTIVE','TP15 populated migration',:now,:now,1,:actor,1)"
                ),
                {"id": synthetic_id, "now": "2026-09-23T00:00:00.000Z", "actor": actor_id},
            )
            row = connection.execute(
                text("SELECT display_name, interface_epoch FROM applications WHERE id=:id"),
                {"id": synthetic_id},
            ).one()
            assert row[0] == "TP15 populated migration"
            assert row[1] == 1
            connection.execute(text("DELETE FROM applications WHERE id=:id"), {"id": synthetic_id})
    finally:
        engine.dispose()
