# O02 Progress — Portable Type Contracts

**Date:** 2026-09-11
**Packet:** O02 (Portable type contracts for Oracle)
**Status:** 🟡 TESTS WRITTEN — AWAITING DOCKER

---

## Summary

Created comprehensive Oracle-specific portable type contract tests covering all 5 portable types (PortableUUID, PortableUTC, PortableDecimal, CanonicalJSON, Sha256Hex) with 21 test cases.

---

## Deliverables

### 1. Oracle portable type test suite

**File:** `tests/contract/persistence/test_portable_types_oracle.py`
**Test count:** 21 tests
**Coverage:**

#### PortableUUID (3 tests)
- ✅ Round-trip storage and retrieval
- ✅ Physical storage as VARCHAR2(36)
- ✅ Nullable column handling

#### PortableUTC (4 tests)
- ✅ Round-trip with timezone awareness
- ✅ Non-UTC input normalization to UTC
- ✅ Naive datetime rejection
- ✅ Physical storage as VARCHAR2 (ISO text)

#### PortableDecimal (3 tests)
- ✅ Round-trip without precision loss
- ✅ Nullable column handling
- ✅ Physical storage as Oracle NUMBER

#### CanonicalJSON (6 tests)
- ✅ Dict payload round-trip
- ✅ List payload round-trip
- ✅ Nullable column handling
- ✅ Physical storage as CLOB
- ✅ **LOB handle leak prevention** (critical Oracle-specific test)
- ✅ Empty dict vs NULL distinction

#### Sha256Hex (3 tests)
- ✅ Round-trip with lowercase normalization
- ✅ Nullable column handling
- ✅ Physical storage as VARCHAR2(64)

#### Cross-dialect consistency (2 tests)
- ✅ Table name uppercase normalization
- ✅ Column name uppercase normalization

---

## Key Oracle-specific tests

### 1. LOB handle leak prevention

```python
def test_oracle_json_no_lob_handle_leak(oracle_engine: Engine, oracle_session: Session) -> None:
    """
    Verify that CLOB values are fully materialized and don't leak LOB handles.

    Oracle LOB handles must be closed within the session that created them.
    CanonicalJSON must return a plain Python dict/list, not a lazy LOB proxy.
    """
```

**Why this matters:** Oracle CLOB columns can return lazy LOB handles that become invalid after the session closes. This test ensures `CanonicalJSON.process_result_value()` fully materializes the JSON text before returning it to application code.

### 2. Empty string vs NULL

```python
def test_oracle_json_empty_dict_vs_null(oracle_session: Session) -> None:
    """
    Empty dict {} is stored as '{}' text, not NULL.

    Oracle treats empty strings as NULL, but CanonicalJSON stores '{}' which
    is non-empty, so this should work correctly.
    """
```

**Why this matters:** Oracle's empty string = NULL behavior could cause semantic issues. This test verifies that `{}` (two characters) is stored correctly and not converted to NULL.

### 3. Physical storage verification

Each type has a test that uses SQLAlchemy's `inspect()` to verify the actual Oracle column type:
- UUID → VARCHAR2(36)
- UTC → VARCHAR2(32)
- Decimal → NUMBER(precision, scale)
- JSON → CLOB
- SHA256 → VARCHAR2(64)

---

## Test execution blocked

**Error:** `ConnectionRefusedError: [WinError 10061] No connection could be made because the target machine actively refused it`

**Root cause:** Docker Desktop is not running.

**Resolution required:**
1. Start Docker Desktop
2. Verify Oracle container is running: `docker ps | grep oracle`
3. Run tests: `python -m pytest tests/contract/persistence/test_portable_types_oracle.py -v -m oracle`

---

## Fixture design

### Module-scoped Oracle engine

```python
@pytest.fixture(scope="module")
def oracle_engine() -> Engine:
    """
    Oracle test engine with dedicated schema.

    Creates test tables at module start, drops them at module end.
    Uses NullPool to avoid connection pooling issues in tests.
    """
```

**Benefits:**
- Tables created once per module (fast)
- Automatic cleanup on module teardown
- Security check: rejects SYSTEM/SYS connections
- Loads `ORACLE_TEST_URL` from `.env` automatically

### Function-scoped session

```python
@pytest.fixture()
def oracle_session(oracle_engine: Engine) -> Session:
    """Fresh Oracle session for each test."""
```

**Benefits:**
- Each test gets a clean session
- Automatic rollback on test failure
- No cross-test contamination

---

## Comparison with SQLite tests

The Oracle tests mirror the structure of `test_portable_types.py` (SQLite) but add:

1. **Oracle-specific physical storage tests** (VARCHAR2, CLOB, NUMBER)
2. **LOB handle leak test** (Oracle-specific concern)
3. **Case normalization tests** (Oracle uppercases identifiers)
4. **Empty string vs NULL test** (Oracle-specific behavior)
5. **Module-scoped fixtures** (faster than per-test table creation)

---

## Next steps

### Immediate (user action required)

1. **Start Docker Desktop**
2. **Verify Oracle container:** `docker ps | grep oracle-free`
3. **Run Oracle type tests:**
   ```bash
   python -m pytest tests/contract/persistence/test_portable_types_oracle.py -v -m oracle
   ```

### Expected result

```
============================= test session starts =============================
collected 21 items

tests/contract/persistence/test_portable_types_oracle.py::test_oracle_uuid_round_trip PASSED
tests/contract/persistence/test_portable_types_oracle.py::test_oracle_uuid_stored_as_varchar2 PASSED
[... 19 more PASSED ...]

============================= 21 passed in X.XXs ==============================
```

### After tests pass

1. **Run SQLite regression check:**
   ```bash
   python -m pytest tests/contract/persistence/test_portable_types.py -v
   ```
   Expected: All existing SQLite tests still pass (no regression)

2. **Mark O02 complete** and proceed to O03 (migration path hardening) or O04 (runtime config)

---

## Files created

- `tests/contract/persistence/test_portable_types_oracle.py` (489 lines, 21 tests)

## Files modified

None (O02 is additive only)

---

## Acceptance criteria (from ORACLE_INTEGRATION_DESIGN.md)

Per section 11, packet O02:

- ✅ Oracle-specific type contract tests written
- ✅ LOB handle leak test included
- ✅ Empty string vs NULL test included
- ✅ Physical storage verification tests included
- ✅ Module-scoped fixtures for performance
- ✅ Security check (rejects SYSTEM/SYS)
- 🟡 **Tests execution pending Docker startup**

**Status:** O02 implementation complete, awaiting verification.

---

## Lessons learned

1. **Oracle CLOB handling is critical.** The `process_result_value()` method must fully materialize LOB values before returning them to avoid "LOB variable no longer valid" errors after session close.

2. **Physical storage tests catch dialect differences.** Verifying that UUID maps to VARCHAR2(36) and JSON maps to CLOB ensures the portable types work as designed.

3. **Module-scoped fixtures are essential for Oracle.** Creating/dropping tables for every test would be prohibitively slow. Module scope creates tables once and reuses them.

4. **Case normalization matters.** Oracle uppercases unquoted identifiers, so tests must use `.upper()` when comparing table/column names from `inspect()`.

5. **Empty string = NULL is a real concern.** While `CanonicalJSON` stores `'{}'` (non-empty), future types that store empty strings must handle this explicitly.
