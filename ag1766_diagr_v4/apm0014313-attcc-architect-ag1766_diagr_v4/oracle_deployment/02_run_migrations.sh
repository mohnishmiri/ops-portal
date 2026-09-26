#!/bin/bash
# ============================================================================
# Oracle Migration Execution Script
# Migration Intake Application
# Generated: 2026-09-11
# ============================================================================
#
# Purpose: Run Alembic migrations on Oracle database
#
# Prerequisites:
#   - Oracle schema created (01_create_schema.sql)
#   - Python environment with dependencies installed
#   - DATABASE_URL environment variable set
#
# Usage:
#   ./02_run_migrations.sh
#
# ============================================================================

set -e  # Exit on error
set -u  # Exit on undefined variable

# ============================================================================
# Configuration
# ============================================================================

echo "============================================================================"
echo "Migration Intake - Oracle Migration Execution"
echo "============================================================================"
echo ""

# Check if DATABASE_URL is set
if [ -z "${DATABASE_URL:-}" ]; then
    echo "ERROR: DATABASE_URL environment variable is not set"
    echo ""
    echo "Example:"
    echo "  export DATABASE_URL='oracle+oracledb://migration_intake:password@host:1521?service_name=SERVICE'"
    echo ""
    exit 1
fi

# Redact password for logging
REDACTED_URL=$(echo "$DATABASE_URL" | sed -E 's/:([^:@]+)@/:***@/')
echo "Database URL: $REDACTED_URL"
echo ""

# ============================================================================
# Pre-flight Checks
# ============================================================================

echo "============================================================================"
echo "Running pre-flight checks..."
echo "============================================================================"
echo ""

# Check Python
if ! command -v python &> /dev/null; then
    echo "ERROR: Python not found in PATH"
    exit 1
fi

echo "✓ Python version: $(python --version)"

# Check Alembic
if ! python -c "import alembic" 2>/dev/null; then
    echo "ERROR: Alembic not installed"
    echo "Run: pip install -e '.[dev]'"
    exit 1
fi

echo "✓ Alembic installed"

# Check SQLAlchemy
if ! python -c "import sqlalchemy" 2>/dev/null; then
    echo "ERROR: SQLAlchemy not installed"
    exit 1
fi

echo "✓ SQLAlchemy installed"

# Check oracledb driver
if ! python -c "import oracledb" 2>/dev/null; then
    echo "ERROR: oracledb driver not installed"
    echo "Run: pip install oracledb"
    exit 1
fi

echo "✓ Oracle driver (oracledb) installed"

# Test database connection
echo ""
echo "Testing database connection..."
python -c "
from sqlalchemy import create_engine, text
import os
import sys

try:
    engine = create_engine(os.environ['DATABASE_URL'])
    with engine.connect() as conn:
        result = conn.execute(text('SELECT 1 FROM DUAL'))
        print('✓ Database connection successful')
except Exception as e:
    print(f'ERROR: Database connection failed: {e}')
    sys.exit(1)
"

if [ $? -ne 0 ]; then
    exit 1
fi

echo ""

# ============================================================================
# Check Current Migration Status
# ============================================================================

echo "============================================================================"
echo "Checking current migration status..."
echo "============================================================================"
echo ""

# Check if alembic_version table exists
CURRENT_VERSION=$(python -c "
from sqlalchemy import create_engine, text, inspect
import os

engine = create_engine(os.environ['DATABASE_URL'])
inspector = inspect(engine)

# Check if alembic_version table exists
if 'alembic_version' in inspector.get_table_names():
    with engine.connect() as conn:
        result = conn.execute(text('SELECT version_num FROM alembic_version'))
        version = result.scalar()
        print(version if version else 'none')
else:
    print('none')
" 2>/dev/null)

if [ "$CURRENT_VERSION" = "none" ]; then
    echo "Current version: <not migrated>"
    echo "This appears to be a fresh database."
else
    echo "Current version: $CURRENT_VERSION"
fi

echo ""

# ============================================================================
# Run Migrations
# ============================================================================

echo "============================================================================"
echo "Running Alembic migrations..."
echo "============================================================================"
echo ""

# Run migrations
alembic upgrade head

if [ $? -ne 0 ]; then
    echo ""
    echo "ERROR: Migration failed!"
    exit 1
fi

echo ""

# ============================================================================
# Verify Migration Success
# ============================================================================

echo "============================================================================"
echo "Verifying migration success..."
echo "============================================================================"
echo ""

# Get new version
NEW_VERSION=$(python -c "
from sqlalchemy import create_engine, text
import os

engine = create_engine(os.environ['DATABASE_URL'])
with engine.connect() as conn:
    result = conn.execute(text('SELECT version_num FROM alembic_version'))
    print(result.scalar())
")

echo "New version: $NEW_VERSION"

# Verify expected version (0012 is current head)
if [ "$NEW_VERSION" = "0012" ]; then
    echo "✓ Migration successful - at head revision"
else
    echo "⚠ Warning: Expected version 0012, got $NEW_VERSION"
fi

echo ""

# ============================================================================
# Verify Table Creation
# ============================================================================

echo "============================================================================"
echo "Verifying table creation..."
echo "============================================================================"
echo ""

python -c "
from sqlalchemy import create_engine, inspect
import os

engine = create_engine(os.environ['DATABASE_URL'])
inspector = inspect(engine)

tables = inspector.get_table_names()
expected_tables = [
    'actors', 'applications', 'app_identifiers', 'intakes',
    'cat_releases', 'cat_sections', 'cat_questions', 'cat_options', 'cat_src_rels',
    'ans_instances', 'ans_revisions',
    'evidence_items', 'import_runs', 'import_sheet_results', 'import_findings',
    'candidates', 'candidate_findings', 'answer_evidence_links',
    'wave_util_rows', 'wave_util_revisions',
    'int_snaps', 'audit_events', 'alembic_version'
]

print(f'Total tables created: {len(tables)}')
print(f'Expected tables: {len(expected_tables)}')
print('')

missing = set(expected_tables) - set(tables)
if missing:
    print('⚠ Missing tables:')
    for table in sorted(missing):
        print(f'  - {table}')
else:
    print('✓ All expected tables created')

extra = set(tables) - set(expected_tables)
if extra:
    print('')
    print('Additional tables:')
    for table in sorted(extra):
        print(f'  - {table}')
"

echo ""

# ============================================================================
# Summary
# ============================================================================

echo "============================================================================"
echo "Migration Complete!"
echo "============================================================================"
echo ""
echo "Database is ready for application deployment."
echo ""
echo "Next steps:"
echo "  1. Start the application with DATABASE_URL set"
echo "  2. Verify health endpoints:"
echo "     curl http://localhost:8000/health/live"
echo "     curl http://localhost:8000/health/ready"
echo "  3. Monitor application logs for any issues"
echo ""
echo "============================================================================"
