# Catalog Quick Reference

## Quick Answer: Where is the Catalog Created?

### The Catalog Source
📄 **File:** `src/migration_intake/catalog/data/catalog-0.2.0.csv`

This is a CSV (spreadsheet) file containing all 100+ questions for the Migration Intake application.

### The Compilation Process
```
CSV File (catalog-0.2.0.csv)
    ↓
CatalogCompiler (compiler.py)
    ↓
Validates & Parses Rows
    ↓
Creates CatalogRelease Object
    ↓
CatalogPublicationService (bootstrap.py)
    ↓
Publishes to Database
    ↓
Database Tables (cat_releases, cat_sections, cat_questions)
```

### The Bootstrap Command
```bash
python -c "from migration_intake.catalog.bootstrap import main; main()"
```

**Result:** Catalog 0.2.0 is published to the database

---

## File Locations

| What | Where | Purpose |
|------|-------|---------|
| **Catalog CSV** | `src/migration_intake/catalog/data/catalog-0.2.0.csv` | Source of truth for all questions |
| **Compiler** | `src/migration_intake/catalog/compiler.py` | Reads CSV, validates, compiles |
| **Bootstrap Script** | `src/migration_intake/catalog/bootstrap.py` | Publishes compiled catalog to DB |
| **Database** | SQLite (configured in `.env`) | Stores compiled catalog |
| **Original Excel** | `_data/` (not packaged) | Original source (reference only) |

---

## CSV Structure (First Few Rows)

```
Question_ID | Section | Collection_Mode | Question_Text | Response_Type | ...
CTL-001 | Intake Control | AUTO_IMPORT | What is the application correlation or MOTS ID? | IDENTIFIER | ...
CTL-002 | Intake Control | AUTO_IMPORT | What are the approved application name and acronym? | TEXT_PAIR | ...
APP-001 | Application | AUTO_IMPORT | What business function does the application provide? | LONG_TEXT | ...
APP-002 | Application | AUTO_IMPORT | Who are the IT application owner and primary technical contacts? | PEOPLE_LIST | ...
APP-003 | Application | AUTO_IMPORT | What is the current operational status? | SINGLE_SELECT | ...
...
```

---

## How It Works

### 1. **CSV File** (Source)
- Contains all questions in structured format
- Columns: Question_ID, Section, Response_Type, etc.
- Version: 0.2.0
- Reviewed and sanitized (not the raw Excel)

### 2. **Compiler** (Processing)
```python
# Reads CSV
content = Path("catalog-0.2.0.csv").read_text()

# Compiles
result = CatalogCompiler().compile(
    content,
    version="0.2.0",
    source_filename="catalog-0.2.0.csv"
)

# Validates
if result.release:
    print(f"✓ {result.report.question_count} questions compiled")
else:
    print(f"✗ Compilation failed")
```

### 3. **Bootstrap** (Publication)
```python
# Publishes to database
release = publish_catalog(session_factory, source_path)

# Returns
print(f"Catalog {release['semantic_version']} is published")
print(f"Release ID: {release['id']}")
```

### 4. **Database** (Storage)
```
cat_releases
├── id: 13eacdac-ba33-4553-a665-5c1deba02ac8
├── semantic_version: 0.2.0
├── source_sha256: (hash of CSV)
└── pub_state: PUBLISHED

cat_sections
├── Intake Control
├── Application
├── Network
└── ... (15+ sections)

cat_questions
├── CTL-001, CTL-002, CTL-003
├── APP-001, APP-002, APP-003, ...
├── NET-001, NET-002, ...
└── ... (100+ questions)
```

---

## Key Points

✅ **CSV is the Source**
- `catalog-0.2.0.csv` is the authoritative source
- Not the original Excel workbook
- Reviewed and sanitized version

✅ **Compiler Validates**
- Checks for required columns
- Validates response types
- Compiles conditions
- Generates SHA256 hash

✅ **Bootstrap Publishes**
- Idempotent (safe to run multiple times)
- Same source = same release ID
- Creates database tables

✅ **Database Stores**
- Immutable catalog releases
- Versioned (0.2.0, future 0.3.0, etc.)
- Linked to intakes for consistency

---

## Development Workflow

```bash
# 1. Install
pip install -e ".[dev]"

# 2. Migrate database
python -m alembic upgrade head

# 3. Bootstrap catalog
python -c "from migration_intake.catalog.bootstrap import main; main()"

# 4. Start server
python -m uvicorn migration_intake.main:get_app --factory --host 127.0.0.1 --port 8001
```

---

## Excel Reference

**Original Excel Workbook:**
- Location: `_data/` (git-ignored, not packaged)
- Status: Reference only
- Used for: Reviewing changes, understanding source

**Why CSV Instead?**
1. Deterministic (reproducible)
2. Version-controllable (git-friendly)
3. No Excel dependency
4. Auditable (see diffs)
5. Compiled to immutable releases

---

## Database Tables

### `cat_releases`
Stores catalog versions
```sql
SELECT * FROM cat_releases;
-- id, semantic_version, source_filename, source_sha256, pub_state, ...
```

### `cat_sections`
Stores question sections
```sql
SELECT * FROM cat_sections WHERE catalog_id = '...';
-- Intake Control, Application, Network, Database, ...
```

### `cat_questions`
Stores individual questions
```sql
SELECT * FROM cat_questions WHERE section_id = '...';
-- CTL-001, APP-001, NET-001, ...
```

---

## Troubleshooting

| Problem | Solution |
|---------|----------|
| "No published catalog found" | Run: `python -c "from migration_intake.catalog.bootstrap import main; main()"` |
| "Catalog compilation failed" | Check CSV file exists and has valid format |
| "no such column: cat_releases" | Run: `python -m alembic upgrade head` |
| "Duplicate question ID" | Check CSV for duplicate Question_ID values |

---

## Summary Table

| Aspect | Details |
|--------|---------|
| **CSV File** | `src/migration_intake/catalog/data/catalog-0.2.0.csv` |
| **Compiler** | `src/migration_intake/catalog/compiler.py` |
| **Bootstrap** | `src/migration_intake/catalog/bootstrap.py` |
| **Database** | SQLite with 3 catalog tables |
| **Version** | 0.2.0 |
| **Questions** | 100+ questions across 15+ sections |
| **Bootstrap Command** | `migration-intake-bootstrap-catalog` |
| **Idempotent** | Yes (safe to run multiple times) |
| **Original Excel** | `_data/` (reference only, not packaged) |
