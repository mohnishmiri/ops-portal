"""
Database Configuration and Connection Management.

Provides:
- Async SQLAlchemy engine with connection pooling
- Session factory for database operations
- FastAPI dependency injection (get_db)
- Connection health checks and graceful degradation
- Automatic table creation at startup
- Auto-reconnection when the database becomes available after a failed startup
"""

import ssl
import time
from collections.abc import AsyncGenerator

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import settings

logger = structlog.get_logger(__name__)

# Global engine and session factory
_engine: AsyncEngine | None = None
_SessionLocal: async_sessionmaker | None = None
_db_connected: bool = False

# Auto-reconnection: cooldown prevents hammering when DB is truly down.
_last_reconnect_attempt: float = 0.0
_RECONNECT_COOLDOWN_SECONDS: float = 30.0


async def init_db() -> None:
    """Initialize database connection pool and create tables (called at startup)."""
    global _engine, _SessionLocal, _db_connected

    try:
        logger.info(
            "Initializing database connection",
            url=settings.DATABASE_URL.split("@")[0] + "@...",
        )

        # Build connect_args — Azure PostgreSQL Flexible Server requires SSL
        connect_args: dict = {
            "timeout": 30,
            "command_timeout": 30,
        }
        if "ssl=require" in settings.DATABASE_URL or "sslmode=require" in settings.DATABASE_URL:
            ssl_ctx = ssl.create_default_context()
            ssl_ctx.check_hostname = False
            ssl_ctx.verify_mode = ssl.CERT_NONE  # Azure Flex Server uses MS-managed certs
            connect_args["ssl"] = ssl_ctx

        # Strip ssl= from URL query since we pass it via connect_args
        db_url = settings.DATABASE_URL.replace("?ssl=require", "").replace("&ssl=require", "")

        # Create async engine with connection pooling
        _engine = create_async_engine(
            db_url,
            echo=settings.DB_ECHO,
            pool_size=settings.DB_POOL_SIZE,
            max_overflow=settings.DB_MAX_OVERFLOW,
            pool_recycle=settings.DB_POOL_RECYCLE,
            pool_timeout=settings.DB_POOL_TIMEOUT,
            pool_pre_ping=True,
            connect_args=connect_args,
        )

        # Create session factory
        _SessionLocal = async_sessionmaker(
            _engine,
            class_=AsyncSession,
            expire_on_commit=False,
            autocommit=False,
            autoflush=False,
        )

        # Test connection
        async with _engine.begin() as conn:
            await conn.execute(text("SELECT 1"))

        _db_connected = True
        logger.info("Database connection established")

        # Auto-create tables if they don't exist
        await create_tables()

    except Exception as e:
        logger.error("Failed to connect to database", error=str(e))
        _db_connected = False
        _engine = None
        _SessionLocal = None
        # Don't raise — allow app to run without database for testing


async def create_tables() -> None:
    """Create all database tables (idempotent — uses IF NOT EXISTS)."""
    if _engine is None:
        return

    try:
        from app.models.database import Base

        async with _engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            # Backfill columns added after the original table was created. CREATE TABLE
            # is idempotent, but it will not add newly introduced columns to existing tables.
            await conn.execute(
                text(
                    """
                    ALTER TABLE IF EXISTS alert_schedule_configs
                    ADD COLUMN IF NOT EXISTS check_pg_thresholds BOOLEAN NOT NULL DEFAULT TRUE
                    """
                )
            )
            await conn.execute(
                text(
                    """
                    ALTER TABLE IF EXISTS custom_expiry_alert_configs
                    ADD COLUMN IF NOT EXISTS environment VARCHAR(20)
                    """
                )
            )
            await conn.execute(
                text(
                    """
                    ALTER TABLE IF EXISTS aks_pod_checksums
                    ADD COLUMN IF NOT EXISTS image_digests JSONB
                    """
                )
            )
            # Backfill RBAC columns added to the resources table (Apr 2026)
            await conn.execute(
                text(
                    """
                    ALTER TABLE IF EXISTS resources
                    ADD COLUMN IF NOT EXISTS parent_id INTEGER REFERENCES resources(id)
                    """
                )
            )
            await conn.execute(
                text(
                    """
                    ALTER TABLE IF EXISTS resources
                    ADD COLUMN IF NOT EXISTS route_path VARCHAR(500)
                    """
                )
            )
            await conn.execute(
                text(
                    """
                    ALTER TABLE IF EXISTS resources
                    ADD COLUMN IF NOT EXISTS is_system BOOLEAN NOT NULL DEFAULT FALSE
                    """
                )
            )
            # Drop the old global unique index on environment_sequences.name
            # (replaced by composite unique on name+cluster_id+namespace)
            await conn.execute(
                text(
                    """
                    DROP INDEX IF EXISTS ix_environment_sequences_name
                    """
                )
            )
            await conn.execute(
                text(
                    """
                    ALTER TABLE IF EXISTS environment_sequences
                    DROP CONSTRAINT IF EXISTS environment_sequences_name_key
                    """
                )
            )
            # Fix stale step_details: completed/failed executions with pending steps
            await conn.execute(
                text(
                    """
                    UPDATE environment_execution_history
                    SET step_details = (
                        SELECT jsonb_agg(
                            CASE
                                WHEN elem->>'status' = 'pending' OR elem->>'status' = 'running'
                                THEN jsonb_set(elem, '{status}', to_jsonb(status))
                                ELSE elem
                            END
                        )
                        FROM jsonb_array_elements(step_details) AS elem
                    )
                    WHERE status IN ('completed', 'failed', 'rolled_back')
                      AND step_details IS NOT NULL
                      AND step_details::text LIKE '%pending%'
                    """
                )
            )
            # Backfill environment_scope column on permissions table (Jun 2026)
            await conn.execute(
                text(
                    """
                    ALTER TABLE IF EXISTS permissions
                    ADD COLUMN IF NOT EXISTS environment_scope VARCHAR(20) NOT NULL DEFAULT 'all'
                    """
                )
            )
            await conn.execute(
                text(
                    """
                    ALTER TABLE IF EXISTS cert_certificates
                    ADD COLUMN IF NOT EXISTS has_private_key BOOLEAN DEFAULT FALSE
                    """
                )
            )
            # Create teams table if it doesn't exist
            await conn.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS teams (
                        id SERIAL PRIMARY KEY,
                        team_name VARCHAR(255) NOT NULL UNIQUE,
                        description TEXT,
                        created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                        updated_at TIMESTAMP NOT NULL DEFAULT NOW()
                    )
                    """
                )
            )
            # Create team_memberships table if it doesn't exist
            await conn.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS team_memberships (
                        id SERIAL PRIMARY KEY,
                        team_id INTEGER NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
                        user_id VARCHAR(255) NOT NULL,
                        user_email VARCHAR(255),
                        created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                        CONSTRAINT uq_team_user UNIQUE (team_id, user_id)
                    )
                    """
                )
            )
            await conn.execute(
                text(
                    """
                    CREATE INDEX IF NOT EXISTS ix_team_memberships_team_id ON team_memberships(team_id)
                    """
                )
            )
            await conn.execute(
                text(
                    """
                    CREATE INDEX IF NOT EXISTS ix_team_memberships_user_id ON team_memberships(user_id)
                    """
                )
            )
        logger.info("Database tables verified/created successfully")
    except Exception as e:
        logger.error("Failed to create database tables", error=str(e))


async def close_db() -> None:
    """Close database connection pool (called at shutdown)."""
    global _engine, _db_connected

    if _engine:
        try:
            await _engine.dispose()
            logger.info("Database connection pool closed")
            _db_connected = False
        except Exception as e:
            logger.error("Error closing database", error=str(e))


async def _dispose_stale_pool() -> None:
    """Dispose stale connections so the next request gets a fresh one."""
    global _engine
    if _engine is not None:
        try:
            await _engine.dispose()
            logger.info("Stale connection pool disposed, new connections will be created on demand")
        except Exception as exc:
            logger.error("Failed to dispose pool", error=str(exc))


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """
    FastAPI dependency to get database session.

    Yields:
        AsyncSession: Active database session, or None if DB is unavailable

    Example:
        @router.get("/items")
        async def get_items(db: AsyncSession = Depends(get_db)):
            if db is None:
                # Handle offline mode
                return {"error": "Database unavailable"}
            ...
    """
    global _db_connected, _last_reconnect_attempt

    if not _db_connected or _SessionLocal is None:
        # Attempt auto-reconnection with a cooldown to avoid hammering a
        # genuinely-unreachable DB on every single request.
        now = time.monotonic()
        if now - _last_reconnect_attempt >= _RECONNECT_COOLDOWN_SECONDS:
            _last_reconnect_attempt = now
            logger.info("database_reconnect_attempt", reason="db not connected, retrying")
            await init_db()

    if not _db_connected or _SessionLocal is None:
        logger.warning("Database not available, returning mock session")
        yield None
        return

    try:
        async with _SessionLocal() as session:
            try:
                yield session
            except Exception as e:
                logger.error("Database error in session", error=str(e))
                await session.rollback()
                # Dispose stale pool connections on OS/TCP-level errors
                # so the NEXT request gets a fresh connection
                if isinstance(e, OSError) or "semaphore" in str(e).lower():
                    logger.warning(
                        "Stale connection detected, disposing pool",
                        error_type=type(e).__name__,
                    )
                    await _dispose_stale_pool()
                raise
            finally:
                await session.close()
    except OSError as e:
        # Session creation itself failed (TCP/semaphore error)
        logger.warning("Session creation failed, disposing pool", error=str(e))
        await _dispose_stale_pool()
        yield None


# ============================================================================
# Async Context Managers for Standalone Usage (outside FastAPI)
# ============================================================================


async def get_session() -> AsyncSession:
    """Get a new database session (for non-FastAPI contexts)."""
    if not _db_connected or _SessionLocal is None:
        raise RuntimeError("Database not connected")

    async with _SessionLocal() as session:
        return session


async def get_standalone_session() -> AsyncSession | None:
    """Get a new independent session, or None if DB unavailable.

    Use for fire-and-forget writes (e.g. audit logging) that must not
    interfere with the request's main session.
    """
    if not _db_connected or _SessionLocal is None:
        return None
    return _SessionLocal()


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """
    Async generator for database session in background tasks/schedulers.

    Use this in non-FastAPI contexts where you need a yielded session:
        async for db in get_db_session():
            # use db
    """
    if not _db_connected or _SessionLocal is None:
        raise RuntimeError("Database not connected")

    async with _SessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


# ============================================================================
# Health Check
# ============================================================================


async def check_db_health() -> dict:
    """Check database connection health."""
    if not _db_connected or _engine is None:
        return {
            "status": "unhealthy",
            "message": "Database not connected",
            "connection_string": settings.DATABASE_URL.split("@")[0] + "@...",
        }

    try:
        async with _engine.begin() as conn:
            result = await conn.execute(text("SELECT 1 as health_check"))
            result.fetchone()
        return {
            "status": "healthy",
            "message": "Database connection working",
        }
    except Exception as e:
        return {
            "status": "unhealthy",
            "message": f"Health check failed: {str(e)}",
        }
