"""
Tests for catalog definitions.

These tests verify:
- CatalogRelease immutability and versioning
- Section and Question definition structures
- Response type and schema version binding
- Source, owner, and destination relationships
- Applicability condition structure
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest


class TestCatalogRelease:
    """Tests for CatalogRelease definition."""

    def test_catalog_release_has_required_fields(self) -> None:
        """CatalogRelease should have all required fields."""
        from migration_intake.catalog.definitions import CatalogRelease

        release = CatalogRelease(
            release_id="550e8400-e29b-41d4-a716-446655440000",
            version="0.2.0",
            source_filename="QUESTION_CATALOG_V0_2.csv",
            source_hash="abc123def456",
            compiler_version="1.0.0",
            published=True,
            published_at=datetime.now(timezone.utc),
        )

        assert release.release_id == "550e8400-e29b-41d4-a716-446655440000"
        assert release.version == "0.2.0"
        assert release.source_filename == "QUESTION_CATALOG_V0_2.csv"
        assert release.source_hash == "abc123def456"
        assert release.compiler_version == "1.0.0"
        assert release.published is True

    def test_catalog_release_is_immutable(self) -> None:
        """CatalogRelease should be immutable."""
        from migration_intake.catalog.definitions import CatalogRelease

        release = CatalogRelease(
            release_id="550e8400-e29b-41d4-a716-446655440000",
            version="0.2.0",
            source_filename="test.csv",
            source_hash="abc123",
            compiler_version="1.0.0",
            published=False,
        )

        with pytest.raises((AttributeError, TypeError)):
            release.version = "0.3.0"  # type: ignore[misc]

    def test_catalog_release_sections_are_ordered(self) -> None:
        """CatalogRelease sections should maintain order."""
        from migration_intake.catalog.definitions import CatalogRelease, Section

        sections = [
            Section(code="CTL", title="Control Information", order=1),
            Section(code="APP", title="Application Details", order=2),
            Section(code="NET", title="Network Requirements", order=3),
        ]

        release = CatalogRelease(
            release_id="test-id",
            version="0.2.0",
            source_filename="test.csv",
            source_hash="abc123",
            compiler_version="1.0.0",
            published=True,
            sections=tuple(sections),
        )

        assert len(release.sections) == 3
        assert release.sections[0].code == "CTL"
        assert release.sections[1].code == "APP"
        assert release.sections[2].code == "NET"


class TestSection:
    """Tests for Section definition."""

    def test_section_has_required_fields(self) -> None:
        """Section should have code, title, and order."""
        from migration_intake.catalog.definitions import Section

        section = Section(
            code="CTL",
            title="Control Information",
            order=1,
        )

        assert section.code == "CTL"
        assert section.title == "Control Information"
        assert section.order == 1

    def test_section_is_immutable(self) -> None:
        """Section should be immutable."""
        from migration_intake.catalog.definitions import Section

        section = Section(code="CTL", title="Control", order=1)

        with pytest.raises((AttributeError, TypeError)):
            section.code = "APP"  # type: ignore[misc]

    def test_section_code_is_normalized(self) -> None:
        """Section code should be uppercase."""
        from migration_intake.catalog.definitions import Section

        section = Section(code="ctl", title="Control", order=1)

        assert section.code == "CTL"


class TestQuestionDefinition:
    """Tests for QuestionDefinition."""

    def test_question_has_required_fields(self) -> None:
        """QuestionDefinition should have all required fields."""
        from migration_intake.catalog.definitions import QuestionDefinition

        question = QuestionDefinition(
            question_id="CTL-001",
            section_code="CTL",
            question_text="What is the correlation ID?",
            response_type="IDENTIFIER",
            response_schema_version="1.0",
            required_level="REQUIRED",
            order=1,
        )

        assert question.question_id == "CTL-001"
        assert question.section_code == "CTL"
        assert question.response_type == "IDENTIFIER"
        assert question.required_level == "REQUIRED"

    def test_question_is_immutable(self) -> None:
        """QuestionDefinition should be immutable."""
        from migration_intake.catalog.definitions import QuestionDefinition

        question = QuestionDefinition(
            question_id="CTL-001",
            section_code="CTL",
            question_text="Test",
            response_type="TEXT",
            response_schema_version="1.0",
            required_level="REQUIRED",
            order=1,
        )

        with pytest.raises((AttributeError, TypeError)):
            question.question_id = "CTL-002"  # type: ignore[misc]

    def test_question_id_format_validated(self) -> None:
        """QuestionDefinition should validate question ID format."""
        from migration_intake.catalog.definitions import QuestionDefinition

        # Valid format: PREFIX-NNN
        question = QuestionDefinition(
            question_id="APP-001",
            section_code="APP",
            question_text="Test",
            response_type="TEXT",
            response_schema_version="1.0",
            required_level="REQUIRED",
            order=1,
        )
        assert question.question_id == "APP-001"

    def test_question_with_allowed_values(self) -> None:
        """QuestionDefinition should support allowed values."""
        from migration_intake.catalog.definitions import AllowedValue, QuestionDefinition

        allowed = [
            AllowedValue(code="YES", label="Yes"),
            AllowedValue(code="NO", label="No"),
            AllowedValue(code="UNKNOWN", label="Unknown"),
        ]

        question = QuestionDefinition(
            question_id="DB-001",
            section_code="DB",
            question_text="Does the application use a database?",
            response_type="BOOLEAN",
            response_schema_version="1.0",
            required_level="REQUIRED",
            order=1,
            allowed_values=tuple(allowed),
        )

        assert len(question.allowed_values) == 3
        assert question.allowed_values[0].code == "YES"

    def test_question_with_applicability_condition(self) -> None:
        """QuestionDefinition should support applicability conditions."""
        from migration_intake.catalog.definitions import (
            ApplicabilityCondition,
            QuestionDefinition,
        )

        condition = ApplicabilityCondition(
            raw_expression="DB-001 = YES",
            compiled_ast={"op": "eq", "question": "DB-001", "value": "YES"},
        )

        question = QuestionDefinition(
            question_id="DB-002",
            section_code="DB",
            question_text="What database engine?",
            response_type="SINGLE_SELECT",
            response_schema_version="1.0",
            required_level="CONDITIONAL",
            order=2,
            applicability_condition=condition,
        )

        assert question.applicability_condition is not None
        assert question.applicability_condition.compiled_ast["op"] == "eq"


class TestAllowedValue:
    """Tests for AllowedValue definition."""

    def test_allowed_value_has_code_and_label(self) -> None:
        """AllowedValue should have code and label."""
        from migration_intake.catalog.definitions import AllowedValue

        value = AllowedValue(code="YES", label="Yes")

        assert value.code == "YES"
        assert value.label == "Yes"

    def test_allowed_value_code_is_normalized(self) -> None:
        """AllowedValue code should be uppercase."""
        from migration_intake.catalog.definitions import AllowedValue

        value = AllowedValue(code="yes", label="Yes")

        assert value.code == "YES"

    def test_allowed_value_with_description(self) -> None:
        """AllowedValue should support optional description."""
        from migration_intake.catalog.definitions import AllowedValue

        value = AllowedValue(
            code="CRITICAL",
            label="Critical",
            description="Business-critical application",
        )

        assert value.description == "Business-critical application"


class TestApplicabilityCondition:
    """Tests for ApplicabilityCondition."""

    def test_condition_has_raw_and_compiled(self) -> None:
        """ApplicabilityCondition should have raw expression and compiled AST."""
        from migration_intake.catalog.definitions import ApplicabilityCondition

        condition = ApplicabilityCondition(
            raw_expression="DB-001 = YES",
            compiled_ast={"op": "eq", "question": "DB-001", "value": "YES"},
        )

        assert condition.raw_expression == "DB-001 = YES"
        assert condition.compiled_ast["op"] == "eq"

    def test_condition_pending_status(self) -> None:
        """ApplicabilityCondition should support pending status."""
        from migration_intake.catalog.definitions import ApplicabilityCondition

        condition = ApplicabilityCondition(
            raw_expression="Dependencies exist",
            compiled_ast=None,
            is_pending=True,
        )

        assert condition.is_pending is True
        assert condition.compiled_ast is None


class TestSourceRelationship:
    """Tests for source relationships."""

    def test_source_relationship_has_priority(self) -> None:
        """SourceRelationship should have source label and priority."""
        from migration_intake.catalog.definitions import SourceRelationship

        source = SourceRelationship(
            source_label="Workbook",
            priority=1,
        )

        assert source.source_label == "Workbook"
        assert source.priority == 1

    def test_question_with_multiple_sources(self) -> None:
        """QuestionDefinition should support multiple sources with priority."""
        from migration_intake.catalog.definitions import (
            QuestionDefinition,
            SourceRelationship,
        )

        sources = [
            SourceRelationship(source_label="Workbook", priority=1),
            SourceRelationship(source_label="iTAP", priority=2),
            SourceRelationship(source_label="Manual", priority=3),
        ]

        question = QuestionDefinition(
            question_id="APP-001",
            section_code="APP",
            question_text="Test",
            response_type="TEXT",
            response_schema_version="1.0",
            required_level="REQUIRED",
            order=1,
            sources=tuple(sources),
        )

        assert len(question.sources) == 3
        assert question.sources[0].priority == 1


class TestOwnerRelationship:
    """Tests for owner relationships."""

    def test_owner_relationship_has_role(self) -> None:
        """OwnerRelationship should have role code."""
        from migration_intake.catalog.definitions import OwnerRelationship

        owner = OwnerRelationship(role_code="APPLICATION_OWNER")

        assert owner.role_code == "APPLICATION_OWNER"

    def test_owner_role_is_normalized(self) -> None:
        """OwnerRelationship role should be uppercase with underscores."""
        from migration_intake.catalog.definitions import OwnerRelationship

        owner = OwnerRelationship(role_code="application owner")

        assert owner.role_code == "APPLICATION_OWNER"


class TestDestinationMapping:
    """Tests for destination mappings."""

    def test_destination_has_target(self) -> None:
        """DestinationMapping should have target type and identifier."""
        from migration_intake.catalog.definitions import DestinationMapping

        dest = DestinationMapping(
            target_type="REGISTER",
            target_identifier="ISSUE_REGISTER",
        )

        assert dest.target_type == "REGISTER"
        assert dest.target_identifier == "ISSUE_REGISTER"

    def test_destination_output_types(self) -> None:
        """DestinationMapping should support output types."""
        from migration_intake.catalog.definitions import DestinationMapping

        dest = DestinationMapping(
            target_type="OUTPUT",
            target_identifier="TOPOLOGY",
        )

        assert dest.target_type == "OUTPUT"
        assert dest.target_identifier == "TOPOLOGY"


class TestRequiredLevel:
    """Tests for required level enumeration."""

    def test_required_levels_defined(self) -> None:
        """RequiredLevel should have expected values."""
        from migration_intake.catalog.definitions import RequiredLevel

        assert hasattr(RequiredLevel, "REQUIRED")
        assert hasattr(RequiredLevel, "CONDITIONAL")
        assert hasattr(RequiredLevel, "OPTIONAL")
        assert hasattr(RequiredLevel, "COMPUTED")


class TestCollectionMode:
    """Tests for collection mode enumeration."""

    def test_collection_modes_defined(self) -> None:
        """CollectionMode should have expected values."""
        from migration_intake.catalog.definitions import CollectionMode

        assert hasattr(CollectionMode, "DIRECT")
        assert hasattr(CollectionMode, "IMPORT")
        assert hasattr(CollectionMode, "COMPUTED")
        assert hasattr(CollectionMode, "APPROVAL")
