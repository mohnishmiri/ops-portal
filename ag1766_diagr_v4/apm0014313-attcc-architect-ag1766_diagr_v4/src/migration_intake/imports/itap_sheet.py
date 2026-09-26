"""iTAP source-capture sheet adapter (B03).

The iTAP sheet uses an item/details layout: two columns (A = item label,
B = details value).  This adapter produces typed ITAPCandidate objects for
known labels and ITAPFinding objects for anomalies such as unknown labels,
blank values, and duplicate rows.

Design invariants
-----------------
- Label lookup is *explicit*: only labels present in ITAP_LABEL_MAP are
  recognised.  No fuzzy matching is performed.
- Row numbers are 1-based; source locators use the format
  ``Sheet:iTAP/Row:{n}/Col:B``.
- Blank (or whitespace-only) detail cells produce a BLANK_DETAIL finding
  and no candidate.
- Unrecognised labels produce an UNMAPPED_CONTENT finding.
- Duplicate recognised labels produce a DUPLICATE_ITEM finding with
  "corroborating" or "conflict" text depending on value equality.
- Both candidates are retained on conflict so that a human reviewer can
  adjudicate.
- The overall outcome is always "VALID"; iTAP is supplemental evidence
  and a finding-laden sheet does not constitute a hard failure.
- All candidates carry ``origin="DETERMINISTIC"``; AI is never involved
  in this adapter.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum

# ---------------------------------------------------------------------------
# Public enumerations
# ---------------------------------------------------------------------------


class ITAPFindingType(str, Enum):
    UNMAPPED_CONTENT = "UNMAPPED_CONTENT"
    DUPLICATE_ITEM = "DUPLICATE_ITEM"
    BLANK_DETAIL = "BLANK_DETAIL"
    IDENTITY_MISMATCH = "IDENTITY_MISMATCH"


# ---------------------------------------------------------------------------
# Public data transfer objects
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ITAPCandidate:
    """A single parsed value ready for candidate-review ingestion.

    Attributes:
        row_number:      1-based row index in the iTAP sheet.
        canonical_code:  Question code from ITAP_LABEL_MAP (e.g. "CTL-001").
        raw_label:       Original label string exactly as read from the sheet.
        raw_value:       Original value string exactly as read from the sheet.
        source_locator:  Deterministic location string: ``Sheet:iTAP/Row:{n}/Col:B``.
        origin:          Always "DETERMINISTIC" for this adapter.
    """

    row_number: int
    canonical_code: str
    raw_label: str
    raw_value: str
    source_locator: str
    origin: str = "DETERMINISTIC"


@dataclass(frozen=True)
class ITAPFinding:
    """A structural or semantic anomaly detected during parsing.

    Attributes:
        row_number:   1-based row index where the issue was found.
        finding_type: Category of finding.
        raw_label:    Label string as read from the sheet.
        raw_value:    Value string as read from the sheet.
        detail:       Human-readable description of the finding.
    """

    row_number: int
    finding_type: ITAPFindingType
    raw_label: str
    raw_value: str
    detail: str


@dataclass(frozen=True)
class ITAPSheetResult:
    """Immutable result of a single iTAP sheet parse operation.

    Attributes:
        outcome:        Always "VALID" for iTAP (supplemental source).
        candidates:     All extracted value candidates.
        findings:       All anomaly findings (BLANK, UNMAPPED, DUPLICATE).
        mapped_count:   Number of rows successfully mapped to a canonical code.
        unmapped_count: Number of rows with unrecognised labels.
    """

    outcome: str  # "VALID" | "QUARANTINED" | "FAILED"
    candidates: tuple[ITAPCandidate, ...]
    findings: tuple[ITAPFinding, ...]
    mapped_count: int
    unmapped_count: int


# ---------------------------------------------------------------------------
# Adapter
# ---------------------------------------------------------------------------


class ITAPSheetAdapter:
    """Parse the iTAP source-capture sheet into candidates and findings.

    Parameters
    ----------
    label_map:
        Mapping of *normalised* label strings to canonical question codes.
        Defaults to :data:`ITAP_LABEL_MAP`.
    """

    def __init__(
        self,
        label_map: dict[str, str] | None = None,
    ) -> None:
        # Pre-compute a normalised key → (canonical_label, code) lookup so
        # that whitespace variations in the sheet map correctly.
        raw_map = label_map if label_map is not None else ITAP_LABEL_MAP
        self._label_map: dict[str, str] = raw_map
        # normalised_key → canonical code
        self._norm_map: dict[str, str] = {
            self._normalize_label(k): v for k, v in raw_map.items()
        }

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def parse(self, rows: list[tuple[str, str]]) -> ITAPSheetResult:
        """Parse iTAP rows and return a fully populated :class:`ITAPSheetResult`.

        Parameters
        ----------
        rows:
            List of ``(label, value)`` string pairs, row-by-row from the
            sheet.  Row numbers are assigned starting from **1**.

        Returns
        -------
        ITAPSheetResult
            Outcome is always ``"VALID"``; findings describe anomalies.
        """
        if not rows:
            return ITAPSheetResult(
                outcome="VALID",
                candidates=(),
                findings=(),
                mapped_count=0,
                unmapped_count=0,
            )

        candidates: list[ITAPCandidate] = []
        findings: list[ITAPFinding] = []
        mapped_count = 0
        unmapped_count = 0

        # Track previously seen normalised labels so we can detect duplicates.
        # Maps normalised_label → list of (row_number, raw_value, candidate_index)
        seen: dict[str, list[tuple[int, str]]] = {}

        for row_idx, (raw_label, raw_value) in enumerate(rows, start=1):
            norm_label = self._normalize_label(raw_label)
            source_locator = f"Sheet:iTAP/Row:{row_idx}/Col:B"

            # ---- look up the label ----------------------------------------
            code = self._norm_map.get(norm_label)

            if code is None:
                # Unknown label
                unmapped_count += 1
                findings.append(
                    ITAPFinding(
                        row_number=row_idx,
                        finding_type=ITAPFindingType.UNMAPPED_CONTENT,
                        raw_label=raw_label,
                        raw_value=raw_value,
                        detail=(
                            f"Label {raw_label!r} is not present in ITAP_LABEL_MAP "
                            f"and cannot be mapped to a canonical question code."
                        ),
                    )
                )
                continue

            # ---- blank / whitespace-only value check ----------------------
            if not raw_value.strip():
                findings.append(
                    ITAPFinding(
                        row_number=row_idx,
                        finding_type=ITAPFindingType.BLANK_DETAIL,
                        raw_label=raw_label,
                        raw_value=raw_value,
                        detail=(
                            f"Label {raw_label!r} (row {row_idx}) has a blank "
                            f"detail value; no candidate can be extracted."
                        ),
                    )
                )
                # Count as mapped (label was recognised) but emit no candidate.
                mapped_count += 1
                seen.setdefault(norm_label, []).append((row_idx, raw_value))
                continue

            # ---- duplicate detection ---------------------------------------
            prior_occurrences = seen.get(norm_label, [])
            if prior_occurrences:
                # Determine conflict vs corroborating based on non-blank priors
                non_blank_priors = [v for _, v in prior_occurrences if v.strip()]
                if non_blank_priors:
                    # Compare current value against the first non-blank prior
                    first_prior_value = non_blank_priors[0]
                    if raw_value.strip() == first_prior_value.strip():
                        detail = (
                            f"Label {raw_label!r} appears more than once "
                            f"(rows {prior_occurrences[0][0]} and {row_idx}). "
                            f"Values are identical — corroborating duplicate."
                        )
                    else:
                        detail = (
                            f"Label {raw_label!r} appears more than once "
                            f"(rows {prior_occurrences[0][0]} and {row_idx}) "
                            f"with different values — conflict: "
                            f"{first_prior_value!r} vs {raw_value!r}."
                        )
                    findings.append(
                        ITAPFinding(
                            row_number=row_idx,
                            finding_type=ITAPFindingType.DUPLICATE_ITEM,
                            raw_label=raw_label,
                            raw_value=raw_value,
                            detail=detail,
                        )
                    )

            # ---- emit candidate -------------------------------------------
            candidates.append(
                ITAPCandidate(
                    row_number=row_idx,
                    canonical_code=code,
                    raw_label=raw_label,
                    raw_value=raw_value,
                    source_locator=source_locator,
                    origin="DETERMINISTIC",
                )
            )
            mapped_count += 1
            seen.setdefault(norm_label, []).append((row_idx, raw_value))

        return ITAPSheetResult(
            outcome="VALID",
            candidates=tuple(candidates),
            findings=tuple(findings),
            mapped_count=mapped_count,
            unmapped_count=unmapped_count,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _normalize_label(self, raw: str) -> str:
        """Normalise a label for lookup: strip outer whitespace, collapse interior runs.

        Parameters
        ----------
        raw:
            Raw label string as read from the sheet cell.

        Returns
        -------
        str
            Normalised label with leading/trailing whitespace removed and
            internal whitespace sequences collapsed to a single space.
        """
        return re.sub(r"\s+", " ", raw).strip()


# ---------------------------------------------------------------------------
# Canonical label → question-code map
# ---------------------------------------------------------------------------

ITAP_LABEL_MAP: dict[str, str] = {
    "Application Name": "CTL-001",
    "MOTS ID": "CTL-003",
    "Business Criticality": "APP-004-criticality",
    "Emergency Tier": "APP-004-tier",
    "PCI Scope": "SEC-001",
    "SOX Scope": "SEC-002",
    "RTO (hours)": "APP-006-rto",
    "RPO (hours)": "APP-006-rpo",
    "Application Owner": "APP-007-owner",
    "Technical Contact": "APP-007-tech",
    "Internet Required": "NET-007-internet",
    "Proxy Required": "NET-007-proxy",
    "Internal Users": "APP-006-internal",
    "External Users": "APP-006-external",
    "Data Classification": "SEC-003",
    "Hosting Platform": "ENV-001",
}
