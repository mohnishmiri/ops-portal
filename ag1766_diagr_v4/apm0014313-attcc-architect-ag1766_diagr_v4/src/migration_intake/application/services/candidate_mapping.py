"""
Candidate mapping application service (PAI-4).

Builds bounded mapping requests from eligible evidence fragments, validates
provider output locally, and stages candidate-only proposals through a port.
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from migration_intake.ai.models import MappingRequest, MappingResult

if TYPE_CHECKING:
    from migration_intake.ai.port import CandidateMapper
    from migration_intake.application.ports import CandidateStagingPort


class CandidateMappingPolicyError(Exception):
    """Raised when mapping command policy constraints are violated."""


class CandidateMappingValidationError(Exception):
    """Raised when mapper output fails local validation rules."""


@dataclass(frozen=True)
class MappingFragment:
    """One bounded input fragment eligible for mapping."""

    source_fragment: str
    source_locator: str
    source_type: str
    classification: str = "SYNTHETIC"


@dataclass(frozen=True)
class CandidateMappingCommand:
    """Application command for a candidate-only mapping run."""

    application_id: str
    intake_id: str
    evidence_item_id: str
    import_run_id: str
    actor_id: str
    prompt_template_version: str
    fragments: tuple[MappingFragment, ...]
    question_definitions: tuple[dict[str, Any], ...]
    response_schemas: tuple[dict[str, Any], ...]
    allowed_values: dict[str, list[str]]


@dataclass(frozen=True)
class CandidateMappingServiceResult:
    """Summary returned after staging candidate proposals/findings."""

    mapping_request_count: int
    staged_candidate_count: int
    staged_finding_count: int
    request_hash: str
    response_hash: str
    attempt_count: int


class CandidateMappingService:
    """Coordinates mapper requests, output validation, and candidate staging."""

    def __init__(
        self,
        *,
        mapper: CandidateMapper,
        staging_port: CandidateStagingPort,
        max_fragment_chars: int,
        max_requests_per_import: int,
    ) -> None:
        self._mapper = mapper
        self._staging = staging_port
        self._max_fragment_chars = max_fragment_chars
        self._max_requests_per_import = max_requests_per_import

    def run(self, command: CandidateMappingCommand) -> CandidateMappingServiceResult:
        """
        Execute candidate mapping over bounded fragments.

        Only candidate proposals/findings are staged; no canonical answer writes
        occur at this service boundary.
        """
        if len(command.fragments) > self._max_requests_per_import:
            raise CandidateMappingPolicyError(
                "Fragment count exceeds max requests per import policy"
            )
        if not command.fragments:
            raise CandidateMappingPolicyError("At least one fragment is required")

        question_ids = {
            str(item.get("id"))
            for item in command.question_definitions
            if item.get("id")
        }
        if not question_ids:
            raise CandidateMappingPolicyError("No question definitions available for mapping")

        staged_candidates: list[dict[str, Any]] = []
        staged_findings: list[dict[str, Any]] = []
        request_count = 0
        request_hashes: list[str] = []
        response_hashes: list[str] = []

        for fragment in command.fragments:
            if len(fragment.source_fragment) > self._max_fragment_chars:
                raise CandidateMappingPolicyError(
                    "Fragment exceeds max fragment chars policy"
                )
            if not fragment.source_fragment.strip():
                staged_findings.append(
                    {
                        "finding_type": "EMPTY_FRAGMENT",
                        "severity": "WARNING",
                        "message": "Fragment contains no text",
                        "source_locator": fragment.source_locator,
                    }
                )
                continue

            request = MappingRequest(
                request_id=str(uuid.uuid4()),
                source_fragment=fragment.source_fragment,
                source_locator=fragment.source_locator,
                source_type=fragment.source_type,
                application_scope=command.application_id,
                question_definitions=[dict(item) for item in command.question_definitions],
                response_schemas=[dict(item) for item in command.response_schemas],
                allowed_values=command.allowed_values,
                prompt_template_version=command.prompt_template_version,
                classification=fragment.classification,
            )
            request_count += 1
            request_hashes.append(
                hashlib.sha256(
                    (
                        f"{request.source_fragment}|{request.source_locator}|"
                        f"{request.source_type}|{request.classification}"
                    ).encode()
                ).hexdigest()
            )
            result = self._mapper.map(request)
            self._validate_result(result=result, request=request, question_ids=question_ids)
            response_hashes.append(result.raw_response_hash)

            for mapping in result.proposed_mappings:
                staged_candidates.append(
                    {
                        "target_kind": "QUESTION",
                        "target_key": mapping.question_id,
                        "raw_value_json": mapping.proposed_value,
                        "normalized_value_json": mapping.proposed_value,
                        "scope_json": {"scope": "APPLICATION"},
                        "source_locator": mapping.source_locator,
                        "origin": f"AI:{result.provider}",
                        "validation_json": {
                            "validation_status": result.validation_status,
                            "request_id": result.request_id,
                            "response_hash": result.raw_response_hash,
                        },
                        "confidence": None,
                    }
                )

            for warning in result.warnings:
                staged_findings.append(
                    {
                        "finding_type": "MAPPER_WARNING",
                        "severity": "WARNING",
                        "message": warning,
                        "source_locator": fragment.source_locator,
                    }
                )

        self._staging.stage_mapping_batch(
            application_id=command.application_id,
            intake_id=command.intake_id,
            evidence_item_id=command.evidence_item_id,
            import_run_id=command.import_run_id,
            origin="AI_MAPPING_SERVICE",
            proposals=staged_candidates,
            findings=staged_findings,
        )

        aggregate_request_hash = hashlib.sha256(
            "|".join(request_hashes).encode("utf-8")
        ).hexdigest()
        aggregate_response_hash = hashlib.sha256(
            "|".join(response_hashes).encode("utf-8")
        ).hexdigest()

        return CandidateMappingServiceResult(
            mapping_request_count=request_count,
            staged_candidate_count=len(staged_candidates),
            staged_finding_count=len(staged_findings),
            request_hash=aggregate_request_hash,
            response_hash=aggregate_response_hash,
            attempt_count=max(1, request_count),
        )

    @staticmethod
    def _validate_result(
        *,
        result: MappingResult,
        request: MappingRequest,
        question_ids: set[str],
    ) -> None:
        if result.request_id != request.request_id:
            raise CandidateMappingValidationError("Mapper result request_id mismatch")

        for mapping in result.proposed_mappings:
            if mapping.question_id not in question_ids:
                raise CandidateMappingValidationError(
                    f"Mapper returned unknown question_id: {mapping.question_id}"
                )
            if mapping.grounding_quote not in request.source_fragment:
                raise CandidateMappingValidationError(
                    "Mapper returned grounding_quote not present in source fragment"
                )
            if mapping.source_locator != request.source_locator:
                raise CandidateMappingValidationError(
                    "Mapper returned source_locator that does not match request locator"
                )
