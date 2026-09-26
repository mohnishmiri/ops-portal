"""
CandidateMapper factory and disabled implementation.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from migration_intake.ai.candidate_mapper_provider import ProviderBackedCandidateMapper
from migration_intake.ai.errors import OutboundAIDisabledError
from migration_intake.ai.mock import MockCandidateMapper
from migration_intake.ai.port import CandidateMapper
from migration_intake.ai.provider_registry import build_structured_completion_client

if TYPE_CHECKING:
    from migration_intake.config import Settings


class DisabledCandidateMapper(CandidateMapper):
    """CandidateMapper that rejects mapping calls under disabled policy."""

    def __init__(self, reason: str) -> None:
        self._reason = reason

    def map(self, _request):
        raise OutboundAIDisabledError(self._reason)


def build_candidate_mapper(settings: Settings) -> CandidateMapper:
    """
    Build the active CandidateMapper from validated settings.

    Default behavior is safe:
    - provider=mock uses local deterministic mapping (no outbound call)
    - outbound disabled returns DisabledCandidateMapper
    - unsupported providers remain disabled until a dedicated adapter lands
    """
    if settings.llm_provider == "mock":
        return MockCandidateMapper()
    if not settings.llm_enabled or not settings.llm_outbound_enabled:
        return DisabledCandidateMapper(
            "AI mapping is disabled by profile policy for this environment."
        )
    if settings.llm_provider in ("openai_compatible", "anthropic", "bedrock"):
        completion_client = build_structured_completion_client(settings)
        return ProviderBackedCandidateMapper(
            completion_client=completion_client,
            provider_id=settings.llm_provider,
            model_id=settings.llm_model or "unknown-model",
        )
    return DisabledCandidateMapper(
        f"Provider '{settings.llm_provider}' is not yet implemented in CandidateMapper factory."
    )
