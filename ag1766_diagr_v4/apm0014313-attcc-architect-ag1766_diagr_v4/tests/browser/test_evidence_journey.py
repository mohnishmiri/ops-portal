"""
J4 — Evidence import journey, driven entirely through the browser.

Upload synthetic UAQ evidence, process it, review the proposals, accept one,
and confirm the accepted value is the answer the questionnaire shows. This is
the application's primary value path; every step below broke at least once
during manual testing.
"""

from __future__ import annotations

import re
from typing import Any

import pytest
from playwright.sync_api import Page, expect

from tests.browser.conftest import build_uaq_workbook, timestamped_name
from tests.browser.invariants import assert_no_horizontal_overflow

pytestmark = pytest.mark.browser


def _sources_url(base: str, intake: dict) -> str:
    return (
        f"{base}/applications/{intake['application_id']}"
        f"/intakes/{intake['intake_id']}/sources"
    )


def _upload_and_process(page: Page, base: str, intake: dict, content: bytes) -> None:
    """Upload evidence through the UI and trigger processing."""
    page.goto(_sources_url(base, intake))
    page.locator('form[action$="/evidence"] input[type="file"]').set_input_files(
        files=[
            {
                "name": timestamped_name("synthetic-uaq"),
                "mimeType": (
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                ),
                "buffer": content,
            }
        ]
    )
    page.locator('form[action$="/evidence"] button[type="submit"]').click()
    expect(page.locator("table")).to_contain_text("ACTIVE")

    # Processing redirects straight to the import run, so wait for that page
    # rather than for a state change in the sources table.
    page.locator('form[action*="/process-workbook"] button[type="submit"]').last.click()
    expect(page).to_have_url(re.compile(r"/imports/[0-9a-f-]{36}"))


def test_evidence_upload_review_accept_reaches_questionnaire(
    page: Page, app_server: str, intake: dict, recorder: Any
) -> None:
    _upload_and_process(
        page, app_server, intake, build_uaq_workbook(intake["correlation_id"])
    )

    # _upload_and_process leaves us on the import run page.
    expect(page.locator("h1")).to_have_text("Import Run Details")

    page.locator('a:has-text("Review extracted data")').click()
    expect(page.locator("h1")).to_have_text("Review extracted data")

    # Identity must be verified, or no proposal is actionable.
    expect(page.locator("body")).to_contain_text("APPLICATION_MATCHED")
    assert_no_horizontal_overflow(page)

    # APP-003 is mapped from the synthetic UAQ operational-status column.
    card = page.locator('article.card:has-text("APP-003")').first
    expect(card).to_contain_text("ACTIVE")

    accept = card.locator('form[action$="/accept"] button[type="submit"]')
    expect(accept).to_be_visible()
    accept.click()

    # The accepted value must now be the questionnaire's current answer.
    page.goto(
        f"{app_server}/applications/{intake['application_id']}"
        f"/intakes/{intake['intake_id']}/questionnaire/APPLICATION"
    )
    selected = page.locator("#q-APP-003-input option[selected]")
    expect(selected).to_have_count(1)
    expect(selected).to_have_attribute("value", "ACTIVE")


def test_mismatched_identity_quarantines_and_offers_no_accept(
    page: Page, app_server: str, intake: dict, recorder: Any
) -> None:
    """A correlation ID belonging to another application must not be acceptable."""
    _upload_and_process(page, app_server, intake, build_uaq_workbook("99999"))

    page.locator('a:has-text("Review extracted data")').click()

    expect(page.locator("body")).to_contain_text("Quarantined")
    # The verdict must name the mismatching identifier, not just refuse.
    expect(page.locator(".quarantine-panel")).to_contain_text("99999")
    # …and offer a way out rather than a dead end.
    expect(page.locator(".quarantine-panel .how-to-fix summary")).to_have_text("How to fix")
    expect(page.locator('button:has-text("Accept")')).to_have_count(0)


def test_unrecognized_sheet_is_reported_not_silent(
    page: Page, app_server: str, intake: dict, recorder: Any
) -> None:
    """
    A workbook whose sheet matches no source contract must say so.

    Silent skipping previously made a renamed or Excel-truncated tab
    indistinguishable from an empty file.
    """
    from io import BytesIO

    from openpyxl import Workbook

    workbook = Workbook()
    workbook.active.title = "Totally Unknown Tab"
    workbook.active.append(["Trace Token", "x"])
    workbook.active.append(["value", timestamped_name("trace", "txt")])
    stream = BytesIO()
    workbook.save(stream)

    _upload_and_process(page, app_server, intake, stream.getvalue())

    expect(page.locator("body")).to_contain_text("UNRECOGNIZED_SHEET")
    expect(page.locator("body")).to_contain_text("Totally Unknown Tab")
