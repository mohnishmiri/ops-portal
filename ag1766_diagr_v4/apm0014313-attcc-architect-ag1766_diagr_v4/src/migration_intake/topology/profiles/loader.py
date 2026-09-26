"""
Profile Loader — P6 Implementation.

Implements profile loading, validation, and compatibility checking
based on the P6 design document.

Design rules:
- Profiles are versioned and content-hashed
- Profile selection is explicit (no automatic selection in v1)
- Component hashes are verified on load
- Compatibility is checked against projection version
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from importlib.resources.abc import Traversable

from packaging.version import InvalidVersion, Version

_REQUIRED_COMPONENTS = frozenset({"slots", "mappings", "markers", "issue_rules", "naming_rules"})
_COMPONENT_FILES = {
    "slots": "slots.json",
    "mappings": "mappings.json",
    "markers": "markers.json",
    "issue_rules": "issue_rules.json",
    "naming_rules": "naming_rules.json",
}


# ─────────────────────────────────────────────────────────────────────────────
# Enums
# ─────────────────────────────────────────────────────────────────────────────


class SlotType(StrEnum):
    """Slot requirement type."""

    MANDATORY = "MANDATORY"
    CONDITIONAL = "CONDITIONAL"
    OPTIONAL = "OPTIONAL"
    REPEATING = "REPEATING"


class UnresolvedPolicy(StrEnum):
    """Policy for unresolved slots."""

    ERROR = "ERROR"
    WARN = "WARN"
    SKIP = "SKIP"


class NameAuthority(StrEnum):
    """Authority level for name composition."""

    PROPOSE = "PROPOSE"
    VALIDATE = "VALIDATE"
    ALLOCATED = "ALLOCATED"


class IssueSeverity(StrEnum):
    """Severity level for profile issues."""

    ERROR = "ERROR"
    WARN = "WARN"
    INFO = "INFO"


# ─────────────────────────────────────────────────────────────────────────────
# Exceptions
# ─────────────────────────────────────────────────────────────────────────────


class ProfileError(Exception):
    """Base class for profile errors."""

    pass


class ProfileNotFoundError(ProfileError):
    """Profile does not exist."""

    pass


class ProfileHashMismatchError(ProfileError):
    """Component or profile hash does not match."""

    pass


class ProfileIncompatibleError(ProfileError):
    """Profile is not compatible with projection."""

    pass


class ProfileValidationError(ProfileError):
    """Profile manifest or component is invalid."""

    pass


# ─────────────────────────────────────────────────────────────────────────────
# Data classes
# ─────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ProfileSlot:
    """A slot definition for diagram filling."""

    slot_id: str
    slot_type: SlotType
    display_name: str
    page_selector: dict[str, Any]
    cell_matcher: dict[str, Any]
    tokens: tuple[str, ...]
    unresolved_policy: UnresolvedPolicy = UnresolvedPolicy.ERROR
    cardinality_min: int = 1
    cardinality_max: int = 1
    validation: dict[str, Any] | None = None


@dataclass(frozen=True)
class ProfileToken:
    """A token binding to projection data."""

    token_id: str
    projection_path: str
    scope: dict[str, str | None]
    cardinality: str = "SINGLE"
    transform: str | None = None
    default_value: str | None = None


@dataclass(frozen=True)
class ProfileMarker:
    """A governed marker pattern."""

    pattern: str
    token: str
    format_spec: str | None = None
    required: bool = False


@dataclass(frozen=True)
class ProfileIssueRule:
    """An issue detection rule."""

    rule_id: str
    condition: str
    severity: IssueSeverity
    message: str
    blocking: bool = False


@dataclass(frozen=True)
class ProfileNamingRule:
    """A name composition rule."""

    rule_id: str
    pattern: str
    tokens: dict[str, str]
    authority: NameAuthority = NameAuthority.PROPOSE
    validation: dict[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class GeneratedRegion:
    """Governed repeated-node/edge mutation region."""

    region_id: str
    page_name: str
    container_cell_id: str
    generated_id_prefix: str
    node_prototype_cell_id: str
    edge_prototype_cell_id: str
    node_selector: str
    edge_selector: str
    row_capacity: int
    page_capacity: int
    overflow_policy: str
    continuation_page_pattern: str | None = None
    generated_cell_id: str | None = None
    label_token: str | None = None
    x: float = 0
    y: float = 0
    width: float = 180
    height: float = 30


@dataclass
class ProfileManifest:
    """Profile manifest with metadata and component references."""

    profile_id: str
    version: str
    display_name: str
    description: str
    variant: str
    target_platform: str

    # Compatibility
    min_projection_version: str
    max_projection_version: str
    required_resource_kinds: list[str]
    optional_resource_kinds: list[str]

    # Component hashes
    component_hashes: dict[str, str]

    # Combined profile hash
    profile_hash: str

    # Metadata
    created_at: str | None = None
    created_by: str | None = None
    approved_at: str | None = None
    approved_by: str | None = None


@dataclass
class Profile:
    """A complete loaded profile."""

    manifest: ProfileManifest
    slots: list[ProfileSlot]
    tokens: list[ProfileToken]
    markers: list[ProfileMarker]
    issue_rules: list[ProfileIssueRule]
    naming_rules: list[ProfileNamingRule]
    generated_regions: list[GeneratedRegion] = field(default_factory=list)

    # Token lookup
    _token_by_id: dict[str, ProfileToken] = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        """Build lookup indexes."""
        self._token_by_id = {t.token_id: t for t in self.tokens}

    def get_token(self, token_id: str) -> ProfileToken | None:
        """Get token by ID."""
        return self._token_by_id.get(token_id)

    @property
    def profile_id(self) -> str:
        """Get profile ID."""
        return self.manifest.profile_id

    @property
    def version(self) -> str:
        """Get profile version."""
        return self.manifest.version

    @property
    def profile_hash(self) -> str:
        """Get profile hash."""
        return self.manifest.profile_hash


@dataclass
class ProfileCompatibilityReport:
    """Compatibility check results."""

    profile_id: str
    profile_version: str
    profile_hash: str

    projection_version: str
    projection_hash: str

    is_compatible: bool

    # Page inventory
    pages_found: list[str] = field(default_factory=list)
    pages_expected: list[str] = field(default_factory=list)
    pages_missing: list[str] = field(default_factory=list)

    # Slot matching
    slots_total: int = 0
    slots_matched: int = 0
    slots_unmatched: int = 0

    # Marker inventory
    markers_total: int = 0
    markers_bound: int = 0
    markers_unbound: int = 0

    # Issues
    blocking_issues: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    # Overall status
    ready_for_render: bool = False
    readiness_reason: str | None = None


# ─────────────────────────────────────────────────────────────────────────────
# Profile Loading
# ─────────────────────────────────────────────────────────────────────────────


def _compute_file_hash(content: bytes) -> str:
    """Compute SHA-256 hash of file content."""
    return hashlib.sha256(content).hexdigest()


def _compute_profile_hash(
    component_hashes: dict[str, str], manifest_data: dict[str, Any] | None = None
) -> str:
    """Compute a canonical profile identity including manifest semantics."""
    if manifest_data is None:
        payload: Any = {"components": dict(sorted(component_hashes.items()))}
    else:
        payload = dict(manifest_data)
        payload.pop("profile_sha256", None)
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
            "utf-8"
        )
    ).hexdigest()


def _parse_generated_region(data: dict[str, Any]) -> GeneratedRegion:
    required = {
        "region_id",
        "page_name",
        "container_cell_id",
        "generated_id_prefix",
        "node_prototype_cell_id",
        "edge_prototype_cell_id",
        "node_selector",
        "edge_selector",
        "row_capacity",
        "page_capacity",
        "overflow_policy",
    }
    optional = {
        "continuation_page_pattern",
        "generated_cell_id",
        "label_token",
        "x",
        "y",
        "width",
        "height",
    }
    unknown = set(data) - required - optional
    missing = required - set(data)
    if unknown or missing:
        raise ProfileValidationError(
            f"Generated region fields mismatch: missing={sorted(missing)} unknown={sorted(unknown)}"
        )
    if data["overflow_policy"] not in {"BLOCK", "CONTINUATION_PAGE"}:
        raise ProfileValidationError("Generated region overflow_policy is invalid")
    for field_name in ("row_capacity", "page_capacity"):
        if not isinstance(data[field_name], int) or data[field_name] < 1:
            raise ProfileValidationError(f"Generated region {field_name} must be positive")
    if data["overflow_policy"] == "CONTINUATION_PAGE" and not data.get("continuation_page_pattern"):
        raise ProfileValidationError("Continuation pages require a page-name pattern")
    return GeneratedRegion(**data)


def _parse_slot(slot_data: dict[str, Any]) -> ProfileSlot:
    """Parse a slot definition from JSON."""
    return ProfileSlot(
        slot_id=slot_data["slot_id"],
        slot_type=SlotType(slot_data["slot_type"]),
        display_name=slot_data.get("display_name", slot_data["slot_id"]),
        page_selector=slot_data.get("page_selector", {}),
        cell_matcher=slot_data.get("cell_matcher", {}),
        tokens=tuple(slot_data.get("tokens", [])),
        unresolved_policy=UnresolvedPolicy(slot_data.get("unresolved_policy", "ERROR")),
        cardinality_min=slot_data.get("cardinality", {}).get("min", 1),
        cardinality_max=slot_data.get("cardinality", {}).get("max", 1),
        validation=slot_data.get("validation"),
    )


def _parse_token(token_data: dict[str, Any]) -> ProfileToken:
    """Parse a token definition from JSON."""
    return ProfileToken(
        token_id=token_data["token_id"],
        projection_path=token_data["projection_path"],
        scope=token_data.get("scope", {}),
        cardinality=token_data.get("cardinality", "SINGLE"),
        transform=token_data.get("transform"),
        default_value=token_data.get("default_value"),
    )


def _parse_marker(marker_data: dict[str, Any]) -> ProfileMarker:
    """Parse a marker definition from JSON."""
    return ProfileMarker(
        pattern=marker_data["pattern"],
        token=marker_data["token"],
        format_spec=marker_data.get("format"),
        required=marker_data.get("required", False),
    )


def _parse_issue_rule(rule_data: dict[str, Any]) -> ProfileIssueRule:
    """Parse an issue rule from JSON."""
    return ProfileIssueRule(
        rule_id=rule_data["rule_id"],
        condition=rule_data["condition"],
        severity=IssueSeverity(rule_data["severity"]),
        message=rule_data["message"],
        blocking=rule_data.get("blocking", False),
    )


def _parse_naming_rule(rule_data: dict[str, Any]) -> ProfileNamingRule:
    """Parse a naming rule from JSON."""
    return ProfileNamingRule(
        rule_id=rule_data["rule_id"],
        pattern=rule_data["pattern"],
        tokens=rule_data.get("tokens", {}),
        authority=NameAuthority(rule_data.get("authority", "PROPOSE")),
        validation=rule_data.get("validation"),
    )


def _validate_manifest(manifest_data: dict[str, Any]) -> dict[str, dict[str, str]]:
    """Validate the closed profile manifest shape before any component is read."""
    required_fields = {
        "profile_id",
        "version",
        "variant",
        "target_platform",
        "components",
        "profile_sha256",
    }
    missing_fields = required_fields - manifest_data.keys()
    if missing_fields:
        raise ProfileValidationError(f"Manifest missing required fields: {sorted(missing_fields)}")
    components = manifest_data["components"]
    if not isinstance(components, dict) or set(components) != _REQUIRED_COMPONENTS:
        raise ProfileValidationError(
            "Manifest components must contain exactly the required component set"
        )
    if (
        not isinstance(manifest_data["profile_sha256"], str)
        or len(manifest_data["profile_sha256"]) != 64
    ):
        raise ProfileValidationError("Manifest profile_sha256 must be a SHA-256 digest")

    validated: dict[str, dict[str, str]] = {}
    for component_name, expected_filename in _COMPONENT_FILES.items():
        component = components[component_name]
        if not isinstance(component, dict) or set(component) != {"path", "sha256"}:
            raise ProfileValidationError(f"Invalid {component_name} component declaration")
        path, digest = component["path"], component["sha256"]
        if path != expected_filename or not isinstance(digest, str) or len(digest) != 64:
            raise ProfileValidationError(
                f"Invalid {component_name} component path or SHA-256 digest"
            )
        validated[component_name] = {"path": path, "sha256": digest}
    return validated


def _require_nonempty(component_name: str, values: list[Any]) -> None:
    if not values:
        raise ProfileValidationError(f"Required {component_name} component is empty")


def _reject_duplicate_ids(component_name: str, values: list[Any], field_name: str) -> None:
    identifiers = [getattr(value, field_name) for value in values]
    if len(identifiers) != len(set(identifiers)):
        raise ProfileValidationError(f"Duplicate {field_name} in {component_name} component")


def _load_profile(profile_root: Path | Traversable, verify_hashes: bool) -> Profile:
    manifest_path = profile_root.joinpath("manifest.json")
    if not manifest_path.is_file():
        raise ProfileNotFoundError("Profile manifest not found")
    try:
        manifest_data = json.loads(manifest_path.read_bytes())
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        raise ProfileValidationError(f"Invalid manifest JSON: {error}") from error
    if not isinstance(manifest_data, dict):
        raise ProfileValidationError("Profile manifest must be a JSON object")

    components = _validate_manifest(manifest_data)
    component_hashes = {name: component["sha256"] for name, component in components.items()}
    if (
        verify_hashes
        and _compute_profile_hash(component_hashes, manifest_data)
        != manifest_data["profile_sha256"]
    ):
        raise ProfileHashMismatchError("Profile hash mismatch")

    compatibility = manifest_data.get("compatibility", {})
    metadata = manifest_data.get("metadata", {})
    manifest = ProfileManifest(
        profile_id=manifest_data["profile_id"],
        version=manifest_data["version"],
        display_name=str(manifest_data.get("display_name") or manifest_data["profile_id"]),
        description=manifest_data.get("description", ""),
        variant=manifest_data["variant"],
        target_platform=manifest_data["target_platform"],
        min_projection_version=compatibility.get("min_projection_version", "1.0.0"),
        max_projection_version=compatibility.get("max_projection_version", "999.x"),
        required_resource_kinds=compatibility.get("required_resource_kinds", []),
        optional_resource_kinds=compatibility.get("optional_resource_kinds", []),
        component_hashes=component_hashes,
        profile_hash=manifest_data["profile_sha256"],
        created_at=metadata.get("created_at"),
        created_by=metadata.get("created_by"),
        approved_at=metadata.get("approved_at"),
        approved_by=metadata.get("approved_by"),
    )

    parsed: dict[str, list[Any]] = {}
    generated_regions: list[GeneratedRegion] = []
    parsers = {
        "slots": ("slots", _parse_slot),
        "mappings": ("tokens", _parse_token),
        "markers": ("governed_markers", _parse_marker),
        "issue_rules": ("issue_rules", _parse_issue_rule),
        "naming_rules": ("naming_rules", _parse_naming_rule),
    }
    for component_name, component in components.items():
        component_path = profile_root.joinpath(component["path"])
        if not component_path.is_file():
            raise ProfileNotFoundError(f"Component not found: {component['path']}")
        content = component_path.read_bytes()
        if verify_hashes and _compute_file_hash(content) != component["sha256"]:
            raise ProfileHashMismatchError(f"Component {component_name} hash mismatch")
        try:
            component_data = json.loads(content)
            values_key, parser = parsers[component_name]
            values = component_data[values_key]
            if not isinstance(values, list):
                raise TypeError("collection must be a list")
            parsed[component_name] = [parser(value) for value in values]
            if component_name == "slots":
                candidate_regions = component_data.get("generated_regions", [])
                if not isinstance(candidate_regions, list) or any(
                    not isinstance(region, dict) for region in candidate_regions
                ):
                    raise ProfileValidationError("generated_regions must be a list of objects")
                generated_regions = [
                    _parse_generated_region(region) for region in candidate_regions
                ]
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
            raise ProfileValidationError(f"Invalid {component_name} component: {error}") from error
        _require_nonempty(component_name, parsed[component_name])

    _reject_duplicate_ids("slots", parsed["slots"], "slot_id")
    _reject_duplicate_ids("mappings", parsed["mappings"], "token_id")
    _reject_duplicate_ids("issue_rules", parsed["issue_rules"], "rule_id")
    _reject_duplicate_ids("naming_rules", parsed["naming_rules"], "rule_id")
    return Profile(
        manifest,
        parsed["slots"],
        parsed["mappings"],
        parsed["markers"],
        parsed["issue_rules"],
        parsed["naming_rules"],
        generated_regions,
    )


def load_profile_from_path(profile_path: Path, verify_hashes: bool = True) -> Profile:
    """
    Load a profile from a directory path.

    Args:
        profile_path: Path to profile directory
        verify_hashes: Whether to verify component hashes

    Returns:
        Loaded Profile

    Raises:
        ProfileNotFoundError: Profile directory not found
        ProfileHashMismatchError: Hash verification failed
        ProfileValidationError: Invalid profile data
    """
    if not profile_path.exists():
        raise ProfileNotFoundError(f"Profile path not found: {profile_path}")

    if profile_path.is_symlink():
        raise ProfileValidationError("Profile path must not be a symlink")
    return _load_profile(profile_path, verify_hashes)


def load_profile(profile_id: str, verify_hashes: bool = True) -> Profile:
    """
    Load a profile by ID from the package.

    Args:
        profile_id: Profile identifier (e.g., "CCPM_OUTPOST_V1")
        verify_hashes: Whether to verify component hashes

    Returns:
        Loaded Profile

    Raises:
        ProfileNotFoundError: Profile not found
    """
    try:
        from importlib.resources import files

        profile_package = f"migration_intake.topology.profiles.{profile_id.lower()}"
        profile_files = files(profile_package)
        return _load_profile(profile_files, verify_hashes)
    except (ModuleNotFoundError, TypeError) as error:
        raise ProfileNotFoundError(f"Profile {profile_id} not found") from error


def list_available_profiles() -> list[str]:
    """
    List available profile IDs.

    Returns:
        List of profile IDs
    """
    profiles_dir = Path(__file__).parent
    profile_ids = []

    for item in profiles_dir.iterdir():
        if item.is_dir() and (item / "manifest.json").exists():
            profile_ids.append(item.name.upper())

    return sorted(profile_ids)


# ─────────────────────────────────────────────────────────────────────────────
# Compatibility Checking
# ─────────────────────────────────────────────────────────────────────────────


def _version_in_range(version: str, min_version: str, max_version: str) -> bool:
    """Check if version is within range."""
    try:
        v = Version(version)
        min_v = Version(min_version)

        # Handle max version with 'x' wildcard
        if max_version.endswith(".x"):
            max_major = int(max_version.split(".")[0])
            return v >= min_v and v.major <= max_major
        else:
            max_v = Version(max_version)
            return min_v <= v <= max_v
    except (InvalidVersion, ValueError):
        return False


def check_profile_compatibility(
    profile: Profile,
    projection_version: str,
    projection_hash: str,
    resource_kinds: set[str],
) -> ProfileCompatibilityReport:
    """
    Check profile compatibility with a projection.

    Args:
        profile: Profile to check
        projection_version: Projection schema version
        projection_hash: Projection content hash
        resource_kinds: Set of resource kinds in projection

    Returns:
        ProfileCompatibilityReport with compatibility status
    """
    report = ProfileCompatibilityReport(
        profile_id=profile.profile_id,
        profile_version=profile.version,
        profile_hash=profile.profile_hash,
        projection_version=projection_version,
        projection_hash=projection_hash,
        is_compatible=True,
        slots_total=len(profile.slots),
    )

    # Check projection version
    if not _version_in_range(
        projection_version,
        profile.manifest.min_projection_version,
        profile.manifest.max_projection_version,
    ):
        report.is_compatible = False
        report.blocking_issues.append(
            f"Projection version {projection_version} not in range "
            f"[{profile.manifest.min_projection_version}, "
            f"{profile.manifest.max_projection_version}]"
        )

    # Check required resource kinds
    for required_kind in profile.manifest.required_resource_kinds:
        if required_kind not in resource_kinds:
            report.is_compatible = False
            report.blocking_issues.append(
                f"Required resource kind {required_kind} not found in projection"
            )

    # Check optional resource kinds (warnings only)
    for optional_kind in profile.manifest.optional_resource_kinds:
        if optional_kind not in resource_kinds:
            report.warnings.append(
                f"Optional resource kind {optional_kind} not found in projection"
            )

    # Determine readiness
    report.ready_for_render = report.is_compatible and len(report.blocking_issues) == 0

    if not report.ready_for_render:
        report.readiness_reason = "; ".join(report.blocking_issues)

    return report
