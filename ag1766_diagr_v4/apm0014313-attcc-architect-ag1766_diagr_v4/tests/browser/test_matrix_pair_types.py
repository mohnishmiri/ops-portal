"""
P1 — Response-type round-trip matrix: the pair family.

Batch companion to ``test_response_type_matrix.py`` (see that module for why
the matrix exists and why it is type-aware). TEXT_PAIR's case lives in the
baseline module; this one covers the other two fixed-pair types:

- CONTROLLED_PAIR, twice: once with published options (two ``<select>``
  elements) and once with none, because APP-004 has no persisted options and
  a ``<select>`` over an empty list can neither display nor accept an answer.
- COUNT_PAIR, whose two counts are submitted and whose ``unit`` is not:
  ``CountPairType.parse_form`` always writes the unit configured on the
  response type and ignores a submitted one, so the editor shows the unit
  read-only rather than pretending it is editable.

All three types submit the canonical payload keys ``first``/``second``; the
per-question named fields (STATE.md, "Named Fields for Pair/Set Types") only
change the visible labels.
"""

from __future__ import annotations

from collections.abc import Callable

import pytest
from playwright.sync_api import Page, expect

from tests.browser.matrix_support import (
    Case,
    fill_text,
    run_round_trip,
    verify_text,
)

pytestmark = pytest.mark.browser


def fill_select_field(field: str, value: str) -> Callable[[Page, str], None]:
    """Choose a value in the named ``<select>`` of a multi-control editor."""

    def _fill(page: Page, code: str) -> None:
        page.locator(f"#question-{code} select[name='{field}']").select_option(value)

    return _fill


def verify_selected_option(field: str, value: str) -> Callable[[Page, str], None]:
    """Prove the server rendered the stored value as the selected option.

    Asserted on the ``selected`` attribute rather than the live value so a
    freshly loaded page cannot pass on client-side state alone.
    """

    def _verify(page: Page, code: str) -> None:
        selected = page.locator(f"#question-{code} select[name='{field}'] option[selected]")
        expect(selected).to_have_count(1)
        expect(selected).to_have_attribute("value", value)

    return _verify


def verify_readonly_unit(unit: str) -> Callable[[Page, str], None]:
    """COUNT_PAIR shows the payload's unit, and does not offer to edit it."""

    def _verify(page: Page, code: str) -> None:
        field = page.locator(f"#q-{code}-unit")
        expect(field).to_have_value(unit)
        expect(field).not_to_be_editable()

    return _verify


def both(*steps: Callable[[Page, str], None]) -> Callable[[Page, str], None]:
    def _run(page: Page, code: str) -> None:
        for step in steps:
            step(page, code)

    return _run


CASES: tuple[Case, ...] = (
    Case(
        "CONTROLLED_PAIR",
        options=("ALPHA", "BETA"),
        fill=both(fill_select_field("first", "ALPHA"), fill_select_field("second", "BETA")),
        verify=both(
            verify_selected_option("first", "ALPHA"),
            verify_selected_option("second", "BETA"),
        ),
    ),
    # No options: the editor must fall back to text inputs, or APP-004 can
    # never be answered at all.
    Case(
        "CONTROLLED_PAIR",
        fill=both(fill_text("first", "CRITICAL"), fill_text("second", "TIER_2")),
        verify=both(verify_text("first", "CRITICAL"), verify_text("second", "TIER_2")),
    ),
    Case(
        "COUNT_PAIR",
        fill=both(fill_text("first", "12"), fill_text("second", "7")),
        verify=both(
            verify_text("first", "12"),
            verify_text("second", "7"),
            # The registry registers CountPairType with its default unit, and
            # parse_form writes that unit regardless of what was submitted.
            verify_readonly_unit("count"),
        ),
    ),
)

CASE_IDS = ("CONTROLLED_PAIR", "CONTROLLED_PAIR-without-options", "COUNT_PAIR")

def _register_coverage() -> None:
    """Tell the baseline module's coverage guard which types this batch covers.

    The guard compares the registry against its own ``COVERED`` set, which is
    built from its own ``CASES``, so a batch that lives in a sibling module
    has to announce itself or the guard would report its types as
    unaccounted-for. Done defensively and by name rather than with a module
    import at the top of this file: the baseline module may itself discover
    sibling batches, and importing it while it is importing this one would
    hand back a half-initialised module.
    """
    import importlib

    baseline = importlib.import_module("tests.browser.test_response_type_matrix")
    covered = getattr(baseline, "COVERED", None)
    if isinstance(covered, set):
        covered.update(case.response_type for case in CASES)


_register_coverage()


@pytest.mark.parametrize(
    "case",
    [
        pytest.param(case, id=case_id)
        for case, case_id in zip(CASES, CASE_IDS, strict=True)
    ],
)
def test_pair_answer_round_trips_through_its_editor(
    page: Page,
    app_server: str,
    intake: dict,
    session_factory,
    catalog_release_id: str,
    case: Case,
) -> None:
    run_round_trip(
        page=page,
        app_server=app_server,
        intake=intake,
        session_factory=session_factory,
        catalog_release_id=catalog_release_id,
        case=case,
    )
