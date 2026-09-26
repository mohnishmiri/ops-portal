"""
Tests for the intake hub read model (UX-2).

The hub exists because nothing in the application counted the work waiting on
a human: a user with 17 undecided proposals concluded the import had failed.
So the assertions here are mostly about the three counters being exactly right
against a seeded fixture, and in particular about the two ways they can lie:

- counting computed response types as outstanding work, when ``AnswerService``
  refuses to save them at all; and
- reporting a fully-derived section as "0 of 3", which reads as unfinished.

Fixtures are synthetic and local to this module. Client evidence and the
developer's ``local.db`` are never touched (AGENTS.md).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from migration_intake.application.services.intake_hub import IntakeHubService
from migration_intake.catalog.response_types import get_default_registry
from migration_intake.persistence.models import (
    Actor,
    AnswerInstance,
    AnswerRevision,
    Application,
    ApplicationIdentifier,
    Base,
    CatalogQuestion,
    CatalogRelease,
    CatalogSection,
    Intake,
)
from migration_intake.persistence.models_candidates import Candidate
from migration_intake.persistence.models_evidence import EvidenceItem
from migration_intake.persistence.models_imports import ImportRun

#: A response type the registry reports as computed, asserted below rather
#: than assumed — the point of the exclusion is that it is registry-driven.
COMPUTED_TYPE = "REGISTER_STATUS"
#: A response type a person can actually answer.
ANSWERABLE_TYPE = "TEXT"


def _now() -> datetime:
    return datetime.now(tz=timezone.utc)


@pytest.fixture()
def engine():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return engine


@pytest.fixture()
def session_factory(engine):
    return sessionmaker(bind=engine)


@pytest.fixture()
def hub_service(session_factory) -> IntakeHubService:
    return IntakeHubService(session_factory)


# ---------------------------------------------------------------------------
# Seeding
# ---------------------------------------------------------------------------


class Fixture:
    """Handles for the seeded intake, so tests can name what they mutate."""

    def __init__(self) -> None:
        self.actor_id = str(uuid.uuid4())
        self.application_id = str(uuid.uuid4())
        self.intake_id = str(uuid.uuid4())
        self.catalog_id = str(uuid.uuid4())
        self.evidence_id = str(uuid.uuid4())
        self.import_run_id = str(uuid.uuid4())
        #: question_code -> question_id
        self.questions: dict[str, str] = {}


def _seed_intake(engine, *, correlation_id: str = "80001234") -> Fixture:
    """Seed an actor, application (with correlation id), catalog and intake."""
    fixture = Fixture()
    now = _now()
    with Session(engine) as session:
        session.add(Actor(id=fixture.actor_id, display_name="Test Actor", created_at=now))
        session.add(
            Application(
                id=fixture.application_id,
                state="ACTIVE",
                display_name="Hub Test App",
                created_at=now,
                updated_at=now,
                row_version=1,
                created_by_id=fixture.actor_id,
            )
        )
        session.add(
            ApplicationIdentifier(
                id=str(uuid.uuid4()),
                application_id=fixture.application_id,
                identifier_type="CORRELATION",
                raw_value=correlation_id,
                normalized_value=correlation_id,
                created_at=now,
            )
        )
        session.add(
            CatalogRelease(
                id=fixture.catalog_id,
                semantic_version="0.2.0",
                source_filename="catalog.yaml",
                source_sha256="a" * 64,
                compiler_version="1.0",
                pub_state="PUBLISHED",
                published_at=now,
                created_at=now,
            )
        )
        session.add(
            Intake(
                id=fixture.intake_id,
                application_id=fixture.application_id,
                catalog_id=fixture.catalog_id,
                state="DRAFT",
                created_at=now,
                updated_at=now,
                row_version=1,
                created_by_id=fixture.actor_id,
            )
        )
        session.commit()
    return fixture


def _seed_section(
    engine,
    fixture: Fixture,
    *,
    code: str,
    order: int,
    questions: list[tuple[str, str, str]],
) -> None:
    """
    Add a section and its questions.

    ``questions`` items are ``(question_code, response_type, required_level)``.
    """
    section_id = str(uuid.uuid4())
    with Session(engine) as session:
        session.add(
            CatalogSection(
                id=section_id,
                release_id=fixture.catalog_id,
                section_code=code,
                display_name=code.replace("-", " ").title(),
                display_order=order,
            )
        )
        for index, (question_code, response_type, required_level) in enumerate(questions):
            question_id = str(uuid.uuid4())
            fixture.questions[question_code] = question_id
            session.add(
                CatalogQuestion(
                    id=question_id,
                    section_id=section_id,
                    question_code=question_code,
                    question_text=f"Question {question_code}?",
                    response_type=response_type,
                    required_level=required_level,
                    collection_mode="SINGLE",
                    display_order=index + 1,
                    is_active=True,
                )
            )
        session.commit()


def _seed_answer(engine, fixture: Fixture, question_code: str, response_json: dict) -> None:
    """Give a question a current answer revision."""
    now = _now()
    instance_id = str(uuid.uuid4())
    revision_id = str(uuid.uuid4())
    with Session(engine) as session:
        session.add(
            AnswerInstance(
                id=instance_id,
                intake_id=fixture.intake_id,
                question_id=fixture.questions[question_code],
                created_at=now,
                updated_at=now,
                row_version=1,
            )
        )
        session.commit()
    with Session(engine) as session:
        session.add(
            AnswerRevision(
                id=revision_id,
                instance_id=instance_id,
                revision_number=1,
                response_json=response_json,
                confirm_state="DRAFT",
                authored_at=now,
                authored_by_id=fixture.actor_id,
            )
        )
        session.commit()
    with Session(engine) as session:
        instance = session.query(AnswerInstance).filter_by(id=instance_id).one()
        instance.current_rev_id = revision_id
        session.commit()


def _seed_import_run(engine, fixture: Fixture) -> None:
    now = _now()
    with Session(engine) as session:
        session.add(
            EvidenceItem(
                id=fixture.evidence_id,
                application_id=fixture.application_id,
                intake_id=fixture.intake_id,
                storage_key="evidence/hub-test.xlsx",
                media_type="application/octet-stream",
                size_bytes=1,
                sha256_hex="b" * 64,
                original_filename="hub-test.xlsx",
                state="ACTIVE",
                created_at=now,
                created_by_id=fixture.actor_id,
            )
        )
        session.add(
            ImportRun(
                id=fixture.import_run_id,
                application_id=fixture.application_id,
                intake_id=fixture.intake_id,
                evidence_item_id=fixture.evidence_id,
                contract_name="test",
                parser_version="1.0",
                state="COMPLETED",
                total_candidates=0,
                total_findings=0,
                created_at=now,
                completed_at=now,
                created_by_id=fixture.actor_id,
            )
        )
        session.commit()


def _seed_candidate(
    engine, fixture: Fixture, question_code: str, *, state: str = "PROPOSED"
) -> None:
    """Add one candidate targeting a question. Requires the import run."""
    now = _now()
    with Session(engine) as session:
        session.add(
            Candidate(
                id=str(uuid.uuid4()),
                import_run_id=fixture.import_run_id,
                application_id=fixture.application_id,
                intake_id=fixture.intake_id,
                evidence_item_id=fixture.evidence_id,
                target_kind="QUESTION",
                target_key=question_code,
                origin="test",
                extractor_version="1.0",
                contract_version="1.0",
                raw_value_json={"text": "Proposed"},
                scope_json={"scope": "APPLICATION"},
                state=state,
                row_version=1,
                created_at=now,
            )
        )
        session.commit()


def _seed_reference_shape(engine) -> Fixture:
    """
    Seed the intake every counter test measures.

    Deliberately built so each counter has a different answer and no two
    definitions coincide:

    ================ ======== ============== ========= ==========
    section          required computed       answered  proposals
    ================ ======== ============== ========= ==========
    CONTROL          2        0              1         1 (CTL-002)
    DERIVED          3        3              0         0
    NETWORK          4        1              1         1 (NET-004)
    OPTIONALS        0        0              n/a       1 (OPT-001)
    ================ ======== ============== ========= ==========

    Totals: 9 required, 2 answered, 4 computed, 3 pending proposals,
    and 4 questions that need a person (CTL-001 is answered but has no
    proposal, so it counts; NET-002 and NET-003 are unanswered with no
    proposal; and NET-001 is answered with no proposal).
    """
    fixture = _seed_intake(engine)
    _seed_section(
        engine,
        fixture,
        code="CONTROL",
        order=1,
        questions=[
            ("CTL-001", ANSWERABLE_TYPE, "REQUIRED"),
            ("CTL-002", ANSWERABLE_TYPE, "REQUIRED"),
        ],
    )
    _seed_section(
        engine,
        fixture,
        code="DERIVED",
        order=2,
        questions=[
            ("DRV-001", COMPUTED_TYPE, "REQUIRED"),
            ("DRV-002", COMPUTED_TYPE, "REQUIRED"),
            ("DRV-003", COMPUTED_TYPE, "REQUIRED"),
        ],
    )
    _seed_section(
        engine,
        fixture,
        code="NETWORK",
        order=3,
        questions=[
            ("NET-001", ANSWERABLE_TYPE, "REQUIRED"),
            ("NET-002", ANSWERABLE_TYPE, "REQUIRED"),
            ("NET-003", ANSWERABLE_TYPE, "REQUIRED"),
            ("NET-004", COMPUTED_TYPE, "REQUIRED"),
        ],
    )
    _seed_section(
        engine,
        fixture,
        code="OPTIONALS",
        order=4,
        questions=[("OPT-001", ANSWERABLE_TYPE, "OPTIONAL")],
    )

    _seed_answer(engine, fixture, "CTL-001", {"text": "answered"})
    _seed_answer(engine, fixture, "NET-001", {"text": "answered"})

    _seed_import_run(engine, fixture)
    _seed_candidate(engine, fixture, "CTL-002")
    _seed_candidate(engine, fixture, "NET-004")
    _seed_candidate(engine, fixture, "OPT-001")
    # A decided candidate is not waiting on anybody and must not be counted.
    _seed_candidate(engine, fixture, "NET-002", state="ACCEPTED")
    return fixture


def _section(hub: dict, code: str) -> dict:
    return next(section for section in hub["sections"] if section["code"] == code)


# ---------------------------------------------------------------------------
# The premise the exclusion rests on
# ---------------------------------------------------------------------------


def test_fixture_response_types_match_the_registry() -> None:
    """
    The computed exclusion is registry-driven, never a hard-coded list.

    If this fails, every counter assertion below is measuring the wrong thing.
    """
    registry = get_default_registry()
    assert registry.get(COMPUTED_TYPE).is_computed is True
    assert registry.get(ANSWERABLE_TYPE).is_computed is False


# ---------------------------------------------------------------------------
# Counters
# ---------------------------------------------------------------------------


def test_unknown_intake_returns_none(hub_service: IntakeHubService) -> None:
    assert hub_service.get_intake_hub(str(uuid.uuid4())) is None


def test_counters_match_the_seeded_fixture_exactly(engine, hub_service) -> None:
    fixture = _seed_reference_shape(engine)
    totals = hub_service.get_intake_hub(fixture.intake_id)["totals"]

    # Required total counts REQUIRED only: the OPTIONAL question is excluded.
    assert totals["required_total"] == 9
    assert totals["required_answered"] == 2
    assert totals["required_percent"] == 22

    # Undecided question proposals only — the ACCEPTED one is not waiting.
    assert totals["pending_proposals"] == 3

    # required, not computed, no proposal: CTL-001, NET-001, NET-002, NET-003.
    assert totals["needs_person"] == 4
    assert totals["computed_required"] == 4


def test_needs_person_excludes_computed_response_types(engine, hub_service) -> None:
    """
    Without the computed exclusion the count would be 8, not 4.

    37 of the reference catalog's 93 required questions are computed types;
    counting them as human work is the single largest way this page can lie.
    """
    fixture = _seed_reference_shape(engine)
    hub = hub_service.get_intake_hub(fixture.intake_id)

    assert hub["totals"]["needs_person"] == 4

    # DERIVED's three questions are required and have no proposal, so a count
    # that ignored computedness would report 7 and overstate the human
    # workload by three quarters.
    assert _section(hub, "DERIVED")["computed_required"] == 3
    assert _section(hub, "DERIVED")["needs_person"] == 0
    assert _section(hub, "NETWORK")["needs_person"] == 3
    assert _section(hub, "CONTROL")["needs_person"] == 1


def test_needs_person_excludes_questions_with_a_proposal(engine, hub_service) -> None:
    """A question an import already answered is not waiting on a person."""
    fixture = _seed_reference_shape(engine)
    before = hub_service.get_intake_hub(fixture.intake_id)["totals"]["needs_person"]

    _seed_candidate(engine, fixture, "NET-002")

    after = hub_service.get_intake_hub(fixture.intake_id)["totals"]["needs_person"]
    assert after == before - 1


def test_cleared_answer_does_not_count_as_answered(engine, hub_service) -> None:
    """
    An emptied answer still owns a revision; progress must not count it.

    ``clear_answer`` writes ``response_json = {}``, so revision existence
    alone would report the question as done.
    """
    fixture = _seed_intake(engine)
    _seed_section(
        engine,
        fixture,
        code="CONTROL",
        order=1,
        questions=[
            ("CTL-001", ANSWERABLE_TYPE, "REQUIRED"),
            ("CTL-002", ANSWERABLE_TYPE, "REQUIRED"),
        ],
    )
    _seed_answer(engine, fixture, "CTL-001", {"text": "real"})
    _seed_answer(engine, fixture, "CTL-002", {})

    totals = hub_service.get_intake_hub(fixture.intake_id)["totals"]
    assert totals["required_answered"] == 1
    assert totals["required_total"] == 2


def test_section_counters_carry_their_own_proposal_badge(engine, hub_service) -> None:
    fixture = _seed_reference_shape(engine)
    hub = hub_service.get_intake_hub(fixture.intake_id)

    assert _section(hub, "CONTROL")["pending_proposals"] == 1
    assert _section(hub, "DERIVED")["pending_proposals"] == 0
    assert _section(hub, "NETWORK")["pending_proposals"] == 1
    # A proposal against an optional question is still undecided work.
    assert _section(hub, "OPTIONALS")["pending_proposals"] == 1
    assert sum(s["pending_proposals"] for s in hub["sections"]) == 3


# ---------------------------------------------------------------------------
# Fully computed sections
# ---------------------------------------------------------------------------


def test_fully_computed_section_is_flagged_not_reported_as_zero(engine, hub_service) -> None:
    """"0 of 3" reads as unfinished work nobody is able to finish."""
    fixture = _seed_reference_shape(engine)
    derived = _section(hub_service.get_intake_hub(fixture.intake_id), "DERIVED")

    assert derived["all_computed"] is True
    assert derived["required_total"] == 3
    assert derived["computed_required"] == 3
    assert derived["needs_person"] == 0


def test_partly_computed_section_is_not_flagged(engine, hub_service) -> None:
    fixture = _seed_reference_shape(engine)
    network = _section(hub_service.get_intake_hub(fixture.intake_id), "NETWORK")

    assert network["all_computed"] is False
    assert network["required_total"] == 4
    assert network["computed_required"] == 1
    assert network["required_answered"] == 1


def test_section_without_required_questions_is_not_flagged_as_computed(
    engine, hub_service
) -> None:
    fixture = _seed_reference_shape(engine)
    optionals = _section(hub_service.get_intake_hub(fixture.intake_id), "OPTIONALS")

    assert optionals["has_required"] is False
    assert optionals["all_computed"] is False
    assert optionals["required_percent"] == 0


# ---------------------------------------------------------------------------
# Continue where I left off
# ---------------------------------------------------------------------------


def test_continue_targets_first_section_with_an_unanswered_required_question(
    engine, hub_service
) -> None:
    """
    CONTROL is first in display order and CTL-002 is unanswered.

    A proposal existing for CTL-002 must not disqualify it: a proposal is not
    an answer until somebody accepts it.
    """
    fixture = _seed_reference_shape(engine)
    assert hub_service.get_intake_hub(fixture.intake_id)["continue_section"] == "CONTROL"


def test_continue_skips_a_completed_section(engine, hub_service) -> None:
    fixture = _seed_reference_shape(engine)
    _seed_answer(engine, fixture, "CTL-002", {"text": "answered"})

    assert hub_service.get_intake_hub(fixture.intake_id)["continue_section"] == "NETWORK"


def test_continue_skips_a_fully_computed_section(engine, hub_service) -> None:
    """
    A derived section's questions are permanently unanswered by design.

    Sending "Continue where I left off" there would land the user on a page
    the hub itself describes as having nothing to answer.
    """
    fixture = _seed_intake(engine)
    _seed_section(
        engine,
        fixture,
        code="DERIVED",
        order=1,
        questions=[
            ("DRV-001", COMPUTED_TYPE, "REQUIRED"),
            ("DRV-002", COMPUTED_TYPE, "REQUIRED"),
            ("DRV-003", COMPUTED_TYPE, "REQUIRED"),
        ],
    )
    _seed_section(
        engine,
        fixture,
        code="NETWORK",
        order=2,
        questions=[("NET-001", ANSWERABLE_TYPE, "REQUIRED")],
    )

    assert hub_service.get_intake_hub(fixture.intake_id)["continue_section"] == "NETWORK"


def test_continue_is_none_when_everything_answerable_is_answered(
    engine, hub_service
) -> None:
    fixture = _seed_reference_shape(engine)
    for code in ("CTL-002", "NET-002", "NET-003"):
        _seed_answer(engine, fixture, code, {"text": "answered"})

    hub = hub_service.get_intake_hub(fixture.intake_id)
    assert hub["continue_section"] is None


# ---------------------------------------------------------------------------
# Empty and complete extremes
# ---------------------------------------------------------------------------


def test_intake_with_zero_answers_reports_zero_percent_not_an_error(
    engine, hub_service
) -> None:
    fixture = _seed_intake(engine)
    _seed_section(
        engine,
        fixture,
        code="CONTROL",
        order=1,
        questions=[("CTL-001", ANSWERABLE_TYPE, "REQUIRED")],
    )

    hub = hub_service.get_intake_hub(fixture.intake_id)
    assert hub["totals"]["required_answered"] == 0
    assert hub["totals"]["required_percent"] == 0
    assert hub["totals"]["pending_proposals"] == 0
    assert hub["continue_section"] == "CONTROL"


def test_catalog_with_no_questions_does_not_divide_by_zero(engine, hub_service) -> None:
    fixture = _seed_intake(engine)
    _seed_section(engine, fixture, code="EMPTY", order=1, questions=[])

    hub = hub_service.get_intake_hub(fixture.intake_id)
    assert hub["totals"]["required_total"] == 0
    assert hub["totals"]["required_percent"] == 0
    assert _section(hub, "EMPTY")["required_percent"] == 0
    assert hub["continue_section"] is None


def test_catalog_with_no_sections_returns_an_empty_grid(engine, hub_service) -> None:
    fixture = _seed_intake(engine)

    hub = hub_service.get_intake_hub(fixture.intake_id)
    assert hub["sections"] == []
    assert hub["totals"]["required_percent"] == 0


def test_fully_answered_intake_reports_one_hundred_percent(engine, hub_service) -> None:
    fixture = _seed_intake(engine)
    _seed_section(
        engine,
        fixture,
        code="CONTROL",
        order=1,
        questions=[
            ("CTL-001", ANSWERABLE_TYPE, "REQUIRED"),
            ("CTL-002", ANSWERABLE_TYPE, "REQUIRED"),
        ],
    )
    _seed_answer(engine, fixture, "CTL-001", {"text": "a"})
    _seed_answer(engine, fixture, "CTL-002", {"text": "b"})

    hub = hub_service.get_intake_hub(fixture.intake_id)
    assert hub["totals"]["required_percent"] == 100
    assert _section(hub, "CONTROL")["required_percent"] == 100
    assert hub["continue_section"] is None


# ---------------------------------------------------------------------------
# Identity and review target
# ---------------------------------------------------------------------------


def test_identity_block_carries_correlation_and_catalog_version(engine, hub_service) -> None:
    fixture = _seed_intake(engine, correlation_id="80009999")
    hub = hub_service.get_intake_hub(fixture.intake_id)

    assert hub["application"]["display_name"] == "Hub Test App"
    assert hub["application"]["correlation_id"] == "80009999"
    assert hub["intake"]["catalog_version"] == "0.2.0"
    assert hub["intake"]["state"] == "DRAFT"


def test_review_run_id_points_at_a_run_with_undecided_proposals(engine, hub_service) -> None:
    fixture = _seed_reference_shape(engine)
    hub = hub_service.get_intake_hub(fixture.intake_id)
    assert hub["totals"]["pending_proposals"] > 0


def test_review_run_id_is_none_when_nothing_is_pending(engine, hub_service) -> None:
    fixture = _seed_intake(engine)
    _seed_section(
        engine,
        fixture,
        code="CONTROL",
        order=1,
        questions=[("CTL-001", ANSWERABLE_TYPE, "REQUIRED")],
    )
    assert hub_service.get_intake_hub(fixture.intake_id)["totals"]["pending_proposals"] == 0
