# Oracle Integration Test Schema

The application uses `python-oracledb` thin mode by default. This schema is only for Oracle integration tests and is separate from `SYSTEM`.

## Create or reset the local test user

From the repository root, connect to the local `oracle-free` container and run:

```powershell
docker exec -it oracle-free sqlplus system@//localhost:1521/FREEPDB1
```

At the SQL*Plus prompt, run the script from the mounted repository path, or copy its contents into SQL*Plus:

```sql
@/workspace/scripts/oracle/create_test_user.sql
```

If the repository is not mounted into the container, run SQL*Plus from the host instead:

```powershell
sqlplus system@//localhost:1521/FREEPDB1 @scripts/oracle/create_test_user.sql
```

The script prompts for the `MIGRATION_INTAKE_TEST` password. It creates or resets only that user and grants the minimum schema privileges needed by the migration test suite.

## Application connection

Keep the URL in a local environment variable or secret. Do not commit it:

```powershell
$env:ORACLE_TEST_URL = "oracle+oracledb://migration_intake_test:<PASSWORD>@localhost:1521/?service_name=FREEPDB1"
$env:DATABASE_URL = $env:ORACLE_TEST_URL
python -m alembic upgrade head
```

The same value is used by the manual GitHub Actions Oracle smoke job as the `ORACLE_TEST_URL` repository secret.

## CI policy

The Oracle job is manual because it requires access to an Oracle instance and a secret connection URL. Normal CI remains SQLite/thin-mode and does not require Oracle credentials or the Oracle Container Registry.
