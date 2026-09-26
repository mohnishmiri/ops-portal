"""Quick debug script to test Oracle connection with explicit credentials."""

import sys
from pathlib import Path

try:
    from dotenv import load_dotenv
    env_path = Path(__file__).parent.parent / ".env"
    if env_path.exists():
        load_dotenv(env_path)
        print(f"[OK] Loaded .env from: {env_path}")
except ImportError:
    print("[WARN] python-dotenv not available")

import os

# Show what we loaded (redacted)
oracle_url = os.environ.get("ORACLE_TEST_URL", "NOT SET")
if oracle_url and oracle_url != "NOT SET":
    # Redact password
    if "@" in oracle_url and "://" in oracle_url:
        parts = oracle_url.split("://", 1)
        if len(parts) == 2:
            scheme, rest = parts
            if "@" in rest:
                creds, host = rest.split("@", 1)
                if ":" in creds:
                    user, pwd = creds.split(":", 1)
                    print(f"[DEBUG] URL scheme: {scheme}")
                    print(f"[DEBUG] Username: {user}")
                    print(f"[DEBUG] Password length: {len(pwd)} characters")
                    print(f"[DEBUG] Host/service: {host}")
                    print(f"[DEBUG] Full URL (redacted): {scheme}://{user}:{'*' * len(pwd)}@{host}")

# Now try direct connection with oracledb
try:
    import oracledb
    print(f"\n[OK] oracledb version: {oracledb.__version__}")

    # Parse the URL manually
    if oracle_url and "://" in oracle_url:
        parts = oracle_url.split("://", 1)[1]  # Remove scheme
        creds_host = parts.split("@")
        if len(creds_host) == 2:
            creds, host_part = creds_host
            username, password = creds.split(":", 1)

            # Parse host:port/?service_name=X
            if "?" in host_part:
                host_port, params = host_part.split("?", 1)
                host, port = host_port.split(":")
                # Extract service_name
                service_name = None
                for param in params.split("&"):
                    if param.startswith("service_name="):
                        service_name = param.split("=", 1)[1]

                print(f"\n[DEBUG] Attempting direct connection:")
                print(f"  Host: {host}")
                print(f"  Port: {port}")
                print(f"  Service: {service_name}")
                print(f"  User: {username}")
                print(f"  Password: {'*' * len(password)}")

                try:
                    conn = oracledb.connect(
                        user=username,
                        password=password,
                        host=host,
                        port=int(port),
                        service_name=service_name
                    )
                    print(f"\n[SUCCESS] Direct connection worked!")

                    cursor = conn.cursor()
                    cursor.execute("SELECT USER FROM DUAL")
                    current_user = cursor.fetchone()[0]
                    print(f"[OK] Connected as: {current_user}")

                    cursor.close()
                    conn.close()

                except Exception as e:
                    print(f"\n[FAIL] Direct connection failed: {e}")
                    print(f"\n[HINT] Common issues:")
                    print(f"  1. Password mismatch - verify in SQL Developer:")
                    print(f"     ALTER USER {username} IDENTIFIED BY \"your_password\";")
                    print(f"  2. Case sensitivity - Oracle usernames are uppercase by default")
                    print(f"  3. Account locked - check: SELECT account_status FROM dba_users WHERE username = '{username.upper()}';")
                    sys.exit(1)

except ImportError:
    print("[FAIL] oracledb not installed")
    sys.exit(1)
