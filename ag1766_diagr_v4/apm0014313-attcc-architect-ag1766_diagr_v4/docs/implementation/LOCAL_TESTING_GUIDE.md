# HAF Topology Pipeline — Local Development and Testing Guide

Complete guide for running, testing, and validating the HAF topology pipeline implementation locally.

---

## 1. Prerequisites

- **Python 3.13+** (project requires `>=3.13,<3.14`)
- **Git** for version control
- **SQLite** (included with Python)
- **Virtual environment** (`.venv` directory should exist)
- **Port 8000** available for local app server

---

## 2. Quick Start — Running the App Locally

### Step 1: Activate the virtual environment

```bash
cd C:\GitHub\aws_diag_v4_1\aws_diag_v4
source .venv/Scripts/activate  # On Windows: .venv\Scripts\activate
```

### Step 2: Start the development server

```bash
python -m uvicorn migration_intake.main:get_app --factory --host 127.0.0.1 --port 8000 --reload
```

Expected output:
```
INFO:     Will watch for changes in these directories: ['C:\GitHub\aws_diag_v4_1\aws_diag_v4']
INFO:     Uvicorn running on http://127.0.0.1:8000 (Press CTRL+C to quit)
INFO:     Started reloader process [PID] using WatchFiles
```

### Step 3: Access the app

Open your browser and navigate to:
```
http://127.0.0.1:8000/applications/
```

You should see the Applications list page with the CCPM application visible.

---

## 3. Verifying the CCPM Application and Interfaces

### Step 1: Navigate to CCPM application

1. Go to `http://127.0.0.1:8000/applications/`
2. Find the **CCPM** application (correlation ID: 18678)
3. Click on it to view the application details

### Step 2: Verify interfaces are loaded

1. In the CCPM application view, navigate to the **Interfaces** section
2. Verify that you see **55 interface records** across multiple locations:
   - **AWS**: ~9 interfaces
   - **Azure**: ~22 interfaces
   - **Midrange**: ~20 interfaces
   - **Unknown**: ~4 interfaces

### Step 3: Check interface details

Each interface should display:
- Interface name
- Direction (Inbound, Outbound, or Bidirectional)
- Location (AWS, Azure, Midrange, or Unknown)
- Application name (remote peer)

---

## 4. Running the Automated Test Suite

### Step 1: Run all topology tests

```bash
cd C:\GitHub\aws_diag_v4_1\aws_diag_v4
python -m pytest tests/unit/topology/ -v
```

Expected result: **419 tests passed**

### Step 2: Run specific test modules

**HAF Pipeline tests** (core implementation):
```bash
python -m pytest tests/unit/topology/test_haf_pipeline.py -v
```

**HAF Styles tests** (style registry):
```bash
python -m pytest tests/unit/topology/test_haf_styles.py -v
```

**Guide Policy tests** (location aliases):
```bash
python -m pytest tests/unit/topology/test_guide_policy.py -v
```

**E2E tests** (real template + real DB):
```bash
python -m pytest tests/unit/topology/test_haf_e2e.py -v
```

### Step 3: Run with coverage

```bash
python -m pytest tests/unit/topology/ --cov=src/migration_intake/topology --cov-report=html
```

Coverage report will be generated in `htmlcov/index.html`.

---

## 5. Testing the HAF Pipeline Directly

### Step 1: Load the input template

```python
from pathlib import Path

template_path = Path("docs/development/topo_9_24/AWS__input_Outpost_Topology_UNRESOLVED_UNRESOLVED-v1.7.drawio")
template_bytes = template_path.read_bytes()

print(f"Template size: {len(template_bytes)} bytes")
print(f"Template loaded: {template_bytes[:100]}")
```

### Step 2: Query the CCPM application from the local SQLite DB

```python
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

# Connect to local SQLite DB
engine = create_engine("sqlite:///migration_intake.db")

with Session(engine) as session:
    # Find CCPM application
    result = session.execute(text("""
        SELECT a.id, a.display_name, COUNT(i.id) as interface_count
        FROM applications a
        LEFT JOIN interfaces i ON i.application_id = a.id
        WHERE a.display_name = 'CCPM'
        GROUP BY a.id, a.display_name
    """)).first()
    
    if result:
        app_id, app_name, interface_count = result
        print(f"Found {app_name} (ID: {app_id}) with {interface_count} interfaces")
    else:
        print("CCPM application not found")
```

### Step 3: Run the HAF pipeline

```python
from migration_intake.topology.haf_service import generate_haf_topology

# Generate topology
result = generate_haf_topology(
    session=session,
    intake_id=intake_id,  # From previous query
    profile_id="OUTPOST_V1",
    template_bytes=template_bytes,
)

print(f"Success: {result.success}")
print(f"Mutations applied: {len(result.mutations)}")
print(f"Gaps found: {len(result.gaps)}")
print(f"Output size: {len(result.filled_xml)} bytes")

# Save output for inspection
with open("ccpm_output.drawio", "wb") as f:
    f.write(result.filled_xml)

print("Output saved to ccpm_output.drawio")
```

### Step 4: Inspect the output

1. Download or copy `ccpm_output.drawio` to your local machine
2. Open it in **draw.io** (https://draw.io) or **diagrams.net**
3. Verify:
   - All interface slots are populated with interface names
   - No `UNRESOLVED` or `NEEDS` placeholders remain
   - Layout is preserved from the input template
   - All 55 interfaces are distributed across location groups

---

## 6. Detailed Extraction Verification

Run this script to verify the extraction pipeline:

```python
from migration_intake.topology.haf_extractor import extract_application_interfaces
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

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
        
        # Extract interfaces
        interfaces = extract_application_interfaces(session, intake_id)
        
        print(f"Total interfaces: {len(interfaces)}")
        
        # Group by location
        by_location = {}
        for iface in interfaces:
            loc = iface.location or "UNKNOWN"
            if loc not in by_location:
                by_location[loc] = []
            by_location[loc].append(iface)
        
        for location in sorted(by_location.keys()):
            ifaces = by_location[location]
            print(f"\n{location}: {len(ifaces)} interfaces")
            for iface in ifaces[:5]:  # Show first 5
                print(f"  - {iface.app_name} ({iface.direction})")
            if len(ifaces) > 5:
                print(f"  ... and {len(ifaces) - 5} more")
```

---

## 7. Structural Safety Verification

Run this script to verify the generated XML is valid and safe:

```python
from migration_intake.topology.renderer.core import parse_diagram_safely
import xml.etree.ElementTree as ET

# Load the generated output
with open("ccpm_output.drawio", "rb") as f:
    output_xml = f.read()

# Parse safely (enforces XML security limits)
try:
    root = parse_diagram_safely(output_xml)
    print("✓ XML is valid and safe")
    
    # Count cells
    cells = root.findall(".//mxCell")
    print(f"✓ Total cells: {len(cells)}")
    
    # Verify no UNRESOLVED placeholders remain
    unresolved_count = 0
    for cell in cells:
        value = cell.get("value", "")
        if "UNRESOLVED" in value or "NEEDS" in value:
            unresolved_count += 1
            print(f"  ⚠ Found placeholder: {value[:50]}")
    
    if unresolved_count == 0:
        print("✓ No UNRESOLVED or NEEDS placeholders found")
    else:
        print(f"✗ Found {unresolved_count} placeholders")
    
except Exception as e:
    print(f"✗ XML parsing failed: {e}")
```

---

## 8. UI-Based Testing

### Step 1: Access the topology generation UI (when implemented)

Once the HAF pipeline is wired into the web routes:

```
POST /api/topology/generate
Content-Type: multipart/form-data

intake_id: <intake_id>
profile_id: OUTPOST_V1
template: <file upload>
```

### Step 2: Manual testing via UI

1. Navigate to `http://127.0.0.1:8000/applications/`
2. Find CCPM application
3. Click "Generate Topology" (when button is added)
4. Upload the input template file
5. Select profile: "OUTPOST_V1"
6. Click "Generate"
7. Download the resulting `.drawio` file
8. Open in draw.io to verify

---

## 9. Expected Test Results Summary

| Test Suite | Count | Status | Notes |
|---|---|---|---|
| HAF Pipeline | 53 | ✓ PASS | Core implementation tests |
| HAF Styles | 8 | ✓ PASS | Style registry tests |
| Guide Policy | 4 | ✓ PASS | Location alias tests |
| E2E | 2 | ✓ PASS | Real template + real DB tests |
| **Total** | **419** | **✓ PASS** | All topology tests passing |

---

## 10. Troubleshooting

### Issue: "ModuleNotFoundError: No module named 'migration_intake'"

**Solution**: Ensure virtual environment is activated and the package is installed:
```bash
source .venv/Scripts/activate
pip install -e ".[dev]"
```

### Issue: "sqlite3.OperationalError: no such table: applications"

**Solution**: The local SQLite DB may not be initialized. Run migrations:
```bash
alembic upgrade head
```

### Issue: "CCPM application not found in database"

**Solution**: The test data may not be loaded. Check if the app has been used to create intakes:
```bash
python -c "from sqlalchemy import create_engine, text; from sqlalchemy.orm import Session; engine = create_engine('sqlite:///migration_intake.db'); session = Session(engine); print(session.execute(text('SELECT COUNT(*) FROM applications')).scalar())"
```

### Issue: Port 8000 already in use

**Solution**: Use a different port:
```bash
python -m uvicorn migration_intake.main:get_app --factory --host 127.0.0.1 --port 8001 --reload
```

### Issue: "interface_epoch" column not found

**Solution**: The local SQLite DB predates migration 0022. The extractor uses a `text()` query to avoid this, but if you want to upgrade:
```bash
alembic upgrade head
```

---

## 11. Next Steps

1. **Run the automated test suite** to verify all 419 tests pass
2. **Verify CCPM interfaces** in the UI at `http://127.0.0.1:8000/applications/`
3. **Run the HAF pipeline** against the real CCPM data using the Python script in section 5
4. **Inspect the output** in draw.io to verify interface population
5. **Wire the pipeline into the UI** (Phase 2 work) to enable end-user topology generation

---

## 12. Key Files and Locations

| File | Purpose |
|---|---|
| `src/migration_intake/topology/haf_pipeline.py` | Core HAF pipeline implementation |
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

## 13. Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│                    HAF Topology Pipeline                     │
├─────────────────────────────────────────────────────────────┤
│                                                               │
│  Input Template (draw.io XML)                                │
│         ↓                                                     │
│  ┌──────────────────────────────────────────────────────┐   │
│  │ haf_pipeline.parse_haf_template()                    │   │
│  │ - Validate XML (security limits)                     │   │
│  │ - Parse structure                                    │   │
│  └──────────────────────────────────────────────────────┘   │
│         ↓                                                     │
│  ┌──────────────────────────────────────────────────────┐   │
│  │ haf_extractor.extract_application_interfaces()       │   │
│  │ - Query SQLite DB for CCPM interfaces               │   │
│  │ - Group by location (AWS, Azure, Midrange, Unknown) │   │
│  │ - Normalize direction (Inbound, Outbound, Bidir)    │   │
│  └──────────────────────────────────────────────────────┘   │
│         ↓                                                     │
│  ┌──────────────────────────────────────────────────────┐   │
│  │ haf_pipeline.fill_interface_regions()                │   │
│  │ - Locate interface slot cells in template           │   │
│  │ - Populate with extracted interfaces                │   │
│  │ - Apply rendering mode (MULTILINE_TEXT or GENERATE) │   │
│  └──────────────────────────────────────────────────────┘   │
│         ↓                                                     │
│  Output Diagram (draw.io XML)                                │
│  - All interface slots populated                             │
│  - No UNRESOLVED/NEEDS placeholders                          │
│  - Ready for draw.io inspection                              │
│                                                               │
└─────────────────────────────────────────────────────────────┘
```

---

## 14. Testing Workflow

### Automated Testing (CI/CD Ready)

```bash
# Run all topology tests
python -m pytest tests/unit/topology/ -v

# Run specific slice tests
python -m pytest tests/unit/topology/test_haf_pipeline.py::test_parse_haf_template_safely -v
python -m pytest tests/unit/topology/test_haf_pipeline.py::test_generate_subcells_deterministic -v
python -m pytest tests/unit/topology/test_haf_e2e.py -v
```

### Manual Testing (Development)

1. Start the app: `python -m uvicorn migration_intake.main:get_app --factory --host 127.0.0.1 --port 8000 --reload`
2. Verify CCPM in UI: `http://127.0.0.1:8000/applications/`
3. Run pipeline script (section 5)
4. Open output in draw.io
5. Verify interface population and no placeholders

---

## 15. Known Limitations and Gaps

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
