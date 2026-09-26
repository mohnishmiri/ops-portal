"""
Tests for provider-neutral completion contract and provider registry.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import SecretStr, ValidationError


def _settings(**overrides: object):
    """Construct Settings without env side effects."""
    from migration_intake.config import Settings

    data = {
        "app_env": "test",
        "database_url": "",
        "oracle_client_lib_dir": None,
        "db_pool_size": 5,
        "db_max_overflow": 10,
        "db_pool_recycle_seconds": 3600,
        "sql_echo": False,
        "evidence_root": Path(),
        "max_upload_bytes": 100 * 1024 * 1024,
        "max_xlsx_uncompressed_bytes": 500 * 1024 * 1024,
        "max_waveutil_rows": 20_000,
        "actor_id": "00000000-0000-0000-0000-000000000001",
        "actor_display_name": "Test Actor",
        "actor_attuid": None,
        "csrf_secret": SecretStr("test-csrf-secret-minimum-32-characters-long"),
        "catalog_path": None,
        "workbook_contract_version": "APP_DATA_CAPTURE_V1",
        "llm_enabled": True,
        "llm_provider": "openai_compatible",
        "llm_profile": "synthetic-local",
        "llm_outbound_enabled": True,
        "llm_base_url": "https://api.example.com",
        "llm_model": "test-model",
        "llm_auth_mode": "bearer_token",
        "llm_api_token": SecretStr("test-token"),
        "llm_allowed_classifications_raw": "SYNTHETIC",
        "llm_connect_timeout_seconds": 10,
        "llm_read_timeout_seconds": 60,
        "llm_max_attempts": 3,
        "llm_max_response_bytes": 10 * 1024 * 1024,
        "llm_max_fragment_chars": 12_000,
        "llm_max_requests_per_import": 20,
        "log_level": "INFO",
        "log_format": "human",
    }
    data.update(overrides)
    return Settings.model_construct(**data)


class TestStructuredCompletionContract:
    def test_request_accepts_valid_sha256_hash(self) -> None:
        from migration_intake.ai.completion import StructuredCompletionRequest

        request = StructuredCompletionRequest(
            request_id="r1",
            correlation_id="corr-1",
            provider_id="openai_compatible",
            model_id="test-model",
            system_instruction="Return JSON only.",
            user_content="Extract values.",
            classification="SYNTHETIC",
            prompt_template_version="v1.0",
            request_content_hash="a" * 64,
        )
        assert request.request_content_hash == "a" * 64

    def test_request_rejects_non_sha256_hash(self) -> None:
        from migration_intake.ai.completion import StructuredCompletionRequest

        with pytest.raises(ValidationError, match="request_content_hash"):
            StructuredCompletionRequest(
                request_id="r1",
                correlation_id="corr-1",
                provider_id="openai_compatible",
                model_id="test-model",
                system_instruction="Return JSON only.",
                user_content="Extract values.",
                classification="SYNTHETIC",
                prompt_template_version="v1.0",
                request_content_hash="not-a-hash",
            )

    def test_response_rejects_non_sha256_hash(self) -> None:
        from migration_intake.ai.completion import StructuredCompletionResponse

        with pytest.raises(ValidationError, match="response_hash"):
            StructuredCompletionResponse(
                provider_id="openai_compatible",
                model_id="test-model",
                finish_reason="stop",
                attempt_count=1,
                latency_bucket="<=250ms",
                normalized_content='{"ok": true}',
                response_hash="bad",
                validation_status="VALID",
            )

    def test_models_are_immutable(self) -> None:
        from migration_intake.ai.completion import StructuredCompletionRequest

        request = StructuredCompletionRequest(
            request_id="r1",
            correlation_id="corr-1",
            provider_id="openai_compatible",
            model_id="test-model",
            system_instruction="Return JSON only.",
            user_content="Extract values.",
            classification="SYNTHETIC",
            prompt_template_version="v1.0",
            request_content_hash="b" * 64,
        )
        with pytest.raises(ValidationError):
            request.model_id = "other-model"  # type: ignore[misc]


class TestProviderRegistry:
    def test_disabled_client_when_llm_disabled(self) -> None:
        from migration_intake.ai.completion import StructuredCompletionRequest
        from migration_intake.ai.errors import OutboundAIDisabledError
        from migration_intake.ai.provider_registry import build_structured_completion_client

        client = build_structured_completion_client(_settings(llm_enabled=False))
        request = StructuredCompletionRequest(
            request_id="r1",
            correlation_id="corr-1",
            provider_id="openai_compatible",
            model_id="test-model",
            system_instruction="Return JSON only.",
            user_content="Extract values.",
            classification="SYNTHETIC",
            prompt_template_version="v1.0",
            request_content_hash="c" * 64,
        )
        with pytest.raises(OutboundAIDisabledError):
            client.complete(request)

    def test_disabled_client_when_outbound_disabled(self) -> None:
        from migration_intake.ai.completion import StructuredCompletionRequest
        from migration_intake.ai.errors import OutboundAIDisabledError
        from migration_intake.ai.provider_registry import build_structured_completion_client

        client = build_structured_completion_client(
            _settings(llm_enabled=True, llm_outbound_enabled=False)
        )
        request = StructuredCompletionRequest(
            request_id="r1",
            correlation_id="corr-1",
            provider_id="openai_compatible",
            model_id="test-model",
            system_instruction="Return JSON only.",
            user_content="Extract values.",
            classification="SYNTHETIC",
            prompt_template_version="v1.0",
            request_content_hash="d" * 64,
        )
        with pytest.raises(OutboundAIDisabledError):
            client.complete(request)

    def test_unregistered_provider_raises(self) -> None:
        from migration_intake.ai.errors import ProviderNotRegisteredError
        from migration_intake.ai.provider_registry import (
            ProviderRegistry,
            build_structured_completion_client,
        )

        settings = _settings(llm_provider="anthropic")
        with pytest.raises(ProviderNotRegisteredError):
            build_structured_completion_client(settings, registry=ProviderRegistry())

    def test_registered_factory_is_used(self) -> None:
        from migration_intake.ai.completion import (
            StructuredCompletionClient,
            StructuredCompletionRequest,
            StructuredCompletionResponse,
        )
        from migration_intake.ai.provider_registry import (
            ProviderRegistry,
            build_structured_completion_client,
        )

        class _FakeClient:
            def complete(
                self,
                request: StructuredCompletionRequest,
            ) -> StructuredCompletionResponse:
                return StructuredCompletionResponse(
                    provider_id="openai_compatible",
                    model_id=request.model_id,
                    provider_request_id="req-1",
                    finish_reason="stop",
                    attempt_count=1,
                    latency_bucket="<=250ms",
                    normalized_content='{"proposed_mappings":[]}',
                    response_hash="e" * 64,
                    validation_status="VALID",
                )

        registry = ProviderRegistry()
        registry.register("openai_compatible", lambda _settings: _FakeClient())
        client = build_structured_completion_client(_settings(), registry=registry)
        assert isinstance(client, StructuredCompletionClient)
