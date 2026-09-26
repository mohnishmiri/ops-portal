# Topology Review Workspace

- Mode: READ_ONLY_INVESTIGATION.
- Repository: `C:\GitHub\aws_diag_v4_1\aws_diag_v4`.
- All new investigation artifacts belong in this folder and its subdirectories.
- Scope and execution rules: [REVIEW_PROTOCOL.md](REVIEW_PROTOCOL.md).
- Recovery order: `STATE.json`, [CHECKPOINT.md](CHECKPOINT.md), the immutable checkpoint named in state, recent work-log entries, and the evidence index.
- Current work: source/document investigation and architecture synthesis are complete enough for reporting as of 2026-09-24. The assembled report is in `report/topology-review-report.html`; no runtime checks or implementation are authorized by this review.
- `to_archive/` and `tests/` are excluded entirely from discovery, inspection, evidence, comparisons, and conclusions, including linked or indirectly referenced material. Do not run or import the excluded test suite.
- Existing-test coverage and certification are outside this review's scope. Future testing recommendations are proposals, not claims about the excluded suite.
- The user confirmed the supplied two-page output as the expected target for this migrating application, not a universal template. Intake/XLSX correctness analysis is excluded and accepted as working by user direction; topology consumption of existing reviewed data remains in scope.
- Production code, existing tests, supplied documents, existing databases, and root project documentation remain unchanged by this investigation.
- Official generation and approval must remain disabled. No implementation, commit, push, deployment, or merge resolution is authorized.

## Supplied References

The three files already present in this folder are inputs, not generated outputs:

- `AWS__input_Outpost_Topology_UNRESOLVED_UNRESOLVED-v1.7.drawio`
- `CCPM_out_put_18678_TargetState_AWS_OutPosts_v01 (1).drawio`
- `Topology Guide.docx`

The supplied two-page output is the user-confirmed expected target for this application (D-009). Per-page context and business rules still require guide/profile interpretation; do not invent application values. The local guide and `docs/architecture/Topology Guide.docx` have identical SHA-256 hashes at initialization. Intake/XLSX analysis is excluded by D-010, not blocked on a missing file.

Additional required sources are `docs/TOPOLOGY_GENERATION_ASSESSMENT.html`, `docs/implementation/topology-implementation-plan.md`, and `docs/topology-implementation-plan.html`. Existence and hashes are checked before document analysis; their claims are not assumed correct.

## Durable Records

- `STATE.json`: authoritative execution cursor and chunk results; published atomically after JSON validation.
- `state/chunk_plan.json`: bounded work definitions and dependencies, not execution results.
- `state/findings.json`: authoritative claim records, with evidence and verification status.
- `state/decisions.json`: authoritative scope and approval decisions.
- `state/inspected_files.json`: file metadata, hashes, inspected ranges, and evidence dependencies.
- `state/completed_chunks.json` and `state/pending_chunks.json`: derived summaries, not competing sources of truth.
- `CHECKPOINT.md`: human-readable current recovery state.
- `checkpoints/`: immutable snapshots; retries use a new suffix.
- `WORK_LOG.md`, `COMMAND_LOG.md`, `ERROR_LOG.md`, `OPEN_QUESTIONS.md`, `EVIDENCE_INDEX.md`: append-only entries or explicitly corrected records.
- `inventory/`, `evidence/`, `analysis/`, `report/sections/`, `report/assets/`: inventories, sanitized evidence, analysis, and incremental report fragments. Stage-specific directories are created before use.

## Resume

1. Read `STATE.json`, `CHECKPOINT.md`, the checkpoint named in state, recent work-log entries, and the evidence index.
2. Verify referenced artifacts, repository commit, unmerged paths, and relevant source hashes. Do not inspect `to_archive/` or `tests/`.
3. Observe any current blockers in STATE.json. Q-001 was resolved by the user and verified; do not resolve future Git conflicts on the user's behalf.
4. Announce and execute only the next eligible bounded chunk from `state/chunk_plan.json`.
5. Persist evidence, validate it, append logs, write a unique checkpoint, then atomically publish the execution cursor.

The final report is assembled at `report/topology-review-report.html`. Earlier conversation findings were used only where persisted in this workspace; no prior test counts or test-derived claims are used as evidence for this scoped review.