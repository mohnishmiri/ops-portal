# O00 Complete — Oracle Preflight

**Date:** 2026-09-10
**Packet:** O00 (Oracle preflight and dedicated schema)
**Status:** ✅ READY FOR USER ACTION

---

## Deliverables

### 1. Oracle driver installed
- ✅ `oracledb>=2.2.0,<3.0` installed via `pip install -e ".[oracle]"`
- ✅ Thin mode confirmed available
- ✅ Version: 2.5.1

### 2. Preflight verification script
- ✅ Created: `tests/oracle_preflight.py`
- ✅ Verifies: driver, connectivity, user identity, DDL/DML capability
- ✅ Security: Rejects SYSTEM/SYS connections
- ✅ Security: Reads credentials from environment only (never from repository)

### 3. Schema setup documentation
- ✅ Created: `ORACLE_SCHEMA_SETUP.md`
- ✅ Documents: dedicated user creation, minimal privileges, troubleshooting
- ✅ Security: Explicit warnings against SYSTEM usage

### 4. Environment template
- ✅ Created: `.env.example`
- ✅ Verified: `.env` is in `.gitignore` (lines 30, 69)

### 5. Docker health verified
- ✅ Container: `oracle-free`
- ✅ Status: Up 3 days (healthy)
- ✅ Ports: 1521 (database), 5500 (EM Express)

---

## User action required

**You must now create the dedicated Oracle test schema.** The agent cannot do this because:
1. It requires SYSTEM credentials (which must never be in the repository)
2. It is a one-time administrative task
3. The password must be chosen by you and stored locally

### Steps:

1. **Connect to Oracle as SYSTEM** using SQL*Plus, SQL Developer, or DBeaver:
   ```
   Host: localhost
   Port: 1521
   Service Name: FREEPDB1
   User: SYSTEM
   Password: <your SYSTEM password>
   ```

2. **Run the schema creation SQL** from `ORACLE_SCHEMA_SETUP.md`:
   ```sql
   CREATE USER migration_intake_test IDENTIFIED BY "<choose_a_password>"
     DEFAULT TABLESPACE USERS
     TEMPORARY TABLESPACE TEMP
     QUOTA UNLIMITED ON USERS;

   GRANT CREATE SESSION TO migration_intake_test;
   GRANT CREATE TABLE TO migration_intake_test;
   GRANT CREATE SEQUENCE TO migration_intake_test;
   GRANT CREATE VIEW TO migration_intake_test;
   ```

3. **Create `.env` file** in the project root:
   ```bash
   ORACLE_TEST_URL=oracle+oracledb://migration_intake_test:<your_password>@localhost:1521/?service_name=FREEPDB1
   ```

4. **Verify connectivity:**
   ```bash
   python tests/oracle_preflight.py
   ```

   Expected: `✅ All preflight checks PASSED`

---

## Security verification

- ✅ No credentials in repository
- ✅ No credentials in this document
- ✅ `.env` is in `.gitignore`
- ✅ Preflight script redacts passwords in output
- ✅ SYSTEM/SYS connections are rejected by preflight script

---

## Known decisions (from G0)

- **Driver mode:** Thin only (no Oracle Instant Client required)
- **Schema identity:** `migration_intake_test` (dedicated, non-SYSTEM)
- **Privilege model:** Minimal grants, incremental discovery through failing tests
- **Migration owner = runtime user:** Same user for local validation only (exception documented)
- **Data cutover:** OUT OF SCOPE (no existing production data)

---

## Next steps

**After user completes schema setup and preflight passes:**

Proceed to **O01: Clean Alembic migration execution**
- Upgrade empty Oracle schema from base to head (revision 0010)
- Verify all 9 migrations execute without error
- Verify `alembic current` reports correct head
- Document any privilege escalations required

See: `ORACLE_INTEGRATION_DESIGN.md` section 10, packet O01

---

## Blocked until

- [ ] User creates dedicated Oracle schema using SYSTEM
- [ ] User configures `.env` with `ORACLE_TEST_URL`
- [ ] `python tests/oracle_preflight.py` exits 0

**Agent cannot proceed to O01 until preflight verification passes.**
