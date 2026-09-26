"""
Contract tests for catalog publication — P05c/C04.

These tests verify:
- Publish idempotence (same version+hash succeeds)
- Conflicting release rejection (same version, different hash)
- Exact section/question order preservation
- All metadata round trips correctly
- Latest published release query
- Ordered sections for intake query
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timezone

import pytest

from migration_intake.persistence.unit_of_work import uow_context


class TestCatalogPublicationIdempotence:
    """Tests for catalog publication idempotence."""

    def test_publish_same_version_same_hash_succeeds(
        self, session_factory
    ) -> None:
        """Publishing same version with same hash is idempotent."""
        from migration_intake.application.services.catalogs import CatalogPublicationService

        service = CatalogPublicationService(session_factory)

        source_content = b"test catalog content v1"
        source_sha256 = hashlib.sha256(source_content).hexdigest()

        # First publish
        result1 = service.publish_release(
            semantic_version="1.0.0",
            source_filename="catalog_v1.yaml",
            source_sha256=source_sha256,
            catalog_hash=hashlib.sha256(b"compiled-v1").hexdigest(),
            compiler_version="1.0.0",
            sections=[],
        )

        # Second publish with same version and hash
        result2 = service.publish_release(
            semantic_version="1.0.0",
            source_filename="catalog_v1.yaml",
            source_sha256=source_sha256,
            catalog_hash=hashlib.sha256(b"compiled-v1").hexdigest(),
            compiler_version="1.0.0",
            sections=[],
        )

        assert result1["id"] == result2["id"]
        assert result1["pub_state"] == "PUBLISHED"
        assert result2["pub_state"] == "PUBLISHED"

    def test_publish_same_version_different_hash_fails(
        self, session_factory
    ) -> None:
        """Publishing same version with different hash fails."""
        from migration_intake.application.services.catalogs import CatalogPublicationService
        from migration_intake.application.errors import CatalogVersionConflictError

        service = CatalogPublicationService(session_factory)

        source_content1 = b"test catalog content v1"
        source_sha256_1 = hashlib.sha256(source_content1).hexdigest()

        source_content2 = b"test catalog content v1 modified"
        source_sha256_2 = hashlib.sha256(source_content2).hexdigest()

        # First publish
        service.publish_release(
            semantic_version="1.0.0",
            source_filename="catalog_v1.yaml",
            source_sha256=source_sha256_1,
            catalog_hash=hashlib.sha256(b"compiled-v1").hexdigest(),
            compiler_version="1.0.0",
            sections=[],
        )

        # Second publish with same version but different hash
        with pytest.raises(CatalogVersionConflictError) as exc_info:
            service.publish_release(
                semantic_version="1.0.0",
                source_filename="catalog_v1_modified.yaml",
                source_sha256=source_sha256_2,
                catalog_hash=hashlib.sha256(b"compiled-v1-modified").hexdigest(),
                compiler_version="1.0.0",
                sections=[],
            )

        assert "1.0.0" in str(exc_info.value)

    def test_publish_same_source_different_compiled_hash_fails(
        self, session_factory
    ) -> None:
        """A source-identical release cannot change its compiled contract."""
        from migration_intake.application.errors import CatalogVersionConflictError
        from migration_intake.application.services.catalogs import CatalogPublicationService

        service = CatalogPublicationService(session_factory)
        source_sha256 = hashlib.sha256(b"same source").hexdigest()
        service.publish_release(
            semantic_version="1.1.0",
            source_filename="catalog_v1_1.yaml",
            source_sha256=source_sha256,
            catalog_hash=hashlib.sha256(b"compiled-v1").hexdigest(),
            compiler_version="1.0.0",
            sections=[],
        )

        with pytest.raises(CatalogVersionConflictError):
            service.publish_release(
                semantic_version="1.1.0",
                source_filename="catalog_v1_1.yaml",
                source_sha256=source_sha256,
                catalog_hash="b" * 64,
                compiler_version="1.0.0",
                sections=[],
            )


class TestCatalogPublicationSectionOrder:
    """Tests for section and question ordering."""

    def test_sections_preserve_display_order(self, session_factory) -> None:
        """Sections are persisted with correct display_order."""
        from migration_intake.application.services.catalogs import CatalogPublicationService

        service = CatalogPublicationService(session_factory)

        source_sha256 = hashlib.sha256(b"ordered sections").hexdigest()

        result = service.publish_release(
            semantic_version="2.0.0",
            source_filename="catalog_v2.yaml",
            source_sha256=source_sha256,
            catalog_hash=hashlib.sha256(b"compiled-v2").hexdigest(),
            compiler_version="1.0.0",
            sections=[
                {
                    "section_code": "SEC-C",
                    "display_name": "Section C",
                    "display_order": 3,
                    "questions": [],
                },
                {
                    "section_code": "SEC-A",
                    "display_name": "Section A",
                    "display_order": 1,
                    "questions": [],
                },
                {
                    "section_code": "SEC-B",
                    "display_name": "Section B",
                    "display_order": 2,
                    "questions": [],
                },
            ],
        )

        # Query sections in order
        with uow_context(session_factory) as uow:
            sections = uow.catalogs.get_sections_for_release(result["id"])

        assert len(sections) == 3
        assert sections[0]["section_code"] == "SEC-A"
        assert sections[0]["display_order"] == 1
        assert sections[1]["section_code"] == "SEC-B"
        assert sections[1]["display_order"] == 2
        assert sections[2]["section_code"] == "SEC-C"
        assert sections[2]["display_order"] == 3

    def test_questions_preserve_display_order(self, session_factory) -> None:
        """Questions within sections preserve display_order."""
        from migration_intake.application.services.catalogs import CatalogPublicationService

        service = CatalogPublicationService(session_factory)

        source_sha256 = hashlib.sha256(b"ordered questions").hexdigest()

        result = service.publish_release(
            semantic_version="3.0.0",
            source_filename="catalog_v3.yaml",
            source_sha256=source_sha256,
            catalog_hash=hashlib.sha256(b"compiled-v3").hexdigest(),
            compiler_version="1.0.0",
            sections=[
                {
                    "section_code": "SEC-1",
                    "display_name": "Section 1",
                    "display_order": 1,
                    "questions": [
                        {
                            "question_code": "Q-003",
                            "question_text": "Third question",
                            "response_type": "YES_NO",
                            "required_level": "REQUIRED",
                            "collection_mode": "MANUAL",
                            "display_order": 3,
                        },
                        {
                            "question_code": "Q-001",
                            "question_text": "First question",
                            "response_type": "YES_NO",
                            "required_level": "REQUIRED",
                            "collection_mode": "MANUAL",
                            "display_order": 1,
                        },
                        {
                            "question_code": "Q-002",
                            "question_text": "Second question",
                            "response_type": "YES_NO",
                            "required_level": "REQUIRED",
                            "collection_mode": "MANUAL",
                            "display_order": 2,
                        },
                    ],
                },
            ],
        )

        # Query questions in order
        with uow_context(session_factory) as uow:
            sections = uow.catalogs.get_sections_for_release(result["id"])
            questions = uow.catalogs.get_questions_for_section(sections[0]["id"])

        assert len(questions) == 3
        assert questions[0]["question_code"] == "Q-001"
        assert questions[0]["display_order"] == 1
        assert questions[1]["question_code"] == "Q-002"
        assert questions[1]["display_order"] == 2
        assert questions[2]["question_code"] == "Q-003"
        assert questions[2]["display_order"] == 3


class TestCatalogPublicationMetadata:
    """Tests for metadata round-trip."""

    def test_question_metadata_round_trips(self, session_factory) -> None:
        """Question metadata (help_text, units, field_name) round trips."""
        from migration_intake.application.services.catalogs import CatalogPublicationService

        service = CatalogPublicationService(session_factory)

        source_sha256 = hashlib.sha256(b"metadata test").hexdigest()

        result = service.publish_release(
            semantic_version="4.0.0",
            source_filename="catalog_v4.yaml",
            source_sha256=source_sha256,
            catalog_hash=hashlib.sha256(b"compiled-v1").hexdigest(),
            compiler_version="1.0.0",
            sections=[
                {
                    "section_code": "META",
                    "display_name": "Metadata Section",
                    "display_order": 1,
                    "questions": [
                        {
                            "question_code": "META-001",
                            "question_text": "What is the memory size?",
                            "response_type": "QUANTITY",
                            "required_level": "REQUIRED",
                            "collection_mode": "MANUAL",
                            "display_order": 1,
                            "help_text": "Enter the total RAM in GB",
                            "units": "GB",
                            "field_name": "memory_size_gb",
                            "response_schema_version": "1.0",
                        },
                    ],
                },
            ],
        )

        with uow_context(session_factory) as uow:
            sections = uow.catalogs.get_sections_for_release(result["id"])
            questions = uow.catalogs.get_questions_for_section(sections[0]["id"])

        assert len(questions) == 1
        q = questions[0]
        assert q["help_text"] == "Enter the total RAM in GB"
        assert q["units"] == "GB"
        assert q["field_name"] == "memory_size_gb"
        assert q["response_schema_version"] == "1.0"

    def test_condition_ast_round_trips(self, session_factory) -> None:
        """Conditional AST is persisted and retrieved correctly."""
        from migration_intake.application.services.catalogs import CatalogPublicationService

        service = CatalogPublicationService(session_factory)

        source_sha256 = hashlib.sha256(b"condition test").hexdigest()

        condition_ast = {
            "type": "equals",
            "left": {"type": "ref", "code": "Q-001"},
            "right": {"type": "literal", "value": "YES"},
        }

        result = service.publish_release(
            semantic_version="5.0.0",
            source_filename="catalog_v5.yaml",
            source_sha256=source_sha256,
            catalog_hash=hashlib.sha256(b"compiled-v5").hexdigest(),
            compiler_version="1.0.0",
            sections=[
                {
                    "section_code": "COND",
                    "display_name": "Conditional Section",
                    "display_order": 1,
                    "questions": [
                        {
                            "question_code": "COND-001",
                            "question_text": "Conditional question",
                            "response_type": "YES_NO",
                            "required_level": "CONDITIONAL",
                            "collection_mode": "MANUAL",
                            "display_order": 1,
                            "condition_ast": condition_ast,
                        },
                    ],
                },
            ],
        )

        with uow_context(session_factory) as uow:
            sections = uow.catalogs.get_sections_for_release(result["id"])
            questions = uow.catalogs.get_questions_for_section(sections[0]["id"])

        assert questions[0]["condition_ast"] == condition_ast


class TestLatestPublishedRelease:
    """Tests for latest published release query."""

    def test_get_latest_published_release(self, session_factory) -> None:
        """Returns the most recently published release."""
        from migration_intake.application.services.catalogs import CatalogPublicationService

        service = CatalogPublicationService(session_factory)

        # Publish v1
        service.publish_release(
            semantic_version="1.0.0",
            source_filename="catalog_v1.yaml",
            source_sha256=hashlib.sha256(b"v1").hexdigest(),
            catalog_hash=hashlib.sha256(b"compiled-v1").hexdigest(),
            compiler_version="1.0.0",
            sections=[],
        )

        # Publish v2
        result_v2 = service.publish_release(
            semantic_version="2.0.0",
            source_filename="catalog_v2.yaml",
            source_sha256=hashlib.sha256(b"v2").hexdigest(),
            catalog_hash=hashlib.sha256(b"compiled-v2").hexdigest(),
            compiler_version="1.0.0",
            sections=[],
        )

        with uow_context(session_factory) as uow:
            latest = uow.catalogs.get_latest_published_release()

        assert latest is not None
        assert latest["id"] == result_v2["id"]
        assert latest["semantic_version"] == "2.0.0"

    def test_get_latest_published_release_empty(self, session_factory) -> None:
        """Returns None when no releases are published."""
        with uow_context(session_factory) as uow:
            latest = uow.catalogs.get_latest_published_release()

        assert latest is None


class TestSectionsForIntake:
    """Tests for getting ordered sections for an intake."""

    def test_get_sections_for_intake(self, session_factory) -> None:
        """Returns sections in display_order for an intake's catalog."""
        from migration_intake.application.services.catalogs import CatalogPublicationService
        from migration_intake.application.services.applications import ApplicationService
        from migration_intake.application.commands import (
            CreateApplicationCommand,
            CreateIntakeCommand,
        )
        from migration_intake.application.dto import ActorContext

        # Publish catalog
        catalog_service = CatalogPublicationService(session_factory)
        catalog = catalog_service.publish_release(
            semantic_version="6.0.0",
            source_filename="catalog_v6.yaml",
            source_sha256=hashlib.sha256(b"v6 intake test").hexdigest(),
            catalog_hash=hashlib.sha256(b"compiled-v6").hexdigest(),
            compiler_version="1.0.0",
            sections=[
                {
                    "section_code": "SEC-B",
                    "display_name": "Section B",
                    "display_order": 2,
                    "questions": [],
                },
                {
                    "section_code": "SEC-A",
                    "display_name": "Section A",
                    "display_order": 1,
                    "questions": [],
                },
            ],
        )

        # Create application and intake
        app_service = ApplicationService(session_factory)
        actor = ActorContext(actor_id=str(uuid.uuid4()))

        app_result = app_service.create_application(
            CreateApplicationCommand(
                display_name="Test App",
                identifiers=(),
                actor=actor,
            )
        )

        intake_result = app_service.create_intake(
            CreateIntakeCommand(
                application_id=app_result["id"],
                catalog_release_id=catalog["id"],
                actor=actor,
            )
        )

        # Get sections for intake
        with uow_context(session_factory) as uow:
            sections = uow.catalogs.get_sections_for_intake(intake_result["id"])

        assert len(sections) == 2
        assert sections[0]["section_code"] == "SEC-A"
        assert sections[1]["section_code"] == "SEC-B"
