# Anil Handoff - Topology Generation

**Date:** 2026-09-16  
**Repository root:** `apm0014313-attcc-architect`  
**Feature:** Database-backed Draw.io topology generation  
**Status:** RCA confirmed; diagram binding and run-status follow-up remain pending.

## 1. Purpose

This document is the continuation handoff for topology generation. It records the verified implementation state, the exact RCA for the CCPM diagram not being updated, the input and output artifact paths, the production-to-POC comparison, completed work, known defects, and the ordered next steps.

The RCA below is based on:

- Production Python code currently in this repository.
- The uploaded Draw.io XML input.
- The generated Draw.io XML output.
- The generated HTML gap report.
- A direct execution of the production filler against the exact uploaded input.
- The reference POC code in the sibling workspace.

Existing Markdown documents were not used as the source of truth for the RCA.

## 2. Exact Sample Artifacts

All paths below are relative to this repository root.

### Input

```text
docs/Input/AWS_Outpost_Topology_CCPM_18678-v1.6.drawio
```

This is the base diagram uploaded for the CCPM application with correlation `18678`.

### Generated output

```text
docs/output/topology_APP_20260916_180416.drawio
```

### Gap report

```text
docs/output/gap_report_APP_20260916_180416.html
```

### Application and intake used by the live run

```text
application_id: 8974f49b-843e-47d8-9c7f-1a24e3cb90f5
intake_id:     317a1d8b-2f82-425c-bb6b-824091eb1e2f
run_id:        582fae68-3899-45a5-be5b-ff5ed4248c83
```

The generated report records the base filename and the run ID above.

## 3. Executive Finding

The generated diagram was not visually updated because the production slot-binding configuration matched **zero cells** in the uploaded CCPM diagram.

The production filler did execute successfully, but it had no bound cells to mutate:

```text
all configured slots matched: 0 cells
FillResult.success: True
FillResult.errors: []
FillResult.warnings: 6 unmatched-slot warnings
FillResult.mutations: 0
changed mxCell values: 0
```

The generated file is byte-different from the input because the XML was parsed and serialized again. The byte difference is not a topology update.

## 4. Exact RCA

### 4.1 Production generation call path

The live production path is:

```text
web route
  -> TopologyGenerationService.generate_topology()
  -> TopologyGenerationService._generate_diagram()
  -> extract_topology_data()
  -> fill_diagram()
  -> FilesystemStore artifact write
  -> gap report generation
```

Relevant production files:

```text
src/migration_intake/web/routes/topology.py
src/migration_intake/application/services/topology_generation.py
src/migration_intake/topology/adapter.py
src/migration_intake/topology/resolution.py
src/migration_intake/topology/normalize.py
src/migration_intake/topology/fill.py
src/migration_intake/topology/report.py
src/migration_intake/topology/config/slot_bindings.json
src/migration_intake/topology/config/fact_map.json
src/migration_intake/topology/config/naming.json
```

In `topology_generation.py`, `_generate_diagram()` extracts database values and invokes:

```python
topology_data = extract_topology_data(session, intake_id)
fill_result = fill_diagram(base_content, topology_data.tokens)
```

In `fill.py`, `_bind_slots()` finds cells by visible label text. The mutation loop only runs for cells returned by `_bind_slots()`:

```python
bindings = _bind_slots(tree, slot_bindings, warnings)

for slot, _ordinal, cell in bindings:
    cell.set("value", new_value)
```

Therefore, when `bindings` is empty, no cell value can change.

### 4.2 Active binding rules

The active configuration is:

```text
src/migration_intake/topology/config/slot_bindings.json
```

It searches for these visible labels:

| Slot | Matcher | Expected cells |
|---|---|---:|
| `app_name` | Contains `Application Name` | 1 |
| `app_acronym` | Contains `App Acronym` | 1 |
| `correlation_id` | Contains `Correlation ID` | 1 |
| `environment_region` | Contains both `Environment` and `Region` in one cell | 1 |
| `network_cidrs` | Contains both `VPC CIDR` and `Subnet CIDR` in one cell | 1 |
| `database_info` | Contains both `Database Engine` and `DB Version` in one cell | 1 |

All six bindings currently have `required: false`. The filler therefore records a warning and continues when a slot has zero matches.

### 4.3 Actual match result against the uploaded CCPM XML

The exact input was inspected using the same visible-label semantics as production:

```text
Input: docs/Input/AWS_Outpost_Topology_CCPM_18678-v1.6.drawio

app_name:           0
app_acronym:        0
correlation_id:     0
environment_region: 0
network_cidrs:      0
database_info:      0
```

None of the six configured phrases occurs in the CCPM template. The CCPM template uses a different AWS Outposts vocabulary, including labels related to accounts, VPCs, subnets, security groups, EC2, and ENI resources.

This is the primary root cause.

### 4.4 Direct production filler reproduction

From the repository root, set the source path and run the following diagnostic. It does not modify any file:

```powershell
$env:PYTHONPATH=(Get-Location).Path + '\src'
@'
import json
import xml.etree.ElementTree as ET
from pathlib import Path
from migration_intake.topology.fill import fill_diagram, visible_label

base_path = Path('docs/Input/AWS_Outpost_Topology_CCPM_18678-v1.6.drawio')
config_path = Path('src/migration_intake/topology/config/slot_bindings.json')
base_bytes = base_path.read_bytes()
config = json.loads(config_path.read_text(encoding='utf-8'))

root = ET.fromstring(base_bytes)
cells = list(root.iter('mxCell'))

def matches(label, find):
    text = visible_label(label).casefold()
    if 'label_contains' in find:
        return find['label_contains'].casefold() in text
    if 'label_contains_all' in find:
        return all(term.casefold() in text for term in find['label_contains_all'])
    raise ValueError(find)

for slot in config['slots']:
    count = sum(matches(cell.get('value', ''), slot['find']) for cell in cells)
    print(f"{slot['slot_name']}: {count}")

result = fill_diagram(base_bytes, {
    'app_name': 'CCPM',
    'app_acronym': 'X',
    'correlation_id': '18678',
    'environment': 'PROD',
    'region': 'us-east-1',
    'vpc_cidr': '10.0.0.0/16',
    'subnet_cidr': '10.0.1.0/24',
    'db_engine': 'Oracle',
    'db_version': '19c',
})

print('success:', result.success)
print('errors:', result.errors)
print('warnings:', result.warnings)
print('mutations:', len(result.mutations))
print('byte_identical:', result.filled_xml == base_bytes)
'@ | python -
```

Expected result:

```text
app_name: 0
app_acronym: 0
correlation_id: 0
environment_region: 0
network_cidrs: 0
database_info: 0
success: True
errors: []
mutations: 0
byte_identical: False
```

`byte_identical: False` is expected because `fill.py` serializes the XML again. It does not mean a cell was updated.

### 4.5 Input versus output XML comparison

The exact comparison found:

- Both files are valid uncompressed Draw.io XML.
- Both have one diagram page.
- Both have 128 `mxCell` elements.
- No cells were added.
- No cells were removed.
- No `mxCell value` changed.
- The generated file still contains all 10 `UNRESOLVED` labels.

The correct verification signal for this feature is changed `mxCell` values, not file byte size or hash alone.

### 4.6 Data gaps reported by the run

The report contains seven medium-severity missing-data issues:

- Application acronym.
- Database engine.
- Database engine version.
- Target environment.
- AWS region.
- VPC CIDR.
- Subnet CIDR.

The report also contains six low-severity unmatched-slot warnings, one for each configured slot.

Two values were available from the database and appear in the report:

```text
app_name       = CCPM
correlation_id = 18678
```

They were not written because their target cells were not found. This proves the primary issue is binding mismatch, not simply missing database data.

## 5. Production Versus POC Comparison

The reference POC is in the sibling workspace. From this repository root, its relative path is:

```text
..\..\aws_diag_v4_topolgy\aws_diag_v4
```

POC source files:

```text
..\..\aws_diag_v4_topolgy\aws_diag_v4\_data\spike\src\extract.py
..\..\aws_diag_v4_topolgy\aws_diag_v4\_data\spike\src\resolve.py
..\..\aws_diag_v4_topolgy\aws_diag_v4\_data\spike\src\fill.py
..\..\aws_diag_v4_topolgy\aws_diag_v4\_data\spike\src\report.py
..\..\aws_diag_v4_topolgy\aws_diag_v4\_data\spike\src\cli.py
```

### 5.1 Logic that is aligned with the POC

| POC responsibility | Production implementation | Status |
|---|---|---|
| Typed fact extraction shape | `topology/adapter.py` | Ported, database-backed source |
| Value normalization | `topology/normalize.py` | Ported POC-style normalization |
| Candidate selection and confidence handling | `topology/resolution.py` | Ported |
| Missing/conflict issue generation | `topology/resolution.py` plus `config/fact_map.json` | Ported with production catalog scope |
| Placeholder generation | `topology/resolution.py` | Ported concept |
| Visible-label matching | `topology/fill.py` | Ported |
| Ordinal binding protection | `topology/fill.py` | Ported |
| Structural postflight validation | `topology/fill.py` | Ported |
| Value-only cell mutation | `topology/fill.py` | Ported |
| HTML escaping in rendered labels | `topology/fill.py` | Ported |
| Self-contained gap report | `topology/report.py` | Production implementation based on POC report design |

### 5.2 Intentional production differences

These differences are expected because production uses the application database rather than POC files:

1. POC extraction reads UAQ, iTAP, Deep Dive, naming workbook, site YAML, and other files. Production reads canonical application/intake data, identifiers, answer revisions, and catalog questions through SQLAlchemy.
2. Production uses a `FillResult` object and returns the original base bytes if filling raises a `DiagramError`, allowing a gap report to be generated.
3. Production allows optional slots to match zero cells and reports warnings. The POC treats a zero-match slot as an error because the POC template is fixed.
4. Production stores generated diagram and report artifacts through `FilesystemStore` and records database artifact/run metadata.
5. Production has draft-preview support and official snapshot-backed runs; this is not the same as the standalone POC CLI flow.
6. Production slot bindings are JSON configuration in `topology/config/slot_bindings.json`; the POC reads slot configuration from its spike configuration.

### 5.3 Important production defect still present

The service computes a gap-aware status inside `_generate_report()`, but `generate_topology()` currently persists:

```python
status=GenerationStatus.READY_FOR_REVIEW.value
```

This means a run with zero mutations, missing tokens, or unmatched slots can be persisted as `READY_FOR_REVIEW` even though the HTML report says `GENERATED WITH GAPS`.

This should be corrected so the same computed status is used for both:

- `GenerationRun.status` in the database.
- `ReportData.run_status` in the HTML report.

A separate regression test is required for this behavior.

## 6. Completed Work

The following work is present in the current repository:

1. Database-backed topology extraction is implemented in `topology/adapter.py`.
2. Application identifiers are converted into topology facts.
3. Canonical answer revisions are mapped into known topology fact paths.
4. POC-style normalization exists in `topology/normalize.py`.
5. POC-style resolution, confidence selection, placeholders, and issue creation exist in `topology/resolution.py`.
6. Draw.io XML parsing validates the `mxfile` root, uncompressed format, diagram pages, and unique cell IDs.
7. Cell matching uses visible labels rather than cell IDs.
8. Structural attributes and geometry are protected by postflight checks.
9. Only bound cell `value` attributes are intended to be mutated.
10. Slot bindings are externalized into versioned JSON.
11. Gap reports include missing data and unmatched slot warnings.
12. Base and generated artifacts are stored and retrievable through the topology service.
13. Route-level scope protection exists for application, intake, and generation-run access.
14. Focused topology and topology-route tests have passed previously in this workspace.

The CCPM run itself proves the artifact storage path works: the generated Draw.io and HTML report were both created and downloadable. The failure is specifically in semantic binding and data completeness.

## 7. Pending Work, In Priority Order

### P0 - Correct the persisted run status

Update `src/migration_intake/application/services/topology_generation.py` so the service calculates status once after extraction/fill/report issue construction and uses it for the database update and report.

Required behavior:

- `GENERATED_WITH_GAPS` when there are missing tokens, fill warnings, fill errors, unresolved placeholders, or open report issues.
- `READY_FOR_REVIEW` only when generation has no unresolved gap conditions.

Add a focused service test that creates a successful run with an unmatched slot and asserts the persisted status is `GENERATED_WITH_GAPS`.

### P0 - Add CCPM-specific bindings

Do not guess mappings from label names alone. First inventory every relevant CCPM label and identify the authoritative production fact for each one.

Candidate diagram concepts include:

- AWS application account.
- Workload VPC.
- Private application subnet.
- Application security group.
- EC2 instance.
- ENI.
- Outpost/site/region labels.

For each candidate binding, document:

- Exact source `mxCell` label.
- Slot name.
- Token name.
- Catalog question code or identifier source.
- Whether the value is approved, missing, or unavailable.
- Expected match count.

Only add a binding when a real reviewed database source exists. Do not use a placeholder binding to make the diagram appear populated.

### P1 - Add or confirm catalog questions and intake values

The current catalog/data path does not supply all infrastructure values required by the CCPM template. Confirm whether the following are represented by approved catalog questions or application registers:

- VPC ID.
- Subnet ID.
- Security group name or ID.
- EC2 instance identifier/type/count.
- ENI identifier.
- Outpost identifier/site.
- AWS account identifier.
- Region.
- Environment.
- VPC and subnet CIDRs.
- Database engine and version.

If a value is not present in reviewed canonical data, keep it unresolved and report the gap. Do not infer it from the diagram or from absence.

### P1 - Add a semantic no-op guard

Generation should explicitly report a no-op when:

- The input contains unresolved placeholders or configured target markers, and
- `FillResult.mutations` is empty.

This should be visible in the run detail page and HTML report, not only as six low-severity warnings.

### P1 - Add direct artifact comparison tests

Add tests that assert:

1. A matching slot changes exactly one cell value.
2. A no-match diagram produces zero mutations and a gap status.
3. Unbound cell values remain unchanged.
4. Geometry, style, parent, edge, source, and target attributes remain unchanged.
5. XML serialization differences alone do not count as topology mutations.

### P2 - Improve binding diagnostics

The report should include, for each unmatched slot:

- The slot matcher.
- Expected match count.
- Actual match count.
- Candidate labels inspected or a concise label inventory.
- Suggested next action.

This will make template/configuration mismatch immediately visible to the architect.

### P2 - Validate XML library/security choice

`fill.py` uses the Python standard-library XML parser. Review whether the application's security policy requires a hardened XML parser for uploaded Draw.io files. If so, introduce the approved parser through the project dependency manager and retain the existing structural checks.

## 8. Ordered Continuation Procedure

1. Read this handoff and `AGENTS.md`.
2. Confirm the input and output paths in section 2.
3. Run the direct filler reproduction in section 4.4.
4. Inspect actual CCPM labels and create a reviewed binding table.
5. Verify the database/catalog source for each proposed token.
6. Fix persisted run status and add the regression test.
7. Add only approved CCPM bindings to `slot_bindings.json`.
8. Add or update synthetic fixtures and focused tests.
9. Populate missing canonical intake values using the approved questionnaire/evidence workflow.
10. Upload the CCPM base diagram again and generate a new run.
11. Compare base and generated XML by `mxCell value`, not file hash alone.
12. Review the new gap report.
13. Run focused tests, then the applicable broader suite.
14. Update this handoff or `STATE.md` with the new run ID, artifact paths, mutation count, and remaining gaps.

## 9. Verification Commands

### Compile check

```powershell
$env:PYTHONPATH=(Get-Location).Path + '\src'
python -m compileall -q src/migration_intake/topology src/migration_intake/application/services/topology_generation.py
```

### Focused topology tests

```powershell
$env:PYTHONPATH=(Get-Location).Path + '\src'
python -m pytest tests/unit/topology/ tests/integration/web/test_topology_routes.py -q
```

### Production diagnostics

```powershell
$env:PYTHONPATH=(Get-Location).Path + '\src'
python -m pytest tests/ -q --ignore=tests/integration/migrations --ignore=tests/browser
```

The broader suite may contain unrelated environment/database failures. Record those separately from topology failures.

### XML comparison checklist

For any new run, compare:

- `mxfile` root and page count.
- Number of `mxCell` elements.
- Cell IDs and ordering.
- `mxCell value` changes.
- Geometry and style attributes.
- Remaining `UNRESOLVED` labels.
- Report mutation count.
- Report gap count.
- Persisted generation status.

## 10. Definition of Done for CCPM Generation

A CCPM generation run is not complete merely because a Draw.io file downloads successfully. It is complete when:

- Every intended CCPM slot has an exact, reviewed label binding.
- Every populated token comes from approved canonical database data.
- Missing values remain explicit gaps rather than invented values.
- The generated XML contains the expected `mxCell value` changes.
- No unbound layout or structural attributes change.
- The run status matches the report status.
- The report lists remaining gaps and their owners/actions.
- Focused tests pass.
- The new run ID and artifact paths are recorded for review.

## 11. Current Bottom Line

The upload, database extraction, artifact storage, XML validation, and report generation paths are operational.

The CCPM diagram did not update because the configured bindings target labels that do not exist in the CCPM XML. The filler therefore performed zero mutations while still returning a successful XML fill result. The seven missing intake values are a separate data-completeness issue. The persisted run-status hardcoding is an additional defect that should be fixed before relying on the UI status for review decisions.
