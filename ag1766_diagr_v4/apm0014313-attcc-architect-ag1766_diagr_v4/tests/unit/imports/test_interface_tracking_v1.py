from migration_intake.imports.interface_tracking_v1 import InterfaceTrackingV1Adapter


def test_interface_rows_preserve_directional_fields_and_locator() -> None:
    result = InterfaceTrackingV1Adapter().parse({
        "Interfaces": [{
            "Migrating App Correlation ID": "corr-123",
            "Interface Correlation ID": "if-001",
            "Direction": "OUTBOUND",
            "Endpoint": "vendor.example",
            "Current Protocol": "HTTPS",
            "Current Port": "443",
            "Target Protocol": "HTTPS",
            "Target Port": "443",
            "Owner Commitment": "",
        }],
    })

    assert len(result.interfaces) == 1
    assert result.interfaces[0].direction == "OUTBOUND"
    assert result.interfaces[0].source_locator == {"sheet": "Interfaces", "row": 2}
    assert any(f.finding_type == "GOVERNANCE_FIELD_MISSING" for f in result.findings)
    assert result.aggregates[0].question_code == "INT-001"
    assert result.aggregates[0].proposed_value == "IN_PROGRESS"
    assert result.aggregates[1].question_code == "INT-002"
    assert result.aggregates[1].proposed_value == "IN_PROGRESS"
    assert any(f.finding_type == "INT_003_GOVERNANCE_GAP" for f in result.findings)
    assert any(f.finding_type == "MIG_005_TEST_STATUS_GAP" for f in result.findings)


def test_incomplete_interface_does_not_create_completion_or_progress_claim() -> None:
    result = InterfaceTrackingV1Adapter().parse({
        "Interfaces": [{"Interface Correlation ID": "if-001", "Direction": "OUTBOUND"}],
    })

    assert result.aggregates == []


def test_target_protocol_or_port_supports_int_002_review_without_target_approval() -> None:
    result = InterfaceTrackingV1Adapter().parse({
        "Interfaces": [{
            "Interface Correlation ID": "if-001",
            "Direction": "OUTBOUND",
            "Endpoint": "vendor.example",
            "Current Protocol": "HTTPS",
            "Current Port": "443",
            "Target Port": "8443",
            "Connectivity Test": "PLANNED",
            "UAT": "PLANNED",
        }],
    })

    assert [candidate.question_code for candidate in result.aggregates] == ["INT-001", "INT-002"]
    assert result.interfaces[0].target_port == "8443"


def test_sample_interface_data_is_ignored() -> None:
    result = InterfaceTrackingV1Adapter().parse({"Sample Interface Data": [{"x": "y"}]})

    assert result.interfaces == []
    assert result.ignored_sheets == ["Sample Interface Data"]
    assert result.findings[0].finding_type == "IGNORED_SHEET"


def test_contact_and_scan_sheets_are_scoped_evidence_only() -> None:
    result = InterfaceTrackingV1Adapter().parse({
        "Contact & Data Impact": [{"Data Classification": "PCI"}],
        "Scan Data": [{"Endpoint": "host.example"}],
    })

    assert result.interfaces == []
    assert [f.finding_type for f in result.findings] == [
        "SCOPED_EVIDENCE_ONLY", "SCOPED_EVIDENCE_ONLY"
    ]
