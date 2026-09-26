# Governed Preview: Capture, Projection and Reservation

Evidence EV-FLOW-002. S02-C02, static inspection of five source files. No application execution, database access, existing-suite inspection, or archived evidence.

## Route Boundary

- topology.py `generate_governed_preview` verifies application/intake URL ownership, TOPOLOGY_GENERATE capability, CSRF, selected base existence/ownership, APPROVED state, and compatibility ID/record.
- It constructs one ContextKey from form environment/site and a ScopeSelection with combined-overview-with-details layout. The form defaults are PROD/SITE_A/Overview; render capability is parsed as an enum.
- It calls runner.run_preview with the two `_PREVIEW_MAPPINGS` entries for CTL-002 application name/acronym, the stored parser-policy hash, generator label governed-preview-v1, and constant layout/result policy hashes consisting of zero/one characters.
- Parser-policy compatibility is checked downstream. The constant layout/result hashes are integration placeholders, not evidence that actual policies have been fingerprinted; assess their required semantics in the policy/renderer review.
- Route catches GovernedRunnerError as 409. Construction/validation exceptions outside that boundary require separate inspection; no HTTP error reproduction was attempted.

## Immutable Capture

- run_preview invokes _capture_preview before project/reserve/render and supplies DRAFT_PREVIEW mode with capture_id, not snapshot_id.
- Capture enters a UoW, requests an intake capture fence, reads intake, locks application/intake via repositories, validates catalog compiled hash and preview-state eligibility, and gathers answers/resources/relationships/interfaces/WaveUtil.
- `_capture_answers` serializes repository-returned confirmed answers with response payload, confirm/review state, revision and provenance. The repository query implementation is not inspected in this chunk; no assumption about its filtering beyond the caller contract is certified.
- Active resource/link current revisions are checked for revision identity and CONFIRMED state. Interface epoch is compared with the locked application epoch before capture serialization.
- The v3 document is canonicalized and stored as a topology capture with SHA-256 and an audit event; the UoW commits before projection. This is a frozen copy of preview inputs, not approved official authority.
- Observation for later lineage review: application identifiers are fetched and checked for empty normalized values, but the document writes `identifiers: []`. Internal application UUID is retained. Determine whether the missing external identifier lineage violates the approved mapping contract before prescribing a change.

## Correct v3 Owner

- The runtime runner imports serialize_snapshot_document/load_snapshot_document from topology/contracts.py, not application/snapshots.py.
- The latter still declares legacy schema version 2.0.0/support for 1.0.0 and 2.0.0. Its presence is not evidence that the governed runner uses a legacy snapshot format.
- topology/contracts.py declares schema 3.0.0, validates shape, deeply freezes values, canonicalizes UTF-8 JSON with sorted keys/no NaN, hashes exact bytes, and rejects stored content whose hash or canonical reserialization differs.
- Loader shape helpers were not fully inspected here. Source implementations, not runtime corpus verification, establish these observed checks.

## Projection and T1 Reservation

1. project_v3_snapshot reloads/validates authority bytes and matches application/intake identity to the requested selection.
2. It rejects duplicate output mappings, processes confirmed answers, records blocking UNMAPPED_ANSWER/MISSING_FACT issues as applicable, then projects resources/relationships/semantic graph.
3. The runner rejects a projection with blockers and verifies canonical projection serialization/hash.
4. It calls BaseDiagramService.eligible_base with exact selection/capability/partition views, loads compatibility and checks parser-policy hash.
5. TopologyInputIdentity includes mode/capability, projection/selection/base/compatibility/profile/catalog hashes, generator/parser/layout/result policies, and selected contexts. Operational IDs/timestamps are documented as excluded from semantic identity in the contract.
6. T1 reopens a UoW, fences/locks intake/application/base, checks application/state and base version/review/compatibility stability, persists or reuses topology input, reserves a run, writes a reservation audit event if absent, and commits.
7. Non-PENDING reservations return immediately. PENDING runs claim a UUID lease; an explicit claim conflict returns the current run. Exact SQL atomicity/idempotency is not established by these caller-level checks and is deferred to repository inspection.
8. After commit, the runner reloads the persisted projection with its expected hash, compares input pins/identity, and calls the renderer with persisted input. Renderer exceptions attempt a sanitized leased failure transition. A successful renderer call precedes a leased STORING transition and finalization.

Persisted-input validation occurs after claiming the lease but before the renderer try/except. Whether these validation failures receive truthful terminal state or only later lease recovery is an open failure-path check for S02-C03/S11.

## Official Authority Contrast

run_official loads a persisted snapshot by ID, requires schema 3.0.0 and frozen intake state in the contract, verifies exact canonical bytes/hash and snapshot row metadata, and then enters the shared project/reserve/render path with OFFICIAL_SNAPSHOT mode. This method's existence is not web release approval; official generation remains disabled by the review boundary.

## F-PIPE-001: Route Mapping Set Cannot Cover Other Confirmed Answers

- Kind: FACT / VERIFIED static; severity: High for the preview integration; runtime not demonstrated.
- The route passes only CTL-002 mappings. The projector creates a blocking UNMAPPED_ANSWER for each confirmed captured answer whose question code has no mapping. The runner aborts before reservation if blockers exist.
- Therefore a capture containing any other confirmed question cannot pass this route's mapping contract. This is a conditional source-level conclusion, not a claim about the contents of a particular intake.
- Impact: An otherwise eligible approved base does not establish a usable preview workflow for a populated intake. The upload governance gap and this mapping limitation are independent prerequisites.
- Proposed options: select a versioned profile/catalog mapping set appropriate to the approved capability; or explicitly define a reviewed label-only projection boundary that excludes nonparticipating facts with recorded reasons. Do not globally suppress strict unmapped-fact failures or discard required facts silently.
- Proposed acceptance: applicable confirmed fields map with provenance; irrelevant fields have explicitly approved exclusions; genuinely unsupported required facts block with actionable diagnostics. Use independently designed synthetic probes in a later authorized slice, not the excluded suite.
- API/schema/UI impact: likely mapping/profile integration and better blocker presentation; no schema change justified yet. Rollback preserves current strict blocking behavior and disabled official activation.

## Verification Limits

- Capture fencing/query implementations, repository reservation SQL, deep projection graph semantics, renderer policy hashes, and finalization state behavior still require local inspection.
- No concurrency, determinism, HTTP, or database result is certified here. Excluded tests and historical test counts are not evidence.