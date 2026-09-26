"""
Mock CandidateMapper: deterministic, keyword-fixture-based AI candidate mapper.

This implementation is the default for all tests and local development.
It uses a keyword registry to identify values in the source_fragment, producing
grounding quotes that are exact substrings of the fragment.

Design guarantees:
- Same input always produces the same output (deterministic).
- Mappings are produced only for questions listed in question_definitions.
- Every grounding_quote is a verbatim substring of source_fragment.
- Questions with no keyword fixture produce a warning and no mapping.
- All output is candidate only; never a canonical answer.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from migration_intake.ai.models import MappingRequest, MappingResult, ProposedMapping

# ---------------------------------------------------------------------------
# Keyword registry
#
# Maps question_id → ordered dict of {keyword: proposed_value_dict}.
# Keywords are matched case-insensitively against source_fragment.
# The grounding_quote is the verbatim matched substring from the fragment
# (preserving its original casing), ensuring it is always a substring.
# Entries are ordered longest-first so more-specific phrases win.
# ---------------------------------------------------------------------------

_KEYWORD_REGISTRY: dict[str, dict[str, dict[str, Any]]] = {
    "os_type": {
        "linux": {"value": "LINUX"},
        "windows": {"value": "WINDOWS"},
        "unix": {"value": "UNIX"},
        "solaris": {"value": "UNKNOWN"},
        "macos": {"value": "UNKNOWN"},
        "aix": {"value": "UNKNOWN"},
    },
    "ram_gb": {
        "gb ram": {"value": "UNKNOWN"},
        "ram": {"value": "UNKNOWN"},
        "gb": {"value": "UNKNOWN"},
        "memory": {"value": "UNKNOWN"},
    },
    "db_type": {
        "sql server": {"value": "MSSQL"},
        "postgresql": {"value": "POSTGRESQL"},
        "postgres": {"value": "POSTGRESQL"},
        "oracle": {"value": "ORACLE"},
        "mysql": {"value": "MYSQL"},
        "mssql": {"value": "MSSQL"},
        "db2": {"value": "UNKNOWN"},
    },
    "server_type": {
        "bare metal": {"value": "PHYSICAL"},
        "virtual machine": {"value": "VIRTUAL"},
        "physical": {"value": "PHYSICAL"},
        "virtual": {"value": "VIRTUAL"},
        "vm": {"value": "VIRTUAL"},
        "container": {"value": "UNKNOWN"},
    },
    "environment": {
        "production": {"value": "PRODUCTION"},
        "non-production": {"value": "NON_PRODUCTION"},
        "staging": {"value": "STAGING"},
        "development": {"value": "DEVELOPMENT"},
        "test": {"value": "TEST"},
        "uat": {"value": "UAT"},
    },
    "storage_type": {
        "san": {"value": "SAN"},
        "nas": {"value": "NAS"},
        "local disk": {"value": "LOCAL"},
        "local": {"value": "LOCAL"},
        "s3": {"value": "OBJECT_STORE"},
    },
}

_MOCK_FIXTURE_VERSION = "v1.0"


# ---------------------------------------------------------------------------
# Grounding utilities
# ---------------------------------------------------------------------------


def validate_grounding(grounding_quote: str, source_fragment: str) -> bool:
    """
    Return True when grounding_quote is a non-empty substring of source_fragment.

    Args:
        grounding_quote: Proposed evidence quote from an AI mapping.
        source_fragment: The original bounded text from the evidence source.

    Returns:
        True if grounding_quote appears verbatim in source_fragment and both
        are non-empty; False otherwise.
    """
    if not grounding_quote or not source_fragment:
        return False
    return grounding_quote in source_fragment


def _find_in_fragment(keyword: str, fragment: str) -> str | None:
    """
    Locate keyword in fragment using case-insensitive search.

    Returns the verbatim matched substring from fragment (preserving original
    casing), so the returned string is guaranteed to be in the fragment.

    Args:
        keyword: Lowercase keyword to search for.
        fragment: Original source text to search within.

    Returns:
        The exact substring from fragment that matches the keyword, or None.
    """
    lower_fragment = fragment.lower()
    lower_keyword = keyword.lower()
    idx = lower_fragment.find(lower_keyword)
    if idx >= 0:
        return fragment[idx : idx + len(keyword)]
    return None


# ---------------------------------------------------------------------------
# Hash utility
# ---------------------------------------------------------------------------


def _deterministic_hash(data: Any) -> str:
    """Return a SHA-256 hex digest of the canonical sorted-key JSON of data."""
    canonical = json.dumps(data, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# MockCandidateMapper
# ---------------------------------------------------------------------------


class MockCandidateMapper:
    """
    Deterministic, fixture-based CandidateMapper for tests and local development.

    For each question in question_definitions the mapper scans source_fragment
    for known keywords. When a keyword is found, the verbatim matched substring
    becomes the grounding_quote and a fixture value is proposed.

    Questions with no registry entry produce a warning and no mapping.
    Questions in the registry with no keyword match produce an unmapped entry.
    When no mappings are produced, validation_status is GROUNDING_FAILED.

    All output is candidate only; this mapper never produces canonical answers.
    """

    def map(self, request: MappingRequest) -> MappingResult:
        """
        Produce candidate mappings for the given MappingRequest.

        Args:
            request: The mapping request with source fragment and question
                     definitions.

        Returns:
            MappingResult with proposed_mappings, grounding_quotes, warnings,
            unmapped_fragments, raw_response_hash, and validation_status.
        """
        proposed_mappings: list[ProposedMapping] = []
        warnings: list[str] = []
        unmapped_fragments: list[str] = []

        for question in request.question_definitions:
            qid = question.get("id", "")
            registry_entry = _KEYWORD_REGISTRY.get(qid)

            if registry_entry is None:
                warnings.append(
                    f"No fixture for question_id={qid!r}; skipping this question."
                )
                continue

            # Search keywords in insertion order (deterministic)
            matched: ProposedMapping | None = None
            for keyword, value_dict in registry_entry.items():
                found_quote = _find_in_fragment(keyword, request.source_fragment)
                if found_quote is not None:
                    matched = ProposedMapping(
                        question_id=qid,
                        proposed_value=dict(value_dict),
                        confidence_metadata={
                            "fixture_version": _MOCK_FIXTURE_VERSION,
                            "matched_keyword": keyword,
                        },
                        grounding_quote=found_quote,
                        source_locator=request.source_locator,
                    )
                    break

            if matched is not None:
                proposed_mappings.append(matched)
            else:
                unmapped_fragments.append(
                    f"No keyword match for question_id={qid!r} in source fragment."
                )

        # Collect all grounding quotes
        grounding_quotes = [m.grounding_quote for m in proposed_mappings]

        # Determine validation status
        validation_status = "VALID" if proposed_mappings else "GROUNDING_FAILED"

        # Compute a deterministic audit hash of the fixture response
        raw_response = {
            "request_id": request.request_id,
            "fixture_version": _MOCK_FIXTURE_VERSION,
            "mappings": [m.model_dump() for m in proposed_mappings],
            "warnings": warnings,
            "unmapped_fragments": unmapped_fragments,
        }
        raw_response_hash = _deterministic_hash(raw_response)

        return MappingResult(
            request_id=request.request_id,
            provider="mock",
            model_metadata={
                "fixture_version": _MOCK_FIXTURE_VERSION,
                "provider": "mock",
            },
            proposed_mappings=proposed_mappings,
            unmapped_fragments=unmapped_fragments,
            warnings=warnings,
            grounding_quotes=grounding_quotes,
            raw_response_hash=raw_response_hash,
            validation_status=validation_status,
        )
