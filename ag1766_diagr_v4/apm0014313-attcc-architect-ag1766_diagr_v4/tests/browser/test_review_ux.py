"""
J7 — Evidence lanes and bulk proposal review, driven through the browser.

Two measured failures drive these specs:

1. A user uploaded a *completed intake form* into the source-document
   uploader because both were the same anonymous file input. The import
   produced ``UNRECOGNIZED_SHEET`` and zero proposals, and the page then told
   them their application identity was wrong — a misleading dead end.
2. Accepting the 17 proposals from one import cost 17 page round-trips,
   because the only affordance was a per-row Accept button.

There is also a data-loss precedent to design against: two accepted proposals
targeted the same question and the second silently replaced the first. Rows
that would replace an existing answer are therefore flagged and never
pre-selected, and a bulk decision reports its partial outcome honestly.
"""

from __future__ import annotations

import re
from typing import Any

import httpx
import pytest
from playwright.sync_api import Page, expect
from sqlalchemy import select

from tests.browser.conftest import (
    build_uaq_workbook,
    fill_intake_form,
    timestamped_name,
)

pytestmark = pytest.mark.browser

XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _sources_url(base: str, intake: dict) -> str:
    return (
        f"{base}/applications/{intake['application_id']}"
        f"/intakes/{intake['intake_id']}/sources"
    )


def _export_form(base: str, intake: dict) -> bytes:
    """Fetch the blank intake form from the app's own export, never hand-built."""
    response = httpx.get(
        f"{base}/applications/{intake['application_id']}"
        f"/intakes/{intake['intake_id']}/gap-workbook.xlsx",
        params={"include": "required"},
        timeout=30.0,
    )
    assert response.status_code == 200, response.text[:200]
    return response.content


def _import_answers(page: Page, base: str, intake: dict, answers: dict[str, str]) -> None:
    """
    Return a completed intake form containing ``answers`` and land on review.

    The form is always re-exported immediately before filling: accepting a
    proposal bumps the answer instance's row version, and the workbook's
    concurrency token is validated on reimport (conftest landmine 5).
    """
    filled = fill_intake_form(_export_form(base, intake), answers)
    page.goto(_sources_url(base, intake))
    form = page.locator('form[action$="/intake-form/import"]')
    form.locator('input[type="file"]').set_input_files(
        files=[
            {
                "name": timestamped_name("intake-form"),
                "mimeType": XLSX_MIME,
                "buffer": filled,
            }
        ]
    )
    form.locator('button[type="submit"]').click()
    expect(page.locator("h1")).to_have_text("Review extracted data")


def _answered_codes(session_factory: Any, intake_id: str) -> set[str]:
    """
    Return the question codes that hold a canonical answer for this intake.

    Read straight from the append-only answer tables rather than from the
    questionnaire markup, so this spec cannot break when another packet
    redesigns that page.
    """
    from migration_intake.persistence.models import AnswerInstance, CatalogQuestion

    with session_factory() as session:
        rows = session.execute(
            select(CatalogQuestion.question_code, AnswerInstance.current_rev_id).join(
                AnswerInstance, AnswerInstance.question_id == CatalogQuestion.id
            ).where(AnswerInstance.intake_id == intake_id)
        ).all()
    return {code for code, current_rev_id in rows if current_rev_id is not None}


# ---------------------------------------------------------------------------
# Screen 3 — evidence lanes
# ---------------------------------------------------------------------------


def test_sources_page_renders_both_lanes_and_the_form_download(
    page: Page, app_server: str, intake: dict, recorder: Any
) -> None:
    """
    The two upload paths must be separately labelled, not one anonymous input.

    A single unlabelled file field is what let a completed intake form reach
    the source-document reader.
    """
    page.goto(_sources_url(app_server, intake))

    source_lane = page.locator(".lane-card--source")
    form_lane = page.locator(".lane-card--form")
    expect(source_lane).to_have_count(1)
    expect(form_lane).to_have_count(1)

    expect(source_lane).to_contain_text("Source documents")
    expect(source_lane).to_contain_text("UAQ")
    expect(source_lane.locator('form[action$="/evidence"]')).to_have_count(1)

    expect(form_lane).to_contain_text("Intake form")
    expect(form_lane.locator('a[href*="gap-workbook.xlsx"]')).to_have_count(1)
    expect(form_lane.locator('form[action$="/intake-form/import"]')).to_have_count(1)

    # Each lane owns exactly one file input, so neither can be mistaken for
    # the other's.
    expect(source_lane.locator('input[type="file"]')).to_have_count(1)
    expect(form_lane.locator('input[type="file"]')).to_have_count(1)

    # A CSP is enforced and no new shared JS exists this round.
    assert not re.search(r"\son(click|change|submit|input)=", page.content())


def test_quarantined_import_row_shows_the_mismatch_and_how_to_fix(
    page: Page, app_server: str, intake: dict, recorder: Any
) -> None:
    """A quarantined row must diagnose the file, not blame the application."""
    page.goto(_sources_url(app_server, intake))
    page.locator('form[action$="/evidence"] input[type="file"]').set_input_files(
        files=[
            {
                "name": timestamped_name("foreign-uaq"),
                "mimeType": XLSX_MIME,
                "buffer": build_uaq_workbook("99999"),
            }
        ]
    )
    page.locator('form[action$="/evidence"] button[type="submit"]').click()
    page.locator('form[action*="/process-workbook"] button[type="submit"]').last.click()
    expect(page).to_have_url(re.compile(r"/imports/[0-9a-f-]{36}"))

    page.goto(_sources_url(app_server, intake))

    row = page.locator("tr.import-row--quarantined")
    expect(row).to_have_count(1)
    expect(row).to_contain_text("Quarantined")
    # The identifier actually found in the file, and the one expected here.
    expect(row).to_contain_text("99999")
    expect(row).to_contain_text(intake["correlation_id"])
    # Remediation, not a dead end.
    expect(row.locator("details.how-to-fix summary")).to_have_text("How to fix")
    expect(row.locator("details.how-to-fix")).to_contain_text("Correlation ID")
    # And no "Review N" primary action pointing nowhere useful.
    expect(row.locator('a:has-text("Review")')).to_have_count(0)


def test_reviewable_import_row_states_its_outcome_and_primary_action(
    page: Page, app_server: str, intake: dict, recorder: Any
) -> None:
    """Each import row states verdict, proposal count, problems, and next step."""
    _import_answers(page, app_server, intake, {"APP-007": "NO", "APP-003": "ACTIVE"})

    page.goto(_sources_url(app_server, intake))

    row = page.locator("tr.import-row").first
    expect(row).to_contain_text("Intake form")
    expect(row).to_contain_text("Identity verified")
    expect(row).to_contain_text("2 proposals")
    expect(row).to_contain_text("0 problems")
    expect(row.locator('a')).to_have_text("Review →")


# ---------------------------------------------------------------------------
# Screen 4 — bulk review
# ---------------------------------------------------------------------------


def test_bulk_accept_creates_every_answer_in_one_action(
    page: Page, app_server: str, intake: dict, recorder: Any, session_factory: Any
) -> None:
    """Three proposals, one click, three canonical answers."""
    _import_answers(
        page,
        app_server,
        intake,
        {"APP-007": "NO", "APP-005": "DEV, PROD", "APP-003": "ACTIVE"},
    )

    assert _answered_codes(session_factory, intake["intake_id"]) == set()

    rows = page.locator("tr.review-row")
    expect(rows).to_have_count(3)
    expect(page.locator('tr.review-row input[type="checkbox"]:checked')).to_have_count(3)

    page.locator('button:has-text("Accept selected")').click()

    expect(page.locator(".bulk-result__summary")).to_contain_text("3 accepted.")
    assert _answered_codes(session_factory, intake["intake_id"]) == {
        "APP-003",
        "APP-005",
        "APP-007",
    }
    # Nothing is left awaiting a decision, so the bulk table is gone.
    expect(page.locator("tr.review-row")).to_have_count(0)


def test_replacing_proposal_is_flagged_and_never_pre_selected(
    page: Page, app_server: str, intake: dict, recorder: Any
) -> None:
    """
    Silent overwrites are how an application owner value was previously lost.

    A proposal landing on a question that already holds an answer must show
    both values and start unticked.
    """
    _import_answers(page, app_server, intake, {"APP-003": "ACTIVE"})
    page.locator(
        'article.card:has-text("APP-003") form[action$="/accept"] button[type="submit"]'
    ).first.click()

    _import_answers(
        page, app_server, intake, {"APP-003": "MAINTENANCE", "APP-007": "NO"}
    )

    replacing = page.locator("tr#review-row-APP-003")
    expect(replacing).to_have_class(re.compile(r"review-row--replaces"))
    expect(replacing).to_contain_text("ACTIVE")        # what is there now
    expect(replacing).to_contain_text("MAINTENANCE")   # what would land
    expect(replacing).to_contain_text("replaces current")
    expect(replacing.locator('input[type="checkbox"]')).not_to_be_checked()

    additive = page.locator("tr#review-row-APP-007")
    expect(additive).not_to_have_class(re.compile(r"review-row--replaces"))
    expect(additive.locator('input[type="checkbox"]')).to_be_checked()

    # The primary action counts only what is pre-selected.
    expect(page.locator('button:has-text("Accept selected")')).to_contain_text("(1)")


def test_bulk_accept_reports_a_partial_result_and_still_accepts_the_rest(
    page: Page, app_server: str, intake: dict, recorder: Any, session_factory: Any
) -> None:
    """
    One stale row must not fail the batch, nor be reported as a success.

    A second tab decides one proposal after this page was rendered, so the
    submitted concurrency token no longer describes reality.
    """
    _import_answers(
        page,
        app_server,
        intake,
        {"APP-007": "NO", "APP-005": "DEV, PROD", "APP-003": "ACTIVE"},
    )
    coverage_url = page.url

    other = page.context.new_page()
    try:
        other.goto(coverage_url)
        other.locator(
            'article.card:has-text("APP-003") form[action$="/accept"] '
            'button[type="submit"]'
        ).first.click()
        expect(other.locator("h1")).to_have_text("Review extracted data")
    finally:
        other.close()

    # This page still holds the pre-decision selection.
    page.locator('button:has-text("Accept selected")').click()

    summary = page.locator(".bulk-result__summary")
    expect(summary).to_contain_text("2 accepted, 1 skipped.")
    detail = page.locator(".bulk-result__detail")
    expect(detail).to_contain_text("APP-003")
    expect(detail).to_contain_text("stale")

    # The two healthy proposals landed regardless, and APP-003 kept the value
    # the other tab accepted rather than being written twice.
    assert _answered_codes(session_factory, intake["intake_id"]) == {
        "APP-003",
        "APP-005",
        "APP-007",
    }


def test_per_row_accept_survives_alongside_bulk_review(
    page: Page, app_server: str, intake: dict, recorder: Any, session_factory: Any
) -> None:
    """Both surfaces are wanted: one-at-a-time work must still be possible."""
    _import_answers(page, app_server, intake, {"APP-007": "NO", "APP-003": "ACTIVE"})

    expect(page.locator("tr.review-row")).to_have_count(2)
    page.locator(
        'article.card:has-text("APP-007") form[action$="/accept"] button[type="submit"]'
    ).first.click()

    assert _answered_codes(session_factory, intake["intake_id"]) == {"APP-007"}
    expect(page.locator("tr.review-row")).to_have_count(1)
