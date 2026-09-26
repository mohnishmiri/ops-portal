# SL-PROJ-002: Reviewed Interface Scope Authority

## Record

- ID: SL-PROJ-002
- Status: NOT_STARTED
- Priority: P0
- Risk: High, additive schema plus canonical authority contract
- Objective: provide explicit reviewed environment/site/account/region states for each interface without changing workbook/import correctness.
- Value: enables truthful multi-context topology and removes request-context inference.
- Reason/evidence: F-PROJ-001; EV-PROJ-001; current interface model has no required topology scope fields.

## Scope and Non-Goals

Scope: add an append-only `InterfaceScopeDecision` authority, repository/service command, current-decision pointer, interface-epoch fencing and capture allowlist fields. Non-goals: no workbook/importer change, no automatic scope inference, no topology rendering/profile/UI activation, no migration of UNKNOWN to a concrete value, no private data fixture.

Dependencies: SL-PROJ-001 complete; architect approves required dimensions and state vocabulary. Blockers: exact source/reviewer workflow and existing-data preflight; migration number/head must be rechecked at execution time.

## Expected Files

- Inspect: interface model/repository/service and latest Alembic head; actor/audit conventions; topology contracts.
- Modify/add: proposed `models_interface_scope.py`, `repositories/interface_scope.py`, `application/services/interface_scope.py`, next additive migration, Alembic model registration, `models_interfaces.py` pointer, `interfaces.py` capture read, topology contract types, focused synthetic tests, docs.
- Avoid modifying importers unless later evidence proves an approved direct mapping; this slice uses explicit review decisions.

## Data and Schema

Proposed append-only table fields: decision UUID, interface record/application IDs, environment/site/account/region state+value, provenance references, rationale, actor, timestamp, canonical decision hash and optional superseded-decision ID. Add nullable `interfaces.topology_scope_decision_id` FK/pointer for historical rows. Enforce state/value consistency and actor/interface FKs where portable. Pointer update uses expected interface row version and advances application interface epoch in the same transaction. No cascade deletion of decisions.

Existing interfaces remain valid with null pointer = UNKNOWN/unreviewed. Do not backfill guesses.

## API, UI, Security and Observability

- API/application command accepts typed states/values, rationale, provenance and expected row version; no public topology route in this slice.
- UI change: none; later interface-review UI may call the command.
- Security: require the existing authorized interface-review capability; scope command by application/interface; exclude contacts/notes; audit actor/rationale.
- Observability: stable decision-created/CAS-conflict events with IDs/state dimensions only, no raw sensitive fields.

## Implementation Steps

1. Ratify `KNOWN`, `GLOBAL`, `UNKNOWN`, `NOT_APPLICABLE` validity by dimension; environment/site required for non-global topology contexts, account/region optional but stateful.
2. RED schema/repository/service/capture checks.
3. Add model/migration and metadata registration; run preflight before constraints.
4. Implement append decision + conditional pointer update + epoch bump under one UoW.
5. Extend capture projection rows with decision ID/hash and typed scope values/states; null pointer emits UNKNOWN states.
6. Validate canonical v3 shape/hash and mutation rollback.
7. Update documentation/evidence; stop before projector v2.

## TDD

RED proposed files: `tests/unit/application/test_interface_scope_service.py`, `tests/unit/persistence/test_interface_scope_repository.py`, `tests/integration/migrations/test_interface_scope_upgrade.py`, and focused capture contract checks. They must fail because no model/command/pointer exists.

GREEN: smallest table/pointer/service/repository/capture implementation. REFACTOR: share existing ScopeState validation only; do not generalize unrelated registers.

Unit cases: state/value matrix, canonical decision hash, permission/scope/rationale, stale row version, supersession pointer, null decision -> UNKNOWN. Integration/contract: FK/CHECK/unique constraints, rollback leaves decision pointer/epoch unchanged, exact current decision captured, Oracle/SQLite type parity when separately authorized. E2E: deferred to interface-review UI and SL-CERT-002.

Fixtures: synthetic UUIDs/application/interface/actors only. Negative: cross-application interface, missing rationale/provenance, KNOWN with blank value, UNKNOWN with supplied value, deleted/mismatched decision, stale CAS, duplicate request.

## Acceptance

1. Every captured interface has explicit scope states and decision lineage; no request context appears as source authority.
2. Missing decision remains UNKNOWN and is not approved automatically.
3. One successful decision advances pointer, row version and interface epoch exactly once; stale writer loses with no partial row/pointer effect.
4. Historical decisions remain queryable and immutable through application API.
5. Fresh/representative migration succeeds only after violations are dispositioned; FK check clean.
6. No importer, renderer, route activation or client evidence change.

## Proposed Gates

```powershell
.venv\Scripts\python.exe -m pytest -q <approved focused scope decision and migration files>
.venv\Scripts\python.exe -m ruff check <changed src files>
.venv\Scripts\python.exe -m mypy <changed src files>
git diff --check
```

Database certification: clean and populated disposable SQLite; Oracle only under separate authorization. API certification: application command contract only. UI/diagram/performance: NOT_APPLICABLE in this slice. Security: capability/scope/CSRF if later routed, no sensitive payload logging. Compatibility: null pointer preserves old rows as UNKNOWN; old immutable snapshots remain unchanged/readable.

## Rollback and Documentation

Before use, rollback may drop additive pointer/table using migration downgrade if repository policy permits. After authority rows are used, prefer forward disable/reader compatibility rather than deleting history. Update schema map, projection decision ADR, user-facing scope semantics and progress ledger.

Evidence: migration SQL/metadata diff, preflight counts, synthetic decision/capture JSON+hash, CAS interleaving result, SQLite/authorized Oracle receipts, diagnostics. Definition of done: all acceptance gates pass, no guessed backfill, SL-PROJ-003 receives a frozen typed input contract, user approves continuation.

Completion placeholder:

```yaml
slice_id: SL-PROJ-002
status: NOT_STARTED
started_at: null
completed_at: null
commit: null
files_changed: []
commands: []
evidence: []
blockers: []
```

## Agent Prompt

```text
After explicit approval, implement only SL-PROJ-002. Resume from topology_review_workspace STATE.json and current Git state. Verify the latest migration head and existing user changes. Write RED synthetic model/repository/service/capture checks first. Add an append-only reviewed interface-scope decision and nullable current pointer; never infer/backfill concrete values. Update pointer, row version and interface epoch under one CAS/UoW. Extend capture with typed states/decision provenance only. Run approved focused checks in disposable databases, persist evidence, review migration/diff and stop. Do not modify importers, projector rendering, routes, tests outside approved focus, feature flags, or commit/push automatically.
```