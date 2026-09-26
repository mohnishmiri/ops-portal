"""
Tests for Profile Loader (P6 Implementation).

These tests verify profile loading, validation, and compatibility checking.
"""

import hashlib
import json
import tempfile
from importlib import resources
from pathlib import Path

import pytest

from migration_intake.topology.profiles.loader import (
    ProfileHashMismatchError,
    ProfileNotFoundError,
    ProfileSlot,
    ProfileToken,
    ProfileValidationError,
    SlotType,
    UnresolvedPolicy,
    _compute_file_hash,
    _compute_profile_hash,
    _version_in_range,
    check_profile_compatibility,
    load_profile,
    load_profile_from_path,
)

# ─────────────────────────────────────────────────────────────────────────────
# Test Fixtures
# ─────────────────────────────────────────────────────────────────────────────


def create_test_profile(profile_dir: Path, profile_id: str = "TEST_PROFILE_V1"):
    """Create a test profile in the given directory."""
    # Create slots.json
    slots_data = {
        "slots": [
            {
                "slot_id": "APP_NAME",
                "slot_type": "MANDATORY",
                "display_name": "Application Name",
                "page_selector": {"page_name_pattern": "^Overview$"},
                "cell_matcher": {"match_type": "MARKER", "marker_pattern": "{{APP_NAME}}"},
                "tokens": ["APP_NAME"],
                "unresolved_policy": "ERROR",
                "cardinality": {"min": 1, "max": 1},
            },
            {
                "slot_id": "ENVIRONMENT",
                "slot_type": "OPTIONAL",
                "display_name": "Environment",
                "page_selector": {},
                "cell_matcher": {"match_type": "MARKER", "marker_pattern": "{{ENVIRONMENT}}"},
                "tokens": ["ENVIRONMENT"],
                "unresolved_policy": "SKIP",
            },
        ]
    }
    slots_content = json.dumps(slots_data, sort_keys=True).encode()
    slots_hash = hashlib.sha256(slots_content).hexdigest()
    (profile_dir / "slots.json").write_bytes(slots_content)

    # Create mappings.json
    mappings_data = {
        "tokens": [
            {
                "token_id": "APP_NAME",
                "projection_path": "$.application.name",
                "scope": {"lifecycle": "TARGET"},
                "cardinality": "SINGLE",
            },
            {
                "token_id": "ENVIRONMENT",
                "projection_path": "$.context.environment",
                "scope": {},
                "cardinality": "SINGLE",
            },
        ]
    }
    mappings_content = json.dumps(mappings_data, sort_keys=True).encode()
    mappings_hash = hashlib.sha256(mappings_content).hexdigest()
    (profile_dir / "mappings.json").write_bytes(mappings_content)

    # Create markers.json
    markers_data = {
        "governed_markers": [
            {"pattern": "{{APP_NAME}}", "token": "APP_NAME", "required": True},
            {"pattern": "{{ENVIRONMENT}}", "token": "ENVIRONMENT", "required": False},
        ]
    }
    markers_content = json.dumps(markers_data, sort_keys=True).encode()
    markers_hash = hashlib.sha256(markers_content).hexdigest()
    (profile_dir / "markers.json").write_bytes(markers_content)

    # Create issue_rules.json
    issue_rules_data = {
        "issue_rules": [
            {
                "rule_id": "MISSING_APP_NAME",
                "condition": "$.application.name == null",
                "severity": "ERROR",
                "message": "Application name is required",
                "blocking": True,
            }
        ]
    }
    issue_rules_content = json.dumps(issue_rules_data, sort_keys=True).encode()
    issue_rules_hash = hashlib.sha256(issue_rules_content).hexdigest()
    (profile_dir / "issue_rules.json").write_bytes(issue_rules_content)

    # Create naming_rules.json
    naming_rules_data = {
        "naming_rules": [
            {
                "rule_id": "RESOURCE_NAME",
                "pattern": "{app_name}-{environment}",
                "tokens": {"app_name": "APP_NAME", "environment": "ENVIRONMENT"},
                "authority": "PROPOSE",
            }
        ]
    }
    naming_rules_content = json.dumps(naming_rules_data, sort_keys=True).encode()
    naming_rules_hash = hashlib.sha256(naming_rules_content).hexdigest()
    (profile_dir / "naming_rules.json").write_bytes(naming_rules_content)

    # Compute combined profile hash
    component_hashes = {
        "slots": slots_hash,
        "mappings": mappings_hash,
        "markers": markers_hash,
        "issue_rules": issue_rules_hash,
        "naming_rules": naming_rules_hash,
    }
    # Create manifest.json
    manifest_data = {
        "profile_id": profile_id,
        "version": "1.0.0",
        "display_name": "Test Profile V1",
        "description": "A test profile for unit tests",
        "variant": "TEST",
        "target_platform": "AWS",
        "compatibility": {
            "min_projection_version": "1.0.0",
            "max_projection_version": "2.x",
            "required_resource_kinds": ["PLACEMENT", "VPC"],
            "optional_resource_kinds": ["SUBNET", "COMPUTE"],
        },
        "components": {
            "slots": {"path": "slots.json", "sha256": slots_hash},
            "mappings": {"path": "mappings.json", "sha256": mappings_hash},
            "markers": {"path": "markers.json", "sha256": markers_hash},
            "issue_rules": {"path": "issue_rules.json", "sha256": issue_rules_hash},
            "naming_rules": {"path": "naming_rules.json", "sha256": naming_rules_hash},
        },
        "profile_sha256": "",
        "metadata": {
            "created_at": "2026-09-18T00:00:00Z",
            "created_by": "test-user",
        },
    }
    profile_hash = _compute_profile_hash(component_hashes, manifest_data)
    manifest_data["profile_sha256"] = profile_hash
    manifest_content = json.dumps(manifest_data, sort_keys=True, indent=2).encode()
    (profile_dir / "manifest.json").write_bytes(manifest_content)

    return profile_hash


@pytest.fixture
def test_profile_dir():
    """Create a temporary directory with a test profile."""
    with tempfile.TemporaryDirectory() as tmpdir:
        profile_dir = Path(tmpdir) / "test_profile_v1"
        profile_dir.mkdir()
        create_test_profile(profile_dir)
        yield profile_dir


# ─────────────────────────────────────────────────────────────────────────────
# Hash Computation Tests
# ─────────────────────────────────────────────────────────────────────────────


class TestHashComputation:
    """Tests for hash computation functions."""

    def test_compute_file_hash(self):
        """Compute SHA-256 hash of content."""
        content = b"test content"
        expected = hashlib.sha256(content).hexdigest()
        assert _compute_file_hash(content) == expected

    def test_compute_profile_hash(self):
        """Compute combined profile hash."""
        hashes = {"a": "hash_a", "b": "hash_b", "c": "hash_c"}
        expected = hashlib.sha256(
            b'{"components":{"a":"hash_a","b":"hash_b","c":"hash_c"}}'
        ).hexdigest()
        assert _compute_profile_hash(hashes) == expected

    def test_compute_profile_hash_order_independent(self):
        """Profile hash is independent of input order."""
        hashes1 = {"a": "hash_a", "b": "hash_b"}
        hashes2 = {"b": "hash_b", "a": "hash_a"}
        assert _compute_profile_hash(hashes1) == _compute_profile_hash(hashes2)


# ─────────────────────────────────────────────────────────────────────────────
# Profile Loading Tests
# ─────────────────────────────────────────────────────────────────────────────


class TestProfileLoading:
    """Tests for profile loading."""

    def test_load_profile_from_path(self, test_profile_dir):
        """Load a profile from a directory."""
        profile = load_profile_from_path(test_profile_dir)

        assert profile.profile_id == "TEST_PROFILE_V1"
        assert profile.version == "1.0.0"
        assert len(profile.slots) == 2
        assert len(profile.tokens) == 2
        assert len(profile.markers) == 2
        assert len(profile.issue_rules) == 1
        assert len(profile.naming_rules) == 1

    def test_load_profile_manifest(self, test_profile_dir):
        """Verify manifest is loaded correctly."""
        profile = load_profile_from_path(test_profile_dir)

        assert profile.manifest.display_name == "Test Profile V1"
        assert profile.manifest.variant == "TEST"
        assert profile.manifest.target_platform == "AWS"
        assert profile.manifest.min_projection_version == "1.0.0"
        assert profile.manifest.max_projection_version == "2.x"
        assert "PLACEMENT" in profile.manifest.required_resource_kinds
        assert "VPC" in profile.manifest.required_resource_kinds

    def test_load_profile_slots(self, test_profile_dir):
        """Verify slots are loaded correctly."""
        profile = load_profile_from_path(test_profile_dir)

        app_name_slot = next(s for s in profile.slots if s.slot_id == "APP_NAME")
        assert app_name_slot.slot_type == SlotType.MANDATORY
        assert app_name_slot.unresolved_policy == UnresolvedPolicy.ERROR
        assert "APP_NAME" in app_name_slot.tokens

        env_slot = next(s for s in profile.slots if s.slot_id == "ENVIRONMENT")
        assert env_slot.slot_type == SlotType.OPTIONAL
        assert env_slot.unresolved_policy == UnresolvedPolicy.SKIP

    def test_load_profile_tokens(self, test_profile_dir):
        """Verify tokens are loaded correctly."""
        profile = load_profile_from_path(test_profile_dir)

        app_name_token = profile.get_token("APP_NAME")
        assert app_name_token is not None
        assert app_name_token.projection_path == "$.application.name"
        assert app_name_token.scope.get("lifecycle") == "TARGET"

    def test_load_profile_not_found(self):
        """Loading non-existent profile raises error."""
        with pytest.raises(ProfileNotFoundError):
            load_profile_from_path(Path("/nonexistent/path"))

    def test_load_profile_hash_mismatch(self, test_profile_dir):
        """Hash mismatch raises error."""
        # Corrupt a component file
        slots_path = test_profile_dir / "slots.json"
        slots_path.write_text('{"slots": []}')  # Different content

        with pytest.raises(ProfileHashMismatchError):
            load_profile_from_path(test_profile_dir, verify_hashes=True)

    def test_load_profile_skip_hash_verification(self, test_profile_dir):
        """Can skip hash verification."""
        # Corrupt a component file
        slots_path = test_profile_dir / "slots.json"
        slots_path.write_text(
            '{"slots": [{"slot_id": "REPLACEMENT", "slot_type": "OPTIONAL", '
            '"page_selector": {}, "cell_matcher": {}, "tokens": ["REPLACEMENT"]}]}'
        )

        # Should not raise with verify_hashes=False
        profile = load_profile_from_path(test_profile_dir, verify_hashes=False)
        assert profile.profile_id == "TEST_PROFILE_V1"

    @pytest.mark.parametrize(
        "mutation",
        [
            lambda manifest: manifest.update({"description": "changed"}),
            lambda manifest: manifest["components"].update({"unknown": {"path": "x.json", "sha256": "0" * 64}}),
            lambda manifest: manifest["components"]["slots"].update({"path": "../slots.json"}),
        ],
    )
    def test_rejects_semantically_changed_or_unsafe_manifest(self, test_profile_dir, mutation):
        """Profile identity covers manifest semantics and strict component inventory."""
        manifest_path = test_profile_dir / "manifest.json"
        manifest = json.loads(manifest_path.read_text())
        mutation(manifest)
        manifest_path.write_text(json.dumps(manifest))

        with pytest.raises((ProfileHashMismatchError, ProfileValidationError)):
            load_profile_from_path(test_profile_dir)

    def test_rejects_empty_required_component(self, test_profile_dir):
        """Required component collections cannot silently load as empty."""
        slots_path = test_profile_dir / "slots.json"
        slots_content = b'{"slots": []}'
        slots_path.write_bytes(slots_content)

        manifest_path = test_profile_dir / "manifest.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["components"]["slots"]["sha256"] = _compute_file_hash(slots_content)
        manifest["profile_sha256"] = _compute_profile_hash(
            {
                name: component["sha256"]
                for name, component in manifest["components"].items()
            },
            manifest,
        )
        manifest_path.write_text(json.dumps(manifest))

        with pytest.raises(ProfileValidationError, match="slots"):
            load_profile_from_path(test_profile_dir)

    def test_rejects_duplicate_token_ids(self, test_profile_dir):
        """Duplicate token IDs are ambiguous and must fail closed."""
        mappings_path = test_profile_dir / "mappings.json"
        mappings = json.loads(mappings_path.read_text())
        mappings["tokens"].append(mappings["tokens"][0])
        mappings_content = json.dumps(mappings, sort_keys=True).encode()
        mappings_path.write_bytes(mappings_content)

        manifest_path = test_profile_dir / "manifest.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["components"]["mappings"]["sha256"] = _compute_file_hash(mappings_content)
        manifest["profile_sha256"] = _compute_profile_hash(
            {
                name: component["sha256"]
                for name, component in manifest["components"].items()
            },
            manifest,
        )
        manifest_path.write_text(json.dumps(manifest))

        with pytest.raises(ProfileValidationError, match="Duplicate token_id"):
            load_profile_from_path(test_profile_dir)

    def test_load_profile_uses_packaged_synthetic_release(self):
        """Profile package resources remain usable without filesystem source paths."""
        profile = load_profile("SYNTHETIC_LABEL_ONLY")

        assert profile.manifest.target_platform == "DRAWIO"
        assert resources.files("migration_intake.topology.profiles.synthetic_label_only").is_dir()


# ─────────────────────────────────────────────────────────────────────────────
# Version Range Tests
# ─────────────────────────────────────────────────────────────────────────────


class TestVersionRange:
    """Tests for version range checking."""

    def test_version_in_exact_range(self):
        """Version within exact range."""
        assert _version_in_range("1.5.0", "1.0.0", "2.0.0")

    def test_version_at_min(self):
        """Version at minimum."""
        assert _version_in_range("1.0.0", "1.0.0", "2.0.0")

    def test_version_at_max(self):
        """Version at maximum."""
        assert _version_in_range("2.0.0", "1.0.0", "2.0.0")

    def test_version_below_min(self):
        """Version below minimum."""
        assert not _version_in_range("0.9.0", "1.0.0", "2.0.0")

    def test_version_above_max(self):
        """Version above maximum."""
        assert not _version_in_range("2.1.0", "1.0.0", "2.0.0")

    def test_version_with_wildcard_max(self):
        """Version with wildcard max (2.x)."""
        assert _version_in_range("2.5.0", "1.0.0", "2.x")
        assert _version_in_range("2.99.99", "1.0.0", "2.x")
        assert not _version_in_range("3.0.0", "1.0.0", "2.x")


# ─────────────────────────────────────────────────────────────────────────────
# Compatibility Checking Tests
# ─────────────────────────────────────────────────────────────────────────────


class TestCompatibilityChecking:
    """Tests for profile compatibility checking."""

    def test_compatible_profile(self, test_profile_dir):
        """Profile is compatible with matching projection."""
        profile = load_profile_from_path(test_profile_dir)

        report = check_profile_compatibility(
            profile=profile,
            projection_version="1.5.0",
            projection_hash="abc123",
            resource_kinds={"PLACEMENT", "VPC", "SUBNET"},
        )

        assert report.is_compatible
        assert report.ready_for_render
        assert len(report.blocking_issues) == 0

    def test_incompatible_projection_version(self, test_profile_dir):
        """Profile incompatible with wrong projection version."""
        profile = load_profile_from_path(test_profile_dir)

        report = check_profile_compatibility(
            profile=profile,
            projection_version="0.5.0",  # Below min
            projection_hash="abc123",
            resource_kinds={"PLACEMENT", "VPC"},
        )

        assert not report.is_compatible
        assert not report.ready_for_render
        assert len(report.blocking_issues) > 0
        assert "version" in report.blocking_issues[0].lower()

    def test_missing_required_resource_kind(self, test_profile_dir):
        """Profile incompatible when required resource kind missing."""
        profile = load_profile_from_path(test_profile_dir)

        report = check_profile_compatibility(
            profile=profile,
            projection_version="1.5.0",
            projection_hash="abc123",
            resource_kinds={"PLACEMENT"},  # Missing VPC
        )

        assert not report.is_compatible
        assert not report.ready_for_render
        assert any("VPC" in issue for issue in report.blocking_issues)

    def test_missing_optional_resource_kind(self, test_profile_dir):
        """Missing optional resource kind generates warning only."""
        profile = load_profile_from_path(test_profile_dir)

        report = check_profile_compatibility(
            profile=profile,
            projection_version="1.5.0",
            projection_hash="abc123",
            resource_kinds={"PLACEMENT", "VPC"},  # Missing SUBNET (optional)
        )

        assert report.is_compatible
        assert report.ready_for_render
        assert any("SUBNET" in warning for warning in report.warnings)


# ─────────────────────────────────────────────────────────────────────────────
# Data Class Tests
# ─────────────────────────────────────────────────────────────────────────────


class TestDataClasses:
    """Tests for profile data classes."""

    def test_slot_type_enum(self):
        """SlotType enum values."""
        assert SlotType.MANDATORY.value == "MANDATORY"
        assert SlotType.CONDITIONAL.value == "CONDITIONAL"
        assert SlotType.OPTIONAL.value == "OPTIONAL"
        assert SlotType.REPEATING.value == "REPEATING"

    def test_unresolved_policy_enum(self):
        """UnresolvedPolicy enum values."""
        assert UnresolvedPolicy.ERROR.value == "ERROR"
        assert UnresolvedPolicy.WARN.value == "WARN"
        assert UnresolvedPolicy.SKIP.value == "SKIP"

    def test_profile_slot_frozen(self):
        """ProfileSlot is immutable."""
        slot = ProfileSlot(
            slot_id="TEST",
            slot_type=SlotType.MANDATORY,
            display_name="Test",
            page_selector={},
            cell_matcher={},
            tokens=("TOKEN",),
        )

        with pytest.raises(AttributeError):
            slot.slot_id = "CHANGED"

    def test_profile_token_frozen(self):
        """ProfileToken is immutable."""
        token = ProfileToken(
            token_id="TEST",
            projection_path="$.test",
            scope={},
        )

        with pytest.raises(AttributeError):
            token.token_id = "CHANGED"
