"""
Shared helpers for the response-type round-trip matrix.

Kept separate from the spec files so batches of response types can be worked
on in parallel without colliding in one CASES tuple.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any, Callable

from playwright.sync_api import Page, expect

@dataclass(frozen=True)
class Case:
    """How to fill one response type's editor and how to prove it round-tripped."""

    response_type: str
    options: tuple[str, ...] = ()
    fill: Callable[[Page, str], None] = lambda page, code: None
    verify: Callable[[Page, str], None] = lambda page, code: None


def fill_select(value: str) -> Callable[[Page, str], None]:
    def _fill(page: Page, code: str) -> None:
        page.locator(f"#q-{code}-input").select_option(value)

    return _fill


def verify_select(value: str) -> Callable[[Page, str], None]:
    def _verify(page: Page, code: str) -> None:
        selected = page.locator(f"#q-{code}-input option[selected]")
        expect(selected).to_have_count(1)
        expect(selected).to_have_attribute("value", value)

    return _verify


def fill_text(field: str, value: str) -> Callable[[Page, str], None]:
    def _fill(page: Page, code: str) -> None:
        page.locator(f"#question-{code} [name='{field}']").first.fill(value)

    return _fill


def verify_text(field: str, value: str) -> Callable[[Page, str], None]:
    def _verify(page: Page, code: str) -> None:
        expect(page.locator(f"#question-{code} [name='{field}']").first).to_have_value(value)

    return _verify


def fill_radio(option_id: str) -> Callable[[Page, str], None]:
    def _fill(page: Page, code: str) -> None:
        page.locator(f"#q-{code}-{option_id}").check()

    return _fill


def verify_radio(option_id: str) -> Callable[[Page, str], None]:
    def _verify(page: Page, code: str) -> None:
        expect(page.locator(f"#q-{code}-{option_id}")).to_be_checked()

    return _verify


def fill_checkboxes(values: tuple[str, ...]) -> Callable[[Page, str], None]:
    def _fill(page: Page, code: str) -> None:
        for value in values:
            page.locator(f"#question-{code} input[type=checkbox][value='{value}']").check()

    return _fill


def verify_checkboxes(values: tuple[str, ...]) -> Callable[[Page, str], None]:
    def _verify(page: Page, code: str) -> None:
        for value in values:
            expect(
                page.locator(f"#question-{code} input[type=checkbox][value='{value}']")
            ).to_be_checked()

    return _verify


def seed_question(session_factory: Any, catalog_id: str, case: Case) -> str:
    """Seed one active REQUIRED question of this response type, with options."""
    from sqlalchemy.orm import Session

    from migration_intake.persistence.models import (
        CatalogOption,
        CatalogQuestion,
        CatalogSection,
    )

    code = f"MTX-{uuid.uuid4().hex[:6].upper()}"
    with Session(session_factory.kw["bind"]) as session:
        section_id = str(uuid.uuid4())
        session.add(
            CatalogSection(
                id=section_id,
                release_id=catalog_id,
                section_code=f"MATRIX-{code}",
                display_name=f"Matrix {case.response_type}",
                display_order=900,
            )
        )
        session.flush()
        question_id = str(uuid.uuid4())
        session.add(
            CatalogQuestion(
                id=question_id,
                section_id=section_id,
                question_code=code,
                question_text=f"Matrix probe for {case.response_type}",
                response_type=case.response_type,
                required_level="REQUIRED",
                collection_mode="SINGLE",
                display_order=1,
                is_active=True,
                response_schema_version="1.0",
            )
        )
        session.flush()
        for order, option in enumerate(case.options, start=1):
            session.add(
                CatalogOption(
                    id=str(uuid.uuid4()),
                    question_id=question_id,
                    option_code=option,
                    display_label=option.title(),
                    display_order=order,
                )
            )
        session.commit()
    return f"MATRIX-{code}", code




def expand_question(page: Page, question_code: str) -> None:
    """
    Force a question's disclosure open.

    Answered questions render collapsed (UX-1), so a reloaded question is
    closed by the time the matrix reads its editor back. ``open`` is set
    directly rather than clicked, because clicking the summary of an already
    open question would close it.
    """
    page.locator(f"#question-{question_code} details.qx-disclosure").evaluate(
        "element => { element.open = true; }"
    )


def save_by_blurring(page: Page, question_code: str) -> None:
    """
    Commit the answer the way a user does: by leaving the field.

    There is no Save button any more — the questionnaire autosaves on blur —
    so this blurs whatever the editor left focused and then waits for the
    saved indicator. Waiting is not optional: without it the reload below
    races the in-flight POST and the assertion reads a stale page.
    """
    page.evaluate(
        "() => { if (document.activeElement) { document.activeElement.blur(); } }"
    )
    expect(
        page.locator(f"#q-{question_code}-save[data-state='saved']")
    ).to_be_visible()


def run_round_trip(
    *,
    page: Page,
    app_server: str,
    intake: dict,
    session_factory: Any,
    catalog_release_id: str,
    case: Case,
) -> None:
    """Seed, fill, autosave, reload, and prove the editor renders the value back."""
    section_code, question_code = seed_question(session_factory, catalog_release_id, case)
    section_url = (
        f"{app_server}/applications/{intake['application_id']}"
        f"/intakes/{intake['intake_id']}/questionnaire/{section_code}"
    )

    page.goto(section_url)
    expect(page.locator(f"#question-{question_code}")).to_be_visible()

    case.fill(page, question_code)
    save_by_blurring(page, question_code)

    # A save that silently stored nothing is the exact failure this catches:
    # the value must be rendered back by the editor after a reload.
    page.goto(section_url)
    expand_question(page, question_code)
    case.verify(page, question_code)
