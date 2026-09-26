# HAF Topology Pipeline — Technical Design and Implementation Plan

A detailed technical design and implementation plan for a focused pipeline that takes an input draw.io template with haf-role annotated cells and UNRESOLVED placeholders, resolves them from reviewed intake answers/interfaces in the application DB, and produces a single-page end-state topology diagram — built incrementally in testable execution blocks.

---

## A. Evidence Review

### A.1 Evidence Directory Catalog

The `docs/development/topo_9_24/` directory contains:

| Artifact | Purpose |
|---|---|
| `AWS__input_Outpost_Topology_UNRESOLVED_UNRESOLVED-v1.7.drawio` | Input template diagram: 1 page, 42 haf-role annotated cells, UNRESOLVED/NEEDS placeholders |
| `CCPM_out_put_18678_TargetState_AWS_OutPosts_v01 (1).drawio` | Expected output: 2 pages (NonProd + Prod), resolved values, populated interface lists |
| `CHECKPOINT.md` | Review checkpoint: read-only investigation complete, remediation not started |
| `analysis/architecture/root_causes.md` | 7 root causes (RC-01 through RC-07), semantic boundary leakage is primary |
| `analysis/architecture/target.md` | Proposed target architecture with component model, ADRs, migration plan |
| `analysis/semantic_diff/node_comparison.md` | Input: 98 vertices; Output page 1: 179; page 2: 184 |
| `analysis/semantic_diff/edge_comparison.md` | Input: 41 edges; Output page 1: 63; page 2: 76 |
| `analysis/business_rules/guide_rule_matrix.md` | 12 guide fragments, 45 blocks, standard/category/app-derived separation |
| `analysis/remediation_options/first_slice.md` | SL-PROJ-001: fail-closed on missing interface scope |
| `report/topology-review-report.html` | Assembled final review report |

### A.2 Input Diagram Structure (v1.7)

- **Format**: Uncompressed draw.io XML, root `<mxfile>`, single `<diagram>` page
- **42 haf-role annotated cells** organized into semantic categories:

**Layout/Frame:**
- `root_layer` — root mxCell layer
- `outer_frame` — outer orange border
- `header_line page_inner_frame` — page header with `NEEDS-OUTPOST-ID` placeholder

**Infrastructure (fillable):**
- `private_application_subnet` — contains `NEEDS-CIDR` and `UNRESOLVED-subnet`
- `app_security_group` — contains `UNRESOLVED-useast2-aldc-prod-sg`
- `app_account_container` — contains `ACC-PROD-0-UNRESOLVED`
- `workload_vpc workload_vpc_label` — contains `NEEDS-AZ` and `NEEDS-CIDR`
- `db_security_group` — contains `UNRESOLVED-useast2-aldc-prod-db-sg`

**AWS Services (static):**
- `cloudwatch`, `directconnect`

**Legend (protected — never mutated):**
- `legend_data_flow_block`, `legend_data_flow_label`
- `legend_protocol_ssh`, `legend_protocol_https`, `legend_protocol_sql`, `legend_protocol_jdbc`, `legend_protocol_smtp`, `legend_protocol_dataguard`, `legend_protocol_gg`, `legend_protocol_multiple`
- `legend_github_block`, `legend_application_specific`
- `legend_notes_block notes_block`

**Interface Regions (populated from interface register):**
- `att_internal_interfaces_band` — container band
- `att_internal_in_slot` — ATT Internal inbound interfaces (pre-filled with 18 app names)
- `att_internal_out_primary_slot` — ATT Internal outbound primary
- `att_internal_out_secondary_slot` — ATT Internal outbound secondary (pre-filled with 21 app names)
- `att_internal_in_out_slot` — ATT Internal bidirectional

**Azure Region (populated from interface register):**
- `azure_apps_container`, `azure_apps_slot` (pre-filled with 22 app names)
- `azure_apps_label`, `azure_apps_bridge_box`, `azure_apps_bridge_label`
- `azure_apps_icon_express_route`

**Other Regions:**
- `dns_phz_container` — DNS/PHZ group
- `tier2_internet_slot` — Tier 2 internet interfaces
- `nas_title_label`, `nas_detail_block` — NAS details
- `ebr_title_label`, `ebr_detail_block` — EBR details

### A.3 Placeholder Token Inventory (7 tokens found in input)

| # | Pattern | haf-role | Cell ID | Context |
|---|---|---|---|---|
| 1 | `NEEDS-OUTPOST-ID` | `header_line` | `7a1ef04a-...` | Page header outpost facility code |
| 2 | `NEEDS-CIDR` | `private_application_subnet` | `22e8d8a3-...` | Subnet CIDR block |
| 3 | `UNRESOLVED-subnet` | `private_application_subnet` | `22e8d8a3-...` | Subnet resource name |
| 4 | `UNRESOLVED-useast2-aldc-prod-sg` | `app_security_group` | `1881d405-...` | Security group name |
| 5 | `ACC-PROD-0-UNRESOLVED` | `app_account_container` | `fa2fbf4a-...` | AWS account ID |
| 6 | `NEEDS-AZ` + `NEEDS-CIDR` | `workload_vpc` | `dec39e72-...` | Availability zone + VPC CIDR |
| 7 | `UNRESOLVED-useast2-aldc-prod-db-sg` | `db_security_group` | `f5a560b0-...` | DB security group name |

Additional UNRESOLVED patterns found in non-haf-role cells (EC2/ENI instances):
- `UNRESOLVED-useast2-aldc-prod-app-` (App EC2 Instance)
- `UNRESOLVED-useast2-aldc-prod-app-eni` (App ENI)

### A.4 Output Diagram Structure (Target)

- **2 pages**: "CCPM-NonProd-AWS Infra connectivity" and "CCPM-Prod-AWS Infra connectivity"
- **Resolved placeholders** with real values: `ALPRGAED`, `130.x.x.x/28`, `useast2-aldc-nprd-18678-subnet-01`
- **Interface lists** populated from the interface register
- **Same structural layout** as input but with all `UNRESOLVED`/`NEEDS` tokens replaced
- **No cells removed** from the input; output is strictly additive (resolved values + second page)

### A.5 Existing Topology Code Architecture

| Module | Layer | Role |
|---|---|---|
| `topology/adapter.py` | Data extraction | Reads DB answers/identifiers, maps question codes to fact paths via `FACT_REGISTRY` |
| `topology/resolution.py` | Fact resolution | Normalize/select/build_issues/compose_names pipeline (ported from POC) |
| `topology/fill.py` | Legacy renderer | Label-text-matching slot binder, structural verification, value-only mutation |
| `topology/projection.py` | v1 projection | Snapshot JSON -> `TopologyProjection` with fact mappings |
| `topology/strict_projection.py` | v3 projection | Multi-context scoped projection with nodes/flows/exclusions |
| `topology/renderer/core.py` | Governed renderer | Profile-driven marker/slot resolution with hash verification |
| `topology/profiles/loader.py` | Profile system | JSON-based profiles with slots/tokens/markers/regions |
| `topology/scope.py` | Scope contracts | `ContextKey`, `ScopeSelection`, relationship types |
| `topology/contracts.py` | Core contracts | Schema versions, authority levels, render capabilities, canonical JSON |
| `topology/guide_policy.py` | Business rules | Interface flow normalization and guide policy |
| `application/services/topology_generation.py` | Service | Orchestrates upload, readiness check, generation, artifact storage |
| `application/services/topology_runner.py` | Service | Governed preview/official runner with lease/CAS fencing |
| `web/routes/topology.py` | Routes | Landing page, upload, generate, run detail, diagram download, approval |

### A.6 Key Architectural Decisions (User-Confirmed)

| Decision | Choice | Rationale |
|---|---|---|
| Transformation scope | **Single-page first** | Resolve one page from template; multi-page/context duplication deferred to Phase 2 |
| Rendering approach | **New focused pipeline** | Reuses contracts/models but not existing renderer complexity; pragmatic middle ground |
| Cell matching | **haf-role attributes** | Primary cell selector; reliable, deterministic, already present in input template |
| Token mapping | **Profile JSON config** | Per template type (e.g., `outpost_v1.json`); versioned and auditable |
| Interface rendering | **Profile-specified per region** | Config specifies MULTILINE_TEXT or GENERATE_CELLS per region |
| Interface scope | **Fix scope first (SL-PROJ-001)** | Fail-closed before building pipeline; prevents wrong-page placement |

---

## B. Requirements Baseline

### B.1 Functional Requirements (Phase 1: Single-Page)

| ID | Requirement | Source |
|---|---|---|
| FR-01 | Parse an input draw.io template and identify cells by `haf-role` attribute | Input diagram analysis |
| FR-02 | Resolve `NEEDS-*` and `UNRESOLVED-*` placeholder tokens in cell values using reviewed intake answers | Input-to-output comparison |
| FR-03 | Populate interface region slots (`att_internal_in_slot`, `att_internal_out_*`, `azure_apps_slot`, `tier2_internet_slot`) from the interface register | Input diagram haf-role inventory |
| FR-04 | Fill detail blocks (`nas_detail_block`, `ebr_detail_block`) from application resource data | Input diagram haf-role inventory |
| FR-05 | Validate that all mandatory placeholders are resolved before producing output | Product invariant: never invent missing values |
| FR-06 | Produce a valid draw.io XML file that preserves all non-bound cell structure | fill.py structural verification pattern |
| FR-07 | Generate a gap report listing unresolved placeholders and missing interface data | Existing `topology/report.py` pattern |
| FR-08 | The pipeline must be callable from the existing topology generation route | `web/routes/topology.py` integration |
| FR-09 | Interface scope must be fail-closed: missing environment/site produces UNKNOWN, not fabricated scope | SL-PROJ-001 + user decision |

### B.2 Non-Functional Requirements

| ID | Requirement |
|---|---|
| NFR-01 | Pure function: no DB access inside the renderer; data extraction is a separate phase |
| NFR-02 | Deterministic: same inputs produce byte-identical output |
| NFR-03 | Structural safety: only cell `value` attributes are mutated; geometry/style/structure unchanged |
| NFR-04 | No client data in test fixtures; all tests use synthetic data |
| NFR-05 | Profile config is versioned JSON; no hardcoded token mappings in code |

### B.3 Deferred to Phase 2

- Multi-page duplication (one template -> N context-specific pages)
- Governed hash verification chain (projection hash -> renderer hash -> artifact hash)
- Official generation mode with snapshot pinning
- Approval/review workflow integration
- Prototype cell cloning for structural regions

---

## C. Diagram Transformation Specification

### C.1 Placeholder Resolution Rules

| Input Pattern | haf-role | Resolution Source | Question Code / Data Path | Output Example |
|---|---|---|---|---|
| `NEEDS-OUTPOST-ID` | `header_line` | Application identifier or answer | `OUTPOST_ID` / `app.outpost_id` | `ALPRGAED` |
| `NEEDS-CIDR` | `private_application_subnet` | Answer | `SUBNET_CIDR` / `network.subnet_cidr` | `130.x.x.x/28` |
| `UNRESOLVED-subnet` | `private_application_subnet` | Composed name | naming config template | `useast2-aldc-nprd-18678-subnet-01` |
| `UNRESOLVED-...-sg` | `app_security_group` | Composed name | naming config template | `useast2-aldc-nprd-18678-sg-01` |
| `ACC-PROD-0-UNRESOLVED` | `app_account_container` | Answer | `AWS_ACCOUNT_ID` / `app.aws_account` | `ACC-PROD-0-12345` |
| `NEEDS-AZ` | `workload_vpc` | Answer | `AWS_AZ` / `env.availability_zone` | `use2-az1` |
| `NEEDS-CIDR` (VPC) | `workload_vpc` | Answer | `VPC_CIDR` / `network.vpc_cidr` | `10.x.x.x/16` |
| `UNRESOLVED-...-db-sg` | `db_security_group` | Composed name | naming config template | `useast2-aldc-nprd-18678-db-sg-01` |

### C.2 Interface Region Population Rules

| haf-role | Population Method | Data Source | Rendering |
|---|---|---|---|
| `att_internal_in_slot` | Multi-line text fill | Interface register: category=ATT_INTERNAL, direction=IN | `AppName (CorrelationID)\n...` |
| `att_internal_out_primary_slot` | Multi-line text fill | Interface register: category=ATT_INTERNAL, direction=OUT, group=PRIMARY | Same format |
| `att_internal_out_secondary_slot` | Multi-line text fill | Interface register: category=ATT_INTERNAL, direction=OUT, group=SECONDARY | Same format |
| `att_internal_in_out_slot` | Multi-line text fill | Interface register: category=ATT_INTERNAL, direction=IN_OUT | Same format or `<None found>` |
| `azure_apps_slot` | Multi-line text fill | Interface register: category=AZURE | Same format |
| `tier2_internet_slot` | Multi-line text fill | Interface register: category=TIER2_INTERNET | Same format or `<None found>` |

### C.3 Detail Block Population Rules

| haf-role | Fields | Data Source |
|---|---|---|
| `nas_detail_block` | NAS Server name, EC2 Names | Application resource register |
| `ebr_detail_block` | Strategy, EC2 Names | Application resource register |

### C.4 Cells NOT Mutated (Protected)

All `legend_*` cells, `outer_frame`, `root_layer`, AWS service icons (`cloudwatch`, `directconnect`), `dns_phz_container`, bridge/label cells, edges. These are template standard content and are listed in the profile config's `protected_roles` array.

---

## D. Detailed System Design

### D.1 New Module: `topology/haf_pipeline.py`

A focused, thin pipeline module that:
1. Parses input draw.io XML
2. Indexes cells by `haf-role`
3. Applies token resolution rules from a profile config
4. Populates interface regions from extracted data
5. Validates all mandatory slots resolved
6. Produces output XML + gap report

```
Input Template (bytes) + Extracted Data (dict) + Profile Config (JSON)
    |
    v
[1. Parse & Index by haf-role]
    |
    v
[2. Resolve placeholder tokens in cell values]
    |
    v
[3. Populate interface region slots]
    |
    v
[4. Fill detail blocks]
    |
    v
[5. Validate completeness]
    |
    v
[6. Serialize & structural verify]
    |
    v
Output XML (bytes) + Gap Report (dict) + Mutation Log (list)
```

### D.2 New Config: `topology/config/haf_profiles/outpost_v1.json`

JSON profile config mapping haf-roles to resolution rules:

```json
{
  "profile_id": "OUTPOST_V1",
  "template_version": "1.7",
  "schema_version": "1.0.0",
  "placeholder_bindings": [
    {
      "haf_role": "header_line",
      "pattern": "NEEDS-OUTPOST-ID",
      "token": "outpost_id",
      "required": true
    },
    {
      "haf_role": "private_application_subnet",
      "pattern": "NEEDS-CIDR",
      "token": "subnet_cidr",
      "required": true
    },
    {
      "haf_role": "private_application_subnet",
      "pattern": "UNRESOLVED-subnet",
      "token": "subnet_name",
      "required": true
    },
    {
      "haf_role": "app_security_group",
      "pattern_regex": "UNRESOLVED-[\\w-]+-sg",
      "token": "app_sg_name",
      "required": true
    },
    {
      "haf_role": "app_account_container",
      "pattern_regex": "ACC-[\\w-]+-UNRESOLVED",
      "token": "aws_account_id",
      "required": true
    },
    {
      "haf_role": "workload_vpc",
      "pattern": "NEEDS-AZ",
      "token": "availability_zone",
      "required": true
    },
    {
      "haf_role": "workload_vpc",
      "pattern": "NEEDS-CIDR",
      "token": "vpc_cidr",
      "required": true
    },
    {
      "haf_role": "db_security_group",
      "pattern_regex": "UNRESOLVED-[\\w-]+-db-sg",
      "token": "db_sg_name",
      "required": true
    }
  ],
  "interface_regions": [
    {
      "haf_role": "att_internal_in_slot",
      "category": "ATT_INTERNAL",
      "direction": "IN",
      "rendering": "MULTILINE_TEXT",
      "format": "{app_name} ({correlation_id})",
      "empty_value": "<None found in source data — please verify>"
    },
    {
      "haf_role": "att_internal_out_primary_slot",
      "category": "ATT_INTERNAL",
      "direction": "OUT",
      "group": "PRIMARY",
      "rendering": "MULTILINE_TEXT",
      "format": "{app_name} ({correlation_id})",
      "empty_value": "<None found in source data — please verify>"
    },
    {
      "haf_role": "att_internal_out_secondary_slot",
      "category": "ATT_INTERNAL",
      "direction": "OUT",
      "group": "SECONDARY",
      "rendering": "MULTILINE_TEXT",
      "format": "{app_name} ({correlation_id})",
      "empty_value": "<None found in source data — please verify>"
    },
    {
      "haf_role": "att_internal_in_out_slot",
      "category": "ATT_INTERNAL",
      "direction": "IN_OUT",
      "rendering": "MULTILINE_TEXT",
      "format": "{app_name} ({correlation_id})",
      "empty_value": "<None found in source data — please verify>"
    },
    {
      "haf_role": "azure_apps_slot",
      "category": "AZURE",
      "direction": null,
      "rendering": "MULTILINE_TEXT",
      "format": "{app_name} ({correlation_id})",
      "empty_value": "<None found in source data — please verify>"
    },
    {
      "haf_role": "tier2_internet_slot",
      "category": "TIER2_INTERNET",
      "direction": null,
      "rendering": "MULTILINE_TEXT",
      "format": "{app_name} ({correlation_id})",
      "empty_value": "<None found in source data — please verify>"
    }
  ],
  "detail_blocks": [
    {
      "haf_role": "nas_detail_block",
      "fields": ["nas_server", "ec2_names"],
      "template": "<b> - NAS Server</b>: {nas_server}<br><b> - EC2 Names</b>: {ec2_names}"
    },
    {
      "haf_role": "ebr_detail_block",
      "fields": ["strategy", "ec2_names"],
      "template": "<b> - Strategy: </b>{strategy}<br><b> - EC2 Names</b>: {ec2_names}"
    }
  ],
  "protected_roles": [
    "legend_*",
    "outer_frame",
    "root_layer",
    "cloudwatch",
    "directconnect",
    "dns_phz_container",
    "azure_apps_bridge_box",
    "azure_apps_bridge_label",
    "azure_apps_icon_express_route",
    "azure_apps_label",
    "att_internal_interfaces_band",
    "nas_title_label",
    "ebr_title_label"
  ]
}
```

### D.3 Data Extraction Extension: `topology/haf_extractor.py`

Extends the existing `topology/adapter.py` pattern to extract:
- All tokens needed by the profile config (reuses `FACT_REGISTRY` + new entries for `OUTPOST_ID`, `AWS_ACCOUNT_ID`, `AWS_AZ`)
- Interface data grouped by category/direction from the interface register
- Resource details for detail blocks (NAS server, EBR strategy, EC2 names)
- Composed names using existing `topology/resolution.py` naming pipeline

Returns an `HafExtractionResult` dataclass with:
```python
@dataclass
class HafExtractionResult:
    tokens: dict[str, str]       # token_name -> resolved value
    interfaces: dict[str, list]  # "category:direction" -> list of {app_name, correlation_id}
    details: dict[str, dict]     # haf_role -> {field_name: value}
    issues: list[dict]           # extraction issues/gaps
```

### D.4 Integration Point

The existing route `POST /applications/{app_id}/intakes/{intake_id}/topology/generate` calls `TopologyGenerationService.generate_topology()`. The new pipeline will be callable through this same flow:

1. Route sends profile_id alongside base_artifact_id
2. Service detects haf-role-based template (via profile_id or template attribute inspection)
3. Service calls `haf_extractor.extract()` to get tokens + interfaces + details
4. Service calls `haf_pipeline.fill_haf_template()` with template bytes + extracted data + profile
5. Service stores output XML + gap report as artifacts and creates run record

### D.5 Scope Safety (SL-PROJ-001 — Prerequisite)

Before building the pipeline, fix `strict_projection.py` `_project_semantic_graph()` so that interface flows with missing environment/site scope produce `UNKNOWN_FLOW_SCOPE` exclusions instead of inheriting the request context. This is a prerequisite because `haf_extractor` will read interface data and must not fabricate scope.

---

## E. Logical Execution Blocks

### Block 0: Scope Safety Fix (SL-PROJ-001)

| Field | Value |
|---|---|
| **Purpose** | Ensure missing interface scope fails closed before any pipeline work |
| **Files to modify** | `src/migration_intake/topology/strict_projection.py` |
| **Files to create** | `tests/unit/topology/test_projection_scope_safety.py` |
| **Inputs** | Synthetic v3 snapshot with interface rows lacking scope |
| **Outputs** | Blocking `UNKNOWN_FLOW_SCOPE` exclusion; no fabricated EXPLICIT flow |
| **Dependencies** | None |

**Validation criteria:**
- `test_single_context_does_not_supply_missing_interface_scope` — RED then GREEN
- `test_known_interface_scope_must_match_selected_context` — RED then GREEN
- `test_multi_context_missing_scope_is_blocking_once` — RED then GREEN
- Existing topology tests still pass: `python -m pytest tests/unit/topology/ -v`

---

### Block 1: haf-role Parser and Indexer

| Field | Value |
|---|---|
| **Purpose** | Parse draw.io XML and build a lookup dict of `haf-role -> list[mxCell]` |
| **Files to create** | `src/migration_intake/topology/haf_pipeline.py` (initial skeleton) |
| **Files to create** | `tests/unit/topology/test_haf_pipeline.py` |
| **Inputs** | Raw draw.io XML bytes |
| **Outputs** | `HafIndex` dataclass with `by_role: dict[str, list[ET.Element]]`, `all_roles: set[str]`, validation errors |
| **Dependencies** | None (pure XML parsing) |

**Validation criteria:**
- Parse synthetic input template fixture -> 42 roles indexed
- Reject compressed/invalid XML
- Reject XML with duplicate cell IDs
- `haf-role` attribute with multiple space-separated roles (e.g. `"header_line page_inner_frame"`) indexes under each role
- Cells without `haf-role` are preserved in the tree but not indexed
- Acceptance: `python -m pytest tests/unit/topology/test_haf_pipeline.py -k index -v`

---

### Block 2: Profile Config Loader

| Field | Value |
|---|---|
| **Purpose** | Load and validate haf profile JSON configs |
| **Files to modify** | `src/migration_intake/topology/haf_pipeline.py` (add profile loading) |
| **Files to create** | `src/migration_intake/topology/config/haf_profiles/outpost_v1.json` |
| **Inputs** | Profile JSON path or ID |
| **Outputs** | `HafProfile` dataclass with typed `placeholder_bindings`, `interface_regions`, `detail_blocks`, `protected_roles` |
| **Dependencies** | Block 1 (uses same module) |

**Validation criteria:**
- Load outpost_v1 profile -> all required fields parsed
- Reject malformed/missing profiles with typed error
- Validate `protected_roles` glob patterns (e.g. `legend_*`) match correctly
- Validate haf_role references resolve in a given HafIndex
- Acceptance: `python -m pytest tests/unit/topology/test_haf_pipeline.py -k profile -v`

---

### Block 3: Placeholder Token Resolver

| Field | Value |
|---|---|
| **Purpose** | Resolve `NEEDS-*` and `UNRESOLVED-*` patterns in cell values using extracted token data |
| **Files to modify** | `src/migration_intake/topology/haf_pipeline.py` (add resolver) |
| **Inputs** | `HafIndex` + `HafProfile` + `tokens: dict[str, str]` |
| **Outputs** | Mutated cell values + `list[HafMutation]` records + `list[HafGap]` for unresolved tokens |
| **Dependencies** | Blocks 1, 2 |

**Validation criteria:**
- Synthetic template with 7 NEEDS/UNRESOLVED tokens + complete token dict -> all 7 resolved, 0 gaps
- Synthetic template + partial token dict -> resolved tokens filled, missing required tokens produce `HafGap` with `blocking=True`
- Protected cells (legend_*) are never mutated even if they contain matching patterns
- Only `value` attribute changes; structural snapshot before/after identical (reuses `fill.py` `_structural_snapshot` pattern)
- Both literal `pattern` and `pattern_regex` matching work correctly
- Acceptance: `python -m pytest tests/unit/topology/test_haf_pipeline.py -k resolver -v`

---

### Block 4: Interface Region Filler

| Field | Value |
|---|---|
| **Purpose** | Populate interface region cells with data from the interface register |
| **Files to modify** | `src/migration_intake/topology/haf_pipeline.py` (add interface filler) |
| **Inputs** | `HafIndex` + `HafProfile` + `interfaces: dict[str, list[dict]]` (keyed by `"category:direction"`) |
| **Outputs** | Mutated interface slot cell values + mutation records |
| **Dependencies** | Blocks 1, 2 |

**Validation criteria:**
- Synthetic ATT_INTERNAL IN interfaces (3 apps) -> `att_internal_in_slot` value = `"AppA (1001)\nAppB (1002)\nAppC (1003)"`
- Empty interface list -> slot value = configured `empty_value` text from profile
- Profile specifies `MULTILINE_TEXT` -> value is newline-joined using `format` template
- Structural postflight passes (geometry/style/structure unchanged)
- Acceptance: `python -m pytest tests/unit/topology/test_haf_pipeline.py -k interface -v`

---

### Block 5: Detail Block Filler

| Field | Value |
|---|---|
| **Purpose** | Fill detail blocks (NAS, EBR) with resource data |
| **Files to modify** | `src/migration_intake/topology/haf_pipeline.py` (add detail filler) |
| **Inputs** | `HafIndex` + `HafProfile` + `details: dict[str, dict]` |
| **Outputs** | Mutated detail block cell values + mutation records |
| **Dependencies** | Blocks 1, 2 |

**Validation criteria:**
- Synthetic NAS data -> `nas_detail_block` filled with HTML template from profile
- Missing data fields -> detail block value preserves template with empty values (not placeholder markers)
- Structural postflight passes
- Acceptance: `python -m pytest tests/unit/topology/test_haf_pipeline.py -k detail -v`

---

### Block 6: Pipeline Orchestrator + Gap Report

| Field | Value |
|---|---|
| **Purpose** | Wire blocks 3-5 into one `fill_haf_template()` function that runs validation and produces output |
| **Files to modify** | `src/migration_intake/topology/haf_pipeline.py` (add orchestrator) |
| **Inputs** | `template_bytes: bytes`, `tokens: dict`, `interfaces: dict`, `details: dict`, `profile_id: str` |
| **Outputs** | `HafFillResult` with `filled_xml: bytes`, `mutations: list`, `gaps: list`, `success: bool` |
| **Dependencies** | Blocks 1-5 |

**Validation criteria:**
- Full synthetic flow: template + all data -> `success=True`, valid draw.io XML, 0 gaps
- Missing mandatory token -> `success=False`, gaps list populated with blocking gap
- Structural postflight: before/after snapshot identical except `value` of bound cells
- Gap report includes `haf_role`, expected `token`, resolution `status` for every binding
- Output XML is well-formed and parseable as draw.io
- Mutation log is ordered and complete
- Acceptance: `python -m pytest tests/unit/topology/test_haf_pipeline.py -k orchestrator -v`

---

### Block 7: Data Extractor for haf Pipeline

| Field | Value |
|---|---|
| **Purpose** | Extract tokens, interfaces, and details from the database for a given intake |
| **Files to create** | `src/migration_intake/topology/haf_extractor.py` |
| **Files to create** | `tests/unit/topology/test_haf_extractor.py` |
| **Inputs** | SQLAlchemy Session + intake_id + profile_id |
| **Outputs** | `HafExtractionResult` with `tokens: dict`, `interfaces: dict`, `details: dict`, `issues: list` |
| **Dependencies** | Block 6 (defines the expected data shape), existing `adapter.py` and `resolution.py` |

**Validation criteria:**
- Synthetic DB fixtures (in-memory SQLite) -> correct token extraction from answers + identifiers
- Interface register query returns grouped interfaces by category/direction
- Missing answer -> token value is placeholder, listed in issues
- Composed name tokens use naming config resolution
- No DB access happens outside this module (pipeline remains pure)
- Acceptance: `python -m pytest tests/unit/topology/test_haf_extractor.py -v`

---

### Block 8: Service Integration

| Field | Value |
|---|---|
| **Purpose** | Wire the haf pipeline into `TopologyGenerationService` as a new generation path |
| **Files to modify** | `src/migration_intake/application/services/topology_generation.py` |
| **Files to modify** | `src/migration_intake/web/routes/topology.py` (add profile selection to generation form) |
| **Inputs** | User clicks "Generate" with a selected base template + profile |
| **Outputs** | Generation run record with diagram + report artifacts stored |
| **Dependencies** | Blocks 6, 7 |

**Validation criteria:**
- Integration test: create application + intake + answers + upload haf-role template -> generate with profile_id -> run created with artifacts
- Route returns redirect to run detail page
- Run record has correct status, artifact hashes, mutation count
- Non-haf templates continue to use the existing generation path (backward compatible)
- Acceptance: `python -m pytest tests/integration/test_haf_generation.py -v`

---

### Block 9: End-to-End Verification

| Field | Value |
|---|---|
| **Purpose** | Validate the complete workflow from UI through to artifact download |
| **Files to create** | `tests/integration/test_haf_e2e.py` |
| **Inputs** | Synthetic application with realistic answers + synthetic input template with haf-roles |
| **Outputs** | Downloaded diagram has all placeholders resolved, interface slots populated |
| **Dependencies** | Block 8 |

**Validation criteria:**
- Synthetic answers for all 7 placeholders -> output XML has zero `NEEDS-` or `UNRESOLVED-` tokens
- Interface slots contain expected app names from synthetic register
- Downloaded diagram is valid draw.io XML (parseable, mxfile root, diagram page present)
- Gap report is empty (all resolved)
- Existing generation routes/tests not broken
- Acceptance: `python -m pytest tests/integration/test_haf_e2e.py -v`

---

## F. Implementation Plan (Roadmap)

### Phase 1: Foundation (Blocks 0-2)

| Step | Block | Estimated Effort | Gate |
|---|---|---|---|
| 1 | Block 0: Scope safety fix (SL-PROJ-001) | Small | 3 new tests GREEN + existing topology tests pass |
| 2 | Block 1: haf-role parser/indexer | Small | Parser tests GREEN |
| 3 | Block 2: Profile config loader + outpost_v1.json | Small | Profile tests GREEN |

### Phase 2: Core Pipeline (Blocks 3-6)

| Step | Block | Estimated Effort | Gate |
|---|---|---|---|
| 4 | Block 3: Placeholder token resolver | Medium | Resolver tests GREEN + structural postflight |
| 5 | Block 4: Interface region filler | Medium | Interface tests GREEN |
| 6 | Block 5: Detail block filler | Small | Detail tests GREEN |
| 7 | Block 6: Pipeline orchestrator + gap report | Medium | Full pipeline tests GREEN + structural postflight |

### Phase 3: Integration (Blocks 7-9)

| Step | Block | Estimated Effort | Gate |
|---|---|---|---|
| 8 | Block 7: Database extractor | Medium | Extractor tests GREEN with in-memory SQLite |
| 9 | Block 8: Service/route integration | Medium | Integration test GREEN |
| 10 | Block 9: End-to-end verification | Small | E2E test GREEN + full test suite passes |

### Phase 2b (Future — Not in Scope)

- Page duplication logic (one template page -> N context-specific pages)
- Per-page scope selection from reviewed context keys
- Interface filtering by environment/site scope
- Governed hash chain integration

---

## G. Test Strategy

### G.1 Unit Tests (Blocks 0-6)

All unit tests use **synthetic fixtures only** (no client data per `AGENTS.md`).

| Test File | Covers | Key Assertions |
|---|---|---|
| `tests/unit/topology/test_projection_scope_safety.py` | Block 0 | UNKNOWN_FLOW_SCOPE exclusion for missing scope |
| `tests/unit/topology/test_haf_pipeline.py` | Blocks 1-6 | Parser, profile loader, resolver, fillers, orchestrator |

**Synthetic fixtures required:**
- Minimal draw.io template XML with representative haf-roles and placeholder tokens (~15 cells covering each role category)
- Profile JSON with bindings for the synthetic template
- Token dicts (complete and partial)
- Interface lists (populated and empty)
- Detail block data

### G.2 Integration Tests (Blocks 7-9)

| Test File | Covers | Key Assertions |
|---|---|---|
| `tests/unit/topology/test_haf_extractor.py` | Block 7 | DB extraction with in-memory SQLite synthetic fixtures |
| `tests/integration/test_haf_generation.py` | Block 8 | Service + route integration |
| `tests/integration/test_haf_e2e.py` | Block 9 | Full workflow end-to-end |

### G.3 Verification Commands

After each block:
```bash
python -m pytest tests/unit/topology/ -v                # Unit tests
python -m mypy src/migration_intake/topology/            # Type check
python -m ruff check src/migration_intake/topology/      # Lint
```

After integration blocks:
```bash
python -m pytest tests/integration/ -v    # Integration tests
python -m pytest tests/ -v                # Full suite
```

### G.4 Block Completion Definition

A block is complete when:
1. All its defined tests pass
2. No existing tests are broken (`python -m pytest tests/unit/topology/ -v` passes)
3. `mypy` and `ruff` pass for modified files
4. Structural postflight (where applicable) confirms no unintended cell mutations

---

## H. Risks, Assumptions, and Open Questions

### H.1 Risks

| Risk | Impact | Mitigation |
|---|---|---|
| Interface register schema may lack category/direction columns matching profile expectations | Block 4/7 needs schema adaptation | Inspect `persistence/models_interfaces.py` before Block 4; add mapping layer if needed |
| Composed names (UNRESOLVED-*) require naming config that may not cover all patterns | Block 3 tokens might not resolve all patterns | Profile config includes explicit regex patterns; unresolved patterns produce gaps, never wrong values |
| Input templates from different applications may use different haf-role vocabularies | Profile config becomes application-specific | By design: each template type gets its own profile JSON |
| Performance: large interface lists (100+ entries) in a single cell value | Draw.io rendering slowdown | Configurable max per region in profile config; excess produces gap/truncation |
| Non-haf-role cells with UNRESOLVED patterns (EC2/ENI instances) need a different resolution mechanism | Incomplete resolution in Phase 1 | Document as known gap; profile config can be extended with non-haf-role patterns in a follow-up |

### H.2 Assumptions

1. **The input template will always have `haf-role` attributes.** Templates without `haf-role` are not supported by this pipeline; they continue using the legacy `fill.py` path.
2. **Single-page first.** Multi-page duplication is Phase 2.
3. **Interface data is queryable by category and direction.** The existing interface register model supports this or can be extended with a lightweight mapping.
4. **The profile JSON config is authored by a developer/architect and version-controlled**, not user-editable at runtime.
5. **Composed names use the existing naming config** (`topology/config/naming.json`) plus profile-specific template patterns.
6. **The existing `fill.py` structural postflight pattern** (snapshot before/after comparison) is the correct safety mechanism for the new pipeline.

### H.3 Open Questions

| # | Question | Impact | Resolution Path |
|---|---|---|---|
| Q-01 | What are the exact column names in the interface register for category and direction? | Block 4/7 implementation | Inspect `persistence/models_interfaces.py` before Block 4 |
| Q-02 | Are NAS/EBR detail fields stored as answers, resources, or separate register entries? | Block 5/7 implementation | Inspect application resource model before Block 5 |
| Q-03 | Should composed names (e.g., `useast2-aldc-nprd-18678-subnet-01`) use the existing `resolution.py` naming pipeline or new profile-defined templates? | Block 3 detail design | Recommend profile-defined templates for new pipeline; reuse naming config for abbreviations |
| Q-04 | How should the pipeline handle templates with haf-roles not defined in the profile? | Error handling strategy | Recommend: log as WARNING, do not mutate, include in gap report |
| Q-05 | Should non-haf-role cells with UNRESOLVED patterns (EC2/ENI instances on line 407) be handled in Phase 1? | Completeness of Phase 1 output | Recommend: document as known gap; extend profile config schema in follow-up block |

---

## I. Next Steps

### Immediate (Begin Implementation)

1. **Block 0**: SL-PROJ-001 scope safety fix in `strict_projection.py` — prerequisite for all interface work
2. **Block 1 + Block 2** in parallel: parser/indexer and profile config are independent
3. Proceed sequentially through Blocks 3-9

### After Phase 1 Complete

- Update `STATE.md` with haf pipeline status
- Update both plan documents (`topology-implementation-plan.md` and HTML)
- Propose Phase 2 (multi-page duplication)

### Files to Create (New)

| File | Block | Purpose |
|---|---|---|
| `src/migration_intake/topology/haf_pipeline.py` | 1-6 | Core pipeline: parser, resolver, fillers, orchestrator |
| `src/migration_intake/topology/haf_extractor.py` | 7 | Database extraction for haf pipeline |
| `src/migration_intake/topology/config/haf_profiles/outpost_v1.json` | 2 | Outpost template profile config |
| `tests/unit/topology/test_projection_scope_safety.py` | 0 | Scope safety tests |
| `tests/unit/topology/test_haf_pipeline.py` | 1-6 | Pipeline unit tests |
| `tests/unit/topology/test_haf_extractor.py` | 7 | Extractor unit tests |
| `tests/integration/test_haf_generation.py` | 8 | Service integration tests |
| `tests/integration/test_haf_e2e.py` | 9 | End-to-end tests |

### Files to Modify (Existing)

| File | Block | Change |
|---|---|---|
| `src/migration_intake/topology/strict_projection.py` | 0 | Scope safety fix in `_project_semantic_graph()` |
| `src/migration_intake/application/services/topology_generation.py` | 8 | Add haf pipeline generation path |
| `src/migration_intake/web/routes/topology.py` | 8 | Add profile selection to generation form |
| `STATE.md` | 9 | Update after Phase 1 completion |

---

## J. Implementation Status and End-to-End Testing Guide

> **Added after Blocks 0-9 implementation completed — 2026-09-24**

### J.1 Implementation Status

All 10 execution blocks (0-9) are **implemented and tested**.

| Block | Component | Source File | Test File | Tests | Status |
|---|---|---|---|---|---|
| 0 | SL-PROJ-001 scope safety fix | `strict_projection.py` (modified) | `test_projection_scope_safety.py` | 4 | GREEN |
| 1 | haf-role XML parser/indexer | `haf_pipeline.py` | `test_haf_pipeline.py` | 9 | GREEN |
| 2 | Profile config loader + outpost_v1.json | `haf_pipeline.py` + `config/haf_profiles/outpost_v1.json` | `test_haf_pipeline.py` | 8 | GREEN |
| 3 | Placeholder token resolver | `haf_pipeline.py` | `test_haf_pipeline.py` | 6 | GREEN |
| 4 | Interface region filler | `haf_pipeline.py` | `test_haf_pipeline.py` | 4 | GREEN |
| 5 | Detail block filler | `haf_pipeline.py` | `test_haf_pipeline.py` | 3 | GREEN |
| 6 | Pipeline orchestrator + gap report | `haf_pipeline.py` | `test_haf_pipeline.py` | 6 | GREEN |
| 7 | Database extractor | `haf_extractor.py` | `test_haf_extractor.py` | 5 | GREEN |
| 8 | Service integration | `haf_service.py` | `test_haf_service.py` | 3 | GREEN |
| 9 | E2E with real v1.7 template | (none) | `test_haf_e2e.py` | 5 | GREEN |

**Total: 53 new tests, all passing. Full topology unit suite: 397 passed, 0 failed.**

Git commits:
- `aac8081` — Blocks 0-6 (core pipeline)
- `9818da7` — Blocks 7-9 (DB extractor, service, E2E)

### J.2 Architecture Overview

```
User clicks "Generate Topology" in UI
POST /applications/{app_id}/intakes/{intake_id}/topology/...
        |
        v
haf_service.generate_haf_topology(session, intake_id,
                                   profile_id, template_bytes)

  Step 1: haf_extractor.extract_haf_data(session, intake_id, profile_id)
    -> Reads answers (response_json), identifiers, interfaces from DB
    -> Groups interfaces by LOCATION_ALIASES category + direction
    -> Returns: tokens dict, interfaces dict, details dict, issues

  Step 2: haf_pipeline.fill_haf_template(template_bytes, tokens,
          interfaces, details, profile_id)
    -> Parses draw.io XML, indexes cells by haf-role
    -> Loads profile from outpost_v1.json
    -> Resolves NEEDS-*/UNRESOLVED-* placeholders from tokens
    -> Fills interface region slots with grouped interface data
    -> Fills detail blocks
    -> Serializes filled XML
    -> Returns: filled_xml bytes, mutations, gaps

  Returns: HafTopologyResult(filled_xml, mutations, gaps,
           extraction_issues, success)
```

### J.3 Files Created

| File | Purpose |
|---|---|
| `src/migration_intake/topology/haf_pipeline.py` | Pure pipeline: parser, profile loader, resolver, fillers, orchestrator |
| `src/migration_intake/topology/haf_extractor.py` | DB extraction layer (tokens, interfaces, details) |
| `src/migration_intake/topology/haf_service.py` | Service entry point: wires extractor + pipeline |
| `src/migration_intake/topology/config/haf_profiles/outpost_v1.json` | OUTPOST_V1 profile config (8 placeholder bindings, 6 interface regions, 2 detail blocks) |
| `tests/unit/topology/test_projection_scope_safety.py` | Block 0 scope safety tests |
| `tests/unit/topology/test_haf_pipeline.py` | Blocks 1-6 pipeline tests |
| `tests/unit/topology/test_haf_extractor.py` | Block 7 extractor tests (in-memory SQLite) |
| `tests/unit/topology/test_haf_service.py` | Block 8 service integration tests |
| `tests/unit/topology/test_haf_e2e.py` | Block 9 E2E tests with real v1.7 template |

### J.4 Real CCPM Data Verification (Local SQLite DB)

The pipeline was verified against the live local SQLite database (`migration_intake.db`) containing the real CCPM application data:

**Application in DB:**
- App: `CCPM` (id: `96353d13-12fd-4984-bec1-719d1fd8e6da`)
- Correlation ID: `18678`
- Intake: `26385e58-8954-4312-bf27-9d8414c79421` (state: DRAFT)
- 55 interface records (ACTIVE)
- 28 answer revisions

**Pipeline extraction from real DB:**
- Tokens extracted: `app_name=CCPM`, `correlation_id=18678`
- 8 tokens missing (infrastructure tokens like CIDR, account ID — not in current catalog answers)
- 6 interface groups extracted:
  - `AWS:OUTBOUND` — 1 entry (DTV-VDAS)
  - `AZURE:INBOUND` — 9 entries (ATTCC, BOOST, CCAP, CENET, CP, FIN_DATA_AUTO, HZNREP, NEXXUS, OCE)
  - `AZURE:OUTBOUND` — 13 entries (ACM-C, AT&T-MicroStrategy, AZDP, DPG-Sales, DPG-UDART, eCDW Sunrise, FIN_DATA_AUTO, HZNREP x2, NEXXUS, OSP, TT-C, Varicent-ETL)
  - `UNKNOWN:INBOUND` — 18 entries (Midrange: ORACLE SCM, DITREX, LS-OMS, CCR-R, EDW, EDGE, LS CRM, CPC, ATT VERINT CQM, Enabler LS, TLG-MOB, OPUS-C, uDAS, eCDW, SOCS, CCQT, OVALS GIS, Saart)
  - `UNKNOWN:OUTBOUND` — 6 entries (CPC, MSTRS, Mylogin, eCDW, CCPM self-ref x2)
  - `UNKNOWN:UNKNOWN` — 8 entries (missing location/direction: CCT WFM QPC MIG, CCWEB, CRFT, DVT, External Consumer Interface, ImE FLEX, MyTracker, RMCAS)

**Pipeline result: 8 mutations applied, 8 gaps reported, output diagram: 120,985 bytes**

**Important finding:** `Midrange` location is NOT in `guide_policy.LOCATION_ALIASES` and maps to `UNKNOWN`. The 24+ Midrange interfaces go into `UNKNOWN:*` groups and end up in the `tier2_internet_slot`. To fix this, add `"MIDRANGE": "INTERNAL"` to `LOCATION_ALIASES` in `guide_policy.py` (requires architectural decision).

---

## K. End-to-End Testing Guide

### K.1 Prerequisites

Before running any tests, ensure:

1. **Local app is running** at `http://localhost:8000/applications/`
   - Start with: `cd C:\GitHub\aws_diag_v4_1\aws_diag_v4 && python -m uvicorn migration_intake.web.app:app --reload --port 8000`
2. **SQLite database exists** at `./migration_intake.db` with CCPM data
   - Verify: the file should be approximately 970 KB
3. **Python environment** with the project installed: `pip install -e ".[dev]"`
4. **Input template** exists at `docs/development/topo_9_24/AWS__input_Outpost_Topology_UNRESOLVED_UNRESOLVED-v1.7.drawio`

### K.2 Step 1 — Automated Test Suite (run these first)

These tests use in-memory SQLite with synthetic data (no external DB needed).

```bash
cd C:\GitHub\aws_diag_v4_1\aws_diag_v4

# Block 0: Scope safety fix
python -m pytest tests/unit/topology/test_projection_scope_safety.py -v
# Expected: 4 passed

# Blocks 1-6: Parser, profile, resolver, fillers, orchestrator
python -m pytest tests/unit/topology/test_haf_pipeline.py -v
# Expected: 36 passed

# Block 7: DB extractor (in-memory SQLite)
python -m pytest tests/unit/topology/test_haf_extractor.py -v
# Expected: 5 passed

# Block 8: Service integration (in-memory SQLite)
python -m pytest tests/unit/topology/test_haf_service.py -v
# Expected: 3 passed

# Block 9: E2E with real v1.7 template (in-memory SQLite + synthetic data)
python -m pytest tests/unit/topology/test_haf_e2e.py -v
# Expected: 5 passed

# ALL haf pipeline tests together (quick combined check)
python -m pytest tests/unit/topology/test_haf_pipeline.py tests/unit/topology/test_haf_extractor.py tests/unit/topology/test_haf_service.py tests/unit/topology/test_haf_e2e.py tests/unit/topology/test_projection_scope_safety.py -v
# Expected: 53 passed

# Full topology unit suite (regression gate)
python -m pytest tests/unit/topology/ -v
# Expected: 397 passed, 0 failed
```

**STOP here if any test fails.** Investigate before proceeding to live DB testing.

### K.3 Step 2 — Run Pipeline Against Live CCPM SQLite DB

This step runs the actual pipeline against the live `migration_intake.db` containing real CCPM data.

```python
# Save as: test_live_ccpm.py  (or run inline with python -c)
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from migration_intake.topology.haf_service import generate_haf_topology

engine = create_engine("sqlite:///./migration_intake.db")
template = open(
    "docs/development/topo_9_24/"
    "AWS__input_Outpost_Topology_UNRESOLVED_UNRESOLVED-v1.7.drawio", "rb"
).read()

with Session(engine) as session:
    result = generate_haf_topology(
        session=session,
        intake_id="26385e58-8954-4312-bf27-9d8414c79421",
        profile_id="OUTPOST_V1",
        template_bytes=template,
    )

print(f"Success: {result.success}")
print(f"Mutations: {len(result.mutations)}")
print(f"Gaps: {len(result.gaps)}")
print(f"Extraction issues: {len(result.extraction_issues)}")
print(f"Output size: {len(result.filled_xml)} bytes")
print()
print("--- Mutations ---")
for m in result.mutations:
    print(f"  {m.haf_role:35s} token={m.token}")
print()
print("--- Gaps ---")
for g in result.gaps:
    print(f"  {g.haf_role:35s} token={g.token:20s} blocking={g.blocking}")
print()
print("--- Extraction Issues ---")
for i in result.extraction_issues:
    print(f"  {i}")

# Save output for manual review
import os, json
os.makedirs("docs/output/haf-pipeline", exist_ok=True)
with open("docs/output/haf-pipeline/ccpm_filled_topology.drawio", "wb") as f:
    f.write(result.filled_xml)
report = {
    "success": result.success,
    "mutations": [{"cell_id": m.cell_id, "role": m.haf_role, "token": m.token}
                  for m in result.mutations],
    "gaps": [{"role": g.haf_role, "token": g.token, "blocking": g.blocking}
             for g in result.gaps],
    "extraction_issues": result.extraction_issues,
}
with open("docs/output/haf-pipeline/ccpm_gap_report.json", "w") as f:
    json.dump(report, f, indent=2)
print()
print("Output saved to docs/output/haf-pipeline/")
```

**Expected output:**
```
Success: False
Mutations: 8
Gaps: 8
Extraction issues: 8
Output size: ~120985 bytes
```

**Success is `False`** because there are blocking gaps (infrastructure tokens not answered in the CCPM catalog). The CCPM catalog only has application-level questions (APP-*, SEC-*, CTL-*, RES-*, APR-*), not infrastructure questions (VPC_CIDR, SUBNET_CIDR, etc.). The 8 mutations (interface fills + detail blocks) are applied successfully.

### K.4 Step 3 — Open the Filled Diagram in draw.io

1. Open `docs/output/haf-pipeline/ccpm_filled_topology.drawio` in:
   - **draw.io Desktop App** (recommended), or
   - **[app.diagrams.net](https://app.diagrams.net)** (web version)

2. **Verify interface regions are populated with real CCPM data:**

   | Region in Diagram | Expected Content |
   |---|---|
   | AT&T Internal Inbound slot | Empty or placeholder (no INTERNAL:INBOUND in DB since Midrange maps to UNKNOWN) |
   | AT&T Internal Outbound slot | Empty or placeholder (same reason) |
   | Azure Apps slot | ATTCC, BOOST, CCAP, CENET, CP, FIN_DATA_AUTO, HZNREP, NEXXUS, OCE, ACM-C, AT&T-MicroStrategy, AZDP, DPG-Sales, DPG-UDART, eCDW Sunrise, etc. (22 entries) |
   | Tier 2 / Internet slot | UNKNOWN-category interfaces (Midrange + missing-location: 32 entries) |

3. **Verify unresolved tokens remain as placeholders:**
   - Header should still contain `NEEDS-OUTPOST-ID`
   - Subnet should still contain `NEEDS-CIDR` and `UNRESOLVED-subnet`
   - VPC should still contain `NEEDS-AZ` and `NEEDS-CIDR`
   - Security groups should still have unresolved names

4. **Verify structural integrity visually:**
   - Open the original input template side-by-side: `docs/development/topo_9_24/AWS__input_Outpost_Topology_UNRESOLVED_UNRESOLVED-v1.7.drawio`
   - All cell positions, sizes, colors, and styles should be identical
   - Only the `value` text in interface slots, detail blocks, and header should differ

5. **Verify protected cells are unchanged:**
   - Legend cells (HTTPS protocol label, data flow arrows) must be identical to input
   - Frame cell must not change

### K.5 Step 4 — Compare Against the Expected Output

1. Open `docs/development/topo_9_24/CCPM_out_put_18678_TargetState_AWS_OutPosts_v01 (1).drawio` (the manually-crafted target output)
2. Compare interface name lists between the expected output and pipeline output
3. **Known differences (expected):**
   - Expected output has **2 pages** (NonProd + Prod) — the haf pipeline produces **1 page** (multi-page is Phase 2)
   - Expected output has **resolved infrastructure values** (CIDR, account ID, security groups) — these require additional catalog questions
   - Expected output has **Midrange interfaces categorized under ATT/Internal** — our pipeline currently maps Midrange to UNKNOWN

### K.6 Step 5 — Structural Safety Verification (automated)

Run this to programmatically prove the pipeline only mutates `value` attributes:

```python
# Save as: test_structural_safety.py
import xml.etree.ElementTree as ET
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from migration_intake.topology.haf_service import generate_haf_topology

engine = create_engine("sqlite:///./migration_intake.db")
template = open(
    "docs/development/topo_9_24/"
    "AWS__input_Outpost_Topology_UNRESOLVED_UNRESOLVED-v1.7.drawio", "rb"
).read()

with Session(engine) as session:
    result = generate_haf_topology(
        session=session,
        intake_id="26385e58-8954-4312-bf27-9d8414c79421",
        profile_id="OUTPOST_V1",
        template_bytes=template,
    )

before = ET.fromstring(template)
after = ET.fromstring(result.filled_xml)

before_cells = {c.get("id"): c for c in before.iter("mxCell") if c.get("id")}
after_cells = {c.get("id"): c for c in after.iter("mxCell") if c.get("id")}

print(f"Cells before: {len(before_cells)}")
print(f"Cells after:  {len(after_cells)}")
assert set(before_cells) == set(after_cells), "FAIL: Cell set changed!"
print("Cell set: IDENTICAL")

structural_ok = True
value_changes = 0
for cid in before_cells:
    bc, ac = before_cells[cid], after_cells[cid]
    for attr in ("parent", "style", "vertex", "edge", "source", "target"):
        if bc.get(attr) != ac.get(attr):
            print(f"STRUCTURAL VIOLATION: {attr} changed for {cid}")
            structural_ok = False
    bg, ag = bc.find("mxGeometry"), ac.find("mxGeometry")
    if bg is not None and ag is not None:
        for ga in ("x", "y", "width", "height"):
            if bg.get(ga) != ag.get(ga):
                print(f"GEOMETRY VIOLATION: {ga} changed for {cid}")
                structural_ok = False
    if bc.get("value") != ac.get("value"):
        value_changes += 1

status = "PASS" if structural_ok else "FAIL"
print(f"Structural integrity: {status}")
print(f"Value changes: {value_changes} cells")
print(f"Mutations reported: {len(result.mutations)}")
```

**Expected:**
```
Cells before: 139
Cells after:  139
Cell set: IDENTICAL
Structural integrity: PASS
Value changes: 8 cells
Mutations reported: 8
```

### K.7 Step 6 — Detailed Extraction Verification

Use this to inspect exactly what the extractor pulls from the CCPM DB:

```python
# Save as: test_extraction_detail.py
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from migration_intake.topology.haf_extractor import extract_haf_data

engine = create_engine("sqlite:///./migration_intake.db")

with Session(engine) as session:
    result = extract_haf_data(
        session,
        "26385e58-8954-4312-bf27-9d8414c79421",
        "OUTPOST_V1",
    )

print("=== Tokens ===")
for k, v in sorted(result.tokens.items()):
    print(f"  {k:25s} = {v}")

print()
print("=== Interface Groups ===")
for group_key in sorted(result.interfaces.keys()):
    entries = result.interfaces[group_key]
    print(f"  {group_key} ({len(entries)} entries):")
    for entry in entries:
        print(f"    {entry['app_name']:35s} corr={entry['correlation_id']}")

print()
print("=== Extraction Issues ===")
for issue in result.issues:
    print(f"  [{issue['type']}] {issue.get('token', '')} - {issue['message']}")
```

**What to verify:**
- `app_name` = `CCPM`
- `correlation_id` = `18678`
- 6 interface groups totaling 55 entries
- All 8 MISSING_TOKEN issues listed

### K.8 Step 7 — Verify via the Running UI

1. Open `http://localhost:8000/applications/` in your browser
2. Click on the **CCPM** application card
3. Navigate to the intake workspace
4. Review the **Interfaces** tab — confirm 55 interface records visible
5. Review the **Answers** tab — confirm 28 answers visible

**Note:** The haf pipeline is **not yet wired into the UI routes**. The service layer (`haf_service.py`) is ready but the web route has not been modified to add a "HAF Generate" button. Currently:
- The existing topology route (`/applications/{app_id}/intakes/{intake_id}/topology`) uses the governed `TopologyGenerationService` and `PersistedLabelRenderer`
- That existing flow requires a FROZEN intake with an official snapshot
- The CCPM intake is currently in DRAFT state
- To fully test from the UI, the next developer task is to add a POST endpoint that calls `generate_haf_topology()` and returns the filled diagram for download

### K.9 Quick Verification Checklist

Use this checklist to verify the pipeline end-to-end:

- [ ] `python -m pytest tests/unit/topology/ -v` reports 397 passed, 0 failed
- [ ] Pipeline runs against local SQLite CCPM DB without errors
- [ ] Output diagram saved to `docs/output/haf-pipeline/ccpm_filled_topology.drawio`
- [ ] Output opens correctly in draw.io desktop or app.diagrams.net
- [ ] Interface regions show real CCPM counterpart names (ORACLE SCM, DITREX, DPG-Sales, etc.)
- [ ] Unresolved tokens (NEEDS-OUTPOST-ID, NEEDS-CIDR, etc.) remain visible as placeholders
- [ ] Legend cells unchanged from input template
- [ ] Cell count identical between input and output (139 cells)
- [ ] No geometry, style, or edge changes between input and output
- [ ] Gap report lists all 8 missing infrastructure tokens
- [ ] Running app at `http://localhost:8000/applications/` shows CCPM with 55 interfaces
- [ ] Structural safety script reports `PASS` with exactly 8 value changes

### K.10 Known Gaps and Remediation Path

| # | Gap | Root Cause | Remediation |
|---|---|---|---|
| 1 | 8 infrastructure tokens unresolved (CIDR, account ID, outpost ID, etc.) | CCPM catalog does not have VPC_CIDR, SUBNET_CIDR, OUTPOST_ID, AWS_ACCOUNT_ID, AWS_AZ, APP_SG_NAME, DB_SG_NAME, SUBNET_NAME question codes | Add these question codes to the catalog, or add a separate token-entry form for infrastructure data |
| 2 | Midrange location maps to UNKNOWN | `guide_policy.LOCATION_ALIASES` does not include MIDRANGE | Add `"MIDRANGE": "INTERNAL"` to LOCATION_ALIASES (requires architectural decision) |
| 3 | Single page output only | Multi-page duplication deferred to Phase 2 | Implement NonProd/Prod page duplication |
| 4 | Not wired into UI routes | Block 8 created `haf_service.py` but web routes not modified | Add POST endpoint to topology routes that calls `generate_haf_topology()` with uploaded template |
| 5 | Intake state not validated | Pipeline runs on any intake state | Add state gate if business rules require FROZEN intake |
| 6 | `interface_epoch` column missing in local SQLite | Local DB predates migration 0022 | Run `alembic upgrade head` or recreate DB; extractor uses `text()` query to avoid this |
| 7 | 8 interfaces have empty location/direction | Source data quality | These go into UNKNOWN:UNKNOWN group; need upstream data cleanup |
