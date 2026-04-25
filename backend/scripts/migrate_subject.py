"""One-time migration: add subject column to alert_notification_history."""

import asyncio
import ssl

import asyncpg


async def migrate():
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    conn = await asyncpg.connect(
        host="attcc-eastus2-prf1-db-psqlfs.postgres.database.azure.com",
        port=5432,
        user="psqladmin",
        password="Accenture@123",
        database="opsportal",
        ssl=ctx,
    )
    row = await conn.fetchrow(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_name='alert_notification_history' AND column_name='subject'"
    )
    if row:
        print("subject column already exists")
    else:
        await conn.execute("ALTER TABLE alert_notification_history ADD COLUMN subject VARCHAR(500)")
        print("Added subject column to alert_notification_history")
    await conn.close()


asyncio.run(migrate())
