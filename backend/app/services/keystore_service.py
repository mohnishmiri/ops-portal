"""PKCS#12 → Java KeyStore (JKS) conversion.

Keyfactor Command has no JKS download format, so the portal builds the keystore
itself from PFX material — either a live Keyfactor export or the escrowed key.

The legacy JKS container (magic ``0xFEEDFEED``) is produced deliberately rather
than a PKCS#12 file named ``.jks``: Java 8 cannot read PKCS#12 through a strict
``KeyStore.getInstance("JKS")``, and Java 8 is still in service here. On Java 9+
either container works, so legacy JKS is the option that covers the whole fleet.

Key material is never logged; failures surface as ``ValueError`` for the caller
to translate into an HTTP response.
"""

from __future__ import annotations

import jks
import structlog
from cryptography import x509
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography.x509.oid import NameOID

logger = structlog.get_logger(__name__)

DEFAULT_ALIAS = "certificate"
_ALIAS_MAX_LENGTH = 255


def sanitize_alias(value: str | None) -> str:
    """Normalize a JKS entry alias.

    Java lowercases JKS aliases and compares them case-insensitively, so the
    alias is lowercased here to match what an application will actually see.
    """
    alias = (value or "").strip().lower()[:_ALIAS_MAX_LENGTH]
    return alias or DEFAULT_ALIAS


def _leaf_common_name(cert: x509.Certificate) -> str | None:
    try:
        attrs = cert.subject.get_attributes_for_oid(NameOID.COMMON_NAME)
    except Exception:  # pragma: no cover - malformed subject
        return None
    if not attrs:
        return None
    value = attrs[0].value
    return value if isinstance(value, str) else None


def pfx_to_jks(
    pfx_bytes: bytes,
    *,
    pfx_password: str,
    store_password: str,
    alias: str | None = None,
    include_chain: bool = True,
) -> bytes:
    """Convert PKCS#12 material into a legacy JKS keystore.

    ``store_password`` protects both the keystore integrity check and the
    private-key entry, which is what the recipient will use to open the file.
    When ``alias`` is omitted the certificate's common name is used, since that
    is the alias a deployment most likely expects to reference.
    """
    if not store_password:
        raise ValueError("a keystore password is required to build a JKS file")

    try:
        key, cert, chain = pkcs12.load_key_and_certificates(
            pfx_bytes, pfx_password.encode("utf-8") if pfx_password else None
        )
    except Exception as exc:
        # The exception text can echo key bytes, so only the type is recorded.
        raise ValueError(f"could not read the PKCS#12 material ({type(exc).__name__})") from exc

    if key is None or cert is None:
        raise ValueError("the PKCS#12 material has no private key or certificate")

    key_der = key.private_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    # Leaf first, then the issuing chain — the order Java expects when it walks
    # the entry's certificate chain.
    certs_der = [cert.public_bytes(serialization.Encoding.DER)]
    if include_chain:
        certs_der.extend(c.public_bytes(serialization.Encoding.DER) for c in (chain or []))

    entry_alias = sanitize_alias(alias or _leaf_common_name(cert))
    entry = jks.PrivateKeyEntry.new(entry_alias, certs_der, key_der, "pkcs8")
    keystore = jks.KeyStore.new("jks", [entry])

    try:
        blob = keystore.saves(store_password)
    except Exception as exc:
        raise ValueError(f"could not serialize the JKS keystore ({type(exc).__name__})") from exc

    logger.info(
        "jks_keystore_built",
        alias=entry_alias,
        chain_length=len(certs_der),
        size_bytes=len(blob),
    )
    return blob
