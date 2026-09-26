"""
Provider-neutral AI integration errors.

These errors are intentionally normalized so application services do not depend
on provider SDK/HTTP exception types.
"""

from __future__ import annotations


class AIIntegrationError(Exception):
    """Base class for provider-neutral AI integration failures."""


class ProviderProfileError(AIIntegrationError):
    """Raised when provider/profile configuration is invalid or incomplete."""


class OutboundAIDisabledError(AIIntegrationError):
    """Raised when outbound AI calls are blocked by policy or configuration."""


class ProviderNotRegisteredError(AIIntegrationError):
    """Raised when no StructuredCompletionClient is registered for a provider."""


class ProviderContractError(AIIntegrationError):
    """Raised when a provider adapter violates the completion contract."""


class ProviderTransportError(AIIntegrationError):
    """Raised for transient or terminal transport-level provider failures."""


class ProviderAuthError(AIIntegrationError):
    """Raised when provider authentication fails."""


class ProviderRateLimitError(AIIntegrationError):
    """Raised when provider rate-limit retries are exhausted."""


class ProviderResponseValidationError(AIIntegrationError):
    """Raised when normalized provider output fails schema/shape validation."""
