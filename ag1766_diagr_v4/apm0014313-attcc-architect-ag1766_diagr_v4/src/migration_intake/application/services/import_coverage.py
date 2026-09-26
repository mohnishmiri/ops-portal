"""Read-only coverage summary for one auditable import run."""
from __future__ import annotations

from collections import Counter
from typing import Any

from sqlalchemy.orm import sessionmaker

from migration_intake.imports.legacy_intake_mappings_v1 import canonical_target_key
from migration_intake.persistence.repositories.candidates import CandidateRepository
from migration_intake.persistence.repositories.catalogs import CatalogRepository
from migration_intake.persistence.repositories.imports import ImportRepository
from migration_intake.persistence.repositories.intakes import IntakeRepository


class ImportCoverageService:
    """Compute exact proposal, finding, and required-question coverage for a run."""

    def __init__(self, session_factory: sessionmaker) -> None:
        self._session_factory = session_factory

    def get_run_coverage(self, run_id: str) -> dict[str, Any] | None:
        session = self._session_factory()
        try:
            run = ImportRepository(session).get_run(run_id)
            if run is None or run["intake_id"] is None:
                return None
            intake = IntakeRepository(session).get(run["intake_id"])
            if intake is None:
                return None
            catalog = CatalogRepository(session)
            all_questions = [
                question
                for section in catalog.get_sections_for_release(intake["catalog_id"])
                for question in catalog.get_questions_for_section(section["id"])
            ]
            questions = [
                question
                for question in all_questions
                if question["required_level"] == "REQUIRED" and question["is_active"]
            ]
            # A reviewer cannot judge a proposed value from a question code
            # alone, so the question's text travels with every candidate.
            question_text_by_code = {
                question["question_code"]: question["question_text"]
                for question in all_questions
            }
            candidates = [
                self._candidate_to_dict(candidate, question_text_by_code)
                for candidate in CandidateRepository(session).get_by_run(run_id)
            ]
            findings = ImportRepository(session).list_findings_for_run(run_id)
            question_candidates = [
                candidate
                for candidate in candidates
                if candidate["target_kind"] == "QUESTION"
            ]
            review_questions = [
                {
                    "code": question["question_code"],
                    "text": question["question_text"],
                    "required_level": question["required_level"],
                    "is_active": question["is_active"],
                    "section_code": next(
                        section["section_code"]
                        for section in catalog.get_sections_for_release(intake["catalog_id"])
                        if section["id"] == question["section_id"]
                    ),
                }
                for question in all_questions
                if question["is_active"]
                and question["required_level"] in {"REQUIRED", "CONDITIONAL"}
            ]
            candidate_counts = Counter(candidate["state"] for candidate in candidates)
            proposed_targets = {candidate["target_key"] for candidate in question_candidates}
            return {
                "run_id": run_id,
                "identity_decision": run["identity_decision"],
                "candidate_counts": dict(candidate_counts),
                "candidates": candidates,
                "finding_counts": dict(Counter(finding["finding_type"] for finding in findings)),
                "required_question_count": len(questions),
                "proposed_question_count": len(proposed_targets),
                "remaining_required_question_count": sum(
                    question["question_code"] not in proposed_targets
                    for question in questions
                ),
                "review_questions": review_questions,
                "question_count": len(review_questions),
            }
        finally:
            session.close()

    @staticmethod
    def _candidate_to_dict(
        candidate: Any, question_text_by_code: dict[str, str]
    ) -> dict[str, Any]:
        """Return one candidate as a plain dict, annotated with its question text."""
        scope = candidate.scope_json
        target_key = canonical_target_key(candidate.target_key)
        return {
            "id": str(candidate.id),
            "target_kind": candidate.target_kind,
            "target_key": target_key,
            "question_text": (
                question_text_by_code.get(target_key)
                if candidate.target_kind == "QUESTION"
                else None
            ),
            "state": candidate.state,
            "scope_json": scope,
            "is_application_scoped": (
                bool(scope) and scope.get("scope") == "APPLICATION"
            ) or (
                candidate.origin == "legacy_intake_v1"
                and target_key in question_text_by_code
            ),
            "raw_value_json": candidate.raw_value_json,
            "normalized_value_json": candidate.normalized_value_json,
            "validation_json": candidate.validation_json,
            "source_locator": candidate.source_locator,
            "row_version": candidate.row_version,
        }
