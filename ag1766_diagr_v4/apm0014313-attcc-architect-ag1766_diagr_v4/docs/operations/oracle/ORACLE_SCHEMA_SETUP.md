# Oracle Test Schema Setup

**Purpose:** Create a dedicated, non-privileged Oracle schema for local validation.

**Security requirements:**
- ❌ Do NOT use `SYSTEM` or `SYS` as the application/test identity
- ❌ Do NOT commit passwords or connection strings to the repository
- ✅ Use a dedicated schema: `migration_intake` or `migration_intake_test`
- ✅ Store credentials in local `.env` file (already in `.gitignore`)

---

## Step 1: Connect to Oracle as SYSTEM (one-time admin task)

Using your preferred SQL client (SQL*Plus, SQL Developer, or DBeaver), connect to your local Oracle Free container:

```
Host: localhost
Port: 1521
Service Name: FREEPDB1
User: SYSTEM
Password: <your SYSTEM password>
```

---

## Step 2: Create dedicated test user/schema

Run the following SQL as `SYSTEM`:

```sql
-- Create dedicated user for migration_intake application
CREATE USER migration_intake_test IDENTIFIED BY "<choose_a_password>"
  DEFAULT TABLESPACE USERS
  TEMPORARY TABLESPACE TEMP
  QUOTA UNLIMITED ON USERS;

-- Grant minimal required privileges
GRANT CREATE SESSION TO migration_intake_test;
GRANT CREATE TABLE TO migration_intake_test;
GRANT CREATE SEQUENCE TO migration_intake_test;
GRANT CREATE VIEW TO migration_intake_test;

-- Verify user was created
SELECT username, default_tablespace, account_status
FROM dba_users
WHERE username = 'MIGRATION_INTAKE_TEST';
```

**Expected output:**
```
USERNAME              DEFAULT_TABLESPACE  ACCOUNT_STATUS
--------------------  ------------------  --------------
MIGRATION_INTAKE_TEST USERS               OPEN
```

---

## Step 3: Configure local environment

Create or update `.env` in the project root (this file is already in `.gitignore`):

```bash
# Oracle test database (local Docker container)
# SECURITY: This file is in .gitignore — never commit it
ORACLE_TEST_URL=oracle+oracledb://migration_intake_test:<your_password>@localhost:1521?service_name=FREEPDB1
```

Replace `<your_password>` with the password you chose in Step 2.

---

## Step 4: Verify connectivity

Run the preflight verification script:

```bash
python tests/oracle_preflight.py
```

**Expected output:**
```
Oracle Preflight Verification (O00)
============================================================
✓ oracledb driver installed: 2.5.1
✓ Thin mode available: True
✓ ORACLE_TEST_URL configured: oracle+oracledb://migration_intake_test:****@localhost:1521/?service_name=FREEPDB1
✓ Connected as: MIGRATION_INTAKE_TEST
✓ Service name: FREEPDB1
✓ Oracle version: Oracle Database 23ai Free Release 23.0.0.0.0 - Develop, Learn, and Run for Free
✓ DDL capability verified (created preflight_test_table)
✓ DML capability verified (inserted and queried)
✓ Cleanup successful (dropped preflight_test_table)
============================================================
✅ All preflight checks PASSED
```

If you see `❌ FAIL: Connected as SYSTEM — FORBIDDEN`, you must create the dedicated user above.

---

## Step 5: Update application configuration

The application's `config.py` already reads `DATABASE_URL` from the environment. For Oracle testing, you can:

**Option A: Use environment variable**
```bash
export DATABASE_URL=$ORACLE_TEST_URL
python -m pytest tests/contract/persistence/ -v
```

**Option B: Use pytest fixture override** (recommended for parallel SQLite/Oracle testing)

This will be implemented in packet O02 (Oracle test fixtures).

---

## Privilege escalation notes

The initial grants above are minimal. If Alembic migrations fail with privilege errors during O01, you may need to add:

- `CREATE PROCEDURE` — if migrations create stored procedures
- `CREATE TRIGGER` — if migrations create triggers
- Additional object privileges — discovered through failing tests

**Document any additional grants in this file** so the privilege set is reproducible.

---

## Cleanup (when Oracle testing is complete)

To remove the test schema:

```sql
-- Connect as SYSTEM
DROP USER migration_intake_test CASCADE;
```

**WARNING:** This is a destructive operation. All tables, data, and objects owned by this user will be permanently deleted.

---

## Troubleshooting

### "ORA-01017: invalid username/password"
- Verify the password in `.env` matches the one used in `CREATE USER`
- Check for special characters that need URL encoding

### "ORA-12154: TNS:could not resolve the connect identifier"
- Verify Docker container is running: `docker ps | grep oracle`
- Verify service name is `FREEPDB1` (case-sensitive)
- Try `localhost` instead of `127.0.0.1` or vice versa

### "ORA-01950: no privileges on tablespace 'USERS'"
- Re-run the `GRANT` statements above
- Verify quota: `SELECT * FROM dba_ts_quotas WHERE username = 'MIGRATION_INTAKE_TEST';`

### Preflight script fails with import error
- Ensure Oracle driver is installed: `pip install -e ".[oracle]"`
- Verify installation: `python -c "import oracledb; print(oracledb.__version__)"`

---

## Next steps

Once preflight passes, proceed to:
- **O01:** Clean Alembic migration execution (upgrade empty Oracle schema to head)
- See: [ORACLE_INTEGRATION_DESIGN.md](ORACLE_INTEGRATION_DESIGN.md) section 10
