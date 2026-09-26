"""
Security policy tests for the OpenAI-compatible adapter.

All tests are pure-Python (no network). They verify that the multi-gate
guard prevents accidental or malicious network calls from:
- Default settings (LLM disabled)
- HTTP base URLs
- Missing token or model
- Non-SYNTHETIC request classifications
- Mock provider (must not delegate to the OpenAI adapter)

Token values are never expected in exception messages.
"""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest
from pydantic import SecretStr


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _make_minimal_settings(**overrides: object):
    """
    Build a Settings instance via model_construct (bypasses env/validator).
    Only the fields in ``overrides`` deviate from the secure defaults.
    """
    from migration_intake.config import Settings

    base: dict = dict(
        app_env="test",
        evidence_root=Path("."),
        actor_id="00000000-0000-0000-0000-000000000001",
        actor_display_name="Test Actor",
        actor_attuid=None,
        csrf_secret=SecretStr("test-csrf-secret-minimum-32-chars-long"),
        database_url="",
        db_pool_size=5,
        db_max_overflow=10,
        db_pool_recycle_seconds=3600,
        sql_echo=False,
        max_upload_bytes=100 * 1024 * 1024,
        max_xlsx_uncompressed_bytes=500 * 1024 * 1024,
        max_waveutil_rows=20_000,
        llm_provider="openai_compatible",
        llm_profile="synthetic-local",
        llm_outbound_enabled=False,
        llm_enabled=False,
        llm_base_url="https://api.example.com",
        llm_model="test-model",
        llm_auth_mode="bearer_token",
        llm_api_token=SecretStr("test-token"),
        llm_allowed_classifications_raw="SYNTHETIC",
        llm_connect_timeout_seconds=10,
        llm_read_timeout_seconds=60,
        llm_max_attempts=3,
        llm_max_response_bytes=10 * 1024 * 1024,
        llm_max_fragment_chars=12_000,
        llm_max_requests_per_import=20,
        log_level="INFO",
        log_format="human",
        catalog_path=None,
        workbook_contract_version="APP_DATA_CAPTURE_V1",
    )
    base.update(overrides)
    return Settings.model_construct(**base)


def _make_synthetic_request(**overrides: object):
    """Build a minimal synthetic MappingRequest."""
    from migration_intake.ai.models import MappingRequest

    base: dict = dict(
        request_id=str(uuid.uuid4()),
        source_fragment="Linux with Oracle DB — synthetic fixture",
        source_locator="Sheet:TEST/Row:1",
        source_type="workbook_app_sheet",
        application_scope="synthetic_test_app",
        question_definitions=[{"id": "os_type", "label": "OS"}],
        response_schemas=[{"question_id": "os_type", "type": "scalar"}],
        allowed_values={"os_type": ["LINUX"]},
        prompt_template_version="v1.0",
        classification="SYNTHETIC",
    )
    base.update(overrides)
    return MappingRequest(**base)


# ---------------------------------------------------------------------------
# Security tests
# ---------------------------------------------------------------------------


class TestAISecurityPolicy:
    """Security-policy gate tests; no network calls in any test."""

    def test_llm_disabled_by_default(self) -> None:
        """Default Settings has llm_enabled=False → AdapterGateError before any network."""
        from migration_intake.ai.openai_compatible import AdapterGateError, OpenAICompatibleMapper

        settings = _make_minimal_settings(llm_enabled=False)
        mapper = OpenAICompatibleMapper(settings, _allow_http_for_testing=True)

        with pytest.raises(AdapterGateError):
            mapper.map_candidates(_make_synthetic_request())

    def test_http_base_url_rejected(self) -> None:
        """HTTP base_url → AdapterGateError even if llm_enabled=True."""
        from migration_intake.ai.openai_compatible import AdapterGateError, OpenAICompatibleMapper

        # _allow_http_for_testing NOT set (default False) → HTTPS gate active
        settings = _make_minimal_settings(
            llm_enabled=True,
            llm_base_url="http://api.example.com",
        )
        mapper = OpenAICompatibleMapper(settings)  # no bypass

        with pytest.raises(AdapterGateError):
            mapper.map_candidates(_make_synthetic_request())

    def test_missing_token_rejected(self) -> None:
        """Empty/None token → AdapterGateError before any network."""
        from migration_intake.ai.openai_compatible import AdapterGateError, OpenAICompatibleMapper

        settings = _make_minimal_settings(
            llm_enabled=True,
            llm_api_token=None,
        )
        mapper = OpenAICompatibleMapper(settings, _allow_http_for_testing=True)

        with pytest.raises(AdapterGateError):
            mapper.map_candidates(_make_synthetic_request())

    def test_missing_model_rejected(self) -> None:
        """Empty model → AdapterGateError before any network."""
        from migration_intake.ai.openai_compatible import AdapterGateError, OpenAICompatibleMapper

        settings = _make_minimal_settings(
            llm_enabled=True,
            llm_model=None,
        )
        mapper = OpenAICompatibleMapper(settings, _allow_http_for_testing=True)

        with pytest.raises(AdapterGateError):
            mapper.map_candidates(_make_synthetic_request())

    def test_client_evidence_prohibited(self) -> None:
        """classification != 'SYNTHETIC' → AdapterGateError; client evidence blocked."""
        from migration_intake.ai.openai_compatible import AdapterGateError, OpenAICompatibleMapper

        settings = _make_minimal_settings(llm_enabled=True)
        mapper = OpenAICompatibleMapper(settings, _allow_http_for_testing=True)

        non_synthetic = _make_synthetic_request(classification="CLIENT")

        with pytest.raises(AdapterGateError):
            mapper.map_candidates(non_synthetic)

    def test_mock_provider_does_not_use_openai_adapter(self) -> None:
        """MockCandidateMapper makes no HTTP calls even if LLM_ENABLED=True."""
        import unittest.mock

        from migration_intake.ai.mock import MockCandidateMapper
        from migration_intake.ai.models import MappingResult

        mapper = MockCandidateMapper()

        # Patch httpx.Client to catch any accidental network call
        with unittest.mock.patch("httpx.Client") as mock_client_cls:
            result = mapper.map(_make_synthetic_request())

        mock_client_cls.assert_not_called()
        assert isinstance(result, MappingResult)
        assert result.provider == "mock"

    def test_provider_name_alone_does_not_enable_network(self) -> None:
        """provider='openai_compatible' but llm_enabled=False → still AdapterGateError."""
        from migration_intake.ai.openai_compatible import AdapterGateError, OpenAICompatibleMapper

        settings = _make_minimal_settings(
            llm_provider="openai_compatible",
            llm_enabled=False,
        )
        mapper = OpenAICompatibleMapper(settings, _allow_http_for_testing=True)

        with pytest.raises(AdapterGateError):
            mapper.map_candidates(_make_synthetic_request())

    def test_token_not_in_exception_message(self) -> None:
        """When the auth gate raises, the exception message contains no secret value."""
        from migration_intake.ai.openai_compatible import AdapterGateError, OpenAICompatibleMapper

        secret = "super-secret-api-token-12345"
        settings = _make_minimal_settings(
            llm_enabled=False,
            llm_api_token=SecretStr(secret),
        )
        mapper = OpenAICompatibleMapper(settings, _allow_http_for_testing=True)

        with pytest.raises(AdapterGateError) as exc_info:
            mapper.map_candidates(_make_synthetic_request())

        assert secret not in str(exc_info.value)

    def test_http_redirect_to_https_is_rejected(self) -> None:
        """Any attempt to call HTTP base_url raises before connection, not after redirect."""
        from migration_intake.ai.openai_compatible import AdapterGateError, OpenAICompatibleMapper

        # Without the testing bypass, HTTP should be rejected at gate-check time,
        # not after a connection attempt or after following a redirect.
        settings = _make_minimal_settings(
            llm_enabled=True,
            llm_base_url="http://example.com",
        )
        mapper = OpenAICompatibleMapper(settings)  # no _allow_http_for_testing

        import unittest.mock

        with unittest.mock.patch("httpx.Client") as mock_client_cls:
            with pytest.raises(AdapterGateError):
                mapper.map_candidates(_make_synthetic_request())

        # httpx must never have been instantiated
        mock_client_cls.assert_not_called()
