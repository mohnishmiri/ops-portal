"""
ResourceRepository — P5B (Resource Persistence).

Implements the repository port defined in P5A for target resource persistence.

Design rules:
- Returns plain dicts, never ORM entity instances
- No independent session management; session is owned by UnitOfWork
- Compare-and-set semantics for concurrency control
- Append-only revisions
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from migration_intake.persistence.models_resources import (
    TargetResource,
    TargetResourceRevision,
    TopologyResourceLink,
    TopologyResourceLinkRevision,
)
from migration_intake.persistence.repositories.intakes import IntakeRepository
from migration_intake.topology.scope import resource_scope_key


class DuplicateLogicalKeyError(Exception):
    """Logical key already exists in scope."""

    pass


class InvalidParentError(Exception):
    """Parent resource is invalid (not found, wrong kind, or cycle)."""

    pass


class ResourceNotFoundError(Exception):
    """Resource does not exist."""

    pass


class ConcurrencyConflictError(Exception):
    """Expected revision does not match current revision."""

    pass


class ActiveChildrenError(Exception):
    """Cannot retire/supersede resource with active children."""

    pass


class InvalidSuccessorError(Exception):
    """Successor resource is invalid for supersession."""

    pass


class InvalidStateTransitionError(Exception):
    """State transition is not allowed."""

    pass


# Valid parent kinds for each child kind
VALID_PARENT_KINDS: dict[str, set[str]] = {
    "PLACEMENT": set(),  # Root resource
    "ACCOUNT": {"PLACEMENT"},
    "VPC": {"ACCOUNT"},
    "SUBNET": {"VPC"},
    "SECURITY_GROUP": {"VPC"},
    "COMPUTE": {"SUBNET"},
    "ENI": {"SUBNET"},
    "DATABASE": {"SUBNET"},
}


class ResourceRepository:
    """Persistence adapter for target resources."""

    def __init__(self, session: Session) -> None:
        self._session = session

    # ------------------------------------------------------------------
    # Create operations
    # ------------------------------------------------------------------

    def create_resource(
        self,
        resource_id: str,
        intake_id: str,
        logical_key: str,
        kind: str,
        lifecycle: str,
        environment: str | None,
        site: str | None,
        tier: str | None,
        parent_id: str | None,
        payload: dict[str, Any],
        review_state: str,
        created_by: str,
        created_at: datetime,
        provenance_references: list[str] | None = None,
    ) -> str:
        """
        Create a new resource with initial revision.

        Returns:
            Resource ID

        Raises:
            DuplicateLogicalKeyError: Logical key exists in scope
            InvalidParentError: Parent not found or invalid kind
        """
        IntakeRepository(self._session).lock_content_epoch(intake_id)

        # Validate parent
        if parent_id is not None:
            parent = self._get_resource_entity(parent_id)
            if parent is None:
                raise InvalidParentError(f"Parent resource {parent_id} not found")

            valid_parents = VALID_PARENT_KINDS.get(kind, set())
            if parent.kind not in valid_parents:
                raise InvalidParentError(
                    f"Invalid parent kind {parent.kind} for child kind {kind}. "
                    f"Valid parent kinds: {valid_parents}"
                )

            # Check for cycles
            if self._would_create_cycle(resource_id, parent_id):
                raise InvalidParentError("Parent reference would create a cycle")

        # Check for duplicate logical key
        existing = self._get_resource_by_logical_key(
            intake_id, logical_key, lifecycle, environment
        )
        if existing is not None:
            raise DuplicateLogicalKeyError(
                f"Logical key {logical_key} already exists in scope"
            )

        # Create resource
        scope_key = resource_scope_key(
            lifecycle=lifecycle,
            environment=environment,
            site=site,
            tier=tier,
        )
        resource = TargetResource(
            id=resource_id,
            intake_id=intake_id,
            logical_key=logical_key,
            kind=kind,
            scope_key=scope_key,
            lifecycle=lifecycle,
            environment=environment,
            site=site,
            tier=tier,
            parent_id=parent_id,
            revision_number=1,
            row_version=1,
            resource_state="ACTIVE",
            created_at=created_at,
            updated_at=created_at,
            created_by=created_by,
        )
        self._session.add(resource)
        self._session.flush()

        # Create initial revision
        import uuid

        revision_id = str(uuid.uuid4())
        revision = TargetResourceRevision(
            id=revision_id,
            resource_id=resource_id,
            revision_number=1,
            payload=payload,
            review_state=review_state,
            provenance_references=provenance_references or [],
            parent_id=parent_id,
            resource_state="ACTIVE",
            change_reason="CREATED",
            authored_at=created_at,
            authored_by=created_by,
        )
        self._session.add(revision)
        self._session.flush()

        # Update resource with current revision
        stmt = (
            update(TargetResource)
            .where(TargetResource.id == resource_id)
            .values(current_revision_id=revision_id)
        )
        self._session.execute(stmt)
        self._session.flush()
        IntakeRepository(self._session).bump_content_epoch(intake_id)
        return resource_id

    def create_revision(
        self,
        resource_id: str,
        payload: dict[str, Any],
        review_state: str,
        authored_by: str,
        authored_at: datetime,
        expected_revision: int,
        provenance_references: list[str] | None = None,
        parent_id: str | None = None,
        preserve_parent: bool = True,
        resource_state: str | None = None,
        successor_id: str | None = None,
        set_successor: bool = False,
        change_reason: str | None = None,
    ) -> int:
        """
        Create a new revision for an existing resource.

        Uses compare-and-set semantics for concurrency control.

        Returns:
            New revision number

        Raises:
            ResourceNotFoundError: Resource does not exist
            ConcurrencyConflictError: Expected revision mismatch
        """
        resource = self._get_resource_entity(resource_id)
        if resource is None:
            raise ResourceNotFoundError(f"Resource {resource_id} not found")
        intake_id = str(resource.intake_id)
        IntakeRepository(self._session).lock_content_epoch(intake_id)
        self._session.refresh(resource)

        if resource.revision_number != expected_revision:
            raise ConcurrencyConflictError(
                f"Expected revision {expected_revision}, "
                f"but current is {resource.revision_number}"
            )

        new_revision_number = resource.revision_number + 1
        effective_parent_id = resource.parent_id if preserve_parent else parent_id
        effective_resource_state = resource_state or resource.resource_state

        # Create revision
        import uuid

        revision_id = str(uuid.uuid4())
        revision = TargetResourceRevision(
            id=revision_id,
            resource_id=resource_id,
            revision_number=new_revision_number,
            payload=payload,
            review_state=review_state,
            provenance_references=provenance_references or [],
            parent_id=effective_parent_id,
            resource_state=effective_resource_state,
            change_reason=change_reason,
            authored_at=authored_at,
            authored_by=authored_by,
        )
        self._session.add(revision)
        self._session.flush()

        # Update resource
        stmt = (
            update(TargetResource)
            .where(
                TargetResource.id == resource_id,
                TargetResource.revision_number == expected_revision,
            )
            .values(
                current_revision_id=revision_id,
                revision_number=new_revision_number,
                row_version=TargetResource.row_version + 1,
                updated_at=authored_at,
            )
        )
        result = self._session.execute(stmt)
        if result.rowcount == 0:
            raise ConcurrencyConflictError("Concurrent modification detected")
        self._session.flush()

        if set_successor:
            self._session.execute(
                update(TargetResource)
                .where(TargetResource.id == resource_id)
                .values(successor_id=successor_id)
            )
            self._session.flush()

        IntakeRepository(self._session).bump_content_epoch(intake_id)
        return new_revision_number

    # ------------------------------------------------------------------
    # Read operations
    # ------------------------------------------------------------------

    def get_resource(self, resource_id: str) -> dict[str, Any] | None:
        """Get resource with current revision."""
        resource = self._get_resource_entity(resource_id)
        if resource is None:
            return None
        return self._resource_to_dict(resource)

    def get_resource_by_logical_key(
        self,
        intake_id: str,
        logical_key: str,
        lifecycle: str,
        environment: str | None,
        site: str | None = None,
        tier: str | None = None,
    ) -> dict[str, Any] | None:
        """Get resource by logical key within scope."""
        resource = self._get_resource_by_logical_key(
            intake_id, logical_key, lifecycle, environment, site, tier
        )
        if resource is None:
            return None
        return self._resource_to_dict(resource)

    def get_revision(
        self,
        resource_id: str,
        revision_number: int,
    ) -> dict[str, Any] | None:
        """Get specific revision of a resource."""
        stmt = select(TargetResourceRevision).where(
            TargetResourceRevision.resource_id == resource_id,
            TargetResourceRevision.revision_number == revision_number,
        )
        revision = self._session.execute(stmt).scalar_one_or_none()
        if revision is None:
            return None
        return self._revision_to_dict(revision)

    def list_revisions(self, resource_id: str) -> list[dict[str, Any]]:
        """List all revisions for a resource."""
        stmt = (
            select(TargetResourceRevision)
            .where(TargetResourceRevision.resource_id == resource_id)
            .order_by(TargetResourceRevision.revision_number)
        )
        revisions = self._session.execute(stmt).scalars().all()
        return [self._revision_to_dict(r) for r in revisions]

    def get_children(
        self,
        resource_id: str,
        state: str | None = None,
    ) -> list[dict[str, Any]]:
        """Get child resources, optionally filtered by state."""
        stmt = select(TargetResource).where(TargetResource.parent_id == resource_id)
        if state is not None:
            stmt = stmt.where(TargetResource.resource_state == state)
        children = self._session.execute(stmt).scalars().all()
        return [self._resource_to_dict(c) for c in children]

    def list_resources_for_intake(
        self,
        intake_id: str,
        kind: str | None = None,
        state: str | None = None,
    ) -> list[dict[str, Any]]:
        """List resources for an intake, optionally filtered."""
        stmt = select(TargetResource).where(TargetResource.intake_id == intake_id)
        if kind is not None:
            stmt = stmt.where(TargetResource.kind == kind)
        if state is not None:
            stmt = stmt.where(TargetResource.resource_state == state)
        stmt = stmt.order_by(TargetResource.kind, TargetResource.logical_key)
        resources = self._session.execute(stmt).scalars().all()
        return [self._resource_to_dict(r) for r in resources]

    def list_links_for_intake(
        self, intake_id: str, state: str | None = None
    ) -> list[dict[str, Any]]:
        """List typed relationship heads for one intake."""
        stmt = select(TopologyResourceLink).where(
            TopologyResourceLink.intake_id == intake_id
        )
        if state is not None:
            stmt = stmt.where(TopologyResourceLink.link_state == state)
        links = self._session.execute(
            stmt.order_by(
                TopologyResourceLink.relationship_type,
                TopologyResourceLink.source_resource_id,
                TopologyResourceLink.target_resource_id,
            )
        ).scalars().all()
        return [self._link_to_dict(link) for link in links]

    def get_link_revision(
        self, link_id: str, revision_number: int
    ) -> dict[str, Any] | None:
        """Return one immutable relationship revision."""
        revision = self._session.execute(
            select(TopologyResourceLinkRevision).where(
                TopologyResourceLinkRevision.link_id == link_id,
                TopologyResourceLinkRevision.revision_number == revision_number,
            )
        ).scalar_one_or_none()
        if revision is None:
            return None
        return self._link_revision_to_dict(revision)

    # ------------------------------------------------------------------
    # State transition operations
    # ------------------------------------------------------------------

    def retire_resource(
        self,
        resource_id: str,
        retired_by: str,
        retired_at: datetime,
        reason: str,
        expected_revision: int,
    ) -> None:
        """
        Retire a resource.

        Raises:
            ResourceNotFoundError: Resource does not exist
            ActiveChildrenError: Resource has active children
            ConcurrencyConflictError: Expected revision mismatch
            InvalidStateTransitionError: Resource is not active
        """
        resource = self._get_resource_entity(resource_id)
        if resource is None:
            raise ResourceNotFoundError(f"Resource {resource_id} not found")

        if resource.revision_number != expected_revision:
            raise ConcurrencyConflictError(
                f"Expected revision {expected_revision}, "
                f"but current is {resource.revision_number}"
            )

        if resource.resource_state != "ACTIVE":
            raise InvalidStateTransitionError(
                f"Cannot retire resource in state {resource.resource_state}"
            )

        # Check for active children
        active_children = self.get_children(resource_id, state="ACTIVE")
        if active_children:
            raise ActiveChildrenError(
                f"Cannot retire resource with {len(active_children)} active children"
            )

        current = self.get_revision(resource_id, expected_revision)
        if current is None:
            raise ResourceNotFoundError("Current resource revision not found")
        self.create_revision(
            resource_id=resource_id,
            payload=current["payload"],
            review_state=current["review_state"],
            authored_by=retired_by,
            authored_at=retired_at,
            expected_revision=expected_revision,
            provenance_references=current["provenance_references"],
            resource_state="RETIRED",
            change_reason=reason,
        )
        self._session.execute(
            update(TargetResource)
            .where(TargetResource.id == resource_id)
            .values(resource_state="RETIRED")
        )
        self._session.flush()

    def supersede_resource(
        self,
        resource_id: str,
        successor_id: str,
        superseded_by: str,
        superseded_at: datetime,
        expected_revision: int,
    ) -> None:
        """
        Supersede a resource with a successor.

        Raises:
            ResourceNotFoundError: Resource or successor not found
            InvalidSuccessorError: Successor invalid (wrong kind, scope, etc.)
            ActiveChildrenError: Resource has active children not reparented
            ConcurrencyConflictError: Expected revision mismatch
            InvalidStateTransitionError: Resource is not active
        """
        resource = self._get_resource_entity(resource_id)
        if resource is None:
            raise ResourceNotFoundError(f"Resource {resource_id} not found")

        successor = self._get_resource_entity(successor_id)
        if successor is None:
            raise ResourceNotFoundError(f"Successor resource {successor_id} not found")

        if resource.revision_number != expected_revision:
            raise ConcurrencyConflictError(
                f"Expected revision {expected_revision}, "
                f"but current is {resource.revision_number}"
            )

        if resource.resource_state != "ACTIVE":
            raise InvalidStateTransitionError(
                f"Cannot supersede resource in state {resource.resource_state}"
            )

        # Validate successor
        if successor.kind != resource.kind:
            raise InvalidSuccessorError(
                f"Successor kind {successor.kind} does not match "
                f"resource kind {resource.kind}"
            )

        if successor.lifecycle != resource.lifecycle:
            raise InvalidSuccessorError(
                f"Successor lifecycle {successor.lifecycle} does not match "
                f"resource lifecycle {resource.lifecycle}"
            )

        # Check for active children
        active_children = self.get_children(resource_id, state="ACTIVE")
        if active_children:
            raise ActiveChildrenError(
                f"Cannot supersede resource with {len(active_children)} active children. "
                "Reparent or retire children first."
            )

        if successor_id == resource_id:
            raise InvalidSuccessorError("A resource cannot supersede itself")
        if successor.resource_state != "ACTIVE":
            raise InvalidSuccessorError("Successor must be ACTIVE")
        if successor.intake_id != resource.intake_id or (
            successor.environment != resource.environment
            or successor.site != resource.site
            or successor.tier != resource.tier
        ):
            raise InvalidSuccessorError("Successor scope must match resource scope")
        current = self.get_revision(resource_id, expected_revision)
        if current is None:
            raise ResourceNotFoundError("Current resource revision not found")
        self.create_revision(
            resource_id=resource_id,
            payload=current["payload"],
            review_state=current["review_state"],
            authored_by=superseded_by,
            authored_at=superseded_at,
            expected_revision=expected_revision,
            provenance_references=current["provenance_references"],
            resource_state="SUPERSEDED",
            successor_id=successor_id,
            set_successor=True,
            change_reason="SUPERSEDED",
        )
        self._session.execute(
            update(TargetResource)
            .where(TargetResource.id == resource_id)
            .values(resource_state="SUPERSEDED", successor_id=successor_id)
        )
        self._session.flush()

    def reparent_resource(
        self,
        resource_id: str,
        new_parent_id: str,
        reparented_by: str,
        reparented_at: datetime,
        expected_revision: int,
    ) -> None:
        """
        Change the parent of a resource.

        Raises:
            ResourceNotFoundError: Resource or new parent not found
            InvalidParentError: New parent invalid (wrong kind, scope, cycle)
            ConcurrencyConflictError: Expected revision mismatch
        """
        resource = self._get_resource_entity(resource_id)
        if resource is None:
            raise ResourceNotFoundError(f"Resource {resource_id} not found")

        new_parent = self._get_resource_entity(new_parent_id)
        if new_parent is None:
            raise ResourceNotFoundError(f"New parent resource {new_parent_id} not found")

        if resource.revision_number != expected_revision:
            raise ConcurrencyConflictError(
                f"Expected revision {expected_revision}, "
                f"but current is {resource.revision_number}"
            )

        # Validate new parent kind
        valid_parents = VALID_PARENT_KINDS.get(resource.kind, set())
        if new_parent.kind not in valid_parents:
            raise InvalidParentError(
                f"Invalid parent kind {new_parent.kind} for child kind {resource.kind}"
            )

        # Check for cycles
        if self._would_create_cycle(resource_id, new_parent_id):
            raise InvalidParentError("Parent reference would create a cycle")

        if new_parent_id == resource_id:
            raise InvalidParentError("A resource cannot parent itself")
        if (
            new_parent.intake_id != resource.intake_id
            or new_parent.lifecycle != resource.lifecycle
            or new_parent.environment != resource.environment
            or new_parent.site != resource.site
            or new_parent.tier != resource.tier
        ):
            raise InvalidParentError("New parent must share intake and scope")
        current = self.get_revision(resource_id, expected_revision)
        if current is None:
            raise ResourceNotFoundError("Current resource revision not found")
        self.create_revision(
            resource_id=resource_id,
            payload=current["payload"],
            review_state=current["review_state"],
            authored_by=reparented_by,
            authored_at=reparented_at,
            expected_revision=expected_revision,
            provenance_references=current["provenance_references"],
            parent_id=new_parent_id,
            preserve_parent=False,
            change_reason="REPARENTED",
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _get_resource_entity(self, resource_id: str) -> TargetResource | None:
        """Get resource ORM entity."""
        stmt = select(TargetResource).where(TargetResource.id == resource_id)
        return self._session.execute(stmt).scalar_one_or_none()

    def _get_resource_by_logical_key(
        self,
        intake_id: str,
        logical_key: str,
        lifecycle: str,
        environment: str | None,
        site: str | None = None,
        tier: str | None = None,
    ) -> TargetResource | None:
        """Get resource by logical key within scope."""
        stmt = select(TargetResource).where(
            TargetResource.intake_id == intake_id,
            TargetResource.logical_key == logical_key,
            TargetResource.lifecycle == lifecycle,
        )
        if environment is not None:
            stmt = stmt.where(TargetResource.environment == environment)
        else:
            stmt = stmt.where(TargetResource.environment.is_(None))
        if site is not None:
            stmt = stmt.where(TargetResource.site == site)
        else:
            stmt = stmt.where(TargetResource.site.is_(None))
        if tier is not None:
            stmt = stmt.where(TargetResource.tier == tier)
        else:
            stmt = stmt.where(TargetResource.tier.is_(None))
        return self._session.execute(stmt).scalar_one_or_none()

    def _would_create_cycle(self, resource_id: str, parent_id: str) -> bool:
        """Check if setting parent would create a cycle."""
        visited = {resource_id}
        current = parent_id

        while current is not None:
            if current in visited:
                return True
            visited.add(current)
            parent = self._get_resource_entity(current)
            current = str(parent.parent_id) if parent and parent.parent_id else None

        return False

    @staticmethod
    def _resource_to_dict(resource: TargetResource) -> dict[str, Any]:
        """Convert resource to dict."""
        return {
            "id": str(resource.id),
            "intake_id": str(resource.intake_id),
            "logical_key": resource.logical_key,
            "kind": resource.kind,
            "scope_key": resource.scope_key,
            "lifecycle": resource.lifecycle,
            "environment": resource.environment,
            "site": resource.site,
            "tier": resource.tier,
            "parent_id": str(resource.parent_id) if resource.parent_id else None,
            "current_revision_id": (
                str(resource.current_revision_id)
                if resource.current_revision_id
                else None
            ),
            "revision_number": resource.revision_number,
            "row_version": resource.row_version,
            "resource_state": resource.resource_state,
            "successor_id": str(resource.successor_id) if resource.successor_id else None,
            "created_at": resource.created_at,
            "updated_at": resource.updated_at,
            "created_by": resource.created_by,
        }

    @staticmethod
    def _revision_to_dict(revision: TargetResourceRevision) -> dict[str, Any]:
        """Convert revision to dict."""
        return {
            "id": str(revision.id),
            "resource_id": str(revision.resource_id),
            "revision_number": revision.revision_number,
            "payload": revision.payload,
            "review_state": revision.review_state,
            "parent_id": str(revision.parent_id) if revision.parent_id else None,
            "resource_state": revision.resource_state,
            "change_reason": revision.change_reason,
            "provenance_references": revision.provenance_references,
            "authored_at": revision.authored_at,
            "authored_by": revision.authored_by,
        }

    @staticmethod
    def _link_to_dict(link: TopologyResourceLink) -> dict[str, Any]:
        return {
            "id": str(link.id),
            "intake_id": str(link.intake_id),
            "relationship_type": link.relationship_type,
            "source_resource_id": str(link.source_resource_id),
            "target_resource_id": str(link.target_resource_id),
            "current_revision_id": str(link.current_revision_id) if link.current_revision_id else None,
            "revision_number": link.revision_number,
            "row_version": link.row_version,
            "link_state": link.link_state,
        }

    @staticmethod
    def _link_revision_to_dict(
        revision: TopologyResourceLinkRevision,
    ) -> dict[str, Any]:
        return {
            "id": str(revision.id),
            "link_id": str(revision.link_id),
            "revision_number": revision.revision_number,
            "review_state": revision.review_state,
            "provenance_references": revision.provenance_references or [],
            "authored_at": revision.authored_at,
            "authored_by": revision.authored_by,
        }
