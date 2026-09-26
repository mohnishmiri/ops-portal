# Migration Intake - Personal Schema Installation (AG1766)

**Target Schema:** AG1766 (your personal schema)  
**Environment:** PERF  
**Schema Version:** 0013  
**Date:** 2026-09-11

---

## Overview

These instructions are for installing the Migration Intake schema in your personal Oracle schema (AG1766) in the PERF environment. Since you already have:
- ✅ Schema/user created (AG1766)
- ✅ 2GB quota in USERS tablespace
- ✅ Necessary privileges

You can **skip user creation** and go straight to creating tables.

---

## Quick Start

### Using SQL Developer

1. **Connect to PERF as AG1766**
   - Host: [PERF host]
   - Port: 1521
   - Service: [PERF service name]
   - Username: AG1766
   - Password: [your password]

2. **Run Scripts in Order:**
   ```
   @02_create_tables.sql
   @03_create_indexes.sql
   @04_seed_data.sql
   @05_verify_schema.sql
   ```

3. **Verify Installation:**
   - Check output of `05_verify_schema.sql`
   - Expected: 23 tables, ~80 indexes, 0 invalid objects

### Using SQL*Plus

```bash
# Connect to PERF
sqlplus ag1766/YOUR_PASSWORD@PERF_TNS_NAME

# Run scripts
@02_create_tables.sql
@03_create_indexes.sql
@04_seed_data.sql
@05_verify_schema.sql
```

---

## Scripts to Run

| Script | Purpose | Duration |
|--------|---------|----------|
| `02_create_tables.sql` | Create 23 tables with constraints | 1-2 min |
| `03_create_indexes.sql` | Create ~80 indexes | 2-3 min |
| `04_seed_data.sql` | Insert required seed data | < 1 min |
| `05_verify_schema.sql` | Verify installation | < 1 min |

**Total Time:** ~5 minutes

---

## What Gets Created

### Tables (23)
- `ACTORS` - System users
- `APPLICATIONS` - Subject applications
- `APP_IDENTIFIERS` - External identifiers
- `INTAKES` - Assessment intakes
- `ANS_INSTANCES` - Current answers
- `ANS_REVISIONS` - Answer history
- `CANDIDATES` - Proposed updates
- `EVIDENCE_ITEMS` - Uploaded files
- `IMPORT_RUNS` - Import processing
- And 14 more...

### Indexes (~80)
- Foreign key indexes
- Query performance indexes
- Composite indexes

### Seed Data
- 2 system actors (System, Default)
- Alembic version marker (0013)

---

## Application Configuration

After installation, update your application's `.env` file:

```bash
# PERF Environment - Personal Schema
DATABASE_URL=oracle+oracledb://ag1766:YOUR_PASSWORD@perf-host:1521?service_name=PERFDB
```

**Replace:**
- `YOUR_PASSWORD` - Your AG1766 password
- `perf-host` - PERF database host
- `PERFDB` - PERF service name

---

## Verification Checklist

After running all scripts, verify:

- [ ] 23 tables created in AG1766 schema
- [ ] 23 primary keys
- [ ] ~30 foreign keys
- [ ] ~15 unique constraints
- [ ] ~80 indexes
- [ ] 2 actors in ACTORS table
- [ ] ALEMBIC_VERSION shows '0013'
- [ ] 0 invalid objects
- [ ] All constraints are ENABLED

Run `05_verify_schema.sql` to check all of these automatically.

---

## Common SQL Developer Steps

### 1. Open SQL Developer
- Launch SQL Developer
- Create new connection or use existing AG1766 connection

### 2. Run Each Script
- Open script file (File → Open)
- Click "Run Script" button (F5) or press F5
- Review output in Script Output tab
- Look for errors (should be none)

### 3. Check Results
- Refresh Tables node in left panel
- You should see 23 new tables
- Expand APPLICATIONS table to verify structure

### 4. Verify Data
```sql
-- Check tables
SELECT COUNT(*) FROM user_tables;  -- Should be 23+

-- Check actors
SELECT * FROM actors;  -- Should show 2 rows

-- Check version
SELECT * FROM alembic_version;  -- Should show '0013'
```

---

## Troubleshooting

### Issue: ORA-01950: no privileges on tablespace 'USERS'

**Cause:** Quota not set or insufficient  
**Solution:** Already resolved - you have 2GB quota

### Issue: ORA-00955: name is already used by an existing object

**Cause:** Tables already exist from previous run  
**Solution:** Drop tables first:
```sql
-- List your tables
SELECT table_name FROM user_tables WHERE table_name LIKE 'A%' OR table_name LIKE 'C%';

-- Drop specific table
DROP TABLE applications CASCADE CONSTRAINTS;

-- Or drop all (CAUTION!)
BEGIN
   FOR t IN (SELECT table_name FROM user_tables) LOOP
      EXECUTE IMMEDIATE 'DROP TABLE ' || t.table_name || ' CASCADE CONSTRAINTS';
   END LOOP;
END;
/
```

### Issue: Script runs but shows errors

**Check:**
1. Are you connected as AG1766?
2. Do you have CREATE TABLE privilege?
3. Is tablespace quota sufficient?
4. Review error messages in Script Output

---

## Cleanup (If Needed)

To remove all Migration Intake objects:

```sql
-- Drop all tables (CAUTION: Destroys all data!)
BEGIN
   FOR t IN (
      SELECT table_name FROM user_tables 
      WHERE table_name IN (
         'ACTORS', 'APPLICATIONS', 'APP_IDENTIFIERS', 'INTAKES',
         'ANS_INSTANCES', 'ANS_REVISIONS', 'CANDIDATES', 'EVIDENCE_ITEMS',
         'IMPORT_RUNS', 'IMPORT_SHEET_RESULTS', 'IMPORT_FINDINGS',
         'CANDIDATE_FINDINGS', 'ANSWER_EVIDENCE_LINKS',
         'CAT_RELEASES', 'CAT_SECTIONS', 'CAT_QUESTIONS', 'CAT_OPTIONS',
         'CAT_SRC_RELS', 'INT_SNAPS', 'WAVE_UTIL_REVISIONS', 'WAVE_UTIL_ROWS',
         'AUDIT_EVENTS', 'ALEMBIC_VERSION'
      )
   ) LOOP
      EXECUTE IMMEDIATE 'DROP TABLE ' || t.table_name || ' CASCADE CONSTRAINTS';
   END LOOP;
END;
/
```

---

## Next Steps After Installation

1. **Start Application:**
   ```bash
   python -m uvicorn migration_intake.main:get_app --factory --reload --port 8000
   ```

2. **Verify Connection:**
   - Navigate to http://localhost:8000/health/ready
   - Should show database: ok

3. **Create First Application:**
   - Go to http://localhost:8000/applications
   - Click "Create New Application"
   - Test the workflow

4. **Test Legacy Intake Upload:**
   - Create an application
   - Create an intake
   - Go to Evidence Sources
   - Upload via lane ③ (Legacy completed intake)

---

## Advantages of Personal Schema

✅ **Immediate start** - No waiting for DBA  
✅ **Full control** - You own the objects  
✅ **Easy cleanup** - Drop and recreate anytime  
✅ **Isolated testing** - Won't affect others  
✅ **Quick iterations** - Make changes as needed  

---

## Migration to Dedicated Schema (Later)

If you need to move to a dedicated schema later:

1. Export your data:
   ```bash
   expdp ag1766/PASSWORD directory=DATA_PUMP_DIR \
     dumpfile=migration_intake.dmp \
     tables=APPLICATIONS,INTAKES,ACTORS,...
   ```

2. Send original scripts to Nasir for dedicated schema creation

3. Import data to new schema:
   ```bash
   impdp migration_intake_test/PASSWORD directory=DATA_PUMP_DIR \
     dumpfile=migration_intake.dmp \
     remap_schema=ag1766:migration_intake_test
   ```

---

## Support

**For Script Issues:**
- Review script output for specific errors
- Check `QUICK_REFERENCE.md` for common commands
- Verify prerequisites

**For Application Issues:**
- Check application logs
- Verify connection string in `.env`
- Test database connectivity

**For Oracle Issues:**
- Check tablespace quota: `SELECT * FROM user_ts_quotas;`
- Check privileges: `SELECT * FROM user_sys_privs;`
- Review Oracle alert log

---

## Summary

You're all set! Since you already have:
- Schema (AG1766) ✅
- Quota (2GB) ✅
- Privileges ✅

Just run scripts 02-05 in SQL Developer and you're done!

**Estimated Time:** 5 minutes  
**Difficulty:** Easy  
**Risk:** Low (only affects your schema)

---

**Questions?** Review `QUICK_REFERENCE.md` or reach out to the development team.
