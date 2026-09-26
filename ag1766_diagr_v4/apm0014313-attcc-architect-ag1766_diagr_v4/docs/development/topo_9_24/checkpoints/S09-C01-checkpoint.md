# Current Checkpoint

- Mode: READ_ONLY_INVESTIGATION; result: COMPLETED.
- Stage/chunk: 09 / S09-C01.
- Last completed chunk: S09-C01.
- Next pending chunk: S09-C02.
- Checkpoint time: 2026-09-24T17:12:28.2247056-05:00.
- Production/reference files modified: No. Database mutations: No.
- Excluded entirely: tests/ and to_archive/.

## Completed Since Previous Checkpoint
- Resource scope hashing preserves UNKNOWN and target resource selection blocks unknown scope
- Interface allowlist carries no environment/site/account/region
- Single-context projection substitutes selection scope as EXPLICIT
- Endpoint nodes key only counterpart ID
- Guide region group is omitted from ProjectedFlow and dedup identity
- Resource provenance lookup uses a nonexistent revision wrapper
- Semantic nodes include all document resources rather than selected sets

## Key Confirmed Findings
See analysis/data_lineage/projection_identity.md and the evidence index. Source-level conclusions are not runtime certification.

## Current Hypotheses and Blockers
- Structural renderer's exact use of nodes/scopes pending S10
- Approved profile mapping from categories to target pages pending S09-C02
- Runtime counterexamples intentionally deferred/permission-gated
- Exact current policy decision resolving guide prose/legend needs plan/decision comparison

## Artifacts Created or Updated
analysis/data_lineage/projection_identity.md, evidence/repository/S09-C01-receipt.json, state/chunks/S09-C01.json, logs and derived state.

## Exact Resume Instructions
Read STATE.json, CHECKPOINT.md, this immutable snapshot, recent WORK_LOG.md, and EVIDENCE_INDEX.md. Validate receipt/artifact existence and source hashes. Execute only S09-C02; do not repeat completed chunks without a freshness failure. Scope exclusions remain mandatory.

## Next Safe Action
Trace approved token/profile mappings from canonical facts to rendering slots
