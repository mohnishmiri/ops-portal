"""Template loader — extract tabs from multi-tab draw.io master templates."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path
from typing import TYPE_CHECKING

from sqlalchemy.orm import sessionmaker

from migration_intake.persistence.repositories.templates import TemplateRepository
from migration_intake.storage.filesystem import FilesystemStore

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

def list_tabs(template_bytes: bytes) -> list[dict[str, str | int]]:
    """Enumerate diagram tabs in a multi-tab ``.drawio`` (mxfile) document.

    Returns a list of ``{"index": int, "name": str}`` dicts, one per
    ``<diagram>`` element.

    Raises ``ValueError`` for non-mxfile XML.
    """
    root = ET.fromstring(template_bytes)
    if root.tag != "mxfile":
        raise ValueError(f"Root element <{root.tag}> is not a valid mxfile")
    return [
        {"index": i, "name": d.get("name", "")}
        for i, d in enumerate(root.findall("diagram"))
    ]


def extract_tab(
    template_bytes: bytes,
    *,
    tab_name: str | None = None,
    tab_index: int | None = None,
) -> bytes:
    """Extract a single diagram tab from a multi-tab ``.drawio`` file.

    Provide exactly one of *tab_name* or *tab_index*.  Returns a valid
    single-diagram mxfile as ``bytes`` with the original ``<mxfile>``
    attributes preserved.

    Raises ``ValueError`` for missing tab, out-of-range index,
    or ambiguous arguments.
    """
    if (tab_name is None) == (tab_index is None):
        raise ValueError("Provide exactly one of tab_name or tab_index")

    root = ET.fromstring(template_bytes)
    if root.tag != "mxfile":
        raise ValueError(f"Root element <{root.tag}> is not a valid mxfile")

    diagrams = root.findall("diagram")

    if tab_name is not None:
        matches = [d for d in diagrams if d.get("name") == tab_name]
        if not matches:
            raise ValueError(f"Tab '{tab_name}' not found")
        selected = matches[0]
    else:
        assert tab_index is not None
        if tab_index < 0 or tab_index >= len(diagrams):
            raise ValueError(
                f"Tab index {tab_index} out of range (0..{len(diagrams) - 1})"
            )
        selected = diagrams[tab_index]

    new_root = ET.Element("mxfile", root.attrib)
    new_root.append(selected)
    return ET.tostring(new_root, encoding="unicode", xml_declaration=False).encode("utf-8")


_BUNDLED_TEMPLATE = (
    Path(__file__).resolve().parent / "config" / "templates" / "outpost_v1.7.drawio"
)

# Maps variant key → tab name in the bundled multi-tab template.
_VARIANT_TAB_MAP: dict[str, str] = {
    "basic": "Without LBs",
    "tlgw": "tLGW Load Balancer",
    "f5": "F5 Load Balancer",
    "hadr": "HA/DR with Global Load Balancer",
}


def load_bundled_template(variant: str) -> bytes:
    """Load an annotated tab from the bundled multi-tab master template.

    Args:
        variant: Variant key (``"basic"``, ``"tlgw"``, ``"f5"``, ``"hadr"``).

    Returns:
        Single-diagram mxfile XML bytes with haf-role annotations.

    Raises:
        HafProfileError: If the variant is unknown.
        FileNotFoundError: If the bundled template is missing.
    """
    tab_name = _VARIANT_TAB_MAP.get(variant)
    if tab_name is None:
        from migration_intake.topology.haf_pipeline import HafProfileError

        raise HafProfileError(
            f"Unknown variant {variant!r}. "
            f"Valid variants: {sorted(_VARIANT_TAB_MAP)}"
        )
    return extract_tab(_BUNDLED_TEMPLATE.read_bytes(), tab_name=tab_name)


def resolve_template(
    variant: str,
    *,
    session_factory: sessionmaker[Session] | None = None,
    storage: FilesystemStore | None = None,
) -> tuple[bytes, str]:
    """Resolve the template bytes for a variant.

    Priority order:
    1. Latest published template in the DB-backed release registry.
    2. Bundled template shipped with the application.

    Returns:
        Tuple ``(template_bytes, source_label)`` where source_label is either
        a release UUID or the constant ``"bundled_fallback"``.
    """
    tab_name = _VARIANT_TAB_MAP.get(variant)
    if tab_name is None:
        from migration_intake.topology.haf_pipeline import HafProfileError

        raise HafProfileError(
            f"Unknown variant {variant!r}. "
            f"Valid variants: {sorted(_VARIANT_TAB_MAP)}"
        )

    if session_factory is not None and storage is not None:
        session = session_factory()
        try:
            release = TemplateRepository(session).get_latest_published_release()
            if release is not None:
                with storage.retrieve(release["content_address"]) as stream:
                    template_bytes = stream.read()
                return extract_tab(template_bytes, tab_name=tab_name), release["id"]
        finally:
            session.close()

    return load_bundled_template(variant), "bundled_fallback"
