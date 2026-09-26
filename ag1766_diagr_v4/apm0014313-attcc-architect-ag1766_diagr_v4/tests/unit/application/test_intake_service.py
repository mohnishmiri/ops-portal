"""
Unit tests for ApplicationService.create_intake — A01 intake creation.

Fixtures ``tmp_engine`` and ``session_factory`` come from conftest.py.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timezone

import pytest

from migration_intake.application.errors import (
    ApplicationNotActiveError,
    CatalogNotPublishedError,
    OpenIntakeExistsError,
)
from migration_intake.application.services.applications import ApplicationService
from migration_intake.application.commands import (
    CreateApplicationCommand,
    CreateIntakeCommand,
)
from migration_intake.application.dto import ActorContext
from migration_intake.persistence.unit_of_work import uow_context


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_actor() -> ActorContext:
    return ActorContext(
        actor_id=str(uuid.uuid4()),
        display_name="Test Actor",
        actor_type="CONFIGURED",
    )


def _unique_sha256() -> str:
    """Return a valid, unique SHA-256 hex digest for each call."""
    return hashlib.sha256(uuid.uuid4().bytes).hexdigest()


def _create_test_application(
    session_factory,
    actor: ActorContext,
    state: str = "ACTIVE",
    display_name: str = "Test App",
) -> str:
    """Create an application via the service; optionally force a non-ACTIVE state."""
    svc = ApplicationService(session_factory)
    cmd = CreateApplicationCommand(
        display_name=display_name,
        identifiers=(),
        actor=actor,
    )
    result = svc.create_application(cmd)
    app_id = result["id"]

    if state != "ACTIVE":
        # Directly update state to simulate ON_HOLD / ARCHIVED
        with uow_context(session_factory) as uow:
            uow.applications.update_state(
                application_id=app_id,
                new_state=state,
                expected_version=1,
                updated_at=datetime.now(tz=timezone.utc),
            )
            uow.commit()

    return app_id


def _create_catalog_release(
    session_factory, pub_state: str = "PUBLISHED"
) -> str:
    """Insert a catalog release row; return its UUID string."""
    release_id = str(uuid.uuid4())
    sha256 = _unique_sha256()
    now = datetime.now(tz=timezone.utc)

    with uow_context(session_factory) as uow:
        uow.catalogs.add_release(
            release_id=release_id,
            semantic_version="1.0.0",
            source_filename="test-catalog.yaml",
            source_sha256=sha256,
            compiler_version="1.0.0",
            pub_state=pub_state,
            created_at=now,
        )
        uow.commit()
    return release_id


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_create_intake_for_active_application_succeeds(
    session_factory,
) -> None:
    """Creating an intake for an ACTIVE app with a PUBLISHED catalog returns DRAFT state."""
    svc = ApplicationService(session_factory)
    actor = _make_actor()
    app_id = _create_test_application(session_factory, actor)
    cat_id = _create_catalog_release(session_factory)

    cmd = CreateIntakeCommand(
        application_id=app_id,
        catalog_release_id=cat_id,
        actor=actor,
    )
    result = svc.create_intake(cmd)

    assert "id" in result
    uuid.UUID(result["id"])  # must be a valid UUID
    assert result["state"] == "DRAFT"
    assert result["application_id"] == app_id


def test_create_intake_writes_audit_event(session_factory) -> None:
    """An AuditEvent with event_code INTAKE_CREATED must be written atomically."""
    from sqlalchemy import select

    from migration_intake.persistence.models import AuditEvent

    svc = ApplicationService(session_factory)
    actor = _make_actor()
    app_id = _create_test_application(session_factory, actor)
    cat_id = _create_catalog_release(session_factory)

    cmd = CreateIntakeCommand(
        application_id=app_id,
        catalog_release_id=cat_id,
        actor=actor,
    )
    result = svc.create_intake(cmd)

    session = session_factory()
    try:
        stmt = select(AuditEvent).where(
            AuditEvent.entity_type == "intake",
            AuditEvent.event_code == "INTAKE_CREATED",
        )
        events = session.execute(stmt).scalars().all()
    finally:
        session.close()

    assert len(events) == 1
    assert str(events[0].entity_id) == result["id"]


def test_create_intake_for_non_active_application_raises(
    session_factory,
) -> None:
    """Creating an intake for an ARCHIVED application → ApplicationNotActiveError."""
    svc = ApplicationService(session_factory)
    actor = _make_actor()
    app_id = _create_test_application(session_factory, actor, state="ARCHIVED")
    cat_id = _create_catalog_release(session_factory)

    cmd = CreateIntakeCommand(
        application_id=app_id,
        catalog_release_id=cat_id,
        actor=actor,
    )

    with pytest.raises(ApplicationNotActiveError):
        svc.create_intake(cmd)


def test_create_intake_for_unpublished_catalog_raises(
    session_factory,
) -> None:
    """Creating an intake against a DRAFT catalog release → CatalogNotPublishedError."""
    svc = ApplicationService(session_factory)
    actor = _make_actor()
    app_id = _create_test_application(session_factory, actor)
    cat_id = _create_catalog_release(session_factory, pub_state="DRAFT")

    cmd = CreateIntakeCommand(
        application_id=app_id,
        catalog_release_id=cat_id,
        actor=actor,
    )

    with pytest.raises(CatalogNotPublishedError):
        svc.create_intake(cmd)


def test_one_open_intake_policy_enforced(session_factory) -> None:
    """A second intake creation while one is open → OpenIntakeExistsError."""
    svc = ApplicationService(session_factory)
    actor = _make_actor()
    app_id = _create_test_application(session_factory, actor)
    cat_id = _create_catalog_release(session_factory)

    cmd = CreateIntakeCommand(
        application_id=app_id,
        catalog_release_id=cat_id,
        actor=actor,
    )
    svc.create_intake(cmd)  # First succeeds

    with pytest.raises(OpenIntakeExistsError):
        svc.create_intake(cmd)  # Second must fail


def test_second_intake_allowed_after_first_cancelled(
    session_factory,
) -> None:
    """Once the open intake is CANCELLED a new intake may be created."""
    svc = ApplicationService(session_factory)
    actor = _make_actor()
    app_id = _create_test_application(session_factory, actor)
    cat_id = _create_catalog_release(session_factory)

    cmd = CreateIntakeCommand(
        application_id=app_id,
        catalog_release_id=cat_id,
        actor=actor,
    )
    first = svc.create_intake(cmd)

    # Cancel the first intake directly via the repository
    with uow_context(session_factory) as uow:
        uow.intakes.update_state(
            intake_id=first["id"],
            new_state="CANCELLED",
            expected_version=1,
            updated_at=datetime.now(tz=timezone.utc),
        )
        uow.commit()

    # Second creation must now succeed
    second = svc.create_intake(cmd)
    assert second["state"] == "DRAFT"
    assert second["id"] != first["id"]
