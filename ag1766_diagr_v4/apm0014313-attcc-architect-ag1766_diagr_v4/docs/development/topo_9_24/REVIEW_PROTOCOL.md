# Reconciled Topology Review Protocol

## Objective and Authority

Perform an evidence-based architecture, engineering, and test review of the current topology-generation workflow. Produce a target design and an agent-executable, phased remediation plan. This is an investigation, not implementation approval.

The user's selected analysis root is `docs/development/topo_9_24/`. It replaces the earlier proposed nested `topology_review_workspace/` path. All generated artifacts stay under this root. Existing source documents and project plans are read-only; proposed amendments are drafted here, not published over canonical documents.

Exclude the repository-root `to_archive/` and `tests/` directories entirely. Every recursive search, inventory, extraction, and comparison must enforce both exclusions. Do not follow references into them or use their contents as evidence. Do not execute the excluded suite or import its fixtures/helpers. References to tests in production/configuration/documents do not establish coverage and must not be followed into the excluded directory. Do not inspect `.env` values, credentials, private connection strings, or unrelated user changes.

Follow repository instructions and the current primary plan. The application is an intake-evidence-to-Draw.io generator. Do not assume live AWS collection, cloud discovery infrastructure, or an interactive graph canvas exists or is required. Mark unsupported review dimensions NOT_APPLICABLE with reasons instead of inventing missing requirements.

Candidates are not approved facts. Preserve UNKNOWN, scope, provenance, and conflicting evidence. Distinguish immutable non-authoritative preview capture from approved snapshot authority for official output. Keep official generation and approval disabled.

## Inputs

Verify the supplied input Draw.io, user-confirmed application-specific expected-output Draw.io, and guide listed in README. Also inspect the assessment, active Markdown implementation plan, and its HTML reading copy. D-009 confirms the two-page output as the expected target for this particular migrating application, not a universal layout. Record per-page context/rule uncertainties without inventing values. D-010 excludes intake/XLSX and importer-correctness analysis; accept intake as working for this review and do not request a workbook. Topology consumption of existing reviewed canonical data remains in scope.

Treat all document claims as claims to verify. The two guide copies have matching initialization hashes; this establishes byte equality, not correctness. Earlier review notes can prioritize investigation but cannot substitute for current, persisted proof.

## Permissions and Stop Conditions

- Allowed: scoped repository reads, source/reference hashing, local safe document parsing, and new sanitized review artifacts inside the analysis root.
- Not authorized: production edits, existing-test edits, existing-database mutation, cloud calls, deployment, merge resolution, installing dependencies, Git commits/pushes, or external transmission of evidence.
- Before any runtime verification, approve an explicit standalone isolated environment independent of `tests/`: synthetic inputs only, no inherited database/cloud/LLM credentials, no root `.env`, and output/caches confined to this workspace. Disposable probe writes are not permission to modify an existing database. Do not use the excluded suite to establish a baseline.
- Existing/shared Oracle databases, production-like services, credentials, or actions outside this boundary require explicit user approval.
- Unexpected changes affecting the baseline require a checkpoint and user direction. The initial unmerged `src/migration_intake/web/health.py` was resolved by the user and verified in EV-REPO-003; the earlier broad-review pause is lifted. New source changes require freshness checks, not automatic resets.
- Normally, checkpoint initialization as its own operation, then continue routine authorized read-only chunks automatically. Stop at permission gates, unresolved errors, or resource limits. Do not request approval after every routine chunk.
- Existing-test inventory, execution, coverage assessment, and suite certification are outside the user-authorized review scope. Document this limitation, not a passing gate. Testing requirements in the future remediation plan are proposals, with exact existing test locations unverified.
- Do not resolve pre-existing lint/type failures or inspect excluded tests during this review.

## Chunk Contract

Each chunk has a stable ID, one objective, declared inputs, expected outputs, completion condition, evidence paths, result, and exact next action. Inspect at most five closely related source files, one document section/worksheet, one diagram category, one runtime segment, or one report section. Split larger work before continuing.

For every chunk:

1. Resume from validated state, checkpoint, recent logs, and evidence. Check source freshness; never restart completed work without a reason.
2. Announce objective, read-only status, inputs, planned operations, outputs, and completion condition.
3. Execute only that chunk. Record significant commands, working directory, exit status, mutation scope, duration when available, and output location.
4. Persist sanitized facts and intermediate analysis immediately. Do not keep the only copy in conversation or terminal output.
5. Validate nonempty/readable artifacts, JSON/CSV syntax, evidence references, redaction, and protected source hashes.
6. Append work/error/command/evidence records, create an immutable checkpoint with a unique retry suffix, and update the human recovery summary.
7. Write pending execution state to a temporary file in the same directory, validate it and referenced artifacts, then replace `STATE.json` atomically. Update derived summary files from this authoritative manifest.
8. Close as COMPLETED, PARTIAL, BLOCKED, or FAILED. Never start the next chunk before evidence and state are durable.

If an operation fails, stop the chunk; preserve partial outputs, exact sanitized error and exit code, reliability limits, retry instructions, alternative approach, and next safe action. If context/time/output limits approach, stop at a recoverable checkpoint rather than claiming completion.

State files are not a multi-file transaction. A published state must name a validated immutable checkpoint and evidence artifacts. On inconsistency, prefer the latest fully validated checkpoint and record the conflict. Do not silently merge incompatible state.

## Claims and Certification

Record separately:

- Claim kind: FACT, INFERENCE, HYPOTHESIS, OPEN_QUESTION, or DECISION.
- Verification: VERIFIED, PARTIALLY_VERIFIED, UNKNOWN, BLOCKED, or NOT_APPLICABLE.
- Decision approval: PROPOSED, USER_APPROVED, or REJECTED.
- Execution result: NOT_STARTED, IN_PROGRESS, COMPLETED, PARTIAL, BLOCKED, or FAILED.

Findings use IDs such as F-PIPE-001; implementation slices use distinct IDs such as SL-PIPE-001. Every major conclusion cites stable evidence IDs, repository-relative paths, symbols/ranges where available, reproduction method, and limitations. Explain inferences; never promote a hypothesis without evidence.

Stages with blocked mandatory chunks are BLOCKED or COMPLETE_WITH_LIMITATIONS, never unqualified COMPLETE. A final assessment may explicitly document inaccessible evidence, but blocked requirements do not become passing release/certification gates.

## Required Analysis

- Current stack, entry points, feature gates, ownership boundaries, and approved behavior.
- Actual upload/base governance, capture/snapshot, normalization/projection, scoped graph identity, renderer, storage/finalization, recovery, review, downloads, and UI states.
- Candidate-to-canonical-to-snapshot lineage; actual models, migrations, constraints, indexes, repository contracts, and SQLite/Oracle portability. Do not invent tables or rely on live data access.
- Draw.io page/cell hierarchy, node/edge semantics, labels, styles, protected regions, prototypes, scope, and deterministic output. Hash equality proves bytes only, not semantic correctness.
- Guide text/tables/images and topology consumption mappings, with application and lifecycle applicability. Preserve evidence conflicts for authorized decisions. Intake worksheet/import correctness is explicitly out of scope.
- Authorization, parser safety, redaction, failure handling, CAS/leases, idempotency, publication integrity, partial artifacts, restart behavior, and observability.
- Production observability and any separately authorized, standalone synthetic/browser probes. Existing tests, fixtures, test reports, and historical suite counts are excluded as review evidence. A seeded completed run is not an upload-to-runner end-to-end demonstration. UI checks do not replace proposed concurrency/authority verification.
- Current documented intent versus current implementation, desired behavior, gaps, proposed architecture, migration, and deferred work.

For each finding include severity/likelihood, current behavior, evidence, desired behavior, operational/user/security impact, alternatives, trade-offs, component/schema/API/UI impact, recommendation, slice, and objective acceptance/certification.

## Report and Plan

Produce current and target component, sequence, and data-flow diagrams; a pipeline stage table; a source-to-persistence-to-output/UI lineage table; a state machine; a verified schema/ER view; a findings matrix; and architecture decision records. Reuse repository conventions. Do not add infrastructure without evidence of need.

Write these report fragments independently under `report/sections/`:

1. Title and baseline metadata.
2. Executive summary.
3. Evidence inventory.
4. Current architecture.
5. Semantic Draw.io comparison.
6. Business-rule matrix.
7. Data lineage.
8. Root causes.
9. Existing implementation-plan gaps.
10. Options and target architecture.
11. Remediation slices and dependency graph.
12. Verification matrix.
13. User-acceptance checklist.
14. Open questions and limitations.
15. First implementation slice.
16. Appendices, commands, and provenance.

Generate `report/topology-review-report.partial.html` from validated completed fragments only. Assemble `report/topology-review-report.html` only after required sections are complete and blocked evidence is explicitly dispositioned. Use escaped code/XML, relative assets, no unapproved external CDNs, readable scrollable tables, internal navigation, and generation/Git metadata. Validate local links/assets, required sections, browser opening, and desktop/mobile readability. Sensitive raw evidence does not belong in the distributable report.

Each proposed slice must include ID/title/status, priority/risk/value/rationale/evidence, scope/non-goals/dependencies/blockers, files to inspect/modify, schema/API/UI/security/observability impacts, detailed Red-Green-Refactor steps, proposed tests and fixtures, failure cases, proposed acceptance/gating commands, database/API/UI/diagram/performance/security certification as applicable, compatibility, rollback, documentation, evidence attachments, definition of done, completion record, and an execution prompt. Do not claim existing test files or coverage were verified. Use NOT_APPLICABLE with a reason for genuinely inapplicable work; use OUT_OF_SCOPE for the excluded suite rather than misrepresenting its applicability.

Specify execution order, dependencies, critical path, parallelizable independent slices, risks, release boundaries, feature flags, and stop/go decisions. Prioritize characterization of the real UI-to-runner workflow plus backend integrity failures, not speculative discovery features. Formal-methods work is proposed only after executable invariants: bounded TLA+ for the concurrency protocol; Lean remains deferred.

Do not implement until the assessment and plan have been presented and the user explicitly approves the first slice. If implementation is later authorized, keep the same checkpoint protocol, focused tests, reversible changes, semantic evidence, and required phase approvals.