"""Certificate private-key escrow (Azure Key Vault backed).

Keyfactor returns a certificate's PFX only at the moment of issuance, so
without escrow a newly issued certificate can be loaded into exactly one Key
Vault and never again — which is what blocks a multi-SAN certificate whose
hostnames span several environments, each with its own vault.

This module captures that one-time PFX into a *dedicated* escrow Key Vault and
records a pointer row in PostgreSQL, so the same certificate and key can be
imported into any number of vaults later.

Where the key material lives is the entire point of the design:

* The PFX and the password protecting it are stored as one Key Vault secret, so
  they inherit HSM-backed storage, RBAC, soft-delete/purge protection and
  Azure's own access audit trail.
* PostgreSQL holds only the vault name and secret name. Database dumps,
  replicas and PITR snapshots therefore never contain key material.
* Co-locating the PFX password with the PFX means the password itself no longer
  adds protection. That is deliberate: the Key Vault's access control is the
  control, and a password nobody recorded is useless months later when someone
  needs the key during an incident.

Key material is never logged and never written to the audit table.
"""

from __future__ import annotations

import base64
import json
from datetime import UTC, datetime, timedelta
from typing import Any

import structlog
from cryptography.hazmat.primitives.serialization import BestAvailableEncryption, pkcs12
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.database import CertificateKeyEscrow, CertificateSnapshot
from app.services.keyvault_service import KeyVaultService

logger = structlog.get_logger(__name__)

# Key Vault caps a secret value at 25 KB. A PFX with a 4096-bit key and a full
# chain stays well under that, but reject oversized material with a clear error
# instead of letting Key Vault return an opaque 400.
_MAX_SECRET_BYTES = 24 * 1024

# The secret's own expiry is set far out on purpose: an *expired* Key Vault
# secret cannot be read, which would silently break a legitimate AKV load for a
# still-valid certificate. Escrow lifetime is governed by ``purge_expired``,
# which deletes the secret once the certificate itself has expired.
_SECRET_LIFETIME_DAYS = 3650

_ENVELOPE_VERSION = 1


class CertificateEscrowService:
    """Read/write certificate PFX material in the escrow Key Vault."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self._kv = KeyVaultService()

    # ── Configuration ──────────────────────────────────────────────────

    @staticmethod
    def is_enabled() -> bool:
        """True when escrow is switched on *and* pointed at a vault."""
        return settings.cert_key_escrow_active

    @staticmethod
    def vault_uri() -> str:
        return settings.cert_key_escrow_vault_uri

    @staticmethod
    def vault_name() -> str:
        uri = settings.cert_key_escrow_vault_uri
        if not uri:
            return ""
        return uri.rstrip("/").split("//")[-1].split(".")[0]

    @staticmethod
    def secret_name_for(thumbprint: str) -> str:
        """Deterministic secret name so re-escrowing the same cert is idempotent."""
        return f"cert-pfx-{(thumbprint or '').strip().lower()}"

    # ── Write ──────────────────────────────────────────────────────────

    async def escrow(
        self,
        *,
        certificate_id: int | None,
        thumbprint: str,
        common_name: str | None,
        pfx_base64: str,
        password: str | None,
        source: str,
        actor: str | None = None,
    ) -> dict[str, Any] | None:
        """Store issuance-time PFX material and record the pointer row.

        Returns the pointer metadata on success, or ``None`` when escrow is
        disabled, the inputs are unusable, or the vault write fails. Callers
        treat this as best-effort: a failed escrow must never fail the
        enrollment or renewal that produced the certificate.
        """
        if not self.is_enabled():
            return None
        thumb = (thumbprint or "").strip().lower()
        if not thumb or not pfx_base64:
            return None

        envelope = json.dumps(
            {
                "version": _ENVELOPE_VERSION,
                "thumbprint": thumb,
                "common_name": common_name or "",
                "pfx_base64": pfx_base64,
                "password": password or "",
            }
        )
        if len(envelope.encode("utf-8")) > _MAX_SECRET_BYTES:
            logger.warning(
                "cert_escrow_material_too_large",
                thumbprint=thumb,
                size_bytes=len(envelope.encode("utf-8")),
                limit_bytes=_MAX_SECRET_BYTES,
            )
            return None

        secret_name = self.secret_name_for(thumb)
        vault_uri = self.vault_uri()
        now = datetime.utcnow()
        try:
            await self._kv.create_or_update_secret(
                vault_uri,
                secret_name,
                envelope,
                content_type="application/json; profile=cert-pfx-escrow",
                tags={
                    "thumbprint": thumb,
                    "common_name": (common_name or "")[:250],
                    "source": source,
                    "managed-by": "ops-portal-cert-escrow",
                },
                expires=(now + timedelta(days=_SECRET_LIFETIME_DAYS)).isoformat(),
            )
        except Exception as exc:  # escrow is best-effort
            logger.warning(
                "cert_escrow_vault_write_failed",
                thumbprint=thumb,
                vault=self.vault_name(),
                error=str(exc)[:300],
            )
            return None

        try:
            existing = await self.db.execute(
                select(CertificateKeyEscrow).where(CertificateKeyEscrow.thumbprint == thumb)
            )
            row = existing.scalar_one_or_none()
            if row is None:
                row = CertificateKeyEscrow(
                    certificate_id=int(certificate_id or 0),
                    thumbprint=thumb,
                    common_name=common_name or None,
                    vault_name=self.vault_name(),
                    secret_name=secret_name,
                    source=source,
                    escrowed_by=actor,
                    escrowed_at=now,
                )
                self.db.add(row)
            else:
                # Re-escrow (e.g. a retried renewal) refreshes the pointer and
                # clears any earlier purge marker.
                row.certificate_id = int(certificate_id or row.certificate_id)
                row.common_name = common_name or row.common_name
                row.vault_name = self.vault_name()
                row.secret_name = secret_name
                row.source = source
                row.escrowed_by = actor or row.escrowed_by
                row.escrowed_at = now
                row.purged_at = None
            await self.db.commit()
        except Exception as exc:  # vault write already succeeded
            await self.db.rollback()
            logger.warning("cert_escrow_row_write_failed", thumbprint=thumb, error=str(exc)[:300])
            return None

        logger.info(
            "cert_escrow_stored",
            thumbprint=thumb,
            vault=self.vault_name(),
            secret_name=secret_name,
            source=source,
        )
        return {
            "vault_name": self.vault_name(),
            "secret_name": secret_name,
            "thumbprint": thumb,
        }

    # ── Read ───────────────────────────────────────────────────────────

    async def find_pointer(
        self,
        *,
        certificate_id: int | None = None,
        thumbprint: str | None = None,
    ) -> CertificateKeyEscrow | None:
        """Locate a live (non-purged) escrow pointer by cert id or thumbprint."""
        if not self.is_enabled():
            return None
        conditions = []
        if thumbprint and thumbprint.strip():
            conditions.append(CertificateKeyEscrow.thumbprint == thumbprint.strip().lower())
        elif certificate_id is not None:
            conditions.append(CertificateKeyEscrow.certificate_id == int(certificate_id))
        else:
            return None
        result = await self.db.execute(
            select(CertificateKeyEscrow).where(*conditions).where(CertificateKeyEscrow.purged_at.is_(None)).limit(1)
        )
        return result.scalar_one_or_none()

    async def get_material(
        self,
        *,
        certificate_id: int | None = None,
        thumbprint: str | None = None,
    ) -> tuple[bytes, str] | None:
        """Return ``(pfx_bytes, password)`` for an escrowed certificate.

        ``None`` means "no usable escrowed key" — no pointer, the secret is gone
        from the vault, or the stored envelope is unreadable. Callers fall back
        to a live Keyfactor export.
        """
        pointer = await self.find_pointer(certificate_id=certificate_id, thumbprint=thumbprint)
        if pointer is None:
            return None

        try:
            secret = await self._kv.get_secret_value(self.vault_uri(), pointer.secret_name)
        except Exception as exc:  # fall back to Keyfactor export
            logger.warning(
                "cert_escrow_vault_read_failed",
                thumbprint=pointer.thumbprint,
                secret_name=pointer.secret_name,
                error=str(exc)[:300],
            )
            return None

        try:
            envelope = json.loads(secret.get("value") or "")
            pfx_base64 = envelope["pfx_base64"]
            password = envelope.get("password") or ""
            pfx_bytes = base64.b64decode(pfx_base64)
        except Exception as exc:  # never leak the value itself
            logger.warning(
                "cert_escrow_envelope_unreadable",
                thumbprint=pointer.thumbprint,
                error=type(exc).__name__,
            )
            return None

        if not pfx_bytes:
            return None
        return pfx_bytes, password

    async def export_pfx(
        self,
        *,
        password: str,
        certificate_id: int | None = None,
        thumbprint: str | None = None,
        include_chain: bool = True,
    ) -> bytes | None:
        """Escrowed PFX re-encrypted under a caller-chosen ``password``.

        The escrowed material is protected by whatever password was used at
        issuance, which nobody remembers months later, so it is re-wrapped under
        the password the caller is about to use to open the file. ``None`` means
        no usable escrowed key, leaving the caller to surface its own error.
        """
        material = await self.get_material(certificate_id=certificate_id, thumbprint=thumbprint)
        if material is None:
            return None
        pfx_bytes, stored_password = material
        try:
            return rewrap_pfx(
                pfx_bytes,
                current_password=stored_password,
                new_password=password,
                include_chain=include_chain,
            )
        except Exception as exc:
            # Never echo the exception message: it can carry key material.
            logger.warning(
                "cert_escrow_pfx_rewrap_failed",
                certificate_id=certificate_id,
                thumbprint=thumbprint,
                error=type(exc).__name__,
            )
            return None

    async def escrowed_thumbprints(self, thumbprints: list[str]) -> set[str]:
        """Subset of ``thumbprints`` (lowercased) that have live escrowed keys."""
        if not self.is_enabled():
            return set()
        wanted = {(t or "").strip().lower() for t in thumbprints if (t or "").strip()}
        if not wanted:
            return set()
        result = await self.db.execute(
            select(CertificateKeyEscrow.thumbprint)
            .where(CertificateKeyEscrow.thumbprint.in_(wanted))
            .where(CertificateKeyEscrow.purged_at.is_(None))
        )
        return {row[0] for row in result.all()}

    # ── Retention ──────────────────────────────────────────────────────

    async def reconcile(self) -> dict[str, int]:
        """Backfill expiry onto escrow rows, then purge keys for expired certs.

        Called after a certificate sync: the enrollment response carries neither
        the expiry nor (for renewals) the common name, so both are learned from
        the synced snapshot. A row whose expiry is still unknown is never purged
        — deleting the only copy of a private key requires proof the certificate
        is dead.
        """
        if not self.is_enabled():
            return {"backfilled": 0, "purged": 0}
        backfilled = await self._backfill_from_snapshot()
        purged = await self.purge_expired()
        return {"backfilled": backfilled, "purged": purged}

    async def _backfill_from_snapshot(self) -> int:
        """Copy expiry and common name from the synced snapshot onto pointers."""
        try:
            rows = await self.db.execute(
                select(CertificateKeyEscrow.id, CertificateKeyEscrow.thumbprint)
                .where(CertificateKeyEscrow.not_after.is_(None) | CertificateKeyEscrow.common_name.is_(None))
                .where(CertificateKeyEscrow.purged_at.is_(None))
            )
            pending = rows.all()
            if not pending:
                return 0

            snapshot = await self.db.execute(
                select(
                    CertificateSnapshot.thumbprint,
                    CertificateSnapshot.not_after,
                    CertificateSnapshot.common_name,
                ).where(CertificateSnapshot.thumbprint.isnot(None))
            )
            by_thumb = {(t or "").strip().lower(): (na, cn) for t, na, cn in snapshot.all() if (t or "").strip()}

            updated = 0
            for row_id, thumb in pending:
                found = by_thumb.get(thumb)
                if found is None:
                    continue
                not_after, common_name = found
                values: dict[str, Any] = {}
                if not_after:
                    values["not_after"] = not_after
                if common_name:
                    values["common_name"] = common_name
                if not values:
                    continue
                await self.db.execute(
                    update(CertificateKeyEscrow).where(CertificateKeyEscrow.id == row_id).values(**values)
                )
                updated += 1
            if updated:
                await self.db.commit()
            return updated
        except Exception as exc:  # reconciliation is best-effort
            await self.db.rollback()
            logger.warning("cert_escrow_backfill_failed", error=str(exc)[:300])
            return 0

    async def purge_expired(self) -> int:
        """Delete escrowed keys whose certificate has expired."""
        try:
            result = await self.db.execute(
                select(CertificateKeyEscrow)
                .where(CertificateKeyEscrow.purged_at.is_(None))
                .where(CertificateKeyEscrow.not_after.isnot(None))
            )
            rows = result.scalars().all()
        except Exception as exc:
            logger.warning("cert_escrow_purge_query_failed", error=str(exc)[:300])
            return 0

        now = datetime.now(UTC)
        purged = 0
        for row in rows:
            expiry = _parse_expiry(row.not_after)
            if expiry is None or expiry > now:
                continue
            try:
                await self._kv.delete_secret(self.vault_uri(), row.secret_name)
            except Exception as exc:  # retry on the next sync
                logger.warning(
                    "cert_escrow_purge_delete_failed",
                    thumbprint=row.thumbprint,
                    error=str(exc)[:300],
                )
                continue
            row.purged_at = datetime.utcnow()
            purged += 1

        if purged:
            try:
                await self.db.commit()
                logger.info("cert_escrow_purged", count=purged)
            except Exception as exc:
                await self.db.rollback()
                logger.warning("cert_escrow_purge_commit_failed", error=str(exc)[:300])
                return 0
        return purged


def rewrap_pfx(
    pfx_bytes: bytes,
    *,
    current_password: str,
    new_password: str,
    include_chain: bool = True,
) -> bytes:
    """Re-encrypt a PKCS#12 blob under a new password.

    Raises on unreadable material or a PFX without a private key — callers treat
    that as "no usable escrowed key" rather than propagating it.
    """
    if not new_password:
        raise ValueError("a non-empty password is required to re-wrap a PFX")
    key, cert, chain = pkcs12.load_key_and_certificates(
        pfx_bytes, current_password.encode("utf-8") if current_password else None
    )
    if key is None or cert is None:
        raise ValueError("escrowed material has no private key or certificate")
    return pkcs12.serialize_key_and_certificates(
        name=None,
        key=key,
        cert=cert,
        cas=(chain or None) if include_chain else None,
        encryption_algorithm=BestAvailableEncryption(new_password.encode("utf-8")),
    )


def _parse_expiry(value: str | None) -> datetime | None:
    """Parse a Keyfactor expiry string into an aware datetime, or ``None``."""
    raw = (value or "").strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
