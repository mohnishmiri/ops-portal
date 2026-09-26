# Topology Template Admin — Documentation Index

**Status:** Design Complete — Ready for TDD Implementation  
**Last Updated:** September 26, 2026

---

## Quick Navigation

### For Architects & Reviewers
Start here: **[TOPOLOGY_TEMPLATE_ADMIN_DESIGN.md](TOPOLOGY_TEMPLATE_ADMIN_DESIGN.md)**
- Complete architecture overview
- Design decisions and rationale
- Data model and component map
- Acceptance criteria
- Risks and mitigations
- ~760 lines, 30-40 min read

### For Implementing Agents
Start here: **[TOPOLOGY_TEMPLATE_ADMIN_IMPLEMENTATION_PLAN.md](TOPOLOGY_TEMPLATE_ADMIN_IMPLEMENTATION_PLAN.md)**
- 10 TDD slices with exact instructions
- Test names and file locations
- Implementation pseudocode
- Verification commands
- Slice-by-slice checklist
- ~820 lines, step-by-step guide

### For Project Managers
**Summary:** 10 iterative slices, ~93 tests, 2-3 weeks, 0 new dependencies

---

## Document Overview

### 1. TOPOLOGY_TEMPLATE_ADMIN_DESIGN.md

**What it covers:**
- Objective and architecture
- Design decisions (DB-first, semantic versioning, etc.)
- Component map and data model
- Template compiler validation logic
- Acceptance criteria (15 items)
- File changes (14 new, 7 modified)
- 10 TDD slices with test names
- Risks and mitigations
- Dependencies and non-goals

**When to read:**
- Before starting implementation
- During design review
- For understanding the big picture

**Key sections:**
- Section 2: Architecture Overview
- Section 3: Acceptance Criteria
- Section 4: Files to Create/Modify
- Section 5: TDD Implementation Slices

---

### 2. TOPOLOGY_TEMPLATE_ADMIN_IMPLEMENTATION_PLAN.md

**What it covers:**
- Quick start for agents
- Detailed checklist for each of 10 slices
- For each slice:
  - Status and estimated time
  - Exact files to create/modify
  - Implementation details
  - Test names and file locations
  - Key dependencies
  - Verification commands
  - Acceptance criteria
- Summary checklist
- Troubleshooting guide

**When to read:**
- When starting implementation
- For each slice before coding
- For verification commands

**Key sections:**
- Slice 1-10 checklists (each ~2-3 pages)
- Verification commands (per slice)
- Summary checklist (final verification)

---

### 3. TOPOLOGY_TEMPLATE_ADMIN_INDEX.md (this file)

**What it covers:**
- Navigation guide
- Document overview
- Key facts and statistics
- Related documentation
- Glossary

---

## Key Facts

| Aspect | Details |
|--------|---------|
| **Objective** | DB-managed topology template registry with admin UI |
| **Pattern** | Modeled after existing Catalog Admin (CAT-B2/B3) |
| **New Files** | 14 (models, services, routes, templates, tests) |
| **Modified Files** | 7 (models, routes, nav, security, main) |
| **New Tests** | ~93 across 10 slices |
| **New Dependencies** | 0 (uses existing SQLAlchemy, FastAPI, Jinja2) |
| **Estimated Time** | 2-3 weeks (iterative, agent-autonomous) |
| **Test Coverage** | ≥90% of new code |
| **Breaking Changes** | None (optional FK on topo_base, no existing table changes) |

---

## Architecture Summary

### Two Template Resolution Paths

**Path 1: User-Uploaded (Card 1 → Card 2)**
- User uploads `.drawio` file via UI
- Stored in `topo_base` table
- Used for generation via Card 2
- Existing flow, unchanged

**Path 2: Bundled Standard (Card 3)**
- User selects variant via UI
- **NEW:** Loads from DB if published template exists
- **FALLBACK:** Uses bundled disk template if no DB version
- Existing flow, enhanced with DB-first resolution

### New Components

| Component | Purpose |
|-----------|---------|
| `TemplateCompiler` | Validates `.drawio` files (structural + role validation) |
| `TemplateRelease` | ORM model for `tpl_releases` table |
| `TemplateRepository` | CRUD operations for releases |
| `TemplateAdminPublishService` | Preview, publish, activate, retire workflows |
| `TemplateAdminQueryService` | Read-only list and detail queries |
| `resolve_template()` | DB-first, bundled-fallback resolution |
| `/admin/templates` routes | Admin UI for template management |

---

## Implementation Slices

| # | Slice | Tests | Time | Status |
|---|-------|-------|------|--------|
| 1 | Structural Validation | 8 | 2-3h | Ready |
| 2 | Deep Role Validation | 10 | 3-4h | Ready |
| 3 | ORM + Repository | 15 | 4-5h | Ready |
| 4 | Publish Service | 16 | 4-5h | Ready |
| 5 | Query Service | 8 | 2-3h | Ready |
| 6 | DB-First Resolution | 7 | 2-3h | Ready |
| 7 | Wire Resolution | 4 | 1-2h | Ready |
| 8 | Read-Only Routes | 7 | 3-4h | Ready |
| 9 | Publish Routes | 11 | 4-5h | Ready |
| 10 | Integration & Regression | 7 | 2-3h | Ready |
| **Total** | | **93** | **28-37h** | **Ready** |

---

## Related Documentation

### Previous Work
- [TEMPLATE_LOADING_ARCHITECTURE.md](TEMPLATE_LOADING_ARCHITECTURE.md) — Complete template loading paths (user-uploaded + bundled)
- [TEMPLATE_LOADING_QUICK_REFERENCE.md](TEMPLATE_LOADING_QUICK_REFERENCE.md) — Quick lookup for template operations
- [investigation-report-20260926.md](investigation-report-20260926.md) — Root cause analysis of UI generation issues

### Project State
- [STATE.md](../STATE.md) — Current project state (to be updated during implementation)
- [HANDOFF_20250925.md](../HANDOFF_20250925.md) — Previous handoff document

---

## Glossary

| Term | Definition |
|------|-----------|
| **Bundled Template** | `outpost_v1.7.drawio` shipped with the application code |
| **DB-Published Template** | `.drawio` file uploaded via admin UI and stored in `tpl_releases` table |
| **Variant** | Template variant key: "basic", "tlgw", "f5", "hadr" |
| **Tab** | Individual diagram within a multi-tab `.drawio` file |
| **HAF Role** | Cell attribute (`haf-role`) defining semantic role in topology diagram |
| **HAF Profile** | JSON config mapping roles to resolution rules (code-shipped) |
| **Template Compiler** | Validation engine that checks `.drawio` files before publish |
| **Pub State** | Publication state: DRAFT, PUBLISHED, RETIRED |
| **Content Address** | Filesystem storage key based on SHA-256 hash |
| **DB-First Resolution** | Load template from DB if published; fallback to bundled |

---

## Getting Started

### For Architects
1. Read [TOPOLOGY_TEMPLATE_ADMIN_DESIGN.md](TOPOLOGY_TEMPLATE_ADMIN_DESIGN.md) (30-40 min)
2. Review acceptance criteria (Section 3)
3. Review risks and mitigations (Section 8)
4. Approve or request changes

### For Agents (TDD Implementation)
1. Read [TOPOLOGY_TEMPLATE_ADMIN_IMPLEMENTATION_PLAN.md](TOPOLOGY_TEMPLATE_ADMIN_IMPLEMENTATION_PLAN.md) (20-30 min)
2. Start with **Slice 1** checklist
3. For each slice:
   - Write failing tests (RED)
   - Implement just enough to pass (GREEN)
   - Refactor for clarity (REFACTOR)
   - Run verification command
   - Update `STATE.md`
4. Move to next slice only after all tests pass
5. After Slice 10, run full regression test suite

### For Reviewers
1. Read [TOPOLOGY_TEMPLATE_ADMIN_DESIGN.md](TOPOLOGY_TEMPLATE_ADMIN_DESIGN.md) (architecture)
2. Review [TOPOLOGY_TEMPLATE_ADMIN_IMPLEMENTATION_PLAN.md](TOPOLOGY_TEMPLATE_ADMIN_IMPLEMENTATION_PLAN.md) (implementation approach)
3. Check `STATE.md` for progress
4. Review code changes after each slice

---

## Success Criteria

✅ **Implementation is complete when:**
- All 10 slices done
- ~93 tests passing
- No regressions in existing tests (826+ tests)
- Type checking passes (`mypy`)
- Linting passes (`ruff`)
- Feature ready for code review

---

## Questions?

Refer to the appropriate document:
- **"What should the feature do?"** → TOPOLOGY_TEMPLATE_ADMIN_DESIGN.md (Section 3: Acceptance Criteria)
- **"How do I implement Slice X?"** → TOPOLOGY_TEMPLATE_ADMIN_IMPLEMENTATION_PLAN.md (Slice X checklist)
- **"What files do I need to change?"** → TOPOLOGY_TEMPLATE_ADMIN_DESIGN.md (Section 4: Files to Create/Modify)
- **"What's the architecture?"** → TOPOLOGY_TEMPLATE_ADMIN_DESIGN.md (Section 2: Architecture Overview)
- **"How do I verify my work?"** → TOPOLOGY_TEMPLATE_ADMIN_IMPLEMENTATION_PLAN.md (Verification commands)

---

**Document Version:** 1.0  
**Status:** Ready for Implementation  
**Last Updated:** September 26, 2026
