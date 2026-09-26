# Production-Shaped Thin Vertical Slice — Architecture Review and Confirmed Decisions

**Reviewed:** 2026-09-05  
**Decision status:** Core architecture decisions accepted; detailed production-foundation design is the next artifact.  
**Implementation location:** Root `src/migration_intake`; this is production-quality foundation code with deliberately limited vertical scope, not disposable prototype code.  
**Detailed design:** `src/PRODUCTION_FOUNDATION_ARCHITECTURE_AND_TECHNICAL_DESIGN.md`

## Confirmed decision record

The following decisions supersede earlier alternatives and recommendations in this review where they conflict:

1. Implement the production-shaped vertical slice in root `src`, not under a separate `spikes/` directory.
2. Keep `QUESTION_CATALOG_V0_2.csv` authoritative for question semantics and stable IDs.
3. Treat `App Data Capture_intake_1.xlsx` as a per-application upload and review package whose values produce candidates.
4. Validate the workbook `App` projection against catalog v0.2 and fail or quarantine unexplained drift.
5. Treat `iTAP`, `WaveUtil`, `TSS`, and `Provisioning` as distinct typed sheet contracts.
6. Treat `Infra` and `Database` as candidate extensions requiring explicit mapping, duplicate detection, and unresolved findings.
7. Make all 112 catalog questions editable by defining schemas, validation, serialization, display, and editor behavior for all 25 response types before calling the slice complete.
8. Implement WaveUtil as the first end-to-end repeated-row register.
9. Use SQLAlchemy 2.x ORM as the database-dialect abstraction, behind narrow use-case repositories and a unit of work.
10. Use SQLite for local development and Oracle for shared test and anticipated production use.
11. Require the same persistence contract suite to pass against a real Oracle test schema before the slice is complete. Oracle provisioning is currently an external blocker.
12. Use a configured demo actor for the slice while preserving actor IDs and audit fields so OIDC can replace it later.
13. Implement a provider-neutral `CandidateMapper`, a deterministic mock provider, and one disabled OpenAI-compatible adapter tested only with synthetic content and a fake HTTP endpoint.
14. Do not send client evidence to a runtime LLM in this slice.
15. Runtime AI may create candidates and findings only; it cannot approve, overwrite canonical values, resolve conflicts, make architect decisions, or freeze snapshots.
16. Preserve append-only answer and WaveUtil revisions and generate only from immutable canonical snapshots.
17. Do not implement the full 46-table future model; implement the smallest production-grade relational subset needed by the vertical slice.
18. Reconsider workbook-authoring Option C only after the slice supplies evidence about governance and compiler behavior.

## Revised scope statement

A quick, production-shaped vertical slice is the correct next step, but it should **not** attempt to implement the entire 46-table design. Unlike the initial recommendation, it **will** load and provide typed editing for all 112 controls; scope is constrained through reusable response-type infrastructure, one full register, one workbook contract, one configured actor, and no production SSO or deliverable renderer.

The spike should answer four architectural questions:

1. Can the consolidated workbook be compiled into a stable, typed questionnaire definition?
2. Can one application intake be created, answered, autosaved, and resumed without tying business logic to SQLite?
3. Can document imports and optional LLM calls produce reviewable candidates rather than overwrite answers?
4. Can the same application services and persistence contracts run against SQLite now and Oracle later?

The answer to the database question is yes: SQLite and Oracle can be isolated behind a reasonably small persistence boundary. However, “database-independent” does **not** mean that every database behavior can be hidden completely. Schema migration, concurrency, JSON handling, case-insensitive uniqueness, locking, and timestamp behavior still require deliberate cross-database design.

My recommendation is:

- Build a **production-shaped vertical slice** in root `src/migration_intake`.
- Use FastAPI, SQLAlchemy 2.x, Pydantic, Jinja2/HTMX, SQLite for local development, and Oracle for required shared-environment validation.
- Define persistence at the **unit-of-work and repository level**, not through generic CRUD.
- Run the same repository contract tests against SQLite and, when credentials are available, Oracle.
- Do not build both database implementations manually.
- Use SQLAlchemy’s dialect support for SQLite and Oracle.
- Implement a mock `CandidateMapper` and one disabled OpenAI-compatible adapter; test the adapter with synthetic data and a fake HTTP endpoint, and make no real client-evidence calls.
- Treat the consolidated workbook as the latest team-maintained intake package, but **not yet as a production catalog release**.

---

# 1. Consolidated workbook findings

I inspected:

`C:\GitHub\aws_diag_v4\docs\App Data Capture_intake_1.xlsx`

The workbook contains seven sheets:

| Sheet | Rows | Columns | Purpose |
|---|---:|---:|---|
| `App` | 113 | 9 | 112 questionnaire controls plus header |
| `iTAP` | 17 | 2 | Application and recovery metadata template |
| `WaveUtil` | 1 | 34 | Empty server/wave-sizing register schema |
| `Infra` | 16 | 9 | Legacy infrastructure questionnaire subset |
| `Database` | 26 | 7 | Database-specific detailed questions |
| `TSS` | 20 | 7 | Empty technology lifecycle register |
| `Provisioning` | 11 | 8 | Site, region, CLLI, Outpost, AZ, and replication mapping |

Other measured characteristics:

- File size: approximately 36 KB.
- No formulas.
- No external workbook links.
- No defined names.
- No Excel tables.
- No data validations.
- No frozen panes.
- No autofilters.
- No merged regions.
- All sheets are visible.
- The `App` sheet has 112 questions and no populated responses.
- The `App` sheet contains a header typo: `Resonse`.
- `Infra` also uses `Resonse`.
- `Database` contains one exact duplicate question about RAC/Data Guard/standby.
- Some database questions appear to duplicate or decompose controls already represented by the `App` sheet.
- Several `Database` preferred/fallback source assignments appear questionable and should be reviewed semantically rather than trusted as final mappings.
- `Provisioning` contains real-looking reference data but has incomplete rows and inconsistent casing.
- `WaveUtil` and `TSS` currently define columns but contain no data rows.

## Most important discovery

The 112 rows in the workbook’s `App` sheet are an **exact field-for-field copy of `QUESTION_CATALOG_V0_2.csv`** for:

- Question text.
- Response type.
- Required level.
- Required condition.
- Preferred source.
- Fallback sources.

Therefore, the workbook does not currently supersede catalog v0.2 semantically. It packages catalog v0.2 together with additional intake/register sheets.

The workbook removes several catalog attributes:

- Stable `Question_ID`.
- Section.
- Collection mode.
- Default owner.
- Target outputs.
- Destination/register mapping.

This means the `App` sheet cannot be used alone as the production question catalog. The numbered `No` values 1–112 are display numbers, not durable semantic IDs.

## Architectural interpretation

The workbook should be treated as a **team-maintained intake design package**, with distinct sheet roles:

```text
App            -> questionnaire projection of catalog v0.2
iTAP           -> source-capture/register schema
WaveUtil       -> server sizing register schema
Infra          -> legacy/detail question extension requiring mapping
Database       -> detail question extension requiring deduplication/mapping
TSS            -> technology register schema
Provisioning   -> reference/master data candidate
```

Do not import every sheet using one generic “worksheet to table” mechanism.

---

# 2. Workbook authority options

## Option A — Workbook becomes the sole catalog authority

The system compiles all questionnaire and register definitions directly from the XLSX.

### Pros

- Matches how the team currently collaborates.
- One artifact appears to contain the intake design.
- Non-developers can update it.
- Easy to distribute and review.

### Cons

- The `App` sheet lacks stable question IDs.
- It lacks sections, collection mode, owners, outputs, and destination mappings.
- No validation rules prevent accidental edits.
- No machine-readable register definitions or stable row keys.
- No workbook-level version metadata.
- Duplicate and overlapping questions already exist.
- Reference data and application-input schemas are mixed.
- Excel is weak for diffs, code review, and controlled releases.
- Row numbers cannot safely become identifiers.

### Verdict

Not recommended in its present form.

---

## Option B — Catalog CSV remains authoritative; workbook is a source and review package

Keep question catalog definitions outside the workbook. Import workbook responses and register rows using mapping contracts.

### Pros

- Preserves stable IDs and catalog metadata.
- Existing design already supports immutable compiled releases.
- Clear separation between definition and application data.
- Easier diffing and automated validation.
- Workbook can evolve without silently changing intake semantics.

### Cons

- Team maintains two related artifacts.
- Drift detection is required.
- Workbook changes must be reconciled into the catalog.
- Business users may expect workbook edits to become automatically authoritative.

### Verdict

Safest immediate option.

---

## Option C — Workbook is authoring format; compiler produces a canonical release

Enhance the workbook contract to contain stable IDs, sections, collection modes, owners, outputs, destination mappings, register IDs, and version metadata. A compiler validates it and publishes an immutable catalog/register release.

### Pros

- Business-friendly authoring.
- One governed input package.
- Stable machine-readable output.
- Compiler can reject duplicates, invalid conditions, missing IDs, and unsupported response types.
- Fits the existing immutable-release design.
- Can include source schemas and reference data when roles are explicit.

### Cons

- Requires a formal workbook contract.
- More initial catalog compiler work.
- Excel remains harder to diff than CSV/YAML.
- Register schema definitions can become awkward in spreadsheets.
- Governance is needed around who publishes releases.

### Verdict

Best medium-term option if the team insists on Excel as its collaboration surface.

## Recommendation

For the spike:

- Use **Option B**.
- Compare the workbook’s `App` projection to catalog v0.2 and fail on unexplained drift.
- Treat `iTAP`, `WaveUtil`, `TSS`, and `Provisioning` as separate typed schemas.
- Treat `Infra` and `Database` as candidate extensions that need mapping and deduplication.

After the spike, decide whether to evolve toward Option C.

---

# 3. Problems in the current design documents

The existing UI plan is thoughtful but has become too broad for a first executable slice.

## Strong design choices to retain

- Internal application UUID.
- Typed external identifiers.
- Immutable catalog releases.
- Append-only revisions.
- Separate workflow states.
- Evidence outside the relational database.
- Candidates before canonical answers.
- Immutable generation snapshots.
- Server-rendered FastAPI/HTMX UI.
- Repository/service separation.
- Deterministic source parsing.
- Portal evidence without portal credentials.

These principles are clearly established in the architecture decision record.

## Design changes now required

### 1. PostgreSQL is no longer the only future database

The current design explicitly says SQLite should lead to PostgreSQL.

It must be generalized to:

```text
SQLite for local spike/development
Oracle as a possible enterprise target
PostgreSQL optionally retained as another future target
```

### 2. SQLite-specific DDL cannot be the portable schema contract

The draft uses:

- `PRAGMA`.
- `STRICT`.
- `COLLATE NOCASE`.
- Partial indexes.
- SQLite JSON functions in `CHECK` constraints.
- SQLite-specific trigger and boolean conventions.

These are acceptable for a SQLite implementation but cannot be the canonical cross-database schema definition.

### 3. The consolidated workbook must be added to the source baseline

The plan currently describes the prior Application Questionnaire workbook and question catalog but not this new team-consolidated workbook.

### 4. Runtime LLM architecture is absent

The documents mention document import but do not formally define:

- Runtime AI versus development-time AI.
- Provider-neutral client.
- AI use-case boundaries.
- Structured output validation.
- Prompt/version lineage.
- Mock provider.
- Candidate-only authority.
- Endpoint availability and governance.

### 5. The suggested source layout is too large for a spike

The proposed structure has many route, service, domain, repository, and generator modules before behavior exists.

That may be reasonable as a future package map, but copying it wholesale into a spike would create empty abstractions and slow learning.

---

# 4. What the quick spike should prove

The spike should be a **thin vertical slice**, not a miniature production platform.

## Primary scenario

```text
1. Compile the 112 App controls from catalog v0.2.
2. Verify the XLSX App sheet matches the catalog projection.
3. Create one application with UUID, name, acronym, and external identifier.
4. Create one intake pinned to the compiled catalog release.
5. Render questionnaire sections.
6. Edit and autosave a small representative question set.
7. Import one deterministic source candidate.
8. Create one mock-AI candidate from a narrative fragment.
9. Review accept/reject candidate.
10. Resume the intake after restarting the application.
11. Create a canonical snapshot.
12. Demonstrate the same application service does not know whether SQLite or Oracle is underneath it.
```

## Representative question types

Do not implement all 25 response types initially. Select enough to exercise the model:

- `BOOLEAN`.
- `SINGLE_SELECT`.
- `MULTI_SELECT`.
- `LONG_TEXT`.
- One structured composite such as `TEXT_PAIR`.
- `REGISTER_STATUS` as a computed navigation gate.
- One structured register, preferably TSS or servers.
- One conditional question.

## Representative state behavior

Prove:

- `PROPOSED` candidate.
- `ANSWERED` user value.
- `CONFIRMED` review.
- `CONFLICT`.
- `NOT_APPLICABLE`.
- Snapshot freeze.

That gives meaningful architectural evidence without implementing every workflow.

---

# 5. Spike location options

You explicitly do not want code under the production root `src` yet.

## Option A — Extend `_data/spike`

Example:

```text
_data/spike/intake_ui/
```

### Pros

- Keeps all experimentation together.
- No new top-level concept.
- Easy to distinguish from production.

### Cons

- `_data/spike` currently has strict topology-specific rules:
  - Five modules only.
  - Limited dependencies.
  - No new abstractions.
- Mixing UI/database/LLM dependencies into the topology spike would invalidate its compact boundary.
- Private evidence and executable prototype code become further entangled.

### Verdict

Do not place the new UI spike under the existing topology package.

---

## Option B — New top-level `spikes/intake_ui`

Example:

```text
spikes/
  intake_ui/
    pyproject.toml
    src/intake_spike/
    tests/
    README.md
```

### Pros

- Clean separation from production `src`.
- Clean separation from private `_data`.
- Can have its own dependencies and rules.
- Easy to discard or promote selectively.
- Communicates experimental status clearly.
- Most code can be copied later if kept production-shaped.

### Cons

- Adds one top-level directory.
- Requires conscious promotion rather than pretending the spike is production code.
- Shared code with the topology spike must initially be copied or adapted carefully.

### Verdict

**Recommended.**

---

## Option C — `prototype/` or `poc/`

### Pros

- Clearly non-production.
- Familiar terminology.

### Cons

- Often becomes permanent unlabeled production code.
- Less explicit that multiple focused experiments may exist.
- Encourages lower engineering standards than a “production-shaped spike.”

### Verdict

Acceptable but less precise than `spikes/intake_ui`.

---

# 6. Recommended lean spike structure

Avoid the 30-module production layout. Use a compact architecture that still preserves promotable boundaries:

```text
spikes/intake_ui/
├── pyproject.toml
├── README.md
├── src/
│   └── intake_spike/
│       ├── app.py
│       ├── config.py
│       ├── domain.py
│       ├── services.py
│       ├── persistence.py
│       ├── models.py
│       ├── catalog.py
│       ├── llm.py
│       ├── web.py
│       ├── templates/
│       └── static/
└── tests/
    ├── test_catalog.py
    ├── test_intake_service.py
    ├── test_persistence_contract.py
    ├── test_candidates.py
    └── test_web_smoke.py
```

This is not the only acceptable layout, but it has the right balance.

## Module responsibilities

### `domain.py`

Plain domain objects and enums:

- Application.
- Intake.
- Question definition.
- Answer.
- Candidate.
- Review result.
- Snapshot.

No FastAPI, SQLAlchemy, Oracle, SQLite, or LLM SDK imports.

### `services.py`

Use-case boundaries:

- Create application/intake.
- Get questionnaire.
- Save answer.
- Stage candidate.
- Accept/reject candidate.
- Freeze snapshot.

Depends on narrow persistence and LLM protocols.

### `persistence.py`

Minimal contracts:

- `UnitOfWork`.
- `ApplicationRepository`.
- `IntakeRepository`.
- Potentially `CatalogRepository`.

No universal generic repository.

### `models.py`

SQLAlchemy ORM models and session wiring.

For the spike, one model set should work on both SQLite and Oracle-compatible SQLAlchemy dialects.

### `catalog.py`

- Load catalog v0.2.
- Verify workbook projection.
- Compile a small runtime representation.
- Identify workbook extension/register sheets.

### `llm.py`

- Protocol/interface.
- Mock provider.
- Optional OpenAI-compatible provider.
- Structured candidate response validation.

### `web.py`

Thin routes and templates. No SQL or business state calculations.

### `app.py`

Composition root:

- Build engine.
- Build repositories/unit of work.
- Build LLM provider.
- Wire services and FastAPI.

This is the only place that needs to know concrete infrastructure implementations.

---

# 7. Database abstraction: what is possible

Yes, database substitution is practical if the abstraction is placed at the correct level.

## Bad abstraction: generic CRUD repository

Avoid:

```text
repository.save(table, dict)
repository.find(table, filters)
repository.update(table, id, values)
```

### Why it fails

- Leaks relational structure into business services.
- Provides no transaction semantics.
- Becomes a weak reimplementation of SQLAlchemy.
- Does not hide database differences meaningfully.
- Makes domain invariants difficult to enforce.
- Encourages query logic throughout services.

---

## Bad abstraction: hide SQLAlchemy completely

Creating fully separate SQLite and Oracle repository implementations for every entity is unnecessary at this stage.

### Why it fails

- Duplicated query logic.
- Premature interface explosion.
- Tests pass against fake repositories but not real databases.
- Large maintenance burden.
- Over-engineering before Oracle availability is known.

---

## Recommended abstraction: use-case-oriented repositories plus unit of work

Example conceptual API:

```python
class IntakeRepository(Protocol):
    def get(self, intake_id: UUID) -> Intake | None: ...
    def add(self, intake: Intake) -> None: ...
    def get_questionnaire(self, intake_id: UUID) -> Questionnaire: ...

class UnitOfWork(Protocol):
    applications: ApplicationRepository
    intakes: IntakeRepository

    def commit(self) -> None: ...
    def rollback(self) -> None: ...
```

Business services receive a `UnitOfWork` factory:

```text
save_answer(command, uow_factory)
freeze_intake(command, uow_factory)
```

One SQLAlchemy implementation can use either:

```text
sqlite:///...
oracle+oracledb://...
```

The difference is selected in the composition root using configuration.

## Why this is enough

- Application services do not import database drivers.
- Transaction boundaries are explicit.
- SQLAlchemy handles ordinary dialect differences.
- Tests can run against SQLite.
- Oracle integration tests can use the same repository implementation.
- If one operation eventually requires Oracle-specific optimization, it can be isolated.

---

# 8. SQLite versus Oracle options

## Option 1 — SQLite spike and pilot; Oracle-compatible design

### Pros

- Zero server provisioning.
- Fast local development.
- Simple test setup.
- Portable database file.
- Appropriate for a single-process spike.
- Fast feedback.
- No Oracle credentials or network dependency.

### Cons

- Different concurrency behavior.
- Different type and constraint semantics.
- SQLite is permissive.
- JSON and case-insensitive behavior differ.
- It cannot prove Oracle dialect compatibility alone.
- WAL is unsuitable on some shared network filesystems.
- Multiple worker processes require care.

### Appropriate use

Best for the quick spike and possibly a very limited local pilot.

---

## Option 2 — Oracle from the start

### Pros

- Tests the true enterprise runtime.
- Correct concurrency, locking, and transaction behavior.
- Enterprise backup, availability, monitoring, and access controls.
- Avoids late Oracle schema surprises.
- Aligns with an existing corporate database standard if mandated.

### Cons

- Provisioning and credential friction.
- Slower local development.
- Network dependency.
- Integration tests become less isolated.
- Schema creation permissions and migration ownership may delay progress.
- Oracle-specific assumptions may enter the code too early.
- More difficult for every developer to run independently.
- The team may over-design operational concerns before validating the UI workflow.

### Appropriate use

Use from the start only if Oracle is already a firm mandate and a development instance/schema is immediately available.

---

## Option 3 — SQLite locally, Oracle in shared test/production

### Pros

- Fast local iteration.
- Real Oracle validation before production.
- Same SQLAlchemy models and repositories.
- Clear distinction between unit/component and dialect integration tests.
- Balances speed and enterprise realism.
- Leaves production database decision reversible.

### Cons

- Must support two dialects.
- Developers may discover differences later unless Oracle contract tests run regularly.
- Migrations need cross-dialect validation.
- Some constraints behave differently.
- Requires an Oracle integration environment eventually.

### Appropriate use

**Recommended if Oracle remains a real candidate.**

---

## Option 4 — Build separate database adapters immediately

### Pros

- Maximum theoretical isolation.
- Can optimize independently per database.
- Explicit backend behavior.

### Cons

- Significant duplicate code.
- Premature abstraction.
- More tests and maintenance.
- Little value while domain behavior is still changing.
- High risk of the two implementations diverging.

### Verdict

Do not do this for the spike.

---

# 9. Database portability rules

If Oracle is a real possibility, make these decisions now.

## Use portable identifiers

Oracle limits and naming conventions can create friction. Keep table, index, constraint, and column names reasonably short and lowercase in Python metadata.

## Store UUIDs deliberately

Options:

### Text UUID

```text
CHAR(36) / VARCHAR(36)
```

Pros:

- Easy to inspect.
- Same representation in SQLite.
- Simple portability.

Cons:

- Larger indexes.
- Less efficient than binary/native representations.

### Binary UUID

```text
RAW(16) in Oracle
BLOB in SQLite
```

Pros:

- Compact.
- Better indexes.

Cons:

- More conversion complexity.
- Less human-readable.
- Dialect-specific type handling.

### Recommendation

Use canonical string UUIDs in the spike. Optimize only after measured need.

## Use UTC timestamps

Prefer timezone-aware UTC values in Python. Verify Oracle and SQLite serialization behavior through contract tests.

## Treat booleans carefully

Do not rely on a database-native boolean being identical across all Oracle versions and SQLite. Let SQLAlchemy map a constrained representation.

## Avoid database JSON constraints as the domain contract

The SQLite DDL currently uses `json_valid(...)`. Oracle JSON support and constraints vary by version/configuration.

Instead:

- Validate JSON structures with Pydantic/application schemas.
- Store serialized JSON using SQLAlchemy’s JSON/type decorator strategy.
- Use database JSON queries only when a measured requirement appears.
- Keep frequently queried identity/state fields relational.

## Avoid case-insensitive collation assumptions

`COLLATE NOCASE` is SQLite-specific.

Portable approach:

- Store a normalized comparison column such as `normalized_value`.
- Normalize consistently in application/domain code.
- Apply a normal unique index to the normalized value.

## Avoid partial indexes as correctness dependencies

SQLite and Oracle support different index strategies. Enforce critical cross-row policies in service transactions, and add backend-specific performance indexes only where required.

## Do not hand-maintain SQLite and Oracle DDL

Use SQLAlchemy metadata and Alembic migration logic as the intended schema source once the production scaffold begins.

For the spike:

- Use `metadata.create_all()` if migration behavior is not part of the question.
- Or prove one minimal Alembic migration on both dialects if schema portability itself is a spike objective.

## Test the actual dialect

SQLite passing does not mean Oracle compatibility. Define a small persistence contract suite:

```text
create application
enforce normalized external-ID uniqueness
create intake
save answer revision
optimistic concurrency conflict
accept candidate atomically with audit event
freeze snapshot
rollback failed transaction
```

Run against:

- SQLite on every local test run.
- Oracle when an integration database is available.

---

# 10. Whether to use SQLAlchemy

## Option A — Raw SQL with repository wrappers

### Pros

- Maximum SQL control.
- Few abstractions.
- Straightforward for a tiny database.

### Cons

- SQLite and Oracle SQL differences become your responsibility.
- Duplicate DDL/query logic.
- Difficult portable migrations.
- More manual row mapping.
- Database replacement becomes harder.

### Verdict

Not suitable given your explicit portability goal.

## Option B — SQLAlchemy Core

### Pros

- Strong SQL control.
- Portable expression language.
- Less ORM behavior.
- Good for explicit persistence logic.

### Cons

- More mapping code.
- Aggregates and revision relationships require manual handling.
- Team must manage row-to-domain transformations.

### Verdict

Viable if the team strongly prefers explicit SQL.

## Option C — SQLAlchemy ORM behind repositories

### Pros

- Existing plan already selected it.
- Supports SQLite and Oracle.
- Good unit-of-work/session model.
- Less persistence boilerplate.
- Alembic integration.
- One model set can serve both databases.

### Cons

- ORM misuse can leak lazy loading and sessions into services.
- Complex query behavior must be understood.
- Dialect portability still requires testing.
- It can encourage an anemic domain if models are used everywhere.

### Verdict

**Recommended**, provided:

- SQLAlchemy models remain inside persistence.
- Services do not pass active ORM sessions to templates.
- Routes do not query models directly.
- Repository methods reflect use cases rather than generic CRUD.

---

# 11. Existing mockup assessment

The mockup gives a strong conceptual information architecture:

- Portfolio.
- Application workspace.
- Sources.
- Questionnaire.
- Registers.
- Issues.
- Reviews.
- Deliverables.
- History.

## What to reuse in the spike

- Dense application workspace.
- Persistent application context.
- Section navigation.
- Visible source/provenance.
- Independent status dimensions.
- Register navigation.
- Issue/candidate review.
- Server-rendered visual direction.

## What not to copy directly

- In-memory `demo` state.
- Fabricated application records.
- Hard-coded FACET data.
- Raw HTML-string rendering functions.
- Generic hidden file input as the full ingestion UX.
- Dependency on a public CDN for Lucide if the application must operate internally/offline.
- All views at once.

## Spike UI subset

Implement only:

```text
Application list/create
Questionnaire section
One register
Evidence/import result
Candidate review
```

Do not implement notifications, portfolio analytics, catalog administration, deliverable approvals, and complete history in the first spike.

---

# 12. Runtime LLM abstraction

The availability of an LLM endpoint should be documented as an optional runtime capability, not as a hard dependency.

The referenced design correctly distinguishes:

- Development-time AI in Windsurf/Claude Code/VS Code.
- Runtime AI called by the product.

## What to reuse

- Provider selected by configuration.
- One application-facing interface.
- Mock provider for tests.
- No network or API credentials in automated tests.
- IDE-independent runtime behavior.
- OpenAI-compatible endpoint support.
- Credentials from environment or approved secret mechanisms.
- Provider details outside business services.

## What not to copy unchanged

The referenced API is:

```python
generate(prompt: str, max_tokens: int) -> str
```

That is too generic for document ingestion.

The application should not pass arbitrary prompts throughout the codebase. Use a small structured port:

```python
class CandidateMapper(Protocol):
    def map_fragment(
        self,
        request: MappingRequest,
    ) -> MappingResult: ...
```

Where `MappingRequest` contains:

- Fragment text/table.
- Exact source locator.
- Relevant question definitions only.
- Relevant register schema only.
- Allowed values.
- Explicit scope.
- Non-inference instructions.

`MappingResult` contains typed candidate proposals and findings.

## Minimal implementation options

### Option A — Document availability only

Update design to record that provider-neutral runtime AI is available as a future option. Implement nothing.

#### Pros

- No premature dependency.
- No security work yet.
- Keeps spike focused.

#### Cons

- Does not prove provider abstraction or structured validation.
- AI integration risks remain theoretical.

### Option B — Mock provider only

Implement the interface and deterministic canned mapping result.

#### Pros

- Proves service boundary.
- No credentials or network.
- Tests candidate workflow.
- Very small.
- Prevents AI details leaking into services.

#### Cons

- Does not prove real endpoint compatibility.
- Does not expose latency, malformed output, or provider failure behavior.

### Option C — Mock plus one OpenAI-compatible adapter

Implement:

```text
mock
openai_compatible
```

Configuration selects base URL and model.

#### Pros

- Supports the internal endpoint without naming it throughout the system.
- Proves network integration.
- Supports multiple OpenAI-compatible providers.
- Small provider surface.
- Easy to test adapter with a fake HTTP server.

#### Cons

- Requires dependency and credentials for manual integration.
- Security/data-governance approval is needed.
- Structured-output support varies by model/provider.
- Endpoint status is not confirmed.
- The referenced design uses an HTTP URL while its architecture says HTTPS; that must be resolved before sending client evidence.

### Option D — Mock, OpenAI, Bedrock, Anthropic, Copilot immediately

#### Pros

- Maximum provider choice.

#### Cons

- Premature.
- Multiple SDKs.
- Larger security and testing surface.
- No demonstrated need.
- Configuration complexity.
- Provider-specific behavior leaks into design.

### Recommendation

For the spike, use **Option B**, or Option C only if the endpoint is already available and approved.

Document potential providers, but implement one generic OpenAI-compatible adapter only when needed. Add Bedrock/Anthropic-specific adapters later based on an actual deployment decision.

---

# 13. Lean LLM architecture

```text
Intake application service
    |
    v
CandidateMappingService
    |
    +--> DeterministicMapper
    |
    `--> CandidateMapper protocol
             |
             +--> MockCandidateMapper
             `--> OpenAICompatibleCandidateMapper (optional)
```

## Important rule

The service chooses **whether** AI is appropriate based on policy. It does not choose a vendor.

The composition root chooses the provider based on configuration.

## Required local validation

After receiving an AI result:

- Validate JSON/schema.
- Reject unknown question IDs.
- Reject unknown register fields.
- Reject invalid allowed values.
- Reject missing source locators.
- Reject unsupported units.
- Reject candidates not grounded in the supplied fragment.
- Never auto-accept.
- Record provider, model, prompt version, request/response hash, and validation result if retained.

## Keep prompts out of business code

Prompt templates should be versioned resources belonging to the AI adapter/mapping capability, not inline strings in routes or application services.

---

# 14. Is a full “AI agent” needed?

No.

For document-to-question mapping, an autonomous agent with tools and iterative loops is unnecessary at first.

## Simple model call

```text
fragment + relevant schema -> structured candidate result
```

### Pros

- Predictable.
- Auditable.
- Small blast radius.
- Easy to validate.
- Lower token and latency cost.

## Agentic loop

```text
model chooses tools, searches catalog, rereads documents, retries mappings
```

### Pros

- More flexible for complex documents.
- Can explore unknown formats.

### Cons

- Harder audit.
- Higher cost.
- More prompt-injection risk.
- Difficult reproducibility.
- Harder to constrain.
- Unnecessary before deterministic extraction and simple mapping are proven.

### Recommendation

Start with a **single bounded structured inference call**, not an agent.

---

# 15. Spike-scope options

## Option 1 — UI-only spike

Build questionnaire pages backed by SQLite.

### Pros

- Fastest visual feedback.
- Tests HTMX and autosave.
- Easy stakeholder demonstration.

### Cons

- Does not validate workbook compilation.
- Does not validate candidate ingestion.
- Does not validate database portability.
- Risks producing a throwaway UI.

### Verdict

Too narrow.

---

## Option 2 — Persistence/domain spike only

Build catalog compilation, domain services, repositories, and SQLite/Oracle tests without UI.

### Pros

- Focuses on hardest technical boundaries.
- Strong portability evidence.
- Less presentation work.

### Cons

- Stakeholders cannot evaluate workflow.
- Does not prove server-rendered interaction.
- May over-focus on storage before usability.

### Verdict

Useful but incomplete.

---

## Option 3 — Thin vertical slice

Build one real path from workbook/catalog through UI, persistence, candidate review, and snapshot.

### Pros

- Tests architecture end to end.
- Produces reusable scaffolding.
- Exposes UX and data-model problems early.
- Gives realistic evidence for SQLite/Oracle decision.
- Supports a bounded mock-LLM workflow.

### Cons

- Requires disciplined scope.
- More work than a single-layer spike.
- Can expand uncontrollably unless acceptance criteria are strict.

### Verdict

**Recommended.**

---

# 16. What should be reusable versus disposable

## Build to promote

- Domain value objects/enums.
- Use-case services.
- Repository and unit-of-work protocols.
- SQLAlchemy model conventions.
- Catalog compiler.
- Response-type registry contract.
- Pydantic schemas.
- Candidate mapping protocol.
- Mock LLM provider.
- Focused templates/components.
- Persistence contract tests.
- Security validation utilities.

## Treat as spike-only

- Hard-coded demo identity/authentication.
- SQLite `create_all()` bootstrap.
- Minimal navigation.
- Limited response renderers.
- Sample/mock candidates.
- Simplified file storage.
- Manual Oracle test configuration.
- Temporary composition/configuration.

This prevents “copy the entire spike” from becoming the promotion strategy. Promote reviewed components, not the directory wholesale.

---

# 17. Data-model scope for the spike

Do not start with all 46 tables. Use approximately 10–14 concepts:

```text
applications
application_identifiers
catalog_releases
question_definitions
intakes
answer_instances
answer_revisions
evidence_items
import_runs
import_candidates
register_instances
register_rows
audit_events
intake_snapshots
```

Possibly omit users/roles initially by using one configured demo actor, unless authorization itself is being tested.

## Why fewer tables

The spike needs to validate:

- Catalog pinning.
- Answers and revisions.
- Candidate review.
- One register.
- Evidence lineage.
- Snapshot creation.
- Database portability.

It does not need to validate every future assignment, notification, approval, risk, and deliverable table.

---

# 18. Specific workbook design concerns to resolve before coding

## Stable IDs

The `App` sheet must not use 1–112 as durable IDs. Continue using catalog IDs such as `NET-001`.

## Workbook version

Add or externally record:

- Package version.
- Release date.
- Author/owner.
- Status: draft/published/retired.
- Source hash.
- Compatible catalog version.

## Sheet role

Each sheet needs a declared role:

```text
QUESTIONNAIRE_PROJECTION
SOURCE_CAPTURE
REGISTER_SCHEMA
REFERENCE_DATA
LEGACY_QUESTION_EXTENSION
```

## `Database` duplicate

Remove or intentionally map the duplicate RAC/Data Guard question.

## `Infra` and `Database` mappings

Each detail question must have:

- Stable ID.
- Relationship to canonical question/register.
- Response type.
- Required rule.
- Owner.
- Target outputs.
- Disposition:
  - canonical question;
  - register field;
  - duplicate;
  - retired;
  - supporting prompt/help text.

## `Provisioning`

Determine whether this is:

- Governing reference/master data.
- A static configuration file.
- A database-managed admin table.
- Application-specific input.

It should not be silently imported as questionnaire answers.

## Data validation

If the workbook remains a human authoring/capture surface, add Excel validation or rely on compiler enforcement. Compiler enforcement is mandatory regardless.

## Response column

Clarify whether the `App` response column is intended to be populated per application. If so, the workbook becomes both schema and instance data, which should be separated explicitly.

---

# 19. Recommended architecture decisions

I would propose these decisions for discussion.

## AD-DB-001 — SQLAlchemy is the dialect abstraction

Use SQLAlchemy 2.x for SQLite and Oracle. Do not create parallel hand-written SQL repositories.

## AD-DB-002 — Repositories express domain use cases

Repositories and unit-of-work hide sessions/transactions from web routes and application services. Do not build a generic CRUD abstraction.

## AD-DB-003 — Portable model subset

The spike avoids SQLite-only correctness mechanisms and validates normalization, JSON structures, and workflow policy in application/domain code where appropriate.

## AD-DB-004 — SQLite is the default spike backend

Oracle remains a supported target candidate and must pass a persistence contract suite before a production decision.

## AD-DB-005 — Database target remains an operational decision

The business/domain model does not select a database. Deployment configuration and the composition root select the SQLAlchemy URL/dialect.

## AD-LLM-001 — Runtime AI is optional

No core questionnaire, review, or generation behavior depends on an available LLM.

## AD-LLM-002 — Provider-neutral mapping port

Business services depend on `CandidateMapper`, not OpenAI, Copilot, Anthropic, or Bedrock SDKs.

## AD-LLM-003 — Candidate-only authority

Runtime AI can propose candidates and findings only.

## AD-LLM-004 — Mock provider in automated tests

All automated tests run without credentials, network, or cost.

## AD-LLM-005 — One real adapter at a time

Implement only the approved provider actually needed; document other potential adapters.

## AD-WB-001 — Consolidated workbook is not yet a published catalog

It is a design package whose `App` sheet mirrors catalog v0.2 and whose additional sheets require formal contracts.

---

# 20. Risks and mitigations

| Risk | Mitigation |
|---|---|
| Spike becomes production accidentally | Explicit promotion checklist; build only core boundaries to promote |
| Generic DB abstraction becomes an internal ORM | Use narrow repositories and SQLAlchemy UoW |
| SQLite hides Oracle incompatibility | Persistence contract tests against actual Oracle before production decision |
| Oracle slows the spike | Keep it optional and configuration-driven |
| Workbook row numbers become IDs | Retain catalog stable IDs |
| Workbook sheets are treated uniformly | Declare sheet roles and adapter contracts |
| 46-table schema slows learning | Implement only the vertical-slice subset |
| AI provider becomes mandatory | Mock/default disabled; deterministic path always works |
| AI output becomes accepted truth | Candidate-only state and mandatory human review |
| Endpoint sends private evidence over HTTP | No real evidence calls until HTTPS and governance are confirmed |
| Public CDN breaks internal/offline UI | Vendor static assets locally or use CSS/system icons |
| Hard-coded demo state leaks into production | Do not copy `app.js` data model; reuse visual patterns only |

---

# 21. Confirmed sequence before implementation

## Step 1 — Record accepted slice decisions

The following are confirmed:

- Root `src/migration_intake` production foundation.
- Thin vertical slice with all 112 questions editable through reusable response-type infrastructure.
- SQLAlchemy ORM plus narrow repositories and unit of work.
- SQLite local development and required Oracle contract validation.
- Mock plus disabled OpenAI-compatible candidate mapper using synthetic data only.
- Catalog-authoritative Workbook Option B.
- Per-application workbook upload.
- WaveUtil as the first complete register.
- Configured demo actor with audit identity.

## Step 2 — Update architecture documents

Before code, update or add decisions for:

- Oracle portability.
- Persistence boundary.
- Consolidated workbook authority.
- Runtime LLM abstraction.
- AI candidate-only policy.
- Spike scope and promotion criteria.

You are correct: current design documents do not adequately reflect Oracle or the LLM option.

## Step 3 — Normalize workbook/catalog contract

Produce a machine-readable decision for every sheet and resolve:

- IDs.
- Duplicates.
- Legacy/detail mappings.
- Reference-data role.
- Register keys.
- Response schemas.
- Conditions.

## Step 4 — Define spike acceptance tests first

Write explicit tests for:

- Catalog projection parity.
- Application/intake lifecycle.
- Answer revision.
- Candidate acceptance.
- Transaction rollback.
- Snapshot immutability.
- SQLite repository contract.
- Oracle repository contract when available.
- Mock LLM behavior.
- Web smoke flow.

## Step 5 — Scaffold only the vertical slice

Create production foundation code under `src/migration_intake`; do not build deferred SSO, notifications, ADS/DDD rendering, autonomous AI, or the complete future 46-table workflow.

## Step 6 — Review results

Use evidence from the spike to decide:

- SQLite versus Oracle deployment.
- Final package structure.
- Final migration strategy.
- Whether HTMX is sufficient.
- Whether a real LLM endpoint adds enough value.
- Which code should be promoted.

---

# 22. Decisions I recommend you make now

My recommended defaults are:

| Decision | Accepted direction |
|---|---|
| Implementation location | Root `src/migration_intake` |
| Slice style | Production-shaped thin vertical slice |
| Web stack | FastAPI + Jinja2 + HTMX |
| Domain framework | Plain Python plus Pydantic boundary schemas |
| Persistence | SQLAlchemy ORM + narrow repositories/UoW |
| Local database | SQLite |
| Shared test/production candidate | Oracle |
| Portability proof | Same contract tests; real Oracle pass required before completion |
| Catalog authority | Stable-ID catalog v0.2 |
| Workbook role | Per-application source/review package producing candidates |
| Workbook drift | Fail or quarantine unexplained drift |
| Editable breadth | All 112 questions through all 25 response-type contracts |
| First register | WaveUtil |
| Runtime AI | Candidate mapper only |
| Automated-test provider | Mock |
| Network adapter | Disabled OpenAI-compatible adapter; synthetic/fake-server tests only |
| Agentic runtime loop | No |
| Actor model | Configured demo actor with audit identity |
| Full 46-table model | Defer; implement the required relational subset |
| UI scope | Application, upload, all questions, WaveUtil, candidates, snapshot |
| Snapshot | Immutable and included |
| Oracle availability | Provisioning required; external completion blocker |

# Final verdict

Proceed with a **production-shaped thin vertical slice in root `src/migration_intake`**. It is the initial production foundation with intentionally constrained use cases, not disposable prototype code and not the complete production product.

Use SQLite to accelerate the spike, but design and test persistence around SQLAlchemy plus narrow repositories and a unit of work so Oracle remains viable. This is achievable without over-engineering as long as you avoid generic CRUD repositories, parallel backend implementations, and database-specific correctness assumptions.

Implement runtime LLM availability as an optional provider-neutral candidate-mapping capability. Include a mock implementation and one disabled OpenAI-compatible adapter tested with synthetic content against a fake HTTP endpoint. Do not send client evidence or enable a real endpoint until availability, TLS, authentication, authorization, retention, and data-governance requirements are confirmed.

Most importantly, do not treat the new workbook as one undifferentiated intake schema. Its `App` sheet exactly mirrors catalog v0.2 but omits critical metadata, while its other sheets represent several different architectural concepts that require explicit contracts.
