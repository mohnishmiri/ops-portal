"""
Provider registry and completion-client factory.

The registry is a pure construction boundary: it maps provider IDs to adapter
factories and returns a StructuredCompletionClient without mutating environment
state or making network calls.
"""

from __future__ import annotations

from collections.abc import Callable

from migration_intake.ai.completion import (
    DisabledStructuredCompletionClient,
    StructuredCompletionClient,
)
from migration_intake.ai.errors import ProviderNotRegisteredError
from migration_intake.config import Settings

ProviderFactory = Callable[[Settings], StructuredCompletionClient]


class ProviderRegistry:
    """Mutable in-process registry used by the composition root."""

    def __init__(self) -> None:
        self._factories: dict[str, ProviderFactory] = {}

    def register(self, provider_id: str, factory: ProviderFactory) -> None:
        """Register one provider factory under a closed-set provider ID."""
        self._factories[provider_id] = factory

    def resolve(self, provider_id: str) -> ProviderFactory:
        """Resolve one provider factory or raise when absent."""
        factory = self._factories.get(provider_id)
        if factory is None:
            raise ProviderNotRegisteredError(
                f"No StructuredCompletionClient registered for provider '{provider_id}'"
            )
        return factory


def build_structured_completion_client(
    settings: Settings,
    *,
    registry: ProviderRegistry | None = None,
) -> StructuredCompletionClient:
    """
    Build one completion client from validated settings.

    Behavior:
    - Returns Disabled client when AI is disabled or outbound is blocked.
    - Returns Disabled client for provider=mock.
    - Resolves registered provider factory for enabled outbound profiles.
    """
    if not settings.llm_enabled:
        return DisabledStructuredCompletionClient(
            reason="LLM provider calls are disabled by configuration (LLM_ENABLED=false)."
        )
    if not settings.llm_outbound_enabled:
        return DisabledStructuredCompletionClient(
            reason="LLM outbound calls are disabled by policy (LLM_OUTBOUND_ENABLED=false)."
        )
    if settings.llm_provider == "mock":
        return DisabledStructuredCompletionClient(
            reason="Provider 'mock' is local-only and cannot perform outbound calls."
        )

    local_registry = registry or create_default_provider_registry()
    factory = local_registry.resolve(settings.llm_provider)
    return factory(settings)


def create_default_provider_registry() -> ProviderRegistry:
    """Create the default in-process registry for known provider adapters."""
    registry = ProviderRegistry()
    from migration_intake.ai.providers.openai_compatible import (
        OpenAICompatibleCompletionClient,
    )

    registry.register(
        "openai_compatible",
        lambda settings: OpenAICompatibleCompletionClient(settings),
    )
    return registry
