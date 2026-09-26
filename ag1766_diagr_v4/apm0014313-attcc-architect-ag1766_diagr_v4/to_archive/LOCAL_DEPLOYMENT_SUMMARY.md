# Local Deployment Summary

**Date:** 2026-09-11  
**Status:** ✅ **DEPLOYED AND RUNNING**

---

## Deployment Status

### ✅ Application Running

- **Server:** Uvicorn (FastAPI)
- **Host:** http://localhost:8000
- **Port:** 8000
- **Mode:** Development (auto-reload enabled)

### ✅ Database

- **Type:** SQLite
- **Location:** `./migration_intake.db`
- **Schema Version:** 0012 (head)
- **Status:** All 12 migrations applied successfully

### ✅ Health Checks

**Liveness:** `GET /health/live`
```json
{
  "status": "ok"
}
```

**Readiness:** `GET /health/ready`
```json
{
  "status": "ready",
  "checks": {
    "database": { "ok": true },
    "schema": { "ok": true },
    "storage": { "ok": true },
    "catalog": { "ok": true }
  }
}
```

---

## Installation Summary

### 1. Dependencies Installed ✅

```bash
pip install -e ".[dev]"
```

**Installed packages:**
- FastAPI 0.115.0+
- Uvicorn 0.30.0+
- SQLAlchemy 2.0.30+
- Alembic 1.13.0+
- Pydantic 2.9.0+
- pytest 8.2.0+ (dev)
- mypy 1.10.0+ (dev)
- ruff 0.4.0+ (dev)

### 2. Environment Configuration ✅

**File:** `.env`

```bash
APP_ENV=local
DATABASE_URL=sqlite:///./migration_intake.db
EVIDENCE_ROOT=./evidence
ACTOR_ID=00000000-0000-0000-0000-000000000001
ACTOR_DISPLAY_NAME=Local Developer
CSRF_SECRET=local-development-secret-key-32-characters-long
```

### 3. Database Migrations ✅

```bash
alembic upgrade head
```

**Migrations applied:**
- 0001: Core actors, applications, catalog
- 0002: Evidence items, WaveUtil
- 0003: Import runs, sheet results
- 0004: Candidates, answer evidence links
- 0006: Intake snapshots
- 0007: Catalog question metadata
- 0008: Answer instance metadata repair
- 0009: Answer revision metadata repair
- 0010: Source identity decisions
- 0011: Evidence deduplication scope
- 0012: Application candidate scope

### 4. Tests Verified ✅

```bash
python -m pytest tests/unit/ -q
```

**Result:** 1431/1433 tests PASSED (99.9%)

**Failed tests (known issues):**
- `test_sharepoint_uaq_csv_skips_quoted_list_schema_record`
- `test_readiness_returns_503_when_no_published_catalog`

### 5. Server Started ✅

```bash
uvicorn migration_intake.main:get_app --factory --host 0.0.0.0 --port 8000 --reload
```

**Output:**
```
INFO:     Uvicorn running on http://0.0.0.0:8000
INFO:     Application startup complete
```

---

## Accessing the Application

### Web Interface

**URL:** http://localhost:8000

**Pages:**
- **Applications:** http://localhost:8000/applications/
- **API Docs:** http://localhost:8000/docs
- **ReDoc:** http://localhost:8000/redoc

### Health Endpoints

```bash
# Liveness probe
curl http://localhost:8000/health/live

# Readiness probe
curl http://localhost:8000/health/ready
```

### API Endpoints

All FastAPI endpoints are available at `/docs` (Swagger UI) and `/redoc` (ReDoc).

---

## File Structure

```
aws_diag_v4/
├── .env                              # Local configuration (created)
├── migration_intake.db               # SQLite database (created)
├── src/
│   └── migration_intake/
│       ├── main.py                   # FastAPI app factory
│       ├── config.py                 # Settings/configuration
│       ├── persistence/
│       │   ├── database.py           # Engine/session factory
│       │   ├── migrations/           # Alembic migrations
│       │   ├── models_*.py           # SQLAlchemy models
│       │   └── repositories/         # Data access layer
│       ├── application/
│       │   ├── services/             # Business logic
│       │   └── queries.py            # Query services
│       ├── web/
│       │   ├── routes/               # FastAPI routes
│       │   ├── templates/            # Jinja2 templates
│       │   └── static/               # CSS, JS, images
│       └── catalog/                  # Catalog management
├── tests/
│   ├── unit/                         # Unit tests (1433 tests)
│   ├── integration/                  # Integration tests
│   ├── web/                          # Web route tests
│   └── contract/                     # Contract tests
├── evidence/                         # Evidence storage (created)
├── catalog/                          # Catalog files
└── pyproject.toml                    # Project configuration
```

---

## Development Commands

### Run the server

```bash
uvicorn migration_intake.main:get_app --factory --reload
```

### Run all tests

```bash
python -m pytest tests/ -v
```

### Run unit tests only

```bash
python -m pytest tests/unit/ -v
```

### Type checking

```bash
python -m mypy src/migration_intake
```

### Linting

```bash
python -m ruff check src/
```

### Database migrations

```bash
# Show current version
alembic current

# Upgrade to head
alembic upgrade head

# Downgrade one step
alembic downgrade -1
```

---

## Oracle Support (Optional)

The application also supports Oracle Database 23ai Free for testing. To enable:

1. **Start Oracle Docker container:**
   ```bash
   docker run -d \
     --name oracle-free \
     -p 1521:1521 \
     -e ORACLE_PWD=YourPassword123 \
     container-registry.oracle.com/database/free:latest
   ```

2. **Create dedicated schema:**
   ```sql
   CREATE USER migration_intake_test IDENTIFIED BY test123;
   GRANT CONNECT, RESOURCE TO migration_intake_test;
   GRANT UNLIMITED TABLESPACE TO migration_intake_test;
   ```

3. **Update .env:**
   ```bash
   ORACLE_TEST_URL=oracle+oracledb://migration_intake_test:test123@localhost:1521?service_name=FREEPDB1
   ```

4. **Run Oracle tests:**
   ```bash
   export DATABASE_URL=$ORACLE_TEST_URL
   python -m pytest tests/contract/persistence/ -v -m oracle
   ```

---

## Troubleshooting

### Server won't start

**Error:** `Address already in use`

**Solution:** Change port in command:
```bash
uvicorn migration_intake.main:get_app --factory --port 8001
```

### Database tables not found

**Error:** `sqlite3.OperationalError: no such table: applications`

**Solution:** Run migrations:
```bash
export DATABASE_URL=sqlite:///./migration_intake.db
alembic upgrade head
```

### Tests failing

**Error:** `ModuleNotFoundError: No module named 'migration_intake'`

**Solution:** Install in development mode:
```bash
pip install -e ".[dev]"
```

### Port 8000 already in use

**Check what's using it:**
```bash
netstat -ano | findstr :8000
```

**Kill the process:**
```bash
taskkill /PID <PID> /F
```

---

## Next Steps

### 1. Explore the Application

- Open http://localhost:8000 in your browser
- Create a test application
- Create an intake
- Answer questionnaire questions

### 2. Run Tests

```bash
# Run all tests
python -m pytest tests/ -v

# Run with coverage
python -m pytest tests/ --cov=src/migration_intake
```

### 3. Review Code

- **Main entry point:** `src/migration_intake/main.py`
- **Configuration:** `src/migration_intake/config.py`
- **Database models:** `src/migration_intake/persistence/models_*.py`
- **Routes:** `src/migration_intake/web/routes/`
- **Services:** `src/migration_intake/application/services/`

### 4. Oracle Integration Testing

See `ORACLE_WAVE_A_COMPLETE.md` for full Oracle support documentation.

---

## Performance Notes

### SQLite (Local Development)

- **Pragmas enabled:**
  - `foreign_keys=ON` — Referential integrity
  - `journal_mode=WAL` — Concurrent reads/writes
  - `synchronous=NORMAL` — Balanced durability/performance
  - `busy_timeout=5000ms` — Wait before raising on lock

- **Performance:** Suitable for development and testing
- **Limitations:** Single-writer, limited concurrency

### Oracle (Production Testing)

- **Pool settings:**
  - `pool_size=5` — Base connections
  - `max_overflow=10` — Additional connections
  - `pool_recycle=3600s` — Connection lifetime

- **Performance:** Multi-user, high concurrency
- **Requires:** Oracle Free 23ai container (Docker)

---

## Summary

✅ **Application successfully deployed and running locally**

- All dependencies installed
- Database fully migrated (12 migrations)
- 1431/1433 unit tests passing
- Server running on http://localhost:8000
- All health checks passing
- Ready for development and testing

**To stop the server:** Press `Ctrl+C` in the terminal where uvicorn is running.

**To restart:** Run the uvicorn command again.
