"""
Canonical data transfer objects for the application layer — G1.

DTOs are immutable containers for data crossing boundaries.
They contain no business logic.

All IDs are string-typed for simpler HTTP serialization. The service layer
resolves and validates UUIDs internally.

Browser forms never submit actor IDs, actor types, roles, or audit fields.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ActorContext:
    """
    Context for the actor performing an operation.

    This is constructed by the web adapter from authenticated/configured
    sources. Actor IDs and role codes submitted in browser forms are ignored.

    Attributes:
        actor_id: Unique identifier for the actor (UUID string)
        actor_type: Type of actor ("CONFIGURED", "OIDC_USER", "SYSTEM")
        display_name: Human-readable name for audit/UI
        role_codes: Immutable set of capability codes
        request_correlation_id: Correlation ID for request tracing
        external_subject: Optional external identity (e.g., OIDC subject)
    """

    actor_id: str
    actor_type: str = "CONFIGURED"
    display_name: str = ""
    role_codes: frozenset[str] = frozenset()
    request_correlation_id: str = ""
    external_subject: str | None = None

    def has_capability(self, capability: str) -> bool:
        """Check if the actor has a specific capability."""
        return capability in self.role_codes

    def has_any_capability(self, *capabilities: str) -> bool:
        """Check if the actor has any of the specified capabilities."""
        return bool(self.role_codes & set(capabilities))

    def has_all_capabilities(self, *capabilities: str) -> bool:
        """Check if the actor has all of the specified capabilities."""
        return set(capabilities) <= self.role_codes


@dataclass(frozen=True, slots=True)
class StoredContent:
    """
    Result of storing content in the evidence store.

    Attributes:
        storage_key: Key to retrieve the content
        content_hash: Hash of the content for integrity verification
        size_bytes: Size of the stored content
    """

    storage_key: str
    content_hash: str
    size_bytes: int


@dataclass(frozen=True, slots=True)
class WorkbookRequest:
    """
    Request to process a workbook.

    Attributes:
        storage_key: Key to the stored workbook file
        application_id: Target application ID
        intake_id: Target intake ID
        expected_contract_version: Expected workbook contract version
    """

    storage_key: str
    application_id: str
    intake_id: str
    expected_contract_version: str


@dataclass(frozen=True, slots=True)
class MappingRequest:
    """
    Request to map a text fragment to catalog values.

    Attributes:
        fragment: Text fragment to map
        control_code: Target control code
        context: Additional context for mapping
    """

    fragment: str
    control_code: str
    context: str | None = None
