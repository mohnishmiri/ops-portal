# DBA Handoff - Migration Intake Application Oracle Schema

**Date:** 2026-09-11  
**Application:** Migration Intake  
**Schema Version:** 0013 (includes legacy intake workbook import support)  
**Target Environment:** Test/Development Oracle Database

---

## Executive Summary

This package contains complete DDL and DML scripts to create the Oracle database schema for the Migration Intake application in the test environment. The schema consists of 23 tables with approximately 80 indexes, supporting application and intake management, question catalog, answer versioning, evidence import, and audit trail functionality.

---

## Package Contents

| File | Purpose | Size | Run As |
|------|---------|------|--------|
| `00_README.md` | Overview and detailed documentation | 4.2 KB | Read first |
| `01_create_schema_and_user.sql` | Create schema/user and grant privileges | 1.8 KB | SYSDBA |
| `02_create_tables.sql` | Create 23 tables with constraints | 22 KB | Schema owner |
| `03_create_indexes.sql` | Create ~80 indexes for performance | 5.8 KB | Schema owner |
| `04_seed_data.sql` | Insert required seed data | 4.0 KB | Schema owner |
| `05_verify_schema.sql` | Verification queries and checks | 7.7 KB | Schema owner |
| `QUICK_REFERENCE.md` | Commands and troubleshooting guide | 6.7 KB | Reference |
| `DBA_HANDOFF.md` | This document | - | Read first |

**Total Package Size:** ~52 KB

---

## Prerequisites

### Database Requirements
- Oracle Database 19c or later (tested on Oracle 23c Free)
- Database character set: AL32UTF8 (UTF-8)
- Available tablespace: ~500 MB initial (will grow with data)
- DBA privileges to create users and grant permissions

### Network Requirements
- Application server must have network access to Oracle database
- Port 1521 (default) or custom Oracle listener port
- Service name or SID configured

---

## Installation Steps

### Step 1: Review Documentation
Read `00_README.md` for complete overview and requirements.

### Step 2: Create Schema and User
```bash
sqlplus / as sysdba @01_create_schema_and_user.sql
```

**Actions:**
- Creates user `MIGRATION_INTAKE_TEST`
- Sets default password (MUST be changed)
- Grants necessary privileges
- Assigns USERS tablespace with unlimited quota

**Post-Step:**
- Change default password immediately
- Note connection details for application team

### Step 3: Create Tables
```bash
sqlplus migration_intake_test/PASSWORD @02_create_tables.sql
```

**Actions:**
- Creates 23 tables
- Defines primary keys (23)
- Defines foreign keys (~30)
- Defines unique constraints (~15)
- Adds table and column comments

**Expected Duration:** 1-2 minutes

### Step 4: Create Indexes
```bash
sqlplus migration_intake_test/PASSWORD @03_create_indexes.sql
```

**Actions:**
- Creates ~80 indexes
- Includes foreign key indexes
- Includes composite indexes for common queries

**Expected Duration:** 2-3 minutes

### Step 5: Insert Seed Data
```bash
sqlplus migration_intake_test/PASSWORD @04_seed_data.sql
```

**Actions:**
- Inserts system actor
- Inserts default user actor
- Sets Alembic version to 0013
- (Optional) Creates sample application

**Expected Duration:** < 1 minute

### Step 6: Verify Installation
```bash
sqlplus migration_intake_test/PASSWORD @05_verify_schema.sql
```

**Actions:**
- Counts tables, constraints, indexes
- Checks seed data
- Identifies invalid objects
- Displays schema summary

**Expected Output:**
- 23 tables
- 23 primary keys
- ~30 foreign keys
- ~15 unique constraints
- ~80 indexes
- 2 actors
- Alembic version: 0013
- 0 invalid objects

---

## Post-Installation Tasks

### 1. Change Default Password
```sql
ALTER USER migration_intake_test IDENTIFIED BY "SecurePassword123!";
```

### 2. Provide Connection String to Application Team

**Format:**
```
oracle+oracledb://migration_intake_test:PASSWORD@HOST:PORT?service_name=SERVICE_NAME
```

**Example:**
```
oracle+oracledb://migration_intake_test:SecurePass123@dbhost.example.com:1521?service_name=TESTDB
```

### 3. Configure Application
Application team will:
- Update `.env` file with connection string
- Start application
- Verify connectivity
- Application will auto-create catalog on first startup

### 4. Create First Application
Via web UI at `http://application-host:8000/applications`

---

## Schema Overview

### Core Components

**Identity and Access (2 tables):**
- `actors` - System users
- `audit_events` - Audit trail

**Application Management (6 tables):**
- `applications` - Subject applications
- `app_identifiers` - External IDs
- `intakes` - Assessment instances
- `int_snaps` - Immutable snapshots
- `ans_instances` - Current answers
- `ans_revisions` - Answer history

**Question Catalog (6 tables):**
- `cat_releases` - Catalog versions
- `cat_sections` - Sections
- `cat_questions` - Questions
- `cat_options` - Allowed values
- `cat_src_rels` - Source mappings

**Evidence Import (8 tables):**
- `evidence_items` - Uploaded files
- `import_runs` - Import processing
- `import_sheet_results` - Per-sheet results
- `import_findings` - Issues/warnings
- `candidates` - Proposed updates
- `candidate_findings` - Candidate issues
- `answer_evidence_links` - Answer-evidence links

**Wave Utility (2 tables):**
- `wave_util_revisions` - Form versions
- `wave_util_rows` - Data rows

**Schema Management (1 table):**
- `alembic_version` - Migration tracking

---

## Important Notes

### Data Types
- **UUIDs:** Stored as CHAR(36) in format `xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx`
- **Timestamps:** Stored as VARCHAR2(32) in ISO 8601 UTC format
- **JSON:** Stored in CLOB columns

### Constraints
- All foreign keys have explicit names (Oracle 30-char limit)
- All unique constraints have explicit names
- Primary keys use auto-generated names

### Performance
- Indexes created for all foreign keys
- Composite indexes for common query patterns
- Statistics will be gathered automatically by Oracle

### Security
- User has minimal required privileges
- No SYSDBA or elevated privileges
- Password must be changed from default

---

## Rollback Procedure

If installation needs to be rolled back:

```sql
-- As SYSDBA
DROP USER migration_intake_test CASCADE;
```

**CAUTION:** This destroys all data and objects!

---

## Troubleshooting

### Common Issues

**Issue:** ORA-01950: no privileges on tablespace 'USERS'  
**Solution:** `ALTER USER migration_intake_test QUOTA UNLIMITED ON USERS;`

**Issue:** ORA-00955: name is already used by an existing object  
**Solution:** Drop and recreate user (see Rollback Procedure)

**Issue:** Application cannot connect  
**Solution:** Verify:
1. User exists and is unlocked
2. Password is correct
3. Service name is correct
4. Network connectivity
5. Listener is running

See `QUICK_REFERENCE.md` for more troubleshooting steps.

---

## Maintenance

### Regular Tasks
- Monitor table growth
- Gather statistics (automatic by default)
- Review audit events
- Archive old data as needed

### Backup Recommendations
- Include schema in regular database backups
- Test restore procedure
- Document backup schedule

### Monitoring
- Monitor active sessions
- Check for long-running queries
- Review invalid objects
- Monitor tablespace usage

---

## Support and Contacts

### For Schema Issues
- Review `QUICK_REFERENCE.md` for common commands
- Check `05_verify_schema.sql` output
- Review Oracle alert log

### For Application Issues
- Contact application development team
- Check application logs
- Verify connection string

### For Database Issues
- Contact Oracle DBA team
- Review Oracle documentation
- Check Oracle support

---

## Schema Version History

**Current Version:** 0013 (2026-09-11)

**Recent Changes:**
- Added `import_lane` column to `import_runs` table
- Added `matched_identifier_type` column to `import_runs` table
- Added `base_answer_revision` column to `candidates` table
- Support for legacy intake workbook import

**Previous Versions:** See `00_README.md` for full history

---

## Sign-Off

### DBA Checklist

- [ ] Reviewed all scripts
- [ ] Verified prerequisites
- [ ] Executed scripts in order
- [ ] Verified installation (05_verify_schema.sql)
- [ ] Changed default password
- [ ] Provided connection string to application team
- [ ] Documented any deviations or issues
- [ ] Configured backups
- [ ] Set up monitoring

### Installation Details

**Installed By:** ___________________________  
**Date:** ___________________________  
**Database Host:** ___________________________  
**Service Name:** ___________________________  
**Schema Name:** MIGRATION_INTAKE_TEST  
**Schema Version:** 0013  

**Notes:**
_________________________________________________________________
_________________________________________________________________
_________________________________________________________________

---

**Document Version:** 1.0  
**Last Updated:** 2026-09-11  
**Prepared By:** Migration Intake Development Team
