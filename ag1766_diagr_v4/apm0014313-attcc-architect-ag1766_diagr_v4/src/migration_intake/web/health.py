"""
/health/live and /health/ready endpoints (O02 — Liveness and Readiness probes).

Design rules:
- /health/live: no external dependency checks; always 200 if the process responds.
- /health/ready: strict checks on DB, schema, evidence storage, and catalog.
  Returns 503 on any failure.
- Never expose connection strings, filesystem paths, schema names, or stack
  traces in response bodies.  Only {"ok": true/false} per check.
- Health routes are infrastructure probes: no authentication required.
- LLM availability is excluded from readiness (LLM is optional; never fails).

Architecture (sections 58.5 and 59):
  checks performed by /health/ready
    database  — SELECT 1 against the configured engine
    schema    — alembic_version matches head revision (check_schema_current)
    storage   — evidence root exists and accepts a write/delete cycle
    catalog   — at least one CatalogRelease with pub_state='PUBLISHED'

Response shapes:
  200 {"status": "ready",    "checks": {"database": {"ok": true}, ...}}
  503 {"status": "degraded", "checks": {"database": {"ok": false}, ...}}

Liveness always returns:
  200 {"status": "ok"}
"""
from __future__ import annotations

import contextlib
import os
import tempfile
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from sqlalchemy import func, select, text

health_router = APIRouter(prefix="/health", tags=["Health"])


# ---------------------------------------------------------------------------
# /health/live
# ---------------------------------------------------------------------------


@health_router.get("/live")
async def liveness() -> JSONResponse:
    """
    Liveness probe — no external checks.

    Returns 200 immediately.  The presence of a response proves the process
    and event loop are alive.  External systems (DB, storage, catalog) are
    never queried here; that is the readiness probe's responsibility.
    """
    return JSONResponse(content={"status": "ok"}, status_code=200)


# ---------------------------------------------------------------------------
# /health/ready
# ---------------------------------------------------------------------------


@health_router.get("/ready")
async def readiness(request: Request) -> JSONResponse:
    """
    Readiness probe — DB, schema, evidence storage, and catalog checks.

    Uses the SQLAlchemy engine stored in app.state.engine and the Settings
    object in app.state.settings.  Both are wired by the application factory
    in main.py.

    Failure semantics:
      - Each check is isolated in its own try/except block.
      - A failure in one check does not prevent subsequent checks from running.
      - No error messages, paths, or connection strings are included in the
        response body.
    """
    engine = request.app.state.engine
    settings = request.app.state.settings

    checks: dict[str, Any] = {}
    all_ok = True

    # ------------------------------------------------------------------
    # 1. Database connectivity — SELECT 1
    # ------------------------------------------------------------------
    try:
        with engine.connect() as conn:
            # Compiles to "SELECT ... FROM DUAL" on Oracle, which rejects a bare SELECT 1.
            conn.scalar(select(literal(1)))
        checks["database"] = {"ok": True}
    except Exception:
        checks["database"] = {"ok": False}
        all_ok = False

    # ------------------------------------------------------------------
    # 2. Schema version — alembic_version at head revision
    # ------------------------------------------------------------------
    try:
        from migration_intake.persistence.database import check_schema_current

        schema_ok: bool = check_schema_current(engine)
        checks["schema"] = {"ok": schema_ok}
        if not schema_ok:
            all_ok = False
    except Exception:
        checks["schema"] = {"ok": False}
        all_ok = False

    # ------------------------------------------------------------------
    # 3. Evidence storage — directory exists and accepts a write/delete
    # ------------------------------------------------------------------
    try:
        evidence_root = settings.evidence_root
        if evidence_root.exists() and evidence_root.is_dir():
            # Atomic write-and-delete: proves the filesystem is writable.
            # mkstemp avoids NamedTemporaryFile's Windows sharing restriction.
            fd, tmp_name = tempfile.mkstemp(
                dir=str(evidence_root),
                prefix=".health_check_",
            )
            try:
                os.write(fd, b"ok")
            finally:
                os.close(fd)
                with contextlib.suppress(OSError):
                    Path(tmp_name).unlink()
            checks["storage"] = {"ok": True}
        else:
            checks["storage"] = {"ok": False}
            all_ok = False
    except Exception:
        checks["storage"] = {"ok": False}
        all_ok = False

    # ------------------------------------------------------------------
    # 4. Catalog release — at least one PUBLISHED CatalogRelease row
    # ------------------------------------------------------------------
    try:
        from migration_intake.persistence.models import CatalogRelease

        with engine.connect() as conn:
            stmt = (
                select(func.count())
                .select_from(CatalogRelease)
                .where(CatalogRelease.pub_state == "PUBLISHED")
            )
            count: int = conn.scalar(stmt) or 0
        catalog_ok = count > 0
        checks["catalog"] = {"ok": catalog_ok}
        if not catalog_ok:
            all_ok = False
    except Exception:
        checks["catalog"] = {"ok": False}
        all_ok = False

    # ------------------------------------------------------------------
    # Response
    # ------------------------------------------------------------------
    status_code = 200 if all_ok else 503
    return JSONResponse(
        content={
            "status": "ready" if all_ok else "degraded",
            "checks": checks,
        },
        status_code=status_code,
    )
