"""Tests for variant → profile mapping (Slice 5)."""

from __future__ import annotations

import pytest

from migration_intake.topology.haf_pipeline import (
    VARIANT_PROFILE_MAP,
    load_haf_profile,
)


class TestVariantProfileMap:
    """VARIANT_PROFILE_MAP maps variant strings to profile IDs."""

    def test_map_exists(self) -> None:
        assert isinstance(VARIANT_PROFILE_MAP, dict)

    def test_none_maps_to_legacy(self) -> None:
        assert VARIANT_PROFILE_MAP[None] == "OUTPOST_V1"

    def test_basic_variant(self) -> None:
        assert VARIANT_PROFILE_MAP["basic"] == "OUTPOST_V1_BASIC"

    def test_tlgw_variant(self) -> None:
        assert VARIANT_PROFILE_MAP["tlgw"] == "OUTPOST_V1_TLGW"

    def test_f5_variant(self) -> None:
        assert VARIANT_PROFILE_MAP["f5"] == "OUTPOST_V1_F5"

    def test_hadr_variant(self) -> None:
        assert VARIANT_PROFILE_MAP["hadr"] == "OUTPOST_V1_HADR"

    def test_all_profiles_loadable(self) -> None:
        for variant, profile_id in VARIANT_PROFILE_MAP.items():
            profile = load_haf_profile(profile_id)
            assert profile.profile_id == profile_id, (
                f"Variant {variant!r} profile {profile_id!r} not loadable"
            )


class TestGetProfileForVariant:
    """get_profile_for_variant returns the correct profile."""

    def test_none_returns_legacy(self) -> None:
        from migration_intake.topology.haf_pipeline import get_profile_for_variant

        profile = get_profile_for_variant(None)
        assert profile.profile_id == "OUTPOST_V1"

    def test_basic_returns_basic(self) -> None:
        from migration_intake.topology.haf_pipeline import get_profile_for_variant

        profile = get_profile_for_variant("basic")
        assert profile.profile_id == "OUTPOST_V1_BASIC"

    def test_unknown_variant_raises(self) -> None:
        from migration_intake.topology.haf_pipeline import (
            HafProfileError,
            get_profile_for_variant,
        )

        with pytest.raises(HafProfileError, match="Unknown variant"):
            get_profile_for_variant("nonexistent")
