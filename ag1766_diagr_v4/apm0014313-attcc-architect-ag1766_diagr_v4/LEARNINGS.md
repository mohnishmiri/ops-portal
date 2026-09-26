# Project Learnings

Durable project discoveries and corrections. Search by tag or topic; do not read this entire file at session start. `AGENTS.md` contains the small set of always-on invariants.

Append new entries only after a concrete incident or measured discovery. Keep the rule imperative, state why it exists, and identify when it applies.

## Format

```text
- **[TAG] <imperative rule>**
  Why: <dated incident or measured evidence>
  Applies when: <specific paths, sources, or task types>
```

---

- **[DRAWIO] Bind diagram cells by semantic label pattern, never by cross-document cell ID.**
  Why: 2026-09-04 — template and AMP IDs did not correspond, and structural fingerprints were incomplete.
  Applies when: mapping or filling draw.io topology cells.

- **[UAQ][CSV] Check for schema or metadata rows before treating row zero as the header.**
  Why: 2026-09-04 — the SharePoint UAQ export places a non-column-aligned `ListSchema` blob before the real header.
  Applies when: parsing SharePoint or portal CSV exports.

- **[CONFIDENCE] Treat detected, estimated, not-indicated, and please-validate values as unverified proposals.**
  Why: 2026-09-04 — tool-generated UAQ values sometimes contradicted human statements.
  Applies when: assigning confidence to imported facts.

- **[CONFLICT] Preserve disagreeing human-source candidates instead of selecting a winner silently.**
  Why: 2026-09-04 — sources disagreed on Oracle version and hard-coded IP behavior.
  Applies when: peer evidence provides different like-for-like values.

- **[SCOPE] Compare typed and scoped facts before declaring a conflict.**
  Why: 2026-09-04 — database TDE versus backup encryption and several PCI dimensions were initially conflated.
  Applies when: normalizing, reconciling, and raising issues.

- **[MAPPING] Keep source-to-canonical and canonical-to-output mappings separate.**
  Why: 2026-09-04 — coupling workbook columns directly to diagram slots would make source and template changes ripple through the pipeline.
  Applies when: designing import adapters, canonical schemas, or renderers.

- **[UNKNOWN] Never seed unknown target or operator inputs with plausible defaults.**
  Why: 2026-09-04 — initial resource identifiers used plausible values unsupported by evidence.
  Applies when: scaffolding application/site configuration or proposing target facts.

- **[CATALOG] Use one immutable versioned question catalog, not one mutable worksheet per application.**
  Why: 2026-09-04 — 28 application worksheets had 82 question variants, with only 28 common questions.
  Applies when: defining questionnaire releases and creating application intakes.

- **[PORTAL] Preserve portal provenance even when a value was copied into another document.**
  Why: 2026-09-04 — documents referenced SUD and PORT without record IDs, exports, retrieval dates, or collectors.
  Applies when: collecting TSS, iTAP, SUD, PORT, DXC, or Wave evidence.

- **[TEMPLATES] Clear presentation-template examples unless reviewed canonical evidence supports them.**
  Why: 2026-09-04 — the ADS template contained application-specific-looking claims that were only reusable examples.
  Applies when: generating ADS, DDD, or other deliverables from templates.

- **[APPLICABILITY] Reject wrong-application or wrong-wave evidence before importing candidates.**
  Why: 2026-09-04 — the valid Wave 3 workbook contained no FACET/8375 record, while FACET belongs to Wave 4.
  Applies when: associating multi-application, Wave sizing, execution, or capacity evidence.

- **[SIZING] Separate observed measurements from spreadsheet-derived recommendations.**
  Why: 2026-09-04 — Wave sizing formulas used defaults, cached results, external links, and questionable exception logic.
  Applies when: importing utilization and target-sizing records.

- **[IDENTITY] Use an immutable internal application ID and model external identifiers separately.**
  Why: 2026-09-04 — iTAP, Correlation, MOTS, acronym, and name have different lifecycles and unresolved alias semantics.
  Applies when: creating applications and linking evidence.

- **[STATE] Do not collapse the workflow into one application status.**
  Why: 2026-09-04 — intakes, sections, answers, registers, evidence, issues, jobs, and deliverables progress independently.
  Applies when: designing persistence, dashboards, transitions, and readiness.

- **[CATALOG] Compile and validate the catalog before rendering UI controls.**
  Why: 2026-09-04 — catalog v0.2 contains complex response types, prose conditions, normalized relationships, and computed register gates.
  Applies when: publishing a catalog release or adding UI renderers.

- **[SNAPSHOT] Freeze an immutable intake snapshot before deliverable generation.**
  Why: 2026-09-04 — generation from mutable answers invalidates reproducibility and approval lineage after later edits.
  Applies when: generating or superseding Topology, ADS, or DDD artifacts.

- **[AI] Keep runtime AI in the candidate-proposal path, never the approval or deterministic-rendering path.**
  Why: 2026-09-05 — document ingestion needs semantic flexibility without allowing probabilistic output to become canonical truth.
  Applies when: designing AI-assisted classification, extraction, normalization, or mapping.

- **[AGENTS] Keep always-on agent guidance small and move detailed context behind a `STATE.md` pointer.**
  Why: 2026-09-05 — a large Claude-specific framework duplicated rules and added hooks, skills, CI, and process machinery that would consume context without advancing this project.
  Applies when: maintaining `AGENTS.md`, `STATE.md`, `CLAUDE.md`, or future agent configuration.

- **[TOPOLOGY] Corporate proxy requires explicit NO_PROXY bypass for localhost browser tests.**
  Why: 2026-09-22 — cso.proxy.att.com:8080 intercepted localhost connections even with httpx.Client(proxy=None). Solution: set os.environ["NO_PROXY"]="localhost,127.0.0.1" before creating httpx client.
  Applies when: running browser tests behind corporate proxy; use system Edge (msedge channel) instead of downloading Chromium.

- **[TOPOLOGY] Browser test console errors include non-critical 404s for static resources.**
  Why: 2026-09-22 — favicon and static resource 404s appeared in console error list but did not affect test validity. Solution: filter console_errors to exclude "404" strings.
  Applies when: asserting console_errors in browser tests; distinguish critical errors from resource loading failures.

- **[TOPOLOGY] Negative test for missing generated container returns 409 Conflict, not 400/422.**
  Why: 2026-09-22 — compatibility check for missing container id="1" returns HTTP 409 (Conflict) to indicate incompatibility. Solution: accept 409 as valid rejection status alongside 303/400/422.
  Applies when: testing negative cases for base diagram incompatibility.
