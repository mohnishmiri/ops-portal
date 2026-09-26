"""Versioned, approved topology guide policy for deterministic interface mapping."""

from __future__ import annotations

from dataclasses import dataclass

POLICY_VERSION = "1.0.0"
APPROVED_AT = "2026-09-22"
SUPPORTED_DIRECTIONS = frozenset({"INBOUND", "OUTBOUND", "BIDIRECTIONAL"})
LOCATION_ALIASES = {
    "ATT": "INTERNAL",
    "INTERNAL": "INTERNAL",
    "ON-PREM": "INTERNAL",
    "ON PREM": "INTERNAL",
    "AWS": "AWS",
    "AMAZON WEB SERVICES": "AWS",
    "AZURE": "AZURE",
    "MICROSOFT AZURE": "AZURE",
}
PROJECTION_FIELDS = (
    "id",
    "application_id",
    "interface_correlation_id",
    "interface_app_acronym",
    "interface_system_location",
    "data_traffic_direction",
    "target_protocol",
    "future_port",
    "state",
    "origin",
    "created_at",
    "created_by_id",
    "updated_at",
    "updated_by_id",
    "row_version",
)
PROHIBITED_LABEL_FIELDS = frozenset({"interface_contact", "interface_cutover_contact", "notes"})


@dataclass(frozen=True, slots=True)
class ApprovedFlow:
    """One normalized semantic flow or an explicit unresolved issue."""

    source_id: str | None
    target_id: str | None
    direction: str | None
    protocol: str | None
    port: str | None
    group: str
    issue: str | None = None

    @property
    def semantic_key(self) -> tuple[str | None, ...]:
        return (
            self.source_id,
            self.target_id,
            self.direction,
            self.protocol,
            self.port,
            self.group,
        )


def normalize_interface_flow(
    row: dict[str, object], application_id: str
) -> tuple[ApprovedFlow, ...]:
    """Apply the approved TP04 defaults without inventing missing values."""
    direction = _normalized(row.get("data_traffic_direction"))
    counterpart_id = _normalized(row.get("interface_correlation_id"))
    protocol = _normalized(row.get("target_protocol"))
    port = _normalized(row.get("future_port"))
    location = _normalized(row.get("interface_system_location"))
    group = LOCATION_ALIASES.get(location or "", "UNKNOWN")
    if direction not in SUPPORTED_DIRECTIONS:
        return (ApprovedFlow(None, None, direction, protocol, port, group, "UNKNOWN_DIRECTION"),)
    if counterpart_id is None:
        return (ApprovedFlow(None, None, direction, protocol, port, group, "MISSING_ENDPOINT_ID"),)
    if port is not None and not _valid_port(port):
        return (ApprovedFlow(None, None, direction, protocol, port, group, "INVALID_PORT"),)
    if direction == "INBOUND":
        return (ApprovedFlow(counterpart_id, application_id, direction, protocol, port, group),)
    if direction == "OUTBOUND":
        return (ApprovedFlow(application_id, counterpart_id, direction, protocol, port, group),)
    return (
        ApprovedFlow(counterpart_id, application_id, "INBOUND", protocol, port, group),
        ApprovedFlow(application_id, counterpart_id, "OUTBOUND", protocol, port, group),
    )


def _normalized(value: object) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    return value.strip().upper()


def _valid_port(value: str) -> bool:
    if "-" in value:
        parts = value.split("-", 1)
        return all(part.isdigit() and 1 <= int(part) <= 65535 for part in parts)
    return value.isdigit() and 1 <= int(value) <= 65535
