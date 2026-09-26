"""
Unit tests for ApplicationService — A01 create_application and
update_application_identity operations.

Fixtures ``tmp_engine`` and ``session_factory`` come from conftest.py.
"""

from __future__ import annotations

import uuid

import pytest

from migration_intake.application.errors import (
    ConcurrencyConflictError,
    DuplicateIdentifierError,
)
from migration_intake.application.services.applications import ApplicationService
from migration_intake.application.commands import (
    CreateApplicationCommand,
    IdentifierInput,
    UpdateApplicationIdentityCommand,
)
from migration_intake.application.dto import ActorContext


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_actor() -> ActorContext:
    return ActorContext(
        actor_id=str(uuid.uuid4()),
        display_name="Test Actor",
        actor_type="CONFIGURED",
    )


def _make_create_cmd(
    actor: ActorContext | None = None,
    display_name: str = "My App",
    identifiers: tuple = (),
) -> CreateApplicationCommand:
    if actor is None:
        actor = _make_actor()
    return CreateApplicationCommand(
        display_name=display_name,
        identifiers=identifiers,
        actor=actor,
    )


# ---------------------------------------------------------------------------
# create_application tests
# ---------------------------------------------------------------------------


class TestCreateApplication:
    def test_create_application_returns_id_and_state(
        self, session_factory
    ) -> None:
        """Result dict must contain a valid UUID 'id' and state=='ACTIVE'."""
        svc = ApplicationService(session_factory)
        cmd = _make_create_cmd()
        result = svc.create_application(cmd)

        assert "id" in result
        uuid.UUID(result["id"])  # raises ValueError if not valid UUID
        assert result["state"] == "ACTIVE"

    def test_create_application_persists_to_db(self, session_factory) -> None:
        """After create, the application is findable in a fresh UoW session."""
        from migration_intake.persistence.unit_of_work import uow_context

        svc = ApplicationService(session_factory)
        cmd = _make_create_cmd(display_name="Persisted App")
        result = svc.create_application(cmd)

        with uow_context(session_factory) as uow:
            app = uow.applications.get(result["id"])

        assert app is not None
        assert app["display_name"] == "Persisted App"
        assert app["state"] == "ACTIVE"

    def test_create_application_writes_audit_event(
        self, session_factory
    ) -> None:
        """An AuditEvent with event_code APPLICATION_CREATED must be written."""
        from sqlalchemy import select

        from migration_intake.persistence.models import AuditEvent

        svc = ApplicationService(session_factory)
        cmd = _make_create_cmd()
        result = svc.create_application(cmd)

        session = session_factory()
        try:
            stmt = select(AuditEvent).where(
                AuditEvent.entity_type == "application",
                AuditEvent.event_code == "APPLICATION_CREATED",
            )
            events = session.execute(stmt).scalars().all()
        finally:
            session.close()

        assert len(events) == 1
        assert str(events[0].entity_id) == result["id"]

    def test_create_application_normalizes_display_name(
        self, session_factory
    ) -> None:
        """Extra/internal whitespace in display_name is collapsed."""
        from migration_intake.persistence.unit_of_work import uow_context

        svc = ApplicationService(session_factory)
        cmd = _make_create_cmd(display_name="  My   App  Name  ")
        result = svc.create_application(cmd)

        with uow_context(session_factory) as uow:
            app = uow.applications.get(result["id"])

        assert app["display_name"] == "My App Name"

    def test_create_application_persists_identifiers(
        self, session_factory
    ) -> None:
        """Identifiers are stored with normalized lowercase values."""
        from sqlalchemy import select

        from migration_intake.persistence.models import ApplicationIdentifier

        svc = ApplicationService(session_factory)
        idents = (
            IdentifierInput(identifier_type="ITAP", raw_value="ABC-123"),
            IdentifierInput(identifier_type="MOTS", raw_value="MOTS-999"),
        )
        cmd = _make_create_cmd(identifiers=idents)
        result = svc.create_application(cmd)

        session = session_factory()
        try:
            stmt = select(ApplicationIdentifier).where(
                ApplicationIdentifier.application_id == result["id"]
            )
            rows = session.execute(stmt).scalars().all()
        finally:
            session.close()

        assert len(rows) == 2
        normalized_values = {r.normalized_value for r in rows}
        assert "abc-123" in normalized_values
        assert "mots-999" in normalized_values

    def test_duplicate_normalized_identifier_raises(
        self, session_factory
    ) -> None:
        """Same (type, normalized_value) on a second application → DuplicateIdentifierError."""
        svc = ApplicationService(session_factory)

        # Create first application with ITAP:ABC-123
        idents1 = (IdentifierInput(identifier_type="ITAP", raw_value="ABC-123"),)
        cmd1 = _make_create_cmd(identifiers=idents1)
        svc.create_application(cmd1)

        # Attempt second application with same normalized value (different case)
        idents2 = (IdentifierInput(identifier_type="ITAP", raw_value="abc-123"),)
        cmd2 = _make_create_cmd(identifiers=idents2)

        with pytest.raises(DuplicateIdentifierError):
            svc.create_application(cmd2)


# ---------------------------------------------------------------------------
# update_application_identity tests
# ---------------------------------------------------------------------------


class TestUpdateApplicationIdentity:
    def test_update_application_identity_correct_version(
        self, session_factory
    ) -> None:
        """Update with expected_version=1 succeeds; row_version becomes 2."""
        from migration_intake.persistence.unit_of_work import uow_context

        svc = ApplicationService(session_factory)
        actor = _make_actor()
        create_cmd = _make_create_cmd(actor=actor, display_name="Original Name")
        result = svc.create_application(create_cmd)

        update_cmd = UpdateApplicationIdentityCommand(
            application_id=result["id"],
            display_name="Updated Name",
            identifiers=(),
            expected_version=1,
            actor=actor,
        )
        svc.update_application_identity(update_cmd)

        with uow_context(session_factory) as uow:
            app = uow.applications.get(result["id"])

        assert app["display_name"] == "Updated Name"
        assert app["row_version"] == 2

    def test_update_application_identity_stale_version(
        self, session_factory
    ) -> None:
        """Update with wrong expected_version → ConcurrencyConflictError."""
        svc = ApplicationService(session_factory)
        actor = _make_actor()
        create_cmd = _make_create_cmd(actor=actor)
        result = svc.create_application(create_cmd)

        update_cmd = UpdateApplicationIdentityCommand(
            application_id=result["id"],
            display_name="Should Not Apply",
            identifiers=(),
            expected_version=99,  # actual is 1
            actor=actor,
        )

        with pytest.raises(ConcurrencyConflictError):
            svc.update_application_identity(update_cmd)

    def test_update_application_identity_duplicate_ident_raises(
        self, session_factory
    ) -> None:
        """Updating with an identifier already owned by another app → DuplicateIdentifierError."""
        svc = ApplicationService(session_factory)
        actor = _make_actor()

        # First app owns ITAP:TAKEN-111
        idents1 = (IdentifierInput(identifier_type="ITAP", raw_value="TAKEN-111"),)
        cmd1 = _make_create_cmd(actor=actor, identifiers=idents1)
        svc.create_application(cmd1)

        # Second app (no identifiers)
        cmd2 = _make_create_cmd(actor=actor, display_name="Second App")
        result2 = svc.create_application(cmd2)

        # Try to assign ITAP:TAKEN-111 to second app → conflict
        update_cmd = UpdateApplicationIdentityCommand(
            application_id=result2["id"],
            display_name="Second App",
            identifiers=(
                IdentifierInput(identifier_type="ITAP", raw_value="TAKEN-111"),
            ),
            expected_version=1,
            actor=actor,
        )

        with pytest.raises(DuplicateIdentifierError):
            svc.update_application_identity(update_cmd)
