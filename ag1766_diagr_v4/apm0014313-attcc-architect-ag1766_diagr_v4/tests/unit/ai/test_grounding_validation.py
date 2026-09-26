"""
Tests for grounding validation in the AI layer.

These tests verify:
- validate_grounding returns True when the quote is a non-empty substring
- validate_grounding returns False for an empty grounding quote
- validate_grounding returns False when the quote is not in the fragment
- validate_grounding returns False when source_fragment is empty
- MockCandidateMapper only maps questions present in question_definitions
- ProposedMapping.proposed_value has non-empty content
- MappingResult.validation_status is GROUNDING_FAILED when no quote is found
"""

from __future__ import annotations

import uuid

import pytest


def _make_request(
    source_fragment: str,
    question_definitions: list[dict],
    allowed_values: dict | None = None,
    **overrides: object,
) -> object:
    """Build a MappingRequest with caller-supplied fragment and definitions."""
    from migration_intake.ai.models import MappingRequest

    base: dict = dict(
        request_id=str(uuid.uuid4()),
        source_fragment=source_fragment,
        source_locator="Sheet:APP_DATA/Row:5/Col:B",
        source_type="workbook_app_sheet",
        application_scope="test_app",
        question_definitions=question_definitions,
        response_schemas=[],
        allowed_values=allowed_values or {},
        prompt_template_version="v1.0",
    )
    base.update(overrides)
    return MappingRequest(**base)


class TestGroundingValidation:
    """Tests for the validate_grounding helper function."""

    def test_returns_true_for_exact_substring(self) -> None:
        """validate_grounding should return True when quote is in fragment."""
        from migration_intake.ai.mock import validate_grounding

        assert (
            validate_grounding(
                grounding_quote="runs on Linux",
                source_fragment="Application runs on Linux with 8 GB RAM.",
            )
            is True
        )

    def test_returns_false_when_quote_absent(self) -> None:
        """validate_grounding should return False when quote is not in fragment."""
        from migration_intake.ai.mock import validate_grounding

        assert (
            validate_grounding(
                grounding_quote="runs on Windows",
                source_fragment="Application runs on Linux with 8 GB RAM.",
            )
            is False
        )

    def test_returns_false_for_empty_grounding_quote(self) -> None:
        """validate_grounding should return False for an empty quote."""
        from migration_intake.ai.mock import validate_grounding

        assert validate_grounding(grounding_quote="", source_fragment="some text") is False

    def test_returns_false_for_empty_source_fragment(self) -> None:
        """validate_grounding should return False when source_fragment is empty."""
        from migration_intake.ai.mock import validate_grounding

        assert validate_grounding(grounding_quote="text", source_fragment="") is False

    def test_exact_full_match_is_valid(self) -> None:
        """validate_grounding should accept a quote equal to the full fragment."""
        from migration_intake.ai.mock import validate_grounding

        fragment = "Oracle DB version 19c is required."
        assert (
            validate_grounding(grounding_quote=fragment, source_fragment=fragment) is True
        )

    def test_single_word_quote_is_valid(self) -> None:
        """validate_grounding should accept a single word that appears in fragment."""
        from migration_intake.ai.mock import validate_grounding

        assert (
            validate_grounding(
                grounding_quote="Oracle",
                source_fragment="Requires Oracle DB.",
            )
            is True
        )


class TestMockMapperGrounding:
    """Tests for grounding behaviour in MockCandidateMapper."""

    def test_all_quotes_are_substrings_of_source(self) -> None:
        """Every grounding_quote from mock mappings must appear in source_fragment."""
        from migration_intake.ai.mock import MockCandidateMapper

        source = "Application runs on Linux with 8 GB RAM."
        request = _make_request(
            source_fragment=source,
            question_definitions=[{"id": "os_type", "label": "OS"}],
            allowed_values={"os_type": ["LINUX", "UNKNOWN"]},
        )
        mapper = MockCandidateMapper()
        result = mapper.map(request)

        for mapping in result.proposed_mappings:
            assert mapping.grounding_quote in source

    def test_question_not_in_definitions_not_mapped(self) -> None:
        """MockCandidateMapper must not produce mappings for unlisted questions."""
        from migration_intake.ai.mock import MockCandidateMapper

        request = _make_request(
            source_fragment="Application runs on Linux.",
            question_definitions=[{"id": "os_type", "label": "OS"}],
        )
        mapper = MockCandidateMapper()
        result = mapper.map(request)

        mapped_ids = {m.question_id for m in result.proposed_mappings}
        for qid in mapped_ids:
            assert qid == "os_type", f"Unexpected question_id {qid!r} in mappings"

    def test_grounding_failed_when_no_keyword_in_fragment(self) -> None:
        """validation_status should be GROUNDING_FAILED when source has no matching keyword."""
        from migration_intake.ai.mock import MockCandidateMapper

        # Fragment contains no OS-related keywords
        request = _make_request(
            source_fragment="This fragment contains no relevant keywords at all.",
            question_definitions=[{"id": "os_type", "label": "OS"}],
            allowed_values={"os_type": ["LINUX", "UNKNOWN"]},
        )
        mapper = MockCandidateMapper()
        result = mapper.map(request)

        assert result.validation_status == "GROUNDING_FAILED"
        assert result.proposed_mappings == []

    def test_proposed_value_has_non_empty_content(self) -> None:
        """ProposedMapping.proposed_value must be a non-empty dict."""
        from migration_intake.ai.mock import MockCandidateMapper

        request = _make_request(
            source_fragment="Application runs on Linux.",
            question_definitions=[{"id": "os_type", "label": "OS"}],
            allowed_values={"os_type": ["LINUX", "UNKNOWN"]},
        )
        mapper = MockCandidateMapper()
        result = mapper.map(request)

        for mapping in result.proposed_mappings:
            assert isinstance(mapping.proposed_value, dict)
            assert len(mapping.proposed_value) > 0

    def test_unknown_question_id_skipped_with_warning(self) -> None:
        """Questions with no fixture should produce a warning and no mapping."""
        from migration_intake.ai.mock import MockCandidateMapper

        request = _make_request(
            source_fragment="Some text about the application environment.",
            question_definitions=[{"id": "nonexistent_question_xyz", "label": "Unknown"}],
        )
        mapper = MockCandidateMapper()
        result = mapper.map(request)

        assert result.proposed_mappings == []
        assert len(result.warnings) > 0
