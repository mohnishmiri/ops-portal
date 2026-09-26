"""
UX-2 — Intake hub, driven through the browser against the real catalog.

The hub exists because the application never told anybody what was waiting on
them: a user with 17 undecided proposals concluded the import had silently
failed. These tests therefore assert the three counters as *numbers on the
page*, not as service return values, and they assert them against seeded data
rather than against constants — the packaged catalog may grow.

Exact-value coverage of the read model itself lives in
``tests/unit/application/test_intake_hub_service.py``. What is proved here is
that the page shows those numbers, that a fully derived section explains
itself instead of reading "0 of 3", and that the primary action lands on real
work.

Seeding goes through the service layer or direct row inserts, never the UI,
and uses only synthetic data (AGENTS.md).
"""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime
from typing import Any
from urllib.parse import quote

import pytest
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.browser

#: Inline event handlers break the CSP applied by web/security.py.
_INLINE_HANDLER = re.compile(r"\son(click|change|submit|input|focus|blur)=", re.IGNORECASE)


# ---------------------------------------------------------------------------
# Catalog oracle — read independently of the service under test
# ---------------------------------------------------------------------------


class Catalog:
    """The intake's questions, classified the way the hub claims to classify."""

    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows

    @property
    def required(self) -> list[dict[str, Any]]:
        return [row for row in self.rows if row["required_level"] == "REQUIRED"]

    @property
    def computed_required(self) -> list[dict[str, Any]]:
        return [row for row in self.required if row["is_computed"]]

    @property
    def answerable_required(self) -> list[dict[str, Any]]:
        return [row for row in self.required if not row["is_computed"]]

    def in_section(self, section_code: str) -> list[dict[str, Any]]:
        return [
            row for row in self.answerable_required if row["section_code"] == section_code
        ]

    def fully_computed_sections(self) -> list[str]:
        sections: dict[str, list[dict[str, Any]]] = {}
        for row in self.required:
            sections.setdefault(row["section_code"], []).append(row)
        return [
            code
            for code, rows in sections.items()
            if rows and all(row["is_computed"] for row in rows)
        ]

    def first_answerable_section(self, answered: set[str] | None = None) -> str:
        """Section code of the first unanswered, answerable required question."""
        done = answered or set()
        for row in self.rows:
            if row["required_level"] != "REQUIRED" or row["is_computed"]:
                continue
            if row["question_code"] not in done:
                return str(row["section_code"])
        raise AssertionError("catalog has no answerable required question")


@pytest.fixture(scope="session")
def catalog(session_factory: Any, catalog_release_id: str) -> Catalog:
    """Load the published catalog once, classified via the response registry."""
    from sqlalchemy import select

    from migration_intake.catalog.response_types import get_default_registry
    from migration_intake.persistence.models import CatalogQuestion, CatalogSection

    registry = get_default_registry()
    with session_factory() as session:
        rows = session.execute(
            select(
                CatalogSection.section_code,
                CatalogSection.display_name,
                CatalogQuestion.question_code,
                CatalogQuestion.response_type,
                CatalogQuestion.required_level,
            )
            .join(CatalogQuestion, CatalogQuestion.section_id == CatalogSection.id)
            .where(CatalogSection.release_id == catalog_release_id)
            .order_by(
                CatalogSection.display_order.asc(),
                CatalogQuestion.display_order.asc(),
            )
        ).mappings().all()

    classified = []
    for row in rows:
        spec = registry.get(row["response_type"])
        classified.append({**dict(row), "is_computed": bool(spec and spec.is_computed)})

    result = Catalog(classified)
    # Landmine-style guard: without computed required questions the exclusion
    # this page is built around would be untested by a green suite.
    assert result.computed_required, "catalog has no computed required questions"
    assert result.answerable_required, "catalog has no answerable required questions"
    return result


# ---------------------------------------------------------------------------
# Seeding
# ---------------------------------------------------------------------------


def _actor(server_env: dict[str, str]) -> Any:
    from migration_intake.application.dto import ActorContext

    return ActorContext(
        actor_id=server_env["ACTOR_ID"],
        display_name="Browser Suite Actor",
        actor_type="CONFIGURED",
    )


def _answer(
    session_factory: Any, server_env: dict[str, str], intake_id: str, codes: list[str]
) -> None:
    """
    Save human answers through the real service.

    The payload is a synthetic ``{"text": ...}`` for every response type: the
    hub counts *whether* a question holds a non-empty answer, never what the
    answer says, and building a valid payload per editor is the response-type
    matrix's job, not this suite's. ``AnswerService`` still enforces what
    matters here — it refuses computed types outright — so these codes are
    always drawn from the answerable set.
    """
    from migration_intake.application.services.answers import AnswerService

    service = AnswerService(session_factory)
    actor = _actor(server_env)
    for code in codes:
        service.save_answer(
            intake_id=intake_id,
            question_code=code,
            response_json={"text": f"Synthetic answer for {code}"},
            actor=actor,
            change_reason="browser hub fixture",
        )


def _propose(
    session_factory: Any, intake: dict, question_codes: list[str], *, state: str = "PROPOSED"
) -> str:
    """
    Insert candidates directly, with the evidence and import run they need.

    Driving a real import instead would make the proposal count depend on the
    adapter's column mapping, which is not what these tests are measuring.
    """
    from sqlalchemy import select

    from migration_intake.persistence.models import Actor
    from migration_intake.persistence.models_candidates import Candidate
    from migration_intake.persistence.models_evidence import EvidenceItem
    from migration_intake.persistence.models_imports import ImportRun

    now = datetime.now(tz=UTC)
    evidence_id = str(uuid.uuid4())
    run_id = str(uuid.uuid4())

    with session_factory() as session:
        actor_id = session.execute(select(Actor.id).limit(1)).scalar_one()
        session.add(
            EvidenceItem(
                id=evidence_id,
                application_id=intake["application_id"],
                intake_id=intake["intake_id"],
                storage_key=f"evidence/hub-{run_id}.xlsx",
                media_type="application/octet-stream",
                size_bytes=1,
                # Evidence is deduplicated by content hash, so each seed needs
                # its own (harness landmine 4).
                sha256_hex=uuid.uuid4().hex * 2,
                original_filename=f"hub-{run_id}.xlsx",
                state="ACTIVE",
                created_at=now,
                created_by_id=actor_id,
            )
        )
        session.add(
            ImportRun(
                id=run_id,
                application_id=intake["application_id"],
                intake_id=intake["intake_id"],
                evidence_item_id=evidence_id,
                contract_name="browser-hub-fixture",
                parser_version="1.0",
                state="COMPLETED",
                total_candidates=len(question_codes),
                total_findings=0,
                created_at=now,
                completed_at=now,
                created_by_id=actor_id,
            )
        )
        session.flush()
        for code in question_codes:
            session.add(
                Candidate(
                    id=str(uuid.uuid4()),
                    import_run_id=run_id,
                    application_id=intake["application_id"],
                    intake_id=intake["intake_id"],
                    evidence_item_id=evidence_id,
                    target_kind="QUESTION",
                    target_key=code,
                    origin="browser-hub-fixture",
                    extractor_version="1.0",
                    contract_version="1.0",
                    raw_value_json={"text": f"Proposed for {code}"},
                    scope_json={"scope": "APPLICATION"},
                    state=state,
                    row_version=1,
                    created_at=now,
                )
            )
        session.commit()
    return run_id


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _hub_url(base: str, intake: dict) -> str:
    return f"{base}/applications/{intake['application_id']}/intakes/{intake['intake_id']}"


def _counter(page: Page, element_id: str) -> int:
    return int(page.locator(f"#{element_id}").inner_text().strip())


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_hub_counters_are_computed_from_the_database(
    page: Page,
    app_server: str,
    intake: dict,
    session_factory: Any,
    server_env: dict[str, str],
    catalog: Catalog,
    recorder: Any,
) -> None:
    """
    Each counter moves only in response to the data that defines it.

    Deltas rather than constants, so the packaged catalog can grow without
    turning this into a maintenance chore — but the *starting* relationship
    (needs-a-person equals required minus computed, when nothing is proposed)
    is asserted exactly, and that is the computed-question exclusion.
    """
    page.goto(_hub_url(app_server, intake))

    required_total = _counter(page, "hub-required-total")
    assert required_total == len(catalog.required)
    assert _counter(page, "hub-required-answered") == 0
    assert _counter(page, "hub-pending-proposals") == 0

    # The exclusion, stated as an equation: a fresh intake needs a person for
    # every required question except the derived ones.
    needs_person = _counter(page, "hub-needs-person")
    assert needs_person == len(catalog.answerable_required)
    assert needs_person == required_total - len(catalog.computed_required)
    expect(page.locator("#hub-computed-note")).to_contain_text(
        f"{len(catalog.computed_required)} are derived"
    )

    # Three proposals arrive; three questions stop needing a person.
    codes = [row["question_code"] for row in catalog.answerable_required]
    assert len(codes) >= 5, "catalog lacks enough answerable required questions"
    proposed, answered = codes[:3], codes[3:5]

    _propose(session_factory, intake, proposed)
    # A decided candidate is not waiting on anybody and must not be counted.
    _propose(session_factory, intake, [proposed[0]], state="ACCEPTED")

    page.reload()
    assert _counter(page, "hub-pending-proposals") == 3
    assert _counter(page, "hub-needs-person") == needs_person - 3
    assert _counter(page, "hub-required-answered") == 0

    # Two answers arrive; only the progress counter moves.
    _answer(session_factory, server_env, intake["intake_id"], answered)

    page.reload()
    assert _counter(page, "hub-required-answered") == 2
    assert _counter(page, "hub-pending-proposals") == 3
    assert _counter(page, "hub-needs-person") == needs_person - 3

    # No inline handlers anywhere on the page (CSP contract).
    assert not _INLINE_HANDLER.search(page.content())


def test_fully_computed_section_explains_itself_instead_of_reading_zero(
    page: Page, app_server: str, intake: dict, catalog: Catalog, recorder: Any
) -> None:
    """
    "0 of 3" reads as unfinished work nobody in the world can finish.

    Sections whose required questions are all computed are derived from
    registers; the card must say so.
    """
    derived_sections = catalog.fully_computed_sections()
    assert derived_sections, "catalog has no fully computed section to assert on"
    code = derived_sections[0]
    expected_total = len(
        [row for row in catalog.required if row["section_code"] == code]
    )

    page.goto(_hub_url(app_server, intake))
    card = page.locator(f'[data-section-code="{code}"]')

    expect(card).to_contain_text("derived from registers")
    expect(card).to_contain_text("nothing to answer")
    expect(card).not_to_contain_text(f"0 of {expected_total}")
    # The progress geometry is meaningless here and must not be drawn.
    expect(card.locator(".hub-bar")).to_have_count(0)


def test_continue_targets_the_first_section_with_real_work(
    page: Page,
    app_server: str,
    intake: dict,
    session_factory: Any,
    server_env: dict[str, str],
    catalog: Catalog,
    recorder: Any,
) -> None:
    """
    The primary action lands on the first section holding answerable work.

    Once that section is finished it must advance rather than loop back.
    """
    first = catalog.first_answerable_section()

    page.goto(_hub_url(app_server, intake))
    page.locator("#hub-continue").click()
    expect(page).to_have_url(re.compile(r"/questionnaire/"))
    assert quote(first) in page.url, f"expected section {first}, landed on {page.url}"

    # Finish every answerable required question in that section. The action
    # must then advance rather than loop back to a completed section.
    finished = {row["question_code"] for row in catalog.in_section(first)}
    _answer(session_factory, server_env, intake["intake_id"], sorted(finished))

    page.goto(_hub_url(app_server, intake))
    next_section = catalog.first_answerable_section(answered=finished)
    assert next_section != first
    href = page.locator("#hub-continue").get_attribute("href")
    assert href is not None and href.endswith(f"/questionnaire/{quote(next_section)}"), href


def test_hub_renders_with_zero_answers_and_with_everything_answered(
    page: Page,
    app_server: str,
    intake: dict,
    session_factory: Any,
    server_env: dict[str, str],
    catalog: Catalog,
    recorder: Any,
) -> None:
    """
    Both extremes render: no divide-by-zero, no empty-state crash.

    ``recorder`` fails the test on any console error or 5xx, so simply
    reaching the assertions proves the page did not blow up.
    """
    from tests.browser.invariants import assert_no_horizontal_overflow

    page.goto(_hub_url(app_server, intake))
    expect(page.locator("#hub-required-answered")).to_have_text("0")
    expect(page.locator(".hub-ring-face")).to_have_text("0%")
    expect(page.locator("#hub-continue")).to_be_visible()
    assert_no_horizontal_overflow(page)

    # Answer everything a person is allowed to answer. The computed remainder
    # can never be answered — AnswerService refuses — so 100% is unreachable
    # by design and the page must still be coherent at the ceiling.
    codes = [row["question_code"] for row in catalog.answerable_required]
    _answer(session_factory, server_env, intake["intake_id"], codes)

    page.reload()
    assert _counter(page, "hub-required-answered") == len(codes)
    assert _counter(page, "hub-required-total") == len(catalog.required)
    expect(page.locator(".hub-ring-face")).not_to_have_text("0%")
    # Nothing answerable is outstanding, so the action changes its offer
    # instead of pointing nowhere.
    expect(page.locator("#hub-continue")).to_contain_text("Open the questionnaire")
    assert_no_horizontal_overflow(page)
