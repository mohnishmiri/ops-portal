"""
UX-4b — Readiness pages, driven through the browser.

Validates:
- No Tailwind utility classes on any readiness page
- Nav rail present with Readiness link active
- Failing dimension has danger CSS class; freeze button absent
- Ready intake shows freeze button
- Snapshot page shows frozen banner, no freeze button
"""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from playwright.sync_api import Page, expect

from tests.browser.conftest import timestamped_name

pytestmark = pytest.mark.browser

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Patterns that indicate leftover Tailwind classes
_TAILWIND_PATTERNS = [
    re.compile(r'\bbg-(?:green|red|blue|yellow|gray|white)-\d+\b'),
    re.compile(r'\btext-(?:green|red|blue|yellow|gray)-\d+\b'),
    re.compile(r'\brounded-lg\b'),
    re.compile(r'\bpx-\d+\b'),
    re.compile(r'\bpy-\d+\b'),
    re.compile(r'\bmx-auto\b'),
    re.compile(r'\bfont-bold\b'),
    re.compile(r'\bspace-[xy]-\d+\b'),
]


def _readiness_url(base: str, intake: dict) -> str:
    return f"{base}/intakes/{intake['intake_id']}/readiness"


def _snapshot_url(base: str, intake: dict) -> str:
    return f"{base}/intakes/{intake['intake_id']}/snapshot"


def _assert_no_tailwind(page: Page, context_name: str = "") -> None:
    """Assert that no known Tailwind utility classes appear in the page HTML."""
    content = page.content()
    for pattern in _TAILWIND_PATTERNS:
        match = pattern.search(content)
        assert match is None, (
            f"Tailwind class '{match.group()}' found on page{' (' + context_name + ')' if context_name else ''}"
        )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def intake_unready(session_factory: Any, catalog_release_id: str, server_env: dict) -> dict:
    """
    Create an application + intake with a PROPOSED candidate so that
    the readiness check returns is_ready=False.
    """
    from migration_intake.application.dto import ActorContext
    from migration_intake.application.services.applications import ApplicationService
    from migration_intake.application.commands import (
        CreateApplicationCommand,
        CreateIntakeCommand,
        IdentifierInput,
    )
    from migration_intake.persistence.models_evidence import EvidenceItem
    from migration_intake.persistence.models_imports import ImportRun
    from migration_intake.persistence.models_candidates import Candidate

    actor = ActorContext(
        actor_id=server_env["ACTOR_ID"],
        display_name="Browser Suite Actor",
        actor_type="CONFIGURED",
    )
    service = ApplicationService(session_factory)
    suffix = uuid.uuid4().hex[:6]
    correlation_id = str(uuid.uuid4().int % 90000000 + 10000000)

    application = service.create_application(
        CreateApplicationCommand(
            display_name=f"Unready App {suffix}",
            identifiers=(
                IdentifierInput(identifier_type="CORRELATION", raw_value=correlation_id),
            ),
            actor=actor,
        )
    )
    created = service.create_intake(
        CreateIntakeCommand(
            application_id=application["id"],
            catalog_release_id=catalog_release_id,
            actor=actor,
        )
    )

    app_id = application["id"]
    intake_id = created["id"]
    actor_id = server_env["ACTOR_ID"]
    now = datetime.now(tz=UTC)

    # Seed a PROPOSED candidate to block the freeze
    with session_factory() as session:
        evidence_id = str(uuid.uuid4())
        run_id = str(uuid.uuid4())

        session.add(
            EvidenceItem(
                id=evidence_id,
                application_id=app_id,
                intake_id=intake_id,
                storage_key=f"test/{uuid.uuid4().hex}",
                sha256_hex="a" * 64,
                size_bytes=100,
                created_at=now,
                created_by_id=actor_id,
            )
        )
        session.flush()

        session.add(
            ImportRun(
                id=run_id,
                application_id=app_id,
                intake_id=intake_id,
                evidence_item_id=evidence_id,
                contract_name="TEST",
                parser_version="1.0",
                state="COMPLETED",
                created_at=now,
                created_by_id=actor_id,
            )
        )
        session.flush()

        session.add(
            Candidate(
                id=str(uuid.uuid4()),
                import_run_id=run_id,
                application_id=app_id,
                intake_id=intake_id,
                evidence_item_id=evidence_id,
                target_kind="QUESTION",
                target_key="Q-TEST-001",
                origin="test-fixture",
                extractor_version="1.0",
                contract_version="1.0",
                raw_value_json='{"value": "synthetic-test-value"}',
                state="PROPOSED",
                row_version=1,
                created_at=now,
            )
        )
        session.commit()

    return {
        "application_id": app_id,
        "intake_id": intake_id,
        "correlation_id": correlation_id,
    }


# ---------------------------------------------------------------------------
# Tests: readiness report page (ready intake)
# ---------------------------------------------------------------------------


def test_readiness_page_no_tailwind(
    page: Page, app_server: str, intake: dict
) -> None:
    """The readiness page contains no Tailwind utility classes."""
    page.goto(_readiness_url(app_server, intake))
    page.wait_for_load_state("networkidle")

    _assert_no_tailwind(page, "readiness report")


def test_readiness_page_nav_rail_present(
    page: Page, app_server: str, intake: dict
) -> None:
    """The nav rail is rendered on the readiness page."""
    page.goto(_readiness_url(app_server, intake))
    page.wait_for_load_state("networkidle")

    # Side nav exists
    nav = page.locator("nav.side-nav")
    expect(nav).to_be_visible()


def test_readiness_nav_item_active(
    page: Page, app_server: str, intake: dict
) -> None:
    """The Readiness nav item is marked as the active link."""
    page.goto(_readiness_url(app_server, intake))
    page.wait_for_load_state("networkidle")

    # The readiness link should have aria-current="page"
    active_link = page.locator("nav.side-nav a[aria-current='page']")
    expect(active_link).to_contain_text("Readiness")


def test_readiness_ready_intake_shows_freeze_button(
    page: Page, app_server: str, intake: dict
) -> None:
    """A ready intake displays the Freeze button."""
    page.goto(_readiness_url(app_server, intake))
    page.wait_for_load_state("networkidle")

    freeze_button = page.locator("button[type='submit']")
    expect(freeze_button).to_be_visible()
    expect(freeze_button).to_contain_text("Freeze")


def test_readiness_ready_has_csrf_in_form(
    page: Page, app_server: str, intake: dict
) -> None:
    """The freeze form contains a CSRF token field."""
    page.goto(_readiness_url(app_server, intake))
    page.wait_for_load_state("networkidle")

    csrf_input = page.locator("input[name='_csrf_token']")
    expect(csrf_input).to_have_count(1)
    # Token value must be non-empty
    token_value = csrf_input.get_attribute("value") or ""
    assert len(token_value) > 10, "CSRF token is unexpectedly short"


def test_readiness_uses_design_system_status_card(
    page: Page, app_server: str, intake: dict
) -> None:
    """The status card uses the readiness-status design-system class."""
    page.goto(_readiness_url(app_server, intake))
    page.wait_for_load_state("networkidle")

    status_card = page.locator(".readiness-status")
    expect(status_card).to_be_visible()


# ---------------------------------------------------------------------------
# Tests: readiness report page (unready intake)
# ---------------------------------------------------------------------------


def test_readiness_unready_fail_dimension_has_danger_class(
    page: Page, app_server: str, intake_unready: dict
) -> None:
    """A failing dimension gets the readiness-dimension--fail class."""
    page.goto(_readiness_url(app_server, intake_unready))
    page.wait_for_load_state("networkidle")

    fail_dims = page.locator(".readiness-dimension--fail")
    expect(fail_dims).to_have_count(
        fail_dims.count() or 1,  # at least one
    )
    assert fail_dims.count() > 0, "Expected at least one failing dimension with danger class"


def test_readiness_unready_no_freeze_button(
    page: Page, app_server: str, intake_unready: dict
) -> None:
    """When not ready, the freeze submit button is absent."""
    page.goto(_readiness_url(app_server, intake_unready))
    page.wait_for_load_state("networkidle")

    freeze_button = page.locator("button[type='submit']")
    expect(freeze_button).to_have_count(0)


def test_readiness_unready_no_tailwind(
    page: Page, app_server: str, intake_unready: dict
) -> None:
    """The not-ready readiness page contains no Tailwind utility classes."""
    page.goto(_readiness_url(app_server, intake_unready))
    page.wait_for_load_state("networkidle")

    _assert_no_tailwind(page, "not-ready readiness report")


# ---------------------------------------------------------------------------
# Tests: snapshot page (after freeze)
# ---------------------------------------------------------------------------


def test_snapshot_page_shows_frozen_banner(
    page: Page, app_server: str, intake: dict
) -> None:
    """After freeze, the snapshot page displays the read-only frozen banner."""
    import httpx

    # Freeze the intake through the JSON API (no CSRF required)
    resp = httpx.post(
        f"{app_server}/intakes/{intake['intake_id']}/freeze.json",
        timeout=15.0,
    )
    assert resp.status_code == 200, f"Freeze failed: {resp.text[:200]}"

    page.goto(_snapshot_url(app_server, intake))
    page.wait_for_load_state("networkidle")

    banner = page.locator(".readiness-frozen-banner")
    expect(banner).to_be_visible()
    expect(banner).to_contain_text("read-only")


def test_snapshot_page_no_freeze_button(
    page: Page, app_server: str, intake: dict
) -> None:
    """The snapshot page does not offer a freeze action."""
    import httpx

    httpx.post(
        f"{app_server}/intakes/{intake['intake_id']}/freeze.json",
        timeout=15.0,
    )

    page.goto(_snapshot_url(app_server, intake))
    page.wait_for_load_state("networkidle")

    # No form posting to freeze endpoint
    freeze_forms = page.locator("form[action*='/freeze']")
    expect(freeze_forms).to_have_count(0)


def test_snapshot_page_has_nav_rail(
    page: Page, app_server: str, intake: dict
) -> None:
    """The snapshot page renders the nav rail."""
    import httpx

    httpx.post(
        f"{app_server}/intakes/{intake['intake_id']}/freeze.json",
        timeout=15.0,
    )

    page.goto(_snapshot_url(app_server, intake))
    page.wait_for_load_state("networkidle")

    nav = page.locator("nav.side-nav")
    expect(nav).to_be_visible()


def test_snapshot_page_no_tailwind(
    page: Page, app_server: str, intake: dict
) -> None:
    """The snapshot page contains no Tailwind utility classes."""
    import httpx

    httpx.post(
        f"{app_server}/intakes/{intake['intake_id']}/freeze.json",
        timeout=15.0,
    )

    page.goto(_snapshot_url(app_server, intake))
    page.wait_for_load_state("networkidle")

    _assert_no_tailwind(page, "snapshot")
