"""Deterministic adapter for the Interface Tracking FACET workbook contract."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

INTERFACE_TRACKING_MAPPING_VERSION = "interface-tracking-facet-v1"
SUPPORTED_SHEETS = frozenset(
    {"Migrating App Data", "Interfaces", "Contact & Data Impact", "Scan Data"}
)
IGNORED_SHEETS = frozenset({"Sample Interface Data", "Read Me"})


def _header_key(value: str) -> str:
    return "".join(character for character in value.casefold() if character.isalnum())


def _value(row: dict[str, Any], *names: str) -> Any:
    values = {_header_key(str(key)): value for key, value in row.items()}
    for name in names:
        if _header_key(name) in values:
            return values[_header_key(name)]
    return None


@dataclass(frozen=True)
class InterfaceTrackingFinding:
    finding_type: str
    severity: str
    message: str
    sheet: str
    row_number: int | None = None
    column: str | None = None


@dataclass(frozen=True)
class InterfaceRecord:
    migrating_application_id: str | None
    interface_correlation_id: str | None
    direction: str | None
    endpoint: str | None
    current_protocol: str | None
    current_port: str | None
    target_protocol: str | None
    target_port: str | None
    raw_values: dict[str, Any]
    source_locator: dict[str, Any]
    # Populated by the App Data Capture "Interface" sheet adapter only; the
    # Interface Tracking FACET workbook has no equivalent columns.
    migrating_app_acronym: str | None = None
    consumer_or_provider: str | None = None
    interface_app_acronym: str | None = None
    interface_system_location: str | None = None
    interface_migration_wave: str | None = None
    connection_owner: str | None = None
    sync_async: str | None = None
    current_interface_type: str | None = None
    target_interface_type: str | None = None
    interface_impact_change_type: str | None = None
    encrypted_solution_cloud: str | None = None
    low_latency_required: str | None = None
    throughput_volume_req: str | None = None
    att_architecture_validated: str | None = None
    listed_in_itap: str | None = None
    engagement_email_sent_on: str | None = None
    funding_template_sent: str | None = None
    interface_commitment_date: str | None = None
    interface_included_in_crp: str | None = None
    funding_approved_epic: str | None = None
    connectivity_tested: str | None = None
    uat_tested: str | None = None
    interface_contact: str | None = None
    interface_cutover_contact: str | None = None
    notes: str | None = None


@dataclass(frozen=True)
class InterfaceAggregateCandidate:
    question_code: str
    proposed_value: str
    source_locator: dict[str, Any]


@dataclass
class InterfaceTrackingResult:
    application_identity: dict[str, Any] = field(default_factory=dict)
    interfaces: list[InterfaceRecord] = field(default_factory=list)
    aggregates: list[InterfaceAggregateCandidate] = field(default_factory=list)
    findings: list[InterfaceTrackingFinding] = field(default_factory=list)
    ignored_sheets: list[str] = field(default_factory=list)


class InterfaceTrackingV1Adapter:
    """Parse approved Interface Tracking sheets without producing answers."""

    def parse(self, sheet_rows: dict[str, list[dict[str, Any]]]) -> InterfaceTrackingResult:
        result = InterfaceTrackingResult()
        for sheet_name, rows in sheet_rows.items():
            if sheet_name in IGNORED_SHEETS:
                result.ignored_sheets.append(sheet_name)
                result.findings.append(
                    InterfaceTrackingFinding(
                        "IGNORED_SHEET",
                        "INFO",
                        "Sheet is intentionally excluded from import",
                        sheet_name,
                    )
                )
                continue
            if sheet_name not in SUPPORTED_SHEETS:
                continue
            if sheet_name == "Migrating App Data":
                self._parse_application_data(rows, result)
            elif sheet_name == "Interfaces":
                self._parse_interfaces(rows, result)
            else:
                result.findings.append(InterfaceTrackingFinding(
                    "SCOPED_EVIDENCE_ONLY", "INFO",
                    "Sheet is retained as scoped evidence and cannot create application answers",
                    sheet_name,
                ))
        valid_interfaces = [
            interface for interface in result.interfaces if self._is_valid_interface(interface)
        ]
        if valid_interfaces:
            result.aggregates.append(InterfaceAggregateCandidate(
                question_code="INT-001",
                proposed_value="IN_PROGRESS",
                source_locator={"sheet": "Interfaces", "predicate": "valid_interface_row"},
            ))
        if any(self._has_change_detail(interface) for interface in valid_interfaces):
            result.aggregates.append(InterfaceAggregateCandidate(
                question_code="INT-002",
                proposed_value="IN_PROGRESS",
                source_locator={"sheet": "Interfaces", "predicate": "interface_change_detail"},
            ))
        if any(self._has_missing_governance_status(interface) for interface in valid_interfaces):
            result.findings.append(InterfaceTrackingFinding(
                "INT_003_GOVERNANCE_GAP",
                "WARNING",
                "Interface governance is incomplete; INT-003 cannot be completed",
                "Interfaces",
            ))
        if any(self._has_missing_test_status(interface) for interface in valid_interfaces):
            result.findings.append(InterfaceTrackingFinding(
                "MIG_005_TEST_STATUS_GAP",
                "WARNING",
                "Interface test status is incomplete; MIG-005 cannot be completed",
                "Interfaces",
            ))
        return result

    @staticmethod
    def _is_valid_interface(interface: InterfaceRecord) -> bool:
        return all((
            interface.interface_correlation_id,
            interface.direction,
            interface.endpoint,
            interface.current_protocol,
            interface.current_port,
        ))

    @staticmethod
    def _has_change_detail(interface: InterfaceRecord) -> bool:
        return any((
            interface.endpoint,
            interface.current_protocol,
            interface.current_port,
            interface.target_protocol,
            interface.target_port,
        ))

    @staticmethod
    def _has_missing_test_status(interface: InterfaceRecord) -> bool:
        return any(
            value in (None, "")
            for value in (
                _value(interface.raw_values, "Connectivity Test"),
                _value(interface.raw_values, "UAT"),
            )
        )

    @staticmethod
    def _has_missing_governance_status(interface: InterfaceRecord) -> bool:
        return any(
            value in (None, "")
            for value in (
                _value(interface.raw_values, "Owner Commitment"),
                _value(interface.raw_values, "Funding"),
                _value(interface.raw_values, "Connectivity Test"),
                _value(interface.raw_values, "UAT"),
            )
        )

    @staticmethod
    def _parse_application_data(
        rows: list[dict[str, Any]], result: InterfaceTrackingResult
    ) -> None:
        if not rows:
            result.findings.append(InterfaceTrackingFinding(
                "EMPTY_SHEET", "WARNING", "No migrating application data rows were supplied",
                "Migrating App Data",
            ))
            return
        row = rows[0]
        for label in (
            "Correlation ID", "Application Acronym", "Name", "Description",
            "Criticality", "Data Classification", "Customer Facing", "Internet Facing",
            "RTO", "RPO",
        ):
            value = _value(row, label)
            if value not in (None, ""):
                result.application_identity[label] = value

    @staticmethod
    def _parse_interfaces(
        rows: list[dict[str, Any]], result: InterfaceTrackingResult
    ) -> None:
        for row_number, row in enumerate(rows, start=2):
            if not any(value not in (None, "") for value in row.values()):
                result.findings.append(InterfaceTrackingFinding(
                    "BLANK_ROW", "INFO", "Blank interface row skipped", "Interfaces", row_number
                ))
                continue
            interface = InterfaceRecord(
                migrating_application_id=_value(
                    row, "Migrating App Correlation ID", "Correlation ID"
                ),
                interface_correlation_id=_value(row, "Interface Correlation ID", "Interface ID"),
                direction=_value(row, "Direction", "Flow Direction"),
                endpoint=_value(row, "Endpoint", "Current Endpoint", "FQDN", "Host"),
                current_protocol=_value(row, "Current Protocol", "Protocol"),
                current_port=_value(row, "Current Port", "Port"),
                target_protocol=_value(row, "Target Protocol"),
                target_port=_value(row, "Target Port"),
                raw_values=dict(row),
                source_locator={"sheet": "Interfaces", "row": row_number},
            )
            result.interfaces.append(interface)
            if any(value in (None, "") for value in (
                _value(row, "Owner Commitment"), _value(row, "Funding"),
                _value(row, "Connectivity Test"), _value(row, "UAT"),
            )):
                result.findings.append(InterfaceTrackingFinding(
                    "GOVERNANCE_FIELD_MISSING", "WARNING",
                    "Interface governance fields are incomplete; no completion is inferred",
                    "Interfaces", row_number,
                ))
