"""
OpenAI-compatible StructuredCompletionClient adapter.

This provider implementation maps the provider-neutral completion contract to
an OpenAI-compatible chat-completions endpoint.
"""

from __future__ import annotations

import hashlib
import json
import time
from ipaddress import ip_address
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

import httpx

from migration_intake.ai.completion import (
    StructuredCompletionClient,
    StructuredCompletionRequest,
    StructuredCompletionResponse,
)
from migration_intake.ai.errors import (
    OutboundAIDisabledError,
    ProviderAuthError,
    ProviderResponseValidationError,
    ProviderTransportError,
)

if TYPE_CHECKING:
    from migration_intake.config import Settings

_ENDPOINT_PATH = "/v1/chat/completions"


class OpenAICompatibleCompletionClient(StructuredCompletionClient):
    """Provider adapter for OpenAI-compatible JSON object completions."""

    def __init__(
        self,
        settings: Settings,
        *,
        allow_http_for_testing: bool = False,
        retry_delay_seconds: float = 0.2,
    ) -> None:
        self._settings = settings
        self._allow_http_for_testing = allow_http_for_testing
        self._retry_delay_seconds = retry_delay_seconds

    def complete(
        self,
        request: StructuredCompletionRequest,
    ) -> StructuredCompletionResponse:
        self._check_policy_gates(request)
        url = self._build_endpoint_url()
        payload = self._build_payload(request)
        headers = self._build_headers(request)
        timeout = httpx.Timeout(
            float(self._settings.llm_read_timeout_seconds),
            connect=float(self._settings.llm_connect_timeout_seconds),
        )
        max_attempts = int(self._settings.llm_max_attempts)

        for attempt in range(1, max_attempts + 1):
            try:
                start = time.perf_counter()
                with httpx.Client(
                    timeout=timeout,
                    follow_redirects=False,
                ) as client:
                    response = client.post(url, headers=headers, json=payload)
                elapsed_ms = (time.perf_counter() - start) * 1000.0
            except httpx.TransportError as exc:
                if attempt < max_attempts:
                    time.sleep(self._retry_delay_seconds)
                    continue
                raise ProviderTransportError(
                    f"Transport failure after {attempt} attempt(s): {type(exc).__name__}"
                ) from exc

            if response.status_code in (301, 302, 303, 307, 308):
                raise ProviderTransportError(
                    "Redirect responses are not permitted for provider calls"
                )
            if response.status_code in (401, 403):
                raise ProviderAuthError(
                    f"Provider authentication failed (HTTP {response.status_code})"
                )
            if response.status_code == 429 or response.status_code >= 500:
                if attempt < max_attempts:
                    time.sleep(self._retry_delay_seconds)
                    continue
                raise ProviderTransportError(
                    f"Provider transient failure after {attempt} attempt(s): "
                    f"HTTP {response.status_code}"
                )
            if response.status_code >= 400:
                raise ProviderTransportError(
                    f"Provider request rejected with HTTP {response.status_code}"
                )

            raw_bytes = response.content
            if len(raw_bytes) > int(self._settings.llm_max_response_bytes):
                raise ProviderResponseValidationError(
                    "Provider response exceeds configured max response bytes"
                )

            try:
                parsed = response.json()
            except (ValueError, json.JSONDecodeError) as exc:
                raise ProviderResponseValidationError(
                    "Provider returned non-JSON response body"
                ) from exc

            content_text = _extract_content_text(parsed)
            response_hash = hashlib.sha256(raw_bytes).hexdigest()
            finish_reason = (
                parsed.get("choices", [{}])[0].get("finish_reason") or "unknown"
            )
            provider_request_id = parsed.get("id")
            return StructuredCompletionResponse(
                provider_id="openai_compatible",
                model_id=str(parsed.get("model") or request.model_id),
                provider_request_id=str(provider_request_id) if provider_request_id else None,
                finish_reason=str(finish_reason),
                attempt_count=attempt,
                latency_bucket=_latency_bucket(elapsed_ms),
                normalized_content=content_text,
                response_hash=response_hash,
                validation_status="VALID",
            )

        raise ProviderTransportError("Unreachable provider state")

    def _check_policy_gates(self, request: StructuredCompletionRequest) -> None:
        if not self._settings.llm_enabled:
            raise OutboundAIDisabledError("LLM provider calls are disabled")
        if not self._settings.llm_outbound_enabled:
            raise OutboundAIDisabledError("LLM outbound calls are disabled")
        if self._settings.llm_provider != "openai_compatible":
            raise OutboundAIDisabledError("Active LLM provider is not openai_compatible")
        if self._settings.llm_auth_mode != "bearer_token":
            raise OutboundAIDisabledError("openai_compatible requires bearer_token auth mode")

        base_url = self._settings.llm_base_url or ""
        if not base_url:
            raise OutboundAIDisabledError("LLM_BASE_URL is not configured")
        if not base_url.startswith("https://") and not (
            self._allow_http_for_testing and _is_loopback_host(base_url)
        ):
            raise OutboundAIDisabledError("HTTPS is required for provider base URL")

        token = self._settings.llm_api_token
        if token is None or not token.get_secret_value():
            raise OutboundAIDisabledError("LLM_API_TOKEN is required for openai_compatible")
        if not self._settings.llm_model:
            raise OutboundAIDisabledError("LLM_MODEL is required for openai_compatible")

        allowed = self._settings.llm_allowed_classifications
        if request.classification.upper() not in allowed:
            raise OutboundAIDisabledError(
                f"Request classification '{request.classification}' is not allowed by policy"
            )

    def _build_endpoint_url(self) -> str:
        base = (self._settings.llm_base_url or "").rstrip("/")
        return f"{base}{_ENDPOINT_PATH}"

    def _build_payload(self, request: StructuredCompletionRequest) -> dict:
        return {
            "model": request.model_id,
            "messages": [
                {"role": "system", "content": request.system_instruction},
                {"role": "user", "content": request.user_content},
            ],
            "temperature": request.temperature,
            "max_tokens": request.max_output_tokens,
            "response_format": {"type": "json_object"},
        }

    def _build_headers(self, request: StructuredCompletionRequest) -> dict[str, str]:
        token = self._settings.llm_api_token
        assert token is not None
        return {
            "Authorization": f"Bearer {token.get_secret_value()}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "X-Idempotency-Key": request.request_id,
            "X-Correlation-Id": request.correlation_id,
        }


def _extract_content_text(parsed: dict) -> str:
    choices = parsed.get("choices")
    if not isinstance(choices, list) or not choices:
        raise ProviderResponseValidationError("Missing choices in provider response")
    first = choices[0]
    if not isinstance(first, dict):
        raise ProviderResponseValidationError("Invalid choice object in provider response")
    message = first.get("message")
    if not isinstance(message, dict):
        raise ProviderResponseValidationError("Missing message in provider response")
    content = message.get("content")
    if not isinstance(content, str) or not content.strip():
        raise ProviderResponseValidationError(
            "Missing or empty message content in provider response"
        )
    return content


def _latency_bucket(elapsed_ms: float) -> str:
    if elapsed_ms <= 250:
        return "<=250ms"
    if elapsed_ms <= 1_000:
        return "<=1s"
    return ">1s"


def _is_loopback_host(url: str) -> bool:
    hostname = urlsplit(url).hostname
    if hostname is None:
        return False
    if hostname == "localhost":
        return True
    try:
        return ip_address(hostname).is_loopback
    except ValueError:
        return False
