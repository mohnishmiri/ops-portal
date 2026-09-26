"""
Page invariants asserted on every navigation in the browser suite.

These catch regressions nobody wrote an assertion for: a template that raises,
a stylesheet that 404s, a console error from a broken script, or a layout that
overflows on a narrow viewport. They are deliberately cheap so every journey
can afford them.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from playwright.sync_api import Page

#: Narrow viewport used for the overflow check (iPhone SE class).
NARROW_WIDTH = 375


@dataclass
class PageRecorder:
    """Collects console errors and failed responses for one page."""

    console_errors: list[str] = field(default_factory=list)
    failed_requests: list[str] = field(default_factory=list)
    server_errors: list[str] = field(default_factory=list)

    def attach(self, page: Page, base_url: str) -> None:
        def on_console(message) -> None:  # noqa: ANN001 - playwright type
            if message.type == "error":
                self.console_errors.append(f"{message.text} @ {page.url}")

        def on_response(response) -> None:  # noqa: ANN001 - playwright type
            status = response.status
            url = response.url
            if status >= 500:
                self.server_errors.append(f"{status} {url}")
            elif status >= 400 and url.startswith(base_url):
                # 4xx on a first-party asset means a broken reference; 4xx on a
                # form post is often a deliberate negative assertion, so only
                # asset-like requests are treated as failures here.
                if any(url.endswith(ext) for ext in (".css", ".js", ".ico", ".svg", ".woff2")):
                    self.failed_requests.append(f"{status} {url}")

        page.on("console", on_console)
        page.on("response", on_response)

    def assert_clean(self) -> None:
        assert not self.server_errors, f"server errors: {self.server_errors}"
        assert not self.console_errors, f"console errors: {self.console_errors}"
        assert not self.failed_requests, f"failed first-party assets: {self.failed_requests}"


def assert_no_horizontal_overflow(page: Page) -> None:
    """
    Assert the document does not scroll horizontally at a narrow width.

    Restores the previous viewport so a journey can continue afterwards.
    """
    original = page.viewport_size or {"width": 1280, "height": 720}
    page.set_viewport_size({"width": NARROW_WIDTH, "height": original["height"]})
    overflow = page.evaluate(
        "() => document.documentElement.scrollWidth - document.documentElement.clientWidth"
    )
    page.set_viewport_size(original)
    assert overflow <= 1, (
        f"page overflows horizontally by {overflow}px at {NARROW_WIDTH}px wide: {page.url}"
    )
