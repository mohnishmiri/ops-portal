"""Browser behavior for applications design-option previews."""

from __future__ import annotations

import pytest
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.browser


@pytest.mark.parametrize("option", ["a", "b", "c"])
def test_application_design_option_renders_without_overflow(
    page: Page,
    app_server: str,
    option: str,
) -> None:
    page.set_viewport_size({"width": 1280, "height": 720})
    response = page.goto(f"{app_server}/applications/design-options/{option}")

    assert response is not None and response.ok
    expect(page.get_by_role("heading", level=1)).to_have_count(1)
    overflow = page.evaluate(
        "document.documentElement.scrollWidth > document.documentElement.clientWidth"
    )
    assert overflow is False


def test_option_switch_preserves_applications_preview_page(page: Page, app_server: str) -> None:
    page.goto(f"{app_server}/applications/design-options/a")
    page.get_by_role("button", name="Loading", exact=True).click()
    expect(page.get_by_role("button", name="Loading", exact=True)).to_have_attribute(
        "aria-pressed", "true"
    )


def test_list_search_menu_dialog_and_states(page: Page, app_server: str) -> None:
    page.goto(f"{app_server}/applications/design-options/b")
    page.get_by_role("searchbox", name="Search applications").fill("EXPRESS")
    cards = page.locator(".preview-card")
    if cards.count() > 0:
        cards.nth(0).locator("[data-preview-menu-button]").click()
        expect(page.get_by_role("menu")).to_be_visible()

    page.get_by_role("button", name="New application").click()
    expect(page.get_by_role("dialog", name="Register application")).to_be_visible()

    page.get_by_role("button", name="Close dialog").click()
    for state in ("Loading", "Empty", "Error", "Populated"):
        page.get_by_role("button", name=state, exact=True).click()
        expect(page.get_by_role("button", name=state, exact=True)).to_have_attribute(
            "aria-pressed", "true"
        )


def test_preview_dialog_validation(page: Page, app_server: str) -> None:
    page.goto(f"{app_server}/applications/design-options/c")
    page.get_by_role("button", name="New application").click()
    dialog = page.get_by_role("dialog", name="Register application")
    expect(dialog).to_be_visible()
    dialog.get_by_role("button", name="Save preview").click()
    expect(dialog.get_by_label("Application name")).to_be_focused()
