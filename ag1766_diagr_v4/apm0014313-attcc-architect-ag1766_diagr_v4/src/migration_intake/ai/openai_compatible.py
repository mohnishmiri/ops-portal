"""
OpenAI-compatible adapter for candidate mapping.

Disabled by default. All network calls require explicit enablement
through Settings gates. Client evidence is prohibited in this slice.
Tokens are never logged, never placed in URLs, never stored.

Design constraints (Architecture §52):
- Tokens appear ONLY in the Authorization header (never URL, body, or logs).
- HTTP base URLs are rejected at gate-check time; no connection attempt made.
- Retry is bounded: at most _max_attempts total for 429 and transient 5xx.
- No retry for auth (401/403), malformed request (400), or schema failures.
- Response size is bounded before JSON decoding.
- Partial/truncated JSON (from token-limit exhaustion) is fully validated.
- Provider metadata returned in model_metadata; secrets never included.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from enum import Enum

import httpx

from migration_intake.ai.models import MappingRequest, MappingResult, ProposedMapping
from migration_intake.config import Settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------

_DEFAULT_MAX_ATTEMPTS: int = 3
_DEFAULT_RETRY_DELAY_SECONDS: float = 0.5
_DEFAULT_MAX_RESPONSE_BYTES: int = 10 * 1024 * 1024  # 10 MB

_CLASSIFICATION_SYNTHETIC: str = "SYNTHETIC"
_PROVIDER_ID: str = "openai_compatible"
_CHAT_COMPLETIONS_PATH: str = "/v1/chat/completions"

# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class ProviderPolicy(str, Enum):
    """Whether this adapter may make network calls."""

    DISABLED = "DISABLED"
    SYNTHETIC_ONLY = "SYNTHETIC_ONLY"


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class AdapterGateError(Exception):
    """Raised when a required gate is not satisfied before a network call."""


class ProviderError(Exception):
    """Raised when the provider returns an error or behaves unexpectedly."""


class ProviderAuthError(ProviderError):
    """Raised when provider authentication fails (HTTP 401 or 403)."""


class ProviderRateLimitError(ProviderError):
    """Raised when all retry attempts are exhausted due to rate-limiting (HTTP 429)."""


# ---------------------------------------------------------------------------
# Adapter
# ---------------------------------------------------------------------------


class OpenAICompatibleMapper:
    """
    CandidateMapper backed by an OpenAI-compatible HTTP API.

    All network calls are gated by Settings. By default, network is
    disabled and this raises AdapterGateError if map_candidates() is called.

    Args:
        settings:
            Application settings.  ``llm_enabled``, ``llm_base_url``,
            ``llm_model``, and ``llm_api_token`` must all be correctly set
            for any network call to proceed.
        _allow_http_for_testing:
            When *True*, the HTTPS-only gate (gate 3) is bypassed so that
            tests may use a local ``http://localhost`` fake server.
            **Never set this to True in production code.**
        _max_response_bytes:
            Upper bound on acceptable response body size (bytes).
            Responses exceeding this limit raise ProviderError without
            decoding the body.
        _retry_delay_seconds:
            Seconds to sleep between retry attempts.  Set to 0.0 in tests
            to avoid wall-clock delays.
        _max_attempts:
            Total number of attempts (initial + retries).  Bounded by
            design; not configurable at runtime via Settings.
        _connect_timeout_seconds:
            Override for the connect timeout in seconds.  Defaults to
            ``settings.llm_connect_timeout_seconds``.
    """

    def __init__(
        self,
        settings: Settings,
        *,
        _allow_http_for_testing: bool = False,
        _max_response_bytes: int = _DEFAULT_MAX_RESPONSE_BYTES,
        _retry_delay_seconds: float = _DEFAULT_RETRY_DELAY_SECONDS,
        _max_attempts: int = _DEFAULT_MAX_ATTEMPTS,
        _connect_timeout_seconds: int | None = None,
    ) -> None:
        self._settings = settings
        self._allow_http_for_testing = _allow_http_for_testing
        self._max_response_bytes = _max_response_bytes
        self._retry_delay_seconds = _retry_delay_seconds
        self._max_attempts = max(1, _max_attempts)
        self._connect_timeout: int = (
            _connect_timeout_seconds
            if _connect_timeout_seconds is not None
            else settings.llm_connect_timeout_seconds
        )

    # ------------------------------------------------------------------
    # Gate enforcement (section 52.2)
    # ------------------------------------------------------------------

    def _check_gates(self, request: MappingRequest) -> None:
        """
        Raise AdapterGateError if any required gate is not satisfied.

        Gates are evaluated in order; the first failure short-circuits
        the remaining checks and raises immediately — no network
        connection is attempted.

        Gate order:
        1. LLM_ENABLED must be True.
        2. ``candidate_mapper_provider`` must be ``"openai_compatible"``.
        3. ``llm_base_url`` must use HTTPS (unless ``_allow_http_for_testing``).
        4. ``llm_model`` and ``llm_api_token`` must be non-empty.
        5. ``request.classification`` must equal ``"SYNTHETIC"``.
        """
        # Gate 1 — feature flag
        if not self._settings.llm_enabled:
            raise AdapterGateError(
                "LLM network calls are disabled (LLM_ENABLED is False). "
                "Set LLM_ENABLED=true and configure all required credentials "
                "to allow network calls."
            )

        # Gate 2 — provider selection
        if self._settings.candidate_mapper_provider != "openai_compatible":
            raise AdapterGateError(
                f"Candidate mapper provider is '{self._settings.candidate_mapper_provider}', "
                "not 'openai_compatible'. "
                "Set CANDIDATE_MAPPER_PROVIDER=openai_compatible."
            )

        # Gate 3 — transport security (HTTPS only unless test-bypass active)
        base_url = self._settings.llm_base_url or ""
        if not self._allow_http_for_testing and not base_url.startswith("https://"):
            raise AdapterGateError(
                "LLM_BASE_URL must use HTTPS. "
                "HTTP connections are rejected to prevent credential exposure "
                "over unencrypted transports."
            )

        # Gate 4a — model must be configured
        if not self._settings.llm_model:
            raise AdapterGateError(
                "LLM_MODEL is required for network calls but is not configured. "
                "Set LLM_MODEL to the target model identifier."
            )

        # Gate 4b — token must be configured and non-empty
        api_token = self._settings.llm_api_token
        if api_token is None:
            raise AdapterGateError(
                "LLM_API_TOKEN is required for network calls but is not configured."
            )
        # Validate the secret value without logging it
        if not api_token.get_secret_value():
            raise AdapterGateError(
                "LLM_API_TOKEN is configured but contains an empty value."
            )

        # Gate 5 — classification guard (client evidence prohibited)
        if request.classification != _CLASSIFICATION_SYNTHETIC:
            raise AdapterGateError(
                f"Request classification '{request.classification}' is not permitted. "
                f"Only '{_CLASSIFICATION_SYNTHETIC}' requests may be forwarded to the "
                "provider in this slice. Client evidence is strictly prohibited."
            )

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def map_candidates(self, request: MappingRequest) -> MappingResult:
        """
        Map candidates using the remote provider.

        All gates are checked before any network activity.  A
        network call is made only when every gate passes.

        Raises:
            AdapterGateError: If any gate rejects the call.
            ProviderError: If the provider returns an error.
            ProviderAuthError: If authentication fails (HTTP 401/403).
            ProviderRateLimitError: If all retries are exhausted (HTTP 429).
        """
        self._check_gates(request)
        body = self._build_request_body(request)
        raw, attempt_count = self._call_provider(body)
        return self._parse_response(raw, request, attempt_count)

    def map(self, request: MappingRequest) -> MappingResult:
        """
        Satisfy the CandidateMapper protocol.

        Delegates to ``map_candidates``.  All gate checks apply.
        """
        return self.map_candidates(request)

    # ------------------------------------------------------------------
    # Request construction
    # ------------------------------------------------------------------

    def _build_request_body(self, request: MappingRequest) -> dict:
        """
        Build the OpenAI-compatible chat completions request body.

        The body includes only the question IDs and the synthetic fragment.
        Credentials are never placed in the body.
        """
        question_ids = [
            q.get("id", "") for q in request.question_definitions if q.get("id")
        ]
        question_list = ", ".join(question_ids) if question_ids else "(none)"

        user_content = (
            "Analyze the following evidence fragment and extract structured values "
            "for the listed questions.\n\n"
            f"Fragment:\n{request.source_fragment}\n\n"
            f"Questions: {question_list}\n\n"
            "Return a JSON object with this exact structure:\n"
            '{"proposed_mappings": [], "warnings": [], "unmapped_fragments": []}'
        )

        return {
            "model": self._settings.llm_model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are a structured data extraction assistant. "
                        "Return only valid JSON. Never include explanatory prose."
                    ),
                },
                {
                    "role": "user",
                    "content": user_content,
                },
            ],
            "max_tokens": 2048,
            "temperature": 0.0,
            "top_p": 1.0,
            "n": 1,
        }

    # ------------------------------------------------------------------
    # HTTP call (section 52.1, 52.4)
    # ------------------------------------------------------------------

    def _call_provider(self, body: dict) -> tuple[dict, int]:
        """
        Make the HTTP POST call to the provider.

        Token sent in Authorization header only — never in the URL, body,
        query string, or logs.  Timeouts are enforced.  Response size is
        bounded before decoding.

        Returns:
            A tuple of (parsed_response_dict, attempt_count).

        Raises:
            ProviderError: On transport errors, bad status, oversized body,
                or non-JSON response body.
            ProviderAuthError: On HTTP 401 or 403.
            ProviderRateLimitError: On HTTP 429 when retries are exhausted.
        """
        api_token = self._settings.llm_api_token
        # _check_gates ensures this is non-None with a non-empty value
        assert api_token is not None, "llm_api_token must be set (gate check missed)"

        base_url = (self._settings.llm_base_url or "").rstrip("/")
        url = f"{base_url}{_CHAT_COMPLETIONS_PATH}"

        # Token in Authorization header ONLY — never logged, never in URL
        headers: dict[str, str] = {
            "Authorization": f"Bearer {api_token.get_secret_value()}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

        # httpx.Timeout requires either a positional default or all four
        # explicit kwargs (connect, read, write, pool).  Pass the read timeout
        # as the positional default so write/pool inherit it, then override
        # connect with the (typically shorter) connection-specific value.
        read_t = float(self._settings.llm_read_timeout_seconds)
        connect_t = float(self._connect_timeout)
        timeout = httpx.Timeout(read_t, connect=connect_t)

        for attempt in range(self._max_attempts):
            logger.debug(
                "Provider request: attempt %d/%d to %s",
                attempt + 1,
                self._max_attempts,
                _CHAT_COMPLETIONS_PATH,  # path only — no credentials in log
            )

            try:
                with httpx.Client(timeout=timeout) as client:
                    response = client.post(url, json=body, headers=headers)
            except httpx.TransportError as exc:
                logger.warning(
                    "Transport error on attempt %d/%d: %s",
                    attempt + 1,
                    self._max_attempts,
                    type(exc).__name__,
                    # exc message deliberately not included — may contain URL fragments
                )
                if attempt < self._max_attempts - 1:
                    if self._retry_delay_seconds > 0:
                        time.sleep(self._retry_delay_seconds)
                    continue
                raise ProviderError(
                    f"Transport error after {attempt + 1} attempt(s): "
                    f"{type(exc).__name__}."
                ) from exc

            status = response.status_code
            logger.debug(
                "Provider HTTP %d on attempt %d/%d",
                status,
                attempt + 1,
                self._max_attempts,
            )

            # ---- 200 OK ------------------------------------------------
            if status == 200:
                body_bytes = response.content
                if len(body_bytes) > self._max_response_bytes:
                    raise ProviderError(
                        f"Response body ({len(body_bytes):,} bytes) exceeds "
                        f"size limit ({self._max_response_bytes:,} bytes). "
                        "Response rejected to prevent memory exhaustion."
                    )
                try:
                    return response.json(), attempt + 1
                except (json.JSONDecodeError, ValueError) as exc:
                    raise ProviderError(
                        "Provider returned a non-JSON response body. "
                        "Possible token-limit truncation or provider misconfiguration."
                    ) from exc

            # ---- 401 / 403 Auth ----------------------------------------
            elif status in (401, 403):
                # No retry. Token deliberately absent from the message.
                raise ProviderAuthError(
                    f"Provider authentication failed (HTTP {status}). "
                    "Check that LLM_API_TOKEN is valid for this endpoint."
                )

            # ---- 400 Bad Request ----------------------------------------
            elif status == 400:
                # No retry. Error body may contain request excerpts — not logged.
                raise ProviderError(
                    "Provider rejected the request (HTTP 400 Bad Request). "
                    "Check the request structure and model configuration."
                )

            # ---- 429 Rate Limited --------------------------------------
            elif status == 429:
                retry_after_str = response.headers.get("Retry-After", "0")
                try:
                    wait_seconds = max(0.0, float(retry_after_str))
                except ValueError:
                    wait_seconds = 0.0

                logger.warning(
                    "Provider rate-limited (HTTP 429) on attempt %d/%d "
                    "(Retry-After: %.1fs)",
                    attempt + 1,
                    self._max_attempts,
                    wait_seconds,
                )

                if attempt < self._max_attempts - 1:
                    if wait_seconds > 0:
                        time.sleep(wait_seconds)
                    continue
                raise ProviderRateLimitError(
                    f"Provider rate-limited all {attempt + 1} attempt(s) (HTTP 429). "
                    "Try again later or increase limits with the provider."
                )

            # ---- 5xx Transient -----------------------------------------
            elif status >= 500:
                logger.warning(
                    "Provider transient error (HTTP %d) on attempt %d/%d",
                    status,
                    attempt + 1,
                    self._max_attempts,
                )
                if attempt < self._max_attempts - 1:
                    if self._retry_delay_seconds > 0:
                        time.sleep(self._retry_delay_seconds)
                    continue
                raise ProviderError(
                    f"Provider server error (HTTP {status}) persisted after "
                    f"{attempt + 1} attempt(s)."
                )

            # ---- Unexpected status -------------------------------------
            else:
                raise ProviderError(
                    f"Unexpected provider response status (HTTP {status})."
                )

        # Guard: unreachable under normal flow, but ensures all paths return/raise
        raise ProviderError(
            f"All {self._max_attempts} attempt(s) exhausted without a result."
        )

    # ------------------------------------------------------------------
    # Response parsing (section 52.3)
    # ------------------------------------------------------------------

    def _parse_response(
        self,
        raw: dict,
        request: MappingRequest,
        attempt_count: int,
    ) -> MappingResult:
        """
        Parse and validate the structured response from the provider.

        Extracts ``choices[0].message.content``, parses it as JSON, and
        builds a fully-validated MappingResult.  Token-limit truncation
        can produce valid-looking incomplete JSON; all fields are required
        to be present before the result is accepted.

        The raw response hash is computed before any content interpretation
        so that audit traceability is preserved even when parsing fails.
        """
        # Audit hash — computed unconditionally, before any validation
        raw_str = json.dumps(raw, sort_keys=True, ensure_ascii=False)
        raw_response_hash = hashlib.sha256(raw_str.encode()).hexdigest()

        model_meta: dict = {
            "provider": _PROVIDER_ID,
            "model": self._settings.llm_model,
            "attempt_count": attempt_count,
        }

        def _error_result(
            validation_status: str,
            warnings: list[str],
            unmapped: list[str] | None = None,
        ) -> MappingResult:
            return MappingResult(
                request_id=request.request_id,
                provider=_PROVIDER_ID,
                model_metadata=model_meta,
                proposed_mappings=[],
                unmapped_fragments=unmapped or [],
                warnings=warnings,
                grounding_quotes=[],
                raw_response_hash=raw_response_hash,
                validation_status=validation_status,
            )

        # -- Validate envelope -------------------------------------------
        choices = raw.get("choices")
        if not isinstance(choices, list) or not choices:
            return _error_result(
                "SCHEMA_FAILED",
                ["Provider response missing or empty 'choices' list."],
            )

        first_choice = choices[0]
        if not isinstance(first_choice, dict):
            return _error_result(
                "SCHEMA_FAILED",
                ["Provider 'choices[0]' is not an object."],
            )

        message = first_choice.get("message")
        if not isinstance(message, dict):
            return _error_result(
                "SCHEMA_FAILED",
                ["Provider 'choices[0].message' is missing or not an object."],
            )

        content_str = message.get("content", "")
        if not isinstance(content_str, str) or not content_str.strip():
            return _error_result(
                "SCHEMA_FAILED",
                ["Provider 'choices[0].message.content' is empty or not a string."],
            )

        # -- Parse embedded JSON content ---------------------------------
        try:
            content = json.loads(content_str)
        except (json.JSONDecodeError, ValueError):
            return _error_result(
                "SCHEMA_FAILED",
                [
                    "Provider content field is not valid JSON. "
                    "Possible token-limit truncation producing incomplete JSON."
                ],
            )

        if not isinstance(content, dict):
            return _error_result(
                "SCHEMA_FAILED",
                ["Provider content JSON is not an object (dict)."],
            )

        # -- Build proposed mappings with full validation -----------------
        proposed_mappings: list[ProposedMapping] = []
        warnings: list[str] = []
        unmapped_fragments: list[str] = []

        raw_warnings = content.get("warnings", [])
        if isinstance(raw_warnings, list):
            warnings.extend(str(w) for w in raw_warnings)

        raw_unmapped = content.get("unmapped_fragments", [])
        if isinstance(raw_unmapped, list):
            unmapped_fragments.extend(str(u) for u in raw_unmapped)

        raw_mappings = content.get("proposed_mappings", [])
        if isinstance(raw_mappings, list):
            for idx, mapping_data in enumerate(raw_mappings):
                if not isinstance(mapping_data, dict):
                    warnings.append(
                        f"Skipping non-object item in proposed_mappings[{idx}]."
                    )
                    continue
                try:
                    mapping = ProposedMapping(
                        question_id=mapping_data["question_id"],
                        proposed_value=mapping_data["proposed_value"],
                        confidence_metadata=mapping_data.get("confidence_metadata", {}),
                        grounding_quote=mapping_data["grounding_quote"],
                        source_locator=mapping_data.get(
                            "source_locator", request.source_locator
                        ),
                    )
                    proposed_mappings.append(mapping)
                except (KeyError, TypeError, ValueError) as exc:
                    warnings.append(
                        f"Failed to parse proposed_mappings[{idx}]: "
                        f"{type(exc).__name__}."
                    )

        grounding_quotes = [m.grounding_quote for m in proposed_mappings]
        validation_status = "VALID" if proposed_mappings else "GROUNDING_FAILED"

        # Safe provider envelope metadata (no secrets)
        finish_reason = first_choice.get("finish_reason")
        if finish_reason:
            model_meta["finish_reason"] = str(finish_reason)

        return MappingResult(
            request_id=request.request_id,
            provider=_PROVIDER_ID,
            model_metadata=model_meta,
            proposed_mappings=proposed_mappings,
            unmapped_fragments=unmapped_fragments,
            warnings=warnings,
            grounding_quotes=grounding_quotes,
            raw_response_hash=raw_response_hash,
            validation_status=validation_status,
        )
