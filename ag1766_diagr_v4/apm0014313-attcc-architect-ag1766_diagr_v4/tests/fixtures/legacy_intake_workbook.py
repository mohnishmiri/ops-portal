"""
Synthetic legacy intake workbook fixture builder.

Creates test workbooks matching the APP_DATA_CAPTURE_LEGACY_V1 contract
without using private client data.
"""
from __future__ import annotations

from io import BytesIO
from typing import Any

from openpyxl import Workbook
from openpyxl.styles import Font


def build_legacy_intake_workbook(
    *,
    correlation_id: str | None = None,
    mots_id: str | None = None,
    itap_id: str | None = None,
    app_name: str = "Test Application",
    app_acronym: str = "TESTAPP",
    include_all_sheets: bool = True,
) -> bytes:
    """
    Build a synthetic seven-sheet legacy intake workbook.

    Args:
        correlation_id: Correlation ID to embed (in App Q1 and iTAP sheet).
        mots_id: MOTS ID to embed (in App Q1 if correlation_id is None).
        itap_id: iTAP ID to embed (in iTAP sheet APM Number).
        app_name: Application name.
        app_acronym: Application acronym.
        include_all_sheets: If True, create all 7 sheets; if False, only App and iTAP.

    Returns:
        Workbook bytes in .xlsx format.
    """
    wb = Workbook()

    # Remove default sheet
    if "Sheet" in wb.sheetnames:
        wb.remove(wb["Sheet"])

    # ── Sheet 1: App ──────────────────────────────────────────────────────
    app_sheet = wb.create_sheet("App")
    app_sheet.append(["No", "Question", "Response_Type", "Response", "Allowed_Values_or_Unit"])
    for cell in app_sheet[1]:
        cell.font = Font(bold=True)

    # Q1: Correlation or MOTS ID
    identifier_response = ""
    if correlation_id:
        identifier_response = correlation_id
    elif mots_id:
        identifier_response = mots_id

    app_sheet.append([
        "1",
        "What is the application correlation or MOTS ID?",
        "IDENTIFIER",
        identifier_response,
        "",
    ])

    # Q2: Name and acronym
    app_sheet.append([
        "2",
        "What are the approved application name and acronym?",
        "TEXT_PAIR",
        f"{app_name}|{app_acronym}",
        "",
    ])

    # Q3-Q10: Additional questions (blank for now)
    questions = [
        ("3", "What deliverables are required for this intake?", "MULTI_SELECT", "", "TOPOLOGY|ADS|DDD"),
        ("4", "What business function does the application provide?", "LONG_TEXT", "", ""),
        ("5", "Who are the IT application owner and primary technical contacts?", "PEOPLE_LIST", "", ""),
        ("6", "What is the current operational status?", "SINGLE_SELECT", "", "ACTIVE|MAINTENANCE|RETIRING|RETIRED|UNKNOWN"),
        ("7", "What are the business criticality and emergency tier?", "CONTROLLED_PAIR", "", ""),
        ("8", "What is the data classification?", "SINGLE_SELECT", "", ""),
        ("9", "What is the customer impact?", "SINGLE_SELECT", "", ""),
        ("10", "Is the application customer facing?", "BOOLEAN", "", "YES|NO|UNKNOWN"),
    ]

    for q in questions:
        app_sheet.append(list(q))

    # ── Sheet 2: iTAP ─────────────────────────────────────────────────────
    itap_sheet = wb.create_sheet("iTAP")
    itap_sheet.append(["Item", "Details"])
    for cell in itap_sheet[1]:
        cell.font = Font(bold=True)

    # iTAP identity fields
    itap_items = [
        ("Application acronym", app_acronym),
        ("Application name", app_name),
        ("APM Number", itap_id or ""),
        ("Correlation ID", correlation_id or ""),
        ("Emergency tier", ""),
        ("Business criticality", ""),
        ("PCI data", ""),
        ("PCI data stored", ""),
        ("PCI assessment", ""),
        ("SOX/FSA in-scope", ""),
        ("DR Priority", ""),
        ("DR RTO", ""),
        ("DR RPO", ""),
        ("OR Priority", ""),
        ("OR RTO", ""),
        ("OR RPO", ""),
    ]

    for item, details in itap_items:
        itap_sheet.append([item, details])

    if include_all_sheets:
        # ── Sheet 3: WaveUtil ─────────────────────────────────────────────
        wave_sheet = wb.create_sheet("WaveUtil")
        wave_sheet.append(["Server Name", "Environment", "Scope", "CPU", "Memory"])
        for cell in wave_sheet[1]:
            cell.font = Font(bold=True)

        # ── Sheet 4: Infra ────────────────────────────────────────────────
        infra_sheet = wb.create_sheet("Infra")
        infra_sheet.append(["No", "Question", "Response_Type", "Response", "Allowed_Values"])
        for cell in infra_sheet[1]:
            cell.font = Font(bold=True)

        # ── Sheet 5: Database ─────────────────────────────────────────────
        db_sheet = wb.create_sheet("Database")
        db_sheet.append(["No", "Question", "Response_Type", "Response", "Allowed_Values"])
        for cell in db_sheet[1]:
            cell.font = Font(bold=True)

        # ── Sheet 6: TSS ──────────────────────────────────────────────────
        tss_sheet = wb.create_sheet("TSS")
        tss_sheet.append(["No", "Question", "Response_Type", "Response", "Allowed_Values"])
        for cell in tss_sheet[1]:
            cell.font = Font(bold=True)

        # ── Sheet 7: Provisioning ─────────────────────────────────────────
        prov_sheet = wb.create_sheet("Provisioning")
        prov_sheet.append(["No", "Question", "Response_Type", "Response", "Allowed_Values"])
        for cell in prov_sheet[1]:
            cell.font = Font(bold=True)

    # Save to bytes
    buffer = BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


def build_legacy_workbook_with_conflicting_ids(
    correlation_in_app: str,
    correlation_in_itap: str,
) -> bytes:
    """
    Build a workbook with conflicting Correlation IDs across sheets.

    This should be rejected by the identity resolver.
    """
    wb = Workbook()
    if "Sheet" in wb.sheetnames:
        wb.remove(wb["Sheet"])

    # App sheet with one Correlation ID
    app_sheet = wb.create_sheet("App")
    app_sheet.append(["No", "Question", "Response_Type", "Response", "Allowed_Values_or_Unit"])
    app_sheet.append([
        "1",
        "What is the application correlation or MOTS ID?",
        "IDENTIFIER",
        correlation_in_app,
        "",
    ])

    # iTAP sheet with a different Correlation ID
    itap_sheet = wb.create_sheet("iTAP")
    itap_sheet.append(["Item", "Details"])
    itap_sheet.append(["Correlation ID", correlation_in_itap])

    buffer = BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


def build_legacy_workbook_with_multiple_ids(
    correlation_id: str,
    mots_id: str,
    itap_id: str,
) -> bytes:
    """
    Build a workbook with all three ID types present.

    Should use Correlation as the primary match key.
    """
    return build_legacy_intake_workbook(
        correlation_id=correlation_id,
        mots_id=mots_id,
        itap_id=itap_id,
        include_all_sheets=True,
    )
