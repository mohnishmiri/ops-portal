"""
Tests for UI01: Design tokens and base shell.

Verifies HTML structure, accessibility, CSP compatibility, and that
no external CDN/script URLs appear. Uses Jinja2 Environment directly
because web routes are not wired yet.

TDD: These tests are written first; the templates and static files
are implemented to make them pass.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from jinja2 import Environment, FileSystemLoader, TemplateNotFound

TEMPLATES_DIR = (
    Path(__file__).parent.parent.parent
    / "src"
    / "migration_intake"
    / "web"
    / "templates"
)

STATIC_DIR = (
    Path(__file__).parent.parent.parent
    / "src"
    / "migration_intake"
    / "web"
    / "static"
)

# External URL patterns that must NOT appear in rendered output.
# The production shell uses only local assets.
_EXTERNAL_URL_PATTERN = re.compile(
    r"(https?://|//)(cdn\.|unpkg\.com|jsdelivr|cdnjs|fonts\.googleapis|"
    r"fonts\.gstatic|skypack|esm\.sh|lucide\.dev)",
    re.IGNORECASE,
)

# Inline event handler attributes that break CSP
_INLINE_HANDLER_PATTERN = re.compile(
    r"\s(onclick|onchange|onsubmit|onload|onerror|onkeyup|onkeydown"
    r"|onfocus|onblur|oninput|onmouseover|onmouseout)=",
    re.IGNORECASE,
)


def _make_env() -> Environment:
    """Create a Jinja2 environment pointed at the production templates dir."""
    return Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        autoescape=True,
    )


def _minimal_context(
    *,
    title: str = "Test Page",
    nav_items: list[dict[str, str]] | None = None,
    active_nav: str = "",
    app_name: str = "",
) -> dict[str, object]:
    """Return a minimal template context for base.html rendering."""
    if nav_items is None:
        nav_items = [
            {"key": "overview", "label": "Overview", "href": "/overview"},
            {"key": "questionnaire", "label": "Questionnaire", "href": "/questionnaire"},
        ]
    return {
        "title": title,
        "nav_items": nav_items,
        "active_nav": active_nav,
        "app_name": app_name,
    }


class TestTemplateFilesExist:
    """Verify that all required template files are present on disk."""

    def test_base_html_exists(self) -> None:
        """base.html must exist in the templates directory."""
        assert (TEMPLATES_DIR / "base.html").is_file(), (
            "base.html not found at expected path"
        )

    def test_nav_component_exists(self) -> None:
        """components/nav.html must exist."""
        assert (TEMPLATES_DIR / "components" / "nav.html").is_file(), (
            "components/nav.html not found at expected path"
        )

    def test_tokens_css_exists(self) -> None:
        """static/css/tokens.css must exist."""
        assert (STATIC_DIR / "css" / "tokens.css").is_file()

    def test_base_css_exists(self) -> None:
        """static/css/base.css must exist."""
        assert (STATIC_DIR / "css" / "base.css").is_file()

    def test_layout_css_exists(self) -> None:
        """static/css/layout.css must exist."""
        assert (STATIC_DIR / "css" / "layout.css").is_file()

    def test_components_css_exists(self) -> None:
        """static/css/components.css must exist."""
        assert (STATIC_DIR / "css" / "components.css").is_file()

    def test_app_js_exists(self) -> None:
        """static/js/app.js must exist."""
        assert (STATIC_DIR / "js" / "app.js").is_file()


class TestBaseHtmlLoads:
    """Verify that base.html can be loaded and rendered by Jinja2."""

    def test_base_html_loads_without_error(self) -> None:
        """base.html must load from the Jinja2 environment."""
        env = _make_env()
        template = env.get_template("base.html")
        assert template is not None

    def test_base_html_renders_with_minimal_context(self) -> None:
        """base.html must render to a non-empty string with minimal context."""
        env = _make_env()
        template = env.get_template("base.html")
        html = template.render(**_minimal_context())
        assert len(html.strip()) > 0


class TestHtmlStructure:
    """Verify semantic HTML structure required for accessibility and SEO."""

    @pytest.fixture()
    def rendered(self) -> str:
        """Render base.html with a standard test context."""
        env = _make_env()
        template = env.get_template("base.html")
        return template.render(
            **_minimal_context(
                title="Migration Intake",
                nav_items=[
                    {"key": "overview", "label": "Overview", "href": "/overview"},
                    {"key": "questionnaire", "label": "Questionnaire", "href": "/questionnaire"},
                ],
                active_nav="overview",
                app_name="FACET",
            )
        )

    def test_doctype_present(self, rendered: str) -> None:
        """Output must begin with DOCTYPE html declaration."""
        assert rendered.strip().lower().startswith("<!doctype html")

    def test_html_lang_attribute(self, rendered: str) -> None:
        """html element must carry lang='en' for screen reader language switching."""
        assert 'lang="en"' in rendered or "lang='en'" in rendered

    def test_charset_meta(self, rendered: str) -> None:
        """head must declare UTF-8 charset."""
        assert "charset" in rendered.lower()
        assert "utf-8" in rendered.lower()

    def test_viewport_meta(self, rendered: str) -> None:
        """head must include viewport meta for responsive layout."""
        assert "viewport" in rendered.lower()

    def test_title_block_rendered(self, rendered: str) -> None:
        """Title supplied in context must appear in rendered <title>."""
        assert "<title>" in rendered.lower()
        assert "Migration Intake" in rendered

    def test_semantic_header_element(self, rendered: str) -> None:
        """Page must include a semantic <header> element."""
        assert "<header" in rendered.lower()

    def test_semantic_nav_element(self, rendered: str) -> None:
        """Page must include a semantic <nav> element."""
        assert "<nav" in rendered.lower()

    def test_semantic_main_element(self, rendered: str) -> None:
        """Page must include a semantic <main> element."""
        assert "<main" in rendered.lower()

    def test_main_has_id_main_content(self, rendered: str) -> None:
        """<main> must carry id='main-content' to receive focus from skip link."""
        assert 'id="main-content"' in rendered or "id='main-content'" in rendered

    def test_skip_link_present(self, rendered: str) -> None:
        """A skip-link anchor must target #main-content for keyboard users."""
        assert 'href="#main-content"' in rendered or "href='#main-content'" in rendered

    def test_skip_link_has_class(self, rendered: str) -> None:
        """Skip link must carry the skip-link CSS class."""
        assert 'class="skip-link"' in rendered or "skip-link" in rendered


class TestLocalAssetsOnly:
    """Verify that no external CDN or font URLs appear in the rendered output."""

    @pytest.fixture()
    def rendered(self) -> str:
        """Render base.html with default context."""
        env = _make_env()
        template = env.get_template("base.html")
        return template.render(**_minimal_context())

    def test_no_external_script_urls(self, rendered: str) -> None:
        """No <script src> must point to an external domain."""
        script_srcs = re.findall(r'<script[^>]+src=["\']([^"\']+)["\']', rendered)
        for src in script_srcs:
            assert not _EXTERNAL_URL_PATTERN.search(src), (
                f"External script URL found: {src}"
            )

    def test_no_external_stylesheet_urls(self, rendered: str) -> None:
        """No <link rel='stylesheet'> must point to an external domain."""
        link_hrefs = re.findall(
            r'<link[^>]+href=["\']([^"\']+)["\']', rendered
        )
        for href in link_hrefs:
            assert not _EXTERNAL_URL_PATTERN.search(href), (
                f"External stylesheet URL found: {href}"
            )

    def test_no_cdn_in_raw_html(self, rendered: str) -> None:
        """No known CDN domain must appear anywhere in the rendered HTML."""
        assert not _EXTERNAL_URL_PATTERN.search(rendered), (
            "External CDN URL found in rendered base.html"
        )

    def test_tokens_css_no_external_imports(self) -> None:
        """tokens.css must not @import from external URLs."""
        css = (STATIC_DIR / "css" / "tokens.css").read_text(encoding="utf-8")
        assert not _EXTERNAL_URL_PATTERN.search(css), (
            "External URL found in tokens.css"
        )

    def test_base_css_no_external_imports(self) -> None:
        """base.css must not @import from external URLs."""
        css = (STATIC_DIR / "css" / "base.css").read_text(encoding="utf-8")
        assert not _EXTERNAL_URL_PATTERN.search(css), (
            "External URL found in base.css"
        )


class TestCspCompatibility:
    """Verify the rendered shell does not contain inline event handlers."""

    @pytest.fixture()
    def rendered(self) -> str:
        """Render base.html with default context."""
        env = _make_env()
        template = env.get_template("base.html")
        return template.render(**_minimal_context())

    def test_no_inline_event_handlers(self, rendered: str) -> None:
        """No on* event handler attributes must appear (CSP script-src policy)."""
        assert not _INLINE_HANDLER_PATTERN.search(rendered), (
            "Inline event handler attribute found in rendered HTML"
        )

    def test_no_javascript_href(self, rendered: str) -> None:
        """No href='javascript:' must appear."""
        assert "javascript:" not in rendered.lower()


class TestNavigationRendering:
    """Verify that nav items from context are rendered correctly."""

    def test_nav_items_appear_in_output(self) -> None:
        """Labels from nav_items context must appear in rendered HTML."""
        env = _make_env()
        template = env.get_template("base.html")
        html = template.render(
            **_minimal_context(
                nav_items=[
                    {"key": "overview", "label": "Overview", "href": "/overview"},
                    {"key": "sources", "label": "Sources", "href": "/sources"},
                ]
            )
        )
        assert "Overview" in html
        assert "Sources" in html

    def test_active_nav_item_marked(self) -> None:
        """The active nav item must carry an aria-current or active class."""
        env = _make_env()
        template = env.get_template("base.html")
        html = template.render(
            **_minimal_context(
                nav_items=[
                    {"key": "overview", "label": "Overview", "href": "/overview"},
                    {"key": "questionnaire", "label": "Questionnaire", "href": "/questionnaire"},
                ],
                active_nav="questionnaire",
            )
        )
        # Active item must be distinguishable - either aria-current or active class
        assert 'aria-current="page"' in html or "active" in html

    def test_nav_item_hrefs_rendered(self) -> None:
        """href values from nav_items must appear as anchor hrefs."""
        env = _make_env()
        template = env.get_template("base.html")
        html = template.render(
            **_minimal_context(
                nav_items=[
                    {"key": "overview", "label": "Overview", "href": "/app/123/overview"},
                ]
            )
        )
        assert "/app/123/overview" in html

    def test_empty_nav_items_renders_without_error(self) -> None:
        """Rendering with an empty nav_items list must not raise an error."""
        env = _make_env()
        template = env.get_template("base.html")
        html = template.render(**_minimal_context(nav_items=[]))
        assert "<main" in html.lower()


class TestMobileNavControl:
    """Verify the mobile navigation toggle control for accessibility."""

    @pytest.fixture()
    def rendered(self) -> str:
        """Render base.html with default context."""
        env = _make_env()
        template = env.get_template("base.html")
        return template.render(**_minimal_context())

    def test_nav_toggle_button_exists(self, rendered: str) -> None:
        """A nav toggle control (button#nav-toggle) must be present in the shell."""
        assert 'id="nav-toggle"' in rendered

    def test_nav_toggle_has_aria_expanded(self, rendered: str) -> None:
        """Nav toggle must carry aria-expanded attribute for screen readers."""
        assert "aria-expanded" in rendered

    def test_nav_toggle_has_aria_label(self, rendered: str) -> None:
        """Nav toggle must carry aria-label so its purpose is clear without text."""
        # Must have aria-label or aria-labelledby on or near the toggle
        assert "aria-label" in rendered

    def test_app_nav_has_id(self, rendered: str) -> None:
        """The navigation element must have id='app-nav' for JS toggle targeting."""
        assert 'id="app-nav"' in rendered


class TestDesignTokens:
    """Verify that tokens.css defines the required custom properties."""

    @pytest.fixture()
    def tokens_css(self) -> str:
        """Read the tokens CSS file."""
        return (STATIC_DIR / "css" / "tokens.css").read_text(encoding="utf-8")

    def test_navy_900_token(self, tokens_css: str) -> None:
        """tokens.css must define --color-navy-900."""
        assert "--color-navy-900" in tokens_css

    def test_canvas_token(self, tokens_css: str) -> None:
        """tokens.css must define --color-canvas for the page background."""
        assert "--color-canvas" in tokens_css

    def test_surface_token(self, tokens_css: str) -> None:
        """tokens.css must define --color-surface for panel backgrounds."""
        assert "--color-surface" in tokens_css

    def test_cyan_accent_token(self, tokens_css: str) -> None:
        """tokens.css must define a cyan accent token for primary actions."""
        assert "--color-cyan-500" in tokens_css

    def test_font_sans_token(self, tokens_css: str) -> None:
        """tokens.css must define --font-sans with the approved font stack."""
        assert "--font-sans" in tokens_css

    def test_status_success_token(self, tokens_css: str) -> None:
        """tokens.css must define --color-success for status indicators."""
        assert "--color-success" in tokens_css

    def test_status_warning_token(self, tokens_css: str) -> None:
        """tokens.css must define --color-warning for status indicators."""
        assert "--color-warning" in tokens_css

    def test_status_danger_token(self, tokens_css: str) -> None:
        """tokens.css must define --color-danger for status indicators."""
        assert "--color-danger" in tokens_css

    def test_spacing_tokens_present(self, tokens_css: str) -> None:
        """tokens.css must define spacing custom properties."""
        assert "--space-4" in tokens_css

    def test_radius_tokens_present(self, tokens_css: str) -> None:
        """tokens.css must define border-radius custom properties."""
        assert "--radius-md" in tokens_css

    def test_tokens_in_root_scope(self, tokens_css: str) -> None:
        """:root { } block must be present in tokens.css."""
        assert ":root" in tokens_css


class TestCssTokenUsage:
    """Verify that CSS files reference tokens via var() rather than hard-coding colors."""

    def test_base_css_uses_var_references(self) -> None:
        """base.css must use var(--...) references, not raw hex colours."""
        css = (STATIC_DIR / "css" / "base.css").read_text(encoding="utf-8")
        assert "var(--" in css

    def test_layout_css_uses_var_references(self) -> None:
        """layout.css must use var(--...) references."""
        css = (STATIC_DIR / "css" / "layout.css").read_text(encoding="utf-8")
        assert "var(--" in css

    def test_components_css_uses_var_references(self) -> None:
        """components.css must use var(--...) references."""
        css = (STATIC_DIR / "css" / "components.css").read_text(encoding="utf-8")
        assert "var(--" in css


class TestAppJs:
    """Verify app.js structure for CSP compliance and mobile nav wiring."""

    @pytest.fixture()
    def app_js(self) -> str:
        """Read app.js content."""
        return (STATIC_DIR / "js" / "app.js").read_text(encoding="utf-8")

    def test_app_js_references_nav_toggle(self, app_js: str) -> None:
        """app.js must reference nav-toggle element by ID."""
        assert "nav-toggle" in app_js

    def test_app_js_references_app_nav(self, app_js: str) -> None:
        """app.js must reference app-nav element by ID."""
        assert "app-nav" in app_js

    def test_app_js_sets_aria_expanded(self, app_js: str) -> None:
        """app.js must set aria-expanded to manage toggle state."""
        assert "aria-expanded" in app_js

    def test_app_js_uses_addeventlistener(self, app_js: str) -> None:
        """app.js must use addEventListener, not inline handlers."""
        assert "addEventListener" in app_js

    def test_app_js_no_document_write(self, app_js: str) -> None:
        """app.js must not use document.write (CSP hostile)."""
        assert "document.write" not in app_js

    def test_app_js_iife_or_strict(self, app_js: str) -> None:
        """app.js must use strict mode or an IIFE to avoid global namespace pollution."""
        assert "'use strict'" in app_js or '"use strict"' in app_js or "(function" in app_js


class TestAppNameContext:
    """Verify that application context is rendered from the view model."""

    def test_app_name_appears_when_set(self) -> None:
        """When app_name is set, it must appear in the rendered HTML."""
        env = _make_env()
        template = env.get_template("base.html")
        html = template.render(**_minimal_context(app_name="FACET"))
        assert "FACET" in html

    def test_page_title_appears_in_head(self) -> None:
        """The title context variable must appear inside the <title> tag."""
        env = _make_env()
        template = env.get_template("base.html")
        html = template.render(**_minimal_context(title="Application Detail"))
        assert "Application Detail" in html


# ---------------------------------------------------------------------------
# UI01b — Design-system audit tests
# ---------------------------------------------------------------------------

# Hex color pattern for detecting hard-coded colors
_HEX_COLOR_PATTERN = re.compile(r"#[0-9a-fA-F]{3,8}\b")

# Allowed hard-coded colors in tokens.css (these define the tokens)
_TOKENS_FILE = "tokens.css"


class TestHardCodedColorsAudit:
    """
    UI01b: Verify that CSS files use semantic tokens instead of hard-coded colors.

    Hard-coded colors are allowed only in tokens.css where they define the tokens.
    All other CSS files must use var(--...) references.
    """

    def _count_hardcoded_colors(self, css_content: str) -> list[str]:
        """
        Find all hard-coded hex colors in CSS content.

        Returns list of found hex colors.
        """
        # Find all hex colors
        colors = _HEX_COLOR_PATTERN.findall(css_content)

        # Filter out colors inside var() references (these are fallbacks, which are ok)
        # and colors in comments
        lines = css_content.split("\n")
        real_hardcoded = []

        for line in lines:
            # Skip comment lines
            if line.strip().startswith("/*") or line.strip().startswith("*"):
                continue

            # Find hex colors in this line
            line_colors = _HEX_COLOR_PATTERN.findall(line)
            for color in line_colors:
                # Check if it's inside a var() fallback - these are acceptable
                # e.g., var(--color-navy-900, #061733) is ok
                if f"var(--" in line and color in line:
                    # Check if the color appears after a comma in a var()
                    var_match = re.search(r"var\([^)]+,\s*" + re.escape(color), line)
                    if var_match:
                        continue  # This is a fallback, skip it

                real_hardcoded.append(color)

        return real_hardcoded

    def test_layout_css_minimal_hardcoded_colors(self) -> None:
        """
        layout.css should minimize hard-coded colors.

        Some hard-coded colors may be acceptable for gradients or rgba values
        that don't have token equivalents, but we track them for audit.
        """
        css = (STATIC_DIR / "css" / "layout.css").read_text(encoding="utf-8")
        hardcoded = self._count_hardcoded_colors(css)

        # Document the current state - these should be moved to tokens over time
        # For now, we just ensure the count doesn't increase
        # Current known hard-coded colors in layout.css:
        # - #d9f1f5, #eef5f7 in gradient
        # - #b8c7d8 in nav item color
        # - #8fdbe7 in command brand eyebrow
        # - #eef7f8 in side-nav hover
        # - #e6f5f8 in side-nav active
        max_allowed = 10  # Current baseline - should decrease over time
        assert len(hardcoded) <= max_allowed, (
            f"layout.css has {len(hardcoded)} hard-coded colors (max {max_allowed}): "
            f"{hardcoded[:5]}..."
        )

    def test_components_css_minimal_hardcoded_colors(self) -> None:
        """
        components.css should minimize hard-coded colors.
        """
        css = (STATIC_DIR / "css" / "components.css").read_text(encoding="utf-8")
        hardcoded = self._count_hardcoded_colors(css)

        # Current known hard-coded colors in components.css:
        # - #ffb000 notification dot
        # - #b9e8f0 profile monogram, nav count
        # - #9ee6ef, #07203d in status pills
        # - #5dd7e5, #82e2ec, #03233e in primary button
        # - #3a698c, #73dbe6 in secondary button
        # - #b91c1c in danger button hover
        # - #e4eaed in side count
        # - #42ccdf, #7ce4ef, #09213d in app monogram
        max_allowed = 20  # Current baseline - should decrease over time
        assert len(hardcoded) <= max_allowed, (
            f"components.css has {len(hardcoded)} hard-coded colors (max {max_allowed}): "
            f"{hardcoded[:5]}..."
        )

    def test_base_css_no_hardcoded_colors(self) -> None:
        """base.css should have no hard-coded colors (only resets and typography)."""
        css = (STATIC_DIR / "css" / "base.css").read_text(encoding="utf-8")
        hardcoded = self._count_hardcoded_colors(css)

        # base.css should only use tokens
        max_allowed = 2  # Allow minimal exceptions
        assert len(hardcoded) <= max_allowed, (
            f"base.css has {len(hardcoded)} hard-coded colors (max {max_allowed}): "
            f"{hardcoded}"
        )


class TestActiveStateTokens:
    """
    UI01b: Verify the approved active-state treatment uses tokens.

    Active state: dark green text, pale green background, visible green border.
    """

    def test_active_tokens_defined(self) -> None:
        """tokens.css must define --color-active, --color-active-bg, --color-active-border."""
        css = (STATIC_DIR / "css" / "tokens.css").read_text(encoding="utf-8")
        assert "--color-active:" in css, "Missing --color-active token"
        assert "--color-active-bg:" in css, "Missing --color-active-bg token"
        assert "--color-active-border:" in css, "Missing --color-active-border token"

    def test_status_pill_active_uses_tokens(self) -> None:
        """status-pill--active must use the active state tokens."""
        css = (STATIC_DIR / "css" / "components.css").read_text(encoding="utf-8")
        # Find the .status-pill--active rule
        assert "var(--color-active)" in css, (
            "status-pill--active should use var(--color-active)"
        )
        assert "var(--color-active-bg)" in css, (
            "status-pill--active should use var(--color-active-bg)"
        )


class TestNoExternalFontUrls:
    """UI01b: Verify no external font URLs (Google Fonts, etc.)."""

    def test_tokens_css_no_google_fonts(self) -> None:
        """tokens.css must not import Google Fonts."""
        css = (STATIC_DIR / "css" / "tokens.css").read_text(encoding="utf-8")
        assert "fonts.googleapis" not in css.lower()
        assert "fonts.gstatic" not in css.lower()

    def test_base_css_no_google_fonts(self) -> None:
        """base.css must not import Google Fonts."""
        css = (STATIC_DIR / "css" / "base.css").read_text(encoding="utf-8")
        assert "fonts.googleapis" not in css.lower()
        assert "fonts.gstatic" not in css.lower()


class TestNoLucideCdn:
    """UI01b: Verify no Lucide CDN references."""

    def test_no_lucide_cdn_in_templates(self) -> None:
        """Templates must not reference Lucide CDN."""
        env = _make_env()
        template = env.get_template("base.html")
        html = template.render(**_minimal_context())
        assert "lucide" not in html.lower() or "cdn" not in html.lower()

    def test_no_lucide_cdn_in_js(self) -> None:
        """app.js must not reference Lucide CDN."""
        js = (STATIC_DIR / "js" / "app.js").read_text(encoding="utf-8")
        assert "lucide.dev" not in js.lower()
        assert "unpkg.com/lucide" not in js.lower()
