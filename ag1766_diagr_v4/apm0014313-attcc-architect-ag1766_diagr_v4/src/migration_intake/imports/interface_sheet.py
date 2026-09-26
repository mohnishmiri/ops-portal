"""Deterministic adapter for the App Data Capture workbook's Interface sheet.

The Interface sheet is a directional interface register: one row per
counterpart connection for the migrating application, identified by the
pair (Migrating App Correlation ID, Interface Correlation ID). All 33
columns are captured verbatim into ``InterfaceRecord`` and become canonical
fields on the ``interfaces`` table — nothing is dropped as "raw evidence
only" (per explicit product decision; see docs/INTERFACE_REGISTER_DESIGN.md
§3).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from migration_intake.imports.interface_tracking_v1 import InterfaceRecord

INTERFACE_SHEET_MAPPING_VERSION = "app-data-capture-interface-v1"


def _header_key(value: str) -> str:
    return "".join(character for character in value.casefold() if character.isalnum())


def _value(row: dict[str, Any], *names: str) -> Any:
    """Look up a row value by header name.

    Real workbook headers often carry a parenthetical hint suffix after the
    core label (e.g. "Interface System Location\n(Mainframe, Midrange, ...)"),
    so matching is by normalized-prefix rather than exact equality.
    """
    values = {_header_key(str(key)): value for key, value in row.items()}
    for name in names:
        key = _header_key(name)
        for header_key, value in values.items():
            if header_key.startswith(key):
                return value
    return None


def _text(value: Any) -> str | None:
    """Stringify a cell value, preserving None (openpyxl may return int/float/str)."""
    return None if value is None else str(value)


@dataclass(frozen=True)
class InterfaceSheetFinding:
    finding_type: str
    severity: str
    message: str
    row_number: int | None = None


@dataclass
class InterfaceSheetResult:
    interfaces: list[InterfaceRecord] = field(default_factory=list)
    findings: list[InterfaceSheetFinding] = field(default_factory=list)


class InterfaceSheetAdapter:
    """Parse the App Data Capture workbook's Interface sheet into InterfaceRecords."""

    def parse(self, rows: list[dict[str, Any]]) -> InterfaceSheetResult:
        result = InterfaceSheetResult()
        for row_number, row in enumerate(rows, start=2):
            if not any(value not in (None, "") for value in row.values()):
                result.findings.append(InterfaceSheetFinding(
                    "BLANK_ROW", "INFO", "Blank interface row skipped", row_number,
                ))
                continue

            interface_correlation_id = _value(row, "Interface Correlation ID")
            if not interface_correlation_id:
                result.findings.append(InterfaceSheetFinding(
                    "MISSING_CORRELATION_ID", "WARNING",
                    "Row has no Interface Correlation ID and cannot be registered",
                    row_number,
                ))
                continue

            result.interfaces.append(InterfaceRecord(
                migrating_application_id=_text(_value(row, "Migrating App Correlation ID")),
                interface_correlation_id=str(interface_correlation_id),
                direction=_value(row, "Architecture Data Traffic (Inbound / Outbound)"),
                endpoint=_value(row, "End Point Name / Detail"),
                current_protocol=_value(row, "Current Protocol"),
                current_port=_text(_value(row, "Current Port")),
                target_protocol=_value(row, "Target Protocol"),
                target_port=_text(_value(row, "Future Port")),
                raw_values=dict(row),
                source_locator={"sheet": "Interface", "row": row_number},
                migrating_app_acronym=_value(row, "Migrating App Acronym"),
                consumer_or_provider=_value(row, "Consumer or Provider of Data"),
                interface_app_acronym=_value(row, "Interface Application Acronym"),
                interface_system_location=_value(row, "Interface System Location"),
                interface_migration_wave=_value(row, "Interface Migration Wave"),
                connection_owner=_value(row, "Connection Owner"),
                sync_async=_value(row, "Sync / Async", "Sync/Async"),
                current_interface_type=_value(row, "Current Interface Type"),
                target_interface_type=_value(row, "Target Interface Type"),
                interface_impact_change_type=_value(row, "Interface Impact Change Type"),
                encrypted_solution_cloud=_value(row, "Encrypted Solution for Cloud"),
                low_latency_required=_value(row, "Low Latency requirement"),
                throughput_volume_req=_value(row, "Throughput / Volume Req"),
                att_architecture_validated=_value(row, "AT&T Architecture Validated"),
                listed_in_itap=_value(row, "Listed in iTAP"),
                engagement_email_sent_on=_text(_value(row, "Engagement Email Sent on")),
                funding_template_sent=_text(
                    _value(row, "Funding Template sent to Interface")
                ),
                interface_commitment_date=_text(
                    _value(row, "Confirmed Interface Commitment Date")
                ),
                interface_included_in_crp=_value(row, "Interface included in CRP"),
                funding_approved_epic=_value(
                    row, "Interface Funding Approved and added to EPIC"
                ),
                connectivity_tested=_value(row, "Connectivity Tested Successfully"),
                uat_tested=_value(row, "UAT Tested"),
                interface_contact=_value(row, "Interface Contact"),
                interface_cutover_contact=_value(row, "Interface Cutover Support Contact"),
                notes=_value(row, "Notes"),
            ))
        return result
