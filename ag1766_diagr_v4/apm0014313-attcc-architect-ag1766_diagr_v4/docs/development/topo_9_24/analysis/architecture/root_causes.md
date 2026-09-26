# Root-Cause Synthesis

EV-ROOT-001; S14-C01. Synthesized from 40 persisted findings: four Critical, 25 High (including one hypothesis), nine Medium and two Low. No new source search or runtime execution.

## RC-01: Semantics Are Recreated Differently At Each Boundary

The intended chain is reviewed fact -> immutable authority -> typed projection -> profile region -> renderer mutation -> verified artifact. Instead, each layer carries a different subset:

- Capture excludes interface scope dimensions needed later.
- Projection substitutes request scope, drops guide category and resource provenance, and weakens endpoint identity.
- Profile mappings cover only application name; no production target profile exists.
- Renderer hashes a different subset again and omits styles/prototypes/page identity.

Consequences: F-PROJ-001..004, F-PROV-001, F-PROFILE-001/002, F-RENDER-001/002/004. This is the primary reason the pipeline cannot reproduce the two-page target safely.

```mermaid
flowchart LR
  Facts[Reviewed scoped facts] -->|scope/category omitted| Capture[Immutable capture]
  Capture -->|fallback/drop| Projection[Typed projection]
  Projection -->|no production mapping| Profile[Synthetic profile]
  Profile -->|prototype ignored / weak IDs| Renderer[Generated XML]
  Renderer --> Output[Visually plausible but ungrounded output risk]
```

Root fix: define one typed semantic identity/provenance contract and preserve it unchanged through every boundary. Request selection filters; it never supplies missing evidence.

## RC-02: Legacy And Governed Paths Coexist Without One Facade

The route module injects both legacy and governed services. Upload uses legacy base persistence; preview requires governed approval pins with no web transition. Approval uses legacy review while a stronger governed review service sits unused. Artifact delivery chooses inconsistent services by mode.

Consequences: F-UI-001, F-AUTH-003, F-API-001, F-UI-003. A feature flag can expose the wrong service rather than activate a complete governed facade.

Root fix: one topology application facade owns upload/governance/generation/inspection/review commands. Legacy rows may remain readable but cannot be a mutation fallback.

## RC-03: The Application-Specific Target Is Not An Executable Contract

The guide and expected output now define meaningful application requirements, but packaged profiles are synthetic. The guide mixes standard content, category-driven flows and application-derived lists, with unresolved direction/conditional details. No profile binds this exact input/target to two page-qualified regions/prototypes.

Consequences: F-RULE-001, F-PROFILE-001..003, F-PIPE-001, F-UI-002. Structural code can pass synthetic contracts while being incapable of the actual deliverable.

Root fix: create a reviewed, versioned production profile/policy package from the supplied artifacts, after semantic projection repairs. Keep application-specific expected output separate from universal template rules.

## RC-04: Relational Integrity Stops Before The Audit Chain

The schema has useful FKs/unique keys, but the most important cross-row/conditional invariants are service-only: run-to-input, mode-to-authority, review targets, current revision ownership and same-scope endpoints. Append-only intent is mostly repository convention.

Consequences: F-DATA-001/002/003/005, F-AUTH-002. Services compensate with late fail-closed checks, making corrupt states representable and recovery/UI more complex.

Root fix: add constraints only after data preflight and portability design, focusing on immutable authority/current-revision ownership and explicit typed references. Keep service checks as defense in depth.

## RC-05: Concurrency Concepts Are Split Across Incompatible Mechanisms

Most phase changes use rowcount-checked conditional UPDATE. Final completion uses select then ORM mutation. Interface edits increment a version but do not compare it. Reparent creates a revision but fails to atomically update head parent. Recovery confuses semantic rerun attempt with worker-recovery attempts.

Consequences: F-DATA-004/006, F-PIPE-002, F-REC-001 and H-PIPE-001. Correct behavior depends on which method is called rather than one state-machine protocol.

Root fix: specify explicit transition predicates and atomic effects for every state change; implement all through conditional DML or equivalent database-guaranteed fencing. Model reservation attempt and recovery attempt separately.

## RC-06: UI Truth Is Derived From Rows, Not Verified Domain State

Run detail treats three artifact rows as receipt-verified readiness, but links are individually enabled and bytes are verified only later. Preview authority text says current intake data, and typed delivery failures lack HTTP mapping. Recovery diagnostics similarly infer visibility from lease presence.

Consequences: F-UI-003, F-API-001, F-REC-002, F-OBS-002. The UI can be internally contradictory even when backend validators fail closed.

Root fix: one verified read model computes authority, bundle integrity, inspection eligibility, review eligibility and retry state. UI text/controls and server enforcement consume the same result.

## RC-07: Completion Evidence Is Not Bound To Current Invariants

The plans preserve extensive historical test counts, but current source contradicts several completion claims. HTML/Markdown ledgers disagree. Runtime evidence is permission-blocked in this review, and tests are user-excluded. Configuration/version/setup documentation also drifts.

Consequences: F-DOC-001..004. Teams can select TP15/broad quality work while owning functional invariants are already broken.

Root fix: every slice completion record names invariant-level evidence tied to source/commit/artifact hashes and a real supported journey. A later counterexample automatically reopens or creates a blocking corrective slice; HTML is generated from the approved source.

## Causal Chains To Prioritize

### Target Fidelity

Guide categories/scope -> capture omits scope -> projection invents scope/drops category -> no production profile -> renderer ignores prototypes/page identity -> target cannot be certified.

### Approval Integrity

Immutable snapshot intent -> input authority weakly constrained -> review omits projection/source validation -> HTTP route bypasses review service -> flag activation can approve unproven output.

### Failure/Recovery Truth

Renderer/finalizer detects invalid output -> explicit failure stays STORING -> expired lease can be reclaimed indefinitely -> diagnostic inventory hides lease-free terminal states -> UI rows/links do not represent verified state.

## What Is Not A Root Cause

- Intake/XLSX parsing: user accepts it as working and excludes it; topology consumption is the issue.
- Need for a graph database, queue or microservice: current scale/requirements do not justify these additions.
- Absence of Lean proofs: executable state/integration evidence is the immediate gap. A bounded TLA+ model may later strengthen the lease/reservation/finalization protocol.
- A single isolated typo such as readiness `literal`: fix it, but it does not explain topology fidelity failures.

## Remediation Ownership Order

1. Canonical scope/category/identity/provenance projection contract.
2. Production target profile and prototype/page-qualified renderer.
3. Atomic finalization/recovery and schema authority constraints.
4. Governed application facade for base workflow, inspection and review.
5. Verified read model/UI and standalone real journey.
6. Documentation/certification regeneration and only then official activation consideration.

This ordering prevents UI/profile work from compensating for missing semantic authority and prevents activation from exposing legacy bypasses.