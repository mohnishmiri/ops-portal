# Legacy Intake Workbook Import — L01-L03 Progress

**Date:** 2026-09-11  
**Status:** L01 ✅ COMPLETE | L02 ✅ COMPLETE | L03 🔄 IN PROGRESS

---

## Summary

Implemented the first three slices of the legacy intake workbook import feature:

- **L01:** Contract and identity discovery (41 passing tests)
- **L02:** Persistence and Oracle migration (migration 0013)
- **L03:** Upload UX and intake selection (routes and templates created)

---

## L01 — Contract and Identity Discovery ✅

### Files Created

1. **`tests/fixtures/legacy_intake_workbook.py`** (205 lines)
   - Synthetic seven-sheet workbook builder
   - Supports conflicting IDs and multiple ID scenarios

2. **`src/migration_intake/imports/legacy_intake_contract.py`** (134 lines)
   - Contract inspector for seven-sheet structure
   - `inspect_legacy_intake_contract()` validates exact headers
   - `is_legacy_intake_workbook()` quick pre-check

3. **`src/migration_intake/imports/legacy_intake_identity.py`** (183 lines)
   - `ExtractedIdentifier` dataclass with source locators
   - `extract_legacy_intake_identifiers()` from App and iTAP sheets
   - `normalize_identifier()` alphanumeric, case-insensitive

4. **`src/migration_intake/imports/legacy_identity_resolver.py`** (224 lines)
   - `resolve_legacy_intake_identity()` with precedence
   - Precedence: Correlation → MOTS → iTAP
   - Cross-ID consistency validation

5. **Test files** (3 files, 41 tests total)
   - `test_legacy_intake_contract.py` (11 tests)
   - `test_legacy_intake_identity.py` (16 tests)
   - `test_legacy_identity_resolver.py` (14 tests)

### Key Features

- **Contract Inspection:** Validates seven-sheet structure (App, iTAP, WaveUtil, Infra, Database, TSS, Provisioning)
- **Identity Extraction:** Extracts Correlation, MOTS, iTAP IDs from App Q1 and iTAP sheet
- **Identity Resolution:** Precedence-based matching with cross-ID consistency
- **Outcomes:** MATCHED, MISSING, MISMATCH, AMBIGUOUS, SOURCE_CONFLICT

---

## L02 — Persistence and Oracle Migration ✅

### Migration 0013

**File:** `src/migration_intake/persistence/migrations/versions/0013_legacy_intake_support.py`

**Changes:**

1. **`import_runs` table:**
   - Added `import_lane` (String30) — SOURCE_DOCUMENT, GAP_WORKBOOK, LEGACY_INTAKE
   - Added `matched_identifier_type` (String20) — CORRELATION, MOTS, ITAP
   - Backfilled existing rows with `import_lane = 'SOURCE_DOCUMENT'`

2. **`candidates` table:**
   - Added `base_answer_revision` (Integer) — for stale-answer detection

### ORM Models Updated

1. **`src/migration_intake/persistence/models_imports.py`**
   - Added `import_lane` and `matched_identifier_type` columns

2. **`src/migration_intake/persistence/models_candidates.py`**
   - Added `base_answer_revision` column

### Verification

- ✅ Migration tested on SQLite
- ✅ Migration tested on Oracle
- ✅ All columns verified in both databases

---

## L03 — Upload UX and Intake Selection 🔄

### Files Created/Modified

1. **`src/migration_intake/web/routes/legacy_intake.py`** (393 lines)
   - POST `/applications/{app}/intakes/{intake}/legacy-intake/upload`
   - GET `/applications/{app}/intakes/{intake}/legacy-intake/{run}/identity`
   - GET `/applications/{app}/intakes/{intake}/legacy-intake/{run}/select-intake`

2. **`src/migration_intake/web/templates/evidence/list.html`** (modified)
   - Updated page description to mention three lanes
   - Added third lane card for legacy intake workbooks
   - Updated lane detection logic

3. **`src/migration_intake/web/templates/legacy_intake/identity_result.html`** (105 lines)
   - Shows identity resolution outcome
   - Displays extracted identifiers with source locations
   - Provides remediation steps

4. **`src/migration_intake/web/templates/legacy_intake/select_intake.html`** (130 lines)
   - Lists eligible intakes for matched application
   - Radio button selection
   - Shows current intake

5. **`src/migration_intake/web/routes/evidence.py`** (modified)
   - Updated lane detection to recognize `APP_DATA_CAPTURE_LEGACY_V1`

6. **`src/migration_intake/main.py`** (modified)
   - Registered `legacy_intake.router`

### Upload Flow

1. **User uploads .xlsx file** via lane ③ on Sources page
2. **File validation:** Size, type, seven-sheet structure
3. **Contract inspection:** Validates exact headers for App and iTAP sheets
4. **Identity extraction:** Reads Correlation, MOTS, iTAP IDs from workbook
5. **Identity resolution:** Matches against application identifiers
6. **Routing:**
   - If MATCHED → Intake selection screen
   - If MISSING/MISMATCH/AMBIGUOUS/CONFLICT → Identity result screen

### Identity Result Screen

Shows when identity resolution fails:

- Identity outcome (MISSING, MISMATCH, AMBIGUOUS, SOURCE_CONFLICT)
- Extracted identifiers table (type, value, source location)
- Application identifiers table
- Remediation steps specific to the outcome

### Intake Selection Screen

Shows when identity matches:

- Success message with matched identifier type and value
- List of eligible intakes (OPEN or IN_PROGRESS)
- Radio button selection
- Current intake highlighted
- Process button (not yet implemented)

---

## Remaining Work

### L03 Completion

- [ ] Implement POST `/applications/{app}/intakes/{intake}/legacy-intake/{run}/process`
- [ ] Web integration tests for upload flow
- [ ] Error handling for edge cases

### L04 — Reviewed Legacy Field Mappings

- [ ] Define exact field mappings for App, iTAP, TSS, Provisioning sheets
- [ ] Create versioned mapping artifact
- [ ] Implement deterministic parsing
- [ ] Create findings for unknown fields
- [ ] Mapping and service tests

### L05 — Stale-Answer Protection

- [ ] Capture baseline revision at import
- [ ] Check baseline at acceptance
- [ ] Block stale overwrites
- [ ] Mixed bulk outcomes
- [ ] Conflict UI

### L06 — End-to-End Verification

- [ ] Browser journey test
- [ ] SQLite regression
- [ ] Oracle verification
- [ ] Documentation

---

## Architecture Decisions

### Three Distinct Lanes

The Sources page now has three clearly labeled lanes:

1. **Source documents** (lane ①) — UAQ, Interface Tracking, WaveUtil
2. **Intake form** (lane ②) — Generated gap workbook
3. **Legacy completed intake** (lane ③) — Seven-sheet App Data Capture workbook

Each lane has:
- Distinct upload endpoint
- Clear description of what belongs there
- Warning about what doesn't belong there

### Identity-First Processing

Legacy intake workbooks are processed identity-first:

1. Extract all identifiers from workbook
2. Resolve application identity
3. Only proceed to field mapping if identity succeeds
4. Never create candidates before identity is confirmed

This prevents:
- Candidates attached to wrong application
- Ambiguous or conflicting imports
- Silent identity failures

### Explicit Intake Selection

Unlike gap workbooks (which embed intake ID), legacy workbooks require explicit intake selection:

- User sees all eligible intakes for the matched application
- User must choose which intake receives the answers
- Current intake is highlighted but not auto-selected
- No automatic intake creation

This ensures:
- User controls which intake is updated
- No accidental overwrites
- Clear audit trail

---

## Testing Status

### Unit Tests

- ✅ 41 tests passing (L01)
- ✅ Contract inspection (11 tests)
- ✅ Identity extraction (16 tests)
- ✅ Identity resolution (14 tests)

### Integration Tests

- ⏳ Web integration tests (pending)
- ⏳ End-to-end browser tests (pending)

### Database Tests

- ✅ Migration 0013 on SQLite
- ✅ Migration 0013 on Oracle

---

## Next Steps

1. **Complete L03:**
   - Implement process route
   - Add web integration tests

2. **L04 — Field Mappings:**
   - Define exact mappings for all sheets
   - Implement deterministic parsing
   - Create findings for unknown fields

3. **L05 — Stale-Answer Protection:**
   - Capture baseline revision
   - Implement acceptance-time checks

4. **L06 — E2E Verification:**
   - Browser journey
   - Full regression suite

---

**Status:** L01 ✅ | L02 ✅ | L03 🔄 (routes and templates complete, processing pending)
