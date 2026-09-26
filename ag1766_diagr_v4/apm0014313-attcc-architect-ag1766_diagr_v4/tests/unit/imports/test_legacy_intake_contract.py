"""Tests for legacy intake workbook contract inspection."""
import pytest

from migration_intake.imports.legacy_intake_contract import (
    LegacyIntakeContractError,
    LegacyIntakeContractVersion,
    inspect_legacy_intake_contract,
    is_legacy_intake_workbook,
)


class TestIsLegacyIntakeWorkbook:
    """Quick pre-check for legacy intake workbook."""

    def test_recognizes_all_seven_sheets(self) -> None:
        sheet_names = [
            "App", "iTAP", "WaveUtil", "Infra", "Database", "TSS", "Provisioning"
        ]
        assert is_legacy_intake_workbook(sheet_names) is True

    def test_rejects_missing_required_sheet(self) -> None:
        sheet_names = [
            "App", "iTAP", "WaveUtil", "Infra", "Database", "TSS"
        ]  # Missing Provisioning
        assert is_legacy_intake_workbook(sheet_names) is False

    def test_rejects_completely_different_sheets(self) -> None:
        sheet_names = ["Sheet1", "Sheet2", "Sheet3"]
        assert is_legacy_intake_workbook(sheet_names) is False

    def test_allows_extra_sheets(self) -> None:
        sheet_names = [
            "App",
            "iTAP",
            "WaveUtil",
            "Infra",
            "Database",
            "TSS",
            "Provisioning",
            "ExtraSheet",
        ]
        assert is_legacy_intake_workbook(sheet_names) is True


class TestInspectLegacyIntakeContract:
    """Full contract inspection with header validation."""

    def test_valid_v1_contract(self) -> None:
        sheet_names = ["App", "iTAP", "WaveUtil", "Infra", "Database", "TSS", "Provisioning"]
        sheet_headers = {
            "App": ("No", "Question", "Response_Type", "Response", "Allowed_Values_or_Unit"),
            "iTAP": ("Item", "Details"),
            "WaveUtil": ("Server", "Environment"),  # Variable structure, not validated
            "Infra": ("No", "Question"),
            "Database": ("No", "Question"),
            "TSS": ("No", "Question"),
            "Provisioning": ("No", "Question"),
        }

        result = inspect_legacy_intake_contract(sheet_names, sheet_headers)

        assert result == LegacyIntakeContractVersion.V1

    def test_accepts_response_type_alias_used_by_completed_workbooks(self) -> None:
        sheet_names = ["App", "iTAP", "WaveUtil", "Infra", "Database", "TSS", "Provisioning"]
        sheet_headers = {
            "App": (
                "No", "Question", "ResponseType", "Response", "Allowed_Values_or_Unit"
            ),
            "iTAP": ("Item", "Details"),
        }

        result = inspect_legacy_intake_contract(sheet_names, sheet_headers)

        assert result == LegacyIntakeContractVersion.V1

    def test_accepts_resonse_typo_used_by_completed_workbooks(self) -> None:
        sheet_names = ["App", "iTAP", "WaveUtil", "Infra", "Database", "TSS", "Provisioning"]
        sheet_headers = {
            "App": (
                "No", "Question", "Response_Type", "Resonse", "Allowed_Values_or_Unit"
            ),
            "iTAP": ("Item", "Details"),
        }

        result = inspect_legacy_intake_contract(sheet_names, sheet_headers)

        assert result == LegacyIntakeContractVersion.V1

    def test_rejects_missing_required_sheet(self) -> None:
        sheet_names = ["App", "iTAP", "WaveUtil", "Infra", "Database", "TSS"]
        sheet_headers = {
            "App": ("No", "Question", "Response_Type", "Response", "Allowed_Values_or_Unit"),
            "iTAP": ("Item", "Details"),
        }

        with pytest.raises(LegacyIntakeContractError, match="Missing required sheets"):
            inspect_legacy_intake_contract(sheet_names, sheet_headers)

    def test_rejects_wrong_app_headers(self) -> None:
        sheet_names = ["App", "iTAP", "WaveUtil", "Infra", "Database", "TSS", "Provisioning"]
        sheet_headers = {
            "App": ("Wrong", "Headers", "Here"),  # Wrong headers
            "iTAP": ("Item", "Details"),
        }

        with pytest.raises(LegacyIntakeContractError, match="unexpected headers"):
            inspect_legacy_intake_contract(sheet_names, sheet_headers)

    def test_rejects_wrong_itap_headers(self) -> None:
        sheet_names = ["App", "iTAP", "WaveUtil", "Infra", "Database", "TSS", "Provisioning"]
        sheet_headers = {
            "App": ("No", "Question", "Response_Type", "Response", "Allowed_Values_or_Unit"),
            "iTAP": ("Label", "Value"),  # Wrong headers
        }

        with pytest.raises(LegacyIntakeContractError, match="unexpected headers"):
            inspect_legacy_intake_contract(sheet_names, sheet_headers)

    def test_rejects_empty_app_sheet(self) -> None:
        sheet_names = ["App", "iTAP", "WaveUtil", "Infra", "Database", "TSS", "Provisioning"]
        sheet_headers = {
            "App": None,  # Empty sheet
            "iTAP": ("Item", "Details"),
        }

        with pytest.raises(LegacyIntakeContractError, match="is empty"):
            inspect_legacy_intake_contract(sheet_names, sheet_headers)

    def test_ignores_extra_columns_in_app_sheet(self) -> None:
        """Extra columns beyond the expected headers are allowed."""
        sheet_names = ["App", "iTAP", "WaveUtil", "Infra", "Database", "TSS", "Provisioning"]
        sheet_headers = {
            "App": (
                "No",
                "Question",
                "Response_Type",
                "Response",
                "Allowed_Values_or_Unit",
                "Extra1",
                "Extra2",
            ),
            "iTAP": ("Item", "Details", "Extra"),
        }

        result = inspect_legacy_intake_contract(sheet_names, sheet_headers)

        assert result == LegacyIntakeContractVersion.V1

    def test_normalizes_whitespace_in_headers(self) -> None:
        """Headers with extra whitespace should still match."""
        sheet_names = ["App", "iTAP", "WaveUtil", "Infra", "Database", "TSS", "Provisioning"]
        sheet_headers = {
            "App": (
                " No ", " Question ", " Response_Type ", " Response ",
                " Allowed_Values_or_Unit "
            ),
            "iTAP": (" Item ", " Details "),
        }

        result = inspect_legacy_intake_contract(sheet_names, sheet_headers)

        assert result == LegacyIntakeContractVersion.V1
