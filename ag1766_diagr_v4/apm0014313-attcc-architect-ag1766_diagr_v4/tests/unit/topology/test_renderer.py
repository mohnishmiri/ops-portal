"""
Tests for Pure Renderer (P9 Implementation).

These tests verify the pure renderer for topology diagram generation.
"""

import gzip
import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from migration_intake.topology.contracts import canonical_json_bytes
from migration_intake.topology.profiles import load_profile
from migration_intake.topology.renderer import render_structural
from migration_intake.topology.renderer.core import (
    BindingResult,
    RenderContext,
    RenderInput,
    RunMode,
    XmlLimitExceededError,
    XmlParseError,
    XmlParserLimits,
    _apply_format,
    _resolve_path,
    find_markers_in_text,
    parse_diagram_safely,
    render_diagram,
    resolve_marker,
)

# ─────────────────────────────────────────────────────────────────────────────
# Test Fixtures
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class MockToken:
    """Mock token for testing."""

    token_id: str
    projection_path: str
    default_value: str | None = None


class MockProfile:
    """Mock profile for testing."""

    def __init__(self, tokens: dict[str, MockToken]):
        self._tokens = tokens

    def get_token(self, token_id: str) -> MockToken | None:
        return self._tokens.get(token_id)


@pytest.fixture
def simple_diagram_xml() -> bytes:
    """Simple diagram XML for testing."""
    return b"""<?xml version="1.0" encoding="UTF-8"?>
<mxfile>
    <diagram name="Page-1">
        <mxGraphModel>
            <root>
                <mxCell id="0"/>
                <mxCell id="1" parent="0"/>
                <mxCell id="2" value="Application: {{APP_NAME}}" parent="1"/>
                <mxCell id="3" value="Environment: {{ENVIRONMENT}}" parent="1"/>
                <mxCell id="4" value="Static text" parent="1"/>
            </root>
        </mxGraphModel>
    </diagram>
</mxfile>
"""


@pytest.fixture
def mock_profile() -> MockProfile:
    """Mock profile with tokens."""
    return MockProfile(
        {
            "APP_NAME": MockToken("APP_NAME", "$.application.name"),
            "ENVIRONMENT": MockToken("ENVIRONMENT", "$.context.environment"),
            "MISSING": MockToken("MISSING", "$.nonexistent"),
            "WITH_DEFAULT": MockToken(
                "WITH_DEFAULT", "$.nonexistent", default_value="DEFAULT_VALUE"
            ),
        }
    )


@pytest.fixture
def mock_projection() -> dict:
    """Mock projection data."""
    return {
        "application": {
            "name": "Test Application",
            "id": "APP-001",
        },
        "context": {
            "environment": "PROD",
            "site": "us-east-1a",
        },
    }


@pytest.fixture
def render_context() -> RenderContext:
    """Render context for testing."""
    return RenderContext(
        environment="PROD",
        site="us-east-1a",
        variant="CCPM_OUTPOST_V1",
        run_id="run-123",
        run_mode=RunMode.PREVIEW,
        created_by="test-user",
        intake_status="ACTIVE",
        readiness_status="READY",
    )


def compute_hash(data: bytes) -> str:
    """Compute SHA-256 hash."""
    return hashlib.sha256(data).hexdigest()


# ─────────────────────────────────────────────────────────────────────────────
# XML Parsing Tests
# ─────────────────────────────────────────────────────────────────────────────


class TestXmlParsing:
    """Tests for XML parsing with security limits."""

    def test_parse_valid_xml(self, simple_diagram_xml):
        """Parse valid XML."""
        root = parse_diagram_safely(simple_diagram_xml)
        assert root is not None
        assert root.tag == "mxfile"

    def test_parse_file_size_limit(self):
        """File size limit is enforced."""
        limits = XmlParserLimits(max_file_size_bytes=100)
        large_xml = b"<root>" + b"x" * 200 + b"</root>"

        with pytest.raises(XmlLimitExceededError) as exc_info:
            parse_diagram_safely(large_xml, limits)

        assert "size" in str(exc_info.value).lower()

    def test_parse_allows_large_drawio_image_style_within_default_limit(self):
        """Embedded Draw.io image styles can be larger than ordinary attributes."""
        style = b"image=data:image/png;base64," + b"A" * 90_000
        xml = b'<mxfile><mxCell id="1" style="' + style + b'"/></mxfile>'

        root = parse_diagram_safely(xml)

        assert root.find(".//mxCell").get("style") == style.decode()

        with pytest.raises(XmlLimitExceededError, match="Attribute length"):
            parse_diagram_safely(xml, XmlParserLimits(max_attribute_length=10_000))

    def test_parse_rejects_entity_declarations(self):
        """Entity declarations are rejected."""
        xml_with_entity = b"""<?xml version="1.0"?>
<!DOCTYPE root [
    <!ENTITY xxe "test">
]>
<root>&xxe;</root>
"""
        with pytest.raises(XmlLimitExceededError) as exc_info:
            parse_diagram_safely(xml_with_entity)

        assert "entity" in str(exc_info.value).lower()

    def test_parse_rejects_external_dtd(self):
        """External DTD references are rejected."""
        xml_with_external = b"""<?xml version="1.0"?>
<!DOCTYPE root SYSTEM "http://evil.com/xxe.dtd">
<root>test</root>
"""
        with pytest.raises(XmlLimitExceededError) as exc_info:
            parse_diagram_safely(xml_with_external)

        assert "dtd" in str(exc_info.value).lower()

    def test_parse_invalid_xml(self):
        """Invalid XML raises parse error."""
        invalid_xml = b"<root><unclosed>"

        with pytest.raises(XmlParseError):
            parse_diagram_safely(invalid_xml)

    def test_parse_cell_count_limit(self):
        """Cell count limit is enforced."""
        # Create XML with many cells
        cells = "".join(f'<mxCell id="{i}"/>' for i in range(100))
        xml = f"<mxfile>{cells}</mxfile>".encode()

        limits = XmlParserLimits(max_cell_count=50)

        with pytest.raises(XmlLimitExceededError) as exc_info:
            parse_diagram_safely(xml, limits)

        assert "cell" in str(exc_info.value).lower()

    @pytest.mark.parametrize(
        "xml",
        [
            b'<?xml version="1.0"?><!DOCTYPE mxfile [<!ENTITY xxe "test">]><mxfile>&xxe;</mxfile>',
            (
                '<?xml version="1.0" encoding="UTF-16"?>'
                '<!DOCTYPE mxfile [<!ENTITY xxe "test">]><mxfile>&xxe;</mxfile>'
            ).encode("utf-16"),
        ],
    )
    def test_parse_rejects_entities_in_all_supported_encodings(self, xml):
        """DTD/entity screening cannot be bypassed by UTF-16 encoding."""
        with pytest.raises(XmlLimitExceededError, match=r"DTD|Entity"):
            parse_diagram_safely(xml)

    @pytest.mark.parametrize(
        "payload",
        [
            gzip.compress(b"<mxfile/>"),
            b"UEsDBBQAAAAIA",  # ZIP magic encoded as base64-like Draw.io input.
        ],
    )
    def test_parse_rejects_compressed_or_encoded_input(self, payload):
        """The parser accepts XML bytes only, never compressed or encoded containers."""
        with pytest.raises(XmlParseError):
            parse_diagram_safely(payload)

    @pytest.mark.parametrize(
        ("xml", "limits", "message"),
        [
            (b"<root/>", XmlParserLimits(), "root"),
            (
                b'<mxfile><diagram name="one"/><diagram name="two"/></mxfile>',
                XmlParserLimits(max_page_count=1),
                "[Pp]age",
            ),
            (b"<mxfile><node/><node/></mxfile>", XmlParserLimits(max_node_count=2), "[Nn]ode"),
            (b"<mxfile><a><b/></a></mxfile>", XmlParserLimits(max_depth=1), "depth"),
            (
                b'<mxfile><mxCell id="1"/><mxCell id="1"/></mxfile>',
                XmlParserLimits(),
                "[Dd]uplicate",
            ),
            (
                b'<mxfile><node a="1" b="2"/></mxfile>',
                XmlParserLimits(max_attribute_count=1),
                "[Aa]ttribute",
            ),
            (b"<mxfile>text</mxfile>", XmlParserLimits(max_text_length=3), "[Tt]ext"),
        ],
    )
    def test_parse_enforces_drawio_structure_limits(self, xml, limits, message):
        """Boundary validation rejects wrong roots and each bounded structure class."""
        with pytest.raises(XmlLimitExceededError, match=message):
            parse_diagram_safely(xml, limits)

    def test_parse_assigns_ids_to_drawio_placeholder_vertices(self):
        xml = (
            b'<mxfile><diagram name="one"><mxGraphModel><root>'
            b'<mxCell id="0"/><mxCell id="1" parent="0"/>'
            b'<mxCell parent="1" vertex="1"><mxGeometry/></mxCell>'
            b"</root></mxGraphModel></diagram></mxfile>"
        )

        root = parse_diagram_safely(xml)

        placeholder = root.find(".//mxCell[@id='__drawio_placeholder_0']")
        assert placeholder is not None

    def test_parse_rejects_meaningful_idless_cell(self):
        xml = b'<mxfile><mxCell value="meaningful"/></mxfile>'

        with pytest.raises(XmlLimitExceededError, match="missing required id"):
            parse_diagram_safely(xml)


# ─────────────────────────────────────────────────────────────────────────────
# Marker Detection Tests
# ─────────────────────────────────────────────────────────────────────────────


class TestMarkerDetection:
    """Tests for marker detection."""

    def test_find_simple_marker(self):
        """Find simple marker."""
        markers = find_markers_in_text("Hello {{APP_NAME}}")
        assert markers == ["APP_NAME"]

    def test_find_multiple_markers(self):
        """Find multiple markers."""
        markers = find_markers_in_text("{{APP_NAME}} - {{ENVIRONMENT}}")
        assert markers == ["APP_NAME", "ENVIRONMENT"]

    def test_find_marker_with_format(self):
        """Find marker with format spec."""
        markers = find_markers_in_text("{{APP_NAME:upper}}")
        assert markers == ["APP_NAME:upper"]

    def test_no_markers(self):
        """No markers in text."""
        markers = find_markers_in_text("Plain text")
        assert markers == []

    def test_invalid_marker_ignored(self):
        """Invalid marker patterns are ignored."""
        markers = find_markers_in_text("{{invalid}} {{123}} {{_bad}}")
        assert markers == []


# ─────────────────────────────────────────────────────────────────────────────
# Marker Resolution Tests
# ─────────────────────────────────────────────────────────────────────────────


class TestMarkerResolution:
    """Tests for marker resolution."""

    def test_resolve_simple_marker(self, mock_profile, mock_projection):
        """Resolve simple marker."""
        value, error = resolve_marker("APP_NAME", mock_projection, mock_profile)
        assert value == "Test Application"
        assert error is None

    def test_resolve_missing_token(self, mock_profile, mock_projection):
        """Missing token returns error."""
        value, error = resolve_marker("UNKNOWN", mock_projection, mock_profile)
        assert value is None
        assert "not found" in error.lower()

    def test_resolve_missing_value(self, mock_profile, mock_projection):
        """Missing value returns error."""
        value, error = resolve_marker("MISSING", mock_projection, mock_profile)
        assert value is None
        assert "not found" in error.lower()

    def test_resolve_with_default(self, mock_profile, mock_projection):
        """Missing value uses default."""
        value, error = resolve_marker("WITH_DEFAULT", mock_projection, mock_profile)
        assert value == "DEFAULT_VALUE"
        assert error is None


class TestPathResolution:
    """Tests for JSONPath-like resolution."""

    def test_resolve_simple_path(self):
        """Resolve simple path."""
        data = {"name": "Test"}
        value = _resolve_path(data, "$.name")
        assert value == "Test"

    def test_resolve_nested_path(self):
        """Resolve nested path."""
        data = {"app": {"name": "Test"}}
        value = _resolve_path(data, "$.app.name")
        assert value == "Test"

    def test_resolve_missing_path(self):
        """Missing path returns None."""
        data = {"name": "Test"}
        value = _resolve_path(data, "$.missing")
        assert value is None


class TestFormatApplication:
    """Tests for format application."""

    def test_format_upper(self):
        """Apply upper format."""
        assert _apply_format("test", "upper") == "TEST"

    def test_format_lower(self):
        """Apply lower format."""
        assert _apply_format("TEST", "lower") == "test"

    def test_format_title(self):
        """Apply title format."""
        assert _apply_format("test app", "title") == "Test App"

    def test_format_unknown(self):
        """Unknown format returns string."""
        assert _apply_format("test", "unknown") == "test"


# ─────────────────────────────────────────────────────────────────────────────
# Render Tests
# ─────────────────────────────────────────────────────────────────────────────


class TestRenderDiagram:
    """Tests for diagram rendering."""

    def test_render_simple_diagram(
        self, simple_diagram_xml, mock_profile, mock_projection, render_context
    ):
        """Render simple diagram with markers."""
        render_input = RenderInput(
            projection=mock_projection,
            projection_hash=compute_hash(str(mock_projection).encode()),
            base_diagram_bytes=simple_diagram_xml,
            base_diagram_hash=compute_hash(simple_diagram_xml),
            profile=mock_profile,
            profile_hash="profile-hash-123",
            render_context=render_context,
            recorded_timestamp=datetime.now(tz=UTC),
        )

        output = render_diagram(render_input)

        assert output.success
        assert output.error_message is None
        assert output.diagram_bytes
        assert output.diagram_hash
        assert output.manifest.success
        assert output.report_html

    def test_render_resolves_markers(
        self, simple_diagram_xml, mock_profile, mock_projection, render_context
    ):
        """Render resolves markers in diagram."""
        render_input = RenderInput(
            projection=mock_projection,
            projection_hash=compute_hash(str(mock_projection).encode()),
            base_diagram_bytes=simple_diagram_xml,
            base_diagram_hash=compute_hash(simple_diagram_xml),
            profile=mock_profile,
            profile_hash="profile-hash-123",
            render_context=render_context,
            recorded_timestamp=datetime.now(tz=UTC),
        )

        output = render_diagram(render_input)

        # Check markers were resolved
        diagram_str = output.diagram_bytes.decode("utf-8")
        assert "Test Application" in diagram_str
        assert "PROD" in diagram_str
        assert "{{APP_NAME}}" not in diagram_str
        assert "{{ENVIRONMENT}}" not in diagram_str

    def test_render_tracks_mutations(
        self, simple_diagram_xml, mock_profile, mock_projection, render_context
    ):
        """Render tracks mutations."""
        render_input = RenderInput(
            projection=mock_projection,
            projection_hash=compute_hash(str(mock_projection).encode()),
            base_diagram_bytes=simple_diagram_xml,
            base_diagram_hash=compute_hash(simple_diagram_xml),
            profile=mock_profile,
            profile_hash="profile-hash-123",
            render_context=render_context,
            recorded_timestamp=datetime.now(tz=UTC),
        )

        output = render_diagram(render_input)

        assert output.diagnostics.mutation_count >= 2
        assert len(output.diagnostics.mutations) >= 2

    def test_render_generates_manifest(
        self, simple_diagram_xml, mock_profile, mock_projection, render_context
    ):
        """Render generates manifest."""
        render_input = RenderInput(
            projection=mock_projection,
            projection_hash="proj-hash",
            base_diagram_bytes=simple_diagram_xml,
            base_diagram_hash="base-hash",
            profile=mock_profile,
            profile_hash="profile-hash",
            render_context=render_context,
            recorded_timestamp=datetime.now(tz=UTC),
        )

        output = render_diagram(render_input)

        assert output.manifest.projection_hash == "proj-hash"
        assert output.manifest.base_diagram_hash == "base-hash"
        assert output.manifest.profile_hash == "profile-hash"
        assert output.manifest.environment == "PROD"
        assert output.manifest.run_mode == "PREVIEW"

    def test_render_generates_report(
        self, simple_diagram_xml, mock_profile, mock_projection, render_context
    ):
        """Render generates HTML report."""
        render_input = RenderInput(
            projection=mock_projection,
            projection_hash="proj-hash",
            base_diagram_bytes=simple_diagram_xml,
            base_diagram_hash="base-hash",
            profile=mock_profile,
            profile_hash="profile-hash",
            render_context=render_context,
            recorded_timestamp=datetime.now(tz=UTC),
        )

        output = render_diagram(render_input)

        assert output.report_html
        assert "<!DOCTYPE html>" in output.report_html
        assert "run-123" in output.report_html
        assert "PROD" in output.report_html

    def test_render_invalid_xml_fails(self, mock_profile, mock_projection, render_context):
        """Render with invalid XML fails gracefully."""
        render_input = RenderInput(
            projection=mock_projection,
            projection_hash="proj-hash",
            base_diagram_bytes=b"<invalid><unclosed>",
            base_diagram_hash="base-hash",
            profile=mock_profile,
            profile_hash="profile-hash",
            render_context=render_context,
            recorded_timestamp=datetime.now(tz=UTC),
        )

        output = render_diagram(render_input)

        assert not output.success
        assert output.error_message is not None

    def test_structural_render_uses_packaged_profile(
        self, simple_diagram_xml, mock_projection, render_context
    ):
        profile = load_profile("SYNTHETIC_STRUCTURAL")
        structural_diagram_xml = simple_diagram_xml.replace(
            b"{{APP_NAME}}", b"{{APPLICATION_NAME}}"
        ).replace(b'name="Page-1"', b'name="Overview"')
        render_input = RenderInput(
            projection=mock_projection,
            projection_hash=compute_hash(canonical_json_bytes(mock_projection)),
            base_diagram_bytes=structural_diagram_xml,
            base_diagram_hash=compute_hash(structural_diagram_xml),
            profile=profile,
            profile_hash=profile.profile_hash,
            render_context=render_context,
            recorded_timestamp=datetime.now(tz=UTC),
        )

        output = render_structural(
            render_input,
            SimpleNamespace(
                is_compatible=True,
                base_hash=compute_hash(structural_diagram_xml),
                profile_hash=profile.profile_hash,
                slot_matches=(
                    SimpleNamespace(
                        slot_id="APPLICATION_NAME",
                        page_name="Overview",
                        cell_ids=("2",),
                    ),
                ),
            ),
        )

        assert output.success
        diagram = parse_diagram_safely(output.diagram_bytes)
        generated_cells = diagram.findall(".//mxCell[@id='structural-application-label']")
        assert len(generated_cells) == 1
        generated = generated_cells[0]
        assert generated.attrib == {
            "id": "structural-application-label",
            "value": "Test Application",
            "vertex": "1",
            "parent": "1",
        }
        assert generated.find("mxGeometry").attrib == {
            "x": "240",
            "y": "120",
            "width": "180",
            "height": "30",
            "as": "geometry",
        }
        assert {
            cell.get("id")
            for cell in diagram.iter("mxCell")
            if cell.get("id", "").startswith("structural-")
        } == {"structural-application-label"}

        repeated = render_structural(
            render_input,
            SimpleNamespace(
                is_compatible=True,
                base_hash=compute_hash(structural_diagram_xml),
                profile_hash=profile.profile_hash,
                slot_matches=(
                    SimpleNamespace(
                        slot_id="APPLICATION_NAME",
                        page_name="Overview",
                        cell_ids=("2",),
                    ),
                ),
            ),
        )

        assert repeated.success
        assert repeated.diagram_bytes == output.diagram_bytes
        assert repeated.manifest_hash == output.manifest_hash

        collision_diagram_xml = structural_diagram_xml.replace(
            b"</root>",
            b'<mxCell id="structural-application-label" parent="1"/></root>',
        )
        collision_input = RenderInput(
            projection=mock_projection,
            projection_hash=compute_hash(canonical_json_bytes(mock_projection)),
            base_diagram_bytes=collision_diagram_xml,
            base_diagram_hash=compute_hash(collision_diagram_xml),
            profile=profile,
            profile_hash=profile.profile_hash,
            render_context=render_context,
            recorded_timestamp=datetime.now(tz=UTC),
        )
        collision = render_structural(
            collision_input,
            SimpleNamespace(
                is_compatible=True,
                base_hash=compute_hash(collision_diagram_xml),
                profile_hash=profile.profile_hash,
                slot_matches=(
                    SimpleNamespace(
                        slot_id="APPLICATION_NAME",
                        page_name="Overview",
                        cell_ids=("2",),
                    ),
                ),
            ),
        )

        assert not collision.success
        assert "already exists" in (collision.error_message or "")


# ─────────────────────────────────────────────────────────────────────────────
# Determinism Tests
# ─────────────────────────────────────────────────────────────────────────────


class TestRenderDeterminism:
    """Tests for render determinism."""

    def test_same_input_same_output(
        self, simple_diagram_xml, mock_profile, mock_projection, render_context
    ):
        """Same input produces same output."""
        timestamp = datetime(2026, 9, 18, 12, 0, 0, tzinfo=UTC)

        render_input = RenderInput(
            projection=mock_projection,
            projection_hash="proj-hash",
            base_diagram_bytes=simple_diagram_xml,
            base_diagram_hash="base-hash",
            profile=mock_profile,
            profile_hash="profile-hash",
            render_context=render_context,
            recorded_timestamp=timestamp,
        )

        output1 = render_diagram(render_input)
        output2 = render_diagram(render_input)

        assert output1.diagram_hash == output2.diagram_hash
        assert output1.manifest_hash == output2.manifest_hash

    def test_different_projection_different_output(
        self, simple_diagram_xml, mock_profile, render_context
    ):
        """Different projection produces different output."""
        timestamp = datetime(2026, 9, 18, 12, 0, 0, tzinfo=UTC)

        projection1 = {"application": {"name": "App One"}, "context": {"environment": "DEV"}}
        projection2 = {"application": {"name": "App Two"}, "context": {"environment": "PROD"}}

        input1 = RenderInput(
            projection=projection1,
            projection_hash="hash1",
            base_diagram_bytes=simple_diagram_xml,
            base_diagram_hash="base-hash",
            profile=mock_profile,
            profile_hash="profile-hash",
            render_context=render_context,
            recorded_timestamp=timestamp,
        )

        input2 = RenderInput(
            projection=projection2,
            projection_hash="hash2",
            base_diagram_bytes=simple_diagram_xml,
            base_diagram_hash="base-hash",
            profile=mock_profile,
            profile_hash="profile-hash",
            render_context=render_context,
            recorded_timestamp=timestamp,
        )

        output1 = render_diagram(input1)
        output2 = render_diagram(input2)

        assert output1.diagram_hash != output2.diagram_hash


# ─────────────────────────────────────────────────────────────────────────────
# Data Class Tests
# ─────────────────────────────────────────────────────────────────────────────


class TestDataClasses:
    """Tests for data classes."""

    def test_binding_result_enum(self):
        """BindingResult enum values."""
        assert BindingResult.MATCHED.value == "MATCHED"
        assert BindingResult.UNMATCHED.value == "UNMATCHED"
        assert BindingResult.UNRESOLVED.value == "UNRESOLVED"

    def test_run_mode_enum(self):
        """RunMode enum values."""
        assert RunMode.OFFICIAL.value == "OFFICIAL"
        assert RunMode.PREVIEW.value == "PREVIEW"
        assert RunMode.DRAFT_PREVIEW.value == "DRAFT_PREVIEW"

    def test_render_context_frozen(self, render_context):
        """RenderContext is immutable."""
        with pytest.raises(AttributeError):
            render_context.environment = "DEV"

    def test_xml_parser_limits_defaults(self):
        """XmlParserLimits has sensible defaults."""
        limits = XmlParserLimits()
        assert limits.max_file_size_bytes == 50 * 1024 * 1024
        assert limits.max_cell_count == 10_000
        assert limits.max_entity_expansions == 0
        assert limits.resolve_external_entities is False
