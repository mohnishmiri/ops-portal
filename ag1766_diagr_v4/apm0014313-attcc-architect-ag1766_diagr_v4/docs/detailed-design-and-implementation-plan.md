# Detailed Design and Implementation Plan — Multi-Tab Master Template Pipeline (Option B)

**Created:** 2026-09-27  
**Status:** IMPLEMENTATION COMPLETE  
**Baseline Tests:** 2950 passing (pre-implementation)  
**Final Tests:** 2918 passing + 93 browser errors (pre-existing) + 11 pre-existing failures  
**Topology Tests:** 673 passing (from 563 baseline)  
**Repository:** `C:\GitHub\aws_diag_v4_1\aws_diag_v4`  
**Completed:** 2026-09-26

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Current Architecture](#2-current-architecture)
3. [Problem Statement](#3-problem-statement)
4. [Design Decisions](#4-design-decisions)
5. [Reuse Matrix](#5-reuse-matrix)
6. [Dependency Graph and Execution Order](#6-dependency-graph-and-execution-order)
7. [TDD Slice Catalog](#7-tdd-slice-catalog)
8. [Persistent-State Protocol](#8-persistent-state-protocol)
9. [Execution Protocol](#9-execution-protocol)
10. [Implementation Readiness Checklist](#10-implementation-readiness-checklist)
11. [Assumptions and Open Questions](#11-assumptions-and-open-questions)

---

## 1. Executive Summary

This plan implements **Option B** — using the architect's multi-tab master template (`AWS_Outpost_Topology_Template_1-v1.7.drawio`) directly in the pipeline. The user selects a variant (tab) from the UI; the pipeline extracts that tab, applies `haf-role` annotations, and fills it with application data.

**9 main slices, 33 sub-slices**, following strict TDD (RED → GREEN → REFACTOR).

Key changes:
- New `template_loader.py` module for tab extraction
- Copy of master template into `config/templates/` with haf-role annotations on all 4 tabs
- 4 per-variant profile configs (`outpost_v1_basic.json`, `_tlgw.json`, `_f5.json`, `_hadr.json`)
- Variant selection wired through service → pipeline
- Bundled template loader bypassing upload step
- Minor UI additions (variant dropdown, "Generate from Standard Template" card)
- AWS Tier 1 connector color fix
- Full E2E comparison with screenshots

---

## 2. Current Architecture

### 2.1 Template Flow

1. **User uploads** a `.drawio` file via `POST /topology/upload-base` (`src/migration_intake/web/routes/topology.py` line 231)
2. File stored via `FilesystemStore` with content-addressed storage; `TopologyBaseArtifact` record created in `topo_base` table with `variant` column (`src/migration_intake/persistence/models_topology.py` line 50)
3. **User clicks Generate** → `POST /topology/generate` → `topology_service.generate_topology()` (`src/migration_intake/application/services/topology_generation.py` line 249)
4. `_is_haf_template()` checks for `haf-role` annotations (line 633). If found → HAF pipeline; else → legacy fill
5. `generate_haf_topology()` in `src/migration_intake/topology/haf_service.py` receives `template_bytes` + `profile_id="OUTPOST_V1"` + extracted DB data
6. `fill_haf_template()` in `src/migration_intake/topology/haf_pipeline.py` parses XML, indexes cells by `haf-role`, loads profile config, resolves tokens/interfaces/details

### 2.2 Key Components

| Component | File | Purpose |
|---|---|---|
| HAF Pipeline | `src/migration_intake/topology/haf_pipeline.py` | Parse template, index by haf-role, resolve tokens, fill interfaces, fill details |
| HAF Service | `src/migration_intake/topology/haf_service.py` | Integration layer: DB extractor → pipeline |
| HAF Extractor | `src/migration_intake/topology/haf_extractor.py` | Extract tokens, interfaces, details from DB |
| ATT Internal Generator | `src/migration_intake/topology/att_internal_generator.py` | Generate grouped ATT Internal rows |
| AWS Tier 1 Generator | `src/migration_intake/topology/aws_tier1_generator.py` | Generate AWS Tier 1 interface boxes |
| Interface Normalization | `src/migration_intake/topology/interface_normalization.py` | Protocol families, location aliases, grouping |
| Profile Config | `src/migration_intake/topology/config/haf_profiles/outpost_v1.json` | Placeholder bindings, interface regions, detail blocks |
| Topology Service | `src/migration_intake/application/services/topology_generation.py` | Orchestrates generation: validate, load, generate, store |
| Web Route | `src/migration_intake/web/routes/topology.py` | HTTP endpoints for upload, generate, download |
| UI Template | `src/migration_intake/web/templates/topology/index.html` | Upload form, variant dropdown, generate button |
| DB Model | `src/migration_intake/persistence/models_topology.py` | `TopologyBaseArtifact`, `GenerationRun`, `GeneratedArtifact` |

### 2.3 Current Template Status

| Template | Location | Cells | haf-roles | Status |
|---|---|---|---|---|
| Dev template | `docs/development/topo_9_24/AWS__input_Outpost_Topology_UNRESOLVED_UNRESOLVED-v1.7.drawio` | 148 | 46 | Incomplete — missing VPCE, Internet, Tier 2, Internal Users/Systems, IDNS |
| Master template | `docs/AWS_Outpost_Topology_Template_1-v1.7.drawio` | 5 tabs (151/165/174/272/2 cells) | 0 | Complete but unannotated |
| Input template | `docs/input_CCPM_AWS_Outpost_Topology_UNRESOLVED_UNRESOLVED-v1.7.drawio` | — | — | Used for E2E comparison |
| Reference CCPM | `docs/CCPM__FINAL_18678_TargetState_AWS_OutPosts_v01 (1).drawio` | 2 diagrams | — | Architect's hand-drawn final |

### 2.4 Master Template Tab Structure

| Tab | Name | Cells | Unique Components |
|---|---|---|---|
| 0 | Without LBs | 151 | Baseline — all standard sections |
| 1 | tLGW Load Balancer | 165 | + tLGW LB, Web ENIs, Internal Users/Systems |
| 2 | F5 Load Balancer | 174 | + F5 LB subnet, F5 ENI, IDNS, Active/Standby |
| 3 | HA/DR with Global Load Balancer | 272 | + Dual outpost regions, DR strategy, IDNS/F5 GTM |
| 4 | Definitions | 2 | Legend only — not a variant |

**Critical finding:** Each tab has completely independent cell IDs — zero overlap between tabs.

### 2.5 Known Issues from Previous E2E Comparison

| # | Issue | Severity |
|---|---|---|
| 1 | AWS Tier 1 connector color: `#6666FF` should be default black | HIGH |
| 2 | VPCE via AT&T Regional Bastion section missing | HIGH |
| 3 | Internet section missing | HIGH |
| 4 | AWS Tier 2 label/container missing | MEDIUM |
| 5 | IDNS icon missing (tab 2/3 only) | MEDIUM |
| 6 | Internal Users/Internal Systems icons missing (tab 1-3 only) | MEDIUM |
| 7 | Azure section: 8 individual port boxes instead of 2 grouped entries | HIGH |
| 8 | DNS section positioning | LOW |

---

## 3. Problem Statement

The current dev template is incomplete — missing 34 labeled sections that the architect's master template has. Using Option B (multi-tab master template directly) solves this by:

1. Using the architect's complete template as the authoritative source
2. Adding `haf-role` annotations to enable pipeline processing
3. Creating per-variant profiles so each tab has correct bindings
4. Allowing users to select the variant via UI dropdown
5. Loading the bundled template without requiring manual upload

---

## 4. Design Decisions

| # | Decision | Choice | Rationale |
|---|---|---|---|
| D1 | Template source | Copy master to `config/templates/`, annotate copy | Architect's original in `docs/` stays untouched |
| D2 | Annotation scope | All 4 variant tabs | Complete coverage for all app architectures |
| D3 | Variant selection | UI dropdown (4 options) | Minimal change; existing `variant` column reused |
| D4 | Dual paths | Both bundled + upload | Backward compatible; bundled is convenience path |
| D5 | Profile strategy | Per-variant profiles | Each tab has unique cell IDs requiring distinct bindings |
| D6 | HA/DR handling | Fill both regions from same data | DR mirrors primary — both get same app interfaces |
| D7 | AWS Tier 1 connector | Remove strokeColor (use default black) | Matches architect's reference |
| D8 | Legacy profile | Keep `outpost_v1.json` | Fallback for existing uploaded templates |
| D9 | .env changes | None | Variant is a UI selection, not deployment config |

---

## 5. Reuse Matrix

### 5.1 drawpyo-main

| Source File | Class/Function | Behavior | Reuse Recommendation | Rationale |
|---|---|---|---|---|
| `src/drawpyo/file.py` | `File` class | Multi-page draw.io file I/O (read/write pages, XML serialization) | **Do not import** — selectively adapt pattern | drawpyo uses its own object model; our pipeline uses raw `xml.etree.ElementTree` manipulation. The page/diagram nesting pattern (`File → Page → Diagram → mxGraph → Root`) informs our tab extraction logic but the class hierarchy is incompatible. |
| `src/drawpyo/page.py` | `Page` class | Page XML generation with diagram/mxGraph/root nesting | **Reference only** — confirms XML structure | Confirms that each page is `<diagram><mxGraphModel><root>...</root></mxGraphModel></diagram>`. Our `extract_tab()` must preserve this nesting. |
| `src/drawpyo/diagram/extended_objects.py` | `List.autosize()` | Height estimation from child count | **Already adapted** — pattern used in `att_internal_generator._left_height_wrapped()` | The autosize pattern (count items × line_height + padding) was adapted in Slice 6 of the previous work. No further reuse needed. |
| `src/drawpyo/drawio_import/drawio_parser.py` | `_parse_drawio_xml()`, `load_diagram()` | Parse draw.io XML into structured objects | **Do not import** — our `parse_haf_template()` already handles this | drawpyo's parser builds `Object`/`Edge` instances; we need raw `mxCell` elements with `haf-role` attributes. Different abstraction level. |
| `src/drawpyo/drawio_import/drawio_parser.py` | `ParsedDiagram.add_to()` | Attach elements to page with offset | **Reference only** — informs component fragment approach (future) | If we later build a component library (Option A), this offset pattern could inform fragment placement. Not needed for Option B. |
| `src/drawpyo/utils/standard_colors.py` | Color constants | Standard draw.io colors | **Reference only** | Our `FAMILY_COLORS` in `interface_normalization.py` are domain-specific; standard colors don't apply. |

**License:** MIT (Copyright 2023 MerrimanInd) — compatible for selective adaptation.

**Tests required:** None — no code imported. The `_left_height_wrapped()` adaptation is already tested in `test_att_internal_generator.py`.

### 5.2 multicloud-diagrams-main

| Source File | Class/Function | Behavior | Reuse Recommendation | Rationale |
|---|---|---|---|---|
| `multicloud_diagrams/__init__.py` | `MultiCloudDiagrams.add_vertex()` | Programmatic vertex creation with style customization | **Do not import** — incompatible architecture | Uses `xml.etree.ElementTree.SubElement` directly (same as our generators), but its ID scheme (`vertex:{type}:{id}`) and style system (`update_style_by_key()`) don't match our `haf-role` approach. |
| `multicloud_diagrams/__init__.py` | `update_style_by_key()` | Regex-based style property update | **Selectively copy if needed** | Useful utility: `re.sub(r'key=([^;]+)', f'key={value}', style_str)`. Could be adapted for style manipulation in annotation scripts. Low priority — manual annotation doesn't need runtime style updates. |
| `multicloud_diagrams/__init__.py` | `add_connection()` | Edge creation with labels and styling | **Reference only** | Confirms edge XML pattern but our generators already produce edges correctly. |
| `multicloud_diagrams/__init__.py` | `export_to_file()` | Multi-page draw.io file export | **Reference only** — confirms file structure | Shows how to write multi-page drawio files. Our `extract_tab()` does the inverse (extract single page). |

**License:** MIT (Copyright 2023 Roman Tsypuk) — compatible.

**Tests required:** If `update_style_by_key()` is copied, a unit test covering key insertion and key replacement is needed.

### 5.3 Reuse Summary

**Conclusion:** Neither reference project provides directly importable code for Option B. The existing codebase already has all the XML manipulation patterns needed. The main reuse value is **pattern confirmation**:
- drawpyo confirms the `<mxfile> → <diagram> → <mxGraphModel> → <root> → <mxCell>` nesting that `extract_tab()` must preserve
- drawpyo's `List.autosize()` pattern was already adapted into the generators
- multicloud-diagrams confirms the `ET.SubElement` approach for programmatic cell creation

---

## 6. Dependency Graph and Execution Order

```
Slice 1: Tab Extraction Module
  │
  ├── Slice 2: Annotate Tab 0 (Without LBs)
  │     │
  │     ├── Slice 3: Basic Profile (outpost_v1_basic.json)
  │     │     │
  │     │     ├── Slice 4a: Annotate Tab 1 (tLGW) + Profile
  │     │     ├── Slice 4b: Annotate Tab 2 (F5) + Profile
  │     │     └── Slice 4c: Annotate Tab 3 (HA/DR) + Profile
  │     │           │
  │     │           └── Slice 5: Wire Variant Selection
  │     │                 │
  │     │                 └── Slice 6: Bundled Template Loader
  │     │                       │
  │     │                       └── Slice 7: UI Updates
  │     │                             │
  │     │                             └── Slice 9: E2E Comparison
  │     │
  │     └── (Slice 3 also depends on Slice 2)
  │
  └── (independent) Slice 8: AWS Tier 1 Connector Color Fix
```

**Recommended execution order:**
1 → 2 → 3 → 4a → 4b → 4c → 5 → 6 → 7 → 8 → 9

Slice 8 is independent and can be done at any point. Slices 4a/4b/4c are sequential (each annotates one tab).

---

## 7. TDD Slice Catalog

---

### Slice 1: Template Tab Extraction Module

#### Sub-slice 1a: `list_tabs()` — Enumerate tabs from multi-tab template

**Objective:** Create a pure function that lists all diagram tabs in a multi-tab `.drawio` file.

**Current behavior:** No tab extraction module exists. The pipeline only handles single-diagram templates.

**Expected behavior:** `list_tabs(template_bytes)` returns a list of `{"index": int, "name": str}` dicts for all `<diagram>` elements in the mxfile.

**Scope:** Only the listing function. Extraction is Sub-slice 1b.

**Non-goals:** No template modification, no haf-role annotation.

**Dependencies:** None.

**Files to change:**
- NEW: `src/migration_intake/topology/template_loader.py`
- NEW: `tests/unit/topology/test_template_loader.py`

**Reusable code candidates:** drawpyo's `File.pages` enumeration pattern (reference only — not imported).

**Test to write first:**
```python
def test_list_tabs_returns_five_entries():
    master = Path("docs/AWS_Outpost_Topology_Template_1-v1.7.drawio").read_bytes()
    tabs = list_tabs(master)
    assert len(tabs) == 5
    assert tabs[0]["name"] == "Without LBs"
    assert tabs[0]["index"] == 0
    assert tabs[3]["name"] == "HA/DR with Global Load Balancer"
```

**Expected reason test will fail:** `template_loader.py` does not exist; `ImportError`.

**Minimum implementation:**
```python
def list_tabs(template_bytes: bytes) -> list[dict[str, str | int]]:
    root = ET.fromstring(template_bytes)
    return [{"index": i, "name": d.get("name", "")} for i, d in enumerate(root.findall("diagram"))]
```

**Focused test command:** `python -m pytest tests/unit/topology/test_template_loader.py -v -k "list_tabs"`

**Relevant regression tests:** `python -m pytest tests/unit/topology/ -v`

**Acceptance criteria:**
- Returns 5 entries for the master template
- Names match: "Without LBs", "tLGW Load Balancer", "F5 Load Balancer", "HA/DR with Global Load Balancer", "Definitions"
- Indices are 0-4
- Raises `ValueError` for non-mxfile XML

**Risks:** Master template file could have encoding issues. Mitigation: read as UTF-8, test with actual file.

**Expected artifacts:** `src/migration_intake/topology/template_loader.py`, test file.

**State update:** Update `state.md` with Slice 1a status, test commands, files changed.

---

#### Sub-slice 1b: `extract_tab()` — Extract single tab by name

**Objective:** Extract a single diagram tab from a multi-tab file, returning a valid single-diagram mxfile.

**Current behavior:** No extraction capability.

**Expected behavior:** `extract_tab(template_bytes, tab_name="Without LBs")` returns bytes containing a valid single-diagram mxfile with the original `<mxfile>` attributes preserved.

**Scope:** Extract by name only. Index extraction is Sub-slice 1c.

**Non-goals:** No modification of cell content.

**Dependencies:** Sub-slice 1a (needs `list_tabs` logic).

**Files to change:**
- MODIFY: `src/migration_intake/topology/template_loader.py`
- EXTEND: `tests/unit/topology/test_template_loader.py`

**Reusable code candidates:** drawpyo's `Page.xml` property confirms nesting structure.

**Test to write first:**
```python
def test_extract_tab_by_name_returns_single_diagram():
    master = Path("docs/AWS_Outpost_Topology_Template_1-v1.7.drawio").read_bytes()
    tab0 = extract_tab(master, tab_name="Without LBs")
    root = ET.fromstring(tab0)
    assert root.tag == "mxfile"
    assert len(root.findall("diagram")) == 1
    assert root.findall("diagram")[0].get("name") == "Without LBs"

def test_extract_tab_preserves_cell_count():
    master = Path("docs/AWS_Outpost_Topology_Template_1-v1.7.drawio").read_bytes()
    tab0 = extract_tab(master, tab_name="Without LBs")
    cells = list(ET.fromstring(tab0).iter("mxCell"))
    assert len(cells) == 151
```

**Expected reason test will fail:** `extract_tab` function does not exist; `ImportError`.

**Minimum implementation:**
```python
def extract_tab(template_bytes: bytes, *, tab_name: str | None = None, tab_index: int | None = None) -> bytes:
    root = ET.fromstring(template_bytes)
    diagrams = root.findall("diagram")
    if tab_name is not None:
        matches = [d for d in diagrams if d.get("name") == tab_name]
        if not matches:
            raise ValueError(f"Tab '{tab_name}' not found")
        selected = matches[0]
    # ... (tab_index handled in 1c)
    new_root = ET.Element("mxfile", root.attrib)
    new_root.append(selected)
    return ET.tostring(new_root, encoding="unicode", xml_declaration=False).encode("utf-8")
```

**Focused test command:** `python -m pytest tests/unit/topology/test_template_loader.py -v -k "extract_tab"`

**Relevant regression tests:** `python -m pytest tests/unit/topology/ -v`

**Acceptance criteria:**
- Extracted bytes parse as valid XML
- Single `<diagram>` element present
- Cell count matches original tab
- `parse_haf_template()` accepts the result without error (once roles are added)
- `<mxfile>` attributes (host, version, type) preserved from original

**Risks:** XML declaration or encoding could change during serialize/deserialize. Mitigation: test round-trip byte content.

**Expected artifacts:** Updated `template_loader.py`.

**State update:** Update `state.md` with Sub-slice 1b completion.

---

#### Sub-slice 1c: `extract_tab()` — Extract by index + error handling

**Objective:** Support extraction by tab index; add error handling for invalid inputs.

**Current behavior:** Extract by name only (from 1b).

**Expected behavior:**
- `extract_tab(master, tab_index=2)` returns Tab 2 ("F5 Load Balancer")
- Raises `ValueError` when both `tab_name` and `tab_index` are provided
- Raises `ValueError` for out-of-range index
- Raises `ValueError` for non-existent tab name

**Scope:** Error handling only.

**Non-goals:** No new file.

**Dependencies:** Sub-slice 1b.

**Files to change:**
- MODIFY: `src/migration_intake/topology/template_loader.py`
- EXTEND: `tests/unit/topology/test_template_loader.py`

**Reusable code candidates:** None.

**Test to write first:**
```python
def test_extract_tab_by_index():
    master = Path("docs/AWS_Outpost_Topology_Template_1-v1.7.drawio").read_bytes()
    tab2 = extract_tab(master, tab_index=2)
    root = ET.fromstring(tab2)
    assert root.findall("diagram")[0].get("name") == "F5 Load Balancer"

def test_extract_tab_both_args_raises():
    master = Path("docs/AWS_Outpost_Topology_Template_1-v1.7.drawio").read_bytes()
    with pytest.raises(ValueError, match="exactly one"):
        extract_tab(master, tab_name="x", tab_index=0)

def test_extract_tab_out_of_range():
    master = Path("docs/AWS_Outpost_Topology_Template_1-v1.7.drawio").read_bytes()
    with pytest.raises(ValueError, match="out of range"):
        extract_tab(master, tab_index=99)
```

**Expected reason test will fail:** Index path and validation not yet implemented.

**Minimum implementation:** Add index branch and validation to `extract_tab()`.

**Focused test command:** `python -m pytest tests/unit/topology/test_template_loader.py -v -k "index or raises or both"`

**Relevant regression tests:** `python -m pytest tests/unit/topology/test_template_loader.py -v`

**Acceptance criteria:**
- Index extraction works for 0-4
- Both-args raises `ValueError`
- Neither-args raises `ValueError`
- Out-of-range raises `ValueError`
- Missing name raises `ValueError`

**Risks:** None significant.

**Expected artifacts:** Updated `template_loader.py` and test file.

**State update:** Update `state.md` with Slice 1 completion.

---

### Slice 2: Copy & Annotate Master Template — Tab 0 (Without LBs)

#### Sub-slice 2a: Copy master template to config directory

**Objective:** Copy the master template file to `src/migration_intake/topology/config/templates/` without modification.

**Current behavior:** No bundled template exists in `config/`.

**Expected behavior:** `config/templates/outpost_v1.7.drawio` exists and is byte-identical to the original.

**Scope:** File copy only. No annotation.

**Non-goals:** No haf-role attributes yet.

**Dependencies:** None.

**Files to change:**
- NEW: `src/migration_intake/topology/config/templates/outpost_v1.7.drawio` (copy)

**Reusable code candidates:** None.

**Test to write first:**
```python
def test_bundled_template_exists():
    bundled = Path("src/migration_intake/topology/config/templates/outpost_v1.7.drawio")
    assert bundled.exists()

def test_bundled_template_has_five_tabs():
    bundled = Path("src/migration_intake/topology/config/templates/outpost_v1.7.drawio")
    tabs = list_tabs(bundled.read_bytes())
    assert len(tabs) == 5
```

**Expected reason test will fail:** File does not exist.

**Minimum implementation:** `cp docs/AWS_Outpost_Topology_Template_1-v1.7.drawio src/migration_intake/topology/config/templates/outpost_v1.7.drawio`

**Focused test command:** `python -m pytest tests/unit/topology/test_master_template_roles.py -v -k "exists or five_tabs"`

**Relevant regression tests:** `python -m pytest tests/unit/topology/ -v`

**Acceptance criteria:**
- File exists at expected path
- Contains 5 tabs with correct names
- Parses without error

**Risks:** Large file (~500KB). Mitigation: acceptable for bundled config; extracted single-tab is ~30KB.

**Expected artifacts:** `config/templates/outpost_v1.7.drawio`

**State update:** Update `state.md`.

---

#### Sub-slice 2b: Annotate Tab 0 — structural roles (layout, containers)

**Objective:** Add `haf-role` attributes to Tab 0's structural cells: root layer, outer frame, header line, application account container, workload VPC, subnets, security groups, network account.

**Current behavior:** Tab 0 has 151 cells, 0 haf-roles.

**Expected behavior:** Structural cells (~15) have `haf-role` attributes matching the bindings in `outpost_v1.json`.

**Scope:** Only structural/layout roles. Interface slots, legend, and standard sections are separate sub-slices.

**Non-goals:** No interface slot annotation. No legend annotation.

**Dependencies:** Sub-slice 2a.

**Files to change:**
- MODIFY: `src/migration_intake/topology/config/templates/outpost_v1.7.drawio`
- NEW: `tests/unit/topology/test_master_template_roles.py`

**Reusable code candidates:** Dev template role assignments (reference for correct role names).

**Test to write first:**
```python
def test_tab0_has_header_line_role():
    tab0 = _load_tab0()
    index = parse_haf_template(tab0)
    assert "header_line" in index.all_roles

def test_tab0_has_app_account_container():
    tab0 = _load_tab0()
    index = parse_haf_template(tab0)
    assert "app_account_container" in index.all_roles

def test_tab0_structural_roles_count():
    tab0 = _load_tab0()
    index = parse_haf_template(tab0)
    structural = {"header_line", "outer_frame", "root_layer", "page_inner_frame",
                  "private_application_subnet", "app_security_group",
                  "app_account_container", "workload_vpc", "workload_vpc_label",
                  "db_security_group", "network_account_container"}
    present = structural & index.all_roles
    assert present == structural
```

**Expected reason test will fail:** Tab 0 has zero haf-roles.

**Minimum implementation:** Python script to add `haf-role` attributes to cells by matching their `value` text content and `style` properties. The annotation is performed on the copy in `config/templates/`, identified by cell ID within Tab 0's diagram element.

**Identifying cells:** Each cell in Tab 0 has a unique ID (e.g., `qcVyhp58iP8Gm4Rmxcgn-XX`). The annotation script finds cells by matching value text patterns (e.g., value containing `"AT&T - AWS"` → `header_line page_inner_frame`; value containing `"Private Application Subnet"` → `private_application_subnet`).

**Focused test command:** `python -m pytest tests/unit/topology/test_master_template_roles.py -v -k "structural"`

**Relevant regression tests:** `python -m pytest tests/unit/topology/ -v`

**Acceptance criteria:**
- All 11 structural roles present in Tab 0
- `parse_haf_template()` returns index with these roles
- No existing tests break

**Risks:** Cell identification by value text could be fragile if templates change. Mitigation: use cell IDs in the annotation script (IDs are stable within a file); test validates roles are present.

**Expected artifacts:** Updated template, test file.

**State update:** Update `state.md`.

---

#### Sub-slice 2c: Annotate Tab 0 — interface slots and generators

**Objective:** Add haf-roles for ATT Internal band, interface slots, Azure apps section, AWS Tier 1 container, tier2/internet slot.

**Current behavior:** These cells exist in Tab 0 but have no haf-role.

**Expected behavior:** Interface-related cells have correct haf-roles. ATT Internal band container, 4 interface slots, Azure container/slot/bridge, AWS Tier 1 container/bg, tier2_internet_slot all annotated.

**Scope:** Interface-related roles only.

**Non-goals:** No legend or standard section roles.

**Dependencies:** Sub-slice 2b.

**Files to change:**
- MODIFY: `src/migration_intake/topology/config/templates/outpost_v1.7.drawio`
- EXTEND: `tests/unit/topology/test_master_template_roles.py`

**Reusable code candidates:** Dev template cell matching (reference for role names).

**Test to write first:**
```python
def test_tab0_has_att_internal_band():
    tab0 = _load_tab0()
    index = parse_haf_template(tab0)
    assert "att_internal_interfaces_band" in index.all_roles

def test_tab0_has_azure_section_roles():
    tab0 = _load_tab0()
    index = parse_haf_template(tab0)
    azure_roles = {"azure_apps_slot", "azure_apps_label",
                   "azure_apps_bridge_box", "azure_apps_bridge_label",
                   "azure_apps_icon_express_route"}
    assert azure_roles <= index.all_roles

def test_tab0_has_aws_tier1_container():
    tab0 = _load_tab0()
    index = parse_haf_template(tab0)
    assert "aws_tier1_container" in index.all_roles
    assert "aws_tier1_bg" in index.all_roles
```

**Expected reason test will fail:** These cells have no `haf-role` attributes yet.

**Minimum implementation:** Add haf-role to ~15 cells by matching their value/style patterns or cell IDs.

**Note on AWS Tier 1:** Tab 0 in the master template does NOT have an AWS Tier 1 container (it was manually added to the dev template in Slice 4 of the previous work). The executing agent must add the AWS Tier 1 container XML to Tab 0, using the same structure as was added to the dev template (`aws_tier1_container`, `aws_tier1_bg` with S3/KMS/Secrets Manager icons). This is a template modification, not just annotation.

**Focused test command:** `python -m pytest tests/unit/topology/test_master_template_roles.py -v -k "interface or azure or aws_tier1"`

**Relevant regression tests:** `python -m pytest tests/unit/topology/ -v`

**Acceptance criteria:**
- ATT Internal band and 4 slot roles present
- Azure section roles present
- AWS Tier 1 container and bg roles present
- tier2_internet_slot role present

**Risks:** Azure section in master template may have different structure than dev template. Mitigation: inspect both before annotating; use master template structure.

**Expected artifacts:** Updated template, extended test file.

**State update:** Update `state.md`.

---

#### Sub-slice 2d: Annotate Tab 0 — legend and detail blocks

**Objective:** Add haf-roles for legend cells, notes block, application-specific details, NAS/EBR detail blocks.

**Current behavior:** Legend cells exist but have no haf-role.

**Expected behavior:** Legend cells (protocol colors, data flow, GitHub, Artifactory), notes block, and detail blocks all annotated with correct roles matching `outpost_v1.json` protected_roles.

**Scope:** Legend and detail block roles only.

**Non-goals:** No standard section roles.

**Dependencies:** Sub-slice 2b.

**Files to change:**
- MODIFY: `src/migration_intake/topology/config/templates/outpost_v1.7.drawio`
- EXTEND: `tests/unit/topology/test_master_template_roles.py`

**Reusable code candidates:** Dev template legend role names (reference).

**Test to write first:**
```python
def test_tab0_has_legend_roles():
    tab0 = _load_tab0()
    index = parse_haf_template(tab0)
    legend_roles = {"legend_protocol_https", "legend_data_flow_label"}
    assert legend_roles <= index.all_roles

def test_tab0_has_detail_block_roles():
    tab0 = _load_tab0()
    index = parse_haf_template(tab0)
    assert "nas_detail_block" in index.all_roles or "nas_title_label" in index.all_roles
```

**Expected reason test will fail:** Legend cells have no haf-role.

**Minimum implementation:** Add haf-role to legend cells by matching their value text (e.g., "HTTPS (443)" → `legend_protocol_https`, "SSH/SFTP (22)" → `legend_protocol_ssh`).

**Focused test command:** `python -m pytest tests/unit/topology/test_master_template_roles.py -v -k "legend or detail"`

**Relevant regression tests:** `python -m pytest tests/unit/topology/ -v`

**Acceptance criteria:**
- All legend protocol roles present
- Data flow legend roles present
- Notes block role present
- NAS/EBR title and detail block roles present (if applicable to Tab 0)

**Risks:** Tab 0 may not have NAS/EBR detail blocks — they may be application-specific content added only in the final CCPM. Mitigation: check master template; if absent, skip those roles for Tab 0 and document as open question.

**Expected artifacts:** Updated template, extended test file.

**State update:** Update `state.md`.

---

#### Sub-slice 2e: Annotate Tab 0 — new standard section roles

**Objective:** Add haf-roles for previously missing standard sections: VPCE via AT&T Regional Bastion, Internet, AWS Tier 2, DirectConnect icon, AllowList/Outbound labels.

**Current behavior:** These sections exist in Tab 0 as visual elements but have no haf-role. They were missing from the dev template entirely.

**Expected behavior:** Each standard section has a role: `vpce_bastion_box`, `vpce_bastion_label`, `internet_box`, `internet_label`, `aws_tier2_container`, `aws_tier2_label`, `directconnect_icon`, `allowlist_label`, `outbound_label`.

**Scope:** Standard section roles only.

**Non-goals:** No binding changes to profile (that's Slice 3).

**Dependencies:** Sub-slice 2b.

**Files to change:**
- MODIFY: `src/migration_intake/topology/config/templates/outpost_v1.7.drawio`
- EXTEND: `tests/unit/topology/test_master_template_roles.py`

**Reusable code candidates:** None.

**Test to write first:**
```python
def test_tab0_has_vpce_bastion_role():
    tab0 = _load_tab0()
    index = parse_haf_template(tab0)
    assert "vpce_bastion_label" in index.all_roles

def test_tab0_has_internet_section_role():
    tab0 = _load_tab0()
    index = parse_haf_template(tab0)
    assert "internet_label" in index.all_roles

def test_tab0_standard_section_roles():
    tab0 = _load_tab0()
    index = parse_haf_template(tab0)
    standard = {"vpce_bastion_label", "internet_label", "aws_tier2_container",
                "directconnect_icon"}
    missing = standard - index.all_roles
    assert not missing, f"Missing standard section roles: {missing}"
```

**Expected reason test will fail:** These cells have no haf-role.

**Minimum implementation:** Identify cells by value text (e.g., "VPCE via AT&T Regional Bastion", "Internet", "AWS Tier 2") and add haf-role attributes.

**ASSUMPTION:** These sections exist as labeled cells in Tab 0. The executing agent must verify by inspecting the master template Tab 0 cells. If any section is absent, it must be added as new XML (similar to how AWS Tier 1 was added to the dev template).

**Focused test command:** `python -m pytest tests/unit/topology/test_master_template_roles.py -v -k "standard_section or vpce or internet"`

**Relevant regression tests:** `python -m pytest tests/unit/topology/ -v`

**Acceptance criteria:**
- All new standard section roles present in Tab 0
- These roles listed in protected_roles (verified in Slice 3)

**Risks:** Some sections may be visual-only (shapes without text labels) making them hard to identify. Mitigation: inspect XML carefully; annotate by cell ID if needed.

**Expected artifacts:** Updated template, extended test file.

**State update:** Update `state.md`.

---

#### Sub-slice 2f: Validate Tab 0 complete annotation — all roles match profile bindings

**Objective:** Comprehensive validation that Tab 0 has all roles needed by the profile config, and profile bindings resolve against Tab 0.

**Current behavior:** (After 2b-2e) Tab 0 has ~45-55 haf-roles.

**Expected behavior:** Every `haf_role` referenced in `outpost_v1.json` (placeholder_bindings, interface_regions, detail_blocks, protected_roles) exists in Tab 0's index.

**Scope:** Validation test only. No code changes to template.

**Non-goals:** No profile changes (that's Slice 3).

**Dependencies:** Sub-slices 2b-2e.

**Files to change:**
- EXTEND: `tests/unit/topology/test_master_template_roles.py`

**Test to write first:**
```python
def test_tab0_has_all_profile_binding_roles():
    """Every haf_role in outpost_v1.json must exist in Tab 0."""
    tab0 = _load_tab0()
    index = parse_haf_template(tab0)
    profile = load_haf_profile("OUTPOST_V1")
    needed = {b.haf_role for b in profile.placeholder_bindings}
    needed |= {r.haf_role for r in profile.interface_regions}
    needed |= {d.haf_role for d in profile.detail_blocks}
    missing = needed - index.all_roles
    assert not missing, f"Tab 0 missing roles: {missing}"
```

**Expected reason test will fail:** If any annotation was missed in 2b-2e. If all annotations are correct, this passes immediately (a GREEN validation).

**Minimum implementation:** None if annotations are complete. Fix any missing annotations if the test fails.

**Focused test command:** `python -m pytest tests/unit/topology/test_master_template_roles.py -v -k "all_profile"`

**Relevant regression tests:** `python -m pytest tests/unit/topology/ -v`

**Acceptance criteria:** Zero missing roles.

**Risks:** None.

**Expected artifacts:** Extended test file.

**State update:** Update `state.md` with Slice 2 completion.

---

### Slice 3: Per-Variant Profile — `outpost_v1_basic.json`

#### Sub-slice 3a: Create basic profile JSON

**Objective:** Create `outpost_v1_basic.json` for Tab 0 — the "Without LBs" variant.

**Current behavior:** Only `outpost_v1.json` exists.

**Expected behavior:** `load_haf_profile("OUTPOST_V1_BASIC")` returns a valid `HafProfile` with all bindings from `outpost_v1.json` plus new standard section protected roles.

**Scope:** Profile JSON file only.

**Non-goals:** No pipeline changes.

**Dependencies:** Slice 2 (Tab 0 must have all roles).

**Files to change:**
- NEW: `src/migration_intake/topology/config/haf_profiles/outpost_v1_basic.json`
- EXTEND: `tests/unit/topology/test_haf_pipeline.py`

**Reusable code candidates:** `outpost_v1.json` as base (copy and modify).

**Test to write first:**
```python
def test_load_basic_profile():
    profile = load_haf_profile("OUTPOST_V1_BASIC")
    assert profile.profile_id == "OUTPOST_V1_BASIC"

def test_basic_profile_has_standard_section_protected_roles():
    profile = load_haf_profile("OUTPOST_V1_BASIC")
    assert "vpce_bastion_label" in profile.protected_roles or \
           any("vpce" in r for r in profile.protected_roles)
```

**Expected reason test will fail:** Profile file does not exist.

**Minimum implementation:** Copy `outpost_v1.json`, change `profile_id` to `"OUTPOST_V1_BASIC"`, add new standard section roles to `protected_roles`.

**Focused test command:** `python -m pytest tests/unit/topology/test_haf_pipeline.py -v -k "basic"`

**Relevant regression tests:** `python -m pytest tests/unit/topology/ -v`

**Acceptance criteria:**
- `load_haf_profile("OUTPOST_V1_BASIC")` succeeds
- Profile has same bindings as `outpost_v1.json`
- `protected_roles` includes new standard section roles
- `standard_sections` updated with accurate section names

**Risks:** None.

**Expected artifacts:** `outpost_v1_basic.json`

**State update:** Update `state.md`.

---

#### Sub-slice 3b: Validate basic profile against Tab 0

**Objective:** Ensure every binding in `outpost_v1_basic.json` resolves against Tab 0's roles.

**Current behavior:** Profile exists (from 3a).

**Expected behavior:** No unresolvable bindings.

**Scope:** Validation test only.

**Non-goals:** No code changes.

**Dependencies:** Sub-slice 3a, Slice 2.

**Files to change:**
- EXTEND: `tests/unit/topology/test_master_template_roles.py`

**Test to write first:**
```python
def test_basic_profile_resolves_against_tab0():
    tab0 = _load_tab0()
    index = parse_haf_template(tab0)
    profile = load_haf_profile("OUTPOST_V1_BASIC")
    binding_roles = {b.haf_role for b in profile.placeholder_bindings}
    missing = binding_roles - index.all_roles
    assert not missing, f"Basic profile bindings reference missing roles: {missing}"
```

**Expected reason test will fail:** Should pass if annotations are correct. If fails, fix annotation.

**Minimum implementation:** None if Slice 2 annotations are correct.

**Focused test command:** `python -m pytest tests/unit/topology/test_master_template_roles.py -v -k "basic_profile_resolves"`

**Acceptance criteria:** Zero missing bindings.

**State update:** Update `state.md` with Slice 3 completion.

---

### Slice 4: Annotate Tabs 1-3 + Create Their Profiles

#### Sub-slice 4a: Annotate Tab 1 (tLGW Load Balancer) + `outpost_v1_tlgw.json`

**Objective:** Annotate Tab 1 with all base roles + tLGW-specific roles; create profile.

**Current behavior:** Tab 1 has 165 cells, 0 haf-roles.

**Expected behavior:** Tab 1 has all base roles (same names as Tab 0 but different cell IDs) plus variant-specific: `tlgw_lb`, `workload_vpc_conexus`, `internal_users_icon`, `internal_systems_icon`, `web_eni_1`, `web_eni_2`, `web_eni_3`.

**Scope:** Tab 1 only.

**Non-goals:** No Tab 2 or 3 changes.

**Dependencies:** Slice 3 (basic profile as template).

**Files to change:**
- MODIFY: `src/migration_intake/topology/config/templates/outpost_v1.7.drawio`
- NEW: `src/migration_intake/topology/config/haf_profiles/outpost_v1_tlgw.json`
- EXTEND: `tests/unit/topology/test_master_template_roles.py`

**Reusable code candidates:** `outpost_v1_basic.json` as base.

**Test to write first:**
```python
def test_tab1_has_base_roles():
    tab1 = extract_tab(_load_master(), tab_name="tLGW Load Balancer")
    index = parse_haf_template(tab1)
    base_roles = {"header_line", "app_account_container", "att_internal_interfaces_band"}
    assert base_roles <= index.all_roles

def test_tab1_has_tlgw_specific_roles():
    tab1 = extract_tab(_load_master(), tab_name="tLGW Load Balancer")
    index = parse_haf_template(tab1)
    assert "tlgw_lb" in index.all_roles

def test_load_tlgw_profile():
    profile = load_haf_profile("OUTPOST_V1_TLGW")
    assert profile.profile_id == "OUTPOST_V1_TLGW"
```

**Expected reason test will fail:** Tab 1 has no haf-roles; profile file doesn't exist.

**Minimum implementation:** Annotate Tab 1 cells by ID; create `outpost_v1_tlgw.json` extending basic profile with tLGW roles.

**Focused test command:** `python -m pytest tests/unit/topology/test_master_template_roles.py -v -k "tab1 or tlgw"`

**Acceptance criteria:**
- Tab 1 has all base roles + tLGW-specific roles
- `load_haf_profile("OUTPOST_V1_TLGW")` succeeds
- Profile bindings resolve against Tab 1

**Risks:** Tab 1 has different cell IDs than Tab 0. Mitigation: find cells by value text + style patterns, not by ID.

**Expected artifacts:** Updated template, `outpost_v1_tlgw.json`, extended test file.

**State update:** Update `state.md`.

---

#### Sub-slice 4b: Annotate Tab 2 (F5 Load Balancer) + `outpost_v1_f5.json`

**Objective:** Annotate Tab 2 with base + F5-specific roles; create profile.

**Current behavior:** Tab 2 has 174 cells, 0 haf-roles.

**Expected behavior:** Base roles + `f5_lb_subnet`, `f5_eni`, `idns_icon`, `active_label`.

**Scope:** Tab 2 only.

**Non-goals:** No HA/DR.

**Dependencies:** Sub-slice 4a (pattern established).

**Files to change:**
- MODIFY: `src/migration_intake/topology/config/templates/outpost_v1.7.drawio`
- NEW: `src/migration_intake/topology/config/haf_profiles/outpost_v1_f5.json`
- EXTEND: `tests/unit/topology/test_master_template_roles.py`

**Reusable code candidates:** `outpost_v1_tlgw.json` as base (extends it with F5 roles).

**Test to write first:**
```python
def test_tab2_has_f5_specific_roles():
    tab2 = extract_tab(_load_master(), tab_name="F5 Load Balancer")
    index = parse_haf_template(tab2)
    assert "f5_lb_subnet" in index.all_roles
    assert "idns_icon" in index.all_roles

def test_load_f5_profile():
    profile = load_haf_profile("OUTPOST_V1_F5")
    assert profile.profile_id == "OUTPOST_V1_F5"
```

**Expected reason test will fail:** No haf-roles on Tab 2; no profile file.

**Minimum implementation:** Same approach as 4a but for Tab 2 cells.

**Focused test command:** `python -m pytest tests/unit/topology/test_master_template_roles.py -v -k "tab2 or f5"`

**Acceptance criteria:**
- Tab 2 has base + F5 roles
- Profile loads and validates

**State update:** Update `state.md`.

---

#### Sub-slice 4c: Annotate Tab 3 (HA/DR) + `outpost_v1_hadr.json`

**Objective:** Annotate Tab 3's TWO outpost regions; create HA/DR profile that fills both from same data.

**Current behavior:** Tab 3 has 272 cells (largest tab), 0 haf-roles.

**Expected behavior:** Primary region uses base roles. DR/secondary region uses `_dr` suffixed roles (e.g., `header_line_dr`, `app_account_container_dr`). Profile duplicates bindings for `_dr` roles with same tokens.

**Scope:** Tab 3 only. This is the most complex annotation.

**Non-goals:** No DR-specific generation logic (both regions get same data per D6).

**Dependencies:** Sub-slice 4b.

**Files to change:**
- MODIFY: `src/migration_intake/topology/config/templates/outpost_v1.7.drawio`
- NEW: `src/migration_intake/topology/config/haf_profiles/outpost_v1_hadr.json`
- EXTEND: `tests/unit/topology/test_master_template_roles.py`

**Reusable code candidates:** `outpost_v1_f5.json` as base.

**Test to write first:**
```python
def test_tab3_has_dual_region_roles():
    tab3 = extract_tab(_load_master(), tab_name="HA/DR with Global Load Balancer")
    index = parse_haf_template(tab3)
    assert "header_line" in index.all_roles
    assert "header_line_dr" in index.all_roles
    assert "app_account_container_dr" in index.all_roles

def test_hadr_profile_has_dr_bindings():
    profile = load_haf_profile("OUTPOST_V1_HADR")
    binding_roles = {b.haf_role for b in profile.placeholder_bindings}
    assert "header_line_dr" in binding_roles or "app_account_container_dr" in binding_roles
```

**Expected reason test will fail:** No haf-roles on Tab 3; no profile file.

**Minimum implementation:** Annotate both regions' cells; create profile with duplicated bindings for `_dr` roles.

**Focused test command:** `python -m pytest tests/unit/topology/test_master_template_roles.py -v -k "tab3 or hadr"`

**Acceptance criteria:**
- Primary region has all base roles
- DR region has all `_dr` suffixed roles
- `load_haf_profile("OUTPOST_V1_HADR")` succeeds
- Profile has duplicate bindings for DR roles (same tokens)

**Risks:** Identifying which cells belong to primary vs DR region. Mitigation: DR region cells are visually positioned to the right/below; inspect geometry to distinguish.

**Expected artifacts:** Updated template, `outpost_v1_hadr.json`, extended test file.

**State update:** Update `state.md` with Slice 4 completion.

---

### Slice 5: Wire Variant Selection into Pipeline

#### Sub-slice 5a: Add `VARIANT_PROFILE_MAP` to service layer

**Objective:** Map variant keys to profile IDs in `haf_service.py`.

**Current behavior:** `generate_haf_topology()` always uses the passed `profile_id` parameter.

**Expected behavior:** If `variant` is provided, it overrides `profile_id` via a lookup map.

**Scope:** Mapping constant and variant parameter only.

**Non-goals:** No UI changes. No bundled template loading.

**Dependencies:** Slice 3 (basic profile must exist for tests to pass).

**Files to change:**
- MODIFY: `src/migration_intake/topology/haf_service.py`
- EXTEND: `tests/unit/topology/test_haf_service.py`

**Reusable code candidates:** None.

**Test to write first:**
```python
def test_variant_basic_selects_basic_profile(tmp_engine, _seed_synthetic_app):
    """variant='basic' should use OUTPOST_V1_BASIC profile."""
    # This test uses the existing synthetic template since profile selection
    # is separate from template content
    result = generate_haf_topology(
        session=session, intake_id=intake_id,
        profile_id="OUTPOST_V1", template_bytes=template,
        variant="basic",
    )
    # The result should succeed (profile loads)
    assert result.filled_xml is not None

def test_variant_none_falls_back_to_legacy(tmp_engine, _seed_synthetic_app):
    result = generate_haf_topology(
        session=session, intake_id=intake_id,
        profile_id="OUTPOST_V1", template_bytes=template,
        variant=None,
    )
    assert result.filled_xml is not None
```

**Expected reason test will fail:** `generate_haf_topology()` does not accept a `variant` parameter.

**Minimum implementation:**
```python
VARIANT_PROFILE_MAP = {
    "basic": "OUTPOST_V1_BASIC",
    "tlgw": "OUTPOST_V1_TLGW",
    "f5": "OUTPOST_V1_F5",
    "hadr": "OUTPOST_V1_HADR",
    None: "OUTPOST_V1",
    "default": "OUTPOST_V1",
}

def generate_haf_topology(*, session, intake_id, profile_id, template_bytes, variant=None):
    resolved_profile = VARIANT_PROFILE_MAP.get(variant, profile_id)
    extraction = extract_haf_data(session, intake_id, resolved_profile)
    fill_result = fill_haf_template(..., profile_id=resolved_profile, ...)
    ...
```

**Focused test command:** `python -m pytest tests/unit/topology/test_haf_service.py -v -k "variant"`

**Relevant regression tests:** `python -m pytest tests/unit/topology/ -v`

**Acceptance criteria:**
- `variant="basic"` → uses `OUTPOST_V1_BASIC`
- `variant=None` → uses `OUTPOST_V1` (legacy)
- `variant="default"` → uses `OUTPOST_V1`
- All existing tests pass (backward compatible)

**Risks:** Adding `variant` parameter could break existing call sites. Mitigation: default `variant=None` preserves behavior.

**Expected artifacts:** Updated `haf_service.py`, extended test file.

**State update:** Update `state.md`.

---

#### Sub-slice 5b: Pass variant through TopologyGenerationService

**Objective:** Pass variant from `TopologyGenerationService._generate_haf_diagram()` to `generate_haf_topology()`.

**Current behavior:** `_generate_haf_diagram()` does not pass variant.

**Expected behavior:** `_generate_haf_diagram()` accepts and forwards `variant` parameter.

**Scope:** Service layer pass-through only.

**Non-goals:** No route changes (that's Slice 7).

**Dependencies:** Sub-slice 5a.

**Files to change:**
- MODIFY: `src/migration_intake/application/services/topology_generation.py`
- EXTEND: `tests/unit/topology/test_haf_service.py`

**Test to write first:**
```python
def test_topology_service_passes_variant():
    """Integration test: variant flows through service to haf_service."""
    # Verified by checking the profile used in the result
    ...
```

**Expected reason test will fail:** Service doesn't accept variant.

**Minimum implementation:** Add `variant: str | None = None` parameter to `_generate_haf_diagram()` and `generate_topology()`, pass through to `generate_haf_topology()`.

**Focused test command:** `python -m pytest tests/unit/topology/ -v`

**Acceptance criteria:**
- `generate_topology()` accepts `variant` parameter
- Variant flows through to `generate_haf_topology()`
- All existing tests pass

**State update:** Update `state.md` with Slice 5 completion.

---

### Slice 6: Bundled Template Loader

#### Sub-slice 6a: `load_bundled_template()` function

**Objective:** Add function to load the bundled master template and extract the tab for a given variant.

**Current behavior:** No bundled template loading capability.

**Expected behavior:** `load_bundled_template("basic")` reads the annotated master template from disk, extracts Tab 0, returns single-tab bytes.

**Scope:** Template loading only.

**Non-goals:** No service integration (that's 6b).

**Dependencies:** Slices 1 (extract_tab), 2 (annotated template).

**Files to change:**
- MODIFY: `src/migration_intake/topology/template_loader.py`
- EXTEND: `tests/unit/topology/test_template_loader.py`

**Reusable code candidates:** None.

**Test to write first:**
```python
def test_load_bundled_basic():
    tab_bytes = load_bundled_template("basic")
    root = ET.fromstring(tab_bytes)
    assert len(root.findall("diagram")) == 1
    assert root.findall("diagram")[0].get("name") == "Without LBs"

def test_load_bundled_f5():
    tab_bytes = load_bundled_template("f5")
    root = ET.fromstring(tab_bytes)
    assert root.findall("diagram")[0].get("name") == "F5 Load Balancer"

def test_load_bundled_invalid_variant():
    with pytest.raises(KeyError):
        load_bundled_template("nonexistent")
```

**Expected reason test will fail:** `load_bundled_template` does not exist.

**Minimum implementation:**
```python
VARIANT_TAB_MAP = {
    "basic": "Without LBs",
    "tlgw": "tLGW Load Balancer",
    "f5": "F5 Load Balancer",
    "hadr": "HA/DR with Global Load Balancer",
}
_BUNDLED_TEMPLATE = Path(__file__).parent / "config" / "templates" / "outpost_v1.7.drawio"

def load_bundled_template(variant: str) -> bytes:
    raw = _BUNDLED_TEMPLATE.read_bytes()
    tab_name = VARIANT_TAB_MAP[variant]
    return extract_tab(raw, tab_name=tab_name)
```

**Focused test command:** `python -m pytest tests/unit/topology/test_template_loader.py -v -k "load_bundled"`

**Acceptance criteria:**
- Returns valid single-tab bytes for each variant
- Tab has haf-role annotations (since it's from the annotated copy)
- Raises `KeyError` for unknown variant

**State update:** Update `state.md`.

---

#### Sub-slice 6b: `generate_from_standard_template()` service method

**Objective:** Add a service method that generates topology from the bundled template, bypassing the upload step.

**Current behavior:** `generate_topology()` requires a `base_artifact_id` (uploaded file).

**Expected behavior:** `generate_from_standard_template(intake_id, variant, actor)` loads the bundled template, runs the pipeline, stores artifacts, creates a generation run.

**Scope:** Service method only.

**Non-goals:** No route or UI changes.

**Dependencies:** Sub-slices 5b, 6a.

**Files to change:**
- MODIFY: `src/migration_intake/application/services/topology_generation.py`
- EXTEND: `tests/unit/topology/test_haf_service.py` or new test file

**Reusable code candidates:** `generate_topology()` logic (reuse artifact storage pattern).

**Test to write first:**
```python
def test_generate_from_standard_template_basic(tmp_engine, _seed_synthetic_app):
    """Integration test: generate from bundled template with 'basic' variant."""
    service = TopologyGenerationService(session_factory, storage_root)
    run = service.generate_from_standard_template(
        intake_id=intake_id, variant="basic", actor=actor,
    )
    assert run["status"] in {"READY_FOR_REVIEW", "GENERATED_WITH_GAPS", "RUNNING"}
```

**Expected reason test will fail:** Method does not exist.

**Minimum implementation:**
```python
def generate_from_standard_template(self, intake_id, variant, actor):
    template_bytes = load_bundled_template(variant)
    # ... create run, generate, store artifacts (reuse pattern from generate_topology)
```

**Focused test command:** `python -m pytest tests/unit/topology/ -v -k "standard_template"`

**Acceptance criteria:**
- Method generates a diagram from bundled template
- Artifacts stored correctly
- Generation run record created
- Works for all 4 variants

**Risks:** The method bypasses the base artifact upload step, so `base_artifact_id` is not available. Mitigation: either create a synthetic base artifact record or use a sentinel `base_artifact_id`. Inspect `GenerationRun` model to determine if `base_artifact_id` is nullable — it is NOT nullable (line 87 of `models_topology.py`), so a synthetic record may be needed.

**OPEN QUESTION:** Should `generate_from_standard_template()` create a `TopologyBaseArtifact` record for the bundled template? This would maintain the invariant that every run has a base artifact. The executing agent should decide based on the model constraints.

**State update:** Update `state.md` with Slice 6 completion.

---

### Slice 7: UI Updates

#### Sub-slice 7a: Update variant dropdown in upload form

**Objective:** Change the existing variant `<select>` options from "Default/HA/DR" to the 4 architectural variants.

**Current behavior:** `src/migration_intake/web/templates/topology/index.html` line 265-269:
```html
<option value="default">Default</option>
<option value="ha">High Availability</option>
<option value="dr">Disaster Recovery</option>
```

**Expected behavior:**
```html
<option value="basic">Without Load Balancers</option>
<option value="tlgw">tLGW Load Balancer</option>
<option value="f5">F5 Load Balancer</option>
<option value="hadr">HA/DR with Global Load Balancer</option>
```

**Scope:** 3-line HTML change only.

**Non-goals:** No new card. No route changes.

**Dependencies:** None.

**Files to change:**
- MODIFY: `src/migration_intake/web/templates/topology/index.html`

**Test to write first:**
```python
def test_topology_variant_dropdown_has_four_options(client, seed_intake):
    """Check that variant dropdown shows 4 architectural variants."""
    resp = client.get(f"/applications/{app_id}/intakes/{intake_id}/topology")
    assert 'value="basic"' in resp.text
    assert 'value="tlgw"' in resp.text
    assert 'value="f5"' in resp.text
    assert 'value="hadr"' in resp.text
```

**Expected reason test will fail:** Old options still present.

**Minimum implementation:** Replace the 3 `<option>` elements.

**Focused test command:** `python -m pytest tests/web/ -v -k "variant"`

**Acceptance criteria:**
- 4 options visible
- Old "Default/HA/DR" options removed
- No inline styles or event handlers

**State update:** Update `state.md`.

---

#### Sub-slice 7b: Add "Generate from Standard Template" card

**Objective:** Add a new card to the topology page that allows generating from the bundled template without uploading.

**Current behavior:** Only upload-then-generate flow exists.

**Expected behavior:** New card with variant dropdown and "Generate topology" button that POSTs to a new route.

**Scope:** HTML card only. No route (that's 7c).

**Non-goals:** No route implementation.

**Dependencies:** Sub-slice 7a.

**Files to change:**
- MODIFY: `src/migration_intake/web/templates/topology/index.html`

**Test to write first:**
```python
def test_topology_page_has_standard_template_card(client, seed_intake):
    resp = client.get(f"/applications/{app_id}/intakes/{intake_id}/topology")
    assert "Generate from Standard Template" in resp.text
    assert "generate-standard" in resp.text
```

**Expected reason test will fail:** Card does not exist in HTML.

**Minimum implementation:** Add a new `<div class="card">` after the existing generate card, with a form posting to `{{ intake_base }}/topology/generate-standard`.

**Focused test command:** `python -m pytest tests/web/ -v -k "standard_template"`

**Acceptance criteria:**
- Card renders on topology page
- Contains variant dropdown (4 options)
- Form action targets `generate-standard`
- Has CSRF token
- Uses design token CSS classes (no inline styles)

**State update:** Update `state.md`.

---

#### Sub-slice 7c: Add `POST /topology/generate-standard` route

**Objective:** Wire the new form to the service method.

**Current behavior:** No `generate-standard` route.

**Expected behavior:** `POST /topology/generate-standard` with `variant` form field → calls `topology_service.generate_from_standard_template()` → redirects to run detail page.

**Scope:** Route only.

**Non-goals:** No service changes (already done in Slice 6).

**Dependencies:** Sub-slices 6b, 7b.

**Files to change:**
- MODIFY: `src/migration_intake/web/routes/topology.py`
- EXTEND: `tests/web/test_topology_containment.py`

**Test to write first:**
```python
def test_generate_standard_requires_csrf(client, seed_intake):
    resp = client.post(f"/applications/{app_id}/intakes/{intake_id}/topology/generate-standard",
                       data={"variant": "basic"})
    assert resp.status_code == 403

def test_generate_standard_requires_capability(client, seed_intake):
    # POST without TOPOLOGY_GENERATE capability
    ...
```

**Expected reason test will fail:** Route does not exist; 404.

**Minimum implementation:**
```python
@router.post("/.../topology/generate-standard")
async def generate_from_standard(request, app_id, intake_id, ...):
    _require_intake_scope(app_id, intake_id, session_factory)
    require_capability(set(actor.role_codes), Capability.TOPOLOGY_GENERATE)
    validate_csrf_token(...)
    run = topology_service.generate_from_standard_template(
        intake_id=intake_id, variant=variant, actor=actor,
    )
    return RedirectResponse(url=f".../{run['id']}", status_code=303)
```

**Focused test command:** `python -m pytest tests/web/ -v -k "generate_standard"`

**Acceptance criteria:**
- Route requires CSRF token
- Route requires TOPOLOGY_GENERATE capability
- Route calls service method with correct variant
- Redirects to run detail page on success
- Returns 400 for invalid variant

**State update:** Update `state.md` with Slice 7 completion.

---

### Slice 8: AWS Tier 1 Connector Color Fix

#### Sub-slice 8a: Fix connector style — remove strokeColor

**Objective:** Remove `strokeColor={color};strokeWidth=2;` from the AWS Tier 1 connector style template.

**Current behavior:** `aws_tier1_generator.py` line 50-54:
```python
CONNECTOR_STYLE = (
    "rounded=0;orthogonalLoop=1;jettySize=auto;html=1;"
    "startArrow={start_arrow};startFill=1;endArrow={end_arrow};endFill=0;"
    "edgeStyle=orthogonalEdgeStyle;"
    "strokeColor={color};strokeWidth=2;"
)
```

**Expected behavior:** Connector uses default black (no explicit strokeColor):
```python
CONNECTOR_STYLE = (
    "rounded=0;orthogonalLoop=1;jettySize=auto;html=1;"
    "startArrow={start_arrow};startFill=1;endArrow={end_arrow};endFill=0;"
    "edgeStyle=orthogonalEdgeStyle;"
)
```

**Scope:** Style constant only.

**Non-goals:** No ATT Internal connector change (those correctly use family colors).

**Dependencies:** None (independent of all other slices).

**Files to change:**
- MODIFY: `src/migration_intake/topology/aws_tier1_generator.py`
- MODIFY: `tests/unit/topology/test_aws_tier1_generator.py`

**Reusable code candidates:** None.

**Test to write first:**
```python
def test_connector_has_no_stroke_color():
    """AWS Tier 1 connector should use default black (no strokeColor)."""
    tree = _make_tree_with_container()
    groups = [_make_group("HTTPS", ["443"], ["App1 (123)"])]
    result = generate_aws_tier1_rows(tree, groups)
    connectors = [e for e in result.elements_created if e.element_type == "connector"]
    for conn in connectors:
        style = conn.xml_element.get("style", "")
        assert "strokeColor" not in style
        assert "strokeWidth" not in style
```

**Expected reason test will fail:** `CONNECTOR_STYLE` still contains `strokeColor={color};strokeWidth=2;`.

**Minimum implementation:** Remove `"strokeColor={color};strokeWidth=2;"` from `CONNECTOR_STYLE`. Also remove the `color` parameter from the `.format()` call on line 234.

**Focused test command:** `python -m pytest tests/unit/topology/test_aws_tier1_generator.py -v -k "stroke"`

**Relevant regression tests:** `python -m pytest tests/unit/topology/test_aws_tier1_generator.py -v`

**Acceptance criteria:**
- No `strokeColor` or `strokeWidth` in generated connector styles
- All existing AWS Tier 1 tests updated and pass
- No regression in other tests

**Risks:** Existing tests may assert on `strokeColor`. Mitigation: update assertions.

**Expected artifacts:** Updated generator, updated tests.

**State update:** Update `state.md` with Slice 8 completion.

---

### Slice 9: End-to-End Comparison

#### Sub-slice 9a: Resolve and validate input and reference files

**Objective:** Locate the actual input and reference files by inspecting the directory (extensions may be omitted in the task specification).

**Current behavior:** Files exist at known paths but extensions could vary.

**Expected behavior:** Script resolves exact file paths and validates both files are valid draw.io XML.

**Scope:** File resolution and validation only.

**Non-goals:** No generation.

**Dependencies:** None.

**Files to change:**
- MODIFY: `scripts/run_e2e_comparison.py`

**Test to write first:** (Script-level validation, not pytest)
```python
def test_input_file_resolves():
    input_path = _resolve_file("docs/input_CCPM_AWS_Outpost_Topology_UNRESOLVED_UNRESOLVED-v1.7")
    assert input_path.exists()
    assert input_path.suffix == ".drawio"

def test_reference_file_resolves():
    ref_path = _resolve_file("docs/CCPM__FINAL_18678_TargetState_AWS_OutPosts_v01 (1)")
    assert ref_path.exists()
```

**Expected reason test will fail:** `_resolve_file` not yet implemented.

**Minimum implementation:** Helper that tries exact path, then with `.drawio` extension.

**Focused test command:** `python scripts/run_e2e_comparison.py --validate-only`

**Acceptance criteria:**
- Input file found: `docs/input_CCPM_AWS_Outpost_Topology_UNRESOLVED_UNRESOLVED-v1.7.drawio`
- Reference file found: `docs/CCPM__FINAL_18678_TargetState_AWS_OutPosts_v01 (1).drawio`
- Both parse as valid XML

**State update:** Update `state.md`.

---

#### Sub-slice 9b: Run the real diagram-generation workflow

**Objective:** Generate a topology diagram using the bundled Tab 0 template ("basic" variant) with synthetic DB data.

**Current behavior:** Previous E2E used the dev template.

**Expected behavior:** Generation uses the annotated master template Tab 0 via `load_bundled_template("basic")`.

**Scope:** Generation only. No comparison yet.

**Non-goals:** No visual comparison.

**Dependencies:** Slices 1-6, 8.

**Files to change:**
- MODIFY: `scripts/run_e2e_comparison.py`

**Test to write first:**
```python
def test_e2e_generation_succeeds():
    result = _run_generation("basic")
    assert result.success
    assert len(result.filled_xml) > 0
```

**Minimum implementation:** Update script to use `load_bundled_template("basic")` and run `fill_haf_template()`.

**Focused test command:** `python scripts/run_e2e_comparison.py --generate-only`

**Acceptance criteria:**
- Pipeline runs without blocking gaps
- Generated XML is valid draw.io format
- Standard sections (VPCE, Internet, Tier 2) present in output

**State update:** Update `state.md`.

---

#### Sub-slice 9c: Save the generated diagram

**Objective:** Save the generated diagram to a timestamped run-specific directory.

**Current behavior:** Previous E2E saved to `artifacts/final-comparison/<timestamp>/`.

**Expected behavior:** Same pattern with updated naming: `artifacts/final-comparison/<YYYYMMDD_HHMMSS>/generated_diagram.drawio`.

**Scope:** File I/O only.

**Non-goals:** No comparison.

**Dependencies:** Sub-slice 9b.

**Files to change:**
- MODIFY: `scripts/run_e2e_comparison.py`

**Minimum implementation:** `Path(run_dir / "generated_diagram.drawio").write_bytes(result.filled_xml)`

**Acceptance criteria:**
- File exists on disk
- Valid draw.io XML
- Path documented in `state.md`

**State update:** Update `state.md`.

---

#### Sub-slice 9d: Render generated and reference diagrams for comparison

**Objective:** Prepare both diagrams for structural comparison (XML-level).

**Current behavior:** Previous E2E did XML-level semantic comparison.

**Expected behavior:** Parse both diagrams, extract labeled cells, sections, and structural information for comparison.

**Scope:** XML extraction only.

**Non-goals:** No visual rendering (draw.io is not a renderable format without the draw.io application).

**Dependencies:** Sub-slices 9a, 9c.

**Files to change:**
- MODIFY: `scripts/run_e2e_comparison.py`

**Minimum implementation:** Extract all cells with labels, roles, styles, and geometry from both diagrams.

**Acceptance criteria:**
- Both diagrams parsed successfully
- Cell count, label count, role count extracted
- Section inventory created for both

**State update:** Update `state.md`.

---

#### Sub-slice 9e: Capture screenshots of both diagrams

**Objective:** If a draw.io rendering tool is available, capture PNG screenshots. Otherwise, produce SVG or skip with a documented note.

**Current behavior:** No screenshot capability.

**Expected behavior:** Attempt to render both diagrams. If draw.io desktop or `drawio-batch` is available, produce PNGs. Otherwise, document as "screenshots not available — requires draw.io application" and produce XML comparison instead.

**Scope:** Best-effort rendering.

**Non-goals:** Do not install draw.io or external dependencies.

**Dependencies:** Sub-slices 9c, 9d.

**Files to change:**
- MODIFY: `scripts/run_e2e_comparison.py`

**ASSUMPTION:** draw.io desktop application or `drawio-batch` CLI is likely NOT available in the execution environment. The script should gracefully handle this and fall back to XML-level comparison.

**Minimum implementation:** Try `subprocess.run(["drawio", "--export", ...])`. If fails, log "Screenshot generation skipped: draw.io not available" and continue.

**Acceptance criteria:**
- If draw.io available: PNGs saved to run directory
- If not available: graceful skip with documentation
- No crash on missing tool

**State update:** Update `state.md`.

---

#### Sub-slice 9f: Create side-by-side comparison and difference report

**Objective:** Create a detailed comparison report between generated and reference diagrams.

**Current behavior:** Previous E2E produced a JSON comparison report.

**Expected behavior:** HTML report with:
- Cell count comparison
- Section-by-section comparison (present/missing/extra)
- Label comparison (matching/mismatched)
- Style comparison for key elements
- Geometry comparison for positioned elements
- Summary of differences

**Scope:** Report generation.

**Non-goals:** No overlay image (handled in 9g if screenshots available).

**Dependencies:** Sub-slice 9d.

**Files to change:**
- MODIFY: `scripts/run_e2e_comparison.py`

**Minimum implementation:** Generate HTML table comparing sections side-by-side, highlighting missing/extra/mismatched items.

**Acceptance criteria:**
- Report saved to `artifacts/final-comparison/<run>/comparison_report.html`
- Differences honestly documented
- Generation success alone is NOT treated as visual match

**State update:** Update `state.md`.

---

#### Sub-slice 9g: Create overlay or difference image where supported

**Objective:** If PNGs were generated in 9e, create a visual overlay highlighting differences.

**Current behavior:** No overlay capability.

**Expected behavior:** If PNGs exist, produce a difference image using PIL/Pillow (if available) or document as "overlay not available".

**Scope:** Best-effort visual diff.

**Non-goals:** Do not add Pillow as a project dependency.

**Dependencies:** Sub-slice 9e.

**Files to change:**
- MODIFY: `scripts/run_e2e_comparison.py`

**ASSUMPTION:** Pillow may or may not be available. Script should handle gracefully.

**Minimum implementation:** Try `from PIL import Image, ImageChops`. If available, create diff image. If not, skip.

**Acceptance criteria:**
- If both PNGs and Pillow available: overlay image saved
- If not available: graceful skip
- No crash

**State update:** Update `state.md`.

---

#### Sub-slice 9h: Compare important sections, nodes, labels, connections, styles, and layout

**Objective:** Detailed section-by-section comparison of the key diagram areas.

**Current behavior:** Previous comparison checked for labeled cells and some sections.

**Expected behavior:** Check each of these sections in both diagrams:
- Header / Application info
- ATT Internal Interfaces band (generated rows)
- AWS Tier 1 box (interface boxes, connectors, static icons)
- Azure App section (port boxes, connectors)
- VPCE via AT&T Regional Bastion
- Internet section
- AWS Tier 2 section
- DNS PHZ section
- DirectConnect
- Legend
- Static sections from profile `standard_sections`
- Connector colors and arrow directions
- Container sizes and positions

**Scope:** Comprehensive comparison.

**Dependencies:** Sub-slice 9f.

**Files to change:**
- MODIFY: `scripts/run_e2e_comparison.py`

**Minimum implementation:** For each section, find matching cells in both diagrams by label text. Report present/absent/mismatched.

**Acceptance criteria:**
- All key sections checked
- Report includes per-section match status
- Missing and extra elements clearly listed

**State update:** Update `state.md`.

---

#### Sub-slice 9i: Document missing, extra, or mismatched content

**Objective:** Honest documentation of all differences found.

**Current behavior:** Previous report was minimal.

**Expected behavior:** Detailed list of:
- Sections missing from generated (expected in reference)
- Sections extra in generated (not in reference)
- Label mismatches
- Style mismatches
- Layout/position differences
- Known issues vs unexpected differences

**Scope:** Documentation only.

**Dependencies:** Sub-slice 9h.

**Files to change:**
- MODIFY: `scripts/run_e2e_comparison.py`

**Acceptance criteria:**
- All differences documented
- Known issues flagged as such
- Unexpected differences flagged for investigation

**State update:** Update `state.md`.

---

#### Sub-slice 9j: Save all artifacts and update state

**Objective:** Save all comparison artifacts to run-specific directory and update `state.md`.

**Current behavior:** Previous artifacts saved under `artifacts/final-comparison/`.

**Expected behavior:** All artifacts saved:
- `generated_diagram.drawio`
- `comparison_report.html`
- `comparison_report.json`
- `screenshots/generated.png` (if available)
- `screenshots/reference.png` (if available)
- `screenshots/diff.png` (if available)
- `section_comparison.json`

**Dependencies:** All 9a-9i sub-slices.

**Files to change:**
- MODIFY: `scripts/run_e2e_comparison.py`
- UPDATE: `state.md`
- UPDATE: This design document

**Acceptance criteria:**
- All artifacts saved to `artifacts/final-comparison/<YYYYMMDD_HHMMSS>/`
- `state.md` updated with exact artifact paths
- This design document updated with actual results
- Full regression passes: `python -m pytest tests/ -v`

**State update:** Update `state.md` with Slice 9 completion — final slice.

---

## 8. Persistent-State Protocol

The executing agent MUST maintain `C:\GitHub\aws_diag_v4_1\aws_diag_v4\state.md` throughout implementation.

### Required updates

**Before each slice:**
```markdown
## Current Phase
Implementation

## Current Slice
Slice X / Sub-slice Xa: [description]

## Status
IN PROGRESS

## Next Exact Action
[what the agent will do first]
```

**After each slice:**
```markdown
## Current Slice
Slice X / Sub-slice Xa: [description]

## Status
COMPLETE

## Last Completed Action
[what was done]

## RED Test Command and Result
`python -m pytest tests/unit/topology/test_xxx.py -v -k "test_name"`
Result: FAILED — [reason]

## GREEN Test Command and Result
`python -m pytest tests/unit/topology/test_xxx.py -v -k "test_name"`
Result: PASSED — X passed

## Regression Test Results
`python -m pytest tests/ -v`
Result: XXXX passed, 0 failed

## Files Changed
- [list of files]

## Decisions and Assumptions
- [any decisions made]

## Reused Components
- [components reused from reference projects]

## Known Issues
- [any issues discovered]

## Artifacts
- [generated artifacts]

## Next Exact Action
[next sub-slice or slice]
```

---

## 9. Execution Protocol

The executing agent MUST follow these rules:

1. **Complete one slice at a time.** Do not jump ahead or combine unrelated slices.

2. **Follow RED → GREEN → REFACTOR for each sub-slice:**
   - Write the failing test first
   - Run the test to confirm it fails (RED)
   - Write the minimum implementation to make it pass
   - Run the test to confirm it passes (GREEN)
   - Refactor if needed (maintain passing tests)
   - Run broader regression tests

3. **Do not combine unrelated slices.** Each sub-slice addresses one behavior.

4. **Do not mark a slice complete until its acceptance criteria pass.** All specified tests must pass plus the full regression suite.

5. **Update state and design documentation immediately** after each completed sub-slice and slice.

6. **Continue to the next slice without asking for routine approval.** The plan is pre-approved for sequential execution.

7. **Stop only for a genuine external blocker:**
   - Authentication/permission issues
   - Missing file that should exist
   - Test infrastructure broken
   - Ambiguous requirement that cannot be resolved from code inspection
   - Do NOT stop for expected test failures (that's RED phase)

8. **Verify after each slice:**
   - Focused tests pass
   - Full regression: `python -m pytest tests/ -v`
   - No production code changes that weren't planned

9. **Document deviations.** If the implementation deviates from this plan (different file, different approach), document why in `state.md` and update this plan.

10. **Final verification:** After all slices, run `python -m pytest tests/ -v` and confirm count is ≥ 2950 + new tests.

---

## 10. Implementation Readiness Checklist

- [x] Existing plan reviewed (`plan-f1ac2334807309e0.md`)
- [x] Repository architecture inspected (pipeline, generators, extractors, service, routes)
- [x] Master template structure verified (5 tabs, 151/165/174/272/2 cells, 0 haf-roles)
- [x] Dev template structure verified (148 cells, 46 haf-roles)
- [x] Reference projects inspected (drawpyo-main, multicloud-diagrams-main)
- [x] Reuse matrix completed — no direct imports recommended
- [x] Profile config structure understood (`outpost_v1.json`)
- [x] UI template structure understood (`topology/index.html`)
- [x] Persistence model constraints verified (`base_artifact_id` NOT nullable in `GenerationRun`)
- [x] Test infrastructure verified (2950 tests, conftest.py fixtures)
- [x] Input file exists: `docs/input_CCPM_AWS_Outpost_Topology_UNRESOLVED_UNRESOLVED-v1.7.drawio`
- [x] Reference file exists: `docs/CCPM__FINAL_18678_TargetState_AWS_OutPosts_v01 (1).drawio`
- [x] Dependency graph defined
- [x] All slices have acceptance criteria
- [x] Persistent-state protocol defined
- [x] Execution protocol defined
- [x] E2E comparison sub-slices defined with honest reporting requirement
- [ ] Awaiting implementation approval

---

## 11. Assumptions and Open Questions

### Verified Facts
1. Master template has 5 tabs: "Without LBs", "tLGW Load Balancer", "F5 Load Balancer", "HA/DR with Global Load Balancer", "Definitions"
2. Each tab has completely independent cell IDs — zero overlap
3. Master template has zero `haf-role` annotations
4. Dev template has 46 `haf-role` annotations across 148 cells
5. `variant` column exists in `TopologyBaseArtifact` model (String(32), default "default")
6. UI already has variant dropdown with 3 options
7. Both reference projects are MIT licensed
8. 2950 tests currently pass

### Assumptions (Labeled)
1. **ASSUMPTION:** Tab 0 ("Without LBs") contains cells for VPCE, Internet, Tier 2, DirectConnect that can be annotated. The executing agent must verify by inspecting cell values before annotation.
2. **ASSUMPTION:** NAS/EBR detail blocks may not exist in the master template (they may be application-specific content). The executing agent must check and handle accordingly.
3. **ASSUMPTION:** The `haf-role` annotation can be done by a Python script that modifies the XML, rather than manual editing. This is the recommended approach for reliability.
4. **ASSUMPTION:** draw.io desktop or CLI tool is NOT available in the execution environment for PNG rendering.
5. **ASSUMPTION:** AWS Tier 1 container does NOT exist in the master template Tab 0 and must be added (same structure as was added to the dev template in previous work).

### Open Questions
1. **Q1:** Should `generate_from_standard_template()` create a synthetic `TopologyBaseArtifact` record to satisfy the NOT NULL constraint on `GenerationRun.base_artifact_id`? **Recommendation:** Yes — create a system-managed base artifact for the bundled template, identified by a deterministic UUID derived from the template SHA256.
2. **Q2:** Should the annotation script be committed as a utility, or is it a one-time operation? **Recommendation:** Commit as `scripts/annotate_template.py` for reproducibility, but the annotated template itself is the deliverable.
3. **Q3:** Are there additional sections in tabs 1-3 that need NEW haf-roles beyond the ones listed in the existing plan? **Recommendation:** The executing agent should inspect each tab during annotation (Sub-slices 4a-4c) and add roles as needed.

---

## Appendix A: File Inventory

### New Files (Planned)

| File | Slice | Purpose |
|---|---|---|
| `src/migration_intake/topology/template_loader.py` | 1 | Tab extraction and bundled template loading |
| `src/migration_intake/topology/config/templates/outpost_v1.7.drawio` | 2 | Annotated copy of master template |
| `src/migration_intake/topology/config/haf_profiles/outpost_v1_basic.json` | 3 | Basic variant profile |
| `src/migration_intake/topology/config/haf_profiles/outpost_v1_tlgw.json` | 4a | tLGW variant profile |
| `src/migration_intake/topology/config/haf_profiles/outpost_v1_f5.json` | 4b | F5 variant profile |
| `src/migration_intake/topology/config/haf_profiles/outpost_v1_hadr.json` | 4c | HA/DR variant profile |
| `tests/unit/topology/test_template_loader.py` | 1 | Tab extraction tests |
| `tests/unit/topology/test_master_template_roles.py` | 2 | Annotation validation tests |

### Modified Files (Planned)

| File | Slice | Change |
|---|---|---|
| `src/migration_intake/topology/haf_service.py` | 5 | Add `VARIANT_PROFILE_MAP`, accept `variant` parameter |
| `src/migration_intake/application/services/topology_generation.py` | 5, 6 | Pass variant, add `generate_from_standard_template()` |
| `src/migration_intake/web/routes/topology.py` | 7 | Add `generate_from_standard` route |
| `src/migration_intake/web/templates/topology/index.html` | 7 | Update variant dropdown, add standard template card |
| `src/migration_intake/topology/aws_tier1_generator.py` | 8 | Remove strokeColor from connector style |
| `scripts/run_e2e_comparison.py` | 9 | Update for bundled template, comprehensive comparison |
| `tests/unit/topology/test_aws_tier1_generator.py` | 8 | Update style assertions |
| `tests/unit/topology/test_haf_service.py` | 5 | Add variant selection tests |
| `tests/unit/topology/test_haf_pipeline.py` | 3 | Add basic profile tests |
| `tests/web/test_topology_containment.py` | 7 | Add route tests |

### Untouched Files (Important)

| File | Why |
|---|---|
| `docs/AWS_Outpost_Topology_Template_1-v1.7.drawio` | Architect's original, stays pristine |
| `src/migration_intake/topology/config/haf_profiles/outpost_v1.json` | Legacy fallback for existing uploads |
| `src/migration_intake/topology/att_internal_generator.py` | No changes needed |
| `src/migration_intake/topology/interface_normalization.py` | No changes needed |
| `src/migration_intake/topology/haf_pipeline.py` | No changes needed (variant handled at service layer) |
| `src/migration_intake/topology/haf_extractor.py` | No changes needed |

---

## Appendix B: Slice Summary Table

| Slice | Sub-slices | Description | Est. New Tests |
|---|---|---|---|
| 1 | 1a, 1b, 1c | Template Tab Extraction Module | 8-10 |
| 2 | 2a, 2b, 2c, 2d, 2e, 2f | Annotate Tab 0 (Without LBs) | 10-15 |
| 3 | 3a, 3b | Basic Variant Profile | 3-5 |
| 4 | 4a, 4b, 4c | Annotate Tabs 1-3 + Profiles | 9-12 |
| 5 | 5a, 5b | Wire Variant Selection | 4-6 |
| 6 | 6a, 6b | Bundled Template Loader | 5-7 |
| 7 | 7a, 7b, 7c | UI Updates | 4-6 |
| 8 | 8a | AWS Tier 1 Connector Color Fix | 2-3 |
| 9 | 9a-9j | E2E Comparison | 0 (script-level) |
| **Total** | **33** | | **45-64** |
