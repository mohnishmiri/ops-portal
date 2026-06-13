"""
KeyVault Sync Service — Syncs Azure Key Vault data into PostgreSQL.

Provides:
- Full sync: discovers all vaults and their secrets/keys/certificates
- Vault-level sync: refreshes a single vault's items
- Incremental sync after mutations (create/update/delete)
- Periodic background sync via APScheduler
- Dashboard and list queries served from PG for fast loading
- Automatic startup sync when DB is empty or stale
- Retry logic with exponential backoff for failed vaults
"""

import asyncio
from datetime import datetime, timedelta
from typing import Any, cast

import structlog
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db_session
from app.models.database import (
    KeyVaultCertSnapshot,
    KeyVaultKeySnapshot,
    KeyVaultSecretSnapshot,
    KeyVaultSnapshot,
    KeyVaultSyncStatus,
)
from app.services.keyvault_service import KeyVaultService

logger = structlog.get_logger(__name__)

# Sync tuning constants
_SYNC_CONCURRENCY = 3  # Max concurrent vault syncs (lower = more reliable)
_SYNC_RETRY_ATTEMPTS = 3  # Retries per failed vault
_SYNC_RETRY_BASE_DELAY = 2.0  # Base delay (seconds) between retries (exponential)
_STALE_THRESHOLD_MINUTES = 60  # Consider data stale after this many minutes
_NON_BLOCKING_ITEM_FAILURES = frozenset({"certs"})


def _has_blocking_item_failures(item_failures: list[str]) -> bool:
    """Return whether a vault sync missed required inventory types."""
    return any(item_type not in _NON_BLOCKING_ITEM_FAILURES for item_type in item_failures)


class KeyVaultSyncService:
    """Manages syncing Azure Key Vault data to PostgreSQL."""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.kv = KeyVaultService()

    # ── Full Sync ──────────────────────────────────────────────────────

    async def full_sync(self, *, triggered_by: str = "manual") -> dict:
        """
        Full sync: pull all vaults and their items from Azure → PG.

        Each vault is synced in its own DB session to avoid concurrent
        session conflicts.  Failed vaults are retried up to 3 times
        with exponential backoff.
        """
        sync_record = KeyVaultSyncStatus(
            sync_type="full",
            status="running",
            started_at=datetime.utcnow(),
            triggered_by=triggered_by,
        )
        self.db.add(sync_record)
        await self.db.commit()
        await self.db.refresh(sync_record)

        try:
            # 1. Discover all vaults from Azure
            vaults = await self.kv.list_vaults(refresh=True)
            logger.info("kv_sync_vaults_discovered", count=len(vaults))

            # Track results
            current_uris: set[str] = set()
            total_secrets = 0
            total_keys = 0
            total_certs = 0
            failed_vaults: list[str] = []
            partially_synced_vaults: list[str] = []
            certificate_access_limited_vaults: list[str] = []

            # 2. Sync each vault in its own DB session (concurrency-limited)
            sem = asyncio.Semaphore(_SYNC_CONCURRENCY)

            async def _sync_one_isolated(vault: dict) -> dict | None:
                """Sync a single vault using its own DB session."""
                async with sem:
                    return await self._sync_vault_isolated(vault)

            results = await asyncio.gather(
                *[_sync_one_isolated(v) for v in vaults],
                return_exceptions=True,
            )

            # Collect successful syncs; queue failures for retry
            retry_queue: list[dict] = []
            for vault, result in zip(vaults, results, strict=False):
                if isinstance(result, Exception):
                    logger.warning(
                        "kv_sync_vault_failed_attempt_1",
                        vault=vault.get("name"),
                        error=str(result)[:300],
                    )
                    retry_queue.append(vault)
                elif result is None:
                    retry_queue.append(vault)
                else:
                    result_data = cast(dict[str, Any], result)
                    current_uris.add(vault["vault_uri"])
                    total_secrets += int(result_data.get("secrets", 0))
                    total_keys += int(result_data.get("keys", 0))
                    total_certs += int(result_data.get("certs", 0))
                    item_failures = cast(list[str], result_data.get("item_failures", []))
                    if item_failures:
                        if _has_blocking_item_failures(item_failures):
                            partially_synced_vaults.append(vault.get("name", "unknown"))
                        else:
                            certificate_access_limited_vaults.append(vault.get("name", "unknown"))

            # 3. Retry failed vaults with exponential backoff
            for attempt in range(2, _SYNC_RETRY_ATTEMPTS + 1):
                if not retry_queue:
                    break
                delay = _SYNC_RETRY_BASE_DELAY * (2 ** (attempt - 2))
                logger.info(
                    "kv_sync_retry_round",
                    attempt=attempt,
                    vaults_to_retry=len(retry_queue),
                    delay_seconds=delay,
                )
                await asyncio.sleep(delay)

                still_failing: list[dict] = []
                # Retry sequentially to be gentler on rate limits
                for vault in retry_queue:
                    try:
                        result = await self._sync_vault_isolated(vault)
                        if result is not None:
                            result_data = cast(dict[str, Any], result)
                            current_uris.add(vault["vault_uri"])
                            total_secrets += int(result_data.get("secrets", 0))
                            total_keys += int(result_data.get("keys", 0))
                            total_certs += int(result_data.get("certs", 0))
                            item_failures = cast(list[str], result_data.get("item_failures", []))
                            if item_failures:
                                if _has_blocking_item_failures(item_failures):
                                    partially_synced_vaults.append(vault.get("name", "unknown"))
                                else:
                                    certificate_access_limited_vaults.append(vault.get("name", "unknown"))
                            logger.info(
                                "kv_sync_vault_retry_success",
                                vault=vault.get("name"),
                                attempt=attempt,
                            )
                        else:
                            still_failing.append(vault)
                    except Exception as e:
                        logger.warning(
                            "kv_sync_vault_retry_failed",
                            vault=vault.get("name"),
                            attempt=attempt,
                            error=str(e)[:300],
                        )
                        still_failing.append(vault)
                retry_queue = still_failing

            # Record permanently failed vaults
            for vault in retry_queue:
                failed_vaults.append(vault.get("name", "unknown"))
                logger.error(
                    "kv_sync_vault_permanent_failure",
                    vault=vault.get("name"),
                    attempts=_SYNC_RETRY_ATTEMPTS,
                )

            # 4. Remove vaults that no longer exist in Azure
            # Only if we have ALL vault URIs from discovery (no permanent failures)
            all_azure_uris = {v["vault_uri"] for v in vaults}
            if current_uris:
                stale = await self.db.execute(
                    select(KeyVaultSnapshot).where(KeyVaultSnapshot.vault_uri.notin_(all_azure_uris))
                )
                for row in stale.scalars().all():
                    await self.db.delete(row)
                await self.db.commit()

            # 5. Update sync status
            sync_record.status = "completed" if not failed_vaults and not partially_synced_vaults else "partial"
            sync_record.completed_at = datetime.utcnow()
            sync_record.vaults_synced = len(current_uris)
            sync_record.secrets_synced = total_secrets
            sync_record.keys_synced = total_keys
            sync_record.certificates_synced = total_certs
            status_parts: list[str] = []
            if failed_vaults:
                status_parts.append(f"Failed vaults ({len(failed_vaults)}): {', '.join(failed_vaults[:10])}")
            if partially_synced_vaults:
                status_parts.append(
                    f"Vaults preserved from cache after item fetch failures ({len(partially_synced_vaults)}): {', '.join(partially_synced_vaults[:10])}"
                )
            sync_record.error_message = " | ".join(status_parts) if status_parts else None
            await self.db.commit()

            if certificate_access_limited_vaults:
                logger.info(
                    "kv_sync_certificate_access_limited",
                    vaults=len(certificate_access_limited_vaults),
                    names=certificate_access_limited_vaults[:10],
                )

            logger.info(
                "kv_sync_completed",
                vaults=len(current_uris),
                secrets=total_secrets,
                keys=total_keys,
                certs=total_certs,
                failed=len(failed_vaults),
                partial=len(partially_synced_vaults),
                certificate_access_limited=len(certificate_access_limited_vaults),
            )

            return {
                "status": sync_record.status,
                "vaults_synced": len(current_uris),
                "vaults_discovered": len(vaults),
                "vaults_failed": len(failed_vaults),
                "failed_vault_names": failed_vaults,
                "vaults_preserved": len(partially_synced_vaults),
                "partially_synced_vault_names": partially_synced_vaults,
                "certificate_access_limited": len(certificate_access_limited_vaults),
                "certificate_access_limited_vault_names": certificate_access_limited_vaults,
                "secrets_synced": total_secrets,
                "keys_synced": total_keys,
                "certificates_synced": total_certs,
                "duration_seconds": (sync_record.completed_at - sync_record.started_at).total_seconds(),
            }

        except Exception as e:
            sync_record.status = "failed"
            sync_record.completed_at = datetime.utcnow()
            sync_record.error_message = str(e)[:500]
            await self.db.commit()
            logger.error("kv_sync_failed", error=str(e))
            raise

    # ── Isolated Vault Sync (own DB session) ───────────────────────────

    async def _sync_vault_isolated(self, vault: dict) -> dict | None:
        """
        Sync a single vault in its own DB session.

        Returns counts dict on success, None on failure.
        Each vault gets a dedicated session to avoid concurrent
        SQLAlchemy session conflicts.
        """
        vault_name = vault.get("name", "unknown")
        vault_uri = vault.get("vault_uri", "")

        try:
            async for db in get_db_session():
                kv = KeyVaultService()

                # Upsert vault row
                result = await db.execute(select(KeyVaultSnapshot).where(KeyVaultSnapshot.vault_uri == vault_uri))
                vault_row = result.scalar_one_or_none()

                if vault_row is None:
                    vault_row = KeyVaultSnapshot(
                        vault_uri=vault_uri,
                        name=vault["name"],
                        resource_id=vault.get("id") or vault.get("resource_id"),
                        location=vault.get("location"),
                        resource_group=vault.get("resource_group"),
                        subscription_id=vault.get("subscription_id"),
                        tenant_id=vault.get("tenant_id"),
                        soft_delete_enabled=vault.get("soft_delete_enabled", False),
                        purge_protection_enabled=vault.get("purge_protection_enabled", False),
                        rbac_enabled=vault.get("rbac_enabled", False),
                        provisioning_state=vault.get("provisioning_state"),
                        sku=vault.get("sku"),
                        tags=vault.get("tags", {}),
                        synced_at=datetime.utcnow(),
                    )
                    db.add(vault_row)
                    await db.flush()
                else:
                    vault_row.name = vault["name"]
                    vault_row.resource_id = vault.get("id") or vault.get("resource_id")
                    vault_row.location = vault.get("location")
                    vault_row.resource_group = vault.get("resource_group")
                    vault_row.subscription_id = vault.get("subscription_id")
                    vault_row.tenant_id = vault.get("tenant_id")
                    vault_row.soft_delete_enabled = vault.get("soft_delete_enabled", False)
                    vault_row.purge_protection_enabled = vault.get("purge_protection_enabled", False)
                    vault_row.rbac_enabled = vault.get("rbac_enabled", False)
                    vault_row.provisioning_state = vault.get("provisioning_state")
                    vault_row.sku = vault.get("sku")
                    vault_row.tags = vault.get("tags", {})
                    vault_row.synced_at = datetime.utcnow()

                # Fetch items from Azure (independent of DB session)
                secrets = keys = certs = None
                item_failures: list[str] = []
                if vault_uri:
                    secrets, keys, certs, item_failures = await self._fetch_vault_items(kv, vault_uri, vault_name)

                # Replace items in DB
                counts = await self._upsert_vault_items_with_session(db, vault_row, secrets, keys, certs)

                vault_row.secrets_count = counts["secrets"]
                vault_row.keys_count = counts["keys"]
                vault_row.certificates_count = counts["certs"]
                await db.commit()

                logger.info(
                    "kv_sync_vault_done",
                    vault=vault_name,
                    secrets=counts["secrets"],
                    keys=counts["keys"],
                    certs=counts["certs"],
                    preserved_item_types=item_failures,
                )
                return {**counts, "item_failures": item_failures}

        except Exception as e:
            logger.warning(
                "kv_sync_vault_isolated_error",
                vault=vault_name,
                error=str(e)[:300],
            )
            raise

        return None

    # ── Vault-Level Sync (for mutations — uses caller's session) ───────

    async def sync_vault(self, vault_uri: str, *, triggered_by: str = "mutation") -> dict:
        """
        Sync a single vault's secrets/keys/certificates after a mutation.
        Uses the caller's DB session (safe for single-vault sync).
        """
        logger.info("kv_sync_vault_start", vault_uri=vault_uri, triggered_by=triggered_by)

        # Look up or create the vault snapshot
        result = await self.db.execute(select(KeyVaultSnapshot).where(KeyVaultSnapshot.vault_uri == vault_uri))
        vault_row = result.scalar_one_or_none()

        if vault_row is None:
            # Vault not yet in DB — run a discovery for just this vault
            vaults = await self.kv.list_vaults(refresh=True)
            vault_data = next((v for v in vaults if v["vault_uri"] == vault_uri), None)
            if vault_data is None:
                return {"status": "vault_not_found"}
            # Use isolated sync for this new vault
            isolated_result = await self._sync_vault_isolated(vault_data)
            return {"status": "synced", **(isolated_result or {})}

        # Fetch fresh items from Azure
        try:
            secrets, keys, certs, item_failures = await self._fetch_vault_items(self.kv, vault_uri, str(vault_row.name))

            counts = await self._upsert_vault_items_with_session(self.db, vault_row, secrets, keys, certs)

            vault_row.secrets_count = counts["secrets"]
            vault_row.keys_count = counts["keys"]
            vault_row.certificates_count = counts["certs"]
            vault_row.synced_at = datetime.utcnow()
            await self.db.commit()

            blocking_item_failures = [
                item_type for item_type in item_failures if item_type not in _NON_BLOCKING_ITEM_FAILURES
            ]

            logger.info("kv_sync_vault_done", vault=vault_row.name, preserved_item_types=item_failures, **counts)
            return {
                "status": "partial" if blocking_item_failures else "synced",
                **counts,
                "item_failures": item_failures,
            }

        except Exception as e:
            logger.error("kv_sync_vault_error", vault_uri=vault_uri, error=str(e))
            raise

    async def _fetch_vault_items(
        self,
        kv: KeyVaultService,
        vault_uri: str,
        vault_name: str,
    ) -> tuple[list[dict] | None, list[dict] | None, list[dict] | None, list[str]]:
        """Fetch vault items and preserve prior cached state when a live call fails."""
        item_failures: list[str] = []
        results = await asyncio.gather(
            kv.list_secrets(vault_uri, refresh=True),
            kv.list_keys(vault_uri, refresh=True),
            kv.list_certificates(vault_uri, refresh=True),
            return_exceptions=True,
        )

        payloads: list[list[dict] | None] = []
        for label, res in zip(["secrets", "keys", "certs"], results, strict=False):
            if isinstance(res, list):
                payloads.append(res)
                continue

            item_failures.append(label)
            payloads.append(None)
            logger.warning(
                "kv_sync_item_fetch_failed",
                vault=vault_name,
                item_type=label,
                error=str(res)[:200],
            )

        return payloads[0], payloads[1], payloads[2], item_failures

    # ── Startup / Staleness Check ──────────────────────────────────────

    async def is_data_stale(self) -> bool:
        """
        Check if DB data is missing or stale (older than threshold).
        Used to decide whether to trigger an automatic sync on startup.
        """
        count_result = await self.db.execute(select(func.count(KeyVaultSnapshot.id)))
        vault_count = count_result.scalar() or 0

        if vault_count == 0:
            return True  # No data at all

        # Check last completed sync time
        last_sync_result = await self.db.execute(
            select(KeyVaultSyncStatus.completed_at)
            .where(KeyVaultSyncStatus.status.in_(["completed", "partial"]))
            .order_by(KeyVaultSyncStatus.completed_at.desc())
            .limit(1)
        )
        last_completed = last_sync_result.scalar_one_or_none()

        if last_completed is None:
            return True  # Never completed a sync

        age = datetime.utcnow() - last_completed
        return age > timedelta(minutes=_STALE_THRESHOLD_MINUTES)

    async def _upsert_vault_items_with_session(
        self,
        db: AsyncSession,
        vault_row: KeyVaultSnapshot,
        secrets: list[dict] | None,
        keys: list[dict] | None,
        certs: list[dict] | None,
    ) -> dict:
        """Replace only successfully fetched item sets and preserve prior cached rows on failures."""
        now = datetime.utcnow()

        if secrets is not None:
            await db.execute(delete(KeyVaultSecretSnapshot).where(KeyVaultSecretSnapshot.vault_id == vault_row.id))
            for s in secrets:
                db.add(
                    KeyVaultSecretSnapshot(
                        vault_id=vault_row.id,
                        name=s.get("name", ""),
                        secret_id=s.get("id"),
                        content_type=s.get("content_type"),
                        enabled=s.get("enabled", True),
                        created=s.get("created"),
                        updated=s.get("updated"),
                        expires=s.get("expires"),
                        not_before=s.get("not_before"),
                        managed=s.get("managed", False),
                        tags=s.get("tags", {}),
                        synced_at=now,
                    )
                )

        if keys is not None:
            await db.execute(delete(KeyVaultKeySnapshot).where(KeyVaultKeySnapshot.vault_id == vault_row.id))
            for k in keys:
                db.add(
                    KeyVaultKeySnapshot(
                        vault_id=vault_row.id,
                        name=k.get("name", ""),
                        kid=k.get("kid"),
                        enabled=k.get("enabled", True),
                        created=k.get("created"),
                        updated=k.get("updated"),
                        expires=k.get("expires"),
                        not_before=k.get("not_before"),
                        managed=k.get("managed", False),
                        tags=k.get("tags", {}),
                        synced_at=now,
                    )
                )

        if certs is not None:
            await db.execute(delete(KeyVaultCertSnapshot).where(KeyVaultCertSnapshot.vault_id == vault_row.id))
            for c in certs:
                db.add(
                    KeyVaultCertSnapshot(
                        vault_id=vault_row.id,
                        name=c.get("name", ""),
                        cert_id=c.get("id"),
                        enabled=c.get("enabled", True),
                        created=c.get("created"),
                        updated=c.get("updated"),
                        expires=c.get("expires"),
                        not_before=c.get("not_before"),
                        cn_name=c.get("cn_name"),
                        san=c.get("san", []),
                        serial_number=c.get("serial_number"),
                        thumbprint=c.get("thumbprint"),
                        tags=c.get("tags", {}),
                        synced_at=now,
                    )
                )

        await db.flush()
        secrets_count = await db.scalar(
            select(func.count(KeyVaultSecretSnapshot.id)).where(KeyVaultSecretSnapshot.vault_id == vault_row.id)
        )
        keys_count = await db.scalar(
            select(func.count(KeyVaultKeySnapshot.id)).where(KeyVaultKeySnapshot.vault_id == vault_row.id)
        )
        certs_count = await db.scalar(
            select(func.count(KeyVaultCertSnapshot.id)).where(KeyVaultCertSnapshot.vault_id == vault_row.id)
        )
        return {
            "secrets": int(secrets_count or 0),
            "keys": int(keys_count or 0),
            "certs": int(certs_count or 0),
        }

    # ── Read from DB ───────────────────────────────────────────────────

    async def get_dashboard_from_db(self, subscription_ids: list[str] | None = None) -> dict | None:
        """
        Build dashboard summary entirely from PG data.

        When ``subscription_ids`` is provided, vaults and expiring items are
        restricted to those subscriptions (the per-request scope). Returns None
        if no data has been synced yet for the scope.
        """
        # Check if any vaults exist in DB (within scope, if scoped)
        count_stmt = select(func.count(KeyVaultSnapshot.id))
        if subscription_ids:
            count_stmt = count_stmt.where(KeyVaultSnapshot.subscription_id.in_(subscription_ids))
        count_result = await self.db.execute(count_stmt)
        vault_count = count_result.scalar()
        if not vault_count:
            return None  # No data synced yet — caller falls back to Azure API

        # Get all vaults with counts (within scope, if scoped)
        vaults_stmt = select(KeyVaultSnapshot).order_by(KeyVaultSnapshot.name)
        if subscription_ids:
            vaults_stmt = vaults_stmt.where(KeyVaultSnapshot.subscription_id.in_(subscription_ids))
        vaults_result = await self.db.execute(vaults_stmt)
        vaults = vaults_result.scalars().all()

        total_secrets = 0
        total_keys = 0
        total_certs = 0
        vault_summaries = []
        expiring_soon: list[dict] = []

        for v in vaults:
            total_secrets += v.secrets_count
            total_keys += v.keys_count
            total_certs += v.certificates_count

            vault_summaries.append(
                {
                    "name": v.name,
                    "vault_uri": v.vault_uri or "",
                    "location": v.location or "",
                    "subscription_id": v.subscription_id or "",
                    "secrets_count": v.secrets_count,
                    "keys_count": v.keys_count,
                    "certificates_count": v.certificates_count,
                    "soft_delete": v.soft_delete_enabled,
                    "purge_protection": v.purge_protection_enabled,
                    "rbac_enabled": v.rbac_enabled,
                }
            )

        # Get expiring items from DB — secrets, keys, certs with expires set
        # Secrets expiring within 90 days
        secrets_stmt = (
            select(KeyVaultSecretSnapshot, KeyVaultSnapshot.name.label("vault_name"))
            .join(KeyVaultSnapshot, KeyVaultSecretSnapshot.vault_id == KeyVaultSnapshot.id)
            .where(KeyVaultSecretSnapshot.expires.isnot(None))
        )
        if subscription_ids:
            secrets_stmt = secrets_stmt.where(KeyVaultSnapshot.subscription_id.in_(subscription_ids))
        secrets_result = await self.db.execute(secrets_stmt)
        for row in secrets_result:
            secret = row[0]
            vault_name = row[1]
            _check_expiry_from_db(
                expiring_soon,
                secret.name,
                vault_name,
                "secret",
                secret.expires,
                secret.enabled,
            )

        # Keys expiring within 90 days
        keys_stmt = (
            select(KeyVaultKeySnapshot, KeyVaultSnapshot.name.label("vault_name"))
            .join(KeyVaultSnapshot, KeyVaultKeySnapshot.vault_id == KeyVaultSnapshot.id)
            .where(KeyVaultKeySnapshot.expires.isnot(None))
        )
        if subscription_ids:
            keys_stmt = keys_stmt.where(KeyVaultSnapshot.subscription_id.in_(subscription_ids))
        keys_result = await self.db.execute(keys_stmt)
        for row in keys_result:
            key = row[0]
            vault_name = row[1]
            _check_expiry_from_db(expiring_soon, key.name, vault_name, "key", key.expires, key.enabled)

        # Certs expiring within 90 days
        certs_stmt = (
            select(KeyVaultCertSnapshot, KeyVaultSnapshot.name.label("vault_name"))
            .join(KeyVaultSnapshot, KeyVaultCertSnapshot.vault_id == KeyVaultSnapshot.id)
            .where(KeyVaultCertSnapshot.expires.isnot(None))
        )
        if subscription_ids:
            certs_stmt = certs_stmt.where(KeyVaultSnapshot.subscription_id.in_(subscription_ids))
        certs_result = await self.db.execute(certs_stmt)
        for row in certs_result:
            cert = row[0]
            vault_name = row[1]
            _check_expiry_from_db(
                expiring_soon,
                cert.name,
                vault_name,
                "certificate",
                cert.expires,
                cert.enabled,
            )

        expiring_soon.sort(key=lambda x: x.get("expires", ""))

        # Get last sync time
        last_sync_result = await self.db.execute(
            select(KeyVaultSyncStatus)
            .where(KeyVaultSyncStatus.status.in_(["completed", "partial"]))
            .order_by(KeyVaultSyncStatus.completed_at.desc())
            .limit(1)
        )
        last_sync = last_sync_result.scalar_one_or_none()

        return {
            "total_vaults": len(vaults),
            "total_secrets": total_secrets,
            "total_keys": total_keys,
            "total_certificates": total_certs,
            "expiring_within_30_days": len([e for e in expiring_soon if e.get("days_remaining", 999) <= 30]),
            "expiring_within_90_days": len([e for e in expiring_soon if e.get("days_remaining", 999) <= 90]),
            "expiring_within_360_days": len([e for e in expiring_soon if e.get("days_remaining", 999) <= 360]),
            "expiring_items": expiring_soon,
            "vault_summaries": vault_summaries,
            "generated_at": datetime.utcnow().isoformat(),
            "source": "database",
            "last_synced_at": last_sync.completed_at.isoformat() if last_sync else None,
        }

    async def get_vaults_from_db(self) -> list[dict] | None:
        """Return vault list from PG. Returns None if empty."""
        result = await self.db.execute(select(KeyVaultSnapshot).order_by(KeyVaultSnapshot.name))
        rows = result.scalars().all()
        if not rows:
            return None

        return [
            {
                "name": v.name,
                "vault_uri": v.vault_uri,
                "id": v.resource_id or "",
                "location": v.location,
                "resource_group": v.resource_group,
                "subscription_id": v.subscription_id,
                "sku": v.sku or "",
                "tenant_id": v.tenant_id,
                "soft_delete_enabled": v.soft_delete_enabled,
                "purge_protection_enabled": v.purge_protection_enabled,
                "rbac_enabled": v.rbac_enabled,
                "provisioning_state": v.provisioning_state,
                "tags": v.tags or {},
            }
            for v in rows
        ]

    async def get_secrets_from_db(self, vault_uri: str, search: str | None = None) -> list[dict] | None:
        """Return secrets for a vault from PG."""
        vault_result = await self.db.execute(select(KeyVaultSnapshot.id).where(KeyVaultSnapshot.vault_uri == vault_uri))
        vault_id = vault_result.scalar_one_or_none()
        if vault_id is None:
            return None

        query = select(KeyVaultSecretSnapshot).where(KeyVaultSecretSnapshot.vault_id == vault_id)
        if search:
            query = query.where(KeyVaultSecretSnapshot.name.ilike(f"%{search}%"))
        query = query.order_by(KeyVaultSecretSnapshot.name)

        result = await self.db.execute(query)
        rows = result.scalars().all()

        return [
            {
                "name": s.name,
                "id": s.secret_id or "",
                "content_type": s.content_type or "",
                "enabled": s.enabled,
                "created": s.created,
                "updated": s.updated,
                "expires": s.expires,
                "not_before": s.not_before,
                "tags": s.tags or {},
                "managed": s.managed,
            }
            for s in rows
        ]

    async def get_keys_from_db(self, vault_uri: str) -> list[dict] | None:
        """Return keys for a vault from PG."""
        vault_result = await self.db.execute(select(KeyVaultSnapshot.id).where(KeyVaultSnapshot.vault_uri == vault_uri))
        vault_id = vault_result.scalar_one_or_none()
        if vault_id is None:
            return None

        result = await self.db.execute(
            select(KeyVaultKeySnapshot)
            .where(KeyVaultKeySnapshot.vault_id == vault_id)
            .order_by(KeyVaultKeySnapshot.name)
        )
        rows = result.scalars().all()

        return [
            {
                "name": k.name,
                "kid": k.kid or "",
                "enabled": k.enabled,
                "created": k.created,
                "updated": k.updated,
                "expires": k.expires,
                "not_before": k.not_before,
                "managed": k.managed,
                "tags": k.tags or {},
            }
            for k in rows
        ]

    async def get_certificates_from_db(self, vault_uri: str) -> list[dict] | None:
        """Return certificates for a vault from PG."""
        vault_result = await self.db.execute(select(KeyVaultSnapshot.id).where(KeyVaultSnapshot.vault_uri == vault_uri))
        vault_id = vault_result.scalar_one_or_none()
        if vault_id is None:
            return None

        result = await self.db.execute(
            select(KeyVaultCertSnapshot)
            .where(KeyVaultCertSnapshot.vault_id == vault_id)
            .order_by(KeyVaultCertSnapshot.name)
        )
        rows = result.scalars().all()

        return [
            {
                "name": c.name,
                "id": c.cert_id or "",
                "enabled": c.enabled,
                "created": c.created,
                "updated": c.updated,
                "expires": c.expires,
                "not_before": c.not_before,
                "cn_name": c.cn_name or "",
                "san": c.san or [],
                "serial_number": c.serial_number,
                "thumbprint": c.thumbprint or "",
                "tags": c.tags or {},
            }
            for c in rows
        ]

    async def get_sync_status(self, limit: int = 5) -> dict:
        """Return last sync status and scheduled info."""
        last_result = await self.db.execute(
            select(KeyVaultSyncStatus).order_by(KeyVaultSyncStatus.started_at.desc()).limit(limit)
        )
        rows = last_result.scalars().all()

        vault_count_result = await self.db.execute(select(func.count(KeyVaultSnapshot.id)))
        vault_count = vault_count_result.scalar() or 0

        return {
            "vaults_in_db": vault_count,
            "recent_syncs": [
                {
                    "id": r.id,
                    "sync_type": r.sync_type,
                    "status": r.status,
                    "started_at": r.started_at.isoformat() if r.started_at else None,
                    "completed_at": (r.completed_at.isoformat() if r.completed_at else None),
                    "vaults_synced": r.vaults_synced,
                    "secrets_synced": r.secrets_synced,
                    "keys_synced": r.keys_synced,
                    "certificates_synced": r.certificates_synced,
                    "error_message": r.error_message,
                    "triggered_by": r.triggered_by,
                }
                for r in rows
            ],
        }


# ── Helpers ────────────────────────────────────────────────────────────


def _check_expiry_from_db(
    expiring_list: list,
    name: str,
    vault_name: str,
    item_type: str,
    expires_str: str | None,
    enabled: bool,
) -> None:
    """Check if an item is expiring within 360 days (from DB string)."""
    if not expires_str:
        return
    try:
        exp_date = datetime.fromisoformat(expires_str)
        days_remaining = (exp_date - datetime.utcnow()).days
        if 0 <= days_remaining <= 360:
            expiring_list.append(
                {
                    "name": name,
                    "vault_name": vault_name,
                    "type": item_type,
                    "expires": expires_str,
                    "days_remaining": days_remaining,
                    "enabled": enabled,
                }
            )
    except (ValueError, TypeError):
        pass
