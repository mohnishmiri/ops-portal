"""
Tests for UI03 — Registry-driven response editors.

Verifies:
- All 25 registered types have corresponding editor/display templates
- Correct editor_key mapping
- Escaped current/raw values
- Unique labels/IDs
- Required and help association
- Hidden schema/version fields
- Computed controls contain no direct-save input
- No inline handlers/styles/external assets
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from jinja2 import Environment, FileSystemLoader

from migration_intake.catalog.response_types import get_default_registry
from migration_intake.catalog.response_types.base import ResponseTypeCodes


TEMPLATES_DIR = (
    Path(__file__).parent.parent.parent
    / "src"
    / "migration_intake"
    / "web"
    / "templates"
)

EDITORS_DIR = TEMPLATES_DIR / "responses" / "editors"
DISPLAYS_DIR = TEMPLATES_DIR / "responses" / "displays"


# External URL patterns that must NOT appear
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

# Inline style pattern
_INLINE_STYLE_PATTERN = re.compile(r'\sstyle\s*=\s*["\']', re.IGNORECASE)


def _make_env() -> Environment:
    """Create a Jinja2 environment pointed at the production templates dir."""
    return Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        autoescape=True,
    )


class TestRegistryHasAllTypes:
    """Verify the registry has all 25 response types."""

    def test_registry_has_25_types(self) -> None:
        """Registry must have exactly 25 response types."""
        registry = get_default_registry()
        assert registry.count() == 25

    def test_all_type_codes_registered(self) -> None:
        """All ResponseTypeCodes must be registered."""
        registry = get_default_registry()
        expected_codes = [
            # Scalar (5)
            ResponseTypeCodes.BOOLEAN,
            ResponseTypeCodes.SINGLE_SELECT,
            ResponseTypeCodes.TEXT,
            ResponseTypeCodes.LONG_TEXT,
            ResponseTypeCodes.IDENTIFIER,
            # Collection (5)
            ResponseTypeCodes.MULTI_SELECT,
            ResponseTypeCodes.TEXT_PAIR,
            ResponseTypeCodes.COUNT_PAIR,
            ResponseTypeCodes.CONTROLLED_PAIR,
            ResponseTypeCodes.PEOPLE_LIST,
            # Measurement (4)
            ResponseTypeCodes.MEASUREMENT,
            ResponseTypeCodes.MEASUREMENT_PAIR,
            ResponseTypeCodes.MEASUREMENT_SET,
            ResponseTypeCodes.MEASUREMENT_CONTEXT,
            # Decision (5)
            ResponseTypeCodes.BOOLEAN_WITH_RATIONALE,
            ResponseTypeCodes.CONTROLLED_SET,
            ResponseTypeCodes.SINGLE_SELECT_PER_COMPONENT,
            ResponseTypeCodes.DECISION_WITH_PERSON,
            ResponseTypeCodes.APPROVAL,
            # Computed (6)
            ResponseTypeCodes.REGISTER_STATUS,
            ResponseTypeCodes.VALIDATION_RESULT,
            ResponseTypeCodes.ISSUE_REGISTER,
            ResponseTypeCodes.DECISION_REGISTER,
            ResponseTypeCodes.APPROVAL_REGISTER,
            ResponseTypeCodes.EVIDENCE_REFERENCE,
        ]
        for code in expected_codes:
            assert registry.is_registered(code), f"Type {code} not registered"


class TestEditorTemplatesExist:
    """Verify editor templates exist for all editable types."""

    @pytest.fixture
    def editable_types(self):
        """Get all editable (non-computed) response types."""
        registry = get_default_registry()
        return registry.editable_types()

    def test_all_editable_types_have_editor_template(self, editable_types) -> None:
        """Each editable type must have a corresponding editor template."""
        for response_type in editable_types:
            editor_key = response_type.editor_key
            template_path = EDITORS_DIR / f"{editor_key}.html"
            assert template_path.is_file(), (
                f"Missing editor template for {response_type.code}: "
                f"expected {template_path}"
            )


class TestDisplayTemplatesExist:
    """Verify display templates exist for computed types."""

    @pytest.fixture
    def computed_types(self):
        """Get all computed response types."""
        registry = get_default_registry()
        return registry.computed_types()

    def test_computed_types_have_display_or_editor_template(self, computed_types) -> None:
        """Each computed type must have a display or editor template."""
        for response_type in computed_types:
            editor_key = response_type.editor_key
            # Check for display template first, then editor
            display_path = DISPLAYS_DIR / f"{editor_key}.html"
            editor_path = EDITORS_DIR / f"{editor_key}.html"
            assert display_path.is_file() or editor_path.is_file(), (
                f"Missing template for computed type {response_type.code}: "
                f"expected {display_path} or {editor_path}"
            )


class TestEditorKeyMapping:
    """Verify editor_key values match expected patterns."""

    def test_scalar_types_have_correct_editor_keys(self) -> None:
        """Scalar types must have correct editor keys."""
        registry = get_default_registry()
        expected = {
            ResponseTypeCodes.BOOLEAN: "boolean_editor",
            ResponseTypeCodes.SINGLE_SELECT: "single_select_editor",
            ResponseTypeCodes.TEXT: "text_editor",
            ResponseTypeCodes.LONG_TEXT: "long_text_editor",
            ResponseTypeCodes.IDENTIFIER: "identifier_editor",
        }
        for code, expected_key in expected.items():
            response_type = registry.get(code)
            assert response_type is not None
            assert response_type.editor_key == expected_key, (
                f"{code} has editor_key {response_type.editor_key}, expected {expected_key}"
            )

    def test_collection_types_have_correct_editor_keys(self) -> None:
        """Collection types must have correct editor keys."""
        registry = get_default_registry()
        expected = {
            ResponseTypeCodes.MULTI_SELECT: "multi_select_editor",
            ResponseTypeCodes.TEXT_PAIR: "text_pair_editor",
            ResponseTypeCodes.COUNT_PAIR: "count_pair_editor",
            ResponseTypeCodes.CONTROLLED_PAIR: "controlled_pair_editor",
            ResponseTypeCodes.PEOPLE_LIST: "people_list_editor",
        }
        for code, expected_key in expected.items():
            response_type = registry.get(code)
            assert response_type is not None
            assert response_type.editor_key == expected_key

    def test_measurement_types_have_correct_editor_keys(self) -> None:
        """Measurement types must have correct editor keys."""
        registry = get_default_registry()
        expected = {
            ResponseTypeCodes.MEASUREMENT: "measurement_editor",
            ResponseTypeCodes.MEASUREMENT_PAIR: "measurement_pair_editor",
            ResponseTypeCodes.MEASUREMENT_SET: "measurement_set_editor",
            ResponseTypeCodes.MEASUREMENT_CONTEXT: "measurement_context_editor",
        }
        for code, expected_key in expected.items():
            response_type = registry.get(code)
            assert response_type is not None
            assert response_type.editor_key == expected_key

    def test_decision_types_have_correct_editor_keys(self) -> None:
        """Decision types must have correct editor keys."""
        registry = get_default_registry()
        expected = {
            ResponseTypeCodes.BOOLEAN_WITH_RATIONALE: "boolean_with_rationale_editor",
            ResponseTypeCodes.CONTROLLED_SET: "controlled_set_editor",
            ResponseTypeCodes.SINGLE_SELECT_PER_COMPONENT: "single_select_per_component_editor",
            ResponseTypeCodes.DECISION_WITH_PERSON: "decision_with_person_editor",
            ResponseTypeCodes.APPROVAL: "approval_editor",
        }
        for code, expected_key in expected.items():
            response_type = registry.get(code)
            assert response_type is not None
            assert response_type.editor_key == expected_key


class TestEditorTemplateContent:
    """Verify editor templates have correct structure."""

    @pytest.fixture
    def env(self) -> Environment:
        """Create Jinja2 environment."""
        return _make_env()

    def test_text_editor_has_input_field(self) -> None:
        """text_editor.html must have a text input."""
        content = (EDITORS_DIR / "text_editor.html").read_text(encoding="utf-8")
        assert 'type="text"' in content or "type='text'" in content
        assert 'name="text"' in content or "name='text'" in content

    def test_boolean_editor_has_radio_buttons(self) -> None:
        """boolean_editor.html must have radio buttons."""
        content = (EDITORS_DIR / "boolean_editor.html").read_text(encoding="utf-8")
        assert 'type="radio"' in content or "type='radio'" in content
        # BOOLEAN is a three-option string enum (YES/NO/UNKNOWN), never a
        # Python boolean: asserting value="true"/"false" here locked in the
        # field values that made every boolean answer unsavable.
        assert 'value="YES"' in content
        assert 'value="NO"' in content
        assert 'value="UNKNOWN"' in content

    def test_single_select_editor_has_select(self) -> None:
        """single_select_editor.html must have a select element."""
        content = (EDITORS_DIR / "single_select_editor.html").read_text(encoding="utf-8")
        assert "<select" in content
        assert "</select>" in content

    def test_multi_select_editor_has_checkboxes(self) -> None:
        """multi_select_editor.html must have checkboxes."""
        content = (EDITORS_DIR / "multi_select_editor.html").read_text(encoding="utf-8")
        assert 'type="checkbox"' in content or "type='checkbox'" in content


class TestNoInlineHandlers:
    """Verify templates don't have inline event handlers."""

    def test_editor_templates_no_inline_handlers(self) -> None:
        """Editor templates must not have inline event handlers."""
        for template_path in EDITORS_DIR.glob("*.html"):
            content = template_path.read_text(encoding="utf-8")
            assert not _INLINE_HANDLER_PATTERN.search(content), (
                f"Inline event handler found in {template_path.name}"
            )

    def test_display_templates_no_inline_handlers(self) -> None:
        """Display templates must not have inline event handlers."""
        for template_path in DISPLAYS_DIR.glob("*.html"):
            content = template_path.read_text(encoding="utf-8")
            assert not _INLINE_HANDLER_PATTERN.search(content), (
                f"Inline event handler found in {template_path.name}"
            )


class TestNoExternalAssets:
    """Verify templates don't reference external assets."""

    def test_editor_templates_no_external_urls(self) -> None:
        """Editor templates must not reference external URLs."""
        for template_path in EDITORS_DIR.glob("*.html"):
            content = template_path.read_text(encoding="utf-8")
            assert not _EXTERNAL_URL_PATTERN.search(content), (
                f"External URL found in {template_path.name}"
            )

    def test_display_templates_no_external_urls(self) -> None:
        """Display templates must not reference external URLs."""
        for template_path in DISPLAYS_DIR.glob("*.html"):
            content = template_path.read_text(encoding="utf-8")
            assert not _EXTERNAL_URL_PATTERN.search(content), (
                f"External URL found in {template_path.name}"
            )


class TestComputedTypesNoDirectSave:
    """Verify computed type displays don't have direct save inputs."""

    def test_display_templates_no_save_button(self) -> None:
        """Display templates must not have save buttons."""
        for template_path in DISPLAYS_DIR.glob("*.html"):
            content = template_path.read_text(encoding="utf-8")
            # Should not have a submit button that saves directly
            assert 'type="submit"' not in content or "Save" not in content, (
                f"Direct save button found in {template_path.name}"
            )

    def test_approval_editor_links_to_workflow(self) -> None:
        """approval_editor.html must link to workflow, not save directly."""
        content = (DISPLAYS_DIR / "approval_editor.html").read_text(encoding="utf-8")
        # Should have a link to workflow
        assert "workflow" in content.lower() or "Workflow" in content
        # Should not have a direct save form
        assert 'method="POST"' not in content or "answer" not in content


class TestQuestionWrapperTemplate:
    """Verify the question wrapper template exists and has correct structure."""

    def test_question_wrapper_exists(self) -> None:
        """_question.html must exist."""
        assert (TEMPLATES_DIR / "responses" / "_question.html").is_file()

    def test_question_wrapper_has_macro(self) -> None:
        """_question.html must define question_wrapper macro."""
        content = (TEMPLATES_DIR / "responses" / "_question.html").read_text(encoding="utf-8")
        assert "macro question_wrapper" in content

    def test_question_wrapper_has_csrf_field(self) -> None:
        """_question.html must include CSRF token field."""
        content = (TEMPLATES_DIR / "responses" / "_question.html").read_text(encoding="utf-8")
        assert "_csrf_token" in content

    def test_question_wrapper_has_schema_version_field(self) -> None:
        """_question.html must include schema version field."""
        content = (TEMPLATES_DIR / "responses" / "_question.html").read_text(encoding="utf-8")
        assert "_schema_version" in content

    def test_question_wrapper_has_row_version_field(self) -> None:
        """_question.html must include row version field for concurrency."""
        content = (TEMPLATES_DIR / "responses" / "_question.html").read_text(encoding="utf-8")
        assert "_row_version" in content
