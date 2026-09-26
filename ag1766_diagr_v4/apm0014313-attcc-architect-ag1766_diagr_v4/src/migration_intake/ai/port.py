"""
Port definition for the CandidateMapper.

The CandidateMapper Protocol defines the narrow interface between the
application layer and any AI provider adapter. Concrete implementations
may be:
- MockCandidateMapper: deterministic, fixture-based (tests and offline).
- An OpenAI-compatible adapter: calls a live LLM endpoint.

Implementations must be deterministic given the same input (mock) or
produce stable, auditable output (live providers). They must never
approve, overwrite, or make architect decisions; all output is candidate
only.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from migration_intake.ai.models import MappingRequest, MappingResult


@runtime_checkable
class CandidateMapper(Protocol):
    """
    Protocol for AI candidate-mapping adapters.

    A CandidateMapper accepts a MappingRequest describing a bounded
    evidence fragment and a set of question definitions, and returns a
    MappingResult containing proposed candidate mappings.

    All output is candidate only and requires authorized review before
    promotion to canonical answers.
    """

    def map(self, request: MappingRequest) -> MappingResult:
        """
        Produce candidate mappings for a single evidence fragment.

        Args:
            request: The mapping request containing the source fragment
                     and question definitions to map against.

        Returns:
            MappingResult with candidate mappings, grounding quotes,
            validation status, and a SHA-256 audit hash of the response.
            All output is candidate only.
        """
        ...
