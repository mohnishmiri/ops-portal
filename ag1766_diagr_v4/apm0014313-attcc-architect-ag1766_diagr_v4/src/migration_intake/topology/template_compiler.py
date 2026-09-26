"""Validation/compile helper for admin-uploaded topology templates."""

from __future__ import annotations

import hashlib
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Any

from migration_intake.topology.haf_pipeline import (
    HafParseError,
    get_profile_for_variant,
    parse_haf_template,
)

_TAB_NAME_TO_VARIANT: dict[str, str] = {
    "Without LBs": "basic",
    "tLGW Load Balancer": "tlgw",
    "F5 Load Balancer": "f5",
    "HA/DR with Global Load Balancer": "hadr",
}


@dataclass(frozen=True)
class TemplateCompileResult:
    """Result of validating an uploaded multi-tab draw.io template."""

    is_valid: bool
    tab_count: int
    variant_manifest: list[dict[str, Any]] = field(default_factory=list)
    diagnostics: list[dict[str, str]] = field(default_factory=list)
    source_sha256: str = ""


class TemplateCompiler:
    """Compile/validate draw.io topology template bytes."""

    COMPILER_VERSION = "1.0.0"

    def compile(self, content: bytes, filename: str) -> TemplateCompileResult:
        diagnostics: list[dict[str, str]] = []
        source_sha256 = hashlib.sha256(content).hexdigest()

        if not content:
            return TemplateCompileResult(
                is_valid=False,
                tab_count=0,
                diagnostics=[
                    {
                        "severity": "error",
                        "code": "EMPTY_FILE",
                        "message": f"{filename} is empty",
                    }
                ],
                source_sha256=source_sha256,
            )

        try:
            root = ET.fromstring(content)
        except ET.ParseError as exc:
            return TemplateCompileResult(
                is_valid=False,
                tab_count=0,
                diagnostics=[
                    {
                        "severity": "error",
                        "code": "INVALID_XML",
                        "message": f"Failed to parse XML: {exc}",
                    }
                ],
                source_sha256=source_sha256,
            )

        if root.tag != "mxfile":
            return TemplateCompileResult(
                is_valid=False,
                tab_count=0,
                diagnostics=[
                    {
                        "severity": "error",
                        "code": "INVALID_ROOT",
                        "message": f"Expected <mxfile> root, got <{root.tag}>",
                    }
                ],
                source_sha256=source_sha256,
            )

        diagrams = root.findall("diagram")
        if len(diagrams) == 1:
            diagnostics.append(
                {
                    "severity": "warning",
                    "code": "SINGLE_TAB_TEMPLATE",
                    "message": "Template contains only one tab",
                }
            )

        variant_manifest: list[dict[str, Any]] = []
        seen_ids: set[str] = set()

        for diagram in diagrams:
            tab_name = diagram.get("name", "")
            variant = _TAB_NAME_TO_VARIANT.get(tab_name)
            graph = diagram.find("mxGraphModel")
            if graph is None and (diagram.text or "").strip():
                diagnostics.append(
                    {
                        "severity": "error",
                        "code": "COMPRESSED_DIAGRAM",
                        "message": f"Tab {tab_name!r} appears compressed",
                    }
                )
                continue

            role_names: set[str] = set()
            if graph is not None:
                for cell in graph.iter("mxCell"):
                    cell_id = cell.get("id")
                    if cell_id:
                        if cell_id in seen_ids:
                            diagnostics.append(
                                {
                                    "severity": "error",
                                    "code": "DUPLICATE_CELL_ID",
                                    "message": f"Duplicate cell id {cell_id!r} found",
                                }
                            )
                        seen_ids.add(cell_id)

                    role_attr = cell.get("haf-role", "").strip()
                    if role_attr:
                        role_names.update(role_attr.split())

            variant_manifest.append(
                {
                    "variant": variant or "unknown",
                    "tab_name": tab_name,
                    "role_count": len(role_names),
                }
            )

            if variant is None:
                diagnostics.append(
                    {
                        "severity": "warning",
                        "code": "UNKNOWN_VARIANT_TAB",
                        "message": f"Tab {tab_name!r} does not map to a known variant",
                    }
                )
                continue

            if graph is None:
                continue

            tab_diagnostics = self._validate_tab_roles(diagram=diagram, variant=variant)
            diagnostics.extend(tab_diagnostics)

        is_valid = not any(item["severity"] == "error" for item in diagnostics)
        return TemplateCompileResult(
            is_valid=is_valid,
            tab_count=len(diagrams),
            variant_manifest=variant_manifest,
            diagnostics=diagnostics,
            source_sha256=source_sha256,
        )

    def _validate_tab_roles(
        self, *, diagram: ET.Element, variant: str
    ) -> list[dict[str, str]]:
        """Validate roles in a tab against the profile for the selected variant."""
        tab_name = diagram.get("name", "")
        wrapper = ET.Element("mxfile")
        wrapper.append(ET.fromstring(ET.tostring(diagram, encoding="utf-8")))
        tab_bytes = ET.tostring(wrapper, encoding="utf-8")

        try:
            index = parse_haf_template(tab_bytes)
        except HafParseError as exc:
            return [
                {
                    "severity": "error",
                    "code": "INVALID_TAB_PARSE",
                    "message": f"Failed to parse tab {tab_name!r}: {exc}",
                }
            ]

        profile = get_profile_for_variant(variant)
        warnings = profile.validate_against_index(index)
        diagnostics: list[dict[str, str]] = []
        for warning in warnings:
            diagnostics.append(
                {
                    "severity": "warning",
                    "code": "PROFILE_ROLE_MISMATCH",
                    "message": warning.get("message", "Profile role mismatch"),
                    "haf_role": warning.get("haf_role", ""),
                    "tab_name": tab_name,
                    "variant": variant,
                }
            )
        return diagnostics
