# HAF Topology Pipeline: Architectural Review and TDD Implementation Plan

Comprehensive design and implementation plan for enhancing the HAF topology pipeline with diagram quality improvements (cloud icons, sub-cell generation, edge routing, auto-layout) using reusable code from drawpyo-main (MIT) and multicloud-diagrams-main (MIT), structured as testable TDD slices verifiable with the real CCPM/Outpost v1.7 input diagram.

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Current-State Architecture](#2-current-state-architecture)
3. [Evidence Inventory](#3-evidence-inventory)
4. [Comparative Decision Matrix](#4-comparative-decision-matrix)
5. [HAF Strengths to Preserve](#5-haf-strengths-to-preserve)
6. [Gaps and Risks](#6-gaps-and-risks)
7. [Improvement Opportunities with Specific Reusable Code](#7-improvement-opportunities-with-specific-reusable-code)
8. [TDD Implementation Slices](#8-tdd-implementation-slices)
9. [Prioritized Roadmap](#9-prioritized-roadmap)
10. [Recommended First Slice (Proof of Concept)](#10-recommended-first-slice-proof-of-concept)
11. [Open Questions](#11-open-questions)
12. [Key Architectural Answers](#12-key-architectural-answers)

---

## 1. Executive Summary

### What This Plan Covers

This is a production-grade design and implementation plan for enhancing the HAF topology pipeline to generate visually rich draw.io topology diagrams — with cloud provider icons, individual interface sub-cells, directional edges, and auto-layout — while preserving the existing template-filling model, deterministic output, and structural safety.

### Key Design Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Generation model | **Keep template-filling** | Architect controls layout in draw.io; pipeline fills data |
| Code reuse | **Export functions from drawpyo + multicloud-diagrams** | Both MIT-licensed; copy utility functions rather than add runtime dependencies |
| Testing model | **TDD with real v1.7 template** | Each slice verified against `AWS__input_Outpost_Topology_UNRESOLVED_UNRESOLVED-v1.7.drawio` |
| Feature toggle | **Profile-driven `rendering` field** | `MULTILINE_TEXT` (current) vs `GENERATE_CELLS` — zero-risk rollback |
| HAF replaces governed renderer | **Confirmed** | Backport governance features (hashing, manifest) to HAF |

### What Gets Reused from Each Repo

**From multicloud-diagrams-main (MIT):**
- `providers/aws2024.json` — 50+ AWS icon style strings (including `outpost`, `direct_connect`, `route_53`, `vpc`, `subnet`, `security_group`, `ec2`, `s3`)
- `providers/azure.json` — Azure service icon styles
- `providers/core.json` — Edge, label, list, and row style templates
- `add_vertex()` pattern — deterministic `vertex:{type}:{id}` ID scheme
- `add_connection()` pattern — edge creation with label support
- `Distribution.Table` algorithm — grid layout calculation
- `stringify_dict()` / `stringify_labels()` — HTML metadata formatting
- `update_style_by_key()` — style string manipulation
- `read_coords_from_file()` — coordinate persistence concept

**From drawpyo-main (MIT):**
- `style_str_from_dict()` — style string assembly from dict
- `import_shape_database()` — TOML/JSON shape library loading pattern
- `xml_base.py` `xmlize` dict + `xml_ify()` — XML character escaping
- `Group` class geometry calculations — `left`, `right`, `top`, `bottom`, `width`, `height`, `center_position`
- `TreeDiagram.auto_position()` — hierarchical layout algorithm pattern
- `Object.create_from_template_object()` — template-based cell creation pattern
- `Edge.attributes` structure — source/target/style edge serialization

### What Does NOT Get Reused (and Why)

| Library Feature | Why Not |
|---|---|
| drawpyo `id(self)` for IDs | Non-deterministic across Python runs |
| drawpyo string-based XML serialization | HAF uses ElementTree (safer, standard) |
| drawpyo full File/Page/Object model | Over-engineered for template mutation — HAF doesn't create files from scratch |
| multicloud-diagrams `requests` dependency | Not needed; HAF extracts data from local DB |
| multicloud-diagrams `yaml` dependency | Not needed; HAF uses JSON profiles |
| multicloud-diagrams `minidom.toprettyxml()` | HAF uses `ET.tostring()` for consistency |

---

## 2. Current-State Architecture

### 2.1 drawpyo-main Data Flow

```
User Python code
  -> File(file_name, file_path)                    [file.py:16]
    -> Page(name, grid, dimensions)                 [page.py:21]
      -> Object(value, position, style, parent)     [objects.py:68]
        -> DiagramBase.style -> style_str_from_dict  [base_diagram.py:94]
        -> DiagramBase.xml_parent -> parent.id       [xml_base.py:58]
      -> Edge(source, target, waypoints, label)     [edges.py:42]
        -> connection_db, pattern_db, waypoints_db  [edges.py:22-29, TOML]
      -> Group(objects)                             [objects.py:764]
        -> left/right/top/bottom geometry           [objects.py:799-850]
      -> TreeDiagram(direction, spacing)            [tree.py:181]
        -> auto_position() -> recursive layout       [tree.py:~250]
    -> file.write() -> string XML concatenation      [file.py:105]
```

**Reusable code locations:**
- `src/drawpyo/diagram/base_diagram.py:94-118` — `style_str_from_dict()` function (26 lines)
- `src/drawpyo/diagram/objects.py:764-910` — `Group` class geometry helpers (146 lines)
- `src/drawpyo/xml_base.py:3-13` — `xmlize` escape table + `xml_ify()` method (11 lines)
- `src/drawpyo/diagram/base_diagram.py:43-91` — `import_shape_database()` for TOML loading (48 lines)

### 2.2 multicloud-diagrams-main Data Flow

```
User Python code
  -> MultiCloudDiagrams()                          [__init__.py:164]
    -> Et.Element('mxfile')                         [__init__.py:175]
    -> Et.SubElement('diagram')                     [__init__.py:180]
    -> Et.SubElement('mxGraphModel')                [__init__.py:183]
    -> Et.SubElement('root')                        [__init__.py:191]
    -> add_vertex(node_id, node_name, node_type)    [__init__.py:383]
      -> get_node_template(node_type)               [__init__.py:285]
        -> providers/{provider}.json lookup          [__init__.py:278-283]
      -> customize(node_template, style)            [__init__.py:31]
      -> Et.SubElement(root, 'mxCell', id=f'vertex:{type}:{id}', ...)  [__init__.py:409]
      -> Et.SubElement(cell, 'mxGeometry', ...)     [__init__.py:418]
    -> add_connection(src, dst, style, labels)      [__init__.py:472]
      -> Et.SubElement(root, 'mxCell', id=f'edge:{src}:to:{dst}', ...)  [__init__.py:525]
    -> add_vertex_list(vertexes, Distribution)      [__init__.py:447]
      -> Table algorithm: grid positioning           [__init__.py:449-467]
    -> export_to_file(path)                         [__init__.py:712]
```

**Reusable code locations:**
- `providers/aws2024.json` — 50+ service style templates (entire file, ~3000 lines)
- `providers/azure.json` — Azure styles (entire file)
- `providers/core.json` — Edge/label/list base styles
- `__init__.py:23-28` — `update_style_by_key()` function (6 lines)
- `__init__.py:31-33` — `customize()` function (3 lines)
- `__init__.py:36-41` — `stringify_dict()` HTML metadata formatter (6 lines)
- `__init__.py:447-467` — `Distribution.Table` grid layout algorithm (20 lines)
- `__init__.py:82-85` — `generate_hash()` deterministic hash (4 lines)
- `__init__.py:670-697` — `read_coords_from_file()` coordinate persistence (27 lines)

### 2.3 HAF Topology Pipeline Data Flow

```
Web route / CLI
  -> haf_service.generate_haf_topology()            [haf_service.py:42]
    -> haf_extractor.extract_haf_data()              [haf_extractor.py:66]
      -> SQL: intakes JOIN applications              [haf_extractor.py:85-92]
      -> SQL: app_identifiers -> tokens              [haf_extractor.py:102-114]
      -> SQL: ans_instances JOIN ans_revisions       [haf_extractor.py:117-133]
      -> SQL: interfaces -> grouped by cat:dir        [haf_extractor.py:146-174]
      -> HafExtractionResult(tokens, interfaces, details, issues)
    -> haf_pipeline.fill_haf_template()              [haf_pipeline.py:498]
      -> parse_haf_template(bytes) -> HafIndex        [haf_pipeline.py:74]
      -> load_haf_profile(id) -> HafProfile           [haf_pipeline.py:200]
      -> resolve_placeholders(index, profile, tokens) [haf_pipeline.py:295]
      -> fill_interface_regions(index, profile, ifs)  [haf_pipeline.py:374]
      -> fill_detail_blocks(index, profile, details)  [haf_pipeline.py:440]
      -> ET.tostring(tree) -> filled_bytes             [haf_pipeline.py:548]
    -> HafTopologyResult(filled_xml, mutations, gaps, issues, success)
```

**Current test baseline:** 397 tests passing (`python -m pytest tests/unit/topology/ -v`)

---

## 3. Evidence Inventory

### 3.1 Files Reviewed — drawpyo-main

| File | Lines | Architectural Role | Reusable? |
|---|---|---|---|
| `src/drawpyo/xml_base.py` | 144 | Base XML serialization, ID gen, XML escaping | YES: `xmlize` dict, `xml_ify()` |
| `src/drawpyo/file.py` | 161 | File wrapper, mxfile tag, disk write | NO: HAF uses ElementTree |
| `src/drawpyo/page.py` | 213 | Page/Diagram/mxGraph/Root nesting | NO: HAF uses templates |
| `src/drawpyo/diagram/base_diagram.py` | ~300 | DiagramBase, Geometry, style_str_from_dict, TOML import | YES: `style_str_from_dict()`, `import_shape_database()` |
| `src/drawpyo/diagram/objects.py` | 910 | Object (mxCell vertex), Group, shape libraries | YES: `Group` geometry, `create_from_template_object()` |
| `src/drawpyo/diagram/edges.py` | ~500 | Edge (mxCell edge), waypoints/connections/patterns | YES: Edge `attributes` structure, style DBs |
| `src/drawpyo/diagram/extended_objects.py` | ~200 | List (container + child items), PieSlice | YES: `List.autosize()` pattern |
| `src/drawpyo/diagram_types/tree.py` | ~400 | TreeDiagram auto-layout algorithm | YES: Layout algorithm pattern (conceptual) |
| `src/drawpyo/drawio_import/drawio_parser.py` | ~300 | ParsedDiagram, round-trip import | YES: Round-trip concept for future |
| `LICENSE` | 21 | MIT License | Allows free reuse |

### 3.2 Files Reviewed — multicloud-diagrams-main

| File | Lines | Architectural Role | Reusable? |
|---|---|---|---|
| `multicloud_diagrams/__init__.py` | 872 | Complete API: vertex, edge, table, YAML, export | YES: Multiple functions (see 2.2) |
| `providers/aws2024.json` | ~3000 | 50+ AWS 2024 icon styles + dimensions | YES: Copy relevant entries to HAF style registry |
| `providers/azure.json` | ~2000 | Azure service icon styles | YES: Copy relevant entries |
| `providers/core.json` | ~100 | Edge, label, list, row base styles | YES: Edge and label styles |
| `tests/aws2024/test_outpost.py` | 46 | Test pattern: verify exact mxCell attributes | YES: Test pattern for HAF sub-cell tests |
| `LICENSE` (in agent tag) | - | MIT License | Allows free reuse |

### 3.3 Files Reviewed — HAF Pipeline

| File | Lines | Architectural Role | Modified? |
|---|---|---|---|
| `topology/haf_pipeline.py` | 556 | Pure pipeline: parser, profile, resolver, fillers, orchestrator | YES (enhanced) |
| `topology/haf_extractor.py` | 206 | DB extraction (tokens, interfaces, details) | MINOR |
| `topology/haf_service.py` | 85 | Service entry point | MINOR |
| `topology/config/haf_profiles/outpost_v1.json` | 135 | OUTPOST_V1 profile config | YES (new fields) |
| `topology/renderer/core.py` | 1319 | Governed renderer (for backporting) | READ-ONLY |
| `topology/guide_policy.py` | ~100 | LOCATION_ALIASES, ApprovedFlow | YES (add MIDRANGE) |
| `topology/contracts.py` | ~200 | Canonical topology contracts, hashing | READ-ONLY |

---

## 4. Comparative Decision Matrix

| # | Dimension | drawpyo | multicloud | HAF | Winner | Reuse path for HAF |
|---|---|---|---|---|---|---|
| 1 | Architecture / SoC | 4/5 | 2/5 | 4/5 | drawpyo = HAF | Preserve HAF 3-layer design |
| 2 | Input normalization | 3/5 | 3/5 | 3/5 | Tie | Copy multicloud JSON provider pattern |
| 3 | Canonical topology model | 4/5 | 2/5 | 2/5 | drawpyo | Add intermediate InterfaceNode model |
| 4 | Layout quality | 4/5 | 2/5 | 1/5 | drawpyo | Copy Distribution.Table + Group geometry |
| 5 | Draw.io fidelity | 4/5 | 3/5 | 4/5 | drawpyo = HAF | Template preserves all |
| 6 | Styling flexibility | 4/5 | 4/5 | 2/5 | Tie | Copy multicloud provider JSON + drawpyo TOML pattern |
| 7 | Cloud icons | 1/5 | 5/5 | 1/5 | multicloud | Copy aws2024.json + azure.json entries |
| 8 | Edge routing | 4/5 | 3/5 | 1/5 | drawpyo | Copy edge serialization pattern |
| 9 | Container nesting | 4/5 | 2/5 | 2/5 | drawpyo | Copy parent/child pattern for sub-cells |
| 10 | Deterministic generation | 2/5 | 4/5 | 4/5 | multicloud = HAF | Copy `vertex:{type}:{id}` ID scheme |
| 11 | Extensibility | 4/5 | 3/5 | 4/5 | drawpyo = HAF | Profile JSON already extensible |
| 12 | Validation | 2/5 | 1/5 | 4/5 | HAF | Backport renderer limits to HAF parser |
| 13 | Error handling | 2/5 | 1/5 | 4/5 | HAF | Preserve typed gap reports |
| 14 | Testability | 3/5 | 3/5 | 5/5 | HAF | Copy multicloud test_outpost.py pattern |
| 15 | Maintainability | 4/5 | 2/5 | 4/5 | drawpyo = HAF | Keep small focused modules |

---

## 5. HAF Strengths to Preserve

1. **Template mutation model** — Architect controls layout; pipeline fills data. `haf_pipeline.py` only mutates `value` attributes on cells tagged with `haf-role`.
2. **Structural safety** — `parse_haf_template()` validates no duplicate IDs; `fill_*` functions only change `value`; structural assertions in tests.
3. **Determinism** — `ET.tostring()` with consistent attribute ordering produces identical bytes for identical inputs.
4. **Profile-driven config** — `outpost_v1.json` drives all behavior; adding a new template type requires only a new JSON profile.
5. **Clean 3-layer separation** — Extractor (DB only) -> Pipeline (pure functions) -> Service (integration).
6. **Gap reporting** — `HafGap` and `HafMutation` track every unresolved token and every mutation.
7. **Test suite** — 53 dedicated tests + 397 full topology suite, including E2E with real v1.7 template.
8. **LOCATION_ALIASES versioned policy** — Shared between HAF and governed renderer.

---

## 6. Gaps and Risks

### GAP-1: Interface Slots Are Plain Text (CRITICAL)

- **Evidence:** `haf_pipeline.py:410-418` — `fill_interface_regions()` joins entries with `\n` into a single cell `value`
- **Impact:** HIGH — diagrams look like text dumps, not topology diagrams
- **Severity:** HIGH — directly degrades diagram usability
- **Affected:** `haf_pipeline.py`, `outpost_v1.json`
- **Mitigation:** OP-2: Generate individual child mxCells per interface (see Slice 4)

### GAP-2: No Cloud Provider Icons

- **Evidence:** HAF sets text-only `value` on cells. No `shape=mxgraph.aws4.*` styles.
- **Impact:** MEDIUM — architects expect visual icons for AWS/Azure services
- **Precedent:** multicloud `providers/aws2024.json` has `outpost` style: `shape=mxgraph.aws4.resourceIcon;resIcon=mxgraph.aws4.outposts`
- **Mitigation:** OP-1: Create style registry JSON copied from multicloud providers (see Slice 3)

### GAP-3: No Edge Generation

- **Evidence:** HAF only mutates cell values; no mxCell edges created
- **Precedent:** Governed renderer `core.py:933-978` generates edges; multicloud `add_connection()` generates edges
- **Mitigation:** OP-3: Add edge generation step (see Slice 6)

### GAP-4: No Auto-Layout Within Slots

- **Evidence:** `fill_interface_regions()` puts all entries in a single string, no geometry
- **Precedent:** multicloud `Distribution.Table` (`__init__.py:449-467`) calculates grid positions
- **Mitigation:** OP-4: Grid layout for sub-cells (see Slice 5)

### GAP-5: Midrange Location Missing

- **Evidence:** `guide_policy.py:10-19` — LOCATION_ALIASES lacks `MIDRANGE`. CCPM has 24+ Midrange interfaces mapped to UNKNOWN
- **Mitigation:** Add `"MIDRANGE": "INTERNAL"` after policy review (see Slice 1)

### GAP-6: No Manifest or Hash Verification

- **Evidence:** `haf_pipeline.py` has no `_compute_hash()` or manifest generation
- **Precedent:** `renderer/core.py:267-299` `RenderManifest` with input/output hashes
- **Mitigation:** OP-6: Backport from governed renderer (see Slice 8)

### GAP-7: No XML Security Limits

- **Evidence:** `haf_pipeline.py:94` uses bare `ET.fromstring()` without DTD/entity/size checks
- **Precedent:** `renderer/core.py:384-441` `_validate_structure_limits()` with `XmlParserLimits`
- **Mitigation:** OP-7: Import existing `parse_diagram_safely()` (see Slice 2)

### RISK-1: Template Coupling (LOW)

- `outpost_v1.json` references specific `haf-role` names; template changes require profile update
- **Mitigated by:** `validate_against_index()` already warns on role mismatches

### RISK-2: Governed Renderer Retirement (MEDIUM)

- HAF replaces the 1319-line governed renderer; losing audit trail capabilities
- **Mitigated by:** Backport manifest/hash generation before decommissioning

---

## 7. Improvement Opportunities with Specific Reusable Code

### OP-1: Cloud Provider Style Registry

- **What:** JSON file mapping `(category, direction)` to draw.io style string + dimensions
- **Reuse from:** `multicloud-diagrams/providers/aws2024.json` entries: `outpost`, `ec2`, `vpc`, `subnet`, `security_group`, `direct_connect`, `route_53`, `s3`, `rds`; `azure.json` entries for Azure interfaces; `core.json` for edge/label styles
- **How:** Copy the `{style, width, height}` dict entries for relevant services into a new `config/haf_styles/interface_styles.json`. Also copy `update_style_by_key()` (6 lines) and `customize()` (3 lines) as utility functions.
- **Effort:** SMALL (JSON creation + 30 lines of Python)
- **Risk:** LOW

### OP-2: Generated Sub-Cells in Interface Slots

- **What:** Replace text-only slot values with individual mxCells inside region containers
- **Reuse from:** multicloud `add_vertex()` pattern for mxCell+mxGeometry creation (`__init__.py:409-429`); drawpyo `Object(parent=container)` parent/child nesting; governed renderer `core.py:892-920` for grid-positioned cell generation
- **How:** New function `_generate_subcells()` that creates `Et.SubElement(graph_root, 'mxCell', id=..., value=..., style=..., parent=container_id, vertex="1")` with `Et.SubElement(cell, 'mxGeometry', x=..., y=..., width=..., height=...)` — this is exactly the pattern from multicloud's `add_vertex()` adapted for template mutation
- **Effort:** MEDIUM (~100 lines)
- **Risk:** MEDIUM (needs draw.io visual verification)

### OP-3: Edge Generation Between Regions

- **What:** Generate mxCell edges connecting interface sub-cells to application core anchors
- **Reuse from:** multicloud `add_connection()` (`__init__.py:472-563`) for edge mxCell creation with labels; drawpyo `Edge.attributes` for source/target/style serialization; governed renderer `core.py:933-978` for edge + label generation inside containers
- **How:** New function `_generate_edges()` following multicloud's `Et.SubElement(root, 'mxCell', id=edge_id, edge="2", source=src_vertex, target=dst_vertex, style=...)` pattern
- **Effort:** MEDIUM (~80 lines)
- **Risk:** MEDIUM (edge routing visual quality)

### OP-4: Grid Auto-Layout

- **What:** Position generated sub-cells in grid within region container bounds
- **Reuse from:** multicloud `Distribution.Table` algorithm (`__init__.py:449-467`) — exact 20-line grid calculation; drawpyo `Group` class (`objects.py:787-850`) for bounding-box geometry helpers
- **How:** Port the Distribution.Table algorithm: `r = (count + columns - 1) // columns; x = col * width + start_x; y = row * height + start_y` — adapted to read container geometry from the template cell's mxGeometry element
- **Effort:** SMALL (~40 lines)
- **Risk:** LOW

### OP-5: Deterministic Semantic ID Scheme

- **What:** Stable composite IDs for generated cells
- **Reuse from:** multicloud `vertex:{type}:{id}` pattern (`__init__.py:411`); multicloud `generate_hash()` (`__init__.py:82-85`) for short deterministic hashes
- **How:** `haf:{profile_id}:{region_role}:{correlation_id}` for vertices; `haf:edge:{src_corr}:to:{dst_corr}` for edges
- **Effort:** SMALL (~15 lines)
- **Risk:** LOW

### OP-6: Manifest and Hash Verification

- **What:** Content hashing and machine-readable manifest
- **Reuse from:** governed renderer `core.py:267-299` `RenderManifest` dataclass; `core.py:594-596` `_compute_hash()`
- **How:** Add `HafManifest` dataclass + `_compute_hash()` function
- **Effort:** SMALL (~50 lines)
- **Risk:** LOW

### OP-7: XML Security Limits

- **What:** DTD/entity/size/depth validation on template input
- **Reuse from:** governed renderer `core.py:91-502` — `XmlParserLimits`, `parse_diagram_safely()`, `_validate_structure_limits()`
- **How:** Import and call existing `parse_diagram_safely()` from `renderer.core`
- **Effort:** SMALL (import + 5 lines)
- **Risk:** LOW

---

## 8. TDD Implementation Slices

Each slice follows RED-GREEN-REFACTOR: write failing test first, implement to make it pass, verify no regression.

### Slice 0: Baseline Snapshot

**Purpose:** Record current test baseline before any changes.

**Steps:**
1. Run `python -m pytest tests/unit/topology/ -v` — record count (expect 397)
2. Run full pipeline against real v1.7 template — save output as golden reference
3. Verify `MULTILINE_TEXT` mode produces exact text output for CCPM interfaces

**Test to write:**
```python
def test_baseline_multiline_text_azure_slot():
    """Characterization test: azure_apps_slot currently produces \\n-separated text."""
    result = fill_haf_template(
        template_bytes=REAL_V17_TEMPLATE,
        tokens=CCPM_TOKENS,
        interfaces=CCPM_INTERFACES,
        details={},
        profile_id="OUTPOST_V1",
    )
    tree = ET.fromstring(result.filled_xml)
    azure_cell = [c for c in tree.iter("mxCell") if c.get("haf-role") == "azure_apps_slot"][0]
    assert "\n" in azure_cell.get("value")  # Current behavior: newline-separated
    assert "ATTCC" in azure_cell.get("value")  # Known CCPM interface
```

**Exit criteria:** Test passes, baseline count recorded.

---

### Slice 1: MIDRANGE Location Alias + Extractor Fix

**Purpose:** Fix GAP-5 so Midrange interfaces are correctly categorized.

**Files modified:**
- `topology/guide_policy.py` — add `"MIDRANGE": "INTERNAL"` to `LOCATION_ALIASES`

**RED test:**
```python
def test_midrange_maps_to_internal():
    """MIDRANGE locations should map to INTERNAL, not UNKNOWN."""
    assert LOCATION_ALIASES.get("MIDRANGE") == "INTERNAL"
```

**GREEN:** Add `"MIDRANGE": "INTERNAL"` to `LOCATION_ALIASES` dict.

**Verify with real data:** Re-run extractor against CCPM SQLite DB — Midrange interfaces should now appear under `INTERNAL:INBOUND` etc. instead of `UNKNOWN:*`.

**Exit criteria:** Existing 397 tests + new test = 398 pass.

---

### Slice 2: XML Security Limits for HAF Parser

**Purpose:** Fix GAP-7 by importing existing security validation.

**Files modified:**
- `topology/haf_pipeline.py` — replace `ET.fromstring()` with `parse_diagram_safely()`

**Reused code:**
- `renderer/core.py:461-502` — `parse_diagram_safely()` (import, not copy)

**RED test:**
```python
def test_haf_parser_rejects_oversized_template():
    """HAF parser should reject templates exceeding size limits."""
    huge = b"<mxfile>" + b"<mxCell id='x'/>" * 100000 + b"</mxfile>"
    with pytest.raises(XmlLimitExceededError):
        parse_haf_template(huge)

def test_haf_parser_rejects_dtd():
    """HAF parser should reject templates with DTD declarations."""
    dtd = b'<!DOCTYPE foo [<!ENTITY xxe "bar">]><mxfile/>'
    with pytest.raises(XmlLimitExceededError):
        parse_haf_template(dtd)
```

**GREEN:** Import `parse_diagram_safely` from `renderer.core` and use it in `parse_haf_template()`.

**Exit criteria:** 2 new security tests + 397 existing = 399 pass.

---

### Slice 3: Cloud Provider Style Registry

**Purpose:** Create reusable style registry for interface categories (OP-1).

**Files created:**
- `topology/config/haf_styles/interface_styles.json` — styles copied from multicloud providers
- `topology/haf_styles.py` — style lookup module (~40 lines)

**Reused code from multicloud-diagrams:**
- Copy `outpost`, `ec2`, `vpc`, `subnet`, `security_group`, `direct_connect`, `route_53` entries from `providers/aws2024.json`
- Copy relevant Azure entries from `providers/azure.json`
- Copy `edge`, `label` entries from `providers/core.json`
- Port `update_style_by_key()` (6 lines) and `customize()` (3 lines)

**Reused code from drawpyo:**
- Port `style_str_from_dict()` (26 lines) for building style strings from dicts

**RED test:**
```python
def test_style_registry_loads():
    """Style registry should load and contain AWS/Azure/INTERNAL categories."""
    from migration_intake.topology.haf_styles import load_interface_styles
    styles = load_interface_styles()
    assert "AWS" in styles
    assert "AZURE" in styles
    assert "INTERNAL" in styles
    assert "mxgraph.aws4" in styles["AWS"]["style"]

def test_style_registry_has_outpost():
    """AWS style should include the Outpost icon."""
    styles = load_interface_styles()
    assert "outposts" in styles["AWS"]["style"]

def test_update_style_by_key():
    """Port of multicloud update_style_by_key."""
    from migration_intake.topology.haf_styles import update_style_by_key
    result = update_style_by_key("rounded=1;fillColor=#E6E6E6;", "fillColor", "#FF0000")
    assert "fillColor=#FF0000" in result
    assert "fillColor=#E6E6E6" not in result
```

**Exit criteria:** Style registry loads, tests pass, no behavior change.

---

### Slice 4: Sub-Cell Generation Function (OP-2, Core)

**Purpose:** Implement `_generate_subcells()` — the core of GENERATE_CELLS mode.

**Files modified:**
- `topology/haf_pipeline.py` — new `_generate_subcells()` function

**Reused patterns:**
- multicloud `add_vertex()` (`__init__.py:409-429`) — mxCell + mxGeometry creation
- multicloud deterministic ID: `vertex:{type}:{id}` -> `haf:{profile}:{region}:{corr_id}`
- multicloud `generate_hash()` for short hashes
- Governed renderer `core.py:892-920` — grid positioning inside containers

**RED test:**
```python
def test_generate_subcells_creates_correct_count():
    """Should generate one mxCell per interface entry."""
    template = b'''<mxfile><diagram><mxGraphModel><root>
        <mxCell id="0"/><mxCell id="1" parent="0"/>
        <mxCell id="region1" parent="1" vertex="1" haf-role="azure_apps_slot"
                style="rounded=1;" value="placeholder">
            <mxGeometry x="100" y="200" width="300" height="400" as="geometry"/>
        </mxCell>
    </root></mxGraphModel></diagram></mxfile>'''
    entries = [
        {"app_name": "ATTCC", "correlation_id": "12345"},
        {"app_name": "BOOST", "correlation_id": "12346"},
        {"app_name": "CCAP", "correlation_id": "12347"},
    ]
    # ... parse, generate, verify 3 new mxCells with correct parent

def test_generate_subcells_deterministic_ids():
    """Same inputs should produce same cell IDs across runs."""
    # Run twice, assert identical IDs

def test_generate_subcells_within_container_bounds():
    """All sub-cells should have geometry within the parent container."""
    # Assert all x,y,width,height within parent geometry

def test_generate_subcells_have_cloud_style():
    """Sub-cells should use styles from the interface_styles registry."""
    # Assert style contains mxgraph.aws4 for AWS category
```

**GREEN implementation (~100 lines):**
```python
def _generate_subcells(
    parent_cell: ET.Element,
    entries: list[dict[str, str]],
    region: InterfaceRegion,
    profile: HafProfile,
    graph_root: ET.Element,
    styles: dict[str, dict],
) -> list[HafMutation]:
    """Generate child mxCells inside a region container.

    Reuses patterns from:
    - multicloud-diagrams add_vertex() for mxCell creation
    - multicloud-diagrams Distribution.Table for grid layout
    - governed renderer core.py:892-920 for container positioning
    """
    # Read parent geometry
    parent_geom = parent_cell.find("mxGeometry")
    container_w = float(parent_geom.get("width", "300"))
    container_h = float(parent_geom.get("height", "400"))

    # Grid layout (ported from multicloud Distribution.Table)
    columns = 2
    cell_w = container_w / columns
    cell_h = 30
    rows = (len(entries) + columns - 1) // columns

    # Style lookup
    category_style = styles.get(region.category, styles.get("UNKNOWN", {}))

    mutations = []
    for index, entry in enumerate(sorted(entries, key=lambda e: e.get("correlation_id", ""))):
        row, col = divmod(index, columns)

        # Deterministic ID (ported from multicloud vertex:{type}:{id} pattern)
        cell_id = f"haf:{profile.profile_id}:{region.haf_role}:{entry['correlation_id']}"

        # Create mxCell (ported from multicloud add_vertex())
        label = region.format.format(**entry)
        cell = ET.SubElement(graph_root, "mxCell", {
            "id": cell_id,
            "value": label,
            "style": category_style.get("style", "rounded=1;"),
            "vertex": "1",
            "parent": parent_cell.get("id"),
        })
        ET.SubElement(cell, "mxGeometry", {
            "x": str(col * cell_w),
            "y": str(row * cell_h),
            "width": str(cell_w),
            "height": str(cell_h),
            "as": "geometry",
        })
        mutations.append(HafMutation(...))

    return mutations
```

**Verify with real v1.7 template:** Run pipeline with `azure_apps_slot` set to `GENERATE_CELLS`, open output in draw.io.

**Exit criteria:** 4+ new tests pass, existing tests unchanged.

---

### Slice 5: Grid Layout Refinement (OP-4)

**Purpose:** Ensure sub-cells fit within container bounds, handle overflow.

**Reused code:**
- multicloud `Distribution.Table` exact algorithm (`__init__.py:449-467`)
- drawpyo `Group` bounding-box helpers (`objects.py:787-850`) — conceptual

**RED test:**
```python
def test_grid_layout_32_entries_fit_in_container():
    """32 UNKNOWN interfaces should fit in the container without overflow."""
    # Create 32 entries, verify all sub-cells within 300x400 container

def test_grid_layout_auto_adjusts_columns():
    """Large counts should increase columns to prevent vertical overflow."""

def test_grid_layout_single_entry_centered():
    """Single entry should be centered in the container."""
```

**Exit criteria:** Layout tests pass, visual verification in draw.io.

---

### Slice 6: Edge Generation (OP-3)

**Purpose:** Generate directional edges between interface sub-cells and app core anchor.

**Files modified:**
- `topology/haf_pipeline.py` — new `_generate_edges()` function
- `topology/config/haf_profiles/outpost_v1.json` — add `edge_targets` and `generate_edges` fields

**Reused code:**
- multicloud `add_connection()` (`__init__.py:472-563`) — edge mxCell creation pattern
- multicloud edge ID: `edge:{src}:to:{dst}` -> `haf:edge:{src_corr}:to:{dst_corr}`
- multicloud label attachment as child of edge (`__init__.py:542-561`)
- drawpyo `Edge.attributes` (`edges.py:213-235`) — source/target/style structure
- Governed renderer `core.py:933-978` — edge generation with protocol/port labels

**RED test:**
```python
def test_generate_edges_connects_subcells_to_anchor():
    """Each interface sub-cell should get an edge to the app core anchor."""
    # Template with app_core_anchor haf-role + azure_apps_slot
    # Generate subcells + edges
    # Verify edge count == interface count
    # Verify edge source == subcell ID, target == anchor ID

def test_edge_has_protocol_label():
    """Edge should show protocol/port when available."""

def test_edge_deterministic_id():
    """Same inputs should produce same edge IDs."""
```

**Exit criteria:** Edge tests pass, edges visible in draw.io.

---

### Slice 7: Wire GENERATE_CELLS Mode Into Pipeline

**Purpose:** Connect sub-cells + edges into the main fill pipeline with feature toggle.

**Files modified:**
- `topology/haf_pipeline.py` — modify `fill_interface_regions()` to branch on `region.rendering`
- `topology/config/haf_profiles/outpost_v1.json` — set `azure_apps_slot.rendering = "GENERATE_CELLS"`

**RED test:**
```python
def test_pipeline_multiline_text_unchanged():
    """MULTILINE_TEXT regions should produce identical output to baseline."""
    # Run with all regions as MULTILINE_TEXT
    # Compare with Slice 0 golden reference

def test_pipeline_generate_cells_for_azure():
    """azure_apps_slot in GENERATE_CELLS mode should produce sub-cells."""
    result = fill_haf_template(
        template_bytes=REAL_V17_TEMPLATE,
        tokens=CCPM_TOKENS,
        interfaces=CCPM_INTERFACES,
        details={},
        profile_id="OUTPOST_V1",
    )
    tree = ET.fromstring(result.filled_xml)
    subcells = [c for c in tree.iter("mxCell")
                if c.get("id", "").startswith("haf:OUTPOST_V1:azure_apps_slot:")]
    assert len(subcells) > 0  # Sub-cells were generated

def test_pipeline_mixed_modes():
    """Some regions MULTILINE_TEXT, some GENERATE_CELLS — both work."""
```

**Exit criteria:** Both rendering modes work, existing tests pass, real template verified.

---

### Slice 8: Manifest and Hash Verification (OP-6)

**Purpose:** Add audit trail capabilities from the governed renderer.

**Reused code:**
- `renderer/core.py:267-299` — `RenderManifest` dataclass structure
- `renderer/core.py:594-596` — `_compute_hash()` function

**RED test:**
```python
def test_manifest_includes_input_output_hashes():
    """Result should include SHA-256 hashes of template, profile, and output."""
    result = fill_haf_template(...)
    assert result.manifest.template_hash
    assert result.manifest.output_hash
    assert result.manifest.profile_hash

def test_manifest_deterministic():
    """Same inputs should produce same manifest."""
    r1 = fill_haf_template(...)
    r2 = fill_haf_template(...)
    assert r1.manifest == r2.manifest
```

**Exit criteria:** Manifest tests pass, hashes stable.

---

### Slice 9: Tooltip Metadata on Sub-Cells

**Purpose:** Add hover metadata to generated sub-cells.

**Reused code:**
- multicloud `stringify_dict()` (`__init__.py:36-41`) — HTML metadata formatting
- drawpyo `tooltip` attribute (`xml_base.py:38,85-86`) — UserObject tooltip pattern

**RED test:**
```python
def test_subcell_has_tooltip_metadata():
    """Sub-cells should have tooltip with correlation ID, location, direction."""
    # Generate subcells, verify tooltip attribute
```

**Exit criteria:** Tooltips visible in draw.io on hover.

---

### Slice 10: End-to-End Integration Test

**Purpose:** Full pipeline E2E with real v1.7 template and CCPM SQLite data.

**Test:**
```python
def test_e2e_ccpm_generate_cells_opens_in_drawio():
    """Full pipeline with GENERATE_CELLS should produce a valid .drawio file."""
    # 1. Connect to local SQLite
    # 2. Extract CCPM data
    # 3. Run pipeline with GENERATE_CELLS for azure_apps_slot
    # 4. Write output to temp .drawio file
    # 5. Verify: valid XML, no duplicate IDs, sub-cells present
    # 6. Verify: all existing template cells preserved (structural safety)
    # 7. Verify: mutations + gaps report complete
```

**Exit criteria:** Output opens in draw.io, all verification checks pass.

---

## 9. Prioritized Roadmap

### Phase 0: Baseline (Slice 0)

| Step | Slice | Effort | Risk | New Tests |
|---|---|---|---|---|
| P0.1 | Slice 0: Baseline snapshot | SMALL | NONE | 1 characterization test |
| **Gate** | 397 + 1 = 398 tests pass | | | |

### Phase 1: Quick Wins (Slices 1-3)

| Step | Slice | Effort | Risk | New Tests | Reuse Source |
|---|---|---|---|---|---|
| P1.1 | Slice 1: MIDRANGE alias | SMALL | LOW | 1 | - |
| P1.2 | Slice 2: XML security limits | SMALL | LOW | 2 | renderer/core.py |
| P1.3 | Slice 3: Style registry | SMALL | LOW | 3 | multicloud providers/*.json, drawpyo style_str_from_dict |
| **Gate** | 398 + 6 = 404 tests, no behavior change in MULTILINE_TEXT | | | | |

### Phase 2: Sub-Cell Generation (Slices 4-7)

| Step | Slice | Effort | Risk | New Tests | Reuse Source |
|---|---|---|---|---|---|
| P2.1 | Slice 4: Sub-cell function | MEDIUM | MEDIUM | 4 | multicloud add_vertex, Distribution.Table |
| P2.2 | Slice 5: Grid layout | SMALL | LOW | 3 | multicloud Distribution.Table, drawpyo Group |
| P2.3 | Slice 6: Edge generation | MEDIUM | MEDIUM | 3 | multicloud add_connection, drawpyo Edge |
| P2.4 | Slice 7: Wire into pipeline | SMALL | LOW | 3 | - |
| **Gate** | 404 + 13 = 417 tests, both modes pass, visual verification | | | | |

### Phase 3: Governance and Polish (Slices 8-10)

| Step | Slice | Effort | Risk | New Tests | Reuse Source |
|---|---|---|---|---|---|
| P3.1 | Slice 8: Manifest/hashing | SMALL | LOW | 2 | renderer/core.py RenderManifest |
| P3.2 | Slice 9: Tooltip metadata | SMALL | LOW | 1 | multicloud stringify_dict, drawpyo tooltip |
| P3.3 | Slice 10: E2E integration | MEDIUM | LOW | 1 | - |
| **Gate** | 417 + 4 = 421+ tests, CCPM output approved, full regression green | | | | |

---

## 10. Recommended First Slice (Proof of Concept)

**Scope:** Slice 4 only — `_generate_subcells()` for `azure_apps_slot` with 3 test interfaces.

**Non-goals:** No edges, no tooltips, no manifest, no style registry (use hardcoded style for POC).

**Components:** `haf_pipeline.py` only — one new function.

**Success metric:** Generated .drawio opens in draw.io with 3 individual cells visible inside the Azure Apps region container.

**Rollback:** Set `azure_apps_slot.rendering = "MULTILINE_TEXT"` in profile JSON.

---

## 11. Open Questions

| # | Question | Evidence Needed | Blocking Slice |
|---|---|---|---|
| 1 | Should MIDRANGE map to INTERNAL or its own region? | Architecture team decision | Slice 1 |
| 2 | What draw.io version do users have? (mxgraph.aws4 compatibility) | User survey | Slice 3 |
| 3 | Should sub-cells be editable or locked in draw.io? | UX requirements | Slice 4 |
| 4 | Max expected interface count per app? (CCPM=55, others?) | Production DB sample | Slice 5 |
| 5 | Should edges use orthogonal or curved routing? | Architect preference | Slice 6 |
| 6 | Should HAF use `RenderManifest` contract or define its own? | Governance decision | Slice 8 |
| 7 | Multi-page support (NonProd + Prod duplication)? | Business requirements | Future |
| 8 | Compressed draw.io format support? | Template audit | Future |

---

## 12. Key Architectural Answers

**Q1: Which ideas from drawpyo/multicloud are applicable?**
- multicloud: deterministic composite IDs, provider JSON icon registry, Distribution.Table layout, add_vertex/add_connection patterns, coordinate persistence, stringify_dict metadata
- drawpyo: style_str_from_dict, Group bounding-box geometry, Object parent/child nesting, tooltip support, TOML shape database pattern

**Q2: Which approaches should HAF avoid?**
- drawpyo `id(self)` (non-deterministic)
- drawpyo string XML serialization (use ElementTree)
- multicloud single-file architecture
- Both: lack of XML validation

**Q3: Canonical topology model?**
- Current `HafIndex` is insufficient for sub-cell generation
- Should add lightweight intermediate model between extractor output and cell generation
- But keep it minimal — avoid over-engineering

**Q4: Topology semantics coupled to draw.io XML?**
- Somewhat — `fill_interface_regions()` directly manipulates mxCell attributes
- Extractor layer is clean and draw.io-agnostic (good)
- Sub-cell generation will increase coupling, but profile-driven configuration contains it

**Q5-Q12:** Answered in Improvement Opportunities and Roadmap sections above.
