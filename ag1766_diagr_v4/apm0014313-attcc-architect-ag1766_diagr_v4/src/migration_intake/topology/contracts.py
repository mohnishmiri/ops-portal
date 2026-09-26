"""Strict, pure contracts for canonical topology inputs and results.

This module is deliberately independent of SQLAlchemy, FastAPI, storage and
the legacy v2 intake serializer. It defines the v3 topology boundary used by
later projection, rendering and orchestration slices.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from types import MappingProxyType
from typing import Any

SNAPSHOT_SCHEMA_VERSION = "3.0.0"
SUPPORTED_TOPOLOGY_SNAPSHOT_VERSIONS = frozenset({SNAPSHOT_SCHEMA_VERSION})
SHA256_HEX_LENGTH = 64


class TopologyContractError(ValueError):
    """Base error for invalid topology contract data."""


class DuplicateJsonKeyError(TopologyContractError):
    """JSON contains a duplicate object key."""


class NonFiniteNumberError(TopologyContractError):
    """JSON contains NaN or infinity."""


class UnknownFieldError(TopologyContractError):
    """A contract object contains an undeclared field."""


class MissingFieldError(TopologyContractError):
    """A required contract field is absent."""


class UnsupportedTopologySchemaError(TopologyContractError):
    """The topology snapshot schema is not supported for authoritative use."""


class NonCanonicalJsonError(TopologyContractError):
    """The supplied JSON bytes are valid but not canonical."""


class HashMismatchError(TopologyContractError):
    """The supplied content does not match its expected SHA-256 hash."""


class TopologyAuthority(StrEnum):
    """Authority class of a topology result."""

    LEGACY_UNPINNED = "LEGACY_UNPINNED"
    DRAFT_PREVIEW = "DRAFT_PREVIEW"
    OFFICIAL_SNAPSHOT = "OFFICIAL_SNAPSHOT"


class RenderCapability(StrEnum):
    """Governed mutation capability selected for a run."""

    LABEL_ONLY = "LABEL_ONLY"
    STRUCTURAL = "STRUCTURAL"


class GenerationMode(StrEnum):
    """Input capture mode for a topology run."""

    OFFICIAL_SNAPSHOT = "OFFICIAL_SNAPSHOT"
    DRAFT_PREVIEW = "DRAFT_PREVIEW"


class RunPhase(StrEnum):
    """Durable orchestration phase."""

    PENDING = "PENDING"
    CAPTURING = "CAPTURING"
    RENDERING = "RENDERING"
    STORING = "STORING"
    VERIFYING = "VERIFYING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class ReadinessStatus(StrEnum):
    """Readiness result vocabulary."""

    READY = "READY"
    NOT_READY = "NOT_READY"
    BLOCKED = "BLOCKED"


class TopologyResultStatus(StrEnum):
    """Shared technical result status consumed by report and persistence."""

    FAILED = "FAILED"
    READY_FOR_REVIEW = "READY_FOR_REVIEW"
    GENERATED_WITH_GAPS = "GENERATED_WITH_GAPS"


class TopologyIssueSeverity(StrEnum):
    """Stable issue severity for contract and render results."""

    BLOCKER = "BLOCKER"
    WARNING = "WARNING"
    INFO = "INFO"


def _reject_constant(value: str) -> Any:
    raise NonFiniteNumberError(f"Non-finite JSON number is not allowed: {value}")


def _object_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise DuplicateJsonKeyError(f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def _deep_freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({key: _deep_freeze(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_deep_freeze(item) for item in value)
    return value


def _deep_thaw(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _deep_thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_deep_thaw(item) for item in value]
    return value


def _validate_json_values(value: Any, path: str = "$") -> None:
    if isinstance(value, float) and not math.isfinite(value):
        raise NonFiniteNumberError(f"Non-finite number at {path}")
    if isinstance(value, Mapping):
        for key, item in value.items():
            _validate_json_values(item, f"{path}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _validate_json_values(item, f"{path}[{index}]")


def _require_object(value: Any, path: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TopologyContractError(f"{path} must be an object")
    return value


def _check_object(
    value: Any,
    path: str,
    allowed: frozenset[str],
    required: frozenset[str],
) -> Mapping[str, Any]:
    obj = _require_object(value, path)
    unknown = set(obj) - allowed
    if unknown:
        raise UnknownFieldError(f"Unknown field(s) at {path}: {sorted(unknown)}")
    missing = required - set(obj)
    if missing:
        raise MissingFieldError(f"Missing field(s) at {path}: {sorted(missing)}")
    return obj


def _check_string(value: Any, path: str, *, allow_empty: bool = False) -> None:
    if not isinstance(value, str) or (not allow_empty and not value):
        raise TopologyContractError(f"{path} must be a non-empty string")


def _check_string_list(value: Any, path: str) -> None:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise TopologyContractError(f"{path} must be a list of strings")


def _check_snapshot_shape(document: Mapping[str, Any]) -> None:
    top_allowed = frozenset(
        {
            "schema_version",
            "application",
            "catalog",
            "intake",
            "answers",
            "interface_register",
            "resources",
            "relationships",
            "wave_util_rows",
            "permitted_gaps",
        }
    )
    top = _check_object(
        document,
        "$",
        top_allowed,
        frozenset(top_allowed),
    )
    if top["schema_version"] != SNAPSHOT_SCHEMA_VERSION:
        raise UnsupportedTopologySchemaError(
            f"Unsupported topology snapshot schema: {top['schema_version']}"
        )

    application = _check_object(
        top["application"],
        "$.application",
        frozenset({"id", "name", "acronym", "identifiers"}),
        frozenset({"id", "name", "acronym", "identifiers"}),
    )
    for field in ("id", "name", "acronym"):
        _check_string(application[field], f"$.application.{field}")
    if not isinstance(application["identifiers"], list):
        raise TopologyContractError("$.application.identifiers must be a list")
    for index, identifier in enumerate(application["identifiers"]):
        item = _check_object(
            identifier,
            f"$.application.identifiers[{index}]",
            frozenset({"namespace", "raw_value", "normalized_value", "is_primary"}),
            frozenset({"namespace", "raw_value", "normalized_value", "is_primary"}),
        )
        _check_string(item["namespace"], f"$.application.identifiers[{index}].namespace")
        _check_string(item["raw_value"], f"$.application.identifiers[{index}].raw_value")
        _check_string(
            item["normalized_value"],
            f"$.application.identifiers[{index}].normalized_value",
        )
        if not isinstance(item["is_primary"], bool):
            raise TopologyContractError("identifier is_primary must be boolean")

    catalog = _check_object(
        top["catalog"],
        "$.catalog",
        frozenset({"id", "version", "source_sha256", "catalog_hash", "compiler_version"}),
        frozenset({"id", "version", "source_sha256", "catalog_hash", "compiler_version"}),
    )
    for field in ("id", "version", "source_sha256", "catalog_hash", "compiler_version"):
        _check_string(catalog[field], f"$.catalog.{field}")

    intake = _check_object(
        top["intake"],
        "$.intake",
        frozenset({"id", "state", "frozen_at", "frozen_by", "row_version", "content_epoch"}),
        frozenset({"id", "state", "frozen_at", "frozen_by", "row_version", "content_epoch"}),
    )
    for field in ("id", "state", "frozen_at", "frozen_by"):
        _check_string(intake[field], f"$.intake.{field}")
    for field in ("row_version", "content_epoch"):
        if not isinstance(intake[field], int) or isinstance(intake[field], bool):
            raise TopologyContractError(f"$.intake.{field} must be an integer")

    interface_register = _check_object(
        top["interface_register"],
        "$.interface_register",
        frozenset({"interface_epoch", "rows"}),
        frozenset({"interface_epoch", "rows"}),
    )
    if not isinstance(interface_register["interface_epoch"], int):
        raise TopologyContractError("$.interface_register.interface_epoch must be an integer")
    _validate_collection_shape(interface_register["rows"], "interface_register.rows")
    _validate_collection_shape(top["answers"], "answers")
    _validate_collection_shape(top["resources"], "resources")
    _validate_collection_shape(top["relationships"], "relationships")
    _validate_collection_shape(top["wave_util_rows"], "wave_util_rows")
    _validate_collection_shape(top["permitted_gaps"], "permitted_gaps")


def _validate_collection_shape(value: Any, name: str) -> None:
    if not isinstance(value, list):
        raise TopologyContractError(f"$.{name} must be a list")
    if name == "permitted_gaps":
        for index, gap in enumerate(value):
            item = _check_object(
                gap,
                f"$.permitted_gaps[{index}]",
                frozenset({"code", "subject", "owner", "policy"}),
                frozenset({"code", "subject", "owner", "policy"}),
            )
            for field in ("code", "subject", "owner", "policy"):
                _check_string(item[field], f"$.permitted_gaps[{index}].{field}")


def parse_canonical_json(canonical_json: str) -> Mapping[str, Any]:
    """Parse strict JSON with duplicate-key and non-finite-number rejection."""
    try:
        parsed = json.loads(
            canonical_json,
            object_pairs_hook=_object_pairs,
            parse_constant=_reject_constant,
        )
    except json.JSONDecodeError as exc:
        raise TopologyContractError(f"Invalid canonical JSON: {exc}") from exc
    _validate_json_values(parsed)
    if not isinstance(parsed, Mapping):
        raise TopologyContractError("Canonical topology JSON must be an object")
    return parsed


def canonical_json_bytes(document: Mapping[str, Any]) -> bytes:
    """Serialize a validated JSON document to canonical UTF-8 bytes."""
    _validate_json_values(document)
    try:
        text = json.dumps(
            _deep_thaw(document),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise TopologyContractError(f"Document is not canonical JSON data: {exc}") from exc
    return text.encode("utf-8")


def sha256_hex(content: bytes) -> str:
    """Hash exact canonical bytes."""
    return hashlib.sha256(content).hexdigest()


@dataclass(frozen=True, slots=True)
class CanonicalSnapshotContract:
    """Validated, deeply immutable v3 topology snapshot."""

    document: Mapping[str, Any]
    canonical_json: str
    sha256_hex: str


def serialize_snapshot_document(document: Mapping[str, Any]) -> CanonicalSnapshotContract:
    """Validate and serialize a new v3 snapshot document."""
    _check_snapshot_shape(document)
    frozen = _deep_freeze(document)
    content = canonical_json_bytes(frozen)
    return CanonicalSnapshotContract(
        document=frozen,
        canonical_json=content.decode("utf-8"),
        sha256_hex=sha256_hex(content),
    )


def load_snapshot_document(
    canonical_json: str,
    expected_hash: str,
) -> CanonicalSnapshotContract:
    """Load exact stored bytes; reject tampering, legacy schema and reordering."""
    actual_hash = sha256_hex(canonical_json.encode("utf-8"))
    if actual_hash != expected_hash:
        raise HashMismatchError(
            f"Snapshot hash mismatch: expected {expected_hash}, got {actual_hash}"
        )
    parsed = parse_canonical_json(canonical_json)
    contract = serialize_snapshot_document(parsed)
    if contract.canonical_json != canonical_json:
        raise NonCanonicalJsonError("Stored snapshot bytes are not canonical")
    return contract


@dataclass(frozen=True, slots=True)
class TopologyInputIdentity:
    """Semantic input identity; operational IDs and timestamps are excluded."""

    mode: GenerationMode
    capability: RenderCapability
    projection_hash: str
    selection_hash: str
    base_hash: str
    compatibility_key: str
    profile_hash: str
    catalog_hash: str
    generator_version: str
    parser_policy_hash: str
    layout_policy_hash: str
    result_policy_hash: str
    contexts: tuple[tuple[str, str], ...]

    def semantic_document(self) -> dict[str, Any]:
        return {
            "mode": self.mode.value,
            "capability": self.capability.value,
            "projection_hash": self.projection_hash,
            "selection_hash": self.selection_hash,
            "base_hash": self.base_hash,
            "compatibility_key": self.compatibility_key,
            "profile_hash": self.profile_hash,
            "catalog_hash": self.catalog_hash,
            "generator_version": self.generator_version,
            "parser_policy_hash": self.parser_policy_hash,
            "layout_policy_hash": self.layout_policy_hash,
            "result_policy_hash": self.result_policy_hash,
            "contexts": [
                {"environment": environment, "site_id": site_id}
                for environment, site_id in sorted(self.contexts)
            ],
        }

    @property
    def input_hash(self) -> str:
        return sha256_hex(canonical_json_bytes(self.semantic_document()))


def normalize_timestamp(value: datetime) -> str:
    """Normalize an aware timestamp to canonical UTC form."""
    if value.tzinfo is None:
        raise TopologyContractError("Naive datetime is not allowed")
    utc_value = value.astimezone(UTC)
    return utc_value.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
