"""Clean up Oracle test schema - drops all tables and alembic_version."""

import os
import sys
from pathlib import Path

try:
    from dotenv import load_dotenv
    env_path = Path(__file__).parent.parent / ".env"
    if env_path.exists():
        load_dotenv(env_path)
except ImportError:
    pass

import oracledb
from sqlalchemy import create_engine, text
from sqlalchemy.pool import NullPool

oracle_url = os.environ.get("ORACLE_TEST_URL")
if not oracle_url:
    print("[FAIL] ORACLE_TEST_URL not set")
    sys.exit(1)

print("Oracle Schema Cleanup")
print("=" * 60)

engine = create_engine(oracle_url, poolclass=NullPool)

with engine.connect() as conn:
    # Get current user
    result = conn.execute(text("SELECT USER FROM DUAL"))
    current_user = result.scalar()
    print(f"[OK] Connected as: {current_user}")

    # Get all tables owned by current user
    result = conn.execute(
        text(
            "SELECT table_name FROM user_tables "
            "WHERE table_name NOT LIKE 'BIN$%' "  # Exclude recycle bin
            "ORDER BY table_name"
        )
    )
    tables = [row[0] for row in result]

    if not tables:
        print("[OK] No tables to drop")
    else:
        print(f"[INFO] Found {len(tables)} tables to drop:")
        for table in tables:
            print(f"  - {table}")

        # Drop all tables
        for table in tables:
            try:
                conn.execute(text(f"DROP TABLE {table} CASCADE CONSTRAINTS PURGE"))
                print(f"[OK] Dropped: {table}")
            except Exception as e:
                print(f"[WARN] Failed to drop {table}: {e}")

        conn.commit()

    # Verify cleanup
    result = conn.execute(text("SELECT COUNT(*) FROM user_tables WHERE table_name NOT LIKE 'BIN$%'"))
    remaining = result.scalar()

    if remaining == 0:
        print("=" * 60)
        print("[SUCCESS] Schema is clean - ready for fresh migration")
    else:
        print(f"[WARN] {remaining} tables still remain")
        sys.exit(1)
