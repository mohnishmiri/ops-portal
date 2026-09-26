# Template Loading Architecture — Comprehensive Review

**Date:** September 26, 2026  
**Scope:** Complete trace of both template-ingestion paths in the application  
**Audience:** Architects, developers, and operators

---

## Overview

The application supports **two distinct template-loading paths**:

1. **User-Uploaded Template Path** — for custom diagrams supplied by users
2. **Bundled Standard Template Path** — for pre-packaged multi-variant master templates

Each path has different entry points, storage mechanisms, database persistence, and generation pipelines. This document traces both end-to-end.

---

## Path 1: User-Uploaded Template (Card 1 → Card 2)

### 1.1 Entry Point: Upload Form

**File:** `src/migration_intake/web/templates/topology/index.html` (Card 1)

**UI Form:**
```html
<form method="POST" action="/applications/{app_id}/intakes/{intake_id}/topology/upload-base" enctype="multipart/form-data">
  <input type="file" name="base_diagram" accept=".drawio">
  <select name="variant">
    <option value="default">Default (legacy)</option>
    <option value="basic">Without LBs</option>
    <option value="tlgw">tLGW Load Balancer</option>
    <option value="f5">F5 Load Balancer</option>
    <option value="hadr">HA/DR with Global Load Balancer</option>
  </select>
  <button type="submit">Upload diagram</button>
</form>
```

**Form fields:**
- `base_diagram` — file upload (required, `.drawio` format)
- `variant` — template variant selector (optional, defaults to `"default"`)
- `_csrf_token` — CSRF protection token
- `environment` — optional metadata
- `site` — optional metadata

### 1.2 HTTP Route Handler

**File:** `src/migration_intake/web/routes/topology.py` (lines 229–288)

**Route Definition:**
```python
@router.post(
    "/applications/{app_id}/intakes/{intake_id}/topology/upload-base",
    response_class=HTMLResponse,
)
async def upload_base_diagram(
    request: Request,
    app_id: str,
    intake_id: str,
    session_factory: Annotated[object, Depends(get_session_factory)],
    topology_service: Annotated[TopologyGenerationService, Depends(get_topology_service)],
    actor: Annotated[ActorContext, Depends(get_actor_context)],
    csrf_token: Annotated[str | None, Form(alias="_csrf_token")] = None,
    base_diagram: UploadFile | None = None,
    environment: Annotated[str | None, Form()] = None,
    site: Annotated[str | None, Form()] = None,
    variant: Annotated[str | None, Form()] = "default",
) -> Response:
```

**Responsibilities:**
1. Validate CSRF token (line 251)
2. Check file is not empty (line 263)
3. Read file bytes with size limit (line 259)
4. Delegate to service layer (line 267)
5. Redirect back to topology page on success (line 285)

**Error Handling:**
- 403: CSRF token missing or invalid
- 400: No file uploaded, empty file, or invalid diagram
- 500: Unexpected service error

### 1.3 Service Layer: Upload and Persist

**File:** `src/migration_intake/application/services/topology_generation.py` (lines 116–193)

**Method:** `TopologyGenerationService.upload_base_diagram()`

**Workflow:**

```
1. Validate XML structure
   ↓
2. Compute SHA-256 hash of file bytes
   ↓
3. Open unit-of-work (database transaction)
   ↓
4. Verify intake exists
   ↓
5. Generate artifact UUID
   ↓
6. Store file bytes to filesystem (content-addressed)
   ↓
7. Create topo_base database record
   ↓
8. Commit transaction
   ↓
9. Return artifact dict
```

**Key Code Points:**

**Validation (line 144):**
```python
validation_errors = self._validate_drawio_xml(file_bytes)
if validation_errors:
    raise InvalidBaseDiagramError(...)
```

**Filesystem Storage (lines 168–171):**
```python
artifact_id = str(uuid.uuid4())
content_address = self._store_content(
    file_bytes, artifact_id, "base_diagrams"
)
```

**Database Persistence (lines 174–189):**
```python
artifact = topology_repo.create_base_artifact(
    artifact_id=artifact_id,
    application_id=intake["application_id"],
    intake_id=intake_id,
    filename=filename,
    mime_type="application/vnd.jgraph.mxfile+xml",
    size_bytes=len(file_bytes),
    sha256_hex=sha256_hex,
    content_address=content_address,
    uploaded_by_id=actor.actor_id,
    uploaded_at=now,
    created_at=now,
    environment=environment,
    site=site,
    variant=variant,  # ← User's variant selection stored here
)
```

### 1.4 Database Schema: topo_base Table

**File:** `src/migration_intake/persistence/models_topology.py` (lines 37–58)

**Table:** `topo_base`

**Key Columns:**
| Column | Type | Nullable | Purpose |
|--------|------|----------|---------|
| `id` | UUID | NO | Primary key (artifact_id) |
| `application_id` | UUID | NO | FK to applications |
| `intake_id` | UUID | NO | FK to intakes |
| `filename` | String(255) | NO | Original filename |
| `mime_type` | String(100) | NO | `application/vnd.jgraph.mxfile+xml` |
| `size_bytes` | Integer | NO | File size |
| `sha256_hex` | Sha256Hex | NO | Content hash |
| `content_address` | String(255) | NO | Filesystem path (content-addressed) |
| `environment` | String(32) | YES | Optional metadata |
| `site` | String(64) | YES | Optional metadata |
| **`variant`** | String(32) | YES | **User's variant selection** |
| `review_state` | String(32) | NO | Default: `"DRAFT"` |
| `uploaded_by_id` | UUID | NO | FK to actors |
| `uploaded_at` | PortableUTC | NO | Upload timestamp |
| `created_at` | PortableUTC | NO | Record creation timestamp |
| `row_version` | Integer | NO | Optimistic lock |
| `authority` | String(32) | NO | Default: `"LEGACY_UNPINNED"` |
| `lifecycle` | String(32) | NO | Default: `"HISTORICAL"` |
| `profile_id` | String(128) | YES | Optional profile override |

### 1.5 Filesystem Storage

**Location:** `evidence/topology/base_diagrams/{artifact_id}`

**Content:** Raw `.drawio` XML bytes (uncompressed)

**Addressing:** Content-addressed by UUID (deterministic lookup)

**Retrieval:** Via `FilesystemStore._load_content(content_address)`

### 1.6 Generation Flow: Card 2 (Generate Test Topology)

**File:** `src/migration_intake/web/routes/topology.py` (lines 296–358)

**Route:**
```python
@router.post(
    "/applications/{app_id}/intakes/{intake_id}/topology/generate",
    response_class=HTMLResponse,
)
async def generate_topology(
    request: Request,
    app_id: str,
    intake_id: str,
    session_factory: Annotated[object, Depends(get_session_factory)],
    topology_service: Annotated[TopologyGenerationService, Depends(get_topology_service)],
    actor: Annotated[ActorContext, Depends(get_actor_context)],
    csrf_token: Annotated[str | None, Form(alias="_csrf_token")] = None,
    base_artifact_id: Annotated[str | None, Form()] = None,
) -> Response:
```

**Form Input:**
- `base_artifact_id` — UUID of the uploaded template (from Card 1)
- `_csrf_token` — CSRF protection

**Workflow:**

```
1. Validate CSRF token
   ↓
2. Verify base_artifact_id is provided
   ↓
3. Call topology_service.generate_topology(intake_id, base_artifact_id, actor)
   ↓
4. Service loads base artifact from database
   ↓
5. Service reads file bytes from filesystem
   ↓
6. Service extracts variant from topo_base record
   ↓
7. Service selects profile based on variant
   ↓
8. Service runs HAF pipeline with user's template
   ↓
9. Service stores generated diagram and gap report
   ↓
10. Redirect to run detail page
```

**Key Point (lines 303–317 in topology_generation.py):**
```python
# Load base diagram
base = topology_repo.get_base_artifact(base_artifact_id)
if base is None:
    raise InvalidBaseDiagramError(...)

# If no variant was passed explicitly, use the variant that
# was stored on the base artifact at upload time.
if variant is None:
    stored_variant = base.get("variant")
    if stored_variant and stored_variant != "default":
        variant = stored_variant
```

The variant stored during upload is retrieved and used to select the correct HAF profile.

---

## Path 2: Bundled Standard Template (Card 3)

### 2.1 Entry Point: Standard Template Form

**File:** `src/migration_intake/web/templates/topology/index.html` (Card 3)

**UI Form:**
```html
<form method="POST" action="/applications/{app_id}/intakes/{intake_id}/topology/generate-standard" enctype="multipart/form-data">
  <select name="variant" id="standard_variant">
    <option value="basic">Without LBs</option>
    <option value="tlgw">tLGW Load Balancer</option>
    <option value="f5">F5 Load Balancer</option>
    <option value="hadr">HA/DR with Global Load Balancer</option>
  </select>
  <button type="submit">Generate from template</button>
</form>
```

**Form fields:**
- `variant` — template variant selector (required, no "default" option)
- `_csrf_token` — CSRF protection token

**Key Difference:** No file upload; variant selection only.

### 2.2 HTTP Route Handler

**File:** `src/migration_intake/web/routes/topology.py` (lines 366–421)

**Route Definition:**
```python
@router.post(
    "/applications/{app_id}/intakes/{intake_id}/topology/generate-standard",
    response_class=HTMLResponse,
)
async def generate_from_standard_template(
    request: Request,
    app_id: str,
    intake_id: str,
    session_factory: Annotated[object, Depends(get_session_factory)],
    topology_service: Annotated[TopologyGenerationService, Depends(get_topology_service)],
    actor: Annotated[ActorContext, Depends(get_actor_context)],
    csrf_token: Annotated[str | None, Form(alias="_csrf_token")] = None,
    variant: Annotated[str | None, Form()] = None,
) -> Response:
```

**Responsibilities:**
1. Validate CSRF token
2. Verify variant is provided
3. Delegate to service layer
4. Redirect to run detail page on success

**Error Handling:**
- 403: CSRF token missing or invalid
- 400: No variant selected
- 500: Unexpected service error

### 2.3 Service Layer: Load and Generate

**File:** `src/migration_intake/application/services/topology_generation.py` (lines 421–583)

**Method:** `TopologyGenerationService.generate_from_standard_template()`

**Workflow:**

```
1. Load bundled template from disk
   ↓
2. Extract variant-specific tab
   ↓
3. Open unit-of-work (database transaction)
   ↓
4. Verify intake exists
   ↓
5. Create synthetic topo_base record
   ↓
6. Create generation run record
   ↓
7. Run HAF pipeline with bundled template
   ↓
8. Store generated diagram and gap report
   ↓
9. Update run status to READY_FOR_REVIEW
   ↓
10. Commit transaction
   ↓
11. Return run dict
```

**Key Code Points:**

**Load Bundled Template (line 441):**
```python
template_bytes = load_bundled_template(variant)
```

**Create Synthetic Base Artifact (lines 456–477):**
```python
base_id = str(uuid.uuid4())
template_sha256 = hashlib.sha256(template_bytes).hexdigest()
base_content_address = self._store_content(
    template_bytes, base_id, "base_diagrams"
)
topology_repo.create_base_artifact(
    artifact_id=base_id,
    application_id=intake["application_id"],
    intake_id=intake_id,
    filename=f"bundled_outpost_v1.7_{variant}.drawio",
    mime_type="application/vnd.jgraph.mxfile+xml",
    size_bytes=len(template_bytes),
    sha256_hex=template_sha256,
    content_address=base_content_address,
    uploaded_by_id=actor.actor_id,
    uploaded_at=now,
    created_at=now,
    variant=variant,
    review_state="APPROVED",
)
```

**Create Generation Run (lines 480–493):**
```python
run = topology_repo.create_generation_run(
    run_id=run_id,
    application_id=intake["application_id"],
    intake_id=intake_id,
    snapshot_id=snapshot["id"] if snapshot else None,
    snapshot_sha256=snapshot["sha256_hex"] if snapshot else None,
    catalog_sha256=snapshot["catalog_sha256"] if snapshot else None,
    base_artifact_id=base_id,  # ← Synthetic UUID
    base_sha256=template_sha256,
    requested_by_id=actor.actor_id,
    requested_at=now,
    created_at=now,
    status=GenerationStatus.RUNNING.value,
)
```

### 2.4 Template Loader: Bundled Template Extraction

**File:** `src/migration_intake/topology/template_loader.py` (lines 81–102)

**Function:** `load_bundled_template(variant: str) -> bytes`

**Source Template:**
```
src/migration_intake/topology/config/templates/outpost_v1.7.drawio
```

**Variant Mapping (lines 73–78):**
```python
_VARIANT_TAB_MAP: dict[str, str] = {
    "basic": "Without LBs",
    "tlgw": "tLGW Load Balancer",
    "f5": "F5 Load Balancer",
    "hadr": "HA/DR with Global Load Balancer",
}
```

**Extraction Logic (lines 81–102):**
```python
def load_bundled_template(variant: str) -> bytes:
    """Load an annotated tab from the bundled multi-tab master template.
    
    Args:
        variant: Variant key ("basic", "tlgw", "f5", "hadr").
    
    Returns:
        Single-diagram mxfile XML bytes with haf-role annotations.
    """
    tab_name = _VARIANT_TAB_MAP.get(variant)
    if tab_name is None:
        raise HafProfileError(...)
    return extract_tab(_BUNDLED_TEMPLATE.read_bytes(), tab_name=tab_name)
```

**Tab Extraction (lines 26–65):**
```python
def extract_tab(
    template_bytes: bytes,
    *,
    tab_name: str | None = None,
    tab_index: int | None = None,
) -> bytes:
    """Extract a single diagram tab from a multi-tab .drawio file."""
    root = ET.fromstring(template_bytes)
    diagrams = root.findall("diagram")
    
    # Find matching tab by name
    matches = [d for d in diagrams if d.get("name") == tab_name]
    if not matches:
        raise ValueError(f"Tab '{tab_name}' not found")
    selected = matches[0]
    
    # Create new mxfile with single diagram
    new_root = ET.Element("mxfile", root.attrib)
    new_root.append(selected)
    return ET.tostring(new_root, encoding="unicode", xml_declaration=False).encode("utf-8")
```

### 2.5 Database Schema: gen_runs Table

**File:** `src/migration_intake/persistence/models_topology.py` (lines 78–127)

**Table:** `gen_runs`

**Key Columns for Template Tracking:**
| Column | Type | Nullable | Purpose |
|--------|------|----------|---------|
| `id` | UUID | NO | Generation run ID |
| `application_id` | UUID | NO | FK to applications |
| `intake_id` | UUID | NO | FK to intakes |
| **`base_artifact_id`** | UUID | NO | **FK to topo_base** |
| `base_sha256` | Sha256Hex | NO | Template content hash |
| `status` | String(32) | NO | `RUNNING`, `READY_FOR_REVIEW`, `FAILED` |
| `error_message` | Text | YES | Error details if FAILED |
| `completed_at` | PortableUTC | YES | Completion timestamp |
| `created_at` | PortableUTC | NO | Record creation timestamp |

**Foreign Key Constraint (line 120):**
```python
ForeignKeyConstraint(["base_artifact_id"], ["topo_base.id"], name="fk_gnrn_bas")
```

Every generation run references a `topo_base` record, whether user-uploaded or synthetic.

---

## Comparative Analysis

### Similarities

| Aspect | Path 1 (User Upload) | Path 2 (Bundled) |
|--------|----------------------|------------------|
| **Storage** | Both store template bytes in `evidence/topology/base_diagrams/` |
| **Database** | Both create `topo_base` records |
| **Generation** | Both run the same HAF pipeline |
| **Variant Selection** | Both support 4 variants (basic, tlgw, f5, hadr) |
| **Output** | Both produce diagram + gap report artifacts |
| **Traceability** | Both link to `gen_runs` via `base_artifact_id` FK |

### Differences

| Aspect | Path 1 (User Upload) | Path 2 (Bundled) |
|--------|----------------------|------------------|
| **Entry Point** | File upload form (Card 1) | Variant selector only (Card 3) |
| **Template Source** | User-supplied file | Shipped with application |
| **Template Location** | Uploaded to database | Embedded in codebase |
| **Variant Timing** | Selected at upload time | Selected at generation time |
| **topo_base.review_state** | `DRAFT` | `APPROVED` |
| **topo_base.filename** | User's original filename | `bundled_outpost_v1.7_{variant}.drawio` |
| **Reusability** | Single upload, multiple generations | Stateless, no upload needed |
| **Update Mechanism** | Re-upload to replace | Redeploy application |

---

## Profile Selection Logic

Both paths use the same profile selection mechanism:

**File:** `src/migration_intake/application/services/topology_generation.py` (lines 107–114)

```python
self._variant_profile_map: dict[str | None, str] = {
    None: "OUTPOST_V1",
    "basic": "OUTPOST_V1_BASIC",
    "tlgw": "OUTPOST_V1_TLGW",
    "f5": "OUTPOST_V1_F5",
    "hadr": "OUTPOST_V1_HADR",
}
```

**Profile Selection (lines 797–799):**
```python
profile_id = self._variant_profile_map.get(
    variant, self._default_haf_profile_id
)
```

Each variant maps to a HAF profile that defines:
- Protected roles (sections that must not be mutated)
- Placeholder bindings (token replacement patterns)
- Interface region definitions
- Detail block specifications

---

## Adding or Updating Templates

### To Add a New User-Uploaded Template

1. User navigates to Card 1
2. Selects a `.drawio` file from their system
3. Optionally selects a variant (defaults to `"default"`)
4. Clicks "Upload diagram"
5. File is validated, stored, and persisted to `topo_base`
6. User then uses Card 2 to generate from the uploaded template

**No code changes required.**

### To Add a New Bundled Template Variant

1. **Update the bundled template file:**
   - Edit `src/migration_intake/topology/config/templates/outpost_v1.7.drawio`
   - Add a new `<diagram name="...">` tab with the new variant
   - Annotate cells with `haf-role` attributes

2. **Update the variant map:**
   - Edit `src/migration_intake/topology/template_loader.py` (lines 73–78)
   - Add entry: `"new_variant": "Tab Name in Diagram"`

3. **Create a new HAF profile:**
   - Create `src/migration_intake/topology/config/haf_profiles/outpost_v1_newvariant.json`
   - Define `protected_roles`, `placeholder_bindings`, etc.

4. **Update the profile map:**
   - Edit `src/migration_intake/application/services/topology_generation.py` (lines 108–114)
   - Add entry: `"new_variant": "OUTPOST_V1_NEWVARIANT"`

5. **Update the UI:**
   - Edit `src/migration_intake/web/templates/topology/index.html`
   - Add `<option value="new_variant">Display Name</option>` to Card 3 dropdown

6. **Test:**
   - Run `python -m pytest tests/unit/topology/ -q`
   - Test Card 3 generation with the new variant

### To Replace an Existing Bundled Template

1. Edit `src/migration_intake/topology/config/templates/outpost_v1.7.drawio`
2. Replace the relevant tab's `<diagram>` element
3. Re-annotate cells with `haf-role` attributes
4. Optionally update the corresponding HAF profile
5. Redeploy the application
6. No database migration needed (templates are not persisted in the DB)

---

## Data Flow Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                    USER INTERFACE (Jinja2)                      │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  Card 1: Upload Base Diagram      Card 3: Generate from Template
│  ┌──────────────────────┐         ┌──────────────────────────┐  │
│  │ File: [Choose File]  │         │ Variant: [Dropdown]      │  │
│  │ Variant: [Dropdown]  │         │ [Generate from template] │  │
│  │ [Upload diagram]     │         └──────────────────────────┘  │
│  └──────────────────────┘                                        │
│         │                                  │                     │
└─────────┼──────────────────────────────────┼─────────────────────┘
          │                                  │
          ▼                                  ▼
┌─────────────────────────────────────────────────────────────────┐
│                    HTTP ROUTES (FastAPI)                        │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  POST /topology/upload-base              POST /topology/generate-standard
│  ├─ CSRF validation                      ├─ CSRF validation
│  ├─ File size check                      ├─ Variant validation
│  └─ Delegate to service                  └─ Delegate to service
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
          │                                  │
          ▼                                  ▼
┌─────────────────────────────────────────────────────────────────┐
│              APPLICATION SERVICE LAYER                          │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  upload_base_diagram()                   generate_from_standard_template()
│  ├─ Validate XML                         ├─ Load bundled template
│  ├─ Compute SHA-256                      ├─ Extract variant tab
│  ├─ Store file bytes                     ├─ Create synthetic topo_base
│  ├─ Create topo_base record              ├─ Create gen_runs record
│  └─ Return artifact dict                 ├─ Run HAF pipeline
│                                          ├─ Store artifacts
│                                          └─ Return run dict
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
          │                                  │
          ▼                                  ▼
┌─────────────────────────────────────────────────────────────────┐
│                  FILESYSTEM STORAGE                             │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  evidence/topology/base_diagrams/{artifact_id}                 │
│  ├─ User-uploaded .drawio files                                │
│  └─ Bundled template extracts                                  │
│                                                                 │
│  evidence/topology/generated/{artifact_id}                     │
│  ├─ Generated diagrams                                         │
│  └─ Gap reports                                                │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
          │                                  │
          ▼                                  ▼
┌─────────────────────────────────────────────────────────────────┐
│                    DATABASE (SQLite)                            │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  topo_base                               gen_runs
│  ├─ id (PK)                              ├─ id (PK)
│  ├─ filename                             ├─ base_artifact_id (FK)
│  ├─ content_address                      ├─ status
│  ├─ sha256_hex                           ├─ created_at
│  ├─ variant                              └─ completed_at
│  ├─ review_state                         
│  └─ uploaded_at                          gen_artifacts
│                                          ├─ generation_run_id (FK)
│  intakes                                 ├─ artifact_type
│  ├─ id (PK)                              ├─ filename
│  └─ application_id (FK)                  └─ content_address
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

---

## Security Considerations

### File Upload (Path 1)

1. **File Size Limit:** Enforced by `max_topology_base_bytes` setting
2. **XML Validation:** Must be valid, uncompressed draw.io XML
3. **Content Hashing:** SHA-256 computed for integrity verification
4. **CSRF Protection:** Token required on upload form
5. **Access Control:** Requires `TOPOLOGY_BASE_UPLOAD` capability
6. **Audit Trail:** `uploaded_by_id` and `uploaded_at` recorded

### Bundled Template (Path 2)

1. **Source Control:** Template is part of the codebase, reviewed before deployment
2. **Immutability:** Cannot be modified without code changes and redeployment
3. **Variant Validation:** Only 4 predefined variants allowed
4. **CSRF Protection:** Token required on generation form
5. **Access Control:** Requires `TOPOLOGY_GENERATE` capability
6. **Audit Trail:** `requested_by_id` and `requested_at` recorded in `gen_runs`

---

## Operational Guidance

### Deploying a New Bundled Template

1. **Prepare the template:**
   - Create or update `outpost_v1.7.drawio` with new tabs
   - Annotate all cells with `haf-role` attributes
   - Test locally with the HAF pipeline

2. **Update configuration:**
   - Add variant to `_VARIANT_TAB_MAP` in `template_loader.py`
   - Create corresponding HAF profile JSON
   - Add variant to `_variant_profile_map` in `topology_generation.py`
   - Update UI dropdown in `index.html`

3. **Test:**
   - Run unit tests: `python -m pytest tests/unit/topology/ -q`
   - Run E2E test: `python scripts/playwright_card3_e2e.py`
   - Verify all 4 variants generate correctly

4. **Deploy:**
   - Commit changes
   - Deploy application
   - No database migration needed

### Troubleshooting Template Issues

**Symptom:** "Tab not found" error when generating from standard template

**Diagnosis:**
1. Check `_VARIANT_TAB_MAP` in `template_loader.py`
2. Verify tab name matches exactly in `outpost_v1.7.drawio`
3. Ensure tab is a `<diagram>` element with `name` attribute

**Symptom:** Generated diagram missing sections

**Diagnosis:**
1. Check HAF profile `protected_roles` list
2. Verify cells have correct `haf-role` attributes
3. Check profile `placeholder_bindings` for token patterns

**Symptom:** User-uploaded template generates but with wrong profile

**Diagnosis:**
1. Check `variant` column in `topo_base` record
2. Verify variant is in `_variant_profile_map`
3. Check if variant was stored correctly at upload time

---

## Conclusion

The application provides two complementary template-loading mechanisms:

- **Path 1 (User Upload):** Flexible, supports any `.drawio` file, variant selection stored with upload
- **Path 2 (Bundled):** Consistent, version-controlled, pre-tested, no upload needed

Both paths converge on the same HAF generation pipeline, ensuring consistent output quality and auditability. The choice between them depends on use case:

- **Use Path 1** when users need to supply custom diagrams
- **Use Path 2** when you want to provide pre-packaged, tested templates

To load a new diagram template into the application, use **Path 1** (user upload). To add a new bundled variant, update the template file, profiles, and configuration as documented above.
