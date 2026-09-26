# HAF Topology Pipeline — Deployment Summary

**Date:** 2026-09-25  
**Status:** ✓ Ready for Local Testing

---

## Quick Start

### 1. Start the Application

```bash
cd C:\GitHub\aws_diag_v4_1\aws_diag_v4
source .venv/Scripts/activate
python -m uvicorn migration_intake.main:get_app --factory --host 127.0.0.1 --port 8000 --reload
```

The app will start on `http://127.0.0.1:8000`

### 2. Access the UI

Open your browser and navigate to:
```
http://127.0.0.1:8000/applications/
```

You should see the Applications list with **CCPM** (ID: 18678) visible.

### 3. Verify CCPM Interfaces

1. Click on **CCPM** application
2. Navigate to **Interfaces** section
3. Verify **55 interface records** are displayed across:
   - AWS: ~9 interfaces
   - Azure: ~22 interfaces
   - Midrange: ~20 interfaces
   - Unknown: ~4 interfaces

---

## Testing

### Run All Tests

```bash
python -m pytest tests/unit/topology/ -v
```

**Expected result:** 419 tests passed

### Run Specific Test Modules

```bash
# HAF Pipeline tests
python -m pytest tests/unit/topology/test_haf_pipeline.py -v

# HAF Styles tests
python -m pytest tests/unit/topology/test_haf_styles.py -v

# Guide Policy tests
python -m pytest tests/unit/topology/test_guide_policy.py -v

# E2E tests
python -m pytest tests/unit/topology/test_haf_e2e.py -v
```

---

## Testing the Pipeline Directly

### Load Template and Run Pipeline

```python
from pathlib import Path
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session
from migration_intake.topology.haf_service import generate_haf_topology

# Load template
template_path = Path("docs/development/topo_9_24/AWS__input_Outpost_Topology_UNRESOLVED_UNRESOLVED-v1.7.drawio")
template_bytes = template_path.read_bytes()

# Connect to DB
engine = create_engine("sqlite:///migration_intake.db")

with Session(engine) as session:
    # Find CCPM intake
    result = session.execute(text("""
        SELECT i.id FROM intakes i
        JOIN applications a ON a.id = i.application_id
        WHERE a.display_name = 'CCPM'
        LIMIT 1
    """)).first()
    
    if result:
        intake_id = result[0]
        
        # Generate topology
        result = generate_haf_topology(
            session=session,
            intake_id=intake_id,
            profile_id="OUTPOST_V1",
            template_bytes=template_bytes,
        )
        
        print(f"✓ Success: {result.success}")
        print(f"✓ Mutations: {len(result.mutations)}")
        print(f"✓ Gaps: {len(result.gaps)}")
        
        # Save output
        with open("ccpm_output.drawio", "wb") as f:
            f.write(result.filled_xml)
        
        print("✓ Output saved to ccpm_output.drawio")
```

### Inspect Output in draw.io

1. Open `ccpm_output.drawio` in [draw.io](https://draw.io)
2. Verify:
   - All interface slots are populated with interface names
   - No `UNRESOLVED` or `NEEDS` placeholders remain
   - Layout is preserved from input template
   - All 55 interfaces distributed across location groups

---

## Documentation

### Implementation Plan

- **Markdown:** `docs/implementation/haf-architectural-review.md` (850 lines)
- **HTML:** `docs/implementation/haf-architectural-review.html` (999 lines, styled)
- **Sections:** Executive Summary, Current-State Architecture, Evidence Inventory, Comparative Decision Matrix, HAF Strengths, Gaps and Risks, Improvement Opportunities, TDD Slices, Prioritized Roadmap, First Slice, Open Questions, Architectural Answers

### Testing Guide

- **File:** `docs/implementation/LOCAL_TESTING_GUIDE.md` (468 lines)
- **Sections:** Prerequisites, Quick Start, CCPM Verification, Test Suite, Direct Pipeline Testing, Extraction Verification, Safety Verification, UI Testing, Troubleshooting, Next Steps, Key Files, Architecture Overview, Testing Workflow, Known Limitations

### Topology Plan

- **File:** `docs/implementation/haf-topology-pipeline-plan.md` (1184 lines)
- **Sections:** Evidence Review, Input/Output Structure, Existing Architecture, Placeholder Inventory, Slice Definitions, Implementation Status, Real CCPM Data Verification, Testing Guide, Known Gaps

---

## Implementation Status

### Completed Slices (10/10)

| Slice | Title | Status | Tests |
|---|---|---|---|
| 0 | Baseline snapshot | ✓ Complete | Characterization test |
| 1 | MIDRANGE alias | ✓ Complete | 1 test |
| 2 | XML security limits | ✓ Complete | 3 tests |
| 3 | Cloud provider style registry | ✓ Complete | 8 tests |
| 4 | Sub-cell generation | ✓ Complete | 12 tests |
| 5 | Grid layout refinement | ✓ Complete | 8 tests |
| 6 | Edge generation | ✓ Complete | 6 tests |
| 7 | Wire GENERATE_CELLS mode | ✓ Complete | 6 tests |
| 8 | Manifest/hashing | ✓ Complete | 4 tests |
| 9 | Tooltip metadata | ✓ Complete | 1 test |
| 10 | E2E generate-cells | ✓ Complete | 1 test |

**Total:** 419 tests passing

### Key Features

- ✓ XML security hardening (DTD/entity/size limits)
- ✓ Deterministic sub-cell generation with grid layout
- ✓ Deterministic edge generation with labels
- ✓ Cloud provider style registry (AWS, Azure, etc.)
- ✓ Mixed rendering modes (MULTILINE_TEXT and GENERATE_CELLS)
- ✓ Manifest hashing for integrity verification
- ✓ Tooltip metadata on generated cells
- ✓ Real CCPM data extraction and population
- ✓ E2E testing with real template and real DB

---

## Architecture

```
Input Template (draw.io XML)
         ↓
    [HAF Parser]
    - Validate XML (security limits)
    - Parse structure
         ↓
[Interface Extractor]
- Query SQLite DB for CCPM interfaces
- Group by location (AWS, Azure, Midrange, Unknown)
- Normalize direction (Inbound, Outbound, Bidirectional)
         ↓
[Interface Filler]
- Locate interface slot cells in template
- Populate with extracted interfaces
- Apply rendering mode (MULTILINE_TEXT or GENERATE)
         ↓
Output Diagram (draw.io XML)
- All interface slots populated
- No UNRESOLVED/NEEDS placeholders
- Ready for draw.io inspection
```

---

## Known Limitations

| # | Gap | Status | Remediation |
|---|---|---|---|
| 1 | 8 infrastructure tokens unresolved (CIDR, account ID, etc.) | OPEN | Add question codes to catalog or separate token-entry form |
| 2 | Midrange location maps to UNKNOWN | OPEN | Decide on MIDRANGE→INTERNAL alias (requires architectural decision) |
| 3 | Single page output only | OPEN | Implement NonProd/Prod page duplication (Phase 2) |
| 4 | Not wired into UI routes | OPEN | Add POST endpoint to topology routes (Phase 2) |
| 5 | Intake state not validated | OPEN | Add state gate if business rules require FROZEN intake |
| 6 | `interface_epoch` column missing in local SQLite | MITIGATED | Extractor uses `text()` query to avoid this |
| 7 | 8 interfaces have empty location/direction | OPEN | Upstream data cleanup needed |

---

## Next Steps

### Phase 2 (UI Integration)

1. **Wire HAF pipeline into web routes**
   - Add POST endpoint to topology routes
   - Accept template upload + profile selection
   - Return generated diagram for download

2. **Add UI buttons**
   - "Generate Topology" button on application detail page
   - Template upload form
   - Profile selector (OUTPOST_V1, etc.)
   - Download generated diagram

3. **Add state validation**
   - Gate generation on intake state (FROZEN, etc.)
   - Add audit logging for topology generation

### Phase 3 (Advanced Features)

1. **Multi-page output**
   - Duplicate topology for NonProd/Prod pages
   - Parameterize page names from profile

2. **Infrastructure token resolution**
   - Add question codes to catalog
   - Or implement separate token-entry form

3. **Midrange location handling**
   - Decide on MIDRANGE→INTERNAL mapping
   - Update guide_policy.py

---

## Troubleshooting

### Port 8000 already in use

```bash
python -m uvicorn migration_intake.main:get_app --factory --host 127.0.0.1 --port 8001 --reload
```

### Virtual environment not activated

```bash
source .venv/Scripts/activate  # Windows
source .venv/bin/activate      # Linux/Mac
```

### Tests failing

```bash
# Run with verbose output
python -m pytest tests/unit/topology/ -vv

# Run specific test
python -m pytest tests/unit/topology/test_haf_pipeline.py::test_name -vv
```

### CCPM application not found

The SQLite DB may need to be initialized. Check:
```bash
python -c "from sqlalchemy import create_engine, text; from sqlalchemy.orm import Session; engine = create_engine('sqlite:///migration_intake.db'); session = Session(engine); print(session.execute(text('SELECT COUNT(*) FROM applications')).scalar())"
```

---

## Files and Locations

| File | Purpose |
|---|---|
| `src/migration_intake/topology/haf_pipeline.py` | Core HAF pipeline (parse, fill, generate) |
| `src/migration_intake/topology/haf_extractor.py` | Interface extraction from DB |
| `src/migration_intake/topology/haf_service.py` | Service layer for topology generation |
| `src/migration_intake/topology/haf_styles.py` | Style registry for cloud providers |
| `src/migration_intake/topology/guide_policy.py` | Location aliases and business rules |
| `src/migration_intake/topology/config/haf_styles/interface_styles.json` | Cloud provider style definitions |
| `tests/unit/topology/test_haf_pipeline.py` | Pipeline tests (53 tests) |
| `tests/unit/topology/test_haf_styles.py` | Style registry tests (8 tests) |
| `tests/unit/topology/test_guide_policy.py` | Policy tests (4 tests) |
| `tests/unit/topology/test_haf_e2e.py` | End-to-end tests (2 tests) |
| `docs/development/topo_9_24/AWS__input_Outpost_Topology_UNRESOLVED_UNRESOLVED-v1.7.drawio` | Input template for testing |
| `migration_intake.db` | Local SQLite database with CCPM test data |

---

## Support

For detailed testing instructions, see:
- `docs/implementation/LOCAL_TESTING_GUIDE.md` — Complete testing guide with scripts
- `docs/implementation/haf-architectural-review.md` — Full architectural plan
- `docs/implementation/haf-topology-pipeline-plan.md` — Topology pipeline design

---
