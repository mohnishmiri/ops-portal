"""
Tests for ResourceRepository (P5B).

These tests verify the resource persistence layer implements
the P5A domain contract correctly.
"""

import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from migration_intake.persistence.models_resources import (
    TargetResource,
    TargetResourceRevision,
)
from migration_intake.persistence.naming import Base
from migration_intake.persistence.repositories.resources import (
    ActiveChildrenError,
    ConcurrencyConflictError,
    DuplicateLogicalKeyError,
    InvalidParentError,
    InvalidStateTransitionError,
    InvalidSuccessorError,
    ResourceNotFoundError,
    ResourceRepository,
    VALID_PARENT_KINDS,
)


# ─────────────────────────────────────────────────────────────────────────────
# Test Fixtures
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture
def engine():
    """Create in-memory SQLite engine with minimal schema."""
    engine = create_engine("sqlite:///:memory:", echo=False)

    # Create only the tables we need for resource tests
    # Create a minimal intakes table for FK reference
    with engine.connect() as conn:
        conn.execute(text("""
            CREATE TABLE intakes (
                id VARCHAR(36) PRIMARY KEY,
                application_id VARCHAR(36),
                state VARCHAR(32),
                content_epoch INTEGER NOT NULL DEFAULT 1,
                created_at TIMESTAMP
            )
        """))
        conn.commit()

    # Create resource tables
    TargetResource.__table__.create(engine, checkfirst=True)
    TargetResourceRevision.__table__.create(engine, checkfirst=True)

    return engine


@pytest.fixture
def session(engine):
    """Create session for tests."""
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


@pytest.fixture
def intake_id(session) -> str:
    """Create a test intake and return its ID."""
    intake_id = str(uuid.uuid4())
    now = datetime.now(tz=timezone.utc)

    # Insert minimal intake record for FK reference
    session.execute(
        text("INSERT INTO intakes (id, application_id, state, created_at) VALUES (:id, :app_id, :state, :created_at)"),
        {"id": intake_id, "app_id": str(uuid.uuid4()), "state": "ACTIVE", "created_at": now},
    )
    session.commit()

    return intake_id


@pytest.fixture
def repo(session) -> ResourceRepository:
    """Create repository instance."""
    return ResourceRepository(session)


def make_resource_id() -> str:
    """Generate a resource ID."""
    return str(uuid.uuid4())


# ─────────────────────────────────────────────────────────────────────────────
# Create Resource Tests
# ─────────────────────────────────────────────────────────────────────────────


class TestCreateResource:
    """Tests for resource creation."""

    def test_create_root_resource(self, repo, intake_id):
        """Create a root resource (PLACEMENT)."""
        resource_id = make_resource_id()
        now = datetime.now(tz=timezone.utc)

        result = repo.create_resource(
            resource_id=resource_id,
            intake_id=intake_id,
            logical_key="placement-prod-001",
            kind="PLACEMENT",
            lifecycle="TARGET",
            environment="PROD",
            site="us-east-1",
            tier=None,
            parent_id=None,
            payload={"outpost_id": "op-123", "outpost_name": "Prod Outpost"},
            review_state="PROPOSED",
            created_by="test-user",
            created_at=now,
        )

        assert result == resource_id

        # Verify resource
        resource = repo.get_resource(resource_id)
        assert resource is not None
        assert resource["logical_key"] == "placement-prod-001"
        assert resource["kind"] == "PLACEMENT"
        assert resource["lifecycle"] == "TARGET"
        assert resource["environment"] == "PROD"
        assert resource["resource_state"] == "ACTIVE"
        assert resource["revision_number"] == 1

    def test_create_child_resource(self, repo, intake_id):
        """Create a child resource with valid parent."""
        now = datetime.now(tz=timezone.utc)

        # Create parent (PLACEMENT)
        parent_id = make_resource_id()
        repo.create_resource(
            resource_id=parent_id,
            intake_id=intake_id,
            logical_key="placement-001",
            kind="PLACEMENT",
            lifecycle="TARGET",
            environment="PROD",
            site=None,
            tier=None,
            parent_id=None,
            payload={},
            review_state="CONFIRMED",
            created_by="test-user",
            created_at=now,
        )

        # Create child (ACCOUNT)
        child_id = make_resource_id()
        repo.create_resource(
            resource_id=child_id,
            intake_id=intake_id,
            logical_key="account-001",
            kind="ACCOUNT",
            lifecycle="TARGET",
            environment="PROD",
            site=None,
            tier=None,
            parent_id=parent_id,
            payload={"account_id": "123456789012"},
            review_state="PROPOSED",
            created_by="test-user",
            created_at=now,
        )

        # Verify child
        child = repo.get_resource(child_id)
        assert child is not None
        assert child["parent_id"] == parent_id

        # Verify parent has child
        children = repo.get_children(parent_id)
        assert len(children) == 1
        assert children[0]["id"] == child_id

    def test_create_duplicate_logical_key_fails(self, repo, intake_id):
        """Duplicate logical key in same scope fails."""
        now = datetime.now(tz=timezone.utc)

        repo.create_resource(
            resource_id=make_resource_id(),
            intake_id=intake_id,
            logical_key="placement-001",
            kind="PLACEMENT",
            lifecycle="TARGET",
            environment="PROD",
            site=None,
            tier=None,
            parent_id=None,
            payload={},
            review_state="PROPOSED",
            created_by="test-user",
            created_at=now,
        )

        with pytest.raises(DuplicateLogicalKeyError):
            repo.create_resource(
                resource_id=make_resource_id(),
                intake_id=intake_id,
                logical_key="placement-001",  # Same key
                kind="PLACEMENT",
                lifecycle="TARGET",
                environment="PROD",  # Same scope
                site=None,
                tier=None,
                parent_id=None,
                payload={},
                review_state="PROPOSED",
                created_by="test-user",
                created_at=now,
            )

    def test_create_with_invalid_parent_kind_fails(self, repo, intake_id):
        """Creating resource with invalid parent kind fails."""
        now = datetime.now(tz=timezone.utc)

        # Create VPC (should have ACCOUNT parent, not PLACEMENT)
        placement_id = make_resource_id()
        repo.create_resource(
            resource_id=placement_id,
            intake_id=intake_id,
            logical_key="placement-001",
            kind="PLACEMENT",
            lifecycle="TARGET",
            environment="PROD",
            site=None,
            tier=None,
            parent_id=None,
            payload={},
            review_state="CONFIRMED",
            created_by="test-user",
            created_at=now,
        )

        # Try to create VPC with PLACEMENT parent (invalid)
        with pytest.raises(InvalidParentError) as exc_info:
            repo.create_resource(
                resource_id=make_resource_id(),
                intake_id=intake_id,
                logical_key="vpc-001",
                kind="VPC",
                lifecycle="TARGET",
                environment="PROD",
                site=None,
                tier=None,
                parent_id=placement_id,  # Invalid - VPC needs ACCOUNT parent
                payload={},
                review_state="PROPOSED",
                created_by="test-user",
                created_at=now,
            )

        assert "Invalid parent kind" in str(exc_info.value)


# ─────────────────────────────────────────────────────────────────────────────
# Revision Tests
# ─────────────────────────────────────────────────────────────────────────────


class TestRevisions:
    """Tests for resource revisions."""

    def test_create_revision(self, repo, intake_id):
        """Create a new revision for existing resource."""
        now = datetime.now(tz=timezone.utc)

        resource_id = make_resource_id()
        repo.create_resource(
            resource_id=resource_id,
            intake_id=intake_id,
            logical_key="placement-001",
            kind="PLACEMENT",
            lifecycle="TARGET",
            environment="PROD",
            site=None,
            tier=None,
            parent_id=None,
            payload={"version": 1},
            review_state="PROPOSED",
            created_by="test-user",
            created_at=now,
        )

        # Create new revision
        new_rev = repo.create_revision(
            resource_id=resource_id,
            payload={"version": 2},
            review_state="CONFIRMED",
            authored_by="reviewer",
            authored_at=now,
            expected_revision=1,
        )

        assert new_rev == 2

        # Verify resource updated
        resource = repo.get_resource(resource_id)
        assert resource["revision_number"] == 2

        # Verify revision history
        revisions = repo.list_revisions(resource_id)
        assert len(revisions) == 2
        assert revisions[0]["revision_number"] == 1
        assert revisions[0]["payload"] == {"version": 1}
        assert revisions[1]["revision_number"] == 2
        assert revisions[1]["payload"] == {"version": 2}

    def test_create_revision_concurrency_conflict(self, repo, intake_id):
        """Concurrent revision creation fails with conflict."""
        now = datetime.now(tz=timezone.utc)

        resource_id = make_resource_id()
        repo.create_resource(
            resource_id=resource_id,
            intake_id=intake_id,
            logical_key="placement-001",
            kind="PLACEMENT",
            lifecycle="TARGET",
            environment="PROD",
            site=None,
            tier=None,
            parent_id=None,
            payload={},
            review_state="PROPOSED",
            created_by="test-user",
            created_at=now,
        )

        # Try to create revision with wrong expected version
        with pytest.raises(ConcurrencyConflictError):
            repo.create_revision(
                resource_id=resource_id,
                payload={},
                review_state="CONFIRMED",
                authored_by="reviewer",
                authored_at=now,
                expected_revision=99,  # Wrong version
            )

    def test_reparent_appends_complete_revision(self, repo, intake_id):
        now = datetime.now(tz=timezone.utc)
        parent_a = make_resource_id()
        parent_b = make_resource_id()
        child = make_resource_id()
        for resource_id, logical_key in ((parent_a, "placement-a"), (parent_b, "placement-b")):
            repo.create_resource(
                resource_id=resource_id,
                intake_id=intake_id,
                logical_key=logical_key,
                kind="PLACEMENT",
                lifecycle="TARGET",
                environment=None,
                site=None,
                tier=None,
                parent_id=None,
                payload={"outpost_id": logical_key},
                review_state="CONFIRMED",
                created_by="actor",
                created_at=now,
                provenance_references=["placement-evidence"],
            )
        repo.create_resource(
            resource_id=child,
            intake_id=intake_id,
            logical_key="account",
            kind="ACCOUNT",
            lifecycle="TARGET",
            environment=None,
            site=None,
            tier=None,
            parent_id=parent_a,
            payload={"account_id": "123456789012"},
            review_state="CONFIRMED",
            created_by="actor",
            created_at=now,
            provenance_references=["account-evidence"],
        )
        repo.reparent_resource(child, parent_b, "actor", now, 1)
        revisions = repo.list_revisions(child)
        assert [item["revision_number"] for item in revisions] == [1, 2]
        assert revisions[1]["parent_id"] == parent_b
        assert revisions[1]["provenance_references"] == ["account-evidence"]

    def test_retire_appends_revision_and_preserves_provenance(self, repo, intake_id):
        now = datetime.now(tz=timezone.utc)
        resource_id = make_resource_id()
        repo.create_resource(
            resource_id=resource_id,
            intake_id=intake_id,
            logical_key="placement",
            kind="PLACEMENT",
            lifecycle="TARGET",
            environment=None,
            site=None,
            tier=None,
            parent_id=None,
            payload={"outpost_id": "op"},
            review_state="CONFIRMED",
            created_by="actor",
            created_at=now,
            provenance_references=["evidence"],
        )
        repo.retire_resource(resource_id, "reviewer", now, "retired", 1)
        revisions = repo.list_revisions(resource_id)
        assert revisions[-1]["resource_state"] == "RETIRED"
        assert revisions[-1]["provenance_references"] == ["evidence"]


# ─────────────────────────────────────────────────────────────────────────────
# State Transition Tests
# ─────────────────────────────────────────────────────────────────────────────


class TestStateTransitions:
    """Tests for resource state transitions."""

    def test_retire_resource(self, repo, intake_id):
        """Retire an active resource."""
        now = datetime.now(tz=timezone.utc)

        resource_id = make_resource_id()
        repo.create_resource(
            resource_id=resource_id,
            intake_id=intake_id,
            logical_key="placement-001",
            kind="PLACEMENT",
            lifecycle="TARGET",
            environment="PROD",
            site=None,
            tier=None,
            parent_id=None,
            payload={},
            review_state="CONFIRMED",
            created_by="test-user",
            created_at=now,
        )

        repo.retire_resource(
            resource_id=resource_id,
            retired_by="admin",
            retired_at=now,
            reason="No longer needed",
            expected_revision=1,
        )

        resource = repo.get_resource(resource_id)
        assert resource["resource_state"] == "RETIRED"

    def test_retire_resource_with_active_children_fails(self, repo, intake_id):
        """Cannot retire resource with active children."""
        now = datetime.now(tz=timezone.utc)

        # Create parent
        parent_id = make_resource_id()
        repo.create_resource(
            resource_id=parent_id,
            intake_id=intake_id,
            logical_key="placement-001",
            kind="PLACEMENT",
            lifecycle="TARGET",
            environment="PROD",
            site=None,
            tier=None,
            parent_id=None,
            payload={},
            review_state="CONFIRMED",
            created_by="test-user",
            created_at=now,
        )

        # Create child
        child_id = make_resource_id()
        repo.create_resource(
            resource_id=child_id,
            intake_id=intake_id,
            logical_key="account-001",
            kind="ACCOUNT",
            lifecycle="TARGET",
            environment="PROD",
            site=None,
            tier=None,
            parent_id=parent_id,
            payload={},
            review_state="CONFIRMED",
            created_by="test-user",
            created_at=now,
        )

        # Try to retire parent
        with pytest.raises(ActiveChildrenError):
            repo.retire_resource(
                resource_id=parent_id,
                retired_by="admin",
                retired_at=now,
                reason="Test",
                expected_revision=1,
            )

    def test_supersede_resource(self, repo, intake_id):
        """Supersede a resource with a successor."""
        now = datetime.now(tz=timezone.utc)

        # Create original
        original_id = make_resource_id()
        repo.create_resource(
            resource_id=original_id,
            intake_id=intake_id,
            logical_key="placement-001",
            kind="PLACEMENT",
            lifecycle="TARGET",
            environment="PROD",
            site=None,
            tier=None,
            parent_id=None,
            payload={"version": "v1"},
            review_state="CONFIRMED",
            created_by="test-user",
            created_at=now,
        )

        # Create successor
        successor_id = make_resource_id()
        repo.create_resource(
            resource_id=successor_id,
            intake_id=intake_id,
            logical_key="placement-002",
            kind="PLACEMENT",
            lifecycle="TARGET",
            environment="PROD",
            site=None,
            tier=None,
            parent_id=None,
            payload={"version": "v2"},
            review_state="CONFIRMED",
            created_by="test-user",
            created_at=now,
        )

        # Supersede
        repo.supersede_resource(
            resource_id=original_id,
            successor_id=successor_id,
            superseded_by="admin",
            superseded_at=now,
            expected_revision=1,
        )

        original = repo.get_resource(original_id)
        assert original["resource_state"] == "SUPERSEDED"
        assert original["successor_id"] == successor_id


# ─────────────────────────────────────────────────────────────────────────────
# Query Tests
# ─────────────────────────────────────────────────────────────────────────────


class TestQueries:
    """Tests for resource queries."""

    def test_list_resources_for_intake(self, repo, intake_id):
        """List all resources for an intake."""
        now = datetime.now(tz=timezone.utc)

        # Create multiple resources
        for i in range(3):
            repo.create_resource(
                resource_id=make_resource_id(),
                intake_id=intake_id,
                logical_key=f"placement-{i:03d}",
                kind="PLACEMENT",
                lifecycle="TARGET",
                environment="PROD",
                site=None,
                tier=None,
                parent_id=None,
                payload={},
                review_state="CONFIRMED",
                created_by="test-user",
                created_at=now,
            )

        resources = repo.list_resources_for_intake(intake_id)
        assert len(resources) == 3

    def test_list_resources_filtered_by_kind(self, repo, intake_id):
        """List resources filtered by kind."""
        now = datetime.now(tz=timezone.utc)

        # Create PLACEMENT
        placement_id = make_resource_id()
        repo.create_resource(
            resource_id=placement_id,
            intake_id=intake_id,
            logical_key="placement-001",
            kind="PLACEMENT",
            lifecycle="TARGET",
            environment="PROD",
            site=None,
            tier=None,
            parent_id=None,
            payload={},
            review_state="CONFIRMED",
            created_by="test-user",
            created_at=now,
        )

        # Create ACCOUNT
        repo.create_resource(
            resource_id=make_resource_id(),
            intake_id=intake_id,
            logical_key="account-001",
            kind="ACCOUNT",
            lifecycle="TARGET",
            environment="PROD",
            site=None,
            tier=None,
            parent_id=placement_id,
            payload={},
            review_state="CONFIRMED",
            created_by="test-user",
            created_at=now,
        )

        placements = repo.list_resources_for_intake(intake_id, kind="PLACEMENT")
        assert len(placements) == 1
        assert placements[0]["kind"] == "PLACEMENT"

        accounts = repo.list_resources_for_intake(intake_id, kind="ACCOUNT")
        assert len(accounts) == 1
        assert accounts[0]["kind"] == "ACCOUNT"

    def test_get_resource_by_logical_key(self, repo, intake_id):
        """Get resource by logical key."""
        now = datetime.now(tz=timezone.utc)

        resource_id = make_resource_id()
        repo.create_resource(
            resource_id=resource_id,
            intake_id=intake_id,
            logical_key="placement-prod-001",
            kind="PLACEMENT",
            lifecycle="TARGET",
            environment="PROD",
            site=None,
            tier=None,
            parent_id=None,
            payload={},
            review_state="CONFIRMED",
            created_by="test-user",
            created_at=now,
        )

        resource = repo.get_resource_by_logical_key(
            intake_id=intake_id,
            logical_key="placement-prod-001",
            lifecycle="TARGET",
            environment="PROD",
        )

        assert resource is not None
        assert resource["id"] == resource_id


# ─────────────────────────────────────────────────────────────────────────────
# Parent Kind Validation Tests
# ─────────────────────────────────────────────────────────────────────────────


class TestParentKindValidation:
    """Tests for parent kind validation rules."""

    def test_valid_parent_kinds_defined(self):
        """Verify valid parent kinds are defined for all resource kinds."""
        expected_kinds = {
            "PLACEMENT",
            "ACCOUNT",
            "VPC",
            "SUBNET",
            "SECURITY_GROUP",
            "COMPUTE",
            "ENI",
            "DATABASE",
        }
        assert set(VALID_PARENT_KINDS.keys()) == expected_kinds

    def test_placement_has_no_parent(self):
        """PLACEMENT is a root resource with no valid parents."""
        assert VALID_PARENT_KINDS["PLACEMENT"] == set()

    def test_account_parent_is_placement(self):
        """ACCOUNT must have PLACEMENT parent."""
        assert VALID_PARENT_KINDS["ACCOUNT"] == {"PLACEMENT"}

    def test_vpc_parent_is_account(self):
        """VPC must have ACCOUNT parent."""
        assert VALID_PARENT_KINDS["VPC"] == {"ACCOUNT"}

    def test_subnet_parent_is_vpc(self):
        """SUBNET must have VPC parent."""
        assert VALID_PARENT_KINDS["SUBNET"] == {"VPC"}

    def test_compute_parent_is_subnet(self):
        """COMPUTE must have SUBNET parent."""
        assert VALID_PARENT_KINDS["COMPUTE"] == {"SUBNET"}
