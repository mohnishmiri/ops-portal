"""Test script to verify all AKS operations endpoints register on the router."""

import os
import sys
from unittest.mock import MagicMock

# Mock heavy dependencies before any app imports
for mod in [
    "app.core.database",
    "app.core.redis",
    "app.core.config",
    "app.middleware.audit",
    "app.middleware.rate_limit",
    "sqlalchemy",
    "sqlalchemy.orm",
    "redis",
    "redis.asyncio",
    "prometheus_client",
]:
    sys.modules[mod] = MagicMock()

sys.path.insert(0, os.getcwd())

from app.api.v1.endpoints.aks_operations import router  # noqa: E402

print(f"\nTotal routes on aks_operations.router: {len(router.routes)}")
print("=" * 60)
for r in router.routes:
    methods = sorted(r.methods - {"HEAD"}) if hasattr(r, "methods") else []
    print(f"  {','.join(methods):10s}  {r.path}  ({r.name})")

expected = [
    ("POST", "/deployments", "create_deployment"),
    ("PUT", "/deployments", "update_deployment"),
    ("DELETE", "/deployments", "delete_deployment"),
    ("GET", "/cronjobs/details", "get_cronjob_detail"),
    ("PUT", "/cronjobs", "update_cronjob"),
    ("DELETE", "/cronjobs", "delete_cronjob"),
]

print("\n" + "=" * 60)
print("Checking previously-missing endpoints:")
for method, path, name in expected:
    found = any(method in r.methods and r.path == path for r in router.routes if hasattr(r, "methods"))
    status = "FOUND" if found else "MISSING"
    print(f"  [{status}]  {method:6s} {path}  ({name})")
