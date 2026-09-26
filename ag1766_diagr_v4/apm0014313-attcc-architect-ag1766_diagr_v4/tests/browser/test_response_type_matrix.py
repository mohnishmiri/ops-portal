"""
P1 — Response-type round-trip matrix (baseline batch).

For every non-computed response type: seed a question of that type, fill its
editor in the browser, save, reload, and assert the value is displayed back.

This exists because the editor templates and the canonical response payloads
were written against different field names, in both directions, for twelve of
nineteen types — so answers were stored and then rendered blank, with no error
anywhere. One generic assertion cannot catch that: each type has its own
editor contract, so the matrix is deliberately type-aware.

Batches for the remaining types live in sibling ``test_matrix_*.py`` modules
so they can be built in parallel. ``PENDING_COVERAGE`` is the shrinking list
of types that still have no case; the coverage guard fails if a type is
neither covered nor explicitly pending, so the matrix cannot fall behind the
registry unnoticed.
"""

from __future__ import annotations

import csv
import pathlib
import re

import pytest
from playwright.sync_api import Page, expect

from tests.browser.matrix_support import (
    Case,
    fill_checkboxes,
    fill_radio,
    fill_select,
    fill_text,
    run_round_trip,
    verify_checkboxes,
    verify_radio,
    verify_select,
    verify_text,
)

pytestmark = pytest.mark.browser


CASES: tuple[Case, ...] = (
    Case("TEXT", fill=fill_text("text", "round trip"), verify=verify_text("text", "round trip")),
    Case(
        "LONG_TEXT",
        fill=fill_text("text", "a longer round trip"),
        verify=verify_text("text", "a longer round trip"),
    ),
    Case(
        "SINGLE_SELECT",
        options=("ALPHA", "BETA"),
        fill=fill_select("BETA"),
        verify=verify_select("BETA"),
    ),
    Case(
        "MEASUREMENT",
        fill=fill_text("value", "42"),
        verify=verify_text("value", "42"),
    ),
    Case(
        "BOOLEAN",
        options=("YES", "NO", "UNKNOWN"),
        fill=fill_radio("no"),
        verify=verify_radio("no"),
    ),
    Case(
        "MULTI_SELECT",
        options=("ALPHA", "BETA", "GAMMA"),
        fill=fill_checkboxes(("ALPHA", "GAMMA")),
        verify=verify_checkboxes(("ALPHA", "GAMMA")),
    ),
    Case(
        "TEXT_PAIR",
        fill=lambda page, code: (
            fill_text("first", "Full Name")(page, code),
            fill_text("second", "ACR")(page, code),
        ),
        verify=lambda page, code: (
            verify_text("first", "Full Name")(page, code),
            verify_text("second", "ACR")(page, code),
        ),
    ),
)

#: Types with no round-trip case yet. Remove a type from here in the same
#: change that adds its case — the guard below then holds the line.
PENDING_COVERAGE: frozenset[str] = frozenset(
    {
        "IDENTIFIER",  # validate() requires identifier_type alongside value
        "BOOLEAN_WITH_RATIONALE",
        "DECISION_WITH_PERSON",
        "EVIDENCE_REFERENCE",
        "MEASUREMENT_CONTEXT",
        "MEASUREMENT_PAIR",
        "MEASUREMENT_SET",
        "PEOPLE_LIST",
        "SINGLE_SELECT_PER_COMPONENT",
    }
)

COVERED = {case.response_type for case in CASES}


def _fillable_types() -> set[str]:
    from migration_intake.catalog.response_types import get_default_registry

    registry = get_default_registry()
    with open(
        "src/migration_intake/catalog/data/catalog-0.2.0.csv", encoding="utf-8-sig"
    ) as handle:
        in_use = {row["Response_Type"] for row in csv.DictReader(handle)}
    return {
        code
        for code in in_use
        if (rt := registry.get(code)) is not None and not rt.is_computed
    }


def _covered_by_all_batches() -> set[str]:
    """
    Collect covered types from this module and every sibling batch.

    Read from the files rather than importing them: batch modules import this
    one for shared state, so importing them back deadlocks on a circular
    import. Scanning also means the guard is correct when only a subset of
    batch files is collected, instead of falsely reporting another batch's
    types as unaccounted.
    """
    covered = set(COVERED)
    here = pathlib.Path(__file__).parent
    for module in here.glob("test_matrix_*.py"):
        covered |= set(
            re.findall(r'Case\(\s*"([A-Z_]+)"', module.read_text(encoding="utf-8"))
        )
    return covered


def test_matrix_does_not_fall_behind_the_registry() -> None:
    """Every fillable type is either covered or explicitly pending."""
    unaccounted = sorted(_fillable_types() - _covered_by_all_batches() - PENDING_COVERAGE)
    assert not unaccounted, (
        "response types used by the catalog are neither covered by a "
        f"round-trip case nor listed as pending: {unaccounted}"
    )


def test_pending_coverage_is_honest() -> None:
    """A type cannot be listed as pending once it has a case."""
    both = sorted(_covered_by_all_batches() & PENDING_COVERAGE)
    assert not both, f"types are both covered and listed pending: {both}"


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
