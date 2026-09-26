"""
Tests for domain value objects.

These tests verify:
- Identifier/name/acronym normalization
- Decimal values reject NaN/infinity
- UTC clock values remain timezone-aware
- Value objects are immutable
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest


class TestNormalizedName:
    """Tests for NormalizedName value object."""

    def test_normalize_whitespace(self) -> None:
        """NormalizedName should collapse internal whitespace."""
        from migration_intake.domain.values import NormalizedName

        name = NormalizedName("  My   Application  Name  ")

        assert name.value == "My Application Name"

    def test_preserve_case(self) -> None:
        """NormalizedName should preserve case."""
        from migration_intake.domain.values import NormalizedName

        name = NormalizedName("MyApp")

        assert name.value == "MyApp"

    def test_reject_empty(self) -> None:
        """NormalizedName should reject empty string."""
        from migration_intake.domain.values import NormalizedName

        with pytest.raises(ValueError, match="[Ee]mpty"):
            NormalizedName("")

    def test_reject_whitespace_only(self) -> None:
        """NormalizedName should reject whitespace-only string."""
        from migration_intake.domain.values import NormalizedName

        with pytest.raises(ValueError, match="[Ee]mpty"):
            NormalizedName("   ")

    def test_immutable(self) -> None:
        """NormalizedName should be immutable."""
        from migration_intake.domain.values import NormalizedName

        name = NormalizedName("Test")

        with pytest.raises((AttributeError, TypeError)):
            name.value = "Changed"  # type: ignore[misc]


class TestNormalizedAcronym:
    """Tests for NormalizedAcronym value object."""

    def test_normalize_to_uppercase(self) -> None:
        """NormalizedAcronym should convert to uppercase."""
        from migration_intake.domain.values import NormalizedAcronym

        acronym = NormalizedAcronym("myapp")

        assert acronym.value == "MYAPP"

    def test_strip_whitespace(self) -> None:
        """NormalizedAcronym should strip whitespace."""
        from migration_intake.domain.values import NormalizedAcronym

        acronym = NormalizedAcronym("  APP  ")

        assert acronym.value == "APP"

    def test_reject_empty(self) -> None:
        """NormalizedAcronym should reject empty string."""
        from migration_intake.domain.values import NormalizedAcronym

        with pytest.raises(ValueError, match="[Ee]mpty"):
            NormalizedAcronym("")

    def test_allow_none_for_optional(self) -> None:
        """NormalizedAcronym.from_optional should allow None."""
        from migration_intake.domain.values import NormalizedAcronym

        result = NormalizedAcronym.from_optional(None)

        assert result is None

    def test_from_optional_with_value(self) -> None:
        """NormalizedAcronym.from_optional should normalize non-None values."""
        from migration_intake.domain.values import NormalizedAcronym

        result = NormalizedAcronym.from_optional("  app  ")

        assert result is not None
        assert result.value == "APP"


class TestSafeDecimal:
    """Tests for SafeDecimal value object."""

    def test_accept_valid_decimal(self) -> None:
        """SafeDecimal should accept valid decimal values."""
        from migration_intake.domain.values import SafeDecimal

        value = SafeDecimal(Decimal("123.45"))

        assert value.value == Decimal("123.45")

    def test_accept_integer(self) -> None:
        """SafeDecimal should accept integer values."""
        from migration_intake.domain.values import SafeDecimal

        value = SafeDecimal(42)

        assert value.value == Decimal("42")

    def test_accept_string(self) -> None:
        """SafeDecimal should accept string representation."""
        from migration_intake.domain.values import SafeDecimal

        value = SafeDecimal("123.45")

        assert value.value == Decimal("123.45")

    def test_reject_nan(self) -> None:
        """SafeDecimal should reject NaN."""
        from migration_intake.domain.values import SafeDecimal

        with pytest.raises(ValueError, match="NaN"):
            SafeDecimal(Decimal("NaN"))

    def test_reject_infinity(self) -> None:
        """SafeDecimal should reject positive infinity."""
        from migration_intake.domain.values import SafeDecimal

        with pytest.raises(ValueError, match="[Ii]nfinity"):
            SafeDecimal(Decimal("Infinity"))

    def test_reject_negative_infinity(self) -> None:
        """SafeDecimal should reject negative infinity."""
        from migration_intake.domain.values import SafeDecimal

        with pytest.raises(ValueError, match="[Ii]nfinity"):
            SafeDecimal(Decimal("-Infinity"))

    def test_immutable(self) -> None:
        """SafeDecimal should be immutable."""
        from migration_intake.domain.values import SafeDecimal

        value = SafeDecimal(Decimal("100"))

        with pytest.raises((AttributeError, TypeError)):
            value.value = Decimal("200")  # type: ignore[misc]


class TestUtcTimestamp:
    """Tests for UtcTimestamp value object."""

    def test_accept_utc_datetime(self) -> None:
        """UtcTimestamp should accept UTC datetime."""
        from migration_intake.domain.values import UtcTimestamp

        dt = datetime(2026, 9, 8, 12, 0, 0, tzinfo=timezone.utc)
        ts = UtcTimestamp(dt)

        assert ts.value == dt
        assert ts.value.tzinfo == timezone.utc

    def test_reject_naive_datetime(self) -> None:
        """UtcTimestamp should reject naive (no timezone) datetime."""
        from migration_intake.domain.values import UtcTimestamp

        naive_dt = datetime(2026, 9, 8, 12, 0, 0)

        with pytest.raises(ValueError, match="[Tt]imezone|UTC"):
            UtcTimestamp(naive_dt)

    def test_convert_non_utc_to_utc(self) -> None:
        """UtcTimestamp should convert non-UTC timezone to UTC."""
        from datetime import timedelta

        from migration_intake.domain.values import UtcTimestamp

        # Create a datetime in UTC-5
        eastern = timezone(timedelta(hours=-5))
        dt = datetime(2026, 9, 8, 12, 0, 0, tzinfo=eastern)

        ts = UtcTimestamp(dt)

        # Should be converted to UTC (17:00 UTC)
        assert ts.value.tzinfo == timezone.utc
        assert ts.value.hour == 17

    def test_now_returns_utc(self) -> None:
        """UtcTimestamp.now() should return current UTC time."""
        from migration_intake.domain.values import UtcTimestamp

        ts = UtcTimestamp.now()

        assert ts.value.tzinfo == timezone.utc

    def test_immutable(self) -> None:
        """UtcTimestamp should be immutable."""
        from migration_intake.domain.values import UtcTimestamp

        ts = UtcTimestamp(datetime.now(timezone.utc))

        with pytest.raises((AttributeError, TypeError)):
            ts.value = datetime.now(timezone.utc)  # type: ignore[misc]


class TestVersionToken:
    """Tests for VersionToken (optimistic concurrency)."""

    def test_create_from_integer(self) -> None:
        """VersionToken should accept integer version."""
        from migration_intake.domain.values import VersionToken

        token = VersionToken(1)

        assert token.value == 1

    def test_increment(self) -> None:
        """VersionToken.next() should return incremented version."""
        from migration_intake.domain.values import VersionToken

        token = VersionToken(1)
        next_token = token.next()

        assert next_token.value == 2

    def test_reject_negative(self) -> None:
        """VersionToken should reject negative values."""
        from migration_intake.domain.values import VersionToken

        with pytest.raises(ValueError, match="[Nn]egative|[Pp]ositive"):
            VersionToken(-1)

    def test_initial_version(self) -> None:
        """VersionToken.initial() should return version 1."""
        from migration_intake.domain.values import VersionToken

        token = VersionToken.initial()

        assert token.value == 1


class TestControlCode:
    """Tests for ControlCode value object."""

    def test_normalize_format(self) -> None:
        """ControlCode should normalize to uppercase with hyphen."""
        from migration_intake.domain.values import ControlCode

        code = ControlCode("app-001")

        assert code.value == "APP-001"

    def test_accept_valid_format(self) -> None:
        """ControlCode should accept valid format."""
        from migration_intake.domain.values import ControlCode

        code = ControlCode("CTL-002")

        assert code.value == "CTL-002"

    def test_reject_invalid_format(self) -> None:
        """ControlCode should reject invalid format."""
        from migration_intake.domain.values import ControlCode

        with pytest.raises(ValueError, match="[Ff]ormat|[Ii]nvalid"):
            ControlCode("INVALID")

    def test_reject_empty(self) -> None:
        """ControlCode should reject empty string."""
        from migration_intake.domain.values import ControlCode

        with pytest.raises(ValueError):
            ControlCode("")
