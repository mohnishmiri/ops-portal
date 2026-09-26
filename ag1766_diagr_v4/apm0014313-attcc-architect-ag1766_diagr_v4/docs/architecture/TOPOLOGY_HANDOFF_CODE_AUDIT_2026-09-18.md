# Topology Generation Remediation — Code-Verified Handoff

**Historical audit:** retain the observations below as dated evidence, not current
completion or worktree status. See the [independent review](docs/architecture/TOPOLOGY_REMEDIATION_IMPLEMENTATION_REVIEW_2026-09-18.md)
for corrected findings and the [active detailed design](docs/architecture/TOPOLOGY_DETAILED_DESIGN_AND_AGENT_IMPLEMENTATION_PLAN_2026-09-18.md)
for confirmed user direction, contract repairs, all finding-to-slice mappings and
25 copy-paste implementation prompts. No remediation is implied by these links.

**Date:** 2026-09-18  
**Repository:** `apm0014313-attcc-architect`  
**Branch:** `ag1766_diagr_v4` (HEAD `a9fcfa5`, plus a substantial uncommitted working tree)  
**Basis for this handoff:** Direct reading of source code and test files. `STATE.md`,
prior handoff `.md` files, and the narrative sections of
`TOPOLOGY_GENERATION_REMEDIATION_DESIGN_PLAN_2026-09-17.md` were **not** used as
evidence of completion — only as pointers to where to look. Every status claim
below cites a file and, where useful, a line number.

**Why this document exists:** The design plan's session summary (dated
2026-09-17) claims only P0A/P0B/P1/P2A were implemented, all "✅ COMPLETE." In
reality the working tree already contains substantial, **uncommitted**
progress on P2B, P3, P4, P5A/B/C, P6, P7, P8, and P9 — but several of the
plan's own "complete" claims are only partially true, and several later
packets have real defects or missing pieces that are not yet visible from any
`.md` file. This handoff gives the next agent/developer an accurate starting
point.

---

## 1. Repository state check first

```
git log --oneline -3
a9fcfa5 (HEAD -> ag1766_diagr_v4) feat: implement Wave 0 remediation (P0A, P0B, P1, P2A)
3ba52da [SALESENAB-15720] Aded interfaces to input
3a75c51 docs: add topology generation remediation design plan
```

`git status` at audit time showed **uncommitted modifications** to snapshot,
catalog, and answer-repository files, plus **untracked** new files:

```
Untracked (selected):
  CG-2_IMMUTABLE_TOPOLOGY_CONTRACT.md
  D-10_CATALOG_DECISION_RECORD.md
  P5A_RESOURCE_DOMAIN_CONTRACT.md
  P6_PROFILE_SCHEMA_DESIGN.md
  P9_RENDERER_RESULT_DESIGN.md
  src/migration_intake/application/services/base_diagram.py
  src/migration_intake/application/services/resources.py
  src/migration_intake/catalog/data/RELEASE_MANIFEST.md
  src/migration_intake/persistence/models_resources.py
  src/migration_intake/persistence/repositories/resources.py
  src/migration_intake/topology/approval.py
  src/migration_intake/topology/orchestration.py
  src/migration_intake/topology/profiles/           (loader.py + framework)
  src/migration_intake/topology/projection.py
  src/migration_intake/topology/renderer/
  tests/unit/application/test_resource_service.py
  tests/unit/persistence/
  tests/unit/topology/test_approval.py
  tests/unit/topology/test_base_diagram_governance.py
  tests/unit/topology/test_orchestration.py
  tests/unit/topology/test_profile_loader.py
  tests/unit/topology/test_projection.py
  tests/unit/topology/test_renderer.py
```

**Action item for the coordinator:** none of this is committed. Before
assigning further work, decide whether to commit this baseline (recommended,
since it is real progress) or discard it. Either way, the next agent must not
assume it is finished just because it exists.

---

## 2. Packet-by-packet verified status

Legend: ✅ Complete and verified · 🟡 Partial · ❌ Not started / non-functional.

### P0A — One status policy: ✅ Complete
- `src/migration_intake/topology/status.py` implements `evaluate_generation_status()` as a pure function returning `(status, issues)`.
- Called from `application/services/topology_generation.py` for persistence; the HTML report consumes the same policy output — not a second calculation.
- `tests/unit/topology/test_topology_status.py` truth-table covers missing-fact, fill-warning, fill-error, no-effective-mutation, and clean-run cases.
- The previously known-wrong unconditional `READY_FOR_REVIEW` assertion in `tests/unit/topology/test_topology_boundaries.py` is gone.

### P0B — Environment and authorization containment: 🟡 Partial
- `src/migration_intake/config.py` implements `AWS_OUTPOST_ALLOW_LOCAL_REMOTE_DATABASE` (default false) and fails startup for local mode + non-loopback DB without the explicit override; forbidden in `shared_test`/`production`. Tested in `tests/unit/test_config.py`.
- `web/security.py` defines `TOPOLOGY_BASE_UPLOAD`, `TOPOLOGY_BASE_REVIEW`, `TOPOLOGY_GENERATE`, `TOPOLOGY_ARTIFACT_DOWNLOAD`, `TOPOLOGY_RUN_APPROVE` capability constants.
- **Gap:** `web/routes/topology.py` only calls `require_capability()` once, on the run-approval route (line 391). Upload, generate, and both download routes have **no** topology-specific capability check. Verified by direct grep — only 1 match for `require_capability` in the whole routes file.

### P1 — Repair canonical candidate ingress: ✅ Complete
- `application/services/candidates.py`: `accept_candidate()` and `accept_with_edit()` both call the same `_resolve_question_target()` resolver and both raise `NonQuestionCandidateError` for non-QUESTION targets.
- Both paths run inside one `uow_context(...)` and call `save_answer_in_uow()` — answer revision, evidence link, and candidate disposition commit together.
- No swallowed `QuestionNotFoundError`; unmapped targets raise `CandidateTargetNotInCatalogError` before any mutation.

### P2A — Catalog census and collision guards: ✅ Complete (enforcement verified)
- `catalog/census.py` computes deterministic `source_hash`/`catalog_hash` and detects same-version/different-hash collisions.
- `application/services/catalogs.py::publish_release()` actually enforces the guard (raises `CatalogVersionConflictError`), not just a detection report. 11 catalog tests pass covering this.

### P2B — Authoritative release manifest and repinning: 🟡 Partial
- D-10 has been recorded: `D-10_CATALOG_DECISION_RECORD.md` selects `1.0.0` / 112 questions as authoritative.
- `catalog/bootstrap.py` pins to `CATALOG_VERSION = "1.0.0"` / `CATALOG_FILENAME = "catalog-1.0.0.csv"`; `catalog/data/RELEASE_MANIFEST.md` documents the release; `backfill_catalog_hashes()` exists for PERF rows with null `catalog_hash`.
- **Gap (packet's second deliverable, entirely missing):** no intake-repinning service, route, or test exists anywhere in the tree. A draft intake pinned to `0.2.0`/`0.3.0` has no governed path to move to `1.0.0`.
- **Gap:** `ensure_catalog_published()` has no isolated test proving a clean-database startup publishes exactly the reviewed artifact once (idempotently) — only its constants are tested.

### P3 — Repair canonical snapshot content: 🟡 Partial
- `application/services/snapshots.py::_build_canonical_answers()` is implemented for real (previously returned `[]`): filters to `confirm_state == "CONFIRMED"`, includes response type/schema version/provenance/revision number/author.
- `application/snapshots.py` defines schema `2.0.0`, deterministic ordering, SHA-256 hashing; `SUPPORTED_SCHEMA_VERSIONS = {"1.0.0", "2.0.0"}` is declared.
- 13 (`test_snapshot_service.py`) + 12 (`test_snapshot_serializer.py`) tests pass, covering confirmed-vs-draft filtering, provenance survival, determinism/order-independence, hash verification.
- `_build_canonical_target_resources()` correctly returns `[]` as an explicit P5 placeholder (this is expected, not a defect).
- **Gap:** `SUPPORTED_SCHEMA_VERSIONS` is defined but **never checked** anywhere a snapshot is loaded — there is no deserialize/validate-on-load function. A tampered or legacy (`1.0.0`) snapshot would not be rejected or flagged; it would simply be read as-is (or fail unpredictably) when topology generation eventually consumes it.

### P4 — Pure snapshot-to-topology projection adapter: 🟡 Partial
- `topology/projection.py` is a genuine pure function of canonical JSON (no SQLAlchemy import); raises `UnsupportedSchemaError`/`InvalidSnapshotError` for bad input; deterministic projection hashing; environment/scope filtering keeps cross-environment resources distinct. 22 tests pass.
- **Gap:** `IdentityMismatchError` is defined (line ~251) but **never raised** — `CTL-001` vs. snapshot application-identity equality is not actually checked, contradicting D-08/G-04's intent.
- **Gap:** the legacy `adapter.py` (`FACT_REGISTRY`, `extract_topology_data`, `extract_topology_facts`) still exists side-by-side with the new pure `projection.py`, and — critically — **generation still calls the old one** (see P8 below), so P4's work is not actually on the execution path yet.
- **Gap:** `MissingValuePolicy.PLACEHOLDER` is defined but unused; missing values become `None` with no policy applied.

### P5A — Freeze the resource-domain contract: ✅ Complete (design-only, as scoped)
- `P5A_RESOURCE_DOMAIN_CONTRACT.md` plus the schemas actually implemented in P5B/P5C match the scoped design-only deliverable.

### P5B — Resource persistence: 🟡 Partial, **blocked for any real deployment**
- `persistence/models_resources.py` (`TargetResource`, `TargetResourceRevision`) and `persistence/repositories/resources.py` (~700 lines) implement append-only revisions, compare-and-set writes, cycle detection, parent-kind matrix, and scope-based uniqueness. Tests in `tests/unit/persistence/test_resource_repository.py` pass.
- **Critical gap:** there is **no Alembic migration**. `src/migration_intake/persistence/migrations/versions/` stops at `0016_interfaces_register.py` — confirmed by direct directory listing. The resource tables exist only as ORM metadata; tests only pass because they call `Table.create(engine, checkfirst=True)` directly, bypassing Alembic. Running `alembic upgrade head` today will **not** create these tables in SQLite or Oracle.
- Payload validation checks required/optional attribute presence but not type/format (e.g., `vpc_id` accepts any string).

### P5C — Adoption and canonical integration: 🟡 Partial
- `application/services/resources.py` implements `propose_resource()`, `adopt_provisioning()` (explicit, no auto site-selection), a review state machine (`PROPOSED → REVIEWED → CONFIRMED`), and `compute_register_status()`. Tests pass in `tests/unit/application/test_resource_service.py`.
- **Gap:** as noted under P3, `SnapshotService._build_canonical_target_resources()` still returns `[]`, so adopted/confirmed resources never reach a canonical snapshot and therefore never reach the projection or renderer. P5C's adoption pipeline is functionally disconnected from the rest of the system until this is wired up.
- **Gap:** `AdoptionRequest.reference_row_id` is an unchecked string; no existence validation against actual provisioning rows.

### P6 — Build and validate `CCPM_OUTPOST_V1`: ❌ Not started (framework built, content missing)
- `topology/profiles/loader.py` is a complete, tested framework: profile manifest dataclasses, `MANDATORY/CONDITIONAL/OPTIONAL` slot enums, component + combined SHA-256 hashing, and `check_profile_compatibility()` producing structured diagnostics.
- **Critical gap:** there is **no `ccpm_outpost_v1/` directory** anywhere in the repo — no `manifest.json`, `slots.json`, `mappings.json`, `naming.json`, or `issues.json` for the actual governed CCPM template. `file_search` for this path returns zero results.
- **Critical gap:** `pyproject.toml` does not package any profile directory (only `slot_bindings.json` is referenced), so even a completed profile would not survive a wheel build today.
- **Regression against the plan's own G-10 requirement:** `topology/fill.py` still defines `_FALLBACK_BINDINGS` (the old six prototype slots — `app_name`, `app_acronym`, etc.) and silently falls back to them when configuration is missing (`fill.py` ~line 321). The plan explicitly requires removing this fail-open behavior; it is still present.

### P7 — Govern base diagrams and schema transitions: ❌ Not started / non-functional
- `application/services/base_diagram.py` and `tests/unit/topology/test_base_diagram_governance.py` exist and read as if a full `UPLOADED_DRAFT → COMPATIBLE → APPROVED/REJECTED/SUPERSEDED` state machine were implemented.
- **Verified directly, this is dead code:** `base_diagram.py` imports `BaseDiagramState`, `ConcurrencyConflictError`, and other symbols from `persistence.repositories.topology` — **none of these exist in that module** (confirmed via grep: zero matches for `class BaseDiagramState`, `class ConcurrencyConflictError`, `def mark_compatible`, `def approve_base_diagram`, `def list_audit_events`). `models_topology.py` has no `row_version` column and no `TopologyAuditEvent`/`CompatibilityResult` model.
- **Consequence:** `base_diagram.py` cannot be imported without `ImportError`, and its entire test file cannot even collect. Any other packet (P8, P10) that assumes base-diagram governance is available is building on a non-functional foundation.

### P8 — Pin immutable inputs and orchestrate generation: 🟡 Partial, **core defect (G-02) still open**
- `topology/orchestration.py` defines real, tested pure domain objects: `TopologyInputRecord`, run-mode enum (`OFFICIAL_SNAPSHOT`/`DRAFT_PREVIEW`), `RunPhase`, and `compute_idempotency_key()`.
- **Critical gap — verified directly:** none of this is wired into the actual generation path. `application/services/topology_generation.py::_generate_diagram()` (around line 613) still calls `extract_topology_data(session, intake_id)`, which internally queries live `AnswerInstance.current_rev_id` rows — the exact G-02 defect the plan describes as critical. The `snapshot` argument passed into `_generate_diagram()` is accepted but not used to build the projection.
- The one test that looks like it proves snapshot-pinned generation
  (`test_topology_service_generates_pinned_artifacts_from_snapshot` in
  `tests/unit/topology/test_topology_boundaries.py`) **monkeypatches**
  `extract_topology_data` to a mock, which hides the live-query defect rather
  than proving it is fixed. This is exactly the anti-pattern the plan's own
  rule 8 (section 11.1) warns against: passing unit tests without a real
  cross-boundary proof.
- `GenerationRun` (in `models_topology.py`) has no `mode`, `input_hash`, `profile_hash`, `projection_hash`, or `phase` columns — `TopologyInputRecord` cannot currently be persisted even if it were wired in.
- No idempotency check is performed before creating a run; `compute_idempotency_key()` is tested in isolation only.

### P9 — Pure renderer, manifest, and deterministic reports: 🟡 Partial
- `topology/renderer/core.py` is a real, well-tested pure renderer: `RenderInput`/`RenderOutput` dataclasses, XML parsing under explicit limits, XXE/external-entity rejection tests, structural before/after snapshotting (`_structural_snapshot()`), mutation tracking, and a manifest with all pinned hashes. 200+ tests in `tests/unit/topology/test_renderer.py` pass, including a same-input/same-output determinism test.
- Status is correctly sourced from P0A's `status.py` — not recomputed.
- **Gaps:** no test proves a missing-mandatory-slot blocks success before an artifact is marked complete; optional-gap issue emission (`SuspiciousMarker`) is defined but under-tested; no test covers compressed (`.gz`) diagram rejection; code comments mark D-13 (security parser limits) as still provisional/pending sign-off.
- Because P6 has no real profile and P8 doesn't call the new projection path, P9's renderer is currently untested end-to-end against real inputs — only synthetic unit fixtures.

### P10 — Authorization, review, supersession, operator UX: ❌ Not started beyond approval
- Only the run-approval route enforces a capability (`Capability.TOPOLOGY_APPROVE`, line 391 of `web/routes/topology.py`); upload/generate/download routes have none.
- No supersession code (`SUPERSEDED` run state) exists anywhere.
- No gap-approval policy code exists.
- No browser tests for any topology journey exist under `tests/browser/` (which has 9 journeys for other features, none for topology).

### P11 — Activate reviewed PERF data: ❌ Not started (correctly — this is operational and depends on P7/P8/P10 being real)
- No runbook execution evidence; `scripts/` contains only `generate_catalog_census.py`. This is appropriate given P7/P8 are not actually ready.

### P12 — Certify release and operational recovery: ❌ Not started
- No restart/recovery, retention, backup/restore, or release-certification tests exist anywhere in `tests/`.

---

## 3. Contract-gate status (verified, not claimed)

| Gate | Verified status |
|---|---|
| CG-0 Baseline/containment | 🟡 Partial — P0B config guard is real; capability enforcement on topology routes is not. |
| CG-1 Canonical ingress | 🟡 Partial — P1 is solid; P2B repinning is missing, so "one immutable catalog artifact/version identity" is only half-true (identity exists, migration policy for existing intakes does not). |
| CG-2 Immutable topology contract | ❌ Not achieved — P3's snapshot lacks load-time validation, P4's identity check is unraised, and P8 does not consume the projection at all. The contract types exist in isolation but are not enforced end-to-end. |
| CG-3 Profile and persistence contract | ❌ Not achieved — P6 has no real profile; P5B has no migration; P7 is non-functional. |
| CG-4 Governed generation | ❌ Not achieved — depends on CG-2/CG-3. |
| CG-5 Release certification | ❌ Not achieved. |

---

## 4. Recommended next actions, in priority order

1. **Fix P7 first.** `base_diagram.py` cannot import today. Either implement the missing `BaseDiagramState` enum, `ConcurrencyConflictError`, `row_version` column, `TopologyAuditEvent` model, and repository methods (`mark_compatible`, `approve_base_diagram`, `reject_base_diagram`, `supersede_base_diagram`, `list_audit_events`) it depends on, or explicitly mark P7 as reverted/not-started and remove the misleading scaffold so nobody builds on it by accident.
2. **Rewire P8 to actually use the snapshot/projection.** Change `_generate_diagram()` to build a `TopologyProjection` via `ProjectionAdapter.project(snapshot.canonical_json, ...)` instead of calling `extract_topology_data(session, intake_id)`. Replace the monkeypatch-based test with a real query-tripwire test (e.g., a session spy that fails the test if any `AnswerInstance` query happens during official generation).
3. **Add the missing Alembic migration for P5B** (`res_resources`, `res_revisions`, provenance-link tables) so resource persistence can run outside of test-only `Table.create()` calls.
4. **Author real `CCPM_OUTPOST_V1` profile content** (synthetic-fixture-safe, no client bytes) and delete `_FALLBACK_BINDINGS` from `fill.py`; add the wheel-packaging include in `pyproject.toml`.
5. **Close P2B's repinning gap and P3's load-time validation gap** — both are contained, well-scoped pieces of work.
6. **Only after 1-5**, extend P10 capability enforcement to the remaining 4 topology routes and add supersession + browser coverage.
7. Do not start P11 (PERF activation) until P7/P8/P10 above are genuinely complete — PERF is a shared, credentialed environment and premature activation against a broken base-diagram/orchestration layer would risk exactly the kind of silent-success failure this whole plan exists to prevent.

## 5. Process note for the coordinator

Several packets exist as uncommitted files with no corresponding entry in
`STATE.md` or the plan's session summary. Going forward, treat any `.md`
status claim as a hypothesis to verify against code, and require that "cross-
boundary proof" (plan section 11.1, rule 8) be a real integration test — not a
mock/monkeypatch of the exact function whose behavior is in question, as
happened with P8's snapshot test. Commit or explicitly discard the current
working tree before assigning further packets, so the next audit has a clean
starting commit to diff against.
