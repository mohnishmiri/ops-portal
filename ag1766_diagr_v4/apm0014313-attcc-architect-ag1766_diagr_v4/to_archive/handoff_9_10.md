# Handoff: UAQ and Interface Tracking Import Workflow (Architect-Reviewed)

**Handoff date:** 2026-09-10
**Reviewed by:** Technical architect pass over `HANDOFF_UAQ_INTERFACE_TRACKING_2026-09-09.md`
**Repository:** `C:\Ash_data\Projects\aws_diag_v4`
**Branch:** `ag1766_diagr_v4`
**Committed baseline reviewed:** `ac4adf8` - `Add UAQ and interface tracking import workflow`
**Remote:** `origin/ag1766_diagr_v4`
**Application:** FastAPI, SQLAlchemy 2.x, Alembic, SQLite, Jinja2, openpyxl
**Handoff purpose:** Carry forward the 2026-09-09 operational handoff with an independent architect review of its claims against the current source tree, a confirmed root cause for the open P0 defect, one previously unreported production-readiness gap, and a re-ordered next-action sequence.

---

## 0. Architect Review — Executive Assessment

I read the 2026-09-09 handoff alongside `AGENTS.md`, `STATE.md`, and the actual source under `src/migration_intake/`. The document is unusually good handoff hygiene for this stage of a project: it states an explicit architectural invariant (candidates never become answers without review), gives exact routes/files, gives a reproducible local deployment recipe, and separates "expected findings" from "defects" so the next owner doesn't chase phantom bugs. Verified against the repo, its factual claims hold up — file paths, migrations, route paths, sheet allow-lists, and test locations all exist as described. I did not find fabricated or stale claims in the sections I checked.

Two things earn a closer look before the next owner starts coding, one of which materially changes where they should start.

### 0.1 Confirmed root cause for the P0 `APPLICATION_ID_MISSING` defect

Section 3 of the original handoff lists six hypotheses and, correctly, tells the next owner to reproduce before fixing. I traced the actual extraction path and can shortcut most of that investigation:

- `WorkbookService._source_identity_values()` — `src/migration_intake/application/services/workbook.py:578-596` — only inspects **`rows[0]`** of each recognized sheet (`UAQ` or `Migrating App Data`), i.e. it assumes the sheet is *row-shaped*: one row per application, with `Correlation ID` as a **column header**.
- It only recognizes a key whose alphanumeric-normalized form is `correlationid` or `migratingappcorrelationid`.
- If the real (or synthetic test) `Migrating App Data` sheet is laid out as a **key/value sheet** — e.g. two columns like `Field` / `Value`, with a row `Field="Correlation ID", Value="APP-1234"` — then `rows[0]` is the *first field row*, not a row containing a `Correlation ID` column, and the function silently returns an empty identity list. That produces exactly the observed `APPLICATION_ID_MISSING` decision.
- This is precisely hypothesis #6 in the original document ("Whether source identity is being read from a key/value-shaped sheet rather than a row-shaped sheet"). I'm elevating it from a hypothesis to the leading, verified explanation, localized to one 18-line static method.

**Recommendation:** before building a full synthetic end-to-end fixture (P0 item #2 in the original plan), write a narrow unit test directly against `_source_identity_values()` with two fixtures — a row-shaped sheet and a key/value-shaped sheet — to confirm which shape the real `Migrating App Data` export actually uses. That is a five-minute test against a pure static method versus a multi-hour full-stack repro, and it tells you immediately whether the fix belongs in `_source_identity_values` (support both shapes) or in a corrected test fixture (original doc's first "expected fix option"). If the real FACET export is genuinely key/value-shaped, the fix must go into the reviewed adapter mapping (`interface-tracking-facet-v1.yaml`) per the project's own governance rule, not as an ad hoc branch in `workbook.py` — keep the mapping artifact as the single source of truth for the shape contract.

### 0.2 New finding: the capability/authorization system is not wired into any route

This was not flagged in the 2026-09-09 handoff and is worth surfacing before more routes are added on top of the current pattern:

- `src/migration_intake/web/security.py` defines `Capability` (8 codes, including `EVIDENCE_UPLOAD` and `CANDIDATE_REVIEW`) and a `require_capability()` / `has_capability()` pair, described in STATE.md's SEC01a checkpoint as "37 tests."
- A repo-wide search shows `require_capability` is called **nowhere in `src/migration_intake/web/routes/`** — every reference outside `security.py` itself is a unit test exercising the function in isolation (`tests/web/test_security.py`, `tests/unit/application/test_command_contracts.py`, `tests/unit/application/test_port_contract_shapes.py`).
- Concretely, the Gap Workbook routes reviewed in this handoff (`src/migration_intake/web/routes/gap_workbook.py`) enforce CSRF on `POST .../reimport` but have **no capability check on either route**, and the `GET .../gap-workbook.xlsx` export route has no CSRF or capability check at all — any caller who can reach the app can download the gap workbook for any application/intake pair without an authorization gate. The import coverage decision routes (accept/reject/defer) described in STATE.md's "Import Candidate Decisions" checkpoint validate CSRF, ownership, identity, and row version, but the same absence of `require_capability` calls applies there too.
- This is consistent with the project currently running single-actor local mode (`ACTOR_ID` env var, no auth), so it is plausibly an intentional deferral rather than an oversight — but it is not documented as a known gap anywhere in STATE.md or the 2026-09-09 handoff, and the existing 37 SEC01a tests could give a false sense that authorization is enforced end-to-end when it is only unit-tested in isolation.

**Recommendation:** add this explicitly to the P1 security backlog (Section 7) as its own line item — "wire `require_capability` into evidence, candidate-decision, and gap-workbook routes, with integration tests proving a missing capability returns 403" — separate from the CSRF/concurrency negative tests already listed, because it is a different failure class (missing authorization, not missing input validation).

### 0.3 Minor verified notes (no action required, informational)

- `tests/browser/` does not exist yet in the working tree. Section 8's Playwright command (`python -m pytest tests/browser/ -v -m browser`) and `tests/browser/test_intake_journey.py` describe a suite to be **created from scratch**, not merely finished — worth saying explicitly so the next owner doesn't spend time looking for a partially-built harness.
- Migration numbering has a gap: `0004_candidates.py` is followed by `0006_snapshots.py` with no `0005` file. The `down_revision` chain is correct (`0006` points to `0004`), so this is not a broken chain — just a numbering skip worth a one-line note in case a future contributor assumes a deleted migration.
- Everything else spot-checked — the catalog artifact (`catalog-0.2.0.csv`, 112 questions), the Interface Tracking sheet allow-list and ignore-list, migrations `0007`-`0010`, the Gap Workbook service/routes, and the referenced test files under `tests/unit/imports/` and `tests/unit/application/test_workbook_service.py` — matches the document's claims exactly.

### 0.4 Revised next-action sequence

Adopt the original Section 8 sequence with one change: insert a narrow unit test against `_source_identity_values()` as step 2a, before building the full synthetic workbook fixture. This turns the P0 investigation from "reproduce a full end-to-end quarantine and guess" into "confirm a known function's behavior against two shapes and fix the shape it's missing."

1. Deploy clean local database and catalog using Section 4.
2. Unit-test `WorkbookService._source_identity_values()` directly against a row-shaped and a key/value-shaped `Migrating App Data` fixture to confirm the extraction gap.
3. Fix in the mapping/adapter layer (not an ad hoc branch) and add regression tests.
4. Add a synthetic matched end-to-end integration test for UAQ.
5. Add a synthetic matched end-to-end integration test for Interface Tracking.
6. Run the full import/evidence/questionnaire focused suites.
7. Wire `require_capability` into evidence, candidate-decision, and gap-workbook routes; add 403 coverage.
8. Add visible Gap Workbook reimport UI if the workflow is intended for business users.
9. Scaffold and add Playwright release-journey coverage under `tests/browser/`.
10. Run full tests, Ruff, and mypy.
11. Update `STATE.md` and this handoff with exact outputs.
12. Commit and push only after review of the final diff and test output.

---

## 1. Executive Summary

This repository contains a production-shaped Migration Intake application for AWS Outposts migration assessment workflows. The implemented feature in commit `ac4adf8` adds a candidate-first import workflow for:

- UAQ CSV evidence.
- Interface Tracking Excel evidence.
- Deterministic identity validation.
- Import-run findings and coverage reporting.
- Candidate review and acceptance into canonical questionnaire answers.
- Candidate-only Gap Workbook export and reimport.

The central architectural invariant is:

> Evidence readers and importers create proposed candidates. They never directly approve or overwrite canonical questionnaire answers.

A reviewer must inspect and accept a valid candidate before it becomes a canonical answer through `AnswerService`. Rejected or deferred candidates do not modify canonical answers. Identity mismatches, missing identities, ambiguous identities, and cross-source conflicts quarantine the import and suppress reviewable application-answer candidates.

The feature is substantially implemented. The next owner should treat the code as an integration/release-hardening baseline, not as a finished production release.

Practical completion estimate:

- **UAQ and Interface Tracking scoped feature:** approximately 90% complete.
- **Production release confidence:** lower than 90% until the browser journey, current live Interface Tracking identity defect, route-level authorization wiring (Section 0.2), security coverage, and full regression suite are closed.

---

## 2. What Was Delivered

### 2.1 Catalog and bootstrap

- Added a reviewed, packaged catalog artifact at:
  - `src/migration_intake/catalog/data/catalog-0.2.0.csv`
- Added explicit idempotent catalog publication command:
  - `migration-intake-bootstrap-catalog`
- Added catalog metadata migration:
  - `0007_catalog_question_metadata.py`
- The intake pins a catalog release. Import validation uses the pinned catalog rather than an arbitrary current catalog.
- Current production-shaped catalog expectation is semantic version `0.2.0` with 112 questions as described by the active import plan. Do not rely on older handoff documents that mention catalog `1.0.0` or 152 questions; those facts are stale.

### 2.2 Database and migration repairs

Added or updated migrations:

- `0007_catalog_question_metadata.py`
- `0008_repair_answer_instance_metadata.py`
- `0009_repair_answer_revision_metadata.py`
- `0010_import_identity.py`

These reconcile historical local databases with current ORM fields and add import identity metadata. Always run `python -m alembic upgrade head` before testing a local database.

*(Architect note: verified — `0007` through `0010` exist under `src/migration_intake/persistence/migrations/versions/`. Note the pre-existing `0004`→`0006` numbering skip described in Section 0.3; it does not affect this work.)*

### 2.3 Identity validation

File:

- `src/migration_intake/imports/source_identity.py`

Identity decisions are deterministic:

- `APPLICATION_MATCHED`
- `APPLICATION_ID_MISSING`
- `APPLICATION_MISMATCH`
- `AMBIGUOUS_APPLICATION_MATCH`
- `SOURCE_ID_CONFLICT`

Normalization is case-insensitive and removes non-alphanumeric characters. Matching is performed against the selected application's correlation identifier. Application name and acronym are corroborating diagnostics, not substitutes for a valid correlation identity.

The identity decision is persisted on the import run with raw/normalized identity details. Non-matched runs are quarantined and cannot expose accept actions for questionnaire candidates.

*(Architect note: the five-value `IdentityDecision` enum is verified at `source_identity.py:8-15`. The gate itself is sound; the defect traced in Section 0.1 is in the caller's value-extraction step, not in this comparison logic.)*

### 2.4 UAQ CSV import

File:

- `src/migration_intake/imports/uaq_sheet.py`

Current behavior:

- Parses the UAQ CSV as the logical `UAQ` source.
- Retains `Correlation ID`, `App name`, and `App Acronym` as identity metadata.
- Uses only reviewed exact mappings from `UAQ_COLUMN_MAP`.
- Populated fields without approved mappings become durable `UNMAPPED_FIELD` findings.
- Blank values are skipped; blanks do not infer `No`, `Complete`, or any other answer.
- Candidates are validated against the intake's pinned catalog and response-type registry before persistence.
- Unknown targets, incompatible response values, and unparseable values become findings rather than candidates.
- Raw and normalized values, response schema version, source locator, scope, and provenance are retained where available.

Important limitation:

- The current reviewed mapping is intentionally narrow. Many UAQ columns will produce `UNMAPPED_FIELD` findings until their semantic mappings are reviewed and added. Do not solve this by guessing question codes from column names.

### 2.5 Interface Tracking Excel import

File:

- `src/migration_intake/imports/interface_tracking_v1.py`

Recognized sheets:

- `Migrating App Data`
- `Interfaces`
- `Contact & Data Impact`
- `Scan Data`

Intentionally ignored:

- `Sample Interface Data`
- `Read Me`

*(Architect note: sheet allow-list and ignore-list verified verbatim in `interface_tracking_v1.py:9-11`.)*

Current behavior:

- `Migrating App Data` is used for application identity and scoped application evidence.
- `Interfaces` produces directional interface records and interface-scoped candidates/evidence.
- `Contact & Data Impact` is retained as counterparty-scoped evidence only.
- `Scan Data` is retained as observation-scoped evidence only.
- Sample/read-me sheets produce informational ignored-sheet findings and do not become application answers.
- Valid interface rows retain direction, endpoint, current protocol, current port, target protocol, target port, raw row values, and source sheet/row locators.
- Valid interface rows may produce `INT-001 = IN_PROGRESS`.
- Interface change detail may produce `INT-002 = IN_PROGRESS`.
- Missing owner commitment, funding, connectivity test, or UAT produces governance findings; it does not produce completion.
- Missing connectivity/UAT status produces `MIG-005_TEST_STATUS_GAP` findings; it does not claim test completion.
- `NET-006`, `SEC-006`, and some additional predicates remain intentionally disabled until exact reviewed source headers and value vocabularies are confirmed.

### 2.6 Versioned mapping artifacts

Files:

- `src/migration_intake/imports/mappings/uaq-v1.yaml`
- `src/migration_intake/imports/mappings/interface-tracking-facet-v1.yaml`

These mappings are the governance boundary. A future mapping change should be versioned and tested. Do not silently change the meaning of an existing mapping version.

*(Architect note: this is exactly why the Section 0.1 fix, if the real export turns out to be key/value-shaped, belongs here rather than as an inline conditional in `workbook.py`.)*

### 2.7 Workbook orchestration and persistence

Primary service:

- `src/migration_intake/application/services/workbook.py`

The service now:

1. Validates evidence ownership.
2. Checks import idempotency where applicable.
3. Parses CSV/XLSX content into logical sheets.
4. Detects UAQ and Interface Tracking source contracts.
5. Performs source identity comparison before reviewable candidate persistence.
6. Persists import runs, sheet results, findings, candidates, raw values, normalized values, scopes, locators, and parser/contract metadata.
7. Quarantines identity-invalid runs and suppresses answer-target candidates.
8. Keeps non-answer interface/register and scoped evidence distinct from application questionnaire answers.

Relevant persistence contracts:

- `src/migration_intake/persistence/models_imports.py`
- `src/migration_intake/persistence/models_candidates.py`
- `src/migration_intake/persistence/repositories/imports.py`
- `src/migration_intake/persistence/repositories/candidates.py`
- `src/migration_intake/persistence/repositories/evidence.py`

### 2.8 Coverage and candidate review UI

Coverage service:

- `src/migration_intake/application/services/import_coverage.py`

Routes:

- `GET /applications/{app_id}/intakes/{intake_id}/sources`
- `POST /applications/{app_id}/intakes/{intake_id}/evidence`
- `POST /applications/{app_id}/intakes/{intake_id}/evidence/{evidence_id}/process-workbook`
- `GET /applications/{app_id}/intakes/{intake_id}/imports/{run_id}`
- `GET /applications/{app_id}/intakes/{intake_id}/imports/{run_id}/coverage`
- `GET /applications/{app_id}/intakes/{intake_id}/imports/{run_id}/diagnostics.csv`

The coverage page reports:

- Identity decision.
- Required question count.
- Proposed question count.
- Remaining required count.
- Candidate state counts.
- Finding counts.
- Candidate raw value, normalized value, scope, validation, and evidence locator.

Review actions:

- Accept.
- Reject with reason.
- Defer with reason.

All review actions validate application/intake/run ownership, CSRF, identity approval, candidate state, and candidate row version. Acceptance delegates to `CandidateService` and `AnswerService`, creates the canonical answer revision, and links evidence provenance.

*(Architect note: see Section 0.2 — these routes validate CSRF and ownership but do not call `require_capability`. In a single-actor local deployment this is low risk; it becomes a real gap the moment a second actor role is introduced.)*

### 2.9 Questionnaire integration

Files:

- `src/migration_intake/application/queries.py`
- `src/migration_intake/web/templates/questionnaire/section.html`

The questionnaire read model aggregates candidates for displayed questions. Pending proposals are shown as review indicators and links to import coverage. Proposed values do not populate `current_answer`. Only accepted candidates become canonical answers.

### 2.10 Gap Workbook export/reimport

Files:

- `src/migration_intake/application/services/gap_workbook.py`
- `src/migration_intake/web/routes/gap_workbook.py`

Export route:

- `GET /applications/{app_id}/intakes/{intake_id}/gap-workbook.xlsx`

Reimport route:

- `POST /applications/{app_id}/intakes/{intake_id}/gap-workbook/reimport`

Export behavior:

- Uses the intake's pinned catalog.
- Includes unresolved active required questions.
- Includes application ID, intake ID, catalog release ID, catalog version, response schema version, question code/text, response type, allowed values/unit metadata, approved answer summary, row-version token, and blank response column.
- Does not treat mutable candidates as approved answers.
- Escapes formula-like cell text.

Reimport behavior:

- Requires multipart `_csrf_token`.
- Validates workbook header/schema.
- Validates application and intake identity.
- Validates pinned catalog release and semantic version.
- Validates active required question target.
- Validates current row-version token to reject stale workbooks.
- Creates provenance evidence metadata and an import run.
- Creates `PROPOSED` candidates only.
- Never writes canonical answers directly.

The current reimport endpoint is an API-style endpoint returning JSON. It is not yet integrated into the Evidence Sources page as a user-facing upload action.

*(Architect note: confirmed directly by reading `src/migration_intake/web/routes/gap_workbook.py`. The export route (`GET .../gap-workbook.xlsx`) has no CSRF requirement — expected for a GET — but also no ownership/capability check of any kind; it will serve the workbook for any `app_id`/`intake_id` pair that resolves. Treat this as part of the Section 0.2 authorization backlog, not a separate defect.)*

---

## 3. Current Known Live Issue

### Interface Tracking run is quarantined as `APPLICATION_ID_MISSING`

Observed on the local deployed application:

- Import detail displayed `APPLICATION_ID_MISSING`.
- Interface rows and governance findings were retained.
- No reviewable questionnaire candidates were exposed because the run was quarantined.
- `Sample Interface Data` was correctly ignored.
- `Contact & Data Impact` and `Scan Data` were correctly retained as scoped evidence only.
- Governance warnings for incomplete interface fields were expected and correct.

The import detail showed findings equivalent to:

- `ERROR: APPLICATION_ID_MISSING`
- `INFO: IGNORED_SHEET` for `Sample Interface Data`
- `WARNING: GOVERNANCE_FIELD_MISSING` for interface rows
- `INFO: SCOPED_EVIDENCE_ONLY` for `Contact & Data Impact`
- `INFO: SCOPED_EVIDENCE_ONLY` for `Scan Data`

Do not simply suppress the error or infer identity from application name/acronym. Reproduce the issue with a synthetic workbook and inspect:

1. Whether the workbook has a `Migrating App Data` sheet.
2. Whether the identity field is exactly `Correlation ID` after header normalization.
3. Whether the workbook parser preserves the sheet name and first-row keys.
4. Whether the selected application's correlation identifier exists in `app_identifiers` with identifier type `CORRELATION` or `Correlation`.
5. Whether `WorkbookService._source_identity_values()` recognizes the extracted sheet and field.
6. Whether source identity is being read from a key/value-shaped sheet rather than a row-shaped sheet.

**Architect verification of the above list:** items 1-4 still require reproduction against the actual FACET export, since they depend on data this session did not have access to. Items 5 and 6 are now answered by code inspection — see Section 0.1. `_source_identity_values()` (`workbook.py:578-596`) reads only `rows[0]` looking for a column-header key normalizing to `correlationid`/`migratingappcorrelationid`; it has no branch for a key/value-shaped sheet at all. If the real or synthetic workbook is key/value-shaped, this function is the confirmed point of failure, not merely a suspect.

Expected fix options, in order:

- Correct the synthetic/local test workbook to contain the reviewed identity field and matching identifier.
- If the real FACET workbook uses a different but approved header shape, update the reviewed adapter mapping and add a regression fixture/test.
- Do not weaken the deterministic identity gate.

The next developer should create a synthetic workbook fixture with a matching correlation ID and prove:

- `APPLICATION_MATCHED`.
- Candidate persistence is enabled.
- Coverage exposes accept actions only for application-scoped question candidates.
- A mismatched workbook remains quarantined.

---

## 4. Exact Local Deployment Steps

Run all commands from:

```powershell
Set-Location C:\Ash_data\Projects\aws_diag_v4
```

*(Architect note: original document used `C:\GitHub\aws_diag_v4`; this session's working directory is `C:\Ash_data\Projects\aws_diag_v4`. Adjust the path to wherever your clone actually lives — the commands below are otherwise unchanged.)*

### 4.1 Install dependencies

Use the project environment. If dependencies are not installed:

```powershell
python -m pip install -e ".[dev]"
```

### 4.2 Configure local environment

Use a local SQLite database and local evidence root. A PowerShell session can use:

```powershell
$env:DATABASE_URL = "sqlite:///C:/Ash_data/Projects/aws_diag_v4/local.db"
$env:EVIDENCE_ROOT = "C:/Ash_data/Projects/aws_diag_v4/evidence"
$env:ACTOR_ID = "7c33e0c5-7c12-48ea-8588-4f08e46340b9"
$env:CSRF_SECRET = "local-dev-test-secret"
$env:APP_ENV = "local"
```

Do not commit secrets. The shown CSRF value is for local development only.

Create storage if necessary:

```powershell
New-Item -ItemType Directory -Force evidence
```

### 4.3 Apply migrations and publish catalog

```powershell
python -m alembic upgrade head
migration-intake-bootstrap-catalog
```

Both commands were verified successfully against `local.db` during the original handoff cycle.

### 4.4 Start the server

```powershell
python -m uvicorn migration_intake.main:get_app --factory --host 127.0.0.1 --port 8000 --reload
```

Expected output:

```text
Uvicorn running on http://127.0.0.1:8000
Application startup complete.
```

If port 8000 is unavailable:

```powershell
python -m uvicorn migration_intake.main:get_app --factory --host 127.0.0.1 --port 8001 --reload
```

Update browser URLs accordingly.

### 4.5 Verify deployment

In another PowerShell terminal:

```powershell
Invoke-WebRequest http://127.0.0.1:8000/health/live
Invoke-WebRequest http://127.0.0.1:8000/health/ready
```

Expected readiness response:

```json
{
  "status": "ready",
  "checks": {
    "database": {"ok": true},
    "schema": {"ok": true},
    "storage": {"ok": true},
    "catalog": {"ok": true}
  }
}
```

Open:

```text
http://127.0.0.1:8000/applications
```

### 4.6 Reset local state when a clean run is required

Only do this when local data can be discarded:

```powershell
Remove-Item local.db -Force -ErrorAction SilentlyContinue
Remove-Item -Recurse evidence -Force -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force evidence
python -m alembic upgrade head
migration-intake-bootstrap-catalog
```

Do not delete databases or evidence in shared environments without confirmation.

---

## 5. Manual End-to-End Test Procedure

### 5.1 Create or select an application

1. Open `/applications`.
2. Create or select an application.
3. Ensure it has a correlation identifier of the correct type.
4. Open or create an active intake pinned to the published catalog.
5. Navigate to **Evidence Sources**.

### 5.2 Upload and process UAQ

1. Select the UAQ CSV in the upload form.
2. Click **Upload**.
3. In the Sources table, click **Process** for the uploaded file.
4. Open **View import**.
5. Open **Review extracted data**.
6. Confirm the identity verdict is `APPLICATION_MATCHED`.
7. Review candidate raw values, normalized values, scopes, validation, and source locators.
8. Accept valid application-scoped question candidates.
9. Reject or defer questionable candidates with a reason.
10. Open Questionnaire and verify only accepted candidates appear as current answers.

Expected behavior:

- Invalid/missing/mismatched identity quarantines the run.
- Unmapped populated UAQ fields become findings.
- Blank values do not create false answers.
- Pending candidates do not appear as canonical answers.

### 5.3 Upload and process Interface Tracking

1. Return to Evidence Sources.
2. Upload the Interface Tracking `.xlsx` file.
3. Click **Process**.
4. Open **View import**.
5. Confirm the expected sheet result is shown as `Interface Tracking`.
6. Confirm identity is `APPLICATION_MATCHED` before attempting review.
7. Review interface records, scope, direction, endpoint, protocol, port, and locator data.
8. Review governance and test-status findings.
9. Accept only application-scoped questionnaire candidates that are eligible and semantically correct.
10. Keep interface/register and counterparty/observation evidence scoped correctly.

Expected findings are not necessarily defects:

- Missing commitment/funding/connectivity/UAT fields should produce warnings.
- `Sample Interface Data` should be ignored.
- `Contact & Data Impact` and `Scan Data` should remain scoped evidence.
- Blank governance fields must not produce completion claims.

### 5.4 Test Gap Workbook flow

1. Call the export route for an intake:
   - `GET /applications/{app_id}/intakes/{intake_id}/gap-workbook.xlsx`
2. Open the workbook and populate one or more `Response` cells.
3. Preserve all identity, catalog, schema, and row-version columns.
4. Submit the workbook to:
   - `POST /applications/{app_id}/intakes/{intake_id}/gap-workbook/reimport`
5. Include `_csrf_token` in the multipart form.
6. Confirm JSON returns an import run ID and candidate count.
7. Open the returned import coverage route.
8. Confirm candidates are `PROPOSED` and canonical answers are unchanged.
9. Accept through the normal candidate review path.

Do not manually alter catalog release, catalog version, question code, schema version, or row-version columns during testing except in explicit negative tests.

---

## 6. Validation Commands

### 6.1 Focused current checks

```powershell
python -m pytest tests/integration/web/test_readiness_routes.py -q -k gap_workbook --tb=short
python -m ruff check src/migration_intake/application/services/gap_workbook.py src/migration_intake/web/routes/gap_workbook.py
git diff --check
```

Expected at the committed baseline:

- 3 Gap Workbook tests pass.
- Ruff passes for the two production files.
- Diff check passes.

*(Architect note: verified — the gap-workbook tests live in `tests/integration/web/test_readiness_routes.py`, matching this command exactly, and both production files exist as named.)*

### 6.2 Import-focused checks

```powershell
python -m pytest tests/unit/imports/ -q
python -m pytest tests/unit/application/test_workbook_service.py -q
python -m pytest tests/integration/web/test_evidence_routes.py -q
python -m pytest tests/integration/web/test_questionnaire_routes.py -q
```

### 6.3 Migration/catalog checks

```powershell
python -m alembic upgrade head
migration-intake-bootstrap-catalog
python -m pytest tests/integration/migrations/test_env_dotenv_fallback.py tests/integration/test_catalog_bootstrap.py -q
```

### 6.4 Broader verification before release

```powershell
python -m pytest tests/ -q
python -m ruff check src/ tests/
python -m mypy src/migration_intake
```

The full-suite number in older handoff documents is not authoritative. Use the current command output as the source of truth. As of this review, `STATE.md` records `1787 passed, 1 skipped` at the same `ac4adf8` baseline — treat that as the last known-good number, not a guarantee for your working tree.

### 6.5 Browser validation

If Playwright/browser dependencies are available:

```powershell
python -m pytest tests/browser/ -v -m browser
```

*(Architect note: `tests/browser/` does not exist yet in this working tree. This is a suite to be created, not a suite to be run and checked — see Section 0.3.)*

---

## 7. Prioritized Remaining Work

### P0 - Reproduce and fix current Interface Tracking identity behavior

This is the immediate next task because a real local import currently shows `APPLICATION_ID_MISSING`. Start with the narrow unit test against `_source_identity_values()` described in Section 0.1 before building a full synthetic workbook.

Acceptance criteria:

- Synthetic workbook with matching `Migrating App Data` correlation identity returns `APPLICATION_MATCHED`.
- Matching run persists eligible candidates.
- Missing identity remains quarantined.
- Mismatched identity remains quarantined.
- Conflicting UAQ/workbook identities return `SOURCE_ID_CONFLICT`.
- Coverage page shows review controls only for approved identity runs.

Likely files:

- `src/migration_intake/application/services/workbook.py`
- `src/migration_intake/imports/interface_tracking_v1.py`
- `src/migration_intake/imports/source_identity.py`
- `tests/unit/application/test_workbook_service.py`
- `tests/unit/imports/test_interface_tracking_v1.py`
- `tests/integration/web/test_evidence_routes.py`

### P0 - Add an executable synthetic end-to-end import fixture

Add synthetic UAQ and Interface Tracking fixtures under tests only. Do not use private `_data` files.

The fixture must prove:

- Application identifier setup.
- Intake pinned catalog.
- Evidence upload.
- Processing.
- Identity match.
- Candidate persistence.
- Coverage display.
- Candidate acceptance.
- Canonical questionnaire revision creation.
- Evidence linkage.
- Questionnaire display after acceptance.

### P1 - Wire authorization capability checks into routes (new — see Section 0.2)

`require_capability()`/`has_capability()` exist and are unit-tested but are not called from any route in `src/migration_intake/web/routes/`. Add capability checks to:

- Evidence upload/process routes.
- Candidate accept/reject/defer routes.
- Gap Workbook export and reimport routes.

Add integration tests proving a missing capability returns 403, distinct from the existing CSRF/ownership tests. Decide and document whether this is genuinely deferred for the single-actor local phase, or whether it should land before the next release gate.

### P1 - Browser release journey

Create or complete `tests/browser/test_intake_journey.py` (directory does not exist yet — scaffold it) covering:

1. Create/select application.
2. Create/resume intake.
3. Upload/process synthetic UAQ.
4. Confirm coverage/proposed/remaining counts.
5. Accept one valid candidate.
6. Verify Questionnaire after reload.
7. Upload/process synthetic Interface Tracking.
8. Confirm interface candidates and governance findings.
9. Verify mismatch upload is quarantined and cannot expose accept actions.
10. Run desktop and narrow-mobile checks:
    - No 500 responses.
    - No console errors.
    - No failed first-party assets.
    - No page-level horizontal overflow.

### P1 - Integrate Gap Workbook reimport into user-facing UI

The API endpoint exists, but Evidence Sources does not yet offer a visible reimport/upload action. Decide whether to:

- Add a dedicated Gap Workbook section/form to the Sources page.
- Add a separate controlled route/page.
- Keep the API route internal and document an operational CLI flow.

Preferred direction: add a visible controlled form with CSRF and clear identity/catalog/staleness error messages. Do not make it look like direct answer import. While doing this, close the export-route authorization gap noted in Section 0.2/2.10 — the export route currently has no ownership or capability check at all.

### P1 - Add negative security and concurrency coverage

Add tests for:

- Invalid/missing CSRF on reimport.
- Wrong application ID.
- Wrong intake ID.
- Wrong catalog release ID.
- Wrong catalog semantic version.
- Wrong schema version.
- Unknown/inactive/non-required question code.
- Stale row version.
- Duplicate reimport behavior.
- Oversized/malformed workbook.
- Formula-like workbook values.
- Import candidate from one intake used against another intake.
- Accept candidate after another reviewer changes its row version.
- Missing-capability access to evidence/candidate/gap-workbook routes (see new P1 item above).

### P1 - Full regression and type quality

Run and resolve relevant failures from:

```powershell
python -m pytest tests/ -q
python -m ruff check src/ tests/
python -m mypy src/migration_intake
```

Do not hide unrelated pre-existing defects. Record them separately in the handoff/state file.

### P2 - Complete reviewed mappings and catalog metadata

- Persist allowed-value metadata in the catalog model/compiler if strict allowed-value validation is required.
- Expand UAQ mapping only from approved semantic mappings.
- Confirm exact source headers/value vocabularies for `NET-006`, `SEC-006`, and remaining disabled predicates.
- Add explicit mapping/version tests for each new predicate.

### P2 - Operational hardening

- Confirm evidence storage path behavior for clean and existing databases.
- Add structured import logging and correlation IDs where missing.
- Document database backup/reset behavior.
- Confirm no credentials or private evidence are committed.
- Add CI commands for migrations, unit/integration tests, lint, and type checking.
- Validate Oracle compatibility after the SQLite slice is stable.

---

## 8. Recommended Next Work Sequence

See the revised sequence in Section 0.4, which supersedes the list below by inserting a narrow unit-test step before the full synthetic fixture and by adding the capability-wiring step. Original sequence, retained for reference:

1. Deploy clean local database and catalog using Section 4.
2. Reproduce the current Interface Tracking `APPLICATION_ID_MISSING` run with synthetic data.
3. Fix/validate identity extraction and add regression tests.
4. Add a synthetic matched end-to-end integration test for UAQ.
5. Add a synthetic matched end-to-end integration test for Interface Tracking.
6. Run the full import/evidence/questionnaire focused suites.
7. Add visible Gap Workbook reimport UI if the workflow is intended for business users.
8. Add Playwright release-journey coverage.
9. Run full tests, Ruff, and mypy.
10. Update `STATE.md` and this handoff with exact outputs.
11. Commit and push only after review of the final diff and test output.

---

## 9. Current Git and Commit Details

At the original handoff creation:

```text
HEAD: ac4adf8 Add UAQ and interface tracking import workflow
Branch: ag1766_diagr_v4
Remote tracking: origin/ag1766_diagr_v4
Working tree: clean before adding this handoff document
```

The commit included 42 files, approximately 3,213 insertions, and 143 deletions. It included the import plan, catalog bootstrap, mapping artifacts, migrations, import adapters, workbook orchestration updates, coverage service, Gap Workbook service/routes, UI route changes, and focused tests.

This architect review was performed against the same `ac4adf8` baseline; no source changes were made as part of the review. The next owner should verify `git status --short` and commit this document separately, or fold it into the next reviewed change, per the team's commit policy.

---

## 10. Architecture Rules the Next Owner Must Preserve

1. Importers and AI create candidates; they never approve canonical answers.
2. Missing values remain missing; never infer `No` or completion from absence.
3. Conflicts remain visible and require authorized resolution.
4. Compare only like-for-like facts and preserve scope.
5. Every candidate retains application, intake, evidence, import-run, raw value, normalized value, scope, locator, parser/mapping/version, confidence, and review state where applicable.
6. Routes orchestrate; services enforce use cases; repositories persist; templates render view models.
7. Every child resource is checked against application and intake ownership.
8. Catalog releases are immutable and intakes use a pinned release.
9. Canonical answers are append-only revisions and accepted candidates retain evidence linkage.
10. Renderer/export consumers use approved immutable snapshots, not mutable live proposals.
11. Use synthetic fixtures only. Never copy private `_data` evidence into tests, logs, screenshots, prompts, or committed artifacts.
12. Do not weaken identity gates merely to make a local workbook pass.
13. *(Architect addition)* Ownership checks are not a substitute for capability checks. Section 0.2 shows both were assumed to be enforced together; they must be verified as two independent gates before any multi-actor deployment.

---

## 11. Suggested Email Handoff

Subject: Handoff - UAQ and Interface Tracking Import Workflow - Architect Review of Commit ac4adf8

Team,

The UAQ and Interface Tracking import workflow implemented in commit `ac4adf8` on branch `ag1766_diagr_v4` has been reviewed against the current source tree. The operational handoff from 2026-09-09 is accurate — file paths, routes, migrations, and test locations all check out — and its architecture is sound: importers only ever produce reviewable candidates, never canonical answers, and identity mismatches are quarantined rather than guessed at.

Two things changed as a result of this review:

1. The open `APPLICATION_ID_MISSING` defect now has a confirmed leading cause: `WorkbookService._source_identity_values()` (`src/migration_intake/application/services/workbook.py:578`) only reads the first row of a sheet looking for a `Correlation ID` column header. If the real `Migrating App Data` export is a key/value-shaped sheet instead of one row per application, this function will never find the identity value. Confirm the actual export shape with a narrow unit test before building the full synthetic end-to-end fixture — it's a much faster way to close this out.
2. The capability/authorization system (`require_capability`/`has_capability` in `web/security.py`) is implemented and unit-tested but is not called from any route. Evidence, candidate-decision, and Gap Workbook routes currently enforce ownership and CSRF but not capability. This is likely fine for the current single-actor local phase but should be an explicit, tracked decision rather than an implicit gap, and should be closed before any multi-actor deployment.

Please deploy locally first using:

```powershell
Set-Location C:\Ash_data\Projects\aws_diag_v4
$env:DATABASE_URL = "sqlite:///C:/Ash_data/Projects/aws_diag_v4/local.db"
$env:EVIDENCE_ROOT = "C:/Ash_data/Projects/aws_diag_v4/evidence"
$env:ACTOR_ID = "7c33e0c5-7c12-48ea-8588-4f08e46340b9"
$env:CSRF_SECRET = "local-dev-test-secret"
$env:APP_ENV = "local"
python -m alembic upgrade head
migration-intake-bootstrap-catalog
python -m uvicorn migration_intake.main:get_app --factory --host 127.0.0.1 --port 8000 --reload
```

Then verify `/health/ready`, create/select an application with a correlation identifier, open an active intake, upload/process synthetic UAQ and Interface Tracking files, review coverage, accept one candidate, and verify the accepted value in Questionnaire.

Remaining work is release hardening: the identity-extraction fix and matched synthetic end-to-end tests, capability wiring into routes, browser/Playwright journey coverage (suite to be scaffolded from scratch under `tests/browser/`), user-facing Gap Workbook reimport UI, negative security/concurrency tests, full-suite/Ruff/mypy verification, and reviewed mappings/catalog metadata for currently disabled predicates such as `NET-006` and `SEC-006`.

The governing rules are candidate-first persistence, no inferred answers from blanks, explicit conflict preservation, immutable catalog/snapshot boundaries, synthetic-only test fixtures, and — as of this review — treating ownership checks and capability checks as two separate, independently-verified gates.
