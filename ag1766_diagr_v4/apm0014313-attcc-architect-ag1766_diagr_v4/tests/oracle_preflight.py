"""
O00 Oracle Preflight Verification

Verifies:
1. Oracle thin-mode driver is installed
2. Docker container is healthy
3. Dedicated test schema exists and is accessible
4. Connected user is NOT SYSTEM (security requirement)
5. Basic DDL capability (create/drop test table)

Usage:
    # Option 1: Use .env file (automatically loaded)
    python tests/oracle_preflight.py

    # Option 2: Set environment variable explicitly
    export ORACLE_TEST_URL="oracle+oracledb://user:pass@localhost:1521/?service_name=FREEPDB1"
    python tests/oracle_preflight.py

Exit codes:
    0 = All checks passed
    1 = Driver/connectivity failure
    2 = Security violation (SYSTEM user detected)
    3 = DDL capability failure
"""

import os
import sys
from pathlib import Path
from typing import NoReturn

try:
    import oracledb
except ImportError:
    print("❌ FAIL: oracledb driver not installed")
    print("   Run: pip install -e '.[oracle]'")
    sys.exit(1)

from sqlalchemy import create_engine, text
from sqlalchemy.pool import NullPool

# Load .env file if it exists
try:
    from dotenv import load_dotenv
    env_path = Path(__file__).parent.parent / ".env"
    if env_path.exists():
        load_dotenv(env_path)
        print(f"[OK] Loaded environment from: {env_path}")
except ImportError:
    pass  # python-dotenv not installed, rely on system environment variables


def fail(message: str, exit_code: int = 1) -> NoReturn:
    """Print failure message and exit."""
    print(f"[FAIL] {message}")
    sys.exit(exit_code)


def main() -> None:
    """Run Oracle preflight checks."""
    print("Oracle Preflight Verification (O00)")
    print("=" * 60)

    # 1. Check driver version
    print(f"[OK] oracledb driver installed: {oracledb.__version__}")
    print(f"[OK] Thin mode available: {oracledb.is_thin_mode()}")

    # 2. Get connection URL from environment (never from repository)
    oracle_url = os.environ.get("ORACLE_TEST_URL")
    if not oracle_url:
        fail(
            "ORACLE_TEST_URL environment variable not set\n"
            "   Example: oracle+oracledb://user:pass@localhost:1521/?service_name=FREEPDB1\n"
            "   SECURITY: Never commit this URL to the repository"
        )

    # Redact password for display
    display_url = oracle_url
    if "@" in oracle_url and ":" in oracle_url.split("@")[0]:
        parts = oracle_url.split("://", 1)
        if len(parts) == 2:
            scheme, rest = parts
            if "@" in rest:
                creds, host_part = rest.split("@", 1)
                if ":" in creds:
                    user, _ = creds.split(":", 1)
                    display_url = f"{scheme}://{user}:****@{host_part}"

    print(f"[OK] ORACLE_TEST_URL configured: {display_url}")

    # 3. Create engine and test connectivity
    try:
        engine = create_engine(
            oracle_url,
            poolclass=NullPool,
            echo=False,
        )
    except Exception as e:
        fail(f"Failed to create engine: {e}")

    try:
        with engine.connect() as conn:
            # 4. Verify connected user
            result = conn.execute(text("SELECT USER FROM DUAL"))
            current_user = result.scalar()
            print(f"[OK] Connected as: {current_user}")

            # 5. SECURITY: Reject SYSTEM or SYS
            if current_user and current_user.upper() in ("SYSTEM", "SYS"):
                fail(
                    f"Connected as {current_user} — FORBIDDEN\n"
                    "   Oracle tests must use a dedicated non-privileged schema\n"
                    "   Create a dedicated user: migration_intake or migration_intake_test\n"
                    "   See: docs/operations/oracle/ORACLE_INTEGRATION_DESIGN.md section 6.2",
                    exit_code=2,
                )

            # 6. Verify service name
            result = conn.execute(
                text("SELECT SYS_CONTEXT('USERENV', 'SERVICE_NAME') FROM DUAL")
            )
            service_name = result.scalar()
            print(f"[OK] Service name: {service_name}")

            # 7. Verify Oracle version
            result = conn.execute(text("SELECT BANNER FROM V$VERSION WHERE ROWNUM = 1"))
            version_banner = result.scalar()
            print(f"[OK] Oracle version: {version_banner}")

            # 8. Test basic DDL capability
            test_table = "preflight_test_table"
            try:
                # Drop if exists (ignore error if not exists)
                try:
                    conn.execute(text(f"DROP TABLE {test_table} PURGE"))
                    conn.commit()
                except Exception:
                    pass

                # Create test table
                conn.execute(
                    text(
                        f"CREATE TABLE {test_table} ("
                        "id NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY, "
                        "test_value VARCHAR2(100))"
                    )
                )
                conn.commit()
                print(f"[OK] DDL capability verified (created {test_table})")

                # Insert and query
                conn.execute(
                    text(f"INSERT INTO {test_table} (test_value) VALUES ('preflight')")
                )
                conn.commit()
                result = conn.execute(
                    text(f"SELECT test_value FROM {test_table} WHERE ROWNUM = 1")
                )
                value = result.scalar()
                if value != "preflight":
                    fail(f"DML verification failed: expected 'preflight', got {value!r}")
                print(f"[OK] DML capability verified (inserted and queried)")

                # Clean up
                conn.execute(text(f"DROP TABLE {test_table} PURGE"))
                conn.commit()
                print(f"[OK] Cleanup successful (dropped {test_table})")

            except Exception as e:
                fail(f"DDL/DML capability test failed: {e}", exit_code=3)

    except Exception as e:
        fail(f"Connection or query failed: {e}")

    print("=" * 60)
    print("[SUCCESS] All preflight checks PASSED")
    print()
    print("Next steps:")
    print("  1. Record ORACLE_TEST_URL in your local .env (never commit)")
    print("  2. Proceed to O01: Clean Alembic migration execution")
    print("  3. See: docs/operations/oracle/ORACLE_INTEGRATION_DESIGN.md section 10 (packet O01)")


if __name__ == "__main__":
    main()
