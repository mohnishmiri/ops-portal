"""
Intake hub read model (UX-2).

The hub is the intake's landing page. Its job is orientation: how much of the
questionnaire is actually done, how many imported proposals are sitting
undecided, and how much work only a person can do. A user with 17 pending
proposals previously concluded the import had silently failed, because nothing
on any page counted them.

Every number here is derived from the database. Three of them carry enough
weight that they are defined once, in this module, and nowhere else:

``required_answered`` / ``required_total``
    Questions whose ``required_level`` is ``REQUIRED``, and of those the ones
    holding a current answer revision with a non-empty payload. An answer that
    was cleared (``response_json == {}``) still owns a revision, so revision
    existence alone would overstate progress.

``pending_proposals``
    Candidates for this intake in state ``PROPOSED`` that target a question.
    These are the decisions the evidence pipeline is waiting on.

``needs_person``
    Required questions that are **not** a computed response type and have no
    proposal available. Nothing in an imported file can answer these; they need
    an architect or an owner. Computed types are excluded because they are
    derived from registers — ``AnswerService`` refuses to save them — and
    counting them as outstanding human work is simply wrong.

Computed-ness is never a hard-coded list: it is read from
``get_default_registry().get(code).is_computed``.

This service is deliberately separate from ``application/queries.py``: the hub
aggregates across every section at once, where that module's read models are
per-section, and keeping them apart lets the two evolve independently.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import and_, func, select
from sqlalchemy.orm import sessionmaker

#: ``required_level`` value that makes a question count toward the hub totals.
REQUIRED_LEVEL = "REQUIRED"

#: Candidate state meaning "a human has not decided about this yet".
PROPOSED_STATE = "PROPOSED"

#: Candidate ``target_kind`` for question-scoped proposals.
QUESTION_TARGET = "QUESTION"


class IntakeHubService:
    """
    Aggregate read model behind ``GET /applications/{app}/intakes/{intake}``.

    Returns plain dicts — no ORM entities and no lazy relationships — so the
    template cannot accidentally issue further queries while rendering.
    """

    def __init__(self, session_factory: sessionmaker) -> None:
        self._session_factory = session_factory

    # ------------------------------------------------------------------
    # get_intake_hub
    # ------------------------------------------------------------------

    def get_intake_hub(self, intake_id: str) -> dict[str, Any] | None:
        """
        Return the hub read model for one intake, or ``None`` if not found.

        Shape::

            {
              "application": {id, display_name, state, correlation_id},
              "intake": {id, state, catalog_version},
              "totals": {
                 required_total, required_answered, required_percent,
                 computed_required, pending_proposals, needs_person,
              },
              "sections": [{
                 code, title, display_order,
                 required_total, required_answered, required_percent,
                 computed_required, all_computed, has_required,
                 pending_proposals, needs_person,
              }],
              "continue_section": section_code | None,
              "needs_person_section": section_code | None,
            }

        Query count is bounded and independent of catalog size: one select for
        the intake, one for the application, one for the catalog release, one
        for identifiers, one for sections, one join for questions-with-answers,
        one grouped count for proposals.
        """
        from migration_intake.catalog.response_types import get_default_registry
        from migration_intake.persistence.models import (
            AnswerInstance,
            AnswerRevision,
            Application,
            ApplicationIdentifier,
            CatalogQuestion,
            CatalogRelease,
            CatalogSection,
            Intake,
        )
        from migration_intake.persistence.models_candidates import Candidate

        session = self._session_factory()
        try:
            intake = session.execute(
                select(Intake).where(Intake.id == intake_id)
            ).scalar_one_or_none()
            if intake is None:
                return None

            application = session.execute(
                select(Application).where(Application.id == intake.application_id)
            ).scalar_one_or_none()
            if application is None:
                return None

            catalog = session.execute(
                select(CatalogRelease).where(CatalogRelease.id == intake.catalog_id)
            ).scalar_one_or_none()

            correlation_id = session.execute(
                select(ApplicationIdentifier.raw_value)
                .where(
                    ApplicationIdentifier.application_id == intake.application_id,
                    ApplicationIdentifier.identifier_type == "CORRELATION",
                )
                .limit(1)
            ).scalar_one_or_none()

            # --- sections -------------------------------------------------
            # Loaded separately from questions so a section with no questions
            # still appears (an inner join would silently drop it).
            section_rows = session.execute(
                select(
                    CatalogSection.section_code,
                    CatalogSection.display_name,
                    CatalogSection.display_order,
                )
                .where(CatalogSection.release_id == intake.catalog_id)
                .order_by(
                    CatalogSection.display_order.asc(),
                    CatalogSection.section_code.asc(),
                )
            ).mappings().all()

            # --- questions with their current answer ----------------------
            question_rows = session.execute(
                select(
                    CatalogSection.section_code,
                    CatalogQuestion.question_code,
                    CatalogQuestion.response_type,
                    CatalogQuestion.required_level,
                    CatalogQuestion.display_order,
                    AnswerInstance.current_rev_id,
                    AnswerRevision.response_json,
                )
                .select_from(CatalogSection)
                .join(CatalogQuestion, CatalogQuestion.section_id == CatalogSection.id)
                .outerjoin(
                    AnswerInstance,
                    and_(
                        AnswerInstance.question_id == CatalogQuestion.id,
                        AnswerInstance.intake_id == intake_id,
                    ),
                )
                .outerjoin(
                    AnswerRevision,
                    AnswerRevision.id == AnswerInstance.current_rev_id,
                )
                .where(CatalogSection.release_id == intake.catalog_id)
                .order_by(
                    CatalogSection.display_order.asc(),
                    CatalogQuestion.display_order.asc(),
                    CatalogQuestion.question_code.asc(),
                )
            ).mappings().all()

            # --- pending proposals, grouped by the question they target ----
            proposals_by_code: dict[str, int] = {
                row["target_key"]: row["proposal_count"]
                for row in session.execute(
                    select(
                        Candidate.target_key,
                        func.count().label("proposal_count"),
                    )
                    .where(
                        Candidate.intake_id == intake_id,
                        Candidate.target_kind == QUESTION_TARGET,
                        Candidate.state == PROPOSED_STATE,
                    )
                    .group_by(Candidate.target_key)
                ).mappings().all()
            }

        finally:
            session.close()

        registry = get_default_registry()
        computed_cache: dict[str, bool] = {}

        def _is_computed(response_type: str) -> bool:
            """Registry lookup, memoised per response type."""
            if response_type not in computed_cache:
                spec = registry.get(response_type)
                computed_cache[response_type] = bool(spec and spec.is_computed)
            return computed_cache[response_type]

        # Accumulators, per section then rolled up.
        blank = {
            "required_total": 0,
            "required_answered": 0,
            "computed_required": 0,
            "needs_person": 0,
            "pending_proposals": 0,
        }
        tallies: dict[str, dict[str, int]] = {
            row["section_code"]: dict(blank) for row in section_rows
        }
        # First section (in display order) holding an unanswered required
        # question a person could actually answer.
        continue_section: str | None = None
        needs_person_section: str | None = None

        for row in question_rows:
            tally = tallies.setdefault(row["section_code"], dict(blank))
            # Proposals are counted for every question, required or not: an
            # optional question's proposal is still an undecided proposal.
            tally["pending_proposals"] += proposals_by_code.get(
                row["question_code"], 0
            )

            if row["required_level"] != REQUIRED_LEVEL:
                continue
            tally["required_total"] += 1

            # A cleared answer keeps its revision but holds an empty payload;
            # counting revision existence alone would overstate progress.
            answered = (
                row["current_rev_id"] is not None and bool(row["response_json"])
            )
            if answered:
                tally["required_answered"] += 1

            computed = _is_computed(row["response_type"])
            if computed:
                tally["computed_required"] += 1
                continue

            has_proposal = row["question_code"] in proposals_by_code
            if not has_proposal:
                tally["needs_person"] += 1
                if needs_person_section is None:
                    needs_person_section = row["section_code"]

            if not answered and continue_section is None:
                continue_section = row["section_code"]

        sections: list[dict[str, Any]] = []
        for row in section_rows:
            code = row["section_code"]
            tally = tallies[code]
            required_total = tally["required_total"]
            computed_required = tally["computed_required"]
            sections.append(
                {
                    "code": code,
                    "title": row["display_name"],
                    "display_order": row["display_order"],
                    "required_total": required_total,
                    "required_answered": tally["required_answered"],
                    "required_percent": _percent(
                        tally["required_answered"], required_total
                    ),
                    "computed_required": computed_required,
                    # "0 of 3" reads as unfinished work when in truth nobody
                    # can answer any of them; such a section says so instead.
                    "all_computed": (
                        required_total > 0 and computed_required == required_total
                    ),
                    "has_required": required_total > 0,
                    "pending_proposals": tally["pending_proposals"],
                    "needs_person": tally["needs_person"],
                }
            )

        required_total = sum(section["required_total"] for section in sections)
        required_answered = sum(section["required_answered"] for section in sections)

        return {
            "application": {
                "id": str(application.id),
                "display_name": application.display_name,
                "state": application.state,
                "correlation_id": correlation_id,
            },
            "intake": {
                "id": str(intake.id),
                "state": intake.state,
                "catalog_version": (
                    catalog.semantic_version if catalog is not None else None
                ),
            },
            "totals": {
                "required_total": required_total,
                "required_answered": required_answered,
                "required_percent": _percent(required_answered, required_total),
                "computed_required": sum(
                    section["computed_required"] for section in sections
                ),
                # Every undecided question proposal, including any whose target
                # code is no longer in the catalog: it still awaits a decision.
                "pending_proposals": sum(proposals_by_code.values()),
                "needs_person": sum(section["needs_person"] for section in sections),
            },
            "sections": sections,
            "continue_section": continue_section,
            "needs_person_section": needs_person_section,
        }


def _percent(part: int, whole: int) -> int:
    """Whole-number percentage that is 0 rather than an error when empty."""
    if whole <= 0:
        return 0
    return round(part * 100 / whole)
