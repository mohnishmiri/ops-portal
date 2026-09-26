# Project AWS OutPost Migration - Design and Architecture Handoff

**Updated:** 2026-09-05  
**Workspace:** `C:\GitHub\aws_diag_v4`  
**Status:** Architecture and interactive mockup are complete enough for stakeholder review; production UI implementation has not started.

## Start Here

Use these artifacts as the current sources of truth:

1. [UI implementation plan](UI_QUESTIONNAIRE_IMPLEMENTATION_PLAN.md) - detailed product scope, architecture, workflows, routes, milestones, testing, and 14 decisions that remain open.
2. [Architecture decisions](UI_ARCHITECTURE_DECISIONS.md) - eight proposed defaults and the open decisions requiring team confirmation.
3. [SQLite schema](SQLITE_SCHEMA_V0_1.sql) - executable v0.1 relational design with 46 tables and four triggers.
4. [Interactive mockup](../_data/spike/mockup/index.html) - static browser prototype supported by `app.js`, `styles.css`, and `assets/` in the same directory.
5. [Question catalog v0.2](../_data/spike/QUESTION_CATALOG_V0_2.csv) - 112 unique controls that drive the proposed questionnaire and register model.
6. [Spike state](../_data/spike/STATE.md) - concise record of completed topology and UI design work, verified facts, and current next steps.

Do not use `_data/ARCHITECTURE_HANDOFF_2026-09-04.md` as this workspace's design record. It describes a different repository named `aws_migration_factory_v3` and is retained only as background.

## Product Goal

Build an internal migration-intake application that consolidates evidence for one application assessment, requests only missing or review-required facts, preserves provenance and conflicts, coordinates owner and architect review, and freezes canonical snapshots for deterministic Topology, ADS, and DDD generation.

The pilot application is FACET, with Correlation/MOTS ID `8375`. The product header is **Project AWS OutPost Migration**.

## Recommended Architecture

- Python 3.12, FastAPI, SQLAlchemy 2.x, Alembic, Pydantic, Jinja2, HTMX, vanilla CSS, pytest, and Playwright.
- Begin as one server-rendered process using SQLite in WAL mode.
- Keep repository and service boundaries portable so PostgreSQL can replace SQLite if concurrency or deployment grows.
- Store evidence and generated files in content-addressed filesystem storage; keep metadata, provenance, workflow, and audit records in the database.
- Routes call application services; services enforce domain transitions and use repository interfaces. Templates do not calculate workflow state, and routes do not write SQL.
- Evidence importers create proposed candidates. They do not silently confirm values.
- Generators consume immutable canonical snapshots, never live mutable answers.
- Every state-changing operation writes an audit event in the same transaction.

## Core Domain Decisions

- Use an internal UUID for application identity. Store Correlation ID, MOTS ID, and iTAP ID as separately typed external identifiers.
- Keep application, intake, section, answer value, answer review, register, evidence, issue, job, and deliverable states independent.
- Compile the CSV catalog into immutable releases; each intake remains pinned to one release.
- Store answer and register changes as append-only revisions with current pointers.
- Model evidence applicability per application. A valid source file can still be `NOT_MATCHED` for a specific application.
- Treat portal work as human tasks and evidence capture. Do not collect or store portal credentials.
- Intake approval freezes facts for generation; Topology, ADS, and DDD approvals remain independent.
- Preserve `UNKNOWN`, `CONFLICT`, `PROPOSED`, and provenance rather than filling gaps with assumptions or sample template content.

## Catalog and Data Notes

- Catalog v0.2 has 112 controls across 20 sections and 25 response types.
- Collection modes: 30 auto-import, 47 owner HITL, 8 portal HITL, 21 architect decisions, and 6 derived controls.
- Forty `REGISTER_STATUS` controls are aggregate gates, not ordinary editable questions.
- Nineteen controls are conditional. `Required_When` is currently prose and needs compilation into a safe condition language.
- Pipe-delimited owners, sources, outputs, and choices need normalization during catalog compilation.
- Six controls have underspecified response schemas: `CTL-001`, `CTL-002`, `APP-002`, `APP-004`, `WAV-005`, and `TGT-002`.
- The SQLite draft has been executed in memory successfully: 46 tables, four triggers, foreign-key checks clean, and integrity `ok`.

## Mockup State

The mockup is a static, in-memory interaction prototype. It is not connected to SQLite, authentication, APIs, or the topology generator.

Implemented views and interactions include:

- Portfolio dashboard and create-application dialog with demo uniqueness checks.
- FACET workspace overview with independent progress dimensions.
- Evidence sources and portal-task states.
- Sectioned questionnaire with answer status, provenance, confidence, ownership, and output mappings.
- Server, interface, and database register examples.
- Issue review and candidate resolution flow.
- Review queue, approval path, deliverable readiness, history, personal work, and catalog views.
- Desktop and mobile layouts with Lucide icons and keyboard-focus treatment.

The visual direction is a dense enterprise operations console using navy, cyan, neutral surfaces, compact tables, restrained status colors, and minimal decoration. Preserve this direction unless stakeholders explicitly choose a redesign. The current branding is **Project AWS OutPost Migration**.

## Evidence and Delivery Constraints

- FACET has no applicable Wave 4 sizing, execution-plan, or target capacity-baseline evidence yet. The supplied Wave 3 workbook does not contain FACET/8375.
- Standalone TSS, iTAP, SUD, PORT, and DXC evidence and the official DDD template are absent.
- ADS v1.3 contains unverified example content; generated outputs must clear or replace it unless reviewed evidence supports it.
- The proven topology spike is value-only and deterministic. Do not infer missing target resource identifiers.
- The static prototype contains fabricated demo records for interaction design; do not treat them as approved migration facts.

## Open Decisions Before Production Coding

The complete list is in `UI_ARCHITECTURE_DECISIONS.md`. Highest-impact decisions are:

1. Confirm whether Correlation ID, MOTS ID, and iTAP ID are distinct and define uniqueness rules.
2. Define actor provisioning, role vocabulary, assignment authority, and separation of duties.
3. Confirm deployment shape, expected concurrency, SSO/OIDC integration, storage root, backup, retention, and access controls.
4. Define evidence freshness by source and risk-acceptance authority by severity.
5. Confirm what intake approval means and who approves each deliverable.
6. Supply the official DDD contract and approve the six underspecified response schemas.
7. Choose notification channels.

## Recommended Next-Agent Sequence

1. Read the three design documents and this handoff; do not re-open all source evidence merely to reconstruct context.
2. Review the mockup with stakeholders and record requested changes as explicit decisions or acceptance criteria.
3. Resolve or document assumptions for the identity, role, approval, deployment, SSO, storage, and evidence-freshness decisions.
4. Normalize catalog v0.2 and define typed response schemas, role codes, register schemas, output mappings, and executable applicability conditions.
5. Reconcile the normalized catalog with the SQLite schema and update both together.
6. Only then scaffold milestone M1 from the implementation plan and preserve the mockup as the UX reference.

When changing the design, update `UI_QUESTIONNAIRE_IMPLEMENTATION_PLAN.md`, `UI_ARCHITECTURE_DECISIONS.md`, and `SQLITE_SCHEMA_V0_1.sql` together when their contracts overlap. Keep mockup-only changes in `_data/spike/mockup/` and clearly distinguish illustrative data from production requirements.

## Validation Baseline

The last verified baseline was:

```text
Topology spike tests: 21 passed
SQLite schema: 46 tables, 4 triggers, integrity ok
Mockup JavaScript syntax: valid
Mockup desktop/mobile: no observed overflow or incoherent overlap
Stored access credentials: none
```

Useful focused checks from the workspace root:

```powershell
node --check _data\spike\mockup\app.js
python -c 'import sqlite3,pathlib; con=sqlite3.connect(":memory:"); con.executescript(pathlib.Path("docs/SQLITE_SCHEMA_V0_1.sql").read_text(encoding="utf-8")); print(con.execute("pragma integrity_check").fetchone()[0]); con.close()'
Set-Location _data\spike; python -m pytest -q
```