# Oracle Enablement: Architecture, TDD Implementation, and Parallel Execution Plan

**Status:** Authoritative execution plan; implementation not yet started
**Updated:** 2026-09-10
**Scope:** Enable and prove the existing application on Oracle while preserving SQLite as the fast local/test database
**Primary target:** Local Oracle AI Database Free in Docker (`FREEPDB1`)
**External certification target:** Enterprise-managed Oracle environment, handled as a later gate

---

## 1. Purpose and authority

This document replaces the earlier Oracle brainstorm, abstraction guide, readiness summary, and diagram as the **single source of truth** for Oracle implementation. It is written so a lead agent can allocate independent packets to implementation agents, enforce test-first delivery, and merge only at explicit gates.

This plan does not claim that Oracle support already works. The codebase contains strong portability intent, but portability is not proven until migrations and persistence contracts execute against a real Oracle schema.

### 1.1 Source precedence

When executing this plan, agents must follow this order:

1. `AGENTS.md` — project rules and product invariants.
2. `STATE.md` — current implementation state and current test baseline.
3. This document — Oracle packet order, ownership, tests, and gates.
4. `src/PRODUCTION_FOUNDATION_ARCHITECTURE_AND_TECHNICAL_DESIGN.md` — existing architecture decisions, especially AD-008 and AD-009.
5. Current code and tests — actual contracts override examples in this plan if the code has legitimately evolved.

Agents must not use hard-coded test counts from this document as acceptance criteria. The baseline changes frequently. Record the discovered count at the start of each packet and require no unexplained regression.

---

## 2. Executive architectural decision

### 2.1 Decision

Use **one SQLAlchemy persistence implementation** for SQLite and Oracle. Keep SQLite as the default local and routine unit/contract-test database. Use Oracle for mandatory migration, type, repository, transaction, health/bootstrap, and selected end-to-end certification gates.

### 2.2 What this work is

Oracle enablement is a **validation-and-repair program**, not a database abstraction rewrite:

- provision an isolated non-`SYSTEM` Oracle test schema;
- install and use `python-oracledb` thin mode;
- execute the current Alembic chain on a clean Oracle schema;
- run shared persistence contracts on both dialects;
- repair only failures demonstrated by those contracts;
- prove startup, catalog bootstrap, readiness, and one canonical vertical journey;
- define a separate, optional SQLite-to-Oracle cutover packet only if real SQLite state must be retained.

### 2.3 What this work is not

The initial enablement explicitly excludes:

- a home-grown database abstraction framework;
- separate Oracle repository classes;
- Oracle-specific business behavior;
- thick-mode Oracle Client support;
- wallets, mTLS, RAC, Data Guard, TDE administration, partitioning, hints, result cache, or NLS session tuning;
- running every pure unit or browser test twice merely to increase test count;
- generic bidirectional database synchronization;
- application-level replacement for RMAN or Data Pump;
- production performance tuning before measured evidence exists;
- a CI Oracle container until the local gate is stable and the registry/license/secret boundary is approved.

These exclusions are deliberate controls against overengineering.

---

## 3. Review of the original four drafts

The original drafts contained useful intent but were not safe as executable plans. The consolidated plan corrects the following issues.

### 3.1 Correct ideas retained

- AD-008/AD-009 already establish SQLite local plus Oracle shared/anticipated production and one SQLAlchemy implementation.
- Portable types, short names, explicit constraints, UUID keys, and Alembic are the correct foundation.
- A dedicated Oracle schema is required; `SYSTEM` must not be the application identity.
- The same behavioral persistence contracts should prove both dialects.
- Oracle's empty-string behavior must be tested at the semantic boundary.
- Data cutover, if required, needs independent verification and rollback.

### 3.2 Overengineering removed

1. **No speculative Oracle connection hook.** The drafts proposed `ALTER SESSION` NLS configuration although timestamps are stored as ISO text and no defect requires NLS changes. Thin mode and SQLAlchemy defaults are sufficient until a failing test proves otherwise.
2. **No premature pooling/tuning packet.** Pool settings already exist in configuration but are not wired in `main.py`. Wiring them is a small, measured runtime packet, not an Oracle optimization program. No index hints, partitioning, result cache, or RAC design is part of initial enablement.
3. **No full-suite dual execution by default.** Most unit, import parser, template, and browser tests do not exercise dialect semantics. Oracle validation targets migrations, persistence contracts, selected service integration, readiness/bootstrap, and one vertical journey.
4. **No Alembic cross-database data copy.** Alembic owns schema evolution inside a target database. It must not open a SQLite source and copy operational data into Oracle.
5. **No bidirectional export/import platform.** A one-way, one-time cutover utility is optional and only built if existing local canonical state must be preserved.
6. **No fixed timeline or performance ratio.** Test counts and execution times are measured at runtime. “Oracle within 2x SQLite” is not a meaningful contract for a network database.
7. **No invented CLI/CI flags.** Options such as `--run-both-dialects` do not exist and must not appear as commands until implemented and tested.

### 3.3 Major gaps corrected

1. **The current migration chain is not simply “10 sequential migrations.”** There is no `0005`; `0006` correctly follows `0004`. Tests must derive Alembic heads and revisions, not assume contiguous numbering.
2. **Migration repair scripts contain inspector-driven, idempotent behavior and raw UPDATE SQL.** Migrations `0007`–`0009` require real Oracle execution, including clean upgrade, repeated upgrade no-op, and targeted upgrade/downgrade/upgrade coverage where safe.
3. **ORM/migration representation divergence exists.** Some candidate ORM timestamp columns use `DateTime(timezone=True)` while migration `0004` created strings. This must be characterized on Oracle rather than assumed portable.
4. **Oracle `Text` becomes a LOB.** Equality/filter/unique/index behavior must be reviewed. The current design mostly avoids indexing JSON/text, which is good, but type and snapshot payload round trips require real tests.
5. **LOB reads after session close must return plain Python values.** Repositories and serializers may not leak Oracle LOB handles.
6. **Oracle identifier normalization and schema introspection differ.** Table/column/constraint metadata comparisons must normalize case and compare semantic structure, not raw dialect spelling.
7. **Schema isolation and cleanup were missing.** Oracle tests cannot safely call `Base.metadata.drop_all()` against a shared schema or use `SYSTEM`. Each run needs an approved disposable schema/user or a single dedicated local test schema with exclusive ownership and deterministic cleanup.
8. **Destructive operations need approval.** Dropping a user/schema or purging test data requires explicit user approval at execution time, even when the schema is intended to be disposable.
9. **Credentials and URL encoding were under-specified.** Passwords containing reserved URL characters must be passed via a safely constructed SQLAlchemy `URL` or correctly encoded environment value; secrets must never appear in logs, test IDs, command output, docs, or exception assertions.
10. **Application engine settings are currently unused.** `db_pool_size`, `db_max_overflow`, `db_pool_recycle_seconds`, and `sql_echo` are declared but `main.py` does not apply them. This is a real composition-root gap.
11. **Application startup auto-publishes/repairs catalog state.** Oracle readiness tests must distinguish schema migration, catalog bootstrap, startup repair, and health checks; tests must not assume startup is read-only.
12. **`create_all()` is not production schema proof.** It remains useful for disposable contract fixtures, but Alembic clean-upgrade is the production gate.
13. **Downgrade policy was unclear.** Production rollback should restore from backup/schema replacement, not rely blindly on Alembic downgrade. Downgrade tests are engineering checks for reversible recent migrations, not the sole operational rollback plan.
14. **Concurrency was underspecified.** Oracle must prove commit/rollback, unique conflicts, optimistic revision handling, and visibility from independent sessions; SQLite lock behavior is not the Oracle contract.
15. **Enterprise certification cannot be inferred from Oracle Free.** Local Free proves SQLAlchemy/Alembic dialect compatibility, not enterprise networking, wallet, service failover, managed backup, observability, or DBA controls.

---

## 4. Current-state facts to verify before implementation

At packet start, the lead agent must confirm these facts from code rather than copy them blindly:

- Optional dependency currently declares `oracledb>=2.2.0,<3.0`.
- `oracle` pytest marker exists, but no Oracle fixture or test harness exists.
- `create_engine_from_url()` only applies SQLite pragmas; no Oracle-specific configuration exists.
- `Settings` declares pool configuration, but `create_app()` currently passes only SQLite `check_same_thread`.
- Alembic reads `DATABASE_URL`, uses `NullPool`, and enables batch mode only for SQLite.
- Current migration revisions are `0001`, `0002`, `0003`, `0004`, `0006`, `0007`, `0008`, `0009`, and `0010`; derive actual head dynamically.
- Persistence contract tests create schema through `Base.metadata.create_all()` on fresh SQLite files.
- Portable type tests define private tables and use raw SQL in physical-representation assertions.
- Application startup calls `ensure_catalog_published(session_factory)` before yielding.
- `STATE.md` contains the live regression baseline and known pre-existing failures.

If any fact has changed, update packet assumptions before coding.

---

## 5. Target architecture and abstraction policy

### 5.1 Runtime dependency flow

```text
FastAPI routes
    -> application services
        -> repository interfaces / unit of work
            -> shared SQLAlchemy repositories
                -> shared ORM models and portable types
                    -> engine created from configured SQLAlchemy URL
                        -> SQLite or Oracle

Alembic migrations
    -> shared migration chain
        -> dialect-aware Alembic rendering only where required
            -> SQLite or Oracle schema
```

### 5.2 Allowed dialect-specific code

Dialect-specific behavior is allowed only when a shared SQLAlchemy construct cannot express the required behavior and a failing cross-dialect test demonstrates the difference. Likely locations:

- `persistence/database.py` for engine/driver construction;
- `persistence/types.py` for physical type selection or bind/result conversion;
- `persistence/migrations/env.py` for migration context configuration;
- individual migration files for unavoidable DDL differences;
- test infrastructure for schema lifecycle and Oracle availability.

Any dialect branch must include:

1. the failing test that required it;
2. the smallest branch possible;
3. a comment only if the reason is not obvious from code;
4. passing SQLite and Oracle contracts.

### 5.3 Forbidden coupling

Do not add dialect checks to:

- domain objects or policies;
- application services;
- routes or templates;
- candidate/import logic;
- catalog compiler;
- snapshot serializer;
- ordinary repository business queries.

A repository may use SQLAlchemy Core/ORM constructs. If SQLAlchemy requires a localized dialect compilation expression, isolate it in persistence infrastructure and contract-test it; do not create a duplicate repository.

### 5.4 Semantic portability, not physical identity

The databases need not expose identical native DDL. They must preserve the same application contract:

- UUIDs return as `uuid.UUID`;
- timestamps return according to the model's documented Python contract;
- decimals retain required precision and scale;
- canonical JSON returns as plain Python dict/list values and deterministic text where hashing depends on bytes;
- constraints enforce the same uniqueness and referential rules;
- transaction boundaries commit and roll back atomically;
- repositories return detached/plain values as expected;
- immutable releases/revisions/snapshots remain immutable.

Schema tests compare logical names, nullability, lengths, uniqueness, foreign-key targets, and indexes after dialect normalization. They must not require `VARCHAR` and `VARCHAR2` spelling to match.

---

## 6. Oracle environment and security contract

### 6.1 Local environment

The current local target is Oracle Free in Docker:

- container: `oracle-free`;
- host access: `localhost:1521`;
- service name: `FREEPDB1`;
- application runs on Windows host, so `localhost` is correct;
- if the application later runs in Docker, use a shared Docker network and the Oracle container DNS name instead.

The setup note proves administrative connectivity only. It does **not** prove application-schema privileges, Alembic compatibility, or application behavior.

### 6.2 Identities and least privilege

Use separate concerns:

- **Provisioning identity:** administrative identity used manually to create/drop local disposable schemas. Never used by the application or tests.
- **Migration owner:** owns the application schema and runs Alembic in this first local slice.
- **Runtime identity:** ideally DML-only in shared/production environments. It may be the same as migration owner for the local Free validation slice only, with the exception documented.

Do not grant `DBA`, `RESOURCE`, `CONNECT`, `UNLIMITED TABLESPACE`, or broad system privileges by convenience. The minimal local migration-owner privilege set is discovered through failing migration tests and documented. Begin with `CREATE SESSION`, table/index/constraint creation through table ownership, and quota on a dedicated/default tablespace; add `CREATE VIEW`, `CREATE SEQUENCE`, or `CREATE PROCEDURE` only if an actual migration needs them.

### 6.3 Secrets

- Store credentials outside version control.
- Prefer environment injection or the approved secret manager.
- Never add passwords to `.env.example`, test parametrization IDs, traceback matching, logs, Markdown, or shell history shown in output.
- Use a separate `ORACLE_TEST_DATABASE_URL` for tests so a developer's runtime `DATABASE_URL` cannot be accidentally targeted.
- Require the Oracle test URL to identify an approved test schema; fail closed if unset.
- Redaction tests must cover reserved characters and query parameters, not only `user:password@host` strings.

### 6.4 Test schema lifecycle

Preferred local model: one dedicated, disposable schema/user per developer or test run. If automated schema creation is not available, use one dedicated exclusive schema and serialize Oracle tests.

The harness must:

1. refuse `SYSTEM`, `SYS`, or an unapproved username;
2. assert the configured service/schema before any cleanup;
3. avoid parallel workers against the same schema;
4. migrate from empty state before tests;
5. clean data by transaction or table order when possible;
6. request explicit approval before dropping the schema/user;
7. always dispose engines and close sessions;
8. never touch client evidence.

---

## 7. Testing architecture

### 7.1 Test classes

| Class | Database | Purpose |
|---|---|---|
| Pure unit/domain/import/UI tests | none or SQLite fixtures | Fast default regression; not duplicated on Oracle |
| Portable type contract | SQLite + Oracle | Python↔DB round trips and LOB behavior |
| Metadata/DDL contract | SQLite + Oracle | Logical schema properties and circular-FK behavior |
| Repository/UoW contract | SQLite + Oracle | Shared persistence behavior and transactions |
| Alembic migration test | SQLite + Oracle | Clean upgrade and targeted upgrade paths |
| Startup/bootstrap/readiness | SQLite + Oracle | Composition root, catalog, schema and redaction |
| Oracle vertical journey | Oracle | One representative canonical workflow |
| Browser suite | SQLite by default | UI behavior; run one Oracle smoke journey only if needed |
| Cutover verification | SQLite source + Oracle target | Optional, only if migration packet is approved |

### 7.2 Marker and fixture behavior

Oracle tests use `@pytest.mark.oracle` and must be skipped with an explicit reason when `ORACLE_TEST_DATABASE_URL` is absent. The default SQLite suite remains green without Oracle installed.

Do **not** parametrize every existing test globally. Instead:

- keep existing SQLite fixtures unchanged;
- introduce an Oracle engine/session fixture in a dedicated Oracle support module;
- reuse behavior through test helpers or contract mixins where this reduces duplication;
- avoid test inheritance/metaprogramming that obscures failures;
- Oracle fixture setup must be session-scoped where safe, with function-level data isolation.

### 7.3 TDD rule for every implementation packet

Every behavior-changing packet follows:

1. **RED:** add the narrowest failing test against current behavior;
2. run it and record the expected failure;
3. **GREEN:** implement the smallest coherent fix;
4. run focused SQLite and Oracle tests;
5. **REFACTOR:** remove accidental duplication without adding speculative abstraction;
6. run the packet gate;
7. review the diff for secrets, client data, dialect leakage, and unrelated changes.

Environment/provisioning packets that cannot produce a code-level red test use a deterministic preflight command with an expected failing condition and captured non-secret diagnostic.

### 7.4 Required Oracle semantic cases

The shared contract set must cover at least:

- UUID bind/read/string input/NULL;
- UTC timestamp normalization and naive timestamp rejection;
- candidate `DateTime(timezone=True)` behavior, with contract explicitly defined from current use;
- Decimal precision, scale, NULL, and float rejection;
- canonical JSON dict/list/unicode/NULL/large payload, returned as plain Python values after session close;
- SHA-256 validation and normalization;
- empty string behavior for nullable fields and explicit rejection/normalization for required fields;
- booleans;
- circular answer-instance/current-revision insert pattern;
- unique and foreign-key enforcement;
- catalog publication idempotency;
- answer append-only revision and optimistic version conflict;
- candidate state transition and stale row-version conflict;
- commit, exception rollback, and no-commit rollback;
- independent-session visibility;
- immutable snapshot idempotency and hash stability;
- readiness redaction and schema-current behavior.

---

## 8. Execution model and dependency graph

### 8.1 Gates

```text
G0 Baseline and decisions
  -> G1 Oracle preflight/schema ownership
      -> G2 Clean Alembic schema
          -> parallel Wave A: type contracts | migration hardening | runtime config tests
              -> G3 Portability foundation
                  -> parallel Wave B: repository groups
                      -> G4 Persistence contract
                          -> parallel Wave C: startup/bootstrap | concurrency | vertical journey
                              -> G5 Application Oracle-ready
                                  -> optional G6 data cutover
                                      -> G7 enterprise certification (external)
```

### 8.2 Merge discipline

- One integration lead owns shared fixture files, `STATE.md`, and final gate execution.
- Parallel agents receive exclusive file ownership.
- Agents must not edit files owned by another packet.
- If a discovered fix crosses ownership boundaries, the agent writes a finding and stops; the lead reallocates or sequences the fix.
- No agent creates a second abstraction or helper without at least two real consumers or a boundary-enforcement reason.
- Each packet returns: files changed, tests added, RED evidence, GREEN evidence, unresolved findings, and explicit statement that no secrets/client data were introduced.

---

## 9. Detailed packets

## G0 — Baseline, inventory, and decisions

**Mode:** Sequential; integration lead only
**Purpose:** Establish a trustworthy start and prevent agents from solving different problems.

### Inputs

- `AGENTS.md`
- `STATE.md`
- this plan
- `pyproject.toml`
- persistence models, repositories, migrations, and contract tests
- local Oracle setup note (private `_data`; do not copy secrets)

### Tasks

1. Record current branch and working-tree status; do not overwrite unrelated user changes.
2. Run or record the current SQLite focused baseline:
   - `python -m pytest tests/contract/persistence/ -q`
   - relevant migration tests
   - `python -m pytest tests/unit/application/ -q` if repository behavior is touched later
3. Read `STATE.md` for current known failures; do not normalize them away.
4. Derive Alembic heads programmatically.
5. Inventory all ORM tables from `Base.metadata`, all migration-created tables, custom types, unique constraints, FKs, indexes, and raw migration SQL.
6. Decide and record:
   - thin mode only for initial local validation;
   - exact approved Oracle test username/schema pattern;
   - whether local migration owner and runtime user may be the same for the spike;
   - whether preserving existing SQLite data is in scope. Default: **no**;
   - whether Oracle CI is in scope. Default: **defer until local G5 passes**.
7. Confirm no production/shared Oracle endpoint is being used.

### Deliverable

A short checkpoint appended to `STATE.md` only after decisions are approved; no implementation code.

### Gate G0

- baseline commands and known failures recorded;
- no ambiguous schema ownership;
- no secret in repository or transcript;
- cutover scope explicitly yes/no;
- thin mode approved for local validation.

---

## O00 — Oracle preflight and dedicated schema

**Depends on:** G0
**Mode:** Sequential environment gate
**Owner:** Oracle environment agent
**Code ownership:** no production code; optional synthetic test/preflight support only

### RED/preflight

With no `ORACLE_TEST_DATABASE_URL`, the Oracle test command must skip safely rather than target `DATABASE_URL`. With an invalid URL, connection fails with a redacted diagnostic.

### Tasks

1. Verify Docker container health and port reachability without exposing credentials.
2. Install project with the Oracle extra in the active environment using the package manager.
3. Have the user/admin create a dedicated local schema using a secret entered outside the repository.
4. Verify the schema can connect to `FREEPDB1` using `oracle+oracledb` thin mode.
5. Query and record non-secret facts:
   - database product/version;
   - current schema/user;
   - service name if safely available;
   - SQLAlchemy and `oracledb` versions;
   - thin mode status.
6. Verify the URL's password encoding path using SQLAlchemy URL parsing/construction.
7. Verify the user cannot access unrelated application schemas by design; do not probe client schemas.
8. Establish cleanup ownership. Do not drop anything during this packet.

### Tests/commands

- driver import smoke;
- `SELECT 1 FROM DUAL` through `create_engine_from_url()`;
- redaction check on the effective URL;
- explicit assertion that connected user is the approved test schema.

### Gate G1

- non-`SYSTEM` test schema connects;
- approved schema identity is asserted;
- Oracle URL remains secret/redacted;
- driver works in thin mode;
- cleanup owner and destructive-operation approval rule are documented.

---

## O01 — Clean Alembic migration execution

**Depends on:** G1
**Mode:** Sequential; blocks all Oracle repository work
**Owner:** migration agent
**Exclusive files:** `tests/integration/migrations/**`, migration files only when a failing Oracle test requires repair

### RED

Add an Oracle-marked migration test that upgrades an empty approved schema to dynamically discovered `head`, then checks `alembic_version`. It must fail before the schema or migration defects are corrected.

### Tasks

1. Run Alembic through the project's `env.py`, not `Base.metadata.create_all()`.
2. Upgrade a clean Oracle schema to head.
3. Capture the first real failure and fix only that failure.
4. Repeat until head is reached.
5. Assert logical table inventory against `Base.metadata`, normalizing identifier case.
6. Assert critical constraints:
   - answer instance/revision circular FK pair;
   - unique intake/question answer instance;
   - application external identifier uniqueness;
   - snapshot uniqueness/idempotency constraints;
   - candidate and evidence link FKs.
7. Verify `check_schema_current(engine)` returns true at head and false before schema initialization.
8. Run `alembic upgrade head` again and assert a no-op success.
9. Generate offline Oracle SQL only as a diagnostic; live execution is authoritative.
10. Do not require raw physical DDL equality with SQLite.

### Migration repair constraints

- Preserve already-deployed SQLite semantics.
- Prefer forward-compatible edits only if migrations have not been released; otherwise add a new corrective migration. The lead decides based on deployment history.
- Never change `alembic_version` manually.
- Do not add Oracle branches until shared Alembic operations demonstrably fail.
- Raw `op.execute()` must use portable SQL or a tightly scoped branch with tests.

### Gate G2

- clean Oracle `upgrade head` passes;
- repeated `upgrade head` passes;
- schema-current check passes;
- SQLite migration smoke remains green;
- logical schema and critical constraints are present;
- no `create_all()` used as substitute for production migration proof.

---

## Parallel Wave A — portability foundation

Wave A starts only after G2. Packets O02, O03, and O04 may run in parallel because they own separate primary files. The lead freezes shared fixture APIs before dispatch.

### O02 — Oracle fixture and portable-type contracts

**Owner:** type-contract agent
**Exclusive files:** `tests/contract/persistence/oracle_support.py` or agreed equivalent; Oracle type-test modules; `persistence/types.py` only if tests prove a defect

#### RED cases

Add Oracle execution for existing type semantics plus missing cases:

- Unicode canonical JSON;
- payload larger than typical VARCHAR limits to force LOB behavior;
- value usable after session/connection close;
- candidate timestamp representation;
- nullable empty string returns `None` on Oracle;
- required-value boundary behavior is explicit and tested at the application/type boundary;
- Decimal boundary values at declared precision/scale.

#### Design constraints

- Do not mechanically reuse SQLite raw-representation assertions where the DBAPI legitimately returns a LOB or different raw type.
- Assert Python application semantics via ORM first.
- Only inspect physical storage where it protects a required invariant, such as deterministic JSON text/hash.
- If `CanonicalJSON` needs dialect-specific CLOB selection, implement through `TypeDecorator.load_dialect_impl`; do not branch in repositories.
- Do not globally normalize every empty string without reviewing field semantics. `None`, `UNKNOWN`, and empty are distinct product states.

#### Gate

All portable-type tests pass on SQLite and Oracle, engines dispose cleanly, and no Oracle LOB object escapes repository/type boundaries.

### O03 — Migration path hardening

**Owner:** migration-path agent
**Exclusive files:** dedicated Oracle migration path tests; no overlap with O01 implementation files without lead reassignment

#### RED cases

Test paths especially likely to expose Oracle differences:

1. upgrade through `0006`, then `0007`–`0010`;
2. repair migration on schema where target columns already exist;
3. repair migration on schema where target columns are absent;
4. `0008` data backfill and NOT NULL transition;
5. recent reversible downgrade/upgrade path if project policy requires it.

#### Important policy

Do not downgrade the shared developer schema destructively without approval. Use a dedicated disposable schema. A downgrade failure does not automatically justify production rollback via downgrade; document restore-based rollback separately.

#### Gate

Targeted migration paths pass on both dialects or have a documented, approved irreversibility policy with forward-fix test coverage.

### O04 — Runtime engine configuration and redaction

**Owner:** composition agent
**Exclusive files:** `config.py`, `main.py`, `persistence/database.py`, focused config/database tests

#### RED cases

1. Non-SQLite `create_app()` applies configured pool size, max overflow, recycle, and `pool_pre_ping` policy as approved.
2. SQLite continues receiving only valid SQLite arguments.
3. `sql_echo` behavior follows configuration without logging URL credentials.
4. URL redaction handles encoded passwords and query strings.
5. Engine disposal occurs on application shutdown.

#### Minimal implementation

- Wire existing settings; do not add thick-mode or wallet settings.
- Prefer SQLAlchemy URL parsing for redaction over regex if tests show regex is insufficient.
- Add `pool_pre_ping=True` for network databases only if accepted as baseline reliability behavior.
- Do not add NLS session hooks.
- Do not duplicate engine option logic between runtime and catalog bootstrap; extract a small shared options/factory path only if both need identical behavior now.

#### Gate

Focused config/database/startup tests pass; SQLite behavior is unchanged; Oracle connection recovers from an invalid/stale pooled connection if such a deterministic test is feasible; shutdown disposes the engine.

### Gate G3 — portability foundation

The integration lead merges Wave A and runs:

- SQLite persistence contracts;
- Oracle type contracts;
- SQLite + Oracle migration gates;
- config/database tests;
- Ruff and mypy on changed production files.

No repository packet starts until G3 is green.

---

## Parallel Wave B — repository and transaction contracts

Wave B partitions existing repositories by table ownership and avoids edits to shared fixtures. If a common defect is found in a type, UoW, or fixture, agents report it to the lead; they do not independently patch shared files.

### O05A — Core identity/catalog/intake repositories

**Exclusive files:** Oracle/shared tests for application, catalog, catalog publication, and intake repositories; corresponding repository files only if a failing shared contract requires repair

#### Required behaviors

- application creation and normalized external identifier uniqueness;
- duplicate conflict surfaces as deterministic domain/application error where existing design requires translation;
- catalog release publication is idempotent;
- sections/questions/options preserve order and typed values;
- intake remains pinned to immutable catalog release;
- deletes/updates respect historical FK restrictions.

### O05B — Answers, UoW, and audit transaction behavior

**Exclusive files:** answer repository, UoW, audit-focused tests/repositories

#### Required behaviors

- answer instance created once per intake/question;
- revision numbers append monotonically;
- current revision pointer update is atomic;
- stale optimistic version is rejected;
- commit persists across independent session;
- exception and no-commit paths roll back;
- failed multi-write command leaves no partial revision/pointer/audit state;
- circular FK insert pattern works on Oracle.

### O05C — Evidence, imports, and candidates

**Exclusive files:** evidence/import/candidate repository tests and corresponding repositories

#### Required behaviors

- evidence content hash deduplication;
- import run/sheet/finding persistence;
- canonical JSON and source locator round trips as plain values;
- candidate CRUD and state transitions;
- stale row-version decision rejection;
- answer-evidence links retain provenance;
- no LOB/session leakage.

### O05D — WaveUtil and snapshots

**Exclusive files:** WaveUtil/snapshot repository tests and corresponding repositories

#### Required behaviors

- row/revision append-only semantics;
- Decimal measurements preserve precision;
- matching keys and ordering are deterministic;
- snapshot canonical JSON survives LOB storage;
- snapshot hash and idempotency remain stable across dialects;
- immutable snapshot rows cannot be silently overwritten.

### Wave B RED/GREEN protocol

Each agent first runs the assigned existing SQLite contract. It then runs the same behavior against Oracle through the frozen Oracle fixture. Each Oracle failure becomes one narrow regression test before the production fix.

### Gate G4 — persistence contract

The lead runs all persistence contract tests on SQLite and the Oracle-marked repository/UoW suite serially. Acceptance requires:

- no unexplained dialect-specific skip;
- no dialect branch outside approved infrastructure;
- no open session/LOB warnings;
- no state leakage between tests;
- stable semantic exception behavior;
- all changed production files pass Ruff and mypy.

---

## Parallel Wave C — composition and application proof

Wave C begins after G4.

### O06A — Startup, catalog bootstrap, and health

**Owner:** startup agent
**Exclusive files:** startup/bootstrap/readiness Oracle tests; catalog bootstrap production code only if tests prove a defect

#### RED cases

1. Unmigrated Oracle schema causes readiness to fail safely without applying migrations.
2. Migrated empty schema bootstraps the packaged catalog exactly once.
3. Second startup is idempotent.
4. `/health/ready` reports database/schema/storage/catalog checks correctly.
5. Diagnostics redact credentials.
6. Startup failure does not silently fall back to SQLite.

#### Gate

Oracle app starts against migrated schema, packaged catalog is available, readiness is green, and wrong schema/credentials produce safe failure.

### O06B — Real concurrency and failure atomicity

**Owner:** concurrency agent
**Exclusive files:** Oracle concurrency integration tests; service/repository code only by reassignment

#### Required tests

- two independent sessions attempt conflicting answer updates; exactly one expected version succeeds;
- two candidate decisions from the same row version cannot both win;
- unique application identifier race produces one durable winner and one controlled conflict;
- an injected failure between revision insert and pointer/audit completion rolls back all writes;
- no tests depend on SQLite's file-lock behavior.

Do not add pessimistic locking unless optimistic contracts fail and the architecture decision is revisited.

### O06C — Representative Oracle vertical journey

**Owner:** journey agent
**Exclusive files:** one Oracle-marked integration journey with synthetic fixtures

#### Journey

Using synthetic data only:

1. migrated Oracle schema;
2. startup/catalog bootstrap;
3. create actor, application, identifier, and intake;
4. save and revise at least one scalar and one structured answer;
5. create synthetic evidence metadata/import candidate;
6. accept a valid application-scoped candidate through the service boundary;
7. verify answer-evidence provenance;
8. compute readiness;
9. freeze snapshot;
10. retrieve canonical export and verify deterministic hash;
11. open a new session and re-read all critical state.

A browser journey is optional. Add it only if the web harness can select Oracle without broad duplication and if the service-level journey misses a real composition boundary.

### Gate G5 — local Oracle application readiness

Run serially against a freshly migrated dedicated Oracle test schema:

1. clean Alembic upgrade;
2. Oracle portable-type contracts;
3. Oracle repository/UoW contracts;
4. startup/bootstrap/readiness tests;
5. concurrency tests;
6. representative vertical journey;
7. default SQLite suite or the project-approved broad regression command;
8. Ruff and mypy;
9. final diff/security review.

**Definition of local Oracle-ready:** all above pass; no fallback, secret leak, LOB leak, or unexplained dialect exception; `STATE.md` records exact commands/results and known external certification gaps.

---

## 10. Optional data cutover stream

This stream is **not part of Oracle enablement by default**. Start only if G0 explicitly confirms that an existing SQLite database contains canonical state that must be preserved.

## O07 — Cutover contract and inventory

**Sequential; no implementation until approved.**

### Preconditions

- G5 complete;
- source SQLite database is backed up and quiesced;
- target Oracle schema is empty and migrated to the same Alembic head;
- maintenance window, rollback owner, and validation signer identified;
- private data remains inside the approved workspace/environment.

### Design

Build a one-way command/service using SQLAlchemy table metadata or repository-level export/import, not Alembic and not JSON as the canonical transport by default.

Required properties:

- source and target URLs explicit and distinct;
- dry-run inventory mode;
- source read-only where supported;
- target-empty precondition;
- dependency-ordered inserts;
- chunked transactions for large tables, with clear atomicity policy;
- IDs, revisions, timestamps, hashes, catalog release IDs, provenance links, and snapshot bytes preserved exactly;
- restart behavior explicit: default fail if target non-empty, not implicit upsert;
- no secrets in output;
- no client data copied outside approved systems.

## O08 — Cutover verification

Verification is independent from copy logic and includes:

- per-table row counts;
- PK set equality;
- FK orphan checks;
- unique constraint checks;
- canonical digest per table using stable ordered serialization of meaningful columns;
- current answer pointer/revision consistency;
- catalog release hashes and option counts;
- evidence metadata/hash preservation (evidence binary store remains a separate storage migration concern);
- snapshot canonical JSON and SHA-256 byte equality;
- application-level read-only smoke against target.

Do not compare database-native physical representations. Compare canonical application values.

## O09 — Cutover rehearsal and production runbook

At least one rehearsal on a synthetic or approved sanitized copy must prove:

1. quiesce source;
2. take source backup;
3. migrate empty target schema;
4. run dry-run inventory;
5. copy;
6. verify independently;
7. point application at Oracle;
8. perform read-only smoke, then controlled write smoke;
9. monitor;
10. rollback by restoring prior app configuration/source availability before accepting new writes, or by the formally approved reconciliation procedure if writes occurred.

Never present Alembic downgrade as data rollback.

### Gate G6

Cutover is complete only when the named business/data owner signs off the verification report. Technical row-count success alone is insufficient.

---

## 11. Enterprise Oracle certification gate

Local Oracle Free proves dialect compatibility only. Before production, G7 must resolve external platform inputs:

- exact Oracle version/edition and compatibility level;
- service naming, DNS, TLS/wallet, certificate rotation, and network allowlists;
- migration owner versus runtime grants;
- tablespace quota and capacity forecast;
- connection limits and pool budget across workers/replicas;
- backup, restore, point-in-time recovery, and recovery drill;
- maintenance/failover behavior;
- monitoring for connectivity, pool saturation, query latency, locks, tablespace, and migration state;
- secret injection and rotation;
- enterprise change-management/DBA approval;
- load and resilience tests using non-client synthetic data.

No local agent may mark G7 complete based on Docker Free results.

---

## 12. File ownership matrix for parallel agents

The lead must refine exact filenames after inspecting the current tree. This matrix defines intended boundaries.

| Packet | Primary owned files | Must not edit |
|---|---|---|
| O00 | Oracle preflight test/support only | repositories, migrations, UI |
| O01 | migration integration tests; required migration fixes | repositories, types, routes |
| O02 | portable type Oracle tests; `types.py` if proven | migrations, repositories, `main.py` |
| O03 | targeted migration-path tests | repositories, runtime config |
| O04 | `database.py`, `config.py`, `main.py`, focused tests | repositories, migrations, UI |
| O05A | app/catalog/intake repository tests and implementations | answer/evidence/Wave/snapshot repos |
| O05B | answer/UoW/audit tests and implementations | catalog/evidence/Wave repos |
| O05C | evidence/import/candidate tests and implementations | answer/catalog/Wave repos |
| O05D | WaveUtil/snapshot tests and implementations | core/candidate repos |
| O06A | startup/bootstrap/health tests and necessary composition files | concurrency/journey tests |
| O06B | concurrency tests and reassigned fixes | startup/bootstrap files unless reassigned |
| O06C | one vertical journey test | production code unless lead reallocates |
| O07–O09 | dedicated cutover package/tests/runbook | Alembic migration history |
| Lead | shared fixtures, marker config, `STATE.md`, final integration | packet-owned code during active work |

If two agents need the same shared fixture, the lead lands the fixture contract before parallel work.

---

## 13. Agent packet template

The lead should issue each implementation packet with the following exact structure:

### Context

- Read `AGENTS.md`, `STATE.md`, this plan sections X–Y.
- Oracle test schema is disposable/exclusive and identified by `ORACLE_TEST_DATABASE_URL`.
- Do not read or use `_data` client evidence.

### Objective

One sentence naming the behavior to prove.

### Allowed files

Explicit list or glob.

### Forbidden files

Explicit list, especially shared fixtures and other packets.

### RED tests

Named test behaviors that must fail first.

### Implementation constraints

- smallest coherent fix;
- no dialect branch outside approved infrastructure;
- no new dependency unless approved;
- no secret/client data;
- no destructive schema operation without confirmation.

### Verification

Exact focused SQLite command, exact Oracle-marked command, Ruff/mypy scope, and expected gate.

### Return contract

- files changed;
- initial failure and root cause;
- final commands/results;
- residual risks/findings;
- whether shared-file work is needed;
- confirmation of no secrets/client evidence.

---

## 14. Deterministic verification commands

Commands must be adapted to the active shell without exposing the Oracle URL. The secret should already be injected into `ORACLE_TEST_DATABASE_URL`.

### Default regression

```text
python -m pytest tests/ -q
python -m mypy src/migration_intake
python -m ruff check src/
```

Use `STATE.md` to account for known baseline errors; do not claim success if new failures are hidden among existing ones.

### Persistence focus

```text
python -m pytest tests/contract/persistence/ -q
python -m pytest tests/contract/persistence/ -m oracle -q
```

The final file paths may be refined during O02. Do not invent new CLI flags.

### Migration focus

Use the existing integration migration test directory discovered at execution time. The Oracle command must select `-m oracle` and the injected test URL. A clean schema is mandatory.

### Application focus

```text
python -m pytest tests/unit/application/ -q
python -m pytest tests/web/ -q
```

Run the full browser suite on SQLite unless a specific Oracle web composition defect requires browser proof.

---

## 15. Acceptance matrix

| Invariant | SQLite evidence | Oracle evidence | Gate |
|---|---|---|---|
| Migration reaches current head | migration test | clean live upgrade | G2 |
| Schema-current check | contract | Oracle readiness | G2 |
| Portable Python types | existing contracts | Oracle contracts | G3 |
| Empty/missing semantics | boundary tests | Oracle boundary tests | G3 |
| Repository behavior | existing contracts | grouped contracts | G4 |
| Atomic commit/rollback | UoW contracts | independent-session contracts | G4 |
| Optimistic concurrency | service/repo tests | real Oracle concurrency | G5 |
| Catalog startup/idempotency | bootstrap tests | Oracle startup tests | G5 |
| Canonical snapshot/hash | snapshot tests | Oracle journey | G5 |
| No SQLite fallback | settings tests | failed Oracle startup test | G5 |
| Secret redaction | config/log tests | Oracle diagnostic tests | G5 |
| Existing data retained | not applicable unless approved | independent cutover verification | G6 |
| Enterprise operations | platform evidence | managed environment test | G7 |

---

## 16. Stop conditions and escalation

An agent must stop and report rather than improvising when:

- the configured user is `SYSTEM`, `SYS`, or an unapproved schema;
- a command would drop a schema/user or destroy non-disposable data without explicit approval;
- a migration fix would rewrite history known to be deployed;
- an Oracle fix requires changing domain semantics;
- a password or private evidence appears in a tracked file or output;
- Oracle Free behavior conflicts with the enterprise target but target details are unknown;
- a common fixture/shared production file is owned by another active packet;
- a proposed dependency is not already available and has not been approved;
- tests reveal that SQLite and Oracle cannot share a semantic contract without a product decision.

The lead records the blocker in `STATE.md` only when it materially affects execution.

---

## 17. Principal-architect recommendation

Proceed in this order:

1. Approve G0 decisions, especially schema ownership and whether data cutover is actually required.
2. Complete O00 and O01 sequentially. Do not invest in repository or runtime work until the migration chain reaches Oracle head.
3. Run Wave A in parallel with three agents: portable types, migration-path hardening, and runtime engine configuration.
4. Integrate at G3 before dispatching four repository groups in Wave B.
5. Integrate at G4 before startup, concurrency, and vertical-journey work in Wave C.
6. Declare local Oracle readiness at G5 based on exact commands and evidence, not test-count parity.
7. Build cutover tooling only if an approved source database has state worth preserving.
8. Treat enterprise Oracle certification as a separate externally owned gate.

This sequence minimizes speculative code, creates fast root-cause feedback, allows meaningful parallelism without shared-file collisions, and preserves the application's existing architecture rather than layering a new database framework on top of SQLAlchemy.
