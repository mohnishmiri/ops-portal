from migration_intake.imports.uaq_sheet import UAQSheetAdapter
from migration_intake.web.routes.evidence import _parse_csv_to_sheets


def test_sharepoint_uaq_csv_skips_quoted_list_schema_record() -> None:
    csv_content = (
        '"ListSchema={\\"schemaXmlList\\":[\\"<Field DisplayName=\\"\\"Metadata\\"\\" />\\"]}"\n'
        'Correlation ID,INV2-Who is the IT Application Owner\n'
        'corr-123,Alice Example\n'
    ).encode()

    sheets = _parse_csv_to_sheets(csv_content)

    assert list(sheets) == ["UAQ"]
    assert sheets["UAQ"] == [
        {
            "Correlation ID": "corr-123",
            "INV2-Who is the IT Application Owner": "Alice Example",
        }
    ]


def test_uaq_does_not_guess_question_codes_for_unmapped_inventory_fields() -> None:
    result = UAQSheetAdapter().parse(
        [{"Correlation ID": "corr-123", "INV99-New Field": "value"}]
    )

    assert result.candidates == []
    assert any(
        finding.finding_type == "UNMAPPED_FIELD"
        and finding.column == "INV99-New Field"
        for finding in result.findings
    )


def test_uaq_identity_fields_are_metadata_not_question_candidates() -> None:
    result = UAQSheetAdapter().parse(
        [{"Correlation ID": "corr-123", "App name": "Billing"}]
    )

    assert result.candidates == []
    assert result.identity["Correlation ID"] == "corr-123"
    assert result.identity["App name"] == "Billing"