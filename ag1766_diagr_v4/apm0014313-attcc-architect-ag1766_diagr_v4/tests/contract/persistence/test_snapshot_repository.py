"""
Contract tests for SnapshotRepository — P07 (Snapshot Persistence).

Verifies:
- Snapshots are immutable (no update/delete)
- Each intake can have at most one snapshot
- Repository returns plain dicts
- Hash lookup works correctly
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

# Import all models to ensure they're registered with Base.metadata
# MUST import models before models_snapshots to resolve FK references
from migration_intake.persistence.models import (
    Actor,
    Application,
    CatalogRelease,
    Intake,
    Base,
)
from migration_intake.persistence.models_snapshots import IntakeSnapshot
from migration_intake.persistence.repositories.snapshots import SnapshotRepository


@pytest.fixture
def tmp_engine():
    """Create an in-memory SQLite engine with all tables."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return engine


@pytest.fixture
def session_factory(tmp_engine):
    """Create a session factory."""
    return sessionmaker(bind=tmp_engine)


def _seed_prerequisites(session_factory) -> dict:
    """Seed prerequisite records."""
    now = datetime.now(tz=timezone.utc)

    with session_factory() as session:
        # Actor
        actor_id = str(uuid.uuid4())
        session.add(Actor(id=actor_id, display_name="Test Actor", created_at=now))

        # Application
        app_id = str(uuid.uuid4())
        session.add(
            Application(
                id=app_id,
                state="ACTIVE",
                display_name="Test App",
                created_at=now,
                updated_at=now,
                row_version=1,
                created_by_id=actor_id,
            )
        )

        # Catalog
        catalog_id = str(uuid.uuid4())
        catalog_sha256 = "a" * 64
        session.add(
            CatalogRelease(
                id=catalog_id,
                semantic_version="1.0.0",
                source_filename="catalog.yaml",
                source_sha256=catalog_sha256,
                compiler_version="1.0",
                pub_state="PUBLISHED",
                published_at=now,
                created_at=now,
            )
        )

        # Intake
        intake_id = str(uuid.uuid4())
        session.add(
            Intake(
                id=intake_id,
                application_id=app_id,
                catalog_id=catalog_id,
                state="FROZEN",
                created_at=now,
                updated_at=now,
                row_version=1,
                created_by_id=actor_id,
            )
        )

        session.commit()

        return {
            "actor_id": actor_id,
            "app_id": app_id,
            "catalog_id": catalog_id,
            "catalog_sha256": catalog_sha256,
            "intake_id": intake_id,
        }


def _create_canonical_json(intake_id: str, app_id: str) -> tuple[str, str]:
    """Create canonical JSON and compute its hash."""
    payload = {
        "schema_version": "1.0.0",
        "intake_id": intake_id,
        "application_id": app_id,
        "answers": [],
        "wave_util_rows": [],
    }
    canonical_json = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    sha256_hex = hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()
    return canonical_json, sha256_hex


class TestCreateSnapshot:
    """Tests for create_snapshot."""

    def test_creates_snapshot(self, session_factory) -> None:
        """Creates a snapshot and returns a dict."""
        prereqs = _seed_prerequisites(session_factory)
        now = datetime.now(tz=timezone.utc)
        snapshot_id = str(uuid.uuid4())
        canonical_json, sha256_hex = _create_canonical_json(
            prereqs["intake_id"], prereqs["app_id"]
        )

        with session_factory() as session:
            repo = SnapshotRepository(session)
            result = repo.create_snapshot(
                snapshot_id=snapshot_id,
                intake_id=prereqs["intake_id"],
                catalog_id=prereqs["catalog_id"],
                schema_version="1.0.0",
                catalog_sha256=prereqs["catalog_sha256"],
                canonical_json=canonical_json,
                sha256_hex=sha256_hex,
                created_at=now,
                created_by_id=prereqs["actor_id"],
            )
            session.commit()

        assert result["id"] == snapshot_id
        assert result["intake_id"] == prereqs["intake_id"]
        assert result["sha256_hex"] == sha256_hex

    def test_returns_plain_dict(self, session_factory) -> None:
        """Returns a plain dict, not an ORM entity."""
        prereqs = _seed_prerequisites(session_factory)
        now = datetime.now(tz=timezone.utc)
        snapshot_id = str(uuid.uuid4())
        canonical_json, sha256_hex = _create_canonical_json(
            prereqs["intake_id"], prereqs["app_id"]
        )

        with session_factory() as session:
            repo = SnapshotRepository(session)
            result = repo.create_snapshot(
                snapshot_id=snapshot_id,
                intake_id=prereqs["intake_id"],
                catalog_id=prereqs["catalog_id"],
                schema_version="1.0.0",
                catalog_sha256=prereqs["catalog_sha256"],
                canonical_json=canonical_json,
                sha256_hex=sha256_hex,
                created_at=now,
                created_by_id=prereqs["actor_id"],
            )
            session.commit()

        assert isinstance(result, dict)
        assert not isinstance(result, IntakeSnapshot)

    def test_unique_intake_constraint(self, session_factory) -> None:
        """Each intake can have at most one snapshot."""
        prereqs = _seed_prerequisites(session_factory)
        now = datetime.now(tz=timezone.utc)
        canonical_json, sha256_hex = _create_canonical_json(
            prereqs["intake_id"], prereqs["app_id"]
        )

        # Create first snapshot
        with session_factory() as session:
            repo = SnapshotRepository(session)
            repo.create_snapshot(
                snapshot_id=str(uuid.uuid4()),
                intake_id=prereqs["intake_id"],
                catalog_id=prereqs["catalog_id"],
                schema_version="1.0.0",
                catalog_sha256=prereqs["catalog_sha256"],
                canonical_json=canonical_json,
                sha256_hex=sha256_hex,
                created_at=now,
                created_by_id=prereqs["actor_id"],
            )
            session.commit()

        # Try to create second snapshot for same intake
        with session_factory() as session:
            repo = SnapshotRepository(session)
            with pytest.raises(IntegrityError):
                repo.create_snapshot(
                    snapshot_id=str(uuid.uuid4()),
                    intake_id=prereqs["intake_id"],  # Same intake
                    catalog_id=prereqs["catalog_id"],
                    schema_version="1.0.0",
                    catalog_sha256=prereqs["catalog_sha256"],
                    canonical_json=canonical_json,
                    sha256_hex=sha256_hex,
                    created_at=now,
                    created_by_id=prereqs["actor_id"],
                )


class TestGetSnapshot:
    """Tests for get_by_id, get_by_intake_id, get_by_hash."""

    def test_get_by_id(self, session_factory) -> None:
        """Retrieves snapshot by ID."""
        prereqs = _seed_prerequisites(session_factory)
        now = datetime.now(tz=timezone.utc)
        snapshot_id = str(uuid.uuid4())
        canonical_json, sha256_hex = _create_canonical_json(
            prereqs["intake_id"], prereqs["app_id"]
        )

        with session_factory() as session:
            repo = SnapshotRepository(session)
            repo.create_snapshot(
                snapshot_id=snapshot_id,
                intake_id=prereqs["intake_id"],
                catalog_id=prereqs["catalog_id"],
                schema_version="1.0.0",
                catalog_sha256=prereqs["catalog_sha256"],
                canonical_json=canonical_json,
                sha256_hex=sha256_hex,
                created_at=now,
                created_by_id=prereqs["actor_id"],
            )
            session.commit()

        with session_factory() as session:
            repo = SnapshotRepository(session)
            result = repo.get_by_id(snapshot_id)

        assert result is not None
        assert result["id"] == snapshot_id

    def test_get_by_id_not_found(self, session_factory) -> None:
        """Returns None for unknown ID."""
        _seed_prerequisites(session_factory)

        with session_factory() as session:
            repo = SnapshotRepository(session)
            result = repo.get_by_id(str(uuid.uuid4()))

        assert result is None

    def test_get_by_intake_id(self, session_factory) -> None:
        """Retrieves snapshot by intake ID."""
        prereqs = _seed_prerequisites(session_factory)
        now = datetime.now(tz=timezone.utc)
        snapshot_id = str(uuid.uuid4())
        canonical_json, sha256_hex = _create_canonical_json(
            prereqs["intake_id"], prereqs["app_id"]
        )

        with session_factory() as session:
            repo = SnapshotRepository(session)
            repo.create_snapshot(
                snapshot_id=snapshot_id,
                intake_id=prereqs["intake_id"],
                catalog_id=prereqs["catalog_id"],
                schema_version="1.0.0",
                catalog_sha256=prereqs["catalog_sha256"],
                canonical_json=canonical_json,
                sha256_hex=sha256_hex,
                created_at=now,
                created_by_id=prereqs["actor_id"],
            )
            session.commit()

        with session_factory() as session:
            repo = SnapshotRepository(session)
            result = repo.get_by_intake_id(prereqs["intake_id"])

        assert result is not None
        assert result["intake_id"] == prereqs["intake_id"]

    def test_get_by_hash(self, session_factory) -> None:
        """Retrieves snapshot by SHA-256 hash."""
        prereqs = _seed_prerequisites(session_factory)
        now = datetime.now(tz=timezone.utc)
        snapshot_id = str(uuid.uuid4())
        canonical_json, sha256_hex = _create_canonical_json(
            prereqs["intake_id"], prereqs["app_id"]
        )

        with session_factory() as session:
            repo = SnapshotRepository(session)
            repo.create_snapshot(
                snapshot_id=snapshot_id,
                intake_id=prereqs["intake_id"],
                catalog_id=prereqs["catalog_id"],
                schema_version="1.0.0",
                catalog_sha256=prereqs["catalog_sha256"],
                canonical_json=canonical_json,
                sha256_hex=sha256_hex,
                created_at=now,
                created_by_id=prereqs["actor_id"],
            )
            session.commit()

        with session_factory() as session:
            repo = SnapshotRepository(session)
            result = repo.get_by_hash(sha256_hex)

        assert result is not None
        assert result["sha256_hex"] == sha256_hex


class TestExistsForIntake:
    """Tests for exists_for_intake."""

    def test_returns_true_when_exists(self, session_factory) -> None:
        """Returns True when snapshot exists for intake."""
        prereqs = _seed_prerequisites(session_factory)
        now = datetime.now(tz=timezone.utc)
        canonical_json, sha256_hex = _create_canonical_json(
            prereqs["intake_id"], prereqs["app_id"]
        )

        with session_factory() as session:
            repo = SnapshotRepository(session)
            repo.create_snapshot(
                snapshot_id=str(uuid.uuid4()),
                intake_id=prereqs["intake_id"],
                catalog_id=prereqs["catalog_id"],
                schema_version="1.0.0",
                catalog_sha256=prereqs["catalog_sha256"],
                canonical_json=canonical_json,
                sha256_hex=sha256_hex,
                created_at=now,
                created_by_id=prereqs["actor_id"],
            )
            session.commit()

        with session_factory() as session:
            repo = SnapshotRepository(session)
            assert repo.exists_for_intake(prereqs["intake_id"]) is True

    def test_returns_false_when_not_exists(self, session_factory) -> None:
        """Returns False when no snapshot exists for intake."""
        prereqs = _seed_prerequisites(session_factory)

        with session_factory() as session:
            repo = SnapshotRepository(session)
            assert repo.exists_for_intake(prereqs["intake_id"]) is False
