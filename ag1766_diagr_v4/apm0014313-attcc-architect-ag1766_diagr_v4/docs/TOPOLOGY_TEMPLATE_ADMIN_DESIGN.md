# Topology Template Admin — Design Document & TDD Implementation Plan

**Date:** September 26, 2026  
**Status:** Implemented (All slices complete)  
**Estimated Effort:** 10 slices, ~93 tests, ~2-3 weeks (iterative, agent-autonomous)

## Implementation Status (2026-09-26)

### Slice Tracker
- ✅ Slice 1 — Template compiler structural validation
- ✅ Slice 2 — Deep HAF role validation
- ✅ Slice 3 — ORM model/repository/migration
- ✅ Slice 4 — Publish service
- ✅ Slice 5 — Query service
- ✅ Slice 6 — DB-first template resolution
- ✅ Slice 7 — Standard-generation wiring to resolver
- ✅ Slice 8 — Read-only admin routes + templates
- ✅ Slice 9 — Publish/preview/activate/retire routes + upload template
- ✅ Slice 10 — Integration/regression verification

### Implemented Deviations (Documented)
- `TemplateRelease` lifecycle is represented through `pub_state` + timestamps; there is no separate “active” table. Active release is computed as latest `PUBLISHED` by `published_at` (same approach as catalog latest).
- `template_release_id` on `topo_base` is nullable and populated only when standard generation resolved from DB release (not bundled fallback).

### Validation Evidence
- New tests added and passing:
  - `tests/unit/topology/test_template_compiler.py`
  - `tests/unit/application/test_template_repository.py`
  - `tests/unit/application/test_template_admin_publish.py`
  - `tests/unit/application/test_template_admin_queries.py`
  - `tests/unit/topology/test_template_resolution.py`
  - `tests/unit/topology/test_generation_resolution.py`
  - `tests/integration/web/test_template_admin_routes.py`
- Regression suites executed:
  - `tests/unit/topology` (689 pass)
  - `tests/unit/application` (359 pass)
  - `tests/integration/web/test_topology_routes.py` (21 pass)
  - `tests/web/test_ui_shell.py tests/web/test_security.py tests/web/test_topology_containment.py` (115 pass)

---

## 1. Objective

Build a **Topology Template Admin** feature that mirrors the existing Catalog Admin pattern. Admins can upload new `.drawio` master template versions through the UI, validate them against code-shipped HAF profiles, publish them, and set which version the application uses for generation. The current bundled-on-disk template (`outpost_v1.7.drawio`) becomes the factory default fallback.

---

## 2. Architecture Overview

### 2.1 Design Decisions (from stakeholder review)

| Decision | Choice | Rationale |
|----------|--------|-----------|
| **Bundled handling** | DB-first with fallback | DB-published template takes priority; bundled template is factory default |
| **Version scheme** | Template file version (1.7, 1.8) | Matches drawio file naming convention |
| **Profile management** | Profiles stay in code | HAF profiles remain as JSON files; templates must match them |
| **Upload format** | Multi-tab file | Admin uploads one multi-tab drawio; system extracts variant tabs |
| **Existing data** | No migration | Existing topo_base/gen_runs records untouched |
| **Validation** | Deep validation | Validate XML + haf-role annotations + profile compatibility |
| **Navigation** | Alongside Catalog Admin | New top-level global nav item |

### 2.2 Component Map

```
┌──────────────────────────────────────────────────────────────────────┐
│                    TEMPLATE ADMIN UI                                │
│  GET  /admin/templates         → list releases                     │
│  GET  /admin/templates/upload  → upload form                       │
│  POST /admin/templates/preview → validate without persisting       │
│  POST /admin/templates/publish → validate + persist + activate     │
│  GET  /admin/templates/{id}    → release detail (tabs, roles, etc) │
│  POST /admin/templates/{id}/activate   → set as active             │
│  POST /admin/templates/{id}/retire     → retire version            │
└─────────────────────────────┬────────────────────────────────────────┘
                              │
                              ▼
┌──────────────────────────────────────────────────────────────────────┐
│             APPLICATION SERVICES                                    │
│  TemplateAdminQueryService   — list, detail (read-only)            │
│  TemplateAdminPublishService — preview, publish, activate, retire  │
└─────────────────────────────┬────────────────────────────────────────┘
                              │
         ┌────────────────────┼────────────────────┐
         ▼                    ▼                    ▼
┌──────────────┐   ┌──────────────────┐   ┌──────────────────┐
│ Template     │   │ Topology         │   │ HAF Pipeline     │
│ Compiler     │   │ Repository       │   │ (validation)     │
│ (validation) │   │ (persistence)    │   │                  │
└──────────────┘   └──────────────────┘   └──────────────────┘
```

### 2.3 Data Model

**New table: `tpl_releases`** (mirrors `cat_releases` pattern)

```sql
CREATE TABLE tpl_releases (
    id              CHAR(36)    NOT NULL PRIMARY KEY,
    template_version STRING(32) NOT NULL,         -- "1.7", "1.8", "2.0"
    source_filename  STRING(255) NOT NULL,         -- original upload filename
    source_sha256    CHAR(64)   NOT NULL UNIQUE,   -- content-addressed dedup
    content_address  STRING(255) NOT NULL,         -- filesystem storage key
    size_bytes       INTEGER    NOT NULL,
    tab_count        INTEGER    NOT NULL,          -- number of variant tabs
    variant_manifest JSON       NOT NULL,          -- [{variant, tab_name, role_count}]
    compiler_version STRING(32) NOT NULL,          -- validation engine version
    compiler_report  JSON       NULL,              -- validation diagnostics
    pub_state        STRING(32) NOT NULL,          -- DRAFT, PUBLISHED, RETIRED
    published_at     STRING(32) NULL,              -- UTC timestamp
    published_by_id  CHAR(36)   NULL,
    retired_at       STRING(32) NULL,
    created_at       STRING(32) NOT NULL,
    FOREIGN KEY (published_by_id) REFERENCES actors(id)
);
```

**Modified table: `topo_base`** — add optional FK to `tpl_releases`

```sql
ALTER TABLE topo_base ADD COLUMN template_release_id CHAR(36) NULL
    REFERENCES tpl_releases(id);
```

### 2.4 Resolution Logic (DB-first, bundled fallback)

```python
def resolve_template(variant: str) -> tuple[bytes, str]:
    """Return (template_bytes, source_label).
    
    Priority:
    1. Latest PUBLISHED tpl_releases row → load from content_address
    2. Bundled disk template (outpost_v1.7.drawio) → factory default
    """
    release = template_repo.get_latest_published_release()
    if release is not None:
        return load_from_filesystem(release["content_address"]), release["id"]
    return load_bundled_template(variant), "bundled_fallback"
```

### 2.5 Template Compiler/Validator

The compiler validates an uploaded `.drawio` file before publish. Validation steps:

1. **Structural validation**: Valid XML, `<mxfile>` root, uncompressed diagrams
2. **Tab enumeration**: Extract all `<diagram>` tabs, match to known variant keys via tab name
3. **Role validation per tab**: Parse each tab, index `haf-role` attributes, cross-check against the code-shipped HAF profile for that variant
4. **Profile compatibility**: For each variant tab, call `HafProfile.validate_against_index()` to detect missing roles
5. **Duplicate detection**: Ensure no duplicate cell IDs within a tab
6. **Completeness check**: Warn if expected variants are missing tabs

Returns a `TemplateCompileResult` with:
- `is_valid: bool`
- `tab_count: int`
- `variant_manifest: list[dict]` — per-variant tab info
- `diagnostics: list[dict]` — errors and warnings with severity, tab, role, message

---

## 3. Acceptance Criteria

### Functional
1. Admin can upload a multi-tab `.drawio` file via `/admin/templates/upload`
2. Preview validates without persisting; shows diagnostics report
3. Publish validates, stores content, creates `tpl_releases` row
4. Detail view shows tabs, variant mapping, role counts, validation status
5. Activate sets a published release as the active template
6. Retire marks a release as retired (cannot be activated)
7. Card 3 "Generate from Standard Template" uses DB-published template when available
8. Card 3 falls back to bundled template if no DB-published version exists
9. Deep validation catches: missing tabs, missing haf-role annotations, profile mismatches
10. Version conflict: same `template_version` with different content is rejected

### Non-Functional
11. No existing tests break
12. No migration of existing `topo_base` or `gen_runs` data required
13. Global nav shows "Template Admin" alongside "Catalog Admin"
14. All new code has ≥90% test coverage via TDD
15. Bundled fallback is deterministic and always works

---

## 4. Files to Create / Modify

### New Files (14)

| # | File | Purpose |
|---|------|---------|
| 1 | `src/migration_intake/persistence/models_templates.py` | `TemplateRelease` ORM model |
| 2 | `src/migration_intake/persistence/repositories/templates.py` | `TemplateRepository` (CRUD + queries) |
| 3 | `src/migration_intake/persistence/migrations/versions/0023_template_releases.py` | Alembic migration |
| 4 | `src/migration_intake/topology/template_compiler.py` | Validation/compilation engine |
| 5 | `src/migration_intake/application/services/template_admin_queries.py` | Read-only query service |
| 6 | `src/migration_intake/application/services/template_admin_publish.py` | Publish/activate/retire service |
| 7 | `src/migration_intake/web/routes/template_admin.py` | Read-only admin routes |
| 8 | `src/migration_intake/web/routes/template_admin_publish.py` | State-changing admin routes |
| 9 | `src/migration_intake/web/templates/template_admin/list.html` | Release list page |
| 10 | `src/migration_intake/web/templates/template_admin/detail.html` | Release detail page |
| 11 | `src/migration_intake/web/templates/template_admin/upload.html` | Upload form page |
| 12 | `tests/unit/topology/test_template_compiler.py` | Compiler unit tests |
| 13 | `tests/unit/application/test_template_admin_queries.py` | Query service tests |
| 14 | `tests/unit/application/test_template_admin_publish.py` | Publish service tests |

### Modified Files (7)

| # | File | Change |
|---|------|--------|
| 1 | `src/migration_intake/persistence/models.py` | Export `TemplateRelease` |
| 2 | `src/migration_intake/persistence/models_topology.py` | Add `template_release_id` to `TopologyBaseArtifact` |
| 3 | `src/migration_intake/topology/template_loader.py` | Add `load_published_template()` with DB-first fallback |
| 4 | `src/migration_intake/application/services/topology_generation.py` | Use `resolve_template()` instead of `load_bundled_template()` |
| 5 | `src/migration_intake/web/routes/_nav.py` | Add "Template Admin" to `global_nav_items()` |
| 6 | `src/migration_intake/web/security.py` | Add `TEMPLATE_MANAGE` capability |
| 7 | `src/migration_intake/main.py` | Register template admin routers |

---

## 5. TDD Implementation Slices

Each slice follows RED-GREEN-REFACTOR. Write failing tests first, then implement just enough to pass, then refactor. Each slice is independent and can be verified with `python -m pytest tests/unit/ -q`.

### Slice 1: Template Compiler — Structural Validation

**Goal:** Build the validation engine that checks uploaded `.drawio` files.

**File to create:** `src/migration_intake/topology/template_compiler.py`

**Tests (RED first):**

```
test_compile_valid_multitab_drawio_returns_success
test_compile_invalid_xml_returns_error
test_compile_non_mxfile_root_returns_error
test_compile_compressed_diagram_returns_error
test_compile_empty_file_returns_error
test_compile_single_tab_drawio_returns_warning
test_compile_extracts_tab_names_and_counts
test_compile_detects_duplicate_cell_ids
```

**Implementation:**

```python
# src/migration_intake/topology/template_compiler.py

@dataclass
class TemplateCompileResult:
    is_valid: bool
    tab_count: int
    variant_manifest: list[dict[str, Any]]
    diagnostics: list[dict[str, Any]]
    source_sha256: str

class TemplateCompiler:
    COMPILER_VERSION = "1.0.0"
    
    def compile(self, content: bytes, filename: str) -> TemplateCompileResult:
        """Validate a .drawio template without persisting."""
        ...
```

**Verification:** `python -m pytest tests/unit/topology/test_template_compiler.py -v`

---

### Slice 2: Template Compiler — Deep HAF Role Validation

**Goal:** Extend compiler to cross-validate tab roles against code-shipped HAF profiles.

**Tests (RED first):**

```
test_compile_validates_roles_against_basic_profile
test_compile_validates_roles_against_tlgw_profile
test_compile_validates_roles_against_f5_profile
test_compile_validates_roles_against_hadr_profile
test_compile_missing_role_produces_warning
test_compile_extra_role_produces_info
test_compile_variant_manifest_includes_role_counts
test_compile_unmatched_tab_name_produces_warning
test_compile_known_variants_mapped_to_profiles
test_compile_profile_validation_uses_validate_against_index
```

**Implementation extends `TemplateCompiler.compile()`:**

```python
def _validate_tab_roles(self, tab_bytes: bytes, variant: str) -> list[dict]:
    """Cross-validate a single tab against its HAF profile."""
    index = parse_haf_template(tab_bytes)
    profile = get_profile_for_variant(variant)
    return profile.validate_against_index(index)
```

**Verification:** `python -m pytest tests/unit/topology/test_template_compiler.py -v`

---

### Slice 3: ORM Model + Repository

**Goal:** Create the `tpl_releases` table model and repository with CRUD operations.

**Files to create:**
- `src/migration_intake/persistence/models_templates.py`
- `src/migration_intake/persistence/repositories/templates.py`
- `src/migration_intake/persistence/migrations/versions/0023_template_releases.py`

**File to modify:**
- `src/migration_intake/persistence/models.py` — add export

**Tests (RED first):** `tests/unit/application/test_template_repository.py`

```
test_add_release_returns_dict_with_all_fields
test_add_release_persists_to_database
test_get_release_returns_none_for_unknown_id
test_get_release_returns_dict_for_existing
test_get_latest_published_returns_most_recent
test_get_latest_published_returns_none_when_no_published
test_get_latest_published_ignores_retired_and_draft
test_list_releases_returns_newest_first
test_list_releases_empty_returns_empty_list
test_get_release_by_version_finds_match
test_get_release_by_version_returns_none_for_unknown
test_get_release_by_version_and_hash_deduplicates
test_update_pub_state_to_published_sets_timestamp
test_update_pub_state_to_retired_sets_timestamp
test_duplicate_source_sha256_raises_integrity_error
```

**Implementation:**

```python
# src/migration_intake/persistence/models_templates.py

class TemplateRelease(Base):
    __tablename__ = "tpl_releases"
    __table_args__ = (
        UniqueConstraint("source_sha256"),
        ForeignKeyConstraint(
            ["published_by_id"], ["actors.id"], name="fk_trel_actor"
        ),
    )

    id = Column(PortableUUID(), primary_key=True)
    template_version = Column(String(32), nullable=False)
    source_filename = Column(String(255), nullable=False)
    source_sha256 = Column(Sha256Hex(), nullable=False)
    content_address = Column(String(255), nullable=False)
    size_bytes = Column(Integer, nullable=False)
    tab_count = Column(Integer, nullable=False)
    variant_manifest = Column(CanonicalJSON(), nullable=False)
    compiler_version = Column(String(32), nullable=False)
    compiler_report = Column(CanonicalJSON(), nullable=True)
    pub_state = Column(String(32), nullable=False)  # DRAFT, PUBLISHED, RETIRED
    published_at = Column(PortableUTC(), nullable=True)
    published_by_id = Column(PortableUUID(), nullable=True)
    retired_at = Column(PortableUTC(), nullable=True)
    created_at = Column(PortableUTC(), nullable=False)
```

```python
# src/migration_intake/persistence/repositories/templates.py

class TemplateRepository:
    def __init__(self, session: Session) -> None: ...
    def add_release(self, **values) -> dict[str, Any]: ...
    def get_release(self, release_id: str) -> dict[str, Any] | None: ...
    def get_latest_published_release(self) -> dict[str, Any] | None: ...
    def list_releases(self) -> list[dict[str, Any]]: ...
    def get_release_by_version(self, template_version: str) -> dict[str, Any] | None: ...
    def get_release_by_version_and_hash(self, version: str, sha256: str) -> dict[str, Any] | None: ...
    def update_pub_state(self, release_id: str, new_state: str, ...) -> dict[str, Any]: ...
```

**Verification:** `python -m pytest tests/unit/application/test_template_repository.py -v`

---

### Slice 4: Template Admin Publish Service

**Goal:** Application service for preview, publish, activate, retire workflows.

**File to create:** `src/migration_intake/application/services/template_admin_publish.py`

**Tests (RED first):** `tests/unit/application/test_template_admin_publish.py`

```
test_preview_valid_template_returns_success
test_preview_invalid_template_returns_diagnostics
test_preview_does_not_persist_to_database
test_publish_valid_template_creates_release
test_publish_valid_template_stores_content
test_publish_valid_template_sets_published_state
test_publish_duplicate_version_different_content_raises
test_publish_duplicate_version_same_content_returns_existing
test_publish_invalid_template_raises_compile_error
test_activate_sets_published_state
test_activate_retires_previously_active_release
test_activate_non_published_raises_error
test_activate_already_active_is_idempotent
test_retire_sets_retired_state_and_timestamp
test_retire_already_retired_is_idempotent
test_retire_draft_raises_error
```

**Implementation:**

```python
class TemplateCompileError(ApplicationServiceError):
    def __init__(self, message: str, diagnostics: list[dict]) -> None: ...

class TemplateVersionConflictError(ApplicationServiceError): ...

class TemplateAdminPublishService:
    def __init__(self, session_factory: sessionmaker, storage_root: Path | None = None): ...
    
    def preview(self, content: bytes, filename: str) -> TemplateCompileResult:
        """Compile without persisting."""
        
    def publish(self, content: bytes, filename: str, 
                template_version: str, actor: ActorContext) -> dict:
        """Compile + persist + set as PUBLISHED."""
        
    def activate(self, release_id: str, actor: ActorContext) -> dict:
        """Set a PUBLISHED release as the active template."""
        
    def retire(self, release_id: str, actor: ActorContext) -> dict:
        """Mark a PUBLISHED/active release as RETIRED."""
```

**Verification:** `python -m pytest tests/unit/application/test_template_admin_publish.py -v`

---

### Slice 5: Template Admin Query Service

**Goal:** Read-only query service for the admin UI.

**File to create:** `src/migration_intake/application/services/template_admin_queries.py`

**Tests (RED first):** `tests/unit/application/test_template_admin_queries.py`

```
test_list_releases_returns_all_newest_first
test_list_releases_marks_is_active
test_list_releases_empty_returns_empty
test_list_releases_includes_generation_run_count
test_get_release_detail_returns_variant_manifest
test_get_release_detail_returns_compiler_report
test_get_release_detail_returns_none_for_unknown_id
test_get_release_detail_invalid_uuid_returns_none
```

**Implementation:**

```python
class TemplateAdminQueryService:
    def __init__(self, session_factory: sessionmaker) -> None: ...
    
    def list_releases(self) -> list[dict[str, Any]]:
        """All releases, newest-first, with is_active flag."""
        
    def get_release_detail(self, release_id: str) -> dict[str, Any] | None:
        """Full release detail including variant manifest and diagnostics."""
```

**Verification:** `python -m pytest tests/unit/application/test_template_admin_queries.py -v`

---

### Slice 6: Template Loader — DB-First Resolution

**Goal:** Modify `template_loader.py` to resolve templates from DB first, falling back to bundled.

**File to modify:** `src/migration_intake/topology/template_loader.py`

**Tests (RED first):** Add to `tests/unit/topology/test_template_loader.py` or new `tests/unit/topology/test_template_resolution.py`

```
test_resolve_template_returns_db_published_when_available
test_resolve_template_falls_back_to_bundled_when_no_published
test_resolve_template_falls_back_when_db_unavailable
test_resolve_template_extracts_correct_variant_tab_from_db
test_resolve_template_returns_source_label_db
test_resolve_template_returns_source_label_bundled
test_load_bundled_still_works_unchanged
```

**Implementation:**

```python
def resolve_template(
    variant: str,
    session_factory: sessionmaker | None = None,
    storage: FilesystemStore | None = None,
) -> tuple[bytes, str]:
    """Load template with DB-first, bundled-fallback resolution.
    
    Returns:
        (template_bytes, source_label) where source_label is either
        the release ID or "bundled_fallback".
    """
    if session_factory is not None:
        session = session_factory()
        try:
            repo = TemplateRepository(session)
            release = repo.get_latest_published_release()
            if release is not None and storage is not None:
                full_bytes = storage.load(release["content_address"])
                return extract_tab(full_bytes, tab_name=_VARIANT_TAB_MAP[variant]), release["id"]
        finally:
            session.close()
    
    return load_bundled_template(variant), "bundled_fallback"
```

**Verification:** `python -m pytest tests/unit/topology/test_template_resolution.py -v`

---

### Slice 7: Wire Resolution into Generation Service

**Goal:** Modify `generate_from_standard_template()` to use `resolve_template()`.

**File to modify:** `src/migration_intake/application/services/topology_generation.py`

**Tests (RED first):** Add to `tests/unit/topology/test_bundled_loader.py` or new integration test

```
test_generate_from_standard_uses_db_template_when_published
test_generate_from_standard_uses_bundled_when_no_published
test_generate_from_standard_records_template_release_id_on_topo_base
test_generate_from_standard_works_with_bundled_fallback
```

**Implementation:**

Modify `generate_from_standard_template()` at line ~450:

```python
# Before (current):
template_bytes = load_bundled_template(variant)

# After:
template_bytes, template_source = resolve_template(
    variant, 
    session_factory=self._session_factory,
    storage=self._storage,
)
```

And when creating the `topo_base` record, optionally set `template_release_id` if source is a DB release.

**Verification:** `python -m pytest tests/unit/topology/ -v && python -m pytest tests/web/ -v`

---

### Slice 8: Admin Routes — Read-Only Views

**Goal:** Build the read-only admin pages (list + detail).

**Files to create:**
- `src/migration_intake/web/routes/template_admin.py`
- `src/migration_intake/web/templates/template_admin/list.html`
- `src/migration_intake/web/templates/template_admin/detail.html`

**Files to modify:**
- `src/migration_intake/web/routes/_nav.py` — add "Template Admin"
- `src/migration_intake/main.py` — register router

**Tests (RED first):** `tests/web/test_template_admin_routes.py`

```
test_list_page_renders_empty_state
test_list_page_renders_releases_table
test_list_page_shows_active_badge
test_detail_page_renders_variant_manifest
test_detail_page_returns_404_for_unknown
test_detail_page_shows_compiler_report
test_nav_includes_template_admin_link
```

**Implementation:** Follow `catalog_admin.py` pattern exactly:
- GET `/admin/templates` → list.html
- GET `/admin/templates/{release_id}` → detail.html

**Verification:** `python -m pytest tests/web/test_template_admin_routes.py -v`

---

### Slice 9: Admin Routes — Upload, Preview, Publish

**Goal:** Build the state-changing admin endpoints.

**Files to create:**
- `src/migration_intake/web/routes/template_admin_publish.py`
- `src/migration_intake/web/templates/template_admin/upload.html`

**File to modify:**
- `src/migration_intake/web/security.py` — add `TEMPLATE_MANAGE` capability
- `src/migration_intake/main.py` — register publish router (BEFORE read-only router)

**Tests (RED first):** `tests/web/test_template_admin_publish_routes.py`

```
test_upload_form_renders_with_csrf_token
test_preview_valid_template_returns_diagnostics_json
test_preview_invalid_template_returns_400
test_publish_valid_template_creates_release
test_publish_invalid_template_returns_400
test_publish_duplicate_version_returns_409
test_publish_requires_csrf_token
test_publish_requires_template_manage_capability
test_activate_sets_active_release
test_activate_unknown_release_returns_404
test_retire_sets_retired_state
```

**Implementation:** Follow `catalog_admin_publish.py` pattern:
- GET `/admin/templates/upload` → upload.html form
- POST `/admin/templates/preview` → JSON diagnostics
- POST `/admin/templates/publish` → create release
- POST `/admin/templates/{id}/activate` → activate
- POST `/admin/templates/{id}/retire` → retire

**Verification:** `python -m pytest tests/web/test_template_admin_publish_routes.py -v`

---

### Slice 10: Integration & Regression Tests

**Goal:** Verify the complete flow end-to-end and ensure no regressions.

**Tests:**

```
test_full_flow_upload_preview_publish_generate
test_generate_standard_uses_published_template_over_bundled
test_generate_standard_falls_back_when_no_published
test_existing_topology_tests_still_pass
test_existing_web_tests_still_pass
test_card2_unaffected_by_template_admin
test_card3_uses_db_template_when_available
```

**Verification:**
```bash
python -m pytest tests/unit/topology/ -v
python -m pytest tests/unit/application/ -v  
python -m pytest tests/web/ -v
python -m pytest tests/ -v  # full regression
```

---

## 6. STATE.md Template for Agent

The agent should update `STATE.md` after each slice:

```markdown
# Topology Template Admin — State Tracker

## Objective
Implement DB-managed topology template registry with admin UI, 
deep validation, and DB-first/bundled-fallback resolution.

## Current Phase
Implementation — Slice {N} of 10

## Current Slice
Slice {N}: {Description}

## Status
{IN_PROGRESS | COMPLETE}

## Baseline Results
{test counts after each slice}

## Completed Slices
### Slice 1: ...
- Tests: X
- Status: COMPLETE

## Next Actions
{what to do next}
```

---

## 7. Implementation Plan (implementation.plan.md) Auto-Update Rules

After each slice the agent should:
1. Run the slice's verification command
2. Record pass/fail count in `STATE.md`
3. Mark the slice as COMPLETE in `STATE.md`
4. Update the "Current Slice" to the next one
5. If tests fail, debug and fix within the same slice before moving on
6. Never skip a slice or combine slices without explicit approval

---

## 8. Risks & Mitigations

| Risk | Mitigation |
|------|-----------|
| Migration breaks existing tests | New table only; no changes to existing tables (except optional nullable FK on topo_base) |
| Profile mismatch not caught until generation | Deep validation in compiler catches role mismatches at upload time |
| DB-first resolution introduces latency | Single query with index on pub_state; cache if needed later |
| Bundled fallback masks broken DB path | Explicit logging when fallback is used; test both paths |
| Multi-tab parser edge cases | Reuses existing battle-tested `template_loader.py` functions |
| CSRF/capability gaps | Follow exact `catalog_admin_publish.py` security pattern |

---

## 9. Verification Commands

```bash
# Per-slice verification
python -m pytest tests/unit/topology/test_template_compiler.py -v     # Slice 1-2
python -m pytest tests/unit/application/test_template_repository.py -v # Slice 3
python -m pytest tests/unit/application/test_template_admin_publish.py -v # Slice 4
python -m pytest tests/unit/application/test_template_admin_queries.py -v # Slice 5
python -m pytest tests/unit/topology/test_template_resolution.py -v    # Slice 6
python -m pytest tests/unit/topology/ -v                               # Slice 7
python -m pytest tests/web/test_template_admin_routes.py -v            # Slice 8
python -m pytest tests/web/test_template_admin_publish_routes.py -v    # Slice 9
python -m pytest tests/ -v                                             # Slice 10 (full)

# Type checking
python -m mypy src/migration_intake

# Linting
python -m ruff check src/
```

---

## 10. Estimated Test Count

| Slice | Tests |
|-------|-------|
| 1: Structural Validation | ~8 |
| 2: Deep Role Validation | ~10 |
| 3: ORM + Repository | ~15 |
| 4: Publish Service | ~16 |
| 5: Query Service | ~8 |
| 6: DB-First Resolution | ~7 |
| 7: Wire Resolution | ~4 |
| 8: Read-Only Routes | ~7 |
| 9: Publish Routes | ~11 |
| 10: Integration | ~7 |
| **Total** | **~93 new tests** |

---

## 11. Dependencies

- **No new external dependencies** — uses existing SQLAlchemy, FastAPI, Jinja2, xml.etree
- **Existing internal dependencies** reused:
  - `template_loader.py` — `list_tabs()`, `extract_tab()`
  - `haf_pipeline.py` — `parse_haf_template()`, `get_profile_for_variant()`, `HafProfile.validate_against_index()`
  - `FilesystemStore` — content-addressed storage
  - `uow_context` — unit of work pattern
  - Security: `Capability`, `require_capability`, CSRF validation
  - Navigation: `global_nav_items()`

---

## 12. Non-Goals (Out of Scope)

- HAF profile management via UI (profiles remain as code-shipped JSON files)
- Template editing in the browser (admin uploads complete files)
- Automatic migration of existing `topo_base` records to new release system
- Multi-tenant template isolation (single global template registry)
- Template rollback (retire + activate a different version instead)
- Template diff/comparison UI (future enhancement)

---

## 13. Next Steps

1. **Agent begins Slice 1** — Create `template_compiler.py` with structural validation tests
2. **After each slice** — Update `STATE.md` with test counts and completion status
3. **After Slice 10** — Full regression test suite passes, feature ready for review
4. **Post-implementation** — Update `TEMPLATE_LOADING_ARCHITECTURE.md` with new admin section

---

**Document Version:** 1.0  
**Last Updated:** September 26, 2026  
**Ready for Implementation:** Yes
