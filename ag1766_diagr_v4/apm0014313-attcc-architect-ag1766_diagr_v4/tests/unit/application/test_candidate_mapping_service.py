"""
Tests for CandidateMappingService (PAI-4).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

import pytest

from migration_intake.ai.models import MappingResult, ProposedMapping
from migration_intake.application.services.candidate_mapping import (
    CandidateMappingCommand,
    CandidateMappingPolicyError,
    CandidateMappingService,
    CandidateMappingValidationError,
    MappingFragment,
)


@dataclass
class _FakeMapper:
    result: MappingResult

    def map(self, request):
        return self.result.model_copy(update={"request_id": request.request_id})


@dataclass
class _FakeStagingPort:
    calls: list[dict]

    def stage_mapping_batch(self, **kwargs):
        self.calls.append(kwargs)


def _result() -> MappingResult:
    mapping = ProposedMapping(
        question_id="os_type",
        proposed_value={"value": "LINUX"},
        confidence_metadata={"signal": "test"},
        grounding_quote="Linux",
        source_locator="Sheet:APP/Row:2/Col:B",
    )
    return MappingResult(
        request_id=str(uuid.uuid4()),
        provider="mock",
        model_metadata={"provider": "mock"},
        proposed_mappings=[mapping],
        unmapped_fragments=[],
        warnings=[],
        grounding_quotes=["Linux"],
        raw_response_hash="a" * 64,
        validation_status="VALID",
    )


def _command(*, fragment_text: str = "Linux host") -> CandidateMappingCommand:
    return CandidateMappingCommand(
        application_id="app-1",
        intake_id="intake-1",
        evidence_item_id="evidence-1",
        import_run_id="run-1",
        actor_id="actor-1",
        prompt_template_version="v1.0",
        fragments=(
            MappingFragment(
                source_fragment=fragment_text,
                source_locator="Sheet:APP/Row:2/Col:B",
                source_type="workbook_app_sheet",
            ),
        ),
        question_definitions=({"id": "os_type", "label": "OS"},),
        response_schemas=({"question_id": "os_type", "type": "TEXT"},),
        allowed_values={"os_type": ["LINUX", "WINDOWS"]},
    )


class TestCandidateMappingService:
    def test_stages_valid_candidate_batch(self) -> None:
        staging = _FakeStagingPort(calls=[])
        service = CandidateMappingService(
            mapper=_FakeMapper(result=_result()),
            staging_port=staging,
            max_fragment_chars=12_000,
            max_requests_per_import=20,
        )

        outcome = service.run(_command(fragment_text="Linux host"))

        assert outcome.mapping_request_count == 1
        assert outcome.staged_candidate_count == 1
        assert len(staging.calls) == 1
        call = staging.calls[0]
        assert call["proposals"][0]["target_kind"] == "QUESTION"
        assert call["proposals"][0]["target_key"] == "os_type"

    def test_rejects_too_many_fragments(self) -> None:
        staging = _FakeStagingPort(calls=[])
        service = CandidateMappingService(
            mapper=_FakeMapper(result=_result()),
            staging_port=staging,
            max_fragment_chars=12_000,
            max_requests_per_import=1,
        )
        command = CandidateMappingCommand(
            **{
                **_command().__dict__,
                "fragments": (
                    MappingFragment("Linux", "Sheet:1", "sheet"),
                    MappingFragment("Oracle", "Sheet:2", "sheet"),
                ),
            }
        )
        with pytest.raises(CandidateMappingPolicyError, match="max requests per import"):
            service.run(command)

    def test_rejects_oversized_fragment(self) -> None:
        staging = _FakeStagingPort(calls=[])
        service = CandidateMappingService(
            mapper=_FakeMapper(result=_result()),
            staging_port=staging,
            max_fragment_chars=5,
            max_requests_per_import=20,
        )
        with pytest.raises(CandidateMappingPolicyError, match="max fragment chars"):
            service.run(_command(fragment_text="Linux host"))

    def test_rejects_unknown_question_id_from_mapper(self) -> None:
        staging = _FakeStagingPort(calls=[])
        bad = _result()
        bad_mapping = bad.proposed_mappings[0].model_copy(update={"question_id": "unknown"})
        bad = bad.model_copy(update={"proposed_mappings": [bad_mapping]})
        service = CandidateMappingService(
            mapper=_FakeMapper(result=bad),
            staging_port=staging,
            max_fragment_chars=12_000,
            max_requests_per_import=20,
        )
        with pytest.raises(CandidateMappingValidationError, match="unknown question_id"):
            service.run(_command(fragment_text="Linux host"))

    def test_rejects_non_verbatim_grounding_quote(self) -> None:
        staging = _FakeStagingPort(calls=[])
        bad = _result()
        bad_mapping = bad.proposed_mappings[0].model_copy(update={"grounding_quote": "Solaris"})
        bad = bad.model_copy(update={"proposed_mappings": [bad_mapping]})
        service = CandidateMappingService(
            mapper=_FakeMapper(result=bad),
            staging_port=staging,
            max_fragment_chars=12_000,
            max_requests_per_import=20,
        )
        with pytest.raises(CandidateMappingValidationError, match="grounding_quote"):
            service.run(_command(fragment_text="Linux host"))
