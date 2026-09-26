"""
Contract tests for UnitOfWork atomicity — P04 (Repositories and Unit of Work).

TDD discipline: written BEFORE implementation; fails with ImportError at
collection time until unit_of_work is implemented.

Coverage:
  1. Changes committed inside a UoW are visible in a new session.
  2. Exception inside UoW context triggers rollback; changes not visible.
  3. Exiting UoW without calling commit() → changes are rolled back.
  4. UoW exposes .applications, .catalogs, .intakes, .answers repositories.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy.orm import Session

# ── RED imports — fail with ImportError until the modules are implemented ────
from migration_intake.persistence.unit_of_work import (  # noqa: E402
    UnitOfWork,
    uow_context,
)
from migration_intake.persistence.repositories.catalogs import (  # noqa: E402
    CatalogRepository,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _now() -> datetime:
    return datetime.now(tz=timezone.utc)


def _sha(c: str) -> str:
    """64-char lowercase hex."""
    assert c in "0123456789abcdef"
    return c * 64


def _make_release_kwargs(semantic_version: str = "1.0.0") -> dict:
    return dict(
        release_id=str(uuid.uuid4()),
        semantic_version=semantic_version,
        source_filename=f"v{semantic_version}.yaml",
        source_sha256=_sha("b"),
        compiler_version="1.0",
        pub_state="PUBLISHED",
        created_at=_now(),
    )


# ---------------------------------------------------------------------------
# Test 1 — commit persists changes
# ---------------------------------------------------------------------------


def test_commit_persists_changes(tmp_engine, session_factory) -> None:
    """Changes committed in UoW are visible in new session."""
    release_id = str(uuid.uuid4())

    with uow_context(session_factory) as uow:
        uow.catalogs.add_release(
            release_id=release_id,
            semantic_version="2.0.0",
            source_filename="v2.yaml",
            source_sha256=_sha("c"),
            compiler_version="2.0",
            pub_state="PUBLISHED",
            created_at=_now(),
        )
        uow.commit()

    # Verify in an independent session — must hit the DB
    with Session(tmp_engine) as session:
        repo = CatalogRepository(session)
        release = repo.get_release(release_id)

    assert release is not None
    assert release["semantic_version"] == "2.0.0"
    assert str(release["id"]) == release_id


# ---------------------------------------------------------------------------
# Test 2 — exception triggers rollback
# ---------------------------------------------------------------------------


def test_rollback_removes_changes(tmp_engine, session_factory) -> None:
    """Exception inside UoW context triggers rollback; changes not visible."""
    release_id = str(uuid.uuid4())

    with pytest.raises(RuntimeError, match="deliberate"):
        with uow_context(session_factory) as uow:
            uow.catalogs.add_release(
                release_id=release_id,
                semantic_version="3.0.0",
                source_filename="v3.yaml",
                source_sha256=_sha("d"),
                compiler_version="3.0",
                pub_state="PUBLISHED",
                created_at=_now(),
            )
            raise RuntimeError("deliberate rollback")

    # Must not be visible after rollback
    with Session(tmp_engine) as session:
        repo = CatalogRepository(session)
        release = repo.get_release(release_id)

    assert release is None


# ---------------------------------------------------------------------------
# Test 3 — no commit also rolls back
# ---------------------------------------------------------------------------


def test_no_commit_also_rolls_back(tmp_engine, session_factory) -> None:
    """Exiting UoW without calling commit() → changes rolled back."""
    release_id = str(uuid.uuid4())

    # Exit the context without calling commit() and without raising
    with uow_context(session_factory) as uow:
        uow.catalogs.add_release(
            release_id=release_id,
            semantic_version="4.0.0",
            source_filename="v4.yaml",
            source_sha256=_sha("e"),
            compiler_version="4.0",
            pub_state="PUBLISHED",
            created_at=_now(),
        )
        # Intentionally NO uow.commit()

    # Must not be visible — session close should have rolled back
    with Session(tmp_engine) as session:
        repo = CatalogRepository(session)
        release = repo.get_release(release_id)

    assert release is None


# ---------------------------------------------------------------------------
# Test 4 — UoW repositories are accessible
# ---------------------------------------------------------------------------


def test_uow_repositories_accessible(tmp_engine, session_factory) -> None:
    """UoW exposes .applications, .catalogs, .intakes, .answers."""
    with uow_context(session_factory) as uow:
        assert uow.applications is not None, "uow.applications must exist"
        assert uow.catalogs is not None, "uow.catalogs must exist"
        assert uow.intakes is not None, "uow.intakes must exist"
        assert uow.answers is not None, "uow.answers must exist"

        # Each has the expected methods
        assert callable(getattr(uow.applications, "add", None))
        assert callable(getattr(uow.applications, "get", None))
        assert callable(getattr(uow.catalogs, "add_release", None))
        assert callable(getattr(uow.intakes, "add", None))
        assert callable(getattr(uow.answers, "add_instance", None))
        uow.commit()
