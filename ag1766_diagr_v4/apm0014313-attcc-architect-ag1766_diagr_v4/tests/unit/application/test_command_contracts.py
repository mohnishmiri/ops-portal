"""
Contract tests for canonical command and actor types — G1.

These tests verify that the canonical command module and ActorContext
have the required fields and types for all service and route consumers.

The canonical modules are:
- migration_intake.application.commands: All command classes
- migration_intake.application.dto: ActorContext and other DTOs

Browser forms never submit actor IDs, actor types, roles, or audit fields.
"""

from __future__ import annotations

import pytest


class TestActorContextContract:
    """Contract tests for the canonical ActorContext."""

    def test_actor_context_has_required_fields(self) -> None:
        """ActorContext must have all fields used by services."""
        from migration_intake.application.dto import ActorContext

        # Create with minimal required fields
        ctx = ActorContext(
            actor_id="00000000-0000-0000-0000-000000000001",
            actor_type="CONFIGURED",
            display_name="Test Actor",
            role_codes=frozenset(["APPLICATION_CREATE"]),
            request_correlation_id="corr-123",
        )

        assert ctx.actor_id == "00000000-0000-0000-0000-000000000001"
        assert ctx.actor_type == "CONFIGURED"
        assert ctx.display_name == "Test Actor"
        assert "APPLICATION_CREATE" in ctx.role_codes
        assert ctx.request_correlation_id == "corr-123"

    def test_actor_context_is_immutable(self) -> None:
        """ActorContext must be frozen (immutable)."""
        from migration_intake.application.dto import ActorContext

        ctx = ActorContext(
            actor_id="00000000-0000-0000-0000-000000000001",
            actor_type="CONFIGURED",
            display_name="Test",
            role_codes=frozenset(),
            request_correlation_id="corr-123",
        )

        with pytest.raises((AttributeError, TypeError)):
            ctx.actor_id = "changed"  # type: ignore[misc]

    def test_actor_context_has_capability_methods(self) -> None:
        """ActorContext must have capability checking methods."""
        from migration_intake.application.dto import ActorContext

        ctx = ActorContext(
            actor_id="00000000-0000-0000-0000-000000000001",
            actor_type="CONFIGURED",
            display_name="Test",
            role_codes=frozenset(["APPLICATION_CREATE", "INTAKE_CREATE"]),
            request_correlation_id="corr-123",
        )

        assert ctx.has_capability("APPLICATION_CREATE")
        assert not ctx.has_capability("ADMIN")
        assert ctx.has_any_capability("APPLICATION_CREATE", "ADMIN")
        assert ctx.has_all_capabilities("APPLICATION_CREATE", "INTAKE_CREATE")
        assert not ctx.has_all_capabilities("APPLICATION_CREATE", "ADMIN")

    def test_actor_context_optional_external_subject(self) -> None:
        """ActorContext external_subject is optional."""
        from migration_intake.application.dto import ActorContext

        ctx = ActorContext(
            actor_id="00000000-0000-0000-0000-000000000001",
            actor_type="OIDC_USER",
            display_name="Test",
            role_codes=frozenset(),
            request_correlation_id="corr-123",
            external_subject="user@example.com",
        )

        assert ctx.external_subject == "user@example.com"


class TestCreateApplicationCommandContract:
    """Contract tests for CreateApplicationCommand."""

    def test_command_has_required_fields(self) -> None:
        """CreateApplicationCommand must have display_name, identifiers, and actor."""
        from migration_intake.application.commands import (
            CreateApplicationCommand,
            IdentifierInput,
        )
        from migration_intake.application.dto import ActorContext

        actor = ActorContext(
            actor_id="00000000-0000-0000-0000-000000000001",
            actor_type="CONFIGURED",
            display_name="Test",
            role_codes=frozenset(),
            request_correlation_id="corr-123",
        )

        cmd = CreateApplicationCommand(
            display_name="Test App",
            identifiers=(
                IdentifierInput(identifier_type="ITAP", raw_value="12345"),
            ),
            actor=actor,
        )

        assert cmd.display_name == "Test App"
        assert len(cmd.identifiers) == 1
        assert cmd.identifiers[0].identifier_type == "ITAP"
        assert cmd.identifiers[0].raw_value == "12345"
        assert cmd.actor.actor_id == "00000000-0000-0000-0000-000000000001"

    def test_command_is_immutable(self) -> None:
        """CreateApplicationCommand must be frozen."""
        from migration_intake.application.commands import CreateApplicationCommand
        from migration_intake.application.dto import ActorContext

        actor = ActorContext(
            actor_id="00000000-0000-0000-0000-000000000001",
            actor_type="CONFIGURED",
            display_name="Test",
            role_codes=frozenset(),
            request_correlation_id="corr-123",
        )

        cmd = CreateApplicationCommand(
            display_name="Test App",
            identifiers=(),
            actor=actor,
        )

        with pytest.raises((AttributeError, TypeError)):
            cmd.display_name = "changed"  # type: ignore[misc]

    def test_command_allows_empty_identifiers(self) -> None:
        """CreateApplicationCommand can have empty identifiers."""
        from migration_intake.application.commands import CreateApplicationCommand
        from migration_intake.application.dto import ActorContext

        actor = ActorContext(
            actor_id="00000000-0000-0000-0000-000000000001",
            actor_type="CONFIGURED",
            display_name="Test",
            role_codes=frozenset(),
            request_correlation_id="corr-123",
        )

        cmd = CreateApplicationCommand(
            display_name="Test App",
            identifiers=(),
            actor=actor,
        )

        assert cmd.identifiers == ()


class TestCreateIntakeCommandContract:
    """Contract tests for CreateIntakeCommand."""

    def test_command_has_required_fields(self) -> None:
        """CreateIntakeCommand must have application_id, catalog_release_id, and actor."""
        from migration_intake.application.commands import CreateIntakeCommand
        from migration_intake.application.dto import ActorContext

        actor = ActorContext(
            actor_id="00000000-0000-0000-0000-000000000001",
            actor_type="CONFIGURED",
            display_name="Test",
            role_codes=frozenset(),
            request_correlation_id="corr-123",
        )

        cmd = CreateIntakeCommand(
            application_id="app-123",
            catalog_release_id="cat-456",
            actor=actor,
        )

        assert cmd.application_id == "app-123"
        assert cmd.catalog_release_id == "cat-456"
        assert cmd.actor.actor_id == "00000000-0000-0000-0000-000000000001"

    def test_command_is_immutable(self) -> None:
        """CreateIntakeCommand must be frozen."""
        from migration_intake.application.commands import CreateIntakeCommand
        from migration_intake.application.dto import ActorContext

        actor = ActorContext(
            actor_id="00000000-0000-0000-0000-000000000001",
            actor_type="CONFIGURED",
            display_name="Test",
            role_codes=frozenset(),
            request_correlation_id="corr-123",
        )

        cmd = CreateIntakeCommand(
            application_id="app-123",
            catalog_release_id="cat-456",
            actor=actor,
        )

        with pytest.raises((AttributeError, TypeError)):
            cmd.application_id = "changed"  # type: ignore[misc]


class TestUpdateApplicationIdentityCommandContract:
    """Contract tests for UpdateApplicationIdentityCommand."""

    def test_command_has_required_fields(self) -> None:
        """UpdateApplicationIdentityCommand must have all required fields."""
        from migration_intake.application.commands import (
            IdentifierInput,
            UpdateApplicationIdentityCommand,
        )
        from migration_intake.application.dto import ActorContext

        actor = ActorContext(
            actor_id="00000000-0000-0000-0000-000000000001",
            actor_type="CONFIGURED",
            display_name="Test",
            role_codes=frozenset(),
            request_correlation_id="corr-123",
        )

        cmd = UpdateApplicationIdentityCommand(
            application_id="app-123",
            display_name="Updated Name",
            identifiers=(
                IdentifierInput(identifier_type="MOTS", raw_value="M-999"),
            ),
            expected_version=5,
            actor=actor,
        )

        assert cmd.application_id == "app-123"
        assert cmd.display_name == "Updated Name"
        assert cmd.expected_version == 5
        assert len(cmd.identifiers) == 1
        assert cmd.actor.actor_id == "00000000-0000-0000-0000-000000000001"

    def test_command_is_immutable(self) -> None:
        """UpdateApplicationIdentityCommand must be frozen."""
        from migration_intake.application.commands import UpdateApplicationIdentityCommand
        from migration_intake.application.dto import ActorContext

        actor = ActorContext(
            actor_id="00000000-0000-0000-0000-000000000001",
            actor_type="CONFIGURED",
            display_name="Test",
            role_codes=frozenset(),
            request_correlation_id="corr-123",
        )

        cmd = UpdateApplicationIdentityCommand(
            application_id="app-123",
            display_name="Test",
            identifiers=(),
            expected_version=1,
            actor=actor,
        )

        with pytest.raises((AttributeError, TypeError)):
            cmd.expected_version = 99  # type: ignore[misc]


class TestIdentifierInputContract:
    """Contract tests for IdentifierInput."""

    def test_identifier_has_required_fields(self) -> None:
        """IdentifierInput must have identifier_type and raw_value."""
        from migration_intake.application.commands import IdentifierInput

        ident = IdentifierInput(
            identifier_type="CORRELATION",
            raw_value="COR-12345",
        )

        assert ident.identifier_type == "CORRELATION"
        assert ident.raw_value == "COR-12345"

    def test_identifier_is_immutable(self) -> None:
        """IdentifierInput must be frozen."""
        from migration_intake.application.commands import IdentifierInput

        ident = IdentifierInput(
            identifier_type="ITAP",
            raw_value="12345",
        )

        with pytest.raises((AttributeError, TypeError)):
            ident.raw_value = "changed"  # type: ignore[misc]


class TestSaveAnswerCommandContract:
    """Contract tests for SaveAnswerCommand."""

    def test_command_has_required_fields(self) -> None:
        """SaveAnswerCommand must have intake_id, question_code, value."""
        from migration_intake.application.commands import SaveAnswerCommand

        cmd = SaveAnswerCommand(
            intake_id="intake-123",
            question_code="APP-001",
            value={"selected": "YES"},
            response_schema_version="1.0",
        )

        assert cmd.intake_id == "intake-123"
        assert cmd.question_code == "APP-001"
        assert cmd.value == {"selected": "YES"}
        assert cmd.response_schema_version == "1.0"

    def test_command_has_optional_expected_version(self) -> None:
        """SaveAnswerCommand expected_version is optional for first save."""
        from migration_intake.application.commands import SaveAnswerCommand

        cmd = SaveAnswerCommand(
            intake_id="intake-123",
            question_code="APP-001",
            value="test",
            response_schema_version="1.0",
            expected_version=None,
        )

        assert cmd.expected_version is None

    def test_command_has_expected_version_for_update(self) -> None:
        """SaveAnswerCommand expected_version required for updates."""
        from migration_intake.application.commands import SaveAnswerCommand

        cmd = SaveAnswerCommand(
            intake_id="intake-123",
            question_code="APP-001",
            value="updated",
            response_schema_version="1.0",
            expected_version=3,
        )

        assert cmd.expected_version == 3


class TestClearAnswerCommandContract:
    """Contract tests for ClearAnswerCommand."""

    def test_command_has_required_fields(self) -> None:
        """ClearAnswerCommand must have intake_id, question_code, reason."""
        from migration_intake.application.commands import ClearAnswerCommand

        cmd = ClearAnswerCommand(
            intake_id="intake-123",
            question_code="APP-001",
            reason="Data was incorrect",
            expected_version=2,
        )

        assert cmd.intake_id == "intake-123"
        assert cmd.question_code == "APP-001"
        assert cmd.reason == "Data was incorrect"
        assert cmd.expected_version == 2


class TestConfirmAnswerCommandContract:
    """Contract tests for ConfirmAnswerCommand."""

    def test_command_has_required_fields(self) -> None:
        """ConfirmAnswerCommand must have intake_id, question_code, expected_version."""
        from migration_intake.application.commands import ConfirmAnswerCommand

        cmd = ConfirmAnswerCommand(
            intake_id="intake-123",
            question_code="APP-001",
            expected_version=5,
        )

        assert cmd.intake_id == "intake-123"
        assert cmd.question_code == "APP-001"
        assert cmd.expected_version == 5


class TestMarkNotApplicableCommandContract:
    """Contract tests for MarkNotApplicableCommand."""

    def test_command_has_required_fields(self) -> None:
        """MarkNotApplicableCommand must have intake_id, question_code."""
        from migration_intake.application.commands import MarkNotApplicableCommand

        cmd = MarkNotApplicableCommand(
            intake_id="intake-123",
            question_code="APP-001",
            reason="Not relevant to this application",
        )

        assert cmd.intake_id == "intake-123"
        assert cmd.question_code == "APP-001"
        assert cmd.reason == "Not relevant to this application"


class TestCanonicalModuleExports:
    """Tests that canonical modules export all required types."""

    def test_commands_module_exports_all_commands(self) -> None:
        """application.commands must export all command classes."""
        from migration_intake.application import commands

        # Application commands
        assert hasattr(commands, "CreateApplicationCommand")
        assert hasattr(commands, "CreateIntakeCommand")
        assert hasattr(commands, "UpdateApplicationIdentityCommand")
        assert hasattr(commands, "IdentifierInput")

        # Answer commands
        assert hasattr(commands, "SaveAnswerCommand")
        assert hasattr(commands, "ClearAnswerCommand")
        assert hasattr(commands, "ConfirmAnswerCommand")
        assert hasattr(commands, "MarkNotApplicableCommand")

    def test_dto_module_exports_actor_context(self) -> None:
        """application.dto must export ActorContext."""
        from migration_intake.application import dto

        assert hasattr(dto, "ActorContext")
        assert hasattr(dto, "StoredContent")

    def test_package_init_exports_canonical_types(self) -> None:
        """application package must export canonical types."""
        from migration_intake import application

        assert hasattr(application, "ActorContext")
        assert hasattr(application, "CreateApplicationCommand")
        assert hasattr(application, "CreateIntakeCommand")
