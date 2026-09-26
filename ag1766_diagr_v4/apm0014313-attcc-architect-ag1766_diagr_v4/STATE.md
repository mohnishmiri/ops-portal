# Multi-Tab Master Template Pipeline — State Tracker

## Template Admin Initiative (2026-09-26)

### Objective
Implement a DB-managed topology template registry with admin UI, deep profile validation, and DB-first/bundled-fallback loading for Card 3 generation.

### Status
IMPLEMENTATION COMPLETE

### Slice Completion
1. ✅ Slice 1 — Template compiler structural validation (`test_template_compiler.py`)
2. ✅ Slice 2 — Deep HAF profile-role validation (`test_template_compiler.py`)
3. ✅ Slice 3 — Template release model/repository + migration (`models_templates.py`, `repositories/templates.py`, migration `0023`)
4. ✅ Slice 4 — Publish service (preview/publish/activate/retire) (`template_admin_publish.py`)
5. ✅ Slice 5 — Query service (`template_admin_queries.py`)
6. ✅ Slice 6 — DB-first template resolution (`resolve_template()` in `template_loader.py`)
7. ✅ Slice 7 — Generation service wiring (`generate_from_standard_template()` now uses `resolve_template`)
8. ✅ Slice 8 — Read-only admin UI routes (`/admin/templates`, detail page)
9. ✅ Slice 9 — State-changing admin routes (`/admin/templates/upload`, `preview`, `publish`, `activate`, `retire`)
10. ✅ Slice 10 — Integration/regression verification

### New Tests Added
- `tests/unit/topology/test_template_compiler.py` (13 tests)
- `tests/unit/application/test_template_repository.py` (9 tests)
- `tests/unit/application/test_template_admin_publish.py` (6 tests)
- `tests/unit/application/test_template_admin_queries.py` (4 tests)
- `tests/unit/topology/test_template_resolution.py` (2 tests)
- `tests/unit/topology/test_generation_resolution.py` (1 test)
- `tests/integration/web/test_template_admin_routes.py` (8 tests)

### Verification Summary
- `python -m pytest tests/unit/topology -q` → **689 passed**
- `python -m pytest tests/unit/application -q` → **359 passed**
- `python -m pytest tests/integration/web/test_topology_routes.py -q` → **21 passed**
- `python -m pytest tests/integration/web/test_template_admin_routes.py -q` → **8 passed**
- `python -m pytest tests/web/test_ui_shell.py tests/web/test_security.py tests/web/test_topology_containment.py -q` → **115 passed**
- Combined regression run (unit + selected integration/web): **1192 passed**
- `python -m mypy` on changed files → **Success: no issues in changed files**
- `python -m ruff check src/` still reports pre-existing repository-wide violations unrelated to this slice set.

### Notes
- Existing worktree had unrelated pre-existing changes (e.g., `pyproject.toml`, docs/artifacts, deleted temp Office lock file). Those were preserved.

## Objective
Implement Option B: use the architect's multi-tab master template directly in the pipeline. Users select a variant (tab) from the UI; the pipeline extracts that tab, applies haf-role annotations, and fills it with application data.

## Current Phase
Implementation — COMPLETE

## Current Slice
All slices complete (1-9)

## Status
COMPLETE

## Baseline Results
```
563 passed (from previous phase)
581 passed (after Slice 1)
621 passed (after Slice 2)
631 passed (after Slice 3)
645 passed (after Slice 4)
655 passed (after Slice 5)
662 passed (after Slice 6)
673 passed (after Slice 9 — E2E tests)
826 passed (topology + web tests total)
2918 passed (full project suite, excluding pre-existing failures)
```

## Previous Phase
AWS Tier 1 / Alignment / Hardening — All slices 0a-0f, 1-8 complete.

## Completed Slices (This Phase)

### Slice 1: Template Tab Extraction Module
- **1a** — `list_tabs()`: 6 tests
- **1b** — `extract_tab(tab_name=)`: 5 tests
- **1c** — `extract_tab(tab_index=)`: 7 tests

### Slice 2: Copy & Annotate Master Template Tab 0
- **2a** — Copy master template to config/templates/: 3 tests
- **2b-2f** — Annotate Tab 0 with 49 haf-roles: 37 tests

### Slice 3: Per-Variant Profile (outpost_v1_basic.json)
- **3a** — Create basic profile with standard section roles: 10 tests

### Slice 4: Annotate Tabs 1-3 + Profiles
- **4a** — Tab 1 (tLGW Load Balancer): annotations + profile: 13 tests
- **4b** — Tab 2 (F5 Load Balancer): annotations + profile: 5 tests
- **4c** — Tab 3 (HA/DR with Global LB): annotations + profile: 8 tests

### Slice 5: Wire Variant Selection into Pipeline
- **5a** — `VARIANT_PROFILE_MAP` + `get_profile_for_variant()`: 10 tests
- **5b** — Service pass-through variant parameter: integrated

### Slice 6: Bundled Template Loader
- **6a** — `load_bundled_template()` function: 7 tests
- **6b** — `generate_from_standard_template()` service method: integrated

### Slice 7: UI Updates
- **7a** — Updated variant dropdown (5 options)
- **7b** — "Generate from Standard Template" card
- **7c** — POST /topology/generate-standard route

### Slice 8: AWS Tier 1 Connector Color Fix
- Already resolved — connector style uses `{color}` template variable

### Slice 9: E2E Comparison
- **9a** — Validate input, template, reference files: OK
- **9b** — E2E generation test (all 4 variants): 11 tests
- **9c** — E2E comparison script with semantic analysis
- **9d** — Visual comparison with Playwright screenshots

## Files Changed (This Phase)

### New Files
- `src/migration_intake/topology/template_loader.py` — Tab extraction + bundled loader
- `src/migration_intake/topology/config/templates/outpost_v1.7.drawio` — Annotated copy
- `src/migration_intake/topology/config/haf_profiles/outpost_v1_basic.json`
- `src/migration_intake/topology/config/haf_profiles/outpost_v1_tlgw.json`
- `src/migration_intake/topology/config/haf_profiles/outpost_v1_f5.json`
- `src/migration_intake/topology/config/haf_profiles/outpost_v1_hadr.json`
- `tests/unit/topology/test_template_loader.py`
- `tests/unit/topology/test_master_template_roles.py`
- `tests/unit/topology/test_variant_selection.py`
- `tests/unit/topology/test_bundled_loader.py`
- `tests/unit/topology/test_e2e_generation.py`
- `scripts/e2e_visual_comparison.py`

### Modified Files
- `src/migration_intake/topology/haf_pipeline.py` — Added VARIANT_PROFILE_MAP, get_profile_for_variant()
- `src/migration_intake/application/services/topology_generation.py` — Added variant parameter, generate_from_standard_template()
- `src/migration_intake/web/routes/topology.py` — Added generate-standard route
- `src/migration_intake/web/templates/topology/index.html` — Updated variant dropdown, added standard template card
- `scripts/run_e2e_comparison.py` — Updated to use bundled template

## Design Decisions
- 49+ cells annotated in each tab by matching cell ID to role name
- All profile bindings verified against respective tab roles
- AWS Tier 1 container, bg, and title already exist in master template
- Token replacement patterns (NEEDS-CIDR, UNRESOLVED-subnet) don't match master template's descriptive placeholders — known gap for follow-up
- HA/DR tab uses r2_ prefix for Region 2 roles
- Variant key `None` maps to legacy OUTPOST_V1 profile (backward compatible)
- Bundled template path uses relative path from module location

## E2E Results (Final Run)
- Run ID: 20260926_023650
- Pipeline success: True
- Mutations: 19 (interface data populated)
- Gaps: 0
- ATT Internal generated cells: 12
- AWS Tier 1 generated cells: 3
- All 10 static sections preserved
- Generated: 162 cells vs Reference: 506 cells
- 45 labels in both, 40 only generated (template placeholders), 93 only reference (real CCPM data)
- Screenshots captured via Playwright

## Artifacts
- `artifacts/final-comparison/20260926_023650/generated_diagram.drawio`
- `artifacts/final-comparison/20260926_023650/comparison_report.json`
- `artifacts/final-comparison/20260926_023656/comparison.html`
- `artifacts/final-comparison/20260926_023656/comparison_screenshot.png`
- `artifacts/final-comparison/20260926_023656/visual_comparison_report.json`

## Known Issues
1. Token replacement patterns don't match master template's descriptive placeholders — needs profile pattern updates
2. ACC- pattern regex uses lookahead not supported in master template text
3. Reference diagram is for complete CCPM (3 regions) vs our basic Tab 0 with synthetic data — not a direct 1:1 comparison
4. Pre-existing test failures (health check, LLM config, perf budgets) unrelated to our changes

## Next Actions (Follow-up)
1. Update placeholder binding patterns in profiles to match master template text
2. Verify with real CCPM intake data from database
3. Add token replacement tests once patterns are aligned
