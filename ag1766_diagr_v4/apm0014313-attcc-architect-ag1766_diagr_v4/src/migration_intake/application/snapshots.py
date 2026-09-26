"""
Canonical serializer for intake snapshots — S01.

Implements a pure service independent of SQLAlchemy/FastAPI that produces
deterministic, canonical JSON for frozen intakes.

Design rules:
- UTF-8 JSON encoding with sorted object keys
- Stable list ordering by documented keys
- Normalized UTC timestamps (ISO 8601)
- Canonical decimals/units
- Explicit null/unknown distinctions
- Schema version included
- No volatile request/runtime fields

Payload includes:
- Application identity
- Pinned catalog identity/hash
- Intake identity/state
- Applicable canonical answers with revision/provenance references
- Canonical WaveUtil rows/revisions
- Unresolved permitted gaps where policy allows
- Requested output mappings

Payload excludes:
- Candidate proposals not accepted
- Raw evidence bytes
- Secrets
- Absolute paths
- Mutable URLs
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

# ─────────────────────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────────────────────

SCHEMA_VERSION = "2.0.0"

# Supported schema versions for reading
SUPPORTED_SCHEMA_VERSIONS = {"1.0.0", "2.0.0"}


# ─────────────────────────────────────────────────────────────────────────────
# Data classes for canonical payload
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class CanonicalIdentifier:
    """A typed application identifier."""

    identifier_type: str  # e.g., CORRELATION, MOTS, ITAP
    value: str
    is_primary: bool = False


@dataclass
class CanonicalAnswer:
    """A canonical answer with revision and provenance references."""

    question_id: str
    question_code: str
    section_code: str
    response_type: str
    value_json: Any
    review_state: str
    revision_number: int
    confirm_state: str = "CONFIRMED"
    response_schema_version: str | None = None
    provenance_references: list[str] = field(default_factory=list)


@dataclass
class CanonicalTargetResource:
    """
    A canonical target resource for topology generation.

    This is a placeholder for P5 implementation. The collection will be
    empty until target-resource persistence is implemented.
    """

    logical_key: str
    kind: str  # PLACEMENT, ACCOUNT, VPC, SUBNET, SECURITY_GROUP, COMPUTE, ENI, DATABASE
    scope: dict[str, str | None] = field(default_factory=dict)  # lifecycle, environment, site, tier
    attributes: dict[str, Any] = field(default_factory=dict)
    review_state: str = "CONFIRMED"
    revision_number: int = 1
    provenance_references: list[str] = field(default_factory=list)


@dataclass
class CanonicalWaveUtilRow:
    """A canonical WaveUtil row with current revision."""

    row_id: str
    server_name: str
    normalized_server_name: str
    environment: str | None
    scope: str | None
    state: str
    revision_number: int
    field_values: dict[str, Any] = field(default_factory=dict)


@dataclass
class CanonicalIntakePayload:
    """The complete canonical payload for a frozen intake.

    Schema v2.0.0 additions:
    - application_identifiers: Typed identifiers (CORRELATION, MOTS, ITAP)
    - target_resources: Scoped resources for topology (empty until P5)
    - catalog_hash: Compiled catalog hash (distinct from source_sha256)
    """

    schema_version: str
    application_id: str
    application_name: str
    catalog_id: str
    catalog_version: str
    catalog_sha256: str  # Source file hash
    catalog_hash: str | None  # Compiled catalog hash (v2.0.0)
    intake_id: str
    intake_state: str
    frozen_at: str  # ISO 8601 UTC timestamp
    frozen_by: str
    # v2.0.0: Typed application identifiers
    application_identifiers: list[CanonicalIdentifier] = field(default_factory=list)
    answers: list[CanonicalAnswer] = field(default_factory=list)
    # v2.0.0: Target resources for topology (empty until P5)
    target_resources: list[CanonicalTargetResource] = field(default_factory=list)
    wave_util_rows: list[CanonicalWaveUtilRow] = field(default_factory=list)
    permitted_gaps: list[str] = field(default_factory=list)


# ─────────────────────────────────────────────────────────────────────────────
# Serializer
# ─────────────────────────────────────────────────────────────────────────────


class CanonicalSerializer:
    """
    Pure service for creating deterministic canonical JSON.

    Independent of SQLAlchemy/FastAPI. Takes domain data and produces
    canonical JSON bytes with a stable SHA-256 hash.
    """

    @staticmethod
    def serialize(payload: CanonicalIntakePayload) -> tuple[str, str]:
        """
        Serialize a canonical payload to JSON and compute its hash.

        Returns:
            (canonical_json, sha256_hex) tuple
        """
        # Convert to dict with stable ordering
        payload_dict = CanonicalSerializer._payload_to_dict(payload)

        # Serialize with sorted keys and no extra whitespace
        canonical_json = json.dumps(
            payload_dict,
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
            default=CanonicalSerializer._json_default,
        )

        # Compute SHA-256 of UTF-8 bytes
        sha256_hex = hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()

        return canonical_json, sha256_hex

    @staticmethod
    def _payload_to_dict(payload: CanonicalIntakePayload) -> dict[str, Any]:
        """Convert payload to dict with stable list ordering."""
        return {
            "schema_version": payload.schema_version,
            "application": {
                "id": payload.application_id,
                "name": payload.application_name,
                # v2.0.0: Typed identifiers sorted by (type, value)
                "identifiers": [
                    CanonicalSerializer._identifier_to_dict(i)
                    for i in sorted(
                        payload.application_identifiers,
                        key=lambda x: (x.identifier_type, x.value),
                    )
                ],
            },
            "catalog": {
                "id": payload.catalog_id,
                "version": payload.catalog_version,
                "source_sha256": payload.catalog_sha256,
                # v2.0.0: Compiled catalog hash
                "catalog_hash": payload.catalog_hash,
            },
            "intake": {
                "id": payload.intake_id,
                "state": payload.intake_state,
                "frozen_at": payload.frozen_at,
                "frozen_by": payload.frozen_by,
            },
            # Sort answers by (section_code, question_code) for stability
            "answers": [
                CanonicalSerializer._answer_to_dict(a)
                for a in sorted(
                    payload.answers,
                    key=lambda x: (x.section_code, x.question_code),
                )
            ],
            # v2.0.0: Target resources sorted by (kind, logical_key)
            "target_resources": [
                CanonicalSerializer._target_resource_to_dict(r)
                for r in sorted(
                    payload.target_resources,
                    key=lambda x: (x.kind, x.logical_key),
                )
            ],
            # Sort wave_util_rows by (normalized_server_name, row_id) for stability
            "wave_util_rows": [
                CanonicalSerializer._wave_util_row_to_dict(r)
                for r in sorted(
                    payload.wave_util_rows,
                    key=lambda x: (x.normalized_server_name, x.row_id),
                )
            ],
            # Sort permitted_gaps alphabetically
            "permitted_gaps": sorted(payload.permitted_gaps),
        }

    @staticmethod
    def _identifier_to_dict(identifier: CanonicalIdentifier) -> dict[str, Any]:
        """Convert identifier to dict."""
        return {
            "type": identifier.identifier_type,
            "value": identifier.value,
            "is_primary": identifier.is_primary,
        }

    @staticmethod
    def _answer_to_dict(answer: CanonicalAnswer) -> dict[str, Any]:
        """Convert answer to dict with v2.0.0 fields."""
        return {
            "question_id": answer.question_id,
            "question_code": answer.question_code,
            "section_code": answer.section_code,
            "response_type": answer.response_type,
            "response_schema_version": answer.response_schema_version,
            "value": answer.value_json,
            "confirm_state": answer.confirm_state,
            "review_state": answer.review_state,
            "revision_number": answer.revision_number,
            "provenance_references": sorted(answer.provenance_references),
        }

    @staticmethod
    def _target_resource_to_dict(resource: CanonicalTargetResource) -> dict[str, Any]:
        """Convert target resource to dict."""
        return {
            "logical_key": resource.logical_key,
            "kind": resource.kind,
            "scope": resource.scope,
            "attributes": resource.attributes,
            "review_state": resource.review_state,
            "revision_number": resource.revision_number,
            "provenance_references": sorted(resource.provenance_references),
        }

    @staticmethod
    def _wave_util_row_to_dict(row: CanonicalWaveUtilRow) -> dict[str, Any]:
        """Convert WaveUtil row to dict."""
        return {
            "row_id": row.row_id,
            "server_name": row.server_name,
            "normalized_server_name": row.normalized_server_name,
            "environment": row.environment,
            "scope": row.scope,
            "state": row.state,
            "revision_number": row.revision_number,
            "field_values": row.field_values,
        }

    @staticmethod
    def _json_default(obj: Any) -> Any:
        """Handle non-standard JSON types."""
        if isinstance(obj, datetime):
            # Normalize to UTC ISO 8601
            if obj.tzinfo is None:
                raise ValueError("Naive datetime not allowed; use timezone-aware")
            utc_dt = obj.astimezone(UTC)
            return utc_dt.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
        if isinstance(obj, Decimal):
            # Canonical decimal representation
            return str(obj)
        raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")

    @staticmethod
    def verify_hash(canonical_json: str, expected_hash: str) -> bool:
        """Verify that canonical JSON matches expected hash."""
        actual_hash = hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()
        return actual_hash == expected_hash

    @staticmethod
    def normalize_timestamp(dt: datetime) -> str:
        """Normalize a datetime to canonical UTC ISO 8601 format."""
        if dt.tzinfo is None:
            raise ValueError("Naive datetime not allowed; use timezone-aware")
        utc_dt = dt.astimezone(UTC)
        return utc_dt.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
