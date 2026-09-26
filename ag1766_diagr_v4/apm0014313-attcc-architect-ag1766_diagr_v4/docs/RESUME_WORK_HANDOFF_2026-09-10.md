# Resume Work Brief

**Date:** 2026-09-10  
**Repository:** `C:\Users\ak521y\OneDrive - AT&T Services, Inc\Documents\Commision\Workspace\ADS\apm0014313-attcc-architect`  
**Branch:** `ag1766_diagr_v4`  
**Current baseline:** `ac4adf8` - `Add UAQ and interface tracking import workflow`  
**Remote:** `origin/ag1766_diagr_v4`

## Purpose

This document consolidates the teammate handoff with the current repository state so work can resume without replaying completed implementation waves.

`STATE.md` is the repository status authority. The supplied teammate handoff is the feature-specific authority for the UAQ and Interface Tracking import work. Where they differ, use the current code and focused test output as the final authority.

## Completed

### Repository and platform foundation

- FastAPI application composition, SQLAlchemy persistence, Alembic migrations, SQLite local execution, health/readiness checks, evidence storage, and server-rendered UI are implemented.
- The production foundation milestones through R5 are recorded complete in `STATE.md`.
- The packaged catalog artifact is `src/migration_intake/catalog/data/catalog-0.2.0.csv`.
- Catalog publication is explicit and idempotent through `migration-intake-bootstrap-catalog`.
- Migrations `0007`, `0008`, `0009`, and `0010` reconcile catalog metadata, historical answer metadata, and import identity fields.
- Questionnaire, evidence, candidate review, readiness, immutable snapshot, and canonical export slices are implemented.

### UAQ and Interface Tracking import slice

- Deterministic source identity decisions are implemented: `APPLICATION_MATCHED`, `APPLICATION_ID_MISSING`, `APPLICATION_MISMATCH`, `AMBIGUOUS_APPLICATION_MATCH`, and `SOURCE_ID_CONFLICT`.
- UAQ CSV parsing preserves identity metadata, uses reviewed mappings, validates candidates against the pinned catalog and response registry, and records unmapped or invalid values as findings.
- Interface Tracking recognizes `Migrating App Data`, `Interfaces`, `Contact & Data Impact`, and `Scan Data`.
- `Sample Interface Data` and `Read Me` are intentionally ignored with findings.
- Interface records retain direction, endpoint, protocols, ports, raw row data, scope, and source locators.
- Implemented predicate behavior includes `INT-001`, `INT-002`, governance-gap findings, and test-status-gap findings. `NET-006`, `SEC-006`, and other unreviewed predicates remain disabled.
- Workbook orchestration persists import runs, sheet results, findings, candidates, raw/normalized values, scopes, locators, and parser/mapping metadata.
- Candidates remain `PROPOSED` until an authorized reviewer accepts them. Accepted candidates become canonical answer revisions through `CandidateService` and `AnswerService`; rejected/deferred candidates do not change canonical answers.
- Import coverage shows identity, required/proposed/remaining counts, candidate states, findings, raw and normalized values, validation, scope, and source locator.
- Questionnaire pages show pending candidate indicators without treating proposals as canonical answers.
- Gap Workbook export/reimport is implemented as a candidate-only flow with catalog, schema, identity, and row-version validation; reimport does not write canonical answers directly.

### Verification already reported

- Focused workbook/import, candidate lifecycle, coverage, and Gap Workbook checks passed during the handoff cycle.
- Alembic upgrade and catalog bootstrap were verified against a local SQLite database.
- The branch was clean at `ac4adf8` when this brief was created.

## Pending

### P0: Resolve and prove Interface Tracking identity

The known live defect is an Interface Tracking run quarantined as `APPLICATION_ID_MISSING`.

Reproduce with a synthetic workbook and inspect, in order:

1. `Migrating App Data` sheet presence and preserved sheet name.
2. Header normalization and exact `Correlation ID` extraction.
3. Whether the sheet is row-shaped or key/value-shaped.
4. The selected application's `app_identifiers` row and identifier type (`CORRELATION`/`Correlation`).
5. `WorkbookService._source_identity_values()` and Interface Tracking adapter output.

Required regression cases:

- Matching correlation ID produces `APPLICATION_MATCHED` and persists eligible candidates.
- Missing, mismatched, and ambiguous identity values remain quarantined.
- Conflicting UAQ and Interface Tracking IDs produce `SOURCE_ID_CONFLICT`.
- Quarantined runs expose no candidate acceptance controls.

Do not weaken the deterministic identity gate or infer identity from application name/acronym.

### P0: Add executable synthetic end-to-end coverage

Add tests using synthetic fixtures only. The flow must prove application and intake setup, catalog pinning, evidence upload, workbook processing, identity match, candidate persistence, coverage rendering, candidate acceptance, canonical revision creation, evidence linkage, and questionnaire display after acceptance.

Cover both UAQ CSV and Interface Tracking XLSX. Keep fixtures under `tests/`; never copy private `_data` evidence.

### P1: Browser release journey

Implement or complete `tests/browser/test_intake_journey.py` and responsive checks for Applications, Questionnaire, Evidence/import coverage, candidate review, WaveUtil, and readiness/snapshot pages.

The browser gate should use an isolated migrated SQLite database, publish the packaged catalog, create synthetic records, and verify no 500 responses, console errors, failed first-party assets, overlap, or page-level horizontal overflow at desktop and narrow-mobile sizes.

### P1: Security and concurrency hardening

Complete or broaden coverage for CSRF, application/intake ownership, capability checks, escaping, bounded uploads/pagination, security headers, safe exception mapping, stale candidate acceptance, and cross-intake/cross-catalog misuse.

### P1: User-facing Gap Workbook reimport

The API endpoint exists, but the Evidence Sources page still needs a controlled user-facing reimport workflow, or an explicit operational decision to keep the endpoint internal. The preferred implementation is a visible CSRF-protected form with clear catalog, identity, schema, and stale-workbook errors.

### P1: Release verification and documentation

Run and record current results for:

```powershell
python -m pytest tests/ -q
python -m ruff check src/ tests/
python -m mypy src/migration_intake
```

Update `STATE.md` after a meaningful implementation slice. Record unrelated pre-existing failures separately instead of masking them.

### P2: Reviewed mappings and operations

- Expand UAQ mappings only after semantic review.
- Confirm exact source headers and vocabularies before enabling `NET-006`, `SEC-006`, or other deferred predicates.
- Add structured import correlation logging and operational recovery/backup documentation.
- Validate Oracle compatibility after the SQLite slice is stable.
- Keep Topology, ADS, and DDD renderers deferred until they consume immutable approved snapshots.

## Recommended first session

1. Configure a disposable local SQLite database and evidence root.
2. Run `python -m alembic upgrade head`.
3. Run `migration-intake-bootstrap-catalog`.
4. Create a synthetic application with a correlation identifier and an active catalog-pinned intake.
5. Build the smallest synthetic Interface Tracking workbook with a matching `Migrating App Data` `Correlation ID`.
6. Run the focused adapter/workbook/evidence tests before changing production code.
7. Fix the smallest identity extraction defect, if reproduced, and add the matching/missing/mismatch/conflict regression tests.
8. Run the focused suite again, then add the matched end-to-end flow.
9. Only after the import path is green, proceed to browser and security release work.

## Local setup

Run from the repository root:

```powershell
$env:DATABASE_URL = "sqlite:///C:/path/to/repository/local.db"
$env:EVIDENCE_ROOT = "C:/path/to/repository/evidence"
$env:ACTOR_ID = "7c33e0c5-7c12-48ea-8588-4f08e46340b9"
$env:CSRF_SECRET = "local-dev-test-secret"
$env:APP_ENV = "local"
python -m alembic upgrade head
migration-intake-bootstrap-catalog
python -m uvicorn migration_intake.main:get_app --factory --host 127.0.0.1 --port 8000 --reload
```

Use a disposable local path and do not commit local databases, evidence, credentials, or client data.

## Guardrails

- Importers and runtime AI create candidates, never approved facts.
- Blank values never imply `No`, completion, or test success.
- Conflicts remain visible and require an authorized decision.
- Compare only like-for-like scoped facts.
- Routes orchestrate; services enforce use cases; repositories persist; templates render view models.
- Every child resource must be authorized through application and intake ownership.
- Use synthetic fixtures only.
