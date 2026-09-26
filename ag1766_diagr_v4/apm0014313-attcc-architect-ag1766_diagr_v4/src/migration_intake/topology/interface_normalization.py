"""Interface normalization for HAF topology pipeline.

This module provides HAF-specific location aliases and interface grouping
for the AT&T Internal Interfaces section per Topology Guide requirements.

The HAF_LOCATION_ALIASES extends the base LOCATION_ALIASES to include
guide-required values (Midrange/Hybrid/Private/Conexus/OnPrem) that map
to INTERNAL category.

Updated 2026-09-25: Created to support grouped protocol/port rendering
for the AT&T Internal Interfaces section.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# HAF-specific location aliases that extend the base guide_policy LOCATION_ALIASES
# to include guide-required values for the AT&T Internal Interfaces section.
HAF_LOCATION_ALIASES: dict[str, str] = {
    # Base aliases from guide_policy
    "ATT": "INTERNAL",
    "INTERNAL": "INTERNAL",
    "ON-PREM": "INTERNAL",
    "ON PREM": "INTERNAL",
    "AWS": "AWS",
    "AMAZON WEB SERVICES": "AWS",
    "AZURE": "AZURE",
    "MICROSOFT AZURE": "AZURE",
    # HAF-specific additions for guide requirements
    "MIDRANGE": "INTERNAL",
    "HYBRID": "INTERNAL",
    "PRIVATE": "INTERNAL",
    "CONEXUS": "INTERNAL",
    "ONPREM": "INTERNAL",
    "ON_PREM": "INTERNAL",
    "GPN": "INTERNAL",
    # Form datalist values and real-world variants
    "MAINFRAME": "INTERNAL",
    "PRIVATE CLOUD": "INTERNAL",
    "ON-PREMISES": "INTERNAL",
    "DATA CENTER": "INTERNAL",
    "DATACENTER": "INTERNAL",
    "TIER2": "TIER2_INTERNET",
    "TIER 2": "TIER2_INTERNET",
    "INTERNET": "TIER2_INTERNET",
}

# Supported direction values
SUPPORTED_DIRECTIONS = frozenset({"INBOUND", "OUTBOUND", "BIDIRECTIONAL", "IN", "OUT", "IN_OUT"})

# Direction normalization mapping
DIRECTION_ALIASES: dict[str, str] = {
    "INBOUND": "INBOUND",
    "IN": "INBOUND",
    "OUTBOUND": "OUTBOUND",
    "OUT": "OUTBOUND",
    "BIDIRECTIONAL": "BIDIRECTIONAL",
    "IN_OUT": "BIDIRECTIONAL",
    "IN/OUT": "BIDIRECTIONAL",
    "BOTH": "BIDIRECTIONAL",
}

# Protocol family patterns for grouped rendering.
# Ordered from most-specific to least-specific; first regex match wins.
# "GOLDENGATE" must match before generic "ORACLE" patterns.
PROTOCOL_FAMILY_PATTERNS: list[tuple[str, str]] = [
    (r"GOLDENGATE|GOLDEN[\s._-]?GATE", "ORACLE_GG"),
    (r"DATA[\s._-]?GUARD", "DATAGUARD"),
    (r"JDBC|ORACLE[\s._-]?NET|ORACLE[\s._-]?NATIVE", "ORACLE_DB"),
    (r"ODBC|SQL[\s._-]?SERVER", "SQL_DB"),
    (r"CONNECT[\s._:/-]?DIRECT", "CONNECT_DIRECT"),
    (r"POSTGRES", "POSTGRESQL"),
    (r"AMQP", "AMQP"),
    (r"SMTP", "SMTP"),
    (r"SFTP|SSH", "SFTP"),
    (r"HTTPS|HTTP", "HTTPS"),
]

# Protocol family → connector hex color for diagram rendering.
FAMILY_COLORS: dict[str, str] = {
    "HTTPS": "#6666FF",
    "ORACLE_DB": "#67AB9F",
    "ORACLE_GG": "#99004D",
    "SQL_DB": "#FF9933",
    "CONNECT_DIRECT": "#CC0000",
    "SFTP": "#00CC66",
    "SMTP": "#CC0000",
    "DATAGUARD": "#CCCC00",
    "AMQP": "#9933CC",
    "POSTGRESQL": "#336791",
    "OTHER": "#666666",
    "UNKNOWN": "#999999",
}


def normalize_protocol_family(protocol: str | None) -> str:
    """Normalize a raw protocol string to a protocol family key.

    Uses ordered regex matching against PROTOCOL_FAMILY_PATTERNS.
    First match wins.

    Args:
        protocol: Raw protocol value (e.g., "HTTPS(TLSv1.2)").

    Returns:
        Family key: "HTTPS", "ORACLE_DB", "ORACLE_GG", "SQL_DB",
        "CONNECT_DIRECT", "SFTP", "AMQP", "POSTGRESQL", "OTHER",
        or "UNKNOWN" for null/empty input.
    """
    if not protocol:
        return "UNKNOWN"
    upper = protocol.strip().upper()
    if not upper:
        return "UNKNOWN"
    for pattern, family in PROTOCOL_FAMILY_PATTERNS:
        if re.search(pattern, upper):
            return family
    return "OTHER"


@dataclass
class InterfaceCandidate:
    """A normalized interface candidate for rendering.

    Attributes:
        interface_system_location: Raw location value from DB.
        data_traffic_direction: Raw direction value from DB.
        target_protocol: Protocol (e.g., HTTPS, SSH, JDBC).
        future_port: Port number or range.
        interface_app_acronym: Application acronym.
        interface_correlation_id: Correlation ID.
        norm_category: Normalized category (INTERNAL, AWS, AZURE, UNKNOWN).
        norm_direction: Normalized direction (INBOUND, OUTBOUND, BIDIRECTIONAL, UNKNOWN).
        norm_protocol: Normalized protocol.
        norm_port: Normalized port.
        raw_location: Alias for interface_system_location (for test compatibility).
        raw_direction: Alias for data_traffic_direction (for test compatibility).
        raw_protocol: Alias for target_protocol (for test compatibility).
        raw_port: Alias for future_port (for test compatibility).
        display_label: Formatted display label for rendering.
    """

    interface_system_location: str | None = None
    data_traffic_direction: str | None = None
    target_protocol: str | None = None
    future_port: str | None = None
    interface_app_acronym: str | None = None
    interface_correlation_id: str | None = None
    norm_category: str = "UNKNOWN"
    norm_direction: str = "UNKNOWN"
    norm_protocol: str = ""
    norm_port: str = ""
    # Aliases for test compatibility
    raw_location: str | None = None
    raw_direction: str | None = None
    raw_protocol: str | None = None
    raw_port: str | None = None
    display_label: str = ""


@dataclass
class InterfaceGroup:
    """A group of interfaces with the same protocol/port combination.

    Used for grouped rendering in interface sections.

    Attributes:
        protocol: The protocol (e.g., HTTPS, SSH).
        port: The port number or range.
        direction: The direction (INBOUND, OUTBOUND, BIDIRECTIONAL).
        entries: List of (app_acronym, correlation_id) tuples.
        entries_inbound: List of InterfaceCandidate for inbound direction.
        entries_outbound: List of InterfaceCandidate for outbound direction.
        entries_bidirectional: List of InterfaceCandidate for bidirectional.
        category: The category (INTERNAL, AWS, AZURE).
    """

    protocol: str
    port: str
    direction: str = ""
    entries: list[tuple[str, str]] = field(default_factory=list)
    entries_inbound: list["InterfaceCandidate"] = field(default_factory=list)
    entries_outbound: list["InterfaceCandidate"] = field(default_factory=list)
    entries_bidirectional: list["InterfaceCandidate"] = field(default_factory=list)
    category: str = "INTERNAL"

    @property
    def display_key(self) -> str:
        """Return a display key for this group (e.g., 'HTTPS 443')."""
        if self.port:
            return f"{self.protocol} {self.port}"
        return self.protocol

    @property
    def sort_key(self) -> tuple[str, str, str]:
        """Return a sort key for deterministic ordering."""
        return (self.protocol, self.port, self.direction)

    @property
    def all_entries(self) -> list["InterfaceCandidate"]:
        """Return all entries across all directions."""
        return self.entries_inbound + self.entries_outbound + self.entries_bidirectional


def _aggregate_direction(candidates: list[InterfaceCandidate]) -> str:
    """Aggregate direction across a set of candidates.

    Returns:
        "IN" if all inbound, "OUT" if all outbound, "IN/OUT" if mixed
        or any bidirectional, "?" if no recognized direction.
    """
    directions = {c.norm_direction for c in candidates}
    has_in = "INBOUND" in directions
    has_out = "OUTBOUND" in directions
    has_bidir = "BIDIRECTIONAL" in directions

    if has_bidir or (has_in and has_out):
        return "IN/OUT"
    if has_in:
        return "IN"
    if has_out:
        return "OUT"
    return "?"


@dataclass
class ProtocolFamilyGroup:
    """A group of interfaces sharing the same protocol family.

    All ports for the family are merged into one row. Direction is aggregated.
    Application labels are deduplicated and comma-separated.
    """

    family: str
    candidates: list[InterfaceCandidate] = field(default_factory=list)

    # Computed on finalize():
    ports: list[str] = field(default_factory=list)
    direction: str = "?"
    labels: list[str] = field(default_factory=list)
    connector_color: str = "#000000"

    def add_candidate(self, candidate: InterfaceCandidate) -> None:
        self.candidates.append(candidate)

    def finalize(self) -> None:
        """Compute derived fields after all candidates are added."""
        # Ports: unique, sorted numerically
        raw_ports = {c.norm_port for c in self.candidates if c.norm_port}
        self.ports = sorted(
            raw_ports,
            key=lambda p: (int(p) if p.isdigit() else 99999, p),
        )

        # Direction: aggregated
        self.direction = _aggregate_direction(self.candidates)

        # Labels: deduplicated (app, corr_id), sorted alphabetically
        seen: set[tuple[str, str]] = set()
        labels: list[str] = []
        for c in sorted(
            self.candidates,
            key=lambda c: (
                c.interface_app_acronym or "",
                c.interface_correlation_id or "",
            ),
        ):
            pair = (
                c.interface_app_acronym or "UNKNOWN",
                c.interface_correlation_id or "?",
            )
            if pair not in seen:
                seen.add(pair)
                labels.append(f"{pair[0]} ({pair[1]})")
        self.labels = labels

        # Connector color from family
        self.connector_color = FAMILY_COLORS.get(self.family, "#000000")

    @property
    def port_display(self) -> str:
        """E.g., '443 8447' or '1521' or '?'."""
        return " ".join(self.ports) if self.ports else "?"

    @property
    def label_display(self) -> str:
        """Comma-separated: 'APP1 (ID1), APP2 (ID2), ...'."""
        return ", ".join(self.labels)

    @property
    def direction_display(self) -> str:
        return self.direction

    @property
    def sort_key(self) -> tuple[str, int]:
        """Deterministic sort: family name, then lowest port number."""
        min_port = min(
            (int(p) for p in self.ports if p.isdigit()), default=99999
        )
        return (self.family, min_port)


@dataclass
class NormalizationReport:
    """Report of interface normalization results.

    Attributes:
        total_interfaces: Total number of interfaces processed.
        total_processed: Alias for total_interfaces (for test compatibility).
        by_category: Count by normalized category.
        by_direction: Count by normalized direction.
        unknown_locations: List of unrecognized location values.
        unknown_directions: List of unrecognized direction values.
        groups_created: Number of protocol/port groups created.
        internal_valid: Count of valid INTERNAL category interfaces.
        excluded_by_category: Count of interfaces excluded by category filter.
    """

    total_interfaces: int = 0
    by_category: dict[str, int] = field(default_factory=dict)
    by_direction: dict[str, int] = field(default_factory=dict)
    unknown_locations: list[str] = field(default_factory=list)
    unknown_directions: list[str] = field(default_factory=list)
    groups_created: int = 0
    excluded_by_category: int = 0

    @property
    def total_processed(self) -> int:
        """Alias for total_interfaces."""
        return self.total_interfaces

    @property
    def internal_valid(self) -> int:
        """Count of valid INTERNAL category interfaces."""
        return self.by_category.get("INTERNAL", 0)

    def add_candidate(self, candidate: InterfaceCandidate) -> None:
        """Add a candidate to the report statistics."""
        self.total_interfaces += 1
        self.by_category[candidate.norm_category] = (
            self.by_category.get(candidate.norm_category, 0) + 1
        )
        self.by_direction[candidate.norm_direction] = (
            self.by_direction.get(candidate.norm_direction, 0) + 1
        )
        if candidate.norm_category == "UNKNOWN" and candidate.interface_system_location:
            if candidate.interface_system_location not in self.unknown_locations:
                self.unknown_locations.append(candidate.interface_system_location)
        if candidate.norm_direction == "UNKNOWN" and candidate.data_traffic_direction:
            if candidate.data_traffic_direction not in self.unknown_directions:
                self.unknown_directions.append(candidate.data_traffic_direction)

    def log_summary(self) -> None:
        """Log a summary of the normalization results."""
        logger.info(
            "Interface normalization: %d total, categories=%s, directions=%s, "
            "groups=%d, unknown_locations=%s, unknown_directions=%s",
            self.total_interfaces,
            self.by_category,
            self.by_direction,
            self.groups_created,
            self.unknown_locations,
            self.unknown_directions,
        )


def normalize_location(raw: str | None) -> str:
    """Normalize a location value to a category.

    Args:
        raw: Raw location value from DB.

    Returns:
        Normalized category (INTERNAL, AWS, AZURE, TIER2_INTERNET, UNKNOWN).
    """
    if not raw:
        return "UNKNOWN"
    normalized = raw.strip().upper()
    return HAF_LOCATION_ALIASES.get(normalized, "UNKNOWN")


def normalize_direction(raw: str | None) -> str:
    """Normalize a direction value.

    Args:
        raw: Raw direction value from DB.

    Returns:
        Normalized direction (INBOUND, OUTBOUND, BIDIRECTIONAL, UNKNOWN).
    """
    if not raw:
        return "UNKNOWN"
    normalized = raw.strip().upper()
    return DIRECTION_ALIASES.get(normalized, "UNKNOWN")


def normalize_protocol(raw: str | None) -> str:
    """Normalize a protocol value.

    Args:
        raw: Raw protocol value from DB.

    Returns:
        Normalized protocol (uppercase, trimmed).
    """
    if not raw:
        return ""
    return raw.strip().upper()


def normalize_port(raw: str | None) -> str:
    """Normalize a port value.

    Args:
        raw: Raw port value from DB.

    Returns:
        Normalized port (trimmed).
    """
    if not raw:
        return ""
    return raw.strip()


def create_interface_candidate(
    interface_system_location: str | None = None,
    data_traffic_direction: str | None = None,
    target_protocol: str | None = None,
    future_port: str | None = None,
    interface_app_acronym: str | None = None,
    interface_correlation_id: str | None = None,
) -> InterfaceCandidate:
    """Create a normalized InterfaceCandidate from raw DB values.

    Args:
        interface_system_location: Raw location value.
        data_traffic_direction: Raw direction value.
        target_protocol: Protocol value.
        future_port: Port value.
        interface_app_acronym: Application acronym.
        interface_correlation_id: Correlation ID.

    Returns:
        InterfaceCandidate with normalized values.
    """
    return InterfaceCandidate(
        interface_system_location=interface_system_location,
        data_traffic_direction=data_traffic_direction,
        target_protocol=target_protocol,
        future_port=future_port,
        interface_app_acronym=interface_app_acronym,
        interface_correlation_id=interface_correlation_id,
        norm_category=normalize_location(interface_system_location),
        norm_direction=normalize_direction(data_traffic_direction),
        norm_protocol=normalize_protocol(target_protocol),
        norm_port=normalize_port(future_port),
    )


def group_interfaces_by_protocol_port(
    candidates: list[InterfaceCandidate],
    category_filter: str | None = "INTERNAL",
) -> list[InterfaceGroup]:
    """Group interfaces by protocol/port for rendering.

    Groups interfaces with the same protocol and port together for
    the AT&T Internal Interfaces section rendering.

    Args:
        candidates: List of InterfaceCandidate objects.
        category_filter: Only include candidates with this category.
            If None, include all categories.

    Returns:
        List of InterfaceGroup objects, sorted deterministically.
    """
    groups: dict[tuple[str, str], InterfaceGroup] = {}

    for candidate in candidates:
        # Filter by category if specified
        if category_filter and candidate.norm_category != category_filter:
            continue

        # Group by protocol/port only (not direction)
        key = (candidate.norm_protocol, candidate.norm_port)
        if key not in groups:
            groups[key] = InterfaceGroup(
                protocol=candidate.norm_protocol,
                port=candidate.norm_port,
                category=candidate.norm_category,
            )

        # Add entry to tuple list (app_acronym, correlation_id)
        entry = (
            candidate.interface_app_acronym or "",
            candidate.interface_correlation_id or "",
        )
        if entry not in groups[key].entries:
            groups[key].entries.append(entry)

        # Also add to direction-specific lists (InterfaceCandidate objects)
        if candidate.norm_direction == "INBOUND":
            if candidate not in groups[key].entries_inbound:
                groups[key].entries_inbound.append(candidate)
        elif candidate.norm_direction == "OUTBOUND":
            if candidate not in groups[key].entries_outbound:
                groups[key].entries_outbound.append(candidate)
        elif candidate.norm_direction == "BIDIRECTIONAL":
            if candidate not in groups[key].entries_bidirectional:
                groups[key].entries_bidirectional.append(candidate)

    # Sort groups deterministically
    result = sorted(groups.values(), key=lambda g: g.sort_key)

    # Sort entries within each group
    for group in result:
        group.entries.sort()
        group.entries_inbound.sort(key=lambda c: (c.interface_app_acronym or "", c.interface_correlation_id or ""))
        group.entries_outbound.sort(key=lambda c: (c.interface_app_acronym or "", c.interface_correlation_id or ""))
        group.entries_bidirectional.sort(key=lambda c: (c.interface_app_acronym or "", c.interface_correlation_id or ""))

    return result


def group_interfaces_by_protocol_family(
    candidates: list[InterfaceCandidate],
    category_filter: str | None = "INTERNAL",
    direction_filter: frozenset[str] | None = None,
) -> list[ProtocolFamilyGroup]:
    """Group interfaces by protocol family for grouped rendering.

    Supplements (does not replace) group_interfaces_by_protocol_port().
    Merges all ports of the same protocol family into one row.
    Incomplete records (missing protocol or port) go to an UNKNOWN group.

    Args:
        candidates: List of InterfaceCandidate objects.
        category_filter: Only include candidates with this category.
            If None, include all categories.
        direction_filter: Only include candidates whose norm_direction
            is in this set.  If None, include all directions.

    Returns:
        Sorted list of ProtocolFamilyGroup objects, finalized and ready
        for rendering.
    """
    # Step 1: Filter to target category and direction
    filtered = [
        c
        for c in candidates
        if (category_filter is None or c.norm_category == category_filter)
        and (direction_filter is None or c.norm_direction in direction_filter)
    ]

    if not filtered:
        return []

    # Step 2: Separate complete vs incomplete
    complete: list[InterfaceCandidate] = []
    incomplete: list[InterfaceCandidate] = []
    for c in filtered:
        family = normalize_protocol_family(c.norm_protocol)
        if c.norm_port and family not in ("UNKNOWN",):
            complete.append(c)
        else:
            incomplete.append(c)

    # Step 3: Group complete records by protocol family
    groups: dict[str, ProtocolFamilyGroup] = {}
    for candidate in complete:
        family = normalize_protocol_family(candidate.norm_protocol)
        if family not in groups:
            groups[family] = ProtocolFamilyGroup(family=family)
        groups[family].add_candidate(candidate)

    # Step 4: Build Unknown group for incomplete records
    if incomplete:
        if "UNKNOWN" not in groups:
            groups["UNKNOWN"] = ProtocolFamilyGroup(family="UNKNOWN")
        for candidate in incomplete:
            groups["UNKNOWN"].add_candidate(candidate)

    # Step 5: Finalize each group and sort deterministically
    for group in groups.values():
        group.finalize()

    # UNKNOWN always last; others sorted by (family, min_port)
    non_unknown = sorted(
        (g for g in groups.values() if g.family != "UNKNOWN"),
        key=lambda g: g.sort_key,
    )
    unknown = [g for g in groups.values() if g.family == "UNKNOWN"]
    return non_unknown + unknown
