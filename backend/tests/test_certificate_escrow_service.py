"""Tests for certificate private-key escrow.

The escrow Key Vault is replaced with an in-memory fake so the assertions can
inspect exactly what would be written to Azure. Two properties matter most and
are covered explicitly: PostgreSQL must never receive key material, and a
private key must never be purged unless the certificate is provably expired.
"""

import base64
import json
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.core.config import settings
from app.models.database import CertificateKeyEscrow
from app.services.certificate_escrow_service import CertificateEscrowService

PFX_BYTES = b"PFX-KEY-MATERIAL"
PFX_B64 = base64.b64encode(PFX_BYTES).decode()
THUMB = "3E49931A64AE04D987533E0DD1C237BDA701DA2C"


class FakeEscrowVault:
    """Captures secret writes/reads/deletes against a dict-backed vault."""

    def __init__(self) -> None:
        self.secrets: dict[str, dict] = {}
        self.deleted: list[str] = []
        self.write_fails = False
        self.read_fails = False

    async def create_or_update_secret(self, vault_uri, name, value, **kwargs):
        if self.write_fails:
            raise RuntimeError("vault write refused")
        self.secrets[name] = {"value": value, "kwargs": kwargs, "vault_uri": vault_uri}
        return {"name": name, "id": f"{vault_uri}secrets/{name}/1"}

    async def get_secret_value(self, vault_uri, name):
        if self.read_fails:
            raise RuntimeError("vault read refused")
        if name not in self.secrets:
            raise RuntimeError("SecretNotFound")
        return {"name": name, "value": self.secrets[name]["value"]}

    async def delete_secret(self, vault_uri, name):
        self.deleted.append(name)
        self.secrets.pop(name, None)
        return {"deleted": True}


@pytest.fixture
def vault(monkeypatch):
    """Enable escrow and point the service at the in-memory vault."""
    fake = FakeEscrowVault()
    monkeypatch.setattr(settings, "CERT_KEY_ESCROW_ENABLED", True)
    monkeypatch.setattr(settings, "CERT_KEY_ESCROW_VAULT", "escrow-kv")
    monkeypatch.setattr(settings, "CERT_KEY_ESCROW_VAULT_URI", "")
    monkeypatch.setattr("app.services.certificate_escrow_service.KeyVaultService", lambda: fake)
    return fake


async def _escrow(db, vault_fixture=None, **overrides):
    service = CertificateEscrowService(db)
    kwargs = {
        "certificate_id": 4242,
        "thumbprint": THUMB,
        "common_name": "cesdataroutergears.dev.att.com",
        "pfx_base64": PFX_B64,
        "password": "single-use-pw",
        "source": "renew",
        "actor": "admin@example.com",
    }
    kwargs.update(overrides)
    return await service.escrow(**kwargs)


# ── Configuration gating ───────────────────────────────────────────────


def test_escrow_inactive_until_both_enabled_and_pointed_at_a_vault(monkeypatch):
    monkeypatch.setattr(settings, "CERT_KEY_ESCROW_ENABLED", True)
    monkeypatch.setattr(settings, "CERT_KEY_ESCROW_VAULT", "")
    monkeypatch.setattr(settings, "CERT_KEY_ESCROW_VAULT_URI", "")
    assert CertificateEscrowService.is_enabled() is False

    monkeypatch.setattr(settings, "CERT_KEY_ESCROW_VAULT", "escrow-kv")
    assert CertificateEscrowService.is_enabled() is True
    assert settings.cert_key_escrow_vault_uri == "https://escrow-kv.vault.azure.net/"

    monkeypatch.setattr(settings, "CERT_KEY_ESCROW_ENABLED", False)
    assert CertificateEscrowService.is_enabled() is False


def test_secret_name_is_deterministic_and_case_insensitive():
    assert (
        CertificateEscrowService.secret_name_for(THUMB)
        == CertificateEscrowService.secret_name_for(THUMB.lower())
        == f"cert-pfx-{THUMB.lower()}"
    )


async def test_escrow_is_a_no_op_when_disabled(db_session, monkeypatch):
    monkeypatch.setattr(settings, "CERT_KEY_ESCROW_ENABLED", False)
    assert await _escrow(db_session) is None
    rows = (await db_session.execute(select(CertificateKeyEscrow))).scalars().all()
    assert rows == []


# ── Write path ─────────────────────────────────────────────────────────


async def test_escrow_stores_material_in_the_vault_only(db_session, vault):
    pointer = await _escrow(db_session)
    assert pointer == {
        "vault_name": "escrow-kv",
        "secret_name": f"cert-pfx-{THUMB.lower()}",
        "thumbprint": THUMB.lower(),
    }

    # The key material lives in the vault, wrapped in a versioned envelope.
    secret = vault.secrets[f"cert-pfx-{THUMB.lower()}"]
    envelope = json.loads(secret["value"])
    assert envelope["pfx_base64"] == PFX_B64
    assert envelope["password"] == "single-use-pw"
    assert envelope["thumbprint"] == THUMB.lower()

    # ...and the database row is a pointer with no key material in any column.
    row = (await db_session.execute(select(CertificateKeyEscrow))).scalar_one()
    assert row.thumbprint == THUMB.lower()
    assert row.certificate_id == 4242
    assert row.vault_name == "escrow-kv"
    assert row.escrowed_by == "admin@example.com"
    assert row.purged_at is None
    persisted = " ".join(str(getattr(row, c.name)) for c in row.__table__.columns)
    assert PFX_B64 not in persisted
    assert "single-use-pw" not in persisted


async def test_escrowed_secret_outlives_the_certificate(db_session, vault):
    # An *expired* Key Vault secret cannot be read, which would silently break a
    # legitimate late AKV load, so the secret's own expiry must be far out.
    await _escrow(db_session)
    expires = vault.secrets[f"cert-pfx-{THUMB.lower()}"]["kwargs"]["expires"]
    assert datetime.fromisoformat(expires) > datetime.utcnow() + timedelta(days=365 * 5)


async def test_escrow_returns_none_when_the_vault_write_fails(db_session, vault):
    vault.write_fails = True
    assert await _escrow(db_session) is None
    # No pointer may be recorded for material that never reached the vault.
    rows = (await db_session.execute(select(CertificateKeyEscrow))).scalars().all()
    assert rows == []


async def test_escrow_rejects_oversized_material(db_session, vault):
    # Key Vault caps a secret at 25 KB; fail cleanly instead of on the API.
    assert await _escrow(db_session, pfx_base64="A" * (25 * 1024)) is None
    assert vault.secrets == {}


async def test_re_escrow_updates_in_place_and_clears_purge_marker(db_session, vault):
    await _escrow(db_session)
    row = (await db_session.execute(select(CertificateKeyEscrow))).scalar_one()
    row.purged_at = datetime.utcnow()
    await db_session.commit()

    await _escrow(db_session, thumbprint=THUMB.lower(), source="enroll")

    rows = (await db_session.execute(select(CertificateKeyEscrow))).scalars().all()
    assert len(rows) == 1
    assert rows[0].purged_at is None
    assert rows[0].source == "enroll"


# ── Read path ──────────────────────────────────────────────────────────


async def test_get_material_round_trips_key_and_password(db_session, vault):
    await _escrow(db_session)
    service = CertificateEscrowService(db_session)

    assert await service.get_material(certificate_id=4242) == (PFX_BYTES, "single-use-pw")
    # Thumbprint lookups ignore Keyfactor's uppercase formatting.
    assert await service.get_material(thumbprint=THUMB) == (PFX_BYTES, "single-use-pw")


async def test_get_material_returns_none_without_a_pointer(db_session, vault):
    assert await CertificateEscrowService(db_session).get_material(certificate_id=999) is None


async def test_get_material_returns_none_when_the_secret_is_unreadable(db_session, vault):
    # Vault outage or deleted secret must degrade to "no escrowed key" so the
    # caller can fall back to a live Keyfactor export instead of erroring.
    await _escrow(db_session)
    vault.read_fails = True
    assert await CertificateEscrowService(db_session).get_material(certificate_id=4242) is None


async def test_get_material_ignores_purged_pointers(db_session, vault):
    await _escrow(db_session)
    row = (await db_session.execute(select(CertificateKeyEscrow))).scalar_one()
    row.purged_at = datetime.utcnow()
    await db_session.commit()
    assert await CertificateEscrowService(db_session).get_material(certificate_id=4242) is None


async def test_escrowed_thumbprints_filters_to_live_pointers(db_session, vault):
    await _escrow(db_session)
    service = CertificateEscrowService(db_session)
    found = await service.escrowed_thumbprints([THUMB, "OTHERTHUMB", ""])
    assert found == {THUMB.lower()}


# ── Retention ──────────────────────────────────────────────────────────


async def test_purge_removes_expired_keys_only(db_session, vault):
    service = CertificateEscrowService(db_session)
    now = datetime.now(UTC)

    async def _row(thumb: str, not_after: str | None):
        await _escrow(db_session, thumbprint=thumb, certificate_id=abs(hash(thumb)) % 10000)
        row = (
            await db_session.execute(
                select(CertificateKeyEscrow).where(CertificateKeyEscrow.thumbprint == thumb.lower())
            )
        ).scalar_one()
        row.not_after = not_after
        await db_session.commit()

    await _row("AAAA", (now - timedelta(days=1)).isoformat())  # expired → purge
    await _row("BBBB", (now + timedelta(days=30)).isoformat())  # live → keep
    await _row("CCCC", None)  # unknown expiry → keep

    assert await service.purge_expired() == 1
    assert vault.deleted == ["cert-pfx-aaaa"]

    rows = {r.thumbprint: r for r in (await db_session.execute(select(CertificateKeyEscrow))).scalars().all()}
    assert rows["aaaa"].purged_at is not None
    assert rows["bbbb"].purged_at is None
    assert rows["cccc"].purged_at is None


async def test_purge_tolerates_unparseable_expiry(db_session, vault):
    await _escrow(db_session)
    row = (await db_session.execute(select(CertificateKeyEscrow))).scalar_one()
    row.not_after = "not-a-date"
    await db_session.commit()

    assert await CertificateEscrowService(db_session).purge_expired() == 0
    assert vault.deleted == []


async def test_reconcile_is_a_no_op_when_disabled(db_session, monkeypatch):
    monkeypatch.setattr(settings, "CERT_KEY_ESCROW_ENABLED", False)
    assert await CertificateEscrowService(db_session).reconcile() == {"backfilled": 0, "purged": 0}
