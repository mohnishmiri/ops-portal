"""One-time migration: add subject column to alert_notification_history.

Usage:
  DATABASE_URL=postgresql+asyncpg://... uv run python scripts/migrate_subject.py
"""

import asyncio
import os

import asyncpg


def _asyncpg_url() -> str:
    raw = os.environ.get("DATABASE_URL", "").strip()
    if not raw:
        raise SystemExit("Set DATABASE_URL before running this migration.")
    return raw.replace("postgresql+asyncpg://", "postgresql://")


async def migrate() -> None:
    conn = await asyncpg.connect(_asyncpg_url())
    try:
        row = await conn.fetchrow(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name='alert_notification_history' AND column_name='subject'"
        )
        if row:
            print("subject column already exists")
        else:
            await conn.execute(
                "ALTER TABLE alert_notification_history ADD COLUMN subject VARCHAR(500)"
            )
            print("Added subject column to alert_notification_history")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(migrate())
