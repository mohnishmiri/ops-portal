"""
Pure Renderer Core — P9 Implementation.

Implements the pure renderer for topology diagram generation based on
the P9 design document.

Design rules:
- Pure: No database, environment, or wall-clock access
- Deterministic: Same inputs = identical outputs (byte-for-byte)
- Auditable: Every mutation is tracked and reported
- Safe: XML parsing under strict security limits (D-13)
"""

from __future__ import annotations

import codecs
import hashlib
import html
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime  # noqa: TC003
from enum import Enum
from typing import Any
from xml.etree import ElementTree as ET

# ─────────────────────────────────────────────────────────────────────────────
# Exceptions
# ─────────────────────────────────────────────────────────────────────────────


class RenderError(Exception):
    """Base class for renderer errors."""

    pass


class XmlLimitExceededError(RenderError):
    """XML parsing limit exceeded."""

    pass


class XmlParseError(RenderError):
    """XML parsing failed."""

    pass


class ProfileMismatchError(RenderError):
    """Profile does not match diagram."""

    pass


class RenderInputIntegrityError(RenderError):
    """A governed render input does not match its recorded pin."""

    pass


# ─────────────────────────────────────────────────────────────────────────────
# Enums
# ─────────────────────────────────────────────────────────────────────────────


class BindingResult(str, Enum):  # noqa: UP042
    """Result of attempting to bind a slot."""

    MATCHED = "MATCHED"  # Slot found and value bound
    UNMATCHED = "UNMATCHED"  # Slot not found in diagram
    UNRESOLVED = "UNRESOLVED"  # Slot found but value not available
    SKIPPED = "SKIPPED"  # Slot skipped per policy
    ERROR = "ERROR"  # Binding failed with error


class RunMode(str, Enum):  # noqa: UP042
    """Render run mode."""

    OFFICIAL = "OFFICIAL"
    PREVIEW = "PREVIEW"
    DRAFT_PREVIEW = "DRAFT_PREVIEW"


# ─────────────────────────────────────────────────────────────────────────────
# Data Classes - Security Limits
# ─────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class XmlParserLimits:
    """
    Security limits for XML parsing (D-13 approved values).

    Note: D-13 security review is pending. These are provisional defaults
    that will be updated when D-13 is recorded.
    """

    # File size limits
    max_file_size_bytes: int = 50 * 1024 * 1024  # 50 MB

    # Structure limits
    max_page_count: int = 100
    max_node_count: int = 50_000
    max_cell_count: int = 10_000
    max_depth: int = 100

    # Content limits
    max_attribute_count: int = 100
    max_attribute_length: int = 100_000
    max_text_length: int = 100_000

    # Entity limits (disabled for security)
    max_entity_expansions: int = 0
    resolve_external_entities: bool = False


# Default limits (D-13 pending)
DEFAULT_XML_LIMITS = XmlParserLimits()


# ─────────────────────────────────────────────────────────────────────────────
# Data Classes - Input/Output
# ─────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class RenderContext:
    """Context for rendering (recorded, not computed)."""

    # Target scope
    environment: str  # "DEV" | "TEST" | "STAGING" | "PROD"
    site: str | None  # Site identifier
    variant: str  # Profile variant

    # Run identification
    run_id: str
    run_mode: RunMode

    # Creator
    created_by: str

    # Status (from P0A policy)
    intake_status: str
    readiness_status: str


@dataclass(frozen=True)
class RenderInput:
    """Immutable input to the pure renderer."""

    # Projection data (from P3/P4)
    projection: dict[str, Any]
    projection_hash: str

    # Base diagram (approved template)
    base_diagram_bytes: bytes
    base_diagram_hash: str

    # Profile (from P6)
    profile: Any  # Profile from P6
    profile_hash: str

    # Render context (recorded at capture time)
    render_context: RenderContext

    # Recorded timestamp (no wall-clock access)
    recorded_timestamp: datetime


@dataclass
class SlotBindingResult:
    """Result of binding a single slot."""

    slot_id: str
    slot_type: str  # MANDATORY | CONDITIONAL | OPTIONAL | REPEATING
    result: BindingResult

    # Cell information
    page_name: str | None = None
    cell_id: str | None = None

    # Value information
    token: str | None = None
    old_value: str | None = None
    new_value: str | None = None

    # Error information
    error_message: str | None = None


@dataclass
class SuspiciousMarker:
    """Unrecognized marker that may indicate a problem."""

    pattern: str
    location: str  # page:cell
    severity: str  # WARN | INFO
    description: str


@dataclass
class MutationRecord:
    """Record of a single mutation."""

    mutation_id: int
    page_name: str
    cell_id: str
    mutation_type: str  # "TEXT_REPLACE" | "ATTRIBUTE_SET" | "CELL_ADD" | "CELL_REMOVE"
    old_value: str | None
    new_value: str | None
    slot_id: str | None
    token: str | None


@dataclass
class BindingDiagnostics:
    """Diagnostics for slot binding."""

    # Slot counts
    slots_total: int = 0
    slots_matched: int = 0
    slots_unmatched: int = 0
    slots_unresolved: int = 0
    slots_skipped: int = 0
    slots_error: int = 0

    # Detailed results
    slot_results: list[SlotBindingResult] = field(default_factory=list)

    # Marker diagnostics
    markers_before: int = 0
    markers_after: int = 0
    markers_resolved: int = 0
    markers_unresolved: int = 0

    # Suspicious markers (unrecognized patterns)
    suspicious_markers: list[SuspiciousMarker] = field(default_factory=list)


@dataclass
class RenderDiagnostics:
    """Complete diagnostics for a render operation."""

    # Binding diagnostics
    binding: BindingDiagnostics = field(default_factory=BindingDiagnostics)

    # Mutation tracking
    mutations: list[MutationRecord] = field(default_factory=list)
    mutation_count: int = 0
    attempted_writes: int = 0
    changed_cells: int = 0

    # Timing (recorded, not measured)
    parse_duration_ms: int = 0
    bind_duration_ms: int = 0
    serialize_duration_ms: int = 0
    total_duration_ms: int = 0

    # Warnings and errors
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


@dataclass
class RenderManifest:
    """Machine-readable manifest of render operation."""

    # Version
    manifest_version: str = "1.0.0"

    # Input hashes
    projection_hash: str = ""
    base_diagram_hash: str = ""
    profile_hash: str = ""

    # Output hashes
    diagram_hash: str = ""
    report_hash: str = ""

    # Context
    environment: str = ""
    site: str | None = None
    variant: str = ""
    run_id: str = ""
    run_mode: str = ""

    # Status
    success: bool = False
    result_status: str = "FAILED"
    mutation_count: int = 0
    slots_matched: int = 0
    slots_total: int = 0

    # Timestamps
    recorded_timestamp: str = ""
    render_timestamp: str = ""


@dataclass
class RenderOutput:
    """Output from the pure renderer."""

    # Generated diagram
    diagram_bytes: bytes = b""
    diagram_hash: str = ""

    # Manifest (machine-readable)
    manifest: RenderManifest = field(default_factory=RenderManifest)
    manifest_hash: str = ""

    # Report (human-readable HTML)
    report_html: str = ""
    report_hash: str = ""

    # Diagnostics
    diagnostics: RenderDiagnostics = field(default_factory=RenderDiagnostics)

    # Overall status
    success: bool = False
    result_status: str = "FAILED"
    error_message: str | None = None


# ─────────────────────────────────────────────────────────────────────────────
# XML Parsing
# ─────────────────────────────────────────────────────────────────────────────


def create_safe_parser() -> ET.XMLParser:
    """
    Create a hardened XML parser.

    Note: Standard library ElementTree is used with manual validation.
    For production, consider using defusedxml when available.
    """
    # Standard library parser - we add manual validation
    return ET.XMLParser()  # noqa: S314


def _count_elements(element: ET.Element) -> int:
    """Count total elements in tree."""
    count = 1
    for child in element:
        count += _count_elements(child)
    return count


def _max_depth(element: ET.Element, current: int = 0) -> int:
    """Find maximum depth of tree."""
    if len(element) == 0:
        return current
    return max(_max_depth(child, current + 1) for child in element)


def _is_drawio_placeholder_cell(element: ET.Element) -> bool:
    """Recognize empty geometry-only vertices emitted by some Draw.io templates."""
    return (
        element.tag == "mxCell"
        and not element.get("id")
        and element.get("vertex") == "1"
        and not element.get("edge")
        and not element.get("value")
        and any(child.tag == "mxGeometry" for child in element)
    )


def _assign_placeholder_cell_ids(root: ET.Element) -> None:
    """Give known Draw.io placeholders deterministic IDs before strict validation."""
    cells = list(root.iter("mxCell"))
    cell_ids = {cell.get("id") for cell in cells if cell.get("id")}
    next_index = 0
    for cell in cells:
        if not _is_drawio_placeholder_cell(cell):
            continue
        while f"__drawio_placeholder_{next_index}" in cell_ids:
            next_index += 1
        cell.set("id", f"__drawio_placeholder_{next_index}")
        cell_ids.add(cell.get("id"))
        next_index += 1


def _validate_structure_limits(root: ET.Element, limits: XmlParserLimits) -> None:
    """Validate XML structure against limits."""
    if root.tag != "mxfile":
        raise XmlLimitExceededError("Diagram root must be mxfile")
    pages = [element for element in root if element.tag == "diagram"]
    if len(pages) > limits.max_page_count:
        raise XmlLimitExceededError(
            f"Page count {len(pages)} exceeds limit {limits.max_page_count}"
        )
    node_count = sum(1 for _ in root.iter())
    if node_count > limits.max_node_count:
        raise XmlLimitExceededError(
            f"Node count {node_count} exceeds limit {limits.max_node_count}"
        )

    # Count cells (mxCell elements)
    cells = root.findall(".//{http://www.w3.org/1999/xhtml}mxCell")
    if not cells:
        cells = root.findall(".//mxCell")
    if len(cells) > limits.max_cell_count:
        raise XmlLimitExceededError(
            f"Cell count {len(cells)} exceeds limit {limits.max_cell_count}"
        )

    _assign_placeholder_cell_ids(root)

    cell_ids: set[str] = set()
    stack: list[tuple[ET.Element, int]] = [(root, 0)]
    while stack:
        elem, depth = stack.pop()
        if depth > limits.max_depth:
            raise XmlLimitExceededError(f"Tree depth {depth} exceeds limit {limits.max_depth}")
        if len(elem.attrib) > limits.max_attribute_count:
            raise XmlLimitExceededError(
                f"Attribute count {len(elem.attrib)} exceeds limit {limits.max_attribute_count}"
            )
        for value in elem.attrib.values():
            if len(value) > limits.max_attribute_length:
                raise XmlLimitExceededError(
                    f"Attribute length {len(value)} exceeds limit {limits.max_attribute_length}"
                )
        if elem.text and len(elem.text) > limits.max_text_length:
            raise XmlLimitExceededError(
                f"Text length {len(elem.text)} exceeds limit {limits.max_text_length}"
            )
        if elem.tail and len(elem.tail) > limits.max_text_length:
            raise XmlLimitExceededError(
                f"Tail length {len(elem.tail)} exceeds limit {limits.max_text_length}"
            )
        if elem.tag == "mxCell":
            cell_id = elem.get("id")
            if not cell_id:
                raise XmlLimitExceededError("mxCell is missing required id")
            if cell_id in cell_ids:
                raise XmlLimitExceededError(f"Duplicate mxCell id: {cell_id}")
            cell_ids.add(cell_id)
        stack.extend((child, depth + 1) for child in elem)


def _decode_xml_for_security_scan(diagram_bytes: bytes) -> str:
    """Decode XML only for declaration screening, preserving XML's encoding rules."""
    if diagram_bytes.startswith((b"PK\x03\x04", b"\x1f\x8b")):
        raise XmlParseError("Compressed or archive diagram input is not allowed")
    if diagram_bytes.startswith(codecs.BOM_UTF16_LE) or diagram_bytes.startswith(
        codecs.BOM_UTF16_BE
    ):
        encoding = "utf-16"
    elif diagram_bytes.startswith(codecs.BOM_UTF8):
        encoding = "utf-8-sig"
    else:
        encoding = "utf-8"
    try:
        return diagram_bytes.decode(encoding)
    except UnicodeDecodeError as error:
        raise XmlParseError(f"Diagram XML must use UTF-8 or UTF-16: {error}") from error


def parse_diagram_safely(
    diagram_bytes: bytes,
    limits: XmlParserLimits | None = None,
) -> ET.Element:
    """
    Parse diagram XML with security limits.

    Args:
        diagram_bytes: Raw XML bytes
        limits: Security limits (defaults to D-13 values)

    Returns:
        Parsed XML root element

    Raises:
        XmlLimitExceededError: Limit exceeded
        XmlParseError: Parse failed
    """
    if limits is None:
        limits = DEFAULT_XML_LIMITS

    # Check file size
    if len(diagram_bytes) > limits.max_file_size_bytes:
        raise XmlLimitExceededError(
            f"File size {len(diagram_bytes)} exceeds limit {limits.max_file_size_bytes}"
        )

    content_str = _decode_xml_for_security_scan(diagram_bytes)
    if "<!DOCTYPE" in content_str.upper() or "<!ENTITY" in content_str.upper():
        raise XmlLimitExceededError("DTD and entity declarations are not allowed")

    # Parse
    try:
        parser = create_safe_parser()
        root = ET.fromstring(diagram_bytes, parser=parser)  # noqa: S314
    except ET.ParseError as e:
        raise XmlParseError(f"XML parse error: {e}") from e

    # Validate structure limits
    _validate_structure_limits(root, limits)

    return root


# ─────────────────────────────────────────────────────────────────────────────
# Marker Detection and Resolution
# ─────────────────────────────────────────────────────────────────────────────


# Marker pattern: {{TOKEN_NAME}} or {{TOKEN_NAME:format}}
MARKER_PATTERN = re.compile(r"\{\{([A-Z_][A-Z0-9_]*(?::[a-z_]+)?)\}\}")


def find_markers_in_text(text: str) -> list[str]:
    """Find all markers in text."""
    return MARKER_PATTERN.findall(text)


def resolve_marker(
    marker: str,
    projection: dict[str, Any],
    profile: Any,
) -> tuple[str | None, str | None]:
    """
    Resolve a marker to its value.

    Returns:
        (resolved_value, error_message)
    """
    # Parse marker
    parts = marker.split(":")
    token_id = parts[0]
    format_spec = parts[1] if len(parts) > 1 else None

    # Get token from profile
    token = profile.get_token(token_id) if hasattr(profile, "get_token") else None
    if token is None:
        return None, f"Token {token_id} not found in profile"

    # Resolve from projection
    # Simple JSONPath-like resolution
    path = token.projection_path if hasattr(token, "projection_path") else f"$.{token_id.lower()}"
    value = _resolve_path(projection, path)

    if value is None:
        # Check for default
        default = token.default_value if hasattr(token, "default_value") else None
        if default is not None:
            value = default
        else:
            return None, f"Value not found for token {token_id}"

    # Apply format if specified
    if format_spec:
        value = _apply_format(value, format_spec)

    return str(value), None


def _resolve_path(data: dict[str, Any], path: str) -> Any:
    """Resolve a simple JSONPath-like path."""
    if not path.startswith("$."):
        return None

    parts = path[2:].split(".")
    current = data

    for part in parts:
        if isinstance(current, dict) and part in current:
            current = current[part]
        else:
            return None

    return current


def _apply_format(value: Any, format_spec: str) -> str:
    """Apply format specification to value."""
    if format_spec == "upper":
        return str(value).upper()
    elif format_spec == "lower":
        return str(value).lower()
    elif format_spec == "title":
        return str(value).title()
    else:
        return str(value)


# ─────────────────────────────────────────────────────────────────────────────
# Core Renderer
# ─────────────────────────────────────────────────────────────────────────────


def _compute_hash(data: bytes) -> str:
    """Compute SHA-256 hash."""
    return hashlib.sha256(data).hexdigest()


def _governed_projection_data(projection: Any, expected_hash: str) -> dict[str, Any]:
    """Adapt a strict projection to token data without changing its identity."""
    if isinstance(projection, Mapping):
        from migration_intake.topology.contracts import canonical_json_bytes

        actual_hash = _compute_hash(canonical_json_bytes(projection))
        if actual_hash != expected_hash:
            raise RenderInputIntegrityError(
                f"Projection hash mismatch: expected {expected_hash}, got {actual_hash}"
            )
        partitions = projection.get("partitions")
        if partitions is None:
            return dict(projection)
        if not isinstance(partitions, list):
            raise RenderInputIntegrityError("Persisted projection partitions must be a list")
        data: dict[str, Any] = {}
        for partition in partitions:
            if not isinstance(partition, Mapping) or not isinstance(partition.get("facts"), list):
                raise RenderInputIntegrityError("Persisted projection partition is malformed")
            for fact in partition["facts"]:
                if not isinstance(fact, Mapping):
                    raise RenderInputIntegrityError("Persisted projection fact is malformed")
                output_key = fact.get("output_key")
                if not isinstance(output_key, str) or not output_key:
                    raise RenderInputIntegrityError("Persisted projection fact has no output key")
                current = data
                parts = output_key.split(".")
                for part in parts[:-1]:
                    next_value = current.setdefault(part, {})
                    if not isinstance(next_value, dict):
                        raise RenderInputIntegrityError(
                            f"Projection output path collision at {output_key}"
                        )
                    current = next_value
                existing = current.get(parts[-1])
                value = fact.get("value")
                if existing is not None and existing != value:
                    raise RenderInputIntegrityError(
                        f"Projection partitions disagree at {output_key}"
                    )
                current[parts[-1]] = value
        return data

    projection_hash = getattr(projection, "projection_hash", None)
    partitions = getattr(projection, "partitions", None)
    if projection_hash is None or partitions is None or projection_hash != expected_hash:
        raise RenderInputIntegrityError("Typed projection identity does not match supplied hash")

    typed_data: dict[str, Any] = {}
    for partition in partitions:
        for fact in partition.facts:
            typed_current: dict[str, Any] = typed_data
            parts = fact.output_key.split(".")
            for part in parts[:-1]:
                next_value = typed_current.setdefault(part, {})
                if not isinstance(next_value, dict):
                    raise RenderInputIntegrityError(
                        f"Projection output path collision at {fact.output_key}"
                    )
                typed_current = next_value
            typed_current[parts[-1]] = fact.value
    return typed_data


def _failed_render_output(
    render_input: RenderInput,
    error: str,
    diagnostics: RenderDiagnostics | None = None,
) -> RenderOutput:
    diagnostics = diagnostics or RenderDiagnostics()
    diagnostics.errors.append(error)
    output = RenderOutput(diagnostics=diagnostics, error_message=error, result_status="FAILED")
    output.report_html = _generate_report_html(render_input, diagnostics, success=False)
    output.report_hash = _compute_hash(output.report_html.encode("utf-8"))
    return output


def render_label_only(
    render_input: RenderInput,
    compatibility_result: Any,
    xml_limits: XmlParserLimits | None = None,
) -> RenderOutput:
    """Render only C5.2-approved label slots from immutable governed inputs."""
    try:
        if not compatibility_result.is_compatible:
            raise ProfileMismatchError("Base/profile compatibility is not approved")
        actual_base_hash = _compute_hash(render_input.base_diagram_bytes)
        if actual_base_hash != render_input.base_diagram_hash:
            raise RenderInputIntegrityError(
                "Base diagram hash mismatch: "
                f"expected {render_input.base_diagram_hash}, got {actual_base_hash}"
            )
        if actual_base_hash != compatibility_result.base_hash:
            raise RenderInputIntegrityError("Base diagram hash differs from compatibility result")
        if render_input.profile_hash != compatibility_result.profile_hash:
            raise RenderInputIntegrityError("Profile hash differs from compatibility result")
        if render_input.profile_hash != render_input.profile.profile_hash:
            raise RenderInputIntegrityError("Profile hash does not match loaded profile")
        projection = _governed_projection_data(
            render_input.projection, render_input.projection_hash
        )
        root = parse_diagram_safely(render_input.base_diagram_bytes, xml_limits)
        cells = {
            (page.get("name", ""), cell.get("id", "")): cell
            for page in root.findall("./diagram")
            for cell in page.iter("mxCell")
        }
        slot_by_id = {slot.slot_id: slot for slot in render_input.profile.slots}
        governed_markers = {marker.pattern for marker in render_input.profile.markers}
        diagnostics = RenderDiagnostics()
        diagnostics.binding.slots_total = len(render_input.profile.slots)

        for slot_match in compatibility_result.slot_matches:
            slot = slot_by_id.get(slot_match.slot_id)
            if slot is None:
                raise ProfileMismatchError(
                    f"Compatibility references unknown slot {slot_match.slot_id}"
                )
            slot_matched = True
            slot_unresolved = False
            for cell_id in slot_match.cell_ids:
                cell = cells.get((slot_match.page_name, cell_id))
                if cell is None:
                    raise RenderInputIntegrityError(
                        f"Compatibility cell {slot_match.page_name}:{cell_id} is absent"
                    )
                old_value = cell.get("value", "")
                new_value = old_value
                markers = find_markers_in_text(old_value)
                diagnostics.binding.markers_before += len(markers)
                for marker in markers:
                    token_id = marker.split(":", 1)[0]
                    if token_id not in slot.tokens:
                        continue
                    full_marker = "{{" + marker + "}}"
                    if full_marker not in governed_markers:
                        raise ProfileMismatchError(f"Marker {full_marker} is not governed")
                    diagnostics.attempted_writes += 1
                    resolved, error = resolve_marker(marker, projection, render_input.profile)
                    if resolved is None:
                        slot_unresolved = True
                        diagnostics.binding.markers_unresolved += 1
                        diagnostics.binding.suspicious_markers.append(
                            SuspiciousMarker(
                                full_marker,
                                f"{slot_match.page_name}:{cell_id}",
                                "ERROR",
                                error or "Unresolved marker",
                            )
                        )
                        continue
                    new_value = new_value.replace(full_marker, resolved, 1)
                    diagnostics.binding.markers_resolved += 1
                    diagnostics.mutations.append(
                        MutationRecord(
                            mutation_id=len(diagnostics.mutations),
                            page_name=slot_match.page_name,
                            cell_id=cell_id,
                            mutation_type="TEXT_REPLACE",
                            old_value=full_marker,
                            new_value=resolved,
                            slot_id=slot.slot_id,
                            token=token_id,
                        )
                    )
                diagnostics.binding.markers_after += len(find_markers_in_text(new_value))
                if new_value != old_value:
                    cell.set("value", new_value)
                    diagnostics.changed_cells += 1
            if slot_unresolved:
                diagnostics.binding.slots_unresolved += 1
                diagnostics.binding.slot_results.append(
                    SlotBindingResult(
                        slot.slot_id,
                        slot.slot_type.value,
                        BindingResult.UNRESOLVED,
                        page_name=slot_match.page_name,
                    )
                )
            else:
                diagnostics.binding.slots_matched += 1
                diagnostics.binding.slot_results.append(
                    SlotBindingResult(
                        slot.slot_id,
                        slot.slot_type.value,
                        BindingResult.MATCHED,
                        page_name=slot_match.page_name,
                    )
                )

        if diagnostics.binding.slots_unresolved:
            raise RenderError("Mandatory governed slot values could not be resolved")
        diagram_bytes = ET.tostring(root, encoding="unicode").encode("utf-8")
        report_html = _generate_report_html(render_input, diagnostics, success=True)
        report_hash = _compute_hash(report_html.encode("utf-8"))
        manifest = RenderManifest(
            projection_hash=render_input.projection_hash,
            base_diagram_hash=render_input.base_diagram_hash,
            profile_hash=render_input.profile_hash,
            diagram_hash=_compute_hash(diagram_bytes),
            report_hash=report_hash,
            environment=render_input.render_context.environment,
            site=render_input.render_context.site,
            variant=render_input.render_context.variant,
            run_id=render_input.render_context.run_id,
            run_mode=render_input.render_context.run_mode.value,
            success=True,
            result_status="READY_FOR_REVIEW",
            mutation_count=diagnostics.changed_cells,
            slots_matched=diagnostics.binding.slots_matched,
            slots_total=diagnostics.binding.slots_total,
            recorded_timestamp=render_input.recorded_timestamp.isoformat(),
            render_timestamp=render_input.recorded_timestamp.isoformat(),
        )
        import json

        manifest_hash = _compute_hash(json.dumps(manifest.__dict__, sort_keys=True).encode("utf-8"))
        diagnostics.mutation_count = len(diagnostics.mutations)
        return RenderOutput(
            diagram_bytes=diagram_bytes,
            diagram_hash=manifest.diagram_hash,
            manifest=manifest,
            manifest_hash=manifest_hash,
            report_html=report_html,
            report_hash=report_hash,
            diagnostics=diagnostics,
            success=True,
            result_status="READY_FOR_REVIEW",
        )
    except (RenderError, XmlLimitExceededError, XmlParseError) as error:
        return _failed_render_output(render_input, str(error), locals().get("diagnostics"))


def _generated_cell_id(prefix: str, kind: str, semantic_identity: str) -> str:
    digest = hashlib.sha256(semantic_identity.encode("utf-8")).hexdigest()[:16]
    return f"{prefix}{kind}-{digest}"


def render_structural(
    render_input: RenderInput,
    compatibility_result: Any,
    xml_limits: XmlParserLimits | None = None,
) -> RenderOutput:
    """Render governed structural slots through the immutable marker engine."""
    if getattr(render_input.profile.manifest, "variant", None) != "STRUCTURAL":
        return _failed_render_output(
            render_input,
            "Structural rendering requires a STRUCTURAL profile",
        )
    output = render_label_only(render_input, compatibility_result, xml_limits)
    if not output.success:
        return output
    try:
        root = parse_diagram_safely(output.diagram_bytes, xml_limits)
        cells = {cell.get("id"): cell for cell in root.iter("mxCell")}
        projection_document = render_input.projection
        for region in render_input.profile.generated_regions:
            region_id = region.region_id
            container_id = region.container_cell_id
            items = list(
                projection_document.get(region.node_selector, [])
                if isinstance(projection_document, Mapping)
                else getattr(projection_document, region.node_selector, ())
            )
            flows = list(
                projection_document.get(region.edge_selector, [])
                if isinstance(projection_document, Mapping)
                else getattr(projection_document, region.edge_selector, ())
            )
            if len(items) > region.page_capacity or len(flows) > region.page_capacity:
                raise RenderError(f"Generated region {region_id} exceeds page capacity")
            if container_id not in cells:
                raise ProfileMismatchError(f"Generated region container {container_id} is absent")
            page_name = region.page_name
            pages = [page for page in root.findall("./diagram") if page.get("name") == page_name]
            if len(pages) != 1:
                raise ProfileMismatchError(f"Generated region page {page_name} is not unique")
            graph_root = pages[0].find("./mxGraphModel/root")
            if graph_root is None:
                raise ProfileMismatchError(f"Generated region page {page_name} has no graph root")
            if not items and region.generated_cell_id:
                token = region.label_token or "APPLICATION_NAME"
                resolved, error = resolve_marker(
                    token,
                    _governed_projection_data(
                        render_input.projection, render_input.projection_hash
                    ),
                    render_input.profile,
                )
                if resolved is None:
                    raise RenderError(error or f"Generated region token {token} is unresolved")
                items = [{"node_id": resolved}]
            node_ids: dict[str, str] = {}
            for index, item in enumerate(sorted(items, key=lambda value: str(value["node_id"]))):
                semantic_id = str(item["node_id"])
                generated_id = (
                    region.generated_cell_id
                    if len(items) == 1 and not flows
                    else _generated_cell_id(region.generated_id_prefix, "node", semantic_id)
                )
                if generated_id in cells:
                    raise ProfileMismatchError(f"Generated cell {generated_id} already exists")
                row, column = divmod(index, region.row_capacity)
                label = semantic_id[:80]
                generated = ET.Element(
                    "mxCell",
                    {"id": generated_id, "value": label, "vertex": "1", "parent": container_id},
                )
                ET.SubElement(
                    generated,
                    "mxGeometry",
                    {
                        "x": str(region.x + column * region.width),
                        "y": str(region.y + row * region.height),
                        "width": str(region.width),
                        "height": str(region.height),
                        "as": "geometry",
                    },
                )
                graph_root.append(generated)
                cells[generated_id] = generated
                node_ids[semantic_id] = generated_id
                output.diagnostics.mutations.append(
                    MutationRecord(
                        len(output.diagnostics.mutations),
                        page_name,
                        generated_id,
                        "CELL_ADD",
                        None,
                        label,
                        region_id,
                        None,
                    )
                )
            for item in sorted(
                flows,
                key=lambda value: (
                    str(value["source_id"]),
                    str(value["target_id"]),
                    str(value.get("protocol")),
                    str(value.get("port")),
                ),
            ):
                source = node_ids.get(str(item["source_id"]))
                target = node_ids.get(str(item["target_id"]))
                if source is None or target is None:
                    raise RenderError("Generated edge endpoint is unavailable")
                semantic = "|".join(
                    str(item.get(key) or "")
                    for key in ("source_id", "target_id", "direction", "protocol", "port")
                )
                edge_id = _generated_cell_id(region.generated_id_prefix, "edge", semantic)
                if edge_id in cells:
                    raise ProfileMismatchError(f"Generated cell {edge_id} already exists")
                edge = ET.Element(
                    "mxCell",
                    {
                        "id": edge_id,
                        "value": f"{item.get('protocol') or ''} {item.get('port') or ''}".strip(),
                        "edge": "1",
                        "parent": container_id,
                        "source": source,
                        "target": target,
                    },
                )
                ET.SubElement(edge, "mxGeometry", {"relative": "1", "as": "geometry"})
                graph_root.append(edge)
                cells[edge_id] = edge
                output.diagnostics.mutations.append(
                    MutationRecord(
                        len(output.diagnostics.mutations),
                        page_name,
                        edge_id,
                        "CELL_ADD",
                        None,
                        edge.get("value"),
                        region_id,
                        None,
                    )
                )
            output.diagnostics.attempted_writes += len(items) + len(flows)
            output.diagnostics.changed_cells += len(items) + len(flows)
        output.diagram_bytes = ET.tostring(root, encoding="unicode").encode("utf-8")
        output.diagram_hash = _compute_hash(output.diagram_bytes)
        output.diagnostics.mutation_count = len(output.diagnostics.mutations)
        output.report_html = _generate_report_html(render_input, output.diagnostics, success=True)
        output.report_hash = _compute_hash(output.report_html.encode("utf-8"))
        output.manifest.diagram_hash = output.diagram_hash
        output.manifest.report_hash = output.report_hash
        output.manifest.mutation_count = output.diagnostics.mutation_count
        output.manifest_hash = _compute_hash(
            json.dumps(output.manifest.__dict__, sort_keys=True).encode("utf-8")
        )
        return output
    except Exception as error:
        return _failed_render_output(render_input, str(error), output.diagnostics)


def _process_cell_value(
    value: str,
    projection: dict[str, Any],
    profile: Any,
    diagnostics: BindingDiagnostics,
    page_name: str,
    cell_id: str,
) -> tuple[str, list[MutationRecord]]:
    """
    Process a cell value, resolving markers.

    Returns:
        (new_value, mutations)
    """
    mutations = []
    new_value = value
    mutation_id = 0

    # Find and resolve markers
    markers = find_markers_in_text(value)
    diagnostics.markers_before += len(markers)

    for marker in markers:
        resolved, error = resolve_marker(marker, projection, profile)

        if resolved is not None:
            # Replace marker with value
            old_marker = "{{" + marker + "}}"
            new_value = new_value.replace(old_marker, resolved, 1)
            diagnostics.markers_resolved += 1

            mutations.append(
                MutationRecord(
                    mutation_id=mutation_id,
                    page_name=page_name,
                    cell_id=cell_id,
                    mutation_type="TEXT_REPLACE",
                    old_value=old_marker,
                    new_value=resolved,
                    slot_id=None,
                    token=marker.split(":")[0],
                )
            )
            mutation_id += 1
        else:
            diagnostics.markers_unresolved += 1
            diagnostics.suspicious_markers.append(
                SuspiciousMarker(
                    pattern="{{" + marker + "}}",
                    location=f"{page_name}:{cell_id}",
                    severity="WARN",
                    description=error or "Unresolved marker",
                )
            )

    # Check for remaining markers
    remaining = find_markers_in_text(new_value)
    diagnostics.markers_after += len(remaining)

    return new_value, mutations


def _process_diagram(
    root: ET.Element,
    projection: dict[str, Any],
    profile: Any,
    diagnostics: RenderDiagnostics,
) -> None:
    """Process diagram, resolving markers in cells."""
    # Find all cells with value attribute
    for cell in root.iter():
        if cell.tag.endswith("mxCell") or cell.tag == "mxCell":
            value = cell.get("value", "")
            cell_id = cell.get("id", "unknown")

            # Find parent page
            page_name = "root"
            parent: ET.Element | None = cell
            while parent is not None:
                if parent.tag.endswith("mxGraphModel") or parent.tag == "mxGraphModel":
                    break
                if parent.tag.endswith("diagram") or parent.tag == "diagram":
                    page_name = parent.get("name", "unnamed")
                    break
                # Try to find parent (not directly supported in ElementTree)
                parent = None

            if value and "{{" in value:
                new_value, mutations = _process_cell_value(
                    value,
                    projection,
                    profile,
                    diagnostics.binding,
                    page_name,
                    cell_id,
                )

                if new_value != value:
                    cell.set("value", new_value)
                    diagnostics.mutations.extend(mutations)


def _generate_report_html(
    render_input: RenderInput,
    diagnostics: RenderDiagnostics,
    success: bool,
) -> str:
    """Generate human-readable HTML report."""
    ctx = render_input.render_context

    mutations_html = ""
    for m in diagnostics.mutations[:50]:  # Limit to 50 for readability
        mutations_html += f"""
        <tr>
            <td>{m.mutation_id}</td>
            <td>{html.escape(m.page_name)}</td>
            <td>{html.escape(m.cell_id)}</td>
            <td>{html.escape(m.mutation_type)}</td>
            <td>{html.escape(str(m.old_value or ""))[:50]}</td>
            <td>{html.escape(str(m.new_value or ""))[:50]}</td>
        </tr>
        """

    warnings_html = ""
    for w in diagnostics.warnings:
        warnings_html += f"<li>{html.escape(w)}</li>"

    suspicious_html = ""
    for s in diagnostics.binding.suspicious_markers:
        suspicious_html += (
            f"<li>[{s.severity}] {html.escape(s.pattern)} at "
            f"{html.escape(s.location)}: {html.escape(s.description)}</li>"
        )

    run_mode = html.escape(
        ctx.run_mode.value if hasattr(ctx.run_mode, "value") else str(ctx.run_mode)
    )
    status_class = "success" if success else "error"
    status_text = "SUCCESS" if success else "FAILED"
    mutation_summary = (
        f"<p><em>Showing first 50 of {len(diagnostics.mutations)} mutations</em></p>"
        if len(diagnostics.mutations) > 50
        else ""
    )
    warnings_section = f"<h2>Warnings</h2><ul>{warnings_html}</ul>" if diagnostics.warnings else ""
    suspicious_section = (
        f"<h2>Suspicious Markers</h2><ul>{suspicious_html}</ul>"
        if diagnostics.binding.suspicious_markers
        else ""
    )
    projection_hash = html.escape(render_input.projection_hash[:16])
    base_diagram_hash = html.escape(render_input.base_diagram_hash[:16])
    profile_hash = html.escape(render_input.profile_hash[:16])

    return f"""<!DOCTYPE html>
<html>
<head>
    <title>Topology Render Report - {html.escape(ctx.run_id)}</title>
    <style>
        body {{ font-family: Arial, sans-serif; margin: 20px; }}
        h1 {{ color: #333; }}
        h2 {{ color: #666; border-bottom: 1px solid #ccc; }}
        table {{ border-collapse: collapse; width: 100%; margin: 10px 0; }}
        th, td {{ border: 1px solid #ddd; padding: 8px; text-align: left; }}
        th {{ background-color: #f4f4f4; }}
        .success {{ color: green; }}
        .error {{ color: red; }}
        .warning {{ color: orange; }}
        .summary {{ background-color: #f9f9f9; padding: 15px; border-radius: 5px; }}
    </style>
</head>
<body>
    <h1>Topology Render Report</h1>

    <div class="summary">
        <h2>Summary</h2>
        <p><strong>Run ID:</strong> {html.escape(ctx.run_id)}</p>
        <p><strong>Mode:</strong> {run_mode}</p>
        <p><strong>Environment:</strong> {html.escape(ctx.environment)}</p>
        <p><strong>Site:</strong> {html.escape(ctx.site or "N/A")}</p>
        <p><strong>Status:</strong> <span class="{status_class}">{status_text}</span></p>
        <p><strong>Mutations:</strong> {len(diagnostics.mutations)}</p>
    </div>

    <h2>Binding Summary</h2>
    <table>
        <tr><th>Metric</th><th>Count</th></tr>
        <tr><td>Markers Before</td><td>{diagnostics.binding.markers_before}</td></tr>
        <tr><td>Markers Resolved</td><td>{diagnostics.binding.markers_resolved}</td></tr>
        <tr><td>Markers Unresolved</td><td>{diagnostics.binding.markers_unresolved}</td></tr>
        <tr><td>Markers After</td><td>{diagnostics.binding.markers_after}</td></tr>
    </table>

    <h2>Mutations</h2>
    <table>
        <tr>
            <th>ID</th>
            <th>Page</th>
            <th>Cell</th>
            <th>Type</th>
            <th>Old Value</th>
            <th>New Value</th>
        </tr>
        {mutations_html}
    </table>
    {mutation_summary}

    {warnings_section}

    {suspicious_section}

    <h2>Input Hashes</h2>
    <table>
        <tr><th>Input</th><th>Hash</th></tr>
        <tr><td>Projection</td><td><code>{projection_hash}...</code></td></tr>
        <tr><td>Base Diagram</td><td><code>{base_diagram_hash}...</code></td></tr>
        <tr><td>Profile</td><td><code>{profile_hash}...</code></td></tr>
    </table>

    <footer>
        <p><em>Generated at {render_input.recorded_timestamp.isoformat()}</em></p>
    </footer>
</body>
</html>
"""


def render_diagram(
    render_input: RenderInput,
    xml_limits: XmlParserLimits | None = None,
) -> RenderOutput:
    """
    Render a topology diagram.

    This is the main entry point for the pure renderer.

    Args:
        render_input: Immutable render input
        xml_limits: Optional XML security limits

    Returns:
        RenderOutput with generated diagram, manifest, and report
    """
    diagnostics = RenderDiagnostics()
    output = RenderOutput(diagnostics=diagnostics)

    try:
        # Parse base diagram
        root = parse_diagram_safely(render_input.base_diagram_bytes, xml_limits)

        # Process diagram (resolve markers)
        _process_diagram(
            root,
            render_input.projection,
            render_input.profile,
            diagnostics,
        )

        # Serialize output
        diagram_bytes = ET.tostring(root, encoding="unicode").encode("utf-8")
        diagram_hash = _compute_hash(diagram_bytes)

        # Generate report
        report_html = _generate_report_html(render_input, diagnostics, success=True)
        report_hash = _compute_hash(report_html.encode("utf-8"))

        # Build manifest
        manifest = RenderManifest(
            manifest_version="1.0.0",
            projection_hash=render_input.projection_hash,
            base_diagram_hash=render_input.base_diagram_hash,
            profile_hash=render_input.profile_hash,
            diagram_hash=diagram_hash,
            report_hash=report_hash,
            environment=render_input.render_context.environment,
            site=render_input.render_context.site,
            variant=render_input.render_context.variant,
            run_id=render_input.render_context.run_id,
            run_mode=render_input.render_context.run_mode.value,
            success=True,
            mutation_count=len(diagnostics.mutations),
            slots_matched=diagnostics.binding.slots_matched,
            slots_total=diagnostics.binding.slots_total,
            recorded_timestamp=render_input.recorded_timestamp.isoformat(),
            render_timestamp=render_input.recorded_timestamp.isoformat(),  # Same as recorded (pure)
        )

        import json

        manifest_json = json.dumps(manifest.__dict__, sort_keys=True)
        manifest_hash = _compute_hash(manifest_json.encode("utf-8"))

        # Update mutation count
        diagnostics.mutation_count = len(diagnostics.mutations)

        return RenderOutput(
            diagram_bytes=diagram_bytes,
            diagram_hash=diagram_hash,
            manifest=manifest,
            manifest_hash=manifest_hash,
            report_html=report_html,
            report_hash=report_hash,
            diagnostics=diagnostics,
            success=True,
            error_message=None,
        )

    except (XmlLimitExceededError, XmlParseError) as e:
        diagnostics.errors.append(str(e))
        output.error_message = str(e)
        output.success = False

        # Generate error report
        output.report_html = _generate_report_html(render_input, diagnostics, success=False)
        output.report_hash = _compute_hash(output.report_html.encode("utf-8"))

        return output

    except Exception as e:
        diagnostics.errors.append(f"Unexpected error: {e}")
        output.error_message = f"Render failed: {e}"
        output.success = False
        return output
