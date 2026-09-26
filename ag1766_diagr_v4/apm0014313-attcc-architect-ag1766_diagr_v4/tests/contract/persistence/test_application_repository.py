"""
Contract tests for ApplicationRepository — P04 (Repositories and Unit of Work).

TDD discipline: this file is written BEFORE the implementation exists.
It fails with ImportError at collection time until the repository module is
implemented; every test must then pass in the GREEN phase.

Coverage:
  1. Insert application; reload in new session proves persistence.
  2. Duplicate (identifier_type, normalized_value) raises IntegrityError.
  3. Optimistic update with correct row_version succeeds (returns True, version ++).
  4. Optimistic update with stale row_version returns False; state unchanged.
  5. get_by_normalized_identifier returns application or None.
  6. Insert identifier; reload in new session confirms persistence.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

# ── RED import — fails with ImportError until the module is implemented ──────
from migration_intake.persistence.repositories.applications import (  # noqa: E402
    ApplicationRepository,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _now() -> datetime:
    return datetime.now(tz=timezone.utc)


def _insert_actor(engine, actor_id: str | None = None) -> str:
    """Insert an Actor row (no FK deps) and return its UUID string."""
    from migration_intake.persistence.models import Actor

    if actor_id is None:
        actor_id = str(uuid.uuid4())
    with Session(engine) as session:
        session.add(
            Actor(id=actor_id, display_name="Test Actor", created_at=_now())
        )
        session.commit()
    return actor_id


# ---------------------------------------------------------------------------
# Test 1 — add and reload proves persistence
# ---------------------------------------------------------------------------


def test_add_and_reload_application(tmp_engine) -> None:
    """Insert application; reload in new session proves persistence."""
    actor_id = _insert_actor(tmp_engine)
    now = _now()
    app_id = str(uuid.uuid4())

    # Write in session 1
    with Session(tmp_engine) as session:
        repo = ApplicationRepository(session)
        returned_id = repo.add(
            actor_id=actor_id,
            display_name="Persistence Test App",
            state="ACTIVE",
            created_at=now,
            application_id=app_id,
        )
        session.commit()

    assert returned_id == app_id

    # Reload in session 2 — must hit the DB, not the session cache
    with Session(tmp_engine) as session:
        repo = ApplicationRepository(session)
        app = repo.get(app_id)

    assert app is not None
    assert str(app["id"]) == app_id
    assert app["display_name"] == "Persistence Test App"
    assert app["state"] == "ACTIVE"
    assert str(app["created_by_id"]) == actor_id
    assert app["row_version"] == 1
    assert app["created_at"] is not None
    assert app["updated_at"] is not None


# ---------------------------------------------------------------------------
# Test 2 — duplicate normalized identifier raises IntegrityError
# ---------------------------------------------------------------------------


def test_duplicate_normalized_identifier_raises(tmp_engine) -> None:
    """Inserting same (identifier_type, normalized_value) twice → IntegrityError."""
    actor_id = _insert_actor(tmp_engine)
    now = _now()

    # Create application + first identifier
    with Session(tmp_engine) as session:
        repo = ApplicationRepository(session)
        app_id = repo.add(
            actor_id=actor_id,
            display_name="Dup ID Test App",
            state="ACTIVE",
            created_at=now,
        )
        repo.add_identifier(
            application_id=app_id,
            identifier_type="ITAP",
            raw_value="12345",
            normalized_value="12345",
            created_at=now,
        )
        session.commit()

    # Second insert with same (type, normalized_value) must raise
    with pytest.raises(IntegrityError):
        with Session(tmp_engine) as session:
            repo = ApplicationRepository(session)
            repo.add_identifier(
                application_id=app_id,
                identifier_type="ITAP",
                raw_value="12345",
                normalized_value="12345",
                created_at=now,
            )
            session.commit()


# ---------------------------------------------------------------------------
# Test 3 — optimistic update with correct version succeeds
# ---------------------------------------------------------------------------


def test_update_state_with_correct_version_succeeds(tmp_engine) -> None:
    """Optimistic update with correct row_version=1 → True, version becomes 2."""
    actor_id = _insert_actor(tmp_engine)
    now = _now()

    with Session(tmp_engine) as session:
        repo = ApplicationRepository(session)
        app_id = repo.add(
            actor_id=actor_id,
            display_name="Optimistic App",
            state="ACTIVE",
            created_at=now,
        )
        session.commit()

    # Update with correct expected_version=1
    with Session(tmp_engine) as session:
        repo = ApplicationRepository(session)
        result = repo.update_state(
            application_id=app_id,
            new_state="ON_HOLD",
            expected_version=1,
            updated_at=now,
        )
        session.commit()

    assert result is True

    # Verify new state and incremented version in fresh session
    with Session(tmp_engine) as session:
        repo = ApplicationRepository(session)
        app = repo.get(app_id)

    assert app is not None
    assert app["state"] == "ON_HOLD"
    assert app["row_version"] == 2


# ---------------------------------------------------------------------------
# Test 4 — optimistic update with stale version returns False
# ---------------------------------------------------------------------------


def test_update_state_with_stale_version_returns_false(tmp_engine) -> None:
    """Optimistic update with stale row_version → False; canonical state unchanged."""
    actor_id = _insert_actor(tmp_engine)
    now = _now()

    with Session(tmp_engine) as session:
        repo = ApplicationRepository(session)
        app_id = repo.add(
            actor_id=actor_id,
            display_name="Stale Version App",
            state="ACTIVE",
            created_at=now,
        )
        session.commit()

    # Update with wrong expected_version=99 (actual is 1)
    with Session(tmp_engine) as session:
        repo = ApplicationRepository(session)
        result = repo.update_state(
            application_id=app_id,
            new_state="ON_HOLD",
            expected_version=99,
            updated_at=now,
        )
        session.commit()

    assert result is False

    # State and version must be unchanged
    with Session(tmp_engine) as session:
        repo = ApplicationRepository(session)
        app = repo.get(app_id)

    assert app is not None
    assert app["state"] == "ACTIVE"
    assert app["row_version"] == 1


# ---------------------------------------------------------------------------
# Test 5 — get_by_normalized_identifier
# ---------------------------------------------------------------------------


def test_get_by_normalized_identifier(tmp_engine) -> None:
    """Find application by (identifier_type, normalized_value); None for miss."""
    actor_id = _insert_actor(tmp_engine)
    now = _now()

    with Session(tmp_engine) as session:
        repo = ApplicationRepository(session)
        app_id = repo.add(
            actor_id=actor_id,
            display_name="FindMe App",
            state="ACTIVE",
            created_at=now,
        )
        repo.add_identifier(
            application_id=app_id,
            identifier_type="ITAP",
            raw_value="99999",
            normalized_value="99999",
            created_at=now,
        )
        session.commit()

    # Hit — must return the application dict
    with Session(tmp_engine) as session:
        repo = ApplicationRepository(session)
        found = repo.get_by_normalized_identifier("ITAP", "99999")

    assert found is not None
    assert found["display_name"] == "FindMe App"
    assert str(found["id"]) == app_id

    # Miss — must return None
    with Session(tmp_engine) as session:
        repo = ApplicationRepository(session)
        missing = repo.get_by_normalized_identifier("ITAP", "00000")

    assert missing is None


# ---------------------------------------------------------------------------
# Test 6 — add_identifier persists; reload in new session confirms
# ---------------------------------------------------------------------------


def test_add_identifier_and_reload(tmp_engine) -> None:
    """Insert identifier; reload in new session confirms persistence."""
    from migration_intake.persistence.models import ApplicationIdentifier

    actor_id = _insert_actor(tmp_engine)
    now = _now()

    with Session(tmp_engine) as session:
        repo = ApplicationRepository(session)
        app_id = repo.add(
            actor_id=actor_id,
            display_name="Identifier Reload App",
            state="ACTIVE",
            created_at=now,
        )
        ident_id = repo.add_identifier(
            application_id=app_id,
            identifier_type="MOTS",
            raw_value="MOT-001",
            normalized_value="mot-001",
            created_at=now,
        )
        session.commit()

    # Reload in fresh session using ORM model directly
    with Session(tmp_engine) as session:
        ident = session.get(ApplicationIdentifier, ident_id)

    assert ident is not None
    assert ident.identifier_type == "MOTS"
    assert ident.raw_value == "MOT-001"
    assert ident.normalized_value == "mot-001"
    assert str(ident.application_id) == app_id
