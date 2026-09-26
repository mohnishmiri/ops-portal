# Template Loading — Quick Reference

## Two Paths to Load Diagrams

### Path 1: User-Uploaded Template (Card 1 → Card 2)

**When to use:** User has a custom `.drawio` file they want to generate from

**Flow:**
```
User selects file + variant
    ↓
POST /topology/upload-base
    ↓
Service validates XML, stores file, creates topo_base record
    ↓
User clicks "Generate topology" (Card 2)
    ↓
Service loads file from filesystem, uses stored variant, runs HAF pipeline
    ↓
Generated diagram + gap report
```

**Key Files:**
- Route: `src/migration_intake/web/routes/topology.py:229` (`upload_base_diagram`)
- Service: `src/migration_intake/application/services/topology_generation.py:116` (`upload_base_diagram`)
- Storage: `evidence/topology/base_diagrams/{artifact_id}`
- Database: `topo_base` table

**Variant Storage:** Stored in `topo_base.variant` at upload time; retrieved at generation time

---

### Path 2: Bundled Standard Template (Card 3)

**When to use:** You want to use a pre-packaged, tested template variant

**Flow:**
```
User selects variant (no file upload)
    ↓
POST /topology/generate-standard
    ↓
Service loads bundled template from disk
    ↓
Service extracts variant-specific tab
    ↓
Service creates synthetic topo_base record
    ↓
Service runs HAF pipeline
    ↓
Generated diagram + gap report
```

**Key Files:**
- Route: `src/migration_intake/web/routes/topology.py:366` (`generate_from_standard_template`)
- Service: `src/migration_intake/application/services/topology_generation.py:421` (`generate_from_standard_template`)
- Loader: `src/migration_intake/topology/template_loader.py:81` (`load_bundled_template`)
- Template: `src/migration_intake/topology/config/templates/outpost_v1.7.drawio`
- Storage: `evidence/topology/base_diagrams/{artifact_id}` (synthetic records)
- Database: `topo_base` table (synthetic records with `review_state="APPROVED"`)

**Variant Mapping:** Defined in `template_loader.py:73`
```python
_VARIANT_TAB_MAP = {
    "basic": "Without LBs",
    "tlgw": "tLGW Load Balancer",
    "f5": "F5 Load Balancer",
    "hadr": "HA/DR with Global Load Balancer",
}
```

---

## Adding a New Template

### Option A: User-Uploaded (No Code Changes)

1. User uploads `.drawio` file via Card 1
2. Done — no code changes needed

### Option B: New Bundled Variant (Code Changes Required)

**Step 1: Update bundled template file**
```
src/migration_intake/topology/config/templates/outpost_v1.7.drawio
```
- Add new `<diagram name="...">` tab
- Annotate cells with `haf-role` attributes

**Step 2: Update variant map**
```python
# src/migration_intake/topology/template_loader.py:73
_VARIANT_TAB_MAP = {
    "basic": "Without LBs",
    "tlgw": "tLGW Load Balancer",
    "f5": "F5 Load Balancer",
    "hadr": "HA/DR with Global Load Balancer",
    "new_variant": "New Tab Name",  # ← Add this
}
```

**Step 3: Create HAF profile**
```
src/migration_intake/topology/config/haf_profiles/outpost_v1_newvariant.json
```
- Define `protected_roles`
- Define `placeholder_bindings`
- Define interface regions and detail blocks

**Step 4: Update profile map**
```python
# src/migration_intake/application/services/topology_generation.py:108
self._variant_profile_map = {
    None: "OUTPOST_V1",
    "basic": "OUTPOST_V1_BASIC",
    "tlgw": "OUTPOST_V1_TLGW",
    "f5": "OUTPOST_V1_F5",
    "hadr": "OUTPOST_V1_HADR",
    "new_variant": "OUTPOST_V1_NEWVARIANT",  # ← Add this
}
```

**Step 5: Update UI**
```html
<!-- src/migration_intake/web/templates/topology/index.html -->
<select name="variant" id="standard_variant">
  <option value="basic">Without LBs</option>
  <option value="tlgw">tLGW Load Balancer</option>
  <option value="f5">F5 Load Balancer</option>
  <option value="hadr">HA/DR with Global Load Balancer</option>
  <option value="new_variant">New Variant Display Name</option>  <!-- ← Add this -->
</select>
```

**Step 6: Test**
```bash
python -m pytest tests/unit/topology/ -q
python scripts/playwright_card3_e2e.py
```

**Step 7: Deploy**
- Commit all changes
- Deploy application
- No database migration needed

---

## Variant Profile Mapping

| Variant | Tab Name | Profile | Protected Roles |
|---------|----------|---------|-----------------|
| `basic` | Without LBs | `OUTPOST_V1_BASIC` | 22 roles (includes AWS Tier 1, Tier 2, Internet, VPCE) |
| `tlgw` | tLGW Load Balancer | `OUTPOST_V1_TLGW` | 23 roles (+ tLGW-specific) |
| `f5` | F5 Load Balancer | `OUTPOST_V1_F5` | 23 roles (+ F5-specific) |
| `hadr` | HA/DR with Global Load Balancer | `OUTPOST_V1_HADR` | 25 roles (+ HA/DR-specific) |

---

## Database Schema (Simplified)

### topo_base (Uploaded or Synthetic Templates)

```sql
CREATE TABLE topo_base (
  id UUID PRIMARY KEY,
  intake_id UUID NOT NULL,
  filename TEXT NOT NULL,
  content_address TEXT NOT NULL,
  sha256_hex TEXT NOT NULL,
  variant TEXT,                    -- "basic", "tlgw", "f5", "hadr", or "default"
  review_state TEXT NOT NULL,      -- "DRAFT" (user-uploaded) or "APPROVED" (bundled)
  uploaded_at TIMESTAMP NOT NULL,
  ...
);
```

### gen_runs (Generation Records)

```sql
CREATE TABLE gen_runs (
  id UUID PRIMARY KEY,
  base_artifact_id UUID NOT NULL REFERENCES topo_base(id),
  status TEXT NOT NULL,            -- "RUNNING", "READY_FOR_REVIEW", "FAILED"
  created_at TIMESTAMP NOT NULL,
  completed_at TIMESTAMP,
  ...
);
```

---

## Common Operations

### List all uploaded templates for an intake
```python
from migration_intake.persistence.repositories.topology import TopologyRepository

repo = TopologyRepository(session)
artifacts = repo.get_base_artifacts_for_intake(intake_id)
for artifact in artifacts:
    print(f"{artifact['filename']} (variant={artifact['variant']}, state={artifact['review_state']})")
```

### Get the variant used for a generation run
```python
run = topology_repo.get_generation_run(run_id)
base = topology_repo.get_base_artifact(run['base_artifact_id'])
variant = base.get('variant', 'default')
print(f"Run {run_id} used variant: {variant}")
```

### Load a bundled template programmatically
```python
from migration_intake.topology.template_loader import load_bundled_template

template_bytes = load_bundled_template("basic")
# template_bytes is a single-diagram mxfile with the "Without LBs" tab
```

### Extract a specific tab from any multi-tab drawio file
```python
from migration_intake.topology.template_loader import extract_tab

with open("my_template.drawio", "rb") as f:
    template_bytes = f.read()

single_tab = extract_tab(template_bytes, tab_name="My Tab Name")
# single_tab is a single-diagram mxfile
```

---

## Troubleshooting

| Issue | Cause | Fix |
|-------|-------|-----|
| "Tab not found" when generating | Variant tab name doesn't match `outpost_v1.7.drawio` | Check `_VARIANT_TAB_MAP` and diagram tab names |
| Generated diagram missing sections | HAF profile missing roles in `protected_roles` | Update profile JSON with all required roles |
| User variant not applied to Card 2 generation | `topo_base.variant` not set correctly | Check upload form and service layer |
| "Invalid draw.io diagram" error | File is compressed or not valid XML | Ensure file is uncompressed `.drawio` format |
| Profile not found error | Variant not in `_variant_profile_map` | Add variant to profile map in service |

---

## Key Architectural Principles

1. **Separation of Concerns:**
   - Routes handle HTTP only
   - Services handle business logic
   - Repositories handle database access
   - Template loader handles file I/O

2. **Immutability:**
   - Bundled templates are code; update requires redeployment
   - User uploads are stored as-is; variant selection is immutable at upload time

3. **Auditability:**
   - All uploads tracked with `uploaded_by_id` and `uploaded_at`
   - All generations tracked with `requested_by_id` and `requested_at`
   - All artifacts linked to their source template via `base_artifact_id`

4. **Consistency:**
   - Both paths use the same HAF pipeline
   - Both paths use the same profile selection logic
   - Both paths produce identical output quality

---

## Related Documentation

- **Full Architecture:** `docs/TEMPLATE_LOADING_ARCHITECTURE.md`
- **Investigation Report:** `docs/investigation-report-20260926.md`
- **Handoff Document:** `HANDOFF_20250925.md`
- **HAF Pipeline:** `src/migration_intake/topology/haf_pipeline.py`
- **Topology Service:** `src/migration_intake/application/services/topology_generation.py`
