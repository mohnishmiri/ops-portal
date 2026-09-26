# SL-PROJ-001: Fail Closed On Missing Interface Scope

## Slice Record

| Field | Value |
| --- | --- |
| Slice ID | SL-PROJ-001 |
| Status | NOT_STARTED |
| Priority | P0 / first corrective slice |
| Risk | High behavioral containment; low code breadth |
| Objective | Ensure missing interface environment/site never inherits request selection or becomes EXPLICIT |
| User/operational value | Prevent confidently wrong application topology and cross-context misclassification |
| Approval | Explicit implementation approval required |

## Reason and Current Evidence

F-PROJ-001 proves the current projector reads scope fields absent from the interface capture allowlist. For one selected context it falls back to the requested environment/site and marks the flow EXPLICIT. The active UI supplies hidden PROD/SITE_A. This violates UNKNOWN preservation and can place every interface on an unsupported page/context.

This slice deliberately does not invent the missing canonical scope source. It restores fail-closed behavior before later schema/review/UI work.

## Scope

- Modify `src/migration_intake/topology/strict_projection.py` only for interface flow scope classification/exclusion.
- Add focused characterization/regression checks in a new or existing topology projection test file after implementation scope permits test inspection. Proposed new path: `tests/unit/topology/test_projection_scope_safety.py`.
- Add one route/runner integration check only if the implementation authorization permits tests/: missing scope leads to sanitized conflict and no input/run/artifact persistence.
- Update the current remediation plan/progress evidence after validation.

## Explicit Non-Goals

- No new scope columns/table, importer or workbook change.
- No PROD/SITE_A default, inference from location/migration wave, or page selection redesign.
- No endpoint/category/profile/renderer fix in this slice.
- No official activation, base auto-approval, test-config weakening or historical projection rewrite.
- No Oracle/shared database execution without separate authorization.

## Dependencies and Blockers

- Depends on current default-off containment and strict projection architecture.
- No design decision is needed to remove unsupported inference.
- Later useful preview output is blocked until SL-PROJ-002 defines and persists reviewed interface scope.
- Current review excluded tests/. Implementation approval must explicitly allow inspecting/adding focused synthetic tests; otherwise use an approved standalone probe and leave TDD slice BLOCKED.

## Expected Files

Inspect:

- `src/migration_intake/topology/strict_projection.py`, `_project_semantic_graph`.
- `src/migration_intake/topology/guide_policy.py`, projection allowlist, read-only unless a necessary import/type is identified.
- `src/migration_intake/application/services/topology_runner.py`, blocker propagation, read-only.
- Existing focused test conventions only after authorization.

Modify:

- `src/migration_intake/topology/strict_projection.py`.
- Focused synthetic test/probe file.
- Analysis/progress/canonical plans only at approved slice completion.

## Contract Impacts

- Data/schema: none.
- API: no response schema change; governed preview with interface rows lacking explicit scope returns existing sanitized 409 blocker instead of producing a run.
- UI: no new control; current hardcoded context can no longer manufacture valid flow scope. The eventual UI scope decision is a later slice.
- Security/privacy: no new fields/labels; prevents cross-scope leakage.
- Observability: stable `UNKNOWN_FLOW_SCOPE` exclusion with bounded source locator; no raw interface values.
- Compatibility: newly generated projection bytes/hashes change for affected inputs. Existing stored projections/artifacts remain immutable/readable and are not reinterpreted.

## TDD Sequence

### RED

Proposed test file: `tests/unit/topology/test_projection_scope_safety.py`.

1. `test_single_context_does_not_supply_missing_interface_scope`
   - Synthetic canonical v3 document with one confirmed interface row, valid direction/endpoint/protocol/port, no environment/site, one selected PROD/SITE_A context.
   - Expect no projected flow for that row, one blocking exclusion/issue `UNKNOWN_FLOW_SCOPE`, and no EXPLICIT PROD/SITE_A endpoint scope derived from selection.
   - Must fail before implementation because current code creates an explicit flow.
2. `test_known_interface_scope_must_match_selected_context`
   - Synthetic row with explicit scope keys as accepted by the projector's internal contract.
   - Matching context projects; nonmatching context is excluded by defined policy. If current contract cannot represent known row scope, keep this RED and mark SL-PROJ-002 dependency rather than faking fields.
3. `test_multi_context_missing_scope_is_blocking_once`
   - Two selected contexts, one unscoped source row.
   - Expect one stable source exclusion/issue, no duplicated inferred flows.
4. `test_unknown_scope_does_not_create_endpoint_node`
   - Ensure excluded flow leaves no counterpart endpoint node.

Optional authorized integration RED:

- POST governed preview with synthetic approved base and unscoped interface authority returns 409, commits capture if that is the approved existing boundary, but commits no topology input/run/artifacts. Pin expected transaction behavior explicitly before implementation.

### GREEN

Smallest implementation:

1. Read interface environment/site without fallback to application/request scope.
2. If either required dimension is absent, append one blocking `UNKNOWN_FLOW_SCOPE` exclusion carrying source provenance and continue before node/flow creation.
3. For explicit source scope, create ProjectedScope from source values only and validate against selected contexts according to the current approved policy.
4. Do not alter resource scope behavior, flow direction normalization or profile/rendering.

### REFACTOR

- If clarity requires it, extract a pure `_project_interface_scope` helper returning explicit scope or exclusion. Do not create a broad new abstraction.
- Use existing types/stable issue ordering; no unrelated formatting or model changes.
- Re-run focused synthetic check, changed-file Ruff/mypy and any authorized route check.

## Negative and Failure Checks

- Missing environment only; missing site only; blank strings; malformed non-string values.
- One unscoped row among valid rows: valid facts remain; one row blocks according to approved all-or-nothing runner policy.
- Bidirectional unscoped row creates no pair of inferred flows/nodes.
- Sensitive contact/notes never appear in issue text.
- Existing immutable stored projection is untouched.

## Acceptance Criteria

1. No code path copies selected context into absent interface source scope.
2. Missing mandatory scope has typed state/exclusion and blocks runner before reservation/render.
3. No endpoint node/flow is created for excluded unscoped interface.
4. Output/exclusion ordering and hashes are deterministic.
5. Existing known resource scope/global behavior is unchanged.
6. Official and legacy mutation gates remain disabled.
7. New focused RED demonstrates pre-change defect; GREEN passes without weakening assertions/config.

## Proposed Gating Commands

Exact commands must use the repository's selected Python 3.13 environment and authorized test scope. Proposed:

```powershell
.venv\Scripts\python.exe -m pytest -q tests/unit/topology/test_projection_scope_safety.py
.venv\Scripts\python.exe -m ruff check src/migration_intake/topology/strict_projection.py
.venv\Scripts\python.exe -m mypy src/migration_intake/topology/strict_projection.py
git diff --check
```

Do not run these under the current read-only review or use root `.env`/existing databases.

## Certification

- Database/schema: NOT_APPLICABLE, no schema change.
- API: sanitized existing conflict contract, if authorized integration evidence is available.
- UI: current page remains truthful that generation cannot complete; no new UI behavior claimed.
- Diagram/topology: semantic node/flow/exclusion assertion; no visual output should be produced for unsupported scope.
- Performance: NOT_APPLICABLE beyond bounded linear row processing; no benchmark required.
- Security: verify issue output contains bounded IDs/codes, not raw sensitive fields.
- Compatibility: compare unaffected known-scope fixtures and preserve historical bytes without mutation.

## Rollback

Revert this production/test slice only. Keep official/default-off containment. Rollback reintroduces unsafe scope inference and therefore must not be used to activate generation; if later scope work is blocked, leave this containment fix active.

## Evidence To Attach

- RED failure and GREEN focused output with interpreter/commit/source hashes.
- Synthetic input and normalized projection/exclusion JSON, with no client data.
- Changed-file diagnostics, Ruff/mypy and diff check.
- Route transaction evidence if the optional integration check is authorized.
- Final diff summary and updated finding disposition.

## Definition of Done

- All acceptance criteria pass in an authorized synthetic environment.
- No unrelated source/test/document churn.
- F-PROJ-001 is narrowed from "invented scope" to "correctly blocked missing scope"; useful scoped generation remains explicitly pending SL-PROJ-002.
- Completion record includes files, commands, results, evidence IDs, commit if later committed, and next slice.
- User reviews evidence and decides whether to approve SL-PROJ-002. No automatic commit/push/activation.

## Completion Record Placeholder

```yaml
slice_id: SL-PROJ-001
status: NOT_STARTED
started_at: null
completed_at: null
commit: null
files_changed: []
commands: []
evidence: []
blockers: []
notes: []
```

## Agent Execution Prompt

```text
Implement only SL-PROJ-001 from docs/development/topo_9_24/analysis/remediation_options/first_slice.md after explicit user approval.

Resume from the investigation STATE.json and current Git state. Preserve all user changes. Never inspect or use to_archive/. Inspect tests/ only if the implementation approval explicitly lifts the review exclusion for the focused synthetic files needed by this slice.

First write the RED characterization proving that a single selected context currently supplies missing interface scope as EXPLICIT. Persist the failure. Then make the smallest change in strict_projection.py so missing interface scope produces one blocking UNKNOWN_FLOW_SCOPE exclusion and no endpoint/flow. Do not add schema, mappings, defaults, route/UI changes or unrelated refactors.

Run only the approved focused checks, persist outputs and source hashes, review the diff, and stop at the SL-PROJ-001 completion gate. Do not commit, push, activate generation or begin SL-PROJ-002 without explicit approval.
```