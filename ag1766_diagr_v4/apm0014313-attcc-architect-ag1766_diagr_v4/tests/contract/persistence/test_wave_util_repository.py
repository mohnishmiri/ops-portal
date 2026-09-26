"""
Contract tests for WaveUtilRepository — P05 (Evidence and WaveUtil Persistence).

TDD discipline: written BEFORE implementation; fails with ImportError at
collection time until the repository is implemented.

Coverage:
  1. add_row + get_row in new session → correct plain dict with server_name.
  2. add_revision + advance_pointer → get_current_revision returns revision dict.
  3. Duplicate (row_id, revision_number) → IntegrityError (append-only).
  4. Duplicate (application_id, normalized_server_name) → IntegrityError.
  5. Same normalized_server_name, different application_id → both succeed.
  6. get_by_normalized_name → returns correct row.
  7. list_rows_for_application → returns all rows for the application (3 of 3).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

# ── RED import — fails with ImportError until the module is implemented ──────
from migration_intake.persistence.repositories.wave_util import WaveUtilRepository  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_NOW = datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc)


def _uid() -> str:
    return str(uuid.uuid4())


def _seed_actor(engine, actor_id: str) -> None:
    from migration_intake.persistence.models import Actor

    with Session(engine) as session:
        session.add(Actor(id=actor_id, display_name="Wave Actor", created_at=_NOW))
        session.commit()


def _seed_application(engine, app_id: str, actor_id: str) -> None:
    from migration_intake.persistence.models import Application

    with Session(engine) as session:
        session.add(
            Application(
                id=app_id,
                state="ACTIVE",
                display_name="Wave App",
                created_at=_NOW,
                updated_at=_NOW,
                row_version=1,
                created_by_id=actor_id,
            )
        )
        session.commit()


def _add_row(
    engine,
    *,
    row_id: str,
    app_id: str,
    actor_id: str,
    server_name: str = "Server01",
    normalized: str = "server01",
) -> dict:
    """Insert a wave_util_rows row and return the dict."""
    with Session(engine) as session:
        repo = WaveUtilRepository(session)
        result = repo.add_row(
            row_id=row_id,
            application_id=app_id,
            intake_id=None,
            server_name=server_name,
            normalized_server_name=normalized,
            environment="PROD",
            scope="IN_SCOPE",
            created_at=_NOW,
            created_by_id=actor_id,
        )
        session.commit()
    return result


# ---------------------------------------------------------------------------
# Test 1 — add_row + get_row round-trip
# ---------------------------------------------------------------------------


def test_add_row_and_get(tmp_engine) -> None:
    """add_row returns a plain dict; get_row in a new session returns server_name."""
    actor_id = _uid()
    app_id = _uid()
    row_id = _uid()

    _seed_actor(tmp_engine, actor_id)
    _seed_application(tmp_engine, app_id, actor_id)

    result = _add_row(
        tmp_engine,
        row_id=row_id,
        app_id=app_id,
        actor_id=actor_id,
        server_name="WebServer01",
        normalized="webserver01",
    )

    assert isinstance(result, dict)
    assert result["id"] == row_id
    assert result["server_name"] == "WebServer01"
    assert result["state"] == "ACTIVE"
    assert result["current_rev_id"] is None

    with Session(tmp_engine) as session:
        fetched = WaveUtilRepository(session).get_row(row_id)

    assert fetched is not None
    assert fetched["id"] == row_id
    assert fetched["application_id"] == app_id
    assert fetched["server_name"] == "WebServer01"
    assert fetched["normalized_server_name"] == "webserver01"
    assert fetched["environment"] == "PROD"
    assert fetched["row_version"] == 1


# ---------------------------------------------------------------------------
# Test 2 — add_revision + advance_pointer → get_current_revision
# ---------------------------------------------------------------------------


def test_add_revision_and_advance_pointer(tmp_engine) -> None:
    """advance_current_pointer links the row to the revision; get_current_revision returns it."""
    actor_id = _uid()
    app_id = _uid()
    row_id = _uid()
    rev_id = _uid()

    _seed_actor(tmp_engine, actor_id)
    _seed_application(tmp_engine, app_id, actor_id)
    _add_row(tmp_engine, row_id=row_id, app_id=app_id, actor_id=actor_id)

    field_values = {"cpu_cores": 8, "ram_gb": 32, "os": "Linux"}

    with Session(tmp_engine) as session:
        repo = WaveUtilRepository(session)
        repo.add_revision(
            revision_id=rev_id,
            row_id=row_id,
            revision_number=1,
            field_values_json=field_values,
            authored_at=_NOW,
            authored_by_id=actor_id,
        )
        repo.advance_current_pointer(row_id, rev_id)
        session.commit()

    with Session(tmp_engine) as session:
        current = WaveUtilRepository(session).get_current_revision(row_id)

    assert current is not None
    assert current["id"] == rev_id
    assert current["row_id"] == row_id
    assert current["revision_number"] == 1
    assert current["field_values_json"] == field_values
    assert current["authored_by_id"] == actor_id

    # After advance, the row's current_rev_id must point to the revision
    with Session(tmp_engine) as session:
        row = WaveUtilRepository(session).get_row(row_id)
    assert row is not None
    assert row["current_rev_id"] == rev_id
    assert row["row_version"] == 2  # incremented by advance_current_pointer


# ---------------------------------------------------------------------------
# Test 3 — duplicate revision_number raises IntegrityError (append-only)
# ---------------------------------------------------------------------------


def test_duplicate_revision_number_raises(tmp_engine) -> None:
    """Inserting revision_number=1 twice for the same row raises IntegrityError."""
    actor_id = _uid()
    app_id = _uid()
    row_id = _uid()

    _seed_actor(tmp_engine, actor_id)
    _seed_application(tmp_engine, app_id, actor_id)
    _add_row(tmp_engine, row_id=row_id, app_id=app_id, actor_id=actor_id)

    with Session(tmp_engine) as session:
        WaveUtilRepository(session).add_revision(
            revision_id=_uid(),
            row_id=row_id,
            revision_number=1,
            field_values_json={"v": "first"},
            authored_at=_NOW,
            authored_by_id=actor_id,
        )
        session.commit()

    with pytest.raises(IntegrityError):
        with Session(tmp_engine) as session:
            WaveUtilRepository(session).add_revision(
                revision_id=_uid(),
                row_id=row_id,
                revision_number=1,  # duplicate!
                field_values_json={"v": "duplicate"},
                authored_at=_NOW,
                authored_by_id=actor_id,
            )
            session.commit()


# ---------------------------------------------------------------------------
# Test 4 — duplicate (application_id, normalized_server_name) raises IntegrityError
# ---------------------------------------------------------------------------


def test_unique_normalized_server_name_per_application(tmp_engine) -> None:
    """Two rows with same app + normalized_server_name violate the UNIQUE constraint."""
    actor_id = _uid()
    app_id = _uid()

    _seed_actor(tmp_engine, actor_id)
    _seed_application(tmp_engine, app_id, actor_id)

    _add_row(
        tmp_engine,
        row_id=_uid(),
        app_id=app_id,
        actor_id=actor_id,
        server_name="MyServer",
        normalized="myserver",
    )

    with pytest.raises(IntegrityError):
        _add_row(
            tmp_engine,
            row_id=_uid(),
            app_id=app_id,
            actor_id=actor_id,
            server_name="MyServer",  # same app + same normalized name → conflict
            normalized="myserver",
        )


# ---------------------------------------------------------------------------
# Test 5 — same normalized_server_name, different application → both succeed
# ---------------------------------------------------------------------------


def test_same_server_name_different_application_allowed(tmp_engine) -> None:
    """The same normalized_server_name may exist in different applications."""
    actor_id = _uid()
    app_id_1 = _uid()
    app_id_2 = _uid()

    _seed_actor(tmp_engine, actor_id)
    _seed_application(tmp_engine, app_id_1, actor_id)
    _seed_application(tmp_engine, app_id_2, actor_id)

    # Both inserts must succeed
    _add_row(
        tmp_engine,
        row_id=_uid(),
        app_id=app_id_1,
        actor_id=actor_id,
        server_name="SharedServer",
        normalized="sharedserver",
    )
    _add_row(
        tmp_engine,
        row_id=_uid(),
        app_id=app_id_2,
        actor_id=actor_id,
        server_name="SharedServer",
        normalized="sharedserver",
    )


# ---------------------------------------------------------------------------
# Test 6 — get_by_normalized_name
# ---------------------------------------------------------------------------


def test_get_by_normalized_name(tmp_engine) -> None:
    """get_by_normalized_name returns the correct row for (application_id, name)."""
    actor_id = _uid()
    app_id = _uid()
    row_id = _uid()

    _seed_actor(tmp_engine, actor_id)
    _seed_application(tmp_engine, app_id, actor_id)
    _add_row(
        tmp_engine,
        row_id=row_id,
        app_id=app_id,
        actor_id=actor_id,
        server_name="FindMe",
        normalized="findme",
    )

    with Session(tmp_engine) as session:
        found = WaveUtilRepository(session).get_by_normalized_name(app_id, "findme")

    assert found is not None
    assert found["id"] == row_id
    assert found["server_name"] == "FindMe"

    # Wrong normalized name → None
    with Session(tmp_engine) as session:
        not_found = WaveUtilRepository(session).get_by_normalized_name(app_id, "nothere")
    assert not_found is None


# ---------------------------------------------------------------------------
# Test 7 — list_rows_for_application
# ---------------------------------------------------------------------------


def test_list_rows_for_application(tmp_engine) -> None:
    """list_rows_for_application returns all 3 ACTIVE rows for the application."""
    actor_id = _uid()
    app_id = _uid()
    other_app_id = _uid()

    _seed_actor(tmp_engine, actor_id)
    _seed_application(tmp_engine, app_id, actor_id)
    _seed_application(tmp_engine, other_app_id, actor_id)

    # Add 3 rows for app_id
    for i in range(3):
        _add_row(
            tmp_engine,
            row_id=_uid(),
            app_id=app_id,
            actor_id=actor_id,
            server_name=f"Server{i:02d}",
            normalized=f"server{i:02d}",
        )

    # Add 1 row for other_app_id — must not appear in results
    _add_row(
        tmp_engine,
        row_id=_uid(),
        app_id=other_app_id,
        actor_id=actor_id,
        server_name="OtherServer",
        normalized="otherserver",
    )

    with Session(tmp_engine) as session:
        rows = WaveUtilRepository(session).list_rows_for_application(app_id)

    assert len(rows) == 3
    assert all(r["application_id"] == app_id for r in rows)
    assert all(r["state"] == "ACTIVE" for r in rows)
