"""
Provisioning reference sheet adapter (B04).

Parses rows from the Provisioning worksheet of the APP_DATA_CAPTURE_V1
workbook into typed ProvisioningCandidate objects (section 14.3).

Key design constraints (section 14.4 — Reference-data trap):
- All candidates carry is_reference_data=True.
- The adapter NEVER auto-selects a target site for any application.
- An explicit architect command is required to adopt a row as target placement.
- Real-looking values in the template are never assumed to apply to the
  uploaded application.

Findings raised:
- BLANK_ROW: tracked internally but NOT emitted (rows silently discarded).
- INCOMPLETE_ROW: required fields (dc_code, aws_region) are empty.
- INVALID_REGION: aws_region does not match the AWS region regex.
- DUPLICATE_MAPPING: the (dc_code, aws_region) pair has already been seen.
- CONTRADICTORY_MAPPING: the same dc_code appears with a different aws_region.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum

# ---------------------------------------------------------------------------
# Column contract
# ---------------------------------------------------------------------------

PROVISIONING_COLUMNS: list[str] = [
    "Physical Location",
    "Data Center Code",
    "Data Center Name",
    "AWS Region",
    "Region Display",
    "CLLI",
    "Outpost ID",
    "Availability Zone",
    "Replication Target",
]

#: Fields whose absence (empty string) makes a row INCOMPLETE.
_REQUIRED_FIELDS: tuple[str, ...] = ("Data Center Code", "AWS Region")

#: AWS region pattern: two lowercase letters, a dash, a word, a dash, a digit.
#: Examples: us-east-1, eu-west-2, ap-southeast-1, ca-central-1.
AWS_REGION_PATTERN: re.Pattern[str] = re.compile(r"^[a-z]{2}-[a-z]+-\d+$")


# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------


class ProvisioningFindingType(str, Enum):
    """Classification of a finding raised during Provisioning sheet parsing."""

    INCOMPLETE_ROW = "INCOMPLETE_ROW"
    INVALID_REGION = "INVALID_REGION"
    DUPLICATE_MAPPING = "DUPLICATE_MAPPING"
    CONTRADICTORY_MAPPING = "CONTRADICTORY_MAPPING"
    BLANK_ROW = "BLANK_ROW"


@dataclass(frozen=True)
class ProvisioningCandidate:
    """
    A reference-data candidate extracted from a single Provisioning row.

    is_reference_data is always True; this is master-data candidate input,
    not per-application truth (section 14.4).
    """

    row_number: int
    physical_location: str
    dc_code: str
    dc_name: str
    aws_region: str
    region_display: str
    clli: str
    outpost_id: str
    availability_zone: str
    replication_target: str
    source_locator: str          # Format: "Sheet:Provisioning/Row:{n}"
    origin: str = "DETERMINISTIC"
    is_reference_data: bool = True   # Always True — section 14.4


@dataclass(frozen=True)
class ProvisioningFinding:
    """A single finding raised against a Provisioning sheet row."""

    row_number: int
    finding_type: ProvisioningFindingType
    detail: str


@dataclass(frozen=True)
class ProvisioningSheetResult:
    """
    Aggregate result of parsing a Provisioning reference sheet.

    Deliberately carries NO ``selected_target`` field — target placement
    must be adopted via an explicit architect command (section 14.3).
    """

    outcome: str                              # "VALID" | "QUARANTINED"
    candidates: tuple[ProvisioningCandidate, ...]
    findings: tuple[ProvisioningFinding, ...]


# ---------------------------------------------------------------------------
# Adapter
# ---------------------------------------------------------------------------


class ProvisioningSheetAdapter:
    """
    Parses Provisioning reference rows into typed candidates and findings.

    Never auto-selects a target site for any application.
    """

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def parse(self, rows: list[dict]) -> ProvisioningSheetResult:
        """
        Parse a list of row dicts from the Provisioning sheet.

        Rules applied in order for each non-blank row:
        1. Detect INCOMPLETE_ROW (required fields missing).
        2. Validate AWS region syntax → INVALID_REGION.
        3. Detect DUPLICATE_MAPPING (same dc_code + aws_region already seen).
        4. Detect CONTRADICTORY_MAPPING (same dc_code, different aws_region).

        All candidates carry is_reference_data=True regardless of findings.
        Blank rows (all values empty) are silently discarded with no finding.

        Args:
            rows: Each dict maps column header to the cell value string.

        Returns:
            ProvisioningSheetResult — never contains a selected_target field.
        """
        candidates: list[ProvisioningCandidate] = []
        findings: list[ProvisioningFinding] = []

        # Deduplication state
        # Maps (dc_code, aws_region) → first row number seen.
        seen_pairs: dict[tuple[str, str], int] = {}
        # Maps dc_code → first aws_region seen for that code.
        seen_dc_region: dict[str, str] = {}

        for row_index, raw_row in enumerate(rows, start=1):
            row = {k: str(v).strip() for k, v in raw_row.items()}

            # ── Blank-row guard (silent discard, no finding emitted) ───
            if self._is_blank(row):
                continue

            # ── Field extraction ───────────────────────────────────────
            physical_location = self._get(row, "Physical Location")
            dc_code = self._get(row, "Data Center Code")
            dc_name = self._get(row, "Data Center Name")
            aws_region = self._get(row, "AWS Region")
            region_display = self._get(row, "Region Display")
            clli = self._get(row, "CLLI")
            outpost_id = self._get(row, "Outpost ID")
            availability_zone = self._get(row, "Availability Zone")
            replication_target = self._get(row, "Replication Target")
            source_locator = f"Sheet:Provisioning/Row:{row_index}"

            row_has_critical_finding = False

            # ── 1. Incomplete-row check ────────────────────────────────
            missing = [f for f in _REQUIRED_FIELDS if not self._get(row, f)]
            if missing:
                findings.append(
                    ProvisioningFinding(
                        row_number=row_index,
                        finding_type=ProvisioningFindingType.INCOMPLETE_ROW,
                        detail=(
                            f"Required fields missing or empty: "
                            f"{', '.join(missing)}"
                        ),
                    )
                )
                row_has_critical_finding = True

            # ── 2. AWS region syntax check ─────────────────────────────
            if aws_region and not AWS_REGION_PATTERN.match(aws_region):
                findings.append(
                    ProvisioningFinding(
                        row_number=row_index,
                        finding_type=ProvisioningFindingType.INVALID_REGION,
                        detail=(
                            f"AWS region {aws_region!r} does not match "
                            r"pattern ^[a-z]{2}-[a-z]+-\d+$"
                        ),
                    )
                )
                row_has_critical_finding = True

            # ── 3 & 4. Duplicate / contradictory mapping checks ────────
            # Only meaningful when both dc_code and aws_region are present.
            if dc_code and aws_region:
                pair = (dc_code, aws_region)
                if pair in seen_pairs:
                    # Exact (dc_code, region) pair seen before → DUPLICATE
                    findings.append(
                        ProvisioningFinding(
                            row_number=row_index,
                            finding_type=ProvisioningFindingType.DUPLICATE_MAPPING,
                            detail=(
                                f"Duplicate (dc_code={dc_code!r}, "
                                f"aws_region={aws_region!r}) already seen "
                                f"at row {seen_pairs[pair]}"
                            ),
                        )
                    )
                    row_has_critical_finding = True
                elif dc_code in seen_dc_region:
                    prior_region = seen_dc_region[dc_code]
                    if prior_region != aws_region:
                        # Same dc_code, different region → CONTRADICTORY
                        findings.append(
                            ProvisioningFinding(
                                row_number=row_index,
                                finding_type=ProvisioningFindingType.CONTRADICTORY_MAPPING,
                                detail=(
                                    f"dc_code {dc_code!r} was previously "
                                    f"mapped to region {prior_region!r} but "
                                    f"now claims {aws_region!r}"
                                ),
                            )
                        )
                        row_has_critical_finding = True
                else:
                    # First time we see this dc_code — record both indexes.
                    seen_pairs[pair] = row_index
                    seen_dc_region[dc_code] = aws_region

            # ── Build candidate (always — even with findings) ──────────
            candidate = ProvisioningCandidate(
                row_number=row_index,
                physical_location=physical_location,
                dc_code=dc_code,
                dc_name=dc_name,
                aws_region=aws_region,
                region_display=region_display,
                clli=clli,
                outpost_id=outpost_id,
                availability_zone=availability_zone,
                replication_target=replication_target,
                source_locator=source_locator,
                origin="DETERMINISTIC",
                is_reference_data=True,
            )
            candidates.append(candidate)

        # Outcome: QUARANTINED if any critical finding was raised; else VALID.
        critical = {
            ProvisioningFindingType.INVALID_REGION,
            ProvisioningFindingType.DUPLICATE_MAPPING,
            ProvisioningFindingType.CONTRADICTORY_MAPPING,
            ProvisioningFindingType.INCOMPLETE_ROW,
        }
        has_critical = any(f.finding_type in critical for f in findings)
        outcome = "QUARANTINED" if has_critical else "VALID"

        return ProvisioningSheetResult(
            outcome=outcome,
            candidates=tuple(candidates),
            findings=tuple(findings),
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _is_blank(row: dict) -> bool:
        """Return True when every value in the row is empty after stripping."""
        return all(not v for v in row.values())

    @staticmethod
    def _get(row: dict, key: str) -> str:
        """Return stripped string value for key, or empty string if absent."""
        return str(row.get(key, "")).strip()
