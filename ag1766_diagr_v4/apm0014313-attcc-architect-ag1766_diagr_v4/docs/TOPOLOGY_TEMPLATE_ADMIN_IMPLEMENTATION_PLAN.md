# Topology Template Admin — Implementation Plan

**Status:** Ready for Agent-Autonomous TDD Implementation  
**Estimated Duration:** 2-3 weeks (10 iterative slices)  
**Test Coverage Target:** ~93 new tests, ≥90% coverage

---

## Quick Start for Agent

1. Read `TOPOLOGY_TEMPLATE_ADMIN_DESIGN.md` for full architecture
2. Start with **Slice 1** below
3. For each slice:
   - Write failing tests first (RED)
   - Implement just enough to pass (GREEN)
   - Refactor for clarity (REFACTOR)
   - Run verification command
   - Update `STATE.md`
4. Move to next slice only after all tests pass
5. Never combine slices or skip ahead

---

## Slice Checklist

### Slice 1: Template Compiler — Structural Validation ✓

**Status:** Ready to start  
**Estimated Tests:** 8  
**Estimated Time:** 2-3 hours

**What to do:**
1. Create `src/migration_intake/topology/template_compiler.py`
2. Define `TemplateCompileResult` dataclass
3. Define `TemplateCompiler` class with `compile()` method
4. Implement structural validation:
   - Valid XML parsing
   - `<mxfile>` root check
   - Uncompressed diagram detection
   - Duplicate cell ID detection
   - Tab enumeration and counting

**Test file:** `tests/unit/topology/test_template_compiler.py`

**Test names:**
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

**Key dependencies:**
- `xml.etree.ElementTree` (stdlib)
- `dataclasses` (stdlib)
- Existing `template_loader.py` functions (reference only)

**Verification:**
```bash
python -m pytest tests/unit/topology/test_template_compiler.py -v
```

**Acceptance:**
- All 8 tests pass
- No type errors
- No lint errors

**Update STATE.md:**
```markdown
## Completed Slices

### Slice 1: Template Compiler — Structural Validation
- Tests: 8
- Status: COMPLETE
- Verification: PASSED
```

---

### Slice 2: Template Compiler — Deep HAF Role Validation ✓

**Status:** Ready after Slice 1  
**Estimated Tests:** 10  
**Estimated Time:** 3-4 hours

**What to do:**
1. Extend `TemplateCompiler` class
2. Add `_validate_tab_roles()` method
3. For each variant tab:
   - Parse with `parse_haf_template()` from `haf_pipeline.py`
   - Load profile with `get_profile_for_variant()` from `haf_pipeline.py`
   - Call `profile.validate_against_index(index)` to get warnings
4. Build `variant_manifest` list with role counts
5. Aggregate all diagnostics

**Test file:** `tests/unit/topology/test_template_compiler.py` (add to existing)

**Test names:**
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

**Key dependencies:**
- `haf_pipeline.py` — `parse_haf_template()`, `get_profile_for_variant()`
- `template_loader.py` — `_VARIANT_TAB_MAP` (reference)

**Verification:**
```bash
python -m pytest tests/unit/topology/test_template_compiler.py -v
```

**Acceptance:**
- All 18 tests pass (8 from Slice 1 + 10 new)
- `variant_manifest` includes role counts
- Profile validation warnings captured

**Update STATE.md:**
```markdown
### Slice 2: Template Compiler — Deep Role Validation
- Tests: 10 (18 total)
- Status: COMPLETE
- Verification: PASSED
```

---

### Slice 3: ORM Model + Repository ✓

**Status:** Ready after Slice 2  
**Estimated Tests:** 15  
**Estimated Time:** 4-5 hours

**What to do:**

**File 1: `src/migration_intake/persistence/models_templates.py`**
1. Import ORM types from `migration_intake.persistence.naming`
2. Define `TemplateRelease` class:
   - `id` — PortableUUID, PK
   - `template_version` — String(32), NOT NULL
   - `source_filename` — String(255), NOT NULL
   - `source_sha256` — Sha256Hex, NOT NULL, UNIQUE
   - `content_address` — String(255), NOT NULL
   - `size_bytes` — Integer, NOT NULL
   - `tab_count` — Integer, NOT NULL
   - `variant_manifest` — CanonicalJSON, NOT NULL
   - `compiler_version` — String(32), NOT NULL
   - `compiler_report` — CanonicalJSON, nullable
   - `pub_state` — String(32), NOT NULL (DRAFT, PUBLISHED, RETIRED)
   - `published_at` — PortableUTC, nullable
   - `published_by_id` — PortableUUID, nullable, FK to actors
   - `retired_at` — PortableUTC, nullable
   - `created_at` — PortableUTC, NOT NULL
3. Add `__table_args__` with UniqueConstraint on `source_sha256` and FK to actors

**File 2: `src/migration_intake/persistence/repositories/templates.py`**
1. Define `TemplateRepository` class (follow `CatalogRepository` pattern)
2. Implement methods:
   - `add_release(**values)` — insert, return dict
   - `get_release(release_id)` — query by ID, return dict or None
   - `get_latest_published_release()` — query PUBLISHED, ordered by published_at DESC
   - `list_releases()` — all releases, newest-first
   - `get_release_by_version(template_version)` — query by version
   - `get_release_by_version_and_hash(version, sha256)` — dedup check
   - `update_pub_state(release_id, new_state, ...)` — update state + timestamp
3. Use `_to_dict()` helper to convert ORM to dict

**File 3: `src/migration_intake/persistence/migrations/versions/0023_template_releases.py`**
1. Follow Alembic migration pattern from existing migrations
2. Create `tpl_releases` table with all columns
3. Add FK constraint to `actors.id`
4. Add unique constraint on `source_sha256`
5. Handle both SQLite and Oracle (use `_oracle_add_columns` pattern if needed)

**File 4: Modify `src/migration_intake/persistence/models.py`**
1. Import `TemplateRelease` from `models_templates`
2. Add to `__all__` export list

**Test file:** `tests/unit/application/test_template_repository.py`

**Test names:**
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

**Key dependencies:**
- `migration_intake.persistence.naming` — `Base`
- `migration_intake.persistence.types` — `PortableUUID`, `Sha256Hex`, `PortableUTC`, `CanonicalJSON`
- `migration_intake.persistence.repositories.catalogs` — reference pattern

**Verification:**
```bash
python -m pytest tests/unit/application/test_template_repository.py -v
```

**Acceptance:**
- All 15 tests pass
- Migration creates table correctly
- No FK violations
- Unique constraint enforced

**Update STATE.md:**
```markdown
### Slice 3: ORM Model + Repository
- Tests: 15
- Status: COMPLETE
- Verification: PASSED
```

---

### Slice 4: Template Admin Publish Service ✓

**Status:** Ready after Slice 3  
**Estimated Tests:** 16  
**Estimated Time:** 4-5 hours

**What to do:**

**File: `src/migration_intake/application/services/template_admin_publish.py`**

1. Define exception classes:
   - `TemplateCompileError(ApplicationServiceError)` — with `diagnostics` attribute
   - `TemplateVersionConflictError(ApplicationServiceError)`

2. Define `TemplateAdminPublishService` class:
   - `__init__(session_factory, storage_root=None)` — initialize with session factory and storage
   - `preview(content, filename) -> TemplateCompileResult` — compile without persisting
   - `publish(content, filename, template_version, actor) -> dict` — compile + persist + publish
   - `activate(release_id, actor) -> dict` — set as active (retire previous if exists)
   - `retire(release_id, actor) -> dict` — mark as retired

3. Implementation details:
   - `preview()`: Call `TemplateCompiler().compile()`, return result (no DB)
   - `publish()`:
     - Call `preview()` to validate
     - Check for version conflict: `get_release_by_version_and_hash()`
     - If exists with same hash, return existing (idempotent)
     - If exists with different hash, raise `TemplateVersionConflictError`
     - Store content via `FilesystemStore`
     - Create `tpl_releases` row with `pub_state=PUBLISHED`
     - Return dict
   - `activate()`:
     - Get release, verify it's PUBLISHED
     - Get current active release (if any)
     - Retire current active
     - Mark target as active (already PUBLISHED)
   - `retire()`:
     - Get release, verify it's PUBLISHED
     - Update `pub_state=RETIRED`, set `retired_at`

**Test file:** `tests/unit/application/test_template_admin_publish.py`

**Test names:**
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

**Key dependencies:**
- `TemplateCompiler` from Slice 1-2
- `TemplateRepository` from Slice 3
- `FilesystemStore` from `migration_intake.storage.filesystem`
- `uow_context` from `migration_intake.persistence.unit_of_work`
- `ActorContext` from `migration_intake.application.dto`

**Verification:**
```bash
python -m pytest tests/unit/application/test_template_admin_publish.py -v
```

**Acceptance:**
- All 16 tests pass
- Version conflict detection works
- Idempotency verified
- Content stored correctly

**Update STATE.md:**
```markdown
### Slice 4: Publish Service
- Tests: 16
- Status: COMPLETE
- Verification: PASSED
```

---

### Slice 5: Template Admin Query Service ✓

**Status:** Ready after Slice 4  
**Estimated Tests:** 8  
**Estimated Time:** 2-3 hours

**What to do:**

**File: `src/migration_intake/application/services/template_admin_queries.py`**

1. Define `TemplateAdminQueryService` class (follow `CatalogAdminQueryService` pattern):
   - `__init__(session_factory)` — initialize with session factory
   - `list_releases() -> list[dict]` — all releases, newest-first, with `is_active` flag
   - `get_release_detail(release_id) -> dict | None` — full detail including variant manifest

2. Implementation details:
   - `list_releases()`:
     - Query all releases via `TemplateRepository.list_releases()`
     - Get current active release via `get_latest_published_release()`
     - Decorate each with `is_active` flag
     - Return newest-first
   - `get_release_detail()`:
     - Validate UUID format (return None if invalid)
     - Get release via `TemplateRepository.get_release()`
     - Return full dict with variant_manifest and compiler_report

**Test file:** `tests/unit/application/test_template_admin_queries.py`

**Test names:**
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

**Key dependencies:**
- `TemplateRepository` from Slice 3
- `uow_context` from `migration_intake.persistence.unit_of_work`

**Verification:**
```bash
python -m pytest tests/unit/application/test_template_admin_queries.py -v
```

**Acceptance:**
- All 8 tests pass
- `is_active` flag correct
- UUID validation works

**Update STATE.md:**
```markdown
### Slice 5: Query Service
- Tests: 8
- Status: COMPLETE
- Verification: PASSED
```

---

### Slice 6: Template Loader — DB-First Resolution ✓

**Status:** Ready after Slice 5  
**Estimated Tests:** 7  
**Estimated Time:** 2-3 hours

**What to do:**

**File: Modify `src/migration_intake/topology/template_loader.py`**

1. Add new function `resolve_template()`:
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
   ```

2. Implementation:
   - If `session_factory` and `storage` provided:
     - Create session, query `TemplateRepository.get_latest_published_release()`
     - If found, load from filesystem via `storage.load(content_address)`
     - Extract variant tab via `extract_tab()`
     - Return (bytes, release_id)
   - Otherwise:
     - Call `load_bundled_template(variant)` (existing function)
     - Return (bytes, "bundled_fallback")

3. Keep existing functions unchanged:
   - `list_tabs()`
   - `extract_tab()`
   - `load_bundled_template()`

**Test file:** `tests/unit/topology/test_template_resolution.py` (new file)

**Test names:**
```
test_resolve_template_returns_db_published_when_available
test_resolve_template_falls_back_to_bundled_when_no_published
test_resolve_template_falls_back_when_db_unavailable
test_resolve_template_extracts_correct_variant_tab_from_db
test_resolve_template_returns_source_label_db
test_resolve_template_returns_source_label_bundled
test_load_bundled_still_works_unchanged
```

**Key dependencies:**
- `TemplateRepository` from Slice 3
- `FilesystemStore` from `migration_intake.storage.filesystem`
- Existing `template_loader.py` functions

**Verification:**
```bash
python -m pytest tests/unit/topology/test_template_resolution.py -v
python -m pytest tests/unit/topology/test_template_loader.py -v  # ensure no regression
```

**Acceptance:**
- All 7 new tests pass
- Existing `test_template_loader.py` tests still pass
- DB-first resolution works
- Fallback works
- Source labels correct

**Update STATE.md:**
```markdown
### Slice 6: DB-First Resolution
- Tests: 7
- Status: COMPLETE
- Verification: PASSED
```

---

### Slice 7: Wire Resolution into Generation Service ✓

**Status:** Ready after Slice 6  
**Estimated Tests:** 4  
**Estimated Time:** 1-2 hours

**What to do:**

**File: Modify `src/migration_intake/application/services/topology_generation.py`**

1. In `generate_from_standard_template()` method (around line 450):
   - Replace: `template_bytes = load_bundled_template(variant)`
   - With: `template_bytes, template_source = resolve_template(variant, session_factory=self._session_factory, storage=self._storage)`

2. When creating `topo_base` record (around line 473):
   - Add optional parameter: `template_release_id=template_source if template_source != "bundled_fallback" else None`

3. Import `resolve_template` from `template_loader`

**Test file:** Add to `tests/unit/topology/test_bundled_loader.py` or create new `tests/unit/topology/test_generation_resolution.py`

**Test names:**
```
test_generate_from_standard_uses_db_template_when_published
test_generate_from_standard_uses_bundled_when_no_published
test_generate_from_standard_records_template_release_id_on_topo_base
test_generate_from_standard_works_with_bundled_fallback
```

**Key dependencies:**
- `resolve_template()` from Slice 6
- Existing `generate_from_standard_template()` logic

**Verification:**
```bash
python -m pytest tests/unit/topology/ -v
python -m pytest tests/web/ -v
```

**Acceptance:**
- All 4 new tests pass
- Existing topology tests still pass (673+)
- Existing web tests still pass (153+)
- No regressions

**Update STATE.md:**
```markdown
### Slice 7: Wire Resolution
- Tests: 4
- Status: COMPLETE
- Verification: PASSED
```

---

### Slice 8: Admin Routes — Read-Only Views ✓

**Status:** Ready after Slice 7  
**Estimated Tests:** 7  
**Estimated Time:** 3-4 hours

**What to do:**

**File 1: `src/migration_intake/web/routes/template_admin.py`**

Follow `catalog_admin.py` pattern exactly:
1. Define routes:
   - `GET /admin/templates` — list releases
   - `GET /admin/templates/{release_id}` — release detail
2. Implement handlers:
   - `list_template_releases()` — call `TemplateAdminQueryService.list_releases()`, render `template_admin/list.html`
   - `get_template_release_detail()` — call `TemplateAdminQueryService.get_release_detail()`, render `template_admin/detail.html` or 404

**File 2: `src/migration_intake/web/templates/template_admin/list.html`**

Follow `catalog_admin/list.html` pattern:
- Table with columns: Version, State, Published, Tab Count, Active, Detail link
- Empty state message
- Status pills for pub_state

**File 3: `src/migration_intake/web/templates/template_admin/detail.html`**

Follow `catalog_admin/detail.html` pattern:
- Release metadata (version, filename, hash, compiler version)
- Variant manifest table (variant, tab name, role count)
- Compiler report (diagnostics)
- Back link

**File 4: Modify `src/migration_intake/web/routes/_nav.py`**

Add to `global_nav_items()`:
```python
{"key": "template_admin", "label": "Template Admin", "href": "/admin/templates"},
```

**File 5: Modify `src/migration_intake/main.py`**

Register router after catalog_admin_publish but before catalog_admin (to avoid wildcard collision):
```python
app.include_router(template_admin.router)
```

**Test file:** `tests/web/test_template_admin_routes.py`

**Test names:**
```
test_list_page_renders_empty_state
test_list_page_renders_releases_table
test_list_page_shows_active_badge
test_detail_page_renders_variant_manifest
test_detail_page_returns_404_for_unknown
test_detail_page_shows_compiler_report
test_nav_includes_template_admin_link
```

**Key dependencies:**
- `TemplateAdminQueryService` from Slice 5
- Jinja2 templates (existing)
- Navigation helpers (existing)

**Verification:**
```bash
python -m pytest tests/web/test_template_admin_routes.py -v
```

**Acceptance:**
- All 7 tests pass
- Pages render correctly
- Nav link present
- 404 handling works

**Update STATE.md:**
```markdown
### Slice 8: Read-Only Admin Routes
- Tests: 7
- Status: COMPLETE
- Verification: PASSED
```

---

### Slice 9: Admin Routes — Upload, Preview, Publish ✓

**Status:** Ready after Slice 8  
**Estimated Tests:** 11  
**Estimated Time:** 4-5 hours

**What to do:**

**File 1: `src/migration_intake/web/routes/template_admin_publish.py`**

Follow `catalog_admin_publish.py` pattern exactly:
1. Define routes:
   - `GET /admin/templates/upload` — upload form
   - `POST /admin/templates/preview` — validate without persisting
   - `POST /admin/templates/publish` — validate + persist
   - `POST /admin/templates/{id}/activate` — activate release
   - `POST /admin/templates/{id}/retire` — retire release

2. Implement handlers:
   - `upload_form()` — render `template_admin/upload.html` with CSRF token
   - `preview_template()` — call `TemplateAdminPublishService.preview()`, return JSON diagnostics
   - `publish_template()` — call `TemplateAdminPublishService.publish()`, return JSON with release ID
   - `activate_template()` — call `TemplateAdminPublishService.activate()`, return JSON
   - `retire_template()` — call `TemplateAdminPublishService.retire()`, return JSON

3. Security:
   - Check `require_capability(actor.role_codes, Capability.TEMPLATE_MANAGE)` FIRST (before CSRF check)
   - Validate CSRF token on all POST routes
   - Handle `TemplateCompileError` → 400 with diagnostics
   - Handle `TemplateVersionConflictError` → 409

**File 2: `src/migration_intake/web/templates/template_admin/upload.html`**

Follow `catalog_admin/upload.html` pattern:
- Form with fields:
  - `template_version` (required, text input, e.g. "1.8")
  - `file` (required, file input, accept `.drawio`)
  - `_csrf_token` (hidden)
- Preview button (client-side, calls POST /admin/templates/preview)
- Publish button (calls POST /admin/templates/publish)
- Diagnostics display area

**File 3: Modify `src/migration_intake/web/security.py`**

Add capability:
```python
TEMPLATE_MANAGE = "TEMPLATE_MANAGE"
```

**File 4: Modify `src/migration_intake/main.py`**

Register publish router BEFORE read-only router:
```python
app.include_router(template_admin_publish.router)
app.include_router(template_admin.router)
```

**Test file:** `tests/web/test_template_admin_publish_routes.py`

**Test names:**
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

**Key dependencies:**
- `TemplateAdminPublishService` from Slice 4
- `Capability`, `require_capability`, CSRF validation (existing)
- Jinja2 templates (existing)

**Verification:**
```bash
python -m pytest tests/web/test_template_admin_publish_routes.py -v
```

**Acceptance:**
- All 11 tests pass
- CSRF protection works
- Capability check works
- Error handling correct

**Update STATE.md:**
```markdown
### Slice 9: Publish Admin Routes
- Tests: 11
- Status: COMPLETE
- Verification: PASSED
```

---

### Slice 10: Integration & Regression Tests ✓

**Status:** Ready after Slice 9  
**Estimated Tests:** 7  
**Estimated Time:** 2-3 hours

**What to do:**

1. Write integration tests covering full flow:
   - Upload → Preview → Publish → Activate → Generate
   - Bundled fallback when no DB template
   - DB template takes priority over bundled

2. Run full regression test suite:
   - All topology tests (673+)
   - All web tests (153+)
   - All application tests
   - Full project tests

**Test file:** `tests/integration/test_template_admin_e2e.py` (new)

**Test names:**
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
python -m mypy src/migration_intake
python -m ruff check src/
```

**Acceptance:**
- All 7 integration tests pass
- All existing tests still pass (no regressions)
- Type checking passes
- Linting passes
- Feature ready for review

**Update STATE.md:**
```markdown
### Slice 10: Integration & Regression
- Tests: 7
- Status: COMPLETE
- Verification: PASSED

## Final Status
IMPLEMENTATION COMPLETE — All 10 slices done, ~93 tests passing, feature ready for review.
```

---

## Summary Checklist

After completing all 10 slices:

- [ ] All 93 tests passing
- [ ] No regressions in existing tests
- [ ] Type checking passes (`mypy`)
- [ ] Linting passes (`ruff`)
- [ ] `STATE.md` updated with final status
- [ ] All 14 new files created
- [ ] All 7 files modified
- [ ] Documentation updated
- [ ] Ready for code review

---

## Troubleshooting

**If tests fail:**
1. Read the error message carefully
2. Check the test file for what's expected
3. Debug the implementation
4. Fix and re-run
5. Do NOT move to next slice until all tests pass

**If you get stuck:**
1. Re-read the design document section for that slice
2. Look at the reference pattern (e.g., `catalog_admin.py` for routes)
3. Check existing code for similar patterns
4. Ask for clarification (but don't skip slices)

**If you need to refactor:**
1. Make sure all tests still pass after refactoring
2. Run the full test suite, not just the slice tests
3. Update `STATE.md` if you find issues

---

**Ready to start Slice 1? Begin here:**

```bash
cd /path/to/aws_diag_v4_1/aws_diag_v4
python -m pytest tests/unit/topology/test_template_compiler.py -v
```

Good luck! 🚀
