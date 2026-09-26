# Local Development Setup

Quick reference for setting up the AWS Migration Intake Application for local development.

## Prerequisites

- **Python 3.13+** — [Download](https://www.python.org/downloads/) (verify with `python --version`)
- **Git** — [Download](https://git-scm.com/) or use `winget install git` (Windows) / `brew install git` (macOS)
- **SQLite3** — Usually included with Python; verify with `sqlite3 --version`
- **pip** — Included with Python 3.4+
- **Virtual Environment** — Built-in with Python 3.3+
- **Alembic** — Installed automatically in step 2 below

## Quick Start (10 minutes)

### 1. Clone and enter the repository

```bash
git clone https://github.com/ATT-DP5/apm0014313-attcc-architect.git
cd apm0014313-attcc-architect
git checkout ag1766_diagr_v4
```

### 2. Create virtual environment and install dependencies

```bash
# Create virtual environment
python -m venv venv

# Activate virtual environment
# Windows (PowerShell):
.\venv\Scripts\Activate.ps1

# Windows (Command Prompt):
venv\Scripts\activate.bat

# macOS/Linux:
source venv/bin/activate

# Upgrade pip to latest version
python -m pip install --upgrade pip

# Install project with dev dependencies
pip install -e ".[dev]"

# Verify installation
pip list | grep migration-intake
```

### 3. Configure environment variables

Create a `.env` file in the project root:

```bash
# Windows (PowerShell):
New-Item -Path ".env" -ItemType File

# macOS/Linux:
touch .env
```

Add these variables to `.env`:

```env
APP_ENV=local
DATABASE_URL=sqlite:///./migration_intake.db
EVIDENCE_ROOT=./evidence
ACTOR_ID=550e8400-e29b-41d4-a716-446655440000
CSRF_SECRET=local-dev-secret-change-in-production
```

**Note:** Generate a new ACTOR_ID with:
```bash
python -c "import uuid; print(uuid.uuid4())"
```

### 4. Create evidence directory

```bash
# Windows (PowerShell):
New-Item -Path "evidence" -ItemType Directory -Force

# macOS/Linux:
mkdir -p evidence
```

### 5. Initialize database

```bash
# IMPORTANT: Run from repo root (NOT from src/ directory)
# Create SQLite database and run migrations
python -m alembic upgrade head

# Verify: You should see migration_intake.db created in repo root
# Windows:
dir migration_intake.db

# macOS/Linux:
ls -la migration_intake.db
```

### 6. Publish the packaged catalog

```bash
# This reads the versioned catalog shipped with the package and publishes it
# idempotently. It is safe to run again after a restart or reinstall.
migration-intake-bootstrap-catalog
```

### 7. Start development server

```bash
# Windows (PowerShell):
python -m uvicorn migration_intake.main:get_app --factory --host 127.0.0.1 --port 8000 --reload

# macOS/Linux (Bash):
python -m uvicorn migration_intake.main:get_app --factory --host 127.0.0.1 --port 8000 --reload
```

✅ **Server running!** Open http://localhost:8000 in your browser.

**Note:** If you get a proxy error with `127.0.0.1`, use `localhost` instead in your browser.

---

## Running the Application

### Start the development server

```bash
# From project root with virtual environment activated
python -m uvicorn migration_intake.main:get_app --factory --host 127.0.0.1 --port 8000 --reload
```

**Output should show:**
```
INFO:     Uvicorn running on http://127.0.0.1:8000
INFO:     Application startup complete
```

### Access the application

- **Web UI**: http://localhost:8000
- **Health Check**: http://localhost:8000/health/live
- **Readiness**: http://localhost:8000/health/ready

### Stop the server

Press `Ctrl+C` in the terminal running the server.

---

## Testing & Verification

### Run all tests

```bash
# Full test suite (1787 tests)
python -m pytest tests/ -v

# Quick run (summary only)
python -m pytest tests/ -q

# Specific test file
python -m pytest tests/integration/web/test_evidence_routes.py -v

# Specific test
python -m pytest tests/unit/application/test_workbook_service.py::test_process_creates_import_run -v

# Run with coverage
python -m pytest tests/ --cov=src/migration_intake --cov-report=html
```

### Type checking

```bash
python -m mypy src/migration_intake
```

### Linting

```bash
python -m ruff check src/
python -m ruff format src/  # Auto-format code
```

### All checks at once

```bash
# Run tests, type check, and lint
python -m pytest tests/ -q && python -m mypy src/migration_intake && python -m ruff check src/
```

### Browser release gate

```bash
# One-time browser test setup
pip install -e ".[dev,browser]"
python -m playwright install chromium

# Isolated synthetic-data browser journeys; does not use local.db or _data
python -m pytest tests/browser/ -v -m browser
```

---

## Key Endpoints

| Endpoint | Method | Purpose | Status |
|----------|--------|---------|--------|
| `/health/live` | GET | Health check (liveness probe) | ✅ Ready |
| `/health/ready` | GET | Readiness probe (DB connected?) | ✅ Ready |
| `/applications` | GET | List all applications (HTML) | ✅ Ready |
| `/applications` | POST | Create new application | ✅ Ready |
| `/applications/{id}` | GET | Application workspace view (HTML) | ✅ Ready |

**Test locally:**
```bash
# Health checks
curl http://127.0.0.1:8000/health/live
curl http://127.0.0.1:8000/health/ready

# List applications (HTML)
curl http://127.0.0.1:8000/applications

# Create application (requires form data)
curl -X POST http://127.0.0.1:8000/applications \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "display_name=Test+App&identifier_type=ITAP&identifier_value=12345"
```

---

## Project Structure

```
src/migration_intake/        # Application source code
  ├─ web/                    # FastAPI routes and templates
  │  ├─ routes/              # Route handlers (.py)
  │  └─ templates/           # HTML templates (.html)
  ├─ application/            # Business logic (services)
  ├─ domain/                 # Domain models and value objects
  ├─ persistence/            # Database ORM models
  └─ main.py                 # FastAPI app factory

tests/                        # Test suite
  ├─ integration/            # Full endpoint tests
  ├─ unit/                   # Individual component tests
  ├─ web/                    # Web-specific tests
  └─ security/               # Security validation tests

docs/                         # Design documentation
_data/spike/                  # Spike prototype and data samples
```

---

## Common Development Tasks

### Create a new database from scratch

```bash
# Delete existing database (⚠️ data will be lost)
# Windows:
Remove-Item migration_intake.db -Force

# macOS/Linux:
rm migration_intake.db

# Re-run migrations
python -m alembic upgrade head

# Re-seed actor and catalog (see step 6 above)
```

### Generate a new actor ID

```bash
python -c "import uuid; print(uuid.uuid4())"
# Copy the output to ACTOR_ID in .env
```

### Reset database and evidence storage

```bash
# Windows (PowerShell):
Remove-Item migration_intake.db -Force
Remove-Item -Recurse -Force evidence -ErrorAction SilentlyContinue
New-Item -Path "evidence" -ItemType Directory -Force
python -m alembic upgrade head

# macOS/Linux:
rm -f migration_intake.db
rm -rf evidence
mkdir -p evidence
python -m alembic upgrade head
```

### Clear test data between runs

```bash
# Tests create their own in-memory database, so no cleanup needed
# To reset your local dev database, use the reset steps above
```

### Debug a specific failing test

```bash
# Run with full traceback
python -m pytest tests/unit/application/test_workbook_service.py::test_process_creates_import_run -vv --tb=long

# Run with print output visible (shows print() calls)
python -m pytest tests/unit/application/test_evidence_service.py -s

# Run with debugging
python -m pytest tests/... -vv --pdb  # Drops into debugger on failure
```

### View database contents

```bash
# Open SQLite CLI
sqlite3 migration_intake.db

# Common queries:
# List all tables:
.tables

# View actors:
SELECT * FROM actors;

# View applications:
SELECT id, display_name FROM applications;

# View catalogs:
SELECT id, semantic_version, pub_state FROM cat_releases;

# Exit:
.exit
```

### Inspect uploaded evidence files

```bash
# Evidence files are stored in ./evidence directory
# Organized by SHA-256 hash: evidence/XX/XXXX...

# List all evidence:
# Windows:
Get-ChildItem -Recurse evidence

# macOS/Linux:
find evidence -type f

# View file info:
ls -lh evidence/*/*
```

---

## Documentation References

- **Project Rules & Architecture:** [AGENTS.md](AGENTS.md)
- **Current Project State:** [STATE.md](STATE.md)
- **TDD Implementation Plan:** [src/PRODUCTION_FOUNDATION_TDD_IMPLEMENTATION_PLAN.md](src/PRODUCTION_FOUNDATION_TDD_IMPLEMENTATION_PLAN.md)
- **Production Architecture:** [src/PRODUCTION_FOUNDATION_ARCHITECTURE_AND_TECHNICAL_DESIGN.md](src/PRODUCTION_FOUNDATION_ARCHITECTURE_AND_TECHNICAL_DESIGN.md)
- **Database Schema:** [docs/SQLITE_SCHEMA_V0_1.sql](docs/SQLITE_SCHEMA_V0_1.sql)
- **UI Architecture:** [docs/UI_ARCHITECTURE_DECISIONS.md](docs/UI_ARCHITECTURE_DECISIONS.md)

---

## Troubleshooting

### "ModuleNotFoundError: No module named 'migration_intake'"

**Cause:** Virtual environment not activated or dependencies not installed.

✅ **Solution:**
```bash
# Verify virtual environment is activated (should see (venv) in prompt)
# Windows:
.\venv\Scripts\Activate.ps1

# macOS/Linux:
source venv/bin/activate

# Install dependencies
pip install -e ".[dev]"
```

### "sqlite3.OperationalError: no such table: actors"

**Cause:** Database migrations haven't run.

✅ **Solution:** Execute from **repo root** (not from src/):
```bash
# Verify you're in project root (should see alembic.ini)
dir alembic.ini  # Windows
ls alembic.ini   # macOS/Linux

# Run migrations
python -m alembic upgrade head
```

### "FAILED: No 'script_location' key found in configuration"

**Cause:** Alembic must be run from the repo root.

✅ **Solution:** Change to repo root:
```bash
# Wrong:
cd src && python -m alembic upgrade head

# Right:
cd apm0014313-attcc-architect  # repo root
python -m alembic upgrade head
```

### "AttributeError: 'NoneType' object has no attribute 'display_name'"

**Cause:** ACTOR_ID environment variable not set or actor not seeded.

✅ **Solution:**
```bash
# Verify .env has ACTOR_ID set
cat .env  # macOS/Linux
type .env  # Windows

# Seed actor (see step 6 in Quick Start)
python -c "
from datetime import datetime, timezone
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from migration_intake.persistence.models import Actor

engine = create_engine('sqlite:///./migration_intake.db')
Session = sessionmaker(bind=engine)

with Session() as session:
    actor = Actor(
        id='550e8400-e29b-41d4-a716-446655440000',
        display_name='Local Developer',
        created_at=datetime.now(tz=timezone.utc)
    )
    session.add(actor)
    session.commit()
"
```

### "Port 8000 already in use"

**Cause:** Another process is using port 8000.

✅ **Solution:** Use a different port:
```bash
python -m uvicorn migration_intake.main:get_app --factory --host 127.0.0.1 --port 8001 --reload
```

Or kill the existing process:
```bash
# Windows (PowerShell):
Get-Process -Id (Get-NetTCPConnection -LocalPort 8000).OwningProcess | Stop-Process -Force

# macOS/Linux:
lsof -i :8000 | grep LISTEN | awk '{print $2}' | xargs kill -9
```

### "Request on loopback from external IP" (400 error)

**Cause:** Proxy settings interfering with localhost requests.

✅ **Solution:** Use `localhost` instead of `127.0.0.1` in browser:
```
http://localhost:8000  # ✅ Works
http://127.0.0.1:8000  # ❌ May fail due to proxy
```

### Tests timeout or hang

**Cause:** Running dev server is blocking test database.

✅ **Solution:** Kill any running dev servers:
```bash
# Windows (PowerShell):
Get-Process -Name python | Where-Object {$_.CommandLine -like "*uvicorn*"} | Stop-Process -Force

# macOS/Linux:
pkill -f "uvicorn"

# Then retry tests:
python -m pytest tests/ -q
```

### "ImportError: cannot import name 'UAQSheetAdapter'"

**Cause:** Code changes not reflected (Python bytecode cache).

✅ **Solution:** Clear Python cache:
```bash
# Windows:
Get-ChildItem -Recurse -Filter "__pycache__" | Remove-Item -Recurse -Force

# macOS/Linux:
find . -type d -name __pycache__ -exec rm -rf {} +

# Restart server and tests
```

### Database locked error

**Cause:** Multiple processes accessing database simultaneously.

✅ **Solution:**
```bash
# Stop all running servers and tests
# Windows: Close all PowerShell/Command Prompt windows
# macOS/Linux: pkill -f "uvicorn" && pkill -f "pytest"

# Delete lock files
# Windows:
Remove-Item migration_intake.db-shm -Force -ErrorAction SilentlyContinue
Remove-Item migration_intake.db-wal -Force -ErrorAction SilentlyContinue

# macOS/Linux:
rm -f migration_intake.db-shm migration_intake.db-wal

# Restart
```

---

## Questions or Issues?

1. Check [STATE.md](STATE.md) for current project milestone and status
2. Review the relevant architecture document listed above
3. Run `python -m pytest tests/ -v` to verify your setup
4. Check git history: `git log --oneline -n 20`

---

**Last Updated:** 2026-09-09  
**R5 Gate Status:** ✅ Complete (1787 tests passing)  
**Current Focus:** CSV import, candidates extraction, UAQ adapter  
**Next Phase:** R6 (Security hardening, browser quality, operations)

---

## Verification Checklist

✅ **All setup steps complete?** Run through this checklist:

- [ ] Python 3.13+ installed (`python --version`)
- [ ] Git installed (`git --version`)
- [ ] Repository cloned and on `ag1766_diagr_v4` branch
- [ ] Virtual environment created and activated
- [ ] Dependencies installed (`pip install -e ".[dev]"`)
- [ ] `.env` file created with required variables
- [ ] `evidence/` directory created
- [ ] Database migrated (`python -m alembic upgrade head`)
- [ ] Actor seeded in database
- [ ] Catalog published (version 1.0.0)
- [ ] All tests pass (`python -m pytest tests/ -q`)

✅ **Server running?** Open http://localhost:8000 in your browser

Expected responses:
- ✅ **GET /health/live** → `{"status":"ok"}` (200)
- ✅ **GET /health/ready** → `{"status":"ready"}` (200)
- ✅ **GET /applications** → HTML list page (200)
- ✅ **POST /applications** → Create new app with form data (303 redirect)

### Quick verification script

```bash
# Run all verification steps
echo "1. Checking Python..."
python --version

echo "2. Checking virtual environment..."
python -c "import sys; print(f'Virtual env: {sys.prefix}')"

echo "3. Checking dependencies..."
pip list | grep -E "fastapi|sqlalchemy|alembic"

echo "4. Checking database..."
sqlite3 migration_intake.db "SELECT COUNT(*) as actor_count FROM actors;"

echo "5. Running tests..."
python -m pytest tests/ -q --tb=no

echo "✅ All checks passed!"
```

---

## Next Steps

1. **Read the documentation:**
   - [HANDOVER_SUMMARY.md](HANDOVER_SUMMARY.md) - Session summary and recent changes
   - [AGENTS.md](AGENTS.md) - Project rules and architecture
   - [STATE.md](STATE.md) - Current project state
   - [docs/USER_GUIDE.md](docs/USER_GUIDE.md) - End-user documentation

2. **Explore the application:**
   - Create an application
   - Create an intake
   - Upload a CSV file (`_data/UAQ - Unified Assessment Questionnaire (4).csv`)
   - Process the workbook
   - View extracted candidates

3. **Start developing:**
   - Make changes to code
   - Run tests: `python -m pytest tests/ -q`
   - Commit changes: `git add . && git commit -m "Your message"`
   - Push to branch: `git push origin ag1766_diagr_v4`

---

**Ready to develop!** 🚀
