# O04 Complete — Runtime Configuration

**Date:** 2026-09-11
**Packet:** O04 (Runtime configuration: pool settings, redaction, shutdown)
**Status:** ✅ COMPLETE

---

## Summary

Wired database pool settings from configuration to the SQLAlchemy engine, verified password redaction works correctly, and tested engine shutdown/disposal. Oracle engines now use configurable connection pooling with proper cleanup on application shutdown.

**Test results:**
- ✅ **9/9 configuration tests PASSED**
- ✅ Pool settings applied to Oracle engines
- ✅ Password redaction works for all database URLs
- ✅ Engine disposal closes connections correctly
- ✅ SQL echo setting applied

---

## Changes made

### 1. Pool settings wired to engine creation

**File:** `src/migration_intake/main.py`

**Before:**
```python
db_url = settings.effective_database_url
engine_kwargs: dict[str, object] = {}
if db_url.startswith("sqlite"):
    engine_kwargs["connect_args"] = {"check_same_thread": False}
engine = create_engine_from_url(db_url, **engine_kwargs)
```

**After:**
```python
db_url = settings.effective_database_url
engine_kwargs: dict[str, object] = {}

if db_url.startswith("sqlite"):
    # Allow the engine to be used across threads (required by TestClient and
    # any sync-in-async usage patterns that rely on a thread-pool executor).
    engine_kwargs["connect_args"] = {"check_same_thread": False}
else:
    # Apply pool settings for non-SQLite databases (Oracle, PostgreSQL)
    engine_kwargs["pool_size"] = settings.db_pool_size
    engine_kwargs["max_overflow"] = settings.db_max_overflow
    engine_kwargs["pool_recycle"] = settings.db_pool_recycle_seconds

# Apply SQL echo setting (useful for debugging)
engine_kwargs["echo"] = settings.sql_echo

engine = create_engine_from_url(db_url, **engine_kwargs)
```

**Why SQLite is excluded:** SQLite uses a file-based database with limited concurrency. Connection pooling is less relevant, and SQLite's default pool behavior is sufficient for local development.

### 2. Engine disposal on shutdown

**File:** `src/migration_intake/main.py`

**Added to lifespan shutdown:**
```python
yield
logger.info("Shutting down Migration Intake application")
# Dispose of the engine to close all connections
engine.dispose()
logger.info("Database engine disposed")
```

**Why this matters:** Ensures all database connections are properly closed when the application shuts down, preventing connection leaks and allowing clean database restarts.

---

## Configuration settings

### Pool settings (already existed in config.py)

| Setting | Default | Range | Description |
|---------|---------|-------|-------------|
| `DB_POOL_SIZE` | 5 | 1-100 | Number of connections to maintain in the pool |
| `DB_MAX_OVERFLOW` | 10 | 0-100 | Max connections beyond pool_size |
| `DB_POOL_RECYCLE_SECONDS` | 3600 | ≥60 | Recycle connections after this many seconds |
| `SQL_ECHO` | false | boolean | Log all SQL statements (debugging) |

### Example .env configuration

```bash
# Oracle connection
DATABASE_URL=oracle+oracledb://migration_intake:password@localhost:1521?service_name=FREEPDB1

# Pool settings (Oracle/PostgreSQL only)
DB_POOL_SIZE=10
DB_MAX_OVERFLOW=20
DB_POOL_RECYCLE_SECONDS=1800

# SQL debugging (set to true to see all queries)
SQL_ECHO=false
```

---

## Password redaction

### Existing functionality verified

**Function:** `migration_intake.persistence.database.redact_url()`
**Also available as:** `Settings.redacted_database_url()`

**Examples:**

| Original URL | Redacted URL |
|-------------|-------------|
| `postgresql://user:s3cr3t@host:5432/db` | `postgresql://***:***@host:5432/db` |
| `oracle+oracledb://admin:pwd@localhost:1521?service_name=FREEPDB1` | `oracle+oracledb://***:***@localhost:1521?service_name=FREEPDB1` |
| `sqlite:///path/to/db.sqlite` | `sqlite:///path/to/db.sqlite` (unchanged) |

**Usage in application startup:**
```python
logger.info(
    "Starting Migration Intake application",
    extra={
        "version": __version__,
        "environment": settings.app_env,
        "database": settings.redacted_database_url(),  # ✅ Credentials hidden
    },
)
```

---

## Test coverage

### Created: `tests/integration/test_database_configuration.py`

**9 tests, all passing:**

#### Password redaction (4 tests)
- ✅ `test_redact_url_removes_credentials` — PostgreSQL URL redaction
- ✅ `test_redact_url_handles_oracle` — Oracle URL redaction
- ✅ `test_redact_url_preserves_sqlite` — SQLite URL unchanged
- ✅ `test_settings_redacted_database_url` — Settings method works

#### Pool configuration (2 tests)
- ✅ `test_sqlite_engine_does_not_use_pool_settings` — SQLite works without pool settings
- ✅ `test_oracle_engine_uses_pool_settings` — Oracle engine receives pool config

#### Engine shutdown (2 tests)
- ✅ `test_engine_disposal_closes_connections` — SQLite disposal works
- ✅ `test_oracle_engine_disposal_closes_connections` — Oracle disposal closes pool

#### SQL echo (1 test)
- ✅ `test_sql_echo_setting_is_applied` — SQL_ECHO setting controls engine.echo

---

## Oracle pool verification

### Test: `test_oracle_engine_uses_pool_settings`

**Setup:**
```python
DATABASE_URL=oracle+oracledb://migration_intake_test:test123@localhost:1521?service_name=FREEPDB1
DB_POOL_SIZE=15
DB_MAX_OVERFLOW=25
DB_POOL_RECYCLE_SECONDS=1800
```

**Verification:**
```python
app = create_app(settings)
engine: Engine = app.state.engine

assert isinstance(engine.pool, QueuePool)  # ✅ Uses QueuePool
assert engine.pool.size() == 15            # ✅ pool_size applied
assert engine.pool._max_overflow == 25     # ✅ max_overflow applied
assert engine.pool._recycle == 1800        # ✅ pool_recycle applied
```

**Result:** ✅ PASSED

---

## Engine disposal verification

### Test: `test_oracle_engine_disposal_closes_connections`

**Scenario:**
1. Create Oracle engine with pool_size=5
2. Open 3 connections
3. Execute queries on all connections
4. Close connections (return to pool)
5. Call `engine.dispose()`
6. Verify engine still works (creates new pool)

**Result:** ✅ PASSED

**Key insight:** `engine.dispose()` closes all pooled connections but doesn't prevent the engine from being used again. Subsequent connections create a new pool.

---

## Files modified

- `src/migration_intake/main.py` (2 changes)
  - Added pool settings for non-SQLite databases
  - Added engine disposal on shutdown

## Files created

- `tests/integration/test_database_configuration.py` (276 lines, 9 tests)

---

## Acceptance criteria (from ORACLE_INTEGRATION_DESIGN.md)

Per section 11, packet O04:

- ✅ Pool settings (`db_pool_size`, `db_max_overflow`, `db_pool_recycle_seconds`) wired to engine
- ✅ Pool settings applied only to non-SQLite databases
- ✅ Password redaction verified for Oracle URLs
- ✅ Engine shutdown/disposal implemented and tested
- ✅ SQL echo setting applied
- ✅ Integration tests cover all configuration scenarios

**Status:** O04 COMPLETE ✅

---

## Lessons learned

### 1. SQLite doesn't need pool settings

SQLite is file-based with limited concurrency. While it can use QueuePool, the pool_size/max_overflow settings are less relevant. The application correctly applies pool settings only to Oracle/PostgreSQL.

### 2. Engine disposal is idempotent

Calling `engine.dispose()` multiple times is safe. It closes all pooled connections but doesn't prevent the engine from being used again.

### 3. Pool recycle prevents stale connections

Oracle connections can become stale if held too long (network issues, server restarts). The `pool_recycle` setting (default 3600s = 1 hour) ensures connections are recycled periodically.

**Recommended values:**
- **Local development:** pool_size=5, max_overflow=10, pool_recycle=3600
- **Production:** pool_size=10-20, max_overflow=20-40, pool_recycle=1800 (30 min)

### 4. SQL echo is useful for debugging

Setting `SQL_ECHO=true` logs all SQL statements, which is invaluable for debugging query performance or understanding what SQLAlchemy generates. Should be `false` in production.

### 5. Password redaction must be consistent

The application uses `settings.redacted_database_url()` in startup logs. This ensures credentials never appear in logs, even if SQL echo is enabled (SQLAlchemy's echo doesn't log connection strings).

---

## Next steps

**Wave A (O00-O04) is now complete!** ✅

Ready to proceed to:

**G3 integration:** Merge Wave A changes and run full persistence contract tests on both SQLite and Oracle.

See: `ORACLE_INTEGRATION_DESIGN.md` section 11 (Wave A → G3 gate)

---

## Verification commands

### Check pool settings are applied (Oracle)

```python
from migration_intake.config import Settings
from migration_intake.main import create_app

settings = Settings()  # Loads from .env
app = create_app(settings)
engine = app.state.engine

print(f"Pool type: {type(engine.pool).__name__}")
print(f"Pool size: {engine.pool.size()}")
print(f"Max overflow: {engine.pool._max_overflow}")
print(f"Pool recycle: {engine.pool._recycle}s")
```

### Test engine disposal

```python
# Open connections
with engine.connect() as conn:
    result = conn.execute(text("SELECT USER FROM DUAL"))
    print(f"Connected as: {result.scalar()}")

# Dispose
engine.dispose()
print("Engine disposed")

# Verify still works (creates new pool)
with engine.connect() as conn:
    result = conn.execute(text("SELECT USER FROM DUAL"))
    print(f"Reconnected as: {result.scalar()}")
```

### Verify password redaction

```python
from migration_intake.config import Settings

settings = Settings()
print(f"Original: {settings.effective_database_url}")
print(f"Redacted: {settings.redacted_database_url()}")
```
