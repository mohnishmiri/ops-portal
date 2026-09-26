"""
P1 — Response-type round-trip matrix: selection batch.

Sibling batch of ``test_response_type_matrix.py`` (see that module's docstring
for why the matrix is type-aware). This batch owns the selection types whose
canonical payload is a *collection*, where the editor contract is not just a
field name but the shape the submitted fields have to arrive in.

``CONTROLLED_SET``'s canonical payload is ``{items: [{code, detail?, scope?}]}``
— a list of objects, not a list of codes — so its editor posts one
``items[<n>].code`` field per checked row rather than a repeated flat name.
"""

from __future__ import annotations

import pytest
from playwright.sync_api import Page

from tests.browser import test_response_type_matrix as baseline
from tests.browser.matrix_support import (
    Case,
    fill_checkboxes,
    run_round_trip,
    verify_checkboxes,
)

pytestmark = pytest.mark.browser


CASES: tuple[Case, ...] = (
    Case(
        "CONTROLLED_SET",
        options=("OUTPOST", "AWS_REGION", "ON_PREMISES"),
        # Deliberately non-adjacent options: the checked rows carry
        # non-contiguous indices, which the boundary must not renumber into
        # the wrong codes or drop.
        fill=fill_checkboxes(("OUTPOST", "ON_PREMISES")),
        verify=verify_checkboxes(("OUTPOST", "ON_PREMISES")),
    ),
)

#: Report this batch's coverage to the baseline module's guard. The guard
#: compares the registry against the union of covered types, but its
#: ``COVERED`` set can only see its own ``CASES``; sibling batches are written
#: in parallel and must not edit the shared module beyond removing their own
#: ``PENDING_COVERAGE`` entries, so each batch registers itself.
baseline.COVERED.update(case.response_type for case in CASES)


@pytest.mark.parametrize("case", CASES, ids=lambda c: c.response_type)
def test_answer_round_trips_through_its_editor(
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


def test_unchecked_rows_are_not_stored(
    page: Page,
    app_server: str,
    intake: dict,
    session_factory,
    catalog_release_id: str,
) -> None:
    """An option left unchecked must not come back checked.

    The list-of-objects boundary builds one item per submitted index, so an
    off-by-one there would silently store a code the user never selected —
    exactly the class of silent mis-save this matrix exists to catch.
    """
    case = Case(
        "CONTROLLED_SET",
        options=("OUTPOST", "AWS_REGION", "ON_PREMISES"),
        fill=fill_checkboxes(("ON_PREMISES",)),
        verify=verify_checkboxes(("ON_PREMISES",)),
    )
    run_round_trip(
        page=page,
        app_server=app_server,
        intake=intake,
        session_factory=session_factory,
        catalog_release_id=catalog_release_id,
        case=case,
    )
    from playwright.sync_api import expect

    for unchecked in ("OUTPOST", "AWS_REGION"):
        expect(
            page.locator(f"input[type=checkbox][value='{unchecked}']").first
        ).not_to_be_checked()
