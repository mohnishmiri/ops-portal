"""
AI mapping routes (PAI-6).

Provides a capability-gated command for synthetic candidate mapping that stages
only PROPOSED candidates plus redacted lineage metadata.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Annotated, Any

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import RedirectResponse

from migration_intake.ai.errors import OutboundAIDisabledError
from migration_intake.application.dto import ActorContext
from migration_intake.application.services.candidate_mapping import (
    CandidateMappingCommand,
    CandidateMappingPolicyError,
    CandidateMappingService,
    CandidateMappingValidationError,
    MappingFragment,
)
from migration_intake.persistence.models_candidates import Candidate, CandidateFinding
from migration_intake.persistence.repositories.ai_mapping_runs import AIMappingRunRepository
from migration_intake.persistence.repositories.catalogs import CatalogRepository
from migration_intake.persistence.repositories.evidence import EvidenceRepository
from migration_intake.persistence.repositories.imports import ImportRepository
from migration_intake.persistence.repositories.intakes import IntakeRepository
from migration_intake.web.security import (
    CONFIGURED_ACTOR_CAPABILITIES,
    Capability,
    require_capability,
    validate_csrf_token,
)

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

router = APIRouter(tags=["AI Mapping"])


def _actor_from_request(request: Request) -> ActorContext:
    settings = request.app.state.settings
    return ActorContext(
        actor_id=settings.actor_id,
        display_name=settings.actor_display_name,
        role_codes=frozenset(c.value for c in CONFIGURED_ACTOR_CAPABILITIES),
    )


def _catalog_subset(
    session: Session,
    catalog_id: str,
) -> tuple[list[dict], list[dict], dict[str, list[str]]]:
    catalog = CatalogRepository(session)
    sections = catalog.get_sections_for_release(catalog_id)
    question_definitions: list[dict] = []
    response_schemas: list[dict] = []
    allowed_values: dict[str, list[str]] = {}
    for section in sections:
        questions = catalog.get_questions_for_section(section["id"])
        for question in questions:
            if not question.get("is_active", True):
                continue
            code = question["question_code"]
            question_definitions.append(
                {
                    "id": code,
                    "label": question["question_text"],
                    "response_type": question["response_type"],
                }
            )
            response_schemas.append(
                {
                    "question_id": code,
                    "response_type": question["response_type"],
                    "schema_version": question.get("response_schema_version") or "1.0",
                }
            )
            allowed_values[code] = []
    return question_definitions, response_schemas, allowed_values


class _DatabaseCandidateStagingPort:
    """Repository-backed candidate staging port for AI mapping batches."""

    def __init__(
        self,
        *,
        session_factory: Any,
        actor_id: str,
        extractor_version: str,
        contract_version: str,
    ) -> None:
        self._session_factory = session_factory
        self._actor_id = actor_id
        self._extractor_version = extractor_version
        self._contract_version = contract_version

    def stage_mapping_batch(
        self,
        *,
        application_id: str,
        intake_id: str,
        evidence_item_id: str,
        import_run_id: str,
        origin: str,
        proposals: list[dict],
        findings: list[dict],
    ) -> None:
        del origin
        now = datetime.now(tz=UTC)
        with self._session_factory() as session:
            for proposal in proposals:
                candidate = Candidate(
                    id=str(uuid.uuid4()),
                    import_run_id=import_run_id,
                    application_id=application_id,
                    intake_id=intake_id,
                    evidence_item_id=evidence_item_id,
                    target_kind=proposal["target_kind"],
                    target_key=proposal["target_key"],
                    origin=proposal["origin"],
                    extractor_version=self._extractor_version,
                    contract_version=self._contract_version,
                    response_schema_version="1.0",
                    source_locator={"locator": proposal["source_locator"]},
                    raw_value_json=proposal["raw_value_json"],
                    normalized_value_json=proposal["normalized_value_json"],
                    scope_json=proposal.get("scope_json"),
                    confidence=proposal.get("confidence"),
                    validation_json=proposal.get("validation_json"),
                    state="PROPOSED",
                    row_version=1,
                    created_at=now,
                )
                session.add(candidate)

            for finding in findings:
                row = CandidateFinding(
                    id=str(uuid.uuid4()),
                    candidate_id=None,
                    import_run_id=import_run_id,
                    finding_type=finding["finding_type"],
                    severity=finding["severity"],
                    message=finding["message"],
                    details_json=None,
                    source_locator={"locator": finding.get("source_locator")},
                    created_at=now,
                )
                session.add(row)
            session.commit()


@router.post("/applications/{app_id}/intakes/{intake_id}/ai-mapping/run")
async def run_ai_mapping(
    request: Request,
    app_id: str,
    intake_id: str,
    actor: Annotated[ActorContext, Depends(_actor_from_request)],
    csrf_token: Annotated[str, Form(alias="_csrf_token")],
    source_fragment: Annotated[str, Form()],
    source_locator: Annotated[str, Form()] = "Manual:AI/Row:1",
    source_type: Annotated[str, Form()] = "manual_text",
) -> RedirectResponse:
    """Run capability-gated AI candidate mapping for one synthetic fragment."""
    settings = request.app.state.settings
    if not validate_csrf_token(csrf_token, settings.csrf_secret):
        raise HTTPException(status_code=403, detail="CSRF token invalid or expired")

    require_capability(set(actor.role_codes), Capability.AI_MAPPING_RUN)
    session_factory = request.app.state.session_factory

    with session_factory() as session:
        intake = IntakeRepository(session).get(intake_id)
        if intake is None or intake["application_id"] != app_id:
            raise HTTPException(status_code=404, detail="Intake not found")

        evidence_repo = EvidenceRepository(session)
        evidence_items = evidence_repo.list_for_intake(intake_id)
        if not evidence_items:
            raise HTTPException(
                status_code=400,
                detail="No evidence exists for this intake; upload evidence before AI mapping",
            )
        evidence_id = evidence_items[0]["id"]

        question_definitions, response_schemas, allowed_values = _catalog_subset(
            session, intake["catalog_id"]
        )

        import_run_id = str(uuid.uuid4())
        now = datetime.now(tz=UTC)
        ImportRepository(session).add_run(
            run_id=import_run_id,
            application_id=app_id,
            intake_id=intake_id,
            evidence_item_id=evidence_id,
            contract_name="AI_MAPPING_V1",
            parser_version="1.0.0",
            created_at=now,
            created_by_id=actor.actor_id,
        )

        ai_run_repo = AIMappingRunRepository(session)
        ai_run_id = str(uuid.uuid4())
        ai_run_repo.add_run(
            run_id=ai_run_id,
            application_id=app_id,
            intake_id=intake_id,
            evidence_item_id=evidence_id,
            provider_id=settings.llm_provider,
            profile_id=settings.llm_profile,
            model_id=settings.llm_model or "n/a",
            prompt_template_version="v1.0",
            classification="SYNTHETIC",
            fragment_count=1,
            started_at=now,
            created_by_id=actor.actor_id,
            created_at=now,
        )
        ai_run_repo.mark_running(ai_run_id)
        session.commit()

    staging_port = _DatabaseCandidateStagingPort(
        session_factory=session_factory,
        actor_id=actor.actor_id,
        extractor_version="ai-mapping-v1",
        contract_version=settings.workbook_contract_version,
    )
    service = CandidateMappingService(
        mapper=request.app.state.candidate_mapper,
        staging_port=staging_port,
        max_fragment_chars=settings.llm_max_fragment_chars,
        max_requests_per_import=settings.llm_max_requests_per_import,
    )

    try:
        result = service.run(
            CandidateMappingCommand(
                application_id=app_id,
                intake_id=intake_id,
                evidence_item_id=evidence_id,
                import_run_id=import_run_id,
                actor_id=actor.actor_id,
                prompt_template_version="v1.0",
                fragments=(
                    MappingFragment(
                        source_fragment=source_fragment,
                        source_locator=source_locator,
                        source_type=source_type,
                        classification="SYNTHETIC",
                    ),
                ),
                question_definitions=tuple(question_definitions),
                response_schemas=tuple(response_schemas),
                allowed_values=allowed_values,
            )
        )
    except (
        OutboundAIDisabledError,
        CandidateMappingPolicyError,
        CandidateMappingValidationError,
    ) as exc:
        with session_factory() as session:
            ImportRepository(session).update_run_state(
                import_run_id,
                "FAILED",
                total_sheets=1,
                total_candidates=0,
                total_findings=1,
                completed_at=datetime.now(tz=UTC),
            )
            AIMappingRunRepository(session).mark_failed(
                ai_run_id,
                attempt_count=1,
                failure_category=type(exc).__name__,
                failure_detail_redacted=str(exc)[:255],
                finished_at=datetime.now(tz=UTC),
                metrics_json={"source_type": source_type},
            )
            session.commit()
        raise HTTPException(
            status_code=403,
            detail="AI mapping is unavailable for this profile",
        ) from exc

    with session_factory() as session:
        ImportRepository(session).update_run_state(
            import_run_id,
            "COMPLETED",
            total_sheets=1,
            total_candidates=result.staged_candidate_count,
            total_findings=result.staged_finding_count,
            completed_at=datetime.now(tz=UTC),
        )
        AIMappingRunRepository(session).mark_completed(
            ai_run_id,
            request_hash=result.request_hash,
            response_hash=result.response_hash,
            attempt_count=result.attempt_count,
            candidate_count=result.staged_candidate_count,
            finding_count=result.staged_finding_count,
            finished_at=datetime.now(tz=UTC),
            metrics_json={"source_type": source_type},
        )
        session.commit()

    return RedirectResponse(
        url=(
            f"/applications/{app_id}/intakes/{intake_id}/imports/{import_run_id}"
            "?upload_message=AI+mapping+completed&upload_message_type=success"
        ),
        status_code=status.HTTP_303_SEE_OTHER,
    )
