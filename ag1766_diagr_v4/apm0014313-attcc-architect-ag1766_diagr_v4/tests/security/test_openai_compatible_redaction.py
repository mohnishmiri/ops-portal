"""
Security tests for OpenAI-compatible completion adapter redaction/gating.
"""

from __future__ import annotations

from pathlib import Path
from typing import ClassVar
from unittest.mock import patch

import pytest
from pydantic import SecretStr

from migration_intake.ai.completion import StructuredCompletionRequest
from migration_intake.ai.errors import OutboundAIDisabledError, ProviderAuthError
from migration_intake.ai.providers.openai_compatible import OpenAICompatibleCompletionClient
from migration_intake.config import Settings


def _settings(**overrides: object) -> Settings:
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
        "llm_api_token": SecretStr("super-secret-token-value"),
        "llm_allowed_classifications_raw": "SYNTHETIC",
        "llm_connect_timeout_seconds": 2,
        "llm_read_timeout_seconds": 2,
        "llm_max_attempts": 1,
        "llm_max_response_bytes": 1024,
        "llm_max_fragment_chars": 12_000,
        "llm_max_requests_per_import": 20,
        "log_level": "INFO",
        "log_format": "human",
    }
    data.update(overrides)
    return Settings.model_construct(**data)


def _request(classification: str = "SYNTHETIC") -> StructuredCompletionRequest:
    return StructuredCompletionRequest(
        request_id="req-1",
        correlation_id="corr-1",
        provider_id="openai_compatible",
        model_id="test-model",
        system_instruction="Return JSON only.",
        user_content="Extract.",
        classification=classification,
        prompt_template_version="v1.0",
        request_content_hash="f" * 64,
    )


def test_http_base_url_rejected_before_network_call() -> None:
    settings = _settings(llm_base_url="http://insecure.example.com")
    client = OpenAICompatibleCompletionClient(settings)

    with patch("httpx.Client") as httpx_client, pytest.raises(
        OutboundAIDisabledError, match="HTTPS is required"
    ):
        client.complete(_request())
    httpx_client.assert_not_called()


def test_disallowed_classification_blocked_before_network_call() -> None:
    settings = _settings(llm_allowed_classifications_raw="SYNTHETIC")
    client = OpenAICompatibleCompletionClient(settings)

    with patch("httpx.Client") as httpx_client, pytest.raises(
        OutboundAIDisabledError, match="not allowed by policy"
    ):
        client.complete(_request(classification="CLIENT"))
    httpx_client.assert_not_called()


def test_missing_token_error_does_not_leak_secret_value() -> None:
    secret_value = "my-secret-token"  # noqa: S105 - synthetic test secret
    settings = _settings(llm_api_token=SecretStr(secret_value), llm_enabled=False)
    client = OpenAICompatibleCompletionClient(settings)

    with pytest.raises(OutboundAIDisabledError) as exc_info:
        client.complete(_request())

    assert secret_value not in str(exc_info.value)


def test_auth_error_message_does_not_include_token() -> None:
    settings = _settings()
    client = OpenAICompatibleCompletionClient(settings)

    class _FakeResponse:
        status_code = 401
        content = b"{}"
        headers: ClassVar[dict] = {}

        @staticmethod
        def json():
            return {}

    class _FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def post(self, *_args, **_kwargs):
            return _FakeResponse()

    with patch("httpx.Client", _FakeClient), pytest.raises(
        ProviderAuthError
    ) as exc_info:
        client.complete(_request())
    assert "super-secret-token-value" not in str(exc_info.value)
