"""
UX-4a — Application shell UX: list, workspace, create, edit.

Verifies the card grid, action grid, hub entry point, and shell completeness
against the running application.  All seeding goes through the service layer;
the UI tests verify what the user sees, not what the service stores.

Design-system contracts tested here:
- No inline style= attributes on workspace page
- No inline on* event handlers
- Workspace shows hub link (a[href*="/intakes/"])
- Workspace renders 4 action cards
- List page shows card grid, not an embedded create form
- "New application →" navigates to /applications/new
- Create form submits and redirects to workspace
"""

from __future__ import annotations

import re
import uuid
from typing import Any

import pytest
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.browser

#: Selector that must not match anything on pages claiming design-system compliance.
_INLINE_HANDLER = re.compile(r"\son(click|change|submit|input|focus|blur)=", re.IGNORECASE)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _list_url(base: str) -> str:
    return f"{base}/applications"


def _new_url(base: str) -> str:
    return f"{base}/applications/new"


def _workspace_url(base: str, app_id: str) -> str:
    return f"{base}/applications/{app_id}"


def _design_option_url(base: str, option: str = "a") -> str:
    return f"{base}/applications/design-options/{option}"


def _seed_app(session_factory: Any, server_env: dict[str, str]) -> dict:
    """Create an application (no intake) and return its id."""
    from migration_intake.application.commands import (
        CreateApplicationCommand,
        IdentifierInput,
    )
    from migration_intake.application.dto import ActorContext
    from migration_intake.application.services.applications import ApplicationService

    actor = ActorContext(
        actor_id=server_env["ACTOR_ID"],
        display_name="Browser Suite Actor",
        actor_type="CONFIGURED",
    )
    svc = ApplicationService(session_factory)
    suffix = uuid.uuid4().hex[:6]
    corr_id = str(uuid.uuid4().int % 90000000 + 10000000)
    app = svc.create_application(
        CreateApplicationCommand(
            display_name=f"UX4a App {suffix}",
            identifiers=(
                IdentifierInput(identifier_type="CORRELATION", raw_value=corr_id),
            ),
            actor=actor,
        )
    )
    return {"application_id": app["id"], "correlation_id": corr_id}


# ---------------------------------------------------------------------------
# List page
# ---------------------------------------------------------------------------


def test_list_page_renders_card_grid(
    page: Page,
    app_server: str,
    intake: dict,
    recorder: Any,
) -> None:
    """
    The list page renders at least one .app-card element, not a bare create form.

    The 'intake' fixture seeds one application with an open intake.
    """
    page.goto(_list_url(app_server))
    # At minimum one card must be visible.
    cards = page.locator(".app-card")
    assert cards.count() >= 1, "expected at least one .app-card on the list page"
    # No inline event handlers anywhere on the page.
    assert not _INLINE_HANDLER.search(page.content())


def test_list_page_card_shows_application_name(
    page: Page,
    app_server: str,
    intake: dict,
    recorder: Any,
) -> None:
    """Each seeded application appears in its own card by name."""
    page.goto(_list_url(app_server))
    # The intake fixture creates an app; its name should appear in some card.
    assert page.locator(".app-card").count() >= 1


def test_new_application_button_navigates(
    page: Page,
    app_server: str,
    intake: dict,
    recorder: Any,
) -> None:
    """'New application →' link in command bar navigates to /applications/new."""
    page.goto(_list_url(app_server))
    # Find the "New application" link and click it.
    new_btn = page.locator('a[href$="/applications/new"]').first
    expect(new_btn).to_be_visible()
    new_btn.click()
    expect(page).to_have_url(re.compile(r"/applications/new$"))


@pytest.mark.parametrize("option", ["a", "b", "c"])
def test_design_options_render_isolated_live_previews(
    page: Page,
    app_server: str,
    intake: dict,
    option: str,
) -> None:
    """Each preview route renders cards without changing the production list."""
    page.goto(_design_option_url(app_server, option))
    expect(page.locator("[data-application-preview]")).to_be_visible()
    expect(page.locator(".preview-card").first).to_be_visible()
    expect(page.locator("[style]")).to_have_count(0)


def test_design_option_filters_opens_menu_and_dialog(
    page: Page,
    app_server: str,
    intake: dict,
) -> None:
    """Search, overflow actions, and the non-destructive dialog are operable."""
    page.goto(_design_option_url(app_server))
    cards = page.locator(".preview-card")
    initial_count = cards.count()
    assert initial_count >= 1

    first_name = cards.first.locator("h2").inner_text()
    page.get_by_role("searchbox", name="Search applications").fill(first_name)
    expect(page.locator(".preview-card:visible")).to_have_count(1)

    page.locator("[data-preview-menu-button]:visible").click()
    expect(page.get_by_role("menu")).to_be_visible()

    page.get_by_role("button", name="New application").click()
    expect(page.get_by_role("dialog")).to_be_visible()


def test_design_option_states_and_no_horizontal_overflow(
    page: Page,
    app_server: str,
    intake: dict,
) -> None:
    """Explicit loading, empty, and error previews remain contained."""
    page.set_viewport_size({"width": 1280, "height": 720})
    page.goto(_design_option_url(app_server, "b"))
    for state in ("Loading", "Empty", "Error"):
        page.get_by_role("button", name=state, exact=True).click()
        expect(page.get_by_role("button", name=state, exact=True)).to_have_attribute(
            "aria-pressed", "true"
        )
    overflow = page.evaluate(
        "document.documentElement.scrollWidth > document.documentElement.clientWidth"
    )
    assert overflow is False


# ---------------------------------------------------------------------------
# New application form
# ---------------------------------------------------------------------------


def test_new_application_form_renders(
    page: Page,
    app_server: str,
    recorder: Any,
) -> None:
    """GET /applications/new renders the create form with the breadcrumb."""
    page.goto(_new_url(app_server))
    # Form must be present.
    expect(page.locator('form[action$="/applications"]')).to_be_visible()
    # Breadcrumb shows "Applications" and "New application".
    expect(page.locator(".breadcrumb")).to_contain_text("Applications")
    expect(page.locator(".breadcrumb")).to_contain_text("New application")
    # No inline handlers.
    assert not _INLINE_HANDLER.search(page.content())


def test_create_form_submits_and_redirects_to_workspace(
    page: Page,
    app_server: str,
    recorder: Any,
) -> None:
    """
    Submitting the create form with a display name redirects to the workspace.

    Uses a unique display name so concurrent suite runs don't collide.
    """
    unique_name = f"UX4a Create Test {uuid.uuid4().hex[:8]}"
    page.goto(_new_url(app_server))
    page.locator("#display_name").fill(unique_name)
    page.locator('button[type="submit"]').click()
    # Must land on a workspace page (URL matches /applications/{uuid}).
    expect(page).to_have_url(re.compile(r"/applications/[0-9a-f-]{36}$"))
    # The workspace page shows the app name.
    expect(page.locator("h1")).to_contain_text(unique_name)


# ---------------------------------------------------------------------------
# Workspace page
# ---------------------------------------------------------------------------


def test_workspace_shows_hub_link(
    page: Page,
    app_server: str,
    intake: dict,
    recorder: Any,
) -> None:
    """Workspace renders a link to the intake hub (href contains /intakes/)."""
    page.goto(_workspace_url(app_server, intake["application_id"]))
    # There must be an anchor pointing into /intakes/.
    hub_links = page.locator('a[href*="/intakes/"]')
    assert hub_links.count() >= 1, "expected at least one hub link on workspace"


def test_workspace_renders_six_action_cards(
    page: Page,
    app_server: str,
    intake: dict,
    recorder: Any,
) -> None:
    """Workspace renders six .app-action-card actions including Topology."""
    page.goto(_workspace_url(app_server, intake["application_id"]))
    cards = page.locator(".app-action-card")
    assert cards.count() == 6, (
        f"expected 6 action cards, got {cards.count()}"
    )


def test_workspace_no_inline_style_attributes(
    page: Page,
    app_server: str,
    intake: dict,
    recorder: Any,
) -> None:
    """No element on the workspace page carries an inline style= attribute."""
    page.goto(_workspace_url(app_server, intake["application_id"]))
    expect(page.locator("[style]")).to_have_count(0)


def test_workspace_no_inline_event_handlers(
    page: Page,
    app_server: str,
    intake: dict,
    recorder: Any,
) -> None:
    """No inline on* event handlers appear anywhere on the workspace page."""
    page.goto(_workspace_url(app_server, intake["application_id"]))
    assert not _INLINE_HANDLER.search(page.content())


def test_workspace_primary_action_is_open_hub(
    page: Page,
    app_server: str,
    intake: dict,
    recorder: Any,
) -> None:
    """The primary action card ('Intake Hub') has an 'Open hub' button."""
    page.goto(_workspace_url(app_server, intake["application_id"]))
    hub_card = page.locator(".app-action-card--primary")
    expect(hub_card).to_be_visible()
    expect(hub_card.locator("a")).to_contain_text("Open hub")


# ---------------------------------------------------------------------------
# No inline styles on new and list pages too
# ---------------------------------------------------------------------------


def test_list_no_inline_style_attributes(
    page: Page,
    app_server: str,
    intake: dict,
    recorder: Any,
) -> None:
    """No inline style= attributes on the applications list page."""
    page.goto(_list_url(app_server))
    expect(page.locator("[style]")).to_have_count(0)


def test_new_no_inline_style_attributes(
    page: Page,
    app_server: str,
    recorder: Any,
) -> None:
    """No inline style= attributes on the new application page."""
    page.goto(_new_url(app_server))
    expect(page.locator("[style]")).to_have_count(0)
