# AWS Tier 1 Dynamic Generation, ATT Internal Alignment, and Multi-App Hardening

Design and implementation plan for dynamically generating the AWS Tier 1 / PaaS Apps section, fixing ATT Internal alignment discrepancies, hardening for 200-300 diverse applications, and protecting static diagram sections.

---

## 1. Current Architecture and Generation Flow

### 1.1 Pipeline Data Flow

```
Web route (topology_generation.py:641)
  -> generate_haf_topology()                         [haf_service.py:53]
    -> extract_haf_data(session, intake_id, profile)  [haf_extractor.py:88]
      |  SELECT InterfaceRecord WHERE application_id + state=ACTIVE
      |  create_interface_candidate() per row          [interface_normalization.py:421]
      |    normalize_location()  -> HAF_LOCATION_ALIASES  -> "INTERNAL"/"AWS"/"AZURE"/...
      |    normalize_direction() -> DIRECTION_ALIASES     -> "INBOUND"/"OUTBOUND"/...
      |    normalize_protocol()  -> uppercase trimmed
      |    normalize_port()      -> trimmed
      |  group_interfaces_by_protocol_family(candidates, category_filter="INTERNAL")
      |  Result: interface_groups (list[ProtocolFamilyGroup] for INTERNAL only)
    -> fill_haf_template()                             [haf_pipeline.py:617]
      |  parse_haf_template()     -> HafIndex (cells by haf-role)
      |  load_haf_profile()       -> HafProfile
      |  resolve_placeholders()   -> token substitution
      |  generate_att_internal_rows(tree, groups) [att_internal_generator.py:251]
      |    _delete_generated()      -> remove prior att_internal_gen_* cells
      |    _remove_static_slots()   -> remove att_internal_*_slot cells
      |    For each group: create left_box + label_box + connector edge
      |  fill_interface_regions()   -> non-INTERNAL slots (Azure, Tier2, etc.)
      |  fill_detail_blocks()       -> NAS, EBR detail blocks
      |  ET.tostring()              -> serialized filled XML bytes
```

### 1.2 Key Source Files

| File | Path | Purpose |
|---|---|---|
| `interface_normalization.py` | `src/migration_intake/topology/` | `HAF_LOCATION_ALIASES`, `PROTOCOL_FAMILY_PATTERNS`, `FAMILY_COLORS`, `InterfaceCandidate`, `ProtocolFamilyGroup`, `group_interfaces_by_protocol_family()` |
| `att_internal_generator.py` | `src/migration_intake/topology/` | `generate_att_internal_rows()` — creates dashed boxes, labels, connectors inside ATT Internal container |
| `haf_extractor.py` | `src/migration_intake/topology/` | DB query, normalization, grouping; `HafExtractionResult` |
| `haf_pipeline.py` | `src/migration_intake/topology/` | `fill_haf_template()` orchestrator; `parse_haf_template()`, `resolve_placeholders()`, `fill_interface_regions()` |
| `haf_service.py` | `src/migration_intake/topology/` | `generate_haf_topology()` — wires extractor + pipeline |
| `outpost_v1.json` | `src/migration_intake/topology/config/haf_profiles/` | Profile: placeholder bindings, interface regions, detail blocks, protected roles |
| Template | `docs/development/topo_9_24/AWS__input_Outpost_Topology_UNRESOLVED_UNRESOLVED-v1.7.drawio` | draw.io XML with haf-role attributes |

### 1.3 Multi-App Isolation Architecture

Each pipeline run is fully isolated:
- `topology_generation.py` loads `base_content` (unmodified template bytes) from per-app storage
- `fill_haf_template()` parses a fresh `ElementTree` from those bytes
- All DB queries are scoped by `application_id` + `state=ACTIVE`
- No shared mutable state between runs
- The filled XML bytes are returned, never written back to the template

---

## 2. Findings from Existing Devin Plan

The previous investigation identified 8 multi-app hardening issues (M1-M8), 5 ATT Internal alignment discrepancies (A1-A5), and the complete absence of AWS Tier 1 generation. All findings were verified against repository evidence.

### 2.1 Confirmed Issues

| ID | Issue | Severity | Verified at |
|---|---|---|---|
| M1 | `HAF_LOCATION_ALIASES` missing "Mainframe", "Private Cloud", "Data Center", etc. | Critical | `interface_normalization.py:25-46` vs form datalist in `interfaces/form.html:92-99` |
| M2 | `tier2_internet_slot` has `category:"UNKNOWN"` but aliases map to `"TIER2_INTERNET"` | Critical | `outpost_v1.json:100-106` vs `interface_normalization.py:43-45` |
| M3 | Template has hardcoded CCPM data in `att_internal_in_slot`, `att_internal_out_secondary_slot`, `azure_apps_slot` | High | Template XML cells with CCPM app names |
| M4 | `ProtocolFamilyGroup` docstring says "INTERNAL" | Low | `interface_normalization.py:224` |
| M5 | `InterfaceGroup` docstring says "AT&T Internal" | Low | `interface_normalization.py:159-161` |
| M7 | No container height auto-resize — AWS Tier 1 starts at 220px, needs resize | Medium | `att_internal_generator.py:283-284` |
| M8 | `max_rows=15` truncation not surfaced to user | Low | `att_internal_generator.py:429-432` |
| A2 | Connector targets group cell, architect targets background rect | Medium | `att_internal_generator.py:417` |
| A3 | Label style differs from architect (rounded=1, white fill) | Low | `att_internal_generator.py:59-62` |
| A5 | SQL_DB color #FF8000 doesn't match legend #FF9933 | Low | `interface_normalization.py:82` vs template legend |

### 2.2 Confirmed Decisions

- Template: Update v1.7 in-place (user-confirmed)
- Grouping: By protocol family, same as ATT Internal (user-confirmed)
- Direction filter for AWS Tier 1: INBOUND + BIDIRECTIONAL (user-confirmed)
- Color authority: Template legend is the authoritative source

---

## 3. Requirements Discovered from Code and Artifacts

### 3.1 From the architect's final CCPM draw.io

The architect's manually drawn CCPM file (`docs/CCPM__FINAL_18678_TargetState_AWS_OutPosts_v01 (1).drawio`) reveals:

**AWS Tier 1 container (cell CVVs1qhz3C6rMBpojcnh-10):**
- Group cell containing: background rect (#FFCC99), AWS icon, title, S3/KMS/Secrets Manager icons
- Dynamic interface box: dashed, gray fill #E6E6E6, format "AppAcronym (CorrelationID)"
- Connector: `startArrow=classic;endArrow=none` (inbound), edge label with bold port "443"
- Container size: 341x220

**ATT Internal section (cell tHqj9sfw9at4eJAR7oj_-0):**
- 5 family-grouped rows (not 11+ individual rows)
- Connector targets background rect (not group cell)
- Port labels at x~270, standalone boxes with `rounded=0;whiteSpace=wrap;html=1;`
- Connector colors use `light-dark()` CSS function (dark mode support)

### 3.2 From template legend

Authoritative color map from template:
- HTTPS: #6666FF, SSH/SFTP: #00CC66, SQL/ODBC: #FF9933, JDBC: #67AB9F
- SMTP: #CC0000, GG: #99004D, DataGuard: #CCCC00, Multiple: default (black)

### 3.3 From form datalist

Location options offered to users: Mainframe, Midrange, Azure, AWS, Conexus, Private Cloud.
"Mainframe" and "Private Cloud" are NOT in `HAF_LOCATION_ALIASES`.

---

## 4. Assumptions and Unresolved Questions

| # | Item | Status |
|---|---|---|
| 1 | AWS service icons (S3, KMS, Secrets Manager) are static across all apps | Assumed YES |
| 2 | Template legend colors are authoritative over architect's ad-hoc colors | Confirmed |
| 3 | The form will eventually add "Bidirectional" direction option | Unknown — code handles it |
| 4 | The same v1.7 template is used for all 300 apps | Confirmed (base_content loaded per-app) |
| 5 | SMTP family should map to CC0000 (same as legend) | Assumed YES — add pattern |

---

## 5. Proposed Design and Component Boundaries

### 5.1 New module: `aws_tier1_generator.py`

Mirrors `att_internal_generator.py` pattern:
- `GENERATED_ID_PREFIX = "aws_tier1_gen_"`
- `LAYOUT` dict with AWS-specific positions (start_y below icons)
- `generate_aws_tier1_rows(tree, aws_groups)` -> `GenerationResult`
- Imports `GeneratedElement`, `GenerationResult`, `_find_graph_root`, `_left_height_wrapped`, `_arrow_config`, `_direction_label` from `att_internal_generator.py`
- Implements container auto-resize when rows exceed container height

### 5.2 Modified modules

| Module | Changes |
|---|---|
| `interface_normalization.py` | Add location aliases, `direction_filter` param, DATAGUARD/SMTP families, fix SQL_DB color, update docstrings |
| `haf_extractor.py` | Add `aws_tier1_groups` field, second grouping call with AWS filter |
| `haf_pipeline.py` | Call `generate_aws_tier1_rows()`, accept `aws_tier1_groups` param |
| `haf_service.py` | Pass `aws_tier1_groups` through |
| `outpost_v1.json` | Fix tier2 category, add `standard_sections` list |
| Template .drawio | Clear CCPM data, add AWS Tier 1 container |
| `att_internal_generator.py` | Fix connector target, label style, edge routing |

---

## 6. Reuse Analysis

### 6.1 drawpyo-main

| File | Symbol | Useful? | Decision |
|---|---|---|---|
| `extended_objects.py:70-77` | `List.autosize()` | Height = startSize + sum(child heights) | **Reference only** — pattern already adapted into `_left_height_wrapped()` |
| `base_diagram.py` | `Geometry` class | x/y/w/h attributes | **Reference only** — we use raw ET.SubElement |
| `edges.py` | Edge creation patterns | source/target, style | **Reference only** — our connector style is more specific |
| `drawio_parser.py` | File parsing | XML parsing | **Reference only** — we use `parse_haf_template()` |

**Decision:** No direct imports. drawpyo uses an object model that conflicts with our template-mutation approach. The `List.autosize()` height calculation pattern was already adapted.

### 6.2 multicloud-diagrams-main

| File | Symbol | Useful? | Decision |
|---|---|---|---|
| `__init__.py` | `update_style_by_key()` | Regex style mutation | **Reference only** — not needed |
| `__init__.py` | AWS icon shape definitions | Icon styles | **Reference only** — we copy icon XML from architect's CCPM |
| Various test files | Node/edge creation patterns | Layout patterns | **Reference only** |

**Decision:** No direct imports. The library creates diagrams from scratch; we mutate existing templates. The icon shape data could theoretically be extracted but the architect's CCPM XML provides the exact styles we need.

---

## 7. Configuration and .env Recommendations

### 7.1 What belongs in profile config (outpost_v1.json)

- `standard_sections` list — section names that must not be modified
- `interface_regions` — category/direction mappings for slot cells
- `protected_roles` — haf-role patterns that are never mutated
- `placeholder_bindings` — token → cell mappings

### 7.2 What does NOT belong in .env

- Protocol family patterns, colors — these are typed constants in `interface_normalization.py`
- Layout dimensions — these are module-level dicts in generator modules
- Business logic — grouping, normalization, rendering
- Static section lists — tied to template version, not environment
- Icon styles/positions — static XML structure in the template

### 7.3 What could optionally use .env

| Item | Recommendation |
|---|---|
| Feature flags (e.g., `ENABLE_AWS_TIER1_GENERATION=true`) | **Acceptable** for gradual rollout. Default ON in code. |
| `HAF_PROFILE_ID` override | **Acceptable** — currently hardcoded as `"OUTPOST_V1"` in `topology_generation.py:106` |
| Input/output paths for batch runs | **Acceptable** — useful for scripted batch processing |
| Visual comparison thresholds | **Not needed now** — final comparison is manual inspection |

### 7.4 Recommendation

Create a typed configuration module `src/migration_intake/topology/config/settings.py` with safe defaults:

```python
import os

HAF_PROFILE_ID = os.environ.get("HAF_PROFILE_ID", "OUTPOST_V1")
ENABLE_AWS_TIER1 = os.environ.get("ENABLE_AWS_TIER1", "true").lower() == "true"
```

This is lightweight and doesn't require a `.env` file for normal operation.

---

## 8. Ordered Implementation Slices

### Slice 0: Multi-App Hardening — Location Aliases and Colors

**Sub-slice 0a: Missing location aliases**
- **Objective:** Add "MAINFRAME", "PRIVATE CLOUD", "ON-PREMISES", "DATA CENTER", "DATACENTER" to `HAF_LOCATION_ALIASES` mapping to `"INTERNAL"`.
- **Files:** `src/migration_intake/topology/interface_normalization.py`
- **Tests first:** `test_mainframe_maps_to_internal`, `test_private_cloud_maps_to_internal`, `test_datacenter_maps_to_internal`, `test_on_premises_maps_to_internal`
- **Test file:** `tests/unit/topology/test_interface_normalization.py`
- **Test command:** `python -m pytest tests/unit/topology/test_interface_normalization.py -q`
- **Acceptance:** New tests pass. `python -m pytest tests/unit/topology/ -q` shows 484+N passed, 0 failed.
- **Dependencies:** None

**Sub-slice 0b: DATAGUARD and SMTP protocol families**
- **Objective:** Add DATAGUARD and SMTP to `PROTOCOL_FAMILY_PATTERNS` and `FAMILY_COLORS`.
- **Files:** `src/migration_intake/topology/interface_normalization.py`
- **Tests first:** `test_dataguard_family`, `test_smtp_family`, `test_dataguard_color`, `test_smtp_color`
- **Acceptance:** New tests pass. No regressions.
- **Dependencies:** None

**Sub-slice 0c: SQL_DB color fix**
- **Objective:** Change `FAMILY_COLORS["SQL_DB"]` from `"#FF8000"` to `"#FF9933"` to match template legend.
- **Files:** `src/migration_intake/topology/interface_normalization.py`
- **Tests first:** `test_sql_db_color_matches_legend`
- **Acceptance:** Test passes. Update any existing tests that assert #FF8000.
- **Dependencies:** None

**Sub-slice 0d: tier2_internet_slot category fix**
- **Objective:** Change `tier2_internet_slot` category from `"UNKNOWN"` to `"TIER2_INTERNET"` in profile.
- **Files:** `src/migration_intake/topology/config/haf_profiles/outpost_v1.json`
- **Tests first:** `test_tier2_internet_slot_category_matches_aliases`
- **Acceptance:** Test passes. No regressions.
- **Dependencies:** None

**Sub-slice 0e: Template CCPM data cleanup**
- **Objective:** Replace hardcoded CCPM interface data in template with placeholder text.
- **Files:** `docs/development/topo_9_24/AWS__input_Outpost_Topology_UNRESOLVED_UNRESOLVED-v1.7.drawio`
- **Tests first:** `test_template_no_ccpm_data`
- **Acceptance:** No cells in template contain CCPM-specific app names. Existing tests still pass.
- **Dependencies:** None

**Sub-slice 0f: Generic docstrings**
- **Objective:** Update `ProtocolFamilyGroup` and `InterfaceGroup` docstrings to be category-agnostic.
- **Files:** `src/migration_intake/topology/interface_normalization.py`
- **Tests:** No new tests (docstring only). Regression check.
- **Dependencies:** None

### Slice 1: Multi-App Stress Tests

- **Objective:** Parameterized tests proving the pipeline handles diverse app profiles.
- **Files:** New `tests/unit/topology/test_multi_app_stress.py`
- **Tests:** `test_app_with_zero_interfaces`, `test_app_with_unknown_location`, `test_app_with_unknown_protocol`, `test_app_with_50_interfaces_per_family`, `test_app_with_all_families`, `test_app_with_missing_protocol_and_port`, `test_deterministic_output_across_runs`, `test_no_ccpm_data_leaks_in_output`
- **Test command:** `python -m pytest tests/unit/topology/test_multi_app_stress.py -q`
- **Acceptance:** All stress tests pass.
- **Dependencies:** Slice 0

### Slice 2: ATT Internal Alignment Fixes

**Sub-slice 2a: Connector target fix**
- **Objective:** Change connector target from container group cell to background rect.
- **Files:** `src/migration_intake/topology/att_internal_generator.py`
- **Tests first:** `test_connector_targets_background_rect`
- **Acceptance:** Test passes. Connector `target` attribute is the background rect ID.
- **Dependencies:** Slice 0

**Sub-slice 2b: Label style simplification**
- **Objective:** Change `LABEL_STYLE` to `rounded=0;whiteSpace=wrap;html=1;fontStyle=1;` to match architect.
- **Files:** `src/migration_intake/topology/att_internal_generator.py`
- **Tests first:** Update existing label style assertions.
- **Acceptance:** All tests pass with new style.
- **Dependencies:** Sub-slice 2a

**Sub-slice 2c: Edge routing cleanup**
- **Objective:** Use entry/exit point routing instead of explicit sourcePoint/targetPoint.
- **Files:** `src/migration_intake/topology/att_internal_generator.py`
- **Tests first:** `test_connector_uses_exit_entry_routing`
- **Acceptance:** Connectors use exitX/exitY + entryX/entryY, no sourcePoint/targetPoint mxPoints.
- **Dependencies:** Sub-slice 2a

**Sub-slice 2d: Container height auto-resize**
- **Objective:** Expand container and background rect height when generated content exceeds container.
- **Files:** `src/migration_intake/topology/att_internal_generator.py`
- **Tests first:** `test_container_height_expands_when_needed`
- **Acceptance:** When total row height > container height, container geometry is updated.
- **Dependencies:** Sub-slice 2a

### Slice 3: Static Sections Config

- **Objective:** Add `standard_sections` to profile and validate in E2E tests.
- **Files:** `outpost_v1.json`, `tests/unit/topology/test_haf_e2e.py`
- **Tests first:** `test_standard_sections_in_profile`, `test_e2e_standard_sections_unchanged`
- **Acceptance:** Sections documented and verified.
- **Dependencies:** Slice 0

### Slice 4: Template Update — AWS Tier 1 Container

- **Objective:** Add `aws_tier1_band` haf-role group cell with static icons to v1.7 template.
- **Files:** Template .drawio file
- **Tests first:** `test_template_has_aws_tier1_band_role`, `test_aws_tier1_container_geometry`
- **Test command:** `python -m pytest tests/unit/topology/test_haf_pipeline.py -q`
- **Acceptance:** `parse_haf_template()` returns `aws_tier1_band` in `all_roles`. All tests pass.
- **Dependencies:** Sub-slice 0e

### Slice 5: Direction Filter for Grouping

- **Objective:** Add `direction_filter: frozenset[str] | None = None` parameter to `group_interfaces_by_protocol_family()`.
- **Files:** `src/migration_intake/topology/interface_normalization.py`
- **Tests first:** `test_direction_filter_inbound_only`, `test_direction_filter_inbound_bidirectional`, `test_direction_filter_none_includes_all`, `test_aws_category_with_direction_filter`
- **Test command:** `python -m pytest tests/unit/topology/test_interface_normalization.py -q`
- **Acceptance:** All filter tests pass. Existing tests unaffected (default=None is backward compatible).
- **Dependencies:** Slice 0

### Slice 6: AWS Tier 1 Generator

**Sub-slice 6a: Generator skeleton with single group**
- **Objective:** Create `aws_tier1_generator.py` that generates one interface box + connector for one group.
- **Files:** New `src/migration_intake/topology/aws_tier1_generator.py`
- **Tests first:** `test_single_group_creates_interface_box`, `test_single_group_creates_connector`, `test_single_group_creates_edge_label`
- **Acceptance:** One group produces interface box, connector, and edge label.
- **Dependencies:** Slice 4

**Sub-slice 6b: Multiple groups, stacking, and colors**
- **Objective:** Support multiple groups with stacked rows and family-based connector colors.
- **Tests first:** `test_multiple_groups_stacked`, `test_connector_color_matches_family`
- **Acceptance:** Multiple groups render at increasing y positions with correct colors.
- **Dependencies:** Sub-slice 6a

**Sub-slice 6c: Container auto-resize**
- **Objective:** Expand AWS Tier 1 container height when many groups are generated.
- **Tests first:** `test_container_height_expanded`
- **Acceptance:** Container geometry height updated when rows exceed initial height.
- **Dependencies:** Sub-slice 6b

**Sub-slice 6d: Edge cases and idempotency**
- **Objective:** Handle empty groups, missing container, idempotent re-generation, label overflow.
- **Tests first:** `test_no_groups_produces_no_entries`, `test_container_not_found_graceful`, `test_idempotent_regeneration`, `test_comma_separated_labels`, `test_generated_ids_prefix`
- **Acceptance:** All edge case tests pass.
- **Dependencies:** Sub-slice 6b

### Slice 7: Wire AWS Tier 1 into Pipeline

- **Objective:** Connect AWS Tier 1 grouping and generation into extraction -> pipeline -> service.
- **Files:** `haf_extractor.py`, `haf_pipeline.py`, `haf_service.py`
- **Tests first:** `test_extractor_returns_aws_tier1_groups`, `test_extractor_excludes_outbound_aws`, `test_extractor_includes_bidirectional_aws`, `test_pipeline_calls_aws_generator`, `test_att_internal_unaffected`
- **Acceptance:** Integration tests pass. No regressions.
- **Dependencies:** Slices 5, 6

### Slice 8: E2E Validation + Final Comparison

**Sub-slice 8a: E2E tests with synthetic data**
- **Objective:** E2E tests with real template and synthetic AWS interfaces.
- **Tests first:** `test_e2e_aws_tier1_generated`, `test_e2e_standard_sections_unchanged`, `test_e2e_deterministic_with_aws`, `test_e2e_no_aws_interfaces_static_only`, `test_e2e_att_internal_still_correct`
- **Acceptance:** All E2E tests pass. Full suite green.
- **Dependencies:** Slice 7

**Sub-slice 8b: Final comparison against architect's CCPM**
- **Objective:** Run pipeline with real input template, compare output to architect's reference.
- **Input:** `docs/input_CCPM_AWS_Outpost_Topology_UNRESOLVED_UNRESOLVED-v1.7.drawio`
- **Reference:** `docs/CCPM__FINAL_18678_TargetState_AWS_OutPosts_v01 (1).drawio`
- **Artifacts:** `artifacts/final-comparison/<run-id>/`
- **Report:** `docs/aws-tier1-alignment-hardening-final-report.md`
- **Dependencies:** Sub-slice 8a

---

## 9. Backward Compatibility Considerations

| Change | Risk | Mitigation |
|---|---|---|
| New location aliases | None — adds mappings, doesn't change existing | Existing aliases unchanged |
| SQL_DB color change | Tests asserting #FF8000 will break | Update test assertions |
| tier2 category fix | Tests asserting UNKNOWN category for tier2 will break | Update test assertions |
| Connector target change | Tests asserting `target=container_id` will break | Update test assertions |
| Label style change | Tests asserting LABEL_STYLE will break | Update test assertions |
| `direction_filter` parameter | None — defaults to None (backward compatible) | Default preserves existing behavior |
| New `aws_tier1_groups` field | None — new optional field with default | Existing code doesn't reference it |

---

## 10. Risks and Mitigations

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Template positioning of AWS Tier 1 overlaps existing sections | Medium | High | Use exact coordinates from architect's CCPM |
| Container height expansion breaks layout for large datasets | Low | Medium | Test with 10+ groups and verify |
| Unknown location values across 300 apps | Medium | High | Slice 0 adds common aliases; UNKNOWN category still renders gracefully |
| Breaking existing tests with style/color changes | High | Low | Update assertions immediately in same sub-slice |
| draw.io rendering differences between versions | Low | Low | Use XML structure comparison, not pixel comparison |

---

## 11. TDD Strategy

For every sub-slice:
1. Write the failing test first (RED)
2. Run and verify it fails for the right reason
3. Implement minimum change (GREEN)
4. Run focused test + regression suite
5. Record in state.md

Test commands:
- Focused: `python -m pytest tests/unit/topology/test_<module>.py -q`
- Full regression: `python -m pytest tests/unit/topology/ -q`
- Expected baseline: **484 passed, 0 failed, 0 skipped**

---

## 12. Decision Log

| # | Decision | Rationale | Date |
|---|---|---|---|
| D1 | Update v1.7 template in-place | User-confirmed; simpler than version bump | Pre-session |
| D2 | Group AWS Tier 1 by protocol family | User-confirmed; consistent with ATT Internal | Pre-session |
| D3 | Include INBOUND + BIDIRECTIONAL for AWS Tier 1 | User-confirmed | Pre-session |
| D4 | Template legend is authoritative color source | Legend matches UI display; architect used ad-hoc colors | Discovery |
| D5 | No direct imports from drawpyo-main or multicloud-diagrams-main | Different architecture (object model vs template mutation) | Discovery |
| D6 | Use typed config module, not .env for constants | Business logic doesn't belong in environment variables | Design |
| D7 | Hardening slices first, then features | Prevents shipping bugs to 300 apps | Design |

---

## 13. Progress/Status

| Slice | Sub-slice | Status | Tests Added | Tests Passing |
|---|---|---|---|---|
| 0a | Location aliases | Pending | 0 | — |
| 0b | DATAGUARD/SMTP families | Pending | 0 | — |
| 0c | SQL_DB color fix | Pending | 0 | — |
| 0d | tier2 category fix | Pending | 0 | — |
| 0e | Template CCPM cleanup | Pending | 0 | — |
| 0f | Generic docstrings | Pending | 0 | — |
| 1 | Multi-app stress tests | Pending | 0 | — |
| 2a | Connector target | Pending | 0 | — |
| 2b | Label style | Pending | 0 | — |
| 2c | Edge routing | Pending | 0 | — |
| 2d | Container resize | Pending | 0 | — |
| 3 | Static sections config | Pending | 0 | — |
| 4 | Template AWS Tier 1 | Pending | 0 | — |
| 5 | Direction filter | Pending | 0 | — |
| 6a | Generator skeleton | Pending | 0 | — |
| 6b | Multiple groups/colors | Pending | 0 | — |
| 6c | Container resize | Pending | 0 | — |
| 6d | Edge cases | Pending | 0 | — |
| 7 | Pipeline wiring | Pending | 0 | — |
| 8a | E2E tests | Pending | 0 | — |
| 8b | Final comparison | Pending | 0 | — |
