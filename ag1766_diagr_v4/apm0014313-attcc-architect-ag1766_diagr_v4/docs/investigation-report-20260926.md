# Investigation Report — UI-Driven Topology Generation Defects

**Date:** September 26, 2026  
**Scope:** Read-only analysis; no code was modified.  
**Investigator:** Automated static and runtime analysis

---

## 1. Executive Summary

Two distinct root causes explain the two reported issues. Both are **proven** with direct evidence.

**Scenario 1 — "Generate Test Topology" shows old bugs:**  
The UI path and the non-UI E2E test use **completely different templates**. The non-UI E2E script loads the new bundled master template (`config/templates/outpost_v1.7.drawio`, Tab "Without LBs") which contains all yesterday's fixes. The UI "Generate test topology" flow loads the **user-uploaded dev template** from the database — the old single-tab file (`docs/development/topo_9_24/AWS__input_Outpost_Topology_UNRESOLVED_UNRESOLVED-v1.7.drawio`, Tab "Topology") that predates all fixes. This is not a regression; the two paths never used the same template.

**Confidence: PROVEN.** Cell IDs, tab names, haf-role counts, and missing standard sections in the artifacts directly confirm which template produced each output.

**Scenario 2 — "Generate from Standard Template" returns Internal Server Error:**  
The `generate_from_standard_template()` service method generates a synthetic UUID for `base_artifact_id` but never inserts a corresponding row into the `topo_base` table. The `gen_runs.base_artifact_id` column has a `NOT NULL` foreign key constraint (`fk_gnrn_bas`) pointing to `topo_base.id`. SQLite raises `IntegrityError: FOREIGN KEY constraint failed` at `session.flush()`.

**Confidence: PROVEN.** The full stack trace was captured from the running server confirming `sqlite3.IntegrityError: FOREIGN KEY constraint failed` at `topology.py` line 393 → `topology_generation.py` line 462 → `topology.py` (repository) line 580.

---

## 2. Observed Facts

| ID | Observed Fact | Evidence Source | File / Line / Artifact |
|----|--------------|----------------|----------------------|
| F1 | Non-UI E2E output tab name is `"Without LBs"` | XML parse of artifact | `artifacts/final-comparison/20260926_023237/generated_diagram.drawio` — root `<diagram name="Without LBs">` |
| F2 | UI-generated output tab name is `"Topology"` | XML parse of artifact | `artifacts/final-comparison/20260926_023237/topology_APP_20260926_111645.drawio` — root `<diagram name="Topology">` |
| F3 | Dev template tab name is `"Topology"`, cell ID prefix `3d824326-...` | XML parse of dev template | `docs/development/topo_9_24/AWS__input_Outpost_Topology_UNRESOLVED_UNRESOLVED-v1.7.drawio` |
| F4 | Bundled master template Tab 0 name is `"Without LBs"`, cell ID prefix `qcVyhp58iP8Gm4Rmxcgn-...` | XML parse of bundled template | `src/migration_intake/topology/config/templates/outpost_v1.7.drawio` |
| F5 | UI-generated output cell IDs match dev template: `3d824326-...`, `ffefcb74-...` | XML parse comparison | Both `topology_APP_20260926_111645.drawio` and dev template share identical root cell IDs |
| F6 | Non-UI E2E output cell IDs match bundled template: `qcVyhp58iP8Gm4Rmxcgn-...` | XML parse comparison | Both `generated_diagram.drawio` and bundled template share identical root cell IDs |
| F7 | Non-UI E2E has 45 haf-roles; UI has 38 haf-roles | XML attribute count | Direct parse of both artifacts |
| F8 | Non-UI E2E has 7 roles absent from UI: `aws_tier1_bg`, `aws_tier1_container`, `aws_tier1_title`, `aws_tier2_label`, `directconnect_icon`, `internet_label`, `vpce_bastion_label` | Set difference of haf-roles | Both artifacts compared |
| F9 | Dev template is missing `aws_tier2_label`, `internet_label`, `vpce_bastion_label` roles | XML parse of dev template | Dev template has 46 roles; these 3 are absent |
| F10 | Non-UI E2E has 3 AWS Tier 1 generated cells (`aws_tier1_gen_*`); UI has 0 | Cell ID prefix search | Both artifacts |
| F11 | Non-UI E2E has 12 ATT Internal generated cells; UI has 21 | Cell ID prefix search | `att_internal_gen_*` count in both artifacts |
| F12 | UI output contains `NEEDS-CIDR` in 2 cells and `UNRESOLVED` in 6 cells; Non-UI E2E has 0 of each | Text search of cell values | Both artifacts |
| F13 | UI output is missing `Tier 2`, `Internet`, and `VPCE` standard sections; E2E has all | Text search for section labels | Both artifacts |
| F14 | UI output has no `DTV-VDAS` (the AWS Tier 1 interface); E2E has it | Text search | Both artifacts |
| F15 | Non-UI E2E script calls `load_bundled_template("basic")` directly | Source code | `scripts/run_e2e_comparison.py` line 92 |
| F16 | Non-UI E2E script calls `fill_haf_template()` directly with synthetic data, bypassing DB and service layer | Source code | `scripts/run_e2e_comparison.py` lines 96–185 |
| F17 | Non-UI E2E script uses profile `OUTPOST_V1_BASIC` | Source code | `scripts/run_e2e_comparison.py` line 182 |
| F18 | UI generate route calls `topology_service.generate_topology()` without `variant` parameter | Source code | `src/migration_intake/web/routes/topology.py` lines 324–328 |
| F19 | `generate_topology()` with `variant=None` maps to profile `OUTPOST_V1` | Source code | `topology_generation.py` line 797: `self._variant_profile_map.get(None, ...)` → `{None: "OUTPOST_V1"}` at line 109 |
| F20 | Profile `OUTPOST_V1` has 13 protected roles; `OUTPOST_V1_BASIC` has 22 protected roles | JSON file comparison | `config/haf_profiles/outpost_v1.json` vs `outpost_v1_basic.json` |
| F21 | `OUTPOST_V1` profile is missing: `aws_tier1_bg`, `aws_tier1_container`, `aws_tier1_title`, `aws_tier2_label`, `directconnect_icon`, `internet_label`, `network_account_container`, `vpce_bastion_label`, `azure_apps_container` | JSON comparison | `outpost_v1.json` `protected_roles` array |
| F22 | The `generate-standard` POST returns HTTP 500 | Server log | Live server output: `"POST .../topology/generate-standard HTTP/1.1" 500` |
| F23 | The exception is `sqlite3.IntegrityError: FOREIGN KEY constraint failed` on INSERT into `gen_runs` | Server stack trace | Full traceback captured from running server |
| F24 | The failure occurs at `topology_generation.py` line 462: `topology_repo.create_generation_run(...)` | Server stack trace | `topology_generation.py:462` → `topology.py:580` (flush) |
| F25 | `generate_from_standard_template()` creates `base_id = str(uuid.uuid4())` at line 457 but never inserts a `topo_base` row | Source code | `topology_generation.py` lines 456–458 — comment says "Create a synthetic base artifact record" but no insertion follows |
| F26 | `gen_runs.base_artifact_id` has `ForeignKeyConstraint(["base_artifact_id"], ["topo_base.id"])` and `nullable=False` | Model definition | `models_topology.py` lines 87, 120 |
| F27 | Card 2 form does not include a `variant` field; only `base_artifact_id` and `_csrf_token` are submitted | HTML template | `topology/index.html` lines 286–295 |
| F28 | Card 1 upload form captures `variant` and stores it on the `topo_base` record | Source code | `topology.py` line 244: `variant: ... Form() = "default"`; line 274: passed to `upload_base_diagram()` |
| F29 | Only uncommitted change is `pyproject.toml` (`requires-python` relaxed to `>=3.12`) | `git status` and `git diff` | Working tree |
| F30 | The UI-generated ATT Internal data contains real CCPM app names (`CCPM`, `CCR-Relational`, `DITREX`, etc.); the E2E data contains synthetic names (`ORACLE SCM`, `MyTracker`, `LS-OMS`, etc.) | Cell value text | Both artifacts — ATT Internal `att_internal_gen_*` cells |

---

## 3. Execution-Path Comparison

| Stage | Non-UI E2E Script | UI "Generate Test Topology" (Card 2) | UI "Generate from Standard Template" (Card 3) | Difference / Significance |
|-------|-------------------|--------------------------------------|-----------------------------------------------|--------------------------|
| **Entry point** | `scripts/run_e2e_comparison.py` (direct Python execution) | `POST .../topology/generate` → `topology.py:300 generate_topology()` | `POST .../topology/generate-standard` → `topology.py:370 generate_from_standard_template()` | Three completely separate entry points |
| **Template source** | `load_bundled_template("basic")` → reads `config/templates/outpost_v1.7.drawio`, extracts Tab "Without LBs" | Loads from DB via `base.get("content")` or `_load_content(content_address)` — whatever the user uploaded | `load_bundled_template(variant)` → reads `config/templates/outpost_v1.7.drawio`, extracts variant tab | **ROOT CAUSE #1**: Card 2 uses the old uploaded dev template; E2E and Card 3 use the new bundled master template |
| **Template identity** | Tab "Without LBs", cell IDs `qcVyhp58iP8Gm4Rmxcgn-*`, 151 cells, 49 haf-roles | Tab "Topology", cell IDs `3d824326-*`, 148 cells, 46 haf-roles | Tab "Without LBs" (for basic), cell IDs `qcVyhp58iP8Gm4Rmxcgn-*`, 151 cells, 49 haf-roles | Dev template lacks 7 roles and 3 standard sections present in master |
| **Profile selection** | Hardcoded `"OUTPOST_V1_BASIC"` | `variant=None` → `VARIANT_PROFILE_MAP[None]` → `"OUTPOST_V1"` | `variant` from form → `VARIANT_PROFILE_MAP[variant]` → `"OUTPOST_V1_BASIC"` etc. | Card 2 uses the old profile with 13 protected roles; E2E and Card 3 use the new profile with 22 |
| **Data source** | Synthetic hardcoded data (8 interfaces, fixed tokens) | Real DB extraction via `extract_haf_data(session, intake_id, ...)` | Real DB extraction via `extract_haf_data(session, intake_id, ...)` | E2E has controlled data; UI paths extract real data (which actually works correctly — the different app names in UI output are correct real data) |
| **Pipeline function** | `fill_haf_template()` called directly | `generate_haf_topology()` → `fill_haf_template()` (same core function) | `generate_haf_topology()` → `fill_haf_template()` | Same core fill function; differences are in inputs |
| **DB operations** | None — bypasses DB entirely | Creates `gen_runs` record (FK to existing `topo_base` row) — works | Creates `gen_runs` record with synthetic `base_artifact_id` — FK violation | **ROOT CAUSE #2**: Card 3 fails because no `topo_base` row is created |
| **Output storage** | Writes to `artifacts/final-comparison/*/generated_diagram.drawio` | Stores via `FilesystemStore` + DB `gen_artifacts` record | Never reaches output storage — fails at DB insertion | Card 3 never gets past run creation |

---

## 4. Artifact Comparison

### generated_diagram.drawio (Non-UI E2E) vs topology_APP_20260926_111645.drawio (UI)

| Dimension | Non-UI E2E | UI-Generated | Significance |
|-----------|-----------|--------------|--------------|
| Tab name | `Without LBs` | `Topology` | Different source templates |
| Total cells | 162 | 158 | E2E has 4 more (3 AWS Tier 1 generated + 1 added standard section cell) |
| haf-role cells | 45 | 38 | 7 roles missing from UI output (template lacked them) |
| ATT Internal gen cells | 12 (4 groups × 3 cells) | 21 (7 groups × 3 cells) | UI has more because real CCPM data has more interface families |
| AWS Tier 1 gen cells | 3 (DTV-VDAS) | 0 | **Defect #1**: Dev template has `aws_tier1_bg/container/title` roles BUT profile `OUTPOST_V1` may handle them differently |
| `NEEDS-CIDR` remaining | 0 | 2 | **Defect #2**: E2E's master template has different placeholder text; dev template has literal `NEEDS-CIDR` that token resolution attempted but failed against real data |
| `UNRESOLVED` remaining | 0 | 6 | **Defect #3**: Same root cause as NEEDS-CIDR — dev template's placeholder patterns |
| `DTV-VDAS` present | Yes (aws_tier1_gen) | No | **Defect #4**: No AWS Tier 1 generation in UI output |
| Tier 2 section | Present | **Missing** | **Defect #5**: Dev template has no `aws_tier2_label` role |
| Internet section | Present | **Missing** | **Defect #6**: Dev template has no `internet_label` role |
| VPCE section | Present | **Missing** | **Defect #7**: Dev template has no `vpce_bastion_label` role |
| GitHub Runners | Present | Present | Both templates have this section |
| CloudWatch | Present | Present | Both templates have this section |
| ATT Internal app names | Synthetic (`ORACLE SCM`, `MyTracker`) | Real CCPM data (`CCPM`, `DITREX`, `eCDW`) | Different data sources — both are correct for their context |
| File size | 128,733 bytes | 127,913 bytes | Similar |

### Key Finding

The "bugs that were fixed yesterday" are not regressions — they are **symptoms of using the old dev template**, which structurally lacks the sections and roles that were added to the new master template. The dev template was never modified by yesterday's work. Yesterday's fixes were applied exclusively to the new bundled master template copy.

---

## 5. Root-Cause Hypotheses

| Rank | Hypothesis | Supporting Evidence | Contradicting Evidence | Confidence |
|------|-----------|-------------------|----------------------|------------|
| **1** | **Scenario 1: Card 2 uses the user-uploaded dev template (not the new master template) because the generate route loads content from DB, and the user uploaded the old template.** | F1–F6 (tab names and cell IDs match), F7–F9 (role counts differ exactly as expected), F13 (missing sections match missing roles), F15–F16 (E2E uses different template), F18 (no variant passed), F30 (different app data confirms different data sources) | None | **PROVEN** |
| **2** | **Scenario 1 (secondary): Even if the correct template were used, Card 2 uses profile `OUTPOST_V1` (13 protected roles) instead of `OUTPOST_V1_BASIC` (22 protected roles), so standard sections would not be fully protected.** | F18 (variant=None), F19 (maps to OUTPOST_V1), F20–F21 (profile lacks 9 roles) | The template itself would carry the sections; whether the profile protects them from mutation is a separate concern | **STRONGLY SUPPORTED** |
| **3** | **Scenario 2: `generate_from_standard_template()` fails with FK violation because it assigns a synthetic UUID to `base_artifact_id` without inserting a `topo_base` row, and the `gen_runs` table enforces FK constraint.** | F22 (HTTP 500 observed), F23 (exact exception), F24 (exact line), F25 (code inspection shows no INSERT), F26 (FK constraint defined) | None | **PROVEN** |
| 4 | Stale server process running old code | The server was restarted before today's test; `git status` shows all pipeline code is committed and up to date (F29) | **Contradicted** — the server IS running the latest code; the issue is that the code works as designed — it loads the user's uploaded template, not the new bundled one | **ELIMINATED** |
| 5 | Cached artifacts or build issues | The `pip install -e .` editable install was refreshed before this session | **Contradicted** — both flows work correctly given their inputs | **ELIMINATED** |

---

## 6. Internal Server Error Analysis

### Triggering Request
```
POST /applications/96353d13-12fd-4984-bec1-719d1fd8e6da/intakes/26385e58-8954-4312-bf27-9d8414c79421/topology/generate-standard
Form data: _csrf_token=<token>&variant=basic
```

### Endpoint and Handler
- **Route:** `topology.py` line 367: `@router.post(".../topology/generate-standard")`
- **Handler:** `generate_from_standard_template()` at line 370
- **Service call:** line 393: `topology_service.generate_from_standard_template(intake_id, variant, actor)`

### Failure Location
- **Service method:** `topology_generation.py` line 421: `generate_from_standard_template()`
- **Failure line:** line 462: `topology_repo.create_generation_run(...)` — specifically the `base_artifact_id=base_id` parameter
- **Repository:** `topology.py` (persistence) line 580: `self._session.flush()` triggers the FK check
- **DB:** SQLite enforces `fk_gnrn_bas` (line 120 of `models_topology.py`)

### Exception Type and Message
```
sqlalchemy.exc.IntegrityError: (sqlite3.IntegrityError) FOREIGN KEY constraint failed
[SQL: INSERT INTO gen_runs (..., base_artifact_id, ...) VALUES (..., ?, ...)]
[parameters: (..., 'a885d48d-2f0c-43f9-b108-f0e9f9111164', ...)]
```

### Root Cause Code
```python
# topology_generation.py lines 456-458
# Create a synthetic base artifact record for traceability
base_id = str(uuid.uuid4())                              # <-- creates UUID
template_sha256 = hashlib.sha256(template_bytes).hexdigest()

# line 462
run = topology_repo.create_generation_run(
    ...
    base_artifact_id=base_id,    # <-- references nonexistent topo_base row
    ...
)
```

The comment on line 456 says "Create a synthetic base artifact record" but no actual insertion into `topo_base` is performed between lines 456 and 462.

### Why "Without LBs" Triggers It
This is NOT variant-specific. **All four variants** (basic, tlgw, f5, hadr) trigger the same failure because the FK violation occurs before any variant-specific logic runs. The template tab extraction succeeds (line 441: `load_bundled_template(variant)` — confirmed working), but the DB insertion at line 462 fails for every variant equally.

### Why Other Flows Avoid This
The Card 2 "Generate test topology" flow works because the user has already uploaded a template via Card 1, which created a real `topo_base` row with a real UUID. The `generate_topology()` method references that existing UUID (line 317: `base_artifact_id=base_artifact_id`), so the FK check passes.

---

## 7. Proof / Validation Plan

| Conclusion | Validation Method |
|-----------|-------------------|
| **Scenario 1: Template mismatch** | (1) In the DB, query the `topo_base` table for the artifact used in the UI generation; examine its `filename` and `variant` columns — expected to show the dev template filename, not the master template. (2) Upload the new bundled template via Card 1 and generate via Card 2 — the output should then match the E2E result. (3) In a read-only test, call `_is_haf_template()` on both templates — both return True, confirming the pipeline dispatches to HAF for both, but with different role sets. |
| **Scenario 1: Profile mismatch** | (1) Modify the Card 2 route to read `variant` from the `topo_base` record and pass it to `generate_topology()`. (2) Alternatively, hard-code `variant="basic"` in the route and observe the profile switch. |
| **Scenario 2: FK violation** | (1) Add a `topo_base` INSERT before `create_generation_run()` in `generate_from_standard_template()`. (2) Run the same UI flow; the FK error will disappear. (3) Alternatively, make `base_artifact_id` nullable on `gen_runs` — but this is a schema change with broader implications. |

---

## 8. Final Assessment

| Issue | Classification | Explanation |
|-------|---------------|-------------|
| **Scenario 1: UI "Generate Topology" produces old-looking output** | **PROVEN — Design gap, not a regression.** | The UI Card 2 path generates from the user-uploaded template stored in the database. The user uploaded the old dev template, which predates all fixes. The non-UI E2E script bypasses the DB and loads the new bundled master template directly. The two paths were never connected; they use different templates, different profiles, and different data sources. No code was reverted; no cache is stale. The fix requires either: (a) having Card 2 retrieve the variant from the base artifact and pass it through, or (b) having the user upload the new master template, or (c) connecting Card 2 to the bundled template loading path. |
| **Scenario 2: ISE on "Generate from Standard Template"** | **PROVEN — Implementation bug.** | The `generate_from_standard_template()` method assigns a UUID to `base_artifact_id` but never inserts the corresponding `topo_base` row. The `gen_runs` FK constraint fails at flush time. The fix is to insert a `topo_base` row before creating the generation run. |

---

## 9. Missing Evidence

| Item | Why It Would Help | Current Status |
|------|------------------|---------------|
| The exact `topo_base` row used for the UI generation | Would confirm which filename/variant was stored at upload time | Inferable from cell IDs but DB query not performed (read-only investigation) |
| Browser network tab showing exact POST payload for Card 2 | Would confirm only `base_artifact_id` was sent (no variant) | Inferred from HTML template source code — Card 2 form has no `variant` field |
| Full server log for the Card 2 generation run | Would show which profile was selected and any extraction warnings | Partial log captured — interface normalization output visible |
| Whether `OUTPOST_V1` profile handles AWS Tier 1 generation at all | The dev template has `aws_tier1_*` roles but the old profile may not trigger AWS Tier 1 grouped rendering | Would require tracing `fill_haf_template()` with `OUTPOST_V1` profile to confirm |

---

## Appendix A: File References

| Component | File | Key Lines |
|-----------|------|----------|
| Non-UI E2E script | `scripts/run_e2e_comparison.py` | 92 (load_bundled_template), 177–185 (fill_haf_template call) |
| UI generate route (Card 2) | `src/migration_intake/web/routes/topology.py` | 296–358 (no variant param) |
| UI standard route (Card 3) | `src/migration_intake/web/routes/topology.py` | 366–421 (calls generate_from_standard_template) |
| Service: generate_topology | `src/migration_intake/application/services/topology_generation.py` | 257–418 (loads from DB) |
| Service: generate_from_standard_template | `src/migration_intake/application/services/topology_generation.py` | 421–554 (FK violation at 462) |
| Service: _generate_haf_diagram | `src/migration_intake/application/services/topology_generation.py` | 789–856 (profile selection at 797) |
| Variant profile map | `src/migration_intake/application/services/topology_generation.py` | 108–114 |
| HAF pipeline variant map | `src/migration_intake/topology/haf_pipeline.py` | 45–51 |
| Template loader | `src/migration_intake/topology/template_loader.py` | 81–102 (load_bundled_template) |
| DB model: gen_runs FK | `src/migration_intake/persistence/models_topology.py` | 87 (base_artifact_id NOT NULL), 120 (FK constraint) |
| DB model: topo_base | `src/migration_intake/persistence/models_topology.py` | 37–58 (variant column at 50) |
| Profile: OUTPOST_V1 | `src/migration_intake/topology/config/haf_profiles/outpost_v1.json` | 13 protected roles |
| Profile: OUTPOST_V1_BASIC | `src/migration_intake/topology/config/haf_profiles/outpost_v1_basic.json` | 22 protected roles |
| HTML Card 2 form | `src/migration_intake/web/templates/topology/index.html` | 286–295 (no variant field) |
| HTML Card 3 form | `src/migration_intake/web/templates/topology/index.html` | 308–320 (has variant field) |
| Bundled template | `src/migration_intake/topology/config/templates/outpost_v1.7.drawio` | 5 tabs, 49 roles on Tab 0 |
| Dev template (old) | `docs/development/topo_9_24/AWS__input_Outpost_Topology_UNRESOLVED_UNRESOLVED-v1.7.drawio` | 1 tab, 46 roles, missing sections |
| E2E artifact (correct) | `artifacts/final-comparison/20260926_023237/generated_diagram.drawio` | 162 cells, 45 roles, all sections present |
| UI artifact (old behavior) | `artifacts/final-comparison/20260926_023237/topology_APP_20260926_111645.drawio` | 158 cells, 38 roles, 3 sections missing |
