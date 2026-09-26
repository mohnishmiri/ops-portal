# Oracle Database Setup Scripts for Migration Intake Application

**Target Environment:** Test/Development Oracle Database  
**Schema Name:** `MIGRATION_INTAKE_TEST` (or as configured)  
**Generated:** 2026-09-11  
**Application Version:** Migration 0013 (includes legacy intake support)

---

## Overview

These scripts create the complete database schema for the Migration Intake application in Oracle. The schema includes 23 tables supporting:

- Application and intake management
- Question catalog and answer versioning
- Evidence import and candidate review
- Wave utility data capture
- Audit trail

---

## Execution Order

Execute scripts in this order:

1. **01_create_schema_and_user.sql** - Create schema/user and grant privileges
2. **02_create_tables.sql** - Create all tables with constraints
3. **03_create_indexes.sql** - Create indexes for performance
4. **04_seed_data.sql** - Insert required seed data (actors, catalog)
5. **05_verify_schema.sql** - Verification queries

---

## Prerequisites

- Oracle Database 19c or later (tested on Oracle 23c Free)
- DBA privileges to create users and grant permissions
- Sufficient tablespace for application data (~500MB initial)

---

## Schema Components

### Core Tables (23 total)

**Identity and Access:**
- `actors` - System users and service accounts
- `audit_events` - Audit trail for all changes

**Application Management:**
- `applications` - Subject applications under assessment
- `app_identifiers` - External identifiers (Correlation, MOTS, iTAP)
- `intakes` - Assessment intake instances
- `int_snaps` - Immutable intake snapshots

**Question Catalog:**
- `cat_releases` - Catalog versions
- `cat_sections` - Catalog sections
- `cat_questions` - Questions with response types
- `cat_options` - Allowed values for controlled questions
- `cat_src_rels` - Source-to-question relationships

**Answers:**
- `ans_instances` - Current answer state
- `ans_revisions` - Answer history (append-only)

**Evidence Import:**
- `evidence_items` - Uploaded evidence files
- `import_runs` - Import processing runs
- `import_sheet_results` - Per-sheet import results
- `import_findings` - Import issues and warnings
- `candidates` - Proposed answer updates
- `candidate_findings` - Candidate-specific issues
- `answer_evidence_links` - Answer-to-evidence relationships

**Wave Utility:**
- `wave_util_revisions` - Wave utility form versions
- `wave_util_rows` - Wave utility data rows

**Schema Management:**
- `alembic_version` - Migration version tracking

---

## Important Notes

### Character Encoding
- All VARCHAR2 columns use default database character set
- Ensure database is configured for UTF-8 (AL32UTF8)

### Date/Time Storage
- All timestamps stored as VARCHAR2(32) in ISO 8601 format
- Format: `YYYY-MM-DDTHH:MI:SS.ffffff+00:00`
- Timezone: UTC only

### UUID Format
- All UUIDs stored as CHAR(36) in standard format
- Format: `xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx`

### JSON Storage
- JSON data stored in CLOB columns
- Oracle 19c+ native JSON validation recommended

### Constraints
- All foreign keys have explicit names (Oracle 30-char limit)
- Primary keys use auto-generated names
- Unique constraints have explicit names

---

## Post-Installation

After running all scripts:

1. **Verify schema:** Run `05_verify_schema.sql`
2. **Test connection:** Use application connection string
3. **Run migrations:** Application will verify schema version
4. **Create first application:** Use web UI or API

---

## Connection String Format

```
oracle+oracledb://migration_intake_test:PASSWORD@HOST:PORT?service_name=SERVICE
```

Example:
```
oracle+oracledb://migration_intake_test:SecurePass123@dbhost.example.com:1521?service_name=TESTDB
```

---

## Support

For issues or questions:
- Check application logs for detailed error messages
- Verify schema version matches application version
- Review `alembic_version` table for migration state

---

## Schema Version

**Current Version:** 0013  
**Migration Name:** Add legacy intake workbook import support

**Recent Changes (0013):**
- Added `import_lane` column to `import_runs`
- Added `matched_identifier_type` column to `import_runs`
- Added `base_answer_revision` column to `candidates`
