# Installation Checklist - AG1766 Personal Schema

**Your Name:** AG1766  
**Environment:** PERF  
**Date:** _______________

---

## Pre-Installation Checklist

- [ ] Connected to PERF database as AG1766
- [ ] Verified 2GB quota in USERS tablespace
- [ ] SQL Developer or SQL*Plus ready
- [ ] Scripts downloaded to local directory

---

## Installation Steps

### Step 1: Create Tables (02_create_tables.sql)

- [ ] Opened `02_create_tables.sql` in SQL Developer
- [ ] Pressed F5 to run script
- [ ] Reviewed output - no errors
- [ ] Verified: "Table creation complete!" message
- [ ] Verified: 23 tables created

**Notes:**
_________________________________________________________________

### Step 2: Create Indexes (03_create_indexes.sql)

- [ ] Opened `03_create_indexes.sql` in SQL Developer
- [ ] Pressed F5 to run script
- [ ] Reviewed output - no errors
- [ ] Verified: "Index creation complete!" message
- [ ] Verified: ~80 indexes created

**Notes:**
_________________________________________________________________

### Step 3: Insert Seed Data (04_seed_data.sql)

- [ ] Opened `04_seed_data.sql` in SQL Developer
- [ ] Pressed F5 to run script
- [ ] Reviewed output - no errors
- [ ] Verified: 2 actors inserted
- [ ] Verified: Alembic version = 0013

**Notes:**
_________________________________________________________________

### Step 4: Verify Installation (05_verify_schema.sql)

- [ ] Opened `05_verify_schema.sql` in SQL Developer
- [ ] Pressed F5 to run script
- [ ] Reviewed all verification sections

**Verification Results:**

| Check | Expected | Actual | Status |
|-------|----------|--------|--------|
| Tables | 23 | _____ | ☐ Pass ☐ Fail |
| Primary Keys | 23 | _____ | ☐ Pass ☐ Fail |
| Foreign Keys | ~30 | _____ | ☐ Pass ☐ Fail |
| Unique Constraints | ~15 | _____ | ☐ Pass ☐ Fail |
| Indexes | ~80 | _____ | ☐ Pass ☐ Fail |
| Actors | 2 | _____ | ☐ Pass ☐ Fail |
| Alembic Version | 0013 | _____ | ☐ Pass ☐ Fail |
| Invalid Objects | 0 | _____ | ☐ Pass ☐ Fail |

**Notes:**
_________________________________________________________________

---

## Post-Installation Checklist

### Application Configuration

- [ ] Located `.env` file in application directory
- [ ] Updated `DATABASE_URL` with AG1766 credentials
- [ ] Saved `.env` file

**Connection String Used:**
```
oracle+oracledb://ag1766:PASSWORD@HOST:PORT?service_name=SERVICE
```

### Application Startup

- [ ] Started application server
- [ ] Checked health endpoint: http://localhost:8000/health/ready
- [ ] Verified database status: "ok"

**Health Check Response:**
_________________________________________________________________

### First Application Test

- [ ] Navigated to http://localhost:8000/applications
- [ ] Clicked "Create New Application"
- [ ] Created test application successfully
- [ ] Application ID: _______________________________________

### Legacy Intake Test

- [ ] Created intake for test application
- [ ] Navigated to Evidence Sources page
- [ ] Saw three lanes (①, ②, ③)
- [ ] Lane ③ shows "Legacy completed intake"
- [ ] Uploaded test workbook via lane ③
- [ ] Identity extraction worked
- [ ] Intake selection screen appeared
- [ ] Processing created candidates

**Test Results:**
_________________________________________________________________

---

## Troubleshooting Log

**Issue 1:**
- Problem: _______________________________________________________
- Solution: _______________________________________________________
- Status: ☐ Resolved ☐ Escalated

**Issue 2:**
- Problem: _______________________________________________________
- Solution: _______________________________________________________
- Status: ☐ Resolved ☐ Escalated

**Issue 3:**
- Problem: _______________________________________________________
- Solution: _______________________________________________________
- Status: ☐ Resolved ☐ Escalated

---

## Final Sign-Off

### Installation Summary

- **Total Time:** __________ minutes
- **Tables Created:** __________ (expected: 23)
- **Indexes Created:** __________ (expected: ~80)
- **Errors Encountered:** ☐ None ☐ Some (see troubleshooting log)
- **Overall Status:** ☐ Success ☐ Partial ☐ Failed

### Application Testing

- **Application Starts:** ☐ Yes ☐ No
- **Database Connection:** ☐ Working ☐ Failed
- **Can Create Application:** ☐ Yes ☐ No
- **Can Upload Evidence:** ☐ Yes ☐ No
- **Legacy Intake Works:** ☐ Yes ☐ No ☐ Not Tested

### Ready for Use

- [ ] Schema installed successfully
- [ ] Application configured
- [ ] Application tested
- [ ] No critical issues
- [ ] Ready for development/testing

---

## Quick Reference Commands

### Check Your Tables
```sql
SELECT COUNT(*) FROM user_tables;
SELECT table_name FROM user_tables ORDER BY table_name;
```

### Check Actors
```sql
SELECT id, display_name, attuid FROM actors;
```

### Check Schema Version
```sql
SELECT version_num FROM alembic_version;
```

### Check Tablespace Quota
```sql
SELECT tablespace_name, bytes/1024/1024 AS mb_used, max_bytes/1024/1024 AS mb_quota
FROM user_ts_quotas;
```

### Check Invalid Objects
```sql
SELECT object_name, object_type, status
FROM user_objects
WHERE status = 'INVALID';
```

---

## Next Steps

After successful installation:

1. **Development:**
   - Start building/testing features
   - Use legacy intake upload functionality
   - Test with real workbooks

2. **Documentation:**
   - Document any issues found
   - Update team on progress
   - Share connection details if needed

3. **Future Migration (if needed):**
   - Export data from AG1766
   - Request dedicated schema from Nasir
   - Import data to new schema

---

## Contact Information

**For Script Issues:**
- Review `PERSONAL_SCHEMA_README.md`
- Check `QUICK_REFERENCE.md`

**For Application Issues:**
- Check application logs
- Review application documentation

**For Oracle Issues:**
- Contact: Nasir Loladia
- Check Oracle documentation

---

**Completed By:** AG1766  
**Date:** _______________  
**Time:** _______________  
**Status:** ☐ Success ☐ Needs Follow-up

**Additional Notes:**
_________________________________________________________________
_________________________________________________________________
_________________________________________________________________
