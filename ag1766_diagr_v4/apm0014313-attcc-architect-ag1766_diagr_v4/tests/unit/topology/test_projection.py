"""
Tests for topology projection adapter (P4).

These tests verify that the projection adapter correctly transforms
canonical snapshot JSON into topology projections for rendering.
"""

import hashlib
import json
from datetime import datetime, timezone

import pytest

from migration_intake.topology.projection import (
    PROJECTION_SCHEMA_VERSION,
    FactMapping,
    InvalidSnapshotError,
    MissingValuePolicy,
    ProjectedAnswer,
    ProjectedIdentifier,
    ProjectedResource,
    ProjectionAdapter,
    ProjectionContext,
    ProjectionIssueLevel,
    TopologyProjection,
    UnsupportedSchemaError,
    project_snapshot,
)


# ─────────────────────────────────────────────────────────────────────────────
# Test Fixtures
# ─────────────────────────────────────────────────────────────────────────────


def create_snapshot_json(
    schema_version: str = "2.0.0",
    application_id: str = "app-123",
    application_name: str = "Test Application",
    identifiers: list | None = None,
    answers: list | None = None,
    resources: list | None = None,
    permitted_gaps: list | None = None,
) -> tuple[str, str]:
    """Create a canonical snapshot JSON and its hash."""
    snapshot = {
        "schema_version": schema_version,
        "application": {
            "id": application_id,
            "name": application_name,
            "identifiers": identifiers or [],
        },
        "catalog": {
            "id": "cat-123",
            "version": "1.0.0",
            "source_sha256": "a" * 64,
            "catalog_hash": "b" * 64,
        },
        "intake": {
            "id": "intake-123",
            "state": "FROZEN",
            "frozen_at": "2026-09-18T12:00:00.000Z",
            "frozen_by": "test-user",
        },
        "answers": answers or [],
        "target_resources": resources or [],
        "wave_util_rows": [],
        "permitted_gaps": permitted_gaps or [],
    }

    json_str = json.dumps(snapshot, sort_keys=True, separators=(",", ":"))
    hash_str = hashlib.sha256(json_str.encode("utf-8")).hexdigest()

    return json_str, hash_str


# ─────────────────────────────────────────────────────────────────────────────
# Basic Projection Tests
# ─────────────────────────────────────────────────────────────────────────────


class TestProjectionAdapter:
    """Tests for ProjectionAdapter."""

    def test_project_empty_snapshot(self):
        """Project an empty snapshot."""
        snapshot_json, snapshot_hash = create_snapshot_json()
        context = ProjectionContext(environment="PROD")
        now = datetime.now(tz=timezone.utc)

        adapter = ProjectionAdapter()
        projection = adapter.project(
            snapshot_json=snapshot_json,
            snapshot_hash=snapshot_hash,
            context=context,
            projected_at=now,
        )

        assert projection.schema_version == PROJECTION_SCHEMA_VERSION
        assert projection.snapshot_hash == snapshot_hash
        assert projection.application_id == "app-123"
        assert projection.application_name == "Test Application"
        assert projection.context == context
        assert projection.is_valid
        assert not projection.has_blocking_issues

    def test_project_with_identifiers(self):
        """Project snapshot with application identifiers."""
        identifiers = [
            {"type": "CORRELATION", "value": "CORR-123", "is_primary": True},
            {"type": "MOTS", "value": "MOTS-456", "is_primary": False},
        ]
        snapshot_json, snapshot_hash = create_snapshot_json(identifiers=identifiers)
        context = ProjectionContext(environment="PROD")
        now = datetime.now(tz=timezone.utc)

        adapter = ProjectionAdapter()
        projection = adapter.project(
            snapshot_json=snapshot_json,
            snapshot_hash=snapshot_hash,
            context=context,
            projected_at=now,
        )

        assert len(projection.identifiers) == 2
        assert projection.identifiers[0].identifier_type == "CORRELATION"
        assert projection.identifiers[0].value == "CORR-123"
        assert projection.identifiers[0].is_primary is True
        assert projection.identifiers[1].identifier_type == "MOTS"

    def test_project_with_confirmed_answers(self):
        """Project snapshot with confirmed answers."""
        answers = [
            {
                "question_id": "q-1",
                "question_code": "CTL-001",
                "section_code": "CONTROL",
                "response_type": "TEXT",
                "value": "Test Value",
                "confirm_state": "CONFIRMED",
                "review_state": "APPROVED",
                "revision_number": 1,
                "provenance_references": ["ref-1"],
            },
            {
                "question_id": "q-2",
                "question_code": "CTL-002",
                "section_code": "CONTROL",
                "response_type": "TEXT_PAIR",
                "value": {"first": "Name", "second": "Acronym"},
                "confirm_state": "CONFIRMED",
                "review_state": "APPROVED",
                "revision_number": 2,
                "provenance_references": [],
            },
        ]
        snapshot_json, snapshot_hash = create_snapshot_json(answers=answers)
        context = ProjectionContext(environment="PROD")
        now = datetime.now(tz=timezone.utc)

        adapter = ProjectionAdapter()
        projection = adapter.project(
            snapshot_json=snapshot_json,
            snapshot_hash=snapshot_hash,
            context=context,
            projected_at=now,
        )

        assert len(projection.answers) == 2
        assert projection.answers[0].question_code == "CTL-001"
        assert projection.answers[0].value == "Test Value"
        assert projection.answers[0].confirm_state == "CONFIRMED"
        assert projection.answers[1].question_code == "CTL-002"
        assert projection.answers[1].value == {"first": "Name", "second": "Acronym"}

    def test_project_excludes_unconfirmed_answers(self):
        """Unconfirmed answers are excluded from projection."""
        answers = [
            {
                "question_id": "q-1",
                "question_code": "CTL-001",
                "section_code": "CONTROL",
                "response_type": "TEXT",
                "value": "Confirmed Value",
                "confirm_state": "CONFIRMED",
                "review_state": "APPROVED",
                "revision_number": 1,
                "provenance_references": [],
            },
            {
                "question_id": "q-2",
                "question_code": "CTL-002",
                "section_code": "CONTROL",
                "response_type": "TEXT",
                "value": "Draft Value",
                "confirm_state": "DRAFT",
                "review_state": "PENDING",
                "revision_number": 1,
                "provenance_references": [],
            },
        ]
        snapshot_json, snapshot_hash = create_snapshot_json(answers=answers)
        context = ProjectionContext(environment="PROD")
        now = datetime.now(tz=timezone.utc)

        adapter = ProjectionAdapter()
        projection = adapter.project(
            snapshot_json=snapshot_json,
            snapshot_hash=snapshot_hash,
            context=context,
            projected_at=now,
        )

        assert len(projection.answers) == 1
        assert projection.answers[0].question_code == "CTL-001"

    def test_project_with_resources(self):
        """Project snapshot with target resources."""
        resources = [
            {
                "logical_key": "vpc-prod-001",
                "kind": "VPC",
                "scope": {"lifecycle": "TARGET", "environment": "PROD"},
                "attributes": {"vpc_id": "vpc-123", "cidr_block": "10.0.0.0/16"},
                "review_state": "CONFIRMED",
                "revision_number": 1,
                "provenance_references": [],
            },
            {
                "logical_key": "subnet-prod-001",
                "kind": "SUBNET",
                "scope": {"lifecycle": "TARGET", "environment": "PROD"},
                "attributes": {"subnet_id": "subnet-123", "cidr_block": "10.0.1.0/24"},
                "review_state": "CONFIRMED",
                "revision_number": 1,
                "parent_logical_key": "vpc-prod-001",
                "provenance_references": [],
            },
        ]
        snapshot_json, snapshot_hash = create_snapshot_json(resources=resources)
        context = ProjectionContext(environment="PROD")
        now = datetime.now(tz=timezone.utc)

        adapter = ProjectionAdapter()
        projection = adapter.project(
            snapshot_json=snapshot_json,
            snapshot_hash=snapshot_hash,
            context=context,
            projected_at=now,
        )

        assert len(projection.resources) == 2
        # Resources sorted by (kind, logical_key) - SUBNET < VPC alphabetically
        resource_kinds = [r.kind for r in projection.resources]
        assert "VPC" in resource_kinds
        assert "SUBNET" in resource_kinds

    def test_project_filters_resources_by_environment(self):
        """Resources are filtered by target environment."""
        resources = [
            {
                "logical_key": "vpc-prod-001",
                "kind": "VPC",
                "scope": {"lifecycle": "TARGET", "environment": "PROD"},
                "attributes": {},
                "review_state": "CONFIRMED",
                "revision_number": 1,
                "provenance_references": [],
            },
            {
                "logical_key": "vpc-dev-001",
                "kind": "VPC",
                "scope": {"lifecycle": "TARGET", "environment": "DEV"},
                "attributes": {},
                "review_state": "CONFIRMED",
                "revision_number": 1,
                "provenance_references": [],
            },
        ]
        snapshot_json, snapshot_hash = create_snapshot_json(resources=resources)
        context = ProjectionContext(environment="PROD")
        now = datetime.now(tz=timezone.utc)

        adapter = ProjectionAdapter()
        projection = adapter.project(
            snapshot_json=snapshot_json,
            snapshot_hash=snapshot_hash,
            context=context,
            projected_at=now,
        )

        assert len(projection.resources) == 1
        assert projection.resources[0].logical_key == "vpc-prod-001"

    def test_project_warns_on_unconfirmed_resources(self):
        """Unconfirmed resources generate warnings."""
        resources = [
            {
                "logical_key": "vpc-prod-001",
                "kind": "VPC",
                "scope": {"lifecycle": "TARGET", "environment": "PROD"},
                "attributes": {},
                "review_state": "PROPOSED",
                "revision_number": 1,
                "provenance_references": [],
            },
        ]
        snapshot_json, snapshot_hash = create_snapshot_json(resources=resources)
        context = ProjectionContext(environment="PROD")
        now = datetime.now(tz=timezone.utc)

        adapter = ProjectionAdapter()
        projection = adapter.project(
            snapshot_json=snapshot_json,
            snapshot_hash=snapshot_hash,
            context=context,
            projected_at=now,
        )

        assert len(projection.resources) == 0
        assert len(projection.issues) == 1
        assert projection.issues[0].issue_id == "UNCONFIRMED_RESOURCE"
        assert projection.issues[0].level == ProjectionIssueLevel.WARNING
        assert not projection.issues[0].blocking


# ─────────────────────────────────────────────────────────────────────────────
# Error Handling Tests
# ─────────────────────────────────────────────────────────────────────────────


class TestProjectionErrors:
    """Tests for projection error handling."""

    def test_unsupported_schema_version(self):
        """Unsupported schema version raises error."""
        snapshot_json, _ = create_snapshot_json(schema_version="1.0.0")
        # Compute correct hash for the modified snapshot
        snapshot_hash = hashlib.sha256(snapshot_json.encode("utf-8")).hexdigest()
        context = ProjectionContext(environment="PROD")
        now = datetime.now(tz=timezone.utc)

        adapter = ProjectionAdapter()
        with pytest.raises(UnsupportedSchemaError) as exc_info:
            adapter.project(
                snapshot_json=snapshot_json,
                snapshot_hash=snapshot_hash,
                context=context,
                projected_at=now,
            )

        assert "1.0.0" in str(exc_info.value)

    def test_hash_mismatch(self):
        """Hash mismatch raises error."""
        snapshot_json, _ = create_snapshot_json()
        wrong_hash = "wrong" * 16
        context = ProjectionContext(environment="PROD")
        now = datetime.now(tz=timezone.utc)

        adapter = ProjectionAdapter()
        with pytest.raises(InvalidSnapshotError) as exc_info:
            adapter.project(
                snapshot_json=snapshot_json,
                snapshot_hash=wrong_hash,
                context=context,
                projected_at=now,
            )

        assert "hash mismatch" in str(exc_info.value).lower()

    def test_invalid_json(self):
        """Invalid JSON raises error."""
        snapshot_json = "not valid json"
        snapshot_hash = hashlib.sha256(snapshot_json.encode("utf-8")).hexdigest()
        context = ProjectionContext(environment="PROD")
        now = datetime.now(tz=timezone.utc)

        adapter = ProjectionAdapter()
        with pytest.raises(InvalidSnapshotError) as exc_info:
            adapter.project(
                snapshot_json=snapshot_json,
                snapshot_hash=snapshot_hash,
                context=context,
                projected_at=now,
            )

        assert "invalid" in str(exc_info.value).lower()


# ─────────────────────────────────────────────────────────────────────────────
# Determinism Tests
# ─────────────────────────────────────────────────────────────────────────────


class TestProjectionDeterminism:
    """Tests for projection determinism."""

    def test_same_input_same_hash(self):
        """Same input produces same projection hash."""
        snapshot_json, snapshot_hash = create_snapshot_json(
            identifiers=[
                {"type": "CORRELATION", "value": "CORR-123", "is_primary": True},
            ],
            answers=[
                {
                    "question_id": "q-1",
                    "question_code": "CTL-001",
                    "section_code": "CONTROL",
                    "response_type": "TEXT",
                    "value": "Test",
                    "confirm_state": "CONFIRMED",
                    "review_state": "APPROVED",
                    "revision_number": 1,
                    "provenance_references": [],
                },
            ],
        )
        context = ProjectionContext(environment="PROD")
        now = datetime(2026, 9, 18, 12, 0, 0, tzinfo=timezone.utc)

        adapter = ProjectionAdapter()

        projection1 = adapter.project(
            snapshot_json=snapshot_json,
            snapshot_hash=snapshot_hash,
            context=context,
            projected_at=now,
        )

        projection2 = adapter.project(
            snapshot_json=snapshot_json,
            snapshot_hash=snapshot_hash,
            context=context,
            projected_at=now,
        )

        assert projection1.projection_hash == projection2.projection_hash

    def test_different_context_different_hash(self):
        """Different context produces different projection hash."""
        snapshot_json, snapshot_hash = create_snapshot_json()
        now = datetime(2026, 9, 18, 12, 0, 0, tzinfo=timezone.utc)

        adapter = ProjectionAdapter()

        projection1 = adapter.project(
            snapshot_json=snapshot_json,
            snapshot_hash=snapshot_hash,
            context=ProjectionContext(environment="PROD"),
            projected_at=now,
        )

        projection2 = adapter.project(
            snapshot_json=snapshot_json,
            snapshot_hash=snapshot_hash,
            context=ProjectionContext(environment="DEV"),
            projected_at=now,
        )

        assert projection1.projection_hash != projection2.projection_hash


# ─────────────────────────────────────────────────────────────────────────────
# Convenience Function Tests
# ─────────────────────────────────────────────────────────────────────────────


class TestProjectSnapshotFunction:
    """Tests for project_snapshot convenience function."""

    def test_project_snapshot_basic(self):
        """Basic usage of project_snapshot function."""
        snapshot_json, snapshot_hash = create_snapshot_json()

        projection = project_snapshot(
            snapshot_json=snapshot_json,
            snapshot_hash=snapshot_hash,
            environment="PROD",
        )

        assert projection.is_valid
        assert projection.context.environment == "PROD"
        assert projection.context.site is None

    def test_project_snapshot_with_site(self):
        """project_snapshot with site specified."""
        snapshot_json, snapshot_hash = create_snapshot_json()

        projection = project_snapshot(
            snapshot_json=snapshot_json,
            snapshot_hash=snapshot_hash,
            environment="PROD",
            site="us-east-1a",
        )

        assert projection.context.site == "us-east-1a"

    def test_project_snapshot_with_variant(self):
        """project_snapshot with variant specified."""
        snapshot_json, snapshot_hash = create_snapshot_json()

        projection = project_snapshot(
            snapshot_json=snapshot_json,
            snapshot_hash=snapshot_hash,
            environment="PROD",
            variant="OUTPOST",
        )

        assert projection.context.variant == "OUTPOST"


# ─────────────────────────────────────────────────────────────────────────────
# Fact Mapping Tests
# ─────────────────────────────────────────────────────────────────────────────


class TestFactMappings:
    """Tests for fact mapping configuration."""

    def test_custom_fact_mappings(self):
        """Custom fact mappings can be provided."""
        custom_mappings = [
            FactMapping(
                question_code="CUSTOM-001",
                fact_path="custom.path",
                data_type="text",
                response_type="TEXT",
            ),
        ]

        adapter = ProjectionAdapter(fact_mappings=custom_mappings)
        assert len(adapter._fact_mappings) == 1
        assert adapter._mapping_by_code.get("CUSTOM-001") is not None

    def test_fact_mapping_properties(self):
        """FactMapping has correct properties."""
        mapping = FactMapping(
            question_code="TEST-001",
            fact_path="test.path",
            data_type="text",
            response_type="TEXT",
            lifecycle="TARGET",
            scope_rule="EXACT",
            cardinality="SINGLE",
            missing_policy=MissingValuePolicy.ERROR,
        )

        assert mapping.question_code == "TEST-001"
        assert mapping.fact_path == "test.path"
        assert mapping.lifecycle == "TARGET"
        assert mapping.missing_policy == MissingValuePolicy.ERROR
