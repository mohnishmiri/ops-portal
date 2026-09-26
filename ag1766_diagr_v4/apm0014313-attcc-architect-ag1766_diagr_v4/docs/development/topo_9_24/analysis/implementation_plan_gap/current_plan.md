# Active Plan Completion-Claim Reconciliation

EV-DOC-002; S13-C02. Compared Markdown TP07-TP15 completion sections and HTML TP13-TP15 completion blocks with current persisted source/document/diagram evidence. Existing tests and historical test counts are user-excluded and are neither rerun nor used to invalidate/confirm past execution records.

## Status Disposition

| Slice | Plan claim | Current disposition | Source-backed reason |
| --- | --- | --- | --- |
| TP07 projection | COMPLETE; scope in identity, missing scope fails closed, provenance retained | REOPEN REQUIRED | Interface allowlist has no scope; single-context selection becomes explicit source scope; endpoint identity omits scope; guide category and resource provenance are lost; off-context resources enter semantic nodes. F-PROJ-001..004, F-PROV-001. |
| TP08 profile/compatibility | COMPLETE; context/page/prototype pins and continuation schema | INFRASTRUCTURE PARTIAL, PRODUCTION PROFILE BLOCKED | Only synthetic profiles exist. Cell IDs are global rather than page-qualified; actual target repeats 104 IDs across pages. Projection-version/resource-kind compatibility is not called. F-PROFILE-001/003, F-RENDER-004. |
| TP09 structural renderer | COMPLETE; semantic IDs, endpoints, approved regions, overflow | REOPEN REQUIRED | Prototypes are checked but ignored; generated cells are unstyled; scope/category/type omitted from IDs; continuation is not implemented. F-RENDER-001..003. The completion note itself defers continuation/style certification despite slice acceptance requiring them. |
| TP10 finalization/status | COMPLETE; lease/version CAS and persisted failures | REOPEN REQUIRED | Explicit ArtifactFinalizationError bypasses FAILED transition; completion is SELECT then ORM write rather than atomic conditional final UPDATE. F-PIPE-002, H-PIPE-001. |
| TP11 preview HTTP | COMPLETE; explicit context selection and verified route integration | PARTIAL / WORKFLOW BLOCKED | UI context is hidden hardcoded PROD/SITE_A/Overview; fresh upload yields ineligible DRAFT base with no governance web path; CTL-002-only mapping blocks other confirmed answers; typed artifact errors are unhandled. F-UI-001/002, F-PIPE-001, F-API-001. |
| TP12 review integrity | COMPLETE; full immutable authority/policy revalidation and CAS | REOPEN REQUIRED | Service does not revalidate projection/hash or source snapshot; actual approval route uses legacy unfenced service with no append review record. F-AUTH-001/003. |
| TP13 truthful inspection UI | COMPLETE in Markdown | REOPEN REQUIRED; HTML STALE | Metadata row presence is called receipt-verified; links ignore complete-bundle readiness; preview text says current intake data instead of immutable capture; official manifest route cannot deliver official manifests. F-UI-003, F-API-001. HTML still says NOT_STARTED. |
| TP14 bounded recovery | COMPLETE; stops at three attempts and diagnostic inventory | REOPEN REQUIRED; HTML STALE | Recovery never advances the checked attempt counter; later semantic reruns can be denied before first recovery; diagnostics see only lease-bearing oldest 100 rows. F-REC-001/002. HTML still says NOT_STARTED. |
| TP15 certification | IN_PROGRESS in Markdown | BLOCKED / HTML STALE | IN_PROGRESS is directionally correct, but blockers are not just broad quality gates. Critical profile/projection/renderer/review/workflow defects remain. Existing Oracle/SQLite/browser/performance claims are historical records and out of this review's evidence scope. HTML says NOT_STARTED. |

TP01-TP06 completion records were not reopened in this chunk. Their retained controls (default-off containment, schema foundation, policy, epochs and immutable authority) are important, but current downstream defects prevent release claims.

## Direct Claim Contradictions

- TP07 says missing scope fails closed; active single-context interface projection marks fallback scope EXPLICIT.
- TP09 scope required IDs from semantic identity plus page/context and cloned prototypes; completion implementation hashes weaker identity and constructs new unstyled cells.
- TP10 says finalization completes under lease/row-version CAS and persists sanitized failures; explicit validation errors bypass failure recording and final completion lacks atomic conditional DML.
- TP12 says complete source authority/policy revalidation; review omits projection/source snapshot validation, and the route does not use it.
- TP13 says incomplete bundles expose no download; template enables individual links when rows exist.
- TP14 says a three-attempt cap; recovery claim never changes the checked counter.

These are source-level contradictions, independent of whether historical focused commands passed.

## Plan Synchronization Drift

- Markdown reports TP13/TP14 COMPLETE and TP15 IN_PROGRESS with later evidence.
- HTML completion blocks report TP13/TP14/TP15 NOT_STARTED and NOT_RUN.
- Markdown TP15 text is internally stale: earlier handoff/evidence says manual diagram signoff complete, while the completion block still lists signoff as remaining.
- Markdown and STATE also rely heavily on test counts that are historical and cannot substitute for verified current source invariants.

## Recommended Documentation Treatment

1. Preserve original completion dates/evidence as historical records; do not erase them.
2. Add a dated current-worktree remediation overlay that marks TP07-TP14 `REOPEN_REQUIRED` or creates explicit corrective slices mapped to these findings.
3. Make TP15 `BLOCKED` on corrective slices plus runtime permission/certification, not only broad pytest/mypy/Ruff debt.
4. Synchronize HTML from the corrected Markdown after review approval; include a source hash/generated timestamp.
5. Keep official generation/approval default-off and TP16 unavailable.
6. Do not publish these changes into canonical plans during this read-only investigation; draft the exact amendments in the final remediation plan for user approval.

## Evidence Limitation

This reconciliation evaluates current source/document invariants. It does not review tests/, rerun historical commands, inspect private evidence, connect to Oracle/SQLite or determine whether a prior checkout once satisfied each completion record.