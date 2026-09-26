"""
Web layer for Migration Intake.

Contains FastAPI routers for HTTP endpoints.  Routes do not write SQL and
do not inspect environment variables directly — all dependencies are injected
via app.state or FastAPI Depends.

Exported routers:
- health_router: /health/live and /health/ready probes (O02)
"""
from __future__ import annotations
