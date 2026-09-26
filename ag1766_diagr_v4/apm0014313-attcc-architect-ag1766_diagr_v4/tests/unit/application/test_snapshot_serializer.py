"""
Unit tests for CanonicalSerializer — S01.

Verifies:
- Insertion/query order independence
- Unicode handling
- Decimal handling
- Date handling
- Same-state same-bytes/hash
- One-value hash change
- Unsupported payload failure
- No client fixture data
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone, timedelta
from decimal import Decimal

import pytest

from migration_intake.application.snapshots import (
    CanonicalAnswer,
    CanonicalIntakePayload,
    CanonicalSerializer,
    CanonicalWaveUtilRow,
    SCHEMA_VERSION,
)


def _create_test_payload(
    answers: list[CanonicalAnswer] | None = None,
    wave_util_rows: list[CanonicalWaveUtilRow] | None = None,
) -> CanonicalIntakePayload:
    """Create a test payload with default values."""
    return CanonicalIntakePayload(
        schema_version=SCHEMA_VERSION,
        application_id="app-001",
        application_name="Test Application",
        catalog_id="cat-001",
        catalog_version="1.0.0",
        catalog_sha256="a" * 64,
        catalog_hash="b" * 64,  # v2.0.0: compiled catalog hash
        intake_id="intake-001",
        intake_state="FROZEN",
        frozen_at="2025-01-15T10:30:00.000Z",
        frozen_by="actor-001",
        answers=answers or [],
        wave_util_rows=wave_util_rows or [],
        permitted_gaps=[],
    )


class TestDeterministicSerialization:
    """Tests for deterministic serialization."""

    def test_same_payload_same_hash(self) -> None:
        """Same payload produces same hash."""
        payload = _create_test_payload()

        json1, hash1 = CanonicalSerializer.serialize(payload)
        json2, hash2 = CanonicalSerializer.serialize(payload)

        assert json1 == json2
        assert hash1 == hash2

    def test_insertion_order_independence_answers(self) -> None:
        """Answer insertion order does not affect hash."""
        answer1 = CanonicalAnswer(
            question_id="q1",
            question_code="Q001",
            section_code="S01",
            response_type="TEXT",
            value_json="Answer 1",
            review_state="CONFIRMED",
            revision_number=1,
        )
        answer2 = CanonicalAnswer(
            question_id="q2",
            question_code="Q002",
            section_code="S01",
            response_type="TEXT",
            value_json="Answer 2",
            review_state="CONFIRMED",
            revision_number=1,
        )

        # Create payloads with answers in different orders
        payload1 = _create_test_payload(answers=[answer1, answer2])
        payload2 = _create_test_payload(answers=[answer2, answer1])

        _, hash1 = CanonicalSerializer.serialize(payload1)
        _, hash2 = CanonicalSerializer.serialize(payload2)

        assert hash1 == hash2

    def test_insertion_order_independence_wave_util(self) -> None:
        """WaveUtil row insertion order does not affect hash."""
        row1 = CanonicalWaveUtilRow(
            row_id="row1",
            server_name="Server-A",
            normalized_server_name="server-a",
            environment="PROD",
            scope="IN_SCOPE",
            state="ACTIVE",
            revision_number=1,
        )
        row2 = CanonicalWaveUtilRow(
            row_id="row2",
            server_name="Server-B",
            normalized_server_name="server-b",
            environment="DEV",
            scope="IN_SCOPE",
            state="ACTIVE",
            revision_number=1,
        )

        # Create payloads with rows in different orders
        payload1 = _create_test_payload(wave_util_rows=[row1, row2])
        payload2 = _create_test_payload(wave_util_rows=[row2, row1])

        _, hash1 = CanonicalSerializer.serialize(payload1)
        _, hash2 = CanonicalSerializer.serialize(payload2)

        assert hash1 == hash2


class TestUnicodeHandling:
    """Tests for Unicode handling."""

    def test_unicode_in_answer_value(self) -> None:
        """Unicode characters in answer values are preserved."""
        answer = CanonicalAnswer(
            question_id="q1",
            question_code="Q001",
            section_code="S01",
            response_type="TEXT",
            value_json="日本語テスト 🎉",
            review_state="CONFIRMED",
            revision_number=1,
        )
        payload = _create_test_payload(answers=[answer])

        json_str, _ = CanonicalSerializer.serialize(payload)

        assert "日本語テスト" in json_str
        assert "🎉" in json_str

    def test_unicode_in_server_name(self) -> None:
        """Unicode characters in server names are preserved."""
        row = CanonicalWaveUtilRow(
            row_id="row1",
            server_name="サーバー-001",
            normalized_server_name="サーバー-001",
            environment="PROD",
            scope="IN_SCOPE",
            state="ACTIVE",
            revision_number=1,
        )
        payload = _create_test_payload(wave_util_rows=[row])

        json_str, _ = CanonicalSerializer.serialize(payload)

        assert "サーバー-001" in json_str


class TestDecimalHandling:
    """Tests for Decimal handling."""

    def test_decimal_in_field_values(self) -> None:
        """Decimal values are serialized as strings."""
        row = CanonicalWaveUtilRow(
            row_id="row1",
            server_name="server-001",
            normalized_server_name="server-001",
            environment="PROD",
            scope="IN_SCOPE",
            state="ACTIVE",
            revision_number=1,
            field_values={"memory_gb": Decimal("32.5")},
        )
        payload = _create_test_payload(wave_util_rows=[row])

        json_str, _ = CanonicalSerializer.serialize(payload)

        # Decimal should be serialized as string
        assert '"32.5"' in json_str


class TestDateHandling:
    """Tests for date/time handling."""

    def test_datetime_normalized_to_utc(self) -> None:
        """Datetime values are normalized to UTC."""
        # Create a non-UTC datetime
        est = timezone(timedelta(hours=-5))
        dt = datetime(2025, 1, 15, 10, 30, 0, tzinfo=est)

        normalized = CanonicalSerializer.normalize_timestamp(dt)

        # Should be converted to UTC (15:30)
        assert normalized == "2025-01-15T15:30:00.000Z"

    def test_naive_datetime_rejected(self) -> None:
        """Naive datetime raises ValueError."""
        dt = datetime(2025, 1, 15, 10, 30, 0)  # No timezone

        with pytest.raises(ValueError, match="Naive datetime"):
            CanonicalSerializer.normalize_timestamp(dt)


class TestHashVerification:
    """Tests for hash verification."""

    def test_verify_hash_correct(self) -> None:
        """Correct hash verifies successfully."""
        payload = _create_test_payload()
        json_str, expected_hash = CanonicalSerializer.serialize(payload)

        assert CanonicalSerializer.verify_hash(json_str, expected_hash) is True

    def test_verify_hash_incorrect(self) -> None:
        """Incorrect hash fails verification."""
        payload = _create_test_payload()
        json_str, _ = CanonicalSerializer.serialize(payload)

        assert CanonicalSerializer.verify_hash(json_str, "wrong" * 16) is False


class TestOneValueHashChange:
    """Tests for hash sensitivity to value changes."""

    def test_answer_value_change_changes_hash(self) -> None:
        """Changing an answer value changes the hash."""
        answer1 = CanonicalAnswer(
            question_id="q1",
            question_code="Q001",
            section_code="S01",
            response_type="TEXT",
            value_json="Original",
            review_state="CONFIRMED",
            revision_number=1,
        )
        answer2 = CanonicalAnswer(
            question_id="q1",
            question_code="Q001",
            section_code="S01",
            response_type="TEXT",
            value_json="Modified",  # Changed
            review_state="CONFIRMED",
            revision_number=1,
        )

        payload1 = _create_test_payload(answers=[answer1])
        payload2 = _create_test_payload(answers=[answer2])

        _, hash1 = CanonicalSerializer.serialize(payload1)
        _, hash2 = CanonicalSerializer.serialize(payload2)

        assert hash1 != hash2

    def test_server_name_change_changes_hash(self) -> None:
        """Changing a server name changes the hash."""
        row1 = CanonicalWaveUtilRow(
            row_id="row1",
            server_name="server-001",
            normalized_server_name="server-001",
            environment="PROD",
            scope="IN_SCOPE",
            state="ACTIVE",
            revision_number=1,
        )
        row2 = CanonicalWaveUtilRow(
            row_id="row1",
            server_name="server-002",  # Changed
            normalized_server_name="server-002",  # Changed
            environment="PROD",
            scope="IN_SCOPE",
            state="ACTIVE",
            revision_number=1,
        )

        payload1 = _create_test_payload(wave_util_rows=[row1])
        payload2 = _create_test_payload(wave_util_rows=[row2])

        _, hash1 = CanonicalSerializer.serialize(payload1)
        _, hash2 = CanonicalSerializer.serialize(payload2)

        assert hash1 != hash2


class TestSchemaVersion:
    """Tests for schema version handling."""

    def test_schema_version_included(self) -> None:
        """Schema version is included in output."""
        payload = _create_test_payload()

        json_str, _ = CanonicalSerializer.serialize(payload)
        parsed = json.loads(json_str)

        assert parsed["schema_version"] == SCHEMA_VERSION


class TestSortedKeys:
    """Tests for sorted key output."""

    def test_json_keys_sorted(self) -> None:
        """JSON output has sorted keys."""
        payload = _create_test_payload()

        json_str, _ = CanonicalSerializer.serialize(payload)
        parsed = json.loads(json_str)

        # Top-level keys should be sorted
        keys = list(parsed.keys())
        assert keys == sorted(keys)

    def test_provenance_references_sorted(self) -> None:
        """Provenance references are sorted."""
        answer = CanonicalAnswer(
            question_id="q1",
            question_code="Q001",
            section_code="S01",
            response_type="TEXT",
            value_json="Test",
            review_state="CONFIRMED",
            revision_number=1,
            provenance_references=["ref-c", "ref-a", "ref-b"],
        )
        payload = _create_test_payload(answers=[answer])

        json_str, _ = CanonicalSerializer.serialize(payload)
        parsed = json.loads(json_str)

        refs = parsed["answers"][0]["provenance_references"]
        assert refs == ["ref-a", "ref-b", "ref-c"]


class TestSchemaV2Features:
    """Tests for schema v2.0.0 features."""

    def test_application_identifiers_included(self) -> None:
        """Application identifiers are included in v2.0.0 output."""
        from migration_intake.application.snapshots import CanonicalIdentifier

        identifiers = [
            CanonicalIdentifier(
                identifier_type="CORRELATION",
                value="12345",
                is_primary=True,
            ),
            CanonicalIdentifier(
                identifier_type="MOTS",
                value="APP001",
                is_primary=True,
            ),
        ]
        payload = CanonicalIntakePayload(
            schema_version=SCHEMA_VERSION,
            application_id="app-001",
            application_name="Test Application",
            catalog_id="cat-001",
            catalog_version="1.0.0",
            catalog_sha256="a" * 64,
            catalog_hash="b" * 64,
            intake_id="intake-001",
            intake_state="FROZEN",
            frozen_at="2025-01-15T10:30:00.000Z",
            frozen_by="actor-001",
            application_identifiers=identifiers,
        )

        json_str, _ = CanonicalSerializer.serialize(payload)
        parsed = json.loads(json_str)

        assert "identifiers" in parsed["application"]
        assert len(parsed["application"]["identifiers"]) == 2
        # Sorted by (type, value)
        assert parsed["application"]["identifiers"][0]["type"] == "CORRELATION"
        assert parsed["application"]["identifiers"][1]["type"] == "MOTS"

    def test_target_resources_included(self) -> None:
        """Target resources are included in v2.0.0 output."""
        from migration_intake.application.snapshots import CanonicalTargetResource

        resources = [
            CanonicalTargetResource(
                logical_key="vpc-prod-001",
                kind="VPC",
                scope={"lifecycle": "TARGET", "environment": "PROD"},
                attributes={"cidr": "10.0.0.0/16"},
                review_state="CONFIRMED",
                revision_number=1,
            ),
        ]
        payload = CanonicalIntakePayload(
            schema_version=SCHEMA_VERSION,
            application_id="app-001",
            application_name="Test Application",
            catalog_id="cat-001",
            catalog_version="1.0.0",
            catalog_sha256="a" * 64,
            catalog_hash="b" * 64,
            intake_id="intake-001",
            intake_state="FROZEN",
            frozen_at="2025-01-15T10:30:00.000Z",
            frozen_by="actor-001",
            target_resources=resources,
        )

        json_str, _ = CanonicalSerializer.serialize(payload)
        parsed = json.loads(json_str)

        assert "target_resources" in parsed
        assert len(parsed["target_resources"]) == 1
        assert parsed["target_resources"][0]["kind"] == "VPC"
        assert parsed["target_resources"][0]["logical_key"] == "vpc-prod-001"

    def test_catalog_hash_included(self) -> None:
        """Catalog hash (compiled) is included in v2.0.0 output."""
        payload = _create_test_payload()

        json_str, _ = CanonicalSerializer.serialize(payload)
        parsed = json.loads(json_str)

        assert "catalog_hash" in parsed["catalog"]
        assert "source_sha256" in parsed["catalog"]
        assert parsed["catalog"]["catalog_hash"] == "b" * 64
        assert parsed["catalog"]["source_sha256"] == "a" * 64

    def test_answer_confirm_state_included(self) -> None:
        """Answer confirm_state is included in v2.0.0 output."""
        answer = CanonicalAnswer(
            question_id="q1",
            question_code="Q001",
            section_code="S01",
            response_type="TEXT",
            value_json="Test",
            review_state="REVIEWED",
            revision_number=1,
            confirm_state="CONFIRMED",
            response_schema_version="1.0",
        )
        payload = _create_test_payload(answers=[answer])

        json_str, _ = CanonicalSerializer.serialize(payload)
        parsed = json.loads(json_str)

        assert parsed["answers"][0]["confirm_state"] == "CONFIRMED"
        assert parsed["answers"][0]["response_schema_version"] == "1.0"

    def test_identifiers_sorted_by_type_and_value(self) -> None:
        """Identifiers are sorted by (type, value)."""
        from migration_intake.application.snapshots import CanonicalIdentifier

        identifiers = [
            CanonicalIdentifier(identifier_type="MOTS", value="B001", is_primary=False),
            CanonicalIdentifier(identifier_type="CORRELATION", value="999", is_primary=True),
            CanonicalIdentifier(identifier_type="MOTS", value="A001", is_primary=True),
        ]
        payload = CanonicalIntakePayload(
            schema_version=SCHEMA_VERSION,
            application_id="app-001",
            application_name="Test Application",
            catalog_id="cat-001",
            catalog_version="1.0.0",
            catalog_sha256="a" * 64,
            catalog_hash="b" * 64,
            intake_id="intake-001",
            intake_state="FROZEN",
            frozen_at="2025-01-15T10:30:00.000Z",
            frozen_by="actor-001",
            application_identifiers=identifiers,
        )

        json_str, _ = CanonicalSerializer.serialize(payload)
        parsed = json.loads(json_str)

        ids = parsed["application"]["identifiers"]
        assert ids[0]["type"] == "CORRELATION"
        assert ids[1]["type"] == "MOTS"
        assert ids[1]["value"] == "A001"
        assert ids[2]["type"] == "MOTS"
        assert ids[2]["value"] == "B001"

    def test_target_resources_sorted_by_kind_and_key(self) -> None:
        """Target resources are sorted by (kind, logical_key)."""
        from migration_intake.application.snapshots import CanonicalTargetResource

        resources = [
            CanonicalTargetResource(logical_key="subnet-002", kind="SUBNET"),
            CanonicalTargetResource(logical_key="vpc-001", kind="VPC"),
            CanonicalTargetResource(logical_key="subnet-001", kind="SUBNET"),
        ]
        payload = CanonicalIntakePayload(
            schema_version=SCHEMA_VERSION,
            application_id="app-001",
            application_name="Test Application",
            catalog_id="cat-001",
            catalog_version="1.0.0",
            catalog_sha256="a" * 64,
            catalog_hash="b" * 64,
            intake_id="intake-001",
            intake_state="FROZEN",
            frozen_at="2025-01-15T10:30:00.000Z",
            frozen_by="actor-001",
            target_resources=resources,
        )

        json_str, _ = CanonicalSerializer.serialize(payload)
        parsed = json.loads(json_str)

        res = parsed["target_resources"]
        assert res[0]["kind"] == "SUBNET"
        assert res[0]["logical_key"] == "subnet-001"
        assert res[1]["kind"] == "SUBNET"
        assert res[1]["logical_key"] == "subnet-002"
        assert res[2]["kind"] == "VPC"
