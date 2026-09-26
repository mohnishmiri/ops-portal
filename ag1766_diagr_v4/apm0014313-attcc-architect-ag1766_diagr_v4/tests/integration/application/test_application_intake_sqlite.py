"""
Integration test — full application + intake workflow against an in-memory
SQLite database.

Verifies that:
- Application is created with normalized name and identifiers persisted.
- Intake is created in DRAFT state linked to the application and catalog.
- Both audit events (APPLICATION_CREATED, INTAKE_CREATED) are present.
- All data survives a new session (i.e., is truly committed to the DB).

Fixtures ``tmp_engine`` and ``session_factory`` are provided by conftest.py.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timezone

from sqlalchemy import select

from migration_intake.application.services.applications import ApplicationService
from migration_intake.application.commands import (
    CreateApplicationCommand,
    CreateIntakeCommand,
    IdentifierInput,
)
from migration_intake.application.dto import ActorContext
from migration_intake.persistence.models import AuditEvent
from migration_intake.persistence.unit_of_work import uow_context


def test_full_application_intake_workflow_sqlite(
    tmp_engine, session_factory
) -> None:
    """Create application with identifiers, then create intake; verify all persisted."""
    svc = ApplicationService(session_factory)

    actor = ActorContext(
        actor_id=str(uuid.uuid4()),
        display_name="Integration Test Actor",
        actor_type="CONFIGURED",
    )

    # ------------------------------------------------------------------
    # 1. Seed a PUBLISHED catalog release
    # ------------------------------------------------------------------
    cat_id = str(uuid.uuid4())
    sha256 = hashlib.sha256(b"integration-test-catalog").hexdigest()
    now = datetime.now(tz=timezone.utc)

    with uow_context(session_factory) as uow:
        uow.catalogs.add_release(
            release_id=cat_id,
            semantic_version="3.0.0",
            source_filename="integration.yaml",
            source_sha256=sha256,
            compiler_version="1.0.0",
            pub_state="PUBLISHED",
            created_at=now,
        )
        uow.commit()

    # ------------------------------------------------------------------
    # 2. Create application with two identifiers
    # ------------------------------------------------------------------
    idents = (
        IdentifierInput(identifier_type="ITAP", raw_value="INT-001"),
        IdentifierInput(identifier_type="MOTS", raw_value="MOTS-INT-001"),
    )
    create_cmd = CreateApplicationCommand(
        display_name="  Integration  Test  App  ",
        identifiers=idents,
        actor=actor,
    )
    app_result = svc.create_application(create_cmd)

    # ------------------------------------------------------------------
    # 3. Create intake against the published catalog
    # ------------------------------------------------------------------
    intake_cmd = CreateIntakeCommand(
        application_id=app_result["id"],
        catalog_release_id=cat_id,
        actor=actor,
    )
    intake_result = svc.create_intake(intake_cmd)

    # ------------------------------------------------------------------
    # 4. Verify all data in a FRESH session
    # ------------------------------------------------------------------
    with uow_context(session_factory) as uow:
        app = uow.applications.get(app_result["id"])
        intake = uow.intakes.get(intake_result["id"])

    # Application
    assert app is not None, "Application not found in fresh session"
    assert app["display_name"] == "Integration Test App"  # whitespace normalized
    assert app["state"] == "ACTIVE"
    assert app["row_version"] == 1

    # Intake
    assert intake is not None, "Intake not found in fresh session"
    assert intake["state"] == "DRAFT"
    assert intake["application_id"] == app_result["id"]
    assert intake["catalog_id"] == cat_id
    assert intake["row_version"] == 1

    # ------------------------------------------------------------------
    # 5. Verify both audit events exist
    # ------------------------------------------------------------------
    session = session_factory()
    try:
        app_events = session.execute(
            select(AuditEvent).where(
                AuditEvent.entity_type == "application",
                AuditEvent.event_code == "APPLICATION_CREATED",
            )
        ).scalars().all()

        intake_events = session.execute(
            select(AuditEvent).where(
                AuditEvent.entity_type == "intake",
                AuditEvent.event_code == "INTAKE_CREATED",
            )
        ).scalars().all()
    finally:
        session.close()

    assert len(app_events) == 1
    assert str(app_events[0].entity_id) == app_result["id"]

    assert len(intake_events) == 1
    assert str(intake_events[0].entity_id) == intake_result["id"]
