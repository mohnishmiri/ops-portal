"""
Tests for Resource Service (P5C).

These tests verify the adoption and canonical integration functionality.
"""

import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from migration_intake.application.services.resources import (
    AdoptionRequest,
    InvalidPayloadError,
    InvalidResourceKindError,
    InvalidScopeError,
    RegisterStatus,
    ResourceKind,
    ResourceProposal,
    ResourceService,
    ReviewError,
    ReviewState,
    validate_payload,
    validate_scope,
)
from migration_intake.persistence.models_resources import (
    TargetResource,
    TargetResourceRevision,
)
from migration_intake.persistence.repositories.resources import (
    ResourceRepository,
    ResourceNotFoundError,
)


# ─────────────────────────────────────────────────────────────────────────────
# Test Fixtures
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture
def engine():
    """Create in-memory SQLite engine with minimal schema."""
    engine = create_engine("sqlite:///:memory:", echo=False)

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

    session.execute(
        text("INSERT INTO intakes (id, application_id, state, created_at) VALUES (:id, :app_id, :state, :created_at)"),
        {"id": intake_id, "app_id": str(uuid.uuid4()), "state": "ACTIVE", "created_at": now},
    )
    session.commit()

    return intake_id


@pytest.fixture
def repository(session) -> ResourceRepository:
    """Create repository instance."""
    return ResourceRepository(session)


@pytest.fixture
def service(repository) -> ResourceService:
    """Create service instance."""
    return ResourceService(repository)


# ─────────────────────────────────────────────────────────────────────────────
# Payload Validation Tests
# ─────────────────────────────────────────────────────────────────────────────


class TestPayloadValidation:
    """Tests for payload validation."""

    def test_valid_placement_payload(self):
        """Valid PLACEMENT payload passes validation."""
        payload = {"outpost_id": "op-123", "outpost_name": "Test Outpost"}
        errors = validate_payload(ResourceKind.PLACEMENT, payload)
        assert errors == []

    def test_missing_required_attribute(self):
        """Missing required attribute fails validation."""
        payload = {"outpost_name": "Test Outpost"}  # Missing outpost_id
        errors = validate_payload(ResourceKind.PLACEMENT, payload)
        assert len(errors) == 1
        assert "outpost_id" in errors[0]

    def test_undeclared_attribute(self):
        """Undeclared attribute fails validation."""
        payload = {"outpost_id": "op-123", "unknown_attr": "value"}
        errors = validate_payload(ResourceKind.PLACEMENT, payload)
        assert len(errors) == 1
        assert "unknown_attr" in errors[0]

    def test_valid_vpc_payload(self):
        """Valid VPC payload passes validation."""
        payload = {"vpc_id": "vpc-123", "cidr_block": "10.0.0.0/16"}
        errors = validate_payload(ResourceKind.VPC, payload)
        assert errors == []

    def test_vpc_missing_cidr(self):
        """VPC missing cidr_block fails validation."""
        payload = {"vpc_id": "vpc-123"}
        errors = validate_payload(ResourceKind.VPC, payload)
        assert len(errors) == 1
        assert "cidr_block" in errors[0]


class TestScopeValidation:
    """Tests for scope validation."""

    def test_valid_target_scope(self):
        """Valid TARGET scope passes validation."""
        errors = validate_scope(ResourceKind.VPC, "TARGET", "PROD", None)
        assert errors == []

    def test_invalid_lifecycle(self):
        """Invalid lifecycle fails validation."""
        errors = validate_scope(ResourceKind.VPC, "INVALID", "PROD", None)
        assert len(errors) == 1
        assert "lifecycle" in errors[0].lower()

    def test_placement_requires_site(self):
        """PLACEMENT requires site."""
        errors = validate_scope(ResourceKind.PLACEMENT, "TARGET", "PROD", None)
        assert len(errors) == 1
        assert "site" in errors[0].lower()

    def test_placement_with_site(self):
        """PLACEMENT with site passes validation."""
        errors = validate_scope(ResourceKind.PLACEMENT, "TARGET", "PROD", "us-east-1a")
        assert errors == []


# ─────────────────────────────────────────────────────────────────────────────
# Proposal Tests
# ─────────────────────────────────────────────────────────────────────────────


class TestResourceProposal:
    """Tests for resource proposal."""

    def test_propose_placement(self, service, intake_id):
        """Propose a PLACEMENT resource."""
        proposal = ResourceProposal(
            logical_key="placement-prod-001",
            kind=ResourceKind.PLACEMENT,
            lifecycle="TARGET",
            environment="PROD",
            site="us-east-1a",
            tier=None,
            parent_logical_key=None,
            payload={"outpost_id": "op-123", "outpost_name": "Prod Outpost"},
        )

        result = service.propose_resource(
            intake_id=intake_id,
            proposal=proposal,
            proposed_by="test-user",
        )

        assert result.success
        assert result.kind == "PLACEMENT"
        assert result.review_state == "PROPOSED"
        assert result.revision_number == 1

    def test_propose_vpc_with_parent(self, service, intake_id):
        """Propose a VPC with ACCOUNT parent."""
        # Create PLACEMENT first
        placement = ResourceProposal(
            logical_key="placement-001",
            kind=ResourceKind.PLACEMENT,
            lifecycle="TARGET",
            environment="PROD",
            site="us-east-1a",
            tier=None,
            parent_logical_key=None,
            payload={"outpost_id": "op-123"},
        )
        service.propose_resource(intake_id, placement, "test-user")

        # Create ACCOUNT
        account = ResourceProposal(
            logical_key="account-001",
            kind=ResourceKind.ACCOUNT,
            lifecycle="TARGET",
            environment="PROD",
            site="us-east-1a",
            tier=None,
            parent_logical_key="placement-001",
            payload={"account_id": "123456789012"},
        )
        service.propose_resource(intake_id, account, "test-user")

        # Create VPC
        vpc = ResourceProposal(
            logical_key="vpc-001",
            kind=ResourceKind.VPC,
            lifecycle="TARGET",
            environment="PROD",
            site="us-east-1a",
            tier=None,
            parent_logical_key="account-001",
            payload={"vpc_id": "vpc-123", "cidr_block": "10.0.0.0/16"},
        )
        result = service.propose_resource(intake_id, vpc, "test-user")

        assert result.success
        assert result.kind == "VPC"

    def test_propose_invalid_kind(self, service, intake_id):
        """Proposing invalid kind raises error."""
        proposal = ResourceProposal(
            logical_key="invalid-001",
            kind="INVALID_KIND",
            lifecycle="TARGET",
            environment="PROD",
            site=None,
            tier=None,
            parent_logical_key=None,
            payload={},
        )

        with pytest.raises(InvalidResourceKindError):
            service.propose_resource(intake_id, proposal, "test-user")

    def test_propose_invalid_payload(self, service, intake_id):
        """Proposing with invalid payload raises error."""
        proposal = ResourceProposal(
            logical_key="placement-001",
            kind=ResourceKind.PLACEMENT,
            lifecycle="TARGET",
            environment="PROD",
            site="us-east-1a",
            tier=None,
            parent_logical_key=None,
            payload={},  # Missing outpost_id
        )

        with pytest.raises(InvalidPayloadError):
            service.propose_resource(intake_id, proposal, "test-user")

    def test_propose_missing_parent(self, service, intake_id):
        """Proposing with missing parent raises error."""
        proposal = ResourceProposal(
            logical_key="vpc-001",
            kind=ResourceKind.VPC,
            lifecycle="TARGET",
            environment="PROD",
            site=None,
            tier=None,
            parent_logical_key="nonexistent-account",
            payload={"vpc_id": "vpc-123", "cidr_block": "10.0.0.0/16"},
        )

        with pytest.raises(Exception) as exc_info:
            service.propose_resource(intake_id, proposal, "test-user")
        assert "parent" in str(exc_info.value).lower()


# ─────────────────────────────────────────────────────────────────────────────
# Review Tests
# ─────────────────────────────────────────────────────────────────────────────


class TestResourceReview:
    """Tests for resource review."""

    def test_review_proposed_resource(self, service, intake_id):
        """Review a proposed resource."""
        # Create resource
        proposal = ResourceProposal(
            logical_key="placement-001",
            kind=ResourceKind.PLACEMENT,
            lifecycle="TARGET",
            environment="PROD",
            site="us-east-1a",
            tier=None,
            parent_logical_key=None,
            payload={"outpost_id": "op-123"},
        )
        create_result = service.propose_resource(intake_id, proposal, "test-user")

        # Review
        result = service.review_resource(
            resource_id=create_result.resource_id,
            new_state=ReviewState.REVIEWED,
            reviewed_by="reviewer",
            expected_revision=1,
        )

        assert result.success
        assert result.review_state == "REVIEWED"
        assert result.revision_number == 2

    def test_confirm_reviewed_resource(self, service, intake_id):
        """Confirm a reviewed resource."""
        # Create and review
        proposal = ResourceProposal(
            logical_key="placement-001",
            kind=ResourceKind.PLACEMENT,
            lifecycle="TARGET",
            environment="PROD",
            site="us-east-1a",
            tier=None,
            parent_logical_key=None,
            payload={"outpost_id": "op-123"},
        )
        create_result = service.propose_resource(intake_id, proposal, "test-user")

        service.review_resource(
            resource_id=create_result.resource_id,
            new_state=ReviewState.REVIEWED,
            reviewed_by="reviewer",
            expected_revision=1,
        )

        # Confirm
        result = service.confirm_resource(
            resource_id=create_result.resource_id,
            confirmed_by="approver",
            expected_revision=2,
        )

        assert result.success
        assert result.review_state == "CONFIRMED"

    def test_reject_resource(self, service, intake_id):
        """Reject a resource."""
        # Create
        proposal = ResourceProposal(
            logical_key="placement-001",
            kind=ResourceKind.PLACEMENT,
            lifecycle="TARGET",
            environment="PROD",
            site="us-east-1a",
            tier=None,
            parent_logical_key=None,
            payload={"outpost_id": "op-123"},
        )
        create_result = service.propose_resource(intake_id, proposal, "test-user")

        # Reject
        result = service.reject_resource(
            resource_id=create_result.resource_id,
            rejected_by="reviewer",
            expected_revision=1,
            rejection_reason="Invalid outpost ID",
        )

        assert result.success
        assert result.review_state == "REJECTED"

    def test_invalid_state_transition(self, service, intake_id):
        """Invalid state transition raises error."""
        # Create and confirm
        proposal = ResourceProposal(
            logical_key="placement-001",
            kind=ResourceKind.PLACEMENT,
            lifecycle="TARGET",
            environment="PROD",
            site="us-east-1a",
            tier=None,
            parent_logical_key=None,
            payload={"outpost_id": "op-123"},
        )
        create_result = service.propose_resource(intake_id, proposal, "test-user")

        service.review_resource(
            resource_id=create_result.resource_id,
            new_state=ReviewState.REVIEWED,
            reviewed_by="reviewer",
            expected_revision=1,
        )

        service.confirm_resource(
            resource_id=create_result.resource_id,
            confirmed_by="approver",
            expected_revision=2,
        )

        # Try to transition from CONFIRMED (invalid)
        with pytest.raises(ReviewError):
            service.review_resource(
                resource_id=create_result.resource_id,
                new_state=ReviewState.REVIEWED,
                reviewed_by="reviewer",
                expected_revision=3,
            )


# ─────────────────────────────────────────────────────────────────────────────
# Adoption Tests
# ─────────────────────────────────────────────────────────────────────────────


class TestProvisioningAdoption:
    """Tests for provisioning adoption."""

    def test_adopt_provisioning(self, service, intake_id):
        """Adopt a provisioning reference as PLACEMENT."""
        request = AdoptionRequest(
            reference_row_id="ref-123",
            intake_id=intake_id,
            logical_key="placement-prod-001",
            environment="PROD",
            site="us-east-1a",
            outpost_id="op-123",
            outpost_name="Production Outpost",
            provenance_references=["evidence:doc-456"],
        )

        result = service.adopt_provisioning(request, adopted_by="cloud-architect")

        assert result.success
        assert result.kind == "PLACEMENT"
        assert "adopted" in result.message.lower()

    def test_adoption_creates_provenance(self, service, repository, intake_id):
        """Adoption creates provenance reference to source row."""
        request = AdoptionRequest(
            reference_row_id="ref-123",
            intake_id=intake_id,
            logical_key="placement-001",
            environment="PROD",
            site="us-east-1a",
            outpost_id="op-123",
        )

        result = service.adopt_provisioning(request, adopted_by="cloud-architect")

        # Check provenance
        resource = repository.get_resource(result.resource_id)
        revision = repository.get_revision(result.resource_id, 1)

        assert revision is not None
        assert "provisioning:ref-123" in revision["provenance_references"]


# ─────────────────────────────────────────────────────────────────────────────
# Register Status Tests
# ─────────────────────────────────────────────────────────────────────────────


class TestRegisterStatus:
    """Tests for register status computation."""

    def test_empty_register(self, service, intake_id):
        """Empty register has EMPTY status."""
        result = service.compute_register_status(intake_id)

        assert result.status == RegisterStatus.EMPTY
        assert result.total_resources == 0
        assert "PLACEMENT" in result.missing_kinds

    def test_incomplete_register(self, service, intake_id):
        """Register with missing kinds is INCOMPLETE."""
        # Create only PLACEMENT
        proposal = ResourceProposal(
            logical_key="placement-001",
            kind=ResourceKind.PLACEMENT,
            lifecycle="TARGET",
            environment="PROD",
            site="us-east-1a",
            tier=None,
            parent_logical_key=None,
            payload={"outpost_id": "op-123"},
        )
        service.propose_resource(intake_id, proposal, "test-user")

        result = service.compute_register_status(intake_id)

        assert result.status == RegisterStatus.INCOMPLETE
        assert result.total_resources == 1
        assert "ACCOUNT" in result.missing_kinds
        assert "VPC" in result.missing_kinds

    def test_pending_review_register(self, service, intake_id):
        """Register with all kinds but pending review."""
        # Create all required resources
        placement = ResourceProposal(
            logical_key="placement-001",
            kind=ResourceKind.PLACEMENT,
            lifecycle="TARGET",
            environment="PROD",
            site="us-east-1a",
            tier=None,
            parent_logical_key=None,
            payload={"outpost_id": "op-123"},
        )
        service.propose_resource(intake_id, placement, "test-user")

        account = ResourceProposal(
            logical_key="account-001",
            kind=ResourceKind.ACCOUNT,
            lifecycle="TARGET",
            environment="PROD",
            site="us-east-1a",
            tier=None,
            parent_logical_key="placement-001",
            payload={"account_id": "123456789012"},
        )
        service.propose_resource(intake_id, account, "test-user")

        vpc = ResourceProposal(
            logical_key="vpc-001",
            kind=ResourceKind.VPC,
            lifecycle="TARGET",
            environment="PROD",
            site="us-east-1a",
            tier=None,
            parent_logical_key="account-001",
            payload={"vpc_id": "vpc-123", "cidr_block": "10.0.0.0/16"},
        )
        service.propose_resource(intake_id, vpc, "test-user")

        result = service.compute_register_status(intake_id)

        assert result.status == RegisterStatus.PENDING_REVIEW
        assert result.total_resources == 3
        assert result.pending_resources == 3
        assert result.missing_kinds == []

    def test_retired_resources_do_not_complete_register(self, service, intake_id):
        proposal = ResourceProposal(
            logical_key="placement-retired",
            kind=ResourceKind.PLACEMENT,
            lifecycle="TARGET",
            environment="PROD",
            site="us-east-1a",
            tier=None,
            parent_logical_key=None,
            payload={"outpost_id": "op-retired"},
        )
        result = service.propose_resource(intake_id, proposal, "test-user")
        service.review_resource(result.resource_id, ReviewState.REVIEWED, "reviewer", 1)
        service.confirm_resource(result.resource_id, "reviewer", 2)
        service._repository.retire_resource(
            result.resource_id,
            "reviewer",
            datetime.now(tz=timezone.utc),
            "synthetic retirement",
            3,
        )

        status = service.compute_register_status(intake_id, ["PLACEMENT"])
        assert status.status == RegisterStatus.EMPTY


# ─────────────────────────────────────────────────────────────────────────────
# Snapshot Integration Tests
# ─────────────────────────────────────────────────────────────────────────────


class TestSnapshotIntegration:
    """Tests for snapshot integration."""

    def test_get_resources_for_snapshot(self, service, intake_id):
        """Get confirmed resources for snapshot."""
        # Create and confirm a resource
        proposal = ResourceProposal(
            logical_key="placement-001",
            kind=ResourceKind.PLACEMENT,
            lifecycle="TARGET",
            environment="PROD",
            site="us-east-1a",
            tier=None,
            parent_logical_key=None,
            payload={"outpost_id": "op-123"},
        )
        create_result = service.propose_resource(intake_id, proposal, "test-user")

        service.review_resource(
            resource_id=create_result.resource_id,
            new_state=ReviewState.REVIEWED,
            reviewed_by="reviewer",
            expected_revision=1,
        )

        service.confirm_resource(
            resource_id=create_result.resource_id,
            confirmed_by="approver",
            expected_revision=2,
        )

        # Get for snapshot
        resources = service.get_resources_for_snapshot(intake_id, confirmed_only=True)

        assert len(resources) == 1
        assert resources[0]["logical_key"] == "placement-001"
        assert resources[0]["kind"] == "PLACEMENT"
        assert resources[0]["review_state"] == "CONFIRMED"
        assert resources[0]["attributes"]["outpost_id"] == "op-123"

    def test_snapshot_excludes_unconfirmed(self, service, intake_id):
        """Snapshot excludes unconfirmed resources."""
        # Create but don't confirm
        proposal = ResourceProposal(
            logical_key="placement-001",
            kind=ResourceKind.PLACEMENT,
            lifecycle="TARGET",
            environment="PROD",
            site="us-east-1a",
            tier=None,
            parent_logical_key=None,
            payload={"outpost_id": "op-123"},
        )
        service.propose_resource(intake_id, proposal, "test-user")

        # Get for snapshot
        resources = service.get_resources_for_snapshot(intake_id, confirmed_only=True)

        assert len(resources) == 0

    def test_snapshot_resource_ordering(self, service, intake_id):
        """Snapshot resources are sorted by (kind, logical_key)."""
        # Create resources in non-sorted order
        placement = ResourceProposal(
            logical_key="placement-001",
            kind=ResourceKind.PLACEMENT,
            lifecycle="TARGET",
            environment="PROD",
            site="us-east-1a",
            tier=None,
            parent_logical_key=None,
            payload={"outpost_id": "op-123"},
        )
        p_result = service.propose_resource(intake_id, placement, "test-user")
        service.review_resource(p_result.resource_id, ReviewState.REVIEWED, "r", 1)
        service.confirm_resource(p_result.resource_id, "a", 2)

        account = ResourceProposal(
            logical_key="account-001",
            kind=ResourceKind.ACCOUNT,
            lifecycle="TARGET",
            environment="PROD",
            site="us-east-1a",
            tier=None,
            parent_logical_key="placement-001",
            payload={"account_id": "123456789012"},
        )
        a_result = service.propose_resource(intake_id, account, "test-user")
        service.review_resource(a_result.resource_id, ReviewState.REVIEWED, "r", 1)
        service.confirm_resource(a_result.resource_id, "a", 2)

        # Get for snapshot
        resources = service.get_resources_for_snapshot(intake_id, confirmed_only=True)

        assert len(resources) == 2
        # Should be sorted: ACCOUNT before PLACEMENT
        assert resources[0]["kind"] == "ACCOUNT"
        assert resources[1]["kind"] == "PLACEMENT"
