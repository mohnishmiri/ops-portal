"""
Integration tests for OpenAICompatibleMapper against a fake HTTP server.

All tests use a ThreadingHTTPServer fake server (pytest-httpserver not available).
The mapper is constructed with _allow_http_for_testing=True so the HTTPS gate is
bypassed for local test servers. Security tests (no bypass flag) live in
tests/security/test_ai_policy.py.

The token used in all tests is "test-token". Tests assert it never appears in
log output, URLs, or request bodies.
"""

from __future__ import annotations

import json
import socket
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Generator

import pytest
from pydantic import SecretStr

# ---------------------------------------------------------------------------
# Fake server infrastructure
# ---------------------------------------------------------------------------


class _ServerState:
    """Thread-safe state for the fake HTTP server."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.requests: list[dict] = []
        self._responses: list[tuple[int, bytes, dict[str, str]]] = []

    def push_response(
        self,
        status: int,
        body: bytes,
        headers: dict[str, str] | None = None,
    ) -> None:
        """Enqueue a response to return for the next incoming request."""
        with self._lock:
            self._responses.append((status, body, headers or {}))

    def pop_response(self) -> tuple[int, bytes, dict[str, str]]:
        """Dequeue and return the next queued response (FIFO)."""
        with self._lock:
            if self._responses:
                return self._responses.pop(0)
            return (200, b"{}", {})

    def record(self, request_info: dict) -> None:
        """Record metadata for a received request."""
        with self._lock:
            self.requests.append(request_info)

    def clear(self) -> None:
        """Reset all recorded requests and queued responses."""
        with self._lock:
            self.requests.clear()
            self._responses.clear()


def _make_handler(state: _ServerState) -> type:
    """Return a BaseHTTPRequestHandler class that uses the given state."""

    class _Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802
            length = int(self.headers.get("Content-Length", 0))
            body_bytes = self.rfile.read(length) if length else b""
            try:
                body_json = json.loads(body_bytes) if body_bytes else {}
            except (json.JSONDecodeError, ValueError):
                body_json = {}

            state.record(
                {
                    "method": "POST",
                    "path": self.path,
                    "headers": dict(self.headers),
                    "body": body_json,
                    "raw_url": self.path,
                }
            )

            status, resp_body, extra_headers = state.pop_response()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(resp_body)))
            for k, v in extra_headers.items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(resp_body)

        def log_message(self, format: str, *args: object) -> None:  # noqa: ARG002,A002
            """Suppress all server-side log output during tests."""

    return _Handler


def _free_port() -> int:
    """Return a free loopback port by binding then immediately closing a socket."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class _FakeServer:
    """Thin wrapper around ThreadingHTTPServer for test fixtures."""

    def __init__(self) -> None:
        self.state = _ServerState()
        handler = _make_handler(self.state)
        # Bind directly in ThreadingHTTPServer; avoids an extra intermediate socket
        self._server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.port: int = self._server.server_address[1]
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._server.shutdown()
        self._server.server_close()  # close the listening socket explicitly
        self._thread.join(timeout=5)

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}"


# ---------------------------------------------------------------------------
# Helpers: settings factory and request/response builders
# ---------------------------------------------------------------------------


def _make_test_settings(base_url: str):
    """Build Settings via model_construct to bypass HTTPS validator."""
    from migration_intake.config import Settings

    return Settings.model_construct(
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
        llm_outbound_enabled=True,
        llm_enabled=True,
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
        log_level="DEBUG",
        log_format="human",
        catalog_path=None,
        workbook_contract_version="APP_DATA_CAPTURE_V1",
    )


def _make_test_request(**overrides: object):
    """Return a synthetic MappingRequest with sensible defaults."""
    from migration_intake.ai.models import MappingRequest

    base: dict = dict(
        request_id=str(uuid.uuid4()),
        source_fragment="The application runs on Linux with Oracle DB.",
        source_locator="Sheet:TEST/Row:1/Col:A",
        source_type="workbook_app_sheet",
        application_scope="synthetic_test_app",
        question_definitions=[{"id": "os_type", "label": "Operating System"}],
        response_schemas=[{"question_id": "os_type", "type": "scalar"}],
        allowed_values={"os_type": ["LINUX", "WINDOWS", "UNKNOWN"]},
        prompt_template_version="v1.0",
        classification="SYNTHETIC",
    )
    base.update(overrides)
    return MappingRequest(**base)


def _valid_response_body(model: str = "test-model", mappings: list | None = None) -> bytes:
    """Return a minimal valid OpenAI-compatible chat.completion response."""
    content_payload = {
        "proposed_mappings": mappings if mappings is not None else [],
        "warnings": [],
        "unmapped_fragments": [],
    }
    raw = {
        "id": "chatcmpl-test-001",
        "object": "chat.completion",
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": json.dumps(content_payload),
                },
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
    }
    return json.dumps(raw).encode()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def fake_server() -> Generator[_FakeServer, None, None]:
    """Start a local fake HTTP server; yield it; stop on teardown."""
    srv = _FakeServer()
    srv.start()
    yield srv
    srv.stop()


@pytest.fixture()
def mapper(fake_server: _FakeServer):
    """OpenAICompatibleMapper pointed at the fake server (HTTP bypass enabled)."""
    from migration_intake.ai.openai_compatible import OpenAICompatibleMapper

    settings = _make_test_settings(fake_server.base_url)
    return OpenAICompatibleMapper(
        settings,
        _allow_http_for_testing=True,
        _retry_delay_seconds=0.0,
        _max_attempts=3,
    )


@pytest.fixture()
def mapper_with_bad_port():
    """Mapper whose base URL points to a port with no listener (connection refused)."""
    from migration_intake.ai.openai_compatible import OpenAICompatibleMapper

    # Bind, record the port, then release — nothing listens afterward
    port = _free_port()

    settings = _make_test_settings(f"http://127.0.0.1:{port}")
    return OpenAICompatibleMapper(
        settings,
        _allow_http_for_testing=True,
        _retry_delay_seconds=0.0,
        _max_attempts=1,
        _connect_timeout_seconds=1,
    )


# ---------------------------------------------------------------------------
# Test cases
# ---------------------------------------------------------------------------


class TestOpenAICompatibleFakeServer:
    """Integration tests against a local fake HTTP server."""

    def test_request_url_built_correctly(
        self, fake_server: _FakeServer, mapper
    ) -> None:
        """POST goes to /v1/chat/completions on the configured base URL."""
        fake_server.state.push_response(200, _valid_response_body())
        mapper.map_candidates(_make_test_request())
        assert len(fake_server.state.requests) == 1
        assert fake_server.state.requests[0]["path"] == "/v1/chat/completions"

    def test_bearer_token_in_header_only(
        self, fake_server: _FakeServer, mapper
    ) -> None:
        """Authorization: Bearer token present; 'test-token' absent from URL and body."""
        fake_server.state.push_response(200, _valid_response_body())
        mapper.map_candidates(_make_test_request())
        req = fake_server.state.requests[0]

        auth_header = req["headers"].get("Authorization") or req["headers"].get(
            "authorization", ""
        )
        assert auth_header.startswith("Bearer "), (
            f"Authorization header missing or wrong format: {auth_header!r}"
        )
        assert "test-token" in auth_header  # token IS in the header

        # Token must NOT appear in the URL
        assert "test-token" not in req["raw_url"]

        # Token must NOT appear in the request body
        body_str = json.dumps(req["body"])
        assert "test-token" not in body_str

    def test_model_in_request_body(
        self, fake_server: _FakeServer, mapper
    ) -> None:
        """The 'model' field in the request body equals the configured model name."""
        fake_server.state.push_response(200, _valid_response_body())
        mapper.map_candidates(_make_test_request())
        body = fake_server.state.requests[0]["body"]
        assert body.get("model") == "test-model"

    def test_structured_success_response_parsed(
        self, fake_server: _FakeServer, mapper
    ) -> None:
        """200 with a valid JSON body returns a MappingResult."""
        from migration_intake.ai.models import MappingResult

        fake_server.state.push_response(200, _valid_response_body())
        result = mapper.map_candidates(_make_test_request())

        assert isinstance(result, MappingResult)
        assert result.provider == "openai_compatible"
        assert len(result.raw_response_hash) == 64
        assert all(c in "0123456789abcdef" for c in result.raw_response_hash)

    def test_malformed_json_response_raises(
        self, fake_server: _FakeServer, mapper
    ) -> None:
        """200 with non-JSON body → ProviderError or error MappingResult, not crash."""
        from migration_intake.ai.openai_compatible import ProviderError

        fake_server.state.push_response(200, b"this is not json at all {{{{")
        with pytest.raises(ProviderError):
            mapper.map_candidates(_make_test_request())

    def test_400_raises_adapter_error(
        self, fake_server: _FakeServer, mapper
    ) -> None:
        """400 from provider → raises ProviderError."""
        from migration_intake.ai.openai_compatible import ProviderError

        fake_server.state.push_response(
            400, b'{"error": {"message": "Bad request", "type": "invalid_request_error"}}'
        )
        with pytest.raises(ProviderError):
            mapper.map_candidates(_make_test_request())

    def test_401_raises_auth_error(
        self, fake_server: _FakeServer, mapper
    ) -> None:
        """401 → ProviderAuthError; token NOT in exception message."""
        from migration_intake.ai.openai_compatible import ProviderAuthError

        fake_server.state.push_response(
            401, b'{"error": {"message": "Unauthorized"}}'
        )
        with pytest.raises(ProviderAuthError) as exc_info:
            mapper.map_candidates(_make_test_request())

        # Token must not appear in the exception message
        assert "test-token" not in str(exc_info.value)

    def test_403_raises_auth_error(
        self, fake_server: _FakeServer, mapper
    ) -> None:
        """403 → ProviderAuthError."""
        from migration_intake.ai.openai_compatible import ProviderAuthError

        fake_server.state.push_response(
            403, b'{"error": {"message": "Forbidden"}}'
        )
        with pytest.raises(ProviderAuthError):
            mapper.map_candidates(_make_test_request())

    def test_429_with_retry_header_retries(
        self, fake_server: _FakeServer, mapper
    ) -> None:
        """429 + Retry-After header causes at least one retry; second call succeeds."""
        fake_server.state.push_response(
            429,
            b'{"error": {"message": "Rate limited"}}',
            {"Retry-After": "0"},
        )
        fake_server.state.push_response(200, _valid_response_body())

        from migration_intake.ai.models import MappingResult

        result = mapper.map_candidates(_make_test_request())
        assert isinstance(result, MappingResult)
        # Exactly two requests made: one 429, one 200
        assert len(fake_server.state.requests) == 2

    def test_500_transient_raises(
        self, fake_server: _FakeServer, mapper
    ) -> None:
        """Persistent 500 responses → ProviderError after bounded retries."""
        from migration_intake.ai.openai_compatible import ProviderError

        # Push enough 500s to exhaust all attempts (max_attempts=3)
        for _ in range(3):
            fake_server.state.push_response(500, b'{"error": {"message": "Server error"}}')

        with pytest.raises(ProviderError):
            mapper.map_candidates(_make_test_request())

        # All three attempts were made
        assert len(fake_server.state.requests) == 3

    def test_connect_timeout_raises(self, mapper_with_bad_port) -> None:
        """Connection refused → ProviderError; no crash, within timeout."""
        from migration_intake.ai.openai_compatible import ProviderError

        t0 = time.monotonic()
        with pytest.raises(ProviderError):
            mapper_with_bad_port.map_candidates(_make_test_request())
        elapsed = time.monotonic() - t0

        # Should fail quickly (well under 10 seconds)
        assert elapsed < 10.0

    def test_oversized_response_rejected(
        self, fake_server: _FakeServer
    ) -> None:
        """Response body exceeding size limit → ProviderError, not memory exhaustion."""
        from migration_intake.ai.openai_compatible import OpenAICompatibleMapper, ProviderError

        # Build mapper with a tiny response limit (200 bytes)
        settings = _make_test_settings(fake_server.base_url)
        small_limit_mapper = OpenAICompatibleMapper(
            settings,
            _allow_http_for_testing=True,
            _retry_delay_seconds=0.0,
            _max_attempts=1,
            _max_response_bytes=200,
        )

        # Server returns 500 bytes: exceeds the 200-byte limit
        fake_server.state.push_response(200, b"x" * 500)

        with pytest.raises(ProviderError):
            small_limit_mapper.map_candidates(_make_test_request())

    def test_token_not_in_any_log_output(
        self, fake_server: _FakeServer, mapper, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Run a successful call; confirm 'test-token' absent from all log records."""
        import logging

        fake_server.state.push_response(200, _valid_response_body())

        with caplog.at_level(logging.DEBUG, logger="migration_intake"):
            mapper.map_candidates(_make_test_request())

        for record in caplog.records:
            msg = record.getMessage()
            assert "test-token" not in msg, (
                f"Token leaked into log record [{record.levelname}] {msg!r}"
            )
