# O02 Complete — Portable Type Contracts

**Date:** 2026-09-11
**Packet:** O02 (Portable type contracts for Oracle)
**Status:** ✅ COMPLETE

---

## Summary

Created and verified comprehensive Oracle-specific portable type contract tests. All 5 portable types (PortableUUID, PortableUTC, PortableDecimal, CanonicalJSON, Sha256Hex) behave identically on Oracle and SQLite.

**Test results:**
- ✅ **21/21 Oracle tests PASSED**
- ✅ **21/21 SQLite tests PASSED** (no regression)

---

## Deliverables

### 1. Oracle portable type test suite

**File:** `tests/contract/persistence/test_portable_types_oracle.py`
**Lines:** 489
**Test count:** 21 tests
**Execution time:** ~5.3 seconds

### Test coverage by type

#### PortableUUID (3 tests)
- ✅ `test_oracle_uuid_round_trip` — UUID stored and retrieved as uuid.UUID object
- ✅ `test_oracle_uuid_stored_as_varchar2` — Physical storage as VARCHAR2(36)
- ✅ `test_oracle_uuid_nullable_column_stores_none` — NULL handling

#### PortableUTC (4 tests)
- ✅ `test_oracle_utc_round_trip` — Timezone-aware datetime round-trip
- ✅ `test_oracle_utc_normalizes_non_utc_input` — Non-UTC input converted to UTC
- ✅ `test_oracle_utc_rejects_naive_datetime` — Naive datetime rejected
- ✅ `test_oracle_utc_stored_as_varchar2` — Physical storage as VARCHAR2 (ISO text)

#### PortableDecimal (3 tests)
- ✅ `test_oracle_decimal_round_trip` — Precision-preserving round-trip
- ✅ `test_oracle_decimal_null_explicit` — NULL handling
- ✅ `test_oracle_decimal_stored_as_number` — Physical storage as Oracle NUMBER

#### CanonicalJSON (6 tests)
- ✅ `test_oracle_json_round_trip` — Dict payload round-trip
- ✅ `test_oracle_json_list_round_trip` — List payload round-trip
- ✅ `test_oracle_json_null_explicit` — NULL handling
- ✅ `test_oracle_json_stored_as_clob` — Physical storage as CLOB
- ✅ `test_oracle_json_no_lob_handle_leak` — **Critical: LOB handle leak prevention**
- ✅ `test_oracle_json_empty_dict_vs_null` — Empty dict `{}` vs NULL distinction

#### Sha256Hex (3 tests)
- ✅ `test_oracle_sha256_hex_round_trip` — Lowercase normalization round-trip
- ✅ `test_oracle_sha256_hex_null_explicit` — NULL handling
- ✅ `test_oracle_sha256_hex_stored_as_varchar2` — Physical storage as VARCHAR2(64)

#### Cross-dialect consistency (2 tests)
- ✅ `test_oracle_table_names_are_uppercase` — Oracle identifier case normalization
- ✅ `test_oracle_column_names_are_uppercase` — Column name case normalization

---

## Critical Oracle-specific tests

### 1. LOB handle leak prevention

```python
def test_oracle_json_no_lob_handle_leak(oracle_engine: Engine, oracle_session: Session) -> None:
    """
    Verify that CLOB values are fully materialized and don't leak LOB handles.

    Oracle LOB handles must be closed within the session that created them.
    CanonicalJSON must return a plain Python dict/list, not a lazy LOB proxy.
    """
    pk = _uid()
    payload = {"large": "x" * 5000}  # Force CLOB storage
    oracle_session.add(_OracleJSONRow(id=pk, payload=payload))
    oracle_session.commit()

    # Fetch and close session
    row = oracle_session.get(_OracleJSONRow, pk)
    assert row is not None
    retrieved_payload = row.payload
    oracle_session.close()

    # Access payload AFTER session is closed
    # If LOB handle leaked, this would raise "LOB variable no longer valid"
    assert retrieved_payload == payload
    assert isinstance(retrieved_payload, dict)
```

**Why this matters:** Without proper materialization, accessing JSON data after session close would raise `DatabaseError: LOB variable no longer valid after commit`. This test verifies that `CanonicalJSON.process_result_value()` returns a fully materialized Python object.

**Result:** ✅ PASSED — No LOB handle leaks detected

### 2. Empty string vs NULL

```python
def test_oracle_json_empty_dict_vs_null(oracle_session: Session) -> None:
    """
    Empty dict {} is stored as '{}' text, not NULL.

    Oracle treats empty strings as NULL, but CanonicalJSON stores '{}' which
    is non-empty, so this should work correctly.
    """
```

**Why this matters:** Oracle's `empty string = NULL` behavior could cause semantic issues. This test verifies that `{}` (two-character string) is stored correctly and not converted to NULL.

**Result:** ✅ PASSED — Empty dict stored as `'{}'`, not NULL

### 3. Physical storage verification

Each type verifies the actual Oracle column type using SQLAlchemy's `inspect()`:

| Portable Type | Oracle Physical Type | Verified |
|--------------|---------------------|----------|
| PortableUUID | VARCHAR2(36) | ✅ |
| PortableUTC | VARCHAR2(32) | ✅ |
| PortableDecimal | NUMBER(precision, scale) | ✅ |
| CanonicalJSON | CLOB | ✅ |
| Sha256Hex | VARCHAR2(64) | ✅ |

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
- Tables created once per module (5.3s vs ~60s if per-test)
- Automatic cleanup on module teardown
- Security check: rejects SYSTEM/SYS connections
- Loads `ORACLE_TEST_URL` from `.env` automatically

### Function-scoped session

```python
@pytest.fixture()
def oracle_session(oracle_engine: Engine) -> Session:
    """Fresh Oracle session for each test."""
    session = Session(oracle_engine)
    yield session
    session.rollback()
    session.close()
```

**Benefits:**
- Each test gets a clean session
- Automatic rollback on test failure
- No cross-test contamination

---

## Regression verification

**SQLite baseline tests:** All 21 tests still pass (0.34s)

```
tests/contract/persistence/test_portable_types.py::test_uuid_round_trip PASSED
tests/contract/persistence/test_portable_types.py::test_uuid_stored_as_string_in_database PASSED
[... 19 more PASSED ...]
============================= 21 passed in 0.34s ==============================
```

**Conclusion:** No regression — portable types work identically on both dialects.

---

## Files created

- `tests/contract/persistence/test_portable_types_oracle.py` (489 lines, 21 tests)

## Files modified

- `tests/contract/persistence/test_portable_types_oracle.py` (1 fix: UUID query specificity)

---

## Acceptance criteria (from ORACLE_INTEGRATION_DESIGN.md)

Per section 11, packet O02:

- ✅ Oracle-specific type contract tests written
- ✅ LOB handle leak test included and passing
- ✅ Empty string vs NULL test included and passing
- ✅ Physical storage verification tests included and passing
- ✅ Module-scoped fixtures for performance
- ✅ Security check (rejects SYSTEM/SYS)
- ✅ All 21 tests execute and pass on Oracle
- ✅ SQLite regression check passes (no regressions)

**Status:** O02 COMPLETE ✅

---

## Lessons learned

### 1. Oracle CLOB handling is critical

The `process_result_value()` method in `CanonicalJSON` correctly calls `json.loads(str(value))`, which fully materializes the CLOB before returning it. This prevents "LOB variable no longer valid" errors.

**Key insight:** Always convert LOB values to Python strings/objects within `process_result_value()`, never return lazy LOB proxies.

### 2. Physical storage tests catch dialect differences

Verifying that UUID maps to VARCHAR2(36) and JSON maps to CLOB ensures the portable types work as designed. These tests would catch if SQLAlchemy's Oracle dialect changed its type mappings.

### 3. Module-scoped fixtures are essential for Oracle

Creating/dropping tables for every test would be ~12x slower (60s vs 5s). Module scope creates tables once and reuses them across all tests in the module.

### 4. Case normalization matters

Oracle uppercases unquoted identifiers. Tests must use `.upper()` when comparing table/column names from `inspect()`:

```python
id_col = next(c for c in columns if c["name"].upper() == "ID")
```

### 5. Empty string = NULL is handled correctly

`CanonicalJSON` stores `'{}'` (non-empty string), so Oracle's empty-string behavior doesn't affect it. Future types that store empty strings must handle this explicitly (e.g., store a sentinel value like `'__EMPTY__'`).

### 6. Query specificity in shared fixtures

When using module-scoped fixtures, tests must query for specific rows (e.g., `WHERE id = :pk`) rather than assuming they're the only row (`WHERE ROWNUM = 1`).

---

## Next steps

O02 is complete. Ready to proceed to:

1. **O03:** Migration path hardening (0007-0009 repair validation)
2. **O04:** Runtime configuration (pool settings, redaction, shutdown)

Both O03 and O04 can execute in parallel as they have no dependencies on each other.

See: `ORACLE_INTEGRATION_DESIGN.md` section 11 (Wave A completion)

---

## Test execution commands

### Run Oracle portable type tests
```bash
python -m pytest tests/contract/persistence/test_portable_types_oracle.py -v -m oracle
```

### Run SQLite portable type tests (regression check)
```bash
python -m pytest tests/contract/persistence/test_portable_types.py -v
```

### Run both (full portable type verification)
```bash
python -m pytest tests/contract/persistence/test_portable_types*.py -v
```
