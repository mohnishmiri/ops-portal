# O01 Complete — Clean Alembic Migration Execution

**Date:** 2026-09-10
**Packet:** O01 (Clean Alembic migration to Oracle head)
**Status:** ✅ COMPLETE

---

## Summary

All 9 Alembic migrations (0001, 0002, 0003, 0004, 0006, 0007, 0008, 0009, 0010) executed successfully against an empty Oracle Free schema. One Oracle-specific defect was discovered and fixed.

---

## Defect found and fixed

### Issue: Migration 0010 used `sa.JSON()` instead of portable type

**Error:**
```
sqlalchemy.exc.UnsupportedCompilationError: Compiler <OracleTypeCompiler> can't render element of type JSON
```

**Root cause:**
Migration `0010_import_identity.py` line 29 used `sa.JSON()` which is not supported by Oracle's type compiler.

**Fix:**
Replaced `sa.JSON()` with `CanonicalJSON()` from `migration_intake.persistence.types`.

**Files changed:**
- `src/migration_intake/persistence/migrations/versions/0010_import_identity.py`
  - Added import: `from migration_intake.persistence.types import CanonicalJSON`
  - Changed: `sa.JSON()` → `CanonicalJSON()`

**Verification:**
- ✅ Oracle migration now succeeds
- ✅ SQLite migration still succeeds (regression check passed)

---

## Migration execution log

### Oracle (target dialect)

```
$ alembic upgrade head
INFO  [alembic.runtime.migration] Context impl OracleImpl.
INFO  [alembic.runtime.migration] Running upgrade  -> 0001, Core actors, applications, catalog releases/definitions, intakes, answers, audit.
INFO  [alembic.runtime.migration] Running upgrade 0001 -> 0002, Evidence items, WaveUtil rows, and WaveUtil revisions.
INFO  [alembic.runtime.migration] Running upgrade 0002 -> 0003, Import runs, sheet results, and findings.
INFO  [alembic.runtime.migration] Running upgrade 0003 -> 0004, Candidates and answer evidence links.
INFO  [alembic.runtime.migration] Running upgrade 0004 -> 0006, Intake snapshots for frozen intakes.
INFO  [alembic.runtime.migration] Running upgrade 0006 -> 0007, Add catalog question metadata required by registry-driven editors.
INFO  [alembic.runtime.migration] Running upgrade 0007 -> 0008, Repair answer metadata missing from databases stamped at earlier revisions.
INFO  [alembic.runtime.migration] Running upgrade 0008 -> 0009, Repair answer revision metadata missing from historically stamped databases.
INFO  [alembic.runtime.migration] Running upgrade 0009 -> 0010, Persist source identity decisions on import runs.

$ alembic current
0010 (head)
```

**Result:** ✅ All migrations executed successfully

### SQLite (baseline dialect)

```
$ alembic upgrade head
INFO  [alembic.runtime.migration] Context impl SQLiteImpl.
[... all 9 migrations executed ...]

$ alembic current
0010 (head)
```

**Result:** ✅ No regression - SQLite migrations still work

---

## Oracle schema verification

**Tables created:** 23
**Expected tables:** 22 (from ORM) + 1 (alembic_version) = 23 ✅

**Table list:**
```
ACTORS
ALEMBIC_VERSION
ANSWER_EVIDENCE_LINKS
ANS_INSTANCES
ANS_REVISIONS
APPLICATIONS
APP_IDENTIFIERS
AUDIT_EVENTS
CANDIDATES
CANDIDATE_FINDINGS
CAT_OPTIONS
CAT_QUESTIONS
CAT_RELEASES
CAT_SECTIONS
CAT_SRC_RELS
EVIDENCE_ITEMS
IMPORT_FINDINGS
IMPORT_RUNS
IMPORT_SHEET_RESULTS
INTAKES
INT_SNAPS
WAVE_UTIL_REVISIONS
WAVE_UTIL_ROWS
```

**Naming verification:**
- ✅ All table names are uppercase (Oracle default)
- ✅ All table names ≤ 30 characters (Oracle 12c compatibility)
- ✅ No naming collisions after case normalization

---

## Privilege verification

**Grants used:**
- `CREATE SESSION` — required for connection
- `CREATE TABLE` — required for migrations 0001-0010
- `CREATE SEQUENCE` — **not yet required** (no sequences in current migrations)
- `CREATE VIEW` — **not yet required** (no views in current migrations)

**Additional grants needed:** None at this time.

**Note:** If future migrations add sequences or views, the privilege set documented in `ORACLE_SCHEMA_SETUP.md` already includes them.

---

## Cleanup utility

Created `tests/oracle_cleanup_schema.py` to drop all tables and reset the schema for fresh migration testing.

**Usage:**
```bash
python tests/oracle_cleanup_schema.py
```

**Safety:** Only drops tables owned by the connected user (not SYSTEM).

---

## Gate G1 acceptance criteria

Per `ORACLE_INTEGRATION_DESIGN.md` section 10 (packet O01):

- ✅ All migrations execute without error on Oracle
- ✅ `alembic current` reports correct head (0010)
- ✅ Table count matches ORM metadata (22 tables + alembic_version)
- ✅ No privilege escalation required beyond initial grants
- ✅ SQLite migrations still work (no regression)
- ✅ Defects found are documented and fixed
- ✅ Schema cleanup utility provided

**Status:** Gate G1 PASSED — ready for Wave A parallel dispatch

---

## Next steps

Proceed to **Wave A parallel implementation:**

1. **O02:** Portable type contracts (UUID, UTC, Decimal, JSON, SHA256)
2. **O03:** Migration path hardening (0007-0009 repair validation)
3. **O04:** Runtime configuration (pool settings, redaction, shutdown)

These three packets can execute **in parallel** as they have no dependencies on each other.

See: `ORACLE_INTEGRATION_DESIGN.md` section 11 (Wave A)

---

## Lessons learned

1. **Generic SQLAlchemy types are not portable.** Always use custom `TypeDecorator` classes from `persistence.types` for cross-dialect compatibility.
2. **Migrations must be tested on target dialect.** The `sa.JSON()` issue was silent on SQLite but fatal on Oracle.
3. **Oracle schema cleanup is non-trivial.** The cleanup utility handles `CASCADE CONSTRAINTS` and `PURGE` correctly.
4. **Alembic `env.py` already loads `.env`.** No additional configuration needed for local Oracle testing.

---

## Files created/modified

**Created:**
- `tests/oracle_cleanup_schema.py` — Schema reset utility

**Modified:**
- `src/migration_intake/persistence/migrations/versions/0010_import_identity.py` — Fixed JSON type portability

**No changes to:**
- ORM models (already using portable types)
- Application code
- Test fixtures
- Configuration
