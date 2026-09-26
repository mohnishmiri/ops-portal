# UAQ and Interface Tracking Import Plan

**Status:** Proposed implementation handoff

**Scope:** Import a UAQ CSV and an Interface Tracking workbook for one application intake. Extract deterministic, scoped candidates; allow authorized reviewers to apply valid candidates to canonical questionnaire answers; preserve all evidence and ambiguity.

## 1. Goal

The initial intake workflow should begin with evidence rather than manual data entry:

1. A user opens an application workspace and its open intake.
2. The user uploads a UAQ export and/or Interface Tracking workbook.
3. The service validates that each file applies to the selected application.
4. Deterministic adapters extract facts as candidate proposals.
5. The UI shows coverage, proposed answers, conflicts, unmapped fields, and remaining work.
6. An authorized reviewer accepts, edits-and-accepts, rejects, or defers each proposal.
7. The questionnaire shows accepted answers and leaves unresolved questions for manual completion.

The result is a faster intake without allowing a spreadsheet, an importer, or AI to approve facts.

## 2. Explicit Non-Goals

- Do not write an imported value directly to a canonical answer.
- Do not infer `NO`, `NOT_APPLICABLE`, `COMPLETE`, or a target-state decision from a blank, `N/A`, unknown, or absent value.
- Do not treat source relevance as an answer. A file may support a question without completing it.
- Do not convert interface rows into facts about the migrating application when they describe a counterpart application.
- Do not import the workbook's `Sample Interface Data` sheet.
- Do not use `_data` files as test fixtures, package data, screenshots, or CI inputs.
- Do not add runtime AI to v1 of this capability.

## 3. Example Assumption and Identity Rule

For the requested test run, treat the UAQ, Interface Tracking workbook, and application as the same application after the UAQ correlation ID is corrected. The production behavior must still validate that conclusion.

### 3.1 Identity Sources

| File | Authoritative identity fields to read |
|---|---|
| UAQ CSV | `Correlation ID`, `App name`, `App Acronym` |
| Interface Tracking workbook | `Migrating App Data` rows for Correlation ID, Application Acronym, Name; `Interfaces` rows for Migrating App Correlation ID and Acronym |

### 3.2 Identity Decision

Normalize IDs using the existing identifier normalization policy. Compare the source correlation ID to an `app_identifiers` record of the application being imported.

| Outcome | Behavior |
|---|---|
| One source ID matches one application identifier | Import may proceed; record `APPLICATION_MATCHED`. |
| Source ID is missing | Persist evidence but quarantine the import run as `APPLICATION_ID_MISSING`; create no answer-target candidates. |
| Source ID differs from selected application | Persist evidence but quarantine as `APPLICATION_MISMATCH`; create no answer-target candidates. |
| UAQ and workbook IDs disagree | Persist both sources; quarantine as `SOURCE_ID_CONFLICT`; require an authorized identity resolution. |
| Multiple applications match | Quarantine as `AMBIGUOUS_APPLICATION_MATCH`; require selection/resolution. |

Application acronym and display name are corroborating diagnostics, not a substitute for an unambiguous identifier. Every import run stores the raw and normalized source identity, selected application ID, comparison result, and source locators.

## 4. Observed Source Shape

The example UAQ has one application row and 217 columns. It contains inventory, application, database, storage, network, security, documentation, and migration-response fields.

The example Interface Tracking workbook contains:

| Sheet | Intended treatment |
|---|---|
| `Migrating App Data` | Key/value application evidence; candidate source for identity, criticality, data classification, customer/internet facing, and RTO/RPO. |
| `Interfaces` | Directional interface-register rows for the migrating application. |
| `Contact & Data Impact` | Counterparty-scoped contact/data classification corroboration; never silently apply to the migrating application. |
| `Scan Data` | Network-observation evidence; not a directed application-interface register. |
| `Sample Interface Data` | Ignore with an informational finding. |
| `Read Me` | Ignore. |

The example workbook has 11 populated interface rows for one migrating application. Several governance fields are empty, including interface commitment, connectivity-test, and UAT fields; the import must leave `INT-003` unresolved rather than marking it complete.

## 5. Catalog Coverage Model

The pinned catalog has 112 questions. It identifies UAQ and Interface Tracking as relevant to 72 distinct controls. That number is only an upper bound: usable coverage depends on populated source values, exact mapping, response-type compatibility, identity match, and reviewer approval.

### 5.1 Expected Coverage

| Category | Initial estimate | Treatment |
|---|---:|---|
| Direct, reviewable question proposals from UAQ and Migrating App Data | 30-40 controls | Typed candidates when exact mapping and parser validation succeed. |
| Register/evidence support from interface rows and scan observations | 15-20 controls | Candidate rows, supporting evidence, or completeness signals; not automatically answers. |
| Unresolved or decision-owned controls | Remaining controls | Questionnaire/manual workflow; retain source links where relevant. |

The first implementation must produce an exact coverage report for each run rather than relying on these estimates.

### 5.2 Initial Mapping Families

| Catalog area | Source fields | Candidate result |
|---|---|---|
| Intake/application identity | UAQ identity; Migrating App Data identity | Update only through the existing application-edit/identity process, never as a questionnaire answer. |
| Application overview | UAQ business function, contacts, operational status, environments; workbook description, criticality, customer/internet facing | Candidates for compatible `APP-*` and `CTL-*` questions. |
| Database/storage | UAQ inventory/database/storage fields | Typed candidates or scoped database/storage register proposals. |
| Network | UAQ `NET*`; interface endpoints, protocol, ports, encryption, latency, volume | Candidates for compatible question controls plus interface register rows. |
| Security/resilience | UAQ security/DR responses; Migrating App Data classifications and RTO/RPO | Typed candidates only where response schema supports the source's granularity. |
| Operations/devops/migration | UAQ documentation/application fields | Long-text, people, status, and evidence-reference proposals when exact mappings are approved. |
| Interfaces | `Interfaces` sheet | Directional normalized interface records and aggregate candidates for `INT-001`, `INT-002`, `INT-003`, `NET-006`, `SEC-006`, `MIG-005` only when their specific predicates are met. |

## 6. Mapping Governance

The existing UAQ adapter mapping is not fit for production use: it currently maps source fields to obsolete or semantically unrelated question codes. Replace it; do not patch it incrementally.

Create versioned mapping artifacts under `src/migration_intake/imports/mappings/`:

```text
uaq-v1.yaml
interface-tracking-facet-v1.yaml
```

Each mapping entry must contain:

```yaml
source:
  format: UAQ_CSV_V1
  field: "INV..."
target:
  kind: QUESTION | INTERFACE_REGISTER | APPLICATION_IDENTIFIER
  key: "APP-001"
transform: text | yes_no_unknown | people_list | controlled_pair | measurement
scope: APPLICATION | INTERFACE | COUNTERPART | OBSERVATION
blank_policy: SKIP | FINDING
placeholder_policy: SKIP | FINDING
confidence: 1.0
```

Rules:

- Mapping keys are exact approved headers after explicit whitespace/line-break normalization only.
- A mapping must target an existing question in the intake's pinned catalog and use its declared response type.
- One source field may produce multiple scoped candidates only when its transformation is explicit and tests prove the behavior.
- Source values remain raw evidence; transformed values are recorded separately.
- Unmapped populated fields become bounded informational findings, not invented question codes.
- Mapping version, source format version, catalog release ID, parser version, and transform version are persisted on every run/candidate.

## 7. Data and Service Design

### 7.1 Existing Components to Reuse

- `EvidenceService` and `FilesystemStore` for uploaded bytes and provenance.
- `WorkbookService` for run/sheet/finding/candidate persistence.
- `CandidateRepository` and `CandidateService` for proposal state and accept/reject/defer lifecycle.
- `AnswerService` for typed canonical answer revisions and concurrency.
- Published catalog read model for pinned question and response-type validation.

### 7.2 Required New Components

```text
imports/
  source_identity.py             # normalize and compare source/application identity
  uaq_v1_adapter.py              # replacement deterministic UAQ adapter
  interface_tracking_v1.py       # workbook profile and adapters by sheet
  mappings/uaq-v1.yaml
  mappings/interface-tracking-facet-v1.yaml
application/services/
  import_coverage.py             # candidate/finding/question coverage read model
web/routes/
  import_review.py               # run coverage and candidate review pages/fragments
web/templates/import_review/
  coverage.html
  candidate_list.html
  candidate_detail.html
```

Use the existing persistence types where they capture required facts. Add a migration only when the current import-run/candidate models cannot record a source identity decision, mapping version, candidate scope, or explicit disposition. Avoid duplicating an interface register as generic question JSON.

### 7.3 Candidate Contract

Every candidate created by these adapters must include:

- `target_kind` and target key.
- Application ID, intake ID, evidence item ID, and import run ID.
- Raw value and normalized/typed proposed value.
- Scope: `APPLICATION`, `INTERFACE`, `COUNTERPART`, or `OBSERVATION`.
- Source locator: sheet/file, row, column/key, and record identity where applicable.
- Parser/mapping/transform versions.
- Confidence as metadata only.
- Validation outcome: `VALID`, `INVALID`, `AMBIGUOUS`, `OUT_OF_SCOPE`, or `UNMAPPED`.
- Initial state `PROPOSED` only for valid, application-scoped, exact question mappings.

All other outcomes become findings or non-answer register proposals. Candidate acceptance must continue to call `AnswerService`; no importer writes `ans_instances` or `ans_revisions` directly.

## 8. Interface Tracking Semantics

Normalize the `Interfaces` sheet into a directional record keyed by:

```text
migrating_application_id + interface_correlation_id + direction + endpoint + current_protocol + current_port
```

Retain source values for current and target protocol/type/port independently. Target values in the source are proposals, never architecture approval.

Derive aggregate candidates only under explicit rules:

| Control | Allowed inference |
|---|---|
| `INT-001` | Propose `IN_PROGRESS` when at least one valid interface row exists; never `COMPLETE` solely from row presence. |
| `INT-002` | Propose a register-status review item when an interface has endpoint/protocol/port or impact-change information. |
| `INT-003` | No completion proposal unless every required commitment/funding/connectivity/UAT field is present and valid; otherwise create a gap finding. |
| `NET-006` | Propose `YES` only from an interface explicitly scoped to a third party/SaaS/vendor; otherwise retain rows as evidence. |
| `SEC-006` | Propose only when a mapped interface data-classification source explicitly supports it; do not infer it from an endpoint alone. |
| `MIG-005` | Surface test-status gaps; never claim test completion from blank fields. |

`Scan Data` may corroborate observed connectivity but must not create or complete interface-register records without a deterministic correlation rule approved in the mapping artifact.

## 9. User Experience

### 9.1 Sources Page

Add source type detection and a visible import summary:

- Detected contract: UAQ CSV v1 or Interface Tracking v1.
- Source identity and application-match status.
- Import state, mapping version, sheet outcomes, candidate count, conflict count, and unmapped count.
- `Review extracted data` action after processing.

Do not call this “answers imported.”

### 9.2 Import Coverage Page

Route:

```text
GET /applications/{app_id}/intakes/{intake_id}/imports/{run_id}/coverage
```

Show:

- Exact counts: mapped/proposed, accepted, rejected, deferred, invalid, ambiguous, unmapped, and remaining required questions.
- Grouping by questionnaire section and source sheet.
- Identity verdict before any review actions.
- Filters by target, question section, state, scope, validation outcome, and source field.
- A per-question comparison: canonical answer, proposed candidate(s), source locator, response-type validation result, and reviewer action.

### 9.3 Questionnaire Integration

For every question, show candidate count and evidence links. Accepted candidates render as the current answer with provenance. Proposed/conflicting candidates render as a review indicator, never as a populated answer.

### 9.4 Gap Workbook Export (Second Increment)

After import/review, offer a generated workbook containing only unresolved applicable questions. Include application ID, intake ID, catalog semantic version/release ID, question code, question text, response type, allowed values/unit, existing approved answer summary, and a row-version token. Reimport validates all tokens and returns candidates for review.

## 10. Implementation Sequence

### Packet 1: Contracts and Identity

1. Add tests for exact source identity extraction from synthetic UAQ and Interface Tracking fixtures.
2. Implement source-identity normalization/comparison service.
3. Add import-run identity decision persistence if absent.
4. Integrate identity validation before candidate persistence.

**Acceptance:** mismatch, missing, ambiguous, and source-conflict cases persist evidence/findings but create no reviewable answer candidates.

### Packet 2: UAQ Replacement Adapter

1. Define a reviewed UAQ v1 mapping artifact targeting only valid catalog controls.
2. Implement typed transformations against the pinned catalog response type.
3. Emit `UNMAPPED_FIELD`, `BLANK_VALUE`, `PLACEHOLDER_VALUE`, and `TYPE_MISMATCH` findings.
4. Retire the obsolete code-number guessing behavior.

**Acceptance:** every populated mapped field has an explicit disposition; no candidate targets a nonexistent catalog question; blank/placeholder values create no canonical proposal.

### Packet 3: Interface Tracking Adapter

1. Add workbook profile detection and explicit sheet allowlist.
2. Parse `Migrating App Data` as labeled fields; parse `Interfaces` as directional records.
3. Ignore `Sample Interface Data` and `Read Me` with findings.
4. Keep counterpart/contact and scan observations scoped and non-authoritative.
5. Add aggregate interface question candidates only under Section 8 predicates.

**Acceptance:** 11 synthetic interface rows retain direction, endpoints, protocols, ports, and locators; blank governance columns do not produce a completion claim.

### Packet 4: Coverage and Review UI

1. Add coverage query service and route/template.
2. Extend candidate UI with source scope, mapping version, parsed validation, raw/proposed diff, and evidence locator.
3. Enforce identity verdict and candidate state before actions.
4. Link Sources, import detail, coverage, candidate review, and questionnaire indicators.

**Acceptance:** accepting one valid candidate creates exactly one canonical revision with evidence linkage; rejecting/defering changes no canonical answer.

### Packet 5: Gap Workbook Export

1. Define export/reimport schema and secure workbook writer.
2. Implement prefilled unresolved-question export.
3. Implement reimport with identity, catalog, schema-version, and row-version validation.

**Acceptance:** returned data cannot target another application/intake/catalog or overwrite a newer answer; every value remains a candidate until accepted.

## 11. Test Plan

Use synthetic fixtures only. Model the observed source structures but never copy private client values.

### Unit Tests

- Header normalization and contract detection.
- Identity extraction and all decision outcomes.
- Mapping validation: target existence, response-type compatibility, and transform behavior.
- UAQ blanks/placeholders/unknowns produce no false answers.
- Interface normalization preserves directional scope and counterpart identity.
- Aggregate predicates for `INT-001`, `INT-002`, `INT-003`, `NET-006`, `SEC-006`, and `MIG-005`.

### Integration Tests

- Upload/process UAQ and Interface Tracking into an Alembic-migrated temporary database.
- Published catalog is pinned; all candidates reference that release through the intake.
- Application mismatch quarantines without reviewable answer candidates.
- Same evidence/parser/mapping/catalog is idempotent.
- A changed mapping or catalog creates a distinct, auditable run.
- Accept/edit/reject/defer transitions retain evidence lineage and obey optimistic concurrency.

### Browser Release Journey

Extend `tests/browser/test_intake_journey.py` with synthetic files:

1. Create application with matching correlation ID and intake.
2. Upload/process UAQ.
3. Verify coverage page displays proposals and unresolved counts.
4. Accept one compatible candidate and confirm it in Questionnaire after reload.
5. Upload/process Interface Tracking.
6. Verify interface candidates and gap findings; no test/UAT completion is claimed from empty source columns.
7. Verify mismatch upload is quarantined and cannot expose accept actions.
8. Run desktop and narrow mobile checks for no `500`, no console errors, no failed first-party assets, and no page-level horizontal overflow.

## 12. Commands

```powershell
python -m pytest tests/unit/imports/ tests/unit/application/test_candidate_service.py -q
python -m pytest tests/integration/application/ tests/integration/web/test_evidence_routes.py -q
python -m pytest tests/browser/test_intake_journey.py -v -m browser
python -m ruff check src/ tests/
python -m mypy src/migration_intake
```

## 13. Completion Criteria

This feature is complete only when:

- Both formats have explicit versioned mappings and identity validation.
- Every populated recognized field receives a candidate or a durable finding.
- No importer writes canonical answers directly.
- Application mismatch/conflict is visible and blocks candidate application.
- Source provenance, scope, raw value, normalized value, mapping version, and review decision are retained.
- The coverage UI reports exact answered/proposed/remaining counts for the pinned catalog.
- Synthetic integration and browser tests pass.
- The browser release command remains part of the release-candidate validation ladder.