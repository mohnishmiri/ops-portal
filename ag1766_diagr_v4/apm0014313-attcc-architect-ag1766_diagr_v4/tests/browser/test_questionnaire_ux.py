"""
UX-1 — the redesigned questionnaire, driven through a real browser.

Each test here pins one behaviour the redesign is *for*, so a regression is
reported as the product failure it is rather than as a changed selector:

- there is no Save button any more, so blurring a field has to persist it;
- editing the same field twice in a row has to work, which it only does if the
  client refreshes its concurrency token from the save response
  (``AnswerService.save_answer`` compares ``expected_version`` against the
  current *revision number*, so re-posting the rendered token 409s);
- an answered question has to collapse, or the page stays 3,882px tall;
- an imported proposal has to be decidable on the question, because a link
  reading "2 pending review" is how 17 proposals went unnoticed;
- computed questions have to be hideable, because nobody can answer them;
- and none of it may use an inline event handler, which the CSP forbids.
"""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from playwright.sync_api import Page, expect

from tests.browser.invariants import assert_no_horizontal_overflow
from tests.browser.matrix_support import Case, seed_question

pytestmark = pytest.mark.browser


#: Same audit the shell test applies, kept here so the questionnaire's own
#: markup is checked rather than only base.html's.
INLINE_HANDLER = re.compile(
    r"\s(onclick|onchange|onsubmit|onload|onerror|onkeyup|onkeydown"
    r"|onfocus|onblur|oninput|onmouseover|onmouseout)=",
    re.IGNORECASE,
)

UUID_IN_TEXT = re.compile(
    r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b",
    re.IGNORECASE,
)


def section_url(app_server: str, intake: dict, section_code: str) -> str:
    return (
        f"{app_server}/applications/{intake['application_id']}"
        f"/intakes/{intake['intake_id']}/questionnaire/{section_code}"
    )


def blur_active(page: Page) -> None:
    """Leave the field, which is the only way to save."""
    page.evaluate(
        "() => { if (document.activeElement) { document.activeElement.blur(); } }"
    )


def version_token(page: Page, question_code: str) -> str:
    return page.locator(f"#q-{question_code}-version").input_value()


def seed_proposal(
    session_factory: Any,
    intake: dict,
    server_env: dict[str, str],
    question_code: str,
    value: dict,
) -> str:
    """
    Seed one PROPOSED candidate the way an import would leave it.

    Written straight to the database rather than through the evidence UI: the
    sources and coverage pages belong to another packet, and this test is
    about the questionnaire's response to a proposal, not about how it got
    there. ``identity_decision`` and the APPLICATION scope both matter — the
    decision routes refuse a candidate without them.
    """
    from sqlalchemy.orm import Session

    from migration_intake.persistence.models_candidates import Candidate
    from migration_intake.persistence.models_evidence import EvidenceItem
    from migration_intake.persistence.models_imports import ImportRun

    actor_id = server_env["ACTOR_ID"]
    now = datetime.now(tz=UTC)
    evidence_id = str(uuid.uuid4())
    run_id = str(uuid.uuid4())
    candidate_id = str(uuid.uuid4())

    with Session(session_factory.kw["bind"]) as session:
        session.add(
            EvidenceItem(
                id=evidence_id,
                application_id=intake["application_id"],
                intake_id=intake["intake_id"],
                storage_key=f"synthetic/{evidence_id}.xlsx",
                sha256_hex=uuid.uuid4().hex * 2,
                size_bytes=1024,
                media_type="application/vnd.openxmlformats-officedocument."
                "spreadsheetml.sheet",
                original_filename="synthetic-interface-tracking.xlsx",
                state="ACTIVE",
                created_at=now,
                created_by_id=actor_id,
            )
        )
        # Flush between inserts: the candidate's foreign keys point at rows
        # SQLAlchemy would otherwise be free to insert after it.
        session.flush()
        session.add(
            ImportRun(
                id=run_id,
                application_id=intake["application_id"],
                intake_id=intake["intake_id"],
                evidence_item_id=evidence_id,
                contract_name="INTERFACE_TRACKING",
                parser_version="test",
                state="COMPLETED",
                total_candidates=1,
                total_findings=0,
                identity_decision="APPLICATION_MATCHED",
                source_identity_raw=intake["correlation_id"],
                source_identity_normalized=intake["correlation_id"],
                created_at=now,
                created_by_id=actor_id,
            )
        )
        session.flush()
        session.add(
            Candidate(
                id=candidate_id,
                import_run_id=run_id,
                application_id=intake["application_id"],
                intake_id=intake["intake_id"],
                evidence_item_id=evidence_id,
                target_kind="QUESTION",
                target_key=question_code,
                origin="iTAP",
                extractor_version="test",
                contract_version="1.0",
                response_schema_version="1.0",
                source_locator={
                    "sheet": "Migrating App Data",
                    "column": "Customer facing indicator",
                    "row": 4,
                },
                raw_value_json=value,
                normalized_value_json=value,
                scope_json={"scope": "APPLICATION"},
                confidence=0.95,
                state="PROPOSED",
                row_version=1,
                created_at=now,
            )
        )
        session.commit()
    return candidate_id


# ---------------------------------------------------------------------------
# Autosave
# ---------------------------------------------------------------------------


def test_blurring_a_field_saves_it_with_no_save_button(
    page: Page,
    app_server: str,
    intake: dict,
    session_factory: Any,
    catalog_release_id: str,
) -> None:
    """Answering is typing and moving on, not typing and pressing Save."""
    section_code, code = seed_question(
        session_factory, catalog_release_id, Case("TEXT")
    )
    url = section_url(app_server, intake, section_code)
    page.goto(url)

    card = page.locator(f"#question-{code}")
    expect(card).to_be_visible()
    # The button is gone, not merely unused: its presence would mean users are
    # still expected to submit each question individually.
    expect(card.locator("button:has-text('Save')")).to_have_count(0)

    page.locator(f"#q-{code}-input").fill("saved by walking away")
    blur_active(page)

    indicator = page.locator(f"#q-{code}-save")
    expect(indicator).to_have_attribute("data-state", "saved")
    expect(indicator).to_contain_text("Saved")

    page.goto(url)
    page.locator(f"#question-{code} details.qx-disclosure").evaluate(
        "element => { element.open = true; }"
    )
    expect(page.locator(f"#q-{code}-input")).to_have_value("saved by walking away")


def test_editing_the_same_field_twice_does_not_conflict_with_itself(
    page: Page,
    app_server: str,
    intake: dict,
    session_factory: Any,
    catalog_release_id: str,
) -> None:
    """
    The concurrency token must be refreshed from the save response.

    ``save_answer`` compares ``expected_version`` against the current revision
    number. A client that keeps posting the number the page was rendered with
    saves once and then 409s on every later edit of the same field — the
    single most likely way to ship a broken autosave.
    """
    section_code, code = seed_question(
        session_factory, catalog_release_id, Case("TEXT")
    )
    url = section_url(app_server, intake, section_code)

    conflicts: list[str] = []
    page.on(
        "response",
        lambda response: (
            conflicts.append(f"{response.status} {response.url}")
            if response.status == 409 and "/answer" in response.url
            else None
        ),
    )

    page.goto(url)
    assert version_token(page, code) == "0"

    page.locator(f"#q-{code}-input").fill("first value")
    blur_active(page)
    expect(page.locator(f"#q-{code}-version")).to_have_value("1")
    expect(page.locator(f"#q-{code}-save")).to_have_attribute("data-state", "saved")

    page.locator(f"#q-{code}-input").fill("second value")
    blur_active(page)
    expect(page.locator(f"#q-{code}-version")).to_have_value("2")
    expect(page.locator(f"#q-{code}-save")).to_have_attribute("data-state", "saved")

    assert not conflicts, f"autosave conflicted with itself: {conflicts}"

    page.goto(url)
    page.locator(f"#question-{code} details.qx-disclosure").evaluate(
        "element => { element.open = true; }"
    )
    expect(page.locator(f"#q-{code}-input")).to_have_value("second value")


# ---------------------------------------------------------------------------
# Collapse
# ---------------------------------------------------------------------------


def test_an_answered_question_renders_collapsed_showing_its_value(
    page: Page,
    app_server: str,
    intake: dict,
    session_factory: Any,
    catalog_release_id: str,
) -> None:
    """Settled work costs one line; the editor is one click away."""
    section_code, code = seed_question(
        session_factory, catalog_release_id, Case("TEXT")
    )
    url = section_url(app_server, intake, section_code)

    page.goto(url)
    page.locator(f"#q-{code}-input").fill("a business function")
    blur_active(page)
    expect(page.locator(f"#q-{code}-save")).to_have_attribute("data-state", "saved")

    page.goto(url)
    disclosure = page.locator(f"#question-{code} details.qx-disclosure")
    assert disclosure.evaluate("element => element.open") is False

    # The value is readable without expanding anything, and the raw payload
    # shape ({'text': ...}) is not what the user sees.
    summary = page.locator(f"#question-{code} .qx-value")
    expect(summary).to_be_visible()
    expect(summary).to_have_text("a business function")
    expect(page.locator(f"#q-{code}-input")).to_be_hidden()

    page.locator(f"#question-{code} .qx-summary").click()
    expect(page.locator(f"#q-{code}-input")).to_be_visible()


# ---------------------------------------------------------------------------
# Inline proposals
# ---------------------------------------------------------------------------


def test_a_pending_proposal_is_decidable_on_the_question(
    page: Page,
    app_server: str,
    intake: dict,
    session_factory: Any,
    catalog_release_id: str,
    server_env: dict[str, str],
    recorder: Any,
) -> None:
    """Accepting imported evidence must not require finding another page."""
    section_code, code = seed_question(
        session_factory,
        catalog_release_id,
        Case("BOOLEAN", options=("YES", "NO", "UNKNOWN")),
    )
    seed_proposal(
        session_factory, intake, server_env, code, {"value": "NO"}
    )

    page.goto(section_url(app_server, intake, section_code))

    strip = page.locator(f"#question-{code} .qx-proposal")
    expect(strip).to_have_count(1)
    expect(strip).to_contain_text("Evidence suggests")
    expect(strip).to_contain_text("NO")
    # Provenance a reviewer can act on: where it came from and how sure it is.
    expect(strip).to_contain_text("iTAP")
    expect(strip).to_contain_text("Customer facing indicator")
    expect(strip).to_contain_text("95%")

    strip.locator("button:has-text('Accept')").click()

    # The proposal is now the canonical answer and the strip is gone.
    expect(page.locator(f"#q-{code}-no")).to_be_checked()
    expect(page.locator(f"#question-{code} .qx-proposal")).to_have_count(0)

    # text_content, not inner_text: the question is now answered, so it has
    # collapsed and its metadata is present but not rendered.
    card_text = page.locator(f"#question-{code}").text_content() or ""
    assert not UUID_IN_TEXT.search(card_text), (
        f"a candidate UUID leaked into the answer metadata: {card_text!r}"
    )
    assert "ago" in card_text or "just now" in card_text, (
        f"answer metadata should read as relative time, got: {card_text!r}"
    )


# ---------------------------------------------------------------------------
# Derived questions
# ---------------------------------------------------------------------------


def test_the_derived_toggle_hides_computed_questions(
    page: Page,
    app_server: str,
    intake: dict,
    session_factory: Any,
    catalog_release_id: str,
) -> None:
    """37 of 93 required questions are computed; showing them is noise."""
    section_code, code = seed_question(
        session_factory, catalog_release_id, Case("REGISTER_STATUS")
    )

    page.goto(section_url(app_server, intake, section_code))

    toggle = page.locator("#toggle-derived")
    expect(toggle).to_be_checked()
    expect(page.locator(f"#question-{code}")).to_be_hidden()

    toggle.uncheck()
    expect(page.locator(f"#question-{code}")).to_be_visible()

    toggle.check()
    expect(page.locator(f"#question-{code}")).to_be_hidden()


# ---------------------------------------------------------------------------
# CSP
# ---------------------------------------------------------------------------


def test_the_rendered_section_has_no_inline_event_handlers(
    page: Page,
    app_server: str,
    intake: dict,
    session_factory: Any,
    catalog_release_id: str,
    server_env: dict[str, str],
) -> None:
    """A CSP is enforced, so behaviour lives in app.js or it does not run."""
    section_code, code = seed_question(
        session_factory,
        catalog_release_id,
        Case("SINGLE_SELECT", options=("ALPHA", "BETA")),
    )
    seed_proposal(session_factory, intake, server_env, code, {"value": "BETA"})

    page.goto(section_url(app_server, intake, section_code))
    seeded = page.content()
    assert not INLINE_HANDLER.search(seeded), "inline handler in a seeded section"
    # The rail is a grid column, so a phone must stack it rather than scroll.
    assert_no_horizontal_overflow(page)

    # The real catalog section exercises every editor the packaged questions
    # use, which the synthetic sections above deliberately do not.
    page.goto(section_url(app_server, intake, "APPLICATION"))
    application = page.content()
    assert not INLINE_HANDLER.search(application), (
        "inline handler in the APPLICATION section"
    )
