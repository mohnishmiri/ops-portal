"""
Topology domain types — T01.

Domain value objects and enumerations for topology diagram generation.
These types define the vocabulary for generation status, approval states,
and readiness results.

Design rules:
- Pure domain types with no persistence or web dependencies
- Immutable dataclasses for value objects
- String enums for status codes (compatible with JSON serialization)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class GenerationStatus(str, Enum):
    """
    Lifecycle status of a topology generation run.

    PENDING: Run created but not yet started
    RUNNING: Generation in progress
    SUCCESS: Generation completed successfully
    FAILED: Generation failed with errors
    READY_FOR_REVIEW: Generated with no blocking issues
    GENERATED_WITH_GAPS: Generated but has gaps requiring review
    """

    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    READY_FOR_REVIEW = "READY_FOR_REVIEW"
    GENERATED_WITH_GAPS = "GENERATED_WITH_GAPS"


class ApprovalStatus(str, Enum):
    """
    Approval status of a generated topology.

    PENDING: Awaiting architect review
    APPROVED: Architect approved the generated topology
    REJECTED: Architect rejected the generated topology
    SUPERSEDED: A newer generation run supersedes this one
    """

    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"


class ArtifactType(str, Enum):
    """
    Type of generated artifact.

    DIAGRAM: The filled draw.io diagram
    GAP_REPORT: HTML gap report documenting issues
    REPORT_JSON: Machine-readable report data
    """

    DIAGRAM = "DIAGRAM"
    GAP_REPORT = "GAP_REPORT"
    REPORT_JSON = "REPORT_JSON"


@dataclass(frozen=True)
class TopologyReadinessIssue:
    """A single issue blocking or warning topology generation."""

    code: str
    severity: str  # "BLOCKER", "WARNING", "INFO"
    message: str
    related_question: str | None = None
    related_slot: str | None = None


@dataclass(frozen=True)
class TopologyReadinessResult:
    """
    Result of checking topology generation readiness.

    Attributes:
        is_ready: True if generation can proceed
        blockers: Issues that prevent generation
        warnings: Issues that allow generation but require review
        permitted_gaps: Explicitly permitted missing values
        snapshot_id: The snapshot that was checked
        base_artifact_id: The base diagram that was checked (if any)
    """

    is_ready: bool
    blockers: list[TopologyReadinessIssue] = field(default_factory=list)
    warnings: list[TopologyReadinessIssue] = field(default_factory=list)
    permitted_gaps: list[str] = field(default_factory=list)
    snapshot_id: str | None = None
    base_artifact_id: str | None = None


@dataclass(frozen=True)
class TopologyFact:
    """
    A single typed, scoped fact for topology rendering.

    Derived from the canonical snapshot via the adapter.
    """

    path: str  # Canonical fact path, e.g., "app.acronym"
    value: str | None  # Resolved value or None if missing
    data_type: str  # Type hint: "string", "identifier", "cidr", etc.
    scope: dict[str, str | None] = field(default_factory=dict)
    provenance: str | None = None  # Reference to source evidence


@dataclass(frozen=True)
class RenderToken:
    """
    A token for diagram label rendering.

    Maps a slot name to its resolved value and formatting.
    """

    slot_name: str
    value: str
    placeholder: str | None = None  # Fallback if value is missing
    is_missing: bool = False
    is_conflict: bool = False
    issue_id: str | None = None


@dataclass
class TopologyFactSet:
    """
    Complete set of facts and tokens for topology generation.

    This is the output of the snapshot-to-topology adapter.
    """

    facts: list[TopologyFact] = field(default_factory=list)
    tokens: list[RenderToken] = field(default_factory=list)
    issues: list[TopologyReadinessIssue] = field(default_factory=list)
    application_id: str | None = None
    snapshot_id: str | None = None
    snapshot_sha256: str | None = None
