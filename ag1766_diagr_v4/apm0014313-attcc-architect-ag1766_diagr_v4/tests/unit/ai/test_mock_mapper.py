"""
Tests for MockCandidateMapper.

These tests verify:
- MockCandidateMapper returns MappingResult for a valid request
- Results include all required fields
- Only maps questions defined in question_definitions
- Grounding quotes exist in source_fragment
- Same input always produces same output (deterministic)
- model_metadata contains no credentials
- Provider is identified as 'mock'
- raw_response_hash is a valid SHA-256 hex string
- MockCandidateMapper satisfies the CandidateMapper protocol
"""

from __future__ import annotations

import uuid

import pytest


def _make_request(**overrides: object) -> object:
    """Build a MappingRequest with sensible defaults."""
    from migration_intake.ai.models import MappingRequest

    base: dict = dict(
        request_id=str(uuid.uuid4()),
        source_fragment=(
            "The application runs on Linux with 16 GB RAM and requires Oracle DB."
        ),
        source_locator="Sheet:APP_DATA/Row:5/Col:B",
        source_type="workbook_app_sheet",
        application_scope="app_linux_oracle",
        question_definitions=[
            {"id": "os_type", "label": "Operating System"},
            {"id": "ram_gb", "label": "RAM GB"},
        ],
        response_schemas=[
            {"question_id": "os_type", "type": "scalar"},
            {"question_id": "ram_gb", "type": "measurement"},
        ],
        allowed_values={
            "os_type": ["LINUX", "WINDOWS", "UNKNOWN"],
            "ram_gb": ["UNKNOWN"],
        },
        prompt_template_version="v1.0",
    )
    base.update(overrides)
    return MappingRequest(**base)


class TestMockCandidateMapper:
    """Tests for MockCandidateMapper."""

    def test_returns_mapping_result(self) -> None:
        """MockCandidateMapper.map should return a MappingResult."""
        from migration_intake.ai.mock import MockCandidateMapper
        from migration_intake.ai.models import MappingResult

        mapper = MockCandidateMapper()
        result = mapper.map(_make_request())

        assert isinstance(result, MappingResult)

    def test_result_request_id_matches(self) -> None:
        """MappingResult.request_id should match the originating request."""
        from migration_intake.ai.mock import MockCandidateMapper

        request = _make_request()
        mapper = MockCandidateMapper()
        result = mapper.map(request)

        assert result.request_id == request.request_id

    def test_provider_is_mock(self) -> None:
        """MockCandidateMapper.provider should be 'mock'."""
        from migration_intake.ai.mock import MockCandidateMapper

        mapper = MockCandidateMapper()
        result = mapper.map(_make_request())

        assert result.provider == "mock"

    def test_raw_response_hash_is_sha256_hex(self) -> None:
        """raw_response_hash should be a 64-character lowercase hex string."""
        from migration_intake.ai.mock import MockCandidateMapper

        mapper = MockCandidateMapper()
        result = mapper.map(_make_request())

        assert len(result.raw_response_hash) == 64
        assert all(c in "0123456789abcdef" for c in result.raw_response_hash)

    def test_only_maps_defined_questions(self) -> None:
        """MockCandidateMapper must not produce mappings for undefined questions."""
        from migration_intake.ai.mock import MockCandidateMapper

        request = _make_request(
            question_definitions=[
                {"id": "os_type", "label": "Operating System"},
            ]
        )
        mapper = MockCandidateMapper()
        result = mapper.map(request)

        defined_ids = {q["id"] for q in request.question_definitions}
        mapped_ids = {m.question_id for m in result.proposed_mappings}
        assert mapped_ids.issubset(defined_ids)

    def test_grounding_quotes_are_substrings_of_source_fragment(self) -> None:
        """Every grounding_quote in proposed_mappings must appear in source_fragment."""
        from migration_intake.ai.mock import MockCandidateMapper

        request = _make_request()
        mapper = MockCandidateMapper()
        result = mapper.map(request)

        for mapping in result.proposed_mappings:
            assert mapping.grounding_quote in request.source_fragment, (
                f"grounding_quote {mapping.grounding_quote!r} not found in source_fragment"
            )

    def test_deterministic_output(self) -> None:
        """Same input must always produce the same output."""
        from migration_intake.ai.mock import MockCandidateMapper

        request = _make_request(request_id="00000000-0000-0000-0000-000000000001")
        mapper = MockCandidateMapper()

        result1 = mapper.map(request)
        result2 = mapper.map(request)

        assert result1.proposed_mappings == result2.proposed_mappings
        assert result1.raw_response_hash == result2.raw_response_hash

    def test_validation_status_is_recognised_value(self) -> None:
        """validation_status must be one of the three recognised values."""
        from migration_intake.ai.mock import MockCandidateMapper

        mapper = MockCandidateMapper()
        result = mapper.map(_make_request())

        assert result.validation_status in ("VALID", "GROUNDING_FAILED", "SCHEMA_FAILED")

    def test_model_metadata_contains_no_credentials(self) -> None:
        """model_metadata must not contain credentials, tokens, keys, or secrets."""
        from migration_intake.ai.mock import MockCandidateMapper

        mapper = MockCandidateMapper()
        result = mapper.map(_make_request())

        meta_str = str(result.model_metadata).lower()
        assert "token" not in meta_str
        assert "secret" not in meta_str
        assert "password" not in meta_str

    def test_satisfies_candidate_mapper_protocol(self) -> None:
        """MockCandidateMapper must satisfy the CandidateMapper Protocol."""
        from migration_intake.ai.mock import MockCandidateMapper
        from migration_intake.ai.port import CandidateMapper

        mapper = MockCandidateMapper()
        assert isinstance(mapper, CandidateMapper)

    def test_proposed_mapping_source_locator_from_request(self) -> None:
        """ProposedMapping.source_locator should be copied from the request."""
        from migration_intake.ai.mock import MockCandidateMapper

        request = _make_request()
        mapper = MockCandidateMapper()
        result = mapper.map(request)

        for mapping in result.proposed_mappings:
            assert mapping.source_locator == request.source_locator

    def test_result_has_grounding_quotes_list(self) -> None:
        """MappingResult.grounding_quotes should be a list of strings."""
        from migration_intake.ai.mock import MockCandidateMapper

        mapper = MockCandidateMapper()
        result = mapper.map(_make_request())

        assert isinstance(result.grounding_quotes, list)
        for quote in result.grounding_quotes:
            assert isinstance(quote, str)

    def test_result_has_warnings_list(self) -> None:
        """MappingResult.warnings should be a list."""
        from migration_intake.ai.mock import MockCandidateMapper

        mapper = MockCandidateMapper()
        result = mapper.map(_make_request())

        assert isinstance(result.warnings, list)

    def test_result_has_unmapped_fragments_list(self) -> None:
        """MappingResult.unmapped_fragments should be a list."""
        from migration_intake.ai.mock import MockCandidateMapper

        mapper = MockCandidateMapper()
        result = mapper.map(_make_request())

        assert isinstance(result.unmapped_fragments, list)
