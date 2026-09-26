"""
Provider-backed CandidateMapper built on StructuredCompletionClient.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from migration_intake.ai.completion import (
    StructuredCompletionClient,
    StructuredCompletionRequest,
)
from migration_intake.ai.models import MappingRequest, MappingResult, ProposedMapping
from migration_intake.ai.port import CandidateMapper


class ProviderBackedCandidateMapper(CandidateMapper):
    """Map candidates via provider-neutral completion capability."""

    def __init__(
        self,
        *,
        completion_client: StructuredCompletionClient,
        provider_id: str,
        model_id: str,
    ) -> None:
        self._completion_client = completion_client
        self._provider_id = provider_id
        self._model_id = model_id

    def map(self, request: MappingRequest) -> MappingResult:
        question_ids = [
            q.get("id")
            for q in request.question_definitions
            if isinstance(q, dict) and q.get("id")
        ]
        system_instruction = (
            "You are a structured extraction assistant. "
            "Return JSON only with keys: proposed_mappings, warnings, unmapped_fragments."
        )
        user_content = (
            f"Source fragment:\n{request.source_fragment}\n\n"
            f"Source locator: {request.source_locator}\n"
            f"Questions: {', '.join(str(q) for q in question_ids)}\n"
            "Return proposed mappings with question_id, proposed_value, grounding_quote."
        )
        request_hash = hashlib.sha256(
            (
                f"{request.source_fragment}|{request.source_locator}|"
                f"{request.source_type}|{request.classification}|{request.prompt_template_version}"
            ).encode()
        ).hexdigest()
        completion = self._completion_client.complete(
            StructuredCompletionRequest(
                request_id=request.request_id,
                correlation_id=request.request_id,
                provider_id=self._provider_id,
                model_id=self._model_id,
                system_instruction=system_instruction,
                user_content=user_content,
                classification=request.classification,
                prompt_template_version=request.prompt_template_version,
                request_content_hash=request_hash,
            )
        )
        payload = _parse_completion_payload(completion.normalized_content)

        proposed_mappings: list[ProposedMapping] = []
        warnings: list[str] = [str(item) for item in payload.get("warnings", [])]
        unmapped: list[str] = [
            str(item) for item in payload.get("unmapped_fragments", [])
        ]

        for item in payload.get("proposed_mappings", []):
            if not isinstance(item, dict):
                warnings.append("Ignoring non-dict proposed mapping entry")
                continue
            question_id = str(item.get("question_id") or "").strip()
            grounding_quote = str(item.get("grounding_quote") or "").strip()
            if not question_id:
                warnings.append("Ignoring mapping without question_id")
                continue
            if grounding_quote not in request.source_fragment:
                warnings.append(f"Ignoring mapping with non-verbatim grounding for {question_id}")
                continue
            proposed_value = item.get("proposed_value")
            if not isinstance(proposed_value, dict):
                warnings.append(
                    f"Ignoring mapping with non-object proposed_value for {question_id}"
                )
                continue
            proposed_mappings.append(
                ProposedMapping(
                    question_id=question_id,
                    proposed_value=proposed_value,
                    confidence_metadata={
                        "provider_id": completion.provider_id,
                        "model_id": completion.model_id,
                        "validation_status": completion.validation_status,
                    },
                    grounding_quote=grounding_quote,
                    source_locator=request.source_locator,
                )
            )

        validation_status = "VALID" if proposed_mappings else "GROUNDING_FAILED"
        return MappingResult(
            request_id=request.request_id,
            provider=completion.provider_id,
            model_metadata={
                "provider_id": completion.provider_id,
                "model_id": completion.model_id,
                "provider_request_id": completion.provider_request_id,
                "attempt_count": completion.attempt_count,
                "latency_bucket": completion.latency_bucket,
            },
            proposed_mappings=proposed_mappings,
            unmapped_fragments=unmapped,
            warnings=warnings,
            grounding_quotes=[m.grounding_quote for m in proposed_mappings],
            raw_response_hash=completion.response_hash,
            validation_status=validation_status,
        )


def _parse_completion_payload(content: str) -> dict[str, Any]:
    try:
        data = json.loads(content)
    except (ValueError, json.JSONDecodeError):
        return {
            "proposed_mappings": [],
            "warnings": ["Provider returned non-JSON content"],
            "unmapped_fragments": [],
        }
    if not isinstance(data, dict):
        return {
            "proposed_mappings": [],
            "warnings": ["Provider returned non-object JSON content"],
            "unmapped_fragments": [],
        }
    return data
