# G0 Baseline — Oracle Enablement Start

**Date:** 2026-09-10
**Lead:** Principal architect executing ORACLE_INTEGRATION_DESIGN.md
**Branch:** ag1766_diagr_v4
**Working tree:** Modified files present (52 changed, pre-existing work)

---

## Baseline inventory

### Alembic migration chain

**Current head:** `0010`
**All revisions:** `0001`, `0002`, `0003`, `0004`, `0006`, `0007`, `0008`, `0009`, `0010`
**Note:** Revision `0005` intentionally does not exist; numbering is not contiguous.

### ORM schema

**Table count:** 22
**Tables:** actors, ans_instances, ans_revisions, answer_evidence_links, app_identifiers, applications, audit_events, candidate_findings, candidates, cat_options, cat_questions, cat_releases, cat_sections, cat_src_rels, evidence_items, import_findings, import_runs, import_sheet_results, int_snaps, intakes, wave_util_revisions, wave_util_rows

### SQLite persistence contract baseline

**Command:** `python -m pytest tests/contract/persistence/ -q --tb=no`
**Result:** 114 passed, 6 failed in 4.18s

**Known failures (pre-existing):**
- `test_catalog_repository.py::TestListReleases::test_returns_all_releases_regardless_of_pub_state`
- `test_catalog_repository.py::TestListReleases::test_orders_newest_first_by_published_at`
- `test_catalog_repository.py::TestListReleases::test_never_published_release_sorts_after_published_releases`
- `test_catalog_repository.py::TestListReleases::test_release_shape_matches_release_to_dict_fields`
- `test_catalog_repository.py::TestCountByCatalogId::test_count_is_zero_when_no_intakes_pinned`
- `test_catalog_repository.py::TestCountByCatalogId::test_count_matches_exact_number_of_pinned_intakes`

These 6 failures are **not Oracle-related**; they exist in the current SQLite baseline and must not be counted as Oracle regressions.

### Current STATE.md baseline

**Phase:** R5 gate COMPLETE
**Test count reported:** 1787 tests
**Status:** Full service layer, 25 response types, 22-table ORM, catalog publication, answer service, candidate pipeline, evidence routes, WaveUtil, snapshots, readiness/freeze, browser suite (21 tests)

---

## G0 Decisions

Following ORACLE_INTEGRATION_DESIGN.md section 9, the following decisions are recorded:

### 1. Oracle driver mode
**Decision:** Thin mode only for local validation.
**Rationale:** No thick-mode Oracle Instant Client required; simpler setup; sufficient for SQLAlchemy dialect proof.

### 2. Oracle test schema identity
**Approved pattern:** Dedicated non-SYSTEM user/schema named `migration_intake` or `migration_intake_test`.
**Forbidden:** `SYSTEM`, `SYS`, or any production/shared schema.
**Enforcement:** Tests must assert configured schema identity and fail closed if unapproved.

### 3. Migration owner vs runtime user
**Decision:** Same user for local Oracle Free validation only.
**Rationale:** Simplifies local spike; production will use separate migration-owner (DDL) and runtime (DML) identities.
**Documentation requirement:** Explicitly note this exception in O00 deliverable.

### 4. Privilege discovery
**Starting grants:** `CREATE SESSION`, table/index/constraint creation via ownership, quota on USERS tablespace.
**Add incrementally:** `CREATE VIEW`, `CREATE SEQUENCE`, `CREATE PROCEDURE` only if migration tests fail without them.
**Forbidden convenience grants:** `DBA`, `RESOURCE`, `CONNECT`, `UNLIMITED TABLESPACE`.

### 5. Data cutover scope
**Decision:** **NO** — existing SQLite data preservation is **out of scope** for initial enablement.
**Rationale:** No production SQLite database exists; local development databases are disposable; Oracle enablement proves dialect compatibility only.
**Implication:** Packets O07–O09 are **not executed**; G6 gate is **skipped**.

### 6. Oracle CI scope
**Decision:** **DEFER** until local G5 passes.
**Rationale:** No CI Oracle container until local validation is stable and registry/license/secret boundary is approved.

### 7. Production/shared Oracle endpoint protection
**Verification:** No `DATABASE_URL` or test configuration points to production/shared Oracle.
**Current Oracle setup:** Local Docker container `oracle-free`, service `FREEPDB1`, localhost:1521.
**Confirmation:** This is a local, disposable, developer-owned environment only.

---

## Verification of current-state facts (section 4)

- ✅ Optional dependency declares `oracledb>=2.2.0,<3.0` in `pyproject.toml`
- ✅ `oracle` pytest marker exists in `pyproject.toml` markers list
- ❌ No Oracle fixture or test harness exists (expected; will be created in O02)
- ✅ `create_engine_from_url()` only applies SQLite pragmas; no Oracle config exists
- ✅ `Settings` declares `db_pool_size`, `db_max_overflow`, `db_pool_recycle_seconds`
- ❌ `create_app()` currently passes only SQLite `check_same_thread` (will be fixed in O04)
- ✅ Alembic reads `DATABASE_URL`, uses `NullPool`, enables batch mode only for SQLite
- ✅ Current migration revisions confirmed: 0001, 0002, 0003, 0004, 0006, 0007, 0008, 0009, 0010
- ✅ Persistence contract tests use `Base.metadata.create_all()` on fresh SQLite files
- ✅ Portable type tests define private tables and use raw SQL for physical assertions
- ✅ Application startup calls `ensure_catalog_published(session_factory)` before yielding
- ✅ `STATE.md` contains live regression baseline (1787 tests, 6 known contract failures)

---

## Scope exclusions confirmed

The following are **explicitly out of scope** for Oracle enablement:

- ❌ Thick-mode Oracle Client
- ❌ Wallets, mTLS, RAC, Data Guard, TDE administration
- ❌ Partitioning, index hints, result cache, NLS session tuning
- ❌ Running every unit/browser test on both dialects
- ❌ Generic bidirectional database synchronization
- ❌ Application-level RMAN/Data Pump replacement
- ❌ SQLite-to-Oracle data cutover (no existing production data)
- ❌ Oracle CI container (deferred)
- ❌ Enterprise Oracle certification (external gate G7)

---

## Next steps

**Immediate:** Proceed to O00 (Oracle preflight and dedicated schema).

**O00 prerequisites:**
1. User/admin creates dedicated Oracle schema using secret entered outside repository
2. Verify Docker container health without exposing credentials
3. Install `oracledb` driver: `pip install -e ".[oracle]"`
4. Verify thin-mode connectivity to `FREEPDB1`
5. Assert connected user is approved test schema (not SYSTEM)
6. Document cleanup ownership and destructive-operation approval rule

**Gate G0 acceptance:**
- ✅ Baseline commands and known failures recorded
- ✅ No ambiguous schema ownership
- ✅ No secret in repository or transcript
- ✅ Cutover scope explicitly NO
- ✅ Thin mode approved for local validation
- ✅ All current-state facts verified

**Status:** G0 COMPLETE — ready for O00.
