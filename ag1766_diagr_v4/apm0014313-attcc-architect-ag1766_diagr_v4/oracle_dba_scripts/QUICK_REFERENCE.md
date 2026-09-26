# Quick Reference Guide - Oracle DBA Scripts

## Connection Information

**Schema/User:** `MIGRATION_INTAKE_TEST`  
**Default Password:** `CHANGE_THIS_PASSWORD` (must be changed after creation)  
**Tablespace:** `USERS`  
**Temp Tablespace:** `TEMP`

---

## Script Execution Order

```bash
# 1. As SYSDBA
sqlplus / as sysdba @01_create_schema_and_user.sql

# 2-5. As MIGRATION_INTAKE_TEST user
sqlplus migration_intake_test/PASSWORD @02_create_tables.sql
sqlplus migration_intake_test/PASSWORD @03_create_indexes.sql
sqlplus migration_intake_test/PASSWORD @04_seed_data.sql
sqlplus migration_intake_test/PASSWORD @05_verify_schema.sql
```

---

## Connection String for Application

```
oracle+oracledb://migration_intake_test:PASSWORD@HOST:PORT?service_name=SERVICE_NAME
```

### Examples

**Local Oracle Free:**
```
oracle+oracledb://migration_intake_test:SecurePass123@localhost:1521?service_name=FREEPDB1
```

**Remote Oracle:**
```
oracle+oracledb://migration_intake_test:SecurePass123@dbhost.example.com:1521?service_name=TESTDB
```

---

## Verification Checklist

After running all scripts, verify:

- [ ] 23 tables created
- [ ] 23 primary keys
- [ ] ~30 foreign keys
- [ ] ~15 unique constraints
- [ ] ~80 indexes
- [ ] 2 actors (System, Default)
- [ ] Alembic version = 0013
- [ ] 0 invalid objects
- [ ] All constraints ENABLED

---

## Common Commands

### Check Schema Version
```sql
SELECT version_num FROM alembic_version;
```

### List All Tables
```sql
SELECT table_name FROM user_tables ORDER BY table_name;
```

### Check Table Row Counts
```sql
SELECT table_name, num_rows 
FROM user_tables 
WHERE num_rows > 0
ORDER BY num_rows DESC;
```

### Check for Invalid Objects
```sql
SELECT object_name, object_type, status
FROM user_objects
WHERE status = 'INVALID';
```

### View Foreign Key Relationships
```sql
SELECT 
    c.table_name,
    c.constraint_name,
    r.table_name AS referenced_table
FROM user_constraints c
JOIN user_constraints r ON c.r_constraint_name = r.constraint_name
WHERE c.constraint_type = 'R'
ORDER BY c.table_name;
```

---

## Troubleshooting

### Issue: ORA-01950: no privileges on tablespace 'USERS'

**Solution:**
```sql
ALTER USER migration_intake_test QUOTA UNLIMITED ON USERS;
```

### Issue: ORA-00955: name is already used by an existing object

**Solution:** Drop and recreate (CAUTION: destroys data)
```sql
DROP USER migration_intake_test CASCADE;
-- Then re-run 01_create_schema_and_user.sql
```

### Issue: Application cannot connect

**Checklist:**
1. Verify user exists: `SELECT username FROM dba_users WHERE username = 'MIGRATION_INTAKE_TEST';`
2. Verify password is correct
3. Verify service name: `SELECT name FROM v$services;`
4. Check listener status: `lsnrctl status`
5. Test connection: `sqlplus migration_intake_test/PASSWORD@HOST:PORT/SERVICE`

### Issue: Schema version mismatch

**Check current version:**
```sql
SELECT version_num FROM alembic_version;
```

**Expected:** `0013`

If version is different, the application may need to run migrations.

---

## Data Dictionary Queries

### Table Sizes
```sql
SELECT 
    segment_name,
    ROUND(bytes/1024/1024, 2) AS size_mb
FROM user_segments
WHERE segment_type = 'TABLE'
ORDER BY bytes DESC;
```

### Column Details for a Table
```sql
SELECT 
    column_name,
    data_type,
    data_length,
    nullable,
    data_default
FROM user_tab_columns
WHERE table_name = 'APPLICATIONS'
ORDER BY column_id;
```

### Index Details
```sql
SELECT 
    index_name,
    table_name,
    uniqueness,
    status
FROM user_indexes
WHERE table_name = 'APPLICATIONS';
```

### Constraint Details
```sql
SELECT 
    constraint_name,
    constraint_type,
    status,
    validated
FROM user_constraints
WHERE table_name = 'APPLICATIONS';
```

---

## Backup and Restore

### Export Schema (Data Pump)
```bash
expdp migration_intake_test/PASSWORD \
  schemas=migration_intake_test \
  directory=DATA_PUMP_DIR \
  dumpfile=migration_intake_backup.dmp \
  logfile=migration_intake_export.log
```

### Import Schema (Data Pump)
```bash
impdp migration_intake_test/PASSWORD \
  schemas=migration_intake_test \
  directory=DATA_PUMP_DIR \
  dumpfile=migration_intake_backup.dmp \
  logfile=migration_intake_import.log
```

### Export Schema (Traditional)
```bash
exp migration_intake_test/PASSWORD \
  file=migration_intake_backup.dmp \
  log=migration_intake_export.log \
  owner=migration_intake_test
```

---

## Performance Monitoring

### Check Active Sessions
```sql
SELECT 
    sid,
    serial#,
    username,
    program,
    status,
    sql_id
FROM v$session
WHERE username = 'MIGRATION_INTAKE_TEST';
```

### Check Long-Running Queries
```sql
SELECT 
    s.sid,
    s.serial#,
    s.username,
    s.sql_id,
    t.sql_text,
    s.last_call_et AS seconds_running
FROM v$session s
JOIN v$sqltext t ON s.sql_id = t.sql_id
WHERE s.username = 'MIGRATION_INTAKE_TEST'
  AND s.status = 'ACTIVE'
  AND s.last_call_et > 60
ORDER BY s.last_call_et DESC;
```

### Check Table Statistics
```sql
SELECT 
    table_name,
    num_rows,
    blocks,
    avg_row_len,
    last_analyzed
FROM user_tables
WHERE num_rows > 0
ORDER BY num_rows DESC;
```

---

## Security

### Change User Password
```sql
ALTER USER migration_intake_test IDENTIFIED BY "NewSecurePassword123";
```

### Lock User Account
```sql
ALTER USER migration_intake_test ACCOUNT LOCK;
```

### Unlock User Account
```sql
ALTER USER migration_intake_test ACCOUNT UNLOCK;
```

### View User Privileges
```sql
SELECT * FROM user_sys_privs;
SELECT * FROM user_tab_privs;
SELECT * FROM user_role_privs;
```

---

## Clean Uninstall

**CAUTION:** This destroys all data!

```sql
-- As SYSDBA
DROP USER migration_intake_test CASCADE;
```

This will:
- Drop the user
- Drop all tables
- Drop all indexes
- Drop all constraints
- Drop all data

---

## Support Contacts

For issues with:
- **Scripts:** Check `00_README.md` for detailed documentation
- **Application:** Check application logs and documentation
- **Oracle Database:** Consult Oracle documentation or DBA team

---

## Schema Version History

| Version | Date | Description |
|---------|------|-------------|
| 0001 | - | Core catalog and answers |
| 0002 | - | Evidence and wave utility |
| 0003 | - | Import runs |
| 0004 | - | Candidates |
| 0006 | - | Snapshots |
| 0007 | - | Catalog question metadata |
| 0008 | - | Repair answer instance metadata |
| 0009 | - | Repair answer revision metadata |
| 0010 | - | Import identity |
| 0011 | - | Scope evidence deduplication |
| 0012 | - | Application candidate scope |
| **0013** | **2026-09-11** | **Legacy intake workbook import support** |

---

**Last Updated:** 2026-09-11  
**Schema Version:** 0013
