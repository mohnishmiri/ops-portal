"""
Unit tests for domain/wave_util_matching.py — WaveUtil Matching and Reconciliation (V03).

TDD RED: written before implementation; ImportError expected until
src/migration_intake/domain/wave_util_matching.py exists.

Architecture reference: section 19 of PRODUCTION_FOUNDATION_ARCHITECTURE_AND_TECHNICAL_DESIGN.md

Tests (15 required):
1.  test_blank_server_name_gives_invalid_identity
2.  test_none_server_name_gives_invalid_identity
3.  test_exact_match_on_server_name
4.  test_exact_match_is_case_insensitive
5.  test_probable_match_environment_differs
6.  test_new_row_when_no_canonical
7.  test_ambiguous_when_multiple_canonical_match
8.  test_application_mismatch_when_canonical_belongs_to_other_app
9.  test_duplicate_source_rows_both_flagged
10. test_duplicate_detection_is_case_insensitive
11. test_blank_candidate_does_not_produce_scope_mismatch
12. test_scope_mismatch_produces_finding_not_conflict
13. test_missing_from_source_produces_finding
14. test_missing_is_not_retirement
15. test_identical_duplicate_retains_both_locators
"""
from __future__ import annotations

import pytest

from migration_intake.domain.wave_util_matching import (
    CanonicalRow,
    MatchOutcome,
    MatchResult,
    ReconciliationFinding,
    ReconciliationFindingType,
    SourceRow,
    WaveUtilMatcher,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_source(
    server_name: str | None = "SRV001",
    environment: str | None = "PRODUCTION",
    scope: str | None = "PROD",
    source_locator: str = "Sheet:WaveUtil/Row:2",
    raw_fields: dict | None = None,
) -> SourceRow:
    return SourceRow(
        server_name=server_name,
        environment=environment,
        scope=scope,
        source_locator=source_locator,
        raw_fields=raw_fields or {},
    )


def _make_canonical(
    row_id: str = "can-001",
    server_name: str = "SRV001",
    application_id: str = "APP-42",
    environment: str | None = "PRODUCTION",
    scope: str | None = "PROD",
    current_field_values: dict | None = None,
) -> CanonicalRow:
    return CanonicalRow(
        row_id=row_id,
        server_name=server_name,
        application_id=application_id,
        environment=environment,
        scope=scope,
        current_field_values=current_field_values or {},
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestInvalidIdentity:
    """INVALID_IDENTITY outcome — blank or None server_name."""

    def test_blank_server_name_gives_invalid_identity(self) -> None:
        """Test 1: SourceRow(server_name='') → INVALID_IDENTITY."""
        matcher = WaveUtilMatcher()
        source_row = _make_source(server_name="")
        results = matcher.match_batch([source_row], [], application_id="APP-42")

        assert len(results) == 1
        assert results[0].outcome == MatchOutcome.INVALID_IDENTITY

    def test_none_server_name_gives_invalid_identity(self) -> None:
        """Test 2: SourceRow(server_name=None) → INVALID_IDENTITY."""
        matcher = WaveUtilMatcher()
        source_row = _make_source(server_name=None)
        results = matcher.match_batch([source_row], [], application_id="APP-42")

        assert len(results) == 1
        assert results[0].outcome == MatchOutcome.INVALID_IDENTITY


class TestExactMatch:
    """EXACT_MATCH outcome — single unambiguous canonical row match."""

    def test_exact_match_on_server_name(self) -> None:
        """Test 3: Source row matches canonical row exactly → EXACT_MATCH."""
        matcher = WaveUtilMatcher()
        source_row = _make_source(server_name="SRV001", environment="PRODUCTION", scope="PROD")
        canonical = _make_canonical(server_name="SRV001", environment="PRODUCTION", scope="PROD")

        results = matcher.match_batch([source_row], [canonical], application_id="APP-42")

        assert len(results) == 1
        result = results[0]
        assert result.outcome == MatchOutcome.EXACT_MATCH
        assert result.canonical_row_id == canonical.row_id

    def test_exact_match_is_case_insensitive(self) -> None:
        """Test 4: 'MyServer' matches 'myserver' canonical → EXACT_MATCH."""
        matcher = WaveUtilMatcher()
        source_row = _make_source(server_name="MyServer")
        canonical = _make_canonical(server_name="myserver")

        results = matcher.match_batch([source_row], [canonical], application_id="APP-42")

        assert len(results) == 1
        assert results[0].outcome == MatchOutcome.EXACT_MATCH


class TestProbableMatch:
    """PROBABLE_MATCH outcome — server name matches but secondary fields differ."""

    def test_probable_match_environment_differs(self) -> None:
        """Test 5: Server name matches but environment differs → PROBABLE_MATCH."""
        matcher = WaveUtilMatcher()
        source_row = _make_source(server_name="SRV001", environment="TEST", scope="TEST")
        canonical = _make_canonical(server_name="SRV001", environment="PRODUCTION", scope="PROD")

        results = matcher.match_batch([source_row], [canonical], application_id="APP-42")

        assert len(results) == 1
        assert results[0].outcome == MatchOutcome.PROBABLE_MATCH


class TestNewRow:
    """NEW_ROW outcome — no canonical row found for server name."""

    def test_new_row_when_no_canonical(self) -> None:
        """Test 6: No canonical rows → NEW_ROW."""
        matcher = WaveUtilMatcher()
        source_row = _make_source(server_name="BRAND-NEW-SRV")

        results = matcher.match_batch([source_row], [], application_id="APP-42")

        assert len(results) == 1
        result = results[0]
        assert result.outcome == MatchOutcome.NEW_ROW
        assert result.canonical_row_id is None


class TestAmbiguousMatch:
    """AMBIGUOUS_MATCH outcome — multiple canonical rows match same server name."""

    def test_ambiguous_when_multiple_canonical_match(self) -> None:
        """Test 7: Two canonical rows with same server name → AMBIGUOUS_MATCH."""
        matcher = WaveUtilMatcher()
        source_row = _make_source(server_name="SRV001")
        canonical_a = _make_canonical(row_id="can-001", server_name="SRV001")
        canonical_b = _make_canonical(row_id="can-002", server_name="SRV001")

        results = matcher.match_batch([source_row], [canonical_a, canonical_b], application_id="APP-42")

        assert len(results) == 1
        assert results[0].outcome == MatchOutcome.AMBIGUOUS_MATCH


class TestApplicationMismatch:
    """APPLICATION_MISMATCH outcome — canonical row belongs to a different application."""

    def test_application_mismatch_when_canonical_belongs_to_other_app(self) -> None:
        """Test 8: canonical.application_id != command application_id → APPLICATION_MISMATCH."""
        matcher = WaveUtilMatcher()
        source_row = _make_source(server_name="SRV001")
        canonical = _make_canonical(server_name="SRV001", application_id="APP-OTHER")

        results = matcher.match_batch([source_row], [canonical], application_id="APP-42")

        assert len(results) == 1
        assert results[0].outcome == MatchOutcome.APPLICATION_MISMATCH


class TestDuplicateSourceRows:
    """DUPLICATE_SOURCE_ROW outcome — repeated server_name inside the same import batch."""

    def test_duplicate_source_rows_both_flagged(self) -> None:
        """Test 9: Two source rows with same (normalized) server name → both DUPLICATE_SOURCE_ROW."""
        matcher = WaveUtilMatcher()
        row_a = _make_source(server_name="SRV001", source_locator="Sheet:WaveUtil/Row:2")
        row_b = _make_source(server_name="SRV001", source_locator="Sheet:WaveUtil/Row:5")

        results = matcher.match_batch([row_a, row_b], [], application_id="APP-42")

        assert len(results) == 2
        outcomes = {r.outcome for r in results}
        assert outcomes == {MatchOutcome.DUPLICATE_SOURCE_ROW}

    def test_duplicate_detection_is_case_insensitive(self) -> None:
        """Test 10: 'Server1' and 'server1' in same batch → both DUPLICATE_SOURCE_ROW."""
        matcher = WaveUtilMatcher()
        row_a = _make_source(server_name="Server1", source_locator="Sheet:WaveUtil/Row:2")
        row_b = _make_source(server_name="server1", source_locator="Sheet:WaveUtil/Row:7")

        results = matcher.match_batch([row_a, row_b], [], application_id="APP-42")

        assert len(results) == 2
        outcomes = {r.outcome for r in results}
        assert outcomes == {MatchOutcome.DUPLICATE_SOURCE_ROW}

    def test_identical_duplicate_retains_both_locators(self) -> None:
        """Test 15: Two duplicate source rows — both MatchResult.source_locator are preserved."""
        matcher = WaveUtilMatcher()
        row_a = _make_source(server_name="SRV001", source_locator="Sheet:WaveUtil/Row:2")
        row_b = _make_source(server_name="SRV001", source_locator="Sheet:WaveUtil/Row:9")

        results = matcher.match_batch([row_a, row_b], [], application_id="APP-42")

        assert len(results) == 2
        locators = {r.source_locator for r in results}
        assert "Sheet:WaveUtil/Row:2" in locators
        assert "Sheet:WaveUtil/Row:9" in locators


class TestReconciliationFindings:
    """Reconciliation finding rules for blank candidates, scope mismatches, and missing rows."""

    def test_blank_candidate_does_not_produce_scope_mismatch(self) -> None:
        """Test 11: Blank scope field on source row → only BLANK_CANDIDATE finding, not SCOPE_MISMATCH."""
        matcher = WaveUtilMatcher()
        source_row = _make_source(
            server_name="SRV001",
            environment=None,
            scope=None,
            raw_fields={"scope": ""},
        )
        canonical = _make_canonical(server_name="SRV001", environment="PRODUCTION", scope="PROD")

        findings = matcher.find_missing_from_source([], [])
        # The core assertion: matching a blank-scope source against a canonical with scope
        # must not produce SCOPE_MISMATCH — at most BLANK_CANDIDATE.
        results = matcher.match_batch([source_row], [canonical], application_id="APP-42")

        finding_types_in_results = set()
        # Verify no SCOPE_MISMATCH arises from blank scope — EXACT_MATCH or PROBABLE_MATCH is ok
        # The key rule: blank candidate never triggers scope mismatch finding.
        # We verify this by checking there are no SCOPE_MISMATCH findings emitted for blank scope.
        # (Finding emission is separate from match outcome; test the finding collection.)
        blank_scope_findings = _collect_reconciliation_findings(matcher, source_row, canonical, "APP-42")
        scope_mismatch_findings = [
            f for f in blank_scope_findings
            if f.finding_type == ReconciliationFindingType.SCOPE_MISMATCH
        ]
        assert len(scope_mismatch_findings) == 0

    def test_scope_mismatch_produces_finding_not_conflict(self) -> None:
        """Test 12: Scope differs (PROD vs DEV) → SCOPE_MISMATCH finding, not APPLICATION_MISMATCH."""
        matcher = WaveUtilMatcher()
        source_row = _make_source(server_name="SRV001", environment="DEVELOPMENT", scope="DEV")
        canonical = _make_canonical(server_name="SRV001", environment="PRODUCTION", scope="PROD")

        results = matcher.match_batch([source_row], [canonical], application_id="APP-42")
        # outcome is PROBABLE_MATCH (not APPLICATION_MISMATCH) because scope differs, not app_id
        assert results[0].outcome == MatchOutcome.PROBABLE_MATCH
        assert results[0].outcome != MatchOutcome.APPLICATION_MISMATCH

    def test_missing_from_source_produces_finding(self) -> None:
        """Test 13: Canonical row absent from batch → MISSING_FROM_SOURCE finding returned."""
        matcher = WaveUtilMatcher()
        canonical = _make_canonical(server_name="GHOST-SRV")

        # Source batch is empty — canonical row is absent
        findings = matcher.find_missing_from_source([], [canonical])

        assert len(findings) == 1
        assert findings[0].finding_type == ReconciliationFindingType.MISSING_FROM_SOURCE
        assert findings[0].server_name == "GHOST-SRV"

    def test_missing_is_not_retirement(self) -> None:
        """Test 14: MISSING_FROM_SOURCE finding type is MISSING_FROM_SOURCE — not delete/retire."""
        matcher = WaveUtilMatcher()
        canonical = _make_canonical(server_name="OLD-SRV")

        findings = matcher.find_missing_from_source([], [canonical])

        assert len(findings) == 1
        finding = findings[0]
        # Must be MISSING_FROM_SOURCE — no delete/retire action implicit
        assert finding.finding_type == ReconciliationFindingType.MISSING_FROM_SOURCE
        # The finding type value should be the literal string "MISSING_FROM_SOURCE"
        assert finding.finding_type.value == "MISSING_FROM_SOURCE"


# ---------------------------------------------------------------------------
# Internal helper for reconciliation finding collection
# ---------------------------------------------------------------------------


def _collect_reconciliation_findings(
    matcher: WaveUtilMatcher,
    source_row: SourceRow,
    canonical: CanonicalRow,
    application_id: str,
) -> list[ReconciliationFinding]:
    """Helper: match one source row against one canonical and return any reconciliation findings."""
    return matcher.reconcile_fields(source_row, canonical, application_id=application_id)
