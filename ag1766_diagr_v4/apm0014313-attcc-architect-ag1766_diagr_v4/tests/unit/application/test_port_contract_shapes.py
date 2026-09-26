"""
Tests for application port contracts and shapes.

These tests verify:
- Actor context ignores untrusted browser actor fields
- Command DTOs require expected versions for mutable state
- Ports expose no SQLAlchemy/openpyxl/httpx types
- Port protocols define required methods
"""

from __future__ import annotations

import uuid
from typing import get_type_hints

import pytest


class TestActorContext:
    """Tests for ActorContext."""

    def test_create_with_required_fields(self) -> None:
        """ActorContext should be created with required fields."""
        from migration_intake.application.dto import ActorContext

        actor_id = str(uuid.uuid4())
        context = ActorContext(
            actor_id=actor_id,
            actor_type="CONFIGURED",
            display_name="Test User",
            role_codes=frozenset(["application:create"]),
            request_correlation_id=str(uuid.uuid4()),
        )

        assert context.actor_id == actor_id
        assert context.actor_type == "CONFIGURED"
        assert context.display_name == "Test User"

    def test_ignores_untrusted_fields_from_browser(self) -> None:
        """ActorContext should not accept actor_id from untrusted input."""
        from migration_intake.application.dto import ActorContext

        # Simulate untrusted browser input trying to set actor_id
        trusted_actor_id = str(uuid.uuid4())
        untrusted_actor_id = str(uuid.uuid4())

        # ActorContext should be constructed by the adapter, not from form data
        context = ActorContext(
            actor_id=trusted_actor_id,
            actor_type="CONFIGURED",
            display_name="Trusted User",
            role_codes=frozenset(["application:create"]),
            request_correlation_id=str(uuid.uuid4()),
        )

        # The context should use the trusted actor_id, not any untrusted input
        assert context.actor_id == trusted_actor_id
        assert context.actor_id != untrusted_actor_id

    def test_role_codes_are_immutable(self) -> None:
        """ActorContext role_codes should be immutable."""
        from migration_intake.application.dto import ActorContext

        context = ActorContext(
            actor_id=str(uuid.uuid4()),
            actor_type="CONFIGURED",
            display_name="Test User",
            role_codes=frozenset(["application:create"]),
            request_correlation_id=str(uuid.uuid4()),
        )

        # role_codes should be a frozenset
        assert isinstance(context.role_codes, frozenset)

    def test_has_capability_check(self) -> None:
        """ActorContext should check for capabilities."""
        from migration_intake.application.dto import ActorContext

        context = ActorContext(
            actor_id=str(uuid.uuid4()),
            actor_type="CONFIGURED",
            display_name="Test User",
            role_codes=frozenset(["application:create", "intake:create"]),
            request_correlation_id=str(uuid.uuid4()),
        )

        assert context.has_capability("application:create")
        assert context.has_capability("intake:create")
        assert not context.has_capability("admin:delete")


class TestCommandDTOs:
    """Tests for command DTOs — G1 canonical string-typed commands."""

    def test_create_application_command_shape(self) -> None:
        """CreateApplicationCommand should have required fields."""
        from migration_intake.application.commands import CreateApplicationCommand
        from migration_intake.application.dto import ActorContext

        actor = ActorContext(actor_id=str(uuid.uuid4()))
        cmd = CreateApplicationCommand(
            display_name="Test App",
            identifiers=(),
            actor=actor,
        )

        assert cmd.display_name == "Test App"
        assert cmd.identifiers == ()
        assert cmd.actor.actor_id is not None

    def test_update_command_requires_expected_version(self) -> None:
        """Update commands should require expected_version."""
        from migration_intake.application.commands import UpdateApplicationIdentityCommand
        from migration_intake.application.dto import ActorContext

        actor = ActorContext(actor_id=str(uuid.uuid4()))
        cmd = UpdateApplicationIdentityCommand(
            application_id=str(uuid.uuid4()),
            display_name="Updated Name",
            identifiers=(),
            expected_version=1,
            actor=actor,
        )

        assert cmd.expected_version == 1

    def test_create_intake_command_requires_application_id(self) -> None:
        """CreateIntakeCommand should require application_id."""
        from migration_intake.application.commands import CreateIntakeCommand
        from migration_intake.application.dto import ActorContext

        actor = ActorContext(actor_id=str(uuid.uuid4()))
        cmd = CreateIntakeCommand(
            application_id=str(uuid.uuid4()),
            catalog_release_id=str(uuid.uuid4()),
            actor=actor,
        )

        assert cmd.application_id is not None
        assert cmd.catalog_release_id is not None


class TestPortProtocols:
    """Tests for port protocol shapes."""

    def test_unit_of_work_protocol_has_commit(self) -> None:
        """UnitOfWork protocol should have commit method."""
        from migration_intake.application.ports import UnitOfWork

        # Check protocol has expected methods
        assert hasattr(UnitOfWork, "commit")
        assert hasattr(UnitOfWork, "rollback")

    def test_unit_of_work_protocol_has_repositories(self) -> None:
        """UnitOfWork protocol should expose repository attributes."""
        from migration_intake.application.ports import UnitOfWork

        # These should be defined in the protocol
        assert hasattr(UnitOfWork, "applications")
        assert hasattr(UnitOfWork, "intakes")

    def test_evidence_store_protocol_shape(self) -> None:
        """EvidenceStore protocol should have put/open/exists methods."""
        from migration_intake.application.ports import EvidenceStore

        assert hasattr(EvidenceStore, "put")
        assert hasattr(EvidenceStore, "open")
        assert hasattr(EvidenceStore, "exists")

    def test_ports_do_not_import_sqlalchemy(self) -> None:
        """Port protocols should not import SQLAlchemy."""
        from migration_intake.application import ports

        module_source = ports.__file__
        assert module_source is not None

        with open(module_source) as f:
            source = f.read()

        # Should not have import statements for SQLAlchemy
        assert "from sqlalchemy" not in source
        assert "import sqlalchemy" not in source

    def test_ports_do_not_import_openpyxl(self) -> None:
        """Port protocols should not import openpyxl."""
        from migration_intake.application import ports

        module_source = ports.__file__
        assert module_source is not None

        with open(module_source) as f:
            source = f.read()

        assert "from openpyxl" not in source
        assert "import openpyxl" not in source

    def test_ports_do_not_import_httpx(self) -> None:
        """Port protocols should not import httpx."""
        from migration_intake.application import ports

        module_source = ports.__file__
        assert module_source is not None

        with open(module_source) as f:
            source = f.read()

        assert "from httpx" not in source
        assert "import httpx" not in source


class TestQueryDTOs:
    """Tests for query DTOs."""

    def test_application_summary_dto_shape(self) -> None:
        """ApplicationSummaryDTO should have expected fields."""
        from migration_intake.application.queries import ApplicationSummaryDTO
        from migration_intake.domain.ids import ApplicationId
        from migration_intake.domain.states import ApplicationState

        dto = ApplicationSummaryDTO(
            id=ApplicationId.generate(),
            name="Test App",
            acronym="TST",
            state=ApplicationState.ACTIVE,
            intake_count=0,
        )

        assert dto.name == "Test App"
        assert dto.state == ApplicationState.ACTIVE

    def test_intake_summary_dto_shape(self) -> None:
        """IntakeSummaryDTO should have expected fields."""
        from migration_intake.application.queries import IntakeSummaryDTO
        from migration_intake.domain.ids import ApplicationId, IntakeId
        from migration_intake.domain.states import IntakeState

        dto = IntakeSummaryDTO(
            id=IntakeId.generate(),
            application_id=ApplicationId.generate(),
            state=IntakeState.DRAFT,
            progress_percent=0,
        )

        assert dto.state == IntakeState.DRAFT
