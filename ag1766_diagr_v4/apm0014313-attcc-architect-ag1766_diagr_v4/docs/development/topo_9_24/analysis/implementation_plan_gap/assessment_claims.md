# Assessment Section 7: Current-Worktree Reconciliation

EV-DOC-001; S13-C01. Compared only `docs/TOPOLOGY_GENERATION_ASSESSMENT.html` section 7 (lines 152-165) with persisted current-worktree source evidence. The assessment remains a historical input; it was not edited.

| Original gap | Current classification | Current evidence and qualification |
| --- | --- | --- |
| Snapshot metadata pinned but live answers rendered | PARTIALLY REMEDIATED / CONTAINED | Governed preview commits immutable v3 capture; official runner requires frozen v3 snapshot. Legacy generation remains present behind default-off flag, and activation route wiring remains unsafe. EV-FLOW-002, EV-STATUS-002. |
| Migration/ORM/repository governance mismatch; governed pipeline cannot run | SUPERSEDED AS BLANKET CLAIM | Governed topology tables/fields and repositories now exist and source paths are wired. Current integrity gaps are narrower but serious: missing input/current-revision/review FKs, authority cardinality, CAS/finalization/recovery defects. EV-DATA-001..004, EV-STATUS-001. No deployed schema was inspected. |
| Interfaces absent from snapshots/captures/projections/rendering | PARTIALLY REMEDIATED | Interfaces are epoch-fenced into preview capture and projected into nodes/flows. Scope is currently invented for single-context requests, category/provenance are dropped, and no production target profile exists. EV-FLOW-002, EV-PROJ-001, EV-PROFILE-001. |
| Legacy service always persists READY_FOR_REVIEW | CONTAINED / CURRENT LEGACY DETAIL NOT REVERIFIED | Governed finalization validates result/status agreement and readiness, but explicit validation failures can remain STORING. Legacy path is disabled yet still used by approval/download wiring. This bounded review did not reopen the legacy render body solely to restate its historical status behavior. EV-FLOW-003, EV-STATUS-002. |
| Route security implementation differs from tests | TEST COMPARISON OUT OF SCOPE | Current source contains scope, capability, CSRF and default-off checks. `tests/` is user-excluded, so the implementation-versus-tests claim is not evaluated. Approval and delivery have current service-integrity defects independent of test drift. EV-FLOW-001, EV-STATUS-002. |
| No repeated-node/edge layout or style engine | PARTIALLY REMEDIATED | A deterministic repeated structural renderer exists, but ignores prototypes/styles, omits scoped/category identity, uses global page IDs and does not implement declared continuation pages. EV-RENDER-001, EV-DRAWIO-007. |
| Mutable interfaces lack authoritative capture semantics | SUBSTANTIALLY REMEDIATED WITH RESIDUAL CAS GAP | Immutable capture plus application interface epoch exists. Interface edits increment versions/epoch but do not compare expected row version, so stale writes remain possible. EV-DATA-002. |
| Unknown/blank locations and directions lack policy | PARTIALLY REMEDIATED / DEFECTIVE INTEGRATION | Unknown direction/missing endpoint/invalid port block; unknown target resource scope blocks. Missing interface scope is instead replaced by selected context, and unknown category is silently dropped. EV-PROJ-001. |
| Contacts/endpoints are sensitive; strict allowlist needed | REMEDIATED IN CAPTURE ALLOWLIST | PROJECTION_FIELDS excludes contact/cutover-contact/notes and includes selected interface fields plus lineage metadata. Endpoint display/sensitive-label rules still require profile/renderer validation. EV-PROJ-001. |
| Filesystem writes precede transaction completion; failed runs can leave orphan blobs | VERIFIED RESIDUAL BY DESIGN | Governed finalizer stores/read-verifies bytes before metadata commit. No deletion is implemented; storage orphans remain possible and require bounded inventory/retention policy. Recovery inventory itself excludes lease-free runs. EV-FLOW-003, EV-STATUS-001. |

## Important New Current Findings Missing From The Assessment

- F-PROFILE-001: no governed production profile for the supplied base/two-page target.
- F-PROJ-001: active preview invents explicit PROD/SITE_A for interfaces without canonical scope.
- F-RENDER-001/F-RENDER-004: generated cells ignore styles/prototypes and global ID lookup conflicts with 104 page-local repeated IDs in the actual target.
- F-AUTH-003: direct approval route uses legacy unfenced review rather than governed review.
- F-DATA-006: valid resource reparent leaves head/current revision mismatched.
- F-REC-001: recovery cap uses a counter that recovery never increments.
- F-AUTH-001/F-API-001: review authority and artifact delivery remain incomplete/inconsistent.

## Documentation Disposition

Do not delete or rewrite the assessment as if it were wrong when authored. Label section 7 as a dated baseline and link the final current-worktree review. Current release decisions must use the new findings/evidence matrix, not historical severities or historical test claims.

No original assessment test result was reused as current evidence. Existing tests remain out of scope.