from migration_intake.imports.interface_sheet import InterfaceSheetAdapter


def test_interface_row_extracts_core_fields_and_locator() -> None:
    result = InterfaceSheetAdapter().parse([{
        "Migrating App Correlation  ID": "corr-123",
        "Migrating App Acronym": "SYN-APP",
        "Consumer or Provider of Data \n(iTAP)": "Consumer",
        "Interface Correlation  ID": "if-001",
        "Interface Application Acronym": "ORDR-SVC",
        "Interface System Location\n(Mainframe, Midrange, Azure, AWS, Conexus, Private Cloud, ect)": "Azure",
        "Architecture Data Traffic (Inbound / Outbound) \n": "Outbound",
        "Target Protocol ": "HTTPS / TLS 1.2",
        "Future Port": "8443",
    }])

    assert len(result.interfaces) == 1
    record = result.interfaces[0]
    assert record.migrating_application_id == "corr-123"
    assert record.migrating_app_acronym == "SYN-APP"
    assert record.consumer_or_provider == "Consumer"
    assert record.interface_correlation_id == "if-001"
    assert record.interface_app_acronym == "ORDR-SVC"
    assert record.interface_system_location == "Azure"
    assert record.direction == "Outbound"
    assert record.target_protocol == "HTTPS / TLS 1.2"
    assert record.target_port == "8443"
    assert record.source_locator == {"sheet": "Interface", "row": 2}
    assert result.findings == []


def test_interface_row_extracts_governance_and_contact_fields() -> None:
    result = InterfaceSheetAdapter().parse([{
        "Interface Correlation ID": "if-001",
        "Encrypted Solution for Cloud (Yes / No)": "Yes",
        "Low Latency requirement (Yes / No)": "No",
        "Throughput / Volume Req": "Low",
        "AT&T Architecture Validated (Yes / No)": "Yes",
        "Listed in iTAP (Yes / Yes-Remove, No / No-Add)": "Yes",
        "Engagement Email Sent on": "2026-01-01",
        "Funding Template sent to Interface (Date / NA)": "NA",
        "Confirmed Interface Commitment Date": "2026-02-01",
        "Interface included in CRP? (Yes - include number / No)": "No",
        "Interface Funding Approved and added to EPIC (Yes / No / NA)": "NA",
        "Connectivity Tested Successfully (Yes / No)": "Yes",
        "UAT Tested (Yes / No / NA)": "NA",
        "Interface Contact": "jane@example.com",
        "Interface Cutover Support Contact": "john@example.com",
        "Notes": "Legacy carryover",
    }])

    record = result.interfaces[0]
    assert record.encrypted_solution_cloud == "Yes"
    assert record.low_latency_required == "No"
    assert record.throughput_volume_req == "Low"
    assert record.att_architecture_validated == "Yes"
    assert record.listed_in_itap == "Yes"
    assert record.engagement_email_sent_on == "2026-01-01"
    assert record.funding_template_sent == "NA"
    assert record.interface_commitment_date == "2026-02-01"
    assert record.interface_included_in_crp == "No"
    assert record.funding_approved_epic == "NA"
    assert record.connectivity_tested == "Yes"
    assert record.uat_tested == "NA"
    assert record.interface_contact == "jane@example.com"
    assert record.interface_cutover_contact == "john@example.com"
    assert record.notes == "Legacy carryover"


def test_blank_row_is_skipped_with_finding() -> None:
    result = InterfaceSheetAdapter().parse([{"Interface Correlation ID": "", "Target Protocol": ""}])

    assert result.interfaces == []
    assert result.findings[0].finding_type == "BLANK_ROW"


def test_missing_correlation_id_is_skipped_with_finding() -> None:
    result = InterfaceSheetAdapter().parse([{
        "Interface Application Acronym": "ORDR-SVC",
        "Target Protocol": "HTTPS",
    }])

    assert result.interfaces == []
    assert result.findings[0].finding_type == "MISSING_CORRELATION_ID"


def test_raw_values_preserve_the_full_row_for_evidence() -> None:
    row = {
        "Interface Correlation ID": "if-001",
        "Current Protocol": "HTTPS",
        "Current Port": "443",
        "Notes": "Legacy carryover",
    }
    result = InterfaceSheetAdapter().parse([row])

    assert result.interfaces[0].raw_values == row
