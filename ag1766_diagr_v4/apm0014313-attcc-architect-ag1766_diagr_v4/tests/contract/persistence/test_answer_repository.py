"""
Contract tests for AnswerRepository — P04 (Repositories and Unit of Work).

TDD discipline: written BEFORE implementation; fails with ImportError at
collection time until the repository is implemented.

Coverage:
  1. Insert revision, advance pointer; new session returns correct current revision.
  2. Duplicate (instance_id, revision_number) → IntegrityError (append-only guarantee).
  3. Multiple revisions returned in ascending revision_number order.
  4. get_current_revision returns latest revision after advancing pointer.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

# ── RED import — fails with ImportError until the module is implemented ──────
from migration_intake.persistence.repositories.answers import (  # noqa: E402
    AnswerRepository,
)


# ---------------------------------------------------------------------------
# Helpers — build the full FK chain for answer tests
# ---------------------------------------------------------------------------


def _now() -> datetime:
    return datetime.now(tz=timezone.utc)


def _sha(c: str) -> str:
    """Return a valid 64-char lowercase hex string."""
    assert c in "0123456789abcdef"
    return c * 64


def _seed_prerequisites(engine) -> tuple[str, str, str, str]:
    """
    Insert Actor, CatalogRelease, CatalogSection, CatalogQuestion,
    Application, and Intake rows; return (actor_id, intake_id, question_id, instance_id).
    """
    from migration_intake.persistence.models import (
        Actor,
        Application,
        CatalogQuestion,
        CatalogRelease,
        CatalogSection,
        Intake,
    )

    now = _now()
    actor_id = str(uuid.uuid4())
    cat_id = str(uuid.uuid4())
    sec_id = str(uuid.uuid4())
    q_id = str(uuid.uuid4())
    app_id = str(uuid.uuid4())
    intake_id = str(uuid.uuid4())

    with Session(engine) as session:
        session.add(Actor(id=actor_id, display_name="Answer Actor", created_at=now))
        session.flush()

        session.add(
            CatalogRelease(
                id=cat_id,
                semantic_version="1.0.0",
                source_filename="v1.yaml",
                source_sha256=_sha("a"),
                compiler_version="1.0",
                pub_state="PUBLISHED",
                created_at=now,
            )
        )
        session.flush()

        session.add(
            Application(
                id=app_id,
                state="ACTIVE",
                display_name="Answer Test App",
                created_at=now,
                updated_at=now,
                row_version=1,
                created_by_id=actor_id,
            )
        )
        session.add(
            CatalogSection(
                id=sec_id,
                release_id=cat_id,
                section_code="ANS",
                display_name="Answer Section",
                display_order=1,
            )
        )
        session.flush()

        session.add(
            CatalogQuestion(
                id=q_id,
                section_id=sec_id,
                question_code="ANS-001",
                question_text="Test question?",
                response_type="TEXT",
                required_level="REQUIRED",
                collection_mode="MANUAL",
                display_order=1,
                is_active=True,
            )
        )
        session.flush()

        session.add(
            Intake(
                id=intake_id,
                application_id=app_id,
                catalog_id=cat_id,
                state="DRAFT",
                created_at=now,
                updated_at=now,
                row_version=1,
                created_by_id=actor_id,
            )
        )
        session.commit()

    return actor_id, intake_id, q_id


def _seed_instance(engine, intake_id: str, question_id: str) -> str:
    """Insert an AnswerInstance (current_rev_id=NULL) and return instance_id."""
    from migration_intake.persistence.models import AnswerInstance

    now = _now()
    instance_id = str(uuid.uuid4())
    with Session(engine) as session:
        session.add(
            AnswerInstance(
                id=instance_id,
                intake_id=intake_id,
                question_id=question_id,
                created_at=now,
                current_rev_id=None,
                applicability="APPLICABLE",
                value_state="EMPTY",
                review_state="UNREVIEWED",
                updated_at=now,
                row_version=1,
            )
        )
        session.commit()
    return instance_id


# ---------------------------------------------------------------------------
# Test 1 — add revision, advance pointer, reload in new session
# ---------------------------------------------------------------------------


def test_add_revision_and_advance_pointer_atomically(tmp_engine) -> None:
    """Insert revision, advance pointer; new session returns correct current revision."""
    actor_id, intake_id, q_id = _seed_prerequisites(tmp_engine)
    instance_id = _seed_instance(tmp_engine, intake_id, q_id)
    now = _now()
    rev_id = str(uuid.uuid4())

    # Write revision + advance pointer in one session, commit
    with Session(tmp_engine) as session:
        repo = AnswerRepository(session)
        repo.add_revision(
            revision_id=rev_id,
            instance_id=instance_id,
            revision_number=1,
            response_json={"value": "hello"},
            confirm_state="DRAFT",
            authored_at=now,
            authored_by_id=actor_id,
        )
        repo.advance_current_pointer(instance_id, rev_id)
        session.commit()

    # Verify in a fresh session — must not use the session cache
    with Session(tmp_engine) as session:
        repo = AnswerRepository(session)
        current = repo.get_current_revision(instance_id)

    assert current is not None
    assert str(current["id"]) == rev_id
    assert current["revision_number"] == 1
    assert current["response_json"] == {"value": "hello"}
    assert current["confirm_state"] == "DRAFT"


# ---------------------------------------------------------------------------
# Test 2 — revision is append-only (duplicate revision_number forbidden)
# ---------------------------------------------------------------------------


def test_revision_is_append_only(tmp_engine) -> None:
    """Duplicate (instance_id, revision_number) → IntegrityError."""
    actor_id, intake_id, q_id = _seed_prerequisites(tmp_engine)
    instance_id = _seed_instance(tmp_engine, intake_id, q_id)
    now = _now()

    with Session(tmp_engine) as session:
        repo = AnswerRepository(session)
        repo.add_revision(
            revision_id=str(uuid.uuid4()),
            instance_id=instance_id,
            revision_number=1,
            response_json={"value": "first"},
            confirm_state="DRAFT",
            authored_at=now,
            authored_by_id=actor_id,
        )
        session.commit()

    # Second insert with same revision_number must raise
    with pytest.raises(IntegrityError):
        with Session(tmp_engine) as session:
            repo = AnswerRepository(session)
            repo.add_revision(
                revision_id=str(uuid.uuid4()),
                instance_id=instance_id,
                revision_number=1,  # duplicate!
                response_json={"value": "duplicate"},
                confirm_state="DRAFT",
                authored_at=now,
                authored_by_id=actor_id,
            )
            session.commit()


# ---------------------------------------------------------------------------
# Test 3 — get_revisions returns multiple revisions in ascending order
# ---------------------------------------------------------------------------


def test_get_revisions_in_order(tmp_engine) -> None:
    """Multiple revisions returned in ascending revision_number order."""
    actor_id, intake_id, q_id = _seed_prerequisites(tmp_engine)
    instance_id = _seed_instance(tmp_engine, intake_id, q_id)
    now = _now()

    rev_ids = [str(uuid.uuid4()) for _ in range(3)]

    with Session(tmp_engine) as session:
        repo = AnswerRepository(session)
        # Insert out of insertion order to prove ORDER BY, not insertion order
        for i, rid in enumerate(rev_ids):
            repo.add_revision(
                revision_id=rid,
                instance_id=instance_id,
                revision_number=i + 1,
                response_json={"revision": i + 1},
                confirm_state="DRAFT",
                authored_at=now,
                authored_by_id=actor_id,
            )
        session.commit()

    with Session(tmp_engine) as session:
        repo = AnswerRepository(session)
        revisions = repo.get_revisions(instance_id)

    assert len(revisions) == 3
    assert [r["revision_number"] for r in revisions] == [1, 2, 3]
    assert revisions[0]["response_json"] == {"revision": 1}
    assert revisions[2]["response_json"] == {"revision": 3}


# ---------------------------------------------------------------------------
# Test 4 — get_current_revision after advancing pointer
# ---------------------------------------------------------------------------


def test_get_current_revision_after_advance(tmp_engine) -> None:
    """get_current_revision returns the latest revision after advancing pointer."""
    actor_id, intake_id, q_id = _seed_prerequisites(tmp_engine)
    instance_id = _seed_instance(tmp_engine, intake_id, q_id)
    now = _now()

    rev1_id = str(uuid.uuid4())
    rev2_id = str(uuid.uuid4())

    # Add rev1, advance pointer to rev1
    with Session(tmp_engine) as session:
        repo = AnswerRepository(session)
        repo.add_revision(
            revision_id=rev1_id,
            instance_id=instance_id,
            revision_number=1,
            response_json={"answer": "v1"},
            confirm_state="DRAFT",
            authored_at=now,
            authored_by_id=actor_id,
        )
        repo.advance_current_pointer(instance_id, rev1_id)
        session.commit()

    # Add rev2, advance pointer to rev2
    with Session(tmp_engine) as session:
        repo = AnswerRepository(session)
        repo.add_revision(
            revision_id=rev2_id,
            instance_id=instance_id,
            revision_number=2,
            response_json={"answer": "v2"},
            confirm_state="CONFIRMED",
            authored_at=now,
            authored_by_id=actor_id,
        )
        repo.advance_current_pointer(instance_id, rev2_id)
        session.commit()

    # Fresh session — current revision must be rev2
    with Session(tmp_engine) as session:
        repo = AnswerRepository(session)
        current = repo.get_current_revision(instance_id)

    assert current is not None
    assert str(current["id"]) == rev2_id
    assert current["revision_number"] == 2
    assert current["response_json"] == {"answer": "v2"}
    assert current["confirm_state"] == "CONFIRMED"

    # A non-existent instance_id must also return None.
    with Session(tmp_engine) as session:
        repo = AnswerRepository(session)
        result = repo.get_current_revision(str(uuid.uuid4()))

    assert result is None
