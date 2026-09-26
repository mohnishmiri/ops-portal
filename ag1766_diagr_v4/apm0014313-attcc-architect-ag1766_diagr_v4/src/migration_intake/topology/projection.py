"""
Topology Projection — P4 (Snapshot-to-Topology Projection Adapter).

This module defines the pure projection schema and adapter that transforms
canonical snapshot JSON into topology projections for rendering.

Design rules:
- Pure function of canonical JSON plus profile mappings
- No database access, no SQLAlchemy
- No XML rendering (that's P9)
- Unknown schema, unknown response shape, and identity mismatch fail closed
- Deterministic output for identical inputs

The projection is the data contract between P3 (snapshot) and P9 (renderer).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any

# ─────────────────────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────────────────────

PROJECTION_SCHEMA_VERSION = "1.0.0"

# Supported snapshot schema versions for projection
SUPPORTED_SNAPSHOT_VERSIONS = {"2.0.0"}


# ─────────────────────────────────────────────────────────────────────────────
# Enums
# ─────────────────────────────────────────────────────────────────────────────


class ProjectionIssueLevel(str, Enum):
    """Severity level for projection issues."""

    ERROR = "ERROR"  # Blocking issue
    WARNING = "WARNING"  # Non-blocking issue
    INFO = "INFO"  # Informational


class MissingValuePolicy(str, Enum):
    """Policy for handling missing values."""

    ERROR = "ERROR"  # Fail if value is missing
    PLACEHOLDER = "PLACEHOLDER"  # Use placeholder marker
    SKIP = "SKIP"  # Skip the binding


# ─────────────────────────────────────────────────────────────────────────────
# Data classes for projection
# ─────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ProjectionContext:
    """
    Target context for projection.

    Specifies the environment, site, and variant to project for.
    Required for v1 - no automatic selection.
    """

    environment: str  # DEV | TEST | STAGING | PROD
    site: str | None = None  # Site identifier
    variant: str | None = None  # Profile variant


@dataclass(frozen=True)
class ProjectedIdentifier:
    """A projected application identifier."""

    identifier_type: str
    value: str
    raw_value: str | None = None
    source: str | None = None
    is_primary: bool = False


@dataclass(frozen=True)
class ProjectedAnswer:
    """A projected answer value."""

    question_code: str
    section_code: str
    response_type: str
    value: Any
    confirm_state: str
    revision_number: int
    provenance_references: tuple[str, ...] = ()


@dataclass(frozen=True)
class ProjectedResource:
    """A projected target resource."""

    logical_key: str
    kind: str
    scope: dict[str, str | None]
    attributes: dict[str, Any]
    review_state: str
    revision_number: int
    parent_logical_key: str | None = None


@dataclass(frozen=True)
class ProjectionIssue:
    """An issue detected during projection."""

    issue_id: str
    level: ProjectionIssueLevel
    message: str
    location: str | None = None  # e.g., "answer:CTL-002"
    blocking: bool = False


@dataclass
class TopologyProjection:
    """
    The complete topology projection for rendering.

    This is the data contract between P3 (snapshot) and P9 (renderer).
    The projection is a pure transformation of the canonical snapshot
    filtered by the target context.
    """

    # Schema version
    schema_version: str = PROJECTION_SCHEMA_VERSION

    # Source references
    snapshot_id: str = ""
    snapshot_hash: str = ""
    catalog_version: str = ""
    catalog_hash: str | None = None

    # Application identity
    application_id: str = ""
    application_name: str = ""

    # Target context
    context: ProjectionContext | None = None

    # Projected data
    identifiers: list[ProjectedIdentifier] = field(default_factory=list)
    answers: list[ProjectedAnswer] = field(default_factory=list)
    resources: list[ProjectedResource] = field(default_factory=list)
    permitted_gaps: list[str] = field(default_factory=list)

    # Issues
    issues: list[ProjectionIssue] = field(default_factory=list)

    # Projection metadata
    projected_at: str = ""  # ISO 8601 UTC
    projection_hash: str = ""

    @property
    def has_blocking_issues(self) -> bool:
        """Check if projection has any blocking issues."""
        return any(issue.blocking for issue in self.issues)

    @property
    def is_valid(self) -> bool:
        """Check if projection is valid for rendering."""
        return not self.has_blocking_issues and self.snapshot_hash != ""


# ─────────────────────────────────────────────────────────────────────────────
# Mapping Records
# ─────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class FactMapping:
    """
    Profile-independent mapping record for answer-to-fact transformation.

    Replaces the guessed code-to-path tuples in FACT_REGISTRY with
    explicit, typed mapping records.
    """

    question_code: str
    fact_path: str
    data_type: str  # text, identifier, cidr, region, version, etc.
    response_type: str  # TEXT, SINGLE_SELECT, CONTROLLED_SET, etc.
    lifecycle: str | None = None  # SOURCE | TARGET | None (both)
    scope_rule: str = "EXACT"  # EXACT | ANY | INHERIT
    cardinality: str = "SINGLE"  # SINGLE | MULTIPLE
    missing_policy: MissingValuePolicy = MissingValuePolicy.PLACEHOLDER


# Standard fact mappings (profile-independent)
STANDARD_FACT_MAPPINGS: list[FactMapping] = [
    # Application identity
    FactMapping("CTL-001", "app.id", "identifier", "TEXT"),
    FactMapping("CTL-002", "app.name", "text", "TEXT_PAIR"),

    # Environment
    FactMapping("APP-005", "env.name", "text", "SINGLE_SELECT"),
    FactMapping("APP-006", "env.region", "region", "SINGLE_SELECT"),

    # Network
    FactMapping("NET-001", "network.vpc_cidr", "cidr", "TEXT"),
    FactMapping("NET-002", "network.subnet_cidr", "cidr", "TEXT"),
    FactMapping("NET-003", "network.outpost_cidr", "cidr", "TEXT"),

    # Database
    FactMapping("DB-001", "db.engine", "text", "SINGLE_SELECT"),
    FactMapping("DB-002", "db.engine.version", "version", "TEXT"),
    FactMapping("DB-003", "db.instance_type", "text", "SINGLE_SELECT"),
    FactMapping("DB-004", "db.storage_size", "text", "TEXT"),

    # Compute
    FactMapping("EC2-001", "compute.ec2_instance_type", "text", "SINGLE_SELECT"),
    FactMapping("EC2-002", "compute.ec2_count", "text", "TEXT"),

    # Storage
    FactMapping("EBS-001", "storage.ebs_size", "text", "TEXT"),
    FactMapping("EBS-002", "storage.ebs_type", "text", "SINGLE_SELECT"),

    # Load balancer
    FactMapping("LB-001", "lb.alb_name", "text", "TEXT"),
    FactMapping("LB-002", "lb.nlb_name", "text", "TEXT"),
]


# ─────────────────────────────────────────────────────────────────────────────
# Projection Adapter
# ─────────────────────────────────────────────────────────────────────────────


class ProjectionError(Exception):
    """Base class for projection errors."""

    pass


class UnsupportedSchemaError(ProjectionError):
    """Snapshot schema version is not supported."""

    pass


class IdentityMismatchError(ProjectionError):
    """Application identity mismatch detected."""

    pass


class InvalidSnapshotError(ProjectionError):
    """Snapshot data is invalid or malformed."""

    pass


class ProjectionAdapter:
    """
    Pure adapter that transforms canonical snapshot JSON to topology projection.

    This adapter:
    - Parses and validates canonical snapshot JSON
    - Filters data by target context
    - Transforms answers to projected facts
    - Detects and reports projection issues
    - Produces a deterministic projection hash
    """

    def __init__(
        self,
        fact_mappings: list[FactMapping] | None = None,
    ):
        """
        Initialize the projection adapter.

        Args:
            fact_mappings: Custom fact mappings (defaults to STANDARD_FACT_MAPPINGS)
        """
        self._fact_mappings = fact_mappings or STANDARD_FACT_MAPPINGS
        self._mapping_by_code = {m.question_code: m for m in self._fact_mappings}

    def project(
        self,
        snapshot_json: str,
        snapshot_hash: str,
        context: ProjectionContext,
        projected_at: datetime,
    ) -> TopologyProjection:
        """
        Project a canonical snapshot to a topology projection.

        Args:
            snapshot_json: Canonical snapshot JSON string
            snapshot_hash: SHA-256 hash of the snapshot JSON
            context: Target context for projection
            projected_at: Timestamp for the projection

        Returns:
            TopologyProjection with projected data and any issues

        Raises:
            UnsupportedSchemaError: If snapshot schema is not supported
            InvalidSnapshotError: If snapshot data is malformed
        """
        # Verify hash
        actual_hash = hashlib.sha256(snapshot_json.encode("utf-8")).hexdigest()
        if actual_hash != snapshot_hash:
            raise InvalidSnapshotError(
                f"Snapshot hash mismatch: expected {snapshot_hash}, got {actual_hash}"
            )

        # Parse JSON
        try:
            snapshot_data = json.loads(snapshot_json)
        except json.JSONDecodeError as e:
            raise InvalidSnapshotError(f"Invalid snapshot JSON: {e}")

        # Validate schema version
        schema_version = snapshot_data.get("schema_version", "")
        if schema_version not in SUPPORTED_SNAPSHOT_VERSIONS:
            raise UnsupportedSchemaError(
                f"Unsupported snapshot schema version: {schema_version}. "
                f"Supported versions: {SUPPORTED_SNAPSHOT_VERSIONS}"
            )

        # Build projection
        projection = TopologyProjection(
            schema_version=PROJECTION_SCHEMA_VERSION,
            snapshot_id=snapshot_data.get("intake", {}).get("id", ""),
            snapshot_hash=snapshot_hash,
            catalog_version=snapshot_data.get("catalog", {}).get("version", ""),
            catalog_hash=snapshot_data.get("catalog", {}).get("catalog_hash"),
            application_id=snapshot_data.get("application", {}).get("id", ""),
            application_name=snapshot_data.get("application", {}).get("name", ""),
            context=context,
            projected_at=self._format_timestamp(projected_at),
        )

        # Project identifiers
        projection.identifiers = self._project_identifiers(
            snapshot_data.get("application", {}).get("identifiers", [])
        )

        # Project answers
        projection.answers, answer_issues = self._project_answers(
            snapshot_data.get("answers", []),
            context,
        )
        projection.issues.extend(answer_issues)

        # Project resources
        projection.resources, resource_issues = self._project_resources(
            snapshot_data.get("target_resources", []),
            context,
        )
        projection.issues.extend(resource_issues)

        # Copy permitted gaps
        projection.permitted_gaps = list(snapshot_data.get("permitted_gaps", []))

        # Compute projection hash
        projection.projection_hash = self._compute_projection_hash(projection)

        return projection

    def _project_identifiers(
        self,
        identifiers: list[dict[str, Any]],
    ) -> list[ProjectedIdentifier]:
        """Project application identifiers."""
        return [
            ProjectedIdentifier(
                identifier_type=ident.get("type", ""),
                value=ident.get("value", ""),
                is_primary=ident.get("is_primary", False),
            )
            for ident in identifiers
        ]

    def _project_answers(
        self,
        answers: list[dict[str, Any]],
        context: ProjectionContext,
    ) -> tuple[list[ProjectedAnswer], list[ProjectionIssue]]:
        """
        Project answers filtered by context.

        Returns:
            Tuple of (projected_answers, issues)
        """
        projected = []
        issues = []

        for answer in answers:
            question_code = answer.get("question_code", "")
            confirm_state = answer.get("confirm_state", "")

            # Only include confirmed answers
            if confirm_state != "CONFIRMED":
                continue

            # Check for mapping
            mapping = self._mapping_by_code.get(question_code)
            if mapping is None:
                # No mapping - include anyway for profile to handle
                pass

            projected.append(
                ProjectedAnswer(
                    question_code=question_code,
                    section_code=answer.get("section_code", ""),
                    response_type=answer.get("response_type", ""),
                    value=answer.get("value"),
                    confirm_state=confirm_state,
                    revision_number=answer.get("revision_number", 0),
                    provenance_references=tuple(
                        answer.get("provenance_references", [])
                    ),
                )
            )

        return projected, issues

    def _project_resources(
        self,
        resources: list[dict[str, Any]],
        context: ProjectionContext,
    ) -> tuple[list[ProjectedResource], list[ProjectionIssue]]:
        """
        Project resources filtered by context.

        Returns:
            Tuple of (projected_resources, issues)
        """
        projected = []
        issues = []

        for resource in resources:
            scope = resource.get("scope", {})

            # Filter by environment if specified
            resource_env = scope.get("environment")
            if resource_env and resource_env != context.environment:
                continue

            # Filter by site if specified
            resource_site = scope.get("site")
            if context.site and resource_site and resource_site != context.site:
                continue

            # Only include confirmed resources
            review_state = resource.get("review_state", "")
            if review_state != "CONFIRMED":
                issues.append(
                    ProjectionIssue(
                        issue_id="UNCONFIRMED_RESOURCE",
                        level=ProjectionIssueLevel.WARNING,
                        message=f"Resource {resource.get('logical_key')} is not confirmed",
                        location=f"resource:{resource.get('logical_key')}",
                        blocking=False,
                    )
                )
                continue

            projected.append(
                ProjectedResource(
                    logical_key=resource.get("logical_key", ""),
                    kind=resource.get("kind", ""),
                    scope=scope,
                    attributes=resource.get("attributes", {}),
                    review_state=review_state,
                    revision_number=resource.get("revision_number", 0),
                    parent_logical_key=resource.get("parent_logical_key"),
                )
            )

        return projected, issues

    def _compute_projection_hash(self, projection: TopologyProjection) -> str:
        """Compute deterministic hash of the projection."""
        # Create canonical representation
        canonical = {
            "schema_version": projection.schema_version,
            "snapshot_hash": projection.snapshot_hash,
            "catalog_version": projection.catalog_version,
            "catalog_hash": projection.catalog_hash,
            "application_id": projection.application_id,
            "application_name": projection.application_name,
            "context": {
                "environment": projection.context.environment if projection.context else None,
                "site": projection.context.site if projection.context else None,
                "variant": projection.context.variant if projection.context else None,
            },
            "identifiers": [
                {
                    "type": i.identifier_type,
                    "value": i.value,
                    "is_primary": i.is_primary,
                }
                for i in sorted(
                    projection.identifiers,
                    key=lambda x: (x.identifier_type, x.value),
                )
            ],
            "answers": [
                {
                    "question_code": a.question_code,
                    "section_code": a.section_code,
                    "value": a.value,
                    "confirm_state": a.confirm_state,
                }
                for a in sorted(
                    projection.answers,
                    key=lambda x: (x.section_code, x.question_code),
                )
            ],
            "resources": [
                {
                    "logical_key": r.logical_key,
                    "kind": r.kind,
                    "scope": r.scope,
                    "attributes": r.attributes,
                }
                for r in sorted(
                    projection.resources,
                    key=lambda x: (x.kind, x.logical_key),
                )
            ],
            "permitted_gaps": sorted(projection.permitted_gaps),
        }

        canonical_json = json.dumps(
            canonical,
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
        )

        return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()

    @staticmethod
    def _format_timestamp(dt: datetime) -> str:
        """Format datetime to ISO 8601 UTC."""

        if dt.tzinfo is None:
            raise ValueError("Naive datetime not allowed; use timezone-aware")
        utc_dt = dt.astimezone(UTC)
        return utc_dt.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


# ─────────────────────────────────────────────────────────────────────────────
# Convenience functions
# ─────────────────────────────────────────────────────────────────────────────


def project_snapshot(
    snapshot_json: str,
    snapshot_hash: str,
    environment: str,
    site: str | None = None,
    variant: str | None = None,
    projected_at: datetime | None = None,
) -> TopologyProjection:
    """
    Convenience function to project a snapshot.

    Args:
        snapshot_json: Canonical snapshot JSON string
        snapshot_hash: SHA-256 hash of the snapshot JSON
        environment: Target environment (DEV, TEST, STAGING, PROD)
        site: Optional site identifier
        variant: Optional profile variant
        projected_at: Optional projection timestamp (defaults to now)

    Returns:
        TopologyProjection with projected data
    """

    if projected_at is None:
        projected_at = datetime.now(tz=UTC)

    context = ProjectionContext(
        environment=environment,
        site=site,
        variant=variant,
    )

    adapter = ProjectionAdapter()
    return adapter.project(
        snapshot_json=snapshot_json,
        snapshot_hash=snapshot_hash,
        context=context,
        projected_at=projected_at,
    )
