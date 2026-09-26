"""
Topology Profiles — P6 Implementation.

This package contains profile definitions and the profile loading infrastructure.
"""

from migration_intake.topology.profiles.loader import (
    Profile,
    ProfileCompatibilityReport,
    ProfileError,
    ProfileHashMismatchError,
    ProfileIncompatibleError,
    ProfileIssueRule,
    ProfileManifest,
    ProfileMarker,
    ProfileNotFoundError,
    ProfileSlot,
    ProfileToken,
    check_profile_compatibility,
    list_available_profiles,
    load_profile,
)

__all__ = [
    "Profile",
    "ProfileCompatibilityReport",
    "ProfileError",
    "ProfileHashMismatchError",
    "ProfileIncompatibleError",
    "ProfileIssueRule",
    "ProfileManifest",
    "ProfileMarker",
    "ProfileNotFoundError",
    "ProfileSlot",
    "ProfileToken",
    "check_profile_compatibility",
    "list_available_profiles",
    "load_profile",
]
