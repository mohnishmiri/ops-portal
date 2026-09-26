"""
Tests for ProviderBackedCandidateMapper and factory integration.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import SecretStr

from migration_intake.ai.candidate_mapper import build_candidate_mapper
from migration_intake.ai.candidate_mapper_provider import ProviderBackedCandidateMapper
from migration_intake.ai.completion import StructuredCompletionResponse
from migration_intake.ai.models import MappingRequest
from migration_intake.config import Settings


class _FakeCompletionClient:
    def complete(self, request):
        _ = request
        return StructuredCompletionResponse(
            provider_id="openai_compatible",
            model_id="test-model",
            provider_request_id="req-123",
            finish_reason="stop",
            attempt_count=1,
            latency_bucket="<=250ms",
            normalized_content=(
                '{"proposed_mappings":[{"question_id":"os_type","proposed_value":{"value":"LINUX"},'
                '"grounding_quote":"Linux"}],"warnings":[],"unmapped_fragments":[]}'
            ),
            response_hash="a" * 64,
            validation_status="VALID",
        )


def _request() -> MappingRequest:
    return MappingRequest(
        request_id="req-1",
        source_fragment="Linux host",
        source_locator="Manual:AI/Row:1",
        source_type="manual_text",
        application_scope="app-1",
        question_definitions=[{"id": "os_type", "label": "OS"}],
        response_schemas=[{"question_id": "os_type", "response_type": "TEXT"}],
        allowed_values={"os_type": ["LINUX"]},
        prompt_template_version="v1.0",
        classification="SYNTHETIC",
    )


def _settings(**overrides: object) -> Settings:
    base = {
        "app_env": "test",
        "database_url": "",
        "evidence_root": Path(),
        "actor_id": "00000000-0000-0000-0000-000000000001",
        "actor_display_name": "Test Actor",
        "csrf_secret": SecretStr("test-csrf-secret-minimum-32-chars-long"),
        "llm_provider": "openai_compatible",
        "llm_enabled": True,
        "llm_outbound_enabled": True,
        "llm_base_url": "https://api.example.com",
        "llm_model": "test-model",
        "llm_auth_mode": "bearer_token",
        "llm_api_token": SecretStr("test-token"),
        "llm_allowed_classifications_raw": "SYNTHETIC",
    }
    base.update(overrides)
    return Settings.model_construct(**base)


def test_provider_backed_mapper_parses_valid_json() -> None:
    mapper = ProviderBackedCandidateMapper(
        completion_client=_FakeCompletionClient(),
        provider_id="openai_compatible",
        model_id="test-model",
    )
    result = mapper.map(_request())
    assert result.provider == "openai_compatible"
    assert len(result.proposed_mappings) == 1
    assert result.proposed_mappings[0].question_id == "os_type"


def test_factory_builds_provider_backed_mapper_for_openai_profile() -> None:
    mapper = build_candidate_mapper(_settings())
    assert isinstance(mapper, ProviderBackedCandidateMapper)
