"""
Integration tests for the provider-neutral OpenAI-compatible completion client.
"""

from __future__ import annotations

import json
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from pydantic import SecretStr

from migration_intake.ai.completion import StructuredCompletionRequest
from migration_intake.ai.providers.openai_compatible import OpenAICompatibleCompletionClient
from migration_intake.config import Settings


class _ServerState:
    def __init__(self) -> None:
        self.requests: list[dict] = []
        self.responses: list[tuple[int, bytes, dict[str, str]]] = []
        self.lock = threading.Lock()

    def record(self, request_data: dict) -> None:
        with self.lock:
            self.requests.append(request_data)

    def push(self, status: int, body: bytes, headers: dict[str, str] | None = None) -> None:
        with self.lock:
            self.responses.append((status, body, headers or {}))

    def pop(self) -> tuple[int, bytes, dict[str, str]]:
        with self.lock:
            if not self.responses:
                return (200, b"{}", {})
            return self.responses.pop(0)


def _make_handler(state: _ServerState):
    class _Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            length = int(self.headers.get("Content-Length", "0"))
            body = self.rfile.read(length) if length else b""
            state.record(
                {
                    "path": self.path,
                    "headers": dict(self.headers),
                    "raw_body": body,
                }
            )
            status, payload, headers = state.pop()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            for key, value in headers.items():
                self.send_header(key, value)
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, fmt: str, *args: object) -> None:  # noqa: ARG002
            return

    return _Handler


@pytest.fixture()
def fake_server():
    state = _ServerState()
    server = ThreadingHTTPServer(("127.0.0.1", 0), _make_handler(state))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield state, f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _settings(base_url: str) -> Settings:
    return Settings.model_construct(
        app_env="test",
        database_url="",
        oracle_client_lib_dir=None,
        db_pool_size=5,
        db_max_overflow=10,
        db_pool_recycle_seconds=3600,
        sql_echo=False,
        evidence_root=Path(),
        max_upload_bytes=100 * 1024 * 1024,
        max_xlsx_uncompressed_bytes=500 * 1024 * 1024,
        max_waveutil_rows=20_000,
        actor_id="00000000-0000-0000-0000-000000000001",
        actor_display_name="Test Actor",
        actor_attuid=None,
        csrf_secret=SecretStr("test-csrf-secret-minimum-32-characters-long"),
        catalog_path=None,
        workbook_contract_version="APP_DATA_CAPTURE_V1",
        llm_enabled=True,
        llm_provider="openai_compatible",
        llm_profile="synthetic-local",
        llm_outbound_enabled=True,
        llm_base_url=base_url,
        llm_model="test-model",
        llm_auth_mode="bearer_token",
        llm_api_token=SecretStr("test-token"),
        llm_allowed_classifications_raw="SYNTHETIC",
        llm_connect_timeout_seconds=5,
        llm_read_timeout_seconds=10,
        llm_max_attempts=3,
        llm_max_response_bytes=10 * 1024 * 1024,
        llm_max_fragment_chars=12_000,
        llm_max_requests_per_import=20,
        log_level="INFO",
        log_format="human",
    )


def _request() -> StructuredCompletionRequest:
    return StructuredCompletionRequest(
        request_id=str(uuid.uuid4()),
        correlation_id="corr-1",
        provider_id="openai_compatible",
        model_id="test-model",
        system_instruction="Return JSON only.",
        user_content="Extract candidates.",
        classification="SYNTHETIC",
        prompt_template_version="v1.0",
        request_content_hash="a" * 64,
    )


def _ok_response() -> bytes:
    data = {
        "id": "chatcmpl-123",
        "model": "test-model",
        "choices": [
            {
                "message": {"role": "assistant", "content": '{"proposed_mappings": []}'},
                "finish_reason": "stop",
            }
        ],
    }
    return json.dumps(data).encode("utf-8")


def test_complete_builds_expected_endpoint_and_headers(fake_server) -> None:
    state, base_url = fake_server
    state.push(200, _ok_response())
    client = OpenAICompatibleCompletionClient(
        _settings(base_url),
        allow_http_for_testing=True,
    )
    response = client.complete(_request())

    assert response.provider_id == "openai_compatible"
    assert state.requests[0]["path"] == "/v1/chat/completions"
    assert state.requests[0]["headers"]["Authorization"] == "Bearer test-token"
    assert "X-Idempotency-Key" in state.requests[0]["headers"]


def test_complete_does_not_follow_redirects(fake_server) -> None:
    from migration_intake.ai.errors import ProviderTransportError

    state, base_url = fake_server
    state.push(307, b"{}", {"Location": "https://elsewhere"})
    client = OpenAICompatibleCompletionClient(
        _settings(base_url),
        allow_http_for_testing=True,
    )

    with pytest.raises(ProviderTransportError, match="Redirect responses are not permitted"):
        client.complete(_request())


def test_complete_retries_transient_429(fake_server) -> None:
    state, base_url = fake_server
    state.push(429, b"{}")
    state.push(200, _ok_response())
    settings = _settings(base_url)
    settings = settings.model_copy(update={"llm_max_attempts": 2})
    client = OpenAICompatibleCompletionClient(
        settings,
        allow_http_for_testing=True,
        retry_delay_seconds=0.0,
    )
    response = client.complete(_request())

    assert response.attempt_count == 2
    assert len(state.requests) == 2


def test_complete_rejects_oversized_response(fake_server) -> None:
    from migration_intake.ai.errors import ProviderResponseValidationError

    state, base_url = fake_server
    state.push(200, b"x" * 2048)
    settings = _settings(base_url).model_copy(update={"llm_max_response_bytes": 1024})
    client = OpenAICompatibleCompletionClient(
        settings,
        allow_http_for_testing=True,
    )

    with pytest.raises(ProviderResponseValidationError, match="max response bytes"):
        client.complete(_request())
