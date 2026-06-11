"""SyncWorker — background queue runner for amortized + leadership syncs.

Decouples Azure sync work from the HTTP request path. Endpoints insert a
``sync_jobs`` row and return immediately; this worker picks oldest queued
jobs and executes them on a dedicated DB session. Failures don't take the
request thread with them, and a slow Azure call can't time the user out.

Lifecycle: ``start_sync_worker()`` is called from the FastAPI lifespan on
startup, ``stop_sync_worker()`` on shutdown. Only one worker task runs
per process.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from datetime import datetime, timedelta

import structlog
from sqlalchemy import select, update

from app.core import database as _db_module
from app.models.database import SyncJob


def _get_session_factory():
    """Look up the session factory dynamically.

    ``from app.core.database import _SessionLocal`` would capture ``None``
    at module-load time because init_db() runs later — Python imports are
    snapshots, not live references. Reading the attribute through the
    module object resolves the current value on every call.
    """
    return getattr(_db_module, "_SessionLocal", None)


logger = structlog.get_logger(__name__)

POLL_INTERVAL_SECONDS = 5
MAX_ATTEMPTS = 3
ABANDONED_RUNNING_TIMEOUT_MINUTES = 120

_worker_task: asyncio.Task | None = None
_shutdown_event: asyncio.Event | None = None


async def _expire_abandoned_jobs() -> None:
    """Recover jobs left in 'running' by a crashed/restarted process."""
    session_factory = _get_session_factory()
    if session_factory is None:
        return
    cutoff = datetime.utcnow() - timedelta(minutes=ABANDONED_RUNNING_TIMEOUT_MINUTES)
    try:
        async with session_factory() as session:
            result = await session.execute(
                update(SyncJob)
                .where(SyncJob.status == "running", SyncJob.started_at < cutoff)
                .values(
                    status="failed",
                    completed_at=datetime.utcnow(),
                    last_error="abandoned: worker restarted while job was running",
                )
            )
            expired = getattr(result, "rowcount", 0) or 0
            if expired:
                await session.commit()
                logger.warning("sync_worker_expired_running_jobs", count=expired)
    except Exception as exc:
        logger.warning("sync_worker_expire_failed", error=str(exc)[:200])


async def _claim_next_job() -> SyncJob | None:
    """Pick the oldest queued job and atomically flip it to 'running'.

    Uses SELECT ... FOR UPDATE SKIP LOCKED so multiple replicas can run
    workers without claiming the same queued job.
    """
    session_factory = _get_session_factory()
    if session_factory is None:
        return None
    async with session_factory() as session:
        result = await session.execute(
            select(SyncJob)
            .where(SyncJob.status == "queued")
            .order_by(SyncJob.enqueued_at.asc())
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        job = result.scalars().first()
        if job is None:
            return None
        # Claim it
        job.status = "running"
        job.started_at = datetime.utcnow()
        job.attempts = (job.attempts or 0) + 1
        await session.commit()
        await session.refresh(job)
        # Detach for use after session close
        session.expunge(job)
        return job


async def _run_job(job: SyncJob) -> tuple[str, str | None, dict | None]:
    """Dispatch a job to the right service. Returns (status, error, result)."""
    payload = json.loads(job.payload or "{}")
    triggered_by = job.triggered_by or "queue"

    session_factory = _get_session_factory()
    if session_factory is None:
        return "failed", "session factory not initialised", None

    if job.job_type == "amortized":
        from app.services.amortized_cost_sync_service import AmortizedCostSyncService

        async with session_factory() as session:
            svc = AmortizedCostSyncService(session)
            result = await svc.full_sync(
                months=int(payload.get("months", 2)),
                triggered_by=triggered_by,
                force=bool(payload.get("force", False)),
            )
            status = result.get("status", "failed")
            err = result.get("error") if status != "completed" else None
            return ("completed" if status == "completed" else "failed", err, result)

    if job.job_type == "leadership":
        from app.services.leadership_sync_service import LeadershipSyncService

        async with session_factory() as session:
            svc = LeadershipSyncService(session)
            result = await svc.full_sync(triggered_by=triggered_by)
            status = result.get("status", "failed")
            err = result.get("error") if status != "completed" else None
            return ("completed" if status == "completed" else "failed", err, result)

    return "failed", f"unknown job_type: {job.job_type}", None


async def _finalize_job(job_id: int, status: str, error: str | None, result: dict | None) -> None:
    session_factory = _get_session_factory()
    if session_factory is None:
        return
    async with session_factory() as session:
        await session.execute(
            update(SyncJob)
            .where(SyncJob.id == job_id)
            .values(
                status=status,
                completed_at=datetime.utcnow(),
                last_error=(error[:2000] if error else None),
                result=(json.dumps(result, default=str) if result is not None else None),
            )
        )
        await session.commit()


async def _requeue_for_retry(job_id: int, error: str) -> None:
    session_factory = _get_session_factory()
    if session_factory is None:
        return
    async with session_factory() as session:
        await session.execute(
            update(SyncJob)
            .where(SyncJob.id == job_id)
            .values(status="queued", last_error=error[:2000], started_at=None)
        )
        await session.commit()
        logger.info("sync_worker_requeued_for_retry", job_id=job_id)


async def _worker_loop() -> None:
    logger.info("sync_worker_started", poll_interval=POLL_INTERVAL_SECONDS)
    assert _shutdown_event is not None
    # Sweep abandoned jobs once on startup
    await _expire_abandoned_jobs()

    while not _shutdown_event.is_set():
        try:
            job = await _claim_next_job()
            if job is None:
                # Idle — wait for either a shutdown signal or the next poll tick.
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(_shutdown_event.wait(), timeout=POLL_INTERVAL_SECONDS)
                continue

            logger.info(
                "sync_worker_job_started",
                job_id=job.id,
                job_type=job.job_type,
                attempts=job.attempts,
                triggered_by=job.triggered_by,
            )
            try:
                status, error, result = await _run_job(job)
            except Exception as exc:
                logger.error(
                    "sync_worker_job_crashed",
                    job_id=job.id,
                    job_type=job.job_type,
                    error=str(exc)[:500],
                )
                status, error, result = "failed", f"{type(exc).__name__}: {exc}"[:500], None

            if status != "completed" and (job.attempts or 0) < MAX_ATTEMPTS:
                await _requeue_for_retry(job.id, error or "unknown error")
            else:
                await _finalize_job(job.id, status, error, result)
                logger.info(
                    "sync_worker_job_finished",
                    job_id=job.id,
                    status=status,
                    attempts=job.attempts,
                )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.error("sync_worker_loop_error", error=str(exc)[:500])
            # Backoff on unexpected loop-level errors so we don't tight-loop.
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(_shutdown_event.wait(), timeout=10)

    logger.info("sync_worker_stopped")


async def start_sync_worker() -> None:
    """Start the background worker. Safe to call multiple times."""
    global _worker_task, _shutdown_event
    if _worker_task is not None and not _worker_task.done():
        return
    _shutdown_event = asyncio.Event()
    _worker_task = asyncio.create_task(_worker_loop(), name="sync-worker")


async def stop_sync_worker() -> None:
    """Signal shutdown and wait briefly for the worker to drain."""
    global _worker_task, _shutdown_event
    if _shutdown_event is not None:
        _shutdown_event.set()
    if _worker_task is not None:
        try:
            await asyncio.wait_for(_worker_task, timeout=15)
        except TimeoutError:
            _worker_task.cancel()
            logger.warning("sync_worker_stop_timed_out_cancelled")
        except Exception as exc:
            logger.warning("sync_worker_stop_error", error=str(exc)[:200])
    _worker_task = None
    _shutdown_event = None


async def enqueue_job(
    job_type: str,
    *,
    payload: dict | None = None,
    triggered_by: str | None = None,
    idempotency_key: str | None = None,
    dedup_session=None,
) -> int:
    """Insert a queued job row and return its ID.

    Idempotency: if ``idempotency_key`` is given and a row with the same
    (job_type, idempotency_key) is already queued or running, returns its
    existing ID instead of creating a duplicate.
    """
    session_factory = _get_session_factory()
    if session_factory is None:
        raise RuntimeError("database session factory not initialised")

    async with session_factory() as session:
        if idempotency_key:
            result = await session.execute(
                select(SyncJob)
                .where(
                    SyncJob.job_type == job_type,
                    SyncJob.idempotency_key == idempotency_key,
                    SyncJob.status.in_(["queued", "running"]),
                )
                .order_by(SyncJob.enqueued_at.desc())
                .limit(1)
            )
            existing = result.scalars().first()
            if existing:
                return existing.id

        job = SyncJob(
            job_type=job_type,
            status="queued",
            idempotency_key=idempotency_key,
            payload=json.dumps(payload or {}),
            triggered_by=triggered_by,
        )
        session.add(job)
        await session.commit()
        await session.refresh(job)
        return job.id
