"""HAF topology pipeline — haf-role-based template fill for draw.io diagrams.

This module provides a focused, deterministic pipeline for transforming
input draw.io templates with ``haf-role`` annotated cells into resolved
end-state topology diagrams. It:

1. Parses draw.io XML and indexes cells by ``haf-role`` attribute (Block 1)
2. Loads profile configs mapping roles to resolution rules (Block 2)
3. Resolves placeholder tokens in cell values (Block 3)
4. Populates interface region slots (Block 4)
5. Fills detail blocks (Block 5)
6. Orchestrates the full pipeline with gap report (Block 6)

Design rules:
- Pure function: no DB access; data extraction is a separate phase.
- Deterministic: same inputs produce byte-identical output.
- Structural safety: only cell ``value`` attributes are mutated.
- Only cells with ``haf-role`` matching the profile are touched.
- Protected roles (legend, frame, etc.) are never mutated.

Updated 2026-09-25: Added grouped interface rendering for ATT Internal section
with protocol/port grouping and bidirectional semantics per Topology Guide.
"""

from __future__ import annotations

import fnmatch
import json
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING
from migration_intake.topology.att_internal_generator import generate_att_internal_rows

if TYPE_CHECKING:
    from migration_intake.topology.interface_normalization import (
        InterfaceGroup,
        ProtocolFamilyGroup,
    )

_PROFILES_DIR = Path(__file__).resolve().parent / "config" / "haf_profiles"

# Maps variant key (from UI) to profile ID.
# None = legacy behavior (user-uploaded template, original profile).
VARIANT_PROFILE_MAP: dict[str | None, str] = {
    None: "OUTPOST_V1",
    "basic": "OUTPOST_V1_BASIC",
    "tlgw": "OUTPOST_V1_TLGW",
    "f5": "OUTPOST_V1_F5",
    "hadr": "OUTPOST_V1_HADR",
}


class HafPipelineError(ValueError):
    """Base error for haf pipeline failures."""


class HafParseError(HafPipelineError):
    """Input draw.io XML is invalid or unsupported."""


class HafProfileError(HafPipelineError):
    """Profile config is invalid or not found."""


@dataclass
class HafIndex:
    """Parsed draw.io template indexed by haf-role.

    Attributes:
        by_role: Mapping from each individual role name to the list of
            mxCell elements that declare that role.
        all_roles: Set of all unique role names found in the template.
        tree: The full parsed ElementTree (cells are live references).
    """

    by_role: dict[str, list[ET.Element]] = field(default_factory=dict)
    all_roles: set[str] = field(default_factory=set)
    tree: ET.ElementTree = field(default=None)  # type: ignore[assignment]


def parse_haf_template(data: bytes) -> HafIndex:
    """Parse a draw.io XML template and index cells by ``haf-role``.

    Args:
        data: Raw draw.io XML bytes (uncompressed).

    Returns:
        HafIndex with cells indexed by role.

    Raises:
        HafParseError: If the XML is invalid, compressed, or has duplicate IDs.
    """
    try:
        root = ET.fromstring(data)
    except ET.ParseError as exc:
        raise HafParseError(f"Failed to parse draw.io XML: {exc}") from exc

    if root.tag != "mxfile":
        raise HafParseError(f"Expected <mxfile> root, got <{root.tag}>")

    diagrams = root.findall("diagram")
    if not diagrams:
        raise HafParseError("No <diagram> elements found")

    # Reject compressed diagrams (text content instead of mxGraphModel child)
    for diagram in diagrams:
        if diagram.find("mxGraphModel") is None:
            text = (diagram.text or "").strip()
            if text:
                raise HafParseError(
                    "Compressed draw.io not supported; expected <mxGraphModel> "
                    "child inside <diagram>"
                )

    tree = ET.ElementTree(root)
    by_role: dict[str, list[ET.Element]] = {}
    all_roles: set[str] = set()
    seen_ids: dict[str, int] = {}

    for cell in root.iter("mxCell"):
        cell_id = cell.get("id")
        if cell_id:
            if cell_id in seen_ids:
                raise HafParseError(f"Duplicate cell ID: {cell_id!r}")
            seen_ids[cell_id] = 1

        role_attr = cell.get("haf-role")
        if not role_attr:
            continue

        roles = role_attr.strip().split()
        for role in roles:
            all_roles.add(role)
            by_role.setdefault(role, []).append(cell)

    return HafIndex(by_role=by_role, all_roles=all_roles, tree=tree)


# ─── Block 2: Profile config ──────────────────────────────────────────


@dataclass(frozen=True)
class PlaceholderBinding:
    """One placeholder token binding from the profile config."""

    haf_role: str
    token: str
    required: bool = True
    pattern: str | None = None
    pattern_regex: str | None = None


@dataclass(frozen=True)
class InterfaceRegion:
    """One interface region definition from the profile config."""

    haf_role: str
    category: str
    direction: str | None
    rendering: str = "MULTILINE_TEXT"
    format: str = "{app_name} ({correlation_id})"
    empty_value: str = ""
    group: str | None = None


@dataclass(frozen=True)
class DetailBlock:
    """One detail block definition from the profile config."""

    haf_role: str
    fields: tuple[str, ...]
    template: str


@dataclass
class HafProfile:
    """Parsed and validated haf profile config."""

    profile_id: str
    template_version: str
    schema_version: str
    placeholder_bindings: list[PlaceholderBinding] = field(default_factory=list)
    interface_regions: list[InterfaceRegion] = field(default_factory=list)
    detail_blocks: list[DetailBlock] = field(default_factory=list)
    protected_roles: list[str] = field(default_factory=list)
    standard_sections: list[str] = field(default_factory=list)

    def is_protected(self, role: str) -> bool:
        """Check if a role is protected (should never be mutated)."""
        for pattern in self.protected_roles:
            if fnmatch.fnmatch(role, pattern):
                return True
        return False

    def validate_against_index(self, index: HafIndex) -> list[dict[str, str]]:
        """Validate profile roles exist in the template index.

        Returns a list of warning dicts for roles referenced in the profile
        but not found in the template.
        """
        warnings: list[dict[str, str]] = []
        referenced_roles: set[str] = set()

        for binding in self.placeholder_bindings:
            referenced_roles.add(binding.haf_role)
        for region in self.interface_regions:
            referenced_roles.add(region.haf_role)
        for block in self.detail_blocks:
            referenced_roles.add(block.haf_role)

        for role in sorted(referenced_roles):
            if role not in index.all_roles:
                warnings.append({
                    "haf_role": role,
                    "message": f"Profile references role {role!r} but template has no cell with that role",
                })

        return warnings


def load_haf_profile(profile_id: str) -> HafProfile:
    """Load a haf profile config by ID.

    Args:
        profile_id: Profile identifier (e.g. ``"OUTPOST_V1"``).

    Returns:
        Parsed HafProfile.

    Raises:
        HafProfileError: If the profile is not found or invalid.
    """
    # Scan the profiles directory for a matching profile_id
    for path in _PROFILES_DIR.glob("*.json"):
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise HafProfileError(f"Failed to read profile {path}: {exc}") from exc

        if raw.get("profile_id") == profile_id:
            return _parse_profile(raw, path)

    raise HafProfileError(f"Profile {profile_id!r} not found in {_PROFILES_DIR}")


def get_profile_for_variant(variant: str | None) -> HafProfile:
    """Look up and load the HAF profile for a variant key.

    Args:
        variant: Variant key from the UI (e.g. ``"basic"``, ``"tlgw"``).
            ``None`` returns the legacy ``OUTPOST_V1`` profile.

    Returns:
        Loaded HafProfile.

    Raises:
        HafProfileError: If the variant is not recognized.
    """
    profile_id = VARIANT_PROFILE_MAP.get(variant)
    if profile_id is None:
        raise HafProfileError(
            f"Unknown variant {variant!r}. "
            f"Valid variants: {sorted(k for k in VARIANT_PROFILE_MAP if k)}"
        )
    return load_haf_profile(profile_id)


def _parse_profile(raw: dict, source: Path) -> HafProfile:
    """Parse a raw JSON dict into a typed HafProfile."""
    try:
        bindings = [
            PlaceholderBinding(
                haf_role=b["haf_role"],
                token=b["token"],
                required=b.get("required", True),
                pattern=b.get("pattern"),
                pattern_regex=b.get("pattern_regex"),
            )
            for b in raw.get("placeholder_bindings", [])
        ]
        regions = [
            InterfaceRegion(
                haf_role=r["haf_role"],
                category=r["category"],
                direction=r.get("direction"),
                rendering=r.get("rendering", "MULTILINE_TEXT"),
                format=r.get("format", "{app_name} ({correlation_id})"),
                empty_value=r.get("empty_value", ""),
                group=r.get("group"),
            )
            for r in raw.get("interface_regions", [])
        ]
        detail_blocks = [
            DetailBlock(
                haf_role=d["haf_role"],
                fields=tuple(d["fields"]),
                template=d["template"],
            )
            for d in raw.get("detail_blocks", [])
        ]
        return HafProfile(
            profile_id=raw["profile_id"],
            template_version=raw.get("template_version", ""),
            schema_version=raw.get("schema_version", ""),
            placeholder_bindings=bindings,
            interface_regions=regions,
            detail_blocks=detail_blocks,
            protected_roles=list(raw.get("protected_roles", [])),
            standard_sections=list(raw.get("standard_sections", [])),
        )
    except (KeyError, TypeError) as exc:
        raise HafProfileError(f"Invalid profile {source}: {exc}") from exc


# ─── Block 3: Placeholder token resolver ──────────────────────────────


@dataclass
class HafMutation:
    """Record of a single cell value mutation."""

    cell_id: str
    haf_role: str
    token: str
    old_fragment: str
    new_fragment: str


@dataclass
class HafGap:
    """Record of an unresolved placeholder."""

    haf_role: str
    token: str
    pattern: str
    blocking: bool


def resolve_placeholders(
    index: HafIndex,
    profile: HafProfile,
    tokens: dict[str, str],
) -> tuple[list[HafMutation], list[HafGap]]:
    """Resolve placeholder tokens in cell values.

    For each placeholder binding in the profile, find cells matching the
    binding's ``haf_role`` and replace the pattern/regex in the cell's
    ``value`` attribute with the corresponding token value.

    Args:
        index: Parsed template index.
        profile: Loaded profile config.
        tokens: Mapping from token name to resolved value.

    Returns:
        Tuple of (mutations applied, gaps for unresolved tokens).
    """
    import re

    mutations: list[HafMutation] = []
    gaps: list[HafGap] = []

    for binding in profile.placeholder_bindings:
        # Skip protected roles
        if profile.is_protected(binding.haf_role):
            continue

        cells = index.by_role.get(binding.haf_role, [])
        if not cells:
            if binding.required:
                gaps.append(HafGap(
                    haf_role=binding.haf_role,
                    token=binding.token,
                    pattern=binding.pattern or binding.pattern_regex or "",
                    blocking=True,
                ))
            continue

        value = tokens.get(binding.token)
        if value is None:
            pattern_str = binding.pattern or binding.pattern_regex or ""
            gaps.append(HafGap(
                haf_role=binding.haf_role,
                token=binding.token,
                pattern=pattern_str,
                blocking=binding.required,
            ))
            continue

        for cell in cells:
            old_value = cell.get("value") or ""
            new_value = old_value

            if binding.pattern:
                if binding.pattern in old_value:
                    new_value = old_value.replace(binding.pattern, value)
            elif binding.pattern_regex:
                match = re.search(binding.pattern_regex, old_value)
                if match:
                    new_value = old_value[:match.start()] + value + old_value[match.end():]

            if new_value != old_value:
                cell.set("value", new_value)
                mutations.append(HafMutation(
                    cell_id=cell.get("id") or "",
                    haf_role=binding.haf_role,
                    token=binding.token,
                    old_fragment=binding.pattern or (match.group() if binding.pattern_regex and match else ""),
                    new_fragment=value,
                ))

    return mutations, gaps


# ─── Block 4: Interface region filler ─────────────────────────────────


def fill_interface_regions(
    index: HafIndex,
    profile: HafProfile,
    interfaces: dict[str, list[dict[str, str]]],
    *,
    skip_internal: bool = False,
) -> list[HafMutation]:
    """Populate interface region cells with interface data.

    Args:
        index: Parsed template index.
        profile: Loaded profile config.
        interfaces: Mapping from ``"category:direction"`` to list of
            dicts with ``app_name`` and ``correlation_id``.
        skip_internal: If True, skip INTERNAL category regions (used when
            grouped rendering has already filled them).

    Returns:
        List of mutations applied.
    """
    mutations: list[HafMutation] = []

    for region in profile.interface_regions:
        if profile.is_protected(region.haf_role):
            continue

        # Skip INTERNAL regions if grouped rendering was used
        if skip_internal and region.category == "INTERNAL":
            continue

        cells = index.by_role.get(region.haf_role, [])
        if not cells:
            continue

        if region.direction is not None:
            key = f"{region.category}:{region.direction}"
            entries = interfaces.get(key, [])
        else:
            # direction=null means aggregate all directions for this category
            entries = []
            for ikey, ival in interfaces.items():
                if ikey.startswith(f"{region.category}:"):
                    entries.extend(ival)

        if entries:
            lines = [
                region.format.format(
                    app_name=entry.get("app_name", ""),
                    correlation_id=entry.get("correlation_id", ""),
                )
                for entry in entries
            ]
            new_value = "\n".join(lines)
        else:
            new_value = region.empty_value

        for cell in cells:
            old_value = cell.get("value") or ""
            if new_value != old_value:
                cell.set("value", new_value)
                mutations.append(HafMutation(
                    cell_id=cell.get("id") or "",
                    haf_role=region.haf_role,
                    token=f"interface:{region.category}:{region.direction}",
                    old_fragment=old_value[:50],
                    new_fragment=new_value[:50],
                ))

    return mutations


# ─── Block 4b: Grouped interface region filler (ATT Internal) ─────────


def fill_interface_regions_grouped(
    index: HafIndex,
    profile: HafProfile,
    interface_groups: list,
) -> list[HafMutation]:
    """Populate ATT Internal interface regions with grouped protocol/port data.

    This function renders interfaces grouped by protocol and port, with
    bidirectional semantics, as required by the Topology Guide for the
    AT&T Internal Interfaces section.

    Args:
        index: Parsed template index.
        profile: Loaded profile config.
        interface_groups: List of InterfaceGroup objects from normalization.

    Returns:
        List of mutations applied.
    """
    mutations: list[HafMutation] = []

    # Find ATT Internal regions in the profile
    internal_regions = [
        r for r in profile.interface_regions
        if r.category == "INTERNAL" and not profile.is_protected(r.haf_role)
    ]

    if not internal_regions or not interface_groups:
        return mutations

    def _format_entry(region: InterfaceRegion, app_name: str | None, correlation_id: str | None) -> str:
        return region.format.format(
            app_name=app_name or "",
            correlation_id=correlation_id or "",
        )

    inbound_region = next((r for r in internal_regions if r.direction == "INBOUND"), None)
    bidirectional_region = next((r for r in internal_regions if r.direction == "BIDIRECTIONAL"), None)
    outbound_regions = [r for r in internal_regions if r.direction == "OUTBOUND"]
    outbound_regions.sort(key=lambda r: (0 if (r.group or "").upper() == "PRIMARY" else 1, r.haf_role))

    role_to_lines: dict[str, list[str]] = {region.haf_role: [] for region in internal_regions}

    outbound_group_index = 0
    for iface_group in interface_groups:
        if inbound_region is not None:
            for entry in iface_group.entries_inbound:
                role_to_lines[inbound_region.haf_role].append(
                    _format_entry(inbound_region, entry.interface_app_acronym, entry.interface_correlation_id)
                )

        if bidirectional_region is not None:
            for entry in iface_group.entries_bidirectional:
                role_to_lines[bidirectional_region.haf_role].append(
                    _format_entry(
                        bidirectional_region,
                        entry.interface_app_acronym,
                        entry.interface_correlation_id,
                    )
                )

        if outbound_regions:
            target_region = outbound_regions[outbound_group_index % len(outbound_regions)]
            outbound_group_index += 1
            for entry in iface_group.entries_outbound:
                role_to_lines[target_region.haf_role].append(
                    _format_entry(target_region, entry.interface_app_acronym, entry.interface_correlation_id)
                )

    # Fill each INTERNAL region
    for region in internal_regions:
        cells = index.by_role.get(region.haf_role, [])
        if not cells:
            continue

        lines = role_to_lines.get(region.haf_role, [])

        if lines:
            new_value = "\n".join(lines)
        else:
            new_value = region.empty_value

        for cell in cells:
            old_value = cell.get("value") or ""
            if new_value != old_value:
                cell.set("value", new_value)
                mutations.append(HafMutation(
                    cell_id=cell.get("id") or "",
                    haf_role=region.haf_role,
                    token=f"interface_grouped:{region.category}:{region.direction}",
                    old_fragment=old_value[:50],
                    new_fragment=new_value[:50],
                ))

    return mutations


# ─── Block 5: Detail block filler ────────────────────────────────────


def fill_detail_blocks(
    index: HafIndex,
    profile: HafProfile,
    details: dict[str, dict[str, str]],
) -> list[HafMutation]:
    """Fill detail block cells with resource data.

    Args:
        index: Parsed template index.
        profile: Loaded profile config.
        details: Mapping from ``haf_role`` to dict of field values.

    Returns:
        List of mutations applied.
    """
    mutations: list[HafMutation] = []

    for block in profile.detail_blocks:
        if profile.is_protected(block.haf_role):
            continue

        cells = index.by_role.get(block.haf_role, [])
        if not cells:
            continue

        data = details.get(block.haf_role, {})
        # Apply template with available data (missing fields become empty)
        fill_values = {f: data.get(f, "") for f in block.fields}
        new_value = block.template.format(**fill_values)

        for cell in cells:
            old_value = cell.get("value") or ""
            if new_value != old_value:
                cell.set("value", new_value)
                mutations.append(HafMutation(
                    cell_id=cell.get("id") or "",
                    haf_role=block.haf_role,
                    token=f"detail:{block.haf_role}",
                    old_fragment=old_value[:50],
                    new_fragment=new_value[:50],
                ))

    return mutations


# ─── Block 6: Pipeline orchestrator ──────────────────────────────────


@dataclass
class HafFillResult:
    """Result of the full haf template fill pipeline."""

    filled_xml: bytes
    mutations: list[HafMutation]
    gaps: list[HafGap]
    success: bool


def fill_haf_template(
    *,
    template_bytes: bytes,
    tokens: dict[str, str],
    interfaces: dict[str, list[dict[str, str]]],
    details: dict[str, dict[str, str]],
    profile_id: str,
    interface_groups: list["InterfaceGroup"] | list["ProtocolFamilyGroup"] | None = None,
    aws_interface_groups: list["ProtocolFamilyGroup"] | None = None,
) -> HafFillResult:
    """Run the full haf template fill pipeline.

    1. Parse template and index by haf-role
    2. Load profile config
    3. Resolve placeholder tokens
    4. Populate interface regions (with optional grouped rendering for ATT Internal)
    5. Fill detail blocks
    6. Validate and serialize

    Args:
        template_bytes: Raw draw.io XML bytes.
        tokens: Token name -> resolved value.
        interfaces: ``"category:direction"`` -> list of interface dicts.
        details: ``haf_role`` -> dict of detail field values.
        profile_id: Profile identifier to load.
        interface_groups: Optional list of InterfaceGroup objects for grouped
            rendering of ATT Internal section. If provided, uses grouped
            protocol/port rendering; otherwise uses legacy flat rendering.

    Returns:
        HafFillResult with filled XML, mutations, gaps, and success flag.
    """
    index = parse_haf_template(template_bytes)
    profile = load_haf_profile(profile_id)

    all_mutations: list[HafMutation] = []
    all_gaps: list[HafGap] = []

    # Step 1: Resolve placeholder tokens
    token_mutations, token_gaps = resolve_placeholders(index, profile, tokens)
    all_mutations.extend(token_mutations)
    all_gaps.extend(token_gaps)

    # Step 2: Populate interface regions
    # Use programmatic rendering for ATT Internal if groups are provided.
    skip_internal = False
    if interface_groups:
        row_result = generate_att_internal_rows(index.tree, interface_groups)
        # Track generated/deleted structural operations as mutations for reporting.
        for created in row_result.elements_created:
            all_mutations.append(
                HafMutation(
                    cell_id=created.element_id,
                    haf_role="att_internal_interfaces_band",
                    token="ATT_INTERNAL_GENERATED",
                    old_fragment="",
                    new_fragment=created.element_type,
                )
            )
        if row_result.elements_deleted:
            all_mutations.append(
                HafMutation(
                    cell_id="att_internal_generated_cleanup",
                    haf_role="att_internal_interfaces_band",
                    token="ATT_INTERNAL_DELETED",
                    old_fragment=str(row_result.elements_deleted),
                    new_fragment="0",
                )
            )
        if row_result.issues:
            for issue in row_result.issues:
                all_gaps.append(
                    HafGap(
                        haf_role="att_internal_interfaces_band",
                        token="ATT_INTERNAL_LAYOUT",
                        pattern=issue,
                        blocking=False,
                    )
                )
        skip_internal = True  # Don't overwrite INTERNAL regions with legacy rendering

    # Step 2b: Generate AWS Tier 1 interface boxes
    if aws_interface_groups:
        from migration_intake.topology.aws_tier1_generator import (
            generate_aws_tier1_rows,
        )
        aws_result = generate_aws_tier1_rows(index.tree, aws_interface_groups)
        for created in aws_result.elements_created:
            all_mutations.append(
                HafMutation(
                    cell_id=created.element_id,
                    haf_role="aws_tier1_container",
                    token="AWS_TIER1_GENERATED",
                    old_fragment="",
                    new_fragment=created.element_type,
                )
            )
        if aws_result.elements_deleted:
            all_mutations.append(
                HafMutation(
                    cell_id="aws_tier1_generated_cleanup",
                    haf_role="aws_tier1_container",
                    token="AWS_TIER1_DELETED",
                    old_fragment=str(aws_result.elements_deleted),
                    new_fragment="0",
                )
            )
        if aws_result.issues:
            for issue in aws_result.issues:
                all_gaps.append(
                    HafGap(
                        haf_role="aws_tier1_container",
                        token="AWS_TIER1_LAYOUT",
                        pattern=issue,
                        blocking=False,
                    )
                )

    # Fill non-INTERNAL regions using legacy flat rendering
    # (or all regions if no grouped rendering was done)
    interface_mutations = fill_interface_regions(
        index, profile, interfaces, skip_internal=skip_internal
    )
    all_mutations.extend(interface_mutations)

    # Step 3: Fill detail blocks
    detail_mutations = fill_detail_blocks(index, profile, details)
    all_mutations.extend(detail_mutations)

    # Step 4: Check for blocking gaps
    has_blocking = any(g.blocking for g in all_gaps)

    # Step 5: Serialize the filled tree
    filled_xml = ET.tostring(index.tree.getroot(), encoding="unicode", xml_declaration=False)
    filled_bytes = filled_xml.encode("utf-8")

    return HafFillResult(
        filled_xml=filled_bytes,
        mutations=all_mutations,
        gaps=all_gaps,
        success=not has_blocking,
    )
