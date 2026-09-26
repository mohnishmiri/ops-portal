"""Pure base/profile compatibility inspection for governed topology rendering."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING, Any

from migration_intake.topology.contracts import (
    RenderCapability,
    canonical_json_bytes,
    sha256_hex,
)
from migration_intake.topology.renderer.core import (
    XmlParserLimits,
    find_markers_in_text,
    parse_diagram_safely,
)

if TYPE_CHECKING:
    from migration_intake.topology.profiles.loader import Profile, ProfileSlot
    from migration_intake.topology.scope import ContextKey, ScopeSelection

COMPATIBILITY_VALIDATOR_VERSION = "1.0.0"


@dataclass(frozen=True, slots=True)
class BasePage:
    """Inventory of one Draw.io page."""

    page_id: str
    name: str
    cell_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class BaseCell:
    """Inventory of one Draw.io cell."""

    page_name: str
    cell_id: str
    value: str | None
    parent: str | None


@dataclass(frozen=True, slots=True)
class BaseInventory:
    """Canonical, read-only inventory of a parsed base diagram."""

    base_hash: str
    pages: tuple[BasePage, ...]
    cells: tuple[BaseCell, ...]
    markers: tuple[str, ...]
    inventory_hash: str


@dataclass(frozen=True, slots=True)
class CompatibilityIssue:
    """Stable compatibility diagnostic."""

    code: str
    message: str
    subject: str
    blocking: bool = True


@dataclass(frozen=True, slots=True)
class SlotMatch:
    """A governed profile slot matched to exact base cells."""

    slot_id: str
    page_name: str
    cell_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CompatibilityResult:
    """Deterministic compatibility result, independent of data readiness."""

    is_compatible: bool
    base_hash: str
    profile_hash: str
    selection_hash: str
    capability: RenderCapability
    parser_policy_hash: str
    compatibility_key: str
    result_hash: str
    inventory: BaseInventory
    slot_matches: tuple[SlotMatch, ...]
    issues: tuple[CompatibilityIssue, ...]
    warnings: tuple[CompatibilityIssue, ...]

    @property
    def blocking_issues(self) -> tuple[CompatibilityIssue, ...]:
        """Return blocking compatibility diagnostics."""
        return tuple(issue for issue in self.issues if issue.blocking)


class CompatibilityError(ValueError):
    """Base error for malformed compatibility inputs."""


def _hash_document(document: dict[str, Any]) -> str:
    return sha256_hex(canonical_json_bytes(document))


def _parser_policy_hash(parser_policy: XmlParserLimits) -> str:
    return _hash_document(asdict(parser_policy))


def _page_inventory(root: Any) -> tuple[tuple[BasePage, ...], tuple[BaseCell, ...]]:
    pages: list[BasePage] = []
    cells: list[BaseCell] = []
    page_ids: set[str] = set()
    for page_index, page in enumerate(child for child in root if child.tag == "diagram"):
        page_id = page.get("id") or f"page-{page_index}"
        page_name = page.get("name")
        if not page_name:
            raise CompatibilityError("Every Draw.io page requires a name")
        if page_id in page_ids:
            raise CompatibilityError(f"Duplicate page ID: {page_id}")
        page_ids.add(page_id)
        page_cell_ids: list[str] = []
        for element in page.iter():
            if element.tag != "mxCell":
                continue
            cell_id = element.get("id")
            if not cell_id:
                raise CompatibilityError(f"Page {page_name} contains a cell without an ID")
            page_cell_ids.append(cell_id)
            cells.append(
                BaseCell(
                    page_name=page_name,
                    cell_id=cell_id,
                    value=element.get("value"),
                    parent=element.get("parent"),
                )
            )
        pages.append(BasePage(page_id, page_name, tuple(page_cell_ids)))
    if not pages:
        raise CompatibilityError("Draw.io base must contain at least one named page")
    return tuple(pages), tuple(cells)


def _inventory(base_bytes: bytes, parser_policy: XmlParserLimits) -> BaseInventory:
    root = parse_diagram_safely(base_bytes, parser_policy)
    try:
        pages, cells = _page_inventory(root)
    except CompatibilityError:
        raise
    markers = tuple(
        sorted(
            {
                f"{{{{{marker}}}}}"
                for cell in cells
                for marker in find_markers_in_text(cell.value or "")
            }
        )
    )
    document = {
        "base_hash": sha256_hex(base_bytes),
        "pages": [
            {"id": page.page_id, "name": page.name, "cell_ids": list(page.cell_ids)}
            for page in pages
        ],
        "cells": [asdict(cell) for cell in cells],
        "markers": list(markers),
    }
    return BaseInventory(
        base_hash=sha256_hex(base_bytes),
        pages=pages,
        cells=cells,
        markers=markers,
        inventory_hash=_hash_document(document),
    )


def _page_matches(page: BasePage, selector: dict[str, Any]) -> bool:
    allowed = {"page_name_pattern"}
    if set(selector) - allowed:
        raise CompatibilityError("Unknown page selector field")
    pattern = selector.get("page_name_pattern")
    if pattern is None:
        return True
    if not isinstance(pattern, str):
        raise CompatibilityError("Page selector pattern must be a string")
    try:
        return re.fullmatch(pattern, page.name) is not None
    except re.error as error:
        raise CompatibilityError(f"Invalid page selector pattern: {error}") from error


def _slot_matches(
    slot: ProfileSlot, page: BasePage, cells_by_id: dict[str, BaseCell]
) -> tuple[str, ...]:
    matcher = slot.cell_matcher
    if set(matcher) - {"match_type", "marker_pattern"}:
        raise CompatibilityError(f"Unknown cell matcher field for slot {slot.slot_id}")
    if matcher.get("match_type") != "MARKER":
        raise CompatibilityError(f"Unsupported cell matcher for slot {slot.slot_id}")
    marker_pattern = matcher.get("marker_pattern")
    if not isinstance(marker_pattern, str):
        raise CompatibilityError(f"Slot {slot.slot_id} requires a marker pattern")
    return tuple(
        cell.cell_id
        for cell in (cells_by_id[cell_id] for cell_id in page.cell_ids)
        if marker_pattern in (cell.value or "")
    )


def _profile_marker_patterns(profile: Profile) -> set[str]:
    return {marker.pattern for marker in profile.markers}


def _result_hash(
    inventory: BaseInventory,
    profile: Profile,
    selection: ScopeSelection,
    capability: RenderCapability,
    slot_matches: tuple[SlotMatch, ...],
    issues: tuple[CompatibilityIssue, ...],
    warnings: tuple[CompatibilityIssue, ...],
) -> str:
    document = {
        "base_hash": inventory.base_hash,
        "inventory_hash": inventory.inventory_hash,
        "profile_hash": profile.profile_hash,
        "selection": selection.as_dict(),
        "capability": capability.value,
        "slot_matches": [asdict(match) for match in slot_matches],
        "issues": [asdict(issue) for issue in issues],
        "warnings": [asdict(issue) for issue in warnings],
    }
    return _hash_document(document)


def inspect_base(
    base_bytes: bytes,
    profile: Profile,
    selection: ScopeSelection,
    *,
    capability: RenderCapability,
    parser_policy: XmlParserLimits,
    partition_views: dict[ContextKey, str],
) -> CompatibilityResult:
    """Inspect a base against a loaded profile and explicit selected contexts."""
    inventory = _inventory(base_bytes, parser_policy)
    parser_policy_hash = _parser_policy_hash(parser_policy)
    issues: list[CompatibilityIssue] = []
    warnings: list[CompatibilityIssue] = []
    slot_matches: list[SlotMatch] = []

    if profile.manifest.variant != capability.value:
        issues.append(
            CompatibilityIssue(
                "CAPABILITY_MISMATCH",
                f"Profile variant {profile.manifest.variant} does not support {capability.value}",
                f"profile:{profile.profile_id}",
            )
        )

    if capability == RenderCapability.STRUCTURAL and not profile.generated_regions:
        issues.append(
            CompatibilityIssue(
                "STRUCTURAL_POLICY_MISSING",
                "Structural generated-region policy is not declared",
                f"profile:{profile.profile_id}",
            )
        )

    pages_by_name: dict[str, list[BasePage]] = {}
    for page in inventory.pages:
        pages_by_name.setdefault(page.name, []).append(page)
    cells_by_id = {cell.cell_id: cell for cell in inventory.cells}
    if capability == RenderCapability.STRUCTURAL:
        generated_prefixes: set[str] = set()
        for region in profile.generated_regions:
            region_id = region.region_id
            container_id = region.container_cell_id
            if region.generated_id_prefix in generated_prefixes:
                issues.append(
                    CompatibilityIssue(
                        "DUPLICATE_GENERATED_PREFIX",
                        f"Generated ID prefix {region.generated_id_prefix} is reused",
                        f"region:{region_id}",
                    )
                )
            generated_prefixes.add(region.generated_id_prefix)
            missing_cells = [
                cell_id
                for cell_id in (
                    container_id,
                    region.node_prototype_cell_id,
                    region.edge_prototype_cell_id,
                )
                if cell_id not in cells_by_id
            ]
            if missing_cells:
                issues.append(
                    CompatibilityIssue(
                        "MISSING_GENERATED_REGION",
                        f"Generated region cells are missing: {','.join(missing_cells)}",
                        f"region:{region_id}",
                    )
                )
    governed_markers = _profile_marker_patterns(profile)
    for marker in inventory.markers:
        if marker not in governed_markers:
            issues.append(
                CompatibilityIssue(
                    "UNRECOGNIZED_MARKER",
                    f"Base marker {marker} is not declared by the profile",
                    f"marker:{marker}",
                )
            )

    for context in selection.ordered_contexts:
        page_name = partition_views.get(context)
        if page_name is None:
            issues.append(
                CompatibilityIssue(
                    "MISSING_PARTITION_VIEW",
                    f"No base page is declared for {context.environment}/{context.site_id}",
                    f"context:{context.environment}/{context.site_id}",
                )
            )
            continue
        selected_pages = pages_by_name.get(page_name, [])
        if len(selected_pages) == 0:
            issues.append(
                CompatibilityIssue(
                    "MISSING_PAGE",
                    f"Configured page {page_name} is missing",
                    f"page:{page_name}",
                )
            )
            continue
        if len(selected_pages) > 1:
            issues.append(
                CompatibilityIssue(
                    "AMBIGUOUS_PAGE",
                    f"Configured page {page_name} occurs more than once",
                    f"page:{page_name}",
                )
            )
            continue
        page = selected_pages[0]
        for slot in profile.slots:
            if not _page_matches(page, slot.page_selector):
                if slot.slot_type.value == "MANDATORY":
                    issues.append(
                        CompatibilityIssue(
                            "MISSING_SLOT",
                            f"Mandatory slot {slot.slot_id} is not configured for page {page.name}",
                            f"slot:{slot.slot_id}:{context.environment}/{context.site_id}",
                        )
                    )
                continue
            matches = _slot_matches(slot, page, cells_by_id)
            if not matches and slot.cardinality_min > 0:
                issues.append(
                    CompatibilityIssue(
                        "MISSING_SLOT",
                        f"Mandatory slot {slot.slot_id} has no matching cells",
                        f"slot:{slot.slot_id}:{page.name}",
                    )
                )
                continue
            if not slot.cardinality_min <= len(matches) <= slot.cardinality_max:
                issues.append(
                    CompatibilityIssue(
                        "SLOT_CARDINALITY",
                        f"Slot {slot.slot_id} matched {len(matches)} cells; expected "
                        f"{slot.cardinality_min}..{slot.cardinality_max}",
                        f"slot:{slot.slot_id}:{page.name}",
                    )
                )
                continue
            slot_matches.append(SlotMatch(slot.slot_id, page.name, matches))

    pages_document = [
        {"context": context.as_dict(), "page": partition_views.get(context)}
        for context in selection.ordered_contexts
    ]
    if len(set(partition_views.values())) != len(partition_views):
        issues.append(
            CompatibilityIssue(
                "DUPLICATE_PARTITION_VIEW",
                "Selected contexts must map to distinct pages",
                "selection:partition_views",
            )
        )
    if not pages_document:
        issues.append(
            CompatibilityIssue("EMPTY_SELECTION", "At least one partition is required", "selection")
        )

    slot_matches_tuple = tuple(
        sorted(slot_matches, key=lambda item: (item.page_name, item.slot_id))
    )
    issues_tuple = tuple(issues)
    warnings_tuple = tuple(warnings)
    compatibility_document = {
        "base_hash": inventory.base_hash,
        "profile_hash": profile.profile_hash,
        "selection_hash": selection.selection_hash,
        "capability": capability.value,
        "parser_policy_hash": parser_policy_hash,
        "validator_version": COMPATIBILITY_VALIDATOR_VERSION,
        "partition_views": pages_document,
    }
    compatibility_key = _hash_document(compatibility_document)
    result_hash = _result_hash(
        inventory, profile, selection, capability, slot_matches_tuple, issues_tuple, warnings_tuple
    )
    return CompatibilityResult(
        is_compatible=not any(issue.blocking for issue in issues_tuple),
        base_hash=inventory.base_hash,
        profile_hash=profile.profile_hash,
        selection_hash=selection.selection_hash,
        capability=capability,
        parser_policy_hash=parser_policy_hash,
        compatibility_key=compatibility_key,
        result_hash=result_hash,
        inventory=inventory,
        slot_matches=slot_matches_tuple,
        issues=issues_tuple,
        warnings=warnings_tuple,
    )
