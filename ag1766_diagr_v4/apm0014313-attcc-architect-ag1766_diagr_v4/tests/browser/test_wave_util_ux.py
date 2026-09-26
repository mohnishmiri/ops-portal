"""
UX-4c — WaveUtil list and detail pages, driven through the browser.

Pins behaviour the redesign is for:
- Nav rail is present with WaveUtil active (side-nav was absent before UX-4c).
- Non-design-system class names (filter-select, summary-stats) are gone.
- Client-side filter pills work: PROD click hides DEV rows.
- Detail page uses a <dl> layout for server fields.
- No inline event handlers on any WaveUtil page.
"""
from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.browser

INLINE_HANDLER = re.compile(
    r"\s(onclick|onchange|onsubmit|onload|onerror|onkeyup|onkeydown"
    r"|onfocus|onblur|oninput|onmouseover|onmouseout)=",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _list_url(base: str, intake: dict) -> str:
    return (
        f"{base}/applications/{intake['application_id']}"
        f"/intakes/{intake['intake_id']}/wave-util"
    )


def _detail_url(base: str, intake: dict, row_id: str) -> str:
    return (
        f"{base}/applications/{intake['application_id']}"
        f"/intakes/{intake['intake_id']}/wave-util/{row_id}"
    )


def _seed_wave_util_rows(
    session_factory: Any,
    intake: dict,
    server_env: dict[str, str],
    envs: tuple[str, ...] = ("PROD", "DEV"),
) -> list[str]:
    """
    Seed WaveUtil rows with the given environments.

    Written directly to the database because the WaveUtil import UI belongs
    to another test suite — this one is about the list/detail UX.
    """
    from migration_intake.persistence.models_evidence import WaveUtilRow, WaveUtilRevision

    actor_id = server_env["ACTOR_ID"]
    app_id = intake["application_id"]
    intake_id = intake["intake_id"]
    now = datetime.now(tz=UTC)
    row_ids: list[str] = []

    with session_factory() as session:
        for env in envs:
            row_id = str(uuid.uuid4())
            rev_id = str(uuid.uuid4())
            server_name = f"server-{env.lower()}-{uuid.uuid4().hex[:6]}"
            normalized = server_name.lower()

            row = WaveUtilRow(
                id=row_id,
                application_id=app_id,
                intake_id=intake_id,
                server_name=server_name,
                normalized_server_name=normalized,
                environment=env,
                scope="IN_SCOPE",
                state="ACTIVE",
                current_rev_id=None,
                created_at=now,
                updated_at=now,
                row_version=1,
                created_by_id=actor_id,
            )
            session.add(row)
            session.flush()

            rev = WaveUtilRevision(
                id=rev_id,
                row_id=row_id,
                revision_number=1,
                field_values_json={"cpu": "4", "memory": "16GB"},
                authored_at=now,
                authored_by_id=actor_id,
            )
            session.add(rev)
            session.flush()

            # Break the circular dep: set current_rev_id after revision exists
            row_obj = session.get(WaveUtilRow, row_id)
            row_obj.current_rev_id = rev_id
            row_ids.append(row_id)

        session.commit()

    return row_ids


# ---------------------------------------------------------------------------
# List page tests
# ---------------------------------------------------------------------------


class TestWaveUtilListUX:
    """Browser tests for the WaveUtil list page."""

    def test_nav_rail_present(
        self,
        page: Page,
        app_server: str,
        intake: dict,
        session_factory: Any,
        server_env: dict[str, str],
    ) -> None:
        """Nav rail is present after UX-4c adds nav context to the route."""
        _seed_wave_util_rows(session_factory, intake, server_env)
        page.goto(_list_url(app_server, intake))
        assert page.locator("nav.side-nav").count() > 0

    def test_wave_util_nav_item_is_active(
        self,
        page: Page,
        app_server: str,
        intake: dict,
        session_factory: Any,
        server_env: dict[str, str],
    ) -> None:
        """The 'WaveUtil' side-nav item carries the active class."""
        _seed_wave_util_rows(session_factory, intake, server_env)
        page.goto(_list_url(app_server, intake))
        active = page.locator(".side-nav-item.active")
        expect(active).to_contain_text("WaveUtil")

    def test_no_legacy_css_classes(
        self,
        page: Page,
        app_server: str,
        intake: dict,
        session_factory: Any,
        server_env: dict[str, str],
    ) -> None:
        """Non-design-system class names removed after UX-4c template rewrite."""
        _seed_wave_util_rows(session_factory, intake, server_env)
        page.goto(_list_url(app_server, intake))
        content = page.content()
        assert "filter-select" not in content, "legacy filter-select class found"
        assert "summary-stats" not in content, "legacy summary-stats class found"

    def test_data_wave_util_list_attribute(
        self,
        page: Page,
        app_server: str,
        intake: dict,
        session_factory: Any,
        server_env: dict[str, str],
    ) -> None:
        """Table carries data-wave-util-list so JS filter only activates here."""
        _seed_wave_util_rows(session_factory, intake, server_env)
        page.goto(_list_url(app_server, intake))
        assert page.locator("[data-wave-util-list]").count() > 0

    def test_filter_pill_prod_hides_dev_rows(
        self,
        page: Page,
        app_server: str,
        intake: dict,
        session_factory: Any,
        server_env: dict[str, str],
    ) -> None:
        """Clicking the PROD filter pill hides rows whose environment is DEV."""
        _seed_wave_util_rows(session_factory, intake, server_env, envs=("PROD", "DEV"))
        page.goto(_list_url(app_server, intake))

        # Verify at least one DEV row is visible before filtering
        dev_rows = page.locator("tr[data-environment='DEV']")
        assert dev_rows.count() > 0, "no DEV rows seeded — check _seed_wave_util_rows"

        # Click PROD pill
        page.locator("button.filter-pill[data-filter-env='PROD']").click()

        # DEV rows must now be hidden (JS sets row.hidden = true)
        expect(dev_rows.first).to_be_hidden()

    def test_no_inline_handlers_on_list_page(
        self,
        page: Page,
        app_server: str,
        intake: dict,
        session_factory: Any,
        server_env: dict[str, str],
    ) -> None:
        """No inline on* event handlers in the list page markup."""
        _seed_wave_util_rows(session_factory, intake, server_env)
        page.goto(_list_url(app_server, intake))
        content = page.content()
        assert not INLINE_HANDLER.search(content), "inline event handler found on list page"


# ---------------------------------------------------------------------------
# Detail page tests
# ---------------------------------------------------------------------------


class TestWaveUtilDetailUX:
    """Browser tests for the WaveUtil detail page."""

    def test_detail_page_has_dl_element(
        self,
        page: Page,
        app_server: str,
        intake: dict,
        session_factory: Any,
        server_env: dict[str, str],
    ) -> None:
        """Server detail card uses a <dl> layout with design-system class."""
        row_ids = _seed_wave_util_rows(session_factory, intake, server_env, envs=("PROD",))
        page.goto(_detail_url(app_server, intake, row_ids[0]))
        assert page.locator("dl.detail-grid").count() > 0

    def test_detail_page_nav_rail_active(
        self,
        page: Page,
        app_server: str,
        intake: dict,
        session_factory: Any,
        server_env: dict[str, str],
    ) -> None:
        """WaveUtil item is active in side nav on detail page."""
        row_ids = _seed_wave_util_rows(session_factory, intake, server_env, envs=("PROD",))
        page.goto(_detail_url(app_server, intake, row_ids[0]))
        active = page.locator(".side-nav-item.active")
        expect(active).to_contain_text("WaveUtil")

    def test_no_inline_handlers_on_detail_page(
        self,
        page: Page,
        app_server: str,
        intake: dict,
        session_factory: Any,
        server_env: dict[str, str],
    ) -> None:
        """No inline on* event handlers in the detail page markup."""
        row_ids = _seed_wave_util_rows(session_factory, intake, server_env, envs=("PROD",))
        page.goto(_detail_url(app_server, intake, row_ids[0]))
        content = page.content()
        assert not INLINE_HANDLER.search(content), "inline event handler found on detail page"
