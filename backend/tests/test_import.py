"""Quick smoke test — run with: python test_import.py"""

import sys

print(f"Python: {sys.version}")
try:
    from app.main import create_application

    print("Import OK")
    app = create_application()
    print(f"App created: {app.title}")
except Exception as e:
    print(f"ERROR: {e}")
    import traceback

    traceback.print_exc()
