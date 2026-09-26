"""
Provider-neutral structured completion contract.

This module defines the internal capability boundary used by provider adapters.
It is intentionally separate from CandidateMapper so application services keep a
task-specific interface and never depend on provider wire details.
"""

from __future__ import annotations

import re
from typing import Literal, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field, field_validator

from migration_intake.ai.errors import OutboundAIDisabledError

_SHA256_HEX = re.compile(r"^[0-9a-f]{64}$")

ResponseMode = Literal["JSON_OBJECT"]
CompletionValidationStatus = Literal["VALID", "SCHEMA_FAILED", "GROUNDING_FAILED"]


class StructuredCompletionRequest(BaseModel):
    """
    Provider-neutral completion input.

    Carries only bounded request content and safe metadata. Credentials or
    provider URLs are never included in this request object.
    """

    model_config = ConfigDict(frozen=True)

    request_id: str = Field(description="Internal request identifier (UUID string).")
    correlation_id: str = Field(
        description="Cross-system correlation key for traceability."
    )
    provider_id: str = Field(
        description="Provider identifier selected by profile (e.g. openai_compatible)."
    )
    model_id: str = Field(description="Provider model identifier.")
    system_instruction: str = Field(description="Provider-independent system prompt.")
    user_content: str = Field(description="Bounded user payload for completion.")
    temperature: float = Field(default=0.0, ge=0.0, le=2.0)
    max_output_tokens: int = Field(default=2048, ge=1, le=32_768)
    response_mode: ResponseMode = Field(default="JSON_OBJECT")
    classification: str = Field(
        description="Data classification attached to the request payload."
    )
    prompt_template_version: str = Field(
        description="Prompt template version for deterministic audit lineage."
    )
    request_content_hash: str = Field(
        description="SHA-256 hash of the outbound payload content."
    )

    @field_validator("request_content_hash")
    @classmethod
    def validate_request_hash(cls, value: str) -> str:
        """Require lowercase SHA-256 hex for request content hashing."""
        if not _SHA256_HEX.match(value):
            raise ValueError("request_content_hash must be a 64-char lowercase SHA-256 hex")
        return value


class StructuredCompletionResponse(BaseModel):
    """
    Provider-neutral completion output.

    Exposes normalized completion text and safe metadata only.
    """

    model_config = ConfigDict(frozen=True)

    provider_id: str = Field(description="Provider identifier that produced this response.")
    model_id: str = Field(description="Model identifier used by the provider.")
    provider_request_id: str | None = Field(
        default=None,
        description="Provider-native request ID when supplied by provider.",
    )
    finish_reason: str = Field(description="Provider finish reason.")
    attempt_count: int = Field(description="Total request attempts.", ge=1, le=10)
    latency_bucket: str = Field(
        description="Redacted latency bucket label (e.g. '<=250ms', '<=1s', '>1s')."
    )
    normalized_content: str = Field(
        description="Normalized content text for downstream JSON parsing/validation."
    )
    response_hash: str = Field(description="SHA-256 hash of raw provider response bytes.")
    validation_status: CompletionValidationStatus = Field(default="VALID")

    @field_validator("response_hash")
    @classmethod
    def validate_response_hash(cls, value: str) -> str:
        """Require lowercase SHA-256 hex for response hashing."""
        if not _SHA256_HEX.match(value):
            raise ValueError("response_hash must be a 64-char lowercase SHA-256 hex")
        return value


@runtime_checkable
class StructuredCompletionClient(Protocol):
    """
    Capability protocol implemented by provider adapters.

    Adapters map provider-specific transport/auth/wire conventions to the
    provider-neutral request/response models.
    """

    def complete(
        self,
        request: StructuredCompletionRequest,
    ) -> StructuredCompletionResponse:
        """Execute one structured completion request."""


class DisabledStructuredCompletionClient:
    """Capability implementation that always blocks outbound calls."""

    def __init__(self, *, reason: str) -> None:
        self._reason = reason

    def complete(
        self,
        _request: StructuredCompletionRequest,
    ) -> StructuredCompletionResponse:
        raise OutboundAIDisabledError(self._reason)
