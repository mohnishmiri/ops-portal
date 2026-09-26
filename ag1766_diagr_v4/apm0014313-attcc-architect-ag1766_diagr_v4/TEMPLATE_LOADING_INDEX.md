# Template Loading Documentation Index

## Quick Answer

**Question:** What is the path in the app which we use to load new diagram templates into the app?

**Answer:** There are **two paths**:

1. **Path 1 — User-Uploaded Templates** (Card 1 → Card 2)
   - Route: `POST /applications/{app_id}/intakes/{intake_id}/topology/upload-base`
   - No code changes needed
   - User uploads any `.drawio` file
   - Variant selection stored with upload

2. **Path 2 — Bundled Standard Templates** (Card 3)
   - Route: `POST /applications/{app_id}/intakes/{intake_id}/topology/generate-standard`
   - Requires code changes to add new variants
   - Pre-packaged, version-controlled templates
   - Shipped with the application

---

## Documentation Map

### 1. **TEMPLATE_LOADING_SUMMARY.md** ← START HERE
**Length:** 273 lines | **Time:** 5 minutes

Executive summary with:
- Quick answer to your question
- Architectural comparison table
- Step-by-step guide to adding templates
- Key files and locations
- Verification status

**Best for:** Getting oriented, understanding the big picture

---

### 2. **TEMPLATE_LOADING_QUICK_REFERENCE.md**
**Length:** 276 lines | **Time:** 10 minutes

Quick lookup guide with:
- Two-path comparison
- Step-by-step instructions for both paths
- Variant mapping table
- Database schema (simplified)
- Common operations with code examples
- Troubleshooting guide

**Best for:** Finding specific information quickly, copying code snippets

---

### 3. **TEMPLATE_LOADING_ARCHITECTURE.md**
**Length:** 763 lines | **Time:** 30 minutes

Comprehensive architectural review with:
- Complete end-to-end trace of both paths
- Detailed code references with line numbers
- Database schema (full)
- Data flow diagrams
- Security considerations
- Operational guidance
- Troubleshooting procedures

**Best for:** Deep understanding, implementation details, operational decisions

---

### 4. **TEMPLATE_LOADING_FLOW_DIAGRAMS.txt**
**Length:** 400 lines | **Time:** 10 minutes

ASCII flow diagrams showing:
- Path 1 step-by-step (upload + generate)
- Path 2 step-by-step (select variant + generate)
- Variant mapping
- Database schema relationships
- Key files and their locations

**Best for:** Visual learners, understanding data flow

---

### 5. **investigation-report-20260926.md**
**Length:** 220 lines | **Time:** 15 minutes

Technical investigation report with:
- Root cause analysis of UI generation issues
- Proof that both paths work correctly
- Execution path comparison
- Artifact comparison
- Evidence-based conclusions

**Best for:** Understanding why both paths exist, verification of fixes

---

### 6. **HANDOFF_20250925.md**
**Length:** 372 lines | **Time:** 20 minutes

Complete handoff document with:
- Implementation summary
- All 122 new tests
- UI test matrix (18 tests)
- Known issues and fixes
- Critical FK violation bug (fixed)
- Token replacement gap (documented)

**Best for:** Understanding the complete implementation, testing procedures

---

## Reading Paths by Role

### For a New Developer
1. Start: **TEMPLATE_LOADING_SUMMARY.md** (5 min)
2. Then: **TEMPLATE_LOADING_QUICK_REFERENCE.md** (10 min)
3. Reference: **TEMPLATE_LOADING_ARCHITECTURE.md** (as needed)

### For a DevOps/Operations Engineer
1. Start: **TEMPLATE_LOADING_SUMMARY.md** (5 min)
2. Then: **TEMPLATE_LOADING_ARCHITECTURE.md** → Operational Guidance section (10 min)
3. Reference: **TEMPLATE_LOADING_QUICK_REFERENCE.md** → Troubleshooting (as needed)

### For a Technical Architect
1. Start: **TEMPLATE_LOADING_ARCHITECTURE.md** (30 min)
2. Reference: **TEMPLATE_LOADING_FLOW_DIAGRAMS.txt** (10 min)
3. Verify: **investigation-report-20260926.md** (15 min)

### For a QA/Tester
1. Start: **TEMPLATE_LOADING_SUMMARY.md** (5 min)
2. Then: **HANDOFF_20250925.md** → UI Test Matrix section (15 min)
3. Reference: **TEMPLATE_LOADING_QUICK_REFERENCE.md** → Common Operations (as needed)

---

## Key Sections by Topic

### "How do I load a new template?"
- **TEMPLATE_LOADING_SUMMARY.md** → "To Load a New Diagram Template"
- **TEMPLATE_LOADING_QUICK_REFERENCE.md** → "Adding a New Template"

### "What are the differences between the two paths?"
- **TEMPLATE_LOADING_SUMMARY.md** → "Architectural Comparison"
- **TEMPLATE_LOADING_ARCHITECTURE.md** → "Comparative Analysis"

### "Where is the code?"
- **TEMPLATE_LOADING_SUMMARY.md** → "Key Files and Locations"
- **TEMPLATE_LOADING_ARCHITECTURE.md** → "Appendix A: File References"
- **TEMPLATE_LOADING_QUICK_REFERENCE.md** → "Key Files"

### "How does the database work?"
- **TEMPLATE_LOADING_QUICK_REFERENCE.md** → "Database Schema (Simplified)"
- **TEMPLATE_LOADING_ARCHITECTURE.md** → "Database Schema"

### "What if something breaks?"
- **TEMPLATE_LOADING_QUICK_REFERENCE.md** → "Troubleshooting"
- **TEMPLATE_LOADING_ARCHITECTURE.md** → "Operational Guidance" → "Troubleshooting Template Issues"

### "How do I test this?"
- **HANDOFF_20250925.md** → "UI Test Matrix"
- **TEMPLATE_LOADING_QUICK_REFERENCE.md** → "Common Operations" → "Test"

### "What was fixed recently?"
- **investigation-report-20260926.md** → "Two Proven Root Causes"
- **HANDOFF_20250925.md** → "Critical Bug Identified (FK Violation)"

---

## File Locations

All documentation is in the repository root or `docs/` directory:

```
C:\GitHub\aws_diag_v4_1\aws_diag_v4\
├── TEMPLATE_LOADING_SUMMARY.md              ← START HERE
├── TEMPLATE_LOADING_INDEX.md                ← You are here
├── docs/
│   ├── TEMPLATE_LOADING_ARCHITECTURE.md     ← Full details
│   ├── TEMPLATE_LOADING_QUICK_REFERENCE.md  ← Quick lookup
│   ├── TEMPLATE_LOADING_FLOW_DIAGRAMS.txt   ← Visual diagrams
│   ├── investigation-report-20260926.md     ← Technical analysis
│   └── ...
├── HANDOFF_20250925.md                      ← Implementation summary
└── ...
```

---

## Code Locations

### Route Handlers (HTTP Entry Points)
- `src/migration_intake/web/routes/topology.py`
  - Line 229: `upload_base_diagram()` — POST /topology/upload-base
  - Line 366: `generate_from_standard_template()` — POST /topology/generate-standard

### Services (Business Logic)
- `src/migration_intake/application/services/topology_generation.py`
  - Line 116: `upload_base_diagram()` — Upload and persist
  - Line 421: `generate_from_standard_template()` — Load and generate

### Template Loader
- `src/migration_intake/topology/template_loader.py`
  - Line 81: `load_bundled_template()` — Load and extract variant

### Bundled Template
- `src/migration_intake/topology/config/templates/outpost_v1.7.drawio`
  - Multi-tab master template (5 tabs)

### HAF Profiles
- `src/migration_intake/topology/config/haf_profiles/`
  - `outpost_v1.json` — Legacy (13 roles)
  - `outpost_v1_basic.json` — Without LBs (22 roles)
  - `outpost_v1_tlgw.json` — tLGW (23 roles)
  - `outpost_v1_f5.json` — F5 (23 roles)
  - `outpost_v1_hadr.json` — HA/DR (25 roles)

### UI Templates
- `src/migration_intake/web/templates/topology/index.html`
  - Card 1: Upload form
  - Card 2: Generate from uploaded
  - Card 3: Generate from bundled

---

## Quick Facts

| Fact | Details |
|------|---------|
| **Two paths** | User-uploaded (Path 1) and bundled (Path 2) |
| **Entry points** | Card 1 (upload), Card 2 (generate from upload), Card 3 (generate from bundled) |
| **HTTP routes** | POST /topology/upload-base, POST /topology/generate, POST /topology/generate-standard |
| **Variants** | basic, tlgw, f5, hadr (4 variants) |
| **Database** | topo_base (templates), gen_runs (generation records) |
| **Storage** | evidence/topology/base_diagrams/, evidence/topology/generated/ |
| **Tests** | 826 passing (673 topology + 153 web) |
| **E2E verified** | 27/27 Playwright tests passing |
| **Code changes for new variant** | 5 files (template, loader, profiles, service, UI) |
| **Code changes for user upload** | None (built-in) |

---

## Status

✅ **Complete and Verified**
- Both paths implemented and tested
- 826 unit tests passing
- 27/27 E2E tests passing
- All documentation complete
- Production-ready

---

## Next Steps

1. **To understand the system:** Read TEMPLATE_LOADING_SUMMARY.md (5 min)
2. **To add a new template:** Follow TEMPLATE_LOADING_QUICK_REFERENCE.md (15 min)
3. **For deep dive:** Read TEMPLATE_LOADING_ARCHITECTURE.md (30 min)
4. **For troubleshooting:** Use TEMPLATE_LOADING_QUICK_REFERENCE.md → Troubleshooting section

---

## Questions?

Refer to the appropriate documentation section above, or contact the development team with specific questions about:
- Implementation details → TEMPLATE_LOADING_ARCHITECTURE.md
- Code locations → TEMPLATE_LOADING_SUMMARY.md → Key Files
- Troubleshooting → TEMPLATE_LOADING_QUICK_REFERENCE.md → Troubleshooting
- Testing → HANDOFF_20250925.md → UI Test Matrix
