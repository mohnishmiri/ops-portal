"""PKCS#12 → Java KeyStore (JKS) conversion — pure Python, no C extensions.

Implements just enough of the legacy JKS format (magic 0xFEEDFEED, version 2)
to produce a PrivateKeyEntry keystore that Java 8+ can open.  Only the write
path is needed; reading JKS/JCEKS files is not used here.

Key-protection algorithm: Sun's proprietary scheme from ``KeyProtector.java``
(OID 1.3.6.1.4.1.42.2.17.1.1), implemented with ``hashlib.sha1`` — no Twofish,
no C extensions, no MSVC required.

Key material is never logged; failures surface as ``ValueError`` for the caller
to translate into an HTTP response.
"""

from __future__ import annotations

import hashlib
import io
import os
import struct
import time

import structlog
from cryptography import x509
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography.x509.oid import NameOID

logger = structlog.get_logger(__name__)

DEFAULT_ALIAS = "certificate"
_ALIAS_MAX_LENGTH = 255

# ── JKS format constants ───────────────────────────────────────────────────────

_JKS_MAGIC = 0xFEEDFEED
_JKS_VERSION = 2
_JKS_TAG_PRIVATE_KEY = 1

# DER encoding of OID 1.3.6.1.4.1.42.2.17.1.1 (Sun JKS key-protection algorithm)
# Components: 1.3 → 43, then 6,1,4,1,42,2,17,1,1 (10 bytes total value)
_SUN_OID_DER = bytes(
    [
        0x06,
        0x0A,  # tag=OID, length=10
        0x2B,
        0x06,
        0x01,
        0x04,
        0x01,
        0x2A,
        0x02,
        0x11,
        0x01,
        0x01,
    ]
)

# Constant mixed into the keystore MAC (from JavaKeyStore.java)
_JKS_MAC_PHRASE = b"Mighty Aphrodite"


# ── Internal helpers ───────────────────────────────────────────────────────────


def _pw_bytes(password: str) -> bytes:
    """Password as 2-byte big-endian chars (Java's DataOutputStream convention)."""
    return password.encode("utf-16-be")


def _jks_protect_key(key_der: bytes, password: str) -> bytes:
    """Encrypt a PKCS#8 key with Sun's proprietary JKS obfuscation.

    Algorithm from ``sun.security.provider.KeyProtector#protect``:
      1. random salt (20 bytes)
      2. keystream = SHA1(pw + salt), SHA1(pw + prev), …
      3. ciphertext = key XOR keystream[:len(key)]
      4. check     = SHA1(pw + plain_key)
      result = salt + ciphertext + check
    """
    pw = _pw_bytes(password)
    salt = os.urandom(20)

    # Build keystream via chained SHA-1 digests
    xoring_key = hashlib.sha1(pw + salt).digest()
    keystream = bytearray(xoring_key)
    while len(keystream) < len(key_der):
        xoring_key = hashlib.sha1(pw + xoring_key).digest()
        keystream.extend(xoring_key)

    ciphertext = bytes(k ^ s for k, s in zip(key_der, keystream, strict=False))
    check = hashlib.sha1(pw + key_der).digest()
    return salt + ciphertext + check


def _der_len(n: int) -> bytes:
    """Minimal DER length encoding."""
    if n < 0x80:
        return bytes([n])
    if n < 0x100:
        return bytes([0x81, n])
    return bytes([0x82, (n >> 8) & 0xFF, n & 0xFF])


def _der_seq(content: bytes) -> bytes:
    return b"\x30" + _der_len(len(content)) + content


def _der_octet(content: bytes) -> bytes:
    return b"\x04" + _der_len(len(content)) + content


def _epki(protected_key: bytes) -> bytes:
    """Wrap the protected key bytes in EncryptedPrivateKeyInfo DER.

    ::

        EncryptedPrivateKeyInfo ::= SEQUENCE {
          encryptionAlgorithm  AlgorithmIdentifier,   -- Sun OID + NULL
          encryptedData        OCTET STRING
        }
    """
    alg_id = _der_seq(_SUN_OID_DER + b"\x05\x00")  # OID + NULL parameters
    enc_data = _der_octet(protected_key)
    return _der_seq(alg_id + enc_data)


def _write_utf(s: str) -> bytes:
    """Java DataOutputStream.writeUTF: 2-byte length prefix + UTF-8 payload."""
    encoded = s.encode("utf-8")
    return struct.pack(">H", len(encoded)) + encoded


# ── Public API ────────────────────────────────────────────────────────────────


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

    # Protect the private key with Sun's proprietary scheme, then wrap in EPKI DER
    protected = _jks_protect_key(key_der, store_password)
    epki_der = _epki(protected)

    # ── Serialize the JKS stream ───────────────────────────────────────────────
    buf = io.BytesIO()
    buf.write(struct.pack(">II", _JKS_MAGIC, _JKS_VERSION))
    buf.write(struct.pack(">I", 1))  # number of entries

    # Private key entry (tag 1)
    buf.write(struct.pack(">I", _JKS_TAG_PRIVATE_KEY))
    buf.write(_write_utf(entry_alias))
    buf.write(struct.pack(">Q", int(time.time() * 1000)))  # creation timestamp (ms)
    buf.write(struct.pack(">I", len(epki_der)))
    buf.write(epki_der)
    buf.write(struct.pack(">I", len(certs_der)))
    for cert_der in certs_der:
        buf.write(_write_utf("X.509"))
        buf.write(struct.pack(">I", len(cert_der)))
        buf.write(cert_der)

    # ── Append MAC: SHA1(pw_utf16be + "Mighty Aphrodite" + stream) ────────────
    pw = _pw_bytes(store_password)
    stream_bytes = buf.getvalue()
    mac = hashlib.sha1(pw + _JKS_MAC_PHRASE + stream_bytes).digest()
    buf.write(mac)

    blob = buf.getvalue()
    logger.info(
        "jks_keystore_built",
        alias=entry_alias,
        chain_length=len(certs_der),
        size_bytes=len(blob),
    )
    return blob
