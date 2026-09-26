# Catalog Creation and Bootstrap Guide

## Overview

The catalog is the authoritative source of all questions in the Migration Intake application. It defines:
- Question codes (e.g., APP-001, NET-006)
- Question text and response types
- Required/conditional logic
- Preferred and fallback sources
- Owner roles and target outputs

## Catalog Source File

**Location:** `src/migration_intake/catalog/data/catalog-0.2.0.csv`

**Format:** CSV (Comma-Separated Values)

**Columns:**
```
Question_ID,Section,Collection_Mode,Question_Text,Response_Type,Allowed_Values_or_Unit,Required_Level,Required_When,Preferred_Source,Fallback_Sources,Default_Owner,Target_Outputs,Destination
```

### Column Descriptions

| Column | Purpose | Example |
|--------|---------|---------|
| `Question_ID` | Unique question code | `APP-001`, `NET-006` |
| `Section` | Section grouping | `Application`, `Network`, `Database` |
| `Collection_Mode` | How data is collected | `AUTO_IMPORT`, `HITL_OWNER`, `ARCHITECT_DECISION` |
| `Question_Text` | Full question text | "What business function does the application provide?" |
| `Response_Type` | Type of answer expected | `LONG_TEXT`, `BOOLEAN`, `PEOPLE_LIST`, `REGISTER_STATUS` |
| `Allowed_Values_or_Unit` | Valid values or units | `ACTIVE\|MAINTENANCE\|RETIRING`, `ms\|Mbps\|Gbps` |
| `Required_Level` | Requirement status | `REQUIRED`, `CONDITIONAL`, `OPTIONAL` |
| `Required_When` | Condition for requirement | `Application has interactive users` |
| `Preferred_Source` | Primary source system | `UAQ`, `iTAP`, `Interface Tracking` |
| `Fallback_Sources` | Alternative sources | `Deep Dive Notes\|PORT` |
| `Default_Owner` | Responsible role | `Application Owner`, `Network Architect` |
| `Target_Outputs` | Destination systems | `ADS\|DDD`, `TOPOLOGY` |
| `Destination` | Output mapping | `03_Answers`, `05_Interfaces` |

## Catalog Compilation Process

### Step 1: Source Validation
The CSV file is validated for:
- Required columns present
- No duplicate question IDs
- Valid response types
- Proper condition syntax

### Step 2: Compilation
File: `src/migration_intake/catalog/compiler.py`

The `CatalogCompiler` class:
1. Reads the CSV file
2. Parses each row into a `QuestionDefinition`
3. Compiles applicability conditions (if conditional)
4. Validates response types
5. Generates a SHA256 hash of the source content
6. Creates a `CatalogRelease` object

```python
from migration_intake.catalog.compiler import CatalogCompiler

compiler = CatalogCompiler()
result = compiler.compile(
    csv_content,
    version="0.2.0",
    source_filename="catalog-0.2.0.csv"
)

if result.release:
    print(f"Compiled {result.report.question_count} questions")
    print(f"Sections: {result.report.section_count}")
else:
    print(f"Compilation failed: {result.report.diagnostics}")
```

### Step 3: Publication
File: `src/migration_intake/catalog/bootstrap.py`

The compiled catalog is published to the database using `CatalogPublicationService`:

```python
from migration_intake.catalog.bootstrap import publish_catalog

release = publish_catalog(session_factory, source_path)
print(f"Catalog {release['semantic_version']} published (ID: {release['id']})")
```

## Bootstrap Command

### How to Bootstrap the Catalog

**Command:**
```bash
python -c "from migration_intake.catalog.bootstrap import main; main()"
```

Or via the installed script:
```bash
migration-intake-bootstrap-catalog
```

**What it does:**
1. Reads `src/migration_intake/catalog/data/catalog-0.2.0.csv`
2. Compiles the CSV into a structured catalog
3. Publishes the catalog to the database
4. Returns the release ID and version

**Output:**
```
Catalog 0.2.0 is published (release 13eacdac-ba33-4553-a665-5c1deba02ac8).
```

### Idempotent Operation
The bootstrap command is idempotent - running it multiple times with the same source file will:
- Return the same release ID
- Not create duplicate entries
- Verify the source SHA256 hash matches

## Database Storage

### Tables Created

**`cat_releases`** - Catalog versions
- `id` - Release UUID
- `semantic_version` - Version (e.g., "0.2.0")
- `source_filename` - Source file name
- `source_sha256` - Hash of source content
- `pub_state` - Publication state (DRAFT, PUBLISHED, RETIRED)
- `catalog_hash` - Hash of compiled catalog
- `compiler_report` - JSON compilation diagnostics

**`cat_sections`** - Question sections
- `id` - Section UUID
- `catalog_id` - Reference to catalog release
- `section_code` - Code (e.g., "Application")
- `display_name` - Display name
- `display_order` - Sort order

**`cat_questions`** - Individual questions
- `id` - Question UUID
- `section_id` - Reference to section
- `question_code` - Code (e.g., "APP-001")
- `question_text` - Full question text
- `response_type` - Type of response
- `required_level` - REQUIRED, CONDITIONAL, OPTIONAL
- `collection_mode` - How data is collected
- `condition_ast` - Compiled condition logic (if conditional)
- `response_schema_version` - Response type version
- `is_active` - Whether question is active

## Standard Developer Setup

After cloning the repository:

```bash
# 1. Install dependencies
pip install -e ".[dev]"

# 2. Run database migrations
python -m alembic upgrade head

# 3. Bootstrap the catalog
python -c "from migration_intake.catalog.bootstrap import main; main()"

# 4. Start the server
python -m uvicorn migration_intake.main:get_app --factory --host 127.0.0.1 --port 8001
```

## Catalog Versioning

- **Current Version:** 0.2.0
- **File:** `src/migration_intake/catalog/data/catalog-0.2.0.csv`
- **Compiler Version:** 1.0.0

### Version History
- **0.2.0** - Current production catalog with UAQ and Interface Tracking support

## Excel Source Reference

**Note:** The original Excel workbook source is NOT packaged with the application.

- Original workbook location: `_data/` (ignored in git)
- Reviewed and sanitized CSV: `src/migration_intake/catalog/data/catalog-0.2.0.csv`
- The CSV is the authoritative source for all deployments

### Why CSV Instead of Excel?

1. **Deterministic:** CSV content is reproducible and version-controllable
2. **Portable:** Works across all platforms without Excel dependencies
3. **Auditable:** Changes are visible in git diffs
4. **Compiled:** Compiled into immutable database releases
5. **Validated:** Compiler validates structure and semantics

## Accessing the Catalog at Runtime

### Via Repository
```python
from migration_intake.persistence.repositories.catalogs import CatalogRepository
from sqlalchemy.orm import Session

with Session(engine) as session:
    repo = CatalogRepository(session)
    
    # Get latest published catalog
    catalog = repo.get_latest_published_release()
    
    # Get specific version
    catalog = repo.get_published_release("0.2.0")
    
    # Get sections
    sections = repo.get_sections_for_release(catalog['id'])
    
    # Get questions in section
    questions = repo.get_questions_for_section(section['id'])
```

### Via Service
```python
from migration_intake.application.services.catalogs import CatalogQueryService

service = CatalogQueryService(session_factory)
catalog = service.get_latest_published_release()
sections = service.get_sections_for_release(catalog['id'])
```

## Troubleshooting

### Catalog Not Found
**Error:** "No published catalog found"

**Solution:**
```bash
python -c "from migration_intake.catalog.bootstrap import main; main()"
```

### Compilation Errors
**Error:** "Catalog compilation failed: ..."

**Check:**
1. CSV file exists at `src/migration_intake/catalog/data/catalog-0.2.0.csv`
2. All required columns are present
3. No duplicate Question_IDs
4. Valid response types
5. Proper condition syntax

### Database Migration Issues
**Error:** "no such column: cat_releases...."

**Solution:**
```bash
python -m alembic upgrade head
```

## Summary

| Aspect | Details |
|--------|---------|
| **Source File** | `src/migration_intake/catalog/data/catalog-0.2.0.csv` |
| **Compiler** | `src/migration_intake/catalog/compiler.py` |
| **Bootstrap** | `src/migration_intake/catalog/bootstrap.py` |
| **Database Tables** | `cat_releases`, `cat_sections`, `cat_questions` |
| **Bootstrap Command** | `migration-intake-bootstrap-catalog` |
| **Current Version** | 0.2.0 |
| **Compiler Version** | 1.0.0 |
| **Idempotent** | Yes - safe to run multiple times |
