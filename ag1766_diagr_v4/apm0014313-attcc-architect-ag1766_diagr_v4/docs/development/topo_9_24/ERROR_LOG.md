# Error and Blocker Log

## B-001: Unmerged Baseline

- Chunk: S00-C01.
- Operation: `git status --short --branch`.
- Exit code: 0; this is a baseline blocker, not a failed command.
- Observed status: `UU src/migration_intake/web/health.py` alongside many pre-existing staged modifications.
- Files affected by investigation: None outside the analysis workspace.
- Reliability limit: The current commit does not describe the mixed working-tree implementation; runtime/import results could be affected by the unresolved merge.
- Partial evidence: Repository/reference metadata remains useful; no architecture conclusion is based on the conflicted file.
- Safe retry: After user merge resolution, repeat scoped Git metadata and refresh affected hashes before analysis.
- Alternative: Explicit user authorization for static-only review of the current mixed tree, with conflicted/dependent behavior marked BLOCKED or UNKNOWN.
- State: Broad review paused; initialization may finish. Do not resolve, stage, reset, stash, or overwrite the conflict.

No parser, test, or runtime failures have been observed in this initialization chunk.

## W-001: Inconclusive Terminal Validation Response

- Chunk: S00-C01.
- Operation: Initial multi-statement PowerShell JSON/artifact validation.
- Observed output: Only a partial command echo; no completion summary or failure code supplied.
- Reliability: Not counted as validation success.
- Recovery: Repeated the same read-only validation in a single script block. Result: PASS, four JSON documents, 12 artifacts, 43 unique chunk IDs.
- Files affected: None.
- State: RESOLVED. Use single-block commands and require a visible completion result.

## E-001: Incorrect Workspace Prefix in Scope Patch

- Chunk: S00-C01.
- Operation: apply_patch for the tests-directory exclusion.
- Error: File not found at repository-root ERROR_LOG.md; the intended log is inside the analysis workspace. No command exit code supplied.
- Partial-output check: Targeted search confirmed pending state and plan still contained only the previous archive exclusion; the new decision was absent. No source file was edited.
- Recovery: Corrected every patch target to the analysis-root prefix and retried the scoped patch. Validate JSON/exclusions before accepting the result.
- State: RESOLVED. Corrected patch applied; subsequent focused validation passed with both exclusions present, zero excluded-suite dependencies, four valid JSON documents, and 12 nonempty referenced artifacts.

## E-002: Checkpoint Helper Syntax

- Chunk: S00-C02.
- Operation: PowerShell Language.Parser.ParseFile on record_chunk.ps1.
- Failure: MissingEndCurlyBrace in the derived pending-chunk summary expression; exit 1.
- Impact: Helper was not executed; published STATE.json and immutable checkpoints remain unchanged. Resume metadata remains valid.
- Repair: Replace the compact nested expression with an explicit bounded foreach block; rerun the identical syntax/JSON validation before execution.
- Retry: Syntax-check the helper, then publish only S00-C02. Do not restart initialization.
- Status: RESOLVED. Identical PowerShell syntax and JSON checks passed after the repair.

## E-003: Atomic Replacement Null Path

- Chunk: S00-C02.
- Operation: record_chunk.ps1 first metadata publication.
- Failure: File.Replace raised "The path is empty. (Parameter 'path')"; exit 1. PowerShell converted the optional null backup path into an empty string.
- Impact: state/inspected_files.json.pending was retained; published metadata/state/checkpoints were not replaced. No production/source file was touched.
- Repair: Pass [NullString]::Value for the optional .NET string argument. Preserve the pending candidate under evidence/repository before retrying the identical chunk.
- Status: RESOLVED. Preserved the candidate as evidence/repository/E-003-preserved-metadata.json; the identical S00-C02 publication completed successfully. No initialization evidence was discarded.

## E-004: Numeric Stage-Key Publication

- Chunk: S01-C03.
- Operation: Add-Member -NotePropertyName for stage key "01" during record_chunk.ps1.
- Failure: Parameter validation rejected a name convertible to PSMemberTypes; exit 1.
- Impact: Source evidence/diagnostic JSON and validation receipt remain saved. STATE.json still identifies the active chunk; no immutable closure snapshot was created and no production file was changed.
- Repair: Use explicit -MemberType NoteProperty -Name for the numeric stage name. Retry only S01-C03; existing generated receipt can be atomically replaced before closure.
- Status: RESOLVED. Identical S01-C03 checkpoint retry completed successfully; stage 01 and its immutable snapshot are published.

## E-005: Rejected Extra Patch Target

- Chunk: S05-C02.
- Operation: apply_patch for the edge comparison note.
- Failure: An unintended repository-root state/unused update target did not exist; the patch was rejected.
- Partial-output check: Targeted file search confirmed edge_comparison.md was not created; the already validated comparison JSON remained intact.
- Recovery: Retry only the intended analysis-folder files, incorporating the user's new target/intake scope decisions, then publish S05-C02.
- Status: RESOLVED. Corrected note and scope decisions passed S05-C02 checkpoint publication. No production/reference file was changed.

## E-006: Rejected Guide Follow-Up Patch

- Chunk: S06-C01, after successful package inventory.
- Operation: apply_patch intended to close inventory and prepare later section/media extraction.
- Failure: An unintended repository-root ERROR_LOG.md target did not exist; the entire patch was rejected.
- Partial-output check: Source search confirmed S06-C01 remained IN_PROGRESS and no extracted_media extension appeared in inspect_guide.ps1. The saved inventory remained valid.
- Recovery: Limited the next edit to the existing chunk record, validated JSON against 45 blocks/11 media and the unchanged guide hash, and retained section/media work for the next bounded chunk.
- Status: RESOLVED for inventory closure. Do not assume the rejected section/media helper extension exists.
- Resume: Register S06-C02 and inspect only blocks 1-5 plus their referenced images. No need to repeat inventory or any completed source/diagram chunk.

## Session Capacity Checkpoint

- This long session is ending at the validated S06-C01 boundary instead of starting more extraction with a crowded context.
- User decisions D-009/D-010 are authoritative for the next session: the two-page output is the application-specific expected target; intake/XLSX correctness analysis is excluded and assumed working.
- tests/ and to_archive/ remain excluded from inspection, execution and evidence. No implementation, database/service execution, commit or deployment occurred.
- The final review/report is still incomplete; a checkpoint is not a completion claim.

## E-011: Embedded Patch Header in Chunk JSON

- Chunk: S08-C02 registration.
- Failure: A malformed multi-file apply_patch prefixed the second file header as added content, leaving literal patch syntax after the otherwise valid chunk object. The plan was not updated.
- Detection: Tool result named only S08-C02; immediate read showed the embedded header before any source inspection or chunk start.
- Impact: S08-C02 JSON was temporarily invalid; published STATE/checkpoints and production/reference files were unchanged.
- Recovery: Remove the exact appended text, apply the plan insertion as a real second update, validate both JSON files and unique IDs before starting S08-C02.
- Status: Repair applied; focused validation pending.
- Follow-up: repaired JSON and plan passed validation before S08-C02 began; E-011 is RESOLVED.

## E-012: Ambiguous HashSet Constructor In Target Assessment

- Chunk: S10-C02.
- Operation: assess_drawio_target.ps1 after successful syntax/chunk validation.
- Failure: PowerShell selected the integer-capacity HashSet constructor for a cell ID string and could not convert it to Int32; exit 1.
- Impact: Failure occurred before target_preservation.json was written. Supplied diagrams, published checkpoints and production files were unchanged.
- Repair: Build each string set explicitly and add IDs one by one; copy sets the same way before intersection.
- Retry: Run the identical assessment once, preserving the current S10-C02 state. Do not repeat prior diagram inventory.
- First repair result: explicit construction succeeded, but PowerShell could not bind generic `IntersectWith` with one collection argument; exit 1. Output still was not written.
- Final repair: replace the generic method call with a direct membership count. One final retry is permitted; if it fails, preserve the chunk as PARTIAL and proceed without this derived metric.
- Final retry result: PASS. target_preservation.json was written with source hashes unchanged. E-012 is RESOLVED; both failed attempts produced no output and no source/reference change.

## E-013: Delayed S13-C02 Chunk Manifest

- Chunk: S13-C02 current-plan reconciliation.
- Deviation: The assistant announced the bounded read and inspected relevant Markdown/HTML completion ranges before creating/publishing the chunk manifest.
- Impact: Reads were limited to two planned documents and produced no output/source mutation, but the exact resume cursor was not durable during those reads.
- Recovery: Create/register S13-C02, publish its start, then write and validate conclusions from the already gathered bounded evidence. Do not repeat or broaden the reads.
- Status: Recovery initiated before analysis artifact creation.
- Recovery result: S13-C02 start was published before conclusions were written; bounded source reads were not repeated or widened. E-013 is RESOLVED.

## E-007: Interrupted Final State Publication

- Chunk: S06-C01.
- Failure: File.Replace reported "Unable to remove the file to be replaced" while publishing state/pending_chunks.json; exit 1. File attributes were Archive, not ReadOnly; the precise transient cause is unknown.
- Already durable: guide evidence, COMPLETED receipt, immutable S06-C01 snapshot, CHECKPOINT.md, work/evidence logs, and completed-chunk summary.
- Not yet published: derived pending summary and STATE.json execution cursor, which still named S05-C02.
- Recovery: Preserve the staged pending summary and validate existing artifacts, then retry only the two final atomic replacements. Do not rerun the chunk, duplicate logs, or overwrite the immutable snapshot.
- Recovery helper: recover_checkpoint_publication.ps1. Observed result: RECOVERED, exit 0; 17 chunks completed, last S06-C01, next S06-C02, state PAUSED_AT_CHECKPOINT. E-007 is RESOLVED; staged summary preserved as evidence/repository/E-007-pending-summary.json.

## E-008: Response Image Retrieval Failure

- Chunk: S06-C03, guide blocks 6-7.
- User-reported failure: HTTP 400, invalid_request_body, "Error while downloading file. Upstream status code: 404."
- Client request: 1614a36c-54cb-4ee8-8ba5-285132853c66; GH request: 67BE:1AB24B:1DA123:201E90:6AB576AD.
- Local verification: section-002.json, image3.png, and image3-4x.png all exist and are nonempty. The original image still matches its recorded SHA-256. STATE.json retains active S06-C03; S06-C02 is the last completed checkpoint.
- Hypothesis: response-image retrieval failed upstream, not local document extraction. An expired/unavailable attachment is possible but not proven.
- Safe retry: issue one fresh local-image view; do not repeat extraction, overwrite evidence, or reuse an old response-image URL.
- Alternative if image delivery fails: retain the original and derived images, use an available local-only inspection method, or record visual labels as unverified. Do not invent labels or send evidence to external OCR.
- Status: REVIEW WORK RECOVERED via local Windows OCR after a fresh view remained unsuitable for reliable label inspection. Upstream service repair is not claimed. Original/derived images and qualified OCR are preserved; S06-C03 closes with visual-label limitations explicit.

## E-009: Local OCR Framework Reference Paths

- Chunk: S06-C03, recovery fallback for E-008.
- Operation: Compile local_ocr.cs using the installed .NET Framework compiler and Windows OCR metadata.
- Failure: CS0006 for assumed Framework64/v4.0.30319/Facades/System.Runtime.dll and System.Threading.Tasks.dll paths; exit 1.
- Impact: No OCR execution or source/reference mutation. The new helper source and previously validated image artifacts remain available.
- Safe retry: Locate the two assemblies in the installed framework assembly cache, verify paths, and retry the same bounded helper compilation. No dependency download, installation, application build, or excluded-suite inspection.
- Status: RESOLVED. Installed assembly-cache paths replaced the nonexistent facade paths. Final compilation and execution succeeded; no result is attributed to the failed compile.

## E-010: Windows Runtime Async Compilation

- Chunk: S06-C03, local OCR fallback.
- Verified assembly-cache paths resolved E-009's missing metadata files. Second compilation then reported CS4028 for direct await on Windows Runtime IAsyncOperation values; exit 1.
- No OCR result or source/reference mutation occurred.
- Final bounded repair: use the installed WindowsRuntimeSystemExtensions.AsTask bridge to convert operations to CLR Tasks before await. Limit compilation to one further attempt; retain visual-label uncertainty if it fails.
- Status: RESOLVED. Final helper compilation passed and local OCR returned four lines with an unchanged source hash. No external OCR or dependency installation occurred.