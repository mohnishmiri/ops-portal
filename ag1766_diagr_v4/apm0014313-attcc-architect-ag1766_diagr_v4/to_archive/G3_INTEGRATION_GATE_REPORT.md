# G3 Integration Gate Report — Wave A Verification

**Date:** 2026-09-11  
**Gate:** G3 (Wave A Integration)  
**Status:** 🔄 **IN PROGRESS**

---

## Executive Summary

G3 Integration Gate verifies that Wave A Oracle foundation work integrates cleanly with the existing SQLite codebase. This gate runs full persistence contract tests on both dialects to ensure no regressions and identify any Oracle-specific behaviors.

**Current Status:**
- ✅ SQLite persistence contracts: 118/120 passing (98.3%)
- ⏳ Oracle persistence contracts: Pending
- ⚠️ 2 issues identified requiring fixes

---

## Test Results

### SQLite Persistence Contracts

**Command:**
```bash
python -m pytest tests/contract/persistence/ -v
```

**Results:**
```
118 passed
2 failed
27 skipped (Oracle tests - expected)
Total: 147 tests
Time: 5.01s
```

**Pass Rate:** 98.3% (118/120 non-Oracle tests)

---

## Issues Identified

### Issue 1: Constraint Name Too Long for Oracle ❌

**Test:** `test_all_constraint_names_oracle_safe`

**Error:**
```
AssertionError: Constraint/index names exceed Oracle 12c 30-char limit:
  evidence_items.constraint('uq_evidence_items_app_intake_storage') = 36 chars
```

**Root Cause:**
The unique constraint name `uq_evidence_items_app_intake_storage` is 36 characters long, exceeding Oracle's 30-character limit for identifier names (Oracle 12c and earlier).

**Impact:**
- ❌ Migration 0011 will fail on Oracle 12c
- ✅ May work on Oracle 23ai (supports longer identifiers)
- ⚠️ Breaks Oracle portability goal

**Fix Required:**
Shorten the constraint name to ≤30 characters:
- Current: `uq_evidence_items_app_intake_storage` (36 chars)
- Proposed: `uq_evidence_app_intake_storage` (30 chars)
- Alternative: `uq_evid_app_intake_storage` (26 chars)

**Files to Update:**
- Migration `0011_scope_evidence_deduplication.py`
- Model `src/migration_intake/persistence/models_evidence.py`

---

### Issue 2: Evidence Duplicate Storage Key Test Failing ❌

**Test:** `test_duplicate_storage_key_raises_integrity_error`

**Error:**
```
Failed: DID NOT RAISE <class 'sqlalchemy.exc.IntegrityError'>
```

**Root Cause:**
The test expects an `IntegrityError` when inserting a duplicate storage key, but the constraint may not be properly defined or the test setup is incorrect.

**Location:**
`tests/contract/persistence/test_evidence_repository.py:227`

**Impact:**
- ⚠️ Evidence deduplication may not work correctly
- ⚠️ Duplicate evidence files could be stored
- ⚠️ Storage integrity not guaranteed

**Investigation Needed:**
1. Check if unique constraint exists on `evidence_items.storage_key`
2. Verify constraint is scoped correctly (application + intake + storage_key)
3. Review migration 0011 changes

---

## Detailed Test Breakdown

### Passing Test Categories

| Category | Tests | Status |
|----------|-------|--------|
| Answer Repository | 4 | ✅ All passing |
| Application Repository | 6 | ✅ All passing |
| Candidate Repository | 14 | ✅ All passing |
| Catalog Publication | 9 | ✅ All passing |
| Catalog Repository | 4 | ✅ All passing |
| Database Config | 3 | ✅ All passing |
| Evidence Repository | 4/5 | ⚠️ 1 failure |
| Import Repository | 7 | ✅ All passing |
| Model Metadata | 14/15 | ⚠️ 1 failure |
| Portable Types (SQLite) | 21 | ✅ All passing |
| Snapshot Repository | 6 | ✅ All passing |
| UoW Atomicity | 4 | ✅ All passing |
| Wave Util Repository | 7 | ✅ All passing |

### Skipped Tests

| Category | Tests | Reason |
|----------|-------|--------|
| Oracle Migration Idempotency | 6 | ORACLE_TEST_URL not configured |
| Oracle Portable Types | 21 | ORACLE_TEST_URL not configured |

**Total Skipped:** 27 tests (expected - Oracle-specific)

---

## Next Steps

### 1. Fix Constraint Name Length ⏳

**Priority:** HIGH  
**Effort:** LOW

**Steps:**
1. Update migration 0011 to use shorter constraint name
2. Update model definition to match
3. Test on both SQLite and Oracle
4. Verify no breaking changes

**Estimated Time:** 30 minutes

---

### 2. Fix Evidence Duplicate Storage Key Test ⏳

**Priority:** HIGH  
**Effort:** MEDIUM

**Steps:**
1. Review migration 0011 constraint definition
2. Check if constraint is properly created
3. Verify test expectations are correct
4. Fix either constraint or test
5. Verify on both SQLite and Oracle

**Estimated Time:** 1 hour

---

### 3. Run Oracle Persistence Contracts ⏳

**Priority:** HIGH  
**Effort:** LOW

**Prerequisites:**
- Issues 1 and 2 fixed
- Oracle container running
- ORACLE_TEST_URL configured

**Command:**
```bash
export ORACLE_TEST_URL=oracle+oracledb://migration_intake_test:test123@localhost:1521?service_name=FREEPDB1
python -m pytest tests/contract/persistence/ -v -m oracle
```

**Expected:** 27 Oracle-specific tests should pass

---

### 4. Full Test Suite Verification ⏳

**Priority:** MEDIUM  
**Effort:** LOW

**Command:**
```bash
python -m pytest tests/ -v
```

**Expected:** No regressions in existing functionality

---

### 5. Documentation Updates ⏳

**Priority:** MEDIUM  
**Effort:** LOW

**Files to Update:**
- `STATE.md` — Update with Oracle readiness status
- `ORACLE_WAVE_A_COMPLETE.md` — Add G3 gate results
- `LEARNINGS.md` — Document constraint name length issue

---

## Oracle Availability

### Docker Container Status

```
NAMES         STATUS                 PORTS
oracle-free   Up 2 hours (healthy)   0.0.0.0:1521->1521/tcp
```

**Status:** ✅ Running and healthy

### Connection Details

```
Host:         localhost
Port:         1521
Service:      FREEPDB1
User:         migration_intake_test
Password:     test123 (from setup)
```

---

## G3 Gate Criteria

### Required for Gate Passage

| Criterion | Status | Notes |
|-----------|--------|-------|
| SQLite persistence contracts passing | ⚠️ 98.3% | 2 failures to fix |
| Oracle persistence contracts passing | ⏳ Pending | After fixes |
| No regressions in existing tests | ⏳ Pending | Full suite verification |
| Oracle-specific behaviors documented | ⏳ Pending | After Oracle tests |
| STATE.md updated | ⏳ Pending | After completion |

### Optional (Wave B)

| Item | Status | Notes |
|------|--------|-------|
| Repository group testing (O05A-D) | ⏳ Wave B | Not required for G3 |
| Startup/concurrency testing (O06A-C) | ⏳ Wave C | Not required for G3 |
| Performance benchmarking | ⏳ Future | Not required for G3 |

---

## Risk Assessment

### High Risk

1. **Constraint name length** — Blocks Oracle 12c compatibility
   - Mitigation: Fix immediately before Oracle tests

2. **Evidence deduplication** — Data integrity issue
   - Mitigation: Investigate and fix constraint

### Medium Risk

1. **Oracle-specific test failures** — Unknown until tests run
   - Mitigation: Run Oracle tests after fixes

### Low Risk

1. **Performance differences** — Expected between SQLite and Oracle
   - Mitigation: Document, optimize in future wave

---

## Timeline

### Immediate (Today)

- ✅ Run SQLite persistence contracts
- ⏳ Fix constraint name length issue
- ⏳ Fix evidence duplicate storage key test
- ⏳ Run Oracle persistence contracts

### Short Term (This Week)

- ⏳ Full test suite verification
- ⏳ Documentation updates
- ⏳ G3 gate completion report

### Medium Term (Next Week)

- ⏳ Wave B: Repository group testing (O05A-D)
- ⏳ Wave C: Startup/concurrency testing (O06A-C)
- ⏳ G4/G5 integration gates

---

## Summary

G3 Integration Gate is **IN PROGRESS** with 2 issues identified:

1. ❌ Constraint name too long for Oracle (36 chars > 30 char limit)
2. ❌ Evidence duplicate storage key test failing

**Next Actions:**
1. Fix constraint name length
2. Fix evidence deduplication test
3. Run Oracle persistence contracts
4. Verify full test suite
5. Update documentation

**Estimated Time to Complete:** 2-3 hours

---

**Report Generated:** 2026-09-11  
**Generated By:** Devin  
**Status:** Draft - Awaiting fixes and Oracle test results
