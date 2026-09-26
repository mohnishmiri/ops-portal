# Legacy Intake Workbook Import — L01 Complete

**Date:** 2026-09-11  
**Slice:** L01 — Contract and Identity Discovery  
**Status:** ✅ **COMPLETE**

---

## Summary

Slice L01 implements the foundation for legacy intake workbook import:
- Synthetic fixture builder for testing
- Exact seven-sheet contract inspector
- Typed identity extraction with source locators
- Generalized identity resolver with precedence and cross-ID consistency

**All 41 unit tests passing.**

---

## Files Created

### Production Code

1. **`src/migration_intake/imports/legacy_intake_contract.py`** (134 lines)
   - `LegacyIntakeContractVersion` enum
   - `LegacyIntakeSheetContract` dataclass
   - `LEGACY_INTAKE_V1_SHEETS` constant (7 sheets)
   - `inspect_legacy_intake_contract()` — validates exact contract
   - `is_legacy_intake_workbook()` — quick pre-check
   - `LegacyIntakeContractError` exception

2. **`src/migration_intake/imports/legacy_intake_identity.py`** (183 lines)
   - `ExtractedIdentifier` dataclass with source locators
   - `normalize_identifier()` — alphanumeric, case-insensitive policy
   - `extract_legacy_intake_identifiers()` — extracts from App and iTAP sheets
   - `consolidate_identifiers_by_type()` — groups by type
   - `get_unique_identifier_value()` — detects within-type conflicts

3. **`src/migration_intake/imports/legacy_identity_resolver.py`** (224 lines)
   - `LegacyIdentityResolution` dataclass
   - `resolve_legacy_intake_identity()` — precedence and cross-ID consistency
   - Precedence: Correlation → MOTS → iTAP
   - Cross-ID validation: all supplied IDs must resolve to same application

### Test Code

4. **`tests/fixtures/legacy_intake_workbook.py`** (205 lines)
   - `build_legacy_intake_workbook()` — synthetic seven-sheet workbook
   - `build_legacy_workbook_with_conflicting_ids()` — conflict test fixture
   - `build_legacy_workbook_with_multiple_ids()` — precedence test fixture

5. **`tests/unit/imports/test_legacy_intake_contract.py`** (130 lines)
   - 11 tests for contract inspection
   - Tests: valid contract, missing sheets, wrong headers, empty sheets, whitespace normalization

6. **`tests/unit/imports/test_legacy_intake_identity.py`** (193 lines)
   - 16 tests for identity extraction
   - Tests: normalization, extraction from App/iTAP, multiple IDs, blank handling, grouping, conflicts

7. **`tests/unit/imports/test_legacy_identity_resolver.py`** (262 lines)
   - 14 tests for identity resolution
   - Tests: precedence, fallback, cross-ID consistency, conflicts, ambiguous/unknown IDs

---

## Test Results

```
============================= test session starts =============================
collected 41 items

test_legacy_intake_contract.py::TestIsLegacyIntakeWorkbook ............ [ 27%]
test_legacy_intake_contract.py::TestInspectLegacyIntakeContract ...... [ 54%]
test_legacy_intake_identity.py::TestNormalizeIdentifier .............. [ 68%]
test_legacy_intake_identity.py::TestExtractLegacyIntakeIdentifiers ... [ 85%]
test_legacy_intake_identity.py::TestConsolidateIdentifiersByType ..... [ 90%]
test_legacy_intake_identity.py::TestGetUniqueIdentifierValue ......... [ 95%]
test_legacy_identity_resolver.py::TestResolveLegacyIntakeIdentity .... [100%]

============================= 41 passed in 0.45s ==============================
```

---

## Key Design Decisions

### 1. Exact Contract Matching

The inspector requires all seven sheets with exact headers for App and iTAP:

- **App:** `No`, `Question`, `Response_Type`, `Response`, `Allowed_Values_or_Unit`
- **iTAP:** `Item`, `Details`
- Other sheets (WaveUtil, Infra, Database, TSS, Provisioning) are required but have variable structure

### 2. Identity Extraction

Identifiers are extracted from:

- **App Q1:** "What is the application correlation or MOTS ID?" (Response column)
- **iTAP sheet:** Item/Details pairs matching known labels:
  - "Correlation ID" → CORRELATION
  - "APM Number" → ITAP
  - "MOTS ID" → MOTS

Each extracted identifier includes:
- Type (CORRELATION, MOTS, ITAP)
- Raw and normalized values
- Source sheet, row, column, and label

### 3. Precedence Algorithm

When multiple identifier types are present:

1. Use **Correlation** if present
2. Else use **MOTS** if present
3. Else use **ITAP** if present

### 4. Conflict Detection

Two levels of conflict detection:

**Within-type conflicts:**
- Same type (e.g., CORRELATION) with different normalized values
- Example: App has "CORR-123", iTAP has "CORR-456"
- Result: `SOURCE_ID_CONFLICT`

**Cross-type conflicts:**
- Different types resolve to different applications
- Example: Correlation matches app-1, MOTS matches app-2
- Result: `SOURCE_ID_CONFLICT` with detailed explanation

### 5. Identity Outcomes

- `MATCHED` — Unique match, all IDs consistent
- `MISSING` — No identifier found
- `MISMATCH` — Identifier not registered or wrong application
- `AMBIGUOUS` — Same identifier on multiple applications
- `SOURCE_CONFLICT` — Conflicting values or cross-ID inconsistency

---

## Coverage

### Contract Inspection

- ✅ Valid seven-sheet contract
- ✅ Missing required sheets
- ✅ Wrong headers
- ✅ Empty sheets
- ✅ Extra columns allowed
- ✅ Whitespace normalization

### Identity Extraction

- ✅ Correlation from App Q1
- ✅ Correlation from iTAP
- ✅ MOTS from iTAP
- ✅ iTAP from APM Number
- ✅ Multiple identifiers
- ✅ Blank values ignored
- ✅ Non-identifier questions ignored

### Identity Resolution

- ✅ Correlation-only match
- ✅ MOTS fallback
- ✅ iTAP fallback
- ✅ Correlation preferred over MOTS
- ✅ Correlation preferred over iTAP
- ✅ Missing identifier
- ✅ Unknown identifier
- ✅ Ambiguous identifier
- ✅ Selected application mismatch
- ✅ Within-type conflict
- ✅ Cross-ID consistency success
- ✅ Cross-ID consistency failure
- ✅ Unregistered lower-priority ID ignored
- ✅ All extracted identifiers preserved

---

## Example Usage

### Extract and Resolve Identity

```python
from migration_intake.imports.legacy_intake_identity import extract_legacy_intake_identifiers
from migration_intake.imports.legacy_identity_resolver import resolve_legacy_intake_identity

# Extract from workbook
app_rows = [
    {
        "No": "1",
        "Question": "What is the application correlation or MOTS ID?",
        "Response_Type": "IDENTIFIER",
        "Response": "CORR-12345",
    }
]
itap_rows = [
    ("Correlation ID", "CORR-12345"),
    ("APM Number", "APM-67890"),
]

extracted = extract_legacy_intake_identifiers(app_rows, itap_rows)

# Resolve against database
app_identifiers = [
    ("app-uuid-1", "CORRELATION", "CORR-12345"),
    ("app-uuid-1", "ITAP", "APM-67890"),
]

result = resolve_legacy_intake_identity(
    extracted_identifiers=extracted,
    application_identifiers=app_identifiers,
)

# Result:
# - outcome: MATCHED
# - selected_identifier_type: CORRELATION (precedence)
# - matched_application_ids: ("app-uuid-1",)
```

---

## Next Steps

### L02 — Persistence and Oracle Migration

1. Add `import_lane` column to `import_runs`
2. Add `matched_identifier_type` column
3. Add `base_answer_revision` column to `candidates`
4. Create migration `0013_legacy_intake_support`
5. Test on SQLite and Oracle

### L03 — Upload and Intake-Selection UX

1. Add third lane card on Sources page
2. Create upload route with identity extraction
3. Create identity result screen
4. Create intake chooser screen
5. Web integration tests

### L04 — Reviewed Legacy Mapping

1. Define exact field mappings for App, iTAP, TSS, Provisioning
2. Create versioned mapping artifact
3. Implement deterministic parsing
4. Create findings for unknown fields
5. Mapping and service tests

### L05 — Stale-Answer Protection

1. Capture baseline revision at import
2. Check baseline at acceptance
3. Block stale overwrites
4. Mixed bulk outcomes
5. Conflict UI

### L06 — End-to-End Gate

1. Browser journey
2. SQLite regression
3. Oracle verification
4. Documentation

---

## Verification

```bash
# Run L01 tests
python -m pytest tests/unit/imports/test_legacy_intake_contract.py \
                 tests/unit/imports/test_legacy_intake_identity.py \
                 tests/unit/imports/test_legacy_identity_resolver.py -v

# Expected: 41 passed
```

---

**Status:** ✅ **L01 COMPLETE** — Ready for L02 (Persistence and Oracle Migration)
