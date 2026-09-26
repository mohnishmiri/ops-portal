# Governed Topology Schema Contract

EV-DATA-001; S08-C01. Static inspection of `models_topology.py` and migrations 0014, 0015, 0020 and 0021. No database connection, migration execution, schema reflection or excluded-suite inspection. "Present" means declared in both the inspected migration chain and current ORM, not observed in a deployed database.

## Evolution

1. Migration 0014 creates legacy `topo_base`, `gen_runs` and `gen_artifacts`.
2. Migration 0015 makes run snapshot/catalog pins nullable for historical draft generation. This is retained compatibility, not authority for official mutable generation.
3. Migration 0020 adds base/run governance columns, artifact-type uniqueness, and creates compatibility, capture, immutable input, reservation and review tables. Existing rows default to `LEGACY_UNPINNED`/`HISTORICAL` as applicable.
4. Migration 0021 adds intake content epoch, input compatibility pins/FK, run rerun reason, and unique run-attempt identity after rejecting existing duplicate identity groups.

Current ORM shape matches the inspected migration progression for these topology fields and named constraints. Deployed SQLite/Oracle parity is not claimed in this static chunk.

## Table Map

| Table | Purpose / principal writers and readers | Verified keys and constraints | Static risks / lifecycle notes |
| --- | --- | --- | --- |
| `topo_base` | Stored base diagram metadata; upload/base-governance services write; runner/landing/review read | PK id; FKs application, intake, upload actor; indexes intake/hash | Compatibility/reviewer references are not FKs. State/lifecycle/capability vocabularies and positive row version/size are service-only. Legacy rows intentionally unpinned/historical. |
| `gen_runs` | Operational run, phase, lease, result/review summary; runner/recovery/review/UI read/write | PK id; FKs application/intake/snapshot/base/request/approval/supersession; unique intake+semantic hash+attempt; indexes intake/status/input | `input_id` has an index but no FK. Nullable governance fields support legacy rows; no conditional constraints distinguish governed from legacy or phase/status/lease combinations. |
| `gen_artifacts` | Diagram/report/manifest receipt metadata; finalizer writes; delivery/review reads | PK id; FK run; unique run+artifact type; indexes run/type | Database prevents duplicate type for a run but does not require exactly one complete three-artifact bundle or constrain artifact vocabulary/positive size. Blob lifecycle is external. |
| `topo_compat` | Immutable compatibility result/pins for stored base/profile/selection/capability | PK id; FKs base/check actor; globally unique compatibility key; base index | JSON/hash semantic agreement and capability vocabulary require application validation. |
| `topo_captures` | Immutable preview authority bytes/hash at intake content epoch | PK id; FKs intake/capture actor; intake index | No uniqueness on intake+epoch+hash, which may be intentional to retain repeated captures. Exact-byte/hash/schema agreement remains service-enforced. |
| `topo_inputs` | Persisted projection plus all semantic/policy/base/authority pins | PK id; FKs application/intake/base/snapshot/capture/capture actor/compatibility; unique intake+semantic input hash; intake index | No CHECK enforces mode/authority: snapshot and capture are independently nullable, so both/neither and mode mismatch are structurally possible. Cross-row application/intake ownership is not composite-enforced. |
| `gen_keys` | One semantic reservation per intake pointing to a run | PK id; FKs intake/run; unique intake+semantic input hash; run index | Database supports duplicate-request serialization; semantic hash correctness and reservation/run identity agreement are application-owned. |
| `topo_reviews` | Append-oriented review/supersession evidence for run/base entities | PK id; entity index only | No FKs for actor, run or base; no target/cardinality CHECK; database does not enforce append-only mutation. Polymorphic entity ID may preclude one FK, but explicit typed columns can still be constrained. |

Expected cardinalities and retention periods are UNKNOWN from these five files. Do not invent production volumes or deletion policy.

## F-DATA-001: Governed Run Input Reference Is Not Referentially Enforced

- FACT / VERIFIED static; severity High.
- `GenerationRun.input_id` exists and is indexed. Neither the ORM table arguments nor migration 0020/0021 creates an FK to `topo_inputs.id`.
- The runner/review code expects a persisted input; prior source trace shows missing input blocks later operations, but service checks do not prevent an orphan row from existing.
- Impact: deleted/mistyped/migrated input IDs can leave runs that cannot render, recover, review or establish authority. Database foreign-key checks cannot detect this relationship.
- Proposed change: after auditing/backfilling governed rows, add a named nullable FK for legacy compatibility; require non-null input for governed modes through a conditional constraint or migration policy. Consider deletion behavior explicitly; do not cascade immutable authority away silently.
- Alternative: retain service-only validation for portability, accepting weaker integrity. This is not preferred for an immutable audit chain.
- Acceptance proposal: clean and representative upgrades reject orphan governed input IDs, permit documented legacy nulls, and preserve Oracle/SQLite behavior. No migration is authorized in this review.

## F-DATA-002: Input Authority Cardinality and Mode Are Not Enforced

- FACT / VERIFIED static; severity High for future official activation.
- `topo_inputs.mode` is non-null; `snapshot_id` and `capture_id` are independently nullable FKs. No CHECK enforces exactly one or associates it with OFFICIAL_SNAPSHOT versus DRAFT_PREVIEW.
- Impact: a row can structurally have both authorities, neither authority, or a mode/authority mismatch. Hash-valid projection data alone then cannot establish the intended source authority.
- Proposed change: define the supported modes and add a portable conditional invariant after existing-data audit, or use separate typed tables if Oracle/SQLite CHECK portability cannot express it cleanly. Keep service validation as defense in depth.
- Acceptance proposal: official requires snapshot and forbids capture; preview requires capture and forbids snapshot; unsupported modes fail; existing legacy records are explicitly outside `topo_inputs` or migrated/dispositioned.

## F-DATA-003: Review Audit References Are Weakly Linked

- FACT / VERIFIED static; severity Medium.
- `topo_reviews.actor_id`, `run_id`, and `base_artifact_id` have no FKs in migration or ORM. `topo_base.reviewed_by_id` and compatibility_id also lack FKs. `entity_type/entity_id` has only an index and no target/cardinality CHECK.
- Impact: orphan actor/target/reviewer identifiers and contradictory typed/polymorphic target columns are structurally possible, weakening audit lineage and validation queries.
- Trade-off: polymorphic entity references are difficult to FK directly and cyclic base/compatibility references need careful DDL ordering. Those concerns do not explain every unconstrained explicit typed reference.
- Proposed change: add FKs for explicit actor/run/base references where migration portability permits, and enforce one valid review target/type combination. Preserve review rows and use restrictive deletion or durable actor-history strategy rather than cascade loss.

## Other Static Observations

- No inspected topology table declares CHECK constraints for enum-like states, positive sizes/versions/attempts, terminal timestamps, lease-phase consistency or result status. Application CAS methods remain necessary but are not a substitute for all row invariants.
- Artifact uniqueness is strong for one row per type/run, but completeness is a service/review invariant.
- The unique reservation and run-attempt keys support deterministic duplicate handling at the database boundary. They do not prove finalization fencing or recovery-attempt accounting.
- Migration 0021 correctly checks duplicate attempt groups before adding its unique constraint. Runtime/deployed data and rollback behavior remain unverified.
- Migration 0020 contains Oracle-specific column/index handling. Portability claims require S08-C03 source review and separately authorized disposable execution, not inference from branches.

## Validation Queries To Adapt After Authorization

These are proposed checks using verified names, not executed SQL:

- Governed runs whose non-null `input_id` has no `topo_inputs` row.
- Inputs where authority count is not one, or mode disagrees with snapshot/capture presence.
- Reviews with missing actor/run/base targets or contradictory target columns/entity type.
- Completed runs missing one of DIAGRAM/GAP_REPORT/MANIFEST, duplicate types, or manifest hash.
- Nonterminal/terminal phase-status combinations with inconsistent leases/timestamps.
- Duplicate run-attempt/reservation identities and inputs whose pinned application/intake differ from referenced base/authority rows.

Any validation must use a disposable/safely authorized environment; do not query the existing database during this read-only investigation.