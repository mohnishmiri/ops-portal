# SL-PROJ-003: Scoped Topology Projection v2

## Record

- ID/status: SL-PROJ-003 / NOT_STARTED
- Priority/risk: P0 / Critical contract migration
- Objective: persist one deterministic projection containing explicit scope, guide category, canonical endpoint identity, selected resources and provenance.
- Value/reason: enables the application target and removes F-PROJ-002/003/004 and F-PROV-001 after SL-PROJ-001/002.

## Scope, Non-Goals, Dependencies

Scope: introduce projection schema 2.0.0, strict typed records/loader/serializer, approved policy category mapping, runner input identity/version pin and dual historical reader. Non-goals: no profile/render/UI/schema graph tables; no reinterpretation of v1; no live AWS/Azure discovery; no arbitrary labels.

Dependencies: SL-PROJ-001 and SL-PROJ-002 complete with approved scope decision contract. Blockers: resolve current guide inbound/IN-OUT policy from existing approved decision or explicit user decision; ratify category aliases including Midrange/Hybrid/Private/Conexus/OnPrem.

## Expected Files and Contracts

- Inspect/modify: `strict_projection.py`, `scope.py`, `guide_policy.py`, topology contracts, runner/input identity, status/report manifest contracts and focused synthetic tests.
- Data/schema: projection JSON/hash remains in `topo_inputs`; add an explicit projection schema/version relational pin only if preflight shows it is needed for efficient gating. No graph tables.
- API/UI: no route change; newly requested previews use v2 and may block on unresolved policy/scope. Historical v1 display remains read-only.
- Security: strict field/label allowlist, provenance locators only, no contact/notes.
- Observability: version/hash, node/flow/exclusion counts and stable blocker codes.

## Projection v2 Identity

- Endpoint key: namespace + stable counterpart ID + explicit environment/site/account/region state/value.
- Flow key: scoped source/target keys + direction + typed relationship + protocol + port + approved guide category/region.
- Node/flow provenance: exact captured record/revision/provenance references.
- Semantic resources: only selected TARGET plus approved global/shared and explicitly modeled SOURCE resources; no unfiltered document loop.
- Application anchors: explicit per-context/page role, not one ambiguous multi-context node.
- UNKNOWN/CONFLICT: typed blocking exclusions; never selection fallback.

## Implementation Steps

1. Freeze v2 JSON schema and enums with exact field sets.
2. RED synthetic identity/scope/category/provenance/deep-loader checks.
3. Refactor projector to build selected semantic sets first, then nodes/flows/endpoints.
4. Include category and scope in identity/dedup; union provenance only for exact duplicates.
5. Fix top-level resource provenance consumption.
6. Add v1 historical loader and v2 new-generation gate; persist version in semantic input/manifest/report.
7. Update runner/profile compatibility input and docs; no renderer changes.

## TDD

RED proposed files: focused projection-v2 unit/contract tests after implementation permission. Cases: same endpoint across two contexts remains two nodes; AWS/Azure/internal same tuple remains distinct; missing scope/category blocks; known nonselected scope excluded; top-level resource provenance retained; off-context resource absent; exact duplicate unions provenance; bidirectional yields two flows; deep loader rejects duplicate nodes/dangling endpoints/invalid enum/identity hash.

GREEN: minimum new dataclasses/schema serializer/projector path. REFACTOR: common canonical identity helpers only after RED/GREEN; do not retain fallback branches.

Integration: runner persists/reloads identical v2 bytes/hash and semantic input hash changes with category/scope. E2E deferred to profile/renderer. Fixtures synthetic C00-C12 plus cross-scope/category/provenance cases. Negative tests include malformed scope state/value, duplicate output keys, conflicts, sensitive label attempt and v1 passed to v2 official gate.

## Acceptance and Gates

1. Every endpoint/flow identity is scope/category complete or excluded.
2. No request selection appears as source scope.
3. Nodes exactly cover selected/shared policy; all flow endpoints exist.
4. Provenance survives capture -> projection JSON -> reload.
5. Same input/policy/time produces deterministic canonical bytes/hash; operational timestamp excluded or pinned.
6. v1 remains readable but cannot be approved/generated as v2.
7. Focused tests, changed-file Ruff/mypy and diff check pass in authorized environment.

Proposed commands follow selected Python 3.13 and focused files only. Database gate: optional schema pin migration only if approved; otherwise persistence round-trip. API/UI/diagram: no activation; projector counts/semantic JSON are certification evidence. Performance: 5,000 flows remains O(n log n), benchmark later. Security: sensitive fields absent. Compatibility: profile compatibility explicitly names projection schema 2.0.0.

## Rollback, Docs, Evidence, Done

Rollback disables v2 new generation while preserving v2 rows/readers; never rewrite them as v1. Update schema/ADR/policy/profile compatibility docs. Attach RED/GREEN output, canonical fixtures/hashes/diffs, provenance/identity matrix, diagnostics and performance sample.

Done when v2 contract is approved, all semantics pass, no fallback remains, existing history is preserved and SL-PROFILE-001 can target stable selectors. No commit/push/next slice automatically.

Completion placeholder:

```yaml
slice_id: SL-PROJ-003
status: NOT_STARTED
commit: null
files_changed: []
commands: []
evidence: []
blockers: [SL-PROJ-002, direction-policy-decision]
```

## Agent Prompt

```text
After explicit approval and completion of SL-PROJ-001/002, implement only SL-PROJ-003. Start with RED synthetic v2 identity/deep-loader cases. Add projection 2.0.0 with scoped endpoint and flow identities, approved guide category, selected resource sets and preserved provenance. Never infer scope/category, edit importers, add graph tables, change renderer/UI, relabel v1, or activate generation. Persist focused evidence and stop for review without commit/push or starting the profile slice.
```