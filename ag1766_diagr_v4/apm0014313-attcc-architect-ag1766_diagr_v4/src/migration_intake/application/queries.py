"""
Query objects and read DTOs.

Queries return purpose-built read DTOs and do not mutate state.
DTOs are optimized for specific UI/API needs.

ApplicationQueryService (A03) returns plain dicts — no ORM entities.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from migration_intake.domain.ids import (
    ApplicationId,
    IntakeId,
)
from migration_intake.domain.states import (
    AnswerApplicability,
    AnswerReviewState,
    AnswerValueState,
    ApplicationState,
    CandidateState,
    IntakeState,
)

# Read DTOs - optimized for specific views


@dataclass(frozen=True, slots=True)
class ApplicationSummaryDTO:
    """
    Summary view of an application for list views.

    Attributes:
        id: Application ID
        name: Application name
        acronym: Optional acronym
        state: Current state
        intake_count: Number of intakes
    """

    id: ApplicationId
    name: str
    acronym: str | None
    state: ApplicationState
    intake_count: int


@dataclass(frozen=True, slots=True)
class ApplicationDetailDTO:
    """
    Detailed view of an application.

    Attributes:
        id: Application ID
        name: Application name
        acronym: Optional acronym
        state: Current state
        external_ids: External identifiers
        portfolio: Portfolio name
        created_at: Creation timestamp
        updated_at: Last update timestamp
        active_intake: Active intake summary, if any
    """

    id: ApplicationId
    name: str
    acronym: str | None
    state: ApplicationState
    external_ids: list[ExternalIdDTO]
    portfolio: str | None
    created_at: datetime
    updated_at: datetime
    active_intake: IntakeSummaryDTO | None


@dataclass(frozen=True, slots=True)
class ExternalIdDTO:
    """External identifier DTO."""

    id_type: str
    value: str


@dataclass(frozen=True, slots=True)
class IntakeSummaryDTO:
    """
    Summary view of an intake for list views.

    Attributes:
        id: Intake ID
        application_id: Parent application ID
        state: Current state
        progress_percent: Completion percentage (0-100)
    """

    id: IntakeId
    application_id: ApplicationId
    state: IntakeState
    progress_percent: int


@dataclass(frozen=True, slots=True)
class IntakeDetailDTO:
    """
    Detailed view of an intake.

    Attributes:
        id: Intake ID
        application_id: Parent application ID
        catalog_version: Catalog version used
        state: Current state
        progress_percent: Completion percentage
        sections: Section summaries
        created_at: Creation timestamp
        updated_at: Last update timestamp
    """

    id: IntakeId
    application_id: ApplicationId
    catalog_version: str
    state: IntakeState
    progress_percent: int
    sections: list[SectionSummaryDTO]
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class SectionSummaryDTO:
    """Summary of a questionnaire section."""

    code: str
    title: str
    question_count: int
    answered_count: int
    confirmed_count: int
    has_issues: bool


@dataclass(frozen=True, slots=True)
class QuestionDTO:
    """
    Question view for questionnaire UI.

    Attributes:
        control_code: Control code (e.g., APP-001)
        question_text: Question text
        response_type: Response type code
        applicability: Whether question applies
        value_state: State of the answer value
        review_state: Review state
        current_value: Current answer value
        candidates: Pending candidates
        is_required: Whether answer is required
        condition_met: Whether display condition is met
    """

    control_code: str
    question_text: str
    response_type: str
    applicability: AnswerApplicability
    value_state: AnswerValueState
    review_state: AnswerReviewState
    current_value: object | None
    candidates: list[CandidateDTO]
    is_required: bool
    condition_met: bool


@dataclass(frozen=True, slots=True)
class CandidateDTO:
    """Candidate value DTO."""

    id: str
    value: object
    source: str
    confidence: float | None
    state: CandidateState
    created_at: datetime


# Query objects


@dataclass(frozen=True, slots=True)
class ListApplicationsQuery:
    """Query to list applications with optional filters."""

    state_filter: ApplicationState | None = None
    search_term: str | None = None
    page: int = 1
    page_size: int = 20


@dataclass(frozen=True, slots=True)
class GetApplicationQuery:
    """Query to get application details."""

    application_id: ApplicationId


@dataclass(frozen=True, slots=True)
class GetIntakeQuery:
    """Query to get intake details."""

    intake_id: IntakeId


@dataclass(frozen=True, slots=True)
class GetSectionQuestionsQuery:
    """Query to get questions for a section."""

    intake_id: IntakeId
    section_code: str


@dataclass(frozen=True, slots=True)
class SearchApplicationsQuery:
    """Query to search applications."""

    search_term: str
    include_archived: bool = False
    page: int = 1
    page_size: int = 20


# ===========================================================================
# A03 — Read-model query service
# ===========================================================================

# Intake states that are NOT "open" (terminal states).
_TERMINAL_INTAKE_STATES: tuple[str, ...] = ("FROZEN", "CANCELLED", "SUPERSEDED")


# ---------------------------------------------------------------------------
# Questionnaire presentation helpers (UX-1)
#
# The questionnaire page previously rendered raw storage: ``{'text': 'x'}``
# for a value, a full ISO timestamp for "last updated", and a candidate UUID
# inside the change reason. None of that is readable, and the UUID is noise a
# reviewer cannot act on, so the read model does the humanising once — in one
# place, where it can be tested — instead of in Jinja.
# ---------------------------------------------------------------------------

#: Payload keys that carry protocol meaning rather than a displayable value.
_NON_DISPLAY_KEYS: frozenset[str] = frozenset({"_unknown", "_empty"})

#: Typographic separators, written as escapes so this module stays ASCII
#: (ruff flags ambiguous punctuation literals).
_DOT = " · "
_CRUMB = " › "  # noqa: RUF001 - breadcrumb separator is intentional

#: Any UUID, in any surrounding prose. Change reasons written by candidate
#: acceptance embed the candidate id; it is meaningless to a human reader.
_UUID_PATTERN = re.compile(
    r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"
)


def _format_scalar(item: object) -> str:
    """Render one leaf of a response payload."""
    if item is None or item == "":
        return ""
    if isinstance(item, bool):
        return "Yes" if item else "No"
    if isinstance(item, dict):
        return _format_answer_summary(item)
    if isinstance(item, (list, tuple)):
        rendered = [_format_scalar(entry) for entry in item]
        rendered = [entry for entry in rendered if entry]
        if not rendered:
            return ""
        if all(not isinstance(entry, (dict, list)) for entry in item):
            return ", ".join(rendered)
        return f"{len(rendered)} entries"
    return str(item)


def _format_answer_summary(value: object) -> str:
    """
    Render a stored response payload as one human-readable line.

    Deliberately generic: nineteen response types share this collapsed row,
    and a per-type formatter that silently missed one would show ``{}``.
    """
    if not isinstance(value, dict) or not value:
        return ""
    if value.get("_unknown"):
        return "Unknown"
    parts: list[str] = []
    for key, item in value.items():
        if key in _NON_DISPLAY_KEYS:
            continue
        rendered = _format_scalar(item)
        if rendered:
            parts.append(rendered)
    return _DOT.join(parts)


def _relative_time(moment: datetime | None, *, now: datetime | None = None) -> str:
    """Render a timestamp as "4 minutes ago" rather than an ISO string."""
    if moment is None:
        return ""
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    reference = now or datetime.now(tz=UTC)
    seconds = (reference - moment).total_seconds()
    if seconds < 0:
        return "just now"
    for limit, divisor, unit in (
        (45, 1, None),
        (5400, 60, "minute"),
        (129600, 3600, "hour"),
        (2592000, 86400, "day"),
    ):
        if seconds < limit:
            if unit is None:
                return "just now"
            count = max(1, round(seconds / divisor))
            return f"{count} {unit}{'s' if count != 1 else ''} ago"
    return moment.strftime("%d %b %Y")


def _absolute_time(moment: datetime | None) -> str:
    """Render a timestamp for the provenance panel — readable, still exact."""
    if moment is None:
        return ""
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return moment.strftime("%d %b %Y, %H:%M UTC")


def _humanise_reason(reason: str | None) -> str:
    """Strip candidate UUIDs out of a change reason without losing its sense."""
    if not reason:
        return ""
    cleaned = _UUID_PATTERN.sub("", reason)
    cleaned = re.sub(r"\s{2,}", " ", cleaned).strip()
    # Trailing punctuation left behind by the removed id, incl. en/em dashes.
    return cleaned.rstrip(" -:,–—")  # noqa: RUF001


def _format_source_label(origin: str | None, locator: object) -> str:
    """Render a candidate's provenance as ``origin · Sheet > Column · row 4``."""
    parts: list[str] = []
    if origin:
        parts.append(str(origin))
    if isinstance(locator, dict):
        place = [
            str(locator[key])
            for key in ("sheet", "section", "column", "field", "cell")
            if locator.get(key)
        ]
        if place:
            parts.append(_CRUMB.join(place))
        if locator.get("row"):
            parts.append(f"row {locator['row']}")
    elif locator:
        parts.append(str(locator))
    return _DOT.join(parts)


class ApplicationQueryService:
    """
    Read-model query service (A03).

    All methods return plain dicts (no ORM entities, no lazy relationships,
    no datetime objects — converted to ISO strings).  No state is mutated.
    """

    def __init__(self, session_factory: sessionmaker) -> None:
        self._session_factory = session_factory

    # ------------------------------------------------------------------
    # list_applications
    # ------------------------------------------------------------------

    def list_applications(
        self,
        state_filter: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict]:
        """
        Return a paginated list of application summary dicts.

        Each dict: {id, display_name, state, created_at (ISO), open_intake_id | None}
        Ordered by created_at ASC, id ASC for a consistent tie-breaker.
        """
        from migration_intake.persistence.models import Application, ApplicationIdentifier, Intake

        session: Session = self._session_factory()
        try:
            # Subquery: one open intake per application (first match wins).
            open_intake_sq = (
                select(
                    Intake.application_id.label("app_id"),
                    Intake.id.label("open_intake_id"),
                )
                .where(Intake.state.not_in(_TERMINAL_INTAKE_STATES))
                .subquery()
            )

            # Subquery: first CORRELATION identifier per application.
            corr_sq = (
                select(
                    ApplicationIdentifier.application_id.label("app_id"),
                    ApplicationIdentifier.raw_value.label("correlation_id"),
                )
                .where(ApplicationIdentifier.identifier_type == "CORRELATION")
                .subquery()
            )

            stmt = (
                select(
                    Application.id,
                    Application.display_name,
                    Application.state,
                    Application.created_at,
                    open_intake_sq.c.open_intake_id,
                    corr_sq.c.correlation_id,
                )
                .outerjoin(
                    open_intake_sq,
                    Application.id == open_intake_sq.c.app_id,
                )
                .outerjoin(
                    corr_sq,
                    Application.id == corr_sq.c.app_id,
                )
                .order_by(Application.created_at.asc(), Application.id.asc())
                .limit(limit)
                .offset(offset)
            )

            if state_filter is not None:
                stmt = stmt.where(Application.state == state_filter)

            rows = session.execute(stmt).mappings().all()

            return [
                {
                    "id": str(row["id"]),
                    "display_name": row["display_name"],
                    "state": row["state"],
                    "created_at": row["created_at"].isoformat(),
                    "open_intake_id": (
                        str(row["open_intake_id"])
                        if row["open_intake_id"] is not None
                        else None
                    ),
                    "correlation_id": row["correlation_id"],
                }
                for row in rows
            ]
        finally:
            session.close()

    # ------------------------------------------------------------------
    # get_application_workspace
    # ------------------------------------------------------------------

    def get_application_workspace(self, application_id: str) -> dict | None:
        """
        Return a workspace view dict for one application, or None if not found.

        Dict shape:
          {id, display_name, state, row_version, created_at (ISO),
           identifiers: [{type, raw_value}],
           open_intake: {id, state, catalog_id} | None,
           evidence_count: int}
        """
        from migration_intake.persistence.models import (
            Application,
            ApplicationIdentifier,
            Intake,
        )
        from migration_intake.persistence.models_evidence import EvidenceItem

        session: Session = self._session_factory()
        try:
            # 1. Load application row.
            app_stmt = select(Application).where(Application.id == application_id)
            app = session.execute(app_stmt).scalar_one_or_none()
            if app is None:
                return None

            # 2. Load identifiers.
            ident_stmt = select(ApplicationIdentifier).where(
                ApplicationIdentifier.application_id == application_id
            )
            identifiers = session.execute(ident_stmt).scalars().all()

            # 3. Find the open intake (first non-terminal state).
            open_intake_stmt = select(Intake).where(
                Intake.application_id == application_id,
                Intake.state.not_in(_TERMINAL_INTAKE_STATES),
            )
            open_intake = session.execute(open_intake_stmt).scalar_one_or_none()

            # 4. Count ACTIVE evidence items.
            ev_count_stmt = select(func.count()).select_from(EvidenceItem).where(
                EvidenceItem.application_id == application_id,
                EvidenceItem.state == "ACTIVE",
            )
            evidence_count: int = session.execute(ev_count_stmt).scalar() or 0

            return {
                "id": str(app.id),
                "display_name": app.display_name,
                "state": app.state,
                "row_version": app.row_version,
                "created_at": app.created_at.isoformat(),
                "identifiers": [
                    {
                        "type": ident.identifier_type,
                        "raw_value": ident.raw_value,
                    }
                    for ident in identifiers
                ],
                "open_intake": (
                    {
                        "id": str(open_intake.id),
                        "state": open_intake.state,
                        "catalog_id": str(open_intake.catalog_id),
                    }
                    if open_intake is not None
                    else None
                ),
                "evidence_count": evidence_count,
            }
        finally:
            session.close()

    # ------------------------------------------------------------------
    # get_questionnaire_section
    # ------------------------------------------------------------------

    def get_questionnaire_section(
        self, intake_id: str, section_code: str
    ) -> dict | None:
        """
        Return a section view dict for one catalog section within an intake,
        or None if the intake is not found or the section_code is not in its catalog.

        Dict shape:
          {section_code, display_name,
           questions: [{question_code, question_text, response_type, required_level,
                        current_answer: {instance_id, revision_number, response_json,
                                         confirm_state, authored_at} | None}]}
        """
        from sqlalchemy import and_

        from migration_intake.persistence.models import (
            AnswerInstance,
            AnswerRevision,
            CatalogQuestion,
            CatalogSection,
            Intake,
        )

        session: Session = self._session_factory()
        try:
            # 1. Load intake to get catalog_id.
            intake_stmt = select(Intake).where(Intake.id == intake_id)
            intake = session.execute(intake_stmt).scalar_one_or_none()
            if intake is None:
                return None

            # 2. Find the section in this catalog.
            section_stmt = select(CatalogSection).where(
                CatalogSection.release_id == intake.catalog_id,
                CatalogSection.section_code == section_code,
            )
            section = session.execute(section_stmt).scalar_one_or_none()
            if section is None:
                return None

            # 3. JOIN questions → answer_instances (LEFT) → answer_revisions (LEFT).
            #    Single query, no N+1.
            stmt = (
                select(
                    CatalogQuestion.id.label("q_id"),
                    CatalogQuestion.question_code,
                    CatalogQuestion.question_text,
                    CatalogQuestion.response_type,
                    CatalogQuestion.required_level,
                    CatalogQuestion.display_order,
                    AnswerInstance.id.label("instance_id"),
                    AnswerRevision.id.label("revision_id"),
                    AnswerRevision.revision_number,
                    AnswerRevision.response_json,
                    AnswerRevision.confirm_state,
                    AnswerRevision.authored_at,
                )
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
                .where(CatalogQuestion.section_id == section.id)
                .order_by(CatalogQuestion.display_order.asc())
            )

            rows = session.execute(stmt).mappings().all()

            questions = []
            for row in rows:
                has_answer = (
                    row["instance_id"] is not None
                    and row["revision_id"] is not None
                )
                current_answer = (
                    {
                        "instance_id": str(row["instance_id"]),
                        "revision_number": row["revision_number"],
                        "response_json": row["response_json"],
                        "confirm_state": row["confirm_state"],
                        "authored_at": row["authored_at"].isoformat(),
                    }
                    if has_answer
                    else None
                )
                questions.append(
                    {
                        "question_code": row["question_code"],
                        "question_text": row["question_text"],
                        "response_type": row["response_type"],
                        "required_level": row["required_level"],
                        "current_answer": current_answer,
                    }
                )

            return {
                "section_code": section.section_code,
                "display_name": section.display_name,
                "questions": questions,
            }
        finally:
            session.close()

    # ------------------------------------------------------------------
    # get_questionnaire_page (A03b)
    # ------------------------------------------------------------------

    def get_questionnaire_page(
        self,
        intake_id: str,
        section_code: str | None = None,
    ) -> dict | None:
        """
        Return the full questionnaire page read model for UI04.

        This is the primary read model for the questionnaire UI. It returns
        all information needed to render a section page in bounded queries.

        Args:
            intake_id: The intake ID
            section_code: Optional section code. If None, returns first section.

        Returns:
            Dict with shape:
            {
                application: {id, display_name, state},
                intake: {id, state, row_version, catalog_version, catalog_hash},
                sections: [{code, title, display_order, question_count,
                           answered_count, confirmed_count, blocker_count}],
                current_section: {code, title, previous_code, next_code},
                questions: [{
                    question_id, code, text, help, display_order,
                    response_type, schema_version, editor_key, is_computed,
                    required_level, collection_mode, options, units, field_names,
                    applicability, applicability_reason,
                    owner_roles, source_labels, output_destinations,
                    current_answer: {
                        instance_id, row_version, revision_number, value,
                        value_state, review_state, actor_display_name,
                        updated_at, change_reason
                    } | None,
                    candidate_count, evidence_count, history_count
                }]
            }
            or None if intake not found.
        """
        from sqlalchemy import and_

        from migration_intake.catalog.response_types import get_default_registry
        from migration_intake.persistence.models import (
            Actor,
            AnswerInstance,
            AnswerRevision,
            Application,
            CatalogQuestion,
            CatalogRelease,
            CatalogSection,
            Intake,
        )

        session: Session = self._session_factory()
        try:
            # 1. Load intake with application and catalog.
            intake_stmt = select(Intake).where(Intake.id == intake_id)
            intake = session.execute(intake_stmt).scalar_one_or_none()
            if intake is None:
                return None

            app_stmt = select(Application).where(Application.id == intake.application_id)
            app = session.execute(app_stmt).scalar_one_or_none()
            if app is None:
                return None

            catalog_stmt = select(CatalogRelease).where(CatalogRelease.id == intake.catalog_id)
            catalog = session.execute(catalog_stmt).scalar_one_or_none()
            if catalog is None:
                return None

            # 2. Load all sections for this catalog with counts.
            sections_stmt = (
                select(CatalogSection)
                .where(CatalogSection.release_id == intake.catalog_id)
                .order_by(CatalogSection.display_order.asc())
            )
            sections = session.execute(sections_stmt).scalars().all()

            if not sections:
                return None

            registry = get_default_registry()

            # Per-section tallies for the side rail, in two grouped queries
            # rather than two more per section. The rail has to say how much
            # work a section actually holds: 37 of the catalog's 93 required
            # questions are computed types nobody can answer, so a raw
            # question count reads as workload that does not exist.
            derived_by_section: dict[str, int] = {}
            answerable_by_section: dict[str, int] = {}
            type_rows = session.execute(
                select(
                    CatalogQuestion.section_id,
                    CatalogQuestion.response_type,
                    func.count(),
                )
                .join(CatalogSection, CatalogSection.id == CatalogQuestion.section_id)
                .where(CatalogSection.release_id == intake.catalog_id)
                .group_by(CatalogQuestion.section_id, CatalogQuestion.response_type)
            ).all()
            for section_id, response_type_code, count in type_rows:
                key = str(section_id)
                response_type = registry.get(response_type_code)
                if response_type is not None and response_type.is_computed:
                    derived_by_section[key] = derived_by_section.get(key, 0) + count
                else:
                    answerable_by_section[key] = (
                        answerable_by_section.get(key, 0) + count
                    )

            from migration_intake.persistence.models_candidates import (
                Candidate as _Candidate,
            )

            proposals_by_section: dict[str, int] = {}
            proposal_rows = session.execute(
                select(CatalogQuestion.section_id, func.count())
                .select_from(_Candidate)
                .join(
                    CatalogQuestion,
                    CatalogQuestion.question_code == _Candidate.target_key,
                )
                .join(CatalogSection, CatalogSection.id == CatalogQuestion.section_id)
                .where(
                    _Candidate.intake_id == intake_id,
                    _Candidate.target_kind == "QUESTION",
                    _Candidate.state == "PROPOSED",
                    CatalogSection.release_id == intake.catalog_id,
                )
                .group_by(CatalogQuestion.section_id)
            ).all()
            for section_id, count in proposal_rows:
                proposals_by_section[str(section_id)] = count

            answered_by_section: dict[str, int] = {}
            answer_rows = session.execute(
                select(CatalogQuestion.section_id, AnswerRevision.response_json)
                .select_from(AnswerInstance)
                .join(CatalogQuestion, CatalogQuestion.id == AnswerInstance.question_id)
                .join(AnswerRevision, AnswerRevision.id == AnswerInstance.current_rev_id)
                .where(AnswerInstance.intake_id == intake_id)
            ).all()
            for section_id, response_json in answer_rows:
                if response_json:
                    key = str(section_id)
                    answered_by_section[key] = answered_by_section.get(key, 0) + 1

            # Build section summaries with counts.
            section_summaries = []
            section_map = {}
            summary_map: dict[str, dict] = {}
            for sec in sections:
                # Count questions in this section.
                q_count_stmt = select(func.count()).select_from(CatalogQuestion).where(
                    CatalogQuestion.section_id == sec.id
                )
                question_count = session.execute(q_count_stmt).scalar() or 0

                answered_count = answered_by_section.get(str(sec.id), 0)

                # Count confirmed answers.
                confirmed_stmt = (
                    select(func.count())
                    .select_from(AnswerInstance)
                    .join(CatalogQuestion, CatalogQuestion.id == AnswerInstance.question_id)
                    .join(AnswerRevision, AnswerRevision.id == AnswerInstance.current_rev_id)
                    .where(
                        CatalogQuestion.section_id == sec.id,
                        AnswerInstance.intake_id == intake_id,
                        AnswerRevision.confirm_state == "CONFIRMED",
                    )
                )
                confirmed_count = session.execute(confirmed_stmt).scalar() or 0

                answerable_count = answerable_by_section.get(str(sec.id), 0)
                derived_count = derived_by_section.get(str(sec.id), 0)
                if answerable_count == 0:
                    progress_state = "derived"
                elif answered_count >= answerable_count:
                    progress_state = "done"
                elif answered_count > 0:
                    progress_state = "part"
                else:
                    progress_state = "none"

                summary = {
                    "code": sec.section_code,
                    "title": sec.display_name,
                    "display_order": sec.display_order,
                    "question_count": question_count,
                    "answered_count": answered_count,
                    "confirmed_count": confirmed_count,
                    "blocker_count": 0,  # TODO: implement blocker tracking
                    "answerable_count": answerable_count,
                    "derived_count": derived_count,
                    "proposed_count": proposals_by_section.get(str(sec.id), 0),
                    "completed_count": answered_count,
                    "progress_state": progress_state,
                    "progress_percent": (
                        round(100 * min(answered_count, answerable_count) / answerable_count)
                        if answerable_count
                        else 0
                    ),
                }
                section_summaries.append(summary)
                section_map[sec.section_code] = sec
                summary_map[sec.section_code] = summary

            # 3. Determine current section.
            if section_code is None:
                current_section = sections[0]
            else:
                current_section = section_map.get(section_code)
                if current_section is None:
                    return None

            current_summary = summary_map[current_section.section_code]

            # Find previous/next sections.
            section_codes = [s.section_code for s in sections]
            current_idx = section_codes.index(current_section.section_code)
            previous_code = section_codes[current_idx - 1] if current_idx > 0 else None
            next_code = section_codes[current_idx + 1] if current_idx < len(section_codes) - 1 else None

            # 4. Load questions for current section with answers.
            stmt = (
                select(
                    CatalogQuestion.id.label("q_id"),
                    CatalogQuestion.question_code,
                    CatalogQuestion.question_text,
                    CatalogQuestion.help_text,
                    CatalogQuestion.response_type,
                    CatalogQuestion.required_level,
                    CatalogQuestion.collection_mode,
                    CatalogQuestion.display_order,
                    CatalogQuestion.units,
                    CatalogQuestion.field_name,
                    CatalogQuestion.response_schema_version,
                    AnswerInstance.id.label("instance_id"),
                    AnswerInstance.row_version.label("instance_row_version"),
                    AnswerRevision.id.label("revision_id"),
                    AnswerRevision.revision_number,
                    AnswerRevision.response_json,
                    AnswerRevision.confirm_state,
                    AnswerRevision.authored_at,
                    AnswerRevision.change_reason,
                    AnswerRevision.authored_by_id,
                )
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
                .where(CatalogQuestion.section_id == current_section.id)
                .order_by(CatalogQuestion.display_order.asc())
            )

            rows = session.execute(stmt).mappings().all()

            from migration_intake.persistence.models_candidates import Candidate

            question_codes = [row["question_code"] for row in rows]
            candidate_rows = []
            if question_codes:
                candidate_stmt = (
                    select(Candidate)
                    .where(
                        Candidate.intake_id == intake_id,
                        Candidate.target_kind == "QUESTION",
                        Candidate.target_key.in_(question_codes),
                    )
                    .order_by(Candidate.created_at.asc())
                )
                candidate_rows = session.execute(candidate_stmt).scalars().all()
            candidates_by_question: dict[str, list] = {}
            for candidate in candidate_rows:
                candidates_by_question.setdefault(candidate.target_key, []).append(candidate)

            # An import whose identity did not match this application keeps its
            # candidates for audit but they can never be accepted, so the
            # inline strip must not offer an Accept the route would refuse.
            identity_by_run: dict[str, str] = {}
            run_ids = {str(candidate.import_run_id) for candidate in candidate_rows}
            if run_ids:
                from migration_intake.persistence.models_imports import ImportRun

                run_rows = session.execute(
                    select(ImportRun.id, ImportRun.identity_decision).where(
                        ImportRun.id.in_(run_ids)
                    )
                ).all()
                identity_by_run = {str(row[0]): row[1] for row in run_rows}

            # Load every allowed value for this section in one query: a
            # controlled editor with no options cannot display or accept an
            # answer at all.
            from migration_intake.persistence.models import CatalogOption

            options_by_question: dict[str, list[dict[str, Any]]] = {}
            question_ids = [row["q_id"] for row in rows if row["q_id"]]
            if question_ids:
                option_stmt = (
                    select(CatalogOption)
                    .where(CatalogOption.question_id.in_(question_ids))
                    .order_by(CatalogOption.display_order.asc())
                )
                for option in session.execute(option_stmt).scalars().all():
                    options_by_question.setdefault(str(option.question_id), []).append(
                        {"value": option.option_code, "label": option.display_label}
                    )

            # Build actor cache for display names.
            actor_ids = {row["authored_by_id"] for row in rows if row["authored_by_id"]}
            actor_names = {}
            if actor_ids:
                actor_stmt = select(Actor).where(Actor.id.in_(actor_ids))
                actors = session.execute(actor_stmt).scalars().all()
                actor_names = {str(a.id): a.display_name for a in actors}

            questions = []
            for row in rows:
                response_type_code = row["response_type"]
                response_type = registry.get(response_type_code)

                has_current_revision = (
                    row["instance_id"] is not None
                    and row["revision_id"] is not None
                )
                has_answer = has_current_revision and bool(row["response_json"])

                current_answer = None
                if has_answer:
                    actor_id = row["authored_by_id"]
                    actor_name = actor_names.get(str(actor_id), "Unknown") if actor_id else "Unknown"

                    # Map confirm_state to value_state/review_state.
                    confirm_state = row["confirm_state"] or "DRAFT"
                    value_state = "ANSWERED" if row["response_json"] else "EMPTY"
                    review_state = confirm_state

                    current_answer = {
                        "instance_id": str(row["instance_id"]),
                        "row_version": row["instance_row_version"],
                        "revision_number": row["revision_number"],
                        "value": row["response_json"],
                        "value_state": value_state,
                        "review_state": review_state,
                        "actor_display_name": actor_name,
                        "updated_at": row["authored_at"].isoformat() if row["authored_at"] else None,
                        "change_reason": row["change_reason"],
                        # Humanised for display. The raw fields above stay so
                        # nothing that already reads them breaks.
                        "display_value": _format_answer_summary(row["response_json"]),
                        "updated_at_relative": _relative_time(row["authored_at"]),
                        "updated_at_display": _absolute_time(row["authored_at"]),
                        "change_reason_display": _humanise_reason(row["change_reason"]),
                    }

                # Parse units as list if comma-separated.
                units_str = row["units"]
                units_list = units_str.split(",") if units_str else None
                question_candidates = candidates_by_question.get(row["question_code"], [])
                proposed_candidates = [
                    candidate for candidate in question_candidates if candidate.state == "PROPOSED"
                ]

                proposals = []
                for candidate in proposed_candidates:
                    scope = candidate.scope_json or {}
                    run_id = str(candidate.import_run_id)
                    proposed_value = (
                        candidate.normalized_value_json or candidate.raw_value_json
                    )
                    proposals.append(
                        {
                            "candidate_id": str(candidate.id),
                            "import_run_id": run_id,
                            "row_version": candidate.row_version,
                            "display_value": _format_answer_summary(proposed_value)
                            or _format_scalar(proposed_value),
                            "source_label": _format_source_label(
                                candidate.origin, candidate.source_locator
                            ),
                            "confidence_percent": (
                                round(candidate.confidence * 100)
                                if candidate.confidence is not None
                                else None
                            ),
                            # The decision routes refuse both of these, so the
                            # strip shows why instead of a button that 409s.
                            "decidable": (
                                identity_by_run.get(run_id) == "APPLICATION_MATCHED"
                                and scope.get("scope") == "APPLICATION"
                            ),
                        }
                    )

                is_computed = response_type.is_computed if response_type else False
                questions.append({
                    "question_id": str(row["q_id"]),
                    "code": row["question_code"],
                    "text": row["question_text"],
                    "help": row["help_text"],
                    "display_order": row["display_order"],
                    "response_type": response_type_code,
                    "schema_version": row["response_schema_version"] or (response_type.schema_version if response_type else "1.0"),
                    "editor_key": response_type.editor_key if response_type else "text_editor",
                    "is_computed": is_computed,
                    "required_level": row["required_level"],
                    "collection_mode": row["collection_mode"],
                    "options": options_by_question.get(str(row["q_id"])) or None,
                    "units": units_list,
                    "field_names": [row["field_name"]] if row["field_name"] else None,
                    "applicability": "APPLICABLE",  # TODO: implement applicability
                    "applicability_reason": None,
                    "owner_roles": [],  # TODO: implement owner tracking
                    "source_labels": [],
                    "output_destinations": [],
                    "current_answer": current_answer,
                    "candidate_count": len(question_candidates),
                    "proposed_candidate_count": len(proposed_candidates),
                    "proposals": proposals,
                    "review_import_run_id": (
                        str(proposed_candidates[0].import_run_id)
                        if proposed_candidates
                        else None
                    ),
                    "evidence_count": 0,  # TODO: implement evidence counting
                    "history_count": row["revision_number"] or 0,
                    "is_answered": has_answer,
                    # Collapse only what is settled: an unanswered question, or
                    # one carrying an undecided proposal, still needs the user.
                    "is_collapsed": has_answer and not proposed_candidates,
                    # No source file can answer these; the hub counts them and
                    # the question says so rather than looking merely skipped.
                    "needs_person": (
                        not has_answer
                        and not is_computed
                        and not proposed_candidates
                        and row["required_level"] == "REQUIRED"
                    ),
                })

            return {
                "application": {
                    "id": str(app.id),
                    "display_name": app.display_name,
                    "state": app.state,
                },
                "intake": {
                    "id": str(intake.id),
                    "state": intake.state,
                    "row_version": intake.row_version,
                    "catalog_version": catalog.semantic_version,
                    "catalog_hash": catalog.source_sha256[:16] if catalog.source_sha256 else None,
                },
                "sections": section_summaries,
                "overall_status": {
                    "completed_count": sum(
                        section["completed_count"] for section in section_summaries
                    ),
                    "question_count": sum(
                        section["answerable_count"] for section in section_summaries
                    ),
                },
                "current_section": {
                    "code": current_section.section_code,
                    "title": current_section.display_name,
                    "previous_code": previous_code,
                    "next_code": next_code,
                    "position": current_idx + 1,
                    "total": len(section_codes),
                    "next_title": (
                        section_map[next_code].display_name if next_code else None
                    ),
                    "answered_count": current_summary["answered_count"],
                    "answerable_count": current_summary["answerable_count"],
                    "derived_count": current_summary["derived_count"],
                    "progress_percent": current_summary["progress_percent"],
                    "proposed_count": sum(
                        question["proposed_candidate_count"] for question in questions
                    ),
                    "completed_count": current_summary["completed_count"],
                },
                "questions": questions,
            }
        finally:
            session.close()

    # ------------------------------------------------------------------
    # get_import_run_summary
    # ------------------------------------------------------------------

    def get_import_run_summary(self, intake_id: str) -> list[dict]:
        """
        Return import run summaries for an intake, ordered by created_at ASC.

        Each dict: {run_id, state, total_candidates, total_findings, created_at (ISO)}
        Returns an empty list when no runs exist.
        """
        from migration_intake.persistence.models_imports import ImportRun

        session: Session = self._session_factory()
        try:
            stmt = (
                select(ImportRun)
                .where(ImportRun.intake_id == intake_id)
                .order_by(ImportRun.created_at.asc(), ImportRun.id.asc())
            )
            runs = session.execute(stmt).scalars().all()
            return [
                {
                    "run_id": str(run.id),
                    "state": run.state,
                    "total_candidates": run.total_candidates,
                    "total_findings": run.total_findings,
                    "created_at": run.created_at.isoformat(),
                }
                for run in runs
            ]
        finally:
            session.close()
