"""Explicit, local-only preparation for the external CCPM test profile.

No source labels are interpreted, no facts are inferred, and no network or
database is used. The default CLI operation returns digest/count metadata only.
Writing a derived base requires --write and a new path inside this workspace.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import xml.etree.ElementTree as ET
from pathlib import Path

from migration_intake.topology.profiles.loader import Profile, load_profile_from_path
from migration_intake.topology.renderer.core import (
    XmlLimitExceededError,
    XmlParseError,
    find_markers_in_text,
    parse_diagram_safely,
)
from migration_intake.topology.strict_projection import StrictFactMapping

WORKSPACE = Path(__file__).absolute().parents[1]
PROFILE_PATH = WORKSPACE / "docs" / "architecture" / "ccpm-test-profile"
PROFILE_ID = "CCPM_TEST_LABEL_ONLY"
CONTROL_PAGE = "CCPM Test Controls"
CONTROL_PAGE_ID = "ccpm-test-controls"
MAX_BASE_BYTES = 10 * 1024 * 1024
CONTROL_IDS = frozenset({
    "ccpm-test-root", "ccpm-test-layer", "ccpm-test-banner",
    "ccpm-test-name", "ccpm-test-acronym",
})


class TestBasePreparationError(ValueError):
    """A source cannot be safely prepared under the bounded test contract."""


def load_test_profile() -> Profile:
    """Load external assets with manifest and component verification enabled."""
    return load_profile_from_path(PROFILE_PATH)


def fact_mappings() -> tuple[StrictFactMapping, ...]:
    """Use the existing confirmed TEXT_PAIR selectors; never infer source facts."""
    return (
        StrictFactMapping("CTL-002", "TEXT_PAIR", "application.name", "TEXT_PAIR.first"),
        StrictFactMapping("CTL-002", "TEXT_PAIR", "application.acronym", "TEXT_PAIR.second"),
    )


def prepare_test_base(source: bytes, *, expected_sha256: str) -> bytes:
    """Return a new deterministic base with one isolated test-label page.

    Existing pages are preserved as returned by the bounded parser. Its known
    empty-placeholder ID normalization and XML serialization are not byte-for-
    byte preservation; original source bytes must always be retained separately.
    """
    if not re.fullmatch(r"[0-9a-f]{64}", expected_sha256):
        raise TestBasePreparationError("Expected SHA-256 must be 64 lowercase hex characters")
    if len(source) > MAX_BASE_BYTES:
        raise TestBasePreparationError("Source exceeds the test preparation size policy")
    if hashlib.sha256(source).hexdigest() != expected_sha256:
        raise TestBasePreparationError("Source digest differs from the explicitly selected base")
    try:
        root = parse_diagram_safely(source)
    except (XmlParseError, XmlLimitExceededError):
        # Do not put private source identifiers or values into CLI diagnostics.
        raise TestBasePreparationError("Source failed bounded XML validation") from None
    pages = root.findall("./diagram")
    if any(p.get("name") == CONTROL_PAGE or p.get("id") == CONTROL_PAGE_ID for p in pages):
        raise TestBasePreparationError("Reserved test control page already exists")
    if len(pages) != 2:
        raise TestBasePreparationError("This test contract requires a two-page source")
    if any(not p.get("id") or not p.get("name") for p in pages):
        raise TestBasePreparationError("Source pages require explicit IDs and names")
    if len({p.get("id") for p in pages}) != 2 or len({p.get("name") for p in pages}) != 2:
        raise TestBasePreparationError("Source page identities must be distinct")
    if any(c.get("id") in CONTROL_IDS for c in root.iter("mxCell")):
        raise TestBasePreparationError("Reserved test cell ID collides with source")
    if any(find_markers_in_text(c.get("value", "")) for c in root.iter("mxCell")):
        raise TestBasePreparationError("Source contains markers outside the test control page")

    page = ET.SubElement(root, "diagram", {"id": CONTROL_PAGE_ID, "name": CONTROL_PAGE})
    model = ET.SubElement(page, "mxGraphModel")
    graph = ET.SubElement(model, "root")
    ET.SubElement(graph, "mxCell", {"id": "ccpm-test-root"})
    ET.SubElement(graph, "mxCell", {"id": "ccpm-test-layer", "parent": "ccpm-test-root"})
    for cell_id, label, y in (
        ("ccpm-test-banner", "TEST ONLY - NOT AN APPROVED TOPOLOGY", 20),
        ("ccpm-test-name", "Application: {{APPLICATION_NAME}}", 90),
        ("ccpm-test-acronym", "Acronym: {{APPLICATION_ACRONYM}}", 150),
    ):
        cell = ET.SubElement(graph, "mxCell", {
            "id": cell_id, "value": label, "vertex": "1", "parent": "ccpm-test-layer",
            "style": "rounded=0;whiteSpace=wrap;html=0;",
        })
        ET.SubElement(cell, "mxGeometry", {
            "x": "20", "y": str(y), "width": "480", "height": "50", "as": "geometry",
        })
    prepared = ET.tostring(root, encoding="utf-8")
    if not isinstance(prepared, bytes):
        raise TestBasePreparationError("Derived serialization must produce bytes")
    if len(prepared) > MAX_BASE_BYTES:
        raise TestBasePreparationError("Derived base exceeds the test preparation size policy")
    try:
        parse_diagram_safely(prepared)
    except (XmlParseError, XmlLimitExceededError):
        raise TestBasePreparationError("Derived base failed bounded XML validation") from None
    return prepared


def _workspace_file(path: Path) -> Path:
    """Confine a local path and reject links/reparse points at every component.

    Windows may deny the final-path handle API for otherwise readable files and
    directories. Rejecting all link components permits lexical normalization
    without relying on that API. This CLI assumes a trusted local workspace,
    not a hostile concurrent filesystem; output still uses exclusive creation.
    """
    if path.name in {"", ".", ".."}:
        raise TestBasePreparationError("A regular workspace file is required")
    # resolve() is denied on this Windows filesystem; every link is rejected below.
    checked = Path(os.path.abspath(path))  # noqa: PTH100
    workspace = Path(os.path.abspath(WORKSPACE))  # noqa: PTH100
    if not checked.is_relative_to(workspace):
        raise TestBasePreparationError(
            "Source and derived output must remain inside this workspace"
        )
    for component in (checked, *checked.parents):
        if component.is_symlink() or component.is_junction():
            raise TestBasePreparationError("A regular workspace file is required, not a link")
        try:
            info = component.lstat()
        except FileNotFoundError:
            if component != checked:
                raise
            continue  # Only a new output leaf may be absent.
        if getattr(info, "st_file_attributes", 0) & getattr(
            stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0
        ):
            raise TestBasePreparationError("Reparse paths are not allowed for local test inputs")
    return checked


def main(argv: list[str] | None = None) -> int:
    """Inspect by default; write only an explicitly requested new local file."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--expected-sha256", required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args(argv)
    if args.write != (args.output is not None):
        parser.error("--write and --output must be supplied together")
    try:
        source_path = _workspace_file(args.source)
        if source_path.stat().st_size > MAX_BASE_BYTES:
            raise TestBasePreparationError("Source exceeds the test preparation size policy")
        with source_path.open("rb") as stream:
            source = stream.read(MAX_BASE_BYTES + 1)
        prepared = prepare_test_base(source, expected_sha256=args.expected_sha256)
        profile = load_test_profile()
        if args.write:
            output_path = _workspace_file(args.output)
            # Exclusive creation also rejects the original path, hardlinks and symlinks.
            with output_path.open("xb") as stream:
                stream.write(prepared)
        print(json.dumps({
            "profile_id": profile.profile_id,
            "profile_sha256": profile.profile_hash,
            "source_sha256": hashlib.sha256(source).hexdigest(),
            "derived_sha256": hashlib.sha256(prepared).hexdigest(),
            "derived_bytes": len(prepared),
            "source_pages": 2,
            "added_test_pages": 1,
            "written": args.write,
            "test_only": True,
        }, sort_keys=True))
    except TestBasePreparationError as error:
        parser.exit(2, f"Test preparation refused: {error}\n")
    except OSError:
        parser.exit(2, "Test preparation refused: local file access or exclusive creation failed\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
