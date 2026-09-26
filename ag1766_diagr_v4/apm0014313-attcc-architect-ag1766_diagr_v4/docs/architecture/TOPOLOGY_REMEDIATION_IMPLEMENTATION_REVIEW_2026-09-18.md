# Topology Remediation: Independent Review and Completion Plan

**Date:** 2026-09-18
**Status:** Review complete; implementation and release authorization pending.
**Baseline:** `ag1766_diagr_v4`, commit `6ed8af2`; clean worktree at review start.
**Scope:** Current checkout, topology execution path, persistence, immutable inputs,
profiles, renderer, authorization, and regression evidence. No client evidence,
remote database, credentials, or external provider calls are used in this review.

**Current coding specification:** [Detailed design and agent implementation plan](TOPOLOGY_DETAILED_DESIGN_AND_AGENT_IMPLEMENTATION_PLAN_2026-09-18.md).
User decisions recorded there on 2026-09-18 supersede this review's provisional
single-context/label-only design recommendations: the program includes separately
governed label-only and structural capabilities, combined environments/sites, explicit
authorized architect self-approval, a PERF pilot before production, and immutable legacy
history. The 23 findings and dated verification below remain the evidence baseline;
the detailed specification owns contracts, slice prompts and new-scope risk controls.

## 1. Executive Decision

Do not activate official topology generation in PERF or production yet. Preserve
the implemented domain modules, but complete and prove their integration before
treating packet completion or isolated unit tests as release evidence.

The active generation service still uses live answers while recording a snapshot
hash. The replacement renderer is not yet a governed slot renderer: it replaces
markers but does not enforce profile slot requirements, and reports success after
parsing without applying the shared generation-status policy.

## 2. Source Documents

- [Original plan](TOPOLOGY_GENERATION_REMEDIATION_DESIGN_PLAN_2026-09-17.md).
- [Anil updated plan](../../TOPOLOGY_GENERATION_REMEDIATION_DESIGN_PLAN_2026-09-17_Anil_2026-09-18.md).
- [Code-review handoff](../../TOPOLOGY_HANDOFF_CODE_AUDIT_2026-09-18.md).

These are requirements and review hypotheses, not evidence that the current
runtime satisfies them. Historical completion counts and commit-state statements
must be reconciled with the present checkout.

## 3. Verified Gap Register

Critical means an official result or approval can misrepresent its inputs or
validity. High means deployment, isolation, lineage, or integrity is not enforced.
Evidence is static source review unless an executed probe is identified below.
"Additional" means newly specified or materially deeper than the supplied audit,
not necessarily a new high-level requirement absent from the original plan.

| ID | Severity | Finding | Evidence |
|---|---|---|---|
| R-01 | Critical | Official generation records snapshot metadata but calls the live database adapter. | [Generation service](../../src/migration_intake/application/services/topology_generation.py#L609) |
| R-02 | High | Upload, generation, and downloads lack topology capability enforcement; URL ownership checks are present but are not authorization. | [Routes](../../src/migration_intake/web/routes/topology.py#L185) |
| R-03 | Critical | Replacement renderer does not evaluate mandatory slots or shared status policy; parsed input can report success with unresolved markers and false input hashes. **Additional; reproduced.** | [Renderer](../../src/migration_intake/topology/renderer/core.py#L720) |
| R-04 | High | Projection mappings and context are not applied to answers; intake ID is assigned to snapshot ID. | [Projection](../../src/migration_intake/topology/projection.py#L334) |
| R-05 | Critical | New approval preflight classifies missing artifacts and failed readiness as warnings. Hash and manifest checks are optional; an official-mode dictionary with neither can be approvable. **Additional; reproduced.** | [Approval preflight](../../src/migration_intake/topology/approval.py#L406) |
| R-06 | High | Base governance cannot import: repository exceptions, states, operations, and persistence columns are absent. This is a broken contract, not merely an unwired route. **Collection error reproduced.** | [Base service imports](../../src/migration_intake/application/services/base_diagram.py#L24) |
| R-07 | High | Resource tables have no Alembic revision; current head is `0017`. Topology input, compatibility, review concurrency, and durable audit contracts also lack the required schema. | [Migrations](../../src/migration_intake/persistence/migrations/versions/), [topology models](../../src/migration_intake/persistence/models_topology.py) |
| R-08 | High | Same-version/same-source publication returns before compiled-hash comparison. A changed compiled hash/compiler can be silently treated as idempotent success. **Additional; reproduced.** | [Publication](../../src/migration_intake/application/services/catalogs.py#L78) |
| R-09 | High | Freeze checks readiness outside its write transaction, ignores the boolean CAS result, and re-reads an answer head to collect provenance. Concurrent changes can invalidate readiness or mix value and lineage. **Additional mechanism; race not executed.** | [Freeze](../../src/migration_intake/application/services/snapshots.py#L98), [answer capture](../../src/migration_intake/application/services/snapshots.py#L281), [CAS return](../../src/migration_intake/persistence/repositories/intakes.py#L70) |
| R-10 | High | Answer confirmation creates a new revision without carrying response schema version or evidence links. Resource review likewise creates a revision without its prior provenance. **Additional; resource loss reproduced, answer path source-verified.** | [Answer confirmation](../../src/migration_intake/application/services/answers.py#L444), [resource review](../../src/migration_intake/application/services/resources.py#L427) |
| R-11 | High | Resource reparent increments the head revision but inserts no revision row; snapshot helper then omits that resource. Retire/supersede do not advance the concurrency version and discard actor/reason arguments from history. **Additional; reparent omission reproduced.** | [Resource transitions](../../src/migration_intake/persistence/repositories/resources.py#L347), [snapshot export](../../src/migration_intake/application/services/resources.py#L682) |
| R-12 | High | Parent checks omit intake/lifecycle/environment/site agreement and active-parent checks. Supersession omits self/scope/active-successor guards. The repository accepts a foreign-intake parent. Scope uniqueness omits site/tier; nullable environment also needs a portable uniqueness design. **Additional; foreign parent reproduced.** | [Resource creation](../../src/migration_intake/persistence/repositories/resources.py#L92), [supersession](../../src/migration_intake/persistence/repositories/resources.py#L403), [resource model](../../src/migration_intake/persistence/models_resources.py) |
| R-13 | High | Resource readiness counts retired/superseded rows and aggregates all environments/sites; missing revisions need not prevent COMPLETE. **Additional; retired confirmed placement reported COMPLETE in probe.** | [Register status](../../src/migration_intake/application/services/resources.py#L596) |
| R-14 | High | Snapshot resource builder remains empty. Its canonical resource type and service export omit parent identity; projected resources drop provenance. Snapshot answers omit author/revision ID despite available query fields; identifiers lose raw value and select primary by iteration order. | [Snapshot contract](../../src/migration_intake/application/snapshots.py), [resource placeholder](../../src/migration_intake/application/services/snapshots.py#L322), [projection](../../src/migration_intake/topology/projection.py) |
| R-15 | High | Projection accepts SOURCE resources and resources with missing environment/site into a selected target context. It does not execute response selectors, response-shape validation, identity reconciliation, conflict/cardinality policy, or mapping missing-value policy. **Additional scope leak reproduced.** | [Projection resource filter](../../src/migration_intake/topology/projection.py#L438) |
| R-16 | High | No actual governed profile exists. Compatibility checks only version/resource-kind presence, not diagram pages, slots, duplicates, or stale labels. Base service even supplies base hash as a projection-hash proxy. **Additional false compatibility reproduced.** | [Profile compatibility](../../src/migration_intake/topology/profiles/loader.py#L543), [base compatibility](../../src/migration_intake/application/services/base_diagram.py#L276) |
| R-17 | High | Profile hash covers component digests, not manifest semantics; empty hash/components are allowed, paths are not confined, duplicate token IDs overwrite lookup entries, and unknown components are ignored. Version parsing fails open to string comparison; `packaging` is an undeclared direct runtime import. **Additional; source-verified.** | [Profile loader](../../src/migration_intake/topology/profiles/loader.py#L277), [dependencies](../../pyproject.toml) |
| R-18 | High | Replacement XML parser scans UTF-8-decoded text but parses original bytes: UTF-16 entity declarations bypass the scan and expand. Page limit is unused, depth is checked recursively after parsing, and root/compressed/duplicate-ID policy is absent. Active upload reads the entire file before its size check. **Additional encoding and page-limit probes reproduced.** | [Parser](../../src/migration_intake/topology/renderer/core.py#L379), [upload](../../src/migration_intake/web/routes/topology.py#L211) |
| R-19 | High | New renderer scans markers globally rather than governed page/cell slots, supports only dictionary paths despite list-based projection answers/resources, and uses defaults as facts. It has no independent structural invariant check; mutation IDs restart per cell, page names remain `root`, and counts represent marker operations rather than changed cells. **Additional; source-verified.** | [Binding](../../src/migration_intake/topology/renderer/core.py#L520), [diagram processing](../../src/migration_intake/topology/renderer/core.py#L578) |
| R-20 | High | Active orchestration does rendering/storage inside one database transaction, has no durable captured input/idempotency reservation/recovery phase, and retrieves bytes without digest verification. A caught storage failure can commit partial artifact metadata; a process exit can lose the run record while files remain. | [Generation](../../src/migration_intake/application/services/topology_generation.py#L270), [retrieval](../../src/migration_intake/application/services/topology_generation.py#L505) |
| R-21 | High | Active approval uses snapshot presence instead of explicit mode and accepts GENERATED_WITH_GAPS without issue-level policy or integrity checks; repository updates lack CAS/audit. New policy accepts self-supersession and checks rationale presence by gap ID rather than non-empty trusted decision content. **Additional self-supersession reproduced.** | [Active approval](../../src/migration_intake/application/services/topology_generation.py#L436), [new review validation](../../src/migration_intake/topology/approval.py#L497), [supersession](../../src/migration_intake/topology/approval.py#L572) |
| R-22 | High | Startup automatically backfills hashes/repairs published options; backfill matches source hash without verifying stored release version and persisted contract. D-10 has an APPROVED banner but pending named signatories and abbreviated digests; no executable repinning workflow exists. **Governance authorization remains unverified.** | [Bootstrap](../../src/migration_intake/catalog/bootstrap.py#L106), [D-10](../../D-10_CATALOG_DECISION_RECORD.md) |
| R-23 | Medium | New orchestration readiness hashes include random check IDs; version comparison is lexical and ignores the maximum; phase transitions are unrestricted and failure records the new FAILED phase rather than the failing phase. Input hashes omit generator version while renderer/approval disagree on manifest status and run-mode vocabulary. **Additional; source-verified.** | [Orchestration](../../src/migration_intake/topology/orchestration.py), [render manifest](../../src/migration_intake/topology/renderer/core.py#L264) |

R-17 path handling is a latent trust-boundary defect, not evidence of a currently
exposed remote arbitrary-file-read route. R-09's concurrency outcome requires the
scheduled multi-session regression proof. Do not overstate either as an observed
production incident.

## 4. Corrections to the Supplied Reviews

- The implementation is committed at this baseline, not an uncommitted scaffold
	to discard. Preserve it and repair the owning contracts.
- P0A works on the legacy path, but the replacement renderer does not use it.
- P1's shared resolver/UoW is present. This does not prove provenance survives
	later confirmation; R-10 is a separate downstream regression boundary.
- P2A enforces different-source collisions, but R-08 prevents a complete verdict.
- P3 now includes confirmed answers, but neither transaction safety nor complete
	lineage/parent serialization is proved. Empty resources are a delivery blocker,
	not an acceptable placeholder once declaring the combined P5 slice complete.
- P4 is pure but not a functioning typed fact projection. R-04/R-15 are more than
	an unused exception or missing placeholder implementation.
- P5A/B/C need contract repair, not simply a migration and snapshot hook.
- P6 is incomplete both in profile content and compatibility implementation.
- P7 import failure is confirmed; its proposed compatibility behavior also needs
	repair before implementing the missing repository API.
- P8 contains useful data classes/helpers, not a transactional orchestrator.
- P9 has **34 test functions**, not evidence of 200+ renderer tests. Independent
	structural comparison exists in the old [filler](../../src/migration_intake/topology/fill.py#L170),
	not the replacement core. Reuse this property rather than losing it.
- P10 gap/supersession helpers exist in [approval.py](../../src/migration_intake/topology/approval.py),
	but are disconnected and fail open in the reproduced cases.
- Alembic head is `0017` (AI mapping runs), not `0016`. Reserve subsequent numbers
	only after checking the integration branch head; do not overwrite migrations.
- Missing `force-include` entries alone do not prove Hatch will exclude package
	data. No real profile exists to package today; prove inclusion in an installed
	wheel rather than declaring a packaging defect from configuration alone.
- Shared-test/production startup is already blocked until enterprise authentication
	is configured in [main.py](../../src/migration_intake/main.py#L117). Keep that guard;
	do not imply these routes are currently an authenticated enterprise deployment.
- D-10 authorization cannot be inferred from its banner. Obtain the actual named
	decision record and full digests, particularly if an existing `1.0.0` differs.

**Gate verdict:** CG-0 and CG-1 remain partial; CG-2 through CG-5 are not met.
P11 remains blocked. This review does not certify a current PERF database state.

## 5. Target Design

### 5.1 One Production Path

```text
authorized command + explicit mode/context/profile
	-> validated immutable snapshot OR consistent preview capture
	-> typed projection + deterministic readiness/compatibility result
	-> durable input envelope + reserved run
	-> pure governed renderer
	-> verified content-addressed artifact bundle
	-> atomic finalization + audit
	-> integrity-checked review/download/downstream linkage
```

Keep routes thin. Application services own transactions and authorization
decisions; repositories implement portable atomic predicates; pure policies decide
states. Keep the legacy adapter/filler behind an explicit non-authoritative legacy
boundary until the new vertical slice passes, then remove it from official call
sites. Never fall back from failed official validation to live answers or defaults.

### 5.2 Immutable Contracts

1. **Snapshot envelope:** repository snapshot ID, intake/application/catalog IDs,
	 exact stored JSON bytes/hash, schema version, source and compiled catalog hashes.
	 Validate relational identity as well as the JSON hash. Do not derive snapshot ID
	 from the intake. Legacy v1 remains readable for history, but unsupported topology
	 inputs return a stable diagnostic; do not rewrite old snapshots.
2. **Snapshot content:** pin answer instance/revision IDs, response schema version,
	 author/time, review/confirmation/applicability, typed raw/normalized identifiers,
	 and sorted provenance. Resource records include stable resource/revision IDs,
	 parent identity, lifecycle/state, exact scope, payload schema, and provenance.
	 Evolve the schema explicitly if existing v2 snapshots lack these required fields.
3. **Projection:** one canonical serializer shared by hashing, persistence, renderer,
	 and tests. Define application identity/name/acronym, selected context, typed
	 scoped facts/resources, lineage, and stable issues. No arbitrary `Any` profile
	 or guessed conversion of the dataclass to the mock dictionary shape.
4. **Mapping selectors:** versioned mapping keyed by catalog contract hash, question,
	 response type/version, typed member selector, lifecycle, scope, and cardinality.
	 Validate CTL-001 against the appropriate typed identifier, not a database UUID.
	 Confirm CTL-002 member ordering with the data owner. Select zero values as a gap,
	 one as a fact, and multiple distinct exact-scope values as a blocker.
5. **Scope:** environment/site/variant are explicit at command entry. SOURCE is not
	 TARGET. Missing scope is unknown, not a wildcard. Any inherited/global fact must
	 have an explicit allowed scope rule. Preserve repeated resources and reject
	 ambiguity; do not choose by confidence, list order, or primary-by-first-row.
6. **Input envelope:** pin canonical projection bytes/hash, snapshot/capture identity,
	 catalog, base bytes/hash, profile release/hash, parser/policy version, generator
	 build, context, and one recorded render timestamp. Hash canonical semantic
	 fields; exclude random operational IDs from semantic readiness hashes.
7. **Result:** one typed result contains binding outcomes, stable issue IDs/severity,
	 before/after markers, attempted writes, changed-cell count, structural verdict,
	 and shared generation status. HTML, persistence, and approval consume it without
	 reinterpretation. Use one enum for OFFICIAL_SNAPSHOT and DRAFT_PREVIEW.

### 5.3 Transaction and Resource Integrity

- All canonical writers and freeze acquire the same intake write fence/version
	protocol. Recheck readiness and capture heads within that transaction; a failed
	CAS aborts snapshot, state, and audit together. Oracle READ COMMITTED alone is
	insufficient to keep several head reads stable. Use consistent lock order and
	bounded retries; test the real competing sessions.
- Fetch value, revision ID, schema, and provenance from the same revision selection.
	Confirmation copies unchanged lineage into the new revision atomically; edits
	require explicit lineage decisions. Keep review rationale outside resource payload.
- Separate resource head `row_version` from immutable content `revision_number`.
	Every state/parent change increments the former and appends a revision or typed
	event that can reconstruct the historical graph. Never increment a content
	revision without inserting that revision; never drop a missing head silently.
- Validate parent/successor ownership, allowed kind, active state, lifecycle, and
	scope. Cross-scope/global parent relationships require an explicit domain rule.
	Serialize parent retirement against child creation/reparenting to prevent races.
- Define a canonical resource identity tuple including required scope dimensions.
	Represent unknown scope explicitly and use portable non-null uniqueness keys;
	do not rely on different SQLite/Oracle NULL-unique behavior. Add a composite
	current-revision ownership FK where feasible, or a tested repository invariant.
- Adoption loads the actual scoped provisioning row and its reviewed revision;
	validate source, applicability, freshness, and actor authority. Client-supplied
	IDs/attributes alone are not evidence. Resource commands reject frozen intakes.
- Readiness uses active, confirmed, validated resources in the selected context,
	complete parent chains and lineage. Missing revision, conflict, invalid identifier,
	absent required resource, or unreviewed adoption is an explicit blocker.

### 5.4 Profiles, Base Compatibility, and Rendering

- Publish a strict profile schema with explicit components, unique slot/token IDs,
	bounded selectors, conditions, cardinality, render templates, missing-value and
	stale-label policies. Reject unknown fields/components and unsupported operations.
- Compute component digests over documented canonical bytes and profile digest over
	a canonical manifest containing component names/digests and all executable
	semantics. Exclude only the self-hash and detached attestation. Hash validation
	is integrity, not authorization: approval must identify the trusted release hash.
- Constrain component paths beneath the profile root; reject traversal, absolute
	paths, and escaping links. Make semantic-version parsing strict; declare any
	direct runtime dependency. Load packaged assets through importlib resources.
- Separate template compatibility from data readiness. Compatibility accepts parsed
	base bytes, profile, and selected context; inventories actual pages/cells/markers;
	checks cardinality/duplicates and stale labels. A base hash is never a projection
	hash. Persist results keyed to exact base/profile/context/parser contract.
- Recompute compatibility at approval/generation if any pin differs. Propagate CAS
	failures as conflicts, not successful checks with silently skipped transitions.
- Use one security-reviewed parser boundary for upload, compatibility, generation,
	and postflight. Prefer a hardened parser such as `defusedxml`, added through project
	dependencies; also enforce streaming byte/node/depth/page/cell/attribute/text limits.
	Reject DTD/entities regardless of encoding, unsupported encodings/compression,
	duplicate scoped IDs, and malformed Draw.io graphs with stable error codes.
- Renderer mutates only profile-selected `mxCell.value` fields. Do not resolve
	arbitrary markers in unbound cells; no default allocated identifiers or canonical
	names. Missing facts remain structured gaps; any display placeholder is explicitly
	non-factual. Treat HTML-label insertion separately from XML escaping.
- Independently compare pre/post graph structure, page order, IDs, edges, parent,
	style, geometry, and unbound values. Count changed cells independently from marker
	replacements. Stable mutation identity is page ID + cell ID + operation ordinal.
- Shared status policy distinguishes failure/blockers from permitted gaps and clean
	readiness. A structurally valid file alone is never a successful governed render.

### 5.5 Artifact Finalization and Review

**T1 capture:** authorize and validate mode/context; verify pins; reserve a unique
idempotency key; persist immutable input and RUNNING phase with audit, then commit.
The unique key includes intake/context boundary, mode, projection/base/profile
hashes, generator/policy version. Concurrent identical requests return one run;
an authorized rerun records a reason and a distinct attempt tied to that key.

**Outside transaction:** render exclusively from captured inputs, store staged
content using the existing storage port, and verify actual read-back digests and
sizes. Reuse atomic content-addressed writes, but verify pre-existing deduplicated
objects too. Shared storage may be an approved managed volume; a class name alone
does not establish durability or cross-process availability.

**T2 finalize:** CAS the expected run phase/version, insert the complete unique
artifact set and final status/metrics, and append audit in one transaction. On
failure, write a redacted stable failure code and failing phase in a fresh UoW.
No partial artifact set is downloadable as a completed official result.

**Hash ordering:** create canonical result core and diagram hash first; HTML is
derived only from that core; the final manifest contains the core, diagram hash,
and HTML hash. Store manifest hash externally in artifact metadata, not inside
itself. This avoids a report/manifest mutual-hash cycle. Display/review consume the
same core status; compare all recorded digests against actual bytes.

**Recovery:** a lease/heartbeat or bounded stale-run policy distinguishes active
workers from abandoned work. Retry reuses recorded context/inputs. Reconciliation
finds interrupted runs, missing/corrupt objects, and unreferenced staged content;
retention deletes only unreferenced content after a governed grace period.

**Review:** require completed OFFICIAL_SNAPSHOT mode, authenticated scoped actor,
verified complete artifact bundle, current pin integrity, and exact status agreement.
Missing readiness/hash/manifest/artifact checks fail closed. Blockers are never
approvable. Non-blocking exceptions require non-empty issue-specific rationale
recorded from the trusted actor/time, not supplied reviewer identity. Review and
supersession use CAS plus atomic audit; forbid self-links, cycles, and wrong scope.
Downstream ADS/DDD links the exact approved run and immutable bundle.

### 5.6 Catalog and Deployment Governance

- Compare source and compiled hashes before any idempotent publication return.
	Reconcile compiler/version and persisted contract; serialize concurrent publication.
- Replace implicit startup writes with explicit authorized publish/repair commands,
	dry-run output, full-hash preconditions, and audit. Never backfill a compiled hash
	from source equality alone or rebrand divergent published bytes as the same release.
- D-10 must name actual approvers and the exact artifact/version/full hashes. Where
	the existing version conflicts, choose a new version or a documented reconciliation;
	an agent must not make that business decision.
- Repin only eligible empty draft intakes via CAS and audit after checking answers,
	snapshots, registers, and pending candidate mappings. Answered intakes require an
	explicit migration plan/new revisioned intake; frozen snapshots remain unchanged.
- Implement the enterprise principal-to-capability integration as a prerequisite to
	shared-test deployment; preserve current startup rejection until it exists. Align
	web and domain capability vocabularies. Scope checks and CSRF are additional
	controls, not substitutes for authorization.

## 6. Ordered Implementation Packets

Sizes are relative engineering scope, not calendar estimates. Ownership indicates
implementation boundaries; this review does not launch agents or authorize commits.

| Packet | Scope / Existing Owners | Dependencies | Deterministic Exit Proof |
|---|---|---|---|
| C0 (M) Containment and baseline | P0B/P10: topology routes, security, upload boundary; CI environment owner | None | Deny upload/generate/download/review without the exact capability before any storage or DB side effect; wrong-scope 404; CSRF matrix; Python 3.13 reproducible test environment. |
| C1 (M) Catalog governance | P2A/P2B: publication service, bootstrap, catalog/intake repositories | C0 for admin routes; named D-10 for release selection | Same source/different compiled hash rejected; exact repeat idempotent; startup performs zero writes; repin dry-run/CAS/audit; no frozen mutation. |
| C2 (L) Contract lock | P3/P4/P5A/P6/P8/P9 owners agree snapshot/projection/profile/result contracts | C0 baseline; schema decisions | Shared complete/gapped/conflicting synthetic fixtures travel through real serializers/loaders without adapters mocked out. Explicit enums, hash formulas, scope/identity and lineage requirements signed off. |
| C3 (L) Resource integrity and schema | P5B/P5C + sole migration owner: resource models/repository/service | C2 | Migration-created SQLite and authorized disposable Oracle; lineage survives review; parent/scope/state violations rejected; every head resolves; competing writers have one winner; active exact-scope readiness. |
| C4 (L) Freeze and projection | P3/P4: snapshot service/serializer, answer confirmation/query, projection | C2; C3 for resource integration | Accept -> confirm -> freeze preserves schema/lineage/parents; freeze race aborts fully; unknown/hash/identity mismatch blocks; exact scope and typed CTL-002 selectors; no live answer reads during official projection. |
| C5 (L) Profile and pure renderer | P6/P9: loader, governed profile assets, filler/renderer/report | C2; D-09/D-13 and approved mapping semantics | Real packaged profile + synthetic Draw.io; mandatory/conditional/repeating slots; zero-match/duplicate/unknown selector rejection; security matrix; exact value-only structural diff; shared status and deterministic bundle. |
| C6 (L) Base/run persistence | P7/P8 migration owner: topology models/repository, base service, audit | C2; C3 migration merged; C5 compatibility API | All P7 tests collect against real repository; linear migration chain; reviewed compatibility pins; atomic CAS/audit; legacy rows remain non-authoritative without invented pins. |
| C7 (XL, split) Runtime integration | P8: generation service, input/readiness capture, storage/reconciliation | C4/C5/C6; D-12/D-14 | T1/render/T2 protocol; official no-answer-query tripwire; preview capture stability; idempotent races; corrupt/missing storage; failpoint/restart recovery; no legacy fallback. |
| C8 (L) Review and operator workflow | P10: approval policies/service, routes/templates, downstream run link | C7; D-06/D-07; trusted principal for shared mode | Fail-closed artifact/hash/readiness matrix, gap rationale, concurrent review, self/cyclic/wrong-scope supersession rejected; download rehash; browser journey for preview and official. |
| C9 (L + operations) Certification and activation | P12/P11: release coordinator, platform/data/security owners | C0-C8, named governance approvals | Installed-wheel synthetic vertical slice, SQLite/Oracle migrations, full CI gates, backup/restore/recovery and cross-process storage; then explicitly authorized PERF pilot and post-activation review. |

**Recommended sequence:** begin C0 immediately; develop C1 and C2 concurrently
under distinct ownership. After C2, C3 and C5 can proceed independently, with C4
starting snapshot/selector work and integrating C3 when its API is ready. Serialize
C6's migrations after C3; integrate C7 only after C4/C5/C6 contracts pass. C8's policy
tests may start earlier, but its production integration follows C7. C9's disposable
certification precedes any real PERF data writes. Pilot observation is the final
operational gate, not a substitute for certification.

**C7 split:** C7a captures/persists input, readiness, and idempotency with a renderer
port; C7b adds storage finalization, failpoints, recovery, and actual renderer wiring.
Both serialize edits to the generation service. No packet independently invents a
second run status, profile hash, actor model, or projection format.

## 7. Persistence Migration Plan

One migration owner controls the chain after current `0017`; provisional numbers
below must be rebased onto the current head before implementation.

1. **Next revision: resources.** Resource heads/revisions, scope identity, provenance,
	 current-revision ownership, parent/successor integrity, row versions, and transition
	 events. Integrate model registration into Alembic/runtime metadata explicitly.
2. **Following revision: governance.** Base profile/context pins, compatibility result
	 records, row version/review history; immutable topology inputs; run mode/phase,
	 generator/policy pins, idempotency reservation and metrics; artifact-set uniqueness;
	 reuse the existing append-only audit store where its contract is sufficient.
3. **Legacy handling:** mark old bases/runs LEGACY_UNPINNED or an equivalent explicit
	 authority flag. Keep bytes and historical review metadata; never infer approval,
	 recompute a missing original input hash, or claim a run consumed its snapshot.
4. **Upgrade validation:** fresh database and upgrade from `0015`, `0016`, and `0017`
	 with synthetic historical rows; FK checks; required indexes/constraints; one Alembic
	 head; Oracle identifier budget, CLOB/JSON, timestamp, empty-string/NULL, and cycle-FK
	 behavior. Test through Alembic, not `Table.create()`.
5. **Rollback:** application rollback is gated by schema compatibility and feature
	 flags. Do not drop reviewed revisions/artifacts on downgrade; use backup and a
	 reviewed forward recovery where destructive downgrade would lose audit history.

## 8. Test and Release Gates

Reuse the current test modules for focused cases; add only the missing cross-boundary
integration fixture/journey in the repository's established test directories.

| Gate | Required Proof |
|---|---|
| G-A Contract truth | Corrected P7 collection; R-03/R-05/R-08/R-10/R-11/R-12/R-13/R-15/R-18 probes become regression tests that fail before fixes. Full Python 3.13 dependency set and standard pytest warning configuration work. |
| G-B Canonical lineage | Synthetic candidate and evidence -> accept -> confirm -> resource review -> freeze -> validated projection. Values, raw/normalized identity, schema, author, exact revision, parent and provenance survive. Frozen snapshot bytes never change. |
| G-C Governed rendering | Load actual packaged profile, compatible synthetic base and real projection. Independent graph comparison proves only allowed values changed; required-slot failure blocks; optional gap status agrees in result/HTML/manifest/database. |
| G-D Isolation and races | Cross-app/intake/environment/site, SOURCE/TARGET ambiguity, foreign parents, unknown scope; simultaneous freeze/edit, child-add/retire, review/review, publish/publish, and duplicate generate. Test sessions must overlap, not simulate concurrency by sequential stale arguments only. |
| G-E Security and recovery | UTF-8/UTF-16 declarations, DTD/entities, malformed/compressed input, limits at boundary and +1, duplicate IDs, profile traversal, HTML labels, bounded upload; crashes after each phase; corrupt/dedup/missing artifacts; restore and reconciliation. |
| G-F Delivery | Installed wheel in a clean supported runtime; no source-tree import fallback; exact profile/catalog identities; SQLite and authorized disposable Oracle migration tests; scoped browser flows; project pytest/mypy/Ruff and CI contract checks. |
| G-G Operations | Named D-01 through D-15 decisions where applicable, trusted shared principal, durable storage, credentials handled by operations, read-only applicability/census review, explicit pilot authorization and rollback/retention plan. |

The official-generation tripwire must attach at SQL execution and reject reads
of mutable answer/current-head tables after capture. Do not monkeypatch
`extract_topology_data` or the projection under test. Preview must prove changes
after capture cannot alter output. Fault injection may replace an I/O failure
boundary, but must leave the contract being proved real.

Required project commands after implementation are `python -m pytest tests/ -v`,
`python -m mypy src/migration_intake`, and `python -m ruff check src/` in the
supported isolated environment. Browser/Oracle/recovery/wheel checks remain
separate named gates; skipped external tests are not passes. Never run test or
Alembic commands with a workstation's private database configuration inherited.

## 9. Traceability

| Original Gaps | Primary Completion Packets |
|---|---|
| G-01, G-04, G-05, G-07, G-15 | C2/C4 with C3 |
| G-02, G-09, G-14, G-23, G-27 | C7 with C4/C5/C6 |
| G-03, G-08, G-10, G-12, G-13, G-24, G-26 | C5 with C0/C6/C7 |
| G-06, G-18 | C3/C4; retain P1's non-question candidate boundary |
| G-11 | C5/C9 installed-wheel proof |
| G-16 | Coordinator status updates backed by current results |
| G-17 | Preserve P1; add C4 confirmation/freeze lineage and concurrency proof |
| G-19, G-28 | C1; named D-10 and explicit maintenance |
| G-20 | C0/C8/C9; retain environment/authentication startup guards |
| G-21, G-22, G-25 | C6/C8 with C3 migrations |

Additional R-08/R-22 are owned by C1; R-09/R-10/R-14/R-15 by C3/C4;
R-11/R-12/R-13 by C3; R-03/R-16/R-17/R-18/R-19 by C5;
R-05/R-21 by C8; R-20/R-23 by C7 with C5/C6. C0 closes immediate route/upload
exposure independently of those larger completion packets.

## 10. Executed Evidence and Limits

- Review-start `git status --short --branch`: clean, tracking branch synchronized.
	Baseline commit: `6ed8af2` (`Updating code for topology`).
- Focused tests: **259 passed, 1 collection error**, Python **3.12.7**. Scope:
	`tests/unit/topology`, resource/snapshot service and serializer, resource repository,
	and catalog census tests. The error is `BaseDiagramNotFoundError` import from
	the topology repository. This is a failing slice, not a green release baseline.
- Tests were launched from a fresh temporary working directory with absolute test
	paths, source-only PYTHONPATH, database/runtime environment variables removed,
	and `--continue-on-collection-errors -q --tb=short`. No local `.env` was inspected.
- Python **3.13.13** suite attempt stops on unavailable
	`starlette.exceptions.StarletteDeprecationWarning`. With a process-local
	`-o filterwarnings=default` override, it stops because SQLAlchemy is not installed.
	No dependencies were installed or configuration changed to conceal this.
- Seven synthetic contract probes succeeded in reproducing defects on Python 3.12:
	false render success/pins, false template compatibility, fail-open approval,
	self-supersession, ignored page limit, UTF-16 entity expansion, and wrong snapshot
	ID/SOURCE-to-target projection. Five dependency-free cases were repeated on
	Python 3.13: renderer, approval, supersession, page count, and entity expansion.
- Four disposable in-memory SQLite resource probes reproduced review provenance
	loss, retired-resource COMPLETE status, cross-intake parent acceptance, and
	reparent head/revision divergence with snapshot omission. A fifth database probe
	reproduced same-source/different-compiled-hash publication returning success.
	These are defect reproductions, not fixes or migration certification.
- Alembic ScriptDirectory inspection reports head `0017`; profile inventory returns
	`[]`; AST inspection finds 34 renderer test functions. No migration execution or
	remote database connection was performed.
- No full suite, Oracle, browser, installed-wheel, multi-session race, or live PERF
	certification was executed. No client files, provider calls, runtime changes,
	data writes to configured databases, commits, or pushes are part of this review.

Minimal repeatable dependency-free approval counterexample:

```python
from migration_intake.topology.approval import run_preflight_checks

result = run_preflight_checks({
		"mode": "OFFICIAL_SNAPSHOT",
		"readiness_status": "NOT_READY",
})
assert result.can_approve is True  # Observed defect; desired behavior is False.
```

Minimal renderer counterexample: use a real `Profile` containing one mandatory
slot/token absent from an `mxfile`, pass an unresolved `{{MISSING}}` cell and false
input hashes to `RenderInput`, and call `render_diagram`. Current result is
`success=True`, unresolved markers=1, slots_total=0. Regression fixtures must use
the actual loader and selector contract, not the existing mock profile shape.

## 11. Immediate Handoff

1. Approve C0 containment and designate contract/migration owners; do not activate
	 official generation or make PERF writes based on the existing completion banners.
2. Turn the reproduced defects into focused failing regressions in existing modules;
	 repair C1's publication guard and C2's contracts before wiring the pipeline.
3. Obtain named D-10/D-09/D-13 decisions and D-12 storage approval; do not invent
	 catalog authority, template bindings, parser limits, or allocated resource values.
4. Deliver C3-C8 through the stated gates. Each handoff records owned files, exact
	 contract versions, migrations, commands/results, negative cases and remaining risk.
5. Execute C9 synthetic/disposable certification before the authorized PERF pilot.
	 Completion requires end-to-end proof, not another layer of unconnected helpers.