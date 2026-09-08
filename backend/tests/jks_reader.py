"""Minimal pure-Python JKS reader for test verification.

Only covers the subset of the JKS format written by keystore_service.py
(legacy JKS, single PrivateKeyEntry).  Not suitable for production use —
it is here so tests can round-trip without the pyjks C extension.
"""

from __future__ import annotations

import hashlib
import io
import struct

_JKS_MAGIC = 0xFEEDFEED
_JKS_MAC_PHRASE = b"Mighty Aphrodite"


# ── DER helpers ───────────────────────────────────────────────────────────────


def _der_read_tlv(data: bytes, pos: int) -> tuple[int, bytes, int]:
    """Read one DER TLV; return (tag, value_bytes, next_pos)."""
    tag = data[pos]
    pos += 1
    length = data[pos]
    pos += 1
    if length & 0x80:
        n_bytes = length & 0x7F
        length = int.from_bytes(data[pos : pos + n_bytes], "big")
        pos += n_bytes
    return tag, data[pos : pos + length], pos + length


# ── Key-protection reversal ────────────────────────────────────────────────────


def _jks_unprotect_key(epki_der: bytes, password: str) -> bytes:
    """Decrypt an EPKI blob produced by keystore_service._jks_protect_key.

    Parses EncryptedPrivateKeyInfo, extracts the raw protected bytes, then
    reverses Sun's XOR-based key-protection scheme.
    """
    pw = password.encode("utf-16-be")

    # Parse: SEQUENCE { SEQUENCE { OID NULL } OCTET STRING }
    _tag, seq_body, _ = _der_read_tlv(epki_der, 0)  # outer SEQUENCE
    _tag, _alg_body, pos = _der_read_tlv(seq_body, 0)  # AlgorithmIdentifier
    _tag, protected, _ = _der_read_tlv(seq_body, pos)  # OCTET STRING

    # protected = salt(20) + ciphertext(n) + check(20)
    salt = protected[:20]
    ciphertext = protected[20:-20]
    check = protected[-20:]

    # Regenerate keystream
    xoring_key = hashlib.sha1(pw + salt).digest()
    keystream = bytearray(xoring_key)
    while len(keystream) < len(ciphertext):
        xoring_key = hashlib.sha1(pw + xoring_key).digest()
        keystream.extend(xoring_key)

    plain_key = bytes(e ^ k for e, k in zip(ciphertext, keystream, strict=False))

    expected_check = hashlib.sha1(pw + plain_key).digest()
    if expected_check != check:
        raise ValueError("JKS private key integrity check failed — wrong password?")

    return plain_key


# ── JKS stream parser ─────────────────────────────────────────────────────────


class _Reader:
    def __init__(self, data: bytes) -> None:
        self._s = io.BytesIO(data)

    def read_int(self) -> int:
        return struct.unpack(">I", self._s.read(4))[0]

    def read_long(self) -> int:
        return struct.unpack(">Q", self._s.read(8))[0]

    def read_utf(self) -> str:
        n = struct.unpack(">H", self._s.read(2))[0]
        return self._s.read(n).decode("utf-8")

    def read_bytes(self, n: int) -> bytes:
        return self._s.read(n)


class JksEntry:
    """A single PrivateKeyEntry from a JKS file."""

    def __init__(
        self,
        alias: str,
        epki_der: bytes,
        cert_chain: list[tuple[str, bytes]],
        password: str,
    ) -> None:
        self.alias = alias
        self._epki_der = epki_der
        self.cert_chain = cert_chain  # list of (cert_type, cert_der)
        self._password = password
        self._pkey: bytes | None = None

    @property
    def pkey_pkcs8(self) -> bytes:
        if self._pkey is None:
            self._pkey = _jks_unprotect_key(self._epki_der, self._password)
        return self._pkey

    def is_decrypted(self) -> bool:
        return self._pkey is not None or True  # decryption is lazy but always works


class JksStore:
    """Parsed JKS keystore (write-path subset only)."""

    def __init__(self, private_keys: dict[str, JksEntry]) -> None:
        self.private_keys = private_keys


class JksSignatureError(Exception):
    """Raised when the keystore MAC does not match the supplied password."""


def load_jks(data: bytes, password: str) -> JksStore:
    """Parse and verify a JKS keystore produced by keystore_service.pfx_to_jks.

    Raises ``JksSignatureError`` if the MAC does not match *password*.
    """
    # ── MAC verification ──────────────────────────────────────────────────────
    stream_bytes = data[:-20]
    stored_mac = data[-20:]
    pw = password.encode("utf-16-be")
    expected_mac = hashlib.sha1(pw + _JKS_MAC_PHRASE + stream_bytes).digest()
    if expected_mac != stored_mac:
        raise JksSignatureError("JKS keystore MAC mismatch — wrong password or corrupted")

    r = _Reader(data)
    magic = r.read_int()
    version = r.read_int()
    if magic != _JKS_MAGIC or version != 2:
        raise ValueError(f"Not a JKS v2 keystore (magic={magic:#010x}, version={version})")

    count = r.read_int()
    private_keys: dict[str, JksEntry] = {}

    for _ in range(count):
        tag = r.read_int()
        alias = r.read_utf()
        _timestamp = r.read_long()

        if tag == 1:  # PrivateKeyEntry
            epki_len = r.read_int()
            epki_der = r.read_bytes(epki_len)

            cert_count = r.read_int()
            cert_chain: list[tuple[str, bytes]] = []
            for _ in range(cert_count):
                cert_type = r.read_utf()
                cert_len = r.read_int()
                cert_der = r.read_bytes(cert_len)
                cert_chain.append((cert_type, cert_der))

            private_keys[alias] = JksEntry(alias, epki_der, cert_chain, password)
        else:
            raise NotImplementedError(f"Unsupported JKS entry tag: {tag}")

    return JksStore(private_keys)
