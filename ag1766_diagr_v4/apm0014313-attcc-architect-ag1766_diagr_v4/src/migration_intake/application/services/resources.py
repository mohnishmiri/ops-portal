"""
Resource Service — P5C (Adoption and Canonical Integration).

Implements application-level commands for resource management:
- Resource proposal and review
- Provisioning adoption workflow
- Canonical snapshot integration
- Register status computation

Design rules:
- Validates target kind, payload schema, scope, parent relationship
- Explicit provisioning adoption (no automatic site selection)
- Integrates with P3 snapshot serializer and P4 projection adapter
- Computes register status from completeness and review state
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any

from migration_intake.persistence.repositories.resources import (
    DuplicateLogicalKeyError,
    InvalidParentError,
    ResourceNotFoundError,
    ResourceRepository,
)

# ─────────────────────────────────────────────────────────────────────────────
# Enums and Constants
# ─────────────────────────────────────────────────────────────────────────────


class ResourceKind(str, Enum):
    """Registered resource kinds."""

    PLACEMENT = "PLACEMENT"
    ACCOUNT = "ACCOUNT"
    VPC = "VPC"
    SUBNET = "SUBNET"
    SECURITY_GROUP = "SECURITY_GROUP"
    COMPUTE = "COMPUTE"
    ENI = "ENI"
    DATABASE = "DATABASE"


class ReviewState(str, Enum):
    """Resource review states."""

    PROPOSED = "PROPOSED"
    REVIEWED = "REVIEWED"
    CONFIRMED = "CONFIRMED"
    REJECTED = "REJECTED"


class RegisterStatus(str, Enum):
    """Computed register status."""

    EMPTY = "EMPTY"  # No resources
    INCOMPLETE = "INCOMPLETE"  # Some resources, not all confirmed
    PENDING_REVIEW = "PENDING_REVIEW"  # All resources present, awaiting review
    COMPLETE = "COMPLETE"  # All required resources confirmed


# Required attributes per resource kind
REQUIRED_ATTRIBUTES: dict[str, set[str]] = {
    "PLACEMENT": {"outpost_id"},
    "ACCOUNT": {"account_id"},
    "VPC": {"vpc_id", "cidr_block"},
    "SUBNET": {"subnet_id", "cidr_block", "availability_zone"},
    "SECURITY_GROUP": {"security_group_id"},
    "COMPUTE": {"instance_id", "instance_type"},
    "ENI": {"eni_id"},
    "DATABASE": {"db_instance_id", "engine"},
}

# Optional attributes per resource kind
OPTIONAL_ATTRIBUTES: dict[str, set[str]] = {
    "PLACEMENT": {"outpost_name", "outpost_arn", "availability_zone"},
    "ACCOUNT": {"account_name", "account_alias"},
    "VPC": {"vpc_name", "enable_dns_support", "enable_dns_hostnames"},
    "SUBNET": {"subnet_name", "map_public_ip_on_launch"},
    "SECURITY_GROUP": {"security_group_name", "description"},
    "COMPUTE": {"instance_name", "ami_id", "key_name"},
    "ENI": {"eni_name", "private_ip_address"},
    "DATABASE": {"db_name", "engine_version", "instance_class", "storage_type"},
}


# ─────────────────────────────────────────────────────────────────────────────
# Exceptions
# ─────────────────────────────────────────────────────────────────────────────


class ResourceServiceError(Exception):
    """Base class for resource service errors."""

    pass


class InvalidResourceKindError(ResourceServiceError):
    """Resource kind is not registered."""

    pass


class InvalidPayloadError(ResourceServiceError):
    """Payload does not match schema for resource kind."""

    pass


class InvalidScopeError(ResourceServiceError):
    """Scope is invalid for resource."""

    pass


class AdoptionError(ResourceServiceError):
    """Provisioning adoption failed."""

    pass


class ReviewError(ResourceServiceError):
    """Resource review operation failed."""

    pass


# ─────────────────────────────────────────────────────────────────────────────
# Data Classes
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class ResourceProposal:
    """A proposal to create or update a resource."""

    logical_key: str
    kind: ResourceKind
    lifecycle: str
    environment: str | None
    site: str | None
    tier: str | None
    parent_logical_key: str | None
    payload: dict[str, Any]
    provenance_references: list[str] = field(default_factory=list)


@dataclass
class AdoptionRequest:
    """Request to adopt a provisioning reference as a PLACEMENT resource."""

    reference_row_id: str
    intake_id: str
    logical_key: str
    environment: str
    site: str
    outpost_id: str
    outpost_name: str | None = None
    outpost_arn: str | None = None
    availability_zone: str | None = None
    provenance_references: list[str] = field(default_factory=list)


@dataclass
class ResourceResult:
    """Result of a resource operation."""

    resource_id: str
    logical_key: str
    kind: str
    revision_number: int
    review_state: str
    success: bool
    message: str | None = None


@dataclass
class RegisterStatusResult:
    """Computed register status for an intake."""

    intake_id: str
    status: RegisterStatus
    total_resources: int
    confirmed_resources: int
    pending_resources: int
    rejected_resources: int
    missing_kinds: list[str] = field(default_factory=list)
    issues: list[str] = field(default_factory=list)


# ─────────────────────────────────────────────────────────────────────────────
# Payload Validation
# ─────────────────────────────────────────────────────────────────────────────


def validate_payload(kind: ResourceKind, payload: dict[str, Any]) -> list[str]:
    """
    Validate payload against schema for resource kind.

    Returns list of validation errors (empty if valid).
    """
    errors = []

    # Check required attributes
    required = REQUIRED_ATTRIBUTES.get(kind.value, set())
    for attr in required:
        if attr not in payload or payload[attr] is None:
            errors.append(f"Missing required attribute: {attr}")

    # Check for undeclared attributes
    allowed = required | OPTIONAL_ATTRIBUTES.get(kind.value, set())
    for attr in payload:
        if attr not in allowed:
            errors.append(f"Undeclared attribute: {attr}")

    return errors


def validate_scope(
    kind: ResourceKind,
    lifecycle: str,
    environment: str | None,
    site: str | None,
) -> list[str]:
    """
    Validate scope for resource kind.

    Returns list of validation errors (empty if valid).
    """
    errors = []

    # Lifecycle must be SOURCE or TARGET
    if lifecycle not in ("SOURCE", "TARGET"):
        errors.append(f"Invalid lifecycle: {lifecycle}")

    # PLACEMENT requires site
    if kind == ResourceKind.PLACEMENT and not site:
        errors.append("PLACEMENT requires site")

    return errors


# ─────────────────────────────────────────────────────────────────────────────
# Resource Service
# ─────────────────────────────────────────────────────────────────────────────


class ResourceService:
    """
    Application service for resource management.

    Provides commands for:
    - Creating resource proposals
    - Reviewing and confirming resources
    - Provisioning adoption
    - Computing register status
    """

    def __init__(self, repository: ResourceRepository):
        self._repository = repository

    # ------------------------------------------------------------------
    # Proposal Commands
    # ------------------------------------------------------------------

    def propose_resource(
        self,
        intake_id: str,
        proposal: ResourceProposal,
        proposed_by: str,
    ) -> ResourceResult:
        """
        Create a new resource proposal.

        Args:
            intake_id: Intake ID
            proposal: Resource proposal
            proposed_by: User creating the proposal

        Returns:
            ResourceResult with created resource

        Raises:
            InvalidResourceKindError: Kind not registered
            InvalidPayloadError: Payload validation failed
            InvalidScopeError: Scope validation failed
            InvalidParentError: Parent not found or invalid
        """
        # Validate kind
        try:
            kind = ResourceKind(proposal.kind) if isinstance(proposal.kind, str) else proposal.kind
        except ValueError:
            raise InvalidResourceKindError(f"Unknown resource kind: {proposal.kind}")

        # Validate payload
        payload_errors = validate_payload(kind, proposal.payload)
        if payload_errors:
            raise InvalidPayloadError("; ".join(payload_errors))

        # Validate scope
        scope_errors = validate_scope(
            kind, proposal.lifecycle, proposal.environment, proposal.site
        )
        if scope_errors:
            raise InvalidScopeError("; ".join(scope_errors))

        # Resolve parent ID if specified
        parent_id = None
        if proposal.parent_logical_key:
            parent = self._repository.get_resource_by_logical_key(
                intake_id=intake_id,
                logical_key=proposal.parent_logical_key,
                lifecycle=proposal.lifecycle,
                environment=proposal.environment,
                site=proposal.site if proposal.environment is not None else None,
                tier=proposal.tier if proposal.environment is not None else None,
            )
            if parent is None:
                raise InvalidParentError(
                    f"Parent resource not found: {proposal.parent_logical_key}"
                )
            parent_id = parent["id"]

        # Create resource
        now = datetime.now(tz=UTC)
        resource_id = str(uuid.uuid4())

        try:
            self._repository.create_resource(
                resource_id=resource_id,
                intake_id=intake_id,
                logical_key=proposal.logical_key,
                kind=kind.value,
                lifecycle=proposal.lifecycle,
                environment=proposal.environment,
                site=proposal.site,
                tier=proposal.tier,
                parent_id=parent_id,
                payload=proposal.payload,
                review_state=ReviewState.PROPOSED.value,
                created_by=proposed_by,
                created_at=now,
                provenance_references=proposal.provenance_references,
            )
        except DuplicateLogicalKeyError:
            raise InvalidScopeError(
                f"Resource with logical key {proposal.logical_key} already exists in scope"
            )

        return ResourceResult(
            resource_id=resource_id,
            logical_key=proposal.logical_key,
            kind=kind.value,
            revision_number=1,
            review_state=ReviewState.PROPOSED.value,
            success=True,
            message="Resource proposed successfully",
        )

    def update_resource(
        self,
        resource_id: str,
        payload: dict[str, Any],
        updated_by: str,
        expected_revision: int,
        provenance_references: list[str] | None = None,
    ) -> ResourceResult:
        """
        Update an existing resource with new payload.

        Args:
            resource_id: Resource ID
            payload: New payload
            updated_by: User updating the resource
            expected_revision: Expected current revision for CAS
            provenance_references: Optional provenance references

        Returns:
            ResourceResult with updated resource
        """
        resource = self._repository.get_resource(resource_id)
        if resource is None:
            raise ResourceNotFoundError(f"Resource {resource_id} not found")

        # Validate payload
        kind = ResourceKind(resource["kind"])
        payload_errors = validate_payload(kind, payload)
        if payload_errors:
            raise InvalidPayloadError("; ".join(payload_errors))

        # Create new revision
        now = datetime.now(tz=UTC)
        new_revision = self._repository.create_revision(
            resource_id=resource_id,
            payload=payload,
            review_state=ReviewState.PROPOSED.value,
            authored_by=updated_by,
            authored_at=now,
            expected_revision=expected_revision,
            provenance_references=provenance_references,
        )

        return ResourceResult(
            resource_id=resource_id,
            logical_key=resource["logical_key"],
            kind=resource["kind"],
            revision_number=new_revision,
            review_state=ReviewState.PROPOSED.value,
            success=True,
            message="Resource updated successfully",
        )

    # ------------------------------------------------------------------
    # Review Commands
    # ------------------------------------------------------------------

    def review_resource(
        self,
        resource_id: str,
        new_state: ReviewState,
        reviewed_by: str,
        expected_revision: int,
        review_notes: str | None = None,
    ) -> ResourceResult:
        """
        Review a resource and update its review state.

        Args:
            resource_id: Resource ID
            new_state: New review state
            reviewed_by: User performing the review
            expected_revision: Expected current revision for CAS
            review_notes: Optional review notes

        Returns:
            ResourceResult with reviewed resource
        """
        resource = self._repository.get_resource(resource_id)
        if resource is None:
            raise ResourceNotFoundError(f"Resource {resource_id} not found")

        # Get current revision
        current_revision = self._repository.get_revision(
            resource_id, resource["revision_number"]
        )
        if current_revision is None:
            raise ReviewError("Current revision not found")

        # Validate state transition
        current_state = ReviewState(current_revision["review_state"])
        if not self._is_valid_review_transition(current_state, new_state):
            raise ReviewError(
                f"Invalid state transition: {current_state.value} -> {new_state.value}"
            )

        # Create new revision with updated review state
        now = datetime.now(tz=UTC)
        payload = current_revision["payload"]
        review_notes = review_notes.strip() if review_notes else None

        new_revision = self._repository.create_revision(
            resource_id=resource_id,
            payload=payload,
            review_state=new_state.value,
            authored_by=reviewed_by,
            authored_at=now,
            expected_revision=expected_revision,
            provenance_references=current_revision.get("provenance_references", []),
            change_reason=review_notes,
        )

        return ResourceResult(
            resource_id=resource_id,
            logical_key=resource["logical_key"],
            kind=resource["kind"],
            revision_number=new_revision,
            review_state=new_state.value,
            success=True,
            message=f"Resource {new_state.value.lower()}",
        )

    def confirm_resource(
        self,
        resource_id: str,
        confirmed_by: str,
        expected_revision: int,
    ) -> ResourceResult:
        """Confirm a reviewed resource."""
        return self.review_resource(
            resource_id=resource_id,
            new_state=ReviewState.CONFIRMED,
            reviewed_by=confirmed_by,
            expected_revision=expected_revision,
        )

    def reject_resource(
        self,
        resource_id: str,
        rejected_by: str,
        expected_revision: int,
        rejection_reason: str,
    ) -> ResourceResult:
        """Reject a resource."""
        return self.review_resource(
            resource_id=resource_id,
            new_state=ReviewState.REJECTED,
            reviewed_by=rejected_by,
            expected_revision=expected_revision,
            review_notes=rejection_reason,
        )

    @staticmethod
    def _is_valid_review_transition(
        current: ReviewState, target: ReviewState
    ) -> bool:
        """Check if review state transition is valid."""
        valid_transitions = {
            ReviewState.PROPOSED: {ReviewState.REVIEWED, ReviewState.REJECTED},
            ReviewState.REVIEWED: {ReviewState.CONFIRMED, ReviewState.REJECTED},
            ReviewState.CONFIRMED: set(),  # Cannot transition from CONFIRMED
            ReviewState.REJECTED: {ReviewState.PROPOSED},  # Can re-propose
        }
        return target in valid_transitions.get(current, set())

    # ------------------------------------------------------------------
    # Adoption Commands
    # ------------------------------------------------------------------

    def adopt_provisioning(
        self,
        request: AdoptionRequest,
        adopted_by: str,
    ) -> ResourceResult:
        """
        Adopt a provisioning reference row as a PLACEMENT resource.

        This is an explicit command - import order or confidence
        cannot automatically select a site.

        Args:
            request: Adoption request with reference row details
            adopted_by: User performing the adoption

        Returns:
            ResourceResult with created PLACEMENT resource
        """
        # Build payload from adoption request
        payload = {
            "outpost_id": request.outpost_id,
        }
        if request.outpost_name:
            payload["outpost_name"] = request.outpost_name
        if request.outpost_arn:
            payload["outpost_arn"] = request.outpost_arn
        if request.availability_zone:
            payload["availability_zone"] = request.availability_zone

        # Create proposal
        proposal = ResourceProposal(
            logical_key=request.logical_key,
            kind=ResourceKind.PLACEMENT,
            lifecycle="TARGET",
            environment=request.environment,
            site=request.site,
            tier=None,
            parent_logical_key=None,
            payload=payload,
            provenance_references=request.provenance_references + [
                f"provisioning:{request.reference_row_id}"
            ],
        )

        # Create the resource
        result = self.propose_resource(
            intake_id=request.intake_id,
            proposal=proposal,
            proposed_by=adopted_by,
        )

        result.message = f"Provisioning reference {request.reference_row_id} adopted as PLACEMENT"
        return result

    # ------------------------------------------------------------------
    # Register Status
    # ------------------------------------------------------------------

    def compute_register_status(
        self,
        intake_id: str,
        required_kinds: list[str] | None = None,
    ) -> RegisterStatusResult:
        """
        Compute register status from resource completeness and review state.

        Args:
            intake_id: Intake ID
            required_kinds: Optional list of required resource kinds

        Returns:
            RegisterStatusResult with computed status
        """
        # Default required kinds for topology
        if required_kinds is None:
            required_kinds = ["PLACEMENT", "ACCOUNT", "VPC"]

        # Get all resources for intake
        resources = self._repository.list_resources_for_intake(intake_id, state="ACTIVE")

        if not resources:
            return RegisterStatusResult(
                intake_id=intake_id,
                status=RegisterStatus.EMPTY,
                total_resources=0,
                confirmed_resources=0,
                pending_resources=0,
                rejected_resources=0,
                missing_kinds=required_kinds,
            )

        # Count by state
        confirmed = 0
        pending = 0
        rejected = 0
        present_kinds = set()

        for resource in resources:
            present_kinds.add(resource["kind"])

            # Get current revision to check review state
            revision = self._repository.get_revision(
                resource["id"], resource["revision_number"]
            )
            if revision:
                state = revision["review_state"]
                if state == ReviewState.CONFIRMED.value:
                    confirmed += 1
                elif state == ReviewState.REJECTED.value:
                    rejected += 1
                else:
                    pending += 1
            else:
                issues.append(f"Missing current revision for resource {resource['id']}")

        # Check for missing required kinds
        missing_kinds = [k for k in required_kinds if k not in present_kinds]

        # Determine status
        issues = []
        if missing_kinds:
            issues.append(f"Missing required resource kinds: {', '.join(missing_kinds)}")
            status = RegisterStatus.INCOMPLETE
        elif rejected > 0:
            issues.append(f"{rejected} resource(s) rejected")
            status = RegisterStatus.INCOMPLETE
        elif pending > 0:
            status = RegisterStatus.PENDING_REVIEW
        else:
            status = RegisterStatus.COMPLETE
        if issues:
            status = RegisterStatus.INCOMPLETE

        return RegisterStatusResult(
            intake_id=intake_id,
            status=status,
            total_resources=len(resources),
            confirmed_resources=confirmed,
            pending_resources=pending,
            rejected_resources=rejected,
            missing_kinds=missing_kinds,
            issues=issues,
        )

    # ------------------------------------------------------------------
    # Snapshot Integration
    # ------------------------------------------------------------------

    def get_resources_for_snapshot(
        self,
        intake_id: str,
        confirmed_only: bool = True,
    ) -> list[dict[str, Any]]:
        """
        Get resources formatted for canonical snapshot serialization.

        This integrates with P3 snapshot serializer interface.

        Args:
            intake_id: Intake ID
            confirmed_only: Only include confirmed resources

        Returns:
            List of resources in snapshot format
        """
        state_filter = "ACTIVE" if confirmed_only else None
        resources = self._repository.list_resources_for_intake(
            intake_id, state=state_filter
        )

        snapshot_resources = []
        for resource in resources:
            # Get current revision
            revision = self._repository.get_revision(
                resource["id"], resource["revision_number"]
            )
            if revision is None:
                continue

            # Filter by review state if confirmed_only
            if confirmed_only and revision["review_state"] != ReviewState.CONFIRMED.value:
                continue

            snapshot_resources.append({
                "logical_key": resource["logical_key"],
                "kind": resource["kind"],
                "scope": {
                    "lifecycle": resource["lifecycle"],
                    "environment": resource["environment"],
                    "site": resource["site"],
                    "tier": resource["tier"],
                },
                "attributes": revision["payload"],
                "review_state": revision["review_state"],
                "revision_number": revision["revision_number"],
                "parent_logical_key": resource.get("parent_id"),
                "provenance_references": revision.get("provenance_references", []),
            })

        # Sort by (kind, logical_key) for deterministic ordering
        snapshot_resources.sort(key=lambda r: (r["kind"], r["logical_key"]))

        return snapshot_resources
