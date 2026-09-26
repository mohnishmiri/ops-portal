# Topology Template Admin — Complete Design Package

**Status:** ✅ Design Complete — Ready for TDD Implementation  
**Date:** September 26, 2026  
**Audience:** Architects, Agents, Developers, Project Managers

---

## What Was Delivered

A **complete, production-ready design document and implementation plan** for a DB-managed topology template registry feature. This package enables an agent to autonomously implement the feature using TDD across 10 iterative slices.

### Three Documents

| Document | Purpose | Length | Audience |
|----------|---------|--------|----------|
| **TOPOLOGY_TEMPLATE_ADMIN_DESIGN.md** | Complete architecture, design decisions, acceptance criteria | 758 lines | Architects, Reviewers |
| **TOPOLOGY_TEMPLATE_ADMIN_IMPLEMENTATION_PLAN.md** | Step-by-step implementation guide for 10 TDD slices | 821 lines | Agents, Developers |
| **TOPOLOGY_TEMPLATE_ADMIN_INDEX.md** | Navigation guide, quick reference, glossary | 247 lines | Everyone |

**Total:** 1,826 lines of comprehensive documentation

---

## What the Feature Does

Admins can upload new `.drawio` master template versions through a web UI, validate them against code-shipped HAF profiles, publish them, and set which version the application uses for topology generation.

### Key Capabilities

1. **Upload** — Admin uploads a multi-tab `.drawio` file
2. **Validate** — Deep validation: XML structure + haf-role annotations + profile compatibility
3. **Preview** — Show validation diagnostics before publishing
4. **Publish** — Store template, create database record, set as active
5. **Activate** — Switch between published template versions
6. **Retire** — Mark old versions as retired
7. **Fallback** — If no DB template published, use bundled `outpost_v1.7.drawio`
8. **Generate** — Card 3 uses DB template if available, falls back to bundled

---

## Architecture Highlights

### Design Decisions (Stakeholder-Approved)

✅ **DB-first with bundled fallback** — DB-published template wins; bundled is factory default  
✅ **Template file versioning** (1.7, 1.8) — Matches drawio naming convention  
✅ **HAF profiles stay in code** — Simpler, profiles rarely change  
✅ **Multi-tab upload** — Admin uploads one file; system extracts variant tabs  
✅ **Deep validation** — Compiler cross-checks roles against profiles at upload time  
✅ **No data migration** — Existing records untouched  
✅ **Alongside Catalog Admin** — New top-level nav item  

### New Components

- **TemplateCompiler** — Validates `.drawio` files (structural + role validation)
- **TemplateRelease** ORM model — Represents published templates in DB
- **TemplateRepository** — CRUD operations for releases
- **TemplateAdminPublishService** — Preview, publish, activate, retire workflows
- **TemplateAdminQueryService** — Read-only list and detail queries
- **resolve_template()** — DB-first, bundled-fallback resolution
- **Admin UI** at `/admin/templates` — Upload, list, detail, activate, retire

### Data Model

**New table: `tpl_releases`** (mirrors `cat_releases` pattern)
- Stores published template versions
- Tracks pub_state (DRAFT, PUBLISHED, RETIRED)
- Stores validation diagnostics
- Links to actors (published_by_id)

**Modified table: `topo_base`** (optional FK)
- Add `template_release_id` to track which release was used

---

## Implementation Plan

### 10 TDD Slices (Agent-Autonomous)

Each slice is independent, fully specified, and verifiable:

| # | Slice | Tests | Time | Dependencies |
|---|-------|-------|------|--------------|
| 1 | Structural Validation | 8 | 2-3h | stdlib |
| 2 | Deep Role Validation | 10 | 3-4h | Slice 1 |
| 3 | ORM + Repository | 15 | 4-5h | Slice 2 |
| 4 | Publish Service | 16 | 4-5h | Slice 3 |
| 5 | Query Service | 8 | 2-3h | Slice 3 |
| 6 | DB-First Resolution | 7 | 2-3h | Slice 5 |
| 7 | Wire Resolution | 4 | 1-2h | Slice 6 |
| 8 | Read-Only Routes | 7 | 3-4h | Slice 5 |
| 9 | Publish Routes | 11 | 4-5h | Slice 4 |
| 10 | Integration & Regression | 7 | 2-3h | All slices |
| **Total** | | **93 tests** | **28-37h** | |

### TDD Workflow (Per Slice)

1. **RED** — Write failing tests
2. **GREEN** — Implement just enough to pass
3. **REFACTOR** — Improve code clarity
4. **VERIFY** — Run verification command
5. **UPDATE** — Mark slice complete in STATE.md
6. **NEXT** — Move to next slice

---

## Files to Create/Modify

### New Files (14)

```
src/migration_intake/persistence/models_templates.py
src/migration_intake/persistence/repositories/templates.py
src/migration_intake/persistence/migrations/versions/0023_template_releases.py
src/migration_intake/topology/template_compiler.py
src/migration_intake/application/services/template_admin_queries.py
src/migration_intake/application/services/template_admin_publish.py
src/migration_intake/web/routes/template_admin.py
src/migration_intake/web/routes/template_admin_publish.py
src/migration_intake/web/templates/template_admin/list.html
src/migration_intake/web/templates/template_admin/detail.html
src/migration_intake/web/templates/template_admin/upload.html
tests/unit/topology/test_template_compiler.py
tests/unit/application/test_template_admin_queries.py
tests/unit/application/test_template_admin_publish.py
```

### Modified Files (7)

```
src/migration_intake/persistence/models.py
src/migration_intake/persistence/models_topology.py
src/migration_intake/topology/template_loader.py
src/migration_intake/application/services/topology_generation.py
src/migration_intake/web/routes/_nav.py
src/migration_intake/web/security.py
src/migration_intake/main.py
```

---

## Acceptance Criteria

### Functional (10)
1. ✅ Admin can upload multi-tab `.drawio` file via `/admin/templates/upload`
2. ✅ Preview validates without persisting; shows diagnostics
3. ✅ Publish validates, stores content, creates `tpl_releases` row
4. ✅ Detail view shows tabs, variant mapping, role counts, validation status
5. ✅ Activate sets a published release as the active template
6. ✅ Retire marks a release as retired (cannot be activated)
7. ✅ Card 3 uses DB-published template when available
8. ✅ Card 3 falls back to bundled template if no DB version
9. ✅ Deep validation catches: missing tabs, missing roles, profile mismatches
10. ✅ Version conflict: same version with different content is rejected

### Non-Functional (5)
11. ✅ No existing tests break
12. ✅ No migration of existing data required
13. ✅ Global nav shows "Template Admin" alongside "Catalog Admin"
14. ✅ All new code has ≥90% test coverage
15. ✅ Bundled fallback is deterministic and always works

---

## Key Metrics

| Metric | Value |
|--------|-------|
| **New Tests** | ~93 |
| **New Files** | 14 |
| **Modified Files** | 7 |
| **New Dependencies** | 0 |
| **Breaking Changes** | 0 |
| **Estimated Effort** | 28-37 hours |
| **Test Coverage** | ≥90% |
| **Regression Risk** | Low (optional FK, no existing table changes) |

---

## How to Use This Package

### For Architects
1. Read **TOPOLOGY_TEMPLATE_ADMIN_DESIGN.md** (30-40 min)
2. Review Section 3: Acceptance Criteria
3. Review Section 8: Risks & Mitigations
4. Approve or request changes

### For Agents (Implementation)
1. Read **TOPOLOGY_TEMPLATE_ADMIN_IMPLEMENTATION_PLAN.md** (20-30 min)
2. Start with **Slice 1** checklist
3. For each slice:
   - Follow the checklist exactly
   - Write failing tests first
   - Implement just enough to pass
   - Run verification command
   - Update `STATE.md`
4. Move to next slice only after all tests pass
5. After Slice 10, run full regression test suite

### For Project Managers
- **Design:** Complete ✅
- **Ready for implementation:** Yes ✅
- **Estimated duration:** 2-3 weeks (iterative)
- **Risk level:** Low (isolated feature, no breaking changes)
- **Dependencies:** None (uses existing libraries)

### For Reviewers
1. Read **TOPOLOGY_TEMPLATE_ADMIN_DESIGN.md** (architecture)
2. Review **TOPOLOGY_TEMPLATE_ADMIN_IMPLEMENTATION_PLAN.md** (approach)
3. Check `STATE.md` for progress
4. Review code changes after each slice

---

## Success Criteria

✅ **Implementation is complete when:**
- All 10 slices done
- ~93 tests passing
- No regressions (826+ existing tests still pass)
- Type checking passes (`mypy`)
- Linting passes (`ruff`)
- Feature ready for code review

---

## Related Documentation

### Previous Work
- [TEMPLATE_LOADING_ARCHITECTURE.md](TEMPLATE_LOADING_ARCHITECTURE.md) — Complete template loading paths
- [TEMPLATE_LOADING_QUICK_REFERENCE.md](TEMPLATE_LOADING_QUICK_REFERENCE.md) — Quick lookup guide
- [investigation-report-20260926.md](investigation-report-20260926.md) — Root cause analysis

### Project State
- [STATE.md](../STATE.md) — Current project state (to be updated during implementation)
- [HANDOFF_20250925.md](../HANDOFF_20250925.md) — Previous handoff document

---

## Document Navigation

| Document | Read Time | Best For |
|----------|-----------|----------|
| **TOPOLOGY_TEMPLATE_ADMIN_INDEX.md** | 10 min | Quick navigation, glossary |
| **TOPOLOGY_TEMPLATE_ADMIN_DESIGN.md** | 30-40 min | Architecture, design decisions, acceptance criteria |
| **TOPOLOGY_TEMPLATE_ADMIN_IMPLEMENTATION_PLAN.md** | 20-30 min | Step-by-step implementation guide |
| **This file (README)** | 5-10 min | Overview, quick reference |

---

## Questions?

- **"What should the feature do?"** → TOPOLOGY_TEMPLATE_ADMIN_DESIGN.md (Section 3)
- **"How do I implement Slice X?"** → TOPOLOGY_TEMPLATE_ADMIN_IMPLEMENTATION_PLAN.md (Slice X)
- **"What files do I change?"** → TOPOLOGY_TEMPLATE_ADMIN_DESIGN.md (Section 4)
- **"What's the architecture?"** → TOPOLOGY_TEMPLATE_ADMIN_DESIGN.md (Section 2)
- **"How do I verify my work?"** → TOPOLOGY_TEMPLATE_ADMIN_IMPLEMENTATION_PLAN.md (Verification)
- **"What's the glossary?"** → TOPOLOGY_TEMPLATE_ADMIN_INDEX.md (Glossary)

---

## Next Steps

1. **Architects:** Review TOPOLOGY_TEMPLATE_ADMIN_DESIGN.md and approve
2. **Agents:** Begin Slice 1 using TOPOLOGY_TEMPLATE_ADMIN_IMPLEMENTATION_PLAN.md
3. **Project Managers:** Track progress via STATE.md updates
4. **Reviewers:** Review code after each slice completion

---

**Package Version:** 1.0  
**Status:** ✅ Ready for Implementation  
**Last Updated:** September 26, 2026  
**Created by:** Technical Architecture Review (Comprehensive Planning Session)

---

## Summary

This is a **complete, production-ready design and implementation plan** for the Topology Template Admin feature. It includes:

✅ Comprehensive architecture document (758 lines)  
✅ Step-by-step implementation guide (821 lines)  
✅ Navigation and reference guide (247 lines)  
✅ 10 independent TDD slices  
✅ ~93 tests with exact names  
✅ 0 new dependencies  
✅ 0 breaking changes  
✅ Agent-autonomous implementation approach  

**The feature is ready to be built. Begin with Slice 1.**
