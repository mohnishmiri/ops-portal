"""Pure multi-context topology selection and relationship contracts."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

from migration_intake.topology.contracts import (
    TopologyContractError,
    canonical_json_bytes,
    sha256_hex,
)


class ScopeState(str, Enum):
    """Whether a scope dimension is known, global or explicitly unknown."""

    KNOWN = "KNOWN"
    GLOBAL = "GLOBAL"
    UNKNOWN = "UNKNOWN"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class ResourceLifecycle(str, Enum):
    """Lifecycle of a fact/resource in the topology graph."""

    SOURCE = "SOURCE"
    TARGET = "TARGET"


class RelationshipType(str, Enum):
    """Typed graph relationships; connectivity is never inferred."""

    CONTAINS = "CONTAINS"
    DR_PAIR = "DR_PAIR"
    COMPUTE_USES_SECURITY_GROUP = "COMPUTE_USES_SECURITY_GROUP"
    ENI_ATTACHED_TO_COMPUTE = "ENI_ATTACHED_TO_COMPUTE"


class ScopeContractError(TopologyContractError):
    """Scope or graph contract violation."""


@dataclass(frozen=True, slots=True, order=True)
class ContextKey:
    """One explicit environment/site partition."""

    environment: str
    site_id: str

    def __post_init__(self) -> None:
        if not self.environment or not self.site_id:
            raise ScopeContractError("Context environment and site_id are required")

    def as_dict(self) -> dict[str, str]:
        return {"environment": self.environment, "site_id": self.site_id}


@dataclass(frozen=True, slots=True)
class ScopeSelection:
    """Explicit set of contexts rendered together in one official document."""

    application_id: str
    intake_id: str
    contexts: tuple[ContextKey, ...]
    view_variant: str

    def __post_init__(self) -> None:
        if not self.application_id or not self.intake_id or not self.view_variant:
            raise ScopeContractError("Selection identity and view_variant are required")
        if not self.contexts:
            raise ScopeContractError("At least one context must be selected")
        if len(set(self.contexts)) != len(self.contexts):
            raise ScopeContractError("Duplicate context selection is not allowed")

    @property
    def ordered_contexts(self) -> tuple[ContextKey, ...]:
        return tuple(sorted(self.contexts))

    def as_dict(self) -> dict[str, Any]:
        return {
            "application_id": self.application_id,
            "intake_id": self.intake_id,
            "contexts": [context.as_dict() for context in self.ordered_contexts],
            "view_variant": self.view_variant,
        }

    @property
    def selection_hash(self) -> str:
        return sha256_hex(canonical_json_bytes(self.as_dict()))

    def contains(self, context: ContextKey) -> bool:
        return context in self.contexts


@dataclass(frozen=True, slots=True)
class ScopedResourceRef:
    """Canonical resource identity used by graph relationships."""

    resource_id: str
    logical_key: str
    kind: str
    lifecycle: ResourceLifecycle
    context: ContextKey | None = None
    global_scope: bool = False

    def __post_init__(self) -> None:
        if not self.resource_id or not self.logical_key or not self.kind:
            raise ScopeContractError("Resource identity fields are required")
        if self.global_scope and self.context is not None:
            raise ScopeContractError("Global resources cannot also have a context")
        if not self.global_scope and self.context is None:
            raise ScopeContractError("Non-global resources require a context")

    @property
    def scope_key(self) -> str:
        scope = {
            "lifecycle": self.lifecycle.value,
            "global": self.global_scope,
            "context": self.context.as_dict() if self.context else None,
        }
        return sha256_hex(canonical_json_bytes(scope))


def resource_scope_key(
    *,
    lifecycle: str,
    environment: str | None,
    site: str | None,
    tier: str | None = None,
) -> str:
    """Hash a resource scope, preserving omitted dimensions as UNKNOWN.

    Persistence callers may not yet know every scope dimension. UNKNOWN is an
    explicit state and never matches a concrete context during projection.
    """
    if lifecycle not in {item.value for item in ResourceLifecycle}:
        raise ScopeContractError(f"Unknown resource lifecycle: {lifecycle}")
    scope = {
        "lifecycle": lifecycle,
        "environment": {
            "state": ScopeState.KNOWN.value if environment is not None else ScopeState.UNKNOWN.value,
            "value": environment,
        },
        "site": {
            "state": ScopeState.KNOWN.value if site is not None else ScopeState.UNKNOWN.value,
            "value": site,
        },
        "tier": {
            "state": ScopeState.KNOWN.value if tier is not None else ScopeState.UNKNOWN.value,
            "value": tier,
        },
    }
    return sha256_hex(canonical_json_bytes(scope))


@dataclass(frozen=True, slots=True)
class TopologyRelationship:
    """Reviewed relationship between two canonical resources."""

    relationship_id: str
    relationship_type: RelationshipType
    source_resource_id: str
    target_resource_id: str
    reviewed: bool = False


RELATIONSHIP_RULES: dict[RelationshipType, tuple[frozenset[str], frozenset[str]]] = {
    RelationshipType.CONTAINS: (
        frozenset({"PLACEMENT", "ACCOUNT", "VPC", "SUBNET", "COMPUTE", "ENI", "DATABASE"}),
        frozenset({"ACCOUNT", "VPC", "SUBNET", "SECURITY_GROUP", "COMPUTE", "ENI", "DATABASE"}),
    ),
    RelationshipType.DR_PAIR: (frozenset({"PLACEMENT"}), frozenset({"PLACEMENT"})),
    RelationshipType.COMPUTE_USES_SECURITY_GROUP: (frozenset({"COMPUTE"}), frozenset({"SECURITY_GROUP"})),
    RelationshipType.ENI_ATTACHED_TO_COMPUTE: (frozenset({"ENI"}), frozenset({"COMPUTE"})),
}


@dataclass(frozen=True, slots=True)
class TopologyGraph:
    """Validated multi-context graph for downstream projection/rendering."""

    selection: ScopeSelection
    resources: tuple[ScopedResourceRef, ...]
    relationships: tuple[TopologyRelationship, ...]

    def __post_init__(self) -> None:
        resource_ids = [resource.resource_id for resource in self.resources]
        if len(set(resource_ids)) != len(resource_ids):
            raise ScopeContractError("Resource IDs must be unique")
        resources = {resource.resource_id: resource for resource in self.resources}
        for resource in self.resources:
            if resource.lifecycle == ResourceLifecycle.TARGET and not resource.global_scope:
                if not self.selection.contains(resource.context):  # type: ignore[arg-type]
                    raise ScopeContractError(
                        f"Target resource {resource.resource_id} is outside selection"
                    )
        relationship_ids: set[str] = set()
        for relation in self.relationships:
            if relation.relationship_id in relationship_ids:
                raise ScopeContractError("Relationship IDs must be unique")
            relationship_ids.add(relation.relationship_id)
            if not relation.reviewed:
                raise ScopeContractError("Unreviewed relationships cannot enter the graph")
            source = resources.get(relation.source_resource_id)
            target = resources.get(relation.target_resource_id)
            if source is None or target is None:
                raise ScopeContractError("Relationship endpoints must exist")
            source_kinds, target_kinds = RELATIONSHIP_RULES[relation.relationship_type]
            if source.kind not in source_kinds or target.kind not in target_kinds:
                raise ScopeContractError(
                    f"Invalid {relation.relationship_type.value} endpoint kinds"
                )
            if relation.relationship_type == RelationshipType.CONTAINS:
                if source.context != target.context or source.global_scope != target.global_scope:
                    raise ScopeContractError("Containment cannot cross context boundaries")
            elif not (
                source.global_scope
                or target.global_scope
                or source.context == target.context
                or relation.relationship_type == RelationshipType.DR_PAIR
            ):
                raise ScopeContractError("Cross-context relationship is not permitted")

    @property
    def graph_hash(self) -> str:
        document = {
            "selection": self.selection.as_dict(),
            "resources": [
                {
                    "resource_id": resource.resource_id,
                    "logical_key": resource.logical_key,
                    "kind": resource.kind,
                    "lifecycle": resource.lifecycle.value,
                    "scope_key": resource.scope_key,
                }
                for resource in sorted(self.resources, key=lambda item: item.resource_id)
            ],
            "relationships": [
                {
                    "relationship_id": relation.relationship_id,
                    "type": relation.relationship_type.value,
                    "source": relation.source_resource_id,
                    "target": relation.target_resource_id,
                }
                for relation in sorted(
                    self.relationships, key=lambda item: item.relationship_id
                )
            ],
        }
        return sha256_hex(canonical_json_bytes(document))
