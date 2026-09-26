# Review, Inspection and HTTP Integrity

EV-STATUS-002; S11-C02. Five controlling surfaces inspected. Official generation/approval remains disabled and UI approval is hardcoded unavailable. No HTTP request or service execution.

## Available Strong Service

TopologyReviewService provides:

- Scoped run lookup and capability/rationale validation.
- Official mode/authority, completed result status and pending approval checks.
- Base lifecycle/review/profile/capability/compatibility pins.
- Run/input pin agreement.
- Exact three-artifact bundle, storage byte/size/hash and manifest/run/readiness status checks.
- Blocker/warning rationale checks and row-version CAS review mutation with append review record.
- Approved official artifact and completed preview artifact receipt verification.

It still lacks full projection/hash and source snapshot revalidation (F-AUTH-001), but it is materially stronger than the route's actual approval path.

## F-AUTH-003: Approval Route Uses Legacy Unfenced Review

- FACT / VERIFIED static; severity Critical for any activation.
- `review_generation_run` is feature/capability/CSRF gated, but injects TopologyGenerationService and calls `approve_generation_run`, not TopologyReviewService.review_run.
- Legacy approval checks only scoped existence, non-null snapshot ID, reviewable status and pending approval. It does not require OFFICIAL_SNAPSHOT mode/authority/phase, immutable input/manifest, valid base/compatibility/profile/policies, complete verified bundle, readiness blockers/warnings, projection/source authority or exact issue rationales.
- It calls repository `update_run_approval`, a loaded-row mutation with no expected row version/approval predicate and no append TopologyReview record.
- Impact: flipping the feature flag would expose a weaker approval boundary than the implemented governance service, permit stale/concurrent decisions and lose review audit evidence.
- Required release change: route to the repaired TopologyReviewService contract with expected version and issue decisions, explicit error translation and no legacy fallback. Keep controls hidden/default-off until end-to-end negative/positive certification.

## F-API-001: Artifact Delivery Has Inconsistent Authority And Error Contracts

- FACT / VERIFIED static; severity High.
- Preview diagram/report/manifest use receipt verification, but TopologyReviewError is neither caught by these routes nor registered in main.py. Missing/corrupt/ineligible preview artifacts therefore fall to generic server-error handling rather than an explicit bounded 404/409/410 contract.
- Official/non-preview diagram and report use TopologyGenerationService raw storage loading, without stored receipt verification or approval/status guard.
- Manifest route always calls `verified_preview_artifact`; an official run with a visible manifest link is rejected as non-preview and the error is unhandled.
- Strong `verified_artifact` exists for approved official runs but is not called by these routes. There is no separately named verified preapproval-inspection contract.
- Proposed change: centralize mode-aware, scoped verified artifact delivery; define whether official preapproval inspection is allowed and verify receipts either way. Translate typed errors consistently without exposing storage paths/details.

## Visible Run-State Drift

- Detail route computes `inspection_ready` from terminal phase/status and all three artifact rows, but does not verify bytes. Template calls a metadata-complete bundle "receipt-verified" before download verification.
- Each link is enabled by its individual artifact row, not inspection_ready (F-UI-003). Partial bundle warning and active links can coexist.
- For any run with no snapshot ID, the template says "Generated from current intake data." Governed preview actually renders from a committed immutable capture. The message understates the authority boundary and can be read as mutable live rendering.
- `approval_available` is always False, correctly hiding controls. The direct route remains present and would activate under the single legacy feature flag.
- Draft preview ineligibility and official activation-disabled messages are otherwise explicit.

## Recommended HTTP/UI State Matrix

| Run/bundle | Detail state | Delivery | Review |
| --- | --- | --- | --- |
| Preview pending/running | Non-authoritative, phase visible | No links | Never |
| Preview failed/incomplete/corrupt | Exact failure/unavailable status | Typed unavailable response; no misleading link | Never |
| Preview completed/verified bundle | Immutable capture ID/hash, PREVIEW label | Scoped receipt-verified inspection | Never |
| Official pending/running | Official authority pins, phase visible | Policy-defined verified inspection only | No |
| Official completed with blocker/corruption | Blocked reason, no ready claim | Typed failure | No |
| Official reviewable verified bundle | Complete verified authority/bundle | Verified inspection | Authorized CAS review |
| Official approved/superseded | Immutable decision history and successor | Approved-policy delivery | No second decision |
| Legacy | LEGACY_UNPINNED warning | Historical policy only | Never |

## Release Conditions

1. Repair TopologyReviewService's missing projection/source authority validation.
2. Wire approval/supersession routes only to that service with CAS and append audit.
3. Create one mode-aware verified delivery application boundary and typed web error mapping.
4. Derive link visibility/status text from the same verified bundle state used server-side.
5. Label preview authority as immutable non-authoritative capture, not current live data.
6. Keep official activation disabled until standalone real workflow and concurrency/integrity checks pass.

Stage 11 is COMPLETE_WITH_LIMITATIONS: status/review/delivery source behavior is mapped; no HTTP/concurrency/database execution or accessibility/browser verification was performed.