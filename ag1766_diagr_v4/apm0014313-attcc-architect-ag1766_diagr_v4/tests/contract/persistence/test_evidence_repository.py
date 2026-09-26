"""
Contract tests for EvidenceRepository — P05 (Evidence and WaveUtil Persistence).

TDD discipline: written BEFORE implementation; fails with ImportError at
collection time until the repository is implemented.

Coverage:
  1. add + get in new session → correct plain dict with all fields.
  2. get_by_storage_key → returns the right evidence item.
  3. Duplicate storage_key → IntegrityError (UNIQUE constraint).
  4. list_for_intake → returns both ACTIVE items for an intake.
  5. update_state → persists new state; get shows updated value.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

# ── RED import — fails with ImportError until the module is implemented ──────
from migration_intake.persistence.repositories.evidence import EvidenceRepository  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_NOW = datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
_SHA256 = "a" * 64  # valid 64-char hex string


def _uid() -> str:
    return str(uuid.uuid4())


def _seed_actor(engine, actor_id: str) -> None:
    """Insert a minimal Actor row."""
    from migration_intake.persistence.models import Actor

    with Session(engine) as session:
        session.add(Actor(id=actor_id, display_name="Test Actor", created_at=_NOW))
        session.commit()


def _seed_application(engine, app_id: str, actor_id: str) -> None:
    """Insert a minimal Application row."""
    from migration_intake.persistence.models import Application

    with Session(engine) as session:
        session.add(
            Application(
                id=app_id,
                state="ACTIVE",
                display_name="Test App",
                created_at=_NOW,
                updated_at=_NOW,
                row_version=1,
                created_by_id=actor_id,
            )
        )
        session.commit()


def _seed_intake(engine, intake_id: str, app_id: str, actor_id: str) -> None:
    """Insert a minimal Intake row (requires a CatalogRelease)."""
    from migration_intake.persistence.models import CatalogRelease, Intake

    cat_id = _uid()
    with Session(engine) as session:
        session.add(
            CatalogRelease(
                id=cat_id,
                semantic_version="1.0.0",
                source_filename="v1.yaml",
                source_sha256="b" * 64,
                compiler_version="1.0",
                pub_state="PUBLISHED",
                created_at=_NOW,
            )
        )
        session.add(
            Intake(
                id=intake_id,
                application_id=app_id,
                catalog_id=cat_id,
                state="OPEN",
                created_at=_NOW,
                updated_at=_NOW,
                row_version=1,
                created_by_id=actor_id,
            )
        )
        session.commit()


# ---------------------------------------------------------------------------
# Test 1 — add + get round-trip
# ---------------------------------------------------------------------------


def test_add_and_get_evidence_item(tmp_engine) -> None:
    """add() returns a plain dict; get() in a new session returns correct fields."""
    actor_id = _uid()
    app_id = _uid()
    evidence_id = _uid()
    storage_key = f"aa/{_SHA256}"

    _seed_actor(tmp_engine, actor_id)
    _seed_application(tmp_engine, app_id, actor_id)

    # Write
    with Session(tmp_engine) as session:
        repo = EvidenceRepository(session)
        result = repo.add(
            evidence_id=evidence_id,
            application_id=app_id,
            intake_id=None,
            storage_key=storage_key,
            sha256_hex=_SHA256,
            size_bytes=4096,
            media_type="application/pdf",
            original_filename="report.pdf",
            created_at=_NOW,
            created_by_id=actor_id,
        )
        session.commit()

    # add() must return a plain dict
    assert isinstance(result, dict)
    assert result["id"] == evidence_id
    assert result["storage_key"] == storage_key
    assert result["sha256_hex"] == _SHA256
    assert result["state"] == "ACTIVE"

    # Read in a fresh session
    with Session(tmp_engine) as session:
        fetched = EvidenceRepository(session).get(evidence_id)

    assert fetched is not None
    assert fetched["id"] == evidence_id
    assert fetched["application_id"] == app_id
    assert fetched["intake_id"] is None
    assert fetched["size_bytes"] == 4096
    assert fetched["media_type"] == "application/pdf"
    assert fetched["original_filename"] == "report.pdf"
    assert fetched["state"] == "ACTIVE"
    assert fetched["created_by_id"] == actor_id


# ---------------------------------------------------------------------------
# Test 2 — get_by_storage_key
# ---------------------------------------------------------------------------


def test_get_by_storage_key(tmp_engine) -> None:
    """get_by_storage_key returns the evidence item for the given storage key."""
    actor_id = _uid()
    app_id = _uid()
    evidence_id = _uid()
    sha256 = "c" * 64
    storage_key = f"cc/{sha256}"

    _seed_actor(tmp_engine, actor_id)
    _seed_application(tmp_engine, app_id, actor_id)

    with Session(tmp_engine) as session:
        EvidenceRepository(session).add(
            evidence_id=evidence_id,
            application_id=app_id,
            intake_id=None,
            storage_key=storage_key,
            sha256_hex=sha256,
            size_bytes=512,
            media_type="image/png",
            original_filename=None,
            created_at=_NOW,
            created_by_id=actor_id,
        )
        session.commit()

    with Session(tmp_engine) as session:
        item = EvidenceRepository(session).get_by_storage_key(storage_key)

    assert item is not None
    assert item["id"] == evidence_id
    assert item["storage_key"] == storage_key

    # Non-existent key returns None
    with Session(tmp_engine) as session:
        assert EvidenceRepository(session).get_by_storage_key("no/such/key") is None


# ---------------------------------------------------------------------------
# Test 3 — duplicate storage_key raises IntegrityError
# ---------------------------------------------------------------------------


def test_duplicate_storage_key_raises_integrity_error(tmp_engine) -> None:
    """Inserting two items with the same (app, intake, storage_key) raises IntegrityError."""
    actor_id = _uid()
    app_id = _uid()
    intake_id = _uid()
    sha256 = "d" * 64
    storage_key = f"dd/{sha256}"

    _seed_actor(tmp_engine, actor_id)
    _seed_application(tmp_engine, app_id, actor_id)
    _seed_intake(tmp_engine, intake_id, app_id, actor_id)

    with Session(tmp_engine) as session:
        EvidenceRepository(session).add(
            evidence_id=_uid(),
            application_id=app_id,
            intake_id=intake_id,
            storage_key=storage_key,
            sha256_hex=sha256,
            size_bytes=100,
            media_type="application/octet-stream",
            original_filename=None,
            created_at=_NOW,
            created_by_id=actor_id,
        )
        session.commit()

    with pytest.raises(IntegrityError):
        with Session(tmp_engine) as session:
            EvidenceRepository(session).add(
                evidence_id=_uid(),
                application_id=app_id,
                intake_id=intake_id,
                storage_key=storage_key,  # duplicate!
                sha256_hex=sha256,
                size_bytes=200,
                media_type="application/octet-stream",
                original_filename=None,
                created_at=_NOW,
                created_by_id=actor_id,
            )
            session.commit()


# ---------------------------------------------------------------------------
# Test 4 — list_for_intake
# ---------------------------------------------------------------------------


def test_list_for_intake(tmp_engine) -> None:
    """list_for_intake returns all ACTIVE evidence items for the given intake."""
    actor_id = _uid()
    app_id = _uid()
    intake_id = _uid()

    _seed_actor(tmp_engine, actor_id)
    _seed_application(tmp_engine, app_id, actor_id)
    _seed_intake(tmp_engine, intake_id, app_id, actor_id)

    ev1 = _uid()
    ev2 = _uid()

    with Session(tmp_engine) as session:
        repo = EvidenceRepository(session)
        repo.add(
            evidence_id=ev1,
            application_id=app_id,
            intake_id=intake_id,
            storage_key=f"e1/{'e' * 64}",
            sha256_hex="e" * 64,
            size_bytes=111,
            media_type="text/plain",
            original_filename="file1.txt",
            created_at=_NOW,
            created_by_id=actor_id,
        )
        repo.add(
            evidence_id=ev2,
            application_id=app_id,
            intake_id=intake_id,
            storage_key=f"f2/{'f' * 64}",
            sha256_hex="f" * 64,
            size_bytes=222,
            media_type="text/plain",
            original_filename="file2.txt",
            created_at=_NOW,
            created_by_id=actor_id,
        )
        session.commit()

    with Session(tmp_engine) as session:
        items = EvidenceRepository(session).list_for_intake(intake_id)

    assert len(items) == 2
    ids = {i["id"] for i in items}
    assert ev1 in ids
    assert ev2 in ids
    assert all(i["state"] == "ACTIVE" for i in items)


# ---------------------------------------------------------------------------
# Test 5 — update_state
# ---------------------------------------------------------------------------


def test_update_state(tmp_engine) -> None:
    """update_state persists the new state; get() in a new session reflects it."""
    actor_id = _uid()
    app_id = _uid()
    evidence_id = _uid()
    sha256 = "9" * 64
    storage_key = f"99/{sha256}"

    _seed_actor(tmp_engine, actor_id)
    _seed_application(tmp_engine, app_id, actor_id)

    with Session(tmp_engine) as session:
        EvidenceRepository(session).add(
            evidence_id=evidence_id,
            application_id=app_id,
            intake_id=None,
            storage_key=storage_key,
            sha256_hex=sha256,
            size_bytes=50,
            media_type="application/octet-stream",
            original_filename=None,
            created_at=_NOW,
            created_by_id=actor_id,
        )
        session.commit()

    with Session(tmp_engine) as session:
        updated = EvidenceRepository(session).update_state(evidence_id, "QUARANTINED")
        session.commit()

    assert updated is True

    with Session(tmp_engine) as session:
        fetched = EvidenceRepository(session).get(evidence_id)

    assert fetched is not None
    assert fetched["state"] == "QUARANTINED"

    # Non-existent ID returns False
    with Session(tmp_engine) as session:
        not_found = EvidenceRepository(session).update_state(_uid(), "DELETED")
    assert not_found is False
